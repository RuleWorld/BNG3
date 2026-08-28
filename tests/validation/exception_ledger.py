"""Validated, strict expected-failure ledger for scientific parity tests."""

from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import pytest

from tests.validation import corpus

LEDGER_PATH = Path(__file__).with_name("exceptions.json")

_REQUIRED_ENTRY_FIELDS = {
    "id",
    "model",
    "tests",
    "method",
    "platforms",
    "issue_url",
    "technical_reason",
    "owner",
    "introduced_on",
    "review_by",
    "expected_failure_signature",
}


class LedgerError(ValueError):
    """The exception ledger is incomplete, ambiguous, or expired."""


@dataclass(frozen=True)
class ExpectedFailure:
    id: str
    model: str
    tests: tuple[str, ...]
    method: str
    platforms: tuple[str, ...]
    issue_url: str
    technical_reason: str
    owner: str
    introduced_on: date
    review_by: date
    expected_failure_signature: str

    def applies_to(self, test_id: str, model: str, method: str, platform: str) -> bool:
        platform_matches = "all" in self.platforms or platform in self.platforms
        return (
            test_id in self.tests
            and model == self.model
            and method == self.method
            and platform_matches
        )

    def matches_failure(self, message: str) -> bool:
        return re.search(self.expected_failure_signature, message) is not None


@dataclass(frozen=True)
class ExceptionLedger:
    schema_version: int
    exceptions: tuple[ExpectedFailure, ...]

    def find(
        self,
        test_id: str,
        model: str,
        method: str,
        platform: str = sys.platform,
    ) -> ExpectedFailure | None:
        matches = [
            entry
            for entry in self.exceptions
            if entry.applies_to(test_id, model, method, platform)
        ]
        if len(matches) > 1:
            raise LedgerError(f"multiple exceptions apply to {test_id}")
        return matches[0] if matches else None


def _nonempty_string(raw: dict, field: str, entry_id: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{entry_id}: {field} must be a non-empty string")
    return value


def _string_list(raw: dict, field: str, entry_id: str) -> tuple[str, ...]:
    value = raw[field]
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise LedgerError(f"{entry_id}: {field} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise LedgerError(f"{entry_id}: {field} contains duplicates")
    return tuple(value)


def _iso_date(value: str, field: str, entry_id: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LedgerError(f"{entry_id}: {field} must be an ISO date") from exc


def _parse_entry(raw: object, as_of: date) -> ExpectedFailure:
    if not isinstance(raw, dict):
        raise LedgerError("each exception must be an object")
    entry_id = raw.get("id", "<missing id>")
    if set(raw) != _REQUIRED_ENTRY_FIELDS:
        missing = sorted(_REQUIRED_ENTRY_FIELDS - set(raw))
        unknown = sorted(set(raw) - _REQUIRED_ENTRY_FIELDS)
        raise LedgerError(f"{entry_id}: missing={missing}, unknown={unknown}")

    entry_id = _nonempty_string(raw, "id", str(entry_id))
    tests = _string_list(raw, "tests", entry_id)
    platforms = _string_list(raw, "platforms", entry_id)
    if "all" in platforms and len(platforms) != 1:
        raise LedgerError(f"{entry_id}: platform 'all' cannot be combined with others")

    issue_url = _nonempty_string(raw, "issue_url", entry_id)
    parsed_url = urlparse(issue_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise LedgerError(f"{entry_id}: issue_url must be an absolute HTTPS URL")

    introduced_on = _iso_date(
        _nonempty_string(raw, "introduced_on", entry_id), "introduced_on", entry_id
    )
    review_by = _iso_date(
        _nonempty_string(raw, "review_by", entry_id), "review_by", entry_id
    )
    if review_by < introduced_on:
        raise LedgerError(f"{entry_id}: review_by precedes introduced_on")
    if review_by < as_of:
        raise LedgerError(f"{entry_id}: review overdue since {review_by.isoformat()}")

    signature = _nonempty_string(raw, "expected_failure_signature", entry_id)
    try:
        re.compile(signature)
    except re.error as exc:
        raise LedgerError(f"{entry_id}: invalid expected_failure_signature") from exc

    return ExpectedFailure(
        id=entry_id,
        model=_nonempty_string(raw, "model", entry_id),
        tests=tests,
        method=_nonempty_string(raw, "method", entry_id),
        platforms=platforms,
        issue_url=issue_url,
        technical_reason=_nonempty_string(raw, "technical_reason", entry_id),
        owner=_nonempty_string(raw, "owner", entry_id),
        introduced_on=introduced_on,
        review_by=review_by,
        expected_failure_signature=signature,
    )


def load_ledger(path: Path = LEDGER_PATH, as_of: date | None = None) -> ExceptionLedger:
    """Load and validate the exception ledger, including its review dates."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read exception ledger {path}: {exc}") from exc

    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "exceptions",
    }:
        raise LedgerError("ledger must contain exactly schema_version and exceptions")
    if document["schema_version"] != 1:
        raise LedgerError(f"unsupported schema_version: {document['schema_version']!r}")
    if not isinstance(document["exceptions"], list):
        raise LedgerError("exceptions must be a list")

    entries = tuple(
        _parse_entry(raw, as_of or date.today()) for raw in document["exceptions"]
    )
    ids = [entry.id for entry in entries]
    if len(ids) != len(set(ids)):
        raise LedgerError("exception ids must be unique")

    assignments: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        for test_id in entry.tests:
            for platform in entry.platforms:
                assignment = (test_id, entry.model, entry.method, platform)
                if assignment in assignments:
                    raise LedgerError(f"duplicate exception assignment: {assignment}")
                assignments.add(assignment)
    return ExceptionLedger(schema_version=1, exceptions=entries)


def validate_references(ledger: ExceptionLedger) -> None:
    """Require ledger models and test functions to exist in this checkout."""
    for entry in ledger.exceptions:
        if corpus.resolve(entry.model) is None:
            raise LedgerError(f"{entry.id}: model not found: {entry.model}")
        for test_id in entry.tests:
            path_text, separator, test_text = test_id.partition("::")
            function_name = test_text.split("[", 1)[0]
            test_path = Path(path_text)
            if (
                not separator
                or test_path.is_absolute()
                or ".." in test_path.parts
                or not function_name.startswith("test_")
            ):
                raise LedgerError(f"{entry.id}: invalid test identity: {test_id}")
            source_path = Path(__file__).parent / test_path
            if not source_path.is_file():
                raise LedgerError(f"{entry.id}: test file not found: {path_text}")
            source = source_path.read_text(encoding="utf-8")
            if (
                re.search(rf"^def {re.escape(function_name)}\(", source, re.MULTILINE)
                is None
            ):
                raise LedgerError(
                    f"{entry.id}: test function not found: {function_name}"
                )


@contextmanager
def strict_expected_failure(entry: ExpectedFailure | None) -> Iterator[None]:
    """Xfail only the declared assertion signature; fail on an unexpected pass."""
    if entry is None:
        yield
        return

    try:
        yield
    except AssertionError as exc:
        if not entry.matches_failure(str(exc)):
            raise
        pytest.xfail(f"{entry.id}: {entry.technical_reason}")
    else:
        pytest.fail(f"unexpected pass for {entry.id}; remove the ledger entry")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-exceptions", type=int, default=None)
    args = parser.parse_args(argv)

    ledger = load_ledger()
    validate_references(ledger)
    count = len(ledger.exceptions)
    if args.max_exceptions is not None and count > args.max_exceptions:
        raise LedgerError(
            f"exception budget exceeded: active={count}, maximum={args.max_exceptions}"
        )
    print(f"exception ledger valid: {count} active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
