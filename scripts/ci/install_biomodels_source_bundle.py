#!/usr/bin/env python3
"""Verify and install the pinned BioModels snapshot into a SHA-addressed cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any

MAX_BUNDLE_UNCOMPRESSED_BYTES = 500_000_000
SOURCE_FIELDS = (
    "id",
    "name",
    "format",
    "mime_type",
    "filename",
    "record_url",
    "download_url",
    "sha256",
    "file_size",
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _validate_records(
    bundle_manifest: dict[str, Any], inventory: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], set[str], list[str]]:
    rows = inventory.get("models")
    records = bundle_manifest.get("records")
    if not isinstance(rows, list) or not isinstance(records, list):
        raise ValueError("source bundle and query inventory must contain model lists")
    if len(rows) != inventory.get("matches") or len(records) != len(rows):
        raise ValueError("source bundle record count does not match the inventory")
    license_info = bundle_manifest.get("license")
    if (
        not isinstance(license_info, dict)
        or not isinstance(license_info.get("spdx"), str)
        or not license_info["spdx"]
        or not str(license_info.get("source_url", "")).startswith("https://")
    ):
        raise ValueError("source bundle license provenance is missing or invalid")
    source_by_id = {str(row.get("id", "")): row for row in rows}
    record_by_id = {str(row.get("id", "")): row for row in records}
    if not all(source_by_id) or len(source_by_id) != len(rows):
        raise ValueError("query inventory has missing or duplicate model ids")
    if set(source_by_id) != set(record_by_id):
        raise ValueError("source bundle does not map every inventory record exactly")
    payload_hashes: set[str] = set()
    no_sbml_archive_ids: list[str] = []
    for model_id, source in source_by_id.items():
        record = record_by_id[model_id]
        for field in SOURCE_FIELDS:
            if record.get(field) != source.get(field):
                raise ValueError(
                    f"source bundle metadata mismatch for {model_id}: {field}"
                )
        if record.get("license_spdx") != license_info["spdx"]:
            raise ValueError(f"source bundle license mismatch for {model_id}")
        digest = str(source.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(
                f"inventory source checksum is missing or invalid: {model_id}"
            )
        should_include = source.get("format") in {"SBML", "COMBINE archive"}
        if bool(record.get("payload_included")) != should_include:
            raise ValueError(f"unexpected payload inclusion state for {model_id}")
        if should_include:
            payload_path = record.get("payload_path")
            if payload_path != f"sha256/{digest}":
                raise ValueError(f"unsafe content path for {model_id}")
            if record.get("source_classification") not in {
                "sbml_xml",
                "combine_archive_contains_sbml",
                "combine_archive_verified_no_sbml",
            }:
                raise ValueError(f"unclassified included payload: {model_id}")
            payload_hashes.add(digest)
        elif record.get("source_classification") == "zip_archive_verified_no_sbml":
            inspection = record.get("archive_inspection") or {}
            if (
                source.get("format") not in {"Other", "ZIP archive"}
                or not str(source.get("filename", "")).lower().endswith(".zip")
                or inspection.get("source_archive_sha256") != digest
                or int(inspection.get("entry_count", 0)) < 1
                or int(inspection.get("xml_or_sbml_suffix_member_count", -1)) != 0
                or int(inspection.get("sbml_root_candidate_count", -1)) != 0
                or not re.fullmatch(
                    r"[0-9a-f]{64}", str(inspection.get("member_list_sha256", ""))
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}", str(inspection.get("archive_module_sha256", ""))
                )
            ):
                raise ValueError(f"invalid no-SBML archive evidence for {model_id}")
            no_sbml_archive_ids.append(model_id)
        elif record.get("source_classification") != "declared_non_sbml":
            raise ValueError(
                f"non-SBML source is not explicitly classified: {model_id}"
            )
    if len(payload_hashes) != bundle_manifest.get("payload_count"):
        raise ValueError(
            "unique payload count does not match the source bundle manifest"
        )
    return record_by_id, payload_hashes, no_sbml_archive_ids


def install_bundle(
    bundle_path: Path,
    bundle_manifest_path: Path,
    inventory_path: Path,
    inventory_provenance_path: Path,
    query_manifest_path: Path,
    cache_dir: Path,
    *,
    only_id: str | None = None,
) -> dict[str, Any]:
    """Verify source and bundle identities, then seed the cache by SHA-256."""

    bundle_manifest = _load_json(bundle_manifest_path)
    inventory = _load_json(inventory_path)
    inventory_provenance = _load_json(inventory_provenance_path)
    query_manifest = _load_json(query_manifest_path)
    if bundle_manifest.get("kind") != "curated-biomodels-offline-source-bundle":
        raise ValueError("unexpected offline source bundle kind")
    identity_checks = (
        ("inventory_sha256", inventory_path),
        ("inventory_provenance_sha256", inventory_provenance_path),
        ("query_manifest_sha256", query_manifest_path),
        ("bundle_sha256", bundle_path),
    )
    for key, path in identity_checks:
        actual = _sha256_file(path)
        if actual != bundle_manifest.get(key):
            label = key.replace("_sha256", " SHA-256").replace("_", " ")
            raise ValueError(f"{label} mismatch: {actual}")
    if inventory_provenance.get("inventory_sha256") != bundle_manifest.get(
        "inventory_sha256"
    ):
        raise ValueError("inventory provenance does not bind the pinned inventory")
    if (
        inventory.get("source") != bundle_manifest.get("source")
        or inventory.get("query") != bundle_manifest.get("query")
        or query_manifest.get("snapshot_date") != bundle_manifest.get("snapshot_date")
        or query_manifest.get("curation_query") != bundle_manifest.get("query")
    ):
        raise ValueError("source bundle query or dated snapshot does not match")
    if only_id is not None and only_id not in {
        str(row.get("id")) for row in inventory.get("models", [])
    }:
        raise ValueError(
            f"requested model is absent from the pinned snapshot: {only_id}"
        )
    records, expected_hashes, no_sbml_archive_ids = _validate_records(
        bundle_manifest, inventory
    )
    expected_members = {f"sha256/{digest}" for digest in expected_hashes}
    try:
        bundle = tarfile.open(bundle_path, mode="r:gz")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ValueError(f"invalid compressed source bundle: {exc}") from exc

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_root = cache_dir.resolve()
    sha_dir = cache_dir / "sha256"
    if sha_dir.exists() and sha_dir.is_symlink():
        raise ValueError("cache SHA directory must not be a symlink")
    sha_dir.mkdir(exist_ok=True)
    selected_hashes = expected_hashes
    if only_id is not None:
        selected_hashes = (
            {str(records[only_id]["sha256"])}
            if records[only_id].get("payload_included")
            else set()
        )

    total_size = 0
    seen: set[str] = set()
    installed = 0
    with tempfile.TemporaryDirectory(
        prefix="biomodels-bundle-", dir=cache_root
    ) as temp:
        temp_root = Path(temp)
        with bundle:
            members = bundle.getmembers()
            for member in members:
                name = member.name
                if name not in expected_members or name in seen:
                    raise ValueError(f"unexpected bundle member: {name}")
                if not member.isfile() or member.issym() or member.islnk():
                    raise ValueError(f"bundle member is not a regular file: {name}")
                digest = name.removeprefix("sha256/")
                source_record = next(
                    row for row in records.values() if row.get("sha256") == digest
                )
                expected_size = int(source_record.get("file_size") or -1)
                if expected_size < 0 or member.size != expected_size:
                    raise ValueError(f"source byte count mismatch for {name}")
                total_size += member.size
                if total_size > MAX_BUNDLE_UNCOMPRESSED_BYTES:
                    raise ValueError(
                        "source bundle expands beyond the configured size limit"
                    )
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot read bundle member: {name}")
                target = temp_root / digest
                computed = hashlib.sha256()
                with target.open("wb") as output:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        computed.update(chunk)
                        output.write(chunk)
                if computed.hexdigest() != digest:
                    raise ValueError(f"source payload checksum mismatch for {name}")
                seen.add(name)
            if seen != expected_members:
                missing = sorted(expected_members - seen)
                raise ValueError(
                    f"source bundle is missing payload members: {missing[:5]}"
                )
        for digest in selected_hashes:
            target = sha_dir / digest
            if target.is_symlink():
                raise ValueError(f"cache payload must not be a symlink: {target}")
            if target.exists():
                if not target.is_file() or _sha256_file(target) != digest:
                    raise ValueError(f"existing cache payload is corrupt: {target}")
                continue
            os.replace(temp_root / digest, target)
            installed += 1

    return {
        "status": "verified",
        "snapshot_date": bundle_manifest["snapshot_date"],
        "query": bundle_manifest["query"],
        "bundle_sha256": bundle_manifest["bundle_sha256"],
        "bundle_manifest_sha256": _sha256_file(bundle_manifest_path),
        "inventory_sha256": bundle_manifest["inventory_sha256"],
        "query_manifest_sha256": bundle_manifest["query_manifest_sha256"],
        "records_verified": len(records),
        "payloads_verified": len(expected_hashes),
        "payloads_installed": installed,
        "selected_id": only_id,
        "verified_non_sbml_archive_ids": sorted(no_sbml_archive_ids),
        "excluded_non_sbml_records": sum(
            not bool(row.get("payload_included")) for row in records.values()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-provenance", type=Path, required=True)
    parser.add_argument("--query-manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--only-id")
    args = parser.parse_args()
    try:
        receipt = install_bundle(
            args.bundle,
            args.bundle_manifest,
            args.inventory,
            args.inventory_provenance,
            args.query_manifest,
            args.cache_dir,
            only_id=args.only_id,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    serialized = json.dumps(receipt, indent=2) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
