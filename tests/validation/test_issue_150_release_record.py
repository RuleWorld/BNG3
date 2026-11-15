"""Tests for Issue 150 hybrid particle-population release acceptance recorder."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ci import record_hybrid_release
from tests.validation import issue_queue

ROOT = Path(__file__).resolve().parents[2]


def test_hybrid_release_record_verifies_manifest():
    manifest_checks = record_hybrid_release.verify_manifest(ROOT)
    assert set(manifest_checks.keys()) == {
        "release-hybrid",
        "release-hybrid-conservation",
        "release-capability-coverage-150",
    }


def test_hybrid_release_record_rejects_stale_revision():
    with pytest.raises(ValueError, match="stale"):
        record_hybrid_release.build_release_record(
            expected_revision="0" * 40,
            root=ROOT,
            skip_tests=True,
        )


def test_hybrid_release_record_rejects_dirty_checkout(monkeypatch):
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
        record_hybrid_release.build_release_record(
            root=ROOT,
            skip_tests=True,
            allow_dirty=False,
        )


def test_hybrid_release_record_builds_valid_report(tmp_path):
    report = record_hybrid_release.build_release_record(
        root=ROOT, skip_tests=True, allow_dirty=True
    )
    assert report["schema_version"] == 1
    assert report["acceptance_check"] == "release-obligation-150"
    assert len(report["results"]) == 3
    for row in report["results"]:
        assert row["status"] == "PASS"
        assert row["supported_execution"] is True
        assert row["evidence_kind"] == "supported-execution"

    out_file = tmp_path / "hybrid_report.json"
    out_file.write_text(json.dumps(report), encoding="utf-8")

    manifest = json.loads((ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8"))
    issue_150 = next(i for i in manifest["issues"] if i["number"] == 150)
    # Clear dependencies for isolated check assessment
    obs = [dict(ob, dependencies=[]) for ob in issue_150["obligations"]]
    assessed = issue_queue.assess_obligations(
        obs, [report], report["source"]["revision"]
    )["obligations"]
    for ob in assessed:
        if "live-acceptance" in ob["id"]:
            assert ob["status"] == "DEMONSTRATED"
            for chk in ob["checks"]:
                assert chk["status"] == "PASS"
                assert chk["missing_evidence"] == []


def test_hybrid_release_record_verifies_junit_xml(tmp_path):
    # Valid JUnit XML
    valid_xml = tmp_path / "valid.xml"
    valid_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="0" skipped="0" tests="3">
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_bng2_native_nfsim_and_bng3_trajectories" time="1.0"/>
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_conservation_and_analytic_conversion_law" time="1.0"/>
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_capability_coverage_150" time="1.0"/>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    record_hybrid_release.verify_junit_xml(valid_xml)

    # Failed case in XML
    failed_xml = tmp_path / "failed.xml"
    failed_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="1" skipped="0" tests="3">
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_bng2_native_nfsim_and_bng3_trajectories">
      <failure message="stochastic mismatch"/>
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="failed"):
        record_hybrid_release.verify_junit_xml(failed_xml)

    # Missing case in XML
    incomplete_xml = tmp_path / "incomplete.xml"
    incomplete_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1">
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_bng2_native_nfsim_and_bng3_trajectories"/>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing expected testcase"):
        record_hybrid_release.verify_junit_xml(incomplete_xml)


def test_hybrid_release_record_verifies_evidence_directory(tmp_path):
    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir()

    qual = {
        "distributional_comparison": {
            "passed": True,
            "violations": 0,
            "points_checked": 10,
        }
    }
    (ev_dir / "qualification.json").write_text(json.dumps(qual), encoding="utf-8")

    cov = {
        "semantic_checks": {
            "release-hybrid": {"passed": True},
            "release-hybrid-conservation": {"passed": True},
        }
    }
    (ev_dir / "capability-coverage-150.json").write_text(json.dumps(cov), encoding="utf-8")

    res = record_hybrid_release.verify_evidence_directory(ev_dir)
    assert res["evidence_verified"] is True

    # Corrupt qualification
    qual_bad = {"distributional_comparison": {"passed": False}}
    (ev_dir / "qualification.json").write_text(json.dumps(qual_bad), encoding="utf-8")
    with pytest.raises(ValueError, match="distributional comparison failed"):
        record_hybrid_release.verify_evidence_directory(ev_dir)


def test_hybrid_record_cli(tmp_path):
    out_file = tmp_path / "report.json"
    summary_file = tmp_path / "summary.md"
    ret = record_hybrid_release.main(
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
    assert data["acceptance_check"] == "release-obligation-150"
