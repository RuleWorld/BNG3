"""Negative controls for the Issue 164 release recorder.

The historical recorder promoted a bounded symbol-resolution characterization
run to PASS for the full refactor checks, and hard-coded ``dirty: false`` even
when ``--allow-dirty`` was used. These controls pin that a partial result, a
missing artifact, a skipped test, a stale report or a dirty checkout cannot
satisfy a full release check.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "record_issue164_release", ROOT / "scripts/ci/record_issue164_release.py"
)
recorder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(recorder)

from tests.validation import atomizer_characterization as characterization  # noqa: E402

REVISION = "a" * 40
BEFORE_REVISION = "b" * 40


def _write_junit(tmp_path: Path, name: str, *, skipped=False, failed=False) -> Path:
    suite = ET.Element(
        "testsuite",
        {
            "name": "gate",
            "tests": "1",
            "failures": "1" if failed else "0",
            "errors": "0",
            "skipped": "1" if skipped else "0",
        },
    )
    case = ET.SubElement(suite, "testcase", {"name": name})
    if skipped:
        ET.SubElement(case, "skipped", {"message": "not run"})
    if failed:
        ET.SubElement(case, "failure", {"message": "failed"})
    path = (
        tmp_path / f"{name}-{'skip' if skipped else 'fail' if failed else 'pass'}.xml"
    )
    ET.ElementTree(suite).write(path)
    return path


def _write_comparison(
    tmp_path: Path,
    *,
    revision=REVISION,
    full=True,
    pins=None,
    all_match=True,
    missing=False,
    stale_ref=False,
) -> Path:
    pins = (
        pins
        if pins is not None
        else {"suite_revision": "cf38585f", "biomodels_corpus_revision": "1234567"}
    )
    refs = {
        "ssts": {"revision": "cf38585f", "sha256": "c" * 64},
        "biomodels": {"revision": "1234567", "sha256": "d" * 64},
    }
    if stale_ref:
        refs["ssts"]["revision"] = "stale-suite"
    counts = {"failed": 0, "timeout": 0, "invalid_source": 0, "skipped": 0}
    if missing:
        counts["failed"] = 2
    document = {
        "schema_version": 1,
        "before": {
            "source": {"revision": BEFORE_REVISION, "dirty": False},
            "full_run": True,
            "report_sha256": "e" * 64,
            "pins": pins,
        },
        "after": {
            "source": {"revision": revision, "dirty": False},
            "full_run": full,
            "report_sha256": "f" * 64,
            "pins": pins,
        },
        "references": refs,
        "reference_laws": {
            "independent": True,
            "detail": "official SSTS + libRoadRunner",
        },
        "counts": counts,
        "record_comparison": {
            "all_match": all_match,
            "missing": [],
            "extra": [],
            "status_changed": [],
            "stale": [],
        },
    }
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps(document))
    return path


def _run(tmp_path: Path, monkeypatch, *, dirty=False, allow_dirty=True, **evidence):
    output = tmp_path / "receipt.json"

    def fake_check_output(argv, **kwargs):
        if "rev-parse" in argv:
            return REVISION
        if "status" in argv:
            return " M touched.py\n" if dirty else ""
        raise AssertionError(f"unexpected subprocess: {argv}")

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(
        characterization,
        "run_worker",
        lambda *_a, **_k: [
            {"id": check, "status": "PASS"} for check in characterization.check_ids()
        ],
    )
    argv = [
        "--bng-cpp",
        str(tmp_path / "bng_cpp"),
        "--source-revision",
        REVISION,
        "--output",
        str(output),
    ]
    if allow_dirty:
        argv.append("--allow-dirty")
    for flag in ("architecture_report", "refactor_comparison", "honesty_report"):
        if flag in evidence and evidence[flag] is not None:
            argv += [f"--{flag.replace('_', '-')}", str(evidence[flag])]
    (tmp_path / "bng_cpp").write_bytes(b"fixture")
    recorder.main(argv)
    return json.loads(output.read_text())


def _rows(receipt):
    return {row["id"]: row for row in receipt["results"]}


def test_characterization_cannot_certify_full_refactor(tmp_path, monkeypatch):
    receipt = _run(tmp_path, monkeypatch)
    rows = _rows(receipt)
    assert all(rows[c]["status"] == "PASS" for c in characterization.check_ids())
    for check in recorder.LIVE_CHECKS + (recorder.BOUNDARY_CHECK,):
        assert rows[check]["status"] == "NOT_TESTED"
        assert rows[check]["supported_execution"] is False
    assert receipt["source"]["dirty"] is False


def test_dirty_checkout_is_reported_dirty(tmp_path, monkeypatch):
    receipt = _run(tmp_path, monkeypatch, dirty=True, allow_dirty=True)
    assert receipt["source"]["dirty"] is True
    assert all(
        _rows(receipt)[c]["status"] == "NOT_TESTED" for c in recorder.LIVE_CHECKS
    )


def test_dirty_checkout_without_allow_dirty_is_refused(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="clean checkout"):
        _run(tmp_path, monkeypatch, dirty=True, allow_dirty=False)
    assert not (tmp_path / "receipt.json").exists()


def test_skipped_or_failed_junit_cannot_certify_architecture(tmp_path, monkeypatch):
    for kwargs in ({"skipped": True}, {"failed": True}):
        sub = tmp_path / ("skip" if kwargs.get("skipped") else "fail")
        sub.mkdir()
        junit = _write_junit(sub, recorder.ARCHITECTURE_TESTS[0], **kwargs)
        # Use a separate output directory so the two cases do not collide.
        receipt = _run(sub, monkeypatch, architecture_report=junit)
        assert _rows(receipt)["release-atomizer-modules"]["status"] == "NOT_TESTED"
        assert _rows(receipt)["release-obligation-164"]["status"] == "NOT_TESTED"


def test_partial_before_after_report_is_rejected(tmp_path, monkeypatch):
    comparison = _write_comparison(tmp_path, missing=True)
    receipt = _run(tmp_path, monkeypatch, refactor_comparison=comparison)
    assert _rows(receipt)["release-atomizer-refactor"]["status"] == "NOT_TESTED"
    assert any("failed" in gap for gap in receipt["evidence_gaps"])


def test_stale_or_partial_run_comparison_is_rejected(tmp_path, monkeypatch):
    stale = _write_comparison(tmp_path, stale_ref=True)
    partial = _write_comparison(tmp_path, full=False)
    for comparison in (stale, partial):
        receipt = _run(tmp_path, monkeypatch, refactor_comparison=comparison)
        assert _rows(receipt)["release-atomizer-refactor"]["status"] == "NOT_TESTED"


def test_full_evidence_set_certifies_live_checks(tmp_path, monkeypatch):
    architecture = _write_junit(tmp_path, recorder.ARCHITECTURE_TESTS[0])
    honesty_dir = tmp_path / "honesty"
    honesty_dir.mkdir()
    # Build a single JUnit file containing every required honesty test.
    honesty = honesty_dir / "honesty.xml"
    suite = ET.Element(
        "testsuite",
        {
            "name": "honesty",
            "tests": str(len(recorder.HONESTY_TESTS)),
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    for name in recorder.HONESTY_TESTS:
        ET.SubElement(suite, "testcase", {"name": name})
    ET.ElementTree(suite).write(honesty)
    comparison = _write_comparison(tmp_path)
    receipt = _run(
        tmp_path,
        monkeypatch,
        architecture_report=architecture,
        refactor_comparison=comparison,
        honesty_report=honesty,
    )
    rows = _rows(receipt)
    for check in recorder.LIVE_CHECKS + (recorder.BOUNDARY_CHECK,):
        assert rows[check]["status"] == "PASS"
        assert rows[check]["supported_execution"] is True
    assert receipt["references"]["refactor_comparison_sha256"]
