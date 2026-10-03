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


RATCHET = REPO / "provenance" / "strict-gate-ratchet.json"
RATCHET_CHECKER = REPO / "scripts" / "check_provenance_ratchet.py"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


def _run_ratchet(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RATCHET_CHECKER), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_strict_gate_ratchet_is_wired_into_ci():
    """The strict gate must be collected by a job, not merely present.

    A gate that fails and that no job runs reads as a passing gate to anyone
    who sees it in the tree. The ratchet step is what makes the strict gate's
    failure set visible on every push, so its absence is the defect this guards.
    """
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/check_provenance_ratchet.py" in workflow, (
        "no CI job runs the strict provenance ratchet; the strict gate is "
        "invisible again"
    )
    # The ratchet only helps if it is allowed to fail the job.
    lint = workflow.split("\n  lint:", 1)[1]
    assert "continue-on-error" not in lint.split("\n  #", 1)[0]


def test_strict_gate_ratchet_matches_the_live_strict_failure_set():
    """The recorded blocker set must equal what the strict gate actually raises.

    Both directions matter. A missing entry is unrecorded provenance debt; an
    extra entry means a decision was made and the ratchet is now stale.
    """
    result = _run_ratchet()
    assert result.returncode == 0, result.stderr
    recorded = set(json.loads(RATCHET.read_text(encoding="utf-8"))["errors"])
    raised = {
        line[len("ERROR: ") :]
        for line in _run("--require-approved").stderr.splitlines()
        if line.startswith("ERROR: ")
    }
    assert raised == recorded
    assert raised, "the strict gate is passing; retire the ratchet instead"


def test_strict_gate_ratchet_fails_when_a_blocker_is_unrecorded(tmp_path):
    """A new unapproved source must be caught, not absorbed by a stale ratchet."""
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["sources"]["ratchet-probe"] = dict(lock["sources"]["bng3"])
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run_ratchet("--lock", str(candidate))
    assert result.returncode == 1
    assert "strict gate requires sources.ratchet-probe.status=accepted" in result.stderr


def test_strict_gate_ratchet_fails_when_a_blocker_is_resolved(tmp_path):
    """Approving a source must not silently leave a stale entry behind."""
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["sources"]["bngsim"]["status"] = "accepted"
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run_ratchet("--lock", str(candidate))
    assert result.returncode == 1
    assert "is stale" in result.stderr
    assert "strict gate requires sources.bngsim.status=accepted" in result.stderr


def test_strict_gate_ratchet_fails_when_the_strict_gate_starts_passing(tmp_path):
    """A green strict gate must not be silently hidden by a stale ratchet.

    This is the case that retires the ratchet, and it is the one most likely
    to be "fixed" by deleting entries instead of by recording the decision.
    """
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    lock["baseline"].update(
        status="approved",
        approved_by="maintainer",
        approved_at="2026-08-28T12:00:00Z",
    )
    for source in lock["sources"].values():
        source["status"] = "accepted"
    # rulehub cannot be accepted from planning-snapshot evidence, so a genuine
    # approval has to re-verify it against the remote first.
    lock["sources"]["rulehub"]["evidence"]["kind"] = "remote-head"
    for oracle in lock["oracles"].values():
        oracle.update(
            status="locked", build_recipe="make", artifact_digest="sha256:" + "a" * 64
        )
    lock["dependencies"]["compiler_images"].update(
        status="locked", images=["ghcr.io/ruleworld/bng3@sha256:" + "b" * 64]
    )
    lock["dependencies"]["python_lock"].update(
        status="locked", path="requirements.lock", digest="sha256:" + "c" * 64
    )
    candidate = tmp_path / "upstreams.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")

    # Precondition: the approved lock really does pass the strict gate.
    assert _run("--lock", str(candidate), "--require-approved").returncode == 0

    result = _run_ratchet("--lock", str(candidate))
    assert result.returncode == 1
    assert "the strict provenance gate now passes" in result.stderr
