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
    if tag == "lambda":
        body = list(element)[-1] if list(element) else None
        return _mathml_to_formula(body)
    if tag == "bvar":
        child = list(element)[0] if list(element) else None
        return _mathml_to_formula(child)
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
            root = ET.fromstring(sbml_string)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid SBML XML: {exc}") from exc
        model_element = next(
            (element for element in root.iter() if _local_name(element.tag) == "model"),
            None,
        )
        if model_element is None:
            raise ValueError("SBML document has no model")
        return self._parse_xml_model(root, model_element)

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
        return _mathml_to_formula(math_element)

    @staticmethod
    def _xml_items(model: Any, container: str, item: str) -> List[Any]:
        parent = _first_child(model, container)
        return list(_children(parent, item)) if parent is not None else []

    @staticmethod
    def _parse_xml_model(root: Any, model: Any) -> SBMLModel:
        compartments = SBMLParser._parse_xml_compartments(model)
        species = SBMLParser._parse_xml_species(model)
        parameters = SBMLParser._parse_xml_parameters(model)
        reactions = SBMLParser._parse_xml_reactions(model)
        rules = SBMLParser._parse_xml_rules(model)
        functions = SBMLParser._parse_xml_functions(model)
        events = SBMLParser._parse_xml_events(model)
        initial_assignments = SBMLParser._parse_xml_initial_assignments(model)
        species_by_compartment: Dict[str, List[str]] = OrderedDict()
        for species_id, item in species.items():
            species_by_compartment.setdefault(item.compartment, []).append(species_id)
        level = _attribute(root, "level")
        try:
            level_value = int(level) if level is not None else None
        except (TypeError, ValueError):
            level_value = None
        model_id = str(_attribute(model, "id", "model") or "model")
        return SBMLModel(
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
        )

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
                size_set=(
                    _attribute(item, "size") is not None
                    or _attribute(item, "volume") is not None
                ),
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
            for descendant in annotation.iter():
                resource = _attribute(descendant, "resource")
                if resource is not None and _local_name(descendant.tag) == "li":
                    resources.append(str(resource))
                namespace = str(descendant.tag)
                if "biology-qualifiers" in namespace:
                    qualifier_type = 1
                    biological = 0 if _local_name(descendant.tag) == "is" else None
                elif "model-qualifiers" in namespace:
                    qualifier_type = 2
                    model_qualifier = 0 if _local_name(descendant.tag) == "is" else None
            if resources:
                result.append(
                    AnnotationInfo(
                        qualifier_type=qualifier_type,
                        biological_qualifier=biological,
                        model_qualifier=model_qualifier,
                        resources=resources,
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
                sbo_term=_attribute(item, "sboTerm"),
                conversion_factor=_attribute(item, "conversionFactor"),
                charge=(
                    _float(_attribute(item, "charge"))
                    if _attribute(item, "charge") is not None
                    else None
                ),
                species_type=_attribute(item, "speciesType"),
            )
        return result

    @staticmethod
    def _parse_xml_parameters(model: Any) -> Dict[str, SBMLParameter]:
        result: Dict[str, SBMLParameter] = OrderedDict()
        for item in SBMLParser._xml_items(model, "listOfParameters", "parameter"):
            item_id = str(_attribute(item, "id", "") or "")
            if not item_id:
                continue
            result[item_id] = SBMLParameter(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                value=_float(_attribute(item, "value"), 0),
                units=str(_attribute(item, "units", "") or ""),
                constant=_bool(_attribute(item, "constant"), True),
                scope="global",
            )
        return result

    @staticmethod
    def _parse_xml_reference(item: Any) -> SBMLSpeciesReference:
        species = str(_attribute(item, "species", "") or "")
        stoichiometry_set = _attribute(item, "stoichiometry") is not None
        stoichiometry = _float(_attribute(item, "stoichiometry"), 1) or 1
        constant = _bool(_attribute(item, "constant"), True)
        return SBMLSpeciesReference(
            species=species,
            stoichiometry=stoichiometry,
            constant=constant,
            id=(str(_attribute(item, "id")) if _attribute(item, "id") else None),
            stoichiometry_set=stoichiometry_set,
            variable_stoichiometry=not constant,
        )

    @staticmethod
    def _parse_xml_kinetic_law(item: Any) -> Optional[SBMLKineticLaw]:
        if item is None:
            return None
        math = SBMLParser._xml_math(item)
        local_parameters: List[SBMLParameter] = []
        local_parent = _first_child(item, "listOfLocalParameters")
        if local_parent is None:
            local_parent = _first_child(item, "listOfParameters")
        if local_parent is not None:
            for local in _children(local_parent, "localParameter"):
                local_id = str(_attribute(local, "id", "") or "")
                if not local_id:
                    continue
                local_parameters.append(
                    SBMLParameter(
                        id=local_id,
                        name=str(_attribute(local, "name", local_id) or local_id),
                        value=_float(_attribute(local, "value"), 0),
                        units=str(_attribute(local, "units", "") or ""),
                        scope="local",
                    )
                )
        return SBMLKineticLaw(
            math=math,
            math_ml=(
                ET.tostring(_first_child(item, "math"), encoding="unicode")
                if _first_child(item, "math") is not None
                else ""
            ),
            local_parameters=local_parameters,
        )

    @staticmethod
    def _parse_xml_reactions(model: Any) -> Dict[str, SBMLReaction]:
        result: Dict[str, SBMLReaction] = OrderedDict()
        for item in SBMLParser._xml_items(model, "listOfReactions", "reaction"):
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
                        SBMLParser._parse_xml_reference(reference)
                        for reference in _children(reactant_parent, "speciesReference")
                    ]
                    if reactant_parent is not None
                    else []
                ),
                products=(
                    [
                        SBMLParser._parse_xml_reference(reference)
                        for reference in _children(product_parent, "speciesReference")
                    ]
                    if product_parent is not None
                    else []
                ),
                modifiers=(
                    [
                        str(_attribute(reference, "species", "") or "")
                        for reference in _children(
                            modifier_parent, "modifierSpeciesReference"
                        )
                    ]
                    if modifier_parent is not None
                    else []
                ),
                kinetic_law=SBMLParser._parse_xml_kinetic_law(
                    _first_child(item, "kineticLaw")
                ),
                compartment=(
                    str(_attribute(item, "compartment"))
                    if _attribute(item, "compartment")
                    else None
                ),
                conversion_factor=_attribute(item, "conversionFactor"),
            )
        return result

    @staticmethod
    def _parse_xml_rules(model: Any) -> List[SBMLRule]:
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
            result.append(
                SBMLRule(
                    type=kind,
                    variable=(
                        str(_attribute(item, "variable"))
                        if _attribute(item, "variable") is not None
                        else None
                    ),
                    math=SBMLParser._xml_math(item),
                )
            )
        return result

    @staticmethod
    def _parse_xml_functions(model: Any) -> Dict[str, SBMLFunctionDefinition]:
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
                children = list(lambda_element)
                body = children[-1] if children else None
            result[item_id] = SBMLFunctionDefinition(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                math=_mathml_to_formula(body),
                arguments=arguments,
            )
        return result

    @staticmethod
    def _parse_xml_events(model: Any) -> List[SBMLEvent]:
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
                            SBMLParser._xml_math(assignment),
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
                    trigger=SBMLParser._xml_math(trigger),
                    delay=SBMLParser._xml_math(_first_child(item, "delay")) or None,
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
                    priority=SBMLParser._xml_math(priority) or None,
                )
            )
        return result

    @staticmethod
    def _parse_xml_initial_assignments(model: Any) -> List[SBMLInitialAssignment]:
        result: List[SBMLInitialAssignment] = []
        for item in SBMLParser._xml_items(
            model, "listOfInitialAssignments", "initialAssignment"
        ):
            symbol = _attribute(item, "symbol")
            if symbol is not None:
                result.append(
                    SBMLInitialAssignment(
                        symbol=str(symbol), math=SBMLParser._xml_math(item)
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
