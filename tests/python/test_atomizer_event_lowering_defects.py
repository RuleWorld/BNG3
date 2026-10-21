"""Regression tests for two defects in the SBML event lowering.

**1. The ``arccot`` folding disagreed with the emitted model.**  The shared
MathML built-in table lowers ``arccot(x)`` onto ``atan(1/(x))`` and evaluates
the same way, but the event-assignment folder used ``atan2(1, x)``, whose
result lies in ``(0, pi)``.  For a negative argument the two differ by
``pi``, so the folded parameter and the model the Atomizer emits described
different systems.  The official SBML Test Suite cases ``semantic/01530`` to
``semantic/01533`` are the reference: their ``P44`` is ``arccot(-0.1)`` and
the suite's own reference reports ``-1.47112767``, which is ``atan(1/x)``.
libRoadRunner 2.10.0 agrees.

**2. A trigger's truth was computed two different ways.**  The event expander
detects a trigger's crossing with a tolerance, but then re-evaluated the
trigger's own expression to decide whether a scheduled firing was still
valid.  For ``time - reset >= 0.01`` with ``reset = 0.02`` at ``t = 0.03``
the two disagree: ``0.03 - 0.02`` is ``0.009999999999999998`` in binary
floating point, so the direct evaluation says the trigger is false at the
very moment it crossed, and the expander cancelled the firing it had just
scheduled.  A recurring reset event then stopped after its second firing.
The official case ``semantic/00963`` is the reference.
"""

from __future__ import annotations

import math

import pytest

from bionetgen.atomizer.modern import Atomizer


def _arccot_event_model() -> str:
    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="arccot_event">
        <listOfParameters>
          <parameter id="P44" value="0" constant="false"/>
        </listOfParameters>
        <listOfEvents>
          <event id="E44" useValuesFromTriggerTime="true">
            <trigger initialValue="false" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <gt/>
                  <csymbol encoding="text"
                    definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
                  <cn>1.5</cn>
                </apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="P44">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  <apply><arccot/><cn>-0.1</cn></apply>
                </math>
              </eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_event_assignment_folds_arccot_as_the_emitted_model_does():
    """The folded value is ``atan(1/x)``, the value the emitted model computes."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_arccot_event_model())

    assert result.success, result.error
    assignments = [
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith("setParameter(")
    ]
    assert len(assignments) == 1, result.bngl
    value = float(assignments[0].split('"')[3])
    # ``atan(1/x)``, the lowering the shared built-in table emits.
    assert math.isclose(value, math.atan(1.0 / -0.1), rel_tol=1e-9)
    # The official reference's own value for ``semantic/01530``'s ``P44``.
    assert math.isclose(value, -1.47112767, rel_tol=1e-6)
    # ``atan2(1, x)`` would be in ``(0, pi)`` and differ by ``pi``.
    assert not math.isclose(value, math.atan2(1.0, -0.1), rel_tol=1e-6)


def test_event_assignment_folds_arccot_like_libroadrunner():
    """The independent oracle agrees with the folded value."""

    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")

    rr = roadrunner.RoadRunner(_arccot_event_model())
    rr.timeCourseSelections = ["time", "P44"]
    values = np.asarray(rr.simulate(times=[0.0, 2.0]), dtype=float)

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_arccot_event_model())
    assert result.success, result.error
    assignment = next(
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith("setParameter(")
    )
    value = float(assignment.split('"')[3])

    assert math.isclose(float(values[1, 1]), value, rel_tol=1e-9)


def _recurring_reset_event_model() -> str:
    """The ``semantic/00963`` model: an event that resets its own clock.

    The trigger ``time - reset >= 0.01`` becomes true again one period after
    the event resets ``reset`` to the current time, so the event fires every
    0.01 s for the whole horizon.
    """

    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="recurring_reset">
        <listOfParameters>
          <parameter id="Q" value="0" constant="false"/>
          <parameter id="reset" value="0" constant="false"/>
        </listOfParameters>
        <listOfEvents>
          <event id="Qinc" useValuesFromTriggerTime="true" priority="1">
            <trigger initialValue="false" persistent="false">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <geq/>
                  <apply><minus/><csymbol encoding="text"
                    definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol><ci>reset</ci></apply>
                  <cn>0.01</cn>
                </apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="reset">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  <csymbol encoding="text"
                    definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
                </math>
              </eventAssignment>
              <eventAssignment variable="Q">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  <apply><plus/><ci>Q</ci><cn>0.01</cn></apply>
                </math>
              </eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_recurring_reset_event_fires_at_every_period():
    """Every period of the recurrence is scheduled, not only the first two.

    The expander scheduled the firing at ``t = 0.03`` and then cancelled it,
    because the trigger's expression evaluated to false one ulp below its
    threshold at the moment it crossed.
    """

    result = Atomizer(atomize=False, quiet_mode=True, t_end=1.0, n_steps=100).atomize(
        _recurring_reset_event_model()
    )

    assert result.success, result.error
    action_block = result.bngl
    assert "begin actions" in action_block, result.bngl
    phases = action_block.count("simulate(")
    # One phase per firing (0.01 s apart over the 1 s horizon) plus the
    # trailing phase that carries the model to the horizon.
    assert phases == 101, phases
    assert action_block.count('setParameter("Q", ') == 100


def _local_parameter_event_model() -> str:
    """A reaction whose rate law uses a *local* parameter of the same name.

    The global ``k`` is ``0.75`` and the reaction's local ``k`` is ``5``.  The
    event fires when ``S1`` falls below ``0.25``, so the crossing time depends
    on the rate the reaction actually states.
    """

    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="local_parameter_event">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="C" initialAmount="0"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.75" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>C</ci><ci>k</ci><ci>S1</ci></apply>
              </math>
              <listOfLocalParameters>
                <localParameter id="k" value="5"/>
              </listOfLocalParameters>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="Event1" useValuesFromTriggerTime="true">
            <trigger initialValue="false" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><lt/><ci>S1</ci><cn>0.25</cn></apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="S2">
                <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
              </eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_state_triggered_event_uses_the_reactions_local_parameter():
    """The crossing time follows the rate the reaction states.

    A reaction's local parameters shadow the model's parameters of the same
    name (SBML Level 3 Version 2 Core, Sec. 4.9.2 "Local parameters"), so the
    species' trajectory is the one the reaction states: ``S1`` decays at the
    local rate ``5`` and crosses ``0.25`` at ``ln(4) / 5``.
    """

    result = Atomizer(atomize=False, quiet_mode=True, t_end=10.0, n_steps=100).atomize(
        _local_parameter_event_model()
    )

    assert result.success, result.error
    assert "S1" in result.bngl
    # The global parameter would give ln(4) / 0.75.
    expected = math.log(4.0) / 5.0
    global_rate = math.log(4.0) / 0.75
    assert result.bngl.count(f"{expected:.12g}") >= 1, result.bngl
    assert result.bngl.count(f"{global_rate:.12g}") == 0, result.bngl


def _initially_true_trigger_model() -> str:
    """An event whose trigger is already true when the simulation starts."""

    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="initially_true_trigger">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1.5e-4"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="C" initialAmount="0"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="1" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k1</ci><ci>S1</ci><ci>C</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="Event1" useValuesFromTriggerTime="true">
            <trigger initialValue="true" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><geq/><csymbol encoding="text"
                  definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol><cn>0</cn></apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="S1">
                <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
              </eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_event_with_an_initially_true_trigger_does_not_fire():
    """SBML fires an event only on a transition from false to true.

    The trigger's value is initialized from ``triggerInitialValue`` and the
    event fires only when that value transitions from false to true (SBML
    Level 3 Version 2 Core, Sec. 4.11.4 "Event triggers").  A trigger that is
    already true when the simulation starts never rises, so the event does
    not fire at all.
    """

    result = Atomizer(atomize=False, quiet_mode=True, t_end=10.0, n_steps=100).atomize(
        _initially_true_trigger_model()
    )

    assert result.success, result.error
    assert "setConcentration" not in result.bngl, result.bngl
