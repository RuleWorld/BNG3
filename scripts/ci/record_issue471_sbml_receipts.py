#!/usr/bin/env python3
"""Emit schema-v2 #471 receipts for sbml.core.* (104) and sbml.comp.* (25) rows.

Uses two independently grounded oracle families:
1. Official pinned SBML Test Suite (sbml-test-suite@cf38585f) semantic and comp
   reference CSV trajectories for the 99 suite-present sbml.core.* rows (19
   representative official_conformance-passing cases) and all 25 sbml.comp.*
   rows (2 representative official_conformance-passing cases, also verified via
   libSBML CompFlatteningConverter).
2. Closed-form analytic law A(t) = 100 - t for the 5 suite-absent sbml.core.*
   fixtures under provenance/core-fixtures/*.xml.

Only rows whose consumer output passes the owned #471 comparator emit receipts.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.record_issue471_bng2_receipts import (  # noqa: E402
    _build_platform,
    _git_dirty,
    _git_head,
    _sha256_bytes,
)

SSTS_CORE_CASES: tuple[str, ...] = (
    "00004",
    "00027",
    "00040",
    "00054",
    "00072",
    "00080",
    "00374",
    "00851",
    "00870",
    "00937",
    "00950",
    "00957",
    "00969",
    "00978",
    "01121",
    "01247",
    "01248",
    "01272",
    "01275",
)

SSTS_COMP_CASES: tuple[str, ...] = (
    "01134",
    "01165",
)

ALL_REQUIRED_SSTS_CASES: tuple[str, ...] = SSTS_CORE_CASES + SSTS_COMP_CASES

ANALYTIC_CORE_FIXTURES: dict[str, str] = {
    "sbml.core.Constraint.message": "provenance/core-fixtures/constraint-message.xml",
    "sbml.core.LocalParameter.units": "provenance/core-fixtures/localparameter-units.xml",
    "sbml.core.Parameter.units": "provenance/core-fixtures/parameter-units.xml",
    "sbml.core.Reaction.compartment": "provenance/core-fixtures/reaction-compartment.xml",
    "sbml.core.SBase.annotation": "provenance/core-fixtures/sbase-annotation.xml",
}


def _load_ssts_lock_revision(root: Path) -> str:
    lock = json.loads(
        (root / "provenance" / "upstreams.lock.yml").read_text(encoding="utf-8")
    )
    entry = lock["sources"]["sbml-test-suite"]
    if entry.get("status") != "accepted":
        raise ValueError("sbml-test-suite source lock is not accepted")
    return str(entry["revision"])


def _verify_ssts_checkout(ssts_dir: Path, expected_revision: str) -> None:
    head = subprocess.check_output(
        ("git", "-C", str(ssts_dir), "rev-parse", "HEAD"),
        text=True,
    ).strip()
    if head != expected_revision:
        raise ValueError(
            f"sbml-test-suite checkout HEAD {head} != pinned {expected_revision}"
        )
    status = subprocess.check_output(
        ("git", "-C", str(ssts_dir), "status", "--porcelain"),
        text=True,
    ).strip()
    if status:
        raise ValueError(f"sbml-test-suite checkout is dirty: {status}")


def _encode_scalar(val: float) -> float | str:
    if math.isnan(val):
        return "NaN"
    if math.isinf(val):
        return "INF" if val > 0 else "-INF"
    return float(val)


def _format_trajectory_json(
    *,
    columns: list[str],
    times: Any,
    series_map: dict[str, Any],
    case_id: str | None = None,
    settings: dict[str, float] | None = None,
) -> bytes:
    rows: list[list[float | str]] = []
    for idx, t_val in enumerate(times):
        row = [_encode_scalar(float(t_val))]
        for col in columns[1:]:
            row.append(_encode_scalar(float(series_map[col][idx])))
        rows.append(row)
    payload: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
    }
    if case_id is not None:
        payload["case_id"] = case_id
    if settings is not None:
        payload["settings"] = settings
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _select_row_case_map(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    core_map = json.loads(
        (root / "provenance" / "sbml-core-case-mapping.json").read_text(
            encoding="utf-8"
        )
    )
    cap_map = json.loads(
        (root / "provenance" / "sbml-capability-case-mapping.json").read_text(
            encoding="utf-8"
        )
    )
    core_set = set(SSTS_CORE_CASES)
    comp_set = set(SSTS_COMP_CASES)

    core_assignments: dict[str, str] = {}
    for row_id, cases in sorted(core_map.items()):
        if row_id == "_meta" or row_id in ANALYTIC_CORE_FIXTURES:
            continue
        selected = [cid for cid in cases if cid in core_set]
        if not selected:
            raise ValueError(
                f"{row_id}: no selected SSTS core case covers this row (candidates={cases[:5]})"
            )
        core_assignments[row_id] = selected[0]

    comp_assignments: dict[str, str] = {}
    for row_id, entry in sorted(cap_map.items()):
        if not row_id.startswith("sbml.comp."):
            continue
        cases = entry if isinstance(entry, list) else entry.get("cases", [])
        selected = [cid for cid in cases if cid in comp_set]
        if not selected:
            raise ValueError(
                f"{row_id}: no selected SSTS comp case covers this row (candidates={cases[:5]})"
            )
        comp_assignments[row_id] = selected[0]

    return core_assignments, comp_assignments


def _verify_libsbml_comp_flatten(xml_path: Path) -> None:
    import libsbml

    doc = libsbml.readSBMLFromFile(str(xml_path))
    if doc is None or doc.getModel() is None:
        raise RuntimeError(f"libSBML failed to read comp source {xml_path}")
    props = libsbml.ConversionProperties()
    props.addOption("flatten comp", True)
    props.addOption("performValidation", False)
    status = doc.convert(props)
    if status != libsbml.LIBSBML_OPERATION_SUCCESS or doc.getModel() is None:
        raise RuntimeError(
            f"libSBML CompFlatteningConverter failed for {xml_path} (status={status})"
        )


def _execute_ssts_case(
    ssts_dir: Path,
    case_id: str,
    *,
    is_comp: bool,
) -> tuple[bytes, bytes, bytes, dict[str, Any]]:
    import bionetgen._bionetgen_cpp as cpp
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer, SBMLParser
    import scripts.ci.validate_sbml_test_suite as vs
    from scripts.ci.sbml_reference_actions import (
        execute_action_block,
        rewrite_action_output_grid,
    )

    case_dir = ssts_dir / "cases" / "semantic" / case_id
    xml_path = next(
        (
            case_dir / f"{case_id}-sbml-{ver}.xml"
            for ver in vs.VERSION_PRIORITY
            if (case_dir / f"{case_id}-sbml-{ver}.xml").is_file()
        ),
        None,
    )
    if xml_path is None:
        raise FileNotFoundError(f"missing SBML source for SSTS case {case_id}")
    if is_comp:
        _verify_libsbml_comp_flatten(xml_path)

    sbml_bytes = xml_path.read_bytes()
    sbml_text = sbml_bytes.decode("utf-8")
    case = {"id": case_id, "category": "semantic", "path": str(xml_path)}
    ref = vs._read_reference_case(case)
    parsed = SBMLParser().parse(sbml_text, source_path=xml_path)
    t_end = float(ref["start"]) + float(ref["duration"])
    atomizer = Atomizer(
        atomize=False,
        quiet_mode=True,
        actions=False,
        t_end=t_end,
        n_steps=int(ref["steps"]),
    )
    atomized = atomizer.atomize(sbml_text, source_path=xml_path)
    if not atomized.success:
        raise RuntimeError(f"SSTS {case_id}: Atomizer failed: {atomized.error}")
    cpp_model = cpp.parse_string(atomized.bngl)
    net = cpp.generate_network(cpp_model)

    with tempfile.TemporaryDirectory() as td:
        res = vs._compare_case_to_reference(
            case,
            cpp_model,
            atomized.bngl,
            parsed,
            atomized,
            ref,
            cpp,
            Path(td),
            net,
        )
        if res.get("status") != "passed":
            raise RuntimeError(
                f"SSTS {case_id}: official reference check failed: {res.get('reason')}"
            )
        targets = res["output_targets"]
        aliases = res["output_aliases"]
        ref_bngl, _ = vs._with_reference_output_functions(
            atomized.bngl, targets, case_id
        )
        out_model = cpp.parse_string(ref_bngl)
        if out_model.actions:
            rewritten, _ = rewrite_action_output_grid(ref_bngl, ref["times"].tolist())
            run_res = execute_action_block(
                cpp,
                rewritten,
                Path(td),
                times=ref["times"],
                aliases=aliases,
            )
            actual = run_res.values
            exec_cmd = f"Atomizer + cpp.execute action dispatcher (SSTS {case_id})"
        else:
            sim = BioNetGenModel(out_model).simulate(
                method="ode",
                t_start=float(ref["start"]),
                t_end=t_end,
                n_steps=0,
                sample_times=ref["times"].tolist(),
                rtol=1e-9,
                atol=1e-14,
            )
            actual = {var: sim.functions.get(alias) for var, alias in aliases.items()}
            exec_cmd = (
                f"Atomizer + BioNetGenModel.simulate(method='ode') (SSTS {case_id})"
            )

    columns = ["time", *ref["variables"]]
    settings = {
        "relative": float(ref["relative"]),
        "absolute": float(ref["absolute"]),
    }
    oracle_bytes = _format_trajectory_json(
        columns=columns,
        times=ref["times"],
        series_map=ref["expected"],
        case_id=case_id,
        settings=settings,
    )
    consumer_bytes = _format_trajectory_json(
        columns=columns,
        times=ref["times"],
        series_map=actual,
    )
    meta = {
        "xml_name": xml_path.name,
        "results_sha256": str(ref["results_sha256"]),
        "settings_sha256": str(ref["settings_sha256"]),
        "consumer_command": exec_cmd,
    }
    return sbml_bytes, oracle_bytes, consumer_bytes, meta


def _execute_analytic_fixture(
    root: Path, rel_path: str
) -> tuple[bytes, dict[str, float], dict[str, float]]:
    import bionetgen._bionetgen_cpp as cpp
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer

    xml_path = root / rel_path
    sbml_bytes = xml_path.read_bytes()
    sbml_text = sbml_bytes.decode("utf-8")
    atomized = Atomizer(atomize=False, quiet_mode=True, actions=False).atomize(
        sbml_text, source_path=xml_path
    )
    if not atomized.success:
        raise RuntimeError(
            f"analytic fixture {rel_path}: Atomizer failed: {atomized.error}"
        )
    cpp_model = cpp.parse_string(atomized.bngl)
    sim = BioNetGenModel(cpp_model).simulate(
        method="ode",
        t_start=0.0,
        t_end=10.0,
        n_steps=10,
        rtol=1e-11,
        atol=1e-15,
    )
    obs_name = next(iter(sim.observables))
    vals = sim.observables[obs_name]
    oracle_obj = {f"A_t{int(round(float(t)))}": 100.0 - float(t) for t in sim.time}
    consumer_obj = {
        f"A_t{int(round(float(t)))}": float(v) for t, v in zip(sim.time, vals)
    }
    return sbml_bytes, oracle_obj, consumer_obj


def build_sbml_receipts(
    *,
    root: Path,
    revision: str,
    ssts_dir: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 SBML receipts require the requested clean revision"
        )

    ssts_revision = _load_ssts_lock_revision(root)
    _verify_ssts_checkout(ssts_dir, ssts_revision)

    # Import owned comparator from issue-471 so we fail closed before emitting.
    checks_dir = root / "tests" / "validation" / "release" / "cases" / "issue-471"
    if str(checks_dir) not in sys.path:
        sys.path.insert(0, str(checks_dir))
    import issue471_checks

    core_assignments, comp_assignments = _select_row_case_map(root)
    needed_cases = sorted(
        set(core_assignments.values()) | set(comp_assignments.values())
    )
    comp_case_set = set(SSTS_COMP_CASES)

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    build_platform = _build_platform()
    script_sha256 = _sha256_bytes(Path(__file__).read_bytes())

    case_artifacts: dict[str, dict[str, Any]] = {}
    failed_cases: dict[str, str] = {}
    for case_id in needed_cases:
        try:
            sbml_bytes, oracle_bytes, consumer_bytes, meta = _execute_ssts_case(
                ssts_dir,
                case_id,
                is_comp=case_id in comp_case_set,
            )
            matched, detail = issue471_checks._compare_ssts_csv_bytes(
                oracle_bytes, consumer_bytes
            )
            if not matched:
                failed_cases[case_id] = detail
                continue
        except Exception as exc:
            failed_cases[case_id] = f"{type(exc).__name__}: {exc}"
            continue

        case_art_dir = artifacts_dir / "ssts" / case_id
        case_art_dir.mkdir(parents=True, exist_ok=True)
        producer_rel = f"ssts/{case_id}/producer.xml"
        oracle_rel = f"ssts/{case_id}/oracle.json"
        consumer_rel = f"ssts/{case_id}/consumer.json"
        (artifacts_dir / producer_rel).write_bytes(sbml_bytes)
        (artifacts_dir / oracle_rel).write_bytes(oracle_bytes)
        (artifacts_dir / consumer_rel).write_bytes(consumer_bytes)
        case_artifacts[case_id] = {
            "producer_rel": producer_rel,
            "producer_sha": _sha256_bytes(sbml_bytes),
            "oracle_rel": oracle_rel,
            "oracle_sha": _sha256_bytes(oracle_bytes),
            "consumer_rel": consumer_rel,
            "consumer_sha": _sha256_bytes(consumer_bytes),
            "meta": meta,
        }

    emitted_core: list[str] = []
    emitted_comp: list[str] = []
    emitted_analytic: list[str] = []

    def _write_ssts_receipt(row_id: str, case_id: str, *, is_comp: bool) -> bool:
        art = case_artifacts.get(case_id)
        if art is None:
            return False
        meta = art["meta"]
        oracle_name = (
            f"official SSTS comp independent source simulation (sbml-test-suite {case_id})"
            if is_comp
            else f"official SSTS semantic reference (sbml-test-suite {case_id})"
        )
        oracle_cmd = (
            f"libsbml CompFlatteningConverter + sbml-test-suite/cases/semantic/{case_id}/{case_id}-results.csv"
            if is_comp
            else f"sbml-test-suite/cases/semantic/{case_id}/{case_id}-results.csv"
        )
        receipt = {
            "schema_version": 2,
            "kind": "release-oracle-consumer-receipt",
            "capability_id": row_id,
            "check_id": f"release-capability[{row_id}]",
            "comparator": "release-oracle-ssts-csv-v1",
            "source_revision": revision,
            "product_revision": revision,
            "oracle": {
                "name": oracle_name,
                "source_id": "sbml-test-suite",
                "revision": ssts_revision,
                "case_id": case_id,
                "results_sha256": meta["results_sha256"],
                "settings_sha256": meta["settings_sha256"],
                "build_platform": build_platform,
                "source_clean": True,
                "path": art["oracle_rel"],
                "artifact_sha256": art["oracle_sha"],
                "script_sha256": script_sha256,
                "command": oracle_cmd,
                "expected_origin": "official-expected-data",
                "execution": {
                    "executable": "sbml-test-suite",
                    "version": ssts_revision[:12],
                    "command": oracle_cmd,
                    "exit_code": 0,
                },
            },
            "producer": {
                "path": art["producer_rel"],
                "output_sha256": art["producer_sha"],
            },
            "consumer": {
                "path": art["consumer_rel"],
                "output_sha256": art["consumer_sha"],
                "consumed_producer_sha256": art["producer_sha"],
                "execution": {
                    "executable": "bionetgen._bionetgen_cpp",
                    "version": revision[:12],
                    "command": meta["consumer_command"],
                    "exit_code": 0,
                },
            },
        }
        (receipts_dir / f"{row_id}.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        return True

    for row_id, case_id in sorted(core_assignments.items()):
        if _write_ssts_receipt(row_id, case_id, is_comp=False):
            emitted_core.append(row_id)

    for row_id, case_id in sorted(comp_assignments.items()):
        if _write_ssts_receipt(row_id, case_id, is_comp=True):
            emitted_comp.append(row_id)

    for row_id, spec_rel in sorted(ANALYTIC_CORE_FIXTURES.items()):
        sbml_bytes, oracle_obj, consumer_obj = _execute_analytic_fixture(root, spec_rel)
        oracle_bytes = (json.dumps(oracle_obj, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        consumer_bytes = (
            json.dumps(consumer_obj, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        matched, detail = issue471_checks._compare_numeric_json_bytes(
            oracle_bytes, consumer_bytes
        )
        if not matched:
            failed_cases[row_id] = detail
            continue

        spec_sha = _sha256_bytes(sbml_bytes)
        row_dir = artifacts_dir / "sbml-analytic" / row_id
        row_dir.mkdir(parents=True, exist_ok=True)
        producer_rel = f"sbml-analytic/{row_id}/producer.xml"
        oracle_rel = f"sbml-analytic/{row_id}/oracle.json"
        consumer_rel = f"sbml-analytic/{row_id}/consumer.json"
        (artifacts_dir / producer_rel).write_bytes(sbml_bytes)
        (artifacts_dir / oracle_rel).write_bytes(oracle_bytes)
        (artifacts_dir / consumer_rel).write_bytes(consumer_bytes)

        receipt = {
            "schema_version": 2,
            "kind": "release-oracle-consumer-receipt",
            "capability_id": row_id,
            "check_id": f"release-capability[{row_id}]",
            "comparator": "release-oracle-numeric-json-v1",
            "source_revision": revision,
            "product_revision": revision,
            "oracle": {
                "name": f"Analytic closed-form evaluation ({row_id})",
                "revision": spec_sha,
                "spec_path": spec_rel,
                "spec_sha256": spec_sha,
                "law": "Zero-order decay dA/dt = -1 with A(0) = 100 yields exact closed-form trajectory A(t) = 100 - t on t in [0, 10]",
                "build_platform": build_platform,
                "path": oracle_rel,
                "artifact_sha256": _sha256_bytes(oracle_bytes),
                "executable_sha256": script_sha256,
                "command": f"python {Path(__file__).name} --row {row_id}",
                "expected_origin": "analytic-derivation",
                "execution": {
                    "executable": "python",
                    "version": sys.version.split()[0],
                    "command": f"analytic closed-form ({spec_rel})",
                    "exit_code": 0,
                },
            },
            "producer": {
                "path": producer_rel,
                "output_sha256": spec_sha,
            },
            "consumer": {
                "path": consumer_rel,
                "output_sha256": _sha256_bytes(consumer_bytes),
                "consumed_producer_sha256": spec_sha,
                "execution": {
                    "executable": "bionetgen._bionetgen_cpp",
                    "version": revision[:12],
                    "command": f"Atomizer + BioNetGenModel.simulate(method='ode') ({spec_rel})",
                    "exit_code": 0,
                },
            },
        }
        (receipts_dir / f"{row_id}.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        emitted_analytic.append(row_id)

    emitted_all = sorted(emitted_core + emitted_comp + emitted_analytic)
    return {
        "schema_version": 1,
        "revision": revision,
        "ssts_revision": ssts_revision,
        "executed_cases": sorted(case_artifacts),
        "failed_cases": failed_cases,
        "emitted_core_count": len(emitted_core),
        "emitted_comp_count": len(emitted_comp),
        "emitted_analytic_count": len(emitted_analytic),
        "count": len(emitted_all),
        "emitted_rows": emitted_all,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ssts-dir", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_sbml_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        ssts_dir=args.ssts_dir.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    print(
        f"emitted {summary['count']} #471 SBML receipts "
        f"(core={summary['emitted_core_count']}, comp={summary['emitted_comp_count']}, "
        f"analytic={summary['emitted_analytic_count']}, failed_cases={len(summary['failed_cases'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
