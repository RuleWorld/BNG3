"""Fault controls for the stochastic-parity qualification (#167).

The qualification compares the stochastic backends with an independent count
law.  These tests inject the faults that would make such a comparison
meaningless: a law that does not describe the model, a law that is compared
against the product's own output, a run budget that silently changes, and a
case that the backend cannot execute.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tests.validation import integrated_extensions as extensions
from tests.validation import stochastic_parity


def _case(case_id):
    return next(case for case in stochastic_parity.cases() if case["id"] == case_id)


def test_every_generated_case_declares_an_independent_law_and_a_decoy():
    cases = stochastic_parity.cases()
    assert cases
    assert len({case["id"] for case in cases}) == len(cases)
    conventions = {case["convention"] for case in cases}
    assert {
        "local-function",
        "local-function-state",
        "builtin",
        "tfun",
        "special-rate-saturation",
        "special-rate-hill",
        "elementary-bimolecular",
    } <= conventions
    for case in cases:
        assert case["law"]["kind"] in ("binomial-thinning", "pure-death")
        assert case["decoy"]["kind"] in ("binomial-thinning", "pure-death")
        assert case["decoy_reason"]
        assert "Acount" in case["text"]
        assert "begin reaction rules" in case["text"]


def test_thinning_law_is_the_exact_binomial_of_the_declared_rate():
    law = stochastic_parity._thinning_law(20, 0.4)
    masses = stochastic_parity._law_masses(law, (0.0, 1.0, 2.0))
    means = stochastic_parity._law_mean(law, (0.0, 1.0, 2.0), masses)
    np.testing.assert_allclose(masses.sum(axis=1), 1.0, atol=1e-12)
    np.testing.assert_allclose(means, 20 * np.exp(-0.4 * np.array([0.0, 1.0, 2.0])))
    assert math.isclose(masses[0][20], 1.0, abs_tol=1e-12)


def test_pure_death_law_is_the_exact_generator_exponential():
    law = stochastic_parity._death_law(20, ("saturation", 0.4, 10.0))
    masses = stochastic_parity._law_masses(law, (0.0, 1.0, 2.0))
    means = stochastic_parity._law_mean(law, (0.0, 1.0, 2.0), masses)
    np.testing.assert_allclose(masses.sum(axis=1), 1.0, atol=1e-12)
    assert np.all(masses >= 0)
    # The first firing rate at the initial population is the declared hazard.
    survival = masses[1][20] / masses[0][20]
    assert math.isclose(-math.log(survival), 0.4 * 20 / 30.0, rel_tol=1e-9)
    assert 0 < means[2] <= means[1] <= means[0]


def test_bimolecular_law_keeps_the_statistical_factor_of_identical_reactants():
    law = stochastic_parity._death_law(20, ("elementary-bimolecular", 0.4), step=2)
    masses = stochastic_parity._law_masses(law, (1.0,))
    # The first firing rate is k*C(n,2) and the count only moves in steps of two.
    survival = masses[0][20]
    assert math.isclose(-math.log(survival), 0.4 * 190, rel_tol=1e-9)
    assert np.all(masses[0][1::2] == 0)


def test_exact_test_rejects_a_law_the_ensemble_does_not_follow():
    case = _case("parameter-n20-k04")
    masses = stochastic_parity._law_masses(case["law"], stochastic_parity.TIMES)
    means = stochastic_parity._law_mean(case["law"], stochastic_parity.TIMES, masses)
    runs = 32
    # An ensemble that never fires is not the declared thinning law.
    stuck = np.full((runs, len(stochastic_parity.TIMES)), 20.0)
    rows = stochastic_parity._assess(case, "ssa", stuck, masses, means, runs, 1e-6)
    by_check = {row["check"]: row for row in rows}
    assert by_check["mean-refinement"]["status"] == "FAIL"
    assert by_check["sample-validity"]["status"] == "PASS"


def test_an_ensemble_that_follows_the_decoy_cannot_be_separated_from_it():
    case = _case("parameter-n20-k04")
    masses = stochastic_parity._law_masses(case["law"], stochastic_parity.TIMES)
    means = stochastic_parity._law_mean(case["law"], stochastic_parity.TIMES, masses)
    decoy_masses = stochastic_parity._law_masses(case["decoy"], stochastic_parity.TIMES)
    rng = np.random.default_rng(31337)
    runs = 256
    samples = np.column_stack(
        [rng.choice(21, size=runs, p=row) for row in decoy_masses]
    ).astype(float)
    rows = stochastic_parity._assess(case, "ssa", samples, masses, means, runs, 1e-6)
    by_check = {row["check"]: row for row in rows}
    # The doubled rate is a different law, so the refinement statement fails and
    # the ensemble cannot be separated from the declared misreading.
    assert by_check["mean-refinement"]["status"] == "FAIL"
    assert by_check["convention-separation"]["status"] == "FAIL"


def test_exact_test_accepts_an_ensemble_drawn_from_the_declared_law():
    case = _case("parameter-n20-k04")
    masses = stochastic_parity._law_masses(case["law"], stochastic_parity.TIMES)
    rng = np.random.default_rng(2024)
    samples = np.column_stack(
        [rng.choice(21, size=256, p=row) for row in masses]
    ).astype(float)
    rows = stochastic_parity._assess(
        case,
        "ssa",
        samples,
        masses,
        stochastic_parity._law_mean(case["law"], stochastic_parity.TIMES, masses),
        256,
        1e-6,
    )
    by_check = {row["check"]: row for row in rows}
    assert by_check["mean-refinement"]["status"] == "PASS"
    assert by_check["law-cdf"]["status"] == "PASS"
    assert by_check["convention-separation"]["status"] == "PASS"
    assert (
        by_check["mean-refinement"]["worst_exact_pvalue"]
        > by_check["mean-refinement"]["per_timepoint_budget"]
    )


def test_malformed_ensembles_never_qualify():
    case = _case("parameter-n20-k04")
    masses = stochastic_parity._law_masses(case["law"], stochastic_parity.TIMES)
    means = stochastic_parity._law_mean(case["law"], stochastic_parity.TIMES, masses)
    for samples in (
        np.zeros((0, len(stochastic_parity.TIMES))),
        np.full((32, len(stochastic_parity.TIMES)), np.nan),
        np.full((32, len(stochastic_parity.TIMES)), 0.5),
        np.full((32, len(stochastic_parity.TIMES)), 21.0),
    ):
        rows = stochastic_parity._assess(case, "ssa", samples, masses, means, 32, 1e-6)
        assert not any(row["status"] == "PASS" for row in rows)


def test_the_run_budget_and_the_seed_policy_are_fixed_and_recorded():
    assert stochastic_parity.RUNS == 64
    assert stochastic_parity.SEED_BASE == 17
    assert stochastic_parity.SEED_STRIDE == 7919
    plan = stochastic_parity._plan(stochastic_parity.cases(), 64, 1e-6)
    assert plan["ensemble_runs"] == 64
    assert plan["seed_policy"] == stochastic_parity.SEED_POLICY
    assert plan["alpha"] == 1e-6
    assert plan["qualified_slice"] == stochastic_parity.SLICE
    assert "never the product's own output" in plan["independent_expectation"]


def test_the_declared_check_identities_are_unique_and_named():
    ids = stochastic_parity.check_ids()
    assert len(ids) == len(set(ids))
    assert "campaign:stochastic-parity" not in ids
    for name in stochastic_parity.OBLIGATION_CHECKS:
        assert f"qualification:issue:167:{name}" in ids
    assert set(ids) <= set(extensions.expected_ids([]))


def test_an_unexecutable_case_is_refused_instead_of_being_scored():
    case = dict(_case("parameter-n20-k04"))
    case["id"] = "refused-case"
    masses = stochastic_parity._law_masses(case["law"], stochastic_parity.TIMES)
    means = stochastic_parity._law_mean(case["law"], stochastic_parity.TIMES, masses)
    # A backend that refuses the model leaves no sample to compare.
    rows = stochastic_parity._assess(
        case, "nf", np.zeros((0, 11)), masses, means, 64, 1e-6
    )
    assert not any(row["status"] == "PASS" for row in rows)
    assert {row["status"] for row in rows} == {"FAIL", "NOT_TESTED"}


def test_the_operation_is_registered_in_the_campaign_registry():
    assert "stochastic-parity" in extensions.OPERATIONS
    assert extensions.check_ids("stochastic-parity") == stochastic_parity.check_ids()
