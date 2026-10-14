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
