"""Negative controls for the Issue 174 release recorder.

The historical baseline, a partial workload report, a stale/foreign report,
or #174 acceptance without clean #176 acceptance cannot produce a current
benchmark PASS.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.ci import record_issue174_release as rec

ROOT = Path(__file__).resolve().parents[2]
REV = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _current(revision=REV, family=None, workloads=None):
    family = family or rec._expected_platform_family()
    workloads = (
        workloads
        if workloads is not None
        else {
            name: {
                "status": "PASS",
                "median": 0.01,
                "reps": [0.01],
                "control": "independent control",
            }
            for name in rec.REQUIRED_WORKLOADS
        }
    )
    return {
        "check": "issue174-current-cpu-benchmark",
        "status": "PASS",
        "identity": {
            "source_revision": revision,
            "host": "host",
            "machine": "arm64",
            "python": "3.14.6",
            "compiler": "clang",
            "extension_sha256": "a" * 64,
            "platform_family": family,
            "historical_baseline_revision": "10915aa",
            "historical_baseline_sha256": "b" * 64,
        },
        "workloads": workloads,
        "alternating_aa_control": True,
    }


def _prior(statuses=None):
    statuses = statuses or {
        "release-nf-ensemble": "PASS",
        "release-capability-coverage-176": "PASS",
    }
    return {"results": [{"id": k, "status": v} for k, v in statuses.items()]}


def _build(current=None, prior=None, executed=None, **kwargs):
    executed = {"leaf": {}} if executed is None else executed

    def fake(root):
        return executed

    mp = pytest.MonkeyPatch()
    mp.setattr(rec, "run_tests", fake)
    try:
        record = rec.build_release_record(
            expected_revision=REV,
            allow_dirty=True,
            root=ROOT,
            current_report=current,
            issue176_report=prior,
            **kwargs,
        )
    finally:
        mp.undo()
    return {row["id"]: row for row in record["results"]}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def test_leaf_only_cannot_certify_current_benchmark():
    rows = _build()
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())


def test_skipped_execution_cannot_be_pass():
    rows = _build(skip_tests=True)
    assert all(row["status"] == "NOT_TESTED" for row in rows.values())


def test_partial_workload_report_cannot_satisfy_benchmarks(tmp_path):
    workloads = {
        name: {"status": "PASS", "median": 0.01, "control": "x"}
        for name in rec.REQUIRED_WORKLOADS
    }
    del workloads["nfnext"]
    path = _write(tmp_path, "partial.json", _current(workloads=workloads))
    rows = _build(current=path, prior=_write(tmp_path, "prior.json", _prior()))
    assert rows["release-benchmarks"]["status"] == "NOT_TESTED"


def test_foreign_platform_report_is_rejected(tmp_path):
    foreign = "linux" if rec._expected_platform_family() == "apple" else "apple"
    path = _write(tmp_path, "foreign.json", _current(family=foreign))
    rows = _build(current=path, prior=_write(tmp_path, "prior.json", _prior()))
    assert rows["release-benchmarks"]["status"] == "NOT_TESTED"


def test_stale_current_report_is_rejected(tmp_path):
    path = _write(tmp_path, "stale.json", _current(revision="0" * 40))
    rows = _build(current=path, prior=_write(tmp_path, "prior.json", _prior()))
    assert rows["release-benchmarks"]["status"] == "NOT_TESTED"


def test_missing_issue176_acceptance_blocks_final_acceptance(tmp_path):
    current = _write(tmp_path, "current.json", _current())
    rows = _build(current=current)
    assert rows["release-benchmarks"]["status"] == "PASS"
    assert rows["release-obligation-174"]["status"] == "NOT_TESTED"


def test_partial_issue176_acceptance_blocks_final_acceptance(tmp_path):
    current = _write(tmp_path, "current.json", _current())
    prior = _write(
        tmp_path,
        "prior.json",
        _prior(
            statuses={
                "release-nf-ensemble": "PASS",
                "release-capability-coverage-176": "NOT_TESTED",
            }
        ),
    )
    rows = _build(current=current, prior=prior)
    assert rows["release-obligation-174"]["status"] == "NOT_TESTED"


def test_complete_evidence_can_produce_pass(tmp_path):
    current = _write(tmp_path, "current.json", _current())
    prior = _write(tmp_path, "prior.json", _prior())
    rows = _build(current=current, prior=prior)
    assert all(row["status"] == "PASS" for row in rows.values())
