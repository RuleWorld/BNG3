"""Reaction analysis and species-composition inference.

This is a focused Python port of the Playground atomizer's
``atomization/core.ts``.  The dependency graph is intentionally explicit: a
species may only inherit structure from a species that has already been
resolved, and unresolved relationships remain elemental rather than being
silently guessed.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import (
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from .structures import Component, Molecule, Species, read_from_string
from .types import (
    DEFAULT_NAMING_PATTERNS,
    ReactionPattern,
    SBMLModel,
    SBMLReaction,
    SBMLSpecies,
    SCTEntry,
    SeedSpeciesEntry,
    SpeciesCompositionTable,
    get_kinetic_math,
    standardize_name,
)


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(left) + 1))
    for row, right_char in enumerate(right, 1):
        current = [row]
        for column, left_char in enumerate(left, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def similarity(left: str, right: str) -> float:
    size = max(len(left), len(right))
    return 1.0 if size == 0 else 1.0 - levenshtein(left, right) / size


def add_to_dependency_graph(
    dependency_graph: Dict[str, List[str]],
    label: str,
    value: Union[str, Sequence[str]],
) -> None:
    """Add one or more unique dependency labels, matching the reference API."""

    dependencies = dependency_graph.setdefault(label, [])
    values = [value] if isinstance(value, str) else value
    for dependency in values:
        if dependency and dependency not in dependencies:
            dependencies.append(dependency)


def longest_common_substring(left: str, right: str) -> str:
    if not left or not right:
        return ""
    previous = [0] * (len(right) + 1)
    longest = 0
    end = 0
    for left_index, left_char in enumerate(left, 1):
        current = [0]
        for right_index, right_char in enumerate(right, 1):
            value = previous[right_index - 1] + 1 if left_char == right_char else 0
            current.append(value)
            if value > longest:
                longest = value
                end = left_index
        previous = current
    return left[end - longest : end]


def find_longest_substring(left: str, right: str) -> str:
    """Source-compatible name for the longest-common-substring helper."""

    return longest_common_substring(left, right)


def get_differences(shorter: str, longer: str) -> List[str]:
    differences: List[str] = []
    left = right = 0
    while left < len(shorter) and right < len(longer):
        if shorter[left] == longer[right]:
            left += 1
            right += 1
        elif shorter[left] in longer[right:]:
            differences.append(f"+ {longer[right]}")
            right += 1
        else:
            differences.append(f"- {shorter[left]}")
            left += 1
    while right < len(longer):
        differences.append(f"+ {longer[right]}")
        right += 1
    return differences


@dataclass(frozen=True)
class EditDistanceMatrixResult:
    """Reference-shaped result with a compatibility iterator for old callers."""

    matrix: List[List[int]]
    pairs: List[Tuple[str, str]]
    differences: List[List[str]]

    def __iter__(self) -> Iterator[object]:
        """Keep the pre-port two-value unpacking contract working."""

        yield self.pairs
        yield self.differences


def define_edit_distance_matrix(
    species_names: Sequence[str], similarity_threshold: int = 4
) -> EditDistanceMatrixResult:
    matrix = [[0 for _ in species_names] for _ in species_names]
    pairs: List[Tuple[str, str]] = []
    differences: List[List[str]] = []
    for index, left in enumerate(species_names):
        for right_index, right in enumerate(species_names[index + 1 :], index + 1):
            if abs(len(left) - len(right)) > similarity_threshold:
                continue
            distance = levenshtein(left, right)
            matrix[index][right_index] = distance
            matrix[right_index][index] = distance
            if 0 < distance <= similarity_threshold:
                shorter, longer = (
                    (left, right) if len(left) <= len(right) else (right, left)
                )
                pairs.append((shorter, longer))
                differences.append(get_differences(shorter, longer))
    return EditDistanceMatrixResult(matrix, pairs, differences)


def analyze_naming_conventions(
    species_names: Sequence[str],
    patterns: Optional[Mapping[Tuple[str, ...], str]] = None,
    similarity_threshold: int = 4,
) -> Dict[str, object]:
    conventions = patterns or DEFAULT_NAMING_PATTERNS
    distance_result = define_edit_distance_matrix(species_names, similarity_threshold)
    pairs, differences = distance_result
    pair_classification: Dict[str, List[Tuple[str, str]]] = OrderedDict()
    keys: List[str] = []
    for pair, difference in zip(pairs, differences):
        key = tuple(difference)
        if key not in keys:
            keys.append(key)
        modification = conventions.get(key)
        if modification:
            pair_classification.setdefault(modification, []).append(pair)
    return {
        "pairClassification": pair_classification,
        "keys": keys,
        "patterns": conventions,
    }


def infer_modification(
    species_name: str,
    base_species: Sequence[str],
    patterns: Optional[Mapping[Tuple[str, ...], str]] = None,
) -> Tuple[Optional[str], Optional[str], float]:
    conventions = patterns or DEFAULT_NAMING_PATTERNS
    candidates = [
        candidate for candidate in base_species if len(candidate) < len(species_name)
    ]
    best: Tuple[Optional[str], Optional[str], float] = (None, None, 0.0)
    for candidate in candidates:
        modification = conventions.get(tuple(get_differences(candidate, species_name)))
        if modification:
            confidence = similarity(candidate, species_name)
            if confidence > best[2]:
                best = (candidate, modification, confidence)
    if best[2] > 0:
        return best

    for candidate in candidates:
        common = longest_common_substring(candidate, species_name)
        confidence = len(common) / max(len(candidate), len(species_name))
        if confidence <= max(best[2], 0.5):
            continue
        suffix = species_name[len(candidate) :]
        modification = None
        if re.fullmatch(r"_?[pP]+", suffix):
            modification = (
                "Double-Phosphorylation"
                if len(suffix.replace("_", "")) > 1
                else "Phosphorylation"
            )
        elif re.fullmatch(r"_?[aA]ct?", suffix):
            modification = "Activation"
        elif re.fullmatch(r"_?[uU]b?", suffix):
            modification = "Ubiquitination"
        elif suffix.startswith("_"):
            modification = "Binding"
        if modification:
            best = (candidate, modification, confidence)
    return best


def _reaction_species(references: Iterable[object]) -> List[str]:
    result = []
    for reference in references:
        species = getattr(reference, "species", None)
        if species is None and isinstance(reference, Mapping):
            species = reference.get("species")
        if species and species != "EmptySet":
            result.append(str(species))
    return result


def _has_saturation_rate(reaction: SBMLReaction) -> bool:
    math = get_kinetic_math(reaction.kinetic_law).lower()
    return any(token in math for token in ("sat", "mm", "hill")) or "/" in math


def classify_reaction(reaction: SBMLReaction) -> ReactionPattern:
    reactants = _reaction_species(reaction.reactants)
    products = _reaction_species(reaction.products)
    modifiers = list(reaction.modifiers)
    common = [species for species in reactants if species in products]

    if not reactants and products:
        return ReactionPattern("synthesis", [], products, modifiers)
    if reactants and not products:
        return ReactionPattern("degradation", reactants, [], modifiers)
    if (
        len(reactants) == 2
        and len(products) == 1
        and len(common) == 1
        and _has_saturation_rate(reaction)
    ):
        catalyst = common[0]
        substrate = next(species for species in reactants if species != catalyst)
        return ReactionPattern(
            "catalysis", [substrate], [substrate], [catalyst] + modifiers, catalyst
        )
    if len(reactants) >= 2 and len(products) == 1:
        return ReactionPattern("binding", reactants, products, modifiers)
    if len(reactants) == 1 and len(products) >= 2 and len(common) == 1:
        common_species = common[0]
        return ReactionPattern(
            "synthesis",
            [],
            [species for species in products if species != common_species],
            [common_species] + modifiers,
            common_species,
        )
    if len(reactants) == 1 and len(products) >= 2:
        return ReactionPattern("unbinding", reactants, products, modifiers)
    if len(reactants) == 1 and len(products) == 1:
        return ReactionPattern("modification", reactants, products, modifiers)
    if len(reactants) == 2 and len(products) == 2 and len(common) == 1:
        common_species = common[0]
        return ReactionPattern(
            "catalysis",
            [species for species in reactants if species != common_species],
            [species for species in products if species != common_species],
            modifiers,
            common_species,
        )
    return ReactionPattern("transformation", reactants, products, modifiers)


def analyze_reactions(model: SBMLModel) -> Dict[str, object]:
    binding: Dict[str, List[str]] = OrderedDict()
    modification: Dict[str, str] = OrderedDict()
    dependencies: Dict[str, Set[str]] = OrderedDict()
    patterns: Dict[str, ReactionPattern] = OrderedDict()

    for reaction_id, reaction in model.reactions.items():
        pattern = classify_reaction(reaction)
        patterns[reaction_id] = pattern
        if pattern.type == "binding" and len(pattern.products) == 1:
            product = pattern.products[0]
            binding[product] = list(pattern.reactants)
            dependencies.setdefault(product, set()).update(pattern.reactants)
        elif pattern.type == "unbinding" and len(pattern.reactants) == 1:
            complex_id = pattern.reactants[0]
            complex_name = (
                model.species.get(complex_id, SBMLSpecies(complex_id)).name
                or complex_id
            )
            if all(
                (model.species.get(product, SBMLSpecies(product)).name or product)
                in complex_name
                or complex_name
                in (model.species.get(product, SBMLSpecies(product)).name or product)
                for product in pattern.products
            ):
                binding.setdefault(complex_id, list(pattern.products))
                dependencies.setdefault(complex_id, set()).update(pattern.products)
        elif (
            pattern.type in {"modification", "catalysis"}
            and pattern.reactants
            and pattern.products
        ):
            base = pattern.reactants[0]
            derived = pattern.products[0]
            base_name = model.species.get(base, SBMLSpecies(base)).name or base
            derived_name = (
                model.species.get(derived, SBMLSpecies(derived)).name or derived
            )
            if base_name in derived_name or len(derived_name) > len(base_name):
                modification[derived] = base
                dependencies.setdefault(derived, set()).add(base)
    return {
        "bindingReactions": binding,
        "modificationReactions": modification,
        "dependencies": dependencies,
        "patterns": patterns,
    }


def topological_sort(
    species_ids: Sequence[str], dependencies: Mapping[str, Set[str]]
) -> List[str]:
    sorted_species: List[str] = []
    visited: Set[str] = set()
    visiting: Set[str] = set()

    def visit(species_id: str) -> None:
        if species_id in visited:
            return
        if species_id in visiting:
            return
        visiting.add(species_id)
        for dependency in dependencies.get(species_id, set()):
            if dependency in species_ids:
                visit(dependency)
        visiting.remove(species_id)
        visited.add(species_id)
        sorted_species.append(species_id)

    for species_id in species_ids:
        visit(species_id)
    return sorted_species


def compute_weights(
    species_ids: Sequence[str], dependencies: Mapping[str, Set[str]]
) -> Dict[str, int]:
    weights: Dict[str, int] = {}
    for species_id in topological_sort(species_ids, dependencies):
        weights[species_id] = 1 + sum(
            weights.get(dependency, 1)
            for dependency in dependencies.get(species_id, set())
        )
    return weights


def _sanitize_structure(species: Species) -> None:
    for molecule in species.molecules:
        molecule.name = standardize_name(molecule.name)
        molecule.compartment = (
            standardize_name(molecule.compartment) if molecule.compartment else ""
        )
        for component in molecule.components:
            component.name = standardize_name(component.name)
            component.states = [
                (
                    state
                    if state in ("+", "?")
                    or re.fullmatch(r"-?\d+(?:\.\d+)?", state or "")
                    else standardize_name(state)
                )
                for state in component.states
            ]
            if component.active_state:
                component.active_state = standardize_name(component.active_state)


def _apply_name_compartments(name: str, species: Species) -> None:
    prefix = re.match(r"^@([^:]+)::", name or "")
    species_compartment = prefix.group(1) if prefix else ""
    pattern = name[prefix.end() :] if prefix else name
    molecules = pattern.split(".")
    for index, molecule in enumerate(species.molecules[: len(molecules)]):
        match = re.search(r"@([^@.]+)$", molecules[index])
        molecule.compartment = match.group(1) if match else species_compartment


def _elemental_species(sbml_species: SBMLSpecies) -> Species:
    name = sbml_species.name or sbml_species.id
    name_without_compartment = re.sub(r"^@[^:]+::", "", name)
    try:
        parsed = read_from_string(name_without_compartment)
        if parsed.molecules and any(
            molecule.components for molecule in parsed.molecules
        ):
            _sanitize_structure(parsed)
            for molecule in parsed.molecules:
                molecule.idx = sbml_species.id
            return parsed
    except (TypeError, ValueError):
        pass
    result = Species()
    result.add_molecule(Molecule(standardize_name(sbml_species.id), sbml_species.id))
    return result


def _complex_species(
    component_ids: Sequence[str], entries: Mapping[str, SCTEntry], use_id: bool = False
) -> Species:
    result = Species()
    copied_groups: List[List[Molecule]] = []
    for index, component_id in enumerate(component_ids):
        entry = entries.get(component_id)
        if entry is not None:
            component_species = entry.structure.copy()
            component_species.update_bonds(result.get_bond_numbers())
            for molecule in component_species.molecules:
                if index > 0 and not molecule.contains(f"b{index}"):
                    molecule.add_component(
                        Component(f"b{index}", f"{molecule.idx}_b{index}")
                    )
                if index < len(component_ids) - 1 and not molecule.contains(
                    f"b{index + 1}"
                ):
                    molecule.add_component(
                        Component(f"b{index + 1}", f"{molecule.idx}_b{index + 1}")
                    )
            copied_groups.append(component_species.molecules)
            for molecule in component_species.molecules:
                result.add_molecule(molecule)
        else:
            name = component_id if use_id else standardize_name(component_id)
            molecule = Molecule(name, component_id)
            if index > 0:
                molecule.add_component(
                    Component(f"b{index}", f"{molecule.idx}_b{index}")
                )
            if index < len(component_ids) - 1:
                molecule.add_component(
                    Component(f"b{index + 1}", f"{molecule.idx}_b{index + 1}")
                )
            copied_groups.append([molecule])
            result.add_molecule(molecule)

    for index in range(len(copied_groups) - 1):
        left = copied_groups[index][0]
        right = copied_groups[index + 1][0]
        bond = max(result.get_bond_numbers() or [0]) + 1
        left_site = left.get_component(f"b{index + 1}")
        right_site = right.get_component(f"b{index + 1}")
        if left_site is not None and right_site is not None:
            left_site.add_bond(bond)
            right_site.add_bond(bond)
            result.bonds.append((left_site.idx, right_site.idx))
    result.renumber_bonds()
    return result


def _modification_state(modification: str) -> str:
    return {
        "Phosphorylation": "P",
        "Double-Phosphorylation": "PP",
        "Triple-Phosphorylation": "PPP",
        "Dephosphorylation": "0",
        "Ubiquitination": "Ub",
        "Deubiquitination": "0",
        "Acetylation": "Ac",
        "Deacetylation": "0",
        "Methylation": "Me",
        "Demethylation": "0",
        "Activation": "A",
        "Inactivation": "I",
        "Binding": "bound",
        "Localization": "loc",
        "Dimerization": "dim",
        "Trimerization": "trim",
    }.get(modification, modification[:1].upper())


def _modified_species(
    base: Optional[SCTEntry], modification: str, fallback: SBMLSpecies
) -> Species:
    if base is None:
        return _elemental_species(fallback)
    result = base.structure.copy()
    if not result.molecules:
        return result
    molecule = result.molecules[0]
    component_name = modification.lower()
    component = molecule.get_component(component_name)
    state = _modification_state(modification)
    if component is None:
        component = Component(component_name, f"{molecule.idx}_{component_name}")
        component.add_state("0")
        component.add_state(state)
        component.set_active_state(state)
        molecule.add_component(component)
    else:
        component.set_active_state(state)
    return result


def build_species_composition_table(
    model: SBMLModel,
    *,
    use_id: bool = False,
    use_annotations: bool = True,
    atomize: bool = False,
    naming_patterns: Optional[Mapping[Tuple[str, ...], str]] = None,
    **_: object,
) -> SpeciesCompositionTable:
    species_ids = list(model.species.keys())
    relationships = analyze_reactions(model)
    binding = relationships["bindingReactions"]
    modifications = relationships["modificationReactions"]
    dependencies: Dict[str, Set[str]] = OrderedDict()
    for species_id, deps in relationships["dependencies"].items():
        dependencies.setdefault(species_id, set()).update(deps)

    names_to_ids: Dict[str, str] = OrderedDict()
    for species_id in species_ids:
        item = model.species[species_id]
        if item.name and item.name not in names_to_ids:
            names_to_ids[item.name] = species_id
        names_to_ids.setdefault(species_id, species_id)

    naming = analyze_naming_conventions(
        [model.species[species_id].name or species_id for species_id in species_ids],
        naming_patterns,
    )
    for pairs in naming["pairClassification"].values():
        for base_name, derived_name in pairs:
            base_id = names_to_ids.get(base_name)
            derived_id = names_to_ids.get(derived_name)
            if base_id and derived_id and base_id != derived_id:
                dependencies.setdefault(derived_id, set()).add(base_id)

    reverse: Dict[str, Set[str]] = OrderedDict()
    for species_id, deps in dependencies.items():
        for dependency in deps:
            reverse.setdefault(dependency, set()).add(species_id)

    sorted_species = topological_sort(species_ids, dependencies)
    weights = compute_weights(species_ids, dependencies)
    entries: Dict[str, SCTEntry] = OrderedDict()

    for species_id in sorted_species:
        item = model.species[species_id]
        item_name = item.name or species_id
        is_elemental = True
        components: List[str] = []
        modifications_info: Dict[str, str] = {}

        has_real_structure = ("." in item_name or "(" in item_name) and "!" in item_name
        if atomize and has_real_structure:
            structure = read_from_string(item_name)
            _sanitize_structure(structure)
            components = structure.get_molecule_names()
            is_elemental = False
        elif atomize and species_id in binding:
            components = list(binding[species_id])
            is_elemental = False
            structure = _complex_species(components, entries, use_id)
        elif atomize and species_id in modifications:
            base_id = modifications[species_id]
            components = [base_id]
            is_elemental = False
            base_name = model.species.get(base_id, SBMLSpecies(base_id)).name or base_id
            _, modification, _confidence = infer_modification(
                item_name, [base_name], naming_patterns
            )
            if modification:
                modifications_info["state"] = modification
                structure = _modified_species(entries.get(base_id), modification, item)
            else:
                structure = _elemental_species(item)
        elif atomize and dependencies.get(species_id):
            dependency_ids = list(dependencies[species_id])
            components = dependency_ids
            is_elemental = False
            if len(dependency_ids) == 1:
                base_id = dependency_ids[0]
                base_name = (
                    model.species.get(base_id, SBMLSpecies(base_id)).name or base_id
                )
                _, modification, _confidence = infer_modification(
                    item_name, [base_name], naming_patterns
                )
                if modification:
                    modifications_info["state"] = modification
                    structure = _modified_species(
                        entries.get(base_id), modification, item
                    )
                else:
                    structure = _complex_species(dependency_ids, entries, use_id)
            else:
                structure = _complex_species(dependency_ids, entries, use_id)
        else:
            structure = _elemental_species(item)

        _apply_name_compartments(item_name, structure)
        declared = {
            standardize_name(compartment_id) for compartment_id in model.compartments
        }
        if item.compartment and standardize_name(item.compartment) in declared:
            for molecule in structure.molecules:
                if (
                    molecule.compartment
                    and standardize_name(molecule.compartment) not in declared
                ):
                    molecule.compartment = item.compartment
        entries[species_id] = SCTEntry(
            structure=structure,
            components=components,
            sbml_id=species_id,
            is_elemental=is_elemental,
            modifications=modifications_info,
            weight=weights.get(species_id, 1),
        )

    table = SpeciesCompositionTable(
        entries=entries,
        dependencies=dependencies,
        reverse_dependencies=reverse,
        sorted_species=sorted_species,
        weights=sorted(weights.items(), key=lambda item: item[1]),
    )
    reconcile_sct(table, get_molecule_types(table))
    return table


def _update_molecule_type(existing: Molecule, incoming: Molecule) -> None:
    existing_by_name: Dict[str, List[Component]] = OrderedDict()
    incoming_by_name: Dict[str, List[Component]] = OrderedDict()
    for component in existing.components:
        existing_by_name.setdefault(component.name, []).append(component)
    for component in incoming.components:
        incoming_by_name.setdefault(component.name, []).append(component)
    for name, incoming_components in incoming_by_name.items():
        current = existing_by_name.setdefault(name, [])
        for component in incoming_components[len(current) :]:
            copied = component.copy()
            existing.add_component(copied)
            current.append(copied)
        for left, right in zip(current, incoming_components):
            left.add_states(right.states, update=False)


def get_molecule_types(sct: SpeciesCompositionTable) -> List[Molecule]:
    molecule_types: Dict[str, Molecule] = OrderedDict()
    for entry in sct.entries.values():
        for molecule in entry.structure.molecules:
            if molecule.name not in molecule_types:
                molecule_types[molecule.name] = molecule.copy()
            else:
                _update_molecule_type(molecule_types[molecule.name], molecule)
    return list(molecule_types.values())


def reconcile_sct(
    sct: SpeciesCompositionTable, molecule_types: Sequence[Molecule]
) -> None:
    type_map = {molecule.name: molecule for molecule in molecule_types}
    for entry in sct.entries.values():
        for molecule in entry.structure.molecules:
            template = type_map.get(molecule.name)
            if template is None:
                continue
            counts = {}
            templates = {}
            for component in template.components:
                counts[component.name] = counts.get(component.name, 0) + 1
                templates.setdefault(component.name, component)
            present = {}
            for component in molecule.components:
                present[component.name] = present.get(component.name, 0) + 1
            for name, count in counts.items():
                for _ in range(max(0, count - present.get(name, 0))):
                    component = templates[name].copy()
                    component.bonds = []
                    component.set_active_state(
                        "0"
                        if "0" in component.states
                        else (component.states[0] if component.states else "")
                    )
                    molecule.add_component(component)


def disambiguate_colliding_species(
    sct: SpeciesCompositionTable, model: SBMLModel
) -> int:
    groups: Dict[Tuple[str, str], List[str]] = OrderedDict()
    for species_id, entry in sct.entries.items():
        if not entry.structure.molecules:
            continue
        pattern = ".".join(
            sorted(molecule.to_string(True) for molecule in entry.structure.molecules)
        )
        compartment = model.species.get(species_id, SBMLSpecies(species_id)).compartment
        groups.setdefault((compartment, pattern), []).append(species_id)
    count = 0
    for species_ids in groups.values():
        if len(set(species_ids)) < 2:
            continue
        for species_id in species_ids:
            entry = sct.entries[species_id]
            discriminator = Component("__sp", states=[standardize_name(species_id)])
            discriminator.set_active_state(standardize_name(species_id))
            entry.structure.molecules[0].add_component(discriminator)
            count += 1
    return count


def get_seed_species(
    sct: SpeciesCompositionTable, model: SBMLModel
) -> List[SeedSpeciesEntry]:
    initial_assignments = {item.symbol: item.math for item in model.initial_assignments}
    result: List[SeedSpeciesEntry] = []
    for species_id, entry in sct.entries.items():
        item = model.species[species_id]
        compartment = standardize_name(item.compartment or "Compartment")
        volume = f"__compartment_{compartment}__"
        amount_set = item.initial_amount_set or item.initial_amount != 0
        concentration_set = (
            item.initial_concentration_set or item.initial_concentration != 0
        )
        if species_id in initial_assignments:
            expression = initial_assignments[species_id]
            if not item.has_only_substance_units:
                expression = f"({expression} * __Avogadro__ * {volume})"
            else:
                expression = f"({expression})"
        elif amount_set:
            expression = (
                str(item.initial_amount).rstrip("0").rstrip(".")
                if "." in str(item.initial_amount)
                else str(item.initial_amount)
            )
        elif concentration_set:
            expression = f"({item.initial_concentration} * __Avogadro__ * {volume})"
        else:
            expression = "0"
        result.append(
            SeedSpeciesEntry(
                entry.structure.copy(), expression, item.compartment, species_id
            )
        )
    return result


# Keep the public names used by the TypeScript reference available alongside
# BNG3's snake_case spelling.
addToDependencyGraph = add_to_dependency_graph
defineEditDistanceMatrix = define_edit_distance_matrix
findLongestSubstring = find_longest_substring


__all__ = [
    "EditDistanceMatrixResult",
    "addToDependencyGraph",
    "add_to_dependency_graph",
    "analyze_naming_conventions",
    "analyze_reactions",
    "build_species_composition_table",
    "classify_reaction",
    "compute_weights",
    "defineEditDistanceMatrix",
    "define_edit_distance_matrix",
    "disambiguate_colliding_species",
    "get_differences",
    "findLongestSubstring",
    "find_longest_substring",
    "get_molecule_types",
    "get_seed_species",
    "infer_modification",
    "levenshtein",
    "reconcile_sct",
    "similarity",
    "topological_sort",
]
