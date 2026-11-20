"""Named-contract checks for issue 181.

These checks verify that the declared release identities match the live
obligation catalog and that the executed resume regression uses real locked
tier-S cases. They do not claim coverage or full-corpus results.
"""

from __future__ import annotations

import json
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO = CASE_DIR.parents[4]


def _contract() -> dict:
    return json.loads((CASE_DIR / "contract.json").read_text(encoding="utf-8"))


def test_contract_declares_the_live_named_checks():
    contract = _contract()
    assert contract["schema_version"] == 1
    assert contract["issue"] == 181
    assert contract["acceptance_checks"] == [
        "release-corpus-coverage",
        "release-corpus-results",
        "release-obligation-181",
    ]


def test_contract_obligations_match_the_catalog():
    catalog = json.loads((REPO / "provenance/issue-obligations.json").read_text())
    issue = next(row for row in catalog["issues"] if row["number"] == 181)
    assert _contract()["obligations"] == [row["id"] for row in issue["obligations"]]


def test_executed_resume_regression_uses_locked_tier_s_cases():
    from tests.validation import test_corpus_resume

    selection = json.loads(
        (REPO / "provenance/corpus/selection.json").read_text(encoding="utf-8")
    )
    records = {row["id"]: row for row in selection["records"]}
    assert set(test_corpus_resume.CASE_IDS) <= set(selection["tiers"]["s"])
    for case in test_corpus_resume.CASE_IDS:
        assert test_corpus_resume._records()[case]["sha256"] == records[case]["sha256"]


def test_readme_does_not_claim_unexecuted_acceptance():
    text = (CASE_DIR / "README.md").read_text(encoding="utf-8")
    assert "does not claim `release-corpus-coverage`" in text
    assert "--corpus-tier s --resume" in text
    assert "stale-discarded-and-executed" in text
