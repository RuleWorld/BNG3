"""Release receipts must consume actual, revision-locked BioModels results."""

import hashlib
import json

import pytest

from scripts.ci import sbml_162_disposition as disp


def _write(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pinned_943(mode_name):
    """The evidence-backed numerical-limit case required in a full corpus."""
    metrics = {"finite": True, "undefined": False, "undefined_at": [], "passed": False}
    stages = [
        {"name": name, "status": "passed"}
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
        )
    ]
    stages += [
        {
            "name": name,
            "status": "failed",
            "error": disp.SOURCE_ERROR,
        }
        for name in (
            "cross-engine-comparison",
            "cross-engine-comparison-retry",
            "original-source-sbml-comparison",
        )
    ]
    return {
        "id": disp.MODEL_ID,
        "format": "SBML",
        "filename": "Hat2016.xml",
        "sha256": disp.MODEL_SHA256,
        "status": "failed",
        "source_artifact": {"sha256": disp.MODEL_SHA256},
        "modes": [
            {
                "mode": mode_name,
                "status": "failed",
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
                    "observables": {
                        disp.FAILED_OBSERVABLE: {**metrics, **disp.WRITTEN_METRICS}
                    },
                },
                "source_simulation_comparison": {
                    "passed": False,
                    "comparison_scope": disp.SOURCE_SCOPE,
                    "error": disp.SOURCE_ERROR,
                    "failed_observables": list(disp.SOURCE_FAILED_OBSERVABLES),
                    "t_start": 0.0,
                    "t_end": 1.0,
                    "observables": {
                        disp.FAILED_OBSERVABLE: {**metrics, **disp.SOURCE_METRICS}
                    },
                },
            }
        ],
    }


def _pinned_refusals():
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
    records = [
        {
            "id": model_id,
            "format": "SBML",
            "filename": f"{model_id}.xml",
            "sha256": "e" * 64,
            "status": "unsupported",
            "unsupported_reason": "pinned valid-input refusal",
            "source_artifact": {"sha256": "e" * 64},
        }
        for model_id in sorted(set().union(*disp.PINNED_REFUSAL_IDS.values()))
    ]
    return records, by_cause


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing-source",
        "valid-refusal",
        "wrong-binary",
        "delay",
        "unverified-delay",
    ],
)
def test_receipt_consumes_the_two_source_comparisons(tmp_path, fault):
    from scripts.ci.record_issue162_release import build_release_record

    commit = "a" * 40
    native_hash = "b" * 64
    model_hash = "c" * 64
    inventory = tmp_path / "inventory.json"
    model = {"id": "MODEL", "format": "SBML", "filename": "m.xml", "sha256": model_hash}
    refusals, by_cause = _pinned_refusals()
    pinned_models = [
        {
            "id": disp.MODEL_ID,
            "format": "SBML",
            "filename": "Hat2016.xml",
            "sha256": disp.MODEL_SHA256,
        },
        *[
            {
                "id": row["id"],
                "format": row["format"],
                "filename": row["filename"],
                "sha256": row["sha256"],
            }
            for row in refusals
        ],
    ]
    all_models = [model, *pinned_models]
    inventory_hash = _write(
        inventory, {"matches": len(all_models), "models": all_models}
    )
    bundle_manifest = tmp_path / "bundle-manifest.json"
    bundle_hash = _write(
        bundle_manifest,
        {
            "bundle_sha256": "d" * 64,
            "inventory_sha256": inventory_hash,
            "payload_count": len(all_models),
            "records": all_models,
        },
    )
    receipt = tmp_path / "source-receipt.json"
    _write(
        receipt,
        {
            "status": "verified",
            "bundle_sha256": "d" * 64,
            "bundle_manifest_sha256": bundle_hash,
            "inventory_sha256": inventory_hash,
            "records_verified": len(all_models),
            "payloads_verified": len(all_models),
            "payloads_installed": len(all_models),
            "selected_id": None,
        },
    )
    package = tmp_path / "package.json"
    _write(
        package,
        {
            "source_revision": commit,
            "product_source_revision": commit,
            "validation_harness_revision": commit,
            "git_head": commit,
            "native_extension_sha256": native_hash,
        },
    )
    reports = {}
    for mode in ("flat", "atomized"):
        source = {
            "passed": True,
            "comparison_scope": "original_source_sbml_species_output_fidelity",
            "method_sbml": "libRoadRunner CVODE",
            "roadrunner_version": "2.10.0",
            "observables": {"X": {"passed": True}},
            "source_species_targets": {"X": "X_amt"},
            "unmapped_source_species": [],
        }
        if mode == "atomized" and fault in {"delay", "unverified-delay"}:
            source.update(
                method_sbml="sbmlsim-core CVODE",
                delay_oracle={
                    "version": "0.20.0",
                    "original_sbml_sha256": model_hash,
                    "converted_sbml_sha256": (
                        "missing" if fault == "unverified-delay" else "e" * 64
                    ),
                    "libsbml_version": "5.21.2",
                    "roadrunner_refusal": "Unable to support delay differential equations",
                    "solver_attempts": [{"stiff": True, "passed": True}],
                },
            )
        results = {
            "mode": mode,
            "source_xml": {"passed": True, "validator": "libsbml"},
            "simulation_comparison": {
                "passed": True,
                "method_sbml": "libRoadRunner CVODE",
                "roadrunner_version": "2.10.0",
            },
            "source_simulation_comparison": source,
        }
        record = {
            **model,
            "status": "passed",
            "source_artifact": model,
            "modes": [results],
        }
        if mode == "atomized" and fault == "missing-source":
            del results["source_simulation_comparison"]
        if mode == "atomized" and fault == "valid-refusal":
            record.update(
                status="unsupported", unsupported_reason="fast reaction refused"
            )
        reports[mode] = tmp_path / f"{mode}.json"
        _write(
            reports[mode],
            {
                "mode": mode,
                "records": [
                    record,
                    _pinned_943(mode),
                    *[{**row, "modes": [{"mode": mode}]} for row in refusals],
                ],
                "summary": {"timeout_records": 0},
                "unsupported_summary": {"by_cause": by_cause},
                "completeness": {
                    "partial_run": False,
                    "counts_match": True,
                    "expected_records": len(all_models),
                },
                "runtime_provenance": {
                    "native_extension_sha256": (
                        "e" * 64
                        if mode == "atomized" and fault == "wrong-binary"
                        else native_hash
                    )
                },
            },
        )
    if fault == "wrong-binary":
        with pytest.raises(ValueError, match="native extension"):
            build_release_record(
                commit, inventory, bundle_manifest, receipt, package, reports
            )
        return
    report = build_release_record(
        commit, inventory, bundle_manifest, receipt, package, reports
    )
    assert {row["id"] for row in report["results"]} == {
        "release-biomodels",
        "release-biomodels-triage",
        "release-obligation-162",
    }
    assert {row["status"] for row in report["results"]} == {
        "PASS" if fault in {None, "delay"} else "FAIL"
    }
    assert report["modes"]["atomized"]["unresolved"] == (
        [] if fault in {None, "delay"} else ["MODEL"]
    )
