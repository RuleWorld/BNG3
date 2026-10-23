"""Pinned BioModels source bundles fail closed before seeding the offline cache."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import socket
import tarfile
from pathlib import Path

import pytest

from scripts.ci.install_biomodels_source_bundle import SOURCE_FIELDS, install_bundle


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_fixture(
    tmp_path: Path,
    *,
    unsafe_member: str | None = None,
    missing_digest: str | None = None,
    duplicate_member: bool = False,
    symlink_member: bool = False,
    corrupt_digest: str | None = None,
    wrong_source_mapping: bool = False,
    wrong_license: bool = False,
):
    sbml = b"<sbml id='one'/ >\n"
    omex = b"combine bytes"
    non_sbml = b"onnx bytes"
    no_sbml_zip = b"zip bytes"
    rows = [
        {
            "id": "BIOMD0000000001",
            "format": "SBML",
            "filename": "one.xml",
            "download_url": "https://www.biomodels.org/model/one",
            "record_url": "https://www.biomodels.org/BIOMD1?format=json",
            "sha256": _sha(sbml),
            "file_size": str(len(sbml)),
        },
        {
            "id": "BIOMD0000000002",
            "format": "COMBINE archive",
            "filename": "two.omex",
            "download_url": "https://www.biomodels.org/model/two",
            "record_url": "https://www.biomodels.org/BIOMD2?format=json",
            "sha256": _sha(omex),
            "file_size": str(len(omex)),
        },
        {
            "id": "BIOMD0000000003",
            "format": "Open Neural Network Exchange",
            "filename": "three.onnx",
            "download_url": "https://www.biomodels.org/model/three",
            "record_url": "https://www.biomodels.org/BIOMD3?format=json",
            "sha256": _sha(non_sbml),
            "file_size": str(len(non_sbml)),
        },
        {
            "id": "BIOMD0000000004",
            "format": "Other",
            "filename": "four.zip",
            "download_url": "https://www.biomodels.org/model/four",
            "record_url": "https://www.biomodels.org/BIOMD4?format=json",
            "sha256": _sha(no_sbml_zip),
            "file_size": str(len(no_sbml_zip)),
        },
    ]
    inventory = {
        "schema_version": 1,
        "source": "https://www.biomodels.org/search",
        "query": "curationstatus:Manually curated",
        "matches": len(rows),
        "models": rows,
    }
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    query_manifest = {
        "schema_version": 2,
        "search_api_url": inventory["source"],
        "curation_query": inventory["query"],
        "snapshot_date": "2026-09-15",
        "expected_total_records": len(rows),
        "expected_sbml_records": 1,
        "expected_non_sbml_records": 3,
        "inventory_cache_name": "curated-biomodels-inventory.json",
    }
    query_manifest_path = tmp_path / "query-manifest.json"
    query_manifest_path.write_text(json.dumps(query_manifest), encoding="utf-8")
    provenance = {"inventory_sha256": _sha(inventory_path.read_bytes())}
    provenance_path = tmp_path / "inventory-provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    payloads = {
        _sha(sbml): sbml,
        _sha(omex): omex,
    }
    payload_rows = [
        {
            **row,
            "payload_included": True,
            "payload_path": f"sha256/{row['sha256']}",
            "source_classification": (
                "sbml_xml"
                if row["format"] == "SBML"
                else "combine_archive_contains_sbml"
            ),
        }
        for row in rows[:2]
    ]
    payload_rows.extend(
        [
            {
                **rows[2],
                "payload_included": False,
                "payload_path": None,
                "source_classification": "declared_non_sbml",
            },
            {
                **rows[3],
                "payload_included": False,
                "payload_path": None,
                "source_classification": "zip_archive_verified_no_sbml",
                "archive_inspection": {
                    "source_archive_sha256": rows[3]["sha256"],
                    "entry_count": 1,
                    "xml_or_sbml_suffix_member_count": 0,
                    "sbml_root_candidate_count": 0,
                    "member_list_sha256": "a" * 64,
                    "archive_module_sha256": "b" * 64,
                },
            },
        ]
    )
    if wrong_source_mapping:
        payload_rows[0]["download_url"] = "https://www.biomodels.org/model/wrong"
    for record in payload_rows:
        record["license_spdx"] = "MIT" if wrong_license else "CC0-1.0"
    bundle = tmp_path / "payloads.tar.gz"
    with bundle.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT
            ) as archive:
                for digest, data in sorted(payloads.items()):
                    if digest == missing_digest:
                        continue
                    name = unsafe_member or f"sha256/{digest}"
                    info = tarfile.TarInfo(name)
                    if digest == corrupt_digest:
                        data = b"x" * len(data)
                    if digest == next(iter(payloads)) and symlink_member:
                        info.type = tarfile.SYMTYPE
                        info.linkname = "../../outside"
                    else:
                        info.size = len(data)
                    archive.addfile(
                        info,
                        None if info.issym() else io.BytesIO(data),
                    )
                    if digest == next(iter(payloads)) and duplicate_member:
                        duplicate = tarfile.TarInfo(name)
                        duplicate.size = len(data)
                        archive.addfile(duplicate, io.BytesIO(data))
    bundle_manifest = {
        "schema_version": 1,
        "kind": "curated-biomodels-offline-source-bundle",
        "source": inventory["source"],
        "license": {
            "spdx": "CC0-1.0",
            "source_url": "https://www.biomodels.org/docs/",
        },
        "snapshot_date": query_manifest["snapshot_date"],
        "query": query_manifest["curation_query"],
        "inventory_sha256": provenance["inventory_sha256"],
        "inventory_provenance_sha256": _sha(provenance_path.read_bytes()),
        "query_manifest_sha256": _sha(query_manifest_path.read_bytes()),
        "bundle_sha256": _sha(bundle.read_bytes()),
        "record_count": len(rows),
        "payload_count": len(payloads),
        "records": payload_rows,
    }
    bundle_manifest_path = tmp_path / "bundle-manifest.json"
    bundle_manifest_path.write_text(json.dumps(bundle_manifest), encoding="utf-8")
    return (
        bundle,
        bundle_manifest_path,
        inventory_path,
        provenance_path,
        query_manifest_path,
        rows,
    )


def test_install_bundle_verifies_all_sources_and_seeds_sha_cache(tmp_path):
    bundle, bundle_manifest, inventory, provenance, query, rows = _write_fixture(
        tmp_path
    )
    cache = tmp_path / "cache"

    receipt = install_bundle(
        bundle, bundle_manifest, inventory, provenance, query, cache
    )

    assert receipt["records_verified"] == 4
    assert receipt["payloads_installed"] == 2
    assert set(receipt["verified_non_sbml_archive_ids"]) == {"BIOMD0000000004"}
    for row in rows[:2]:
        target = cache / "sha256" / row["sha256"]
        assert target.is_file()
        assert _sha(target.read_bytes()) == row["sha256"]


def test_install_bundle_rejects_path_traversal_before_writing(tmp_path):
    bundle, bundle_manifest, inventory, provenance, query, _ = _write_fixture(
        tmp_path, unsafe_member="sha256/../../outside"
    )
    cache = tmp_path / "cache"

    with pytest.raises(ValueError, match="unexpected bundle member"):
        install_bundle(bundle, bundle_manifest, inventory, provenance, query, cache)

    assert not (tmp_path / "outside").exists()
    assert not list((cache / "sha256").glob("*"))


def test_install_bundle_rejects_inventory_hash_mismatch(tmp_path):
    bundle, bundle_manifest, inventory, provenance, query, _ = _write_fixture(tmp_path)
    inventory.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="inventory SHA-256 mismatch"):
        install_bundle(
            bundle,
            bundle_manifest,
            inventory,
            provenance,
            query,
            tmp_path / "cache",
        )


def test_install_selected_id_still_verifies_every_pinned_payload_without_network(
    tmp_path, monkeypatch
):
    bundle, bundle_manifest, inventory, provenance, query, rows = _write_fixture(
        tmp_path
    )

    def reject_network(*_args, **_kwargs):
        raise AssertionError("source bundle installation attempted network access")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    cache = tmp_path / "cache"
    receipt = install_bundle(
        bundle,
        bundle_manifest,
        inventory,
        provenance,
        query,
        cache,
        only_id=rows[0]["id"],
    )

    assert receipt["payloads_verified"] == 2
    assert receipt["payloads_installed"] == 1
    assert (cache / "sha256" / rows[0]["sha256"]).is_file()
    assert not (cache / "sha256" / rows[1]["sha256"]).exists()


def test_install_selected_id_rejects_corrupt_unselected_payload(tmp_path):
    bundle, bundle_manifest, inventory, provenance, query, rows = _write_fixture(
        tmp_path, corrupt_digest=_sha(b"combine bytes")
    )

    with pytest.raises(ValueError, match="source payload checksum mismatch"):
        install_bundle(
            bundle,
            bundle_manifest,
            inventory,
            provenance,
            query,
            tmp_path / "cache",
            only_id=rows[0]["id"],
        )


def test_install_bundle_rejects_missing_omex_payload(tmp_path):
    bundle, bundle_manifest, inventory, provenance, query, rows = _write_fixture(
        tmp_path, missing_digest=_sha(b"combine bytes")
    )

    with pytest.raises(ValueError, match="source bundle is missing payload members"):
        install_bundle(
            bundle, bundle_manifest, inventory, provenance, query, tmp_path / "cache"
        )


def test_install_bundle_rejects_truncated_archive(tmp_path):
    bundle, bundle_manifest, inventory, provenance, query, _ = _write_fixture(tmp_path)
    content = bundle.read_bytes()
    bundle.write_bytes(content[: len(content) // 2])
    metadata = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    metadata["bundle_sha256"] = _sha(bundle.read_bytes())
    bundle_manifest.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="invalid compressed source bundle|source bundle is missing payload members",
    ):
        install_bundle(
            bundle, bundle_manifest, inventory, provenance, query, tmp_path / "cache"
        )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"duplicate_member": True}, "unexpected bundle member"),
        ({"symlink_member": True}, "not a regular file"),
        ({"wrong_source_mapping": True}, "source bundle metadata mismatch"),
        ({"wrong_license": True}, "source bundle license mismatch"),
    ],
)
def test_install_bundle_rejects_ambiguous_or_unmapped_sources(
    tmp_path, options, message
):
    bundle, bundle_manifest, inventory, provenance, query, _ = _write_fixture(
        tmp_path, **options
    )

    with pytest.raises(ValueError, match=message):
        install_bundle(
            bundle, bundle_manifest, inventory, provenance, query, tmp_path / "cache"
        )


def test_pinned_source_bundle_maps_every_inventory_row_and_payload():
    root = Path(__file__).resolve().parents[1]
    bundle_manifest = json.loads(
        (root / "provenance/curated-biomodels-source-bundle.json").read_text()
    )
    inventory = json.loads(
        (root / "provenance/curated-biomodels-query-inventory.json").read_text()
    )
    bundle_path = root / bundle_manifest["bundle_path"]

    assert bundle_manifest["license"]["spdx"] == "CC0-1.0"
    assert (
        hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        == bundle_manifest["bundle_sha256"]
    )
    source_by_id = {row["id"]: row for row in inventory["models"]}
    record_by_id = {row["id"]: row for row in bundle_manifest["records"]}
    assert set(source_by_id) == set(record_by_id)
    assert len(source_by_id) == bundle_manifest["record_count"] == 1096
    for model_id, source in source_by_id.items():
        record = record_by_id[model_id]
        assert all(record[field] == source[field] for field in SOURCE_FIELDS)
        assert record["license_spdx"] == bundle_manifest["license"]["spdx"]

    expected = {
        f"sha256/{record['sha256']}": int(record["file_size"])
        for record in bundle_manifest["records"]
        if record["payload_included"]
    }
    with tarfile.open(bundle_path, "r:gz") as archive:
        members = archive.getmembers()
    assert len(members) == len(expected) == bundle_manifest["payload_count"] == 1084
    assert all(member.isfile() for member in members)
    assert {member.name: member.size for member in members} == expected
