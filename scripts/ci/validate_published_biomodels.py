#!/usr/bin/env python3
"""Validate every manually curated BioModels SBML record.

The official BioModels search API is the inventory source.  Every returned
record is retained in the report: SBML records go through the modern
Atomizer, C++ network generation, C++ SBML writing, modern SBML re-import,
the native C++ SBML reader, and direct BNG3-CVODE/libRoadRunner observable
comparison; non-SBML records are explicitly reported as unsupported by this
SBML path. Public-source transport failures are reported as ``harness_error``
with endpoint and HTTP diagnostics; they are not Atomizer verdicts.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import math
import re
import shutil
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

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ci.deterministic_environment import (
    STARTUP_HASH_SEED,
    ensure_fixed_hash_seed,
    fixed_hash_seed_environment,
)
from scripts.ci.case_phase_journal import case_phase_scope, phase_progress
from scripts.ci.imported_package_guard import (
    ForeignPackageError,
    package_source_digest,
    verify_imported_package,
    verify_native_extension,
)

USER_AGENT = "BNG3-curated-BioModels-roundtrip-validator/2"
NUMERICAL_COMPARISON_ATOL_FLOOR = 5e-12
# libRoadRunner and BNG3 use independent CVODE builds and Jacobian paths;
# retain a small model-scale floor for cross-engine dense-output differences.
NUMERICAL_COMPARISON_RTOL_FLOOR = 1e-5
BIOMODELS_CASE_PHASE_PREFIX = "@@BIOMODELS_CASE_PHASE@@"
MAX_CASE_PACKET_BYTES = 4 * 1024 * 1024
MAX_CASE_PACKET_FILE_BYTES = 1024 * 1024
COMPARISON_SCOPE = "written_sbml_export_consistency"


def _write_mode_checkpoint(
    result: dict[str, Any], path: Path | None, *, state: str = "in_progress"
) -> None:
    """Atomically retain completed mode evidence before later stages can time out."""

    if path is None:
        return
    payload = {**result, "checkpoint_state": state}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_compatible(payload), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _mode_stage(result: dict[str, Any], name: str):
    """Retain per-mode stage outcomes while emitting timeout breadcrumbs."""

    from contextlib import contextmanager

    @contextmanager
    def stage():
        try:
            with case_phase_scope(BIOMODELS_CASE_PHASE_PREFIX, name):
                yield
        except BaseException as exc:
            result.setdefault("stage_results", []).append(
                {
                    "name": name,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
        else:
            result.setdefault("stage_results", []).append(
                {"name": name, "status": "passed"}
            )

    return stage()


def _failed_mode_result(mode: str, prior: dict[str, Any], exc: BaseException):
    """Turn an exception into a mode result without dropping prior evidence."""

    result = dict(prior)
    message = f"{type(exc).__name__}: {exc}"
    result.update(
        mode=mode,
        status="unsupported" if _known_unsupported_error(message) else "failed",
        core_passed=False,
        error=message,
    )
    if result["status"] == "unsupported":
        result["unsupported_reason"] = message
    return result


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


def _model_source_cache_path(cache_dir: Path, entry: dict[str, Any]) -> Path:
    """Return a content-addressed or model-scoped source path."""

    model_id = str(entry.get("id", ""))
    filename = Path(str(entry.get("filename", ""))).name
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model_id)
        or not filename
        or filename in {".", ".."}
    ):
        raise ValueError("source cache entries require a model id and filename")
    expected = str(entry.get("sha256", "")).lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected):
        return cache_dir / "sha256" / expected
    return cache_dir / "models" / model_id / filename


def _source_xml_artifact_bytes(
    source_path: Path, source_xml: str, *, extracted_from_archive: bool
) -> bytes:
    """Keep original SBML bytes or encode the extracted archive member clearly."""

    if extracted_from_archive:
        return source_xml.encode("utf-8")
    return source_path.read_bytes()


def _migrate_legacy_source_cache(
    cache_dir: Path, entries: list[dict[str, Any]]
) -> dict[str, int]:
    """Copy matching legacy files into SHA paths once before isolated workers start."""

    expected = {
        str(entry.get("sha256", "")).lower()
        for entry in entries
        if re.fullmatch(r"[0-9a-fA-F]{64}", str(entry.get("sha256", "")))
    }
    destinations = {digest: cache_dir / "sha256" / digest for digest in expected}
    pending = {digest for digest, path in destinations.items() if not path.is_file()}
    if not pending:
        return {"expected_hashes": len(expected), "migrated": 0, "missing": 0}

    root = cache_dir.resolve()
    migrated: set[str] = set()
    for candidate in root.rglob("*"):
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or candidate.suffix.lower() not in {".xml", ".omex", ".zip"}
            or "sha256" in candidate.relative_to(root).parts
        ):
            continue
        try:
            digest = _sha256(candidate)
        except OSError:
            continue
        if digest not in pending:
            continue
        destination = destinations[digest]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, destination)
        migrated.add(digest)
        pending.remove(digest)
        if not pending:
            break
    return {
        "expected_hashes": len(expected),
        "migrated": len(migrated),
        "missing": len(pending),
    }


def _runtime_provenance(
    package_trace: dict[str, Any], extension_trace: dict[str, Any]
) -> dict[str, Any]:
    """Record which Python package and native extension the gate measured."""

    import bionetgen
    import bionetgen._bionetgen_cpp as native

    package_file = Path(bionetgen.__file__).resolve()
    extension_file = Path(native.__file__).resolve()
    return {
        "bionetgen_package_path": str(package_file),
        "python_package_source_sha256": package_source_digest(package_file.parent),
        "imported_package_trace": package_trace,
        "native_extension_path": str(extension_file),
        "native_extension_sha256": _sha256(extension_file),
        "imported_extension_trace": extension_trace,
        "python_hash_seed": STARTUP_HASH_SEED,
    }


def _supported_surface_passed(
    *,
    partial: bool,
    counts_match: bool,
    failed_records: int,
    harness_error_records: int,
    timeout_records: int,
    not_comparable_records: int,
) -> bool:
    """Require complete inputs, no harness errors, and a comparison per record."""

    return (
        not partial
        and counts_match
        and failed_records == 0
        and harness_error_records == 0
        and timeout_records == 0
        and not_comparable_records == 0
    )


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


class SourceAcquisitionError(RuntimeError):
    """A public model source could not be acquired for scientific validation."""

    def __init__(self, message: str, attempts: list[dict[str, Any]]):
        super().__init__(message)
        self.attempts = attempts


class SourceIntegrityError(RuntimeError):
    """Downloaded source bytes did not match their pinned digest."""

    def __init__(self, path: Path, expected_sha256: str, actual_sha256: str):
        super().__init__(
            f"sha256 mismatch for {path.name}: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256


def _acquisition_attempt(url: str, exc: Exception) -> dict[str, Any]:
    status = getattr(exc, "code", None)
    return {
        "url": url,
        "error_type": type(exc).__name__,
        "http_status": status,
        "reason": str(getattr(exc, "reason", None) or exc)[:300],
    }


def _model_exception_status(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if _known_unsupported_error(message):
        return "unsupported"
    if isinstance(exc, (SourceAcquisitionError, SourceIntegrityError)):
        return "harness_error"
    return "failed"


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


def _download_if_needed(
    path: Path, entry: dict[str, Any], *, offline: bool = False
) -> str:
    expected = entry.get("sha256")
    if offline and not re.fullmatch(r"[0-9a-f]{64}", str(expected or "")):
        raise SourceAcquisitionError(
            "offline source cache cannot be verified without an expected SHA-256",
            [],
        )
    if expected and path.exists() and _sha256(path) == expected:
        return str(expected)
    if not path.exists() or (expected and _sha256(path) != expected):
        if offline:
            raise SourceAcquisitionError(
                f"offline source cache is missing or has the wrong SHA-256: {path}",
                [],
            )
        attempts: list[dict[str, Any]] = []
        try:
            request = urllib.request.Request(
                entry["download_url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
        except (OSError, TimeoutError) as exc:
            attempts.append(_acquisition_attempt(entry["download_url"], exc))
            # Most records use the stable ``{id}_url.xml`` name, but the
            # record endpoint is authoritative for models whose main file
            # has a different name.  Resolve that only on a failed default
            # download so the full inventory remains fast.
            try:
                record = _fetch_json(entry["record_url"])
            except (OSError, TimeoutError, ValueError) as metadata_exc:
                attempts.append(_acquisition_attempt(entry["record_url"], metadata_exc))
                raise SourceAcquisitionError(
                    f"could not acquire source metadata or model bytes: {attempts}",
                    attempts,
                ) from metadata_exc
            files = list(_record_files(record))
            if not files:
                raise SourceAcquisitionError(
                    f"source metadata contained no main file after download failure: {attempts}",
                    attempts,
                )
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
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = response.read()
            except (OSError, TimeoutError) as retry_exc:
                attempts.append(_acquisition_attempt(entry["download_url"], retry_exc))
                raise SourceAcquisitionError(
                    f"could not acquire model bytes after metadata fallback: {attempts}",
                    attempts,
                ) from retry_exc
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    expected = entry.get("sha256")
    actual = _sha256(path)
    if expected and actual != expected:
        raise SourceIntegrityError(path, str(expected), actual)
    return actual


def _verified_no_sbml_archive_records(
    receipt_path: Path,
    bundle_manifest_path: Path,
    inventory_path: Path,
    query_manifest_path: Path,
    *,
    repo_root: Path,
) -> dict[str, dict[str, Any]]:
    """Load pinned negative archive evidence only from a verified bundle receipt."""

    from scripts.ci.install_biomodels_source_bundle import (
        SOURCE_FIELDS,
        _validate_records,
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    query_manifest = json.loads(query_manifest_path.read_text(encoding="utf-8"))
    bundle_manifest_sha = _sha256(bundle_manifest_path)
    inventory_sha = _sha256(inventory_path)
    query_manifest_sha = _sha256(query_manifest_path)
    if receipt.get("status") != "verified":
        raise ValueError("source bundle receipt is not verified")
    if bundle_manifest.get("kind") != "curated-biomodels-offline-source-bundle":
        raise ValueError("unexpected offline source bundle manifest kind")
    if receipt.get("bundle_manifest_sha256") != bundle_manifest_sha:
        raise ValueError("source bundle receipt does not bind the bundle manifest")
    if (
        receipt.get("inventory_sha256") != inventory_sha
        or bundle_manifest.get("inventory_sha256") != inventory_sha
    ):
        raise ValueError("source bundle receipt does not bind the pinned inventory")
    if (
        receipt.get("query_manifest_sha256") != query_manifest_sha
        or bundle_manifest.get("query_manifest_sha256") != query_manifest_sha
    ):
        raise ValueError("source bundle receipt does not bind the query manifest")
    if (
        receipt.get("bundle_sha256") != bundle_manifest.get("bundle_sha256")
        or receipt.get("query") != bundle_manifest.get("query")
        or receipt.get("snapshot_date") != bundle_manifest.get("snapshot_date")
        or inventory.get("source") != bundle_manifest.get("source")
        or inventory.get("query") != bundle_manifest.get("query")
        or query_manifest.get("search_api_url") != bundle_manifest.get("source")
        or query_manifest.get("curation_query") != bundle_manifest.get("query")
        or query_manifest.get("snapshot_date") != bundle_manifest.get("snapshot_date")
    ):
        raise ValueError(
            "source bundle receipt and pinned snapshot identities disagree"
        )

    records, payload_hashes, no_sbml_ids = _validate_records(bundle_manifest, inventory)
    if receipt.get("records_verified") != len(records):
        raise ValueError("source bundle receipt record count is inconsistent")
    if receipt.get("payloads_verified") != len(payload_hashes):
        raise ValueError("source bundle receipt payload count is inconsistent")
    receipt_ids = receipt.get("verified_non_sbml_archive_ids")
    if not isinstance(receipt_ids, list) or sorted(receipt_ids) != sorted(no_sbml_ids):
        raise ValueError("source bundle receipt no-SBML archive IDs are inconsistent")

    archive_module = repo_root / "python/bionetgen/atomizer/modern/archive.py"
    if not archive_module.is_file():
        raise ValueError(f"archive inspection module is missing: {archive_module}")
    archive_module_sha = _sha256(archive_module)
    evidence: dict[str, dict[str, Any]] = {}
    for model_id in no_sbml_ids:
        source_record = next(
            row for row in inventory["models"] if row.get("id") == model_id
        )
        bundle_record = records[model_id]
        inspection = bundle_record.get("archive_inspection") or {}
        if inspection.get("archive_module_sha256") != archive_module_sha:
            raise ValueError(
                f"source archive inspection module is stale for {model_id}"
            )
        if inspection.get("source_archive_sha256") != source_record.get("sha256"):
            raise ValueError(f"source archive hash is inconsistent for {model_id}")
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(inspection.get("member_list_sha256", ""))
        ):
            raise ValueError(
                f"source archive member-list hash is invalid for {model_id}"
            )
        evidence[model_id] = {
            "source": {field: source_record.get(field) for field in SOURCE_FIELDS},
            "archive_inspection": inspection,
        }
    return evidence


def _verified_no_sbml_archive_outcome(
    entry: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    source = evidence["source"]
    if any(entry.get(field) != value for field, value in source.items()):
        raise ValueError(
            f"runtime inventory source identity disagrees with verified "
            f"no-SBML evidence for {entry.get('id')}"
        )
    return {
        "sha256": source["sha256"],
        "status": "unsupported",
        "unsupported_reason": "verified source archive contains no SBML XML document",
        "core_passed": False,
        "source_artifact": {
            "format": source["format"],
            "filename": source["filename"],
            "mime_type": source["mime_type"],
            "sha256": source["sha256"],
            "size_bytes": int(source["file_size"]),
            "sbml_extracted": False,
            "archive_inspection": evidence["archive_inspection"],
        },
    }


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
    if "compartment derivative" in lower:
        causes.append("species_rate_rules")
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
    if "observable is undefined at t=" in lower:
        causes.append("undefined_observables")
    if "could not integrate the written sbml" in lower:
        causes.append("oracle_solver_failure")
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

    This is deliberately structural. It prevents large package documents
    from spending the model timeout in a kinetic network expansion while
    retaining a reproducible, model-independent unsupported reason. Fixed
    fixed or statically resolvable stoichiometry is left to the writer's
    deterministic flux lowering; dynamic values are rejected from parser
    diagnostics. Events are counted for reporting but are not a surface-level
    unsupported condition.
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
        if not math.isfinite(value) or value < 0:
            limitations.append(
                "SBML contains negative or non-finite reaction stoichiometry; "
                "deterministic flux lowering requires finite nonnegative values."
            )
            break
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
            # The Atomizer refuses a species concentration rate rule whose
            # compartment size has no continuous derivative.  The refusal is
            # explicit and names the construct, so it is a gap rather than a
            # failure of the gate.
            "compartment derivative",
            "unsupported stoichiometry",
            "variable stoichiometry",
            "package detected",
        )
    )


class OracleIntegrationError(RuntimeError):
    """The independent oracle could not integrate the model under comparison.

    A failure of libRoadRunner's own solver is a limitation of the
    measurement, not a disagreement between the two engines: the corpus
    comparison needs a trajectory from *both* engines, so a record whose
    oracle cannot integrate the written SBML cannot be judged.
    """


class BngSimulationError(RuntimeError):
    """BNG3 could not produce the trajectory required by a comparison."""


def _same_undefined_value(left: np.ndarray, right: np.ndarray) -> bool:
    """Return True when both engines report the same undefined value.

    An observable that is not a finite number at a grid point -- the
    logarithm of a quantity that is zero at the initial point, a ratio of
    two quantities that are both zero -- has no value to compare.  When the
    two engines report the *same* undefined value (both NaN, or both the
    same infinity) at the *same* points, the record reproduces the source's
    own undefined observable instead of disagreeing with it.
    """

    left_undefined = ~np.isfinite(left)
    right_undefined = ~np.isfinite(right)
    if not left_undefined.any() or not right_undefined.any():
        return False
    if not np.array_equal(left_undefined, right_undefined):
        return False
    same_kind = np.isnan(left) == np.isnan(right)
    same_kind &= np.isposinf(left) == np.isposinf(right)
    same_kind &= np.isneginf(left) == np.isneginf(right)
    return bool(same_kind.all())


def _finite_max_abs(values: np.ndarray) -> float:
    """Return the largest finite magnitude in a series, or zero.

    A series that carries a non-finite value must not widen the comparison's
    tolerance: an infinite scale would let every observable pass.
    """

    if values.size == 0:
        return 0.0
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    return float(np.max(np.abs(finite)))


def _format_time(value: float) -> str:
    """Format a grid time for a reason string without a trailing ``.0``."""

    text = f"{float(value):g}"
    return text


def _undefined_label(values: np.ndarray) -> str:
    """Name the undefined value a series carries at its first undefined point."""

    for value in values:
        if np.isnan(value):
            return "NaN"
        if np.isposinf(value):
            return "+inf"
        if np.isneginf(value):
            return "-inf"
    return "a non-finite value"


def _simulate_oracle_trajectory(
    rr: Any, t_end: float, n_steps: int, *, sample_times: np.ndarray | None = None
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Retry BDF convergence failure for a finite law with an unusable Jacobian.

    Fractional powers at zero can make RoadRunner's initial numerical Jacobian
    non-finite although the rate law and trajectory are finite. CVODE Adams uses
    functional iteration instead; retain the same error controls and time grid.
    Some valid source SBML models also make RoadRunner's full-Jacobian query
    raise, so that query failure is recorded and handled like a non-finite
    Jacobian when reaction rates remain finite.
    """
    stiff = bool(rr.integrator.getValue("stiff"))
    attempts: list[dict[str, Any]] = []
    initial_tolerances = list(rr.integrator.getAbsoluteToleranceVector())
    try:
        values = np.asarray(
            (
                rr.simulate(times=sample_times)
                if sample_times is not None
                else rr.simulate(0.0, t_end, n_steps + 1)
            ),
            dtype=float,
        )
    except Exception as exc:
        if not stiff or "CV_CONV_FAILURE" not in str(exc):
            raise
        # Diagnose at the initial state, not at a partially advanced failed step.
        rr.resetAll()
        if not np.isfinite(np.asarray(rr.getReactionRates(), dtype=float)).all():
            raise
        jacobian_error = None
        try:
            jacobian = np.asarray(rr.getFullJacobian(), dtype=float)
        except Exception as diagnostic_exc:
            jacobian_error = f"{type(diagnostic_exc).__name__}: {diagnostic_exc}"
        else:
            if np.isfinite(jacobian).all():
                raise
        attempts.append(
            {
                "stiff": True,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                **(
                    {"jacobian_error": jacobian_error}
                    if jacobian_error is not None
                    else {}
                ),
            }
        )
        rr.integrator.setValue("stiff", False)
        # A scalar tolerance is rescaled from current state by RoadRunner.
        # Preserve the exact initial vector across the failed attempt and reset.
        rr.integrator.setValue("absolute_tolerance", initial_tolerances)
        try:
            values = np.asarray(
                (
                    rr.simulate(times=sample_times)
                    if sample_times is not None
                    else rr.simulate(0.0, t_end, n_steps + 1)
                ),
                dtype=float,
            )
        except Exception as retry_exc:
            raise RuntimeError(
                f"BDF failed: {exc}; Adams retry failed: {retry_exc}"
            ) from retry_exc
        stiff = False
    attempts.append({"stiff": stiff, "passed": True})
    return values, attempts


def _source_action_bngl(
    bngl: str,
    *,
    rtol: float,
    atol: float,
    max_step: float,
    t_end: float,
    n_steps: int,
) -> str:
    """Add the requested comparison grid to generated deterministic ODE actions."""

    pattern = re.compile(
        r"(?im)^(?P<prefix>\s*simulate(?:_ode|_ssa|_nf|_pla|_psa)?\s*\(\s*\{)"
        r"(?P<arguments>[^}\n]*)(?P<suffix>\}\s*\))\s*$"
    )
    found = 0
    previous_end = 0.0
    requested_times = np.linspace(0.0, t_end, n_steps + 1).tolist()
    covered_times: set[int] = set()

    def argument_value(arguments: str, key: str) -> str | None:
        match = re.search(rf"(?i)(?<![A-Za-z0-9_]){key}\s*=>\s*([^,]+)", arguments)
        return match.group(1).strip() if match is not None else None

    def numeric_time(value: str, key: str) -> float:
        try:
            parsed = float(value.strip(" '\""))
        except (TypeError, ValueError) as exc:
            raise OracleIntegrationError(
                f"source ODE action {key} is not a static numeric time"
            ) from exc
        if not math.isfinite(parsed):
            raise OracleIntegrationError(
                f"source ODE action {key} is not a finite numeric time"
            )
        return parsed

    def replace_arguments(arguments: str, updates: dict[str, str]) -> str:
        arguments = re.sub(
            r"(?i)(?:^|,)\s*sample_times\s*=>\s*\[[^\]]*\]\s*(?=,|$)",
            "",
            arguments,
        )
        parts = [part.strip() for part in arguments.split(",") if part.strip()]
        retained = [
            part
            for part in parts
            if not any(re.match(rf"(?i)^{key}\s*=>", part) for key in updates)
            and not re.match(r"(?i)^n_steps\s*=>", part)
            and not re.match(r"(?i)^n_output_steps\s*=>", part)
        ]
        retained.extend(f"{key}=>{value}" for key, value in updates.items())
        return ", ".join(retained)

    def update(match: re.Match[str]) -> str:
        nonlocal found, previous_end
        arguments = match.group("arguments")
        action_name = match.group("prefix").split("(", 1)[0].strip().lower()
        ode_method = (
            action_name == "simulate_ode"
            or re.search(
                r"(?i)\bmethod\s*=>\s*['\"]?(?:ode|cvode)['\"]?\b",
                arguments,
            )
            is not None
        )
        simulation_actions = {
            "simulate",
            "simulate_ode",
            "simulate_ssa",
            "simulate_nf",
            "simulate_pla",
            "simulate_psa",
        }
        if action_name in simulation_actions and not ode_method:
            raise OracleIntegrationError(
                "original-source comparison requires a deterministic ODE action; "
                f"found {action_name}"
            )
        if not ode_method:
            return match.group(0)
        found += 1
        t_end_text = argument_value(arguments, "t_end")
        if t_end_text is None:
            raise OracleIntegrationError(
                "source ODE action has no explicit t_end for the requested grid"
            )
        continuing = (argument_value(arguments, "continue") or "").strip(" '\"").lower()
        is_continuation = continuing in {"1", "true"}
        if found > 1 and not is_continuation:
            raise OracleIntegrationError(
                "generated source ODE actions do not continue one trajectory"
            )
        start_text = argument_value(arguments, "t_start")
        start = (
            numeric_time(start_text, "t_start")
            if start_text is not None
            else previous_end if is_continuation else 0.0
        )
        end = numeric_time(t_end_text, "t_end")
        if start_text is None and is_continuation:
            end += previous_end
        if end < start:
            raise OracleIntegrationError(
                "source ODE action interval ends before it starts"
            )
        tolerance = max(1e-12, abs(t_end) * 1e-12)
        zero_duration = math.isclose(start, end, rel_tol=0.0, abs_tol=tolerance)
        sample_times = [start]
        for index, time_value in enumerate(requested_times):
            if start + tolerance < time_value < end - tolerance:
                sample_times.append(time_value)
            if start - tolerance <= time_value <= end + tolerance:
                covered_times.add(index)
        if end - sample_times[-1] > tolerance:
            sample_times.append(end)
        elif not math.isclose(sample_times[-1], end, rel_tol=0.0, abs_tol=tolerance):
            sample_times.append(end)
        previous_end = end
        updates = {
            "rtol": format(rtol, ".17g"),
            "atol": format(atol, ".17g"),
            "max_step": format(max_step, ".17g"),
            "print_functions": "1",
        }
        if zero_duration:
            # Continued actions drop their initial row. Keep two equal output
            # times so the retained row records the post-assignment state.
            updates["n_steps"] = "1"
        else:
            updates["sample_times"] = (
                "[" + ",".join(format(value, ".17g") for value in sample_times) + "]"
            )
        arguments = replace_arguments(arguments, updates)
        return match.group("prefix") + arguments + match.group("suffix")

    rewritten = pattern.sub(update, bngl)
    if not found:
        raise OracleIntegrationError(
            "generated source BNGL has no deterministic ODE simulation action"
        )
    if len(covered_times) != len(requested_times):
        missing = [
            format(time_value, ".17g")
            for index, time_value in enumerate(requested_times)
            if index not in covered_times
        ]
        raise OracleIntegrationError(
            "generated source ODE actions do not cover requested output times: "
            + ", ".join(missing[:8])
        )
    return rewritten


def _deduplicate_action_trajectory(
    times: np.ndarray, values: np.ndarray, names: list[str]
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Score the post-event row and retain pre-event values as diagnostics."""

    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    if times.ndim != 1 or not times.size or not np.isfinite(times).all():
        raise RuntimeError("BNG3 action trajectory has invalid output times")
    if (np.diff(times) < 0.0).any():
        raise RuntimeError("BNG3 action trajectory output times are not ordered")
    keep: list[int] = []
    pre_event_rows: list[dict[str, Any]] = []
    index = 0
    while index < times.size:
        end = index + 1
        while end < times.size and times[end] == times[index]:
            end += 1
        count = end - index
        if count > 1:
            if count != 2:
                raise OracleIntegrationError(
                    "BNG3 action trajectory has more than two rows at one event time"
                )
            pre_event_rows.append(
                {
                    "time": float(times[index]),
                    "outputs": {
                        name: float(values[index, column + 1])
                        for column, name in enumerate(names)
                    },
                    "scored": False,
                    "reason": "the left-limit source state is not sampled at the event time",
                }
            )
        keep.append(end - 1)
        index = end
    return times[keep], values[keep], pre_event_rows


def _simulate_and_compare(
    cpp_model: Any,
    model_type: Any,
    output_path: Path,
    *,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    native_amount_scale: float = 1.0,
    native_tolerance_context: dict[str, Any] | None = None,
    max_step: float = 0.0,
    function_names: set[str] | None = None,
    reference_model: str | None = None,
    action_bngl: str | None = None,
    action_model_parser: Any | None = None,
    reference_selections: dict[str, str] | None = None,
    comparison_scope: str = COMPARISON_SCOPE,
    source_time_units: str | None = None,
) -> dict[str, Any]:
    """Compare BNG3/CVODE observables with libRoadRunner on one time grid."""

    try:
        import roadrunner
    except ImportError as exc:
        raise OracleIntegrationError(
            "libRoadRunner is required for direct numerical comparison"
        ) from exc

    if not math.isfinite(atol) or atol <= 0.0:
        raise OracleIntegrationError(
            "requested comparison absolute tolerance must be finite and positive"
        )
    if not math.isfinite(native_amount_scale) or native_amount_scale <= 0.0:
        raise OracleIntegrationError(
            "native amount normalization scale must be finite and positive"
        )

    compared_model = (
        "original source SBML" if reference_model is not None else "written SBML"
    )
    try:
        rr = roadrunner.RoadRunner(
            reference_model if reference_model is not None else str(output_path)
        )
        integrator = rr.integrator
        if integrator.hasValue("relative_tolerance"):
            integrator.setValue("relative_tolerance", rtol)
        if integrator.hasValue("absolute_tolerance"):
            integrator.setValue("absolute_tolerance", atol)
        if max_step > 0.0 and integrator.hasValue("maximum_time_step"):
            integrator.setValue("maximum_time_step", max_step)
        if not hasattr(integrator, "getAbsoluteToleranceVector"):
            raise OracleIntegrationError(
                "libRoadRunner integrator does not expose effective absolute "
                "tolerance vectors required for source-faithful comparison"
            )
        tolerance_mapping = "conservative_minima"
        rr_effective_atol_min = None
        rr_state_count = None
        if native_tolerance_context and native_tolerance_context.get(
            "empty_dynamic_species_set"
        ):
            actual_native_atol = atol
            tolerance_mapping = "empty_dynamic_species_set"
        else:
            tolerance_vector = np.asarray(
                integrator.getAbsoluteToleranceVector(), dtype=float
            ).reshape(-1)
            if not np.isfinite(tolerance_vector).all() or (tolerance_vector <= 0).any():
                raise OracleIntegrationError(
                    "libRoadRunner returned non-positive or non-finite effective "
                    "absolute tolerances"
                )
            rr_state_count = int(tolerance_vector.size)
            if rr_state_count:
                rr_effective_atol_min = float(np.min(tolerance_vector))
                derived_native_atol = rr_effective_atol_min * native_amount_scale
                if not math.isfinite(derived_native_atol) or derived_native_atol <= 0.0:
                    raise OracleIntegrationError(
                        "mapped native absolute tolerance is zero or non-finite"
                    )
                actual_native_atol = min(atol, derived_native_atol)
                tolerance_mapping = "conservative_minima"
            else:
                actual_native_atol = atol
                tolerance_mapping = "empty_source_state_vector"
    except OracleIntegrationError:
        raise
    except Exception as exc:
        raise OracleIntegrationError(
            f"the independent oracle (libRoadRunner) could not load the "
            f"{compared_model}: {type(exc).__name__}: {exc}"
        ) from exc

    unscored_pre_event_rows: list[dict[str, Any]] = []
    if action_bngl is not None:
        if action_model_parser is None:
            raise RuntimeError("source action comparison requires a BNGL parser")
        action_source = _source_action_bngl(
            action_bngl,
            rtol=rtol,
            atol=actual_native_atol,
            max_step=max_step,
            t_end=t_end,
            n_steps=n_steps,
        )
        action_cpp_model = action_model_parser(action_source)
        with tempfile.TemporaryDirectory(prefix="biomodels-action-oracle-") as temp:
            action_path = Path(temp) / "source.bngl"
            action_path.write_text(action_source, encoding="utf-8")
            try:
                model_type(action_cpp_model, source_path=str(action_path)).execute()
            except Exception as exc:
                raise BngSimulationError(
                    f"BNG3 action execution could not simulate model: {exc}"
                ) from exc
            gdat_path = action_path.with_suffix(".gdat")
            try:
                lines = gdat_path.read_text(encoding="utf-8").splitlines()
                header = next(line for line in lines if line.startswith("#"))
                columns = header.removeprefix("#").split()
                action_values = np.loadtxt(gdat_path, comments="#", dtype=float)
                action_values = np.atleast_2d(action_values)
            except (OSError, StopIteration, ValueError) as exc:
                raise RuntimeError(
                    f"BNG3 action execution did not produce readable gdat: {exc}"
                ) from exc
            if action_values.ndim != 2 or action_values.shape[1] != len(columns):
                raise RuntimeError("BNG3 action gdat header and data shape differ")
            column_indices = {name: index for index, name in enumerate(columns)}
            observable_names = list(reference_selections or {})
            missing = [name for name in observable_names if name not in column_indices]
            if missing:
                raise RuntimeError(
                    "BNG3 action gdat is missing mapped source outputs: "
                    + ", ".join(missing[:10])
                )
            bng_time, action_values, unscored_pre_event_rows = (
                _deduplicate_action_trajectory(
                    action_values[:, column_indices["time"]],
                    action_values,
                    observable_names,
                )
            )
            requested_times = np.linspace(0.0, t_end, n_steps + 1)
            if not all(
                np.any(np.isclose(bng_time, time_value, rtol=0.0, atol=1e-12))
                for time_value in requested_times
            ):
                raise OracleIntegrationError(
                    "BNG3 action output omits one or more requested comparison times"
                )
            bng_values = {
                name: action_values[:, column_indices[name]]
                for name in observable_names
            }
            if (
                bng_time.size == 0
                or not math.isclose(float(bng_time[0]), 0.0, abs_tol=1e-12)
                or not math.isclose(
                    float(bng_time[-1]), t_end, rel_tol=0.0, abs_tol=1e-9
                )
            ):
                raise RuntimeError(
                    "BNG3 action trajectory does not cover the requested source horizon"
                )
    else:
        try:
            bng_result = model_type(cpp_model).simulate(
                method="ode",
                t_start=0.0,
                t_end=t_end,
                n_steps=n_steps,
                rtol=rtol,
                atol=actual_native_atol,
                max_step=max_step,
            )
        except Exception as exc:
            raise BngSimulationError(
                f"BNG3 CVODE could not simulate model: {exc}"
            ) from exc
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

    def sbml_id(name: str) -> str:
        valid = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
        if valid and valid[0].isdigit():
            valid = "_" + valid
        return valid or "species"

    selected_names: list[str] = []
    missing: list[str] = []
    if reference_selections is not None:
        for name, selection in reference_selections.items():
            if name not in bng_values:
                missing.append(name)
            else:
                selected_names.append(selection)
        observable_names = list(reference_selections)
        bng_values = {
            name: bng_values[name] for name in observable_names if name in bng_values
        }
    else:
        available = set(rr.getAssignmentRuleIds())
        for name in observable_names:
            safe_name = sbml_id(name)
            candidates = [
                safe_name,
                "obs_" + safe_name,
                "func_" + safe_name,
                "param_" + safe_name,
            ]
            selected = next(
                (candidate for candidate in candidates if candidate in available),
                None,
            )
            if selected is None:
                missing.append(name)
            else:
                selected_names.append(selected)
    if missing:
        missing_description = (
            "mapped BNG3 source outputs are missing: "
            if reference_selections is not None
            else "written SBML is missing observable assignment rules: "
        )
        raise RuntimeError(missing_description + ", ".join(missing[:10]))
    rr.timeCourseSelections = ["time", *selected_names]
    try:
        rr_values, oracle_solver_attempts = _simulate_oracle_trajectory(
            rr,
            t_end,
            n_steps,
            sample_times=bng_time if action_bngl is not None else None,
        )
    except Exception as exc:
        # The oracle's own solver failed.  That is a limitation of the
        # measurement, not a disagreement between the two engines.
        raise OracleIntegrationError(
            "the independent oracle (libRoadRunner) could not integrate the "
            f"{compared_model}: {type(exc).__name__}: {exc}"
        ) from exc
    expected_shape = (len(bng_time), len(observable_names) + 1)
    if rr_values.ndim != 2 or rr_values.shape != expected_shape:
        raise RuntimeError(
            f"libRoadRunner returned shape {rr_values.shape}, expected {expected_shape}"
        )
    if not np.allclose(rr_values[:, 0], bng_time, rtol=0.0, atol=max(atol, 1e-12)):
        raise RuntimeError("BNG3 and libRoadRunner produced different time grids")

    comparison_scale = max(
        [
            *(_finite_max_abs(values) for values in bng_values.values()),
            *(
                _finite_max_abs(rr_values[:, index])
                for index in range(1, rr_values.shape[1])
                if rr_values.shape[0]
            ),
            0.0,
        ]
    )
    comparisons: dict[str, dict[str, Any]] = {}
    failed = []
    not_comparable: dict[str, str] = {}
    undefined_points: set[str] = set()
    observable_description = (
        "the original source observable"
        if reference_model is not None
        else "the translated/written observable"
    )
    for index, name in enumerate(observable_names, start=1):
        left = bng_values[name]
        right = rr_values[:, index]
        if left.shape != right.shape:
            raise RuntimeError(f"observable {name!r} returned mismatched shapes")
        finite = bool(np.isfinite(left).all() and np.isfinite(right).all())
        undefined = False
        undefined_at: list[float] = []
        if finite:
            difference = np.abs(left - right)
            scale = max(_finite_max_abs(left), _finite_max_abs(right))
            max_abs = float(np.max(difference)) if difference.size else 0.0
        else:
            # The observable is not a finite number somewhere on the grid.
            # When both engines report the same undefined value at the same
            # points, the compared model's observable is undefined there.
            undefined = _same_undefined_value(left, right)
            if undefined:
                mask = np.isfinite(left) & np.isfinite(right)
                difference = (
                    np.abs(left[mask] - right[mask]) if mask.any() else left[:0]
                )
                scale = max(
                    _finite_max_abs(left[mask]) if mask.any() else 0.0,
                    _finite_max_abs(right[mask]) if mask.any() else 0.0,
                )
                max_abs = float(np.max(difference)) if difference.size else 0.0
                undefined_at = [
                    float(bng_time[position])
                    for position in np.where(~np.isfinite(left))[0]
                    if position < len(bng_time)
                ]
            else:
                difference = np.abs(left - right)
                scale = max(_finite_max_abs(left), _finite_max_abs(right))
                max_abs = float(np.max(difference)) if difference.size else 0.0
        # Cross-engine CVODE paths have small dense-output/RHS differences;
        # scale that floor to this observable so unrelated large series do
        # not make a small series mismatch appear acceptable.
        tolerance = max(
            atol + rtol * scale,
            NUMERICAL_COMPARISON_ATOL_FLOOR + NUMERICAL_COMPARISON_RTOL_FLOOR * scale,
        )
        scaled_error = max_abs / tolerance if tolerance else math.inf
        if undefined:
            # The translated/written observable has no value at this point, so
            # the pointwise comparison cannot be made there. The agreement at
            # finite points is recorded as evidence, but the record is not
            # comparable and must say so rather than claim a pass.
            passed = False
            points = ", ".join(f"t={_format_time(time)}" for time in undefined_at[:5])
            not_comparable[name] = (
                f"{observable_description} is undefined at {points} "
                f"({_undefined_label(left)}); BNG3 and libRoadRunner "
                "report the same undefined value"
            )
            undefined_points.update(points.split(", "))
        else:
            passed = bool(finite) and max_abs <= tolerance
            if not passed:
                failed.append(name)
        comparisons[name] = {
            "finite": finite,
            "undefined": undefined,
            "undefined_at": undefined_at,
            "comparison_scale": scale,
            "max_abs_difference": max_abs,
            "tolerance": tolerance,
            "max_scaled_error": scaled_error,
            "passed": passed,
        }
    base: dict[str, Any] = {
        "method_bngl": (
            "BNG3 CVODE (generated deterministic ODE actions)"
            if action_bngl is not None
            else "BNG3 CVODE (simulate method='ode')"
        ),
        "method_sbml": "libRoadRunner CVODE",
        "roadrunner_version": getattr(roadrunner, "__version__", None),
        "t_start": 0.0,
        "t_end": t_end,
        "n_steps": n_steps,
        "rtol": rtol,
        "atol": atol,
        "requested_comparison_atol": atol,
        "roadrunner_requested_atol": atol,
        "roadrunner_effective_atol_min": rr_effective_atol_min,
        "roadrunner_state_count": rr_state_count,
        "roadrunner_solver_attempts": oracle_solver_attempts,
        "native_solver_atol": actual_native_atol,
        "native_amount_scale": native_amount_scale,
        "native_tolerance_mapping": tolerance_mapping,
        "max_step": max_step,
        "comparison_scope": comparison_scope,
        "comparison_scale_scope": "per_observable",
        "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
        "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
        "comparison_reference_scale": comparison_scale,
        "observable_count": len(observable_names),
        "sbml_observable_ids": dict(zip(observable_names, selected_names)),
        "observables": comparisons,
    }
    if action_bngl is not None:
        base["unscored_pre_event_rows"] = unscored_pre_event_rows
    if native_tolerance_context:
        base.update(native_tolerance_context)
    if source_time_units is not None:
        base["source_time_units"] = source_time_units
    if not_comparable:
        return {
            **base,
            "passed": False,
            "not_comparable": not_comparable,
            "error": (
                observable_description
                + " is undefined at "
                + ", ".join(sorted(undefined_points))
                + ": BNG3 and libRoadRunner report the same undefined value, "
                "so a pointwise comparison cannot measure the record ("
                + ", ".join(sorted(not_comparable)[:10])
                + ")"
            ),
            "failed_observables": failed,
        }
    if failed:
        return {
            **base,
            "passed": False,
            "error": (
                "BNG3 CVODE/libRoadRunner observable mismatch: "
                + ", ".join(failed[:10])
            ),
            "failed_observables": failed,
        }
    return {**base, "passed": True, "failed_observables": []}


SOURCE_COMPARISON_SCOPE = "original_source_sbml_species_output_fidelity"


def _source_species_unit_factors(
    source_model: Any,
) -> dict[str, tuple[float, float]]:
    """Measure effective factors by running the Atomizer's normalizer on probes."""

    from copy import deepcopy

    from bionetgen.atomizer.modern.units import apply_unit_scaling

    normalized = deepcopy(source_model)
    for species in normalized.species.values():
        species.initial_amount = 1.0
        species.initial_amount_set = True
        species.initial_concentration = 1.0
        species.initial_concentration_set = True
    for compartment in normalized.compartments.values():
        compartment.size = 1.0
    apply_unit_scaling(normalized)
    return {
        species_id: (
            float(normalized.species[species_id].initial_amount),
            float(
                normalized.compartments[species.compartment].size
                if species.compartment in normalized.compartments
                else 1.0
            ),
        )
        for species_id, species in normalized.species.items()
    }


def _simulate_source_and_compare(
    cpp: Any,
    bngl: str,
    model_type: Any,
    source_sbml: str,
    source_model: Any,
    observable_map: dict[str, str],
    *,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    max_step: float = 0.0,
    model_id: str,
) -> dict[str, Any]:
    """Compare mapped BNG3 species with the original SBML in libRoadRunner."""

    from bionetgen.atomizer.modern.types import standardize_name
    from scripts.ci.validate_sbml_test_suite import (
        _reference_output_target,
        _with_reference_output_functions,
    )

    from decimal import Decimal

    default_units = {"amount": [], "concentration": []}
    targets: dict[str, str] = {}
    selections: dict[str, str] = {}
    normalizations: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []
    effective_factors = _source_species_unit_factors(source_model)
    for species_id, species in source_model.species.items():
        compartment = source_model.compartments.get(species.compartment)
        dimensions = (
            float(getattr(compartment, "spatial_dimensions", 3))
            if compartment is not None
            else 3.0
        )
        is_zero_dimensional = dimensions == 0.0
        if is_zero_dimensional:
            default_units["amount"].append(species_id)
        target = _reference_output_target(
            species_id,
            default_units,
            source_model,
            observable_map,
            standardize_name,
        )
        if target is None:
            unmapped.append(species_id)
            continue
        substance_factor, compartment_factor = effective_factors[species_id]
        substance_exact = Decimal(str(substance_factor))
        compartment_exact = Decimal(str(compartment_factor))
        quantity_kind = (
            "amount"
            if species.has_only_substance_units or is_zero_dimensional
            else "concentration"
        )
        to_source_factor = (
            Decimal(1) / substance_exact
            if quantity_kind == "amount"
            else compartment_exact / substance_exact
        )
        if not to_source_factor.is_finite() or to_source_factor == 0:
            unmapped.append(species_id)
            continue
        if to_source_factor != Decimal(1):
            target = f"({target}) * {format(to_source_factor.normalize(), 'f')}"
        targets[species_id] = target
        normalizations[species_id] = {
            "quantity_kind": quantity_kind,
            "substance_factor": substance_factor,
            "compartment_factor": compartment_factor,
            "normalized_to_source_factor": float(to_source_factor),
        }
        # SBML's species symbol uses amount when hasOnlySubstanceUnits is true.
        # RoadRunner's bracket selection always requests concentration.
        selections[species_id] = (
            species_id if quantity_kind == "amount" else f"[{species_id}]"
        )

    if not targets:
        return {
            "passed": False,
            "comparison_scope": SOURCE_COMPARISON_SCOPE,
            "comparison_scale_scope": "per_observable",
            "source_time_units": source_model.time_units
            or "unspecified; source numeric time",
            "source_comparison_surface": "mapped_species_outputs",
            "failed_observables": [],
            "not_comparable": {
                "source_species_mapping": "no source species has an exact BNG3 output mapping"
            },
            "error": "original source comparison has no mapped source species",
            "source_species_targets": targets,
            "source_species_roadrunner_selections": selections,
            "unmapped_source_species": unmapped,
        }

    dynamic_species = {
        species_id
        for species_id, species in source_model.species.items()
        if not getattr(species, "constant", False)
        and not getattr(species, "boundary_condition", False)
    }
    amount_factors = [
        float(effective_factors[species_id][0])
        for species_id in dynamic_species
        if species_id in effective_factors
        and math.isfinite(float(effective_factors[species_id][0]))
        and float(effective_factors[species_id][0]) > 0.0
    ]
    if dynamic_species and not amount_factors:
        raise OracleIntegrationError(
            "no positive source-to-native amount factor is available for dynamic states"
        )
    native_amount_scale = min(amount_factors) if amount_factors else 1.0
    native_tolerance_context = {
        "dynamic_species_count": len(dynamic_species),
        "source_to_native_amount_factor_min": (
            native_amount_scale if amount_factors else None
        ),
        "source_normalization_rule": (
            "minimum positive normalized amount per unit source amount "
            "across nonconstant, nonboundary source species"
            if amount_factors
            else "no dynamic source species; retain requested scalar"
        ),
        "empty_dynamic_species_set": not bool(dynamic_species),
    }
    safe_model_id = re.sub(r"[^A-Za-z0-9_]", "_", model_id)
    reference_bngl, aliases = _with_reference_output_functions(
        bngl, targets, safe_model_id
    )
    has_actions = (
        re.search(r"(?im)^\s*simulate(?:_ode|_ssa|_nf|_pla|_psa)?\s*\(", reference_bngl)
        is not None
    )
    reference_model = None if has_actions else cpp.parse_string(reference_bngl)
    reference_selections = {
        aliases[species_id]: selection for species_id, selection in selections.items()
    }

    def compare_with_step(step: float) -> dict[str, Any]:
        return _simulate_and_compare(
            reference_model,
            model_type,
            Path("original-source.sbml"),
            t_end=t_end,
            n_steps=n_steps,
            rtol=rtol,
            atol=atol,
            native_amount_scale=native_amount_scale,
            native_tolerance_context=native_tolerance_context,
            max_step=step,
            function_names=set(aliases.values()),
            reference_model=source_sbml,
            action_bngl=reference_bngl if has_actions else None,
            action_model_parser=cpp.parse_string if has_actions else None,
            reference_selections=reference_selections,
            comparison_scope=SOURCE_COMPARISON_SCOPE,
            source_time_units=source_model.time_units
            or "unspecified; source numeric time",
        )

    comparison = compare_with_step(max_step)
    solver_attempts = [
        {
            "max_step": max_step,
            "passed": bool(comparison.get("passed", False)),
            "failed_observable_count": len(comparison.get("failed_observables", [])),
        }
    ]
    initial_source_comparison_passed = bool(comparison.get("passed", False))
    if (
        not initial_source_comparison_passed
        and comparison.get("failed_observables")
        and not comparison.get("not_comparable")
    ):
        retry_max_step = max(abs(t_end) / 2000.0, 1e-6)
        retries = [retry_max_step * factor for factor in (1.0, 0.2, 0.1, 0.04, 0.02)]
        seen_steps = {max_step} if max_step > 0.0 else set()
        for retry_step in retries:
            if retry_step in seen_steps or retry_step <= 0.0:
                continue
            if max_step > 0.0 and retry_step >= max_step:
                continue
            seen_steps.add(retry_step)
            try:
                refined = compare_with_step(retry_step)
            except RuntimeError as exc:
                solver_attempts.append(
                    {
                        "max_step": retry_step,
                        "passed": False,
                        "failed_observable_count": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            attempt = {
                "max_step": retry_step,
                "passed": bool(refined.get("passed", False)),
                "failed_observable_count": len(refined.get("failed_observables", [])),
            }
            if refined.get("not_comparable"):
                attempt["not_comparable"] = refined["not_comparable"]
            if refined.get("error"):
                attempt["error"] = refined["error"]
            solver_attempts.append(attempt)
            if refined.get("passed", False):
                comparison = refined
                break
    comparison["source_comparison_surface"] = "mapped_species_outputs"
    comparison["initial_source_comparison_passed"] = initial_source_comparison_passed
    comparison["source_solver_attempts"] = solver_attempts
    alias_to_species = {alias: species_id for species_id, alias in aliases.items()}
    if comparison.get("error"):
        for alias, species_id in alias_to_species.items():
            comparison["error"] = comparison["error"].replace(alias, species_id)
    comparison["observables"] = {
        alias_to_species.get(alias, alias): details
        for alias, details in comparison.get("observables", {}).items()
    }
    comparison["sbml_observable_ids"] = {
        alias_to_species.get(alias, alias): selection
        for alias, selection in comparison.get("sbml_observable_ids", {}).items()
    }
    comparison["failed_observables"] = [
        alias_to_species.get(alias, alias)
        for alias in comparison.get("failed_observables", [])
    ]
    if "not_comparable" in comparison:
        comparison["not_comparable"] = {
            alias_to_species.get(alias, alias): reason
            for alias, reason in comparison["not_comparable"].items()
        }
    comparison["source_species_targets"] = targets
    comparison["source_species_normalization"] = normalizations
    comparison["source_species_roadrunner_selections"] = selections
    comparison["unmapped_source_species"] = unmapped
    if unmapped:
        comparison["passed"] = False
        comparison.setdefault("not_comparable", {})["source_species_mapping"] = (
            "no exact BNG3 output mapping for: " + ", ".join(unmapped[:10])
        )
        comparison["error"] = (
            "original source comparison could not measure every species; "
            + ", ".join(unmapped[:10])
        )
    return comparison


def _retry_numerical_comparison(
    comparison: dict[str, Any],
    *,
    compare: Any,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    max_step: float,
) -> dict[str, Any]:
    """Refine both CVODE solves once after a numerical observable mismatch.

    This retry does not relax the comparison predicate. It tightens solver
    tolerances on both engines; unsupported records and solver failures retain
    their original classification.
    """

    if comparison.get("passed") or not comparison.get("failed_observables"):
        return comparison
    refined_rtol = max(float(rtol) * 1e-4, 1e-12)
    refined_atol = max(float(atol) * 1e-8, 1e-24)
    if refined_rtol >= rtol and refined_atol >= atol:
        return comparison

    attempt = {
        "rtol": refined_rtol,
        "atol": refined_atol,
        "max_step": max_step,
    }
    try:
        refined = compare(
            t_end=t_end,
            n_steps=n_steps,
            rtol=refined_rtol,
            atol=refined_atol,
            max_step=max_step,
        )
    except RuntimeError as exc:
        attempt["error"] = str(exc)
        result = dict(comparison)
        result["refinement_attempt"] = attempt
        return result

    attempt["passed"] = bool(refined.get("passed", False))
    if attempt["passed"]:
        refined = dict(refined)
        refined["refinement_attempt"] = attempt
        return refined
    result = dict(comparison)
    result["refinement_attempt"] = attempt
    return result


def _comparison_verdict(
    comparison: dict[str, Any] | None,
    source_comparison: dict[str, Any] | None,
    *,
    oracle_error: Exception | None = None,
    comparison_error: Exception | None = None,
) -> tuple[str, str | None]:
    """Resolve comparison outcomes with semantic failures ahead of gaps."""

    written_failed = comparison is not None and bool(
        comparison.get("failed_observables")
    )
    source_failed = source_comparison is not None and bool(
        source_comparison.get("failed_observables")
    )
    if source_failed:
        return "failed", source_comparison.get(
            "error", "original source SBML comparison failed"
        )
    if written_failed:
        return "failed", comparison.get("error", "numerical comparison failed")
    if source_comparison is not None and source_comparison.get("harness_error"):
        return "harness_error", source_comparison["harness_error"]
    if comparison is None:
        if oracle_error is not None:
            return "not_comparable", str(oracle_error)
        return "failed", str(
            comparison_error or "written comparison produced no result"
        )
    if comparison.get("not_comparable"):
        return "not_comparable", comparison.get(
            "error", "the written comparison could not be measured"
        )
    if not comparison.get("passed", False):
        return "failed", comparison.get("error", "numerical comparison failed")
    if source_comparison is None:
        return "harness_error", "original source SBML comparison returned no result"
    if source_comparison.get("not_comparable"):
        return "not_comparable", source_comparison.get(
            "error", "original source SBML comparison could not be measured"
        )
    if not source_comparison.get("passed", False):
        return "failed", source_comparison.get(
            "error", "original source SBML comparison failed"
        )
    return "passed", None


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
    artifacts_dir: Path | None = None,
    partial_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import (
        Atomizer,
        SBMLParser,
        source_metadata_payload,
        source_metadata_summary,
    )
    from bionetgen.atomizer.modern.types import standardize_name

    mode = "atomized" if mode_atomize else "flat"
    result: dict[str, Any] = partial_result if partial_result is not None else {}
    checkpoint_path = (
        artifacts_dir / f"mode.{mode}.progress.json"
        if artifacts_dir is not None
        else None
    )

    def finish() -> dict[str, Any]:
        _write_mode_checkpoint(result, checkpoint_path, state="complete")
        return result

    result.update(
        mode=mode,
        source_xml={},
        comparison_scope=COMPARISON_SCOPE,
    )
    try:
        with _mode_stage(result, "source-xml-validation"):
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
        return finish()
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
        return finish()
    try:
        with _mode_stage(result, "source-sbml-parse"):
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
        return finish()
    result["source"] = {
        "species": len(source_model.species),
        "reactions": len(source_model.reactions),
        "warnings": _warnings(source_model),
        "metadata": source_metadata_summary(source_model),
    }
    source_metadata = source_metadata_payload(source_model)
    atomizer = Atomizer(
        atomize=mode_atomize,
        quiet_mode=True,
        t_end=simulation_t_end,
        n_steps=simulation_n_steps,
    )
    source_warnings = result["source"]["warnings"]
    try:
        with _mode_stage(result, "atomizer-translation"):
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
            return finish()
        raise
    if not atomized.success:
        raise RuntimeError(atomized.error or "modern Atomizer returned failure")
    if artifacts_dir is not None:
        (artifacts_dir / f"translated.{mode}.bngl").write_text(
            atomized.bngl, encoding="utf-8"
        )
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
        return finish()
    with _mode_stage(result, "network-generation"):
        cpp_model = cpp.parse_string(atomized.bngl)
        network = cpp.generate_network(cpp_model, max_iter=100)
    result["generated_network"] = {
        "species": network.num_species,
        "reactions": network.num_reactions,
    }

    output_path = work_dir / f"{model_id}_{mode}.xml"
    with _mode_stage(result, "sbml-export"):
        cpp.io.write_sbml(
            cpp_model,
            network,
            str(output_path),
            source_metadata=source_metadata,
        )
    if artifacts_dir is not None:
        (artifacts_dir / output_path.name).write_bytes(output_path.read_bytes())
    roundtrip_sbml = output_path.read_text(encoding="utf-8")
    with _mode_stage(result, "written-sbml-validation"):
        result["written_xml"] = _validate_xml(roundtrip_sbml, "written SBML")

    with _mode_stage(result, "roundtrip-sbml-parse"):
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
    with _mode_stage(result, "roundtrip-atomizer-translation"):
        reimport = Atomizer(
            atomize=False,
            quiet_mode=True,
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
        ).atomize(roundtrip_sbml)
    if not reimport.success:
        raise RuntimeError(reimport.error or "round-trip Atomizer returned failure")
    if artifacts_dir is not None:
        (artifacts_dir / f"reimported.{mode}.bngl").write_text(
            reimport.bngl, encoding="utf-8"
        )
    with _mode_stage(result, "roundtrip-network-generation"):
        reimport_cpp = cpp.parse_string(reimport.bngl)
        reimport_network = cpp.generate_network(reimport_cpp, max_iter=100)
    result["reimport_network"] = {
        "species": reimport_network.num_species,
        "reactions": reimport_network.num_reactions,
    }

    with _mode_stage(result, "native-sbml-readback"):
        native = dict(cpp.io.read_sbml(str(output_path), False))
        result["native_reader"] = native
        if not native.get("success"):
            raise RuntimeError(
                native.get("error") or "native SBML reader returned failure"
            )
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

    comparison: dict[str, Any] | None = None
    initial_runtime_error: RuntimeError | None = None
    oracle_error: OracleIntegrationError | None = None
    try:
        with _mode_stage(result, "cross-engine-comparison"):
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
                    if rule.type == "assignment" and rule.variable
                }
                | {
                    standardize_name(str(assignment.symbol))
                    for assignment in source_model.initial_assignments
                    if assignment.symbol
                },
            )
    except OracleIntegrationError as exc:
        oracle_error = exc
    except RuntimeError as exc:
        initial_runtime_error = exc

    # Cross-engine CVODE can fail on a stiff, unit-normalized model before
    # either trajectory is available, or can return a mismatch caused by
    # different adaptive-step histories. Retry with progressively smaller
    # shared internal steps. The first retry remains bounded at t_end/2000;
    # the smaller retries handle models whose unit normalization creates
    # transients below that scale. A successful tighter comparison is still
    # required from both engines, so this cannot turn a real mismatch into a
    # pass by changing only one side.
    if (
        initial_runtime_error is not None
        or oracle_error is not None
        or comparison is None
        or not comparison.get("passed", False)
    ):
        retry_max_step = max(abs(simulation_t_end) / 2000.0, 1e-6)
        retries = [retry_max_step * factor for factor in (1.0, 0.2, 0.1, 0.04, 0.02)]
        last_comparison = comparison
        for retry_max_step in retries:
            try:
                with _mode_stage(result, "cross-engine-comparison-retry"):
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
    source_comparison: dict[str, Any] | None = None
    try:
        with _mode_stage(result, "original-source-sbml-comparison"):
            source_comparison = _simulate_source_and_compare(
                cpp,
                atomized.bngl,
                model_type,
                sbml,
                source_model,
                dict(atomized.observable_map),
                t_end=simulation_t_end,
                n_steps=simulation_n_steps,
                rtol=simulation_rtol,
                atol=simulation_atol,
                model_id=model_id,
            )
    except OracleIntegrationError as exc:
        source_comparison = {
            "passed": False,
            "comparison_scope": SOURCE_COMPARISON_SCOPE,
            "comparison_scale_scope": "per_observable",
            "source_time_units": source_model.time_units
            or "unspecified; source numeric time",
            "source_comparison_surface": "mapped_species_outputs",
            "failed_observables": [],
            "not_comparable": {"oracle": str(exc)},
            "error": str(exc),
        }
    except BngSimulationError as exc:
        source_comparison = {
            "passed": False,
            "comparison_scope": SOURCE_COMPARISON_SCOPE,
            "comparison_scale_scope": "per_observable",
            "source_time_units": source_model.time_units
            or "unspecified; source numeric time",
            "source_comparison_surface": "mapped_species_outputs",
            "failed_observables": ["BNG3 simulation"],
            "error": str(exc),
        }
    except Exception as exc:
        source_comparison = {
            "passed": False,
            "comparison_scope": SOURCE_COMPARISON_SCOPE,
            "comparison_scale_scope": "per_observable",
            "source_time_units": source_model.time_units
            or "unspecified; source numeric time",
            "source_comparison_surface": "mapped_species_outputs",
            "failed_observables": [],
            "harness_error": f"{type(exc).__name__}: {exc}",
            "error": f"original source comparison harness error: {exc}",
        }
    result["source_simulation_comparison"] = source_comparison
    result["source_comparison_scope"] = SOURCE_COMPARISON_SCOPE
    _write_mode_checkpoint(result, checkpoint_path)
    if source_comparison is not None and source_comparison.get("failed_observables"):
        source_comparison = _retry_numerical_comparison(
            source_comparison,
            compare=lambda **settings: _simulate_source_and_compare(
                cpp,
                atomized.bngl,
                model_type,
                sbml,
                source_model,
                dict(atomized.observable_map),
                model_id=model_id,
                **settings,
            ),
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
            rtol=simulation_rtol,
            atol=simulation_atol,
            max_step=float(source_comparison.get("max_step") or 0.0),
        )
        result["source_simulation_comparison"] = source_comparison
    if comparison is None and oracle_error is not None:
        comparison = {
            "passed": False,
            "skipped": False,
            "not_comparable": {"oracle": str(oracle_error)},
            "error": str(oracle_error),
            "method_bngl": "BNG3 CVODE",
            "method_sbml": "libRoadRunner CVODE",
        }
    if comparison is not None and comparison.get("failed_observables"):
        function_names = {
            standardize_name(str(rule.variable))
            for rule in source_model.rules
            if rule.type == "assignment" and rule.variable
        } | {
            standardize_name(str(assignment.symbol))
            for assignment in source_model.initial_assignments
            if assignment.symbol
        }
        comparison = _retry_numerical_comparison(
            comparison,
            compare=lambda **settings: _simulate_and_compare(
                cpp_model,
                model_type,
                output_path,
                function_names=function_names,
                **settings,
            ),
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
            rtol=simulation_rtol,
            atol=simulation_atol,
            max_step=float(comparison.get("max_step") or 0.0),
        )
    result["simulation_comparison"] = comparison
    _write_mode_checkpoint(result, checkpoint_path)
    verdict, reason = _comparison_verdict(
        comparison,
        source_comparison,
        oracle_error=oracle_error,
        comparison_error=initial_runtime_error,
    )
    if verdict != "passed":
        result["status"] = verdict
        result["core_passed"] = False
        if verdict == "not_comparable":
            result["not_comparable_reason"] = reason
        elif verdict == "harness_error":
            result["error"] = reason
        else:
            result["error"] = reason
        return finish()

    limitations = _simulation_limitations(result["source"]["warnings"])
    if limitations:
        result["status"] = "unsupported"
        result["unsupported_reason"] = " ".join(limitations)
        result["core_passed"] = False
        return finish()

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
    return finish()


def _run_isolated_model(
    entry: dict[str, Any], args: argparse.Namespace, *, mode: str | None = None
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
        mode or args.mode,
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
    if args.artifacts_dir is not None:
        command.extend(["--artifacts-dir", str(args.artifacts_dir.resolve())])
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=args.model_timeout,
            # A fresh interpreter randomises its hash seed, and the Atomizer
            # emits part of its output in set-iteration order.  Pinning the
            # seed makes the generated text the same on every run.
            env=fixed_hash_seed_environment(),
        )
        if not worker_json.exists():
            raise RuntimeError(
                f"worker exited {completed.returncode} without a report: "
                f"{completed.stderr[-500:]}"
            )
        worker_record = json.loads(worker_json.read_text(encoding="utf-8"))["records"][
            0
        ]
        progress = phase_progress(completed.stderr, BIOMODELS_CASE_PHASE_PREFIX)
        if progress["active_phase"] is not None or progress["last_completed_phase"]:
            worker_record["phase_progress"] = progress
        if worker_record.get("status") in {
            "failed",
            "timeout",
            "harness_error",
            "not_comparable",
        }:
            worker_record["source_validation"] = _timeout_source_validation(entry, args)
            if args.artifacts_dir is not None:
                _attach_case_packet(worker_record, entry, args)
        return worker_record
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr or ""
        record.update(
            status="timeout",
            core_passed=False,
            error=f"per-model timeout after {args.model_timeout}s",
        )
        progress = phase_progress(stderr, BIOMODELS_CASE_PHASE_PREFIX)
        if progress["active_phase"] is not None or progress["last_completed_phase"]:
            record["phase_progress"] = progress
        record["source_validation"] = _timeout_source_validation(entry, args)
        if args.artifacts_dir is not None:
            checkpoints = _load_mode_checkpoints(entry, args)
            if checkpoints:
                record["mode_checkpoints"] = checkpoints
            _attach_case_packet(record, entry, args)
            _persist_parent_record(record, entry, args)
    except Exception as exc:
        record.update(
            status="harness_error",
            core_passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        worker_json.unlink(missing_ok=True)
    return record


def _timeout_source_validation(
    entry: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    expected = str(entry.get("sha256", "")).lower()
    source_path = _model_source_cache_path(args.cache_dir, entry)
    evidence: dict[str, Any] = {
        "model_id": str(entry.get("id", "")),
        "filename": Path(str(entry.get("filename", ""))).name,
        "expected_sha256": expected or None,
        "status": "unverified",
    }
    if not source_path.is_file():
        evidence["reason"] = "cached source payload is missing"
        return evidence
    actual = _sha256(source_path)
    evidence["actual_sha256"] = actual
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        evidence["reason"] = "inventory does not provide a valid source SHA-256"
    elif actual != expected:
        evidence["status"] = "sha256_mismatch"
        evidence["reason"] = "cached source SHA-256 differs from pinned inventory"
    else:
        evidence["status"] = "verified_sha256"
        evidence["sha256"] = actual
    return evidence


def _load_mode_checkpoints(
    entry: dict[str, Any], args: argparse.Namespace
) -> dict[str, dict[str, Any]]:
    """Load atomically saved per-mode state after an isolated child timeout."""

    model_dir = args.artifacts_dir / str(entry["id"])
    checkpoints: dict[str, dict[str, Any]] = {}
    for mode in ("flat", "atomized"):
        path = model_dir / f"mode.{mode}.progress.json"
        if not path.is_file():
            continue
        try:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(checkpoint, dict)
            and checkpoint.get("mode") == mode
            and checkpoint.get("checkpoint_state") in {"in_progress", "complete"}
        ):
            checkpoints[mode] = checkpoint
    return checkpoints


def _write_case_packet(
    entry: dict[str, Any], args: argparse.Namespace, record: dict[str, Any]
) -> str:
    """Write a small allowlisted packet for a failed or interrupted model."""

    model_dir = args.artifacts_dir / str(entry["id"])
    packet_dir = model_dir / "case-packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    allowed = {
        "source.xml",
        "translated.flat.bngl",
        "translated.atomized.bngl",
        "reimported.flat.bngl",
        "reimported.atomized.bngl",
        f"{entry['id']}_flat.xml",
        f"{entry['id']}_atomized.xml",
        "mode.flat.progress.json",
        "mode.atomized.progress.json",
    }
    files = []
    omitted = []
    # Leave room for the JSON receipt itself so artifacts plus metadata stay
    # within the advertised packet cap.
    remaining = MAX_CASE_PACKET_BYTES - 64 * 1024
    for path in sorted(model_dir.iterdir()):
        if not path.is_file() or path.name not in allowed:
            continue
        size = path.stat().st_size
        if size > MAX_CASE_PACKET_FILE_BYTES or size > remaining:
            omission = {
                "name": path.name,
                "size_bytes": size,
                "reason": "per-file or packet byte cap",
            }
            if path.name == "source.xml":
                omission["sha256"] = _sha256(path)
            omitted.append(omission)
            continue
        target = packet_dir / path.name
        shutil.copyfile(path, target)
        copied_size = target.stat().st_size
        if copied_size > MAX_CASE_PACKET_FILE_BYTES or copied_size > remaining:
            target.unlink()
            omitted.append(
                {
                    "name": path.name,
                    "size_bytes": copied_size,
                    "reason": "copied file exceeds per-file or packet byte cap",
                }
            )
            continue
        remaining -= copied_size
        files.append(
            {
                "name": path.name,
                "size_bytes": copied_size,
                "sha256": _sha256(target),
            }
        )
    packet = {
        "model_id": str(entry["id"]),
        "source_validation": record.get("source_validation", {}),
        "source_xml_representation": (
            "extracted-sbml-utf8"
            if _is_archive_entry(entry)
            else "original-source-bytes"
        ),
        "phase_progress": record.get("phase_progress"),
        "status": record.get("status"),
        "artifacts": files,
        "omitted_artifacts": omitted,
        "included_bytes": MAX_CASE_PACKET_BYTES - 64 * 1024 - remaining,
        "max_bytes": MAX_CASE_PACKET_BYTES,
    }
    packet_path = packet_dir / "packet.json"
    packet_path.write_text(
        json.dumps(_json_compatible(packet), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if packet_path.stat().st_size + packet["included_bytes"] > MAX_CASE_PACKET_BYTES:
        packet_path.unlink()
        raise RuntimeError("case packet metadata exceeded reserved byte budget")
    return str(packet_path)


def _attach_case_packet(
    record: dict[str, Any], entry: dict[str, Any], args: argparse.Namespace
) -> None:
    """Retain the original model verdict if optional packet writing fails."""

    try:
        record["case_packet"] = _write_case_packet(entry, args, record)
    except Exception as exc:
        record["case_packet_error"] = f"{type(exc).__name__}: {exc}"


def _persist_parent_record(
    record: dict[str, Any], entry: dict[str, Any], args: argparse.Namespace
) -> None:
    """Persist parent timeout evidence without replacing its model verdict."""

    try:
        model_dir = args.artifacts_dir / str(entry["id"])
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "record.json").write_text(
            json.dumps(_json_compatible(record), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        record["record_persistence_error"] = f"{type(exc).__name__}: {exc}"


def _load_stage_replay_cohort(
    path: Path,
    *,
    inventory_ids: set[str],
    mode: str,
    model_timeout: int,
) -> dict[str, Any]:
    """Load a small manifest of prior per-mode stage timeouts."""

    cohort = json.loads(path.read_text(encoding="utf-8"))
    if cohort.get("kind") != "curated-biomodels-stage-replay-cohort":
        raise ValueError("invalid stage replay cohort kind")
    if mode not in {"flat", "atomized", "both"}:
        raise ValueError(f"invalid stage replay mode: {mode}")
    if cohort.get("model_timeout_seconds") != model_timeout:
        raise ValueError("stage replay timeout must match cohort timeout")
    report_hashes = cohort.get("source_reports_sha256")
    if (
        not isinstance(report_hashes, dict)
        or set(report_hashes) != {"flat", "atomized"}
        or any(
            not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in report_hashes.values()
        )
    ):
        raise ValueError("stage replay cohort requires flat/atomized report SHA-256s")
    models = cohort.get("models")
    statuses = cohort.get("prior_statuses")
    if not isinstance(models, dict) or not 1 <= len(models) <= 25:
        raise ValueError("stage replay cohort must contain 1 to 25 models")
    if not isinstance(statuses, dict) or set(statuses) != set(models):
        raise ValueError("stage replay prior status records must match models")
    selected: dict[str, list[str]] = {}
    normalized_statuses: dict[str, dict[str, str]] = {}
    allowed_modes = {"flat", "atomized"}
    for model_id, listed_modes in models.items():
        if model_id not in inventory_ids:
            raise ValueError(f"unknown model in stage replay cohort: {model_id}")
        if (
            not isinstance(listed_modes, list)
            or not listed_modes
            or len(set(listed_modes)) != len(listed_modes)
            or not set(listed_modes) <= allowed_modes
        ):
            raise ValueError(f"invalid stage replay modes for {model_id}")
        old_statuses = statuses[model_id]
        if not isinstance(old_statuses, dict) or set(old_statuses) != set(listed_modes):
            raise ValueError(f"stage replay prior status modes disagree for {model_id}")
        if any(status != "timeout" for status in old_statuses.values()):
            raise ValueError(
                f"stage replay prior status must be timeout for {model_id}"
            )
        selected_modes = (
            listed_modes if mode == "both" else [mode] if mode in listed_modes else []
        )
        if selected_modes:
            selected[model_id] = selected_modes
            normalized_statuses[model_id] = {
                selected_mode: old_statuses[selected_mode]
                for selected_mode in selected_modes
            }
    if not selected:
        raise ValueError(f"stage replay cohort has no models for mode {mode}")
    if not cohort.get("source_run_id") or not cohort.get("source_run_commit"):
        raise ValueError("stage replay cohort is missing source run identity")
    return {
        "source_run_id": str(cohort["source_run_id"]),
        "source_run_commit": str(cohort["source_run_commit"]),
        "source_reports_sha256": cohort.get("source_reports_sha256", {}),
        "model_timeout_seconds": model_timeout,
        "models": selected,
        "prior_statuses": normalized_statuses,
        "partial_run": True,
    }


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
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help=(
            "retain each model's source SBML, generated BNGL, exported SBML "
            "and record so two runs' artifacts can be compared"
        ),
    )
    parser.add_argument("--mode", choices=("flat", "atomized", "both"), default="flat")
    parser.add_argument("--refresh-inventory", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--source-bundle-receipt", type=Path)
    parser.add_argument("--source-bundle-manifest", type=Path)
    parser.add_argument(
        "--source-query-inventory",
        type=Path,
        default=repo / "provenance" / "curated-biomodels-query-inventory.json",
    )
    parser.add_argument(
        "--fetch-record-metadata",
        action="store_true",
        help="fetch one BioModels record endpoint per model for exact main-file metadata",
    )
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--only-id")
    parser.add_argument(
        "--replay-cohort",
        type=Path,
        help="replay a bounded manifest of prior per-mode stage timeouts",
    )
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

    if args.replay_cohort and (args.only_id or args.max_models):
        parser.error("--replay-cohort cannot be combined with --only-id/--max-models")

    if bool(args.source_bundle_receipt) != bool(args.source_bundle_manifest):
        parser.error(
            "--source-bundle-receipt and --source-bundle-manifest must be paired"
        )
    verified_no_sbml_archives: dict[str, dict[str, Any]] = {}
    if args.source_bundle_receipt:
        try:
            verified_no_sbml_archives = _verified_no_sbml_archive_records(
                args.source_bundle_receipt,
                args.source_bundle_manifest,
                args.source_query_inventory,
                args.manifest,
                repo_root=repo,
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            print(f"source bundle evidence preflight failed: {exc}", file=sys.stderr)
            return 1

    try:
        package_trace = verify_imported_package(Path(__file__).resolve().parents[2])
    except ForeignPackageError as exc:
        print(f"package preflight failed: {exc}", file=sys.stderr)
        return 1
    if package_trace["package_file"]:
        print(
            f"bionetgen package: {package_trace['package_file']} "
            f"(trace: {package_trace['rule']})",
            file=sys.stderr,
        )
    try:
        import bionetgen._bionetgen_cpp as cpp
        from bionetgen import BioNetGenModel
    except ImportError as exc:
        raise SystemExit(
            "BNG3 C++ extension is unavailable; set PYTHONPATH=python:build/cpp"
        ) from exc
    try:
        extension_trace = verify_native_extension(
            Path(__file__).resolve().parents[2],
            extension_file=cpp.__file__,
            package_trace=package_trace,
        )
    except ForeignPackageError as exc:
        print(f"native extension preflight failed: {exc}", file=sys.stderr)
        return 1
    runtime_info = _runtime_provenance(package_trace, extension_trace)

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
    replay_cohort = None
    if args.replay_cohort:
        try:
            replay_cohort = _load_stage_replay_cohort(
                args.replay_cohort,
                inventory_ids={str(entry["id"]) for entry in all_models},
                mode=args.mode,
                model_timeout=args.model_timeout,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            parser.error(f"invalid stage replay cohort: {exc}")
        selected_models = [
            entry for entry in all_models if str(entry["id"]) in replay_cohort["models"]
        ]
    elif args.only_id:
        selected_models = [entry for entry in all_models if entry["id"] == args.only_id]
        if not selected_models:
            raise SystemExit(
                f"BioModels id is not in the curated inventory: {args.only_id}"
            )
    else:
        selected_models = (
            all_models[: args.max_models] if args.max_models else all_models
        )
    partial = bool(args.max_models or args.only_id or replay_cohort)
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

        negative_evidence = verified_no_sbml_archives.get(str(entry.get("id")))
        if negative_evidence is not None:
            record.update(_verified_no_sbml_archive_outcome(entry, negative_evidence))
            records.append(record)
            print(
                f"{entry['id']}: UNSUPPORTED (verified archive contains no SBML)",
                flush=True,
            )
            continue

        if args.isolate_models and not args.worker:
            sbml_selected.append(entry)
            continue

        model_artifacts: Path | None = None
        try:
            path = _model_source_cache_path(args.cache_dir, entry)
            with case_phase_scope(
                BIOMODELS_CASE_PHASE_PREFIX, "source-sha256-verification"
            ):
                record["sha256"] = _download_if_needed(
                    path, entry, offline=args.offline
                )
            record["source_artifact"] = {
                "format": entry.get("format", ""),
                "filename": entry.get("filename", ""),
                "mime_type": entry.get("mime_type", ""),
                "sha256": record["sha256"],
                "size_bytes": path.stat().st_size,
            }
            if args.artifacts_dir is not None:
                model_artifacts = args.artifacts_dir / str(entry["id"])
                model_artifacts.mkdir(parents=True, exist_ok=True)
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
            if model_artifacts is not None:
                (model_artifacts / "source.xml").write_bytes(
                    _source_xml_artifact_bytes(
                        path, sbml, extracted_from_archive=is_archive
                    )
                )
            with tempfile.TemporaryDirectory(
                prefix=f"{entry['id']}-", dir=args.cache_dir
            ) as temp:
                mode_results = []
                model_modes = (
                    replay_cohort["models"][str(entry["id"])] if replay_cohort else None
                )
                for atomize in modes:
                    mode_name = "atomized" if atomize else "flat"
                    if model_modes is not None and mode_name not in model_modes:
                        continue
                    mode_result: dict[str, Any] = {"mode": mode_name}
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
                                artifacts_dir=model_artifacts,
                                partial_result=mode_result,
                            )
                        )
                    except Exception as exc:
                        mode_results.append(
                            _failed_mode_result(mode_name, mode_result, exc)
                        )
                record["modes"] = mode_results
            mode_statuses = [
                mode_result.get("status", "passed") for mode_result in record["modes"]
            ]
            if "failed" in mode_statuses:
                record["status"] = "failed"
            elif "harness_error" in mode_statuses:
                record["status"] = "harness_error"
            elif "not_comparable" in mode_statuses:
                record["status"] = "not_comparable"
                record["not_comparable_reason"] = "; ".join(
                    mode.get("not_comparable_reason", "")
                    for mode in record["modes"]
                    if mode.get("status") == "not_comparable"
                    and mode.get("not_comparable_reason")
                )
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
        except Exception as exc:  # keep transport errors distinct from model failures
            message = f"{type(exc).__name__}: {exc}"
            record["status"] = _model_exception_status(exc)
            record["core_passed"] = False
            record["error"] = message
            if isinstance(exc, SourceAcquisitionError):
                record["source_acquisition_attempts"] = exc.attempts
            if isinstance(exc, SourceIntegrityError):
                record["source_integrity"] = {
                    "expected_sha256": exc.expected_sha256,
                    "actual_sha256": exc.actual_sha256,
                }
            if record["status"] == "unsupported":
                record["unsupported_reason"] = message
        if model_artifacts is not None:
            (model_artifacts / "record.json").write_text(
                json.dumps(_json_compatible(record), indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        records.append(record)
        print(f"{entry['id']}: {record['status'].upper()}", flush=True)

    if sbml_selected:
        if args.jobs < 1:
            raise SystemExit("--jobs must be at least one")

        def run_isolated(entry: dict[str, Any]) -> dict[str, Any]:
            selected_modes = (
                replay_cohort["models"][str(entry["id"])] if replay_cohort else []
            )
            worker_mode = (
                (selected_modes[0] if len(selected_modes) == 1 else "both")
                if replay_cohort
                else None
            )
            return _run_isolated_model(entry, args, mode=worker_mode)

        cache_migration = _migrate_legacy_source_cache(args.cache_dir, sbml_selected)
        print(
            "source cache: "
            f"{cache_migration['migrated']} legacy payloads migrated by SHA; "
            f"{cache_migration['missing']} expected hashes not cached",
            file=sys.stderr,
            flush=True,
        )
        if args.jobs == 1:
            isolated_records = [run_isolated(entry) for entry in sbml_selected]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                isolated_records = list(pool.map(run_isolated, sbml_selected))
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
    harness_errors = sum(record.get("status") == "harness_error" for record in records)
    timeouts = sum(record.get("status") == "timeout" for record in records)
    not_comparable = sum(record.get("status") == "not_comparable" for record in records)
    report = {
        "schema_version": 5,
        "manifest": str(args.manifest.resolve()),
        "cache_dir": str(args.cache_dir.resolve()),
        "runtime_provenance": runtime_info,
        "writer_sbml_version": "L3V2",
        "inventory": inventory,
        "completeness": completeness,
        "mode": args.mode,
        "replay_cohort": replay_cohort,
        "simulation": {
            "t_start": 0.0,
            "t_end": args.simulation_t_end,
            "n_steps": args.simulation_n_steps,
            "rtol": args.simulation_rtol,
            "atol": args.simulation_atol,
            "comparison_scope": COMPARISON_SCOPE,
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
            "not_comparable_records": not_comparable,
            "failed_records": failed,
            "harness_error_records": harness_errors,
            "timeout_records": timeouts,
        },
        "core_passed": (
            not partial
            and completeness["counts_match"]
            and failed == 0
            and harness_errors == 0
            and timeouts == 0
            and sbml_unsupported == 0
            and passed == len(sbml_records)
        ),
        "supported_surface_passed": (
            _supported_surface_passed(
                partial=partial,
                counts_match=completeness["counts_match"],
                failed_records=failed,
                harness_error_records=harness_errors,
                timeout_records=timeouts,
                not_comparable_records=not_comparable,
            )
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
        f"unsupported={unsupported} not_comparable={not_comparable} "
        f"failed={failed} harness_errors={harness_errors} timeouts={timeouts} "
        f"core={'PASS' if report['core_passed'] else 'FAIL'} "
        f"package={runtime_info['bionetgen_package_path']} "
        f"extension_sha256={runtime_info['native_extension_sha256']}"
    )
    return 0 if report["core_passed"] else 1


if __name__ == "__main__":
    # The interpreter reads its hash seed at start-up, so the seed has to be
    # fixed before the harness does any work.  This re-executes the harness
    # once when the interpreter it was started in did not have the fixed seed.
    ensure_fixed_hash_seed()
    raise SystemExit(main())
