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


def test_curated_biomodels_lane_is_manual_and_uses_the_pinned_full_inventory():
    workflow = parse_workflow(ROOT / ".github/workflows/sbml-conformance.yml")
    triggers = workflow.get("on", workflow.get(True))
    lane = triggers["workflow_dispatch"]["inputs"]["lane"]
    assert lane["type"] == "choice"
    assert lane["options"] == ["sbml-suite", "curated-biomodels", "both"]

    suite = workflow["jobs"]["conformance"]
    assert "inputs.lane != 'curated-biomodels'" in suite["if"]
    corpus = workflow["jobs"]["curated-biomodels"]
    assert triggers["workflow_dispatch"]["inputs"]["biomodels_only_id"]["default"] == ""
    assert "inputs.lane == 'curated-biomodels'" in corpus["if"]
    assert "inputs.lane == 'both'" in corpus["if"]
    commands = "\n".join(step.get("run", "") for step in corpus["steps"])
    membership_step = next(
        step
        for step in corpus["steps"]
        if "_enumerate_inventory" in step.get("run", "")
    )
    assert "from datetime import datetime, timezone" in membership_step["run"]
    assert "--require-source-head" in commands
    assert "provenance/curated-biomodels-query-inventory.json" in commands
    assert "_enumerate_inventory" in commands
    assert "pinned_ids == live_ids" in commands
    assert "--offline --isolate-models --jobs 3 --model-timeout 180" in commands
    assert '--mode "$mode"' in commands
    assert "not_comparable_records" in commands
    assert "harness_error_records" in commands
    assert "BIOMODELS_ONLY_ID" in commands
    smoke = next(
        step
        for step in corpus["steps"]
        if step.get("name") == "Run one-model flat and atomized BioModels smoke"
    )
    assert '--only-id "$BIOMODELS_ONLY_ID"' in smoke["run"]
    assert "source_artifact" in smoke["run"]
    assert (
        '{mode.get("mode") for mode in record["modes"]} != {"flat", "atomized"}'
        in smoke["run"]
    )
    assert 'mode.get("core_passed") is not True' in smoke["run"]
    full = next(
        step
        for step in corpus["steps"]
        if step.get("name") == "Run full flat and atomized BioModels corpus"
    )
    assert full.get("if") == "inputs.biomodels_only_id == ''"
    assert "lane_failed=1" in full["run"] and "continue" in full["run"]
    assert "membership-check.json" in commands
    bundle_install = next(
        step
        for step in corpus["steps"]
        if step.get("name") == "Install the verified offline BioModels source snapshot"
    )
    assert "scripts/ci/install_biomodels_source_bundle.py" in bundle_install["run"]
    assert (
        "tests/fixtures/curated_biomodels/source-payloads-2026-09.tar.gz"
        in bundle_install["run"]
    )
    assert "--receipt" in bundle_install["run"]
    assert 'membership.get("status") != "matched"' not in commands
    assert 'manifest_digest != provenance["manifest_sha256"]' in commands
    assert (
        'inventory.get("matches") != manifest.get("expected_total_records")' in commands
    )
    assert "curated-biomodels-${{ github.sha }}" in "\n".join(
        step.get("with", {}).get("name", "") for step in corpus["steps"]
    )


def test_curated_biomodels_inventory_is_a_complete_pinned_query_result():
    import hashlib
    import json

    inventory_path = ROOT / "provenance/curated-biomodels-query-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    provenance = json.loads(
        (
            ROOT / "provenance/curated-biomodels-query-inventory.provenance.json"
        ).read_text(encoding="utf-8")
    )
    manifest_path = ROOT / "provenance/published-biomodels.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert inventory["query"] == manifest["curation_query"]
    assert inventory["matches"] == manifest["expected_total_records"]
    assert manifest["search_api_url"] == "https://www.biomodels.org/search"
    assert manifest["record_api_url_template"].startswith("https://www.biomodels.org/")
    assert inventory["source"] == manifest["search_api_url"]
    assert all(
        item["record_url"].startswith("https://www.biomodels.org/")
        and item["download_url"].startswith("https://www.biomodels.org/")
        for item in inventory["models"]
    )
    assert len(inventory["models"]) == inventory["matches"]
    assert sum(inventory["format_counts"].values()) == inventory["matches"]
    assert inventory["format_counts"]["SBML"] == manifest["expected_sbml_records"]
    assert (
        sum(
            count
            for format_name, count in inventory["format_counts"].items()
            if format_name != "SBML"
        )
        == manifest["expected_non_sbml_records"]
    )
    assert len({model["id"] for model in inventory["models"]}) == len(
        inventory["models"]
    )
    assert all(
        model.get("sha256") and model.get("download_url") and model.get("record_url")
        for model in inventory["models"]
    )
    assert (
        provenance["inventory_sha256"]
        == hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    )
    assert (
        provenance["manifest_sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )


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


def test_bng2_conformance_provisions_required_independent_nfsim_before_harness():
    workflow = parse_workflow(ROOT / ".github/workflows/parity.yml")
    steps = workflow["jobs"]["bng2-parity"]["steps"]
    build = next((s for s in steps if "--name nfsim" in s.get("run", "")), None)
    assert (
        build is not None
    ), "Required native marginal check has no pinned NFsim oracle"
    command = build["run"]
    assert "--target NFsim" in command
    assert 'test -x "$nfsim"' in command
    assert "NFSIM_BIN=$nfsim" in command and '"$GITHUB_ENV"' in command
    assert "sha256sum" in command and '"$GITHUB_STEP_SUMMARY"' in command
    harness = next(
        s for s in steps if "scripts/validate.py --tier smoke" in s.get("run", "")
    )
    assert steps.index(build) < steps.index(harness)
    assert not build.get("continue-on-error")
