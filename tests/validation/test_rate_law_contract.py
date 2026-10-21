"""Rate-law and local-function contract qualification (#143).

The qualification states the supported special-rate, TFUN, scope, multiplicity
and dependency/evaluation conventions executably and compares the supported
backends' coefficients, right-hand sides and propensities against closed-form
laws. These tests keep the comparison honest: the case matrix must stay
inside the declared slice, the generated check identities must be stable, and
a wrong expectation must fail instead of passing quietly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.validation import campaign
from tests.validation import rate_law_contract as rate_law

ISSUES = (143,)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("rate-law-contract")
    return rate_law.run_worker(directory)


def test_the_conventions_are_stated_once():
    assert set(rate_law.CONVENTIONS) == {
        "special-rate",
        "tfun",
        "scope",
        "multiplicity",
        "dependency",
        "cache",
    }
    for name, text in rate_law.CONVENTIONS.items():
        assert isinstance(text, str) and text.strip()
    assert rate_law.SUPPORTED_SLICE.strip()


def test_generated_case_matrix_covers_the_declared_conventions():
    families = {case["family"] for case in rate_law.cases()}
    assert families == {
        "elementary",
        "special-saturation",
        "special-hill",
        "special-michaelis-menten",
        "table-function",
        "local-scope",
        "multiplicity",
        "special-multiplicity",
        "dependency",
        "cache-invalidation",
    }
    for case in rate_law.cases():
        assert case["bngl"].count("begin reaction rules") == 1
        assert case["rate_law_kind"] in rate_law.RATE_LAW_KINDS
        assert case["states"]
        assert len(case["states"]) == len(case["reactions"])
        assert len(case["states"]) == len(case["rhs"])
        for expected in case["reactions"]:
            assert isinstance(expected, list)
            for reaction in expected:
                assert "coefficient" in reaction and "propensity" in reaction
                assert "reactants" in reaction and "products" in reaction


def test_the_boundary_cases_stay_outside_the_slice():
    constructs = {case["construct"] for case in rate_law.boundary_cases()}
    assert constructs == {
        "compartment",
        "filter",
        "modifier",
        "energy",
        "population map",
    }


def test_check_identities_are_stable_and_unique():
    ids = rate_law.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("rate-law-contract:") for item in ids)
    assert "rate-law-contract:elementary-r0:coefficient" in ids
    assert "rate-law-contract:cache-rate-parameter:cache-invalidation" in ids
    assert "rate-law-contract:boundary-filter:slice" in ids


def test_every_case_reaches_a_named_observation(rows):
    assert {row["id"] for row in rows} == set(rate_law.check_ids())
    for row in rows:
        assert row["status"] in campaign.STATUSES
        assert row["related_issues"] == list(ISSUES)
        assert row["detail"]
        assert row["source_artifact"].endswith(".bngl")
        assert len(row["source_sha256"]) == 64


def test_the_backends_agree_with_the_closed_form_laws(rows):
    failures = [row for row in rows if row["status"] != "PASS"]
    assert not failures, json.dumps(failures, indent=2)


def test_a_wrong_coefficient_expectation_is_reported_as_a_difference(
    tmp_path, monkeypatch
):
    """The comparison must fail when the independent expectation is wrong."""
    original_cases = rate_law.cases

    def broken_cases():
        cases = []
        for case in original_cases():
            case = dict(case)
            if case["id"] == "elementary-r0":
                case["reactions"] = [
                    [
                        dict(
                            reactants=["A()"],
                            products=["B()"],
                            coefficient=0.5,
                            propensity=0.5 * 10,
                        )
                    ]
                ]
            cases.append(case)
        return cases

    monkeypatch.setattr(rate_law, "cases", broken_cases)
    broken = rate_law.run_worker(tmp_path)
    row = next(
        item
        for item in broken
        if item["id"] == "rate-law-contract:elementary-r0:coefficient"
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"].startswith("coefficient")


def test_a_wrong_rhs_expectation_is_reported_as_a_difference(tmp_path, monkeypatch):
    """The right-hand side must be able to contradict the engine."""
    original_cases = rate_law.cases

    def broken_cases():
        cases = []
        for case in original_cases():
            case = dict(case)
            if case["id"] == "elementary-r0":
                case["rhs"] = [{"A()": -1.0, "B()": 1.0}]
            cases.append(case)
        return cases

    monkeypatch.setattr(rate_law, "cases", broken_cases)
    broken = rate_law.run_worker(tmp_path)
    row = next(
        item for item in broken if item["id"] == "rate-law-contract:elementary-r0:rhs"
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "rhs.A()"


def test_a_wrong_propensity_expectation_is_reported_as_a_difference(
    tmp_path, monkeypatch
):
    """The SSA propensity must be able to contradict the engine."""
    original_cases = rate_law.cases

    def broken_cases():
        cases = []
        for case in original_cases():
            case = dict(case)
            if case["id"] == "multiplicity-identical":
                case["reactions"] = [
                    [
                        dict(
                            reactants=["A()", "A()"],
                            products=["B()"],
                            coefficient=0.2,
                            propensity=0.2 * 6 * 6,
                        )
                    ]
                ]
            cases.append(case)
        return cases

    monkeypatch.setattr(rate_law, "cases", broken_cases)
    broken = rate_law.run_worker(tmp_path)
    row = next(
        item
        for item in broken
        if item["id"] == "rate-law-contract:multiplicity-identical:propensity"
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"].startswith("propensity")


def test_a_case_outside_the_slice_is_reported_as_unsupported(tmp_path, monkeypatch):
    """A case outside the declared slice is refused, not silently skipped."""

    def refusing_guard(snapshot, case):
        raise rate_law.UnsupportedSlice("the model declares a compartment")

    monkeypatch.setattr(rate_law, "_slice_guard", refusing_guard)
    broken = rate_law.run_worker(tmp_path)
    row = next(
        item
        for item in broken
        if item["id"] == "rate-law-contract:elementary-r0:coefficient"
    )
    assert row["status"] == "UNSUPPORTED"
    assert row["supported_execution"] is False
    assert "outside the qualified slice" in row["detail"]


def test_the_cache_invalidation_check_follows_the_changed_rate(tmp_path, monkeypatch):
    """A stale cached rate must be reported, not accepted."""
    original_cases = rate_law.cases

    def broken_cases():
        cases = []
        for case in original_cases():
            case = dict(case)
            if case["id"] == "cache-rate-parameter":
                mutated = dict(case["mutated"])
                mutated["reactions"] = [
                    [
                        dict(
                            reactants=["A()"],
                            products=["B()"],
                            coefficient=0.4,
                            propensity=4.0,
                        )
                    ]
                ]
                case["mutated"] = mutated
            cases.append(case)
        return cases

    monkeypatch.setattr(rate_law, "cases", broken_cases)
    broken = rate_law.run_worker(tmp_path)
    row = next(
        item
        for item in broken
        if item["id"] == "rate-law-contract:cache-rate-parameter:cache-invalidation"
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"] is not None


def test_the_extension_registry_emits_the_declared_identities(tmp_path, monkeypatch):
    """The campaign import must accept the rows the worker emits."""
    from argparse import Namespace

    from tests.validation import integrated_extensions as extensions

    monkeypatch.chdir(tmp_path)
    args = Namespace(report_dir=tmp_path, ensemble_runs=32)
    emitted = extensions.run_worker("rate-law-contract", args)
    assert [row["id"] for row in emitted] == extensions.check_ids("rate-law-contract")
    for row in emitted:
        assert row["check"] == row["id"].rsplit(":", 1)[-1]
        assert row["status"] in campaign.STATUSES
        assert isinstance(row["detail"], str) and row["detail"]
        assert row["related_issues"] and all(
            isinstance(number, int) and number >= 1 for number in row["related_issues"]
        )
        artifact = tmp_path / row["source_artifact"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == row["source_sha256"]
