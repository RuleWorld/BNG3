"""Consume the hosted flat and atomized BioModels source comparisons."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci import sbml_162_disposition as disposition

CHECKS = ("release-biomodels", "release-biomodels-triage", "release-obligation-162")

# Verdicts the recorder already treats as resolved without this module's
# dispositions. Everything else must be an explicit, evidence-backed
# disposition or remains unresolved and fails the gate.
BASE_DISPOSED = {"compared", "non-sbml-source", "invalid-source", "not_comparable"}


def _read(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _by_id(records, label: str) -> dict:
    indexed = {row["id"]: row for row in records}
    if not indexed or len(indexed) != len(records) or "" in indexed:
        raise ValueError(f"{label}: missing or duplicate model IDs")
    return indexed


def _independent_oracle_recorded(comparison: dict) -> bool:
    method = comparison.get("method_sbml")
    if method == "libRoadRunner CVODE":
        return bool(comparison.get("roadrunner_version"))
    if method != "sbmlsim-core CVODE":
        return False
    oracle = comparison.get("delay_oracle") or {}
    attempts = oracle.get("solver_attempts") or []
    return (
        oracle.get("version") == "0.20.0"
        and bool(oracle.get("libsbml_version"))
        and "Unable to support delay differential equations"
        in str(oracle.get("roadrunner_refusal"))
        and all(
            re.fullmatch(r"[0-9a-f]{64}", str(oracle.get(key)))
            for key in ("original_sbml_sha256", "converted_sbml_sha256")
        )
        and bool(attempts)
        and attempts[-1].get("passed") is True
    )


def _comparison_passed(mode: dict) -> bool:
    source_xml = mode.get("source_xml") or {}
    written = mode.get("simulation_comparison") or {}
    original = mode.get("source_simulation_comparison") or {}
    observables = original.get("observables") or {}
    return (
        source_xml.get("validator") == "libsbml"
        and source_xml.get("passed") is True
        and written.get("passed") is True
        and _independent_oracle_recorded(written)
        and original.get("passed") is True
        and _independent_oracle_recorded(original)
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

    loaded = {}
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
        loaded[mode_name] = (report, report_hash, records)

    raw_outcomes = {
        mode_name: {
            key: _case_verdict(records[key], bundled[key], mode_name)
            for key in sorted(records)
        }
        for mode_name, (_, _, records) in loaded.items()
    }
    # Only the recorder's ordinary unresolved refusals are eligible for a
    # REFUSAL disposition. A genuine failure, timeout or excluded package
    # cannot be laundered into one.
    unresolved_refusals = {
        mode_name: {
            key
            for key, verdict in raw_outcomes[mode_name].items()
            if verdict == "unresolved-refusal"
        }
        for mode_name in loaded
    }
    disposition_rows, disposition_receipt = disposition.build_disposition_receipt(
        loaded["flat"][0],
        loaded["flat"][2],
        loaded["atomized"][0],
        loaded["atomized"][2],
        unresolved_refusals,
    )

    modes = {}
    for mode_name in ("flat", "atomized"):
        report, report_hash, records = loaded[mode_name]
        bucket = disposition_receipt["modes"][mode_name]
        outcomes = dict(raw_outcomes[mode_name])
        for model_id in bucket["refusal_ids"]:
            outcomes[model_id] = "refusal:" + bucket["refusal_classes"][model_id]
        if disposition.MODEL_ID in outcomes:
            outcomes[disposition.MODEL_ID] = "numerical-limit-non-comparable"
        unresolved = [
            key
            for key, verdict in outcomes.items()
            if verdict not in BASE_DISPOSED
            and not verdict.startswith("decision-excluded-package:")
            and not verdict.startswith("refusal:")
            and verdict not in {"timeout", "numerical-limit-non-comparable"}
        ]
        modes[mode_name] = {
            "report_sha256": report_hash,
            "counts": dict(Counter(outcomes.values())),
            "unresolved": unresolved,
            "outcomes": outcomes,
            "timeout_ids": bucket["timeout_ids"],
            "refusal_counts": bucket["refusal_counts"],
        }
    passed = (
        all(
            m["counts"].get("compared") and not m["unresolved"]
            for m in modes.values()
        )
        and disposition_receipt["agreement"]["flat_atomized_match"]
        and disposition_receipt["agreement"]["report_receipt_match"]
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
        # Explicit non-PASS disposition rows, carried outside ``results`` so
        # the closure gate cannot mistake them for supported execution.
        "dispositions": disposition_rows,
        "disposition_receipt": disposition_receipt,
        "results": [
            {
                "id": check,
                "status": "PASS" if passed else "FAIL",
                "evidence_kind": "supported-execution",
                "supported_execution": passed,
                "related_issues": [162],
                "detail": (
                    "Flat and atomized comparison and disposition outcomes are "
                    f"retained per model; {len(disposition_rows)} explicit "
                    "disposition rows (numerical limit, timeout and valid-input "
                    "refusals) are non-passes and count as no supported execution."
                ),
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
