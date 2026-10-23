"""The SBML conformance expectation manifest must detect a coverage regression.

The manifest in ``provenance/sbml-campaign/expectations.json`` records the
expected verdict of every official SBML Test Suite case at every stage of the
gate.  These tests keep the manifest honest and prove that a disagreement
between the manifest and a run fails with a per-case diff instead of needing a
human to read two large reports side by side.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import sbml_campaign_inventory as inventory

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "sbml-campaign" / "expectations.json"
INVENTORY = REPO / "provenance" / "sbml-campaign" / "current-2026-10-22.json"
LOCK = REPO / "provenance" / "upstreams.lock.yml"
TOOL = REPO / "scripts" / "ci" / "sbml_campaign_inventory.py"
GATE = REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _inventory_rows() -> dict[str, dict[str, Any]]:
    committed = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return {row["ref"]: row for row in committed["sbml_test_suite"]["cases"]}


# The inventory records the harness's own status vocabulary; the manifest
# records the closed expectation vocabulary.  This is the documented mapping
# between them.
INVENTORY_TO_EXPECTATION = {
    "passed": "passed",
    "unsupported": "unsupported",
    "failed": "failed",
    "timeout": "failed",
    "timed-out": "failed",
    "not-tested": "not_tested",
}


def _report_from_inventory() -> dict[str, Any]:
    """Build a report whose observed verdicts are the committed inventory."""

    records = []
    for identity, row in sorted(_inventory_rows().items()):
        category, _, case_id = identity.partition("/")
        record: dict[str, Any] = {
            "category": category,
            "id": case_id,
            "status": row["conversion"],
            "official_conformance": {"status": row["official_reference"]},
        }
        roundtrip = row["roundtrip_structure"]
        if roundtrip != "not-tested":
            record["roundtrip_passed"] = roundtrip == "passed"
        independent = row["independent_comparison"]
        if independent != "not-tested":
            record["simulation_comparison"] = {"passed": independent == "passed"}
        records.append(record)
    return {
        "records": records,
        "partial_run": False,
        "suite_commit": "cf38585fac5de8e0e90112febb62851ee2181816",
    }


def _report_from_cases(cases: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Build a report whose observed verdicts are exactly ``cases``."""

    records = []
    for identity, statuses in sorted(cases.items()):
        category, _, case_id = identity.partition("/")
        record: dict[str, Any] = {
            "category": category,
            "id": case_id,
            "status": statuses["conversion"],
            "official_conformance": {"status": statuses["official_reference"]},
        }
        roundtrip = statuses["roundtrip_structure"]
        if roundtrip != "not_tested":
            record["roundtrip_passed"] = roundtrip == "passed"
        independent = statuses["independent_comparison"]
        if independent != "not_tested":
            record["simulation_comparison"] = {"passed": independent == "passed"}
        records.append(record)
    return {
        "records": records,
        "partial_run": False,
        "suite_commit": "cf38585fac5de8e0e90112febb62851ee2181816",
    }


@pytest.mark.smoke
def test_committed_manifest_records_a_reproducible_measurement():
    manifest = _manifest()
    assert manifest["schema_version"] == 1
    assert manifest["kind"] == "sbml-test-suite-expectations"
    assert manifest["generator"] == "scripts/ci/sbml_campaign_inventory.py"
    assert "harness-side comparability limit" in manifest["note"]
    assert tuple(manifest["stages"]) == inventory.EXPECTATION_STAGES
    assert tuple(manifest["statuses"]) == inventory.EXPECTATION_STATUSES

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert (
        manifest["suite"]["revision"] == lock["sources"]["sbml-test-suite"]["revision"]
    )
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["source_report"]["sha256"])
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_report"]["bng3_commit"])

    cases = manifest["cases"]
    assert manifest["suite"]["case_count"] == len(cases)
    assert cases
    for identity, statuses in cases.items():
        assert re.fullmatch(r"(semantic|stochastic)/[0-9]{5}", identity), identity
        assert set(inventory.EXPECTATION_STAGES) <= set(statuses), identity
        for stage in inventory.EXPECTATION_STAGES:
            assert statuses[stage] in inventory.EXPECTATION_STATUSES, (
                identity,
                stage,
            )


@pytest.mark.smoke
def test_an_unsupported_expectation_names_the_construct_it_waits_for():
    """``passed`` is a result; ``unsupported`` is a gap with a named cause."""

    manifest = _manifest()
    assert "gap" in manifest["note"]
    gaps = {
        case: entry["gap"]
        for case, entry in manifest["cases"].items()
        if "gap" in entry
    }
    assert gaps
    for case, entry in gaps.items():
        assert set(entry) <= {"conversion", "official_reference"}, case
        for stage, detail in entry.items():
            assert detail["construct"], (case, stage)
            assert isinstance(detail["causes"], list), (case, stage)
    # Every case that is refused at the conversion stage names the construct.
    for case, entry in manifest["cases"].items():
        if entry["conversion"] == "unsupported":
            assert "conversion" in gaps.get(case, {}), case
            assert gaps[case]["conversion"]["construct"], case


@pytest.mark.smoke
def test_generic_nonfinite_and_scheduled_boundary_refusals_are_classified():
    """Fresh report records must not fall into the generic ``other`` bucket."""

    from scripts.ci import validate_sbml_test_suite as suite

    parameter_approximation = (
        'Parameter "P" has an infinite value; emitted 1e20 as a finite BNGL '
        "approximation."
    )
    assert suite._unsupported_causes(parameter_approximation) == ["mathml"]
    assert inventory.reason_signature(parameter_approximation) == (
        "mathml:non-finite-parameter-approximation"
    )
    conversion_record = {
        "category": "semantic",
        "id": "99998",
        "status": "unsupported",
        "unsupported_reason": parameter_approximation,
        "unsupported_causes": ["other"],
    }
    suite._unsupported_summary([conversion_record])
    assert conversion_record["unsupported_causes"] == ["mathml"]
    assert inventory._stage_gap(conversion_record, "conversion") == {
        "construct": "mathml:non-finite-parameter-approximation",
        "causes": ["mathml"],
        "side": "atomizer",
    }

    scheduled_boundary = (
        "the official output grid contains the boundary of the generated "
        "scheduled actions at t=25.0, where the reference convention and "
        "native action dispatcher differ"
    )
    record = {
        "category": "semantic",
        "id": "99999",
        "status": "passed",
        "official_conformance": {
            "status": "unsupported",
            "reason": scheduled_boundary,
        },
    }
    gap = inventory._stage_gap(record, "official_reference")
    assert gap == {
        "construct": "harness:scheduled-action-phase-boundary",
        "causes": ["events"],
        "side": "harness",
    }


def test_inventory_refines_recorded_other_without_losing_source_report_label():
    record = {
        "category": "semantic",
        "id": "99997",
        "status": "unsupported",
        "unsupported_reason": (
            'Compartment "C" has spatialDimensions 7; BNG3 does not support '
            "spatialDimensions values greater than 3."
        ),
        "unsupported_causes": ["other"],
        "official_conformance": {"status": "unsupported"},
    }

    reduced = inventory.suite_inventory({"records": [record]})

    assert reduced["cases"][0]["causes"] == ["compartments"]
    assert reduced["cases"][0]["reported_causes"] == ["other"]
    assert reduced["cause_counts"] == {"compartments": 1}


def test_ensemble_work_budget_is_a_harness_comparability_gap_not_support():
    reason = (
        "The documented ensemble work budget for 40000 runs exceeds the "
        "gate's estimated event-work budget; this case is not comparable."
    )
    record = {
        "category": "stochastic",
        "id": "00023",
        "status": "passed",
        "official_conformance": {"status": "unsupported", "reason": reason},
    }

    gap = inventory._stage_gap(record, "official_reference")

    assert gap == {
        "construct": "harness:stochastic-ensemble-budget-not-comparable",
        "causes": ["ensemble_budget"],
        "side": "harness",
    }
    assert inventory.expectation_gaps({"records": [record]}) == {
        "stochastic/00023": {"official_reference": gap}
    }
    # The source-run status remains the historical unsupported label. This
    # classification is explicitly a harness comparability limit, not a
    # scientific pass or an Atomizer representability claim.
    assert record["official_conformance"]["status"] == "unsupported"


@pytest.mark.smoke
def test_committed_manifest_agrees_with_the_committed_inventory():
    manifest = _manifest()
    rows = _inventory_rows()
    assert set(rows) == set(manifest["cases"])
    for identity, row in rows.items():
        expected = manifest["cases"][identity]
        for stage in inventory.EXPECTATION_STAGES:
            assert expected[stage] == INVENTORY_TO_EXPECTATION[row[stage]], (
                identity,
                stage,
            )

    # The same disagreement, read through the comparator, is a per-case diff.
    comparison = inventory.compare_expectations(manifest, _report_from_inventory())
    assert comparison["differences"] == [], "\n".join(
        inventory.format_difference(diff) for diff in comparison["differences"]
    )


@pytest.mark.smoke
def test_manifest_matches_a_run_that_reproduces_it():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    comparison = inventory.compare_expectations(manifest, report)
    assert comparison["differences"] == []
    assert comparison["cases_compared"] == len(manifest["cases"])
    assert comparison["suite_revision_mismatch"] is False


@pytest.mark.smoke
def test_perturbing_an_expected_status_fails_with_a_per_case_diff():
    manifest = _manifest()
    # The observed run is the committed inventory, which was measured
    # independently of the manifest.
    report = _report_from_inventory()
    assert inventory.compare_expectations(manifest, report)["differences"] == []

    # A case the run refuses to convert.  Perturbing the expectation to a
    # pass makes the run fall short of what the manifest expects.
    identity = next(
        case
        for case, statuses in sorted(manifest["cases"].items())
        if statuses["conversion"] == "unsupported"
    )
    perturbed = json.loads(json.dumps(manifest))
    perturbed["cases"][identity]["conversion"] = "passed"
    comparison = inventory.compare_expectations(perturbed, report)
    assert len(comparison["differences"]) == 1
    difference = comparison["differences"][0]
    assert difference["case"] == identity
    assert difference["stage"] == "conversion"
    assert difference["expected"] == "passed"
    assert difference["observed"] == "unsupported"
    assert difference["classification"] == "regression"
    rendered = inventory.format_difference(difference)
    assert identity in rendered and "expected passed" in rendered

    # A case the run converts and whose official reference passes.
    # Perturbing the expectation to a failure asks for less than the run
    # delivers, which is only accepted once the manifest is updated.
    identity = next(
        case
        for case, statuses in sorted(manifest["cases"].items())
        if statuses["official_reference"] == "passed"
    )
    perturbed = json.loads(json.dumps(manifest))
    perturbed["cases"][identity]["official_reference"] = "failed"
    comparison = inventory.compare_expectations(perturbed, report)
    assert len(comparison["differences"]) == 1
    difference = comparison["differences"][0]
    assert difference["case"] == identity
    assert difference["stage"] == "official_reference"
    assert difference["expected"] == "failed"
    assert difference["observed"] == "passed"
    assert difference["classification"] == "improvement"


@pytest.mark.smoke
def test_an_improvement_is_only_accepted_when_the_manifest_is_updated():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    # Any stage the manifest does not expect to pass will do: the point is
    # that a stage which starts passing is only accepted once the manifest
    # records it, not that a particular measurement contains a failure.
    identity = next(
        case
        for case, statuses in sorted(manifest["cases"].items())
        if statuses["official_reference"] not in {"passed", "not_tested"}
    )
    expected = manifest["cases"][identity]["official_reference"]

    # The manifest still expects the old verdict, so the run is a difference.
    comparison = inventory.compare_expectations(manifest, report)
    assert comparison["differences"] == []

    improved = _report_from_cases(manifest["cases"])
    for record in improved["records"]:
        if f"{record['category']}/{record['id']}" == identity:
            record["official_conformance"]["status"] = "passed"
    comparison = inventory.compare_expectations(manifest, improved)
    assert len(comparison["differences"]) == 1
    difference = comparison["differences"][0]
    assert difference["case"] == identity
    assert difference["stage"] == "official_reference"
    assert difference["expected"] == expected
    assert difference["observed"] == "passed"
    assert difference["classification"] == "improvement"

    # The same run is accepted once the manifest records the new verdict.
    updated = json.loads(json.dumps(manifest))
    updated["cases"][identity]["official_reference"] = "passed"
    assert inventory.compare_expectations(updated, improved)["differences"] == []


@pytest.mark.smoke
def test_a_case_that_is_no_longer_executed_is_not_a_regression():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    identity = sorted(manifest["cases"])[0]
    report["records"] = [
        record
        for record in report["records"]
        if f"{record['category']}/{record['id']}" != identity
    ]
    report["partial_run"] = True
    comparison = inventory.compare_expectations(manifest, report)
    assert comparison["differences"] == []
    assert comparison["cases_not_executed"] == 1


@pytest.mark.smoke
def test_the_cli_fails_on_a_perturbed_expectation(tmp_path):
    manifest = _manifest()
    identity = next(
        case
        for case, statuses in sorted(manifest["cases"].items())
        if statuses["conversion"] == "unsupported"
    )
    perturbed = json.loads(json.dumps(manifest))
    perturbed["cases"][identity]["conversion"] = "passed"

    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(_report_from_cases(manifest["cases"])), encoding="utf-8"
    )
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(perturbed), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--suite-report",
            str(report_path),
            "--expectations",
            str(manifest_path),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert identity in result.stderr
    assert "expected passed" in result.stderr
    assert "observed unsupported" in result.stderr
    assert "conversion" in result.stderr


@pytest.mark.smoke
def test_the_cli_rejects_a_run_against_another_suite_revision(tmp_path):
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report["suite_commit"] = "0" * 40
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--suite-report",
            str(report_path),
            "--expectations",
            str(manifest_path),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "suite revision mismatch" in result.stderr


def test_biomodels_causes_are_derived_when_a_report_omits_the_labels():
    """A report that carries only the mode-level reason still yields counts."""

    report = {
        "records": [
            {
                "id": "BIOMD0000000001",
                "format": "SBML",
                "status": "unsupported",
                "modes": [
                    {
                        "mode": "flat",
                        "status": "unsupported",
                        "unsupported_reason": (
                            "SBML fbc package is present; flux-balance "
                            "constraints/objectives define a constraint-based "
                            "model with no kinetic BNGL equivalent."
                        ),
                    }
                ],
            },
            {
                "id": "BIOMD0000000002",
                "format": "SBML",
                "status": "passed",
                "modes": [{"mode": "flat", "status": "passed"}],
            },
        ]
    }
    reduced = inventory.biomodels_inventory(report)
    assert reduced["status_counts"] == {"passed": 1, "unsupported": 1}
    assert reduced["cause_counts"] == {"constraints": 1}
    assert reduced["cases"][0]["causes"] == ["constraints"]
    assert (
        reduced["cases"][0]["reason_signature"]
        == "constraints:flux-balance-not-kinetic"
    )
    assert reduced["cases"][1]["causes"] == []
    assert reduced["cases"][1]["reason_signature"] == ""


def test_biomodels_causes_prefer_the_labels_the_harness_recorded():
    report = {
        "records": [
            {
                "id": "BIOMD0000000003",
                "format": "SBML",
                "status": "unsupported",
                "unsupported_reason": "1 SBML event(s) parsed; untranslated.",
                "unsupported_causes": ["events", "mathml"],
                "modes": [
                    {
                        "mode": "flat",
                        "status": "unsupported",
                        "unsupported_reason": "1 SBML event(s) parsed; untranslated.",
                    }
                ],
            }
        ]
    }
    reduced = inventory.biomodels_inventory(report)
    assert reduced["cases"][0]["causes"] == ["events", "mathml"]
    assert reduced["cause_counts"] == {"events": 1, "mathml": 1}


def test_biomodels_extraction_keeps_every_status_separate():
    report = {
        "records": [
            {"id": "a", "status": "passed"},
            {"id": "b", "status": "unsupported"},
            {"id": "c", "status": "unsupported_format"},
            {"id": "d", "status": "failed"},
            {"id": "e", "status": "timeout"},
        ]
    }
    reduced = inventory.biomodels_inventory(report)
    assert reduced["status_counts"] == {
        "failed": 1,
        "passed": 1,
        "timeout": 1,
        "unsupported": 1,
        "unsupported_format": 1,
    }
    assert reduced["cause_counts"] == {"format": 1, "other": 1}


def _generated_region(document: str, name: str) -> str:
    begin = f"<!-- BEGIN GENERATED: {name} -->"
    end = f"<!-- END GENERATED: {name} -->"
    start = document.index(begin) + len(begin)
    stop = document.index(end)
    return document[start:stop]


def test_the_check_mode_reports_a_region_that_drifted_from_the_reports():
    """The document's generated sections are checked, not trusted."""

    from scripts.ci import sbml_campaign_tables as tables

    regions = {name: f"generated {name}\n" for name in tables.REGIONS}
    document = "".join(
        f"{tables.BEGIN_MARKER_TEMPLATE.format(name=name)}\n\n"
        f"{regions[name]}\n"
        f"{tables.END_MARKER_TEMPLATE.format(name=name)}\n\n"
        for name in tables.REGIONS
    )
    assert tables.check_regions(document, regions) == []

    drifted = dict(regions)
    drifted["sbml-campaign-current"] = "a hand-written number\n"
    problems = tables.check_regions(document, drifted)
    assert problems
    assert any("sbml-campaign-current" in problem for problem in problems)
    assert any("-generated sbml-campaign-current" in problem for problem in problems)


def test_a_region_that_is_missing_is_an_error():
    from scripts.ci import sbml_campaign_tables as tables

    document = (
        f"{tables.BEGIN_MARKER_TEMPLATE.format(name='sbml-campaign-current')}\n"
        "x\n"
        f"{tables.END_MARKER_TEMPLATE.format(name='sbml-campaign-current')}\n"
    )
    with pytest.raises(ValueError):
        tables.read_region(document, "sbml-campaign-baseline")


@pytest.mark.smoke
def test_the_campaign_document_tables_state_the_committed_measurement():
    document = (REPO / "docs" / "SBML_ATOMIZER_COVERAGE_CAMPAIGN.md").read_text(
        encoding="utf-8"
    )
    committed = json.loads(INVENTORY.read_text(encoding="utf-8"))
    suite = committed["sbml_test_suite"]
    counts = dict(suite["stage_counts"])
    official = suite["official_reference_counts"]
    counts["official_reference"] = {
        "passed": official.get("passed", 0),
        "unsupported": official.get("unsupported", 0),
        "failed": official.get("failed", 0),
        "not-tested": sum(
            official.get(status, 0)
            for status in ("timed-out", "invalid-source", "pending", "missing")
        ),
    }
    region = _generated_region(document, "sbml-campaign-current")
    labels = {
        "conversion": "Conversion (SBML → BNGL)",
        "roundtrip_structure": "Round-trip structure",
        "independent_comparison": "Independent libRoadRunner comparison",
        "official_reference": "Official reference comparison",
    }
    for stage, label in labels.items():
        expected = counts[stage]
        row = "| {} | {} | {} | {} | {} |".format(
            label,
            expected.get("passed", 0),
            expected.get("unsupported", 0),
            expected.get("failed", 0),
            expected.get("not-tested", 0),
        )
        assert row in region, stage


def _live_gate(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    suite_dir = os.environ.get("BNG3_SBML_SUITE_DIR", "")
    if not suite_dir or not Path(suite_dir).is_dir():
        pytest.skip("BNG3_SBML_SUITE_DIR does not name a pinned suite checkout")
    try:
        import bionetgen._bionetgen_cpp  # noqa: F401
    except ImportError:
        pytest.skip("the BNG3 native extension is not importable")
    report_path = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--suite-dir",
            suite_dir,
            "--categories",
            "semantic",
            "--max-cases",
            "16",
            "--selection-strategy",
            "feature-cover",
            "--isolate-cases",
            "--case-timeout",
            "120",
            "--jobs",
            "4",
            "--gate-selected-cases",
            "--json",
            str(report_path),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_a_live_gate_run_matches_the_committed_expectations(tmp_path):
    """A bounded live run must agree with the committed manifest."""

    _live_gate(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    manifest = _manifest()
    comparison = inventory.compare_expectations(manifest, report)
    assert comparison["suite_revision_mismatch"] is False
    assert comparison["differences"] == [], "\n".join(
        inventory.format_difference(diff) for diff in comparison["differences"]
    )
    assert comparison["cases_compared"] > 0


@pytest.mark.smoke
def test_a_failed_verdict_is_a_finding_and_not_a_construct_gap():
    """``failed`` is a result the run produced; only ``unsupported`` is a gap."""

    manifest = _manifest()
    for case, entry in manifest["cases"].items():
        gap = entry.get("gap")
        if gap is None:
            continue
        for stage in gap:
            assert entry[stage] == "unsupported", (case, stage)
        # "other" is the unclassified bucket: a refusal whose reason matches
        # no known construct class.  It is a legitimate, named construct.
        assert gap[stage]["construct"], (case, stage)


# --------------------------------------------------------------------------
# The workflow's manifest step must not fail a branch that predates the
# manifest, and it must say why it did not compare.
# --------------------------------------------------------------------------

WORKFLOW = REPO / ".github" / "workflows" / "sbml-conformance.yml"
MANIFEST_STEP_NAME = "Compare the run against the committed expectation manifest"


def _manifest_step_script() -> str:
    from tests.workflow_yaml import parse_workflow

    workflow = parse_workflow(WORKFLOW)
    steps = workflow["jobs"]["conformance"]["steps"]
    for step in steps:
        if step.get("name") == MANIFEST_STEP_NAME:
            return str(step["run"])
    raise AssertionError(f"the workflow has no step named {MANIFEST_STEP_NAME!r}")


def _stub_tool(root: Path, body: str) -> Path:
    """Write a stand-in for the campaign inventory tool."""

    tool = root / "scripts" / "ci" / "sbml_campaign_inventory.py"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text(body, encoding="utf-8")
    return tool


def _run_manifest_step(root: Path, tmp_path: Path):
    """Run the workflow's manifest step against ``root`` as the checkout."""

    runner = tmp_path / "runner"
    runner.mkdir(parents=True, exist_ok=True)
    (runner / "report.json").write_text("{}", encoding="utf-8")
    environment = {
        **os.environ,
        "RUNNER_TEMP": str(runner),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    return subprocess.run(
        ["bash", "-c", _manifest_step_script()],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_the_manifest_step_skips_a_branch_that_predates_the_manifest(tmp_path):
    """A tool without ``--expectations`` must skip, visibly, not fail."""

    root = tmp_path / "checkout"
    root.mkdir()
    _stub_tool(
        root,
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    print('usage: sbml_campaign_inventory.py [-h] [--suite-report X] --out OUT')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
    )
    result = _run_manifest_step(root, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::notice::" in result.stdout
    assert "does not apply" in result.stdout
    assert "predates" in result.stdout


def test_the_manifest_step_skips_a_branch_without_the_tool(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    result = _run_manifest_step(root, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::notice::" in result.stdout
    assert "does not apply" in result.stdout


def test_the_manifest_step_still_fails_on_a_real_difference(tmp_path):
    """The skip must not become a blanket pass."""

    root = tmp_path / "checkout"
    root.mkdir()
    _stub_tool(
        root,
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    print('usage: sbml_campaign_inventory.py [-h] [--suite-report X] [--expectations X] --out OUT')\n"
        "    raise SystemExit(0)\n"
        "print('1 expectation difference(s) against the manifest:', file=sys.stderr)\n"
        "print('  semantic/00001 [conversion]: expected passed, observed unsupported (regression)', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
    )
    result = _run_manifest_step(root, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::notice::" not in result.stdout
    assert "semantic/00001" in result.stderr


def test_the_manifest_step_documents_the_selection_limit():
    """A reader must not take a green pull-request gate as a current manifest."""

    script = _manifest_step_script()
    assert "128-case feature-cover" in script
    assert "scheduled full run compares every case" in script


@pytest.mark.smoke
def test_the_committed_manifest_is_internally_consistent():
    """Every case, every stage, every gap — the record must describe itself."""

    manifest = _manifest()
    cases = manifest["cases"]
    assert manifest["suite"]["case_count"] == len(cases) == 1923

    for identity, entry in cases.items():
        assert set(inventory.EXPECTATION_STAGES) <= set(entry), identity
        for stage in inventory.EXPECTATION_STAGES:
            assert entry[stage] in inventory.EXPECTATION_STATUSES, (identity, stage)
        gap = entry.get("gap")
        if gap is None:
            continue
        for stage, detail in gap.items():
            # A gap is recorded only for a refusal, and it names the construct
            # that is not representable today.
            assert entry[stage] == "unsupported", (identity, stage)
            assert detail["construct"], (identity, stage)
            assert detail["construct"], (identity, stage)

    # A reference mismatch is a finding, not a missing construct: the
    # official-reference failures are recorded as failures and carry no gap.
    failures = [
        identity
        for identity, entry in cases.items()
        if entry["official_reference"] == "failed"
    ]
    for identity in failures:
        assert "official_reference" not in cases[identity].get("gap", {}), identity


@pytest.mark.smoke
def test_the_manifests_stage_counts_agree_with_its_per_case_verdicts():
    """The summary and the detail are one record, not two."""

    manifest = _manifest()
    cases = manifest["cases"]
    recorded = manifest["stage_counts"]
    for stage in inventory.EXPECTATION_STAGES:
        tally = Counter(entry[stage] for entry in cases.values())
        assert dict(sorted(tally.items())) == recorded[stage], stage
        assert sum(recorded[stage].values()) == len(cases), stage


def test_the_manifest_step_compares_whenever_the_tool_supports_expectations(
    tmp_path,
):
    """A tool that can compare must never be mistaken for one that cannot.

    The step reads the tool's usage text rather than piping it into a
    matcher, so a tool that writes a long usage text cannot lose the
    comparison to a broken pipe.
    """

    root = tmp_path / "checkout"
    root.mkdir()
    _stub_tool(
        root,
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    print('usage: sbml_campaign_inventory.py [-h] [--suite-report X] "
        "[--expectations X] --out OUT')\n"
        "    for index in range(2000):\n"
        "        print('filler line ' + str(index))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n",
    )
    result = _run_manifest_step(root, tmp_path)
    # The tool supports --expectations, so the step must compare and fail on
    # the tool's non-zero exit, not skip.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::notice::" not in result.stdout


@pytest.mark.smoke
def test_every_gap_records_the_side_of_the_boundary_it_sits_on():
    """A harness-side gap is a measurement limit; an Atomizer-side one is not."""

    manifest = _manifest()
    sides = set()
    for case, entry in manifest["cases"].items():
        for stage, gap in entry.get("gap", {}).items():
            assert gap["side"] in inventory.GAP_SIDES, (case, stage)
            sides.add(gap["side"])
            if gap["construct"].startswith("harness:"):
                assert gap["side"] == "harness", (case, stage)
            if gap["construct"] == "reference:not-applicable":
                assert gap["side"] == "not-applicable", (case, stage)
            if gap["construct"] == "reference:no-result-mapping":
                assert gap["side"] == "harness", (case, stage)
    assert sides == set(inventory.GAP_SIDES)


def test_the_failure_clusters_follow_the_official_feature_tags():
    """The cluster a case lands in is decided by its own official metadata."""

    from scripts.ci import sbml_campaign_tables as tables

    assert tables.FAILURE_CLUSTER_TAGS == (
        ("CSymbolDelay", "CSymbolDelay"),
        ("CSymbolRateOf", "CSymbolRateOf"),
        ("CSymbolAvogadro", "CSymbolAvogadro"),
        ("AlgebraicRule", "AlgebraicRule"),
        ("InitialAssignment", "InitialAssignment"),
        ("AssignmentRule", "AssignmentRule"),
        ("RateRule", "RateRule"),
    )

    def cluster_for(tags: list[str]) -> str:
        for tag, label in tables.FAILURE_CLUSTER_TAGS:
            if tag in tags:
                return label
        return tables.FAILURE_CLUSTER_OTHER

    # The most specific tag wins, so a case that also carries an
    # InitialAssignment tag is still reported as a delay case.
    assert cluster_for(["Compartment", "CSymbolDelay", "InitialAssignment"]) == (
        "CSymbolDelay"
    )
    assert cluster_for(["CSymbolAvogadro", "Parameter"]) == "CSymbolAvogadro"
    assert cluster_for(["InitialAssignment", "Species"]) == "InitialAssignment"
    assert cluster_for(["AssignmentRule", "Parameter"]) == "AssignmentRule"
    assert cluster_for(["RateRule", "Reaction", "Species"]) == "RateRule"
    assert cluster_for(["AlgebraicRule", "Parameter"]) == "AlgebraicRule"
    assert cluster_for(["Compartment", "Reaction", "Species"]) == "other"
