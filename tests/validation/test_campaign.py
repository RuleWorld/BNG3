"""Fault injection for campaign bookkeeping and independent reference guards."""

import sys
import subprocess
import os
import json
from pathlib import Path

import pytest

from tests.validation import campaign


def test_successful_process_with_missing_output_is_harness_error(tmp_path):
    result = campaign.run_command(
        [sys.executable, "-c", "print('success')"], tmp_path, 5, required=["result.net"]
    )
    assert result["status"] == "HARNESS_ERROR"
    assert "result.net" in result["detail"]
    assert (tmp_path / "stdout.log").read_text().strip() == "success"


def test_timeout_is_not_a_semantic_failure(tmp_path):
    result = campaign.run_command(
        [sys.executable, "-c", "import time;time.sleep(5)"], tmp_path, 0.05
    )
    assert result["status"] == "TIMEOUT"


def test_junit_preserves_skips_errors_and_individual_failures(tmp_path):
    p = tmp_path / "results.xml"
    p.write_text(
        '<testsuites><testsuite tests="4"><testcase classname="a" name="ok"/><testcase classname="a" name="skip"><skipped message="no oracle"/></testcase><testcase classname="a" name="bad"><failure message="rate mismatch"/></testcase><testcase classname="a" name="broken"><error message="import"/></testcase></testsuite></testsuites>'
    )
    rows = campaign.read_junit(p, "suite")
    assert [r["status"] for r in rows] == [
        "PASS",
        "NOT_TESTED",
        "FAIL",
        "HARNESS_ERROR",
    ]
    assert rows[2]["detail"] == "rate mismatch"


def test_empty_or_malformed_junit_cannot_pass(tmp_path):
    p = tmp_path / "results.xml"
    p.write_text("<testsuites/>")
    with pytest.raises(ValueError, match="no test cases"):
        campaign.read_junit(p, "suite")
    p.write_text("broken")
    with pytest.raises(ValueError):
        campaign.read_junit(p, "suite")


def test_identical_reference_and_subject_content_is_rejected(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"same engine")
    b.write_bytes(a.read_bytes())
    with pytest.raises(ValueError, match="same implementation"):
        campaign.reject_shared_engine(a, b)


def test_embedded_different_binary_is_not_an_independent_reference(tmp_path):
    root = tmp_path / "subject"
    root.mkdir()
    a, b = root / "bng_cpp", root / "NFsim"
    a.write_bytes(b"CLI")
    b.write_bytes(b"embedded NFsim")
    with pytest.raises(ValueError, match="embedded"):
        campaign.reject_shared_engine(a, b, implementation_root=root)


def test_manifest_drift_is_not_silent_selection(tmp_path):
    p = tmp_path / "m.bngl"
    p.write_text("changed")
    with pytest.raises(ValueError, match="digest"):
        campaign.verify_digest(p, "0" * 64)


def test_timeout_preserves_completed_failure_names_and_unfinished_cases(tmp_path):
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "test_partial.py"
    source.write_text(
        'import time\ndef test_bad(): assert False, "injected rate mismatch"\ndef test_wait(): time.sleep(30)\n'
    )
    events = tmp_path / "events.jsonl"
    env = {**os.environ, "BNG3_TEST_EVENT_LOG": str(events)}
    result = campaign.run_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.validation.pytest_evidence",
            str(source),
            "-q",
        ],
        tmp_path / "work",
        3,
        env=env,
        cwd=root,
    )
    assert result["status"] == "TIMEOUT"
    rows = campaign.read_pytest_events(events, "partial")
    assert any(
        "test_bad" in r["id"]
        and r["status"] == "FAIL"
        and "injected rate mismatch" in r["detail"]
        for r in rows
    )
    assert any("test_wait" in r["id"] and r["status"] != "PASS" for r in rows)


def test_truncated_stream_tail_does_not_erase_completed_failure(tmp_path):
    path = tmp_path / "events.jsonl"
    event = {
        "event": "case",
        "nodeid": "test_a.py::test_bad",
        "file": "test_a.py",
        "when": "call",
        "outcome": "failed",
        "duration": 0.1,
        "detail": "known mismatch",
    }
    path.write_text(json.dumps(event) + '\n{"event":')
    rows = campaign.read_pytest_events(path, "partial")
    assert any(r["status"] == "FAIL" and "test_bad" in r["id"] for r in rows)
    assert any(r["status"] == "HARNESS_ERROR" for r in rows)


def test_reference_source_checks_revision_remote_and_dirty_tree(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.org")
    git("config", "user.name", "Test")
    git("remote", "add", "origin", "https://github.com/RuleWorld/bionetgen.git")
    (tmp_path / "BNG2.pl").write_text("pinned")
    git("add", "BNG2.pl")
    git("commit", "-qm", "fixture")
    source = {
        "revision": git("rev-parse", "HEAD"),
        "repository": "https://github.com/RuleWorld/bionetgen.git",
    }
    assert campaign.verify_source(tmp_path, source)["revision"] == source["revision"]
    with pytest.raises(ValueError, match="revision"):
        campaign.verify_source(tmp_path, {**source, "revision": "0" * 40})
    (tmp_path / "BNG2.pl").write_text("mutated")
    with pytest.raises(ValueError, match="dirty"):
        campaign.verify_source(tmp_path, source)


def test_streamed_failure_keeps_concise_assertion_separate_from_full_traceback(
    tmp_path,
):
    path = tmp_path / "events.jsonl"
    events = [
        {
            "event": "collection",
            "cases": [{"nodeid": "test_x.py::test_rate", "file": "test_x.py"}],
        },
        {
            "event": "case",
            "nodeid": "test_x.py::test_rate",
            "file": "test_x.py",
            "when": "call",
            "outcome": "failed",
            "duration": 0.1,
            "detail": "full traceback with setup context",
            "summary": "A(t=0.05): expected 9.97, actual 10.0",
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    row = campaign.read_pytest_events(path, "probes")[0]
    assert row["failure_summary"] == "A(t=0.05): expected 9.97, actual 10.0"
    assert row["detail"] == "full traceback with setup context"
