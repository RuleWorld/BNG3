"""A generated event schedule must carry the seed the caller asked for.

A model whose SBML events are lowered to scheduled actions gets a
generated ``simulate`` block instead of the action block the caller
requested.  The generated block has to carry the requested seed with it,
otherwise the seed the caller asked for is silently dropped and the run
that comes back is not the run that was requested.
"""

from bionetgen.atomizer.modern import Atomizer

SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/l3v1/core" level="3" version="1">
  <model id="seeded">
    <listOfCompartments>
      <compartment id="c" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialAmount="10"
               hasOnlySubstanceUnits="true" constant="false"
               boundaryCondition="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="p" value="0" constant="true"/>
    </listOfParameters>
    <listOfEvents>
      <event id="e" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci> time </ci><cn> 2 </cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="p">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn> 5 </cn>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


def _generate(method: str, seed: str = "") -> str:
    atomizer = Atomizer(
        atomize=False,
        quiet_mode=True,
        actions=(
            f'simulate({{method=>"{method}", t_start=>0, t_end=>10, n_steps=>10'
            f"{seed}}})"
        ),
    )
    result = atomizer.atomize(SBML)
    assert result.success, result.error
    return result.bngl


def test_generated_event_schedule_keeps_the_requested_ssa_seed():
    written = _generate("ssa", ", seed=>42")
    # The event was lowered to a schedule, so the requested action block was
    # replaced by a generated one; the generated phases still carry the seed.
    assert "translated to scheduled actions" in written
    assert 'method=>"ssa"' in written
    assert "seed=>42" in written


def test_generated_event_schedule_has_no_seed_when_none_was_requested():
    written = _generate("ssa")
    assert "translated to scheduled actions" in written
    assert "seed=>" not in written


def test_a_deterministic_schedule_does_not_invent_a_seed():
    written = _generate("ode", ", seed=>42")
    assert "translated to scheduled actions" in written
    assert "seed=>" not in written
