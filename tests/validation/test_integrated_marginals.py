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


def test_source_law_cases_cover_orders_conventions_and_parameter_backed_volume():
    cases = integrated_cases.source_law_cases()
    assert len(cases) == 6
    assert {case["law"] for case in cases} == {
        "zero-order",
        "first-order",
        "second-order",
    }
    assert {case["rate_convention"] for case in cases} == {
        "physical_source_law",
        "bngl_count",
    }
    assert {case["volume"] for case in cases} == {3}
    for case in cases:
        source = integrated_cases.source_law_bngl(case)
        assert "V 3" in source
        assert "cell 3 V" in source
        assert "Molecules A @cell:A()" in source
    concentration = next(
        case for case in cases if case["quantity_basis"] == "concentration"
    )
    assert concentration["initial_coordinate_value"] == 40 / 3
    assert "initialConcentration=" in integrated_cases.source_law_bngl(concentration)


def test_source_laws_separate_physical_units_from_bare_count_conventions():
    from tests.validation.integrated_marginals import source_marginal_mass

    zero_physical = dict(
        law="zero-order",
        initial=0,
        rate=0.4,
        volume=3,
        rate_convention="physical_source_law",
        quantity_basis="amount",
    )
    zero_bare = dict(zero_physical, rate_convention="bngl_count")
    physical = source_marginal_mass(zero_physical)
    bare = source_marginal_mass(zero_bare)
    assert np.allclose(physical.sum(axis=1), 1, atol=1e-14)
    assert np.allclose(bare.sum(axis=1), 1, atol=1e-14)
    assert np.allclose(physical.sum(axis=1), 1, atol=1e-14)
    assert np.allclose(bare.sum(axis=1), 1, atol=1e-14)
    assert np.isclose(np.dot(np.arange(physical.shape[1]), physical[-1]), 0.8)
    assert np.isclose(np.dot(np.arange(bare.shape[1]), bare[-1]), 2.4)

    dimer_physical = dict(
        law="second-order",
        family="second-order",
        initial=2,
        rate=0.4,
        volume=3,
        rate_convention="physical_source_law",
        quantity_basis="amount",
    )
    dimer_bare = dict(dimer_physical, rate_convention="bngl_count")
    physical_mass = source_marginal_mass(dimer_physical)
    bare_mass = source_marginal_mass(dimer_bare)
    assert np.isclose(physical_mass[-1, 2], np.exp(-2 * 0.4 * 2 / 3))
    assert np.isclose(bare_mass[-1, 2], np.exp(-0.4 * 2 / 3))


def test_source_law_detector_rejects_wrong_rate_and_concentration_is_amount_scaled():
    model = dict(
        law="first-order",
        family="first-order",
        initial=40,
        rate=0.4,
        volume=3,
        rate_convention="physical_source_law",
        quantity_basis="concentration",
    )
    expected = integrated_marginals.source_marginal_mass(model)
    rng = np.random.default_rng(3107)
    samples = np.column_stack(
        [rng.choice(41, size=512, p=probability) for probability in expected]
    )
    assert all(
        r["status"] == "PASS"
        for r in integrated_marginals.assess_samples(samples, model)
    )
    wrong_model = dict(model, rate=0.04)
    assert any(
        row["status"] == "FAIL"
        for row in integrated_marginals.assess_samples(samples, wrong_model)
    )


def test_poisson_source_cdf_tail_does_not_treat_support_overflow_as_unit_error():
    model = dict(
        law="zero-order",
        family="zero-order",
        initial=0,
        rate=0.4,
        volume=3,
        rate_convention="physical_source_law",
        quantity_basis="amount",
    )
    mass = integrated_marginals.source_marginal_mass(model)
    rng = np.random.default_rng(771)
    samples = np.column_stack([rng.choice(len(row), size=512, p=row) for row in mass])
    samples[0, -1] = mass.shape[1] + 1
    cdf = next(
        row
        for row in integrated_marginals.assess_samples(samples, model)
        if row["check"] == "source-cdf"
    )
    assert cdf["status"] == "PASS"
