"""Release receipts must consume actual, revision-locked BioModels results."""

import hashlib
import json

import pytest


def _write(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    inventory_hash = _write(inventory, {"matches": 1, "models": [model]})
    bundle_manifest = tmp_path / "bundle-manifest.json"
    bundle_hash = _write(
        bundle_manifest,
        {
            "bundle_sha256": "d" * 64,
            "inventory_sha256": inventory_hash,
            "payload_count": 1,
            "records": [model],
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
            "records_verified": 1,
            "payloads_verified": 1,
            "payloads_installed": 1,
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
                "records": [record],
                "completeness": {
                    "partial_run": False,
                    "counts_match": True,
                    "expected_records": 1,
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
