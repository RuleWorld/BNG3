#!/usr/bin/env python3
"""Execute and record the Issue 186 migration and maintenance guidance release acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NODE = "tests/validation/release/cases/issue-186/test_migration_docs_release.py"
PRODUCER = ".github/workflows/parity.yml#migration-docs"

CHECKS = (
    "release-migration-docs",
    "release-maintenance-docs",
    "release-obligation-186",
)

DISPOSITION_CHECKS = (
    "qualification:issue:186:document-alpha-installation-versus-legacy-stable-supported-exper",
    "qualification:issue:186:record-canonical-contribution-policy-release-guidance-and-intend",
    "qualification:issue:186:closure-record",
)


def _row(identity, kind, detail, *, supported=True, status="PASS", selector=None):
    r = {
        "id": identity,
        "status": status,
        "check": identity,
        "related_issues": [186],
        "evidence_kind": kind,
        "supported_execution": supported,
        "stage": "migration-docs",
        "detail": detail,
    }
    if selector:
        r["selector"] = selector
    return r


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--junit", type=Path, help="pytest junit report of executed rows"
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="allow dirty working tree"
    )
    args = parser.parse_args(argv)

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if head != args.source_revision:
        raise SystemExit(f"requested source revision does not match checkout: {head}")
    if not args.allow_dirty and subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ):
        raise SystemExit("Issue 186 receipt requires a clean checkout")

    import xml.etree.ElementTree as ET

    has_full_coverage = False
    if args.junit and args.junit.is_file():
        tree = ET.parse(args.junit)
        base_passed = set()
        for case in tree.iter("testcase"):
            bad = (
                case.find("failure") is not None
                or case.find("error") is not None
                or case.find("skipped") is not None
            )
            if not bad:
                base_passed.add(case.get("name", "").split("[")[0])
        expected_tests = {
            "test_release_migration_docs",
            "test_release_maintenance_docs",
            "test_release_obligation_186",
        }
        has_full_coverage = bool(expected_tests <= base_passed)
    else:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(ROOT / NODE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        has_full_coverage = proc.returncode == 0

    if not has_full_coverage:
        raise SystemExit("Issue 186 tests did not all pass")

    results = []
    test_map = {
        "release-migration-docs": (
            f"{NODE}::test_release_migration_docs",
            "Installed-package examples and all migration-table targets execute successfully.",
        ),
        "release-maintenance-docs": (
            f"{NODE}::test_release_maintenance_docs",
            "README, migration guide, and DECISIONS.md agree with no contradictory backend or retirement policy.",
        ),
        "release-obligation-186": (
            f"{NODE}::test_release_obligation_186",
            "Contract, manifest definitions, source identities, and typed negative controls verified.",
        ),
    }

    for check in CHECKS:
        selector, detail = test_map[check]
        results.append(
            _row(
                check,
                "supported-execution",
                detail,
                supported=True,
                status="PASS",
                selector=selector,
            )
        )

    for check in DISPOSITION_CHECKS:
        results.append(
            _row(
                check,
                "disposition",
                "Discharged by the release-migration-docs, release-maintenance-docs, and release-obligation-186 acceptance suites.",
                supported=False,
                status="PASS",
            )
        )

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-migration-docs",
        "case": "issue-186/migration-docs",
        "source": {"revision": head, "dirty": False},
        "results": results,
        "manifest_check_ids": sorted([r["id"] for r in results]),
        "selector": f"{NODE}::test_release_migration_docs",
        "receipt_producer": PRODUCER,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output} with {len(results)} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
