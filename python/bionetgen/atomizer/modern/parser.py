"""Pure-XML SBML parser for the Playground-derived atomizer.

The parser deliberately accepts SBML as a string, matching the
Playground implementation while keeping the modern path independent of the
optional and platform-sensitive libSBML SWIG bindings.
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
    coerce_import_warning,
    SBMLModifierSpeciesReference,
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


def _mathml_to_formula(element: Optional[Any]) -> str:
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
                if (expression := _mathml_to_formula(child).strip())
            ),
            "",
        )
    if tag in {"ci", "csymbol"}:
        definition_url = str(_attribute(element, "definitionURL", "") or "").lower()
        if "symbols/time" in definition_url:
            return "time"
        if "symbols/avogadro" in definition_url:
            return "__Avogadro__"
        return _mathml_text(element)
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
    if tag in {"lambda", "bvar", "piece", "otherwise"}:
        return next(
            (
                expression
                for child in children
                if (expression := _mathml_to_formula(child).strip())
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
                value = _mathml_to_formula(part_children[0])
                condition = _mathml_to_formula(part_children[1])
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
            args = [_mathml_to_formula(child) for child in children[1:]]
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
            _mathml_to_formula(child)
            for child in children[1:]
            if _local_name(child.tag) not in {"degree", "logbase"}
        ]
        if operator in {"plus", "times", "minus", "divide", "power"}:
            symbol = {
                "plus": "+",
                "times": "*",
                "minus": "-",
                "divide": "/",
                "power": "^",
            }[operator]
            if operator == "minus" and len(args) == 1:
                return f"-({args[0]})"
            return f" {symbol} ".join(args)
        if operator == "root":
            if degree is not None:
                return f"root({_mathml_to_formula(degree)}, {args[0] if args else ''})"
            return f"sqrt({args[0] if args else ''})"
        if operator == "log":
            if logbase is not None:
                return f"log({_mathml_to_formula(logbase)}, {args[0] if args else ''})"
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
        declared_packages = {
            match.group(1).lower()
            for match in re.finditer(
                r"xmlns(?::[A-Za-z0-9_]+)?\s*=\s*"
                r"[\"']http://www\.sbml\.org/sbml/level3/version\d+/"
                r"([a-z]+)/version\d+[\"']",
                sbml_string,
                re.IGNORECASE,
            )
        }
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
        return _mathml_to_formula(math_element)

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
        root: Any, model: Any, declared_packages: Optional[Iterable[str]] = None
    ) -> SBMLModel:
        compartments = SBMLParser._parse_xml_compartments(model)
        species = SBMLParser._parse_xml_species(model)
        parameter_warnings: List[Dict[str, Any]] = []
        parameter_aliases: Dict[str, str] = {}
        parameters = SBMLParser._parse_xml_parameters(
            model, parameter_warnings, parameter_aliases
        )
        reactions = SBMLParser._parse_xml_reactions(model, parameter_aliases)
        rules = SBMLParser._parse_xml_rules(model, parameter_aliases)
        functions = SBMLParser._parse_xml_functions(model, parameter_aliases)
        events = SBMLParser._parse_xml_events(model, parameter_aliases)
        initial_assignments = SBMLParser._parse_xml_initial_assignments(
            model, parameter_aliases
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
        )
        result.import_warnings.extend(apply_unit_scaling(result))
        result.import_warnings.extend(parameter_warnings)
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
            if reaction.conversion_factor:
                result.import_warnings.append(
                    {
                        "category": "conversionFactor",
                        "message": (
                            f'Reaction "{reaction_id}" declares '
                            f'conversionFactor="{reaction.conversion_factor}"; '
                            "captured but not applied to the rate law."
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
            "multi": "multistate/multicomponent species beyond the conservative reference extraction",
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
        }
        package_counts: Dict[str, int] = {
            str(package).lower(): 0 for package in (declared_packages or [])
        }
        package_uri = re.compile(
            r"^http://www\.sbml\.org/sbml/level3/version\d+/" r"([a-z]+)/version\d+$",
            re.IGNORECASE,
        )
        for element in root.iter():
            tag = str(getattr(element, "tag", ""))
            if not tag.startswith("{") or "}" not in tag:
                continue
            uri = tag[1:].split("}", 1)[0]
            match = package_uri.match(uri)
            if match:
                package_counts[match.group(1).lower()] = (
                    package_counts.get(match.group(1).lower(), 0) + 1
                )
        package_reasons = {
            "fbc": " This is a constraint-based flux-balance model, not a kinetic time-course model.",
            "qual": " This is a discrete logical model, not a continuous-time kinetic network.",
        }
        for package, description in dynamic_packages.items():
            if package not in package_counts:
                continue
            count = package_counts[package]
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
    def _parse_xml_parameters(
        model: Any,
        warnings: Optional[List[Dict[str, Any]]] = None,
        aliases: Optional[Dict[str, str]] = None,
    ) -> Dict[str, SBMLParameter]:
        result: Dict[str, SBMLParameter] = OrderedDict()
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
            if aliases is not None:
                SBMLParser._register_alias(aliases, raw_id, parameter.id)
                SBMLParser._register_alias(aliases, parameter.id, parameter.id)
                SBMLParser._register_alias(aliases, parameter.name, parameter.id)
        return result

    @staticmethod
    def _parse_xml_reference(item: Any) -> SBMLSpeciesReference:
        species = str(_attribute(item, "species", "") or "")
        stoichiometry_set = _attribute(item, "stoichiometry") is not None
        stoichiometry = (
            _float(_attribute(item, "stoichiometry"), 1) if stoichiometry_set else 1
        )
        constant = _bool(_attribute(item, "constant"), True)
        stoichiometry_math_set = _first_child(item, "stoichiometryMath") is not None
        return SBMLSpeciesReference(
            species=species,
            stoichiometry=stoichiometry,
            constant=constant,
            id=(str(_attribute(item, "id")) if _attribute(item, "id") else None),
            stoichiometry_set=stoichiometry_set,
            variable_stoichiometry=not constant or stoichiometry_math_set,
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
            for local_index, local in enumerate(
                _children(local_parent, "localParameter")
            ):
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
            )
        return result

    @staticmethod
    def _parse_xml_rules(
        model: Any, parameter_aliases: Optional[Dict[str, str]] = None
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
            result.append(
                SBMLRule(
                    type=kind,
                    variable=(
                        str(_attribute(item, "variable"))
                        if _attribute(item, "variable") is not None
                        else None
                    ),
                    math=SBMLParser._normalize_formula_identifiers(
                        SBMLParser._xml_math(item), parameter_aliases
                    ),
                )
            )
        return result

    @staticmethod
    def _parse_xml_functions(
        model: Any, parameter_aliases: Optional[Dict[str, str]] = None
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
                children = list(lambda_element)
                body = children[-1] if children else None
            result[item_id] = SBMLFunctionDefinition(
                id=item_id,
                name=str(_attribute(item, "name", item_id) or item_id),
                math=SBMLParser._normalize_formula_identifiers(
                    _mathml_to_formula(body), parameter_aliases
                ),
                arguments=arguments,
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
                )
            )
        return result

    @staticmethod
    def _parse_xml_initial_assignments(
        model: Any, parameter_aliases: Optional[Dict[str, str]] = None
    ) -> List[SBMLInitialAssignment]:
        result: List[SBMLInitialAssignment] = []
        for item in SBMLParser._xml_items(
            model, "listOfInitialAssignments", "initialAssignment"
        ):
            symbol = _attribute(item, "symbol")
            if symbol is not None:
                result.append(
                    SBMLInitialAssignment(
                        symbol=str(symbol),
                        math=SBMLParser._normalize_formula_identifiers(
                            SBMLParser._xml_math(item), parameter_aliases
                        ),
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
