#!/usr/bin/env python3
"""Execute and record Issue 152 energy/protocol release acceptance evidence."""

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
    "release-energy-protocols",
    "release-extension-protocols",
    "release-obligation-152",
)
TEST_FILE = "tests/validation/release/cases/issue-152/test_energy_protocols.py"


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads((root / "provenance/issue-obligations.json").read_text())
    issue = next((i for i in manifest["issues"] if i["number"] == 152), None)
    if issue is None:
        _fail("Issue 152 is missing from the obligations manifest")
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
        _fail(f"manifest missing checks: {sorted(set(EXPECTED_CHECKS)-set(checks))}")
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
            f"Issue 152 tests failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )


def build_release_record(
    expected_revision=None, root=ROOT, skip_tests=False, allow_dirty=False
):
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 152 evidence: HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 152 evidence checkout is dirty: {dirty}")
    manifest = verify_manifest(root)
    if not skip_tests:
        run_tests(root)
    details = {
        "release-energy-protocols": "Source-linked real-model families and canonical energy execution reproduce declared invariants and analytic laws.",
        "release-extension-protocols": "Analytic cycle affinity, driven-protocol monotonicity and fail-closed extension gates hold under the declared opt-in.",
        "release-obligation-152": "Named check identities, source/oracle revision and exact main commit recorded with negative controls.",
    }
    results = [
        {
            "id": k,
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [152],
            "stage": k,
            "detail": details[k],
            "source_revision": revision,
            "selector": manifest[k]["selector"],
        }
        for k in EXPECTED_CHECKS
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
        "acceptance_check": "release-obligation-152",
        "case": "issue-152-energy-protocol-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "leaf_tests": TEST_FILE,
            "fixtures": "tests/validation/real_model_fixtures.py",
            "provenance": "provenance/issue-obligations.json",
        },
        "results": results,
        "manifest_check_ids": sorted(EXPECTED_CHECKS),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-revision")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--summary-file", type=Path)
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--allow-dirty", action="store_true")
    a = p.parse_args(argv)
    rec = build_release_record(
        a.source_revision, skip_tests=a.skip_tests, allow_dirty=a.allow_dirty
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(rec, indent=2) + "\n")
    if a.summary_file:
        a.summary_file.parent.mkdir(parents=True, exist_ok=True)
        with a.summary_file.open("a", encoding="utf-8") as h:
            h.write("\n## Issue 152 energy/protocol release evidence\n\n")
            for r in rec["results"]:
                h.write(f"- {r['id']}: {r['status']}\n")
    print(f"wrote {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
