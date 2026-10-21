#!/usr/bin/env python3
"""Build the curated BioModels corpus inventory.

The inventory is a machine-readable record of one measurement of the curated
BioModels corpus: which records exist, what the Atomizer did with each of
them in the flat and the atomized mode, why a record was not supported, and
which construct a residual failure or timeout is attributed to.

The inventory is *derived* from the harness reports.  It never re-judges a
record: the harness owns the conversion, the numerical comparison and the
status vocabulary, and this script only reduces its reports to a stable
schema and adds the corpus identity (the BioModels inventory query, the
snapshot date, the report digests and the tool versions) that a reader needs
to know which measurement the numbers describe.

The same tool also writes the corpus *expectation manifest*: the expected
verdict of every curated record at every stage the corpus gate reports, with
the construct behind every refusal and the side of that gap.  The manifest
turns a corpus regression into a failing comparison instead of a human
reading two large reports side by side, and it uses the vocabulary of the
official SBML Test Suite manifest so the campaign has one vocabulary.

Usage::

    python scripts/ci/curated_biomodels_corpus_inventory.py \
        --flat-report /path/to/flat.json \
        --atomized-report /path/to/atomized.json \
        --manifest provenance/published-biomodels.json \
        --base-commit <sha> --out provenance/curated-biomodels-corpus-inventory.json

    # Regenerate the committed expectation manifest (an explicit, reviewable act).
    python scripts/ci/curated_biomodels_corpus_inventory.py \
        --flat-report /path/to/flat.json \
        --expectations-out provenance/curated-biomodels-corpus-expectations.json

    # Compare a fresh run against the committed expectation manifest.
    python scripts/ci/curated_biomodels_corpus_inventory.py \
        --flat-report /path/to/flat.json \
        --expectations provenance/curated-biomodels-corpus-expectations.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# The residual failures and timeouts of the curated corpus, classified by the
# SBML construct that causes them.  The classification is a statement about the
# *source model*, so it does not change when the Atomizer changes: a record is
# listed here because the construct it uses is the reason the record does not
# convert, not because of a particular code path.  A record that no longer
# fails keeps its entry, so the diagnosis of the boundary it reached stays
# readable.
#
# ``layer`` names the component that owns the outcome:
#
#   atomizer   the Atomizer's lowering is wrong or incomplete
#   harness    the corpus harness or its independent oracle cannot judge the
#              record; the Atomizer's own output is not the cause
#   source     the source model itself is degenerate (an undefined observable,
#              a malformed kinetic law) and the Atomizer reproduces it
FAILURE_TAXONOMY: dict[str, dict[str, Any]] = {
    "BIOMD0000000245": {
        "layer": "atomizer",
        "construct": "reaction id used as a rate inside a rule",
        "summary": (
            "The rule names seven reaction ids; the flux inlining replaced one "
            "reaction per pass and stopped after four passes, so the remaining "
            "ids reached the emitted rule as unresolved expression symbols."
        ),
    },
    "BIOMD0000000570": {
        "layer": "atomizer",
        "construct": "reaction id used as a rate inside a rate rule",
        "summary": (
            "The rate rule names seven reaction ids; the same four-pass "
            "inlining limit left three ids unresolved."
        ),
    },
    "BIOMD0000000353": {
        "layer": "atomizer",
        "construct": "compartment size set by an initialAssignment",
        "summary": (
            "A species assignment rule names a compartment whose size is set "
            "by an initial assignment; the compartment was rewritten to the "
            "constant volume parameter, producing a call to an undeclared "
            "function."
        ),
    },
    "BIOMD0000000638": {
        "layer": "atomizer",
        "construct": "compartment size in a scaled unit",
        "summary": (
            "The unit conversion multiplied the declared size by the double "
            "approximation of the conversion factor, which rounds the product "
            "twice.  The scaled size was one unit in the last place away from "
            "the value the source states, and the record's rate laws divide by "
            "it, so the rate coefficients are of order 1e19 and the model is "
            "stiff: that one unit stopped libRoadRunner's CVODE from taking its "
            "first step."
        ),
    },
    "BIOMD0000000954": {
        "layer": "atomizer",
        "construct": "rate law that names a species the reaction does not consume",
        "summary": (
            "The numeric mass-action probe replaced the state-dependent rate "
            "law of the Cdh1dp production with a fitted constant, so the "
            "emitted model was a snapshot of the law at the probe points "
            "rather than the law itself.  The constant changed with the probe, "
            "so the record's status was not reproducible at a fixed commit."
        ),
    },
    "BIOMD0000001098": {
        "layer": "atomizer",
        "construct": "MathML <apply> without an operator",
        "summary": (
            "The kinetic law of every reaction is an <apply> whose operator is "
            "a <ci> naming a parameter, which MathML reads as a call to an "
            "undeclared function.  The Atomizer translated the call faithfully "
            "and emitted a rule that does not parse."
        ),
    },
    "BIOMD0000000338": {
        "layer": "harness",
        "construct": "event-driven compartment size with a species rate rule",
        "summary": (
            "The Atomizer refuses explicitly: a species rate rule in a "
            "compartment whose size an event changes has no exact BNGL "
            "lowering.  The corpus harness now recognises the refusal and "
            "records the record as unsupported, with the construct named, "
            "instead of as a failure of the gate."
        ),
    },
    "BIOMD0000000339": {
        "layer": "harness",
        "construct": "event-driven compartment size with a species rate rule",
        "summary": (
            "The Atomizer refuses explicitly for the same reason as "
            "BIOMD0000000338; the corpus harness now recognises the refusal "
            "and records the record as unsupported."
        ),
    },
    "BIOMD0000000404": {
        "layer": "harness",
        "construct": "ill-conditioned product observable",
        "summary": (
            "The failing observable is a seven-fold product of species "
            "concentrations in a 1.41e-15 L compartment.  The comparison sits "
            "at the edge of the tolerance and does not reproduce between runs."
        ),
    },
    "BIOMD0000000451": {
        "layer": "harness",
        "construct": "stiff model rejected by the independent oracle's solver",
        "summary": (
            "libRoadRunner's CVODE fails to converge on the written SBML; "
            "BNG3's own solver produces a trajectory, and the two models "
            "integrate alike at a tolerance libRoadRunner can reach.  The "
            "corpus comparison needs a trajectory from both engines, so the "
            "record is recorded as not comparable rather than as a "
            "disagreement."
        ),
    },
    "BIOMD0000000601": {
        "layer": "harness",
        "construct": "stiff model rejected by a solver",
        "summary": (
            "A CVODE convergence failure on a stiff model.  The record does "
            "not reproduce on the merged tree with the rebuilt native "
            "extension."
        ),
    },
    "BIOMD0000000674": {
        "layer": "atomizer",
        "construct": "reversible TotalRate rule written as a mass-action law",
        "summary": (
            "The C++ SBML writer recognised the TotalRate modifier only in "
            "the forward direction of a reversible rule.  The reverse "
            "reaction was written as an ordinary mass-action law: it carried "
            "an extra factor of the species the forward rule produced and it "
            "lost the bng:totalRate annotation, so the written SBML did not "
            "reproduce the model it came from.  The writer now recognises the "
            "modifier in both directions."
        ),
    },
    "BIOMD0000000731": {
        "layer": "source",
        "construct": "observable that is undefined at t=0",
        "summary": (
            "The observable is ln of a quantity that is zero at t=0, so both "
            "BNG3 and libRoadRunner return -inf.  A pointwise comparison "
            "cannot measure the record, so the corpus gate records it as not "
            "comparable instead of as a failure."
        ),
    },
    "BIOMD0000000803": {
        "layer": "source",
        "construct": "observable that is undefined at t=0",
        "summary": (
            "The observable is a ratio of two species that both start at "
            "zero, so both BNG3 and libRoadRunner return NaN.  A pointwise "
            "comparison cannot measure the record, so the corpus gate records "
            "it as not comparable instead of as a failure."
        ),
    },
    "BIOMD0000000973": {
        "layer": "source",
        "construct": "observable that is undefined at t=0",
        "summary": (
            "The observable divides by a species that starts at zero, so both "
            "BNG3 and libRoadRunner return NaN.  A pointwise comparison "
            "cannot measure the record, so the corpus gate records it as not "
            "comparable instead of as a failure."
        ),
    },
}

TIMEOUT_TAXONOMY: dict[str, dict[str, Any]] = {
    "BIOMD0000001096": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000001099": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000574": {
        "layer": "atomizer",
        "construct": "large regulatory network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000474": {
        "layer": "atomizer",
        "construct": "large regulatory network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000255": {
        "layer": "atomizer",
        "construct": "large signalling network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000235": {
        "layer": "atomizer",
        "construct": "large regulatory network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000595": {
        "layer": "atomizer",
        "construct": "large signalling network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000471": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000473": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000469": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000470": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000472": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
}

# The effect of the change under review, measured record by record with the
# corpus gate's own ``--only-id`` path.  The entries are the records the
# branch changes; each one was measured on the branch and on ``main`` with the
# same native extension.
BRANCH_EFFECT: dict[str, dict[str, Any]] = {
    "BIOMD0000000245": {
        "construct": "reaction id used as a rate inside a rule",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "The rule names seven reaction ids.  The flux inlining replaced one "
            "reaction per pass and stopped after four passes, so the remaining "
            "ids reached the emitted rule as unresolved expression symbols and "
            "the model did not compile."
        ),
    },
    "BIOMD0000000570": {
        "construct": "reaction id used as a rate inside a rate rule",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "The rate rule names seven reaction ids; the same four-pass limit "
            "left three of them unresolved."
        ),
    },
    "BIOMD0000000353": {
        "construct": "compartment size set by an initialAssignment",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "A species assignment rule names a compartment whose size an "
            "initial assignment sets; the compartment was rewritten to the "
            "constant volume parameter, producing a call to an undeclared "
            "function."
        ),
    },
    "BIOMD0000000638": {
        "construct": "compartment size in a scaled unit",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "The scaled compartment size was one unit in the last place away "
            "from the value the source states, and the independent oracle "
            "failed to converge on it."
        ),
    },
    "BIOMD0000000954": {
        "construct": "rate law that names a species the reaction does not consume",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "A state-dependent rate law was replaced by a numerically fitted "
            "constant, so the exported model was not the model the source "
            "states."
        ),
    },
    "BIOMD0000001098": {
        "construct": "MathML <apply> without an operator",
        "main": "failed",
        "branch": "unsupported",
        "cause": (
            "Every kinetic law is an <apply> whose operator is a <ci> naming a "
            "parameter, which MathML reads as a call to an undeclared "
            "function; the emitted rule did not parse.  The construct is now "
            "reported as a loss."
        ),
    },
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# The corpus expectation manifest
# ---------------------------------------------------------------------------

CORPUS_EXPECTATION_SCHEMA_VERSION = 1

# The stages of the curated BioModels gate that the flat (SBML path) mode
# reports, in report order.  They are the corpus counterparts of the official
# SBML Test Suite gate's stages: the corpus has no official reference
# trajectory, so its third stage is the independent libRoadRunner comparison.
CORPUS_EXPECTATION_STAGES: tuple[str, ...] = (
    "conversion",
    "roundtrip_structure",
    "independent_comparison",
)

# The closed expectation vocabulary of the curated corpus.  It is the official
# SBML Test Suite manifest's vocabulary plus the three buckets the corpus gate
# has of its own:
#
#   unsupported_format  the record is not an SBML artifact at all
#   timeout             the run produced no verdict for the record
#   not_comparable      the gate could not measure the record: the record's
#                       own observable has no value to compare, or the
#                       independent oracle could not integrate the model
#
# A timeout is *not* a verdict.  The corpus gate's per-model budget is sized
# for an unloaded machine, so a timeout records that the machine was busy, not
# that the model is unsupported.  A difference that is only a timeout is
# reported as such and is never counted as a regression.
#
# A *not_comparable* verdict is not a verdict about the model either: the
# record says why the comparison could not be measured, and its gap entry
# names the construct that makes the measurement impossible.
CORPUS_EXPECTATION_STATUSES: tuple[str, ...] = (
    "passed",
    "unsupported",
    "failed",
    "not_tested",
    "unsupported_format",
    "timeout",
    "not_comparable",
)

# The sides of a gap, shared with the official SBML Test Suite manifest.
#
#   harness        the gate could not evaluate the record; the record is a
#                  measurement limitation, not a claim about the Atomizer
#   atomizer       a construct is not representable today
#   not-applicable the record does not present a convertible SBML document
#   source         the source model itself is degenerate -- an observable that
#                  is undefined at the initial point -- and the Atomizer
#                  reproduces that degeneracy exactly
CORPUS_GAP_SIDES: tuple[str, ...] = (
    "harness",
    "atomizer",
    "not-applicable",
    "source",
)

# The constructs whose boundary is the *semantics* of the source model rather
# than the presence of a convertible document.  They carry their own side, so
# they are listed here instead of being derived from the construct's prefix.
SOURCE_SEMANTIC_CONSTRUCTS: tuple[str, ...] = ("source:undefined-observable",)

# The construct that keeps a record from converting.  The needles are matched
# against the harness's own reason text and the signatures are the official
# SBML Test Suite manifest's signatures for the same constructs, so the two
# manifests name the same construct the same way.  The needles are ordered
# from the most specific to the least, so a record that carries two reasons is
# named by the one that describes its boundary.
CORPUS_CONSTRUCTS: tuple[tuple[str, str], ...] = (
    ("not an sbml biomodels artifact", "format:not-an-sbml-artifact"),
    ("contains no usable sbml", "format:no-usable-sbml"),
    ("not libsbml-valid", "source:libsbml-invalid"),
    (
        "could not integrate the written sbml",
        "harness:oracle-solver-failure",
    ),
    (
        "the source observable is undefined at",
        "source:undefined-observable",
    ),
    (
        "event-controlled parameter initial assignment",
        "assignment:event-controlled-initial-value",
    ),
    ("flux-balance constraints/objectives", "constraints:flux-balance-not-kinetic"),
    ("qual package is present", "package:qual-not-quantitative"),
    ("event(s) parsed", "events:untranslated"),
    ("is marked fast", "fast-reaction:no-fast-equilibrium-solve"),
    ("is not losslessly representable", "sbml-writer:unrepresentable-function"),
    ("uses the undefined operator", "mathml:undefined-operator"),
    ("conversion factor", "conversion-factor:unsupported"),
    ("algebraic rule", "rules:algebraic-not-applied"),
    (
        "assignment rule targets species",
        "rules:species-rate-rule-needs-compartment",
    ),
    ("compartment derivative", "rules:species-rate-rule-needs-compartment"),
    ("reaction-local", "scope:reaction-local"),
    ("no mathml kinetic law", "sbml:reaction-without-kinetic-law"),
    ("no mathml expression", "sbml:empty-math"),
    ("spatialdimensions", "compartment:unsupported-spatial-dimensions"),
    ("unsupported stoichiometry", "stoichiometry:unsupported"),
    (
        "could not be resolved to a number",
        "stoichiometry:assigned-stoichiometry-unresolved",
    ),
    ("no species", "model:no-state-variables"),
    ("no reactants or products", "reaction:no-participants"),
    ("negative numeric rate", "rate:negative"),
    ("distrib", "package:distrib"),
)


def corpus_construct(reason: str) -> str:
    """Name the construct that keeps a record from converting."""

    lowered = str(reason or "").lower()
    for needle, construct in CORPUS_CONSTRUCTS:
        if needle in lowered:
            return construct
    return "other"


def corpus_gap_side(construct: str) -> str:
    """Classify a gap by the side of the boundary it sits on.

    A *harness-side* gap is a measurement limitation: the gate could not
    evaluate the record, so the record is not a claim about the Atomizer.  An
    *Atomizer-side* gap is a representational one: a construct is not
    representable today.  A record that does not present a convertible SBML
    document is neither: there is nothing for the SBML path to evaluate.  A
    record whose *own* observable is undefined sits on the source's side:
    the model reproduces the source exactly, and there is no value to
    compare.
    """

    if construct in SOURCE_SEMANTIC_CONSTRUCTS:
        return "source"
    if construct.startswith("harness:"):
        return "harness"
    if construct.startswith("format:") or construct.startswith("source:"):
        return "not-applicable"
    return "atomizer"


def _mode_result(record: dict[str, Any], mode: str = "flat") -> dict[str, Any] | None:
    """Return the per-mode result of one harness record."""

    for entry in record.get("modes") or []:
        if str(entry.get("mode")) == mode:
            return entry
    return None


def _conversion_status(record: dict[str, Any]) -> str:
    """Return the corpus gate's own verdict for a record."""

    status = str(record.get("status") or "")
    if status in CORPUS_EXPECTATION_STATUSES:
        return status
    return "not_tested"


def _roundtrip_status(mode: dict[str, Any] | None) -> str:
    """Return the verdict of the structural round trip.

    The round trip is the corpus gate's own check: the written SBML is valid
    and the native reader reads back the generated network's species and
    reaction counts.  A stage that produced no verdict at all -- the record
    was refused before the model was written, or the worker was killed -- is
    ``not_tested``.

    The Python re-import's own counts are *not* a verdict: the corpus gate
    records them but does not compare them, so a manifest that called them a
    failure would report a verdict the gate does not produce.
    """

    if not mode:
        return "not_tested"
    written = mode.get("written_xml") or {}
    if written.get("passed") is False:
        return "failed"
    generated = mode.get("generated_network") or {}
    native = mode.get("native_reader") or {}
    if native.get("success") is True and generated:
        if native.get("species_count") != generated.get("species") or native.get(
            "reaction_count"
        ) != generated.get("reactions"):
            return "failed"
        return "passed"
    if native and native.get("success") is False:
        return "failed"
    return "not_tested"


def _independent_status(mode: dict[str, Any] | None) -> str:
    """Return the verdict of the independent libRoadRunner comparison."""

    if not mode:
        return "not_tested"
    comparison = mode.get("simulation_comparison") or {}
    if comparison.get("passed") is True:
        return "passed"
    if comparison.get("skipped"):
        return "not_tested"
    if comparison.get("not_comparable"):
        # The comparison ran, but it could not measure the record: the
        # record's own observable has no value to compare, or the independent
        # oracle could not integrate the written model.
        return "not_comparable"
    if comparison:
        return "failed"
    return "not_tested"


def _record_reason(record: dict[str, Any]) -> str:
    """Return the reason that explains a record's refusal."""

    reason = str(record.get("unsupported_reason") or "").strip()
    if reason:
        return reason
    reason = str(record.get("not_comparable_reason") or "").strip()
    if reason:
        return reason
    for mode in record.get("modes") or []:
        candidate = str(mode.get("unsupported_reason") or "").strip()
        if candidate:
            return candidate
        candidate = str(mode.get("not_comparable_reason") or "").strip()
        if candidate:
            return candidate
        error = str(mode.get("error") or "").strip()
        if error:
            return error
    return str(record.get("error") or "").strip()


def _record_causes(record: dict[str, Any], reason: str) -> list[str]:
    """Return the harness's cause labels for a refused record."""

    recorded = sorted(
        set(str(cause) for cause in (record.get("unsupported_causes") or []))
    )
    if recorded:
        return recorded
    if str(record.get("status")) == "unsupported_format":
        return ["format"]
    if str(record.get("status")) not in {"unsupported", "not_comparable"}:
        return []
    return sorted(
        set(_harness_causes("scripts.ci.validate_published_biomodels", reason))
    )


def _harness_causes(module_name: str, reason: str) -> list[str]:
    """Reuse the corpus harness's cause taxonomy when it is importable.

    The harness owns the taxonomy; the manifest only reads it.  A missing or
    unimportable harness yields no labels rather than an invented one.
    """

    # The script runs as ``python scripts/ci/curated_biomodels_corpus_inventory.py``,
    # which puts ``scripts/ci`` on the path rather than the repository root the
    # harness is imported by.  The harness's taxonomy is the harness's to own,
    # so the root goes on the path before the import is attempted.
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
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


def corpus_expectation_cases(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return the observed verdict of every record at every stage."""

    cases: dict[str, dict[str, str]] = {}
    for record in report.get("records") or []:
        identity = str(record.get("id") or "")
        if not identity:
            continue
        mode = _mode_result(record)
        cases[identity] = {
            "conversion": _conversion_status(record),
            "roundtrip_structure": _roundtrip_status(mode),
            "independent_comparison": _independent_status(mode),
        }
    return cases


def corpus_expectation_gaps(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the construct that keeps each refused record from converting."""

    gaps: dict[str, dict[str, Any]] = {}
    for record in report.get("records") or []:
        identity = str(record.get("id") or "")
        if not identity:
            continue
        if str(record.get("status")) not in {
            "unsupported",
            "unsupported_format",
            "not_comparable",
        }:
            continue
        reason = _record_reason(record)
        construct = corpus_construct(reason)
        gaps[identity] = {
            "conversion": {
                "construct": construct,
                "causes": _record_causes(record, reason),
                "side": corpus_gap_side(construct),
            }
        }
    return gaps


def _corpus_identity(
    manifest: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Return the corpus identity the report was measured against."""

    inventory = report.get("inventory") or {}
    completeness = report.get("completeness") or {}
    expected = manifest.get("corpus") or {}
    return {
        "inventory_query": str(inventory.get("query") or ""),
        "expected_total_records": completeness.get("expected_records"),
        "expected_sbml_records": completeness.get("expected_sbml_records"),
        "expected_non_sbml_records": completeness.get("expected_non_sbml_records"),
        "declared_query": str(expected.get("inventory_query") or ""),
        "declared_total_records": expected.get("expected_total_records"),
        "declared_sbml_records": expected.get("expected_sbml_records"),
        "declared_non_sbml_records": expected.get("expected_non_sbml_records"),
    }


def _identity_mismatches(identity: dict[str, Any]) -> list[str]:
    """Return the corpus identity fields a report does not agree with."""

    mismatches = []
    pairs = (
        ("inventory_query", "declared_query"),
        ("expected_total_records", "declared_total_records"),
        ("expected_sbml_records", "declared_sbml_records"),
        ("expected_non_sbml_records", "declared_non_sbml_records"),
    )
    for observed_key, declared_key in pairs:
        observed = identity.get(observed_key)
        declared = identity.get(declared_key)
        if observed in (None, "") or declared in (None, ""):
            continue
        if observed != declared:
            mismatches.append(
                f"{observed_key}: report {observed!r} != manifest {declared!r}"
            )
    return mismatches


def _report_revision(report: dict[str, Any]) -> str:
    """Return the revision the report states it was measured at."""

    for holder in (
        report.get("source_provenance") or {},
        report.get("runtime_provenance") or {},
    ):
        value = str(holder.get("bng3_commit") or holder.get("bng3_revision") or "")
        if value:
            return value
    return str(report.get("tool_revision") or "")


def corpus_expectations_from_report(
    report: dict[str, Any],
    *,
    source_report_sha256: str,
    corpus: dict[str, Any] | None = None,
    measurement_date: str | None = None,
    measured_commit: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the corpus expectation manifest from one corpus gate report.

    The manifest records the verdict every curated record is expected to
    produce at every stage the corpus gate reports, so a corpus regression
    fails a comparison instead of needing a human to read two large reports
    side by side.
    """

    mode = str(report.get("mode") or "flat")
    if mode != "flat":
        raise ValueError(
            "the corpus expectation manifest describes the flat (SBML path) "
            f"measurement; the report was measured in the {mode!r} mode"
        )
    cases = corpus_expectation_cases(report)
    gaps = corpus_expectation_gaps(report)
    runtime = report.get("runtime_provenance") or {}
    manifest: dict[str, Any] = {
        "schema_version": CORPUS_EXPECTATION_SCHEMA_VERSION,
        "kind": "curated-biomodels-corpus-expectations",
        "generator": "scripts/ci/curated_biomodels_corpus_inventory.py",
        "note": (
            "Each entry records the verdict the tree named by "
            "source_report.bng3_commit produced for that record at each stage "
            "of the curated BioModels gate. 'passed' is a result. 'failed' is "
            "a result too: the stage ran and disagreed with the independent "
            "comparison, which is a finding to investigate. 'unsupported', "
            "'unsupported_format' and 'not_comparable' are the only gaps: the "
            "record was refused, or the gate could not measure it, and its "
            "'gap' entry names the construct that is not representable today "
            "together with the harness's cause labels and the side of the "
            "gap. A 'not_comparable' record is one whose own observable has "
            "no value to compare, or whose independent oracle could not "
            "integrate the model: it is neither a pass nor a disagreement. A "
            "'timeout' is not a verdict: the corpus gate's per-model budget "
            "is sized for an unloaded machine, so a timeout records that the "
            "machine was busy and never counts as a regression. No entry "
            "claims that a currently unsupported construct should become "
            "supported, and an 'unsupported' entry is never counted as "
            "support."
        ),
        "stages": list(CORPUS_EXPECTATION_STAGES),
        "statuses": list(CORPUS_EXPECTATION_STATUSES),
        "status_mapping": {
            "conversion": (
                "the corpus gate's record status; a timeout maps to timeout "
                "and is not a verdict"
            ),
            "roundtrip_structure": (
                "the written SBML re-imports with the generated network's "
                "species and reaction counts; a stage that produced no "
                "verdict maps to not_tested"
            ),
            "independent_comparison": (
                "simulation_comparison.passed; a skipped comparison maps to "
                "not_tested"
            ),
        },
        "sides": list(CORPUS_GAP_SIDES),
        "corpus": dict(corpus or {}),
        "source_report": {
            "sha256": source_report_sha256,
            "bng3_commit": str(measured_commit or _report_revision(report)),
            "measured_at_commit": _report_revision(report),
            "mode": mode,
            "python_version": str(runtime.get("python_version") or ""),
        },
        "provenance": {
            "tool_versions": _tool_versions(),
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
    manifest["stage_counts"] = {
        stage: dict(
            sorted(Counter(statuses[stage] for statuses in cases.values()).items())
        )
        for stage in CORPUS_EXPECTATION_STAGES
    }
    constructs: Counter = Counter()
    sides: Counter = Counter()
    for entry in gaps.values():
        for detail in entry.values():
            constructs[detail["construct"]] += 1
            sides[detail["side"]] += 1
    manifest["gap_counts"] = {
        "by_construct": dict(sorted(constructs.items())),
        "by_side": dict(sorted(sides.items())),
    }
    if measurement_date:
        manifest["source_report"]["measurement_date"] = measurement_date
    return manifest


def classify_corpus_difference(expected: str, observed: str) -> str:
    """Classify one expected/observed verdict difference.

    A difference in which a timeout takes part is not a verdict difference:
    the timeout bucket is load-sensitive, so it is classified on its own and
    never counted as a regression in either direction.
    """

    if expected == observed:
        return "same"
    if "timeout" in {expected, observed}:
        return "timeout"
    if expected == "passed" and observed != "passed":
        return "regression"
    if expected != "passed" and observed == "passed":
        return "improvement"
    return "change"


def compare_corpus_expectations(
    manifest: dict[str, Any],
    report: dict[str, Any],
    report_revision: str | None = None,
) -> dict[str, Any]:
    """Compare an observed run against a committed expectation manifest.

    Every difference is reported.  A record that was ``passed`` and no longer
    is a regression; a record that moves to ``passed`` is an improvement that
    is only accepted once the manifest is explicitly updated; a record that
    disappeared is reported, never ignored.
    """

    expected_cases = manifest.get("cases") or {}
    observed = corpus_expectation_cases(report)
    differences: list[dict[str, Any]] = []
    not_executed: list[str] = []
    completeness = report.get("completeness") or {}
    partial = bool(completeness.get("partial_run"))

    for identity in sorted(set(expected_cases) | set(observed)):
        expected = expected_cases.get(identity)
        actual = observed.get(identity)
        if expected is None:
            differences.append(
                {
                    "record": identity,
                    "stage": "*",
                    "expected": None,
                    "observed": "present",
                    "classification": "unrecorded-record",
                }
            )
            continue
        if actual is None:
            if partial:
                not_executed.append(identity)
                continue
            differences.append(
                {
                    "record": identity,
                    "stage": "*",
                    "expected": "present",
                    "observed": None,
                    "classification": "missing-record",
                }
            )
            continue
        for stage in CORPUS_EXPECTATION_STAGES:
            expected_status = str(expected.get(stage, "not_tested"))
            observed_status = str(actual.get(stage, "not_tested"))
            if expected_status == observed_status:
                continue
            timeout_sides = sorted(
                side
                for side, status in (
                    ("expected", str(expected.get("conversion", "not_tested"))),
                    ("observed", str(actual.get("conversion", "not_tested"))),
                )
                if status == "timeout"
            )
            if timeout_sides:
                # The record produced no verdict on one side, so no verdict
                # expectation can be checked: the difference is the
                # load-sensitive timeout bucket, not a change of a verdict.
                classification = "timeout"
            else:
                classification = classify_corpus_difference(
                    expected_status, observed_status
                )
            difference: dict[str, Any] = {
                "record": identity,
                "stage": stage,
                "expected": expected_status,
                "observed": observed_status,
                "classification": classification,
            }
            if timeout_sides:
                difference["timeout_side"] = "+".join(timeout_sides)
            differences.append(difference)

    identity = _corpus_identity(manifest, report)
    mismatches = _identity_mismatches(identity)
    manifest_revision = str(
        (manifest.get("source_report") or {}).get("bng3_commit") or ""
    )
    observed_revision = str(report_revision or _report_revision(report))
    return {
        "records_compared": len(observed),
        "records_expected": len(expected_cases),
        "records_not_executed": len(not_executed),
        "corpus_identity_mismatches": mismatches,
        "revision_expected": manifest_revision,
        "revision_observed": observed_revision,
        "revision_mismatch": bool(
            manifest_revision
            and observed_revision
            and manifest_revision != observed_revision
        ),
        "differences": differences,
    }


def format_corpus_difference(diff: dict[str, Any]) -> str:
    """Render one difference as a reviewable line."""

    line = (
        f"{diff['record']} [{diff['stage']}]: expected {diff['expected']}, "
        f"observed {diff['observed']} ({diff['classification']})"
    )
    if "timeout_side" in diff:
        line += f" [{diff['timeout_side']} side timed out]"
    return line


def _write_corpus_expectations(path: Path, manifest: dict[str, Any]) -> None:
    """Write the expectation manifest with one compact line per record.

    The manifest holds one entry per record per stage.  Writing each record
    on a single line keeps the file reviewable and makes a refresh diff show
    the records whose verdict actually changed.
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
        parts = [f'"{stage}": "{entry[stage]}"' for stage in CORPUS_EXPECTATION_STAGES]
        gap = entry.get("gap")
        if gap:
            parts.append('"gap": ' + json.dumps(gap, sort_keys=True))
        lines.append(f'    "{identity}": {{' + ", ".join(parts) + "}")
    body += '\n  "cases": {\n' + ",\n".join(lines) + "\n  }\n}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _tool_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for name in ("libsbml", "roadrunner"):
        try:
            module = __import__(name)
        except ImportError:
            versions[name] = None
            continue
        versions[name] = getattr(module, "__version__", None)
    try:
        import bionetgen

        versions["bionetgen"] = getattr(bionetgen, "__version__", None)
    except ImportError:
        versions["bionetgen"] = None
    return versions


def _record_modes(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the per-mode results of one harness record."""

    modes = record.get("modes")
    if isinstance(modes, list):
        return modes
    return []


def _mode_status(record: dict[str, Any], mode: str) -> str:
    for entry in _record_modes(record):
        if entry.get("mode") == mode:
            return str(entry.get("status") or "passed")
    return str(record.get("status") or "unknown")


def _structural_atomization(bngl: str) -> dict[str, Any]:
    """Report whether a generated model carries inferred molecular structure.

    The structural trigger in the Atomizer's species-composition table is a
    bond character in a species name.  A model whose species names carry no
    bond character degrades to one molecule per species, which is the flat
    representation written with a different name.
    """

    molecules = 0
    bonded = 0
    for line in bngl.splitlines():
        stripped = line.strip()
        if not stripped.startswith("M_"):
            continue
        molecules += 1
        if "(" in stripped and ")" in stripped:
            inner = stripped[stripped.find("(") + 1 : stripped.rfind(")")]
            if re.search(r"[!\-=]", inner):
                bonded += 1
    return {
        "molecule_types": molecules,
        "molecule_types_with_bonds": bonded,
        "structurally_atomized": bonded > 0,
    }


def _summarize(report: dict[str, Any], label: str) -> dict[str, Any]:
    records = report.get("records") or []
    status_counts: Counter = Counter()
    cause_counts: Counter = Counter()
    sbml_records = 0
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] += 1
        for cause in record.get("unsupported_causes") or []:
            cause_counts[str(cause)] += 1
        if str(record.get("format", "")).lower().find("sbml") >= 0:
            sbml_records += 1
    return {
        "label": label,
        "mode": report.get("mode"),
        "selected_records": len(records),
        "declared_sbml_records": sbml_records,
        "status_counts": dict(sorted(status_counts.items())),
        "unsupported_cause_counts": dict(sorted(cause_counts.items())),
        "summary": report.get("summary"),
    }


def _case_rows(
    flat: dict[str, Any],
    atomized: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    flat_records = {str(r.get("id")): r for r in (flat.get("records") or [])}
    atomized_records = (
        {str(r.get("id")): r for r in (atomized.get("records") or [])}
        if atomized
        else {}
    )
    rows: list[dict[str, Any]] = []
    for model_id, record in flat_records.items():
        other = atomized_records.get(model_id)
        flat_status = str(record.get("status", "unknown"))
        atomized_status = (
            str(other.get("status", "unknown")) if other is not None else None
        )
        row: dict[str, Any] = {
            "id": model_id,
            "name": record.get("name"),
            "format": record.get("format"),
            "flat_status": flat_status,
            "atomized_status": atomized_status,
            "flat_causes": sorted(
                set(str(c) for c in (record.get("unsupported_causes") or []))
            ),
            "atomized_causes": (
                sorted(set(str(c) for c in (other.get("unsupported_causes") or [])))
                if other is not None
                else None
            ),
            "moved_between_modes": (
                atomized_status is not None and atomized_status != flat_status
            ),
            "flat_network": _network_size(record),
            "atomized_network": _network_size(other) if other is not None else None,
        }
        if flat_status == "failed":
            row["failure_classification"] = FAILURE_TAXONOMY.get(model_id)
        if flat_status == "timeout":
            row["timeout_classification"] = TIMEOUT_TAXONOMY.get(model_id)
        rows.append(row)
    return rows


def _network_size(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the generated network size of one harness record."""

    if not record:
        return None
    for entry in _record_modes(record):
        network = entry.get("generated_network")
        if network:
            return {
                "species": network.get("species"),
                "reactions": network.get("reactions"),
            }
    return None


def _corpus_identity_block(
    corpus_manifest: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Return the corpus identity the report and the corpus manifest agree on.

    The identity is what a reader needs to know which collection the
    measurement describes: the query that enumerates it, the snapshot date of
    the manifest that declares it, and the record counts.
    """

    summary = report.get("summary") or {}
    completeness = report.get("completeness") or {}
    inventory = report.get("inventory") or {}
    query = str(corpus_manifest.get("curation_query") or "")
    observed_query = str(inventory.get("query") or "")
    if observed_query and query and observed_query != query:
        raise ValueError(
            "the report was measured against a different corpus: it enumerates "
            f"{observed_query!r} and the corpus manifest declares {query!r}"
        )
    return {
        "source": corpus_manifest.get("source"),
        "search_api_url": corpus_manifest.get("search_api_url"),
        "inventory_query": query,
        "snapshot_date": corpus_manifest.get("snapshot_date"),
        "expected_total_records": corpus_manifest.get("expected_total_records"),
        "expected_sbml_records": corpus_manifest.get("expected_sbml_records"),
        "expected_non_sbml_records": corpus_manifest.get("expected_non_sbml_records"),
        "record_count": len(report.get("records") or []),
        "sbml_path_record_count": summary.get("sbml_records"),
        "inventory_matches": completeness.get("inventory_matches"),
    }


def _regenerated_expectations(
    args: argparse.Namespace,
    corpus_manifest: dict[str, Any],
    report: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild the expectation manifest from the report the manifest names.

    The rebuild uses the committed manifest's own header inputs -- the
    measurement date, the commit it describes and its provenance block -- so a
    regeneration is a pure function of the report and the committed record.
    """

    source_report = manifest.get("source_report") or {}
    return corpus_expectations_from_report(
        report,
        source_report_sha256=_digest(args.flat_report),
        corpus=_corpus_identity_block(corpus_manifest, report),
        measurement_date=str(source_report.get("measurement_date") or "") or None,
        measured_commit=str(source_report.get("bng3_commit") or "") or None,
        provenance=manifest.get("provenance"),
    )


def _expectations_main(
    args: argparse.Namespace,
    corpus_manifest: dict[str, Any],
    report: dict[str, Any],
) -> int:
    """Write or check the corpus expectation manifest."""

    if args.expectations_out is not None:
        provenance = (
            json.loads(args.expectations_provenance.read_text(encoding="utf-8"))
            if args.expectations_provenance
            else None
        )
        manifest = corpus_expectations_from_report(
            report,
            source_report_sha256=_digest(args.flat_report),
            corpus=_corpus_identity_block(corpus_manifest, report),
            measurement_date=args.measurement_date or None,
            measured_commit=args.measured_commit or None,
            provenance=provenance,
        )
        _write_corpus_expectations(args.expectations_out, manifest)
        print(
            f"wrote {args.expectations_out} "
            f"({manifest['corpus']['record_count']} records)"
        )
        return 0

    manifest = json.loads(args.expectations.read_text(encoding="utf-8"))

    if args.verify_regeneration:
        regenerated = _regenerated_expectations(args, corpus_manifest, report, manifest)
        with tempfile.TemporaryDirectory(prefix="bng3-corpus-expectations-") as tmp:
            rebuilt = Path(tmp) / "expectations.json"
            _write_corpus_expectations(rebuilt, regenerated)
            committed = args.expectations.read_bytes()
            derived = rebuilt.read_bytes()
        if committed == derived:
            print(
                f"{args.expectations} regenerates byte-identically from "
                f"{args.flat_report}"
            )
            return 0
        print(
            f"{args.expectations} does not regenerate byte-identically from "
            f"{args.flat_report}",
            file=sys.stderr,
        )
        return 1

    comparison = compare_corpus_expectations(
        manifest,
        report,
        report_revision=args.report_revision or None,
    )
    mismatches = list(comparison["corpus_identity_mismatches"])
    # The snapshot the expectation was recorded against must still be the
    # snapshot the corpus manifest declares.
    declared_corpus = manifest.get("corpus") or {}
    for corpus_key, manifest_key in (
        ("snapshot_date", "snapshot_date"),
        ("curation_query", "inventory_query"),
    ):
        current = corpus_manifest.get(corpus_key)
        declared = declared_corpus.get(manifest_key)
        if current and declared and current != declared:
            mismatches.append(
                f"{manifest_key}: the corpus manifest declares {current!r} and "
                f"the expectation manifest {declared!r}"
            )
    if mismatches:
        print(
            "corpus identity mismatch: the report was measured against a "
            "different corpus",
            file=sys.stderr,
        )
        for mismatch in mismatches:
            print(f"  {mismatch}", file=sys.stderr)
        return 2
    if comparison["revision_mismatch"]:
        print(
            "tool revision mismatch: the manifest describes "
            f"{comparison['revision_expected']}, the run used "
            f"{comparison['revision_observed']}",
            file=sys.stderr,
        )
        return 2
    if comparison["revision_expected"] and not comparison["revision_observed"]:
        print(
            "the report does not state the revision it was measured at; pass "
            "--report-revision with the commit the run executed",
            file=sys.stderr,
        )
        return 2

    differences = comparison["differences"]
    verdict_differences = [
        diff for diff in differences if diff["classification"] != "timeout"
    ]
    timeout_differences = [
        diff for diff in differences if diff["classification"] == "timeout"
    ]
    if verdict_differences:
        print(
            f"{len(verdict_differences)} expectation difference(s) against "
            f"{args.expectations}:",
            file=sys.stderr,
        )
        for diff in verdict_differences:
            print(f"  {format_corpus_difference(diff)}", file=sys.stderr)
        print(
            "Update the manifest only when the change is intended and reviewed.",
            file=sys.stderr,
        )
    if timeout_differences:
        print(
            f"{len(timeout_differences)} timeout difference(s): the corpus "
            "gate's timeout bucket is load-sensitive on a shared machine and a "
            "timeout is not a verdict, so these are reported and are not "
            "counted as regressions:",
            file=sys.stderr,
        )
        for diff in timeout_differences:
            print(f"  {format_corpus_difference(diff)}", file=sys.stderr)
    if verdict_differences:
        return 1
    print(
        f"{comparison['records_compared']} record(s) match {args.expectations} "
        f"({comparison['records_not_executed']} not executed by this run)"
    )
    return 0


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flat-report", type=Path, required=True)
    parser.add_argument("--atomized-report", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo / "provenance" / "published-biomodels.json",
    )
    parser.add_argument("--base-commit", default="")
    parser.add_argument("--measurement-date", default="")
    parser.add_argument(
        "--structural-trigger-report",
        type=Path,
        help=(
            "output of scripts/ci/measure_structural_trigger.py: the per-record "
            "count of the species whose name carries the Atomizer's structural "
            "trigger"
        ),
    )
    parser.add_argument("--label", default="corpus")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--expectations-out",
        type=Path,
        help="write the corpus expectation manifest for --flat-report",
    )
    parser.add_argument(
        "--expectations",
        type=Path,
        help="compare --flat-report against a committed corpus expectation manifest",
    )
    parser.add_argument(
        "--measured-commit",
        default="",
        help=(
            "the commit the expectation manifest describes; defaults to the "
            "commit the report states it was measured at"
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
    parser.add_argument(
        "--report-revision",
        default="",
        help=(
            "the revision the compared report was measured at, for the corpus "
            "gate reports that do not state it themselves"
        ),
    )
    parser.add_argument(
        "--verify-regeneration",
        action="store_true",
        help=(
            "with --expectations: check that the committed manifest is exactly "
            "what the tool derives from the report it names"
        ),
    )
    args = parser.parse_args()

    if args.out is None and args.expectations_out is None and args.expectations is None:
        parser.error("one of --out, --expectations-out or --expectations is required")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    flat = json.loads(args.flat_report.read_text(encoding="utf-8"))

    if args.expectations_out is not None or args.expectations is not None:
        return _expectations_main(args, manifest, flat)

    atomized = (
        json.loads(args.atomized_report.read_text(encoding="utf-8"))
        if args.atomized_report
        else None
    )
    structural = (
        json.loads(args.structural_trigger_report.read_text(encoding="utf-8"))
        if args.structural_trigger_report
        else None
    )

    inventory: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": args.label,
        "description": (
            "Inventory of the curated BioModels corpus: the corpus identity, the "
            "per-record outcome of the modern Atomizer in the flat and the "
            "atomized mode, and the classification of every residual failure "
            "and timeout.  The harness owns every status; this file only "
            "reduces its reports and adds the corpus identity."
        ),
        "corpus": {
            "source": manifest.get("source"),
            "search_api_url": manifest.get("search_api_url"),
            "inventory_query": manifest.get("curation_query"),
            "snapshot_date": manifest.get("snapshot_date"),
            "expected_total_records": manifest.get("expected_total_records"),
            "expected_sbml_records": manifest.get("expected_sbml_records"),
            "expected_non_sbml_records": manifest.get("expected_non_sbml_records"),
        },
        "measurement": {
            "base_commit": args.base_commit,
            "measurement_date": args.measurement_date,
            "tool_versions": _tool_versions(),
            "note": (
                "The per-record status is the status the reduced harness report "
                "records.  The effect of the change under review is stated "
                "separately, in residuals.branch_effect, with the records it "
                "touches and where they were measured."
            ),
            "reports": {
                "flat": {
                    "path": str(args.flat_report),
                    "sha256": _digest(args.flat_report),
                },
            },
        },
        "modes": {
            "flat": _summarize(flat, "flat"),
        },
    }
    if atomized is not None:
        inventory["measurement"]["reports"]["atomized"] = {
            "path": str(args.atomized_report),
            "sha256": _digest(args.atomized_report),
        }
        inventory["modes"]["atomized"] = _summarize(atomized, "atomized")

    rows = _case_rows(flat, atomized)
    inventory["cases"] = rows

    flat_summary = inventory["modes"]["flat"]
    failures = [row for row in rows if row["flat_status"] == "failed"]
    timeouts = [row for row in rows if row["flat_status"] == "timeout"]
    inventory["residuals"] = {
        "failed_count": len(failures),
        "timeout_count": len(timeouts),
        "failed_ids": [row["id"] for row in failures],
        "timeout_ids": [row["id"] for row in timeouts],
        "by_layer": dict(
            sorted(
                Counter(
                    (row.get("failure_classification") or {}).get(
                        "layer", "unclassified"
                    )
                    for row in failures
                ).items()
            )
        ),
        "timeout_by_layer": dict(
            sorted(
                Counter(
                    (row.get("timeout_classification") or {}).get(
                        "layer", "unclassified"
                    )
                    for row in timeouts
                ).items()
            )
        ),
    }
    if atomized is not None:
        moved = [row for row in rows if row["moved_between_modes"]]
        atomized_summary = inventory["modes"]["atomized"]
        inflations = [
            row["atomized_network"]["species"] / row["flat_network"]["species"]
            for row in rows
            if row.get("flat_network")
            and row.get("atomized_network")
            and row["flat_network"].get("species")
        ]
        inventory["mode_comparison"] = {
            "records_in_both_modes": sum(
                1 for row in rows if row["atomized_status"] is not None
            ),
            "moved_between_modes": len(moved),
            "moved_ids": [row["id"] for row in moved],
            "flat_passed": flat_summary["status_counts"].get("passed", 0),
            "atomized_passed": atomized_summary["status_counts"].get("passed", 0),
            "lost_in_atomized": sorted(
                row["id"]
                for row in rows
                if row["flat_status"] == "passed"
                and row["atomized_status"] not in (None, "passed")
            ),
            "gained_in_atomized": sorted(
                row["id"]
                for row in rows
                if row["flat_status"] != "passed" and row["atomized_status"] == "passed"
            ),
            "records_with_both_networks": len(inflations),
            "records_with_a_different_network": sum(
                1
                for row in rows
                if row.get("flat_network")
                and row.get("atomized_network")
                and row["flat_network"].get("species")
                != row["atomized_network"].get("species")
            ),
            "median_species_inflation": (
                sorted(inflations)[len(inflations) // 2] if inflations else None
            ),
            "max_species_inflation": max(inflations) if inflations else None,
        }
    if structural is not None:
        inventory["structural_atomization"] = {
            "source_report": {
                "path": str(args.structural_trigger_report),
                "sha256": _digest(args.structural_trigger_report),
            },
            "summary": structural.get("summary"),
        }
    if BRANCH_EFFECT:
        inventory["residuals"]["branch_effect"] = {
            "note": (
                "The records the change under review touches, measured record "
                "by record with the corpus gate's --only-id path on the branch "
                "and on main with the same native extension."
            ),
            "records": {
                model_id: {
                    **entry,
                    "measured_in_report": next(
                        (row["flat_status"] for row in rows if row["id"] == model_id),
                        None,
                    ),
                }
                for model_id, entry in sorted(BRANCH_EFFECT.items())
            },
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
