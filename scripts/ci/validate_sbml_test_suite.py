#!/usr/bin/env python3
"""Run BNG3's SBML round-trip gate over the official SBML Test Suite.

This checks the canonical semantic and stochastic SBML cases from a pinned
suite checkout.  It validates source and generated XML, imports each case
through the modern Atomizer and C++ network generator, writes SBML, reimports
that output, and checks the native C++ SBML reader's species/reaction counts.
It is an import/round-trip gate, not a claim of numerical SBML Test Suite
simulation conformance.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import json
import math
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

VERSION_PRIORITY = ("l3v2", "l3v1", "l2v5", "l2v4", "l2v3", "l2v2", "l2v1", "l1v2")
NUMERICAL_COMPARISON_ATOL_FLOOR = 5e-12
# BNG3 and libRoadRunner use separate CVODE wrappers and evaluate assignment
# rules/dense output at different points. Use one documented cross-engine
# relative floor instead of case-specific tolerances.
# libRoadRunner and BNG3 use independent CVODE builds and Jacobian paths;
# retain a small model-scale floor for cross-engine dense-output differences.
NUMERICAL_COMPARISON_RTOL_FLOOR = 1e-5
UNSUPPORTED_MARKERS = (
    "unsupported",
    "not representable",
    "not executable",
    "not implemented",
    "dropped",
    "cannot be represented",
    "not losslessly representable",
    "gcd(",
    "lcm(",
    "notanumber",
)


def _validate_xml(text: str, label: str) -> dict[str, Any]:
    try:
        import libsbml
    except ImportError:
        ET.fromstring(text)
        return {"passed": True, "validator": "xml.etree"}
    document = libsbml.readSBMLFromString(text)
    errors = int(document.getNumErrors())
    if errors:
        messages = [
            document.getError(index).getMessage() for index in range(min(errors, 5))
        ]
        raise RuntimeError(f"{label} has {errors} libSBML error(s): {messages}")
    consistency_errors = int(document.checkInternalConsistency())
    if consistency_errors:
        raise RuntimeError(
            f"{label} has {consistency_errors} libSBML consistency error(s)"
        )
    return {"passed": True, "validator": "libsbml", "errors": errors}


def _simulate_and_compare(
    cpp_model: Any,
    output_path: Path,
    *,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    function_names: set[str] | None = None,
) -> dict[str, Any]:
    """Compare BNG3/CVODE observables with libRoadRunner on one time grid."""

    try:
        import roadrunner
        from bionetgen import BioNetGenModel
    except ImportError as exc:
        raise RuntimeError(
            "libRoadRunner is required for direct numerical comparison"
        ) from exc
    bng_result = BioNetGenModel(cpp_model).simulate(
        method="ode",
        t_start=0.0,
        t_end=t_end,
        n_steps=n_steps,
        rtol=rtol,
        atol=atol,
    )
    series = dict(bng_result.observables)
    function_values = getattr(bng_result, "functions", {}) or {}
    if function_names is None:
        series.update(function_values)
    else:
        series.update(
            {
                name: values
                for name, values in function_values.items()
                if name in function_names
            }
        )
    names = list(series)
    bng_time = np.asarray(bng_result.time, dtype=float)
    bng_values = {name: np.asarray(series[name], dtype=float) for name in names}
    rr = roadrunner.RoadRunner(str(output_path))
    integrator = rr.integrator
    if integrator.hasValue("relative_tolerance"):
        integrator.setValue("relative_tolerance", rtol)
    if integrator.hasValue("absolute_tolerance"):
        integrator.setValue("absolute_tolerance", atol)
    available = set(rr.getAssignmentRuleIds())

    def sbml_id(name: str) -> str:
        valid = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
        if valid and valid[0].isdigit():
            valid = "_" + valid
        return valid or "species"

    selected_names = []
    missing = []
    for name in names:
        safe_name = sbml_id(name)
        # The C++ SBML writer prefixes a function when its source name
        # collides with a generated network species or parameter ID.
        candidates = [
            safe_name,
            "obs_" + safe_name,
            "func_" + safe_name,
            "param_" + safe_name,
        ]
        selected = next(
            (candidate for candidate in candidates if candidate in available), None
        )
        if selected is None:
            missing.append(name)
        else:
            selected_names.append(selected)
    if missing:
        raise RuntimeError(
            "written SBML is missing observable assignment rules: "
            + ", ".join(missing[:10])
        )
    rr.timeCourseSelections = ["time", *selected_names]
    rr_values = np.asarray(rr.simulate(0.0, t_end, n_steps + 1), dtype=float)
    expected_shape = (len(bng_time), len(names) + 1)
    if rr_values.ndim != 2 or rr_values.shape != expected_shape:
        raise RuntimeError(
            f"libRoadRunner returned shape {rr_values.shape}, expected {expected_shape}"
        )
    if not np.allclose(rr_values[:, 0], bng_time, rtol=0.0, atol=max(atol, 1e-12)):
        raise RuntimeError("BNG3 and libRoadRunner produced different time grids")
    comparison_scale = max(
        [
            *(
                float(np.max(np.abs(values)))
                for values in bng_values.values()
                if values.size
            ),
            *(
                float(np.max(np.abs(rr_values[:, index])))
                for index in range(1, rr_values.shape[1])
                if rr_values.shape[0]
            ),
            0.0,
        ]
    )
    comparisons: dict[str, dict[str, Any]] = {}
    failed = []
    for index, name in enumerate(names, start=1):
        left = bng_values[name]
        right = rr_values[:, index]
        if left.shape != right.shape:
            raise RuntimeError(f"observable {name!r} returned mismatched shapes")
        finite = bool(np.isfinite(left).all() and np.isfinite(right).all())
        difference = np.abs(left - right)
        scale = max(
            float(np.max(np.abs(left))) if left.size else 0.0,
            float(np.max(np.abs(right))) if right.size else 0.0,
        )
        # BNG3 and libRoadRunner both use CVODE, but their dense-output and
        # RHS evaluation paths differ. Keep a small global floor for
        # cross-engine round-trip comparison.
        # Use one model-wide reference scale. A small product/side species
        # inherits the same absolute CVODE error as its larger reactant, so a
        # per-observable relative tolerance would reject valid parity.
        tolerance = max(
            atol + rtol * scale,
            NUMERICAL_COMPARISON_ATOL_FLOOR
            + NUMERICAL_COMPARISON_RTOL_FLOOR * comparison_scale,
        )
        max_abs = float(np.max(difference)) if difference.size else 0.0
        scaled_error = max_abs / tolerance if tolerance else math.inf
        passed = finite and max_abs <= tolerance
        if not passed:
            failed.append(name)
        comparisons[name] = {
            "finite": finite,
            "max_abs_difference": max_abs,
            "tolerance": tolerance,
            "max_scaled_error": scaled_error,
            "passed": passed,
        }
    if failed:
        return {
            "passed": False,
            "error": (
                "BNG3 CVODE/libRoadRunner observable mismatch: "
                + ", ".join(failed[:10])
            ),
            "method_bngl": "BNG3 CVODE (simulate method='ode')",
            "method_sbml": "libRoadRunner CVODE",
            "roadrunner_version": getattr(roadrunner, "__version__", None),
            "t_start": 0.0,
            "t_end": t_end,
            "n_steps": n_steps,
            "rtol": rtol,
            "atol": atol,
            "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
            "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
            "comparison_reference_scale": comparison_scale,
            "observable_count": len(names),
            "sbml_observable_ids": dict(zip(names, selected_names)),
            "failed_observables": failed,
            "observables": comparisons,
        }
    return {
        "passed": True,
        "method_bngl": "BNG3 CVODE (simulate method='ode')",
        "method_sbml": "libRoadRunner CVODE",
        "roadrunner_version": getattr(roadrunner, "__version__", None),
        "t_start": 0.0,
        "t_end": t_end,
        "n_steps": n_steps,
        "rtol": rtol,
        "atol": atol,
        "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
        "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
        "comparison_reference_scale": comparison_scale,
        "observable_count": len(names),
        "sbml_observable_ids": dict(zip(names, selected_names)),
        "observables": comparisons,
    }


def _case_files(suite_dir: Path, categories: list[str]) -> list[dict[str, Any]]:
    cases = []
    for category in categories:
        root = suite_dir / "cases" / category
        if not root.is_dir():
            continue
        for case_dir in sorted(root.iterdir()):
            if not case_dir.is_dir() or not re.fullmatch(r"\d{5}", case_dir.name):
                continue
            source = next(
                (
                    case_dir / f"{case_dir.name}-sbml-{version}.xml"
                    for version in VERSION_PRIORITY
                    if (case_dir / f"{case_dir.name}-sbml-{version}.xml").exists()
                ),
                None,
            )
            if source is not None:
                cases.append(
                    {
                        "category": category,
                        "id": case_dir.name,
                        "version": source.stem.rsplit("-", 1)[-1],
                        "path": source,
                    }
                )
    return cases


def _classify_error(message: str) -> str:
    lower = message.lower()
    return (
        "unsupported"
        if any(marker in lower for marker in UNSUPPORTED_MARKERS)
        else "failed"
    )


def _warning_limitations(warnings: list[dict[str, Any]]) -> list[str]:
    return [
        str(warning["message"])
        for warning in warnings
        if any(
            marker in str(warning["message"]).lower() for marker in UNSUPPORTED_MARKERS
        )
    ]


def _simulation_limitations(warnings: list[dict[str, Any]]) -> list[str]:
    """Return warnings that prevent an executable numerical claim.

    ``approximated`` is intentionally a hard boundary here.  The parser uses
    that severity for source constructs such as variable stoichiometry and
    lossy MathML that can be rendered into BNGL text but cannot be claimed
    equivalent by this numerical gate.  Informational unit-scale notes are
    retained because the parser deliberately preserves the source numeric
    scale in that case.
    """

    limitations = []
    for warning in warnings:
        message = str(warning["message"])
        if (
            warning["severity"] in {"dropped", "approximated"}
            and warning.get("category") != "units"
        ):
            limitations.append(message)
    return limitations


def _event_translation_limitations(bngl: str) -> list[str]:
    """Return explicit diagnostics for events the BNGL action lowering rejected."""

    marker = "# Events NOT simulated"
    if marker not in bngl:
        return []
    details = []
    in_notes = False
    for line in bngl.splitlines():
        if line.strip() == marker:
            in_notes = True
            continue
        if in_notes and line.startswith("# ============================"):
            break
        if in_notes and line.startswith("#") and line.strip() != "#":
            details.append(line.lstrip("# "))
    detail = " | ".join(details[:8])
    return [
        "Generated BNGL retained untranslated SBML event(s); "
        "state-dependent or dynamic event scheduling is outside the BNGL action engine."
        + (f" Details: {detail}" if detail else "")
    ]


def _warnings(model: Any) -> list[dict[str, Any]]:
    return [
        {
            "category": warning.category,
            "message": warning.message,
            "severity": warning.severity,
        }
        for warning in model.import_warnings
    ]


def _merge_generated_warnings(
    source_warnings: list[dict[str, Any]], generated_warnings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge writer diagnostics, replacing parser-only event summaries."""

    if any(warning.get("category") == "event" for warning in generated_warnings):
        source_warnings = [
            warning for warning in source_warnings if warning.get("category") != "event"
        ]
    for warning in generated_warnings:
        if warning not in source_warnings:
            source_warnings.append(warning)
    return source_warnings


def _unsupported_causes(reason: str) -> list[str]:
    """Normalize an unsupported reason into auditable semantic cause labels."""

    lower = str(reason or "").lower()
    causes: list[str] = []
    for package in (
        "comp",
        "fbc",
        "qual",
        "spatial",
        "arrays",
        "distrib",
        "dyn",
        "multi",
    ):
        if f'"{package}" package' in lower or f"package:{package}" in lower:
            causes.append(f"package:{package}")
    if "event" in lower:
        causes.append("events")
    if "algebraic rule" in lower:
        causes.append("algebraic_rules")
    if "assignment rule targets species" in lower or "speciesassignmentrule" in lower:
        causes.append("species_assignment_rules")
    if "stoichiometr" in lower:
        causes.append("stoichiometry")
    if "fast-equilibrium" in lower or "marked fast" in lower:
        causes.append("fast_reactions")
    if "conversionfactor" in lower or "conversion factor" in lower:
        causes.append("conversion_factors")
    if "reaction-local" in lower or "no bngl-wide scope" in lower:
        causes.append("local_scope")
    if any(
        marker in lower
        for marker in (
            "mathml",
            "treated as rational",
            "gcd(",
            "lcm(",
            "rateof",
            "delay",
        )
    ):
        causes.append("mathml")
    if "constraint" in lower:
        causes.append("constraints")
    if "negative numeric rate" in lower or "nonnegative reaction rate" in lower:
        causes.append("negative_rates")
    if "no species" in lower or "no species or rate-rule" in lower:
        causes.append("no_state_variables")
    if "no reactants or products" in lower:
        causes.append("reaction_participants")
    if not causes:
        causes.append("other")
    return list(dict.fromkeys(causes))


def _record_ref(record: dict[str, Any]) -> str:
    category = str(record.get("category", "")).strip()
    identifier = str(record.get("id", "")).strip()
    return f"{category}/{identifier}" if category else identifier


def _stoichiometry_subcauses(reason: str) -> list[str]:
    """Split the broad stoichiometry boundary into semantic subcauses."""

    lower = str(reason or "").lower()
    subcauses: list[str] = []
    if "variable stoichiometry" in lower or "stoichiometrymath" in lower:
        subcauses.append("dynamic_or_stoichiometryMath")
    raw_values = re.findall(
        r"unsupported stoichiometry\s+(-?(?:\d+(?:\.\d*)?|\.\d+))", lower
    )
    if any(raw.startswith("-") for raw in raw_values):
        subcauses.append("constant_negative")
    if any(
        not raw.startswith("-") and abs(float(raw) - round(float(raw))) > 1e-12
        for raw in raw_values
    ):
        subcauses.append("constant_noninteger")
    if any(
        not raw.startswith("-") and abs(float(raw) - round(float(raw))) <= 1e-12
        for raw in raw_values
    ) and any(float(raw) > 100 for raw in raw_values):
        subcauses.append("constant_integer_above_expansion_limit")
    if "non-integer reaction stoichiometry" in lower:
        subcauses.append("constant_noninteger")
    if "above the bngl expansion limit" in lower:
        subcauses.append("constant_integer_above_expansion_limit")
    if "stoichiometr" in lower and not subcauses:
        subcauses.append("unclassified_stoichiometry")
    return list(dict.fromkeys(subcauses))


def _unsupported_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach cause labels and return counts, intersections, and exact IDs."""

    by_cause: dict[str, list[str]] = {}
    by_cause_records: dict[str, list[str]] = {}
    by_intersection: dict[tuple[str, ...], list[str]] = {}
    cardinality: dict[str, int] = {}
    stoichiometry_subcauses: dict[str, list[str]] = {}
    unsupported = []
    for record in records:
        if record.get("status") != "unsupported":
            continue
        reason = str(record.get("unsupported_reason") or record.get("error", ""))
        if reason and not record.get("unsupported_reason"):
            record["unsupported_reason"] = reason
        causes = _unsupported_causes(reason)
        record["unsupported_causes"] = causes
        subcauses = _stoichiometry_subcauses(reason)
        record["unsupported_subcauses"] = (
            {"stoichiometry": subcauses} if "stoichiometry" in causes else {}
        )
        reference = _record_ref(record)
        unsupported.append(record)
        unique_causes = tuple(sorted(set(causes)))
        cardinality[str(len(unique_causes))] = (
            cardinality.get(str(len(unique_causes)), 0) + 1
        )
        by_intersection.setdefault(unique_causes, []).append(reference)
        for cause in causes:
            by_cause.setdefault(cause, []).append(str(record.get("id", "")))
            by_cause_records.setdefault(cause, []).append(reference)
        for subcause in subcauses:
            stoichiometry_subcauses.setdefault(subcause, []).append(reference)
    return {
        "record_count": len(unsupported),
        "by_cause": {
            cause: {
                "count": len(ids),
                "ids": ids,
                "records": by_cause_records[cause],
            }
            for cause, ids in sorted(by_cause.items())
        },
        "stoichiometry_subsummary": {
            "record_count": sum(
                "stoichiometry" in record.get("unsupported_causes", [])
                for record in unsupported
            ),
            "by_subcause": {
                subcause: {
                    "count": len(references),
                    "records": references,
                }
                for subcause, references in sorted(stoichiometry_subcauses.items())
            },
        },
        "intersection_summary": {
            "record_count": len(unsupported),
            "cause_cardinality": dict(
                sorted(cardinality.items(), key=lambda item: int(item[0]))
            ),
            "by_cause_set": {
                " + ".join(cause_set) if cause_set else "none": {
                    "count": len(references),
                    "records": references,
                }
                for cause_set, references in sorted(
                    by_intersection.items(), key=lambda item: (len(item[0]), item[0])
                )
            },
            "pairwise": {
                " + ".join(pair): {
                    "count": sum(
                        set(pair).issubset(set(record.get("unsupported_causes", [])))
                        for record in unsupported
                    ),
                    "records": [
                        _record_ref(record)
                        for record in unsupported
                        if set(pair).issubset(set(record.get("unsupported_causes", [])))
                    ],
                }
                for pair in sorted(
                    {
                        pair
                        for record in unsupported
                        for pair in itertools.combinations(
                            sorted(set(record.get("unsupported_causes", []))), 2
                        )
                    }
                )
            },
        },
    }


def _validate_case(
    case: dict[str, Any],
    cpp: Any,
    work_dir: Path,
    simulation_t_end: float,
    simulation_n_steps: int,
    simulation_rtol: float,
    simulation_atol: float,
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import (
        Atomizer,
        SBMLParser,
        source_metadata_payload,
        source_metadata_summary,
    )
    from bionetgen.atomizer.modern.types import standardize_name

    source_path = Path(case["path"])
    sbml = source_path.read_text(encoding="utf-8-sig")
    record: dict[str, Any] = {
        "category": case["category"],
        "id": case["id"],
        "version": case["version"],
        "source": str(source_path),
    }
    try:
        record["source_xml"] = _validate_xml(sbml, "source SBML")
        parsed = SBMLParser().parse(sbml)
        record["source_model"] = {
            "species": len(parsed.species),
            "reactions": len(parsed.reactions),
            "warnings": _warnings(parsed),
            "metadata": source_metadata_summary(parsed),
        }
        source_metadata = source_metadata_payload(parsed)
        atomizer = Atomizer(atomize=False, quiet_mode=True)
        atomized = atomizer.atomize(sbml)
        if not atomized.success:
            raise RuntimeError(atomized.error or "modern Atomizer returned failure")
        source_warnings = record["source_model"]["warnings"]
        source_warnings = _merge_generated_warnings(
            source_warnings, _warnings(atomizer.model)
        )
        record["source_model"]["warnings"] = source_warnings
        source_limitations = [
            *_simulation_limitations(source_warnings),
            *_warning_limitations(source_warnings),
            *_event_translation_limitations(atomized.bngl),
        ]
        if not parsed.species and not any(rule.type == "rate" for rule in parsed.rules):
            source_limitations.append(
                "SBML model has no species or rate-rule state variable for a "
                "BNGL network/simulation round-trip."
            )
        if source_limitations:
            record["status"] = "unsupported"
            record["unsupported_reason"] = " ".join(source_limitations)
            record["simulation_comparison"] = {
                "passed": False,
                "skipped": True,
                "reason": record["unsupported_reason"],
                "method_bngl": "BNG3 CVODE",
                "method_sbml": "libRoadRunner CVODE",
            }
            record["core_passed"] = False
            return record
        cpp_model = cpp.parse_string(atomized.bngl)
        network = cpp.generate_network(cpp_model, max_iter=100)
        record["generated_network"] = {
            "species": network.num_species,
            "reactions": network.num_reactions,
        }

        output_path = work_dir / f"{case['category']}_{case['id']}.xml"
        cpp.io.write_sbml(
            cpp_model,
            network,
            str(output_path),
            source_metadata=source_metadata,
        )
        output_text = output_path.read_text(encoding="utf-8")
        record["written_xml"] = _validate_xml(output_text, "written SBML")
        reimport_model = SBMLParser().parse(output_text)
        record["reimport_model"] = {
            "species": len(reimport_model.species),
            "reactions": len(reimport_model.reactions),
            "warnings": _warnings(reimport_model),
            "metadata": source_metadata_summary(reimport_model),
        }
        record["metadata_roundtrip"] = {
            "source": record["source_model"].get("metadata", {}),
            "reimport": record["reimport_model"].get("metadata", {}),
            "status": (
                "not_present"
                if not source_metadata
                else (
                    "preserved"
                    if reimport_model.source_metadata_payload == source_metadata
                    else "dropped"
                )
            ),
            "payloadPresent": bool(reimport_model.source_metadata_payload),
            "payloadMatch": bool(
                source_metadata
                and reimport_model.source_metadata_payload == source_metadata
            ),
        }
        reimport = Atomizer(atomize=False, quiet_mode=True).atomize(output_text)
        if not reimport.success:
            raise RuntimeError(reimport.error or "round-trip Atomizer returned failure")
        reimport_network = cpp.generate_network(
            cpp.parse_string(reimport.bngl), max_iter=100
        )
        record["reimport_network"] = {
            "species": reimport_network.num_species,
            "reactions": reimport_network.num_reactions,
        }
        native = dict(cpp.io.read_sbml(str(output_path), False))
        record["native_reader"] = native
        if not native.get("success"):
            raise RuntimeError(
                native.get("error") or "native SBML reader returned failure"
            )
        if native["species_count"] != network.num_species:
            raise RuntimeError(
                f"native species count {native['species_count']} != {network.num_species}"
            )
        if native["reaction_count"] != network.num_reactions:
            raise RuntimeError(
                f"native reaction count {native['reaction_count']} != {network.num_reactions}"
            )

        # Empty SBML models are valid documents, but they have no BNGL state
        # variables or observables on which to run the requested numerical
        # parity gate. Keep this as an explicit model-class limitation rather
        # than allowing the zero-state simulator path to segfault.
        if network.num_species == 0:
            record["status"] = "unsupported"
            record["unsupported_reason"] = (
                "Zero-species SBML model has no BNGL state variables or "
                "observables for numerical comparison."
            )
            record["simulation_comparison"] = {
                "passed": False,
                "skipped": True,
                "reason": record["unsupported_reason"],
                "method_bngl": "BNG3 CVODE",
                "method_sbml": "libRoadRunner CVODE",
                "observable_count": 0,
            }
            record["core_passed"] = False
            return record

        warnings = record["source_model"]["warnings"]
        limitations = [
            *_simulation_limitations(warnings),
            *_warning_limitations(warnings),
        ]
        if limitations:
            record["status"] = "unsupported"
            record["unsupported_reason"] = " ".join(limitations)
        else:
            record["status"] = "passed"
        comparison = _simulate_and_compare(
            cpp_model,
            output_path,
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
            rtol=simulation_rtol,
            atol=simulation_atol,
            function_names={
                standardize_name(str(rule.variable))
                for rule in parsed.rules
                if rule.type == "assignment"
                and rule.variable
                and str(rule.variable) in parsed.species
            },
        )
        record["simulation_comparison"] = comparison
        if not comparison.get("passed", False):
            record["status"] = "failed"
            record["error"] = comparison.get("error", "numerical comparison failed")
        record["core_passed"] = record["status"] == "passed"
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        warning_limitations = _warning_limitations(
            record.get("source_model", {}).get("warnings", [])
        )
        record["status"] = _classify_error(
            message + " " + " ".join(warning_limitations)
        )
        record["core_passed"] = False
        record["error"] = message
        if record["status"] == "unsupported" and warning_limitations:
            record["unsupported_reason"] = " ".join(warning_limitations)
    return record


def _run_isolated_case(
    case: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    """Run one suite case in a bounded child process."""

    worker_json = args.json.parent / (
        f".worker-sbml-{case['category']}-{case['id']}.json"
    )
    worker_json.unlink(missing_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--suite-dir",
        str(args.suite_dir.resolve()),
        "--json",
        str(worker_json),
        "--categories",
        case["category"],
        "--only-case",
        f"{case['category']}/{case['id']}",
        "--worker",
        "--simulation-t-end",
        str(args.simulation_t_end),
        "--simulation-n-steps",
        str(args.simulation_n_steps),
        "--simulation-rtol",
        str(args.simulation_rtol),
        "--simulation-atol",
        str(args.simulation_atol),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=args.case_timeout,
        )
        if not worker_json.exists():
            raise RuntimeError(
                f"worker exited {completed.returncode} without a report: "
                f"{completed.stderr[-500:]}"
            )
        return json.loads(worker_json.read_text(encoding="utf-8"))["records"][0]
    except subprocess.TimeoutExpired:
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "timeout",
            "core_passed": False,
            "error": f"per-case timeout after {args.case_timeout}s",
        }
    except Exception as exc:
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "failed",
            "core_passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        worker_json.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--categories", nargs="+", default=["semantic", "stochastic"])
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--only-case", help="validate one case as CATEGORY/ID")
    parser.add_argument(
        "--isolate-cases",
        action="store_true",
        help="run each case in a bounded child process",
    )
    parser.add_argument(
        "--case-timeout", type=int, default=60, help="per-case timeout in seconds"
    )
    parser.add_argument(
        "--jobs", type=int, default=8, help="parallel isolated case workers"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulation-t-end", type=float, default=1.0)
    parser.add_argument("--simulation-n-steps", type=int, default=10)
    parser.add_argument("--simulation-rtol", type=float, default=1e-7)
    parser.add_argument("--simulation-atol", type=float, default=1e-12)
    args = parser.parse_args()

    try:
        commit = subprocess.check_output(
            ["git", "-C", str(args.suite_dir), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        commit = None
    cases = _case_files(args.suite_dir, args.categories)
    if args.only_case:
        try:
            only_category, only_id = args.only_case.split("/", 1)
        except ValueError as exc:
            raise SystemExit("--only-case must be CATEGORY/ID") from exc
        selected = [
            case
            for case in cases
            if case["category"] == only_category and case["id"] == only_id
        ]
        if not selected:
            raise SystemExit(f"case is not in the suite inventory: {args.only_case}")
    else:
        selected = cases[: args.max_cases] if args.max_cases else cases
    partial = bool(args.max_cases or args.only_case)
    try:
        import bionetgen._bionetgen_cpp as cpp
    except ImportError as exc:
        raise SystemExit(
            "BNG3 C++ extension is unavailable; set PYTHONPATH=python:build/cpp"
        ) from exc

    records = []
    with tempfile.TemporaryDirectory(prefix="bng3-sbml-suite-") as temp:
        work_dir = Path(temp)
        if args.isolate_cases and not args.worker:
            if args.jobs < 1:
                raise SystemExit("--jobs must be at least one")
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                records = list(
                    pool.map(lambda case: _run_isolated_case(case, args), selected)
                )
            for case, record in zip(selected, records):
                print(
                    f"{case['category']}/{case['id']}: {record['status'].upper()}",
                    flush=True,
                )
        else:
            for case in selected:
                record = _validate_case(
                    case,
                    cpp,
                    work_dir,
                    args.simulation_t_end,
                    args.simulation_n_steps,
                    args.simulation_rtol,
                    args.simulation_atol,
                )
                records.append(record)
                print(
                    f"{case['category']}/{case['id']}: {record['status'].upper()}",
                    flush=True,
                )

    unsupported_summary = _unsupported_summary(records)
    counts = {
        status: sum(record["status"] == status for record in records)
        for status in ("passed", "unsupported", "failed", "timeout")
    }
    by_category = {
        category: {
            status: sum(
                record["category"] == category and record["status"] == status
                for record in records
            )
            for status in ("passed", "unsupported", "failed", "timeout")
        }
        for category in args.categories
    }
    report = {
        "schema_version": 3,
        "suite_dir": str(args.suite_dir.resolve()),
        "suite_commit": commit,
        "writer_sbml_version": "L3V2",
        "categories": args.categories,
        "canonical_version_priority": list(VERSION_PRIORITY),
        "case_inventory": len(cases),
        "selected_cases": len(selected),
        "partial_run": partial,
        "counts": counts,
        "by_category": by_category,
        "records": records,
        "unsupported_summary": unsupported_summary,
        "sbml_unsupported_summary": unsupported_summary,
        "roundtrip_gate": "SBML XML validation + modern Atomizer/C++ network generation + C++ SBML writer + modern reimport + native C++ reader count check + BNG3 CVODE/libRoadRunner all-observable comparison",
        "simulation": {
            "t_start": 0.0,
            "t_end": args.simulation_t_end,
            "n_steps": args.simulation_n_steps,
            "rtol": args.simulation_rtol,
            "atol": args.simulation_atol,
            "comparison": "all generated BNGL observables on the same time grid",
            "engines": ["BNG3 CVODE", "libRoadRunner CVODE"],
        },
        "numerical_conformance": "SBML Test Suite reference-result conformance not run; direct BNG3/libRoadRunner parity is run",
        "core_passed": (
            not partial
            and counts["failed"] == 0
            and counts["unsupported"] == 0
            and counts["timeout"] == 0
        ),
        "supported_surface_passed": (
            not partial and counts["failed"] == 0 and counts["timeout"] == 0
        ),
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"cases={len(records)} passed={counts['passed']} "
        f"unsupported={counts['unsupported']} failed={counts['failed']} "
        f"timeouts={counts['timeout']} "
        f"core={'PASS' if report['core_passed'] else 'FAIL'}"
    )
    return 0 if report["core_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
