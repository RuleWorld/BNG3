"""Reduced analytic acceptance for the dynamic event root in semantic/00966."""

from pathlib import Path

import numpy as np
import pytest
import libsbml
import roadrunner
import bionetgen

SOURCE = Path(__file__).with_name("periodic_threshold.xml").read_text(encoding="utf-8")


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
