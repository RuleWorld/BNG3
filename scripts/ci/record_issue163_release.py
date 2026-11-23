#!/usr/bin/env python3
"""Execute and record the Issue 163 format-tier release acceptance.

Combines the actually executed export-format tier, the native BNGIR
adversarial slices, and the scope/closure dispositions into one
issue-queue-compatible receipt. Every named check is backed by an executed
tier/BNGIR row or by the recorded scope boundary; a fixture list or a passing
process exit alone is not evidence. No scientific expectation, tolerance or
case id is authored here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))

SELECTOR = (
    "tests/validation/test_export_format_tier.py::test_tier_executes_every_named_check"
)
PRODUCER = ".github/workflows/parity.yml#export-format-tier"

BNGIR_CHECKS = (
    "bngir-adversarial:molecule-id-permutation",
    "bngir-adversarial:compartment-suffix",
    "bngir-adversarial:compartment-prefix",
    "bngir-adversarial:molecule-compartment",
)
DISPOSITION_CHECKS = (
    "qualification:issue:163:inventory-supported-bngl-xml-net-sbml-multi-and-code-graph-docum",
    "qualification:issue:163:closure-record",
)
LIVE_CHECKS = (
    "release-formats",
    "release-format-semantics",
    "release-capability-coverage-163",
)


def _row(identity, kind, detail, *, supported=True):
    return {
        "id": identity,
        "status": "PASS",
        "check": identity,
        "related_issues": [163],
        "evidence_kind": kind,
        "supported_execution": supported,
        "stage": "export-format-tier",
        "detail": detail,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, default=ROOT / "build/cpp/bng_cpp")
    parser.add_argument(
        "--bngir-report",
        type=Path,
        help="exact-revision integrated bngir-adversarial report.json",
    )
    args = parser.parse_args(argv)

    from tests.validation import export_format_tier as tier

    with tempfile.TemporaryDirectory() as work_dir:
        rows = tier.run_worker(work_dir, bng_cpp=str(args.bng_cpp))

    by_id = {row["id"]: row for row in rows}
    expected = set(tier.check_ids())
    if set(by_id) != expected:
        raise SystemExit(
            f"tier did not execute every named check: {sorted(expected - set(by_id))}"
        )

    results = []
    for identity in sorted(expected):
        row = by_id[identity]
        if row["status"] != "PASS":
            raise SystemExit(f"tier check did not pass: {identity}: {row['detail']}")
        results.append(
            {
                "id": identity,
                "status": "PASS",
                "check": identity,
                "related_issues": [163],
                "evidence_kind": row["evidence_kind"],
                "supported_execution": row["supported_execution"],
                "stage": "export-format-tier",
                "detail": row["detail"],
            }
        )

    # Native BNGIR adversarial controls: consume an exact-revision report.
    if args.bngir_report is None:
        raise SystemExit("--bngir-report is required for the reconstruction slices")
    bngir = json.loads(args.bngir_report.read_text())
    if bngir.get("source", {}).get("revision") != args.source_revision:
        raise SystemExit("bngir report revision does not match --source-revision")
    if bngir.get("source", {}).get("dirty") is not False:
        raise SystemExit("bngir report was produced from a dirty checkout")
    bngir_rows = {row["id"]: row for row in bngir.get("results", [])}
    for identity in BNGIR_CHECKS:
        row = bngir_rows.get(identity)
        if row is None or row.get("status") != "PASS":
            raise SystemExit(f"bngir control did not pass: {identity}")
        results.append(
            {
                "id": identity,
                "status": "PASS",
                "check": identity,
                "related_issues": [163],
                "evidence_kind": "native-bngir-semantic-control",
                "supported_execution": True,
                "stage": "bngir-adversarial",
                "detail": row.get("detail", "native reader control passed"),
            }
        )

    # Scope and closure dispositions are recorded from the obligation's own
    # documented boundary, not authored as new semantic claims.
    for identity in DISPOSITION_CHECKS:
        results.append(
            _row(
                identity,
                "disposition",
                "Inventory and closure recorded by the documented export-format "
                "tier scope: BNGL/NET/SBML round trips with independent consumers "
                "and the eBNGL energy refusal boundary; two first-order cases; "
                "no structural/graph exporter qualification.",
                supported=False,
            )
        )

    # Live checks are the same executed tier, summarised per named identity.
    for identity in LIVE_CHECKS:
        results.append(
            _row(
                identity,
                "supported-execution",
                "All named export-format-tier checks executed and passed against "
                "their independent consumers (native CLI, libRoadRunner).",
            )
        )

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-format-semantics",
        "case": "issue-163/export-format-tier",
        "source": {"revision": args.source_revision, "dirty": False},
        "subject": {
            "binary": str(args.bng_cpp),
            "sha256": hashlib.sha256(args.bng_cpp.read_bytes()).hexdigest(),
        },
        "references": {
            "bngir_report_sha256": hashlib.sha256(
                args.bngir_report.read_bytes()
            ).hexdigest()
        },
        "results": results,
        "manifest_check_ids": sorted(expected),
        "selector": SELECTOR,
        "receipt_producer": PRODUCER,
    }
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output} with {len(results)} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
