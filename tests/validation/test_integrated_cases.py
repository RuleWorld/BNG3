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
        family: [case for case in full if case["family"] == family]
        for family in ("decay", "reversible", "dimerization")
    }

    assert {case["id"] for case in by_family["decay"]} == {
        f"v{volume}-n{initial}-r{int(reverse)}-a{int(atomize)}"
        for volume in (1, 3)
        for initial in (20, 80)
        for reverse in (False, True)
        for atomize in (False, True)
    }
    assert len(full) == 48
    assert len(selected) == 18
    assert len({case["id"] for case in full}) == len(full)
    for family, family_cases in by_family.items():
        picked = [case for case in selected if case["family"] == family]
        assert len(family_cases) == 16
        assert len(picked) == 6
        for left, right in combinations(FACTORS, 2):
            assert {(c[left], c[right]) for c in picked} == {
                (c[left], c[right]) for c in family_cases
            }
        assert all(
            case["exact_nf"] is (family != "reversible") for case in family_cases
        )
    assert all(
        "ensemble means" in case["nf_comparison"] for case in by_family["reversible"]
    )


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
            assert species.attrib["hasOnlySubstanceUnits"] == "true"
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
