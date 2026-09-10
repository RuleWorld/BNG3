"""SBML Level 3 Multi v1 parsing and executable BNGL reconstruction.

The parser validates the released Multi vocabulary and semantic references,
retains structured diagnostics for unsupported constructs, and lowers every
representable structure into the modern Atomizer's BNGL metadata contract.
Patterns that cannot be represented by one BNGL rule are preserved as
diagnostics and fail closed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

from .structures import read_from_string
from .types import SBMLImportWarning, SBMLMultiComponentMap

MULTI_V1_NAMESPACE = "http://www.sbml.org/sbml/level3/version1/multi/version1"
CORE_V1_NAMESPACE = "http://www.sbml.org/sbml/level3/version1/core"
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _attribute(element: Any, name: str, default: str = "") -> str:
    for key, value in getattr(element, "attrib", {}).items():
        if key == name or _local_name(key) == name:
            return str(value)
    return default


def _namespaced_attribute(
    element: Any, namespace: str, name: str, default: str = ""
) -> str:
    key = f"{{{namespace}}}{name}"
    return str(getattr(element, "attrib", {}).get(key, default) or default)


def _bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def _children(element: Any, name: str, namespace: Optional[str] = None) -> List[Any]:
    if element is None:
        return []
    return [
        child
        for child in list(element)
        if _local_name(child.tag) == name
        and (namespace is None or _namespace(child.tag) == namespace)
    ]


def _first_child(
    element: Any, name: str, namespace: Optional[str] = None
) -> Optional[Any]:
    children = _children(element, name, namespace)
    return children[0] if children else None


def _clean(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value or "")


@dataclass
class _Instance:
    id: str
    type_id: str
    name: str
    compartment_reference: str = ""


@dataclass
class _SpeciesType:
    id: str
    name: str
    is_binding_site: bool = False
    compartment: str = ""
    features: List[Tuple[str, List[str]]] = field(default_factory=list)
    feature_definitions: Dict[str, Tuple[str, Dict[str, str]]] = field(
        default_factory=dict
    )
    feature_occurs: Dict[str, int] = field(default_factory=dict)
    feature_numeric_values: Dict[str, str] = field(default_factory=dict)
    instances: List[_Instance] = field(default_factory=list)
    component_indexes: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    bonds: List[Tuple[str, str]] = field(default_factory=list)


class MultiComplexPattern(NamedTuple):
    """Reference-shaped Multi complex record with legacy tuple behavior."""

    type_id: str
    pattern: str

    @property
    def typeId(self) -> str:
        return self.type_id


@dataclass
class MultiParseResult:
    present: bool = False
    deep: bool = False
    bngl_molecule_types: List[str] = field(default_factory=list)
    complex_patterns: List[MultiComplexPattern] = field(default_factory=list)
    seed_patterns: List[Tuple[str, str]] = field(default_factory=list)
    species_patterns: Dict[str, str] = field(default_factory=dict)
    type_patterns: Dict[str, str] = field(default_factory=dict)
    component_aliases: Dict[str, Dict[str, List[Tuple[str, int, int]]]] = field(
        default_factory=dict
    )
    reaction_product_maps: Dict[str, Dict[str, List[Any]]] = field(default_factory=dict)
    compartment_references: Dict[str, Dict[str, str]] = field(default_factory=dict)
    numeric_values: Dict[str, str] = field(default_factory=dict)
    executable: bool = False
    warnings: List[SBMLImportWarning] = field(default_factory=list)

    @property
    def bnglMoleculeTypes(self) -> List[str]:
        return self.bngl_molecule_types

    @bnglMoleculeTypes.setter
    def bnglMoleculeTypes(self, value: List[str]) -> None:
        self.bngl_molecule_types = value

    @property
    def complexPatterns(self) -> List[MultiComplexPattern]:
        return self.complex_patterns

    @complexPatterns.setter
    def complexPatterns(self, value: List[MultiComplexPattern]) -> None:
        self.complex_patterns = value

    @property
    def seedPatterns(self) -> List[Tuple[str, str]]:
        return self.seed_patterns

    @seedPatterns.setter
    def seedPatterns(self, value: List[Tuple[str, str]]) -> None:
        self.seed_patterns = value

    @property
    def speciesPatterns(self) -> Dict[str, str]:
        return self.species_patterns

    @speciesPatterns.setter
    def speciesPatterns(self, value: Dict[str, str]) -> None:
        self.species_patterns = value

    @property
    def typePatterns(self) -> Dict[str, str]:
        return self.type_patterns

    @typePatterns.setter
    def typePatterns(self, value: Dict[str, str]) -> None:
        self.type_patterns = value

    @property
    def componentAliases(self) -> Dict[str, Dict[str, List[Tuple[str, int, int]]]]:
        return self.component_aliases

    @componentAliases.setter
    def componentAliases(
        self, value: Dict[str, Dict[str, List[Tuple[str, int, int]]]]
    ) -> None:
        self.component_aliases = value

    @property
    def reactionProductMaps(self) -> Dict[str, Dict[str, List[Any]]]:
        return self.reaction_product_maps

    @reactionProductMaps.setter
    def reactionProductMaps(self, value: Dict[str, Dict[str, List[Any]]]) -> None:
        self.reaction_product_maps = value

    @property
    def compartmentReferences(self) -> Dict[str, Dict[str, str]]:
        return self.compartment_references

    @compartmentReferences.setter
    def compartmentReferences(self, value: Dict[str, Dict[str, str]]) -> None:
        self.compartment_references = value

    @property
    def numericValues(self) -> Dict[str, str]:
        return self.numeric_values

    @numericValues.setter
    def numericValues(self, value: Dict[str, str]) -> None:
        self.numeric_values = value


def _warning(message: str, severity: str = "approximated") -> SBMLImportWarning:
    return SBMLImportWarning(
        category="package:multi", message=message, count=1, severity=severity
    )


def _as_root(document: Union[str, Any]) -> Any:
    if isinstance(document, str):
        if not document.strip():
            return None
        return ET.fromstring(document)
    return document


def _multi_namespace(root: Any, source: Optional[str] = None) -> Optional[str]:
    if source:
        match = re.search(
            r"\bxmlns:([A-Za-z0-9_]+)\s*=\s*[\"']"
            r"(http://www\.sbml\.org/sbml/level3/version\d+/multi/version\d+)"
            r"[\"']",
            source,
            re.IGNORECASE,
        )
        if match:
            return match.group(2)
    for element in root.iter():
        namespace = _namespace(element.tag)
        if "/multi/" in namespace:
            return namespace
    return None


def _model_element(root: Any) -> Optional[Any]:
    return next(
        (element for element in root.iter() if _local_name(element.tag) == "model"),
        None,
    )


def _sites_of(species_type: _SpeciesType, binding_sites: set) -> List[Tuple[set, str]]:
    result = []
    for instance in species_type.instances:
        if instance.type_id in binding_sites:
            result.append(
                (
                    {instance.id, instance.type_id, instance.name},
                    _clean(instance.name or instance.id),
                )
            )
    return result


def _declaration(species_type: _SpeciesType, binding_sites: set) -> str:
    features = [
        f"{_clean(name)}~{'~'.join(_clean(state) for state in states)}"
        for name, states in species_type.features
    ]
    sites = [label for _keys, label in _sites_of(species_type, binding_sites)]
    return f"{species_type.name}({','.join(features + sites)})"


def _species_pattern(
    species: Any,
    species_type: _SpeciesType,
    binding_sites: set,
    namespace: str,
) -> Optional[str]:
    """Render a conservative pattern for a direct single-molecule species.

    Multi omits unspecified features and outward sites deliberately: omitted
    feature values mean don't-care, and omitted outward binding sites mean
    bindingStatus="either". BNGL's ``!?`` is the closest comment-only pattern
    representation for that latter state. Complexes still use the type-level
    reconstruction path.
    """

    if any(
        instance.type_id not in binding_sites
        for instance in species_type.instances
        if instance.type_id
    ):
        return None

    explicit_features: Dict[str, List[str]] = {}
    feature_list = _first_child(species, "listOfSpeciesFeatures", namespace)
    for feature in _children(feature_list, "speciesFeature", namespace):
        feature_id = _attribute(feature, "speciesFeatureType")
        definition = species_type.feature_definitions.get(feature_id)
        if definition is None:
            continue
        _feature_name, value_labels = definition
        values_parent = _first_child(feature, "listOfSpeciesFeatureValues", namespace)
        values = []
        for value in _children(values_parent, "speciesFeatureValue", namespace):
            raw = _attribute(value, "value")
            values.append(_clean(value_labels.get(raw, raw)))
        if values:
            explicit_features[feature_id] = values

    outward: Dict[str, str] = {}
    outward_list = _first_child(species, "listOfOutwardBindingSites", namespace)
    for item in _children(outward_list, "outwardBindingSite", namespace):
        component = _attribute(item, "component")
        status = _attribute(item, "bindingStatus", "either").lower()
        if component:
            outward[component] = status

    components: List[str] = []
    for feature_id, (feature_name, _values) in species_type.feature_definitions.items():
        selected = explicit_features.get(feature_id, [])
        if len(selected) == 1:
            components.append(f"{feature_name}~{selected[0]}")
        elif len(selected) > 1:
            # BNGL cannot express Multi's value disjunction in one seed
            # pattern; retain the state domain as a visible approximation.
            components.append(f"{feature_name}~{'~'.join(selected)}")

    for keys, label in _sites_of(species_type, binding_sites):
        status = next((outward[key] for key in keys if key in outward), "either")
        suffix = {"bound": "!+", "either": "!?"}.get(status, "")
        components.append(f"{label}{suffix}")
    return f"{species_type.name}({','.join(components)})"


def parse_multi_package(document: Union[str, Any]) -> MultiParseResult:
    """Extract canonical Multi-package molecule/complex references."""

    source = document if isinstance(document, str) else None
    root = _as_root(document)
    if root is None:
        return MultiParseResult()
    namespace = _multi_namespace(root, source)
    if namespace is None:
        return MultiParseResult()

    warnings: List[SBMLImportWarning] = []
    spec_warnings: List[SBMLImportWarning] = []
    if namespace != MULTI_V1_NAMESPACE:
        spec_warnings.append(
            _warning(
                f'SBML Multi namespace "{namespace}" is not the released '
                f'Level 3 Multi Version 1 namespace "{MULTI_V1_NAMESPACE}"; '
                "parsed conservatively.",
                "approximated",
            )
        )

    required = _namespaced_attribute(root, namespace, "required")
    if required == "":
        spec_warnings.append(
            _warning(
                "SBML Multi is used but the root sbml element has no "
                "multi:required attribute; the package requirement is not explicit.",
                "approximated",
            )
        )
    elif not _bool(required):
        spec_warnings.append(
            _warning(
                'SBML Multi is used with multi:required="false"; a core-only '
                "consumer may legally ignore the package, so executable flattening "
                "is disabled.",
                "dropped",
            )
        )

    # Multi attributes added to core elements must carry the Multi namespace.
    # Keep parsing legacy hand-authored fixtures, but make the spec violation visible.
    for element in root.iter():
        if _local_name(element.tag) not in {"species", "compartment"}:
            continue
        for key in getattr(element, "attrib", {}):
            if key in {"speciesType", "compartmentType", "isType"}:
                spec_warnings.append(
                    _warning(
                        f'Multi attribute "{key}" on {_local_name(element.tag)} '
                        "is unqualified; SBML package attributes on core elements "
                        "must use the Multi namespace.",
                        "approximated",
                    )
                )

    compartment_parent = _first_child(_model_element(root), "listOfCompartments")
    for compartment in _children(compartment_parent, "compartment"):
        if _namespaced_attribute(
            compartment, namespace, "compartmentType"
        ) and not _namespaced_attribute(compartment, namespace, "isType"):
            spec_warnings.append(
                _warning(
                    f'Compartment "{_attribute(compartment, "id")}" uses '
                    "Multi compartmentType without the required Multi isType "
                    "attribute; the compartment extension is not reconstructed.",
                    "approximated",
                )
            )

    if any(
        _local_name(element.tag) == "subListOfSpeciesFeatures"
        for element in root.iter()
    ):
        spec_warnings.append(
            _warning(
                "SBML Multi subListOfSpeciesFeatures relations are preserved only "
                "as diagnostics; BNGL reference seeds use direct feature values.",
                "approximated",
            )
        )
    for feature in root.iter():
        if _local_name(feature.tag) != "speciesFeature":
            continue
        try:
            occur = int(_attribute(feature, "occur", "1"))
        except ValueError:
            occur = 1
        if occur > 1:
            spec_warnings.append(
                _warning(
                    "SBML Multi speciesFeature occurrences greater than one are "
                    "not flattened into a single BNGL component.",
                    "approximated",
                )
            )

    model = _model_element(root)
    list_types = _first_child(model, "listOfSpeciesTypes", namespace)
    if list_types is None:
        warnings.append(
            _warning(
                "SBML Multi package is present but no listOfSpeciesTypes was found.",
                "info",
            )
        )
        return MultiParseResult(
            present=True,
            warnings=warnings + spec_warnings,
        )

    binding_sites = {
        _attribute(item, "id")
        for item in _children(list_types, "bindingSiteSpeciesType", namespace)
        if _attribute(item, "id")
    }
    species_types: Dict[str, _SpeciesType] = {}
    for item in _children(list_types, "speciesType", namespace):
        type_id = _attribute(item, "id")
        if not type_id:
            continue
        species_type = _SpeciesType(
            id=type_id,
            name=_clean(_attribute(item, "name") or type_id),
        )
        feature_list = _first_child(item, "listOfSpeciesFeatureTypes", namespace)
        for feature in _children(feature_list, "speciesFeatureType", namespace):
            values: List[str] = []
            value_labels: Dict[str, str] = {}
            possible = _first_child(
                feature, "listOfPossibleSpeciesFeatureValues", namespace
            )
            for value in _children(possible, "possibleSpeciesFeatureValue", namespace):
                value_id = _attribute(value, "id")
                label = _clean(_attribute(value, "name") or value_id)
                if label:
                    values.append(label)
                    if value_id:
                        value_labels[value_id] = label
            feature_name = _clean(
                _attribute(feature, "name") or _attribute(feature, "id")
            )
            if feature_name:
                species_type.features.append((feature_name, values))
                feature_id = _attribute(feature, "id")
                if feature_id:
                    species_type.feature_definitions[feature_id] = (
                        feature_name,
                        value_labels,
                    )

        instance_list = _first_child(item, "listOfSpeciesTypeInstances", namespace)
        if is_binding_site and instance_list is not None:
            warnings.append(
                _warning(
                    f'Multi bindingSiteSpeciesType "{type_id}" must be atomic '
                    "and cannot contain speciesTypeInstance children.",
                    "dropped",
                )
            )
        for instance in _children(instance_list, "speciesTypeInstance", namespace):
            instance_id = _attribute(instance, "id")
            instance_type = _attribute(instance, "speciesType")
            if instance_id and instance_type:
                species_type.instances.append(
                    _Instance(
                        id=instance_id,
                        type_id=instance_type,
                        name=_clean(_attribute(instance, "name") or instance_id),
                    )
                )

        index_list = _first_child(item, "listOfSpeciesTypeComponentIndexes", namespace)
        for component in _children(index_list, "speciesTypeComponentIndex", namespace):
            component_id = _attribute(component, "id")
            if component_id:
                species_type.component_indexes[component_id] = (
                    _attribute(component, "component"),
                    _attribute(component, "identifyingParent"),
                )

        bond_list = _first_child(item, "listOfInSpeciesTypeBonds", namespace)
        for bond in _children(bond_list, "inSpeciesTypeBond", namespace):
            site1 = _attribute(bond, "bindingSite1")
            site2 = _attribute(bond, "bindingSite2")
            if site1 and site2:
                species_type.bonds.append((site1, site2))
        species_types[type_id] = species_type

    if not species_types and not binding_sites:
        warnings.append(
            _warning(
                "SBML Multi listOfSpeciesTypes is empty; the package cannot define "
                "species types, features, or binding sites.",
                "dropped",
            )
        )

    top_types = []
    for element in root.iter():
        for attribute, value in getattr(element, "attrib", {}).items():
            if _local_name(attribute) != "speciesType":
                continue
            if _namespace(attribute) != namespace:
                continue
            type_id = str(value)
            if type_id in species_types and type_id not in top_types:
                top_types.append(type_id)

    # Keep compatibility with hand-authored fixtures that use an unqualified
    # speciesType attribute on a core species element.
    species_list = _first_child(model, "listOfSpecies")
    for species in _children(species_list, "species"):
        type_id = _attribute(species, "speciesType")
        if type_id in species_types and type_id not in top_types:
            top_types.append(type_id)

    if not top_types:
        warnings.append(
            _warning(
                "SBML Multi package has species types but no referenced top-level "
                "species type.",
                "info",
            )
        )
        return MultiParseResult(
            present=True,
            warnings=warnings + spec_warnings,
        )

    def is_container(species_type: _SpeciesType) -> bool:
        return any(
            instance.type_id in species_types for instance in species_type.instances
        )

    deep = any(
        any(
            instance.type_id in species_types
            and is_container(species_types[instance.type_id])
            for instance in species_types[type_id].instances
        )
        for type_id in top_types
    )
    if deep:
        names = []
        for species_type in species_types.values():
            if species_type.name not in names and not re.match(
                r"^(?:mcp|bst|cps|mol)[_-]?\d", species_type.name, re.IGNORECASE
            ):
                names.append(species_type.name)
        return MultiParseResult(
            present=True,
            deep=True,
            warnings=warnings
            + [
                _warning(
                    "SBML Multi package uses a multi-layer hierarchy; molecule "
                    "boundaries cannot be inferred safely, so complexes were not "
                    f"reconstructed. Molecule names: {', '.join(names[:20])}."
                )
            ]
            + spec_warnings,
        )

    molecule_type_ids = []
    for type_id in top_types:
        top = species_types[type_id]
        subtypes = [
            instance.type_id
            for instance in top.instances
            if instance.type_id in species_types
        ]
        candidates = subtypes or [type_id]
        for candidate in candidates:
            if candidate not in molecule_type_ids:
                molecule_type_ids.append(candidate)
    molecule_types = [
        _declaration(species_types[type_id], binding_sites)
        for type_id in molecule_type_ids
    ]

    complex_patterns: List[MultiComplexPattern] = []
    unresolved = 0
    for type_id in top_types:
        top = species_types[type_id]
        subtypes = [
            instance for instance in top.instances if instance.type_id in species_types
        ]
        if not subtypes:
            continue

        def resolve(reference: str) -> Optional[Tuple[str, str]]:
            component, parent = top.component_indexes.get(reference, (reference, ""))
            instance_id = ""
            if parent and any(item.id == parent for item in subtypes):
                instance_id = parent
            elif any(item.id == component for item in subtypes):
                instance_id = component
            if not instance_id:
                return None
            instance = next(item for item in subtypes if item.id == instance_id)
            sites = _sites_of(species_types[instance.type_id], binding_sites)
            site = next((item for item in sites if component in item[0]), None)
            if site is None and len(sites) == 1:
                site = sites[0]
            return (instance_id, site[1]) if site is not None else None

        bond_map: Dict[str, Dict[str, int]] = {}
        ok = True
        bond_number = 0
        for site1, site2 in top.bonds:
            endpoint1 = resolve(site1)
            endpoint2 = resolve(site2)
            if endpoint1 is None or endpoint2 is None:
                ok = False
                break
            bond_number += 1
            bond_map.setdefault(endpoint1[0], {})[endpoint1[1]] = bond_number
            bond_map.setdefault(endpoint2[0], {})[endpoint2[1]] = bond_number
        if not ok:
            unresolved += 1
            continue

        molecules = []
        for instance in subtypes:
            sites = _sites_of(species_types[instance.type_id], binding_sites)
            labels = []
            for _keys, label in sites:
                bond = bond_map.get(instance.id, {}).get(label)
                labels.append(f"{label}!{bond}" if bond is not None else label)
            molecules.append(
                f"{species_types[instance.type_id].name}({','.join(labels)})"
            )
        complex_patterns.append(MultiComplexPattern(type_id, ".".join(molecules)))

    warnings.extend(spec_warnings)
    if unresolved:
        warnings.append(
            _warning(
                f"{unresolved} Multi complex type(s) had bonds that could not be "
                "resolved; molecule types were retained."
            )
        )
    if molecule_types:
        suffix = (
            f" Reconstructed {len(complex_patterns)} bonded complex pattern(s)."
            if complex_patterns
            else ""
        )
        warnings.append(
            _warning(
                f"SBML Multi package: extracted {len(molecule_types)} molecule "
                f"type(s) with binding sites and states.{suffix}"
            )
        )

    # A concrete species instance can safely retain the reconstructed complex
    # as a reference seed.  Do not inject it into BNGL: Multi species feature
    # values, omitted features, and outward-site semantics still need an
    # execution oracle before they can become initial conditions.
    complex_by_type = {item.type_id: item.pattern for item in complex_patterns}
    seed_patterns: List[Tuple[str, str]] = []
    for species in _children(_first_child(model, "listOfSpecies"), "species"):
        type_id = _namespaced_attribute(species, namespace, "speciesType")
        if not type_id:
            type_id = _attribute(species, "speciesType")
        if type_id not in top_types:
            continue
        if (
            _attribute(species, "initialAmount") == ""
            and _attribute(species, "initialConcentration") == ""
        ):
            continue
        pattern = complex_by_type.get(type_id)
        if pattern is None:
            top = species_types[type_id]
            pattern = _species_pattern(species, top, binding_sites, namespace)
        if pattern:
            seed_patterns.append((_attribute(species, "id"), pattern))

    return MultiParseResult(
        present=True,
        bngl_molecule_types=molecule_types,
        complex_patterns=complex_patterns,
        seed_patterns=seed_patterns,
        warnings=warnings,
    )


@dataclass
class _FlatComponent:
    label: str
    aliases: set = field(default_factory=set)
    states: List[str] = field(default_factory=list)
    feature_ids: set = field(default_factory=set)
    active_state: str = ""
    binding_status: str = ""
    bonds: List[int] = field(default_factory=list)
    feature_occurrence: int = 1
    is_binding_site: bool = False


@dataclass
class _FlatMolecule:
    name: str
    aliases: set = field(default_factory=set)
    components: List[_FlatComponent] = field(default_factory=list)
    compartment: str = ""


@dataclass
class _FlatType:
    molecules: List[_FlatMolecule] = field(default_factory=list)
    bonds: List[Tuple[_FlatComponent, _FlatComponent]] = field(default_factory=list)


def _flat_component_aliases(
    flat: _FlatType,
) -> Dict[str, List[Tuple[str, int, int]]]:
    """Index Multi aliases by flattened BNGL location."""

    result: Dict[str, List[Tuple[str, int, int]]] = {}

    def add(alias: str, kind: str, molecule_index: int, component_index: int) -> None:
        alias = str(alias or "")
        if not alias:
            return
        location = (kind, molecule_index, component_index)
        if location not in result.setdefault(alias, []):
            result[alias].append(location)

    for molecule_index, molecule in enumerate(flat.molecules):
        for alias in molecule.aliases:
            add(alias, "molecule", molecule_index, -1)
        for component_index, component in enumerate(molecule.components):
            for alias in component.aliases:
                add(alias, "component", molecule_index, component_index)
    return result


def _clean_pattern_name(value: str, fallback: str) -> str:
    """Get a BNGL molecule name from a Multi name or identifier."""

    candidate = str(value or fallback or "")
    if "(" in candidate:
        candidate = candidate.split("(", 1)[0]
    candidate = _clean(candidate)
    return candidate or _clean(fallback) or "Molecule"


def _feature_defs(
    species_type: _SpeciesType,
) -> List[Tuple[str, str, List[str], int]]:
    result: List[Tuple[str, str, List[str], int]] = []
    for feature_id, (feature_name, labels) in species_type.feature_definitions.items():
        occur = species_type.feature_occurs.get(feature_id, 1)
        for occurrence in range(1, occur + 1):
            label = _clean(feature_name)
            if occur > 1:
                label = f"{label}_{occurrence}"
            result.append((feature_id, label, list(labels.values()), occurrence))
    return result


def _feature_value(species_type: _SpeciesType, feature_id: str, raw_value: str) -> str:
    definition = species_type.feature_definitions.get(feature_id)
    if definition is None:
        return _clean(raw_value)
    _name, labels = definition
    return _clean(labels.get(raw_value, raw_value))


def _is_complex_type(type_id: str, types: Dict[str, _SpeciesType]) -> bool:
    species_type = types.get(type_id)
    if species_type is None:
        return False
    return any(
        instance.type_id in types and not types[instance.type_id].is_binding_site
        for instance in species_type.instances
    )


def _find_component(
    flat_type: _FlatType, token: str, parent: str = ""
) -> Optional[Tuple[_FlatMolecule, _FlatComponent]]:
    candidates = flat_type.molecules
    if parent:
        candidates = [molecule for molecule in candidates if parent in molecule.aliases]
    for molecule in candidates:
        for component in molecule.components:
            if token in component.aliases:
                return molecule, component
    return None


def _find_molecule(flat_type: _FlatType, token: str) -> Optional[_FlatMolecule]:
    return next(
        (molecule for molecule in flat_type.molecules if token in molecule.aliases),
        None,
    )


def _apply_component_indexes(species_type: _SpeciesType, flat_type: _FlatType) -> None:
    for index_id, (component, parent) in species_type.component_indexes.items():
        if parent:
            found = _find_component(flat_type, component, parent)
            if found is not None:
                found[1].aliases.add(index_id)
            continue
        molecule = _find_molecule(flat_type, component)
        if molecule is not None:
            molecule.aliases.add(index_id)
            continue
        found = _find_component(flat_type, component)
        if found is not None:
            found[1].aliases.add(index_id)


def _resolve_bond_endpoint(
    species_type: _SpeciesType, flat_type: _FlatType, reference: str
) -> Optional[Tuple[_FlatMolecule, _FlatComponent]]:
    component, parent = species_type.component_indexes.get(reference, (reference, ""))
    found = _find_component(flat_type, component, parent)
    if found is not None:
        return found
    if component != reference:
        found = _find_component(flat_type, reference, parent)
        if found is not None:
            return found
    # Older Multi producers used a component index token that was not copied
    # into the nested binding-site declaration.  Preserve the Playground
    # fallback when scope leaves exactly one possible component.
    scoped = [
        (molecule, candidate)
        for molecule in flat_type.molecules
        for candidate in molecule.components
        if not parent or parent in molecule.aliases
    ]
    if len(scoped) == 1:
        return scoped[0]
    return None


def _flatten_type(
    type_id: str,
    types: Dict[str, _SpeciesType],
    warnings: List[SBMLImportWarning],
    stack: Tuple[str, ...] = (),
    compartment_references: Optional[Dict[str, Dict[str, str]]] = None,
    inherited_compartment: str = "",
) -> _FlatType:
    """Resolve any Multi speciesType hierarchy into BNGL molecules."""

    if type_id not in types:
        warnings.append(
            _warning(f'Multi speciesType "{type_id}" is undefined.', "dropped")
        )
        return _FlatType()
    if type_id in stack:
        warnings.append(
            _warning(
                "SBML Multi speciesType hierarchy contains a cycle at "
                f'"{type_id}"; the affected structure was not executable.',
                "dropped",
            )
        )
        return _FlatType()

    species_type = types[type_id]
    effective_compartment = inherited_compartment or species_type.compartment
    children = [
        instance
        for instance in species_type.instances
        if instance.type_id in types and not types[instance.type_id].is_binding_site
    ]
    flat = _FlatType()
    if children and species_type.feature_definitions:
        warnings.append(
            _warning(
                f'Multi composite speciesType "{type_id}" defines its own '
                "speciesFeatureTypes; the feature owner is ambiguous across "
                "nested BNGL molecules.",
                "dropped",
            )
        )
    if children and any(
        instance.type_id in types and types[instance.type_id].is_binding_site
        for instance in species_type.instances
    ):
        warnings.append(
            _warning(
                f'Multi composite speciesType "{type_id}" contains direct '
                "binding-site instances; SBML Multi does not identify a unique "
                "BNGL molecule owner for those sites.",
                "dropped",
            )
        )
    if not children:
        molecule = _FlatMolecule(
            name=_clean_pattern_name(species_type.name, species_type.id),
            aliases={species_type.id, species_type.name, _clean(species_type.name)},
            compartment=effective_compartment,
        )
        for feature_id, feature_name, values, occurrence in _feature_defs(species_type):
            aliases = {feature_id, feature_name, _clean(feature_name)}
            if occurrence > 1:
                aliases.update(
                    {
                        f"{feature_id}_{occurrence}",
                        f"{_clean(feature_name)}_{occurrence}",
                    }
                )
            molecule.components.append(
                _FlatComponent(
                    label=_clean(feature_name),
                    aliases=aliases,
                    states=[_clean(value) for value in values],
                    feature_ids={feature_id},
                    feature_occurrence=occurrence,
                )
            )
        for instance in species_type.instances:
            target = types.get(instance.type_id)
            if target is None:
                warnings.append(
                    _warning(
                        f'SBML Multi speciesTypeInstance "{instance.id}" '
                        f'references undefined speciesType "{instance.type_id}".',
                        "dropped",
                    )
                )
                continue
            if not target.is_binding_site:
                continue
            if instance.compartment_reference:
                resolved = (
                    (compartment_references or {})
                    .get(effective_compartment, {})
                    .get(instance.compartment_reference, "")
                )
                if not resolved:
                    warnings.append(
                        _warning(
                            f'Multi speciesTypeInstance "{instance.id}" references '
                            f'unknown compartmentReference "{instance.compartment_reference}".',
                            "dropped",
                        )
                    )
                elif effective_compartment and resolved != effective_compartment:
                    warnings.append(
                        _warning(
                            "A binding-site component resolves to a different "
                            "compartment than its containing BNGL molecule; this "
                            "Multi structure is not executable.",
                            "dropped",
                        )
                    )
            instance_label = (
                instance.name
                if instance.name and instance.name != instance.id
                else target.name or target.id
            )
            label = _clean_pattern_name(instance_label, instance.id or target.id)
            aliases = {
                instance.id,
                instance.type_id,
                target.id,
                target.name,
                _clean(target.name),
                instance.name,
                _clean(instance.name),
            }
            states: List[str] = []
            feature_ids = set()
            for feature_id, feature_name, values, occurrence in _feature_defs(target):
                aliases.update({feature_id, feature_name, _clean(feature_name)})
                if occurrence > 1:
                    aliases.update(
                        {
                            f"{feature_id}_{occurrence}",
                            f"{_clean(feature_name)}_{occurrence}",
                        }
                    )
                feature_ids.add(feature_id)
                states.extend(_clean(value) for value in values)
            molecule.components.append(
                _FlatComponent(
                    label=label,
                    aliases={alias for alias in aliases if alias},
                    states=list(dict.fromkeys(states)),
                    feature_ids=feature_ids,
                    is_binding_site=True,
                )
            )
        flat.molecules.append(molecule)
        _apply_component_indexes(species_type, flat)
        for site1, site2 in species_type.bonds:
            endpoint1 = _resolve_bond_endpoint(species_type, flat, site1)
            endpoint2 = _resolve_bond_endpoint(species_type, flat, site2)
            if endpoint1 is None or endpoint2 is None:
                warnings.append(
                    _warning(
                        f'Multi bond in speciesType "{type_id}" could not resolve '
                        f'its endpoints "{site1}" and "{site2}".',
                        "dropped",
                    )
                )
                continue
            if not endpoint1[1].is_binding_site or not endpoint2[1].is_binding_site:
                warnings.append(
                    _warning(
                        f'Multi bond in speciesType "{type_id}" must connect two '
                        "binding-site components.",
                        "dropped",
                    )
                )
                continue
            flat.bonds.append((endpoint1[1], endpoint2[1]))
        return flat

    for instance in children:
        instance_compartment = ""
        if instance.compartment_reference:
            instance_compartment = (
                (compartment_references or {})
                .get(effective_compartment, {})
                .get(instance.compartment_reference, "")
            )
            if not instance_compartment:
                warnings.append(
                    _warning(
                        f'Multi speciesTypeInstance "{instance.id}" references '
                        f'unknown compartmentReference "{instance.compartment_reference}".',
                        "dropped",
                    )
                )
        child_type = types.get(instance.type_id)
        child_compartment = child_type.compartment if child_type is not None else ""
        target_compartment = (
            instance_compartment or child_compartment or effective_compartment
        )
        child = _flatten_type(
            instance.type_id,
            types,
            warnings,
            stack + (type_id,),
            compartment_references,
            target_compartment,
        )
        for molecule in child.molecules:
            molecule.aliases.update(
                {
                    instance.id,
                    instance.name,
                    _clean(instance.name),
                    instance.type_id,
                }
            )
        flat.molecules.extend(child.molecules)
        flat.bonds.extend(child.bonds)

    _apply_component_indexes(species_type, flat)
    for site1, site2 in species_type.bonds:
        endpoint1 = _resolve_bond_endpoint(species_type, flat, site1)
        endpoint2 = _resolve_bond_endpoint(species_type, flat, site2)
        if endpoint1 is None or endpoint2 is None:
            warnings.append(
                _warning(
                    f'Multi bond in speciesType "{type_id}" could not resolve '
                    f'its endpoints "{site1}" and "{site2}".',
                    "dropped",
                )
            )
            continue
        if not endpoint1[1].is_binding_site or not endpoint2[1].is_binding_site:
            warnings.append(
                _warning(
                    f'Multi bond in speciesType "{type_id}" must connect two '
                    "binding-site components.",
                    "dropped",
                )
            )
            continue
        flat.bonds.append((endpoint1[1], endpoint2[1]))
    return flat


def _render_flat_type(flat: _FlatType, show_states: bool = True) -> str:
    for component in [
        component for molecule in flat.molecules for component in molecule.components
    ]:
        component.bonds = []
    for bond_number, (left, right) in enumerate(flat.bonds, 1):
        left.bonds.append(bond_number)
        right.bonds.append(bond_number)

    rendered_molecules: List[str] = []
    for molecule in flat.molecules:
        components: List[str] = []
        for component in molecule.components:
            rendered = component.label
            if component.active_state:
                rendered += f"~{component.active_state}"
            elif show_states and component.states:
                rendered += "~" + "~".join(component.states)
            if component.bonds:
                rendered += "".join(f"!{bond}" for bond in component.bonds)
            elif component.binding_status == "bound":
                rendered += "!+"
            elif component.binding_status == "either":
                rendered += "!?"
            elif component.binding_status == "unbound":
                # A concrete unbound species is represented by the absence of
                # a bond; reaction-pattern code may add !0 separately.
                pass
            components.append(rendered)
        rendered = f"{molecule.name}({','.join(components)})"
        if molecule.compartment:
            rendered += f"@{_clean(molecule.compartment)}"
        rendered_molecules.append(rendered)
    return ".".join(rendered_molecules)


def _source_pattern_is_usable(source: str, flat: _FlatType) -> bool:
    if not source or not flat.molecules:
        return False
    try:
        parsed = read_from_string(source)
    except TypeError:
        return False
    except ValueError:
        return False
    if len(parsed.molecules) != len(flat.molecules):
        return False
    return all(
        parsed_molecule.name == flat_molecule.name
        and (
            not flat_molecule.compartment
            or parsed_molecule.compartment == _clean(flat_molecule.compartment)
        )
        for parsed_molecule, flat_molecule in zip(parsed.molecules, flat.molecules)
    )


def _species_pattern_from_multi(
    species: Any,
    type_id: str,
    types: Dict[str, _SpeciesType],
    namespace: str,
    warnings: List[SBMLImportWarning],
    compartment_references: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[str]:
    flat = _flatten_type(
        type_id,
        types,
        warnings,
        compartment_references=compartment_references,
    )
    if not flat.molecules:
        return None
    source = str(_attribute(species, "name", "") or "").strip()
    source_is_usable = _source_pattern_is_usable(source, flat)

    feature_entries: List[Tuple[Any, str]] = []
    feature_parent = _first_child(species, "listOfSpeciesFeatures", namespace)
    for child in list(feature_parent) if feature_parent is not None else []:
        if (
            _local_name(child.tag) == "speciesFeature"
            and _namespace(child.tag) == namespace
        ):
            feature_entries.append((child, ""))
        elif (
            _local_name(child.tag) == "subListOfSpeciesFeatures"
            and _namespace(child.tag) == namespace
        ):
            relation = _attribute(child, "relation", "").lower()
            if relation == "and":
                inherited_component = _attribute(child, "component")
                for nested in _children(child, "speciesFeature", namespace):
                    feature_entries.append((nested, inherited_component))
            else:
                warnings.append(
                    _warning(
                        f'SBML subListOfSpeciesFeatures relation "{relation}" '
                        "cannot be represented by one BNGL pattern.",
                        "dropped",
                    )
                )

    for feature, inherited_component in feature_entries:
        feature_id = _attribute(feature, "speciesFeatureType")
        component_token = _attribute(feature, "component") or inherited_component
        raw_occur = _attribute(feature, "occur")
        try:
            occur = int(raw_occur)
        except ValueError:
            occur = 0
        if not raw_occur or occur <= 0:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" has an invalid occur; '
                    "the species pattern was not reconstructed.",
                    "dropped",
                )
            )
            continue
        values_parent = _first_child(feature, "listOfSpeciesFeatureValues", namespace)
        raw_values = [
            _attribute(value, "value")
            for value in _children(values_parent, "speciesFeatureValue", namespace)
        ]
        values = []
        for raw_value in raw_values:
            definition = None
            for species_type in types.values():
                if feature_id in species_type.feature_definitions:
                    definition = species_type
                    break
            values.append(
                _feature_value(definition, feature_id, raw_value)
                if definition
                else _clean(raw_value)
            )
        targets: List[_FlatComponent] = []
        for molecule in flat.molecules:
            for component in molecule.components:
                if component_token and component_token in component.aliases:
                    targets.append(component)
                elif component_token and component_token in molecule.aliases:
                    if feature_id in component.feature_ids:
                        targets.append(component)
                elif not component_token and (
                    feature_id in component.feature_ids
                    or feature_id in component.aliases
                ):
                    targets.append(component)
        if not values:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" has no required '
                    "speciesFeatureValue children.",
                    "dropped",
                )
            )
            continue

        occurrence_targets = [
            target for target in targets if target.feature_occurrence == occur
        ]
        if len(occurrence_targets) != 1:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" occurrence {occur} on '
                    f'species "{_attribute(species, "id")}" is '
                    + (
                        "ambiguous or unresolved."
                        if occurrence_targets
                        else "not resolvable."
                    ),
                    "dropped",
                )
            )
            continue
        if len(values) == 1:
            occurrence_targets[0].active_state = values[0]
        elif len(values) > 1:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" has multiple values; '
                    "a single BNGL state cannot represent this value set.",
                    "dropped",
                )
            )

    seen_outward_components = set()
    for outward in _children(
        _first_child(species, "listOfOutwardBindingSites", namespace),
        "outwardBindingSite",
        namespace,
    ):
        component_token = _attribute(outward, "component")
        raw_status = _attribute(outward, "bindingStatus")
        status = raw_status.lower()
        if not component_token or not raw_status:
            warnings.append(
                _warning(
                    f'Multi outwardBindingSite on species "{_attribute(species, "id")}" '
                    "requires component and bindingStatus attributes.",
                    "dropped",
                )
            )
            continue
        if component_token in seen_outward_components:
            warnings.append(
                _warning(
                    f'Multi outwardBindingSite component "{component_token}" is '
                    "listed more than once on a species.",
                    "dropped",
                )
            )
            continue
        seen_outward_components.add(component_token)
        if status not in {"unbound", "bound", "either"}:
            warnings.append(
                _warning(
                    f'Unsupported Multi bindingStatus "{status}" on species '
                    f'"{_attribute(species, "id")}".',
                    "dropped",
                )
            )
            continue
        targets = [
            component
            for molecule in flat.molecules
            for component in molecule.components
            if component_token in component.aliases
        ]
        if len(targets) != 1:
            warnings.append(
                _warning(
                    f'Multi outwardBindingSite component "{component_token}" on '
                    f'species "{_attribute(species, "id")}" is '
                    + ("ambiguous." if targets else "not resolvable."),
                    "dropped",
                )
            )
            continue
        if not targets[0].is_binding_site:
            warnings.append(
                _warning(
                    f'Multi outwardBindingSite component "{component_token}" '
                    "does not identify a binding-site component.",
                    "dropped",
                )
            )
            continue
        if any(targets[0] is endpoint for bond in flat.bonds for endpoint in bond):
            warnings.append(
                _warning(
                    f'Multi outwardBindingSite component "{component_token}" is '
                    "already used by an inSpeciesTypeBond.",
                    "dropped",
                )
            )
            continue
        targets[0].binding_status = status
    if source_is_usable:
        return source
    return _render_flat_type(flat, show_states=False)


_MULTI_ELEMENTS = {
    "listOfCompartmentReferences",
    "compartmentReference",
    "listOfSpeciesTypes",
    "speciesType",
    "bindingSiteSpeciesType",
    "listOfSpeciesTypeInstances",
    "speciesTypeInstance",
    "listOfSpeciesTypeComponentIndexes",
    "speciesTypeComponentIndex",
    "listOfInSpeciesTypeBonds",
    "inSpeciesTypeBond",
    "listOfSpeciesFeatureTypes",
    "speciesFeatureType",
    "listOfPossibleSpeciesFeatureValues",
    "possibleSpeciesFeatureValue",
    "listOfSpeciesFeatures",
    "speciesFeature",
    "listOfSpeciesFeatureValues",
    "speciesFeatureValue",
    "listOfOutwardBindingSites",
    "outwardBindingSite",
    "subListOfSpeciesFeatures",
    "intraSpeciesReaction",
    "listOfSpeciesTypeComponentMapsInProduct",
    "speciesTypeComponentMapInProduct",
}

_MULTI_ELEMENT_ATTRIBUTES = {
    "bindingSiteSpeciesType": {"id", "name", "compartment"},
    "speciesType": {"id", "name", "compartment"},
    "speciesTypeInstance": {"id", "name", "speciesType", "compartmentReference"},
    "speciesTypeComponentIndex": {
        "id",
        "name",
        "component",
        "identifyingParent",
    },
    "inSpeciesTypeBond": {"id", "name", "bindingSite1", "bindingSite2"},
    "speciesFeatureType": {"id", "name", "occur"},
    "possibleSpeciesFeatureValue": {"id", "name", "numericValue"},
    "speciesFeature": {
        "id",
        "name",
        "speciesFeatureType",
        "occur",
        "component",
    },
    "speciesFeatureValue": {"value"},
    "outwardBindingSite": {"id", "name", "component", "bindingStatus"},
    "compartmentReference": {"id", "name", "compartment"},
    "subListOfSpeciesFeatures": {"id", "name", "relation", "component"},
    "speciesTypeComponentMapInProduct": {
        "id",
        "name",
        "reactant",
        "reactantComponent",
        "productComponent",
    },
    "ci": {"representationType", "speciesReference"},
}

_MULTI_LIST_CHILDREN = {
    "listOfCompartmentReferences": {"compartmentReference"},
    "listOfSpeciesTypes": {"speciesType", "bindingSiteSpeciesType"},
    "listOfSpeciesTypeInstances": {"speciesTypeInstance"},
    "listOfSpeciesTypeComponentIndexes": {"speciesTypeComponentIndex"},
    "listOfInSpeciesTypeBonds": {"inSpeciesTypeBond"},
    "listOfSpeciesFeatureTypes": {"speciesFeatureType"},
    "listOfPossibleSpeciesFeatureValues": {"possibleSpeciesFeatureValue"},
    "listOfSpeciesFeatures": {"speciesFeature", "subListOfSpeciesFeatures"},
    "subListOfSpeciesFeatures": {"speciesFeature"},
    "listOfSpeciesFeatureValues": {"speciesFeatureValue"},
    "listOfOutwardBindingSites": {"outwardBindingSite"},
    "listOfSpeciesTypeComponentMapsInProduct": {"speciesTypeComponentMapInProduct"},
}

_MULTI_CORE_ATTRIBUTES = {"metaid", "sboTerm"}
_INTRA_REACTION_CORE_ATTRIBUTES = {
    "id",
    "name",
    "reversible",
    "fast",
    "compartment",
    "metaid",
    "sboTerm",
}
_CORE_MULTI_ATTRIBUTES = {
    "sbml": {"required"},
    "species": {"speciesType"},
    "compartment": {"compartmentType", "isType"},
    "speciesReference": {"compartmentReference"},
    "modifierSpeciesReference": {"compartmentReference"},
    "ci": {"representationType", "speciesReference"},
}

_MULTI_REQUIRED_ATTRIBUTES = {
    "compartmentReference": {"compartment"},
    "speciesType": {"id"},
    "bindingSiteSpeciesType": {"id"},
    "speciesTypeInstance": {"id", "speciesType"},
    "speciesTypeComponentIndex": {"id", "component"},
    "inSpeciesTypeBond": {"bindingSite1", "bindingSite2"},
    "speciesFeatureType": {"id", "occur"},
    "possibleSpeciesFeatureValue": {"id"},
    "speciesFeature": {"speciesFeatureType", "occur"},
    "speciesFeatureValue": {"value"},
    "outwardBindingSite": {"component", "bindingStatus"},
    "subListOfSpeciesFeatures": {"relation"},
    "intraSpeciesReaction": {"id"},
    "speciesTypeComponentMapInProduct": {
        "reactant",
        "reactantComponent",
        "productComponent",
    },
}

_MULTI_CONTAINER_NAMES = {
    "listOfCompartmentReferences",
    "listOfSpeciesTypes",
    "listOfSpeciesTypeInstances",
    "listOfSpeciesTypeComponentIndexes",
    "listOfInSpeciesTypeBonds",
    "listOfSpeciesFeatureTypes",
    "listOfPossibleSpeciesFeatureValues",
    "listOfSpeciesFeatures",
    "listOfSpeciesFeatureValues",
    "listOfOutwardBindingSites",
    "listOfSpeciesTypeComponentMapsInProduct",
}

_MULTI_ALLOWED_PARENTS = {
    "listOfCompartmentReferences": {"compartment"},
    "compartmentReference": {"listOfCompartmentReferences"},
    "listOfSpeciesTypes": {"model"},
    "speciesType": {"listOfSpeciesTypes"},
    "bindingSiteSpeciesType": {"listOfSpeciesTypes"},
    "listOfSpeciesTypeInstances": {"speciesType", "bindingSiteSpeciesType"},
    "speciesTypeInstance": {"listOfSpeciesTypeInstances"},
    "listOfSpeciesTypeComponentIndexes": {"speciesType", "bindingSiteSpeciesType"},
    "speciesTypeComponentIndex": {"listOfSpeciesTypeComponentIndexes"},
    "listOfInSpeciesTypeBonds": {"speciesType", "bindingSiteSpeciesType"},
    "inSpeciesTypeBond": {"listOfInSpeciesTypeBonds"},
    "listOfSpeciesFeatureTypes": {"speciesType", "bindingSiteSpeciesType"},
    "speciesFeatureType": {"listOfSpeciesFeatureTypes"},
    "listOfPossibleSpeciesFeatureValues": {"speciesFeatureType"},
    "possibleSpeciesFeatureValue": {"listOfPossibleSpeciesFeatureValues"},
    "listOfSpeciesFeatures": {"species"},
    "speciesFeature": {"listOfSpeciesFeatures", "subListOfSpeciesFeatures"},
    "subListOfSpeciesFeatures": {"listOfSpeciesFeatures"},
    "listOfSpeciesFeatureValues": {"speciesFeature"},
    "speciesFeatureValue": {"listOfSpeciesFeatureValues"},
    "listOfOutwardBindingSites": {"species"},
    "outwardBindingSite": {"listOfOutwardBindingSites"},
    "intraSpeciesReaction": {"listOfReactions"},
    "listOfSpeciesTypeComponentMapsInProduct": {"speciesReference"},
    "speciesTypeComponentMapInProduct": {
        "listOfSpeciesTypeComponentMapsInProduct"
    },
}


def _validate_multi_markup(
    root: Any, namespace: str, warnings: List[SBMLImportWarning]
) -> bool:
    """Check Multi namespace placement and the package element vocabulary."""

    invalid = False
    parents = {
        id(child): parent
        for parent in root.iter()
        for child in list(parent)
    }
    for element in root.iter():
        local = _local_name(element.tag)
        element_namespace = _namespace(element.tag)
        if "/multi/" in element_namespace and element_namespace != namespace:
            invalid = True
            warnings.append(
                _warning(
                    f'Unsupported SBML Multi element namespace "{element_namespace}".',
                    "dropped",
                )
            )
            continue
        if element_namespace == namespace:
            if local not in _MULTI_ELEMENTS:
                invalid = True
                warnings.append(
                    _warning(
                        f'Unsupported SBML Multi element "{local}"; its semantics '
                        "are not reconstructed.",
                        "dropped",
                    )
                )
            parent = parents.get(id(element))
            parent_local = _local_name(parent.tag) if parent is not None else ""
            allowed_parents = _MULTI_ALLOWED_PARENTS.get(local)
            if allowed_parents is not None and parent_local not in allowed_parents:
                invalid = True
                warnings.append(
                    _warning(
                        f'SBML Multi element "{local}" is not allowed inside '
                        f'core or Multi parent "{parent_local or "<root>"}".',
                        "dropped",
                    )
                )
            elif allowed_parents and parent is not None:
                parent_namespace = _namespace(parent.tag)
                core_parent_names = {
                    "model",
                    "compartment",
                    "species",
                    "listOfReactions",
                    "speciesReference",
                }
                expected_parent_namespace = (
                    CORE_V1_NAMESPACE
                    if parent_local in core_parent_names
                    else namespace
                )
                if parent_namespace != expected_parent_namespace:
                    invalid = True
                    warnings.append(
                        _warning(
                            f'SBML Multi element "{local}" has parent '
                            f'"{parent_local}" in namespace "{parent_namespace}"; '
                            f'expected "{expected_parent_namespace}".',
                            "dropped",
                        )
                    )
            allowed = set(_MULTI_ELEMENT_ATTRIBUTES.get(local, set()))
            if local == "intraSpeciesReaction":
                allowed.clear()
            for required_attribute in _MULTI_REQUIRED_ATTRIBUTES.get(local, set()):
                if not _attribute(element, required_attribute):
                    invalid = True
                    warnings.append(
                        _warning(
                            f'Multi {local} is missing required attribute '
                            f'"{required_attribute}".',
                            "dropped",
                        )
                    )
            for key in getattr(element, "attrib", {}):
                key_namespace = _namespace(key)
                key_local = _local_name(key)
                if key_namespace == namespace:
                    if key_local not in allowed:
                        invalid = True
                        warnings.append(
                            _warning(
                                f'Unexpected Multi attribute "{key_local}" on '
                                f"{local}.",
                                "dropped",
                            )
                        )
                elif key_namespace == CORE_V1_NAMESPACE:
                    if key_local not in _MULTI_CORE_ATTRIBUTES:
                        invalid = True
                        warnings.append(
                            _warning(
                                f'Unexpected core attribute "{key_local}" on '
                                f"Multi {local}.",
                                "dropped",
                            )
                        )
                elif key_namespace == "":
                    unqualified_allowed = (
                        _INTRA_REACTION_CORE_ATTRIBUTES
                        if local == "intraSpeciesReaction"
                        else set(_CORE_MULTI_ATTRIBUTES.get(local, set()))
                        | set(allowed)
                    )
                    if key_local not in unqualified_allowed:
                        invalid = True
                        warnings.append(
                            _warning(
                                f'Multi attribute "{key_local}" on {local} must '
                                "use the Multi namespace.",
                                "dropped",
                            )
                        )
                else:
                    invalid = True
                    warnings.append(
                        _warning(
                            f'Attribute "{key_local}" on Multi element {local} '
                            "uses an unsupported namespace.",
                            "dropped",
                        )
                    )
            allowed_children = _MULTI_LIST_CHILDREN.get(local)
            if allowed_children is not None:
                package_children = [
                    child
                    for child in list(element)
                    if _namespace(child.tag) == namespace
                ]
                if not package_children:
                    invalid = True
                    warnings.append(
                        _warning(
                            f"SBML Multi {local} must contain at least one "
                            "package child.",
                            "dropped",
                        )
                    )
                for child in package_children:
                    child_local = _local_name(child.tag)
                    if child_local not in allowed_children:
                        invalid = True
                        warnings.append(
                            _warning(
                                f"SBML Multi {local} contains unsupported child "
                                f'"{child_local}".',
                                "dropped",
                            )
                        )
            continue
        expected = _CORE_MULTI_ATTRIBUTES.get(local, set())
        for key in getattr(element, "attrib", {}):
            if _namespace(key) == namespace:
                if _local_name(key) not in expected:
                    invalid = True
                    warnings.append(
                        _warning(
                            f'Unexpected Multi attribute "{_local_name(key)}" on '
                            f"core {local}.",
                            "dropped",
                        )
                    )
            elif _namespace(key) == "" and (
                _local_name(key) in expected
                or _local_name(key)
                in {
                    "speciesType",
                    "compartmentType",
                    "isType",
                    "compartmentReference",
                }
            ):
                invalid = True
                warnings.append(
                    _warning(
                        f'Multi attribute "{_local_name(key)}" on core {local} '
                        "must use the Multi namespace.",
                        "dropped",
                    )
                )
        for child in list(element):
            child_namespace = _namespace(child.tag)
            child_local = _local_name(child.tag)
            if child_namespace in {
                "",
                namespace,
                CORE_V1_NAMESPACE,
                MATHML_NAMESPACE,
            }:
                continue
            if child_namespace:
                invalid = True
                warnings.append(
                    _warning(
                        f'Unexpected child "{child_local}" on core {local}.',
                        "dropped",
                    )
                )
    return invalid


def _parse_multi_package_complete(document: Union[str, Any]) -> MultiParseResult:
    """Parse SBML Multi v1 and retain executable BNGL reconstruction metadata."""

    source = document if isinstance(document, str) else None
    try:
        root = _as_root(document)
    except (ET.ParseError, TypeError, ValueError) as error:
        return MultiParseResult(
            warnings=[
                _warning(
                    f"SBML Multi document could not be parsed as XML: {error}.",
                    "dropped",
                )
            ]
        )
    if root is None:
        return MultiParseResult()
    namespace = _multi_namespace(root, source)
    if namespace is None:
        return MultiParseResult()

    warnings: List[SBMLImportWarning] = []
    model = _model_element(root)
    if model is None:
        return MultiParseResult(
            present=True,
            warnings=[_warning("SBML document has no core model element.", "dropped")],
        )
    required = _namespaced_attribute(root, namespace, "required")
    required_is_true = required in {"true", "1"}
    required_is_false = required in {"false", "0"}
    package_valid = namespace == MULTI_V1_NAMESPACE and required_is_true
    if namespace != MULTI_V1_NAMESPACE:
        warnings.append(
            _warning(
                f'Unsupported SBML Multi namespace "{namespace}"; expected '
                f'"{MULTI_V1_NAMESPACE}".',
                "dropped",
            )
        )
    if required == "":
        warnings.append(
            _warning(
                "SBML Multi is present without the required multi:required "
                "attribute; executable reconstruction is disabled.",
                "dropped",
            )
        )
    elif required_is_true:
        pass
    elif not required_is_false:
        warnings.append(
            _warning(
                f'SBML Multi has invalid boolean multi:required="{required}"; '
                "executable reconstruction is disabled.",
                "dropped",
            )
        )
    else:
        warnings.append(
            _warning(
                'SBML Multi has multi:required="false"; executable reconstruction '
                "is disabled for a package the core model may ignore.",
                "dropped",
            )
        )

    namespace_violation = _validate_multi_markup(root, namespace, warnings)
    for parent in root.iter():
        for container_name in _MULTI_CONTAINER_NAMES:
            containers = _children(parent, container_name, namespace)
            if len(containers) > 1:
                warnings.append(
                    _warning(
                        f'SBML Multi object {_local_name(parent.tag)} contains '
                        f'multiple {container_name} containers; the package '
                        "allows at most one.",
                        "dropped",
                    )
                )
    for sublist in root.iter():
        if _local_name(sublist.tag) != "subListOfSpeciesFeatures":
            continue
        relation = _attribute(sublist, "relation", "").lower()
        children = _children(sublist, "speciesFeature", namespace)
        if relation not in {"and", "or", "not"}:
            warnings.append(
                _warning(
                    'SBML subListOfSpeciesFeatures requires relation="and", '
                    'relation="or", or relation="not".',
                    "dropped",
                )
            )
        if len(children) < 2:
            warnings.append(
                _warning(
                    "SBML subListOfSpeciesFeatures must contain at least two "
                    "speciesFeature children.",
                    "dropped",
                )
            )
        if relation in {"or", "not"}:
            warnings.append(
                _warning(
                    f"SBML subListOfSpeciesFeatures relation={relation} requires multiple "
                    "alternative species patterns and is not representable by the "
                    "single-pattern atomizer contract.",
                    "dropped",
                )
            )

    list_types = _first_child(model, "listOfSpeciesTypes", namespace)
    if list_types is None:
        has_multi_model_use = any(
            _namespace(element.tag) == namespace
            and _local_name(element.tag) != "listOfSpeciesTypes"
            for element in root.iter()
        ) or any(
            _namespace(attribute) == namespace
            and not (
                element is root and _local_name(attribute) == "required"
            )
            for element in root.iter()
            for attribute in getattr(element, "attrib", {})
        )
        return MultiParseResult(
            present=True,
            warnings=[
                _warning(
                    "SBML Multi package has no listOfSpeciesTypes; no typed "
                    "Multi structures were reconstructed.",
                    "info" if package_valid and not has_multi_model_use else "dropped",
                ),
                _warning(
                    "SBML Multi package has no referenced top-level species type.",
                    "info",
                ),
            ]
            + warnings,
            executable=package_valid and not has_multi_model_use and not namespace_violation,
        )

    types: Dict[str, _SpeciesType] = {}
    possible_value_owner: Dict[str, Tuple[str, str]] = {}
    core_model_ids = {
        _attribute(element, "id")
        for element in model.iter()
        if _namespace(element.tag) in {"", CORE_V1_NAMESPACE}
        and _attribute(element, "id")
    }
    raw_type_elements = [
        *(_children(list_types, "bindingSiteSpeciesType", namespace)),
        *(_children(list_types, "speciesType", namespace)),
    ]
    for item in raw_type_elements:
        type_id = _attribute(item, "id")
        if not type_id:
            warnings.append(
                _warning(
                    f"Multi {_local_name(item.tag)} has no required multi:id.",
                    "dropped",
                )
            )
            continue
        if type_id in types:
            warnings.append(
                _warning(f'Duplicate Multi speciesType id "{type_id}".', "dropped")
            )
            continue
        if type_id in core_model_ids:
            warnings.append(
                _warning(
                    f'Multi speciesType id "{type_id}" collides with a core '
                    "Model identifier.",
                    "dropped",
                )
            )
        is_binding_site = _local_name(item.tag) == "bindingSiteSpeciesType"
        species_type = _SpeciesType(
            id=type_id,
            name=_clean(_attribute(item, "name") or type_id),
            is_binding_site=is_binding_site,
            compartment=_attribute(item, "compartment"),
        )
        feature_list = _first_child(item, "listOfSpeciesFeatureTypes", namespace)
        for feature in _children(feature_list, "speciesFeatureType", namespace):
            feature_id = _attribute(feature, "id")
            if not feature_id:
                warnings.append(
                    _warning(
                        f'Multi speciesFeatureType on "{type_id}" has no id.',
                        "dropped",
                    )
                )
                continue
            if feature_id in species_type.feature_definitions:
                warnings.append(
                    _warning(
                        f'Duplicate Multi speciesFeatureType id "{feature_id}" '
                        f'in speciesType "{type_id}".',
                        "dropped",
                    )
                )
                continue
            value_labels: Dict[str, str] = {}
            possible = _first_child(
                feature, "listOfPossibleSpeciesFeatureValues", namespace
            )
            for value in _children(possible, "possibleSpeciesFeatureValue", namespace):
                value_id = _attribute(value, "id")
                if not value_id:
                    warnings.append(
                        _warning(
                            f'Multi speciesFeatureType "{feature_id}" contains a '
                            "possibleSpeciesFeatureValue without id.",
                            "dropped",
                        )
                    )
                    continue
                owner = (type_id, feature_id)
                if value_id in possible_value_owner:
                    warnings.append(
                        _warning(
                            f"Duplicate Multi possibleSpeciesFeatureValue id "
                            f'"{value_id}" in {owner} and '
                            f"{possible_value_owner[value_id]}.",
                            "dropped",
                        )
                    )
                    continue
                if value_id in types:
                    warnings.append(
                        _warning(
                            f'Multi possibleSpeciesFeatureValue id "{value_id}" '
                            "collides with a speciesType identifier.",
                            "dropped",
                        )
                    )
                    continue
                if value_id in core_model_ids:
                    warnings.append(
                        _warning(
                            f'Multi possibleSpeciesFeatureValue id "{value_id}" '
                            "collides with a core Model identifier.",
                            "dropped",
                        )
                    )
                possible_value_owner[value_id] = owner
                value_labels[value_id] = _clean(_attribute(value, "name") or value_id)
                numeric_value = _attribute(value, "numericValue")
                if numeric_value:
                    species_type.feature_numeric_values[value_id] = numeric_value
            feature_name = _clean(_attribute(feature, "name") or feature_id)
            species_type.features.append((feature_name, list(value_labels.values())))
            species_type.feature_definitions[feature_id] = (
                feature_name,
                value_labels,
            )
            try:
                occur = int(_attribute(feature, "occur", ""))
            except ValueError:
                occur = 0
            if occur <= 0:
                warnings.append(
                    _warning(
                        f'Multi speciesFeatureType "{feature_id}" has an invalid '
                        "positive occur attribute.",
                        "dropped",
                    )
                )
                occur = 1
            species_type.feature_occurs[feature_id] = occur
            if not value_labels:
                warnings.append(
                    _warning(
                        f'Multi speciesFeatureType "{feature_id}" has no possible '
                        "species feature values.",
                        "dropped",
                    )
                )

        instance_list = _first_child(item, "listOfSpeciesTypeInstances", namespace)
        if is_binding_site and instance_list is not None:
            warnings.append(
                _warning(
                    f'Multi bindingSiteSpeciesType "{type_id}" must be atomic '
                    "and cannot contain speciesTypeInstance children.",
                    "dropped",
                )
            )
        instance_ids = set()
        for instance in _children(instance_list, "speciesTypeInstance", namespace):
            instance_id = _attribute(instance, "id")
            instance_type = _attribute(instance, "speciesType")
            if not instance_id or not instance_type:
                warnings.append(
                    _warning(
                        f'Multi speciesType "{type_id}" contains an incomplete '
                        "speciesTypeInstance.",
                        "dropped",
                    )
                )
                continue
            if instance_id in instance_ids:
                warnings.append(
                    _warning(
                        f'Duplicate Multi speciesTypeInstance id "{instance_id}" '
                        f'in speciesType "{type_id}".',
                        "dropped",
                    )
                )
                continue
            instance_ids.add(instance_id)
            species_type.instances.append(
                _Instance(
                    id=instance_id,
                    type_id=instance_type,
                    name=_clean(_attribute(instance, "name") or instance_id),
                    compartment_reference=_attribute(instance, "compartmentReference"),
                )
            )

        index_list = _first_child(item, "listOfSpeciesTypeComponentIndexes", namespace)
        index_ids = set()
        for component in _children(index_list, "speciesTypeComponentIndex", namespace):
            component_id = _attribute(component, "id")
            component_ref = _attribute(component, "component")
            if component_id and component_ref:
                if component_id in index_ids:
                    warnings.append(
                        _warning(
                            f"Duplicate Multi speciesTypeComponentIndex id "
                            f'"{component_id}" in speciesType "{type_id}".',
                            "dropped",
                        )
                    )
                    continue
                index_ids.add(component_id)
                species_type.component_indexes[component_id] = (
                    component_ref,
                    _attribute(component, "identifyingParent"),
                )
            else:
                warnings.append(
                    _warning(
                        f'Multi speciesType "{type_id}" contains an incomplete '
                        "speciesTypeComponentIndex.",
                        "dropped",
                    )
                )

        bond_list = _first_child(item, "listOfInSpeciesTypeBonds", namespace)
        bond_pairs = set()
        for bond in _children(bond_list, "inSpeciesTypeBond", namespace):
            site1 = _attribute(bond, "bindingSite1")
            site2 = _attribute(bond, "bindingSite2")
            if site1 and site2:
                pair = tuple(sorted((site1, site2)))
                if site1 == site2 or pair in bond_pairs:
                    warnings.append(
                        _warning(
                            f'Multi speciesType "{type_id}" contains a duplicate '
                            "or self-referential inSpeciesTypeBond.",
                            "dropped",
                        )
                    )
                    continue
                bond_pairs.add(pair)
                species_type.bonds.append((site1, site2))
            else:
                warnings.append(
                    _warning(
                        f'Multi speciesType "{type_id}" contains an incomplete '
                        "inSpeciesTypeBond.",
                        "dropped",
                    )
                )
        types[type_id] = species_type

    for species_type in types.values():
        for instance in species_type.instances:
            if instance.type_id not in types:
                warnings.append(
                    _warning(
                        f'SBML Multi speciesTypeInstance "{instance.id}" in '
                        f'"{species_type.id}" references undefined speciesType '
                        f'"{instance.type_id}".',
                        "dropped",
                    )
                )
        component_ids = {
            instance.id for instance in species_type.instances
        } | set(species_type.component_indexes) | {species_type.id} | set(types)
        for index_id, (component, identifying_parent) in species_type.component_indexes.items():
            if component not in component_ids:
                warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'"{species_type.id}" references unknown component '
                        f'"{component}".',
                        "dropped",
                    )
                )
            if identifying_parent and identifying_parent not in component_ids:
                warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'"{species_type.id}" has unknown identifyingParent '
                        f'"{identifying_parent}".',
                        "dropped",
                    )
                )
        valid_bond_endpoints = {
            instance.id for instance in species_type.instances
        } | set(species_type.component_indexes)

        def binding_type_for(
            token: str, seen: Tuple[str, ...] = ()
        ) -> Optional[str]:
            if token in seen:
                return None
            component, _parent = species_type.component_indexes.get(token, (token, ""))
            instance = next(
                (candidate for candidate in species_type.instances if candidate.id == component),
                None,
            )
            if instance is not None:
                target = types.get(instance.type_id)
                return target.id if target is not None and target.is_binding_site else None
            if component in species_type.component_indexes:
                return binding_type_for(component, seen + (token,))
            target = types.get(component)
            if target is not None and target.is_binding_site:
                return target.id
            return None

        for site1, site2 in species_type.bonds:
            if site1 not in valid_bond_endpoints or site2 not in valid_bond_endpoints:
                warnings.append(
                    _warning(
                        f'Multi inSpeciesTypeBond in "{species_type.id}" must '
                        "reference a speciesTypeInstance or component index.",
                        "dropped",
                    )
                )
                continue
            binding_type1 = binding_type_for(site1)
            binding_type2 = binding_type_for(site2)
            if not binding_type1 or not binding_type2:
                warnings.append(
                    _warning(
                        f'Multi inSpeciesTypeBond in "{species_type.id}" must '
                        "resolve both endpoints to bindingSiteSpeciesType objects.",
                        "dropped",
                    )
                )
                continue
            if binding_type1 and binding_type1 == binding_type2:
                warnings.append(
                    _warning(
                        f'Multi inSpeciesTypeBond in "{species_type.id}" joins '
                        f'two binding sites of the same type "{binding_type1}".',
                        "dropped",
                    )
                )

    if not types:
        warnings.append(
            _warning(
                "SBML Multi listOfSpeciesTypes is empty; the package cannot define "
                "species types, features, or binding sites.",
                "dropped",
            )
        )
        warnings.append(
            _warning(
                "SBML Multi package has species types but no referenced top-level "
                "species type.",
                "info",
            )
        )

    compartment_references: Dict[str, Dict[str, str]] = {}
    compartment_reference_edges: Dict[str, set] = {}
    compartments = _first_child(model, "listOfCompartments")
    compartment_ids = set()
    for compartment in _children(compartments, "compartment"):
        compartment_id = _attribute(compartment, "id")
        if not compartment_id:
            warnings.append(
                _warning("SBML core compartment is missing its required id.", "dropped")
            )
            continue
        if compartment_id in compartment_ids:
            warnings.append(
                _warning(
                    f'Duplicate core compartment id "{compartment_id}".',
                    "dropped",
                )
            )
        compartment_ids.add(compartment_id)
    compartment_is_type = {}
    for compartment in _children(compartments, "compartment"):
        compartment_id = _attribute(compartment, "id")
        if compartment_id:
            raw_is_type = _namespaced_attribute(compartment, namespace, "isType")
            compartment_is_type[compartment_id] = (
                "true" if raw_is_type in {"true", "1"} else "false"
            )
    for compartment in _children(compartments, "compartment"):
        compartment_id = _attribute(compartment, "id")
        compartment_type = _namespaced_attribute(
            compartment, namespace, "compartmentType"
        )
        is_type = _namespaced_attribute(compartment, namespace, "isType")
        if is_type not in {"true", "false", "1", "0"}:
            warnings.append(
                _warning(
                    f'Compartment "{compartment_id or "<anonymous>"}" must have '
                    "a valid required multi:isType attribute.",
                    "dropped",
                )
            )
        normalized_is_type = "true" if is_type in {"true", "1"} else "false"
        if compartment_type and compartment_type not in compartment_ids:
            warnings.append(
                _warning(
                    f'Compartment "{compartment_id}" references undefined '
                    f'Multi compartmentType "{compartment_type}".',
                    "dropped",
                )
            )
        elif compartment_type and compartment_is_type.get(compartment_type) != "true":
            warnings.append(
                _warning(
                    f'Compartment "{compartment_id}" compartmentType '
                    f'"{compartment_type}" is not a compartment type.',
                    "dropped",
                )
            )
        if compartment_type and normalized_is_type != "false":
            warnings.append(
                _warning(
                    f'Compartment "{compartment_id}" uses multi:compartmentType '
                    'without multi:isType="false".',
                    "dropped",
                )
            )
        reference_list = _first_child(
            compartment, "listOfCompartmentReferences", namespace
        )
        if not compartment_id or reference_list is None:
            continue
        references: Dict[str, str] = {}
        reference_targets: List[Tuple[str, bool]] = []
        for reference in _children(reference_list, "compartmentReference", namespace):
            reference_id = _attribute(reference, "id")
            reference_compartment = _attribute(reference, "compartment")
            if not reference_compartment:
                warnings.append(
                    _warning(
                        f'Compartment "{compartment_id}" contains a '
                        "compartmentReference without multi:compartment.",
                        "dropped",
                    )
                )
                continue
            if reference_compartment not in compartment_ids:
                warnings.append(
                    _warning(
                        f'CompartmentReference "{reference_id or "<anonymous>"}" '
                        f'references undefined compartment "{reference_compartment}".',
                        "dropped",
                    )
                )
            elif (
                is_type in {"true", "false", "1", "0"}
                and compartment_is_type.get(reference_compartment) != normalized_is_type
            ):
                warnings.append(
                    _warning(
                        f'CompartmentReference "{reference_id or "<anonymous>"}" '
                        f'in compartment "{compartment_id}" has an isType value '
                        "inconsistent with its parent compartment.",
                        "dropped",
                    )
                )
            reference_targets.append((reference_compartment, bool(reference_id)))
            if reference_id:
                if reference_id in references:
                    warnings.append(
                        _warning(
                            f'Duplicate compartmentReference id "{reference_id}" '
                            f'in compartment "{compartment_id}".',
                            "dropped",
                        )
                    )
                references[reference_id] = reference_compartment
        if reference_targets:
            compartment_reference_edges[compartment_id] = {
                target for target, _has_id in reference_targets
            }
        target_counts: Dict[str, int] = {}
        for target, _has_id in reference_targets:
            target_counts[target] = target_counts.get(target, 0) + 1
        if any(
            count > 1
            and any(target == repeated_target and not has_id for target, has_id in reference_targets)
            for repeated_target, count in target_counts.items()
        ):
            warnings.append(
                _warning(
                    f'Compartment "{compartment_id}" has multiple '
                    "compartmentReferences to the same compartment; every such "
                    "reference must have an id.",
                    "dropped",
                )
            )
        if references:
            compartment_references[compartment_id] = references

    reference_graph = compartment_reference_edges
    visiting: set = set()
    visited: set = set()

    def visit_compartment(compartment_id: str) -> None:
        if compartment_id in visiting:
            warnings.append(
                _warning(
                    f'Compartment references contain a cycle at "{compartment_id}".',
                    "dropped",
                )
            )
            return
        if compartment_id in visited:
            return
        visiting.add(compartment_id)
        for target in reference_graph.get(compartment_id, set()):
            visit_compartment(target)
        visiting.remove(compartment_id)
        visited.add(compartment_id)

    for compartment_id in reference_graph:
        visit_compartment(compartment_id)

    for species_type in types.values():
        if species_type.compartment and species_type.compartment not in compartment_ids:
            warnings.append(
                _warning(
                    f'Multi speciesType "{species_type.id}" references undefined '
                    f'compartment "{species_type.compartment}".',
                    "dropped",
                )
            )
        if species_type.compartment:
            scoped_references = compartment_references.get(species_type.compartment, {})
            for instance in species_type.instances:
                if instance.compartment_reference and (
                    not species_type.compartment
                    or instance.compartment_reference not in scoped_references
                ):
                    warnings.append(
                        _warning(
                            f'SpeciesTypeInstance "{instance.id}" references '
                            f'unknown compartmentReference "{instance.compartment_reference}" '
                            f'in compartment "{species_type.compartment}".',
                            "dropped",
                        )
                    )
        else:
            for instance in species_type.instances:
                if instance.compartment_reference:
                    warnings.append(
                        _warning(
                            f'SpeciesTypeInstance "{instance.id}" in '
                            f'"{species_type.id}" uses compartmentReference '
                            "without a containing speciesType compartment.",
                            "dropped",
                        )
                    )

    parameter_ids = {
        _attribute(parameter, "id")
        for parameter in _children(_first_child(model, "listOfParameters"), "parameter")
        if _attribute(parameter, "id")
    }
    for species_type in types.values():
        for value_id, parameter_id in species_type.feature_numeric_values.items():
            if parameter_id not in parameter_ids:
                warnings.append(
                    _warning(
                        f'Multi possibleSpeciesFeatureValue "{value_id}" references '
                        f'undefined numericValue parameter "{parameter_id}".',
                        "dropped",
                    )
                )

    type_patterns: Dict[str, str] = {}
    component_aliases: Dict[str, Dict[str, List[Tuple[str, int, int]]]] = {}
    molecule_types: List[str] = []
    complex_patterns: List[MultiComplexPattern] = []
    structure_warnings: List[SBMLImportWarning] = []
    for type_id, species_type in types.items():
        if species_type.is_binding_site:
            continue
        flat = _flatten_type(
            type_id,
            types,
            structure_warnings,
            compartment_references=compartment_references,
        )
        if not flat.molecules:
            continue
        component_aliases[type_id] = _flat_component_aliases(flat)
        for index_id in species_type.component_indexes:
            if index_id not in component_aliases[type_id]:
                structure_warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'speciesType "{type_id}" could not resolve its component.',
                        "dropped",
                    )
                )
        rendered = _render_flat_type(flat, show_states=True)
        type_patterns[type_id] = rendered
        if _is_complex_type(type_id, types):
            complex_patterns.append(MultiComplexPattern(type_id, rendered))
        else:
            if rendered not in molecule_types:
                molecule_types.append(rendered)

    deep_hierarchy = any(
        any(
            instance.type_id in types and _is_complex_type(instance.type_id, types)
            for instance in species_type.instances
        )
        for species_type in types.values()
    )
    if deep_hierarchy and not package_valid:
        # Invalid/optional packages cannot be safely flattened: a core-only
        # consumer is allowed to ignore Multi, so avoid manufacturing a
        # different executable network from a structure whose package contract
        # was not asserted by the document.
        return MultiParseResult(
            present=True,
            deep=True,
            warnings=[
                _warning(
                    "SBML Multi package uses a multi-layer hierarchy; molecule "
                    "boundaries cannot be inferred safely, so complexes were not "
                    "reconstructed.",
                    "approximated",
                )
            ]
            + warnings,
        )

    species_patterns: Dict[str, str] = {}
    seed_patterns: List[Tuple[str, str]] = []
    species_type_by_species: Dict[str, str] = {}
    species_compartments: Dict[str, str] = {}
    species_feature_ids: set = set()
    species_parent = _first_child(model, "listOfSpecies")

    def visible_feature_types(
        type_id: str, stack: Tuple[str, ...] = ()
    ) -> Tuple[Dict[str, Tuple[int, set]], set]:
        if type_id in stack or type_id not in types:
            return {}, set()
        species_type = types[type_id]
        visible = {
            feature_id: (
                species_type.feature_occurs.get(feature_id, 1),
                set(labels),
            )
            for feature_id, (_name, labels) in species_type.feature_definitions.items()
        }
        ambiguous: set = set()
        for instance in species_type.instances:
            if (
                instance.type_id in types
                and not types[instance.type_id].is_binding_site
            ):
                nested, nested_ambiguous = visible_feature_types(
                    instance.type_id, stack + (type_id,)
                )
                ambiguous.update(nested_ambiguous)
                for feature_id, definition in nested.items():
                    if feature_id in visible and visible[feature_id] != definition:
                        ambiguous.add(feature_id)
                    else:
                        visible[feature_id] = definition
        return visible, ambiguous

    for species in _children(species_parent, "species"):
        species_id = _attribute(species, "id")
        species_compartment = _attribute(species, "compartment")
        if species_id:
            if species_id in species_compartments:
                warnings.append(
                    _warning(
                        f'Duplicate core species id "{species_id}".',
                        "dropped",
                    )
                )
            species_compartments[species_id] = species_compartment
        type_id = _namespaced_attribute(species, namespace, "speciesType")
        if not type_id:
            # Legacy fixtures are retained as parse-only compatibility, but are
            # never considered executable SBML Multi.
            type_id = _attribute(species, "speciesType")
        feature_list = _first_child(species, "listOfSpeciesFeatures", namespace)
        outward_list = _first_child(species, "listOfOutwardBindingSites", namespace)
        has_multi_species_children = (
            feature_list is not None or outward_list is not None
        )
        if not species_id:
            warnings.append(
                _warning(
                    "SBML Multi species is missing its required core id.", "dropped"
                )
            )
            continue
        if has_multi_species_children and not type_id:
            warnings.append(
                _warning(
                    f'Multi species "{species_id}" has species features or outward '
                    "binding sites but no speciesType attribute.",
                    "dropped",
                )
            )
            continue
        if not type_id:
            source_pattern = str(_attribute(species, "name", "") or "").strip()
            source_pattern = source_pattern or species_id
            try:
                parsed_source = read_from_string(source_pattern)
            except (TypeError, ValueError):
                parsed_source = None
            if parsed_source is None or not getattr(parsed_source, "molecules", None):
                warnings.append(
                    _warning(
                        f'Core species "{species_id}" has no Multi speciesType '
                        "and its name is not a parseable BNGL pattern.",
                        "dropped",
                    )
                )
                continue
            species_patterns[species_id] = source_pattern
            if (
                _attribute(species, "initialAmount") != ""
                or _attribute(species, "initialConcentration") != ""
            ):
                seed_patterns.append((species_id, source_pattern))
            continue
        if type_id not in types:
            if type_id:
                warnings.append(
                    _warning(
                        f'Multi species "{species_id}" references undefined '
                        f'speciesType "{type_id}".',
                        "dropped",
                    )
                )
            continue
        type_compartment = types[type_id].compartment
        if (
            type_compartment
            and species_compartment
            and type_compartment != species_compartment
        ):
            warnings.append(
                _warning(
                    f'Multi species "{species_id}" compartment '
                    f'"{species_compartment}" conflicts with speciesType '
                    f'compartment "{type_compartment}".',
                    "dropped",
                )
            )
        if (
            species_compartment
            and compartment_is_type.get(species_compartment) == "true"
            and (
                _attribute(species, "initialAmount") != ""
                or _attribute(species, "initialConcentration") != ""
            )
        ):
            warnings.append(
                _warning(
                    f'Multi species "{species_id}" is initialized in a '
                    "compartment type and is not fully defined.",
                    "dropped",
                )
            )
        species_type_by_species[species_id] = type_id
        known_feature_types, ambiguous_feature_ids = visible_feature_types(type_id)
        feature_elements: List[Any] = []
        for child in list(feature_list) if feature_list is not None else []:
            if _local_name(child.tag) == "speciesFeature":
                feature_elements.append(child)
            elif _local_name(child.tag) == "subListOfSpeciesFeatures":
                if _attribute(child, "relation", "").lower() == "and":
                    nested_feature_ids = {
                        _attribute(feature, "speciesFeatureType")
                        for feature in _children(child, "speciesFeature", namespace)
                    }
                    if not any(
                        known_occur > 1
                        for feature_id in nested_feature_ids
                        for known_occur, _values in [
                            known_feature_types.get(feature_id, (0, set()))
                        ]
                    ):
                        warnings.append(
                            _warning(
                                "SBML subListOfSpeciesFeatures relation=and is "
                                "only valid when at least one referenced "
                                "speciesFeatureType has occur>1.",
                                "dropped",
                            )
                        )
                feature_elements.extend(_children(child, "speciesFeature", namespace))
        seen_feature_occurrences = set()
        seen_feature_ids = set()
        for child in list(feature_list) if feature_list is not None else []:
            if _local_name(child.tag) != "subListOfSpeciesFeatures":
                continue
            sublist_id = _attribute(child, "id")
            if sublist_id:
                if sublist_id in seen_feature_ids:
                    warnings.append(
                        _warning(
                            f'Duplicate Multi species feature object id "{sublist_id}" '
                            f'in species "{species_id}".',
                            "dropped",
                        )
                    )
                seen_feature_ids.add(sublist_id)
        for feature in feature_elements:
            feature_id = _attribute(feature, "speciesFeatureType")
            feature_object_id = _attribute(feature, "id")
            if feature_object_id:
                species_feature_ids.add(feature_object_id)
                if feature_object_id in seen_feature_ids:
                    warnings.append(
                        _warning(
                            f'Duplicate Multi speciesFeature id "{feature_object_id}" '
                            f'in species "{species_id}".',
                            "dropped",
                        )
                    )
                seen_feature_ids.add(feature_object_id)
            raw_occur = _attribute(feature, "occur")
            try:
                occur = int(raw_occur)
            except ValueError:
                occur = 0
            if not raw_occur or occur <= 0:
                warnings.append(
                    _warning(
                        f'Multi speciesFeature "{feature_id}" on species '
                        f'"{species_id}" must have a positive occur attribute.',
                        "dropped",
                    )
                )
                continue
            if not feature_id:
                warnings.append(
                    _warning(
                        f'Multi species "{species_id}" contains a speciesFeature '
                        "without speciesFeatureType.",
                        "dropped",
                    )
                )
                continue
            if feature_id in ambiguous_feature_ids:
                warnings.append(
                    _warning(
                        f'Multi species "{species_id}" references ambiguous '
                        f'speciesFeatureType "{feature_id}" from nested components.',
                        "dropped",
                    )
                )
                continue
            feature_key = (
                feature_id,
                occur,
                _attribute(feature, "component"),
            )
            if feature_key in seen_feature_occurrences:
                warnings.append(
                    _warning(
                        f'Multi species "{species_id}" repeats speciesFeature '
                        f'occurrence "{feature_id}:{occur}" for the same component.',
                        "dropped",
                    )
                )
            seen_feature_occurrences.add(feature_key)
            known = known_feature_types.get(feature_id)
            if known is None:
                warnings.append(
                    _warning(
                        f'Multi species "{species_id}" references undefined '
                        f'speciesFeatureType "{feature_id}".',
                        "dropped",
                    )
                )
                continue
            max_occur, allowed_values = known
            if occur > max_occur:
                warnings.append(
                    _warning(
                        f'Multi species "{species_id}" speciesFeature "{feature_id}" '
                        f"has occur={occur}, exceeding its speciesFeatureType "
                        f"occur={max_occur}.",
                        "dropped",
                    )
                )
            values_parent = _first_child(
                feature, "listOfSpeciesFeatureValues", namespace
            )
            values = _children(values_parent, "speciesFeatureValue", namespace)
            if not values:
                warnings.append(
                    _warning(
                        f'Multi speciesFeature "{feature_id}" on species '
                        f'"{species_id}" requires at least one value.',
                        "dropped",
                    )
                )
            for value in values:
                raw_value = _attribute(value, "value")
                if not raw_value or raw_value not in allowed_values:
                    warnings.append(
                        _warning(
                            f'Multi speciesFeature "{feature_id}" on species '
                            f'"{species_id}" references undefined value '
                            f'"{raw_value}".',
                            "dropped",
                        )
                    )
        pattern = _species_pattern_from_multi(
            species,
            type_id,
            types,
            namespace,
            structure_warnings,
            compartment_references,
        )
        if pattern:
            species_patterns[species_id] = pattern
            if (
                _attribute(species, "initialAmount") != ""
                or _attribute(species, "initialConcentration") != ""
            ):
                seed_patterns.append((species_id, pattern))

    reaction_product_maps: Dict[str, Dict[str, List[Any]]] = {}
    species_ids = set(species_compartments)
    species_elements = {
        _attribute(species, "id"): species
        for species in _children(species_parent, "species")
        if _attribute(species, "id")
    }

    def has_explicit_unbound_site(species_id: str) -> bool:
        species_element = species_elements.get(species_id)
        if species_element is None:
            return False
        outward_list = _first_child(
            species_element, "listOfOutwardBindingSites", namespace
        )
        return any(
            _attribute(site, "bindingStatus").lower() == "unbound"
            for site in _children(outward_list, "outwardBindingSite", namespace)
        )

    def reference_stoichiometry(reference: Any) -> int:
        raw = _attribute(reference, "stoichiometry", "1")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0
        return int(value) if value.is_integer() and value >= 0 else 0

    untyped_reaction_species = False
    reaction_parent = _first_child(model, "listOfReactions")
    reaction_ids = set()
    for reaction in (list(reaction_parent) if reaction_parent is not None else []):
        if _local_name(reaction.tag) not in {"reaction", "intraSpeciesReaction"}:
            continue
        reaction_id = _attribute(reaction, "id")
        if not reaction_id:
            continue
        if reaction_id in reaction_ids:
            warnings.append(
                _warning(
                    f'Duplicate core reaction id "{reaction_id}".',
                    "dropped",
                )
            )
        reaction_ids.add(reaction_id)
        reference_ids = set()
        reactant_refs = {
            _attribute(reference, "id"): reference
            for reference in _children(
                _first_child(reaction, "listOfReactants"),
                "speciesReference",
            )
            if _attribute(reference, "id")
        }
        for reference in _children(
            _first_child(reaction, "listOfReactants"), "speciesReference"
        ):
            reference_id = _attribute(reference, "id")
            if reference_id in reference_ids:
                warnings.append(
                    _warning(
                        f'Duplicate speciesReference id "{reference_id}" in '
                        f'reaction "{reaction_id}".',
                        "dropped",
                    )
                )
            if reference_id:
                reference_ids.add(reference_id)
        for reference in _children(
            _first_child(reaction, "listOfReactants"), "speciesReference"
        ):
            species_id = _attribute(reference, "species")
            if species_id not in species_ids:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" references undefined species '
                        f'"{species_id}".',
                        "dropped",
                    )
                )
            elif (
                species_id not in species_type_by_species
                and species_id not in species_patterns
            ):
                untyped_reaction_species = True
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" uses core species "{species_id}" '
                        "without a Multi speciesType; the complete reaction "
                        "semantics cannot be reconstructed.",
                        "dropped",
                    )
                )
            compartment_reference = _namespaced_attribute(
                reference, namespace, "compartmentReference"
            )
            if compartment_reference:
                parent_compartment = species_compartments.get(species_id, "")
                if compartment_reference not in compartment_references.get(
                    parent_compartment, {}
                ):
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" reactant compartmentReference '
                            f'"{compartment_reference}" is not defined by species '
                            f'compartment "{parent_compartment}".',
                            "dropped",
                        )
                    )
        for reference in _children(
            _first_child(reaction, "listOfModifiers"), "modifierSpeciesReference"
        ):
            modifier_species = _attribute(reference, "species")
            if modifier_species not in species_ids:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" modifier references undefined '
                        f'species "{modifier_species}".',
                        "dropped",
                    )
                )
            compartment_reference = _namespaced_attribute(
                reference, namespace, "compartmentReference"
            )
            if compartment_reference:
                parent_compartment = species_compartments.get(modifier_species, "")
                if compartment_reference not in compartment_references.get(
                    parent_compartment, {}
                ):
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" modifier compartmentReference '
                            f'"{compartment_reference}" is not defined by species '
                            f'compartment "{parent_compartment}".',
                            "dropped",
                        )
                    )
        product_parent = _first_child(reaction, "listOfProducts")
        product_reference_ids = set()
        for product_index, product in enumerate(
            _children(product_parent, "speciesReference")
        ):
            product_id = _attribute(product, "id") or f"product_{product_index + 1}"
            if product_id in product_reference_ids or product_id in reference_ids:
                warnings.append(
                    _warning(
                        f'Duplicate product speciesReference id "{product_id}" in '
                        f'reaction "{reaction_id}".',
                        "dropped",
                    )
                )
            product_reference_ids.add(product_id)
            product_species = _attribute(product, "species")
            if product_species not in species_ids:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" references undefined product '
                        f'species "{product_species}".',
                        "dropped",
                    )
                )
            elif (
                product_species not in species_type_by_species
                and product_species not in species_patterns
            ):
                untyped_reaction_species = True
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" uses core product species '
                        f'"{product_species}" without a Multi speciesType; the '
                        "complete reaction semantics cannot be reconstructed.",
                        "dropped",
                    )
                )
            compartment_reference = _namespaced_attribute(
                product, namespace, "compartmentReference"
            )
            if compartment_reference:
                parent_compartment = species_compartments.get(product_species, "")
                if compartment_reference not in compartment_references.get(
                    parent_compartment, {}
                ):
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" product compartmentReference '
                            f'"{compartment_reference}" is not defined by species '
                            f'compartment "{parent_compartment}".',
                            "dropped",
                        )
                    )
            map_parent = _first_child(
                product, "listOfSpeciesTypeComponentMapsInProduct"
            )
            maps: List[Any] = []
            if map_parent is not None and not _children(
                map_parent, "speciesTypeComponentMapInProduct", namespace
            ):
                warnings.append(
                    _warning(
                        f'Reaction product "{product_id}" in "{reaction_id}" has '
                        "an empty Multi component-map list.",
                        "dropped",
                    )
                )
            mapping_ids = set()
            mapped_product_components = set()
            for mapping in _children(
                map_parent, "speciesTypeComponentMapInProduct", namespace
            ):
                reactant = _attribute(mapping, "reactant")
                reactant_component = _attribute(mapping, "reactantComponent")
                product_component = _attribute(mapping, "productComponent")
                if not reactant or not reactant_component or not product_component:
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" contains an incomplete '
                            "Multi product component map.",
                            "dropped",
                        )
                    )
                    continue
                mapping_id = _attribute(mapping, "id")
                if mapping_id and mapping_id in mapping_ids:
                    warnings.append(
                        _warning(
                            f'Duplicate Multi product component map id "{mapping_id}" '
                            f'in reaction "{reaction_id}".',
                            "dropped",
                        )
                    )
                    continue
                if mapping_id:
                    mapping_ids.add(mapping_id)
                if reactant not in reactant_refs:
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" refers '
                            f'to unknown reactant speciesReference "{reactant}".',
                            "dropped",
                        )
                    )
                    continue
                reactant_species = _attribute(reactant_refs[reactant], "species")
                reactant_type = species_type_by_species.get(reactant_species, "")
                product_type = species_type_by_species.get(product_species, "")
                if not reactant_type or not product_type:
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" requires '
                            "Multi speciesType references on both reactant and "
                            "product species.",
                            "dropped",
                        )
                    )
                    continue
                if reactant_type and reactant_component not in component_aliases.get(
                    reactant_type, {}
                ):
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" cannot '
                            f'resolve reactant component "{reactant_component}".',
                            "dropped",
                        )
                    )
                    continue
                if product_type and product_component not in component_aliases.get(
                    product_type, {}
                ):
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" cannot '
                            f'resolve product component "{product_component}".',
                            "dropped",
                        )
                    )
                    continue
                if product_component in mapped_product_components:
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" maps '
                            f'product component "{product_component}" more than once.',
                            "dropped",
                        )
                    )
                    continue
                mapped_product_components.add(product_component)
                maps.append(
                    SBMLMultiComponentMap(
                        reactant=reactant,
                        reactant_component=reactant_component,
                        product_component=product_component,
                        id=mapping_id or None,
                        name=_attribute(mapping, "name"),
                    )
                )
            if maps:
                reaction_product_maps.setdefault(reaction_id, {})[product_id] = maps

        if _local_name(reaction.tag) == "intraSpeciesReaction":
            reactants = _children(
                _first_child(reaction, "listOfReactants"), "speciesReference"
            )
            products = _children(
                _first_child(reaction, "listOfProducts"), "speciesReference"
            )
            reactant_count = sum(reference_stoichiometry(item) for item in reactants)
            product_count = sum(reference_stoichiometry(item) for item in products)
            association_shape = (
                len(reactants) == 2
                and all(reference_stoichiometry(item) == 1 for item in reactants)
                and len(products) == 1
                and product_count == 1
            )
            dissociation_shape = (
                len(reactants) == 1
                and reactant_count == 1
                and len(products) == 2
                and all(reference_stoichiometry(item) == 1 for item in products)
            )
            if association_shape:
                if not all(
                    has_explicit_unbound_site(_attribute(item, "species"))
                    for item in reactants
                ):
                    warnings.append(
                        _warning(
                            f'IntraSpeciesReaction "{reaction_id}" association '
                            "requires an explicit unbound outward binding site on "
                            "each reactant species.",
                            "dropped",
                        )
                    )
            elif dissociation_shape:
                if not all(
                    has_explicit_unbound_site(_attribute(item, "species"))
                    for item in products
                ):
                    warnings.append(
                        _warning(
                            f'IntraSpeciesReaction "{reaction_id}" dissociation '
                            "requires an explicit unbound outward binding site on "
                            "each product species.",
                            "dropped",
                        )
                    )
            else:
                warnings.append(
                    _warning(
                        f'IntraSpeciesReaction "{reaction_id}" must be a '
                        "two-reactant association or two-product dissociation.",
                        "dropped",
                    )
                )

    valid_product_map_containers = {
        id(product_map)
        for reaction in (list(reaction_parent) if reaction_parent is not None else [])
        if _local_name(reaction.tag) in {"reaction", "intraSpeciesReaction"}
        for product in _children(
            _first_child(reaction, "listOfProducts"), "speciesReference"
        )
        for product_map in [
            _first_child(product, "listOfSpeciesTypeComponentMapsInProduct")
        ]
        if product_map is not None
    }
    for element in root.iter():
        if (
            _local_name(element.tag) == "listOfSpeciesTypeComponentMapsInProduct"
            and _namespace(element.tag) == namespace
            and id(element) not in valid_product_map_containers
        ):
            warnings.append(
                _warning(
                    "SBML Multi component maps are only permitted on reaction "
                    "product speciesReference objects.",
                    "dropped",
                )
            )

    math_namespace = "http://www.w3.org/1998/Math/MathML"
    for reaction in (list(reaction_parent) if reaction_parent is not None else []):
        if _local_name(reaction.tag) not in {"reaction", "intraSpeciesReaction"}:
            continue
        reaction_id = _attribute(reaction, "id") or "<anonymous>"
        reference_ids = {
            _attribute(reference, "id")
            for parent_name, child_name in (
                ("listOfReactants", "speciesReference"),
                ("listOfProducts", "speciesReference"),
                ("listOfModifiers", "modifierSpeciesReference"),
            )
            for reference in _children(_first_child(reaction, parent_name), child_name)
            if _attribute(reference, "id")
        }
        for ci in reaction.iter():
            if _local_name(ci.tag) != "ci" or _namespace(ci.tag) != math_namespace:
                continue
            representation = _namespaced_attribute(ci, namespace, "representationType")
            species_reference = _namespaced_attribute(ci, namespace, "speciesReference")
            content = "".join(ci.itertext()).strip()
            if representation not in {"", "sum", "numericValue"}:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" has unsupported Multi '
                        f'representationType "{representation}".',
                        "dropped",
                    )
                )
            if species_reference and species_reference not in reference_ids:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" MathML ci references unknown '
                        f'speciesReference "{species_reference}".',
                        "dropped",
                    )
                )
            if representation == "numericValue" and not species_reference:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" numericValue representation '
                        "requires a speciesReference.",
                        "dropped",
                    )
                )
            if representation == "sum" and content not in species_ids:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" sum ci content "{content}" '
                        "does not identify a core species.",
                        "dropped",
                    )
                )
            if representation == "numericValue" and content not in possible_value_owner:
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" numericValue ci content '
                        f'"{content}" does not identify a possibleSpeciesFeatureValue.',
                        "dropped",
                    )
                )
            if (
                species_reference
                and content not in species_ids
                and content not in species_feature_ids
                and not (
                    representation == "numericValue"
                    and content in possible_value_owner
                )
            ):
                warnings.append(
                    _warning(
                        f'Reaction "{reaction_id}" MathML ci content "{content}" '
                        "must identify a species or speciesFeature when "
                        "multi:speciesReference is present.",
                        "dropped",
                    )
                )
            if representation == "numericValue" and content in possible_value_owner:
                numeric_parameter = next(
                    (
                        species_type.feature_numeric_values.get(content, "")
                        for species_type in types.values()
                        if content in species_type.feature_numeric_values
                    ),
                    "",
                )
                if not numeric_parameter:
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" numericValue ci content '
                            f'"{content}" has no referenced parameter.',
                            "dropped",
                        )
                    )

    warnings.extend(structure_warnings)
    if molecule_types:
        warnings.append(
            _warning(
                f"SBML Multi parsed {len(molecule_types)} molecule type(s), "
                f"{len(complex_patterns)} complex type(s), and "
                f"{len(species_patterns)} species pattern(s).",
                "info" if package_valid else "approximated",
            )
        )
    executable = bool(
        package_valid
        and types
        and species_patterns
        and not untyped_reaction_species
        and not namespace_violation
        and not any(warning.severity == "dropped" for warning in warnings)
        and not any(warning.severity == "dropped" for warning in structure_warnings)
    )
    if not executable and package_valid and species_patterns and structure_warnings:
        warnings.append(
            _warning(
                "SBML Multi structures were retained as diagnostics but execution "
                "was disabled because at least one structure was not representable.",
                "dropped",
            )
        )
    return MultiParseResult(
        present=True,
        deep=deep_hierarchy,
        bngl_molecule_types=molecule_types,
        complex_patterns=complex_patterns,
        seed_patterns=seed_patterns,
        species_patterns=species_patterns,
        type_patterns=type_patterns,
        component_aliases=component_aliases,
        reaction_product_maps=reaction_product_maps,
        compartment_references=compartment_references,
        numeric_values={
            value_id: parameter_id
            for species_type in types.values()
            for value_id, parameter_id in species_type.feature_numeric_values.items()
        },
        executable=executable,
        warnings=warnings,
    )


# Keep the public entry point stable while replacing the earlier bounded
# extractor with the spec-aware resolver above.
parse_multi_package = _parse_multi_package_complete


__all__ = [
    "MULTI_V1_NAMESPACE",
    "MultiParseResult",
    "parse_multi_package",
]
