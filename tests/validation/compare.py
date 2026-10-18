"""Comparators for differential validation.

One module, every comparison. Consolidates and corrects the logic that was
scattered across scripts/validate_*.py.

Key correctness fix over the old scripts: the .net comparator keys reactions by
structural species identity, not by species indices or raw serialization labels.
Two networks that are identical up to species ordering, site ordering, and bond
numbering compare equal; an extra or unmerged reaction still compares unequal.
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s.strip())


def _rate_definition_key(name: str) -> str:
    """Normalize .net function definitions to the names used in rate fields."""
    key = _norm(name)
    return key[:-2] if key.endswith("()") else key


# --------------------------------------------------------------------------- #
# .net parsing
# --------------------------------------------------------------------------- #
@dataclass
class Network:
    """A parsed reaction network, comparison-ready."""

    # species index (as written) -> source species string
    species_by_index: dict[int, str]
    # multiset of (sorted reactant strings, sorted product strings, rate-key)
    reaction_multiset: Counter
    # parameters/functions blocks: generated-name -> defining expression string.
    # Used to resolve a reaction's rate reference to a value (rate_mode="value"),
    # so two networks that differ only in auto-generated rate-parameter NAMES
    # (rateLaw4 vs _rateLaw4 vs __R1_local1) still compare equal — while a real
    # difference in the rate VALUE/expression is still caught.
    rate_defs: dict[str, str] = field(default_factory=dict)
    # The reaction list before rate resolution, so we can re-key under a
    # different rate_mode without re-reading the file.
    _raw: list = field(default_factory=list)
    # Rate-key semantics used when the parsed reaction multiset was built.
    rate_mode: str = "value"
    # Observable-group index -> (serialized label, species index -> weight).
    # BNG2 and BNG3 use different labels for some groups; the indexed weighted
    # membership is the semantic contract used by the network engine.
    groups: dict[int, tuple[str, dict[int, float]]] = field(default_factory=dict)
    # Names of zero-argument user functions. Their call suffix is present in
    # function definitions but omitted from reaction rate fields.
    rate_functions: set[str] = field(default_factory=set)
    # Names of observables from the NET groups block. Some writers serialize a
    # zero-argument observable as ``CheYp()`` while others use ``CheYp``.
    rate_observables: set[str] = field(default_factory=set)
    initial_amounts: dict[int, str] = field(default_factory=dict)

    @property
    def n_species(self) -> int:
        return len(self.species_by_index)

    @property
    def n_reactions(self) -> int:
        return sum(self.reaction_multiset.values())


# --------------------------------------------------------------------------- #
# Rate resolution: make auto-generated rate-parameter NAMES irrelevant while
# still comparing rate VALUES/expressions. See _resolve_rate.
# --------------------------------------------------------------------------- #
import math

_SAFE_NAMES = {
    "ln": math.log,
    # Perl's legacy ``log`` spelling is base-10; ``ln`` is natural log.
    "log": math.log10,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asinh": math.asinh,
    "acosh": math.acosh,
    "atanh": math.atanh,
    "rint": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
    "pi": math.pi,
    "e": math.e,
}


def _resolve_rate(
    token: str,
    rate_defs: dict[str, str],
    rate_mode: str,
    rate_functions: set[str] | None = None,
    rate_observables: set[str] | None = None,
) -> str:
    """Turn a reaction's 4th-field rate token into a comparison key.

    rate_mode="string"  -> the token verbatim (old behavior; byte-identical names).
    rate_mode="value"   -> resolve the token through the parameters/functions
                           table. If it constant-folds to a number, the key is
                           that number (so 0.5, k_synthC*2, and 1.0 all compare
                           equal when they evaluate equally). If it depends on
                           observables/time (a true function rate), the key is the
                           canonical expression with parameter names substituted —
                           a structural compare that still catches a different
                           expression but ignores the generated parameter name.
    """
    tok = _norm(token)
    if rate_mode == "string":
        return tok

    # NET kinetic-law fields contain positional arguments, not one arithmetic
    # token. Keep each resolved argument separate so Sat kcat Km cannot silently
    # lose both parameters or conflate adjacent numeric spellings.
    fields = tok.split()
    if len(fields) > 1 and fields[0] in {"Sat", "MM", "Hill", "Ele"}:
        arguments = [
            _resolve_rate(arg, rate_defs, rate_mode, rate_functions, rate_observables)
            for arg in fields[1:]
        ]
        return f"law:{fields[0]}({','.join(arguments)})"

    # Resolve complex top-level expressions (e.g. "2*rateLaw4" or "rateLaw1*2")
    # by evaluating them as expressions directly rather than just single symbol names.
    val, expr = _eval_expr(
        tok,
        rate_defs,
        set(),
        rate_functions or set(),
        rate_observables or set(),
    )
    if val is not None:
        # Rational rates are exact quantities. Keep their bounded source-level
        # canonical form so a nonzero coefficient such as 1e-999 cannot
        # underflow to the same float key as zero. Transcendental constants
        # retain the established numeric normalization below.
        if val == 0.0 and _has_underflowing_nonzero_literal(expr):
            return f"expr:{_canon_expr(expr)}"
        # Normalize serialization noise by significant digits. Decimal-place
        # rounding erased every rate below 5e-13, even equating it with zero.
        return repr(float(format(val, ".12g")))
    # Non-constant (references observables/time): compare the substituted,
    # canonicalized expression rather than the generated name.
    return f"expr:{_canon_expr(expr)}"


# Tokenizer for simple rate arithmetic: numbers, identifiers, operators, parens.
_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*(?:[eE][+-]?\d+)?|[()+\-*/^,]|\S")
_CANON_NUMERIC_LITERAL = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?\Z")
_MAX_CANON_NUMERIC_LITERAL_CHARS = 128
_MAX_CANON_NUMERIC_EXPONENT = 1000
_MAX_CANON_NUMERIC_BITS = 4096


def _is_rational_arithmetic(expr: str) -> bool:
    """Whether an expression contains only numeric literals and rational ops."""
    source = re.sub(r"\s+", "", expr).replace("^", "**")
    if not source or re.fullmatch(r"[\d.eE+*/^()\-]+", source) is None:
        return False
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return False

    def supported(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return supported(node.body)
        if isinstance(node, ast.Constant):
            return type(node.value) in (int, float)
        if isinstance(node, ast.UnaryOp):
            return isinstance(node.op, (ast.UAdd, ast.USub)) and supported(node.operand)
        if isinstance(node, ast.BinOp):
            return isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
            ) and (supported(node.left) and supported(node.right))
        return False

    return supported(tree)


def _has_underflowing_nonzero_literal(expr: str) -> bool:
    """Detect source literals that float evaluation would silently turn to 0."""
    literals = re.findall(
        r"\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?", expr
    )
    for literal in literals:
        if len(literal) > _MAX_CANON_NUMERIC_LITERAL_CHARS:
            continue
        mantissa = re.split(r"[eE]", literal, maxsplit=1)[0]
        if not any(character.isdigit() and character != "0" for character in mantissa):
            continue
        try:
            if float(literal) == 0.0:
                return True
        except ValueError:
            continue
    return False


def _eval_symbol(
    name: str,
    defs: dict[str, str],
    seen: set[str],
    rate_functions: set[str],
    rate_observables: set[str],
):
    """Resolve a symbol to (value|None, substituted_expression_string).

    Returns a float value when the symbol constant-folds; otherwise None and the
    fully name-substituted expression string (for structural comparison).
    """
    if name in seen:  # cycle guard
        return None, name
    if name not in defs:
        # A bare number, a built-in (Sat/MM/Hill...), or an observable/time:
        try:
            return float(name), name
        except ValueError:
            return None, name
    seen = seen | {name}
    return _eval_expr(defs[name], defs, seen, rate_functions, rate_observables)


def _eval_expr(
    expr: str,
    defs: dict[str, str],
    seen: set[str],
    rate_functions: set[str] | None = None,
    rate_observables: set[str] | None = None,
):
    """Evaluate a rate expression. (value|None, substituted_expr_string)."""
    toks = _TOKEN.findall(expr)
    rate_functions = rate_functions or set()
    rate_observables = rate_observables or set()
    # Substitute identifiers (that are defined parameters) for the structural form.
    sub_parts = []
    constant = True
    index = 0
    while index < len(toks):
        t = toks[index]
        if re.match(r"^[A-Za-z_]\w*$", t):
            if t in _SAFE_NAMES or t == "if":
                sub_parts.append(t)
            else:
                v, sub = _eval_symbol(t, defs, seen, rate_functions, rate_observables)
                if v is None:
                    constant = False
                    sub_parts.append(f"({sub})" if t in defs and sub != t else sub)
                elif t in defs and (
                    _is_rational_arithmetic(sub)
                    or (v == 0.0 and _has_underflowing_nonzero_literal(sub))
                ):
                    # Preserve exact numeric source for rational parameters
                    # and functions whose nonzero result underflows to zero.
                    sub_parts.append(f"({sub})")
                else:
                    sub_parts.append(repr(v))
            index += 1
            # A no-argument user function is written as f() in its definition,
            # while its expanded body is just an expression. Consume only the
            # empty call of known zero-argument functions; non-empty calls such
            # as TFUN(path, value) stay structural and fail closed.
            if t in rate_functions | rate_observables and toks[index : index + 2] == [
                "(",
                ")",
            ]:
                index += 2
        else:
            sub_parts.append(t)
            index += 1
    sub_expr = "".join(sub_parts)

    if not constant:
        return None, sub_expr
    # All leaves are numeric or safe math functions — safely evaluate the arithmetic.
    try:
        val = _safe_arith(sub_expr)
        return val, sub_expr
    except Exception:
        return None, sub_expr


class _ConditionalToIfExp(ast.NodeTransformer):
    """Preserve BNGL if's selected-branch evaluation in numeric expressions."""

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "_bng_if":
            if len(node.args) != 3 or node.keywords:
                raise ValueError("if expects three arguments")
            return ast.copy_location(
                ast.IfExp(test=node.args[0], body=node.args[1], orelse=node.args[2]),
                node,
            )
        return node


def _safe_arith(expr: str) -> float:
    """Evaluate a pure-numeric arithmetic expression with safe math functions."""
    e = expr.replace("^", "**").replace("&&", " and ").replace("||", " or ")

    # Check that all alphabetical tokens are allowed math functions
    for word in re.findall(r"\b[A-Za-z_]\w*\b", e):
        if word not in _SAFE_NAMES and word not in {"if", "and", "or", "True", "False"}:
            raise ValueError(f"unknown function or symbol {word!r}")

    ns = {
        "ln": math.log,
        "log": math.log10,
        "log10": math.log10,
        "log2": math.log2,
        "exp": math.exp,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "sinh": math.sinh,
        "cosh": math.cosh,
        "tanh": math.tanh,
        "asinh": math.asinh,
        "acosh": math.acosh,
        "atanh": math.atanh,
        "rint": round,
        "floor": math.floor,
        "ceil": math.ceil,
        "abs": abs,
        "pi": math.pi,
        "e": math.e,
    }
    # `if` is a Python keyword. Turn only BNGL calls into lazy conditional
    # expressions; a function wrapper would evaluate both branches eagerly.
    e = re.sub(r"\bif\s*(?=\()", "_bng_if", e)
    tree = _ConditionalToIfExp().visit(ast.parse(e, mode="eval"))
    ast.fix_missing_locations(tree)
    # Only approved functions — safe to eval in an empty namespace.
    return float(
        eval(compile(tree, "<numeric rate>", "eval"), {"__builtins__": {}}, ns)
    )


def _canon_expr(expr: str) -> str:
    """Canonicalize arithmetic spelling while preserving dynamic structure."""
    result = re.sub(r"\s+", "", expr)

    def strip_outer_parentheses(value: str) -> str:
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            encloses_all = True
            for index, char in enumerate(value):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0 and index != len(value) - 1:
                        encloses_all = False
                        break
            if not encloses_all or depth != 0:
                break
            value = value[1:-1]
        return value

    # BNG2 and BNG3 can wrap the same function argument or whole expression
    # with different numbers of redundant parentheses.
    result = strip_outer_parentheses(result)

    # BNG3 may wrap a compartment-scaled observable in a no-argument call,
    # e.g. ``(A/cell)()``; BNG2 writes the same term as ``A/cell()``. Remove
    # only the redundant outer call around a simple identifier quotient.
    result = re.sub(
        r"\(([A-Za-z_]\w*/(?:[A-Za-z_]\w*|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))\)\(\)",
        r"\1()",
        result,
    )

    while True:
        changed = False
        for index in range(len(result) - 1):
            if result[index] == "(" and result[index + 1] == "(":
                inner_depth = 0
                for end in range(index + 1, len(result)):
                    if result[end] == "(":
                        inner_depth += 1
                    elif result[end] == ")":
                        inner_depth -= 1
                        if inner_depth == 0:
                            if end + 1 < len(result) and result[end + 1] == ")":
                                result = (
                                    result[:index]
                                    + result[index + 1 : end + 1]
                                    + result[end + 2 :]
                                )
                                changed = True
                            break
                if changed:
                    break
        if not changed:
            break

    # BNG2 and BNG3 can serialize the same unary-minus product with different
    # redundant parentheses, e.g. ``(-(g/2))*x`` vs ``-(g/2)*x``.  Normalize
    # only the safe arithmetic subset; unsupported rate syntax keeps the
    # structural spelling above and therefore remains fail-closed.
    def supported(node: ast.AST) -> bool:
        if isinstance(node, (ast.Expression, ast.Name, ast.Constant)):
            return True
        if isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub, ast.Not)
        ):
            return supported(node.operand)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            return all(supported(value) for value in node.values)
        if isinstance(node, ast.Compare):
            return (
                all(
                    isinstance(
                        operator,
                        (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE),
                    )
                    for operator in node.ops
                )
                and supported(node.left)
                and all(supported(value) for value in node.comparators)
            )
        if isinstance(node, ast.IfExp):
            return (
                supported(node.test) and supported(node.body) and supported(node.orelse)
            )
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            return supported(node.left) and supported(node.right)
        if isinstance(node, ast.Call) and isinstance(
            node.func, (ast.Name, ast.Constant)
        ):
            return supported(node.func) and all(
                supported(argument) for argument in node.args
            )
        return False

    class NormalizeNegativeProduct(ast.NodeTransformer):
        def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
            node = self.generic_visit(node)
            if (
                isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.BinOp)
                and isinstance(node.operand.op, (ast.Mult, ast.Div))
            ):
                return ast.BinOp(
                    left=self.visit(
                        ast.UnaryOp(op=ast.USub(), operand=node.operand.left)
                    ),
                    op=node.operand.op,
                    right=node.operand.right,
                )
            return node

    class StripUnitMultiplications(ast.NodeTransformer):
        def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
            node = self.generic_visit(node)
            if isinstance(node.op, ast.Mult):
                if isinstance(node.left, ast.Constant) and node.left.value == 1:
                    return node.right
                if isinstance(node.right, ast.Constant) and node.right.value == 1:
                    return node.left
            return node

    class NormalizeProductOfQuotient(ast.NodeTransformer):
        def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
            node = self.generic_visit(node)
            if (
                isinstance(node.op, ast.Mult)
                and isinstance(node.right, ast.BinOp)
                and isinstance(node.right.op, ast.Div)
            ):
                # Normalize a*(b/c) to a*b/c. BNG2 and BNG3 differ in whether
                # the parser retains this redundant grouping in function
                # definitions; the arithmetic expression is the same.
                return ast.BinOp(
                    left=ast.BinOp(
                        left=node.left,
                        op=ast.Mult(),
                        right=node.right.left,
                    ),
                    op=ast.Div(),
                    right=node.right.right,
                )
            return node

    source = result.replace("^", "**").replace("&&", " and ").replace("||", " or ")
    source = re.sub(r"\bif\s*(?=\()", "_bng_if", source)

    def binary64_fraction(value: Fraction) -> Fraction:
        """Round representable numeric operations as the NET engines do.

        Retain out-of-range nonzero rationals rather than silently accepting
        underflow as zero or overflow as infinity.
        """
        try:
            rounded = float(value)
        except OverflowError:
            return value
        if math.isfinite(rounded) and (rounded != 0.0 or value == 0):
            return Fraction(rounded)
        return value

    def literal_fraction(node: ast.Constant) -> Fraction | None:
        literal = ast.get_source_segment(source, node)
        if literal is None or len(literal) > _MAX_CANON_NUMERIC_LITERAL_CHARS:
            return None
        match = _CANON_NUMERIC_LITERAL.fullmatch(literal)
        if match is None:
            return None
        exponent_text = match.group(1)
        if exponent_text is not None:
            # Bound before converting to int or constructing a large Fraction.
            exponent_digits = exponent_text.lstrip("+-")
            if len(exponent_digits) > 4:
                return None
            if abs(int(exponent_text)) > _MAX_CANON_NUMERIC_EXPONENT:
                return None
        try:
            value = binary64_fraction(Fraction(literal))
        except (OverflowError, ValueError, ZeroDivisionError):
            return None
        if (
            max(value.numerator.bit_length(), value.denominator.bit_length())
            > _MAX_CANON_NUMERIC_BITS
        ):
            return None
        return value

    def numeric_value(node: ast.AST) -> Fraction | None:
        """Evaluate a numeric subtree with binary64 rounding at each operation."""
        folded = getattr(node, "_canonical_fraction", None)
        if folded is not None:
            return folded
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return literal_fraction(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = numeric_value(node.operand)
            if value is not None:
                return value if isinstance(node.op, ast.UAdd) else -value
            return None
        if not isinstance(node, ast.BinOp):
            return None
        left = numeric_value(node.left)
        right = numeric_value(node.right)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return binary64_fraction(left + right)
            if isinstance(node.op, ast.Sub):
                return binary64_fraction(left - right)
            if isinstance(node.op, ast.Mult):
                return binary64_fraction(left * right)
            if isinstance(node.op, ast.Div):
                return binary64_fraction(left / right)
            if isinstance(node.op, ast.Pow) and right.denominator == 1:
                # Avoid pathological work from malformed or adversarial NETs.
                exponent = right.numerator
                operand_bits = max(
                    left.numerator.bit_length(), left.denominator.bit_length()
                )
                if abs(exponent) <= 10000 and operand_bits * abs(exponent) <= 4096:
                    return binary64_fraction(left**exponent)
        except (OverflowError, ZeroDivisionError, ValueError):
            return None
        return None

    def constant_truth(node: ast.AST) -> bool | None:
        """Prove only bounded, short-circuit-safe constant conditions."""
        if isinstance(node, ast.Constant) and type(node.value) is bool:
            return node.value
        number = numeric_value(node)
        if number is not None:
            return bool(number)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = constant_truth(node.operand)
            return None if value is None else not value
        if isinstance(node, ast.BoolOp):
            unknown = False
            for value_node in node.values:
                value = constant_truth(value_node)
                if isinstance(node.op, ast.And):
                    if value is False:
                        return False
                    if value is None:
                        unknown = True
                elif isinstance(node.op, ast.Or):
                    if value is True:
                        return True
                    if value is None:
                        unknown = True
                else:
                    return None
            return None if unknown else isinstance(node.op, ast.And)
        if isinstance(node, ast.Compare):
            left = numeric_value(node.left)
            if left is None:
                return None
            for operator, comparator in zip(node.ops, node.comparators):
                right = numeric_value(comparator)
                if right is None:
                    return None
                if isinstance(operator, ast.Eq):
                    result = left == right
                elif isinstance(operator, ast.NotEq):
                    result = left != right
                elif isinstance(operator, ast.Lt):
                    result = left < right
                elif isinstance(operator, ast.LtE):
                    result = left <= right
                elif isinstance(operator, ast.Gt):
                    result = left > right
                elif isinstance(operator, ast.GtE):
                    result = left >= right
                else:
                    return None
                if not result:
                    return False
                left = right
            return True
        return None

    class SimplifyConstantConditionals(ast.NodeTransformer):
        """Fold known if conditions without visiting the discarded branch."""

        def visit_Call(self, node: ast.Call) -> ast.AST:
            if isinstance(node.func, ast.Name) and node.func.id == "_bng_if":
                if len(node.args) != 3 or node.keywords:
                    raise ValueError("if expects three arguments")
                test = self.visit(node.args[0])
                selected = constant_truth(test)
                if selected is not None:
                    return self.visit(node.args[1] if selected else node.args[2])
                return ast.copy_location(
                    ast.IfExp(
                        test=test,
                        body=self.visit(node.args[1]),
                        orelse=self.visit(node.args[2]),
                    ),
                    node,
                )
            return self.generic_visit(node)

    class FoldNumericSubtrees(ast.NodeTransformer):
        """Use exact value markers for numeric terms in dynamic rates."""

        @staticmethod
        def _marker(value: Fraction, location: ast.AST) -> ast.Constant:
            marker = ast.Constant(
                value=f"__rational_{value.numerator}_{value.denominator}__"
            )
            marker._canonical_fraction = value
            return ast.copy_location(marker, location)

        def visit_Constant(self, node: ast.Constant) -> ast.AST:
            if type(node.value) in (int, float):
                value = numeric_value(node)
                if value is not None:
                    return self._marker(value, node)
            return node

        def _fold(self, node: ast.AST) -> ast.AST:
            node = self.generic_visit(node)
            if isinstance(node, (ast.UnaryOp, ast.BinOp)):
                value = numeric_value(node)
                if value is not None:
                    return self._marker(value, node)
            return node

        def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
            return self._fold(node)

        def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
            return self._fold(node)

    try:
        tree = ast.parse(source, mode="eval")
        tree = SimplifyConstantConditionals().visit(tree)
        ast.fix_missing_locations(tree)
        numeric_literals_are_bounded = all(
            literal_fraction(node) is not None
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and type(node.value) in (int, float)
        )
        if supported(tree) and numeric_literals_are_bounded:
            normalized = NormalizeNegativeProduct().visit(tree)
            normalized = StripUnitMultiplications().visit(normalized)
            normalized = NormalizeProductOfQuotient().visit(normalized)
            normalized = FoldNumericSubtrees().visit(normalized)
            result = re.sub(r"\s+", "", ast.unparse(normalized))
    except (SyntaxError, ValueError):
        pass
    return result


def split_species(s: str) -> list[str]:
    """Split a species string into a list of molecules separated by '.' (outside parens)."""
    parts: list[str] = []
    curr: list[str] = []
    depth = 0
    for char in s:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "." and depth == 0:
            parts.append("".join(curr))
            curr = []
            continue
        curr.append(char)
    if curr:
        parts.append("".join(curr))
    return parts


def renumber_bonds(s: str) -> str:
    """Renumber integer bond indices (!1, !2...) in order of left-to-right appearance."""
    bonds = re.findall(r"!(\d+)", s)
    if not bonds:
        return s
    mapping = {}
    next_id = 1
    for b in bonds:
        if b not in mapping:
            mapping[b] = str(next_id)
            next_id += 1
    return re.sub(r"!(\d+)", lambda m: "!" + mapping[m.group(1)], s)


def split_sites(mol: str) -> tuple[str, list[str]]:
    """Parse a molecule string 'Name(s1,s2,...)' into (name, [site_tokens]).

    Returns (mol, []) for molecules without parentheses.
    Each site token is a string like 'a', 'a~p', 'a!1', 'a~p!1', 'a!+'.
    """
    paren = mol.find("(")
    if paren == -1 or not mol.endswith(")"):
        return mol, []
    name = mol[:paren]
    inner = mol[paren + 1 : -1]
    # Split inner by commas (sites are flat — no nested parens in BNGL site lists)
    sites = [t.strip() for t in inner.split(",")] if inner else []
    return name, sites


@dataclass
class _SpeciesGraph:
    """Small labeled graph used for species identity checks.

    Molecules and sites are vertices.  Molecule-site edges retain site
    membership; site-site edges retain explicit bond connectivity.  Bond
    numbers are deliberately absent because they are serialization labels,
    not model identity.
    """

    header: tuple[str, tuple[str, ...]]
    labels: list[tuple[str, ...]]
    adjacency: list[list[tuple[int, str]]]


def _split_species_compartment(value: str) -> tuple[str, str]:
    """Return ``(species-compartment, body)`` for a leading ``@C::`` prefix."""

    if value.startswith("@"):
        marker = value.find("::")
        if marker > 1:
            return value[1:marker], value[marker + 2 :]
    return "", value


def _split_molecule_compartment(value: str) -> tuple[str, str]:
    """Return ``(molecule, compartment)`` for a top-level ``@C`` suffix."""

    depth = 0
    for index in range(len(value) - 1, -1, -1):
        char = value[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
        elif char == "@" and depth == 0:
            return value[:index], value[index + 1 :]
    return value, ""


def _parse_species_graph(value: str) -> _SpeciesGraph | None:
    """Parse a concrete BNGL species into a labeled graph.

    This intentionally handles concrete ``.net`` species, not arbitrary BNGL
    patterns.  Unknown site syntax remains part of a label instead of being
    silently discarded.
    """

    value = _norm(value)
    if not value:
        return None

    species_compartment, body = _split_species_compartment(value)
    annotations = tuple(re.findall(r"\{[^}]*\}", body))
    body = re.sub(r"\{[^}]*\}", "", body)
    molecules = split_species(body)
    if not molecules or any(not molecule.strip() for molecule in molecules):
        return None

    labels: list[tuple[str, ...]] = []
    adjacency: list[list[tuple[int, str]]] = []
    bonds: defaultdict[str, list[int]] = defaultdict(list)

    def add_vertex(label: tuple[str, ...]) -> int:
        labels.append(label)
        adjacency.append([])
        return len(labels) - 1

    def add_edge(left: int, right: int, kind: str) -> None:
        adjacency[left].append((right, kind))
        adjacency[right].append((left, kind))

    for molecule in molecules:
        molecule, molecule_compartment = _split_molecule_compartment(molecule.strip())
        molecule = molecule.strip()
        if not molecule:
            return None
        if not molecule_compartment:
            molecule_compartment = species_compartment

        is_constant = molecule.startswith("$")
        constant = "1" if is_constant else "0"
        if is_constant:
            molecule = molecule[1:]
        name, sites = split_sites(molecule)
        if not name:
            return None

        molecule_vertex = add_vertex(("molecule", name, molecule_compartment, constant))
        for site in sites:
            site = site.strip()
            if not site:
                return None
            if "!" in site:
                site_body, bond = site.rsplit("!", 1)
                if bond.isdigit() and int(bond) > 0:
                    bond_kind = "explicit"
                    bonds[bond].append(len(labels))
                elif bond in ("+", "?"):
                    bond_kind = f"wildcard:{bond}"
                else:
                    bond_kind = f"unknown:{bond}"
            else:
                site_body = site
                bond_kind = "free"

            if "~" in site_body:
                site_name, state = site_body.split("~", 1)
            else:
                site_name, state = site_body, ""
            if not site_name:
                return None
            site_vertex = add_vertex(("site", site_name, state, bond_kind))
            add_edge(molecule_vertex, site_vertex, "membership")

    for bond, endpoints in bonds.items():
        if len(endpoints) == 2:
            add_edge(endpoints[0], endpoints[1], "bond")
        else:
            # Preserve malformed/dangling explicit bonds without treating the
            # numeric label itself as identity.  Valid .net files take the
            # two-endpoint path above.
            bond_vertex = add_vertex(("bond", str(len(endpoints))))
            for endpoint in endpoints:
                add_edge(bond_vertex, endpoint, "bond")

    return _SpeciesGraph(
        header=(species_compartment, annotations),
        labels=labels,
        adjacency=adjacency,
    )


def _edge_profile(graph: _SpeciesGraph, left: int, right: int) -> Counter:
    return Counter(
        kind for endpoint, kind in graph.adjacency[left] if endpoint == right
    )


def _refined_colors(
    left: _SpeciesGraph, right: _SpeciesGraph
) -> tuple[list[int], list[int]]:
    """Compute comparable Weisfeiler-Lehman colors for two labeled graphs."""

    def initial(graph: _SpeciesGraph, vertex: int) -> tuple:
        return (
            graph.labels[vertex],
            len(graph.adjacency[vertex]),
            tuple(
                sorted(
                    (kind, graph.labels[endpoint])
                    for endpoint, kind in graph.adjacency[vertex]
                )
            ),
        )

    signatures = [initial(left, i) for i in range(len(left.labels))]
    signatures += [initial(right, i) for i in range(len(right.labels))]

    def assign(values: list[tuple]) -> list[int]:
        table = {
            value: index for index, value in enumerate(sorted(set(values), key=repr))
        }
        return [table[value] for value in values]

    colors = assign(signatures)
    left_colors = colors[: len(left.labels)]
    right_colors = colors[len(left.labels) :]
    for _ in range(max(len(left.labels), len(right.labels))):
        combined = []
        for graph, graph_colors in ((left, left_colors), (right, right_colors)):
            combined.extend(
                (
                    graph_colors[vertex],
                    tuple(
                        sorted(
                            (kind, graph_colors[endpoint])
                            for endpoint, kind in graph.adjacency[vertex]
                        )
                    ),
                )
                for vertex in range(len(graph.labels))
            )
        refined = assign(combined)
        new_left = refined[: len(left.labels)]
        new_right = refined[len(left.labels) :]
        if new_left == left_colors and new_right == right_colors:
            break
        left_colors, right_colors = new_left, new_right
    return left_colors, right_colors


@lru_cache(maxsize=4096)
def species_isomorphic(
    left: str,
    right: str,
    molecule_name_aliases: tuple[tuple[str, str], ...] = (),
) -> bool:
    """Return whether two concrete species have the same labeled graph.

    Molecule/site order and explicit bond numbers may differ.  Molecule names,
    site names/states, wildcard bonds, compartments, and bond connectivity must
    match after any explicit source-specific molecule-name aliases are applied.
    The implementation uses refinement followed by constrained backtracking,
    which keeps the symmetry-heavy ``blbr`` complexes tractable.
    """

    left_graph = _parse_species_graph(left)
    right_graph = _parse_species_graph(right)
    if left_graph is None or right_graph is None:
        return _norm(left) == _norm(right)
    aliases = dict(molecule_name_aliases)
    for index, label in enumerate(left_graph.labels):
        if label[0] == "molecule" and label[1] in aliases:
            left_graph.labels[index] = (label[0], aliases[label[1]], *label[2:])
    if left_graph.header != right_graph.header:
        return False
    if len(left_graph.labels) != len(right_graph.labels):
        return False

    left_colors, right_colors = _refined_colors(left_graph, right_graph)
    if Counter(left_colors) != Counter(right_colors):
        return False
    if Counter(
        (left_graph.labels[i], len(left_graph.adjacency[i]), left_colors[i])
        for i in range(len(left_graph.labels))
    ) != Counter(
        (right_graph.labels[i], len(right_graph.adjacency[i]), right_colors[i])
        for i in range(len(right_graph.labels))
    ):
        return False

    candidates = {
        vertex: [
            other
            for other in range(len(right_graph.labels))
            if left_colors[vertex] == right_colors[other]
            and left_graph.labels[vertex] == right_graph.labels[other]
            and len(left_graph.adjacency[vertex]) == len(right_graph.adjacency[other])
        ]
        for vertex in range(len(left_graph.labels))
    }
    mapping: dict[int, int] = {}
    used: set[int] = set()

    def choose_vertex() -> int:
        remaining = [i for i in range(len(left_graph.labels)) if i not in mapping]
        return min(
            remaining,
            key=lambda i: (
                -sum(
                    1 for endpoint, _ in left_graph.adjacency[i] if endpoint in mapping
                ),
                -len(left_graph.adjacency[i]),
                len(candidates[i]),
            ),
        )

    def compatible(vertex: int, other: int) -> bool:
        for mapped_vertex, mapped_other in mapping.items():
            if _edge_profile(left_graph, vertex, mapped_vertex) != _edge_profile(
                right_graph, other, mapped_other
            ):
                return False
        return True

    def search() -> bool:
        if len(mapping) == len(left_graph.labels):
            return True
        vertex = choose_vertex()
        for other in candidates[vertex]:
            if other in used or not compatible(vertex, other):
                continue
            mapping[vertex] = other
            used.add(other)
            if search():
                return True
            used.remove(other)
            del mapping[vertex]
        return False

    return search()


def normalize_molecule(mol: str) -> str:
    """Return a form of mol with sites sorted lexicographically.

    Bond indices (!N) are first replaced with a placeholder (!) so that the
    sort key is topology-invariant. This is used only for grouping; the actual
    molecule string passed to permutation search retains original bond indices.
    """
    name, sites = split_sites(mol)
    if not sites:
        return mol
    # Replace bond indices with placeholder for stable sort key
    norm_sites = sorted(re.sub(r"!\d+", "!", st) for st in sites)
    return name + "(" + ",".join(norm_sites) + ")"


def _mol_site_orderings(mol: str) -> list[str]:
    """Generate all orderings of the site list within a single molecule string.

    Returns a list of molecule strings with every permutation of sites, each
    already using the original bond indices (renumbering happens later over the
    full species string).
    """
    import itertools

    name, sites = split_sites(mol)
    if len(sites) <= 1:
        return [mol]
    perms = list(itertools.permutations(sites))
    return [name + "(" + ",".join(p) + ")" for p in perms]


def canonicalize_species(s: str) -> str:
    """Canonicalize a BNGL species string to a graph-isomorphism-invariant form.

    Invariant to molecule order, bond index numbering, and site ordering within
    each molecule. Uses a BFS traversal from each possible root molecule to
    produce traversal-order bond renumbering, then picks the lex-min result.

    This correctly handles symmetric structures like blbr 5L+5R rings where
    WL coloring alone cannot distinguish molecule positions.
    """
    import itertools
    from collections import defaultdict, deque

    mols = split_species(s)
    n = len(mols)

    if n == 1:
        # Normalize site order for single-molecule species
        name, sites = split_sites(mols[0])
        if len(sites) <= 1:
            return mols[0]
        sorted_sites = sorted(
            sites, key=lambda st: (re.sub(r"!\d+", "", st), "!" in st)
        )
        return name + "(" + ",".join(sorted_sites) + ")"

    # --- Parse each molecule ---
    parsed: list[tuple[str, list[tuple[str, int | None]]]] = []
    for mol in mols:
        name, sites = split_sites(mol)
        parsed_sites: list[tuple[str, int | None]] = []
        for st in sites:
            m = re.match(r"^([^!~]*)(?:~[^!]*)?(?:!(\d+|[+?]))?$", st)
            if m:
                site_name = m.group(1) or ""
                bond_raw = m.group(2)
                if bond_raw is None:
                    bond_idx: int | None = None
                elif bond_raw in ("+", "?"):
                    bond_idx = -1
                else:
                    bond_idx = int(bond_raw)
            else:
                site_name = re.sub(r"!.*", "", st)
                bond_idx = None
            parsed_sites.append((site_name, bond_idx))
        parsed.append((name, parsed_sites))

    # --- Build bond adjacency (molecule-level) ---
    bond_to_mols: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for mi, (_, psites) in enumerate(parsed):
        for si, (_, bidx) in enumerate(psites):
            if bidx is not None and bidx > 0:
                bond_to_mols[bidx].append((mi, si))

    # mol_bonds: mol_idx -> list of (neighbor_mol_idx, my_site_idx, their_site_idx, bond_idx)
    mol_bonds: list[list[tuple[int, int, int, int]]] = [[] for _ in range(n)]
    for bidx, eps in bond_to_mols.items():
        if len(eps) == 2:
            (mi1, si1), (mi2, si2) = eps
            mol_bonds[mi1].append((mi2, si1, si2, bidx))
            mol_bonds[mi2].append((mi1, si2, si1, bidx))

    # Pre-compute neighbor degree (connectivity) for canonical BFS ordering
    # This is bond-count independent: uses site names and free-site count
    def _mol_sig(mi: int) -> tuple:
        """Canonical signature of molecule mi for BFS ordering."""
        name, psites = parsed[mi]
        free_sites = sorted(sn for sn, bidx in psites if bidx is None)
        bonded_count = sum(1 for _, bidx in psites if bidx is not None and bidx > 0)
        return (name, bonded_count, tuple(free_sites))

    mol_sigs = [_mol_sig(i) for i in range(n)]

    # Sort each adjacency list by (neighbor_sig, my_site_name, their_site_name)
    # This is fully independent of original bond indices
    for mi, bl in enumerate(mol_bonds):
        bl.sort(
            key=lambda t: (
                mol_sigs[t[0]],
                parsed[mi][1][t[1]][0],
                parsed[t[0]][1][t[2]][0],
            )
        )

    def _serialize_from_root(root: int) -> str:
        """BFS from `root`, serialize in BFS order with bond renumbering."""
        visited_order: list[int] = []
        queue: deque[int] = deque([root])
        visited: set[int] = {root}
        while queue:
            mi = queue.popleft()
            visited_order.append(mi)
            for neighbor, _, _, _ in mol_bonds[mi]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        # Append disconnected molecules (safe for single-complex species)
        for mi in range(n):
            if mi not in visited:
                visited_order.append(mi)

        # Renumber bonds in BFS traversal order (left-to-right through the order list)
        bond_map: dict[int, int] = {}
        next_bond = [1]

        def _get_new_bond(old_bidx: int) -> str:
            if old_bidx <= 0:
                return "!+" if old_bidx == -1 else ""
            if old_bidx not in bond_map:
                bond_map[old_bidx] = next_bond[0]
                next_bond[0] += 1
            return f"!{bond_map[old_bidx]}"

        # Pass 1: assign new bond indices by scanning each molecule's sites
        # in original (parsed) order — this gives a stable numbering independent
        # of which molecule was encoded first in the source string.
        for mi in visited_order:
            _, psites = parsed[mi]
            for _, bidx in psites:
                if bidx is not None and bidx > 0 and bidx not in bond_map:
                    bond_map[bidx] = next_bond[0]
                    next_bond[0] += 1

        # Pass 2: serialize with sites sorted by (name, new_bond_idx or +inf if free)
        mol_strs = []
        for mi in visited_order:
            name, psites = parsed[mi]

            def _site_sort_key(item: tuple[str, int | None]) -> tuple:
                sn, bidx = item
                if bidx is None:
                    return (sn, False, float("inf"))
                elif bidx <= 0:
                    return (sn, True, float("inf"))
                else:
                    return (sn, True, bond_map[bidx])

            sorted_psites = sorted(psites, key=_site_sort_key)
            site_strs = []
            for sn, bidx in sorted_psites:
                if bidx is None:
                    site_strs.append(sn)
                elif bidx <= 0:
                    site_strs.append(sn + "!+")
                else:
                    site_strs.append(sn + f"!{bond_map[bidx]}")
            mol_strs.append(name + "(" + ",".join(site_strs) + ")")
        return ".".join(mol_strs)

    # Try BFS from every molecule as root; pick the lex-min serialization
    best: str | None = None
    for root in range(n):
        candidate = _serialize_from_root(root)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    return best


def parse_net(path: str | Path, *, rate_mode: str = "value") -> Network | None:
    """Parse a BNG .net file into a comparison-ready Network.

    Species block:     <idx> <species_string> <conc> [labels]
    Reaction block:    <idx> <r1,r2,...> <p1,p2,...> <rate> [annotations]
    Parameters block:  <idx> <name> <expression>   (or <name> <expression>)

    rate_mode (default "value") controls how the reaction rate field is keyed;
    see _resolve_rate. "value" makes auto-generated rate-parameter NAMES
    irrelevant while still comparing rate VALUES/expressions.
    """
    path = Path(path)
    if not path.exists():
        return None

    species: dict[int, str] = {}
    initial_amounts: dict[int, str] = {}
    raw_reactions: list[tuple[list[int], list[int], str]] = []
    rate_defs: dict[str, str] = {}
    rate_functions: set[str] = set()
    groups: dict[int, tuple[str, dict[int, float]]] = {}
    section = None
    has_species_block = False
    has_reactions_block = False

    for line in path.read_text().splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("begin "):
            section = stripped[len("begin ") :].strip()
            has_species_block |= section == "species"
            has_reactions_block |= section == "reactions"
            continue
        if stripped.startswith("end "):
            section = None
            continue

        if section == "species":
            parts = _norm(stripped).split(" ")
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[0])
            except ValueError:
                continue
            # Keep the source serialization.  Canonical strings are useful for
            # display, but they cannot represent graph identity: bond numbers,
            # site order, and (critically) site states are independent fields.
            species[idx] = parts[1]
            if len(parts) >= 3:
                initial_amounts[idx] = " ".join(parts[2:])

        elif section == "reactions":
            parts = _norm(stripped).split(" ")
            if len(parts) < 4:
                continue
            try:
                reactants = [int(x) for x in parts[1].split(",") if x and x != "0"]
                products = [int(x) for x in parts[2].split(",") if x and x != "0"]
            except ValueError:
                continue
            rate = " ".join(parts[3:])
            raw_reactions.append((reactants, products, rate))

        elif section in ("parameters", "functions"):
            parts = _norm(stripped).split(" ")
            # Forms seen across BNG2/BNG3: "<idx> <name> <expr...>" or
            # "<name> <expr...>" or "<name>=<expr>".
            if "=" in stripped and len(parts) >= 1 and "=" in parts[0]:
                name, _, expr = stripped.partition("=")
                key = _rate_definition_key(name)
                rate_defs[key] = _norm(expr)
                if section == "functions" and name.strip().endswith("()"):
                    rate_functions.add(key)
                continue
            if len(parts) >= 3 and parts[0].isdigit():
                name = parts[1]
                expression = " ".join(parts[2:])
            elif len(parts) >= 2:
                name = parts[0]
                expression = " ".join(parts[1:])
            else:
                continue
            key = _rate_definition_key(name)
            rate_defs[key] = expression
            if section == "functions" and name.strip().endswith("()"):
                rate_functions.add(key)

        elif section == "groups":
            parts = _norm(stripped).split(" ", 2)
            if len(parts) < 3:
                continue
            try:
                int(parts[0])
            except ValueError:
                continue
            group_index = int(parts[0])
            name = parts[1]
            entries: dict[int, float] = {}
            for item in parts[2].split(","):
                item = item.strip()
                if not item:
                    continue
                if "*" in item:
                    weight_text, index_text = item.split("*", 1)
                    try:
                        weight = float(weight_text)
                    except ValueError:
                        continue
                else:
                    weight = 1.0
                    index_text = item
                try:
                    index = int(index_text)
                except ValueError:
                    continue
                entries[index] = entries.get(index, 0.0) + weight
            groups[group_index] = (name, entries)

    if (
        not species
        and not raw_reactions
        and not (has_species_block and has_reactions_block)
    ):
        return None

    net = Network(
        species_by_index=species,
        reaction_multiset=Counter(),
        rate_defs=rate_defs,
        _raw=raw_reactions,
        rate_mode=rate_mode,
        groups=groups,
        rate_functions=rate_functions,
        rate_observables={name for name, _entries in groups.values()},
        initial_amounts=initial_amounts,
    )
    _rekey(net, rate_mode)
    return net


def _rekey(net: Network, rate_mode: str) -> None:
    """(Re)build reaction_multiset from net._raw under the given rate_mode."""
    multiset: Counter = Counter()
    for reactants, products, rate in net._raw:
        try:
            r_strs = tuple(sorted(net.species_by_index[i] for i in reactants))
            p_strs = tuple(sorted(net.species_by_index[i] for i in products))
        except KeyError:
            r_strs = tuple(f"?{i}" for i in sorted(reactants))
            p_strs = tuple(f"?{i}" for i in sorted(products))
        rate_key = _resolve_rate(
            rate,
            net.rate_defs,
            rate_mode,
            net.rate_functions,
            net.rate_observables,
        )
        multiset[(r_strs, p_strs, rate_key)] += 1
    net.reaction_multiset = multiset


@dataclass
class NetDiff:
    ok: bool
    n_species_ref: int
    n_species_test: int
    n_reactions_ref: int
    n_reactions_test: int
    species_only_ref: set[str]
    species_only_test: set[str]
    reactions_only_ref: list
    reactions_only_test: list
    groups_only_ref: set[int] = field(default_factory=set)
    groups_only_test: set[int] = field(default_factory=set)
    groups_changed: set[int] = field(default_factory=set)
    groups_renamed: set[int] = field(default_factory=set)
    initial_amounts_changed: set[str] = field(default_factory=set)

    def summary(self) -> str:
        lines = [
            f"species:   ref={self.n_species_ref} test={self.n_species_test}",
            f"reactions: ref={self.n_reactions_ref} test={self.n_reactions_test} "
            f"(delta={self.n_reactions_test - self.n_reactions_ref:+d})",
        ]
        if self.species_only_ref:
            lines.append(
                f"  species only in ref ({len(self.species_only_ref)}): "
                + ", ".join(sorted(self.species_only_ref)[:5])
            )
        if self.species_only_test:
            lines.append(
                f"  species only in test ({len(self.species_only_test)}): "
                + ", ".join(sorted(self.species_only_test)[:5])
            )
        if self.reactions_only_test:
            lines.append(
                f"  reactions only in test ({len(self.reactions_only_test)}) "
                "— candidates for the over-count / failed merge:"
            )
            for r, p, rate in self.reactions_only_test[:5]:
                lines.append(f"    {' + '.join(r)} -> {' + '.join(p)}  [{rate}]")
        if self.reactions_only_ref:
            lines.append(f"  reactions only in ref ({len(self.reactions_only_ref)}):")
            for r, p, rate in self.reactions_only_ref[:5]:
                lines.append(f"    {' + '.join(r)} -> {' + '.join(p)}  [{rate}]")
        if self.groups_only_ref:
            lines.append(
                f"  observable groups only in ref ({len(self.groups_only_ref)}): "
                + ", ".join(str(i) for i in sorted(self.groups_only_ref)[:5])
            )
        if self.groups_only_test:
            lines.append(
                f"  observable groups only in test ({len(self.groups_only_test)}): "
                + ", ".join(str(i) for i in sorted(self.groups_only_test)[:5])
            )
        if self.groups_changed:
            lines.append(
                f"  observable groups changed ({len(self.groups_changed)}): "
                + ", ".join(str(i) for i in sorted(self.groups_changed)[:5])
            )
        if self.groups_renamed:
            lines.append(
                f"  observable group labels differ ({len(self.groups_renamed)}): "
                + ", ".join(str(i) for i in sorted(self.groups_renamed)[:5])
            )
        if self.initial_amounts_changed:
            lines.append(
                "  initial species amounts changed: "
                + ", ".join(sorted(self.initial_amounts_changed)[:5])
            )
        return "\n".join(lines)


def set_rate_mode(net: Network, rate_mode: str) -> Network:
    """Re-key an already-parsed Network under a different rate_mode, in place."""
    net.rate_mode = rate_mode
    _rekey(net, rate_mode)
    return net


def _species_prefilter_key(
    value: str,
    molecule_name_aliases: tuple[tuple[str, str], ...],
    apply_aliases: bool,
) -> tuple:
    """Necessary-condition key for :func:`species_isomorphic` on ``value``.

    ``species_isomorphic`` can only return True when both graphs share the
    ``(compartment, annotations)`` header and, after applying molecule-name
    aliases to the reference side, the multiset of vertex labels paired with
    vertex degrees (both are checked explicitly there, via the header equality
    and the ``Counter((label, degree, color))`` equality).  When parsing fails
    it falls back to normalized-string equality; because parsing is a function
    of the normalized string, a parseable and an unparsable species can only
    match when their normalized strings are equal — which makes both sides
    unparsable.  The key therefore encodes exactly those necessary conditions:
    two species with different keys are a pair ``species_isomorphic`` rejects.
    """
    graph = _parse_species_graph(value)
    if graph is None:
        return ("raw", _norm(value))
    labels = graph.labels
    if apply_aliases and molecule_name_aliases:
        alias_map = dict(molecule_name_aliases)
        labels = [
            (
                (label[0], alias_map[label[1]], *label[2:])
                if label[0] == "molecule" and label[1] in alias_map
                else label
            )
            for label in labels
        ]
    multiset = Counter(
        (label, len(degree)) for label, degree in zip(labels, graph.adjacency)
    )
    return ("graph", graph.header, tuple(sorted(multiset.items())))


def _species_index_mapping(
    ref: Network,
    test: Network,
    molecule_name_aliases: tuple[tuple[str, str], ...] = (),
    *,
    match_amounts: bool = False,
) -> dict[int, int]:
    """Find a one-to-one structural mapping from reference to test species."""

    reference_indices = list(ref.species_by_index)
    test_indices = list(test.species_by_index)

    # Bucket test species by the prefilter key so species that cannot be
    # isomorphic never reach species_isomorphic.  Bucket lists append in
    # test_indices order, and the comprehension below keeps that order, so
    # every candidates list — and therefore the Kuhn matching result — is
    # identical to the unbucketed computation.
    test_buckets: dict[tuple, list[int]] = {}
    for test_index in test_indices:
        test_buckets.setdefault(
            _species_prefilter_key(test.species_by_index[test_index], (), False), []
        ).append(test_index)
    candidates = {
        ref_index: [
            test_index
            for test_index in test_buckets.get(
                _species_prefilter_key(
                    ref.species_by_index[ref_index],
                    molecule_name_aliases,
                    True,
                ),
                (),
            )
            if species_isomorphic(
                ref.species_by_index[ref_index],
                test.species_by_index[test_index],
                molecule_name_aliases,
            )
            and (
                not match_amounts
                or _resolve_rate(
                    ref.initial_amounts.get(ref_index, ""),
                    ref.rate_defs,
                    "value",
                    ref.rate_functions,
                    ref.rate_observables,
                )
                == _resolve_rate(
                    test.initial_amounts.get(test_index, ""),
                    test.rate_defs,
                    "value",
                    test.rate_functions,
                    test.rate_observables,
                )
            )
        ]
        for ref_index in reference_indices
    }
    matched_test: dict[int, int] = {}

    # Kuhn matching handles duplicate/isomorphic species entries without
    # depending on their serialized indices or input order.
    def augment(ref_index: int, visited: set[int]) -> bool:
        for test_index in candidates[ref_index]:
            if test_index in visited:
                continue
            visited.add(test_index)
            previous = matched_test.get(test_index)
            if previous is None or augment(previous, visited):
                matched_test[test_index] = ref_index
                return True
        return False

    for ref_index in sorted(reference_indices, key=lambda i: len(candidates[i])):
        augment(ref_index, set())
    return {ref_index: test_index for test_index, ref_index in matched_test.items()}


def _reaction_view(
    net: Network,
    species_identity: dict[int, tuple[str, int]],
    *,
    compare_rates: bool,
) -> tuple[Counter, dict[tuple, tuple[tuple[str, ...], tuple[str, ...], str]]]:
    """Build a reaction multiset keyed by structural species identities."""

    counter: Counter = Counter()
    payload: dict[tuple, tuple[tuple[str, ...], tuple[str, ...], str]] = {}
    for reactants, products, rate in net._raw:
        reactant_ids = tuple(
            sorted(
                species_identity.get(index, ("missing", index)) for index in reactants
            )
        )
        product_ids = tuple(
            sorted(
                species_identity.get(index, ("missing", index)) for index in products
            )
        )
        rate_key = (
            _resolve_rate(
                rate,
                net.rate_defs,
                net.rate_mode,
                net.rate_functions,
                net.rate_observables,
            )
            if compare_rates
            else ""
        )
        key = (
            (reactant_ids, product_ids, rate_key)
            if compare_rates
            else (reactant_ids, product_ids)
        )
        counter[key] += 1
        try:
            reactant_names = tuple(
                sorted(net.species_by_index[index] for index in reactants)
            )
            product_names = tuple(
                sorted(net.species_by_index[index] for index in products)
            )
        except KeyError:
            reactant_names = tuple(sorted(f"?{index}" for index in reactants))
            product_names = tuple(sorted(f"?{index}" for index in products))
        payload[key] = (reactant_names, product_names, rate_key)
    return counter, payload


def _group_view(
    net: Network, species_identity: dict[int, tuple[str, int]]
) -> dict[int, tuple[str, tuple[tuple[tuple[str, int], float], ...]]]:
    """Map indexed observable groups from species indices to identities."""

    view = {}
    for group_index, (name, entries) in net.groups.items():
        mapped: dict[tuple[str, int], float] = {}
        for index, weight in entries.items():
            identity = species_identity.get(index, ("missing", index))
            mapped[identity] = mapped.get(identity, 0.0) + weight
        view[group_index] = (name, tuple(sorted(mapped.items(), key=repr)))
    return view


def compare_net(
    ref: Network,
    test: Network,
    *,
    compare_rates: bool = True,
    compare_initial_amounts: bool = False,
    molecule_name_aliases: dict[str, str] | None = None,
) -> NetDiff:
    """Compare networks by graph identity and reaction multiset.

    Molecule/site order and explicit bond numbers are serialization details.
    Molecule names remain significant unless an explicit source-specific alias
    maps a reference name to its generated name. Site states, compartments,
    explicit connectivity, stoichiometry, multiplicity, and (when enabled) rate
    values always remain significant.
    """
    aliases = molecule_name_aliases or {}
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("molecule name aliases must map to unique generated names")
    alias_items = tuple(sorted(aliases.items()))
    mapping = _species_index_mapping(ref, test, alias_items)
    if compare_initial_amounts:
        amount_mapping = _species_index_mapping(
            ref, test, alias_items, match_amounts=True
        )
        if len(amount_mapping) == len(mapping):
            mapping = amount_mapping
    matched_test = set(mapping.values())
    ref_identity = {
        index: ("species", mapping[index]) if index in mapping else ("ref", index)
        for index in ref.species_by_index
    }
    test_identity = {
        index: ("species", index) if index in matched_test else ("test", index)
        for index in test.species_by_index
    }
    rxn_ref, payload_ref = _reaction_view(
        ref, ref_identity, compare_rates=compare_rates
    )
    rxn_test, payload_test = _reaction_view(
        test, test_identity, compare_rates=compare_rates
    )
    groups_ref = _group_view(ref, ref_identity)
    groups_test = _group_view(test, test_identity)
    amounts_changed = set()
    if compare_initial_amounts:
        for left, right in mapping.items():
            a = ref.initial_amounts.get(left)
            b = test.initial_amounts.get(right)
            if (
                a is None
                or b is None
                or _resolve_rate(
                    a,
                    ref.rate_defs,
                    "value",
                    ref.rate_functions,
                    ref.rate_observables,
                )
                != _resolve_rate(
                    b,
                    test.rate_defs,
                    "value",
                    test.rate_functions,
                    test.rate_observables,
                )
            ):
                amounts_changed.add(ref.species_by_index[left])
    only_ref = rxn_ref - rxn_test
    only_test = rxn_test - rxn_ref
    groups_only_ref = set(groups_ref) - set(groups_test)
    groups_only_test = set(groups_test) - set(groups_ref)
    groups_changed = {
        index
        for index in set(groups_ref) & set(groups_test)
        if groups_ref[index][1] != groups_test[index][1]
    }
    groups_renamed = {
        index
        for index in set(groups_ref) & set(groups_test)
        if groups_ref[index][0] != groups_test[index][0]
    }

    def _explode(counter, payload):
        out = []
        for key, n in counter.items():
            r, p, rate = payload[key]
            out.extend([(list(r), list(p), rate)] * n)
        return out

    matched_ref = set(mapping)
    species_only_ref = {
        ref.species_by_index[index]
        for index in ref.species_by_index
        if index not in matched_ref
    }
    species_only_test = {
        test.species_by_index[index]
        for index in test.species_by_index
        if index not in matched_test
    }
    ok = (
        len(mapping) == len(ref.species_by_index) == len(test.species_by_index)
        and not only_ref
        and not only_test
        and not groups_only_ref
        and not groups_only_test
        and not groups_changed
        and not amounts_changed
    )
    return NetDiff(
        ok=ok,
        n_species_ref=ref.n_species,
        n_species_test=test.n_species,
        n_reactions_ref=sum(rxn_ref.values()),
        n_reactions_test=sum(rxn_test.values()),
        species_only_ref=species_only_ref,
        species_only_test=species_only_test,
        reactions_only_ref=_explode(only_ref, payload_ref),
        reactions_only_test=_explode(only_test, payload_test),
        groups_only_ref=groups_only_ref,
        groups_only_test=groups_only_test,
        groups_changed=groups_changed,
        groups_renamed=groups_renamed,
        initial_amounts_changed=amounts_changed,
    )


# --------------------------------------------------------------------------- #
# .gdat / trajectory parsing
# --------------------------------------------------------------------------- #


def parse_gdat(path: str | Path) -> tuple[np.ndarray, list[str]] | tuple[None, None]:
    """Parse a .gdat/.cdat file into (data, columns). First column is time."""
    path = Path(path)
    if not path.exists():
        return None, None
    lines = path.read_text().splitlines()
    if not lines:
        return None, None
    header = lines[0].strip().lstrip("#").strip()
    columns = header.split()
    rows = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([float(x) for x in line.split()])
    if not rows:
        return None, None
    return np.asarray(rows, dtype=float), columns


@dataclass
class TrajDiff:
    ok: bool
    max_rel_err: float
    max_rel_col: str
    l2_rel_err: float
    note: str = ""

    def summary(self) -> str:
        s = (
            f"max rel err = {self.max_rel_err:.3e} at '{self.max_rel_col}', "
            f"L2 rel err = {self.l2_rel_err:.3e}"
        )
        return s if not self.note else f"{s} ({self.note})"


COLUMNS_INTERSECT = "intersect"
COLUMNS_EXACT = "exact"
COLUMN_MODES = (COLUMNS_INTERSECT, COLUMNS_EXACT)


def _observable_columns(columns: list[str]) -> list[str]:
    return [column for column in columns if column.lower() != "time"]


def _duplicate_columns(columns: list[str]) -> list[str]:
    return sorted(column for column, count in Counter(columns).items() if count > 1)


def _column_mismatch_note(ref_cols: list[str], test_cols: list[str], mode: str) -> str:
    if mode not in COLUMN_MODES:
        raise ValueError(
            f"unknown column mode {mode!r}; expected one of {list(COLUMN_MODES)}"
        )

    for side, columns in (("ref", ref_cols), ("test", test_cols)):
        duplicates = _duplicate_columns(columns)
        if duplicates:
            return f"duplicate column names in {side}: {duplicates}"

    if mode == COLUMNS_EXACT:
        ref_observables = _observable_columns(ref_cols)
        test_observables = _observable_columns(test_cols)
        only_ref = [
            column for column in ref_observables if column not in test_observables
        ]
        only_test = [
            column for column in test_observables if column not in ref_observables
        ]
        if only_ref or only_test:
            return (
                f"observable column sets differ: only in ref {only_ref}, "
                f"only in test {only_test}"
            )
    return ""


def compare_trajectories(
    ref: np.ndarray,
    ref_cols: list[str],
    test: np.ndarray,
    test_cols: list[str],
    *,
    rtol: float = 1e-6,
    atol: float = 1e-12,
    columns: str = COLUMNS_INTERSECT,
) -> TrajDiff:
    """Compare two trajectories on their shared or exactly matching columns.

    Aligns on the common time grid (intersection of time points, exact match).
    Relative error uses max(|ref|, atol) in the denominator so near-zero
    observables don't blow up the metric. ``intersect`` compares only shared
    observable names; ``exact`` first requires equal observable-name sets.
    Column order is not significant because values are aligned by name. Both
    modes reject duplicate column names because those values cannot be aligned
    unambiguously.
    """
    for side, data, names in (("ref", ref, ref_cols), ("test", test, test_cols)):
        if data.ndim != 2 or data.shape[1] != len(names):
            return TrajDiff(
                False, np.inf, "", np.inf, f"invalid trajectory shape in {side}"
            )
        if not np.all(np.isfinite(data)):
            return TrajDiff(
                False, np.inf, "", np.inf, f"non-finite trajectory in {side}"
            )
    note = _column_mismatch_note(ref_cols, test_cols, columns)
    if note:
        return TrajDiff(False, np.inf, "", np.inf, note)

    ref_observables = _observable_columns(ref_cols)
    test_observables = _observable_columns(test_cols)
    if columns == COLUMNS_EXACT:
        common = ref_observables
    else:
        common = [c for c in ref_observables if c in test_observables]
    if not common:
        return TrajDiff(False, np.inf, "", np.inf, "no shared observable columns")

    rt = ref[:, ref_cols.index("time")] if "time" in ref_cols else ref[:, 0]
    tt = test[:, test_cols.index("time")] if "time" in test_cols else test[:, 0]

    # Align on shared time points (tolerant match).
    ridx, tidx = _align_times(rt, tt)
    if len(ridx) < 2:
        return TrajDiff(
            False,
            np.inf,
            "",
            np.inf,
            f"insufficient shared time points (ref={len(rt)}, test={len(tt)})",
        )

    worst = 0.0
    worst_col = ""
    sq_sum = 0.0
    n = 0
    for c in common:
        rv = ref[ridx, ref_cols.index(c)]
        tv = test[tidx, test_cols.index(c)]
        denom = np.maximum(np.abs(rv), atol)
        abs_diff = np.abs(tv - rv)
        rel = np.zeros_like(abs_diff, dtype=float)
        np.divide(abs_diff, denom, out=rel, where=denom != 0)
        rel[(denom == 0) & (abs_diff != 0)] = np.inf
        cmax = float(np.max(rel))
        if cmax > worst:
            worst, worst_col = cmax, c
        sq_sum += float(np.sum(rel**2))
        n += rel.size

    l2 = float(np.sqrt(sq_sum / max(n, 1)))
    ok = worst <= rtol
    return TrajDiff(ok=ok, max_rel_err=worst, max_rel_col=worst_col, l2_rel_err=l2)


def _align_times(a: np.ndarray, b: np.ndarray, tol: float = 1e-9):
    """Return index arrays into a and b for time points present in both."""
    ai, bi = [], []
    j = 0
    for i, ta in enumerate(a):
        while j < len(b) and b[j] < ta - tol:
            j += 1
        if j < len(b) and abs(b[j] - ta) <= tol + tol * abs(ta):
            ai.append(i)
            bi.append(j)
            j += 1
    return np.asarray(ai, dtype=int), np.asarray(bi, dtype=int)


# --------------------------------------------------------------------------- #
# Stochastic ensemble comparison (SSA / PLA / PSA / NF)
# --------------------------------------------------------------------------- #


@dataclass
class EnsembleDiff:
    ok: bool
    n_violations: int
    n_points_checked: int
    worst_z: float
    worst_col: str
    note: str = ""

    def summary(self) -> str:
        summary = (
            f"ensemble: {self.n_violations}/{self.n_points_checked} points outside "
            f"mean +/- 3 pooled SE; worst |z|={self.worst_z:.2f} at '{self.worst_col}'"
        )
        return summary if not self.note else f"{summary} ({self.note})"


def compare_stochastic(
    ref_runs: list[tuple[np.ndarray, list[str]]],
    test_runs: list[tuple[np.ndarray, list[str]]],
    *,
    n_sigma: float = 3.0,
    max_violation_frac: float = 0.02,
    min_ref_runs: int = 2,
    min_test_runs: int = 2,
    columns: str = COLUMNS_INTERSECT,
) -> EnsembleDiff:
    """Distributional comparison of two stochastic ensembles.

    For each selected observable at each shared time point, compare the two
    independent ensemble means using the pooled standard error
    sqrt(SE(ref)^2 + SE(test)^2). Pass if the fraction of violating points is
    <= max_violation_frac (allows for the few tail points expected at 3 sigma
    over many checks). ``intersect`` compares shared observable names;
    ``exact`` requires equal observable-name sets. Duplicate names always fail.
    """
    if columns not in COLUMN_MODES:
        raise ValueError(
            f"unknown column mode {columns!r}; expected one of {list(COLUMN_MODES)}"
        )

    if len(ref_runs) < min_ref_runs or len(test_runs) < min_test_runs:
        return EnsembleDiff(
            False,
            0,
            0,
            np.inf,
            "",
            note=(
                f"insufficient ensemble members (ref={len(ref_runs)}, "
                f"test={len(test_runs)}, required={min_ref_runs}/{min_test_runs})"
            ),
        )

    for side, runs in (("ref", ref_runs), ("test", test_runs)):
        for index, (data, run_cols) in enumerate(runs):
            if data.ndim != 2 or data.shape[1] != len(run_cols):
                return EnsembleDiff(
                    False,
                    0,
                    0,
                    np.inf,
                    "",
                    note=f"invalid trajectory shape in {side} ensemble run {index + 1}",
                )
            if not np.all(np.isfinite(data)):
                return EnsembleDiff(
                    False,
                    0,
                    0,
                    np.inf,
                    "",
                    note=f"non-finite trajectory in {side} ensemble run {index + 1}",
                )
            duplicates = _duplicate_columns(run_cols)
            if duplicates:
                return EnsembleDiff(
                    False,
                    0,
                    0,
                    np.inf,
                    "",
                    note=(
                        f"duplicate column names in {side} ensemble run "
                        f"{index + 1}: {duplicates}"
                    ),
                )

    rmean, rse, rcols, rt = _ensemble_stats(ref_runs)
    tmean, tse, tcols, tt = _ensemble_stats(test_runs)
    if rmean is None or tmean is None:
        return EnsembleDiff(False, 0, 0, np.inf, "", note="empty ensemble")

    note = _column_mismatch_note(rcols, tcols, columns)
    if note:
        return EnsembleDiff(False, 0, 0, np.inf, "", note=note)

    ref_observables = _observable_columns(rcols)
    test_observables = _observable_columns(tcols)
    if columns == COLUMNS_EXACT:
        common = ref_observables
    else:
        common = [c for c in ref_observables if c in test_observables]
    ridx, tidx = _align_times(rt, tt)
    if not common or len(ridx) < 2:
        return EnsembleDiff(False, 0, 0, np.inf, "", note="no shared trajectory")

    violations = 0
    checked = 0
    worst_z = 0.0
    worst_col = ""
    for c in common:
        rm = rmean[ridx, rcols.index(c)]
        rs = rse[ridx, rcols.index(c)]
        ts = tse[tidx, tcols.index(c)]
        # The ensembles are independent samples.  Using only the reference
        # SE makes a zero-variance rare observable fail whenever the test
        # ensemble contains one or two events, even when the two distributions
        # are compatible.  Pool both mean uncertainties instead.
        tm = tmean[tidx, tcols.index(c)]
        se = np.maximum(np.hypot(rs, ts), 1e-12)
        z = np.abs(tm - rm) / se
        cz = float(np.max(z))
        if cz > worst_z:
            worst_z, worst_col = cz, c
        violations += int(np.sum(z > n_sigma))
        checked += z.size

    frac = violations / max(checked, 1)
    return EnsembleDiff(
        ok=frac <= max_violation_frac,
        n_violations=violations,
        n_points_checked=checked,
        worst_z=worst_z,
        worst_col=worst_col,
    )


def _ensemble_stats(runs: list[tuple[np.ndarray, list[str]]]):
    if not runs:
        return None, None, None, None
    first_data, first_cols = runs[0]
    if first_data.ndim != 2 or first_data.shape[1] != len(first_cols):
        return None, None, None, None
    cols = list(first_cols)
    for data, run_cols in runs:
        if (
            data.ndim != 2
            or data.shape != first_data.shape
            or list(run_cols) != cols
            or not np.all(np.isfinite(data))
        ):
            return None, None, None, None
    time = first_data[:, cols.index("time")] if "time" in cols else first_data[:, 0]
    stack = np.stack([r[0] for r in runs], axis=0)  # (n_runs, n_t, n_col)
    mean = stack.mean(axis=0)
    se = (
        stack.std(axis=0, ddof=1) / np.sqrt(stack.shape[0])
        if stack.shape[0] > 1
        else np.zeros_like(mean)
    )
    return mean, se, cols, time


# --------------------------------------------------------------------------- #
# Export format checks
# --------------------------------------------------------------------------- #


def check_xml_wellformed(path: str | Path) -> tuple[bool, str]:
    import xml.etree.ElementTree as ET

    try:
        ET.parse(str(path))
        return True, "well-formed"
    except ET.ParseError as e:
        return False, f"XML parse error: {e}"


def check_sbml(path: str | Path) -> tuple[bool, str]:
    """Validate SBML with libsbml if available, else fall back to well-formed."""
    try:
        import libsbml  # type: ignore
    except ImportError:
        ok, msg = check_xml_wellformed(path)
        return ok, f"{msg} (libsbml absent; well-formedness only)"
    doc = libsbml.readSBML(str(path))
    n_err = doc.getNumErrors()
    serious = sum(
        1
        for i in range(n_err)
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    )
    if serious:
        return False, f"{serious} SBML error(s); first: {doc.getError(0).getMessage()}"
    return True, f"valid SBML ({n_err} non-fatal notices)"


def qualify_binomial_marginal(runs, column, *, population, probability, label):
    """Independent mean control for a known binomial marginal (six analytic SE).

    Use the analytic variance, not an empirical reference variance that could
    itself be biased. This qualifies an oracle before cross-engine comparison;
    it does not replace or alter the parity thresholds.
    """
    mean, _, columns, times = _ensemble_stats(runs)
    assert (
        mean is not None and len(runs) >= 2
    ), f"{label}: invalid analytic control ensemble"
    assert column in columns, f"{label}: missing analytic control observable {column}"
    values = np.array([data[:, names.index(column)] for data, names in runs])
    assert np.isfinite(values).all(), f"{label}: nonfinite analytic control samples"
    assert (
        (values >= 0) & (values <= population) & (values == np.floor(values))
    ).all(), f"{label}: invalid binomial marginal counts"
    p = np.asarray(probability(times))
    assert (
        p.shape == times.shape and np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
    )
    expected = population * p
    se = np.sqrt(population * p * (1 - p) / len(runs))
    residual = np.abs(values.mean(axis=0) - expected)
    bad = residual > 6 * se + 1e-12
    if np.any(bad):
        index = int(np.flatnonzero(bad)[0])
        raise AssertionError(
            f"{label}: {column} fails analytic binomial marginal qualification at "
            f"t={times[index]:g}: mean={values.mean(axis=0)[index]:g}, "
            f"expected={expected[index]:g}, analytic SE={se[index]:g}; "
            "reference seed schedule/oracle requires requalification"
        )
