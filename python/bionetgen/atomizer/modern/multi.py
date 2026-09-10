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
_SID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _is_sid(value: str) -> bool:
    """Return whether *value* has SBML's SId/SIdRef lexical shape."""

    return bool(value and _SID_PATTERN.fullmatch(value))


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
        for attribute in getattr(element, "attrib", {}):
            namespace = _namespace(attribute)
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
    feature_values: Dict[str, Dict[str, str]] = field(default_factory=dict)
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
    matches = _find_components(flat_type, token, parent)
    return matches[0] if matches else None


def _find_components(
    flat_type: _FlatType, token: str, parent: str = ""
) -> List[Tuple[_FlatMolecule, _FlatComponent]]:
    candidates = flat_type.molecules
    if parent:
        candidates = [molecule for molecule in candidates if parent in molecule.aliases]
    return [
        (molecule, component)
        for molecule in candidates
        for component in molecule.components
        if token in component.aliases
    ]


def _find_molecule(flat_type: _FlatType, token: str) -> Optional[_FlatMolecule]:
    matches = _find_molecules(flat_type, token)
    return matches[0] if matches else None


def _find_molecules(flat_type: _FlatType, token: str) -> List[_FlatMolecule]:
    return [molecule for molecule in flat_type.molecules if token in molecule.aliases]


def _apply_component_indexes(
    species_type: _SpeciesType,
    flat_type: _FlatType,
    warnings: Optional[List[SBMLImportWarning]] = None,
) -> None:
    pending = list(species_type.component_indexes.items())
    while pending:
        unresolved = []
        progress = False
        for index_id, (component, parent) in pending:
            if parent:
                molecule_matches = [
                    molecule
                    for molecule in flat_type.molecules
                    if parent in molecule.aliases and component in molecule.aliases
                ]
                component_matches = _find_components(flat_type, component, parent)
                match_count = len(molecule_matches) + len(component_matches)
                if match_count == 1:
                    if molecule_matches:
                        molecule_matches[0].aliases.add(index_id)
                    else:
                        component_matches[0][1].aliases.add(index_id)
                    progress = True
                elif match_count > 1 and warnings is not None:
                    warnings.append(
                        _warning(
                            f'Multi speciesTypeComponentIndex "{index_id}" in '
                            f'speciesType "{species_type.id}" is ambiguous for '
                            f'component "{component}" under parent "{parent}".',
                            "dropped",
                        )
                    )
                else:
                    unresolved.append((index_id, component, parent))
                continue
            molecule_matches = _find_molecules(flat_type, component)
            component_matches = _find_components(flat_type, component)
            match_count = len(molecule_matches) + len(component_matches)
            if match_count == 1:
                if molecule_matches:
                    molecule_matches[0].aliases.add(index_id)
                else:
                    component_matches[0][1].aliases.add(index_id)
                progress = True
            elif match_count > 1 and warnings is not None:
                warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'speciesType "{species_type.id}" is ambiguous for '
                        f'component "{component}".',
                        "dropped",
                    )
                )
            else:
                unresolved.append((index_id, component, parent))
        if not unresolved or not progress:
            if unresolved and warnings is not None:
                for index_id, component, parent in unresolved:
                    scope = f' under parent "{parent}"' if parent else ""
                    warnings.append(
                        _warning(
                            f'Multi speciesTypeComponentIndex "{index_id}" in '
                            f'speciesType "{species_type.id}" could not resolve '
                            f'component "{component}"{scope}.',
                            "dropped",
                        )
                    )
            return
        pending = [
            (index_id, (component, parent))
            for index_id, component, parent in unresolved
        ]


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


def _bonded_component(flat_type: _FlatType, component: _FlatComponent) -> bool:
    return any(
        component is endpoint
        for bond in flat_type.bonds
        for endpoint in bond
    )


def _flatten_type(
    type_id: str,
    types: Dict[str, _SpeciesType],
    warnings: List[SBMLImportWarning],
    stack: Tuple[str, ...] = (),
    compartment_references: Optional[Dict[str, Dict[str, str]]] = None,
    inherited_compartment: str = "",
    compartment_types: Optional[Dict[str, str]] = None,
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
            aliases={species_type.id},
            compartment=effective_compartment,
        )
        for feature_id, feature_name, values, occurrence in _feature_defs(species_type):
            molecule.components.append(
                _FlatComponent(
                    label=_clean(feature_name),
                    aliases=set(),
                    states=[_clean(value) for value in values],
                    feature_ids={feature_id},
                    feature_values={
                        feature_id: dict(
                            species_type.feature_definitions[feature_id][1]
                        )
                    },
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
            if any(
                occurrence > 1 for occurrence in target.feature_occurs.values()
            ):
                warnings.append(
                    _warning(
                        f'Multi binding-site speciesType "{instance.type_id}" '
                        "contains repeated speciesFeature occurrences; a BNGL "
                        "binding-site component cannot represent those nested "
                        "feature instances without changing the component graph.",
                        "dropped",
                    )
                )
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
            target_compartment = target.compartment
            if (
                not instance.compartment_reference
                and effective_compartment
                and target_compartment
                and effective_compartment != target_compartment
                and (compartment_types or {}).get(effective_compartment)
                != target_compartment
            ):
                warnings.append(
                    _warning(
                        f'Multi binding-site instance "{instance.id}" in '
                        f'speciesType "{type_id}" uses compartment '
                        f'"{target_compartment}" inconsistent with containing '
                        f'compartment "{effective_compartment}" without a '
                        "compartmentReference.",
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
            }
            states: List[str] = []
            feature_ids = set()
            feature_values: Dict[str, Dict[str, str]] = {}
            for feature_id, feature_name, values, occurrence in _feature_defs(target):
                feature_ids.add(feature_id)
                feature_values[feature_id] = dict(
                    target.feature_definitions[feature_id][1]
                )
                states.extend(_clean(value) for value in values)
            molecule.components.append(
                _FlatComponent(
                    label=label,
                    aliases={alias for alias in aliases if alias},
                    states=list(dict.fromkeys(states)),
                    feature_ids=feature_ids,
                    feature_values=feature_values,
                    is_binding_site=True,
                )
            )
        flat.molecules.append(molecule)
        _apply_component_indexes(species_type, flat, warnings)
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
            if (
                endpoint1[1] is endpoint2[1]
                or _bonded_component(flat, endpoint1[1])
                or _bonded_component(flat, endpoint2[1])
            ):
                warnings.append(
                    _warning(
                        f'Multi bond in speciesType "{type_id}" reuses a binding '
                        "site; Multi bonds are one-to-one.",
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
        if (
            not instance.compartment_reference
            and effective_compartment
            and child_compartment
            and effective_compartment != child_compartment
            and (compartment_types or {}).get(effective_compartment)
            != child_compartment
        ):
            warnings.append(
                _warning(
                    f'SpeciesTypeInstance "{instance.id}" in speciesType '
                    f'"{type_id}" uses child compartment "{child_compartment}" '
                    f'inconsistent with containing compartment '
                    f'"{effective_compartment}" without a compartmentReference.',
                    "dropped",
                )
            )
        if instance_compartment:
            target_compartment = instance_compartment
        elif (
            effective_compartment
            and child_compartment
            and (
                effective_compartment == child_compartment
                or (compartment_types or {}).get(effective_compartment)
                == child_compartment
            )
        ):
            target_compartment = effective_compartment
        else:
            target_compartment = child_compartment or effective_compartment
        child = _flatten_type(
            instance.type_id,
            types,
            warnings,
            stack + (type_id,),
            compartment_references,
            target_compartment,
            compartment_types,
        )
        for molecule in child.molecules:
            molecule.aliases.update(
                {
                    instance.id,
                    instance.type_id,
                }
            )
        flat.molecules.extend(child.molecules)
        flat.bonds.extend(child.bonds)

    # The containing SpeciesType itself is a valid identifying parent for
    # component references.  Give flattened molecules that scope alias before
    # resolving local indexes.
    for molecule in flat.molecules:
        molecule.aliases.add(type_id)
    _apply_component_indexes(species_type, flat, warnings)
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
        if (
            endpoint1[1] is endpoint2[1]
            or _bonded_component(flat, endpoint1[1])
            or _bonded_component(flat, endpoint2[1])
        ):
            warnings.append(
                _warning(
                    f'Multi bond in speciesType "{type_id}" reuses a binding '
                    "site; Multi bonds are one-to-one.",
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
    compartment_types: Optional[Dict[str, str]] = None,
    species_compartment: str = "",
    initialized_by_assignment: bool = False,
) -> Optional[str]:
    flat = _flatten_type(
        type_id,
        types,
        warnings,
        compartment_references=compartment_references,
        compartment_types=compartment_types,
    )
    if not flat.molecules:
        return None
    type_compartment = types[type_id].compartment
    if species_compartment and type_compartment != species_compartment:
        if not type_compartment:
            for molecule in flat.molecules:
                if not molecule.compartment:
                    molecule.compartment = species_compartment
        elif (compartment_types or {}).get(species_compartment) == type_compartment:
            for molecule in flat.molecules:
                if molecule.compartment == type_compartment:
                    molecule.compartment = species_compartment
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
        targets: List[_FlatComponent] = []
        for molecule in flat.molecules:
            for component in molecule.components:
                if component_token and component_token in component.aliases:
                    targets.append(component)
                elif component_token and component_token in molecule.aliases:
                    if feature_id in component.feature_ids:
                        targets.append(component)
                elif not component_token and feature_id in component.feature_ids:
                    targets.append(component)
        if not raw_values:
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
        value_labels = occurrence_targets[0].feature_values.get(feature_id, {})
        values = []
        for raw_value in raw_values:
            if raw_value not in value_labels:
                warnings.append(
                    _warning(
                        f'Multi speciesFeature "{feature_id}" value '
                        f'"{raw_value}" is not defined by its component.',
                        "dropped",
                    )
                )
                continue
            values.append(_clean(value_labels[raw_value]))
        if not values:
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

    # A positive initial pool must denote one fully defined species, rather
    # than a pattern that still stands for many pools.  Zero-valued pattern
    # species are common and remain valid templates.  This mirrors Multi
    # section 3.19 while keeping the BNGL wildcard mapping explicit.
    initial_values = [
        _attribute(species, "initialAmount"),
        _attribute(species, "initialConcentration"),
    ]
    has_positive_initial = initialized_by_assignment
    for raw_initial in initial_values:
        if not raw_initial:
            continue
        try:
            has_positive_initial = has_positive_initial or float(raw_initial) > 0
        except (TypeError, ValueError):
            pass
    if has_positive_initial:
        bonded_components = {
            id(endpoint)
            for bond in flat.bonds
            for endpoint in bond
        }
        for molecule in flat.molecules:
            for component in molecule.components:
                if component.is_binding_site and id(component) not in bonded_components and (
                    component.binding_status != "unbound"
                ):
                    warnings.append(
                        _warning(
                            f'Multi species "{_attribute(species, "id")}" has a '
                            "positive initial pool but not all outward binding "
                            "sites are explicitly unbound.",
                            "dropped",
                        )
                    )
                if component.feature_ids and not component.active_state:
                    warnings.append(
                        _warning(
                            f'Multi species "{_attribute(species, "id")}" has a '
                            "positive initial pool but not every speciesFeature "
                            "occurrence has one value.",
                            "dropped",
                        )
                    )
    # Core Species.name is a human-readable label, not a pattern-bearing
    # attribute.  A Multi speciesType is therefore always reconstructed from
    # the package graph and per-species annotations; accepting a parseable
    # name here would silently turn arbitrary labels into executable BNGL.
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

_MULTI_ALLOWED_CHILDREN = {
    "listOfCompartmentReferences": {"compartmentReference"},
    "compartmentReference": set(),
    "listOfSpeciesTypes": {"speciesType", "bindingSiteSpeciesType"},
    "speciesType": {
        "listOfSpeciesFeatureTypes",
        "listOfSpeciesTypeInstances",
        "listOfSpeciesTypeComponentIndexes",
        "listOfInSpeciesTypeBonds",
    },
    # BindingSiteSpeciesType inherits SpeciesType.  The specification only
    # forbids listOfSpeciesTypeInstances for this class; other inherited lists
    # remain part of the package grammar and are rejected later only when they
    # cannot be lowered to an executable BNGL atom.
    "bindingSiteSpeciesType": {
        "listOfSpeciesFeatureTypes",
        "listOfSpeciesTypeComponentIndexes",
        "listOfInSpeciesTypeBonds",
    },
    "listOfSpeciesTypeInstances": {"speciesTypeInstance"},
    "speciesTypeInstance": set(),
    "listOfSpeciesTypeComponentIndexes": {"speciesTypeComponentIndex"},
    "speciesTypeComponentIndex": set(),
    "listOfInSpeciesTypeBonds": {"inSpeciesTypeBond"},
    "inSpeciesTypeBond": set(),
    "listOfSpeciesFeatureTypes": {"speciesFeatureType"},
    "speciesFeatureType": {"listOfPossibleSpeciesFeatureValues"},
    "listOfPossibleSpeciesFeatureValues": {"possibleSpeciesFeatureValue"},
    "possibleSpeciesFeatureValue": set(),
    "listOfSpeciesFeatures": {"speciesFeature", "subListOfSpeciesFeatures"},
    "speciesFeature": {"listOfSpeciesFeatureValues"},
    "listOfSpeciesFeatureValues": {"speciesFeatureValue"},
    "speciesFeatureValue": set(),
    "listOfOutwardBindingSites": {"outwardBindingSite"},
    "outwardBindingSite": set(),
    "subListOfSpeciesFeatures": {"speciesFeature"},
    "intraSpeciesReaction": {
        "listOfReactants",
        "listOfProducts",
        "listOfModifiers",
        "kineticLaw",
    },
    "listOfSpeciesTypeComponentMapsInProduct": {
        "speciesTypeComponentMapInProduct"
    },
    "speciesTypeComponentMapInProduct": set(),
}

_MULTI_METADATA_ELEMENTS = {"notes", "annotation"}
_MULTI_CORE_CHILDREN = {
    "listOfReactants",
    "listOfProducts",
    "listOfModifiers",
    "kineticLaw",
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
    metadata_nodes = {
        id(descendant)
        for element in root.iter()
        if _namespace(element.tag) == CORE_V1_NAMESPACE
        and _local_name(element.tag) in _MULTI_METADATA_ELEMENTS
        for descendant in element.iter()
    }

    def mark(message: str) -> None:
        nonlocal invalid
        invalid = True
        warnings.append(_warning(message, "dropped"))

    def validate_value(element: Any, key: str, value: str, key_namespace: str) -> None:
        """Validate Multi primitive lexical values before semantic resolution."""

        nonlocal invalid
        if key_namespace not in {namespace, ""}:
            return
        if key in {"id", "component", "identifyingParent", "bindingSite1", "bindingSite2",
                   "speciesType", "compartmentReference", "compartment", "compartmentType",
                   "reactant", "reactantComponent", "productComponent", "value",
                   "numericValue", "speciesFeatureType", "speciesReference"}:
            if not _is_sid(value):
                mark(
                    f'Multi attribute "{key}" on {_local_name(element.tag)} '
                    f'has invalid SId/SIdRef value "{value}".'
                )
        elif key == "occur" and not re.fullmatch(r"[1-9][0-9]*", value):
            mark(
                f'Multi attribute "occur" on {_local_name(element.tag)} must be '
                "a positiveInteger."
            )
        elif key == "bindingStatus" and value not in {"bound", "unbound", "either"}:
            mark(
                f'Multi attribute "bindingStatus" on {_local_name(element.tag)} '
                f'has invalid value "{value}".'
            )
        elif key == "relation" and value not in {"and", "or", "not"}:
            mark(
                f'Multi attribute "relation" on {_local_name(element.tag)} '
                f'has invalid value "{value}".'
            )
        elif key == "representationType" and value not in {"sum", "numericValue"}:
            mark(
                f'Multi attribute "representationType" on {_local_name(element.tag)} '
                f'has invalid value "{value}".'
            )
        elif key in {"required", "isType"} and value not in {
            "true",
            "false",
            "1",
            "0",
        }:
            mark(
                f'Multi boolean attribute "{key}" on {_local_name(element.tag)} '
                f'has invalid value "{value}".'
            )

    for element in root.iter():
        if id(element) in metadata_nodes:
            continue
        local = _local_name(element.tag)
        element_namespace = _namespace(element.tag)
        if "/multi/" in element_namespace and element_namespace != namespace:
            mark(
                f'Unsupported SBML Multi element namespace "{element_namespace}".'
            )
            continue
        if element_namespace == namespace:
            if local not in _MULTI_ELEMENTS:
                mark(
                    f'Unsupported SBML Multi element "{local}"; its semantics '
                    "are not reconstructed."
                )
            parent = parents.get(id(element))
            parent_local = _local_name(parent.tag) if parent is not None else ""
            allowed_parents = _MULTI_ALLOWED_PARENTS.get(local)
            if allowed_parents is not None and parent_local not in allowed_parents:
                mark(
                    f'SBML Multi element "{local}" is not allowed inside '
                    f'core or Multi parent "{parent_local or "<root>"}".'
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
                    mark(
                        f'SBML Multi element "{local}" has parent '
                        f'"{parent_local}" in namespace "{parent_namespace}"; '
                        f'expected "{expected_parent_namespace}".'
                    )
            allowed = set(_MULTI_ELEMENT_ATTRIBUTES.get(local, set()))
            if local == "intraSpeciesReaction":
                allowed.clear()
            for required_attribute in _MULTI_REQUIRED_ATTRIBUTES.get(local, set()):
                if not _attribute(element, required_attribute):
                    mark(
                        f'Multi {local} is missing required attribute '
                        f'"{required_attribute}".'
                    )
            for key in getattr(element, "attrib", {}):
                key_namespace = _namespace(key)
                key_local = _local_name(key)
                if key_namespace == namespace:
                    if key_local not in allowed:
                        mark(
                            f'Unexpected Multi attribute "{key_local}" on '
                            f"{local}."
                        )
                    else:
                        validate_value(
                            element,
                            key_local,
                            str(element.attrib[key]),
                            key_namespace,
                        )
                elif key_namespace == CORE_V1_NAMESPACE:
                    if key_local not in _MULTI_CORE_ATTRIBUTES:
                        mark(
                            f'Unexpected core attribute "{key_local}" on '
                            f"Multi {local}."
                        )
                elif key_namespace == "":
                    # Multi attributes on package-defined elements may be
                    # unqualified or explicitly in the Multi namespace.
                    # Attributes added to SBML Core/MathML elements are the
                    # exception and are required to use the Multi namespace.
                    unqualified_allowed = (
                        _INTRA_REACTION_CORE_ATTRIBUTES
                        if local == "intraSpeciesReaction"
                        else allowed
                    )
                    if key_local not in unqualified_allowed:
                        mark(
                            f'Multi attribute "{key_local}" on {local} must '
                            "use the Multi namespace."
                        )
                    else:
                        validate_value(
                            element,
                            key_local,
                            str(element.attrib[key]),
                            key_namespace,
                        )
                else:
                    mark(
                        f'Attribute "{key_local}" on Multi element {local} '
                        "uses an unsupported namespace."
                    )
            allowed_children = _MULTI_LIST_CHILDREN.get(local)
            if allowed_children is not None:
                package_children = [
                    child
                    for child in list(element)
                    if _namespace(child.tag) == namespace
                ]
                if not package_children:
                    mark(
                        f"SBML Multi {local} must contain at least one "
                        "package child."
                    )
                for child in package_children:
                    child_local = _local_name(child.tag)
                    if child_local not in allowed_children:
                        mark(
                            f"SBML Multi {local} contains unsupported child "
                            f'"{child_local}".'
                        )
            allowed_children = _MULTI_ALLOWED_CHILDREN.get(local)
            if allowed_children is not None:
                for child in list(element):
                    child_local = _local_name(child.tag)
                    child_namespace = _namespace(child.tag)
                    if (
                        child_namespace == CORE_V1_NAMESPACE
                        and child_local in _MULTI_METADATA_ELEMENTS
                    ):
                        continue
                    if child_local not in allowed_children:
                        mark(
                            f'SBML Multi {local} contains unexpected child '
                            f'"{child_local}".'
                        )
                    elif child_local in _MULTI_CORE_CHILDREN:
                        if child_namespace != CORE_V1_NAMESPACE:
                            mark(
                                f'Core child "{child_local}" under Multi {local} '
                                "must use the SBML Core namespace."
                            )
                    elif child_namespace != namespace:
                        mark(
                            f'Multi child "{child_local}" under {local} must use '
                            "the Multi namespace."
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
                else:
                    validate_value(
                        element,
                        _local_name(key),
                        str(element.attrib[key]),
                        namespace,
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
                mark(
                    f'Multi attribute "{_local_name(key)}" on core {local} '
                    "must use the Multi namespace."
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
            # Other SBML packages are validated by their own import paths.  Do
            # not make Multi fail closed merely because another package is
            # present; only Multi namespace placement is this validator's job.
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
    # IntraSpeciesReaction is a Multi element derived from the core Reaction
    # class, so its id participates in the model-wide SId namespace too.
    core_model_ids.update(
        _attribute(element, "id")
        for element in model.iter()
        if _namespace(element.tag) == namespace
        and _local_name(element.tag) == "intraSpeciesReaction"
        and _attribute(element, "id")
    )
    raw_type_elements = [
        *(_children(list_types, "bindingSiteSpeciesType", namespace)),
        *(_children(list_types, "speciesType", namespace)),
    ]
    all_type_ids = {
        identifier
        for element in raw_type_elements
        if (identifier := _attribute(element, "id"))
    }
    all_possible_value_ids = {
        identifier
        for element in root.iter()
        if _namespace(element.tag) == namespace
        and _local_name(element.tag) == "possibleSpeciesFeatureValue"
        if (identifier := _attribute(element, "id"))
    }
    for identifier in sorted(all_type_ids & all_possible_value_ids):
        warnings.append(
            _warning(
                f'Multi identifier "{identifier}" is used by both a '
                "speciesType and a possibleSpeciesFeatureValue; these IDs "
                "must be globally unique.",
                "dropped",
            )
        )
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
                if value_id in all_type_ids:
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
        index_list = _first_child(item, "listOfSpeciesTypeComponentIndexes", namespace)
        bond_list = _first_child(item, "listOfInSpeciesTypeBonds", namespace)
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

        bond_ids = set()
        bond_pairs = set()
        for bond in _children(bond_list, "inSpeciesTypeBond", namespace):
            bond_id = _attribute(bond, "id")
            if bond_id and bond_id in bond_ids:
                warnings.append(
                    _warning(
                        f'Duplicate Multi inSpeciesTypeBond id "{bond_id}" '
                        f'in speciesType "{type_id}".',
                        "dropped",
                    )
                )
                continue
            if bond_id:
                bond_ids.add(bond_id)
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

    def resolve_component_scope(
        owner: _SpeciesType,
        token: str,
        seen: Tuple[Tuple[str, str], ...] = (),
    ) -> Optional[_SpeciesType]:
        """Resolve a component object to its nested SpeciesType scope."""

        marker = (owner.id, token)
        if not token or marker in seen:
            return None
        if token == owner.id:
            return owner
        direct_instances = [
            instance for instance in owner.instances if instance.id == token
        ]
        if len(direct_instances) == 1:
            return types.get(direct_instances[0].type_id)
        typed_instances = [
            instance for instance in owner.instances if instance.type_id == token
        ]
        if len(typed_instances) == 1:
            return types.get(typed_instances[0].type_id)
        if len(typed_instances) > 1:
            return None
        if token not in owner.component_indexes:
            return None
        component, parent = owner.component_indexes[token]
        scope = owner
        if parent:
            scope = resolve_component_scope(owner, parent, seen + (marker,))
        if scope is None:
            return None
        return resolve_component_scope(scope, component, seen + (marker,))

    def scoped_component_tokens(
        owner: _SpeciesType, identifying_parent: str = ""
    ) -> set:
        """Return component/index ids visible from a Multi component scope."""

        scope = (
            owner
            if not identifying_parent
            else resolve_component_scope(owner, identifying_parent)
        )
        if scope is None:
            return set()
        tokens = {scope.id} | set(scope.component_indexes)
        for instance in scope.instances:
            tokens.update({instance.id, instance.type_id})
        return tokens

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
        for index_id, (component, identifying_parent) in species_type.component_indexes.items():
            component_ids = scoped_component_tokens(species_type, identifying_parent)
            if component not in component_ids:
                warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'"{species_type.id}" references unknown component '
                        f'"{component}".',
                        "dropped",
                    )
                )
            parent_ids = scoped_component_tokens(species_type)
            if identifying_parent and identifying_parent not in parent_ids:
                warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'"{species_type.id}" has unknown identifyingParent '
                        f'"{identifying_parent}".',
                        "dropped",
                    )
                )
        valid_bond_endpoints = set(species_type.component_indexes)
        valid_bond_endpoints.update(instance.id for instance in species_type.instances)

        def binding_type_for(token: str) -> Optional[str]:
            target = resolve_component_scope(species_type, token)
            return target.id if target is not None and target.is_binding_site else None

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
    compartment_outside: Dict[str, str] = {}
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
        compartment_outside[compartment_id] = _attribute(compartment, "outside")

    def compartment_contains(ancestor: str, child: str) -> bool:
        seen = set()
        current = child
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            current = compartment_outside.get(current, "")
        return False

    compartment_is_type = {}
    compartment_types: Dict[str, str] = {}
    for compartment in _children(compartments, "compartment"):
        compartment_id = _attribute(compartment, "id")
        if compartment_id:
            raw_is_type = _namespaced_attribute(compartment, namespace, "isType")
            compartment_is_type[compartment_id] = (
                "true" if raw_is_type in {"true", "1"} else "false"
            )
            compartment_types[compartment_id] = _namespaced_attribute(
                compartment, namespace, "compartmentType"
            )

    def compartment_matches_type(actual: str, expected: str) -> bool:
        return not actual or not expected or actual == expected or (
            compartment_types.get(actual) == expected
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
        reference_ids = {compartment_id}
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
            elif compartment_contains(reference_compartment, compartment_id):
                warnings.append(
                    _warning(
                        f'CompartmentReference "{reference_id or "<anonymous>"}" '
                        f'in compartment "{compartment_id}" references ancestor '
                        f'compartment "{reference_compartment}".',
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
                if reference_id in reference_ids:
                    warnings.append(
                        _warning(
                            f'Duplicate compartmentReference id "{reference_id}" '
                            f'in compartment "{compartment_id}".',
                            "dropped",
                        )
                    )
                reference_ids.add(reference_id)
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
        for instance in species_type.instances:
            if not instance.compartment_reference or instance.type_id not in types:
                continue
            target_compartment = compartment_references.get(
                species_type.compartment, {}
            ).get(instance.compartment_reference, "")
            child_compartment = types[instance.type_id].compartment
            if (
                target_compartment
                and child_compartment
                and target_compartment != child_compartment
                and compartment_types.get(target_compartment) != child_compartment
            ):
                warnings.append(
                    _warning(
                        f'SpeciesTypeInstance "{instance.id}" in '
                        f'speciesType "{species_type.id}" uses compartmentReference '
                        f'"{instance.compartment_reference}" whose target '
                        f'"{target_compartment}" is inconsistent with child '
                        f'compartment "{child_compartment}".',
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
            compartment_types=compartment_types,
        )
        if not flat.molecules:
            continue
        component_aliases[type_id] = _flat_component_aliases(flat)
        for index_id in species_type.component_indexes:
            locations = component_aliases[type_id].get(index_id, [])
            if not locations:
                structure_warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'speciesType "{type_id}" could not resolve its component.',
                        "dropped",
                    )
                )
            elif len(locations) > 1:
                structure_warnings.append(
                    _warning(
                        f'Multi speciesTypeComponentIndex "{index_id}" in '
                        f'speciesType "{type_id}" resolves ambiguously to '
                        f'{len(locations)} components.',
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
    if deep_hierarchy:
        # Multi permits arbitrary SpeciesType trees, but BNGL requires an
        # explicit molecule boundary.  A deep tree (for example,
        # complex->component->molecule->binding-site) does not provide one
        # structurally; flattening it would silently merge or split molecules.
        # Preserve the diagnostic and fail closed for both required and
        # optional packages rather than manufacturing a different network.
        return MultiParseResult(
            present=True,
            deep=True,
            warnings=[
                _warning(
                    "SBML Multi package uses a multi-layer hierarchy; molecule "
                    "boundaries cannot be inferred safely, so executable BNGL "
                    "structures were not reconstructed.",
                    "dropped" if package_valid else "approximated",
                )
            ]
            + warnings,
        )

    species_patterns: Dict[str, str] = {}
    seed_patterns: List[Tuple[str, str]] = []
    species_type_by_species: Dict[str, str] = {}
    species_compartments: Dict[str, str] = {}
    species_feature_ids_by_species: Dict[str, set] = {}
    species_parent = _first_child(model, "listOfSpecies")
    initial_assignment_symbols: set = set()
    initial_assignment_parent = _first_child(
        model, "listOfInitialAssignments", CORE_V1_NAMESPACE
    )
    for assignment in _children(
        initial_assignment_parent, "initialAssignment", CORE_V1_NAMESPACE
    ):
        symbol = _attribute(assignment, "symbol")
        if not symbol:
            warnings.append(
                _warning(
                    "Core initialAssignment is missing its required symbol.",
                    "dropped",
                )
            )
            continue
        if symbol in initial_assignment_symbols:
            warnings.append(
                _warning(
                    f'Duplicate core initialAssignment target "{symbol}".',
                    "dropped",
                )
            )
            continue
        if symbol not in core_model_ids:
            warnings.append(
                _warning(
                    f'Core initialAssignment symbol "{symbol}" does not '
                    "identify a Model element.",
                    "dropped",
                )
            )
            continue
        if _first_child(assignment, "math", MATHML_NAMESPACE) is None:
            warnings.append(
                _warning(
                    f'Core initialAssignment for "{symbol}" is missing its '
                    "required MathML math child.",
                    "dropped",
                )
            )
            continue
        initial_assignment_symbols.add(symbol)

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
            if instance.type_id in types:
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
                or species_id in initial_assignment_symbols
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
            and not compartment_matches_type(species_compartment, type_compartment)
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
                or species_id in initial_assignment_symbols
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
        feature_elements: List[Tuple[Any, str]] = []
        for child in list(feature_list) if feature_list is not None else []:
            if _local_name(child.tag) == "speciesFeature":
                feature_elements.append((child, ""))
            elif _local_name(child.tag) == "subListOfSpeciesFeatures":
                inherited_component = _attribute(child, "component")
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
                nested_features = _children(child, "speciesFeature", namespace)
                feature_elements.extend(
                    (feature, inherited_component) for feature in nested_features
                )
        seen_feature_occurrences = set()
        # SpeciesFeature and SubListOfSpeciesFeatures ids share the Species
        # object's local id scope, which includes the core species id.
        seen_feature_ids = {species_id}
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
        for feature, inherited_component in feature_elements:
            feature_id = _attribute(feature, "speciesFeatureType")
            component_token = _attribute(feature, "component") or inherited_component
            feature_object_id = _attribute(feature, "id")
            if feature_object_id:
                species_feature_ids_by_species.setdefault(species_id, set()).add(
                    feature_object_id
                )
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
            if feature_id in ambiguous_feature_ids and not component_token:
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
                component_token,
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
            if feature_id in ambiguous_feature_ids and component_token:
                scoped_definitions = [
                    species_type.feature_definitions[feature_id]
                    for species_type in types.values()
                    if feature_id in species_type.feature_definitions
                ]
                if scoped_definitions:
                    known = (
                        max(
                            types[owner_id].feature_occurs.get(feature_id, 1)
                            for owner_id in types
                            if feature_id in types[owner_id].feature_definitions
                        ),
                        {
                            value_id
                            for _name, labels in scoped_definitions
                            for value_id in labels
                        },
                    )
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
        seen_outward_ids = set()
        for outward in _children(outward_list, "outwardBindingSite", namespace):
            outward_id = _attribute(outward, "id")
            if outward_id:
                if outward_id in seen_outward_ids:
                    warnings.append(
                        _warning(
                            f'Duplicate Multi outwardBindingSite id "{outward_id}" '
                            f'in species "{species_id}".',
                            "dropped",
                        )
                    )
                seen_outward_ids.add(outward_id)
        pattern = _species_pattern_from_multi(
            species,
            type_id,
            types,
            namespace,
            structure_warnings,
            compartment_references=compartment_references,
            compartment_types=compartment_types,
            species_compartment=(
                species_compartment if package_valid and not namespace_violation else ""
            ),
            initialized_by_assignment=species_id in initial_assignment_symbols,
        )
        if pattern:
            species_patterns[species_id] = pattern
            if (
                _attribute(species, "initialAmount") != ""
                or _attribute(species, "initialConcentration") != ""
                or species_id in initial_assignment_symbols
            ):
                seed_patterns.append((species_id, pattern))

    # A bindingSiteSpeciesType may also be used as a top-level SpeciesType.
    # It is atomic in Multi, but still needs a BNGL molecule declaration when
    # it is instantiated directly as a core species.
    for type_id in set(species_type_by_species.values()):
        species_type = types.get(type_id)
        if species_type is None or not species_type.is_binding_site:
            continue
        flat = _flatten_type(
            type_id,
            types,
            structure_warnings,
            compartment_references=compartment_references,
            compartment_types=compartment_types,
        )
        if flat.molecules:
            rendered = _render_flat_type(flat, show_states=True)
            type_patterns[type_id] = rendered
            if rendered not in molecule_types:
                molecule_types.append(rendered)

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
            reference_id = _attribute(reference, "id")
            if reference_id and reference_id in reference_ids:
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
        mapping_ids = set()
        for product_index, product in enumerate(
            _children(product_parent, "speciesReference")
        ):
            raw_product_id = _attribute(product, "id")
            product_id = raw_product_id or f"product_{product_index + 1}"
            if raw_product_id and (
                raw_product_id in product_reference_ids
                or raw_product_id in reference_ids
            ):
                warnings.append(
                    _warning(
                        f'Duplicate product speciesReference id "{product_id}" in '
                        f'reaction "{reaction_id}".',
                        "dropped",
                    )
                )
            if raw_product_id:
                product_reference_ids.add(raw_product_id)
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
            mapped_product_locations = set()
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
                reactant_locations = component_aliases.get(reactant_type, {}).get(
                    reactant_component, []
                )
                if len(reactant_locations) != 1:
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" cannot '
                            f'resolve reactant component "{reactant_component}" '
                            f'unambiguously ({len(reactant_locations)} matches).',
                            "dropped",
                        )
                    )
                    continue
                product_locations = component_aliases.get(product_type, {}).get(
                    product_component, []
                )
                if len(product_locations) != 1:
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" cannot '
                            f'resolve product component "{product_component}" '
                            f'unambiguously ({len(product_locations)} matches).',
                            "dropped",
                        )
                    )
                    continue
                product_location = product_locations[0]
                if product_location in mapped_product_locations:
                    warnings.append(
                        _warning(
                            f'Multi product map in reaction "{reaction_id}" maps '
                            f'product component "{product_component}" more than once.',
                            "dropped",
                        )
                    )
                    continue
                mapped_product_locations.add(product_location)
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
            referenced_species = ""
            referenced_reference = None
            if species_reference:
                for reference in (
                    *_children(
                        _first_child(reaction, "listOfReactants"),
                        "speciesReference",
                    ),
                    *_children(
                        _first_child(reaction, "listOfProducts"),
                        "speciesReference",
                    ),
                    *_children(
                        _first_child(reaction, "listOfModifiers"),
                        "modifierSpeciesReference",
                    ),
                ):
                    if _attribute(reference, "id") == species_reference:
                        referenced_species = _attribute(reference, "species")
                        referenced_reference = reference
                        break
            content_is_referenced_feature = (
                bool(referenced_species)
                and content in species_feature_ids_by_species.get(
                    referenced_species, set()
                )
            )
            content_is_referenced_species = (
                bool(referenced_species) and content == referenced_species
            )
            if (
                species_reference
                and not content_is_referenced_species
                and not content_is_referenced_feature
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
            if (
                species_reference
                and representation not in {"sum", "numericValue"}
                and referenced_reference is not None
            ):
                if content_is_referenced_feature:
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" MathML ci references '
                            f'speciesFeature "{content}" through '
                            "multi:speciesReference; feature-count rate laws "
                            "are not representable by the BNGL writer.",
                            "dropped",
                        )
                    )
                elif _namespaced_attribute(
                    referenced_reference, namespace, "compartmentReference"
                ):
                    warnings.append(
                        _warning(
                            f'Reaction "{reaction_id}" MathML ci uses '
                            f'multi:speciesReference="{species_reference}" '
                            "for a sub-compartment species reference; the "
                            "reference-specific amount is not representable by "
                            "the BNGL rate-law contract.",
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
        and (species_patterns or type_patterns)
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
