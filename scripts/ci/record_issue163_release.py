#!/usr/bin/env python3
"""Execute and record the Issue 163 export-format-tier acceptance.

Runs the generated export-format tier against the native BNG3 CLI and emits an
issue-queue-compatible receipt. Every named check must be backed by an
actually executed tier row; a fixture list or a passing process exit alone is
not evidence. No scientific expectation, tolerance or case id is authored here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))

SELECTOR = (
    "tests/validation/test_export_format_tier.py::test_tier_executes_every_named_check"
)
PRODUCER = ".github/workflows/parity.yml#export-format-tier"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, default=ROOT / "build/cpp/bng_cpp")
    args = parser.parse_args(argv)

    from tests.validation import export_format_tier as tier

    import tempfile

    with tempfile.TemporaryDirectory() as work_dir:
        rows = tier.run_worker(work_dir, bng_cpp=str(args.bng_cpp))

    by_id = {row["id"]: row for row in rows}
    expected = set(tier.check_ids())
    if set(by_id) != expected:
        missing = expected - set(by_id)
        raise SystemExit(f"tier did not execute every named check: {sorted(missing)}")

    results = []
    for identity in sorted(expected):
        row = by_id[identity]
        results.append(
            {
                "id": identity,
                "status": "PASS" if row["status"] == "PASS" else row["status"],
                "check": identity,
                "related_issues": [163],
                "evidence_kind": row["evidence_kind"],
                "supported_execution": row["supported_execution"],
                "stage": "export-format-tier",
                "detail": row["detail"],
            }
        )

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-format-semantics",
        "case": "issue-163/export-format-tier",
        "source": {"revision": args.source_revision, "dirty": False},
        "subject": {
            "binary": str(args.bng_cpp),
            "sha256": __import__("hashlib")
            .sha256(args.bng_cpp.read_bytes())
            .hexdigest(),
        },
        "references": {},
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
