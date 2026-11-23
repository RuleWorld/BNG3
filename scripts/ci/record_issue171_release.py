#!/usr/bin/env python3
"""Execute and record the Issue 171 PyBioNetGen public compatibility release acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.validation.junit import executed_test_names

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NODE = "tests/validation/release/cases/issue-171/test_pybionetgen_api_release.py"
PRODUCER = ".github/workflows/parity.yml#pybionetgen-compat"

CHECKS = (
    "release-python-api",
    "release-python-install",
    "release-capability-coverage-171",
)

DISPOSITION_CHECKS = (
    "api-surface:surface:signatures-defaults",
    "api-surface:surface:positional-dispatch",
    "api-surface:surface:timeouts",
    "api-surface:surface:actions",
    "api-surface:surface:results-files",
    "api-surface:surface:exceptions",
    "api-surface:surface:optional-imports",
    "api-surface:surface:intentional-incompatibilities",
    "api-surface:methods:ode:api-vs-law",
    "api-surface:methods:ode:cli-vs-law",
    "api-surface:methods:ode:route-agreement",
    "api-surface:methods:ssa:api-vs-law",
    "api-surface:methods:ssa:cli-vs-law",
    "api-surface:methods:ssa:route-agreement",
    "api-surface:methods:nf:api-vs-law",
    "api-surface:methods:nf:cli-vs-law",
    "api-surface:methods:nf:route-agreement",
    "api-surface:methods:pla:api-vs-law",
    "api-surface:methods:pla:cli-vs-law",
    "api-surface:methods:pla:route-agreement",
    "api-surface:methods:psa:api-vs-law",
    "api-surface:methods:psa:cli-vs-law",
    "api-surface:methods:psa:route-agreement",
    "manual:issue:171:closure-record",
)


def _row(identity, kind, detail, *, supported=True, status="PASS", selector=None):
    r = {
        "id": identity,
        "status": status,
        "check": identity,
        "related_issues": [171],
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
    parser.add_argument(
        "--py-row-map",
        type=Path,
        help="JSON artifact mapping every py.* row to pinned-oracle evidence",
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
        raise SystemExit("Issue 171 receipt requires a clean checkout")

    expected_tests = {
        "test_release_python_api",
        "test_release_python_install",
        "test_release_capability_coverage_171",
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
                f"Issue 171 tests did not all pass:\n{proc.stdout}\n{proc.stderr}"
            )
    # Execution identities come only from the JUnit report.  A pytest exit
    # code, an expected-name list or a skipped case cannot establish that a
    # named acceptance test actually ran.
    executed = executed_test_names(junit)
    missing = expected_tests - executed
    if missing:
        raise SystemExit(
            "Issue 171 named acceptance tests did not execute: "
            + ", ".join(sorted(missing))
        )

    py_row_map = None
    if args.py_row_map:
        if not args.py_row_map.is_file():
            raise SystemExit("Issue 171 py.* row map artifact is missing")
        py_row_map = json.loads(args.py_row_map.read_text())
        if py_row_map.get("package", {}).get("source_revision") != head:
            raise SystemExit("Issue 171 py.* row map has a stale package revision")
        if py_row_map.get("oracle", {}).get("source_revision") != py_row_map.get(
            "oracle", {}
        ).get("pinned_revision"):
            raise SystemExit("Issue 171 py.* row map oracle does not match its pin")
        failed = [
            row["id"]
            for row in py_row_map.get("results", [])
            if row.get("status") != "PASS"
        ]
        if failed:
            raise SystemExit(
                "Issue 171 py.* row map has unresolved rows: "
                + ", ".join(sorted(failed))
            )

    disposition_evidence: dict[str, dict] = {}
    if args.disposition_evidence:
        if not args.disposition_evidence.is_file():
            raise SystemExit("Issue 171 disposition evidence artifact is missing")
        evidence = json.loads(args.disposition_evidence.read_text())
        if evidence.get("source", {}).get("revision") != head:
            raise SystemExit("Issue 171 disposition evidence has a stale revision")
        rows = evidence.get("results")
        if not isinstance(rows, list):
            raise SystemExit("Issue 171 disposition evidence has no results array")
        for row in rows:
            if isinstance(row, dict) and row.get("id") in DISPOSITION_CHECKS:
                disposition_evidence[row["id"]] = row

    results = []
    # Live acceptance checks
    test_map = {
        "release-python-api": (
            f"{NODE}::test_release_python_api",
            "All public py.* API families and entry points demonstrated differential compatibility.",
        ),
        "release-python-install": (
            f"{NODE}::test_release_python_install",
            "Installed wheel/package and CLI entry points execute with optional extras isolated.",
        ),
        "release-capability-coverage-171": (
            f"{NODE}::test_release_capability_coverage_171",
            "All 5 simulation methods (ODE, SSA, NF, PLA, PSA) pass against analytic mass-action law and CLI matches API.",
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

    # Disposition checks are records of a decision, not scientific execution.
    # They may only be marked PASS when an exact-revision artifact actually
    # records that disposition; otherwise they remain NOT_TESTED.
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
        "acceptance_check": "release-python-api",
        "case": "issue-171/pybionetgen-compat",
        "source": {"revision": head, "dirty": False},
        "results": results,
        "manifest_check_ids": sorted([r["id"] for r in results]),
        "selector": f"{NODE}::test_release_python_api",
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
        "py_row_map": (
            {
                "path": str(args.py_row_map),
                "sha256": hashlib.sha256(args.py_row_map.read_bytes()).hexdigest(),
                "row_count": py_row_map["row_count"],
                "package": py_row_map["package"],
                "oracle": py_row_map["oracle"],
            }
            if py_row_map is not None
            else None
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output} with {len(results)} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
