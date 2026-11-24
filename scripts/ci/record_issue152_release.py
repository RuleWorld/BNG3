#!/usr/bin/env python3
"""Execute and record Issue 152 energy/protocol release acceptance evidence.

Verdicts are evidence-driven. ``release-obligation-152`` is a structural/
fail-closed check and is backed by its collected leaf test. The two scientific
checks require consuming reports, because the current leaf suite checks source
links, invariants, conservation and analytic arithmetic stated in the harness;
it does not compare each canonical fixture against a pinned native NFsim
trajectory, nor tie the cycle-affinity arithmetic to product-derived rates.
Those checks stay ``NOT_TESTED`` until such evidence is supplied.
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
    "release-energy-protocols",
    "release-extension-protocols",
    "release-obligation-152",
)
TEST_FILE = "tests/validation/release/cases/issue-152/test_energy_protocols.py"

# Only the structural / fail-closed check is genuinely covered by the leaf.
MEASURED_LEAF_CHECKS = frozenset({"release-obligation-152"})
REPORT_CHECKS = frozenset({"release-energy-protocols", "release-extension-protocols"})

REQUIRED_FAMILIES = (
    "rna-uorf",
    "motor",
    "tqssa",
    "fceri",
    "multisite-protocol",
)

UNMEASURED_DETAILS = {
    "release-energy-protocols": (
        "The leaf checks source links, initial states, invariants, closed-form "
        "laws and Ising conservation. No pinned native-NFsim trajectory "
        "comparison is present for each canonical fixture, so 'matching native "
        "NFsim behavior for canonical constructs' is unmeasured."
    ),
    "release-extension-protocols": (
        "The leaf checks analytic cycle-affinity arithmetic stated in the "
        "harness and product mass conservation. The rate/affinity equality is "
        "not tied to product-derived rates, so the extension protocol check "
        "is only partially measured."
    ),
    "release-obligation-152": (
        "Contract schema, obligation inventory, reconciliation ledger and "
        "fail-closed gate refusal are checked by the collected leaf."
    ),
}


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


def run_tests(root: Path = ROOT) -> dict[str, dict]:
    """Run the collected leaf file and return the checks it genuinely covered."""
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
    return {"release-obligation-152": {"selector": TEST_FILE, "returncode": 0}}


def verify_native_report(path: Path, revision: str) -> dict | None:
    """Validate a canonical native-NFsim comparison report."""
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(report, dict)
        or report.get("check") != "release-energy-protocols"
    ):
        return None
    if (
        report.get("source_revision") != revision
        or report.get("source_dirty") is not False
    ):
        return None
    if report.get("status") != "PASS":
        return None
    if report.get("native_revision") != report.get("expected_native_revision"):
        return None
    families = report.get("families")
    if not isinstance(families, dict):
        return None
    for family in REQUIRED_FAMILIES:
        row = families.get(family)
        if not isinstance(row, dict) or row.get("native_comparison") is not True:
            return None
        if not row.get("seed_budget") or not row.get("independent_oracle"):
            return None
    return report


def verify_extension_report(path: Path, revision: str) -> dict | None:
    """Validate product-linked extension-protocol evidence."""
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(report, dict)
        or report.get("check") != "release-extension-protocols"
    ):
        return None
    if (
        report.get("source_revision") != revision
        or report.get("source_dirty") is not False
    ):
        return None
    if report.get("status") != "PASS":
        return None
    rows = report.get("checks")
    if not isinstance(rows, dict):
        return None
    for key in ("cycle_affinity", "driven_monotonicity", "barrier_detailed_balance"):
        row = rows.get(key)
        if not isinstance(row, dict) or row.get("product_linked") is not True:
            return None
        if not row.get("independent_expectation"):
            return None
    return report


def build_release_record(
    expected_revision=None,
    root=ROOT,
    skip_tests=False,
    allow_dirty=False,
    reports=None,
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
    executed = (run_tests(root) if not skip_tests else {}) or {}

    reports = reports or {}
    native = (
        verify_native_report(Path(reports["release-energy-protocols"]), revision)
        if "release-energy-protocols" in reports
        else None
    )
    extension = (
        verify_extension_report(Path(reports["release-extension-protocols"]), revision)
        if "release-extension-protocols" in reports
        else None
    )

    results = []
    for check_id in EXPECTED_CHECKS:
        measured = check_id in MEASURED_LEAF_CHECKS and check_id in executed
        reported = (check_id == "release-energy-protocols" and native is not None) or (
            check_id == "release-extension-protocols" and extension is not None
        )
        if not skip_tests and (measured or reported):
            status = "PASS"
            evidence_kind = "supported-execution"
            supported = True
            detail = (
                "Consuming report covers the named check with independent evidence."
                if reported
                else UNMEASURED_DETAILS[check_id]
            )
        else:
            status = "NOT_TESTED"
            evidence_kind = "not-tested"
            supported = False
            detail = UNMEASURED_DETAILS[check_id]
        results.append(
            {
                "id": check_id,
                "check": check_id,
                "test_file": manifest[check_id]["selector"],
                "status": status,
                "evidence_kind": evidence_kind,
                "supported_execution": supported,
                "related_issues": [152],
                "stage": check_id,
                "detail": detail,
                "source_revision": revision,
                "selector": manifest[check_id]["selector"],
            }
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
            "reports": {k: str(v) for k, v in sorted(reports.items())},
        },
        "results": results,
        "manifest_check_ids": sorted(EXPECTED_CHECKS),
        "unmeasured_checks": sorted(
            row["id"] for row in results if row["status"] == "NOT_TESTED"
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-revision")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--summary-file", type=Path)
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument(
        "--report",
        action="append",
        default=[],
        metavar="CHECK=PATH",
        help="consuming scientific report for a named check (repeatable)",
    )
    a = p.parse_args(argv)
    reports = {}
    for item in a.report:
        check_id, _, path = item.partition("=")
        if check_id not in REPORT_CHECKS or not path:
            _fail(f"invalid --report: {item}")
        reports[check_id] = path
    rec = build_release_record(
        a.source_revision,
        skip_tests=a.skip_tests,
        allow_dirty=a.allow_dirty,
        reports=reports,
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
