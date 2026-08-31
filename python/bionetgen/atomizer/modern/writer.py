"""BNGL writer for the Playground atomizer port."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .structures import Molecule, Species
from .types import (
    SBMLModel,
    SBMLReaction,
    SeedSpeciesEntry,
    SpeciesCompositionTable,
    get_kinetic_math,
    standardize_name,
)


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

        def replace_call(args: List[str], arguments=arguments, body=body):
            if not arguments and len(args) == 1 and not args[0]:
                return f"({body})"
            if len(args) == 1 and not args[0] and arguments:
                return f"{name}()"
            if len(args) != len(arguments):
                return f"{name}({', '.join(args)})"
            expanded = body
            for formal, actual in zip(arguments, args):
                expanded = re.sub(rf"\b{re.escape(formal)}\b", f"({actual})", expanded)
            return f"({expanded})"

        result = _replace_nested_function(result, name, replace_call)
        if not arguments:
            result = _replace_nested_function(result, function_id, replace_call)

    for parameter, value in parameter_dict.items():
        replacement = _number(value)
        result = re.sub(rf"\b{re.escape(parameter)}\b", replacement, result)
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


def _rate_for_reaction(reaction: SBMLReaction, model: SBMLModel) -> str:
    math = extend_function(
        get_kinetic_math(reaction.kinetic_law),
        {
            parameter_id: parameter.value
            for parameter_id, parameter in model.parameters.items()
        },
        model.function_definitions,
    )
    math = convert_math_expression(math)
    if not math:
        return "1"
    reactants = [
        reference.species
        for reference in reaction.reactants
        if reference.species != "EmptySet"
    ]
    return _strip_mass_action_factors(math, reactants)


def write_parameters(
    model: SBMLModel, assignment_variables: Optional[Set[str]] = None
) -> List[str]:
    assignment_variables = assignment_variables or set()
    lines = ["__Avogadro__ 1"]
    for compartment_id, compartment in model.compartments.items():
        lines.append(
            f"__compartment_{standardize_name(compartment_id)}__ {_number(compartment.size)}"
        )
    for parameter_id, parameter in model.parameters.items():
        name = standardize_name(parameter_id)
        if name in assignment_variables:
            continue
        lines.append(f"{name} {_number(parameter.value)}")
    return lines


def write_compartments(model: SBMLModel) -> List[str]:
    lines = []
    for compartment_id, compartment in model.compartments.items():
        dimension = max(1, int(compartment.spatial_dimensions or 3))
        line = f"{standardize_name(compartment_id)} {dimension} {_number(compartment.size)}"
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


def write_seed_species(
    seed_species: Sequence[SeedSpeciesEntry],
    sct: SpeciesCompositionTable,
    model: SBMLModel,
) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    lines: List[str] = []
    sbml_to_pattern: Dict[str, str] = OrderedDict()
    pattern_to_id: Dict[str, str] = OrderedDict()
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
        line = f"{pattern} {seed.concentration}"
        lines.append(line)
        sbml_to_pattern[seed.sbml_id] = pattern
        pattern_to_id[pattern] = seed.sbml_id
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
        name = standardize_name(species.name or species_id)
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
        lines.append(f"Species {name} {pattern} # {species_id}")
        observable_map[species_id] = name
    return lines, observable_map


def _rewrite_zero_argument_calls(expression: str, names: Iterable[str]) -> str:
    result = expression
    for name in names:
        result = re.sub(rf"\b{re.escape(name)}\b(?!\s*\()", f"{name}()", result)
    return result


def write_functions(model: SBMLModel) -> List[str]:
    lines = []
    zero_argument_functions = []
    for function_id, function in model.function_definitions.items():
        name = standardize_name(function.name or function_id)
        if function.arguments:
            # BNG2/BNGL function blocks do not consistently support
            # argument-taking SBML definitions.  Inline those definitions at
            # call sites, as the Playground writer does.
            continue
        args = ", ".join(standardize_name(argument) for argument in function.arguments)
        lines.append(f"{name}({args}) = {convert_math_expression(function.math)}")
        zero_argument_functions.append(name)
    for rule in model.rules:
        if not rule.variable or rule.type != "assignment":
            continue
        body = extend_function(
            rule.math,
            {
                parameter_id: parameter.value
                for parameter_id, parameter in model.parameters.items()
            },
            model.function_definitions,
        )
        body = convert_math_expression(body)
        body = _rewrite_zero_argument_calls(body, zero_argument_functions)
        lines.append(f"{standardize_name(rule.variable)}() = {body}")
    return lines


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


def write_reaction_rules(
    model: SBMLModel, sct: SpeciesCompositionTable, atomize: bool
) -> List[str]:
    lines = []
    used_labels = set()
    for reaction_id, reaction in model.reactions.items():
        reactants: List[str] = []
        products: List[str] = []
        for reference in reaction.reactants:
            if reference.species == "EmptySet":
                continue
            reactants.extend(
                [_reaction_pattern(reference.species, sct, model)]
                * max(1, int(reference.stoichiometry or 1))
            )
        for reference in reaction.products:
            if reference.species == "EmptySet":
                continue
            products.extend(
                [_reaction_pattern(reference.species, sct, model)]
                * max(1, int(reference.stoichiometry or 1))
            )
        label = standardize_name(reaction.name or reaction_id)
        candidate = label
        suffix = 2
        while candidate in used_labels:
            candidate = f"{label}_{suffix}"
            suffix += 1
        used_labels.add(candidate)
        arrow = "<->" if reaction.reversible else "->"
        rate = _rate_for_reaction(reaction, model)
        if reaction.reversible:
            rate = f"{rate}, {rate}"
        lines.append(
            f"{candidate}: {' + '.join(reactants) if reactants else '0'} "
            f"{arrow} {' + '.join(products) if products else '0'} {rate}"
        )
    return lines


def generate_bngl(
    model: SBMLModel,
    sct: SpeciesCompositionTable,
    molecule_types: Sequence[Molecule],
    seed_species: Sequence[SeedSpeciesEntry],
    atomize: bool = False,
) -> Tuple[str, Mapping[str, str]]:
    assignment_variables = {
        standardize_name(rule.variable)
        for rule in model.rules
        if rule.type == "assignment" and rule.variable
    }
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
    sections.append(_section("molecule types", write_molecule_types(molecule_types)))
    seed_lines, species_to_pattern, _pattern_to_id = write_seed_species(
        seed_species, sct, model
    )
    if seed_lines:
        sections.append(_section("seed species", seed_lines))
    observable_lines, observable_map = write_observables(model, sct, species_to_pattern)
    if observable_lines:
        sections.append(_section("observables", observable_lines))
    function_lines = write_functions(model)
    if function_lines:
        sections.append(_section("functions", function_lines))
    sections.append(
        _section("reaction rules", write_reaction_rules(model, sct, atomize))
    )
    sections.append("end model")
    return (
        "\n\n".join(section for section in sections if section != "") + "\n",
        observable_map,
    )


__all__ = [
    "bngl_function",
    "convert_math_expression",
    "extend_function",
    "generate_bngl",
    "write_compartments",
    "write_functions",
    "write_molecule_types",
    "write_observables",
    "write_parameters",
    "write_reaction_rules",
    "write_seed_species",
]
