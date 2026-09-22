"""Pure-XML SBML parser for the Playground-derived atomizer.

The parser deliberately accepts SBML as a string, matching the
Playground implementation while keeping the modern path independent of the
optional and platform-sensitive libSBML SWIG bindings.
"""

from __future__ import annotations

import math
import re
import base64
import xml.etree.ElementTree as ET
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .types import (
    AnnotationInfo,
    SBMLEvent,
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLInitialAssignment,
    SBMLKineticLaw,
    SBMLModel,
    coerce_import_warning,
    SBMLModifierSpeciesReference,
    SBMLMultiComponentMap,
    SBMLParameter,
    SBMLReaction,
    SBMLRule,
    SBMLSpecies,
    SBMLSpeciesReference,
    standardize_name,
)
from .multi import parse_multi_package
from .units import apply_unit_scaling
from .helpers import logger


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: Any, name: str) -> Iterable[Any]:
    return (child for child in list(element) if _local_name(child.tag) == name)


def _first_child(element: Any, name: str) -> Optional[Any]:
    return next(iter(_children(element, name)), None)


def _attribute(element: Any, name: str, default: Any = None) -> Any:
    for key, value in getattr(element, "attrib", {}).items():
        if key == name or key.rsplit("}", 1)[-1] == name:
            return value
    return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _formula_from_math(math_node: Any, libsbml: Any) -> str:
    if math_node is None:
        return ""
    try:
        formula = libsbml.formulaToString(math_node)
    except Exception:
        formula = ""
    if formula:
        return str(formula).strip()
    return ""


def _mathml_text(element: Optional[Any]) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _raw_child_xml(element: Optional[Any], name: str) -> str:
    """Serialize source metadata children without treating them as kinetics."""

    if element is None:
        return ""
    values = [
        ET.tostring(child, encoding="unicode") for child in _children(element, name)
    ]
    return "\n".join(value.strip() for value in values if value.strip())


def _source_metadata(element: Optional[Any]) -> Dict[str, Any]:
    if element is None:
        return {
            "metaid": None,
            "sbo_term": None,
            "notes_xml": "",
            "annotation_xml": "",
        }
    return {
        "metaid": _attribute(element, "metaid"),
        "sbo_term": _attribute(element, "sboTerm"),
        "notes_xml": _raw_child_xml(element, "notes"),
        "annotation_xml": _raw_child_xml(element, "annotation"),
    }


def _source_metadata_payload(element: Optional[Any]) -> str:
    """Read the optional opaque metadata annotation emitted by BNG3."""

    annotation = _first_child(element, "annotation") if element is not None else None
    if annotation is None:
        return ""
    for candidate in annotation.iter():
        if _local_name(getattr(candidate, "tag", "")) != "sourceMetadata":
            continue
        tag = str(getattr(candidate, "tag", ""))
        namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
        if namespace and namespace != "https://bionetgen.org/sbml":
            continue
        value = "".join(candidate.itertext()).strip()
        if str(_attribute(candidate, "encoding", "")).lower() == "base64":
            try:
                return base64.b64decode(value, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return ""
        return value
    return ""


def _declared_package_uris(sbml_string: str) -> Dict[str, str]:
    """Extract package namespace declarations, including empty packages."""

    result: Dict[str, str] = OrderedDict()
    pattern = re.compile(
        r"xmlns(?::[A-Za-z0-9_]+)?\s*=\s*['\"]"
        r"(https?://www\.sbml\.org/sbml/level3/version\d+/"
        r"([a-z][a-z0-9_]*)/version\d+)['\"]",
        re.IGNORECASE,
    )
    for match in pattern.finditer(sbml_string):
        result[match.group(2).lower()] = match.group(1)
    return result


def _mathml_to_formula(element: Optional[Any], parenthesize: bool = False) -> str:
    """Translate the MathML subset used by SBML into stable infix/function text."""

    if element is None:
        return ""
    tag = _local_name(element.tag)
    children = [child for child in list(element) if _local_name(child.tag) != "#text"]

    if tag in {"math", "semantics", "annotation-xml", "condition"}:
        return next(
            (
                expression
                for child in children
                if (expression := _mathml_to_formula(child, parenthesize).strip())
            ),
            "",
        )
    if tag in {"ci", "csymbol"}:
        definition_url = str(_attribute(element, "definitionURL", "") or "").lower()
        if "symbols/time" in definition_url:
            return "time"
        if "symbols/avogadro" in definition_url:
            return "__Avogadro__"
        if "symbols/delay" in definition_url:
            return "delay"
        if "symbols/rateof" in definition_url:
            return "rateOf"
        content = _mathml_text(element)
        representation = str(_attribute(element, "representationType", "") or "")
        if representation == "sum":
            return f"__SBML_MULTI_SUM__{content}__"
        if representation == "numericValue":
            return f"__SBML_MULTI_NUMERIC__{content}__"
        return content
    if tag == "cn":
        chunks: List[str] = []
        if element.text and element.text.strip():
            chunks.append(element.text.strip())
        for child in children:
            if _local_name(child.tag) == "sep":
                if child.tail and child.tail.strip():
                    chunks.append(child.tail.strip())
            elif child.tail and child.tail.strip():
                chunks.append(child.tail.strip())
        if len(chunks) >= 2 and any(
            _local_name(child.tag) == "sep" for child in children
        ):
            number_type = str(_attribute(element, "type", "") or "").lower()
            if number_type in {"e-notation", "enotation"}:
                return f"({chunks[0]} * 10^({chunks[1]}))"
            return f"({chunks[0]} / {chunks[1]})"
        return _mathml_text(element)
    if tag == "true":
        return "1"
    if tag == "false":
        return "0"
    if tag == "pi":
        return "3.141592653589793"
    if tag == "exponentiale":
        return "2.718281828459045"
    if tag == "infinity":
        return "1e308"
    if tag == "notanumber":
        return "0"
    if tag == "lambda":
        # SBML function bodies are lambda(bvar..., body).  Bound-variable
        # declarations are metadata; the final non-bvar child is the body.
        expressions = [
            _mathml_to_formula(child, parenthesize).strip()
            for child in children
            if _local_name(child.tag) != "bvar"
        ]
        return expressions[-1] if expressions else ""
    if tag in {"bvar", "piece", "otherwise"}:
        return next(
            (
                expression
                for child in children
                if (expression := _mathml_to_formula(child, parenthesize).strip())
            ),
            _mathml_text(element) if tag == "bvar" else "",
        )
    if tag == "piecewise":
        branches: List[tuple[str, str]] = []
        fallback = "0"
        for part in children:
            part_tag = _local_name(part.tag)
            part_children = [
                child for child in list(part) if _local_name(child.tag) != "#text"
            ]
            if part_tag == "piece" and len(part_children) >= 2:
                wrapped_condition = next(
                    (
                        child
                        for child in part_children
                        if _local_name(child.tag) == "condition"
                    ),
                    None,
                )
                if wrapped_condition is not None:
                    value_node = next(
                        (
                            child
                            for child in part_children
                            if child is not wrapped_condition
                        ),
                        None,
                    )
                    condition_node = wrapped_condition
                else:
                    value_node, condition_node = part_children[:2]
                value = _mathml_to_formula(value_node)
                condition = _mathml_to_formula(condition_node)
                branches.append((value, condition))
            elif part_tag == "otherwise" and part_children:
                fallback = _mathml_to_formula(part_children[0])
        result = fallback
        for value, condition in reversed(branches):
            result = f"if({condition}, {value}, {result})"
        return result
    if tag == "apply":
        if not children:
            return ""
        operator_node = children[0]
        operator = _local_name(operator_node.tag)
        if operator in {"ci", "csymbol"}:
            function_name = _mathml_to_formula(operator_node)
            args = [_mathml_to_formula(child, True) for child in children[1:]]
            if operator == "csymbol":
                definition_url = str(
                    _attribute(operator_node, "definitionURL", "") or ""
                ).lower()
                if (
                    "symbols/delay" in definition_url
                    or "symbols/rateof" in definition_url
                ):
                    operand = _mathml_text(operator_node)
                    # Some libAntimony exports put the first operand in the
                    # csymbol text. ``rateOf`` has one argument, so a child
                    # already supplies it; ``delay`` has two arguments and
                    # still needs the csymbol text when only one child is
                    # present. Do not duplicate the rateOf operand.
                    needs_operand = (
                        not args
                        if "symbols/rateof" in definition_url
                        else len(args) < 2
                    )
                    if (
                        needs_operand
                        and operand
                        and operand.lower()
                        not in {function_name.lower(), "delay", "rateof"}
                    ):
                        args.insert(0, operand)
            return (
                f"{function_name}({', '.join(args)})"
                if function_name
                else ", ".join(args)
            )

        degree = next(
            (child for child in children[1:] if _local_name(child.tag) == "degree"),
            None,
        )
        logbase = next(
            (child for child in children[1:] if _local_name(child.tag) == "logbase"),
            None,
        )
        args = [
            _mathml_to_formula(child, True)
            for child in children[1:]
            if _local_name(child.tag) not in {"degree", "logbase"}
        ]
        if operator == "and" and not args:
            return "1"
        if operator in {"or", "xor"} and not args:
            return "0"
        if operator == "not" and not args:
            return "1"
        if operator in {"plus", "times", "minus", "divide", "power"}:
            if not args:
                return {
                    "plus": "0",
                    "times": "1",
                    "minus": "0",
                    "divide": "1",
                    "power": "1",
                }[operator]
            symbol = {
                "plus": "+",
                "times": "*",
                "minus": "-",
                "divide": "/",
                "power": "^",
            }[operator]
            if operator == "minus" and len(args) == 1:
                return f"-({args[0]})"
            if operator == "power" and len(args) >= 2:
                # The exponent is an expression, not a flat token.  Without
                # grouping, MathML e^(-t) becomes ``e ^ -1 * t`` and changes
                # the model to (e^-1)*t.
                return f"({args[0]}) ^ ({args[1]})"
            # Child arithmetic nodes carry their own grouping.  Keep the
            # historical flat spelling for a simple top-level node while
            # still preserving nested precedence (for example,
            # ``a / (b + c)``).
            expression = f" {symbol} ".join(args)
            return f"({expression})" if parenthesize else expression
        if operator == "root":
            if degree is not None:
                return f"root({_mathml_to_formula(degree, True)}, {args[0] if args else ''})"
            return f"sqrt({args[0] if args else ''})"
        if operator == "log":
            if logbase is not None:
                return f"log({_mathml_to_formula(logbase, True)}, {args[0] if args else ''})"
            return f"log10({args[0] if args else ''})"
        if operator == "quotient":
            return f"floor(({args[0]}) / ({args[1]}))" if len(args) >= 2 else ""
        if operator == "rem":
            return (
                f"(({args[0]}) - ({args[1]}) * floor(({args[0]}) / ({args[1]})))"
                if len(args) >= 2
                else ""
            )
        direct = {
            "ceiling": "ceil",
            "arcsin": "asin",
            "arccos": "acos",
            "arctan": "atan",
        }
        return f"{direct.get(operator, operator)}({', '.join(args)})"
    return (
        _mathml_to_formula(children[0], parenthesize)
        if children
        else _mathml_text(element)
    )


def _evaluate_static_arithmetic(
    expression: str,
    symbols: Dict[str, float],
    functions: Optional[Mapping[str, SBMLFunctionDefinition]] = None,
    function_stack: tuple[str, ...] = (),
) -> Optional[float]:
    """Evaluate a stoichiometry expression after static-symbol substitution.

    This accepts numeric arithmetic and pure user-defined SBML functions whose
    arguments and bodies reduce to that same arithmetic.  Dynamic SBML
    stoichiometry, unknown functions, and species-valued expressions remain
    marked variable because BNGL reaction patterns require a fixed integer
    count.
    """

    result = str(expression or "").strip()
    for symbol in sorted(symbols, key=len, reverse=True):
        value = symbols[symbol]
        result = re.sub(
            rf"\b{re.escape(symbol)}\b(?!\s*\()",
            format(value, ".15g"),
            result,
        )

    def function_for(name: str) -> Optional[SBMLFunctionDefinition]:
        if functions is None:
            return None
        direct = functions.get(name)
        if direct is not None:
            return direct
        normalized = standardize_name(name)
        return next(
            (
                function
                for function_id, function in functions.items()
                if standardize_name(str(function_id)) == normalized
            ),
            None,
        )

    def split_arguments(value: str) -> Optional[List[str]]:
        if not value.strip():
            return []
        arguments: List[str] = []
        start = 0
        depth = 0
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0:
                    return None
            elif character == "," and depth == 0:
                arguments.append(value[start:index].strip())
                start = index + 1
        if depth != 0:
            return None
        arguments.append(value[start:].strip())
        return arguments if all(arguments) else None

    # Resolve function calls before tokenizing the arithmetic.  A small
    # balanced scanner avoids eval and handles nested calls without accepting
    # arbitrary Python syntax.
    while True:
        call = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", result)
        if call is None:
            break
        function_name = call.group(1)
        function = function_for(function_name)
        function_key = function_name
        if function is not None:
            function_key = next(
                (
                    str(function_id)
                    for function_id, candidate in (functions or {}).items()
                    if candidate is function
                ),
                function_name,
            )
        if function is None or function_key in function_stack:
            return None
        opening = call.end() - 1
        depth = 0
        closing: Optional[int] = None
        for index in range(opening, len(result)):
            if result[index] == "(":
                depth += 1
            elif result[index] == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            return None
        arguments = split_arguments(result[opening + 1 : closing])
        if arguments is None or len(arguments) != len(function.arguments):
            return None
        argument_values = [
            _evaluate_static_arithmetic(
                argument,
                symbols,
                functions,
                (*function_stack, function_key),
            )
            for argument in arguments
        ]
        if any(value is None for value in argument_values):
            return None
        local_symbols = dict(symbols)
        for argument_name, value in zip(function.arguments, argument_values):
            assert value is not None
            local_symbols[str(argument_name)] = value
            local_symbols[standardize_name(str(argument_name))] = value
        value = _evaluate_static_arithmetic(
            function.math,
            local_symbols,
            functions,
            (*function_stack, function_key),
        )
        if value is None:
            return None
        result = result[: call.start()] + format(value, ".15g") + result[closing + 1 :]

    tokens = re.findall(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+\-*/^()]", result)
    if not tokens or "".join(tokens) != re.sub(r"\s+", "", result):
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
            value = float(token)
            position += 1

        while position < len(tokens):
            operator = peek()
            if operator in {None, ")"}:
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
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return None


_RATE_OF_CALL = re.compile(
    r"\brateOf\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
    re.IGNORECASE,
)


def _expand_rate_of_from_rate_rules(model: SBMLModel) -> None:
    """Inline ``rateOf`` calls whose targets have explicit SBML rate rules.

    A rate rule directly defines the time derivative of its target, so this
    substitution is exact for that subset and makes the result executable in
    BNGL.  Reaction-derived ``rateOf`` values and cyclic/unknown references
    are deliberately left untouched; the writer will report those as
    unsupported instead of silently guessing a derivative.
    """

    rate_rules: Dict[str, str] = {}
    ambiguous: set[str] = set()
    for rule in model.rules:
        if rule.type != "rate" or not rule.variable or not rule.math.strip():
            continue
        variable = str(rule.variable)
        for key in {variable, standardize_name(variable)}:
            if key in rate_rules and rate_rules[key] != rule.math:
                ambiguous.add(key)
            else:
                rate_rules[key] = rule.math
    for key in ambiguous:
        rate_rules.pop(key, None)
    if not rate_rules:
        return

    def expand(expression: str, stack: tuple[str, ...] = ()) -> str:
        source = str(expression or "")

        def replace(match: re.Match[str]) -> str:
            identifier = match.group(1)
            key = (
                identifier if identifier in rate_rules else standardize_name(identifier)
            )
            replacement = rate_rules.get(key)
            if replacement is None or key in stack:
                return match.group(0)
            return f"({expand(replacement, (*stack, key))})"

        return _RATE_OF_CALL.sub(replace, source)

    for reaction in model.reactions.values():
        kinetic_law = reaction.kinetic_law
        if kinetic_law is None:
            continue
        old_math = (
            kinetic_law.get("math", "")
            if isinstance(kinetic_law, Mapping)
            else getattr(kinetic_law, "math", "")
        )
        new_math = expand(old_math)
        if isinstance(kinetic_law, Mapping):
            kinetic_law["math"] = new_math
        if hasattr(kinetic_law, "math"):
            kinetic_law.math = new_math

    for rule in model.rules:
        rule.math = expand(rule.math)
    for function in model.function_definitions.values():
        function.math = expand(function.math)
    for event in model.events:
        event.trigger = expand(event.trigger)
        event.delay = expand(event.delay) if event.delay else event.delay
        event.priority = expand(event.priority) if event.priority else event.priority
        for assignment in event.assignments:
            if hasattr(assignment, "math"):
                assignment.math = expand(assignment.math)
            elif isinstance(assignment, Mapping):
                assignment["math"] = expand(assignment.get("math", ""))
    for assignment in model.initial_assignments:
        assignment.math = expand(assignment.math)


def _expand_rate_of_from_simple_reactions(model: SBMLModel) -> None:
    """Inline reaction-derived ``rateOf`` for a conservative ODE subset.

    For a fixed-volume, non-event species, SBML's derivative is the sum of
    reaction stoichiometry times reaction extent rates.  This lowering is
    intentionally limited to ordinary reactions with fixed finite
    stoichiometry and static conversion factors.  Any target touched by an
    unsafe reaction is left unresolved so the writer can report it.
    """

    explicit_rate_targets = {
        str(rule.variable)
        for rule in model.rules
        if rule.type == "rate" and rule.variable
    }
    explicit_rate_targets.update(
        standardize_name(variable) for variable in tuple(explicit_rate_targets)
    )
    assignment_targets = {
        str(rule.variable)
        for rule in model.rules
        if rule.type == "assignment" and rule.variable
    }
    assignment_targets.update(
        standardize_name(variable) for variable in tuple(assignment_targets)
    )
    event_targets = {
        str(assignment.variable)
        for event in model.events
        for assignment in event.assignments
        if getattr(assignment, "variable", None)
    }
    event_targets.update(
        standardize_name(variable) for variable in tuple(event_targets)
    )

    def key_for(identifier: str) -> str:
        return (
            identifier if identifier in model.species else standardize_name(identifier)
        )

    def stoichiometry(reference: SBMLSpeciesReference) -> Optional[float]:
        value = getattr(reference, "stoichiometry", None)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if (
            getattr(reference, "variable_stoichiometry", False)
            or not math.isfinite(number)
            or number < 0
            or abs(number - round(number)) > 1e-12
        ):
            return None
        return number

    def kinetic_math(reaction: SBMLReaction) -> str:
        law = reaction.kinetic_law
        if law is None:
            return ""
        expression = (
            law.get("math", "")
            if isinstance(law, Mapping)
            else getattr(law, "math", "")
        )
        local_parameters = (
            law.get("localParameters", [])
            if isinstance(law, Mapping)
            else getattr(law, "local_parameters", [])
        )
        expression = str(expression or "")
        for parameter in local_parameters or []:
            parameter_id = (
                parameter.get("id")
                if isinstance(parameter, Mapping)
                else getattr(parameter, "id", None)
            )
            parameter_value = (
                parameter.get("value")
                if isinstance(parameter, Mapping)
                else getattr(parameter, "value", None)
            )
            try:
                value = float(parameter_value)
            except (TypeError, ValueError):
                return ""
            if not parameter_id or not math.isfinite(value):
                return ""
            expression = _RATE_OF_CALL.sub(
                lambda match: (
                    "0"
                    if match.group(1) == str(parameter_id)
                    or standardize_name(match.group(1))
                    == standardize_name(str(parameter_id))
                    else match.group(0)
                ),
                expression,
            )
            expression = re.sub(
                rf"\b{re.escape(str(parameter_id))}\b",
                format(value, ".15g"),
                expression,
            )
        return expression

    def conversion_factor_expression(species_id: str) -> tuple[bool, str]:
        """Return the effective scalar for one species derivative.

        SBML applies a reaction's flux separately to each affected species.
        A model-level conversion factor is overridden by a species-level
        factor, so a single reaction can legitimately require different
        scalars on its reactant and product derivatives.
        """

        species = model.species.get(str(species_id))
        factor_id = (
            getattr(species, "conversion_factor", None) if species else None
        ) or (getattr(model, "conversion_factor", None) or None)
        if factor_id is None:
            return True, ""
        parameter = model.parameters.get(factor_id)
        if parameter is None or not getattr(parameter, "constant", True):
            return False, ""
        try:
            value = float(parameter.value)
        except (TypeError, ValueError):
            return False, ""
        if not math.isfinite(value):
            return False, ""
        return True, format(value, ".15g")

    terms: Dict[str, List[str]] = {}
    unsafe: set[str] = set()
    touched: set[str] = set()
    rate_of_expressions: Dict[str, str] = {}

    def add_rate_of_zero(identifier: str) -> None:
        rate_of_expressions[identifier] = "0"
        rate_of_expressions[standardize_name(identifier)] = "0"

    for parameter_id, parameter in model.parameters.items():
        if getattr(parameter, "constant", True):
            add_rate_of_zero(str(parameter_id))
    for compartment_id, compartment in model.compartments.items():
        if getattr(compartment, "constant", True):
            add_rate_of_zero(str(compartment_id))

    for reaction in model.reactions.values():
        net: Dict[str, float] = {}
        valid = True
        for reference in reaction.reactants:
            value = stoichiometry(reference)
            species_id = str(reference.species)
            if value is None:
                valid = False
            elif species_id != "EmptySet":
                net[species_id] = net.get(species_id, 0.0) - value
        for reference in reaction.products:
            value = stoichiometry(reference)
            species_id = str(reference.species)
            if value is None:
                valid = False
            elif species_id != "EmptySet":
                net[species_id] = net.get(species_id, 0.0) + value
        affected = {
            species_id: coefficient
            for species_id, coefficient in net.items()
            if abs(coefficient) > 1e-12
        }
        if not affected:
            continue
        touched.update(key_for(species_id) for species_id in affected)
        expression = kinetic_math(reaction)
        unsafe_reaction = (
            not valid
            or not expression.strip()
            or bool(_RATE_OF_CALL.search(expression))
            or bool(getattr(reaction, "fast", False))
        )
        if unsafe_reaction:
            unsafe.update(key_for(species_id) for species_id in affected)
            continue
        for species_id, coefficient in affected.items():
            target = model.species.get(species_id)
            if target is None:
                unsafe.add(key_for(species_id))
                continue
            target_key = key_for(species_id)
            if target_key in explicit_rate_targets or target_key in assignment_targets:
                continue
            if target_key in event_targets:
                unsafe.add(target_key)
                continue
            factor_is_safe, factor = conversion_factor_expression(species_id)
            if not factor_is_safe:
                unsafe.add(target_key)
                continue
            if target.constant or target.boundary_condition:
                if target.has_only_substance_units:
                    add_rate_of_zero(str(species_id))
                    continue
                compartment_id = str(target.compartment or "")
                compartment = model.compartments.get(compartment_id)
                if compartment is not None and compartment.constant:
                    add_rate_of_zero(str(species_id))
                    continue
                unsafe.add(target_key)
                continue
            if not target.has_only_substance_units:
                compartment_id = str(target.compartment or "")
                compartment = model.compartments.get(compartment_id)
                if (
                    not compartment_id
                    or compartment is None
                    or not compartment.constant
                    or not math.isfinite(float(compartment.size))
                    or float(compartment.size) == 0
                ):
                    unsafe.add(target_key)
                    continue
                volume = f" / ({compartment_id})"
            else:
                volume = ""
            coefficient_text = format(coefficient, ".15g")
            flux = f"({factor}) * ({expression})" if factor else expression
            terms.setdefault(target_key, []).append(
                f"({coefficient_text}) * ({flux}){volume}"
            )

    for species_id, target in model.species.items():
        target_key = key_for(str(species_id))
        if (
            target_key in explicit_rate_targets
            or target_key in assignment_targets
            or target_key in unsafe
            or target_key not in touched
            or target_key not in terms
        ):
            continue
        rate_of_expressions[target_key] = " + ".join(terms[target_key])
        rate_of_expressions[str(species_id)] = rate_of_expressions[target_key]
    if not rate_of_expressions:
        return

    def replace(expression: str) -> str:
        def substitute(match: re.Match[str]) -> str:
            identifier = match.group(1)
            replacement = rate_of_expressions.get(
                identifier, rate_of_expressions.get(standardize_name(identifier))
            )
            return f"({replacement})" if replacement is not None else match.group(0)

        return _RATE_OF_CALL.sub(substitute, str(expression or ""))

    for reaction in model.reactions.values():
        law = reaction.kinetic_law
        if law is None:
            continue
        old_math = (
            law.get("math", "")
            if isinstance(law, Mapping)
            else getattr(law, "math", "")
        )
        new_math = str(old_math or "")
        local_parameters = (
            law.get("localParameters", [])
            if isinstance(law, Mapping)
            else getattr(law, "local_parameters", [])
        )
        for parameter in local_parameters or []:
            parameter_id = (
                parameter.get("id")
                if isinstance(parameter, Mapping)
                else getattr(parameter, "id", None)
            )
            if not parameter_id:
                continue
            new_math = _RATE_OF_CALL.sub(
                lambda match: (
                    "0"
                    if match.group(1) == str(parameter_id)
                    or standardize_name(match.group(1))
                    == standardize_name(str(parameter_id))
                    else match.group(0)
                ),
                new_math,
            )
        new_math = replace(new_math)
        if isinstance(law, Mapping):
            law["math"] = new_math
        if hasattr(law, "math"):
            law.math = new_math
    for rule in model.rules:
        rule.math = replace(rule.math)
    for function in model.function_definitions.values():
        function.math = replace(function.math)
    for event in model.events:
        event.trigger = replace(event.trigger)
        event.delay = replace(event.delay) if event.delay else event.delay
        event.priority = replace(event.priority) if event.priority else event.priority
        for assignment in event.assignments:
            if hasattr(assignment, "math"):
                assignment.math = replace(assignment.math)
    for assignment in model.initial_assignments:
        assignment.math = replace(assignment.math)


class SBMLParser:
    """Parse SBML text into the atomizer's stable intermediate model."""

    def parse(self, sbml_string: str) -> SBMLModel:
        try:
            root = ET.fromstring(sbml_string)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid SBML XML: {exc}") from exc
        model_element = next(
            (element for element in root.iter() if _local_name(element.tag) == "model"),
            None,
        )
        if model_element is None:
            raise ValueError("SBML document has no model")
        declared_packages = _declared_package_uris(sbml_string)
        return self._parse_xml_model(root, model_element, declared_packages)

    @staticmethod
    def _xml_math(parent: Optional[Any]) -> str:
        if parent is None:
            return ""
        math_element = (
            parent
            if _local_name(getattr(parent, "tag", "")) == "math"
            else _first_child(parent, "math")
        )
        if math_element is None:
            formula = _attribute(parent, "formula", "")
            return str(formula or "").strip()
        formula = _mathml_to_formula(math_element)
        if formula:
            return formula
        # Small fixtures and some libSBML XML exports use a formula attribute
        # on an otherwise empty <math/> element. Preserve it as a compatibility
        # fallback; a genuinely empty MathML node still returns "".
        return str(_attribute(math_element, "formula", "") or "").strip()

    @staticmethod
    def _mathml_import_warnings(root: Any) -> List[Dict[str, Any]]:
        """Collect the source parser's diagnostics for lossy MathML constructs."""

        messages: "OrderedDict[str, int]" = OrderedDict()

        def add(message: str) -> None:
            messages[message] = messages.get(message, 0) + 1

        for math_element in root.iter():
            if _local_name(math_element.tag).lower() != "math":
                continue
            for element in math_element.iter():
                tag = _local_name(element.tag).lower()
                if tag == "infinity":
                    add(
                        "<infinity> constant encountered in math; emitted as a large finite value."
                    )
                elif tag == "notanumber":
                    add(
                        "<notanumber> constant encountered in math; cannot be represented."
                    )
                elif tag in {"gcd", "lcm"}:
                    add(
                        f"<{tag}> used in math; the engine does not provide it. Emitted as {tag}(...)."
                    )
                elif tag == "cn" and any(
                    _local_name(child.tag).lower() == "sep" for child in list(element)
                ):
                    number_type = str(_attribute(element, "type", "") or "").lower()
                    # ``sep`` is also the required separator for SBML's
                    # e-notation form (mantissa <sep/> exponent).  That form
                    # is already lowered exactly above; only a missing or
                    # otherwise unknown type needs the conservative
                    # rational-interpretation diagnostic.
                    if number_type not in {"rational", "e-notation", "enotation"}:
                        add(
                            "<cn> with <sep/> and unspecified type treated as rational."
                        )

        return [
            {
                "category": "mathml",
                "message": message,
                "count": count,
                "severity": "approximated",
            }
            for message, count in messages.items()
        ]

    @staticmethod
    def _xml_items(model: Any, container: str, item: str) -> List[Any]:
        parent = _first_child(model, container)
        return list(_children(parent, item)) if parent is not None else []

    @staticmethod
    def _register_alias(
        aliases: Dict[str, str], alias_raw: Any, canonical_id: str
    ) -> None:
        """Register the source parser's direct, collapsed, and BNGL aliases."""

        direct = str(alias_raw or "").strip()
        if not direct:
            return
        candidates = (direct, re.sub(r"\s+", " ", direct), standardize_name(direct))
        seen = set()
        for alias in candidates:
            key = str(alias or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            existing = aliases.get(key)
            if existing is None or existing == canonical_id:
                aliases[key] = canonical_id

    @staticmethod
    def _normalize_formula_identifiers(
        formula: Any, *alias_maps: Optional[Dict[str, str]]
    ) -> str:
        """Rewrite reference aliases without touching longer identifiers."""

        normalized = str(formula or "")
        if not normalized:
            return normalized
        ordered_aliases = []
        for aliases in alias_maps:
            if aliases is None:
                continue
            ordered_aliases.extend(
                (alias, canonical)
                for alias, canonical in aliases.items()
                if alias and canonical and alias != canonical
            )
        ordered_aliases.sort(key=lambda item: len(item[0]), reverse=True)
        for alias, canonical in ordered_aliases:
            pattern = re.compile(
                rf"(^|[^A-Za-z0-9_]){re.escape(alias)}(?=$|[^A-Za-z0-9_])"
            )
            normalized = pattern.sub(
                lambda match: f"{match.group(1)}{canonical}", normalized
            )
        return normalized

    @staticmethod
    def _parse_xml_model(
        root: Any,
        model: Any,
        declared_packages: Optional[Any] = None,
    ) -> SBMLModel:
        compartments = SBMLParser._parse_xml_compartments(model)
        species = SBMLParser._parse_xml_species(model)
        parameter_warnings: List[Dict[str, Any]] = []
        parameter_aliases: Dict[str, str] = {}
        parameters = SBMLParser._parse_xml_parameters(
            model, parameter_warnings, parameter_aliases
        )
        # SBML formulas resolve exact SId references in the model-wide symbol
        # namespace. A parameter's human-readable name must not shadow an
        # exact species or compartment ID (for example, parameter
        # ``Infected_0`` named ``Infected`` alongside species ``Infected``).
        # Remove only the conflicting non-parameter alias; the exact
        # parameter ID remains available when it is referenced explicitly.
        parameter_ids = set(parameters)
        for symbol_id in [*species, *compartments]:
            for alias in {str(symbol_id), standardize_name(str(symbol_id))}:
                if alias not in parameter_ids:
                    parameter_aliases.pop(alias, None)
        reactions = SBMLParser._parse_xml_reactions(model, parameter_aliases)
        math_warnings: List[Dict[str, Any]] = []
        rules = SBMLParser._parse_xml_rules(model, parameter_aliases, math_warnings)
        functions = SBMLParser._parse_xml_functions(
            model, parameter_aliases, math_warnings
        )
        events = SBMLParser._parse_xml_events(model, parameter_aliases)
        initial_assignments = SBMLParser._parse_xml_initial_assignments(
            model, parameter_aliases, math_warnings
        )
        species_by_compartment: Dict[str, List[str]] = OrderedDict()
        for species_id, item in species.items():
            species_by_compartment.setdefault(item.compartment, []).append(species_id)
        level = _attribute(root, "level")
        try:
            level_value = int(level) if level is not None else None
        except (TypeError, ValueError):
            level_value = None
        model_id = str(_attribute(model, "id", "model") or "model")
        declared_package_uris = (
            dict(declared_packages)
            if isinstance(declared_packages, dict)
            else {str(package).lower(): "" for package in (declared_packages or [])}
        )
        package_required = {
            package: _bool(root.attrib.get("{" + uri + "}required"), False)
            for package, uri in declared_package_uris.items()
            if uri
        }
        package_counts: Dict[str, int] = {
            str(package).lower(): 0 for package in declared_package_uris
        }
        package_uri = re.compile(
            r"^https?://www\.sbml\.org/sbml/level3/version\d+/"
            r"([a-z][a-z0-9_]*)/version\d+$",
            re.IGNORECASE,
        )
        for element in root.iter():
            tag = str(getattr(element, "tag", ""))
            if not tag.startswith("{") or "}" not in tag:
                continue
            uri = tag[1:].split("}", 1)[0]
            match = package_uri.match(uri)
            if match:
                package = match.group(1).lower()
                package_counts[package] = package_counts.get(package, 0) + 1

        model_metadata = _source_metadata(model)
        result = SBMLModel(
            id=model_id,
            name=str(_attribute(model, "name", model_id) or model_id),
            compartments=compartments,
            species=species,
            parameters=parameters,
            reactions=reactions,
            rules=rules,
            function_definitions=functions,
            events=events,
            initial_assignments=initial_assignments,
            species_by_compartment=species_by_compartment,
            unit_definitions=SBMLParser._parse_xml_units(model),
            level=level_value,
            version=(
                int(_attribute(root, "version"))
                if str(_attribute(root, "version", "")).isdigit()
                else None
            ),
            substance_units=str(_attribute(model, "substanceUnits", "") or ""),
            time_units=str(_attribute(model, "timeUnits", "") or ""),
            volume_units=str(_attribute(model, "volumeUnits", "") or ""),
            area_units=str(_attribute(model, "areaUnits", "") or ""),
            length_units=str(_attribute(model, "lengthUnits", "") or ""),
            extent_units=str(_attribute(model, "extentUnits", "") or ""),
            conversion_factor=(
                str(_attribute(model, "conversionFactor"))
                if _attribute(model, "conversionFactor") is not None
                else None
            ),
            constraint_count=len(
                SBMLParser._xml_items(model, "listOfConstraints", "constraint")
            ),
            **model_metadata,
            source_metadata_payload=_source_metadata_payload(model),
            declared_packages=declared_package_uris,
            package_required=package_required,
            package_counts=package_counts,
        )
        result.import_warnings.extend(SBMLParser._mathml_import_warnings(root))
        result.import_warnings.extend(apply_unit_scaling(result))
        result.import_warnings.extend(parameter_warnings)
        result.import_warnings.extend(math_warnings)
        _expand_rate_of_from_rate_rules(result)
        _expand_rate_of_from_simple_reactions(result)
        SBMLParser._fold_static_stoichiometry(result)
        SBMLParser._fold_static_species_assignments(result)
        for compartment_id, compartment in compartments.items():
            dimension = compartment.spatial_dimensions
            if not math.isfinite(dimension) or dimension < 0 or dimension > 3:
                result.import_warnings.append(
                    {
                        "category": "compartment",
                        "message": (
                            f'Compartment "{compartment_id}" has spatialDimensions '
                            f"{dimension:g}; SBML core permits only values 0 through 3."
                        ),
                        "count": 1,
                        "severity": "dropped",
                    }
                )
        for reaction_id, reaction in result.reactions.items():
            for reference in [*reaction.reactants, *reaction.products]:
                value = reference.stoichiometry
                if value == 0:
                    continue
                if reference.variable_stoichiometry:
                    result.import_warnings.append(
                        {
                            "category": "stoichiometry",
                            "message": (
                                f'Reaction "{reaction_id}" has variable '
                                f'stoichiometry for species "{reference.species}"; '
                                f"BNGL will use the parsed fixed value {value:g}."
                            ),
                            "count": 1,
                            "severity": "approximated",
                        }
                    )
                elif (
                    not math.isfinite(value)
                    or value < 0
                    or abs(value - round(value)) > 1e-9
                ):
                    result.import_warnings.append(
                        {
                            "category": "stoichiometry",
                            "message": (
                                f'Reaction "{reaction_id}" has unsupported '
                                f"stoichiometry {value:g} for species "
                                f'"{reference.species}"; the reaction will be omitted.'
                            ),
                            "count": 1,
                            "severity": "dropped",
                        }
                    )
            if reaction.fast:
                result.import_warnings.append(
                    {
                        "category": "fastReaction",
                        "message": (
                            f'Reaction "{reaction_id}" is marked fast '
                            '(fast="true"); BNGL/BNG has no fast-equilibrium '
                            "solve, so it is treated as an ordinary reaction."
                        ),
                        "count": 1,
                        "severity": "approximated",
                    }
                )
        if result.events:
            result.import_warnings.append(
                {
                    "category": "event",
                    "message": (
                        f"{len(result.events)} SBML event(s) parsed; discrete state "
                        "changes are not executed by the simulation engine and are "
                        "emitted as an annotated block for review."
                    ),
                    "count": len(result.events),
                    "severity": "dropped",
                }
            )
        algebraic_count = sum(rule.type == "algebraic" for rule in result.rules)
        if algebraic_count:
            result.import_warnings.append(
                {
                    "category": "algebraicRule",
                    "message": (
                        f"{algebraic_count} algebraic rule(s) present; these are "
                        "implicit DAE constraints with no BNGL equivalent and are "
                        "not applied."
                    ),
                    "count": algebraic_count,
                    "severity": "dropped",
                }
            )
        dynamic_packages = {
            "comp": "hierarchical model composition (submodels/externalModelDefinitions are not flattened)",
            "fbc": "flux-balance constraints and objectives",
            "qual": "qualitative (logical) model transitions",
            "spatial": "spatial geometry and diffusion",
            "arrays": "array-expanded objects",
            "distrib": "distributions and uncertainty",
            "dyn": "dynamic (agent) behaviour",
        }
        benign_packages = {
            "layout": "diagram layout",
            "render": "diagram rendering",
            "groups": "element grouping",
            "req": "requirements metadata (retired package)",
        }
        package_reasons = {
            "fbc": " This is a constraint-based flux-balance model, not a kinetic time-course model.",
            "qual": " This is a discrete logical model, not a continuous-time kinetic network.",
        }
        for package, description in dynamic_packages.items():
            if package not in package_counts:
                continue
            count = package_counts[package]
            if count == 0:
                result.import_warnings.append(
                    {
                        "category": f"package:{package}",
                        "message": (
                            f'SBML "{package}" package is declared but contains '
                            "no package elements; the core kinetic model is "
                            "unaffected."
                        ),
                        "count": 1,
                        "severity": "info",
                    }
                )
                continue
            result.import_warnings.append(
                {
                    "category": f"package:{package}",
                    "message": (
                        f'SBML "{package}" package detected ({count} element(s)): '
                        f"{description}. This package is not imported; affected "
                        f"structure is missing from the atomized model."
                        f"{package_reasons.get(package, '')}"
                    ),
                    "count": count or 1,
                    "severity": "dropped",
                }
            )
        for package, description in benign_packages.items():
            if package not in package_counts:
                continue
            result.import_warnings.append(
                {
                    "category": f"package:{package}",
                    "message": (
                        f'SBML "{package}" package detected ({description}); '
                        "not imported. This does not affect the mathematical model."
                    ),
                    "count": package_counts[package] or 1,
                    "severity": "info",
                }
            )
        if package_counts.get("qual", 0) > 0 and not result.reactions:
            raise ValueError(
                'Unsupported model class: SBML "qual" qualitative/logical '
                "model cannot be represented as a BNGL rule-based network."
            )
        multi = parse_multi_package(root)
        result.import_warnings.extend(multi.warnings)
        result.multi_molecule_types = list(multi.bngl_molecule_types)
        result.multi_complex_patterns = [
            pattern for _type_id, pattern in multi.complex_patterns
        ]
        result.multi_seed_patterns = [
            f"{species}: {pattern}" for species, pattern in multi.seed_patterns
        ]
        result.multi_species_patterns = dict(multi.species_patterns)
        result.multi_type_patterns = dict(multi.type_patterns)
        result.multi_component_aliases = dict(multi.component_aliases)
        result.multi_reaction_mappings = dict(multi.reaction_product_maps)
        result.multi_compartment_references = dict(multi.compartment_references)
        result.multi_numeric_values = dict(multi.numeric_values)
        result.multi_executable = multi.executable
        if result.constraint_count:
            result.import_warnings.append(
                {
                    "category": "constraint",
                    "message": (
                        f"{result.constraint_count} SBML constraint element(s) present; "
                        "constraints are not enforced during simulation."
                    ),
                    "count": result.constraint_count,
                    "severity": "info",
                }
            )
        result.import_warnings = [
            coerce_import_warning(warning) for warning in result.import_warnings
        ]
        logger.info(
            "SBM004",
            f"Parsed SBML model: {len(result.species)} species, "
            f"{len(result.reactions)} reactions",
        )
        for warning in result.import_warnings:
            code = {
                "duplicateParameter": "SBM010",
            }.get(
                warning.get("category"),
                {
                    "dropped": "SBM020",
                    "approximated": "SBM021",
                }.get(warning.get("severity"), "SBM022"),
            )
            count = warning.get("count", 1)
            suffix = f" (x{count})" if count > 1 else ""
            logger.warning(
                code,
                f"[{warning.get('category', 'unknown')}] "
                f"{warning.get('message', '')}{suffix}",
            )
        return result

    @staticmethod
    def _fold_static_stoichiometry(model: SBMLModel) -> None:
        """Resolve species-reference stoichiometry that is static for the run."""

        controlled = {str(rule.variable) for rule in model.rules if rule.variable}
        controlled.update(
            str(assignment.variable)
            for event in model.events
            for assignment in event.assignments
            if getattr(assignment, "variable", None)
        )
        controlled.update(
            str(assignment.symbol)
            for assignment in model.initial_assignments
            if assignment.symbol
        )
        symbols: Dict[str, float] = {}
        for parameter_id, parameter in model.parameters.items():
            if not parameter.constant or parameter_id in controlled:
                continue
            value = parameter.value
            if not math.isfinite(value):
                continue
            symbols[str(parameter_id)] = value
            symbols[standardize_name(str(parameter_id))] = value
        for compartment_id, compartment in model.compartments.items():
            if not compartment.constant or compartment_id in controlled:
                continue
            value = compartment.size
            if not math.isfinite(value):
                continue
            symbols[str(compartment_id)] = value
            symbols[standardize_name(str(compartment_id))] = value

        # A speciesReference may carry an id and be assigned a fixed
        # stoichiometry by an initial/assignment rule instead of by
        # stoichiometryMath. Resolve only numerically static rules; rate rules,
        # event assignments, and state-dependent expressions remain variable.
        dynamic_targets = {
            str(rule.variable)
            for rule in model.rules
            if rule.variable and rule.type == "rate"
        }
        event_targets = {
            str(assignment.variable)
            for event in model.events
            for assignment in event.assignments
            if getattr(assignment, "variable", None)
        }
        static_symbols = dict(symbols)
        for _ in range(len(model.rules) + len(model.initial_assignments) + 1):
            changed = False
            for rule in model.rules:
                variable = str(rule.variable or "")
                if (
                    not variable
                    or rule.type != "assignment"
                    or variable in dynamic_targets
                    or variable in event_targets
                ):
                    continue
                value = _evaluate_static_arithmetic(
                    rule.math, static_symbols, model.function_definitions
                )
                if value is None:
                    continue
                for name in (variable, standardize_name(variable)):
                    if static_symbols.get(name) != value:
                        static_symbols[name] = value
                        changed = True
            for assignment in model.initial_assignments:
                symbol = str(assignment.symbol or "")
                if (
                    not symbol
                    or symbol in dynamic_targets
                    or symbol in event_targets
                    or any(
                        str(rule.variable) == symbol
                        and rule.type in {"assignment", "rate"}
                        for rule in model.rules
                    )
                ):
                    continue
                value = _evaluate_static_arithmetic(
                    assignment.math, static_symbols, model.function_definitions
                )
                if value is None:
                    continue
                for name in (symbol, standardize_name(symbol)):
                    if static_symbols.get(name) != value:
                        static_symbols[name] = value
                        changed = True
            if not changed:
                break

        for reaction in model.reactions.values():
            for reference in [*reaction.reactants, *reaction.products]:
                expression = reference.stoichiometry_math or reference.id or ""
                if not expression:
                    continue
                value = _evaluate_static_arithmetic(
                    expression, static_symbols, model.function_definitions
                )
                if value is None:
                    continue
                reference.stoichiometry = value
                reference.variable_stoichiometry = False

    @staticmethod
    def _fold_static_species_assignments(model: SBMLModel) -> None:
        """Lower isolated constant species assignment rules to initial values."""

        assignment_rules = [
            rule
            for rule in model.rules
            if rule.type == "assignment"
            and rule.variable in model.species
            and rule.math
        ]
        if not assignment_rules:
            return

        controlled = {str(rule.variable) for rule in model.rules if rule.variable}
        controlled.update(
            str(assignment.variable)
            for event in model.events
            for assignment in event.assignments
            if getattr(assignment, "variable", None)
        )
        controlled.update(
            str(assignment.symbol)
            for assignment in model.initial_assignments
            if assignment.symbol
        )
        symbols: Dict[str, float] = {}
        for parameter_id, parameter in model.parameters.items():
            if not parameter.constant or parameter_id in controlled:
                continue
            if math.isfinite(parameter.value):
                symbols[str(parameter_id)] = parameter.value
                symbols[standardize_name(str(parameter_id))] = parameter.value
        for compartment_id, compartment in model.compartments.items():
            if not compartment.constant or compartment_id in controlled:
                continue
            if math.isfinite(compartment.size):
                symbols[str(compartment_id)] = compartment.size
                symbols[standardize_name(str(compartment_id))] = compartment.size

        participants = {
            reference.species
            for reaction in model.reactions.values()
            for reference in [*reaction.reactants, *reaction.products]
        }
        event_targets = {
            str(assignment.variable)
            for event in model.events
            for assignment in event.assignments
            if getattr(assignment, "variable", None)
        }

        def references_identifier(expression: str, variable: str) -> bool:
            names = {str(variable), standardize_name(str(variable))}
            return any(
                re.search(rf"\b{re.escape(name)}\b", expression)
                for name in names
                if name
            )

        def reaction_math(reaction: SBMLReaction) -> str:
            law = reaction.kinetic_law
            if isinstance(law, Mapping):
                return str(law.get("math", "") or "")
            return str(getattr(law, "math", "") or "")

        other_expressions = [
            *(reaction_math(reaction) for reaction in model.reactions.values()),
            *(
                str(rule.math or "")
                for rule in model.rules
                if rule not in assignment_rules
            ),
            *(
                str(function.math or "")
                for function in model.function_definitions.values()
            ),
            *(str(event.trigger or "") for event in model.events),
            *(str(event.delay or "") for event in model.events),
            *(str(event.priority or "") for event in model.events),
            *(
                str(assignment.math or "")
                for event in model.events
                for assignment in event.assignments
            ),
            *(str(assignment.math or "") for assignment in model.initial_assignments),
        ]
        fold: Dict[int, float] = {}
        for rule in assignment_rules:
            variable = str(rule.variable)
            if (
                getattr(rule, "math_from_empty_boolean", False)
                or variable in participants
                or variable in event_targets
                or sum(
                    candidate.variable == rule.variable
                    for candidate in assignment_rules
                )
                != 1
                or any(
                    references_identifier(expression, variable)
                    for expression in other_expressions
                )
            ):
                continue
            value = _evaluate_static_arithmetic(
                rule.math, symbols, model.function_definitions
            )
            if value is not None:
                fold[id(rule)] = value

        if not fold:
            return
        for rule in assignment_rules:
            value = fold.get(id(rule))
            if value is None:
                continue
            species = model.species[str(rule.variable)]
            if species.has_only_substance_units:
                species.initial_amount = value
                species.initial_amount_set = True
                species.initial_concentration_set = False
            else:
                species.initial_concentration = value
                species.initial_concentration_set = True
                # An assignment rule defines the species value at t=0 even
                # when the source also carries an ignored initialAmount.
                species.initial_amount_set = False
            model.import_warnings.append(
                {
                    "category": "speciesAssignmentRule",
                    "message": (
                        f'Constant assignment rule for species "{rule.variable}" '
                        "was lowered to its initial value; the species is not a "
                        "reaction or event state."
                    ),
                    "count": 1,
                    "severity": "info",
                }
            )
        model.rules = [rule for rule in model.rules if id(rule) not in fold]

    @staticmethod
    def _parse_xml_compartments(model: Any) -> Dict[str, SBMLCompartment]:
        result: Dict[str, SBMLCompartment] = OrderedDict()
        for item in SBMLParser._xml_items(model, "listOfCompartments", "compartment"):
            item_id = str(_attribute(item, "id", "") or "")
            if not item_id:
                continue
            result[item_id] = SBMLCompartment(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                spatial_dimensions=_float(_attribute(item, "spatialDimensions"), 3),
                size=_float(_attribute(item, "size", _attribute(item, "volume")), 1),
                units=str(_attribute(item, "units", "") or ""),
                constant=_bool(_attribute(item, "constant"), True),
                outside=(str(_attribute(item, "outside", "") or "") or None),
                compartment_type=_attribute(item, "compartmentType"),
                is_type=_bool(_attribute(item, "isType"), False),
                size_set=(
                    _attribute(item, "size") is not None
                    or _attribute(item, "volume") is not None
                ),
                **_source_metadata(item),
            )
        return result

    @staticmethod
    def _parse_xml_annotations(item: Any) -> List[AnnotationInfo]:
        result: List[AnnotationInfo] = []
        for annotation in _children(item, "annotation"):
            resources: List[str] = []
            qualifier_type = -1
            biological = None
            model_qualifier = None
            qualifier_name = None
            for descendant in annotation.iter():
                resource = _attribute(descendant, "resource")
                if resource is not None and _local_name(descendant.tag) == "li":
                    resources.append(str(resource))
                namespace = str(descendant.tag)
                if "biology-qualifiers" in namespace:
                    qualifier_type = 1
                    biological = 0 if _local_name(descendant.tag) == "is" else None
                    qualifier_name = "BQB_" + _local_name(descendant.tag).upper()
                elif "model-qualifiers" in namespace:
                    qualifier_type = 2
                    model_qualifier = 0 if _local_name(descendant.tag) == "is" else None
                    qualifier_name = "BQM_" + _local_name(descendant.tag).upper()
            if resources:
                result.append(
                    AnnotationInfo(
                        qualifier_type=qualifier_type,
                        biological_qualifier=biological,
                        model_qualifier=model_qualifier,
                        resources=resources,
                        qualifier=qualifier_name,
                    )
                )
        return result

    @staticmethod
    def _parse_xml_species(model: Any) -> Dict[str, SBMLSpecies]:
        result: Dict[str, SBMLSpecies] = OrderedDict()
        for item in SBMLParser._xml_items(model, "listOfSpecies", "species"):
            item_id = str(_attribute(item, "id", "") or "")
            if not item_id:
                continue
            result[item_id] = SBMLSpecies(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                compartment=str(_attribute(item, "compartment", "") or ""),
                initial_concentration=_float(
                    _attribute(item, "initialConcentration"), 0
                ),
                initial_amount=_float(_attribute(item, "initialAmount"), 0),
                substance_units=str(_attribute(item, "substanceUnits", "") or ""),
                has_only_substance_units=_bool(
                    _attribute(item, "hasOnlySubstanceUnits"), False
                ),
                boundary_condition=_bool(_attribute(item, "boundaryCondition"), False),
                constant=_bool(_attribute(item, "constant"), False),
                annotations=SBMLParser._parse_xml_annotations(item),
                initial_amount_set=_attribute(item, "initialAmount") is not None,
                initial_concentration_set=(
                    _attribute(item, "initialConcentration") is not None
                ),
                conversion_factor=_attribute(item, "conversionFactor"),
                charge=(
                    _float(_attribute(item, "charge"))
                    if _attribute(item, "charge") is not None
                    else None
                ),
                species_type=_attribute(item, "speciesType"),
                **_source_metadata(item),
            )
        return result

    @staticmethod
    def _parse_xml_parameters(
        model: Any,
        warnings: Optional[List[Dict[str, Any]]] = None,
        aliases: Optional[Dict[str, str]] = None,
    ) -> Dict[str, SBMLParameter]:
        result: Dict[str, SBMLParameter] = OrderedDict()
        raw_parameter_ids: "OrderedDict[str, str]" = OrderedDict()
        for item in SBMLParser._xml_items(model, "listOfParameters", "parameter"):
            raw_id = str(_attribute(item, "id", "") or "")
            if not raw_id:
                continue
            item_id = standardize_name(raw_id)
            parameter = SBMLParameter(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                value=_float(_attribute(item, "value"), 0),
                units=str(_attribute(item, "units", "") or ""),
                constant=_bool(_attribute(item, "constant"), True),
                scope="global",
                **_source_metadata(item),
            )
            existing = result.get(item_id)
            if existing is not None:
                values_match = (
                    math.isfinite(existing.value)
                    and math.isfinite(parameter.value)
                    and abs(existing.value - parameter.value) <= 1e-12
                )
                if values_match:
                    # Match the reference parser: duplicate declarations with
                    # the same value are one parameter, not a silent overwrite.
                    if aliases is not None:
                        SBMLParser._register_alias(aliases, parameter.name, existing.id)
                    continue
                suffix = 2
                remapped_id = f"{item_id}_{suffix}"
                while remapped_id in result:
                    suffix += 1
                    remapped_id = f"{item_id}_{suffix}"
                parameter.id = remapped_id
                if warnings is not None:
                    warnings.append(
                        {
                            "category": "duplicateParameter",
                            "message": (
                                f'Duplicate parameter id "{item_id}" remapped '
                                f'to "{remapped_id}"'
                            ),
                            "count": 1,
                            "severity": "approximated",
                        }
                    )
            result[parameter.id] = parameter
            raw_parameter_ids.setdefault(raw_id, parameter.id)
            if aliases is not None:
                SBMLParser._register_alias(aliases, raw_id, parameter.id)
                SBMLParser._register_alias(aliases, parameter.id, parameter.id)
                SBMLParser._register_alias(aliases, parameter.name, parameter.id)
        if aliases is not None:
            # Exact SBML IDs are authoritative. A human-readable name can
            # normalize to the same spelling as a different raw ID (for
            # example ``kscig'`` -> ``kscig``), and must not rewrite formulas
            # that refer to the exact ID. Reassert direct and standardized
            # raw-ID aliases after all display-name aliases are collected.
            raw_ids = set(raw_parameter_ids)
            for raw_id, canonical in raw_parameter_ids.items():
                aliases[raw_id] = canonical
                normalized = standardize_name(raw_id)
                if normalized not in raw_ids:
                    aliases[normalized] = canonical
        return result

    @staticmethod
    def _parse_xml_reference(
        item: Any, parameter_aliases: Optional[Dict[str, str]] = None
    ) -> SBMLSpeciesReference:
        species = str(_attribute(item, "species", "") or "")
        stoichiometry_set = _attribute(item, "stoichiometry") is not None
        stoichiometry = (
            _float(_attribute(item, "stoichiometry"), 1) if stoichiometry_set else 1
        )
        denominator = _float(_attribute(item, "denominator"), 0)
        if denominator not in {0, 1}:
            stoichiometry /= denominator
        constant = _bool(_attribute(item, "constant"), True)
        stoichiometry_math = SBMLParser._normalize_formula_identifiers(
            SBMLParser._xml_math(_first_child(item, "stoichiometryMath")),
            parameter_aliases,
        )
        map_parent = _first_child(item, "listOfSpeciesTypeComponentMapsInProduct")
        component_maps = []
        if map_parent is not None:
            for mapping in _children(map_parent, "speciesTypeComponentMapInProduct"):
                component_maps.append(
                    SBMLMultiComponentMap(
                        reactant=str(_attribute(mapping, "reactant", "") or ""),
                        reactant_component=str(
                            _attribute(mapping, "reactantComponent", "") or ""
                        ),
                        product_component=str(
                            _attribute(mapping, "productComponent", "") or ""
                        ),
                        id=(
                            str(_attribute(mapping, "id"))
                            if _attribute(mapping, "id")
                            else None
                        ),
                        name=str(_attribute(mapping, "name", "") or ""),
                    )
                )
        return SBMLSpeciesReference(
            species=species,
            stoichiometry=stoichiometry,
            constant=constant,
            id=(str(_attribute(item, "id")) if _attribute(item, "id") else None),
            stoichiometry_set=stoichiometry_set,
            variable_stoichiometry=not constant or bool(stoichiometry_math),
            stoichiometry_math=stoichiometry_math,
            compartment_reference=(
                str(_attribute(item, "compartmentReference"))
                if _attribute(item, "compartmentReference")
                else None
            ),
            multi_component_maps=component_maps,
        )

    @staticmethod
    def _parse_xml_kinetic_law(
        item: Any, parameter_aliases: Optional[Dict[str, str]] = None
    ) -> Optional[SBMLKineticLaw]:
        if item is None:
            return None
        math = SBMLParser._xml_math(item)
        local_parameters: List[SBMLParameter] = []
        local_parent = _first_child(item, "listOfLocalParameters")
        if local_parent is None:
            local_parent = _first_child(item, "listOfParameters")
        if local_parent is not None:
            local_aliases: Dict[str, str] = {}
            # SBML Level 3 uses ``localParameter`` while SBML Level 2 puts
            # reaction-local declarations in ``listOfParameters`` as
            # ``parameter``.  Both spellings have identical scope here.
            local_items = [
                child
                for child in list(local_parent)
                if _local_name(child.tag) in {"localParameter", "parameter"}
            ]
            for local_index, local in enumerate(local_items):
                raw_local_id = str(_attribute(local, "id", "") or "")
                if not raw_local_id:
                    continue
                local_id = standardize_name(raw_local_id)
                if local_id in local_aliases:
                    local_id = f"{local_id}_{local_index + 1}"
                parameter = SBMLParameter(
                    id=local_id,
                    name=str(_attribute(local, "name", local_id) or local_id),
                    value=_float(_attribute(local, "value"), 0),
                    units=str(_attribute(local, "units", "") or ""),
                    scope="local",
                    **_source_metadata(local),
                )
                local_parameters.append(parameter)
                SBMLParser._register_alias(local_aliases, raw_local_id, parameter.id)
                SBMLParser._register_alias(local_aliases, parameter.id, parameter.id)
                SBMLParser._register_alias(local_aliases, parameter.name, parameter.id)
        else:
            local_aliases = {}
        return SBMLKineticLaw(
            math=SBMLParser._normalize_formula_identifiers(
                math, local_aliases, parameter_aliases
            ),
            math_ml=(
                ET.tostring(_first_child(item, "math"), encoding="unicode")
                if _first_child(item, "math") is not None
                else ""
            ),
            local_parameters=local_parameters,
        )

    @staticmethod
    def _parse_xml_reactions(
        model: Any, parameter_aliases: Optional[Dict[str, str]] = None
    ) -> Dict[str, SBMLReaction]:
        result: Dict[str, SBMLReaction] = OrderedDict()
        reaction_parent = _first_child(model, "listOfReactions")
        reaction_items = (
            [
                item
                for item in list(reaction_parent)
                if _local_name(item.tag) in {"reaction", "intraSpeciesReaction"}
            ]
            if reaction_parent is not None
            else []
        )
        for item in reaction_items:
            item_id = str(_attribute(item, "id", "") or "")
            if not item_id:
                continue
            reactant_parent = _first_child(item, "listOfReactants")
            product_parent = _first_child(item, "listOfProducts")
            modifier_parent = _first_child(item, "listOfModifiers")
            result[item_id] = SBMLReaction(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                reversible=_bool(_attribute(item, "reversible"), False),
                fast=_bool(_attribute(item, "fast"), False),
                reactants=(
                    [
                        SBMLParser._parse_xml_reference(reference, parameter_aliases)
                        for reference in _children(reactant_parent, "speciesReference")
                    ]
                    if reactant_parent is not None
                    else []
                ),
                products=(
                    [
                        SBMLParser._parse_xml_reference(reference, parameter_aliases)
                        for reference in _children(product_parent, "speciesReference")
                    ]
                    if product_parent is not None
                    else []
                ),
                modifiers=(
                    [
                        SBMLModifierSpeciesReference(
                            str(_attribute(reference, "species", "") or "")
                        )
                        for reference in _children(
                            modifier_parent, "modifierSpeciesReference"
                        )
                    ]
                    if modifier_parent is not None
                    else []
                ),
                kinetic_law=SBMLParser._parse_xml_kinetic_law(
                    _first_child(item, "kineticLaw"), parameter_aliases
                ),
                compartment=(
                    str(_attribute(item, "compartment"))
                    if _attribute(item, "compartment")
                    else None
                ),
                conversion_factor=_attribute(item, "conversionFactor"),
                multi_intra_species=(_local_name(item.tag) == "intraSpeciesReaction"),
                **_source_metadata(item),
            )
        return result

    @staticmethod
    def _parse_xml_rules(
        model: Any,
        parameter_aliases: Optional[Dict[str, str]] = None,
        warnings: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SBMLRule]:
        result: List[SBMLRule] = []
        parent = _first_child(model, "listOfRules")
        if parent is None:
            return result
        for item in list(parent):
            kind = {
                "assignmentRule": "assignment",
                "rateRule": "rate",
                "algebraicRule": "algebraic",
            }.get(_local_name(item.tag))
            if kind is None:
                continue
            math = SBMLParser._normalize_formula_identifiers(
                SBMLParser._xml_math(item), parameter_aliases
            )
            math_element = _first_child(item, "math")
            empty_boolean_identity = any(
                _local_name(element.tag) == "apply"
                and len(list(element)) == 1
                and _local_name(list(element)[0].tag) in {"and", "or"}
                for element in (math_element.iter() if math_element is not None else [])
            )
            if not math.strip():
                if warnings is not None:
                    warnings.append(
                        {
                            "category": "missingMath",
                            "message": (
                                f"{kind} rule"
                                + (
                                    f' for "{_attribute(item, "variable")}"'
                                    if _attribute(item, "variable")
                                    else ""
                                )
                                + " has no MathML expression; rule was omitted "
                                "from the executable BNGL."
                            ),
                            "count": 1,
                            "severity": "dropped",
                        }
                    )
                continue
            result.append(
                SBMLRule(
                    type=kind,
                    variable=(
                        str(_attribute(item, "variable"))
                        if _attribute(item, "variable") is not None
                        else None
                    ),
                    math=math,
                    math_from_empty_boolean=empty_boolean_identity,
                    **_source_metadata(item),
                )
            )
        return result

    @staticmethod
    def _parse_xml_functions(
        model: Any,
        parameter_aliases: Optional[Dict[str, str]] = None,
        warnings: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, SBMLFunctionDefinition]:
        result: Dict[str, SBMLFunctionDefinition] = OrderedDict()
        for item in SBMLParser._xml_items(
            model, "listOfFunctionDefinitions", "functionDefinition"
        ):
            item_id = str(_attribute(item, "id", "") or "")
            if not item_id:
                continue
            math_element = _first_child(item, "math")
            lambda_element = (
                _first_child(math_element, "lambda")
                if math_element is not None
                else None
            )
            arguments: List[str] = []
            body = math_element
            if lambda_element is not None:
                for bvar in _children(lambda_element, "bvar"):
                    argument = list(bvar)[0] if list(bvar) else None
                    name = _mathml_to_formula(argument)
                    if name:
                        arguments.append(name)
                children = [
                    child
                    for child in list(lambda_element)
                    if _local_name(child.tag) != "bvar"
                ]
                body = children[-1] if children else None
            math = SBMLParser._normalize_formula_identifiers(
                _mathml_to_formula(body), parameter_aliases
            )
            if not math.strip():
                if warnings is not None:
                    warnings.append(
                        {
                            "category": "missingMath",
                            "message": (
                                f'Function definition "{item_id}" has no MathML '
                                "expression; emitted as the constant zero function."
                            ),
                            "count": 1,
                            "severity": "approximated",
                        }
                    )
                math = "0"
            result[item_id] = SBMLFunctionDefinition(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                math=math,
                arguments=arguments,
                **_source_metadata(item),
            )
        return result

    @staticmethod
    def _parse_xml_events(
        model: Any, parameter_aliases: Optional[Dict[str, str]] = None
    ) -> List[SBMLEvent]:
        result: List[SBMLEvent] = []
        for index, item in enumerate(
            SBMLParser._xml_items(model, "listOfEvents", "event")
        ):
            trigger = _first_child(item, "trigger")
            assignments_parent = _first_child(item, "listOfEventAssignments")
            assignments = []
            if assignments_parent is not None:
                for assignment in _children(assignments_parent, "eventAssignment"):
                    assignments.append(
                        (
                            str(_attribute(assignment, "variable", "") or ""),
                            SBMLParser._normalize_formula_identifiers(
                                SBMLParser._xml_math(assignment), parameter_aliases
                            ),
                        )
                    )
            priority = _first_child(item, "priority")
            result.append(
                SBMLEvent(
                    id=str(
                        _attribute(item, "id", f"event_{index + 1}")
                        or f"event_{index + 1}"
                    ),
                    name=str(
                        _attribute(
                            item, "name", _attribute(item, "id", f"event_{index + 1}")
                        )
                        or f"event_{index + 1}"
                    ),
                    trigger=SBMLParser._normalize_formula_identifiers(
                        SBMLParser._xml_math(trigger), parameter_aliases
                    ),
                    delay=SBMLParser._normalize_formula_identifiers(
                        SBMLParser._xml_math(_first_child(item, "delay")),
                        parameter_aliases,
                    )
                    or None,
                    use_values_from_trigger_time=_bool(
                        _attribute(item, "useValuesFromTriggerTime"), True
                    ),
                    assignments=assignments,
                    trigger_initial_value=(
                        _bool(_attribute(trigger, "initialValue"), True)
                        if trigger is not None
                        else None
                    ),
                    trigger_persistent=(
                        _bool(_attribute(trigger, "persistent"), True)
                        if trigger is not None
                        else None
                    ),
                    priority=SBMLParser._normalize_formula_identifiers(
                        SBMLParser._xml_math(priority), parameter_aliases
                    )
                    or None,
                    **_source_metadata(item),
                )
            )
        return result

    @staticmethod
    def _parse_xml_initial_assignments(
        model: Any,
        parameter_aliases: Optional[Dict[str, str]] = None,
        warnings: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SBMLInitialAssignment]:
        result: List[SBMLInitialAssignment] = []
        for item in SBMLParser._xml_items(
            model, "listOfInitialAssignments", "initialAssignment"
        ):
            symbol = _attribute(item, "symbol")
            if symbol is not None:
                math = SBMLParser._normalize_formula_identifiers(
                    SBMLParser._xml_math(item), parameter_aliases
                )
                if not math.strip():
                    if warnings is not None:
                        warnings.append(
                            {
                                "category": "missingMath",
                                "message": (
                                    f'Initial assignment "{symbol}" has no MathML '
                                    "expression; assignment was omitted."
                                ),
                                "count": 1,
                                "severity": "dropped",
                            }
                        )
                    continue
                result.append(
                    SBMLInitialAssignment(
                        symbol=str(symbol),
                        math=math,
                        **_source_metadata(item),
                    )
                )
        return result

    @staticmethod
    def _parse_xml_units(model: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = OrderedDict()
        for definition in SBMLParser._xml_items(
            model, "listOfUnitDefinitions", "unitDefinition"
        ):
            definition_id = str(_attribute(definition, "id", "") or "")
            if not definition_id:
                continue
            units = []
            parent = _first_child(definition, "listOfUnits")
            if parent is not None:
                for unit in _children(parent, "unit"):
                    units.append(
                        {
                            "kind": _attribute(unit, "kind", ""),
                            "scale": int(_float(_attribute(unit, "scale"), 0)),
                            "exponent": _float(_attribute(unit, "exponent"), 1),
                            "multiplier": _float(_attribute(unit, "multiplier"), 1),
                        }
                    )
            result[definition_id] = units
        return result

    @staticmethod
    def _raw_elements(root: Any) -> Dict[str, Dict[str, Dict[str, str]]]:
        result: Dict[str, Dict[str, Dict[str, str]]] = {
            "compartment": {},
            "species": {},
            "reaction": {},
        }
        for element in root.iter():
            kind = _local_name(element.tag)
            element_id = element.attrib.get("id")
            if kind in result and element_id:
                result[kind][element_id] = dict(element.attrib)
        return result

    @staticmethod
    def _parse_compartments(
        model: Any, raw: Dict[str, Dict[str, str]]
    ) -> Mapping[str, SBMLCompartment]:
        result: Dict[str, SBMLCompartment] = OrderedDict()
        for index in range(model.getNumCompartments()):
            item = model.getCompartment(index)
            item_id = str(item.getId())
            attrs = raw.get(item_id, {})
            result[item_id] = SBMLCompartment(
                id=item_id,
                name=str(item.getName() or item_id),
                spatial_dimensions=_float(item.getSpatialDimensions(), 3),
                size=_float(item.getSize(), 1),
                units=str(item.getUnits() or ""),
                constant=(
                    bool(item.getConstant()) if hasattr(item, "getConstant") else True
                ),
                outside=str(item.getOutside() or attrs.get("outside") or "") or None,
                compartment_type=attrs.get("compartmentType"),
                size_set="size" in attrs or "volume" in attrs,
                metaid=attrs.get("metaid"),
                sbo_term=attrs.get("sboTerm"),
            )
        return result

    @staticmethod
    def _parse_species(
        model: Any, raw: Dict[str, Dict[str, str]], libsbml: Any
    ) -> Mapping[str, SBMLSpecies]:
        result: Dict[str, SBMLSpecies] = OrderedDict()
        for index in range(model.getNumSpecies()):
            item = model.getSpecies(index)
            item_id = str(item.getId())
            attrs = raw.get(item_id, {})
            result[item_id] = SBMLSpecies(
                id=item_id,
                name=str(item.getName() or item_id),
                compartment=str(item.getCompartment() or ""),
                initial_concentration=_float(item.getInitialConcentration(), 0),
                initial_amount=_float(item.getInitialAmount(), 0),
                substance_units=(
                    str(item.getSubstanceUnits() or "")
                    if hasattr(item, "getSubstanceUnits")
                    else ""
                ),
                has_only_substance_units=bool(item.getHasOnlySubstanceUnits()),
                boundary_condition=bool(item.getBoundaryCondition()),
                constant=bool(item.getConstant()),
                annotations=SBMLParser._parse_annotations(item),
                initial_amount_set="initialAmount" in attrs,
                initial_concentration_set="initialConcentration" in attrs,
                sbo_term=attrs.get("sboTerm"),
                conversion_factor=attrs.get("conversionFactor"),
                charge=_float(attrs["charge"]) if "charge" in attrs else None,
                species_type=attrs.get("speciesType"),
                metaid=attrs.get("metaid"),
            )
        return result

    @staticmethod
    def _parse_annotations(item: Any) -> List[AnnotationInfo]:
        result: List[AnnotationInfo] = []
        if not hasattr(item, "getNumCVTerms"):
            return result
        for index in range(item.getNumCVTerms()):
            term = item.getCVTerm(index)
            qualifier_type = int(term.getQualifierType())
            resources = [
                str(term.getResourceURI(resource_index))
                for resource_index in range(term.getNumResources())
            ]
            biological = None
            model = None
            if qualifier_type == 1 and hasattr(term, "getBiologicalQualifierType"):
                biological = int(term.getBiologicalQualifierType())
            elif hasattr(term, "getModelQualifierType"):
                model = int(term.getModelQualifierType())
            result.append(AnnotationInfo(qualifier_type, biological, model, resources))
        return result

    @staticmethod
    def _parse_parameters(
        model: Any, raw: Optional[Dict[str, Dict[str, str]]] = None
    ) -> Mapping[str, SBMLParameter]:
        result: Dict[str, SBMLParameter] = OrderedDict()
        raw = raw or {}
        for index in range(model.getNumParameters()):
            item = model.getParameter(index)
            item_id = str(item.getId())
            result[item_id] = SBMLParameter(
                id=item_id,
                name=str(item.getName() or item_id),
                value=_float(item.getValue(), 0),
                units=str(item.getUnits() or "") if hasattr(item, "getUnits") else "",
                constant=(
                    bool(item.getConstant()) if hasattr(item, "getConstant") else True
                ),
                scope="global",
                metaid=raw.get(item_id, {}).get("metaid"),
                sbo_term=raw.get(item_id, {}).get("sboTerm"),
            )
        return result

    @staticmethod
    def _parse_reference(ref: Any) -> SBMLSpeciesReference:
        stoichiometry = _float(ref.getStoichiometry(), 1)
        is_set = (
            bool(ref.isSetStoichiometry())
            if hasattr(ref, "isSetStoichiometry")
            else stoichiometry != 1
        )
        return SBMLSpeciesReference(
            species=str(ref.getSpecies()),
            stoichiometry=stoichiometry,
            constant=bool(ref.getConstant()) if hasattr(ref, "getConstant") else True,
            id=(
                str(ref.getId() or "")
                if hasattr(ref, "getId") and ref.getId()
                else None
            ),
            stoichiometry_set=is_set,
            variable_stoichiometry=(
                not bool(ref.getConstant()) if hasattr(ref, "getConstant") else False
            ),
        )

    @staticmethod
    def _parse_reactions(
        model: Any, raw: Dict[str, Dict[str, str]], libsbml: Any
    ) -> Mapping[str, SBMLReaction]:
        result: Dict[str, SBMLReaction] = OrderedDict()
        for index in range(model.getNumReactions()):
            item = model.getReaction(index)
            item_id = str(item.getId())
            kinetic = item.getKineticLaw()
            law = None
            if kinetic is not None:
                math_node = kinetic.getMath() if hasattr(kinetic, "getMath") else None
                math = _formula_from_math(math_node, libsbml)
                if not math and hasattr(kinetic, "getFormula"):
                    math = str(kinetic.getFormula() or "").strip()
                local_parameters: List[SBMLParameter] = []
                count = (
                    kinetic.getNumLocalParameters()
                    if hasattr(kinetic, "getNumLocalParameters")
                    else 0
                )
                for local_index in range(count):
                    local = kinetic.getLocalParameter(local_index)
                    local_id = str(local.getId())
                    local_parameters.append(
                        SBMLParameter(
                            id=local_id,
                            name=str(local.getName() or local_id),
                            value=_float(local.getValue(), 0),
                            units=(
                                str(local.getUnits() or "")
                                if hasattr(local, "getUnits")
                                else ""
                            ),
                            constant=True,
                            scope="local",
                        )
                    )
                math_ml = (
                    str(math_node.toMathML())
                    if math_node is not None and hasattr(math_node, "toMathML")
                    else ""
                )
                law = SBMLKineticLaw(
                    math=math, math_ml=math_ml, local_parameters=local_parameters
                )

            result[item_id] = SBMLReaction(
                id=item_id,
                name=str(item.getName() or item_id),
                reversible=bool(item.getReversible()),
                fast=bool(item.getFast()) if hasattr(item, "getFast") else False,
                reactants=[
                    SBMLParser._parse_reference(item.getReactant(i))
                    for i in range(item.getNumReactants())
                ],
                products=[
                    SBMLParser._parse_reference(item.getProduct(i))
                    for i in range(item.getNumProducts())
                ],
                modifiers=[
                    SBMLModifierSpeciesReference(str(item.getModifier(i).getSpecies()))
                    for i in range(item.getNumModifiers())
                ],
                kinetic_law=law,
                compartment=str(
                    item.getCompartment()
                    or raw.get(item_id, {}).get("compartment")
                    or ""
                )
                or None,
                conversion_factor=raw.get(item_id, {}).get("conversionFactor"),
                metaid=raw.get(item_id, {}).get("metaid"),
                sbo_term=raw.get(item_id, {}).get("sboTerm"),
            )
        return result

    @staticmethod
    def _formula_for_sbase(item: Any, libsbml: Any) -> str:
        math_node = item.getMath() if hasattr(item, "getMath") else None
        formula = _formula_from_math(math_node, libsbml)
        if not formula and hasattr(item, "getFormula"):
            formula = str(item.getFormula() or "").strip()
        return formula

    @staticmethod
    def _parse_rules(model: Any, libsbml: Any) -> List[SBMLRule]:
        result: List[SBMLRule] = []
        for index in range(model.getNumRules()):
            item = model.getRule(index)
            if item.isAssignment() if hasattr(item, "isAssignment") else False:
                kind = "assignment"
            elif item.isRate() if hasattr(item, "isRate") else False:
                kind = "rate"
            elif item.isAlgebraic() if hasattr(item, "isAlgebraic") else False:
                kind = "algebraic"
            else:
                continue
            result.append(
                SBMLRule(
                    type=kind,
                    variable=(
                        str(item.getVariable() or "")
                        if hasattr(item, "getVariable")
                        else None
                    ),
                    math=SBMLParser._formula_for_sbase(item, libsbml),
                )
            )
        return result

    @staticmethod
    def _parse_functions(
        model: Any, libsbml: Any
    ) -> Mapping[str, SBMLFunctionDefinition]:
        result: Dict[str, SBMLFunctionDefinition] = OrderedDict()
        count = (
            model.getNumFunctionDefinitions()
            if hasattr(model, "getNumFunctionDefinitions")
            else 0
        )
        for index in range(count):
            item = model.getFunctionDefinition(index)
            item_id = str(item.getId())
            arguments = []
            for arg_index in range(
                item.getNumArguments() if hasattr(item, "getNumArguments") else 0
            ):
                argument = item.getArgument(arg_index)
                arguments.append(
                    str(argument.getName() or argument.getCharacter() or "arg")
                )
            result[item_id] = SBMLFunctionDefinition(
                id=item_id,
                name=str(item.getName() or item_id),
                math=SBMLParser._formula_for_sbase(item, libsbml),
                arguments=arguments,
            )
        return result

    @staticmethod
    def _parse_events(model: Any, libsbml: Any) -> List[SBMLEvent]:
        result: List[SBMLEvent] = []
        count = model.getNumEvents() if hasattr(model, "getNumEvents") else 0
        for index in range(count):
            item = model.getEvent(index)
            trigger = item.getTrigger() if hasattr(item, "getTrigger") else None
            delay = item.getDelay() if hasattr(item, "getDelay") else None
            assignments = []
            for assignment_index in range(item.getNumEventAssignments()):
                assignment = item.getEventAssignment(assignment_index)
                assignments.append(
                    (
                        str(assignment.getVariable()),
                        SBMLParser._formula_for_sbase(assignment, libsbml),
                    )
                )
            priority = item.getPriority() if hasattr(item, "getPriority") else None
            result.append(
                SBMLEvent(
                    id=str(item.getId() or f"event_{index + 1}"),
                    name=str(item.getName() or item.getId() or f"event_{index + 1}"),
                    trigger=SBMLParser._formula_for_sbase(trigger, libsbml),
                    delay=SBMLParser._formula_for_sbase(delay, libsbml) or None,
                    use_values_from_trigger_time=bool(
                        item.getUseValuesFromTriggerTime()
                    ),
                    assignments=assignments,
                    trigger_initial_value=(
                        bool(trigger.getInitialValue())
                        if trigger is not None and hasattr(trigger, "getInitialValue")
                        else None
                    ),
                    trigger_persistent=(
                        bool(trigger.getPersistent())
                        if trigger is not None and hasattr(trigger, "getPersistent")
                        else None
                    ),
                    priority=SBMLParser._formula_for_sbase(priority, libsbml) or None,
                )
            )
        return result

    @staticmethod
    def _parse_initial_assignments(
        model: Any, libsbml: Any
    ) -> List[SBMLInitialAssignment]:
        result: List[SBMLInitialAssignment] = []
        count = (
            model.getNumInitialAssignments()
            if hasattr(model, "getNumInitialAssignments")
            else 0
        )
        for index in range(count):
            item = model.getInitialAssignment(index)
            result.append(
                SBMLInitialAssignment(
                    symbol=str(item.getSymbol()),
                    math=SBMLParser._formula_for_sbase(item, libsbml),
                )
            )
        return result

    @staticmethod
    def _parse_units(model: Any) -> Mapping[str, Any]:
        result: Dict[str, Any] = OrderedDict()
        count = (
            model.getNumUnitDefinitions()
            if hasattr(model, "getNumUnitDefinitions")
            else 0
        )
        for index in range(count):
            definition = model.getUnitDefinition(index)
            units = []
            for unit_index in range(definition.getNumUnits()):
                unit = definition.getUnit(unit_index)
                units.append(
                    {
                        "kind": int(unit.getKind()),
                        "scale": int(unit.getScale()),
                        "exponent": int(unit.getExponent()),
                        "multiplier": _float(unit.getMultiplier(), 1),
                    }
                )
            result[str(definition.getId())] = units
        return result


def extract_uniprot_ids(resources: Iterable[str]) -> List[str]:
    """Extract UniProt identifiers from MIRIAM/identifiers.org resources."""

    result = []
    for resource in resources:
        match = re.search(r"uniprot[:/]([A-Z0-9]+)", str(resource), re.IGNORECASE)
        if match:
            result.append(match.group(1))
    return result


def extract_go_terms(resources: Iterable[str]) -> List[str]:
    result = []
    for resource in resources:
        match = re.search(r"GO[:/](\d+)", str(resource), re.IGNORECASE)
        if match:
            result.append(f"GO:{match.group(1)}")
    return result


extractGOTerms = extract_go_terms
extractUniProtIds = extract_uniprot_ids


__all__ = [
    "SBMLParser",
    "extractGOTerms",
    "extractUniProtIds",
    "extract_go_terms",
    "extract_uniprot_ids",
]
