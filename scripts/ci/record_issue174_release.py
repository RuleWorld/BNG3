#!/usr/bin/env python3
"""Execute and record Issue 174 published CPU benchmark acceptance evidence.

The historical ``bench/baseline.json`` is preserved at its original revision.
This recorder does not treat that manifest as a current benchmark. A PASS
requires a consuming current-report with machine, toolchain, source and build
identity, cold/warm measurements, alternating A/A controls, independent
correctness for every required workload, an explicit platform family (Apple and
Linux measurements are never merged), and a clean #176 acceptance report.
"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_CHECKS = (
    "release-benchmarks",
    "release-benchmark-correctness",
    "release-obligation-174",
)
TEST_FILES = ("tests/validation/release/cases/issue-174/test_cpu_benchmark_evidence.py",)
REQUIRED_WORKLOADS = (
    "parse_compile", "netgen", "ode", "ssa", "nfnext", "scan"
)
REQUIRED_IDENTITY = (
    "source_revision", "host", "machine", "python", "compiler",
    "extension_sha256", "platform_family", "historical_baseline_revision",
    "historical_baseline_sha256",
)

UNMEASURED_DETAILS = {
    "release-benchmarks": (
        "Only the historical baseline manifest is validated. No current "
        "machine/corpus/revision record with cold/warm measurements for the "
        "required CPU workloads was consumed."
    ),
    "release-benchmark-correctness": (
        "Historical guard strings are retained, but no current measured "
        "workload with an independent correctness result and A/A control was "
        "consumed."
    ),
    "release-obligation-174": (
        "The historical identity leaf ran. A current benchmark record with "
        "toolchain/build identity and a clean #176 acceptance report is "
        "required before final acceptance."
    ),
}


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 174), None)
    if issue is None:
        _fail("Issue 174 is missing from the obligations manifest")
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
            cwd=str(root), capture_output=True, text=True,
        )
        if result.returncode != 0:
            _fail(
                f"Issue 174 test {rel} failed (code {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        executed[rel] = {"selector": rel, "returncode": 0}
    return executed


def _expected_platform_family() -> str:
    system = platform.system().lower()
    return "apple" if system == "darwin" else "linux" if system == "linux" else system


def verify_current_report(path: Path, revision: str) -> dict | None:
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("status") != "PASS":
        return None
    identity = report.get("identity")
    if not isinstance(identity, dict):
        return None
    if identity.get("source_revision") != revision:
        return None
    if any(not identity.get(key) for key in REQUIRED_IDENTITY):
        return None
    # Apple and Linux measurements stay distinct: a report recorded on another
    # platform family cannot qualify the current machine's benchmark.
    if identity.get("platform_family") != _expected_platform_family():
        return None
    workloads = report.get("workloads")
    if not isinstance(workloads, dict):
        return None
    for name in REQUIRED_WORKLOADS:
        row = workloads.get(name)
        if not isinstance(row, dict) or row.get("status") != "PASS":
            return None
        if not row.get("median") or not row.get("control"):
            return None
    if not report.get("alternating_aa_control"):
        return None
    return report


def verify_issue176_report(path: Path) -> dict | None:
    """#174 final acceptance requires a clean #176 acceptance report first."""
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    results = {row.get("id"): row.get("status") for row in report.get("results", [])}
    for check_id in ("release-nf-ensemble", "release-capability-coverage-176"):
        if results.get(check_id) != "PASS":
            return None
    return report


def build_release_record(
    expected_revision: str | None = None,
    root: Path = ROOT,
    skip_tests: bool = False,
    allow_dirty: bool = False,
    current_report: str | None = None,
    issue176_report: str | None = None,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 174 evidence: HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 174 evidence checkout is dirty: {dirty}")

    manifest = verify_manifest(root)
    executed = (run_tests(root) if not skip_tests else {}) or {}
    current = verify_current_report(Path(current_report), revision) if current_report else None
    prior = verify_issue176_report(Path(issue176_report)) if issue176_report else None

    results = []
    for check_id in EXPECTED_CHECKS:
        qualified = bool(current) and bool(executed)
        if check_id == "release-obligation-174":
            qualified = qualified and bool(prior)
        if not skip_tests and qualified:
            status, evidence_kind, supported = "PASS", "supported-execution", True
            detail = (
                "Consuming current benchmark report and #176 acceptance report "
                "carry full identity, cold/warm measurements and controls."
            )
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
                "related_issues": [174],
                "stage": check_id,
                "detail": detail,
                "source_revision": revision,
                "selector": manifest[check_id]["selector"],
            }
        )
    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-174",
        "case": "issue-174-cpu-benchmark-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "leaf_tests": list(TEST_FILES),
            "provenance": "provenance/issue-obligations.json",
            "baseline": "bench/baseline.json (preserved at original SHA)",
            "current_report": current_report or "",
            "issue176_report": issue176_report or "",
            "platform_family": _expected_platform_family(),
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
    parser.add_argument("--current-report", type=Path)
    parser.add_argument("--issue176-report", type=Path)
    args = parser.parse_args(argv)
    record = build_release_record(
        expected_revision=args.source_revision,
        skip_tests=args.skip_tests,
        allow_dirty=args.allow_dirty,
        current_report=str(args.current_report) if args.current_report else None,
        issue176_report=str(args.issue176_report) if args.issue176_report else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        with args.summary_file.open("a", encoding="utf-8") as handle:
            handle.write("\n## Issue 174 CPU benchmark release evidence\n\n")
            for row in record["results"]:
                handle.write(f"- {row['id']}: {row['status']}\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
