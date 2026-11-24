"""Negative controls for the Issue 159 spec-backed NON-COMPARABLE disposition.

A random event-execution order (SBML L3V2 Core 4.12.3) makes one mapped Core
case impossible to compare point-wise. This module proves that the disposition
is narrow: it is accepted only with the harness-generated reason at every
recording site, and a changed reason, a missing case or a genuine failure still
fails closed in both the recorder and the executable coverage selector.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
from scripts.ci import sbml_noncomparable_disposition as disp

RECORDER_PATH = ROOT / "scripts/ci/record_issue159_release.py"
SELECTOR_PATH = (
    ROOT / "tests/validation/release/cases/issue-159/test_ssts_full_execution.py"
)
HARNESS_PATH = ROOT / "scripts/ci/validate_sbml_test_suite.py"

REVISION = "8a7eca96035808d5f4364bbdcb0d512b3448126a"
SUITE_REVISION = "cf38585fac5de8e0e90112febb62851ee2181816"
ROW = "sbml.core.Priority.math"
CATEGORY = "semantic"
CASE_ID = "00965"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mapping():
    return json.loads((ROOT / "provenance/sbml-core-case-mapping.json").read_text())


def _case_ids(mapping):
    return sorted(
        {
            case_id
            for row, cases in mapping.items()
            if not row.startswith("_")
            for case_id in cases
        }
    )


def _report(mapping, *, missing=False, reason=None, status=None, failed=False):
    records = [
        {"category": CATEGORY, "id": case_id, "status": "passed"}
        for case_id in _case_ids(mapping)
        if not (missing and case_id == CASE_ID)
    ]
    for record in records:
        if record["id"] == CASE_ID:
            record.update(
                {
                    "status": status or ("failed" if failed else "unsupported"),
                    "official_conformance": {
                        "status": "failed" if failed else "unsupported",
                        "reason": reason if reason is not None else disp.REASON,
                    },
                    "unsupported_reason": (
                        reason if reason is not None else disp.REASON
                    ),
                    "simulation_comparison": {
                        "skipped": not failed,
                        "skip_reason": (reason if reason is not None else disp.REASON),
                    },
                }
            )
    return {
        "schema_version": 1,
        "suite_commit": SUITE_REVISION,
        "case_inventory": 1923,
        "case_selection": 1923,
        "selected_cases": 1923,
        "full_suite_inventory": 1923,
        "source_provenance": {
            "bng3_commit": REVISION,
            "bng3_tracked_worktree_clean": True,
        },
        "partial_run": False,
        "counts": {
            "passed": 1819,
            "unsupported": 1,
            "failed": 0,
            "timeout": 0,
            "invalid-source": 0,
        },
        "official_conformance": {"counts": {"failed": 0, "timed-out": 0}},
        "records": records,
    }


def _fixtures():
    recorder = _load(RECORDER_PATH, "recorder_under_test")
    return {"fixtures": {name: True for name in recorder.FIXTURE_NAMES.values()}}


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_pinned_reason_is_generated_by_the_harness():
    """The pin is the harness's own reason, not an acceptance-authored string."""
    harness = _load(HARNESS_PATH, "harness_under_test")

    def event(name, variable):
        return SimpleNamespace(
            id=name,
            trigger="time - reset >= 0.01",
            priority="",
            delay="",
            trigger_persistent=False,
            assignments=[{"variable": "reset"}, {"variable": variable}],
        )

    parsed = SimpleNamespace(events=[event("Qinc", "Q"), event("Rinc", "R")])
    verdict = harness._random_event_execution_verdict(parsed)
    assert verdict is not None
    assert verdict["status"] == "unsupported"
    assert verdict["reason"] == disp.REASON
    assert all(fragment in disp.REASON for fragment in disp.SPEC_BASIS)


def test_pinned_case_source_semantics():
    """Source facts come from the pinned SSTS case when the suite is present."""
    suite_dir = os.environ.get("BNG3_SSTS_SUITE_DIR")
    if not suite_dir:
        pytest.skip("BNG3_SSTS_SUITE_DIR not provided")
    case = Path(suite_dir) / "cases/semantic/00965/00965-sbml-l3v2.xml"
    root = ET.parse(case).getroot()
    ns = {"sbml": "http://www.sbml.org/sbml/level3/version2/core"}
    events = {
        event.get("id"): event
        for event in root.findall(".//sbml:event", ns)
        if event.get("id") in {"Qinc", "Rinc"}
    }
    assert set(events) == {"Qinc", "Rinc"}
    triggers, priorities, assignments = {}, {}, {}
    for name, event in events.items():
        trigger = event.find("sbml:trigger", ns)
        priority = event.find("sbml:priority", ns)
        assert trigger is not None and trigger.get("persistent") == "false"
        assert priority is not None and "10" in ET.tostring(
            priority, encoding="unicode"
        )
        trigger_math = next(
            child for child in trigger if child.tag.rsplit("}", 1)[-1] == "math"
        )
        triggers[name] = ET.tostring(trigger_math, encoding="unicode")
        priorities[name] = ET.tostring(priority, encoding="unicode")
        assignments[name] = ET.tostring(
            event.find("sbml:listOfEventAssignments", ns), encoding="unicode"
        )
    assert triggers["Qinc"] == triggers["Rinc"]
    assert priorities["Qinc"] == priorities["Rinc"]
    assert 'variable="reset"' in assignments["Qinc"]
    assert 'variable="reset"' in assignments["Rinc"]
    assert 'variable="Q"' in assignments["Qinc"]
    assert 'variable="R"' in assignments["Rinc"]


def test_exact_disposition_is_emitted(tmp_path, monkeypatch):
    mapping = _mapping()
    report = _report(mapping)
    recorder = _load(RECORDER_PATH, "recorder_exact")
    diagnostics, receipt, dispositions = recorder._verify_core_coverage(
        report, mapping, _fixtures()
    )
    assert diagnostics == []
    assert len(dispositions) == 1
    row = dispositions[0]
    assert row["id"] == "non-comparable:semantic/00965"
    assert row["status"] == disp.DISPOSITION_STATUS
    assert row["supported_execution"] is False
    assert row["counts_as_pass"] is False
    assert row["reason"] == disp.REASON
    assert receipt["disposition_ids"] == [row["id"]]

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(recorder.subprocess, "run", lambda *a, **k: _Completed())
    suite = _write_json(tmp_path / "report.json", report)
    fixtures = _write_json(tmp_path / "fixtures.json", _fixtures())
    expectations = _write_json(tmp_path / "expectations.json", {})
    full = recorder.build_release_report(
        suite, expectations, REVISION, core_fixtures_report=fixtures
    )
    assert [row["id"] for row in full["dispositions"]] == [row["id"]]
    assert {result["id"] for result in full["results"]} == {
        "release-ssts",
        "release-ssts-coverage",
        "release-obligation-159",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "changed-reason",
        "missing-case",
        "genuine-failure",
        "spec-basis-removed",
    ],
)
def test_recorder_fails_closed(mutation, tmp_path, monkeypatch):
    mapping = _mapping()
    kwargs = {}
    if mutation == "changed-reason":
        kwargs["reason"] = "some other unsupported reason"
    elif mutation == "missing-case":
        kwargs["missing"] = True
    elif mutation == "genuine-failure":
        kwargs["failed"] = True
    elif mutation == "spec-basis-removed":
        kwargs["reason"] = disp.REASON.replace(
            "SBML Level 3 Version 2 Core, Release 2, section 4.12.3",
            "an unspecified rule",
        )
    report = _report(mapping, **kwargs)
    recorder = _load(RECORDER_PATH, "recorder_negative")
    diagnostics, _, dispositions = recorder._verify_core_coverage(
        report, mapping, _fixtures()
    )
    assert dispositions == []
    assert diagnostics, f"{mutation} was accepted as coverage"

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(recorder.subprocess, "run", lambda *a, **k: _Completed())
    suite = _write_json(tmp_path / "report.json", report)
    fixtures = _write_json(tmp_path / "fixtures.json", _fixtures())
    expectations = _write_json(tmp_path / "expectations.json", {})
    with pytest.raises(ValueError) as caught:
        recorder.build_release_report(
            suite, expectations, REVISION, core_fixtures_report=fixtures
        )
    assert "release-ssts-coverage" in str(caught.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "changed-reason",
        "missing-case",
        "genuine-failure",
        "spec-basis-removed",
    ],
)
def test_selector_fails_closed(mutation, tmp_path, monkeypatch):
    mapping = _mapping()
    kwargs = {}
    if mutation == "changed-reason":
        kwargs["reason"] = "some other unsupported reason"
    elif mutation == "missing-case":
        kwargs["missing"] = True
    elif mutation == "genuine-failure":
        kwargs["failed"] = True
    elif mutation == "spec-basis-removed":
        kwargs["reason"] = disp.REASON.replace(
            "SBML Level 3 Version 2 Core, Release 2, section 4.12.3",
            "an unspecified rule",
        )
    report = _write_json(tmp_path / "ssts.json", _report(mapping, **kwargs))
    fixtures = _write_json(tmp_path / "fixtures.json", _fixtures())
    monkeypatch.setenv("BNG3_SSTS_FULL_REPORT", str(report))
    monkeypatch.setenv("BNG3_CORE_FIXTURES_REPORT", str(fixtures))
    selector = _load(SELECTOR_PATH, "selector_negative")
    with pytest.raises((AssertionError, KeyError)):
        selector.test_release_ssts_coverage()
