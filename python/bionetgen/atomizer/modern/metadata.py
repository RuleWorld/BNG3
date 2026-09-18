"""Source-level SBML metadata accounting for the modern Atomizer.

SBML notes, CVTerms/MIRIAM annotations, SBO terms, and package declarations
are not kinetic state.  This module keeps their accounting separate from the
executable BNGL model so a round-trip report can distinguish preserved source
metadata from executable semantic parity.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any, Dict, Iterable, Mapping

from .types import SBMLModel


def _metadata_fields(item: Any) -> Dict[str, Any]:
    return {
        "metaid": getattr(item, "metaid", None),
        "sboTerm": getattr(item, "sbo_term", None),
        "notesXml": getattr(item, "notes_xml", "") or "",
        "annotationXml": getattr(item, "annotation_xml", "") or "",
    }


def _collections(model: SBMLModel) -> Iterable[tuple[str, Iterable[Any]]]:
    yield "compartments", model.compartments.values()
    yield "species", model.species.values()
    yield "parameters", model.parameters.values()
    yield "reactions", model.reactions.values()
    yield "rules", model.rules
    yield "functionDefinitions", model.function_definitions.values()
    yield "events", model.events
    yield "initialAssignments", model.initial_assignments


def source_metadata_summary(model: SBMLModel) -> Dict[str, Any]:
    """Return deterministic counts and preservation status for source metadata."""

    collections: Dict[str, Dict[str, int]] = OrderedDict()
    metadata_entity_count = 0
    notes_count = 0
    annotation_count = 0
    sbo_term_count = 0
    metaid_count = 0
    for collection_name, items in _collections(model):
        total = 0
        notes = 0
        annotations = 0
        sbo_terms = 0
        metaids = 0
        for item in items:
            total += 1
            fields = _metadata_fields(item)
            metaids += bool(fields["metaid"])
            notes += bool(fields["notesXml"])
            annotations += bool(fields["annotationXml"])
            sbo_terms += bool(fields["sboTerm"])
        collections[collection_name] = {
            "total": total,
            "notes": notes,
            "annotations": annotations,
            "sboTerms": sbo_terms,
            "metaids": metaids,
        }
        metadata_entity_count += notes + annotations + sbo_terms + metaids
        notes_count += notes
        annotation_count += annotations
        sbo_term_count += sbo_terms
        metaid_count += metaids

    species_cvterm_count = sum(
        len(getattr(species, "annotations", []) or [])
        for species in model.species.values()
    )
    species_resource_count = sum(
        len(annotation.resources)
        for species in model.species.values()
        for annotation in (getattr(species, "annotations", []) or [])
    )
    model_fields = _metadata_fields(model)
    all_items = [model]
    species_item_ids = set()
    for _collection_name, items in _collections(model):
        values = list(items)
        all_items.extend(values)
        if _collection_name == "species":
            species_item_ids = {id(item) for item in values}
    raw_annotation_xml = [
        _metadata_fields(item)["annotationXml"]
        for item in all_items
        if _metadata_fields(item)["annotationXml"]
    ]
    raw_resource_count = sum(
        len(re.findall(r"(?:[A-Za-z_][A-Za-z0-9_.-]*:)?resource\s*=", value))
        for value in raw_annotation_xml
    )
    resource_count = max(species_resource_count, raw_resource_count)
    # Species CVTerms are parsed into structured records.  For other SBML
    # elements retain a conservative one-term count per annotated element;
    # exact source XML remains available on the corresponding model object.
    cvterm_count = (
        species_cvterm_count
        + sum(
            1
            for item in all_items
            if item is not model
            and id(item) not in species_item_ids
            and _metadata_fields(item)["annotationXml"]
        )
        + bool(model_fields["annotationXml"])
    )
    model_metadata_count = sum(
        bool(model_fields[field])
        for field in ("metaid", "notesXml", "annotationXml", "sboTerm")
    )
    metadata_entity_count += model_metadata_count
    notes_count += bool(model_fields["notesXml"])
    annotation_count += bool(model_fields["annotationXml"])
    sbo_term_count += bool(model_fields["sboTerm"])
    metaid_count += bool(model_fields["metaid"])
    package_names = sorted(
        set(model.declared_packages)
        | set(model.package_counts)
        | set(model.package_required)
    )
    packages = OrderedDict(
        (
            package,
            {
                "namespace": model.declared_packages.get(package, ""),
                "required": bool(model.package_required.get(package, False)),
                "elementCount": int(model.package_counts.get(package, 0)),
            },
        )
        for package in package_names
    )
    source_present = bool(
        model_fields["notesXml"]
        or model_fields["annotationXml"]
        or model_fields["sboTerm"]
        or metadata_entity_count
        or cvterm_count
        or packages
    )
    return {
        "schemaVersion": 1,
        "sourcePresent": source_present,
        "model": {
            "metaid": model_fields["metaid"],
            "sboTerm": model_fields["sboTerm"],
            "notesPresent": bool(model_fields["notesXml"]),
            "annotationPresent": bool(model_fields["annotationXml"]),
        },
        "packages": packages,
        "cvTerms": cvterm_count,
        "annotationResources": resource_count,
        "metadataEntities": metadata_entity_count,
        "notes": notes_count,
        "annotations": annotation_count,
        "sboTerms": sbo_term_count,
        "metaids": metaid_count,
        "collections": collections,
        # The modern parser retains source fields.  BNGL comments classify
        # them, while the optional C++ SBML writer channel preserves the
        # machine-readable payload as non-kinetic annotation.
        "intermediateModelPreserved": True,
        "executableBnglPreserved": False,
        "executableSbmlPayloadPreserved": bool(
            getattr(model, "source_metadata_payload", "")
        ),
        "classification": (
            "opaque source metadata payload preserved in executable SBML "
            "annotation; executable BNGL remains non-kinetic classification"
            if getattr(model, "source_metadata_payload", "")
            else "source metadata retained in the intermediate model and "
            "reported; executable BNGL remains non-kinetic classification"
        ),
    }


def metadata_payload(model: SBMLModel) -> Dict[str, Any]:
    """Return a compact machine-readable payload suitable for BNGL comments."""

    summary = source_metadata_summary(model)
    payload = {
        "schemaVersion": summary["schemaVersion"],
        "modelId": model.id,
        "modelName": model.name,
        "model": summary["model"],
        "packages": summary["packages"],
        "cvTerms": summary["cvTerms"],
        "annotationResources": summary["annotationResources"],
        "metadataEntities": summary["metadataEntities"],
        "notes": summary["notes"],
        "annotations": summary["annotations"],
        "sboTerms": summary["sboTerms"],
        "metaids": summary["metaids"],
        "executableBnglPreserved": summary["executableBnglPreserved"],
    }
    return payload


def source_metadata_payload(model: SBMLModel) -> str:
    """Serialize source metadata for the executable SBML writer channel.

    The payload is intentionally separate from the generated BNGL comment:
    comments are useful diagnostics, while this compact JSON document is an
    opaque, namespaced SBML annotation that can survive a normal C++ export.
    Raw notes/annotation XML is retained per source entity; no metadata is
    interpreted as executable kinetics.
    """

    def record(collection: str, item_id: str, item: Any) -> Dict[str, Any]:
        return {
            "collection": collection,
            "id": item_id,
            **_metadata_fields(item),
        }

    entities = []
    for collection, items in _collections(model):
        for item in items:
            item_id = getattr(item, "id", None) or getattr(item, "variable", None)
            fields = _metadata_fields(item)
            if item_id and any(value for value in fields.values()):
                entities.append(record(collection, str(item_id), item))

    model_fields = _metadata_fields(model)
    packages = source_metadata_summary(model)["packages"]
    if (
        not any(value for value in model_fields.values())
        and not entities
        and not packages
    ):
        return ""

    payload = {
        "schemaVersion": 1,
        "model": {
            "id": model.id,
            "name": model.name,
            **model_fields,
        },
        "packages": packages,
        "entities": entities,
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
