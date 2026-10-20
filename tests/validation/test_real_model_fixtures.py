"""Fault controls for the real-model fixture qualification (#152).

The fixtures are real models of the canonical NFsim source.  These tests
inject the faults that would make their comparison meaningless: a fixture
that no longer matches its source, a broken conservation law, a trajectory
that does not follow the analytic law, and a fixture the engine refuses.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from tests.validation import integrated_extensions as extensions
from tests.validation import real_model_fixtures as fixtures


def _fixture(fixture_id):
    return next(
        fixture for fixture in fixtures.fixtures() if fixture["id"] == fixture_id
    )


def test_every_named_family_is_present_with_a_source_link():
    fixtures_ = fixtures.fixtures()
    assert {fixture["family"] for fixture in fixtures_} == set(fixtures.FAMILIES)
    for fixture in fixtures_:
        assert fixture["source"]["repository"]
        assert len(fixture["source"]["revision"]) == 40
        assert fixture["source"]["path"]
        assert fixture["sha256"]
        assert fixture["invariants"]
        assert fixture["path"].is_file()


def test_the_vendored_fixtures_match_their_recorded_source():
    for fixture in fixtures.fixtures():
        assert fixtures._digest(fixture["path"]) == fixture["sha256"]


def test_the_source_link_is_verified_against_the_upstream_checkout_when_named(
    monkeypatch,
):
    source = fixtures._sources()
    revision = source["source"]["revision"]
    assert len(revision) == 40
    upstream, detail = fixtures._upstream_digest(
        dict(repository="x", revision=revision, path="does/not/exist.bngl")
    )
    assert upstream is None
    assert "no upstream NFsim checkout" in detail or "does not exist" in detail
    monkeypatch.setenv("BNG3_NFSIM_SOURCE", "/nonexistent/nfsim")
    upstream, detail = fixtures._upstream_digest(
        dict(repository="x", revision=revision, path="does/not/exist.bngl")
    )
    assert upstream is None
    assert "does not exist" in detail


def test_every_fixture_declares_an_independent_expectation():
    for fixture in fixtures.fixtures():
        for invariant in fixture["invariants"]:
            assert invariant["terms"]
            assert invariant["value"] is not None or invariant["at_most"] is not None
        if fixture["law"] is not None:
            assert fixture["law"]["reason"]


def test_the_motor_law_is_the_exact_two_state_chain():
    fixture = _fixture("motor-motor")
    times = np.asarray([0.0, 0.5, 1.0])
    law = fixtures._thinning_law(fixture, times)
    expected = 8200 * 3.5 / 13.5 * (1.0 - np.exp(-13.5 * times))
    np.testing.assert_allclose(law, expected, rtol=1e-12)
    assert law[0] == 0.0


def test_the_tqssa_steady_state_solves_the_declared_equations():
    fixture = _fixture("tqssa-gk-simple")
    law = fixtures._steady_state_law(fixture)
    assert law["residual"] < 1e-6
    # The substrate is conserved: the free and the bound forms together are
    # the declared 900 molecules.
    assert law["S"] + law["Sp"] == pytest.approx(900.0, rel=1e-6)


def test_a_trajectory_that_breaks_a_conservation_law_is_refused():
    fixture = copy.deepcopy(_fixture("tqssa-gk-simple"))
    times = np.asarray([0.0, 1.0])
    series = {"S": np.asarray([0.0, 10.0]), "Sp": np.asarray([900.0, 880.0])}
    rows = {row["check"]: row for row in fixtures._assess(fixture, times, series)}
    assert rows["invariant"]["status"] == "FAIL"
    assert "substrate" in rows["invariant"]["first_difference"]["failed"]


def test_a_trajectory_that_breaks_the_analytic_law_is_refused():
    fixture = copy.deepcopy(_fixture("motor-motor"))
    times = np.asarray([0.0, 0.5, 1.0])
    series = {
        "CheYp": np.asarray([0.0, 100.0, 2125.0]),
        "MotCW": np.asarray([10.0, 5.0, 5.0]),
        "MotCCW": np.asarray([0.0, 5.0, 5.0]),
    }
    rows = {row["check"]: row for row in fixtures._assess(fixture, times, series)}
    assert rows["closed-form-law"]["status"] == "FAIL"
    assert rows["closed-form-law"]["first_difference"]["worst_relative_error"] > 0


def test_a_refused_fixture_is_recorded_and_not_skipped():
    fixture = copy.deepcopy(_fixture("motor-motor"))
    rows = fixtures._refusal(fixture, "the engine refused the model")
    assert rows
    for row in rows:
        assert row["status"] == "UNSUPPORTED"
        assert row["supported_execution"] is False
        assert "the engine refused the model" in row["detail"]
        assert row["id"].startswith(f"real-model-fixtures:{fixture['id']}:")


def test_the_qualified_slice_is_declared():
    ids = fixtures.check_ids()
    assert len(ids) == len(set(ids))
    assert "campaign:real-model-fixtures" not in ids
    for fixture in fixtures.fixtures():
        assert f"real-model-fixtures:{fixture['id']}:source-link" in ids
        assert f"real-model-fixtures:{fixture['id']}:invariant" in ids
    assert f"qualification:issue:152:{fixtures.OBLIGATION_CHECK}" in ids
    assert set(ids) <= set(extensions.expected_ids([]))


def test_the_operation_is_registered_in_the_campaign_registry():
    assert "real-model-fixtures" in extensions.OPERATIONS
    assert extensions.check_ids("real-model-fixtures") == fixtures.check_ids()
