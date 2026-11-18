#!/usr/bin/env python3
"""Execute the accepted provenance checks required by upstream reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from record_issue142_release import read_junit_cases

ROOT = Path(__file__).resolve().parents[2]
CHECKS = {
    "release-provenance": {
        "test_release_provenance_accepts_current_lock_and_ratchet": 1,
    },
    "release-provenance-negative": {
        "test_release_provenance_negative_rejects_mutated_lock": 3,
        "test_release_provenance_negative_rejects_stale_ratchet": 1,
    },
    "release-obligation-179": {
        "test_release_obligation_179_executes_strict_gate_before_release_evidence": 1,
    },
}


def run_check(check_id: str, expected: dict[str, int], output: Path) -> dict:
    junit = output / f"{check_id}.xml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "-q",
            *(f"tests/test_ci_contract.py::{test}" for test in expected),
            "--junitxml",
            str(junit),
        ],
        cwd=ROOT,
        check=False,
    )
    detail = f"pytest exit code {result.returncode}"
    passed = False
    if result.returncode == 0:
        try:
            cases = read_junit_cases(junit)
            observed = {test: 0 for test in expected}
            for case in cases:
                test = case.partition("[")[0]
                if test not in observed:
                    raise ValueError(f"unexpected provenance test case: {case}")
                observed[test] += 1
            if observed != expected:
                raise ValueError(f"expected {expected}, executed {observed}")
            passed = True
            detail = ", ".join(sorted(cases))
        except ValueError as exc:
            detail = str(exc)
    row = dict(
        id=check_id,
        status="PASS" if passed else "FAIL",
        evidence_kind="supported-execution",
        supported_execution=passed,
        related_issues=[179],
        detail=detail,
    )
    if junit.is_file():
        row["junit"] = junit.name
        row["junit_sha256"] = hashlib.sha256(junit.read_bytes()).hexdigest()
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    if head.strip() != args.revision or dirty:
        parser.error("provenance acceptance requires the requested clean BNG3 revision")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = [run_check(check, tests, output) for check, tests in CHECKS.items()]
    lock = ROOT / "provenance/upstreams.lock.yml"
    report = {
        "schema_version": 1,
        "source": {"revision": args.revision, "dirty": False},
        "references": {
            "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "locked_sources": json.loads(lock.read_bytes())["sources"],
        },
        "results": results,
    }
    (output / "reconciliation-prerequisite.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return int(any(row["status"] != "PASS" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
