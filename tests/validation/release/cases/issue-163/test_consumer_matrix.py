"""Guard the issue-163 format/action -> consumer matrix.

The matrix is a completeness list, not a pass claim. Every live inventory row
must appear with an intended consumer; consumer-executed rows must name the
route that actually ran. Missing routes remain visible as gaps.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_consumer_matrix_lists_every_live_row():
    contract = json.loads((HERE / "contract.json").read_text())
    matrix = json.loads((HERE / "consumer_matrix.json").read_text())
    rows = {entry["row"]: entry for entry in matrix["rows"]}
    assert set(rows) == set(contract["inventory_rows"])
    assert matrix["summary"]["total_rows"] == len(contract["inventory_rows"])
    for entry in matrix["rows"]:
        assert entry["intended_consumer"]
        assert entry["execution_class"] in (
            "consumer-executed",
            "unmeasured-or-structure-only",
        )
        if entry["execution_class"] == "consumer-executed":
            assert entry["executed_route"]


def test_missing_routes_remain_visible():
    matrix = json.loads((HERE / "consumer_matrix.json").read_text())
    executed = {
        r["row"] for r in matrix["rows"] if r["execution_class"] == "consumer-executed"
    }
    missing = {
        r["row"] for r in matrix["rows"] if r["execution_class"] != "consumer-executed"
    }
    assert not (executed & missing)
    assert matrix["summary"]["consumer_executed_rows"] == len(executed)
    assert matrix["summary"]["missing_consumer_rows"] == len(missing)
