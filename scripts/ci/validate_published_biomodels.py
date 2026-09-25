#!/usr/bin/env python3
"""Validate every manually curated BioModels SBML record.

The official BioModels search API is the inventory source.  Every returned
record is retained in the report: SBML records go through the modern
Atomizer, C++ network generation, C++ SBML writing, modern SBML re-import,
the native C++ SBML reader, and direct BNG3-CVODE/libRoadRunner observable
comparison; non-SBML records are explicitly reported as unsupported by this
SBML path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np

USER_AGENT = "BNG3-curated-BioModels-roundtrip-validator/2"
NUMERICAL_COMPARISON_ATOL_FLOOR = 5e-12
# libRoadRunner and BNG3 use independent CVODE builds and Jacobian paths;
# retain a small model-scale floor for cross-engine dense-output differences.
NUMERICAL_COMPARISON_RTOL_FLOOR = 1e-5


def _json_compatible(value: Any) -> Any:
    """Replace IEEE non-finite numbers with JSON null recursively."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read().decode("utf-8-sig")


def _search_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("models", "results"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    hits = payload.get("hits")
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        return [
            row.get("_source", row) for row in hits["hits"] if isinstance(row, dict)
        ]
    return []


def _row_id(row: dict[str, Any]) -> str:
    value = row.get("id") or row.get("modelId") or row.get("model_id")
    return str(value or "").strip()


def _format_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or value)
    return str(value or "").strip()


def _record_files(record: dict[str, Any]) -> Iterable[dict[str, Any]]:
    files = record.get("files", {})
    if isinstance(files, dict):
        main = files.get("main", [])
    else:
        main = files
    if isinstance(main, dict):
        main = [main]
    if isinstance(main, list):
        return [item for item in main if isinstance(item, dict)]
    return []


def _enrich_record(
    row: dict[str, Any], manifest: dict[str, Any], offline: bool, fetch_metadata: bool
) -> dict[str, Any]:
    model_id = _row_id(row)
    result: dict[str, Any] = {
        "id": model_id,
        "name": str(row.get("name") or row.get("modelName") or model_id),
        "format": _format_text(
            row.get("format") or row.get("modelFormat") or row.get("formatName")
        ),
        "mime_type": "",
        "file_size": "",
    }
    record_url = manifest["record_api_url_template"].format(id=model_id)
    result["record_url"] = record_url
    if fetch_metadata and not offline:
        record = _fetch_json(record_url)
        result["format"] = _format_text(
            record.get("format") or record.get("modelFormat") or result["format"]
        )
        result["name"] = str(record.get("name") or result["name"])
        files = list(_record_files(record))
        if files:
            item = files[0]
            result["filename"] = str(
                item.get("name")
                or item.get("filename")
                or item.get("fileName")
                or f"{model_id}_url.xml"
            )
            result["mime_type"] = str(item.get("mimeType") or "")
            result["file_size"] = str(item.get("fileSize") or "")
            checksum = item.get("sha256sum") or item.get("sha256")
            if checksum:
                result["sha256"] = str(checksum).lower()
    result.setdefault("filename", f"{model_id}_url.xml")
    result["download_url"] = manifest["download_url_template"].format(
        id=model_id, filename=urllib.parse.quote(result["filename"])
    )
    return result


def _is_declared_sbml(entry: dict[str, Any]) -> bool:
    return "sbml" in str(entry.get("format", "")).lower()


def _is_archive_entry(entry: dict[str, Any]) -> bool:
    description = " ".join(
        str(entry.get(key, "")) for key in ("format", "filename", "mime_type")
    ).lower()
    return (
        "combine" in description
        or ".omex" in description
        or ".zip" in description
        or "application/zip" in description
    )


def _update_cached_artifact_metadata(
    inventory: dict[str, Any], manifest: dict[str, Any]
) -> bool:
    """Resolve main-file metadata for non-SBML records in an old cache."""

    changed = False
    for entry in inventory.get("models", []):
        if _is_declared_sbml(entry):
            continue
        try:
            record = _fetch_json(entry["record_url"])
        except Exception:
            continue
        files = list(_record_files(record))
        if not files:
            continue
        item = files[0]
        filename = str(
            item.get("name")
            or item.get("filename")
            or item.get("fileName")
            or entry.get("filename", "")
        )
        checksum = str(
            item.get("sha256sum") or item.get("sha256") or entry.get("sha256", "")
        ).lower()
        updated = {
            "filename": filename,
            "mime_type": str(item.get("mimeType") or ""),
            "file_size": str(item.get("fileSize") or ""),
            "sha256": checksum,
            "download_url": manifest["download_url_template"].format(
                id=entry["id"], filename=urllib.parse.quote(filename)
            ),
        }
        for key, value in updated.items():
            if value and entry.get(key) != value:
                entry[key] = value
                changed = True
    return changed


def _enumerate_inventory(
    manifest: dict[str, Any],
    cache_dir: Path,
    refresh: bool,
    offline: bool,
    fetch_metadata: bool,
) -> dict[str, Any]:
    cache_path = cache_dir / manifest["inventory_cache_name"]
    if cache_path.exists() and not refresh:
        inventory = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            fetch_metadata
            and not offline
            and _update_cached_artifact_metadata(inventory, manifest)
        ):
            cache_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )
        return inventory
    if offline:
        raise RuntimeError(f"offline inventory cache is missing: {cache_path}")

    page_size = int(manifest["page_size"])
    query = manifest["curation_query"]
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    total: int | None = None
    offset = 0
    while total is None or offset < total:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "format": "json",
                "numResults": page_size,
                "offset": offset,
            }
        )
        payload = _fetch_json(f"{manifest['search_api_url']}?{params}")
        if total is None:
            total = int(payload.get("matches") or payload.get("total") or 0)
        rows = _search_rows(payload)
        if not rows and offset < total:
            raise RuntimeError(f"BioModels search page at offset {offset} was empty")
        for row in rows:
            model_id = _row_id(row)
            if model_id and model_id not in seen:
                seen.add(model_id)
                models.append(
                    _enrich_record(
                        row, manifest, offline=False, fetch_metadata=fetch_metadata
                    )
                )
        offset += page_size

    inventory = {
        "schema_version": 1,
        "source": manifest["search_api_url"],
        "query": query,
        "matches": total,
        "models": models,
        "format_counts": dict(Counter(item["format"] for item in models)),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def _download_if_needed(path: Path, entry: dict[str, Any]) -> str:
    expected = entry.get("sha256")
    if not path.exists() or (expected and _sha256(path) != expected):
        try:
            request = urllib.request.Request(
                entry["download_url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
        except Exception:
            # Most records use the stable ``{id}_url.xml`` name, but the
            # record endpoint is authoritative for models whose main file
            # has a different name.  Resolve that only on a failed default
            # download so the full inventory remains fast.
            record = _fetch_json(entry["record_url"])
            files = list(_record_files(record))
            if not files:
                raise
            item = files[0]
            entry["filename"] = str(
                item.get("name")
                or item.get("filename")
                or item.get("fileName")
                or entry["filename"]
            )
            checksum = item.get("sha256sum") or item.get("sha256")
            if checksum:
                entry["sha256"] = str(checksum).lower()
            entry["download_url"] = entry["download_url"].split("?", 1)[0] + (
                "?filename=" + urllib.parse.quote(entry["filename"])
            )
            request = urllib.request.Request(
                entry["download_url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
        path.write_bytes(data)
    expected = entry.get("sha256")
    actual = _sha256(path)
    if expected and actual != expected:
        raise RuntimeError(
            f"sha256 mismatch for {path.name}: expected {expected}, got {actual}"
        )
    return actual


def _validate_xml(text: str, label: str) -> dict[str, Any]:
    try:
        import libsbml
    except ImportError:
        ET.fromstring(text)
        return {"passed": True, "validator": "xml.etree"}
    document = libsbml.readSBMLFromString(text)
    errors = int(document.getNumErrors())
    if errors:
        messages = [
            document.getError(index).getMessage() for index in range(min(errors, 5))
        ]
        raise RuntimeError(f"{label} has {errors} libSBML error(s): {messages}")
    consistency_errors = int(document.checkInternalConsistency())
    if consistency_errors:
        raise RuntimeError(
            f"{label} has {consistency_errors} libSBML consistency error(s)"
        )
    return {"passed": True, "validator": "libsbml", "errors": errors}


def _warnings(model: Any) -> list[dict[str, Any]]:
    return [
        {
            "category": warning.category,
            "message": warning.message,
            "severity": warning.severity,
        }
        for warning in model.import_warnings
    ]


def _merge_generated_warnings(
    source_warnings: list[dict[str, Any]], generated_warnings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge writer diagnostics, replacing parser-only event summaries."""

    if any(warning.get("category") == "event" for warning in generated_warnings):
        source_warnings = [
            warning for warning in source_warnings if warning.get("category") != "event"
        ]
    for warning in generated_warnings:
        if warning not in source_warnings:
            source_warnings.append(warning)
    return source_warnings


def _unsupported_causes(reason: str) -> list[str]:
    """Normalize an unsupported reason into auditable semantic cause labels."""

    lower = str(reason or "").lower()
    causes: list[str] = []
    for package in (
        "comp",
        "fbc",
        "qual",
        "spatial",
        "arrays",
        "distrib",
        "dyn",
        "multi",
    ):
        if f'"{package}" package' in lower or f"package:{package}" in lower:
            causes.append(f"package:{package}")
    if "event" in lower:
        causes.append("events")
    if "algebraic rule" in lower:
        causes.append("algebraic_rules")
    if "assignment rule targets species" in lower or "speciesassignmentrule" in lower:
        causes.append("species_assignment_rules")
    if "stoichiometr" in lower:
        causes.append("stoichiometry")
    if "fast-equilibrium" in lower or "marked fast" in lower:
        causes.append("fast_reactions")
    if "conversionfactor" in lower or "conversion factor" in lower:
        causes.append("conversion_factors")
    if "reaction-local" in lower or "no bngl-wide scope" in lower:
        causes.append("local_scope")
    if any(
        marker in lower
        for marker in (
            "mathml",
            "treated as rational",
            "gcd(",
            "lcm(",
            "rateof",
            "delay",
        )
    ):
        causes.append("mathml")
    if "constraint" in lower:
        causes.append("constraints")
    if "negative numeric rate" in lower or "nonnegative reaction rate" in lower:
        causes.append("negative_rates")
    if "no species" in lower or "no species or rate-rule" in lower:
        causes.append("no_state_variables")
    if "no reactants or products" in lower:
        causes.append("reaction_participants")
    if "no usable sbml" in lower or "not an sbml" in lower:
        causes.append("format")
    if not causes:
        causes.append("other")
    return list(dict.fromkeys(causes))


def _record_ref(record: dict[str, Any]) -> str:
    category = str(record.get("category", "")).strip()
    identifier = str(record.get("id", "")).strip()
    return f"{category}/{identifier}" if category else identifier


def _stoichiometry_subcauses(reason: str) -> list[str]:
    """Split the broad stoichiometry boundary into semantic subcauses."""

    lower = str(reason or "").lower()
    subcauses: list[str] = []
    if "variable stoichiometry" in lower or "stoichiometrymath" in lower:
        subcauses.append("dynamic_or_stoichiometryMath")
    raw_values = re.findall(
        r"unsupported stoichiometry\s+(-?(?:\d+(?:\.\d*)?|\.\d+))", lower
    )
    if any(raw.startswith("-") for raw in raw_values):
        subcauses.append("constant_negative")
    if any(
        not raw.startswith("-") and abs(float(raw) - round(float(raw))) > 1e-12
        for raw in raw_values
    ):
        subcauses.append("constant_noninteger")
    if any(
        not raw.startswith("-") and abs(float(raw) - round(float(raw))) <= 1e-12
        for raw in raw_values
    ) and any(float(raw) > 100 for raw in raw_values):
        subcauses.append("constant_integer_above_expansion_limit")
    if "non-integer reaction stoichiometry" in lower:
        subcauses.append("constant_noninteger")
    if "above the bngl expansion limit" in lower:
        subcauses.append("constant_integer_above_expansion_limit")
    if "stoichiometr" in lower and not subcauses:
        subcauses.append("unclassified_stoichiometry")
    return list(dict.fromkeys(subcauses))


def _unsupported_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach cause labels and return counts, intersections, and exact IDs."""

    by_cause: dict[str, list[str]] = {}
    by_cause_records: dict[str, list[str]] = {}
    by_intersection: dict[tuple[str, ...], list[str]] = {}
    cardinality: dict[str, int] = {}
    stoichiometry_subcauses: dict[str, list[str]] = {}
    unsupported = []
    for record in records:
        if record.get("status") not in {"unsupported", "unsupported_format"}:
            continue
        reason = str(record.get("unsupported_reason") or record.get("error", ""))
        if reason and not record.get("unsupported_reason"):
            record["unsupported_reason"] = reason
        causes = (
            ["format"]
            if record.get("status") == "unsupported_format"
            else _unsupported_causes(reason)
        )
        record["unsupported_causes"] = causes
        subcauses = _stoichiometry_subcauses(reason)
        record["unsupported_subcauses"] = (
            {"stoichiometry": subcauses} if "stoichiometry" in causes else {}
        )
        reference = _record_ref(record)
        unsupported.append(record)
        unique_causes = tuple(sorted(set(causes)))
        cardinality[str(len(unique_causes))] = (
            cardinality.get(str(len(unique_causes)), 0) + 1
        )
        by_intersection.setdefault(unique_causes, []).append(reference)
        for cause in causes:
            by_cause.setdefault(cause, []).append(str(record.get("id", "")))
            by_cause_records.setdefault(cause, []).append(reference)
        for subcause in subcauses:
            stoichiometry_subcauses.setdefault(subcause, []).append(reference)
    return {
        "record_count": len(unsupported),
        "by_cause": {
            cause: {
                "count": len(ids),
                "ids": ids,
                "records": by_cause_records[cause],
            }
            for cause, ids in sorted(by_cause.items())
        },
        "stoichiometry_subsummary": {
            "record_count": sum(
                "stoichiometry" in record.get("unsupported_causes", [])
                for record in unsupported
            ),
            "by_subcause": {
                subcause: {
                    "count": len(references),
                    "records": references,
                }
                for subcause, references in sorted(stoichiometry_subcauses.items())
            },
        },
        "intersection_summary": {
            "record_count": len(unsupported),
            "cause_cardinality": dict(
                sorted(cardinality.items(), key=lambda item: int(item[0]))
            ),
            "by_cause_set": {
                " + ".join(cause_set) if cause_set else "none": {
                    "count": len(references),
                    "records": references,
                }
                for cause_set, references in sorted(
                    by_intersection.items(), key=lambda item: (len(item[0]), item[0])
                )
            },
            "pairwise": {
                " + ".join(pair): {
                    "count": sum(
                        set(pair).issubset(set(record.get("unsupported_causes", [])))
                        for record in unsupported
                    ),
                    "records": [
                        _record_ref(record)
                        for record in unsupported
                        if set(pair).issubset(set(record.get("unsupported_causes", [])))
                    ],
                }
                for pair in sorted(
                    {
                        pair
                        for record in unsupported
                        for pair in itertools.combinations(
                            sorted(set(record.get("unsupported_causes", []))), 2
                        )
                    }
                )
            },
        },
    }


def _simulation_limitations(warnings: list[dict[str, Any]]) -> list[str]:
    """Return warnings that prevent an executable numerical claim.

    ``approximated`` is intentionally a hard boundary here.  A construct may
    be rendered into BNGL text while still lacking SBML semantic equivalence;
    the curated numerical gate must not classify that result as passed.
    Informational unit-scale notes remain non-blocking because the parser
    preserves the source numeric scale by design.
    """

    limitations = []
    for warning in warnings:
        message = str(warning["message"])
        if (
            warning["severity"] in {"dropped", "approximated"}
            and warning.get("category") != "units"
        ):
            limitations.append(message)
    return limitations


def _event_translation_limitations(bngl: str) -> list[str]:
    """Return explicit diagnostics for events the BNGL action lowering rejected."""

    marker = "# Events NOT simulated"
    if marker not in bngl:
        return []
    details = []
    in_notes = False
    for line in bngl.splitlines():
        if line.strip() == marker:
            in_notes = True
            continue
        if in_notes and line.startswith("# ============================"):
            break
        if in_notes and line.startswith("#") and line.strip() != "#":
            details.append(line.lstrip("# "))
    detail = " | ".join(details[:8])
    return [
        "Generated BNGL retained untranslated SBML event(s); "
        "state-dependent or dynamic event scheduling is outside the BNGL action engine."
        + (f" Details: {detail}" if detail else "")
    ]


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _attribute(element: ET.Element, name: str, default: Any = None) -> Any:
    for key, value in element.attrib.items():
        if key == name or key.rsplit("}", 1)[-1] == name:
            return value
    return default


def _sbml_surface_limitations(sbml: str) -> tuple[dict[str, int], list[str]]:
    """Detect package and stoichiometry boundaries before expensive atomization.

    This is deliberately structural.  It prevents large package documents
    from spending the model timeout in a kinetic network expansion while
    retaining a reproducible, model-independent unsupported reason.  Events
    are counted for reporting but are translated by the modern writer and
    therefore are not a surface-level unsupported condition here.
    """

    root = ET.fromstring(sbml)
    counts = {
        "species": sum(
            _local_name(element.tag) == "species" for element in root.iter()
        ),
        "reactions": sum(
            _local_name(element.tag) == "reaction" for element in root.iter()
        ),
        "events": sum(_local_name(element.tag) == "event" for element in root.iter()),
    }
    package_counts: Counter[str] = Counter()
    for element in root.iter():
        tag = str(element.tag)
        if not tag.startswith("{"):
            continue
        namespace = tag[1:].split("}", 1)[0].lower()
        for package in ("fbc", "qual", "comp", "distrib"):
            if f"/{package}/" in namespace:
                package_counts[package] += 1

    limitations: list[str] = []
    if package_counts["fbc"]:
        limitations.append(
            "SBML fbc package is present; flux-balance constraints/objectives "
            "define a constraint-based model with no kinetic BNGL equivalent."
        )
    if package_counts["qual"]:
        limitations.append(
            "SBML qual package is present; qualitative/logical transitions "
            "have no quantitative BNGL reaction-rule equivalent."
        )
    if package_counts["comp"]:
        limitations.append(
            "SBML comp package is present; hierarchical submodels are not "
            "flattened by the Atomizer."
        )
    if package_counts["distrib"]:
        limitations.append(
            "SBML distrib package is present; uncertainty/distribution "
            "semantics are not imported into BNGL."
        )
    for reference in root.iter():
        if _local_name(reference.tag) not in {
            "speciesReference",
            "modifierSpeciesReference",
        }:
            continue
        raw = _attribute(reference, "stoichiometry")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0 or abs(value - round(value)) > 1e-12:
            limitations.append(
                "SBML contains non-integer reaction stoichiometry; BNGL "
                "reaction rules require fixed nonnegative integer stoichiometry."
            )
            break
        if value > 100:
            limitations.append(
                "SBML contains reaction stoichiometry above the BNGL expansion "
                "limit of 100; this cannot be represented as a fixed BNGL rule."
            )
            break
    if any(_local_name(element.tag) == "stoichiometryMath" for element in root.iter()):
        limitations.append(
            "SBML contains variable stoichiometryMath; BNGL reaction rules "
            "require fixed stoichiometry."
        )
    return {
        **counts,
        **{f"package_{key}": value for key, value in package_counts.items()},
    }, limitations


def _known_unsupported_error(message: str) -> bool:
    """Recognize explicit format/engine boundaries, not generic failures."""

    lower = message.lower()
    return any(
        marker in lower
        for marker in (
            "cannot serialize bngl table functions",
            "not losslessly representable",
            'sbml "qual"',
            "qualitative/logical",
            "algebraic rule",
            "assignment rule targets species",
            "unsupported stoichiometry",
            "variable stoichiometry",
            "package detected",
        )
    )


def _simulate_and_compare(
    cpp_model: Any,
    model_type: Any,
    output_path: Path,
    *,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    max_step: float = 0.0,
    function_names: set[str] | None = None,
) -> dict[str, Any]:
    """Compare BNG3/CVODE observables with libRoadRunner on one time grid."""

    try:
        import roadrunner
    except ImportError as exc:
        raise RuntimeError(
            "libRoadRunner is required for direct numerical comparison"
        ) from exc

    bng_result = model_type(cpp_model).simulate(
        method="ode",
        t_start=0.0,
        t_end=t_end,
        n_steps=n_steps,
        rtol=rtol,
        atol=atol,
        max_step=max_step,
    )
    series = dict(bng_result.observables)
    function_values = getattr(bng_result, "functions", {}) or {}
    if function_names is None:
        series.update(function_values)
    else:
        series.update(
            {
                name: values
                for name, values in function_values.items()
                if name in function_names
            }
        )
    observable_names = list(series)
    bng_time = np.asarray(bng_result.time, dtype=float)
    bng_values = {
        name: np.asarray(series[name], dtype=float) for name in observable_names
    }

    rr = roadrunner.RoadRunner(str(output_path))
    integrator = rr.integrator
    if integrator.hasValue("relative_tolerance"):
        integrator.setValue("relative_tolerance", rtol)
    if integrator.hasValue("absolute_tolerance"):
        integrator.setValue("absolute_tolerance", atol)
    if max_step > 0.0 and integrator.hasValue("maximum_time_step"):
        integrator.setValue("maximum_time_step", max_step)
    available = set(rr.getAssignmentRuleIds())

    def sbml_id(name: str) -> str:
        valid = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
        if valid and valid[0].isdigit():
            valid = "_" + valid
        return valid or "species"

    selected_names = []
    missing = []
    for name in observable_names:
        safe_name = sbml_id(name)
        candidates = [
            safe_name,
            "obs_" + safe_name,
            "func_" + safe_name,
            "param_" + safe_name,
        ]
        selected = next(
            (candidate for candidate in candidates if candidate in available), None
        )
        if selected is None:
            missing.append(name)
        else:
            selected_names.append(selected)
    if missing:
        raise RuntimeError(
            "written SBML is missing observable assignment rules: "
            + ", ".join(missing[:10])
        )
    rr.timeCourseSelections = ["time", *selected_names]
    rr_values = np.asarray(rr.simulate(0.0, t_end, n_steps + 1), dtype=float)
    expected_shape = (len(bng_time), len(observable_names) + 1)
    if rr_values.ndim != 2 or rr_values.shape != expected_shape:
        raise RuntimeError(
            f"libRoadRunner returned shape {rr_values.shape}, expected {expected_shape}"
        )
    if not np.allclose(rr_values[:, 0], bng_time, rtol=0.0, atol=max(atol, 1e-12)):
        raise RuntimeError("BNG3 and libRoadRunner produced different time grids")

    comparison_scale = max(
        [
            *(
                float(np.max(np.abs(values)))
                for values in bng_values.values()
                if values.size
            ),
            *(
                float(np.max(np.abs(rr_values[:, index])))
                for index in range(1, rr_values.shape[1])
                if rr_values.shape[0]
            ),
            0.0,
        ]
    )
    comparisons: dict[str, dict[str, Any]] = {}
    failed = []
    for index, name in enumerate(observable_names, start=1):
        left = bng_values[name]
        right = rr_values[:, index]
        if left.shape != right.shape:
            raise RuntimeError(f"observable {name!r} returned mismatched shapes")
        finite = bool(np.isfinite(left).all() and np.isfinite(right).all())
        difference = np.abs(left - right)
        scale = max(
            float(np.max(np.abs(left))) if left.size else 0.0,
            float(np.max(np.abs(right))) if right.size else 0.0,
        )
        # Cross-engine CVODE paths have small dense-output/RHS differences;
        # retain a global floor for low-magnitude parity checks.
        tolerance = max(
            atol + rtol * scale,
            NUMERICAL_COMPARISON_ATOL_FLOOR
            + NUMERICAL_COMPARISON_RTOL_FLOOR * comparison_scale,
        )
        max_abs = float(np.max(difference)) if difference.size else 0.0
        scaled_error = max_abs / tolerance if tolerance else math.inf
        passed = finite and max_abs <= tolerance
        if not passed:
            failed.append(name)
        comparisons[name] = {
            "finite": finite,
            "max_abs_difference": max_abs,
            "tolerance": tolerance,
            "max_scaled_error": scaled_error,
            "passed": passed,
        }
    if failed:
        return {
            "passed": False,
            "error": (
                "BNG3 CVODE/libRoadRunner observable mismatch: "
                + ", ".join(failed[:10])
            ),
            "method_bngl": "BNG3 CVODE (simulate method='ode')",
            "method_sbml": "libRoadRunner CVODE",
            "roadrunner_version": getattr(roadrunner, "__version__", None),
            "t_start": 0.0,
            "t_end": t_end,
            "n_steps": n_steps,
            "rtol": rtol,
            "atol": atol,
            "max_step": max_step,
            "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
            "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
            "comparison_reference_scale": comparison_scale,
            "observable_count": len(observable_names),
            "sbml_observable_ids": dict(zip(observable_names, selected_names)),
            "failed_observables": failed,
            "observables": comparisons,
        }
    return {
        "passed": True,
        "method_bngl": "BNG3 CVODE (simulate method='ode')",
        "method_sbml": "libRoadRunner CVODE",
        "roadrunner_version": getattr(roadrunner, "__version__", None),
        "t_start": 0.0,
        "t_end": t_end,
        "n_steps": n_steps,
        "rtol": rtol,
        "atol": atol,
        "max_step": max_step,
        "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
        "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
        "comparison_reference_scale": comparison_scale,
        "observable_count": len(observable_names),
        "sbml_observable_ids": dict(zip(observable_names, selected_names)),
        "observables": comparisons,
    }


def _validate_mode(
    sbml: str,
    model_id: str,
    mode_atomize: bool,
    cpp: Any,
    model_type: Any,
    work_dir: Path,
    ode_smoke: bool,
    simulation_t_end: float,
    simulation_n_steps: int,
    simulation_rtol: float,
    simulation_atol: float,
    source_path: Path | None = None,
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import (
        Atomizer,
        SBMLParser,
        source_metadata_payload,
        source_metadata_summary,
    )
    from bionetgen.atomizer.modern.types import standardize_name

    mode = "atomized" if mode_atomize else "flat"
    result: dict[str, Any] = {
        "mode": mode,
        "source_xml": {},
    }
    try:
        result["source_xml"] = _validate_xml(sbml, "source SBML")
    except RuntimeError as exc:
        # A small number of archived BioModels files contain malformed or
        # stale package XML.  Preserve the exact libSBML diagnosis, but do
        # not call a source-document defect an Atomizer or writer failure.
        reason = f"source SBML is not libSBML-valid: {exc}"
        result["source_xml"] = {"passed": False, "error": str(exc)}
        result["status"] = "unsupported"
        result["unsupported_reason"] = reason
        result["simulation_comparison"] = {
            "passed": False,
            "skipped": True,
            "reason": reason,
            "method_bngl": "BNG3 CVODE",
            "method_sbml": "libRoadRunner CVODE",
        }
        result["core_passed"] = False
        return result
    surface_counts, surface_limitations = _sbml_surface_limitations(sbml)
    result["source"] = surface_counts
    if surface_limitations:
        reason = " ".join(dict.fromkeys(surface_limitations))
        result["status"] = "unsupported"
        result["unsupported_reason"] = reason
        result["simulation_comparison"] = {
            "passed": False,
            "skipped": True,
            "reason": reason,
            "method_bngl": "BNG3 CVODE",
            "method_sbml": "libRoadRunner CVODE",
        }
        result["core_passed"] = False
        return result
    try:
        source_model = SBMLParser().parse(sbml, source_path=source_path)
    except ValueError as exc:
        message = str(exc)
        if 'SBML "qual"' not in message and "qualitative/logical" not in message:
            raise
        result["status"] = "unsupported"
        result["unsupported_reason"] = message
        result["simulation_comparison"] = {
            "passed": False,
            "skipped": True,
            "reason": message,
            "method_bngl": "BNG3 CVODE",
            "method_sbml": "libRoadRunner CVODE",
        }
        result["core_passed"] = False
        return result
    result["source"] = {
        "species": len(source_model.species),
        "reactions": len(source_model.reactions),
        "warnings": _warnings(source_model),
        "metadata": source_metadata_summary(source_model),
    }
    source_metadata = source_metadata_payload(source_model)
    atomizer = Atomizer(atomize=mode_atomize, quiet_mode=True)
    source_warnings = result["source"]["warnings"]
    try:
        atomized = atomizer.atomize(sbml, source_path=source_path)
    except ValueError as exc:
        message = str(exc)
        if 'SBML "qual"' in message or "qualitative/logical" in message:
            result["status"] = "unsupported"
            result["unsupported_reason"] = message
            result["simulation_comparison"] = {
                "passed": False,
                "skipped": True,
                "reason": message,
                "method_bngl": "BNG3 CVODE",
                "method_sbml": "libRoadRunner CVODE",
            }
            result["core_passed"] = False
            return result
        raise
    if not atomized.success:
        raise RuntimeError(atomized.error or "modern Atomizer returned failure")
    source_warnings = _merge_generated_warnings(
        source_warnings, _warnings(atomizer.model)
    )
    result["source"]["warnings"] = source_warnings
    source_limitations = [
        *_simulation_limitations(source_warnings),
        *_event_translation_limitations(atomized.bngl),
    ]
    if source_limitations:
        result["status"] = "unsupported"
        result["unsupported_reason"] = " ".join(source_limitations)
        result["simulation_comparison"] = {
            "passed": False,
            "skipped": True,
            "reason": result["unsupported_reason"],
            "method_bngl": "BNG3 CVODE",
            "method_sbml": "libRoadRunner CVODE",
        }
        result["core_passed"] = False
        return result
    cpp_model = cpp.parse_string(atomized.bngl)
    network = cpp.generate_network(cpp_model, max_iter=100)
    result["generated_network"] = {
        "species": network.num_species,
        "reactions": network.num_reactions,
    }

    output_path = work_dir / f"{model_id}_{mode}.xml"
    cpp.io.write_sbml(
        cpp_model,
        network,
        str(output_path),
        source_metadata=source_metadata,
    )
    roundtrip_sbml = output_path.read_text(encoding="utf-8")
    result["written_xml"] = _validate_xml(roundtrip_sbml, "written SBML")

    roundtrip_model = SBMLParser().parse(roundtrip_sbml)
    result["reimport_parser"] = {
        "species": len(roundtrip_model.species),
        "reactions": len(roundtrip_model.reactions),
        "metadata": source_metadata_summary(roundtrip_model),
    }
    result["metadata_roundtrip"] = {
        "source": result["source"].get("metadata", {}),
        "reimport": result["reimport_parser"].get("metadata", {}),
        "status": (
            "not_present"
            if not source_metadata
            else (
                "preserved"
                if roundtrip_model.source_metadata_payload == source_metadata
                else "dropped"
            )
        ),
        "payloadPresent": bool(roundtrip_model.source_metadata_payload),
        "payloadMatch": bool(
            source_metadata
            and roundtrip_model.source_metadata_payload == source_metadata
        ),
    }
    reimport = Atomizer(atomize=False, quiet_mode=True).atomize(roundtrip_sbml)
    if not reimport.success:
        raise RuntimeError(reimport.error or "round-trip Atomizer returned failure")
    reimport_cpp = cpp.parse_string(reimport.bngl)
    reimport_network = cpp.generate_network(reimport_cpp, max_iter=100)
    result["reimport_network"] = {
        "species": reimport_network.num_species,
        "reactions": reimport_network.num_reactions,
    }

    native = dict(cpp.io.read_sbml(str(output_path), False))
    result["native_reader"] = native
    if not native.get("success"):
        raise RuntimeError(native.get("error") or "native SBML reader returned failure")
    if native["species_count"] != network.num_species:
        raise RuntimeError(
            "native SBML reader species count differs from writer network: "
            f"{native['species_count']} != {network.num_species}"
        )
    if native["reaction_count"] != network.num_reactions:
        raise RuntimeError(
            "native SBML reader reaction count differs from writer network: "
            f"{native['reaction_count']} != {network.num_reactions}"
        )

    try:
        comparison = _simulate_and_compare(
            cpp_model,
            model_type,
            output_path,
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
            rtol=simulation_rtol,
            atol=simulation_atol,
            function_names={
                standardize_name(str(rule.variable))
                for rule in source_model.rules
                if rule.type == "assignment"
                and rule.variable
            }
            | {
                standardize_name(str(assignment.symbol))
                for assignment in source_model.initial_assignments
                if assignment.symbol
            },
        )
    except RuntimeError as initial_error:
        comparison = None
        initial_runtime_error = initial_error
    else:
        initial_runtime_error = None

    # Cross-engine CVODE can fail on a stiff, unit-normalized model before
    # either trajectory is available, or can return a mismatch caused by
    # different adaptive-step histories. Retry with progressively smaller
    # shared internal steps. The first retry remains bounded at t_end/2000;
    # the smaller retries handle models whose unit normalization creates
    # transients below that scale. A successful tighter comparison is still
    # required from both engines, so this cannot turn a real mismatch into a
    # pass by changing only one side.
    if initial_runtime_error is not None or not comparison.get("passed", False):
        retry_max_step = max(abs(simulation_t_end) / 2000.0, 1e-6)
        retries = [retry_max_step * factor for factor in (1.0, 0.2, 0.1, 0.04, 0.02)]
        last_comparison = comparison
        for retry_max_step in retries:
            try:
                stabilized = _simulate_and_compare(
                    cpp_model,
                    model_type,
                    output_path,
                    t_end=simulation_t_end,
                    n_steps=simulation_n_steps,
                    rtol=simulation_rtol,
                    atol=simulation_atol,
                    max_step=retry_max_step,
                )
            except RuntimeError:
                continue
            last_comparison = stabilized
            if stabilized.get("passed", False):
                break
        comparison = last_comparison
        if comparison is None:
            raise initial_runtime_error
    result["simulation_comparison"] = comparison
    if not comparison.get("passed", False):
        result["status"] = "failed"
        result["core_passed"] = False
        result["error"] = comparison.get("error", "numerical comparison failed")
        return result

    limitations = _simulation_limitations(result["source"]["warnings"])
    if limitations:
        result["status"] = "unsupported"
        result["unsupported_reason"] = " ".join(limitations)
        result["core_passed"] = False
        return result

    if ode_smoke:
        try:
            simulation = model_type(cpp_model).simulate(
                method="ode", t_end=1.0, n_steps=2
            )
            result["ode"] = {
                "passed": simulation.n_steps == 3,
                "time_points": simulation.n_steps,
            }
        except Exception as exc:  # published initial conditions may be singular
            result["ode"] = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    result["core_passed"] = True
    return result


def _run_isolated_model(
    entry: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    """Run one model in a bounded subprocess and return its record."""

    record: dict[str, Any] = dict(entry)
    worker_json = args.cache_dir / f".worker-{entry['id']}.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--manifest",
        str(args.manifest.resolve()),
        "--cache-dir",
        str(args.cache_dir.resolve()),
        "--json",
        str(worker_json),
        "--mode",
        args.mode,
        "--offline",
        "--only-id",
        entry["id"],
        "--worker",
        "--simulation-t-end",
        str(args.simulation_t_end),
        "--simulation-n-steps",
        str(args.simulation_n_steps),
        "--simulation-rtol",
        str(args.simulation_rtol),
        "--simulation-atol",
        str(args.simulation_atol),
    ]
    if args.ode_smoke:
        command.append("--ode-smoke")
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=args.model_timeout,
        )
        if not worker_json.exists():
            raise RuntimeError(
                f"worker exited {completed.returncode} without a report: "
                f"{completed.stderr[-500:]}"
            )
        return json.loads(worker_json.read_text(encoding="utf-8"))["records"][0]
    except subprocess.TimeoutExpired:
        record.update(
            status="timeout",
            core_passed=False,
            error=f"per-model timeout after {args.model_timeout}s",
        )
    except Exception as exc:
        record.update(
            status="failed",
            core_passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        worker_json.unlink(missing_ok=True)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo / "provenance" / "published-biomodels.json",
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--mode", choices=("flat", "atomized", "both"), default="flat")
    parser.add_argument("--refresh-inventory", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--fetch-record-metadata",
        action="store_true",
        help="fetch one BioModels record endpoint per model for exact main-file metadata",
    )
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--only-id")
    parser.add_argument(
        "--isolate-models",
        action="store_true",
        help="run each model in a bounded child process",
    )
    parser.add_argument(
        "--model-timeout", type=int, default=120, help="per-model timeout in seconds"
    )
    parser.add_argument(
        "--jobs", type=int, default=4, help="parallel isolated model workers"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ode-smoke", action="store_true")
    parser.add_argument("--simulation-t-end", type=float, default=1.0)
    parser.add_argument("--simulation-n-steps", type=int, default=10)
    parser.add_argument("--simulation-rtol", type=float, default=1e-7)
    parser.add_argument("--simulation-atol", type=float, default=1e-12)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    inventory = _enumerate_inventory(
        manifest,
        args.cache_dir,
        args.refresh_inventory,
        args.offline,
        args.fetch_record_metadata,
    )
    all_models = list(inventory["models"])
    if args.only_id:
        selected_models = [entry for entry in all_models if entry["id"] == args.only_id]
        if not selected_models:
            raise SystemExit(
                f"BioModels id is not in the curated inventory: {args.only_id}"
            )
    else:
        selected_models = (
            all_models[: args.max_models] if args.max_models else all_models
        )
    partial = bool(args.max_models or args.only_id)
    expected_total = int(manifest["expected_total_records"])
    expected_sbml = int(manifest["expected_sbml_records"])
    expected_non_sbml = int(manifest["expected_non_sbml_records"])
    format_counts = Counter(str(item.get("format", "")) for item in all_models)
    completeness = {
        "inventory_matches": inventory.get("matches"),
        "inventory_records": len(all_models),
        "expected_records": expected_total,
        "expected_sbml_records": expected_sbml,
        "expected_non_sbml_records": expected_non_sbml,
        "sbml_records": sum(_is_declared_sbml(item) for item in all_models),
        "non_sbml_records": sum(not _is_declared_sbml(item) for item in all_models),
        "archive_records": sum(_is_archive_entry(item) for item in all_models),
        "sbml_path_records": sum(
            _is_declared_sbml(item) or _is_archive_entry(item) for item in all_models
        ),
        "format_counts": dict(format_counts),
        "partial_run": partial,
    }
    completeness["counts_match"] = (
        len(all_models) == expected_total
        and completeness["sbml_records"] == expected_sbml
        and completeness["non_sbml_records"] == expected_non_sbml
    )

    try:
        import bionetgen._bionetgen_cpp as cpp
        from bionetgen import BioNetGenModel
    except ImportError as exc:
        raise SystemExit(
            "BNG3 C++ extension is unavailable; set PYTHONPATH=python:build/cpp"
        ) from exc

    records: list[dict[str, Any]] = []
    modes = (False, True) if args.mode == "both" else (args.mode == "atomized",)
    sbml_selected = []
    for entry in selected_models:
        record: dict[str, Any] = dict(entry)
        is_sbml = _is_declared_sbml(entry)
        is_archive = _is_archive_entry(entry)
        if not is_sbml and not is_archive:
            record.update(
                status="unsupported_format",
                unsupported_reason="record is not an SBML BioModels artifact",
                core_passed=False,
            )
            records.append(record)
            print(
                f"{entry['id']}: UNSUPPORTED ({entry.get('format', 'unknown')})",
                flush=True,
            )
            continue

        if args.isolate_models and not args.worker:
            sbml_selected.append(entry)
            continue

        try:
            path = args.cache_dir / str(entry["filename"])
            record["sha256"] = _download_if_needed(path, entry)
            record["source_artifact"] = {
                "format": entry.get("format", ""),
                "filename": entry.get("filename", ""),
                "mime_type": entry.get("mime_type", ""),
                "sha256": record["sha256"],
                "size_bytes": path.stat().st_size,
            }
            if is_archive:
                from bionetgen.atomizer.modern import extract_sbml_from_archive

                try:
                    extraction = extract_sbml_from_archive(path)
                except ValueError as exc:
                    reason = f"{entry.get('format', 'archive')} contains no usable SBML: {exc}"
                    record.update(
                        status="unsupported",
                        unsupported_reason=reason,
                        core_passed=False,
                        source_artifact={
                            **record["source_artifact"],
                            "sbml_extracted": False,
                        },
                    )
                    records.append(record)
                    print(f"{entry['id']}: UNSUPPORTED ({reason})", flush=True)
                    continue
                sbml = extraction.sbml
                record["source_artifact"].update(
                    {
                        "sbml_extracted": True,
                        "sbml_member": extraction.member,
                        "sbml_candidates": list(extraction.candidates),
                        "extraction_warnings": list(extraction.warnings),
                    }
                )
                record["extracted_sbml"] = True
            else:
                sbml = path.read_text(encoding="utf-8-sig")
                record["extracted_sbml"] = False
            with tempfile.TemporaryDirectory(
                prefix=f"{entry['id']}-", dir=args.cache_dir
            ) as temp:
                mode_results = []
                for atomize in modes:
                    mode_name = "atomized" if atomize else "flat"
                    try:
                        mode_results.append(
                            _validate_mode(
                                sbml,
                                entry["id"],
                                atomize,
                                cpp,
                                BioNetGenModel,
                                Path(temp),
                                args.ode_smoke,
                                args.simulation_t_end,
                                args.simulation_n_steps,
                                args.simulation_rtol,
                                args.simulation_atol,
                                source_path=path if not is_archive else None,
                            )
                        )
                    except Exception as exc:
                        message = f"{type(exc).__name__}: {exc}"
                        mode_result = {
                            "mode": mode_name,
                            "status": (
                                "unsupported"
                                if _known_unsupported_error(message)
                                else "failed"
                            ),
                            "core_passed": False,
                            "error": message,
                        }
                        if mode_result["status"] == "unsupported":
                            mode_result["unsupported_reason"] = message
                        mode_results.append(mode_result)
                record["modes"] = mode_results
            mode_statuses = [
                mode_result.get("status", "passed") for mode_result in record["modes"]
            ]
            if "failed" in mode_statuses:
                record["status"] = "failed"
            elif "unsupported" in mode_statuses:
                record["status"] = "unsupported"
                record["unsupported_reason"] = "; ".join(
                    mode.get("unsupported_reason", "")
                    for mode in record["modes"]
                    if mode.get("status") == "unsupported"
                    and mode.get("unsupported_reason")
                )
            else:
                record["status"] = "passed"
            record["core_passed"] = record["status"] == "passed"
        except Exception as exc:  # download and round-trip failures are hard failures
            message = f"{type(exc).__name__}: {exc}"
            record["status"] = (
                "unsupported" if _known_unsupported_error(message) else "failed"
            )
            record["core_passed"] = False
            record["error"] = message
            if record["status"] == "unsupported":
                record["unsupported_reason"] = message
        records.append(record)
        print(f"{entry['id']}: {record['status'].upper()}", flush=True)

    if sbml_selected:
        if args.jobs < 1:
            raise SystemExit("--jobs must be at least one")
        if args.jobs == 1:
            isolated_records = [
                _run_isolated_model(entry, args) for entry in sbml_selected
            ]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                isolated_records = list(
                    pool.map(
                        lambda entry: _run_isolated_model(entry, args), sbml_selected
                    )
                )
        records.extend(isolated_records)
        for record in isolated_records:
            print(f"{record['id']}: {record['status'].upper()}", flush=True)

    # Keep the report in inventory order even when isolated workers complete
    # concurrently and format-only records were handled inline.
    order = {entry["id"]: index for index, entry in enumerate(selected_models)}
    records.sort(key=lambda record: order[record["id"]])
    unsupported_summary = _unsupported_summary(records)

    sbml_records = [
        record
        for record in records
        if _is_declared_sbml(record) or record.get("extracted_sbml")
    ]
    declared_sbml_records = [record for record in records if _is_declared_sbml(record)]
    archive_records = [record for record in records if _is_archive_entry(record)]
    passed = sum(record.get("status") == "passed" for record in sbml_records)
    sbml_unsupported = sum(
        record.get("status") == "unsupported" for record in sbml_records
    )
    unsupported = sum(
        record.get("status") in {"unsupported_format", "unsupported"}
        for record in records
    )
    failed = sum(record.get("status") == "failed" for record in records)
    timeouts = sum(record.get("status") == "timeout" for record in records)
    report = {
        "schema_version": 4,
        "manifest": str(args.manifest.resolve()),
        "cache_dir": str(args.cache_dir.resolve()),
        "writer_sbml_version": "L3V2",
        "inventory": inventory,
        "completeness": completeness,
        "mode": args.mode,
        "simulation": {
            "t_start": 0.0,
            "t_end": args.simulation_t_end,
            "n_steps": args.simulation_n_steps,
            "rtol": args.simulation_rtol,
            "atol": args.simulation_atol,
            "comparison": "all generated BNGL observables on the same time grid",
            "engines": ["BNG3 CVODE", "libRoadRunner CVODE"],
        },
        "records": records,
        "unsupported_summary": unsupported_summary,
        "sbml_unsupported_summary": _unsupported_summary(sbml_records),
        "summary": {
            "selected_records": len(records),
            "sbml_records": len(sbml_records),
            "declared_sbml_records": len(declared_sbml_records),
            "archive_records": len(archive_records),
            "extracted_sbml_records": sum(
                bool(record.get("extracted_sbml")) for record in archive_records
            ),
            "no_sbml_archive_records": sum(
                record.get("status") == "unsupported"
                and not record.get("extracted_sbml")
                for record in archive_records
            ),
            "passed_sbml_records": passed,
            "unsupported_sbml_records": sbml_unsupported,
            "unsupported_records": unsupported,
            "failed_records": failed,
            "timeout_records": timeouts,
        },
        "core_passed": (
            not partial
            and completeness["counts_match"]
            and failed == 0
            and timeouts == 0
            and sbml_unsupported == 0
            and passed == len(sbml_records)
        ),
        "supported_surface_passed": (
            not partial
            and completeness["counts_match"]
            and failed == 0
            and timeouts == 0
        ),
        "unsupported_formats_are_explicit": True,
        "simulation_comparison_is_required": True,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        args.json.write_text(
            json.dumps(
                _json_compatible({"records": records, "summary": report["summary"]}),
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        args.json.write_text(
            json.dumps(_json_compatible(report), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(
        f"records={len(records)} sbml_passed={passed}/{len(sbml_records)} "
        f"unsupported={unsupported} failed={failed} timeouts={timeouts} "
        f"core={'PASS' if report['core_passed'] else 'FAIL'}"
    )
    return 0 if report["core_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
