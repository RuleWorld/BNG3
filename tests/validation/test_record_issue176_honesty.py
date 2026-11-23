"""Negative controls for the Issue 176 release recorder.

A sequential leaf, a partial workload report, a missing native comparison, a
stale/failed report or GPU-only evidence cannot satisfy the full ensemble and
capability-coverage checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import record_issue176_release as rec

ROOT = Path(__file__).resolve().parents[2]
REV = "12dace48a92bd70d08f2f76bebb7dac3d6206b60"


def _ensemble(revision=REV, **overrides):
    doc = {
        "check": "release-nf-ensemble",
        "status": "PASS",
        "source_revision": revision,
        "source_dirty": False,
        "native_revision": rec.PINNED_NFSIM_REVISION,
        "seed_budget": 64,
        "concurrent": True,
        "error_control": "|diff| <= 3 pooled SE",
        "control_se": 0.12,
    }
    doc.update(overrides)
    return doc


def _measurement(revision=REV, workloads=None):
    workloads = workloads if workloads is not None else {
        name: {
            "status": "PASS",
            "startup_seconds": 0.01,
            "ensemble_seconds": 0.5,
            "events": 1000,
            "events_per_second": 2000.0,
            "peak_rss_kib": 100000,
            "correctness": {"invariant": "independent control"},
        }
        for name in rec.REQUIRED_WORKLOADS
    }
    return {
        "check": "release-capability-coverage-176",
        "status": "PASS",
        "source_revision": revision,
        "source_dirty": False,
        "workloads": workloads,
    }


def _build(reports=None, executed=None, **kwargs):
    executed = {"leaf": {}} if executed is None else executed

    def fake(root):
        return executed

    mp = pytest.MonkeyPatch()
    mp.setattr(rec, "run_tests", fake)
    try:
        record = rec.build_release_record(
            expected_revision=REV, allow_dirty=True, root=ROOT,
            reports=reports or {}, **kwargs
        )
    finally:
        mp.undo()
    return {row["id"]: row for row in record["results"]}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def test_leaf_only_cannot_certify_either_check():
    rows = _build(executed={"leaf": {}})
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())


def test_skipped_execution_cannot_be_pass():
    rows = _build(skip_tests=True)
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())


def test_partial_workload_report_cannot_satisfy_coverage(tmp_path):
    workloads = {
        name: {
            "status": "PASS",
            "startup_seconds": 0.01,
            "events_per_second": 2000.0,
            "peak_rss_kib": 100000,
            "correctness": {"invariant": "x"},
        }
        for name in rec.REQUIRED_WORKLOADS
    }
    del workloads["genome"]  # partial: scaffold/genome requirement not met
    path = _write(tmp_path, "partial.json", _measurement(workloads=workloads))
    rows = _build(reports={"release-capability-coverage-176": path})
    assert rows["release-capability-coverage-176"]["status"] == "NOT_TESTED"


def test_native_revision_mismatch_is_rejected(tmp_path):
    path = _write(tmp_path, "drift.json", _ensemble(native_revision="0" * 40))
    rows = _build(reports={"release-nf-ensemble": path})
    assert rows["release-nf-ensemble"]["status"] == "NOT_TESTED"


def test_sequential_report_without_concurrency_is_rejected(tmp_path):
    path = _write(tmp_path, "seq.json", _ensemble(concurrent=False))
    rows = _build(reports={"release-nf-ensemble": path})
    assert rows["release-nf-ensemble"]["status"] == "NOT_TESTED"


def test_missing_and_stale_reports_cannot_satisfy_checks(tmp_path):
    rows = _build(reports={"release-nf-ensemble": str(tmp_path / "none.json")})
    assert rows["release-nf-ensemble"]["status"] == "NOT_TESTED"
    stale = _write(tmp_path, "stale.json", _measurement(revision="0" * 40))
    rows = _build(reports={"release-capability-coverage-176": stale})
    assert rows["release-capability-coverage-176"]["status"] == "NOT_TESTED"


def test_complete_reports_can_produce_pass(tmp_path):
    e = _write(tmp_path, "ensemble.json", _ensemble())
    m = _write(tmp_path, "measure.json", _measurement())
    rows = _build(
        reports={"release-nf-ensemble": e, "release-capability-coverage-176": m}
    )
    assert all(row["status"] == "PASS" for row in rows.values())
