"""The gate report comparison must report verdicts, not provenance or order.

The comparison tool is the instrument the campaign uses to show that a
change to the gate's execution strategy changed no verdict.  A tool that
reports a difference where there is none is worse than no tool, because it
teaches the reader to ignore it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


def _load_comparator():
    path = (
        Path(__file__).parents[1] / "scripts" / "ci" / "compare_sbml_suite_reports.py"
    )
    spec = importlib.util.spec_from_file_location("compare_sbml_suite_reports", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comparator = _load_comparator()


def _record(case_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "category": "semantic",
        "id": case_id,
        "status": "passed",
        "core_passed": True,
        "roundtrip_passed": True,
        "unsupported_reason": None,
        "error": None,
        "simulation_comparison": {
            "passed": True,
            "observables": {"S1": {"passed": True, "max_abs_diff": 0.0}},
        },
        "official_conformance": {"status": "passed", "reason": ""},
        "worker_runtime_provenance": {
            "python_executable": "/usr/bin/python",
            "bionetgen_package_path": "/tmp/one/python/bionetgen/__init__.py",
            "native_extension_sha256": "aaaa",
            "python_package_source_sha256": "bbbb",
        },
    }
    record.update(overrides)
    return record


def _report(records: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    report = {
        "records": records,
        "counts": {"passed": len(records)},
        "stage_counts": {"conversion": {"passed": len(records)}},
        "by_category": {"semantic": {"passed": len(records)}},
        "official_conformance": {
            "counts": {"passed": len(records)},
            "summary": {
                "non_passed_count": 0,
                "non_passed_records": [],
                "by_status_and_reason": [],
            },
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
        "partial_run": False,
        "selected_surface_passed": True,
        "core_passed": True,
        "supported_surface_passed": True,
        "case_inventory": len(records),
        "full_suite_inventory": {"total": len(records)},
        "selected_cases": len(records),
    }
    report.update(overrides)
    return report


def test_runtime_provenance_is_not_a_verdict_difference():
    """Two runs of the same corpus under different builds agree on verdicts."""

    left = _report([_record("00001")])
    right = _report(
        [
            _record(
                "00001",
                worker_runtime_provenance={
                    "python_executable": "/opt/other/python",
                    "bionetgen_package_path": "/tmp/two/python/bionetgen/__init__.py",
                    "native_extension_sha256": "cccc",
                    "python_package_source_sha256": "dddd",
                },
            )
        ]
    )

    differences, differing_cases, report_differences = comparator.compare_reports(
        left, right
    )

    assert differences == []
    assert differing_cases == []
    assert report_differences == []
    assert comparator._provenance_only_cases(left, right) == ["semantic/00001"]


def test_a_real_verdict_difference_is_still_reported():
    """Excluding provenance must not hide an actual verdict change."""

    left = _report([_record("00001")])
    right = _report([_record("00001", status="unsupported", core_passed=False)])

    differences, differing_cases, _ = comparator.compare_reports(left, right)

    assert differing_cases == ["semantic/00001"]
    assert any("status" in difference for difference in differences)


def test_case_order_does_not_change_the_verdict():
    """A different dispatch order must not report a difference."""

    left = _report([_record("00001"), _record("00002"), _record("00003")])
    right = _report([_record("00003"), _record("00001"), _record("00002")])

    differences, differing_cases, report_differences = comparator.compare_reports(
        left, right
    )

    assert differences == []
    assert differing_cases == []
    assert report_differences == []


def test_summary_case_lists_are_compared_without_order():
    """The unsupported-cause summaries list cases in record order."""

    left = _report(
        [_record("00001"), _record("00002")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["00001", "00002"], "records": []}
            },
            "stoichiometry_subsummary": {"record_count": 0, "by_subcause": {}},
        },
    )
    right = _report(
        [_record("00002"), _record("00001")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["00002", "00001"], "records": []}
            },
            "stoichiometry_subsummary": {"record_count": 0, "by_subcause": {}},
        },
    )

    _, _, report_differences = comparator.compare_reports(left, right)

    assert report_differences == []


def test_a_membership_change_in_a_summary_list_is_reported():
    """Order insensitivity must not hide a case that appears or disappears."""

    left = _report(
        [_record("00001"), _record("00002")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["00001", "00002"], "records": []}
            },
            "stoichiometry_subsummary": {"record_count": 0, "by_subcause": {}},
        },
    )
    right = _report(
        [_record("00001"), _record("00002")],
        unsupported_summary={
            "record_count": 2,
            "by_cause": {
                "events": {"count": 2, "ids": ["00001", "00003"], "records": []}
            },
            "stoichiometry_subsummary": {"record_count": 0, "by_subcause": {}},
        },
    )

    _, _, report_differences = comparator.compare_reports(left, right)

    assert report_differences
    assert any("00003" in difference for difference in report_differences)


def test_a_missing_case_is_reported():
    """A case that ran in one report and not the other is a difference."""

    left = _report([_record("00001"), _record("00002")])
    right = _report([_record("00001")])

    differences, differing_cases, _ = comparator.compare_reports(left, right)

    assert differing_cases == ["semantic/00002"]
    assert any("missing from the second report" in d for d in differences)


def test_the_command_line_reports_no_false_difference(tmp_path, capsys):
    """The shipped command must not cry wolf over provenance."""

    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(json.dumps(_report([_record("00001")])), encoding="utf-8")
    right.write_text(
        json.dumps(
            _report(
                [
                    _record(
                        "00001",
                        worker_runtime_provenance={
                            "python_executable": "/opt/other/python"
                        },
                    )
                ]
            )
        ),
        encoding="utf-8",
    )

    import subprocess
    import sys

    script = (
        Path(__file__).parents[1] / "scripts" / "ci" / "compare_sbml_suite_reports.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), str(left), str(right)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "identical verdicts for 1 cases" in result.stdout
