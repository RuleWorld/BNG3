"""Issue 174 release recorder produces a valid exact-revision consuming receipt."""

from pathlib import Path

from scripts.ci.record_issue174_release import EXPECTED_CHECKS, build_release_record

ROOT = Path(__file__).resolve().parents[2]


def test_release_record_shape_without_execution():
    record = build_release_record(skip_tests=True, allow_dirty=True, root=ROOT)
    assert record["acceptance_check"] == "release-obligation-174"
    assert record["source"]["revision"]
    assert {row["id"] for row in record["results"]} == set(EXPECTED_CHECKS)
    assert all(row["status"] == "NOT_TESTED" for row in record["results"])
