"""Replay per-case resume for a locked canonical-BNG2 corpus shard.

This is a bounded replay of the corpus runner's per-case resume path.  It uses
the real locked case IDs, source digests and BNG2 oracle identity, and records
observed command invocations and verdicts.  The engine call is replaced by a
digest-aware recording oracle so the replay is deterministic and needs no
external binaries; it does not claim scientific parity.  See
``tests/validation/test_corpus_resume.py`` for the focused regression.

Example (from the repository root)::

    PYTHONPATH=python:build/cpp python scripts/ci/replay_corpus_shard_resume.py \
      --evidence-dir /tmp/bng3-corpus-replay.XXXX/evidence
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.validation import conformance, corpus_resume  # noqa: E402

DEFAULT_CASES = ("michment", "simple_system")


def _load_locked():
    selection = json.loads((REPO / "provenance/corpus/selection.json").read_text())
    lock = json.loads((REPO / "provenance/upstreams.lock.yml").read_text())
    records = {row["id"]: row for row in selection["records"]}
    source = lock["sources"]["bionetgen"]
    oracle = {
        "bionetgen": {
            "repository": source["repository"],
            "revision": source["revision"],
            "script": "recording-oracle://BNG2.pl",
        }
    }
    return records, selection, oracle


def _install_oracle(verdicts, calls):
    def fake_model(name, source_path, args, directory, reference, env):
        calls[name] = calls.get(name, 0) + 1
        digest = "sha256:" + hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
        return [
            {
                "id": f"{name}:parse",
                "stage": "parse",
                "status": verdicts[name],
                "detail": "recording-oracle verdict",
                "model": name,
                "source_sha256": digest,
            },
            {
                "id": f"{name}:network",
                "stage": "bounded-network",
                "status": verdicts[name],
                "detail": "recording-oracle verdict",
                "model": name,
            },
        ]

    conformance._model = fake_model


def _run_case(directory, case, *, records, candidate, config, oracle, resume):
    args = SimpleNamespace(resume=resume, simulate=False, net_reload=False)
    return conformance._resume_case(
        case,
        REPO / records[case]["path"],
        args,
        directory,
        copy.deepcopy(oracle),
        {},
        source_sha256=records[case]["sha256"],
        candidate_sha256=candidate,
        expected_contract_ids=[f"{case}:parse", f"{case}:network"],
        resume_configuration=config,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=list(DEFAULT_CASES))
    args = parser.parse_args(argv)

    evidence = args.evidence_dir.resolve()
    if evidence.exists() and any(evidence.iterdir()):
        parser.error("evidence directory must be fresh")
    evidence.mkdir(parents=True)
    records, selection, oracle = _load_locked()
    missing = [case for case in args.cases if case not in records]
    if missing:
        parser.error("unknown locked case IDs: " + ", ".join(missing))

    candidate_bytes = b"candidate-under-test\n"
    candidate = "sha256:" + hashlib.sha256(candidate_bytes).hexdigest()
    config = {
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
    verdicts = {case: "PASS" for case in args.cases}
    calls: dict[str, int] = {}
    _install_oracle(verdicts, calls)

    record = {
        "schema_version": 1,
        "source_revision": conformance.campaign.git(REPO, "rev-parse", "HEAD"),
        "selection_digest": "sha256:"
        + hashlib.sha256(
            (REPO / "provenance/corpus/selection.json").read_bytes()
        ).hexdigest(),
        "candidate_sha256": candidate,
        "oracle_identity": oracle,
        "configuration": config,
        "cases": {},
        "phases": {},
    }

    # Phase 1: a clean run of the shard.
    clean_dir = evidence / "clean"
    clean_rows = {}
    for case in args.cases:
        rows, action = _run_case(
            clean_dir,
            case,
            records=records,
            candidate=candidate,
            config=config,
            oracle=oracle,
            resume=False,
        )
        clean_rows[case] = rows
    record["phases"]["clean"] = {"invocations": dict(calls), "actions": "executed"}

    # Phase 2: an interrupted run -- complete the shard, then withhold one
    # finished case artifact.
    interrupted_dir = evidence / "interrupted"
    for case in args.cases:
        _run_case(
            interrupted_dir,
            case,
            records=records,
            candidate=candidate,
            config=config,
            oracle=oracle,
            resume=False,
        )
    withheld = args.cases[-1]
    withheld_path = corpus_resume.artifact_path(interrupted_dir, withheld)
    withheld_path.rename(evidence / ("withheld-" + withheld + ".json"))
    before_resume = dict(calls)

    # Phase 3: resume the interrupted shard.
    resumed_rows = {}
    actions = {}
    for case in args.cases:
        rows, action = _run_case(
            interrupted_dir,
            case,
            records=records,
            candidate=candidate,
            config=config,
            oracle=oracle,
            resume=True,
        )
        resumed_rows[case] = rows
        actions[case] = action
    record["phases"]["resume"] = {
        "invocations_before": before_resume,
        "invocations_after": dict(calls),
        "actions": actions,
    }

    # Phase 4: stale control -- copy a finished artifact, alter its candidate
    # SHA and forge PASS verdicts, then resume. A stale artifact may not pass.
    stale_dir = evidence / "stale-control"
    stale_case = args.cases[0]
    verdicts[stale_case] = "FAIL"
    stale_path = corpus_resume.artifact_path(stale_dir, stale_case)
    stale_path.parent.mkdir(parents=True)
    payload = json.loads(
        corpus_resume.artifact_path(clean_dir, stale_case).read_text(encoding="utf-8")
    )
    payload["rows"] = [dict(row, status="PASS") for row in payload["rows"]]
    payload["rows_sha256"] = corpus_resume._rows_digest(payload["rows"])
    payload["identity"]["candidate_sha256"] = "sha256:" + "c" * 64
    payload["identity"]["key"] = corpus_resume._digest(
        {k: v for k, v in payload["identity"].items() if k != "key"}
    )
    stale_path.write_text(json.dumps(payload), encoding="utf-8")
    stale_rows, stale_action = _run_case(
        stale_dir,
        stale_case,
        records=records,
        candidate=candidate,
        config=config,
        oracle=oracle,
        resume=True,
    )
    record["phases"]["stale_control"] = {
        "action": stale_action,
        "verdicts": [row["status"] for row in stale_rows],
    }

    for case in args.cases:
        record["cases"][case] = {
            "source_sha256": records[case]["sha256"],
            "source_path": records[case]["path"],
            "tiers": records[case]["tiers"],
            "clean_verdicts": [row["status"] for row in clean_rows[case]],
            "resume_verdicts": [row["status"] for row in resumed_rows[case]],
            "verdicts_match_clean": resumed_rows[case] == clean_rows[case],
        }

    (evidence / "replay.json").write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "evidence": str(evidence),
                "cases": list(args.cases),
                "resume_actions": actions,
                "stale_action": stale_action,
                "stale_verdicts": [row["status"] for row in stale_rows],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
