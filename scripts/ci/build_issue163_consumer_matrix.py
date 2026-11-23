#!/usr/bin/env python3
"""Build the issue-163 format/action -> intended-consumer matrix.

Reads the 94 live inventory rows from the release case contract and the
committed capability matrix oracle for each row. It does not execute anything
and does not promote a row to supported: it is the reviewer-facing list that
any full Tier-X claim must account for.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "tests/validation/release/cases/issue-163/contract.json"
CAPABILITY_MATRIX = ROOT / "provenance/capability-matrix.yml"

# Routes with an actually executed consumer in tests/validation/export_format_tier.py
# and tests/validation/release/cases/issue-163/test_export_format_release.py.
EXECUTED_ROUTES = {
    "action.writeBNGL": "BioNetGen parser + engine (re-import, closed-form ODE)",
    "action.writeNET": "native bng_cpp CLI (readFile + simulate_ode)",
    "action.writeNetwork": "native bng_cpp CLI (network regeneration)",
    "action.writeSBML": "libSBML validation + libRoadRunner simulation",
    "action.writeXML": "native NFsim fixed-seed fact (one detector case)",
    "action.writeCPYfile": "Python/SciPy runtime (exported .py + .gdat)",
    "action.writeFile": "BNG parser + engine (re-import exported .bngl, closed-form ODE)",
    "action.writeModel": "BNG parser + engine (re-import exported .bngl, closed-form ODE)",
}


def build() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    rows = yaml.safe_load(CAPABILITY_MATRIX.read_text(encoding="utf-8"))["rows"]
    by_id = {row["id"]: row for row in rows}
    entries = []
    for identity in contract["inventory_rows"]:
        matrix = by_id.get(identity, {})
        oracle = matrix.get("oracle") or ""
        consumer = oracle.split(";")[0].strip() or "unspecified"
        executed = identity in EXECUTED_ROUTES
        entries.append(
            {
                "row": identity,
                "intended_consumer": consumer,
                "oracle": oracle,
                "matrix_status": matrix.get("status", "unassessed"),
                "execution_class": (
                    "consumer-executed" if executed else "unmeasured-or-structure-only"
                ),
                "executed_route": EXECUTED_ROUTES.get(identity),
            }
        )
    executed_count = sum(e["execution_class"] == "consumer-executed" for e in entries)
    return {
        "schema_version": 1,
        "issue": 163,
        "source": {
            "contract": str(CONTRACT.relative_to(ROOT)),
            "capability_matrix": str(CAPABILITY_MATRIX.relative_to(ROOT)),
        },
        "rows": entries,
        "summary": {
            "total_rows": len(entries),
            "consumer_executed_rows": executed_count,
            "missing_consumer_rows": len(entries) - executed_count,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {args.output}: {build()['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
