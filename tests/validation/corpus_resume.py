"""Identity-checked per-case resume artifacts for the corpus shard runner.

A corpus shard writes one immutable artifact per case beside the case's other
outputs.  An artifact is reusable only when its complete identity -- case ID,
source digest, candidate (subject) SHA, oracle identity, configuration and the
expected check IDs -- matches the run requesting resume, and when its stored
verdicts are intact.  Stale, copied, malformed or partial artifacts are never
reused: the case is executed fresh instead.  Verdict rows are copied verbatim,
so PASS / FAIL / UNSUPPORTED / INVALID_INPUT / TIMEOUT / HARNESS_ERROR stay
distinct and NOT_TESTED is never mistaken for completed work.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

ARTIFACT_NAME = "case-result.json"
SCHEMA_VERSION = 1

# Mirrors campaign.STATUSES without importing that module (no cyclic deps).
STATUSES = (
    "PASS",
    "FAIL",
    "UNSUPPORTED",
    "NOT_TESTED",
    "INVALID_INPUT",
    "TIMEOUT",
    "HARNESS_ERROR",
)

# A case that still contains an unexecuted check is not completed work.
_TERMINAL = frozenset(STATUSES) - {"NOT_TESTED"}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def case_identity(
    case_id: str,
    *,
    source_sha256: str,
    candidate_sha256: str | None,
    oracle_identity: dict,
    configuration: dict,
    expected_contract_ids: list[str],
) -> dict:
    """Build the complete, comparable identity of one corpus case execution."""
    identity = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "source_sha256": source_sha256,
        "candidate_sha256": candidate_sha256,
        "oracle_identity": copy.deepcopy(oracle_identity),
        "configuration": copy.deepcopy(configuration),
        "expected_contract_ids": list(expected_contract_ids),
    }
    identity["key"] = _digest({k: v for k, v in identity.items() if k != "key"})
    return identity


def artifact_path(directory: Path, case_id: str) -> Path:
    """Return the per-case artifact path used by the corpus runner."""
    return directory / "models" / case_id / ARTIFACT_NAME


def _rows_digest(rows: list[dict]) -> str:
    return _digest(rows)


def save(directory: Path, identity: dict, rows: list[dict]) -> Path:
    """Persist a completed case and its identity; return the artifact path."""
    path = artifact_path(directory, identity["case_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "rows_sha256": _rows_digest(rows),
        "rows": copy.deepcopy(rows),
    }
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return path


def load(directory: Path, identity: dict) -> tuple[list[dict] | None, str]:
    """Return (rows, reason) for a requested case.

    reason is one of ``hit``, ``missing``, ``stale`` or ``invalid``.  Only
    ``hit`` returns non-None rows; every other reason forces fresh execution.
    """
    path = artifact_path(directory, identity["case_id"])
    if not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "invalid"
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None, "invalid"
    recorded = payload.get("identity")
    rows = payload.get("rows")
    if not isinstance(recorded, dict) or not isinstance(rows, list):
        return None, "invalid"
    # Do not trust a stored key: recompute it from the recorded fields so a
    # copied artifact with one altered identity field cannot masquerade as a
    # matching one.
    recomputed = _digest({k: v for k, v in recorded.items() if k != "key"})
    if recomputed != recorded.get("key"):
        return None, "invalid"
    if (
        recorded.get("key") != identity["key"]
        or recorded.get("case_id") != identity["case_id"]
    ):
        return None, "stale"
    if payload.get("rows_sha256") != _rows_digest(rows):
        return None, "invalid"
    prefix = identity["case_id"] + ":"
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in _TERMINAL:
            return None, "invalid"
        if not str(row.get("id", "")).startswith(prefix):
            return None, "invalid"
    return copy.deepcopy(rows), "hit"


def reuse_or_execute(
    directory: Path,
    identity: dict,
    execute: Callable[[], list[dict]],
    *,
    enabled: bool,
    before_execute: Callable[[], None] | None = None,
) -> tuple[list[dict], str]:
    """Reuse a matching artifact or execute the case and persist its verdicts.

    ``before_execute`` is called only when the case will actually run.  The
    runner uses it to clear leftover staged outputs from an interrupted case:
    without it, re-execution collides with directories such as ``original``
    that the case runner creates from scratch.
    """
    cached, reason = load(directory, identity)
    if enabled and cached is not None:
        return cached, "reused"
    if before_execute is not None:
        before_execute()
    rows = execute()
    if not isinstance(rows, list):
        raise TypeError("case execution must return a list of verdict rows")
    save(directory, identity, rows)
    if reason == "stale":
        return rows, "stale-discarded-and-executed"
    if reason == "invalid":
        return rows, "invalid-discarded-and-executed"
    return rows, "executed"
