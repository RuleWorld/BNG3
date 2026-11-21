#!/usr/bin/env python3
"""Execute and record Issue 150 particle-population hybrid release acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_CHECKS = (
    "release-hybrid",
    "release-hybrid-conservation",
    "release-capability-coverage-150",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 150), None)
    if issue is None:
        _fail("Issue 150 is missing from the obligations manifest")
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


def verify_junit_xml(path: Path) -> None:
    if not path.is_file():
        _fail(f"missing JUnit XML: {path}")
    tree = ET.parse(path)
    root = tree.getroot()
    testcases = list(root.iter("testcase"))
    if not testcases:
        _fail(f"JUnit XML has no test cases: {path}")
    failed_or_errored = [
        tc.attrib.get("name", "")
        for tc in testcases
        if tc.find("failure") is not None or tc.find("error") is not None
    ]
    if failed_or_errored:
        _fail(f"JUnit XML contains failed cases: {failed_or_errored}")
    skipped = [
        tc.attrib.get("name", "") for tc in testcases if tc.find("skipped") is not None
    ]
    if skipped:
        _fail(f"JUnit XML contains skipped cases: {skipped}")

    names = {tc.attrib.get("name", "") for tc in testcases}
    expected_case_fragments = (
        "test_release_hybrid_bng2_native_nfsim_and_bng3_trajectories",
        "test_release_hybrid_conservation_and_analytic_conversion_law",
        "test_release_capability_coverage_150",
        "test_release_hybrid_stage_continuation",
    )
    for fragment in expected_case_fragments:
        if not any(fragment in name for name in names):
            _fail(f"JUnit XML missing expected testcase: {fragment}")


def _case_passes(entry: object, oracle: str, evidence_dir: Path) -> bool:
    if (
        not isinstance(entry, dict)
        or entry.get("passed") is not True
        or entry.get("oracle") != oracle
    ):
        return False
    artifacts = entry.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return False
    for name, digest in artifacts.items():
        if Path(name).name != name:
            return False
        path = evidence_dir / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            return False
    return True


def complete_inventory_coverage(report: dict, root: Path, evidence_dir: Path) -> bool:
    if report.get("issue_150_acceptance") != "complete":
        return False
    matrix = json.loads(
        (root / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    contract = json.loads(
        (root / "tests/validation/release/cases/issue-150/contract.json").read_text(
            encoding="utf-8"
        )
    )
    required = {row["id"] for row in matrix["rows"] if row["issue"] == 150}
    if required != set(contract["inventory_rows"]):
        return False

    sources = json.loads(
        (root / "provenance/upstreams.lock.yml").read_text(encoding="utf-8")
    )["sources"]
    oracles = report.get("oracles", {})
    if not isinstance(oracles, dict):
        return False
    for name, pin, field in (
        ("bng2", "bionetgen", "script_sha256"),
        ("native_nfsim", "nfsim", "binary_sha256"),
    ):
        oracle = oracles.get(name)
        if (
            not isinstance(oracle, dict)
            or oracle.get("revision") != sources[pin]["revision"]
        ):
            return False
        if not re.fullmatch(r"[a-f0-9]{64}", str(oracle.get(field, ""))):
            return False

    rows = report.get("inventory_cases")
    if not isinstance(rows, dict) or set(rows) != required:
        return False
    for identity in required - {"hybrid.execution"}:
        if not _case_passes(rows[identity], "bng2-options", evidence_dir):
            return False
    execution = rows["hybrid.execution"]
    if not isinstance(execution, dict) or execution.get("passed") is not True:
        return False
    cases = execution.get("cases")
    case_oracles = contract["hybrid_execution_cases"]
    return (
        isinstance(cases, dict)
        and set(cases) == set(case_oracles)
        and all(
            _case_passes(cases[name], oracle, evidence_dir)
            for name, oracle in case_oracles.items()
        )
    )


def verify_evidence_directory(
    evidence_dir: Path, revision: str, root: Path = ROOT
) -> set[str]:
    if not evidence_dir.is_dir():
        _fail(f"missing evidence directory: {evidence_dir}")
    qual_file = evidence_dir / "qualification.json"
    if qual_file.is_file():
        qual = json.loads(qual_file.read_text(encoding="utf-8"))
        dist = qual.get("distributional_comparison", {})
        if dist.get("passed") is not True:
            _fail(f"distributional comparison failed: {dist}")

    cov_file = evidence_dir / "capability-coverage-150.json"
    if not cov_file.is_file():
        return set()
    cov = json.loads(cov_file.read_text(encoding="utf-8"))
    source = cov.get("source", {})
    if (
        not isinstance(source, dict)
        or source.get("revision") != revision
        or source.get("dirty") is not False
    ):
        _fail("stale or dirty hybrid capability evidence")
    passed_checks = set()
    for name, entry in cov.get("semantic_checks", {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("passed") is False:
            _fail(f"semantic check {name} failed in capability-coverage-150.json")
        if entry.get("passed") is True:
            passed_checks.add(name)
    if (
        "release-capability-coverage-150" in passed_checks
        and not complete_inventory_coverage(cov, root, evidence_dir)
    ):
        passed_checks.remove("release-capability-coverage-150")
    return passed_checks


def run_tests(root: Path, evidence_dir: Path) -> None:
    test_path = root / "tests/validation/test_hybrid_execution.py"
    if not test_path.is_file():
        _fail(f"missing test file: {test_path}")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        "tests/validation/pytest.ini",
        "-q",
        "-ra",
        str(test_path),
    ]
    result = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "BNG3_HYBRID_EVIDENCE_DIR": str(evidence_dir)},
    )
    if result.returncode != 0:
        _fail(
            f"Issue 150 release tests failed (code {result.returncode}):\n{result.stdout}\n{result.stderr}"
        )


def build_release_record(
    expected_revision: str | None = None,
    evidence_dir: Path | None = None,
    junit_xml: Path | None = None,
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
        _fail(f"stale Issue 150 evidence: checkout HEAD {head} != {expected_revision}")
    revision = expected_revision or head

    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 150 evidence checkout is dirty: {dirty}")

    manifest_checks = verify_manifest(root)

    passed_checks: set[str] = set()
    if not skip_tests:
        if junit_xml:
            verify_junit_xml(junit_xml)
        if evidence_dir:
            passed_checks = verify_evidence_directory(evidence_dir, revision, root)
        if not junit_xml and not evidence_dir:
            with TemporaryDirectory(prefix="bng3-hybrid-evidence-") as temp_dir:
                generated_evidence = Path(temp_dir)
                run_tests(root, generated_evidence)
                passed_checks = verify_evidence_directory(
                    generated_evidence, revision, root
                )

    results = [
        {
            "id": "release-hybrid",
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [150],
            "stage": "hybrid-distribution-parity",
            "detail": (
                "BNG2 hybrid output executed by native NFsim matches BNG3 hybrid "
                "distributions and observables within 4.0 sigma pooled SE."
            ),
        },
        {
            "id": "release-hybrid-conservation",
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [150],
            "stage": "hybrid-conservation-laws",
            "detail": (
                "independent analytic conversion/mass conservation and multiplicity laws "
                "hold in mixed particle/population cases (A_total + B_total = N, dimer A_units = 2*N)."
            ),
        },
        {
            "id": "release-capability-coverage-150",
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [150],
            "stage": "hybrid-capability-coverage",
            "detail": (
                "all assigned inventory cases execute against their row's named independent "
                "oracle (pinned BNG2, native NFsim and analytic laws). The retained "
                "capability-coverage-150.json identifies the executed cases and replay artifacts."
            ),
        },
    ]

    for row in results:
        if row["id"] in passed_checks:
            continue
        row["status"] = "NOT_TESTED"
        row["supported_execution"] = False
        row["evidence_kind"] = "not-tested"
        row["detail"] = (
            "Execution was skipped; no scientific acceptance evidence was collected."
            if skip_tests
            else "The capability report lacks affirmative evidence for the full check."
        )

    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-150",
        "case": "issue-150-hybrid-execution-release",
        "source": {
            "revision": revision,
            "dirty": bool(dirty),
        },
        "references": {
            "bng2": "pinned BNG2 generate_hybrid_model option contract and HPP transformation",
            "native_nfsim": "pinned native NFsim stochastic ensembles (4.0-sigma distributional agreement)",
            "analytic_laws": "pure-death and reversible CTMC binomial marginals and exact mass conservation",
        },
        "results": results,
        "manifest_check_ids": sorted(manifest_checks.keys()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 150 particle-population hybrid release acceptance."
    )
    parser.add_argument("--source-revision", help="Expected git commit SHA")
    parser.add_argument(
        "--evidence-dir", type=Path, help="Path to hybrid evidence directory"
    )
    parser.add_argument("--junit-xml", type=Path, help="Path to JUnit XML test report")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--summary-file", type=Path, help="GitHub step summary path")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail unless all Issue 150 checks passed",
    )
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
        report = build_release_record(
            expected_revision=args.source_revision,
            evidence_dir=args.evidence_dir,
            junit_xml=args.junit_xml,
            root=ROOT,
            skip_tests=args.skip_tests,
            allow_dirty=args.allow_dirty,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        summary = [
            "## Issue 150 particle-population hybrid release obligation record",
            "",
            f"- Main/source commit: `{report['source']['revision']}`",
            *(f"- {row['id']}: {row['status']}" for row in report["results"]),
            f"- Pinned BNG2 oracle: `{report['references']['bng2']}`",
            f"- Pinned native NFsim oracle: `{report['references']['native_nfsim']}`",
            f"- Analytic CTMC oracle: `{report['references']['analytic_laws']}`",
            "",
            f"Consolidated JSON: `{args.output}`",
            "",
        ]
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(summary))
        else:
            sys.stdout.write("\n".join(summary))
        if args.require_complete:
            missing = [
                row["id"] for row in report["results"] if row["status"] != "PASS"
            ]
            if missing:
                _fail("missing affirmative acceptance evidence: " + ", ".join(missing))
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"Issue 150 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
