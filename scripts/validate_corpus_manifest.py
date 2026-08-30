#!/usr/bin/env python3
"""Validate a frozen BNG3 corpus selection and every recorded model digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / "provenance" / "corpus" / "selection.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TIERS = ("s", "p", "nf", "expr", "x", "b")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def inside_repo(relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    candidate = (REPO / relative).resolve()
    try:
        candidate.relative_to(REPO.resolve())
    except ValueError:
        return None
    return candidate


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if document.get("selection_status") not in {
        "pending-maintainer-approval",
        "approved",
    }:
        errors.append("selection_status is invalid")

    lock_ref = document.get("source_lock")
    if not isinstance(lock_ref, dict):
        errors.append("source_lock must be an object")
        lock_path = None
    else:
        lock_path = inside_repo(lock_ref.get("path"))
        if lock_path is None:
            errors.append("source_lock.path must name a repository-relative file")
        if not DIGEST_RE.fullmatch(str(lock_ref.get("sha256"))):
            errors.append("source_lock.sha256 must be a sha256 digest")
        elif (
            lock_path is not None
            and lock_path.is_file()
            and digest(lock_path) != lock_ref["sha256"]
        ):
            errors.append("source_lock.sha256 does not match the lock file")

    lock: dict[str, Any] | None = None
    if lock_path is not None and lock_path.is_file():
        try:
            lock = load(lock_path)
        except ValueError as exc:
            errors.append(str(exc))
    elif lock_path is not None:
        errors.append("source_lock.path does not exist")

    rulehub = document.get("rulehub")
    if not isinstance(rulehub, dict):
        errors.append("rulehub must be an object")
    else:
        if not re.fullmatch(
            r"^https://github\.com/.+\.git$", str(rulehub.get("repository"))
        ):
            errors.append("rulehub.repository must be a canonical GitHub .git URL")
        if not SHA_RE.fullmatch(str(rulehub.get("revision"))):
            errors.append("rulehub.revision must be a full lowercase Git SHA")
        if rulehub.get("status") not in {
            "observed",
            "pending-maintainer-approval",
            "approved",
        }:
            errors.append("rulehub.status is invalid")
        if not rulehub.get("policy"):
            errors.append("rulehub.policy must be non-empty")
        if lock is not None:
            locked_revision = lock.get("sources", {}).get("rulehub", {}).get("revision")
            if rulehub.get("revision") != locked_revision:
                errors.append("rulehub.revision does not match the source lock")

    records = document.get("records")
    by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(records, list):
        errors.append("records must be an array")
        records = []
    for index, record in enumerate(records):
        where = f"records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{where} must be an object")
            continue
        model_id = record.get("id")
        if not isinstance(model_id, str) or not model_id:
            errors.append(f"{where}.id must be non-empty")
        elif model_id in by_id:
            errors.append(f"{where}.id is duplicated")
        else:
            by_id[model_id] = record
        model_path = inside_repo(record.get("path"))
        if model_path is None:
            errors.append(f"{where}.path must name a repository-relative file")
        elif not model_path.is_file():
            errors.append(f"{where}.path does not exist")
        if not DIGEST_RE.fullmatch(str(record.get("sha256"))):
            errors.append(f"{where}.sha256 must be a sha256 digest")
        elif (
            model_path is not None
            and model_path.is_file()
            and digest(model_path) != record["sha256"]
        ):
            errors.append(f"{where}.sha256 does not match the model")
        if record.get("origin") != "repository-fixture":
            errors.append(f"{where}.origin must be repository-fixture")
        tiers = record.get("tiers")
        if (
            not isinstance(tiers, list)
            or len(set(tiers)) != len(tiers)
            or any(tier not in TIERS for tier in tiers)
        ):
            errors.append(f"{where}.tiers must be a unique list of known tiers")

    tiers_document = document.get("tiers")
    if not isinstance(tiers_document, dict):
        errors.append("tiers must be an object")
        tiers_document = {}
    for tier in TIERS:
        values = tiers_document.get(tier)
        if not isinstance(values, list) or sorted(set(values)) != values:
            errors.append(f"tiers.{tier} must be a sorted unique list")
            values = []
        for model_id in values:
            if model_id not in by_id:
                errors.append(f"tiers.{tier} references unknown model {model_id!r}")

    for model_id, record in by_id.items():
        expected = [tier for tier in TIERS if model_id in tiers_document.get(tier, [])]
        if record.get("tiers") != expected:
            errors.append(f"records[{model_id!r}].tiers disagrees with tier lists")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        document = load(args.manifest)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    errors = validate(document)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(
            f"corpus manifest validation failed ({len(errors)} error(s))",
            file=sys.stderr,
        )
        return 1
    print(f"corpus manifest validation passed: {len(document['records'])} model(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
