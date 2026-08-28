"""Contract tests for the Phase 0 provenance spine."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "provenance" / "upstreams.lock.yml"
VALIDATOR = REPO / "scripts" / "validate_provenance.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.smoke
def test_pending_source_lock_is_structurally_valid():
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "pending maintainer approval" in result.stdout


def test_pending_source_lock_cannot_pass_release_gate():
    result = _run("--require-approved")
    assert result.returncode == 1
    assert "strict gate requires an approved baseline" in result.stderr


def test_source_lock_does_not_claim_unmade_decisions():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert lock["baseline"]["status"] == "pending-maintainer-approval"
    assert all(source["status"] == "observed" for source in lock["sources"].values())
    assert all(oracle["status"] == "pending" for oracle in lock["oracles"].values())


def test_malformed_revision_is_rejected(tmp_path):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["sources"]["nfsim"]["revision"] = "short"
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run("--lock", str(candidate))
    assert result.returncode == 1
    assert "sources.nfsim.revision" in result.stderr


def test_approval_cannot_hide_pending_components(tmp_path):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["baseline"].update(
        {
            "status": "approved",
            "approved_by": "maintainer",
            "approved_at": "2026-08-28T12:00:00Z",
        }
    )
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run("--lock", str(candidate))
    assert result.returncode == 1
    assert "sources.bionetgen.status=accepted" in result.stderr
    assert "oracles.bng2.status=locked" in result.stderr


def test_reconciliation_schema_has_all_plan_classifications():
    schema_path = REPO / "provenance" / "schemas" / "reconciliation-ledger.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    classifications = set(
        schema["$defs"]["entry"]["properties"]["classification"]["enum"]
    )
    assert classifications == {
        "incorporated-identically",
        "incorporated-equivalently",
        "superseded-by-bng3",
        "not-applicable",
        "pending-port",
        "blocked-on-design",
    }
