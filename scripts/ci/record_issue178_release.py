#!/usr/bin/env python3
"""Execute and record Issue 178 shared-decision/backend release acceptance."""

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
    "release-shared-decisions",
    "release-interface-parity",
    "release-obligation-178",
    "release-backend-contract",
    "release-backend-oracles",
)
# Each named check has a bounded leaf test. Each runs in its own process so
# native-extension loading is isolated.
LEAF_TESTS = {
    "release-shared-decisions": "tests/validation/test_option_decision_owner.py::test_poplevel_decision_has_one_compile_owner",
    "release-interface-parity": "tests/python/test_finite_backend.py::test_nf_never_routes_through_bngsim",
    "release-obligation-178": "tests/validation/test_nf_default_docs_consistency.py::test_active_docs_do_not_claim_nfcore_is_the_default",
    "release-backend-contract": "tests/python/test_finite_backend.py::test_explicit_bngsim_fails_closed_when_unavailable_or_unsupported",
    "release-backend-oracles": "tests/validation/test_shared_decision_ownership.py::test_general_energy_gate_has_one_owner",
}


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads((root / "provenance/issue-obligations.json").read_text())
    issue = next((i for i in manifest["issues"] if i["number"] == 178), None)
    if issue is None:
        _fail("Issue 178 is missing from the obligations manifest")
    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            if check["id"] not in EXPECTED_CHECKS:
                continue
            if check["id"] in checks:
                _fail(f"duplicate manifest definition for {check['id']}")
            if (
                check.get("selector") != LEAF_TESTS[check["id"]]
                or check.get("selector_status") != "COLLECTED"
            ):
                _fail(f"{check['id']} selector is not the expected collected leaf")
            if check.get(
                "receipt_producer_status"
            ) != "CONSUMER_READY" or not check.get("receipt_producer"):
                _fail(f"{check['id']} has no consumer-ready receipt producer")
            checks[check["id"]] = check
    if set(checks) != set(EXPECTED_CHECKS):
        _fail(f"manifest missing checks: {sorted(set(EXPECTED_CHECKS)-set(checks))}")
    return checks


def run_tests(root: Path = ROOT) -> None:
    for check_id, selector in LEAF_TESTS.items():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--noconftest", "-q", selector],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _fail(
                f"Issue 178 leaf {check_id} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
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
        _fail(f"stale Issue 178 evidence: HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 178 evidence checkout is dirty: {dirty}")
    manifest = verify_manifest(root)
    if not skip_tests:
        run_tests(root)
    details = {
        "release-shared-decisions": "The compile-owned poplevel decision has a single-owner check. Other option and rate decisions require their own evidence.",
        "release-interface-parity": "The leaf checks BNGsim bypass for network-free methods. Independent cross-backend and format parity remains unmeasured.",
        "release-obligation-178": "The leaf compares the documented NF default. The full obligation requires evidence for the remaining work clauses.",
        "release-backend-contract": "The leaf checks explicit BNGsim refusal. The shared result schema and option behavior across all backends remain unmeasured.",
        "release-backend-oracles": "The leaf checks ownership of the energy gate. Backend execution against independent oracles remains unmeasured.",
    }
    results = [
        {
            "id": k,
            "status": ("NOT_TESTED" if skip_tests else "PASS"),
            "evidence_kind": ("not-tested" if skip_tests else "supported-execution"),
            "supported_execution": not skip_tests,
            "related_issues": [178],
            "stage": k,
            "detail": ("Leaf verification was skipped." if skip_tests else details[k]),
            "source_revision": revision,
            "selector": manifest[k]["selector"],
        }
        for k in EXPECTED_CHECKS
    ]
    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-178",
        "case": "issue-178-shared-decisions-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "leaf_tests": list(LEAF_TESTS.values()),
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
            h.write("\n## Issue 178 shared decisions release evidence\n\n")
            for r in rec["results"]:
                h.write(f"- {r['id']}: {r['status']}\n")
    print(f"wrote {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
