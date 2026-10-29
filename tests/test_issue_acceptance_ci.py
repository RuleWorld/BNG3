"""Contracts for the opt-in native acceptance workflow."""

from tests.workflow_yaml import REPO, parse_workflow

WORKFLOW = parse_workflow(REPO / ".github" / "workflows" / "issue-acceptance.yml")


def test_native_acceptance_is_opt_in_and_keeps_prerequisite_separate():
    triggers = WORKFLOW.get("on") or WORKFLOW.get(True) or {}
    assert set(triggers) == {"pull_request", "workflow_dispatch"}
    paths = triggers["pull_request"]["paths"]
    assert "tests/validation/release/cases/issue-157/**" in paths
    assert "tests/validation/release/cases/issue-161/**" in paths
    assert "cpp/engine/OdeIntegrator.cpp" in paths
    assert "cpp/actions/ActionDispatch.cpp" in paths
    assert "cpp/io/SbmlMultiWriter.cpp" in paths
    assert "cpp/io/SbmlMultiWriter.hpp" in paths
    assert "cpp/parser/BNGAstVisitor.cpp" in paths
    assert "cpp/compile/CompiledModel.cpp" in paths
    assert "python/bionetgen/atomizer/modern/writer.py" in paths
    inputs = triggers["workflow_dispatch"]["inputs"]
    for issue in (157, 161):
        choice = inputs[f"run_issue_{issue}"]
        assert choice["type"] == "boolean"
        assert choice["default"] is False
        assert (
            WORKFLOW["jobs"][f"issue-{issue}"]["if"]
            == f"github.event_name == 'pull_request' || inputs.run_issue_{issue}"
        )

    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "tests/validation/release/cases/issue-159/test_stochastic_00003_law.py" in ci
    assert "--confcutdir=tests/validation/release/cases/issue-159" in ci


def test_native_acceptance_preserves_failure_artifacts():
    for issue, artifact_name in (
        (157, "issue-157-native-acceptance"),
        (161, "issue-161-multi-acceptance"),
    ):
        job = WORKFLOW["jobs"][f"issue-{issue}"]
        steps = job["steps"]
        execute = next(step for step in steps if step.get("id") == "acceptance")
        assert not execute.get("continue-on-error", False)
        upload = next(
            step
            for step in steps
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        assert upload["if"] == "always()"
        assert artifact_name in upload["with"]["name"]
        assert upload["with"]["retention-days"] == 30
        assert not any(step.get("continue-on-error", False) for step in steps)

    issue_161 = WORKFLOW["jobs"]["issue-161"]["steps"]
    oracle_checkout = next(
        step for step in issue_161 if step.get("name") == "Checkout pinned BNG2 oracle"
    )
    assert "scripts/ci/checkout_oracle.py" in oracle_checkout["run"]
    assert "--name bionetgen" in oracle_checkout["run"]
    assert any(
        "tests/validation/release/cases/issue-161/test_run_case.py"
        in step.get("run", "")
        for step in issue_161
    )
