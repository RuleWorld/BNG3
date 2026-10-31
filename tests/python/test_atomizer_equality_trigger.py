"""An SBML equality trigger is refused explicitly unless it is an exact gate.

A continuous quantity equals a value only at isolated instants.  The order
resolvers schedule the crossing of an inequality; an equality has no such
crossing they can represent (it can also fire again at a later crossing or at
a tangential touch), so they must not claim it.  ``_COMPARISON_ALIASES``
contained ``eq`` although its comment excluded it, which had two effects:

* ``eq(0.5, S1)`` reached ``_REVERSED_COMPARISON_OPERATOR["eq"]`` and the
  import failed with the bare error ``'eq'``;
* ``eq(S1, 0.5)`` was reported as a fixed-time event lowered to scheduled
  actions, but no action was emitted, so the event was silently lost.

Equality remains supported where it is exact: as a gate inside a conjunction
whose other conjunct supplies the continuous crossing, which the native
runtime evaluates after every event assignment.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.events import (
    _parse_affine_state_threshold,
    _parse_state_difference_threshold,
)

TIME = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>'
)


def _math(body: str) -> str:
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML">{body}</math>'


def _event(identifier: str, trigger: str, variable: str, value: str) -> str:
    return (
        f'<event id="{identifier}" useValuesFromTriggerTime="true">'
        '<trigger initialValue="true" persistent="true">'
        f"{_math(trigger)}</trigger><listOfEventAssignments>"
        f'<eventAssignment variable="{variable}">{_math(value)}'
        "</eventAssignment></listOfEventAssignments></event>"
    )


def _model(events: str, law: str = "<apply><times/><ci>p</ci><ci>S1</ci></apply>"):
    return (
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
        'level="3" version="1"><model id="m" timeUnits="time">'
        '<listOfCompartments><compartment id="C" size="1" constant="true"/>'
        "</listOfCompartments><listOfSpecies>"
        '<species id="S1" compartment="C" initialAmount="1" '
        'hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>'
        '<species id="S2" compartment="C" initialAmount="0" '
        'hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>'
        "</listOfSpecies><listOfParameters>"
        '<parameter id="p" value="1" constant="false"/>'
        '<parameter id="g" value="1" constant="false"/>'
        "</listOfParameters><listOfReactions>"
        '<reaction id="r" reversible="false" fast="false"><listOfReactants>'
        '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
        "</listOfReactants><listOfProducts>"
        '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
        f"</listOfProducts><kineticLaw>{_math(law)}</kineticLaw></reaction>"
        f"</listOfReactions><listOfEvents>{events}</listOfEvents></model></sbml>"
    )


def _convert(source: str):
    return Atomizer(atomize=False, quiet_mode=True, t_end=3, n_steps=6).atomize(source)


def _assert_refused_explicitly(result) -> None:
    assert result.success, result.error
    bngl = result.bngl
    assert "begin bng3_events" not in bngl
    assert "setConcentration(" not in bngl
    assert "lowered to scheduled BNGL actions" not in bngl
    assert "remain untranslated" in bngl


def test_reversed_equality_trigger_is_refused_instead_of_failing_the_import():
    trigger = "<apply><eq/><cn>0.5</cn><ci>S1</ci></apply>"
    _assert_refused_explicitly(
        _convert(_model(_event("E1", trigger, "S2", "<cn>0</cn>")))
    )


def test_equality_trigger_is_not_reported_as_a_scheduled_event():
    # S1 = e^-t reaches 0.5 at t = ln 2, which the order resolver can schedule
    # for lt(S1, 0.5); for eq(S1, 0.5) it used to claim a schedule it never
    # emitted.
    trigger = "<apply><eq/><ci>S1</ci><cn>0.5</cn></apply>"
    _assert_refused_explicitly(
        _convert(_model(_event("E1", trigger, "S2", "<cn>0</cn>")))
    )


def test_equality_gate_inside_a_conjunction_still_reaches_the_native_runtime():
    # g changes only when E2 fires, so g == 1 is an exact gate and S1 < 0.5
    # supplies the crossing.  The nonlinear law keeps the analytic scheduler
    # out, so the event takes the native route.
    gated = (
        "<apply><and/><apply><lt/><ci>S1</ci><cn>0.5</cn></apply>"
        "<apply><eq/><ci>g</ci><cn>1</cn></apply></apply>"
    )
    events = _event("E1", gated, "S2", "<cn>0</cn>") + _event(
        "E2",
        f"<apply><geq/>{TIME}<cn>2</cn></apply>",
        "g",
        "<apply><minus/><ci>g</ci><cn>1</cn></apply>",
    )
    law = "<apply><times/><ci>p</ci><ci>S1</ci><ci>S1</ci><ci>S2</ci></apply>"
    result = _convert(_model(events, law))
    assert result.success, result.error
    assert "trigger: (S1_amt < 0.5) && (g_amt == 1)" in result.bngl


def test_order_resolvers_reject_equality_in_either_argument_order():
    for trigger in ("eq(S4, 3)", "eq(3, S4)", "neq(3, S4)", "eq(S4, S3)"):
        assert _parse_affine_state_threshold(trigger) is None, trigger
        assert _parse_state_difference_threshold(trigger) is None, trigger
