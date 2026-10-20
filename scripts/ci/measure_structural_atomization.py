#!/usr/bin/env python3
"""Measure structural atomization over a curated SBML corpus.

The script reports four metrics that answer different questions and are
therefore kept apart:

``translation``
    how many records translate to BNGL at all;
``equivalence``
    how many records produce the same generated species and reactions in
    the flat and the atomized translation, and (with ``--simulate``) the
    same deterministic trajectories;
``structural``
    how many species received a molecular interpretation, and how confident
    that interpretation was;
``ground_truth``
    not measurable on a real corpus; it is measured on the synthetic
    ground-truth set by the focused regression tests.

Usage::

    python scripts/ci/measure_structural_atomization.py \\
        --cache-dir /tmp/bng3-campaign/biomodels-cache \\
        --inventory-json /tmp/bng3-campaign/biomodels-baseline.json \\
        --json /tmp/bng3-campaign/agentG/structural-corpus.json
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))


def _load_inventory(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    inventory = payload.get("inventory")
    if isinstance(inventory, dict):
        return list(inventory.get("models") or [])
    if isinstance(inventory, list):
        return list(inventory)
    return list(payload.get("models") or [])


def _measure_one(
    sbml_text: str,
    model_timeout: float,
    simulate: bool,
) -> Dict[str, Any]:
    """Translate one model both ways and report the four metrics."""

    import bionetgen._bionetgen_cpp as cpp
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.model import BioNetGenModel

    result: Dict[str, Any] = {
        "translated": False,
        "error": None,
        "equivalence": "not-measured",
        "species_total": 0,
        "structural_species": 0,
        "elemental_species": 0,
        "confidence": {},
        "uncertain_species": 0,
        "equivalence_problems": [],
    }
    flat = Atomizer({"atomize": False, "quiet_mode": True}).atomize(sbml_text)
    atomized = Atomizer({"atomize": True, "quiet_mode": True}).atomize(sbml_text)
    result["translated"] = bool(flat.success and atomized.success)
    result["error"] = flat.error or atomized.error
    if not result["translated"]:
        result["equivalence"] = "not-translated"
        return result

    report = atomized.structural_inference or {}
    summary = dict(report.get("summary") or {})
    result["species_total"] = int(summary.get("species_total", 0) or 0)
    result["structural_species"] = int(summary.get("structural_species", 0) or 0)
    result["elemental_species"] = int(summary.get("elemental_species", 0) or 0)
    result["confidence"] = dict(summary.get("confidence") or {})
    result["uncertain_species"] = len(summary.get("uncertain_species") or [])

    problems: List[str] = []
    try:
        flat_network = cpp.generate_network(cpp.parse_string(flat.bngl), max_iter=100)
        atomized_network = cpp.generate_network(
            cpp.parse_string(atomized.bngl), max_iter=100
        )
        if flat_network.num_species != atomized_network.num_species:
            problems.append(
                f"species {flat_network.num_species} != "
                f"{atomized_network.num_species}"
            )
        if flat_network.num_reactions != atomized_network.num_reactions:
            problems.append(
                f"reactions {flat_network.num_reactions} != "
                f"{atomized_network.num_reactions}"
            )
        result["flat_species"] = flat_network.num_species
        result["atomized_species"] = atomized_network.num_species
        result["flat_reactions"] = flat_network.num_reactions
        result["atomized_reactions"] = atomized_network.num_reactions
    except Exception as exc:  # pragma: no cover - defensive
        problems.append(f"network generation failed: {exc}")

    if simulate and not problems:
        try:
            flat_model = BioNetGenModel(cpp.parse_string(flat.bngl))
            atomized_model = BioNetGenModel(cpp.parse_string(atomized.bngl))
            flat_result = flat_model.simulate(method="ode", t_end=5.0, n_steps=6)
            atomized_result = atomized_model.simulate(
                method="ode", t_end=5.0, n_steps=6
            )
            flat_observables = {
                name: [float(value) for value in values]
                for name, values in flat_result.observables.items()
            }
            atomized_observables = {
                name: [float(value) for value in values]
                for name, values in atomized_result.observables.items()
            }
            if sorted(flat_observables) != sorted(atomized_observables):
                problems.append("observable sets differ")
            else:
                worst = 0.0
                for name, values in flat_observables.items():
                    for left, right in zip(values, atomized_observables[name]):
                        worst = max(worst, abs(left - right))
                result["max_trajectory_difference"] = worst
                if worst > 1e-6:
                    problems.append(f"trajectory difference {worst:g}")
        except Exception as exc:  # pragma: no cover - defensive
            problems.append(f"simulation failed: {exc}")

    result["equivalence_problems"] = problems
    result["equivalence"] = "equivalent" if not problems else "different"
    return result


def _read_source(path: Path) -> Optional[str]:
    """Read an SBML source document, or ``None`` when it is not one."""

    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"<sbml" not in raw[:4096] and b"<SBML" not in raw[:4096]:
        return None
    return raw.decode("utf-8-sig", errors="replace")


def _worker(payload: Tuple[str, str, float, bool]) -> Dict[str, Any]:
    record_id, path, timeout, simulate = payload
    text = _read_source(Path(path))
    if text is None:
        return {
            "id": record_id,
            "filename": Path(path).name,
            "translated": False,
            "error": "not an SBML document",
            "equivalence": "not-applicable",
        }
    try:
        measured = _measure_one(text, timeout, simulate)
    except Exception:  # pragma: no cover - defensive
        measured = {
            "translated": False,
            "error": traceback.format_exc(limit=3),
            "equivalence": "not-translated",
        }
    measured["id"] = record_id
    measured["filename"] = Path(path).name
    return measured


def _run_isolated(
    record_id: str,
    path: Path,
    timeout: float,
    simulate: bool,
) -> Dict[str, Any]:
    """Measure one model in a child process with a hard timeout.

    Some corpus models make the translation itself run for a very long time.
    The corpus gate reports those records as timeouts; the measurement must
    not hang on them either.
    """

    import subprocess

    request = json.dumps(
        {
            "id": record_id,
            "path": str(path),
            "simulate": bool(simulate),
        }
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                request,
            ],
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return {
            "id": record_id,
            "filename": path.name,
            "translated": False,
            "error": f"model timeout after {timeout:g}s",
            "equivalence": "timeout",
        }
    if completed.returncode != 0:
        return {
            "id": record_id,
            "filename": path.name,
            "translated": False,
            "error": (completed.stderr or "worker failed").strip()[-2000:],
            "equivalence": "not-translated",
        }
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "id": record_id,
            "filename": path.name,
            "translated": False,
            "error": "worker produced no report",
            "equivalence": "not-translated",
        }


def _worker_entry(request: str) -> int:
    payload = json.loads(request)
    record = _worker(
        (
            str(payload.get("id", "")),
            str(payload.get("path", "")),
            120.0,
            bool(payload.get("simulate")),
        )
    )
    sys.stdout.write(json.dumps(record))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--inventory-json", default="")
    parser.add_argument("--json", default="")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model-timeout", type=float, default=120.0)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--worker", default="")
    args = parser.parse_args(argv)

    if args.worker:
        return _worker_entry(args.worker)

    cache_dir = Path(args.cache_dir)
    inventory = _load_inventory(args.inventory_json)
    if not inventory:
        candidates = sorted(cache_dir.glob("*.xml"))
        inventory = [{"id": path.name, "filename": path.name} for path in candidates]
    payloads: List[Tuple[str, str, float, bool]] = []
    missing: List[str] = []
    for entry in inventory:
        path = cache_dir / str(entry.get("filename", ""))
        if not path.is_file():
            missing.append(str(entry.get("id", "")))
            continue
        payloads.append(
            (
                str(entry.get("id", "")),
                str(path),
                args.model_timeout,
                bool(args.simulate),
            )
        )
    if args.limit:
        payloads = payloads[: args.limit]

    records: List[Dict[str, Any]] = []
    if args.jobs <= 1:
        for record_id, path, timeout, simulate in payloads:
            record = _run_isolated(record_id, Path(path), timeout, simulate)
            records.append(record)
            print(
                f"{record['id']}: {record['equivalence']} "
                f"structural={record.get('structural_species', 0)}"
                f"/{record.get('species_total', 0)}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as executor:
            futures = {
                executor.submit(
                    _run_isolated, record_id, Path(path), timeout, simulate
                ): record_id
                for record_id, path, timeout, simulate in payloads
            }
            for future in as_completed(futures):
                record = future.result()
                records.append(record)
                print(
                    f"{record['id']}: {record['equivalence']} "
                    f"structural={record.get('structural_species', 0)}"
                    f"/{record.get('species_total', 0)}",
                    flush=True,
                )

    records.sort(key=lambda item: str(item.get("id", "")))
    translated = [record for record in records if record.get("translated")]
    equivalent = [
        record for record in records if record.get("equivalence") == "equivalent"
    ]
    different = [
        record for record in records if record.get("equivalence") == "different"
    ]
    timed_out = [record for record in records if record.get("equivalence") == "timeout"]
    not_translated = [record for record in records if not record.get("translated")]
    not_applicable = [
        record for record in records if record.get("equivalence") == "not-applicable"
    ]
    confidence: Dict[str, int] = {}
    species_total = 0
    structural_total = 0
    uncertain_total = 0
    for record in records:
        species_total += int(record.get("species_total", 0) or 0)
        structural_total += int(record.get("structural_species", 0) or 0)
        uncertain_total += int(record.get("uncertain_species", 0) or 0)
        for key, value in (record.get("confidence") or {}).items():
            confidence[key] = confidence.get(key, 0) + int(value)
    summary = {
        "records_selected": len(payloads),
        "records_missing_from_cache": len(missing),
        "translation_passed": len(translated),
        "translation_failed": len(not_translated),
        "equivalence_equivalent": len(equivalent),
        "equivalence_different": len(different),
        "equivalence_timeout": len(timed_out),
        "not_applicable": len(not_applicable),
        "species_total": species_total,
        "structural_species": structural_total,
        "elemental_species": species_total - structural_total,
        "structural_fraction": (
            (structural_total / species_total) if species_total else 0.0
        ),
        "uncertain_species": uncertain_total,
        "confidence": confidence,
    }
    payload = {
        "summary": summary,
        "records": records,
        "missing": missing,
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
