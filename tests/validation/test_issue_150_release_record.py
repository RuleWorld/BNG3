"""Tests for Issue 150 hybrid particle-population release acceptance recorder."""

from __future__ import annotations

import hashlib
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
        assert row["status"] == "NOT_TESTED"
        assert row["supported_execution"] is False
        assert row["evidence_kind"] == "not-tested"

    out_file = tmp_path / "hybrid_report.json"
    out_file.write_text(json.dumps(report), encoding="utf-8")

    manifest = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue_150 = next(i for i in manifest["issues"] if i["number"] == 150)
    # Clear dependencies for isolated check assessment
    obs = [dict(ob, dependencies=[]) for ob in issue_150["obligations"]]
    assessed = issue_queue.assess_obligations(
        obs, [report], report["source"]["revision"]
    )["obligations"]
    for ob in assessed:
        if "live-acceptance" in ob["id"]:
            assert ob["status"] != "DEMONSTRATED"
            for chk in ob["checks"]:
                assert chk["status"] == "NOT_TESTED"


def test_hybrid_release_record_verifies_junit_xml(tmp_path):
    # Valid JUnit XML
    valid_xml = tmp_path / "valid.xml"
    valid_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="0" skipped="0" tests="4">
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_bng2_native_nfsim_and_bng3_trajectories" time="1.0"/>
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_conservation_and_analytic_conversion_law" time="1.0"/>
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_capability_coverage_150" time="1.0"/>
    <testcase classname="tests.validation.test_hybrid_execution" name="test_release_hybrid_stage_continuation" time="1.0"/>
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

    revision = "a" * 40
    cov = {
        "source": {"revision": revision, "dirty": False},
        "semantic_checks": {
            "release-hybrid": {"passed": True},
            "release-hybrid-conservation": {"passed": True},
        },
    }
    (ev_dir / "capability-coverage-150.json").write_text(
        json.dumps(cov), encoding="utf-8"
    )

    assert record_hybrid_release.verify_evidence_directory(ev_dir, revision) == {
        "release-hybrid",
        "release-hybrid-conservation",
    }
    with pytest.raises(ValueError, match="stale or dirty"):
        record_hybrid_release.verify_evidence_directory(ev_dir, "b" * 40)

    # Corrupt qualification
    qual_bad = {"distributional_comparison": {"passed": False}}
    (ev_dir / "qualification.json").write_text(json.dumps(qual_bad), encoding="utf-8")
    with pytest.raises(ValueError, match="distributional comparison failed"):
        record_hybrid_release.verify_evidence_directory(ev_dir, revision)


@pytest.mark.parametrize(
    "defect",
    [
        "partial",
        "absent_summary",
        "missing_row",
        "missing_case",
        "failed_case",
        "wrong_oracle",
        "wrong_pin",
        "corrupt_replay",
        None,
    ],
)
def test_hybrid_release_record_requires_affirmative_complete_coverage(tmp_path, defect):
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    checks = {
        "release-hybrid": {"passed": True},
        "release-hybrid-conservation": {"passed": True},
    }
    if defect != "absent_summary":
        checks["release-capability-coverage-150"] = {"passed": True}
    contract = json.loads(
        (ROOT / "tests/validation/release/cases/issue-150/contract.json").read_text()
    )
    artifact = tmp_path / "replay.csv"
    artifact.write_text("time,A,B\n0,5,0\n")
    replay = {artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest()}
    if defect == "corrupt_replay":
        artifact.write_text("corrupt")
    cases = {
        identity: {"passed": True, "oracle": "bng2-options", "artifacts": replay}
        for identity in contract["inventory_rows"]
    }
    execution = {
        name: {"passed": True, "oracle": oracle, "artifacts": replay}
        for name, oracle in contract["hybrid_execution_cases"].items()
    }
    cases["hybrid.execution"] = {"passed": True, "cases": execution}
    if defect == "missing_row":
        del cases["hybrid.execution"]
    elif defect == "missing_case":
        del execution["stage_compartment_graph_and_counts"]
    elif defect == "failed_case":
        execution["stage_bngl_protocol"]["passed"] = False
    elif defect == "wrong_oracle":
        execution["stage_native_rate_change"]["oracle"] = "bng3"
    pins = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())["sources"]
    oracles = {
        "bng2": {"revision": pins["bionetgen"]["revision"], "script_sha256": "a" * 64},
        "native_nfsim": {
            "revision": pins["nfsim"]["revision"],
            "binary_sha256": "b" * 64,
        },
    }
    if defect == "wrong_pin":
        oracles["native_nfsim"]["revision"] = "0" * 40
    (tmp_path / "capability-coverage-150.json").write_text(
        json.dumps(
            {
                "source": {"revision": revision, "dirty": False},
                "issue_150_acceptance": (
                    "partial" if defect == "partial" else "complete"
                ),
                "semantic_checks": checks,
                "oracles": oracles,
                "inventory_cases": cases,
            }
        ),
        encoding="utf-8",
    )

    receipt = record_hybrid_release.build_release_record(
        expected_revision=revision, evidence_dir=tmp_path, root=ROOT, allow_dirty=True
    )

    results = {row["id"]: row for row in receipt["results"]}
    assert results["release-hybrid"]["status"] == "PASS"
    assert results["release-hybrid-conservation"]["status"] == "PASS"
    coverage = results["release-capability-coverage-150"]
    assert coverage["status"] == ("PASS" if defect is None else "NOT_TESTED")
    assert coverage["supported_execution"] is (defect is None)


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


def test_hybrid_record_require_complete_writes_partial_report_but_fails(tmp_path):
    out = tmp_path / "report.json"
    assert (
        record_hybrid_release.main(
            [
                "--output",
                str(out),
                "--skip-tests",
                "--allow-dirty",
                "--require-complete",
            ]
        )
        == 1
    )
    assert {result["status"] for result in json.loads(out.read_text())["results"]} == {
        "NOT_TESTED"
    }
