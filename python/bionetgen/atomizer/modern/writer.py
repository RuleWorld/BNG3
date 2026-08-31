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
    replacements = {
        "power": "pow",
        "log10": "log10",
        "ceiling": "ceil",
        "exponentiale": "2.71828182845905",
    }
    for source, target in replacements.items():
        if source != target:
            result = re.sub(rf"\b{re.escape(source)}\b", target, result)
    result = re.sub(r"\bpi\b", "3.14159265358979", result)
    result = re.sub(r"\btrue\b", "1", result, flags=re.IGNORECASE)
    result = re.sub(r"\bfalse\b", "0", result, flags=re.IGNORECASE)
    result = re.sub(r"\btime\b(?!\s*\()", "time()", result)
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


def _rate_for_reaction(reaction: SBMLReaction) -> str:
    math = convert_math_expression(get_kinetic_math(reaction.kinetic_law))
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


def write_functions(model: SBMLModel) -> List[str]:
    lines = []
    for function_id, function in model.function_definitions.items():
        name = standardize_name(function.name or function_id)
        args = ", ".join(standardize_name(argument) for argument in function.arguments)
        lines.append(f"{name}({args}) = {convert_math_expression(function.math)}")
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
        rate = _rate_for_reaction(reaction)
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
    "convert_math_expression",
    "generate_bngl",
    "write_compartments",
    "write_functions",
    "write_molecule_types",
    "write_observables",
    "write_parameters",
    "write_reaction_rules",
    "write_seed_species",
]
