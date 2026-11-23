"""Consume the hosted flat and atomized BioModels source comparisons."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

CHECKS = ("release-biomodels", "release-biomodels-triage", "release-obligation-162")


def _read(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _by_id(records, label: str) -> dict:
    indexed = {row["id"]: row for row in records}
    if not indexed or len(indexed) != len(records) or "" in indexed:
        raise ValueError(f"{label}: missing or duplicate model IDs")
    return indexed


def _comparison_passed(mode: dict) -> bool:
    source_xml = mode.get("source_xml") or {}
    original = mode.get("source_simulation_comparison") or {}
    observables = original.get("observables") or {}
    return (
        source_xml.get("validator") == "libsbml"
        and source_xml.get("passed") is True
        and (mode.get("simulation_comparison") or {}).get("passed") is True
        and original.get("passed") is True
        and original.get("method_sbml") == "libRoadRunner CVODE"
        and bool(original.get("roadrunner_version"))
        and any(
            original.get("comparison_scope")
            == f"original_source_sbml_{kind}_output_fidelity"
            and not original.get(f"unmapped_source_{kind}")
            and set(observables) == set(original.get(f"source_{kind}_targets") or {})
            for kind in ("species", "parameter")
        )
        and bool(observables)
        and all(value.get("passed") is True for value in observables.values())
    )


def _case_verdict(record: dict, pinned: dict, mode_name: str) -> str:
    """Keep policy dispositions separate from independent supported execution."""
    if any(
        record.get(key) != pinned.get(key) for key in ("format", "filename", "sha256")
    ):
        return "source-identity-mismatch"
    status = record.get("status")
    if status in {"failed", "timeout", "not_comparable", "harness_error"}:
        return status
    reason = str(record.get("unsupported_reason") or "")
    classification = pinned.get("source_classification")
    if (
        status == "unsupported_format"
        and classification in {"declared_non_sbml", "zip_archive_verified_no_sbml"}
        and pinned.get("payload_included") is False
        and reason
    ):
        return "non-sbml-source"
    if (record.get("source_artifact") or {}).get("sha256") != pinned["sha256"]:
        return "source-payload-unverified"
    if (
        status == "unsupported"
        and classification == "combine_archive_verified_no_sbml"
        and "no usable SBML" in reason
    ):
        return "non-sbml-source"
    modes = record.get("modes") or []
    mode = modes[0] if len(modes) == 1 and modes[0].get("mode") == mode_name else {}
    if status == "passed":
        return (
            "compared" if _comparison_passed(mode) else "incomplete-source-comparison"
        )
    if status == "unsupported":
        source_xml = mode.get("source_xml") or {}
        if (
            source_xml.get("passed") is False
            and "libSBML error(s)" in str(source_xml.get("error", ""))
            and reason.startswith("source SBML is not libSBML-valid:")
        ):
            return "invalid-source"
        source = mode.get("source") or {}
        for package in ("fbc", "qual", "spatial"):
            if (
                source_xml.get("passed") is True
                and source_xml.get("validator") == "libsbml"
                and source.get(f"package_{package}", 0) > 0
                and reason.startswith(f"SBML {package} package is present;")
            ):
                return f"decision-excluded-package:{package}"
        return "unresolved-refusal"
    return str(status or "missing-verdict")


def build_release_record(
    revision: str,
    inventory_path: Path,
    bundle_manifest_path: Path,
    bundle_receipt_path: Path,
    package_path: Path,
    reports: dict[str, Path],
) -> dict:
    inventory, inventory_hash = _read(inventory_path)
    bundle, bundle_manifest_hash = _read(bundle_manifest_path)
    receipt, receipt_hash = _read(bundle_receipt_path)
    package, package_hash = _read(package_path)
    native_hash = str(package.get("native_extension_sha256") or "")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", revision)
        or any(
            package.get(key) != revision
            for key in (
                "source_revision",
                "product_source_revision",
                "validation_harness_revision",
                "git_head",
            )
        )
        or not re.fullmatch(r"[0-9a-f]{64}", native_hash)
    ):
        raise ValueError(
            "BioModels package identity does not bind the exact revision and native extension"
        )
    pinned = _by_id(inventory["models"], "pinned inventory")
    bundled = _by_id(bundle["records"], "source bundle")
    if (
        inventory["matches"] != len(pinned)
        or bundled.keys() != pinned.keys()
        or bundle["inventory_sha256"] != inventory_hash
        or receipt["status"] != "verified"
        or receipt["selected_id"] is not None
        or receipt["inventory_sha256"] != inventory_hash
        or receipt["bundle_sha256"] != bundle["bundle_sha256"]
        or receipt["bundle_manifest_sha256"] != bundle_manifest_hash
        or receipt["records_verified"] != len(pinned)
        or receipt["payloads_verified"] != bundle["payload_count"]
        or receipt["payloads_installed"] != bundle["payload_count"]
        or any(
            bundled[model_id].get(key) != row.get(key)
            for model_id, row in pinned.items()
            for key in ("format", "filename", "sha256")
        )
    ):
        raise ValueError("BioModels source bundle and pinned membership do not agree")

    modes = {}
    for mode_name in ("flat", "atomized"):
        report, report_hash = _read(reports[mode_name])
        if report["runtime_provenance"]["native_extension_sha256"] != native_hash:
            raise ValueError(
                f"{mode_name}: native extension differs from package identity"
            )
        records = _by_id(report["records"], mode_name)
        completeness = report["completeness"]
        if (
            report["mode"] != mode_name
            or records.keys() != pinned.keys()
            or completeness["partial_run"] is not False
            or completeness["counts_match"] is not True
            or completeness["expected_records"] != len(pinned)
        ):
            raise ValueError(f"{mode_name}: incomplete or foreign BioModels inventory")
        outcomes = {
            key: _case_verdict(records[key], bundled[key], mode_name)
            for key in sorted(records)
        }
        unresolved = [
            key
            for key, verdict in outcomes.items()
            if verdict not in {"compared", "non-sbml-source", "invalid-source"}
            and not verdict.startswith("decision-excluded-package:")
        ]
        modes[mode_name] = {
            "report_sha256": report_hash,
            "counts": dict(Counter(outcomes.values())),
            "unresolved": unresolved,
            "outcomes": outcomes,
        }
    passed = all(
        m["counts"].get("compared") and not m["unresolved"] for m in modes.values()
    )
    return {
        "schema_version": 1,
        "case": "issue-162-curated-biomodels",
        "source": {"revision": revision, "dirty": False},
        "references": {
            "inventory_sha256": inventory_hash,
            "source_bundle_receipt_sha256": receipt_hash,
            "package_identity_sha256": package_hash,
            "native_extension_sha256": native_hash,
        },
        "results": [
            {
                "id": check,
                "status": "PASS" if passed else "FAIL",
                "evidence_kind": "supported-execution",
                "supported_execution": passed,
                "related_issues": [162],
                "detail": "Flat and atomized comparison and disposition outcomes are retained per model.",
            }
            for check in CHECKS
        ],
        "modes": modes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    for option in (
        "inventory",
        "bundle-manifest",
        "bundle-receipt",
        "package-identity",
        "flat-report",
        "atomized-report",
        "output",
    ):
        parser.add_argument(f"--{option}", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = build_release_record(
            args.revision,
            args.inventory,
            args.bundle_manifest,
            args.bundle_receipt,
            args.package_identity,
            {"flat": args.flat_report, "atomized": args.atomized_report},
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"BioModels acceptance evidence is invalid: {exc}", file=sys.stderr)
        return 2
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for name, mode in record["modes"].items():
        print(f"{name}: {mode['counts']}")
    return 0 if all(r["status"] == "PASS" for r in record["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
