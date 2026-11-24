#!/usr/bin/env python3
"""Build the issue-163 format/action -> intended-consumer matrix.

Reads the 94 live inventory rows from the release case contract and the
committed capability matrix oracle for each row. It does not execute anything
and does not promote a row to supported: it is the reviewer-facing list that
any full Tier-X claim must account for.

For rows with an actually executed consumer, ``semantic_facts_preserved``
records the facts the named consumer assertions prove. Every fact carries a
verbatim assertion fragment and the test file that contains it, so the metadata
is derived from executed checks rather than invented. Rows without a consumer
route get an empty fact list and an explicit basis; they remain unmeasured.
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
    "action.writeMEXfile": "g++ compile + execute generated MEX C with mxArray ABI shim",
    "action.writeMexfile": "g++ compile + execute generated MEX C with mxArray ABI shim",
}


# Each entry is (fact, verbatim assertion fragment, test file). The fragment
# must occur in the referenced file; tests/validation/release/cases/issue-163/
# test_consumer_matrix.py enforces that derivation. No expectation, tolerance
# or verdict is authored here: the facts restate what the consumer asserts.
_CONSUMER_ASSERTIONS = {
    "action.writeBNGL": [
        (
            "Exported BNGL re-imports through the public parser; the source "
            "entities (parameters, molecule types, seed species, observables "
            "and reaction rules) are preserved.",
            "_model_entities(restored), _model_entities(model)",
            "tests/validation/export_format_tier.py",
        ),
        (
            "The re-imported BNGL engine reproduces the source observable "
            "A_obs endpoint 10*exp(-0.1) at t=1 for k=0.1, A(0)=10 (rel=1e-5).",
            "10 * math.exp(-0.1), rel=1e-5",
            "tests/validation/release/cases/issue-163/test_write_actions_consumers.py",
        ),
        (
            "The re-imported model reproduces the case's closed-form law on "
            "the tier time grid, not merely a writer echo.",
            "_compare_values(values, law, rtol=LAW_RTOL, atol=LAW_ATOL)",
            "tests/validation/export_format_tier.py",
        ),
    ],
    "action.writeNET": [
        (
            "The native CLI consumes the exported .net, regenerates the "
            "source network and reports the same species and reaction count.",
            "network.n_reactions != source_network.num_reactions",
            "tests/validation/export_format_tier.py",
        ),
        (
            "The .net consumer reproduces observable A_obs at t=2 with "
            "10*exp(-0.2) for k=0.1, A(0)=10 (rel=1e-4).",
            "10 * math.exp(-0.2), rel=1e-4",
            "tests/validation/release/cases/issue-163/test_write_actions_consumers.py",
        ),
    ],
    "action.writeNetwork": [
        (
            "The action-produced network artifact is consumed by the native "
            "CLI with the same species and reaction count as the source network.",
            "network.n_reactions != source_network.num_reactions",
            "tests/validation/export_format_tier.py",
        ),
        (
            "The regenerated network consumer reproduces observable A_obs at "
            "t=2 with 10*exp(-0.2) for k=0.1, A(0)=10 (rel=1e-4).",
            "10 * math.exp(-0.2), rel=1e-4",
            "tests/validation/release/cases/issue-163/test_write_actions_consumers.py",
        ),
    ],
    "action.writeSBML": [
        (
            "libSBML-valid exported SBML preserves species names and initial "
            "amounts and the source reaction count.",
            'structure["species"] != expected_species',
            "tests/validation/export_format_tier.py",
        ),
        (
            "The independent libRoadRunner consumer reproduces the case's "
            "closed-form law from the exported SBML.",
            "_compare_values(values, law, rtol=LAW_RTOL, atol=LAW_ATOL)",
            "tests/validation/export_format_tier.py",
        ),
    ],
    "action.writeCPYfile": [
        (
            "The exported Python/ODE consumer writes a gdat with exactly the "
            "time and A_total observable columns.",
            'columns == ["time", "A_total"]',
            "tests/validation/release/cases/issue-163/test_export_format_release.py",
        ),
        (
            "The consumer trajectory matches 12*exp(-0.4*(t-0.25)) on "
            "linspace(0.25, 1.75, 6) with rtol=1e-7.",
            "np.testing.assert_allclose(observables[:, 1], expected_amounts, rtol=1e-7)",
            "tests/validation/release/cases/issue-163/test_export_format_release.py",
        ),
    ],
    "action.writeMEXfile": [
        (
            "The generated MEX C source compiles against the mxArray ABI shim "
            "and executes; its third time-point observable matches "
            "10*exp(-0.1) with rel=1e-6.",
            "10 * math.exp(-0.1), rel=1e-6",
            "tests/validation/release/cases/issue-163/test_mex_consumer.py",
        ),
    ],
    "action.writeMexfile": [
        (
            "The generated MEX C source compiles against the mxArray ABI shim "
            "and executes; its third time-point observable matches "
            "10*exp(-0.1) with rel=1e-6.",
            "10 * math.exp(-0.1), rel=1e-6",
            "tests/validation/release/cases/issue-163/test_mex_consumer.py",
        ),
    ],
    "action.writeFile": [
        (
            "The exported BNGL contains a model document and re-imports "
            "through the public parser.",
            '"begin model" in exported.read_text()',
            "tests/validation/release/cases/issue-163/test_write_file_model_consumers.py",
        ),
        (
            "The re-imported model reproduces observable A_obs endpoint "
            "10*exp(-0.1) at t=1 for k=0.1, A(0)=10 (rel=1e-5).",
            "10 * math.exp(-0.1), rel=1e-5",
            "tests/validation/release/cases/issue-163/test_write_file_model_consumers.py",
        ),
    ],
    "action.writeModel": [
        (
            "The exported BNGL contains a model document and re-imports "
            "through the public parser.",
            '"begin model" in exported.read_text()',
            "tests/validation/release/cases/issue-163/test_write_file_model_consumers.py",
        ),
        (
            "The re-imported model reproduces observable A_obs endpoint "
            "10*exp(-0.1) at t=1 for k=0.1, A(0)=10 (rel=1e-5).",
            "10 * math.exp(-0.1), rel=1e-5",
            "tests/validation/release/cases/issue-163/test_write_file_model_consumers.py",
        ),
    ],
    "action.writeXML": [
        (
            "The exported BNG-XML marks the $-prefixed seed A() as Fixed=1.",
            's.get("Fixed") == "1"',
            "tests/validation/test_xml_export_fixed_seed_nfsim_consumer.py",
        ),
        (
            "Pinned native NFsim keeps the fixed pool Atot at exactly 5 at "
            "every sample while the product grows.",
            'all(value == FIXED_COUNT for value in baseline["Atot"])',
            "tests/validation/test_xml_export_fixed_seed_nfsim_consumer.py",
        ),
        (
            "Control: rewriting the exported observable pattern changes the "
            "consumer's observable, so the fact follows the exported bytes.",
            'control["Btot"][-1] != baseline["Btot"][-1]',
            "tests/validation/test_xml_export_fixed_seed_nfsim_consumer.py",
        ),
    ],
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
        facts = [
            {"fact": fact, "assertion": assertion, "source": source}
            for fact, assertion, source in _CONSUMER_ASSERTIONS.get(identity, [])
        ]
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
                "semantic_facts_preserved": facts,
                "semantic_facts_basis": (
                    "derived from consumer assertions in the named test files"
                    if facts
                    else "no consumer assertion: row remains unmeasured"
                ),
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
            "rows_with_semantic_facts": sum(
                bool(entry["semantic_facts_preserved"]) for entry in entries
            ),
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
