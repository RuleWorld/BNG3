"""Per-case corpus shard resume: reuse, interruption and stale-artifact control.

These tests drive the real corpus runner helper (:func:`conformance._resume_case`)
with real locked case IDs and digests.  Command execution is replaced by a
recording oracle stub, so the assertions are about observed invocations and
the exact verdict rows that survive a resume -- not about filenames.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.validation import conformance, corpus_resume

REPO = Path(__file__).resolve().parents[2]
SELECTION = REPO / "provenance" / "corpus" / "selection.json"
LOCK = REPO / "provenance" / "upstreams.lock.yml"

# A small existing canonical-BNG2 shard: two tier-S cases with locked digests.
CASE_IDS = ("michment", "simple_system")


def _records() -> dict:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in selection["records"]}
    assert set(CASE_IDS) <= set(by_id)
    assert set(CASE_IDS) <= set(selection["tiers"]["s"])
    return by_id


def _oracle_identity() -> dict:
    """Independently pinned BNG2 identity from the accepted source lock."""
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    source = lock["sources"]["bionetgen"]
    return {
        "bionetgen": {
            "repository": source["repository"],
            "revision": source["revision"],
            "script": "/oracle/bionetgen/bng2/BNG2.pl",
            "script_sha256": "sha256:" + "b" * 64,
        }
    }


def _candidate(tmp_path: Path) -> str:
    binary = tmp_path / "bng_cpp-stub"
    binary.write_bytes(b"candidate-under-test\n")
    return "sha256:" + hashlib.sha256(binary.read_bytes()).hexdigest()


def _config() -> dict:
    return {
        "tiers": ["smoke"],
        "corpus_tier": "s",
        "shard": [0, 1],
        "case_timeout": 30,
        "network_iterations": 4,
        "max_aggregate": 8,
        "simulate": False,
        "net_reload": False,
        "package_mode": "source",
    }


def _expected(case: str) -> list[str]:
    return [f"{case}:parse", f"{case}:network"]


def _install_oracle(monkeypatch, verdicts: dict[str, str], calls: dict[str, int]):
    """Replace the real engine with a digest-aware, invocation-recording oracle."""

    def fake_model(name, source, args, directory, reference, env):
        calls[name] = calls.get(name, 0) + 1
        # The oracle consumes the real locked source, so a stale source digest
        # cannot be substituted without changing the recorded invocation.
        digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        assert digest == _records()[name]["sha256"]
        assert reference is not None
        return [
            {
                "id": f"{name}:parse",
                "stage": "parse",
                "status": verdicts[name],
                "detail": "recorded oracle verdict",
                "model": name,
                "digest": digest,
            },
            {
                "id": f"{name}:network",
                "stage": "bounded-network",
                "status": verdicts[name],
                "detail": "recorded oracle verdict",
                "model": name,
            },
        ]

    monkeypatch.setattr(conformance, "_model", fake_model)


def _run_case(directory, case, *, records, candidate, resume, config):
    args = SimpleNamespace(resume=resume, simulate=False, net_reload=False)
    return conformance._resume_case(
        case,
        REPO / records[case]["path"],
        args,
        directory,
        copy.deepcopy(_oracle_identity()),
        {},
        source_sha256=records[case]["sha256"],
        candidate_sha256=candidate,
        expected_contract_ids=_expected(case),
        resume_configuration=config,
    )


def test_resume_reuses_completed_case_and_executes_withheld_case(tmp_path, monkeypatch):
    """A clean shard, a withheld finished case, then an identity-checked resume."""
    records, candidate, config = _records(), _candidate(tmp_path), _config()
    calls: dict[str, int] = {}
    _install_oracle(monkeypatch, {"michment": "PASS", "simple_system": "PASS"}, calls)

    clean = tmp_path / "clean"
    clean_rows = {}
    for case in CASE_IDS:
        rows, action = _run_case(
            clean,
            case,
            records=records,
            candidate=candidate,
            resume=False,
            config=config,
        )
        assert action == "executed"
        clean_rows[case] = rows
    assert calls["michment"] == calls["simple_system"] == 1

    # Reproduce an interrupted shard: keep the finished artifact for one case,
    # withhold the finished artifact for the other.
    interrupted = tmp_path / "interrupted"
    for case in CASE_IDS:
        _run_case(
            interrupted,
            case,
            records=records,
            candidate=candidate,
            resume=False,
            config=config,
        )
    withheld = corpus_resume.artifact_path(interrupted, "simple_system")
    assert withheld.is_file()
    withheld.unlink()

    before = dict(calls)
    resumed_rows = {}
    for case in CASE_IDS:
        rows, action = _run_case(
            interrupted,
            case,
            records=records,
            candidate=candidate,
            resume=True,
            config=config,
        )
        resumed_rows[case] = rows
        assert action == ("reused" if case == "michment" else "executed")

    # Observed invocations, not filename presence: the completed case was not
    # re-executed and the missing case was executed exactly once more.
    assert calls["michment"] == before["michment"]
    assert calls["simple_system"] == before["simple_system"] + 1
    for case in CASE_IDS:
        assert resumed_rows[case] == clean_rows[case]
        assert [r["status"] for r in resumed_rows[case]] == ["PASS", "PASS"]


def test_copied_artifact_with_altered_identity_cannot_yield_a_pass(
    tmp_path, monkeypatch
):
    """A copied artifact whose candidate SHA changed is stale, not a pass."""
    records, candidate, config = _records(), _candidate(tmp_path), _config()
    calls: dict[str, int] = {}
    _install_oracle(monkeypatch, {"michment": "FAIL"}, calls)

    source_dir = tmp_path / "source"
    rows, action = _run_case(
        source_dir,
        "michment",
        records=records,
        candidate=candidate,
        resume=False,
        config=config,
    )
    assert action == "executed"
    assert [r["status"] for r in rows] == ["FAIL", "FAIL"]

    # Copy the artifact into a fresh evidence directory and alter one relevant
    # identity: the candidate SHA. The copied rows still say PASS so a naive
    # filename/manifest check would incorrectly accept them.
    copied = tmp_path / "stale"
    path = corpus_resume.artifact_path(copied, "michment")
    path.parent.mkdir(parents=True)
    payload = json.loads(
        corpus_resume.artifact_path(source_dir, "michment").read_text(encoding="utf-8")
    )
    payload["rows"] = [
        dict(row, status="PASS", detail="forged stale pass") for row in payload["rows"]
    ]
    payload["rows_sha256"] = corpus_resume._rows_digest(payload["rows"])
    payload["identity"]["candidate_sha256"] = "sha256:" + "c" * 64
    payload["identity"]["key"] = corpus_resume._digest(
        {k: v for k, v in payload["identity"].items() if k != "key"}
    )
    path.write_text(json.dumps(payload), encoding="utf-8")

    stale_rows, stale_action = _run_case(
        copied,
        "michment",
        records=records,
        candidate=candidate,
        resume=True,
        config=config,
    )
    assert stale_action == "stale-discarded-and-executed"
    assert [r["status"] for r in stale_rows] == ["FAIL", "FAIL"]
    assert calls["michment"] == 2  # original run plus fresh re-execution
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["identity"]["candidate_sha256"] == candidate
    assert [r["status"] for r in stored["rows"]] == ["FAIL", "FAIL"]


@pytest.mark.parametrize(
    "status", ["FAIL", "UNSUPPORTED", "TIMEOUT", "INVALID_INPUT", "HARNESS_ERROR"]
)
def test_resume_preserves_non_pass_verdicts(tmp_path, monkeypatch, status):
    """Resume must not collapse failure/unsupported/timeout/invalid-source."""
    records, candidate, config = _records(), _candidate(tmp_path), _config()
    calls: dict[str, int] = {}
    _install_oracle(monkeypatch, {"michment": status}, calls)

    directory = tmp_path / status.lower()
    first, first_action = _run_case(
        directory,
        "michment",
        records=records,
        candidate=candidate,
        resume=False,
        config=config,
    )
    second, second_action = _run_case(
        directory,
        "michment",
        records=records,
        candidate=candidate,
        resume=True,
        config=config,
    )
    assert first_action == "executed"
    assert second_action == "reused"
    assert second == first
    assert [r["status"] for r in second] == [status, status]
    assert calls["michment"] == 1


def test_partial_not_tested_artifact_is_not_reused(tmp_path, monkeypatch):
    """An artifact containing NOT_TESTED is incomplete and must be re-executed."""
    records, candidate, config = _records(), _candidate(tmp_path), _config()
    calls: dict[str, int] = {}
    _install_oracle(monkeypatch, {"michment": "PASS"}, calls)

    directory = tmp_path / "partial"
    _run_case(
        directory,
        "michment",
        records=records,
        candidate=candidate,
        resume=False,
        config=config,
    )
    path = corpus_resume.artifact_path(directory, "michment")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][1]["status"] = "NOT_TESTED"
    payload["rows_sha256"] = corpus_resume._rows_digest(payload["rows"])
    path.write_text(json.dumps(payload), encoding="utf-8")

    rows, action = _run_case(
        directory,
        "michment",
        records=records,
        candidate=candidate,
        resume=True,
        config=config,
    )
    assert action == "invalid-discarded-and-executed"
    assert [r["status"] for r in rows] == ["PASS", "PASS"]
    assert calls["michment"] == 2
