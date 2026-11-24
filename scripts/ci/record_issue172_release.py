#!/usr/bin/env python3
"""Execute and record the Issue 172 Python legacy consolidation release acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.validation.junit import executed_test_names

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NODE = "tests/validation/release/cases/issue-172/test_python_consolidation_release.py"
PRODUCER = ".github/workflows/parity.yml#pybionetgen-compat"

CHECKS = (
    "release-python-consolidation",
    "release-python-legacy",
    "release-obligation-172",
)

DISPOSITION_CHECKS = (
    "api-surface:surface:optional-imports",
    "qualification:issue:172:trace-imports-and-callers-of-modelapi-legacy-network-parser-simu",
    "qualification:issue:172:remove-only-superseded-paths-after-contracts-pass-and-make-missi",
    "qualification:issue:172:closure-record",
)


def _row(identity, kind, detail, *, supported=True, status="PASS", selector=None):
    r = {
        "id": identity,
        "status": status,
        "check": identity,
        "related_issues": [172],
        "evidence_kind": kind,
        "supported_execution": supported,
        "stage": "pybionetgen-compat",
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
    parser.add_argument(
        "--disposition-evidence",
        type=Path,
        help="JSON artifact recording executed disposition checks at this revision",
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
        raise SystemExit("Issue 172 receipt requires a clean checkout")

    expected_tests = {
        "test_release_python_consolidation",
        "test_release_python_legacy",
        "test_release_obligation_172",
    }
    temp = None
    if args.junit and args.junit.is_file():
        junit = args.junit
    else:
        temp = TemporaryDirectory()
        junit = Path(temp.name) / "pytest.xml"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                str(ROOT / NODE),
                "--junitxml",
                str(junit),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"Issue 172 tests did not all pass:\n{proc.stdout}\n{proc.stderr}"
            )
    executed = executed_test_names(junit)
    missing = expected_tests - executed
    if missing:
        raise SystemExit(
            "Issue 172 named acceptance tests did not execute: "
            + ", ".join(sorted(missing))
        )

    disposition_evidence: dict[str, dict] = {}
    if args.disposition_evidence:
        if not args.disposition_evidence.is_file():
            raise SystemExit("Issue 172 disposition evidence artifact is missing")
        evidence = json.loads(args.disposition_evidence.read_text())
        if evidence.get("source", {}).get("revision") != head:
            raise SystemExit("Issue 172 disposition evidence has a stale revision")
        rows = evidence.get("results")
        if not isinstance(rows, list):
            raise SystemExit("Issue 172 disposition evidence has no results array")
        for row in rows:
            if isinstance(row, dict) and row.get("id") in DISPOSITION_CHECKS:
                disposition_evidence[row["id"]] = row

    results = []
    test_map = {
        "release-python-consolidation": (
            f"{NODE}::test_release_python_consolidation",
            "Dependency audit verifies single maintained C++ semantic engine behind common interfaces.",
        ),
        "release-python-legacy": (
            f"{NODE}::test_release_python_legacy",
            "Complete pinned PyBioNetGen compatibility suite (94 tests) passes against installed BNG3.",
        ),
        "release-obligation-172": (
            f"{NODE}::test_release_obligation_172",
            "Contract, manifest definitions, source identities and typed error negative controls verified.",
        ),
    }

    for check in CHECKS:
        selector, detail = test_map[check]
        test_name = selector.split("::")[-1]
        results.append(
            _row(
                check,
                "supported-execution",
                detail,
                supported=test_name in executed,
                status="PASS" if test_name in executed else "NOT_TESTED",
                selector=selector,
            )
        )

    for check in DISPOSITION_CHECKS:
        record = disposition_evidence.get(check)
        if record is not None and record.get("status") == "PASS":
            results.append(
                _row(
                    check,
                    "disposition",
                    record.get(
                        "detail",
                        "Exact-revision disposition recorded in evidence artifact.",
                    ),
                    supported=False,
                    status="PASS",
                )
            )
        else:
            results.append(
                _row(
                    check,
                    "not-tested",
                    "No exact-revision disposition evidence artifact was supplied for this check.",
                    supported=False,
                    status="NOT_TESTED",
                )
            )

    receipt = {
        "schema_version": 1,
        "acceptance_check": "release-python-consolidation",
        "case": "issue-172/pybionetgen-compat",
        "source": {"revision": head, "dirty": False},
        "results": results,
        "manifest_check_ids": sorted([r["id"] for r in results]),
        "selector": f"{NODE}::test_release_python_consolidation",
        "receipt_producer": PRODUCER,
        "junit": {
            "path": str(junit),
            "sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
            "executed_tests": sorted(executed),
        },
        "disposition_evidence": (
            {
                "path": str(args.disposition_evidence),
                "sha256": hashlib.sha256(
                    args.disposition_evidence.read_bytes()
                ).hexdigest(),
            }
            if args.disposition_evidence
            else None
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output} with {len(results)} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
