"""Reduced analytic acceptance for the dynamic event root in semantic/00966."""

import math
from pathlib import Path

import numpy as np
import pytest
import libsbml
import roadrunner
import bionetgen
from bionetgen.atomizer.modern import Atomizer

SOURCE = Path(__file__).with_name("periodic_threshold.xml").read_text(encoding="utf-8")
PARAMETER_SWITCH_SOURCE = (
    Path(__file__).with_name("event_parameter_switch.xml").read_text(encoding="utf-8")
)


def _native_bngl(include_floor_trigger: bool = True) -> str:
    floor_event = (
        """
  event "complete_after_sixteen_ticks"
    trigger: floor(ticks / 16) >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    priority: 5
    assignment: complete = 1
  end event
"""
        if include_floor_trigger
        else ""
    )
    return f"""begin model
begin molecule types
  Reset()
  Tick()
  Complete()
end molecule types
begin seed species
  Reset() 0
  Tick() 0
  Complete() 0
end seed species
begin observables
  Molecules reset Reset()
  Molecules ticks Tick()
  Molecules complete Complete()
end observables
begin bng3_events version 1
  event "tick"
    trigger: time >= reset + 0.01
    initial_value: false
    persistent: false
    use_values_from_trigger_time: true
    priority: 10
    assignment: reset = time
    assignment: ticks = ticks + 1
  end event
{floor_event}end bng3_events
end model
"""


def test_source_fixture_is_valid_sbml_and_matches_its_analytic_event_schedule():
    document = libsbml.readSBMLFromString(SOURCE)
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors

    # The reset event fires at 0.01, ..., 0.16. The samples are deliberately
    # between events: the floor trigger changes after the sixteenth update.
    oracle = roadrunner.RoadRunner(SOURCE)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = np.asarray(
        oracle.simulate(
            times=[0.0, 0.085, 0.165],
            selections=["time", "reset", "ticks", "complete"],
        ),
        dtype=float,
    )
    np.testing.assert_allclose(
        expected[1:],
        [[0.085, 0.08, 8, 0], [0.165, 0.16, 16, 1]],
        rtol=0,
        atol=1e-9,
    )


def test_native_event_runtime_supports_time_minus_state_threshold(tmp_path):
    source = tmp_path / "periodic-threshold.bngl"
    source.write_text(_native_bngl(include_floor_trigger=False), encoding="utf-8")
    result = bionetgen.load(str(source)).simulate(method="ode", t_end=0.165, n_steps=33)

    assert result.observables["reset"][-1] == pytest.approx(0.16, abs=1e-9)
    assert result.observables["ticks"][-1] == pytest.approx(16, abs=1e-9)


def test_native_event_runtime_retests_floor_trigger_after_discrete_updates(tmp_path):

    source = tmp_path / "periodic-threshold.bngl"
    source.write_text(_native_bngl(), encoding="utf-8")
    result = bionetgen.load(str(source)).simulate(method="ode", t_end=0.165, n_steps=33)

    assert result.observables["reset"][-1] == pytest.approx(0.16, abs=1e-9)
    assert result.observables["ticks"][-1] == pytest.approx(16, abs=1e-9)
    assert result.observables["complete"][-1] == pytest.approx(1, abs=1e-9)


def _parameter_switch_source(switch_time: float) -> str:
    threshold = 10 * math.exp(-switch_time)
    return PARAMETER_SWITCH_SOURCE.replace(
        'id="threshold" value="1"',
        f'id="threshold" value="{threshold:.17g}"',
    )


def _native_parameter_switch_bngl(switch_time: float) -> str:
    return f"""begin model
begin parameters
  k 1
  threshold {10 * math.exp(-switch_time):.17g}
end parameters
begin molecule types
  A()
  EventMarker()
end molecule types
begin seed species
  A() 10
  EventMarker() 0
end seed species
begin observables
  Molecules A A()
  Molecules event_marker EventMarker()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin bng3_events version 1
  event "switch_rate"
    trigger: A < threshold
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: k = 2
    assignment: event_marker = 1
  end event
end bng3_events
end model
"""


def _analytic_parameter_switch_amount(switch_time: float) -> float:
    return 10 * math.exp(switch_time - 4.0)


@pytest.mark.parametrize("switch_time", [0.5, 1.0, 1.5])
def test_parameter_switch_source_is_valid_and_matches_the_independent_oracle(
    switch_time,
):
    source = _parameter_switch_source(switch_time)
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors

    oracle = roadrunner.RoadRunner(source)
    oracle.integrator.relative_tolerance = 1e-12
    oracle.integrator.absolute_tolerance = 1e-14
    epsilon = 1e-5
    before_event = switch_time - epsilon
    after_event = switch_time + epsilon
    values = np.asarray(
        oracle.simulate(
            times=[0.0, before_event, after_event, 2.0],
            selections=["time", "A", "event_marker", "k"],
        ),
        dtype=float,
    )
    assert values[1, 1] == pytest.approx(10 * math.exp(-before_event), rel=1e-8)
    assert values[1, 2] == pytest.approx(0.0, abs=1e-12)
    assert values[1, 3] == pytest.approx(1.0, abs=1e-12)
    assert values[2, 1] == pytest.approx(
        10 * math.exp(switch_time - 2 * after_event), rel=1e-8
    )
    assert values[2, 2] == pytest.approx(1.0, abs=1e-12)
    assert values[2, 3] == pytest.approx(2.0, abs=1e-12)
    assert values[-1, 1] == pytest.approx(
        _analytic_parameter_switch_amount(switch_time), rel=1e-9, abs=1e-11
    )
    assert values[-1, 2] == pytest.approx(1.0, abs=1e-12)
    assert values[-1, 3] == pytest.approx(2.0, abs=1e-12)


@pytest.mark.parametrize("switch_time", [0.5, 1.0, 1.5])
@pytest.mark.parametrize("steps", [1, 16])
def test_native_event_parameter_assignment_matches_the_public_api(
    tmp_path, switch_time, steps
):
    expected_amount = _analytic_parameter_switch_amount(switch_time)

    direct_path = tmp_path / f"direct-{switch_time}-{steps}.bngl"
    direct_path.write_text(_native_parameter_switch_bngl(switch_time), encoding="utf-8")
    direct = bionetgen.load(str(direct_path)).simulate(
        method="ode", t_end=2.0, n_steps=steps
    )
    assert direct.observables["A"][-1] == pytest.approx(
        expected_amount, rel=2e-6, abs=2e-6
    )
    assert direct.observables["event_marker"][-1] == pytest.approx(1.0, abs=1e-12)


def test_coupled_event_parameter_assignment_lowers_to_bng3_events(tmp_path):
    """A coupled model with dynamic trigger and parameter assignment lowers to bng3_events."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="coupled_event_parameter_switch">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="marker" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="1" constant="false"/>
      <parameter id="k2" value="0.5" constant="true"/>
      <parameter id="thresh" value="5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="2"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><apply><power/><ci>A</ci><cn>2</cn></apply></apply>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="r2" reversible="false">
        <listOfReactants><speciesReference species="B" stoichiometry="1"/></listOfReactants>
        <listOfProducts><speciesReference species="A" stoichiometry="1"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k2</ci><ci>B</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="ev1">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>A</ci><ci>thresh</ci></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML\"><cn>2</cn></math></eventAssignment>
          <eventAssignment variable="marker"><math xmlns="http://www.w3.org/1998/Math/MathML\"><cn>1</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result = Atomizer(atomize=False, quiet_mode=True, t_end=2.0, n_steps=10).atomize(
        xml
    )
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "assignment: k_amt = 2" in result.bngl or "assignment: k = 2" in result.bngl
    atomized_path = tmp_path / "coupled_atomized.bngl"
    atomized_path.write_text(result.bngl, encoding="utf-8")
    atomized = bionetgen.load(str(atomized_path)).simulate(
        method="ode", t_end=2.0, n_steps=10
    )
    assert atomized.observables["marker_amt"][-1] == pytest.approx(1.0, abs=1e-12)
