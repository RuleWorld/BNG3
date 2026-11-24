"""Controls for the #181 corpus release consumers (not product-support evidence)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corpus_release_checks as checks  # noqa: E402

REVISION = "e" * 40


def _receipt(revision=REVISION):
    return {
        "schema_version": 1,
        "source_revision": revision,
        "phases": {
            "resume": {"actions": {"michment": "reused"}},
            "stale_control": {"action": "stale-discarded-and-executed"},
        },
    }


def test_corpus_tiers_and_identities_are_complete():
    assert checks.coverage_gaps() == []


def test_results_require_every_case_and_a_partial_replay(tmp_path):
    selection = json.loads(
        (checks.ROOT / "provenance/corpus/selection.json").read_text()
    )
    report = {
        "source": {"revision": REVISION, "dirty": False},
        "results": [
            {
                "id": f"corpus-case[{row['id']}]",
                "status": "PASS",
                "supported_execution": True,
                "evidence_kind": "supported-execution",
            }
            for row in selection["records"]
        ],
    }
    assert checks.result_gaps([report], REVISION, [_receipt()]) == []


@pytest.mark.parametrize(
    "mutation", ["missing-case", "stale-report", "no-reuse", "conflict"]
)
def test_results_reject_incomplete_or_unverifiable_evidence(mutation):
    selection = json.loads(
        (checks.ROOT / "provenance/corpus/selection.json").read_text()
    )
    results = [
        {
            "id": f"corpus-case[{row['id']}]",
            "status": "PASS",
            "supported_execution": True,
            "evidence_kind": "supported-execution",
        }
        for row in selection["records"]
    ]
    receipt = _receipt()
    revision = REVISION
    if mutation == "missing-case":
        results = results[1:]
    elif mutation == "stale-report":
        revision = "f" * 40
    elif mutation == "no-reuse":
        receipt["phases"]["resume"]["actions"] = {"michment": "executed"}
    else:
        results.append(dict(results[0], status="FAIL"))
    report = {"source": {"revision": REVISION, "dirty": False}, "results": results}
    assert checks.result_gaps([report], revision, [receipt])


def test_declaration_only_cannot_qualify_results():
    assert checks.result_gaps([], REVISION, [])
