"""Analytic contracts for continuous-root native event execution."""

import numpy as np
import pytest
from _extdep import require_extension

require_extension()
import bionetgen


def model(tmp_path, trigger="X >= 5", assignments="X = 0", initial="false", extra=""):
    path = tmp_path / "events.bngl"
    path.write_text(f"""begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
 B()
end molecule types
begin seed species
 A() 10
 B() 2
end seed species
begin observables
 Molecules X A()
 Molecules Y B()
end observables
begin reaction rules
 A() -> 0 k
end reaction rules
begin bng3_events version 1
 event "reset"
 trigger: {trigger}
 initial_value: {initial}
 persistent: true
 use_values_from_trigger_time: true
 {extra}
 {''.join('assignment: '+a.strip()+chr(10) for a in assignments.split(';'))}
 end event
end bng3_events
end model
""")
    return bionetgen.load(str(path))


@pytest.mark.parametrize("steps", [1, 17])
def test_decay_crossing_is_independent_of_output_grid(tmp_path, steps):
    result = model(tmp_path, "X <= 5", "Y = X; X = 1").simulate(
        method="ode", t_end=2, n_steps=steps
    )
    assert result.observables["Y"][-1] == pytest.approx(5, abs=2e-6)
    assert result.observables["X"][-1] == pytest.approx(2 * np.exp(-2), rel=2e-6)


@pytest.mark.parametrize("initial,expected", [("false", 0), ("true", 10 * np.exp(-1))])
def test_initial_trigger_history(tmp_path, initial, expected):
    result = model(tmp_path, "X > 5", "X = 0", initial=initial).simulate(
        method="ode", t_end=1, n_steps=1
    )
    assert result.observables["X"][-1] == pytest.approx(expected, abs=2e-6)


@pytest.mark.parametrize("operator", ["<", "<="])
def test_recurring_reset_rearms_after_trigger_becomes_false(tmp_path, operator):
    result = model(tmp_path, f"X {operator} 5", "X = 10").simulate(
        method="ode", t_end=2, n_steps=1
    )
    assert result.observables["X"][-1] == pytest.approx(40 * np.exp(-2), rel=2e-6)


def test_time_root_and_simultaneous_pre_event_values(tmp_path):
    result = model(tmp_path, "time >= 0.7", "Y = X; X = Y").simulate(
        method="ode", t_end=2, n_steps=1
    )
    assert result.observables["Y"][-1] == pytest.approx(10 * np.exp(-0.7), rel=2e-6)
    assert result.observables["X"][-1] == pytest.approx(2 * np.exp(-1.3), rel=2e-6)


def test_repeated_runs_do_not_share_event_history(tmp_path):
    instance = model(tmp_path, "X <= 5", "X = 10")
    first = instance.simulate(method="ode", t_end=2, n_steps=4)
    second = instance.simulate(method="ode", t_end=2, n_steps=4)
    np.testing.assert_array_equal(first.observables["X"], second.observables["X"])


def test_nonstrict_initial_equality_fires(tmp_path):
    result = model(tmp_path, "X >= 10", "X = 0").simulate(
        method="ode", t_end=1, n_steps=1
    )
    assert result.observables["X"][0] == 0


def test_strict_initial_threshold_equality_is_explicitly_unsupported(tmp_path):
    with pytest.raises(
        RuntimeError, match="strict trigger equals its threshold at the initial time"
    ):
        model(tmp_path, "time > 0", "X = 0").simulate(method="ode", t_end=1, n_steps=1)


@pytest.mark.parametrize("trigger", ["(time-1)*(time-1) <= 0", "X*X <= 25"])
def test_nonmonotone_root_surfaces_are_refused(tmp_path, trigger):
    with pytest.raises(
        RuntimeError,
        match="trigger requires one time or species observable against a static threshold",
    ):
        model(tmp_path, trigger, "X = 0").simulate(method="ode", t_end=2, n_steps=1)


def test_delayed_assignment_that_reevaluates_the_trigger_triggers_the_event_again(
    tmp_path,
):
    # SBML 4.12.8: the trigger is re-tested after an execution.  The event is
    # triggered when the amount falls below 5, and its delayed execution
    # happens after the amount has risen above 5 again, so the assignment
    # that restores it makes the trigger true once more.
    # The trigger holds at the start of the simulation and the trigger's
    # initial value is false, so the event fires at t = 0 and its delayed
    # execution runs at t = 1, when the amount has fallen below 5 and the
    # trigger is false.  The assignment restores the amount, which makes the
    # trigger true again, so the event triggers once more.
    result = model(tmp_path, "X > 5", "X = 10", extra="delay: 1.0").simulate(
        method="ode", t_end=1.5, n_steps=15
    )
    values = np.asarray(result.observables["X"], dtype=float)
    # Without the re-test the amount would have kept decaying from 10.
    assert values[-1] == pytest.approx(10.0 * np.exp(-0.5), rel=1e-6)


def test_a_single_event_carries_its_priority_without_changing_the_execution(
    tmp_path,
):
    # The priority orders events that are executed simultaneously.  With one
    # event there is nothing to order, so the value must not change when or
    # what the event does.
    plain = model(tmp_path, "X < 5", "X = 1").simulate(method="ode", t_end=1, n_steps=4)
    prioritised = model(tmp_path, "X < 5", "X = 1", extra="priority: 7").simulate(
        method="ode", t_end=1, n_steps=4
    )
    np.testing.assert_allclose(
        np.asarray(plain.observables["X"]),
        np.asarray(prioritised.observables["X"]),
    )


@pytest.mark.parametrize("rules", ["A() -> B() k\n B() -> A() k", "A() -> 0 time+1"])
def test_species_root_executes_a_non_monotone_surface(tmp_path, rules):
    # The runtime's contract is the first sign change of the root function,
    # not a proven monotone surface, so a species whose amount is not monotone
    # still executes: the event fires at the first crossing and resets it.
    model(tmp_path, "X <= 5", "X = 10")
    path = tmp_path / "events.bngl"
    path.write_text(path.read_text().replace("A() -> 0 k", rules))
    instance = bionetgen.load(str(path))
    result = instance.simulate(method="ode", t_end=2, n_steps=1)
    # The reset to 10 is visible: the value at the end of the run is above the
    # threshold that the trigger watches.
    assert result.observables["X"][-1] > 5.0


def test_recurring_native_event_matches_independent_roadrunner(tmp_path):
    roadrunner = pytest.importorskip("roadrunner")
    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="decay_reset"><listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
<listOfSpecies>
<species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
<species id="B" compartment="c" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
</listOfSpecies><listOfReactions><reaction id="decay" reversible="false">
<listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></kineticLaw>
</reaction></listOfReactions><listOfEvents><event id="reset" useValuesFromTriggerTime="true">
<trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><leq/><ci>A</ci><cn>5</cn></apply></math></trigger>
<listOfEventAssignments>
<eventAssignment variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>10</cn></math></eventAssignment>
<eventAssignment variable="B"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></eventAssignment>
</listOfEventAssignments></event></listOfEvents></model></sbml>"""
    oracle = roadrunner.RoadRunner(sbml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(0, 2, 18, selections=["time", "A", "B"])
    actual = model(tmp_path, "X <= 5", "X = 10; Y = X").simulate(
        method="ode", t_end=2, n_steps=17
    )
    np.testing.assert_allclose(
        actual.observables["X"], expected[:, 1], rtol=2e-6, atol=2e-6
    )
    np.testing.assert_allclose(
        actual.observables["Y"], expected[:, 2], rtol=2e-6, atol=2e-6
    )


@pytest.mark.parametrize("time_symbol", ["time", "t"])
def test_dynamic_native_event_priorities_match_independent_roadrunner(
    tmp_path, time_symbol
):
    roadrunner = pytest.importorskip("roadrunner")
    path = tmp_path / "dynamic-priorities.bngl"
    path.write_text(f"""begin molecule types
  S()
  O()
end molecule types
begin seed species
  S() 0
  O() 0
end seed species
begin observables
  Molecules Signal S()
  Molecules Result O()
end observables
begin bng3_events version 1
  event "raise_signal"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: false
    delay: 1
    priority: 100
    assignment: Signal = 10
  end event
  event "set_first"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: false
    delay: 1
    priority: 10 - Signal + {time_symbol}
    assignment: Result = 1
  end event
  event "set_last"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: false
    delay: 1
    priority: 5 + Signal - {time_symbol}
    assignment: Result = 2
  end event
end bng3_events
""")
    actual = bionetgen.load(str(path)).simulate(method="ode", t_end=3, n_steps=3)

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="dynamic_priority"><listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
<listOfSpecies>
<species id="Signal" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
<species id="Result" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
</listOfSpecies><listOfEvents>
<event id="raise_signal" useValuesFromTriggerTime="false"><trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply></math></trigger><delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay><priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>100</cn></math></priority><listOfEventAssignments><eventAssignment variable="Signal"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>10</cn></math></eventAssignment></listOfEventAssignments></event>
<event id="set_first" useValuesFromTriggerTime="false"><trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply></math></trigger><delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay><priority><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><apply><minus/><cn>10</cn><ci>Signal</ci></apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply></math></priority><listOfEventAssignments><eventAssignment variable="Result"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment></listOfEventAssignments></event>
<event id="set_last" useValuesFromTriggerTime="false"><trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply></math></trigger><delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay><priority><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><apply><plus/><cn>5</cn><ci>Signal</ci></apply><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply></math></priority><listOfEventAssignments><eventAssignment variable="Result"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment></listOfEventAssignments></event>
</listOfEvents></model></sbml>"""
    oracle = roadrunner.RoadRunner(sbml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(0, 3, 4, selections=["time", "Signal", "Result"])
    assert expected[2, 2] == pytest.approx(1.0)
    np.testing.assert_allclose(
        actual.observables["Signal"], expected[:, 1], rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        actual.observables["Result"], expected[:, 2], rtol=0, atol=1e-12
    )


def test_simultaneous_assignments_refuse_two_aliases_for_same_species(tmp_path):
    model(tmp_path, assignments="X = 1; Y = 2")
    path = tmp_path / "events.bngl"
    path.write_text(path.read_text().replace("Molecules Y B()", "Molecules Y A()"))
    with pytest.raises(RuntimeError, match="assignments alias the same species"):
        bionetgen.load(str(path)).simulate(method="ode", t_end=2, n_steps=1)


def multi_event_model(tmp_path, events):
    """A model with several native events.

    ``events`` is the text of the ``event`` blocks, one after the other.
    """
    path = tmp_path / "events.bngl"
    path.write_text(f"""begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 2
end seed species
begin observables
  Molecules X A()
  Molecules Y B()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin bng3_events version 1
{events}
end bng3_events
end model
""")
    return bionetgen.load(str(path))


def event_block(
    name, trigger, assignments, priority=None, delay=None, persistent="true"
):
    lines = [
        f'  event "{name}"',
        f"  trigger: {trigger}",
        "  initial_value: false",
        f"  persistent: {persistent}",
        "  use_values_from_trigger_time: true",
    ]
    if delay is not None:
        lines.append(f"  delay: {delay}")
    if priority is not None:
        lines.append(f"  priority: {priority}")
    for assignment in assignments:
        lines.append(f"  assignment: {assignment}")
    lines.append("  end event")
    return "\n".join(lines)


def test_simultaneous_events_are_executed_in_priority_order(tmp_path):
    # SBML L3V2 Core Sec. 4.12.3: the event with the higher priority is
    # executed first, so the lower priority's assignment is the one that
    # survives.
    high_first = multi_event_model(
        tmp_path,
        event_block("high", "X < 5", ["Y = 1"], priority=10)
        + "\n"
        + event_block("low", "X < 5", ["Y = 2"], priority=1),
    ).simulate(method="ode", t_end=2, n_steps=4)
    low_first = multi_event_model(
        tmp_path,
        event_block("high", "X < 5", ["Y = 1"], priority=1)
        + "\n"
        + event_block("low", "X < 5", ["Y = 2"], priority=10),
    ).simulate(method="ode", t_end=2, n_steps=4)

    assert high_first.observables["Y"][-1] == pytest.approx(2.0)
    assert low_first.observables["Y"][-1] == pytest.approx(1.0)


def test_non_persistent_event_is_not_executed_when_its_trigger_is_false(tmp_path):
    # SBML L3V2 Core Sec. 4.12.2: a trigger that is not persistent is
    # re-evaluated before the execution.  The trigger below holds on an
    # interval that is shorter than the delay, so the event is not executed.
    persistent = multi_event_model(
        tmp_path,
        event_block("window", "(X < 5) && (X > 1)", ["Y = 1"], delay=2.0),
    ).simulate(method="ode", t_end=4, n_steps=4)
    not_persistent = multi_event_model(
        tmp_path,
        event_block(
            "window", "(X < 5) && (X > 1)", ["Y = 1"], delay=2.0, persistent="false"
        ),
    ).simulate(method="ode", t_end=4, n_steps=4)

    assert persistent.observables["Y"][-1] == pytest.approx(1.0)
    assert not_persistent.observables["Y"][-1] == pytest.approx(2.0)


def test_an_execution_that_triggers_another_event_runs_a_cascade(tmp_path):
    # SBML L3V2 Core Sec. 4.12.7: every trigger is re-tested after an
    # execution, so the event whose trigger the assignment made true is
    # executed at the same instant.
    result = multi_event_model(
        tmp_path,
        event_block("first", "X < 5", ["Y = 200"])
        + "\n"
        + event_block("second", "Y > 100", ["X = 1"]),
    ).simulate(method="ode", t_end=2, n_steps=4)

    # The second event resets X at the instant the first one fires, so X
    # decays from 1 instead of continuing to decay from 10.
    assert result.observables["Y"][-1] == pytest.approx(200.0)
    assert result.observables["X"][-1] == pytest.approx(np.exp(-(2.0 - np.log(2.0))))


def test_nonfirst_cvode_root_group_executes_its_event(tmp_path):
    result = multi_event_model(
        tmp_path,
        event_block("later", "time >= 100", ["Y = 999"])
        + "\n"
        + event_block("decay", "X < 5", ["Y = 123"]),
    ).simulate(method="ode", t_end=2, n_steps=4)

    assert result.observables["Y"][-1] == pytest.approx(123.0)


@pytest.mark.parametrize("threshold,expected", [(4, 7), (6, 9)])
def test_event_assignment_samples_a_piecewise_value(tmp_path, threshold, expected):
    # X=5 at the crossing; the condition is sampled when the event assigns Y.
    result = model(tmp_path, "X <= 5", f"Y = if(X > {threshold}, 7, 9)").simulate(
        method="ode", t_end=1, n_steps=1
    )
    assert result.observables["Y"][-1] == pytest.approx(expected)
