#!/usr/bin/env python3
"""Export detailed, stable CSV rows from the round-trip JSON reports."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FIELDS = [
    "report_kind",
    "report_schema_version",
    "report_roundtrip_gate",
    "report_core_passed",
    "report_supported_surface_passed",
    "inventory_complete",
    "suite_commit",
    "category",
    "id",
    "name",
    "version",
    "format",
    "source",
    "filename",
    "sha256",
    "status",
    "core_passed",
    "roundtrip_gate",
    "detailed_reason",
    "unsupported_reason",
    "error",
    "extracted_sbml",
    "source_artifact_json",
    "sbml_member",
    "sbml_candidates_json",
    "mode_statuses_json",
    "mode_errors_json",
    "mode_reasons_json",
    "source_xml_passed",
    "source_species",
    "source_reactions",
    "source_warnings_json",
    "source_metadata_json",
    "source_packages_json",
    "source_package_required_json",
    "source_package_counts_json",
    "source_cv_terms",
    "source_annotation_resources",
    "source_metadata_entities",
    "source_notes",
    "source_annotations",
    "source_sbo_terms",
    "source_metaids",
    "generated_species",
    "generated_reactions",
    "written_xml_passed",
    "reimport_species",
    "reimport_reactions",
    "reimport_metadata_json",
    "metadata_roundtrip_status",
    "native_reader_success",
    "native_species_count",
    "native_reaction_count",
    "simulation_passed",
    "simulation_skipped",
    "simulation_reason",
    "simulation_method_bngl",
    "simulation_method_sbml",
    "simulation_t_end",
    "simulation_n_steps",
    "simulation_rtol",
    "simulation_atol",
    "comparison_reference_scale",
    "comparison_atol_floor",
    "comparison_rtol_floor",
    "max_observable_abs_difference",
    "max_observable_tolerance",
    "failed_observables",
    "observables_json",
    "reproducibility_command",
]


def _json(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _warnings(record: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("source", "source_model"):
        value = record.get(key)
        if isinstance(value, dict) and isinstance(value.get("warnings"), list):
            return value["warnings"]
    return []


def _primary_mode(record: dict[str, Any]) -> dict[str, Any]:
    modes = record.get("modes")
    if isinstance(modes, list) and modes:
        return modes[0] if isinstance(modes[0], dict) else {}
    return record


def _max_comparison(simulation: dict[str, Any], field: str) -> Any:
    values = [
        comparison.get(field)
        for comparison in (simulation.get("observables") or {}).values()
        if isinstance(comparison, dict) and comparison.get(field) is not None
    ]
    return max(values) if values else ""


def _reason(record: dict[str, Any], modes: list[dict[str, Any]]) -> str:
    if record.get("status") == "passed":
        return (
            "All configured source XML, Atomizer/C++ generation, latest SBML "
            "writer validation, reimport, native-reader, and numerical parity "
            "checks passed."
        )
    reasons = []
    for value in (
        record.get("unsupported_reason"),
        record.get("error"),
    ):
        if value:
            reasons.append(str(value))
    for mode in modes:
        for value in (mode.get("unsupported_reason"), mode.get("error")):
            if value:
                reasons.append(f"{mode.get('mode', 'mode')}: {value}")
    for warning in _warnings(record):
        message = str(warning.get("message", ""))
        if message and warning.get("severity") in {"dropped", "approximated"}:
            reasons.append(f"{warning.get('category', 'warning')}: {message}")
    unique = list(dict.fromkeys(reasons))
    return " | ".join(unique) or "No structured reason was recorded."


def _command(report: dict[str, Any], kind: str) -> str:
    python = "/opt/anaconda3/bin/python"
    if kind == "curated":
        mode = report.get("mode", "flat")
        return (
            "PYTHONPATH=python:build/cpp "
            f"{python} scripts/ci/validate_published_biomodels.py "
            f"--manifest {report.get('manifest', '')} "
            f"--cache-dir {report.get('cache_dir', '')} "
            "--json outputs/curated_biomodels_roundtrip.json --offline "
            f"--mode {mode} --isolate-models --jobs 8 --model-timeout 120"
        )
    categories = " ".join(report.get("categories", []))
    return (
        "PYTHONPATH=python:build/cpp "
        f"{python} scripts/ci/validate_sbml_test_suite.py "
        f"--suite-dir {report.get('suite_dir', '')} "
        "--json outputs/sbml_test_suite_roundtrip.json "
        f"--categories {categories} --isolate-cases --case-timeout 60"
    )


def _row(
    report: dict[str, Any], record: dict[str, Any], kind: str
) -> dict[str, Any]:
    modes = [mode for mode in record.get("modes", []) if isinstance(mode, dict)]
    primary = _primary_mode(record)
    source_info = record.get("source_model") or record.get("source") or {}
    if not isinstance(source_info, dict):
        source_info = {}
    source_xml = primary.get("source_xml") or record.get("source_xml") or {}
    generated = primary.get("generated_network") or record.get("generated_network") or {}
    written = primary.get("written_xml") or record.get("written_xml") or {}
    reimport = primary.get("reimport_network") or record.get("reimport_network") or {}
    native = primary.get("native_reader") or record.get("native_reader") or {}
    simulation = primary.get("simulation_comparison") or record.get(
        "simulation_comparison", {}
    )
    if not isinstance(simulation, dict):
        simulation = {}
    source_metadata = source_info.get("metadata", {})
    if not isinstance(source_metadata, dict):
        source_metadata = {}
    reimport_model = primary.get("reimport_model") or record.get(
        "reimport_model", {}
    )
    if not isinstance(reimport_model, dict):
        reimport_model = {}
    reimport_metadata = reimport_model.get("metadata", {})
    if not isinstance(reimport_metadata, dict):
        reimport_metadata = {}
    metadata_roundtrip = record.get("metadata_roundtrip", {})
    if not isinstance(metadata_roundtrip, dict):
        metadata_roundtrip = {}
    statuses = [mode.get("status", "passed") for mode in modes]
    mode_errors = {mode.get("mode", "mode"): mode.get("error", "") for mode in modes}
    mode_reasons = {
        mode.get("mode", "mode"): mode.get("unsupported_reason", "")
        for mode in modes
    }
    status = str(record.get("status", ""))
    row = {field: "" for field in FIELDS}
    row.update(
        {
            "report_kind": kind,
            "report_schema_version": report.get("schema_version", ""),
            "report_roundtrip_gate": "PASS" if report.get("core_passed") else "FAIL",
            "report_core_passed": _value(report.get("core_passed")),
            "report_supported_surface_passed": _value(
                report.get("supported_surface_passed")
            ),
            "inventory_complete": _value(
                (report.get("completeness") or {}).get("counts_match", "")
            ),
            "suite_commit": report.get("suite_commit", ""),
            "category": record.get("category", ""),
            "id": record.get("id", ""),
            "name": record.get("name", ""),
            "version": record.get("version", ""),
            "format": record.get("format", ""),
            "source": record.get("source") or record.get("record_url", ""),
            "filename": record.get("filename", ""),
            "sha256": record.get("sha256", ""),
            "status": status,
            "core_passed": _value(record.get("core_passed")),
            "roundtrip_gate": status.upper(),
            "detailed_reason": _reason(record, modes),
            "unsupported_reason": record.get("unsupported_reason", ""),
            "error": record.get("error", ""),
            "extracted_sbml": _value(record.get("extracted_sbml")),
            "source_artifact_json": _json(record.get("source_artifact")),
            "sbml_member": (record.get("source_artifact") or {}).get("sbml_member", ""),
            "sbml_candidates_json": _json(
                (record.get("source_artifact") or {}).get("sbml_candidates")
            ),
            "mode_statuses_json": _json(statuses),
            "mode_errors_json": _json(mode_errors),
            "mode_reasons_json": _json(mode_reasons),
            "source_xml_passed": _value(source_xml.get("passed")),
            "source_species": source_info.get("species", ""),
            "source_reactions": source_info.get("reactions", ""),
            "source_warnings_json": _json(_warnings(record)),
            "source_metadata_json": _json(source_metadata),
            "source_packages_json": _json(source_metadata.get("packages")),
            "source_package_required_json": _json(
                {
                    package: value.get("required", False)
                    for package, value in (source_metadata.get("packages") or {}).items()
                    if isinstance(value, dict)
                }
            ),
            "source_package_counts_json": _json(
                {
                    package: value.get("elementCount", 0)
                    for package, value in (source_metadata.get("packages") or {}).items()
                    if isinstance(value, dict)
                }
            ),
            "source_cv_terms": source_metadata.get("cvTerms", ""),
            "source_annotation_resources": source_metadata.get(
                "annotationResources", ""
            ),
            "source_metadata_entities": source_metadata.get("metadataEntities", ""),
            "source_notes": source_metadata.get("notes", ""),
            "source_annotations": source_metadata.get("annotations", ""),
            "source_sbo_terms": source_metadata.get("sboTerms", ""),
            "source_metaids": source_metadata.get("metaids", ""),
            "generated_species": generated.get("species", ""),
            "generated_reactions": generated.get("reactions", ""),
            "written_xml_passed": _value(written.get("passed")),
            "reimport_species": reimport.get("species", ""),
            "reimport_reactions": reimport.get("reactions", ""),
            "reimport_metadata_json": _json(reimport_metadata),
            "metadata_roundtrip_status": metadata_roundtrip.get("status", ""),
            "native_reader_success": _value(native.get("success")),
            "native_species_count": native.get("species_count", ""),
            "native_reaction_count": native.get("reaction_count", ""),
            "simulation_passed": _value(simulation.get("passed")),
            "simulation_skipped": _value(simulation.get("skipped")),
            "simulation_reason": simulation.get("reason", ""),
            "simulation_method_bngl": simulation.get("method_bngl", ""),
            "simulation_method_sbml": simulation.get("method_sbml", ""),
            "simulation_t_end": simulation.get("t_end", ""),
            "simulation_n_steps": simulation.get("n_steps", ""),
            "simulation_rtol": simulation.get("rtol", ""),
            "simulation_atol": simulation.get("atol", ""),
            "comparison_reference_scale": simulation.get(
                "comparison_reference_scale", ""
            ),
            "comparison_atol_floor": simulation.get("comparison_atol_floor", ""),
            "comparison_rtol_floor": simulation.get("comparison_rtol_floor", ""),
            "max_observable_abs_difference": _max_comparison(
                simulation, "max_abs_difference"
            ),
            "max_observable_tolerance": _max_comparison(simulation, "tolerance"),
            "failed_observables": _json(
                [
                    name
                    for name, comparison in (simulation.get("observables") or {}).items()
                    if isinstance(comparison, dict) and not comparison.get("passed", False)
                ]
            ),
            "observables_json": _json(simulation.get("observables")),
            "reproducibility_command": _command(report, kind),
        }
    )
    return row


def _export(report_path: Path, output_path: Path, kind: str) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = [_row(report, record, kind) for record in report.get("records", [])]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", type=Path)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.curated is None and args.suite is None:
        parser.error("provide --curated and/or --suite")
    if args.curated:
        _export(args.curated, args.out_dir / "curated_biomodels_roundtrip.csv", "curated_biomodels")
    if args.suite:
        _export(args.suite, args.out_dir / "sbml_test_suite_roundtrip.csv", "sbml_test_suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
