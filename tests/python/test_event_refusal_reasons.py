"""Refusal reasons must name the cause that the model author can act on.

A state threshold on a species whose SBML id carries a character outside the
SId class (``A-B``) is refused because the id cannot be spelled, not because
the trigger is state-dependent.  Reporting the state-dependent reason sends
the author to rewrite a trigger that is already correct, so the two causes get
distinct reasons -- and the specific one is only used when it is the true and
sole cause.
"""

import sys

import pytest

sys.path.insert(0, "python")

MML = 'xmlns="http://www.w3.org/1998/Math/MathML"'

# The reason the trigger shape is refused, shared with every other
# state-dependent refusal in the lowering.
STATE_DEPENDENT_REASON = (
    "trigger is not a simple time threshold (state-dependent "
    "triggers cannot be scheduled)"
)


def _context(resolve_species_pattern=None, resolve_param=None):
    from bionetgen.atomizer.modern.events import EventTranslationContext

    return EventTranslationContext(
        resolve_species_pattern=resolve_species_pattern
        or (lambda variable: "@cell:M_S()" if variable == "S" else None),
        resolve_param=resolve_param or (lambda variable: {"k": 3}.get(variable)),
        is_param=lambda variable: variable == "k",
        method="ode",
        base_t_end=10,
        base_steps=20,
    )


def _event(trigger):
    from bionetgen.atomizer.modern import SBMLEvent

    return SBMLEvent(id="e0", trigger=trigger, assignments=[("S", "0")])


def _reason_for(trigger):
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    result = synthesize_event_actions([_event(trigger)], _context())
    assert result.untranslated, f"{trigger!r} was expected to be refused"
    return result.untranslated[0][1]


def test_hyphenated_id_state_threshold_reports_the_unspellable_id():
    """``gt(A-B, 1)`` is a plain state threshold; the id is what cannot be used."""

    reason = _reason_for("gt(A-B, 1)")

    assert reason != STATE_DEPENDENT_REASON
    assert "A-B" in reason
    assert "SId" in reason


def test_unsupported_trigger_keeps_the_state_dependent_reason():
    """A trigger that is genuinely not a threshold keeps the old reason."""

    assert _reason_for("gt(plus(S, 1), S)") == STATE_DEPENDENT_REASON


def test_hyphenated_id_does_not_mask_an_unsupported_trigger():
    """The specific reason needs the unspellable id to be the sole cause."""

    # The left operand is an expression, not a bare id, so the comparison is
    # refused for its own shape even though ``A-B`` appears in it.
    assert _reason_for("gt(plus(A-B, 1), S)") == STATE_DEPENDENT_REASON
    # Both operands are states, so neither side is a constant threshold.
    assert _reason_for("gt(A-B, S)") == STATE_DEPENDENT_REASON
    # Two dynamic conjuncts are not a single state threshold either.
    assert _reason_for("and(gt(A-B, 1), gt(S, 1))") == STATE_DEPENDENT_REASON


def test_a_supported_trigger_is_unaffected():
    """A trigger that lowers today still lowers, and is not reclassified."""

    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )

    context = EventTranslationContext(
        resolve_species_pattern=lambda variable: (
            "@cell:M_S()" if variable == "S" else None
        ),
        resolve_param=lambda variable: {"k": 3}.get(variable),
        is_param=lambda variable: variable == "k",
        # ``S`` rises affinely, so ``gt(S, 1)`` is a schedulable crossing.
        resolve_affine_rate_for_event=lambda identifier, _event: (
            (0.0, 2.0) if identifier == "S" else None
        ),
        method="ode",
        base_t_end=10,
        base_steps=20,
    )

    for trigger in ("geq(time, 5)", "gt(S, 1)"):
        result = synthesize_event_actions([_event(trigger)], context)
        assert result.converted == 1, (trigger, result.untranslated)
        assert result.untranslated == [], (trigger, result.untranslated)


_HYPHEN_EVENT_MODEL = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="hyphen_trigger">
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false" constant="false"/>
      <species id="A-B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="produce" reversible="false">
        <listOfProducts>
          <speciesReference species="A-B" stoichiometry="1"/>
        </listOfProducts>
        <kineticLaw><math {MML}><cn>0.1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfParameters>
      <parameter id="out" value="0" constant="false"/>
    </listOfParameters>
    <listOfEvents>
      <event id="tick">
        <trigger initialValue="true" persistent="true"><math {MML}>
          <apply><gt/><ci>A-B</ci><cn>1</cn></apply>
        </math></trigger>
        <listOfEventAssignments>
          <eventAssignment variable="out"><math {MML}><cn>7</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""


def test_writer_note_carries_the_unspellable_id_reason():
    """The reason reaches the generated BNGL note the author actually reads."""

    from bionetgen.atomizer.modern import Atomizer

    result = Atomizer(atomize=False, quiet_mode=True, t_end=50, n_steps=100).atomize(
        _HYPHEN_EVENT_MODEL
    )

    assert result.success, result.error
    assert STATE_DEPENDENT_REASON not in result.bngl
    assert 'event tick: trigger references id "A-B"' in result.bngl


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    for trigger in ("gt(A-B, 1)", "gt(plus(S, 1), S)", "geq(time, 5)"):
        print(trigger, "->", _reason_for(trigger))
