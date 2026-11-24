"""Controls and real structural execution checks for record_issue137_cases."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "scripts/ci"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue137_checks  # noqa: E402
import record_issue137_cases as recorder  # noqa: E402


def test_structural_mode_executes_and_grounds_both_structural_rows(tmp_path):
    report_path = tmp_path / "structural.json"
    rev = recorder._git_head(REPO)
    rc = recorder.main(
        [
            "--mode",
            "structural",
            "--root",
            str(REPO),
            "--revision",
            rev,
            "--report",
            str(report_path),
            "--allow-dirty",
        ]
    )
    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["source"]["dirty"] = False
    by_id = {row["id"]: row for row in report["results"]}
    assert set(by_id) == {
        "release-capability[core.graph.canonicalization.single-nauty]",
        "release-capability[validation.oracles-goldens-release]",
    }
    assert all(row["status"] == "PASS" for row in by_id.values())
    assert all(row["supported_execution"] is True for row in by_id.values())
    gaps = issue137_checks.coverage_gaps([report], rev, REPO)
    assert not any("single-nauty" in gap for gap in gaps)
    assert not any("oracles-goldens-release" in gap for gap in gaps)
    assert len(gaps) == 14


def test_structural_mode_fails_closed_when_selector_fails(tmp_path, monkeypatch):
    def fake_run(command, *, cwd=REPO, env=None):
        return subprocess.CompletedProcess(command, 1, "", "simulated failure")

    monkeypatch.setattr(recorder, "_run", fake_run)
    _, results = recorder.run_structural(REPO)
    assert all(row["status"] == "FAIL" for row in results)
    assert all(row["supported_execution"] is False for row in results)


def test_recorder_refuses_stale_revision(tmp_path):
    with pytest.raises(SystemExit):
        recorder.main(
            [
                "--mode",
                "structural",
                "--root",
                str(REPO),
                "--revision",
                "0" * 40,
                "--report",
                str(tmp_path / "stale.json"),
            ]
        )
