"""Tests for Issue 147 NFnext lowering release acceptance recorder."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.ci import record_issue147_release
from tests.validation import issue_queue

ROOT = Path(__file__).resolve().parents[2]


def test_nfir_lowering_release_record_verifies_manifest():
    manifest_checks = record_issue147_release.verify_manifest(ROOT)
    assert set(manifest_checks.keys()) == {
        "release-nfir-lowering",
        "release-nfir-roundtrip",
        "release-obligation-147",
    }


def test_nfir_lowering_release_record_rejects_stale_revision():
    with pytest.raises(ValueError, match="stale"):
        record_issue147_release.build_release_record(
            expected_revision="0" * 40,
            root=ROOT,
            skip_tests=True,
        )


def test_nfir_lowering_release_record_rejects_dirty_checkout(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: type(
            "Result",
            (),
            {
                "stdout": "M file.py" if "status" in cmd else "a" * 40,
                "returncode": 0,
            },
        )(),
    )
    with pytest.raises(ValueError, match="dirty"):
        record_issue147_release.build_release_record(
            root=ROOT,
            skip_tests=True,
            allow_dirty=False,
        )


def test_nfir_lowering_release_record_builds_valid_report(tmp_path):
    report = record_issue147_release.build_release_record(
        root=ROOT, skip_tests=True, allow_dirty=True
    )
    assert report["schema_version"] == 1
    assert report["acceptance_check"] == "release-obligation-147"
    assert len(report["results"]) == 3
    for row in report["results"]:
        assert row["status"] == "NOT_TESTED"
        assert row["supported_execution"] is False
        assert row["evidence_kind"] == "not-tested"

    out_file = tmp_path / "issue147_report.json"
    out_file.write_text(json.dumps(report), encoding="utf-8")

    manifest = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue_147 = next(i for i in manifest["issues"] if i["number"] == 147)
    # Clear dependencies for isolated check assessment
    obs = [dict(ob, dependencies=[]) for ob in issue_147["obligations"]]
    assessed = issue_queue.assess_obligations(
        obs, [report], report["source"]["revision"]
    )["obligations"]
    for ob in assessed:
        if "live-acceptance" in ob["id"]:
            assert ob["status"] != "DEMONSTRATED"
            for chk in ob["checks"]:
                assert chk["status"] == "NOT_TESTED"


def test_nfir_lowering_record_cli(tmp_path):
    out_file = tmp_path / "report.json"
    summary_file = tmp_path / "summary.md"
    ret = record_issue147_release.main(
        [
            "--output",
            str(out_file),
            "--summary-file",
            str(summary_file),
            "--skip-tests",
            "--allow-dirty",
        ]
    )
    assert ret == 0
    assert out_file.is_file()
    assert summary_file.is_file()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["acceptance_check"] == "release-obligation-147"


def test_successful_bounded_wrapper_is_not_full_acceptance(monkeypatch):
    """A successful wrapper cannot establish every family or consumer."""
    monkeypatch.setattr(
        record_issue147_release,
        "run_tests",
        lambda root: [{"id": "bounded:unary", "status": "PASS"}],
    )
    report = record_issue147_release.build_release_record(root=ROOT, allow_dirty=True)
    assert report["bounded_results"] == [{"id": "bounded:unary", "status": "PASS"}]
    assert all(row["status"] == "NOT_TESTED" for row in report["results"])
    assert all(row["supported_execution"] is False for row in report["results"])
    # Evaluate the clean-source case as well: the missing full-scope evidence,
    # not merely the dirty-source guard, must prevent a demonstrated result.
    report["source"]["dirty"] = False
    manifest = json.loads((ROOT / "provenance/issue-obligations.json").read_text())
    issue = next(item for item in manifest["issues"] if item["number"] == 147)
    obligations = [dict(item, dependencies=[]) for item in issue["obligations"]]
    assessed = issue_queue.assess_obligations(
        obligations, [report], report["source"]["revision"]
    )["obligations"]
    assert all(item["status"] != "DEMONSTRATED" for item in assessed)


def test_bounded_junit_preserves_skipped_cases(monkeypatch):
    def fake_run(cmd, **kwargs):
        path = Path(
            next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--junitxml="))
        )
        path.write_text(
            '<testsuite><testcase classname="test" name="ran" time="0"/>'
            '<testcase classname="test" name="skipped" time="0">'
            '<skipped message="optional oracle unavailable"/></testcase></testsuite>'
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(record_issue147_release.subprocess, "run", fake_run)
    rows = record_issue147_release.run_tests(ROOT)
    assert {row["name"]: row["status"] for row in rows} == {
        "ran": "PASS",
        "skipped": "NOT_TESTED",
    }


def test_bounded_junit_rejects_zero_collection(monkeypatch):
    def fake_run(cmd, **kwargs):
        path = Path(
            next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--junitxml="))
        )
        path.write_text("<testsuite/>")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(record_issue147_release.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="no test cases"):
        record_issue147_release.run_tests(ROOT)
