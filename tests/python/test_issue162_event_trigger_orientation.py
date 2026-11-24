"""Focused regressions for event triggers written as state minus time.

``state - time <= c`` is the same continuous crossing as ``time >= state - c``.
The native event runtime detects the latter; this module keeps that exact
orientation rewrite from regressing and refuses a scaled clock expression that
the rewrite cannot prove.
"""

from bionetgen.atomizer.modern import Atomizer


def _model(
    trigger_math: str,
    assignment_math: str = "<cn> 1 </cn>",
    extra_events: str = "",
    initial_value: str = "true",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
 <model id="m">
  <listOfCompartments>
   <compartment id="c" size="1" constant="true"/>
  </listOfCompartments>
  <listOfParameters>
   <parameter id="clock" value="10" constant="false"/>
   <parameter id="flag" value="0" constant="false"/>
  </listOfParameters>
  <listOfRules>
   <rateRule variable="clock">
    <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 0 </cn></math>
   </rateRule>
   <rateRule variable="flag">
    <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 0 </cn></math>
   </rateRule>
  </listOfRules>
  <listOfEvents>
   <event id="tick" useValuesFromTriggerTime="true">
    <trigger initialValue="{initial_value}" persistent="true">
     <math xmlns="http://www.w3.org/1998/Math/MathML">{trigger_math}</math>
    </trigger>
    <listOfEventAssignments>
     <eventAssignment variable="clock">
      <math xmlns="http://www.w3.org/1998/Math/MathML">
       <apply><plus/><ci> clock </ci><cn> 10 </cn></apply>
      </math>
     </eventAssignment>
     <eventAssignment variable="flag">
      <math xmlns="http://www.w3.org/1998/Math/MathML">{assignment_math}</math>
     </eventAssignment>
    </listOfEventAssignments>
   </event>
   {extra_events}
  </listOfEvents>
 </model>
</sbml>"""


_TIME = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>'
)


def _translate(
    trigger_math: str, extra_events: str = "", initial_value: str = "true"
) -> str:
    atomizer = Atomizer(atomize=False, quiet_mode=True, t_end=20, n_steps=20)
    result = atomizer.atomize(
        _model(
            trigger_math,
            extra_events=extra_events,
            initial_value=initial_value,
        )
    )
    assert result.success, result.error
    return result.bngl


def test_state_minus_time_trigger_lowers_to_moving_native_threshold() -> None:
    bngl = _translate(
        f"<apply><leq/><apply><minus/><ci> clock </ci>{_TIME}</apply><cn> 0 </cn></apply>"
    )
    assert "begin bng3_events version 1" in bngl
    assert "trigger: time >= clock_amt - (0)" in bngl
    assert "assignment: clock_amt = clock_amt + 10" in bngl
    assert "remain untranslated" not in bngl


def test_state_minus_time_window_keeps_both_edges() -> None:
    bngl = _translate(
        "<apply><and/>"
        f"<apply><leq/><apply><minus/><ci> clock </ci>{_TIME}</apply><cn> 12 </cn></apply>"
        f"<apply><gt/><apply><minus/><ci> clock </ci>{_TIME}</apply><cn> 0 </cn></apply>"
        "</apply>"
    )
    assert "begin bng3_events version 1" in bngl
    assert "trigger: (time >= clock_amt - (12)) && (time < clock_amt - (0))" in bngl


def test_scaled_clock_minus_time_trigger_stays_explicitly_unsupported() -> None:
    # Negative control: the rewrite handles one state symbol minus the clock.
    # A scaled clock would put two dynamic terms on one side, so no native
    # root function can be certified and the event must remain untranslated.
    bngl = _translate(
        f"<apply><leq/><apply><minus/><ci> clock </ci>"
        f"<apply><times/><cn> 2 </cn>{_TIME}</apply></apply><cn> 0 </cn></apply>"
    )
    assert "begin bng3_events version 1" not in bngl
    assert "# Events NOT simulated" in bngl
    assert "clock - (2 * time)" in bngl


def test_clock_equals_initial_instant_uses_startup_non_strict_edge() -> None:
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        _native_trigger_expression,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent

    context = EventTranslationContext(
        resolve_species_pattern=lambda _identifier: None,
        resolve_param=lambda _identifier: None,
        is_param=lambda _identifier: False,
    )
    # eq(time, 0) holds only at initialization. The native runtime's startup
    # check fires a non-strict trigger at t=0 exactly when initialValue=false;
    # with initialValue=true there is no edge and the clock never returns.
    for initial_value in (False, True):
        event = SBMLEvent(
            id="tick0",
            trigger="eq(time, 0)",
            trigger_initial_value=initial_value,
            trigger_persistent=True,
        )
        assert (
            _native_trigger_expression(event, context, instantaneous=True)
            == "time <= 0"
        )

    bngl = _translate(f"<apply><eq/>{_TIME}<cn> 0 </cn></apply>")
    assert "remain untranslated" not in bngl
    assert "NOT simulated" not in bngl
