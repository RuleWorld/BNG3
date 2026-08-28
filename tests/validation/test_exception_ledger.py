"""Self-tests for the machine-readable expected-failure policy."""

from __future__ import annotations

import json
from datetime import date

import pytest

from tests.validation import exception_ledger


def _write_ledger(tmp_path, document):
    path = tmp_path / "exceptions.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_repository_exception_ledger_is_valid():
    ledger = exception_ledger.load_ledger(as_of=date(2026, 8, 28))
    exception_ledger.validate_references(ledger)

    assert len(ledger.exceptions) == 1
    entry = ledger.find(
        "test_parity_net.py::test_net_parity_smoke[blbr]",
        "blbr",
        "network_generation",
    )
    assert entry is not None
    assert entry.matches_failure(
        "net mismatch [blbr] (ref=golden):\n" "reactions: ref=66 test=92 (delta=+26)"
    )
    assert not entry.matches_failure(
        "net mismatch [blbr] (ref=golden):\n" "reactions: ref=67 test=92 (delta=+25)"
    )


def test_strict_exception_rejects_unexpected_pass():
    ledger = exception_ledger.load_ledger(as_of=date(2026, 8, 28))
    entry = ledger.exceptions[0]

    with pytest.raises(pytest.fail.Exception, match="unexpected pass"):
        with exception_ledger.strict_expected_failure(entry):
            pass


def test_strict_exception_does_not_hide_a_different_failure():
    ledger = exception_ledger.load_ledger(as_of=date(2026, 8, 28))
    entry = ledger.exceptions[0]

    with pytest.raises(AssertionError, match="engine produced no .net"):
        with exception_ledger.strict_expected_failure(entry):
            raise AssertionError("engine produced no .net")


def test_ledger_rejects_missing_required_field(tmp_path):
    document = json.loads(exception_ledger.LEDGER_PATH.read_text(encoding="utf-8"))
    del document["exceptions"][0]["owner"]

    with pytest.raises(exception_ledger.LedgerError, match="owner"):
        exception_ledger.load_ledger(
            _write_ledger(tmp_path, document), as_of=date(2026, 8, 28)
        )


def test_ledger_rejects_overdue_review(tmp_path):
    document = json.loads(exception_ledger.LEDGER_PATH.read_text(encoding="utf-8"))

    with pytest.raises(exception_ledger.LedgerError, match="review overdue"):
        exception_ledger.load_ledger(
            _write_ledger(tmp_path, document), as_of=date(2026, 11, 27)
        )


def test_ledger_rejects_duplicate_assignment(tmp_path):
    document = json.loads(exception_ledger.LEDGER_PATH.read_text(encoding="utf-8"))
    duplicate = dict(document["exceptions"][0])
    duplicate["id"] = "duplicate-id"
    document["exceptions"].append(duplicate)

    with pytest.raises(
        exception_ledger.LedgerError, match="duplicate exception assignment"
    ):
        exception_ledger.load_ledger(
            _write_ledger(tmp_path, document), as_of=date(2026, 8, 28)
        )
