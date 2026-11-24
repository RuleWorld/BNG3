"""Prove the issue-163 consumer matrix's semantic facts are evidence-derived.

Every row now carries ``semantic_facts_preserved``. For the ten consumer-executed
rows each fact names a verbatim assertion fragment and the test file containing
it; the other 84 rows carry an empty list with an explicit no-consumer basis.
Nothing here changes the matrix or any scientific expectation: the tests
validate the committed metadata against its named sources and the builder.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ci import build_issue163_consumer_matrix as builder

ROOT = Path(__file__).resolve().parents[5]
MATRIX = ROOT / "tests/validation/release/cases/issue-163/consumer_matrix.json"


def _load():
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def _validate(matrix):
    rows = matrix["rows"]
    assert len(rows) == 94
    assert matrix["summary"]["total_rows"] == len(rows)
    assert matrix["summary"]["consumer_executed_rows"] == 10
    assert matrix["summary"]["rows_with_semantic_facts"] == 10
    for row in rows:
        assert "semantic_facts_preserved" in row, f"{row['row']}: missing fact metadata"
        facts = row["semantic_facts_preserved"]
        assert isinstance(facts, list)
        if row["execution_class"] == "consumer-executed":
            assert facts, f"{row['row']}: consumer row without preserved facts"
            assert "derived from consumer assertions" in row["semantic_facts_basis"]
            for fact in facts:
                assert set(fact) == {"fact", "assertion", "source"}
                assert fact["fact"].strip()
                source = ROOT / fact["source"]
                assert source.is_file(), f"{row['row']}: missing {source}"
                assert fact["assertion"] in source.read_text(encoding="utf-8"), (
                    f"{row['row']}: assertion {fact['assertion']!r} is not in "
                    f"{fact['source']}"
                )
        else:
            assert facts == [], f"{row['row']}: invented facts for unmeasured row"
            assert "no consumer assertion" in row["semantic_facts_basis"]
    return rows


def test_committed_matrix_has_derived_per_row_facts():
    rows = _validate(_load())
    assert {row["row"] for row in rows if row["semantic_facts_preserved"]} == set(
        builder.EXECUTED_ROUTES
    )


def test_builder_output_matches_committed_matrix():
    assert builder.build() == _load()


@pytest.mark.parametrize(
    "mutation", ["changed-assertion", "missing-fact", "invented-unmeasured-fact"]
)
def test_fact_validation_fails_closed(mutation):
    matrix = copy.deepcopy(_load())
    row = next(r for r in matrix["rows"] if r["row"] == "action.writeXML")
    if mutation == "changed-assertion":
        row["semantic_facts_preserved"][0]["assertion"] = "Fixed=0"
    elif mutation == "missing-fact":
        row["semantic_facts_preserved"] = []
    else:
        other = next(
            r for r in matrix["rows"] if r["execution_class"] != "consumer-executed"
        )
        other["semantic_facts_preserved"] = [
            {"fact": "invented", "assertion": "invented", "source": "nonexistent.py"}
        ]
    with pytest.raises(AssertionError):
        _validate(matrix)
