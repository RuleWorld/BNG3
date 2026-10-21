"""The curated BioModels expectation manifest must detect a corpus regression.

The manifest in ``provenance/curated-biomodels-corpus-expectations.json``
records the expected verdict of every curated BioModels record at every stage
of the corpus gate.  These tests keep the manifest honest and prove that a
disagreement between the manifest and a run fails with a per-record diff
instead of needing a human to read two large reports side by side.

The vocabulary is the official SBML Test Suite manifest's vocabulary, so the
campaign has one set of words for a gap: a construct that names the boundary
and a side that says whose boundary it is.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import curated_biomodels_corpus_inventory as inventory

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "curated-biomodels-corpus-expectations.json"
CORPUS_MANIFEST = REPO / "provenance" / "published-biomodels.json"
TOOL = REPO / "scripts" / "ci" / "curated_biomodels_corpus_inventory.py"


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _corpus_manifest() -> dict[str, Any]:
    return json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))


def _mode_for(stages: dict[str, str]) -> dict[str, Any]:
    """Return the mode evidence a record with these stage verdicts carries."""

    mode: dict[str, Any] = {
        "mode": "flat",
        "status": stages["conversion"],
        "core_passed": stages["conversion"] == "passed",
    }
    if stages["roundtrip_structure"] != "not_tested":
        mode["written_xml"] = {"passed": True}
        mode["generated_network"] = {"species": 2, "reactions": 3}
        mode["native_reader"] = {
            "success": True,
            "species_count": 2,
            "reaction_count": 3,
        }
    if stages["independent_comparison"] == "passed":
        mode["simulation_comparison"] = {
            "passed": True,
            "skipped": False,
            "failed_observables": [],
        }
    elif stages["independent_comparison"] == "failed":
        mode["simulation_comparison"] = {
            "passed": False,
            "skipped": False,
            "failed_observables": ["S1"],
            "error": "BNG3 CVODE/libRoadRunner observable mismatch: S1",
        }
    elif stages["independent_comparison"] == "not_comparable":
        mode["simulation_comparison"] = {
            "passed": False,
            "skipped": False,
            "failed_observables": [],
            "not_comparable": {"S1": "the source observable is undefined at t=0"},
            "error": (
                "the source observable is undefined at t=0: BNG3 and "
                "libRoadRunner report the same undefined value"
            ),
        }
    return mode


def _report_from_cases(cases: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Build a report whose observed verdicts are exactly ``cases``."""

    records = []
    for model_id, stages in sorted(cases.items()):
        record: dict[str, Any] = {
            "id": model_id,
            "name": f"model {model_id}",
            "format": "SBML",
            "status": stages["conversion"],
            "core_passed": stages["conversion"] == "passed",
        }
        if stages["conversion"] not in {"timeout", "unsupported_format"}:
            record["modes"] = [_mode_for(stages)]
        records.append(record)
    return {
        "schema_version": 4,
        "mode": "flat",
        "records": records,
        "inventory": {
            "source": "BioModels manually curated records",
            "query": "curationstatus:Manually curated",
            "matches": len(records),
        },
        "completeness": {
            "partial_run": False,
            "expected_records": 1096,
            "expected_sbml_records": 1075,
            "expected_non_sbml_records": 21,
        },
    }


@pytest.mark.smoke
def test_committed_manifest_records_a_reproducible_measurement():
    manifest = _manifest()
    assert manifest["schema_version"] == 1
    assert manifest["kind"] == "curated-biomodels-corpus-expectations"
    assert manifest["generator"] == "scripts/ci/curated_biomodels_corpus_inventory.py"
    assert tuple(manifest["stages"]) == inventory.CORPUS_EXPECTATION_STAGES
    assert tuple(manifest["statuses"]) == inventory.CORPUS_EXPECTATION_STATUSES
    assert tuple(manifest["sides"]) == inventory.CORPUS_GAP_SIDES

    corpus = _corpus_manifest()
    assert manifest["corpus"]["inventory_query"] == corpus["curation_query"]
    assert manifest["corpus"]["snapshot_date"] == corpus["snapshot_date"]
    assert (
        manifest["corpus"]["expected_total_records"] == corpus["expected_total_records"]
    )
    assert manifest["corpus"]["record_count"] == corpus["expected_total_records"]
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["source_report"]["sha256"])
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_report"]["bng3_commit"])
    assert manifest["source_report"]["measurement_date"]
    assert manifest["provenance"]["tool_versions"]

    cases = manifest["cases"]
    assert manifest["corpus"]["record_count"] == len(cases)
    assert cases
    for model_id, statuses in cases.items():
        assert re.fullmatch(r"BIOMD[0-9]{10}", model_id), model_id
        assert set(inventory.CORPUS_EXPECTATION_STAGES) <= set(statuses), model_id
        for stage in inventory.CORPUS_EXPECTATION_STAGES:
            assert statuses[stage] in inventory.CORPUS_EXPECTATION_STATUSES, (
                model_id,
                stage,
            )


@pytest.mark.smoke
def test_an_unsupported_expectation_names_the_construct_and_the_side():
    """``passed`` is a result; a refusal is a gap with a named construct."""

    manifest = _manifest()
    assert "gap" in manifest["note"]
    gaps = {
        model_id: entry["gap"]
        for model_id, entry in manifest["cases"].items()
        if "gap" in entry
    }
    assert gaps
    for model_id, entry in gaps.items():
        assert set(entry) <= {"conversion"}, model_id
        for detail in entry.values():
            assert detail["construct"], (model_id, detail)
            assert isinstance(detail["causes"], list), (model_id, detail)
            assert detail["side"] in inventory.CORPUS_GAP_SIDES, (model_id, detail)
    # Every record the gate refused names the construct it waits for.
    for model_id, entry in manifest["cases"].items():
        if entry["conversion"] in {"unsupported", "unsupported_format"}:
            assert "conversion" in gaps.get(model_id, {}), model_id
            assert gaps[model_id]["conversion"]["construct"], model_id
    # A record the gate could not measure names the construct that made the
    # measurement impossible, so a reader is never left with an unnamed
    # boundary.
    for model_id, entry in manifest["cases"].items():
        if entry["conversion"] == "not_comparable":
            assert "conversion" in gaps.get(model_id, {}), model_id
            assert gaps[model_id]["conversion"]["construct"], model_id
    # A failure is a result, not a construct gap.
    for model_id, entry in manifest["cases"].items():
        if entry["conversion"] == "failed":
            assert model_id not in gaps, model_id
    # Every gap names a construct the corpus taxonomy knows, so a reader is
    # never left with an unnamed boundary.
    for model_id, entry in gaps.items():
        for detail in entry.values():
            assert detail["construct"] != "other", (
                model_id,
                detail,
                "the corpus construct taxonomy has to name this boundary",
            )


@pytest.mark.smoke
def test_the_manifest_agrees_with_the_committed_corpus_identity():
    """The manifest describes the corpus the gate enumerates."""

    manifest = _manifest()
    corpus = _corpus_manifest()
    identity = manifest["corpus"]
    assert identity["expected_total_records"] == corpus["expected_total_records"]
    assert identity["expected_sbml_records"] == corpus["expected_sbml_records"]
    assert identity["expected_non_sbml_records"] == corpus["expected_non_sbml_records"]
    # The records that reach the SBML path are the declared SBML records plus
    # the archives that carry an SBML document.
    assert identity["sbml_path_record_count"] == 1083
    assert identity["sbml_path_record_count"] < identity["record_count"]


@pytest.mark.smoke
def test_the_manifest_matches_a_run_that_reproduces_it():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    comparison = inventory.compare_corpus_expectations(manifest, report)
    assert comparison["differences"] == [], "\n".join(
        inventory.format_corpus_difference(diff) for diff in comparison["differences"]
    )
    assert comparison["records_compared"] == len(manifest["cases"])
    assert comparison["corpus_identity_mismatches"] == []
    assert comparison["revision_mismatch"] is False


@pytest.mark.smoke
def test_perturbing_an_expected_status_fails_with_a_per_record_diff():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    assert inventory.compare_corpus_expectations(manifest, report)["differences"] == []

    # A record the gate refuses.  Perturbing the expectation to a pass makes
    # the run fall short of what the manifest expects.
    identity = next(
        model_id
        for model_id, stages in sorted(manifest["cases"].items())
        if stages["conversion"] == "unsupported"
    )
    perturbed = json.loads(json.dumps(manifest))
    perturbed["cases"][identity]["conversion"] = "passed"
    comparison = inventory.compare_corpus_expectations(perturbed, report)
    assert len(comparison["differences"]) == 1
    difference = comparison["differences"][0]
    assert difference["record"] == identity
    assert difference["stage"] == "conversion"
    assert difference["expected"] == "passed"
    assert difference["observed"] == "unsupported"
    assert difference["classification"] == "regression"
    rendered = inventory.format_corpus_difference(difference)
    assert identity in rendered and "expected passed" in rendered


@pytest.mark.smoke
def test_an_improvement_is_only_accepted_when_the_manifest_is_updated():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    identity = next(
        model_id
        for model_id, stages in sorted(manifest["cases"].items())
        if stages["conversion"] == "failed"
    )
    assert inventory.compare_corpus_expectations(manifest, report)["differences"] == []

    improved = _report_from_cases(manifest["cases"])
    for record in improved["records"]:
        if record["id"] == identity:
            record["status"] = "passed"
            record["core_passed"] = True
            record["modes"][0]["status"] = "passed"
            record["modes"][0]["core_passed"] = True
            record["modes"][0]["simulation_comparison"] = {
                "passed": True,
                "skipped": False,
                "failed_observables": [],
            }
    comparison = inventory.compare_corpus_expectations(manifest, improved)
    assert comparison["differences"]
    assert any(
        diff["record"] == identity and diff["classification"] == "improvement"
        for diff in comparison["differences"]
    )

    updated = json.loads(json.dumps(manifest))
    updated["cases"][identity]["conversion"] = "passed"
    updated["cases"][identity]["independent_comparison"] = "passed"
    assert inventory.compare_corpus_expectations(updated, improved)["differences"] == []


@pytest.mark.smoke
def test_a_timeout_is_not_a_verdict_in_either_direction():
    """The corpus gate's timeout bucket is load-sensitive, not a result."""

    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    identity = next(
        model_id
        for model_id, stages in sorted(manifest["cases"].items())
        if stages["conversion"] == "passed"
    )

    # A record that passed and timed out is not a regression: the timeout
    # records that the machine was busy.  Every stage of that record is
    # affected, so none of them is a verdict difference either.
    timed_out = _report_from_cases(manifest["cases"])
    for record in timed_out["records"]:
        if record["id"] == identity:
            record["status"] = "timeout"
            record["core_passed"] = False
            record.pop("modes", None)
    comparison = inventory.compare_corpus_expectations(manifest, timed_out)
    assert comparison["differences"]
    assert all(
        diff["record"] == identity for diff in comparison["differences"]
    ), comparison["differences"]
    assert all(
        diff["classification"] == "timeout" for diff in comparison["differences"]
    ), comparison["differences"]
    assert all(
        diff["timeout_side"] == "observed" for diff in comparison["differences"]
    ), comparison["differences"]

    # The other direction: a record the manifest recorded as a timeout and
    # that now produces a verdict is a timeout difference too, not a change
    # of a verdict.
    assert inventory.classify_corpus_difference("timeout", "failed") == "timeout"
    assert inventory.classify_corpus_difference("failed", "timeout") == "timeout"
    assert inventory.classify_corpus_difference("passed", "unsupported") == (
        "regression"
    )
    assert inventory.classify_corpus_difference("failed", "passed") == "improvement"
    assert inventory.classify_corpus_difference("unsupported", "failed") == "change"


@pytest.mark.smoke
def test_a_record_that_disappeared_is_reported():
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    identity = sorted(manifest["cases"])[0]
    report["records"] = [
        record for record in report["records"] if record["id"] != identity
    ]
    comparison = inventory.compare_corpus_expectations(manifest, report)
    assert comparison["differences"]
    missing = [
        diff
        for diff in comparison["differences"]
        if diff["classification"] == "missing-record"
    ]
    assert len(missing) == 1
    assert missing[0]["record"] == identity

    # A partial run states that it did not execute the record; the record is
    # reported as not executed and is not a difference.
    partial = json.loads(json.dumps(report))
    partial["completeness"]["partial_run"] = True
    comparison = inventory.compare_corpus_expectations(manifest, partial)
    assert comparison["differences"] == []
    assert comparison["records_not_executed"] == 1


@pytest.mark.smoke
def test_the_cli_fails_on_a_perturbed_expectation(tmp_path):
    manifest = _manifest()
    identity = next(
        model_id
        for model_id, stages in sorted(manifest["cases"].items())
        if stages["conversion"] == "passed"
    )
    perturbed = json.loads(json.dumps(manifest))
    perturbed["cases"][identity]["conversion"] = "unsupported"

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
            "--flat-report",
            str(report_path),
            "--expectations",
            str(manifest_path),
            "--report-revision",
            manifest["source_report"]["bng3_commit"],
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert identity in result.stderr
    assert "expected unsupported" in result.stderr
    assert "observed passed" in result.stderr
    assert "conversion" in result.stderr


@pytest.mark.smoke
def test_the_cli_rejects_a_run_against_another_corpus_snapshot(tmp_path):
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report["inventory"]["query"] = "curationstatus:NonManually curated"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
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
    assert "corpus identity mismatch" in result.stderr


@pytest.mark.smoke
def test_the_cli_rejects_a_manifest_from_another_corpus_snapshot(tmp_path):
    """The expectation must describe the snapshot the corpus manifest declares."""

    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    corpus_manifest = _corpus_manifest()
    corpus_manifest["snapshot_date"] = "2026-10-01"
    corpus_path = tmp_path / "published-biomodels.json"
    corpus_path.write_text(json.dumps(corpus_manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
            str(report_path),
            "--expectations",
            str(manifest_path),
            "--manifest",
            str(corpus_path),
            "--report-revision",
            manifest["source_report"]["bng3_commit"],
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "corpus identity mismatch" in result.stderr
    assert "snapshot_date" in result.stderr


@pytest.mark.smoke
def test_the_cli_rejects_a_run_against_another_record_count(tmp_path):
    """A corpus that grew or shrank is a different corpus."""

    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report["completeness"]["expected_records"] = 1200
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
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
    assert "corpus identity mismatch" in result.stderr


@pytest.mark.smoke
def test_the_cli_rejects_a_run_against_another_tool_revision(tmp_path):
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
            str(report_path),
            "--expectations",
            str(manifest_path),
            "--report-revision",
            "0" * 40,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "tool revision mismatch" in result.stderr


@pytest.mark.smoke
def test_the_cli_rejects_a_report_that_states_no_revision(tmp_path):
    """A stale expectation must not be compared against an unknown corpus."""

    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
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
    assert "--report-revision" in result.stderr


@pytest.mark.smoke
def test_the_cli_accepts_a_run_that_reproduces_the_manifest(tmp_path):
    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
            str(report_path),
            "--expectations",
            str(MANIFEST),
            "--report-revision",
            manifest["source_report"]["bng3_commit"],
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "match" in result.stdout


def test_the_manifest_is_regenerated_from_its_report(tmp_path):
    """The committed manifest is a function of the report it names.

    The regeneration check is what makes the record trustworthy: the manifest
    is not a hand-written summary but the tool's own reading of a report.
    """

    manifest = _manifest()
    report = _report_from_cases(manifest["cases"])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "expectations.json"

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--flat-report",
            str(report_path),
            "--expectations-out",
            str(out),
            "--measurement-date",
            manifest["source_report"]["measurement_date"],
            "--measured-commit",
            manifest["source_report"]["bng3_commit"],
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    regenerated = json.loads(out.read_text(encoding="utf-8"))
    stages = inventory.CORPUS_EXPECTATION_STAGES
    assert {
        model_id: {stage: entry[stage] for stage in stages}
        for model_id, entry in regenerated["cases"].items()
    } == {
        model_id: {stage: entry[stage] for stage in stages}
        for model_id, entry in manifest["cases"].items()
    }
    assert regenerated["stage_counts"] == manifest["stage_counts"]


def test_the_manifests_stage_counts_agree_with_its_per_record_verdicts():
    """The summary and the detail cannot drift apart."""

    manifest = _manifest()
    cases = manifest["cases"]
    for stage in inventory.CORPUS_EXPECTATION_STAGES:
        tally: dict[str, int] = {}
        for statuses in cases.values():
            tally[statuses[stage]] = tally.get(statuses[stage], 0) + 1
        assert manifest["stage_counts"][stage] == dict(sorted(tally.items())), stage
        assert sum(manifest["stage_counts"][stage].values()) == len(cases), stage


def test_the_manifests_gap_counts_agree_with_its_per_record_gaps():
    """The gap histogram is derived from the gaps, not typed in."""

    manifest = _manifest()
    constructs: dict[str, int] = {}
    sides: dict[str, int] = {}
    for entry in manifest["cases"].values():
        for detail in (entry.get("gap") or {}).values():
            constructs[detail["construct"]] = constructs.get(detail["construct"], 0) + 1
            sides[detail["side"]] = sides.get(detail["side"], 0) + 1
    assert manifest["gap_counts"]["by_construct"] == dict(sorted(constructs.items()))
    assert manifest["gap_counts"]["by_side"] == dict(sorted(sides.items()))
    assert sum(sides.values()) == len(
        [entry for entry in manifest["cases"].values() if entry.get("gap")]
    )
