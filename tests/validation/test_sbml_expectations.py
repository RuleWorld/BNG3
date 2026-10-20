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
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import sbml_campaign_inventory as inventory

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "sbml-campaign" / "expectations.json"
INVENTORY = REPO / "provenance" / "sbml-campaign" / "integrated-2026-10-20.json"
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
        assert tuple(statuses) == inventory.EXPECTATION_STAGES, identity
        assert set(statuses.values()) <= set(inventory.EXPECTATION_STATUSES), identity


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
    identity = next(
        case
        for case, statuses in sorted(manifest["cases"].items())
        if statuses["official_reference"] == "failed"
    )

    # The manifest still expects the failure, so the run is a difference.
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
    assert difference["expected"] == "failed"
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
