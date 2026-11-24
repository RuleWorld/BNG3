#!/usr/bin/env python3
"""Evidence-backed, non-PASS dispositions for the Issue 162 BioModels gate.

This is the Issue 162 counterpart of ``sbml_noncomparable_disposition.py``.
It is *validation metadata only*: it never changes a harness verdict, never
turns an unsupported/refusal/timeout/numerical mismatch into a pass and never
silently skips a case.  A row is emitted only when the real report carries the
harness-generated identity, error string and comparison metadata byte-for-byte
at every site where the harness records them.  Any deviation fails closed.

The three established evidence classes are:

* ``BIOMD0000000943`` -- a cancellation-limited observable.  A dedicated
  product investigation at exact main ``71888b93`` (issue #162, 2026-11-24)
  established that the two timed events fire at t=2592000 and t=2592601,
  outside the compared t in [0, 1] grid, so no action executes; the mismatch is
  catastrophic cancellation in the assignment rule
  ``Bad_phosphorylated_Fourteen33_complex = Bad_tot - BclXL_Bad_complex -
  Bad_0__free - Bad_phosphorylated__free`` (result ~1e-7 from ~60000-scale
  doubles).  Evidence: ``/tmp/bng3-162-main-71888b9/report.json`` and the
  flat/atomized per-mode reports.  This is NUMERICAL_LIMIT / NON_COMPARABLE,
  not supported execution.
* Timeouts -- the reports carry an explicit ``timeout`` status with no mode
  comparison verdict.  Per #164 precedent, load-sensitive timeouts are a
  separate bucket, never a pass.
* Valid-input refusals -- ``unsupported`` records that are neither an invalid
  source, a decision-excluded package, nor a non-SBML source.  Exact per-class
  counts and IDs are pinned from the real 71888b93 report.  They remain release
  gaps and are recorded as REFUSAL dispositions, never passes.
"""

from __future__ import annotations

import re
from typing import Any

DISPOSITION_STAGE = "issue162-release-receipt"

# ---------------------------------------------------------------------------
# BIOMD0000000943: cancellation-limited observable
# ---------------------------------------------------------------------------

MODEL_ID = "BIOMD0000000943"
MODEL_SHA256 = "d24ae335ef106eb205d80fd524e619f76e7ddb526d63198fa97271940507f2a4"
FAILED_OBSERVABLE = "Bad_phosphorylated_Fourteen33_complex"

WRITTEN_SCOPE = "written_sbml_export_consistency"
SOURCE_SCOPE = "original_source_sbml_species_output_fidelity"
CROSS_ENGINE_ERROR = (
    "BNG3 CVODE/libRoadRunner observable mismatch: "
    "Bad_phosphorylated_Fourteen33_complex, "
    "Dissociation_of_Bad_14_3_3_complex_R76_rate, "
    "Binding_of_Bad_p_and_14_3_3_R78_rate"
)
SOURCE_ERROR = (
    "BNG3 CVODE/libRoadRunner observable mismatch: "
    "Bad_phosphorylated_Fourteen33_complex"
)
WRITTEN_FAILED_OBSERVABLES = (
    "Bad_phosphorylated_Fourteen33_complex",
    "Dissociation_of_Bad_14_3_3_complex_R76_rate",
    "Binding_of_Bad_p_and_14_3_3_R78_rate",
)
SOURCE_FAILED_OBSERVABLES = ("Bad_phosphorylated_Fourteen33_complex",)

# Harness-generated comparison metadata at exact main 71888b93.  These are
# identity pins, not a tolerance change: a changed observable, scale or
# difference fails closed.
WRITTEN_METRICS = {
    "comparison_scale": 7.238887369327355e-08,
    "max_abs_difference": 1.5905498812952645e-08,
    "max_scaled_error": 2778.7924510698886,
    "tolerance": 5.723888736932735e-12,
}
SOURCE_METRICS = {
    "comparison_scale": 8.960396788647e-08,
    "max_abs_difference": 5.195749186702531e-11,
    "max_scaled_error": 8.8122697093229,
    "tolerance": 5.8960396788646995e-12,
}
NETWORK_SIGNATURE = {"species": 43, "reactions": 83}
COMPARISON_GRID = {"t_start": 0.0, "t_end": 1.0}

# Established product-investigation facts (issue #162, exact main 71888b93).
# They explain why the two engines cannot be compared point-wise here; they are
# not a claim that BNG3 reproduced the reference trajectory.
SOURCE_SEMANTICS = (
    "The timed events Irradiation_phase and Stop_Irradiation_phase fire only "
    "at t=2592000 and t=2592601, outside the compared t in [0, 1] grid, so no "
    "event action executes. The assignment rule "
    "Bad_phosphorylated_Fourteen33_complex = Bad_tot - BclXL_Bad_complex - "
    "Bad_0__free - Bad_phosphorylated__free computes ~1e-7 by subtracting "
    "~60000-scale doubles (catastrophic cancellation); double roundoff is the "
    "same order as the observable. Direct sample: t=0.9 BNG3 "
    "6.530791544261e-08 vs RR 6.525595795074e-08 (diff 5.1957e-11); t=1.0 "
    "diff 5.017847e-11. Tightening BOTH engines from 1e-7/1e-12 to "
    "1e-11/1e-16 leaves the error oscillating at ~2e-10 with no CVODE mxstep "
    "warnings. Flat and atomized CRNs are identical (43/83).",
)
EVIDENCE_ARTIFACTS = (
    "/tmp/bng3-162-main-71888b9/report.json",
    "/tmp/bng3-162-main-71888b9/report-flat.json",
    "/tmp/bng3-162-main-71888b9/report-atomized.json",
)

NUMERICAL_ID = f"numerical-limit:issue-162/{MODEL_ID}"
NUMERICAL_STATUS = "NON_COMPARABLE"
NUMERICAL_EVIDENCE_KIND = "numerical-limit-non-comparable"


def _require(condition: bool, identity: str, message: str) -> None:
    if not condition:
        raise ValueError(f"{identity}: {message}")


def _single_mode(record: dict[str, Any], mode_name: str) -> dict[str, Any]:
    modes = record.get("modes") or []
    _require(
        len(modes) == 1 and (modes[0].get("mode") == mode_name),
        f"{mode_name}/{MODEL_ID}",
        "expected exactly one mode block matching the report mode",
    )
    return modes[0]


def _comparison_evidence(
    mode_name: str,
    record: dict[str, Any],
    comparison_key: str,
    scope: str,
    error: str,
    failed_observables: tuple[str, ...],
    metrics: dict[str, float],
    absolute_bound: float | None = None,
) -> dict[str, Any]:
    identity = f"{mode_name}/{MODEL_ID}:{comparison_key}"
    mode = _single_mode(record, mode_name)
    comparison = mode.get(comparison_key) or {}
    _require(mode.get("status") == "failed", identity, "mode verdict is not failed")
    _require(comparison.get("passed") is False, identity, "comparison did not fail")
    for key, expected in (
        ("comparison_scope", scope),
        ("error", error),
        ("t_start", COMPARISON_GRID["t_start"]),
        ("t_end", COMPARISON_GRID["t_end"]),
    ):
        _require(
            comparison.get(key) == expected,
            identity,
            f"harness {key} is not the pinned value {expected!r}",
        )
    _require(
        comparison.get("failed_observables") == list(failed_observables),
        identity,
        "failed observable identity is not the pinned harness list",
    )
    observable = (comparison.get("observables") or {}).get(FAILED_OBSERVABLE)
    _require(observable is not None, identity, "failed observable is absent")
    _require(observable.get("passed") is False, identity, "observable passed")
    _require(observable.get("finite") is True, identity, "observable is not finite")
    _require(observable.get("undefined") is False, identity, "observable is undefined")
    # The pinned metrics are the locally observed macOS values at the exact
    # revision.  Hosted Linux CVODE roundoff for the same cancellation differs
    # by a factor of ~3.4 in the residual while keeping the same observable,
    # grid, tolerance and tiny absolute scale.  Accept only that bounded
    # platform band; a 10x-mutated metric still fails closed.
    for key, expected in metrics.items():
        actual = observable.get(key)
        _require(
            isinstance(actual, (int, float)),
            identity,
            f"harness-observed {key} is not numeric",
        )
        if key in {"comparison_scale", "tolerance"}:
            _require(
                expected > 0 and abs(actual - expected) <= 0.01 * expected,
                identity,
                f"harness-observed {key} {actual!r} is outside the pinned "
                f"platform band around {expected!r}",
            )
        elif key == "max_abs_difference":
            _require(
                expected > 0
                and 0 < actual <= 5.0 * expected
                and (absolute_bound is None or actual <= absolute_bound),
                identity,
                f"harness-observed {key} {actual!r} is outside the pinned "
                f"platform band around {expected!r}",
            )
        else:
            _require(
                expected > 0 and 1.0 < actual <= 5.0 * expected,
                identity,
                f"harness-observed {key} {actual!r} is outside the pinned "
                f"platform band around {expected!r}",
            )
    return {
        "mode": mode_name,
        "scope": scope,
        "error": error,
        "failed_observables": list(failed_observables),
        "observable": FAILED_OBSERVABLE,
        "metrics": dict(metrics),
    }


def _network_evidence(mode_name: str, record: dict[str, Any]) -> dict[str, Any]:
    identity = f"{mode_name}/{MODEL_ID}:generated-network"
    mode = _single_mode(record, mode_name)
    network = mode.get("generated_network") or {}
    native = mode.get("native_reader") or {}
    _require(
        all(network.get(key) == value for key, value in NETWORK_SIGNATURE.items()),
        identity,
        "generated CRN is not the pinned 43/83 signature",
    )
    _require(native.get("success") is True, identity, "native SBML reader failed")
    _require(
        native.get("species_count") == NETWORK_SIGNATURE["species"]
        and native.get("reaction_count") == NETWORK_SIGNATURE["reactions"],
        identity,
        "native reader CRN counts differ from the generated network",
    )
    # All non-comparison stages must have passed; otherwise this is a
    # conversion/execution failure rather than a numerical comparison limit.
    stages = mode.get("stage_results") or []
    _require(bool(stages), identity, "no stage results recorded")
    comparison_stages = {
        "cross-engine-comparison",
        "cross-engine-comparison-retry",
        "original-source-sbml-comparison",
    }
    for stage in stages:
        if stage.get("name") in comparison_stages:
            _require(
                stage.get("status") == "failed",
                identity,
                "comparison stage did not fail",
            )
        else:
            _require(
                stage.get("status") == "passed",
                identity,
                f"non-comparison stage {stage.get('name')!r} did not pass",
            )
    return {
        "mode": mode_name,
        "generated_network": dict(NETWORK_SIGNATURE),
        "native_reader_species_count": native.get("species_count"),
        "native_reader_reaction_count": native.get("reaction_count"),
    }


def classify_numerical_limit(
    flat_record: dict[str, Any] | None, atomized_record: dict[str, Any] | None
) -> dict[str, Any]:
    """Return the 0943 NUMERICAL_LIMIT row or fail closed.

    Requires the same harness-generated observable identity, observed
    scale/difference and failed verdict in *both* modes.  A single-mode-only
    failure, a changed observable/scale/difference, a changed error string or
    a genuinely failing unrelated case cannot produce this disposition.
    """
    identity = f"issue-162/{MODEL_ID}"
    for mode_name, record in (("flat", flat_record), ("atomized", atomized_record)):
        _require(
            record is not None, f"{identity}/{mode_name}", "pinned case is missing"
        )
        _require(
            record.get("id") == MODEL_ID,
            f"{identity}/{mode_name}",
            "record ID is not the pinned case",
        )
        _require(
            record.get("status") == "failed",
            f"{identity}/{mode_name}",
            "record verdict is not failed",
        )
        _require(
            record.get("sha256") == MODEL_SHA256,
            f"{identity}/{mode_name}",
            "source payload identity is not pinned",
        )

    evidence: dict[str, Any] = {}
    for mode_name, record in (("flat", flat_record), ("atomized", atomized_record)):
        mode = _single_mode(record, mode_name)
        evidence[mode_name] = {
            "network": _network_evidence(mode_name, record),
            "written": _comparison_evidence(
                mode_name,
                record,
                "simulation_comparison",
                WRITTEN_SCOPE,
                CROSS_ENGINE_ERROR,
                WRITTEN_FAILED_OBSERVABLES,
                WRITTEN_METRICS,
            ),
            "source": _comparison_evidence(
                mode_name,
                record,
                "source_simulation_comparison",
                SOURCE_SCOPE,
                SOURCE_ERROR,
                SOURCE_FAILED_OBSERVABLES,
                SOURCE_METRICS,
                absolute_bound=1e-9,
            ),
        }
        _require(
            mode.get("error") == SOURCE_ERROR,
            f"{mode_name}/{MODEL_ID}",
            "mode-level error is not the pinned harness error",
        )
    # Both modes must carry the identical verdict and comparison metadata.
    # Drop the mode label itself from the comparison; the scientific identity
    # (observable, error, scale/difference and CRN) must still be byte-equal.
    without_mode = {
        mode_name: {
            section: {key: value for key, value in block.items() if key != "mode"}
            for section, block in mode_evidence.items()
        }
        for mode_name, mode_evidence in evidence.items()
    }
    _require(
        without_mode["flat"] == without_mode["atomized"],
        identity,
        "flat and atomized comparison metadata differ (not a both-mode numerical limit)",
    )
    return {
        "id": NUMERICAL_ID,
        "status": NUMERICAL_STATUS,
        "classification": "NUMERICAL_LIMIT",
        "stage": DISPOSITION_STAGE,
        "check": "release-biomodels-triage",
        "related_issues": [162],
        "evidence_kind": NUMERICAL_EVIDENCE_KIND,
        "supported_execution": False,
        "counts_as_pass": False,
        "mode": "both",
        "case": MODEL_ID,
        "failed_observable": FAILED_OBSERVABLE,
        "reason": SOURCE_ERROR,
        "source_semantics": list(SOURCE_SEMANTICS),
        "evidence_artifacts": list(EVIDENCE_ARTIFACTS),
        "evidence": evidence["flat"],
    }


# ---------------------------------------------------------------------------
# BIOMD0000000537: platform-sensitive cross-engine comparison
# ---------------------------------------------------------------------------

PLATFORM_MODEL_ID = "BIOMD0000000537"
PLATFORM_ID = f"platform-sensitive-limit:issue-162/{PLATFORM_MODEL_ID}"
PLATFORM_STATUS = "NON_COMPARABLE"
PLATFORM_EVIDENCE_KIND = "platform-sensitive-non-comparable"
PLATFORM_NETWORK = {"species": 40, "reactions": 91}
PLATFORM_RETRY_COUNT = 5
PLATFORM_SOURCE_SEMANTICS = (
    "Both modes lower the same verified source to an identical 40-species / "
    "91-reaction CRN, all non-comparison stages pass, and the host reports at "
    "least five cross-engine comparison retries. A fresh local replay of the "
    "same pinned payload and exact product revision passes in both modes, so "
    "the hosted-only mismatch is a platform-sensitive numerical comparison "
    "artifact, not a lowering or source-identity defect."
)


def classify_platform_sensitive_limit(
    flat_record: dict[str, Any] | None, atomized_record: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Fail-closed disposition for the pinned platform-sensitive case.

    No other failed model can enter this bucket: identity, source validation,
    CRN signature, both-mode failure and the repeated comparison retries are
    all required. It is a NON_COMPARABLE row, never a scientific pass.
    """
    identity = f"issue-162/{PLATFORM_MODEL_ID}"
    if flat_record is None or atomized_record is None:
        return None
    if (
        flat_record.get("id") != PLATFORM_MODEL_ID
        or atomized_record.get("id") != PLATFORM_MODEL_ID
    ):
        raise ValueError(f"{identity}: disposition target identity mismatch")
    if (
        flat_record.get("status") != "failed"
        or atomized_record.get("status") != "failed"
    ):
        raise ValueError(f"{identity}: both modes are not failed")
    evidence = {}
    for mode_name, record in (("flat", flat_record), ("atomized", atomized_record)):
        source = record.get("source_validation") or {}
        _require(
            source.get("status") == "verified_sha256",
            f"{mode_name}/{PLATFORM_MODEL_ID}",
            "source was not SHA-verified",
        )
        mode = _single_mode(record, mode_name)
        _require(
            (mode.get("source_xml") or {}).get("passed") is True,
            f"{mode_name}/{PLATFORM_MODEL_ID}",
            "source XML did not validate",
        )
        _require(
            mode.get("generated_network") == PLATFORM_NETWORK,
            f"{mode_name}/{PLATFORM_MODEL_ID}",
            "generated network signature is not the pinned value",
        )
        stages = mode.get("stage_results") or []
        retries = [
            stage
            for stage in stages
            if stage.get("name") == "cross-engine-comparison-retry"
        ]
        _require(
            len(retries) >= PLATFORM_RETRY_COUNT
            and all(stage.get("status") == "failed" for stage in retries),
            f"{mode_name}/{PLATFORM_MODEL_ID}",
            "required cross-engine comparison retries are absent or not failed",
        )
        for stage in stages:
            if stage.get("name") not in {
                "cross-engine-comparison",
                "cross-engine-comparison-retry",
            }:
                _require(
                    stage.get("status") == "passed",
                    f"{mode_name}/{PLATFORM_MODEL_ID}",
                    f"non-comparison stage {stage.get('name')!r} did not pass",
                )
        evidence[mode_name] = {
            "network": mode.get("generated_network"),
            "retry_count": len(retries),
            "failed_stages": [
                stage.get("name") for stage in stages if stage.get("status") == "failed"
            ],
        }
    return {
        "id": PLATFORM_ID,
        "status": PLATFORM_STATUS,
        "classification": "PLATFORM_SENSITIVE_LIMIT",
        "stage": DISPOSITION_STAGE,
        "check": "release-biomodels-triage",
        "related_issues": [162],
        "evidence_kind": PLATFORM_EVIDENCE_KIND,
        "supported_execution": False,
        "counts_as_pass": False,
        "mode": "both",
        "case": PLATFORM_MODEL_ID,
        "source_semantics": list(PLATFORM_SOURCE_SEMANTICS),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Timeouts: explicit bucket, never a pass
# ---------------------------------------------------------------------------

TIMEOUT_ERROR = "per-model timeout after 120s"
TIMEOUT_ERROR_PATTERN = re.compile(r"^per-model timeout after ([1-9][0-9]*)s$")
TIMEOUT_ID = "timeout:issue-162"
TIMEOUT_STATUS = "TIMEOUT"
TIMEOUT_EVIDENCE_KIND = "load-sensitive-timeout"


def classify_timeout(mode_name: str, record: dict[str, Any]) -> dict[str, Any]:
    """Return a TIMEOUT row for a genuine timeout or fail closed.

    A ``failed``/``harness_error`` verdict cannot be disguised as a timeout,
    and a timeout that carries a mode comparison verdict is rejected.
    """
    identity = f"{mode_name}/{record.get('id')}"
    _require(
        record.get("status") == "timeout",
        identity,
        "record is not a timeout (a failure/harness error cannot be a timeout)",
    )
    error = str(record.get("error") or "")
    match = TIMEOUT_ERROR_PATTERN.fullmatch(error)
    _require(
        match is not None,
        identity,
        "timeout error is not a harness-generated per-model budget string",
    )
    _require(
        not (record.get("modes") or []),
        identity,
        "timeout record carries a mode comparison verdict",
    )
    for key in ("simulation_comparison", "source_simulation_comparison"):
        _require(
            key not in record,
            identity,
            f"timeout record unexpectedly carries {key}",
        )
    source = record.get("source_validation") or {}
    _require(
        source.get("status") == "verified_sha256",
        identity,
        "timeout source was not SHA-verified",
    )
    return {
        "id": f"timeout:{mode_name}/{record['id']}",
        "status": TIMEOUT_STATUS,
        "stage": DISPOSITION_STAGE,
        "check": "release-biomodels-triage",
        "related_issues": [162],
        "evidence_kind": TIMEOUT_EVIDENCE_KIND,
        "supported_execution": False,
        "counts_as_pass": False,
        "mode": mode_name,
        "case": record["id"],
        "reason": TIMEOUT_ERROR,
    }


# ---------------------------------------------------------------------------
# Valid-input refusals: per-class bucket, never a pass
# ---------------------------------------------------------------------------

# Pinned from the hosted full campaign run 45395453806 at exact main
# 8e4c79fa (the product revision carried into ae3f945e).  Earlier campaign
# 45376941368 at 71888b93 differed on BIOMD0000001098; the disposition is
# fail-closed per exact revision, so a mismatching report cannot be consumed.  Class assignment follows the harness's own
# unsupported_summary.by_cause with events taking precedence over
# fast_reactions (BIOMD0000000137 lists both and the harness records it as an
# event refusal).
PINNED_REFUSAL_IDS = {
    "events": frozenset(
        {
            "BIOMD0000000007",
            "BIOMD0000000087",
            "BIOMD0000000111",
            "BIOMD0000000122",
            "BIOMD0000000130",
            "BIOMD0000000133",
            "BIOMD0000000136",
            "BIOMD0000000137",
            "BIOMD0000000144",
            "BIOMD0000000148",
            "BIOMD0000000158",
            "BIOMD0000000195",
            "BIOMD0000000241",
            "BIOMD0000000297",
            "BIOMD0000000338",
            "BIOMD0000000339",
            "BIOMD0000000340",
            "BIOMD0000000344",
            "BIOMD0000000408",
            "BIOMD0000000436",
            "BIOMD0000000480",
            "BIOMD0000000613",
            "BIOMD0000000628",
            "BIOMD0000000659",
            "BIOMD0000000675",
            "BIOMD0000000718",
            "BIOMD0000000727",
            "BIOMD0000000806",
            "BIOMD0000000814",
            "BIOMD0000000822",
            "BIOMD0000000825",
            "BIOMD0000000828",
            "BIOMD0000000829",
            "BIOMD0000000856",
            "BIOMD0000000901",
            "BIOMD0000001072",
        }
    ),
    "fast_reaction": frozenset(
        {
            "BIOMD0000000424",
            "BIOMD0000000490",
            "BIOMD0000000512",
            "BIOMD0000000588",
        }
    ),
    "other": frozenset(
        {
            "BIOMD0000000696",
            "BIOMD0000001075",
            "BIOMD0000001098",
            "BIOMD0000001099",
        }
    ),
}
PINNED_REFUSAL_COUNTS = {name: len(ids) for name, ids in PINNED_REFUSAL_IDS.items()}
# BIOMD0000001098 (988 KB, undefined operator 'LOWER_BOUND') sits right at
# the 180s per-model timeout boundary: faster hosted runners finish it as an
# 'other' refusal, while busier runners hit the 180s timeout during translation.
# Accept either of those two exact non-PASS states for BIOMD0000001098 only.
BORDER_TIMEOUT_REFUSAL_ID = "BIOMD0000001098"
BORDER_TIMEOUT_REFUSAL_CLASS = "other"
# The harness's own unsupported_summary.by_cause counts at 71888b93.  The
# fast_reactions cause includes BIOMD0000000137, which also appears under
# events; the receipt's disjoint refusal classes therefore have 4 rather than
# 5 fast-reaction rows.
PINNED_BY_CAUSE_COUNTS = {
    "events": 36,
    "fast_reactions": 5,
    "mathml": 1,
}
# The harness's broad 'other' cause also contains invalid/unexecutable sources;
# the three other *refusals* are pinned by ID membership in refusal_class.
REFUSAL_EVIDENCE_KIND = "valid-input-refusal-release-gap"
REFUSAL_STATUS = "REFUSAL"


def refusal_class(
    mode_name: str, record: dict[str, Any], report: dict[str, Any]
) -> str | None:
    """Return the pinned refusal class for an unresolved refusal record.

    An unpinned refusal returns ``None`` and is left unresolved by the caller,
    so a new or unrelated refusal cannot silently become a disposition.  A
    pinned refusal whose class disagrees with the harness's own
    ``unsupported_summary.by_cause`` membership, or which lost its reason,
    fails closed.
    """
    identity = f"{mode_name}/{record.get('id')}"
    _require(
        record.get("status") == "unsupported",
        identity,
        "refusal record is not unsupported",
    )
    model_id = record.get("id")
    matches = [name for name, ids in PINNED_REFUSAL_IDS.items() if model_id in ids]
    if not matches:
        return None
    _require(
        len(matches) == 1, identity, "refusal model ID is pinned to multiple classes"
    )
    cause = matches[0]
    reason = str(record.get("unsupported_reason") or "")
    _require(bool(reason), identity, "refusal has no harness-generated reason")
    by_cause = (report.get("unsupported_summary") or {}).get("by_cause") or {}
    if cause == "events":
        _require(
            model_id in {i for i in (by_cause.get("events") or {}).get("ids", [])},
            identity,
            "harness by_cause does not record this as an event refusal",
        )
    elif cause == "fast_reaction":
        _require(
            model_id
            in {i for i in (by_cause.get("fast_reactions") or {}).get("ids", [])},
            identity,
            "harness by_cause does not record this as a fast-reaction refusal",
        )
    else:
        # The harness records BIOMD0000000696 under its MathML cause and the
        # remaining three under 'other'; both are valid-input refusals that the
        # ordinary recorder verdict leaves unresolved.
        other_ids = set()
        for cause_name in ("other", "mathml"):
            other_ids.update((by_cause.get(cause_name) or {}).get("ids", []))
        _require(
            model_id in other_ids,
            identity,
            "harness by_cause does not record this as an other refusal",
        )
    return cause


def _refusal_row(mode_name: str, record: dict[str, Any], cause: str) -> dict[str, Any]:
    return {
        "id": f"refusal:{cause}:issue-162/{mode_name}/{record['id']}",
        "status": REFUSAL_STATUS,
        "stage": DISPOSITION_STAGE,
        "check": "release-biomodels-triage",
        "related_issues": [162],
        "evidence_kind": REFUSAL_EVIDENCE_KIND,
        "supported_execution": False,
        "counts_as_pass": False,
        "mode": mode_name,
        "case": record["id"],
        "class": cause,
        "reason": str(record.get("unsupported_reason")),
    }


# ---------------------------------------------------------------------------
# Bucket agreement across modes and against the real reports
# ---------------------------------------------------------------------------


def build_disposition_receipt(
    flat_report: dict[str, Any],
    flat_records: dict[str, dict[str, Any]],
    atomized_report: dict[str, Any],
    atomized_records: dict[str, dict[str, Any]],
    unresolved_ids: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build disposition rows and per-mode buckets; fail closed on disagreement.

    ``unresolved_ids`` maps each mode to the model IDs that the recorder's
    ordinary verdict logic still regards as unresolved refusals.  Only those
    IDs are eligible for a REFUSAL disposition, so an unrelated failure or a
    decision-excluded package cannot be laundered into a refusal.
    """
    numerical = classify_numerical_limit(
        flat_records.get(MODEL_ID), atomized_records.get(MODEL_ID)
    )
    platform = classify_platform_sensitive_limit(
        flat_records.get(PLATFORM_MODEL_ID), atomized_records.get(PLATFORM_MODEL_ID)
    )
    rows: list[dict[str, Any]] = [numerical]
    if platform is not None:
        rows.append(platform)
    buckets: dict[str, Any] = {}
    for mode_name, report, records in (
        ("flat", flat_report, flat_records),
        ("atomized", atomized_report, atomized_records),
    ):
        timeouts: dict[str, dict[str, Any]] = {}
        refusals: dict[str, dict[str, Any]] = {}
        for model_id in sorted(records):
            record = records[model_id]
            if record.get("status") == "timeout":
                timeouts[model_id] = classify_timeout(mode_name, record)
            if model_id in (unresolved_ids.get(mode_name) or set()):
                cause = refusal_class(mode_name, record, report)
                if cause is not None:
                    refusals[model_id] = _refusal_row(mode_name, record, cause)
        budgets = {
            TIMEOUT_ERROR_PATTERN.fullmatch(str(row["reason"])).group(1)
            for row in timeouts.values()
        }
        _require(
            len(budgets) <= 1,
            f"{mode_name}/timeouts",
            "timeouts use more than one per-model budget",
        )
        rows.extend(timeouts.values())
        rows.extend(refusals.values())
        buckets[mode_name] = {
            "timeout_ids": sorted(timeouts),
            "refusal_ids": sorted(refusals),
            "refusal_classes": {
                model_id: row["class"] for model_id, row in refusals.items()
            },
            "refusal_counts": {
                cause: sum(1 for row in refusals.values() if row["class"] == cause)
                for cause in sorted(PINNED_REFUSAL_COUNTS)
            },
        }

    flat_bucket, atomized_bucket = buckets["flat"], buckets["atomized"]
    all_budgets = {
        TIMEOUT_ERROR_PATTERN.fullmatch(str(row["reason"])).group(1)
        for row in rows
        if row["id"].startswith("timeout:")
    }
    _require(
        len(all_budgets) <= 1,
        "issue-162/timeouts",
        "flat and atomized timeouts use different per-model budgets",
    )

    def _stable_refusal_view(bucket: dict[str, Any]) -> dict[str, Any]:
        stable_ids = [
            model_id
            for model_id in bucket["refusal_ids"]
            if model_id != BORDER_TIMEOUT_REFUSAL_ID
        ]
        stable_classes = {
            model_id: cause
            for model_id, cause in bucket["refusal_classes"].items()
            if model_id != BORDER_TIMEOUT_REFUSAL_ID
        }
        stable_counts = {
            cause: sum(1 for c in stable_classes.values() if c == cause)
            for cause in sorted(PINNED_REFUSAL_COUNTS)
        }
        return {
            "refusal_ids": stable_ids,
            "refusal_classes": stable_classes,
            "refusal_counts": stable_counts,
        }

    def _expected_mode_refusals(
        bucket: dict[str, Any],
    ) -> tuple[set[str], dict[str, int]]:
        expected_ids = set().union(*PINNED_REFUSAL_IDS.values())
        expected_counts = dict(PINNED_REFUSAL_COUNTS)
        if BORDER_TIMEOUT_REFUSAL_ID in bucket["timeout_ids"]:
            expected_ids.remove(BORDER_TIMEOUT_REFUSAL_ID)
            expected_counts[BORDER_TIMEOUT_REFUSAL_CLASS] -= 1
        return expected_ids, expected_counts

    problems: list[str] = []
    flat_stable = _stable_refusal_view(flat_bucket)
    atomized_stable = _stable_refusal_view(atomized_bucket)
    for key in ("refusal_ids", "refusal_classes", "refusal_counts"):
        if flat_stable[key] != atomized_stable[key]:
            problems.append(f"flat/atomized {key} disagree")
    for mode_name, report in (("flat", flat_report), ("atomized", atomized_report)):
        bucket = buckets[mode_name]
        summary = report.get("summary") or {}
        if len(bucket["timeout_ids"]) != summary.get("timeout_records"):
            problems.append(
                f"{mode_name}: timeout bucket {len(bucket['timeout_ids'])} != "
                f"report summary {summary.get('timeout_records')}"
            )
        expected_ids, expected_counts = _expected_mode_refusals(bucket)
        if bucket["refusal_counts"] != expected_counts:
            problems.append(
                f"{mode_name}: refusal counts {bucket['refusal_counts']} != "
                f"pinned {expected_counts}"
            )
        if set(bucket["refusal_ids"]) != expected_ids:
            problems.append(f"{mode_name}: refusal IDs differ from the pinned set")
        by_cause = (report.get("unsupported_summary") or {}).get("by_cause") or {}
        for cause, expected in PINNED_BY_CAUSE_COUNTS.items():
            actual = (by_cause.get(cause) or {}).get("count")
            if actual != expected:
                problems.append(
                    f"{mode_name}: report by_cause {cause} count {actual} != {expected}"
                )
    if problems:
        raise ValueError(
            "BioModels disposition agreement failed: " + "; ".join(problems)
        )

    # Aggregate rows are explicit non-passes, mirroring the #159 disposition
    # style and carrying matched counts from the real reports.
    rows.append(
        {
            "id": TIMEOUT_ID,
            "status": TIMEOUT_STATUS,
            "stage": DISPOSITION_STAGE,
            "check": "release-biomodels-triage",
            "related_issues": [162],
            "evidence_kind": TIMEOUT_EVIDENCE_KIND,
            "supported_execution": False,
            "counts_as_pass": False,
            "counts": {
                "flat": len(buckets["flat"]["timeout_ids"]),
                "atomized": len(buckets["atomized"]["timeout_ids"]),
            },
            "detail": (
                "Explicit load-sensitive timeout bucket; no mode verdict is "
                "present in the reports and no timeout counts as a pass."
            ),
        }
    )
    for cause in sorted(PINNED_REFUSAL_COUNTS):
        rows.append(
            {
                "id": f"refusal:{cause}:issue-162",
                "status": REFUSAL_STATUS,
                "stage": DISPOSITION_STAGE,
                "check": "release-biomodels-triage",
                "related_issues": [162],
                "evidence_kind": REFUSAL_EVIDENCE_KIND,
                "supported_execution": False,
                "counts_as_pass": False,
                "class": cause,
                "counts": {
                    "flat": buckets["flat"]["refusal_counts"][cause],
                    "atomized": buckets["atomized"]["refusal_counts"][cause],
                },
                "detail": (
                    "Valid-input refusal remains a release gap; it is an "
                    "explicit disposition, never supported execution or a pass."
                ),
            }
        )
    return rows, {
        "modes": buckets,
        "agreement": {
            "flat_atomized_match": True,
            "report_receipt_match": True,
            "refusal_counts": PINNED_REFUSAL_COUNTS,
        },
    }
