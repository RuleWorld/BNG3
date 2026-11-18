#!/usr/bin/env python3
"""Execute and record Issue 152 NFsim energy, Rasi and protocols release acceptance evidence."""

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


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 152), None)
    if issue is None:
        _fail("Issue 152 is missing from the obligations manifest")
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


def run_tests(root: Path = ROOT) -> None:
    test_path = root / "tests/validation/release/cases/issue-152/test_energy_protocols.py"
    if not test_path.is_file():
        _fail(f"missing test file: {test_path}")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--confcutdir=tests/validation/release/cases/issue-152",
        str(test_path),
    ]
    env = dict(subprocess.os.environ)
    env["PYTHONPATH"] = f"{root / 'python'}:{root / 'build/cpp'}:{env.get('PYTHONPATH', '')}"
    result = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        _fail(
            f"Issue 152 release tests failed (code {result.returncode}):\n{result.stdout}\n{result.stderr}"
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
        _fail(f"stale Issue 152 evidence: checkout HEAD {head} != {expected_revision}")
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

    manifest_checks = verify_manifest(root)

    if not skip_tests:
        run_tests(root)

    results = [
        {
            "id": "release-energy-protocols",
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [152],
            "stage": "energy-protocols",
            "detail": (
                "source-linked real-model fixtures execute with matching native NFsim behavior "
                "and exact invariant preservation."
            ),
        },
        {
            "id": "release-extension-protocols",
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [152],
            "stage": "extension-protocols",
            "detail": (
                "analytic cycle affinity and driven-protocol expectations pass for BNG3 energy "
                "extensions under protocol execution."
            ),
        },
        {
            "id": "release-obligation-152",
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [152],
            "stage": "energy-protocols-obligations",
            "detail": (
                "reconciliation records, obligation coverage, and negative containment (fail-closed refusal) pass on main."
            ),
        },
    ]

    if skip_tests:
        for row in results:
            row["status"] = "NOT_TESTED"
            row["supported_execution"] = False
            row["evidence_kind"] = "not-tested"
            row["detail"] = "Execution was skipped; no scientific acceptance evidence was collected."

    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-152",
        "case": "issue-152-energy-protocols-release",
        "source": {
            "revision": revision,
            "dirty": bool(dirty),
        },
        "references": {
            "native_nfsim": "pinned native NFsim 9b00d42f",
            "analytic_laws": "Kolmogorov cycle criterion, Markov thinning law, GK algebraic root",
        },
        "results": results,
        "manifest_check_ids": sorted(manifest_checks.keys()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 152 energy protocols release acceptance."
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
            "## Issue 152 energy protocols release obligation record",
            "",
            f"- Source commit: `{record['source']['revision']}`",
            *(f"- {row['id']}: {row['status']}" for row in record["results"]),
            f"- Native NFsim oracle: `{record['references']['native_nfsim']}`",
            f"- Analytic laws oracle: `{record['references']['analytic_laws']}`",
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
        print(f"Issue 152 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
