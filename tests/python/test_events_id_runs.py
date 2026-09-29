"""Whole-id-run scanning for event delay expressions carrying raw SBML ids.

``standardize_name`` runs on a raw SBML id only at emission, so a delay whose
MathML is a single ``<ci> A-B </ci>`` reaches event analysis in its source
spelling.  A ``[A-Za-z_][A-Za-z0-9_]*`` tokenizer splits that into ``A`` and
``B``, and ``fold`` (which tokenizes the same way) then evaluates the delay as
the difference ``A - B``.  Scanning maximal id runs keeps the declared symbol
whole, so the event is refused instead of scheduled at a fabricated time.
"""

import pytest

PARAMETERS = {"A": 5.0, "B": 2.0}


def _cycle_context():
    from bionetgen.atomizer.modern.events import EventTranslationContext

    return EventTranslationContext(
        resolve_species_pattern=lambda identifier: (
            f"{identifier}()" if identifier in {"X", "Y", "Z", "A-B"} else None
        ),
        resolve_param=lambda identifier: PARAMETERS.get(identifier),
        is_param=lambda identifier: identifier in PARAMETERS,
        is_compile_time_constant=lambda identifier: identifier in PARAMETERS,
        resolve_initial_value=lambda identifier: {
            "X": 3.0,
            "Y": 1.0,
            "Z": 1.0,
            "A-B": 0.0,
        }.get(identifier),
        resolve_first_order_cycle_event_system=lambda: (
            ("X", "Y", "Z"),
            (1.0, 1.0, 1.0),
        ),
        base_t_end=10.0,
    )


def _cycle_event(delay):
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    return SBMLEvent(
        id="cycle",
        trigger="lt(X, 2)",
        delay=delay,
        trigger_persistent=True,
        assignments=[SBMLEventAssignment("X", "0")],
    )


def _first_firing(result):
    assert result.actions_block is not None
    for line in result.actions_block.splitlines():
        if "t_end=>" in line:
            return float(line.split("t_end=>")[1].split(",")[0])
    raise AssertionError("no scheduled firing in the translated block")


def test_cycle_event_refuses_delay_naming_a_hyphenated_species():
    """A cycle event whose delay is the dynamic species ``A-B`` is refused.

    ``A`` and ``B`` are declared parameters, so the tokenized delay passed the
    compile-time-constant gate and folded to ``5 - 2 == 3``; the event was
    scheduled ``3`` past its real crossing instead of being refused.
    """
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    result = synthesize_event_actions([_cycle_event("A-B")], _cycle_context())

    assert result.converted == 0
    assert [event for event, _reason in result.untranslated] == [_cycle_event("A-B")]


def test_cycle_event_still_lowers_a_constant_delay():
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    result = synthesize_event_actions([_cycle_event("1")], _cycle_context())

    assert result.converted == 1
    assert result.untranslated == []
    assert _first_firing(result) == pytest.approx(1.76550992527)


def _quadratic_context():
    from bionetgen.atomizer.modern.events import EventTranslationContext

    slopes = {"S": 1.0, "S2": 0.5}

    return EventTranslationContext(
        resolve_species_pattern=lambda identifier: (
            f"{identifier}()" if identifier in {"S", "S2", "A-B"} else None
        ),
        resolve_param=lambda identifier: PARAMETERS.get(identifier),
        is_param=lambda identifier: identifier in PARAMETERS,
        is_compile_time_constant=lambda identifier: identifier in PARAMETERS,
        resolve_initial_value=lambda identifier: {
            "S": 0.0,
            "S2": 0.0,
            "A-B": 0.0,
        }.get(identifier),
        resolve_quadratic_rate_from_state=lambda identifier, _event, state: (
            (state.get("S", 0.0) if identifier == "S" else 0.0, 0.0, 0.0, 1.0)
            if identifier in {"S", "S2"}
            else None
        ),
        resolve_quadratic_state_values_from_state=(
            lambda identifier, value, _event, state: {
                "S": value if identifier == "S" else state.get("S", value),
                "S2": 0.0,
            }
        ),
        base_t_end=10.0,
    )


def _quadratic_event(delay):
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    return SBMLEvent(
        id="quadratic",
        trigger="gt(S, 1)",
        delay=delay,
        trigger_persistent=True,
        assignments=[SBMLEventAssignment("S2", "0")],
    )


def test_quadratic_event_refuses_delay_naming_a_hyphenated_species():
    """A single-event quadratic lowering whose delay is ``A-B`` is refused."""
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    result = synthesize_event_actions([_quadratic_event("A-B")], _quadratic_context())

    assert result.converted == 0
    assert [event for event, _reason in result.untranslated] == [
        _quadratic_event("A-B")
    ]


def test_quadratic_event_still_lowers_a_constant_delay():
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    result = synthesize_event_actions([_quadratic_event("1")], _quadratic_context())

    assert result.converted == 1
    assert result.untranslated == []
    assert _first_firing(result) == pytest.approx(2.0)


def _group_context():
    from bionetgen.atomizer.modern.events import EventTranslationContext

    slopes = {"S1": 1.0, "S2": 2.0}

    return EventTranslationContext(
        resolve_species_pattern=lambda identifier: (
            f"{identifier}()" if identifier in {"S1", "S2", "A-B"} else None
        ),
        resolve_param=lambda identifier: PARAMETERS.get(identifier),
        is_param=lambda identifier: identifier in PARAMETERS,
        is_compile_time_constant=lambda identifier: identifier in PARAMETERS,
        resolve_initial_value=lambda identifier: {
            "S1": 0.0,
            "S2": 0.0,
            "A-B": 0.0,
        }.get(identifier),
        resolve_quadratic_rate_from_state=(
            lambda identifier, _event, state: (
                (
                    state.get(identifier, 0.0),
                    0.0,
                    0.0,
                    slopes[identifier],
                )
                if identifier in slopes
                else None
            )
        ),
        resolve_quadratic_state_values_from_state=(
            lambda identifier, value, _event, state: {
                key: state.get(key, value) for key in state
            }
        ),
        base_t_end=10.0,
    )


def _group_events(delay):
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    return [
        SBMLEvent(
            id="E1",
            trigger="gt(S1, 1)",
            delay=delay,
            trigger_persistent=True,
            assignments=[SBMLEventAssignment("S1", "0")],
        ),
        SBMLEvent(
            id="E2",
            trigger="gt(S2, 1)",
            trigger_persistent=True,
            assignments=[SBMLEventAssignment("S2", "0")],
        ),
    ]


def test_quadratic_group_refuses_delay_naming_a_hyphenated_species():
    """A two-event quadratic group whose delay is ``A-B`` is refused."""
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    result = synthesize_event_actions(_group_events("A-B"), _group_context())

    assert result.converted == 0
    assert [event for event, _reason in result.untranslated] == _group_events("A-B")


def test_spaced_delay_difference_is_still_a_difference():
    """``A - B`` keeps its arithmetic meaning and is still lowered exactly.

    The parser serializes a real MathML difference with surrounding spaces, so
    an id-run scan must keep reading it as two symbols rather than as one
    hyphenated id.
    """
    from bionetgen.atomizer.modern.events import synthesize_event_actions

    spaced = synthesize_event_actions([_cycle_event("A - B")], _cycle_context())
    constant = synthesize_event_actions([_cycle_event("3")], _cycle_context())

    assert spaced.converted == 1
    assert spaced.untranslated == []
    assert spaced.actions_block == constant.actions_block
    assert _first_firing(spaced) == pytest.approx(3.76550992527)
