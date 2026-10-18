from pathlib import Path

from tests.workflow_yaml import parse_workflow

ROOT = Path(__file__).resolve().parents[2]


def test_common_harness_has_a_fast_path_in_main_ci():
    workflow = parse_workflow(ROOT / ".github/workflows/ci.yml")
    triggers = workflow.get("on", workflow.get(True))
    assert "workflow_dispatch" in triggers and "pull_request" in triggers
    job = workflow["jobs"]["harness"]
    assert job["timeout-minutes"] <= 15
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "provenance/validation-plan.json" in commands
    assert 'suite["id"] == "harness"' in commands
    assert "subprocess.check_call" in commands
    assert "cmake --build" not in commands
    assert any(
        step.get("if") == "always()"
        and step.get("uses", "").startswith("actions/upload-artifact@")
        for step in job["steps"]
    )


def test_existing_ci_runs_harness_mutations_and_publishes_inventory():
    workflow = parse_workflow(ROOT / ".github/workflows/ci.yml")
    steps = workflow["jobs"]["lint"]["steps"]
    assert any("test_campaign_mutations.py" in s.get("run", "") for s in steps)
    assert any("--inventory-only" in s.get("run", "") for s in steps)
    assert any(
        s.get("uses", "").startswith("actions/upload-artifact@")
        and "inventory" in s.get("with", {}).get("name", "")
        for s in steps
    )


def test_differential_reporting_is_additive_and_nightly():
    workflow = parse_workflow(ROOT / ".github/workflows/parity.yml")
    triggers = workflow.get("on", workflow.get(True))
    assert {"cron": "17 4 * * *"} in triggers["schedule"]
    steps = workflow["jobs"]["bng2-parity"]["steps"]
    report = next(
        s for s in steps if "scripts/validate.py --tier smoke" in s.get("run", "")
    )
    assert "--report-only" in report["run"]
    assert "--bng2-root" in report["run"]
    assert "--corpus-tier" in report["run"]


def test_backlog_snapshot_enriches_reports_without_blocking_semantic_execution():
    workflow = parse_workflow(ROOT / ".github/workflows/parity.yml")
    steps = workflow["jobs"]["bng2-parity"]["steps"]
    snapshot = next(s for s in steps if "gh issue list" in s.get("run", ""))
    assert "continue-on-error" not in snapshot
    assert "if gh issue list" in snapshot["run"]
    assert 'mv "$RUNNER_TEMP/bng3-issues.tmp"' in snapshot["run"]
    assert "--state all" in snapshot["run"]
    assert "number,title,state,url" in snapshot["run"]
    report = next(
        s for s in steps if "scripts/validate.py --tier smoke" in s.get("run", "")
    )
    assert "--issues-json" in report["run"]
    assert "issue_args=()" in report["run"]
    assert "mapped-only" in report["run"]
    assert steps.index(snapshot) < steps.index(report)


def test_ci_checks_cdat_gdat_and_publishes_a_distinct_red_diagnostic_check():
    workflow = parse_workflow(ROOT / ".github/workflows/parity.yml")
    jobs = workflow["jobs"]
    steps = jobs["bng2-parity"]["steps"]
    run = next(
        s["run"]
        for s in steps
        if "scripts/validate.py --tier smoke" in s.get("run", "")
    )
    assert "--simulate" in run and "--net-reload" in run
    assert "--bng2-network-sha256" in run
    assert any(
        "tests.validation.ci_report" in s.get("run", "") and s.get("if") == "always()"
        for s in steps
    )
    gate = jobs["conformance-findings"]
    assert gate["needs"] == "bng2-parity"
    assert gate["if"] == "always()"
    assert any(
        "tests.validation.ci_report" in s.get("run", "")
        and "--strict" in s["run"]
        and "--revision" in s["run"]
        for s in gate["steps"]
    )
    assert "continue-on-error" not in gate


def test_common_evidence_job_installs_source_law_oracle_dependency():
    workflow = parse_workflow(ROOT / ".github/workflows/ci.yml")
    job = next(
        job
        for job in workflow["jobs"].values()
        if job.get("name") == "Common evidence and selection contracts"
    )
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "scipy" in commands


def test_bng2_conformance_job_installs_source_law_oracle_dependency():
    workflow = parse_workflow(ROOT / ".github/workflows/parity.yml")
    job = workflow["jobs"]["bng2-parity"]
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "scipy" in commands
