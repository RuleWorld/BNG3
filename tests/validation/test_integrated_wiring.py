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
    )
    assert artifact["if"] == "always()"
    assert "bng3-integrated-validation-" in artifact["with"]["name"]
    assert artifact["with"]["path"] == "${{ runner.temp }}/bng3-integrated-validation/"
