"""Regression tests for a rate-ruled species-reference stoichiometry.

SBML Level 3 Version 2 Core Sec. 4.11.3 gives a ``speciesReference`` id the
meaning of a model-level symbol whose value is that reference's
stoichiometry, and Sec. 4.11.7 ("Mathematical interpretation of SBML
reactions and kinetic laws") states that the species' *amount* changes by

    d n_Si / dt = c_Si * sum_j stoich_ij(t) * v_Rj

where ``v_Rj`` is the reaction's extent rate and ``c_Si`` is the species'
conversion factor (or the model's).  A ``rateRule`` on the stoichiometry
symbol makes ``stoich_ij`` a function of time, so the reaction's
contribution to the species is time-dependent.

The time-zero value of that symbol is the reference's ``stoichiometry``
attribute unless an initial assignment defines the same symbol, in which
case Sec. 4.11.3 says the attribute is ignored.  The Atomizer has to carry
that value into the state variable that carries the symbol; a state variable
that starts at the default 0 is a different model.

The official SBML Test Suite cases ``01103``, ``01637``, ``01718``,
``01727``, ``01728``, ``01729``, ``01736``, ``01737``, ``01738`` and
``01742`` (``testTags: AssignedVariableStoichiometry``) are the reference for
the expected trajectories.
"""

from __future__ import annotations

import math

import pytest

from _extdep import require_extension

_cpp = require_extension()

from bionetgen.atomizer.modern import Atomizer  # noqa: E402


def _rate_ruled_stoichiometry_model(
    *,
    species: str,
    rules: str,
    products: str = "",
    reactants: str = "",
    law: str = "<cn>0.1</cn>",
    parameters: str = "",
    initial_assignments: str = "",
    model_attributes: str = "",
) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="variable_stoichiometry" {model_attributes}>
        <listOfCompartments>
          <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species}</listOfSpecies>
        <listOfParameters>{parameters}</listOfParameters>
        <listOfInitialAssignments>{initial_assignments}</listOfInitialAssignments>
        <listOfRules>{rules}</listOfRules>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="false">
            <listOfReactants>{reactants}</listOfReactants>
            <listOfProducts>{products}</listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">{law}</math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""


def _simulate(bngl: str, t_end: float, n_steps: int) -> dict[str, list[float]]:
    model = _cpp.parse_string(bngl)
    network = _cpp.generate_network(model, max_iter=100)
    raw = _cpp.simulate_ode(
        model,
        network,
        t_end=t_end,
        n_steps=n_steps,
        t_start=0.0,
        rtol=1e-9,
        atol=1e-14,
    )
    return {
        name: [float(value) for value in values]
        for name, values in raw["observables"].items()
    }


def _atomize(sbml: str):
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(sbml)
    assert result.success, result.error
    return atomizer, result


def test_rate_ruled_stoichiometry_seeds_the_attribute_value():
    """The state that carries the stoichiometry starts at the attribute value."""

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    assert "@C:M___rate_rule_state__S1_stoich() 1" in result.bngl, result.bngl
    # The reaction's rate reads the stoichiometry state, not a constant.
    assert "S1_stoich_amt" in result.bngl, result.bngl


def test_rate_ruled_stoichiometry_reproduces_the_official_trajectory():
    """S1's amount follows ``integral of stoichiometry(t) * extent rate``.

    This is the shape of the official suite case ``01718``: the
    stoichiometry symbol starts at 1 and grows at 1/s, the extent rate is
    0.1, so ``n_S1(t) = 0.1 * (t + t**2 / 2)``.  The official reference
    trajectory for ``01718`` is exactly that.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    amounts = observables["S1_amt"]
    for index, amount in enumerate(amounts):
        time = float(index)
        expected = 0.1 * (time + time * time / 2.0)
        assert math.isclose(amount, expected, rel_tol=1e-6, abs_tol=1e-8), (
            index,
            amount,
            expected,
        )


def test_rate_ruled_stoichiometry_applies_conversion_factors():
    """The conversion factor scales the species' amount rate.

    This is the shape of the official suite case ``01727``: a model-level
    conversion factor of 3, a species-level factor of 5 on S1, and two
    rate-ruled stoichiometry symbols that both start at 1 and grow at
    0.01/s.  ``dn_S1/dt = 5 * (-(1 + 0.01 t)) * 0.01`` and
    ``dn_S2/dt = 3 * (+(1 + 0.01 t)) * 0.01``.
    """

    sbml = _rate_ruled_stoichiometry_model(
        model_attributes='conversionFactor="m_cf"',
        species=(
            '<species id="S1" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false" conversionFactor="s1_cf"/>'
            '<species id="S2" compartment="C" initialAmount="3" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        parameters=(
            '<parameter id="m_cf" value="3" constant="true"/>'
            '<parameter id="s1_cf" value="5" constant="true"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S2_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.01</cn></math>'
            "</rateRule>"
        ),
        reactants=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
        products=(
            '<speciesReference id="S2_stoich" species="S2" stoichiometry="1" '
            'constant="false"/>'
        ),
        law="<cn>0.01</cn>",
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    for index in range(11):
        time = float(index)
        integral = time + 0.005 * time * time
        assert math.isclose(
            observables["S1_amt"][index],
            2.0 - 5.0 * 0.01 * integral,
            rel_tol=1e-6,
            abs_tol=1e-8,
        ), index
        assert math.isclose(
            observables["S2_amt"][index],
            3.0 + 3.0 * 0.01 * integral,
            rel_tol=1e-6,
            abs_tol=1e-8,
        ), index


def test_initial_assignment_overrides_the_stoichiometry_attribute():
    """Sec. 4.11.3: the attribute is ignored once an initial assignment wins.

    The stoichiometry symbol starts at 2 (the initial assignment) and grows
    at 1/s, so the species' amount is ``integral of (2 + t) * 1``.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="1" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        initial_assignments=(
            '<initialAssignment symbol="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>'
            "</initialAssignment>"
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="7" '
            'constant="false"/>'
        ),
        law="<cn>1</cn>",
    )
    _atomizer, result = _atomize(sbml)

    assert "@C:M___rate_rule_state__S1_stoich() 2" in result.bngl, result.bngl
    observables = _simulate(result.bngl, t_end=4.0, n_steps=4)
    for index, amount in enumerate(observables["S1_amt"]):
        time = float(index)
        expected = 1.0 + 2.0 * time + 0.5 * time * time
        assert math.isclose(amount, expected, rel_tol=1e-6, abs_tol=1e-8), (
            index,
            amount,
            expected,
        )


def test_rate_ruled_stoichiometry_coupled_to_the_species():
    """A stoichiometry rule that reads the species is a coupled ODE.

    ``d(stoich)/dt = [S1]`` and ``dn_S1/dt = stoich(t) * 0.1`` give
    ``n_S1'' = 0.1 * n_S1`` with ``n_S1(0) = 1`` and ``n_S1'(0) = 0.1``,
    whose solution is checked here.  The lowering has to reproduce the
    coupling, not just the stoichiometry's own trajectory.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="1" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><ci> S1 </ci></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    root = math.sqrt(0.1)
    growing = (1.0 + 0.1 / root) / 2.0
    decaying = (1.0 - 0.1 / root) / 2.0
    for index, amount in enumerate(observables["S1_amt"]):
        time = float(index)
        expected = growing * math.exp(root * time) + decaying * math.exp(
            -root * time
        )
        assert math.isclose(amount, expected, rel_tol=1e-6, abs_tol=1e-8), (
            index,
            amount,
            expected,
        )


def test_rate_ruled_stoichiometry_without_an_initial_value_is_reported():
    """A stoichiometry symbol with no time-zero value must not be seeded 0."""

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" constant="false"/>'
        ),
    )
    atomizer, _result = _atomize(sbml)

    assert any(
        warning["category"] == "stoichiometry"
        and warning["severity"] == "dropped"
        and "S1_stoich" in warning["message"]
        for warning in atomizer.model.import_warnings
    ), atomizer.model.import_warnings


@pytest.mark.parametrize(
    "case_id",
    ["01103", "01637", "01718", "01727", "01728", "01729", "01736", "01737", "01738", "01742"],
)
def test_official_suite_cases_match_their_reference_trajectories(case_id):
    """The official suite cases reproduce their published trajectories.

    The suite checkout is not part of this repository, so the case is
    skipped when it is unavailable rather than silently passing.
    """

    import csv
    import os

    suite = os.environ.get("SBML_TEST_SUITE_DIR", "/tmp/bng3-ssts-20261016")
    case_dir = os.path.join(suite, "cases", "semantic", case_id)
    xml_path = os.path.join(case_dir, f"{case_id}-sbml-l3v1.xml")
    if not os.path.isfile(xml_path):
        xml_path = os.path.join(case_dir, f"{case_id}-sbml-l3v2.xml")
    if not os.path.isfile(xml_path):
        pytest.skip(f"SBML Test Suite case {case_id} is not available")

    settings = {}
    with open(os.path.join(case_dir, f"{case_id}-settings.txt")) as handle:
        for line in handle:
            if ":" in line:
                key, value = line.split(":", 1)
                settings[key.strip()] = value.strip()
    duration = float(settings["duration"])
    steps = int(settings["steps"])
    amounts = [
        name.strip()
        for name in settings.get("amount", "").split(",")
        if name.strip()
    ]

    with open(xml_path) as handle:
        atomizer, result = _atomize(handle.read())
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings

    observables = _simulate(result.bngl, t_end=duration, n_steps=steps)
    with open(os.path.join(case_dir, f"{case_id}-results.csv")) as handle:
        rows = list(csv.DictReader(handle))
    for name in amounts:
        expected = [float(row[name]) for row in rows]
        actual = observables[f"{name}_amt"]
        assert len(actual) == len(expected), (name, len(actual), len(expected))
        for index, (want, got) in enumerate(zip(expected, actual)):
            tolerance = 1e-4 + 1e-4 * abs(want)
            assert abs(got - want) <= tolerance, (name, index, got, want)
