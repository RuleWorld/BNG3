"""Structured BNGL patterns used by the Playground atomizer port.

The public TypeScript implementation keeps a deliberately small object model:
Species contain Molecules, Molecules contain Components, and Components carry
states and bonds.  This module preserves that separation while making IDs
deterministic, which is useful for Python callers and reproducible output.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple, Union

Bond = Union[str, int]


def _bond_number(value: Bond) -> Optional[int]:
    if value in ("+", "?"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Component:
    """A BNGL binding or modification site."""

    def __init__(
        self,
        name: str,
        idx: str = "",
        bonds: Optional[Iterable[Bond]] = None,
        states: Optional[Iterable[str]] = None,
    ) -> None:
        self.name = name
        self.idx = idx or name
        self.states = list(states or [])
        self.bonds = list(bonds or [])
        self.active_state = ""

    def copy(self) -> "Component":
        result = Component(
            self.name, self.idx, copy.deepcopy(self.bonds), copy.deepcopy(self.states)
        )
        result.active_state = self.active_state
        return result

    def add_state(self, state: str, update: bool = True) -> None:
        if state not in self.states:
            self.states.append(state)
        if update:
            self.set_active_state(state)
        if "0" not in self.states:
            self.states.append("0")

    def add_states(self, states: Iterable[str], update: bool = True) -> None:
        for state in states:
            if state not in self.states:
                self.add_state(state, update)

    def add_bond(self, bond: Bond) -> None:
        if all(str(existing) != str(bond) for existing in self.bonds):
            self.bonds.append(bond)

    def set_active_state(self, state: str) -> bool:
        if state:
            if state not in self.states:
                self.states.append(state)
            self.active_state = state
        else:
            self.active_state = ""
        return True

    def get_name(self) -> str:
        return self.name

    def has_wildcard_bonds(self) -> bool:
        return "+" in self.bonds or "?" in self.bonds

    def reset(self) -> None:
        self.bonds = []
        if "0" in self.states:
            self.active_state = "0"

    def get_rule_str(self) -> str:
        result = self.name
        if self.bonds:
            result += "!" + "!".join(str(bond) for bond in self.bonds)
        if self.active_state:
            result += "~" + self.active_state
        return result

    def get_total_str(self) -> str:
        return self.name + "~" + "~".join(self.states)

    def str2(self) -> str:
        result = self.name
        if self.bonds:
            result += "!" + "!".join(str(bond) for bond in self.bonds)
        if self.states:
            result += "~" + "~".join(self.states)
        if result and result[0].isdigit():
            result = "_" + result
        return result

    def __str__(self) -> str:
        return self.get_rule_str()

    def hash(self) -> str:
        return self.name


class Molecule:
    """A molecule instance or molecule type."""

    def __init__(self, name: str, idx: str = "") -> None:
        self.name = name
        self.idx = idx or name
        self.components: List[Component] = []
        self.compartment = ""
        self.true_name = ""
        self.unique_identifier = 0

    def copy(self) -> "Molecule":
        result = Molecule(self.name, self.idx)
        result.compartment = self.compartment
        result.true_name = self.true_name
        result.unique_identifier = self.unique_identifier
        result.components = [component.copy() for component in self.components]
        return result

    def add_component(self, component: Component, overlap: bool = False) -> None:
        if not overlap:
            self.components.append(component)
        else:
            existing = self.get_component(component.name)
            if existing is None:
                self.components.append(component)
            else:
                existing.add_states(component.states)
        self.components.sort(key=lambda item: item.name)

    def set_compartment(self, compartment: str) -> None:
        self.compartment = compartment

    def get_component_by_id(self, idx: str) -> Optional[Component]:
        return next(
            (component for component in self.components if component.idx == idx), None
        )

    def get_bond_numbers(self) -> List[int]:
        return [
            number
            for component in self.components
            for bond in component.bonds
            if (number := _bond_number(bond)) is not None
        ]

    def get_component(self, component_name: str) -> Optional[Component]:
        return next(
            (
                component
                for component in self.components
                if component.name == component_name
            ),
            None,
        )

    def remove_component(self, component_name: str) -> None:
        self.components = [
            component
            for component in self.components
            if component.name != component_name
        ]

    def remove_components(self, components: Iterable[Component]) -> None:
        for element in components:
            if element in self.components:
                self.components.remove(element)

    def add_bond(self, component_name: str, bond_name: int) -> None:
        while bond_name in self.get_bond_numbers():
            bond_name += 1
        component = self.get_component(component_name)
        if component is not None:
            component.add_bond(bond_name)

    def get_component_with_bonds(self) -> List[Component]:
        return [component for component in self.components if component.bonds]

    def contains(self, component_name: str) -> bool:
        return self.get_component(component_name) is not None

    def has_wildcard_bonds(self) -> bool:
        return any(component.has_wildcard_bonds() for component in self.components)

    def extend(self, molecule: "Molecule") -> None:
        for incoming in molecule.components:
            existing = self.get_component(incoming.name)
            if existing is None:
                self.components.append(incoming.copy())
            else:
                for bond in incoming.bonds:
                    existing.add_bond(bond)
                existing.add_states(incoming.states)
        self.components.sort(key=lambda item: item.name)

    def update(self, molecule: "Molecule") -> None:
        names = {component.name for component in self.components}
        for incoming in molecule.components:
            if incoming.name not in names:
                self.components.append(incoming.copy())
                names.add(incoming.name)
        self.components.sort(key=lambda item: item.name)

    def reset(self) -> None:
        for component in self.components:
            component.reset()

    def distance(self, other: "Molecule") -> int:
        distance = 10000 if self.name != other.name else 0
        for left, right in zip_longest(self.components, other.components):
            if left is None or right is None:
                distance += 1
                continue
            if left.bonds != right.bonds:
                distance += 1
            if left.active_state != right.active_state:
                distance += 1
        return distance

    def compare(self, other: "Molecule") -> None:
        self.components.sort(key=lambda item: item.name)
        other.components.sort(key=lambda item: item.name)
        for left, right in zip(self.components, other.components):
            if left.active_state != right.active_state:
                left.active_state = ""

    def to_string(self, full: bool = False) -> str:
        self.components.sort(key=lambda item: item.name)
        interesting = (
            self.components
            if full
            else [
                component
                for component in self.components
                if component.bonds or component.active_state
            ]
        )
        result = self.name
        if interesting:
            result += "(" + ",".join(str(component) for component in interesting) + ")"
        elif full and self.components:
            result += (
                "(" + ",".join(str(component) for component in self.components) + ")"
            )
        if self.compartment:
            result += "@" + self.compartment
        return result

    def str2(self) -> str:
        self.components.sort(key=lambda item: item.name)
        result = self.name.replace("-", "_")
        if result and result[0].isdigit():
            result = "m__" + result
        if self.components:
            result += (
                "(" + ",".join(component.str2() for component in self.components) + ")"
            )
        return result

    def str3(self) -> str:
        return (
            self.name + "(" + self.components[0].name + ")"
            if self.components
            else self.name + "()"
        )

    def __str__(self) -> str:
        return self.to_string()


def zip_longest(left: Sequence[Component], right: Sequence[Component]):
    length = max(len(left), len(right))
    for index in range(length):
        yield (
            left[index] if index < len(left) else None,
            right[index] if index < len(right) else None,
        )


class Species:
    """A connected or disconnected BNGL species pattern."""

    def __init__(self) -> None:
        self.molecules: List[Molecule] = []
        self.bond_numbers: List[int] = []
        self.bonds: List[Tuple[str, str]] = []
        self.identifier = 0
        self.idx = ""

    def get_bond_numbers(self) -> List[int]:
        return [0] + [
            number
            for molecule in self.molecules
            for number in molecule.get_bond_numbers()
        ]

    def copy(self) -> "Species":
        result = Species()
        result.bond_numbers = copy.deepcopy(self.bond_numbers)
        result.bonds = copy.deepcopy(self.bonds)
        result.identifier = self.identifier
        result.idx = self.idx
        result.molecules = [molecule.copy() for molecule in self.molecules]
        return result

    def get_molecule_by_id(self, idx: str) -> Optional[Molecule]:
        return next(
            (molecule for molecule in self.molecules if molecule.idx == idx), None
        )

    def add_molecule(
        self, molecule: Molecule, concatenate: bool = False, iteration: int = 1
    ) -> None:
        if not concatenate:
            self.molecules.append(molecule)
            return
        count = 0
        for existing in self.molecules:
            if existing.name == molecule.name:
                count += 1
                if count == iteration:
                    existing.extend(molecule)
                    return
        self.molecules.append(molecule)

    def add_compartment(self, tags: str) -> None:
        for molecule in self.molecules:
            if not molecule.compartment:
                molecule.set_compartment(tags)

    def delete_molecule(self, molecule_name: str) -> None:
        dead = next(
            (molecule for molecule in self.molecules if molecule.name == molecule_name),
            None,
        )
        if dead is None:
            return
        removed = set(dead.get_bond_numbers())
        self.molecules.remove(dead)
        for molecule in self.molecules:
            for component in molecule.components:
                component.bonds = [
                    bond
                    for bond in component.bonds
                    if _bond_number(bond) not in removed
                ]

    def get_molecule(self, molecule_name: str) -> Optional[Molecule]:
        return next(
            (molecule for molecule in self.molecules if molecule.name == molecule_name),
            None,
        )

    def get_size(self) -> int:
        return len(self.molecules)

    def get_molecule_names(self) -> List[str]:
        return [molecule.name for molecule in self.molecules]

    def contains(self, molecule_name: str) -> bool:
        return any(molecule.name == molecule_name for molecule in self.molecules)

    def has_wildcard_bonds(self) -> bool:
        return any(molecule.has_wildcard_bonds() for molecule in self.molecules)

    def extract_atomic_patterns(
        self,
        action: str,
        site1: str,
        site2: str,
        differentiate_dimers: bool = False,
    ) -> "AtomicPatternResult":
        """Extract component and bonded patterns for rule-center analysis."""

        atomic_patterns: dict[str, Species] = {}
        bonded_patterns: dict[str, Species] = {}
        reaction_center: List[Species] = []
        context: List[Species] = []

        name_counter = Counter(molecule.name for molecule in self.molecules)
        name_counter_copy = Counter(molecule.name for molecule in self.molecules)
        self.sort()

        for molecule in self.molecules:
            molecule_counter = (
                name_counter[molecule.name] - name_counter_copy[molecule.name]
            )
            name_counter_copy[molecule.name] -= 1
            mol_name = (
                f"{molecule.name}%{molecule_counter}"
                if differentiate_dimers
                else molecule.name
            )

            for component in molecule.components:
                if component.active_state != "":
                    species_structure = Species()
                    species_structure.bonds = list(self.bonds)
                    molecule_structure = Molecule(mol_name, molecule.idx)
                    component_structure = Component(component.name, component.idx)
                    component_structure.add_state(component.active_state)
                    component_structure.active_state = component.active_state
                    molecule_structure.add_component(component_structure)
                    species_structure.add_molecule(molecule_structure)

                    if (
                        component_structure.idx in {site1, site2}
                        and action == "StateChange"
                    ):
                        reaction_center.append(species_structure)
                    else:
                        context.append(species_structure)
                    atomic_patterns[str(species_structure)] = species_structure

                species_structure = Species()
                species_structure.bonds = list(self.bonds)
                molecule_structure = Molecule(mol_name, molecule.idx)
                component_structure = Component(component.name, component.idx)
                molecule_structure.add_component(component_structure)
                species_structure.add_molecule(molecule_structure)

                if not component.bonds:
                    atomic_patterns[str(species_structure)] = species_structure
                else:
                    bond_key = str(component.bonds[0])
                    component_structure.add_bond("+" if bond_key == "+" else 1)
                    if bond_key not in bonded_patterns:
                        bonded_patterns[bond_key] = species_structure
                    elif bond_key != "+" or not bonded_patterns[bond_key].molecules:
                        bonded_patterns[bond_key].add_molecule(molecule_structure)

                if (
                    component_structure.idx in {site1, site2}
                    and action != "StateChange"
                ):
                    reaction_center.append(species_structure)
                elif component.bonds or component.active_state == "":
                    context.append(species_structure)

        atomic_patterns.update(
            (str(value), value) for value in bonded_patterns.values()
        )
        reaction_center_strings = [
            str(value) for value in reaction_center if str(value) in atomic_patterns
        ]
        context_strings = [
            str(value) for value in context if str(value) in atomic_patterns
        ]
        return AtomicPatternResult(
            atomic_patterns=atomic_patterns,
            reaction_center=reaction_center_strings,
            context=context_strings,
        )

    def list_of_bonds(
        self, name_dict: Mapping[str, str]
    ) -> Dict[str, Dict[str, List[Tuple[str, str]]]]:
        """Return bonds indexed by molecule and component display names."""

        result: Dict[str, Dict[str, List[Tuple[str, str]]]] = {}
        for first, second in self.bonds:
            molecule1 = re.sub(r"_C[^_]*$", "", first)
            molecule2 = re.sub(r"_C[^_]*$", "", second)
            molecule1_name = name_dict.get(molecule1, molecule1)
            molecule2_name = name_dict.get(molecule2, molecule2)
            first_name = name_dict.get(first, first)
            second_name = name_dict.get(second, second)
            result.setdefault(molecule1_name, {})[first_name] = [
                (molecule2_name, second_name)
            ]
            result.setdefault(molecule2_name, {})[second_name] = [
                (molecule1_name, first_name)
            ]
        return result

    def extend(self, species: "Species", update: bool = True) -> None:
        if len(self.molecules) == len(species.molecules):
            left = sorted(
                self.molecules,
                key=lambda molecule: (len(molecule.components), molecule.name),
            )
            right = sorted(
                species.molecules,
                key=lambda molecule: (len(molecule.components), molecule.name),
            )
            for current, incoming in zip(left, right):
                incoming_counts = Counter(
                    component.name for component in incoming.components
                )
                current_counts = Counter(
                    component.name for component in current.components
                )
                existing = {}
                for component in current.components:
                    existing.setdefault(component.name, component)
                for component in incoming.components:
                    if current_counts[component.name] < incoming_counts[component.name]:
                        copied = component.copy()
                        current.components.append(copied)
                        current_counts[component.name] += 1
                        existing.setdefault(component.name, copied)
                    else:
                        target = existing.get(component.name)
                        if target is not None:
                            target.add_states(component.states, update)
            return

        for incoming in species.molecules:
            candidates = [
                molecule
                for molecule in self.molecules
                if molecule.name == incoming.name
            ]
            if not candidates:
                self.add_molecule(incoming.copy())
                continue
            target = max(
                candidates,
                key=lambda molecule: self._sequence_match_ratio(
                    [
                        str(bond)
                        for component in molecule.components
                        for bond in component.bonds
                    ],
                    [
                        str(bond)
                        for component in incoming.components
                        for bond in component.bonds
                    ],
                ),
            )
            for component in incoming.components:
                existing = target.get_component(component.name)
                if existing is None:
                    target.add_component(component.copy(), update)
                else:
                    existing.add_states(component.states, update)

    @staticmethod
    def _sequence_match_ratio(
        left: Sequence[Union[str, int]], right: Sequence[Union[str, int]]
    ) -> float:
        """Match the Playground's inclusion-based molecule similarity score."""

        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        matches = sum(1 for item in left if item in right)
        return (2 * matches) / (len(left) + len(right))

    def update_bonds(self, bond_numbers: Iterable[int]) -> None:
        offset = max(list(bond_numbers) or [0]) + 1
        for molecule in self.molecules:
            for component in molecule.components:
                component.bonds = [
                    bond if bond in ("+", "?") else _bond_number(bond) + offset
                    for bond in component.bonds
                ]

    def delete_bond(self, molecule_pair: Iterable[str]) -> None:
        names = list(molecule_pair)
        for molecule in self.molecules:
            if molecule.name not in names:
                continue
            partners = list(names)
            partners.remove(molecule.name)
            partner_names = {str(partner).lower() for partner in partners}
            for component in molecule.components:
                if component.name.lower() in partner_names:
                    component.bonds = []

    def append(self, species: "Species") -> None:
        incoming = species.copy()
        incoming.update_bonds(self.get_bond_numbers())
        self.molecules.extend(incoming.molecules)

    def sort(self) -> None:
        def key(molecule: Molecule):
            bonds = molecule.get_bond_numbers()
            active = sum(
                1
                for component in molecule.components
                if component.active_state not in ("", "0")
            )
            return (
                -len(molecule.components),
                min(bonds or [999]),
                -len(molecule.get_component_with_bonds()),
                -active,
                len(molecule.to_string()),
                molecule.to_string(),
            )

        self.molecules.sort(key=key)

    def renumber_bonds(self) -> None:
        mapping = {}
        next_bond = 1
        for molecule in self.molecules:
            for component in molecule.components:
                for index, bond in enumerate(component.bonds):
                    if bond in ("+", "?"):
                        continue
                    key = str(bond)
                    if key not in mapping:
                        mapping[key] = next_bond
                        next_bond += 1
                    component.bonds[index] = mapping[key]

    def to_string(self, full: bool = False) -> str:
        self.sort()
        return ".".join(
            molecule.to_string(full).replace("-", "_") for molecule in self.molecules
        )

    def str2(self) -> str:
        self.sort()
        return ".".join(
            molecule.str2().replace("-", "_") for molecule in self.molecules
        )

    def reset(self) -> None:
        for molecule in self.molecules:
            molecule.reset()

    def __str__(self) -> str:
        return self.to_string()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Species) and str(self) == str(other)


class Action:
    """A state, bond, or molecule operation attached to a reaction rule."""

    def __init__(self) -> None:
        self.action = ""
        self.site1 = ""
        self.site2 = ""

    def set_action(self, action: str, site1: str, site2: str = "") -> None:
        self.action = action
        self.site1 = site1
        self.site2 = site2

    setAction = set_action

    def __str__(self) -> str:
        return f"{self.action}, {self.site1}, {self.site2}"

    toString = __str__


class Rule:
    """A rule-based reaction with structured patterns and actions."""

    def __init__(self, label: str = "") -> None:
        self.label = label
        self.reactants: List[Species] = []
        self.products: List[Species] = []
        self.rates: List[str] = []
        self.bidirectional = False
        self.actions: List[Action] = []
        self.mapping: List[Tuple[str, str]] = []

    def add_reactant(self, reactant: Species) -> None:
        self.reactants.append(reactant)

    def add_product(self, product: Species) -> None:
        self.products.append(product)

    def add_reactant_list(self, reactants: Iterable[Species]) -> None:
        self.reactants.extend(reactants)

    def add_product_list(self, products: Iterable[Species]) -> None:
        self.products.extend(products)

    def add_rate(self, rate: str) -> None:
        self.rates.append(rate)

    def add_mapping(self, mapping: Tuple[str, str]) -> None:
        self.mapping.append(mapping)

    def add_mapping_list(self, mappings: Iterable[Tuple[str, str]]) -> None:
        self.mapping.extend(mappings)

    def add_action_list(self, actions: Iterable[Action]) -> None:
        self.actions.extend(actions)

    addReactant = add_reactant
    addProduct = add_product
    addReactantList = add_reactant_list
    addProductList = add_product_list
    addRate = add_rate
    addMapping = add_mapping
    addMappingList = add_mapping_list
    addActionList = add_action_list

    def __str__(self) -> str:
        label = f"{self.label}: " if self.label else ""
        arrow = " <-> " if self.bidirectional else " -> "
        return (
            label
            + " + ".join(str(item) for item in self.reactants)
            + arrow
            + " + ".join(str(item) for item in self.products)
            + " "
            + ",".join(self.rates)
        )

    toString = __str__


@dataclass
class AtomicPatternResult:
    atomic_patterns: Dict[str, Species]
    reaction_center: List[str]
    context: List[str]

    @property
    def atomicPatterns(self) -> Dict[str, Species]:
        return self.atomic_patterns

    @property
    def reactionCenter(self) -> List[str]:
        return self.reaction_center


class Databases:
    """Container for translation and annotation lookup tables."""

    def __init__(self) -> None:
        self.translator: Dict[str, Species] = {}
        self.synthesis_database: Dict[str, object] = {}
        self.catalysis_database: Dict[str, object] = {}
        self.raw_database: Dict[str, object] = {}
        self.label_dictionary: Dict[str, object] = {}
        self.synthesis_database2: Dict[str, object] = {}

    def get_raw_database(self) -> Dict[str, object]:
        return self.raw_database

    def get_label_dictionary(self) -> Dict[str, object]:
        return self.label_dictionary

    def add2_label_dictionary(self, key: Iterable[str], value: object) -> None:
        self.label_dictionary[",".join(sorted(key))] = value

    def get_translator(self) -> Dict[str, Species]:
        return self.translator

    getRawDatabase = get_raw_database
    getLabelDictionary = get_label_dictionary
    add2LabelDictionary = add2_label_dictionary
    getTranslator = get_translator


class States:
    """Simple state descriptor retained for source compatibility."""

    def __init__(self, name: str = "", idx: str = "") -> None:
        self.name = name
        self.idx = idx


def _split_top_level(value: str, separator: str) -> List[str]:
    parts: List[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == separator and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return parts


def read_from_string(pattern_str: str) -> Species:
    """Parse a BNGL pattern, including species and molecule compartments."""

    species = Species()
    working = pattern_str.strip()
    species_compartment = ""
    prefix = re.match(r"^@([^:]+)::", working)
    if prefix:
        species_compartment = prefix.group(1)
        working = working[prefix.end() :]

    for molecule_text in _split_top_level(working, "."):
        molecule_text = molecule_text.strip()
        if not molecule_text:
            continue
        match = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*)(?:\(([^)]*)\))?(?:@([A-Za-z_][A-Za-z0-9_]*))?$",
            molecule_text,
        )
        if not match:
            continue
        molecule = Molecule(match.group(1))
        molecule.set_compartment(match.group(3) or species_compartment)
        component_text = match.group(2) or ""
        if component_text.strip():
            for component_def in _split_top_level(component_text, ","):
                tokens = re.split(r"([~!])", component_def.strip())
                if not tokens or not tokens[0]:
                    continue
                component = Component(tokens[0])
                for index in range(1, len(tokens) - 1, 2):
                    separator, value = tokens[index], tokens[index + 1]
                    if separator == "~":
                        component.add_state(value)
                    elif separator == "!":
                        component.add_bond(value)
                molecule.add_component(component)
        species.add_molecule(molecule)
    return species


__all__ = [
    "Action",
    "AtomicPatternResult",
    "Bond",
    "Component",
    "Databases",
    "Molecule",
    "Rule",
    "Species",
    "States",
    "read_from_string",
]
