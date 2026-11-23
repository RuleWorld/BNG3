"""Negative controls for the Issue 178 release recorder.

These tests prove that a partial result, a missing artifact, a skipped test,
a stale report, or GPU-compile-only evidence cannot be reported as a full
cross-backend PASS. They are independent of BNG3 execution: the recorder is
driven with synthetic evidence so the verdict logic itself is under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import record_issue178_release as rec

ROOT = Path(__file__).resolve().parents[2]
REV = "12dace48a92bd70d08f2f76bebb7dac3d6206b60"


def _route_report(check_id, *, revision=REV, routes=None, dirty=False, status="PASS"):
    routes = routes if routes is not None else {
        name: {
            "compiled_input": True,
            "result_schema": True,
            "invalid_options": True,
            "independent_output": True,
            "scope": "cpu-execution",
        }
        for name in rec.REQUIRED_ROUTES[check_id]
    }
    return {
        "check": check_id,
        "status": status,
        "source_revision": revision,
        "source_dirty": dirty,
        "routes": routes,
    }


def _write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def _run(fake_executed=None, **kwargs):
    """Build a receipt with run_tests replaced by a controllable stub."""
    calls = {}

    def fake_run_tests(root):
        calls["called"] = True
        return fake_executed

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rec, "run_tests", fake_run_tests)
    try:
        record = rec.build_release_record(
            expected_revision=REV, allow_dirty=True, root=ROOT, **kwargs
        )
    finally:
        monkeypatch.undo()
    return {row["id"]: row for row in record["results"]}, calls


def test_mocked_noop_execution_cannot_produce_pass():
    rows, calls = _run(fake_executed=None)
    assert calls["called"] is True
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())
    assert all(row["supported_execution"] is False for row in rows.values())


def test_skipped_execution_cannot_produce_pass():
    rows, _ = _run(fake_executed={c: {} for c in rec.EXPECTED_CHECKS}, skip_tests=True)
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())


def test_leaf_execution_alone_cannot_certify_route_checks():
    # Even every leaf reporting executed cannot turn a route check into PASS
    # without a consuming route report.
    rows, _ = _run(fake_executed={c: {} for c in rec.EXPECTED_CHECKS})
    for check_id in rec.ROUTE_CHECKS:
        assert rows[check_id]["status"] == "NOT_TESTED"
        assert "unmeasured" in rows[check_id]["detail"].lower()


def test_partial_route_report_cannot_satisfy_full_check(tmp_path):
    check_id = "release-backend-contract"
    routes = {
        name: {
            "compiled_input": True,
            "result_schema": True,
            "invalid_options": True,
            "independent_output": True,
            "scope": "cpu-execution",
        }
        for name in rec.REQUIRED_ROUTES[check_id]
    }
    # One required route lacks the independent-output aspect.
    first = sorted(routes)[0]
    routes[first]["independent_output"] = False
    path = _write(tmp_path, "partial.json", _route_report(check_id, routes=routes))
    rows, _ = _run(fake_executed={}, route_reports={check_id: path})
    assert rows[check_id]["status"] == "NOT_TESTED"


def test_missing_route_artifact_cannot_satisfy_check(tmp_path):
    check_id = "release-interface-parity"
    missing = str(tmp_path / "does-not-exist.json")
    rows, _ = _run(fake_executed={}, route_reports={check_id: missing})
    assert rows[check_id]["status"] == "NOT_TESTED"


def test_stale_route_report_is_rejected(tmp_path):
    check_id = "release-backend-oracles"
    path = _write(
        tmp_path,
        "stale.json",
        _route_report(check_id, revision="0" * 40),
    )
    rows, _ = _run(fake_executed={}, route_reports={check_id: path})
    assert rows[check_id]["status"] == "NOT_TESTED"


def test_failed_route_report_is_rejected(tmp_path):
    check_id = "release-backend-oracles"
    path = _write(tmp_path, "failed.json", _route_report(check_id, status="FAIL"))
    rows, _ = _run(fake_executed={}, route_reports={check_id: path})
    assert rows[check_id]["status"] == "NOT_TESTED"


def test_gpu_device_row_does_not_count_as_device_execution(tmp_path):
    check_id = "release-backend-oracles"
    routes = {
        name: {
            "compiled_input": True,
            "result_schema": True,
            "invalid_options": True,
            "independent_output": True,
            "scope": "gpu-device",
        }
        for name in rec.REQUIRED_ROUTES[check_id]
    }
    path = _write(tmp_path, "gpu.json", _route_report(check_id, routes=routes))
    rows, _ = _run(fake_executed={}, route_reports={check_id: path})
    assert rows[check_id]["status"] == "NOT_TESTED"


def test_complete_route_report_can_produce_pass(tmp_path):
    # Positive control: genuine full evidence is accepted, so the negative
    # controls above have discriminating power.
    check_id = "release-backend-contract"
    path = _write(tmp_path, "full.json", _route_report(check_id))
    rows, _ = _run(fake_executed={}, route_reports={check_id: path})
    assert rows[check_id]["status"] == "PASS"
    assert rows[check_id]["supported_execution"] is True
