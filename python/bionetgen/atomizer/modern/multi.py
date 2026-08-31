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
from typing import Any, Dict, List, Optional, Tuple, Union


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _attribute(element: Any, name: str, default: str = "") -> str:
    for key, value in getattr(element, "attrib", {}).items():
        if key == name or _local_name(key) == name:
            return str(value)
    return default


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


@dataclass
class _SpeciesType:
    id: str
    name: str
    features: List[Tuple[str, List[str]]] = field(default_factory=list)
    instances: List[_Instance] = field(default_factory=list)
    component_indexes: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    bonds: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class MultiParseResult:
    present: bool = False
    deep: bool = False
    bngl_molecule_types: List[str] = field(default_factory=list)
    complex_patterns: List[Tuple[str, str]] = field(default_factory=list)
    seed_patterns: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)


def _warning(message: str, severity: str = "approximated") -> Dict[str, Any]:
    return {
        "category": "package:multi",
        "message": message,
        "count": 1,
        "severity": severity,
    }


def _as_root(document: Union[str, Any]) -> Any:
    if isinstance(document, str):
        if not document.strip():
            return None
        return ET.fromstring(document)
    return document


def _multi_namespace(root: Any) -> Optional[str]:
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


def parse_multi_package(document: Union[str, Any]) -> MultiParseResult:
    """Extract canonical Multi-package molecule/complex references."""

    root = _as_root(document)
    if root is None:
        return MultiParseResult()
    namespace = _multi_namespace(root)
    if namespace is None:
        return MultiParseResult()

    model = _model_element(root)
    list_types = _first_child(model, "listOfSpeciesTypes", namespace)
    if list_types is None:
        return MultiParseResult(
            present=True,
            warnings=[
                _warning(
                    "SBML Multi package is present but no listOfSpeciesTypes was found.",
                    "info",
                )
            ],
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
            possible = _first_child(
                feature, "listOfPossibleSpeciesFeatureValues", namespace
            )
            for value in _children(possible, "possibleSpeciesFeatureValue", namespace):
                label = _clean(_attribute(value, "name") or _attribute(value, "id"))
                if label:
                    values.append(label)
            feature_name = _clean(
                _attribute(feature, "name") or _attribute(feature, "id")
            )
            if feature_name:
                species_type.features.append((feature_name, values))

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
        return MultiParseResult(
            present=True,
            warnings=[
                _warning(
                    "SBML Multi package has species types but no referenced top-level species type.",
                    "info",
                )
            ],
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
            warnings=[
                _warning(
                    "SBML Multi package uses a multi-layer hierarchy; molecule "
                    "boundaries cannot be inferred safely, so complexes were not "
                    f"reconstructed. Molecule names: {', '.join(names[:20])}."
                )
            ],
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

    complex_patterns: List[Tuple[str, str]] = []
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
        complex_patterns.append((type_id, ".".join(molecules)))

    warnings = []
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
    return MultiParseResult(
        present=True,
        bngl_molecule_types=molecule_types,
        complex_patterns=complex_patterns,
        seed_patterns=[],
        warnings=warnings,
    )


__all__ = ["MultiParseResult", "parse_multi_package"]
