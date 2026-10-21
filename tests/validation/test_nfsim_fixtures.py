"""Focused contracts for the generated NFsim fixture family (issue #146).

The campaign qualification lives in ``tests/validation/integrated_nfsim_fixtures.py``.
These tests are the focused, offline part: the family covers the named
features, the route assertion is fail-closed, the direct and XML routes agree
bit for bit, the independent source count law is reproduced, and a missing
oracle is reported as an untested route rather than as a pass.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.validation import integrated_nfsim_fixtures as fixtures

NAMED_FEATURES = {
    "scopes",
    "dynamic-rates",
    "observables",
    "symmetry",
    "deletion",
    "filters",
    "compartments",
    "lifecycle",
}


def case_by(feature):
    return next(case for case in fixtures.fixture_cases() if case["feature"] == feature)


def test_the_family_covers_every_named_feature_exactly_once():
    cases = fixtures.fixture_cases()
    assert {case["feature"] for case in cases} == NAMED_FEATURES
    assert len(cases) == len(NAMED_FEATURES)
    assert len({case["id"] for case in cases}) == len(cases)


def test_every_fixture_states_its_observables_and_invariants():
    for case in fixtures.fixture_cases():
        assert case["observables"]
        assert case["invariants"]
        assert "begin model" in case["source"]
        assert "end model" in case["source"]
        if case["law"] is not None:
            assert case["law"]["observable"] in case["observables"]


def test_check_identities_are_stable_and_unique():
    ids = fixtures.check_ids()
    assert len(ids) == len(set(ids))
    for case in fixtures.fixture_cases():
        assert f"{case['id']}:nf-fixtures:route" in ids
        assert f"{case['id']}:nf-fixtures:direct-xml-equality" in ids
        assert f"{case['id']}:nf-fixtures:native-distributional" in ids
        if case["law"] is None:
            assert f"{case['id']}:nf-fixtures:source-law" not in ids


def test_the_recorded_seed_budget_is_fixed_before_execution():
    assert fixtures.SEED_BASE == 17
    assert fixtures.SEED_STRIDE == 7919
    assert fixtures.ENSEMBLE_RUNS == 8
    seeds = [fixtures.seed_for(index) for index in range(fixtures.ENSEMBLE_RUNS)]
    assert len(set(seeds)) == len(seeds)
    assert seeds == sorted(seeds)
    # The seed policy is part of the recorded evidence, not a run-time choice.
    assert (
        "17 + 7919"
        in fixtures._row(fixtures.fixture_cases()[0], "route", "PASS", "detail")[
            "seed_policy"
        ]
    )


@pytest.mark.slow
def test_a_generated_fixture_runs_on_the_direct_route_and_agrees_with_the_xml_route(
    tmp_path,
):
    case = case_by("symmetry")
    rows = fixtures.run(tmp_path, runs=8, cases=[case])
    by_check = {row["check"]: row for row in rows}
    assert by_check["route"]["status"] == "PASS"
    assert by_check["direct-xml-equality"]["status"] == "PASS"
    assert by_check["source-law"]["status"] == "PASS"
    assert by_check["native-distributional"]["status"] == "NOT_TESTED"
    assert (
        by_check["native-distributional"]["applicability"]
        == "native-oracle-unavailable"
    )
    # The error control is recorded with the row, not implied by it.
    assert by_check["source-law"]["alpha"] > 0
    assert by_check["source-law"]["per_check_budget"] > 0
    assert by_check["source-law"]["ensemble_runs"] == 8


@pytest.mark.slow
def test_a_declined_fixture_is_reported_as_a_failure_and_never_as_a_pass(tmp_path):
    case = dict(case_by("symmetry"))
    # A model the direct route cannot execute must be reported, not hidden.
    case = dict(case)
    case["source"] = case["source"].replace(
        "begin reaction rules", "begin reaction rules\n  broken: A() -> B() missing"
    )
    rows = fixtures.run(tmp_path, runs=8, cases=[case])
    by_check = {row["check"]: row for row in rows}
    assert by_check["route"]["status"] == "FAIL"
    assert by_check["direct-xml-equality"]["status"] == "NOT_TESTED"
    assert by_check["source-law"]["status"] == "NOT_TESTED"


def test_a_violated_invariant_fails_the_route_check(tmp_path):
    case = case_by("deletion")
    # The catalyst must survive the deletion; a trajectory that destroys it
    # violates the fixture invariant and must not pass the route check.
    data = np.array([[0.0, 100.0, 90.0, 1.0], [1.0, 50.0, 40.0, 1.0]])
    columns = ["time", "OA", "OB", "OD"]
    failure = fixtures._invariant_failure(case, data, columns)
    assert failure is not None
    assert failure["invariant"] == "equal"
    # A trajectory that satisfies the invariants is accepted.
    good = np.array([[0.0, 100.0, 100.0, 1.0], [1.0, 50.0, 50.0, 1.0]])
    assert fixtures._invariant_failure(case, good, columns) is None


def test_the_ensemble_budget_is_bounded():
    with pytest.raises(ValueError):
        fixtures.run("/tmp/never", runs=4)
    with pytest.raises(ValueError):
        fixtures.run("/tmp/never", runs=1000)
