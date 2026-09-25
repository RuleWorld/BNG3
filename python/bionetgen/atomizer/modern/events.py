"""SBML event translation for the Playground-derived atomizer.

Fixed-time, constant-valued events are lowered to executable BNGL action
phases.  State-dependent or otherwise dynamic events remain explicit
diagnostics because the BNGL action language has no general trigger scheduler.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
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
    # Only immutable SBML identifiers may be folded into scheduled actions.
    # Default keeps the older direct-call contract source-compatible.
    is_compile_time_constant: Callable[[str], bool] = lambda _identifier: True
    # Optional values for immutable species and other non-parameter symbols.
    resolve_constant: Callable[[str], Optional[float]] = lambda _identifier: None

    @property
    def resolveSpeciesPattern(self):
        return self.resolve_species_pattern

    @resolveSpeciesPattern.setter
    def resolveSpeciesPattern(self, value):
        self.resolve_species_pattern = value

    @property
    def resolveParam(self):
        return self.resolve_param

    @resolveParam.setter
    def resolveParam(self, value):
        self.resolve_param = value

    @property
    def isParam(self):
        return self.is_param

    @isParam.setter
    def isParam(self, value):
        self.is_param = value

    @property
    def isCompileTimeConstant(self):
        return self.is_compile_time_constant

    @isCompileTimeConstant.setter
    def isCompileTimeConstant(self, value):
        self.is_compile_time_constant = value

    @property
    def baseTEnd(self):
        return self.base_t_end

    @baseTEnd.setter
    def baseTEnd(self, value):
        self.base_t_end = value

    @property
    def baseSteps(self):
        return self.base_steps

    @baseSteps.setter
    def baseSteps(self, value):
        self.base_steps = value


@dataclass
class EventSet:
    kind: str
    target: str
    value: float
    variable: str


@dataclass
class EventTranslationResult:
    actions_block: Optional[str]
    converted: int
    untranslated: List[Tuple[SBMLEvent, str]]

    @property
    def actionsBlock(self):
        return self.actions_block

    @actionsBlock.setter
    def actionsBlock(self, value):
        self.actions_block = value


EventActionsResult = EventTranslationResult


def _tokenize(expression: str) -> Optional[List[str]]:
    token_pattern = re.compile(
        r"\s*("
        r"[A-Za-z_][A-Za-z0-9_]*|"
        r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
        r"[(),+\-*/^])"
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
        return value if self._finite(value) else None

    @staticmethod
    def _finite(value: object) -> bool:
        return isinstance(value, (int, float)) and math.isfinite(value)

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
        return base if self._finite(base) else None

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
            if (
                self.position + 1 < len(self.tokens)
                and self.tokens[self.position + 1] == "("
            ):
                function_name = token.lower()
                self.take()
                self.take()  # opening parenthesis
                arguments: List[float] = []
                if self.peek() != ")":
                    while True:
                        argument = self.parse_expression()
                        if argument is None:
                            return None
                        arguments.append(argument)
                        if self.peek() != ",":
                            break
                        self.take()
                if self.take() != ")":
                    return None
                unary = {
                    "abs": abs,
                    "sqrt": math.sqrt,
                    "exp": math.exp,
                    "ln": math.log,
                    "log10": math.log10,
                    "sin": math.sin,
                    "cos": math.cos,
                    "tan": math.tan,
                    "asin": math.asin,
                    "acos": math.acos,
                    "atan": math.atan,
                    "sinh": math.sinh,
                    "cosh": math.cosh,
                    "tanh": math.tanh,
                    "floor": math.floor,
                    "ceil": math.ceil,
                }
                try:
                    comparisons = {
                        "lt": lambda a, b: a < b,
                        "leq": lambda a, b: a <= b,
                        "gt": lambda a, b: a > b,
                        "geq": lambda a, b: a >= b,
                        "eq": lambda a, b: a == b,
                        "neq": lambda a, b: a != b,
                    }
                    if function_name in comparisons and len(arguments) == 2:
                        return float(comparisons[function_name](*arguments))
                    if function_name == "and" and arguments:
                        return float(all(value != 0 for value in arguments))
                    if function_name == "or" and arguments:
                        return float(any(value != 0 for value in arguments))
                    if function_name == "not" and len(arguments) == 1:
                        return float(arguments[0] == 0)
                    if function_name in unary and len(arguments) == 1:
                        value = unary[function_name](arguments[0])
                    elif function_name == "log" and len(arguments) == 1:
                        value = math.log10(arguments[0])
                    elif function_name == "log" and len(arguments) == 2:
                        value = math.log(arguments[1], arguments[0])
                    elif function_name in {"pow", "power"} and len(arguments) == 2:
                        value = arguments[0] ** arguments[1]
                    elif function_name == "root" and len(arguments) == 2:
                        value = arguments[1] ** (1 / arguments[0])
                    elif function_name == "sec" and len(arguments) == 1:
                        value = 1 / math.cos(arguments[0])
                    elif function_name == "csc" and len(arguments) == 1:
                        value = 1 / math.sin(arguments[0])
                    elif function_name == "cot" and len(arguments) == 1:
                        value = 1 / math.tan(arguments[0])
                    else:
                        return None
                except (ArithmeticError, OverflowError, TypeError, ValueError):
                    return None
                return value if self._finite(value) else None
            self.take()
            value = self.resolve(token)
            return value if value is not None and self._finite(value) else None
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


def _parse_scaled_time_threshold(trigger: str) -> Optional[Tuple[str, str]]:
    """Solve ``time / positive_constant > threshold`` for ``time``."""

    match = re.match(
        r"^(?:geq|gt)\s*\(\s*\(?\s*time\s*/\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*,\s*(.+)\)\s*$",
        str(trigger or "").strip(),
        re.IGNORECASE,
    )
    if match is None:
        return None
    scale_identifier = match.group(1)
    threshold = _strip_outer_parens(_balanced_inner(match.group(2)))
    return f"({threshold}) * ({scale_identifier})", scale_identifier


def _event_assignment(assignment: object) -> Tuple[str, str]:
    if isinstance(assignment, Mapping):
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

    def fold(expression: str, time_value: Optional[float] = None) -> Optional[float]:
        if time_value is not None:
            expression = re.sub(
                r"\btime\b", _format_number(time_value), expression, flags=re.IGNORECASE
            )
        def resolve(identifier: str) -> Optional[float]:
            if context.is_compile_time_constant(identifier):
                value = context.resolve_param(identifier)
                if value is not None:
                    return value
            return context.resolve_constant(identifier)

        return fold_numeric(expression, resolve)

    for event in events:
        threshold = parse_time_threshold(event.trigger)
        scale_identifier: Optional[str] = None
        if threshold is None:
            scaled_threshold = _parse_scaled_time_threshold(event.trigger)
            if scaled_threshold is not None:
                threshold, scale_identifier = scaled_threshold
                scale = (
                    context.resolve_param(scale_identifier)
                    if context.is_compile_time_constant(scale_identifier)
                    else None
                )
                if scale is None or not math.isfinite(scale) or scale <= 0:
                    untranslated.append(
                        (
                            event,
                            f'time scale "{scale_identifier}" is not a positive constant',
                        )
                    )
                    continue
        if threshold is None:
            constant_trigger = fold(event.trigger)
            if constant_trigger is not None and constant_trigger in {0, 1}:
                # A time-invariant trigger fires only when SBML's declared
                # pre-simulation trigger value is false and the actual value
                # at t=0 is true. A permanently false trigger never fires.
                if constant_trigger == 0 or event.trigger_initial_value:
                    continue
                threshold = "0"
            else:
                untranslated.append(
                    (
                        event,
                        "trigger is not a simple time threshold (state-dependent "
                        "triggers cannot be scheduled)",
                    )
                )
                continue
        trigger_time = fold(threshold)
        if trigger_time is None:
            untranslated.append(
                (
                    event,
                    f'trigger time "{threshold}" does not reduce to a constant',
                )
            )
            continue
        execution_time = trigger_time
        if event.delay:
            delay = fold(event.delay, trigger_time)
            if delay is None:
                untranslated.append(
                    (
                        event,
                        f'delay "{event.delay}" is not constant',
                    )
                )
                continue
            execution_time += delay

        sets: List[Tuple[str, str, float]] = []
        failure: Optional[str] = None
        for assignment in event.assignments:
            variable, expression = _event_assignment(assignment)
            evaluation_time = (
                trigger_time
                if event.use_values_from_trigger_time
                else execution_time
            )
            value = fold(expression, evaluation_time)
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
            folded_priority = fold(event.priority or "", execution_time)
            if folded_priority is None:
                untranslated.append(
                    (
                        event,
                        f'priority "{event.priority}" is not compile-time constant',
                    )
                )
                continue
            priority = folded_priority
        scheduled.append((execution_time, sets, priority))

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
        # JavaScript Math.round rounds nonnegative half ties upward; Python round ties to even.
        return max(1, math.floor(context.base_steps * scale + 0.5))

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


foldNumeric = fold_numeric
parseTimeThreshold = parse_time_threshold
synthesizeEventActions = synthesize_event_actions


__all__ = [
    "EventActionsResult",
    "EventSet",
    "EventTranslationContext",
    "EventTranslationResult",
    "foldNumeric",
    "fold_numeric",
    "parseTimeThreshold",
    "parse_time_threshold",
    "synthesizeEventActions",
    "synthesize_event_actions",
]
