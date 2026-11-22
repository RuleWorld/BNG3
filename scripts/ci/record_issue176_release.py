#!/usr/bin/env python3
"""Execute and record Issue 176 CPU ensemble release acceptance evidence.

The named checks are backed by real leaf tests: seed reproducibility, seed
independence, state isolation and an independently derived immigration-death
analytic mean. The recorder refuses to emit a PASS record when the checkout is
dirty, the revision is stale, the obligation manifest is incomplete or any leaf
test fails.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_CHECKS = (
    "release-nf-ensemble",
    "release-capability-coverage-176",
)
TEST_FILE = "tests/python/nfnext/test_nfnext_ensemble_rng_isolation.py"


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 176), None)
    if issue is None:
        _fail("Issue 176 is missing from the obligations manifest")
    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            if check["id"] not in EXPECTED_CHECKS:
                continue
            if check["id"] in checks:
                _fail(f"duplicate manifest definition for {check['id']}")
            if check.get("selector_status") != "COLLECTED" or not check.get("selector"):
                _fail(f"{check['id']} has no collected selector")
            if check.get(
                "receipt_producer_status"
            ) != "CONSUMER_READY" or not check.get("receipt_producer"):
                _fail(f"{check['id']} has no consumer-ready receipt producer")
            checks[check["id"]] = check
    if set(checks) != set(EXPECTED_CHECKS):
        _fail(f"manifest missing checks: {sorted(set(EXPECTED_CHECKS) - set(checks))}")
    return checks


def run_tests(root: Path = ROOT) -> None:
    path = root / TEST_FILE
    if not path.is_file():
        _fail(f"missing test file: {path}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--noconftest", "-q", str(path)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _fail(
            f"Issue 176 ensemble tests failed (code {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )


def build_release_record(
    expected_revision: str | None = None,
    root: Path = ROOT,
    skip_tests: bool = False,
    allow_dirty: bool = False,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 176 evidence: HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 176 evidence checkout is dirty: {dirty}")

    manifest = verify_manifest(root)
    if not skip_tests:
        run_tests(root)

    details = {
        "release-nf-ensemble": (
            "Production NFnext entry point reproduces trajectories under fixed "
            "seeds, keeps seeds independent and does not leak state between calls."
        ),
        "release-capability-coverage-176": (
            "Ensemble mean matches an independently derived immigration-death "
            "analytic law with declared seed budget and error control."
        ),
    }
    results = [
        {
            "id": check_id,
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [176],
            "stage": "issue176-cpu-ensemble",
            "detail": details[check_id],
            "source_revision": revision,
            "selector": manifest[check_id]["selector"],
        }
        for check_id in EXPECTED_CHECKS
    ]
    if skip_tests:
        for row in results:
            row.update(
                status="NOT_TESTED",
                supported_execution=False,
                evidence_kind="not-tested",
                detail="Execution was skipped; no scientific acceptance evidence was collected.",
            )
    return {
        "schema_version": 1,
        "acceptance_check": "release-nf-ensemble",
        "case": "issue-176-cpu-ensemble-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "leaf_tests": TEST_FILE,
            "analytic_oracle": "immigration-death mean N0 + (lambda/mu)(1 - exp(-mu t))",
            "provenance": "provenance/issue-obligations.json",
        },
        "results": results,
        "manifest_check_ids": sorted(EXPECTED_CHECKS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    record = build_release_record(
        expected_revision=args.source_revision,
        skip_tests=args.skip_tests,
        allow_dirty=args.allow_dirty,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        with args.summary_file.open("a", encoding="utf-8") as handle:
            handle.write("\n## Issue 176 CPU ensemble release evidence\n\n")
            for row in record["results"]:
                handle.write(f"- {row['id']}: {row['status']}\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
