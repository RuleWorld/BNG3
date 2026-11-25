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


def _pins():
    return json.loads((REPO / "provenance/upstreams.lock.yml").read_text())["sources"]


def test_bng2_mode_grounds_five_rows_and_fails_closed(tmp_path, monkeypatch):
    pins = _pins()
    monkeypatch.setattr(
        recorder,
        "_verify_pin",
        lambda root, name, checkout: pins[name]["revision"],
    )
    monkeypatch.setattr(
        recorder,
        "_run",
        lambda cmd, *, cwd=REPO, env=None: subprocess.CompletedProcess(
            cmd, 0, "1 passed", ""
        ),
    )
    refs, results = recorder.run_bng2(
        REPO, bng_cpp=tmp_path / "bng_cpp", bng2_root=tmp_path / "bng2"
    )
    by_id = {row["id"]: row for row in results}
    assert set(by_id) == {
        "release-capability[bngl.ast.model]",
        "release-capability[bngl.observables.counting-modes]",
        "release-capability[expression.builtins.shared-table]",
        "release-capability[io.sbml.structured-bng2]",
        "release-capability[bngl.actions.setoption]",
    }
    assert all(
        row["status"] == "PASS" and row["supported_execution"] for row in results
    )
    assert refs["bionetgen"]["revision"] == pins["bionetgen"]["revision"]

    def fail_setoption(cmd, *, cwd=REPO, env=None):
        rc = 1 if "test_export_formats.py" in " ".join(cmd) else 0
        return subprocess.CompletedProcess(cmd, rc, "sim", "")

    monkeypatch.setattr(recorder, "_run", fail_setoption)
    _, fail_results = recorder.run_bng2(
        REPO, bng_cpp=tmp_path / "bng_cpp", bng2_root=tmp_path / "bng2"
    )
    fail_by_id = {row["id"]: row for row in fail_results}
    assert fail_by_id["release-capability[bngl.actions.setoption]"]["status"] == "FAIL"
    assert (
        fail_by_id["release-capability[bngl.actions.setoption]"]["supported_execution"]
        is False
    )


def test_nfsim_mode_grounds_eight_rows_and_requires_oracles(tmp_path, monkeypatch):
    pins = _pins()
    monkeypatch.setattr(
        recorder,
        "_verify_pin",
        lambda root, name, checkout: pins[name]["revision"],
    )
    monkeypatch.setattr(
        recorder,
        "_run",
        lambda cmd, *, cwd=REPO, env=None: subprocess.CompletedProcess(
            cmd, 0, "1 passed", ""
        ),
    )
    refs, results = recorder.run_nfsim(
        REPO,
        nfsim_root=tmp_path / "nfsim",
        nfsim_bin=tmp_path / "NFsim",
        bng2_root=tmp_path / "bng2",
        bng_cpp=tmp_path / "bng_cpp",
    )
    by_id = {row["id"]: row for row in results}
    assert set(by_id) == {
        "release-capability[nfsim.molecule-types]",
        "release-capability[nfsim.seed-species]",
        "release-capability[nfsim.observables]",
        "release-capability[nfsim.energy-and-time-functions]",
        "release-capability[nfsim.options.parameters]",
        "release-capability[nfsim.compartments]",
        "release-capability[nfsim.reaction-rules]",
        "release-capability[nfsim.global-functions.safe-subset]",
    }
    assert all(
        row["status"] == "PASS" and row["supported_execution"] for row in results
    )
    assert refs["nfsim"]["revision"] == pins["nfsim"]["revision"]
    assert refs["bionetgen"]["revision"] == pins["bionetgen"]["revision"]

    # Without --bng2-root, the new NFsim rows must fail closed rather than pass.
    no_bng2_refs, no_bng2_results = recorder.run_nfsim(
        REPO, nfsim_root=tmp_path / "nfsim", nfsim_bin=tmp_path / "NFsim"
    )
    assert "bionetgen" not in no_bng2_refs
    no_bng2_by_id = {row["id"]: row for row in no_bng2_results}
    for missing_row in (
        "nfsim.options.parameters",
        "nfsim.compartments",
        "nfsim.reaction-rules",
        "nfsim.global-functions.safe-subset",
    ):
        assert no_bng2_by_id[f"release-capability[{missing_row}]"]["status"] == "FAIL"
        assert (
            no_bng2_by_id[f"release-capability[{missing_row}]"]["supported_execution"]
            is False
        )


def test_combined_sixteen_rows_satisfy_issue137_coverage(tmp_path, monkeypatch):
    pins = _pins()
    revision = recorder._git_head(REPO)
    monkeypatch.setattr(
        recorder,
        "_verify_pin",
        lambda root, name, checkout: pins[name]["revision"],
    )
    monkeypatch.setattr(
        recorder,
        "_run",
        lambda cmd, *, cwd=REPO, env=None: subprocess.CompletedProcess(
            cmd, 0, "1 passed", ""
        ),
    )
    struct_refs, struct_results = recorder.run_structural(REPO)
    bng2_refs, bng2_results = recorder.run_bng2(
        REPO, bng_cpp=tmp_path / "bng_cpp", bng2_root=tmp_path / "bng2"
    )
    nfsim_refs, nfsim_results = recorder.run_nfsim(
        REPO,
        nfsim_root=tmp_path / "nfsim",
        nfsim_bin=tmp_path / "NFsim",
        bng2_root=tmp_path / "bng2",
        bng_cpp=tmp_path / "bng_cpp",
    )
    pybng_report = {
        "schema_version": 1,
        "source": {"revision": revision, "dirty": False},
        "references": {"pybionetgen": {"revision": pins["pybionetgen"]["revision"]}},
        "results": [
            {
                "id": "release-capability[pybionetgen.api-cli-atomizer]",
                "status": "PASS",
                "evidence_kind": "supported-execution",
                "supported_execution": True,
                "related_issues": [137],
            }
        ],
    }
    reports = [
        {
            "schema_version": 1,
            "source": {"revision": revision, "dirty": False},
            "references": refs,
            "results": results,
        }
        for refs, results in (
            (struct_refs, struct_results),
            (bng2_refs, bng2_results),
            (nfsim_refs, nfsim_results),
        )
    ] + [pybng_report]
    assert issue137_checks.coverage_gaps(reports, revision, REPO) == []
