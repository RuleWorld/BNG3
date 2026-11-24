"""Consuming checks for the locally recorded #474 device report.

The report is produced by ``scripts/ci/record_issue474_release.py`` from actual
device receipts.  These tests only consume it; a passing command with no device
receipt, a Metal result wearing a CUDA label, or a compilation/fallback artifact
cannot produce a PASS row here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
REPORT_ENV = "BNG3_ISSUE474_REPORT"
RECORDER = ROOT / "scripts/ci/record_issue474_release.py"


def _report() -> dict:
    path = os.environ.get(REPORT_ENV)
    if not path:
        pytest.skip(f"set {REPORT_ENV} to a recorded issue-474 report")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rows(report: dict) -> dict:
    return {row["id"]: row for row in report["results"]}


def _head() -> str:
    expected = os.environ.get("BNG3_ISSUE474_REVISION")
    if expected:
        return expected
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def test_report_is_exact_revision_and_clean():
    report = _report()
    assert report["source"]["revision"] == _head()
    assert report["source"]["dirty"] is False
    assert {row["id"] for row in report["results"]} == {
        "release-metal-device",
        "release-metal-performance",
        "release-cuda-device",
        "release-cuda-performance",
        "release-nf-gpu",
        "release-capability-coverage-474",
    }


@pytest.mark.parametrize("check", ("release-metal-device", "release-metal-performance"))
def test_metal_rows_are_supported_device_execution(check):
    row = _rows(_report())[check]
    assert row["status"] == "PASS"
    assert row["supported_execution"] is True
    assert row["evidence_kind"] == "supported-execution"
    assert row["related_issues"] == [474]


def test_metal_performance_carries_cost_and_correctness_evidence():
    report = _report()
    assert report["metal"]["crossover"]
    assert report["metal"]["native_sha256"]
    assert report["network_free"]["metal"]["total_events"] > 0


def test_public_simulate_ssa_route_is_attributed_and_qualified():
    report = _report()
    rows = [
        row
        for row in report["gpu"]["models"]
        if row.get("model") == "toy-jim-public-route"
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "PASS"
    assert row["backend"] == "metal"
    assert row["device_grid_shape"] == [11, 25]
    assert row["seed_replay"] is True
    assert row["n_steps"] > 0 and row["batch_size"] > 0
    assert row["comparison"].startswith("distributional")
    assert all(check["pass"] for check in row["checks"])


def test_cuda_rows_are_never_promoted_without_a_device():
    rows = _rows(_report())
    for check in ("release-cuda-device", "release-cuda-performance"):
        assert rows[check]["status"] == "NOT_TESTED"
        assert rows[check]["supported_execution"] is False
    assert report_cuda_status(_report()) == "BLOCKED"


def report_cuda_status(report: dict) -> str:
    return report["cuda"]["verdict"]["status"]


def test_nf_gpu_does_not_claim_the_full_corpus_or_cuda():
    row = _rows(_report())["release-nf-gpu"]
    assert row["status"] == "NOT_TESTED"
    assert "full network-free GPU corpus" in row["detail"]
    assert "CUDA" in row["detail"]


def test_capability_coverage_acknowledges_cuda_gap():
    row = _rows(_report())["release-capability-coverage-474"]
    assert row["status"] == "NOT_TESTED"
    assert "CUDA" in row["detail"]


def test_workload_receipt_keeps_extended_scope_when_supplied():
    path = os.environ.get("BNG3_ISSUE474_NF_WORKLOADS")
    if not path:
        pytest.skip("set BNG3_ISSUE474_NF_WORKLOADS to a recorded workload receipt")
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
    assert data["device"]["backend"] == "metal"
    assert data["cuda"]["status"] == "UNSUPPORTED"
    assert data["full_corpus_claimed"] is False
    assert len(data["workloads"]) >= 3
    assert {row["class"] for row in data["workloads"]} >= {
        "two_state_ctmc",
        "three_state_chain",
        "particle_heavy",
    }
    assert all(row["status"] == "REFUSED" for row in data["refusals"])
    for row in data["workloads"]:
        assert row["total_events"] > 0
        assert row["device_memory_bytes"] > 0
        assert row["events_per_sec_dispatch"] > 0
        assert row["timings_ms"]["setup"] >= 0.0
        assert all(check["pass"] for check in row["checks"])


def test_receipt_digests_match_the_files(tmp_path):
    report = _report()
    for entry in report["receipts"]:
        path = Path(entry.get("display_path", entry["path"]))
        if not path.is_absolute():
            path = ROOT / path
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def _recorder_module():
    spec = importlib.util.spec_from_file_location("issue474_recorder", RECORDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_receipt(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_stale_parity_receipt_is_rejected(tmp_path):
    recorder = _recorder_module()
    receipt = _write_receipt(
        tmp_path,
        "parity.json",
        {
            "source_revision": "0" * 40,
            "source_dirty": False,
            "native_sha256": "a" * 64,
            "gpu": {
                "status": "PASS",
                "backend": "metal",
                "inventory": [],
                "models": [],
            },
        },
    )
    with pytest.raises(ValueError, match="parity receipt: stale revision"):
        recorder._validate_parity(receipt, "1" * 40, "Apple M5 Pro", "a" * 64)


def test_fallback_labelled_metal_is_rejected(tmp_path):
    recorder = _recorder_module()
    receipt = _write_receipt(
        tmp_path,
        "parity.json",
        {
            "source_revision": "1" * 40,
            "source_dirty": False,
            "native_sha256": "a" * 64,
            "gpu": {"status": "PASS", "backend": "cpu", "inventory": [], "models": []},
        },
    )
    with pytest.raises(ValueError, match="not a Metal run"):
        recorder._validate_parity(receipt, "1" * 40, "Apple M5 Pro", "a" * 64)
