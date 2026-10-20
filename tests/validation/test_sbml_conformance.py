"""Harness contract checks for the locked official SBML conformance family."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.validation import sbml_conformance
from tests.validation import integrated_extensions as extensions

ROOT = Path(__file__).resolve().parents[2]


def test_check_identities_are_stable_and_unique():
    ids = sbml_conformance.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("sbml-conformance:") for item in ids)


def test_the_family_reports_the_four_outcomes_separately():
    """A green conversion must not be able to stand in for a reference check."""

    stages = {row[1] for row in sbml_conformance.STAGE_ROWS}
    assert stages == {
        "conversion",
        "roundtrip",
        "official-reference",
        "independent-oracle",
    }
    ids = set(sbml_conformance.check_ids())
    for stage in stages:
        assert f"sbml-conformance:{stage}" in ids
    # The four outcomes are four rows, not one aggregate row.
    assert len(sbml_conformance.STAGE_ROWS) == 4
    assert len({row[0] for row in sbml_conformance.STAGE_ROWS}) == 4


def test_the_event_and_zero_observable_cohorts_have_their_own_rows():
    ids = set(sbml_conformance.check_ids())
    assert sbml_conformance.EVENT_ROW in ids
    assert sbml_conformance.ZERO_OBSERVABLE_ROW in ids
    assert sbml_conformance.RUNNER_ROW in ids


def test_a_failed_stage_fails_its_own_row_and_not_a_neighbour():
    counts = {
        "conversion": {"passed": 12, "unsupported": 1},
        "roundtrip_structure": {"passed": 12, "unsupported": 1},
        "official_reference": {"passed": 10, "failed": 1, "unsupported": 2},
        "independent_comparison": {"passed": 12, "unsupported": 1},
    }
    statuses = {key: sbml_conformance._stage_status(counts, key)[0] for key in counts}
    assert statuses["official_reference"] == "FAIL"
    assert statuses["conversion"] == "PASS"
    assert statuses["independent_comparison"] == "PASS"


def test_a_wholly_unsupported_stage_is_not_reported_as_a_pass():
    counts = {"official_reference": {"unsupported": 3}}
    status, detail = sbml_conformance._stage_status(counts, "official_reference")
    assert status == "UNSUPPORTED"
    assert "not a conformance pass" in detail


def test_an_unexecuted_stage_is_not_reported_as_a_pass():
    counts = {"official_reference": {}}
    status, _detail = sbml_conformance._stage_status(counts, "official_reference")
    assert status == "NOT_TESTED"


def test_a_missing_suite_checkout_is_never_a_pass(tmp_path):
    rows = sbml_conformance.run(tmp_path, suite_dir=None)
    assert {row["id"] for row in rows} == set(sbml_conformance.check_ids())
    assert all(row["status"] == "NOT_TESTED" for row in rows)
    assert all("not evidence of conformance" in row["detail"] for row in rows)


def test_the_locked_suite_family_is_not_a_campaign_stage():
    """The locked suite is an external corpus; the campaign cannot supply it."""

    assert "sbml-conformance" not in extensions.OPERATIONS
    assert "atomizer-reconstruction" in extensions.OPERATIONS


def test_the_obligation_catalog_names_the_new_checks():
    catalog = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next(item for item in catalog["issues"] if item["number"] == 159)
    named = {
        check["id"]
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
    }
    assert set(sbml_conformance.check_ids()).issubset(named)
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            assert not check["id"].startswith("qualification:"), obligation["id"]


@pytest.mark.slow
@pytest.mark.skipif(
    not (ROOT / "provenance" / "upstreams.lock.yml").is_file(),
    reason="the source lock is not available",
)
def test_the_runner_report_is_mapped_onto_four_separate_outcomes(tmp_path):
    """The family maps one runner report onto four separate outcomes.

    The report is the runner's own schema.  A synthetic report keeps this
    check independent of the external suite checkout while still exercising
    the mapping the family performs on real evidence.
    """

    report = {
        "suite_commit": "0" * 40,
        "source_provenance": {"bng3_commit": "0" * 40},
        "runtime_provenance": {"native_extension_sha256": "0" * 64},
        "stage_counts": {
            "conversion": {"passed": 3},
            "roundtrip_structure": {"passed": 3},
            "official_reference": {"passed": 2, "failed": 1},
            "independent_comparison": {"passed": 3},
        },
        "records": [
            {
                "id": "00001",
                "source": str(tmp_path / "00001-sbml-l3v2.xml"),
                "official_conformance": {"status": "passed"},
                "simulation_comparison": {"passed": True, "observable_count": 2},
            },
            {
                "id": "00002",
                "source": str(tmp_path / "00002-sbml-l3v2.xml"),
                "official_conformance": {"status": "failed"},
                "simulation_comparison": {"passed": True, "observable_count": 1},
            },
        ],
    }
    (tmp_path / "00001-sbml-l3v2.xml").write_text("<sbml/>\n", encoding="utf-8")
    (tmp_path / "00002-sbml-l3v2.xml").write_text(
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">'
        "<model><listOfEvents><event/></listOfEvents></model></sbml>\n",
        encoding="utf-8",
    )
    event_records, zero_records = sbml_conformance._cohort_rows(report)
    assert [record["id"] for record in event_records] == ["00002"]
    assert zero_records == []

    status, detail, counts = sbml_conformance._cohort_outcome(
        event_records, "official_conformance"
    )
    assert status == "FAIL"
    assert counts["failed"] == 1
    assert "failed" in detail


def test_the_family_runs_the_existing_locked_suite_runner(tmp_path):
    """The family must execute the existing runner, not re-implement it."""

    command = sbml_conformance._run_runner(
        tmp_path,
        tmp_path / "report.json",
        None,
        categories=["semantic"],
        max_cases=1,
        selection_strategy="prefix",
        jobs=1,
        case_timeout=5,
    )
    assert command["command"][1].endswith("scripts/ci/validate_sbml_test_suite.py")
    assert "--suite-dir" in command["command"]
    assert "--isolate-cases" in command["command"]
    # The runner refuses a checkout that does not match the lock, so the
    # family must not report a pass for it.
    assert command["returncode"] != 0
    assert not (tmp_path / "report.json").exists()
