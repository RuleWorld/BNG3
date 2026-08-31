"""Convert BioNetGen's BNG-SBML extension back to BNGL.

This is the Python counterpart of the public Playground fallback converter.
It intentionally handles BNG-specific ``ListOf*`` sections in addition to
ordinary SBML and keeps the conversion dependency-free.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _descendants(element: Optional[ET.Element], *names: str) -> List[ET.Element]:
    if element is None:
        return []
    wanted = {name.lower() for name in names}
    return [item for item in element.iter() if _local_name(item.tag).lower() in wanted]


def _first(element: Optional[ET.Element], *names: str) -> Optional[ET.Element]:
    values = _descendants(element, *names)
    return values[0] if values else None


def _attribute(element: ET.Element, *names: str, default: str = "") -> str:
    for name in names:
        value = element.get(name)
        if value is not None and value != "":
            return value
    return default


def _text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _escape_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _pattern_to_string(pattern: ET.Element, product: bool = False) -> str:
    bond_indices: Dict[str, int] = {}
    next_bond = 1
    bonds = _descendants(_first(pattern, "ListOfBonds"), "Bond")
    for bond in bonds:
        site1 = _attribute(bond, "site1")
        site2 = _attribute(bond, "site2")
        if not site1 or not site2:
            continue
        key = f"{site1}__{site2}"
        index = bond_indices.setdefault(key, next_bond)
        if index == next_bond:
            next_bond += 1
        bond_indices[f"{site2}__{site1}"] = index

    molecule_strings: List[str] = []
    for molecule in _descendants(pattern, "Molecule"):
        molecule_name = _attribute(molecule, "name")
        compartment = _attribute(molecule, "compartment")
        component_strings: List[str] = []
        for component in _descendants(molecule, "Component"):
            component_name = _attribute(component, "name")
            component_id = _attribute(component, "id")
            state = _attribute(component, "state")
            value = component_name + (f"~{state}" if state else "")

            bond_index: Optional[int] = None
            for bond in bonds:
                site1 = _attribute(bond, "site1")
                site2 = _attribute(bond, "site2")
                if component_id not in {site1, site2}:
                    continue
                partner = site2 if site1 == component_id else site1
                bond_index = bond_indices.get(
                    f"{component_id}__{partner}",
                    bond_indices.get(f"{partner}__{component_id}"),
                )
                if bond_index is not None:
                    break

            if bond_index is not None:
                value += f"!{bond_index}"
            else:
                number_of_bonds = _attribute(component, "numberOfBonds")
                direct_bond = _attribute(component, "bond")
                if "+" in number_of_bonds or "+" in direct_bond:
                    value += "!+"
                elif "?" in number_of_bonds or "?" in direct_bond:
                    value += "!?"
                elif direct_bond and direct_bond != "0":
                    value += f"!{direct_bond}"
            if component_name:
                component_strings.append(value)

        base = (
            f"{molecule_name}({','.join(component_strings)})"
            if component_strings
            else f"{molecule_name}()"
        )
        molecule_strings.append(f"{base}@{compartment}" if compartment else base)

    separator = "." if product else " + "
    return separator.join(molecule_strings)


def _reaction_rate(
    reaction_rule: ET.Element,
    parameter_names: Iterable[str],
) -> str:
    rate_law = _first(reaction_rule, "RateLaw")
    if rate_law is None:
        return ""

    rate_type = _attribute(rate_law, "type")
    rate_constants = _descendants(rate_law, "RateConstant")
    if rate_type.lower() == "ele":
        return _attribute(rate_constants[0], "value", default=_text(rate_constants[0])) if rate_constants else ""
    if rate_type.lower() == "function":
        return _attribute(rate_law, "name")
    if rate_type in {"MM", "Sat", "Hill", "Arrhenius"}:
        arguments = [
            _attribute(item, "value", default=_text(item)) or "0"
            for item in rate_constants
        ]
        if rate_type in {"MM", "Sat"} and len(arguments) >= 2:
            reactant_list = _first(reaction_rule, "ListOfReactantPatterns")
            compartment = _attribute(
                _first(reactant_list, "Molecule") or ET.Element("Molecule"),
                "compartment",
            )
            if compartment:
                scale = compartment
                if "NA" in set(parameter_names):
                    scale += " * NA"
                arguments[1] = f"({arguments[1]} * {scale})"
        return f"{rate_type}({','.join(arguments)})"
    return (
        _attribute(rate_constants[0], "value", default=_text(rate_constants[0]))
        if rate_constants
        else ""
    )


def convert_bng_xml_to_bngl(xml: str) -> str:
    """Convert BNG-SBML XML text into a BNGL model string."""

    root = ET.fromstring(xml)
    model = _first(root, "model")
    if model is None:
        raise ValueError("No <model> element found in SBML")

    lines: List[str] = []

    parameters = _descendants(_first(model, "ListOfParameters"), "Parameter")
    parameter_names = {_attribute(item, "id", "name") for item in parameters}
    if parameters:
        lines.append("begin parameters")
        for parameter in parameters:
            identifier = _attribute(parameter, "id", "name", default="p")
            value = _attribute(
                parameter,
                "expr",
                "value",
                default="",
            )
            lines.append(f"    {identifier} {value}")
        lines.extend(["end parameters", ""])

    compartments = _descendants(_first(model, "ListOfCompartments"), "Compartment", "compartment")
    if compartments:
        lines.append("begin compartments")
        for compartment in compartments:
            identifier = _attribute(compartment, "id", "name", default="c")
            size = _attribute(compartment, "size", default="1")
            lines.append(f"    {identifier} {size}")
        lines.extend(["end compartments", ""])

    molecule_type_list = _first(model, "ListOfMoleculeTypes")
    molecule_types = _descendants(molecule_type_list, "MoleculeType")
    if molecule_types:
        lines.append("begin molecule types")
        for molecule_type in molecule_types:
            identifier = _attribute(molecule_type, "id", default="M")
            component_strings: List[str] = []
            for component in _descendants(molecule_type, "ComponentType"):
                name = _attribute(component, "id", "name", default="c")
                states = [
                    _attribute(state, "id", default=_text(state))
                    for state in _descendants(component, "AllowedState")
                ]
                component_strings.append(
                    f"{name}~{'~'.join(state for state in states if state)}"
                    if any(states)
                    else name
                )
            lines.append(f"    {identifier}({','.join(component_strings)})")
        lines.extend(["end molecule types", ""])

    species_list = _first(model, "ListOfSpecies")
    species = _descendants(species_list, "Species")
    if species:
        lines.append("begin seed species")
        for item in species:
            name = _attribute(item, "name", "id")
            compartment = _attribute(item, "compartment")
            concentration = _attribute(
                item,
                "concentration",
                "initialConcentration",
                "initialAmount",
                default="0",
            )
            full_name = f"{name}@{compartment}" if compartment else name
            lines.append(f"    {_escape_name(full_name)}   {concentration}")
        lines.extend(["end seed species", ""])

    observable_list = _first(model, "ListOfObservables")
    observables = _descendants(observable_list, "Observable")
    if observables:
        lines.append("begin observables")
        for observable in observables:
            observable_type = _attribute(observable, "type", default="Molecules")
            name = _attribute(observable, "name", "id", default="obs")
            pattern = _first(observable, "Pattern")
            pattern_string = _pattern_to_string(pattern) if pattern is not None else ""
            lines.append(f"    {observable_type}    {name}    {pattern_string}")
        lines.extend(["end observables", ""])

    function_list = _first(model, "ListOfFunctions")
    functions = _descendants(function_list, "Function")
    if functions:
        lines.append("begin functions")
        for function in functions:
            name = _attribute(function, "id", "name", default="f")
            expression = _first(function, "Expression", "math")
            lines.append(f"    function {name} = {_text(expression)}")
        lines.extend(["end functions", ""])

    rule_list = _first(model, "ListOfReactionRules")
    reaction_rules = _descendants(rule_list, "ReactionRule")
    if reaction_rules:
        lines.append("begin reaction rules")
        for reaction_rule in reaction_rules:
            reactant_list = _first(reaction_rule, "ListOfReactantPatterns")
            product_list = _first(reaction_rule, "ListOfProductPatterns")
            reactants = [
                _pattern_to_string(pattern)
                for pattern in _descendants(reactant_list, "ReactantPattern")
            ]
            products = [
                _pattern_to_string(pattern, product=True)
                for pattern in _descendants(product_list, "ProductPattern")
            ]
            reactant_string = " + ".join(reactants)
            product_string = " + ".join(products)
            rate = _reaction_rate(reaction_rule, parameter_names)
            lines.append(f"    {reactant_string} -> {product_string}   {rate}")
        lines.extend(["end reaction rules", ""])

    return "\n".join(lines)


# Preserve source-facing spelling for callers porting directly from the
# TypeScript reference while keeping snake_case as BNG3's Python API.
convertBNGXmlToBNGL = convert_bng_xml_to_bngl


__all__ = ["convertBNGXmlToBNGL", "convert_bng_xml_to_bngl"]
