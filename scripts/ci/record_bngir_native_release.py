#!/usr/bin/env python3
"""Execute and record Issue 153 native BNGIR reconstruction release checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from record_issue142_release import read_junit_cases  # noqa: E402

# Each check names executable selectors. A whole-directory pytest exit code is
# not row-specific evidence: the recorder parses JUnit and refuses missing or
# skipped cases. No expected value, tolerance or oracle is authored here.
CHECKS = {
    "release-bngir-native": {
        "selectors": [
            "tests/validation/test_bngir_adversarial_native.py",
            "tests/python/test_bngir_native_import.py",
        ],
        "minimum_cases": 10,
    },
    "release-bngir-native-invalid": {
        "selectors": [
            "tests/python/test_bngir_adversarial_fixtures.py::test_adversarial_invalid_fixtures_rejected",
            "tests/python/test_bngir_native_import.py::test_direct_native_builder_rejects_malformed_state_transition_references",
        ],
        "minimum_cases": 2,
    },
    "release-capability-coverage-153": {
        "selectors": [
            "tests/python/test_bngir_roundtrip_matrix.py",
            "tests/python/test_bngir_version_bridge.py",
        ],
        "minimum_cases": 16,
    },
}


def run_check(check_id: str, spec: dict, output: Path) -> dict:
    junit = output / f"{check_id}.xml"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--noconftest",
        "-q",
        *spec["selectors"],
        "--junitxml",
        str(junit),
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    detail = f"pytest exit code {result.returncode}"
    passed, cases = False, []
    if result.returncode == 0:
        try:
            cases = read_junit_cases(junit)
            if len(cases) < spec["minimum_cases"]:
                raise ValueError(
                    f"expected at least {spec['minimum_cases']} cases, ran {len(cases)}"
                )
            passed = True
            detail = f"{len(cases)} executed test cases"
        except ValueError as exc:
            detail = str(exc)
    row = dict(
        id=check_id,
        status="PASS" if passed else "FAIL",
        evidence_kind="supported-execution",
        supported_execution=passed,
        related_issues=[153],
        detail=detail,
        selectors=spec["selectors"],
    )
    if junit.is_file():
        row["junit"] = junit.name
        row["junit_sha256"] = hashlib.sha256(junit.read_bytes()).hexdigest()
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    if head.strip() != args.source_revision or dirty:
        parser.error("issue 153 evidence requires the requested clean BNG3 revision")
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = [run_check(cid, spec, out) for cid, spec in CHECKS.items()]
    report = {
        "schema_version": 1,
        "source": {"revision": args.source_revision, "dirty": False},
        "references": {
            "oracles": "hand-authored native BNGIR v0.2 controls, independent analytic laws and native execution",
        },
        "results": results,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return int(any(row["status"] != "PASS" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
