"""Contracts for the unsupported-SBML-construct boundary qualification.

``tests/validation/sbml_support_boundary.py`` groups the current unsupported
SBML cases by feature class (issue #160).  These tests pin the properties that
make the grouping executable rather than descriptive: every generated case
must produce a diagnostic that names its construct and records its class, and
the harness must fail when a case is refused for an unnamed reason.
"""

from __future__ import annotations

import pytest

from tests.validation import sbml_support_boundary


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("sbml_support_boundary")
    return sbml_support_boundary.run_worker(directory)


def test_every_generated_case_names_its_construct_and_records_its_class(rows):
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == set(sbml_support_boundary.check_ids())
    for case in sbml_support_boundary.cases():
        row = by_id[f"sbml-support-boundary:{case['id']}:named-diagnostic"]
        assert row["status"] == "PASS", row["detail"]
        assert case["group"] in row["detail"]


def test_the_generated_corpus_covers_every_class_issue_160_names(rows):
    groups = {case["group"] for case in sbml_support_boundary.cases()}
    assert groups == {
        "dynamic-rules",
        "events",
        "history",
        "algebraic-constraints",
        "stoichiometry",
        "fast-reactions",
        "packages",
    }


def test_a_refusal_without_a_named_diagnostic_fails_the_case(tmp_path, monkeypatch):
    case = sbml_support_boundary.cases()[0]
    monkeypatch.setattr(
        sbml_support_boundary,
        "_diagnostics",
        lambda _case: ([], "the atomizer reported no BNGL output"),
    )
    row, _ = sbml_support_boundary._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "unnamed-refusal"


def test_a_diagnostic_without_the_expected_class_fails_the_case(tmp_path, monkeypatch):
    case = sbml_support_boundary.cases()[0]
    monkeypatch.setattr(
        sbml_support_boundary,
        "_diagnostics",
        lambda _case: (
            [
                {
                    "category": case["category"],
                    "message": f"the {case['token']} construct was refused",
                    "count": 1,
                    "severity": "dropped",
                    "group": "other",
                }
            ],
            None,
        ),
    )
    row, _ = sbml_support_boundary._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "group"


def test_a_diagnostic_that_does_not_name_the_construct_fails_the_case(
    tmp_path, monkeypatch
):
    case = sbml_support_boundary.cases()[0]
    monkeypatch.setattr(
        sbml_support_boundary,
        "_diagnostics",
        lambda _case: (
            [
                {
                    "category": case["category"],
                    "message": "something else went wrong",
                    "count": 1,
                    "severity": "dropped",
                    "group": case["group"],
                }
            ],
            None,
        ),
    )
    row, _ = sbml_support_boundary._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "named-diagnostic"


def test_an_unclassified_refusal_fails_the_corpus_check():
    row = sbml_support_boundary._check_corpus(
        {
            "case": [
                {
                    "category": "brandNewConstruct",
                    "message": "a construct nobody classified",
                    "count": 1,
                    "severity": "dropped",
                    "group": "other",
                }
            ]
        }
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "unclassified-refusals"


def test_an_informational_note_is_not_required_to_be_classified():
    row = sbml_support_boundary._check_corpus(
        {
            "case": [
                {
                    "category": "units",
                    "message": "the source numeric scale was preserved",
                    "count": 1,
                    "severity": "info",
                    "group": "units",
                }
            ]
        }
    )
    assert row["status"] == "PASS"


def test_the_refusal_rows_never_claim_supported_execution(rows):
    for row in rows:
        assert row["supported_execution"] is False
        assert row["evidence_kind"] == "diagnostic-only"
        assert row["related_issues"] == [160]
