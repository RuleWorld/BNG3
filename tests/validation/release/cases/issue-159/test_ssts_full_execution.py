"""Executable selectors for the two fully-grounded Issue 159 live checks.

These consume an exact-main full SSTS report and its receipt, produced by
scripts/ci/record_issue159_release.py. They verify only the evidence contract:
full non-partial run, exact revision, zero failed/timeout/invalid-source, and
recorded identities. No scientific expectation or verdict is authored here.
"""

import json
import os
from pathlib import Path

import pytest

_SUITE_REPORT = os.environ.get("BNG3_SSTS_FULL_REPORT")
_RECEIPT = os.environ.get("BNG3_ISSUE159_RECEIPT")


def _load(path, label):
    if not path:
        pytest.skip(f"{label} not provided in this environment")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_release_ssts_exact_full_run():
    """release-ssts: exact-revision full suite with zero blocking outcomes."""
    report = _load(_SUITE_REPORT, "BNG3_SSTS_FULL_REPORT")
    revision = os.environ.get("BNG3_EXACT_REVISION")
    assert revision and len(revision) == 40
    prov = report["source_provenance"]
    assert prov["bng3_commit"] == revision
    assert prov["bng3_tracked_worktree_clean"] is True
    assert report["partial_run"] is False
    assert report["case_inventory"] == report["selected_cases"] >= 1923
    counts = report["counts"]
    for key in ("failed", "timeout", "invalid-source"):
        assert counts[key] == 0
    official = report["official_conformance"]["counts"]
    assert official["failed"] == 0 and official["timed-out"] == 0


def test_release_obligation_159_receipt():
    """release-obligation-159: identities and main revision are recorded."""
    receipt = _load(_RECEIPT, "BNG3_ISSUE159_RECEIPT")
    revision = os.environ.get("BNG3_EXACT_REVISION")
    assert revision and len(revision) == 40
    assert receipt["source"]["revision"] == revision
    assert receipt["source"]["dirty"] is False
    rows = {row["id"]: row for row in receipt["results"]}
    assert set(rows) == {"release-ssts", "release-obligation-159"}
    assert rows["release-ssts"]["evidence_kind"] == "supported-execution"
    assert rows["release-ssts"]["supported_execution"] is True
    # The catalog declares this as supported-execution; do not weaken it.
    assert rows["release-obligation-159"]["evidence_kind"] == "supported-execution"
    assert receipt["references"]["ssts"]["revision"]
