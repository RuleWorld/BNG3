"""SBML event translation for the Playground-derived atomizer.

Fixed-time events and narrowly proven analytic state-event systems are lowered
to executable BNGL action phases. General state-dependent event scheduling
remains explicit because the BNGL action language has no trigger scheduler.
"""

from __future__ import annotations

import math
import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Callable, List, Optional, Sequence, Tuple

from .types import SBMLEvent, SBMLRule, standardize_name


def _no_event_affine_rate(
    _identifier: str, _event: SBMLEvent
) -> Optional[Tuple[float, float]]:
    return None


def _no_event_exponential_rate(
    _identifier: str, _event: SBMLEvent
) -> Optional[Tuple[float, float]]:
    return None


def _no_event_square_linear_rate(
    _identifier: str, _event: SBMLEvent
) -> Optional[Tuple[float, float]]:
    return None


def _no_event_species_volume_change(
    _identifier: str, _event: SBMLEvent
) -> Optional[Tuple[float, float]]:
    return None


def _no_event_volume_assignment_targets(
    _identifier: str, _event: SBMLEvent
) -> Sequence[str]:
    return ()


def _no_event_reaction_rate(_identifier: str, _event: SBMLEvent) -> Optional[float]:
    return None


def _no_priority_event_reaction_rate(
    _identifier: str,
    _event: SBMLEvent,
    _state_values: Optional[Mapping[str, float]] = None,
) -> Optional[float]:
    return None


def _no_priority_assignment_value(
    _identifier: str,
    _time: float,
    _event: SBMLEvent,
    _state_values: Mapping[str, float],
) -> Optional[float]:
    return None


def _no_event_quadratic_rate(
    _identifier: str, _event: SBMLEvent
) -> Optional[Tuple[float, float, float, float]]:
    return None


def _no_event_quadratic_state_values(
    _identifier: str, _value: float, _event: SBMLEvent
) -> Optional[Mapping[str, float]]:
    return None


def _no_event_quadratic_rate_from_state(
    _identifier: str,
    _event: SBMLEvent,
    _state_values: Mapping[str, float],
) -> Optional[Tuple[float, float, float, float]]:
    return None


def _no_event_quadratic_state_values_from_state(
    _identifier: str,
    _value: float,
    _event: SBMLEvent,
    _state_values: Mapping[str, float],
) -> Optional[Mapping[str, float]]:
    return None


def _no_first_order_cycle_event_system() -> (
    Optional[Tuple[Tuple[str, str, str], Tuple[float, float, float]]]
):
    return None


def _no_first_order_transfer_event_system() -> Optional[Tuple[str, str, float]]:
    return None


def _no_first_order_chain_event_system() -> (
    Optional[Tuple[str, str, str, float, float]]
):
    return None


@dataclass(frozen=True)
class _FirstOrderCycleTrajectory:
    total: float
    rates: Tuple[float, float, float]
    equilibrium: Tuple[float, float, float]
    mu: float
    discriminant: float
    u: float
    w: float
    v: float
    z: float
    a11: float
    a12: float
    a21: float
    a22: float

    @property
    def discriminant_tolerance(self) -> float:
        scale = max(
            (self.rates[0] + self.rates[2]) ** 2,
            self.rates[1] ** 2,
            abs(self.rates[0] * self.rates[2]),
            1e-300,
        )
        return 1e-14 * scale

    def state_at(self, elapsed: float) -> Optional[Tuple[float, float, float]]:
        if not math.isfinite(elapsed) or elapsed < 0:
            return None
        q = self.discriminant
        tolerance = self.discriminant_tolerance
        if q > tolerance:
            delta = math.sqrt(q)
            try:
                plus = math.exp((self.mu + delta) * elapsed)
                minus = math.exp((self.mu - delta) * elapsed)
            except OverflowError:
                return None
            first = (
                0.5 * (self.u + self.v / delta) * plus
                + 0.5 * (self.u - self.v / delta) * minus
            )
            second = (
                0.5 * (self.w + self.z / delta) * plus
                + 0.5 * (self.w - self.z / delta) * minus
            )
        elif q < -tolerance:
            omega = math.sqrt(-q)
            try:
                decay = math.exp(self.mu * elapsed)
            except OverflowError:
                return None
            cosine = math.cos(omega * elapsed)
            sine = math.sin(omega * elapsed)
            first = decay * (self.u * cosine + self.v * sine / omega)
            second = decay * (self.w * cosine + self.z * sine / omega)
        else:
            try:
                decay = math.exp(self.mu * elapsed)
            except OverflowError:
                return None
            first = decay * (self.u + self.v * elapsed)
            second = decay * (self.w + self.z * elapsed)

        first += self.equilibrium[0]
        second += self.equilibrium[1]
        third = self.total - first - second
        values = [first, second, third]
        if not all(math.isfinite(value) for value in values):
            return None
        scale = max(1e-300, abs(self.total), *(abs(value) for value in values))
        for index, value in enumerate(values):
            if value < -1e-12 * scale:
                return None
            if value < 0:
                values[index] = 0.0
        correction = self.total - math.fsum(values)
        values[2] += correction
        if values[2] < -1e-12 * scale:
            return None
        return values[0], values[1], max(0.0, values[2])

    def first_derivative(self, elapsed: float) -> Optional[float]:
        values = self.state_at(elapsed)
        if values is None:
            return None
        first, _second, third = values
        derivative = -self.rates[0] * first + self.rates[2] * third
        return derivative if math.isfinite(derivative) else None

    def extrema_times(self, horizon: float) -> Optional[List[float]]:
        if not math.isfinite(horizon) or horizon < 0:
            return None
        q = self.discriminant
        tolerance = self.discriminant_tolerance
        roots: List[float] = []
        if q < -tolerance:
            omega = math.sqrt(-q)
            cosine_coefficient = self.mu * self.u + self.v
            sine_coefficient = self.mu * self.v / omega - omega * self.u
            if cosine_coefficient == 0 and sine_coefficient == 0:
                return roots
            phase = math.atan2(-cosine_coefficient, sine_coefficient)
            first_n = math.floor(-phase / math.pi) - 1
            count = math.ceil(omega * horizon / math.pi) + 4
            if count > 10_000:
                return None
            for n in range(first_n, first_n + count):
                value = (phase + n * math.pi) / omega
                if 1e-12 < value < horizon - 1e-12:
                    roots.append(value)
        elif q > tolerance:
            delta = math.sqrt(q)
            positive_mode = 0.5 * (self.u + self.v / delta)
            negative_mode = 0.5 * (self.u - self.v / delta)
            numerator = -(self.mu - delta) * negative_mode
            denominator = (self.mu + delta) * positive_mode
            if denominator != 0 and numerator / denominator > 0:
                value = math.log(numerator / denominator) / (2.0 * delta)
                if 1e-12 < value < horizon - 1e-12:
                    roots.append(value)
        elif self.mu * self.v != 0:
            value = -(self.mu * self.u + self.v) / (self.mu * self.v)
            if 1e-12 < value < horizon - 1e-12:
                roots.append(value)
        return sorted(set(roots))


def _first_order_cycle_trajectory(
    state: Sequence[float], rates: Sequence[float]
) -> Optional[_FirstOrderCycleTrajectory]:
    if len(state) != 3 or len(rates) != 3:
        return None
    values = tuple(float(value) for value in state)
    cycle_rates = tuple(float(rate) for rate in rates)
    if not all(math.isfinite(value) and value >= 0 for value in values) or not all(
        math.isfinite(rate) and rate > 0 for rate in cycle_rates
    ):
        return None
    total = math.fsum(values)
    inverse_rate_sum = math.fsum(1.0 / rate for rate in cycle_rates)
    if not math.isfinite(total) or not math.isfinite(inverse_rate_sum):
        return None
    flux = total / inverse_rate_sum
    equilibrium = tuple(flux / rate for rate in cycle_rates)
    m00 = -(cycle_rates[0] + cycle_rates[2])
    m01 = -cycle_rates[2]
    m10 = cycle_rates[0]
    m11 = -cycle_rates[1]
    mu = 0.5 * (m00 + m11)
    a11, a12, a21, a22 = m00 - mu, m01, m10, m11 - mu
    discriminant = a11 * a11 + a12 * a21
    u = values[0] - equilibrium[0]
    w = values[1] - equilibrium[1]
    v = a11 * u + a12 * w
    z = a21 * u + a22 * w
    components = (*equilibrium, total, mu, discriminant, u, w, v, z)
    if not all(math.isfinite(value) for value in components):
        return None
    return _FirstOrderCycleTrajectory(
        total,
        cycle_rates,
        equilibrium,
        mu,
        discriminant,
        u,
        w,
        v,
        z,
        a11,
        a12,
        a21,
        a22,
    )


def _first_order_transfer_state_at(
    source: float, sink: float, rate: float, elapsed: float
) -> Optional[Tuple[float, float]]:
    if (
        not all(math.isfinite(value) for value in (source, sink, rate, elapsed))
        or source < 0
        or sink < 0
        or rate <= 0
        or elapsed < 0
    ):
        return None
    try:
        remaining = math.exp(-rate * elapsed)
    except OverflowError:
        return None
    next_source = source * remaining
    next_sink = sink + source * (1.0 - remaining)
    if not all(
        math.isfinite(value) and value >= 0 for value in (next_source, next_sink)
    ):
        return None
    return next_source, next_sink


def _first_order_chain_state_at(
    source: float,
    intermediate: float,
    first_rate: float,
    second_rate: float,
    elapsed: float,
) -> Optional[Tuple[float, float]]:
    """Return source and intermediate states in a two-step first-order chain."""
    if (
        not all(
            math.isfinite(value)
            for value in (source, intermediate, first_rate, second_rate, elapsed)
        )
        or source < 0
        or intermediate < 0
        or first_rate <= 0
        or second_rate <= 0
        or elapsed < 0
    ):
        return None
    try:
        first_decay = math.exp(-first_rate * elapsed)
        second_decay = math.exp(-second_rate * elapsed)
    except OverflowError:
        return None
    next_source = source * first_decay
    rate_scale = max(first_rate, second_rate, 1e-300)
    if abs(first_rate - second_rate) <= 1e-14 * rate_scale:
        next_intermediate = second_decay * (
            intermediate + first_rate * source * elapsed
        )
    else:
        next_intermediate = second_decay * intermediate + (
            first_rate
            * source
            * (first_decay - second_decay)
            / (second_rate - first_rate)
        )
    if not all(
        math.isfinite(value) and value >= 0
        for value in (next_source, next_intermediate)
    ):
        return None
    return next_source, next_intermediate


def _first_order_cycle_next_trigger_crossing(
    state: Sequence[float],
    rates: Sequence[float],
    threshold: float,
    operator: str,
    horizon: float,
) -> Optional[Tuple[float, bool]]:
    trajectory = _first_order_cycle_trajectory(state, rates)
    if trajectory is None:
        return None
    extrema = trajectory.extrema_times(horizon)
    if extrema is None:
        return None
    partitions = [0.0, *extrema, horizon]

    for left, right in zip(partitions, partitions[1:]):
        if right <= 1e-12:
            continue
        left_state = trajectory.state_at(left)
        right_state = trajectory.state_at(right)
        if left_state is None or right_state is None:
            return None
        left_delta = left_state[0] - threshold
        right_delta = right_state[0] - threshold
        same_sign = (left_delta > 0 and right_delta > 0) or (
            left_delta < 0 and right_delta < 0
        )
        zero_tolerance = 1e-13 * max(
            1e-300,
            abs(threshold),
            abs(left_state[0]),
            abs(right_state[0]),
        )
        if same_sign or (abs(left_delta) <= zero_tolerance and left <= 1e-12):
            continue
        if abs(left_delta) <= zero_tolerance:
            root = left
        elif abs(right_delta) <= zero_tolerance:
            root = right
        else:
            low, high = left, right
            low_value = left_delta
            for _ in range(80):
                middle = 0.5 * (low + high)
                middle_state = trajectory.state_at(middle)
                if middle_state is None:
                    return None
                middle_value = middle_state[0] - threshold
                if (middle_value < 0) == (low_value < 0):
                    low, low_value = middle, middle_value
                else:
                    high = middle
            root = 0.5 * (low + high)
        if root <= 1e-12 or root > horizon + 1e-12:
            continue
        root_state = trajectory.state_at(root)
        if root_state is None:
            return None
        derivative = trajectory.first_derivative(root)
        derivative_scale = max(
            1e-300,
            trajectory.rates[0] * root_state[0],
            trajectory.rates[2] * root_state[2],
        )
        if derivative is None:
            return None
        if abs(derivative) <= 1e-14 * derivative_scale:
            if operator in {"leq", "geq"}:
                return None
            continue
        enters_true = (operator in {"lt", "leq"} and derivative < 0) or (
            operator in {"gt", "geq"} and derivative > 0
        )
        return min(root, horizon), enters_true
    return math.inf, False


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
    # Return the SBML rate-rule expression for a state whose derivative may
    # depend on parameters updated by an already-proven periodic event group.
    resolve_rate_rule_expression_for_event: Callable[
        [str, SBMLEvent], Optional[str]
    ] = lambda _identifier, _event: None
    # Return (initial value, constant derivative) only for independently
    # affine states. Used to solve simple one-variable threshold crossings.
    resolve_affine_rate: Callable[[str], Optional[Tuple[float, float]]] = (
        lambda _identifier: None
    )
    # Event-local affine proof may ignore that event's own future assignment
    # while rejecting every other controller of the state.
    resolve_affine_rate_for_event: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float]]
    ] = _no_event_affine_rate
    # Priority evaluation may inspect pre-execution trajectories when only
    # simultaneous, same-trigger assignments would otherwise make them
    # ambiguous.
    resolve_affine_priority_rate: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float]]
    ] = _no_event_affine_rate
    # Return (initial value, exponent) for independently exponential states
    # whose exact trajectory is initial * exp(exponent * time).
    resolve_exponential_rate: Callable[[str], Optional[Tuple[float, float]]] = (
        lambda _identifier: None
    )
    resolve_exponential_rate_for_event: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float]]
    ] = _no_event_exponential_rate
    # Return (initial value, squared-state slope) for exact trajectories
    # satisfying state(t)^2 = initial^2 + slope * time.
    resolve_square_linear_rate_for_event: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float]]
    ] = _no_event_square_linear_rate
    # Return the old and assigned volumes when a concentration state has one
    # statically resolved event-driven compartment change.
    resolve_species_volume_change_for_event: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float]]
    ] = _no_event_species_volume_change
    # Compartment assignment rules may alias a mutable parameter that an event
    # updates. Those volume targets must receive matching executable actions.
    resolve_event_volume_assignment_targets: Callable[
        [str, SBMLEvent], Sequence[str]
    ] = _no_event_volume_assignment_targets
    # Return (initial, quadratic, linear, constant) for a proven scalar ODE
    # dx/dt = quadratic*x^2 + linear*x + constant.
    resolve_quadratic_rate_for_event: Callable[
        [str, SBMLEvent], Optional[Tuple[float, float, float, float]]
    ] = _no_event_quadratic_rate
    # Resolve model states at a proven quadratic trigger crossing for
    # trigger-time event assignment snapshots.
    resolve_quadratic_state_values_for_event: Callable[
        [str, float, SBMLEvent], Optional[Mapping[str, float]]
    ] = _no_event_quadratic_state_values
    # Re-resolve an exact quadratic trajectory from a post-event state snapshot.
    resolve_quadratic_rate_from_state: Callable[
        [str, SBMLEvent, Mapping[str, float]],
        Optional[Tuple[float, float, float, float]],
    ] = _no_event_quadratic_rate_from_state
    resolve_quadratic_state_values_from_state: Callable[
        [str, float, SBMLEvent, Mapping[str, float]], Optional[Mapping[str, float]]
    ] = _no_event_quadratic_state_values_from_state
    # Resolve a reaction identifier as its kinetic-law rate when that rate is
    # exactly foldable before the event executes.
    resolve_reaction_rate_for_event: Callable[[str, SBMLEvent], Optional[float]] = (
        _no_event_reaction_rate
    )
    # Resolve a reaction rate from the state immediately before a group of
    # simultaneous, same-trigger events. This is stricter than general event
    # rate folding and is used only to order that group's priorities.
    resolve_priority_reaction_rate_for_event: Callable[
        [str, SBMLEvent, Optional[Mapping[str, float]]], Optional[float]
    ] = _no_priority_event_reaction_rate
    resolve_priority_assignment_value: Callable[
        [str, float, SBMLEvent, Mapping[str, float]], Optional[float]
    ] = _no_priority_assignment_value
    # Resolve assignment-rule values from event-local state trajectories when
    # folding delayed event assignments. This uses stricter, non-simultaneous
    # controller checks than priority evaluation.
    resolve_assignment_rule_value_for_event: Callable[
        [str, float, SBMLEvent, Mapping[str, float]], Optional[float]
    ] = _no_priority_assignment_value
    # Initial value for a parameter that has no rule controller. Priority
    # evaluation may use it before the current simultaneous event group runs.
    resolve_priority_initial_parameter_value: Callable[[str], Optional[float]] = (
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
    # Event-system callbacks stay at the end to preserve positional
    # initializer compatibility.
    resolve_first_order_cycle_event_system: Callable[
        [], Optional[Tuple[Tuple[str, str, str], Tuple[float, float, float]]]
    ] = _no_first_order_cycle_event_system
    # Return source species, sink species, and a positive concentration-rate
    # constant for one isolated first-order transfer event system.
    resolve_first_order_transfer_event_system: Callable[
        [], Optional[Tuple[str, str, float]]
    ] = _no_first_order_transfer_event_system
    # Return source, intermediate, product and both first-order rate constants
    # for an isolated irreversible two-step chain.
    resolve_first_order_chain_event_system: Callable[
        [], Optional[Tuple[str, str, str, float, float]]
    ] = _no_first_order_chain_event_system

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
    horizon_limited: int = 0

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
                    # ``token`` is already lower-cased, so the spelled-out
                    # names reach here exactly as the alias table spells them.
                    order = _COMPARISON_ALIASES.get(function_name)
                    if (
                        order is not None
                        and len(arguments) >= 2
                        and all(value is not None for value in arguments)
                    ):
                        return float(
                            all(
                                comparisons[order](left, right)
                                for left, right in zip(arguments, arguments[1:])
                            )
                        )
                    if (
                        function_name == "eq"
                        and len(arguments) >= 2
                        and all(value is not None for value in arguments)
                    ):
                        return float(
                            all(value == arguments[0] for value in arguments[1:])
                        )
                    if (
                        function_name == "neq"
                        and len(arguments) == 2
                        and all(value is not None for value in arguments)
                    ):
                        return float(comparisons[function_name](*arguments))
                    if function_name == "if" and len(arguments) == 3:
                        condition = arguments[0]
                        if condition is None:
                            return None
                        return arguments[1] if condition != 0 else arguments[2]
                    if function_name == "piecewise" and arguments:
                        pair_limit = len(arguments) - (1 if len(arguments) % 2 else 0)
                        for index in range(0, pair_limit, 2):
                            condition = arguments[index + 1]
                            if condition is None:
                                return None
                            if condition != 0:
                                return arguments[index]
                        return arguments[-1] if len(arguments) % 2 else 0.0
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
    comparison = _match_comparison_call(value)
    if comparison is not None:
        operator, arguments_text = comparison
        arguments = _split_arguments(arguments_text)
        if arguments is not None and len(arguments) == 2:
            left, right = arguments
            if operator in {"gt", "geq"} and left.strip().lower() == "time":
                return _strip_outer_parens(right)
            if operator in {"lt", "leq"} and right.strip().lower() == "time":
                return _strip_outer_parens(left)
    match = re.match(r"^eq\s*\(\s*time\s*,\s*(.+)\)\s*$", value, re.IGNORECASE)
    if match:
        return _strip_outer_parens(_balanced_inner(match.group(1)))
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
    for term in terms:
        comparison = _match_comparison_call(term)
        if comparison is None:
            return None
        operator, arguments_text = comparison
        parts = _split_arguments(arguments_text)
        if parts is None or len(parts) != 2:
            return None
        left, right = (_strip_outer_parens(part) for part in parts)
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
    for term in terms:
        comparison = _match_comparison_call(term)
        if comparison is None:
            value = fold_static(term)
            if value is None:
                return None
            if value == 0:
                return ([], [], False)
            continue
        operator, arguments_text = comparison
        parts = _split_arguments(arguments_text)
        if parts is None or len(parts) != 2:
            return None
        left, right = (_strip_outer_parens(part) for part in parts)
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

    comparison = _match_comparison_call(trigger)
    if comparison is None or comparison[0] not in {"gt", "geq"}:
        return None
    arguments = _split_arguments(comparison[1])
    if arguments is None or len(arguments) != 2:
        return None
    scaled_time = re.fullmatch(
        r"\(?\s*time\s*/\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?",
        arguments[0].strip(),
        re.IGNORECASE,
    )
    if scaled_time is None:
        return None
    scale_identifier = scaled_time.group(1)
    threshold = _strip_outer_parens(arguments[1])
    return f"({threshold}) * ({scale_identifier})", scale_identifier


# An event trigger reaches these resolvers spelled in more than one way.
# MathML content markup lowers to the short relation names ``gt``, ``geq``,
# ``lt`` and ``leq`` (see ``_mathml_to_formula`` in ``parser.py``), while
# triggers that arrive from a ``formula`` attribute or a non-MathML producer
# keep the spelled-out name (``greaterThan``, ``lessOrEqual``, ...).  Both
# name the same comparison, so one table and one recognition helper serve
# every resolver; a second copy is how a spelling ends up accepted by one
# lowering path and silently refused by another.  ``eq`` and ``neq`` are
# deliberately absent: they are not order comparisons, and these resolvers
# only lower a threshold the trigger crosses monotonically.
_COMPARISON_ALIASES = {
    "gt": "gt",
    "greaterthan": "gt",
    "geq": "geq",
    "greaterorequal": "geq",
    "greaterthanorequal": "geq",
    "lt": "lt",
    "lessthan": "lt",
    "leq": "leq",
    "lessorequal": "leq",
    "lessthanorequal": "leq",
}
_COMPARISON_ALIAS_PATTERN = "|".join(sorted(_COMPARISON_ALIASES, key=len, reverse=True))
_REVERSED_COMPARISON_OPERATOR = {"gt": "lt", "geq": "leq", "lt": "gt", "leq": "geq"}


# Names a trigger expression uses for built-in functions rather than model
# symbols.  The comparison entries come from the alias table so that a
# spelled-out relation is not mistaken for a species or parameter.
_RESERVED_TRIGGER_SYMBOLS = frozenset(
    {
        "abs",
        "and",
        "eq",
        "exponentiale",
        *_COMPARISON_ALIASES,
        "if",
        "neq",
        "not",
        "or",
        "pi",
        "plus",
        "times",
    }
)


def _match_comparison_call(expression: str) -> Optional[Tuple[str, str]]:
    """Return the canonical operator and argument text of a comparison call."""
    match = re.match(
        rf"^({_COMPARISON_ALIAS_PATTERN})\s*\((.*)\)$",
        str(expression or "").strip(),
        re.IGNORECASE,
    )
    if match is None:
        return None
    return _COMPARISON_ALIASES[match.group(1).lower()], match.group(2)


def _parse_affine_state_threshold(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse one state comparison, dropping statically true ``and`` terms."""
    value = str(trigger or "").strip()
    comparison = _match_comparison_call(value)
    if comparison is None:
        conjunction = _split_call_arguments(value)
        if conjunction is not None:
            dynamic_terms = []
            for term in conjunction:
                static_value = fold_numeric(term, lambda _identifier: None)
                if static_value is None:
                    dynamic_terms.append(term)
                elif static_value == 0:
                    return None
            if len(dynamic_terms) == 1:
                return _parse_affine_state_threshold(dynamic_terms[0])
        return None
    operator, arguments_text = comparison
    arguments = _split_arguments(arguments_text)
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(argument) for argument in arguments)
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    if re.fullmatch(identifier, left):
        return left, operator, right
    if re.fullmatch(identifier, right):
        return right, _REVERSED_COMPARISON_OPERATOR[operator], left
    return None


def expand_sinusoidal_assignment_rule_events(
    events: Sequence[SBMLEvent],
    rules: Sequence[SBMLRule],
    *,
    t_end: float,
    resolve_constant: Callable[[str], Optional[float]],
    expand_functions: Callable[[str], str] = lambda expression: expression,
) -> List[SBMLEvent]:
    """Replace a narrow time-only sine trigger with its exact rising edges.

    Supported rules have the form ``piecewise(sin(a*time+b), time < t, c)``
    with finite constant coefficients. The fallback must not introduce an
    additional rising edge at the piecewise boundary. Delayed events must be
    persistent so each analytically scheduled firing remains valid.
    """

    def constant(node: ast.AST) -> Optional[float]:
        try:
            value = fold_numeric(ast.unparse(node), resolve_constant)
        except (TypeError, ValueError, SyntaxError):
            return None
        return value if value is not None and math.isfinite(value) else None

    def time_affine(node: ast.AST) -> Optional[Tuple[float, float]]:
        if isinstance(node, ast.Name):
            return (0.0, 1.0) if node.id.lower() == "time" else None
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value), 0.0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = time_affine(node.operand)
            if value is None:
                return None
            scale = -1.0 if isinstance(node.op, ast.USub) else 1.0
            return value[0] * scale, value[1] * scale
        if isinstance(node, ast.BinOp):
            left = time_affine(node.left)
            right = time_affine(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left[0] + right[0], left[1] + right[1]
            if isinstance(node.op, ast.Sub):
                return left[0] - right[0], left[1] - right[1]
            if isinstance(node.op, ast.Mult):
                if left[1] and right[1]:
                    return None
                return (
                    left[0] * right[0],
                    left[0] * right[1] + left[1] * right[0],
                )
            if isinstance(node.op, ast.Div) and right[1] == 0 and right[0] != 0:
                return left[0] / right[0], left[1] / right[0]
        if not any(
            isinstance(item, ast.Name) and item.id.lower() == "time"
            for item in ast.walk(node)
        ):
            value = constant(node)
            return (value, 0.0) if value is not None else None
        return None

    rule_by_variable = {
        standardize_name(str(rule.variable)): rule
        for rule in rules
        if rule.type == "assignment" and rule.variable
    }
    output: List[SBMLEvent] = []
    for event in events:
        parsed_trigger = _parse_affine_state_threshold(event.trigger)
        if parsed_trigger is None:
            output.append(event)
            continue
        identifier, operator, threshold_expression = parsed_trigger
        rule = rule_by_variable.get(standardize_name(identifier))
        if rule is None or operator not in {"gt", "geq", "lt", "leq"}:
            output.append(event)
            continue
        if event.delay and event.trigger_persistent is False:
            output.append(event)
            continue
        threshold = fold_numeric(
            expand_functions(str(threshold_expression)), resolve_constant
        )
        if threshold is None or not math.isfinite(threshold) or abs(threshold) > 1:
            output.append(event)
            continue
        formula = re.sub(
            r"\bif\s*\(", "sbml_if(", expand_functions(str(rule.math or "")), flags=re.I
        )
        try:
            expression = ast.parse(formula, mode="eval").body
        except (TypeError, ValueError, SyntaxError):
            output.append(event)
            continue
        if not (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Name)
            and expression.func.id.lower() in {"piecewise", "sbml_if"}
            and len(expression.args) == 3
        ):
            output.append(event)
            continue
        if expression.func.id.lower() == "sbml_if":
            condition, sine, fallback = expression.args
        else:
            sine, condition, fallback = expression.args
        if (
            isinstance(condition, ast.Call)
            and isinstance(condition.func, ast.Name)
            and condition.func.id.lower() in {"lt", "leq"}
            and len(condition.args) == 2
            and isinstance(condition.args[0], ast.Name)
            and condition.args[0].id.lower() == "time"
        ):
            condition_operator = condition.func.id.lower()
            condition_variable = condition.args[0]
            condition_cutoff = condition.args[1]
        elif (
            isinstance(condition, ast.Compare)
            and len(condition.ops) == 1
            and len(condition.comparators) == 1
            and isinstance(condition.left, ast.Name)
            and condition.left.id.lower() == "time"
            and isinstance(condition.ops[0], (ast.Lt, ast.LtE))
        ):
            condition_operator = (
                "leq" if isinstance(condition.ops[0], ast.LtE) else "lt"
            )
            condition_variable = condition.left
            condition_cutoff = condition.comparators[0]
        else:
            condition_operator = ""
            condition_variable = None
            condition_cutoff = None
        if not (
            isinstance(sine, ast.Call)
            and isinstance(sine.func, ast.Name)
            and sine.func.id.lower() == "sin"
            and len(sine.args) == 1
            and condition_operator in {"lt", "leq"}
            and condition_variable is not None
            and condition_cutoff is not None
        ):
            output.append(event)
            continue
        coefficients = time_affine(sine.args[0])
        cutoff = constant(condition_cutoff)
        fallback_value = constant(fallback)
        if (
            coefficients is None
            or cutoff is None
            or fallback_value is None
            or coefficients[1] == 0
            or t_end <= 0
        ):
            output.append(event)
            continue

        phase, omega = coefficients
        scan_end = min(float(t_end), cutoff)
        asin_threshold = math.asin(float(threshold))
        families = (asin_threshold, math.pi - asin_threshold)
        y_end = phase + omega * scan_end
        y_min, y_max = sorted((phase, y_end))
        roots: List[float] = []
        ambiguous_boundary = False
        period = 2 * math.pi
        for base in families:
            first = math.floor((y_min - base) / period) - 1
            last = math.ceil((y_max - base) / period) + 1
            if last - first > 100_000:
                roots = []
                break
            for cycle in range(first, last + 1):
                time_value = (base + cycle * period - phase) / omega
                if time_value < -1e-12 or time_value > scan_end + 1e-12:
                    continue
                if abs(time_value - cutoff) <= 1e-12:
                    ambiguous_boundary = True
                    continue
                delta = min(1e-6 / abs(omega), 1e-5)

                def trigger_true(value: float) -> bool:
                    return {
                        "gt": value > threshold,
                        "geq": value >= threshold,
                        "lt": value < threshold,
                        "leq": value <= threshold,
                    }[operator]

                left_time = max(0.0, time_value - delta)
                right_time = min(scan_end, time_value + delta)
                left_truth = trigger_true(math.sin(phase + omega * left_time))
                right_truth = trigger_true(math.sin(phase + omega * right_time))
                if time_value <= 1e-12:
                    left_truth = bool(event.trigger_initial_value)
                if not left_truth and right_truth:
                    roots.append(max(0.0, time_value))

        # A jump at the piecewise boundary is a distinct possible rising edge.
        boundary_time = cutoff
        if boundary_time <= t_end and boundary_time > 0:
            delta = min(1e-6 / abs(omega), 1e-5)
            before = trigger_true(math.sin(phase + omega * (boundary_time - delta)))
            after = trigger_true(fallback_value)
            if not before and after:
                roots.append(boundary_time)
        if ambiguous_boundary or not roots:
            # Leave no-crossing cases to the ordinary fail-closed path until
            # their initialValue and piecewise-boundary semantics are proven.
            output.append(event)
            continue

        roots = sorted({round(value, 14) for value in roots})
        for index, time_value in enumerate(roots, 1):
            output.append(
                replace(
                    event,
                    id=f"{event.id}__sine_edge_{index}",
                    trigger=f"geq(time, {_format_number(time_value)})",
                    trigger_initial_value=False,
                )
            )
    return output


def expand_cosh_assignment_rule_events(
    events: Sequence[SBMLEvent],
    rules: Sequence[SBMLRule],
    *,
    resolve_constant: Callable[[str], Optional[float]],
    expand_functions: Callable[[str], str] = lambda expression: expression,
) -> List[SBMLEvent]:
    """Rewrite monotone ``cosh(time)`` assignment-rule triggers as time bounds.

    This handles one rising threshold or a conjunction of lower and upper
    thresholds on the same time-only ``cosh(time)`` assignment rule. On
    SBML's nonnegative time axis, thresholds above one map exactly through
    ``acosh``. Other trajectories and predicate shapes are left for the normal
    event translator to reject explicitly.
    """

    rules_by_variable = {
        standardize_name(str(rule.variable)): rule
        for rule in rules
        if rule.type == "assignment" and rule.variable
    }
    output: List[SBMLEvent] = []
    for event in events:
        terms = _split_call_arguments(str(event.trigger or "").strip())
        if terms is None:
            terms = [str(event.trigger or "").strip()]
        if len(terms) not in {1, 2}:
            output.append(event)
            continue

        parsed: List[Tuple[str, float]] = []
        unsupported = False
        for term in terms:
            comparison = _match_comparison_call(term)
            arguments = (
                _split_arguments(comparison[1]) if comparison is not None else None
            )
            if comparison is None or arguments is None or len(arguments) != 2:
                unsupported = True
                break
            left, right = (_strip_outer_parens(value) for value in arguments)
            operator = comparison[0]
            cosh_time = lambda expression: (
                isinstance(expression, ast.Call)
                and isinstance(expression.func, ast.Name)
                and expression.func.id.lower() == "cosh"
                and len(expression.args) == 1
                and isinstance(expression.args[0], ast.Name)
                and expression.args[0].id.lower() == "time"
            )
            try:
                left_node = ast.parse(expand_functions(left), mode="eval").body
            except (TypeError, ValueError, SyntaxError):
                left_node = None
            if cosh_time(left_node):
                function_node = left_node
                threshold_expression = right
            else:
                try:
                    right_node = ast.parse(expand_functions(right), mode="eval").body
                except (TypeError, ValueError, SyntaxError):
                    right_node = None
                if not cosh_time(right_node):
                    unsupported = True
                    break
                function_node = right_node
                threshold_expression = left
                # ``X <op> cosh(time)`` is ``cosh(time) <rev op> X``.  ``acosh``
                # is strictly increasing on ``[0, inf)``, so mapping the
                # threshold through it keeps this direction rather than
                # inverting the trigger: ``2 lt cosh(time)`` holds exactly
                # for ``t > acosh(2)``, and reversing gives ``gt``.
                operator = _REVERSED_COMPARISON_OPERATOR[operator]
            if not cosh_time(function_node):
                unsupported = True
                break
            threshold = fold_numeric(
                expand_functions(threshold_expression), resolve_constant
            )
            if threshold is None or not math.isfinite(threshold):
                unsupported = True
                break
            parsed.append((operator, float(threshold)))

        if unsupported or len(parsed) != len(terms):
            output.append(event)
            continue
        matching_rule = None
        for candidate in rules_by_variable.values():
            try:
                rule_expression = ast.parse(
                    re.sub(
                        r"\bif\s*\(",
                        "sbml_if(",
                        expand_functions(str(candidate.math or "")),
                        flags=re.I,
                    ),
                    mode="eval",
                ).body
            except (TypeError, ValueError, SyntaxError):
                continue
            if (
                isinstance(rule_expression, ast.Call)
                and isinstance(rule_expression.func, ast.Name)
                and rule_expression.func.id.lower() == "cosh"
                and len(rule_expression.args) == 1
                and isinstance(rule_expression.args[0], ast.Name)
                and rule_expression.args[0].id.lower() == "time"
            ):
                matching_rule = candidate
                break
        if matching_rule is None:
            output.append(event)
            continue

        if len(parsed) == 1:
            operator, threshold = parsed[0]
            if operator not in {"gt", "geq"}:
                output.append(event)
                continue
            trigger_time = 0.0 if threshold < 1 else math.acosh(threshold)
            output.append(
                replace(
                    event,
                    trigger=f"geq(time, {_format_number(trigger_time)})",
                )
            )
            continue

        lower = next((item for item in parsed if item[0] in {"gt", "geq"}), None)
        upper = next((item for item in parsed if item[0] in {"lt", "leq"}), None)
        if lower is None or upper is None or lower[1] <= 1 or upper[1] <= lower[1]:
            output.append(event)
            continue
        lower_time = math.acosh(lower[1])
        upper_time = math.acosh(upper[1])
        lower_operator = "geq" if lower[0] == "geq" else "gt"
        upper_operator = "leq" if upper[0] == "leq" else "lt"
        rewritten = (
            f"and({lower_operator}(time, {_format_number(lower_time)}), "
            f"{upper_operator}(time, {_format_number(upper_time)}))"
        )
        output.append(replace(event, trigger=rewritten))
    return output


def expand_static_parameter_event_system(
    events: Sequence[SBMLEvent],
    *,
    t_end: float,
    parameter_ids: Sequence[str],
    resolve_initial: Callable[[str], Optional[float]],
    affine_rate_parameters: Optional[Mapping[str, float]] = None,
    expand_functions: Callable[[str], str] = lambda expression: expression,
) -> Optional[List[SBMLEvent]]:
    """Compile parameter-only event systems into fixed-time events.

    Optional affine rate rules are limited to parameters with constant slopes.
    Returns ``None`` unless every trigger, delay, priority, and assignment can
    be simulated exactly over the requested horizon.
    """
    if not math.isfinite(float(t_end)) or t_end < 0:
        return None
    events = [event for event in events if str(event.trigger or "").strip()]
    if not events:
        return []

    parameter_names = {standardize_name(name): name for name in parameter_ids}
    if len(parameter_names) != len(parameter_ids):
        return None
    affine_rates = {
        standardize_name(identifier): float(slope)
        for identifier, slope in (affine_rate_parameters or {}).items()
    }
    if any(
        identifier not in parameter_names or not math.isfinite(slope)
        for identifier, slope in affine_rates.items()
    ):
        return None
    values: dict[str, float] = {}
    for normalized, identifier in parameter_names.items():
        initial = resolve_initial(identifier)
        if initial is None or not math.isfinite(float(initial)):
            return None
        values[normalized] = float(initial)

    initial_values = dict(values)

    def resolve_state(
        identifier: str, state: Mapping[str, float], time_value: float
    ) -> Optional[float]:
        if identifier.lower() == "pi":
            return math.pi
        if identifier.lower() == "exponentiale":
            return math.e
        normalized = standardize_name(identifier)
        if normalized in affine_rates:
            value = initial_values[normalized] + affine_rates[normalized] * time_value
            return value if math.isfinite(value) else None
        return state.get(normalized)

    def evaluate(
        expression: str, state: Mapping[str, float], time_value: Optional[float] = None
    ) -> Optional[float]:
        expanded = expand_functions(str(expression or ""))
        current_time = 0.0 if time_value is None else float(time_value)
        expanded = re.sub(
            r"\btime\b", _format_number(current_time), expanded, flags=re.IGNORECASE
        )
        expanded = re.sub(r"\bif\s*\(", "_event_if(", expanded, flags=re.IGNORECASE)

        class RateHistoryRewriter(ast.NodeTransformer):
            def condition_value(self, node: ast.AST) -> Optional[bool]:
                if isinstance(node, ast.Compare) and len(node.ops) == 1:
                    left = fold_numeric(
                        ast.unparse(self.visit(node.left)),
                        lambda name: resolve_state(name, state, current_time),
                    )
                    right = fold_numeric(
                        ast.unparse(self.visit(node.comparators[0])),
                        lambda name: resolve_state(name, state, current_time),
                    )
                    if left is None or right is None:
                        return None
                    operator = node.ops[0]
                    if isinstance(operator, ast.Eq):
                        return left == right
                    if isinstance(operator, ast.NotEq):
                        return left != right
                    if isinstance(operator, ast.Lt):
                        return left < right
                    if isinstance(operator, ast.LtE):
                        return left <= right
                    if isinstance(operator, ast.Gt):
                        return left > right
                    if isinstance(operator, ast.GtE):
                        return left >= right
                return None

            def visit_Call(self, node: ast.Call) -> ast.AST:
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id.lower() in {"if", "_event_if"}
                    and len(node.args) == 3
                ):
                    condition_value = self.condition_value(node.args[0])
                    if condition_value is not None:
                        branch = node.args[1] if condition_value else node.args[2]
                        return self.visit(branch)
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id.lower() == "rateof"
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Name)
                ):
                    slope = affine_rates.get(standardize_name(node.args[0].id))
                    if slope is not None:
                        return ast.copy_location(ast.Constant(value=slope), node)
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id.lower() == "delay"
                    and len(node.args) == 2
                    and isinstance(node.args[0], ast.Name)
                ):
                    identifier = standardize_name(node.args[0].id)
                    slope = affine_rates.get(identifier)
                    if slope is not None:
                        duration_expression = ast.unparse(self.visit(node.args[1]))
                        duration = fold_numeric(
                            duration_expression,
                            lambda name: resolve_state(name, state, current_time),
                        )
                        if (
                            duration is not None
                            and math.isfinite(duration)
                            and duration >= 0
                        ):
                            query_time = current_time - duration
                            value = initial_values[identifier] + slope * max(
                                0.0, query_time
                            )
                            if math.isfinite(value):
                                return ast.copy_location(
                                    ast.Constant(value=value), node
                                )
                return self.generic_visit(node)

        try:
            tree = ast.parse(expanded, mode="eval")
            expanded = ast.unparse(RateHistoryRewriter().visit(tree))
        except (TypeError, ValueError, SyntaxError):
            return None
        value = fold_numeric(
            expanded, lambda name: resolve_state(name, state, current_time)
        )
        return value if value is not None and math.isfinite(value) else None

    def parse_time_edge(trigger: str) -> Optional[Tuple[Optional[str], float]]:
        comparison = _match_comparison_call(trigger)
        arguments = _split_arguments(comparison[1]) if comparison is not None else None
        if comparison is None or arguments is None or len(arguments) != 2:
            return None
        operator = comparison[0]
        left, right = (_strip_outer_parens(value) for value in arguments)
        if operator in {"gt", "geq"}:
            time_expression, threshold_expression = left, right
        else:
            threshold_expression, time_expression = left, right
        offset: Optional[str] = None
        if time_expression.lower() != "time":
            offset_match = re.fullmatch(
                r"time\s*-\s*([A-Za-z_][A-Za-z0-9_]*)", time_expression, re.I
            )
            if offset_match is None:
                return None
            offset = standardize_name(offset_match.group(1))
            if offset not in parameter_names:
                return None
        if any(
            identifier.lower() not in {"pi", "exponentiale"}
            for identifier in re.findall(
                r"\b[A-Za-z_][A-Za-z0-9_]*\b", threshold_expression
            )
        ):
            return None
        threshold = evaluate(threshold_expression, values, 0.0)
        if threshold is None or threshold < 0:
            return None
        return offset, threshold

    def parse_affine_state_edge(
        trigger: str,
    ) -> Optional[Tuple[str, str, float]]:
        comparison = _match_comparison_call(trigger)
        arguments = _split_arguments(comparison[1]) if comparison is not None else None
        if comparison is None or arguments is None or len(arguments) != 2:
            return None
        operator = comparison[0]
        left, right = (_strip_outer_parens(value) for value in arguments)
        identifier: Optional[str] = None
        threshold_expression: Optional[str] = None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", left):
            candidate = standardize_name(left)
            if candidate in affine_rates:
                identifier = candidate
                threshold_expression = right
        if identifier is None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", right):
            candidate = standardize_name(right)
            if candidate in affine_rates:
                identifier = candidate
                threshold_expression = left
                # The state sits on the right, so the comparison reads
                # ``threshold <op> state``; rewrite it around the state
                # without flipping which way it points.
                operator = _REVERSED_COMPARISON_OPERATOR[operator]
        if identifier is None or threshold_expression is None:
            return None
        if any(
            name.lower() not in {"pi", "exponentiale"}
            for name in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", threshold_expression)
        ):
            return None
        threshold = evaluate(threshold_expression, values, 0.0)
        slope = affine_rates[identifier]
        rising = (operator in {"gt", "geq"} and slope > 0) or (
            operator in {"lt", "leq"} and slope < 0
        )
        if threshold is None or not rising:
            return None
        return identifier, operator, threshold

    triggers: List[str] = []
    time_edges: List[Optional[Tuple[Optional[str], float]]] = []
    state_edges: List[Optional[Tuple[str, str, float]]] = []
    delay_expressions: List[Optional[str]] = []
    targets: List[List[Tuple[str, str]]] = []
    for event in events:
        trigger = expand_functions(str(event.trigger or ""))
        time_edge = (
            parse_time_edge(trigger)
            if re.search(r"\btime\b", trigger, re.IGNORECASE)
            else None
        )
        if re.search(r"\btime\b", trigger, re.IGNORECASE) and time_edge is None:
            return None
        rate_symbols = [
            identifier
            for identifier in affine_rates
            if re.search(rf"\b{re.escape(identifier)}\b", trigger, re.IGNORECASE)
        ]
        state_edge = parse_affine_state_edge(trigger) if rate_symbols else None
        if rate_symbols and state_edge is None:
            return None
        identifiers = list(re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", trigger))
        if not trigger or any(
            standardize_name(match.group()) not in parameter_names
            for match in identifiers
            if match.group().lower() not in {"pi", "exponentiale", "time"}
            and not trigger[match.end() :].lstrip().startswith("(")
        ):
            return None
        trigger_value = evaluate(trigger, values, 0.0)
        if trigger_value is None:
            return None
        delay_expression = (
            None if not event.delay else expand_functions(str(event.delay))
        )
        event_targets: List[Tuple[str, str]] = []
        for assignment in event.assignments:
            variable, expression = _event_assignment(assignment)
            normalized = standardize_name(variable)
            if normalized not in parameter_names or normalized in affine_rates:
                return None
            event_targets.append((normalized, expand_functions(expression)))
        if not event_targets:
            return None
        triggers.append(trigger)
        time_edges.append(time_edge)
        state_edges.append(state_edge)
        delay_expressions.append(delay_expression)
        targets.append(event_targets)

    # A pending record keeps trigger-time values for SBML's snapshot option.
    pending: List[dict] = []
    trigger_truth = [
        (
            True
            if event.trigger_initial_value is None
            else bool(event.trigger_initial_value)
        )
        for event in events
    ]
    sequence = 0

    def state_edge_time(index: int) -> float:
        edge = state_edges[index]
        if edge is None:
            return math.inf
        identifier, _operator, threshold = edge
        slope = affine_rates[identifier]
        return (threshold - initial_values[identifier]) / slope

    def schedule_edges(time_value: float, previous: Sequence[bool]) -> None:
        nonlocal sequence
        for index, (event, expression) in enumerate(zip(events, triggers)):
            actual = (
                1.0
                if (
                    time_edges[index] is not None
                    and abs(
                        (values[time_edges[index][0]] if time_edges[index][0] else 0.0)
                        + time_edges[index][1]
                        - time_value
                    )
                    <= 1e-12
                )
                or (
                    state_edges[index] is not None
                    and abs(state_edge_time(index) - time_value) <= 1e-12
                )
                else evaluate(expression, values, time_value)
            )
            if actual is None:
                raise ValueError("trigger evaluation failed")
            current = bool(actual)
            if not previous[index] and current:
                delay = (
                    0.0
                    if delay_expressions[index] is None
                    else evaluate(delay_expressions[index], values, time_value)
                )
                if delay is None or delay < 0:
                    raise ValueError("delay evaluation failed")
                pending.append(
                    {
                        "index": index,
                        "due": time_value + delay,
                        "snapshot": dict(values),
                        "trigger_time": time_value,
                        "active": True,
                        "sequence": sequence,
                    }
                )
                sequence += 1
            if (
                previous[index]
                and not current
                and events[index].trigger_persistent is False
            ):
                for record in pending:
                    if record["index"] == index:
                        record["active"] = False
            trigger_truth[index] = current

    try:
        schedule_edges(0.0, trigger_truth)
        executions: List[Tuple[float, SBMLEvent]] = []
        count = 0
        current_time = 0.0
        while True:
            pending = [record for record in pending if record["active"]]
            next_due = min((record["due"] for record in pending), default=math.inf)
            clock_edges = {
                index: (values[offset] if offset else 0.0) + threshold
                for index, time_edge in enumerate(time_edges)
                if time_edge is not None and not trigger_truth[index]
                for offset, threshold in [time_edge]
                if (values[offset] if offset else 0.0) + threshold
                > current_time + 1e-12
            }
            state_clock_edges = {
                state_edge_time(index)
                for index, edge in enumerate(state_edges)
                if edge is not None
                and not trigger_truth[index]
                and state_edge_time(index) >= current_time - 1e-12
            }
            next_clock = min(
                [*clock_edges.values(), *state_clock_edges], default=math.inf
            )
            next_time = min(next_due, next_clock)
            if not math.isfinite(next_time) or next_time > float(t_end) + 1e-12:
                break
            if abs(next_clock - next_time) <= 1e-12:
                previous = list(trigger_truth)
                schedule_edges(next_time, previous)
            batch = [
                record for record in pending if abs(record["due"] - next_time) <= 1e-12
            ]
            pending = [record for record in pending if record not in batch]
            candidates = [
                record
                for record in batch
                if events[record["index"]].trigger_persistent is not False
                or bool(evaluate(triggers[record["index"]], values, next_time))
            ]
            while candidates:
                priority_values: List[Optional[float]] = []
                for record in candidates:
                    priority = events[record["index"]].priority
                    priority_value = (
                        None if not priority else evaluate(priority, values, next_time)
                    )
                    if priority and priority_value is None:
                        return None
                    priority_values.append(priority_value)

                def independent(records: Sequence[dict]) -> bool:
                    for left_record in records:
                        left_index = left_record["index"]
                        left_event = events[left_index]
                        left_targets = {target for target, _ in targets[left_index]}
                        left_assignment_reads = {
                            standardize_name(identifier)
                            for _target, expression in targets[left_index]
                            for identifier in re.findall(
                                r"\b[A-Za-z_][A-Za-z0-9_]*\b", expression
                            )
                        }
                        for right_record in records:
                            if (
                                right_record is left_record
                                or right_record["index"] == left_index
                            ):
                                continue
                            right_index = right_record["index"]
                            right_event = events[right_index]
                            right_targets = {
                                target for target, _ in targets[right_index]
                            }
                            for shared_target in left_targets & right_targets:
                                left_expression = dict(targets[left_index])[
                                    shared_target
                                ]
                                right_expression = dict(targets[right_index])[
                                    shared_target
                                ]
                                left_uses_trigger_values = (
                                    left_event.use_values_from_trigger_time
                                )
                                right_uses_trigger_values = (
                                    right_event.use_values_from_trigger_time
                                )
                                left_value = evaluate(
                                    left_expression,
                                    (
                                        left_record["snapshot"]
                                        if left_uses_trigger_values
                                        else values
                                    ),
                                    (
                                        left_record["trigger_time"]
                                        if left_uses_trigger_values
                                        else next_time
                                    ),
                                )
                                right_value = evaluate(
                                    right_expression,
                                    (
                                        right_record["snapshot"]
                                        if right_uses_trigger_values
                                        else values
                                    ),
                                    (
                                        right_record["trigger_time"]
                                        if right_uses_trigger_values
                                        else next_time
                                    ),
                                )
                                if (
                                    left_value is None
                                    or right_value is None
                                    or left_value != right_value
                                ):
                                    return False
                            right_trigger_reads = {
                                standardize_name(identifier)
                                for identifier in re.findall(
                                    r"\b[A-Za-z_][A-Za-z0-9_]*\b",
                                    triggers[right_index],
                                )
                            }
                            right_priority_reads = {
                                standardize_name(identifier)
                                for identifier in re.findall(
                                    r"\b[A-Za-z_][A-Za-z0-9_]*\b",
                                    right_event.priority or "",
                                )
                            }
                            if (
                                right_event.trigger_persistent is False
                                and left_targets & right_trigger_reads
                            ):
                                return False
                            if (
                                right_event.priority
                                and left_targets & right_priority_reads
                            ):
                                return False
                            if not left_event.use_values_from_trigger_time and (
                                left_assignment_reads & right_targets
                            ):
                                return False
                    return True

                has_priority = any(value is not None for value in priority_values)
                has_unprioritized = any(value is None for value in priority_values)
                if has_priority and has_unprioritized and not independent(candidates):
                    return None
                if has_priority:
                    order = sorted(
                        range(len(candidates)),
                        key=lambda index: (
                            priority_values[index] is not None,
                            (
                                priority_values[index]
                                if priority_values[index] is not None
                                else 0.0
                            ),
                        ),
                        reverse=True,
                    )
                else:
                    order = list(range(len(candidates)))
                selected = order[0]
                selected_priority = priority_values[selected]
                tied = [
                    candidates[index]
                    for index, value in enumerate(priority_values)
                    if value == selected_priority
                ]
                if len(tied) > 1 and not independent(tied):
                    return None

                record = candidates.pop(selected)
                event_index = record["index"]
                event = events[event_index]
                count += 1
                if count > 10000:
                    return None
                pre_execution = dict(values)
                assignment_state = (
                    record["snapshot"]
                    if event.use_values_from_trigger_time
                    else pre_execution
                )
                assignment_time = (
                    record["trigger_time"]
                    if event.use_values_from_trigger_time
                    else next_time
                )
                updates: dict[str, float] = {}
                for target, expression in targets[event_index]:
                    if target in updates:
                        return None
                    value = evaluate(expression, assignment_state, assignment_time)
                    if value is None:
                        return None
                    updates[target] = value
                values.update(updates)

                materialized = replace(
                    event,
                    id=f"{event.id or 'event'}__static_{record['sequence'] + 1}",
                    trigger=f"geq(time, {_format_number(next_time)})",
                    delay=None,
                    trigger_initial_value=False,
                    trigger_persistent=True,
                    priority=None,
                    assignments=[
                        (parameter_names[target], _format_number(updates[target]))
                        for target, _expression in targets[record["index"]]
                    ],
                )
                executions.append((next_time, materialized))

                previous = list(trigger_truth)
                schedule_edges(next_time, previous)
                candidates = [
                    candidate
                    for candidate in candidates
                    if events[candidate["index"]].trigger_persistent is not False
                    or bool(evaluate(triggers[candidate["index"]], values, next_time))
                ]
                same_time = [
                    pending_record
                    for pending_record in pending
                    if pending_record["active"]
                    and abs(pending_record["due"] - next_time) <= 1e-12
                ]
                pending = [
                    pending_record
                    for pending_record in pending
                    if pending_record not in same_time
                ]
                candidates.extend(
                    pending_record
                    for pending_record in same_time
                    if events[pending_record["index"]].trigger_persistent is not False
                    or bool(
                        evaluate(triggers[pending_record["index"]], values, next_time)
                    )
                )
            current_time = next_time
        return [event for _time, event in executions]
    except (ArithmeticError, OverflowError, TypeError, ValueError):
        return None


def _parse_state_difference_threshold(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse a comparison between two state symbols as a zero threshold."""
    comparison = _match_comparison_call(trigger)
    if comparison is None:
        return None
    operator, arguments_text = comparison
    arguments = _split_arguments(arguments_text)
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(argument) for argument in arguments)
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    if re.fullmatch(identifier, left) and re.fullmatch(identifier, right):
        return f"({left}) - ({right})", operator, "0"
    return None


def _state_difference_components(expression: str) -> Optional[Tuple[str, str]]:
    """Return the two state IDs in the normalized ``left - right`` form."""
    match = re.fullmatch(
        r"\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*-\s*"
        r"\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?",
        str(expression or "").strip(),
    )
    return match.groups() if match is not None else None


def _parse_gated_affine_state_threshold(
    trigger: str, fold_static: Callable[[str], Optional[float]]
) -> Optional[Tuple[str, List[str], List[str], bool]]:
    """Parse one state threshold conjoined with fixed time bounds/constants."""
    terms = _split_call_arguments(str(trigger or "").strip())
    if terms is None:
        return None
    lower: List[str] = []
    upper: List[str] = []
    dynamic: List[str] = []
    for term in terms:
        comparison = _match_comparison_call(term)
        if comparison is not None:
            operator, arguments_text = comparison
            arguments = _split_arguments(arguments_text)
            if arguments is None or len(arguments) != 2:
                return None
            left, right = (_strip_outer_parens(value) for value in arguments)
            if left.lower() == "time" and "time" not in right.lower():
                (lower if operator in {"geq", "gt"} else upper).append(right)
                continue
            if right.lower() == "time" and "time" not in left.lower():
                (lower if operator in {"leq", "lt"} else upper).append(left)
                continue
        value = fold_static(term)
        if value is not None:
            if value == 0:
                return ("", [], [], False)
            continue
        dynamic.append(term)
    if len(dynamic) != 1 or not lower:
        return None
    if _parse_affine_state_threshold(dynamic[0]) is None:
        return None
    return dynamic[0], lower, upper, True


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


def _parse_delayed_affine_state_interval(
    trigger: str,
) -> Optional[Tuple[str, str, List[Tuple[str, str]]]]:
    """Parse a two-bound interval over one fixed-delay state history."""
    terms = _split_call_arguments(str(trigger or "").strip())
    if terms is None or len(terms) != 2:
        return None
    parsed: List[Tuple[str, str, str, str]] = []
    for term in terms:
        comparison = _match_comparison_call(term)
        if comparison is None:
            return None
        operator, arguments_text = comparison
        arguments = _split_arguments(arguments_text)
        if arguments is None or len(arguments) != 2:
            return None
        left, right = (_strip_outer_parens(value) for value in arguments)
        state = re.fullmatch(r"delay\s*\((.*)\)", left, re.I)
        bound = right
        if state is None:
            state = re.fullmatch(r"delay\s*\((.*)\)", right, re.I)
            if state is None:
                return None
            # The state is on the right, so the bound is on the left; keep the
            # comparison pointing the same way by reversing the relation.
            operator, bound = _REVERSED_COMPARISON_OPERATOR[operator], left
        delay_arguments = _split_arguments(state.group(1))
        if delay_arguments is None or len(delay_arguments) != 2:
            return None
        identifier = _strip_outer_parens(delay_arguments[0])
        delay = _strip_outer_parens(delay_arguments[1])
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            return None
        parsed.append((identifier, delay, operator, bound))
    identifiers = {item[0] for item in parsed}
    delays = {item[1] for item in parsed}
    operators = [item[2] for item in parsed]
    if (
        len(identifiers) != 1
        or len(delays) != 1
        or not any(operator in {"gt", "geq"} for operator in operators)
        or not any(operator in {"lt", "leq"} for operator in operators)
    ):
        return None
    return (
        next(iter(identifiers)),
        next(iter(delays)),
        [(operator, bound) for _identifier, _delay, operator, bound in parsed],
    )


def _parse_rate_of_state_threshold(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse one comparison between ``rateOf(state)`` and a constant."""

    comparison = _match_comparison_call(trigger)
    if comparison is None:
        return None
    operator, arguments_text = comparison
    arguments = _split_arguments(arguments_text)
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(value) for value in arguments)
    rate_of = re.compile(r"^rateof\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)$", re.I)
    left_match, right_match = rate_of.fullmatch(left), rate_of.fullmatch(right)
    if left_match is not None:
        return left_match.group(1), operator, right
    if right_match is not None:
        # ``constant <op> rateOf(state)`` reads around the state without
        # changing which way the comparison points.
        return right_match.group(1), _REVERSED_COMPARISON_OPERATOR[operator], left
    return None


def _parse_scaled_state_threshold(
    trigger: str,
    resolve_scale: Optional[Callable[[str], Optional[float]]] = None,
) -> Optional[Tuple[str, str, str, str]]:
    """Parse a comparison of one state times a constant expression."""

    comparison = _match_comparison_call(trigger)
    if comparison is None:
        return None
    operator, arguments_text = comparison
    arguments = _split_arguments(arguments_text)
    if arguments is None or len(arguments) != 2:
        return None
    left, right = (_strip_outer_parens(value) for value in arguments)

    def parse_scaled(value: str) -> List[Tuple[str, str]]:
        expression = _strip_outer_parens(value)
        try:
            parsed = ast.parse(expression, mode="eval").body
        except (TypeError, ValueError, SyntaxError):
            return []
        names = sorted(
            {
                node.id
                for node in ast.walk(parsed)
                if isinstance(node, ast.Name)
                and not any(
                    isinstance(parent, ast.Call) and parent.func is node
                    for parent in ast.walk(parsed)
                )
            }
        )

        def decompose(
            node: ast.AST, identifier: str
        ) -> Optional[Tuple[Optional[str], Optional[str]]]:
            """Return constant and linear terms; reject offsets/nonlinear forms."""
            if not any(
                isinstance(child, ast.Name) and child.id == identifier
                for child in ast.walk(node)
            ):
                return ast.unparse(node), None
            if isinstance(node, ast.Name) and node.id == identifier:
                return None, "1"
            if isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.UAdd, ast.USub)
            ):
                value = decompose(node.operand, identifier)
                if value is None:
                    return None
                sign = "-" if isinstance(node.op, ast.USub) else "+"
                return (
                    f"({sign}{value[0]})" if value[0] is not None else None,
                    f"({sign}{value[1]})" if value[1] is not None else None,
                )
            if isinstance(node, ast.BinOp):
                left_term = decompose(node.left, identifier)
                right_term = decompose(node.right, identifier)
                if left_term is None or right_term is None:
                    return None
                left_constant, left_linear = left_term
                right_constant, right_linear = right_term
                if isinstance(node.op, (ast.Add, ast.Sub)):
                    if left_linear is not None or right_linear is not None:
                        if left_constant is not None or right_constant is not None:
                            return None
                        operator = "+" if isinstance(node.op, ast.Add) else "-"
                        return None, f"({left_linear}) {operator} ({right_linear})"
                    return ast.unparse(node), None
                if isinstance(node.op, ast.Mult):
                    if left_linear is not None and right_linear is not None:
                        return None
                    if left_linear is not None:
                        return None, f"({left_linear}) * ({right_constant})"
                    if right_linear is not None:
                        return None, f"({left_constant}) * ({right_linear})"
                    return ast.unparse(node), None
                if isinstance(node.op, ast.Div):
                    if right_linear is not None:
                        return None
                    if left_linear is not None:
                        return None, f"({left_linear}) / ({right_constant})"
                    return ast.unparse(node), None
                if isinstance(node.op, ast.Pow) and right_linear is None:
                    try:
                        power = float(right_constant or "nan")
                    except ValueError:
                        return None
                    if power == 1 and left_linear is not None:
                        return None, left_linear
                    if left_linear is None:
                        return ast.unparse(node), None
            return None

        candidates = []
        for identifier in names:
            result = decompose(parsed, identifier)
            if result is None or result[0] is not None or result[1] is None:
                continue
            candidates.append((identifier, result[1]))
        if resolve_scale is not None:
            candidates = [
                candidate
                for candidate in candidates
                if (value := resolve_scale(candidate[1])) is not None
                and math.isfinite(value)
                and value != 0
            ]
        return candidates

    left_scaled = parse_scaled(left)
    if left_scaled:
        identifier, scale = left_scaled[0]
        return identifier, operator, right, scale
    right_scaled = parse_scaled(right)
    if right_scaled:
        identifier, scale = right_scaled[0]
        return identifier, _REVERSED_COMPARISON_OPERATOR[operator], left, scale
    return None


def _parse_periodic_reset_trigger(
    trigger: str,
) -> Optional[Tuple[str, str, str]]:
    """Parse ``time - reset >= interval`` with one reset symbol."""

    comparison = _match_comparison_call(trigger)
    if comparison is None or comparison[0] not in {"gt", "geq"}:
        return None
    operator, arguments_text = comparison
    arguments = _split_arguments(arguments_text)
    if arguments is None or len(arguments) != 2:
        return None
    elapsed, interval = (_strip_outer_parens(value) for value in arguments)
    elapsed_match = re.fullmatch(
        r"(?:minus|subtract)\s*\(\s*time\s*,\s*" r"([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        elapsed,
        re.IGNORECASE,
    )
    if elapsed_match is None:
        elapsed_match = re.fullmatch(
            r"time\s*-\s*([A-Za-z_][A-Za-z0-9_]*)", elapsed, re.IGNORECASE
        )
    return (elapsed_match.group(1), operator, interval) if elapsed_match else None


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


def _quadratic_state_at_time(
    initial: float, quadratic: float, linear: float, constant: float, time: float
) -> Optional[float]:
    if time < 0 or not all(
        math.isfinite(value) for value in (initial, quadratic, linear, constant, time)
    ):
        return None
    if time == 0:
        return initial
    scale = max(1.0, abs(quadratic), abs(linear), abs(constant))
    if abs(quadratic) <= 1e-14 * scale:
        if abs(linear) <= 1e-14 * scale:
            value = initial + constant * time
            return value if math.isfinite(value) else None
        equilibrium = -constant / linear
        try:
            value = equilibrium + (initial - equilibrium) * math.exp(linear * time)
        except OverflowError:
            return None
        return value if math.isfinite(value) else None
    discriminant = linear * linear - 4.0 * quadratic * constant
    tolerance = 1e-14 * max(1.0, linear * linear, abs(4.0 * quadratic * constant))
    if discriminant > tolerance:
        root = math.sqrt(discriminant)
        first = (-linear + root) / (2.0 * quadratic)
        second = (-linear - root) / (2.0 * quadratic)
        if abs(initial - first) <= tolerance or abs(initial - second) <= tolerance:
            return initial
        initial_ratio = (initial - first) / (initial - second)
        try:
            ratio = initial_ratio * math.exp(quadratic * (first - second) * time)
        except OverflowError:
            return None
        denominator = ratio - 1.0
        if not math.isfinite(ratio) or abs(denominator) <= 1e-14:
            return None
        value = (ratio * second - first) / denominator
    elif discriminant < -tolerance:
        root = math.sqrt(-discriminant)
        angle = math.atan((2.0 * quadratic * initial + linear) / root)
        angle += root * time / 2.0
        if angle >= math.pi / 2.0:
            return None
        value = (root * math.tan(angle) - linear) / (2.0 * quadratic)
    else:
        repeated = -linear / (2.0 * quadratic)
        delta = initial - repeated
        if delta == 0:
            return initial
        denominator = 1.0 - quadratic * delta * time
        if abs(denominator) <= 1e-14:
            return None
        value = repeated + delta / denominator
    return value if math.isfinite(value) else None


def _quadratic_crossing_time(
    initial: float,
    target: float,
    quadratic: float,
    linear: float,
    constant: float,
) -> Optional[float]:
    if not all(
        math.isfinite(value) for value in (initial, target, quadratic, linear, constant)
    ):
        return None
    if initial == target:
        return 0.0
    scale = max(1.0, abs(quadratic), abs(linear), abs(constant))
    if abs(quadratic) <= 1e-14 * scale:
        if abs(linear) <= 1e-14 * scale:
            return (target - initial) / constant if constant else None
        initial_derivative = linear * initial + constant
        if initial_derivative == 0:
            return None
        ratio = (target + constant / linear) / (initial + constant / linear)
        if ratio <= 0:
            return None
        time = math.log(ratio) / linear
    else:
        discriminant = linear * linear - 4.0 * quadratic * constant
        tolerance = 1e-14 * max(1.0, linear * linear, abs(4.0 * quadratic * constant))
        if discriminant > tolerance:
            root = math.sqrt(discriminant)
            first = (-linear + root) / (2.0 * quadratic)
            second = (-linear - root) / (2.0 * quadratic)
            if target == first or target == second:
                return None
            initial_ratio = (initial - first) / (initial - second)
            target_ratio = (target - first) / (target - second)
            ratio = target_ratio / initial_ratio if initial_ratio else -1.0
            if ratio <= 0 or not math.isfinite(ratio):
                return None
            time = math.log(ratio) / (quadratic * (first - second))
        elif discriminant < -tolerance:
            root = math.sqrt(-discriminant)
            initial_angle = math.atan((2.0 * quadratic * initial + linear) / root)
            target_angle = math.atan((2.0 * quadratic * target + linear) / root)
            time = 2.0 * (target_angle - initial_angle) / root
        else:
            repeated = -linear / (2.0 * quadratic)
            initial_delta = initial - repeated
            target_delta = target - repeated
            if initial_delta == 0 or target_delta == 0:
                return None
            time = (1.0 / initial_delta - 1.0 / target_delta) / quadratic
    return time if math.isfinite(time) and time >= 0 else None


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


def _render_sets(sets: Sequence[Tuple[str, str, float]]) -> List[str]:
    lines: List[str] = []
    for kind, target, value in sets:
        lines.append(_render_set(kind, target, value))
        if kind == "volume":
            # The importer uses this parameter for concentration conversion
            # and volume-scaled reaction laws. Keep it in sync with the
            # simulator's compartment size after a scheduled volume change.
            lines.append(
                f'setParameter("__compartment_{target}__", '
                f'"{_format_number(value)}")'
            )
    return lines


def synthesize_event_actions(
    events: Sequence[SBMLEvent], context: EventTranslationContext
) -> EventTranslationResult:
    """Translate safe fixed-time events and report all rejected events."""

    untranslated: List[Tuple[SBMLEvent, str]] = []
    scheduled: List[
        Tuple[
            float,
            List[Tuple[str, str, float]],
            float,
            Optional[SBMLEvent],
            bool,
            List[Tuple[str, float]],
        ]
    ] = []
    scheduled_values: List[Tuple[float, str, float]] = []
    horizon_limited = 0
    # Deterministic crossings cannot stand in for state changes caused by
    # stochastic reaction jumps.
    if context.method.lower() == "ssa" and not context.static_event_state:
        stochastic_events: List[SBMLEvent] = []
        for event in events:
            if parse_time_threshold(event.trigger) is None:
                untranslated.append(
                    (
                        event,
                        "state-triggered SBML events require stochastic jump "
                        "scheduling",
                    )
                )
            else:
                stochastic_events.append(event)
        events = stochastic_events

    def fold(
        expression: str,
        time_value: Optional[float] = None,
        dynamic_values: Optional[Mapping[str, float]] = None,
        event_context: Optional[SBMLEvent] = None,
    ) -> Optional[float]:
        if time_value is not None:
            expression = re.sub(
                r"\btime\b", _format_number(time_value), expression, flags=re.IGNORECASE
            )
        expression = context.expand_functions(expression)

        def resolve(identifier: str) -> Optional[float]:
            if dynamic_values is not None and identifier in dynamic_values:
                return dynamic_values[identifier]
            if event_context is not None:
                reaction_rate = context.resolve_reaction_rate_for_event(
                    identifier, event_context
                )
                if reaction_rate is not None:
                    return reaction_rate
            if context.is_compile_time_constant(identifier):
                value = context.resolve_param(identifier)
                if value is not None:
                    return value
            return context.resolve_constant(identifier)

        return fold_numeric(expression, resolve)

    def fold_initial(expression: str) -> Optional[float]:
        expression = context.expand_functions(str(expression or ""))
        expression = re.sub(r"\btime\b", "0", expression, flags=re.IGNORECASE)
        return fold_numeric(expression, context.resolve_initial_value)

    # Freeze an initial-state gate only when no distinct or delayed event can
    # change it before the shared trigger edge is queued.
    static_initial_gates_are_safe = (
        context.static_event_state
        and bool(events)
        and all(
            not str(event.delay or "").strip()
            and str(event.trigger or "").strip() == str(events[0].trigger or "").strip()
            and (
                not event.priority
                or fold(event.priority, event_context=event) is not None
            )
            for event in events
        )
    )

    def fold_static_event_gate(
        expression: str, event_context: SBMLEvent
    ) -> Optional[float]:
        value = fold(expression, event_context=event_context)
        if value is not None or not static_initial_gates_are_safe:
            return value
        return fold_initial(expression)

    def fold_at_state(
        expression: str,
        time_value: float,
        state_values: Optional[Mapping[str, float]] = None,
        event_context: Optional[SBMLEvent] = None,
        *,
        priority_evaluation: bool = False,
    ) -> Optional[float]:
        """Fold an event value using only proven state trajectories."""
        values = dict(state_values or {})
        expanded = context.expand_functions(str(expression or ""))

        def delayed_state_value(identifier: str, query_time: float) -> Optional[float]:
            if query_time <= 0:
                initial = context.resolve_initial_value(identifier)
                return float(initial) if initial is not None else None
            trajectory = (
                context.resolve_affine_rate_for_event(identifier, event_context)
                if event_context is not None
                else context.resolve_affine_rate(identifier)
            )
            if trajectory is not None:
                initial, slope = trajectory
                value = initial + slope * query_time
                return value if math.isfinite(value) else None
            exponential = (
                context.resolve_exponential_rate_for_event(identifier, event_context)
                if event_context is not None
                else context.resolve_exponential_rate(identifier)
            )
            if exponential is None:
                square_linear = (
                    context.resolve_square_linear_rate_for_event(
                        identifier, event_context
                    )
                    if event_context is not None
                    else None
                )
                if square_linear is None:
                    return None
                initial, squared_slope = square_linear
                radicand = initial * initial + squared_slope * query_time
                return math.sqrt(radicand) if radicand >= 0 else None
            initial, exponent = exponential
            try:
                value = initial * math.exp(exponent * query_time)
            except OverflowError:
                return None
            return value if math.isfinite(value) else None

        def rate_of_state_value(identifier: str, query_time: float) -> Optional[float]:
            affine = (
                context.resolve_affine_priority_rate(identifier, event_context)
                if priority_evaluation and event_context is not None
                else (
                    context.resolve_affine_rate_for_event(identifier, event_context)
                    if event_context is not None
                    else context.resolve_affine_rate(identifier)
                )
            )
            if affine is not None:
                return float(affine[1]) if math.isfinite(affine[1]) else None
            exponential = (
                context.resolve_exponential_rate_for_event(identifier, event_context)
                if event_context is not None
                else context.resolve_exponential_rate(identifier)
            )
            if exponential is not None:
                initial, exponent = exponential
                try:
                    rate = exponent * initial * math.exp(exponent * query_time)
                except OverflowError:
                    return None
                return rate if math.isfinite(rate) else None
            square_linear = (
                context.resolve_square_linear_rate_for_event(identifier, event_context)
                if event_context is not None
                else None
            )
            if square_linear is None:
                return None
            initial, squared_slope = square_linear
            radicand = initial * initial + squared_slope * query_time
            if radicand <= 0:
                return None
            rate = squared_slope / (2.0 * math.sqrt(radicand))
            return rate if math.isfinite(rate) else None

        class DelayHistoryRewriter(ast.NodeTransformer):
            def visit_Call(self, node: ast.Call) -> ast.AST:
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id.lower() == "rateof"
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Name)
                ):
                    value = rate_of_state_value(node.args[0].id, time_value)
                    if value is not None:
                        return ast.copy_location(ast.Constant(value=value), node)
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id.lower() == "delay"
                    and len(node.args) == 2
                    and isinstance(node.args[0], ast.Name)
                ):
                    duration = fold(
                        ast.unparse(node.args[1]), event_context=event_context
                    )
                    if (
                        duration is not None
                        and math.isfinite(duration)
                        and duration >= 0
                    ):
                        value = delayed_state_value(
                            node.args[0].id, time_value - duration
                        )
                        if value is not None:
                            return ast.copy_location(ast.Constant(value=value), node)
                return self.generic_visit(node)

        try:
            tree = ast.parse(expanded, mode="eval")
        except (TypeError, ValueError, SyntaxError):
            tree = None
        if tree is not None:
            expanded = ast.unparse(DelayHistoryRewriter().visit(tree))
        identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expanded))
        for identifier in identifiers:
            if identifier in values:
                continue
            if event_context is not None and context.static_event_state:
                prior_values = [
                    value
                    for execution_time, symbol, value in scheduled_values
                    if symbol == standardize_name(identifier)
                    and execution_time < time_value
                ]
                if prior_values:
                    values[identifier] = prior_values[-1]
                    continue
                initial = context.resolve_initial_value(identifier)
                if initial is not None and math.isfinite(initial):
                    values[identifier] = float(initial)
                    continue
            trajectory = (
                context.resolve_affine_priority_rate(identifier, event_context)
                if priority_evaluation and event_context is not None
                else (
                    context.resolve_affine_rate_for_event(identifier, event_context)
                    if event_context is not None
                    else context.resolve_affine_rate(identifier)
                )
            )
            try:
                if trajectory is not None:
                    initial, slope = trajectory
                    value = initial + slope * time_value
                else:
                    exponential = (
                        context.resolve_exponential_rate_for_event(
                            identifier, event_context
                        )
                        if event_context is not None
                        else context.resolve_exponential_rate(identifier)
                    )
                    if exponential is not None:
                        initial, exponent = exponential
                        value = initial * math.exp(exponent * time_value)
                    else:
                        square_linear = (
                            context.resolve_square_linear_rate_for_event(
                                identifier, event_context
                            )
                            if event_context is not None
                            else None
                        )
                        if square_linear is not None:
                            initial, squared_slope = square_linear
                            radicand = initial * initial + squared_slope * time_value
                            if radicand < 0:
                                continue
                            value = math.sqrt(radicand)
                        elif event_context is not None:
                            assignment_value = (
                                context.resolve_priority_assignment_value
                                if priority_evaluation
                                else context.resolve_assignment_rule_value_for_event
                            )(identifier, time_value, event_context, values)
                            if assignment_value is not None:
                                value = assignment_value
                            else:
                                initial_parameter = (
                                    context.resolve_priority_initial_parameter_value(
                                        identifier
                                    )
                                    if priority_evaluation
                                    else None
                                )
                                earlier_parameter_write = any(
                                    standardize_name(symbol)
                                    == standardize_name(identifier)
                                    and execution_time < time_value
                                    for execution_time, symbol, _value in scheduled_values
                                )
                                if (
                                    initial_parameter is not None
                                    and math.isfinite(initial_parameter)
                                    and not earlier_parameter_write
                                ):
                                    values[identifier] = float(initial_parameter)
                                    continue
                                reaction_rate = (
                                    context.resolve_priority_reaction_rate_for_event(
                                        identifier, event_context, values
                                    )
                                    if priority_evaluation
                                    else context.resolve_reaction_rate_for_event(
                                        identifier, event_context
                                    )
                                )
                                if reaction_rate is None:
                                    continue
                                value = reaction_rate
                        else:
                            continue
            except OverflowError:
                continue
            if math.isfinite(value):
                values[identifier] = value

        def numeric_ast(node: ast.AST) -> Optional[float | bool]:
            if isinstance(node, ast.Constant) and isinstance(
                node.value, (int, float, bool)
            ):
                return node.value
            if isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.UAdd, ast.USub, ast.Not)
            ):
                value = numeric_ast(node.operand)
                if value is None:
                    return None
                if isinstance(node.op, ast.Not):
                    return not bool(value)
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
            ):
                left, right = numeric_ast(node.left), numeric_ast(node.right)
                if left is None or right is None:
                    return None
                try:
                    if isinstance(node.op, ast.Add):
                        return left + right
                    if isinstance(node.op, ast.Sub):
                        return left - right
                    if isinstance(node.op, ast.Mult):
                        return left * right
                    if isinstance(node.op, ast.Div):
                        return left / right if right != 0 else None
                    return left**right
                except (OverflowError, TypeError, ValueError, ZeroDivisionError):
                    return None
            if isinstance(node, ast.Compare) and len(node.ops) == 1:
                left, right = numeric_ast(node.left), numeric_ast(node.comparators[0])
                if left is None or right is None:
                    return None
                operator = node.ops[0]
                if isinstance(operator, ast.Lt):
                    return left < right
                if isinstance(operator, ast.LtE):
                    return left <= right
                if isinstance(operator, ast.Gt):
                    return left > right
                if isinstance(operator, ast.GtE):
                    return left >= right
                if isinstance(operator, ast.Eq):
                    return left == right
                if isinstance(operator, ast.NotEq):
                    return left != right
            return None

        class TimeConditionalRewriter(ast.NodeTransformer):
            def visit_Call(self, node: ast.Call) -> ast.AST:
                node = self.generic_visit(node)
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "_event_if"
                    and len(node.args) == 3
                ):
                    condition = numeric_ast(node.args[0])
                    if condition is not None:
                        return self.visit(node.args[1 if bool(condition) else 2])
                return node

        timed_expression = re.sub(
            r"\btime\b", _format_number(time_value), expanded, flags=re.IGNORECASE
        )
        timed_expression = re.sub(
            r"\bif\s*\(", "_event_if(", timed_expression, flags=re.IGNORECASE
        )
        try:
            timed_tree = ast.parse(timed_expression, mode="eval")
            reduced_expression = ast.unparse(
                TimeConditionalRewriter().visit(timed_tree)
            )
            reduced_expression = reduced_expression.replace("_event_if(", "if(")
        except (TypeError, ValueError, SyntaxError):
            reduced_expression = timed_expression.replace("_event_if(", "if(")
        return fold(reduced_expression, dynamic_values=values)

    def simultaneous_priority_group_eligible(
        event: SBMLEvent,
        trigger_time: float,
        execution_time: float,
        delay: float,
    ) -> bool:
        if trigger_time <= 0 or len(events) < 2:
            return False
        threshold = parse_time_threshold(event.trigger)
        if threshold is None:
            return False
        for other_event in events:
            if other_event.trigger.strip() != event.trigger.strip():
                return False
            if (
                other_event.trigger_initial_value != event.trigger_initial_value
                or not other_event.use_values_from_trigger_time
            ):
                return False
            other_threshold = parse_time_threshold(other_event.trigger)
            if other_threshold is None:
                return False
            other_trigger_time = fold(other_threshold, event_context=other_event)
            if (
                other_trigger_time is None
                or abs(other_trigger_time - trigger_time) > 1e-12
            ):
                return False
            other_delay = (
                fold_at_state(
                    other_event.delay,
                    other_trigger_time,
                    event_context=other_event,
                )
                if other_event.delay
                else 0.0
            )
            if (
                other_delay is None
                or not math.isfinite(other_delay)
                or other_delay < 0
                or abs(other_delay - delay) > 1e-12
                or abs(other_trigger_time + other_delay - execution_time) > 1e-12
            ):
                return False
        return True

    periodic_groups: dict[Tuple[str, str, float], List[SBMLEvent]] = {}
    periodic_handled: set[int] = set()
    periodic_converted = 0
    periodic_target_ids: set[str] = set()
    periodic_rate_state_ids: set[str] = set()
    periodic_changes: List[Tuple[float, Mapping[str, float]]] = []
    periodic_initial_values: dict[str, float] = {}
    event_proven_inactive: set[int] = set()
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
            else (
                initial_reset >= threshold
                if operator == "geq"
                else (
                    initial_reset < threshold
                    if operator == "lt"
                    else initial_reset <= threshold
                )
            )
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

    # A single exponential rate-rule state can be reset to a fixed value by
    # its own threshold event. A monotone trajectory gives an exact recurrence
    # for each later rising edge and execution time.
    for event in events:
        if id(event) in periodic_handled or len(events) != 1:
            continue
        parsed = _parse_affine_state_threshold(event.trigger)
        if parsed is None:
            continue
        identifier, operator, threshold_expression = parsed
        threshold = fold(threshold_expression)
        trajectory = context.resolve_exponential_rate_for_event(identifier, event)
        assignments = [_event_assignment(item) for item in event.assignments]
        delay = 0.0 if not event.delay else fold(event.delay)
        if (
            threshold is None
            or trajectory is None
            or delay is None
            or not math.isfinite(delay)
            or delay < 0
            or not assignments
            or sum(variable == identifier for variable, _ in assignments) != 1
            or len({variable for variable, _ in assignments}) != len(assignments)
            or any(
                not context.is_param(variable)
                and not context.resolve_species_pattern(variable)
                for variable, _ in assignments
            )
            or (event.priority and fold(event.priority) is None)
        ):
            continue
        assignment_values = {
            variable: fold(expression) for variable, expression in assignments
        }
        if any(
            value is None or not math.isfinite(float(value))
            for value in assignment_values.values()
        ):
            continue
        reset_value = assignment_values[identifier]
        initial, exponent = trajectory
        threshold = float(threshold)
        if (
            not math.isfinite(initial)
            or not math.isfinite(exponent)
            or exponent == 0
            or not math.isfinite(threshold)
            or threshold <= 0
        ):
            continue
        reset_value = float(reset_value)
        if not math.isfinite(reset_value) or reset_value <= 0:
            continue
        rising = (operator in {"lt", "leq"} and exponent < 0) or (
            operator in {"gt", "geq"} and exponent > 0
        )
        if not rising:
            continue
        reset_is_false = (
            reset_value >= threshold
            if operator == "lt"
            else (
                reset_value > threshold
                if operator == "leq"
                else (
                    reset_value <= threshold
                    if operator == "gt"
                    else reset_value < threshold
                )
            )
        )
        if not reset_is_false:
            continue

        initially_true = (
            initial > threshold
            if operator == "gt"
            else (
                initial >= threshold
                if operator == "geq"
                else initial < threshold if operator == "lt" else initial <= threshold
            )
        )
        if initially_true:
            if event.trigger_initial_value:
                periodic_handled.add(id(event))
                periodic_converted += 1
                continue
            first_trigger = 0.0
        else:
            ratio = threshold / initial if initial != 0 else math.nan
            if ratio <= 0 or not math.isfinite(ratio):
                continue
            first_trigger = math.log(ratio) / exponent
            if not math.isfinite(first_trigger) or first_trigger < 0:
                continue
            if first_trigger > context.base_t_end + 1e-12:
                periodic_handled.add(id(event))
                horizon_limited += 1
                continue

        reset_ratio = threshold / reset_value
        if reset_ratio <= 0 or not math.isfinite(reset_ratio):
            continue
        period = math.log(reset_ratio) / exponent
        if not math.isfinite(period) or period <= 0:
            continue
        recurrence: List[Tuple[float, List[Tuple[str, str, float]], float]] = []
        trigger_time = first_trigger
        count = 0
        while trigger_time <= context.base_t_end + 1e-12:
            execution_time = trigger_time + float(delay)
            if not math.isfinite(execution_time):
                recurrence = []
                break
            recurrence.append(
                (
                    execution_time,
                    [
                        (
                            (
                                "conc"
                                if context.resolve_species_pattern(variable)
                                else "param"
                            ),
                            context.resolve_species_pattern(variable)
                            or standardize_name(variable),
                            float(value),
                        )
                        for variable, value in assignment_values.items()
                    ],
                    0.0,
                )
            )
            count += 1
            if count > 10_000:
                recurrence = []
                break
            trigger_time = execution_time + period
        if recurrence:
            scheduled.extend(recurrence)
            periodic_handled.add(id(event))
            periodic_converted += 1

    # A constant-slope rate-rule state can reset itself through an affine
    # assignment, with additional assignments limited to static values.
    # Preserve delayed-event semantics by evaluating the reset at trigger or
    # execution time as requested by SBML.
    for event in events:
        if id(event) in periodic_handled or len(events) != 1:
            continue
        parsed = _parse_affine_state_threshold(event.trigger)
        if parsed is None:
            continue
        identifier, operator, threshold_expression = parsed
        threshold = fold(threshold_expression)
        trajectory = context.resolve_affine_rate_for_event(identifier, event)
        assignments = [_event_assignment(item) for item in event.assignments]
        delay = 0.0 if not event.delay else fold(event.delay)
        is_parameter = context.is_param(identifier)
        species_target = (
            None if is_parameter else context.resolve_species_pattern(identifier)
        )
        assignment_map = dict(assignments)
        companion_values = {
            variable: fold(expression)
            for variable, expression in assignments
            if variable != identifier
        }
        if (
            threshold is None
            or trajectory is None
            or delay is None
            or not math.isfinite(delay)
            or delay < 0
            or len(assignment_map) != len(assignments)
            or identifier not in assignment_map
            or (not is_parameter and species_target is None)
            or any(
                not context.is_param(variable)
                and not context.resolve_species_pattern(variable)
                for variable in assignment_map
            )
            or any(
                value is None or not math.isfinite(value)
                for value in companion_values.values()
            )
            or (event.priority and fold(event.priority) is None)
        ):
            continue
        initial, slope = trajectory
        threshold = float(threshold)
        if (
            not math.isfinite(initial)
            or not math.isfinite(slope)
            or slope == 0
            or not math.isfinite(threshold)
        ):
            continue
        rising = (operator in {"lt", "leq"} and slope < 0) or (
            operator in {"gt", "geq"} and slope > 0
        )
        if not rising:
            continue
        initially_true = (
            initial > threshold
            if operator == "gt"
            else (
                initial >= threshold
                if operator == "geq"
                else initial < threshold if operator == "lt" else initial <= threshold
            )
        )
        if initially_true:
            if event.trigger_initial_value:
                periodic_handled.add(id(event))
                periodic_converted += 1
                continue
            first_trigger = 0.0
        else:
            first_trigger = (threshold - initial) / slope
            if not math.isfinite(first_trigger) or first_trigger < 0:
                continue

        assignment = assignment_map[identifier]
        trigger_state = initial if first_trigger == 0 and initially_true else threshold
        execution_state = trigger_state + slope * float(delay)
        value_time = (
            first_trigger
            if event.use_values_from_trigger_time
            else first_trigger + float(delay)
        )
        assignment_state = (
            trigger_state if event.use_values_from_trigger_time else execution_state
        )
        reset_value = fold_at_state(
            assignment,
            value_time,
            {identifier: assignment_state},
            event_context=event,
        )
        if reset_value is None or not math.isfinite(reset_value):
            continue

        def assignment_actions(self_value: float) -> List[Tuple[str, str, float]]:
            values = {identifier: self_value, **companion_values}
            actions: List[Tuple[str, str, float]] = []
            for variable in assignment_map:
                target_species = (
                    None
                    if context.is_param(variable)
                    else context.resolve_species_pattern(variable)
                )
                if target_species:
                    actions.append(("conc", target_species, float(values[variable])))
                else:
                    actions.append(
                        ("param", standardize_name(variable), float(values[variable]))
                    )
            return actions

        reset_is_false = (
            reset_value >= threshold
            if operator == "lt"
            else (
                reset_value > threshold
                if operator == "leq"
                else (
                    reset_value <= threshold
                    if operator == "gt"
                    else reset_value < threshold
                )
            )
        )
        if not reset_is_false:
            scheduled.append(
                (
                    first_trigger + float(delay),
                    assignment_actions(float(reset_value)),
                    0.0,
                    None,
                    False,
                    [],
                )
            )
            periodic_handled.add(id(event))
            periodic_converted += 1
            continue
        # Repeated resets need a closed-form recurrence. Keep that path
        # restricted to assignments that fold with the reset state alone.
        reset_value = fold(
            assignment,
            value_time,
            dynamic_values={identifier: assignment_state},
        )
        if reset_value is None or not math.isfinite(reset_value):
            continue
        period = (threshold - reset_value) / slope
        if not math.isfinite(period) or period <= 0:
            continue

        recurrence: List[Tuple[float, List[Tuple[str, str, float]], float]] = []
        trigger_time = first_trigger
        count = 0
        while trigger_time <= context.base_t_end + 1e-12:
            execution_time = trigger_time + float(delay)
            if not math.isfinite(execution_time):
                recurrence = []
                break
            trigger_state = (
                initial if trigger_time == 0 and initially_true else threshold
            )
            execution_state = trigger_state + slope * float(delay)
            assignment_state = (
                trigger_state if event.use_values_from_trigger_time else execution_state
            )
            value_time = (
                trigger_time if event.use_values_from_trigger_time else execution_time
            )
            value = fold(
                assignment, value_time, dynamic_values={identifier: assignment_state}
            )
            if value is None or not math.isfinite(value):
                recurrence = []
                break
            recurrence.append((execution_time, assignment_actions(float(value)), 0.0))
            count += 1
            if count > 10_000:
                recurrence = []
                break
            trigger_time = execution_time + period
        if recurrence:
            scheduled.extend(recurrence)
            periodic_handled.add(id(event))
            periodic_converted += 1

    affine_interval_schedules: dict[
        int,
        Tuple[str, str, float, float, float, float, float, float, str, str, float],
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
                    else (
                        initial >= threshold
                        if operator == "geq"
                        else (
                            initial < threshold
                            if operator == "lt"
                            else initial <= threshold
                        )
                    )
                )
                if not initially_true or event.trigger_initial_value:
                    static_event_no_action.add(id(event))
                else:
                    static_event_initial_fires[id(event)] = {identifier: initial}

    for event in events:
        if event.trigger_initial_value is not False:
            continue
        expression = context.expand_functions(event.trigger)
        identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expression))
        function_names = {
            name.lower()
            for name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", expression)
        }
        identifiers = {
            identifier
            for identifier in identifiers
            if identifier.lower() not in function_names
        }
        if not identifiers or "time" in {item.lower() for item in identifiers}:
            continue
        initial_values: dict[str, float] = {}
        statically_resolved = True
        for identifier in identifiers:
            if not context.is_param(identifier):
                statically_resolved = False
                break
            value = context.resolve_initial_value(identifier)
            if value is None or not math.isfinite(float(value)):
                statically_resolved = False
                break
            initial_values[identifier] = float(value)
        if not statically_resolved or any(
            other is not event
            and any(
                standardize_name(variable)
                in {standardize_name(identifier) for identifier in identifiers}
                for assignment in other.assignments
                for variable, _expression in [_event_assignment(assignment)]
            )
            for other in events
        ):
            continue
        initial_truth = fold(
            expression, dynamic_values=initial_values, event_context=event
        )
        if initial_truth == 1:
            static_event_initial_fires[id(event)] = initial_values

    for event in events:
        parsed_delayed_interval = _parse_delayed_affine_state_interval(event.trigger)
        parsed_interval = _parse_affine_state_interval(event.trigger)
        interval_shift = 0.0
        if parsed_delayed_interval is not None:
            identifier, delay_expression, comparisons = parsed_delayed_interval
            interval_shift_value = fold(delay_expression)
            if (
                interval_shift_value is None
                or not math.isfinite(interval_shift_value)
                or interval_shift_value < 0
            ):
                continue
            parsed_interval = (identifier, comparisons)
            interval_shift = float(interval_shift_value)
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
        trajectory_kind = "affine"
        if trajectory is None:
            exponential = context.resolve_exponential_rate_for_event(identifier, event)
            if exponential is not None:
                trajectory = exponential
                trajectory_kind = "exponential"
        if trajectory is None:
            continue
        initial, slope = trajectory
        if not math.isfinite(initial) or not math.isfinite(slope) or slope == 0:
            continue
        if trajectory_kind == "exponential" and any(
            standardize_name(variable) == standardize_name(identifier)
            for assignment in event.assignments
            for variable, _expression in [_event_assignment(assignment)]
        ):
            continue

        def inside_interval(value: float) -> bool:
            lower_ok = value > lower if lower_operator == "gt" else value >= lower
            upper_ok = value < upper if upper_operator == "lt" else value <= upper
            return lower_ok and upper_ok

        initially_inside = inside_interval(initial)
        if initially_inside and event.trigger_initial_value:
            affine_interval_no_action.add(id(event))
            continue
        if trajectory_kind == "affine":
            if slope > 0:
                entry = (
                    0.0
                    if initially_inside
                    else interval_shift + (lower - initial) / slope
                )
                exit_time = interval_shift + (upper - initial) / slope
            else:
                entry = (
                    0.0
                    if initially_inside
                    else interval_shift + (upper - initial) / slope
                )
                exit_time = interval_shift + (lower - initial) / slope
            entry_state = initial + slope * entry
        else:
            if initial <= 0 or lower <= 0 or upper <= 0:
                continue
            if slope > 0:
                entry = (
                    0.0
                    if initially_inside
                    else interval_shift + math.log(lower / initial) / slope
                )
                exit_time = interval_shift + math.log(upper / initial) / slope
                entry_state = initial if initially_inside else lower
            else:
                entry = (
                    0.0
                    if initially_inside
                    else interval_shift + math.log(upper / initial) / slope
                )
                exit_time = interval_shift + math.log(lower / initial) / slope
                entry_state = initial if initially_inside else upper
        if trajectory_kind == "exponential" and parsed_delayed_interval is not None:
            try:
                entry_state = initial * math.exp(slope * entry)
            except OverflowError:
                continue
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
            trajectory_kind,
            initial,
            slope,
            entry,
            lower,
            upper,
            exit_time,
            lower_operator,
            upper_operator,
            entry_state,
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

        comparison = _match_comparison_call(normalized)
        if comparison is not None:
            operation, arguments_text = comparison
            arguments = _split_arguments(arguments_text)
            if arguments is not None and len(arguments) == 2:
                left, right = (_strip_outer_parens(value) for value in arguments)
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
            event_proven_inactive.add(id(event))
            if periodic_target_ids:
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

    # A rate-rule state can remain below an absolute threshold while periodic
    # events update the parameters in its derivative. Integrate its exact
    # piecewise-constant slope across the already-proven event schedule.
    for event in events:
        if id(event) in periodic_handled or not periodic_changes:
            continue
        absolute_threshold = _match_comparison_call(event.trigger)
        if absolute_threshold is None or absolute_threshold[0] not in {"gt", "geq"}:
            continue
        arguments = _split_arguments(absolute_threshold[1])
        if arguments is None or len(arguments) != 2:
            continue
        absolute = re.fullmatch(
            r"abs\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
            arguments[0].strip(),
            re.IGNORECASE,
        )
        if absolute is None:
            continue
        identifier = absolute.group(1)
        threshold_expression = arguments[1]
        threshold = fold(threshold_expression, event_context=event)
        initial_value = context.resolve_initial_value(identifier)
        rate_expression = context.resolve_rate_rule_expression_for_event(
            identifier, event
        )
        if (
            threshold is None
            or not math.isfinite(threshold)
            or threshold <= 0
            or initial_value is None
            or not math.isfinite(initial_value)
            or rate_expression is None
            or any(
                standardize_name(variable) == standardize_name(identifier)
                for assignment in event.assignments
                for variable, _expression in [_event_assignment(assignment)]
            )
            or any(
                standardize_name(variable) == standardize_name(identifier)
                for other in events
                if other is not event
                for assignment in other.assignments
                for variable, _expression in [_event_assignment(assignment)]
            )
        ):
            continue
        rate_symbols = {
            symbol
            for symbol in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*", context.expand_functions(rate_expression)
            )
            if symbol.lower() not in {"pi", "exponentiale"}
        }
        if (
            not rate_symbols
            or rate_symbols & periodic_rate_state_ids
            or any(
                context.resolve_rate_rule_expression_for_event(symbol, event)
                is not None
                for symbol in rate_symbols
            )
            or not rate_symbols.issubset(
                periodic_target_ids
                | {
                    symbol
                    for symbol in rate_symbols
                    if context.is_compile_time_constant(symbol)
                }
            )
            or any(
                id(other) not in periodic_handled
                and other is not event
                and any(
                    standardize_name(variable) == standardize_name(symbol)
                    for assignment in other.assignments
                    for variable, _expression in [_event_assignment(assignment)]
                    for symbol in rate_symbols
                )
                for other in events
            )
        ):
            continue

        dynamic_values = dict(initial_state)
        state_value = float(initial_value)
        current_time = 0.0

        def safely_below_threshold(value: float) -> bool:
            tolerance = 1e-12 * max(1.0, threshold, abs(value))
            return abs(value) < threshold - tolerance

        stays_below = safely_below_threshold(state_value)
        for change_time, changes in periodic_changes:
            if change_time < current_time or change_time > context.base_t_end:
                continue
            slope = fold(
                rate_expression,
                current_time,
                dynamic_values=dynamic_values,
                event_context=event,
            )
            if slope is None or not math.isfinite(slope):
                stays_below = False
                break
            state_value += float(slope) * (change_time - current_time)
            stays_below = stays_below and safely_below_threshold(state_value)
            dynamic_values.update(changes)
            current_time = change_time
        if stays_below:
            slope = fold(
                rate_expression,
                current_time,
                dynamic_values=dynamic_values,
                event_context=event,
            )
            if slope is None or not math.isfinite(slope):
                stays_below = False
            else:
                state_value += float(slope) * (context.base_t_end - current_time)
                stays_below = safely_below_threshold(state_value)
        if stays_below:
            event_proven_inactive.add(id(event))
            periodic_handled.add(id(event))
            self_targets = {
                variable
                for assignment in event.assignments
                for variable, _expression in [_event_assignment(assignment)]
                if context.is_param(variable)
            }
            self_initial_values = {
                target: context.resolve_initial_value(target) for target in self_targets
            }
            if any(value is None for value in self_initial_values.values()):
                periodic_handled.remove(id(event))
                event_proven_inactive.remove(id(event))
                continue
            periodic_target_ids.update(self_targets)
            periodic_initial_values.update(
                {target: float(value) for target, value in self_initial_values.items()}
            )
            initial_state.update(
                {target: float(value) for target, value in self_initial_values.items()}
            )
            periodic_converted += 1

    # A fixed-time trigger can use a mutable gate when prior periodic events
    # prove that gate true at the crossing and keep it true afterward.
    for event in events:
        if id(event) in periodic_handled or event.delay or event.priority:
            continue
        terms = _split_call_arguments(str(event.trigger or ""))
        if terms is None:
            continue
        time_terms = [
            term
            for term in terms
            if re.match(r"^geq\s*\(\s*time\s*,", term, re.IGNORECASE)
        ]
        if len(time_terms) != 1:
            continue
        threshold_expression = parse_time_threshold(time_terms[0])
        trigger_time = (
            fold(threshold_expression, event_context=event)
            if threshold_expression is not None
            else None
        )
        if (
            trigger_time is None
            or not math.isfinite(trigger_time)
            or trigger_time <= 0
            or trigger_time > context.base_t_end
        ):
            continue
        gate_terms = [term for term in terms if term != time_terms[0]]
        if not gate_terms:
            continue
        gate_symbols = {
            symbol
            for term in gate_terms
            for symbol in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", term)
            if symbol.lower() not in _RESERVED_TRIGGER_SYMBOLS
        }
        if (
            any(
                symbol not in periodic_target_ids
                and not context.is_compile_time_constant(symbol)
                for symbol in gate_symbols
            )
            or any(
                context.resolve_rate_rule_expression_for_event(symbol, event)
                is not None
                for symbol in gate_symbols
            )
            or any(
                id(other) not in periodic_handled
                and other is not event
                and any(
                    standardize_name(variable) == standardize_name(symbol)
                    for assignment in other.assignments
                    for variable, _expression in [_event_assignment(assignment)]
                    for symbol in gate_symbols
                )
                for other in events
            )
        ):
            continue

        def gate_is_true(values: Mapping[str, float]) -> bool:
            return all(
                (
                    value := fold(
                        term,
                        trigger_time,
                        dynamic_values=values,
                        event_context=event,
                    )
                )
                is not None
                and value != 0
                for term in gate_terms
            )

        values_before = dict(initial_state)
        values_after = dict(initial_state)
        for change_time, changes in periodic_changes:
            time_tolerance = 1e-12 * max(1.0, abs(trigger_time))
            same_time = abs(change_time - trigger_time) <= time_tolerance
            if change_time < trigger_time and not same_time:
                values_before.update(changes)
                values_after.update(changes)
            elif same_time:
                values_after.update(changes)
        if not gate_is_true(values_before) or not gate_is_true(values_after):
            continue
        gate_stays_true = True
        for change_time, changes in periodic_changes:
            if change_time <= trigger_time:
                continue
            values_after.update(changes)
            if not gate_is_true(values_after):
                gate_stays_true = False
                break
        if not gate_stays_true:
            continue

        assignments: List[Tuple[str, str, float]] = []
        event_targets: set[str] = set()
        for assignment in event.assignments:
            variable, expression = _event_assignment(assignment)
            if (
                not context.is_param(variable)
                or standardize_name(variable) in event_targets
                or standardize_name(variable) in gate_symbols
                or standardize_name(variable)
                in {standardize_name(target) for target in periodic_target_ids}
                or any(
                    other is not event
                    and any(
                        standardize_name(other_variable) == standardize_name(variable)
                        for other_assignment in other.assignments
                        for other_variable, _other_expression in [
                            _event_assignment(other_assignment)
                        ]
                    )
                    for other in events
                )
            ):
                assignments = []
                break
            value = fold(expression, trigger_time, event_context=event)
            if value is None or not math.isfinite(value):
                assignments = []
                break
            event_targets.add(standardize_name(variable))
            assignments.append(("param", standardize_name(variable), float(value)))
        if not assignments:
            continue
        scheduled.append((trigger_time, assignments, 0.0, event, False, []))
        scheduled_values.extend(
            (trigger_time, target, value) for _kind, target, value in assignments
        )
        periodic_handled.add(id(event))
        periodic_target_ids.update(event_targets)
        periodic_initial_values.update(
            {
                variable: float(value)
                for variable in event_targets
                if (value := context.resolve_initial_value(variable)) is not None
            }
        )
        periodic_converted += 1

    def fixed_execution_time(event: SBMLEvent) -> float:
        threshold = parse_time_threshold(event.trigger)
        if threshold is None:
            return math.inf
        trigger_time = fold(threshold, event_context=event)
        if trigger_time is None or not math.isfinite(trigger_time):
            return math.inf
        delay = (
            fold(event.delay, trigger_time, event_context=event) if event.delay else 0.0
        )
        if delay is None or not math.isfinite(delay) or delay < 0:
            return math.inf
        return trigger_time + delay

    ordered_events = (
        sorted(
            enumerate(events),
            key=lambda item: (fixed_execution_time(item[1]), item[0]),
        )
        if context.static_event_state
        else list(enumerate(events))
    )
    normal_converted = 0
    recurrent_handled: set[int] = set()
    if len(events) == 1 and context.method.lower() != "ssa":
        event = events[0]
        cycle_system = context.resolve_first_order_cycle_event_system()
        parsed_cycle_trigger = _parse_affine_state_threshold(event.trigger)
        if cycle_system is not None and parsed_cycle_trigger is not None:
            cycle_ids, cycle_rates = cycle_system
            identifier, operator, threshold_expression = parsed_cycle_trigger
            normalized_cycle_ids = [standardize_name(sid) for sid in cycle_ids]
            trigger_index = next(
                (
                    index
                    for index, sid in enumerate(normalized_cycle_ids)
                    if sid == standardize_name(identifier)
                ),
                None,
            )
            if trigger_index is not None:
                cycle_ids = cycle_ids[trigger_index:] + cycle_ids[:trigger_index]
                cycle_rates = cycle_rates[trigger_index:] + cycle_rates[:trigger_index]

            threshold_symbols = re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*", threshold_expression
            )
            delay_symbols = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", event.delay or "")
            threshold = fold(threshold_expression, event_context=event)
            delay_value = fold(event.delay, event_context=event) if event.delay else 0.0
            state_values = {
                sid: context.resolve_initial_value(sid) for sid in cycle_ids
            }
            cycle_event_is_supported = (
                trigger_index is not None
                and operator in {"lt", "leq", "gt", "geq"}
                and not event.priority
                and event.trigger_persistent
                and event.use_values_from_trigger_time
                and fold_initial(event.trigger) == 0
                and threshold is not None
                and math.isfinite(threshold)
                and delay_value is not None
                and math.isfinite(delay_value)
                and delay_value >= 0
                and all(
                    context.is_compile_time_constant(symbol)
                    for symbol in (*threshold_symbols, *delay_symbols)
                )
                and all(
                    value is not None and math.isfinite(value) and value >= 0
                    for value in state_values.values()
                )
                and abs(float(state_values[cycle_ids[0]]) - float(threshold))
                > 1e-13
                * max(
                    1e-300,
                    abs(float(threshold)),
                    abs(float(state_values[cycle_ids[0]])),
                )
            )
            assignment_targets: List[Tuple[str, str, str]] = []
            seen_targets: set[str] = set()
            if cycle_event_is_supported:
                for assignment in event.assignments:
                    variable, expression = _event_assignment(assignment)
                    normalized_variable = standardize_name(variable)
                    pattern = context.resolve_species_pattern(variable)
                    if (
                        normalized_variable not in normalized_cycle_ids
                        or pattern is None
                        or normalized_variable in seen_targets
                        or not str(expression or "").strip()
                    ):
                        cycle_event_is_supported = False
                        break
                    seen_targets.add(normalized_variable)
                    assignment_targets.append((variable, pattern, expression))
                if not assignment_targets:
                    cycle_event_is_supported = False

            if cycle_event_is_supported:
                current_values = tuple(float(state_values[sid]) for sid in cycle_ids)
                current_time = 0.0
                cycle_schedule = []
                pending_actions: List[
                    Tuple[
                        float,
                        List[Tuple[str, str, float]],
                        List[Tuple[str, float]],
                    ]
                ] = []
                trigger_active = False
                event_armed = True
                for _ in range(10_000):
                    remaining = float(context.base_t_end) - current_time
                    if remaining <= 1e-12:
                        break
                    crossing = _first_order_cycle_next_trigger_crossing(
                        current_values,
                        cycle_rates,
                        float(threshold),
                        operator,
                        remaining,
                    )
                    if crossing is None:
                        cycle_event_is_supported = False
                        break
                    crossing_delta, enters_true = crossing
                    crossing_time = (
                        current_time + crossing_delta
                        if math.isfinite(crossing_delta)
                        else math.inf
                    )
                    due_time = min(
                        (item[0] for item in pending_actions), default=math.inf
                    )
                    if not math.isfinite(crossing_time) and not math.isfinite(due_time):
                        break
                    if (
                        math.isfinite(crossing_time)
                        and math.isfinite(due_time)
                        and abs(crossing_time - due_time) <= 1e-12
                    ):
                        cycle_event_is_supported = False
                        break
                    if crossing_time < due_time:
                        trajectory = _first_order_cycle_trajectory(
                            current_values, cycle_rates
                        )
                        crossing_values = (
                            trajectory.state_at(crossing_delta)
                            if trajectory is not None
                            else None
                        )
                        if crossing_values is None:
                            cycle_event_is_supported = False
                            break
                        if enters_true == trigger_active:
                            cycle_event_is_supported = False
                            break
                        current_values = crossing_values
                        current_time = crossing_time
                        trigger_active = enters_true
                        if not enters_true:
                            event_armed = True
                        elif event_armed:
                            trigger_snapshot = dict(zip(cycle_ids, crossing_values))
                            next_values = dict(trigger_snapshot)
                            scheduled_sets = []
                            event_values = []
                            for variable, pattern, expression in assignment_targets:
                                value = fold_at_state(
                                    expression,
                                    crossing_time,
                                    state_values=trigger_snapshot,
                                    event_context=event,
                                )
                                if (
                                    value is None
                                    or not math.isfinite(value)
                                    or value < 0
                                ):
                                    cycle_event_is_supported = False
                                    break
                                scheduled_sets.append(("conc", pattern, float(value)))
                                normalized_variable = standardize_name(variable)
                                event_values.append((normalized_variable, float(value)))
                                target_id = next(
                                    sid
                                    for sid in cycle_ids
                                    if standardize_name(sid) == normalized_variable
                                )
                                next_values[target_id] = float(value)
                            if not cycle_event_is_supported:
                                break
                            event_armed = False
                            if delay_value > 0:
                                execution_time = crossing_time + float(delay_value)
                                if execution_time <= float(context.base_t_end) + 1e-12:
                                    pending_actions.append(
                                        (
                                            min(
                                                execution_time,
                                                float(context.base_t_end),
                                            ),
                                            scheduled_sets,
                                            event_values,
                                        )
                                    )
                            else:
                                trigger_target = next_values[cycle_ids[0]]
                                trigger_scale = max(
                                    1e-300,
                                    abs(float(threshold)),
                                    abs(trigger_target),
                                )
                                if (
                                    abs(trigger_target - float(threshold))
                                    <= 1e-13 * trigger_scale
                                ):
                                    cycle_event_is_supported = False
                                    break
                                cycle_schedule.append(
                                    (
                                        crossing_time,
                                        scheduled_sets,
                                        0.0,
                                        event,
                                        False,
                                        event_values,
                                    )
                                )
                                post_trigger = fold_at_state(
                                    event.trigger,
                                    crossing_time,
                                    state_values=next_values,
                                    event_context=event,
                                )
                                if post_trigger is None or not math.isfinite(
                                    post_trigger
                                ):
                                    cycle_event_is_supported = False
                                    break
                                trigger_active = post_trigger != 0
                                if not trigger_active:
                                    event_armed = True
                                current_values = tuple(
                                    next_values[sid] for sid in cycle_ids
                                )
                    else:
                        trajectory = _first_order_cycle_trajectory(
                            current_values, cycle_rates
                        )
                        due_delta = due_time - current_time
                        due_values = (
                            trajectory.state_at(due_delta)
                            if trajectory is not None
                            else None
                        )
                        if due_values is None:
                            cycle_event_is_supported = False
                            break
                        current_values = due_values
                        current_time = due_time
                        due = [
                            item
                            for item in pending_actions
                            if abs(item[0] - due_time) <= 1e-12
                        ]
                        if len(due) != 1:
                            cycle_event_is_supported = False
                            break
                        pending_actions = [
                            item for item in pending_actions if item is not due[0]
                        ]
                        next_values = dict(zip(cycle_ids, current_values))
                        for normalized_variable, value in due[0][2]:
                            target_id = next(
                                sid
                                for sid in cycle_ids
                                if standardize_name(sid) == normalized_variable
                            )
                            next_values[target_id] = value
                        post_trigger = fold_at_state(
                            event.trigger,
                            current_time,
                            state_values=next_values,
                            event_context=event,
                        )
                        if post_trigger is None or not math.isfinite(post_trigger):
                            cycle_event_is_supported = False
                            break
                        trigger_target = next_values[cycle_ids[0]]
                        trigger_scale = max(
                            1e-300,
                            abs(float(threshold)),
                            abs(trigger_target),
                        )
                        if (
                            abs(trigger_target - float(threshold))
                            <= 1e-13 * trigger_scale
                        ):
                            cycle_event_is_supported = False
                            break
                        trigger_after_action = post_trigger != 0
                        if not trigger_active and trigger_after_action:
                            cycle_event_is_supported = False
                            break
                        if trigger_active and not trigger_after_action:
                            event_armed = True
                        trigger_active = trigger_after_action
                        current_values = tuple(next_values[sid] for sid in cycle_ids)
                        cycle_schedule.append(
                            (
                                current_time,
                                due[0][1],
                                0.0,
                                event,
                                False,
                                due[0][2],
                            )
                        )
                else:
                    cycle_event_is_supported = False

                if cycle_event_is_supported:
                    scheduled.extend(cycle_schedule)
                    recurrent_handled.add(id(event))
                    normal_converted += 1
                    if not cycle_schedule:
                        event_proven_inactive.add(id(event))
                        horizon_limited += 1

    if len(events) == 2 and context.method.lower() != "ssa":
        transfer_system = context.resolve_first_order_transfer_event_system()
        if transfer_system is not None:
            source_id, sink_id, transfer_rate = transfer_system
            source_key = standardize_name(source_id)
            sink_key = standardize_name(sink_id)
            source_initial = context.resolve_initial_value(source_id)
            sink_initial = context.resolve_initial_value(sink_id)
            transfer_supported = (
                source_key != sink_key
                and source_initial is not None
                and sink_initial is not None
                and math.isfinite(float(source_initial))
                and math.isfinite(float(sink_initial))
                and float(source_initial) >= 0
                and float(sink_initial) >= 0
                and math.isfinite(float(transfer_rate))
                and float(transfer_rate) > 0
                and math.isfinite(float(context.base_t_end))
                and float(context.base_t_end) > 0
            )
            transfer_plans: List[
                Tuple[
                    SBMLEvent,
                    str,
                    str,
                    float,
                    float,
                    List[Tuple[str, str, str]],
                ]
            ] = []
            trigger_roles: set[str] = set()
            if transfer_supported:
                for event in events:
                    parsed = _parse_affine_state_threshold(event.trigger)
                    if parsed is None:
                        transfer_supported = False
                        break
                    identifier, operator, threshold_expression = parsed
                    normalized_identifier = standardize_name(identifier)
                    threshold_symbols = re.findall(
                        r"[A-Za-z_][A-Za-z0-9_]*",
                        context.expand_functions(threshold_expression),
                    )
                    delay_symbols = re.findall(
                        r"[A-Za-z_][A-Za-z0-9_]*",
                        context.expand_functions(event.delay or ""),
                    )
                    delay = (
                        0.0
                        if not event.delay
                        else fold(event.delay, event_context=event)
                    )
                    if normalized_identifier == source_key and operator == "lt":
                        trigger_role = "source"
                    elif normalized_identifier == sink_key and operator == "gt":
                        trigger_role = "sink"
                    else:
                        transfer_supported = False
                        break
                    threshold = fold(threshold_expression, event_context=event)
                    if (
                        threshold is None
                        or not math.isfinite(float(threshold))
                        or float(threshold) <= 0
                        or any(
                            standardize_name(symbol) in {source_key, sink_key, "time"}
                            for symbol in threshold_symbols
                        )
                        or delay is None
                        or not math.isfinite(float(delay))
                        or float(delay) < 0
                        or any(
                            standardize_name(symbol) in {source_key, sink_key, "time"}
                            for symbol in delay_symbols
                        )
                        or event.priority
                        or event.trigger_initial_value is not True
                        or event.trigger_persistent is not True
                        or event.use_values_from_trigger_time is not True
                        or trigger_role in trigger_roles
                    ):
                        transfer_supported = False
                        break
                    trigger_roles.add(trigger_role)
                    assignment_targets: List[Tuple[str, str, str]] = []
                    seen_targets: set[str] = set()
                    for assignment in event.assignments:
                        variable, expression = _event_assignment(assignment)
                        target_key = standardize_name(variable)
                        pattern = context.resolve_species_pattern(variable)
                        if (
                            target_key not in {source_key, sink_key}
                            or pattern is None
                            or target_key in seen_targets
                            or not str(expression or "").strip()
                        ):
                            transfer_supported = False
                            break
                        seen_targets.add(target_key)
                        assignment_targets.append((variable, pattern, expression))
                    if not transfer_supported or not assignment_targets:
                        transfer_supported = False
                        break
                    transfer_plans.append(
                        (
                            event,
                            identifier,
                            operator,
                            float(threshold),
                            float(delay),
                            assignment_targets,
                        )
                    )
            if transfer_supported and trigger_roles == {"source", "sink"}:
                transfer_state = {
                    source_id: float(source_initial),
                    sink_id: float(sink_initial),
                }
                transfer_active: List[bool] = []
                for (
                    _event,
                    identifier,
                    operator,
                    threshold,
                    _delay,
                    _assignments,
                ) in transfer_plans:
                    state_value = transfer_state.get(identifier)
                    if state_value is None:
                        transfer_supported = False
                        break
                    transfer_active.append(
                        state_value < threshold
                        if operator == "lt"
                        else state_value > threshold
                    )

                transfer_schedule: List[
                    Tuple[
                        float,
                        List[Tuple[str, str, float]],
                        float,
                        Optional[SBMLEvent],
                        bool,
                        List[Tuple[str, float]],
                    ]
                ] = []
                current_time = 0.0
                last_fired_at: dict[int, float] = {}
                pending: List[int] = []
                pending_actions: List[
                    Tuple[float, dict[str, Tuple[str, str, float]]]
                ] = []
                for _ in range(10_000):
                    if not transfer_supported:
                        break
                    if not pending:
                        candidates: List[Tuple[float, int]] = []
                        source_value = transfer_state[source_id]
                        sink_value = transfer_state[sink_id]
                        for index, plan in enumerate(transfer_plans):
                            if transfer_active[index]:
                                continue
                            (
                                _event,
                                identifier,
                                operator,
                                threshold,
                                _delay,
                                _assignments,
                            ) = plan
                            if (
                                standardize_name(identifier) == source_key
                                and operator == "lt"
                            ):
                                if source_value < threshold:
                                    transfer_supported = False
                                    break
                                delta = math.log(source_value / threshold) / float(
                                    transfer_rate
                                )
                            else:
                                available = source_value
                                fraction = (
                                    (threshold - sink_value) / available
                                    if available > 0
                                    else math.inf
                                )
                                if fraction < 0:
                                    transfer_supported = False
                                    break
                                if fraction >= 1 or not math.isfinite(fraction):
                                    continue
                                delta = -math.log1p(-fraction) / float(transfer_rate)
                            if not math.isfinite(delta) or delta < -1e-12:
                                transfer_supported = False
                                break
                            candidates.append((max(0.0, delta), index))
                        if not transfer_supported:
                            break
                        next_delta = (
                            min(candidate[0] for candidate in candidates)
                            if candidates
                            else math.inf
                        )
                        crossing_time = current_time + next_delta
                        due_time = min(
                            (action[0] for action in pending_actions),
                            default=math.inf,
                        )
                        simultaneous_tolerance = 1e-11 * max(
                            1.0,
                            abs(next_delta) if math.isfinite(next_delta) else 0.0,
                            (
                                abs(due_time - current_time)
                                if math.isfinite(due_time)
                                else 0.0
                            ),
                        )
                        if (
                            math.isfinite(crossing_time)
                            and due_time <= float(context.base_t_end) + 1e-12
                            and abs(crossing_time - due_time) <= simultaneous_tolerance
                        ):
                            transfer_supported = False
                            break

                        if (
                            due_time <= float(context.base_t_end) + 1e-12
                            and due_time < crossing_time
                        ):
                            due_delta = due_time - current_time
                            if due_delta < -1e-12:
                                transfer_supported = False
                                break
                            due_state = _first_order_transfer_state_at(
                                transfer_state[source_id],
                                transfer_state[sink_id],
                                float(transfer_rate),
                                max(0.0, due_delta),
                            )
                            if due_state is None:
                                transfer_supported = False
                                break
                            transfer_state[source_id], transfer_state[sink_id] = (
                                due_state
                            )
                            current_time = due_time
                            due_records = [
                                action
                                for action in pending_actions
                                if action[0] == due_time
                            ]
                            near_due_records = [
                                action[0]
                                for action in pending_actions
                                if abs(action[0] - due_time) <= simultaneous_tolerance
                            ]
                            if any(time != due_time for time in near_due_records):
                                transfer_supported = False
                                break
                            pending_actions = [
                                action
                                for action in pending_actions
                                if action[0] != due_time
                            ]
                            due_updates: dict[str, Tuple[str, str, float]] = {}
                            for _action_time, action_updates in due_records:
                                for target_key, update in action_updates.items():
                                    prior = due_updates.get(target_key)
                                    if prior is not None and prior[2] != update[2]:
                                        transfer_supported = False
                                        break
                                    due_updates[target_key] = update
                                if not transfer_supported:
                                    break
                            if not transfer_supported:
                                break
                            previous_active = list(transfer_active)
                            for target_key, (
                                variable,
                                _pattern,
                                value,
                            ) in due_updates.items():
                                actual_target = (
                                    source_id if target_key == source_key else sink_id
                                )
                                transfer_state[actual_target] = value
                            event_sets = [
                                ("conc", pattern, value)
                                for _variable, pattern, value in due_updates.values()
                            ]
                            event_values = [
                                (variable, value)
                                for variable, _pattern, value in due_updates.values()
                            ]
                            transfer_schedule.append(
                                (
                                    current_time,
                                    event_sets,
                                    0.0,
                                    None,
                                    False,
                                    event_values,
                                )
                            )
                            newly_triggered: List[int] = []
                            for index, plan in enumerate(transfer_plans):
                                (
                                    _event,
                                    identifier,
                                    operator,
                                    threshold,
                                    _delay,
                                    _assignments,
                                ) = plan
                                value = transfer_state[identifier]
                                is_active = (
                                    value < threshold
                                    if operator == "lt"
                                    else value > threshold
                                )
                                if not previous_active[index] and is_active:
                                    newly_triggered.append(index)
                                transfer_active[index] = is_active
                            pending = newly_triggered
                            continue

                        if not candidates:
                            break
                        next_time = crossing_time
                        if next_time > float(context.base_t_end) + 1e-12:
                            break
                        simultaneous_tolerance = 1e-11 * max(1.0, abs(next_delta))
                        near_simultaneous = [
                            delta
                            for delta, _index in candidates
                            if abs(delta - next_delta) <= simultaneous_tolerance
                        ]
                        if any(delta != next_delta for delta in near_simultaneous):
                            transfer_supported = False
                            break
                        next_state = _first_order_transfer_state_at(
                            transfer_state[source_id],
                            transfer_state[sink_id],
                            float(transfer_rate),
                            next_delta,
                        )
                        if next_state is None:
                            transfer_supported = False
                            break
                        transfer_state[source_id], transfer_state[sink_id] = next_state
                        current_time = min(next_time, float(context.base_t_end))
                        for index, plan in enumerate(transfer_plans):
                            (
                                _event,
                                identifier,
                                operator,
                                threshold,
                                _delay,
                                _assignments,
                            ) = plan
                            value = transfer_state[identifier]
                            transfer_active[index] = (
                                value < threshold
                                if operator == "lt"
                                else value > threshold
                            )
                        pending = [
                            index for delta, index in candidates if delta == next_delta
                        ]
                        for index in pending:
                            transfer_active[index] = True
                    if not pending:
                        continue

                    for index in pending:
                        previous = last_fired_at.get(index)
                        if (
                            previous is not None
                            and abs(previous - current_time) <= 1e-12
                        ):
                            transfer_supported = False
                            break
                    if not transfer_supported:
                        break

                    trigger_state = dict(transfer_state)
                    updates: dict[str, Tuple[str, str, float]] = {}
                    update_values: dict[str, float] = {}
                    for index in pending:
                        (
                            event,
                            _identifier,
                            _operator,
                            _threshold,
                            _delay,
                            assignments,
                        ) = transfer_plans[index]
                        for variable, pattern, expression in assignments:
                            value = fold_at_state(
                                expression,
                                current_time,
                                state_values=trigger_state,
                                event_context=event,
                            )
                            if value is None or not math.isfinite(value) or value < 0:
                                transfer_supported = False
                                break
                            target_key = standardize_name(variable)
                            prior_value = update_values.get(target_key)
                            if prior_value is not None and prior_value != float(value):
                                transfer_supported = False
                                break
                            if prior_value is None:
                                updates[target_key] = (variable, pattern, float(value))
                                update_values[target_key] = float(value)
                        if not transfer_supported:
                            break
                    if not transfer_supported:
                        break

                    event_sets = [
                        ("conc", pattern, value)
                        for _variable, pattern, value in updates.values()
                    ]
                    event_values = [
                        (variable, value)
                        for variable, _pattern, value in updates.values()
                    ]
                    event_delays = {transfer_plans[index][4] for index in pending}
                    if len(event_delays) != 1:
                        transfer_supported = False
                        break
                    delay = next(iter(event_delays))
                    for index in pending:
                        last_fired_at[index] = current_time
                    if delay > 0:
                        execution_time = current_time + delay
                        if not math.isfinite(execution_time):
                            transfer_supported = False
                            break
                        if execution_time <= float(context.base_t_end) + 1e-12:
                            pending_actions.append(
                                (
                                    min(execution_time, float(context.base_t_end)),
                                    updates,
                                )
                            )
                        pending = []
                        continue

                    for target_key, (variable, _pattern, value) in updates.items():
                        actual_target = (
                            source_id if target_key == source_key else sink_id
                        )
                        transfer_state[actual_target] = value
                    transfer_schedule.append(
                        (current_time, event_sets, 0.0, None, False, event_values)
                    )

                    newly_triggered: List[int] = []
                    for index, plan in enumerate(transfer_plans):
                        was_active = transfer_active[index]
                        (
                            _event,
                            identifier,
                            operator,
                            threshold,
                            _delay,
                            _assignments,
                        ) = plan
                        value = transfer_state[identifier]
                        is_active = (
                            value < threshold if operator == "lt" else value > threshold
                        )
                        if not was_active and is_active:
                            newly_triggered.append(index)
                        transfer_active[index] = is_active
                    pending = newly_triggered
                else:
                    transfer_supported = False

                if transfer_supported:
                    scheduled.extend(transfer_schedule)
                    recurrent_handled.update(id(event) for event in events)
                    normal_converted += len(events)
                    if not transfer_schedule:
                        horizon_limited += len(events)

    if (
        len(events) == 1
        and context.method.lower() != "ssa"
        and id(events[0]) not in recurrent_handled
    ):
        event = events[0]
        chain = context.resolve_first_order_chain_event_system()
        parsed = _parse_affine_state_threshold(event.trigger)
        chain_supported = chain is not None and parsed is not None
        if chain_supported:
            assert chain is not None and parsed is not None
            (
                source_id,
                intermediate_id,
                product_id,
                first_rate,
                second_rate,
            ) = chain
            identifier, operator, threshold_expression = parsed
            threshold = fold(threshold_expression, event_context=event)
            delay = fold(event.delay, event_context=event) if event.delay else 0.0
            initial_values = {
                name: context.resolve_initial_value(name)
                for name in (source_id, intermediate_id, product_id)
            }
            chain_supported = (
                standardize_name(identifier) == standardize_name(product_id)
                and operator in {"gt", "geq"}
                and threshold is not None
                and math.isfinite(float(threshold))
                and delay is not None
                and math.isfinite(float(delay))
                and float(delay) >= 0
                and (float(delay) == 0 or event.trigger_persistent is not False)
                and math.isfinite(float(first_rate))
                and math.isfinite(float(second_rate))
                and float(first_rate) > 0
                and float(second_rate) > 0
                and all(
                    value is not None
                    and math.isfinite(float(value))
                    and float(value) >= 0
                    for value in initial_values.values()
                )
                and not event.priority
                and len(event.assignments) == 1
            )
            if chain_supported:
                variable, assignment_expression = _event_assignment(
                    event.assignments[0]
                )
                assignment_value = fold(assignment_expression, event_context=event)
                chain_supported = (
                    standardize_name(variable) == standardize_name(product_id)
                    and assignment_value is not None
                    and math.isfinite(float(assignment_value))
                    and (
                        operator != "gt" or float(assignment_value) != float(threshold)
                    )
                )
            if chain_supported:
                assert threshold is not None and assignment_value is not None
                source = float(initial_values[source_id])
                intermediate = float(initial_values[intermediate_id])
                product = float(initial_values[product_id])
                threshold_value = float(threshold)
                assignment_number = float(assignment_value)
                horizon = float(context.base_t_end)
                delay_value = float(delay)
                current_time = 0.0
                initially_active = (
                    product > threshold_value
                    if operator == "gt"
                    else product >= threshold_value
                )
                pending_initial = initially_active and not event.trigger_initial_value
                active = initially_active
                chain_schedule: List[
                    Tuple[
                        float,
                        List[Tuple[str, str, float]],
                        float,
                        Optional[SBMLEvent],
                        bool,
                        List[Tuple[str, float]],
                    ]
                ] = []
                pending_due: Optional[float] = None

                def terminal_after(
                    elapsed: float,
                ) -> Optional[Tuple[float, float, float]]:
                    states = _first_order_chain_state_at(
                        source,
                        intermediate,
                        float(first_rate),
                        float(second_rate),
                        elapsed,
                    )
                    if states is None:
                        return None
                    next_source, next_intermediate = states
                    next_product = (
                        product
                        + source
                        + intermediate
                        - next_source
                        - next_intermediate
                    )
                    if not math.isfinite(next_product) or next_product < -1e-12:
                        return None
                    return max(0.0, next_product), next_source, next_intermediate

                chain_valid = True
                for _ in range(10_000):
                    if pending_due is not None:
                        if pending_due > horizon:
                            chain_valid = False
                            break
                        due_state = terminal_after(pending_due - current_time)
                        if due_state is None:
                            chain_valid = False
                            break
                        current_time = pending_due
                        product, source, intermediate = due_state
                        pending_due = None
                        pattern = context.resolve_species_pattern(variable)
                        if pattern is None:
                            chain_valid = False
                            break
                        chain_schedule.append(
                            (
                                current_time,
                                [("conc", pattern, assignment_number)],
                                0.0,
                                event,
                                False,
                                [(standardize_name(variable), assignment_number)],
                            )
                        )
                        product = assignment_number
                        active = (
                            product > threshold_value
                            if operator == "gt"
                            else product >= threshold_value
                        )
                        if current_time >= horizon or active:
                            break
                        continue

                    crossing_delta: Optional[float] = 0.0 if pending_initial else None
                    pending_initial = False
                    if crossing_delta is None:
                        if active or current_time >= horizon:
                            break
                        remaining = horizon - current_time
                        endpoint = terminal_after(remaining)
                        if endpoint is None:
                            chain_valid = False
                            break
                        endpoint_true = (
                            endpoint[0] > threshold_value
                            if operator == "gt"
                            else endpoint[0] >= threshold_value
                        )
                        if not endpoint_true:
                            break
                        low, high = 0.0, remaining
                        for _ in range(80):
                            middle = 0.5 * (low + high)
                            candidate = terminal_after(middle)
                            if candidate is None:
                                chain_valid = False
                                break
                            candidate_true = (
                                candidate[0] > threshold_value
                                if operator == "gt"
                                else candidate[0] >= threshold_value
                            )
                            if candidate_true:
                                high = middle
                            else:
                                low = middle
                        if not chain_valid:
                            break
                        crossing_delta = high

                    crossing_state = terminal_after(crossing_delta)
                    if crossing_state is None:
                        chain_valid = False
                        break
                    current_time += crossing_delta
                    product, source, intermediate = crossing_state
                    if delay_value > 0:
                        pending_due = current_time + delay_value
                        if pending_due > horizon:
                            chain_valid = False
                            break
                        continue
                    pattern = context.resolve_species_pattern(variable)
                    if pattern is None or not chain_supported:
                        chain_valid = False
                        break
                    chain_schedule.append(
                        (
                            current_time,
                            [("conc", pattern, assignment_number)],
                            0.0,
                            event,
                            False,
                            [(standardize_name(variable), assignment_number)],
                        )
                    )
                    product = assignment_number
                    active = (
                        product > threshold_value
                        if operator == "gt"
                        else product >= threshold_value
                    )
                    if current_time >= horizon or active:
                        break
                else:
                    chain_valid = False

                if chain_valid:
                    scheduled.extend(chain_schedule)
                    recurrent_handled.add(id(event))
                    normal_converted += 1
                    if not chain_schedule:
                        horizon_limited += 1

    if (
        len(events) > 1
        and context.method.lower() != "ssa"
        and all(
            id(event) not in recurrent_handled
            and id(event) not in event_proven_inactive
            for event in events
        )
    ):
        quadratic_plans: List[dict[str, object]] = []
        statically_inactive_events: List[SBMLEvent] = []
        required_state_symbols: set[str] = set()
        event_target_seed_symbols: set[str] = set()
        quadratic_group_supported = True
        for event in events:
            parsed_threshold = _parse_affine_state_threshold(event.trigger)
            parsed_difference = _parse_state_difference_threshold(event.trigger)
            difference_components = (
                _state_difference_components(parsed_difference[0])
                if parsed_difference is not None
                else None
            )
            if (
                (
                    parsed_threshold is None
                    or fold(parsed_threshold[2], event_context=event) is None
                )
                and difference_components is not None
                and all(
                    context.resolve_species_pattern(symbol) is not None
                    for symbol in difference_components
                )
            ):
                parsed_threshold = parsed_difference
            expanded_delay = context.expand_functions(event.delay or "")
            delay_symbols = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expanded_delay)
            delay = fold(event.delay, event_context=event) if event.delay else 0.0
            delay_uses_time = any(symbol.lower() == "time" for symbol in delay_symbols)
            if (
                parsed_threshold is None
                or event.priority
                or (delay is None and not delay_uses_time)
                or (delay is not None and (not math.isfinite(delay) or delay < 0))
                or any(
                    symbol.lower() != "time"
                    and not context.is_compile_time_constant(symbol)
                    for symbol in delay_symbols
                )
                or not event.trigger_persistent
                or (
                    (delay is None or delay > 0)
                    and not event.use_values_from_trigger_time
                )
                or fold_initial(event.trigger) != 0
            ):
                quadratic_group_supported = False
                break
            trigger_expression, operator, threshold_expression = parsed_threshold
            identifier = (
                difference_components[0]
                if difference_components is not None
                and parsed_threshold is parsed_difference
                else trigger_expression
            )
            threshold = fold(threshold_expression, event_context=event)
            if (
                operator not in {"lt", "gt"}
                or threshold is None
                or not math.isfinite(threshold)
            ):
                quadratic_group_supported = False
                break
            trigger_state_ids = (
                difference_components
                if parsed_threshold is parsed_difference
                and difference_components is not None
                else (identifier,)
            )
            trigger_state_names = {
                standardize_name(symbol) for symbol in trigger_state_ids
            }
            trigger_is_assigned = any(
                standardize_name(variable) in trigger_state_names
                for candidate in events
                for assignment in candidate.assignments
                for variable, _expression in [_event_assignment(assignment)]
            )
            constant_trajectory = context.resolve_affine_rate_for_event(
                identifier, event
            )
            initial_trigger_state = context.resolve_initial_value(identifier)
            if (
                difference_components is None
                and not trigger_is_assigned
                and constant_trajectory is not None
                and constant_trajectory[1] == 0
                and initial_trigger_state is not None
                and math.isfinite(initial_trigger_state)
                and not (
                    initial_trigger_state < threshold
                    if operator == "lt"
                    else initial_trigger_state > threshold
                )
            ):
                statically_inactive_events.append(event)
                continue
            assignments: List[Tuple[str, str, str]] = []
            seen_targets: set[str] = set()
            for assignment in event.assignments:
                variable, expression = _event_assignment(assignment)
                pattern = context.resolve_species_pattern(variable)
                normalized_variable = standardize_name(variable)
                if (
                    pattern is None
                    or normalized_variable in seen_targets
                    or not str(expression or "").strip()
                ):
                    quadratic_group_supported = False
                    break
                seen_targets.add(normalized_variable)
                assignments.append((variable, pattern, expression))
                # Supply every event target's initial value to trajectory
                # resolvers. Another event may assign a species used by this
                # event's rate law, even when that species is not a trigger
                # coordinate. Do not require unrelated targets in snapshots:
                # the trajectory may not determine their later values.
                event_target_seed_symbols.add(variable)
                for symbol in re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]*", str(expression or "")
                ):
                    if standardize_name(symbol) == "time":
                        continue
                    if context.is_compile_time_constant(symbol):
                        continue
                    if (
                        context.resolve_species_pattern(symbol) is not None
                        or context.is_param(symbol)
                        or context.is_compartment(symbol)
                    ):
                        required_state_symbols.add(symbol)
            if not quadratic_group_supported or not assignments:
                quadratic_group_supported = False
                break
            required_state_symbols.add(identifier)
            if parsed_threshold is parsed_difference and difference_components:
                required_state_symbols.update(difference_components)
            quadratic_plans.append(
                {
                    "event": event,
                    "identifier": identifier,
                    "operator": operator,
                    "threshold": float(threshold),
                    "difference_components": (
                        difference_components
                        if parsed_threshold is parsed_difference
                        else None
                    ),
                    "assignments": assignments,
                    "delay": None if delay is None else float(delay),
                    "delay_expression": event.delay or "",
                }
            )

        initial_state: dict[str, float] = {}
        if quadratic_group_supported:
            for symbol in required_state_symbols | event_target_seed_symbols:
                value = context.resolve_initial_value(symbol)
                if value is None or not math.isfinite(value):
                    quadratic_group_supported = False
                    break
                initial_state[symbol] = float(value)

        required_state_names = {
            standardize_name(symbol) for symbol in required_state_symbols
        }
        if quadratic_group_supported:
            for plan in quadratic_plans:
                event = plan["event"]
                identifier = str(plan["identifier"])
                trajectory = context.resolve_quadratic_rate_from_state(
                    identifier, event, initial_state
                )
                if trajectory is None:
                    quadratic_group_supported = False
                    break
                initial_value = trajectory[0]
                initial_snapshot = context.resolve_quadratic_state_values_from_state(
                    identifier, initial_value, event, initial_state
                )
                if initial_snapshot is None or not required_state_names.issubset(
                    {standardize_name(symbol) for symbol in initial_snapshot}
                ):
                    quadratic_group_supported = False
                    break

        def quadratic_trigger_active(
            plan: Mapping[str, object], state_values: Mapping[str, float]
        ) -> Optional[bool]:
            identifier = str(plan["identifier"])
            components = plan.get("difference_components")
            if isinstance(components, tuple) and len(components) == 2:
                normalized_components = tuple(
                    standardize_name(str(symbol)) for symbol in components
                )
                component_values = {
                    standardize_name(symbol): float(value)
                    for symbol, value in state_values.items()
                }
                if not all(
                    symbol in component_values for symbol in normalized_components
                ):
                    return None
                state_value = (
                    component_values[normalized_components[0]]
                    - component_values[normalized_components[1]]
                )
            else:
                normalized_identifier = standardize_name(identifier)
                state_value = next(
                    (
                        float(value)
                        for symbol, value in state_values.items()
                        if standardize_name(symbol) == normalized_identifier
                    ),
                    None,
                )
            if state_value is None or not math.isfinite(state_value):
                return None
            threshold = float(plan["threshold"])
            operator = str(plan["operator"])
            if state_value != threshold:
                return (
                    state_value < threshold
                    if operator == "lt"
                    else state_value > threshold
                )
            event = plan["event"]
            if isinstance(components, tuple) and len(components) == 2:
                derivatives = []
                for symbol in components:
                    trajectory = context.resolve_quadratic_rate_from_state(
                        str(symbol), event, state_values
                    )
                    if trajectory is None:
                        return None
                    initial, quadratic, linear, constant = trajectory
                    derivatives.append(
                        quadratic * initial * initial + linear * initial + constant
                    )
                derivative = derivatives[0] - derivatives[1]
            else:
                trajectory = context.resolve_quadratic_rate_from_state(
                    identifier, event, state_values
                )
                if trajectory is None:
                    return None
                initial, quadratic, linear, constant = trajectory
                derivative = quadratic * initial * initial + linear * initial + constant
            return derivative < 0 if operator == "lt" else derivative > 0

        def quadratic_plan_crossing(
            plan: Mapping[str, object], state_values: Mapping[str, float]
        ) -> Optional[
            Tuple[Optional[float], float, float, Tuple[float, float, float, float]]
        ]:
            identifier = str(plan["identifier"])
            event = plan["event"]
            trajectory = context.resolve_quadratic_rate_from_state(
                identifier, event, state_values
            )
            if trajectory is None:
                return None
            initial, quadratic, linear, constant = trajectory
            threshold = float(plan["threshold"])
            components = plan.get("difference_components")
            if not isinstance(components, tuple) or len(components) != 2:
                derivative = (
                    quadratic * threshold * threshold + linear * threshold + constant
                )
                return (
                    _quadratic_crossing_time(
                        initial, threshold, quadratic, linear, constant
                    ),
                    threshold,
                    derivative,
                    trajectory,
                )

            normalized_values = {
                standardize_name(symbol): float(value)
                for symbol, value in state_values.items()
            }
            left_name, right_name = (str(symbol) for symbol in components)
            left_key, right_key = (
                standardize_name(left_name),
                standardize_name(right_name),
            )
            if left_key not in normalized_values or right_key not in normalized_values:
                return None
            current_difference = (
                normalized_values[left_key] - normalized_values[right_key]
            )
            step = max(1.0, abs(initial))
            projected_differences: List[float] = []
            for coordinate in (initial + step, initial + 2.0 * step):
                snapshot = context.resolve_quadratic_state_values_from_state(
                    identifier, coordinate, event, state_values
                )
                if snapshot is None:
                    return None
                values = {
                    standardize_name(symbol): float(value)
                    for symbol, value in snapshot.items()
                }
                if left_key not in values or right_key not in values:
                    return None
                projected_differences.append(values[left_key] - values[right_key])
            slope = (projected_differences[0] - current_difference) / step
            predicted_second = current_difference + 2.0 * slope * step
            if not math.isfinite(slope) or abs(
                projected_differences[1] - predicted_second
            ) > 1e-12 * max(
                1.0,
                abs(current_difference),
                abs(projected_differences[0]),
                abs(projected_differences[1]),
            ):
                return None
            if abs(slope) <= 1e-14:
                return None, initial, 0.0, trajectory
            crossing_coordinate = initial - current_difference / slope
            if not math.isfinite(crossing_coordinate):
                return None
            derivative = slope * (
                quadratic * crossing_coordinate * crossing_coordinate
                + linear * crossing_coordinate
                + constant
            )
            return (
                _quadratic_crossing_time(
                    initial,
                    crossing_coordinate,
                    quadratic,
                    linear,
                    constant,
                ),
                crossing_coordinate,
                derivative,
                trajectory,
            )

        group_schedule: List[
            Tuple[
                float,
                List[Tuple[str, str, float]],
                float,
                Optional[SBMLEvent],
                bool,
                List[Tuple[str, float]],
            ]
        ] = []
        pending_quadratic_actions: List[dict[str, object]] = []
        group_state = dict(initial_state)
        group_time = 0.0
        initial_trigger_state_pending = True
        if quadratic_group_supported:
            for _ in range(10_000):
                active_by_event: dict[int, bool] = {}
                for plan in quadratic_plans:
                    active = (
                        bool(fold_initial(plan["event"].trigger))
                        if initial_trigger_state_pending
                        else quadratic_trigger_active(plan, group_state)
                    )
                    if active is None:
                        quadratic_group_supported = False
                        break
                    active_by_event[id(plan["event"])] = active
                if not quadratic_group_supported:
                    break

                transitions: List[Tuple[float, Mapping[str, object], str, float]] = []
                remaining = max(0.0, float(context.base_t_end) - group_time)
                for plan in quadratic_plans:
                    event = plan["event"]
                    identifier = str(plan["identifier"])
                    crossing = quadratic_plan_crossing(plan, group_state)
                    if crossing is None:
                        quadratic_group_supported = False
                        break
                    crossing_delta, coordinate_threshold, derivative, trajectory = (
                        crossing
                    )
                    initial, quadratic, linear, constant = trajectory
                    current_active = active_by_event[id(event)]
                    if crossing_delta is None:
                        endpoint = _quadratic_state_at_time(
                            initial, quadratic, linear, constant, remaining
                        )
                        if endpoint is None:
                            quadratic_group_supported = False
                            break
                        components = plan.get("difference_components")
                        if isinstance(components, tuple) and len(components) == 2:
                            endpoint_state = (
                                context.resolve_quadratic_state_values_from_state(
                                    identifier, endpoint, event, group_state
                                )
                            )
                            endpoint_active = (
                                None
                                if endpoint_state is None
                                else quadratic_trigger_active(plan, endpoint_state)
                            )
                        else:
                            endpoint_active = (
                                endpoint < float(plan["threshold"])
                                if plan["operator"] == "lt"
                                else endpoint > float(plan["threshold"])
                            )
                        if endpoint_active is None:
                            quadratic_group_supported = False
                            break
                        if endpoint_active != current_active:
                            quadratic_group_supported = False
                            break
                        continue

                    if crossing_delta <= 1e-12:
                        if initial_trigger_state_pending and not current_active:
                            enters_true = (
                                derivative < 0
                                if plan["operator"] == "lt"
                                else derivative > 0
                            )
                            if enters_true:
                                transitions.append(
                                    (
                                        group_time,
                                        plan,
                                        "entry",
                                        coordinate_threshold,
                                    )
                                )
                        continue
                    event_time = group_time + crossing_delta
                    endpoint = _quadratic_state_at_time(
                        initial, quadratic, linear, constant, remaining
                    )
                    if endpoint is None:
                        quadratic_group_supported = False
                        break
                    components = plan.get("difference_components")
                    if isinstance(components, tuple) and len(components) == 2:
                        endpoint_state = (
                            context.resolve_quadratic_state_values_from_state(
                                identifier, endpoint, event, group_state
                            )
                        )
                        endpoint_active = (
                            None
                            if endpoint_state is None
                            else quadratic_trigger_active(plan, endpoint_state)
                        )
                    else:
                        endpoint_active = (
                            endpoint < float(plan["threshold"])
                            if plan["operator"] == "lt"
                            else endpoint > float(plan["threshold"])
                        )
                    if endpoint_active is None:
                        quadratic_group_supported = False
                        break
                    if event_time > float(context.base_t_end) + 1e-12:
                        if endpoint_active != current_active:
                            quadratic_group_supported = False
                            break
                        continue

                    enters_true = (
                        derivative < 0 if plan["operator"] == "lt" else derivative > 0
                    )
                    is_entry = not current_active and enters_true
                    is_exit = current_active and not enters_true
                    if not is_entry and not is_exit:
                        if endpoint_active != current_active:
                            quadratic_group_supported = False
                            break
                        continue
                    transitions.append(
                        (
                            event_time,
                            plan,
                            "entry" if is_entry else "exit",
                            coordinate_threshold,
                        )
                    )

                if not quadratic_group_supported:
                    break
                if not transitions and not pending_quadratic_actions:
                    break
                transitions.sort(key=lambda item: item[0])
                if (
                    len(transitions) > 1
                    and abs(transitions[1][0] - transitions[0][0]) < 1e-12
                ):
                    quadratic_group_supported = False
                    break

                event_time, plan, transition_kind, coordinate_threshold = (
                    transitions[0] if transitions else (math.inf, {}, "", 0.0)
                )
                next_pending_time = min(
                    (float(action["time"]) for action in pending_quadratic_actions),
                    default=math.inf,
                )
                if next_pending_time <= event_time + 1e-12:
                    if abs(next_pending_time - event_time) < 1e-12:
                        quadratic_group_supported = False
                        break
                    pending = [
                        action
                        for action in pending_quadratic_actions
                        if abs(float(action["time"]) - next_pending_time) < 1e-12
                    ]
                    if len(pending) != 1:
                        quadratic_group_supported = False
                        break
                    action = pending[0]
                    pending_plan = action["plan"]
                    if not isinstance(pending_plan, Mapping):
                        quadratic_group_supported = False
                        break
                    pending_event = pending_plan["event"]
                    pending_identifier = str(pending_plan["identifier"])
                    pending_trajectory = context.resolve_quadratic_rate_from_state(
                        pending_identifier, pending_event, group_state
                    )
                    if pending_trajectory is None:
                        quadratic_group_supported = False
                        break
                    pending_value = _quadratic_state_at_time(
                        *pending_trajectory, next_pending_time - group_time
                    )
                    if pending_value is None:
                        quadratic_group_supported = False
                        break
                    pending_state = context.resolve_quadratic_state_values_from_state(
                        pending_identifier,
                        pending_value,
                        pending_event,
                        group_state,
                    )
                    if pending_state is None or not required_state_names.issubset(
                        {standardize_name(symbol) for symbol in pending_state}
                    ):
                        quadratic_group_supported = False
                        break
                    active_before: dict[int, bool] = {}
                    for other_plan in quadratic_plans:
                        active = quadratic_trigger_active(other_plan, pending_state)
                        if active is None:
                            quadratic_group_supported = False
                            break
                        active_before[id(other_plan["event"])] = active
                    if not quadratic_group_supported:
                        break
                    next_state = {
                        **group_state,
                        **{
                            str(symbol): float(value)
                            for symbol, value in pending_state.items()
                        },
                    }
                    pending_values = list(action["values"])
                    assignment_variables = {
                        standardize_name(variable): variable
                        for variable, _pattern, _expression in pending_plan[
                            "assignments"
                        ]
                    }
                    for normalized_target, numeric_value in pending_values:
                        variable = assignment_variables.get(normalized_target)
                        if variable is None:
                            quadratic_group_supported = False
                            break
                        next_state[variable] = float(numeric_value)
                    if not quadratic_group_supported:
                        break
                    for other_plan in quadratic_plans:
                        post_active = quadratic_trigger_active(other_plan, next_state)
                        if post_active is None or (
                            other_plan["event"] is not pending_event
                            and not active_before[id(other_plan["event"])]
                            and post_active
                        ):
                            quadratic_group_supported = False
                            break
                    if not quadratic_group_supported:
                        break
                    group_schedule.append(
                        (
                            next_pending_time,
                            list(action["sets"]),
                            0.0,
                            pending_event,
                            False,
                            pending_values,
                        )
                    )
                    pending_quadratic_actions.remove(action)
                    group_state = next_state
                    group_time = next_pending_time
                    initial_trigger_state_pending = False
                    continue

                if not transitions:
                    break
                initial_trigger_state_pending = False
                event = plan["event"]
                identifier = str(plan["identifier"])
                threshold = float(coordinate_threshold)
                crossing_state = context.resolve_quadratic_state_values_from_state(
                    identifier, threshold, event, group_state
                )
                if crossing_state is None or not required_state_names.issubset(
                    {standardize_name(symbol) for symbol in crossing_state}
                ):
                    quadratic_group_supported = False
                    break
                group_state = {
                    **group_state,
                    **{
                        str(symbol): float(value)
                        for symbol, value in crossing_state.items()
                    },
                }
                if transition_kind == "exit":
                    group_time = event_time
                    continue

                scheduled_sets: List[Tuple[str, str, float]] = []
                event_values: List[Tuple[str, float]] = []
                next_state = dict(group_state)
                event_value_state = {**group_state, "time": event_time}
                for variable, pattern, expression in plan["assignments"]:
                    value = fold_at_state(
                        expression,
                        event_time,
                        state_values=event_value_state,
                        event_context=event,
                    )
                    if value is None or not math.isfinite(value):
                        quadratic_group_supported = False
                        break
                    numeric_value = float(value)
                    scheduled_sets.append(("conc", pattern, numeric_value))
                    event_values.append((standardize_name(variable), numeric_value))
                    next_state[variable] = numeric_value
                if not quadratic_group_supported:
                    break

                planned_delay = plan["delay"]
                delay_value = (
                    fold(
                        str(plan["delay_expression"]),
                        time_value=event_time,
                        event_context=event,
                    )
                    if planned_delay is None
                    else float(planned_delay)
                )
                if (
                    delay_value is None
                    or not math.isfinite(delay_value)
                    or delay_value < 0
                ):
                    quadratic_group_supported = False
                    break
                delay = float(delay_value)
                if delay == 0:
                    for other_plan in quadratic_plans:
                        post_active = quadratic_trigger_active(other_plan, next_state)
                        if post_active is None:
                            quadratic_group_supported = False
                            break
                        if (
                            other_plan["event"] is not event
                            and not active_by_event[id(other_plan["event"])]
                            and post_active
                        ):
                            # An immediate assignment caused another trigger
                            # to become true at this same time; ordering
                            # without priorities is ambiguous.
                            quadratic_group_supported = False
                            break
                if not quadratic_group_supported:
                    break

                execution_time = event_time + delay
                if delay > 0 and execution_time <= float(context.base_t_end) + 1e-12:
                    pending_quadratic_actions.append(
                        {
                            "time": execution_time,
                            "plan": plan,
                            "sets": scheduled_sets,
                            "values": event_values,
                        }
                    )
                if delay == 0:
                    group_schedule.append(
                        (event_time, scheduled_sets, 0.0, event, False, event_values)
                    )
                    group_state = next_state
                group_time = event_time
            else:
                quadratic_group_supported = False

        if quadratic_group_supported:
            inactive_event_ids = {id(event) for event in statically_inactive_events}
            recurrent_handled.update(
                id(event) for event in events if id(event) not in inactive_event_ids
            )
            event_proven_inactive.update(inactive_event_ids)
            if group_schedule:
                scheduled.extend(group_schedule)
                normal_converted += len(quadratic_plans)
                horizon_limited += len(statically_inactive_events)
            else:
                event_proven_inactive.update(id(event) for event in events)
                horizon_limited += len(events)

    if len(events) == 1 and id(events[0]) not in recurrent_handled:
        event = events[0]
        parsed_difference = _parse_state_difference_threshold(event.trigger)
        difference_components = (
            _state_difference_components(parsed_difference[0])
            if parsed_difference is not None
            else None
        )
        if difference_components is not None and all(
            context.resolve_species_pattern(symbol) is not None
            for symbol in difference_components
        ):
            parsed_threshold = parsed_difference
        else:
            parsed_threshold = _parse_affine_state_threshold(event.trigger)
        delay_symbols = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", event.delay or "")
        delay_value = fold(event.delay, event_context=event) if event.delay else 0.0
        quadratic_delay_is_supported = (
            delay_value is not None
            and math.isfinite(delay_value)
            and delay_value >= 0
            and all(
                context.is_compile_time_constant(symbol) for symbol in delay_symbols
            )
            and (
                delay_value == 0
                or (event.trigger_persistent and event.use_values_from_trigger_time)
            )
        )
        if (
            parsed_threshold is not None
            and quadratic_delay_is_supported
            and not event.priority
            and float(context.base_t_end) > 0
            and math.isfinite(float(context.base_t_end))
        ):
            identifier, operator, threshold_expression = parsed_threshold
            threshold = fold(threshold_expression, event_context=event)
            initial_truth = fold_initial(event.trigger)
            assignment_targets: List[Tuple[str, str, str]] = []
            assignments_are_species = True
            seen_targets: set[str] = set()
            for assignment in event.assignments:
                variable, expression = _event_assignment(assignment)
                pattern = context.resolve_species_pattern(variable)
                normalized_variable = standardize_name(variable)
                if (
                    pattern is None
                    or normalized_variable in seen_targets
                    or not str(expression or "").strip()
                ):
                    assignments_are_species = False
                    break
                seen_targets.add(normalized_variable)
                assignment_targets.append((variable, pattern, expression))

            if (
                threshold is not None
                and math.isfinite(threshold)
                and initial_truth == 0
                and assignments_are_species
                and assignments
            ):

                def comparison_true(value: float) -> bool:
                    if operator == "gt":
                        return value > threshold
                    if operator == "geq":
                        return value >= threshold
                    if operator == "lt":
                        return value < threshold
                    return value <= threshold

                state_values: Mapping[str, float] = {}
                time_value = 0.0
                recurrence: List[
                    Tuple[
                        float,
                        List[Tuple[str, str, float]],
                        float,
                        Optional[SBMLEvent],
                        bool,
                        List[Tuple[str, float]],
                    ]
                ] = []
                recurrence_is_proven = True
                no_firing_within_horizon = False
                pending_action: Optional[
                    Tuple[
                        float,
                        List[Tuple[str, str, float]],
                        List[Tuple[str, float]],
                    ]
                ] = None
                for _ in range(10_000):
                    if pending_action is not None:
                        due_time, scheduled_sets, event_values = pending_action
                        if due_time > float(context.base_t_end) + 1e-12:
                            no_firing_within_horizon = not recurrence
                            break
                        trajectory = context.resolve_quadratic_rate_from_state(
                            identifier, event, state_values
                        )
                        if trajectory is None:
                            recurrence_is_proven = False
                            break
                        initial, quadratic, linear, constant = trajectory
                        due_delta = due_time - time_value
                        if due_delta < -1e-12:
                            recurrence_is_proven = False
                            break
                        due_coordinate = _quadratic_state_at_time(
                            initial,
                            quadratic,
                            linear,
                            constant,
                            max(0.0, due_delta),
                        )
                        if due_coordinate is None or not comparison_true(
                            due_coordinate
                        ):
                            recurrence_is_proven = False
                            break
                        due_state = context.resolve_quadratic_state_values_from_state(
                            identifier, due_coordinate, event, state_values
                        )
                        if due_state is None:
                            recurrence_is_proven = False
                            break
                        next_state = dict(due_state)
                        for normalized_variable, value in event_values:
                            target = next(
                                (
                                    variable
                                    for variable, _pattern, _expression in assignment_targets
                                    if standardize_name(variable) == normalized_variable
                                ),
                                None,
                            )
                            if target is None:
                                recurrence_is_proven = False
                                break
                            next_state[target] = value
                        if not recurrence_is_proven:
                            break
                        post_trigger = fold_at_state(
                            event.trigger,
                            due_time,
                            state_values=next_state,
                            event_context=event,
                        )
                        if post_trigger is None or not math.isfinite(post_trigger):
                            recurrence_is_proven = False
                            break
                        recurrence.append(
                            (
                                due_time,
                                scheduled_sets,
                                0.0,
                                event,
                                False,
                                event_values,
                            )
                        )
                        pending_action = None
                        if post_trigger != 0:
                            break
                        state_values = next_state
                        time_value = due_time
                        continue

                    trajectory = context.resolve_quadratic_rate_from_state(
                        identifier, event, state_values
                    )
                    if trajectory is None:
                        recurrence_is_proven = False
                        break
                    initial, quadratic, linear, constant = trajectory
                    crossing_delta = _quadratic_crossing_time(
                        initial, threshold, quadratic, linear, constant
                    )
                    if crossing_delta is None:
                        endpoint = _quadratic_state_at_time(
                            initial,
                            quadratic,
                            linear,
                            constant,
                            float(context.base_t_end) - time_value,
                        )
                        if endpoint is not None and not comparison_true(endpoint):
                            if recurrence:
                                break
                            # Autonomous scalar quadratic trajectories are
                            # monotone between equilibria; a false endpoint
                            # plus no threshold root proves no firing here.
                            no_firing_within_horizon = True
                            break
                        recurrence_is_proven = False
                        break
                    derivative = (
                        quadratic * threshold * threshold
                        + linear * threshold
                        + constant
                    )
                    rising = (operator in {"gt", "geq"} and derivative > 0) or (
                        operator in {"lt", "leq"} and derivative < 0
                    )
                    crossing_time = time_value + crossing_delta
                    if (
                        not rising
                        or crossing_delta <= 1e-12
                        or not math.isfinite(crossing_time)
                    ):
                        endpoint = _quadratic_state_at_time(
                            initial,
                            quadratic,
                            linear,
                            constant,
                            float(context.base_t_end) - time_value,
                        )
                        if endpoint is not None and not comparison_true(endpoint):
                            if not recurrence:
                                no_firing_within_horizon = True
                            break
                        recurrence_is_proven = False
                        break
                    if crossing_time > float(context.base_t_end) + 1e-12:
                        no_firing_within_horizon = not recurrence
                        break
                    crossing_state = context.resolve_quadratic_state_values_from_state(
                        identifier, threshold, event, state_values
                    )
                    if crossing_state is None:
                        recurrence_is_proven = False
                        break
                    next_state = dict(crossing_state)
                    scheduled_sets: List[Tuple[str, str, float]] = []
                    event_values: List[Tuple[str, float]] = []
                    for variable, pattern, expression in assignment_targets:
                        value = fold_at_state(
                            expression,
                            crossing_time,
                            state_values=crossing_state,
                            event_context=event,
                        )
                        if value is None or not math.isfinite(value):
                            recurrence_is_proven = False
                            break
                        scheduled_sets.append(("conc", pattern, float(value)))
                        event_values.append((standardize_name(variable), float(value)))
                        next_state[variable] = value
                    if not recurrence_is_proven:
                        break
                    if delay_value > 0:
                        execution_time = crossing_time + float(delay_value)
                        if execution_time > float(context.base_t_end) + 1e-12:
                            no_firing_within_horizon = not recurrence
                            break
                        pending_action = (
                            min(execution_time, float(context.base_t_end)),
                            scheduled_sets,
                            event_values,
                        )
                        state_values = crossing_state
                        time_value = crossing_time
                        continue
                    post_trigger = fold_at_state(
                        event.trigger,
                        crossing_time,
                        state_values=next_state,
                        event_context=event,
                    )
                    if post_trigger is None:
                        recurrence_is_proven = False
                        break
                    recurrence.append(
                        (
                            crossing_time,
                            scheduled_sets,
                            0.0,
                            event,
                            False,
                            event_values,
                        )
                    )
                    if post_trigger != 0:
                        # A scalar autonomous quadratic trajectory is monotone
                        # between equilibria. If the reset leaves the trigger
                        # true, it can exit the trigger region only once and
                        # cannot create another false-to-true edge.
                        break
                    state_values = next_state
                    time_value = crossing_time
                else:
                    recurrence_is_proven = False
                if recurrence and recurrence_is_proven:
                    scheduled.extend(recurrence)
                    recurrent_handled.add(id(event))
                    normal_converted += 1
                elif no_firing_within_horizon and recurrence_is_proven:
                    event_proven_inactive.add(id(event))
                    horizon_limited += 1

    def conjunction_stays_false_through_horizon(event: SBMLEvent) -> bool:
        """Prove one monotone conjunct stays false for this run's horizon."""
        terms = _split_call_arguments(event.trigger)
        if terms is None:
            return False
        horizon = float(context.base_t_end)
        if not math.isfinite(horizon) or horizon < 0:
            return False
        for term in terms:
            parsed = _parse_affine_state_threshold(term)
            if parsed is None:
                continue
            identifier, operator, threshold_expression = parsed
            threshold = fold(threshold_expression, event_context=event)
            initial = context.resolve_initial_value(identifier)
            if (
                threshold is None
                or initial is None
                or not math.isfinite(threshold)
                or not math.isfinite(initial)
            ):
                continue
            trajectory = context.resolve_affine_rate_for_event(identifier, event)
            exponential = None
            if trajectory is None:
                exponential = context.resolve_exponential_rate_for_event(
                    identifier, event
                )
            if trajectory is not None:
                value_at_end = trajectory[0] + trajectory[1] * horizon
            elif exponential is not None:
                try:
                    value_at_end = exponential[0] * math.exp(exponential[1] * horizon)
                except OverflowError:
                    continue
            else:
                continue
            if not math.isfinite(value_at_end):
                continue

            def satisfies(value: float) -> bool:
                if operator == "gt":
                    return value > threshold
                if operator == "geq":
                    return value >= threshold
                if operator == "lt":
                    return value < threshold
                return value <= threshold

            # Each accepted trajectory is monotone, so a one-sided comparison
            # that is false at both endpoints is false throughout the run.
            if not satisfies(initial) and not satisfies(value_at_end):
                return True
        return False

    for _source_index, event in ordered_events:
        if (
            id(event) in periodic_handled
            or id(event) in event_proven_inactive
            or id(event) in recurrent_handled
        ):
            continue
        if id(event) in static_event_no_action:
            normal_converted += 1
            continue
        if id(event) in affine_interval_no_action:
            normal_converted += 1
            continue
        if conjunction_stays_false_through_horizon(event):
            normal_converted += 1
            horizon_limited += 1
            continue
        event_trigger = event.trigger
        gated_time_bounds: Optional[Tuple[float, float]] = None
        gated_state = _parse_gated_affine_state_threshold(
            event.trigger, lambda expression: fold(expression, event_context=event)
        )
        if gated_state is not None:
            state_expression, lower_expressions, upper_expressions, gate_is_true = (
                gated_state
            )
            if not gate_is_true:
                normal_converted += 1
                continue
            lower_values = [
                fold(value, event_context=event) for value in lower_expressions
            ]
            upper_values = [
                fold(value, event_context=event) for value in upper_expressions
            ]
            initial_state_truth = fold_initial(state_expression)
            if static_initial_gates_are_safe and initial_state_truth == 0:
                normal_converted += 1
                continue
            if (
                all(
                    value is not None and math.isfinite(value) for value in lower_values
                )
                and all(
                    value is not None and math.isfinite(value) for value in upper_values
                )
                and initial_state_truth == 0
            ):
                lower_bound = max(float(value) for value in lower_values)
                upper_bound = (
                    min(float(value) for value in upper_values)
                    if upper_values
                    else math.inf
                )
                if lower_bound <= upper_bound:
                    event_trigger = state_expression
                    gated_time_bounds = (lower_bound, upper_bound)
        trigger_state_values: Optional[dict[str, float]] = None
        trigger_state_trajectory: Optional[Tuple[str, str, float, float]] = None
        trigger_threshold_value: Optional[float] = None
        event_changes_trigger_state = False
        affine_interval = affine_interval_schedules.get(id(event))
        static_initial_values = static_event_initial_fires.get(id(event))
        if static_initial_values is not None:
            threshold = "0"
            window_end: Optional[float] = None
            trigger_state_values = dict(static_initial_values)
        elif affine_interval is not None:
            (
                interval_identifier,
                interval_kind,
                interval_initial,
                interval_slope,
                interval_entry,
                _interval_lower,
                _interval_upper,
                interval_exit,
                _interval_lower_operator,
                _interval_upper_operator,
                interval_entry_state,
            ) = affine_interval
            threshold = _format_number(interval_entry)
            window_end: Optional[float] = interval_exit
            trigger_state_values = {interval_identifier: interval_entry_state}
            trigger_state_trajectory = (
                interval_identifier,
                interval_kind,
                interval_initial,
                interval_slope,
            )
        else:
            threshold = parse_time_threshold(event_trigger)
            window_end = None
        scale_identifier: Optional[str] = None
        if threshold is None:
            state_threshold = _parse_affine_state_threshold(event_trigger)
            rate_of_threshold = False
            state_threshold_scale = "1"
            difference_threshold = _parse_state_difference_threshold(event_trigger)
            if difference_threshold is not None and (
                context.resolve_quadratic_rate_for_event(difference_threshold[0], event)
                is not None
                or all(
                    context.resolve_affine_rate_for_event(identifier, event) is not None
                    for identifier in _state_difference_components(
                        difference_threshold[0]
                    )
                    or ()
                )
            ):
                state_threshold = difference_threshold
            if state_threshold is None:
                state_threshold = _parse_rate_of_state_threshold(event_trigger)
                rate_of_threshold = state_threshold is not None
            if state_threshold is None:
                scaled_threshold = _parse_scaled_state_threshold(
                    event_trigger,
                    resolve_scale=lambda expression: fold(
                        expression, event_context=event
                    ),
                )
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
                            # A negative scale flips the comparison's
                            # direction; the resolver already returns a
                            # canonical operator, so this cannot ``KeyError``.
                            scaled_operator = _REVERSED_COMPARISON_OPERATOR[
                                scaled_operator
                            ]
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
                difference_components = _state_difference_components(identifier)
                trigger_state_ids = difference_components or (identifier,)
                event_changes_trigger_state = any(
                    standardize_name(variable)
                    in {standardize_name(state_id) for state_id in trigger_state_ids}
                    and standardize_name(_strip_outer_parens(assignment_expression))
                    != standardize_name(variable)
                    for assignment in event.assignments
                    for variable, assignment_expression in [
                        _event_assignment(assignment)
                    ]
                )
                difference_trajectories = (
                    [
                        context.resolve_affine_rate_for_event(state_id, event)
                        for state_id in difference_components
                    ]
                    if difference_components is not None
                    and not event_changes_trigger_state
                    and (
                        event.use_values_from_trigger_time
                        or not event.delay
                        or fold(event.delay, event_context=event) == 0
                    )
                    else None
                )
                trajectory = None
                if not rate_of_threshold:
                    if difference_trajectories and all(difference_trajectories):
                        left, right = difference_trajectories
                        assert left is not None and right is not None
                        trajectory = (left[0] - right[0], left[1] - right[1])
                    elif difference_components is None:
                        trajectory = context.resolve_affine_rate_for_event(
                            identifier, event
                        )
                if (
                    trajectory is None
                    and not rate_of_threshold
                    and not event_changes_trigger_state
                    and difference_components is None
                    and context.resolve_affine_rate_for_event is _no_event_affine_rate
                ):
                    trajectory = context.resolve_affine_rate(identifier)
                crossing_value = fold(threshold_expression)
                if crossing_value is not None:
                    scale_value = float(state_threshold_scale)
                    crossing_value /= scale_value
                    trigger_threshold_value = crossing_value
                if (
                    difference_components is not None
                    and not rate_of_threshold
                    and crossing_value is not None
                    and state_threshold_scale == "1"
                ):
                    stationary_difference = context.resolve_quadratic_rate_for_event(
                        identifier, event
                    )
                    if stationary_difference is not None and stationary_difference[
                        1:
                    ] == (0.0, 0.0, 0.0):
                        initial_difference = stationary_difference[0]
                        initially_true = (
                            initial_difference > crossing_value
                            if operator == "gt"
                            else (
                                initial_difference >= crossing_value
                                if operator == "geq"
                                else (
                                    initial_difference < crossing_value
                                    if operator == "lt"
                                    else initial_difference <= crossing_value
                                )
                            )
                        )
                        if not initially_true:
                            normal_converted += 1
                            continue
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
                        else (
                            initial_value >= crossing_value
                            if operator == "geq"
                            else (
                                initial_value < crossing_value
                                if operator == "lt"
                                else initial_value <= crossing_value
                            )
                        )
                    )
                    if slope == 0:
                        if initially_true and not event.trigger_initial_value:
                            threshold = "0"
                            trigger_state_values = (
                                {
                                    difference_components[0]: difference_trajectories[
                                        0
                                    ][0],
                                    difference_components[1]: difference_trajectories[
                                        1
                                    ][0],
                                }
                                if difference_components is not None
                                and difference_trajectories is not None
                                else {identifier: initial_value}
                            )
                        else:
                            normal_converted += 1
                            continue
                    elif initially_true:
                        if not event.trigger_initial_value:
                            threshold = "0"
                            trigger_state_values = (
                                {
                                    difference_components[0]: difference_trajectories[
                                        0
                                    ][0],
                                    difference_components[1]: difference_trajectories[
                                        1
                                    ][0],
                                }
                                if difference_components is not None
                                and difference_trajectories is not None
                                else {identifier: initial_value}
                            )
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
                            trigger_state_values = (
                                {
                                    difference_components[0]: difference_trajectories[
                                        0
                                    ][0]
                                    + difference_trajectories[0][1] * crossing_time,
                                    difference_components[1]: difference_trajectories[
                                        1
                                    ][0]
                                    + difference_trajectories[1][1] * crossing_time,
                                }
                                if difference_components is not None
                                and difference_trajectories is not None
                                else {identifier: crossing_value}
                            )
                elif crossing_value is not None:
                    exponential = context.resolve_exponential_rate_for_event(
                        identifier, event
                    )
                    if (
                        exponential is None
                        and context.resolve_exponential_rate_for_event
                        is _no_event_exponential_rate
                    ):
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
                            else (
                                initial_trigger_value >= crossing_value
                                if operator == "geq"
                                else (
                                    initial_trigger_value < crossing_value
                                    if operator == "lt"
                                    else initial_trigger_value <= crossing_value
                                )
                            )
                        )
                        if (
                            exponent == 0
                            or initial_trigger_value == 0
                            or (
                                rate_of_threshold
                                and not math.isfinite(crossing_state_value)
                            )
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
                            ) or (operator in {"lt", "leq"} and derivative_sign < 0)
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
                    elif not event_changes_trigger_state and not rate_of_threshold:
                        square_linear = context.resolve_square_linear_rate_for_event(
                            identifier, event
                        )
                        if square_linear is not None:
                            initial_value, squared_slope = square_linear
                            if initial_value <= 0 or crossing_value <= 0:
                                continue
                            initially_true = (
                                initial_value > crossing_value
                                if operator == "gt"
                                else (
                                    initial_value >= crossing_value
                                    if operator == "geq"
                                    else (
                                        initial_value < crossing_value
                                        if operator == "lt"
                                        else initial_value <= crossing_value
                                    )
                                )
                            )
                            if initially_true:
                                if not event.trigger_initial_value:
                                    threshold = "0"
                                    trigger_state_values = {identifier: initial_value}
                                else:
                                    normal_converted += 1
                                    continue
                            else:
                                rising = (
                                    operator in {"gt", "geq"} and squared_slope > 0
                                ) or (operator in {"lt", "leq"} and squared_slope < 0)
                                crossing_time = (
                                    (
                                        crossing_value * crossing_value
                                        - initial_value * initial_value
                                    )
                                    / squared_slope
                                    if squared_slope != 0
                                    else math.inf
                                )
                                if (
                                    rising
                                    and math.isfinite(crossing_time)
                                    and crossing_time >= 0
                                ):
                                    volume_change = (
                                        context.resolve_species_volume_change_for_event(
                                            identifier, event
                                        )
                                    )
                                    if volume_change is not None:
                                        old_volume, new_volume = volume_change
                                        post_event_value = (
                                            crossing_value * old_volume / new_volume
                                        )
                                        post_event_true = (
                                            post_event_value > crossing_value
                                            if operator == "gt"
                                            else (
                                                post_event_value >= crossing_value
                                                if operator == "geq"
                                                else (
                                                    post_event_value < crossing_value
                                                    if operator == "lt"
                                                    else post_event_value
                                                    <= crossing_value
                                                )
                                            )
                                        )
                                        if not post_event_true and squared_slope != 0:
                                            reentry_delay = (
                                                crossing_value * crossing_value
                                                - post_event_value * post_event_value
                                            ) / squared_slope
                                            reentry_time = crossing_time + reentry_delay
                                            if (
                                                math.isfinite(reentry_time)
                                                and reentry_delay >= 0
                                                and reentry_time
                                                <= context.base_t_end + 1e-12
                                            ):
                                                untranslated.append(
                                                    (
                                                        event,
                                                        "volume change can cause the state trigger to re-enter within the simulation horizon",
                                                    )
                                                )
                                                continue
                                    threshold = _format_number(crossing_time)
                                    trigger_state_trajectory = (
                                        identifier,
                                        "square_linear",
                                        initial_value,
                                        squared_slope,
                                    )
                                    trigger_state_values = {identifier: crossing_value}
                    if (
                        threshold is None
                        and not event_changes_trigger_state
                        and not rate_of_threshold
                        and (not event.delay or event.trigger_persistent)
                    ):
                        quadratic_trajectory = context.resolve_quadratic_rate_for_event(
                            identifier, event
                        )
                        if quadratic_trajectory is not None:
                            (
                                initial_value,
                                quadratic,
                                linear,
                                constant,
                            ) = quadratic_trajectory
                            initially_true = (
                                initial_value > crossing_value
                                if operator == "gt"
                                else (
                                    initial_value >= crossing_value
                                    if operator == "geq"
                                    else (
                                        initial_value < crossing_value
                                        if operator == "lt"
                                        else initial_value <= crossing_value
                                    )
                                )
                            )
                            if initially_true:
                                if not event.trigger_initial_value:
                                    threshold = "0"
                                    trigger_state_values = {identifier: initial_value}
                                else:
                                    normal_converted += 1
                                    continue
                            else:
                                crossing_time = _quadratic_crossing_time(
                                    initial_value,
                                    crossing_value,
                                    quadratic,
                                    linear,
                                    constant,
                                )
                                derivative = (
                                    quadratic * crossing_value * crossing_value
                                    + linear * crossing_value
                                    + constant
                                )
                                if (
                                    crossing_time is None
                                    and quadratic == 0
                                    and linear == 0
                                    and constant == 0
                                ):
                                    # An exactly stationary proven trajectory
                                    # that starts outside the trigger cannot
                                    # produce a rising edge at any later time.
                                    normal_converted += 1
                                    continue
                                rising = (
                                    operator in {"gt", "geq"} and derivative > 0
                                ) or (operator in {"lt", "leq"} and derivative < 0)
                                if rising and crossing_time is not None:
                                    threshold = _format_number(crossing_time)
                                    trigger_state_values = {identifier: crossing_value}
                                    if event.use_values_from_trigger_time:
                                        trigger_snapshot = context.resolve_quadratic_state_values_for_event(
                                            identifier, crossing_value, event
                                        )
                                        if trigger_snapshot is not None:
                                            trigger_state_values.update(
                                                trigger_snapshot
                                            )
        if threshold is None:
            window = _parse_gated_time_window(
                event_trigger,
                lambda expression: fold_static_event_gate(expression, event),
            )
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
            scaled_threshold = _parse_scaled_time_threshold(event_trigger)
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
            constant_trigger = fold(event_trigger, event_context=event)
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
                initial_trigger = fold_initial(event_trigger)
                zero_delay = (
                    not event.delay or fold(event.delay, 0, event_context=event) == 0
                )
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
        trigger_time = fold(threshold, event_context=event)
        if trigger_time is None:
            untranslated.append(
                (
                    event,
                    f'trigger time "{threshold}" does not reduce to a constant',
                )
            )
            continue
        if gated_time_bounds is not None:
            lower_bound, upper_bound = gated_time_bounds
            if trigger_time < lower_bound - 1e-12 or trigger_time > upper_bound + 1e-12:
                untranslated.append(
                    (
                        event,
                        "state threshold crosses outside its fixed time gate",
                    )
                )
                continue
            window_end = (
                min(window_end, upper_bound) if window_end is not None else upper_bound
            )
        execution_time = trigger_time
        delay = 0.0
        if event.delay:
            delay = fold_at_state(event.delay, trigger_time, event_context=event)
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
            if affine_interval is not None or window_end is not None:
                normal_converted += 1
                continue
            untranslated.append(
                (event, "nonpersistent delayed event may be canceled at the window end")
            )
            continue

        sets: List[Tuple[str, str, float]] = []
        event_values: List[Tuple[str, float]] = []
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
                    if trajectory_kind == "affine":
                        state_value = initial_value + rate * evaluation_time
                    elif trajectory_kind == "square_linear":
                        radicand = (
                            initial_value * initial_value + rate * evaluation_time
                        )
                        state_value = math.sqrt(radicand) if radicand >= 0 else math.inf
                    else:
                        state_value = initial_value * math.exp(rate * evaluation_time)
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
                event_context=event,
            )
            if value is None and execution_time == 0:
                value = fold_initial(expression)
            if value is None:
                failure = (
                    f'assignment "{variable} := {expression}" is not constant '
                    "(depends on species/time or a function)"
                )
                break
            event_values.append((standardize_name(variable), value))
            if affine_interval is not None and standardize_name(
                variable
            ) == standardize_name(affine_interval[0]):
                (
                    _identifier,
                    trajectory_kind,
                    initial,
                    slope,
                    _entry,
                    lower,
                    upper,
                    _exit,
                    lower_operator,
                    upper_operator,
                    _entry_state,
                ) = affine_interval

                def in_interval(state: float) -> bool:
                    lower_ok = (
                        state > lower if lower_operator == "gt" else state >= lower
                    )
                    upper_ok = (
                        state < upper if upper_operator == "lt" else state <= upper
                    )
                    return lower_ok and upper_ok

                state_before = (
                    initial + slope * execution_time
                    if trajectory_kind == "affine"
                    else initial * math.exp(slope * execution_time)
                )
                no_reentry_within_run = False
                if trajectory_kind == "affine" and slope > 0 and value < lower:
                    next_entry = execution_time + (lower - value) / slope
                    no_reentry_within_run = next_entry > max(
                        context.base_t_end, execution_time
                    )
                elif trajectory_kind == "affine" and slope < 0 and value > upper:
                    next_entry = execution_time + (upper - value) / slope
                    no_reentry_within_run = next_entry > max(
                        context.base_t_end, execution_time
                    )
                if not (
                    (in_interval(state_before) and in_interval(value))
                    or (trajectory_kind == "affine" and slope > 0 and value >= upper)
                    or (trajectory_kind == "affine" and slope < 0 and value <= lower)
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
                sets.extend(
                    ("volume", standardize_name(compartment), value)
                    for compartment in context.resolve_event_volume_assignment_targets(
                        variable, event
                    )
                )
            else:
                failure = (
                    f' assignment target "{variable}" is neither a known species '
                    "nor a parameter"
                ).lstrip()
                break
        if failure is not None:
            untranslated.append((event, failure))
            continue

        if (
            event_changes_trigger_state
            and trigger_state_trajectory is not None
            and trigger_state_trajectory[1] == "exponential"
        ):
            if len(events) != 1 or event.delay:
                failure = (
                    "exponential self-reset requires one undelayed event to prove "
                    "that the trigger cannot re-enter"
                )
            elif trigger_threshold_value is None:
                failure = "exponential self-reset has no proven trigger threshold"
            else:
                identifier, _kind, _initial, exponent = trigger_state_trajectory
                assigned_state = next(
                    (
                        value
                        for symbol, value in event_values
                        if standardize_name(symbol) == standardize_name(identifier)
                    ),
                    None,
                )
                if assigned_state is None:
                    failure = "exponential self-reset does not assign its trigger state"
                else:
                    threshold_value = trigger_threshold_value
                    reset_trigger_true = (
                        assigned_state > threshold_value
                        if operator == "gt"
                        else (
                            assigned_state >= threshold_value
                            if operator == "geq"
                            else (
                                assigned_state < threshold_value
                                if operator == "lt"
                                else assigned_state <= threshold_value
                            )
                        )
                    )
                    if not reset_trigger_true and exponent != 0:
                        rising = (
                            operator in {"gt", "geq"} and threshold_value * exponent > 0
                        ) or (
                            operator in {"lt", "leq"} and threshold_value * exponent < 0
                        )
                        ratio = (
                            threshold_value / assigned_state if assigned_state else -1
                        )
                        if rising and ratio > 0:
                            reentry_time = execution_time + math.log(ratio) / exponent
                            if (
                                math.isfinite(reentry_time)
                                and reentry_time <= context.base_t_end + 1e-12
                            ):
                                failure = (
                                    "exponential self-reset can make the state trigger "
                                    "re-enter within the simulation horizon"
                                )
            if failure is not None:
                untranslated.append((event, failure))
                continue

        priority = 0.0
        dynamic_priority = False
        if getattr(event, "priority", None):
            folded_priority = fold(
                event.priority or "", execution_time, event_context=event
            )
            if folded_priority is None and simultaneous_priority_group_eligible(
                event, trigger_time, execution_time, delay
            ):
                state_priority = fold_at_state(
                    event.priority or "",
                    execution_time,
                    state_values={"time": execution_time},
                    event_context=event,
                    priority_evaluation=True,
                )
                if state_priority is not None:
                    folded_priority = state_priority
                    dynamic_priority = True
            if folded_priority is None:
                untranslated.append(
                    (
                        event,
                        f'priority "{event.priority}" is not compile-time constant',
                    )
                )
                continue
            priority = folded_priority
        scheduled.append(
            (execution_time, sets, priority, event, dynamic_priority, event_values)
        )
        scheduled_values.extend(
            (execution_time, symbol, value) for symbol, value in event_values
        )
        normal_converted += 1

    if not scheduled:
        return EventTranslationResult(
            None,
            periodic_converted + normal_converted,
            untranslated,
            horizon_limited,
        )

    scheduled.sort(key=lambda item: item[0])
    normalized_scheduled = [
        item if len(item) == 6 else (item[0], item[1], item[2], None, False, [])
        for item in scheduled
    ]
    ordered_scheduled: List[
        Tuple[
            float,
            List[Tuple[str, str, float]],
            float,
            Optional[SBMLEvent],
            bool,
            List[Tuple[str, float]],
        ]
    ] = []
    index = 0
    while index < len(normalized_scheduled):
        end = index + 1
        while (
            end < len(normalized_scheduled)
            and abs(normalized_scheduled[end][0] - normalized_scheduled[index][0])
            < 1e-12
        ):
            end += 1
        group = normalized_scheduled[index:end]
        if not any(item[4] for item in group):
            priority_order = sorted(group, key=lambda item: -item[2])
            group_events = [item[3] for item in group]
            group_is_complete = (
                len(group) == len(events)
                and all(event is not None for event in group_events)
                and {id(event) for event in group_events if event is not None}
                == {id(event) for event in events}
            )
            if (
                static_initial_gates_are_safe
                and group_is_complete
                and any(
                    event is not None and event.trigger_persistent is False
                    for event in group_events
                )
            ):
                # SBML cancels a pending nonpersistent event as soon as an
                # earlier same-time assignment makes its trigger false.
                event_state: dict[str, float] = {"time": group[0][0]}
                for event in group_events:
                    assert event is not None
                    for symbol in re.findall(
                        r"[A-Za-z_][A-Za-z0-9_]*", event.trigger or ""
                    ):
                        if standardize_name(symbol) == "time":
                            continue
                        initial_value = context.resolve_initial_value(symbol)
                        if initial_value is None or not math.isfinite(initial_value):
                            continue
                        event_state[symbol] = float(initial_value)
                        event_state[standardize_name(symbol)] = float(initial_value)

                remaining = list(priority_order)
                ordered_group = []
                while remaining:
                    selected = remaining.pop(0)
                    selected_event = selected[3]
                    if selected_event is not None and (
                        selected_event.trigger_persistent is False
                    ):
                        trigger_value = fold(
                            selected_event.trigger,
                            selected[0],
                            dynamic_values=event_state,
                            event_context=selected_event,
                        )
                        if trigger_value is None or not math.isfinite(trigger_value):
                            group_is_complete = False
                            break
                        if trigger_value == 0:
                            continue

                    ordered_group.append(selected)
                    for symbol, value in selected[5]:
                        event_state[symbol] = value
                        event_state[standardize_name(symbol)] = value

                    pending = []
                    for item in remaining:
                        event = item[3]
                        if event is not None and event.trigger_persistent is False:
                            trigger_value = fold(
                                event.trigger,
                                item[0],
                                dynamic_values=event_state,
                                event_context=event,
                            )
                            if trigger_value is None or not math.isfinite(
                                trigger_value
                            ):
                                group_is_complete = False
                                break
                            if trigger_value == 0:
                                continue
                        pending.append(item)
                    if not group_is_complete:
                        break
                    remaining = pending

                if group_is_complete:
                    ordered_scheduled.extend(ordered_group)
                else:
                    normal_converted -= sum(item[3] is not None for item in group)
                    for item in group:
                        if item[3] is not None:
                            untranslated.append(
                                (
                                    item[3],
                                    "simultaneous nonpersistent event cancellation "
                                    "could not be resolved",
                                )
                            )
            else:
                ordered_scheduled.extend(priority_order)
            index = end
            continue

        group_events = [item[3] for item in group]
        group_is_complete = (
            len(group) == len(events)
            and all(event is not None for event in group_events)
            and {id(event) for event in group_events if event is not None}
            == {id(event) for event in events}
        )
        if group_is_complete:
            for event in group_events:
                assert event is not None
                threshold = parse_time_threshold(event.trigger)
                trigger_time = (
                    fold(threshold, event_context=event)
                    if threshold is not None
                    else None
                )
                delay = (
                    fold_at_state(event.delay, trigger_time, event_context=event)
                    if event.delay and trigger_time is not None
                    else 0.0
                )
                if (
                    trigger_time is None
                    or delay is None
                    or not math.isfinite(trigger_time)
                    or not math.isfinite(delay)
                    or not simultaneous_priority_group_eligible(
                        event, trigger_time, trigger_time + delay, delay
                    )
                ):
                    group_is_complete = False
                    break
        ordered_group: List[
            Tuple[
                float,
                List[Tuple[str, str, float]],
                float,
                Optional[SBMLEvent],
                bool,
                List[Tuple[str, float]],
            ]
        ] = []
        if group_is_complete:
            remaining = list(group)
            event_state: dict[str, float] = {"time": group[0][0]}
            while remaining:
                if len(remaining) == 1:
                    ordered_group.extend(remaining)
                    break
                priorities: List[float] = []
                for item in remaining:
                    event = item[3]
                    assert event is not None
                    priority = (
                        fold_at_state(
                            event.priority,
                            item[0],
                            state_values=event_state,
                            event_context=event,
                            priority_evaluation=True,
                        )
                        if event.priority
                        else 0.0
                    )
                    if priority is None or not math.isfinite(priority):
                        group_is_complete = False
                        break
                    priorities.append(priority)
                if not group_is_complete:
                    break
                selected_index = max(
                    range(len(remaining)), key=lambda candidate: priorities[candidate]
                )
                selected = remaining.pop(selected_index)
                ordered_group.append(selected)
                for symbol, value in selected[5]:
                    event_state[symbol] = value
                    event_state[standardize_name(symbol)] = value
        if group_is_complete:
            ordered_scheduled.extend(ordered_group)
        else:
            normal_converted -= sum(item[3] is not None for item in group)
            periodic_converted -= sum(item[3] is None for item in group)
            for item in group:
                if item[3] is not None:
                    untranslated.append(
                        (
                            item[3],
                            "simultaneous dynamic-priority event group could not be "
                            "ordered soundly",
                        )
                    )
        index = end

    merged: List[Tuple[float, List[Tuple[str, str, float]]]] = []
    for time, sets, _priority, _event, _dynamic_priority, _values in ordered_scheduled:
        if merged and abs(merged[-1][0] - time) < 1e-12:
            merged[-1][1].extend(sets)
        else:
            merged.append((time, list(sets)))

    if not merged:
        return EventTranslationResult(
            None,
            periodic_converted + normal_converted,
            untranslated,
            horizon_limited,
        )

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
            lines.extend(_render_sets(sets))

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
                f"t_start=>{_format_number(phase_start)}, "
                f"t_end=>{_format_number(end)}, n_steps=>{steps}}})"
            )
        for time, sets in merged:
            if time > 0 and abs(time - end) < 1e-12:
                lines.extend(_render_sets(sets))
        phase_start = end

    if abs(phase_start - t_final) > 1e-12:
        lines.append(
            f'simulate({{continue=>1, method=>"{method}", '
            f"t_start=>{_format_number(phase_start)}, "
            f"t_end=>{_format_number(t_final)}, "
            f"n_steps=>{steps_for(phase_start, t_final)}}})"
        )

    return EventTranslationResult(
        "\n".join(lines),
        periodic_converted + normal_converted,
        untranslated,
        horizon_limited,
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
