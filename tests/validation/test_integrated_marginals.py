"""Fault injection for independent stochastic marginal detectors."""

import numpy as np

from tests.validation import integrated_cases, integrated_marginals


def case():
    return next(
        c for c in integrated_cases.generated_cases() if c["family"] == "reversible"
    )


def test_source_binomial_mass_is_normalized_including_boundary_probabilities():
    for probability in (0, 0.01, 0.5, 0.99, 1):
        mass = integrated_marginals.binomial_mass(80, probability)
        assert np.isclose(mass.sum(), 1)
        assert np.isclose(np.dot(np.arange(81), mass), 80 * probability)


def test_correct_marginals_pass_but_wrong_rates_and_shared_seed_do_not():
    model = case()
    expected, names = integrated_cases.expected_trajectory(model)
    probability = expected[:, names.index("A")] / model["initial"]
    samples = np.random.default_rng(817).binomial(
        model["initial"], probability, size=(128, len(probability))
    )
    rows = integrated_marginals.assess_samples(samples, model, alpha=1e-6)
    assert all(r["status"] == "PASS" for r in rows)
    shared = np.repeat(samples[:1], len(samples), axis=0)
    rows = integrated_marginals.assess_samples(shared, model, alpha=1e-6)
    assert next(r for r in rows if r["check"] == "seed-spread")["status"] == "FAIL"
    wrong = samples.copy()
    wrong[:, -1] = model["initial"]
    rows = integrated_marginals.assess_samples(wrong, model, alpha=1e-6)
    assert next(r for r in rows if r["check"] == "marginal-means")["status"] == "FAIL"


def test_missing_nonfinite_fractional_or_out_of_range_samples_cannot_qualify():
    model = case()
    for samples in (
        np.zeros((0, 11)),
        np.full((32, 11), np.nan),
        np.full((32, 11), 0.5),
        np.full((32, 11), model["initial"] + 1),
    ):
        rows = integrated_marginals.assess_samples(samples, model)
        assert rows[0]["check"] == "sample-validity"
        assert rows[0]["status"] != "PASS"
        assert not any(r["status"] == "PASS" for r in rows)
