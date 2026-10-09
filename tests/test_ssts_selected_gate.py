"""A bounded official-reference gate must fail on real discrepancies."""

import argparse
import json

import pytest

from scripts.ci import validate_sbml_test_suite as runner
from tests.workflow_yaml import parse_workflow


def passed_case():
    return {
        "status": "passed",
        "simulation_comparison": {"passed": True},
        "official_conformance": {"status": "passed"},
    }


def test_selected_gate_accepts_executed_reference_and_explicit_unsupported():
    records = [
        passed_case(),
        {
            "status": "unsupported",
            "official_conformance": {"status": "unsupported"},
        },
    ]
    assert runner._selected_surface_passed(records)


@pytest.mark.parametrize(
    "status", ["failed", "timed-out", "invalid-source", "pending", "missing"]
)
def test_selected_gate_rejects_official_failure_even_when_roundtrip_passes(status):
    case = passed_case()
    case["official_conformance"]["status"] = status
    assert not runner._selected_surface_passed([case])


@pytest.mark.parametrize("status", ["failed", "timeout"])
def test_selected_gate_rejects_roundtrip_failure_even_when_reference_passes(status):
    case = passed_case()
    case["status"] = status
    assert not runner._selected_surface_passed([case])


def test_selected_gate_rejects_skipped_independent_comparison():
    case = passed_case()
    case["simulation_comparison"] = {"passed": False, "skipped": True}
    assert not runner._selected_surface_passed([case])


@pytest.mark.parametrize(
    "records",
    [
        [],
        [{"status": "unsupported", "official_conformance": {"status": "unsupported"}}],
    ],
)
def test_selected_gate_requires_an_executed_official_reference(records):
    assert not runner._selected_surface_passed(records)


@pytest.mark.parametrize("shadowed", [False, True])
def test_isolated_case_checks_and_retains_worker_runtime(
    tmp_path, monkeypatch, shadowed
):
    expected = {
        "python_executable": "/venv/bin/python",
        "bionetgen_package_path": "/venv/site-packages/bionetgen/__init__.py",
        "native_extension_resolved_path": "/venv/site-packages/bionetgen/native.so",
        "native_extension_sha256": "a" * 64,
        "libsbml_version": "5.21.2",
        "roadrunner_version": "2.10.0",
    }
    worker_runtime = dict(expected)
    if shadowed:
        worker_runtime["bionetgen_package_path"] = (
            "/shared/python/bionetgen/__init__.py"
        )
    # Execute a real child reporting the same envelope as the runner. Only
    # expensive scientific execution is replaced; subprocess/report handling
    # and the identity check being tested remain real.
    child = tmp_path / "worker.py"
    payload = {"records": [passed_case()], "runtime_provenance": worker_runtime}
    child.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[sys.argv.index('--json') + 1]).write_text("
        + repr(json.dumps(payload))
        + ")\n"
    )
    monkeypatch.setattr(runner, "__file__", str(child))
    args = argparse.Namespace(
        json=tmp_path / "report.json",
        suite_dir=tmp_path,
        lock=tmp_path / "lock.json",
        simulation_t_end=1.0,
        simulation_n_steps=10,
        simulation_rtol=1e-7,
        simulation_atol=1e-12,
        case_timeout=10,
    )
    case = {
        "category": "semantic",
        "id": "00001",
        "version": "l3v2",
        "path": str(tmp_path / "source.xml"),
    }
    record = runner._run_isolated_case(case, args, expected)
    if shadowed:
        assert record["status"] == "failed"
        assert "worker runtime identity mismatch" in record["error"]
    else:
        assert record["status"] == "passed"
        assert record["worker_runtime_provenance"] == expected


def test_ssts_workflow_bounds_execution_and_preserves_failure_artifacts():
    workflow = parse_workflow(
        runner.DEFAULT_SUITE_LOCK.parents[1] / ".github/workflows/sbml-conformance.yml"
    )
    job = workflow["jobs"]["conformance"]
    assert job["timeout-minutes"] <= 60
    steps = job["steps"]
    run = next(
        step["run"]
        for step in steps
        if step.get("name") == "Run bounded official conformance"
    )
    assert "--gate-selected-cases" in run
    assert "--max-cases 32" in run
    assert "--case-timeout 60" in run
    assert "--jobs 2" in run
    assert "continue-on-error" not in job
    assert not any(step.get("continue-on-error") for step in steps)
    upload = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
