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
    # Inline pure SBML function definitions before folding fixed-time events.
    expand_functions: Callable[[str], str] = lambda expression: expression
    is_compartment: Callable[[str], bool] = lambda _identifier: False
    # Initial values can determine a trigger's t=0 rising edge even when the
    # referenced symbol changes later. This callback is used only for that
    # edge and immediate assignment values, never for later schedule times.
    resolve_initial_value: Callable[[str], Optional[float]] = lambda _identifier: None
    # Return (initial value, constant derivative) only for independently
    # affine states. Used to solve simple one-variable threshold crossings.
    resolve_affine_rate: Callable[[str], Optional[Tuple[float, float]]] = (
        lambda _identifier: None
    )
    # Event-local affine proof may ignore that event's own future assignment
    # while rejecting every other controller of the state.
    resolve_affine_rate_for_event: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float]]
    ] = lambda _identifier, _event: None
    # Return (initial value, exponent) for independently exponential states
    # whose exact trajectory is initial * exp(exponent * time).
    resolve_exponential_rate: Callable[[str], Optional[Tuple[float, float]]] = (
        lambda _identifier: None
    )
    # Allow periodic reset lowering to inspect a constant rate-rule state even
    # when the event itself assigns that state.
    resolve_rate_reset: Callable[[str], Optional[Tuple[float, float]]] = (
        lambda _identifier: None
    )
    # True only when the model has no reactions, rules, or initial assignments;
    # event-local mutable symbols then remain at their initial values unless
    # an event fires.
    static_event_state: bool = False

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
                arguments: List[Optional[float]] = []
                if self.peek() != ")":
                    while True:
                        argument = self.parse_expression()
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
                    "asinh": math.asinh,
                    "acosh": math.acosh,
                    "atanh": math.atanh,
                    "arcsinh": math.asinh,
                    "arccosh": math.acosh,
                    "arctanh": math.atanh,
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
                    if (
                        function_name in {"lt", "leq", "gt", "geq"}
                        and len(arguments) >= 2
                        and all(value is not None for value in arguments)
                    ):
                        return float(
                            all(
                                comparisons[function_name](left, right)
                                for left, right in zip(arguments, arguments[1:])
                            )
                        )
                    if (
                        function_name in {"eq", "neq"}
                        and len(arguments) == 2
                        and all(value is not None for value in arguments)
                    ):
                        return float(comparisons[function_name](*arguments))
                    if function_name == "and" and arguments:
                        if any(value == 0 for value in arguments):
                            return 0.0
                        if all(value is not None for value in arguments):
                            return 1.0
                        return None
                    if function_name == "or" and arguments:
                        if any(value is not None and value != 0 for value in arguments):
                            return 1.0
                        if all(value is not None for value in arguments):
                            return 0.0
                        return None
                    if (
                        function_name == "not"
                        and len(arguments) == 1
                        and arguments[0] is not None
                    ):
                        return float(arguments[0] == 0)
                    if any(argument is None for argument in arguments):
                        return None
                    arguments = [float(argument) for argument in arguments]
                    if function_name == "plus":
                        value = sum(arguments)
                    elif function_name == "times":
                        value = math.prod(arguments)
                    elif function_name == "minus" and len(arguments) == 1:
                        value = -arguments[0]
                    elif function_name == "minus" and len(arguments) >= 2:
                        value = arguments[0] - sum(arguments[1:])
                    elif function_name == "divide" and len(arguments) == 2:
                        value = arguments[0] / arguments[1]
                    elif function_name == "arcsec" and len(arguments) == 1:
                        value = math.acos(1 / arguments[0])
                    elif function_name == "arccsc" and len(arguments) == 1:
                        value = math.asin(1 / arguments[0])
                    elif function_name == "arccot" and len(arguments) == 1:
                        value = math.atan2(1.0, arguments[0])
                    elif function_name == "arcsech" and len(arguments) == 1:
                        value = math.acosh(1 / arguments[0])
                    elif function_name == "arccsch" and len(arguments) == 1:
                        value = math.asinh(1 / arguments[0])
                    elif function_name == "arccoth" and len(arguments) == 1:
                        value = math.atanh(1 / arguments[0])
                    elif function_name in unary and len(arguments) == 1:
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
    """Return the threshold from a trigger that crosses a time boundary."""

    if not trigger:
        return None
    value = trigger.strip()
    match = re.match(r"^(?:geq|gt)\s*\(\s*time\s*,\s*(.+)\)\s*$", value, re.IGNORECASE)
    if match:
        return _strip_outer_parens(_balanced_inner(match.group(1)))
    match = re.match(r"^eq\s*\(\s*time\s*,\s*(.+)\)\s*$", value, re.IGNORECASE)
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
        r"^\(?\s*time\s*==\s*(.+?)\s*\)?$",
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


def _split_call_arguments(expression: str) -> Optional[List[str]]:
    """Split a function call's arguments without splitting nested calls."""

    value = expression.strip()
    opening = value.find("(")
    if opening <= 0 or not value.endswith(")"):
        return None
    if value[:opening].strip().lower() != "and":
        return None
    body = value[opening + 1 : -1]
    arguments: List[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(body):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return None
        elif character == "," and depth == 0:
            arguments.append(body[start:index].strip())
            start = index + 1
    if depth != 0:
        return None
    arguments.append(body[start:].strip())
    return arguments if len(arguments) >= 2 and all(arguments) else None


def _parse_time_window(trigger: str) -> Optional[Tuple[List[str], List[str]]]:
    """Parse a conjunction of monotone time bounds as lower/upper thresholds.

    Only direct comparisons against ``time`` are accepted. Mixed state
    predicates, disjunctions, scaled time, and equality remain outside this
    fixed schedule lowering.
    """

    terms = _split_call_arguments(trigger)
    if terms is None:
        return None
    lower: List[str] = []
    upper: List[str] = []
    comparison = re.compile(r"^(geq|gt|leq|lt)\s*\((.*)\)$", re.IGNORECASE)
    for term in terms:
        match = comparison.match(term.strip())
        if match is None:
            return None
        parts = _split_arguments(match.group(2))
        if parts is None or len(parts) != 2:
            return None
        left, right = (_strip_outer_parens(part) for part in parts)
        operator = match.group(1).lower()
        if left.lower() == "time" and "time" not in right.lower():
            (lower if operator in {"geq", "gt"} else upper).append(right)
        elif right.lower() == "time" and "time" not in left.lower():
            (lower if operator in {"leq", "lt"} else upper).append(left)
        else:
            return None
    return (lower, upper) if lower else None


def _parse_gated_time_window(
    trigger: str, fold_static: Callable[[str], Optional[float]]
) -> Optional[Tuple[List[str], List[str], bool]]:
    """Parse a time window conjoined with immutable, foldable predicates."""

    terms = _split_call_arguments(trigger)
    if terms is None:
        return None
    lower: List[str] = []
    upper: List[str] = []
    comparison = re.compile(r"^(geq|gt|leq|lt)\s*\((.*)\)$", re.IGNORECASE)
    for term in terms:
        match = comparison.match(term.strip())
        if match is None:
            value = fold_static(term)
            if value is None:
                return None
            if value == 0:
                return ([], [], False)
            continue
        parts = _split_arguments(match.group(2))
        if parts is None or len(parts) != 2:
            return None
        left, right = (_strip_outer_parens(part) for part in parts)
        operator = match.group(1).lower()
        if left.lower() == "time" and "time" not in right.lower():
            (lower if operator in {"geq", "gt"} else upper).append(right)
        elif right.lower() == "time" and "time" not in left.lower():
            (lower if operator in {"leq", "lt"} else upper).append(left)
        else:
            # It may be a constant predicate, such as ``gt(k, 0)``.
            value = fold_static(term)
            if value is None:
                return None
            if value == 0:
                return ([], [], False)
    return (lower, upper, True) if lower else None


def _split_arguments(expression: str) -> Optional[List[str]]:
    """Split a comma-separated argument body at its outermost level."""

    parts: List[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(expression):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return None
        elif character == "," and depth == 0:
            parts.append(expression[start:index].strip())
            start = index + 1
    if depth != 0:
        return None
    parts.append(expression[start:].strip())
    return parts if all(parts) else None


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


def _parse_affine_state_threshold(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse one comparison between a state symbol and a constant threshold."""

    match = re.match(r"^(gt|geq|lt|leq)\s*\((.*)\)$", str(trigger or "").strip(), re.I)
    if match is None:
        return None
    arguments = _split_arguments(match.group(2))
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(value) for value in arguments)
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    if re.fullmatch(identifier, left):
        return left, match.group(1).lower(), right
    if re.fullmatch(identifier, right):
        reverse = {"gt": "lt", "geq": "leq", "lt": "gt", "leq": "geq"}
        return right, reverse[match.group(1).lower()], left
    return None


def _parse_affine_state_interval(
    trigger: str,
) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
    """Parse a conjunction of lower and upper bounds on one state."""

    comparisons = _split_call_arguments(str(trigger or "").strip())
    if comparisons is None or len(comparisons) != 2:
        return None
    parsed = [_parse_affine_state_threshold(term) for term in comparisons]
    if any(item is None for item in parsed):
        return None
    concrete = [item for item in parsed if item is not None]
    identifiers = {item[0] for item in concrete}
    operators = [item[1] for item in concrete]
    if len(identifiers) != 1 or not any(op in {"gt", "geq"} for op in operators):
        return None
    if not any(op in {"lt", "leq"} for op in operators):
        return None
    return next(iter(identifiers)), [(op, value) for _identifier, op, value in concrete]


def _parse_rate_of_state_threshold(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse one comparison between ``rateOf(state)`` and a constant."""

    match = re.match(r"^(gt|geq|lt|leq)\s*\((.*)\)$", str(trigger or "").strip(), re.I)
    if match is None:
        return None
    arguments = _split_arguments(match.group(2))
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(value) for value in arguments)
    rate_of = re.compile(
        r"^rateof\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)$", re.I
    )
    left_match, right_match = rate_of.fullmatch(left), rate_of.fullmatch(right)
    if left_match is not None:
        return left_match.group(1), match.group(1).lower(), right
    if right_match is not None:
        reverse = {"gt": "lt", "geq": "leq", "lt": "gt", "leq": "geq"}
        return right_match.group(1), reverse[match.group(1).lower()], left
    return None


def _parse_scaled_state_threshold(
    trigger: str,
) -> Optional[Tuple[str, str, str, str]]:
    """Parse a comparison of a constant multiple of one state to a value."""

    match = re.match(r"^(gt|geq|lt|leq)\s*\((.*)\)$", str(trigger or "").strip(), re.I)
    if match is None:
        return None
    arguments = _split_arguments(match.group(2))
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(value) for value in arguments)
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"

    def parse_scaled(value: str) -> Optional[Tuple[str, str]]:
        expression = _strip_outer_parens(value)
        product = re.fullmatch(rf"(.+?)\s*\*\s*({identifier})", expression)
        if product is not None:
            return product.group(2), product.group(1)
        product = re.fullmatch(rf"({identifier})\s*\*\s*(.+)", expression)
        if product is not None:
            return product.group(1), product.group(2)
        return None

    left_scaled = parse_scaled(left)
    if left_scaled is not None:
        return left_scaled[0], match.group(1).lower(), right, left_scaled[1]
    right_scaled = parse_scaled(right)
    if right_scaled is not None:
        reverse = {"gt": "lt", "geq": "leq", "lt": "gt", "leq": "geq"}
        return (
            right_scaled[0],
            reverse[match.group(1).lower()],
            left,
            right_scaled[1],
        )
    return None


def _parse_periodic_reset_trigger(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse ``time - reset >= interval`` with one reset symbol."""

    match = re.match(
        r"^(geq|gt)\s*\((.*)\)$", str(trigger or "").strip(), re.IGNORECASE
    )
    if match is None:
        return None
    arguments = _split_arguments(match.group(2))
    if arguments is None or len(arguments) != 2:
        return None
    elapsed, interval = (_strip_outer_parens(value) for value in arguments)
    elapsed_match = re.fullmatch(
        r"(?:minus|subtract)\s*\(\s*time\s*,\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        elapsed,
        re.IGNORECASE,
    )
    if elapsed_match is None:
        elapsed_match = re.fullmatch(
            r"time\s*-\s*([A-Za-z_][A-Za-z0-9_]*)", elapsed, re.IGNORECASE
        )
    return (
        (elapsed_match.group(1), match.group(1).lower(), interval)
        if elapsed_match
        else None
    )


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
    if kind == "volume":
        return f'setVolume({{target=>"{target}", value=>{_format_number(value)}}})'
    command = {
        "conc": "setConcentration",
        "param": "setParameter",
    }.get(kind)
    if command is None:
        raise ValueError(f"unsupported event assignment kind: {kind}")
    return f'{command}("{target}", "{_format_number(value)}")'


def synthesize_event_actions(
    events: Sequence[SBMLEvent], context: EventTranslationContext
) -> EventTranslationResult:
    """Translate safe fixed-time events and report all rejected events."""

    untranslated: List[Tuple[SBMLEvent, str]] = []
    scheduled: List[Tuple[float, List[Tuple[str, str, float]], float]] = []

    def fold(
        expression: str,
        time_value: Optional[float] = None,
        dynamic_values: Optional[Mapping[str, float]] = None,
    ) -> Optional[float]:
        if time_value is not None:
            expression = re.sub(
                r"\btime\b", _format_number(time_value), expression, flags=re.IGNORECASE
            )
        expression = context.expand_functions(expression)

        def resolve(identifier: str) -> Optional[float]:
            if dynamic_values is not None and identifier in dynamic_values:
                return dynamic_values[identifier]
            if context.is_compile_time_constant(identifier):
                value = context.resolve_param(identifier)
                if value is not None:
                    return value
            return context.resolve_constant(identifier)

        return fold_numeric(expression, resolve)

    def fold_initial(expression: str) -> Optional[float]:
        expression = context.expand_functions(str(expression or ""))
        return fold_numeric(expression, context.resolve_initial_value)

    def fold_at_state(
        expression: str,
        time_value: float,
        state_values: Optional[Mapping[str, float]] = None,
    ) -> Optional[float]:
        """Fold an event value using only proven state trajectories."""
        values = dict(state_values or {})
        expanded = context.expand_functions(str(expression or ""))
        identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expanded))
        for identifier in identifiers:
            if identifier in values:
                continue
            trajectory = context.resolve_affine_rate(identifier)
            try:
                if trajectory is not None:
                    initial, slope = trajectory
                    value = initial + slope * time_value
                else:
                    exponential = context.resolve_exponential_rate(identifier)
                    if exponential is None:
                        continue
                    initial, exponent = exponential
                    value = initial * math.exp(exponent * time_value)
            except OverflowError:
                continue
            if math.isfinite(value):
                values[identifier] = value
        return fold(expression, time_value, dynamic_values=values)

    periodic_groups: dict[Tuple[str, str, float], List[SBMLEvent]] = {}
    periodic_handled: set[int] = set()
    periodic_converted = 0
    periodic_target_ids: set[str] = set()
    periodic_rate_state_ids: set[str] = set()
    periodic_changes: List[Tuple[float, Mapping[str, float]]] = []
    periodic_initial_values: dict[str, float] = {}
    for event in events:
        parsed = _parse_periodic_reset_trigger(event.trigger)
        if parsed is None:
            continue
        reset_identifier, operator, interval_expression = parsed
        interval = fold(interval_expression)
        if interval is None or interval <= 0:
            continue
        periodic_groups.setdefault((reset_identifier, operator, interval), []).append(
            event
        )

    for (reset_identifier, _operator, interval), group in periodic_groups.items():
        group_ids = {id(event) for event in group}
        periodic_handled.update(group_ids)
        delays = [0.0 if not event.delay else fold(event.delay) for event in group]
        delay = delays[0] if delays and delays[0] is not None else None
        assignments_by_event = [
            [_event_assignment(assignment) for assignment in event.assignments]
            for event in group
        ]
        group_targets = {
            variable
            for assignments in assignments_by_event
            for variable, _expression in assignments
        }
        valid = (
            not (group_targets & periodic_target_ids)
            and context.is_param(reset_identifier)
            and all(
                delay is not None
                and delay >= 0
                and math.isfinite(delay)
                and (delay == 0 or not event.use_values_from_trigger_time)
                and event_delay == delay
                and (not event.priority or fold(event.priority) is not None)
                and any(
                    variable == reset_identifier
                    and re.sub(r"[()\s]", "", expression).lower() == "time"
                    for variable, expression in assignments
                )
                and all(context.is_param(variable) for variable, _ in assignments)
                for event, assignments, event_delay in zip(
                    group, assignments_by_event, delays
                )
            )
            and all(
                variable == reset_identifier
                or sum(
                    variable == target
                    for assignments in assignments_by_event
                    for target, _expression in assignments
                )
                == 1
                for variable in group_targets
            )
            and not any(
                id(other) not in group_ids
                and any(
                    variable in group_targets
                    for assignment in other.assignments
                    for variable, _expression in [_event_assignment(assignment)]
                )
                for other in events
            )
        )
        initial_reset = context.resolve_initial_value(reset_identifier)
        current_values = {
            variable: context.resolve_initial_value(variable)
            for variable in group_targets
        }
        valid = (
            valid
            and initial_reset is not None
            and all(value is not None for value in current_values.values())
        )
        if not valid:
            untranslated.extend(
                (event, "periodic reset event has dynamic or conflicting assignments")
                for event in group
            )
            continue

        initial_elapsed = -float(initial_reset)
        initially_true = (
            initial_elapsed > interval
            if _operator == "gt"
            else initial_elapsed >= interval
        )
        trigger_initial_value = group[0].trigger_initial_value
        if any(event.trigger_initial_value != trigger_initial_value for event in group):
            untranslated.extend(
                (
                    event,
                    "simultaneous periodic reset events disagree on trigger initialization",
                )
                for event in group
            )
            continue
        if initially_true:
            if not trigger_initial_value:
                next_time = 0.0
            else:
                # The trigger starts true and remains true until this event
                # itself resets the clock; no rising edge occurs in-range.
                periodic_converted += len(group)
                continue
        else:
            next_time = float(initial_reset) + interval + float(delay)

        if initially_true and not trigger_initial_value:
            next_time += float(delay)

        first_time = next_time
        initial_group_values = dict(current_values)
        event_count = 0
        group_schedule: List[Tuple[float, List[Tuple[str, str, float]], float]] = []
        group_changes: List[Tuple[float, Mapping[str, float]]] = []
        while next_time <= context.base_t_end + 1e-12:
            event_count += 1
            if event_count > 10_000:
                valid = False
                break
            updates: dict[str, float] = {}
            sets: List[Tuple[str, str, float]] = []
            for assignments in assignments_by_event:
                for variable, expression in assignments:
                    value = fold(expression, next_time, current_values)
                    if value is None or variable not in current_values:
                        valid = False
                        break
                    normalized = standardize_name(variable)
                    updates[variable] = value
                    sets.append(("param", normalized, value))
                if not valid:
                    break
            if not valid:
                break
            if len(updates) != len(
                {variable for a in assignments_by_event for variable, _ in a}
            ):
                valid = False
                break
            group_schedule.append((next_time, sets, 0.0))
            current_values.update(updates)
            group_changes.append((next_time, dict(current_values)))
            next_time = first_time + event_count * interval

        if valid:
            scheduled.extend(group_schedule)
            periodic_target_ids.update(group_targets)
            periodic_initial_values.update(
                {key: float(value) for key, value in initial_group_values.items()}
            )
            periodic_changes.extend(group_changes)
            periodic_converted += len(group)
        else:
            untranslated.extend(
                (
                    event,
                    "periodic reset assignments do not fold to finite parameter values",
                )
                for event in group
            )

    # A constant rate-rule state can act as a resettable clock too. Once an
    # event resets that state to a fixed value, its linear trajectory crosses
    # the same threshold at a fixed interval on every recurrence.
    rate_groups: dict[Tuple[str, str, float, float, float], List[SBMLEvent]] = {}
    for event in events:
        parsed = _parse_affine_state_threshold(event.trigger)
        if parsed is None:
            continue
        reset_identifier, operator, threshold_expression = parsed
        trajectory = context.resolve_rate_reset(reset_identifier)
        threshold = fold(threshold_expression)
        if trajectory is None or threshold is None:
            continue
        initial_value, slope = trajectory
        if not math.isfinite(initial_value) or not math.isfinite(slope) or slope == 0:
            continue
        rising = (operator in {"gt", "geq"} and slope > 0) or (
            operator in {"lt", "leq"} and slope < 0
        )
        if not rising:
            continue
        assignments = [_event_assignment(item) for item in event.assignments]
        reset_values = [
            fold(expression)
            for variable, expression in assignments
            if variable == reset_identifier
        ]
        if len(reset_values) != 1 or reset_values[0] is None:
            continue
        reset_value = float(reset_values[0])
        period = (float(threshold) - reset_value) / slope
        first_time = (float(threshold) - initial_value) / slope
        if (
            not math.isfinite(period)
            or not math.isfinite(first_time)
            or period <= 0
            or first_time < 0
        ):
            continue
        rate_groups.setdefault(
            (reset_identifier, operator, float(threshold), slope, reset_value), []
        ).append(event)

    for (
        reset_identifier,
        operator,
        threshold,
        slope,
        reset_value,
    ), group in rate_groups.items():
        group_ids = {id(event) for event in group}
        periodic_handled.update(group_ids)
        assignments_by_event = [
            [_event_assignment(assignment) for assignment in event.assignments]
            for event in group
        ]
        group_targets = {
            variable
            for assignments in assignments_by_event
            for variable, _expression in assignments
        }
        initial_rate = context.resolve_rate_reset(reset_identifier)
        initial_reset = initial_rate[0] if initial_rate is not None else None
        valid = (
            not (group_targets & periodic_target_ids)
            and context.is_param(reset_identifier)
            and all(
                not event.delay
                and (not event.priority or fold(event.priority) is not None)
                for event in group
            )
            and all(
                variable == reset_identifier or context.is_param(variable)
                for assignments in assignments_by_event
                for variable, _expression in assignments
            )
            and all(
                len(
                    [
                        expression
                        for variable, expression in assignments
                        if variable == reset_identifier
                    ]
                )
                == 1
                and fold(
                    next(
                        expression
                        for variable, expression in assignments
                        if variable == reset_identifier
                    )
                )
                == reset_value
                for assignments in assignments_by_event
            )
            and all(
                variable == reset_identifier
                or sum(
                    variable == target
                    for assignments in assignments_by_event
                    for target, _expression in assignments
                )
                == 1
                for variable in group_targets
            )
            and not any(
                id(other) not in group_ids
                and any(
                    variable in group_targets
                    for assignment in other.assignments
                    for variable, _expression in [_event_assignment(assignment)]
                )
                for other in events
            )
        )
        current_values = {
            variable: (
                initial_reset
                if variable == reset_identifier
                else context.resolve_initial_value(variable)
            )
            for variable in group_targets
        }
        valid = (
            valid
            and initial_reset is not None
            and all(value is not None for value in current_values.values())
        )
        trigger_initial_value = group[0].trigger_initial_value
        if any(event.trigger_initial_value != trigger_initial_value for event in group):
            valid = False
        if not valid:
            untranslated.extend(
                (event, "rate-rule reset event has dynamic or conflicting assignments")
                for event in group
            )
            continue

        initially_true = (
            initial_reset > threshold
            if operator == "gt"
            else initial_reset >= threshold
            if operator == "geq"
            else initial_reset < threshold
            if operator == "lt"
            else initial_reset <= threshold
        )
        if initially_true and trigger_initial_value:
            periodic_converted += len(group)
            continue
        period = (threshold - reset_value) / slope
        first_time = 0.0 if initially_true else (threshold - initial_reset) / slope
        initial_group_values = dict(current_values)

        def fold_rate_assignment(expression: str, time_value: float) -> Optional[float]:
            expanded = str(expression or "")
            delay_call = re.compile(
                r"\bdelay\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([^()]*)\)",
                re.IGNORECASE,
            )
            while True:
                match = delay_call.search(expanded)
                if match is None:
                    break
                if standardize_name(match.group(1)) != standardize_name(
                    reset_identifier
                ):
                    return None
                duration = fold(match.group(2))
                if duration is None or duration < 0 or not math.isfinite(duration):
                    return None
                history_time = time_value - duration
                if duration == 0 and initially_true and first_time == 0:
                    history_value = float(initial_reset)
                elif duration == 0:
                    # At a threshold crossing, trigger-time assignments read
                    # the pre-event rate-rule value, before the reset occurs.
                    history_value = threshold
                elif history_time <= 0:
                    history_value = float(initial_reset)
                elif history_time < first_time:
                    history_value = float(initial_reset) + slope * history_time
                else:
                    recurrence = math.floor(
                        (history_time - first_time) / period + 1e-12
                    )
                    last_reset_time = first_time + recurrence * period
                    history_value = reset_value + slope * (
                        history_time - last_reset_time
                    )
                expanded = (
                    expanded[: match.start()]
                    + _format_number(history_value)
                    + expanded[match.end() :]
                )
            if re.search(r"\bdelay\s*\(", expanded, re.IGNORECASE):
                return None
            return fold(expanded, time_value, current_values)

        event_count = 0
        group_schedule = []
        group_changes = []
        next_time = first_time
        while next_time <= context.base_t_end + 1e-12:
            event_count += 1
            if event_count > 10_000:
                valid = False
                break
            updates: dict[str, float] = {}
            sets: List[Tuple[str, str, float]] = []
            for assignments in assignments_by_event:
                for variable, expression in assignments:
                    value = fold_rate_assignment(expression, next_time)
                    if value is None:
                        valid = False
                        break
                    updates[variable] = value
                    sets.append(("param", standardize_name(variable), value))
                if not valid:
                    break
            if not valid:
                break
            group_schedule.append((next_time, sets, 0.0))
            current_values.update(updates)
            group_changes.append((next_time, dict(current_values)))
            next_time = first_time + event_count * period

        if valid:
            scheduled.extend(group_schedule)
            periodic_target_ids.update(group_targets)
            periodic_rate_state_ids.add(reset_identifier)
            periodic_initial_values.update(
                {key: float(value) for key, value in initial_group_values.items()}
            )
            periodic_changes.extend(group_changes)
            periodic_converted += len(group)
        else:
            untranslated.extend(
                (
                    event,
                    "rate-rule reset assignments do not fold to finite parameter values",
                )
                for event in group
            )

    affine_interval_schedules: dict[
        int, Tuple[str, float, float, float, float, float, float, str, str]
    ] = {}
    affine_interval_no_action: set[int] = set()
    static_event_no_action: set[int] = set()
    static_event_initial_fires: dict[int, dict[str, float]] = {}
    if context.static_event_state and len(events) == 1:
        event = events[0]
        static_threshold = _parse_affine_state_threshold(event.trigger)
        if static_threshold is not None:
            identifier, operator, expression = static_threshold
            initial = context.resolve_initial_value(identifier)
            threshold = fold_initial(expression)
            if (
                initial is not None
                and threshold is not None
                and math.isfinite(float(initial))
                and math.isfinite(float(threshold))
            ):
                initial = float(initial)
                threshold = float(threshold)
                initially_true = (
                    initial > threshold
                    if operator == "gt"
                    else initial >= threshold
                    if operator == "geq"
                    else initial < threshold
                    if operator == "lt"
                    else initial <= threshold
                )
                if not initially_true or event.trigger_initial_value:
                    static_event_no_action.add(id(event))
                else:
                    static_event_initial_fires[id(event)] = {
                        identifier: initial
                    }

    for event in events:
        parsed_interval = _parse_affine_state_interval(event.trigger)
        if parsed_interval is None or len(events) != 1:
            continue
        identifier, comparisons = parsed_interval
        lower_bounds = [
            (operator, fold(expression))
            for operator, expression in comparisons
            if operator in {"gt", "geq"}
        ]
        upper_bounds = [
            (operator, fold(expression))
            for operator, expression in comparisons
            if operator in {"lt", "leq"}
        ]
        if (
            len(lower_bounds) != 1
            or len(upper_bounds) != 1
            or lower_bounds[0][1] is None
            or upper_bounds[0][1] is None
        ):
            continue
        lower_operator, lower_value = lower_bounds[0]
        upper_operator, upper_value = upper_bounds[0]
        lower = float(lower_value)
        upper = float(upper_value)
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            continue
        trajectory = context.resolve_affine_rate_for_event(identifier, event)
        if trajectory is None:
            continue
        initial, slope = trajectory
        if not math.isfinite(initial) or not math.isfinite(slope) or slope == 0:
            continue

        def inside_interval(value: float) -> bool:
            lower_ok = value > lower if lower_operator == "gt" else value >= lower
            upper_ok = value < upper if upper_operator == "lt" else value <= upper
            return lower_ok and upper_ok

        initially_inside = inside_interval(initial)
        if initially_inside and event.trigger_initial_value:
            affine_interval_no_action.add(id(event))
            continue
        if slope > 0:
            entry = 0.0 if initially_inside else (lower - initial) / slope
            exit_time = (upper - initial) / slope
        else:
            entry = 0.0 if initially_inside else (upper - initial) / slope
            exit_time = (lower - initial) / slope
        if (
            not math.isfinite(entry)
            or not math.isfinite(exit_time)
            or entry < 0
            or exit_time <= entry
        ):
            affine_interval_no_action.add(id(event))
            continue
        if initially_inside and event.trigger_initial_value:
            affine_interval_no_action.add(id(event))
            continue
        affine_interval_schedules[id(event)] = (
            identifier,
            initial,
            slope,
            entry,
            lower,
            upper,
            exit_time,
            lower_operator,
            upper_operator,
        )

    def provably_false_in_horizon(
        expression: str, dynamic_values: Mapping[str, float]
    ) -> bool:
        """Prove a trigger false over this run from a static state trajectory."""
        normalized = str(expression or "").strip()
        match = re.match(r"^(and|or)\s*\((.*)\)$", normalized, re.I)
        if match is not None:
            arguments = _split_arguments(match.group(2))
            if arguments is None:
                return False
            proofs = [
                provably_false_in_horizon(argument, dynamic_values)
                for argument in arguments
            ]
            if match.group(1).lower() == "and":
                return any(proofs)
            return all(proofs)

        comparison = re.match(r"^(gt|geq|lt|leq)\s*\((.*)\)$", normalized, re.I)
        if comparison is not None:
            arguments = _split_arguments(comparison.group(2))
            if arguments is not None and len(arguments) == 2:
                left, right = (_strip_outer_parens(value) for value in arguments)
                operation = comparison.group(1).lower()
                if left.lower() == "time":
                    if operation not in {"gt", "geq"}:
                        return False
                    bound = fold(right, dynamic_values=dynamic_values)
                    if bound is not None:
                        value = (
                            context.base_t_end > bound
                            if operation == "gt"
                            else context.base_t_end >= bound
                        )
                        return not value
                if right.lower() == "time":
                    if operation not in {"lt", "leq"}:
                        return False
                    bound = fold(left, dynamic_values=dynamic_values)
                    if bound is not None:
                        value = (
                            bound < context.base_t_end
                            if operation == "lt"
                            else bound <= context.base_t_end
                        )
                        return not value
        value = fold(normalized, dynamic_values=dynamic_values)
        return value == 0

    if periodic_target_ids:
        periodic_changes.sort(key=lambda item: item[0])
        initial_state = {
            identifier: periodic_initial_values.get(
                identifier, context.resolve_initial_value(identifier)
            )
            for identifier in periodic_target_ids
        }
        for event in events:
            if id(event) in periodic_handled:
                continue
            identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", event.trigger))
            symbol_ids = {
                identifier for identifier in identifiers if context.is_param(identifier)
            }
            self_targets = {
                variable
                for assignment in event.assignments
                for variable, _expression in [_event_assignment(assignment)]
                if context.is_param(variable)
            }
            if (
                not symbol_ids
                or symbol_ids & periodic_rate_state_ids
                or not symbol_ids.issubset(
                    periodic_target_ids
                    | self_targets
                    | {
                        identifier
                        for identifier in symbol_ids
                        if context.is_compile_time_constant(identifier)
                    }
                )
                or any(
                    id(other) not in periodic_handled
                    and other is not event
                    and any(
                        variable in symbol_ids
                        for assignment in other.assignments
                        for variable, _expression in [_event_assignment(assignment)]
                    )
                    for other in events
                )
            ):
                continue
            dynamic_state = dict(initial_state)
            self_initial_values = {
                identifier: context.resolve_initial_value(identifier)
                for identifier in self_targets
            }
            if any(value is None for value in self_initial_values.values()):
                continue
            dynamic_state.update(
                {
                    identifier: float(value)
                    for identifier, value in self_initial_values.items()
                }
            )
            initial_truth = fold(event.trigger, dynamic_values=dynamic_state)
            if initial_truth != 0 and not provably_false_in_horizon(
                event.trigger, dynamic_state
            ):
                continue
            always_false = True
            for _time, changes in periodic_changes:
                dynamic_state.update(changes)
                trigger_value = fold(event.trigger, dynamic_values=dynamic_state)
                if trigger_value != 0 and not provably_false_in_horizon(
                    event.trigger, dynamic_state
                ):
                    always_false = False
                    break
            if always_false:
                periodic_handled.add(id(event))
                periodic_target_ids.update(self_targets)
                periodic_initial_values.update(
                    {
                        identifier: float(value)
                        for identifier, value in self_initial_values.items()
                    }
                )
                initial_state.update(
                    {
                        identifier: float(value)
                        for identifier, value in self_initial_values.items()
                    }
                )
                periodic_converted += 1

    normal_converted = 0
    for event in events:
        if id(event) in periodic_handled:
            continue
        if id(event) in static_event_no_action:
            normal_converted += 1
            continue
        if id(event) in affine_interval_no_action:
            normal_converted += 1
            continue
        trigger_state_values: Optional[dict[str, float]] = None
        trigger_state_trajectory: Optional[Tuple[str, str, float, float]] = None
        affine_interval = affine_interval_schedules.get(id(event))
        static_initial_values = static_event_initial_fires.get(id(event))
        if static_initial_values is not None:
            threshold = "0"
            window_end: Optional[float] = None
            trigger_state_values = dict(static_initial_values)
        elif affine_interval is not None:
            (
                interval_identifier,
                interval_initial,
                interval_slope,
                interval_entry,
                _interval_lower,
                _interval_upper,
                interval_exit,
                _interval_lower_operator,
                _interval_upper_operator,
            ) = affine_interval
            threshold = _format_number(interval_entry)
            window_end: Optional[float] = interval_exit
            trigger_state_values = {
                interval_identifier: interval_initial + interval_slope * interval_entry
            }
            trigger_state_trajectory = (
                interval_identifier,
                "affine",
                interval_initial,
                interval_slope,
            )
        else:
            threshold = parse_time_threshold(event.trigger)
            window_end = None
        scale_identifier: Optional[str] = None
        if threshold is None:
            state_threshold = _parse_affine_state_threshold(event.trigger)
            rate_of_threshold = False
            state_threshold_scale = "1"
            if state_threshold is None:
                state_threshold = _parse_rate_of_state_threshold(event.trigger)
                rate_of_threshold = state_threshold is not None
            if state_threshold is None:
                scaled_threshold = _parse_scaled_state_threshold(event.trigger)
                if scaled_threshold is not None:
                    (
                        scaled_identifier,
                        scaled_operator,
                        scaled_expression,
                        scale_expression,
                    ) = scaled_threshold
                    scale_value = fold(scale_expression)
                    if scale_value is not None and math.isfinite(scale_value):
                        if scale_value < 0:
                            scaled_operator = {
                                "gt": "lt",
                                "geq": "leq",
                                "lt": "gt",
                                "leq": "geq",
                            }[scaled_operator]
                            scale_value = -scale_value
                        if scale_value > 0:
                            state_threshold = (
                                scaled_identifier,
                                scaled_operator,
                                scaled_expression,
                            )
                            state_threshold_scale = _format_number(scale_value)
            if state_threshold is not None:
                identifier, operator, threshold_expression = state_threshold
                trajectory = (
                    None
                    if rate_of_threshold
                    else context.resolve_affine_rate(identifier)
                )
                crossing_value = fold(threshold_expression)
                if crossing_value is not None:
                    scale_value = float(state_threshold_scale)
                    crossing_value /= scale_value
                if trajectory is not None and crossing_value is not None:
                    initial_value, slope = trajectory
                    trigger_state_trajectory = (
                        identifier,
                        "affine",
                        initial_value,
                        slope,
                    )
                    initially_true = (
                        initial_value > crossing_value
                        if operator == "gt"
                        else initial_value >= crossing_value
                        if operator == "geq"
                        else initial_value < crossing_value
                        if operator == "lt"
                        else initial_value <= crossing_value
                    )
                    if slope == 0:
                        if initially_true and not event.trigger_initial_value:
                            threshold = "0"
                            trigger_state_values = {identifier: initial_value}
                        else:
                            normal_converted += 1
                            continue
                    elif initially_true:
                        if not event.trigger_initial_value:
                            threshold = "0"
                            trigger_state_values = {identifier: initial_value}
                        else:
                            normal_converted += 1
                            continue
                    else:
                        rising = (operator in {"gt", "geq"} and slope > 0) or (
                            operator in {"lt", "leq"} and slope < 0
                        )
                        if not rising:
                            normal_converted += 1
                            continue
                        crossing_time = (crossing_value - initial_value) / slope
                        if math.isfinite(crossing_time) and crossing_time >= 0:
                            threshold = _format_number(crossing_time)
                            trigger_state_values = {identifier: crossing_value}
                elif crossing_value is not None:
                    exponential = context.resolve_exponential_rate(identifier)
                    if exponential is not None:
                        initial_value, exponent = exponential
                        trigger_state_trajectory = (
                            identifier,
                            "exponential",
                            initial_value,
                            exponent,
                        )
                        initial_trigger_value = (
                            initial_value * exponent
                            if rate_of_threshold
                            else initial_value
                        )
                        crossing_state_value = (
                            crossing_value / exponent
                            if rate_of_threshold and exponent != 0
                            else crossing_value
                        )
                        initially_true = (
                            initial_trigger_value > crossing_value
                            if operator == "gt"
                            else initial_trigger_value >= crossing_value
                            if operator == "geq"
                            else initial_trigger_value < crossing_value
                            if operator == "lt"
                            else initial_trigger_value <= crossing_value
                        )
                        if (
                            exponent == 0
                            or initial_trigger_value == 0
                            or (rate_of_threshold and not math.isfinite(crossing_state_value))
                        ):
                            if initially_true and not event.trigger_initial_value:
                                threshold = "0"
                                trigger_state_values = {identifier: initial_value}
                            else:
                                normal_converted += 1
                                continue
                        elif initially_true:
                            if not event.trigger_initial_value:
                                threshold = "0"
                                trigger_state_values = {identifier: initial_value}
                            else:
                                normal_converted += 1
                                continue
                        else:
                            derivative_sign = initial_trigger_value * exponent
                            rising = (
                                operator in {"gt", "geq"} and derivative_sign > 0
                            ) or (
                                operator in {"lt", "leq"} and derivative_sign < 0
                            )
                            ratio = crossing_value / initial_trigger_value
                            if not rising or ratio <= 0:
                                normal_converted += 1
                                continue
                            crossing_time = math.log(ratio) / exponent
                            if math.isfinite(crossing_time) and crossing_time >= 0:
                                threshold = _format_number(crossing_time)
                                trigger_state_values = {
                                    identifier: crossing_state_value
                                }
        if threshold is None:
            window = _parse_gated_time_window(event.trigger, fold)
            if window is not None:
                lower_expressions, upper_expressions, gate_is_true = window
                if not gate_is_true:
                    normal_converted += 1
                    continue
                lower_values = [fold(expression) for expression in lower_expressions]
                upper_values = [fold(expression) for expression in upper_expressions]
                if all(value is not None for value in lower_values) and all(
                    value is not None for value in upper_values
                ):
                    trigger_time = max(float(value) for value in lower_values)
                    window_end = (
                        min(float(value) for value in upper_values)
                        if upper_values
                        else None
                    )
                    if window_end is not None and trigger_time >= window_end:
                        untranslated.append(
                            (
                                event,
                                "time-window bounds do not form a nonempty interval",
                            )
                        )
                        continue
                    if trigger_time <= 0:
                        untranslated.append(
                            (
                                event,
                                "time windows beginning at or before t=0 are not lowered",
                            )
                        )
                        continue
                    threshold = _format_number(trigger_time)
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
                # SBML initializes trigger truth from triggerInitialValue, then
                # evaluates the actual initial model state. If those differ,
                # the trigger has an exact rising edge at t=0, regardless of
                # whether a referenced parameter/species changes afterwards.
                initial_trigger = fold_initial(event.trigger)
                zero_delay = not event.delay or fold(event.delay, 0) == 0
                if (
                    initial_trigger == 1
                    and not event.trigger_initial_value
                    and zero_delay
                ):
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
            delay = fold_at_state(event.delay, trigger_time)
            if delay is None:
                untranslated.append(
                    (
                        event,
                        f'delay "{event.delay}" is not constant',
                    )
                )
                continue
            execution_time += delay
        if (
            window_end is not None
            and not event.trigger_persistent
            and execution_time >= window_end
        ):
            if affine_interval is not None:
                normal_converted += 1
                continue
            untranslated.append(
                (event, "nonpersistent delayed event may be canceled at the window end")
            )
            continue

        sets: List[Tuple[str, str, float]] = []
        failure: Optional[str] = None
        for assignment in event.assignments:
            variable, expression = _event_assignment(assignment)
            evaluation_time = (
                trigger_time if event.use_values_from_trigger_time else execution_time
            )
            assignment_state_values = trigger_state_values
            if not event.use_values_from_trigger_time and trigger_state_trajectory:
                identifier, trajectory_kind, initial_value, rate = (
                    trigger_state_trajectory
                )
                try:
                    state_value = (
                        initial_value + rate * evaluation_time
                        if trajectory_kind == "affine"
                        else initial_value * math.exp(rate * evaluation_time)
                    )
                except OverflowError:
                    state_value = math.inf
                if not math.isfinite(state_value):
                    failure = "event state at execution time is not finite"
                    break
                assignment_state_values = {identifier: state_value}
            value = fold_at_state(
                expression,
                evaluation_time,
                state_values=assignment_state_values,
            )
            if value is None and execution_time == 0:
                value = fold_initial(expression)
            if value is None:
                failure = (
                    f'assignment "{variable} := {expression}" is not constant '
                    "(depends on species/time or a function)"
                )
                break
            if affine_interval is not None and standardize_name(
                variable
            ) == standardize_name(affine_interval[0]):
                (
                    _identifier,
                    initial,
                    slope,
                    _entry,
                    lower,
                    upper,
                    _exit,
                    lower_operator,
                    upper_operator,
                ) = affine_interval

                def in_interval(state: float) -> bool:
                    lower_ok = state > lower if lower_operator == "gt" else state >= lower
                    upper_ok = state < upper if upper_operator == "lt" else state <= upper
                    return lower_ok and upper_ok

                state_before = initial + slope * execution_time
                no_reentry_within_run = False
                if slope > 0 and value < lower:
                    next_entry = execution_time + (lower - value) / slope
                    no_reentry_within_run = next_entry > max(
                        context.base_t_end, execution_time
                    )
                elif slope < 0 and value > upper:
                    next_entry = execution_time + (upper - value) / slope
                    no_reentry_within_run = next_entry > max(
                        context.base_t_end, execution_time
                    )
                if not (
                    (in_interval(state_before) and in_interval(value))
                    or (slope > 0 and value >= upper)
                    or (slope < 0 and value <= lower)
                    or no_reentry_within_run
                ):
                    failure = (
                        "delayed interval assignment can create another rising "
                        "trigger edge"
                    )
                    break
            pattern = context.resolve_species_pattern(variable)
            if pattern:
                sets.append(("conc", pattern, value))
            elif context.is_compartment(variable):
                sets.append(("volume", standardize_name(variable), value))
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
        normal_converted += 1

    if not scheduled:
        return EventTranslationResult(
            None, periodic_converted + normal_converted, untranslated
        )

    scheduled.sort(key=lambda item: (item[0], -item[2]))
    merged: List[Tuple[float, List[Tuple[str, str, float]]]] = []
    for time, sets, _priority in scheduled:
        if merged and abs(merged[-1][0] - time) < 1e-12:
            merged[-1][1].extend(sets)
        else:
            merged.append((time, list(sets)))

    last_fire = merged[-1][0]
    t_final = (
        context.base_t_end
        if periodic_changes or context.base_t_end > last_fire
        else last_fire * 1.5 + 1
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

    return EventTranslationResult(
        "\n".join(lines), periodic_converted + normal_converted, untranslated
    )


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
