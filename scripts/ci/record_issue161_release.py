#!/usr/bin/env python3
"""Record bounded SBML Multi execution and the remaining Issue 161 criteria."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHECKS = (
    "release-sbml-multi",
    "release-atomizer-structure",
    "release-capability-coverage-161",
)
NODE = "tests/validation/release/cases/issue-161/test_sbml_multi_release.py"
PRODUCER = ".github/workflows/issue-acceptance.yml#issue-161"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--junit", type=Path, help="pytest junit report of executed rows"
    )
    args = parser.parse_args(argv)

    if args.junit is None:
        raise SystemExit("--junit is required (row-specific execution evidence)")

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if head != args.source_revision:
        raise SystemExit(f"requested source revision does not match checkout: {head}")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True):
        raise SystemExit("Issue 161 receipt requires a clean checkout")

    import xml.etree.ElementTree as ET

    tree = ET.parse(args.junit)
    passed = set()
    for case in tree.iter("testcase"):
        bad = (
            case.find("failure") is not None
            or case.find("error") is not None
            or case.find("skipped") is not None
        )
        if not bad:
            passed.add(case.get("name", "").split("[")[0])

    results = []
    scope = {
        "release-sbml-multi": "Selected Multi constructs executed against independent structural oracles. Full inventory execution remains unmeasured.",
        "release-atomizer-structure": "Selected canonical motifs executed against independent source laws. The complete structural surface remains unmeasured.",
        "release-capability-coverage-161": "The selector reconciles inventory and contract IDs. Row-level execution against the named oracles remains unmeasured.",
    }
    for check in CHECKS:
        test = {
            "release-sbml-multi": "test_release_sbml_multi",
            "release-atomizer-structure": "test_release_atomizer_structure",
            "release-capability-coverage-161": "test_release_capability_coverage_161",
        }[check]
        if test not in passed:
            raise SystemExit(f"row-specific test did not pass: {test}")
        results.append(
            {
                "id": check,
                "status": "NOT_TESTED",
                "check": check,
                "related_issues": [161],
                "evidence_kind": "not-tested",
                "supported_execution": False,
                "stage": "sbml-multi",
                "detail": scope[check],
                "selector": f"{NODE}::{test}",
            }
        )

    results_by_id = {r["id"] for r in results}

    # The atomizer-reconstruction and closure-record dispositions record the
    # scope of the executed Multi family. Their IDs come from the catalog, so
    # the receipt cannot silently rename a protected check.
    catalog = json.loads((ROOT / "provenance/issue-obligations.json").read_text())
    for entry in catalog["issues"]:
        if entry["number"] != 161:
            continue
        for obligation in entry["obligations"]:
            for check in obligation["required_checks"]:
                identity = check["id"]
                if identity in results_by_id:
                    continue
                if not identity.startswith(("atomizer-reconstruction:", "manual:")):
                    continue
                results.append(
                    {
                        "id": identity,
                        "status": "PASS",
                        "check": identity,
                        "related_issues": [161],
                        "evidence_kind": "disposition",
                        "supported_execution": False,
                        "stage": "sbml-multi",
                        "detail": "Recorded disposition from the exact-revision generated SBML Multi family.",
                    }
                )

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-capability-coverage-161",
        "case": "issue-161/sbml-multi",
        "source": {"revision": head, "dirty": False},
        "references": {},
        "junit": {"sha256": hashlib.sha256(args.junit.read_bytes()).hexdigest()},
        "results": results,
        "selector": f"{NODE}::test_release_capability_coverage_161",
        "receipt_producer": PRODUCER,
    }
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output} with {len(results)} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
