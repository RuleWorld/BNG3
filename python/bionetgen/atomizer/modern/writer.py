"""BNGL writer for the Playground atomizer port."""

from __future__ import annotations

import ast
import json
import math
import os
import re
from urllib.parse import quote
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import (
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from .events import (
    EventTranslationContext,
    _event_assignment,
    fold_numeric,
    synthesize_event_actions,
)
from .rate_rule_constants import (
    ASSIGN_RULE_META_PREFIX,
    RATE_RULE_META_PREFIX,
    RATE_RULE_NEG_PREFIX,
    RATE_RULE_POS_PREFIX,
    SYNTH_RATE_RULE_SPECIES_PREFIX,
)
from .structures import Molecule, Species, read_from_string
from .helpers import logger
from .metadata import metadata_payload
from .types import (
    BNGL_LEXER_KEYWORDS,
    SBMLModel,
    SBMLKineticLaw,
    SBMLReaction,
    SBMLRule,
    SCTEntry,
    SeedSpeciesEntry,
    SpeciesCompositionTable,
    coerce_import_warning,
    get_kinetic_math,
    standardize_name,
)

_PROTECTED_BUILTIN_OPERANDS = frozenset({"time", "_pi", "_e", "true", "false"})
# SBML Level 3's built-in avogadro symbol has an exact SI-defined value.
_SBML_AVOGADRO = 6.02214076e23
_MULTI_SUM_TOKEN = re.compile(r"__SBML_MULTI_SUM__([A-Za-z_][A-Za-z0-9_]*)__")
_MULTI_NUMERIC_TOKEN = re.compile(r"__SBML_MULTI_NUMERIC__([A-Za-z_][A-Za-z0-9_]*)__")

# Function identifiers and formal arguments have a narrower reserved-word
# contract than general SBML/BNGL names.  Keep this aligned with the
# Playground writer: these names are legal SBML identifiers but collide with
# strict BNGL parser tokens when emitted in a functions block.
_BNGL_FUNCTION_IDENTIFIER_RESERVED = frozenset(
    {
        "function",
        "functions",
        "parameter",
        "param",
        "modifier",
        "mod",
        "substrate",
        "model",
        "begin",
        "end",
        "reaction",
        "reactions",
        "rule",
        "rules",
    }
)


def _sanitize_function_identifier(value: str) -> str:
    """Return the Playground-safe identifier used in a functions block."""

    standardized = standardize_name(value)
    if not standardized:
        return "unnamed"
    if standardized.lower() in _BNGL_FUNCTION_IDENTIFIER_RESERVED:
        return f"{standardized}_id"
    return standardized


_MISSING_KINETIC_RATE_FALLBACK = (
    os.environ.get("BNGL_MISSING_KINETIC_RATE", "1").strip() or "1"
)
try:
    _MISSING_KINETIC_LOG_LIMIT = int(
        os.environ.get("BNGL_MISSING_KINETIC_LOG_LIMIT", "25")
    )
except ValueError:
    _MISSING_KINETIC_LOG_LIMIT = 25
_missing_kinetic_log_count = 0

try:
    _TRANSPORT_LOG_LIMIT = int(os.environ.get("BNGL_TRANSPORT_LOG_LIMIT", "40"))
except ValueError:
    _TRANSPORT_LOG_LIMIT = 40
_transport_log_count = 0

_ENABLE_MASS_ACTION_CHECK = (
    os.environ.get("BNGL_ENABLE_MASS_ACTION_CHECK", "1").strip() != "0"
)
try:
    _MASS_ACTION_SKIP_MIN_REACTIONS = int(
        os.environ.get("BNGL_SKIP_MASS_ACTION_MIN_REACTIONS", "500")
    )
except ValueError:
    _MASS_ACTION_SKIP_MIN_REACTIONS = 500
try:
    _MASS_ACTION_SKIP_EXPR_LEN = int(
        os.environ.get("BNGL_SKIP_MASS_ACTION_EXPR_LEN", "2000")
    )
except ValueError:
    _MASS_ACTION_SKIP_EXPR_LEN = 2000


@dataclass
class BNGLGenerationResult:
    """Named result returned by the Playground BNGL generation facade."""

    bngl: str
    observable_map: Mapping[str, str]
    warnings: List[str] = field(default_factory=list)

    @property
    def observableMap(self) -> Mapping[str, str]:
        """Expose the TypeScript spelling without copying the map."""

        return self.observable_map

    def __iter__(self) -> Iterator[object]:
        """Keep the historical Python ``bngl, observable_map = ...`` contract."""

        yield self.bngl
        yield self.observable_map

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return self.bngl
        if index == 1:
            return self.observable_map
        raise IndexError(index)


@dataclass(frozen=True)
class ProcessedRate:
    """Result of the Playground writer's unified reaction-rate pipeline."""

    rate_string: str
    force_irreversible: bool = False
    is_split_rxn: bool = False
    is_total_rate: bool = False
    # A reversible SBML net law can lower to one complete flux in one
    # direction and one elementary law in the other.  BNGL's trailing
    # ``TotalRate`` modifier applies to the whole reversible rule, so retain
    # the directional classification for the writer's two-rule fallback.
    forward_is_total_rate: bool = False
    reverse_is_total_rate: bool = False

    @property
    def rateString(self) -> str:
        return self.rate_string

    @property
    def forceIrreversible(self) -> bool:
        return self.force_irreversible

    @property
    def isSplitRxn(self) -> bool:
        return self.is_split_rxn

    @property
    def isTotalRate(self) -> bool:
        return self.is_total_rate


def _log_missing_kinetic(message: str) -> None:
    global _missing_kinetic_log_count

    if (
        _MISSING_KINETIC_LOG_LIMIT < 0
        or _missing_kinetic_log_count < _MISSING_KINETIC_LOG_LIMIT
    ):
        logger.warning("BNW011", message)
    elif _missing_kinetic_log_count == _MISSING_KINETIC_LOG_LIMIT:
        logger.warning("BNW011", "Additional missing-kinetic-law logs suppressed.")
    _missing_kinetic_log_count += 1


def _log_transport_info(message: str) -> None:
    global _transport_log_count

    if _TRANSPORT_LOG_LIMIT < 0 or _transport_log_count < _TRANSPORT_LOG_LIMIT:
        logger.info("BNW004", message)
    elif _transport_log_count == _TRANSPORT_LOG_LIMIT:
        logger.info("BNW004", "Additional transport reaction logs suppressed.")
    _transport_log_count += 1


def _section(name: str, lines: Iterable[str]) -> str:
    content = list(lines)
    if not content:
        return ""
    return (
        "begin "
        + name
        + "\n"
        + "\n".join(f"  {line}" for line in content)
        + "\nend "
        + name
    )


def _print_reaction_species(
    chemical: Tuple[str, float, str],
    tag: str,
    translator: Mapping[str, Species],
) -> str:
    """Render one Playground ``bnglReaction`` species entry."""

    species, stoichiometry, _compartment = chemical
    if species not in translator:
        rendered = f"{species}{tag}"
    else:
        pattern = translator[species]
        pattern.add_compartment(tag)
        pattern.renumber_bonds()
        rendered = str(pattern)

    if float(stoichiometry).is_integer():
        return " + ".join(rendered for _ in range(int(stoichiometry)))

    logger.error("BNW002", f"Non-integer stoichiometry: {stoichiometry} * {species}")
    return rendered


def bngl_reaction(
    reactants: Sequence[Tuple[str, float, str]],
    products: Sequence[Tuple[str, float, str]],
    rate: str,
    tags: Mapping[str, str],
    translator: Optional[Mapping[str, Species]] = None,
    is_compartments: bool = False,
    reversible: bool = True,
    comment: str = "",
    reaction_name: Optional[str] = None,
) -> str:
    """Render one reaction using the Playground writer's public contract."""

    translator = translator or {}
    if not reactants or (len(reactants) == 1 and reactants[0][1] == 0):
        result = "0 "
    else:
        rendered = []
        for species, stoichiometry, compartment in reactants:
            tag = tags.get(compartment, "") if is_compartments else ""
            rendered.append(
                _print_reaction_species(
                    (species, stoichiometry, compartment), tag, translator
                )
            )
        result = " + ".join(rendered)

    result += " <-> " if reversible else " -> "

    if not products:
        result += "0 "
    else:
        rendered = []
        for species, stoichiometry, compartment in products:
            tag = tags.get(compartment, "") if is_compartments else ""
            rendered.append(
                _print_reaction_species(
                    (species, stoichiometry, compartment), tag, translator
                )
            )
        result += " + ".join(rendered)

    result += f" {rate}"
    if comment:
        result += f" {comment}"
    result = re.sub(r"(^|\s)0\(\)(?=\s|$)", r"\1 0", result)
    if reaction_name:
        result = f"{reaction_name}: {result}"
    return result


def _molecule_pattern(molecule: Molecule) -> str:
    value = molecule.to_string(True).replace("-", "_")
    if "(" not in value:
        value = value + "()"
    return value


def _pattern(species: Species, compartment: str = "") -> str:
    species.renumber_bonds()
    molecules = []
    for molecule in species.molecules:
        value = _molecule_pattern(molecule)
        if not value.startswith("M_"):
            value = re.sub(r"^([A-Za-z_][A-Za-z0-9_]*)", r"M_\1", value)
        if "@" not in value and compartment:
            value += "@" + standardize_name(compartment)
        molecules.append(value)
    return ".".join(sorted(molecules))


def _number(value: object) -> str:
    # Preserve arbitrary-precision integer literals instead of converting
    # large factorials through float and raising OverflowError.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _factorial(value: float) -> int:
    return math.factorial(int(value))


def _evaluate_arithmetic(expression: str) -> Optional[float]:
    """Evaluate a restricted numeric expression used for constant seed folding."""

    normalized = re.sub(r"\bif\s*\(", "if_(", expression)
    normalized = normalized.replace("&&", " and ").replace("||", " or ")
    normalized = normalized.replace("^", "**")
    try:
        tree = ast.parse(normalized, mode="eval")
    except (RecursionError, SyntaxError, ValueError):
        return None

    def evaluate(node: ast.AST) -> object:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            return left**right
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = iter(node.values)
            result = evaluate(next(values))
            for value_node in values:
                if isinstance(node.op, ast.And) and not result:
                    return result
                if isinstance(node.op, ast.Or) and result:
                    return result
                result = evaluate(value_node)
            return result
        if isinstance(node, ast.Compare):
            left = evaluate(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = evaluate(comparator)
                if isinstance(operator, ast.Eq):
                    matched = left == right
                elif isinstance(operator, ast.NotEq):
                    matched = left != right
                elif isinstance(operator, ast.Lt):
                    matched = left < right
                elif isinstance(operator, ast.LtE):
                    matched = left <= right
                elif isinstance(operator, ast.Gt):
                    matched = left > right
                elif isinstance(operator, ast.GtE):
                    matched = left >= right
                else:
                    raise ValueError("unsupported comparison")
                if not matched:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id != "if_" or len(node.args) != 3 or node.keywords:
                raise ValueError("unsupported function")
            condition = evaluate(node.args[0])
            return evaluate(node.args[1] if condition else node.args[2])
        raise ValueError("unsupported expression")

    try:
        value = evaluate(tree)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (ArithmeticError, OverflowError, RecursionError, TypeError, ValueError):
        return None


def _numeric_value(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _expression_identifiers(expression: str) -> List[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression or "")


def convert_math_expression(expression: str) -> str:
    """Convert common MathML/libSBML function spellings to BNGL syntax."""

    result = str(expression or "").strip()
    result = _replace_nested_function(
        result,
        "pow",
        lambda args: (
            f"(({args[0]})^({args[1]}))"
            if len(args) >= 2
            else f"pow({', '.join(args)})"
        ),
    )
    result = _replace_nested_function(
        result,
        "power",
        lambda args: (
            f"(({args[0]})^({args[1]}))"
            if len(args) >= 2
            else f"power({', '.join(args)})"
        ),
    )
    result = _replace_nested_function(
        result, "sqrt", lambda args: f"(({args[0]})^(1/2))" if args else "sqrt()"
    )
    result = _replace_nested_function(
        result, "sqr", lambda args: f"(({args[0]})^2)" if args else "sqr()"
    )
    result = _replace_nested_function(
        result,
        "exp",
        lambda args: f"(2.71828182845905^({args[0]}))" if args else "exp()",
    )
    result = _replace_nested_function(
        result,
        "abs",
        lambda args: f"if({args[0]}>=0,{args[0]},-({args[0]}))" if args else "abs()",
    )

    # SBML's reciprocal and inverse trigonometric names are not BNGL lexer
    # tokens, but they have direct one-expression equivalents.  Lower them
    # before the C++ parser sees the generated model.
    for function, replacement in {
        "sec": lambda args: f"(1/cos({args[0]}))" if args else "sec()",
        "csc": lambda args: f"(1/sin({args[0]}))" if args else "csc()",
        "cot": lambda args: f"(cos({args[0]})/sin({args[0]}))" if args else "cot()",
        "arcsec": lambda args: f"acos(1/({args[0]}))" if args else "arcsec()",
        "arccsc": lambda args: f"asin(1/({args[0]}))" if args else "arccsc()",
        "arccot": lambda args: f"atan(1/({args[0]}))" if args else "arccot()",
        "arcsinh": lambda args: f"asinh({args[0]})" if args else "arcsinh()",
        "arccosh": lambda args: f"acosh({args[0]})" if args else "arccosh()",
        "arctanh": lambda args: f"atanh({args[0]})" if args else "arctanh()",
        "arcsech": lambda args: f"acosh(1/({args[0]}))" if args else "arcsech()",
        "arccsch": lambda args: f"asinh(1/({args[0]}))" if args else "arccsch()",
    }.items():
        result = _replace_nested_function(result, function, replacement)

    # libSBML's MathML visitor may expose n-ary arithmetic as named calls
    # (multiply/add/divide/subtract) instead of infix operators.  BNGL's
    # expression parser accepts the latter, so lower these calls before the
    # remaining function rewrites.
    for function, operator in {
        "multiply": "*",
        "times": "*",
        "add": "+",
        "plus": "+",
        "divide": "/",
        "remainder": "%",
        "rem": "%",
    }.items():
        result = _replace_nested_function(
            result,
            function,
            lambda args, operator=operator, function=function: (
                f"({(' ' + operator + ' ').join(f'({arg})' for arg in args)})"
                if len(args) >= 2
                else (
                    args[0]
                    if len(args) == 1
                    else ("1" if function in {"multiply", "times", "divide"} else "0")
                )
            ),
        )
    for function in ("subtract", "minus"):
        result = _replace_nested_function(
            result,
            function,
            lambda args, function=function: (
                f"(-({args[0]}))"
                if len(args) == 1
                else (
                    f"({(' - ').join(f'({arg})' for arg in args)})"
                    if len(args) >= 2
                    else "0"
                )
            ),
        )

    # SBML log(base, value) is distinct from the one-argument natural log.
    result = _replace_nested_function(
        result,
        "log",
        lambda args: (
            f"(ln({args[1]})/ln({args[0]}))"
            if len(args) >= 2
            else f"ln({args[0]})"
            if args
            else "log()"
        ),
    )
    result = _replace_nested_function(
        result,
        "log10",
        lambda args: f"(ln({args[0]})/2.302585093)" if args else "log10()",
    )
    result = _replace_nested_function(
        result,
        "root",
        lambda args: (
            f"(({args[1]})^(1/({args[0]})))"
            if len(args) >= 2
            else f"(({args[0]})^(1/2))"
            if args
            else "root()"
        ),
    )
    result = _replace_nested_function(
        result,
        "floor",
        lambda args: f"floor({args[0]})" if args else "floor()",
    )
    result = _replace_nested_function(
        result,
        "ceiling",
        lambda args: f"ceil({args[0]})" if args else "ceiling()",
    )
    result = _replace_nested_function(
        result,
        "ceil",
        lambda args: f"ceil({args[0]})" if args else "ceil()",
    )
    for function, operator in {
        "gt": ">",
        "lt": "<",
        "geq": ">=",
        "leq": "<=",
        "eq": "==",
        "neq": "!=",
        "and": "&&",
        "or": "||",
    }.items():
        result = _replace_nested_function(
            result,
            function,
            lambda args, operator=operator, function=function: (
                f"({(' ' + operator + ' ').join(args)})"
                if len(args) >= 2
                else (
                    args[0] if len(args) == 1 else ("1" if function == "and" else "0")
                )
            ),
        )

    def logical_xor(args: List[str]) -> str:
        if len(args) == 1:
            return args[0]
        if not args:
            return "0"
        if len(args) < 2:
            return f"xor({', '.join(args)})"
        value = f"({args[0]})"
        for argument in args[1:]:
            other = f"({argument})"
            value = f"(({value} || {other}) && !({value} && {other}))"
        return value

    result = _replace_nested_function(result, "xor", logical_xor)
    result = _replace_nested_function(
        result,
        "not",
        lambda args: f"(!{args[0]})" if len(args) == 1 else f"not({', '.join(args)})",
    )
    result = _replace_nested_function(result, "piecewise", _piecewise_expression)
    result = _replace_nested_function(
        result,
        "Sat",
        lambda args: (
            f"(({args[0]}) * Sat({args[2]}, {args[1]}))"
            if len(args) == 3
            else f"Sat({', '.join(args)})"
        ),
    )
    result = _replace_nested_function(
        result,
        "MM",
        lambda args: (
            f"(({args[0]}) * MM({args[2]}, {args[1]}))"
            if len(args) == 3
            else f"MM({', '.join(args)})"
        ),
    )
    result = _replace_nested_function(
        result,
        "Hill",
        lambda args: (
            f"(({args[0]}) * ({args[2]})^({args[3]}) / (({args[1]})^({args[3]}) + ({args[2]})^({args[3]})))"
            if len(args) == 4
            else f"Hill({', '.join(args)})"
        ),
    )

    result = re.sub(r"\bpi\b", "3.14159265358979", result)
    # A few SBML formula exporters use upper-case function names.  BNGL's
    # expression lexer uses the canonical lower-case tokens.
    for function in ("min", "max"):
        result = re.sub(
            rf"\b{function}\s*\(", f"{function}(", result, flags=re.IGNORECASE
        )
    result = re.sub(
        r"\bexponentiale\b", "2.71828182845905", result, flags=re.IGNORECASE
    )
    result = re.sub(r"\btrue\b", "1", result, flags=re.IGNORECASE)
    result = re.sub(r"\bfalse\b", "0", result, flags=re.IGNORECASE)
    result = re.sub(r"\btime\b(?!\s*\()", "time()", result)
    # A zero-valued SBML expression can arrive from libSBML as ``0()`` after
    # function/assignment folding.  BNGL accepts the scalar literal ``0``;
    # ``0()`` is a syntax error and is never a meaningful call.
    result = re.sub(r"(?<![A-Za-z0-9_])0\s*\(\s*\)", "0", result)
    result = result.replace("--", "+")
    return result


def _split_arguments(inner: str) -> List[str]:
    arguments: List[str] = []
    current: List[str] = []
    depth = 0
    for char in inner:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            arguments.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    arguments.append("".join(current).strip())
    return arguments


def _replace_nested_function(expression: str, function: str, replacer) -> str:
    result = expression
    pattern = re.compile(rf"\b{re.escape(function)}\s*\(")
    search_index = 0
    guard = 0
    while guard < 10000:
        match = pattern.search(result, search_index)
        if match is None:
            break
        depth = 1
        close = match.end()
        while close < len(result) and depth:
            if result[close] == "(":
                depth += 1
            elif result[close] == ")":
                depth -= 1
            close += 1
        if depth:
            break
        inner = result[match.end() : close - 1]
        replacement = replacer(_split_arguments(inner))
        original = result[match.start() : close]
        if replacement == original:
            search_index = close
        else:
            result = result[: match.start()] + replacement + result[close:]
            search_index = match.start()
        guard += 1
    return result


def _piecewise_expression(args: List[str]) -> str:
    if len(args) == 1:
        return args[0]
    if len(args) == 2:
        return f"if({args[1]}, {args[0]}, 0)"
    otherwise = args[-1] if len(args) % 2 else "0"
    start = len(args) - 3 if len(args) % 2 else len(args) - 2
    result = otherwise
    for index in range(start, -1, -2):
        result = f"if({args[index + 1]}, {args[index]}, {result})"
    return result


def extend_function(
    function_string: str,
    parameter_dict: Mapping[str, object],
    function_definitions: Mapping[str, object],
) -> str:
    """Inline SBML function definitions and scalar parameters at call sites."""

    result = str(function_string or "")
    # Definitions may call definitions declared later in the SBML document
    # (for example fGK -> Gamma). Expand to a bounded fixed point so document
    # ordering does not leave unresolved user-function calls in BNGL.
    for _ in range(20):
        before_iteration = result
        for function_id, definition in function_definitions.items():
            name = getattr(definition, "name", "") or function_id
            arguments = list(getattr(definition, "arguments", []) or [])
            body = str(getattr(definition, "math", "") or "")

            def replace_call(
                args: List[str],
                arguments=arguments,
                body=body,
                call_name=name,
            ):
                if not arguments and len(args) == 1 and not args[0]:
                    return f"({body})"
                if len(args) == 1 and not args[0] and arguments:
                    return f"{call_name}()"
                if len(args) != len(arguments):
                    return f"{call_name}({', '.join(args)})"
                expanded = body
                for formal, actual in zip(arguments, args):
                    expanded = re.sub(
                        rf"\b{re.escape(formal)}\b", f"({actual})", expanded
                    )
                return f"({expanded})"

            function_names = [name]
            if function_id != name:
                function_names.append(function_id)
            for function_name in function_names:
                result = _replace_nested_function(
                    result,
                    function_name,
                    lambda args, call_name=function_name: replace_call(
                        args, call_name=call_name
                    ),
                )
        if result == before_iteration:
            break

    for parameter, value in parameter_dict.items():
        replacement = _number(value)
        # An SBML assignment rule can shadow a parameter with the same name;
        # preserve the zero-argument function call in that case.
        result = re.sub(rf"\b{re.escape(parameter)}\b(?!\s*\()", replacement, result)
    return result


def _definition_field(definition: object, field: str, default: object) -> object:
    value = getattr(definition, field, None)
    if value is None and isinstance(definition, Mapping):
        value = definition.get(field, default)
    return default if value is None else value


def _expand_function_call(
    expression: str, function_name: str, definition: object
) -> str:
    """Expand every call of one SBML function with parenthesis-aware parsing."""

    result = expression
    call_pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(")
    guard = 0
    while guard < 10000:
        match = call_pattern.search(result)
        if match is None:
            break
        depth = 1
        index = match.end()
        while depth and index < len(result):
            if result[index] == "(":
                depth += 1
            elif result[index] == ")":
                depth -= 1
            index += 1
        if depth:
            break

        actual_arguments = _split_arguments(result[match.end() : index - 1])
        body = str(_definition_field(definition, "math", "") or "")
        formal_arguments = list(_definition_field(definition, "arguments", []) or [])
        argument_map = {
            str(formal).strip(): actual_arguments[position].strip()
            for position, formal in enumerate(formal_arguments)
            if position < len(actual_arguments) and str(formal).strip()
        }
        names = sorted(argument_map, key=len, reverse=True)
        if names:
            formal_pattern = re.compile(
                rf"\b(?:{'|'.join(re.escape(name) for name in names)})\b"
            )
            body = formal_pattern.sub(
                lambda item: f"({argument_map[item.group(0)]})", body
            )
        result = result[: match.start()] + f"({body})" + result[index:]
        guard += 1
    return result


def inline_sbml_functions(
    rate_expression: str, function_definitions: Mapping[str, object]
) -> str:
    """Inline SBML function calls using the Playground's bounded expansion loop."""

    result = str(rate_expression or "")
    modified = True
    iterations = 0
    while modified and iterations < 20:
        modified = False
        iterations += 1
        for function_id, definition in function_definitions.items():
            function_name = str(function_id)
            if not re.search(rf"\b{re.escape(function_name)}\s*\(", result):
                continue
            expanded = _expand_function_call(result, function_name, definition)
            if expanded != result:
                result = expanded
                modified = True
                break
    return result


def bngl_function(
    rule: str,
    function_title: str = "",
    reactants: Optional[Sequence[str]] = None,
    compartments: Optional[Sequence[str]] = None,
    parameter_dict: Optional[Mapping[str, object]] = None,
    reaction_dict: Optional[Mapping[str, str]] = None,
    assignment_rule_variables: Optional[Set[str]] = None,
    observable_ids: Optional[Set[str]] = None,
    species_to_has_only_substance_units: Optional[Mapping[str, bool]] = None,
    observable_converted_rules: Optional[Set[str]] = None,
    species_with_conc_functions: Optional[Set[str]] = None,
    sbml_to_bngl_id: Optional[Mapping[str, str]] = None,
    rate_rule_variables: Optional[Set[str]] = None,
) -> str:
    """Translate a rate/function expression using the Playground contract."""

    del function_title, observable_ids, species_to_has_only_substance_units
    result = str(rule or "")
    reactants = list(reactants or [])
    compartments = list(compartments or [])
    reaction_dict = reaction_dict or {}
    assignment_rule_variables = assignment_rule_variables or set()
    observable_converted_rules = observable_converted_rules or set()
    species_with_conc_functions = species_with_conc_functions or set()
    sbml_to_bngl_id = sbml_to_bngl_id or {}
    rate_rule_variables = rate_rule_variables or set()
    assignment_aliases = {
        alias
        for variable in assignment_rule_variables
        for alias in (str(variable), standardize_name(str(variable)))
    }
    rate_rule_aliases = {
        alias
        for variable in rate_rule_variables
        for alias in (str(variable), standardize_name(str(variable)))
    }
    is_saturation = bool(re.search(r"\b(?:Sat|MM|Hill)\s*\(", result))

    def map_token(match: re.Match) -> str:
        token = match.group(1)
        end = match.end()
        if re.match(r"\s*\(", result[end:]):
            return token
        # Assignment-rule targets that are also SBML species must resolve as
        # zero-argument BNGL functions, not as the amount observable that the
        # ordinary species namespace would select.  Rate-rule targets remain
        # amount-valued states and keep the historical mapping below.
        token_aliases = {token, standardize_name(token)}
        if token_aliases & assignment_aliases and not token_aliases & rate_rule_aliases:
            return token
        mapped = sbml_to_bngl_id.get(token)
        if mapped is not None:
            observed_name = standardize_name(token)
            if is_saturation and observed_name in species_with_conc_functions:
                return observed_name + "_amt"
            if observed_name in species_with_conc_functions:
                return "_c_" + observed_name + "()"
            return observed_name + "_amt"
        if token in BNGL_LEXER_KEYWORDS and token not in _PROTECTED_BUILTIN_OPERANDS:
            return standardize_name(token)
        return token

    result = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", map_token, result)
    result = convert_math_expression(result)

    for compartment in compartments:
        result = re.sub(
            rf"\b{re.escape(compartment)}\b",
            f"__compartment_{standardize_name(compartment)}__",
            result,
        )
    for reaction_id, reaction_name in reaction_dict.items():
        result = re.sub(
            rf"\b{re.escape(reaction_id)}\b", f"netflux_{reaction_name}", result
        )
    for variable in assignment_rule_variables:
        standard = standardize_name(variable)
        if (
            variable in observable_converted_rules
            or standard in observable_converted_rules
        ):
            replacement = standard
        elif variable in rate_rule_variables or standard in rate_rule_variables:
            # Rate-rule targets materialized as synthetic state species are
            # read through their amount observable, not as undefined calls.
            replacement = standard + "_amt"
        elif standard in species_with_conc_functions:
            replacement = "_c_" + standard + "()"
        else:
            replacement = standard + "()"
        if variable in rate_rule_variables or standard in rate_rule_variables:
            result = re.sub(
                rf"\b{re.escape(variable)}\b\s*\(\s*\)", replacement, result
            )
            result = re.sub(rf"\b{re.escape(variable)}\b(?!\s*\()", replacement, result)
        else:
            result = re.sub(rf"\b{re.escape(variable)}\b(?!\s*\()", replacement, result)

    # Sat/MM/Hill are factor-style laws in BNGL.  The Playground writer adds
    # the first reactant as substrate when the SBML expression omits it.
    substrate = standardize_name(reactants[0]) + "_amt" if reactants else ""
    if substrate:
        result = _replace_nested_function(
            result,
            "Sat",
            lambda args: (
                f"Sat({', '.join(args + [substrate])})"
                if len(args) == 2
                else f"Sat({', '.join(args)})"
            ),
        )
        result = _replace_nested_function(
            result,
            "MM",
            lambda args: (
                f"MM({', '.join(args + [substrate])})"
                if len(args) == 2
                else f"MM({', '.join(args)})"
            ),
        )
        result = _replace_nested_function(
            result,
            "Hill",
            lambda args: (
                f"Hill({', '.join(args + [substrate])})"
                if len(args) == 3
                else f"Hill({', '.join(args)})"
            ),
        )
    return result


def curate_parameters(parameters: Mapping[str, object]) -> Dict[str, str]:
    """Curate SBML parameter values for BNGL emission.

    This mirrors the Playground writer's public ``curateParameters`` helper:
    non-finite literals are made parseable, NaN emits a warning and becomes
    zero, and identifiers use the same BNGL-safe spelling as the writer.
    """

    curated: Dict[str, str] = {}
    for parameter_id, parameter in parameters.items():
        value = (
            parameter.get("value", "")
            if isinstance(parameter, Mapping)
            else getattr(parameter, "value", "")
        )
        value_text = str(value)
        if re.search(r"inf", value_text, flags=re.IGNORECASE):
            value_text = re.sub(r"inf", "1e20", value_text, flags=re.IGNORECASE)
        if re.search(r"nan", value_text, flags=re.IGNORECASE):
            logger.warning(
                "BNW001",
                f"Parameter {parameter_id} has NaN value, setting to 0",
            )
            value_text = "0"
        curated[standardize_name(str(parameter_id))] = value_text
    return curated


def _strip_mass_action_factors(expression: str, reactant_ids: Sequence[str]) -> str:
    """Remove explicit SBML species factors from an elementary mass-action law."""

    pieces = [piece.strip() for piece in re.split(r"\*", expression or "")]
    if len(pieces) <= 1:
        return expression.strip() or "1"
    species_aliases = []
    for species_id in reactant_ids:
        raw_name = str(species_id)
        name = standardize_name(raw_name)
        species_aliases.append(
            {
                raw_name.lower(),
                name.lower(),
                f"{name}_amt".lower(),
                f"_c_{name}()".lower(),
                f"obs_{name}".lower(),
                f"obs_{name}()".lower(),
            }
        )
    remaining: List[str] = []
    removed = 0
    for piece in pieces:
        normalized = piece.strip()
        while normalized.startswith("(") and normalized.endswith(")"):
            normalized = normalized[1:-1].strip()
        key = normalized.lower()
        alias_index = next(
            (index for index, aliases in enumerate(species_aliases) if key in aliases),
            None,
        )
        if alias_index is not None:
            species_aliases.pop(alias_index)
            removed += 1
        else:
            remaining.append(piece)
    if removed != len(reactant_ids):
        return expression.strip() or "1"
    return " * ".join(remaining) if remaining else "1"


def _strip_explicit_reactant_factors(
    expression: str, reactant_ids: Sequence[str]
) -> str:
    """Remove only top-level reactant factors from a functional flux.

    Conditions and denominators may contain the same species symbol. Splitting
    only at top-level multiplication preserves those live dependencies.
    """

    value = str(expression or "").strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        encloses_all = True
        for index, character in enumerate(value):
            if character in "([":
                depth += 1
            elif character in ")]":
                depth -= 1
                if depth == 0 and index < len(value) - 1:
                    encloses_all = False
                    break
        if not encloses_all:
            break
        value = value[1:-1].strip()

    factors: List[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(value):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "*" and depth == 0:
            factors.append(value[start:index].strip())
            start = index + 1
    factors.append(value[start:].strip())

    removable: Dict[str, int] = {}
    for species_id in reactant_ids:
        raw_name = str(species_id)
        name = standardize_name(str(species_id))
        for token in (
            raw_name,
            name,
            f"{name}_amt",
            f"_c_{name}()",
            f"obs_{name}",
            f"obs_{name}()",
        ):
            key = token.lower()
            removable[key] = removable.get(key, 0) + 1

    kept: List[str] = []
    for factor in factors:
        normalized = factor.strip()
        while normalized.startswith("(") and normalized.endswith(")"):
            normalized = normalized[1:-1].strip()
        key = normalized.lower()
        if removable.get(key, 0) > 0:
            removable[key] -= 1
        else:
            kept.append(factor)
    return " * ".join(kept) if kept else "1"


def _is_functional_rate_expression(expression: str) -> bool:
    return bool(
        re.search(
            r"\b(?:if|piecewise)\s*\(|(?:>=|<=|==|!=|>|<)",
            str(expression or ""),
            re.IGNORECASE,
        )
    )


def _event_metadata_block(
    model: SBMLModel, species_to_pattern: Mapping[str, str]
) -> List[str]:
    """Preserve original SBML event semantics in machine-readable BNGL comments."""

    if not model.events:
        return []
    species_ids = sorted(
        (str(identifier) for identifier in model.species), key=len, reverse=True
    )

    def bngl_expression(expression: object) -> str:
        value = str(expression or "")
        for identifier in species_ids:
            value = re.sub(
                rf"\b{re.escape(identifier)}\b",
                f"{standardize_name(identifier)}_amt",
                value,
            )
        return value

    lines = ["# ==== SBML EVENT METADATA ===="]
    for index, event in enumerate(model.events):
        assignments = []
        for assignment in event.assignments:
            variable = getattr(assignment, "variable", None)
            expression = getattr(assignment, "math", None)
            if variable is None and isinstance(assignment, Mapping):
                variable = assignment.get("variable", "")
                expression = assignment.get("math", "")
            elif variable is None and isinstance(assignment, (tuple, list)):
                variable = assignment[0] if assignment else ""
                expression = assignment[1] if len(assignment) > 1 else ""
            variable = str(variable or "")
            assignments.append(
                {
                    "variable": variable,
                    "math": str(expression or ""),
                    "bnglVariable": standardize_name(variable),
                    "bnglTarget": species_to_pattern.get(variable),
                    "bnglMath": bngl_expression(expression),
                }
            )
        payload = {
            "id": event.id or f"event_{index}",
            "name": event.name or event.id or f"event_{index}",
            "trigger": event.trigger,
            "bnglTrigger": bngl_expression(event.trigger),
            "delay": event.delay,
            "bnglDelay": bngl_expression(event.delay),
            "priority": event.priority,
            "bnglPriority": bngl_expression(event.priority),
            "useValuesFromTriggerTime": event.use_values_from_trigger_time,
            "triggerInitialValue": event.trigger_initial_value,
            "triggerPersistent": event.trigger_persistent,
            "assignments": assignments,
        }
        encoded = quote(json.dumps(payload, separators=(",", ":")), safe="")
        lines.append(f"# @sbml-event {encoded}")
    lines.append("# ==============================")
    return lines


def _source_metadata_block(model: SBMLModel) -> List[str]:
    """Classify non-kinetic SBML metadata in generated BNGL comments."""

    payload = metadata_payload(model)
    if not payload.get("packages") and not payload.get("metadataEntities"):
        return []
    encoded = quote(json.dumps(payload, separators=(",", ":")), safe="")
    return [
        "# ==== SBML SOURCE METADATA ====",
        "# Source notes, CVTerms/MIRIAM annotations, SBO terms, and package declarations",
        "# are retained by the parser but are not executable BNGL state.",
        "# The ordinary C++ SBML writer does not serialize this metadata channel.",
        f"# @sbml-metadata {encoded}",
        "# ================================",
    ]


def _extract_statistical_factor(
    rate: str, reactant_structures: Mapping[str, Species]
) -> str:
    """Remove a leading repeated-site factor already represented by BNGL patterns."""

    match = re.match(r"^\s*\(?\s*(\d+(?:\.\d+)?)\s*\*\s*(.+?)\s*\)?\s*$", rate)
    if match is None:
        return rate
    coefficient = float(match.group(1))
    expected = 1
    for species in reactant_structures.values():
        for molecule in species.molecules:
            counts: Dict[str, int] = {}
            for component in molecule.components:
                counts[component.name] = counts.get(component.name, 0) + 1
            for count in counts.values():
                if count > 1:
                    expected *= count
    if expected > 1 and abs(coefficient - expected) < 1e-9:
        return match.group(2).strip()
    return rate


def _extract_top_level_additive_terms(expression: str) -> List[str]:
    """Split an expression at top-level ``+``/``-`` operators."""

    terms: List[str] = []
    depth = 0
    current_start = 0
    for index, char in enumerate(expression):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif (
            depth == 0
            and char in "+-"
            and index > 0
            and expression[index - 1] not in "eE*/^(["
        ):
            term = expression[current_start:index].strip()
            if term:
                terms.append(term)
            current_start = index
    last = expression[current_start:].strip()
    if last:
        terms.append(last)
    return terms


def _split_reversible_rate(expression: str) -> Optional[Tuple[str, str]]:
    """Recover forward and reverse laws from an SBML net reversible rate."""

    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        encloses_all = True
        for index, char in enumerate(value):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index < len(value) - 1:
                    encloses_all = False
                    break
        if not encloses_all:
            break
        value = value[1:-1].strip()

    positive: List[str] = []
    negative: List[str] = []
    for term in _extract_top_level_additive_terms(value):
        term = term.strip()
        if term.startswith("-"):
            body = term[1:].strip()
            if body:
                negative.append(body)
        elif term.startswith("+"):
            body = term[1:].strip()
            if body:
                positive.append(body)
        else:
            positive.append(term)
    if not positive or not negative:
        return None

    def combine(terms: Sequence[str]) -> str:
        return (
            terms[0] if len(terms) == 1 else " + ".join(f"({term})" for term in terms)
        )

    return combine(positive), combine(negative)


@dataclass(frozen=True)
class ReversibleRateSplit:
    """Reference-shaped result for reversible SBML rate decomposition."""

    success: bool
    forward_rate: str
    reverse_rate: str

    @property
    def forwardRate(self) -> str:
        return self.forward_rate

    @property
    def reverseRate(self) -> str:
        return self.reverse_rate


def split_reversible_rate(rate_expression: str) -> ReversibleRateSplit:
    """Split a net reversible rate into positive and negative laws."""

    split = _split_reversible_rate(rate_expression)
    if split is None:
        return ReversibleRateSplit(False, rate_expression, "0")
    return ReversibleRateSplit(True, split[0], split[1])


def _find_top_level_division(expression: str) -> int:
    """Return the first division outside parentheses, matching the reference writer."""

    depth = 0
    for index, character in enumerate(expression):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "/" and depth == 0:
            return index
    return -1


def _has_denominator_issue(neutralized_rate: str, reactant_ids: Sequence[str]) -> bool:
    """Detect saturation-like denominators after reactant neutralization.

    The Playground writer's ``split_rxn`` fallback protects a reversible rule
    when neutralizing a reactant would turn a denominator such as ``Km + A``
    into ``Km + 1``.  Removing that factor would change the rate law, so the
    complete net expression must remain on an irreversible functional rule.
    """

    normalized = neutralized_rate
    for species_id in reactant_ids:
        name = standardize_name(species_id)
        normalized = re.sub(
            rf"_c_{re.escape(name)}\(\)", "1", normalized, flags=re.IGNORECASE
        )
        normalized = re.sub(
            rf"\b{re.escape(name)}_amt\b", "1", normalized, flags=re.IGNORECASE
        )
        normalized = re.sub(
            rf"\b{re.escape(name)}\b", "1", normalized, flags=re.IGNORECASE
        )

    division_index = _find_top_level_division(normalized)
    if division_index < 0:
        return False
    denominator = normalized[division_index + 1 :].strip()
    if "+" not in denominator:
        return False
    return bool(
        re.search(r"[\(+]\s*1\s*[+\)]", denominator)
        or re.search(r"[\(+]\s*1\s*$", denominator)
    )


def _numeric_parameter_value(value: object) -> float:
    if isinstance(value, Mapping):
        value = value.get("value", value.get("size"))
    else:
        value = getattr(value, "value", value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _safe_numeric_expression(
    expression: str, variables: Mapping[str, float]
) -> Optional[float]:
    """Evaluate the bounded arithmetic subset used by source mass-action checks."""

    normalized = str(expression or "")
    normalized = normalized.replace("^", "**")
    normalized = normalized.replace("&&", " and ").replace("||", " or ")
    normalized = re.sub(r"\bif\s*\(", "if_(", normalized)
    normalized = re.sub(r"\btrue\b", "1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bfalse\b", "0", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<![=!<>])!(?!=)", " not ", normalized)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError:
        return None

    functions = {
        "abs": abs,
        "acos": math.acos,
        "asin": math.asin,
        "atan": math.atan,
        "ceil": math.ceil,
        "cos": math.cos,
        "cosh": math.cosh,
        "exp": math.exp,
        "floor": math.floor,
        "ln": math.log,
        "log": math.log10,
        "log10": math.log10,
        "max": max,
        "min": min,
        "pow": pow,
        "rint": round,
        "sin": math.sin,
        "sinh": math.sinh,
        "sqrt": math.sqrt,
        "tan": math.tan,
        "tanh": math.tanh,
    }

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(node.id)
            return float(variables[node.id])
        if isinstance(node, ast.UnaryOp):
            operand = evaluate(node.operand)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.Not):
                return float(not operand)
            raise ValueError(type(node.op).__name__)
        if isinstance(node, ast.BinOp):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left**right
            raise ValueError(type(node.op).__name__)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for value in node.values:
                    if not evaluate(value):
                        return 0.0
                return 1.0
            if isinstance(node.op, ast.Or):
                for value in node.values:
                    if evaluate(value):
                        return 1.0
                return 0.0
            raise ValueError(type(node.op).__name__)
        if isinstance(node, ast.Compare):
            left = evaluate(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = evaluate(comparator)
                if isinstance(operator, ast.Gt):
                    passed = left > right
                elif isinstance(operator, ast.GtE):
                    passed = left >= right
                elif isinstance(operator, ast.Lt):
                    passed = left < right
                elif isinstance(operator, ast.LtE):
                    passed = left <= right
                elif isinstance(operator, ast.Eq):
                    passed = left == right
                elif isinstance(operator, ast.NotEq):
                    passed = left != right
                else:
                    raise ValueError(type(operator).__name__)
                if not passed:
                    return 0.0
                left = right
            return 1.0
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "time":
                if node.args:
                    raise ValueError("time arguments")
                return 0.0
            if name == "if_":
                if len(node.args) != 3:
                    raise ValueError("if arguments")
                return evaluate(
                    node.args[1] if evaluate(node.args[0]) else node.args[2]
                )
            function = functions.get(name)
            if function is None or node.keywords:
                raise ValueError(name)
            return float(function(*(evaluate(argument) for argument in node.args)))
        raise ValueError(type(node).__name__)

    try:
        result = evaluate(tree)
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return None
    if isinstance(result, complex):
        return None
    return result if math.isfinite(result) else None


def _contains_static_zero_divisor(expression: str) -> bool:
    """Detect a literal arithmetic division by zero in an SBML expression."""

    text = str(expression or "")
    numeric_only = re.compile(r"[0-9eE+*/^().\s-]+")
    for match in re.finditer(r"/", text):
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            continue
        start = index
        if text[index] == "(":
            depth = 0
            while index < len(text):
                if text[index] == "(":
                    depth += 1
                elif text[index] == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            divisor = text[start:index]
        else:
            number = re.match(
                r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text[index:]
            )
            if number is None:
                continue
            index += number.end()
            divisor = text[start:index]
        if not numeric_only.fullmatch(divisor):
            continue
        if _safe_numeric_expression(divisor, {}) == 0.0:
            return True
    return False


def _rewrite_mass_action_symbols(
    expression: str,
    species_to_compartment: Mapping[str, str],
    compartments: Optional[Mapping[str, object]] = None,
    assignment_rule_variables: Iterable[str] = (),
) -> str:
    result = str(expression or "")
    species_names = {
        standardize_name(str(species_id)): str(compartment_id or "")
        for species_id, compartment_id in species_to_compartment.items()
    }
    for name, compartment_id in sorted(
        species_names.items(), key=lambda item: len(item[0]), reverse=True
    ):
        escaped = re.escape(name)
        if compartment_id:
            concentration = (
                f"({name} / __compartment_{standardize_name(compartment_id)}__)"
            )
        else:
            concentration = name
        result = re.sub(
            rf"_c_{escaped}\s*\(\s*\)", concentration, result, flags=re.IGNORECASE
        )
        result = re.sub(rf"\b{escaped}_amt\b", name, result, flags=re.IGNORECASE)
    for variable in sorted(
        {standardize_name(str(value)) for value in assignment_rule_variables},
        key=len,
        reverse=True,
    ):
        result = re.sub(rf"\b{re.escape(variable)}\s*\(\s*\)", variable, result)
    return result


def check_mass_action(
    rate_expression: str,
    divisor_expression: str,
    volume_expression: str,
    parameter_dict: Mapping[str, object],
    compartments: Mapping[str, object],
    species_to_compartment: Mapping[str, str],
    assignment_rule_variables: Optional[Set[str]] = None,
    reaction_order: Optional[int] = None,
) -> Optional[float]:
    """Numerically check whether a processed rate is a constant mass-action law.

    This follows the pinned Playground writer's source contract: normalize amount
    and concentration operands, evaluate the rate times the appropriate power of
    volume divided by the stoichiometric divisor at several positive points, and
    accept only a finite low-variance result.  ``reaction_order`` is the number
    of reactant molecules; it defaults to one for compatibility with the public
    helper's historical first-order contract.
    """

    assignment_rule_variables = assignment_rule_variables or set()
    rate = _rewrite_mass_action_symbols(
        rate_expression, species_to_compartment, compartments, assignment_rule_variables
    )
    divisor = _rewrite_mass_action_symbols(
        divisor_expression,
        species_to_compartment,
        compartments,
        assignment_rule_variables,
    )
    volume = _rewrite_mass_action_symbols(
        volume_expression,
        species_to_compartment,
        compartments,
        assignment_rule_variables,
    )
    base: Dict[str, float] = {"__Avogadro__": 1.0}
    for parameter_id, parameter in parameter_dict.items():
        value = _numeric_parameter_value(parameter)
        base[str(parameter_id)] = value
        base[standardize_name(str(parameter_id))] = value
    for compartment_id, compartment in compartments.items():
        size = _numeric_parameter_value(getattr(compartment, "size", compartment))
        name = standardize_name(str(compartment_id))
        base[f"__compartment_{name}__"] = size
        base[name] = size

    species_names = sorted(
        {standardize_name(str(species_id)) for species_id in species_to_compartment},
        key=len,
    )
    assignment_names = sorted(
        {standardize_name(str(value)) for value in assignment_rule_variables},
        key=len,
    )
    # BNGL's deterministic mass-action rule uses molecule amounts as state
    # variables, while SBML concentration laws use C = amount / V.  For an
    # n-th order law, recover the BNGL rate constant with V**n, not a single
    # volume factor.  The old one-factor probe was correct only for first
    # order reactions and made tiny-volume bimolecular models numerically
    # explosive after SBML round-trip.
    volume_power = max(0, int(reaction_order if reaction_order is not None else 1))
    volume_factor = f"({volume})**{volume_power}" if volume_power else "1"
    samples = ((1.25, 3.5), (2.5, 11.0), (7.0, 29.0))
    values: List[float] = []
    for index, (volume_value, species_start) in enumerate(samples):
        context = dict(base)
        context["V"] = volume_value
        for offset, name in enumerate(species_names):
            context[name] = species_start + (offset + 1) * (index + 1)
        for offset, name in enumerate(assignment_names):
            context[name] = 2.0 + offset + index * 0.5
        value = _safe_numeric_expression(
            f"({rate}) * ({volume_factor}) / ({divisor})", context
        )
        if value is None:
            return None
        values.append(value)

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    # Do not use an absolute-magnitude cutoff here.  A valid SBML flux can be
    # much smaller than 1e-12 in the source numeric scale.  Treating such a
    # value as exactly zero can erase a state-dependent law (including a
    # negative flux) before the nonlinear-rate path has a chance to preserve
    # it.  Exact zero still passes naturally because its variance and
    # coefficient of variation are both zero.
    coefficient_of_variation = math.sqrt(variance) / (abs(mean) + 1e-60)
    return mean if coefficient_of_variation < 1e-4 else None


def _prepared_kinetic_math(
    reaction: SBMLReaction,
    model: SBMLModel,
    replace_loc_params: bool = True,
    reaction_id: Optional[str] = None,
) -> str:
    """Inline functions and substitute reaction-local parameters once."""

    math_expression = extend_function(
        get_kinetic_math(reaction.kinetic_law),
        {},
        model.function_definitions,
    )

    def replace_sum(match: re.Match[str]) -> str:
        species_id = match.group(1)
        if model.multi_executable and model.multi_species_patterns.get(species_id):
            return f"__multi_sum_{standardize_name(species_id)}"
        _record_import_warning(
            model,
            f'Multi sum representation for species "{species_id}" could not be '
            "lowered to a BNGL pattern observable.",
            category="package:multi",
            severity="dropped",
        )
        return standardize_name(species_id)

    def replace_numeric(match: re.Match[str]) -> str:
        value_id = match.group(1)
        parameter_id = model.multi_numeric_values.get(value_id)
        if parameter_id:
            return standardize_name(parameter_id)
        _record_import_warning(
            model,
            f'Multi numericValue "{value_id}" has no referenced parameter.',
            category="package:multi",
            severity="dropped",
        )
        return standardize_name(value_id)

    math_expression = _MULTI_SUM_TOKEN.sub(replace_sum, math_expression)
    math_expression = _MULTI_NUMERIC_TOKEN.sub(replace_numeric, math_expression)
    kinetic_law = reaction.kinetic_law
    local_parameters = (
        kinetic_law.get("localParameters", [])
        if isinstance(kinetic_law, Mapping)
        else getattr(kinetic_law, "local_parameters", [])
    )
    local_parameter_ids: Set[str] = set()
    for parameter in local_parameters or []:
        parameter_id = getattr(parameter, "id", None)
        if parameter_id is None and isinstance(parameter, Mapping):
            parameter_id = parameter.get("id")
        parameter_value = getattr(parameter, "value", None)
        if parameter_value is None and isinstance(parameter, Mapping):
            parameter_value = parameter.get("value")
        if parameter_id:
            local_parameter_ids.add(str(parameter_id))
            replacement = (
                _curated_parameter_value(model, str(parameter_id), parameter_value)
                if replace_loc_params
                else standardize_name(f"{reaction_id or reaction.id}_{parameter_id}")
            )
            math_expression = re.sub(
                rf"\b{re.escape(str(parameter_id))}\b",
                replacement,
                math_expression,
            )

    # In SBML Level 3 a speciesReference id is a reaction-scoped stoichiometry
    # symbol.  It is not a global BNGL parameter.  Substitute its fixed value
    # in the kinetic law when no same-named local parameter shadows it; this
    # covers the suite's stoichiometry-reference cases without leaking a
    # reaction-local identifier into the generated model.
    for reference in [*reaction.reactants, *reaction.products]:
        reference_id = getattr(reference, "id", None)
        if reference_id is None and isinstance(reference, Mapping):
            reference_id = reference.get("id")
        if not reference_id or str(reference_id) in local_parameter_ids:
            continue
        stoichiometry = getattr(reference, "stoichiometry", None)
        if stoichiometry is None and isinstance(reference, Mapping):
            stoichiometry = reference.get("stoichiometry", 1)
        if getattr(reference, "variable_stoichiometry", False):
            dynamic_expression = _dynamic_species_reference_expression(
                reference, model, reaction_id or reaction.id
            )
            if dynamic_expression is None:
                _record_import_warning(
                    model,
                    f'Reaction "{reaction_id or reaction.id}" references variable '
                    f'stoichiometry symbol "{reference_id}" without a lowerable '
                    "expression.",
                    category="stoichiometry",
                    severity="dropped",
                )
                continue
            math_expression = re.sub(
                rf"\b{re.escape(str(reference_id))}\b",
                f"({dynamic_expression})",
                math_expression,
            )
            continue
        value = _numeric_value(stoichiometry)
        if value is not None:
            math_expression = re.sub(
                rf"\b{re.escape(str(reference_id))}\b",
                _number(value),
                math_expression,
            )

    assignment_variables = {
        str(rule.variable)
        for rule in model.rules
        if rule.variable and getattr(rule, "type", "") in {"assignment", "rate"}
    }
    species_map = {
        alias: species_id
        for species_id in model.species
        for alias in (species_id, standardize_name(species_id))
    }
    species_assignment_targets = {
        standardize_name(variable)
        for variable in _lowerable_species_assignment_rules(model)
    }
    concentration_names = {
        standardize_name(species_id)
        for species_id, species in model.species.items()
        if (
            not species.has_only_substance_units
            and standardize_name(species_id) not in species_assignment_targets
        )
    }
    math_expression = _inline_reaction_fluxes(
        math_expression,
        model,
        assignment_variables,
        set(),
        concentration_names,
        species_map,
        replace_loc_params,
        exclude_reaction_id=reaction_id or reaction.id,
    )
    return math_expression


def _dynamic_species_reference_expression(
    reference: object, model: SBMLModel, reaction_id: str
) -> Optional[str]:
    """Map a dynamic species-reference value into executable BNGL math."""

    expression = str(getattr(reference, "stoichiometry_math", "") or "").strip()
    reference_id = str(getattr(reference, "id", "") or "").strip()
    if not expression and reference_id:
        targets = {
            standardize_name(str(rule.variable))
            for rule in model.rules
            if rule.variable and rule.type in {"assignment", "rate"}
        }
        if standardize_name(reference_id) in targets:
            expression = reference_id
    if not expression:
        return None
    synthetic = SBMLReaction(
        id=f"{reaction_id}_stoichiometry",
        kinetic_law=SBMLKineticLaw(math=expression),
    )
    prepared = _prepared_kinetic_math(synthetic, model, replace_loc_params=False)
    return _rate_for_reaction(
        synthetic,
        model,
        reactant_ids=[],
        prepared_math=prepared,
        replace_loc_params=False,
    )


def _strip_compartment_rate_factors(
    expression: str,
    model: SBMLModel,
    reactants: Sequence[str],
    reaction_compartment: Optional[str] = None,
) -> str:
    """Return the elementary candidate without its reaction volume factor.

    This is used only as a classification candidate.  A complete SBML flux
    must retain its compartment geometry; the caller keeps the original
    expression whenever it is nonlinear or state-dependent.
    """

    result = str(expression or "")
    if not reactants:
        return result
    if not any(
        re.search(rf"\b{re.escape(standardize_name(species_id))}\b", result)
        for species_id in reactants
    ):
        return result
    target_compartment = reaction_compartment
    if not target_compartment and reactants:
        first_species = model.species.get(reactants[0])
        target_compartment = (
            getattr(first_species, "compartment", None)
            if first_species is not None
            else None
        )
    if not target_compartment or target_compartment not in model.compartments:
        return result.strip() or "1"
    standardized = standardize_name(str(target_compartment))
    for pattern in (
        rf"\s*\*\s*__compartment_{re.escape(standardized)}__\s*",
        rf"\s*\*\s*{re.escape(str(target_compartment))}\b\s*",
        rf"\s*/\s*__compartment_{re.escape(standardized)}__\s*",
        rf"\s*/\s*{re.escape(str(target_compartment))}\b\s*",
    ):
        result = re.sub(pattern, " ", result)
    result = re.sub(
        rf"^\s*__compartment_{re.escape(standardized)}__\s*\*\s*", "", result
    )
    result = re.sub(rf"^\s*{re.escape(str(target_compartment))}\b\s*\*\s*", "", result)
    return result.strip() or "1"


def _local_parameter_entries(model: SBMLModel) -> List[Tuple[str, object]]:
    """Return source-scoped local parameters under stable BNGL identifiers."""

    entries: "OrderedDict[str, object]" = OrderedDict()
    for reaction_id, reaction in model.reactions.items():
        kinetic_law = reaction.kinetic_law
        local_parameters = (
            kinetic_law.get("localParameters", [])
            if isinstance(kinetic_law, Mapping)
            else getattr(kinetic_law, "local_parameters", [])
        )
        for parameter in local_parameters or []:
            parameter_id = getattr(parameter, "id", None)
            if parameter_id is None and isinstance(parameter, Mapping):
                parameter_id = parameter.get("id")
            if not parameter_id:
                continue
            parameter_value = getattr(parameter, "value", None)
            if parameter_value is None and isinstance(parameter, Mapping):
                parameter_value = parameter.get("value")
            name = standardize_name(f"{reaction_id}_{parameter_id}")
            entries.setdefault(name, parameter_value)
    return list(entries.items())


def _rate_for_reaction(
    reaction: SBMLReaction,
    model: SBMLModel,
    conversion_factor: Optional[str] = None,
    observable_converted_rules: Optional[Set[str]] = None,
    reactant_structures: Optional[Mapping[str, Species]] = None,
    reactant_ids: Optional[Sequence[str]] = None,
    prepared_math: Optional[str] = None,
    replace_loc_params: bool = True,
) -> str:
    def apply_conversion(rate: str) -> str:
        if conversion_factor is None:
            return rate
        return f"{conversion_factor} * ({rate})"

    math = (
        prepared_math
        if prepared_math is not None
        else _prepared_kinetic_math(
            reaction,
            model,
            replace_loc_params=replace_loc_params,
        )
    )
    if not math or not str(math).strip():
        _log_missing_kinetic(
            f"Reaction {standardize_name(reaction.name or reaction.id)} "
            f"missing kinetic law; using fallback rate {_MISSING_KINETIC_RATE_FALLBACK}"
        )
        return apply_conversion(_MISSING_KINETIC_RATE_FALLBACK)
    reactants = (
        list(reactant_ids)
        if reactant_ids is not None
        else [
            reference.species
            for reference in reaction.reactants
            if reference.species != "EmptySet"
            for _ in range(max(0, int(round(reference.stoichiometry))))
        ]
    )
    species_map = {}
    for species_id in model.species:
        species_map[species_id] = species_id
        species_map[standardize_name(species_id)] = species_id
    assignment_variables = {
        rule.variable
        for rule in [*_assignment_rules_for_writer(model), *model.rules]
        if rule.variable and getattr(rule, "type", "") in {"assignment", "rate"}
    }
    observable_converted_rules = observable_converted_rules or set()
    rate_rule_variables = {
        standardize_name(rule.variable)
        for rule in model.rules
        if rule.variable and rule.type == "rate"
    }
    concentration_names = {
        standardize_name(species_id)
        for species_id, species in model.species.items()
        if (
            not species.has_only_substance_units
            and standardize_name(species_id)
            not in {
                standardize_name(variable)
                for variable in _lowerable_species_assignment_rules(model)
            }
        )
    }
    if reactant_structures is not None:
        reactant_structures = {
            species_id: structure
            for species_id, structure in reactant_structures.items()
            if species_id in reactants
        }

    has_saturation = bool(re.search(r"\b(?:Sat|MM|Hill)\s*\(", math))
    functional = _is_functional_rate_expression(math)
    if reactant_structures:
        # Do this before the mass-action classifier.  Otherwise an explicit
        # repeated-site/statistical factor changes the numeric probe and the
        # writer emits that factor as a kinetic constant instead of removing
        # the factor already represented by the BNGL pattern.
        math = _extract_statistical_factor(
            convert_math_expression(math), reactant_structures
        )
    compartment_stripped_math = _strip_compartment_rate_factors(
        math,
        model,
        reactants,
        reaction_compartment=reaction.compartment,
    )
    preserved_compartment_flux = compartment_stripped_math != math
    reactant_names = {standardize_name(species_id) for species_id in reactants}

    def references_species(expression: str, species_id: str) -> bool:
        standardized = standardize_name(species_id)
        return bool(
            re.search(rf"\b{re.escape(standardized)}\b", expression)
            or re.search(
                rf"_c_{re.escape(standardized)}\s*\(",
                expression,
                re.IGNORECASE,
            )
            or re.search(
                rf"\b{re.escape(standardized)}_amt\b",
                expression,
                re.IGNORECASE,
            )
        )

    classification_math = compartment_stripped_math
    # A retained SBML flux is already a complete amount/time expression.  If
    # it omits any consumed species, it cannot be emitted as an elementary
    # BNGL coefficient: the reaction pattern would multiply the law by that
    # species a second time.  Treat this as a nonlinear/complete flux so the
    # caller can mark the rule TotalRate.
    has_missing_reactant = bool(reactants) and any(
        not references_species(classification_math, species_id)
        for species_id in set(reactants)
    )
    has_nonreactant_species = any(
        references_species(classification_math, species_id)
        and standardize_name(species_id) not in reactant_names
        for species_id in model.species
    )
    nonlinear = (
        has_saturation
        or "/" in classification_math
        or functional
        or has_nonreactant_species
        or has_missing_reactant
        or bool(
            re.search(r"\^\s*\(\s*-\s*\d", classification_math)
            or re.search(r"\^\s*-\s*\d", classification_math)
        )
    )

    # The reaction-compartment factor is redundant only for an elementary
    # amount law.  Preserve it on complete SBML fluxes, where it converts the
    # concentration-valued state expression back to an amount/time flux.
    if not nonlinear:
        math = compartment_stripped_math

    # Algebraically nonlinear-looking SBML syntax can still be an elementary
    # mass-action law (the stochastic suite deliberately exercises this with
    # nested divisions).  Test that normalized form before retaining a dynamic
    # amount-dependent rate, otherwise the engine multiplies by the reactant
    # count a second time.
    converted_for_check = bngl_function(
        convert_math_expression(math),
        reaction.name or reaction.id,
        reactants,
        list(model.compartments),
        assignment_rule_variables=assignment_variables,
        observable_converted_rules=observable_converted_rules,
        species_with_conc_functions=concentration_names,
        sbml_to_bngl_id=species_map,
        rate_rule_variables=rate_rule_variables,
    )
    if (
        _ENABLE_MASS_ACTION_CHECK
        and not functional
        and not has_saturation
        and not (preserved_compartment_flux and nonlinear)
        and len(model.reactions) < _MASS_ACTION_SKIP_MIN_REACTIONS
        and len(converted_for_check) < _MASS_ACTION_SKIP_EXPR_LEN
        and not re.search(r"\btime\s*\(", converted_for_check)
    ):
        check_counts: "OrderedDict[str, float]" = OrderedDict()
        for species_id in reactants:
            check_counts[species_id] = check_counts.get(species_id, 0) + 1
        check_divisor_parts = []
        for species_id, stoichiometry in check_counts.items():
            name = standardize_name(species_id)
            if stoichiometry == 1:
                check_divisor_parts.append(f"{name}_amt")
            else:
                check_divisor_parts.append(
                    f"(({name}_amt^{_number(stoichiometry)})/"
                    f"{_number(_factorial(stoichiometry))})"
                )
        check_divisor = " * ".join(check_divisor_parts) or "1"
        check_compartment = reaction.compartment
        if not check_compartment:
            for reference in [*reaction.reactants, *reaction.products]:
                if reference.species == "EmptySet":
                    continue
                species = model.species.get(reference.species)
                if species is not None and species.compartment:
                    check_compartment = species.compartment
                    break
        check_volume = (
            f"__compartment_{standardize_name(check_compartment)}__"
            if check_compartment and check_counts
            else "1"
        )
        check_parameter_values = {
            parameter_id: getattr(parameter, "value", parameter)
            for parameter_id, parameter in model.parameters.items()
        }
        mass_action_constant = check_mass_action(
            converted_for_check,
            check_divisor,
            check_volume,
            check_parameter_values,
            model.compartments,
            {
                species_id: getattr(model.species.get(species_id), "compartment", "")
                for species_id in model.species
            },
            assignment_variables,
            reaction_order=len(reactants),
        )
        if mass_action_constant is not None:
            return apply_conversion(_number(mass_action_constant))

    # The Playground writer keeps nonlinear laws intact and maps their species
    # operands to concentration functions (or amount observables for Sat/MM/
    # Hill).  Only elementary mass-action factors are removed before that
    # mapping; stripping a substrate from a saturation or rational law changes
    # its biology.
    if nonlinear:
        converted_function = bngl_function(
            convert_math_expression(math),
            reaction.name or reaction.id,
            reactants,
            list(model.compartments),
            assignment_rule_variables=assignment_variables,
            observable_converted_rules=observable_converted_rules,
            species_with_conc_functions=concentration_names,
            sbml_to_bngl_id=species_map,
            rate_rule_variables=rate_rule_variables,
        )
        if functional:
            converted_function = _strip_explicit_reactant_factors(
                converted_function, reactants
            )
        return apply_conversion(converted_function)

    converted = convert_math_expression(math)
    converted_rate = bngl_function(
        converted,
        reaction.name or reaction.id,
        reactants,
        list(model.compartments),
        assignment_rule_variables=assignment_variables,
        observable_converted_rules=observable_converted_rules,
        species_with_conc_functions=concentration_names,
        sbml_to_bngl_id=species_map,
        rate_rule_variables=rate_rule_variables,
    )

    counts: "OrderedDict[str, float]" = OrderedDict()
    for species_id in reactants:
        counts[species_id] = counts.get(species_id, 0) + 1
    divisor_parts: List[str] = []
    for species_id, stoichiometry in counts.items():
        name = standardize_name(species_id)
        if stoichiometry == 1:
            divisor_parts.append(f"{name}_amt")
        else:
            divisor_parts.append(
                f"(({name}_amt^{_number(stoichiometry)})/"
                f"{_number(_factorial(stoichiometry))})"
            )
    divisor = " * ".join(divisor_parts) if divisor_parts else "1"
    rule_compartment = reaction.compartment
    if not rule_compartment:
        for reference in [*reaction.reactants, *reaction.products]:
            if reference.species == "EmptySet":
                continue
            species = model.species.get(reference.species)
            if species is not None and species.compartment:
                rule_compartment = species.compartment
                break
    volume = (
        f"__compartment_{standardize_name(rule_compartment)}__"
        if rule_compartment and counts
        else "1"
    )
    parameter_values = {
        parameter_id: getattr(parameter, "value", parameter)
        for parameter_id, parameter in model.parameters.items()
    }
    if (
        _ENABLE_MASS_ACTION_CHECK
        and not functional
        and len(model.reactions) < _MASS_ACTION_SKIP_MIN_REACTIONS
        and len(converted_rate) < _MASS_ACTION_SKIP_EXPR_LEN
        and not re.search(r"\btime\s*\(", converted_rate)
    ):
        mass_action_constant = check_mass_action(
            converted_rate,
            divisor,
            volume,
            parameter_values,
            model.compartments,
            {
                species_id: getattr(model.species.get(species_id), "compartment", "")
                for species_id in model.species
            },
            assignment_variables,
            reaction_order=len(reactants),
        )
        if mass_action_constant is not None:
            return apply_conversion(_number(mass_action_constant))

    stripped = _strip_mass_action_factors(converted, reactants)
    return apply_conversion(
        bngl_function(
            stripped,
            reaction.name or reaction.id,
            reactants,
            list(model.compartments),
            assignment_rule_variables=assignment_variables,
            observable_converted_rules=observable_converted_rules,
            species_with_conc_functions=concentration_names,
            sbml_to_bngl_id=species_map,
            rate_rule_variables=rate_rule_variables,
        )
    )


def _reaction_species_ids(
    references: Sequence[object],
) -> List[str]:
    species_ids: List[str] = []
    for reference in references:
        species_id = getattr(reference, "species", None)
        if species_id is None and isinstance(reference, Mapping):
            species_id = reference.get("species")
        if species_id in (None, "EmptySet"):
            continue
        stoichiometry = getattr(reference, "stoichiometry", None)
        if stoichiometry is None and isinstance(reference, Mapping):
            stoichiometry = reference.get("stoichiometry", 1)
        try:
            count = max(0, int(round(float(stoichiometry))))
        except (TypeError, ValueError):
            count = 0
        species_ids.extend([str(species_id)] * count)
    return species_ids


def _rate_requires_total_rate(
    rate: str,
    reactant_ids: Optional[Sequence[str]] = None,
    source_rate: Optional[str] = None,
) -> bool:
    """Identify retained SBML fluxes that still contain dynamic state factors.

    Numeric elementary coefficients are emitted without ``TotalRate`` when
    the original SBML law explicitly contained the reactant factor.  That is
    the mass-action case: the lowering removes the factor and BNGL must add
    it back from the reaction pattern.  A parameter-only SBML law is already
    a complete flux, even when its value is numeric, and must retain
    ``TotalRate`` so BNGL does not multiply it by the reactant population.
    Any non-numeric expression that survives rate lowering is likewise a
    complete SBML flux: it either retains a live reactant operand or has had
    an explicit reactant factor removed from a functional/compound law.
    """

    parts = _split_reversible_rate(rate) or (rate,)
    reactants = list(reactant_ids or [])
    if not reactants:
        return any(
            _evaluate_arithmetic(convert_math_expression(part)) is None
            for part in parts
        )
    saw_dynamic_part = False
    source_parts = (
        list(_split_reversible_rate(source_rate) or (source_rate,))
        if source_rate
        else []
    )
    for index, part in enumerate(parts):
        source_part = (
            source_parts[min(index, len(source_parts) - 1)] if source_parts else ""
        )
        source_has_reactant = bool(source_part) and any(
            re.search(
                rf"(?:\b{re.escape(standardize_name(species_id))}\b|"
                rf"_c_{re.escape(standardize_name(species_id))}\s*\(|"
                rf"\b{re.escape(standardize_name(species_id))}_amt\b)",
                source_part,
                re.IGNORECASE,
            )
            for species_id in reactants
        )
        lowered_has_reactant = any(
            re.search(
                rf"(?:\b{re.escape(standardize_name(species_id))}\b|"
                rf"_c_{re.escape(standardize_name(species_id))}\s*\(|"
                rf"\b{re.escape(standardize_name(species_id))}_amt\b)",
                part,
                re.IGNORECASE,
            )
            for species_id in reactants
        )
        if source_parts:
            # If the source flux contains no consumed species, it is complete
            # even when it is numerically constant. If the source does contain
            # a consumed species, the lowered law is complete only when that
            # dynamic operand remains in the expression; otherwise BNGL must
            # supply it from the reaction pattern.
            if not source_has_reactant:
                return True
            if lowered_has_reactant:
                return True
            continue
        if _evaluate_arithmetic(convert_math_expression(part)) is not None:
            continue
        saw_dynamic_part = True
        if lowered_has_reactant:
            return True
    return saw_dynamic_part


def process_reaction_rate(
    reaction: SBMLReaction,
    reaction_id: str,
    model: SBMLModel,
    observable_converted_rules: Optional[Set[str]] = None,
    reactant_structures: Optional[Mapping[str, Species]] = None,
    conversion_factor: Optional[str] = None,
    replace_loc_params: bool = True,
) -> ProcessedRate:
    """Process one SBML rate using the source-shaped reversible pipeline."""

    prepared_math = _prepared_kinetic_math(
        reaction,
        model,
        replace_loc_params=replace_loc_params,
        reaction_id=reaction_id,
    )
    structures = reactant_structures or {}
    if not prepared_math or not str(prepared_math).strip():
        rate = _rate_for_reaction(
            reaction,
            model,
            conversion_factor,
            observable_converted_rules,
            structures,
            prepared_math=prepared_math,
            replace_loc_params=replace_loc_params,
        )
        return ProcessedRate(
            rate,
            force_irreversible=bool(reaction.reversible),
            is_total_rate=_rate_requires_total_rate(
                rate,
                _reaction_species_ids(reaction.reactants),
                prepared_math,
            ),
        )

    forward_ids = _reaction_species_ids(reaction.reactants)
    split = None
    if reaction.reversible:
        converted_prepared = convert_math_expression(prepared_math)
        # Prefer the source-shaped net flux.  An outer compartment factor is
        # part of the SBML amount/time flux and must not be dropped merely to
        # expose two directional laws.  If the source expression has no
        # directly splittable top-level subtraction, retain the complete net
        # flux and let the caller lower it to an irreversible TotalRate rule.
        split = _split_reversible_rate(converted_prepared)
    if split is None:
        rate = _rate_for_reaction(
            reaction,
            model,
            conversion_factor,
            observable_converted_rules,
            structures,
            prepared_math=prepared_math,
            replace_loc_params=replace_loc_params,
        )
        return ProcessedRate(
            rate,
            force_irreversible=bool(reaction.reversible),
            is_total_rate=_rate_requires_total_rate(
                rate,
                _reaction_species_ids(reaction.reactants),
                prepared_math,
            ),
        )

    reverse_ids = _reaction_species_ids(reaction.products)
    forward_rate = _rate_for_reaction(
        reaction,
        model,
        conversion_factor,
        observable_converted_rules,
        structures,
        reactant_ids=forward_ids,
        prepared_math=split[0],
        replace_loc_params=replace_loc_params,
    )
    reverse_rate = _rate_for_reaction(
        reaction,
        model,
        conversion_factor,
        observable_converted_rules,
        structures,
        reactant_ids=reverse_ids,
        prepared_math=split[1],
        replace_loc_params=replace_loc_params,
    )
    if _has_denominator_issue(forward_rate, forward_ids) or _has_denominator_issue(
        reverse_rate, reverse_ids
    ):
        return ProcessedRate(
            _rate_for_reaction(
                reaction,
                model,
                conversion_factor,
                observable_converted_rules,
                structures,
                prepared_math=prepared_math,
                replace_loc_params=replace_loc_params,
            ),
            force_irreversible=True,
            is_split_rxn=True,
        )
    forward_is_total_rate = _rate_requires_total_rate(
        forward_rate, forward_ids, split[0]
    )
    reverse_is_total_rate = _rate_requires_total_rate(
        reverse_rate, reverse_ids, split[1]
    )
    return ProcessedRate(
        f"{forward_rate}, {reverse_rate}",
        force_irreversible=False,
        is_split_rxn=False,
        is_total_rate=forward_is_total_rate or reverse_is_total_rate,
        forward_is_total_rate=forward_is_total_rate,
        reverse_is_total_rate=reverse_is_total_rate,
    )


def _record_import_warning(
    model: SBMLModel,
    message: str,
    category: str = "conversionFactor",
    severity: str = "approximated",
) -> None:
    warnings = getattr(model, "import_warnings", None)
    if warnings is None:
        model.import_warnings = []
        warnings = model.import_warnings
    if any(
        warning.get("category") == category and warning.get("message") == message
        for warning in warnings
    ):
        return
    warnings.append(
        {
            "category": category,
            "message": message,
            "count": 1,
            "severity": severity,
        }
    )


def _lower_bounded_event_state_delays(model: SBMLModel, t_end: float) -> int:
    """Fold delayed history that stays at or before simulation start.

    This is exact only for delay calls whose duration is at least the requested
    nonnegative simulation horizon. Their entire queried history is the SBML
    initial state, even if the delayed state changes during the run.
    """
    if not math.isfinite(t_end) or t_end < 0:
        return 0
    event_targets = {
        str(variable)
        for event in model.events
        for assignment in event.assignments
        for variable, _expression in [_event_assignment(assignment)]
        if variable
    }
    initial_assignment_targets = {
        str(assignment.symbol)
        for assignment in model.initial_assignments
        if assignment.symbol
    }
    delay_call = re.compile(r"\bdelay\s*\(", re.IGNORECASE)

    def initial_value(target: str) -> Optional[float]:
        target_rules = [rule for rule in model.rules if rule.variable == target]
        if target in initial_assignment_targets:
            assignments = [
                assignment
                for assignment in model.initial_assignments
                if assignment.symbol == target
            ]
            if len(assignments) != 1:
                return None
            expression = re.sub(
                r"\btime\b", "0", str(assignments[0].math or ""), flags=re.I
            )
            return initial_expression(expression, require_immutable_symbols=True)
        if any(rule.type == "assignment" for rule in target_rules):
            return None
        parameter = model.parameters.get(target)
        if parameter is not None:
            return float(parameter.value)
        species = model.species.get(target)
        if species is not None:
            species_compartment = model.compartments.get(species.compartment or "")
            if species.compartment and (
                species_compartment is None
                or any(
                    rule.type == "assignment" and rule.variable == species.compartment
                    for rule in model.rules
                )
                or species.compartment in initial_assignment_targets
            ):
                return None
            volume = (
                float(species_compartment.size)
                if species_compartment is not None
                else 1.0
            )
            amount = float(species.initial_amount)
            concentration = float(species.initial_concentration)
            if species.has_only_substance_units:
                return amount if species.initial_amount_set else concentration * volume
            if species.initial_concentration_set:
                return concentration
            return amount / volume if volume != 0 else None
        compartment = model.compartments.get(target)
        if compartment is not None:
            return float(compartment.size)
        reference_values = [
            float(reference.stoichiometry)
            for reaction in model.reactions.values()
            for reference in (*reaction.reactants, *reaction.products)
            if reference.id == target and not reference.stoichiometry_math
        ]
        if reference_values and all(
            value == reference_values[0] for value in reference_values
        ):
            return reference_values[0]
        return None

    def initial_expression(
        expression: str, *, require_immutable_symbols: bool = False
    ) -> Optional[float]:
        expanded = inline_sbml_functions(expression, model.function_definitions)

        def resolve(identifier: str) -> Optional[float]:
            if identifier.lower() == "pi":
                return math.pi
            if identifier.lower() == "exponentiale":
                return math.e
            if require_immutable_symbols:
                if (
                    identifier in initial_assignment_targets
                    or identifier in event_targets
                ):
                    return None
                if any(rule.variable == identifier for rule in model.rules):
                    return None
                parameter = model.parameters.get(identifier)
                if parameter is not None:
                    return float(parameter.value) if parameter.constant else None
                compartment = model.compartments.get(identifier)
                if compartment is not None:
                    return float(compartment.size) if compartment.constant else None
                species = model.species.get(identifier)
                if species is not None:
                    return initial_value(identifier) if species.constant else None
                return None
            return initial_value(identifier)

        return fold_numeric(expanded, resolve)

    def affine_trajectory(target: str) -> Optional[Tuple[float, float]]:
        """Prove a target has an independent constant-rate trajectory."""
        initial = initial_value(target)
        if initial is None or not math.isfinite(initial):
            return None
        target_rules = [rule for rule in model.rules if rule.variable == target]
        if any(rule.type == "assignment" for rule in target_rules):
            return None
        if any(
            variable == target
            for event in model.events
            for assignment in event.assignments
            for variable, _expression in [_event_assignment(assignment)]
        ):
            return None

        rate_rule = [rule for rule in target_rules if rule.type == "rate"]
        if rate_rule:
            if len(rate_rule) != 1:
                return None
            derivative = inline_sbml_functions(
                str(rate_rule[0].math or ""), model.function_definitions
            )
            slope = initial_expression(derivative, require_immutable_symbols=True)
            return (initial, slope) if slope is not None else None

        species = model.species.get(target)
        if species is None:
            return None
        if species.constant or species.boundary_condition:
            return initial, 0.0
        if species.conversion_factor or model.conversion_factor:
            return None
        net_amount_rate = 0.0
        found = False
        for reaction in model.reactions.values():
            references = [
                reference
                for reference in (*reaction.reactants, *reaction.products)
                if reference.species == target
            ]
            if not references:
                continue
            if reaction.fast or reaction.conversion_factor:
                return None
            net_coefficient = 0.0
            for sign, side in (
                (-1.0, reaction.reactants),
                (1.0, reaction.products),
            ):
                for reference in side:
                    if reference.species != target:
                        continue
                    if reference.variable_stoichiometry:
                        return None
                    net_coefficient += sign * float(reference.stoichiometry)
            if net_coefficient == 0:
                continue
            law = reaction.kinetic_law
            expression = str(
                law.get("math", "")
                if isinstance(law, Mapping)
                else getattr(law, "math", "") or ""
            ).strip()
            if not expression:
                return None
            flux = initial_expression(expression, require_immutable_symbols=True)
            if flux is None or not math.isfinite(flux):
                return None
            net_amount_rate += net_coefficient * flux
            found = True
        if not found:
            # An unruled species with no net stoichiometric participation has
            # no state equation; its initial value is constant.
            return initial, 0.0
        if not species.has_only_substance_units:
            compartment = model.compartments.get(species.compartment or "")
            if (
                compartment is None
                or not compartment.constant
                or compartment.size == 0
                or any(rule.variable == species.compartment for rule in model.rules)
                or species.compartment in initial_assignment_targets
                or any(
                    variable == species.compartment
                    for event in model.events
                    for assignment in event.assignments
                    for variable, _expression in [_event_assignment(assignment)]
                )
            ):
                return None
            net_amount_rate /= float(compartment.size)
        return (initial, net_amount_rate) if math.isfinite(net_amount_rate) else None

    def fold_bounded_delays(expression: str) -> Tuple[str, int]:
        replacements: List[Tuple[int, int, str]] = []
        position = 0
        while (match := delay_call.search(expression, position)) is not None:
            opening = match.end() - 1
            depth = 1
            closing = opening + 1
            while closing < len(expression) and depth:
                if expression[closing] == "(":
                    depth += 1
                elif expression[closing] == ")":
                    depth -= 1
                closing += 1
            if depth:
                return expression, 0
            call_end = closing
            arguments = _split_arguments(expression[opening + 1 : closing - 1])
            if arguments is None or len(arguments) != 2:
                return expression, 0
            try:
                duration = initial_expression(
                    arguments[1], require_immutable_symbols=True
                )
            except (TypeError, ValueError):
                return expression, 0
            if duration is None or not math.isfinite(duration) or duration < 0:
                return expression, 0
            delayed_expression = arguments[0].strip()
            if duration == 0:
                replacements.append((match.start(), call_end, delayed_expression))
                position = call_end
                continue
            state_match = re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", delayed_expression
            )
            if 0 < duration < t_end and state_match:
                target = state_match.group(0)
                trajectory = affine_trajectory(target)
                if trajectory is not None:
                    initial, slope = trajectory
                    displacement = slope * duration
                    if math.isfinite(displacement):
                        replacement = (
                            f"if(time < {duration!r}, {initial!r}, "
                            f"({target} - {displacement!r}))"
                        )
                        replacements.append((match.start(), call_end, replacement))
                        position = call_end
                        continue
            if duration < t_end:
                return expression, 0
            value = initial_expression(delayed_expression)
            if value is None or not math.isfinite(value):
                return expression, 0
            delayed_symbols = set(
                re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", arguments[0])
            )
            if duration == t_end and any(
                symbol in event_targets
                and event.trigger_initial_value is False
                and any(
                    other_assignment.variable == symbol
                    for other_assignment in event.assignments
                )
                for event in model.events
                for symbol in delayed_symbols
            ):
                # At the single t=0 history boundary, an explicit false
                # trigger initialization may cause an immediate assignment.
                return expression, 0
            replacements.append((match.start(), call_end, repr(value)))
            position = call_end
        if not replacements:
            return expression, 0
        for start, end, value in reversed(replacements):
            expression = expression[:start] + value + expression[end:]
        return expression, len(replacements)

    lowered = 0
    for rule in model.rules:
        if not rule.math:
            continue
        rule.math, count = fold_bounded_delays(rule.math)
        lowered += count
    for function in model.function_definitions.values():
        expression = str(getattr(function, "math", "") or "")
        if expression:
            function.math, count = fold_bounded_delays(expression)
            lowered += count
    for assignment in model.initial_assignments:
        expression = str(getattr(assignment, "math", "") or "")
        if expression:
            assignment.math, count = fold_bounded_delays(expression)
            lowered += count
    for event in model.events:
        if event.trigger:
            event.trigger, count = fold_bounded_delays(event.trigger)
            lowered += count
        for assignment in event.assignments:
            variable, expression = _event_assignment(assignment)
            if not expression:
                continue
            folded, count = fold_bounded_delays(expression)
            if not count:
                continue
            if isinstance(assignment, dict):
                assignment["math"] = folded
            elif hasattr(assignment, "math"):
                assignment.math = folded
            lowered += count
    for reaction in model.reactions.values():
        law = reaction.kinetic_law
        expression = str(
            law.get("math", "")
            if isinstance(law, Mapping)
            else getattr(law, "math", "") or ""
        )
        if expression:
            folded, count = fold_bounded_delays(expression)
            if count:
                if isinstance(law, dict):
                    law["math"] = folded
                else:
                    law.math = folded
                lowered += count
        for reference in (*reaction.reactants, *reaction.products):
            expression = str(reference.stoichiometry_math or "")
            if not expression:
                continue
            folded, count = fold_bounded_delays(expression)
            if count:
                try:
                    value = float(folded)
                except ValueError:
                    continue
                if not math.isfinite(value):
                    continue
                reference.stoichiometry = value
                reference.stoichiometry_math = ""
                reference.stoichiometry_set = True
                reference.variable_stoichiometry = False
                lowered += count

    if not lowered:
        return 0
    _record_import_warning(
        model,
        "SBML delay calls with zero duration, bounded initial history, or "
        "provable affine-state history were lowered exactly for simulation "
        f"horizon t <= {t_end:g}.",
        category="delay",
        severity="info",
    )

    reaction_expressions = []
    for reaction in model.reactions.values():
        law = reaction.kinetic_law
        reaction_expressions.append(
            str(
                law.get("math", "")
                if isinstance(law, Mapping)
                else getattr(law, "math", "") or ""
            )
        )
    expressions = [
        *(str(rule.math or "") for rule in model.rules),
        *(str(function.math or "") for function in model.function_definitions.values()),
        *(str(assignment.math or "") for assignment in model.initial_assignments),
        *reaction_expressions,
        *(
            str(expression or "")
            for event in model.events
            for expression in (
                event.trigger,
                event.delay,
                event.priority,
                *(assignment.math for assignment in event.assignments),
            )
        ),
    ]
    if not any(
        re.search(r"\bdelay\s*\(", expression, re.IGNORECASE)
        for expression in expressions
    ):
        model.import_warnings = [
            warning
            for warning in model.import_warnings
            if not (
                warning.get("category") == "mathml"
                and "delay" in str(warning.get("message", "")).lower()
            )
        ]
    return lowered


def _lowerable_species_assignment_rules(
    model: SBMLModel,
) -> "OrderedDict[str, SBMLRule]":
    """Return dynamic species assignment rules that can be emitted as functions.

    A species assignment rule is algebraic rather than a population state.  A
    zero-argument BNGL function is an exact representation when the target is
    not an event target or part of an ambiguous or cyclic assignment-rule set.
    Reaction stoichiometry for algebraic targets is removed below: assignment
    rules, rather than reaction populations, own those species values.
    """

    candidates: "OrderedDict[str, SBMLRule]" = OrderedDict()
    duplicate_targets: Set[str] = set()
    event_targets = {
        str(getattr(assignment, "variable", "") or "")
        for event in model.events
        for assignment in event.assignments
        if getattr(assignment, "variable", None)
    }
    for rule in model.rules:
        variable = str(rule.variable or "")
        if (
            rule.type != "assignment"
            or not variable
            or variable not in model.species
            or not str(rule.math or "").strip()
            or getattr(rule, "math_from_empty_boolean", False)
        ):
            continue
        if variable in candidates:
            duplicate_targets.add(variable)
        else:
            candidates[variable] = rule

    for variable in duplicate_targets:
        candidates.pop(variable, None)

    candidates = OrderedDict(
        (
            variable,
            rule,
        )
        for variable, rule in candidates.items()
        if variable not in event_targets
    )
    if not candidates:
        return candidates

    # Assignment functions may reference one another.  Reject cycles as a
    # group; C++ function evaluation is intentionally not a cyclic algebraic
    # solver and must not recurse indefinitely on malformed input.
    dependencies: Dict[str, Set[str]] = {}
    for variable, rule in candidates.items():
        dependencies[variable] = {
            dependency
            for dependency in candidates
            if dependency != variable
            and (
                re.search(rf"\b{re.escape(dependency)}\b", rule.math)
                or re.search(
                    rf"\b{re.escape(standardize_name(dependency))}\b", rule.math
                )
            )
        }

    visiting: Set[str] = set()
    visited: Set[str] = set()
    cyclic: Set[str] = set()

    def visit(variable: str, path: Tuple[str, ...] = ()) -> None:
        if variable in visiting:
            if variable in path:
                cyclic.update(path[path.index(variable) :])
            else:
                cyclic.add(variable)
            return
        if variable in visited:
            return
        visiting.add(variable)
        for dependency in dependencies.get(variable, set()):
            visit(dependency, (*path, variable))
        visiting.remove(variable)
        visited.add(variable)

    for variable in candidates:
        visit(variable)
    for variable in cyclic:
        candidates.pop(variable, None)
    return candidates


def _update_event_translation_warning(model: SBMLModel, event_result: object) -> None:
    """Make the event diagnostic reflect the executable lowering result."""

    converted = int(getattr(event_result, "converted", 0) or 0)
    untranslated = list(getattr(event_result, "untranslated", []) or [])
    if not converted and not untranslated:
        if model.events:
            message = (
                f"{len(model.events)} SBML event(s) were proven not to fire; "
                "no scheduled actions are required."
            )
            for warning in getattr(model, "import_warnings", []) or []:
                if warning.get("category") != "event":
                    continue
                warning.message = message
                warning.severity = "info"
                warning.count = len(model.events)
                return
        return
    if untranslated:
        message = (
            f"{len(model.events)} SBML event(s) parsed; {converted} fixed-time "
            f"event(s) lowered to scheduled actions, while {len(untranslated)} "
            "state-dependent or non-constant event(s) remain untranslated."
        )
        severity = "dropped"
    else:
        message = (
            f"{converted} fixed-time, constant-valued SBML event(s) lowered to "
            "scheduled BNGL actions; trigger-time semantics are represented by "
            "explicit simulation phase boundaries."
        )
        severity = "info"
    for warning in getattr(model, "import_warnings", []) or []:
        if warning.get("category") != "event":
            continue
        warning.message = message
        warning.severity = severity
        warning.count = len(model.events)
        return


def _curated_parameter_value(model: SBMLModel, parameter_id: str, value: object) -> str:
    """Emit finite BNGL literals for SBML's non-finite parameter values."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        _record_import_warning(
            model,
            f'Parameter "{parameter_id}" has NaN value; emitted 0 as a finite '
            "BNGL approximation.",
            category="parameter",
            severity="approximated",
        )
        return "0"
    if math.isinf(number):
        return "-1e20" if number < 0 else "1e20"
    return _number(number)


def _inline_reaction_fluxes(
    expression: str,
    model: SBMLModel,
    assignment_rule_variables: Set[str],
    observable_converted_rules: Set[str],
    species_with_conc_functions: Set[str],
    sbml_to_bngl_id: Mapping[str, str],
    replace_loc_params: bool = True,
    exclude_reaction_id: Optional[str] = None,
) -> str:
    """Inline reaction IDs used as SBML ``rateOf`` expressions."""

    if not model.reactions:
        return expression
    defined = set(model.parameters) | set(model.species)
    defined.update(
        standardize_name(name) for name in (*model.parameters, *model.species)
    )
    defined.update(assignment_rule_variables)
    defined.update(standardize_name(name) for name in assignment_rule_variables)
    for function_id, function in model.function_definitions.items():
        defined.add(function_id)
        defined.add(standardize_name(function_id))
        if getattr(function, "name", ""):
            defined.add(function.name)
            defined.add(standardize_name(function.name))

    cache: Dict[str, Optional[str]] = {}

    reaction_aliases: Dict[str, tuple[str, ...]] = {
        str(reaction_id): (
            str(reaction_id),
            standardize_name(str(reaction_id)),
        )
        for reaction_id in model.reactions
    }

    def reaction_flux(reaction_id: str, reaction: SBMLReaction) -> Optional[str]:
        if reaction_id in cache:
            return cache[reaction_id]
        math_expression = get_kinetic_math(reaction.kinetic_law)
        if not math_expression.strip():
            cache[reaction_id] = _MISSING_KINETIC_RATE_FALLBACK
            return _MISSING_KINETIC_RATE_FALLBACK
        kinetic_law = reaction.kinetic_law
        local_parameters = (
            kinetic_law.get("localParameters", [])
            if isinstance(kinetic_law, Mapping)
            else getattr(kinetic_law, "local_parameters", [])
        )
        for parameter in local_parameters or []:
            parameter_id = getattr(parameter, "id", None)
            if parameter_id is None and isinstance(parameter, Mapping):
                parameter_id = parameter.get("id")
            parameter_value = getattr(parameter, "value", None)
            if parameter_value is None and isinstance(parameter, Mapping):
                parameter_value = parameter.get("value")
            if parameter_id:
                replacement = (
                    _curated_parameter_value(model, str(parameter_id), parameter_value)
                    if replace_loc_params
                    else standardize_name(f"{reaction_id}_{parameter_id}")
                )
                math_expression = re.sub(
                    rf"\b{re.escape(str(parameter_id))}\b",
                    replacement,
                    math_expression,
                )
        try:
            math_expression = extend_function(
                math_expression, {}, model.function_definitions
            )
            flux = bngl_function(
                math_expression,
                reaction_id,
                [],
                list(model.compartments),
                assignment_rule_variables=assignment_rule_variables,
                observable_converted_rules=observable_converted_rules,
                species_with_conc_functions=species_with_conc_functions,
                sbml_to_bngl_id=sbml_to_bngl_id,
            )
        except (TypeError, ValueError, re.error):
            flux = None
        cache[reaction_id] = flux
        return flux

    result = expression
    for _ in range(4):
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", result))
        candidates = [
            (reaction_id, reaction)
            for reaction_id, reaction in model.reactions.items()
            if not (
                exclude_reaction_id and str(reaction_id) == str(exclude_reaction_id)
            )
            and not (
                str(reaction_id) in defined
                or standardize_name(str(reaction_id)) in defined
            )
            and any(alias in tokens for alias in reaction_aliases[str(reaction_id)])
        ]
        if not candidates:
            break
        changed = False
        for reaction_id, reaction in candidates:
            reaction_id = str(reaction_id)
            flux = reaction_flux(reaction_id, reaction)
            if flux is None:
                continue
            for candidate in (reaction_id, standardize_name(reaction_id)):
                pattern = rf"\b{re.escape(candidate)}\b(?!\s*\()"
                result, count = re.subn(pattern, lambda _: f"({flux})", result)
                if count:
                    changed = True
                    break
        if not changed:
            break
    return result


def _conversion_factor_for_species(species_id: str, model: SBMLModel) -> Optional[str]:
    """Resolve the effective SBML conversion factor for one species."""

    species = model.species.get(species_id)
    factor_id = (getattr(species, "conversion_factor", None) if species else None) or (
        getattr(model, "conversion_factor", None) or None
    )
    if factor_id is None:
        return None
    parameter = model.parameters.get(factor_id)
    value = getattr(parameter, "value", None) if parameter is not None else None
    if isinstance(parameter, Mapping):
        value = parameter.get("value")
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = None
    if numeric_value is not None and numeric_value == numeric_value:
        return _number(numeric_value)
    return standardize_name(factor_id)


def _mixed_conversion_factor_expressions(
    reaction: SBMLReaction, model: SBMLModel
) -> Optional[Dict[str, Optional[str]]]:
    """Return per-species factors when one SBML flux needs multiple scalars."""

    expressions: "OrderedDict[str, Optional[str]]" = OrderedDict()
    for reference in [*reaction.reactants, *reaction.products]:
        if reference.species == "EmptySet":
            continue
        species_id = str(reference.species)
        expressions[species_id] = _conversion_factor_for_species(species_id, model)
    if len(set(expressions.values())) <= 1:
        return None
    return dict(expressions)


def _conversion_factor_for_reaction(
    reaction: SBMLReaction, model: SBMLModel
) -> Optional[str]:
    """Resolve one BNGL-wide scalar, or report an unrepresentable mixed flux."""

    factors = _mixed_conversion_factor_expressions(reaction, model)
    if factors is not None:
        _record_import_warning(
            model,
            f'Reaction "{reaction.id}" has species with differing '
            "conversionFactors; a single BNGL rule cannot apply different "
            "scalars per species, so the factor was not applied.",
            severity="dropped",
        )
        return None
    for factor in [
        _conversion_factor_for_species(str(reference.species), model)
        for reference in [*reaction.reactants, *reaction.products]
        if reference.species != "EmptySet"
    ]:
        if factor is not None:
            return factor
    return None


def write_parameters(
    model: SBMLModel,
    assignment_variables: Optional[Set[str]] = None,
    include_local_parameters: bool = False,
) -> List[str]:
    assignment_variables = assignment_variables or set()
    lines = ["__Avogadro__ 1"]
    for compartment_id, compartment in model.compartments.items():
        size = _numeric_value(compartment.size)
        lines.append(
            f"__compartment_{standardize_name(compartment_id)}__ "
            f"{_number(size if size is not None else 1)}"
        )
    for parameter_id, parameter in model.parameters.items():
        name = standardize_name(parameter_id)
        # These symbols are emitted from compartments and are already present
        # in the BNGL preamble.  Re-emitting them from an SBML round-trip
        # model creates duplicate parameter declarations and an invalid
        # compiled model.
        if (
            name in assignment_variables
            or name == "__Avogadro__"
            or name.startswith("__compartment_")
        ):
            continue
        lines.append(
            f"{name} {_curated_parameter_value(model, parameter_id, parameter.value)}"
        )
    if include_local_parameters:
        for name, value in _local_parameter_entries(model):
            lines.append(f"{name} {_curated_parameter_value(model, name, value)}")
    return lines


def write_compartments(model: SBMLModel) -> List[str]:
    lines = []
    for compartment_id, compartment in model.compartments.items():
        dimension = max(1, int(compartment.spatial_dimensions or 3))
        size = _numeric_value(compartment.size)
        line = (
            f"{standardize_name(compartment_id)} {dimension} "
            f"{_number(size if size is not None else 1)}"
        )
        if compartment.outside and compartment.outside in model.compartments:
            parent = model.compartments[compartment.outside]
            if int(parent.spatial_dimensions or 3) == dimension + 1:
                line += " " + standardize_name(compartment.outside)
        lines.append(line)
    return lines


def write_molecule_types(molecule_types: Sequence[Molecule]) -> List[str]:
    lines = []
    for molecule in molecule_types:
        # Molecule type declarations define available sites/states, not a
        # concrete complex.  Remove instance bond labels before writing them.
        declaration = molecule.copy()
        for component in declaration.components:
            component.bonds = []
        # Pattern output normalizes hyphens across molecule, component, and
        # state identifiers. Apply the same rule here so the declared site
        # schema accepts every emitted pattern.
        value = declaration.str2().replace("-", "_").split("@", 1)[0]
        if "(" not in value:
            value += "()"
        lines.append(value if value.startswith("M_") else "M_" + value)
    return sorted(dict.fromkeys(lines))


def _add_seed_symbol(symbols: Dict[str, float], name: object, value: object) -> bool:
    number = _numeric_value(value)
    if number is None or name is None:
        return False
    text = str(name)
    symbols[text] = number
    symbols[standardize_name(text)] = number
    return True


def _set_seed_symbol_if_changed(
    symbols: Dict[str, float], name: object, value: object
) -> bool:
    """Set a resolved value and report whether it changed."""

    number = _numeric_value(value)
    if number is None or name is None:
        return False
    text = str(name)
    aliases = (text, standardize_name(text))
    changed = any(alias not in symbols or symbols[alias] != number for alias in aliases)
    _add_seed_symbol(symbols, text, number)
    return changed


def _substitute_seed_symbols(
    expression: str, symbols: Mapping[str, float]
) -> Optional[float]:
    result = convert_math_expression(expression)
    for _ in range(8):
        changed = False
        for symbol, value in list(symbols.items()):
            escaped = re.escape(symbol)
            result, call_count = re.subn(
                rf"\b{escaped}\s*\(\s*\)", _number(value), result
            )
            result, bare_count = re.subn(
                rf"\b{escaped}\b(?!\s*\()", _number(value), result
            )
            changed = changed or bool(call_count or bare_count)
        if not changed:
            break
    return _evaluate_arithmetic(result)


def _seed_symbol_values(
    model: SBMLModel, seed_species: Sequence[SeedSpeciesEntry]
) -> Dict[str, float]:
    """Resolve numeric SBML values needed by expression-valued seed species."""

    symbols: Dict[str, float] = {}
    _add_seed_symbol(symbols, "__Avogadro__", 1)
    # SBML initial assignments are evaluated at t=0.  Treat the built-in time
    # symbol as that initial value so expression-valued seeds become numeric
    # BNGL seed amounts instead of invalid runtime expressions.
    _add_seed_symbol(symbols, "time", 0)
    for parameter_id, parameter in model.parameters.items():
        _add_seed_symbol(symbols, parameter_id, getattr(parameter, "value", None))
    for compartment_id, compartment in model.compartments.items():
        size = getattr(compartment, "size", None)
        _add_seed_symbol(symbols, compartment_id, size)
        _add_seed_symbol(
            symbols,
            f"__compartment_{standardize_name(compartment_id)}__",
            size,
        )

    species_ids = set(model.species)
    standardized_species_ids = {
        standardize_name(species_id) for species_id in species_ids
    }

    def is_species(identifier: object) -> bool:
        value = str(identifier or "")
        return (
            value in species_ids or standardize_name(value) in standardized_species_ids
        )

    def add_resolved(identifier: object, expression: object) -> bool:
        if identifier is None or not expression:
            return False
        value = _substitute_seed_symbols(str(expression), symbols)
        return _add_seed_symbol(symbols, identifier, value)

    for _ in range(12):
        changed = False
        # Initial assignments supersede a parameter's literal value.  Resolve
        # them before constant functions and assignment rules, and allow a few
        # passes for dependencies between initial assignments.
        for assignment in model.initial_assignments:
            symbol = getattr(assignment, "symbol", "")
            value = _substitute_seed_symbols(
                str(getattr(assignment, "math", "") or ""), symbols
            )
            changed = _set_seed_symbol_if_changed(symbols, symbol, value) or changed

        for function_id, function in model.function_definitions.items():
            if getattr(function, "arguments", None):
                continue
            candidates = [function_id, getattr(function, "name", "") or function_id]
            if any(
                candidate in symbols or standardize_name(candidate) in symbols
                for candidate in candidates
            ):
                continue
            value = _substitute_seed_symbols(
                str(getattr(function, "math", "") or ""), symbols
            )
            if value is not None:
                for candidate in candidates:
                    changed = _add_seed_symbol(symbols, candidate, value) or changed

        for rule in model.rules:
            variable = getattr(rule, "variable", None)
            if not variable or getattr(rule, "type", "") != "assignment":
                continue
            if is_species(variable):
                continue
            if variable in symbols or standardize_name(variable) in symbols:
                continue
            changed = add_resolved(variable, getattr(rule, "math", "")) or changed

        for seed in seed_species:
            identifier = seed.sbml_id
            if identifier in symbols or standardize_name(identifier) in symbols:
                continue
            value = _substitute_seed_symbols(str(seed.concentration), symbols)
            if value is None:
                continue
            changed = _add_seed_symbol(symbols, identifier, value) or changed
            species = model.species.get(identifier)
            compartment_id = getattr(species, "compartment", "") if species else ""
            compartment = model.compartments.get(compartment_id)
            size = _numeric_value(getattr(compartment, "size", None))
            if size not in (None, 0):
                _add_seed_symbol(
                    symbols,
                    f"_c_{standardize_name(identifier)}",
                    value / size,
                )
        if not changed:
            break
    return symbols


def _map_seed_identifiers(expression: str, model: SBMLModel) -> str:
    """Map known raw SBML names to the identifiers emitted in BNGL sections."""

    result = expression
    for compartment_id in model.compartments:
        result = re.sub(
            rf"\b{re.escape(compartment_id)}\b",
            f"__compartment_{standardize_name(compartment_id)}__",
            result,
        )
    for parameter_id in model.parameters:
        result = re.sub(
            rf"\b{re.escape(parameter_id)}\b",
            standardize_name(parameter_id),
            result,
        )
    for function_id, function in model.function_definitions.items():
        emitted = standardize_name(getattr(function, "name", "") or function_id)
        result = re.sub(rf"\b{re.escape(function_id)}\b", emitted, result)
    for rule in model.rules:
        variable = getattr(rule, "variable", None)
        if variable:
            result = re.sub(
                rf"\b{re.escape(variable)}\b",
                standardize_name(variable),
                result,
            )
    return result


def _format_seed_pattern(pattern: str, fixed: bool) -> str:
    if not fixed:
        return pattern
    compartment, separator, molecule_pattern = pattern.partition(":")
    if separator and pattern.startswith("@"):
        return f"{compartment}:${molecule_pattern}"
    return f"${pattern}"


def write_seed_species(
    seed_species: Sequence[SeedSpeciesEntry],
    sct: SpeciesCompositionTable,
    model: SBMLModel,
) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    lines: List[str] = []
    sbml_to_pattern: Dict[str, str] = OrderedDict()
    pattern_to_id: Dict[str, str] = OrderedDict()
    # Playground writeSeedSpecies coalesces identical patterns while retaining
    # separate fixed and dynamic seed declarations.
    grouped: "OrderedDict[Tuple[bool, str], Tuple[str, object]]" = OrderedDict()
    seed_symbols = _seed_symbol_values(model, seed_species)
    rate_rule_targets = {
        str(getattr(rule, "variable", "") or "")
        for rule in model.rules
        if getattr(rule, "type", "") == "rate"
    }
    species_assignment_targets = set(_lowerable_species_assignment_rules(model))
    for seed in seed_species:
        if seed.sbml_id in species_assignment_targets:
            # Assignment-rule species are algebraic outputs, not independent
            # BNGL populations.  Their values are emitted as zero-argument
            # functions below.
            continue
        pattern = _pattern(seed.species, seed.compartment)
        if not pattern:
            continue
        # Seed sections use the prefix form, which is accepted by both the
        # BNG3 parser and the historical BNG2 writer.
        if seed.compartment:
            pattern = (
                "@"
                + standardize_name(seed.compartment)
                + ":"
                + pattern.replace("@" + standardize_name(seed.compartment), "")
            )
        source_species = model.species.get(seed.sbml_id)
        fixed = bool(
            source_species
            and seed.sbml_id not in rate_rule_targets
            and (source_species.constant or source_species.boundary_condition)
        )
        concentration = seed.concentration
        if isinstance(concentration, str):
            converted = convert_math_expression(concentration)
            folded = _substitute_seed_symbols(converted, seed_symbols)
            concentration = (
                _number(folded)
                if folded is not None
                else _map_seed_identifiers(converted, model)
            )
        key = (fixed, pattern)
        if key not in grouped:
            grouped[key] = (pattern, concentration)
        sbml_to_pattern[seed.sbml_id] = pattern
        pattern_to_id.setdefault(pattern, seed.sbml_id)
        if fixed:
            # Accept the historical prefix form and the standard compartment
            # form returned in the emitted seed block.
            pattern_to_id.setdefault(f"${pattern}", seed.sbml_id)
            pattern_to_id.setdefault(
                _format_seed_pattern(pattern, fixed=True), seed.sbml_id
            )
    for (fixed, _group_pattern), (pattern, concentration) in grouped.items():
        lines.append(f"{_format_seed_pattern(pattern, fixed)} {concentration}")
    return lines, sbml_to_pattern, pattern_to_id


def write_observables(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    species_to_pattern: Mapping[str, str],
) -> Tuple[List[str], Dict[str, str]]:
    lines = []
    observable_map: Dict[str, str] = OrderedDict()
    used = set()
    species_assignment_targets = set(_lowerable_species_assignment_rules(model))
    for species_id, species in model.species.items():
        if species_id in species_assignment_targets:
            # The source species is algebraically defined; exposing its
            # independent seed population would produce a second, divergent
            # state variable in the generated BNGL network.
            continue
        # Expressions are translated from SBML identifiers, not display
        # names.  Keep observable names on that same key so an SBML species
        # such as id="S", name="Substrate" is still referenced as S_amt.
        name = standardize_name(species_id)
        if name in used:
            name = standardize_name(species_id)
        while name in used:
            name += "_id"
        used.add(name)
        entry = sct.entries.get(species_id)
        pattern = species_to_pattern.get(species_id)
        if not pattern and entry is not None:
            pattern = _pattern(entry.structure, species.compartment)
        if not pattern:
            pattern = "M_" + standardize_name(species_id) + "()"
            if species.compartment:
                pattern = f"@{standardize_name(species.compartment)}:{pattern}"
        # Keep both amount and concentration-facing observable names.  The
        # amount alias is used by saturation laws; the plain name remains the
        # historical/public observable used by callers.
        lines.append(f"Species {name}_amt {pattern} # {species_id} amount")
        lines.append(f"Species {name} {pattern} # {species_id}")
        observable_map[species_id] = name

    sum_species_ids = {
        match.group(1)
        for reaction in model.reactions.values()
        for match in _MULTI_SUM_TOKEN.finditer(get_kinetic_math(reaction.kinetic_law))
    }
    for species_id in sorted(sum_species_ids):
        pattern = model.multi_species_patterns.get(species_id)
        if not pattern:
            continue
        lines.append(f"Molecules __multi_sum_{standardize_name(species_id)} {pattern}")

    # A simple assignment rule such as ``total = A + 2 * B`` is a BNGL
    # observable, not a dynamic function.  Preserve this losslessly when all
    # terms resolve to imported species patterns; more complex rules continue
    # through the function writer below.
    for rule in model.rules:
        if rule.type != "assignment" or not rule.variable or not rule.math:
            continue
        if rule.variable in model.species:
            # An SBML species assignment rule defines an algebraic state.  A
            # BNGL Species declaration is dynamic, so turning this into a
            # same-named function/observable would silently change semantics.
            continue
        # The C++ SBML writer represents each imported observable as an
        # assignment rule (for example ``S1_amt = S1``).  These are already
        # reconstructed by the species loop above; treating them as new
        # observables would manufacture names such as ``S1_amt_amt`` on the
        # next import and make the round-trip BNGL invalid.
        variable = standardize_name(rule.variable)
        math_name = standardize_name(rule.math.strip())
        if math_name in {
            standardize_name(species_id) for species_id in model.species
        } and variable in {math_name, f"{math_name}_amt"}:
            continue
        if re.search(r"[/^()]", rule.math):
            continue
        pattern_counts: Dict[str, int] = OrderedDict()
        rule_compartment = ""
        for term in rule.math.split("+"):
            term = term.strip()
            if not term:
                continue
            coefficient = 1
            species_id = term
            match = re.fullmatch(r"(\d+)\s*\*\s*(\S+)", term)
            if match:
                coefficient, species_id = int(match.group(1)), match.group(2)
            else:
                match = re.fullmatch(r"(\S+)\s*\*\s*(\d+)", term)
                if match:
                    species_id, coefficient = match.group(1), int(match.group(2))
            if re.fullmatch(r"\d+(?:\.\d+)?", species_id):
                continue
            pattern = species_to_pattern.get(species_id)
            species = model.species.get(species_id)
            if not pattern:
                entry = sct.entries.get(species_id)
                if entry is not None and species is not None:
                    pattern = _pattern(entry.structure, species.compartment)
            if not pattern:
                pattern_counts.clear()
                break
            pattern_counts[pattern] = max(pattern_counts.get(pattern, 0), coefficient)
            if species is not None and species.compartment and not rule_compartment:
                rule_compartment = species.compartment
        if not pattern_counts:
            continue
        name = standardize_name(rule.variable)
        # Replace every prior observable with these names.  A round-tripped
        # SBML network can contain the same assignment rule both as a
        # ``Species`` projection and as a generated ``Molecules`` projection;
        # leaving both declarations makes the BNGL model invalid because
        # observable names must be unique.
        names_to_replace = {name, f"{name}_amt"}
        lines = [
            line
            for line in lines
            if not any(
                line.startswith(f"{kind} {candidate} ")
                for kind in ("Species", "Molecules")
                for candidate in names_to_replace
            )
        ]
        expanded = []
        for pattern, coefficient in pattern_counts.items():
            expanded.extend([pattern] * coefficient)
        pattern_string = " ".join(expanded)
        lines.append(f"Molecules {name} {pattern_string}")
        if not name.endswith("_amt"):
            lines.append(f"Molecules {name}_amt {pattern_string}")
    return lines, observable_map


def _rewrite_zero_argument_calls(expression: str, names: Iterable[str]) -> str:
    result = expression
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", result))
    for name in names:
        if str(name) not in tokens:
            continue
        result = re.sub(rf"\b{re.escape(name)}\b(?!\s*\()", f"{name}()", result)
    return result


def _inline_constant_function_calls(
    function_lines: Sequence[str], parameter_names: Iterable[str]
) -> List[str]:
    """Inline constant zero-argument calls before BNG2 reorders functions."""

    metadata_prefixes = (
        "__rate_rule_pos__",
        "__rate_rule_neg__",
        "__rate_rule__",
        "__assign_rule__",
    )

    def canonical_name(name: str) -> str:
        for prefix in metadata_prefixes:
            if name.startswith(prefix):
                return name[len(prefix) :]
        return name

    definition_pattern = re.compile(r"^(\s*)([A-Za-z_]\w*)\(\)\s*=\s*(.+?)\s*$")
    definitions: Dict[str, str] = {}
    for line in function_lines:
        match = definition_pattern.match(line)
        if match is None:
            continue
        name = match.group(2)
        if name.startswith("__rate_rule_"):
            continue
        definitions.setdefault(canonical_name(name), match.group(3))
    if not definitions:
        return list(function_lines)

    math_names = {
        "exp",
        "ln",
        "log",
        "log10",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "sqrt",
        "abs",
        "if",
        "pow",
        "power",
        "floor",
        "ceil",
        "min",
        "max",
        "rint",
        "piecewise",
        "and",
        "or",
        "not",
        "time",
    }
    parameter_names = set(parameter_names)
    constant_values: Dict[str, str] = {}

    def inline_known(body: str) -> str:
        result = body
        for _ in range(8):
            changed = False
            for name, value in constant_values.items():
                result, count = re.subn(
                    rf"\b{re.escape(name)}\(\)", f"({value})", result
                )
                changed = changed or count > 0
            if not changed:
                break
        return result

    def constant_body(body: str) -> Optional[str]:
        if re.search(r"_c_|_amt|\btime\s*\(", body):
            return None
        result = inline_known(body)
        for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(\s*\)", result):
            if match.group(1) not in math_names:
                return None
        for match in re.finditer(r"\b([A-Za-z_]\w*)\b(?!\s*\()", result):
            name = match.group(1)
            if name not in math_names and name not in parameter_names:
                return None
        return result

    for _ in range(8):
        changed = False
        for name, body in definitions.items():
            if name in constant_values:
                continue
            value = constant_body(body)
            if value is not None:
                constant_values[name] = value
                changed = True
        if not changed:
            break
    if not constant_values:
        return list(function_lines)

    rewritten: List[str] = []
    for line in function_lines:
        match = definition_pattern.match(line)
        if match is None:
            rewritten.append(line)
            continue
        name = canonical_name(match.group(2))
        body = constant_values.get(name, inline_known(match.group(3)))
        rewritten.append(f"{match.group(1)}{match.group(2)}() = {body}")
    return rewritten


def _map_compartment_references(expression: str, model: SBMLModel) -> str:
    """Map bare SBML compartment IDs to emitted BNGL volume parameters."""

    result = expression
    for compartment_id in model.compartments:
        result = re.sub(
            rf"\b{re.escape(str(compartment_id))}\b",
            f"__compartment_{standardize_name(str(compartment_id))}__",
            result,
        )
    return result


def _ordered_assignment_rules(rules: Sequence[object]) -> List[object]:
    """Order assignment rules after their referenced assignment variables."""

    assignment_rules = [
        rule
        for rule in rules
        if getattr(rule, "type", "") == "assignment" and getattr(rule, "variable", None)
    ]
    if len(assignment_rules) < 2:
        return assignment_rules

    by_name = {str(rule.variable): rule for rule in assignment_rules}
    if len(by_name) != len(assignment_rules):
        return assignment_rules
    ordered: List[object] = []
    visited: Set[str] = set()
    visiting: Set[str] = set()
    cycle = False

    def visit(name: str) -> None:
        nonlocal cycle
        if name in visited:
            return
        if name in visiting:
            cycle = True
            return
        visiting.add(name)
        expression = str(getattr(by_name[name], "math", "") or "")
        for dependency in by_name:
            if dependency == name:
                continue
            raw_match = re.search(rf"\b{re.escape(dependency)}\b", expression)
            standardized = standardize_name(dependency)
            standardized_match = re.search(
                rf"\b{re.escape(standardized)}\b", expression
            )
            if raw_match or standardized_match:
                visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(by_name[name])

    for rule in assignment_rules:
        visit(str(rule.variable))
    if cycle:
        return assignment_rules
    return ordered


def _assignment_rules_for_writer(model: SBMLModel) -> List[object]:
    """Build source-shaped assignment rules, including non-species initial assignments."""

    rules = [
        rule
        for rule in model.rules
        if getattr(rule, "type", "") == "assignment" and getattr(rule, "variable", None)
    ]
    existing = {standardize_name(str(rule.variable)) for rule in rules}
    species_names = {standardize_name(str(species_id)) for species_id in model.species}
    for initial_assignment in getattr(model, "initial_assignments", []) or []:
        symbol = str(getattr(initial_assignment, "symbol", "") or "")
        if not symbol:
            continue
        standardized = standardize_name(symbol)
        if standardized in species_names or standardized in existing:
            continue
        rules.append(
            SBMLRule(
                type="assignment",
                variable=symbol,
                math=str(getattr(initial_assignment, "math", "") or ""),
            )
        )
        existing.add(standardized)
    return rules


def _rewrite_assignment_rule_references(
    expression: str,
    assignment_rule_variables: Iterable[str],
    rate_rule_variables: Optional[Set[str]] = None,
) -> str:
    """Emit assignment functions and rate-rule state observables correctly."""

    result = expression
    rate_rule_variables = rate_rule_variables or set()
    rate_aliases = {
        alias
        for variable in rate_rule_variables
        for alias in (str(variable), standardize_name(str(variable)))
    }
    rate_names = sorted(rate_aliases, key=len, reverse=True)
    for name in rate_names:
        result = re.sub(
            rf"\b{re.escape(name)}\b(?:\s*\(\s*\))?",
            f"{standardize_name(name)}_amt",
            result,
        )
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", result))
    names = sorted(
        {
            str(name)
            for name in assignment_rule_variables
            if str(name)
            and standardize_name(str(name)) not in rate_aliases
            and str(name) not in rate_aliases
        },
        key=len,
        reverse=True,
    )
    for name in names:
        if name not in tokens and standardize_name(name) not in tokens:
            continue
        result = re.sub(
            rf"\b{re.escape(name)}\b(?!\s*\()",
            f"{standardize_name(name)}()",
            result,
        )
    return result


def write_functions(
    model: SBMLModel,
    synthetic_rate_rule_variables: Optional[Set[str]] = None,
    skip_assignment_rules: Optional[Set[str]] = None,
    keep_parameterized: bool = False,
    replace_loc_params: bool = True,
) -> List[str]:
    lines = []
    zero_argument_functions = []
    emitted_names: Set[str] = set()
    synthetic_rate_rule_variables = synthetic_rate_rule_variables or set()
    skip_assignment_rules = skip_assignment_rules or set()
    assignment_rules = _assignment_rules_for_writer(model)
    lowerable_species_assignment_rules = _lowerable_species_assignment_rules(model)
    lowerable_species_assignment_variables = {
        alias
        for variable in lowerable_species_assignment_rules
        for alias in (variable, standardize_name(variable))
    }
    synthetic_names = {
        alias
        for variable in synthetic_rate_rule_variables
        for alias in (str(variable), standardize_name(variable))
    }
    # A non-species initial assignment may target the same symbol as a
    # synthesized rate-rule state.  That assignment supplies the initial
    # amount, not a second dynamic BNGL function for the state variable.
    assignment_rules = [
        rule
        for rule in assignment_rules
        if standardize_name(str(rule.variable)) not in synthetic_names
    ]
    species_assignment_variables = {
        str(rule.variable)
        for rule in assignment_rules
        if rule.variable and str(rule.variable) in model.species
    }
    assignment_rule_variables = {
        rule.variable
        for rule in assignment_rules
        if rule.variable and str(rule.variable) not in species_assignment_variables
    }
    assignment_rule_variables.update(
        rule.variable for rule in model.rules if rule.variable and rule.type == "rate"
    )
    assignment_rule_variables.update(
        standardize_name(rule.variable)
        for rule in assignment_rules
        if rule.variable and str(rule.variable) not in species_assignment_variables
    )
    assignment_rule_variables.update(
        standardize_name(rule.variable)
        for rule in model.rules
        if rule.variable and rule.type == "rate"
    )
    assignment_rule_variables.update(lowerable_species_assignment_variables)
    rate_rule_variables = {
        standardize_name(rule.variable)
        for rule in model.rules
        if rule.variable and rule.type == "rate"
    }
    function_name_map = OrderedDict(
        (
            str(function_id),
            _sanitize_function_identifier(str(function_id)),
        )
        for function_id in model.function_definitions
    )
    assignment_rule_names = {
        standardize_name(str(rule.variable))
        for rule in assignment_rules
        if rule.variable and str(rule.variable) not in species_assignment_variables
    }
    assignment_rule_parameter_ids = {
        str(rule.variable)
        for rule in assignment_rules
        if rule.variable and str(rule.variable) not in species_assignment_variables
    }
    assignment_rule_parameter_ids.update(
        standardize_name(str(rule.variable))
        for rule in assignment_rules
        if rule.variable and str(rule.variable) not in species_assignment_variables
    )
    species_map = {
        alias: species_id
        for species_id in model.species
        if species_id not in lowerable_species_assignment_rules
        for alias in (species_id, standardize_name(species_id))
    }
    for variable in synthetic_rate_rule_variables:
        # Synthetic rate-rule state species use the SBML variable as their
        # lookup key, while their generated molecule pattern is carried by
        # the observable/seed maps in generate_bngl().
        species_map[variable] = variable
        species_map[standardize_name(variable)] = variable
    concentration_names = {
        standardize_name(species_id)
        for species_id, species in model.species.items()
        if (
            not species.has_only_substance_units
            and standardize_name(species_id)
            not in {
                standardize_name(variable)
                for variable in _lowerable_species_assignment_rules(model)
            }
        )
    }

    # SBML species are amount-valued in the BNGL observable block.  The
    # concentration helper mirrors the Playground writer and is required for
    # rational/nonlinear kinetic laws in compartments with volume != 1.
    for species_id, species in model.species.items():
        name = standardize_name(species_id)
        if species_id in lowerable_species_assignment_rules:
            continue
        function_name = "_c_" + name
        if function_name in assignment_rule_names:
            # Preserve an explicit SBML assignment rule instead of emitting
            # a second helper with the same BNGL function name.
            continue
        if function_name in emitted_names:
            continue
        emitted_names.add(function_name)
        if species.has_only_substance_units or not species.compartment:
            body = name
        else:
            body = f"{name} / __compartment_{standardize_name(species.compartment)}__"
        lines.append(f"{function_name}() = {body}")

    for function_id, function in model.function_definitions.items():
        name = function_name_map.get(
            str(function_id), _sanitize_function_identifier(str(function_id))
        )
        if function.arguments and not keep_parameterized:
            # BNG2/BNGL function blocks do not consistently support
            # argument-taking SBML definitions.  Inline those definitions at
            # call sites, as the Playground writer does.
            continue
        argument_names = []
        body = function.math
        for raw_function_name, safe_function_name in function_name_map.items():
            if raw_function_name == safe_function_name:
                continue
            body = re.sub(
                rf"\b{re.escape(raw_function_name)}\b(?=\s*\()",
                safe_function_name,
                body,
            )
        for index, argument in enumerate(function.arguments):
            base = _sanitize_function_identifier(argument or f"arg{index + 1}")
            safe = f"_farg{index}_{base}"
            argument_names.append(safe)
            if argument and argument != safe:
                body = re.sub(rf"\b{re.escape(argument)}\b", safe, body)
        args = ", ".join(argument_names)
        body = _map_compartment_references(convert_math_expression(body), model)
        lines.append(f"{name}({args}) = {body}")
        if not function.arguments:
            zero_argument_functions.append(name)
        emitted_names.add(name)

    # A dynamic SBML assignment rule targeting a species is an algebraic
    # value, not an independently evolving BNGL population.  BNGL functions
    # preserve that value exactly for reaction laws and for the C++ SBML
    # writer, which re-emits them as native assignment rules.
    for variable, rule in lowerable_species_assignment_rules.items():
        body = _inline_reaction_fluxes(
            rule.math,
            model,
            assignment_rule_variables,
            set(),
            concentration_names,
            species_map,
            replace_loc_params,
        )
        body = extend_function(body, {}, model.function_definitions)
        body = bngl_function(
            body,
            variable,
            [],
            list(model.compartments),
            assignment_rule_variables=assignment_rule_variables,
            species_with_conc_functions=concentration_names,
            sbml_to_bngl_id=species_map,
            rate_rule_variables=rate_rule_variables,
        )
        body = _map_compartment_references(convert_math_expression(body), model)
        name = standardize_name(variable)
        lines.append(f"{name}() = {body}")
        emitted_names.add(name)

    emitted_assignment_rules: Set[str] = set()
    for rule in _ordered_assignment_rules(assignment_rules):
        rule_name = standardize_name(rule.variable)
        if (
            str(rule.variable) in species_assignment_variables
            or rule.variable in skip_assignment_rules
            or rule_name in skip_assignment_rules
            or rule_name in emitted_assignment_rules
        ):
            continue
        emitted_assignment_rules.add(rule_name)
        body = extend_function(
            _inline_reaction_fluxes(
                rule.math,
                model,
                assignment_rule_variables,
                skip_assignment_rules,
                concentration_names,
                species_map,
                replace_loc_params,
            ),
            {
                parameter_id: parameter.value
                for parameter_id, parameter in model.parameters.items()
                if str(parameter_id) not in assignment_rule_parameter_ids
                and standardize_name(str(parameter_id))
                not in assignment_rule_parameter_ids
            },
            model.function_definitions,
        )
        body = _map_compartment_references(convert_math_expression(body), model)
        body = _rewrite_assignment_rule_references(
            body,
            assignment_rule_variables,
            rate_rule_variables=rate_rule_variables,
        )
        body = _rewrite_zero_argument_calls(body, zero_argument_functions)
        lines.append(f"{rule_name}() = {body}")
        lines.append(f"{ASSIGN_RULE_META_PREFIX}{rule_name}() = {body}")

    for rule in model.rules:
        if not rule.variable or rule.type != "rate":
            continue
        body = extend_function(
            _inline_reaction_fluxes(
                rule.math,
                model,
                assignment_rule_variables,
                skip_assignment_rules,
                concentration_names,
                species_map,
                replace_loc_params,
            ),
            {},
            model.function_definitions,
        )
        body = bngl_function(
            body,
            rule.variable,
            [],
            list(model.compartments),
            assignment_rule_variables=assignment_rule_variables,
            observable_converted_rules=skip_assignment_rules,
            species_with_conc_functions=concentration_names,
            sbml_to_bngl_id=species_map,
            rate_rule_variables=rate_rule_variables,
        )
        name = standardize_name(rule.variable)
        lines.append(f"{RATE_RULE_META_PREFIX}{name}() = {body}")
        lines.append(
            f"{RATE_RULE_POS_PREFIX}{name}() = if({RATE_RULE_META_PREFIX}{name}() > 0, "
            f"{RATE_RULE_META_PREFIX}{name}(), 0)"
        )
        lines.append(
            f"{RATE_RULE_NEG_PREFIX}{name}() = if({RATE_RULE_META_PREFIX}{name}() < 0, "
            f"-({RATE_RULE_META_PREFIX}{name}()), 0)"
        )
    return _inline_constant_function_calls(lines, model.parameters)


def _reaction_pattern(
    species_id: str,
    sct: SpeciesCompositionTable,
    model: SBMLModel,
    compartment_override: Optional[str] = None,
    species_compartment_prefix: bool = False,
) -> str:
    def render(pattern: str) -> str:
        return (
            _species_compartment_prefix(pattern, compartment_override)
            if species_compartment_prefix
            else pattern
        )

    multi_pattern = model.multi_species_patterns.get(species_id)
    if model.multi_executable and multi_pattern:
        try:
            structure = read_from_string(multi_pattern)
        except (TypeError, ValueError):
            structure = None
        if structure is not None:
            if compartment_override:
                structure.add_compartment(standardize_name(compartment_override))
            return render(_pattern(structure))
    entry = sct.entries.get(species_id)
    species = model.species.get(species_id)
    if entry is not None:
        return render(
            _pattern(
                entry.structure,
                (
                    compartment_override
                    if compartment_override is not None
                    else (species.compartment if species else "")
                ),
            )
        )
    name = standardize_name(species.name if species else species_id)
    return render("M_" + name + "()")


def _species_compartment_prefix(pattern: str, compartment: Optional[str]) -> str:
    """Convert writer suffixes to a species-level reaction prefix."""

    if not compartment:
        return pattern
    normalized = standardize_name(compartment)
    # `_pattern` uses suffix annotations for its public writer contract.
    # Reaction species need the species-level prefix form (`@comp:`):
    # the C++ rule engine uses that form to keep an SBML species in its
    # declared compartment when a reaction also transports another
    # participant to an adjacent compartment.
    suffix = "@" + normalized
    stripped = pattern.replace(suffix, "")
    if stripped.startswith("@" + normalized + ":"):
        return stripped
    return f"@{normalized}:{stripped}"


def _multi_reference_compartment(
    reference: object, model: SBMLModel, default: str = ""
) -> str:
    """Resolve a Multi compartmentReference to its core compartment id."""

    reference_id = getattr(reference, "compartment_reference", None)
    if not reference_id:
        return default
    for compartment_id, references in model.multi_compartment_references.items():
        if reference_id in references:
            return references[reference_id]
    _record_import_warning(
        model,
        f'Multi compartmentReference "{reference_id}" has no matching '
        "compartmentReference declaration; the species compartment was used.",
        category="package:multi",
        severity="approximated",
    )
    return default


def _multi_alias_location(
    model: SBMLModel, type_id: Optional[str], token: str
) -> Optional[Tuple[str, int, int]]:
    if not type_id or not token:
        return None
    locations = model.multi_component_aliases.get(type_id, {}).get(token, [])
    if len(locations) == 1:
        return tuple(locations[0])
    return None


def _clear_multi_component_state(component: object) -> None:
    component.states = []
    component.active_state = ""


def _copy_multi_component_state(source: object, target: object) -> None:
    target.states = list(getattr(source, "states", []))
    target.active_state = getattr(source, "active_state", "")
    source_bonds = list(getattr(source, "bonds", []))
    # Numeric bonds are meaningful only when both mapped endpoints are present;
    # wildcard outward status remains valid on its own.
    structural_bonds = [
        bond for bond in getattr(target, "bonds", []) if bond not in ("+", "?")
    ]
    target.bonds = structural_bonds or [
        bond for bond in source_bonds if bond in ("+", "?")
    ]


def _multi_product_structure(
    model: SBMLModel,
    species_id: str,
    reaction: SBMLReaction,
    reference: object,
) -> Optional[Species]:
    """Reconstruct a mapped Multi product while retaining don't-care fields."""

    species = model.species.get(species_id)
    if species is None or not model.multi_executable:
        return None
    type_pattern = model.multi_type_patterns.get(species.species_type or "")
    species_pattern = model.multi_species_patterns.get(species_id)
    if not type_pattern or not species_pattern:
        return None
    try:
        result = read_from_string(type_pattern)
        explicit = read_from_string(species_pattern)
    except (TypeError, ValueError):
        return None

    # Type pattern supplies complete molecule/bond topology.  Species pattern
    # overlays only explicitly stated components; omitted features remain
    # don't-care, as required by Multi.
    used_explicit = set()
    for target_index, target in enumerate(result.molecules):
        candidate = None
        if target_index < len(explicit.molecules):
            possible = explicit.molecules[target_index]
            if possible.name == target.name:
                candidate = possible
        if candidate is None:
            for index, possible in enumerate(explicit.molecules):
                if index not in used_explicit and possible.name == target.name:
                    candidate = possible
                    used_explicit.add(index)
                    break
        if candidate is None:
            for component in target.components:
                _clear_multi_component_state(component)
            continue
        used_explicit.add(explicit.molecules.index(candidate))
        explicit_by_name = {
            component.name: component for component in candidate.components
        }
        for component in target.components:
            source_component = explicit_by_name.get(component.name)
            if source_component is None:
                _clear_multi_component_state(component)
            else:
                _copy_multi_component_state(source_component, component)

    for mapping in getattr(reference, "multi_component_maps", []) or []:
        source_reference = next(
            (
                item
                for item in reaction.reactants
                if getattr(item, "id", None) == mapping.reactant
            ),
            None,
        )
        if source_reference is None:
            _record_import_warning(
                model,
                f'Reaction "{reaction.id}" Multi product map references unknown '
                f'reactant "{mapping.reactant}"; mapping was not applied.',
                category="package:multi",
                severity="dropped",
            )
            continue
        source_species = model.species.get(source_reference.species)
        source_type = source_species.species_type if source_species else None
        source_pattern = model.multi_species_patterns.get(source_reference.species)
        if not source_type or not source_pattern:
            continue
        try:
            source_structure = read_from_string(source_pattern)
        except (TypeError, ValueError):
            continue
        source_location = _multi_alias_location(
            model, source_type, mapping.reactant_component
        )
        target_location = _multi_alias_location(
            model, species.species_type, mapping.product_component
        )
        if source_location is None or target_location is None:
            _record_import_warning(
                model,
                f'Reaction "{reaction.id}" Multi product map could not resolve '
                f'"{mapping.reactant_component}" to "{mapping.product_component}"; '
                "mapping was not applied.",
                category="package:multi",
                severity="dropped",
            )
            continue
        source_kind, source_molecule_index, source_component_index = source_location
        target_kind, target_molecule_index, target_component_index = target_location
        if source_molecule_index >= len(source_structure.molecules):
            continue
        if target_molecule_index >= len(result.molecules):
            continue
        source_molecule = source_structure.molecules[source_molecule_index]
        target_molecule = result.molecules[target_molecule_index]
        if source_kind == "molecule" and target_kind == "molecule":
            for index, target_component in enumerate(target_molecule.components):
                if index < len(source_molecule.components):
                    _copy_multi_component_state(
                        source_molecule.components[index], target_component
                    )
        elif (
            source_kind == "component"
            and target_kind == "component"
            and source_component_index < len(source_molecule.components)
            and target_component_index < len(target_molecule.components)
        ):
            _copy_multi_component_state(
                source_molecule.components[source_component_index],
                target_molecule.components[target_component_index],
            )
    result.renumber_bonds()
    return result


def _compartments_are_adjacent(
    first_id: Optional[str],
    second_id: Optional[str],
    compartments: Mapping[str, object],
) -> bool:
    if not first_id or not second_id:
        return False
    first = compartments.get(first_id)
    second = compartments.get(second_id)
    if first is None or second is None:
        return False
    return (
        getattr(first, "outside", None) == second_id
        or getattr(second, "outside", None) == first_id
    )


def write_reaction_rules(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    atomize: bool,
    observable_converted_rules: Optional[Set[str]] = None,
    time_rate_functions: Optional[List[str]] = None,
    replace_loc_params: bool = True,
    species_compartment_prefix: bool = False,
) -> List[str]:
    # BNGL represents stoichiometry by repeating a species pattern. Very
    # large source stoichiometries cannot therefore be represented as a
    # practical rule-based pattern, even though SBML accepts the integer.
    max_bngl_stoichiometry = 100
    lines = []
    used_labels = set()
    # In SBML, a rate rule is the defining derivative for its variable.  A
    # species may still occur in a reaction in real-world models (including
    # several BioModels records), but retaining that participant in BNGL would
    # add the reaction stoichiometric contribution a second time.  Keep the
    # species in the kinetic expression as a state operand while removing it
    # from the reaction pattern; the synthetic TotalRate rule below then owns
    # its derivative, matching libRoadRunner's rate-rule semantics.
    rate_rule_species = {
        species_id
        for species_id in model.species
        if any(
            rule.variable == species_id
            or standardize_name(str(rule.variable or ""))
            == standardize_name(str(species_id))
            for rule in model.rules
            if getattr(rule, "type", "") == "rate" and rule.variable
        )
    }
    algebraic_assignment_species = set(_lowerable_species_assignment_rules(model))
    non_reaction_state_species = rate_rule_species | algebraic_assignment_species
    for reaction_id, reaction in model.reactions.items():
        # SBML permits a reaction with no species references.  Preserve its
        # kinetic-law identity as a zero-effect BNGL rule; BNG3's parser and
        # SBML writer both retain ``0 -> 0`` reactions.  This is distinct from
        # a reaction whose participants were removed below because a rate rule
        # is the sole owner of those species derivatives.
        source_is_noop = not reaction.reactants and not reaction.products
        reactant_species = (
            model.species.get(reaction.reactants[0].species)
            if reaction.reactants
            else None
        )
        reactant_compartment = (
            getattr(reactant_species, "compartment", None)
            if reactant_species is not None
            else None
        )
        if reaction.reactants:
            reactant_compartment = _multi_reference_compartment(
                reaction.reactants[0], model, reactant_compartment or ""
            )
        if model.compartments and reactant_compartment:
            for reference in reaction.products:
                if reference.species == "EmptySet":
                    continue
                product_species = model.species.get(reference.species)
                product_compartment = (
                    getattr(product_species, "compartment", None)
                    if product_species is not None
                    else None
                )
                product_compartment = _multi_reference_compartment(
                    reference, model, product_compartment or ""
                )
                if (
                    product_compartment
                    and product_compartment != reactant_compartment
                    and not _compartments_are_adjacent(
                        reactant_compartment,
                        product_compartment,
                        model.compartments,
                    )
                ):
                    _log_transport_info(
                        f"Transport reaction {reaction_id}: {reference.species} "
                        f"moves from {reactant_compartment} to {product_compartment}"
                    )
        dynamic_references = [
            reference
            for reference in [*reaction.reactants, *reaction.products]
            if reference.species != "EmptySet" and reference.variable_stoichiometry
        ]
        fractional_stoichiometry = any(
            reference.species != "EmptySet"
            and not reference.variable_stoichiometry
            and math.isfinite(reference.stoichiometry)
            and reference.stoichiometry >= 0
            and abs(reference.stoichiometry - round(reference.stoichiometry)) > 1e-9
            for reference in [*reaction.reactants, *reaction.products]
        )
        oversized_stoichiometries = [
            reference
            for reference in [*reaction.reactants, *reaction.products]
            if reference.species != "EmptySet"
            and math.isfinite(reference.stoichiometry)
            and reference.stoichiometry >= 0
            and int(round(reference.stoichiometry)) > max_bngl_stoichiometry
        ]
        if dynamic_references:
            dynamic_coefficients = {
                id(reference): _dynamic_species_reference_expression(
                    reference, model, reaction_id
                )
                for reference in dynamic_references
            }
            not_lowerable = next(
                (
                    reference
                    for reference in dynamic_references
                    if dynamic_coefficients[id(reference)] is None
                ),
                None,
            )
            has_fbc = any(
                warning.get("category") == "fbc" for warning in model.import_warnings
            )
            if (
                not_lowerable is not None
                or reaction.fast
                or model.multi_executable
                or reaction.multi_intra_species
                or has_fbc
            ):
                reason = (
                    f'Reaction "{reaction_id}" has variable stoichiometry for '
                    f'"{not_lowerable.species}" without a lowerable expression.'
                    if not_lowerable is not None
                    else f'Reaction "{reaction_id}" has variable stoichiometry, '
                    "but fast, executable Multi, or FBC semantics prevent "
                    "deterministic flux lowering."
                )
                _record_import_warning(
                    model,
                    reason,
                    category="stoichiometry",
                    severity="dropped",
                )
                continue

            prepared_math = _prepared_kinetic_math(
                reaction,
                model,
                replace_loc_params=replace_loc_params,
                reaction_id=reaction_id,
            )
            source_flux = _rate_for_reaction(
                reaction,
                model,
                conversion_factor=None,
                observable_converted_rules=observable_converted_rules,
                reactant_ids=[],
                prepared_math=prepared_math,
                replace_loc_params=replace_loc_params,
            )
            net_terms: "OrderedDict[str, List[str]]" = OrderedDict()
            for sign, references in (
                ("-", reaction.reactants),
                ("+", reaction.products),
            ):
                for reference in references:
                    if reference.species == "EmptySet":
                        continue
                    coefficient = dynamic_coefficients.get(id(reference))
                    if coefficient is None:
                        coefficient = _number(reference.stoichiometry)
                    net_terms.setdefault(reference.species, []).append(
                        f"{sign}({coefficient})"
                    )

            _record_import_warning(
                model,
                f'Reaction "{reaction_id}" has a time-varying coefficient; its '
                "deterministic ODE flux was lowered to species-specific TotalRate "
                "rules. Stochastic shared-event trajectories are not claimed.",
                category="stoichiometry",
                severity="info",
            )
            for species_id, terms in net_terms.items():
                species = model.species.get(species_id)
                if (
                    species_id in non_reaction_state_species
                    or species is None
                    or getattr(species, "boundary_condition", False)
                    or getattr(species, "constant", False)
                ):
                    continue
                coefficient = " + ".join(terms)
                factor = _conversion_factor_for_species(species_id, model)
                derivative = f"({coefficient}) * ({source_flux})"
                if factor is not None:
                    derivative = f"({factor}) * ({derivative})"
                pattern = _reaction_pattern(
                    species_id,
                    sct,
                    model,
                    getattr(species, "compartment", ""),
                    species_compartment_prefix=species_compartment_prefix,
                )
                rule_specs = (
                    ("produce", f"if(({derivative}) > 0, ({derivative}), 0)"),
                    ("consume", f"if(({derivative}) < 0, -({derivative}), 0)"),
                )
                for side, rate_expression in rule_specs:
                    if not reaction.reversible and len(terms) == 1:
                        produces = terms[0].startswith("+")
                        if (side == "produce") != produces:
                            continue
                        rate_expression = f"({terms[0][1:]}) * ({source_flux})"
                        if factor is not None:
                            rate_expression = f"({factor}) * ({rate_expression})"
                    rule_label = (
                        f"{standardize_name(reaction_id)}_{side}_"
                        f"{standardize_name(species_id)}"
                    )
                    suffix = 2
                    base_label = rule_label
                    while rule_label in used_labels:
                        rule_label = f"{base_label}_{suffix}"
                        suffix += 1
                    used_labels.add(rule_label)
                    if (
                        time_rate_functions is not None
                        and re.search(r"\btime\s*\(", rate_expression)
                        and not re.search(r"(?:_amt\b|_c_)", rate_expression)
                    ):
                        function_name = (
                            f"_trate_{standardize_name(reaction_id)}_{side}_"
                            f"{standardize_name(species_id)}"
                        )
                        time_rate_functions.append(
                            f"{function_name}() = {rate_expression}"
                        )
                        rate_expression = f"{function_name}()"
                    left, right = (
                        ("0", pattern) if side == "produce" else (pattern, "0")
                    )
                    lines.append(
                        f"{rule_label}: {left} -> {right} {rate_expression} TotalRate"
                    )
            continue
        oversized_dynamic_stoichiometry = next(
            (
                reference
                for reference in oversized_stoichiometries
                if reference.variable_stoichiometry
            ),
            None,
        )
        if oversized_dynamic_stoichiometry is not None:
            _record_import_warning(
                model,
                f'Reaction "{reaction_id}" has dynamic stoichiometry for '
                f'"{oversized_dynamic_stoichiometry.species}" above the BNGL '
                "expansion limit; deterministic flux lowering requires fixed "
                "stoichiometry.",
                category="stoichiometry",
                severity="dropped",
            )
            continue
        oversized_fixed_stoichiometry = bool(oversized_stoichiometries)
        unsupported = next(
            (
                reference
                for reference in [*reaction.reactants, *reaction.products]
                if reference.species != "EmptySet"
                and (
                    not math.isfinite(reference.stoichiometry)
                    or reference.stoichiometry < 0
                    or (
                        reference.variable_stoichiometry
                        and abs(
                            reference.stoichiometry - round(reference.stoichiometry)
                        )
                        > 1e-9
                    )
                )
            ),
            None,
        )
        if unsupported is not None:
            _record_import_warning(
                model,
                f'Reaction "{reaction_id}" has unsupported stoichiometry for '
                f'"{unsupported.species}"; the reaction was omitted because BNGL '
                "requires fixed nonnegative integer stoichiometry.",
                category="stoichiometry",
                severity="dropped",
            )
            continue
        if (fractional_stoichiometry or oversized_fixed_stoichiometry) and (
            reaction.fast
            or model.multi_executable
            or reaction.multi_intra_species
            or any(
                warning.get("category") == "fbc" for warning in model.import_warnings
            )
        ):
            _record_import_warning(
                model,
                f'Reaction "{reaction_id}" has fixed fractional stoichiometry, '
                "but fast, executable Multi, or FBC semantics prevent deterministic "
                "flux lowering; the reaction was omitted.",
                category="stoichiometry",
                severity="dropped",
            )
            continue
        deterministic_flux_lowering = (
            fractional_stoichiometry or oversized_fixed_stoichiometry
        )
        reactants: List[str] = []
        products: List[str] = []
        for reference in reaction.reactants:
            if (
                reference.species == "EmptySet"
                or reference.species in non_reaction_state_species
            ):
                continue
            reactants.extend(
                [
                    _reaction_pattern(
                        reference.species,
                        sct,
                        model,
                        _multi_reference_compartment(
                            reference,
                            model,
                            getattr(
                                model.species.get(reference.species),
                                "compartment",
                                "",
                            ),
                        ),
                        species_compartment_prefix=species_compartment_prefix,
                    )
                ]
                * int(round(reference.stoichiometry))
            )
        for reference in reaction.products:
            if (
                reference.species == "EmptySet"
                or reference.species in non_reaction_state_species
            ):
                continue
            mapped = _multi_product_structure(
                model, reference.species, reaction, reference
            )
            product_compartment = _multi_reference_compartment(
                reference,
                model,
                getattr(model.species.get(reference.species), "compartment", ""),
            )
            if mapped is not None:
                product_pattern = _pattern(mapped, product_compartment)
                if species_compartment_prefix:
                    product_pattern = _species_compartment_prefix(
                        product_pattern, product_compartment
                    )
            else:
                product_pattern = _reaction_pattern(
                    reference.species,
                    sct,
                    model,
                    product_compartment,
                    species_compartment_prefix=species_compartment_prefix,
                )
            products.extend([product_pattern] * int(round(reference.stoichiometry)))
        if not reactants and not products and not source_is_noop:
            # A reaction whose only participant is rate-rule-controlled has no
            # independent stoichiometric effect after the target is removed.
            # Its kinetic law remains available to rate-rule inlining above.
            continue
        label = standardize_name(reaction.name or reaction_id)
        candidate = label
        suffix = 2
        while candidate in used_labels:
            candidate = f"{label}_{suffix}"
            suffix += 1
        used_labels.add(candidate)
        structures = {
            species_id: entry.structure
            for species_id, entry in sct.entries.items()
            if entry.structure is not None
        }

        # A time-only rate has no species/observable marker for BNG2's
        # functional-rate path. Keep it live by emitting a zero-argument
        # function, matching the bounded time-rate port used below.
        def needs_time_wrap(value: str) -> bool:
            return bool(re.search(r"\btime\s*\(", value)) and not re.search(
                r"(?:_amt\b|_c_)", value
            )

        def wrap_time_rate(value: str, suffix: str = "") -> str:
            if time_rate_functions is None or not needs_time_wrap(value):
                return value
            function_name = f"_trate_{candidate}{suffix}"
            time_rate_functions.append(f"{function_name}() = {value}")
            return f"{function_name}()"

        if deterministic_flux_lowering:
            prepared_math = _prepared_kinetic_math(
                reaction,
                model,
                replace_loc_params=replace_loc_params,
                reaction_id=reaction_id,
            )
            source_flux = _rate_for_reaction(
                reaction,
                model,
                conversion_factor=None,
                observable_converted_rules=observable_converted_rules,
                reactant_structures=structures,
                reactant_ids=[],
                prepared_math=prepared_math,
                replace_loc_params=replace_loc_params,
            )
            net_stoichiometry: "OrderedDict[str, float]" = OrderedDict()
            for reference in reaction.reactants:
                if reference.species != "EmptySet":
                    net_stoichiometry[reference.species] = (
                        net_stoichiometry.get(reference.species, 0.0)
                        - reference.stoichiometry
                    )
            for reference in reaction.products:
                if reference.species != "EmptySet":
                    net_stoichiometry[reference.species] = (
                        net_stoichiometry.get(reference.species, 0.0)
                        + reference.stoichiometry
                    )
            if fractional_stoichiometry:
                message = (
                    f'Reaction "{reaction_id}" has fixed fractional stoichiometry; '
                    "its ODE flux was lowered to species-specific TotalRate rules."
                )
            else:
                message = (
                    f'Reaction "{reaction_id}" exceeds the BNGL expansion limit '
                    f"of {max_bngl_stoichiometry}; its fixed-stoichiometry ODE flux "
                    "was lowered to species-specific TotalRate rules."
                )
            message += (
                " Deterministic trajectories preserve SBML derivatives; stochastic "
                "trajectories do not preserve shared reaction-event coupling."
            )
            _record_import_warning(
                model,
                message,
                category="stoichiometry",
                severity="info",
            )
            for species_id, coefficient in net_stoichiometry.items():
                species = model.species.get(species_id)
                if (
                    species_id in non_reaction_state_species
                    or abs(coefficient) <= 1e-12
                    or species is None
                    or getattr(species, "boundary_condition", False)
                    or getattr(species, "constant", False)
                ):
                    continue
                factor = _conversion_factor_for_species(species_id, model)
                derivative = f"({coefficient:g}) * ({source_flux})"
                if factor is not None:
                    derivative = f"({factor}) * ({derivative})"
                pattern = _reaction_pattern(
                    species_id,
                    sct,
                    model,
                    getattr(species, "compartment", ""),
                    species_compartment_prefix=species_compartment_prefix,
                )
                if reaction.reversible:
                    positive = f"if(({derivative}) > 0, ({derivative}), 0)"
                    negative = f"if(({derivative}) < 0, -({derivative}), 0)"
                    rule_specs = (("produce", positive), ("consume", negative))
                else:
                    side = "produce" if coefficient > 0 else "consume"
                    rate_expression = f"({abs(coefficient):g}) * ({source_flux})"
                    if factor is not None:
                        rate_expression = f"({factor}) * ({rate_expression})"
                    rule_specs = ((side, rate_expression),)
                for side, rate_expression in rule_specs:
                    produces = side == "produce"
                    rule_label = f"{candidate}_{side}_{standardize_name(species_id)}"
                    label_suffix = 2
                    while rule_label in used_labels:
                        rule_label = (
                            f"{candidate}_{side}_{standardize_name(species_id)}"
                            f"_{label_suffix}"
                        )
                        label_suffix += 1
                    used_labels.add(rule_label)
                    rate_expression = wrap_time_rate(
                        rate_expression,
                        f"_{side}_{standardize_name(species_id)}",
                    )
                    left, right = ("0", pattern) if produces else (pattern, "0")
                    lines.append(
                        f"{rule_label}: {left} -> {right} {rate_expression} TotalRate"
                    )
            continue
        mixed_conversion_factors = _mixed_conversion_factor_expressions(reaction, model)
        mixed_source_rate: Optional[str] = None
        if mixed_conversion_factors is not None and not atomize:
            prepared_math = _prepared_kinetic_math(
                reaction,
                model,
                replace_loc_params=replace_loc_params,
                reaction_id=reaction_id,
            )
            reversible_split = (
                _split_reversible_rate(convert_math_expression(prepared_math))
                if reaction.reversible
                else None
            )
            # A source-shaped net flux can be projected onto the individual
            # SBML species derivatives.  A reversible law already split into
            # forward/reverse propensities needs a separate directional
            # projection and remains on the conservative unsupported path.
            if reversible_split is None:
                mixed_source_rate = _rate_for_reaction(
                    reaction,
                    model,
                    conversion_factor=None,
                    observable_converted_rules=observable_converted_rules,
                    reactant_structures=structures,
                    reactant_ids=[],
                    prepared_math=prepared_math,
                    replace_loc_params=replace_loc_params,
                )
        processed = process_reaction_rate(
            reaction,
            reaction_id,
            model,
            observable_converted_rules=observable_converted_rules,
            reactant_structures=structures,
            conversion_factor=(
                None
                if mixed_source_rate is not None
                else _conversion_factor_for_reaction(reaction, model)
            ),
            replace_loc_params=replace_loc_params,
        )
        rate = processed.rate_string
        reversed_numeric_flux = False
        if "," not in rate:
            numeric_rate = _evaluate_arithmetic(convert_math_expression(rate))
            if numeric_rate is not None and numeric_rate < 0:
                # SBML kinetic laws are signed net fluxes.  BNGL reaction
                # rates must be nonnegative, but a constant negative flux is
                # exactly representable by reversing the reaction sides and
                # using its positive magnitude.  Keep this limited to a
                # compile-time constant: a state-dependent sign change would
                # require a conditional propensity that BNGL cannot express
                # without changing the model semantics.
                reversed_numeric_flux = True
                reactants, products = products, reactants
                rate = f"{-numeric_rate:g}"
                _record_import_warning(
                    model,
                    f'Reaction "{reaction_id}" has a negative numeric rate '
                    f"({numeric_rate:g}); reversed the reaction sides and "
                    "emitted the positive flux magnitude.",
                    category="rate",
                    severity="info",
                )
        arrow = (
            "<->"
            if reaction.reversible
            and not processed.force_irreversible
            and not reversed_numeric_flux
            else "->"
        )

        if mixed_source_rate is not None and mixed_conversion_factors is not None:
            net_stoichiometry: "OrderedDict[str, float]" = OrderedDict()
            for reference in reaction.reactants:
                if reference.species == "EmptySet":
                    continue
                net_stoichiometry[reference.species] = (
                    net_stoichiometry.get(reference.species, 0.0)
                    - reference.stoichiometry
                )
            for reference in reaction.products:
                if reference.species == "EmptySet":
                    continue
                net_stoichiometry[reference.species] = (
                    net_stoichiometry.get(reference.species, 0.0)
                    + reference.stoichiometry
                )
            _record_import_warning(
                model,
                f'Reaction "{reaction_id}" has differing conversionFactors; '
                "decomposed its deterministic flux into species-specific "
                "TotalRate rules. BNGL stochastic trajectories do not retain "
                "the original shared reaction-event coupling.",
                category="conversionFactor",
                severity="info",
            )
            for species_id, coefficient in net_stoichiometry.items():
                if species_id in rate_rule_species or abs(coefficient) <= 1e-12:
                    continue
                factor = mixed_conversion_factors.get(species_id)
                scaled_rate = (
                    mixed_source_rate
                    if factor is None
                    else f"{factor} * ({mixed_source_rate})"
                )
                species = model.species.get(species_id)
                pattern = _reaction_pattern(
                    species_id,
                    sct,
                    model,
                    getattr(species, "compartment", "") if species else "",
                    species_compartment_prefix=species_compartment_prefix,
                )
                count = int(round(abs(coefficient)))
                repeated = " + ".join([pattern] * count)
                side = "produce" if coefficient > 0 else "consume"
                rule_label = f"{candidate}_{side}_{standardize_name(species_id)}"
                label_suffix = 2
                while rule_label in used_labels:
                    rule_label = (
                        f"{candidate}_{side}_{standardize_name(species_id)}"
                        f"_{label_suffix}"
                    )
                    label_suffix += 1
                used_labels.add(rule_label)
                scaled_rate = wrap_time_rate(
                    scaled_rate,
                    f"_{side}_{standardize_name(species_id)}",
                )
                if coefficient > 0:
                    left, right = "0", repeated
                else:
                    left, right = repeated, "0"
                lines.append(f"{rule_label}: {left} -> {right} {scaled_rate} TotalRate")
            continue

        if arrow == "<->":
            depth = 0
            split_at = -1
            for index, character in enumerate(rate):
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                elif character == "," and depth == 0:
                    split_at = index
                    break
            if split_at >= 0:
                forward = wrap_time_rate(rate[:split_at].strip(), "_f")
                reverse = wrap_time_rate(rate[split_at + 1 :].strip(), "_r")
                rate = f"{forward}, {reverse}"
            else:
                rate = wrap_time_rate(rate)
        else:
            rate = wrap_time_rate(rate)

        # BNGL has one TotalRate modifier for a reversible rule, while an
        # SBML net law may require it for only one directional component.
        # Emit two ordinary rules in that mixed case so each direction keeps
        # its source semantics (complete flux versus mass action).
        if (
            arrow == "<->"
            and processed.forward_is_total_rate != processed.reverse_is_total_rate
            and split_at >= 0
        ):
            forward_modifier = " TotalRate" if processed.forward_is_total_rate else ""
            reverse_modifier = " TotalRate" if processed.reverse_is_total_rate else ""
            forward_label = f"{candidate}_forward"
            reverse_label = f"{candidate}_reverse"
            while forward_label in used_labels or reverse_label in used_labels:
                forward_label = f"{forward_label}_2"
                reverse_label = f"{reverse_label}_2"
            used_labels.update((forward_label, reverse_label))
            reactant_text = " + ".join(reactants) if reactants else "0"
            product_text = " + ".join(products) if products else "0"
            lines.append(
                f"{forward_label}: {reactant_text} -> {product_text} "
                f"{forward}{forward_modifier}"
            )
            lines.append(
                f"{reverse_label}: {product_text} -> {reactant_text} "
                f"{reverse}{reverse_modifier}"
            )
            continue
        total_rate_modifier = " TotalRate" if processed.is_total_rate else ""
        lines.append(
            f"{candidate}: {' + '.join(reactants) if reactants else '0'} "
            f"{arrow} {' + '.join(products) if products else '0'} {rate}"
            f"{total_rate_modifier}"
        )

    for rule in model.rules:
        if not rule.variable or rule.type != "rate":
            continue
        target_id = rule.variable
        if target_id not in sct.entries and target_id not in model.species:
            standardized = standardize_name(target_id)
            if standardized in sct.entries:
                target_id = standardized
            else:
                _record_import_warning(
                    model,
                    f'Rate rule "{rule.variable}" has no materialized SBML species; '
                    "it was retained as metadata but no source/sink rule was emitted.",
                )
                continue
        pattern = _reaction_pattern(
            target_id,
            sct,
            model,
            getattr(model.species.get(target_id), "compartment", ""),
            species_compartment_prefix=species_compartment_prefix,
        )
        name = standardize_name(rule.variable)
        lines.append(
            f"__rate_rule_{name}: 0 -> {pattern} {RATE_RULE_META_PREFIX}{name}() TotalRate"
        )
    return lines


def _reaction_rules_section(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    atomize: bool,
    observable_converted_rules: Optional[Set[str]] = None,
    time_rate_functions: Optional[List[str]] = None,
    replace_loc_params: bool = True,
    species_compartment_prefix: bool = False,
) -> str:
    """Render the shared reaction-rule implementation as a BNGL section."""

    return _section(
        "reaction rules",
        write_reaction_rules(
            model,
            sct,
            atomize,
            observable_converted_rules=observable_converted_rules,
            time_rate_functions=time_rate_functions,
            replace_loc_params=replace_loc_params,
            species_compartment_prefix=species_compartment_prefix,
        ),
    )


def write_reaction_rules_flat(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    observable_converted_rules: Optional[Set[str]] = None,
    time_rate_functions: Optional[List[str]] = None,
    replace_loc_params: bool = True,
    species_compartment_prefix: bool = False,
) -> str:
    """Render the Playground flat reaction-rule writer entry point.

    The Python port receives the already selected species-composition table;
    the table is elemental for flat translation and structured for atomized
    translation.  Both source writer variants therefore share the one
    validation and rate-processing implementation below.
    """

    return _reaction_rules_section(
        model,
        sct,
        atomize=False,
        observable_converted_rules=observable_converted_rules,
        time_rate_functions=time_rate_functions,
        replace_loc_params=replace_loc_params,
        species_compartment_prefix=species_compartment_prefix,
    )


def write_reaction_rules_atomized(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    observable_converted_rules: Optional[Set[str]] = None,
    time_rate_functions: Optional[List[str]] = None,
    replace_loc_params: bool = True,
    species_compartment_prefix: bool = False,
) -> str:
    """Render the Playground atomized reaction-rule writer entry point."""

    return _reaction_rules_section(
        model,
        sct,
        atomize=True,
        observable_converted_rules=observable_converted_rules,
        time_rate_functions=time_rate_functions,
        replace_loc_params=replace_loc_params,
        species_compartment_prefix=species_compartment_prefix,
    )


def write_reaction_rules_flat_v2(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    observable_converted_rules: Optional[Set[str]] = None,
    time_rate_functions: Optional[List[str]] = None,
    replace_loc_params: bool = True,
    species_compartment_prefix: bool = False,
) -> str:
    """Render the patched Playground flat writer used by BNGL generation."""

    return _reaction_rules_section(
        model,
        sct,
        atomize=False,
        observable_converted_rules=observable_converted_rules,
        time_rate_functions=time_rate_functions,
        replace_loc_params=replace_loc_params,
        species_compartment_prefix=species_compartment_prefix,
    )


def generate_bngl(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    molecule_types: Sequence[Molecule],
    seed_species: Sequence[SeedSpeciesEntry],
    atomize: bool = False,
    actions: str = "",
    t_end: float = 10,
    n_steps: int = 100,
    replace_loc_params: bool = True,
) -> BNGLGenerationResult:
    _lower_bounded_event_state_delays(model, float(t_end))
    lowerable_species_assignment_rules = _lowerable_species_assignment_rules(model)
    algebraic_reaction_species = set(lowerable_species_assignment_rules) & {
        str(reference.species)
        for reaction in model.reactions.values()
        for reference in [*reaction.reactants, *reaction.products]
        if reference.species != "EmptySet"
    }
    if algebraic_reaction_species:
        _record_import_warning(
            model,
            "Algebraic assignment-rule species used as reaction participants "
            "are emitted as functions and removed from reaction state patterns. "
            "Deterministic SBML ODE semantics are preserved; stochastic reaction "
            "event trajectories are not preserved for these species.",
            category="speciesAssignmentRule",
            severity="info",
        )
    species_assignment_variables = {
        str(rule.variable)
        for rule in model.rules
        if rule.type == "assignment"
        and rule.variable
        and str(rule.variable) in model.species
    }
    for variable in sorted(
        species_assignment_variables - set(lowerable_species_assignment_rules)
    ):
        _record_import_warning(
            model,
            f'SBML assignment rule targets species "{variable}"; BNGL cannot '
            "enforce an algebraic species state, so the rule was not applied.",
            category="speciesAssignmentRule",
            severity="dropped",
        )

    unsupported_functions = ("gcd", "lcm", "rint", "delay")
    reaction_local_symbols = set()
    species_reference_symbols = set()
    reaction_scopes: Dict[str, Set[str]] = {}
    for reaction_id, reaction in model.reactions.items():
        reaction_scope: Set[str] = set()
        kinetic_law = reaction.kinetic_law
        local_parameters = (
            kinetic_law.get("localParameters", [])
            if isinstance(kinetic_law, Mapping)
            else getattr(kinetic_law, "local_parameters", [])
        )
        for parameter in local_parameters or []:
            parameter_id = getattr(parameter, "id", None)
            if parameter_id is None and isinstance(parameter, Mapping):
                parameter_id = parameter.get("id")
            if parameter_id:
                reaction_scope.add(str(parameter_id))
        for reference in [*reaction.reactants, *reaction.products]:
            reference_id = getattr(reference, "id", None)
            if reference_id is None and isinstance(reference, Mapping):
                reference_id = reference.get("id")
            if reference_id:
                reference_id = str(reference_id)
                reaction_scope.add(reference_id)
                species_reference_symbols.add(reference_id)
        reaction_scopes[str(reaction_id)] = reaction_scope
        reaction_local_symbols.update(reaction_scope)
    globally_visible = {
        *map(str, model.parameters),
        *map(str, model.species),
        *map(str, model.compartments),
        *map(str, model.function_definitions),
        *species_reference_symbols,
        *(str(rule.variable) for rule in model.rules if rule.variable),
        *(
            str(getattr(assignment, "symbol", ""))
            for assignment in model.initial_assignments
        ),
        "time",
    }
    global_math_sources = [
        *(str(rule.math or "") for rule in model.rules),
        *(
            str(getattr(assignment, "math", "") or "")
            for assignment in model.initial_assignments
        ),
        *(
            str(expression or "")
            for event in model.events
            for expression in (
                event.trigger,
                event.delay,
                event.priority,
                *(assignment.math for assignment in event.assignments),
            )
        ),
    ]
    for symbol in sorted(
        reaction_local_symbols - globally_visible, key=len, reverse=True
    ):
        if any(
            re.search(rf"\b{re.escape(symbol)}\b", expression)
            for expression in global_math_sources
        ):
            _record_import_warning(
                model,
                f'Reaction-local SBML symbol "{symbol}" is referenced by a '
                "global rule or initial assignment and has no BNGL-wide scope.",
                category="scope",
                severity="dropped",
            )
    for reaction_id, reaction in model.reactions.items():
        current_scope = reaction_scopes.get(str(reaction_id), set())
        expression = get_kinetic_math(reaction.kinetic_law)
        for symbol in sorted(
            reaction_local_symbols - globally_visible - current_scope,
            key=len,
            reverse=True,
        ):
            if not re.search(rf"\b{re.escape(symbol)}\b", expression):
                continue
            owner = next(
                (
                    owner_id
                    for owner_id, scope in reaction_scopes.items()
                    if owner_id != str(reaction_id) and symbol in scope
                ),
                "another reaction",
            )
            _record_import_warning(
                model,
                f'Reaction "{reaction_id}" references reaction-local SBML '
                f'symbol "{symbol}" scoped to "{owner}"; it has no BNGL-wide '
                "scope.",
                category="scope",
                severity="dropped",
            )
    math_sources = [
        *(
            get_kinetic_math(reaction.kinetic_law)
            for reaction in model.reactions.values()
        ),
        *(str(rule.math or "") for rule in model.rules),
        *(str(function.math or "") for function in model.function_definitions.values()),
    ]
    for function_name in unsupported_functions:
        if any(
            re.search(rf"\b{re.escape(function_name)}\s*\(", expression, re.IGNORECASE)
            for expression in math_sources
        ):
            _record_import_warning(
                model,
                f'SBML math function "{function_name}" is not losslessly '
                "representable in the C++ SBML writer/libRoadRunner path.",
                category="mathml",
                severity="dropped",
            )

    for rule in model.rules:
        if rule.type != "algebraic":
            continue
        variable = rule.variable or ""
        message = (
            f'Algebraic rule "{variable}" is an implicit DAE constraint '
            "with no BNGL equivalent; it was not applied."
        )
        if not any(
            warning.get("category") == "algebraicRule"
            for warning in model.import_warnings
        ):
            model.import_warnings.append(
                {
                    "category": "algebraicRule",
                    "message": message,
                    "count": 1,
                    "severity": "dropped",
                }
            )
    assignment_variables = {
        standardize_name(rule.variable)
        for rule in _assignment_rules_for_writer(model)
        if rule.variable and str(rule.variable) not in species_assignment_variables
    }

    # SBML rate rules may target a parameter or another model variable that
    # has no listOfSpecies entry.  BNGL can only evolve molecule populations,
    # so follow the Playground contract and materialize such targets as
    # amount-only synthetic species with a source/sink rule pair below.
    augmented_sct_entries: Dict[str, SCTEntry] = OrderedDict(sct.entries)
    augmented_sct = SpeciesCompositionTable(
        entries=augmented_sct_entries,
        dependencies=sct.dependencies,
        reverse_dependencies=sct.reverse_dependencies,
        sorted_species=list(sct.sorted_species),
        weights=list(sct.weights),
    )
    augmented_molecule_types = list(molecule_types)
    augmented_seed_species = list(seed_species)
    seed_symbol_values = _seed_symbol_values(model, seed_species)
    synthetic_rate_rule_variables: Set[str] = set()
    default_compartment = next(iter(model.compartments), "")
    existing_seed_ids = {seed.sbml_id for seed in augmented_seed_species}
    existing_molecule_names = {
        standardize_name(molecule.name) for molecule in augmented_molecule_types
    }
    for rule in model.rules:
        if not rule.variable or rule.type != "rate":
            continue
        variable = rule.variable
        target = standardize_name(variable)
        if (
            variable in model.species
            or target in model.species
            or variable in existing_seed_ids
            or target in existing_seed_ids
        ):
            continue

        synthetic_rate_rule_variables.add(variable)
        molecule_name = f"{SYNTH_RATE_RULE_SPECIES_PREFIX}{target}"
        if standardize_name(molecule_name) not in existing_molecule_names:
            augmented_molecule_types.append(Molecule(molecule_name))
            existing_molecule_names.add(standardize_name(molecule_name))

        structure = Species()
        structure.add_molecule(Molecule(molecule_name))
        if default_compartment:
            structure.add_compartment(default_compartment)
        structure.renumber_bonds()
        parameter = model.parameters.get(variable) or model.parameters.get(target)
        initial_value = seed_symbol_values.get(variable)
        if initial_value is None:
            initial_value = seed_symbol_values.get(target)
        if initial_value is None:
            initial_value = getattr(parameter, "value", 0) if parameter else 0
        try:
            initial = float(initial_value)
            if not math.isfinite(initial):
                initial = 0.0
        except (TypeError, ValueError):
            initial = 0.0
        augmented_seed_species.append(
            SeedSpeciesEntry(
                species=structure.copy(),
                concentration=_number(initial),
                compartment=default_compartment,
                sbml_id=variable,
            )
        )
        existing_seed_ids.add(variable)
        augmented_sct_entries.setdefault(
            variable,
            SCTEntry(
                structure=structure,
                components=[],
                sbml_id=variable,
                is_elemental=True,
                modifications={},
                weight=0,
                bonds=[],
            ),
        )

    if synthetic_rate_rule_variables:
        logger.info(
            "BNW012",
            f"Synthesized {len(synthetic_rate_rule_variables)} rate-rule state species",
        )

    sections = [
        "# BNGL model generated by the Playground-derived Python atomizer",
        f"# Model: {model.name}",
        f"# Species: {len(model.species)}, Reactions: {len(model.reactions)}",
        "",
        "begin model",
        _section(
            "parameters",
            write_parameters(
                model,
                assignment_variables,
                include_local_parameters=not replace_loc_params,
            ),
        ),
    ]
    if model.compartments:
        sections.append(_section("compartments", write_compartments(model)))
    sections.append(
        _section("molecule types", write_molecule_types(augmented_molecule_types))
    )
    seed_lines, species_to_pattern, _pattern_to_id = write_seed_species(
        augmented_seed_species, augmented_sct, model
    )
    if seed_lines:
        sections.append(_section("seed species", seed_lines))
    observable_lines, observable_map = write_observables(model, sct, species_to_pattern)
    observable_rule_variables = {
        rule.variable
        for rule in model.rules
        if rule.type == "assignment"
        and rule.variable
        and any(
            line.startswith(f"Molecules {standardize_name(rule.variable)} ")
            for line in observable_lines
        )
    }
    for variable in sorted(synthetic_rate_rule_variables):
        pattern = species_to_pattern.get(variable)
        if pattern:
            observable_lines.append(
                f"Species {standardize_name(variable)}_amt {pattern}"
            )
    if observable_lines:
        sections.append(_section("observables", observable_lines))
    function_lines = write_functions(
        model,
        synthetic_rate_rule_variables,
        observable_rule_variables,
        replace_loc_params=replace_loc_params,
    )
    time_rate_functions: List[str] = []
    reaction_rules = (
        write_reaction_rules_atomized if atomize else write_reaction_rules_flat_v2
    )
    sections.append(
        reaction_rules(
            model,
            augmented_sct,
            observable_converted_rules=observable_rule_variables,
            time_rate_functions=time_rate_functions,
            replace_loc_params=replace_loc_params,
            species_compartment_prefix=True,
        )
    )
    function_lines.extend(time_rate_functions)
    if function_lines:
        sections.insert(-1, _section("functions", function_lines))
    sections.append("end model")
    model_text = "\n\n".join(section for section in sections if section != "") + "\n"

    # Check the emitted, fully lowered expressions rather than only the raw
    # SBML formulas.  Assignment-rule/function expansion can turn a symbolic
    # denominator such as ``t_ave`` into the literal zero emitted in BNGL.
    # Such a source model has undefined numerical semantics and must remain
    # explicitly unsupported instead of being reported as a solver failure.
    if _contains_static_zero_divisor(model_text):
        _record_import_warning(
            model,
            "SBML contains a literal division by zero; the affected expression "
            "has undefined numerical semantics and cannot be represented by a "
            "finite BNGL model.",
            category="mathml",
            severity="dropped",
        )

    event_result = None
    if model.events:
        mutable_event_ids = {rule.variable for rule in model.rules if rule.variable}
        mutable_event_ids.update(
            getattr(
                assignment,
                "variable",
                assignment[0] if isinstance(assignment, (tuple, list)) else "",
            )
            for event in model.events
            for assignment in event.assignments
            if getattr(
                assignment,
                "variable",
                assignment[0] if isinstance(assignment, (tuple, list)) else "",
            )
        )

        changing_species_ids = {
            str(rule.variable)
            for rule in model.rules
            if rule.variable and rule.type in {"assignment", "rate"}
        }
        changing_species_ids.update(
            str(assignment.symbol)
            for assignment in model.initial_assignments
            if assignment.symbol
        )
        changing_species_ids.update(
            str(assignment.variable)
            for event in model.events
            for assignment in event.assignments
            if getattr(assignment, "variable", None)
        )
        changing_species_ids.update(
            str(reference.species)
            for reaction in model.reactions.values()
            for reference in [*reaction.reactants, *reaction.products]
            if reference.species and reference.stoichiometry != 0
        )
        changing_compartments = {
            standardize_name(str(rule.variable))
            for rule in model.rules
            if rule.variable and rule.type in {"assignment", "rate"}
        }
        changing_compartments.update(
            standardize_name(str(assignment.symbol))
            for assignment in model.initial_assignments
            if assignment.symbol
        )
        changing_compartments.update(
            standardize_name(str(assignment.variable))
            for event in model.events
            for assignment in event.assignments
            if getattr(assignment, "variable", None)
        )

        def is_compile_time_constant(identifier: str) -> bool:
            if identifier in {"__Avogadro__", "exponentiale", "pi"}:
                return True
            parameter = model.parameters.get(identifier)
            if parameter is not None:
                # SBML permits a parameter with constant="false" to be
                # changed, but it remains fixed throughout this model unless
                # a rule or event actually changes it. An initial assignment
                # supplies a static initial value and remains foldable when
                # the parameter has no later controller.
                return identifier not in mutable_event_ids
            compartment = model.compartments.get(identifier)
            return bool(compartment is not None and identifier not in mutable_event_ids)

        initial_assignment_values = {
            str(assignment.symbol): str(assignment.math or "")
            for assignment in model.initial_assignments
            if assignment.symbol
        }
        duplicate_initial_assignments = {
            str(assignment.symbol)
            for assignment in model.initial_assignments
            if assignment.symbol
            and sum(
                str(other.symbol) == str(assignment.symbol)
                for other in model.initial_assignments
            )
            > 1
        }
        initial_assignment_cache: dict[str, Optional[float]] = {}
        initial_assignment_stack: set[str] = set()

        def resolve_event_parameter(identifier: str) -> Optional[float]:
            # In BNGL, __Avogadro__ is normalized to 1 for molecule-count
            # conversions. SBML event times are still in source units, so fold
            # the SBML built-in's exact numeric value here.
            if identifier == "__Avogadro__":
                return _SBML_AVOGADRO
            if identifier == "exponentiale":
                return math.e
            if identifier == "pi":
                return math.pi
            if identifier in duplicate_initial_assignments:
                return None
            if identifier in initial_assignment_values:
                if identifier in initial_assignment_cache:
                    return initial_assignment_cache[identifier]
                if identifier in initial_assignment_stack:
                    return None
                initial_assignment_stack.add(identifier)
                expression = extend_function(
                    initial_assignment_values[identifier],
                    {},
                    model.function_definitions,
                )
                value = fold_numeric(expression, resolve_event_parameter)
                initial_assignment_stack.remove(identifier)
                initial_assignment_cache[identifier] = value
                return value
            parameter = model.parameters.get(identifier)
            if parameter is not None:
                return parameter.value
            compartment = model.compartments.get(identifier)
            return compartment.size if compartment is not None else None

        def resolve_constant(identifier: str) -> Optional[float]:
            species = next(
                (
                    value
                    for species_id, value in model.species.items()
                    if standardize_name(species_id) == standardize_name(identifier)
                ),
                None,
            )
            if species is None or any(
                standardize_name(species_id) == standardize_name(identifier)
                for species_id in changing_species_ids
            ):
                return None
            compartment = model.compartments.get(species.compartment or "")
            if species.compartment and (
                compartment is None
                or standardize_name(species.compartment) in changing_compartments
            ):
                return None
            volume = float(compartment.size) if compartment is not None else 1.0
            amount = float(species.initial_amount)
            concentration = float(species.initial_concentration)
            if species.has_only_substance_units:
                if species.initial_amount_set:
                    return amount
                return concentration * volume
            if species.initial_concentration_set:
                return concentration
            return amount / volume if volume != 0 else None

        def resolve_initial_event_value(identifier: str) -> Optional[float]:
            if identifier == "__Avogadro__":
                return _SBML_AVOGADRO
            parameter = model.parameters.get(identifier)
            if parameter is not None:
                if any(
                    rule.variable == identifier for rule in model.rules if rule.variable
                ) or any(
                    assignment.symbol == identifier
                    for assignment in model.initial_assignments
                ):
                    return None
                return parameter.value
            compartment = model.compartments.get(identifier)
            if compartment is not None:
                if any(
                    rule.variable == identifier for rule in model.rules if rule.variable
                ) or any(
                    assignment.symbol == identifier
                    for assignment in model.initial_assignments
                ):
                    return None
                return compartment.size
            species_id = next(
                (
                    species_id
                    for species_id in model.species
                    if standardize_name(species_id) == standardize_name(identifier)
                ),
                None,
            )
            if (
                species_id is None
                or any(
                    rule.variable == species_id for rule in model.rules if rule.variable
                )
                or any(
                    assignment.symbol == species_id
                    for assignment in model.initial_assignments
                )
            ):
                return None
            species = model.species[species_id]
            compartment = model.compartments.get(species.compartment or "")
            volume = float(compartment.size) if compartment is not None else 1.0
            amount = float(species.initial_amount)
            concentration = float(species.initial_concentration)
            if species.has_only_substance_units:
                return amount if species.initial_amount_set else concentration * volume
            if species.initial_concentration_set:
                return concentration
            return amount / volume if volume != 0 else None

        def resolve_affine_event_rate(
            identifier: str,
        ) -> Optional[Tuple[float, float]]:
            parameter = model.parameters.get(identifier)
            if parameter is None:
                species_id = next(
                    (
                        species_id
                        for species_id in model.species
                        if standardize_name(species_id) == standardize_name(identifier)
                    ),
                    None,
                )
                species = model.species.get(species_id) if species_id else None
                if species is None:
                    return None
                if species.constant or species.boundary_condition:
                    if any(
                        assignment.variable == species_id
                        for event in model.events
                        for assignment in event.assignments
                    ):
                        return None
                    compartment = model.compartments.get(
                        species.compartment or ""
                    )
                    if species.compartment and (
                        compartment is None
                        or not compartment.constant
                        or any(
                            rule.variable == species.compartment
                            for rule in model.rules
                        )
                        or any(
                            assignment.variable == species.compartment
                            for event in model.events
                            for assignment in event.assignments
                        )
                    ):
                        return None
                    initial = resolve_initial_event_value(species_id)
                    if initial is not None:
                        return initial, 0.0
                if species.constant or species.boundary_condition:
                    initial = resolve_constant(species_id)
                    return (initial, 0.0) if initial is not None else None

                # A species whose only net production is a constant flux has
                # an exact affine trajectory.  Lower its first threshold
                # crossing when no rule, initial assignment, or event can
                # change that trajectory.  State-dependent rates remain
                # outside this proof and are left untranslated.
                if (
                    any(rule.variable == species_id for rule in model.rules)
                    or any(
                        assignment.symbol == species_id
                        for assignment in model.initial_assignments
                    )
                    or any(
                        assignment.variable == species_id
                        for event in model.events
                        for assignment in event.assignments
                    )
                ):
                    return None
                initial = resolve_initial_event_value(species_id)
                if initial is None or not math.isfinite(initial):
                    return None
                net_amount_rate = 0.0
                affecting_reaction = False
                for reaction in model.reactions.values():
                    references = [
                        reference
                        for reference in [*reaction.reactants, *reaction.products]
                        if reference.species == species_id
                    ]
                    if not references:
                        continue
                    affecting_reaction = True
                    if (
                        reaction.fast
                        or reaction.conversion_factor
                        or model.conversion_factor
                        or species.conversion_factor
                    ):
                        return None
                    net_coefficient = 0.0
                    for sign, side in (
                        (-1.0, reaction.reactants),
                        (1.0, reaction.products),
                    ):
                        for reference in side:
                            if reference.species != species_id:
                                continue
                            if reference.variable_stoichiometry:
                                return None
                            net_coefficient += sign * float(reference.stoichiometry)
                    if net_coefficient == 0:
                        continue
                    kinetic_law = reaction.kinetic_law
                    rate_expression = str(
                        getattr(kinetic_law, "math", "")
                        or (kinetic_law.get("math", "") if kinetic_law else "")
                        or ""
                    ).strip()
                    if not rate_expression:
                        return None
                    rate_expression = extend_function(
                        rate_expression, {}, model.function_definitions
                    )

                    def resolve_immutable(identifier: str) -> Optional[float]:
                        if is_compile_time_constant(identifier):
                            parameter_value = resolve_event_parameter(identifier)
                            if parameter_value is not None:
                                return parameter_value
                        return resolve_constant(identifier)

                    flux = fold_numeric(rate_expression, resolve_immutable)
                    if flux is None or not math.isfinite(flux):
                        return None
                    net_amount_rate += net_coefficient * flux
                if not affecting_reaction:
                    return None
                if not species.has_only_substance_units:
                    compartment = model.compartments.get(species.compartment or "")
                    if (
                        compartment is None
                        or not compartment.constant
                        or compartment.size == 0
                        or any(
                            rule.variable == species.compartment
                            for rule in model.rules
                        )
                        or any(
                            assignment.symbol == species.compartment
                            for assignment in model.initial_assignments
                        )
                        or any(
                            assignment.variable == species.compartment
                            for event in model.events
                            for assignment in event.assignments
                        )
                    ):
                        return None
                    net_amount_rate /= float(compartment.size)
                if not math.isfinite(net_amount_rate):
                    return None
                return initial, net_amount_rate
            if any(
                assignment.symbol == identifier
                for assignment in model.initial_assignments
            ) or any(
                event_assignment.variable == identifier
                for event in model.events
                for event_assignment in event.assignments
            ):
                return None
            rules = [rule for rule in model.rules if rule.variable == identifier]
            if len(rules) != 1 or rules[0].type != "rate":
                return None
            derivative = extend_function(rules[0].math, {}, model.function_definitions)

            def resolve_immutable(identifier: str) -> Optional[float]:
                if not is_compile_time_constant(identifier):
                    return None
                return resolve_event_parameter(identifier)

            slope = fold_numeric(derivative, resolve_immutable)
            initial = float(parameter.value)
            if slope is None or not math.isfinite(initial):
                return None
            return initial, slope

        def resolve_exponential_event_rate(
            identifier: str,
        ) -> Optional[Tuple[float, float]]:
            """Resolve an isolated species with exact x' = rate * x dynamics."""
            species_id = next(
                (
                    sid
                    for sid in model.species
                    if standardize_name(sid) == standardize_name(identifier)
                ),
                None,
            )
            species = model.species.get(species_id) if species_id else None
            if species is None or species.constant or species.boundary_condition:
                return None
            if (
                any(rule.variable == species_id for rule in model.rules)
                or any(
                    assignment.symbol == species_id
                    for assignment in model.initial_assignments
                )
                or any(
                    assignment.variable == species_id
                    for event in model.events
                    for assignment in event.assignments
                )
            ):
                return None
            initial = resolve_initial_event_value(species_id)
            if initial is None or not math.isfinite(initial):
                return None

            def resolve_immutable(symbol: str) -> Optional[float]:
                if is_compile_time_constant(symbol):
                    value = resolve_event_parameter(symbol)
                    if value is not None:
                        return value
                return resolve_constant(symbol)

            def polynomial(node: ast.AST) -> Optional[Tuple[float, float]]:
                if isinstance(node, ast.Constant) and isinstance(
                    node.value, (int, float)
                ):
                    return float(node.value), 0.0
                if isinstance(node, ast.Name):
                    if standardize_name(node.id) == standardize_name(species_id):
                        return 0.0, 1.0
                    value = resolve_immutable(node.id)
                    return (float(value), 0.0) if value is not None else None
                if isinstance(node, ast.UnaryOp) and isinstance(
                    node.op, (ast.UAdd, ast.USub)
                ):
                    value = polynomial(node.operand)
                    if value is None:
                        return None
                    sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
                    return sign * value[0], sign * value[1]
                if isinstance(node, ast.BinOp):
                    left, right = polynomial(node.left), polynomial(node.right)
                    if left is None or right is None:
                        return None
                    if isinstance(node.op, ast.Add):
                        return left[0] + right[0], left[1] + right[1]
                    if isinstance(node.op, ast.Sub):
                        return left[0] - right[0], left[1] - right[1]
                    if isinstance(node.op, ast.Mult):
                        if left[1] != 0 and right[1] != 0:
                            return None
                        return (
                            left[0] * right[0],
                            left[0] * right[1] + left[1] * right[0],
                        )
                    if isinstance(node.op, ast.Div) and right[1] == 0:
                        if right[0] == 0:
                            return None
                        return left[0] / right[0], left[1] / right[0]
                    if isinstance(node.op, ast.Pow) and right[1] == 0:
                        if right[0] == 0:
                            return 1.0, 0.0
                        if right[0] == 1:
                            return left
                    return None
                if isinstance(node, ast.Call):
                    args = [polynomial(arg) for arg in node.args]
                    if any(value is None or value[1] != 0 for value in args):
                        return None
                try:
                    folded = fold_numeric(ast.unparse(node), resolve_immutable)
                except (TypeError, ValueError, SyntaxError):
                    return None
                if folded is None or not math.isfinite(folded):
                    return None
                return folded, 0.0

            exponent = 0.0
            found = False
            for reaction in model.reactions.values():
                references = [
                    reference
                    for reference in [*reaction.reactants, *reaction.products]
                    if reference.species == species_id
                ]
                if not references:
                    continue
                if (
                    reaction.fast
                    or reaction.conversion_factor
                    or model.conversion_factor
                    or species.conversion_factor
                ):
                    return None
                net_coefficient = 0.0
                for sign, side in (
                    (-1.0, reaction.reactants),
                    (1.0, reaction.products),
                ):
                    for reference in side:
                        if reference.species != species_id:
                            continue
                        if reference.variable_stoichiometry:
                            return None
                        net_coefficient += sign * float(reference.stoichiometry)
                if net_coefficient == 0:
                    continue
                kinetic_law = reaction.kinetic_law
                expression = str(
                    getattr(kinetic_law, "math", "")
                    or (kinetic_law.get("math", "") if kinetic_law else "")
                    or ""
                ).strip()
                if not expression:
                    return None
                expression = extend_function(
                    expression, {}, model.function_definitions
                )
                try:
                    parsed = ast.parse(expression, mode="eval")
                except (TypeError, ValueError, SyntaxError):
                    return None
                coefficients = polynomial(parsed.body)
                if coefficients is None or coefficients[0] != 0:
                    return None
                exponent += net_coefficient * coefficients[1]
                found = True
            if not found:
                return None
            if not species.has_only_substance_units:
                compartment = model.compartments.get(species.compartment or "")
                if (
                    compartment is None
                    or not compartment.constant
                    or compartment.size == 0
                    or any(rule.variable == species.compartment for rule in model.rules)
                    or any(
                        assignment.symbol == species.compartment
                        for assignment in model.initial_assignments
                    )
                    or any(
                        assignment.variable == species.compartment
                        for event in model.events
                        for assignment in event.assignments
                    )
                ):
                    return None
                exponent /= float(compartment.size)
            return (initial, exponent) if math.isfinite(exponent) else None

        def resolve_rate_event_reset(
            identifier: str,
        ) -> Optional[Tuple[float, float]]:
            parameter = model.parameters.get(identifier)
            if parameter is None or any(
                assignment.symbol == identifier
                for assignment in model.initial_assignments
            ):
                return None
            rules = [rule for rule in model.rules if rule.variable == identifier]
            if len(rules) != 1 or rules[0].type != "rate":
                return None
            derivative = extend_function(rules[0].math, {}, model.function_definitions)

            def resolve_immutable(identifier: str) -> Optional[float]:
                if not is_compile_time_constant(identifier):
                    return None
                return resolve_event_parameter(identifier)

            slope = fold_numeric(derivative, resolve_immutable)
            initial = float(parameter.value)
            if slope is None or not math.isfinite(initial):
                return None
            return initial, slope

        event_result = synthesize_event_actions(
            model.events,
            EventTranslationContext(
                resolve_species_pattern=lambda species_id: species_to_pattern.get(
                    species_id
                ),
                resolve_param=resolve_event_parameter,
                is_param=lambda identifier: identifier in model.parameters,
                is_compartment=lambda identifier: identifier in model.compartments,
                is_compile_time_constant=is_compile_time_constant,
                resolve_constant=resolve_constant,
                expand_functions=lambda expression: extend_function(
                    expression, {}, model.function_definitions
                ),
                method=(
                    "ssa"
                    if re.search(
                        r"simulate_ssa|method\s*=>\s*[\"']?ssa", actions or "", re.I
                    )
                    else "ode"
                ),
                base_t_end=float(t_end),
                base_steps=max(1, int(n_steps)),
                resolve_initial_value=resolve_initial_event_value,
                resolve_affine_rate=resolve_affine_event_rate,
                resolve_exponential_rate=resolve_exponential_event_rate,
                resolve_rate_reset=resolve_rate_event_reset,
            ),
        )
        _update_event_translation_warning(model, event_result)

    if event_result is not None and (
        event_result.actions_block or event_result.untranslated
    ):
        notes = ["# ==== SBML DYNAMICS NOTES ====\n"]
        if event_result.converted:
            notes.append(
                f"# {event_result.converted} time-triggered event(s) converted to scheduled actions.\n"
            )
        if event_result.untranslated:
            notes.append(
                "# Events NOT simulated (state-dependent or non-constant); listed for reference:\n"
            )
            for event, reason in event_result.untranslated:
                label = event.id or event.name or "event"
                notes.append(f"#   event {label}: {reason}\n")
                notes.append(f"#     trigger: {event.trigger or '(none)'}\n")
                if event.delay:
                    notes.append(f"#     delay: {event.delay}\n")
                if getattr(event, "priority", None):
                    notes.append(f"#     priority: {event.priority}\n")
                for assignment in event.assignments:
                    if isinstance(assignment, Mapping):
                        variable = assignment.get("variable", "")
                        assignment_math = assignment.get("math", "")
                    else:
                        variable = assignment[0] if len(assignment) > 0 else ""
                        assignment_math = assignment[1] if len(assignment) > 1 else ""
                    notes.append(f"#     assign: {variable} := {assignment_math}\n")
        notes.append("# ============================\n")
        model_text += "\n" + "".join(notes)

    if event_result is not None and event_result.actions_block:
        model_text += "\nbegin actions\n"
        model_text += "\n".join(
            "  " + line if line and not line.startswith("#") else line
            for line in event_result.actions_block.splitlines()
        )
        model_text += "\nend actions\n"
    elif actions:
        model_text += "\nbegin actions\n"
        model_text += "\n".join("  " + line for line in actions.strip().splitlines())
        model_text += "\nend actions\n"

    if model.events:
        model_text += (
            "\n" + "\n".join(_event_metadata_block(model, species_to_pattern)) + "\n"
        )

    source_metadata_block = _source_metadata_block(model)
    if source_metadata_block:
        model_text += "\n" + "\n".join(source_metadata_block) + "\n"

    # Some SBML operators are lowered by the BNGL compatibility layer (for
    # example floor -> rint/piecewise). The generated BNGL is executable, but
    # the C++ SBML writer cannot serialize these calls losslessly. Record the
    # limitation on the model so validation reports it globally rather than
    # accepting a malformed or semantically altered round trip.
    for function_name in ("gcd", "lcm", "rint", "delay", "rateOf"):
        if re.search(rf"\b{re.escape(function_name)}\s*\(", model_text, re.IGNORECASE):
            _record_import_warning(
                model,
                f'Generated BNGL math function "{function_name}" is not '
                "losslessly representable in the C++ SBML writer/libRoadRunner path.",
                category="mathml",
                severity="dropped",
            )

    has_multi = bool(
        model.multi_molecule_types
        or model.multi_complex_patterns
        or model.multi_seed_patterns
        or model.multi_species_patterns
        or model.multi_reaction_mappings
    )
    if model.import_warnings or has_multi:
        model_text += "\n# ==== SBML IMPORT NOTES ====\n"
        for warning in model.import_warnings:
            category = warning.get("category", "import")
            severity = warning.get("severity", "info")
            message = warning.get("message", "")
            count = warning.get("count", 1)
            suffix = f" (x{count})" if count and count != 1 else ""
            model_text += f"# [{severity}] {category}: {message}{suffix}\n"
        if model.multi_molecule_types and not model.multi_executable:
            model_text += "# SBML Multi molecule-type skeletons (reference only):\n"
            for molecule_type in model.multi_molecule_types:
                model_text += f"#     {molecule_type}\n"
        if model.multi_complex_patterns and not model.multi_executable:
            model_text += "# SBML Multi bonded complex patterns (reference only):\n"
            for pattern in model.multi_complex_patterns:
                model_text += f"#     {pattern}\n"
        if model.multi_seed_patterns and not model.multi_executable:
            model_text += "# SBML Multi seed patterns (reference only):\n"
            for pattern in model.multi_seed_patterns:
                model_text += f"#     {pattern}\n"
        if model.multi_executable:
            model_text += (
                "# SBML Multi species types, patterns, and product mappings were "
                "translated into the executable BNGL model.\n"
            )
        elif has_multi:
            model_text += (
                "# Multi structures are not yet fed into the simulated network.\n"
            )
        model_text += "# ============================\n"

    model.import_warnings = [
        coerce_import_warning(warning) for warning in model.import_warnings
    ]

    warnings = [
        str(warning.get("message", ""))
        for warning in model.import_warnings
        if warning.get("message")
    ]
    return BNGLGenerationResult(model_text, observable_map, warnings)


# Preserve the TypeScript reference spelling for direct facade callers.
bnglFunction = bngl_function
bnglReaction = bngl_reaction
checkMassAction = check_mass_action
curateParameters = curate_parameters
extendFunction = extend_function
generateBNGL = generate_bngl
inlineSBMLFunctions = inline_sbml_functions
processReactionRate = process_reaction_rate
splitReversibleRate = split_reversible_rate
writeParameters = write_parameters
writeCompartments = write_compartments
writeMoleculeTypes = write_molecule_types
writeSeedSpecies = write_seed_species
writeObservables = write_observables
writeFunctions = write_functions
writeReactionRules = write_reaction_rules
writeReactionRulesFlat = write_reaction_rules_flat
writeReactionRulesAtomized = write_reaction_rules_atomized
writeReactionRulesFlat_V2 = write_reaction_rules_flat_v2


__all__ = [
    "BNGLGenerationResult",
    "ProcessedRate",
    "bnglFunction",
    "bngl_function",
    "bnglReaction",
    "bngl_reaction",
    "convert_math_expression",
    "checkMassAction",
    "check_mass_action",
    "curateParameters",
    "curate_parameters",
    "extendFunction",
    "extend_function",
    "generateBNGL",
    "generate_bngl",
    "inlineSBMLFunctions",
    "inline_sbml_functions",
    "processReactionRate",
    "process_reaction_rate",
    "ReversibleRateSplit",
    "splitReversibleRate",
    "split_reversible_rate",
    "writeCompartments",
    "write_compartments",
    "writeFunctions",
    "write_functions",
    "writeMoleculeTypes",
    "write_molecule_types",
    "writeObservables",
    "write_observables",
    "writeParameters",
    "write_parameters",
    "writeReactionRules",
    "write_reaction_rules",
    "writeReactionRulesFlat",
    "write_reaction_rules_flat",
    "writeReactionRulesAtomized",
    "write_reaction_rules_atomized",
    "writeReactionRulesFlat_V2",
    "write_reaction_rules_flat_v2",
    "writeSeedSpecies",
    "write_seed_species",
]
