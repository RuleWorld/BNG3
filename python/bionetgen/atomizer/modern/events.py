"""Safe SBML event translation for the Playground-derived atomizer.

The simulation engine has no general trigger executor.  The Playground port
therefore translates only fixed-time, constant-valued events into BNGL action
phases and records every other event as an explicit diagnostic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from .types import SBMLEvent
from .types import standardize_name


@dataclass
class EventTranslationContext:
    """Callbacks and simulation defaults needed for event translation."""

    resolve_species_pattern: Callable[[str], Optional[str]]
    resolve_param: Callable[[str], Optional[float]]
    is_param: Callable[[str], bool]
    method: str = "ode"
    base_t_end: float = 10
    base_steps: int = 100


@dataclass
class EventTranslationResult:
    actions_block: Optional[str]
    converted: int
    untranslated: List[Tuple[SBMLEvent, str]]


def _tokenize(expression: str) -> Optional[List[str]]:
    token_pattern = re.compile(
        r"\s*("
        r"[A-Za-z_][A-Za-z0-9_]*|"
        r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
        r"[()+\-*/^])"
    )
    tokens: List[str] = []
    position = 0
    while position < len(expression):
        match = token_pattern.match(expression, position)
        if match is None:
            if expression[position:].strip():
                return None
            break
        tokens.append(match.group(1))
        position = match.end()
    return tokens


class _NumericParser:
    def __init__(
        self, tokens: Sequence[str], resolve: Callable[[str], Optional[float]]
    ) -> None:
        self.tokens = list(tokens)
        self.resolve = resolve
        self.position = 0

    def peek(self) -> Optional[str]:
        if self.position >= len(self.tokens):
            return None
        return self.tokens[self.position]

    def take(self) -> Optional[str]:
        token = self.peek()
        if token is not None:
            self.position += 1
        return token

    def parse(self) -> Optional[float]:
        value = self.parse_expression()
        if value is None or self.position != len(self.tokens):
            return None
        return value if math.isfinite(value) else None

    def parse_expression(self) -> Optional[float]:
        left = self.parse_term()
        if left is None:
            return None
        while self.peek() in {"+", "-"}:
            operator = self.take()
            right = self.parse_term()
            if right is None:
                return None
            left = left + right if operator == "+" else left - right
        return left

    def parse_term(self) -> Optional[float]:
        left = self.parse_factor()
        if left is None:
            return None
        while self.peek() in {"*", "/"}:
            operator = self.take()
            right = self.parse_factor()
            if right is None or (operator == "/" and right == 0):
                return None
            left = left * right if operator == "*" else left / right
        return left

    def parse_factor(self) -> Optional[float]:
        base = self.parse_unary()
        if base is None:
            return None
        if self.peek() == "^":
            self.take()
            exponent = self.parse_factor()
            if exponent is None:
                return None
            try:
                base = base**exponent
            except (OverflowError, ValueError):
                return None
        return base if math.isfinite(base) else None

    def parse_unary(self) -> Optional[float]:
        if self.peek() == "+":
            self.take()
            return self.parse_unary()
        if self.peek() == "-":
            self.take()
            value = self.parse_unary()
            return -value if value is not None else None
        return self.parse_primary()

    def parse_primary(self) -> Optional[float]:
        token = self.peek()
        if token is None:
            return None
        if token == "(":
            self.take()
            value = self.parse_expression()
            if value is None or self.take() != ")":
                return None
            return value
        if re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token):
            self.take()
            value = float(token)
            return value if math.isfinite(value) else None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            # Function calls are intentionally not folded.  This keeps the
            # action translation fail-closed for unknown or dynamic functions.
            if (
                self.position + 1 < len(self.tokens)
                and self.tokens[self.position + 1] == "("
            ):
                return None
            self.take()
            value = self.resolve(token)
            return value if value is not None and math.isfinite(value) else None
        return None


def fold_numeric(
    expression: str, resolve: Callable[[str], Optional[float]]
) -> Optional[float]:
    """Evaluate a small constant arithmetic language without ``eval``."""

    if not expression or not expression.strip():
        return None
    tokens = _tokenize(expression)
    if not tokens:
        return None
    return _NumericParser(tokens, resolve).parse()


def _strip_outer_parens(value: str) -> str:
    result = value.strip()
    while result.startswith("(") and result.endswith(")"):
        depth = 0
        balanced = True
        for index, character in enumerate(result):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(result) - 1:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        result = result[1:-1].strip()
    return result


def _drop_unmatched_trailing_paren(value: str) -> str:
    result = value.strip()
    while result.endswith(")") and result.count(")") > result.count("("):
        result = result[:-1].rstrip()
    return result


def _balanced_inner(value: str) -> str:
    depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                return value[:index].strip()
            depth -= 1
    return value.strip()


def parse_time_threshold(trigger: str) -> Optional[str]:
    """Return the threshold from a simple ``time >= threshold`` trigger."""

    if not trigger:
        return None
    value = trigger.strip()
    match = re.match(r"^(?:geq|gt)\s*\(\s*time\s*,\s*(.+)\)\s*$", value, re.IGNORECASE)
    if match:
        return _strip_outer_parens(_balanced_inner(match.group(1)))
    match = re.match(
        r"^(?:leq|lt)\s*\(\s*(.+?)\s*,\s*time\s*\)\s*$",
        value,
        re.IGNORECASE,
    )
    if match:
        return _strip_outer_parens(match.group(1))
    match = re.match(
        r"^\(?\s*time\s*(?:>=|>)\s*(.+?)\s*\)?$",
        value,
        re.IGNORECASE,
    )
    if match:
        return _strip_outer_parens(_drop_unmatched_trailing_paren(match.group(1)))
    match = re.match(
        r"^\(?\s*(.+?)\s*(?:<=|<)\s*time\s*\)?$",
        value,
        re.IGNORECASE,
    )
    if match:
        return _strip_outer_parens(_drop_unmatched_trailing_paren(match.group(1)))
    return None


def _event_assignment(assignment: object) -> Tuple[str, str]:
    if isinstance(assignment, dict):
        return str(assignment.get("variable", "")), str(assignment.get("math", ""))
    if isinstance(assignment, (tuple, list)) and len(assignment) >= 2:
        return str(assignment[0]), str(assignment[1])
    return "", ""


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(float(f"{value:.12g}"))


def _render_set(kind: str, target: str, value: float) -> str:
    command = "setConcentration" if kind == "conc" else "setParameter"
    return f'{command}("{target}", "{_format_number(value)}")'


def synthesize_event_actions(
    events: Sequence[SBMLEvent], context: EventTranslationContext
) -> EventTranslationResult:
    """Translate safe fixed-time events and report all rejected events."""

    untranslated: List[Tuple[SBMLEvent, str]] = []
    scheduled: List[Tuple[float, List[Tuple[str, str, float]], float]] = []

    for event in events:
        threshold = parse_time_threshold(event.trigger)
        if threshold is None:
            untranslated.append(
                (
                    event,
                    "trigger is not a simple time threshold (state-dependent "
                    "triggers cannot be scheduled)",
                )
            )
            continue
        time = fold_numeric(threshold, context.resolve_param)
        if time is None:
            untranslated.append(
                (
                    event,
                    f'trigger time "{threshold}" does not reduce to a constant',
                )
            )
            continue
        if event.delay:
            delay = fold_numeric(event.delay, context.resolve_param)
            if delay is None:
                untranslated.append(
                    (
                        event,
                        f'delay "{event.delay}" is not constant',
                    )
                )
                continue
            time += delay

        sets: List[Tuple[str, str, float]] = []
        failure: Optional[str] = None
        for assignment in event.assignments:
            variable, expression = _event_assignment(assignment)
            value = fold_numeric(expression, context.resolve_param)
            if value is None:
                failure = (
                    f'assignment "{variable} := {expression}" is not constant '
                    "(depends on species/time or a function)"
                )
                break
            pattern = context.resolve_species_pattern(variable)
            if pattern:
                sets.append(("conc", pattern, value))
            elif context.is_param(variable):
                sets.append(("param", standardize_name(variable), value))
            else:
                failure = (
                    f' assignment target "{variable}" is neither a known species '
                    "nor a parameter"
                ).lstrip()
                break
        if failure is not None:
            untranslated.append((event, failure))
            continue

        priority = 0.0
        if getattr(event, "priority", None):
            folded_priority = fold_numeric(event.priority or "", context.resolve_param)
            if folded_priority is not None:
                priority = folded_priority
        scheduled.append((time, sets, priority))

    if not scheduled:
        return EventTranslationResult(None, 0, untranslated)

    scheduled.sort(key=lambda item: (item[0], -item[2]))
    merged: List[Tuple[float, List[Tuple[str, str, float]]]] = []
    for time, sets, _priority in scheduled:
        if merged and abs(merged[-1][0] - time) < 1e-12:
            merged[-1][1].extend(sets)
        else:
            merged.append((time, list(sets)))

    last_fire = merged[-1][0]
    t_final = (
        context.base_t_end if context.base_t_end > last_fire else last_fire * 1.5 + 1
    )
    method = context.method or "ode"
    boundaries = [0.0]
    boundaries.extend(time for time, _sets in merged if time > 0)
    boundaries.append(t_final)
    boundaries = [
        value
        for index, value in enumerate(boundaries)
        if index == 0 or value > boundaries[index - 1]
    ]
    total_duration = t_final - boundaries[0]

    def steps_for(start: float, end: float) -> int:
        scale = (end - start) / total_duration if total_duration > 0 else 1
        return max(1, round(context.base_steps * scale))

    lines = [
        f"# {len(merged)} time-triggered SBML event(s) translated to scheduled actions.",
        "generate_network({overwrite=>1})",
    ]
    for time, sets in merged:
        if time <= 0:
            lines.extend(
                _render_set(kind, target, value) for kind, target, value in sets
            )

    phase_start = 0.0
    first = True
    for end in boundaries[1:]:
        steps = steps_for(phase_start, end)
        if first:
            lines.append(
                f'simulate({{method=>"{method}", t_start=>0, '
                f"t_end=>{_format_number(end)}, n_steps=>{steps}}})"
            )
            first = False
        else:
            lines.append(
                f'simulate({{continue=>1, method=>"{method}", '
                f"t_end=>{_format_number(end)}, n_steps=>{steps}}})"
            )
        for time, sets in merged:
            if time > 0 and abs(time - end) < 1e-12:
                lines.extend(
                    _render_set(kind, target, value) for kind, target, value in sets
                )
        phase_start = end

    if abs(phase_start - t_final) > 1e-12:
        lines.append(
            f'simulate({{continue=>1, method=>"{method}", '
            f"t_end=>{_format_number(t_final)}, "
            f"n_steps=>{steps_for(phase_start, t_final)}}})"
        )

    return EventTranslationResult("\n".join(lines), len(scheduled), untranslated)


__all__ = [
    "EventTranslationContext",
    "EventTranslationResult",
    "fold_numeric",
    "parse_time_threshold",
    "synthesize_event_actions",
]
