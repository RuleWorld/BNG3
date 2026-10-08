"""Contract tests for the Phase 0 provenance spine."""

from __future__ import annotations

import json
import hashlib
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


def test_ssts_revision_is_locked_without_approving_the_source_baseline():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    suite = lock["sources"]["sbml-test-suite"]

    assert suite == {
        "repository": "https://github.com/sbmlteam/sbml-test-suite.git",
        "branch": "3.5.0",
        "revision": "cf38585fac5de8e0e90112febb62851ee2181816",
        "role": "official-validation-corpus-not-oracle",
        "status": "observed",
        "evidence": {"kind": "remote-commit", "checked_at": "2026-10-08"},
    }
    assert lock["baseline"]["status"] == "pending-maintainer-approval"


def test_malformed_revision_is_rejected(tmp_path):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["sources"]["nfsim"]["revision"] = "short"
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run("--lock", str(candidate))
    assert result.returncode == 1
    assert "sources.nfsim.revision" in result.stderr


def test_malformed_evidence_is_rejected_without_traceback(tmp_path):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["sources"]["nfsim"]["evidence"] = None
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run("--lock", str(candidate))
    assert result.returncode == 1
    assert "sources.nfsim.evidence must be an object" in result.stderr
    assert "Traceback" not in result.stderr


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


def test_reachable_historical_commit_is_valid_source_evidence(tmp_path):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["sources"]["bngplayground"]["evidence"] = {
        "kind": "remote-commit",
        "checked_at": "2026-10-08",
    }
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run("--lock", str(candidate))
    assert result.returncode == 0, result.stderr


def test_claimed_python_lock_digest_cannot_hide_a_missing_file(tmp_path):
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["dependencies"]["python_lock"] = {
        "status": "locked",
        "path": "provenance/dependencies/does-not-exist.lock",
        "digest": "sha256:" + "0" * 64,
    }
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run("--lock", str(candidate))
    assert result.returncode == 1
    assert "python_lock" in result.stderr


@pytest.mark.parametrize("mutation", ["missing", "modified", "directory", "outside"])
def test_locked_python_dependency_bytes_are_verified(tmp_path, mutation):
    from scripts.validate_provenance import validate_lock

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    root = tmp_path / "repo"
    root.mkdir()
    artifact = root / "requirements.lock"
    payload = b"pytest==8.4.2\n"
    artifact.write_bytes(payload)
    lock["dependencies"]["python_lock"] = {
        "status": "locked",
        "path": "requirements.lock",
        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }
    errors, _ = validate_lock(lock, repository_root=root)
    assert not errors

    if mutation == "missing":
        artifact.unlink()
    elif mutation == "modified":
        artifact.write_bytes(b"pytest==7.0.0\n")
    elif mutation == "directory":
        artifact.unlink()
        artifact.mkdir()
    else:
        outside = tmp_path / "outside.lock"
        outside.write_bytes(payload)
        lock["dependencies"]["python_lock"]["path"] = "../outside.lock"

    errors, _ = validate_lock(lock, repository_root=root)
    assert any("python_lock" in error for error in errors), errors
