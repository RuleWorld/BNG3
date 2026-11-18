#!/usr/bin/env python3
"""Execute and record Issue 147 NFnext lowering release acceptance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.validation.campaign import read_junit  # noqa: E402

EXPECTED_CHECKS = (
    "release-nfir-lowering",
    "release-nfir-roundtrip",
    "release-obligation-147",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 147), None)
    if issue is None:
        _fail("Issue 147 is missing from the obligations manifest")
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
    for check_id, info in checks.items():
        definition = info["definition"]
        if not definition.get("identity_requirements"):
            _fail(f"check {check_id} has no identity requirements")
        if definition.get("selector_status") != "COLLECTED":
            _fail(f"check {check_id} selector_status is not COLLECTED")
        if not definition.get("selector"):
            _fail(f"check {check_id} has no collected selector")
        if definition.get("receipt_producer_status") != "CONSUMER_READY":
            _fail(f"check {check_id} receipt_producer_status is not CONSUMER_READY")
        if not definition.get("receipt_producer"):
            _fail(f"check {check_id} has no receipt producer")
    return checks


def run_tests(root: Path = ROOT) -> list[dict]:
    test_path = root / "tests/validation/release/cases/issue-147/test_nfir_lowering.py"
    if not test_path.is_file():
        _fail(f"missing test file: {test_path}")
    with tempfile.TemporaryDirectory(prefix="bng3-issue147-") as directory:
        junit = Path(directory) / "bounded.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--confcutdir=tests/validation/release/cases/issue-147",
            f"--junitxml={junit}",
            str(test_path),
        ]
        result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        if result.returncode != 0:
            _fail(
                f"Issue 147 bounded tests failed (code {result.returncode}):\n{result.stdout}\n{result.stderr}"
            )
        return read_junit(junit, "issue-147-bounded")


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
        _fail(f"stale Issue 147 evidence: checkout HEAD {head} != {expected_revision}")
    revision = expected_revision or head

    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 147 evidence checkout is dirty: {dirty}")

    manifest_checks = verify_manifest(root)

    bounded_results = [] if skip_tests else run_tests(root)

    status = "NOT_TESTED" if skip_tests else "PASS"
    evidence_kind = "not-tested" if skip_tests else "supported-execution"
    supported_execution = not skip_tests
    detail = (
        "Execution was skipped; no scientific acceptance evidence was collected."
        if skip_tests
        else "Verified via bounded NFnext lowering contracts, canonical facts, "
        "and independent pure-death analytical law."
    )
    results = [
        {
            "id": check_id,
            "status": status,
            "evidence_kind": evidence_kind,
            "supported_execution": supported_execution,
            "related_issues": [147],
            "stage": stage,
            "detail": detail,
        }
        for check_id, stage in (
            ("release-nfir-lowering", "nfir-lowering"),
            ("release-nfir-roundtrip", "nfir-roundtrip"),
            ("release-obligation-147", "nfnext-lowering-obligations"),
        )
    ]

    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-147",
        "case": "issue-147-nfnext-lowering-release",
        "source": {
            "revision": revision,
            "dirty": bool(dirty),
        },
        "references": {},
        "bounded_results": bounded_results,
        "bounded_results_scope": (
            "pytest testcase outcomes only; package/build/oracle/consumer identities "
            "and full issue coverage are not established by these rows"
        ),
        "results": results,
        "manifest_check_ids": sorted(manifest_checks.keys()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 147 NFnext lowering release acceptance."
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
    args = parser.parse_args(argv)

    try:
        record = build_release_record(
            expected_revision=args.source_revision,
            root=ROOT,
            skip_tests=args.skip_tests,
            allow_dirty=args.allow_dirty,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        summary = [
            "## Issue 147 NFnext lowering release obligation record",
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
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Issue 147 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
