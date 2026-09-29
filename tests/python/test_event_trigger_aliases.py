"""Trigger operator spellings must reach the same resolver.

MathML content markup lowers to the short relation names ``gt``/``geq``/``lt``/
``leq``, but a trigger can also arrive spelled out (``greaterThan``, ...) from a
``formula`` attribute or a non-MathML producer. Both name the same comparison,
so both must be recognised by the affine-state resolver *and* by the
state-difference resolver; otherwise the model is refused for the wrong reason.
"""

from __future__ import annotations

_SPELLINGS = (
    ("gt", ("gt", "greaterThan")),
    ("geq", ("geq", "greaterOrEqual", "greaterThanOrEqual")),
    ("lt", ("lt", "lessThan")),
    ("leq", ("leq", "lessOrEqual", "lessThanOrEqual")),
)


def test_difference_resolver_recognizes_every_comparison_spelling():
    from bionetgen.atomizer.modern.events import _parse_state_difference_threshold

    for canonical, spellings in _SPELLINGS:
        for spelling in spellings:
            for trigger in (
                f"{spelling}(S4, S3)",
                f"{spelling.upper()}(S4, S3)",
            ):
                assert _parse_state_difference_threshold(trigger) == (
                    "(S4) - (S3)",
                    canonical,
                    "0",
                ), trigger


def test_affine_and_difference_resolvers_agree_on_every_spelling():
    from bionetgen.atomizer.modern.events import (
        _parse_affine_state_threshold,
        _parse_state_difference_threshold,
    )

    for _canonical, spellings in _SPELLINGS:
        for spelling in spellings:
            trigger = f"{spelling}(S4, 3)"
            # The affine resolver sees a threshold against a constant; the
            # difference resolver requires two bare symbols, so it must refuse
            # this spelling for that structural reason rather than because the
            # operator was unrecognised.
            assert _parse_affine_state_threshold(trigger) is not None, trigger
            assert _parse_state_difference_threshold(trigger) is None, trigger

    for _canonical, spellings in _SPELLINGS:
        for spelling in spellings:
            trigger = f"{spelling}(S4, S3)"
            # Both resolvers must at least recognise the operator; which one
            # wins is the caller's choice, not the spelling's business.
            assert _parse_affine_state_threshold(trigger) is not None, trigger
            assert _parse_state_difference_threshold(trigger) is not None, trigger


def test_difference_resolver_reverses_equality_through_shared_operator_table():
    from bionetgen.atomizer.modern.events import _parse_state_difference_threshold

    for canonical, spellings in _SPELLINGS:
        for spelling in spellings:
            # ``S3 > S4`` is the same threshold as ``S4 < S3`` only for the
            # affine resolver; the difference form is normalised to
            # ``(S3) - (S4)``, so check the operator it records is the
            # canonical short name regardless of how it was written.
            parsed = _parse_state_difference_threshold(f"{spelling}(S3, S4)")
            assert parsed == ("(S3) - (S4)", canonical, "0"), spelling


def test_spelled_out_difference_trigger_is_lowered_as_a_quadratic_event():
    """A spelled-out trigger now reaches the quadratic difference resolver."""
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    # Mirrors the shape of SBML Test Suite semantic/00762: a comparison
    # between two species, one of which the event assigns, with no other
    # guard to refuse the model first.
    event = SBMLEvent(
        id="spelled-out-difference",
        trigger="greaterthan(A, B)",
        assignments=[SBMLEventAssignment("P", "A * time")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda identifier: identifier == "P",
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {
                "A": 1.0,
                "B": 2.0,
            }.get(identifier),
            resolve_quadratic_rate_for_event=lambda expression, _event: (
                (-1.0, 0.0, 0.0, 1.0) if expression == "(A) - (B)" else None
            ),
            resolve_quadratic_state_values_for_event=lambda expression, value, _event: (
                {"A": 4.0, "B": 4.0}
                if expression == "(A) - (B)" and value == 0
                else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>1" in result.actions_block
    assert 'setParameter("P", "4")' in result.actions_block


def test_equality_operators_are_not_treated_as_order_comparisons():
    """``eq``/``neq`` name no order, so no threshold resolver claims them."""
    from bionetgen.atomizer.modern.events import (
        _parse_affine_state_threshold,
        _parse_state_difference_threshold,
    )

    for trigger in ("eq(S4, S3)", "neq(S4, S3)", "equal(S4, S3)"):
        assert _parse_affine_state_threshold(trigger) is None, trigger
        assert _parse_state_difference_threshold(trigger) is None, trigger
