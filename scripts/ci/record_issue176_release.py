#!/usr/bin/env python3
"""Execute and record Issue 176 CPU ensemble release acceptance evidence.

Verdicts are evidence-driven. The leaf suite checks reproducibility, seed
independence and a bounded startup/memory/throughput measurement. It does not
by itself establish concurrent trajectory execution, pinned native-NFsim
distribution parity, or measurement of the scaffold and genome workload
families. Those checks require consuming reports and stay ``NOT_TESTED``
without them.

The recorder refuses to emit a PASS record when the checkout is dirty, the
revision is stale, the obligation manifest is incomplete, or a supplied report
is partial/stale/failed. GPU device work is owned by #474.
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
TEST_FILES = (
    "tests/python/nfnext/test_nfnext_ensemble_rng_isolation.py",
    "tests/validation/release/cases/issue-176/test_nf_performance_measurement.py",
)
REQUIRED_WORKLOADS = ("immigration-death", "scaffold", "genome")
PINNED_NFSIM_REVISION = "8c449bbccc4a0c54586ae562f46f4955e65fe876"

UNMEASURED_DETAILS = {
    "release-nf-ensemble": (
        "The leaf checks sequential reproducibility, seed independence and an "
        "analytic mean. Concurrent trajectories through the production entry "
        "point and pinned native-NFsim distribution parity with a fixed seed "
        "budget and stated error control are unmeasured."
    ),
    "release-capability-coverage-176": (
        "The leaf measures a single immigration-death workload. Startup, "
        "memory and throughput for the scaffold and genome workload families "
        "with independent correctness controls are unmeasured."
    ),
}


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


def run_tests(root: Path = ROOT) -> dict[str, dict]:
    executed: dict[str, dict] = {}
    for rel in TEST_FILES:
        path = root / rel
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
                f"Issue 176 test {rel} failed (code {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        executed[rel] = {"selector": rel, "returncode": 0}
    return executed


def _clean_report(path: Path, check_id: str, revision: str) -> dict | None:
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("check") != check_id:
        return None
    if report.get("status") != "PASS":
        return None
    if report.get("source_revision") != revision or report.get("source_dirty") is not False:
        return None
    return report


def verify_ensemble_report(path: Path, revision: str) -> dict | None:
    report = _clean_report(path, "release-nf-ensemble", revision)
    if report is None:
        return None
    if report.get("native_revision") != PINNED_NFSIM_REVISION:
        return None
    if not report.get("concurrent") or not report.get("seed_budget"):
        return None
    if not report.get("error_control") or report.get("control_se") is None:
        return None
    return report


def verify_measurement_report(path: Path, revision: str) -> dict | None:
    report = _clean_report(path, "release-capability-coverage-176", revision)
    if report is None:
        return None
    workloads = report.get("workloads")
    if not isinstance(workloads, dict):
        return None
    for name in REQUIRED_WORKLOADS:
        row = workloads.get(name)
        if not isinstance(row, dict) or row.get("status") != "PASS":
            return None
        if not row.get("correctness") or not row.get("events_per_second"):
            return None
        if row.get("startup_seconds") is None or row.get("peak_rss_kib") is None:
            return None
    return report


def build_release_record(
    expected_revision: str | None = None,
    root: Path = ROOT,
    skip_tests: bool = False,
    allow_dirty: bool = False,
    reports: dict[str, str] | None = None,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 176 evidence: HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 176 evidence checkout is dirty: {dirty}")

    manifest = verify_manifest(root)
    executed = (run_tests(root) if not skip_tests else {}) or {}
    reports = reports or {}
    ensemble = verify_ensemble_report(Path(reports["release-nf-ensemble"]), revision) if "release-nf-ensemble" in reports else None
    measurement = verify_measurement_report(Path(reports["release-capability-coverage-176"]), revision) if "release-capability-coverage-176" in reports else None

    results = []
    for check_id in EXPECTED_CHECKS:
        reported = (check_id == "release-nf-ensemble" and ensemble is not None) or (
            check_id == "release-capability-coverage-176" and measurement is not None
        )
        if not skip_tests and reported and executed:
            status, evidence_kind, supported = "PASS", "supported-execution", True
            detail = "Consuming report covers the named check with declared budgets and controls."
        else:
            status, evidence_kind, supported = "NOT_TESTED", "not-tested", False
            detail = UNMEASURED_DETAILS[check_id]
        results.append(
            {
                "id": check_id,
                "check": check_id,
                "test_file": manifest[check_id]["selector"],
                "status": status,
                "evidence_kind": evidence_kind,
                "supported_execution": supported,
                "related_issues": [176],
                "stage": "issue176-cpu-ensemble",
                "detail": detail,
                "source_revision": revision,
                "selector": manifest[check_id]["selector"],
            }
        )
    return {
        "schema_version": 1,
        "acceptance_check": "release-nf-ensemble",
        "case": "issue-176-cpu-ensemble-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "leaf_tests": list(TEST_FILES),
            "analytic_oracle": "immigration-death mean N0 + (lambda/mu)(1 - exp(-mu t))",
            "native_oracle": PINNED_NFSIM_REVISION,
            "provenance": "provenance/issue-obligations.json",
            "reports": {k: str(v) for k, v in sorted(reports.items())},
            "gpu_scope": "#474",
        },
        "results": results,
        "manifest_check_ids": sorted(EXPECTED_CHECKS),
        "unmeasured_checks": sorted(
            row["id"] for row in results if row["status"] == "NOT_TESTED"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--report", action="append", default=[], metavar="CHECK=PATH")
    args = parser.parse_args(argv)
    reports = {}
    for item in args.report:
        check_id, _, path = item.partition("=")
        if check_id not in EXPECTED_CHECKS or not path:
            _fail(f"invalid --report: {item}")
        reports[check_id] = path
    record = build_release_record(
        expected_revision=args.source_revision,
        skip_tests=args.skip_tests,
        allow_dirty=args.allow_dirty,
        reports=reports,
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
