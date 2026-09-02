"""Annotation parsing and lightweight MIRIAM helpers for modern Atomizer.

The public RuleWorld/bngplayground annotation parser is the source contract
for this module.  Network-backed ontology resolution remains outside this
pure data layer; callers can use the existing optional legacy resolver when
they explicitly need remote enrichment.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .types import AnnotationInfo, SBMLModel, SBMLSpecies

BIOLOGICAL_QUALIFIER_NAMES = {
    0: "BQB_IS",
    1: "BQB_HAS_PART",
    2: "BQB_IS_PART_OF",
    3: "BQB_IS_VERSION_OF",
    4: "BQB_HAS_VERSION",
    5: "BQB_IS_HOMOLOG_TO",
    6: "BQB_IS_DESCRIBED_BY",
    7: "BQB_IS_ENCODED_BY",
    8: "BQB_ENCODES",
    9: "BQB_OCCURS_IN",
    10: "BQB_HAS_PROPERTY",
    11: "BQB_IS_PROPERTY_OF",
    12: "BQB_HAS_TAXON",
    13: "BQB_UNKNOWN",
}

MODEL_QUALIFIER_NAMES = {
    0: "BQM_IS",
    1: "BQM_IS_DESCRIBED_BY",
    2: "BQM_IS_DERIVED_FROM",
    3: "BQM_IS_INSTANCE_OF",
    4: "BQM_HAS_INSTANCE",
    5: "BQM_UNKNOWN",
}


@dataclass(frozen=True)
class ParsedAnnotation:
    species_id: str
    species_name: str
    qualifier_type: str
    qualifier: str
    resources: List[str]
    database: str
    identifier: str


@dataclass
class AnnotationStats:
    total_species: int
    annotated_species: int
    annotation_count: int
    database_distribution: Dict[str, int] = field(default_factory=dict)
    qualifier_distribution: Dict[str, int] = field(default_factory=dict)
    coverage_percent: float = 0.0


_DATABASE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("uniprot", re.compile(r"uniprot[:/]([A-Z0-9]+)", re.IGNORECASE)),
    ("go", re.compile(r"GO[:/](\d+)", re.IGNORECASE)),
    ("chebi", re.compile(r"CHEBI[:/](\d+)", re.IGNORECASE)),
    (
        "kegg",
        re.compile(
            r"kegg\.(compound|reaction|pathway)[:/]([A-Za-z0-9]+)", re.IGNORECASE
        ),
    ),
    ("reactome", re.compile(r"reactome[:/]([A-Z0-9_]+)", re.IGNORECASE)),
    ("biomodels", re.compile(r"biomodels\.db[:/](BIOMD\d+)", re.IGNORECASE)),
    ("pubmed", re.compile(r"pubmed[:/](\d+)", re.IGNORECASE)),
    ("doi", re.compile(r"doi[:/](10\.\d+/[^\s]+)", re.IGNORECASE)),
    ("obo", re.compile(r"obo\.([A-Z]+)[:/]([A-Z0-9_:]+)", re.IGNORECASE)),
    ("ncbiTaxon", re.compile(r"taxonomy[:/](\d+)", re.IGNORECASE)),
    ("ensembl", re.compile(r"ensembl[:/]([A-Z0-9]+)", re.IGNORECASE)),
    ("interpro", re.compile(r"interpro[:/](IPR\d+)", re.IGNORECASE)),
    ("pfam", re.compile(r"pfam[:/](PF\d+)", re.IGNORECASE)),
    ("ec", re.compile(r"ec-code[:/](\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)),
)


def parse_resource_uri(uri: str) -> Tuple[str, str]:
    """Return ``(database, identifier)`` using reference parser precedence."""

    resource = str(uri)
    for database, pattern in _DATABASE_PATTERNS:
        match = pattern.search(resource)
        if match:
            # Keep the public reference behavior for multi-capture patterns:
            # the first capture is the identifier.
            return database, match.group(1) or (
                match.group(2) if match.lastindex else ""
            )

    identifiers_match = re.search(
        r"identifiers\.org/([^/]+)/([^/\s]+)", resource, re.IGNORECASE
    )
    if identifiers_match:
        return identifiers_match.group(1), identifiers_match.group(2)

    generic_match = re.search(r"/([^/]+)/([^/\s]+)$", resource)
    if generic_match:
        return "unknown", generic_match.group(2)

    return "unknown", resource


def parse_species_annotations(species: SBMLSpecies) -> List[ParsedAnnotation]:
    """Expand each SBML CV-term resource into a normalized annotation."""

    result: List[ParsedAnnotation] = []
    for annotation in species.annotations:
        if annotation.qualifier_type == 1:
            qualifier_type = "biological"
            qualifier = BIOLOGICAL_QUALIFIER_NAMES.get(
                (
                    annotation.biological_qualifier
                    if annotation.biological_qualifier is not None
                    else 13
                ),
                "BQB_UNKNOWN",
            )
        else:
            qualifier_type = "model"
            qualifier = MODEL_QUALIFIER_NAMES.get(
                (
                    annotation.model_qualifier
                    if annotation.model_qualifier is not None
                    else 5
                ),
                "BQM_UNKNOWN",
            )

        for resource in annotation.resources:
            database, identifier = parse_resource_uri(resource)
            result.append(
                ParsedAnnotation(
                    species_id=species.id,
                    species_name=species.name,
                    qualifier_type=qualifier_type,
                    qualifier=qualifier,
                    resources=[resource],
                    database=database,
                    identifier=identifier,
                )
            )
    return result


def get_all_annotations(model: SBMLModel) -> "OrderedDict[str, List[ParsedAnnotation]]":
    result: "OrderedDict[str, List[ParsedAnnotation]]" = OrderedDict()
    for species_id, species in model.species.items():
        annotations = parse_species_annotations(species)
        if annotations:
            result[species_id] = annotations
    return result


def get_annotations_by_database(
    model: SBMLModel, database: str
) -> "OrderedDict[str, List[ParsedAnnotation]]":
    result: "OrderedDict[str, List[ParsedAnnotation]]" = OrderedDict()
    for species_id, species in model.species.items():
        annotations = [
            annotation
            for annotation in parse_species_annotations(species)
            if annotation.database.lower() == database.lower()
        ]
        if annotations:
            result[species_id] = annotations
    return result


def get_annotations_by_qualifier(
    model: SBMLModel, qualifier_type: str, qualifier: Optional[str] = None
) -> "OrderedDict[str, List[ParsedAnnotation]]":
    result: "OrderedDict[str, List[ParsedAnnotation]]" = OrderedDict()
    for species_id, species in model.species.items():
        annotations = [
            annotation
            for annotation in parse_species_annotations(species)
            if annotation.qualifier_type == qualifier_type
            and (qualifier is None or annotation.qualifier == qualifier)
        ]
        if annotations:
            result[species_id] = annotations
    return result


def get_annotations_by_qualifier_resources(
    annotations: Iterable[AnnotationInfo], qualifier: int, is_biological: bool = True
) -> List[str]:
    """Return raw resources matching a Playground qualifier enum value."""

    result: List[str] = []
    for annotation in annotations:
        if (
            is_biological
            and annotation.qualifier_type == 1
            and annotation.biological_qualifier == qualifier
        ) or (
            not is_biological
            and annotation.qualifier_type == 0
            and annotation.model_qualifier == qualifier
        ):
            result.extend(annotation.resources)
    return result


def find_equivalent_species(model: SBMLModel) -> "OrderedDict[str, List[str]]":
    """Group species sharing BQB_IS or BQB_IS_VERSION_OF resources."""

    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for species_id, species in model.species.items():
        for annotation in parse_species_annotations(species):
            if annotation.qualifier not in {"BQB_IS", "BQB_IS_VERSION_OF"}:
                continue
            key = f"{annotation.database}:{annotation.identifier}"
            members = groups.setdefault(key, [])
            if species_id not in members:
                members.append(species_id)

    return OrderedDict(
        (key, members) for key, members in groups.items() if len(members) > 1
    )


def get_canonical_species(
    equivalence_map: Mapping[str, Iterable[str]], model: SBMLModel
) -> Dict[str, str]:
    """Map non-canonical members to shortest-name species in each group."""

    result: Dict[str, str] = {}
    for members in equivalence_map.values():
        member_list = list(members)
        if not member_list:
            continue
        canonical = min(
            member_list,
            key=lambda species_id: (
                len(
                    model.species.get(species_id, SBMLSpecies(species_id)).name
                    or species_id
                ),
                model.species.get(species_id, SBMLSpecies(species_id)).name
                or species_id,
            ),
        )
        for species_id in member_list:
            if species_id != canonical:
                result[species_id] = canonical
    return result


def build_rdf_database(
    model: SBMLModel, filter_string: Optional[Iterable[str]] = None
) -> "OrderedDict[str, List[str]]":
    """Group species by raw RDF resource, sorted by display-name length."""

    filters = list(filter_string or [])
    database: "OrderedDict[str, List[str]]" = OrderedDict()
    for species_id, species in model.species.items():
        for annotation in parse_species_annotations(species):
            resource = annotation.resources[0]
            if filters and not any(item in resource for item in filters):
                continue
            members = database.setdefault(resource, [])
            if species_id not in members:
                members.append(species_id)

    for resource, members in database.items():
        members.sort(
            key=lambda species_id: len(
                model.species.get(species_id, SBMLSpecies(species_id)).name
                or species_id
            )
        )
    return database


def get_equivalence(
    species_id: str, rdf_database: Mapping[str, List[str]]
) -> List[str]:
    for members in rdf_database.values():
        if species_id not in members:
            continue
        return [] if members.index(species_id) == 0 else [members[0]]
    return []


def compute_annotation_stats(model: SBMLModel) -> AnnotationStats:
    annotated_species = 0
    annotation_count = 0
    database_distribution: Dict[str, int] = {}
    qualifier_distribution: Dict[str, int] = {}

    for species in model.species.values():
        annotations = parse_species_annotations(species)
        if not annotations:
            continue
        annotated_species += 1
        annotation_count += len(annotations)
        for annotation in annotations:
            database_distribution[annotation.database] = (
                database_distribution.get(annotation.database, 0) + 1
            )
            qualifier_distribution[annotation.qualifier] = (
                qualifier_distribution.get(annotation.qualifier, 0) + 1
            )

    total_species = len(model.species)
    return AnnotationStats(
        total_species=total_species,
        annotated_species=annotated_species,
        annotation_count=annotation_count,
        database_distribution=database_distribution,
        qualifier_distribution=qualifier_distribution,
        coverage_percent=(
            (annotated_species / total_species * 100) if total_species else 0.0
        ),
    )


def extract_uniprot_accessions(model: SBMLModel) -> Dict[str, List[str]]:
    return {
        species_id: [
            annotation.identifier
            for annotation in parse_species_annotations(species)
            if annotation.database == "uniprot"
        ]
        for species_id, species in model.species.items()
        if any(
            annotation.database == "uniprot"
            for annotation in parse_species_annotations(species)
        )
    }


def annotations_to_yaml(
    model: SBMLModel, annotation_map: Mapping[str, Iterable[ParsedAnnotation]]
) -> str:
    lines: List[str] = []
    for species_id, annotations in annotation_map.items():
        species = model.species.get(species_id)
        name = (species.name if species is not None else "") or species_id
        lines.extend([f"{species_id}:", f"  name: {name}", "  annotations:"])
        for annotation in annotations:
            resource = annotation.resources[0] if annotation.resources else ""
            lines.extend(
                [
                    f"    - qualifier: {annotation.qualifier}",
                    f"      database: {annotation.database}",
                    f"      identifier: {annotation.identifier}",
                    f"      uri: {resource}",
                ]
            )
    return "\n".join(lines)


def annotations_to_json(
    model: SBMLModel, annotation_map: Mapping[str, Iterable[ParsedAnnotation]]
) -> str:
    data: Dict[str, object] = {}
    for species_id, annotations in annotation_map.items():
        species = model.species.get(species_id)
        name = (species.name if species is not None else "") or species_id
        data[species_id] = {
            "name": name,
            "annotations": [
                {
                    "qualifier": annotation.qualifier,
                    "database": annotation.database,
                    "identifier": annotation.identifier,
                    "uri": annotation.resources[0] if annotation.resources else "",
                }
                for annotation in annotations
            ],
        }
    return json.dumps(data, indent=2, ensure_ascii=False)


__all__ = [
    "AnnotationStats",
    "ParsedAnnotation",
    "annotations_to_json",
    "annotations_to_yaml",
    "build_rdf_database",
    "compute_annotation_stats",
    "extract_uniprot_accessions",
    "find_equivalent_species",
    "getAnnotationsByQualifier",
    "get_all_annotations",
    "get_annotations_by_database",
    "get_annotations_by_qualifier",
    "get_annotations_by_qualifier_resources",
    "get_canonical_species",
    "get_equivalence",
    "parse_resource_uri",
    "parse_species_annotations",
]


# Keep the exact public name exported by the TypeScript parser.
getAnnotationsByQualifier = get_annotations_by_qualifier_resources
