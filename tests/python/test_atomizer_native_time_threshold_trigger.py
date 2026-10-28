"""A non-strict time threshold reaches the native event runtime.

``geq(time, c)`` and ``leq(time, c)`` cross their threshold transversally,
because time increases at rate one: unlike a non-strict comparison of a
state, they have no tangential contact.  An event with such a trigger whose
assignment depends on the state (here ``p := 2*S2`` at ``t >= 1.5``) cannot
be a scheduled action, so it has to be lowered to the native runtime, as the
strict ``gt(time, c)`` already was.  Before this change the non-strict
trigger was refused and the event was dropped.
"""

from __future__ import annotations

import math

import pytest

from bionetgen.atomizer.modern import Atomizer

SOURCE = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
<model id="m" timeUnits="time">
<listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
<listOfSpecies>
 <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
 <species id="S2" compartment="C" initialAmount="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
</listOfSpecies>
<listOfParameters><parameter id="p" value="1" constant="false"/></listOfParameters>
<listOfReactions>
 <reaction id="r" reversible="false" fast="false">
  <listOfReactants><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfReactants>
  <listOfProducts><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>p</ci><ci>S1</ci></apply></math></kineticLaw>
 </reaction>
</listOfReactions>
<listOfEvents>
 <event id="E1" useValuesFromTriggerTime="true">
  <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol><cn>1.5</cn></apply></math></trigger>
  <listOfEventAssignments><eventAssignment variable="p"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>2</cn><ci>S2</ci></apply></math></eventAssignment></listOfEventAssignments>
 </event>
</listOfEvents>
</model></sbml>"""


def _convert(source: str = SOURCE, **options) -> str:
    atomized = Atomizer(
        atomize=False, quiet_mode=True, t_end=3, n_steps=6, **options
    ).atomize(source)
    assert atomized.success, atomized.error
    return atomized.bngl


def test_non_strict_time_threshold_is_lowered_to_the_native_runtime():
    bngl = _convert()
    assert "begin bng3_events version 1" in bngl
    assert "trigger: time >= 1.5" in bngl
    assert "assignment: p_amt = 2 * S2_amt" in bngl
    assert "remain untranslated" not in bngl


def test_strict_and_non_strict_time_thresholds_lower_alike():
    strict = _convert(SOURCE.replace("<geq/>", "<gt/>"))
    assert "trigger: time > 1.5" in strict
    assert "assignment: p_amt = 2 * S2_amt" in strict


def test_non_strict_time_threshold_stays_untranslated_for_ssa():
    """The native SSA runtime refuses a trigger that reads the clock."""

    bngl = _convert(actions='simulate({method=>"ssa", t_end=>3, n_steps=>6})')
    assert "begin bng3_events version 1" not in bngl


def test_native_engine_executes_the_non_strict_time_threshold(tmp_path):
    import bionetgen

    # S1' = -p*S1 with p = 1 until t = 1.5, then p = 2*S2(1.5).
    bngl = _convert()
    source = tmp_path / "model.bngl"
    source.write_text(bngl, encoding="utf-8")
    bionetgen.load(str(source)).execute()
    lines = (tmp_path / "model.gdat").read_text().splitlines()
    header = lines[0].lstrip("#").split()
    rows = {}
    for line in lines[1:]:
        if line.strip() and not line.startswith("#"):
            fields = [float(field) for field in line.split()]
            rows[round(fields[0], 9)] = dict(zip(header, fields))
    rate = 2 * (1 - math.exp(-1.5))
    for time in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        expected = (
            math.exp(-time)
            if time <= 1.5
            else math.exp(-1.5) * math.exp(-rate * (time - 1.5))
        )
        assert rows[round(time, 9)]["S1_amt"] == pytest.approx(
            expected, rel=1e-6, abs=1e-8
        )
