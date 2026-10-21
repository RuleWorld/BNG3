"""Regression tests for a state-dependent event that the Atomizer must not deny.

SBML Level 3 Version 2 Core (Sec. 4.14, *Event*) requires an event to fire
whenever its trigger makes the transition from false to true.  The Atomizer
proves some trigger systems analytically and lowers them to scheduled actions;
a trigger it cannot prove must be reported as untranslated, never as "proven
not to fire".

The official SBML Test Suite case ``semantic/01575`` combines a persistent
event with a delay, an algebraic rule and a rate rule.  Its trigger reads
``k2``, and ``k2`` is defined by an assignment rule over the rate-ruled
``k1``, so ``k2`` changes over the run.  Treating that assignment rule's
*value* as a compile-time constant froze ``k2`` at its initial value, proved
the trigger false for the whole horizon and silently dropped the event.

An assignment rule is only a compile-time constant when everything it reads
is one.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer

_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="event_rule_constants">
    <listOfParameters>
      <parameter id="k1" value="1" constant="false"/>
      <parameter id="k2" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><ci> k1 </ci><ci> k2 </ci></apply>
        </math>
      </algebraicRule>
      <rateRule variable="k1">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 1 </cn></math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><gt/><ci> k2 </ci><cn> 3.5 </cn></apply>
              <apply><lt/><ci> k2 </ci><cn type="integer"> 4 </cn></apply>
            </apply>
          </math>
        </trigger>
        <delay>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 1.1 </cn></math>
        </delay>
        <listOfEventAssignments>
          <eventAssignment variable="k1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 1 </cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""


def _atomize():
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_MODEL)
    assert result.success, result.error
    return atomizer, result


def test_event_over_an_assignment_rule_is_not_reported_as_inactive():
    """The trigger of ``semantic/01575`` does become true during the run."""

    atomizer, _result = _atomize()

    messages = [
        warning.message
        for warning in atomizer.model.import_warnings
        if warning.category == "event"
    ]
    assert messages, "the event produced no diagnostic"
    assert not any("proven not to fire" in message for message in messages), messages
    assert any("untranslated" in message for message in messages), messages


def test_event_over_an_assignment_rule_is_reported_as_unsupported():
    """An untranslated event is an explicit refusal, not a silent omission."""

    atomizer, result = _atomize()

    severities = {
        warning.severity
        for warning in atomizer.model.import_warnings
        if warning.category == "event"
    }
    assert "dropped" in severities, severities
    assert "Events NOT simulated" in result.bngl
