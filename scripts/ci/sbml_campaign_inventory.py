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

    # Record an auditable measurement: where it came from, and why every
    # verdict moved relative to a baseline.
    python scripts/ci/sbml_campaign_inventory.py \
        --suite-report /path/to/suite.json \
        --baseline-suite-report /path/to/baseline-suite.json \
        --biomodels-report /path/to/biomodels-flat.json \
        --biomodels-atomized-report /path/to/biomodels-atomized.json \
        --base-commit 219c76dac38655c0f15a12ee294e4a4ac10d02ef \
        --measurement-date 2026-10-20 \
        --out provenance/sbml-campaign/audit-2026-10-20.json

Schema
------
The inventory has ``schema_version``, ``label`` and, when the corresponding
report is supplied, ``sbml_test_suite`` and ``biomodels``.  Each corpus
section carries the corpus denominator (``case_count`` / ``record_count``),
the per-status counts, the cause histogram and one row per case with that
case's verdicts.

``provenance`` records where a measurement came from.  It is either the
document supplied with ``--provenance`` (merged verbatim) or, for an audit
record, a block *derived* from the reports in the same shape:
``base_commit``, ``measurement_date``, ``measurement_host``, ``note`` and
``sbml_test_suite`` with ``case_timeout_seconds``, ``categories``,
``repository`` and ``revision``.

``audit`` is the audit record's own section.  It adds the digests of the
source reports, the commit the run executed, the tool versions the harness
observed, the per-case comparison with a baseline (stating, for every case
that moved, whether a reference file, a tolerance, the result mapping, the
number of compared points or a diagnostic changed), both curated-BioModels
modes with the records one mode supports and the other does not, and any
additional evidence document supplied with ``--extra-evidence``.

Neither section contains reference data or trajectories, and neither changes a
verdict.
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

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
    (
        "official output grid contains the boundary of the generated scheduled actions",
        "harness:scheduled-action-phase-boundary",
    ),
    ("<infinity> constant encountered in math", "mathml:infinity"),
    ("<notanumber> constant encountered in math", "mathml:not-a-number"),
    ("has an infinite value; emitted", "mathml:non-finite-parameter-approximation"),
    ("has nan value; emitted", "mathml:non-finite-parameter-approximation"),
    ("repeated-run mean", "harness:stochastic-ensemble-not-evaluated"),
    (
        "executed in a random order",
        "harness:random-event-execution",
    ),
    (
        "does not track the boundary species",
        "harness:reference-does-not-track-variable",
    ),
    ("does not define an official time-course reference", "reference:not-applicable"),
    ("trigger is not a simple time threshold", "events:state-trigger-not-schedulable"),
    (
        "simultaneous same-priority event group",
        "events:unorderable-simultaneous-execution",
    ),
    (
        "simultaneous event without a priority",
        "events:unorderable-simultaneous-execution",
    ),
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
    """Reduce a curated BioModels harness report to a compact inventory."""

    records = report.get("records") or []
    rows: list[dict[str, Any]] = []
    status_counts: Counter = Counter()
    cause_counts: Counter = Counter()
    cause_sets: Counter = Counter()
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] += 1
        reason = _biomodels_reason(record)
        causes = _biomodels_causes(record, reason)
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
                "causes": causes,
            }
        )
    intersections = [
        {"causes": list(pair), "count": count}
        for pair, count in cause_sets.most_common(40)
    ]
    return {
        "record_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "cause_counts": dict(cause_counts.most_common()),
        "cause_sets": intersections,
        "cases": rows,
    }


# --- Audit record -------------------------------------------------------
#
# Everything below supports one job: state where a measurement came from and
# why every verdict moved relative to a baseline.  It never changes a verdict,
# a tolerance or a reference file.


AUDIT_SCHEMA_VERSION = 1


def _tool_versions(report: dict[str, Any]) -> dict[str, Any]:
    """Read the tool versions the harness recorded for the run."""

    runtime = report.get("runtime_provenance") or {}
    versions = {
        key: runtime.get(key)
        for key in (
            "python_version",
            "platform",
            "bionetgen_version",
            "numpy_version",
            "libsbml_version",
            "roadrunner_version",
        )
        if runtime.get(key)
    }
    versions["native_extension_sha256"] = runtime.get("native_extension_sha256")
    versions["python_package_source_sha256"] = runtime.get(
        "python_package_source_sha256"
    )
    return versions


def _measurement_host(report: dict[str, Any]) -> str:
    """Describe the machine and the tool versions a run executed on."""

    versions = _tool_versions(report)
    platform = str(versions.get("platform") or "")
    python_version = str(versions.get("python_version") or "")
    libsbml_version = str(versions.get("libsbml_version") or "")
    roadrunner_version = str(versions.get("roadrunner_version") or "")
    return (
        f"{platform}, CPython {python_version}, libsbml {libsbml_version}, "
        f"roadrunner {roadrunner_version}"
    )


def _case_fingerprint(record: dict[str, Any]) -> dict[str, Any]:
    """Reduce one harness record to the facts a verdict change can rest on."""

    official = record.get("official_conformance") or {}
    comparison = official.get("comparison") or {}
    digests = record.get("input_sha256") or {}
    model = record.get("source_model") or {}
    dropped = sorted(
        f"[{warning.get('category')}/{warning.get('severity')}] {warning.get('message')}"
        for warning in (model.get("warnings") or [])
        if str(warning.get("severity")) in {"dropped", "approximated"}
        and str(warning.get("category")) != "units"
    )
    return {
        "conversion": record.get("status"),
        "unsupported_reason": record.get("unsupported_reason") or "",
        "official_reference": official.get("status", "missing"),
        "official_reason": official.get("reason") or "",
        "sbml_sha256": digests.get("sbml"),
        "settings_sha256": digests.get("settings"),
        "results_sha256": digests.get("results"),
        "reference_settings_sha256": official.get("settings_sha256"),
        "reference_results_sha256": official.get("results_sha256"),
        "tolerance_absolute": comparison.get("absolute"),
        "tolerance_relative": comparison.get("relative"),
        "tolerance_formula": comparison.get("tolerance_formula"),
        "sample_count": comparison.get("sample_count"),
        "passed_points": comparison.get("passed_points"),
        "output_targets": official.get("output_targets"),
        "dropped_or_approximated_warnings": dropped,
    }


def suite_baseline_comparison(
    baseline_report: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Compare a measurement with a baseline and say why each verdict moved.

    A verdict that moves because the reference file, the tolerance, the result
    mapping or the compared sample count changed is a changed *measurement*.
    A verdict that moves because a ``dropped``/``approximated`` diagnostic
    disappeared is a removed *refusal*.  Both are reported per case, so that a
    reviewer can decide which of them the change actually was.
    """

    baseline = {
        f"{record.get('category')}/{record.get('id')}": record
        for record in baseline_report.get("records") or []
    }
    rows: list[dict[str, Any]] = []
    transitions: Counter = Counter()
    for record in report.get("records") or []:
        key = f"{record.get('category')}/{record.get('id')}"
        before_record = baseline.get(key)
        if before_record is None:
            continue
        before = _case_fingerprint(before_record)
        after = _case_fingerprint(record)
        if (
            before["conversion"] == after["conversion"]
            and before["official_reference"] == after["official_reference"]
        ):
            continue
        mechanisms: list[str] = []

        def changed(field: str, label: str) -> None:
            old = before[field]
            new = after[field]
            if old is not None and new is not None and old != new:
                mechanisms.append(label)

        changed("sbml_sha256", "source-sbml-changed")
        changed("settings_sha256", "settings-file-changed")
        changed("results_sha256", "results-file-changed")
        changed("reference_settings_sha256", "official-settings-digest-changed")
        changed("reference_results_sha256", "official-results-digest-changed")
        changed("tolerance_absolute", "absolute-tolerance-changed")
        changed("tolerance_relative", "relative-tolerance-changed")
        changed("tolerance_formula", "tolerance-formula-changed")
        changed("sample_count", "compared-sample-count-changed")
        changed("output_targets", "official-result-mapping-changed")
        removed = sorted(
            set(before["dropped_or_approximated_warnings"])
            - set(after["dropped_or_approximated_warnings"])
        )
        added = sorted(
            set(after["dropped_or_approximated_warnings"])
            - set(before["dropped_or_approximated_warnings"])
        )
        if removed:
            mechanisms.append("dropped-or-approximated-warning-removed")
        if added:
            mechanisms.append("dropped-or-approximated-warning-added")
        transition = f"{before['official_reference']}->{after['official_reference']}"
        transitions[transition] += 1
        rows.append(
            {
                "ref": key,
                "conversion": f"{before['conversion']}->{after['conversion']}",
                "official_reference": transition,
                "mechanisms": mechanisms,
                "removed_warnings": removed,
                "added_warnings": added,
            }
        )
    return {
        "baseline_case_count": len(baseline),
        "transition_counts": dict(sorted(transitions.items())),
        "cases": rows,
    }


def biomodels_baseline_comparison(
    baseline_report: dict[str, Any],
    report: dict[str, Any],
    recheck: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare a curated-corpus measurement with a baseline, record by record.

    The aggregate counts of a corpus can stay the same while individual
    records change class, so the aggregate alone is not a claim about the
    corpus.  This states, per record, what changed.
    """

    baseline = {
        str(record.get("id")): record for record in baseline_report.get("records") or []
    }
    observed = {str(record.get("id")): record for record in report.get("records") or []}
    verdicts = (recheck or {}).get("verdicts") or {}
    rows: list[dict[str, Any]] = []
    for record_id in sorted(set(baseline) & set(observed)):
        before = str(baseline[record_id].get("status"))
        after = verdicts.get(record_id) or str(observed[record_id].get("status"))
        if before == after:
            continue
        rows.append(
            {
                "id": record_id,
                "baseline_status": before,
                "measured_status": after,
                "parallel_status": str(observed[record_id].get("status")),
                "error": str(
                    ((observed[record_id].get("modes") or [{}])[0]).get("error") or ""
                )[:300],
            }
        )
    counts: Counter = Counter()
    for record_id in observed:
        counts[verdicts.get(record_id) or str(observed[record_id].get("status"))] += 1
    return {
        "record_count": len(observed),
        "status_counts": dict(sorted(counts.items())),
        "changed_record_count": len(rows),
        "changed_records": rows,
    }


def _apply_recheck(
    modes: dict[str, Any], recheck: dict[str, Any] | None, mode: str
) -> None:
    """Replace a mode's parallel verdicts with its serial re-measurement.

    A corpus run that shares a busy machine reports a timeout for a model
    that only ran long because the machine was busy.  Re-measuring the records
    whose verdict differs from the baseline, one worker at a time, decides
    those records without depending on the load.
    """

    if not recheck:
        return
    verdicts = recheck.get("verdicts") or {}
    section = modes.get(mode)
    if not section:
        return
    corrected: dict[str, str] = {}
    for row in section["records"]:
        serial = verdicts.get(str(row["id"]))
        if serial is None:
            continue
        row["parallel_status"] = row["status"]
        row["status"] = serial
        corrected[str(row["id"])] = serial
    section["recheck"] = {
        "rechecked_records": sorted(corrected),
        "changed_records": sorted(
            record_id
            for record_id, status in corrected.items()
            if next(
                row["parallel_status"]
                for row in section["records"]
                if str(row["id"]) == record_id
            )
            != status
        ),
    }
    section["status_counts_after_recheck"] = dict(
        sorted(Counter(row["status"] for row in section["records"]).items())
    )


def _mode_comparison(modes: dict[str, Any]) -> None:
    """State which records one BioModels mode supports and the other does not."""

    flat = modes.get("flat")
    atomized = modes.get("atomized")
    if not flat or not atomized:
        return
    flat_status = {str(row["id"]): row["status"] for row in flat["records"]}
    atomized_status = {str(row["id"]): row["status"] for row in atomized["records"]}
    shared = sorted(set(flat_status) & set(atomized_status))
    flat_only = sorted(
        record_id
        for record_id in shared
        if flat_status[record_id] == "passed" and atomized_status[record_id] != "passed"
    )
    modes["flat_only_passed"] = flat_only
    modes["flat_only_passed_statuses"] = dict(
        sorted(Counter(atomized_status[record_id] for record_id in flat_only).items())
    )
    modes["atomized_only_passed"] = sorted(
        record_id
        for record_id in shared
        if atomized_status[record_id] == "passed" and flat_status[record_id] != "passed"
    )


def _biomodels_mode_section(
    report: dict[str, Any], report_path: Path | None, mode: str
) -> dict[str, Any]:
    """Summarise one curated-BioModels mode and list every record's verdict."""

    records = report.get("records") or []
    rows = []
    for record in records:
        rows.append(
            {
                "id": record.get("id"),
                "status": record.get("status"),
                "format": record.get("format"),
                "causes": sorted(
                    set(
                        str(cause) for cause in (record.get("unsupported_causes") or [])
                    )
                ),
            }
        )
    statuses = Counter(str(row["status"]) for row in rows)
    return {
        "mode": mode,
        "record_count": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "summary": report.get("summary"),
        "completeness": report.get("completeness"),
        "source_report_sha256": _digest(report_path) if report_path else None,
        "records": sorted(rows, key=lambda row: str(row["id"])),
    }


def audit_section(
    suite_report: dict[str, Any] | None,
    suite_report_path: Path | None,
    baseline_suite_report: dict[str, Any] | None,
    baseline_suite_report_path: Path | None,
    biomodels_report: dict[str, Any] | None,
    biomodels_report_path: Path | None,
    biomodels_atomized_report: dict[str, Any] | None,
    biomodels_atomized_report_path: Path | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Collect the corpus denominators, digests, commits and tool versions."""

    audit: dict[str, Any] = {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "base_commit": args.base_commit,
    }

    if suite_report is not None:
        source = suite_report.get("source_provenance") or {}
        lock = suite_report.get("suite_source_lock") or {}
        command = suite_report.get("command") or {}
        arguments = command.get("arguments") or []
        case_timeout = 0
        for index, argument in enumerate(arguments):
            if argument == "--case-timeout" and index + 1 < len(arguments):
                try:
                    case_timeout = int(arguments[index + 1])
                except ValueError:
                    case_timeout = 0
        audit["head_commit"] = source.get("bng3_commit")
        audit["measurement_host"] = _measurement_host(suite_report)
        audit["sbml_test_suite"] = {
            "case_count": len(suite_report.get("records") or []),
            "case_timeout_seconds": case_timeout,
            "categories": suite_report.get("categories"),
            "repository": lock.get("repository"),
            "revision": suite_report.get("suite_commit") or lock.get("revision"),
            "command": command,
            "source_report_sha256": (
                _digest(suite_report_path) if suite_report_path else None
            ),
            "tool_versions": _tool_versions(suite_report),
        }
        if baseline_suite_report is not None:
            audit["sbml_test_suite"]["baseline_comparison"] = suite_baseline_comparison(
                baseline_suite_report, suite_report
            )
            audit["sbml_test_suite"]["baseline_source_report_sha256"] = (
                _digest(baseline_suite_report_path)
                if baseline_suite_report_path
                else None
            )

    if biomodels_report is not None:
        inventory = biomodels_report.get("inventory") or {}
        modes: dict[str, Any] = {
            "inventory": {
                "source": inventory.get("source"),
                "query": inventory.get("query"),
                "matches": inventory.get("matches"),
            },
            "flat": _biomodels_mode_section(
                biomodels_report, biomodels_report_path, "flat"
            ),
        }
        if biomodels_atomized_report is not None:
            modes["atomized"] = _biomodels_mode_section(
                biomodels_atomized_report,
                biomodels_atomized_report_path,
                "atomized",
            )
        audit["biomodels"] = modes

    return audit


def derived_provenance(
    suite_report: dict[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Build a provenance block in the shape the committed inventories use.

    The committed inventories carry a hand-maintained ``provenance`` document.
    Deriving the same shape from the report makes the block a fact about the
    run rather than a fact about a person, and keeps the two inventories
    comparable.
    """

    if suite_report is None:
        return {}
    lock = suite_report.get("suite_source_lock") or {}
    command = suite_report.get("command") or {}
    arguments = command.get("arguments") or []
    case_timeout = 0
    for index, argument in enumerate(arguments):
        if argument == "--case-timeout" and index + 1 < len(arguments):
            try:
                case_timeout = int(arguments[index + 1])
            except ValueError:
                case_timeout = 0
    provenance = {
        "base_commit": args.base_commit,
        "measurement_date": args.measurement_date,
        "measurement_host": _measurement_host(suite_report),
        "note": args.audit_note,
        "sbml_test_suite": {
            "case_timeout_seconds": case_timeout,
            "categories": suite_report.get("categories"),
            "repository": lock.get("repository"),
            "revision": suite_report.get("suite_commit") or lock.get("revision"),
        },
    }
    return provenance


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


GAP_SIDES: tuple[str, ...] = ("harness", "atomizer", "not-applicable")


def gap_side(construct: str) -> str:
    """Classify a gap by the side of the boundary it sits on.

    A *harness-side* gap is a measurement limitation: the gate could not
    evaluate the case, so the case is not a claim about the Atomizer.  An
    *Atomizer-side* gap is a representational one: a construct is not
    representable today.  A case that defines no official reference is
    neither.
    """

    if construct.startswith("harness:"):
        return "harness"
    if construct == "reference:not-applicable":
        return "not-applicable"
    if construct == "reference:no-result-mapping":
        return "harness"
    return "atomizer"


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
        # A report written by an older harness may carry ``other`` even
        # though this inventory revision can now identify the underlying
        # refusal.  Prefer the shared current taxonomy for that unclassified
        # bucket; retain the recorded labels otherwise.
        if not causes or "other" in causes:
            derived = sorted(
                set(_harness_causes("scripts.ci.validate_sbml_test_suite", reason))
            )
            if derived and derived != ["other"]:
                causes = derived
        construct = reason_signature(reason)
        return {
            "construct": construct,
            "causes": causes,
            "side": gap_side(construct),
        }

    if stage == "official_reference":
        official = record.get("official_conformance") or {}
        if str(official.get("status")) != "unsupported":
            return None
        reason = str(official.get("reason") or "")
        causes = sorted(
            set(_harness_causes("scripts.ci.validate_sbml_test_suite", reason))
        )
        construct = reason_signature(reason)
        return {
            "construct": construct,
            "causes": causes,
            "side": gap_side(construct),
        }

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
    measured_commit: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an expectation manifest from one SBML Test Suite report.

    ``measured_commit`` is the commit the manifest *describes*.  The report
    itself records the commit the run actually executed, which may be a
    branch head with the same Atomizer behaviour; both are kept, together
    with the native build and the source tree the numbers came from, so a
    reader can tell which measurement produced the record.
    """

    cases = expectation_cases(report)
    gaps = expectation_gaps(report)
    source_lock = report.get("suite_source_lock") or {}
    source_provenance = report.get("source_provenance") or {}
    runtime = report.get("runtime_provenance") or {}
    measured_at = str(source_provenance.get("bng3_commit") or "")
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
            "bng3_commit": str(measured_commit or measured_at),
            "measured_at_commit": measured_at,
            "python_version": str(runtime.get("python_version") or ""),
        },
        "provenance": {
            "measured_commit": str(measured_commit or measured_at),
            "measured_at_commit": measured_at,
            "measurement_environment": {
                "source_tree": str(runtime.get("bionetgen_package_path") or ""),
                "native_extension_sha256": str(
                    runtime.get("native_extension_sha256") or ""
                ),
                "python_package_source_sha256": str(
                    runtime.get("python_package_source_sha256") or ""
                ),
                "python_version": str(runtime.get("python_version") or ""),
                "platform": str(runtime.get("platform") or ""),
                "libsbml_version": str(runtime.get("libsbml_version") or ""),
                "roadrunner_version": str(runtime.get("roadrunner_version") or ""),
            },
        },
        "cases": {
            identity: {
                **cases[identity],
                **({"gap": gaps[identity]} if identity in gaps else {}),
            }
            for identity in sorted(cases)
        },
    }
    if provenance:
        manifest["provenance"].update(provenance)
    # The recorded summary and the recorded per-case detail must agree, so
    # the summary is derived from the detail rather than typed in.
    manifest["stage_counts"] = {
        stage: dict(
            sorted(Counter(statuses[stage] for statuses in cases.values()).items())
        )
        for stage in EXPECTATION_STAGES
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
    parser.add_argument(
        "--measured-commit",
        help=(
            "the commit the expectation manifest describes; defaults to the "
            "commit the report was produced at"
        ),
    )
    parser.add_argument(
        "--expectations-provenance",
        type=Path,
        help=(
            "JSON document merged into the generated expectation manifest's "
            "'provenance' block"
        ),
    )
    # --- Audit record options -------------------------------------------
    parser.add_argument(
        "--base-commit",
        default="",
        help="the commit a measurement is compared against",
    )
    parser.add_argument(
        "--audit-note",
        default="",
        help="note recorded in the derived provenance block",
    )
    parser.add_argument(
        "--baseline-suite-report",
        type=Path,
        help=(
            "baseline SBML Test Suite harness report; the record then states, "
            "per case, why a verdict moved"
        ),
    )
    parser.add_argument(
        "--biomodels-atomized-report",
        type=Path,
        help="second BioModels harness report, measured in atomized mode",
    )
    parser.add_argument(
        "--biomodels-recheck",
        type=Path,
        help=(
            "serial re-measurement of the BioModels records whose verdict "
            "differed from the baseline; the record then states the counts "
            "after the re-measurement"
        ),
    )
    parser.add_argument(
        "--biomodels-atomized-recheck",
        type=Path,
        help="serial re-measurement for the atomized mode",
    )
    parser.add_argument(
        "--baseline-biomodels-report",
        type=Path,
        help=(
            "baseline curated-BioModels harness report; the record then states, "
            "per record, what changed relative to the baseline"
        ),
    )
    parser.add_argument(
        "--extra-evidence",
        type=Path,
        action="append",
        default=[],
        help=(
            "additional JSON evidence document to embed under "
            "audit.extra_evidence, keyed by its file stem"
        ),
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
            measured_commit=args.measured_commit,
            provenance=(
                _load_json(args.expectations_provenance)
                if args.expectations_provenance is not None
                else None
            ),
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
    suite_report: dict[str, Any] | None = None
    baseline_suite_report: dict[str, Any] | None = None
    biomodels_report: dict[str, Any] | None = None
    biomodels_atomized_report: dict[str, Any] | None = None
    if args.suite_report:
        suite_report = _load_json(args.suite_report)
        inventory["sbml_test_suite"] = suite_inventory(suite_report)
        inventory["sbml_test_suite"]["source_report_sha256"] = _digest(
            args.suite_report
        )
    if args.baseline_suite_report:
        baseline_suite_report = _load_json(args.baseline_suite_report)
    if args.biomodels_report:
        biomodels_report = _load_json(args.biomodels_report)
        inventory["biomodels"] = biomodels_inventory(biomodels_report)
        inventory["biomodels"]["source_report_sha256"] = _digest(args.biomodels_report)
    if args.biomodels_atomized_report:
        biomodels_atomized_report = _load_json(args.biomodels_atomized_report)

    audit_requested = (
        args.baseline_suite_report is not None
        or args.biomodels_atomized_report is not None
        or args.biomodels_recheck is not None
        or args.biomodels_atomized_recheck is not None
        or bool(args.extra_evidence)
    )
    if audit_requested:
        if args.provenance is not None:
            # A supplied provenance document is merged verbatim, exactly as
            # it is without the audit options.
            inventory["provenance"] = _load_json(args.provenance)
        else:
            # Derive the provenance block in the shape the committed
            # inventories use, so the two do not produce different shapes.
            inventory["provenance"] = derived_provenance(suite_report, args)
        inventory["audit"] = audit_section(
            suite_report,
            args.suite_report,
            baseline_suite_report,
            args.baseline_suite_report,
            biomodels_report,
            args.biomodels_report,
            biomodels_atomized_report,
            args.biomodels_atomized_report,
            args,
        )
        modes = inventory["audit"].get("biomodels") or {}
        if args.biomodels_recheck:
            _apply_recheck(modes, _load_json(args.biomodels_recheck), "flat")
        if args.biomodels_atomized_recheck:
            _apply_recheck(
                modes, _load_json(args.biomodels_atomized_recheck), "atomized"
            )
        _mode_comparison(modes)
        if args.baseline_biomodels_report and biomodels_report is not None:
            recheck = (
                _load_json(args.biomodels_recheck) if args.biomodels_recheck else None
            )
            modes["baseline_comparison"] = biomodels_baseline_comparison(
                _load_json(args.baseline_biomodels_report), biomodels_report, recheck
            )
        if args.extra_evidence:
            evidence: dict[str, Any] = {}
            for path in args.extra_evidence:
                evidence[path.stem] = _load_json(path)
            inventory["audit"]["extra_evidence"] = evidence
    elif args.provenance is not None:
        inventory["provenance"] = _load_json(args.provenance)

    _write_json(args.out, inventory)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
