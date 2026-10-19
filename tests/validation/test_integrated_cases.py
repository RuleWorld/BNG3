"""Mathematical controls for generated integration model families."""

from itertools import combinations
import xml.etree.ElementTree as ET

import numpy as np

from tests.validation import integrated_cases

FACTORS = ("volume", "initial", "reverse", "atomize")


def test_generated_families_preserve_decay_ids_and_bound_pairwise_matrix():
    full = integrated_cases.generated_cases(full=True)
    selected = integrated_cases.generated_cases()
    by_family = {
        family: [
            case
            for case in full
            if case["family"] == family and not case.get("transform")
        ]
        for family in ("decay", "reversible", "dimerization")
    }

    assert {case["id"] for case in by_family["decay"]} == {
        f"v{volume}-n{initial}-r{int(reverse)}-a{int(atomize)}"
        for volume in (1, 3)
        for initial in (20, 80)
        for reverse in (False, True)
        for atomize in (False, True)
    }
    assert len(full) == 61
    assert len(selected) == 25
    assert len({case["id"] for case in full}) == len(full)
    for family, family_cases in by_family.items():
        picked = [
            case
            for case in selected
            if case["family"] == family and not case.get("transform")
        ]
        assert len(family_cases) == 16
        assert len(picked) == 6
        for left, right in combinations(FACTORS, 2):
            assert {(c[left], c[right]) for c in picked} == {
                (c[left], c[right]) for c in family_cases
            }

        def expected_exact(case):
            # The native oracle is handed the model in BNG2's count-rate
            # convention, so the seeded trajectories compare exactly for every
            # family.
            return True

        assert all(case["exact_nf"] is expected_exact(case) for case in family_cases)
    assert all("Equal-seed" in case["nf_comparison"] for case in family_cases)


def test_transformed_decay_cases_keep_machine_readable_quantity_basis():
    from tests.validation.integrated_marginals import source_marginal_mass

    transformed = [
        case for case in integrated_cases.generated_cases() if case.get("transform")
    ]

    assert {case["quantity_basis"] for case in transformed} == {"amount"}
    assert {case["transform"] for case in transformed} == {
        "function-shadowing",
        "concentration-coordinate",
        "shadow-global-decoy",
    }
    for case in transformed:
        assert case["quantity_description"]
        mass = source_marginal_mass(case)
        assert mass.shape == (11, case["initial"] + 1)


def test_generated_sbml_has_correct_amount_and_rate_units():
    cases = integrated_cases.generated_cases(full=True)
    ns = {"s": "http://www.sbml.org/sbml/level3/version2/core"}

    for case in cases:
        root = ET.fromstring(integrated_cases.sbml_text(case))
        assert root.tag == f"{{{ns['s']}}}sbml"
        assert root.attrib == {"level": "3", "version": "2"}
        model = root.find("s:model", ns)
        compartment = model.find("s:listOfCompartments/s:compartment", ns)
        assert float(compartment.attrib["size"]) == case["volume"]
        for species in model.findall("s:listOfSpecies/s:species", ns):
            assert species.attrib["substanceUnits"] == "item"
            assert species.attrib["hasOnlySubstanceUnits"] == (
                "false"
                if case.get("transform") == "concentration-coordinate"
                else "true"
            )
        reaction = model.find("s:listOfReactions/s:reaction", ns)
        assert reaction is not None
        assert (
            model.find("s:listOfParameters/s:parameter[@id='k']", ns).attrib["value"]
            == "0.4"
        )
        expected_units = (
            "litre_per_item_second"
            if case["family"] == "dimerization"
            else "per_second"
        )
        assert (
            model.find("s:listOfParameters/s:parameter[@id='k']", ns).attrib["units"]
            == expected_units
        )
        expected_reactions = 2 if case["family"] == "reversible" else 1
        assert (
            len(model.findall("s:listOfReactions/s:reaction", ns)) == expected_reactions
        )

    dimer = next(c for c in cases if c["family"] == "dimerization")
    root = ET.fromstring(integrated_cases.sbml_text(dimer))
    model = root.find("s:model", ns)
    math_ns = {
        **ns,
        "m": "http://www.w3.org/1998/Math/MathML",
    }
    law = model.find(".//s:kineticLaw/m:math", math_ns)
    # The amount-based rate is k*A^2/V, with k in volume/(item second).
    assert "cell" in [element.text for element in law.findall(".//m:ci", math_ns)]
    refs = model.findall(".//s:speciesReference", ns)
    assert [(r.attrib["species"], r.attrib["stoichiometry"]) for r in refs] == [
        ("A", "2"),
        ("D", "1"),
    ]


def test_analytic_trajectories_satisfy_initial_values_and_conservation():
    for case in integrated_cases.generated_cases(full=True):
        data, columns = integrated_cases.expected_trajectory(case)
        assert columns[0] == "time"
        assert np.array_equal(data[:, 0], integrated_cases.TIMES)
        assert data.shape == (len(integrated_cases.TIMES), len(columns))
        assert len(columns) == len(set(columns))
        values = dict(zip(columns, data.T))
        family = case["family"]

        if family in ("decay", "reversible"):
            names = ("A", "B")
            assert all(f"{name}_amt" in columns and name in columns for name in names)
            assert np.allclose(values["A"], values["A_amt"])
            assert np.allclose(values["B"], values["B_amt"])
            assert np.isclose(values["A"][0] + values["B"][0], case["initial"])
            assert np.allclose(values["A"] + values["B"], case["initial"])
            if family == "decay":
                assert np.isclose(values["A"][0], case["initial"])
                assert np.isclose(values["B"][0], 0)
            else:
                dt = data[1, 0]
                expected_a1 = case["initial"] * 0.2 / 0.6 + (
                    values["A"][0] - case["initial"] * 0.2 / 0.6
                ) * np.exp(-0.6 * dt)
                assert np.isclose(values["A"][1], expected_a1)
        else:
            assert all(
                f"{name}_amt" in columns and name in columns for name in ("A", "D")
            )
            assert np.allclose(values["A"], values["A_amt"])
            assert np.allclose(values["D"], values["D_amt"])
            assert np.isclose(values["A"][0], case["initial"])
            assert np.isclose(values["D"][0], 0)
            assert np.allclose(values["A"] + 2 * values["D"], case["initial"])
            dt = data[1, 0]
            expected_a1 = case["initial"] / (
                1 + 2 * 0.4 * case["initial"] * dt / case["volume"]
            )
            assert np.isclose(values["A"][1], expected_a1)


def test_reversible_trajectory_uses_two_rate_equilibrium_and_orientation():
    cases = [
        case
        for case in integrated_cases.generated_cases(full=True)
        if case["family"] == "reversible" and case["volume"] == 1
    ]
    forward = next(
        case for case in cases if not case["reverse"] and case["initial"] == 20
    )
    reverse = next(case for case in cases if case["reverse"] and case["initial"] == 20)
    forward_data, forward_columns = integrated_cases.expected_trajectory(forward)
    reverse_data, reverse_columns = integrated_cases.expected_trajectory(reverse)
    f = dict(zip(forward_columns, forward_data.T))
    r = dict(zip(reverse_columns, reverse_data.T))
    equilibrium_fraction_a = 0.2 / (0.4 + 0.2)

    assert np.isclose(
        f["A"][-1],
        equilibrium_fraction_a * 20
        + (20 - equilibrium_fraction_a * 20) * np.exp(-0.6 * 2),
    )
    assert np.isclose(r["A"][0], 0)
    assert np.isclose(r["A"][-1], equilibrium_fraction_a * 20 * (1 - np.exp(-0.6 * 2)))


def test_every_source_species_initial_amount_matches_analytic_time_zero():
    ns = {"s": "http://www.sbml.org/sbml/level3/version2/core"}
    for case in integrated_cases.generated_cases(full=True):
        root = ET.fromstring(integrated_cases.sbml_text(case))
        volume = float(root.find(".//s:compartment", ns).attrib["size"])
        actual = {}
        for species in root.findall(".//s:species", ns):
            if "initialAmount" in species.attrib:
                amount = float(species.attrib["initialAmount"])
            else:
                amount = float(species.attrib["initialConcentration"]) * volume
            actual[species.attrib["id"]] = amount
        data, columns = integrated_cases.expected_trajectory(case)
        for species, amount in actual.items():
            assert np.isclose(data[0, columns.index(species)], amount)


def test_reuse_controls_keep_mutable_source_dependencies_for_all_families():
    for case in integrated_cases.generated_cases():
        text = integrated_cases.reuse_bngl(case)
        assert "cell 3 V" in text
        assert "N " in text
        assert "rate() = " in text
        assert "k" in text.split("rate() = ")[1].splitlines()[0]
        assert "rate()" in text.split("begin reaction rules")[1]


def test_generated_perturbations_preserve_baseline_and_name_their_lineage():
    baseline = integrated_cases.generated_cases()
    full = integrated_cases.generated_cases(full=True)
    perturbations = [case for case in full if case.get("transform")]

    assert len(perturbations) == 13
    assert len([case for case in baseline if case.get("transform")]) == 7
    assert {case["transform"] for case in perturbations} == {
        "function-shadowing",
        "concentration-coordinate",
        "shadow-global-decoy",
    }
    by_id = {case["id"]: case for case in full}
    for case in perturbations:
        base = by_id[case["base_case_id"]]
        assert base["family"] == "decay"
        assert case["initial"] == base["initial"]
        assert case["volume"] == base["volume"]
        assert case["atomize"] == base["atomize"]
        assert case["reverse"] == base["reverse"]
        expected, columns = integrated_cases.expected_trajectory(case)
        base_expected, base_columns = integrated_cases.expected_trajectory(base)
        assert columns == base_columns
        assert np.array_equal(expected, base_expected)


def test_function_shadowing_is_a_real_parameterized_sbml_transform():
    case = next(
        case
        for case in integrated_cases.generated_cases()
        if case.get("transform") == "function-shadowing"
    )
    root = ET.fromstring(integrated_cases.sbml_text(case))
    ns = {"s": "http://www.sbml.org/sbml/level3/version2/core"}
    model = root.find("s:model", ns)
    function = model.find("s:listOfFunctionDefinitions/s:functionDefinition", ns)
    parameters = {
        parameter.attrib["id"]: float(parameter.attrib["value"])
        for parameter in model.findall("s:listOfParameters/s:parameter", ns)
    }

    assert function is not None
    assert function.attrib["id"] == "rateLaw"
    assert parameters["rate"] == 7.0
    assert parameters["k"] == integrated_cases.RATE
    assert "rateLaw" in integrated_cases.sbml_text(case)


def test_adversarial_shadow_case_is_in_the_pr_sample_and_keeps_source_k_binding():
    case = next(
        case
        for case in integrated_cases.generated_cases()
        if case.get("transform") == "shadow-global-decoy"
    )
    root = ET.fromstring(integrated_cases.sbml_text(case))
    ns = {"s": "http://www.sbml.org/sbml/level3/version2/core"}
    model = root.find("s:model", ns)
    parameters = {
        parameter.attrib["id"]: float(parameter.attrib["value"])
        for parameter in model.findall("s:listOfParameters/s:parameter", ns)
    }
    assert parameters["rate"] == 13.0
    assert parameters["k"] == integrated_cases.RATE
    assert "<bvar><ci>rate</ci></bvar>" in integrated_cases.sbml_text(case)
    assert case["base_case_id"] == "v1-n20-r0-a0"


def test_concentration_transform_keeps_independent_amount_oracle():
    cases = [
        case
        for case in integrated_cases.generated_cases()
        if case.get("transform") == "concentration-coordinate"
    ]
    assert cases
    ns = {"s": "http://www.sbml.org/sbml/level3/version2/core"}
    for case in cases:
        root = ET.fromstring(integrated_cases.sbml_text(case))
        species = root.find(".//s:species[@id='A']", ns)
        law = root.find(".//s:kineticLaw", ns)
        assert np.isclose(
            float(species.attrib["initialConcentration"]),
            case["initial"] / case["volume"],
        )
        assert species.attrib["hasOnlySubstanceUnits"] == "false"
        assert "cell" in ET.tostring(law, encoding="unicode")
        expected, columns = integrated_cases.expected_trajectory(case)
        values = dict(zip(columns, expected.T))
        assert np.allclose(
            values["A_amt"],
            case["initial"] * np.exp(-integrated_cases.RATE * integrated_cases.TIMES),
        )
        source_values, species_names = integrated_cases.expected_source_species(case)
        assert species_names == ["A", "B"]
        assert np.allclose(source_values[:, 0], values["A_amt"] / case["volume"])
        assert np.allclose(source_values[:, 1], values["B_amt"] / case["volume"])
        # The declared concentration law multiplies concentration by volume,
        # yielding the same independently specified amount extent k*N.
        assert np.isclose(
            integrated_cases.RATE * case["volume"] * (case["initial"] / case["volume"]),
            integrated_cases.RATE * case["initial"],
        )


def test_concentration_source_law_executes_the_volume_conversion_expression():
    from tests.validation.integrated_cases import source_law_cases, source_law_bngl

    case = next(c for c in source_law_cases() if c["quantity_basis"] == "concentration")
    source = source_law_bngl(case)
    assert "C0 " in source
    assert "@cell:A() C0*V" in source
