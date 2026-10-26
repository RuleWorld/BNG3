"""Source transport failures remain separate from scientific model verdicts."""

import hashlib
import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest


def _validator():
    path = (
        Path(__file__).parents[1] / "scripts" / "ci" / "validate_published_biomodels.py"
    )
    spec = importlib.util.spec_from_file_location("biomodels_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_fetch_error_retains_both_public_endpoints(tmp_path, monkeypatch):
    validator = _validator()
    entry = {
        "download_url": "https://www.biomodels.org/model/download/BIOMD1?filename=model.xml",
        "record_url": "https://www.biomodels.org/BIOMD1?format=json",
        "filename": "model.xml",
    }

    def denied(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(validator.urllib.request, "urlopen", denied)
    monkeypatch.setattr(
        validator,
        "_fetch_json",
        lambda url: (_ for _ in ()).throw(
            urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        ),
    )

    with pytest.raises(validator.SourceAcquisitionError) as caught:
        validator._download_if_needed(tmp_path / "model.xml", entry)

    assert entry["download_url"] in str(caught.value)
    assert entry["record_url"] in str(caught.value)
    assert "HTTPError" in str(caught.value)
    assert [attempt["http_status"] for attempt in caught.value.attempts] == [403, 403]
    assert [attempt["url"] for attempt in caught.value.attempts] == [
        entry["download_url"],
        entry["record_url"],
    ]
    assert validator._model_exception_status(caught.value) == "harness_error"
    assert (
        validator._model_exception_status(RuntimeError("conversion failed")) == "failed"
    )


def test_offline_cache_miss_refuses_without_trying_either_source_endpoint(
    tmp_path, monkeypatch
):
    validator = _validator()
    entry = {
        "id": "BIOMD0000000005",
        "filename": "model.xml",
        "sha256": "a" * 64,
        "download_url": "https://www.biomodels.org/model/download/BIOMD5",
        "record_url": "https://www.biomodels.org/BIOMD5?format=json",
    }

    def no_network(*args, **kwargs):
        raise AssertionError("offline source acquisition attempted network access")

    monkeypatch.setattr(validator.urllib.request, "urlopen", no_network)
    monkeypatch.setattr(validator, "_fetch_json", no_network)
    with pytest.raises(validator.SourceAcquisitionError, match="offline source cache"):
        validator._download_if_needed(tmp_path / "missing.xml", entry, offline=True)


def test_offline_cache_refuses_unverifiable_source_even_when_a_file_exists(
    tmp_path, monkeypatch
):
    validator = _validator()
    cached = tmp_path / "model.xml"
    cached.write_bytes(b"unverified")
    entry = {
        "id": "BIOMD0000000007",
        "filename": "model.xml",
        "download_url": "https://www.biomodels.org/model/download/BIOMD7",
    }
    monkeypatch.setattr(
        validator.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline source acquisition attempted network access")
        ),
    )
    with pytest.raises(validator.SourceAcquisitionError, match="expected SHA-256"):
        validator._download_if_needed(cached, entry, offline=True)


def test_no_sbml_archive_receipt_binds_source_and_inspection_evidence(
    tmp_path, monkeypatch
):
    import json

    validator = _validator()
    source = {
        "id": "BIOMD0000000006",
        "name": "Archived models",
        "format": "Other",
        "mime_type": "application/zip",
        "filename": "models.zip",
        "record_url": "https://www.biomodels.org/BIOMD6?format=json",
        "download_url": "https://www.biomodels.org/model/download/BIOMD6",
        "sha256": "a" * 64,
        "file_size": "123",
    }
    repo_root = tmp_path / "repo"
    archive_module = repo_root / "python/bionetgen/atomizer/modern/archive.py"
    archive_module.parent.mkdir(parents=True)
    archive_module.write_bytes(b"pinned archive extractor")
    archive_module_sha = hashlib.sha256(archive_module.read_bytes()).hexdigest()
    inspection = {
        "source_archive_sha256": source["sha256"],
        "entry_count": 3,
        "xml_or_sbml_suffix_member_count": 0,
        "sbml_root_candidate_count": 0,
        "member_list_sha256": "b" * 64,
        "archive_module_sha256": archive_module_sha,
    }
    bundle_manifest = {
        "kind": "curated-biomodels-offline-source-bundle",
        "source": "https://www.biomodels.org/search",
        "query": "curationstatus:Manually curated",
        "snapshot_date": "2026-09-15",
        "bundle_sha256": "c" * 64,
        "inventory_sha256": "",
        "query_manifest_sha256": "",
        "payload_count": 0,
        "record_count": 1,
        "license": {
            "spdx": "CC0-1.0",
            "source_url": "https://www.biomodels.org/license",
        },
        "records": [
            {
                **source,
                "payload_included": False,
                "payload_path": None,
                "source_classification": "zip_archive_verified_no_sbml",
                "archive_inspection": inspection,
                "license_spdx": "CC0-1.0",
            }
        ],
    }
    inventory = {
        "source": bundle_manifest["source"],
        "query": bundle_manifest["query"],
        "matches": 1,
        "models": [source],
    }
    query_manifest = {
        "search_api_url": bundle_manifest["source"],
        "snapshot_date": bundle_manifest["snapshot_date"],
        "curation_query": bundle_manifest["query"],
    }
    paths = {}
    for name, value in (
        ("bundle-manifest", bundle_manifest),
        ("inventory", inventory),
        ("query-manifest", query_manifest),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value))
        paths[name] = path
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    bundle_manifest["inventory_sha256"] = sha(paths["inventory"])
    bundle_manifest["query_manifest_sha256"] = sha(paths["query-manifest"])
    paths["bundle-manifest"].write_text(json.dumps(bundle_manifest))
    receipt = {
        "status": "verified",
        "snapshot_date": bundle_manifest["snapshot_date"],
        "query": bundle_manifest["query"],
        "bundle_sha256": bundle_manifest["bundle_sha256"],
        "bundle_manifest_sha256": sha(paths["bundle-manifest"]),
        "inventory_sha256": bundle_manifest["inventory_sha256"],
        "query_manifest_sha256": bundle_manifest["query_manifest_sha256"],
        "records_verified": 1,
        "payloads_verified": 0,
        "verified_non_sbml_archive_ids": [source["id"]],
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))

    evidence = validator._verified_no_sbml_archive_records(
        receipt_path,
        paths["bundle-manifest"],
        paths["inventory"],
        paths["query-manifest"],
        repo_root=repo_root,
    )
    assert evidence[source["id"]]["archive_inspection"] == inspection
    assert evidence[source["id"]]["source"]["sha256"] == source["sha256"]
    outcome = validator._verified_no_sbml_archive_outcome(
        source, evidence[source["id"]]
    )
    assert outcome["status"] == "unsupported"
    assert outcome["core_passed"] is False
    assert outcome["source_artifact"]["sha256"] == source["sha256"]
    assert outcome["source_artifact"]["archive_inspection"] == inspection
    conflicting_source = {**source, "filename": "different.zip"}
    with pytest.raises(ValueError, match="source identity disagrees"):
        validator._verified_no_sbml_archive_outcome(
            conflicting_source, evidence[source["id"]]
        )

    receipt["verified_non_sbml_archive_ids"] = []
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="no-SBML archive IDs"):
        validator._verified_no_sbml_archive_records(
            receipt_path,
            paths["bundle-manifest"],
            paths["inventory"],
            paths["query-manifest"],
            repo_root=repo_root,
        )

    receipt["verified_non_sbml_archive_ids"] = [source["id"]]
    receipt_path.write_text(json.dumps(receipt))
    archive_module.write_bytes(b"changed archive extractor")
    with pytest.raises(ValueError, match="module is stale"):
        validator._verified_no_sbml_archive_records(
            receipt_path,
            paths["bundle-manifest"],
            paths["inventory"],
            paths["query-manifest"],
            repo_root=repo_root,
        )


def test_real_no_sbml_archive_receipt_resolves_1075_without_network(
    tmp_path, monkeypatch
):
    from scripts.ci.install_biomodels_source_bundle import install_bundle

    validator = _validator()
    repo = Path(__file__).parents[1]
    bundle_manifest = repo / "provenance/curated-biomodels-source-bundle.json"
    inventory = repo / "provenance/curated-biomodels-query-inventory.json"
    inventory_provenance = (
        repo / "provenance/curated-biomodels-query-inventory.provenance.json"
    )
    query_manifest = repo / "provenance/published-biomodels.json"
    receipt = install_bundle(
        repo / "tests/fixtures/curated_biomodels/source-payloads-2026-09.tar.gz",
        bundle_manifest,
        inventory,
        inventory_provenance,
        query_manifest,
        tmp_path / "cache",
    )
    receipt_path = tmp_path / "source-bundle-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    evidence = validator._verified_no_sbml_archive_records(
        receipt_path,
        bundle_manifest,
        inventory,
        query_manifest,
        repo_root=repo,
    )
    source = next(
        row
        for row in json.loads(inventory.read_text(encoding="utf-8"))["models"]
        if row["id"] == "BIOMD0000001075"
    )

    def no_network(*args, **kwargs):
        raise AssertionError("verified no-SBML source attempted network access")

    monkeypatch.setattr(validator.urllib.request, "urlopen", no_network)
    outcome = validator._verified_no_sbml_archive_outcome(
        source, evidence[source["id"]]
    )

    assert outcome["status"] == "unsupported"
    assert outcome["source_artifact"]["filename"] == "reproduced_trained_models.zip"
    assert outcome["source_artifact"]["mime_type"] == "application/zip"
    assert outcome["source_artifact"]["size_bytes"] == 87786133
    assert outcome["source_artifact"]["sha256"] == source["sha256"]
    assert (
        outcome["source_artifact"]["archive_inspection"][
            "xml_or_sbml_suffix_member_count"
        ]
        == 0
    )


def test_isolated_model_worker_receives_offline_flag(tmp_path, monkeypatch):
    import argparse

    validator = _validator()
    entry = {"id": "BIOMD0000000005", "filename": "model.xml"}
    args = argparse.Namespace(
        cache_dir=tmp_path,
        manifest=Path("provenance/published-biomodels.json"),
        mode="flat",
        simulation_t_end=1.0,
        simulation_n_steps=10,
        simulation_rtol=1e-8,
        simulation_atol=1e-12,
        ode_smoke=False,
        artifacts_dir=None,
        model_timeout=30,
    )

    def worker(command, **kwargs):
        assert "--offline" in command
        output_path = Path(command[command.index("--json") + 1])
        output_path.write_text(
            json.dumps({"records": [{"id": entry["id"], "status": "passed"}]}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(validator.subprocess, "run", worker)
    record = validator._run_isolated_model(entry, args)
    assert record["id"] == entry["id"]
    assert record["status"] == "passed"


def test_parent_timeout_retains_phase_source_hash_and_bounded_case_packet(
    tmp_path, monkeypatch
):
    import argparse
    import subprocess

    validator = _validator()
    source_bytes = b"<sbml level='3' version='2'/>"
    digest = hashlib.sha256(source_bytes).hexdigest()
    entry = {
        "id": "BIOMD0000000008",
        "filename": "model.xml",
        "sha256": digest,
    }
    cache_dir = tmp_path / "cache"
    cached_source = validator._model_source_cache_path(cache_dir, entry)
    cached_source.parent.mkdir(parents=True)
    cached_source.write_bytes(source_bytes)
    artifacts_dir = tmp_path / "artifacts"
    case_dir = artifacts_dir / entry["id"]
    case_dir.mkdir(parents=True)
    (case_dir / "source.xml").write_bytes(source_bytes)
    (case_dir / "translated.flat.bngl").write_text("begin model\nend model\n")
    (case_dir / "BIOMD0000000008_flat.xml").write_text("<sbml/>")
    (case_dir / "translated.atomized.bngl").write_bytes(b"x" * 1_100_000)
    checkpoint = {
        "mode": "flat",
        "checkpoint_state": "in_progress",
        "stage_results": [
            {"name": "original-source-sbml-comparison", "status": "passed"}
        ],
        "source_simulation_comparison": {
            "passed": True,
            "comparison_scope": "original_source_sbml_species_output_fidelity",
            "observable_count": 94,
        },
        "simulation_comparison": {
            "passed": True,
            "comparison_scope": "written_sbml_export_consistency",
            "observable_count": 190,
        },
    }
    (case_dir / "mode.atomized.progress.json").write_text("{torn", encoding="utf-8")
    (case_dir / "mode.atomized.progress.json.tmp").write_text(
        json.dumps({**checkpoint, "mode": "atomized"}), encoding="utf-8"
    )
    stderr = b"\n".join(
        (
            b"@@BIOMODELS_CASE_PHASE@@ completed source-sha256-verification",
            b"@@BIOMODELS_CASE_PHASE@@ started source-xml-validation",
        )
    )

    def timeout(command, **kwargs):
        validator._write_mode_checkpoint(
            checkpoint, case_dir / "mode.flat.progress.json"
        )
        raise subprocess.TimeoutExpired(
            command, 180, output=b"partial stdout", stderr=stderr
        )

    monkeypatch.setattr(validator.subprocess, "run", timeout)
    args = argparse.Namespace(
        cache_dir=cache_dir,
        manifest=Path("provenance/published-biomodels.json"),
        mode="flat",
        simulation_t_end=1.0,
        simulation_n_steps=10,
        simulation_rtol=1e-8,
        simulation_atol=1e-12,
        ode_smoke=False,
        artifacts_dir=artifacts_dir,
        model_timeout=180,
    )

    record = validator._run_isolated_model(entry, args)

    assert record["status"] == "timeout"
    assert record["phase_progress"]["last_completed_phase"] == (
        "source-sha256-verification"
    )
    assert record["phase_progress"]["active_phase"] == "source-xml-validation"
    assert record["source_validation"]["status"] == "verified_sha256"
    assert record["source_validation"]["model_id"] == entry["id"]
    assert record["source_validation"]["sha256"] == digest
    assert record["mode_checkpoints"]["flat"]["checkpoint_state"] == "in_progress"
    assert "atomized" not in record["mode_checkpoints"]
    assert record["core_passed"] is False
    assert "modes" not in record
    assert (
        record["mode_checkpoints"]["flat"]["source_simulation_comparison"][
            "observable_count"
        ]
        == 94
    )
    assert (
        record["mode_checkpoints"]["flat"]["simulation_comparison"]["observable_count"]
        == 190
    )
    packet_path = case_dir / "case-packet" / "packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["source_validation"]["sha256"] == digest
    assert {item["name"] for item in packet["artifacts"]} == {
        "source.xml",
        "translated.flat.bngl",
        "BIOMD0000000008_flat.xml",
        "mode.flat.progress.json",
        "mode.atomized.progress.json",
    }
    assert packet["included_bytes"] <= validator.MAX_CASE_PACKET_BYTES
    assert record["case_packet"].endswith("case-packet/packet.json")
    assert all(item.get("sha256") for item in packet["artifacts"])
    packet_by_name = {item["name"]: item for item in packet["artifacts"]}
    assert packet_by_name["source.xml"]["sha256"] == digest
    assert (
        packet_by_name["mode.flat.progress.json"]["sha256"]
        == hashlib.sha256(
            (packet_path.parent / "mode.flat.progress.json").read_bytes()
        ).hexdigest()
    )
    for name, item in packet_by_name.items():
        assert hashlib.sha256((packet_path.parent / name).read_bytes()).hexdigest() == (
            item["sha256"]
        )


def test_case_packet_preserves_raw_crlf_source_bytes(tmp_path):
    validator = _validator()
    entry = {
        "id": "BIOMD0000000008",
        "filename": "model.xml",
        "format": "SBML",
        "sha256": "",
    }
    raw_source = b"\xef\xbb\xbf<sbml>\r\n  <model/>\r\n</sbml>\r\n"
    digest = hashlib.sha256(raw_source).hexdigest()
    source_path = tmp_path / "source.xml"
    source_path.write_bytes(raw_source)
    decoded_source = source_path.read_text(encoding="utf-8-sig")
    assert "\r\n" not in decoded_source

    model_dir = tmp_path / "artifacts" / entry["id"]
    model_dir.mkdir(parents=True)
    artifact_path = model_dir / "source.xml"
    artifact_path.write_bytes(
        validator._source_xml_artifact_bytes(
            source_path, decoded_source, extracted_from_archive=False
        )
    )
    record = {
        "status": "timeout",
        "source_validation": {"status": "verified_sha256", "sha256": digest},
    }
    args = SimpleNamespace(artifacts_dir=tmp_path / "artifacts")

    packet_path = Path(validator._write_case_packet(entry, args, record))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_source = next(
        item for item in packet["artifacts"] if item["name"] == "source.xml"
    )

    assert artifact_path.read_bytes() == raw_source
    assert packet["source_xml_representation"] == "original-source-bytes"
    assert packet_source["sha256"] == digest
    assert packet["source_validation"]["sha256"] == digest


def test_case_packet_distinguishes_extracted_archive_sbml_from_archive_hash(tmp_path):
    validator = _validator()
    entry = {
        "id": "BIOMD0000000009",
        "filename": "model.omex",
        "format": "COMBINE archive",
    }
    archive_bytes = b"verified archive bytes"
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    source_path = tmp_path / entry["filename"]
    source_path.write_bytes(archive_bytes)
    extracted_sbml = "<sbml>\r\n  <model/>\r\n</sbml>\r\n"
    extracted_bytes = extracted_sbml.encode("utf-8")

    model_dir = tmp_path / "artifacts" / entry["id"]
    model_dir.mkdir(parents=True)
    artifact_path = model_dir / "source.xml"
    artifact_path.write_bytes(
        validator._source_xml_artifact_bytes(
            source_path, extracted_sbml, extracted_from_archive=True
        )
    )
    args = SimpleNamespace(artifacts_dir=tmp_path / "artifacts")
    record = {
        "status": "timeout",
        "source_validation": {
            "status": "verified_sha256",
            "sha256": archive_digest,
        },
    }

    packet_path = Path(validator._write_case_packet(entry, args, record))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_source = next(
        item for item in packet["artifacts"] if item["name"] == "source.xml"
    )

    assert artifact_path.read_bytes() == extracted_bytes
    assert packet["source_xml_representation"] == "extracted-sbml-utf8"
    assert packet_source["sha256"] == hashlib.sha256(extracted_bytes).hexdigest()
    assert packet_source["sha256"] != packet["source_validation"]["sha256"]


def test_omitted_source_xml_retains_its_digest_in_packet(tmp_path):
    validator = _validator()
    entry = {"id": "BIOMD0000000010", "format": "SBML", "filename": "large.xml"}
    raw_source = b"x" * (validator.MAX_CASE_PACKET_FILE_BYTES + 1)
    digest = hashlib.sha256(raw_source).hexdigest()
    model_dir = tmp_path / "artifacts" / entry["id"]
    model_dir.mkdir(parents=True)
    (model_dir / "source.xml").write_bytes(raw_source)
    args = SimpleNamespace(artifacts_dir=tmp_path / "artifacts")

    packet_path = Path(
        validator._write_case_packet(
            entry,
            args,
            {
                "status": "timeout",
                "source_validation": {"status": "verified_sha256", "sha256": digest},
            },
        )
    )
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    omitted_source = next(
        item for item in packet["omitted_artifacts"] if item["name"] == "source.xml"
    )
    assert omitted_source["sha256"] == digest


def test_parent_timeout_verdict_survives_denied_record_persistence(
    tmp_path, monkeypatch
):
    import argparse
    import subprocess

    validator = _validator()
    source_bytes = b"<sbml/>"
    digest = hashlib.sha256(source_bytes).hexdigest()
    entry = {
        "id": "BIOMD0000000008",
        "filename": "model.xml",
        "sha256": digest,
    }
    cache_dir = tmp_path / "cache"
    cached_source = validator._model_source_cache_path(cache_dir, entry)
    cached_source.parent.mkdir(parents=True)
    cached_source.write_bytes(source_bytes)
    artifacts_dir = tmp_path / "artifacts"

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 180, stderr=b"")

    original_write_text = Path.write_text

    def deny_record(path, *args, **kwargs):
        if path.name == "record.json":
            raise PermissionError("read-only artifact mount")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(validator.subprocess, "run", timeout)
    monkeypatch.setattr(validator, "_attach_case_packet", lambda *_args: None)
    monkeypatch.setattr(Path, "write_text", deny_record)
    args = argparse.Namespace(
        cache_dir=cache_dir,
        manifest=Path("provenance/published-biomodels.json"),
        mode="flat",
        simulation_t_end=1.0,
        simulation_n_steps=10,
        simulation_rtol=1e-8,
        simulation_atol=1e-12,
        ode_smoke=False,
        artifacts_dir=artifacts_dir,
        model_timeout=180,
    )

    record = validator._run_isolated_model(entry, args)

    assert record["status"] == "timeout"
    assert record["core_passed"] is False
    assert record["record_persistence_error"] == (
        "PermissionError: read-only artifact mount"
    )


def test_failed_mode_record_keeps_completed_stages_and_prior_results():
    validator = _validator()
    result = {
        "mode": "atomized",
        "comparison_scope": validator.COMPARISON_SCOPE,
        "generated_network": {"species": 3},
    }
    with pytest.raises(RuntimeError) as caught:
        with validator._mode_stage(result, "native-sbml-readback"):
            raise RuntimeError("native reader failed")

    failed = validator._failed_mode_result("atomized", result, caught.value)
    assert failed["status"] == "failed"
    assert failed["comparison_scope"] == "written_sbml_export_consistency"
    assert failed["generated_network"] == {"species": 3}
    assert failed["stage_results"] == [
        {
            "name": "native-sbml-readback",
            "status": "failed",
            "error": "RuntimeError: native reader failed",
        }
    ]


def test_mode_checkpoint_retains_completed_comparison_without_claiming_pass(tmp_path):
    validator = _validator()
    checkpoint = tmp_path / "mode.flat.progress.json"
    result = {
        "mode": "flat",
        "stage_results": [
            {"name": "original-source-sbml-comparison", "status": "passed"}
        ],
        "source_simulation_comparison": {
            "passed": True,
            "comparison_scope": "original_source_sbml_species_output_fidelity",
            "observable_count": 94,
        },
        "simulation_comparison": {
            "passed": True,
            "comparison_scope": "written_sbml_export_consistency",
            "observable_count": 190,
        },
    }
    validator._write_mode_checkpoint(result, checkpoint)

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["checkpoint_state"] == "in_progress"
    assert saved["source_simulation_comparison"]["observable_count"] == 94
    assert saved["simulation_comparison"]["observable_count"] == 190
    assert "status" not in saved
    assert "core_passed" not in saved


def test_case_packet_error_does_not_replace_model_verdict(monkeypatch, tmp_path):
    import argparse

    validator = _validator()
    monkeypatch.setattr(
        validator,
        "_write_case_packet",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    record = {"status": "timeout", "core_passed": False}
    args = argparse.Namespace(artifacts_dir=tmp_path)

    validator._attach_case_packet(record, {"id": "BIOMD0000000008"}, args)

    assert record["status"] == "timeout"
    assert record["core_passed"] is False
    assert record["case_packet_error"] == "OSError: disk full"


def test_same_source_filename_uses_model_identity_and_content_sha(
    tmp_path, monkeypatch
):
    validator = _validator()
    first_bytes = b"<sbml id='first'/><!---->"
    second_bytes = b"<sbml id='second'/><!---->"
    first_sha = hashlib.sha256(first_bytes).hexdigest()
    second_sha = hashlib.sha256(second_bytes).hexdigest()
    # Legacy/shared caches can have identical basenames in different folders.
    (tmp_path / "legacy-a").mkdir()
    (tmp_path / "legacy-b").mkdir()
    (tmp_path / "legacy-a" / "model.xml").write_bytes(first_bytes)
    (tmp_path / "legacy-b" / "model.xml").write_bytes(second_bytes)

    def no_network(*args, **kwargs):
        raise AssertionError(
            "a verified content-addressed cache hit should avoid download"
        )

    monkeypatch.setattr(validator.urllib.request, "urlopen", no_network)
    first = {
        "id": "BIOMD0000000001",
        "filename": "model.xml",
        "sha256": first_sha,
        "download_url": "https://www.biomodels.org/model/first",
    }
    second = {
        "id": "BIOMD0000000002",
        "filename": "model.xml",
        "sha256": second_sha,
        "download_url": "https://www.biomodels.org/model/second",
    }
    first_path = validator._model_source_cache_path(tmp_path, first)
    second_path = validator._model_source_cache_path(tmp_path, second)

    assert first_path != second_path
    assert first_path == tmp_path / "sha256" / first_sha
    assert second_path == tmp_path / "sha256" / second_sha
    migrated = validator._migrate_legacy_source_cache(tmp_path, [first, second])
    assert migrated == {"expected_hashes": 2, "migrated": 2, "missing": 0}
    assert validator._download_if_needed(first_path, first) == first_sha
    assert validator._download_if_needed(second_path, second) == second_sha
    assert first_path.read_bytes() == first_bytes
    assert second_path.read_bytes() == second_bytes


def test_source_without_valid_sha_does_not_reuse_content_cache(tmp_path, monkeypatch):
    validator = _validator()
    source = tmp_path / "old" / "model.xml"
    source.parent.mkdir()
    source.write_bytes(b"cached bytes")
    target = validator._model_source_cache_path(
        tmp_path, {"id": "BIOMD0000000003", "filename": "model.xml"}
    )
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"fresh bytes"

    def fetch(request, timeout):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(validator.urllib.request, "urlopen", fetch)
    entry = {
        "id": "BIOMD0000000003",
        "filename": "model.xml",
        "download_url": "https://www.biomodels.org/model/no-checksum",
    }
    assert (
        validator._download_if_needed(target, entry)
        == hashlib.sha256(b"fresh bytes").hexdigest()
    )
    assert calls == [entry["download_url"]]
    assert target.read_bytes() == b"fresh bytes"


def test_hash_addressed_worker_hit_does_not_scan_cache_tree(tmp_path, monkeypatch):
    validator = _validator()
    content = b"<sbml id='worker'/>\n"
    digest = hashlib.sha256(content).hexdigest()
    entry = {
        "id": "BIOMD0000000004",
        "filename": "model.xml",
        "sha256": digest,
        "download_url": "https://www.biomodels.org/model/worker",
    }
    path = validator._model_source_cache_path(tmp_path, entry)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    def unexpected_scan(*args, **kwargs):
        raise AssertionError("isolated workers must use the direct SHA path")

    monkeypatch.setattr(Path, "rglob", unexpected_scan)
    assert validator._download_if_needed(path, entry) == digest


def test_downloaded_source_hash_mismatch_is_a_harness_integrity_error(
    tmp_path, monkeypatch
):
    validator = _validator()
    content = b"<sbml/>\n"
    expected = "0" * 64
    entry = {
        "download_url": "https://www.biomodels.org/model/download/BIOMD1?filename=model.xml",
        "record_url": "https://www.biomodels.org/BIOMD1?format=json",
        "filename": "model.xml",
        "sha256": expected,
    }

    monkeypatch.setattr(
        validator.urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(content),
    )

    with pytest.raises(RuntimeError) as caught:
        validator._download_if_needed(tmp_path / "model.xml", entry)

    actual = hashlib.sha256(content).hexdigest()
    assert validator._model_exception_status(caught.value) == "harness_error"
    assert caught.value.expected_sha256 == expected
    assert caught.value.actual_sha256 == actual
