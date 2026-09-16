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
import json
import math
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
            row.get("_source", row)
            for row in hits["hits"]
            if isinstance(row, dict)
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
        if fetch_metadata and not offline and _update_cached_artifact_metadata(
            inventory, manifest
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
            document.getError(index).getMessage()
            for index in range(min(errors, 5))
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


def _simulation_limitations(warnings: list[dict[str, Any]]) -> list[str]:
    limitations = []
    for warning in warnings:
        message = str(warning["message"])
        lower = message.lower()
        if warning["severity"] == "dropped" or (
            "event" in lower and "not executed" in lower
        ):
            limitations.append(message)
    return limitations


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
            'package detected',
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
    )
    observable_names = list(bng_result.observables)
    bng_time = np.asarray(bng_result.time, dtype=float)
    bng_values = {
        name: np.asarray(bng_result.observables[name], dtype=float)
        for name in observable_names
    }

    rr = roadrunner.RoadRunner(str(output_path))
    integrator = rr.integrator
    if integrator.hasValue("relative_tolerance"):
        integrator.setValue("relative_tolerance", rtol)
    if integrator.hasValue("absolute_tolerance"):
        integrator.setValue("absolute_tolerance", atol)
    available = set(rr.getAssignmentRuleIds())

    def sbml_id(name: str) -> str:
        valid = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
        if valid and valid[0].isdigit():
            valid = "_" + valid
        return valid or "species"

    selected_names = []
    missing = []
    for name in observable_names:
        candidates = [sbml_id(name), "obs_" + sbml_id(name)]
        selected = next((candidate for candidate in candidates if candidate in available), None)
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
    if not np.allclose(
        rr_values[:, 0], bng_time, rtol=0.0, atol=max(atol, 1e-12)
    ):
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
        raise RuntimeError(
            "BNG3 CVODE/libRoadRunner observable mismatch: "
            + ", ".join(failed[:10])
        )
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
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import Atomizer, SBMLParser

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
    try:
        source_model = SBMLParser().parse(sbml)
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
    }
    atomizer = Atomizer(atomize=mode_atomize, quiet_mode=True)
    source_warnings = result["source"]["warnings"]
    try:
        atomized = atomizer.atomize(sbml)
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
    for warning in _warnings(atomizer.model):
        if warning not in source_warnings:
            source_warnings.append(warning)
    result["source"]["warnings"] = source_warnings
    source_limitations = _simulation_limitations(source_warnings)
    if not source_model.species and not any(
        rule.type == "rate" for rule in source_model.rules
    ):
        source_limitations.append(
            "SBML model has no species or rate-rule state variable for a "
            "BNGL network/simulation round-trip."
        )
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
    cpp.io.write_sbml(cpp_model, network, str(output_path))
    roundtrip_sbml = output_path.read_text(encoding="utf-8")
    result["written_xml"] = _validate_xml(roundtrip_sbml, "written SBML")

    roundtrip_model = SBMLParser().parse(roundtrip_sbml)
    result["reimport_parser"] = {
        "species": len(roundtrip_model.species),
        "reactions": len(roundtrip_model.reactions),
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

    # Empty SBML models are valid documents, but they have no BNGL state
    # variables or observables on which to run the requested numerical parity
    # gate. Keep this as an explicit model-class limitation rather than
    # allowing the zero-state simulator path to segfault.
    if network.num_species == 0:
        result["status"] = "unsupported"
        result["unsupported_reason"] = (
            "Zero-species SBML model has no BNGL state variables or "
            "observables for numerical comparison."
        )
        result["simulation_comparison"] = {
            "passed": False,
            "skipped": True,
            "reason": result["unsupported_reason"],
            "method_bngl": "BNG3 CVODE",
            "method_sbml": "libRoadRunner CVODE",
            "observable_count": 0,
        }
        result["core_passed"] = False
        return result

    result["simulation_comparison"] = _simulate_and_compare(
        cpp_model,
        model_type,
        output_path,
        t_end=simulation_t_end,
        n_steps=simulation_n_steps,
        rtol=simulation_rtol,
        atol=simulation_atol,
    )

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
        "--manifest", type=Path, default=repo / "provenance" / "published-biomodels.json"
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("flat", "atomized", "both"), default="flat"
    )
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
            raise SystemExit(f"BioModels id is not in the curated inventory: {args.only_id}")
    else:
        selected_models = all_models[: args.max_models] if args.max_models else all_models
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
                    reason = (
                        f"{entry.get('format', 'archive')} contains no usable SBML: {exc}"
                    )
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
            mode_statuses = [mode_result.get("status", "passed") for mode_result in record["modes"]]
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
            isolated_records = [_run_isolated_model(entry, args) for entry in sbml_selected]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                isolated_records = list(
                    pool.map(lambda entry: _run_isolated_model(entry, args), sbml_selected)
                )
        records.extend(isolated_records)
        for record in isolated_records:
            print(f"{record['id']}: {record['status'].upper()}", flush=True)

    # Keep the report in inventory order even when isolated workers complete
    # concurrently and format-only records were handled inline.
    order = {entry["id"]: index for index, entry in enumerate(selected_models)}
    records.sort(key=lambda record: order[record["id"]])

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
        "schema_version": 3,
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
            not partial and completeness["counts_match"] and failed == 0 and timeouts == 0
        ),
        "unsupported_formats_are_explicit": True,
        "simulation_comparison_is_required": True,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        args.json.write_text(
            json.dumps({"records": records, "summary": report["summary"]}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    else:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"records={len(records)} sbml_passed={passed}/{len(sbml_records)} "
        f"unsupported={unsupported} failed={failed} timeouts={timeouts} "
        f"core={'PASS' if report['core_passed'] else 'FAIL'}"
    )
    return 0 if report["core_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
