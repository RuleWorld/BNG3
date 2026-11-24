"""Tests for Issue 154 BNGIR round trip and version migration release acceptance recorder."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.ci import record_bngir_roundtrip_release
from tests.validation import issue_queue

ROOT = Path(__file__).resolve().parents[2]


def test_bngir_roundtrip_release_record_verifies_manifest():
    manifest_checks = record_bngir_roundtrip_release.verify_manifest(ROOT)
    assert set(manifest_checks.keys()) == {
        "release-bngir-roundtrip",
        "release-bngir-version",
        "release-obligation-154",
    }


def test_bngir_roundtrip_release_record_rejects_stale_revision():
    with pytest.raises(ValueError, match="stale"):
        record_bngir_roundtrip_release.build_release_record(
            expected_revision="0" * 40,
            root=ROOT,
            skip_tests=True,
        )


def test_bngir_roundtrip_release_record_rejects_dirty_checkout(monkeypatch):
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
        record_bngir_roundtrip_release.build_release_record(
            root=ROOT,
            skip_tests=True,
            allow_dirty=False,
        )


def test_bngir_roundtrip_release_record_builds_valid_report(tmp_path):
    report = record_bngir_roundtrip_release.build_release_record(
        root=ROOT, skip_tests=True, allow_dirty=True
    )
    assert report["schema_version"] == 1
    assert report["acceptance_check"] == "release-obligation-154"
    assert len(report["results"]) == 3
    for row in report["results"]:
        assert row["status"] == "NOT_TESTED"
        assert row["supported_execution"] is False
        assert row["evidence_kind"] == "not-tested"

    out_file = tmp_path / "issue154_report.json"
    out_file.write_text(json.dumps(report), encoding="utf-8")

    manifest = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue_154 = next(i for i in manifest["issues"] if i["number"] == 154)
    obs = [dict(ob, dependencies=[]) for ob in issue_154["obligations"]]
    assessed = issue_queue.assess_obligations(
        obs, [report], report["source"]["revision"]
    )["obligations"]
    for ob in assessed:
        if "live-acceptance" in ob["id"]:
            assert ob["status"] != "DEMONSTRATED"
            for chk in ob["checks"]:
                assert chk["status"] == "NOT_TESTED"


def test_bngir_roundtrip_record_cli(tmp_path):
    out_file = tmp_path / "report.json"
    summary_file = tmp_path / "summary.md"
    ret = record_bngir_roundtrip_release.main(
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
    assert data["acceptance_check"] == "release-obligation-154"


def test_bounded_native_roundtrip_cannot_qualify_all_constructs(monkeypatch):
    monkeypatch.setattr(record_bngir_roundtrip_release, "run_tests", lambda root: None)
    report = record_bngir_roundtrip_release.build_release_record(
        root=ROOT, allow_dirty=True
    )
    results = {row["id"]: row for row in report["results"]}
    assert results["release-bngir-roundtrip"]["status"] == "NOT_TESTED"
    assert not results["release-bngir-roundtrip"]["supported_execution"]
    # run_tests was replaced by a no-op, so no BNGIR version test executed.
    # A PASS here would certify an unexecuted check.
    assert results["release-bngir-version"]["status"] == "NOT_TESTED"
    assert not results["release-bngir-version"]["supported_execution"]
