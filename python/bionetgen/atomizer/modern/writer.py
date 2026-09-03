"""BNGL writer for the Playground atomizer port."""

from __future__ import annotations

import math
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .events import EventTranslationContext, synthesize_event_actions
from .rate_rule_constants import (
    RATE_RULE_META_PREFIX,
    RATE_RULE_NEG_PREFIX,
    RATE_RULE_POS_PREFIX,
    SYNTH_RATE_RULE_SPECIES_PREFIX,
)
from .structures import Molecule, Species
from .helpers import logger
from .types import (
    BNGL_LEXER_KEYWORDS,
    SBMLModel,
    SBMLReaction,
    SCTEntry,
    SeedSpeciesEntry,
    SpeciesCompositionTable,
    get_kinetic_math,
    standardize_name,
)

_PROTECTED_BUILTIN_OPERANDS = frozenset({"time", "_pi", "_e", "true", "false"})

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
        value = re.sub(r"^([A-Za-z_][A-Za-z0-9_]*)", r"M_\1", value)
        if "@" not in value and compartment:
            value += "@" + standardize_name(compartment)
        molecules.append(value)
    return ".".join(sorted(molecules))


def _number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _evaluate_arithmetic(expression: str) -> Optional[float]:
    """Evaluate only the arithmetic grammar accepted for constant seed folding."""

    tokens = re.findall(
        r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+\-*/^()]",
        expression,
    )
    if not tokens or "".join(tokens) != re.sub(r"\s+", "", expression):
        return None

    position = 0

    def peek() -> Optional[str]:
        return tokens[position] if position < len(tokens) else None

    def precedence(operator: str) -> int:
        return {"+": 1, "-": 1, "*": 2, "/": 2, "^": 3}.get(operator, 0)

    def parse_expression(min_precedence: int) -> float:
        nonlocal position
        token = peek()
        if token is None:
            raise ValueError("missing operand")
        if token == "(":
            position += 1
            value = parse_expression(0)
            if peek() != ")":
                raise ValueError("unbalanced parentheses")
            position += 1
        elif token in {"+", "-"}:
            position += 1
            operand = parse_expression(3)
            value = operand if token == "+" else -operand
        else:
            try:
                value = float(token)
            except (TypeError, ValueError) as error:
                raise ValueError("invalid number") from error
            position += 1

        while position < len(tokens):
            operator = peek()
            if operator == ")":
                break
            if operator is None:
                break
            current_precedence = precedence(operator)
            if current_precedence == 0 or current_precedence < min_precedence:
                break
            position += 1
            right = parse_expression(
                current_precedence if operator == "^" else current_precedence + 1
            )
            if operator == "+":
                value += right
            elif operator == "-":
                value -= right
            elif operator == "*":
                value *= right
            elif operator == "/":
                value /= right
            else:
                value = value**right
        return value

    try:
        value = parse_expression(0)
        if position != len(tokens) or not math.isfinite(value):
            return None
        return value
    except (ArithmeticError, ValueError, OverflowError):
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

    # SBML log(base, value) is distinct from the one-argument natural log.
    result = _replace_nested_function(
        result,
        "log",
        lambda args: (
            f"(ln({args[1]})/ln({args[0]}))"
            if len(args) >= 2
            else f"ln({args[0]})" if args else "log()"
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
            else f"(({args[0]})^(1/2))" if args else "root()"
        ),
    )
    result = _replace_nested_function(
        result,
        "floor",
        lambda args: (
            f"(rint({args[0]}) - if(rint({args[0]}) > ({args[0]}), 1, 0))"
            if args
            else "floor()"
        ),
    )
    result = _replace_nested_function(
        result,
        "ceiling",
        lambda args: (
            f"(rint({args[0]}) + if(rint({args[0]}) < ({args[0]}), 1, 0))"
            if args
            else "ceiling()"
        ),
    )
    result = _replace_nested_function(
        result,
        "ceil",
        lambda args: (
            f"(rint({args[0]}) + if(rint({args[0]}) < ({args[0]}), 1, 0))"
            if args
            else "ceil()"
        ),
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
                f"({args[0]} {operator} {args[1]})"
                if len(args) >= 2
                else f"{function}({', '.join(args)})"
            ),
        )
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
    result = re.sub(
        r"\bexponentiale\b", "2.71828182845905", result, flags=re.IGNORECASE
    )
    result = re.sub(r"\btrue\b", "1", result, flags=re.IGNORECASE)
    result = re.sub(r"\bfalse\b", "0", result, flags=re.IGNORECASE)
    result = re.sub(r"\btime\b(?!\s*\()", "time()", result)
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
                expanded = re.sub(rf"\b{re.escape(formal)}\b", f"({actual})", expanded)
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

    for parameter, value in parameter_dict.items():
        replacement = _number(value)
        result = re.sub(rf"\b{re.escape(parameter)}\b", replacement, result)
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
    is_saturation = bool(re.search(r"\b(?:Sat|MM|Hill)\s*\(", result))

    def map_token(match: re.Match) -> str:
        token = match.group(1)
        end = match.end()
        if re.match(r"\s*\(", result[end:]):
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
        elif standard in species_with_conc_functions:
            replacement = "_c_" + standard + "()"
        else:
            replacement = standard + "()"
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
    species_tokens = list(reactant_ids)
    remaining: List[str] = []
    removed = 0
    for piece in pieces:
        if piece in species_tokens:
            species_tokens.remove(piece)
            removed += 1
        else:
            remaining.append(piece)
    if removed != len(reactant_ids):
        return expression.strip() or "1"
    return " * ".join(remaining) if remaining else "1"


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


def _prepared_kinetic_math(reaction: SBMLReaction, model: SBMLModel) -> str:
    """Inline functions and substitute reaction-local parameters once."""

    math_expression = extend_function(
        get_kinetic_math(reaction.kinetic_law),
        {},
        model.function_definitions,
    )
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
            math_expression = re.sub(
                rf"\b{re.escape(str(parameter_id))}\b",
                _curated_parameter_value(model, str(parameter_id), parameter_value),
                math_expression,
            )
    return math_expression


def _rate_for_reaction(
    reaction: SBMLReaction,
    model: SBMLModel,
    conversion_factor: Optional[str] = None,
    observable_converted_rules: Optional[Set[str]] = None,
    reactant_structures: Optional[Mapping[str, Species]] = None,
    reactant_ids: Optional[Sequence[str]] = None,
    prepared_math: Optional[str] = None,
) -> str:
    def apply_conversion(rate: str) -> str:
        if conversion_factor is None:
            return rate
        return f"{conversion_factor} * ({rate})"

    math = (
        prepared_math
        if prepared_math is not None
        else _prepared_kinetic_math(reaction, model)
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
    species_map = {species_id: species_id for species_id in model.species}
    assignment_variables = {
        rule.variable
        for rule in model.rules
        if rule.variable and rule.type in {"assignment", "rate"}
    }
    observable_converted_rules = observable_converted_rules or set()
    concentration_names = {
        standardize_name(species_id)
        for species_id, species in model.species.items()
        if not species.has_only_substance_units
    }

    # BNG2-exported elementary SBML laws may carry the reaction compartment as
    # a leading volume factor (for example ``cell * k * A``).  The Playground
    # writer removes that factor before normalizing explicit reactant factors;
    # otherwise the emitted BNGL rate constant is multiplied by the volume a
    # second time.  Restrict this bounded cleanup to elementary laws that
    # actually mention a reactant, so zero-order fluxes retain their volume
    # semantics.
    has_saturation = bool(re.search(r"\b(?:Sat|MM|Hill)\s*\(", math))
    nonlinear = has_saturation or "/" in math
    if (
        not has_saturation
        and reactants
        and any(
            re.search(rf"\b{re.escape(standardize_name(species_id))}\b", math)
            for species_id in reactants
        )
    ):
        for compartment_id in model.compartments:
            standardized = standardize_name(str(compartment_id))
            math = re.sub(
                rf"\s*\*\s*__compartment_{re.escape(standardized)}__\s*",
                " ",
                math,
            )
            math = re.sub(
                rf"\s*\*\s*{re.escape(str(compartment_id))}\b\s*",
                " ",
                math,
            )
            math = re.sub(
                rf"\s*/\s*__compartment_{re.escape(standardized)}__\s*",
                " ",
                math,
            )
            math = re.sub(
                rf"\s*/\s*{re.escape(str(compartment_id))}\b\s*",
                " ",
                math,
            )
            math = re.sub(
                rf"^\s*__compartment_{re.escape(standardized)}__\s*\*\s*",
                "",
                math,
            )
            math = re.sub(
                rf"^\s*{re.escape(str(compartment_id))}\b\s*\*\s*",
                "",
                math,
            )
        math = math.strip() or "1"
        nonlinear = has_saturation or "/" in math

    # The Playground writer keeps nonlinear laws intact and maps their species
    # operands to concentration functions (or amount observables for Sat/MM/
    # Hill).  Only elementary mass-action factors are removed before that
    # mapping; stripping a substrate from a saturation or rational law changes
    # its biology.
    if nonlinear:
        return apply_conversion(
            bngl_function(
                math,
                reaction.name or reaction.id,
                reactants,
                list(model.compartments),
                assignment_rule_variables=assignment_variables,
                observable_converted_rules=observable_converted_rules,
                species_with_conc_functions=concentration_names,
                sbml_to_bngl_id=species_map,
            )
        )

    converted = convert_math_expression(math)
    stripped = _strip_mass_action_factors(converted, reactants)
    if reactant_structures:
        stripped = _extract_statistical_factor(stripped, reactant_structures)
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
        )
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

    def reaction_flux(reaction_id: str, reaction: SBMLReaction) -> Optional[str]:
        if reaction_id in cache:
            return cache[reaction_id]
        math_expression = get_kinetic_math(reaction.kinetic_law)
        if not math_expression.strip():
            cache[reaction_id] = None
            return None
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
                math_expression = re.sub(
                    rf"\b{re.escape(str(parameter_id))}\b",
                    _curated_parameter_value(model, str(parameter_id), parameter_value),
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
        changed = False
        for reaction_id, reaction in model.reactions.items():
            reaction_id = str(reaction_id)
            if reaction_id in defined or standardize_name(reaction_id) in defined:
                continue
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


def _conversion_factor_for_reaction(
    reaction: SBMLReaction, model: SBMLModel
) -> Optional[str]:
    """Resolve one BNGL-wide scalar, or report an unrepresentable mixed flux."""

    model_factor = getattr(model, "conversion_factor", None) or None
    effective: List[Optional[str]] = []
    for reference in [*reaction.reactants, *reaction.products]:
        if reference.species == "EmptySet":
            continue
        species = model.species.get(reference.species)
        species_factor = (
            getattr(species, "conversion_factor", None) if species else None
        )
        effective.append(species_factor or model_factor)
    if not effective:
        return None
    unique = set(effective)
    if len(unique) != 1:
        _record_import_warning(
            model,
            f'Reaction "{reaction.id}" has species with differing '
            "conversionFactors; a single BNGL rule cannot apply different "
            "scalars per species, so the factor was not applied.",
        )
        return None
    factor_id = effective[0]
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


def write_parameters(
    model: SBMLModel, assignment_variables: Optional[Set[str]] = None
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
        if name in assignment_variables:
            continue
        lines.append(
            f"{name} {_curated_parameter_value(model, parameter_id, parameter.value)}"
        )
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
        value = declaration.str2().split("@", 1)[0]
        if "(" not in value:
            value += "()"
        lines.append("M_" + value)
    return sorted(dict.fromkeys(lines))


def _add_seed_symbol(symbols: Dict[str, float], name: object, value: object) -> bool:
    number = _numeric_value(value)
    if number is None or name is None:
        return False
    text = str(name)
    symbols[text] = number
    symbols[standardize_name(text)] = number
    return True


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

        for assignment in model.initial_assignments:
            symbol = getattr(assignment, "symbol", "")
            if is_species(symbol):
                continue
            if symbol in symbols or standardize_name(symbol) in symbols:
                continue
            changed = add_resolved(symbol, getattr(assignment, "math", "")) or changed

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
    for seed in seed_species:
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
    for (fixed, _group_pattern), (pattern, concentration) in grouped.items():
        lines.append(f"{'$' if fixed else ''}{pattern} {concentration}")
    return lines, sbml_to_pattern, pattern_to_id


def write_observables(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    species_to_pattern: Mapping[str, str],
) -> Tuple[List[str], Dict[str, str]]:
    lines = []
    observable_map: Dict[str, str] = OrderedDict()
    used = set()
    for species_id, species in model.species.items():
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

    # A simple assignment rule such as ``total = A + 2 * B`` is a BNGL
    # observable, not a dynamic function.  Preserve this losslessly when all
    # terms resolve to imported species patterns; more complex rules continue
    # through the function writer below.
    for rule in model.rules:
        if rule.type != "assignment" or not rule.variable or not rule.math:
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
        # Remove only the direct species observables with this exact name;
        # ``name_amt`` is a distinct observable and must also be replaced.
        lines = [
            line
            for line in lines
            if not line.startswith(f"Species {name} ")
            and not line.startswith(f"Species {name}_amt ")
        ]
        expanded = []
        for pattern, coefficient in pattern_counts.items():
            expanded.extend([pattern] * coefficient)
        pattern_string = " ".join(expanded)
        lines.append(f"Molecules {name} {pattern_string}")
        lines.append(f"Molecules {name}_amt {pattern_string}")
    return lines, observable_map


def _rewrite_zero_argument_calls(expression: str, names: Iterable[str]) -> str:
    result = expression
    for name in names:
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


def write_functions(
    model: SBMLModel,
    synthetic_rate_rule_variables: Optional[Set[str]] = None,
    skip_assignment_rules: Optional[Set[str]] = None,
    keep_parameterized: bool = False,
) -> List[str]:
    lines = []
    zero_argument_functions = []
    emitted_names: Set[str] = set()
    synthetic_rate_rule_variables = synthetic_rate_rule_variables or set()
    skip_assignment_rules = skip_assignment_rules or set()
    assignment_rule_variables = {
        rule.variable
        for rule in model.rules
        if rule.variable and rule.type in {"assignment", "rate"}
    }
    rate_rule_variables = {
        standardize_name(rule.variable)
        for rule in model.rules
        if rule.variable and rule.type in {"assignment", "rate"}
    }
    species_map = {species_id: species_id for species_id in model.species}
    for variable in synthetic_rate_rule_variables:
        # Synthetic rate-rule state species use the SBML variable as their
        # lookup key, while their generated molecule pattern is carried by
        # the observable/seed maps in generate_bngl().
        species_map[variable] = variable
        species_map[standardize_name(variable)] = variable
    concentration_names = {
        standardize_name(species_id)
        for species_id, species in model.species.items()
        if not species.has_only_substance_units
    }

    # SBML species are amount-valued in the BNGL observable block.  The
    # concentration helper mirrors the Playground writer and is required for
    # rational/nonlinear kinetic laws in compartments with volume != 1.
    for species_id, species in model.species.items():
        name = standardize_name(species_id)
        function_name = "_c_" + name
        if function_name in emitted_names:
            continue
        emitted_names.add(function_name)
        if species.has_only_substance_units or not species.compartment:
            body = name
        else:
            body = (
                f"{name} / __compartment_" f"{standardize_name(species.compartment)}__"
            )
        lines.append(f"{function_name}() = {body}")

    for function_id, function in model.function_definitions.items():
        name = standardize_name(function.name or function_id)
        if function.arguments and not keep_parameterized:
            # BNG2/BNGL function blocks do not consistently support
            # argument-taking SBML definitions.  Inline those definitions at
            # call sites, as the Playground writer does.
            continue
        argument_names = []
        body = function.math
        for index, argument in enumerate(function.arguments):
            base = standardize_name(argument or f"arg{index + 1}")
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
    for rule in _ordered_assignment_rules(model.rules):
        if (
            rule.variable in skip_assignment_rules
            or standardize_name(rule.variable) in skip_assignment_rules
        ):
            continue
        body = extend_function(
            _inline_reaction_fluxes(
                rule.math,
                model,
                assignment_rule_variables,
                skip_assignment_rules,
                concentration_names,
                species_map,
            ),
            {
                parameter_id: parameter.value
                for parameter_id, parameter in model.parameters.items()
            },
            model.function_definitions,
        )
        body = _map_compartment_references(convert_math_expression(body), model)
        body = _rewrite_zero_argument_calls(body, zero_argument_functions)
        lines.append(f"{standardize_name(rule.variable)}() = {body}")

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
            ),
            {},
            model.function_definitions,
        )
        body = bngl_function(
            body,
            rule.variable,
            [],
            list(model.compartments),
            assignment_rule_variables=rate_rule_variables,
            observable_converted_rules=skip_assignment_rules,
            species_with_conc_functions=concentration_names,
            sbml_to_bngl_id=species_map,
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
) -> str:
    entry = sct.entries.get(species_id)
    species = model.species.get(species_id)
    if entry is not None:
        return _pattern(entry.structure, species.compartment if species else "")
    name = standardize_name(species.name if species else species_id)
    return "M_" + name + "()"


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
) -> List[str]:
    lines = []
    used_labels = set()
    for reaction_id, reaction in model.reactions.items():
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
        for reference in [*reaction.reactants, *reaction.products]:
            if (
                reference.species != "EmptySet"
                and reference.variable_stoichiometry
                and math.isfinite(reference.stoichiometry)
                and reference.stoichiometry >= 0
                and abs(reference.stoichiometry - round(reference.stoichiometry))
                <= 1e-9
            ):
                _record_import_warning(
                    model,
                    f'Reaction "{reaction_id}" has variable stoichiometry for '
                    f'"{reference.species}"; BNGL uses the parsed fixed value '
                    f"{reference.stoichiometry:g}.",
                    category="stoichiometry",
                    severity="approximated",
                )
        unsupported = next(
            (
                reference
                for reference in [*reaction.reactants, *reaction.products]
                if reference.species != "EmptySet"
                and (
                    not math.isfinite(reference.stoichiometry)
                    or reference.stoichiometry < 0
                    or abs(reference.stoichiometry - round(reference.stoichiometry))
                    > 1e-9
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
        reactants: List[str] = []
        products: List[str] = []
        for reference in reaction.reactants:
            if reference.species == "EmptySet":
                continue
            reactants.extend(
                [_reaction_pattern(reference.species, sct, model)]
                * int(round(reference.stoichiometry))
            )
        for reference in reaction.products:
            if reference.species == "EmptySet":
                continue
            products.extend(
                [_reaction_pattern(reference.species, sct, model)]
                * int(round(reference.stoichiometry))
            )
        label = standardize_name(reaction.name or reaction_id)
        candidate = label
        suffix = 2
        while candidate in used_labels:
            candidate = f"{label}_{suffix}"
            suffix += 1
        used_labels.add(candidate)
        conversion_factor = _conversion_factor_for_reaction(reaction, model)
        structures = {
            species_id: entry.structure
            for species_id, entry in sct.entries.items()
            if entry.structure is not None
        }
        prepared_math = _prepared_kinetic_math(reaction, model)
        split = (
            _split_reversible_rate(convert_math_expression(prepared_math))
            if reaction.reversible
            else None
        )
        if split is not None:
            forward_ids = [
                reference.species
                for reference in reaction.reactants
                if reference.species != "EmptySet"
                for _ in range(max(0, int(round(reference.stoichiometry))))
            ]
            reverse_ids = [
                reference.species
                for reference in reaction.products
                if reference.species != "EmptySet"
                for _ in range(max(0, int(round(reference.stoichiometry))))
            ]
            forward_rate = _rate_for_reaction(
                reaction,
                model,
                conversion_factor,
                observable_converted_rules,
                {
                    species_id: structures[species_id]
                    for species_id in forward_ids
                    if species_id in structures
                },
                reactant_ids=forward_ids,
                prepared_math=split[0],
            )
            reverse_rate = _rate_for_reaction(
                reaction,
                model,
                conversion_factor,
                observable_converted_rules,
                {
                    species_id: structures[species_id]
                    for species_id in reverse_ids
                    if species_id in structures
                },
                reactant_ids=reverse_ids,
                prepared_math=split[1],
            )
            if _has_denominator_issue(
                forward_rate, forward_ids
            ) or _has_denominator_issue(reverse_rate, reverse_ids):
                rate = _rate_for_reaction(
                    reaction,
                    model,
                    conversion_factor,
                    observable_converted_rules,
                    structures,
                    prepared_math=prepared_math,
                )
                arrow = "->"
            else:
                rate = f"{forward_rate}, {reverse_rate}"
                arrow = "<->"
        else:
            arrow = "->"
            rate = _rate_for_reaction(
                reaction,
                model,
                conversion_factor,
                observable_converted_rules,
                structures,
                prepared_math=prepared_math,
            )

        # A time-only rate has no species/observable marker for BNG2's
        # functional-rate path.  Keep it live by emitting a zero-argument
        # function, matching the Playground writer's bounded time-rate port.
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
        lines.append(
            f"{candidate}: {' + '.join(reactants) if reactants else '0'} "
            f"{arrow} {' + '.join(products) if products else '0'} {rate}"
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
        pattern = _reaction_pattern(target_id, sct, model)
        name = standardize_name(rule.variable)
        lines.append(
            f"__rate_rule_in_{name}: 0 -> {pattern} {RATE_RULE_POS_PREFIX}{name}()"
        )
        lines.append(
            f"__rate_rule_out_{name}: {pattern} -> 0 {RATE_RULE_NEG_PREFIX}{name}()"
        )
    return lines


def generate_bngl(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    molecule_types: Sequence[Molecule],
    seed_species: Sequence[SeedSpeciesEntry],
    atomize: bool = False,
    actions: str = "",
    t_end: float = 10,
    n_steps: int = 100,
) -> Tuple[str, Mapping[str, str]]:
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
        for rule in model.rules
        if rule.type == "assignment" and rule.variable
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
        _section("parameters", write_parameters(model, assignment_variables)),
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
    for variable in synthetic_rate_rule_variables:
        pattern = species_to_pattern.get(variable)
        if pattern:
            observable_lines.append(
                f"Species {standardize_name(variable)}_amt {pattern}"
            )
    if observable_lines:
        sections.append(_section("observables", observable_lines))
    function_lines = write_functions(
        model, synthetic_rate_rule_variables, observable_rule_variables
    )
    time_rate_functions: List[str] = []
    sections.append(
        _section(
            "reaction rules",
            write_reaction_rules(
                model,
                augmented_sct,
                atomize,
                observable_converted_rules=observable_rule_variables,
                time_rate_functions=time_rate_functions,
            ),
        )
    )
    function_lines.extend(time_rate_functions)
    if function_lines:
        sections.insert(-1, _section("functions", function_lines))
    sections.append("end model")
    model_text = "\n\n".join(section for section in sections if section != "") + "\n"

    event_result = None
    if model.events:
        event_result = synthesize_event_actions(
            model.events,
            EventTranslationContext(
                resolve_species_pattern=lambda species_id: species_to_pattern.get(
                    species_id
                ),
                resolve_param=lambda identifier: (
                    model.parameters[identifier].value
                    if identifier in model.parameters
                    else (
                        model.compartments[identifier].size
                        if identifier in model.compartments
                        else None
                    )
                ),
                is_param=lambda identifier: identifier in model.parameters
                or identifier in model.compartments,
                method=(
                    "ssa"
                    if re.search(
                        r"simulate_ssa|method\s*=>\s*[\"']?ssa", actions or "", re.I
                    )
                    else "ode"
                ),
                base_t_end=float(t_end),
                base_steps=max(1, int(n_steps)),
            ),
        )

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
                    if isinstance(assignment, dict):
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

    has_multi = bool(
        model.multi_molecule_types
        or model.multi_complex_patterns
        or model.multi_seed_patterns
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
        if model.multi_molecule_types:
            model_text += "# SBML Multi molecule-type skeletons (reference only):\n"
            for molecule_type in model.multi_molecule_types:
                model_text += f"#     {molecule_type}\n"
        if model.multi_complex_patterns:
            model_text += "# SBML Multi bonded complex patterns (reference only):\n"
            for pattern in model.multi_complex_patterns:
                model_text += f"#     {pattern}\n"
        if model.multi_seed_patterns:
            model_text += "# SBML Multi seed patterns (reference only):\n"
            for pattern in model.multi_seed_patterns:
                model_text += f"#     {pattern}\n"
        if has_multi:
            model_text += (
                "# Multi structures are not yet fed into the simulated network.\n"
            )
        model_text += "# ============================\n"

    return model_text, observable_map


# Preserve the TypeScript reference spelling for direct facade callers.
bnglFunction = bngl_function
bnglReaction = bngl_reaction
curateParameters = curate_parameters
generateBNGL = generate_bngl
inlineSBMLFunctions = inline_sbml_functions
splitReversibleRate = split_reversible_rate


__all__ = [
    "bnglFunction",
    "bngl_function",
    "bnglReaction",
    "bngl_reaction",
    "convert_math_expression",
    "curateParameters",
    "curate_parameters",
    "extend_function",
    "generateBNGL",
    "generate_bngl",
    "inlineSBMLFunctions",
    "inline_sbml_functions",
    "ReversibleRateSplit",
    "splitReversibleRate",
    "split_reversible_rate",
    "write_compartments",
    "write_functions",
    "write_molecule_types",
    "write_observables",
    "write_parameters",
    "write_reaction_rules",
    "write_seed_species",
]
