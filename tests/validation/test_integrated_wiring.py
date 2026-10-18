"""Keep the cross-component generated regression lane reachable in CI."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "parity.yml"
SOURCE_HEAD = "${{ github.event.pull_request.head.sha || github.sha }}"


def test_integrated_validation_job_runs_locked_oracles_and_retains_strict_evidence():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["integrated-semantic-validation"]

    assert job["needs"] == "oracle-lock"
    assert job["timeout-minutes"] >= 30
    checkout = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["ref"] == SOURCE_HEAD

    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    for required in (
        "--name bionetgen",
        "--name nfsim",
        "--name pybionetgen",
        'make -C "$network3" -f Makefile.cmake',
        "--target NFsim",
        "pip install -r",
        "requirements.txt",
        "python -m tests.validation.integrated",
        "--bng-cpp",
        "--bng2-root",
        "--bng2-network-sha256",
        "--nfsim-root",
        "--nfsim-binary",
        "--nfsim-sha256",
        "--pybionetgen-root",
        "--pybionetgen-python",
        "--report-dir",
    ):
        assert required in commands, f"integrated validation job lost {required!r}"

    integrated = next(
        step
        for step in job["steps"]
        if step.get("name") == "Run integrated cross-component cases"
    )
    assert '"schedule"' in integrated["run"]
    assert '"workflow_dispatch"' in integrated["run"]
    assert "full_args=(--full)" in integrated["run"]

    summary = next(
        step
        for step in job["steps"]
        if step.get("name") == "Summarize integrated findings for the exact candidate"
    )
    assert summary["if"] == "always()"
    assert "ci_report" in summary["run"]
    assert "--strict" in summary["run"]
    assert "--revision" in summary["run"]

    artifact = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
        and "bng3-integrated-validation-" in step.get("with", {}).get("name", "")
    )
    assert artifact["if"] == "always()"
    assert "bng3-integrated-validation-" in artifact["with"]["name"]
    assert artifact["with"]["path"] == "${{ runner.temp }}/bng3-integrated-validation/"


def test_issue_queue_keeps_snapshots_and_scheduled_drift_without_issue_writes():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["integrated-semantic-validation"]
    assert job["permissions"]["issues"] == "read"
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "gh issue list" in commands and "--limit 1000" in commands
    assert "tests.validation.issue_queue" in commands
    assert "--collect-upstream-heads" in commands
    assert "--revision" in commands
    queue = next(
        s
        for s in job["steps"]
        if s.get("name") == "Build exact-revision issue and provenance evidence queue"
    )
    assert queue["if"] == "always()"
    assert '"schedule"' in queue["run"] and '"workflow_dispatch"' in queue["run"]
    uploaded = next(
        s
        for s in job["steps"]
        if s.get("name") == "Upload issue queue and provenance observations"
    )
    assert uploaded["if"] == "always()"
    assert "bng3-issues.json" in uploaded["with"]["path"]


def test_generated_matrix_audit_runs_on_the_exact_integrated_report_and_candidate():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["integrated-semantic-validation"]
    matrix_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Audit generated consumer matrix receipts"
    )
    assert matrix_step["if"] == "always()"
    assert 'test -s "$RUNNER_TEMP/bng3-integrated-validation/report.json"' in matrix_step["run"]
    assert "python -m tests.validation.integrated_matrix" in matrix_step["run"]
    assert SOURCE_HEAD in matrix_step["run"]
    assert "matrix-report.json" in matrix_step["run"]
    issue_queue = next(
        step
        for step in job["steps"]
        if step.get("name") == "Build exact-revision issue and provenance evidence queue"
    )
    assert '--report "$RUNNER_TEMP/bng3-integrated-validation/matrix-report.json"' in issue_queue["run"]
