"""Independent, restricted evaluator for ordinary mass-action BNG2 .net files.

This intentionally supports only the arithmetic and scalar math used by the
frozen ``expr`` tier. Unknown names, function calls, and rate-law forms fail
closed so a newly unsupported source construct cannot become a false pass.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping, Sequence

from .compare import Network


class UnsupportedExpressionError(ValueError):
    """A .net expression falls outside the independently evaluated subset."""


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {
    "abs": abs,
    "acos": math.acos,
    "acosh": math.acosh,
    "asin": math.asin,
    "asinh": math.asinh,
    "atan": math.atan,
    "atanh": math.atanh,
    "ceil": math.ceil,
    "cos": math.cos,
    "cosh": math.cosh,
    "exp": math.exp,
    "floor": math.floor,
    "ln": math.log,
    "log": math.log10,
    "log10": math.log10,
    "log2": math.log2,
    "rint": round,
    "sin": math.sin,
    "sinh": math.sinh,
    "sqrt": math.sqrt,
    "tan": math.tan,
    "tanh": math.tanh,
}
_CONSTANTS = {"e": math.e, "pi": math.pi}


def _value(
    expression: str,
    definitions: Mapping[str, str],
    environment: Mapping[str, float],
    active: frozenset[str] = frozenset(),
) -> float:
    source = expression.replace("^", "**")
    try:
        root = ast.parse(source, mode="eval").body
    except SyntaxError as exc:
        raise UnsupportedExpressionError(
            f"unsupported expression syntax {expression!r}"
        ) from exc

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in environment:
                return float(environment[node.id])
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            if node.id not in definitions:
                raise UnsupportedExpressionError(
                    f"unknown symbol {node.id!r} in {expression!r}"
                )
            if node.id in active:
                raise UnsupportedExpressionError(
                    f"cyclic definition {node.id!r} in {expression!r}"
                )
            return _value(
                definitions[node.id], definitions, environment, active | {node.id}
            )
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            return _BINARY_OPERATORS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](visit(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = _FUNCTIONS.get(node.func.id)
            if function is None or node.keywords:
                raise UnsupportedExpressionError(
                    f"unsupported function {node.func.id!r} in {expression!r}"
                )
            return float(function(*(visit(argument) for argument in node.args)))
        raise UnsupportedExpressionError(
            f"unsupported expression node {type(node).__name__} in {expression!r}"
        )

    try:
        result = float(visit(root))
    except UnsupportedExpressionError:
        raise
    except (ArithmeticError, OverflowError, ValueError) as exc:
        raise UnsupportedExpressionError(
            f"could not evaluate {expression!r}: {exc}"
        ) from exc
    if not math.isfinite(result):
        raise UnsupportedExpressionError(f"non-finite result for {expression!r}")
    return result


def evaluate_rate_coefficients(
    network: Network, state: Sequence[float], time: float
) -> list[float]:
    """Evaluate per-reaction rate expressions from serialized BNG2 formulas.

    These values are the coefficients before ordinary mass-action species
    factors are applied. Unknown syntax and non-finite results fail closed.
    """
    if len(state) != network.n_species:
        raise ValueError(
            f"state has {len(state)} values for {network.n_species} species"
        )
    values = [float(value) for value in state]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("state must contain only finite values")
    if not math.isfinite(float(time)):
        raise ValueError("time must be finite")

    environment: dict[str, float] = {"time": float(time), "t": float(time)}
    for _, (name, weights) in network.groups.items():
        if name in environment:
            raise UnsupportedExpressionError(
                f"group collides with reserved name {name!r}"
            )
        environment[name] = sum(
            weight * values[index - 1] for index, weight in weights.items()
        )

    return [
        _value(rate_expression, network.rate_defs, environment)
        for _, _, rate_expression in network._raw
    ]


def evaluate_rhs(network: Network, state: Sequence[float], time: float) -> list[float]:
    """Evaluate a frozen-tier .net RHS from its serialized BNG2 formulas.

    All selected expression-tier reaction records use ordinary mass-action
    coefficients (functional formulas are coefficients, not total rates).
    Stoichiometric reactant repetition therefore both multiplies the rate and
    accumulates its negative derivative; product repetition accumulates the
    positive derivative. A ``$``-prefixed .net species is fixed: it still
    contributes to a reaction rate but receives no derivative. Typed
    Sat/MM/Hill total-rate records are rejected instead of guessed.
    """
    values = [float(value) for value in state]
    coefficients = evaluate_rate_coefficients(network, values, time)
    derivative = [0.0] * network.n_species
    for (reactants, products, _), coefficient in zip(network._raw, coefficients):
        rate = coefficient
        for index in reactants:
            rate *= values[index - 1]
        for index in reactants:
            if not network.species_by_index[index].startswith("$"):
                derivative[index - 1] -= rate
        for index in products:
            if not network.species_by_index[index].startswith("$"):
                derivative[index - 1] += rate
    return derivative
