"""Every trigger resolver must accept every spelling of a comparison.

MathML content markup lowers a relational operator to a short name (``gt``,
``geq``, ``lt``, ``leq`` -- see ``_mathml_to_formula`` in ``parser.py``), while a
trigger arriving through a ``formula`` attribute or a non-MathML producer keeps
the spelled-out name (``greaterThan``, ``lessOrEqual``, ...).  Both spellings
name the same comparison, so a resolver that accepts one must accept the other
*with the same answer*.  Accepting only one spelling is not a harmless
difference: ``validate_sbml_test_suite.py`` reads a ``dropped`` warning as a
simulation limitation, so a trigger refused for its spelling alone is reported
as a model that cannot be simulated.

This module walks every comparison-recognition site in
``bionetgen/atomizer/modern/events.py`` with the short spelling and with each
spelled-out alias, and asserts the two agree.
"""

from __future__ import annotations

import math
import re

import pytest

from bionetgen.atomizer.modern import events as E
from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment, SBMLRule

#: Canonical short relation name -> every alias that must name the same thing.
_SPELLINGS = {
    "gt": ("gt", "greaterThan"),
    "geq": ("geq", "greaterOrEqual", "greaterThanOrEqual"),
    "lt": ("lt", "lessThan"),
    "leq": ("leq", "lessOrEqual", "lessThanOrEqual"),
}

_ALL_SPELLINGS = tuple(
    spelling for canonical in _SPELLINGS for spelling in _SPELLINGS[canonical]
)

_ALIASES = {name: name for name in _SPELLINGS}
for _canonical, _spellings in _SPELLINGS.items():
    for _spelling in _spellings:
        _ALIASES[_spelling.lower()] = _canonical

#: Longest alias first so ``greaterthan`` never shadows ``greaterthanorequal``.
_ALIAS_PATTERN = "|".join(sorted(_ALIASES, key=len, reverse=True))


def _fold_nothing(_term):
    return None


def _canonicalize(value):
    """Fold spelled-out relation names in ``value`` back to their short name.

    A few sites hand the *caller's* trigger text back to the caller rather than
    a canonical operator, so two spellings of the same trigger legitimately
    produce two different strings.  Comparing them after this substitution tests
    the parse -- structure, operand order and direction -- rather than the
    spelling the caller happened to type.
    """
    if isinstance(value, str):
        return re.sub(
            rf"\b({_ALIAS_PATTERN})\b",
            lambda match: _ALIASES.get(match.group(0).lower(), match.group(0)),
            value,
            flags=re.IGNORECASE,
        )
    if isinstance(value, tuple):
        return tuple(_canonicalize(item) for item in value)
    return value


def _render(template, operators):
    return template % {f"o{index + 1}": name for index, name in enumerate(operators)}


def _assert_site_agrees(label, probe, cases):
    """For each case, every alias must give the short spelling's answer.

    ``cases`` are ``(template, operators)`` pairs, where the template uses
    ``%(o1)s``/``%(o2)s`` placeholders for the relation names.  At least one
    case must be recognised in short spelling, so a site that refuses
    everything cannot pass by comparing ``None`` to ``None``.
    """
    recognised = 0
    for template, canonical in cases:
        baseline = probe(_render(template, canonical))
        if baseline is not None:
            recognised += 1
        for index, operator in enumerate(canonical):
            for spelling in _SPELLINGS[operator]:
                operators = list(canonical)
                operators[index] = spelling
                spelled = probe(_render(template, operators))
                assert _canonicalize(spelled) == _canonicalize(baseline), (
                    f"{label}: {spelling} disagrees with {operator} on "
                    f"{_render(template, canonical)}\n"
                    f"  short   -> {baseline!r}\n"
                    f"  spelled -> {spelled!r}"
                )
    assert recognised, f"{label}: no case is recognised even in short spelling"


def _parse_scaled(trigger):
    return E._parse_scaled_state_threshold(trigger, lambda _scale: 1.0)


# Each entry is (label, probe, cases).
_RESOLVER_SITES = [
    (
        "parse_time_threshold (:981, time on the left)",
        E.parse_time_threshold,
        [("%(o1)s(time, 5)", ("gt",))],
    ),
    (
        "parse_time_threshold (:988, time on the right)",
        E.parse_time_threshold,
        [("%(o1)s(5, time)", ("lt",))],
    ),
    (
        "_parse_time_window (:1060)",
        E._parse_time_window,
        [("and(%(o1)s(time, 5), %(o1)s(time, 9))", ("gt",))],
    ),
    (
        "_parse_gated_time_window (:1089)",
        lambda trigger: E._parse_gated_time_window(trigger, _fold_nothing),
        [("and(%(o1)s(time, 5), %(o1)s(time, 9))", ("gt",))],
    ),
    (
        "_parse_scaled_time_threshold (:1144)",
        E._parse_scaled_time_threshold,
        [("%(o1)s((time / tc), 3)", ("gt",))],
    ),
    (
        "_parse_affine_state_threshold (:1199)",
        E._parse_affine_state_threshold,
        [("%(o1)s(A, 3)", ("gt",)), ("%(o1)s(3, A)", ("leq",))],
    ),
    (
        "_parse_state_difference_threshold (:2207)",
        E._parse_state_difference_threshold,
        [("%(o1)s(A, B)", ("gt",))],
    ),
    (
        "_parse_gated_affine_state_threshold (:2241)",
        lambda trigger: E._parse_gated_affine_state_threshold(trigger, _fold_nothing),
        [("and(%(o1)s(time, 5), %(o1)s(A, 3))", ("gt",))],
    ),
    (
        "_parse_delayed_affine_state_interval (:2299, direct)",
        E._parse_delayed_affine_state_interval,
        [("and(%(o1)s(delay(A, 2), 1), %(o2)s(delay(A, 2), 9))", ("gt", "lt"))],
    ),
    (
        "_parse_delayed_affine_state_interval (:2299, reversed)",
        E._parse_delayed_affine_state_interval,
        [("and(%(o1)s(1, delay(A, 2)), %(o2)s(9, delay(A, 2)))", ("gt", "lt"))],
    ),
    (
        "_parse_rate_of_state_threshold (:2344, direct)",
        E._parse_rate_of_state_threshold,
        [("%(o1)s(rateOf(B), A)", ("gt",))],
    ),
    (
        "_parse_rate_of_state_threshold (:2344, reversed)",
        E._parse_rate_of_state_threshold,
        [("%(o1)s(A, rateOf(B))", ("gt",))],
    ),
    (
        "_parse_scaled_state_threshold (:2367, direct)",
        _parse_scaled,
        [("%(o1)s(A, 3)", ("gt",))],
    ),
    (
        "_parse_scaled_state_threshold (:2367, reversed)",
        _parse_scaled,
        [("%(o1)s(7, 3 * A)", ("gt",))],
    ),
    (
        "_parse_periodic_reset_trigger (:2488)",
        E._parse_periodic_reset_trigger,
        [("%(o1)s(time - reset, 3)", ("geq",))],
    ),
    (
        "fold_numeric comparison evaluation (:807)",
        lambda trigger: E.fold_numeric(trigger, lambda _name: 1.0),
        [("%(o1)s(k, 1)", ("gt",)), ("%(o1)s(k, 5)", ("lt",))],
    ),
]


@pytest.mark.parametrize(
    "label, probe, cases",
    _RESOLVER_SITES,
    ids=[site[0] for site in _RESOLVER_SITES],
)
def test_resolver_accepts_every_comparison_spelling(label, probe, cases):
    _assert_site_agrees(label, probe, cases)


# --------------------------------------------------------------------------
# Sites that are not module-level resolvers are driven through the public
# entry point that contains them, so the check still exercises the real site.
# --------------------------------------------------------------------------


def _static_parameter_trigger(trigger):
    event = SBMLEvent(
        id="e", trigger=trigger, assignments=[SBMLEventAssignment("P", "1")]
    )
    compiled = E.expand_static_parameter_event_system(
        [event],
        t_end=20.0,
        parameter_ids=["p", "P"],
        resolve_initial=lambda identifier: {"p": 1.0, "P": 0.0}.get(identifier),
        affine_rate_parameters={"p": 2.0},
    )
    if compiled is None:
        return "<refused>"
    return compiled[0].trigger if compiled and compiled[0] is not event else "<kept>"


def _cosh_rewritten_trigger(trigger):
    rule = SBMLRule(type="assignment", variable="C", math="cosh(time)")
    event = SBMLEvent(
        id="e", trigger=trigger, assignments=[SBMLEventAssignment("P", "1")]
    )
    output = E.expand_cosh_assignment_rule_events(
        [event], [rule], resolve_constant=lambda _identifier: None
    )
    return output[0].trigger if output and output[0] is not event else "<kept>"


def _horizon_proof(spelling):
    """Drive ``provably_false_in_horizon`` (:4107) through the translator."""
    periodic = SBMLEvent(
        id="periodic",
        trigger="geq(minus(time, reset), 1)",
        assignments=[
            SBMLEventAssignment("reset", "time"),
            SBMLEventAssignment("k", "k + 1"),
        ],
    )
    gated = SBMLEvent(
        id="gated",
        trigger=f"and({spelling}(time, 100), geq(k, 1))",
        assignments=[SBMLEventAssignment("done", "1")],
    )
    initial = {"reset": 0, "k": 0, "done": 0}
    result = E.synthesize_event_actions(
        [periodic, gated],
        E.EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda identifier: identifier in initial,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=initial.get,
            base_t_end=2.5,
            base_steps=10,
        ),
    )
    return (
        result.converted,
        tuple(sorted(event.id for event, _reason in result.untranslated)),
    )


def _absolute_threshold_proof(spelling):
    """Drive the ``abs`` absolute-threshold site (:4235) through the translator."""
    increment_q = SBMLEvent(
        id="increment-q",
        trigger="geq(reset, 0.01)",
        trigger_initial_value=True,
        trigger_persistent=False,
        priority="1",
        assignments=[
            SBMLEventAssignment("reset", "0"),
            SBMLEventAssignment("Q", "Q + 0.01"),
        ],
    )
    increment_r = SBMLEvent(
        id="increment-r",
        trigger="geq(reset, 0.01)",
        trigger_initial_value=True,
        trigger_persistent=False,
        priority="1",
        assignments=[
            SBMLEventAssignment("reset", "0"),
            SBMLEventAssignment("R", "R + 0.01"),
        ],
    )
    threshold = SBMLEvent(
        id="state-threshold",
        trigger=f"{spelling}(abs(S2), 0.1)",
        assignments=[SBMLEventAssignment("error", "1")],
    )
    initial = {"reset": 0, "Q": 1, "R": 1, "S2": 0, "error": 0}
    result = E.synthesize_event_actions(
        [increment_q, increment_r, threshold],
        E.EventTranslationContext(
            resolve_species_pattern=lambda identifier: (
                "S2()" if identifier == "S2" else None
            ),
            resolve_param=lambda _identifier: None,
            is_param=lambda identifier: identifier in {"reset", "Q", "R", "error"},
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=initial.get,
            resolve_rate_reset=lambda identifier: (
                (0.0, 1.0) if identifier == "reset" else None
            ),
            resolve_rate_rule_expression_for_event=lambda identifier, _event: (
                "Q - R" if identifier == "S2" else None
            ),
            base_t_end=0.025,
            base_steps=10,
        ),
    )
    return (
        result.converted,
        tuple(sorted(event.id for event, _reason in result.untranslated)),
    )


def test_static_parameter_time_edge_accepts_every_spelling():
    """``parse_time_edge`` (:1749) drives the static-parameter compiler."""
    _assert_site_agrees(
        "parse_time_edge (:1749)",
        _static_parameter_trigger,
        [("%(o1)s(time, 5)", ("gt",)), ("%(o1)s(5, time)", ("lt",))],
    )


def test_static_parameter_affine_state_edge_accepts_every_spelling():
    """``parse_affine_state_edge`` (:1786) reverses its operator at :1806."""
    _assert_site_agrees(
        "parse_affine_state_edge (:1786)",
        _static_parameter_trigger,
        [("%(o1)s(p, 5)", ("gt",)), ("%(o1)s(5, p)", ("lt",))],
    )


def test_cosh_rewriter_accepts_every_spelling():
    """``expand_cosh_assignment_rule_events`` (:1473) reverses at :1519."""
    _assert_site_agrees(
        "expand_cosh_assignment_rule_events (:1473)",
        _cosh_rewritten_trigger,
        [
            ("%(o1)s(2, cosh(time))", ("lt",)),
            ("%(o1)s(2, cosh(time))", ("leq",)),
            ("%(o1)s(cosh(time), 2)", ("gt",)),
            ("%(o1)s(cosh(time), 2)", ("geq",)),
        ],
    )


def test_horizon_proof_accepts_every_spelling():
    """``provably_false_in_horizon`` (:4107) proves a time gate unreachable."""
    _assert_site_agrees(
        "provably_false_in_horizon (:4107)", _horizon_proof, [("%(o1)s", ("gt",))]
    )


def test_absolute_threshold_proof_accepts_every_spelling():
    """The ``abs`` rate-rule threshold site (:4235) accepts both spellings."""
    _assert_site_agrees(
        "absolute threshold (:4235)",
        _absolute_threshold_proof,
        [("%(o1)s", ("geq",)), ("%(o1)s", ("gt",))],
    )


def _periodic_gate(spelling):
    """Drive the gate reserved-name filter (:4415) through the translator."""
    increment_q = SBMLEvent(
        id="increment-q",
        trigger="geq(reset, 0.01)",
        trigger_initial_value=True,
        trigger_persistent=False,
        priority="1",
        assignments=[
            SBMLEventAssignment("reset", "0"),
            SBMLEventAssignment("Q", "Q + 0.01"),
        ],
    )
    increment_r = SBMLEvent(
        id="increment-r",
        trigger="geq(reset, 0.01)",
        trigger_initial_value=True,
        trigger_persistent=False,
        priority="1",
        assignments=[
            SBMLEventAssignment("reset", "0"),
            SBMLEventAssignment("R", "R + 0.01"),
        ],
    )
    update_maxdiff = SBMLEvent(
        id="update-maxdiff",
        trigger="gt(abs(Q - R), maxdiff)",
        assignments=[SBMLEventAssignment("maxdiff", "abs(Q - R)")],
    )
    gated = SBMLEvent(
        id="time-gated-error",
        trigger=f"and(geq(time, 0.02), {spelling}(maxdiff, 0.2))",
        assignments=[SBMLEventAssignment("error", "1")],
    )
    initial = {"reset": 0, "Q": 1, "R": 1, "maxdiff": 0, "error": 0}
    result = E.synthesize_event_actions(
        [increment_q, increment_r, update_maxdiff, gated],
        E.EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda identifier: identifier in initial,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=initial.get,
            resolve_rate_reset=lambda identifier: (
                (0.0, 1.0) if identifier == "reset" else None
            ),
            base_t_end=0.025,
            base_steps=10,
        ),
    )
    return (
        result.converted,
        tuple(sorted(event.id for event, _reason in result.untranslated)),
    )


def test_periodic_gate_accepts_every_spelling():
    """A spelled-out relation in a gate is a built-in, not a model symbol."""
    _assert_site_agrees(
        "periodic gate reserved-name filter (:4415)",
        _periodic_gate,
        [("%(o1)s", ("lt",)), ("%(o1)s", ("leq",))],
    )


def test_every_comparison_spelling_is_covered_by_a_site():
    """A spelling with no site probe would silently stop being checked."""
    probed = set()
    for _label, _probe, cases in _RESOLVER_SITES:
        for _template, operators in cases:
            for operator in operators:
                probed.update(_SPELLINGS[operator])
    assert set(_ALL_SPELLINGS) <= probed


# --------------------------------------------------------------------------
# Direction.  The reversing sites are the only places where a wrong answer
# silently flips a trigger, so each is checked by comparing the *meaning* of
# the original trigger with the meaning of the rewritten one over a sweep of
# times, not by comparing strings.
# --------------------------------------------------------------------------


def _holds(trigger, time_value):
    """Evaluate a two-term numeric trigger such as ``lt(2, cosh(time))``."""
    body = trigger.strip()
    opening = body.find("(")
    assert opening > 0 and body.endswith(")"), trigger
    operator, arguments_text = body[:opening], body[opening + 1 : -1]
    arguments = E._split_arguments(arguments_text)
    assert arguments is not None and len(arguments) == 2, trigger
    environment = {"__builtins__": {}, "cosh": math.cosh, "time_value": time_value}
    values = [re.sub(r"\btime\b", "time_value", argument) for argument in arguments]
    left, right = (eval(operand, environment) for operand in values)
    return {
        "gt": left > right,
        "geq": left >= right,
        "lt": left < right,
        "leq": left <= right,
    }[_canonicalize(operator)]


_TIMES = tuple(index / 40.0 for index in range(41))


@pytest.mark.parametrize("spelling", _SPELLINGS["lt"] + _SPELLINGS["leq"])
def test_cosh_rewrite_of_a_reversed_trigger_keeps_its_direction(spelling):
    """``threshold <op> cosh(time)`` means the same set of times rewritten.

    This is the reversing site: ``X <op> cosh(time)`` is ``cosh(time) <rev op> X``,
    and ``acosh`` is strictly increasing on ``[0, inf)``, so the time bound keeps
    that direction.  Comparing truth values over a sweep of times is the only
    assertion that notices an inversion -- both spellings would otherwise
    stringify identically.
    """
    original = f"{spelling}(2, cosh(time))"
    rewritten = _cosh_rewritten_trigger(original)
    assert rewritten not in {"<kept>", "<refused>"}, f"{spelling} was not rewritten"

    for time_value in _TIMES:
        assert _holds(original, time_value) == _holds(
            rewritten, time_value
        ), f"{original} -> {rewritten} differs at t={time_value}"


@pytest.mark.parametrize("spelling", _SPELLINGS["gt"] + _SPELLINGS["geq"])
def test_cosh_rewrite_of_a_direct_trigger_keeps_its_direction(spelling):
    """``cosh(time) <op> threshold`` is already in bound-on-the-left form."""
    original = f"{spelling}(cosh(time), 2)"
    rewritten = _cosh_rewritten_trigger(original)
    assert rewritten not in {"<kept>", "<refused>"}, f"{spelling} was not rewritten"

    for time_value in _TIMES:
        assert _holds(original, time_value) == _holds(
            rewritten, time_value
        ), f"{original} -> {rewritten} differs at t={time_value}"


@pytest.mark.parametrize("canonical", sorted(_SPELLINGS))
def test_reversing_resolvers_report_the_reversed_operator(canonical):
    """A reversed-argument trigger yields the mirrored relation name."""
    expected = {"gt": "lt", "geq": "leq", "lt": "gt", "leq": "geq"}[canonical]
    other = "gt" if expected in {"lt", "leq"} else "lt"

    assert E._parse_rate_of_state_threshold(f"{canonical}(A, rateOf(B))") == (
        "B",
        expected,
        "A",
    )
    assert _parse_scaled(f"{canonical}(7, 3 * A)") == (
        "A",
        expected,
        "7",
        "(3) * (1)",
    )
    assert E._parse_affine_state_threshold(f"{canonical}(3, A)") == ("A", expected, "3")
    parsed = E._parse_delayed_affine_state_interval(
        f"and({canonical}(1, delay(A, 2)), {other}(delay(A, 2), 9))"
    )
    assert parsed is not None
    assert parsed[2][0] == (expected, "1")


def test_reversed_operator_table_cannot_key_error():
    """Every canonical relation reverses to another canonical relation."""
    assert set(E._REVERSED_COMPARISON_OPERATOR) == {"gt", "geq", "lt", "leq"}
    for operator, reversed_operator in E._REVERSED_COMPARISON_OPERATOR.items():
        assert E._REVERSED_COMPARISON_OPERATOR[reversed_operator] == operator


def test_alias_pattern_prefers_the_longest_name():
    """``greaterThanOrEqual`` must win over ``greaterThan``."""
    assert E._match_comparison_call("greaterThanOrEqual(A, 1)") == ("geq", "A, 1")
    assert E._match_comparison_call("greaterOrEqual(A, 1)") == ("geq", "A, 1")
    assert E._match_comparison_call("greaterThan(A, 1)") == ("gt", "A, 1")
    assert E._match_comparison_call("lessThanOrEqual(A, 1)") == ("leq", "A, 1")
    assert E._match_comparison_call("GREATERTHAN(A, 1)") == ("gt", "A, 1")


def test_equality_stays_out_of_the_order_alias_table():
    """``eq``/``neq`` name no order, so no order resolver claims them."""
    for trigger in ("eq(A, 1)", "neq(A, 1)", "equal(A, 1)", "notEqual(A, 1)"):
        assert E._match_comparison_call(trigger) is None, trigger
