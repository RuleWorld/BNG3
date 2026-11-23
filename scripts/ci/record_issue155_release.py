#!/usr/bin/env python3
"""Execute and record Issue 155 native BNGIR contracts & adversarial release acceptance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.validation.junit import executed_test_names, require_passing_junit

EXPECTED_CHECKS = (
    "release-bngir-adversarial",
    "release-bngir-consumer",
    "release-obligation-155",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads((root / "provenance/issue-obligations.json").read_text())
    issue = next((item for item in manifest["issues"] if item["number"] == 155), None)
    if issue is None:
        _fail("Issue 155 is missing from the obligations manifest")
    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            check_id = check["id"]
            if check_id not in EXPECTED_CHECKS:
                continue
            if check_id in checks:
                _fail(f"duplicate or conflicting manifest definition for {check_id}")
            checks[check_id] = {
                "definition": check,
                "test_references": obligation.get("test_references", []),
            }
    missing = set(EXPECTED_CHECKS) - set(checks)
    if missing:
        _fail(f"manifest is missing required checks: {sorted(missing)}")
    return checks


def run_tests(root: Path = ROOT) -> list[str]:
    test_path = (
        root
        / "tests/validation/release/cases/issue-155/test_bngir_adversarial_release.py"
    )
    if not test_path.is_file():
        _fail(f"missing test file: {test_path}")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--confcutdir=tests/validation/release/cases/issue-155",
        str(test_path),
    ]
    with TemporaryDirectory() as directory:
        junit = Path(directory) / "pytest.xml"
        result = subprocess.run(
            [*cmd, "--junitxml", str(junit)],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _fail(
                f"Issue 155 release tests failed (code {result.returncode}):\n{result.stdout}\n{result.stderr}"
            )
        require_passing_junit(
            junit,
            [
                "test_release_bngir_adversarial",
                "test_release_bngir_consumer",
                "test_release_obligation_155",
            ],
        )
        return executed_test_names(junit)


def build_release_record(
    expected_revision: str | None = None,
    root: Path = ROOT,
    skip_tests: bool = False,
    allow_dirty: bool = False,
    junit_path: Path | None = None,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()

    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 155 evidence: checkout HEAD {head} != {expected_revision}")
    revision = expected_revision or head

    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 155 evidence checkout is dirty: {dirty}")

    manifest_checks = verify_manifest(root)

    tested_cases: set[str] = set()
    if junit_path is not None:
        require_passing_junit(
            junit_path,
            [
                "test_release_bngir_adversarial",
                "test_release_bngir_consumer",
                "test_release_obligation_155",
            ],
        )
        tested_cases = executed_test_names(junit_path)
    elif not skip_tests:
        res = run_tests(root)
        if isinstance(res, (list, set, tuple)):
            tested_cases = set(res)

    details = {
        "release-bngir-adversarial": (
            "Hand-authored valid documents validate and roundtrip; malformed JSON "
            "cases fail closed; mutations across units, reversed rules, bonds, maps "
            "and observables are distinguished."
        ),
        "release-bngir-consumer": (
            "Native consumers execute hand-authored valid cases against independent "
            "analytic continuous-time trajectories without BNGL translation."
        ),
        "release-obligation-155": (
            "Exact-revision contract, capability inventory rows (bngir.native, bngir.v02), "
            "and live acceptance obligations verified."
        ),
    }
    results = [
        {
            "id": check_id,
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [155],
            "stage": check_id,
            "detail": details[check_id],
        }
        for check_id in EXPECTED_CHECKS
    ]

    case_map = {
        "release-bngir-adversarial": "test_release_bngir_adversarial",
        "release-bngir-consumer": "test_release_bngir_consumer",
        "release-obligation-155": "test_release_obligation_155",
    }
    for row in results:
        expected_case = case_map.get(row["id"])
        if skip_tests or expected_case not in tested_cases:
            row["status"] = "NOT_TESTED"
            row["supported_execution"] = False
            row["evidence_kind"] = "not-tested"
            if skip_tests:
                row["detail"] = (
                    "Execution was skipped; no scientific acceptance evidence was collected."
                )
            else:
                row["detail"] = (
                    f"Test case {expected_case} was not executed or verified."
                )

    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-155",
        "case": "issue-155-bngir-adversarial-release",
        "source": {
            "revision": revision,
            "dirty": bool(dirty),
        },
        "references": {
            "wire_schemas": "provenance/schemas/bngir-0.1.schema.json and bngir-0.2.schema.json",
            "fixtures": "tests/fixtures/bngir/adversarial",
            "provenance": "provenance/issue-obligations.json and capability-matrix.yml",
        },
        "results": results,
        "manifest_check_ids": sorted(manifest_checks.keys()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 155 BNGIR adversarial release acceptance."
    )
    parser.add_argument("--source-revision", help="Expected git commit SHA")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--summary-file", type=Path, help="GitHub step summary path")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip executing tests (verification of manifest/revision only)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow dirty checkout (local testing only)",
    )
    parser.add_argument("--junit", type=Path, help="Path to passing junit XML report")
    args = parser.parse_args(argv)

    try:
        record = build_release_record(
            expected_revision=args.source_revision,
            skip_tests=args.skip_tests,
            allow_dirty=args.allow_dirty,
            junit_path=args.junit,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        summary = [
            "## Issue 155 BNGIR adversarial release obligation record",
            "",
            f"- Source commit: `{record['source']['revision']}`",
            *(f"- {row['id']}: {row['status']}" for row in record["results"]),
            "",
            f"Consolidated JSON report: `{args.output}`",
            "",
        ]
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(summary))
        else:
            sys.stdout.write("\n".join(summary))
        return 0
    except Exception as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
