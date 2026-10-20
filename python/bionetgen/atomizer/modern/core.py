"""Reaction analysis and species-composition inference.

This is a focused Python port of the Playground atomizer's
``atomization/core.ts``.  The dependency graph is intentionally explicit: a
species may only inherit structure from a species that has already been
resolved, and unresolved relationships remain elemental rather than being
silently guessed.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import (
    Any,
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

from .structures import (
    Component,
    Molecule,
    Species,
    read_from_string,
    read_from_string_with_diagnostics,
)
from .types import (
    DEFAULT_NAMING_CONVENTIONS,
    NamingConventions,
    ReactionPattern,
    SBMLImportWarning,
    SBMLModel,
    SBMLReaction,
    SBMLSpecies,
    SCTEntry,
    SeedSpeciesEntry,
    SpeciesCompositionTable,
    StructuralInference,
    get_kinetic_math,
    standardize_name,
)

_DEP_CYCLE_LOG_LIMIT = int(os.environ.get("ATOMIZER_DEP_CYCLE_LOG_LIMIT", "20"))
_dep_cycle_log_count = 0

NamingPatternConfig = Union[
    Mapping[Tuple[str, ...], str],
    NamingConventions,
]


# ---------------------------------------------------------------------------
# Structural inference vocabulary
# ---------------------------------------------------------------------------
#
# The SBML Level 3 Core specification lets a ``species`` carry an ``sboTerm``
# that names the Systems Biology Ontology (SBO) term describing the process
# that produced the species, or its most relevant function.  A species whose
# SBO term is "phosphorylation" is therefore the phosphorylated form of a
# base species; this is the only machine-readable statement of that fact in
# the SBML source and it outranks any name heuristic.
#
# The identifiers below are the SBO term ids served by the EMBL-EBI OLS4
# service for the SBO release referenced by the SBML specification.
SBO_ADDITIVE_MODIFICATIONS: Mapping[str, str] = OrderedDict(
    [
        ("SBO:0000216", "Phosphorylation"),
        ("SBO:0000217", "Glycosylation"),
        ("SBO:0000214", "Methylation"),
        ("SBO:0000215", "Acetylation"),
        ("SBO:0000224", "Ubiquitination"),
        ("SBO:0000233", "Hydroxylation"),
        ("SBO:0000218", "Palmitoylation"),
        ("SBO:0000219", "Myristoylation"),
        ("SBO:0000221", "Prenylation"),
        ("SBO:0000222", "Farnesylation"),
        ("SBO:0000223", "Geranylgeranylation"),
        ("SBO:0000656", "Activation"),
        ("SBO:0000665", "Inactivation"),
    ]
)

# SBO terms that name a species as the *unmodified* form of a base species.
SBO_REMOVAL_MODIFICATIONS: Mapping[str, str] = OrderedDict(
    [
        ("SBO:0000330", "Dephosphorylation"),
    ]
)

# Modification name -> (binding/modification site name, active state).
# Related modifications share one site so that, for example, a singly and a
# doubly phosphorylated species are states of the same site rather than two
# unrelated sites.
MODIFICATION_SITES: Mapping[str, Tuple[str, str]] = OrderedDict(
    [
        ("Phosphorylation", ("phosphorylation", "P")),
        ("Double-Phosphorylation", ("phosphorylation", "PP")),
        ("Triple-Phosphorylation", ("phosphorylation", "PPP")),
        ("Dephosphorylation", ("phosphorylation", "0")),
        ("Ubiquitination", ("ubiquitination", "Ub")),
        ("Deubiquitination", ("ubiquitination", "0")),
        ("Acetylation", ("acetylation", "Ac")),
        ("Deacetylation", ("acetylation", "0")),
        ("Methylation", ("methylation", "Me")),
        ("Demethylation", ("methylation", "0")),
        ("Glycosylation", ("glycosylation", "Gly")),
        ("Hydroxylation", ("hydroxylation", "OH")),
        ("Palmitoylation", ("palmitoylation", "Pal")),
        ("Myristoylation", ("myristoylation", "Myr")),
        ("Prenylation", ("prenylation", "Pre")),
        ("Farnesylation", ("farnesylation", "Far")),
        ("Geranylgeranylation", ("geranylgeranylation", "Ger")),
        ("Activation", ("activation", "A")),
        ("Inactivation", ("inactivation", "I")),
        ("Binding", ("binding", "bound")),
        ("Localization", ("localization", "loc")),
        ("Dimerization", ("dimerization", "dim")),
        ("Trimerization", ("trimerization", "trim")),
    ]
)

# Trailing name fragments that identify a modification state.  The fragment
# must be the whole remainder of the species name after the base name so that
# unrelated words are not mistaken for a modification.
NAMED_MODIFICATION_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("phosphorylated", "Phosphorylation"),
    ("phosphorylation", "Phosphorylation"),
    ("phospho", "Phosphorylation"),
    ("phos", "Phosphorylation"),
    ("ubiquitinated", "Ubiquitination"),
    ("ubiquitination", "Ubiquitination"),
    ("ubiquitin", "Ubiquitination"),
    ("ubq", "Ubiquitination"),
    ("ubi", "Ubiquitination"),
    ("ub", "Ubiquitination"),
    ("acetylated", "Acetylation"),
    ("acetylation", "Acetylation"),
    ("acetyl", "Acetylation"),
    ("acet", "Acetylation"),
    ("ac", "Acetylation"),
    ("methylated", "Methylation"),
    ("methylation", "Methylation"),
    ("methyl", "Methylation"),
    ("glycosylated", "Glycosylation"),
    ("glycosylation", "Glycosylation"),
    ("glycosyl", "Glycosylation"),
    ("glyco", "Glycosylation"),
    ("gly", "Glycosylation"),
    ("hydroxylated", "Hydroxylation"),
    ("hydroxylation", "Hydroxylation"),
    ("hydroxyl", "Hydroxylation"),
    ("inactivated", "Inactivation"),
    ("inactivation", "Inactivation"),
    ("inactive", "Inactivation"),
    ("inact", "Inactivation"),
    ("activated", "Activation"),
    ("activation", "Activation"),
    ("active", "Activation"),
    ("act", "Activation"),
)

# Separators that may join a base molecule name to a modification or to
# another molecule in a complex.
COMPLEX_NAME_SEPARATORS: Tuple[str, ...] = (".", "-", "_", "!")

_SBO_TERM_PATTERN = re.compile(r"SBO:(\d{7})", re.IGNORECASE)


def _resolve_naming_patterns(
    patterns: Optional[NamingPatternConfig],
) -> Mapping[Tuple[str, ...], str]:
    if patterns is None:
        return DEFAULT_NAMING_CONVENTIONS.patterns
    if isinstance(patterns, NamingConventions):
        return patterns.patterns
    return patterns


def _log_dependency_cycle(message: str) -> None:
    global _dep_cycle_log_count
    from .helpers import logger

    if _DEP_CYCLE_LOG_LIMIT < 0 or _dep_cycle_log_count < _DEP_CYCLE_LOG_LIMIT:
        logger.warning("DEP001", message)
    elif _dep_cycle_log_count == _DEP_CYCLE_LOG_LIMIT:
        logger.warning("DEP001", "Additional dependency cycle logs suppressed.")
    _dep_cycle_log_count += 1


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


@dataclass(frozen=True)
class ModificationInference:
    """Named result returned by the Playground modification heuristic."""

    base: Optional[str]
    modification: Optional[str]
    confidence: float

    def __iter__(self) -> Iterator[object]:
        """Keep the original Python tuple-unpacking contract working."""

        yield self.base
        yield self.modification
        yield self.confidence


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
    patterns: Optional[NamingPatternConfig] = None,
    similarity_threshold: int = 4,
) -> Dict[str, object]:
    conventions = _resolve_naming_patterns(patterns)
    distance_result = define_edit_distance_matrix(species_names, similarity_threshold)
    pairs, differences = distance_result
    pair_classification: Dict[str, List[Tuple[str, str]]] = OrderedDict()
    keys: List[str] = []
    for pair, difference in zip(pairs, differences):
        key = json.dumps(difference, ensure_ascii=False, separators=(",", ":"))
        if key not in keys:
            keys.append(key)
        modification = conventions.get(tuple(difference))
        if modification:
            pair_classification.setdefault(modification, []).append(pair)
    from .helpers import logger

    logger.info(
        "NAM001",
        f"Naming analysis: {len(pairs)} similar pairs, "
        f"{len(pair_classification)} classifications",
    )
    return {
        "pairClassification": pair_classification,
        "keys": keys,
        "patterns": conventions,
    }


def normalize_sbo_term(value: object) -> Optional[str]:
    """Return the canonical ``SBO:NNNNNNN`` spelling of an SBO term.

    SBML files spell the term in several ways (``SBO:0000216``,
    ``0000216`` or an identifier URL).  Anything that cannot be resolved to a
    numbered SBO term returns ``None`` so the caller can report the term as
    unrecognized instead of guessing.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _SBO_TERM_PATTERN.search(text)
    if match:
        return f"SBO:{match.group(1)}"
    if re.fullmatch(r"\d{7}", text):
        return f"SBO:{text}"
    return None


def sbo_modification(sbo_term: object) -> Optional[Tuple[str, str]]:
    """Map an SBML SBO term onto a modification name and its kind.

    The kind is ``additive`` when the term names a species as the modified
    form of a base species and ``removal`` when it names the unmodified form.
    """

    normalized = normalize_sbo_term(sbo_term)
    if normalized is None:
        return None
    if normalized in SBO_ADDITIVE_MODIFICATIONS:
        return SBO_ADDITIVE_MODIFICATIONS[normalized], "additive"
    if normalized in SBO_REMOVAL_MODIFICATIONS:
        return SBO_REMOVAL_MODIFICATIONS[normalized], "removal"
    return None


def _match_modification_suffix(suffix: str) -> Optional[str]:
    """Return the modification named by a trailing name fragment."""

    text = str(suffix or "").strip()
    if not text:
        return None
    if text[0] in "-_. ":
        text = text[1:]
    if not text:
        return None
    if re.fullmatch(r"[pP]{1,3}", text):
        return {
            1: "Phosphorylation",
            2: "Double-Phosphorylation",
            3: "Triple-Phosphorylation",
        }[len(text)]
    lowered = text.lower()
    for token, modification in NAMED_MODIFICATION_SUFFIXES:
        if lowered == token:
            return modification
    return None


def infer_modification(
    species_name: str,
    base_species: Sequence[str],
    patterns: Optional[NamingPatternConfig] = None,
) -> ModificationInference:
    conventions = _resolve_naming_patterns(patterns)
    candidates = [
        candidate for candidate in base_species if len(candidate) < len(species_name)
    ]
    best = ModificationInference(None, None, 0.0)

    # Separator-tolerant suffix match.  BioModels species names spell the
    # modification with ``-``, ``_``, ``.`` or a space ("A-P", "A_P", "A.P"),
    # which the character-difference conventions do not cover.  The fragment
    # must be the whole remainder of the name after a base name, so the match
    # states the modification exactly instead of counting character edits.
    for candidate in candidates:
        if not species_name.startswith(candidate):
            continue
        modification = _match_modification_suffix(species_name[len(candidate) :])
        if modification:
            confidence = similarity(candidate, species_name)
            if confidence > best.confidence:
                best = ModificationInference(candidate, modification, confidence)
    if best.modification:
        # A species name that repeats the phosphorylation marker names the
        # next phosphorylation level ("A-P" plus "P" is "A-PP"), so the
        # modification state is read from the whole name rather than from the
        # added fragment alone.
        if best.modification == "Phosphorylation" and best.base:
            base_run = re.search(r"[pP]+$", best.base)
            product_run = re.search(r"[pP]+$", species_name)
            if (
                base_run
                and product_run
                and len(product_run.group(0)) > len(base_run.group(0))
            ):
                level = len(product_run.group(0))
                best = ModificationInference(
                    best.base,
                    "Double-Phosphorylation"
                    if level == 2
                    else "Triple-Phosphorylation",
                    best.confidence,
                )
        return best

    for candidate in candidates:
        modification = conventions.get(tuple(get_differences(candidate, species_name)))
        if modification:
            confidence = similarity(candidate, species_name)
            if confidence > best.confidence:
                best = ModificationInference(candidate, modification, confidence)
    if best.confidence > 0:
        return best

    for candidate in candidates:
        common = longest_common_substring(candidate, species_name)
        confidence = len(common) / max(len(candidate), len(species_name))
        if confidence <= max(best.confidence, 0.5):
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
            best = ModificationInference(candidate, modification, confidence)
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
    if any(token in math for token in ("sat", "mm", "hill")):
        return True
    return "/" in math and "+" in math and math.count("*") >= 2


def classify_reaction(reaction: SBMLReaction) -> ReactionPattern:
    reactants = _reaction_species(reaction.reactants)
    products = _reaction_species(reaction.products)
    modifiers = [
        str(getattr(modifier, "species", modifier)) for modifier in reaction.modifiers
    ]
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
    from .helpers import logger

    logger.info(
        "RXN001",
        f"Reaction analysis: {len(binding)} binding, "
        f"{len(modification)} modification",
    )
    return {
        "bindingReactions": binding,
        "modificationReactions": modification,
        "dependencies": dependencies,
        "patterns": patterns,
    }


def _stoichiometric_species(references: Iterable[object]) -> List[Tuple[str, float]]:
    """Return the referenced species with their stoichiometry."""

    result: List[Tuple[str, float]] = []
    for reference in references:
        species = getattr(reference, "species", None)
        if species is None and isinstance(reference, Mapping):
            species = reference.get("species")
        if not species or species == "EmptySet":
            continue
        stoichiometry = getattr(reference, "stoichiometry", 1.0)
        try:
            stoichiometry = float(stoichiometry)
        except (TypeError, ValueError):
            stoichiometry = 1.0
        result.append((str(species), stoichiometry))
    return result


def _distinct_species(references: Iterable[Tuple[str, float]]) -> List[str]:
    """Return the referenced species ids in order, without duplicates."""

    result: List[str] = []
    for species, _stoichiometry in references:
        if species not in result:
            result.append(species)
    return result


def _expanded_species(
    references: Iterable[Tuple[str, float]],
) -> Optional[List[str]]:
    """Expand species references by their stoichiometry.

    A reaction with two molecules of one reactant and one of another
    produces a complex of three molecules, so the composition of an inferred
    complex follows the source stoichiometry instead of the distinct
    reactant count.  ``None`` is returned when a stoichiometry is not a
    positive integer, because such a composition has no exact pattern.
    """

    result: List[str] = []
    for species, stoichiometry in references:
        if not math.isfinite(stoichiometry) or stoichiometry < 0:
            return None
        count = int(round(stoichiometry))
        if abs(stoichiometry - count) > 1e-9:
            return None
        result.extend([species] * count)
    return result


def analyze_structural_topology(model: SBMLModel) -> Dict[str, object]:
    """Collect stoichiometry-aware reaction-topology evidence.

    ``complexes`` maps a product species onto the reactant molecules that
    form it.  A species produced by a reaction with two or more reactant
    molecules is a complex of those molecules, and the composition follows
    the source stoichiometry.

    ``modifications`` maps a product species onto the single reactant it is
    derived from, together with the SBML SBO term that names the
    modification when the source provides one.

    ``unbindings`` maps a reactant species onto the distinct products a
    reaction dissociates it into.  A species that dissociates into other
    species is a complex of them.

    The result deliberately does not feed the species-composition
    dependency graph: the flat translation must keep its existing species
    ordering, so the structural evidence is consulted only by the atomized
    translation.
    """

    complexes: Dict[str, List[str]] = OrderedDict()
    modifications: Dict[str, Dict[str, object]] = OrderedDict()
    unbindings: Dict[str, List[str]] = OrderedDict()

    for reaction_id, reaction in model.reactions.items():
        reactants = _stoichiometric_species(reaction.reactants)
        products = _stoichiometric_species(reaction.products)
        distinct_reactants = _distinct_species(reactants)
        distinct_products = _distinct_species(products)
        unit_reactants = all(
            stoichiometry == 1 for _species, stoichiometry in reactants
        )
        unit_products = all(
            stoichiometry == 1 for _species, stoichiometry in products
        )
        expanded_reactants = _expanded_species(reactants)
        expanded_products = _expanded_species(products)
        if (
            expanded_reactants is not None
            and len(expanded_reactants) >= 2
            and len(distinct_products) == 1
            and distinct_products[0] not in distinct_reactants
        ):
            complexes.setdefault(distinct_products[0], expanded_reactants)
        if (
            len(distinct_reactants) == 1
            and len(distinct_products) == 1
            and distinct_reactants[0] != distinct_products[0]
            and unit_reactants
            and unit_products
        ):
            product_species = model.species.get(distinct_products[0])
            sbo = normalize_sbo_term(getattr(product_species, "sbo_term", None))
            entry = modifications.setdefault(
                distinct_products[0],
                {
                    "reactant": distinct_reactants[0],
                    "sbo": None,
                    "reaction": reaction_id,
                },
            )
            if sbo and entry.get("sbo") is None:
                entry["sbo"] = sbo
                entry["reaction"] = reaction_id
        if (
            expanded_products is not None
            and len(distinct_reactants) == 1
            and len(expanded_products) >= 2
            and distinct_reactants[0] not in distinct_products
        ):
            unbindings.setdefault(distinct_reactants[0], expanded_products)

    return {
        "complexes": complexes,
        "modifications": modifications,
        "unbindings": unbindings,
    }


def topological_sort(
    species_ids: Sequence[str], dependencies: Mapping[str, Set[str]]
) -> List[str]:
    sorted_species: List[str] = []
    visited: Set[str] = set()
    visiting: Set[str] = set()
    species_order = {species_id: index for index, species_id in enumerate(species_ids)}

    def visit(species_id: str, path: Optional[List[str]] = None) -> None:
        if species_id in visited:
            return
        if species_id in visiting:
            _log_dependency_cycle(
                f"Dependency cycle detected: {' -> '.join(path or [])} -> {species_id}"
            )
            return
        visiting.add(species_id)
        current_path = [*(path or []), species_id]
        # Dependencies are stored as sets, but their traversal order must not
        # leak into the emitted BNGL seed/network order.  Apart from making
        # artifacts reproducible, stable ordering avoids changing the
        # numerical path of stiff CVODE models between identical imports.
        for dependency in sorted(
            dependencies.get(species_id, set()),
            key=lambda value: (
                species_order.get(value, len(species_order)),
                str(value),
            ),
        ):
            if dependency in species_ids:
                visit(dependency, current_path)
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
            if (
                component.active_state
                and component.active_state not in ("+", "?")
                and not re.fullmatch(r"-?\d+(?:\.\d+)?", component.active_state)
            ):
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
        # BNG3 SBML exports put explicit BNGL molecule patterns in species
        # names; keep site-free patterns when reading those exports back.
        explicit_bngl_pattern = name_without_compartment.startswith("M_") and (
            "(" in name_without_compartment and ")" in name_without_compartment
        )
        if parsed.molecules and (
            explicit_bngl_pattern
            or any(molecule.components for molecule in parsed.molecules)
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


def _modification_site(modification: str) -> Tuple[str, str]:
    """Return the ``(site name, active state)`` pair for a modification.

    Related modifications share one site so that a singly and a doubly
    phosphorylated species are two states of the same site rather than two
    unrelated sites.
    """

    return MODIFICATION_SITES.get(
        modification, (modification.lower(), modification[:1].upper())
    )


def _modification_state(modification: str) -> str:
    return _modification_site(modification)[1]


def _modified_species(
    base: Optional[SCTEntry], modification: str, fallback: SBMLSpecies
) -> Species:
    if base is None:
        return _elemental_species(fallback)
    result = base.structure.copy()
    if not result.molecules:
        return result
    molecule = result.molecules[0]
    component_name, state = _modification_site(modification)
    component = molecule.get_component(component_name)
    if component is None:
        component = Component(component_name, f"{molecule.idx}_{component_name}")
        component.add_state("0")
        component.add_state(state)
        component.set_active_state(state)
        molecule.add_component(component)
    else:
        component.set_active_state(state)
    return result


def _removal_species(
    base: Optional[SCTEntry], modification: str
) -> Optional[Species]:
    """Return the unmodified form of a base species, or ``None``.

    A removal term ("dephosphorylation") states that the species is the
    unmodified form of the species it is derived from.  The site that lost
    its modification must already exist on the base species; when it does
    not, the SBML source does not determine the structure and no inference
    is made.
    """

    if base is None:
        return None
    result = base.structure.copy()
    component_name, state = _modification_site(modification)
    for molecule in result.molecules:
        component = molecule.get_component(component_name)
        if component is not None:
            component.set_active_state(state)
            return result
    return None


def _report_unparsed_fragments(
    model: SBMLModel,
    species_id: str,
    name: str,
    fragments: Sequence[str],
) -> None:
    """Report name fragments that could not be represented as molecules.

    The diagnostic is informational: the species keeps its exact flat
    representation, so no SBML semantics are lost.  It exists so that a
    silently shortened structure is never reported as a successful
    atomization.
    """

    if not fragments:
        return
    if not any(marker in str(name or "") for marker in (".", "(", ")", "!", "~")):
        return
    for fragment in fragments:
        _record_structural_warning(
            model,
            f'Species "{species_id}" name fragment "{fragment}" is not a BNGL '
            "molecule identifier; the fragment was left out of the inferred "
            "molecular structure, and the species keeps its exact flat "
            "representation.",
        )


def _explicit_pattern_structure(name: str) -> Tuple[Optional[Species], List[str]]:
    """Parse a species name as an explicit BNGL molecular pattern.

    A name carries usable structure when it names more than one molecule or
    when it names at least one molecule with a binding or modification site.
    The second return value holds the name fragments that are not valid BNGL
    molecule text so the caller can report them instead of losing them
    silently.
    """

    text = _strip_complex_suffix(re.sub(r"^@[^:]+::", "", str(name or "")))
    if not text:
        return None, []
    parsed, unparsed = read_from_string_with_diagnostics(text)
    if not parsed.molecules:
        return None, unparsed
    if len(parsed.molecules) >= 2:
        return parsed, unparsed
    if any(molecule.components for molecule in parsed.molecules):
        return parsed, unparsed
    return None, unparsed


def _record_structural_warning(
    model: SBMLModel,
    message: str,
    severity: str = "info",
    category: str = "structure",
) -> None:
    """Record one structural-inference diagnostic on the model."""

    warnings = getattr(model, "import_warnings", None)
    if warnings is None:
        model.import_warnings = []
        warnings = model.import_warnings
    if any(
        getattr(warning, "category", None) == category
        and getattr(warning, "message", None) == message
        for warning in warnings
    ):
        return
    warnings.append(
        SBMLImportWarning(
            category=category, message=message, count=1, severity=severity
        )
    )


def _is_molecule_name(text: str) -> bool:
    """Report whether a name fragment can be used as a BNGL molecule name."""

    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(text or "")))


def _strip_complex_suffix(name: str) -> str:
    """Drop a trailing ``complex``/``compound`` word from a species name."""

    return re.sub(
        r"\s+(?:complex|compound|assembly)$", "", str(name or ""), flags=re.IGNORECASE
    )


def _name_complex_candidates(
    name: str, known_names: Mapping[str, str]
) -> List[Tuple[str, List[str]]]:
    """Return the complex readings a species name admits.

    Each entry pairs the separator with the molecule names it yields.  A
    separator that is also used for ordinary identifiers (``-`` and ``_``)
    only yields a reading when every part names an existing species; the
    explicit bond separator ``!`` and the BNGL molecule separator ``.``
    always do.
    """

    text = _strip_complex_suffix(str(name or "").strip())
    text = re.sub(r"@[A-Za-z_][A-Za-z0-9_]*$", "", text)
    if not text:
        return []
    candidates: List[Tuple[str, List[str]]] = []
    for separator in COMPLEX_NAME_SEPARATORS:
        if separator not in text:
            continue
        parts = [part for part in text.split(separator) if part]
        if len(parts) < 2:
            continue
        if not all(_is_molecule_name(part) for part in parts):
            continue
        if separator in "-_":
            if not all(part in known_names for part in parts):
                continue
        candidates.append((separator, parts))
    return candidates


@dataclass
class _StructuralContext:
    """State shared by the per-species structural inference."""

    model: SBMLModel
    entries: Dict[str, SCTEntry]
    topology: Dict[str, object]
    naming_config: Optional[NamingPatternConfig]
    use_id: bool
    names_to_ids: Dict[str, str]
    binding: Mapping[str, List[str]]
    modification_bases: Mapping[str, List[str]]
    naming_dependencies: Mapping[str, List[str]]


def _structure_inference(
    species_id: str,
    name: str,
    structure: Species,
    confidence: str,
    reason: str,
) -> StructuralInference:
    """Build the machine-readable record for one inferred structure."""

    sites: List[str] = []
    states: Dict[str, str] = {}
    for molecule in structure.molecules:
        for component in molecule.components:
            if component.name not in sites:
                sites.append(component.name)
            if component.active_state:
                states[component.name] = component.active_state
    return StructuralInference(
        species_id=species_id,
        name=name,
        molecules=structure.get_molecule_names(),
        sites=sites,
        bonds=list(structure.bonds),
        states=states,
        confidence=confidence,
        reason=reason,
        alternatives=[],
        is_elemental=len(structure.molecules) <= 1 and not sites,
    )


def _alternative_inference(
    confidence: str, reason: str, **extra: object
) -> Dict[str, Any]:
    """Build one alternative reading for the structural inference record."""

    record: Dict[str, Any] = {"confidence": confidence, "reason": reason}
    record.update(extra)
    return record


def _species_base_name(context: _StructuralContext, base_id: str) -> str:
    base_species = context.model.species.get(base_id, SBMLSpecies(base_id))
    return base_species.name or base_id


def _modification_from_name(
    context: _StructuralContext, name: str, base_id: str
) -> Optional[str]:
    """Return the modification a species name declares for a base species."""

    inference = infer_modification(
        name,
        [_species_base_name(context, base_id), base_id],
        context.naming_config,
    )
    return inference.modification


def _topology_matches_molecules(
    components: Sequence[str],
    explicit: Species,
    context: _StructuralContext,
) -> bool:
    """Report whether reaction topology describes the same molecules.

    A species name such as ``A.B`` states the composition of the complex but
    not whether its molecules are bound.  When the reaction topology says the
    species is a complex of exactly those molecules, the topology supplies
    the bonding and the name supplies the composition.
    """

    remaining = [standardize_name(molecule.name) for molecule in explicit.molecules]
    for component in components:
        candidates: List[str] = []
        species = context.model.species.get(component)
        if species is not None and species.name:
            candidates.append(standardize_name(species.name))
        candidates.append(standardize_name(component))
        match = next(
            (candidate for candidate in candidates if candidate in remaining), None
        )
        if match is None:
            return False
        remaining.remove(match)
    return not remaining


def _infer_species_structure(
    species_id: str,
    item: SBMLSpecies,
    context: _StructuralContext,
) -> Tuple[Species, List[str], Dict[str, str], StructuralInference]:
    """Infer the molecular structure of one SBML species.

    The evidence is applied in decreasing order of confidence:

    1. an explicit BNGL pattern spelled out in the species name;
    2. an SBML ``sboTerm`` that names the modification produced by a
       one-reactant/one-product reaction;
    3. reaction topology that makes the species a complex;
    4. a modification name fragment on a one-reactant/one-product reaction;
    5. a naming-convention relationship between similar species names;
    6. a complex name fragment in the species name.

    Anything that stays unresolved keeps the flat, elemental
    representation, which is always mathematically exact.
    """

    name = item.name or species_id
    alternatives: List[Dict[str, Any]] = []
    topology = context.topology
    topology_components = (
        topology["complexes"].get(species_id)
        or context.binding.get(species_id)
        or topology["unbindings"].get(species_id)
    )

    explicit, unparsed = _explicit_pattern_structure(name)
    if explicit is not None:
        for fragment in unparsed:
            alternatives.append(
                _alternative_inference(
                    "name-fragment",
                    f'name fragment "{fragment}" is not a BNGL molecule '
                    "identifier and was left out of the inferred structure",
                    fragment=fragment,
                )
            )
        if topology_components and _topology_matches_molecules(
            topology_components, explicit, context
        ):
            components = list(topology_components)
            structure = _complex_species(
                components, context.entries, context.use_id
            )
            _sanitize_structure(structure)
            record = _structure_inference(
                species_id,
                name,
                structure,
                "reaction-topology",
                "reaction topology makes the species a complex of "
                + ", ".join(str(component) for component in components),
            )
            record.alternatives.append(
                _alternative_inference(
                    "explicit-pattern",
                    "the species name spells out a BNGL molecular pattern",
                    molecules=explicit.get_molecule_names(),
                )
            )
            _report_unparsed_fragments(
                context.model, species_id, name, unparsed
            )
            record.alternatives.extend(alternatives)
            return structure, components, {}, record
        _sanitize_structure(explicit)
        record = _structure_inference(
            species_id,
            name,
            explicit,
            "explicit-pattern",
            "the species name spells out a BNGL molecular pattern",
        )
        if topology_components:
            record.alternatives.append(
                _alternative_inference(
                    "reaction-topology",
                    "reaction topology makes the species a complex of "
                    + ", ".join(str(component) for component in topology_components),
                    molecules=list(topology_components),
                )
            )
        _report_unparsed_fragments(context.model, species_id, name, unparsed)
        record.alternatives.extend(alternatives)
        return explicit, explicit.get_molecule_names(), {}, record
    modification_info = topology["modifications"].get(species_id)
    base_id = str(modification_info["reactant"]) if modification_info else ""
    base_entry = context.entries.get(base_id) if base_id else None

    sbo = modification_info.get("sbo") if modification_info else None
    resolved = sbo_modification(sbo) if sbo else None
    if resolved is not None and base_entry is not None:
        modification, kind = resolved
        structure = (
            _modified_species(base_entry, modification, item)
            if kind == "additive"
            else _removal_species(base_entry, modification)
        )
        if structure is not None:
            _sanitize_structure(structure)
            record = _structure_inference(
                species_id,
                name,
                structure,
                "sbo-term",
                f'SBML sboTerm "{sbo}" names the {modification.lower()} state '
                f'of species "{base_id}"',
            )
            _report_unparsed_fragments(
                context.model, species_id, name, unparsed
            )
            record.alternatives = alternatives
            return structure, [base_id], {"state": modification}, record

    name_candidates = _name_complex_candidates(name, context.names_to_ids)
    complex_components = topology_components
    if complex_components:
        components = list(complex_components)
        structure = _complex_species(components, context.entries, context.use_id)
        _sanitize_structure(structure)
        record = _structure_inference(
            species_id,
            name,
            structure,
            "reaction-topology",
            "reaction topology makes the species a complex of "
            + ", ".join(str(component) for component in components),
        )
        for separator, parts in name_candidates:
            if list(parts) != components:
                record.alternatives.append(
                    _alternative_inference(
                        "name-heuristic",
                        f'the species name splits on "{separator}" into '
                        + ", ".join(parts),
                        molecules=list(parts),
                    )
                )
        _report_unparsed_fragments(context.model, species_id, name, unparsed)
        record.alternatives.extend(alternatives)
        return structure, components, {}, record

    if base_id and base_entry is not None:
        modification = _modification_from_name(context, name, base_id)
        if modification:
            structure = _modified_species(base_entry, modification, item)
            _sanitize_structure(structure)
            record = _structure_inference(
                species_id,
                name,
                structure,
                "name-heuristic",
                f'the species name "{name}" names the '
                f'{modification.lower()} state of species "{base_id}"',
            )
            if resolved is not None and resolved[0] != modification:
                record.alternatives.append(
                    _alternative_inference(
                        "sbo-term",
                        f'SBML sboTerm "{sbo}" names '
                        f'{resolved[0].lower()} instead',
                        modification=resolved[0],
                    )
                )
            _report_unparsed_fragments(context.model, species_id, name, unparsed)
            record.alternatives.extend(alternatives)
            return structure, [base_id], {"state": modification}, record

    for candidate_base in context.modification_bases.get(species_id, []):
        if candidate_base == base_id:
            continue
        candidate_entry = context.entries.get(candidate_base)
        if candidate_entry is None:
            continue
        modification = _modification_from_name(context, name, candidate_base)
        if not modification:
            continue
        structure = _modified_species(candidate_entry, modification, item)
        _sanitize_structure(structure)
        record = _structure_inference(
            species_id,
            name,
            structure,
            "name-heuristic",
            f'the species name "{name}" names the '
            f'{modification.lower()} state of species "{candidate_base}"',
        )
        _report_unparsed_fragments(context.model, species_id, name, unparsed)
        record.alternatives.extend(alternatives)
        return structure, [candidate_base], {"state": modification}, record

    naming_bases = list(context.naming_dependencies.get(species_id) or [])
    if naming_bases:
        if len(naming_bases) == 1:
            naming_base = naming_bases[0]
            naming_entry = context.entries.get(naming_base)
            modification = (
                _modification_from_name(context, name, naming_base)
                if naming_entry is not None
                else None
            )
            if modification and naming_entry is not None:
                structure = _modified_species(naming_entry, modification, item)
                _sanitize_structure(structure)
                record = _structure_inference(
                    species_id,
                    name,
                    structure,
                    "name-heuristic",
                    f'the species name "{name}" names the '
                    f'{modification.lower()} state of species "{naming_base}"',
                )
                _report_unparsed_fragments(
                    context.model, species_id, name, unparsed
                )
                record.alternatives.extend(alternatives)
                return (
                    structure,
                    [naming_base],
                    {"state": modification},
                    record,
                )
        structure = _complex_species(naming_bases, context.entries, context.use_id)
        _sanitize_structure(structure)
        record = _structure_inference(
            species_id,
            name,
            structure,
            "name-heuristic",
            "the species name is a naming-convention variant of "
            + ", ".join(naming_bases),
        )
        _report_unparsed_fragments(context.model, species_id, name, unparsed)
        record.alternatives.extend(alternatives)
        return structure, naming_bases, {}, record

    if name_candidates:
        separator, parts = name_candidates[0]
        resolved_parts = [context.names_to_ids.get(part, part) for part in parts]
        structure = _complex_species(
            resolved_parts, context.entries, context.use_id
        )
        _sanitize_structure(structure)
        record = _structure_inference(
            species_id,
            name,
            structure,
            "name-heuristic",
            f'the species name splits on "{separator}" into '
            + ", ".join(parts),
        )
        for other_separator, other_parts in name_candidates[1:]:
            record.alternatives.append(
                _alternative_inference(
                    "name-heuristic",
                    f'the species name also splits on "{other_separator}" into '
                    + ", ".join(other_parts),
                    molecules=list(other_parts),
                )
            )
        record.alternatives.extend(alternatives)
        return structure, resolved_parts, {}, record

    structure = _elemental_species(item)
    _sanitize_structure(structure)
    record = _structure_inference(
        species_id,
        name,
        structure,
        "elemental",
        "the SBML source does not determine a molecular structure for the "
        "species, so the exact flat representation is kept",
    )
    for separator, parts in name_candidates:
        record.alternatives.append(
            _alternative_inference(
                "name-heuristic",
                f'the species name splits on "{separator}" into '
                + ", ".join(parts),
                molecules=list(parts),
            )
        )
    _report_unparsed_fragments(context.model, species_id, name, unparsed)
    record.alternatives.extend(alternatives)
    return structure, [], {}, record


def build_species_composition_table(
    model: SBMLModel,
    *,
    use_id: bool = False,
    use_annotations: bool = True,
    atomize: bool = False,
    naming_patterns: Optional[NamingPatternConfig] = None,
    naming_conventions: Optional[NamingConventions] = None,
    **_: object,
) -> SpeciesCompositionTable:
    species_ids = list(model.species.keys())
    species_order = {species_id: index for index, species_id in enumerate(species_ids)}
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

    naming_config = (
        naming_conventions if naming_conventions is not None else naming_patterns
    )
    naming = analyze_naming_conventions(
        [model.species[species_id].name or species_id for species_id in species_ids],
        naming_config,
    )
    naming_dependencies: Dict[str, List[str]] = OrderedDict()
    for pairs in naming["pairClassification"].values():
        for base_name, derived_name in pairs:
            base_id = names_to_ids.get(base_name)
            derived_id = names_to_ids.get(derived_name)
            if base_id and derived_id and base_id != derived_id:
                dependencies.setdefault(derived_id, set()).add(base_id)
                naming_dependencies.setdefault(derived_id, []).append(base_id)

    reverse: Dict[str, Set[str]] = OrderedDict()
    for species_id, deps in dependencies.items():
        for dependency in sorted(
            deps,
            key=lambda value: (species_order.get(value, len(species_order)), value),
        ):
            reverse.setdefault(dependency, set()).add(species_id)

    sorted_species = topological_sort(species_ids, dependencies)
    weights = compute_weights(species_ids, dependencies)
    entries: Dict[str, SCTEntry] = OrderedDict()
    inferences: Dict[str, StructuralInference] = OrderedDict()

    topology: Dict[str, object] = {
        "complexes": {},
        "modifications": {},
        "unbindings": {},
    }
    context: Optional[_StructuralContext] = None
    if atomize:
        topology = analyze_structural_topology(model)
        modification_bases: Dict[str, List[str]] = OrderedDict()
        for derived_id, base_id in modifications.items():
            modification_bases.setdefault(derived_id, []).append(base_id)
        for derived_id, info in topology["modifications"].items():
            base_id = str(info["reactant"])
            bases = modification_bases.setdefault(derived_id, [])
            if base_id not in bases:
                bases.append(base_id)
            dependencies.setdefault(derived_id, set()).add(base_id)
        for product_id, components in topology["complexes"].items():
            dependencies.setdefault(product_id, set()).update(components)
        for complex_id, components in topology["unbindings"].items():
            dependencies.setdefault(complex_id, set()).update(components)
        sorted_species = topological_sort(species_ids, dependencies)
        weights = compute_weights(species_ids, dependencies)
        context = _StructuralContext(
            model=model,
            entries=entries,
            topology=topology,
            naming_config=naming_config,
            use_id=use_id,
            names_to_ids=names_to_ids,
            binding=binding,
            modification_bases=modification_bases,
            naming_dependencies=naming_dependencies,
        )

    for species_id in sorted_species:
        item = model.species[species_id]
        item_name = item.name or species_id
        is_elemental = True
        components: List[str] = []
        modifications_info: Dict[str, str] = {}
        inference: Optional[StructuralInference] = None

        multi_pattern = (
            model.multi_species_patterns.get(species_id)
            if model.multi_executable
            else None
        )
        if multi_pattern:
            structure = read_from_string(multi_pattern)
            _sanitize_structure(structure)
            components = structure.get_molecule_names()
            is_elemental = False
        elif context is not None:
            structure, components, modifications_info, inference = (
                _infer_species_structure(species_id, item, context)
            )
            is_elemental = inference.is_elemental
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
            inference=inference,
        )
        if inference is not None:
            inferences[species_id] = inference

    elemental_count = sum(entry.is_elemental for entry in entries.values())
    from .helpers import logger

    logger.info(
        "SCT001",
        f"Built SCT: {len(entries)} species "
        f"({elemental_count} elemental, {len(entries) - elemental_count} complex)",
    )
    table = SpeciesCompositionTable(
        entries=entries,
        dependencies=dependencies,
        reverse_dependencies=reverse,
        sorted_species=sorted_species,
        weights=sorted(weights.items(), key=lambda item: item[1]),
        inferences=inferences,
    )
    reconcile_sct(
        table,
        get_molecule_types(
            table,
            model.multi_type_patterns.values() if model.multi_executable else None,
        ),
        preserve_partial=model.multi_executable,
    )
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


def get_molecule_types(
    sct: SpeciesCompositionTable,
    explicit_patterns: Optional[Sequence[str]] = None,
) -> List[Molecule]:
    molecule_types: Dict[str, Molecule] = OrderedDict()
    for entry in sct.entries.values():
        for molecule in entry.structure.molecules:
            if molecule.name not in molecule_types:
                molecule_types[molecule.name] = molecule.copy()
            else:
                _update_molecule_type(molecule_types[molecule.name], molecule)
    for pattern in explicit_patterns or []:
        try:
            parsed = read_from_string(pattern)
        except (TypeError, ValueError):
            continue
        for molecule in parsed.molecules:
            existing = molecule_types.get(molecule.name)
            if existing is None:
                molecule_types[molecule.name] = molecule.copy()
            else:
                _update_molecule_type(existing, molecule)
    return list(molecule_types.values())


def reconcile_sct(
    sct: SpeciesCompositionTable,
    molecule_types: Sequence[Molecule],
    preserve_partial: bool = False,
) -> None:
    if preserve_partial:
        # Multi species patterns may intentionally omit feature values or
        # outward binding sites.  Omission means don't-care in SBML Multi;
        # filling the molecule from its type would silently turn that into a
        # concrete BNGL state.
        return
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
    if model.multi_executable:
        # SBML Multi deliberately permits several fully-defined species and a
        # pattern species to share one speciesType.  Their identity is carried
        # by the Multi feature/binding semantics, not by synthetic BNGL state.
        return 0
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


def structural_report(sct: SpeciesCompositionTable) -> Dict[str, Any]:
    """Summarize the structural atomization decisions of one model.

    The report is machine readable: it names the inferred molecules, sites,
    bonds and states per species, the confidence of each decision, and the
    alternative readings that remain consistent with the SBML source.  The
    molecules, sites, bonds and states describe the structure that is
    actually emitted; the disambiguation discriminator is not a molecular
    feature and is therefore left out.
    """

    species: Dict[str, Any] = OrderedDict()
    confidence: Dict[str, int] = OrderedDict()
    uncertain: List[str] = []
    structural = 0
    for species_id, inference in sct.inferences.items():
        entry = sct.entries.get(species_id)
        structure = entry.structure if entry is not None else None
        molecules: List[str] = []
        sites: List[str] = []
        states: Dict[str, str] = {}
        bonds: List[Tuple[str, str]] = []
        if structure is not None:
            molecules = structure.get_molecule_names()
            for molecule in structure.molecules:
                for component in molecule.components:
                    if component.name == "__sp":
                        continue
                    if component.name not in sites:
                        sites.append(component.name)
                    if component.active_state:
                        states[component.name] = component.active_state
            bonds = list(structure.bonds)
        species[species_id] = {
            "species": inference.species_id,
            "name": inference.name,
            "molecules": molecules,
            "sites": sites,
            "bonds": [list(bond) for bond in bonds],
            "states": states,
            "confidence": inference.confidence,
            "reason": inference.reason,
            "alternatives": list(inference.alternatives),
        }
        confidence[inference.confidence] = (
            confidence.get(inference.confidence, 0) + 1
        )
        if inference.alternatives:
            uncertain.append(species_id)
        if inference.confidence != "elemental":
            structural += 1
    total = len(species)
    return {
        "species": species,
        "summary": {
            "species_total": total,
            "structural_species": structural,
            "elemental_species": total - structural,
            "confidence": confidence,
            "uncertain_species": uncertain,
        },
    }


def get_seed_species(
    sct: SpeciesCompositionTable, model: SBMLModel
) -> List[SeedSpeciesEntry]:
    initial_assignments = {item.symbol: item.math for item in model.initial_assignments}
    result: List[SeedSpeciesEntry] = []
    for species_id, entry in sct.entries.items():
        item = model.species[species_id]
        compartment = standardize_name(item.compartment or "Compartment")
        volume = f"__compartment_{compartment}__"
        amount_set = (
            item.initial_amount_set
            if item.initial_amount_set is not None
            else item.initial_amount != 0
        )
        concentration_set = (
            item.initial_concentration_set
            if item.initial_concentration_set is not None
            else item.initial_concentration != 0
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
analyzeNamingConventions = analyze_naming_conventions
analyzeReactions = analyze_reactions
buildSpeciesCompositionTable = build_species_composition_table
classifyReaction = classify_reaction
defineEditDistanceMatrix = define_edit_distance_matrix
disambiguateCollidingSpecies = disambiguate_colliding_species
findLongestSubstring = find_longest_substring
getMoleculeTypes = get_molecule_types
getSeedSpecies = get_seed_species
reconcileSCT = reconcile_sct
topologicalSort = topological_sort


__all__ = [
    "EditDistanceMatrixResult",
    "ModificationInference",
    "SBO_ADDITIVE_MODIFICATIONS",
    "SBO_REMOVAL_MODIFICATIONS",
    "MODIFICATION_SITES",
    "addToDependencyGraph",
    "add_to_dependency_graph",
    "analyzeNamingConventions",
    "analyze_naming_conventions",
    "analyzeReactions",
    "analyze_reactions",
    "analyze_structural_topology",
    "buildSpeciesCompositionTable",
    "build_species_composition_table",
    "classifyReaction",
    "classify_reaction",
    "compute_weights",
    "defineEditDistanceMatrix",
    "define_edit_distance_matrix",
    "disambiguateCollidingSpecies",
    "disambiguate_colliding_species",
    "get_differences",
    "getMoleculeTypes",
    "findLongestSubstring",
    "find_longest_substring",
    "getSeedSpecies",
    "get_molecule_types",
    "get_seed_species",
    "infer_modification",
    "levenshtein",
    "normalize_sbo_term",
    "reconcile_sct",
    "reconcileSCT",
    "sbo_modification",
    "similarity",
    "structural_report",
    "topologicalSort",
    "topological_sort",
]
