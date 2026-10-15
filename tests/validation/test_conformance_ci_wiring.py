from pathlib import Path

from tests.workflow_yaml import parse_workflow

ROOT = Path(__file__).resolve().parents[2]


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
