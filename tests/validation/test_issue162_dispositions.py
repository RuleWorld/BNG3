"""Negative controls for the Issue 162 evidence-backed dispositions.

Mirroring the Issue 159 NON-COMPARABLE controls, these tests prove the #162
dispositions are narrow: the cancellation-limited ``BIOMD0000000943`` row is
emitted only with the harness-generated observable identity, scale/difference
and the same verdict in both modes; timeouts and valid-input refusals are
explicit non-PASS buckets; and a changed observable, a changed scale/difference,
a single-mode-only failure, an unrelated genuine failure or a mismatched count
fails closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
from scripts.ci import sbml_162_disposition as disp

RECORDER_PATH = ROOT / "scripts/ci/record_issue162_release.py"
SPEC = importlib.util.spec_from_file_location("recorder162_under_test", RECORDER_PATH)
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)

COMMIT = "a" * 40
NATIVE = "b" * 64
OTHER_ID = "BIOMD0000000001"


def _pinned_observables():
    def entry(metrics):
        return {
            "finite": True,
            "undefined": False,
            "undefined_at": [],
            **metrics,
            "passed": False,
        }

    return (
        {disp.FAILED_OBSERVABLE: entry(disp.WRITTEN_METRICS)},
        {disp.FAILED_OBSERVABLE: entry(disp.SOURCE_METRICS)},
    )


def _pinned_record(mode_name, *, status="failed", failed=None, metrics=None):
    written_obs, source_obs = _pinned_observables()
    if metrics is not None:
        scale, difference = metrics
        source_obs[disp.FAILED_OBSERVABLE]["comparison_scale"] = scale
        source_obs[disp.FAILED_OBSERVABLE]["max_abs_difference"] = difference
    if failed is not None:
        source_obs[failed] = source_obs.pop(disp.FAILED_OBSERVABLE)
        source_obs[failed]["passed"] = False

    comparison_stages = {
        "cross-engine-comparison",
        "cross-engine-comparison-retry",
        "original-source-sbml-comparison",
    }
    stages = [
        {
            "name": name,
            "status": "passed" if name not in comparison_stages else "failed",
            **({"error": disp.SOURCE_ERROR} if name in comparison_stages else {}),
        }
        for name in (
            "source-xml-validation",
            "source-sbml-parse",
            "atomizer-translation",
            "network-generation",
            "sbml-export",
            "written-sbml-validation",
            "roundtrip-sbml-parse",
            "roundtrip-atomizer-translation",
            "roundtrip-network-generation",
            "native-sbml-readback",
            "cross-engine-comparison",
            "cross-engine-comparison-retry",
            "original-source-sbml-comparison",
        )
    ]
    mode = {
        "mode": mode_name,
        "status": "failed" if status == "failed" else status,
        "error": disp.SOURCE_ERROR,
        "generated_network": dict(disp.NETWORK_SIGNATURE),
        "native_reader": {
            "success": True,
            "species_count": 43,
            "reaction_count": 83,
        },
        "stage_results": stages,
        "simulation_comparison": {
            "passed": False,
            "comparison_scope": disp.WRITTEN_SCOPE,
            "error": disp.CROSS_ENGINE_ERROR,
            "failed_observables": list(disp.WRITTEN_FAILED_OBSERVABLES),
            "t_start": 0.0,
            "t_end": 1.0,
            "observables": written_obs,
        },
        "source_simulation_comparison": {
            "passed": False,
            "comparison_scope": disp.SOURCE_SCOPE,
            "error": disp.SOURCE_ERROR,
            "failed_observables": list(disp.SOURCE_FAILED_OBSERVABLES),
            "t_start": 0.0,
            "t_end": 1.0,
            "observables": source_obs,
        },
    }
    return {
        "id": disp.MODEL_ID,
        "sha256": disp.MODEL_SHA256,
        "status": status,
        "modes": [mode],
    }


def _pinned_pair():
    return (
        _pinned_record("flat"),
        _pinned_record("atomized"),
    )


def _timeout_record(mode_name, *, status="timeout", error=None, modes=None):
    record = {
        "id": "BIOMD0000000497",
        "status": status,
        "error": disp.TIMEOUT_ERROR if error is None else error,
        "modes": [] if modes is None else modes,
        "source_validation": {"status": "verified_sha256"},
    }
    return record


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refusal_fixtures(mode_name):
    """The full 39 pinned refusal records plus the harness by_cause view."""
    by_cause = {
        "events": {"count": 31, "ids": sorted(disp.PINNED_REFUSAL_IDS["events"])},
        "fast_reactions": {
            "count": 5,
            "ids": sorted(
                disp.PINNED_REFUSAL_IDS["fast_reaction"] | {"BIOMD0000000137"}
            ),
        },
        "other": {
            "count": 3,
            "ids": sorted(disp.PINNED_REFUSAL_IDS["other"] - {"BIOMD0000000696"}),
        },
        "mathml": {"count": 1, "ids": ["BIOMD0000000696"]},
    }
    records = []
    for model_id in sorted(set().union(*disp.PINNED_REFUSAL_IDS.values())):
        records.append(
            {
                "id": model_id,
                "format": "SBML",
                "filename": f"{model_id}.xml",
                "sha256": "e" * 64,
                "status": "unsupported",
                "unsupported_reason": "pinned valid-input refusal",
                "source_artifact": {"sha256": "e" * 64},
                "modes": [{"mode": mode_name}],
            }
        )
    return records, by_cause


def _write_full_inputs(tmp_path, *, other_status="passed"):
    """Minimal inventory/bundle/reports for recorder-level negative controls."""
    model_943 = {
        "id": disp.MODEL_ID,
        "format": "SBML",
        "filename": "Hat2016.xml",
        "sha256": disp.MODEL_SHA256,
    }
    other = {
        "id": OTHER_ID,
        "format": "SBML",
        "filename": "other.xml",
        "sha256": "c" * 64,
    }
    refusal_records, by_cause = _refusal_fixtures("flat")
    refusal_models = [
        {
            "id": row["id"],
            "format": row["format"],
            "filename": row["filename"],
            "sha256": row["sha256"],
        }
        for row in refusal_records
    ]
    models = [model_943, other, *refusal_models]
    inventory_hash = _write_json(
        tmp_path / "inventory.json", {"matches": len(models), "models": models}
    )
    bundle_hash = _write_json(
        tmp_path / "bundle.json",
        {
            "bundle_sha256": "d" * 64,
            "inventory_sha256": inventory_hash,
            "payload_count": len(models),
            "records": models,
        },
    )
    receipt_path = tmp_path / "receipt.json"
    _write_json(
        receipt_path,
        {
            "status": "verified",
            "bundle_sha256": "d" * 64,
            "bundle_manifest_sha256": bundle_hash,
            "inventory_sha256": inventory_hash,
            "records_verified": len(models),
            "payloads_verified": len(models),
            "payloads_installed": len(models),
            "selected_id": None,
        },
    )
    package_path = tmp_path / "package.json"
    _write_json(
        package_path,
        {
            "source_revision": COMMIT,
            "product_source_revision": COMMIT,
            "validation_harness_revision": COMMIT,
            "git_head": COMMIT,
            "native_extension_sha256": NATIVE,
        },
    )

    def passed_mode(mode_name):
        source = {
            "passed": True,
            "comparison_scope": "original_source_sbml_species_output_fidelity",
            "method_sbml": "libRoadRunner CVODE",
            "roadrunner_version": "2.10.0",
            "observables": {"X": {"passed": True}},
            "source_species_targets": {"X": "X_amt"},
            "unmapped_source_species": [],
        }
        return {
            "mode": mode_name,
            "source_xml": {"passed": True, "validator": "libsbml"},
            "simulation_comparison": {
                "passed": True,
                "method_sbml": "libRoadRunner CVODE",
                "roadrunner_version": "2.10.0",
            },
            "source_simulation_comparison": source,
        }

    reports = {}
    for mode_name in ("flat", "atomized"):
        mode_refusals, mode_by_cause = _refusal_fixtures(mode_name)
        for row in mode_refusals:
            row["modes"] = [{"mode": mode_name}]
        other_record = {
            **other,
            "status": other_status,
            "source_artifact": other,
            "modes": [passed_mode(mode_name)],
        }
        if other_status == "failed":
            other_record["error"] = "unrelated comparison failure"
        report = {
            "mode": mode_name,
            "records": [_pinned_record(mode_name), other_record, *mode_refusals],
            "completeness": {
                "partial_run": False,
                "counts_match": True,
                "expected_records": len(models),
            },
            "summary": {"timeout_records": 0},
            "unsupported_summary": {"by_cause": mode_by_cause},
            "runtime_provenance": {"native_extension_sha256": NATIVE},
        }
        reports[mode_name] = tmp_path / f"{mode_name}.json"
        _write_json(reports[mode_name], report)
    return {
        "inventory": tmp_path / "inventory.json",
        "bundle": tmp_path / "bundle.json",
        "receipt": receipt_path,
        "package": package_path,
        "reports": reports,
    }


def _run_recorder(inputs):
    return recorder.build_release_record(
        COMMIT,
        inputs["inventory"],
        inputs["bundle"],
        inputs["receipt"],
        inputs["package"],
        inputs["reports"],
    )


# ---------------------------------------------------------------------------
# BIOMD0000000943 NUMERICAL_LIMIT / NON_COMPARABLE
# ---------------------------------------------------------------------------


def test_exact_numerical_disposition_is_emitted():
    flat, atomized = _pinned_pair()
    row = disp.classify_numerical_limit(flat, atomized)
    assert row["id"] == "numerical-limit:issue-162/BIOMD0000000943"
    assert row["status"] == "NON_COMPARABLE"
    assert row["classification"] == "NUMERICAL_LIMIT"
    assert row["evidence_kind"] == "numerical-limit-non-comparable"
    assert row["supported_execution"] is False
    assert row["counts_as_pass"] is False
    assert row["failed_observable"] == disp.FAILED_OBSERVABLE
    assert row["evidence"]["written"]["metrics"] == disp.WRITTEN_METRICS
    assert row["evidence"]["source"]["metrics"] == disp.SOURCE_METRICS


@pytest.mark.parametrize(
    "mutation",
    [
        "changed-observable",
        "changed-scale",
        "changed-difference",
        "single-mode-only",
        "changed-error",
        "changed-network",
        "changed-t-grid",
        "missing-case",
    ],
)
def test_numerical_disposition_fails_closed(mutation):
    flat, atomized = _pinned_pair()
    if mutation == "changed-observable":
        atomized["modes"][0]["source_simulation_comparison"]["failed_observables"] = [
            "Some_other_observable"
        ]
        atomized["modes"][0]["source_simulation_comparison"]["observables"] = {
            "Some_other_observable": {"passed": False}
        }
    elif mutation in {"changed-scale", "changed-difference"}:
        key = (
            "comparison_scale" if mutation == "changed-scale" else "max_abs_difference"
        )
        atomized["modes"][0]["source_simulation_comparison"]["observables"][
            disp.FAILED_OBSERVABLE
        ][key] *= 10.0
    elif mutation == "single-mode-only":
        atomized["status"] = "passed"
        atomized["modes"][0]["status"] = "passed"
        atomized["modes"][0]["source_simulation_comparison"]["passed"] = True
        atomized["modes"][0]["simulation_comparison"]["passed"] = True
    elif mutation == "changed-error":
        atomized["modes"][0]["source_simulation_comparison"]["error"] = "other error"
    elif mutation == "changed-network":
        atomized["modes"][0]["generated_network"] = {"species": 42, "reactions": 83}
    elif mutation == "changed-t-grid":
        atomized["modes"][0]["source_simulation_comparison"]["t_end"] = 2.0
    elif mutation == "missing-case":
        atomized = None
    with pytest.raises(ValueError):
        disp.classify_numerical_limit(flat, atomized)


def test_real_reports_produce_the_disposition_when_available():
    """Optional evidence check against the real 71888b93 report artifacts."""
    report_dir = Path("/tmp/bng3-162-main-71888b9")
    if not (report_dir / "report-flat.json").is_file():
        pytest.skip("real 71888b9 reports are not available")
    flat = json.loads((report_dir / "report-flat.json").read_text())
    atomized = json.loads((report_dir / "report-atomized.json").read_text())
    flat_records = {row["id"]: row for row in flat["records"]}
    atomized_records = {row["id"]: row for row in atomized["records"]}
    row = disp.classify_numerical_limit(
        flat_records.get(disp.MODEL_ID), atomized_records.get(disp.MODEL_ID)
    )
    assert row["id"] == "numerical-limit:issue-162/BIOMD0000000943"
    assert row["supported_execution"] is False
    assert (
        row["evidence"]["source"]["metrics"]["max_abs_difference"]
        == 5.195749186702531e-11
    )


# ---------------------------------------------------------------------------
# Timeout bucket
# ---------------------------------------------------------------------------


def test_timeout_bucket_is_explicit_and_never_a_pass():
    row = disp.classify_timeout("flat", _timeout_record("flat"))
    assert row["status"] == "TIMEOUT"
    assert row["evidence_kind"] == "load-sensitive-timeout"
    assert row["supported_execution"] is False
    assert row["counts_as_pass"] is False


@pytest.mark.parametrize(
    "mutation",
    ["changed-error", "failed-as-timeout", "harness-error-as-timeout", "with-verdict"],
)
def test_timeout_fails_closed(mutation):
    kwargs = {}
    if mutation == "changed-error":
        kwargs["error"] = "some other error"
    elif mutation == "failed-as-timeout":
        kwargs["status"] = "failed"
    elif mutation == "harness-error-as-timeout":
        kwargs["status"] = "harness_error"
    elif mutation == "with-verdict":
        kwargs["modes"] = [{"mode": "flat", "status": "passed"}]
    with pytest.raises(ValueError):
        disp.classify_timeout("flat", _timeout_record("flat", **kwargs))


# ---------------------------------------------------------------------------
# Valid-input refusal buckets
# ---------------------------------------------------------------------------


def test_refusal_counts_are_pinned_from_the_real_report():
    assert disp.PINNED_REFUSAL_COUNTS == {
        "events": 31,
        "fast_reaction": 4,
        "other": 4,
    }
    assert sum(disp.PINNED_REFUSAL_COUNTS.values()) == 39


def test_receipt_refuses_mismatched_counts():
    flat, atomized = _pinned_pair()
    flat_refusals, by_cause = _refusal_fixtures("flat")
    atomized_refusals, _ = _refusal_fixtures("atomized")
    flat_records = {disp.MODEL_ID: flat}
    atomized_records = {disp.MODEL_ID: atomized}
    for row in flat_refusals:
        flat_records[row["id"]] = {**row, "modes": [{"mode": "flat"}]}
    for row in atomized_refusals:
        atomized_records[row["id"]] = {**row, "modes": [{"mode": "atomized"}]}
    flat_report = {
        "summary": {"timeout_records": 0},
        "unsupported_summary": {"by_cause": by_cause},
    }
    atomized_report = copy.deepcopy(flat_report)
    all_refusals = set().union(*disp.PINNED_REFUSAL_IDS.values())
    # One mode drops a refusal: flat/atomized count agreement must fail even
    # though the pinned record is otherwise unchanged.
    unresolved = {
        "flat": all_refusals,
        "atomized": all_refusals - {"BIOMD0000000007"},
    }
    with pytest.raises(ValueError, match="flat/atomized refusal_ids disagree"):
        disp.build_disposition_receipt(
            flat_report,
            flat_records,
            atomized_report,
            atomized_records,
            unresolved,
        )
    # A report/receipt timeout-count disagreement must also fail closed.
    atomized_report = copy.deepcopy(flat_report)
    atomized_report["summary"]["timeout_records"] = 1
    with pytest.raises(ValueError, match="timeout bucket"):
        disp.build_disposition_receipt(
            flat_report,
            flat_records,
            atomized_report,
            atomized_records,
            {"flat": all_refusals, "atomized": all_refusals},
        )


# ---------------------------------------------------------------------------
# Recorder-level honesty controls
# ---------------------------------------------------------------------------


def test_recorder_keeps_three_result_rows_with_evidence_backed_dispositions(tmp_path):
    record = _run_recorder(_write_full_inputs(tmp_path))
    assert [row["id"] for row in record["results"]] == list(recorder.CHECKS)
    assert all(row["status"] == "PASS" for row in record["results"])
    assert all(
        row["evidence_kind"] == "supported-execution" for row in record["results"]
    )
    numerical = [
        row for row in record["dispositions"] if row["id"] == disp.NUMERICAL_ID
    ]
    assert len(numerical) == 1
    assert numerical[0]["counts_as_pass"] is False
    assert all(
        row["supported_execution"] is False and row["counts_as_pass"] is False
        for row in record["dispositions"]
    )


def test_recorder_rejects_unrelated_genuine_failure(tmp_path):
    record = _run_recorder(_write_full_inputs(tmp_path, other_status="failed"))
    assert all(row["status"] == "FAIL" for row in record["results"])
    assert OTHER_ID in record["modes"]["flat"]["unresolved"]
    assert all(row.get("case") != OTHER_ID for row in record["dispositions"])


def test_numerical_disposition_accepts_bounded_hosted_roundoff():
    """Hosted Linux roundoff stays in the pinned platform band.

    The locally observed macOS residual is ~5.2e-11; hosted Linux at the same
    exact revision observes ~1.8e-10 for the same cancellation.  The identity
    band must accept that difference without accepting a 10x-mutated metric.
    """
    flat, atomized = _pinned_pair()
    for record in (flat, atomized):
        obs = record["modes"][0]["source_simulation_comparison"]["observables"][
            disp.FAILED_OBSERVABLE
        ]
        obs["comparison_scale"] *= 1.0009
        obs["tolerance"] *= 1.0009
        obs["max_abs_difference"] *= 3.44
        obs["max_scaled_error"] *= 3.44
    row = disp.classify_numerical_limit(flat, atomized)
    assert row["id"] == "numerical-limit:issue-162/BIOMD0000000943"
    assert row["supported_execution"] is False
    assert row["counts_as_pass"] is False


def test_platform_sensitive_disposition_from_hosted_reports():
    """The hosted 8e4c79fa reports yield a non-PASS 0537 disposition."""
    base = Path(
        "/private/var/folders/cl/rt1592vn0sq5jw5vv4shrs4m0000gn/T/opencode/"
        "qual-artifacts/curated-8e4c/_temp/biomodels-artifacts"
    )
    pair = []
    for mode in ("flat", "atomized"):
        path = base / f"{mode}-report.json"
        if not path.is_file():
            pytest.skip("hosted 8e4c79fa reports are not available")
        report = json.loads(path.read_text())
        pair.append({r["id"]: r for r in report["records"]}.get(disp.PLATFORM_MODEL_ID))
    row = disp.classify_platform_sensitive_limit(*pair)
    assert row["status"] == "NON_COMPARABLE"
    assert row["supported_execution"] is False
    assert row["counts_as_pass"] is False
    assert row["evidence"]["flat"]["retry_count"] >= disp.PLATFORM_RETRY_COUNT


def test_platform_sensitive_disposition_fails_closed():
    """A changed CRN or single-mode failure cannot use the 0537 bucket."""
    base = Path(
        "/private/var/folders/cl/rt1592vn0sq5jw5vv4shrs4m0000gn/T/opencode/"
        "qual-artifacts/curated-8e4c/_temp/biomodels-artifacts"
    )
    pair = []
    for mode in ("flat", "atomized"):
        report = json.loads((base / f"{mode}-report.json").read_text())
        pair.append({r["id"]: r for r in report["records"]}[disp.PLATFORM_MODEL_ID])
    flat, atomized = pair
    atomized["modes"][0]["generated_network"] = {"species": 41, "reactions": 91}
    with pytest.raises(ValueError):
        disp.classify_platform_sensitive_limit(flat, atomized)


@pytest.mark.parametrize("mode_state", ["both-timeout", "flat-timeout-only"])
def test_border_model_1098_accepts_timeout_or_refusal_non_pass(mode_state):
    """BIOMD0000001098 may finish as an 'other' refusal or hit the 180s timeout."""
    flat_943, atomized_943 = _pinned_pair()
    flat_refusals, by_cause = _refusal_fixtures("flat")
    atomized_refusals, atomized_by_cause = _refusal_fixtures("atomized")

    def _timeout_1098():
        rec = _timeout_record("flat")
        rec["id"] = disp.BORDER_TIMEOUT_REFUSAL_ID
        return rec

    flat_records = {disp.MODEL_ID: flat_943}
    atomized_records = {disp.MODEL_ID: atomized_943}
    flat_unresolved = set()
    atomized_unresolved = set()
    for row in flat_refusals:
        if row["id"] == disp.BORDER_TIMEOUT_REFUSAL_ID:
            flat_records[row["id"]] = _timeout_1098()
        else:
            flat_records[row["id"]] = {**row, "modes": [{"mode": "flat"}]}
            flat_unresolved.add(row["id"])
    for row in atomized_refusals:
        if mode_state == "both-timeout" and row["id"] == disp.BORDER_TIMEOUT_REFUSAL_ID:
            atomized_records[row["id"]] = _timeout_1098()
        else:
            atomized_records[row["id"]] = {**row, "modes": [{"mode": "atomized"}]}
            atomized_unresolved.add(row["id"])

    by_cause["other"]["ids"] = [
        i for i in by_cause["other"]["ids"] if i != disp.BORDER_TIMEOUT_REFUSAL_ID
    ]
    by_cause["other"]["count"] = len(by_cause["other"]["ids"])
    if mode_state == "both-timeout":
        atomized_by_cause = copy.deepcopy(by_cause)

    flat_report = {
        "summary": {"timeout_records": 1},
        "unsupported_summary": {"by_cause": by_cause},
    }
    atomized_report = {
        "summary": {"timeout_records": 1 if mode_state == "both-timeout" else 0},
        "unsupported_summary": {"by_cause": atomized_by_cause},
    }
    rows, receipt = disp.build_disposition_receipt(
        flat_report,
        flat_records,
        atomized_report,
        atomized_records,
        {"flat": flat_unresolved, "atomized": atomized_unresolved},
    )
    assert receipt["agreement"]["flat_atomized_match"] is True
    assert receipt["modes"]["flat"]["timeout_ids"] == [disp.BORDER_TIMEOUT_REFUSAL_ID]
    assert receipt["modes"]["flat"]["refusal_counts"]["other"] == 3
    if mode_state == "both-timeout":
        assert receipt["modes"]["atomized"]["timeout_ids"] == [
            disp.BORDER_TIMEOUT_REFUSAL_ID
        ]
        assert receipt["modes"]["atomized"]["refusal_counts"]["other"] == 3
    else:
        assert receipt["modes"]["atomized"]["timeout_ids"] == []
        assert receipt["modes"]["atomized"]["refusal_counts"]["other"] == 4
    assert all(r["counts_as_pass"] is False for r in rows)


def test_other_pinned_refusal_cannot_escape_as_timeout():
    """Only BIOMD0000001098 has the timeout/refusal border disposition."""
    flat_943, atomized_943 = _pinned_pair()
    flat_refusals, by_cause = _refusal_fixtures("flat")
    atomized_refusals, atomized_by_cause = _refusal_fixtures("atomized")
    escaped_id = "BIOMD0000001099"
    flat_records = {disp.MODEL_ID: flat_943}
    atomized_records = {disp.MODEL_ID: atomized_943}
    unresolved = set()
    for row in flat_refusals:
        if row["id"] == escaped_id:
            rec = _timeout_record("flat")
            rec["id"] = escaped_id
            flat_records[escaped_id] = rec
        else:
            flat_records[row["id"]] = {**row, "modes": [{"mode": "flat"}]}
            unresolved.add(row["id"])
    for row in atomized_refusals:
        atomized_records[row["id"]] = (
            {**flat_records[escaped_id]}
            if row["id"] == escaped_id
            else {**row, "modes": [{"mode": "atomized"}]}
        )
    by_cause["other"]["ids"] = [i for i in by_cause["other"]["ids"] if i != escaped_id]
    by_cause["other"]["count"] = len(by_cause["other"]["ids"])
    report = {
        "summary": {"timeout_records": 1},
        "unsupported_summary": {"by_cause": by_cause},
    }
    with pytest.raises(ValueError, match="refusal IDs differ"):
        disp.build_disposition_receipt(
            report,
            flat_records,
            copy.deepcopy(report),
            atomized_records,
            {"flat": unresolved, "atomized": set(unresolved)},
        )
