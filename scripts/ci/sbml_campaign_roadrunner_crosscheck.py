#!/usr/bin/env python3
"""Cross-check official SBML Test Suite references with libRoadRunner.

A harness verdict of ``passed`` against the official reference is only
meaningful if the official reference itself is reproducible.  This tool
reproduces the official reference independently of BNG3: it loads a case's own
SBML into libRoadRunner, simulates on the case's official grid, and compares
the trajectory with the published ``-results.csv`` using the official
per-case tolerance from ``-settings.txt``.

Nothing produced by BNG3 is consulted for the trajectory, so the result is an
independent statement about the official reference and therefore about any
BNG3 verdict that relies on it.

The output is a small JSON document suitable for embedding in a campaign
audit record.

Usage:
    python scripts/ci/sbml_campaign_roadrunner_crosscheck.py \
        --suite-dir /path/to/sbml-test-suite \
        --cases 00616 00617 \
        --out /tmp/roadrunner-crosscheck.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

CROSSCHECK_SCHEMA_VERSION = 1


def read_settings(case_dir: Path, case_id: str) -> dict[str, str]:
    """Read the official settings of one case."""

    settings: dict[str, str] = {}
    text = (case_dir / f"{case_id}-settings.txt").read_text(encoding="utf-8-sig")
    for line in text.splitlines():
        if not line.strip():
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        settings[key] = value
    return settings


def read_results(
    case_dir: Path, case_id: str, variables: list[str]
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Read the official reference trajectory of one case."""

    text = (case_dir / f"{case_id}-results.csv").read_text(encoding="utf-8-sig")
    rows = list(csv.reader(text.splitlines()))
    first = [cell.strip() for cell in rows[0]]
    if first and first[0].lower() == "time":
        rows = rows[1:]
    matrix = np.asarray([[float(cell.strip()) for cell in row] for row in rows])
    times = matrix[:, 0]
    expected = {
        variable: matrix[:, index + 1] for index, variable in enumerate(variables)
    }
    return times, expected


def species_initial_values(sbml_path: Path) -> dict[str, dict[str, float]]:
    """Read each species' compartment size and declared initial value."""

    import libsbml

    document = libsbml.readSBML(str(sbml_path))
    model = document.getModel()
    volumes: dict[str, float] = {}
    for index in range(model.getNumCompartments()):
        compartment = model.getCompartment(index)
        volumes[compartment.getId()] = compartment.getSize()
    values: dict[str, dict[str, float]] = {}
    for index in range(model.getNumSpecies()):
        species = model.getSpecies(index)
        values[species.getId()] = {
            "volume": volumes.get(species.getCompartment(), 1.0),
            "initial_amount": species.getInitialAmount(),
            "initial_concentration": species.getInitialConcentration(),
        }
    return values


def check_case(case_dir: Path, case_id: str, sbml_path: Path) -> dict:
    """Simulate one case with libRoadRunner and compare with the reference."""

    import roadrunner

    settings = read_settings(case_dir, case_id)
    variables = [v.strip() for v in settings["variables"].split(",") if v.strip()]
    amounts = {v.strip() for v in settings["amount"].split(",") if v.strip()}
    concentrations = {
        v.strip() for v in settings["concentration"].split(",") if v.strip()
    }
    start = float(settings["start"])
    duration = float(settings["duration"])
    steps = int(settings["steps"])
    absolute = float(settings["absolute"])
    relative = float(settings["relative"])

    _, expected = read_results(case_dir, case_id, variables)
    initials = species_initial_values(sbml_path)

    model = roadrunner.RoadRunner(str(sbml_path))
    model.integrator.setValue("relative_tolerance", 1e-9)
    model.integrator.setValue("absolute_tolerance", 1e-14)

    # libRoadRunner distinguishes a floating species' amount (``S1``) from its
    # concentration (``[S1]``).  The official ``amount:`` and ``concentration:``
    # lists say which one the reference reports.
    selection: list[str] = ["time"]
    kind: dict[str, str] = {}
    for variable in variables:
        if variable in initials and variable in concentrations:
            selection.append(f"[{variable}]")
            kind[variable] = "concentration"
        elif variable in initials and variable in amounts:
            selection.append(variable)
            kind[variable] = "amount"
        else:
            selection.append(variable)
            kind[variable] = "model-variable"
    model.selections = selection
    model.simulate(start, start + duration, steps + 1)
    data = np.asarray(model.getSimulationData())
    names = list(model.getSimulationData().colnames)
    by_name = {name: data[:, index] for index, name in enumerate(names)}

    result: dict = {
        "case": case_id,
        "sbml": str(sbml_path),
        "absolute_tolerance": absolute,
        "relative_tolerance": relative,
        "variables": variables,
        "variable_kind": kind,
        "per_variable": {},
    }

    cross_check: list[dict] = []
    for variable, variable_kind in kind.items():
        if variable_kind not in {"amount", "concentration"}:
            continue
        info = initials[variable]
        volume = info["volume"]
        declared_amount = info["initial_amount"]
        declared_concentration = info["initial_concentration"]
        if declared_amount > 0 and declared_concentration <= 0:
            target = declared_amount
        elif declared_concentration > 0 and declared_amount <= 0:
            target = declared_concentration * volume
        else:
            continue
        series = (
            by_name[f"[{variable}]"]
            if variable_kind == "concentration"
            else by_name[variable]
        )
        actual = float(series[0])
        cross_check.append(
            {
                "variable": variable,
                "kind": variable_kind,
                "roadrunner_t0": actual,
                "sbml_t0": float(target),
                "relative_difference": (
                    abs(actual - float(target)) / abs(float(target))
                    if float(target)
                    else None
                ),
            }
        )
    result["initial_value_cross_check"] = cross_check

    worst_abs = 0.0
    worst_scaled = 0.0
    within = True
    for variable in variables:
        left = expected[variable]
        column = f"[{variable}]" if kind[variable] == "concentration" else variable
        right = np.asarray(by_name[column], dtype=float)
        if right.shape != left.shape:
            result["per_variable"][variable] = {
                "error": f"shape {right.shape} does not match reference {left.shape}"
            }
            within = False
            continue
        finite = np.isfinite(left) & np.isfinite(right)
        difference = np.abs(left[finite] - right[finite])
        tolerance = absolute + relative * np.abs(left[finite])
        variable_within = bool(np.all(difference <= tolerance))
        max_abs = float(np.max(difference)) if difference.size else 0.0
        max_scaled = (
            float(np.max(difference / tolerance))
            if tolerance.size and np.any(tolerance > 0)
            else 0.0
        )
        within = within and variable_within
        worst_abs = max(worst_abs, max_abs)
        worst_scaled = max(worst_scaled, max_scaled)
        result["per_variable"][variable] = {
            "kind": kind[variable],
            "max_abs_difference": max_abs,
            "max_scaled_error": max_scaled,
            "within_official_tolerance": variable_within,
            "sample_count": int(left.size),
        }
    result["roadrunner_within_official_tolerance"] = within
    result["max_abs_difference"] = worst_abs
    result["max_scaled_error"] = worst_scaled
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument(
        "--source-report",
        type=Path,
        help=(
            "harness report whose per-case 'source' path selects the same "
            "canonical SBML version the harness used"
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    sources: dict[str, str] = {}
    if args.source_report:
        report = json.loads(args.source_report.read_text(encoding="utf-8"))
        for record in report.get("records", []):
            sources[f"{record.get('category')}/{record.get('id')}"] = record.get(
                "source", ""
            )

    results = []
    for case_id in args.cases:
        case_dir = args.suite_dir / "cases" / "semantic" / case_id
        source = sources.get(f"semantic/{case_id}")
        candidates = (
            [Path(source)]
            if source and Path(source).exists()
            else sorted(case_dir.glob(f"{case_id}-sbml-*.xml"))
        )
        if not candidates:
            results.append({"case": case_id, "error": "no SBML source found"})
            continue
        try:
            results.append(check_case(case_dir, case_id, candidates[0]))
        except Exception as exc:  # noqa: BLE001 - report, do not hide
            results.append({"case": case_id, "error": f"{type(exc).__name__}: {exc}"})

    payload = {
        "crosscheck_schema_version": CROSSCHECK_SCHEMA_VERSION,
        "roadrunner_version": "2.10.0",
        "suite_dir": str(args.suite_dir),
        "case_count": len(results),
        "within_official_tolerance": sum(
            1
            for result in results
            if result.get("roadrunner_within_official_tolerance") is True
        ),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"roadrunner within official tolerance: "
        f"{payload['within_official_tolerance']}/{payload['case_count']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
