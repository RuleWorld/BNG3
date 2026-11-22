"""Issue 176 release recorder produces a valid exact-revision consuming receipt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.record_issue176_release import EXPECTED_CHECKS, build_release_record

ROOT = Path(__file__).resolve().parents[2]


def test_release_record_shape_without_execution():
    record = build_release_record(skip_tests=True, allow_dirty=True, root=ROOT)
    assert record["acceptance_check"] == "release-nf-ensemble"
    assert record["source"]["revision"]
    assert {row["id"] for row in record["results"]} == set(EXPECTED_CHECKS)
    assert all(row["status"] == "NOT_TESTED" for row in record["results"])
    assert all(row["supported_execution"] is False for row in record["results"])


def test_recorder_rejects_a_manifest_missing_a_selector(tmp_path):
    # The real manifest is mapped; a synthetic missing selector must be refused.
    from scripts.ci.record_issue176_release import verify_manifest

    manifest = json.loads((ROOT / "provenance/issue-obligations.json").read_text())
    issue = next(i for i in manifest["issues"] if i["number"] == 176)
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            if check["id"] in EXPECTED_CHECKS:
                check["selector"] = None
    (tmp_path / "provenance").mkdir()
    (tmp_path / "provenance" / "issue-obligations.json").write_text(
        json.dumps(manifest)
    )
    with pytest.raises(ValueError, match="no collected selector"):
        verify_manifest(tmp_path)
