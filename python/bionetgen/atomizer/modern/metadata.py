"""Source-level SBML metadata accounting for the modern Atomizer.

SBML notes, CVTerms/MIRIAM annotations, SBO terms, and package declarations
are not kinetic state.  This module keeps their accounting separate from the
executable BNGL model so a round-trip report can distinguish preserved source
metadata from executable semantic parity.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from .types import SBMLModel

METADATA_PACKAGE_NAMES = ("layout", "render", "groups")
DEFAULT_PACKAGE_NAMESPACES: Dict[str, str] = {
    "layout": "http://www.sbml.org/sbml/level3/version1/layout/version1",
    "render": "http://www.sbml.org/sbml/level3/version1/render/version1",
    "groups": "http://www.sbml.org/sbml/level3/version1/groups/version1",
}
_XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
_PACKAGE_URI_RE = re.compile(
    r"^https?://www\.sbml\.org/sbml/level3/version\d+/([a-z][a-z0-9_]*)/version\d+$",
    re.IGNORECASE,
)


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _xml_package_name(uri: str) -> str:
    match = _PACKAGE_URI_RE.match(uri or "")
    return match.group(1).lower() if match else ""


def _xml_attr(element: Any, name: str, default: str = "") -> str:
    for key, value in getattr(element, "attrib", {}).items():
        if key == name or _xml_local_name(key) == name:
            return str(value)
    return default


def _xml_children(
    element: Any, local_name: str, package: Optional[str] = None
) -> List[Any]:
    if element is None:
        return []
    result = []
    for child in list(element):
        if _xml_local_name(child.tag) != local_name:
            continue
        if (
            package is not None
            and _xml_package_name(_xml_namespace(child.tag)) != package
        ):
            continue
        result.append(child)
    return result


def _register_package_namespaces(
    declared_packages: Optional[Mapping[str, str]] = None,
) -> None:
    """Register standard SBML metadata package prefixes for clean XML output."""
    ET.register_namespace("xsi", _XSI_NAMESPACE)
    for prefix, default_uri in DEFAULT_PACKAGE_NAMESPACES.items():
        uri = (declared_packages or {}).get(prefix) or default_uri
        ET.register_namespace(prefix, uri)


def _serialize_package_element(
    element: Any, declared_packages: Optional[Mapping[str, str]] = None
) -> str:
    _register_package_namespaces(declared_packages)
    return ET.tostring(element, encoding="unicode").strip()


def _parse_float(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_render_information(
    render_info: Any, *, layout_id: Optional[str] = None
) -> Dict[str, Any]:
    record: Dict[str, Any] = {}
    if layout_id is not None:
        record["layoutId"] = layout_id
    for attr_name in (
        "id",
        "name",
        "programName",
        "programVersion",
        "referenceRenderInformation",
        "backgroundColor",
    ):
        value = _xml_attr(render_info, attr_name)
        if value:
            record[attr_name] = value

    colors: List[Dict[str, str]] = []
    for color_list in _xml_children(render_info, "listOfColorDefinitions", "render"):
        for color in _xml_children(color_list, "colorDefinition", "render"):
            entry: Dict[str, str] = {}
            color_id = _xml_attr(color, "id")
            color_val = _xml_attr(color, "value")
            if color_id:
                entry["id"] = color_id
            if color_val:
                entry["value"] = color_val
            if entry:
                colors.append(entry)
    record["colorDefinitions"] = colors

    gradients: List[str] = []
    for grad_list in _xml_children(render_info, "listOfGradientDefinitions", "render"):
        for grad in list(grad_list):
            if _xml_package_name(_xml_namespace(grad.tag)) == "render":
                grad_id = _xml_attr(grad, "id")
                if grad_id:
                    gradients.append(grad_id)
    record["gradientDefinitions"] = gradients

    line_endings: List[str] = []
    for le_list in _xml_children(render_info, "listOfLineEndings", "render"):
        for le in _xml_children(le_list, "lineEnding", "render"):
            le_id = _xml_attr(le, "id")
            if le_id:
                line_endings.append(le_id)
    record["lineEndings"] = line_endings

    style_count = 0
    for style_list in _xml_children(render_info, "listOfStyles", "render"):
        style_count += len(_xml_children(style_list, "style", "render"))
    record["styleCount"] = style_count
    return record


def extract_package_metadata(
    root: Any,
    declared_packages: Optional[Mapping[str, str]] = None,
    package_required: Optional[Mapping[str, bool]] = None,
    package_counts: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """Extract lossless structured + raw XML metadata for layout, render, and groups.

    These SBML Level 3 packages carry diagram geometry, rendering styles, and
    element groupings rather than kinetic semantics.  Extracting them into a
    dedicated non-kinetic metadata dictionary preserves them across
    import/BNGIR/export without altering the executable BNGL model.
    """
    if root is None:
        return OrderedDict()
    model = next(
        (child for child in list(root) if _xml_local_name(child.tag) == "model"),
        None,
    )
    if model is None:
        return OrderedDict()

    declared = dict(declared_packages or {})
    required = dict(package_required or {})
    counts = dict(package_counts or {})

    # Discover package URIs directly from XML elements in case callers pass an
    # ElementTree without precomputed declared_packages.
    discovered_counts: Dict[str, int] = {}
    for elem in root.iter():
        uri = _xml_namespace(elem.tag)
        pkg = _xml_package_name(uri)
        if pkg in METADATA_PACKAGE_NAMES:
            declared.setdefault(pkg, uri)
            discovered_counts[pkg] = discovered_counts.get(pkg, 0) + 1
    for pkg, count in discovered_counts.items():
        counts.setdefault(pkg, count)

    result: Dict[str, Any] = OrderedDict()

    # 1. layout:listOfLayouts (and nested render global/local information)
    layout_lists = _xml_children(model, "listOfLayouts", "layout")
    global_render_records: List[Dict[str, Any]] = []
    local_render_records: List[Dict[str, Any]] = []
    global_render_xml: List[str] = []
    standalone_global_render_xml: List[str] = []
    local_render_xml: List[Dict[str, str]] = []

    if layout_lists:
        layouts: List[Dict[str, Any]] = []
        layout_raw_xml: List[str] = []
        for lol in layout_lists:
            layout_raw_xml.append(_serialize_package_element(lol, declared))
            # SBML L3 Render v1 places listOfGlobalRenderInformation inside
            # layout:listOfLayouts.
            for global_list in _xml_children(
                lol, "listOfGlobalRenderInformation", "render"
            ):
                global_render_xml.append(
                    _serialize_package_element(global_list, declared)
                )
                for ri in _xml_children(global_list, "renderInformation", "render"):
                    global_render_records.append(_extract_render_information(ri))

            for layout_elem in _xml_children(lol, "layout", "layout"):
                layout_id = _xml_attr(layout_elem, "id")
                entry: Dict[str, Any] = {
                    "id": layout_id,
                    "name": _xml_attr(layout_elem, "name"),
                }
                metaid = _xml_attr(layout_elem, "metaid")
                if metaid:
                    entry["metaid"] = metaid
                sbo = _xml_attr(layout_elem, "sboTerm")
                if sbo:
                    entry["sboTerm"] = sbo

                dims_children = _xml_children(layout_elem, "dimensions", "layout")
                if dims_children:
                    dims: Dict[str, float] = {}
                    for axis in ("width", "height", "depth"):
                        val = _parse_float(_xml_attr(dims_children[0], axis))
                        if val is not None:
                            dims[axis] = val
                    if dims:
                        entry["dimensions"] = dims

                comp_glyphs = []
                for cg_list in _xml_children(
                    layout_elem, "listOfCompartmentGlyphs", "layout"
                ):
                    for cg in _xml_children(cg_list, "compartmentGlyph", "layout"):
                        cg_entry = {
                            "id": _xml_attr(cg, "id"),
                            "compartment": _xml_attr(cg, "compartment"),
                        }
                        if _xml_attr(cg, "metaid"):
                            cg_entry["metaid"] = _xml_attr(cg, "metaid")
                        comp_glyphs.append(cg_entry)
                entry["compartmentGlyphs"] = comp_glyphs

                species_glyphs = []
                for sg_list in _xml_children(
                    layout_elem, "listOfSpeciesGlyphs", "layout"
                ):
                    for sg in _xml_children(sg_list, "speciesGlyph", "layout"):
                        sg_entry = {
                            "id": _xml_attr(sg, "id"),
                            "species": _xml_attr(sg, "species"),
                        }
                        if _xml_attr(sg, "metaid"):
                            sg_entry["metaid"] = _xml_attr(sg, "metaid")
                        species_glyphs.append(sg_entry)
                entry["speciesGlyphs"] = species_glyphs

                reaction_glyphs = []
                for rg_list in _xml_children(
                    layout_elem, "listOfReactionGlyphs", "layout"
                ):
                    for rg in _xml_children(rg_list, "reactionGlyph", "layout"):
                        srg_entries = []
                        for srg_list in _xml_children(
                            rg, "listOfSpeciesReferenceGlyphs", "layout"
                        ):
                            for srg in _xml_children(
                                srg_list, "speciesReferenceGlyph", "layout"
                            ):
                                srg_item: Dict[str, str] = {
                                    "id": _xml_attr(srg, "id"),
                                    "speciesGlyph": _xml_attr(srg, "speciesGlyph"),
                                }
                                if _xml_attr(srg, "speciesReference"):
                                    srg_item["speciesReference"] = _xml_attr(
                                        srg, "speciesReference"
                                    )
                                if _xml_attr(srg, "role"):
                                    srg_item["role"] = _xml_attr(srg, "role")
                                srg_entries.append(srg_item)
                        rg_entry: Dict[str, Any] = {
                            "id": _xml_attr(rg, "id"),
                            "reaction": _xml_attr(rg, "reaction"),
                            "speciesReferenceGlyphs": srg_entries,
                        }
                        reaction_glyphs.append(rg_entry)
                entry["reactionGlyphs"] = reaction_glyphs

                text_glyphs = []
                for tg_list in _xml_children(layout_elem, "listOfTextGlyphs", "layout"):
                    for tg in _xml_children(tg_list, "textGlyph", "layout"):
                        tg_entry: Dict[str, str] = {"id": _xml_attr(tg, "id")}
                        for attr_name in ("graphicalObject", "originOfText", "text"):
                            val = _xml_attr(tg, attr_name)
                            if val:
                                tg_entry[attr_name] = val
                        text_glyphs.append(tg_entry)
                entry["textGlyphs"] = text_glyphs

                extra_objs = []
                for extra_list in _xml_children(
                    layout_elem, "listOfAdditionalGraphicalObjects", "layout"
                ):
                    for obj in list(extra_list):
                        if _xml_package_name(_xml_namespace(obj.tag)) == "layout":
                            obj_entry = {"id": _xml_attr(obj, "id")}
                            if _xml_attr(obj, "metaid"):
                                obj_entry["metaid"] = _xml_attr(obj, "metaid")
                            extra_objs.append(obj_entry)
                entry["additionalGraphicalObjects"] = extra_objs

                # Local render info per SBML L3 Render v1 uses
                # render:listOfRenderInformation (also accept
                # render:listOfLocalRenderInformation defensively).
                local_ri_ids: List[str] = []
                for local_tag in (
                    "listOfRenderInformation",
                    "listOfLocalRenderInformation",
                ):
                    for local_list in _xml_children(layout_elem, local_tag, "render"):
                        local_render_xml.append(
                            {
                                "layoutId": layout_id,
                                "xml": _serialize_package_element(local_list, declared),
                            }
                        )
                        for ri in _xml_children(
                            local_list, "renderInformation", "render"
                        ):
                            rec = _extract_render_information(ri, layout_id=layout_id)
                            local_render_records.append(rec)
                            if rec.get("id"):
                                local_ri_ids.append(rec["id"])
                entry["localRenderInformationIds"] = local_ri_ids
                layouts.append(entry)

        result["layout"] = {
            "namespace": declared.get("layout", DEFAULT_PACKAGE_NAMESPACES["layout"]),
            "required": bool(required.get("layout", False)),
            "elementCount": int(counts.get("layout", 0)),
            "layouts": layouts,
            "rawXml": layout_raw_xml,
        }

    # 2. Standalone render:listOfGlobalRenderInformation directly under <model>
    for standalone_global in _xml_children(
        model, "listOfGlobalRenderInformation", "render"
    ):
        serialized = _serialize_package_element(standalone_global, declared)
        global_render_xml.append(serialized)
        standalone_global_render_xml.append(serialized)
        for ri in _xml_children(standalone_global, "renderInformation", "render"):
            global_render_records.append(_extract_render_information(ri))

    if global_render_xml or local_render_xml:
        result["render"] = {
            "namespace": declared.get("render", DEFAULT_PACKAGE_NAMESPACES["render"]),
            "required": bool(required.get("render", False)),
            "elementCount": int(counts.get("render", 0)),
            "globalRenderInformation": global_render_records,
            "localRenderInformation": local_render_records,
            "rawXml": {
                "globalXml": global_render_xml,
                "localXml": local_render_xml,
                "standaloneGlobalXml": standalone_global_render_xml,
            },
        }

    # 3. groups:listOfGroups
    group_lists = _xml_children(model, "listOfGroups", "groups")
    if group_lists:
        groups: List[Dict[str, Any]] = []
        group_raw_xml: List[str] = []
        for log in group_lists:
            group_raw_xml.append(_serialize_package_element(log, declared))
            for group_elem in _xml_children(log, "group", "groups"):
                group_entry: Dict[str, Any] = {
                    "id": _xml_attr(group_elem, "id"),
                    "name": _xml_attr(group_elem, "name"),
                    "kind": _xml_attr(group_elem, "kind"),
                }
                if _xml_attr(group_elem, "metaid"):
                    group_entry["metaid"] = _xml_attr(group_elem, "metaid")
                if _xml_attr(group_elem, "sboTerm"):
                    group_entry["sboTerm"] = _xml_attr(group_elem, "sboTerm")
                members: List[Dict[str, str]] = []
                for mem_list in _xml_children(group_elem, "listOfMembers", "groups"):
                    for mem in _xml_children(mem_list, "member", "groups"):
                        mem_entry: Dict[str, str] = {}
                        for attr_name in ("id", "name", "idRef", "metaIdRef"):
                            val = _xml_attr(mem, attr_name)
                            if val:
                                mem_entry[attr_name] = val
                        members.append(mem_entry)
                group_entry["members"] = members
                groups.append(group_entry)

        result["groups"] = {
            "namespace": declared.get("groups", DEFAULT_PACKAGE_NAMESPACES["groups"]),
            "required": bool(required.get("groups", False)),
            "elementCount": int(counts.get("groups", 0)),
            "groups": groups,
            "rawXml": group_raw_xml,
        }

    return result


def recover_package_metadata_from_payload(payload_text: str) -> Dict[str, Any]:
    """Recover preserved layout/render/groups metadata from a sourceMetadata payload."""
    if not payload_text:
        return OrderedDict()
    try:
        parsed = json.loads(payload_text)
    except ValueError:
        return OrderedDict()
    if not isinstance(parsed, Mapping):
        return OrderedDict()
    raw = parsed.get("packageMetadata")
    if not isinstance(raw, Mapping):
        return OrderedDict()
    recovered: Dict[str, Any] = OrderedDict()
    for name in METADATA_PACKAGE_NAMES:
        if isinstance(raw.get(name), Mapping):
            recovered[name] = dict(raw[name])
    return recovered


def attach_preserved_package_metadata(
    sbml_xml: str,
    source_metadata: Union[str, Mapping[str, Any]],
) -> str:
    """Re-attach preserved layout/render/groups XML blocks onto an L3 SBML string.

    The C++ ``SbmlWriter`` preserves the complete non-kinetic metadata payload
    inside ``<bng:sourceMetadata>``.  This Python export-side helper
    additionally re-attaches the native L3 ``<layout:listOfLayouts>`` (including
    nested ``render`` lists), standalone ``<render:listOfGlobalRenderInformation>``,
    and ``<groups:listOfGroups>`` blocks under ``<model>`` with their L3
    namespace declarations so downstream SBML/libSBML consumers see them
    directly without affecting kinetic execution.

    Level 2 documents are returned unchanged because L3 package namespaces are
    not valid in SBML Level 2.
    """
    if not sbml_xml or not source_metadata:
        return sbml_xml
    if isinstance(source_metadata, str):
        try:
            parsed: Any = json.loads(source_metadata)
        except ValueError:
            return sbml_xml
    else:
        parsed = source_metadata
    if not isinstance(parsed, Mapping):
        return sbml_xml

    pkg_meta = parsed.get("packageMetadata")
    if not isinstance(pkg_meta, Mapping):
        # Also accept a direct package_metadata dict.
        if any(name in parsed for name in METADATA_PACKAGE_NAMES):
            pkg_meta = parsed
        else:
            return sbml_xml

    sbml_open_match = re.search(r"<sbml\b[^>]*>", sbml_xml, flags=re.DOTALL)
    if sbml_open_match is None:
        return sbml_xml
    sbml_open = sbml_open_match.group(0)
    level_match = re.search(r'\blevel\s*=\s*["\'](\d+)["\']', sbml_open)
    if level_match is not None and int(level_match.group(1)) < 3:
        return sbml_xml
    model_close_idx = sbml_xml.rfind("</model>")
    if model_close_idx < 0:
        return sbml_xml

    blocks: List[str] = []
    needed_namespaces: Dict[str, str] = OrderedDict()

    layout_info = pkg_meta.get("layout")
    if isinstance(layout_info, Mapping):
        raw_layouts = layout_info.get("rawXml") or []
        if raw_layouts and "<layout:listOfLayouts" not in sbml_xml:
            needed_namespaces["layout"] = str(
                layout_info.get("namespace") or DEFAULT_PACKAGE_NAMESPACES["layout"]
            )
            for block in raw_layouts:
                text = str(block).strip()
                if text:
                    blocks.append(text)
                    if "render:" in text or "/render/" in text:
                        render_info = pkg_meta.get("render")
                        render_ns = (
                            str(render_info.get("namespace"))
                            if isinstance(render_info, Mapping)
                            and render_info.get("namespace")
                            else DEFAULT_PACKAGE_NAMESPACES["render"]
                        )
                        needed_namespaces.setdefault("render", render_ns)

    render_info = pkg_meta.get("render")
    if isinstance(render_info, Mapping):
        raw_render = render_info.get("rawXml")
        standalone = (
            raw_render.get("standaloneGlobalXml", [])
            if isinstance(raw_render, Mapping)
            else []
        )
        if standalone and "<render:listOfGlobalRenderInformation" not in sbml_xml:
            needed_namespaces["render"] = str(
                render_info.get("namespace") or DEFAULT_PACKAGE_NAMESPACES["render"]
            )
            for block in standalone:
                text = str(block).strip()
                if text:
                    blocks.append(text)

    groups_info = pkg_meta.get("groups")
    if isinstance(groups_info, Mapping):
        raw_groups = groups_info.get("rawXml") or []
        if raw_groups and "<groups:listOfGroups" not in sbml_xml:
            needed_namespaces["groups"] = str(
                groups_info.get("namespace") or DEFAULT_PACKAGE_NAMESPACES["groups"]
            )
            for block in raw_groups:
                text = str(block).strip()
                if text:
                    blocks.append(text)

    if not blocks:
        return sbml_xml

    attr_additions: List[str] = []
    for prefix, uri in needed_namespaces.items():
        if not re.search(rf"\bxmlns:{re.escape(prefix)}\s*=", sbml_open):
            attr_additions.append(f'xmlns:{prefix}="{uri}"')
        if not re.search(rf"\b{re.escape(prefix)}:required\s*=", sbml_open):
            attr_additions.append(f'{prefix}:required="false"')

    updated_open = sbml_open
    if attr_additions:
        updated_open = sbml_open[:-1] + " " + " ".join(attr_additions) + ">"

    indented_blocks = "\n".join(
        "\n".join(f"    {line}" if line.strip() else "" for line in block.splitlines())
        for block in blocks
    )
    before_model_close = sbml_xml[:model_close_idx]
    if before_model_close and not before_model_close.endswith("\n"):
        before_model_close += "\n"
    after_model_close = sbml_xml[model_close_idx:]
    updated = f"{before_model_close}{indented_blocks}\n{after_model_close}"
    if updated_open != sbml_open:
        updated = (
            updated[: sbml_open_match.start()]
            + updated_open
            + updated[sbml_open_match.end() :]
        )
    return updated


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
    package_metadata = getattr(model, "package_metadata", None) or {}
    preserved_metadata_packages = sorted(
        pkg for pkg in METADATA_PACKAGE_NAMES if pkg in package_metadata
    )
    source_present = bool(
        model_fields["notesXml"]
        or model_fields["annotationXml"]
        or model_fields["sboTerm"]
        or metadata_entity_count
        or cvterm_count
        or packages
        or preserved_metadata_packages
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
        "preservedMetadataPackages": preserved_metadata_packages,
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
    payload: Dict[str, Any] = {
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
    package_metadata = getattr(model, "package_metadata", None) or {}
    if summary["preservedMetadataPackages"]:
        payload["preservedMetadataPackages"] = list(
            summary["preservedMetadataPackages"]
        )
        counts: Dict[str, int] = {}
        if "layout" in package_metadata:
            counts["layouts"] = len(package_metadata["layout"].get("layouts") or [])
        if "render" in package_metadata:
            counts["globalRenderInformation"] = len(
                package_metadata["render"].get("globalRenderInformation") or []
            )
            counts["localRenderInformation"] = len(
                package_metadata["render"].get("localRenderInformation") or []
            )
        if "groups" in package_metadata:
            counts["groups"] = len(package_metadata["groups"].get("groups") or [])
        payload["preservedPackageCounts"] = counts
    return payload


def source_metadata_payload(model: SBMLModel) -> str:
    """Serialize source metadata for the executable SBML writer channel.

    The payload is intentionally separate from the generated BNGL comment:
    comments are useful diagnostics, while this compact JSON document is an
    opaque, namespaced SBML annotation that can survive a normal C++ export.
    Raw notes/annotation XML is retained per source entity and preserved
    layout/render/groups package metadata (structured + raw XML) is included
    when present; no metadata is interpreted as executable kinetics.
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
    package_metadata = getattr(model, "package_metadata", None) or {}
    if (
        not any(value for value in model_fields.values())
        and not entities
        and not packages
        and not package_metadata
    ):
        return ""

    payload: Dict[str, Any] = {
        "schemaVersion": 1,
        "model": {
            "id": model.id,
            "name": model.name,
            **model_fields,
        },
        "packages": packages,
        "entities": entities,
    }
    if package_metadata:
        payload["packageMetadata"] = dict(package_metadata)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
