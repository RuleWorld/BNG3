"""The corpus report comparison must report verdicts, not provenance or order.

The comparison tool is the instrument the campaign uses to show that a change
to the corpus gate's execution strategy changed no verdict.  A tool that
reports a difference where there is none is worse than no tool, because it
teaches the reader to ignore it.

The corpus gate has an outcome bucket of its own: the timeout.  A timeout is
not a verdict -- the per-model budget is sized for an unloaded machine -- so
a difference that is only a timeout is reported as such and is kept distinct
from a real change.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_comparator():
    path = (
        Path(__file__).parents[1]
        / "scripts"
        / "ci"
        / "compare_biomodels_suite_reports.py"
    )
    spec = importlib.util.spec_from_file_location(
        "compare_biomodels_suite_reports", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comparator = _load_comparator()


def _record(model_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "id": model_id,
        "name": f"model {model_id}",
        "format": "SBML",
        "sha256": "a" * 64,
        "source_artifact": {"sha256": "a" * 64},
        "status": "passed",
        "core_passed": True,
        "modes": [
            {
                "mode": "flat",
                "status": "passed",
                "core_passed": True,
                "source_xml": {"passed": True},
                "written_xml": {"passed": True},
                "generated_network": {"species": 2, "reactions": 3},
                "reimport_network": {"species": 2, "reactions": 3},
                "native_reader": {
                    "success": True,
                    "species_count": 2,
                    "reaction_count": 3,
                },
                "simulation_comparison": {
                    "passed": True,
                    "skipped": False,
                    "failed_observables": [],
                },
            }
        ],
    }
    record.update(overrides)
    return record


def _report(records: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    report = {
        "schema_version": 4,
        "mode": "flat",
        "manifest": "/repo/provenance/published-biomodels.json",
        "cache_dir": "/tmp/biomodels-cache",
        "command": [
            "python",
            "scripts/ci/validate_published_biomodels.py",
            "--cache-dir",
            "/tmp/biomodels-cache",
        ],
        "runtime_provenance": {
            "bionetgen_package_path": "/tmp/one/python/bionetgen/__init__.py",
            "native_extension_path": "/tmp/one/build/cpp/_bionetgen_cpp.so",
            "native_extension_sha256": "aaaa",
            "python_package_source_sha256": "bbbb",
            "python_executable": "/usr/bin/python",
        },
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
            "sbml_records": len(records),
        },
        "records": records,
        "summary": {
            "selected_records": len(records),
            "passed_sbml_records": len(records),
            "failed_records": 0,
            "timeout_records": 0,
            "unsupported_records": 0,
        },
        "unsupported_summary": {
            "record_count": 0,
            "by_cause": {},
            "stoichiometry_subsummary": {"record_count": 0, "by_subcause": {}},
        },
        "sbml_unsupported_summary": {
            "record_count": 0,
            "by_cause": {},
            "stoichiometry_subsummary": {"record_count": 0, "by_subcause": {}},
        },
        "simulation": {
            "t_start": 0.0,
            "t_end": 1.0,
            "n_steps": 10,
            "rtol": 1e-07,
            "atol": 1e-12,
        },
        "writer_sbml_version": "L3V2",
        "core_passed": True,
        "supported_surface_passed": True,
        "unsupported_formats_are_explicit": True,
        "simulation_comparison_is_required": True,
    }
    report.update(overrides)
    return report


def test_runtime_provenance_is_not_a_verdict_difference():
    """Two runs of the same corpus under different builds agree on verdicts."""

    left = _report([_record("BIOMD0000000001")])
    right = _report(
        [_record("BIOMD0000000001")],
        manifest="/other/checkout/provenance/published-biomodels.json",
        cache_dir="/other/cache",
        command=["python", "scripts/ci/validate_published_biomodels.py", "--jobs", "8"],
        runtime_provenance={
            "bionetgen_package_path": "/tmp/two/python/bionetgen/__init__.py",
            "native_extension_path": "/tmp/two/build/cpp/_bionetgen_cpp.so",
            "native_extension_sha256": "cccc",
            "python_package_source_sha256": "dddd",
            "python_executable": "/opt/other/python",
        },
    )

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences == []
    assert comparison.report_differences == []
    assert comparison.timeout_differences == []
    assert comparison.differing_records == []
    assert comparison.provenance_notes


def test_a_real_verdict_difference_is_still_reported():
    """Excluding provenance must not hide an actual verdict change."""

    left = _report([_record("BIOMD0000000001")])
    right = _report([_record("BIOMD0000000001", status="failed", core_passed=False)])

    comparison = comparator.compare_reports(left, right)

    assert comparison.differing_records == ["BIOMD0000000001"]
    assert comparison.verdict_differences
    assert any("status" in difference for difference in comparison.verdict_differences)


def test_record_order_does_not_change_the_verdict():
    """A different dispatch order must not report a difference."""

    left = _report(
        [
            _record("BIOMD0000000001"),
            _record("BIOMD0000000002"),
            _record("BIOMD0000000003"),
        ]
    )
    right = _report(
        [
            _record("BIOMD0000000003"),
            _record("BIOMD0000000001"),
            _record("BIOMD0000000002"),
        ]
    )

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences == []
    assert comparison.report_differences == []
    assert comparison.differing_records == []


def test_summary_case_lists_are_compared_without_order():
    """The unsupported-cause summaries list records in record order."""

    left = _report(
        [_record("BIOMD0000000001"), _record("BIOMD0000000002")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["BIOMD0000000001", "BIOMD0000000002"]}
            },
        },
    )
    right = _report(
        [_record("BIOMD0000000002"), _record("BIOMD0000000001")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["BIOMD0000000002", "BIOMD0000000001"]}
            },
        },
    )

    comparison = comparator.compare_reports(left, right)

    assert comparison.report_differences == []


def test_a_membership_change_in_a_summary_list_is_reported():
    """Order insensitivity must not hide a record that appears or disappears."""

    left = _report(
        [_record("BIOMD0000000001"), _record("BIOMD0000000002")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["BIOMD0000000001", "BIOMD0000000002"]}
            },
        },
    )
    right = _report(
        [_record("BIOMD0000000001"), _record("BIOMD0000000002")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["BIOMD0000000001", "BIOMD0000000003"]}
            },
        },
    )

    comparison = comparator.compare_reports(left, right)

    assert comparison.report_differences
    assert any(
        "BIOMD0000000003" in difference for difference in comparison.report_differences
    )


def test_a_missing_record_is_reported():
    """A record that ran in one report and not the other is a difference."""

    left = _report([_record("BIOMD0000000001"), _record("BIOMD0000000002")])
    right = _report([_record("BIOMD0000000001")])

    comparison = comparator.compare_reports(left, right)

    assert comparison.differing_records == ["BIOMD0000000002"]
    assert any(
        "missing from the second report" in difference
        for difference in comparison.verdict_differences
    )


def test_a_timeout_difference_is_reported_as_such_and_is_not_a_change():
    """A timeout is load-sensitive, so it is not a verdict difference."""

    left = _report([_record("BIOMD0000000001")])
    timed_out = _record("BIOMD0000000001", status="timeout", core_passed=False)
    timed_out.pop("modes")
    right = _report([timed_out])

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences == []
    assert comparison.timeout_differences
    assert comparison.differing_records == ["BIOMD0000000001"]


def test_a_timeout_in_one_direction_is_a_timeout_difference():
    """The other direction is load-sensitive in exactly the same way."""

    left = _report([_record("BIOMD0000000001", status="timeout", core_passed=False)])
    right = _report([_record("BIOMD0000000001")])

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences == []
    assert comparison.timeout_differences


def test_an_unsupported_format_change_is_a_verdict_difference():
    """``unsupported_format`` is a refusal with a construct: it is a verdict."""

    left = _report(
        [_record("BIOMD0000000001", status="unsupported_format", core_passed=False)]
    )
    right = _report([_record("BIOMD0000000001")])

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences
    assert not comparison.timeout_differences


def test_the_stage_is_named_in_a_per_record_difference():
    """A reader must see which stage of the gate moved."""

    left = _report([_record("BIOMD0000000001")])
    right = _report([_record("BIOMD0000000001")])
    right["records"][0]["modes"][0]["simulation_comparison"] = {
        "passed": False,
        "skipped": False,
        "failed_observables": ["S1"],
        "error": "BNG3 CVODE/libRoadRunner observable mismatch: S1",
    }

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences
    assert any(
        "flat:independent_comparison" in difference
        for difference in comparison.verdict_differences
    )


def test_the_command_line_reports_no_false_difference(tmp_path):
    """The shipped command must not cry wolf over provenance."""

    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(json.dumps(_report([_record("BIOMD0000000001")])), encoding="utf-8")
    right.write_text(
        json.dumps(
            _report(
                [_record("BIOMD0000000001")],
                cache_dir="/other/cache",
                runtime_provenance={"bionetgen_package_path": "/other/bionetgen.py"},
            )
        ),
        encoding="utf-8",
    )

    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "ci"
        / "compare_biomodels_suite_reports.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), str(left), str(right)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "identical verdicts for 1 records" in result.stdout


def test_the_command_line_fails_on_a_verdict_difference(tmp_path):
    """The shipped command must fail when a verdict moved."""

    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(json.dumps(_report([_record("BIOMD0000000001")])), encoding="utf-8")
    right.write_text(
        json.dumps(
            _report([_record("BIOMD0000000001", status="failed", core_passed=False)])
        ),
        encoding="utf-8",
    )

    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "ci"
        / "compare_biomodels_suite_reports.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), str(left), str(right)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "BIOMD0000000001" in result.stdout


@pytest.mark.parametrize("field", ["cache_dir", "manifest", "command"])
def test_run_local_fields_are_reported_as_notes(field):
    """A run-local field that differs is a note, never a difference."""

    left = _report([_record("BIOMD0000000001")])
    right = _report([_record("BIOMD0000000001")])
    right[field] = "/somewhere/else"

    comparison = comparator.compare_reports(left, right)

    assert comparison.verdict_differences == []
    assert comparison.report_differences == []
    assert any(field in note for note in comparison.provenance_notes)
