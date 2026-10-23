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


def test_product_checkout_identity_root_defaults_to_harness_and_can_be_pinned(tmp_path):
    harness_root = tmp_path / "harness"
    product_root = tmp_path / "product"
    product_root.mkdir()
    subprocess.run(["git", "init", str(product_root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(product_root), "config", "user.name", "SSTS product test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(product_root),
            "config",
            "user.email",
            "ssts-product@example.invalid",
        ],
        check=True,
    )
    (product_root / "model.py").write_text("model = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(product_root), "add", "model.py"], check=True)
    subprocess.run(
        ["git", "-C", str(product_root), "commit", "-m", "product source"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(product_root), "rev-parse", "HEAD"], text=True
    ).strip()

    assert runner._product_checkout_root(None, harness_root) == harness_root
    assert (
        runner._product_checkout_root(product_root, harness_root, revision)
        == product_root.resolve()
    )
    with pytest.raises(ValueError, match="does not match BNG3_SOURCE_REVISION"):
        runner._product_checkout_root(product_root, harness_root, "0" * 40)


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
        "import json, sys\nfrom pathlib import Path\n"
        f"payload = {payload!r}\n"
        "payload['stochastic_seed_base'] = int(sys.argv[sys.argv.index('--stochastic-seed-base') + 1])\n"
        "payload['product_checkout'] = sys.argv[sys.argv.index('--product-checkout') + 1] if '--product-checkout' in sys.argv else None\n"
        "Path(sys.argv[sys.argv.index('--json') + 1]).write_text(json.dumps(payload))\n"
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
        stochastic_seed_base=1234567,
        product_checkout=tmp_path / "product",
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
        command = json.loads((retained / "worker-report.json").read_text())
        assert command["stochastic_seed_base"] == 1234567
        assert command["product_checkout"] == str(args.product_checkout.resolve())


def test_stochastic_seed_base_range_matches_native_uint64():
    assert runner._validate_stochastic_seed_base(0) == 0
    assert runner._validate_stochastic_seed_base((1 << 64) - 1) == (1 << 64) - 1
    with pytest.raises(ValueError, match="unsigned 64-bit"):
        runner._validate_stochastic_seed_base(-1)
    with pytest.raises(ValueError, match="unsigned 64-bit"):
        runner._validate_stochastic_seed_base(1 << 64)
    runner._validate_stochastic_seed_span((1 << 64) - 2, 1)
    with pytest.raises(ValueError, match="seed offset"):
        runner._validate_stochastic_seed_span((1 << 64) - 2, 2)


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
    assert workflow["concurrency"]["group"] == (
        "${{ github.workflow }}-${{ github.event_name == 'workflow_dispatch' "
        "&& github.run_id || github.event.pull_request.head.sha || github.sha }}"
    )
    assert workflow["concurrency"]["cancel-in-progress"] is False
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
    dispatch_env = steps[
        next(
            i
            for i, step in enumerate(steps)
            if step.get("name") == "Run bounded official conformance"
        )
    ]["env"]
    assert dispatch_env["SSTS_ONLY_CASE"] == "${{ inputs.only_case }}"
    assert '--stochastic-seed-base "$SSTS_STOCHASTIC_SEED_BASE"' in run
    assert '"${selection[@]}"' in run
    dispatch = (workflow.get(True) or {}).get("workflow_dispatch") or {}
    bounded = dispatch.get("inputs", {}).get("bounded")
    assert bounded == {
        "description": "Run the bounded 128-case semantic feature cover",
        "required": False,
        "type": "boolean",
        "default": False,
    }
    assert dispatch["inputs"]["only_case"]["type"] == "string"
    assert dispatch["inputs"]["stochastic_seed_base"]["default"] == "1000000"
    assert dispatch["inputs"]["product_revision"] == {
        "description": "Exact BNG3 product commit to qualify; defaults to the workflow checkout",
        "required": False,
        "type": "string",
        "default": "",
    }
    assert any(
        step.get("with", {}).get("path") == "_bng3_product"
        for step in steps
        if step.get("uses", "").startswith("actions/checkout@")
    )
    install = next(
        step["run"]
        for step in steps
        if step.get("name") == "Install hashed runtime and exact-source package"
    )
    assert "git -C _bng3_product rev-parse HEAD" in install
    assert "git -C _bng3_product status --porcelain --untracked-files=all" in install
    assert "pip install --no-deps --no-build-isolation ./_bng3_product" in install
    identity = next(
        step["run"]
        for step in steps
        if step.get("name")
        == "Verify installed identity and required independent engines"
    )
    assert "check_python_package_identity.py" in identity
    assert '--product-checkout "$GITHUB_WORKSPACE/_bng3_product"' in identity
    product_smoke = next(
        step for step in steps if step.get("name") == "Run product smoke tests"
    )
    assert product_smoke["continue-on-error"] == (
        "${{ inputs.product_revision != '' && inputs.product_revision != github.sha }}"
    )
    assert (
        '--junitxml "$RUNNER_TEMP/ssts-artifacts/product-smoke-tests.xml"'
        in product_smoke["run"]
    )
    assert any(
        step.get("name") == "Record product smoke-test outcome"
        and step.get("if") == "always()"
        and "failure" in step.get("run", "")
        for step in steps
    )
    assert '--product-checkout "$GITHUB_WORKSPACE/_bng3_product"' in run
    selector_shell = run.split("python scripts/ci/validate_sbml_test_suite.py", 1)[0]
    selector_shell = selector_shell.replace(
        '"${{ github.event_name }}"', '"$EVENT_NAME"'
    )
    selector_shell = selector_shell.replace(
        '"${{ inputs.bounded }}"', '"$BOUNDED_MANUAL"'
    )
    selector_shell = selector_shell.replace('"${{ inputs.only_case }}"', '"$ONLY_CASE"')
    selector_shell = selector_shell.replace('"$SSTS_ONLY_CASE"', '"$ONLY_CASE"')
    selector_shell += '\nprintf "%s\\n" "${selection[@]}"\n'

    def selected_args(event, bounded_input="false", only_case=""):
        result = subprocess.run(
            ["bash", "-c", selector_shell],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "EVENT_NAME": event,
                "BOUNDED_MANUAL": bounded_input,
                "ONLY_CASE": only_case,
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
    assert selected_args("workflow_dispatch", only_case="stochastic/00003") == [
        "--categories",
        "semantic",
        "stochastic",
        "--only-case",
        "stochastic/00003",
    ]
    conflict = subprocess.run(
        ["bash", "-c", selector_shell],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "EVENT_NAME": "workflow_dispatch",
            "BOUNDED_MANUAL": "true",
            "ONLY_CASE": "stochastic/00003",
        },
    )
    assert conflict.returncode == 2
    assert "--case-timeout 60" in run
    assert "--jobs 4" in run
    assert '--artifacts-dir "$RUNNER_TEMP/ssts-artifacts/cases"' in run
    assert "continue-on-error" not in job
    assert not any(
        step.get("continue-on-error")
        for step in steps
        if step.get("name") != "Run product smoke tests"
    )
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
