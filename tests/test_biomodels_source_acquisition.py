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
