"""Negative controls for the Issue 159 recorder and coverage selector.

The historical 8ea90841 receipt claimed "manifest matched" while the manifest
comparator exited 1 with 71 differences on stderr. These controls pin the
honest behaviour: a comparator error, a stderr-only difference and an
unsupported mapped case must never be reported as demonstrated support.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RECORDER = ROOT / "scripts/ci/record_issue159_release.py"
_spec = importlib.util.spec_from_file_location(
    "record_issue159_release", str(_RECORDER)
)
recorder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recorder)

REVISION = "8ea90841b83ddd9565730581101993c3448945f0"


def _write_report(tmp_path):
    report = {
        "schema_version": 1,
        "suite_commit": "cf38585fac5de8e0e90112febb62851ee2181816",
        "source_provenance": {
            "bng3_commit": REVISION,
            "bng3_tracked_worktree_clean": True,
        },
        "partial_run": False,
        "counts": {
            "passed": 1817,
            "unsupported": 106,
            "failed": 0,
            "timeout": 0,
            "invalid-source": 0,
        },
        "official_conformance": {"counts": {"failed": 0, "timed-out": 0}},
        "case_inventory": 1923,
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    expectations = tmp_path / "expectations.json"
    expectations.write_text("{}")
    return path, expectations


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_recorder(tmp_path, monkeypatch, completed):
    report_path, expectations = _write_report(tmp_path)
    monkeypatch.setattr(recorder.subprocess, "run", lambda *a, **k: completed)
    return recorder.build_release_report(report_path, expectations, REVISION)


def test_comparator_error_is_not_reported_as_matched(tmp_path, monkeypatch):
    completed = _Completed(
        returncode=1,
        stderr=(
            "71 expectation difference(s):\n"
            "  semantic/00963 [official_reference]: expected passed, observed unsupported (regression)\n"
            "  semantic/00761 [conversion]: expected unsupported, observed passed (improvement)\n"
        ),
    )
    receipt = _run_recorder(tmp_path, monkeypatch, completed)
    mc = receipt["manifest_comparison"]
    assert mc["exit_code"] == 1
    assert mc["matched"] is False
    assert mc["difference_count"] == 2
    assert mc["regression_count"] == 1
    assert "semantic/00963" in mc["stderr_tail"]
    detail = {r["id"]: r["detail"] for r in receipt["results"]}["release-ssts"]
    assert "manifest matched" not in detail
    assert "NOT matched" in detail


def test_clean_comparator_is_reported_as_matched(tmp_path, monkeypatch):
    receipt = _run_recorder(tmp_path, monkeypatch, _Completed(returncode=0, stdout=""))
    mc = receipt["manifest_comparison"]
    assert mc["matched"] is True
    assert mc["difference_count"] == 0
    detail = {r["id"]: r["detail"] for r in receipt["results"]}["release-ssts"]
    assert detail.endswith("manifest matched")


def test_stdout_only_differences_are_counted_too(tmp_path, monkeypatch):
    # A comparator variant that emits differences on stdout must still be seen.
    receipt = _run_recorder(
        tmp_path,
        monkeypatch,
        _Completed(
            returncode=1,
            stdout="  semantic/00001 [conversion]: expected unsupported, observed passed (improvement)\n",
        ),
    )
    mc = receipt["manifest_comparison"]
    assert mc["matched"] is False
    assert mc["difference_count"] == 1


def _selector_module():
    path = ROOT / "tests/validation/release/cases/issue-159/test_ssts_full_execution.py"
    spec = importlib.util.spec_from_file_location(
        "issue159_selector_under_test", str(path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_report(tmp_path, status_for=None):
    mapping = json.loads((ROOT / "provenance/sbml-core-case-mapping.json").read_text())
    case_ids = sorted(
        {
            cid
            for row, cases in mapping.items()
            if not row.startswith("_")
            for cid in cases
        }
    )
    reports = {
        "records": [
            {
                "category": "semantic",
                "id": cid,
                "status": (status_for or {}).get(cid, "passed"),
            }
            for cid in case_ids
        ]
    }
    path = tmp_path / "ssts.json"
    path.write_text(json.dumps(reports))
    return path


def _synthetic_fixture_report(tmp_path, results=None):
    defaults = {
        "parameter-units": True,
        "constraint-message": True,
        "reaction-compartment": True,
        "localparameter-units": True,
    }
    defaults.update(results or {})
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps({"fixtures": defaults}))
    return path


def test_selector_rejects_unsupported_mapped_case(tmp_path, monkeypatch):
    mapping = json.loads((ROOT / "provenance/sbml-core-case-mapping.json").read_text())
    first_case = mapping["sbml.core.SBase.metaid"][0]
    report = _synthetic_report(tmp_path, {first_case: "unsupported"})
    fixtures = _synthetic_fixture_report(tmp_path)
    monkeypatch.setenv("BNG3_SSTS_FULL_REPORT", str(report))
    monkeypatch.setenv("BNG3_CORE_FIXTURES_REPORT", str(fixtures))
    selector = _selector_module()
    try:
        selector.test_release_ssts_coverage()
    except AssertionError as exc:
        assert "unsupported" in str(exc)
        assert first_case in str(exc)
    else:
        raise AssertionError("unsupported mapped case was accepted as coverage")


def test_selector_requires_fixture_execution_not_file_presence(tmp_path, monkeypatch):
    report = _synthetic_report(tmp_path)
    monkeypatch.setenv("BNG3_SSTS_FULL_REPORT", str(report))
    monkeypatch.delenv("BNG3_CORE_FIXTURES_REPORT", raising=False)
    selector = _selector_module()
    try:
        selector.test_release_ssts_coverage()
    except AssertionError as exc:
        assert "BNG3_CORE_FIXTURES_REPORT" in str(exc)
    else:
        raise AssertionError("fixture XML presence alone qualified a suite-absent row")


def test_selector_accepts_affirmative_evidence(tmp_path, monkeypatch):
    report = _synthetic_report(tmp_path)
    fixtures = _synthetic_fixture_report(tmp_path)
    monkeypatch.setenv("BNG3_SSTS_FULL_REPORT", str(report))
    monkeypatch.setenv("BNG3_CORE_FIXTURES_REPORT", str(fixtures))
    selector = _selector_module()
    selector.test_release_ssts_coverage()
