"""Strict execution-gate contract for the bounded S5 delay replay."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "s5_consumer_contract", HERE / "case_contract.py"
)
CONTRACT = importlib.util.module_from_spec(CONTRACT_SPEC)
assert CONTRACT_SPEC.loader is not None
CONTRACT_SPEC.loader.exec_module(CONTRACT)

SPEC = importlib.util.spec_from_file_location("s5_consume", HERE / "consume.py")
CONSUMER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CONSUMER)

REVISION = "a" * 40


def _valid_manifest(tmp_path: Path) -> dict:
    module = tmp_path / "_bionetgen_cpp.so"
    module.write_bytes(b"candidate native extension")
    cases = []
    for case_id in ("ordinary", "boundary", "interaction"):
        source = tmp_path / f"{case_id}-source.xml"
        source.write_text(f"<sbml id='{case_id}'/>", encoding="utf-8")
        output = tmp_path / f"{case_id}-public-bng3.json"
        output.write_text(
            json.dumps(
                [
                    {
                        "time": time,
                        "x_amt": CONTRACT.expected(case_id, time)["x"],
                        "z_amt": CONTRACT.expected(case_id, time)["z"],
                        "y": CONTRACT.expected(case_id, time)["y"],
                        "q": CONTRACT.expected(case_id, time)["q"],
                    }
                    for time in CONTRACT.sample_times(case_id)
                ]
            ),
            encoding="utf-8",
        )
        segments = {
            "ordinary": [[0.0, 2.0]],
            "boundary": [[0.0, 0.5], [0.5, 2.0]],
            "interaction": [
                [0.0, 0.4],
                [0.4, 0.5],
                [0.5, 0.8],
                [0.8, 1.2],
                [1.2, 2.0],
            ],
        }[case_id]
        statuses = {
            "source-validation": "PASS",
            "analytic-reference": "PASS",
            "raw-source-libroadrunner": "ORACLE_UNAVAILABLE",
            "atomizer-lowering": "PASS",
            "public-bng3-execution": "PASS",
            "public-bng3-continuation": (
                "NOT_REQUIRED" if case_id == "ordinary" else "PASS"
            ),
            "public-bng3-output-comparison": "PASS",
        }
        stages = [{"id": stage, "status": status} for stage, status in statuses.items()]
        stages[4]["native_identity"] = {
            "module": str(module),
            "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
            "consumer": (
                "public BioNetGenModel ODE API"
                if case_id == "ordinary"
                else "public bionetgen.run action runner"
            ),
        }
        cases.append(
            {
                "case_id": case_id,
                "case_source_revision": REVISION,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "raw_source_copy": str(source),
                "verdict": "PASS",
                "continuation_segments": segments,
                "stages": stages,
            }
        )
        stages[-1]["artifact"] = str(output)
    return {
        "harness_revision": REVISION,
        "native_source_revision": REVISION,
        "repository_dirty": False,
        "cases": cases,
    }


def _write(tmp_path: Path, report: dict) -> Path:
    path = tmp_path / "s5-replay.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_strict_consumer_accepts_three_cases_with_unavailable_roadrunner(tmp_path):
    result = CONSUMER.consume(_write(tmp_path, _valid_manifest(tmp_path)), REVISION)
    assert result["status"] == "PASS"
    assert set(result["case_verdicts"]) == {"ordinary", "boundary", "interaction"}


def test_malformed_report_root_fails_closed(tmp_path):
    with pytest.raises(CONSUMER.GateError, match="root must be a JSON object"):
        CONSUMER.consume(_write(tmp_path, []), REVISION)


@pytest.mark.parametrize(
    ("stage_id", "status"),
    [
        ("public-bng3-execution", "NOT_TESTED"),
        ("public-bng3-execution", "REQUIRED_BUT_UNSUPPORTED"),
        ("public-bng3-continuation", "NOT_TESTED"),
        ("public-bng3-output-comparison", "NOT_TESTED"),
    ],
)
def test_missing_or_unsupported_native_stage_fails_execution_gate(
    tmp_path, stage_id, status
):
    report = _valid_manifest(tmp_path)
    stage = next(row for row in report["cases"][2]["stages"] if row["id"] == stage_id)
    stage["status"] = status
    with pytest.raises(CONSUMER.GateError):
        CONSUMER.consume(_write(tmp_path, report), REVISION)


def test_scientific_verdict_cannot_mask_missing_output_comparison(tmp_path):
    report = _valid_manifest(tmp_path)
    report["cases"][2]["verdict"] = "PASS"
    report["cases"][2]["stages"] = [
        row
        for row in report["cases"][2]["stages"]
        if row["id"] != "public-bng3-output-comparison"
    ]
    with pytest.raises(CONSUMER.GateError, match="public-bng3-output-comparison"):
        CONSUMER.consume(_write(tmp_path, report), REVISION)


def test_scientific_verdict_cannot_mask_wrong_retained_native_outputs(tmp_path):
    report = _valid_manifest(tmp_path)
    output = Path(
        next(
            row
            for row in report["cases"][2]["stages"]
            if row["id"] == "public-bng3-output-comparison"
        )["artifact"]
    )
    rows = json.loads(output.read_text(encoding="utf-8"))
    rows[-1]["x_amt"] += 1.0
    output.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(CONSUMER.GateError, match="analytic source law"):
        CONSUMER.consume(_write(tmp_path, report), REVISION)


def test_runtime_revision_and_extension_digest_are_required(tmp_path):
    report = _valid_manifest(tmp_path)
    report["native_source_revision"] = "b" * 40
    with pytest.raises(CONSUMER.GateError, match="native source revision"):
        CONSUMER.consume(_write(tmp_path, report), REVISION)

    report = _valid_manifest(tmp_path)
    execution = next(
        row
        for row in report["cases"][0]["stages"]
        if row["id"] == "public-bng3-execution"
    )
    execution["native_identity"]["module_sha256"] = "0" * 64
    with pytest.raises(CONSUMER.GateError, match="extension digest"):
        CONSUMER.consume(_write(tmp_path, report), REVISION)
