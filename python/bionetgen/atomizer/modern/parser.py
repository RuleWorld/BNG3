"""SBML parser for the Playground-derived atomizer.

The parser deliberately accepts SBML as a string.  This mirrors the
Playground implementation and avoids the unstable SWIG file-reader path on
some Python libSBML wheels.  libSBML remains responsible for SBML semantics;
the small XML pass only preserves attributes that reduced bindings omit.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional

from .types import (
    AnnotationInfo,
    SBMLEvent,
    SBMLCompartment,
    SBMLFunctionDefinition,
    SBMLInitialAssignment,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLRule,
    SBMLSpecies,
    SBMLSpeciesReference,
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: Any, name: str) -> Iterable[Any]:
    return (child for child in list(element) if _local_name(child.tag) == name)


def _first_child(element: Any, name: str) -> Optional[Any]:
    return next(iter(_children(element, name)), None)


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


def _mathml_to_formula(element: Optional[Any]) -> str:
    """Small fallback for reduced bindings that cannot stringify MathML."""

    if element is None:
        return ""
    tag = _local_name(element.tag)
    if tag in {"ci", "cn", "csymbol"}:
        return (element.text or "").strip()
    if tag == "true":
        return "1"
    if tag == "false":
        return "0"
    if tag == "apply":
        children = list(element)
        if not children:
            return ""
        operator = _local_name(children[0].tag)
        args = [_mathml_to_formula(child) for child in children[1:]]
        if operator in {"plus", "times", "minus", "divide", "power"}:
            symbols = {
                "plus": "+",
                "times": "*",
                "minus": "-",
                "divide": "/",
                "power": "^",
            }
            symbol = symbols[operator]
            if operator == "minus" and len(args) == 1:
                return f"-({args[0]})"
            return f" {symbol} ".join(args)
        if operator in {"ln", "log", "exp", "sqrt", "abs", "sin", "cos", "tan"}:
            return f"{operator}({', '.join(args)})"
        if operator == "root":
            return f"root({', '.join(args)})"
        return f"{operator}({', '.join(args)})"
    if tag == "piecewise":
        parts = list(element)
        branches = []
        fallback = "0"
        for part in parts:
            if _local_name(part.tag) == "piece":
                values = list(part)
                if len(values) >= 2:
                    branches.append(
                        (_mathml_to_formula(values[1]), _mathml_to_formula(values[0]))
                    )
            elif _local_name(part.tag) == "otherwise":
                values = list(part)
                if values:
                    fallback = _mathml_to_formula(values[0])
        result = fallback
        for value, condition in reversed(branches):
            result = f"if({condition}, {value}, {result})"
        return result
    children = list(element)
    return _mathml_to_formula(children[0]) if children else _mathml_text(element)


class SBMLParser:
    """Parse SBML text into the atomizer's stable intermediate model."""

    def parse(self, sbml_string: str) -> SBMLModel:
        try:
            import libsbml
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "python-libsbml is required for the modern atomizer"
            ) from exc

        try:
            root = ET.fromstring(sbml_string)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid SBML XML: {exc}") from exc

        document = libsbml.SBMLReader().readSBMLFromString(sbml_string)
        sbml_model = document.getModel() if document is not None else None
        if sbml_model is None:
            messages = []
            if document is not None:
                for index in range(document.getNumErrors()):
                    messages.append(document.getError(index).getMessage())
            detail = "; ".join(messages[:3])
            raise ValueError(
                "SBML document has no model" + (f": {detail}" if detail else "")
            )

        raw_by_kind_id = self._raw_elements(root)
        compartments = self._parse_compartments(
            sbml_model, raw_by_kind_id.get("compartment", {})
        )
        species = self._parse_species(
            sbml_model, raw_by_kind_id.get("species", {}), libsbml
        )
        parameters = self._parse_parameters(sbml_model)
        reactions = self._parse_reactions(
            sbml_model, raw_by_kind_id.get("reaction", {}), libsbml
        )
        rules = self._parse_rules(sbml_model, libsbml)
        functions = self._parse_functions(sbml_model, libsbml)
        events = self._parse_events(sbml_model, libsbml)
        initial_assignments = self._parse_initial_assignments(sbml_model, libsbml)

        species_by_compartment: Dict[str, List[str]] = OrderedDict()
        for species_id, item in species.items():
            species_by_compartment.setdefault(item.compartment, []).append(species_id)

        unit_definitions = self._parse_units(sbml_model)
        return SBMLModel(
            id=str(sbml_model.getId() or "model"),
            name=str(sbml_model.getName() or sbml_model.getId() or "model"),
            compartments=compartments,
            species=species,
            parameters=parameters,
            reactions=reactions,
            rules=rules,
            function_definitions=functions,
            events=events,
            initial_assignments=initial_assignments,
            species_by_compartment=species_by_compartment,
            unit_definitions=unit_definitions,
            level=(
                int(sbml_model.getLevel()) if hasattr(sbml_model, "getLevel") else None
            ),
        )

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
                size_set="size" in attrs or "volume" in attrs,
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
    def _parse_parameters(model: Any) -> Mapping[str, SBMLParameter]:
        result: Dict[str, SBMLParameter] = OrderedDict()
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
            stoichiometry=stoichiometry or 1,
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
                    str(item.getModifier(i).getSpecies())
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
    seen = set()
    for resource in resources:
        match = re.search(
            r"(?:^|[:/])uniprot[:/]([A-Za-z0-9][A-Za-z0-9_-]*)$",
            str(resource),
            re.IGNORECASE,
        )
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            result.append(match.group(1))
    return result


def extract_go_terms(resources: Iterable[str]) -> List[str]:
    result = []
    seen = set()
    for resource in resources:
        match = re.search(r"(?:^|[:/])go[:/]?(GO:\d+)$", str(resource), re.IGNORECASE)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            result.append(match.group(1))
    return result


__all__ = ["SBMLParser", "extract_go_terms", "extract_uniprot_ids"]
