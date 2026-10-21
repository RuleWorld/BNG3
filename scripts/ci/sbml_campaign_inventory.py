#!/usr/bin/env python3
"""Derive a compact, machine-readable Atomizer coverage inventory.

The full SBML Test Suite and BioModels harness reports are large (tens of
megabytes) because they embed per-case trajectories and worker provenance.
This tool reduces one of those reports to a small, stable artifact that can be
committed alongside the source and diffed between runs:

  * stage counts (conversion, round-trip, independent comparison, official
    reference) with explicit denominators;
  * one row per case with its stage verdicts and, for unsupported cases, the
    normalised cause labels and a stable reason signature;
  * cause histograms and pairwise intersections, so a coverage campaign can
    cluster failures by root cause rather than by model;
  * an *expectation manifest*: the expected verdict of every official SBML
    Test Suite case at every stage of the gate.  The manifest turns a coverage
    regression into a failing comparison instead of a human reading two large
    reports side by side.

The inventory never contains reference data or trajectories, and it never
changes a verdict.  It is a reporting aid only.

Usage:
    python scripts/ci/sbml_campaign_inventory.py \
        --suite-report /path/to/report.json \
        --biomodels-report /path/to/biomodels.json \
        --out provenance/sbml-campaign/inventory.json

    # Regenerate the committed expectation manifest (an explicit, reviewable act).
    python scripts/ci/sbml_campaign_inventory.py \
        --suite-report /path/to/report.json \
        --expectations-out provenance/sbml-campaign/expectations.json

    # Compare a fresh run against the committed manifest.
    python scripts/ci/sbml_campaign_inventory.py \
        --suite-report /path/to/report.json \
        --expectations provenance/sbml-campaign/expectations.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
EXPECTATIONS_SCHEMA_VERSION = 1

# The four stages of the official SBML Test Suite gate, in report order.
EXPECTATION_STAGES: tuple[str, ...] = (
    "conversion",
    "roundtrip_structure",
    "independent_comparison",
    "official_reference",
)

# The closed verdict vocabulary of the expectation manifest.  ``not_tested``
# means the stage produced no verdict (never executed, no reference defined,
# or the source was invalid).  A timeout is a stage that was attempted and
# did not succeed, so it maps to ``failed``.
EXPECTATION_STATUSES: tuple[str, ...] = (
    "passed",
    "unsupported",
    "failed",
    "not_tested",
)

# How a harness status becomes a manifest verdict.  A timeout is a stage that
# was attempted and did not succeed, so it is a failure; a stage that produced
# no verdict at all is not tested.
CONVERSION_STATUS_MAP: dict[str, str] = {
    "passed": "passed",
    "unsupported": "unsupported",
    "failed": "failed",
    "timeout": "failed",
    "timed-out": "failed",
}
OFFICIAL_STATUS_MAP: dict[str, str] = {
    "passed": "passed",
    "unsupported": "unsupported",
    "failed": "failed",
    "timed-out": "failed",
}

# Normalised reason signatures.  The harness emits long, model-specific
# reason strings; these prefixes group them into stable root-cause classes.
# The curated-BioModels needles are checked first because their wording is
# distinctive; the generic needles below are shared with the official suite.
REASON_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("flux-balance constraints/objectives", "constraints:flux-balance-not-kinetic"),
    ('"fbc" package', "package:fbc"),
    ("not an sbml biomodels artifact", "format:not-an-sbml-artifact"),
    ("contains no usable sbml", "format:no-usable-sbml"),
    ("not libsbml-valid", "source:libsbml-invalid"),
    ("qual package is present", "package:qual-not-quantitative"),
    ("bngl syntax errors", "writer:bngl-syntax-error"),
    (
        "cannot generate a network from an invalid compiled",
        "compile:invalid-compiled-model",
    ),
    ("observable mismatch", "simulation:observable-mismatch"),
    ("compartment derivative", "rules:species-rate-rule-needs-compartment"),
    (
        "generated bngl contains scheduled actions",
        "harness:scheduled-actions-not-executed",
    ),
    ("repeated-run mean", "harness:stochastic-ensemble-not-evaluated"),
    ("does not define an official time-course reference", "reference:not-applicable"),
    ("trigger is not a simple time threshold", "events:state-trigger-not-schedulable"),
    ("sbml event(s) parsed", "events:untranslated"),
    ("is marked fast", "fast-reaction:no-fast-equilibrium-solve"),
    ("in math; bngl has no built-in function", "mathml:no-bngl-builtin"),
    ("no mathml expression", "sbml:empty-math"),
    ("have no mathml kinetic law", "sbml:reaction-without-kinetic-law"),
    ("is not losslessly representable", "sbml-writer:unrepresentable-function"),
    ("no exact bng3 result mapping", "reference:no-result-mapping"),
    ("unsupported stoichiometry", "stoichiometry:unsupported"),
    (
        "could not be resolved to a number",
        "stoichiometry:assigned-stoichiometry-unresolved",
    ),
    ("spatialdimensions", "compartment:unsupported-spatial-dimensions"),
    ("algebraic rule(s) present", "rules:algebraic-not-applied"),
    ("conversion factor", "conversion-factor:unsupported"),
    ("reaction-local", "scope:reaction-local"),
    ("distrib", "package:distrib"),
    ("infinity", "mathml:infinity"),
    ("notanumber", "mathml:not-a-number"),
    ("no species", "model:no-state-variables"),
    ("no reactants or products", "reaction:no-participants"),
    ("negative numeric rate", "rate:negative"),
    # A solver failure is only a solver failure when the solver said so.  The
    # official suite's own harness reasons also mention CVODE, so the needle
    # names the failure rather than the engine.
    ("cvode error", "simulation:solver-failure"),
    ("cvode failed", "simulation:solver-failure"),
)


def reason_signature(reason: str) -> str:
    """Map a harness reason string to a stable root-cause signature."""

    lowered = str(reason or "").lower()
    for needle, signature in REASON_SIGNATURES:
        if needle in lowered:
            return signature
    return "other"


def _harness_causes(module_name: str, reason: str) -> list[str]:
    """Reuse a harness cause taxonomy when it is importable.

    The harness owns the taxonomy; the inventory only reads it.  A missing or
    unimportable harness yields no labels rather than an invented one.
    """

    try:
        module = importlib.import_module(module_name)
    except Exception:
        return []
    taxonomy = getattr(module, "_unsupported_causes", None)
    if taxonomy is None:
        return []
    try:
        return [str(cause) for cause in taxonomy(reason)]
    except Exception:
        return []


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
        if not causes and status == "unsupported":
            # The harness normally records the taxonomy labels itself.  When a
            # report omits them, derive the same labels from the reason.
            causes = sorted(
                set(_harness_causes("scripts.ci.validate_sbml_test_suite", reason))
            )
        if status != "passed":
            for cause in causes:
                cause_counts[cause] += 1
            cause_sets[tuple(causes)] += 1

        roundtrip = record.get("roundtrip_passed")
        roundtrip_status = "passed" if roundtrip is True else "not-tested"

        comparison = record.get("simulation_comparison") or {}
        if comparison.get("passed") is True:
            independent_status = "passed"
        elif comparison.get("skipped") or not comparison:
            independent_status = "not-tested"
        else:
            independent_status = "failed"

        row = {
            "ref": ref,
            "category": record.get("category"),
            "id": record.get("id"),
            "version": record.get("version"),
            "conversion": status,
            "roundtrip_structure": roundtrip_status,
            "independent_comparison": independent_status,
            "official_reference": official_status,
            "reason_signature": signature,
            "causes": causes,
        }
        rows.append(row)

        conversion_bucket = stage_counts.setdefault("conversion", Counter())
        conversion_bucket[status] += 1

        roundtrip_bucket = stage_counts.setdefault("roundtrip_structure", Counter())
        roundtrip_bucket[roundtrip_status] += 1

        independent_bucket = stage_counts.setdefault(
            "independent_comparison", Counter()
        )
        independent_bucket[independent_status] += 1

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


def _biomodels_reason(record: dict[str, Any]) -> str:
    """Return the reason that explains a curated BioModels record's verdict.

    The harness records the reason at record level for unsupported records and
    at mode level for every other verdict; both shapes are read so the cause
    histogram does not depend on which one a report happens to carry.
    """

    reason = str(record.get("unsupported_reason") or "").strip()
    if reason:
        return reason
    for mode in record.get("modes") or []:
        candidate = str(mode.get("unsupported_reason") or "").strip()
        if candidate:
            return candidate
        error = str(mode.get("error") or "").strip()
        if error:
            return error
    return str(record.get("error") or "").strip()


def _biomodels_causes(record: dict[str, Any], reason: str) -> list[str]:
    """Return the cause labels of a curated BioModels record."""

    recorded = sorted(
        set(str(cause) for cause in (record.get("unsupported_causes") or []))
    )
    if recorded:
        return recorded
    status = str(record.get("status", ""))
    if status == "unsupported_format":
        return ["format"]
    if status != "unsupported":
        return []
    return sorted(
        set(_harness_causes("scripts.ci.validate_published_biomodels", reason))
    )


def biomodels_inventory(report: dict[str, Any]) -> dict[str, Any]:
    """Reduce a curated BioModels harness report to a compact inventory.

    The retained inventory keeps the five result categories separate - pass,
    unsupported, failed, timed out and invalid source - so a retained result
    says which of them it is, and it keeps the corpus the results came from:
    the pinned corpus manifest, its digest and the counts it declares.
    """

    records = report.get("records") or []
    rows: list[dict[str, Any]] = []
    status_counts: Counter = Counter()
    cause_counts: Counter = Counter()
    cause_sets: Counter = Counter()
    category_counts: Counter = Counter()
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] += 1
        category = _biomodels_category(status)
        category_counts[category] += 1
        reason = _biomodels_reason(record)
        causes = sorted(
            set(str(cause) for cause in (record.get("unsupported_causes") or []))
        )
        for cause in causes:
            cause_counts[cause] += 1
        cause_sets[tuple(causes)] += 1
        rows.append(
            {
                "id": record.get("id"),
                "format": record.get("format"),
                "status": status,
                "reason_signature": (
                    reason_signature(reason) if status != "passed" else ""
                ),
                "category": category,
                "causes": causes,
                "source_sha256": (record.get("source_artifact") or {}).get("sha256"),
            }
        )
    intersections = [
        {"causes": list(pair), "count": count}
        for pair, count in cause_sets.most_common(40)
    ]
    corpus = report.get("corpus") or {}
    return {
        "record_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "category_counts": {
            category: category_counts.get(category, 0)
            for category in (
                "passed",
                "unsupported",
                "failed",
                "timeout",
                "invalid_source",
            )
        },
        "cause_counts": dict(cause_counts.most_common()),
        "cause_sets": intersections,
        "corpus": {
            "manifest": corpus.get("manifest"),
            "manifest_sha256": corpus.get("manifest_sha256"),
            "snapshot_date": corpus.get("snapshot_date"),
            "curation_query": corpus.get("curation_query"),
            "expected_records": corpus.get("expected_records"),
            "expected_sbml_records": corpus.get("expected_sbml_records"),
            "expected_non_sbml_records": corpus.get("expected_non_sbml_records"),
        },
        "cases": rows,
    }


def _conversion_status(record: dict[str, Any]) -> str:
    status = str(record.get("status", "unknown"))
    return CONVERSION_STATUS_MAP.get(status, "not_tested")


def _roundtrip_status(record: dict[str, Any]) -> str:
    value = record.get("roundtrip_passed")
    if value is True:
        return "passed"
    if value is False:
        return "failed"
    return "not_tested"


def _independent_status(record: dict[str, Any]) -> str:
    comparison = record.get("simulation_comparison") or {}
    if comparison.get("passed") is True:
        return "passed"
    if comparison.get("skipped") or not comparison:
        return "not_tested"
    return "failed"


def _official_status(record: dict[str, Any]) -> str:
    official = record.get("official_conformance") or {}
    status = str(official.get("status", "missing"))
    return OFFICIAL_STATUS_MAP.get(status, "not_tested")


def _stage_gap(record: dict[str, Any], stage: str) -> dict[str, Any] | None:
    """Name the construct that keeps a stage from producing a verdict.

    ``passed`` is a result.  ``failed`` is a result too: the stage ran and
    disagreed with the reference, which is a finding to investigate.
    ``unsupported`` is the only gap: the case was refused because a
    construct is not representable today, and the manifest has to say which
    construct rather than record a bare refusal.
    """

    if stage == "conversion":
        status = str(record.get("status", ""))
        if status != "unsupported":
            return None
        reason = str(record.get("unsupported_reason") or record.get("error") or "")
        causes = sorted(
            set(str(cause) for cause in (record.get("unsupported_causes") or []))
        )
        if not causes:
            causes = sorted(
                set(_harness_causes("scripts.ci.validate_sbml_test_suite", reason))
            )
        return {"construct": reason_signature(reason), "causes": causes}

    if stage == "official_reference":
        official = record.get("official_conformance") or {}
        if str(official.get("status")) != "unsupported":
            return None
        reason = str(official.get("reason") or "")
        causes = sorted(
            set(_harness_causes("scripts.ci.validate_sbml_test_suite", reason))
        )
        return {"construct": reason_signature(reason), "causes": causes}

    return None


def expectation_cases(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return the observed verdict of every case at every gate stage."""

    cases: dict[str, dict[str, str]] = {}
    for record in report.get("records") or []:
        identity = f"{record.get('category')}/{record.get('id')}"
        cases[identity] = {
            "conversion": _conversion_status(record),
            "roundtrip_structure": _roundtrip_status(record),
            "independent_comparison": _independent_status(record),
            "official_reference": _official_status(record),
        }
    return cases


def expectation_gaps(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the construct that keeps each non-passing stage from passing."""

    gaps: dict[str, dict[str, Any]] = {}
    for record in report.get("records") or []:
        identity = f"{record.get('category')}/{record.get('id')}"
        entry: dict[str, Any] = {}
        for stage in ("conversion", "official_reference"):
            gap = _stage_gap(record, stage)
            if gap is not None:
                entry[stage] = gap
        if entry:
            gaps[identity] = entry
    return gaps


def expectations_from_report(
    report: dict[str, Any],
    *,
    source_report_sha256: str,
    measurement_date: str | None = None,
) -> dict[str, Any]:
    """Build an expectation manifest from one SBML Test Suite report."""

    cases = expectation_cases(report)
    gaps = expectation_gaps(report)
    source_lock = report.get("suite_source_lock") or {}
    source_provenance = report.get("source_provenance") or {}
    runtime = report.get("runtime_provenance") or {}
    manifest: dict[str, Any] = {
        "schema_version": EXPECTATIONS_SCHEMA_VERSION,
        "kind": "sbml-test-suite-expectations",
        "generator": "scripts/ci/sbml_campaign_inventory.py",
        "note": (
            "Each entry records the verdict the tree named by "
            "source_report.bng3_commit produced for that case. 'passed' is a "
            "result. 'failed' is a result too: the stage ran and disagreed "
            "with the reference, which is a finding to investigate. "
            "'unsupported' is the only gap: the case's 'gap' entry names the "
            "construct that is not representable today together with the "
            "harness's cause labels for it. No entry claims that a currently "
            "unsupported construct should become supported, and an "
            "'unsupported' entry is never counted as support."
        ),
        "stages": list(EXPECTATION_STAGES),
        "statuses": list(EXPECTATION_STATUSES),
        "status_mapping": {
            "conversion": "record status; timeout maps to failed",
            "roundtrip_structure": "roundtrip_passed; absent maps to not_tested",
            "independent_comparison": (
                "simulation_comparison.passed; skipped or absent maps to not_tested"
            ),
            "official_reference": (
                "official_conformance.status; timed-out maps to failed, "
                "invalid-source/pending/missing map to not_tested"
            ),
        },
        "suite": {
            "repository": str(
                source_lock.get("repository")
                or "https://github.com/sbmlteam/sbml-test-suite.git"
            ),
            "revision": str(report.get("suite_commit") or ""),
            "categories": list(report.get("categories") or []),
            "case_count": len(cases),
        },
        "source_report": {
            "sha256": source_report_sha256,
            "bng3_commit": str(source_provenance.get("bng3_commit") or ""),
            "python_version": str(runtime.get("python_version") or ""),
        },
        "cases": {
            identity: {
                **cases[identity],
                **({"gap": gaps[identity]} if identity in gaps else {}),
            }
            for identity in sorted(cases)
        },
    }
    if measurement_date:
        manifest["source_report"]["measurement_date"] = measurement_date
    return manifest


def classify_difference(expected: str, observed: str) -> str:
    """Classify one expected/observed verdict difference."""

    if expected == "passed" and observed != "passed":
        return "regression"
    if expected != "passed" and observed == "passed":
        return "improvement"
    return "change"


def compare_expectations(
    manifest: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Compare an observed run against a committed expectation manifest.

    Every difference is reported.  A case that was ``passed`` and no longer
    is is a regression; a case that moves from ``failed`` to ``passed`` is an
    improvement that is only accepted once the manifest is explicitly
    updated.
    """

    expected_cases = manifest.get("cases") or {}
    observed = expectation_cases(report)
    differences: list[dict[str, Any]] = []
    not_executed: list[str] = []
    partial = bool(report.get("partial_run"))

    for identity in sorted(set(expected_cases) | set(observed)):
        expected = expected_cases.get(identity)
        actual = observed.get(identity)
        if expected is None:
            differences.append(
                {
                    "case": identity,
                    "stage": "*",
                    "expected": None,
                    "observed": actual,
                    "classification": "unrecorded-case",
                }
            )
            continue
        if actual is None:
            if partial:
                not_executed.append(identity)
                continue
            differences.append(
                {
                    "case": identity,
                    "stage": "*",
                    "expected": expected,
                    "observed": None,
                    "classification": "missing-case",
                }
            )
            continue
        for stage in EXPECTATION_STAGES:
            expected_status = str(expected.get(stage, "not_tested"))
            observed_status = str(actual.get(stage, "not_tested"))
            if expected_status == observed_status:
                continue
            differences.append(
                {
                    "case": identity,
                    "stage": stage,
                    "expected": expected_status,
                    "observed": observed_status,
                    "classification": classify_difference(
                        expected_status, observed_status
                    ),
                }
            )

    manifest_revision = str((manifest.get("suite") or {}).get("revision") or "")
    report_revision = str(report.get("suite_commit") or "")
    return {
        "cases_compared": len(observed),
        "cases_expected": len(expected_cases),
        "cases_not_executed": len(not_executed),
        "suite_revision_expected": manifest_revision,
        "suite_revision_observed": report_revision,
        "suite_revision_mismatch": bool(
            manifest_revision
            and report_revision
            and manifest_revision != report_revision
        ),
        "differences": differences,
    }


def format_difference(diff: dict[str, Any]) -> str:
    """Render one difference as a reviewable line."""

    return (
        f"{diff['case']} [{diff['stage']}]: expected {diff['expected']}, "
        f"observed {diff['observed']} ({diff['classification']})"
    )


def _biomodels_category(status: str) -> str:
    """Map a BioModels record status onto one of the five result categories."""
    value = str(status or "").strip().lower()
    if value in {"passed", "pass"}:
        return "passed"
    if value in {"unsupported", "unsupported_format"}:
        return "unsupported"
    if value in {"timeout", "timed-out", "timed_out"}:
        return "timeout"
    if value in {"invalid_source", "invalid-source"}:
        return "invalid_source"
    if value in {"failed", "fail", "error"}:
        return "failed"
    return "failed"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_expectations(path: Path, manifest: dict[str, Any]) -> None:
    """Write an expectation manifest with one compact line per case.

    The manifest holds one entry per case per stage.  Writing each case on a
    single line keeps the file reviewable and makes a refresh diff show the
    cases whose verdict actually changed.
    """

    cases = manifest.get("cases") or {}
    header = {key: value for key, value in manifest.items() if key != "cases"}
    body = json.dumps(header, indent=2, sort_keys=True)
    if not body.endswith("}"):
        raise ValueError("expectation manifest header is not a JSON object")
    body = body[:-1].rstrip()
    if not body.endswith("{"):
        body += ","
    lines = []
    for identity in sorted(cases):
        entry = cases[identity]
        parts = [f'"{stage}": "{entry[stage]}"' for stage in EXPECTATION_STAGES]
        gap = entry.get("gap")
        if gap:
            parts.append('"gap": ' + json.dumps(gap, sort_keys=True))
        lines.append(f'    "{identity}": {{' + ", ".join(parts) + "}")
    body += '\n  "cases": {\n' + ",\n".join(lines) + "\n  }\n}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-report", type=Path)
    parser.add_argument("--biomodels-report", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--label", default="baseline")
    parser.add_argument(
        "--provenance",
        type=Path,
        help="JSON document merged into the inventory under 'provenance'",
    )
    parser.add_argument(
        "--expectations-out",
        type=Path,
        help="write the expectation manifest for --suite-report",
    )
    parser.add_argument(
        "--expectations",
        type=Path,
        help="compare --suite-report against a committed expectation manifest",
    )
    parser.add_argument(
        "--measurement-date",
        help="measurement date recorded in a generated expectation manifest",
    )
    args = parser.parse_args()

    if args.out is None and args.expectations_out is None and args.expectations is None:
        parser.error("one of --out, --expectations-out or --expectations is required")

    if args.suite_report is None and (args.expectations_out or args.expectations):
        parser.error("--suite-report is required for the expectation manifest")

    if args.expectations_out is not None:
        report = _load_json(args.suite_report)
        manifest = expectations_from_report(
            report,
            source_report_sha256=_digest(args.suite_report),
            measurement_date=args.measurement_date,
        )
        _write_expectations(args.expectations_out, manifest)
        print(
            f"wrote {args.expectations_out} "
            f"({manifest['suite']['case_count']} cases)"
        )
        return 0

    if args.expectations is not None:
        report = _load_json(args.suite_report)
        manifest = _load_json(args.expectations)
        comparison = compare_expectations(manifest, report)
        if comparison["suite_revision_mismatch"]:
            print(
                "suite revision mismatch: manifest expects "
                f"{comparison['suite_revision_expected']}, run used "
                f"{comparison['suite_revision_observed']}",
                file=sys.stderr,
            )
            return 2
        differences = comparison["differences"]
        if differences:
            print(
                f"{len(differences)} expectation difference(s) against "
                f"{args.expectations}:",
                file=sys.stderr,
            )
            for diff in differences:
                print(f"  {format_difference(diff)}", file=sys.stderr)
            print(
                "Update the manifest only when the change is intended and " "reviewed.",
                file=sys.stderr,
            )
            return 1
        print(
            f"{comparison['cases_compared']} case(s) match {args.expectations} "
            f"({comparison['cases_not_executed']} not executed by this run)"
        )
        return 0

    inventory: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": args.label,
    }
    if args.provenance is not None:
        inventory["provenance"] = _load_json(args.provenance)
    if args.suite_report:
        report = _load_json(args.suite_report)
        inventory["sbml_test_suite"] = suite_inventory(report)
        inventory["sbml_test_suite"]["source_report_sha256"] = _digest(
            args.suite_report
        )
    if args.biomodels_report:
        report = _load_json(args.biomodels_report)
        inventory["biomodels"] = biomodels_inventory(report)
        inventory["biomodels"]["source_report_sha256"] = _digest(args.biomodels_report)

    _write_json(args.out, inventory)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
