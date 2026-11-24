#!/usr/bin/env python3
"""Execute and record Issue 156 BNGIR/semantic-equality release acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
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
    "release-bngir-schema",
    "release-semantic-equality",
    "release-capability-coverage-156",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads((root / "provenance/issue-obligations.json").read_text())
    issue = next((item for item in manifest["issues"] if item["number"] == 156), None)
    if issue is None:
        _fail("Issue 156 is missing from the obligations manifest")
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


def run_tests(root: Path = ROOT) -> set[str]:
    test_path = root / "tests/validation/release/cases/issue-156/test_bngir_release.py"
    if not test_path.is_file():
        _fail(f"missing test file: {test_path}")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--confcutdir=tests/validation/release/cases/issue-156",
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
                f"Issue 156 release tests failed (code {result.returncode}):\n{result.stdout}\n{result.stderr}"
            )
        require_passing_junit(
            junit,
            [
                "test_release_bngir_schema",
                "test_release_semantic_equality",
                "test_release_capability_coverage_156",
            ],
        )
        return executed_test_names(junit)


def build_release_record(
    expected_revision: str | None = None,
    root: Path = ROOT,
    skip_tests: bool = False,
    allow_dirty: bool = False,
    junit_path: Path | None = None,
    eq_catalogue_path: Path | None = None,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()

    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 156 evidence: checkout HEAD {head} != {expected_revision}")
    revision = expected_revision or head

    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 156 evidence checkout is dirty: {dirty}")

    manifest_checks = verify_manifest(root)

    # Per-row EQ evidence is part of the acceptance check, not an optional
    # attachment.  Run the independent catalogue and keep its row identities
    # and oracle names in the receipt; a membership-only document fails here.
    try:
        from tests.validation.eq_catalogue import (
            run_catalogue,
            validate_catalogue_report,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "bionetgen":
            raise
        # The prerequisite job runs without the installed BNG3 package. The EQ
        # catalogue cannot execute there; keep the receipt but leave dependent
        # checks NOT_TESTED instead of failing the whole prerequisite or
        # claiming PASS. This mirrors the missing-native-binding disposition.
        run_catalogue = None
        validate_catalogue_report = None

    eq_catalogue = None
    artifact_path = None
    if eq_catalogue_path is not None:
        if run_catalogue is None:
            _fail("EQ catalogue artifact supplied but BNG3 package is unavailable")
        if not eq_catalogue_path.is_file():
            _fail(f"missing EQ catalogue artifact: {eq_catalogue_path}")
        eq_catalogue = json.loads(eq_catalogue_path.read_text())
        validate_catalogue_report(eq_catalogue)
        artifact_path = eq_catalogue_path
    elif not skip_tests and run_catalogue is not None:
        try:
            eq_catalogue = run_catalogue()
        except RuntimeError as exc:
            if "native BNG3 binding" not in str(exc):
                raise
            # A job without the optional native binding cannot execute the EQ
            # catalogue. Keep the receipt but mark dependent checks NOT_TESTED
            # rather than failing the whole CI prerequisite or claiming PASS.
            eq_catalogue = None
        if eq_catalogue is not None:
            validate_catalogue_report(eq_catalogue)

    tested_cases: set[str] = set()
    if junit_path is not None:
        require_passing_junit(
            junit_path,
            [
                "test_release_bngir_schema",
                "test_release_semantic_equality",
                "test_release_capability_coverage_156",
            ],
        )
        tested_cases = executed_test_names(junit_path)
    elif not skip_tests:
        res = run_tests(root)
        if isinstance(res, (list, set, tuple)):
            tested_cases = set(res)

    details = {
        "release-bngir-schema": (
            "v0.1/v0.2 BNGIR documents validate against their wire schemas, "
            "round trip through real consumers, and v0.2 is the default."
        ),
        "release-semantic-equality": (
            "All EQ-* families execute with declared equal, different or "
            "explicitly undecided outcomes, each tied to a named independent "
            "oracle; numerical similarity never establishes equality."
        ),
        "release-capability-coverage-156": (
            "Inventory rows bngir.v02 and bngir.equality are backed by the "
            "per-row EQ catalogue results, not by inventory membership."
        ),
    }
    results = [
        {
            "id": check_id,
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [156],
            "stage": check_id,
            "detail": details[check_id],
        }
        for check_id in EXPECTED_CHECKS
    ]

    case_map = {
        "release-bngir-schema": "test_release_bngir_schema",
        "release-semantic-equality": "test_release_semantic_equality",
        "release-capability-coverage-156": "test_release_capability_coverage_156",
    }
    for row in results:
        expected_case = case_map.get(row["id"])
        if skip_tests or eq_catalogue is None or expected_case not in tested_cases:
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
        "acceptance_check": "release-obligation-156",
        "case": "issue-156-bngir-semantic-equality-release",
        "source": {
            "revision": revision,
            "dirty": bool(dirty),
        },
        "references": {
            "wire_schemas": "provenance/schemas/bngir-0.1.schema.json and bngir-0.2.schema.json",
            "equality_design": "docs/design/semantic-equal-design.md EQ-* catalogue",
            "provenance": "provenance/issue-obligations.json and capability-matrix.yml",
        },
        "results": results,
        "manifest_check_ids": sorted(manifest_checks.keys()),
        "eq_catalogue": (
            {
                "design": eq_catalogue["design"],
                "case_count": eq_catalogue["case_count"],
                "row_count": eq_catalogue["row_count"],
                "cases": sorted({row["case"] for row in eq_catalogue["results"]}),
                "oracles": sorted({row["oracle"] for row in eq_catalogue["results"]}),
                "outcomes": sorted(
                    {row["observed"] for row in eq_catalogue["results"]}
                ),
                "artifact": (
                    str(artifact_path) if artifact_path else "generated-in-recorder"
                ),
                "sha256": (
                    hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                    if artifact_path
                    else None
                ),
            }
            if eq_catalogue is not None
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 156 BNGIR release acceptance."
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
    parser.add_argument(
        "--eq-catalogue",
        type=Path,
        help="Per-row EQ catalogue artifact validated with the independent oracle identities",
    )
    args = parser.parse_args(argv)

    try:
        record = build_release_record(
            expected_revision=args.source_revision,
            skip_tests=args.skip_tests,
            allow_dirty=args.allow_dirty,
            junit_path=args.junit,
            eq_catalogue_path=args.eq_catalogue,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        summary = [
            "## Issue 156 BNGIR semantic-equality release obligation record",
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
        print(f"Issue 156 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
