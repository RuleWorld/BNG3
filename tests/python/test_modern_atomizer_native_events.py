"""Contracts for the native ``bng3_events`` lowering of SBML events.

A state-dependent SBML trigger has no finite schedule of BNGL actions, so
the modern Atomizer hands it to the native BNG3 event runtime, which locates
the trigger's rising edge with continuous root finding.  These tests pin the
lowered model, the unit conversion between an SBML value and the observable
the runtime observes, the delay semantics, and the boundaries that stay
explicitly unsupported.
"""

import numpy as np
import pytest

from bionetgen import _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer


def atomize(xml, **kwargs):
    atomizer = Atomizer(atomize=False, quiet_mode=True, **kwargs)
    result = atomizer.atomize(xml)
    result.import_warnings = list(atomizer.model.import_warnings)
    return result


def coupled_event_model(
    *,
    delay: str = "",
    persistent: str = "true",
    operator: str = "lt",
    threshold: str = "0.75",
    use_values_from_trigger_time: str = "true",
    assignment: str = '<eventAssignment variable="S2">'
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>'
    "</eventAssignment>",
    compartment_size: str = "1",
    substance_units: str = "true",
) -> str:
    """A model whose trigger species has no provable analytic trajectory.

    ``S1`` is consumed by a bimolecular reaction and replenished by a
    first-order one, so the crossing time cannot be solved in closed form
    and the event has to reach the native runtime.
    """

    delay_element = (
        f'<delay><math xmlns="http://www.w3.org/1998/Math/MathML">'
        f"<cn>{delay}</cn></math></delay>"
        if delay
        else ""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="native_event">
    <listOfCompartments>
      <compartment id="C" size="{compartment_size}" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="{substance_units}"/>
      <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="{substance_units}"/>
      <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="{substance_units}"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.75" constant="true"/>
      <parameter id="k2" value="0.25" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="consume" reversible="false">
        <listOfReactants>
          <speciesReference species="S1"/>
          <speciesReference species="S2" stoichiometry="2"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="S3"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="release" reversible="false">
        <listOfReactants><speciesReference species="S3"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="S1"/>
          <speciesReference species="S2"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k2</ci><ci>S3</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="reset" useValuesFromTriggerTime="{use_values_from_trigger_time}">
        <trigger initialValue="true" persistent="{persistent}">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><{operator}/><ci>S1</ci><cn>{threshold}</cn></apply>
          </math>
        </trigger>
        {delay_element}
        <listOfEventAssignments>{assignment}</listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""


def test_state_dependent_trigger_is_lowered_to_the_native_event_block():
    result = atomize(coupled_event_model())

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "trigger: S1_amt < 0.75" in result.bngl
    assert "assignment: S2_amt = 1" in result.bngl
    # The event is executed, so the reference marker for a dropped event and
    # the refusal note must both be absent.
    assert "# Events NOT simulated" not in result.bngl
    assert (
        "state-dependent or non-constant event(s) remain untranslated"
        not in result.bngl
    )
    assert "setConcentration(" not in result.bngl


def test_native_event_lowering_reports_an_informational_diagnostic():
    result = atomize(coupled_event_model())

    diagnostics = [
        warning
        for warning in (result.import_warnings or [])
        if warning.get("category") == "event"
    ]
    assert diagnostics, "the event lowering must report what it did"
    assert all(
        "native BNG3 event runtime" in warning.get("message", "")
        for warning in diagnostics
    )
    assert {warning.get("severity") for warning in diagnostics} == {"info"}


def test_native_event_delay_is_carried_into_the_event_block():
    result = atomize(coupled_event_model(delay="1.5"))

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "delay: 1.5" in result.bngl


def test_non_strict_state_trigger_stays_refused_without_a_monotone_state():
    # A non-strict comparison is also true at a tangential contact, which
    # leaves no sign change.  The crossing is therefore only a rising edge
    # when the trigger's state cannot reverse at the threshold, and the
    # coupled model below has no such proof.
    result = atomize(coupled_event_model(operator="leq"))

    assert result.success, result.error
    assert "begin bng3_events version 1" not in result.bngl
    assert "# Events NOT simulated" in result.bngl
    assert "trigger is not a simple time threshold" in result.bngl


def test_non_persistent_trigger_is_lowered_to_the_native_event_block():
    # SBML L3V2 Core Sec. 4.12.2: a trigger that is not persistent is
    # re-evaluated before the execution, and the event is not executed when
    # the trigger has become false again.  The native runtime owns that
    # re-evaluation, so the event reaches the runtime.
    result = atomize(coupled_event_model(persistent="false"))

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "persistent: false" in result.bngl
    assert "# Events NOT simulated" not in result.bngl


def test_stochastic_run_keeps_the_explicit_refusal():
    result = Atomizer(
        atomize=False,
        quiet_mode=True,
        t_end=1,
        n_steps=10,
        actions='simulate({method=>"ssa", t_end=>1, n_steps=>10})',
    ).atomize(coupled_event_model())

    assert result.success, result.error
    assert "begin bng3_events version 1" not in result.bngl
    assert (
        "state-triggered SBML events require stochastic jump scheduling" in result.bngl
    )


def test_two_state_trigger_is_lowered_to_the_native_event_block():
    xml = coupled_event_model(operator="gt", threshold="0.5").replace(
        "<ci>S1</ci><cn>0.5</cn>", "<ci>S1</ci><ci>S2</ci>"
    )
    result = atomize(xml)

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "trigger: S1_amt > S2_amt" in result.bngl


def test_rate_rule_parameter_trigger_is_lowered_to_the_native_event_block():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="rate_rule_event">
    <listOfParameters>
      <parameter id="P" value="1" constant="false"/>
      <parameter id="Q" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="P"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>Q</ci></math></rateRule>
      <rateRule variable="Q"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><ci>P</ci></apply></math></rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="crossing" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>P</ci><cn>0.75</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="P">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""

    result = atomize(xml)

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "trigger: P_amt < 0.75" in result.bngl
    assert "assignment: P_amt = 1" in result.bngl


def test_species_values_are_converted_into_the_observed_amount_units():
    # A species that reports concentrations is observed as an amount, so the
    # comparison and the assignment both carry the compartment size.
    result = atomize(
        coupled_event_model(compartment_size="0.25", substance_units="false")
    )

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    # S1 reports a concentration, so the threshold is an amount: 0.75 * 0.25.
    assert "trigger: S1_amt < (0.25 * (0.75))" in result.bngl
    # The assignment sets a concentration too, so the amount is 1 * 0.25.
    assert "assignment: S2_amt = (1 * (0.25))" in result.bngl


def test_non_strict_conjunctive_trigger_is_lowered_to_the_native_event_block():
    # A conjunction of non-strict comparisons holds on an interval of the
    # state, and its rising edge is the crossing of the smallest conjunct
    # difference.  The rate-ruled parameter below grows monotonically, so the
    # crossing into the interval is transversal.
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="interval_trigger">
    <listOfParameters>
      <parameter id="k1" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="k1"><math xmlns="http://www.w3.org/1998/Math/MathML">
        <cn>1</cn>
      </math></rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="interval" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><geq/><ci>k1</ci><cn>0.25</cn></apply>
              <apply><leq/><ci>k1</ci><cn>0.75</cn></apply>
            </apply>
          </math>
        </trigger>
        <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
        <listOfEventAssignments>
          <eventAssignment variable="k1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""

    result = atomize(xml)

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "trigger: (k1_amt >= 0.25) && (k1_amt <= 0.75)" in result.bngl
    assert "# Events NOT simulated" not in result.bngl


def test_event_priority_is_carried_into_the_native_event_block():
    # The priority orders the assignments of events that are executed
    # simultaneously.  With one event there is nothing to order, so the value
    # is carried without changing the execution.
    xml = coupled_event_model().replace(
        '<event id="reset" useValuesFromTriggerTime="true">',
        '<event id="reset" useValuesFromTriggerTime="true">'
        '<priority><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<cn>7</cn></math></priority>",
    )

    result = atomize(xml)

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "priority: 7" in result.bngl


def test_sbml_export_preserves_the_native_event(tmp_path):
    import libsbml

    result = atomize(coupled_event_model(delay="1.5"))

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=100)
    destination = tmp_path / "exported.xml"
    cpp.io.write_sbml(model, network, str(destination))

    document = libsbml.readSBML(str(destination))
    assert document.getNumErrors() == 0
    model_element = document.getModel()
    assert model_element.getNumEvents() == 1
    event = model_element.getEvent(0)
    assert event.getUseValuesFromTriggerTime() is True
    assert event.getTrigger().getInitialValue() is True
    assert event.getTrigger().getPersistent() is True
    assert event.getNumEventAssignments() == 1
    # The assignment targets the network species the observable covers.
    assignment = event.getEventAssignment(0)
    assert assignment.getVariable() == "S2"


def test_sbml_export_preserves_the_delayed_event(tmp_path):
    import libsbml

    result = atomize(
        coupled_event_model(delay="1.5").replace(
            '<event id="reset" useValuesFromTriggerTime="true">',
            '<event id="reset" useValuesFromTriggerTime="true">'
            '<priority><math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<cn>7</cn></math></priority>",
        )
    )

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=100)
    destination = tmp_path / "exported.xml"
    cpp.io.write_sbml(model, network, str(destination))

    document = libsbml.readSBML(str(destination))
    assert document.getNumErrors() == 0
    event = document.getModel().getEvent(0)
    delay = event.getDelay()
    assert delay is not None
    assert abs(delay.getMath().getValue() - 1.5) < 1e-12


def test_sbml_export_keeps_the_event_executable_after_a_reimport(tmp_path):
    result = atomize(coupled_event_model(delay="1.5"))

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=100)
    destination = tmp_path / "exported.xml"
    cpp.io.write_sbml(model, network, str(destination))

    reimported = atomize(destination.read_text())
    assert reimported.success, reimported.error
    # The exported trigger names the network species the observable covers, so
    # the re-imported document still executes the event.
    assert "begin bng3_events version 1" in reimported.bngl
    assert "trigger: S1_amt < 0.75" in reimported.bngl
    assert "delay: 1.5" in reimported.bngl


def test_runtime_refusal_of_an_initial_rising_edge_stays_unsupported(tmp_path):
    # A strict trigger that equals its threshold at the start of the
    # simulation and rises immediately has no crossing to attribute.  The
    # refusal has to read as an unsupported construct, not as a failure.
    from bionetgen.model import BioNetGenModel

    source = tmp_path / "rising.bngl"
    source.write_text("""begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
end molecule types
begin seed species
 A() 10
end seed species
begin observables
 Molecules X A()
end observables
begin reaction rules
 A() -> 0 k
end reaction rules
begin bng3_events version 1
 event "rising"
 trigger: time > 0
 initial_value: false
 persistent: true
 use_values_from_trigger_time: true
 assignment: X = 0
 end event
end bng3_events
end model
""")
    model = cpp.parse_file(str(source))
    with pytest.raises(RuntimeError) as error:
        BioNetGenModel(model).simulate(method="ode", t_end=1, n_steps=1)
    message = str(error.value)
    assert "strict trigger equals its threshold at the initial time" in message
    # The harness classifies a refusal by its text, so the refusal has to
    # carry a marker that reads as "unsupported".
    assert "not implemented" in message


def _load(result, tmp_path):
    from bionetgen.model import load

    path = tmp_path / "native_event.bngl"
    path.write_text(result.bngl)
    return load(str(path))


def conjunctive_event_model() -> str:
    """A trigger that holds only where both of its comparisons hold."""

    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="conjunctive_event">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
      <species id="S2" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="1" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants><speciesReference species="S1"/></listOfReactants>
        <listOfProducts><speciesReference species="S2"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>S1</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="threshold" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><lt/><ci>S1</ci><cn>0.1</cn></apply>
              <apply><lt/><ci>S2</ci><cn>0.95</cn></apply>
            </apply>
          </math>
        </trigger>
        <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></delay>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""


def test_conjunctive_state_trigger_is_lowered_to_the_native_event_block():
    result = atomize(conjunctive_event_model())

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "trigger: (S1_amt < 0.1) && (S2_amt < 0.95)" in result.bngl
    assert "delay: 1" in result.bngl
    assert "# Events NOT simulated" not in result.bngl


def test_conjunctive_native_event_matches_independent_roadrunner(tmp_path):
    roadrunner = pytest.importorskip("roadrunner")
    xml = conjunctive_event_model()
    result = atomize(xml)

    model = _load(result, tmp_path)
    actual = model.simulate(method="ode", t_end=5.0, n_steps=50)

    oracle = roadrunner.RoadRunner(xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(0, 5.0, 51, selections=["time", "S1", "S2"])

    np.testing.assert_allclose(
        actual.observables["S1_amt"], expected[:, 1], rtol=2e-6, atol=2e-6
    )
    np.testing.assert_allclose(
        actual.observables["S2_amt"], expected[:, 2], rtol=2e-6, atol=2e-6
    )


def test_native_event_trajectory_matches_independent_roadrunner(tmp_path):
    roadrunner = pytest.importorskip("roadrunner")
    xml = coupled_event_model()
    result = atomize(xml)

    model = _load(result, tmp_path)
    actual = model.simulate(method="ode", t_end=1.0, n_steps=50)

    oracle = roadrunner.RoadRunner(xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(0, 1.0, 51, selections=["time", "S1", "S2", "S3"])

    np.testing.assert_allclose(
        actual.observables["S1_amt"], expected[:, 1], rtol=2e-6, atol=2e-6
    )
    np.testing.assert_allclose(
        actual.observables["S2_amt"], expected[:, 2], rtol=2e-6, atol=2e-6
    )
    np.testing.assert_allclose(
        actual.observables["S3_amt"], expected[:, 3], rtol=2e-6, atol=2e-6
    )


def _delayed_trajectory(tmp_path, name, **kwargs):
    result = atomize(coupled_event_model(**kwargs))
    model = _load(result, tmp_path)
    actual = model.simulate(method="ode", t_end=1.0, n_steps=400)
    times = np.asarray(actual.time, dtype=float)
    s1 = np.asarray(actual.observables["S1_amt"], dtype=float)
    s2 = np.asarray(actual.observables["S2_amt"], dtype=float)
    crossing = int(np.argmax(s1 < 0.75))
    after = int(np.searchsorted(times, times[crossing] + 0.5))
    assert crossing > 0
    assert after < times.size
    return times, s1, s2, crossing, after


@pytest.mark.parametrize("delay", ["0.001", "0.02", "0.5"])
@pytest.mark.parametrize("n_steps", [20, 400])
def test_delayed_event_stop_time_matches_independent_roadrunner(
    tmp_path, delay, n_steps
):
    roadrunner = pytest.importorskip("roadrunner")
    xml = coupled_event_model(delay=delay)
    model = _load(atomize(xml), tmp_path)
    actual = model.simulate(method="ode", t_end=1.0, n_steps=n_steps)

    oracle = roadrunner.RoadRunner(xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(
        0, 1.0, n_steps + 1, selections=["time", "S1", "S2", "S3"]
    )
    # Short delays can execute inside the solver step that found the root;
    # coarse and fine output grids must preserve that execution instant.
    for column, name in enumerate(["S1_amt", "S2_amt", "S3_amt"], start=1):
        np.testing.assert_allclose(
            actual.observables[name], expected[:, column], rtol=2e-6, atol=2e-6
        )


def test_native_event_delay_runs_the_assignment_after_the_delay(tmp_path):
    times, s1, s2, crossing, after = _delayed_trajectory(
        tmp_path, "delayed", delay="0.5"
    )

    # The trigger fires when S1 falls below 0.75; the assignment then runs
    # half a second later, so S2 is still on its original trajectory when the
    # trigger is crossed and is reset to 1 once the delay elapses.
    assert s2[after] == pytest.approx(1.0, abs=0.35)
    assert s2[after] < s2[crossing]


def test_native_event_uses_the_trigger_time_values(tmp_path):
    times, s1, s2, crossing, after = _delayed_trajectory(
        tmp_path,
        "trigger-time",
        delay="0.5",
        assignment='<eventAssignment variable="S2">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>'
        "</eventAssignment>",
    )

    # The assignment reads S1 at the trigger time, where it has just fallen
    # below the threshold, not at the execution time, where it has decayed
    # further.
    assert s2[after] == pytest.approx(0.75, abs=0.01)
    assert abs(s2[after] - s1[after]) > 0.02


def test_native_event_can_read_the_execution_time_values(tmp_path):
    times, s1, s2, crossing, after = _delayed_trajectory(
        tmp_path,
        "execution-time",
        delay="0.5",
        use_values_from_trigger_time="false",
        assignment='<eventAssignment variable="S2">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>'
        "</eventAssignment>",
    )

    # Without the trigger-time snapshot the assignment reads S1 where it is
    # when the delay elapses.
    assert s2[after] == pytest.approx(s1[after], rel=2e-3)


def two_event_model(
    *,
    first_priority: str = "",
    second_priority: str = "",
    second_trigger: str = "<ci>S1</ci><cn>0.75</cn>",
    second_delay: str = "",
) -> str:
    """A model with two state-triggered events that share one trigger.

    The two events are triggered at the same instant, so their priorities
    decide the order in which they are executed.
    """

    def priority(value: str) -> str:
        if not value:
            return ""
        return (
            '<priority><math xmlns="http://www.w3.org/1998/Math/MathML">'
            f"<cn>{value}</cn></math></priority>"
        )

    def delay(value: str) -> str:
        if not value:
            return ""
        return (
            '<delay><math xmlns="http://www.w3.org/1998/Math/MathML">'
            f"<cn>{value}</cn></math></delay>"
        )

    return f"""<sbml xmlns="http://www.w3.org/1998/sbml/level3/version2/core">
  <model id="two_events">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
      <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"/>
      <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.75" constant="true"/>
      <parameter id="k2" value="0.25" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="consume" reversible="false">
        <listOfReactants>
          <speciesReference species="S1"/>
          <speciesReference species="S2" stoichiometry="2"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="S3"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="release" reversible="false">
        <listOfReactants><speciesReference species="S3"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="S1"/>
          <speciesReference species="S2"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k2</ci><ci>S3</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="first" useValuesFromTriggerTime="true">
        {priority(first_priority)}
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>S1</ci><cn>0.75</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S2">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="second" useValuesFromTriggerTime="true">
        {priority(second_priority)}
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/>{second_trigger}</apply>
          </math>
        </trigger>
        {delay(second_delay)}
        <listOfEventAssignments>
          <eventAssignment variable="S3">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""


def test_two_events_are_lowered_into_one_native_event_block():
    result = atomize(two_event_model(first_priority="7", second_priority="3"))

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert result.bngl.count('  event "') == 2
    assert "priority: 7" in result.bngl
    assert "priority: 3" in result.bngl
    assert "# Events NOT simulated" not in result.bngl


def test_simultaneous_events_without_a_priority_are_refused():
    # The specification leaves the order of two simultaneous events without a
    # priority undefined, so the model is refused instead of executed with an
    # arbitrary order.
    result = atomize(two_event_model())

    assert result.success, result.error
    assert "begin bng3_events version 1" not in result.bngl
    assert "# Events NOT simulated" in result.bngl
    assert (
        "simultaneous event without a priority has an undefined execution order"
        in result.bngl
    )


def test_simultaneous_events_with_the_same_priority_are_refused():
    result = atomize(two_event_model(first_priority="5", second_priority="5"))

    assert result.success, result.error
    assert "begin bng3_events version 1" not in result.bngl
    assert (
        "simultaneous same-priority event group requires a random execution order"
        in result.bngl
    )


def test_events_with_different_triggers_are_ordered_by_their_priorities():
    # Two events with different triggers can still be triggered at the same
    # instant, so they need a priority of their own as well.
    result = atomize(
        two_event_model(
            first_priority="7",
            second_priority="3",
            second_trigger="<ci>S3</ci><cn>0.5</cn>",
        )
    )

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert result.bngl.count('  event "') == 2


def test_events_with_the_same_trigger_and_different_delays_are_ordered():
    result = atomize(
        two_event_model(first_priority="7", second_priority="3", second_delay="0.5")
    )

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert result.bngl.count('  event "') == 2


def test_source_action_grid_preserves_post_assignment_at_early_boundary(tmp_path):
    """A zero-duration continuation must retain its post-event output row."""
    from bionetgen import load
    from scripts.ci.validate_published_biomodels import _source_action_bngl

    bngl = """begin model
begin parameters
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Species A_count A()
end observables
begin reaction rules
end reaction rules
end model
begin actions
  generate_network({overwrite=>1})
  simulate({method=>"ode", t_start=>0, t_end=>0.01, sample_times=>[0,0.01]})
  setConcentration("A()", "5")
  simulate({continue=>1, method=>"ode", t_start=>0.01, t_end=>0.01, n_steps=>1})
  simulate({continue=>1, method=>"ode", t_start=>0.01, t_end=>1, sample_times=>[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1]})
end actions
"""
    source = _source_action_bngl(
        bngl,
        rtol=1e-7,
        atol=1e-12,
        max_step=0.0,
        t_end=1.0,
        n_steps=10,
    )
    path = tmp_path / "early_boundary.bngl"
    path.write_text(source)
    load(str(path)).execute()

    lines = path.with_suffix(".gdat").read_text().splitlines()
    header = next(
        line.removeprefix("#").split() for line in lines if line.startswith("#")
    )
    rows = np.asarray(
        [
            [float(value) for value in line.split()]
            for line in lines
            if line and not line.startswith("#")
        ]
    )
    boundary = rows[np.isclose(rows[:, header.index("time")], 0.01, rtol=0, atol=1e-12)]
    assert boundary.shape[0] == 2
    assert boundary[0, header.index("A_count")] == pytest.approx(1.0)
    assert boundary[-1, header.index("A_count")] == pytest.approx(5.0)
