#!/usr/bin/env python3
"""Validate BNG3's source lock and optional reconciliation ledgers.

The ``.yml`` documents are JSON-compatible YAML. Keeping the committed format
inside the JSON subset makes this gate usable before project dependencies are
installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO / "provenance" / "upstreams.lock.yml"
REQUIRED_SOURCES = {"bng3", "bionetgen", "nfsim", "pybionetgen", "rulehub"}
RECONCILIATION_SOURCES = {"bionetgen", "nfsim", "pybionetgen"}
CLASSIFICATIONS = {
    "incorporated-identically",
    "incorporated-equivalently",
    "superseded-by-bng3",
    "not-applicable",
    "pending-port",
    "blocked-on-design",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


def load_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON-compatible YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: document root must be an object")
    return value


def _required(value: Any, keys: set[str], where: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return False
    for key in sorted(keys - value.keys()):
        errors.append(f"{where}.{key} is required")
    return True


def _date(value: Any, where: str, errors: list[str]) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        errors.append(f"{where} must be an ISO date")


def _datetime(value: Any, where: str, errors: list[str]) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        errors.append(f"{where} must be an ISO date-time")


def validate_lock(
    document: dict[str, Any], *, require_approved: bool = False
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    baseline = document.get("baseline")
    baseline_approved = False
    if _required(
        baseline,
        {"date", "status", "approved_by", "approved_at", "notes"},
        "baseline",
        errors,
    ):
        _date(baseline.get("date"), "baseline.date", errors)
        status = baseline.get("status")
        if status not in {"pending-maintainer-approval", "approved"}:
            errors.append("baseline.status is invalid")
        if status == "approved":
            baseline_approved = True
            if not baseline.get("approved_by"):
                errors.append("approved baseline requires baseline.approved_by")
            _datetime(baseline.get("approved_at"), "baseline.approved_at", errors)
        else:
            warnings.append("baseline is pending maintainer approval")
        if require_approved and status != "approved":
            errors.append("strict gate requires an approved baseline")

    sources = document.get("sources")
    if _required(sources, REQUIRED_SOURCES, "sources", errors):
        for name, source in sources.items():
            where = f"sources.{name}"
            if not _required(
                source,
                {"repository", "branch", "revision", "role", "status", "evidence"},
                where,
                errors,
            ):
                continue
            if not re.match(
                r"^https://github\.com/.+\.git$", str(source.get("repository"))
            ):
                errors.append(f"{where}.repository must be a canonical GitHub .git URL")
            if not SHA_RE.fullmatch(str(source.get("revision"))):
                errors.append(f"{where}.revision must be a full lowercase Git SHA")
            if source.get("status") not in {"observed", "accepted", "retired"}:
                errors.append(f"{where}.status is invalid")
            evidence = source.get("evidence")
            evidence_is_object = _required(
                evidence, {"kind", "checked_at"}, f"{where}.evidence", errors
            )
            if evidence_is_object:
                if evidence.get("kind") not in {
                    "planning-snapshot",
                    "local-checkout",
                    "remote-head",
                }:
                    errors.append(f"{where}.evidence.kind is invalid")
                _date(
                    evidence.get("checked_at"), f"{where}.evidence.checked_at", errors
                )
            if (
                source.get("status") == "accepted"
                and evidence_is_object
                and evidence.get("kind") == "planning-snapshot"
            ):
                errors.append(
                    f"{where} cannot be accepted from planning-snapshot evidence"
                )
            if (require_approved or baseline_approved) and source.get(
                "status"
            ) != "accepted":
                errors.append(f"strict gate requires {where}.status=accepted")

    oracles = document.get("oracles")
    if _required(oracles, {"bng2", "nfsim"}, "oracles", errors):
        for name in ("bng2", "nfsim"):
            oracle = oracles.get(name)
            where = f"oracles.{name}"
            if not _required(
                oracle,
                {"source", "status", "build_recipe", "artifact_digest"},
                where,
                errors,
            ):
                continue
            status = oracle.get("status")
            if status not in {"pending", "locked"}:
                errors.append(f"{where}.status is invalid")
            if status == "locked":
                if not oracle.get("build_recipe"):
                    errors.append(f"locked {where} requires a build_recipe")
                if not DIGEST_RE.fullmatch(str(oracle.get("artifact_digest"))):
                    errors.append(f"locked {where} requires a sha256 artifact_digest")
            if oracle.get("source") not in document.get("sources", {}):
                errors.append(f"{where}.source must name a locked source")
            if (require_approved or baseline_approved) and status != "locked":
                errors.append(f"strict gate requires {where}.status=locked")

    dependencies = document.get("dependencies")
    if _required(
        dependencies, {"compiler_images", "python_lock"}, "dependencies", errors
    ):
        images = dependencies.get("compiler_images")
        if _required(
            images, {"status", "images"}, "dependencies.compiler_images", errors
        ):
            image_values = images.get("images")
            if not isinstance(image_values, list):
                errors.append("dependencies.compiler_images.images must be an array")
            elif any(not IMAGE_RE.search(str(item)) for item in image_values):
                errors.append(
                    "each compiler image must use an immutable @sha256 digest"
                )
            if images.get("status") == "locked" and not image_values:
                errors.append("locked compiler_images requires at least one image")
            if images.get("status") not in {"pending", "locked"}:
                errors.append("dependencies.compiler_images.status is invalid")
            if (require_approved or baseline_approved) and images.get(
                "status"
            ) != "locked":
                errors.append("strict gate requires compiler_images.status=locked")

        python_lock = dependencies.get("python_lock")
        if _required(
            python_lock,
            {"status", "path", "digest"},
            "dependencies.python_lock",
            errors,
        ):
            status = python_lock.get("status")
            if status not in {"pending", "locked"}:
                errors.append("dependencies.python_lock.status is invalid")
            if status == "locked":
                if not python_lock.get("path"):
                    errors.append("locked python_lock requires a path")
                if not DIGEST_RE.fullmatch(str(python_lock.get("digest"))):
                    errors.append("locked python_lock requires a sha256 digest")
            if (require_approved or baseline_approved) and status != "locked":
                errors.append("strict gate requires python_lock.status=locked")

    return errors, warnings


def validate_ledger(document: dict[str, Any], lock: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "source",
        "represented_revision",
        "cutoff_revision",
        "owner",
        "entries",
    }
    if not _required(document, required, "ledger", errors):
        return errors
    if document.get("schema_version") != 1:
        errors.append("ledger.schema_version must be 1")
    source = document.get("source")
    if source not in RECONCILIATION_SOURCES:
        errors.append("ledger.source is invalid")
    for field in ("represented_revision", "cutoff_revision"):
        if not SHA_RE.fullmatch(str(document.get(field))):
            errors.append(f"ledger.{field} must be a full lowercase Git SHA")
    if not document.get("owner"):
        errors.append("ledger.owner must be non-empty")
    locked_source = lock.get("sources", {}).get(source, {})
    if locked_source and document.get("cutoff_revision") != locked_source.get(
        "revision"
    ):
        errors.append("ledger.cutoff_revision does not match the source lock")

    entries = document.get("entries")
    if not isinstance(entries, list):
        errors.append("ledger.entries must be an array")
        return errors
    seen: set[str] = set()
    entry_fields = {
        "source_revision",
        "capability",
        "classification",
        "bng3_reference",
        "tests",
        "reviewer",
        "rationale",
    }
    for index, entry in enumerate(entries):
        where = f"ledger.entries[{index}]"
        if not _required(entry, entry_fields, where, errors):
            continue
        revision = entry.get("source_revision")
        if not SHA_RE.fullmatch(str(revision)):
            errors.append(f"{where}.source_revision must be a full lowercase Git SHA")
        elif revision in seen:
            errors.append(f"{where}.source_revision is duplicated")
        seen.add(revision)
        if entry.get("classification") not in CLASSIFICATIONS:
            errors.append(f"{where}.classification is invalid")
        for field in ("capability", "reviewer", "rationale"):
            if not entry.get(field):
                errors.append(f"{where}.{field} must be non-empty")
        tests = entry.get("tests")
        if not isinstance(tests, list) or any(not item for item in tests):
            errors.append(f"{where}.tests must be an array of non-empty strings")
        if entry.get("classification") in {
            "incorporated-identically",
            "incorporated-equivalently",
            "superseded-by-bng3",
        } and not entry.get("bng3_reference"):
            errors.append(
                f"{where}.bng3_reference is required for incorporated or superseded commits"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--ledger", action="append", type=Path, default=[])
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()

    try:
        lock = load_document(args.lock)
        errors, warnings = validate_lock(lock, require_approved=args.require_approved)
        for ledger_path in args.ledger:
            ledger = load_document(ledger_path)
            errors.extend(
                f"{ledger_path}: {message}" for message in validate_ledger(ledger, lock)
            )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"provenance validation failed ({len(errors)} error(s))", file=sys.stderr)
        return 1
    print(f"provenance validation passed: 1 source lock, {len(args.ledger)} ledger(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
