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
    if document.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if document.get("selection_status") not in {
        "pending-maintainer-approval",
        "approved",
    }:
        errors.append("selection_status is invalid")

    accepted = document.get("accepted_selections")
    if not isinstance(accepted, dict):
        errors.append("accepted_selections must be an object")
    else:
        if accepted.get("status") not in {
            "observed",
            "pending-maintainer-approval",
            "approved",
        }:
            errors.append("accepted_selections.status is invalid")
        for key in ("approved_tiers", "approved_models"):
            value = accepted.get(key)
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                errors.append(f"accepted_selections.{key} must be a list of names")
        if not accepted.get("note"):
            errors.append("accepted_selections.note must be non-empty")

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
        selection = record.get("selection")
        if not isinstance(selection, dict):
            errors.append(f"{where}.selection must be an object")
        else:
            if not str(selection.get("reason") or "").strip():
                errors.append(f"{where}.selection.reason must be non-empty")
            if selection.get("tiers") != tiers:
                errors.append(f"{where}.selection.tiers disagrees with the record")
            if not str(selection.get("capability") or "").strip():
                errors.append(f"{where}.selection.capability must be non-empty")
            if selection.get("provenance") not in {
                "frozen-selection",
                "added-after-the-frozen-selection",
            }:
                errors.append(f"{where}.selection.provenance is invalid")

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

    justifications = document.get("tier_justifications")
    if not isinstance(justifications, dict):
        errors.append("tier_justifications must be an object")
        justifications = {}
    for tier in TIERS:
        entry = justifications.get(tier)
        if not isinstance(entry, dict):
            errors.append(f"tier_justifications.{tier} must be an object")
            continue
        for key in ("question", "owner", "capability"):
            if not str(entry.get(key) or "").strip():
                errors.append(f"tier_justifications.{tier}.{key} must be non-empty")
        budget = entry.get("budget")
        if not isinstance(budget, dict) or not budget:
            errors.append(f"tier_justifications.{tier}.budget must be an object")
        empty = not tiers_document.get(tier)
        if empty and not str(entry.get("empty_reason") or "").strip():
            errors.append(
                f"tier_justifications.{tier}.empty_reason must record why the "
                "tier is empty"
            )
        if not empty and entry.get("empty_reason"):
            errors.append(
                f"tier_justifications.{tier}.empty_reason must not be recorded "
                "for a populated tier"
            )

    reconciliation = document.get("reconciliation")
    if not isinstance(reconciliation, dict):
        errors.append("reconciliation must be an object")
    else:
        for key in ("workflow", "tested_head", "result", "evidence"):
            if not str(reconciliation.get(key) or "").strip():
                errors.append(f"reconciliation.{key} must be non-empty")
        if not SHA_RE.fullmatch(str(reconciliation.get("tested_head"))):
            errors.append("reconciliation.tested_head must be a full git SHA")
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(reconciliation.get("selection_manifest_sha256"))
        ):
            errors.append(
                "reconciliation.selection_manifest_sha256 must be a sha256 digest"
            )
        count = reconciliation.get("selected_model_count")
        if type(count) is not int or count < 1:
            errors.append("reconciliation.selected_model_count must be a positive int")
        categories = reconciliation.get("failure_categories")
        if not isinstance(categories, dict) or not categories:
            errors.append("reconciliation.failure_categories must be an object")
        else:
            for name, category in categories.items():
                if not isinstance(category, dict):
                    errors.append(
                        f"reconciliation.failure_categories.{name} must be an object"
                    )
                    continue
                if category.get("count") != len(category.get("models") or []):
                    errors.append(
                        f"reconciliation.failure_categories.{name}.count does not "
                        "match its models"
                    )
        added = reconciliation.get("added_models")
        if not isinstance(added, list) or not added:
            errors.append("reconciliation.added_models must be a non-empty list")
        else:
            for entry in added:
                if (
                    not isinstance(entry, dict)
                    or not str(entry.get("id") or "").strip()
                    or not str(entry.get("recorded_outcome") or "").strip()
                ):
                    errors.append(
                        "reconciliation.added_models entries require an id and a "
                        "recorded outcome"
                    )
                    continue
                if entry["id"] not in by_id:
                    errors.append(
                        f"reconciliation.added_models names unselected model "
                        f"{entry['id']!r}"
                    )
                record = by_id.get(entry["id"], {})
                if record.get("selection", {}).get("provenance") != (
                    "added-after-the-frozen-selection"
                ):
                    errors.append(
                        f"records[{entry['id']!r}].selection.provenance does not "
                        "record the addition"
                    )

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
