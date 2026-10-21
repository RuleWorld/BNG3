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

The expected trajectories here are computed analytically rather than read
from the official SBML Test Suite, so that this file never depends on an
external checkout.  Every case mirrors the shape of one official suite case
with ``testTags: AssignedVariableStoichiometry`` and states which one in its
docstring; the official suite itself is exercised by
``scripts/ci/validate_sbml_test_suite.py`` in the ``sbml-conformance``
workflow.

With a rate rule ``d(stoich)/dt = r`` on a reference id whose attribute is
1, the symbol is ``stoich(t) = 1 + r t``.  A reaction with a constant
extent rate ``v`` and a species conversion factor ``c`` therefore gives

    n(t) = n(0) + c * v * (t + r t**2 / 2)

which is the formula the trajectory checks below use.
"""

from __future__ import annotations

import math

from _extdep import require_extension

_cpp = require_extension()

from bionetgen.atomizer.modern import Atomizer  # noqa: E402

_MATHML = "http://www.w3.org/1998/Math/MathML"


def _rate_ruled_stoichiometry_model(
    *,
    species: str,
    rules: str = "",
    products: str = "",
    reactants: str = "",
    law: str = "<cn>0.1</cn>",
    parameters: str = "",
    initial_assignments: str = "",
    functions: str = "",
    events: str = "",
    local_parameters: str = "",
    model_attributes: str = "",
) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="variable_stoichiometry" {model_attributes}>
        <listOfFunctionDefinitions>{functions}</listOfFunctionDefinitions>
        <listOfCompartments>
          <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species}</listOfSpecies>
        <listOfParameters>{parameters}</listOfParameters>
        <listOfInitialAssignments>{initial_assignments}</listOfInitialAssignments>
        <listOfRules>{rules}</listOfRules>
        <listOfEvents>{events}</listOfEvents>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="false">
            <listOfReactants>{reactants}</listOfReactants>
            <listOfProducts>{products}</listOfProducts>
            <kineticLaw>
              <math xmlns="{_MATHML}">{law}</math>
              <listOfLocalParameters>{local_parameters}</listOfLocalParameters>
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


def _assert_trajectory(
    observables: dict[str, list[float]],
    name: str,
    expected,
) -> None:
    """Compare one observable against an analytic value at every output point."""

    amounts = observables[f"{name}_amt"]
    for index, amount in enumerate(amounts):
        want = expected(float(index))
        assert math.isclose(amount, want, rel_tol=1e-6, abs_tol=1e-8), (
            name,
            index,
            amount,
            want,
        )


def _linear_stoichiometry_amount(
    initial: float,
    rate: float,
    extent_rate: float,
    factor: float = 1.0,
    sign: float = 1.0,
):
    """Amount of a species whose stoichiometry grows at ``rate``.

    ``sign`` is ``-1`` for a reactant and ``+1`` for a product, and
    ``factor`` is the species' conversion factor.
    """

    def amount(time: float) -> float:
        integral = time + rate * time * time / 2.0
        return initial + sign * factor * extent_rate * integral

    return amount


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
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    # The reaction's rate reads the stoichiometry state, not a constant.
    assert "S1_stoich_amt" in result.bngl, result.bngl

    # The state that carries the stoichiometry starts at the attribute value.
    observables = _simulate(result.bngl, t_end=0.0, n_steps=1)
    assert math.isclose(observables["S1_stoich_amt"][0], 1.0, rel_tol=1e-12), (
        observables["S1_stoich_amt"],
    )


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
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(0.0, 1.0, 0.1),
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
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S2_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
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
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 0.01, 0.01, factor=5.0, sign=-1.0),
    )
    _assert_trajectory(
        observables,
        "S2",
        _linear_stoichiometry_amount(3.0, 0.01, 0.01, factor=3.0),
    )


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
            f'<math xmlns="{_MATHML}"><cn>2</cn></math>'
            "</initialAssignment>"
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="7" '
            'constant="false"/>'
        ),
        law="<cn>1</cn>",
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=0.0, n_steps=1)
    assert math.isclose(observables["S1_stoich_amt"][0], 2.0, rel_tol=1e-12), (
        observables["S1_stoich_amt"],
    )

    observables = _simulate(result.bngl, t_end=4.0, n_steps=4)
    _assert_trajectory(
        observables,
        "S1",
        lambda time: 1.0 + 2.0 * time + 0.5 * time * time,
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
            f'<math xmlns="{_MATHML}"><ci> S1 </ci></math>'
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
        expected = growing * math.exp(root * time) + decaying * math.exp(-root * time)
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
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=('<speciesReference id="S1_stoich" species="S1" constant="false"/>'),
    )
    atomizer, _result = _atomize(sbml)

    assert any(
        warning["category"] == "stoichiometry"
        and warning["severity"] == "dropped"
        and "S1_stoich" in warning["message"]
        for warning in atomizer.model.import_warnings
    ), atomizer.model.import_warnings


def test_unresolvable_initial_assignment_names_the_initial_assignment():
    """The reason must not claim that the source model supplies neither.

    A model whose initial assignment for the stoichiometry symbol cannot be
    resolved to a number at t=0 does supply an initial assignment, so the
    diagnostic has to say that instead of claiming that the source model
    supplies neither an attribute nor an initial assignment.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        parameters='<parameter id="p" constant="false"/>',
        initial_assignments=(
            '<initialAssignment symbol="S1_stoich">'
            f'<math xmlns="{_MATHML}"><ci> p </ci></math>'
            "</initialAssignment>"
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="3" '
            'constant="false"/>'
        ),
    )
    atomizer, _result = _atomize(sbml)

    messages = [
        warning["message"]
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ]
    assert len(messages) == 1, atomizer.model.import_warnings
    message = messages[0]
    assert "S1_stoich" in message, message
    assert "supplies neither" not in message, message
    assert "initial assignment" in message, message
    assert "could not be resolved to a number at t=0" in message, message


def test_missing_stoichiometry_attribute_reports_that_neither_is_supplied():
    """With no attribute and no initial assignment the reason is unchanged."""

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=('<speciesReference id="S1_stoich" species="S1" constant="false"/>'),
    )
    atomizer, _result = _atomize(sbml)

    messages = [
        warning["message"]
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ]
    assert len(messages) == 1, atomizer.model.import_warnings
    assert "supplies neither" in messages[0], messages[0]


def test_unresolvable_assignment_rule_names_the_assignment_rule():
    """A rule that targets the reference id is the source, and says so.

    Sec. 4.11.3 lets a ``speciesReference`` id be the target of a ``Rule``,
    so an assignment rule is a third source of the symbol's value alongside
    the ``stoichiometry`` attribute and an initial assignment.  When the
    rule's value cannot be resolved to a number at t=0, the reason has to
    name the rule; claiming that the source model supplies neither an
    attribute nor an initial assignment is true here, but it leaves the
    reader without the construct that actually governs the value.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="1" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<assignmentRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><ci> q </ci></math>'
            "</assignmentRule>"
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=('<speciesReference id="S1_stoich" species="S1" constant="false"/>'),
    )
    atomizer, _result = _atomize(sbml)

    messages = [
        warning["message"]
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ]
    assert len(messages) == 1, atomizer.model.import_warnings
    message = messages[0]
    assert "S1_stoich" in message, message
    assert "assignment rule" in message, message
    assert "could not be resolved to a number at t=0" in message, message


def test_mathml_builtin_initial_assignment_is_resolved_and_raises_no_diagnostic():
    """A resolvable initial assignment must not be called unresolvable.

    The static evaluator folds the MathML built-ins, so an initial
    assignment whose expression is a built-in *is* resolvable to a number at
    t=0.  The diagnostic must not fire for it: a message that says the value
    "could not be resolved" about a value the Atomizer has already resolved
    would be lying, and the verdict would be wrong too.  The official suite
    cases ``01516`` and ``01561`` assign their species-reference
    stoichiometries exactly this way.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="1" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        initial_assignments=(
            '<initialAssignment symbol="S1_stoich">'
            f'<math xmlns="{_MATHML}">'
            '<apply><abs/><cn type="integer">-1</cn></apply></math>'
            "</initialAssignment>"
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="3" '
            'constant="false"/>'
        ),
    )
    atomizer, result = _atomize(sbml)

    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings

    # The initial assignment's value wins over the attribute's 3 (Sec. 4.11.3),
    # and ``abs(-1)`` is 1.
    observables = _simulate(result.bngl, t_end=0.0, n_steps=1)
    assert math.isclose(observables["S1_stoich_amt"][0], 1.0, rel_tol=1e-12), (
        observables["S1_stoich_amt"],
    )


def test_assignment_rule_overrides_the_stoichiometry_attribute():
    """Sec. 4.11.3: a rule that targets the reference id wins.

    The species reference's ``id`` "may be the target of an
    InitialAssignment, EventAssignment, or Rule object" (Sec. 4.11.3), and
    the initial conditions order (Sec. "Initial conditions and special
    considerations") puts assignment rules after the attribute's initial
    value, so the rule's value is the one that counts.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="1" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<assignmentRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>4</cn></math>'
            "</assignmentRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="9" '
            'constant="false"/>'
        ),
    )
    atomizer, result = _atomize(sbml)

    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings

    # The rule's value 4 replaces the attribute's 9, so the species gains
    # 4 * 0.1 per time unit instead of 9 * 0.1.
    observables = _simulate(result.bngl, t_end=2.0, n_steps=2)
    _assert_trajectory(
        observables,
        "S1",
        lambda time: 1.0 + 4.0 * 0.1 * time,
    )


def test_initial_assignment_supplies_a_missing_stoichiometry_attribute():
    """A reference without the attribute takes the initial assignment's value.

    Sec. 4.11.3: "A missing stoichiometry implies that the stoichiometry is
    either unknown, or to be obtained from an external source, or determined
    by an initial assignment".  The assignment's value is therefore used and
    no diagnostic is raised.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="1" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        initial_assignments=(
            '<initialAssignment symbol="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>3</cn></math>'
            "</initialAssignment>"
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        products=('<speciesReference id="S1_stoich" species="S1" constant="false"/>'),
    )
    atomizer, result = _atomize(sbml)

    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings

    observables = _simulate(result.bngl, t_end=0.0, n_steps=1)
    assert math.isclose(observables["S1_stoich_amt"][0], 3.0, rel_tol=1e-12), (
        observables["S1_stoich_amt"],
    )


# ---------------------------------------------------------------------------
# The official suite shapes.  Each case below mirrors one official suite
# case with ``testTags: AssignedVariableStoichiometry``; the expected
# trajectory is the analytic one, not a value read from the suite.
# ---------------------------------------------------------------------------


def test_official_shape_01103_nonconstant_rate_parameter():
    """Official suite case ``01103``.

    The extent rate is a non-constant parameter with a fixed value of 1 and
    the reference id grows at 0.01/s from its attribute value 1, so
    ``n_X(t) = t + 0.005 t**2``.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="X" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        parameters='<parameter id="k1" value="1" constant="false"/>',
        rules=(
            '<rateRule variable="Xref">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="Xref" species="X" stoichiometry="1" '
            'constant="false"/>'
        ),
        law="<ci> k1 </ci>",
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "X",
        _linear_stoichiometry_amount(0.0, 0.01, 1.0),
    )


def test_official_shape_01637_local_parameter_shadows_the_reference_id():
    """Official suite case ``01637``.

    The reaction's kinetic law is ``1 / k0`` and the reaction carries a
    local parameter ``k0`` with value 3.  The local parameter shadows the
    model-level symbol in the kinetic law, while the reaction's
    stoichiometry is the model-level ``k0(t) = 1 + t``, so
    ``n_S1(t) = 2 + (t + t**2 / 2) / 3``.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="k0">'
            f'<math xmlns="{_MATHML}"><cn type="integer">1</cn></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="k0" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
        law=('<apply><divide/><cn type="integer">1</cn><ci> k0 </ci></apply>'),
        local_parameters='<localParameter id="k0" value="3"/>',
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 1.0, 1.0 / 3.0),
    )


def test_official_shape_01718_reference_id_in_an_event_trigger():
    """Official suite case ``01718``.

    The reference id also appears in a MathML expression: the event's
    trigger reads it.  The event is orthogonal to the species' amount (the
    official case notes state that the event never executes), so the
    stoichiometry trajectory is still ``0.1 * (t + t**2 / 2)``.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialConcentration="0" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        parameters='<parameter id="P1" value="0" constant="false"/>',
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>1</cn></math>'
            "</rateRule>"
        ),
        events=(
            '<event id="E1" useValuesFromTriggerTime="true">'
            '<trigger initialValue="true" persistent="false">'
            f'<math xmlns="{_MATHML}">'
            "<apply><and/>"
            "<apply><geq/><ci> S1_stoich </ci><cn>2.3</cn></apply>"
            "<apply><leq/><ci> S1_stoich </ci><cn>3.3</cn></apply>"
            "</apply></math></trigger>"
            f'<delay><math xmlns="{_MATHML}"><cn type="integer">2</cn></math></delay>'
            "<listOfEventAssignments>"
            '<eventAssignment variable="P1">'
            f'<math xmlns="{_MATHML}"><cn type="integer">3</cn></math>'
            "</eventAssignment>"
            "</listOfEventAssignments></event>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(0.0, 1.0, 0.1),
    )


def test_official_shape_01742_function_defined_stoichiometry_rate():
    """Official suite case ``01742``.

    The rate rule's formula is a function definition that returns 1.5, so
    ``stoich(t) = 1 + 1.5 t`` and ``n_S1(t) = 2 + 0.1 t + 0.075 t**2``.
    """

    sbml = _rate_ruled_stoichiometry_model(
        functions=(
            '<functionDefinition id="getOnePointFive">'
            f'<math xmlns="{_MATHML}"><lambda><cn>1.5</cn></lambda></math>'
            "</functionDefinition>"
        ),
        species=(
            '<species id="S1" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><apply><ci> getOnePointFive </ci></apply></math>'
            "</rateRule>"
        ),
        products=(
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 1.5, 0.1),
    )


def test_official_shape_01729_model_conversion_factor():
    """Official suite case ``01729``.

    A model-level conversion factor of 3 and two rate-ruled stoichiometry
    symbols that grow at 0.01/s, with an extent rate of 0.01.
    """

    sbml = _rate_ruled_stoichiometry_model(
        model_attributes='conversionFactor="m_cf"',
        species=(
            '<species id="S1" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
            '<species id="S2" compartment="C" initialAmount="3" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        parameters='<parameter id="m_cf" value="3" constant="true"/>',
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S2_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
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
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 0.01, 0.01, factor=3.0, sign=-1.0),
    )
    _assert_trajectory(
        observables,
        "S2",
        _linear_stoichiometry_amount(3.0, 0.01, 0.01, factor=3.0),
    )


def test_official_shape_01728_species_conversion_factor():
    """Official suite case ``01728``.

    A species-level conversion factor of 5 on S1 and no model-level one, so
    S1's amount changes at ``5`` times the extent rate and S2's at ``1``
    times it.
    """

    sbml = _rate_ruled_stoichiometry_model(
        species=(
            '<species id="S1" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false" conversionFactor="s1_cf"/>'
            '<species id="S2" compartment="C" initialAmount="3" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
        ),
        parameters='<parameter id="s1_cf" value="5" constant="true"/>',
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S2_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
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
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 0.01, 0.01, factor=5.0, sign=-1.0),
    )
    _assert_trajectory(
        observables,
        "S2",
        _linear_stoichiometry_amount(3.0, 0.01, 0.01),
    )


def _four_species_model(
    *,
    model_attributes: str,
    parameters: str,
    species_conversion_factor: bool,
) -> str:
    """The four-species shape of the official cases ``01736``-``01738``.

    ``S3`` and ``S4`` are boundary species, so their amounts are constant
    even though the reaction consumes ``S3`` and produces ``S4``.
    """

    species_cf = ' conversionFactor="s1_cf"' if species_conversion_factor else ""
    return _rate_ruled_stoichiometry_model(
        model_attributes=model_attributes,
        species=(
            '<species id="S1" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            f'constant="false"{species_cf}/>'
            '<species id="S2" compartment="C" initialAmount="3" '
            'hasOnlySubstanceUnits="false" boundaryCondition="false" '
            'constant="false"/>'
            '<species id="S3" compartment="C" initialAmount="2" '
            'hasOnlySubstanceUnits="false" boundaryCondition="true" '
            f'constant="false"{species_cf}/>'
            '<species id="S4" compartment="C" initialAmount="3" '
            'hasOnlySubstanceUnits="false" boundaryCondition="true" '
            'constant="false"/>'
        ),
        parameters=parameters,
        rules=(
            '<rateRule variable="S1_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S2_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S3_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
            '<rateRule variable="S4_stoich">'
            f'<math xmlns="{_MATHML}"><cn>0.01</cn></math>'
            "</rateRule>"
        ),
        reactants=(
            '<speciesReference id="S3_stoich" species="S3" stoichiometry="1" '
            'constant="false"/>'
            '<speciesReference id="S1_stoich" species="S1" stoichiometry="1" '
            'constant="false"/>'
        ),
        products=(
            '<speciesReference id="S2_stoich" species="S2" stoichiometry="1" '
            'constant="false"/>'
            '<speciesReference id="S4_stoich" species="S4" stoichiometry="1" '
            'constant="false"/>'
        ),
        law="<cn>0.01</cn>",
    )


def test_official_shape_01738_boundary_species_with_model_conversion_factor():
    """Official suite case ``01738``.

    The model-level conversion factor of 3 applies, the boundary species
    ``S3`` and ``S4`` keep their amounts, and ``S1`` and ``S2`` follow the
    two-species trajectories.
    """

    sbml = _four_species_model(
        model_attributes='conversionFactor="m_cf"',
        parameters='<parameter id="m_cf" value="3" constant="true"/>',
        species_conversion_factor=False,
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 0.01, 0.01, factor=3.0, sign=-1.0),
    )
    _assert_trajectory(
        observables,
        "S2",
        _linear_stoichiometry_amount(3.0, 0.01, 0.01, factor=3.0),
    )
    _assert_trajectory(observables, "S3", lambda time: 2.0)
    _assert_trajectory(observables, "S4", lambda time: 3.0)


def test_official_shape_01737_boundary_species_with_species_conversion_factor():
    """Official suite case ``01737``.

    The species-level conversion factor of 5 applies to ``S1`` and
    ``S3``; the boundary species keep their amounts.
    """

    sbml = _four_species_model(
        model_attributes="",
        parameters='<parameter id="s1_cf" value="5" constant="true"/>',
        species_conversion_factor=True,
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 0.01, 0.01, factor=5.0, sign=-1.0),
    )
    _assert_trajectory(
        observables,
        "S2",
        _linear_stoichiometry_amount(3.0, 0.01, 0.01),
    )
    _assert_trajectory(observables, "S3", lambda time: 2.0)
    _assert_trajectory(observables, "S4", lambda time: 3.0)


def test_official_shape_01736_boundary_species_with_both_conversion_factors():
    """Official suite case ``01736``.

    The model-level conversion factor of 3 and the species-level one of 5
    both apply; the boundary species keep their amounts.
    """

    sbml = _four_species_model(
        model_attributes='conversionFactor="m_cf"',
        parameters=(
            '<parameter id="m_cf" value="3" constant="true"/>'
            '<parameter id="s1_cf" value="5" constant="true"/>'
        ),
        species_conversion_factor=True,
    )
    _atomizer, result = _atomize(sbml)

    observables = _simulate(result.bngl, t_end=10.0, n_steps=10)
    _assert_trajectory(
        observables,
        "S1",
        _linear_stoichiometry_amount(2.0, 0.01, 0.01, factor=5.0, sign=-1.0),
    )
    _assert_trajectory(
        observables,
        "S2",
        _linear_stoichiometry_amount(3.0, 0.01, 0.01, factor=3.0),
    )
    _assert_trajectory(observables, "S3", lambda time: 2.0)
    _assert_trajectory(observables, "S4", lambda time: 3.0)
