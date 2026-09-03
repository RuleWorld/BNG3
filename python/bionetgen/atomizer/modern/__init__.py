"""Playground-derived SBML atomizer for BNG3.

The implementation follows the public ``RuleWorld/bngplayground`` pipeline:
string-based SBML parsing, structured BNGL patterns, reaction classification,
species-composition inference, collision disambiguation, and canonical BNGL
writing.  It is intentionally independent of the legacy atomizer modules so
the two paths can be compared during the migration.
"""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from typing import Any, Dict, Iterable, Mapping, Optional

from .core import (
    EditDistanceMatrixResult,
    ModificationInference,
    addToDependencyGraph,
    add_to_dependency_graph,
    analyzeNamingConventions,
    analyze_naming_conventions,
    analyzeReactions,
    analyze_reactions,
    buildSpeciesCompositionTable,
    build_species_composition_table,
    classifyReaction,
    classify_reaction,
    compute_weights,
    defineEditDistanceMatrix,
    define_edit_distance_matrix,
    disambiguateCollidingSpecies,
    disambiguate_colliding_species,
    findLongestSubstring,
    find_longest_substring,
    getMoleculeTypes,
    get_differences,
    get_molecule_types,
    get_seed_species,
    getSeedSpecies,
    infer_modification,
    levenshtein,
    reconcile_sct,
    similarity,
    topological_sort,
    topologicalSort,
)
from .parser import (
    SBMLParser,
    extractGOTerms,
    extractUniProtIds,
    extract_go_terms,
    extract_uniprot_ids,
)
from .multi import MultiParseResult, parse_multi_package
from .events import (
    EventActionsResult,
    EventSet,
    EventTranslationContext,
    EventTranslationResult,
    foldNumeric,
    fold_numeric,
    parseTimeThreshold,
    parse_time_threshold,
    synthesize_event_actions,
)
from .structures import (
    Action,
    AtomicPatternResult,
    Component,
    Databases,
    Molecule,
    Rule,
    Species,
    States,
    readFromString,
    read_from_string,
)
from .types import *  # noqa: F401,F403
from .writer import (
    BNGLGenerationResult,
    ReversibleRateSplit,
    bnglFunction,
    bnglReaction,
    bngl_function,
    bngl_reaction,
    convert_math_expression,
    curateParameters,
    curate_parameters,
    extend_function,
    generateBNGL,
    generate_bngl,
    inlineSBMLFunctions,
    inline_sbml_functions,
    splitReversibleRate,
    split_reversible_rate,
    write_compartments,
    write_functions,
    write_molecule_types,
    write_observables,
    write_parameters,
    write_reaction_rules,
    write_seed_species,
)
from .units import apply_unit_scaling, resolve_unit_factor, unit_conversion_factor
from .helpers import (
    BindingException,
    Counter,
    CycleError,
    DefaultDict,
    LogMessage,
    Logger,
    Memoize,
    MemoizeMapped,
    TranslationException,
    cleanParameterValue,
    clean_parameter_value,
    comb,
    compareLists,
    compare_lists,
    convertMathFunction,
    convert_math_function,
    deepCopy,
    deep_copy,
    factorial,
    isNode,
    isValidBNGLName,
    is_valid_bngl_name,
    logMess,
    log_mess,
    logger,
    longestCommonSubstring,
    longest_common_substring,
    pmemoize,
    randInt,
    rand_int,
    sequenceMatcherRatio,
    sequence_matcher_ratio,
    setDifference,
    setIntersection,
    setUnion,
    set_difference,
    set_intersection,
    set_union,
    standardizeName,
)
from .annotation import (
    AnnotationStats,
    ParsedAnnotation,
    annotations_to_json,
    annotations_to_yaml,
    build_rdf_database,
    compute_annotation_stats,
    extract_uniprot_accessions,
    find_equivalent_species,
    get_all_annotations,
    getAnnotationsByQualifier,
    get_annotations_by_database,
    get_annotations_by_qualifier,
    get_canonical_species,
    get_equivalence,
    parse_resource_uri,
    parse_species_annotations,
)
from .bng_xml import convertBNGXmlToBNGL, convert_bng_xml_to_bngl
from .rulifier import (
    StateTransition,
    StateTransitionDiagram,
    TransformationCenter,
    TransformationContext,
    analyze_rate_law,
    build_state_transition_diagram,
    collapse_redundant_rules,
    extract_parameters,
    extract_transformation_center,
    find_redundant_rules,
    group_by_reaction_center,
    species_equal,
)
from .uniprot import (
    UniProtEntry,
    clear_uniprot_cache,
    fetch_uniprot_entry,
)

DEFAULT_ATOMIZER_OPTIONS: Dict[str, Any] = {
    "use_id": False,
    "annotation": False,
    "atomize": False,
    "quiet_mode": False,
    "log_level": "WARNING",
    "actions": "",
    "t_end": 10,
    "n_steps": 100,
}


class Atomizer:
    """Convert SBML text to BNGL using the modern atomization pipeline."""

    def __init__(
        self, options: Optional[Mapping[str, Any]] = None, **kwargs: Any
    ) -> None:
        self.options = dict(DEFAULT_ATOMIZER_OPTIONS)
        if options:
            self.options.update(options)
        self.options.update(kwargs)
        self.parser = SBMLParser()
        self.model = None
        self.sct = None
        self.databases = Databases()
        self._configure_logger()

    def _configure_logger(self) -> None:
        level = self.options.get("logLevel", self.options.get("log_level", "WARNING"))
        quiet_mode = self.options.get(
            "quietMode", self.options.get("quiet_mode", False)
        )
        logger.setLevel(str(level).upper())
        logger.setQuietMode(bool(quiet_mode))

    def set_options(self, options: Mapping[str, Any]) -> None:
        self.options.update(options)
        self._configure_logger()

    def get_options(self) -> Dict[str, Any]:
        return dict(self.options)

    @staticmethod
    def _threshold(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            return float("nan")

    def _should_use_large_flat_fast_path(self, sbml_string: str) -> bool:
        if self.options.get("atomize"):
            return False
        if os.environ.get("ATOMIZER_LARGE_FASTPATH", "1") == "0":
            return False
        min_species = self._threshold("ATOMIZER_FASTPATH_MIN_SPECIES", 1500)
        min_reactions = self._threshold("ATOMIZER_FASTPATH_MIN_REACTIONS", 800)
        min_sbml_chars = self._threshold("ATOMIZER_FASTPATH_MIN_SBML_CHARS", 5000000)
        return (
            len(self.model.species) >= min_species
            or len(self.model.reactions) >= min_reactions
            or len(sbml_string) >= min_sbml_chars
        )

    @staticmethod
    def _initial_amount_expression(species: SBMLSpecies) -> str:
        try:
            amount = float(species.initial_amount)
        except (TypeError, ValueError):
            amount = float("nan")
        if math.isfinite(amount) and amount > 0:
            return str(int(amount)) if amount.is_integer() else format(amount, ".15g")

        try:
            concentration = float(species.initial_concentration)
        except (TypeError, ValueError):
            concentration = float("nan")
        if math.isfinite(concentration) and concentration > 0:
            compartment = standardizeName(species.compartment or "Compartment")
            value = (
                str(int(concentration))
                if concentration.is_integer()
                else format(concentration, ".15g")
            )
            return f"({value} * __Avogadro__ * __compartment_{compartment}__)"
        return "0"

    @staticmethod
    def _build_large_flat_artifacts(
        model: SBMLModel,
    ) -> tuple[SpeciesCompositionTable, list[Molecule], list[SeedSpeciesEntry]]:
        entries: Dict[str, SCTEntry] = OrderedDict()
        dependencies: Dict[str, set] = OrderedDict()
        reverse_dependencies: Dict[str, set] = OrderedDict()
        sorted_species = []
        weights = []
        molecule_types: Dict[str, Molecule] = OrderedDict()
        seed_species = []
        used_molecule_names = set()

        def unique_molecule_name(base: str, index: int) -> str:
            if base not in used_molecule_names:
                used_molecule_names.add(base)
                return base
            candidate = index
            while f"{base}_{candidate}" in used_molecule_names:
                candidate += 1
            name = f"{base}_{candidate}"
            used_molecule_names.add(name)
            return name

        for row, (species_id, source_species) in enumerate(model.species.items(), 1):
            base_name = standardizeName(
                species_id or source_species.name or f"sp_{row}"
            )
            molecule_name = unique_molecule_name(base_name, row)
            structure = Species()
            structure.add_molecule(Molecule(molecule_name))
            structure.renumber_bonds()

            entries[species_id] = SCTEntry(
                structure=structure,
                components=[],
                sbml_id=species_id,
                is_elemental=True,
                modifications={},
                weight=0,
                bonds=[],
            )
            dependencies[species_id] = set()
            reverse_dependencies[species_id] = set()
            sorted_species.append(species_id)
            weights.append((species_id, 0))
            molecule_types.setdefault(molecule_name, Molecule(molecule_name))
            seed_species.append(
                SeedSpeciesEntry(
                    species=structure.copy(),
                    concentration=Atomizer._initial_amount_expression(source_species),
                    compartment=source_species.compartment,
                    sbml_id=species_id,
                )
            )

        return (
            SpeciesCompositionTable(
                entries=entries,
                dependencies=dependencies,
                reverse_dependencies=reverse_dependencies,
                sorted_species=sorted_species,
                weights=weights,
            ),
            list(molecule_types.values()),
            seed_species,
        )

    def atomize(self, sbml_string: str) -> AtomizerResult:
        try:
            logger.info("ATM003", "Parsing SBML model...")
            self.model = self.parser.parse(sbml_string)
            logger.info(
                "ATM004",
                f'Model "{self.model.name}": {len(self.model.species)} species, '
                f"{len(self.model.reactions)} reactions",
            )
            if self._should_use_large_flat_fast_path(sbml_string):
                logger.warning(
                    "ATM011",
                    f"Large-model flat fast path enabled "
                    f"(species={len(self.model.species)}, "
                    f"reactions={len(self.model.reactions)}, "
                    f"sbmlChars={len(sbml_string)})",
                )
                self.sct, molecule_types, seed_species = (
                    self._build_large_flat_artifacts(self.model)
                )
                bngl, observable_map = generate_bngl(
                    self.model,
                    self.sct,
                    molecule_types,
                    seed_species,
                    atomize=False,
                    actions=str(self.options.get("actions", "") or ""),
                    t_end=float(self.options.get("t_end", 10) or 10),
                    n_steps=int(self.options.get("n_steps", 100) or 100),
                )
                return AtomizerResult(
                    bngl=bngl,
                    database=self.databases,
                    annotation=None,
                    observable_map=observable_map,
                    log=logger.getMessages(),
                    success=True,
                )
            logger.info("ATM005", "Building species composition table...")
            self.sct = build_species_composition_table(
                self.model,
                use_id=bool(self.options.get("use_id", False)),
                use_annotations=bool(self.options.get("annotation", False)),
                atomize=bool(self.options.get("atomize", False)),
                naming_patterns=self.options.get("naming_patterns"),
            )
            disambiguated = disambiguate_colliding_species(self.sct, self.model)
            if disambiguated > 0:
                logger.info(
                    "ATM008",
                    f"Disambiguated {disambiguated} colliding species (isoform collapse)",
                )
            molecule_types = get_molecule_types(self.sct)
            logger.info("ATM006", f"Found {len(molecule_types)} molecule types")
            reconcile_sct(self.sct, molecule_types)
            seed_species = get_seed_species(self.sct, self.model)
            logger.info("ATM007", f"Found {len(seed_species)} seed species")
            logger.info("ATM008", "Generating BNGL model...")
            bngl, observable_map = generate_bngl(
                self.model,
                self.sct,
                molecule_types,
                seed_species,
                atomize=bool(self.options.get("atomize", False)),
                actions=str(self.options.get("actions", "") or ""),
                t_end=float(self.options.get("t_end", 10) or 10),
                n_steps=int(self.options.get("n_steps", 100) or 100),
            )
            logger.info("ATM009", "BNGL generation complete")
            annotation = (
                self._annotation_data() if self.options.get("annotation") else None
            )
            return AtomizerResult(
                bngl=bngl,
                database=self.databases,
                annotation=annotation,
                observable_map=observable_map,
                log=logger.getMessages(),
                success=True,
            )
        except Exception as exc:
            logger.error("ATM010", f"Atomization failed: {exc}")
            return AtomizerResult(
                bngl="",
                database=self.databases,
                annotation=None,
                observable_map={},
                log=logger.getMessages(),
                success=False,
                error=str(exc),
            )

    def flat_translation(self, sbml_string: str) -> AtomizerResult:
        previous = self.options.get("atomize", False)
        self.options["atomize"] = False
        try:
            return self.atomize(sbml_string)
        finally:
            self.options["atomize"] = previous

    def full_atomization(self, sbml_string: str) -> AtomizerResult:
        previous = self.options.get("atomize", False)
        self.options["atomize"] = True
        try:
            return self.atomize(sbml_string)
        finally:
            self.options["atomize"] = previous

    def get_model(self):
        return self.model

    def get_sct(self):
        return self.sct

    def get_databases(self) -> Databases:
        return self.databases

    def get_uniprot_ids(self, species_id: str) -> list:
        if self.model is None or species_id not in self.model.species:
            return []
        resources = [
            resource
            for annotation in self.model.species[species_id].annotations
            for resource in annotation.resources
        ]
        return extract_uniprot_ids(resources)

    def analyze_naming(self):
        if self.model is None:
            return None
        return analyze_naming_conventions(
            [item.name or item_id for item_id, item in self.model.species.items()]
        )

    def analyze_reaction_patterns(self):
        return analyze_reactions(self.model) if self.model is not None else None

    def clear(self) -> None:
        self.model = None
        self.sct = None
        self.databases = Databases()
        logger.clear()

    def _annotation_data(self) -> Dict[str, Any]:
        if self.model is None:
            return {}
        return {
            "species": {
                species_id: {
                    "name": species.name,
                    "annotations": [
                        {
                            "type": annotation.qualifier_type,
                            "biologicalQualifier": annotation.biological_qualifier,
                            "modelQualifier": annotation.model_qualifier,
                            "resources": list(annotation.resources),
                        }
                        for annotation in species.annotations
                    ],
                }
                for species_id, species in self.model.species.items()
                if species.annotations
            },
            "reactions": {},
            "compartments": {
                compartment_id: {
                    "name": compartment.name,
                    "dimensions": compartment.spatial_dimensions,
                    "size": compartment.size,
                }
                for compartment_id, compartment in self.model.compartments.items()
            },
        }


# Preserve the public method spellings from the TypeScript Atomizer facade
# alongside BNG3's snake_case Python API.
Atomizer.setOptions = Atomizer.set_options
Atomizer.getOptions = Atomizer.get_options
Atomizer.flatTranslation = Atomizer.flat_translation
Atomizer.fullAtomization = Atomizer.full_atomization
Atomizer.getModel = Atomizer.get_model
Atomizer.getSCT = Atomizer.get_sct
Atomizer.getUniProtIds = Atomizer.get_uniprot_ids
Atomizer.getDatabases = Atomizer.get_databases
Atomizer.analyzeNaming = Atomizer.analyze_naming
Atomizer.analyzeReactionPatterns = Atomizer.analyze_reaction_patterns


def sbml_to_bngl(
    sbml_string: str, options: Optional[Mapping[str, Any]] = None, **kwargs: Any
) -> AtomizerResult:
    return Atomizer(options, **kwargs).atomize(sbml_string)


def sbml_to_bngl_flat(
    sbml_string: str, options: Optional[Mapping[str, Any]] = None, **kwargs: Any
) -> AtomizerResult:
    return Atomizer(options, atomize=False, **kwargs).flat_translation(sbml_string)


def sbml_to_bngl_atomized(
    sbml_string: str, options: Optional[Mapping[str, Any]] = None, **kwargs: Any
) -> AtomizerResult:
    return Atomizer(options, atomize=True, **kwargs).full_atomization(sbml_string)


# Preserve the TypeScript convenience-function spellings for direct callers.
sbmlToBngl = sbml_to_bngl
sbmlToBnglFlat = sbml_to_bngl_flat
sbmlToBnglAtomized = sbml_to_bngl_atomized


__all__ = [
    "Action",
    "Atomizer",
    "AtomicPatternResult",
    "AnnotationStats",
    "BindingException",
    "BNGLGenerationResult",
    "BNGL_LEXER_KEYWORDS",
    "Component",
    "Counter",
    "CycleError",
    "DefaultDict",
    "Databases",
    "EditDistanceMatrixResult",
    "EventActionsResult",
    "EventSet",
    "EventTranslationContext",
    "EventTranslationResult",
    "LogMessage",
    "Logger",
    "Memoize",
    "MemoizeMapped",
    "Molecule",
    "ModificationInference",
    "MultiParseResult",
    "ParsedAnnotation",
    "Rule",
    "ReversibleRateSplit",
    "SBMLParser",
    "Species",
    "States",
    "StateTransition",
    "StateTransitionDiagram",
    "TransformationCenter",
    "TransformationContext",
    "TranslationException",
    "UniProtEntry",
    "analyze_naming_conventions",
    "analyzeNamingConventions",
    "analyze_reactions",
    "analyzeReactions",
    "analyze_rate_law",
    "annotations_to_json",
    "annotations_to_yaml",
    "apply_unit_scaling",
    "addToDependencyGraph",
    "add_to_dependency_graph",
    "build_state_transition_diagram",
    "build_species_composition_table",
    "buildSpeciesCompositionTable",
    "cleanParameterValue",
    "clean_parameter_value",
    "convertBNGXmlToBNGL",
    "convert_bng_xml_to_bngl",
    "bngl_function",
    "bnglFunction",
    "bnglReaction",
    "bngl_reaction",
    "curateParameters",
    "curate_parameters",
    "classify_reaction",
    "classifyReaction",
    "clear_uniprot_cache",
    "comb",
    "compareLists",
    "compare_lists",
    "compute_annotation_stats",
    "collapse_redundant_rules",
    "convertMathFunction",
    "convert_math_function",
    "deepCopy",
    "deep_copy",
    "defineEditDistanceMatrix",
    "define_edit_distance_matrix",
    "disambiguate_colliding_species",
    "disambiguateCollidingSpecies",
    "extend_function",
    "extract_go_terms",
    "extractGOTerms",
    "extractUniProtIds",
    "extract_uniprot_accessions",
    "extract_uniprot_ids",
    "extract_parameters",
    "extract_transformation_center",
    "factorial",
    "find_equivalent_species",
    "findLongestSubstring",
    "find_longest_substring",
    "find_redundant_rules",
    "fold_numeric",
    "foldNumeric",
    "fetch_uniprot_entry",
    "generate_bngl",
    "generateBNGL",
    "inlineSBMLFunctions",
    "inline_sbml_functions",
    "get_molecule_types",
    "getMoleculeTypes",
    "get_all_annotations",
    "getAnnotationsByQualifier",
    "get_annotations_by_database",
    "get_annotations_by_qualifier",
    "get_canonical_species",
    "get_equivalence",
    "get_seed_species",
    "getSeedSpecies",
    "group_by_reaction_center",
    "build_rdf_database",
    "isNode",
    "isValidBNGLName",
    "is_valid_bngl_name",
    "levenshtein",
    "logMess",
    "log_mess",
    "logger",
    "longestCommonSubstring",
    "longest_common_substring",
    "pmemoize",
    "randInt",
    "rand_int",
    "read_from_string",
    "readFromString",
    "resolve_unit_factor",
    "parse_time_threshold",
    "parseTimeThreshold",
    "parse_multi_package",
    "parse_resource_uri",
    "parse_species_annotations",
    "sbml_to_bngl",
    "sbml_to_bngl_atomized",
    "sbml_to_bngl_flat",
    "sbmlToBngl",
    "sbmlToBnglAtomized",
    "sbmlToBnglFlat",
    "species_equal",
    "splitReversibleRate",
    "split_reversible_rate",
    "sequenceMatcherRatio",
    "sequence_matcher_ratio",
    "setDifference",
    "setIntersection",
    "setUnion",
    "set_difference",
    "set_intersection",
    "set_union",
    "similarity",
    "topological_sort",
    "topologicalSort",
    "synthesize_event_actions",
    "standardizeName",
    "unit_conversion_factor",
]
