"""Shared MathML built-in semantics for the modern SBML atomizer.

Three consumers have to agree on what a MathML built-in means:

* the parser, which turns a MathML call into the atomizer's formula text,
* the parser's static evaluator, which folds a constant expression to a
  number, and
* the writer, which lowers the same built-in onto a BNGL expression.

If they disagree, a folded constant and the model emitted from the same
source describe different systems.  For example the writer lowers ``exp(x)``
onto ``(2.71828182845905^(x))``: the constant is truncated, so the folded
value has to use the same constant or the emitted model and the folded
parameter differ in their last bits.

This module therefore holds one table.  Each record pairs the BNGL lowering
with the numeric evaluation of that lowering, so the two cannot drift.

The numeric evaluation deliberately reproduces the *lowered* expression
rather than the mathematically ideal one.  ``sqrt`` is evaluated as
``x ** 0.5`` (not ``math.sqrt``) and ``log10`` as ``ln(x)/2.302585093``
(not ``math.log10``) because those are what the emitted BNGL computes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple


def format_number(value: object) -> str:
    """Render a number as a literal that denotes exactly the same double.

    An emitted literal has to round-trip: a value that is written with
    fifteen significant digits denotes a different double from the value it
    came from, and a comparison against that literal then fails for the
    wrong reason.
    """

    # Preserve arbitrary-precision integer literals instead of converting
    # large factorials through float and raising OverflowError.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return str(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return repr(number)


# The writer lowers ``exp`` onto a power of a truncated constant, and
# ``log10`` onto a quotient by a truncated ``ln(10)``.  The evaluator has to
# use the same constants or a folded value disagrees with the emitted model.
TRUNCATED_E = 2.71828182845905
TRUNCATED_LN10 = 2.302585093


@dataclass(frozen=True)
class MathBuiltin:
    """One built-in and the three spellings that have to agree.

    ``name`` is the name the atomizer's formula language uses.  ``mathml``
    lists the MathML spellings that map onto it, so the parser can find the
    record for a MathML operator.  ``formula`` renders the parser's formula
    text for a call from its raw argument texts.  ``lower`` renders the BNGL
    text the writer emits; ``None`` means BNGL already defines the function
    and the writer leaves the call alone.  ``evaluate`` computes the value of
    the lowered expression from the evaluated argument values; ``None`` marks
    a built-in whose value cannot be reduced to a number.
    """

    name: str
    mathml: Tuple[str, ...] = ()
    formula: Optional[Callable[[Sequence[str]], str]] = None
    lower: Optional[Callable[[Sequence[str]], str]] = None
    evaluate: Optional[Callable[[Sequence[float]], float]] = None

    @property
    def lowering_names(self) -> Tuple[str, ...]:
        """Every spelling the writer's lowering applies to."""

        return (self.name,) + tuple(
            spelling for spelling in self.mathml if spelling != self.name
        )


def _call(name: str) -> Callable[[Sequence[str]], str]:
    """Render a call that keeps its own name."""

    def render(arguments: Sequence[str]) -> str:
        return f"{name}({', '.join(arguments)})"

    return render


def _lower_unary(fallback_name: str, template: str) -> Callable[[Sequence[str]], str]:
    """Lower a one-argument call onto ``template``."""

    def lower(arguments: Sequence[str]) -> str:
        if len(arguments) != 1:
            return f"{fallback_name}({', '.join(arguments)})"
        return template.format(arguments[0])

    return lower


def _lower_binary(
    name: str, template: str, single: Optional[str] = None
) -> Callable[[Sequence[str]], str]:
    """Lower a call that takes a base and a value, in that order."""

    def lower(arguments: Sequence[str]) -> str:
        if len(arguments) >= 2:
            return template.format(arguments[0], arguments[1])
        if len(arguments) == 1 and single is not None:
            return single.format(arguments[0])
        return f"{name}({', '.join(arguments)})"

    return lower


def _evaluate_unary(
    function: Callable[[float], float],
) -> Callable[[Sequence[float]], float]:
    def evaluate(values: Sequence[float]) -> float:
        return float(function(values[0]))

    return evaluate


def _abs(values: Sequence[float]) -> float:
    # The BNGL lowering is ``if(x>=0,x,-(x))``, so a negative zero keeps its
    # sign and a NaN stays a NaN.
    value = values[0]
    return value if value >= 0 else -value


def _exp(values: Sequence[float]) -> float:
    return TRUNCATED_E ** values[0]


def _log(values: Sequence[float]) -> float:
    # ``log(base, value)`` lowers to ``(ln(value)/ln(base))``.
    return math.log(values[1]) / math.log(values[0])


def _log10(values: Sequence[float]) -> float:
    # ``log10(value)`` lowers to ``(ln(value)/2.302585093)``.
    return math.log(values[0]) / TRUNCATED_LN10


def _root(values: Sequence[float]) -> float:
    # MathML's ``root`` takes the degree first and the radicand second, and
    # the lowering is ``((radicand)^(1/(degree)))``.
    return values[1] ** (1.0 / values[0])


def _power(values: Sequence[float]) -> float:
    return values[0] ** values[1]


def _factorial(values: Sequence[float]) -> float:
    value = values[0]
    if not math.isfinite(value) or value < 0.0 or math.floor(value) != value:
        raise ValueError("factorial expects a non-negative integer")
    if value > 170.0:
        raise OverflowError("factorial overflows double precision")
    result = 1.0
    current = 2.0
    while current <= value:
        result *= current
        current += 1.0
    return result


def _reciprocal(
    function: Callable[[float], float],
) -> Callable[[Sequence[float]], float]:
    def evaluate(values: Sequence[float]) -> float:
        return 1.0 / function(values[0])

    return evaluate


def _inverse_reciprocal(
    function: Callable[[float], float],
) -> Callable[[Sequence[float]], float]:
    def evaluate(values: Sequence[float]) -> float:
        return function(1.0 / values[0])

    return evaluate


def _quotient(values: Sequence[float]) -> float:
    return float(math.floor(values[0] / values[1]))


def _remainder(values: Sequence[float]) -> float:
    # SBML defines ``rem`` as ``a - b*floor(a/b)``, which differs from a
    # truncating remainder for a negative dividend.
    return values[0] - values[1] * math.floor(values[0] / values[1])


def _native(name: str, function: Callable[[float], float], *mathml: str) -> MathBuiltin:
    """A built-in BNGL already defines under the same name."""

    return MathBuiltin(
        name,
        tuple(mathml) or (name,),
        _call(name),
        None,
        _evaluate_unary(function),
    )


#: The built-ins the atomizer understands, in the order the writer lowers
#: them.  A record's ``lower`` renders the BNGL text of a call and its
#: ``evaluate`` computes the value of that text.
MATH_BUILTINS: "Tuple[MathBuiltin, ...]" = (
    MathBuiltin(
        "pow",
        ("pow",),
        _call("pow"),
        _lower_binary("pow", "(({0})^({1}))"),
        _power,
    ),
    MathBuiltin(
        "power",
        ("power",),
        _call("power"),
        _lower_binary("power", "(({0})^({1}))"),
        _power,
    ),
    MathBuiltin(
        "sqrt",
        ("sqrt",),
        _call("sqrt"),
        _lower_unary("sqrt", "(({0})^(1/2))"),
        _evaluate_unary(lambda value: value**0.5),
    ),
    MathBuiltin(
        "sqr",
        ("sqr",),
        _call("sqr"),
        _lower_unary("sqr", "(({0})^2)"),
        _evaluate_unary(lambda value: value**2),
    ),
    MathBuiltin(
        "exp",
        ("exp",),
        _call("exp"),
        _lower_unary("exp", f"({TRUNCATED_E}^({{0}}))"),
        _exp,
    ),
    MathBuiltin(
        "abs",
        ("abs",),
        _call("abs"),
        _lower_unary("abs", "if({0}>=0,{0},-({0}))"),
        _abs,
    ),
    MathBuiltin(
        "sec",
        ("sec",),
        _call("sec"),
        _lower_unary("sec", "(1/cos({0}))"),
        _reciprocal(math.cos),
    ),
    MathBuiltin(
        "csc",
        ("csc",),
        _call("csc"),
        _lower_unary("csc", "(1/sin({0}))"),
        _reciprocal(math.sin),
    ),
    MathBuiltin(
        "cot",
        ("cot",),
        _call("cot"),
        _lower_unary("cot", "(cos({0})/sin({0}))"),
        lambda values: math.cos(values[0]) / math.sin(values[0]),
    ),
    MathBuiltin(
        "arcsec",
        ("arcsec",),
        _call("arcsec"),
        _lower_unary("arcsec", "acos(1/({0}))"),
        _inverse_reciprocal(math.acos),
    ),
    MathBuiltin(
        "arccsc",
        ("arccsc",),
        _call("arccsc"),
        _lower_unary("arccsc", "asin(1/({0}))"),
        _inverse_reciprocal(math.asin),
    ),
    MathBuiltin(
        "arccot",
        ("arccot",),
        _call("arccot"),
        _lower_unary("arccot", "atan(1/({0}))"),
        _inverse_reciprocal(math.atan),
    ),
    MathBuiltin(
        "asinh",
        ("arcsinh",),
        _call("asinh"),
        _lower_unary("asinh", "asinh({0})"),
        _evaluate_unary(math.asinh),
    ),
    MathBuiltin(
        "acosh",
        ("arccosh",),
        _call("acosh"),
        _lower_unary("acosh", "acosh({0})"),
        _evaluate_unary(math.acosh),
    ),
    MathBuiltin(
        "atanh",
        ("arctanh",),
        _call("atanh"),
        _lower_unary("atanh", "atanh({0})"),
        _evaluate_unary(math.atanh),
    ),
    MathBuiltin(
        "arcsech",
        ("arcsech",),
        _call("arcsech"),
        _lower_unary("arcsech", "acosh(1/({0}))"),
        _inverse_reciprocal(math.acosh),
    ),
    MathBuiltin(
        "arccsch",
        ("arccsch",),
        _call("arccsch"),
        _lower_unary("arccsch", "asinh(1/({0}))"),
        _inverse_reciprocal(math.asinh),
    ),
    MathBuiltin(
        # MathML arccoth(x) is atanh(1/x) on the real domain |x| > 1.
        # Lower to BNGL's existing portable builtin instead of extending
        # its grammar or changing NFsim's builtin contract.
        "arccoth",
        ("arccoth",),
        lambda arguments: (f"atanh(1/({arguments[0]}))" if len(arguments) == 1 else ""),
        None,
        _inverse_reciprocal(math.atanh),
    ),
    MathBuiltin(
        "sech",
        ("sech",),
        _call("sech"),
        _lower_unary("sech", "(1/cosh({0}))"),
        _reciprocal(math.cosh),
    ),
    MathBuiltin(
        "csch",
        ("csch",),
        _call("csch"),
        _lower_unary("csch", "(1/sinh({0}))"),
        _reciprocal(math.sinh),
    ),
    MathBuiltin(
        "coth",
        ("coth",),
        _call("coth"),
        _lower_unary("coth", "(cosh({0})/sinh({0}))"),
        lambda values: math.cosh(values[0]) / math.sinh(values[0]),
    ),
    MathBuiltin(
        "log",
        ("log",),
        _call("log"),
        _lower_binary("log", "(ln({1})/ln({0}))", single="ln({0})"),
        _log,
    ),
    MathBuiltin(
        "log10",
        ("log10",),
        _call("log10"),
        _lower_unary("log10", f"(ln({{0}})/{TRUNCATED_LN10})"),
        _log10,
    ),
    MathBuiltin(
        "root",
        ("root",),
        _call("root"),
        _lower_binary("root", "(({1})^(1/({0})))", single="(({0})^(1/2))"),
        _root,
    ),
    MathBuiltin(
        "floor",
        ("floor",),
        _call("floor"),
        _lower_unary("floor", "floor({0})"),
        _evaluate_unary(math.floor),
    ),
    MathBuiltin(
        "ceil",
        ("ceiling",),
        _call("ceil"),
        _lower_unary("ceil", "ceil({0})"),
        _evaluate_unary(math.ceil),
    ),
    MathBuiltin(
        "quotient",
        ("quotient",),
        lambda arguments: (
            f"floor(({arguments[0]}) / ({arguments[1]}))" if len(arguments) >= 2 else ""
        ),
        None,
        _quotient,
    ),
    MathBuiltin(
        # SBML defines ``rem`` as ``a - b*floor(a/b)``, which differs from a
        # truncating remainder for a negative dividend.
        "rem",
        ("rem",),
        lambda arguments: (
            f"(({arguments[0]}) - ({arguments[1]}) * "
            f"floor(({arguments[0]}) / ({arguments[1]})))"
            if len(arguments) >= 2
            else ""
        ),
        None,
        _remainder,
    ),
    MathBuiltin(
        # A material implication, so its value is boolean and cannot be
        # reduced to a number.
        "implies",
        ("implies",),
        lambda arguments: (
            f"if({arguments[0]}, {arguments[1]}, 1)" if len(arguments) == 2 else ""
        ),
        None,
        None,
    ),
    _native("ln", math.log),
    _native("sin", math.sin),
    _native("cos", math.cos),
    _native("tan", math.tan),
    _native("asin", math.asin, "arcsin"),
    _native("acos", math.acos, "arccos"),
    _native("atan", math.atan, "arctan"),
    _native("sinh", math.sinh),
    _native("cosh", math.cosh),
    _native("tanh", math.tanh),
    MathBuiltin("factorial", ("factorial",), _call("factorial"), None, _factorial),
)

#: The built-in records by the name the formula language uses.
MATH_BUILTIN_BY_NAME: "Dict[str, MathBuiltin]" = {
    builtin.name: builtin for builtin in MATH_BUILTINS
}

#: The built-in records by the MathML spelling that maps onto them.
MATH_BUILTIN_BY_MATHML: "Dict[str, MathBuiltin]" = {
    spelling: builtin for builtin in MATH_BUILTINS for spelling in builtin.mathml
}


def math_builtin_formula(name: str, arguments: Sequence[str]) -> str:
    """Render the atomizer's formula text for one MathML built-in call."""

    builtin = MATH_BUILTIN_BY_MATHML.get(name)
    if builtin is None or builtin.formula is None:
        return f"{name}({', '.join(arguments)})"
    return builtin.formula(arguments)


def lower_math_builtin(name: str, arguments: Sequence[str]) -> str:
    """Render the BNGL lowering of one built-in call."""

    builtin = MATH_BUILTIN_BY_NAME.get(name)
    if builtin is None or builtin.lower is None:
        return f"{name}({', '.join(arguments)})"
    return builtin.lower(arguments)


def evaluate_math_builtin(name: str, values: Sequence[float]) -> Optional[float]:
    """Evaluate one built-in call from its argument values.

    Returns ``None`` when the built-in is unknown, when its arity does not
    match, or when its value is not a finite number.
    """

    builtin = MATH_BUILTIN_BY_NAME.get(name)
    if builtin is None or builtin.evaluate is None:
        return None
    try:
        value = builtin.evaluate(values)
    except (ArithmeticError, IndexError, TypeError, ValueError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


__all__ = [
    "MATH_BUILTINS",
    "MATH_BUILTIN_BY_MATHML",
    "MATH_BUILTIN_BY_NAME",
    "MathBuiltin",
    "TRUNCATED_E",
    "TRUNCATED_LN10",
    "evaluate_math_builtin",
    "format_number",
    "lower_math_builtin",
    "math_builtin_formula",
]
