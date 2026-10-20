"""Contracts for the Atomizer symbol-resolution qualification.

``tests/validation/atomizer_symbol_resolution.py`` characterizes the symbol
resolution and feature-check surface of the Atomizer (issue #164).  These
tests pin the properties that keep the characterization independent: the
expectation is stated per scope, a resolver that changes its answer fails the
check, and a refusal is never read as a resolution.
"""

from __future__ import annotations

import pytest

from tests.validation import atomizer_symbol_resolution


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("atomizer_symbol_resolution")
    return atomizer_symbol_resolution.run_worker(directory)


def test_every_generated_case_satisfies_its_resolution_contract(rows):
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == set(atomizer_symbol_resolution.check_ids())
    for row in rows:
        assert row["status"] == "PASS", row["detail"]


def test_the_generated_family_covers_every_declared_scope(rows):
    scopes = {case["scope"] for case in atomizer_symbol_resolution.cases()}
    assert scopes == {
        "global-parameter",
        "reaction-local-parameter",
        "reaction-local-out-of-scope",
        "species",
        "compartment",
        "function",
        "rate-rule",
        "conversion-factor",
    }


def test_the_family_is_generated_over_several_names():
    names = {
        case["name"]
        for case in atomizer_symbol_resolution.cases()
        if case["scope"] == "global-parameter"
    }
    assert len(names) >= 3


def test_a_refusal_is_never_read_as_a_resolution(tmp_path, monkeypatch):
    case = atomizer_symbol_resolution.cases()[0]
    monkeypatch.setattr(
        atomizer_symbol_resolution,
        "_resolve",
        lambda _case: ("", [], "the atomizer reported no BNGL output"),
    )
    row = atomizer_symbol_resolution._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "refusal"


def test_a_resolver_that_stops_declaring_the_symbol_fails_the_case(
    tmp_path, monkeypatch
):
    case = atomizer_symbol_resolution.cases()[0]
    monkeypatch.setattr(
        atomizer_symbol_resolution,
        "_resolve",
        lambda _case: ("begin model\nend model\n", [], None),
    )
    row = atomizer_symbol_resolution._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "parameters"


def test_a_symbol_that_leaks_into_the_global_scope_fails_the_case(
    tmp_path, monkeypatch
):
    case = next(
        case
        for case in atomizer_symbol_resolution.cases()
        if case["scope"] == "reaction-local-parameter"
    )
    monkeypatch.setattr(
        atomizer_symbol_resolution,
        "_resolve",
        lambda _case: (
            "begin model\nbegin parameters\n  lr 2\nend parameters\n"
            "begin reaction rules\n  R1: A() -> B() lr TotalRate\n"
            "end reaction rules\nend model\n",
            [],
            None,
        ),
    )
    row = atomizer_symbol_resolution._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "absent-parameters"


def test_an_emitted_model_that_does_not_compile_fails_the_case(tmp_path, monkeypatch):
    case = atomizer_symbol_resolution.cases()[0]
    monkeypatch.setattr(
        atomizer_symbol_resolution,
        "_resolve",
        lambda _case: (
            "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
            "begin reaction rules\n  R1: A() -> B() k * undefined_symbol TotalRate\n"
            "end reaction rules\nend model\n",
            [],
            None,
        ),
    )
    row = atomizer_symbol_resolution._check_case(case, tmp_path)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "executable"


def test_the_resolution_rows_are_supported_execution_evidence(rows):
    for row in rows:
        assert row["supported_execution"] is True
        assert row["evidence_kind"] == "supported-execution"
        assert row["related_issues"] == [164]
