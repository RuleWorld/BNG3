#!/usr/bin/env python3
"""Derive a compact, machine-readable Atomizer coverage inventory.

The full SBML Test Suite and BioModels harness reports are large (tens of
megabytes) because they embed per-case trajectories and worker provenance.
This tool reduces one of those reports to a small, stable inventory that can
be committed alongside the source and diffed between runs:

  * stage counts (conversion, round-trip, independent comparison, official
    reference) with explicit denominators;
  * one row per case with its stage verdicts and, for unsupported cases, the
    normalised cause labels and a stable reason signature;
  * cause histograms and pairwise intersections, so a coverage campaign can
    cluster failures by root cause rather than by model.

The inventory never contains reference data or trajectories, and it never
changes a verdict.  It is a reporting aid only.

Usage:
    python scripts/ci/sbml_campaign_inventory.py \
        --suite-report /path/to/report.json \
        --biomodels-report /path/to/biomodels.json \
        --out provenance/sbml-campaign/inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Normalised reason signatures.  The harness emits long, model-specific
# reason strings; these prefixes group them into stable root-cause classes.
REASON_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("scheduled actions", "harness:scheduled-actions-not-executed"),
    ("repeated-run mean", "harness:stochastic-ensemble-not-evaluated"),
    ("does not define an official time-course reference", "reference:not-applicable"),
    ("trigger is not a simple time threshold", "events:state-trigger-not-schedulable"),
    ("SBML event(s) parsed", "events:untranslated"),
    ("is marked fast", "fast-reaction:no-fast-equilibrium-solve"),
    ("in math; BNGL has no built-in function", "mathml:no-bngl-builtin"),
    ("no MathML expression", "sbml:empty-math"),
    ("have no MathML kinetic law", "sbml:reaction-without-kinetic-law"),
    ("is not losslessly representable", "sbml-writer:unrepresentable-function"),
    ("no exact BNG3 result mapping", "reference:no-result-mapping"),
    ("unsupported stoichiometry", "stoichiometry:unsupported"),
    ("spatialDimensions", "compartment:unsupported-spatial-dimensions"),
    ("algebraic rule(s) present", "rules:algebraic-not-applied"),
    ("conversion factor", "conversion-factor:unsupported"),
    ("reaction-local", "scope:reaction-local"),
    ("distrib", "package:distrib"),
    ("infinity", "mathml:infinity"),
    ("notanumber", "mathml:not-a-number"),
    ("no species", "model:no-state-variables"),
    ("no reactants or products", "reaction:no-participants"),
    ("negative numeric rate", "rate:negative"),
)


def reason_signature(reason: str) -> str:
    """Map a harness reason string to a stable root-cause signature."""

    lowered = str(reason or "").lower()
    for needle, signature in REASON_SIGNATURES:
        if needle in lowered:
            return signature
    return "other"


def suite_inventory(report: dict[str, Any]) -> dict[str, Any]:
    """Reduce an SBML Test Suite harness report to a compact inventory."""

    records = report.get("records") or []
    rows: list[dict[str, Any]] = []
    stage_counts: dict[str, Counter] = {}
    cause_counts: Counter = Counter()
    cause_sets: Counter = Counter()
    official_counts: Counter = Counter()

    for record in records:
        ref = f"{record.get('category')}/{record.get('id')}"
        official = record.get("official_conformance") or {}
        official_status = str(official.get("status", "missing"))
        official_counts[official_status] += 1

        status = str(record.get("status", "unknown"))
        reason = str(record.get("unsupported_reason") or record.get("error") or "")
        signature = reason_signature(reason) if status != "passed" else ""
        if status != "passed" and not signature:
            signature = "other"

        causes = sorted(
            set(str(cause) for cause in (record.get("unsupported_causes") or []))
        )
        if status != "passed":
            for cause in causes:
                cause_counts[cause] += 1
            cause_sets[tuple(causes)] += 1

        row = {
            "ref": ref,
            "category": record.get("category"),
            "id": record.get("id"),
            "version": record.get("version"),
            "conversion": status,
            "official_reference": official_status,
            "reason_signature": signature,
            "causes": causes,
        }
        rows.append(row)

        conversion_bucket = stage_counts.setdefault("conversion", Counter())
        conversion_bucket[status] += 1

        roundtrip = record.get("roundtrip_passed")
        roundtrip_bucket = stage_counts.setdefault("roundtrip_structure", Counter())
        roundtrip_bucket["passed" if roundtrip is True else "not-tested"] += 1

        comparison = record.get("simulation_comparison") or {}
        independent_bucket = stage_counts.setdefault(
            "independent_comparison", Counter()
        )
        if comparison.get("passed") is True:
            independent_bucket["passed"] += 1
        elif comparison.get("skipped") or not comparison:
            independent_bucket["not-tested"] += 1
        else:
            independent_bucket["failed"] += 1

    intersections = [
        {"causes": list(pair), "count": count}
        for pair, count in cause_sets.most_common(40)
    ]
    return {
        "case_count": len(rows),
        "stage_counts": {
            stage: dict(sorted(bucket.items()))
            for stage, bucket in sorted(stage_counts.items())
        },
        "official_reference_counts": dict(sorted(official_counts.items())),
        "cause_counts": dict(cause_counts.most_common()),
        "cause_sets": intersections,
        "cases": rows,
    }


def _causes(reason: str) -> list[str]:
    """Reuse the harness cause taxonomy when it is importable."""

    try:
        from scripts.ci.validate_sbml_test_suite import _unsupported_causes
    except Exception:
        return []
    return list(_unsupported_causes(reason))


def biomodels_inventory(report: dict[str, Any]) -> dict[str, Any]:
    """Reduce a curated BioModels harness report to a compact inventory."""

    records = report.get("records") or []
    rows: list[dict[str, Any]] = []
    status_counts: Counter = Counter()
    cause_counts: Counter = Counter()
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] += 1
        causes = sorted(
            set(str(cause) for cause in (record.get("unsupported_causes") or []))
        )
        for cause in causes:
            cause_counts[cause] += 1
        rows.append(
            {
                "id": record.get("id"),
                "format": record.get("format"),
                "status": status,
                "causes": causes,
            }
        )
    return {
        "record_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "cause_counts": dict(cause_counts.most_common()),
        "cases": rows,
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-report", type=Path)
    parser.add_argument("--biomodels-report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()

    inventory: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": args.label,
    }
    if args.suite_report:
        report = json.loads(args.suite_report.read_text(encoding="utf-8"))
        inventory["sbml_test_suite"] = suite_inventory(report)
        inventory["sbml_test_suite"]["source_report_sha256"] = _digest(
            args.suite_report
        )
    if args.biomodels_report:
        report = json.loads(args.biomodels_report.read_text(encoding="utf-8"))
        inventory["biomodels"] = biomodels_inventory(report)
        inventory["biomodels"]["source_report_sha256"] = _digest(args.biomodels_report)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
