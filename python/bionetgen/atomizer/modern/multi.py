"""Conservative SBML Multi-package extraction for the modern atomizer.

The Playground implementation reconstructs the canonical, single-level Multi
package idiom but deliberately does not flatten the deeper Simmune hierarchy.
This module mirrors that boundary: extracted structures are retained as
commented diagnostics and are not injected into the simulated BNGL network.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

from .structures import read_from_string
from .types import SBMLImportWarning, SBMLMultiComponentMap

MULTI_V1_NAMESPACE = "http://www.sbml.org/sbml/level3/version1/multi/version1"


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


@dataclass
class _FlatMolecule:
    name: str
    aliases: set = field(default_factory=set)
    components: List[_FlatComponent] = field(default_factory=list)


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


def _feature_defs(species_type: _SpeciesType) -> List[Tuple[str, str, List[str]]]:
    return [
        (feature_id, feature_name, list(labels.values()))
        for feature_id, (
            feature_name,
            labels,
        ) in species_type.feature_definitions.items()
    ]


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
    children = [
        instance
        for instance in species_type.instances
        if instance.type_id in types and not types[instance.type_id].is_binding_site
    ]
    flat = _FlatType()
    if not children:
        molecule = _FlatMolecule(
            name=_clean_pattern_name(species_type.name, species_type.id),
            aliases={species_type.id, species_type.name, _clean(species_type.name)},
        )
        for feature_id, feature_name, values in _feature_defs(species_type):
            molecule.components.append(
                _FlatComponent(
                    label=_clean(feature_name),
                    aliases={feature_id, feature_name, _clean(feature_name)},
                    states=[_clean(value) for value in values],
                    feature_ids={feature_id},
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
            for feature_id, feature_name, values in _feature_defs(target):
                aliases.update({feature_id, feature_name, _clean(feature_name)})
                feature_ids.add(feature_id)
                states.extend(_clean(value) for value in values)
            molecule.components.append(
                _FlatComponent(
                    label=label,
                    aliases={alias for alias in aliases if alias},
                    states=list(dict.fromkeys(states)),
                    feature_ids=feature_ids,
                )
            )
        flat.molecules.append(molecule)
        _apply_component_indexes(species_type, flat)
        return flat

    for instance in children:
        child = _flatten_type(instance.type_id, types, warnings, stack + (type_id,))
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
        rendered_molecules.append(f"{molecule.name}({','.join(components)})")
    return ".".join(rendered_molecules)


def _source_pattern_is_usable(source: str, flat: _FlatType) -> bool:
    if not source or not flat.molecules:
        return False
    try:
        parsed = read_from_string(source)
    except (TypeError, ValueError):
        return False
    if len(parsed.molecules) != len(flat.molecules):
        return False
    return all(
        parsed_molecule.name == flat_molecule.name
        for parsed_molecule, flat_molecule in zip(parsed.molecules, flat.molecules)
    )


def _species_pattern_from_multi(
    species: Any,
    type_id: str,
    types: Dict[str, _SpeciesType],
    namespace: str,
    warnings: List[SBMLImportWarning],
) -> Optional[str]:
    flat = _flatten_type(type_id, types, warnings)
    if not flat.molecules:
        return None
    source = str(_attribute(species, "name", "") or "").strip()
    if _source_pattern_is_usable(source, flat):
        return source

    for feature in _children(
        _first_child(species, "listOfSpeciesFeatures", namespace),
        "speciesFeature",
        namespace,
    ):
        feature_id = _attribute(feature, "speciesFeatureType")
        component_token = _attribute(feature, "component")
        try:
            occur = int(_attribute(feature, "occur", "1"))
        except ValueError:
            occur = 1
        if occur != 1:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" has occur="{occur}"; '
                    "repeated feature occurrences are not representable as one "
                    "BNGL component.",
                    "dropped",
                )
            )
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
                elif not component_token and (
                    feature_id in component.feature_ids
                    or feature_id in component.aliases
                ):
                    targets.append(component)
        if not targets:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" on species '
                    f'"{_attribute(species, "id")}" has no resolvable component.',
                    "dropped",
                )
            )
            continue
        if len(values) == 1:
            for target in targets:
                target.active_state = values[0]
        elif len(values) > 1:
            warnings.append(
                _warning(
                    f'Multi speciesFeature "{feature_id}" has multiple values; '
                    "a single BNGL state cannot represent this value set.",
                    "dropped",
                )
            )

    for outward in _children(
        _first_child(species, "listOfOutwardBindingSites", namespace),
        "outwardBindingSite",
        namespace,
    ):
        component_token = _attribute(outward, "component")
        status = _attribute(outward, "bindingStatus", "either").lower()
        if status not in {"unbound", "bound", "either"}:
            warnings.append(
                _warning(
                    f'Unsupported Multi bindingStatus "{status}" on species '
                    f'"{_attribute(species, "id")}".',
                    "dropped",
                )
            )
            continue
        for molecule in flat.molecules:
            for component in molecule.components:
                if component_token in component.aliases:
                    component.binding_status = status
    return _render_flat_type(flat, show_states=False)


def _parse_multi_package_complete(document: Union[str, Any]) -> MultiParseResult:
    """Parse SBML Multi v1 and retain executable BNGL reconstruction metadata."""

    source = document if isinstance(document, str) else None
    root = _as_root(document)
    if root is None:
        return MultiParseResult()
    namespace = _multi_namespace(root, source)
    if namespace is None:
        return MultiParseResult()

    warnings: List[SBMLImportWarning] = []
    model = _model_element(root)
    required = _namespaced_attribute(root, namespace, "required")
    package_valid = namespace == MULTI_V1_NAMESPACE and required == "true"
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
    elif required != "true":
        warnings.append(
            _warning(
                'SBML Multi has multi:required="false"; executable reconstruction '
                "is disabled for a package the core model may ignore.",
                "dropped",
            )
        )

    namespace_violation = False
    for element in root.iter():
        if _namespace(element.tag) == namespace:
            for key in getattr(element, "attrib", {}):
                if _namespace(key) != namespace:
                    namespace_violation = True
                    warnings.append(
                        _warning(
                            f'Multi attribute "{_local_name(key)}" on '
                            f"{_local_name(element.tag)} must use the Multi "
                            "namespace.",
                            "dropped",
                        )
                    )
        if _local_name(element.tag) not in {
            "species",
            "compartment",
            "speciesReference",
            "modifierSpeciesReference",
        }:
            continue
        for key in getattr(element, "attrib", {}):
            local = _local_name(key)
            if (
                local
                in {
                    "speciesType",
                    "compartmentType",
                    "isType",
                    "compartmentReference",
                }
                and _namespace(key) != namespace
            ):
                warnings.append(
                    _warning(
                        f'Multi attribute "{local}" on {_local_name(element.tag)} '
                        "must use the Multi namespace.",
                        "dropped",
                    )
                )

    list_types = _first_child(model, "listOfSpeciesTypes", namespace)
    if list_types is None:
        return MultiParseResult(
            present=True,
            warnings=[
                _warning("SBML Multi package has no listOfSpeciesTypes.", "dropped"),
                _warning(
                    "SBML Multi package has no referenced top-level species type.",
                    "info",
                ),
            ]
            + warnings,
        )

    types: Dict[str, _SpeciesType] = {}
    binding_site_ids = set()
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
        is_binding_site = _local_name(item.tag) == "bindingSiteSpeciesType"
        if is_binding_site:
            binding_site_ids.add(type_id)
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
            value_labels: Dict[str, str] = {}
            possible = _first_child(
                feature, "listOfPossibleSpeciesFeatureValues", namespace
            )
            for value in _children(possible, "possibleSpeciesFeatureValue", namespace):
                value_id = _attribute(value, "id")
                if value_id:
                    value_labels[value_id] = _clean(
                        _attribute(value, "name") or value_id
                    )
            feature_name = _clean(_attribute(feature, "name") or feature_id)
            species_type.features.append((feature_name, list(value_labels.values())))
            species_type.feature_definitions[feature_id] = (
                feature_name,
                value_labels,
            )
            try:
                occur = int(_attribute(feature, "occur", "1"))
            except ValueError:
                occur = 1
            if occur != 1:
                warnings.append(
                    _warning(
                        f'Multi speciesFeatureType "{feature_id}" has occur="{occur}"; '
                        "BNGL reconstruction supports only one occurrence.",
                        "dropped",
                    )
                )

        instance_list = _first_child(item, "listOfSpeciesTypeInstances", namespace)
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
            species_type.instances.append(
                _Instance(
                    id=instance_id,
                    type_id=instance_type,
                    name=_clean(_attribute(instance, "name") or instance_id),
                    compartment_reference=_attribute(instance, "compartmentReference"),
                )
            )

        index_list = _first_child(item, "listOfSpeciesTypeComponentIndexes", namespace)
        for component in _children(index_list, "speciesTypeComponentIndex", namespace):
            component_id = _attribute(component, "id")
            component_ref = _attribute(component, "component")
            if component_id and component_ref:
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
        for bond in _children(bond_list, "inSpeciesTypeBond", namespace):
            site1 = _attribute(bond, "bindingSite1")
            site2 = _attribute(bond, "bindingSite2")
            if site1 and site2:
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
    compartments = _first_child(model, "listOfCompartments")
    for compartment in _children(compartments, "compartment"):
        compartment_id = _attribute(compartment, "id")
        reference_list = _first_child(
            compartment, "listOfCompartmentReferences", namespace
        )
        if not compartment_id or reference_list is None:
            continue
        references: Dict[str, str] = {}
        for reference in _children(reference_list, "compartmentReference", namespace):
            reference_id = _attribute(reference, "id")
            reference_compartment = _attribute(reference, "compartment")
            if reference_id and reference_compartment:
                references[reference_id] = reference_compartment
        if references:
            compartment_references[compartment_id] = references

    type_patterns: Dict[str, str] = {}
    component_aliases: Dict[str, Dict[str, List[Tuple[str, int, int]]]] = {}
    molecule_types: List[str] = []
    complex_patterns: List[MultiComplexPattern] = []
    structure_warnings: List[SBMLImportWarning] = []
    for type_id, species_type in types.items():
        if species_type.is_binding_site:
            continue
        flat = _flatten_type(type_id, types, structure_warnings)
        if not flat.molecules:
            continue
        component_aliases[type_id] = _flat_component_aliases(flat)
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
    species_parent = _first_child(model, "listOfSpecies")
    for species in _children(species_parent, "species"):
        species_id = _attribute(species, "id")
        type_id = _namespaced_attribute(species, namespace, "speciesType")
        if not type_id:
            # Legacy fixtures are retained as parse-only compatibility, but are
            # never considered executable SBML Multi.
            type_id = _attribute(species, "speciesType")
        if not species_id or type_id not in types:
            continue
        pattern = _species_pattern_from_multi(
            species, type_id, types, namespace, structure_warnings
        )
        if pattern:
            species_patterns[species_id] = pattern
            if (
                _attribute(species, "initialAmount") != ""
                or _attribute(species, "initialConcentration") != ""
            ):
                seed_patterns.append((species_id, pattern))

    reaction_product_maps: Dict[str, Dict[str, List[Any]]] = {}
    reaction_parent = _first_child(model, "listOfReactions")
    for reaction in (list(reaction_parent) if reaction_parent is not None else []):
        if _local_name(reaction.tag) not in {"reaction", "intraSpeciesReaction"}:
            continue
        reaction_id = _attribute(reaction, "id")
        if not reaction_id:
            continue
        product_parent = _first_child(reaction, "listOfProducts")
        for product_index, product in enumerate(
            _children(product_parent, "speciesReference")
        ):
            product_id = _attribute(product, "id") or f"product_{product_index + 1}"
            map_parent = _first_child(
                product, "listOfSpeciesTypeComponentMapsInProduct"
            )
            maps: List[Any] = []
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
                maps.append(
                    SBMLMultiComponentMap(
                        reactant=reactant,
                        reactant_component=reactant_component,
                        product_component=product_component,
                        id=_attribute(mapping, "id") or None,
                        name=_attribute(mapping, "name"),
                    )
                )
            if maps:
                reaction_product_maps.setdefault(reaction_id, {})[product_id] = maps

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
        and not namespace_violation
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
