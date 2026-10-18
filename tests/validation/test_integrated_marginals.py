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


def test_dimer_count_law_matches_two_molecule_waiting_time():
    from tests.validation.integrated_marginals import source_marginal_mass

    model = dict(family="dimerization", initial=2, volume=3)
    mass = source_marginal_mass(model)
    survival = np.exp(-2 * integrated_cases.RATE * integrated_cases.TIMES / 3)
    assert mass.shape == (11, 3)
    np.testing.assert_allclose(mass[:, 2], survival, atol=1e-14)
    np.testing.assert_allclose(mass[:, 0], 1 - survival, atol=1e-14)
    assert np.array_equal(mass[:, 1], np.zeros(11))


def test_dimer_mass_preserves_parity_and_rejects_wrong_kinetics():
    from tests.validation.integrated_marginals import source_marginal_mass

    model = dict(family="dimerization", initial=21, volume=3)
    mass = source_marginal_mass(model)
    np.testing.assert_allclose(mass.sum(axis=1), 1, atol=1e-13)
    assert np.all(mass >= 0)
    assert np.array_equal(mass[:, ::2], np.zeros((11, 11)))
    rng = np.random.default_rng(919)
    samples = np.column_stack([rng.choice(22, size=256, p=row) for row in mass])
    assert all(
        r["status"] == "PASS"
        for r in integrated_marginals.assess_samples(samples, model)
    )
    samples[:, -1] = 21
    assert any(
        r["status"] == "FAIL"
        for r in integrated_marginals.assess_samples(samples, model)
    )
