"""Fault injection for independent stochastic marginal detectors."""

import json
from pathlib import Path

import numpy as np
import pytest

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


def test_native_oracle_is_handed_the_count_rate_convention_for_a_compartment():
    """The oracle is handed the model the embedded engine executes.

    BNG2 divides a reactant-bearing rate constant by the reaction
    compartment's size; the pinned native NFsim applies a compartment size
    only to zero-order synthesis, so for a bimolecular rule in a compartment
    of size 3 it would sample a different model.  The harness therefore
    folds BNG2's compartment unit conversion into the rule's rate constant
    before the oracle runs, and the case is comparable again.
    """
    dimer_v3 = dict(
        law="second-order",
        family="second-order",
        initial=12,
        rate=0.4,
        volume=3,
        rate_convention="physical_source_law",
        quantity_basis="amount",
    )
    assert integrated_marginals.native_oracle_realizes_source_law(dimer_v3)
    # A compartment of size 1 needs no conversion, but stays comparable.
    assert integrated_marginals.native_oracle_realizes_source_law(
        dict(dimer_v3, volume=1)
    )
    for law in ("zero-order", "first-order"):
        assert integrated_marginals.native_oracle_realizes_source_law(
            dict(dimer_v3, law=law, volume=3)
        )
    assert integrated_marginals.native_oracle_realizes_source_law(
        dict(family="dimerization", initial=20, volume=3)
    )


def test_native_marginal_rows_say_that_the_oracle_sampled_the_model(tmp_path):
    """A native comparison that ran says so; one that could not says why."""
    from tests.validation import integrated_traces

    bionetgen = pytest.importorskip("bionetgen")

    case = next(
        item
        for item in integrated_cases.source_law_cases()
        if item["law"] == "second-order" and item["rate_convention"] == "bngl_count"
    )
    source = tmp_path / "model.bngl"
    source.write_text(integrated_cases.source_law_bngl(case))
    xml = tmp_path / "model.xml"

    bionetgen.load(str(source)).write_xml(str(xml))
    normalisation = integrated_traces.native_count_rate_xml(
        xml, tmp_path / "native-count-rate.xml"
    )
    assert normalisation["status"] == "NORMALISED"
    rule = normalisation["rules"][0]
    # BNG2's count-rate coefficient: rate constant x symmetry factor x the
    # compartment unit conversion of a compartment of size 3.
    assert rule["compartment_unit_conversion"] == pytest.approx(1 / 3)
    assert rule["count_rate_coefficient"] == pytest.approx(0.4 * 0.5 / 3)
    text = (tmp_path / "native-count-rate.xml").read_text()
    assert 'value="0.06666666666666667"' in text
    assert "symmetry_factor" not in text
    # The pinned oracle reads namespace-insensitive XML, but the artefact it
    # is handed must keep the document's own default namespace.
    assert "ns0:" not in text
    assert 'xmlns="http://www.sbml.org/sbml/level3"' in text


def test_native_rows_state_the_count_rate_convention_when_the_oracle_is_present(
    tmp_path,
):
    """A native comparison that ran says so, and reports its coefficients."""
    from tests.validation import oracle_nfsim

    bionetgen = pytest.importorskip("bionetgen")

    binary = oracle_nfsim.nfsim_binary()
    if binary is None:
        pytest.skip("native NFsim binary not available")
    case = next(
        item
        for item in integrated_cases.source_law_cases()
        if item["law"] == "second-order" and item["rate_convention"] == "bngl_count"
    )
    source = tmp_path / "model.bngl"
    source.write_text(integrated_cases.source_law_bngl(case))
    xml = tmp_path / "model.xml"

    bionetgen.load(str(source)).write_xml(str(xml))
    rows = integrated_marginals.run(
        source,
        case,
        binary,
        xml,
        tmp_path / "ensembles",
        runs=32,
        cases=6,
    )
    native = [row for row in rows if row["check"].startswith("native.")]
    assert len(native) == len(integrated_marginals.CHECKS)
    assert all(row["status"] == "PASS" for row in native)
    assert all("count-rate convention" in row["detail"] for row in native)
    rule = native[0]["oracle_count_rate_rules"][0]
    assert rule["count_rate_coefficient"] == pytest.approx(0.4 * 0.5 / 3)
    # The oracle sampled the model the embedded engine executes.
    embedded = [row for row in rows if row["check"].startswith("embedded.")]
    assert all(row["status"] == "PASS" for row in embedded)


def test_native_marginal_rows_report_the_missing_prerequisite(tmp_path):
    """The native rows are NOT_TESTED with the reason, not silently failed.

    A compartment whose size is not statically determinable states no
    count-rate coefficient, so the oracle cannot be handed an equivalent
    model; the comparison is then an explained absence, not a failure.
    """
    from tests.validation import reporting

    bionetgen = pytest.importorskip("bionetgen")

    case = next(
        item
        for item in integrated_cases.source_law_cases()
        if item["law"] == "second-order" and item["rate_convention"] == "bngl_count"
    )
    source = tmp_path / "model.bngl"
    source.write_text(integrated_cases.source_law_bngl(case))
    xml = tmp_path / "model.xml"

    bionetgen.load(str(source)).write_xml(str(xml))
    # A parameter-backed compartment size states no static conversion.
    text = xml.read_text().replace(' size="3"', "")
    xml.write_text(text)
    rows = integrated_marginals.run(
        source,
        case,
        tmp_path / "missing-native-binary",
        xml,
        tmp_path / "ensembles",
        runs=8,
        cases=1,
    )
    native = [row for row in rows if row["check"].startswith("native.")]
    embedded = [row for row in rows if row["check"].startswith("embedded.")]
    assert len(native) == len(embedded) == len(integrated_marginals.CHECKS)
    assert all(row["status"] == "NOT_TESTED" for row in native)
    assert all(
        row["applicability"] == "native-oracle-unit-conversion-unsupported"
        for row in native
    )
    assert all("compartment unit conversion" in row["detail"] for row in native)
    # The explained absence of execution is not a gating failure.
    for index, row in enumerate(native):
        row["id"] = f"case:nf-marginals:{row['check']}"
    assert reporting.gate_failures(native) == []


def test_physical_bridge_cases_cover_orders_bases_and_compartments():
    cases = integrated_cases.physical_bridge_cases()
    assert {case["law"] for case in cases} == {
        "zero-order",
        "first-order",
        "second-order",
    }
    assert {case["substance_basis"] for case in cases} == {"item", "mole"}
    assert {case["volume"] for case in cases} == {3}
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        source = integrated_cases.physical_bridge_bngl(case)
        assert "[litre]" in source
        assert 'setOption("units", "strict")' in source
        if case["substance_basis"] == "mole":
            assert "NumberPerQuantityUnit" in source
            assert "litre/mole/second" in source
        else:
            assert "NumberPerQuantityUnit" not in source
        assert "Molecules A @cell:A()" in source


def test_physical_bridge_check_ids_name_the_catalogued_obligations():
    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root / "provenance/issue-obligations.json").read_text())
    entry = next(row for row in catalog["issues"] if row["number"] == 151)
    required = {
        check["id"]
        for obligation in entry["obligations"]
        for check in obligation["required_checks"]
    }
    bridge = set(integrated_marginals.physical_bridge_check_ids())
    assert bridge <= required
    named = {
        obligation["id"]: obligation["required_checks"][0]["evidence_kind"]
        for obligation in entry["obligations"]
        if obligation["required_checks"][0]["id"] in bridge
    }
    assert len(named) == len(bridge)
    assert named["issue:151:missing-context-refusal"] == "diagnostic-only"
    assert named["issue:151:unsupported-dimension-refusal"] == "diagnostic-only"
    assert named["issue:151:double-scaling-refusal"] == "diagnostic-only"
    assert named["issue:151:amount-count-conversion"] == "supported-execution"
    ids = integrated_marginals.source_law_check_ids()
    assert bridge <= set(ids)
    assert len(ids) == len(set(ids))


def test_typed_count_rate_conversion_matches_the_independent_count_law(tmp_path):
    """The typed model reproduces the count law of the same physical reaction."""
    bionetgen = pytest.importorskip("bionetgen")

    case = next(
        item
        for item in integrated_cases.physical_bridge_cases()
        if item["law"] == "second-order" and item["substance_basis"] == "item"
    )
    source = tmp_path / "typed.bngl"
    source.write_text(integrated_cases.physical_bridge_bngl(case))
    samples = integrated_marginals._embedded_bridge_samples(case, source, tmp_path, 32)
    rows = integrated_marginals.assess_samples(samples, case, alpha=1e-6 / 12)
    assert {row["check"]: row["status"] for row in rows}["source-cdf"] == "PASS"
    final = samples[:, -1]
    mean = float(final.mean())
    standard_error = float(final.std(ddof=1) / np.sqrt(len(final)))
    assert integrated_marginals._discriminates(
        mean, standard_error, integrated_marginals._count_law_mean(case)
    )
    # The bare count-rate convention is a different law, and the detector has
    # to separate it: that is the controlled mutation of this contract.
    mutant = dict(case, rate_convention="bngl_count")
    mutant_source = tmp_path / "mutant.bngl"
    mutant_source.write_text(integrated_cases.source_law_bngl(mutant))
    mutant_samples = integrated_marginals._embedded_bridge_samples(
        case, mutant_source, tmp_path, 32
    )
    mutant_rows = integrated_marginals.assess_samples(
        mutant_samples, case, alpha=1e-6 / 12
    )
    assert {row["check"]: row["status"] for row in mutant_rows}["source-cdf"] == "FAIL"
    mutant_final = mutant_samples[:, -1]
    mutant_mean = float(mutant_final.mean())
    mutant_error = float(mutant_final.std(ddof=1) / np.sqrt(len(mutant_final)))
    assert integrated_marginals._separates(
        mutant_mean, mutant_error, integrated_marginals._count_law_mean(case)
    )
    assert not integrated_marginals._discriminates(
        mutant_mean, mutant_error, integrated_marginals._count_law_mean(case)
    )


def test_typed_bridge_refuses_a_missing_context_and_an_unsupported_dimension(
    tmp_path,
):
    bionetgen = pytest.importorskip("bionetgen")

    cases = integrated_cases.physical_bridge_refusal_cases()
    assert {case["refusal"] for case in cases} == {
        "missing-context",
        "unsupported-dimension",
    }
    for case in cases:
        source = tmp_path / f"{case['id']}.bngl"
        source.write_text(integrated_cases.physical_bridge_refusal_bngl(case))
        assert "[litre]" in source.read_text()
        with pytest.raises(Exception) as exc:
            bionetgen.load(str(source)).simulate(
                method="nf", t_end=2, n_steps=10, seed=17
            )
        assert "physical-unit" in str(exc.value), str(exc.value)
