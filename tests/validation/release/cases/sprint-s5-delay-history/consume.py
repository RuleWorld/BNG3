"""Fail the scientific execution gate when delay replay evidence is incomplete."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path


class GateError(ValueError):
    """The replay artifact does not satisfy the selected execution gate."""


_CASE_SEGMENTS = {
    "ordinary": [[0.0, 2.0]],
    "boundary": [[0.0, 0.5], [0.5, 2.0]],
    "interaction": [
        [0.0, 0.4],
        [0.4, 0.5],
        [0.5, 0.8],
        [0.8, 1.2],
        [1.2, 2.0],
    ],
}
_REQUIRED_STAGES = {
    "source-validation": {"PASS"},
    "analytic-reference": {"PASS"},
    "raw-source-libroadrunner": {"PASS", "ORACLE_UNAVAILABLE"},
    "atomizer-lowering": {"PASS"},
    "public-bng3-execution": {"PASS"},
    "public-bng3-output-comparison": {"PASS"},
}
_ATOL = 1e-9
_RTOL = 1e-9
_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "s5_consumer_case_contract", Path(__file__).with_name("case_contract.py")
)
if _CONTRACT_SPEC is None or _CONTRACT_SPEC.loader is None:
    raise RuntimeError("cannot load the independent delay case contract")
_CONTRACT = importlib.util.module_from_spec(_CONTRACT_SPEC)
_CONTRACT_SPEC.loader.exec_module(_CONTRACT)


def _fail(message: str) -> None:
    raise GateError(message)


def _stage_map(case: dict, case_id: str) -> dict[str, dict]:
    stages = case.get("stages")
    if not isinstance(stages, list):
        _fail(f"{case_id}: missing scientific stages")
    mapped = {}
    for row in stages:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            _fail(f"{case_id}: malformed scientific stage")
        stage_id = row["id"]
        if stage_id in mapped:
            _fail(f"{case_id}: duplicate scientific stage {stage_id}")
        mapped[stage_id] = row
    return mapped


def _check_runtime_identity(stage: dict, case_id: str) -> None:
    identity = stage.get("native_identity")
    if not isinstance(identity, dict):
        _fail(f"{case_id}: native runtime identity is missing")
    module = Path(str(identity.get("module", ""))).resolve()
    digest = identity.get("module_sha256")
    if (
        not module.is_file()
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        _fail(f"{case_id}: native extension identity is incomplete")
    if module.suffix.lower() not in {".so", ".pyd", ".dylib"}:
        _fail(f"{case_id}: loaded module is not a native extension")
    actual_digest = hashlib.sha256(module.read_bytes()).hexdigest()
    if actual_digest != digest:
        _fail(f"{case_id}: native extension digest does not match the loaded module")
    expected_consumer = (
        "public BioNetGenModel ODE API"
        if case_id == "ordinary"
        else "public bionetgen.run action runner"
    )
    if identity.get("consumer") != expected_consumer:
        _fail(f"{case_id}: execution did not use the required public API consumer")


def _compare_native_outputs(case_id: str, output: Path) -> None:
    try:
        rows = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"{case_id}: cannot read native output artifact: {exc}")
    if not isinstance(rows, list) or not rows:
        _fail(f"{case_id}: native output artifact has no observations")
    for row in rows:
        if not isinstance(row, dict):
            _fail(f"{case_id}: malformed native output observation")
        try:
            time = float(row["time"])
            reference = _CONTRACT.expected(case_id, time)
            actuals = {
                "x": float(row["x_amt"]),
                "z": float(row["z_amt"]),
                "y": float(row["y"]),
                "q": float(row["q"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            _fail(f"{case_id}: malformed native output value: {exc}")
        if not math.isfinite(time) or not 0.0 <= time <= 2.0:
            _fail(f"{case_id}: native output time is outside the declared horizon")
        for quantity, actual in actuals.items():
            if not math.isclose(
                actual, reference[quantity], abs_tol=_ATOL, rel_tol=_RTOL
            ):
                _fail(
                    f"{case_id}: native output {quantity} at t={time:g} does not "
                    "match the analytic source law"
                )


def consume(report_path: Path, expected_revision: str) -> dict:
    """Validate every required stage and return a compact execution-gate receipt."""
    report_path = Path(report_path).resolve()
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read replay report: {exc}")
    if not isinstance(report, dict):
        _fail("replay report root must be a JSON object")
    if report.get("harness_revision") != expected_revision:
        _fail("harness revision does not match the selected source revision")
    if report.get("native_source_revision") != expected_revision:
        _fail("native source revision does not match the selected source revision")
    if report.get("repository_dirty") is not False:
        _fail("replay source tree is dirty or its state is missing")
    cases = report.get("cases")
    if (
        not isinstance(cases, list)
        or {row.get("case_id") for row in cases if isinstance(row, dict)}
        != set(_CASE_SEGMENTS)
        or len(cases) != len(_CASE_SEGMENTS)
    ):
        _fail("replay must contain exactly ordinary, boundary, and interaction cases")

    verdicts = {}
    for case in cases:
        case_id = case["case_id"]
        if case.get("case_source_revision") != expected_revision:
            _fail(
                f"{case_id}: source case revision does not match the selected revision"
            )
        source_copy = Path(str(case.get("raw_source_copy", ""))).resolve()
        source_digest = case.get("source_sha256")
        if not source_copy.is_file() or not isinstance(source_digest, str):
            _fail(f"{case_id}: raw source copy or digest is missing")
        if not source_copy.is_relative_to(report_path.parent):
            _fail(f"{case_id}: raw source copy is outside the retained artifact")
        if hashlib.sha256(source_copy.read_bytes()).hexdigest() != source_digest:
            _fail(f"{case_id}: raw source copy does not match its recorded digest")
        if case.get("verdict") != "PASS":
            _fail(
                f"{case_id}: scientific verdict is {case.get('verdict')!r}, expected PASS"
            )
        if case.get("continuation_segments") != _CASE_SEGMENTS[case_id]:
            _fail(f"{case_id}: continuation segment schedule is missing or changed")
        stages = _stage_map(case, case_id)
        for stage_id, accepted in _REQUIRED_STAGES.items():
            stage = stages.get(stage_id)
            if stage is None:
                _fail(f"{case_id}: missing required stage {stage_id}")
            if stage.get("status") not in accepted:
                _fail(
                    f"{case_id}: {stage_id} status {stage.get('status')!r} "
                    f"does not satisfy the execution gate"
                )
        continuation = stages.get("public-bng3-continuation")
        expected_continuation = "NOT_REQUIRED" if case_id == "ordinary" else "PASS"
        if continuation is None or continuation.get("status") != expected_continuation:
            _fail(f"{case_id}: continuation evidence is missing or did not pass")
        execution = stages["public-bng3-execution"]
        _check_runtime_identity(execution, case_id)
        output = Path(
            str(stages["public-bng3-output-comparison"].get("artifact", ""))
        ).resolve()
        if not output.is_file() or output.stat().st_size == 0:
            _fail(f"{case_id}: compared native output artifact is missing or empty")
        if not output.is_relative_to(report_path.parent):
            _fail(
                f"{case_id}: compared output artifact is outside the retained artifact"
            )
        _compare_native_outputs(case_id, output)
        verdicts[case_id] = case["verdict"]
    return {
        "status": "PASS",
        "expected_revision": expected_revision,
        "case_verdicts": verdicts,
        "scope": "three S5 analytic delay-history cases only",
        "release_delay_ode": "not discharged",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = consume(args.report, args.revision)
    report_directory = args.report.resolve().parent
    receipt_path = args.receipt.resolve()
    if not receipt_path.is_relative_to(report_directory):
        _fail("consumer receipt must be written inside the replay artifact directory")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
