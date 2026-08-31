"""Playground-derived SBML atomizer for BNG3.

The implementation follows the public ``RuleWorld/bngplayground`` pipeline:
string-based SBML parsing, structured BNGL patterns, reaction classification,
species-composition inference, collision disambiguation, and canonical BNGL
writing.  It is intentionally independent of the legacy atomizer modules so
the two paths can be compared during the migration.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from .core import (
    analyze_naming_conventions,
    analyze_reactions,
    build_species_composition_table,
    classify_reaction,
    compute_weights,
    define_edit_distance_matrix,
    disambiguate_colliding_species,
    get_differences,
    get_molecule_types,
    get_seed_species,
    infer_modification,
    levenshtein,
    reconcile_sct,
    similarity,
    topological_sort,
)
from .parser import SBMLParser, extract_go_terms, extract_uniprot_ids
from .multi import MultiParseResult, parse_multi_package
from .events import (
    EventTranslationContext,
    EventTranslationResult,
    fold_numeric,
    parse_time_threshold,
    synthesize_event_actions,
)
from .structures import Component, Molecule, Species, read_from_string
from .types import *  # noqa: F401,F403
from .writer import (
    bngl_function,
    convert_math_expression,
    extend_function,
    generate_bngl,
    write_compartments,
    write_functions,
    write_molecule_types,
    write_observables,
    write_parameters,
    write_reaction_rules,
    write_seed_species,
)
from .units import apply_unit_scaling, resolve_unit_factor, unit_conversion_factor

DEFAULT_ATOMIZER_OPTIONS: Dict[str, Any] = {
    "use_id": False,
    "annotation": False,
    "atomize": False,
    "quiet_mode": False,
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
        self.databases: Dict[str, Any] = {}

    def set_options(self, options: Mapping[str, Any]) -> None:
        self.options.update(options)

    def get_options(self) -> Dict[str, Any]:
        return dict(self.options)

    def atomize(self, sbml_string: str) -> AtomizerResult:
        try:
            self.model = self.parser.parse(sbml_string)
            self.sct = build_species_composition_table(
                self.model,
                use_id=bool(self.options.get("use_id", False)),
                use_annotations=bool(self.options.get("annotation", False)),
                atomize=bool(self.options.get("atomize", False)),
                naming_patterns=self.options.get("naming_patterns"),
            )
            disambiguated = disambiguate_colliding_species(self.sct, self.model)
            molecule_types = get_molecule_types(self.sct)
            reconcile_sct(self.sct, molecule_types)
            seed_species = get_seed_species(self.sct, self.model)
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
            self.databases = {
                "model": self.model,
                "sct": self.sct,
                "molecule_types": molecule_types,
                "seed_species": seed_species,
            }
            annotation = (
                self._annotation_data() if self.options.get("annotation") else None
            )
            log = [
                f"Parsed SBML model: {len(self.model.species)} species, {len(self.model.reactions)} reactions",
                f"Disambiguated {disambiguated} colliding species",
                f"Found {len(molecule_types)} molecule types",
            ]
            return AtomizerResult(
                bngl=bngl,
                database=self.databases,
                annotation=annotation,
                observable_map=observable_map,
                log=log,
                success=True,
            )
        except Exception as exc:
            return AtomizerResult(
                bngl="",
                database=self.databases,
                annotation=None,
                observable_map={},
                log=[],
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

    def get_databases(self) -> Dict[str, Any]:
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
        self.databases = {}

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
            },
            "compartments": {
                compartment_id: {
                    "name": compartment.name,
                    "dimensions": compartment.spatial_dimensions,
                    "size": compartment.size,
                }
                for compartment_id, compartment in self.model.compartments.items()
            },
        }


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


__all__ = [
    "Atomizer",
    "BNGL_LEXER_KEYWORDS",
    "Component",
    "EventTranslationContext",
    "EventTranslationResult",
    "Molecule",
    "MultiParseResult",
    "SBMLParser",
    "Species",
    "analyze_naming_conventions",
    "analyze_reactions",
    "apply_unit_scaling",
    "build_species_composition_table",
    "bngl_function",
    "classify_reaction",
    "disambiguate_colliding_species",
    "extend_function",
    "extract_go_terms",
    "extract_uniprot_ids",
    "fold_numeric",
    "generate_bngl",
    "get_molecule_types",
    "get_seed_species",
    "read_from_string",
    "resolve_unit_factor",
    "parse_time_threshold",
    "parse_multi_package",
    "sbml_to_bngl",
    "sbml_to_bngl_atomized",
    "sbml_to_bngl_flat",
    "synthesize_event_actions",
    "unit_conversion_factor",
]
