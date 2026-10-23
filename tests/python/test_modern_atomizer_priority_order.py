"""Two simultaneous events that declare the same priority are not serializable.

SBML Level 3 Version 2 Core, Release 2, section 4.12.3 ("Priority") states
that two events that are executed simultaneously and whose priority values
are mathematically equal "must be triggered in a random order", and that a
random order is not the same as an undefined order: the order of execution
has to differ from run to run.  When such a pair assigns different values to
a shared target, the outcome of the model depends on that order, so the
model cannot be lowered to one deterministic action sequence.

The Atomizer refuses such a pair.  It does not refuse the pairs whose
outcome does not depend on the order: events that assign different targets,
events whose priorities differ, and events that declare no priority at all
(the specification leaves the order of those undefined, and any order is a
valid implementation).
"""

from bionetgen.atomizer.modern import Atomizer

ACTIONS = 'simulate({method=>"ode", t_start=>0, t_end=>10, n_steps=>10})'


def _sbml(
    first_target,
    second_target,
    first_priority,
    second_priority,
    first_value,
    second_value,
):
    def event(identifier, target, priority, value):
        priority_block = ""
        if priority is not None:
            priority_block = (
                "<priority><math xmlns='http://www.w3.org/1998/Math/MathML'>"
                f"<cn> {priority} </cn></math></priority>"
            )
        return f"""
      <event id="{identifier}" useValuesFromTriggerTime="true">
        {priority_block}
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci> time </ci><cn> 2 </cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="{target}">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn> {value} </cn>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/l3v1/core" level="3" version="1">
  <model id="priority">
    <listOfCompartments>
      <compartment id="c" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialAmount="10"
               hasOnlySubstanceUnits="true" constant="false" boundaryCondition="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="p" value="0" constant="true"/>
      <parameter id="q" value="0" constant="true"/>
    </listOfParameters>
    <listOfEvents>
      {event("e1", first_target, first_priority, first_value)}
      {event("e2", second_target, second_priority, second_value)}
    </listOfEvents>
  </model>
</sbml>
"""


def _translate(sbml):
    result = Atomizer(atomize=False, quiet_mode=True, actions=ACTIONS).atomize(sbml)
    assert result.success, result.error
    return result.bngl


def test_equal_priority_events_that_conflict_are_refused():
    written = _translate(_sbml("p", "p", 1, 1, 1, 2))
    assert "Events NOT simulated" in written
    assert "setParameter" not in written


def test_equal_priority_events_with_independent_targets_are_scheduled():
    written = _translate(_sbml("p", "q", 1, 1, 1, 2))
    assert "translated to scheduled actions" in written
    assert 'setParameter("p", "1")' in written
    assert 'setParameter("q", "2")' in written


def test_events_with_different_priorities_are_scheduled():
    written = _translate(_sbml("p", "p", 2, 1, 1, 2))
    assert "translated to scheduled actions" in written
    assert 'setParameter("p", "1")' in written
    assert 'setParameter("p", "2")' in written


def test_events_without_a_priority_are_scheduled():
    written = _translate(_sbml("p", "p", None, None, 1, 2))
    assert "translated to scheduled actions" in written
    assert 'setParameter("p", "1")' in written
    assert 'setParameter("p", "2")' in written
