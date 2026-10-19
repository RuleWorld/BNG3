"""A bounded official-reference gate must fail on real discrepancies."""

import argparse
import json
import os
import subprocess

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


@pytest.mark.parametrize(
    "shadowed", [None, "bionetgen_package_path", "python_package_source_sha256"]
)
def test_isolated_case_checks_and_retains_worker_runtime(
    tmp_path, monkeypatch, shadowed
):
    expected = {
        "python_executable": "/venv/bin/python",
        "bionetgen_package_path": "/venv/site-packages/bionetgen/__init__.py",
        "native_extension_resolved_path": "/venv/site-packages/bionetgen/native.so",
        "native_extension_sha256": "a" * 64,
        "python_package_source_sha256": "b" * 64,
        "libsbml_version": "5.21.2",
        "roadrunner_version": "2.10.0",
    }
    worker_runtime = dict(expected)
    if shadowed:
        worker_runtime[shadowed] = "different source"
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
        artifacts_dir=tmp_path / "artifacts",
    )
    case = {
        "category": "semantic",
        "id": "00001",
        "version": "l3v2",
        "path": str(tmp_path / "source.xml"),
    }
    record = runner._run_isolated_case(case, args, expected)
    retained = args.artifacts_dir / "semantic" / "00001"
    assert (retained / "worker-report.json").is_file()
    assert (retained / "stdout.log").is_file()
    assert (retained / "stderr.log").is_file()
    if shadowed:
        assert record["status"] == "failed"
        assert "worker runtime identity mismatch" in record["error"]
    else:
        assert record["status"] == "passed"
        assert record["worker_runtime_provenance"] == expected


def test_isolated_timeout_retains_partial_output(tmp_path, monkeypatch):
    child = tmp_path / "worker.py"
    child.write_text(
        "import sys, time\n"
        "print('started conversion', flush=True)\n"
        "print('oracle pending', file=sys.stderr, flush=True)\n"
        "time.sleep(30)\n"
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
        case_timeout=1,
        artifacts_dir=tmp_path / "artifacts",
    )
    case = {
        "category": "semantic",
        "id": "00001",
        "version": "l3v2",
        "path": str(tmp_path / "source.xml"),
    }
    record = runner._run_isolated_case(case, args, {})
    assert record["status"] == "timeout"
    assert record["official_conformance"]["status"] == "timed-out"
    assert not runner._selected_surface_passed([record])
    retained = args.artifacts_dir / "semantic" / "00001"
    assert "started conversion" in (retained / "stdout.log").read_text()
    assert "oracle pending" in (retained / "stderr.log").read_text()


def test_ssts_workflow_bounds_execution_and_preserves_failure_artifacts():
    workflow = parse_workflow(
        runner.DEFAULT_SUITE_LOCK.parents[1] / ".github/workflows/sbml-conformance.yml"
    )
    job = workflow["jobs"]["conformance"]
    assert job["timeout-minutes"] <= 360
    steps = job["steps"]
    run = next(
        step["run"]
        for step in steps
        if step.get("name") == "Run bounded official conformance"
    )
    assert "--gate-selected-cases" in run
    assert (
        "selection=(--categories semantic --max-cases 128 "
        "--selection-strategy feature-cover)"
    ) in run
    assert '"${{ github.event_name }}" == "schedule"' in run
    assert '"${{ github.event_name }}" == "workflow_dispatch"' in run
    assert "selection=(--categories semantic stochastic)" in run
    assert '"${selection[@]}"' in run
    dispatch = (workflow.get(True) or {}).get("workflow_dispatch") or {}
    bounded = dispatch.get("inputs", {}).get("bounded")
    assert bounded == {
        "description": "Run the bounded 128-case semantic feature cover",
        "required": False,
        "type": "boolean",
        "default": False,
    }
    selector_shell = run.split("python scripts/ci/validate_sbml_test_suite.py", 1)[0]
    selector_shell = selector_shell.replace(
        '"${{ github.event_name }}"', '"$EVENT_NAME"'
    )
    selector_shell = selector_shell.replace(
        '"${{ inputs.bounded }}"', '"$BOUNDED_MANUAL"'
    )
    selector_shell += '\nprintf "%s\\n" "${selection[@]}"\n'

    def selected_args(event, bounded_input="false"):
        result = subprocess.run(
            ["bash", "-c", selector_shell],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "EVENT_NAME": event,
                "BOUNDED_MANUAL": bounded_input,
            },
        )
        return result.stdout.splitlines()

    bounded_args = [
        "--categories",
        "semantic",
        "--max-cases",
        "128",
        "--selection-strategy",
        "feature-cover",
    ]
    full_args = ["--categories", "semantic", "stochastic"]
    assert selected_args("pull_request") == bounded_args
    assert selected_args("schedule") == full_args
    assert selected_args("workflow_dispatch") == full_args
    assert selected_args("workflow_dispatch", "true") == bounded_args
    assert "--case-timeout 60" in run
    assert "--jobs 4" in run
    assert '--artifacts-dir "$RUNNER_TEMP/ssts-artifacts/cases"' in run
    assert "continue-on-error" not in job
    assert not any(step.get("continue-on-error") for step in steps)
    upload = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"


def test_python_package_digest_detects_source_changes_only(tmp_path):
    source = tmp_path / "module.py"
    source.write_text("rate = 1\n")
    original = runner._python_package_source_digest(tmp_path)
    (tmp_path / "cache.pyc").write_bytes(b"cache")
    assert runner._python_package_source_digest(tmp_path) == original
    source.write_text("rate = 2\n")
    assert runner._python_package_source_digest(tmp_path) != original
