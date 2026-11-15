"""Tests for Issue 473 and Issue 475 release acceptance recorders."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ci import record_delay_release, record_jax_release
from tests.validation import issue_queue

ROOT = Path(__file__).resolve().parents[2]


def test_delay_release_record_verifies_manifest():
    manifest_checks = record_delay_release.verify_manifest(ROOT)
    assert set(manifest_checks.keys()) == {
        "release-delay-ode",
        "release-delay-ssa",
        "release-delay-formats",
    }


def test_jax_release_record_verifies_manifest():
    manifest_checks = record_jax_release.verify_manifest(ROOT)
    assert set(manifest_checks.keys()) == {
        "release-jax-ode",
        "release-jax-ssa",
        "release-jax-install",
    }


def test_delay_release_record_rejects_stale_revision():
    with pytest.raises(ValueError, match="stale"):
        record_delay_release.build_release_record(
            expected_revision="0" * 40,
            root=ROOT,
            skip_tests=True,
        )


def test_jax_release_record_rejects_stale_revision():
    with pytest.raises(ValueError, match="stale"):
        record_jax_release.build_release_record(
            expected_revision="0" * 40,
            root=ROOT,
            skip_tests=True,
        )


def test_delay_release_record_rejects_dirty_checkout(monkeypatch):
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
        record_delay_release.build_release_record(
            root=ROOT,
            skip_tests=True,
            allow_dirty=False,
        )


def test_jax_release_record_rejects_dirty_checkout(monkeypatch):
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
        record_jax_release.build_release_record(
            root=ROOT,
            skip_tests=True,
            allow_dirty=False,
        )


def test_delay_release_record_builds_valid_report(tmp_path):
    report = record_delay_release.build_release_record(
        root=ROOT, skip_tests=True, allow_dirty=True
    )
    assert report["schema_version"] == 1
    assert report["acceptance_check"] == "release-obligation-475"
    assert len(report["results"]) == 3
    for row in report["results"]:
        assert row["status"] == "PASS"
        assert row["supported_execution"] is True
        assert row["evidence_kind"] == "supported-execution"

    out_file = tmp_path / "delay_report.json"
    out_file.write_text(json.dumps(report))

    manifest = json.loads((ROOT / "provenance/issue-obligations.json").read_text())
    issue_475 = next(i for i in manifest["issues"] if i["number"] == 475)
    assessed = issue_queue.assess_obligations(
        issue_475["obligations"], [report], report["source"]["revision"]
    )["obligations"]
    for ob in assessed:
        for chk in ob["checks"]:
            assert chk["status"] == "PASS"
            assert chk["missing_evidence"] == []


def test_jax_release_record_builds_valid_report(tmp_path):
    report = record_jax_release.build_release_record(
        root=ROOT, skip_tests=True, allow_dirty=True
    )
    assert report["schema_version"] == 1
    assert report["acceptance_check"] == "release-obligation-473"
    assert len(report["results"]) == 3
    for row in report["results"]:
        assert row["status"] == "PASS"
        assert row["supported_execution"] is True
        assert row["evidence_kind"] == "supported-execution"

    out_file = tmp_path / "jax_report.json"
    out_file.write_text(json.dumps(report))

    manifest = json.loads((ROOT / "provenance/issue-obligations.json").read_text())
    issue_473 = next(i for i in manifest["issues"] if i["number"] == 473)
    assessed = issue_queue.assess_obligations(
        issue_473["obligations"], [report], report["source"]["revision"]
    )["obligations"]
    for ob in assessed:
        for chk in ob["checks"]:
            assert chk["status"] == "PASS"
            assert chk["missing_evidence"] == []


def test_delay_record_cli(tmp_path):
    out_file = tmp_path / "report.json"
    summary_file = tmp_path / "summary.md"
    ret = record_delay_release.main(
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
    data = json.loads(out_file.read_text())
    assert data["acceptance_check"] == "release-obligation-475"


def test_jax_record_cli(tmp_path):
    out_file = tmp_path / "report.json"
    summary_file = tmp_path / "summary.md"
    ret = record_jax_release.main(
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
    data = json.loads(out_file.read_text())
    assert data["acceptance_check"] == "release-obligation-473"
