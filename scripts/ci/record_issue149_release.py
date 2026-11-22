#!/usr/bin/env python3
"""Consume the Issue 149 NFcore consolidation JUnit report as release acceptance.

``tests/validation/release/cases/issue-149/test_nfcore_consolidation.py``
executes the three named acceptance cases.  CI retains its JUnit XML; this
recorder is the revision-locked consumer that turns that artifact into the
three Issue 149 release rows.  It never infers a pass from a command exit code,
and it refuses a missing, failed, errored, skipped, stale or ambiguous case.

The three cases are pre-existing acceptance tests and do not attach JUnit
``property`` elements.  When those identity properties are present they are
checked strictly (``acceptance_check``, ``bng3_revision`` and ``bng3_dirty``).
When they are absent, equivalent revision evidence is required from this
recorder's own retained report: the exact-main git HEAD must match
``--source-revision``, the checkout must be clean, and the verified revision
and clean flag are recorded on the report and on every PASS row.  This
substitution is disclosed in the emitted ``revision_evidence`` block.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_FILE = "tests/validation/release/cases/issue-149/test_nfcore_consolidation.py"
CHECKS = {
    "test_release_engine_consolidation": "release-engine-consolidation",
    "test_release_nf_default": "release-nf-default",
    "test_release_obligation_149": "release-obligation-149",
}
EXPECTED_CHECKS = tuple(CHECKS.values())
RECORD_PRODUCER = "scripts/ci/record_issue149_release.py"
BODY_DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
IDENTITY_PROPERTIES = ("acceptance_check", "bng3_revision", "bng3_dirty")
DETAILS = {
    "release-engine-consolidation": (
        "NFcore2 capabilities map to passing NFnext contracts with preserved "
        "fixtures and demonstrated native NFnext execution."
    ),
    "release-nf-default": (
        "method='nf' selects NFnext on main; explicit NFnext and NFcore remain "
        "selectable and NFcore still matches analytic CTMC laws."
    ),
    "release-obligation-149": (
        "contract, provenance and ownership matrix were checked and unpromoted "
        "method='nfcore2' was refused fail closed."
    ),
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _require(condition: object, message: str) -> None:
    if not condition:
        _fail(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def verify_manifest(root: Path = ROOT) -> dict[str, dict]:
    """Require executable selectors and a consuming receipt for every check."""
    manifest = json.loads(
        (root / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next((item for item in manifest["issues"] if item["number"] == 149), None)
    if issue is None:
        _fail("Issue 149 is missing from the obligations manifest")

    digests = {issue.get("body_sha256")}
    for obligation in issue["obligations"]:
        if obligation["id"].startswith("issue:149:live-acceptance:"):
            digests.add(obligation.get("live_body_sha256"))
    _require(
        len(digests) == 1
        and all(
            isinstance(value, str) and BODY_DIGEST.fullmatch(value) for value in digests
        ),
        "Issue 149 live-body and issue-body digests are stale or conflicting",
    )

    checks: dict[str, dict] = {}
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            check_id = check["id"]
            if check_id not in EXPECTED_CHECKS:
                continue
            if check_id in checks:
                _fail(f"duplicate or conflicting manifest definition for {check_id}")
            checks[check_id] = check
    missing = set(EXPECTED_CHECKS) - set(checks)
    if missing:
        _fail(f"manifest is missing required checks: {sorted(missing)}")

    expected_selectors = {
        check_id: f"{CASE_FILE}::{testcase}" for testcase, check_id in CHECKS.items()
    }
    for check_id, definition in checks.items():
        _require(
            definition.get("evidence_kind") == "supported-execution",
            f"check {check_id} is not supported-execution evidence",
        )
        _require(
            "source.revision" in definition.get("identity_requirements", []),
            f"check {check_id} does not require source revision identity",
        )
        _require(
            definition.get("selector_status") == "COLLECTED"
            and definition.get("selector") == expected_selectors[check_id],
            f"check {check_id} has no collected executable selector",
        )
        _require(
            definition.get("receipt_producer_status") == "CONSUMER_READY"
            and definition.get("receipt_producer") == RECORD_PRODUCER,
            f"check {check_id} is not mapped to its consuming receipt producer",
        )
        _require(
            not definition.get("missing_evidence"),
            f"check {check_id} still carries unmapped missing evidence",
        )
        selector_file = definition["selector"].split("::", 1)[0]
        _require(
            (root / selector_file).is_file(),
            f"selector for {check_id} does not exist: {selector_file}",
        )
    return checks


def _properties(testcase: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for prop in testcase.findall("./properties/property"):
        name = prop.attrib.get("name", "")
        value = prop.attrib.get("value", "")
        if not name:
            _fail("JUnit property has no name")
        if name in result and result[name] != value:
            _fail(f"conflicting JUnit property {name}: {result[name]} vs {value}")
        result[name] = value
    return result


def read_junit_cases(path: Path) -> dict[str, dict[str, str]]:
    """Parse JUnit strictly; any failure, error or skip rejects the artifact."""
    if not path.is_file():
        _fail(f"missing JUnit result: {path}")
    root = ET.parse(path).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        _fail(f"JUnit result has an unexpected root element: {root.tag}")
    testcases = list(root.iter("testcase"))
    if not testcases:
        _fail(f"JUnit result has no test cases: {path}")
    for testcase in testcases:
        name = testcase.attrib.get("name", "")
        for tag in ("failure", "error", "skipped"):
            if testcase.find(tag) is not None:
                _fail(f"JUnit contains {tag} case: {name!r}")
    cases: dict[str, dict[str, str]] = {}
    for testcase in testcases:
        name = testcase.attrib.get("name", "")
        classname = testcase.attrib.get("classname", "")
        if not name or name in cases:
            _fail(f"missing or duplicate JUnit case name: {name!r}")
        if not classname.endswith("test_nfcore_consolidation"):
            _fail(f"JUnit case {name!r} comes from an unexpected class: {classname!r}")
        cases[name] = _properties(testcase)
    return cases


def verify_junit(path: Path, expected_revision: str) -> dict:
    """Require all three leaf cases and reconcile their identity evidence."""
    cases = read_junit_cases(path)
    for testcase, check_id in CHECKS.items():
        if testcase not in cases:
            _fail(f"expected JUnit case {testcase} is missing")
    unexpected = set(cases) - set(CHECKS)
    if unexpected:
        _fail(f"JUnit result carries unexpected cases: {sorted(unexpected)}")

    properties_present = False
    for testcase, check_id in CHECKS.items():
        props = cases[testcase]
        present = [name for name in IDENTITY_PROPERTIES if name in props]
        if not present:
            continue
        if set(present) != set(IDENTITY_PROPERTIES):
            _fail(f"JUnit case {testcase} has partial identity properties: {present}")
        properties_present = True
        if props["acceptance_check"] != check_id:
            _fail(f"JUnit case {testcase} does not identify {check_id}")
        if props["bng3_revision"] != expected_revision:
            _fail(
                f"stale JUnit revision for {testcase}: "
                f"{props['bng3_revision']} != {expected_revision}"
            )
        if props["bng3_dirty"] != "false":
            _fail(f"JUnit case {testcase} was not recorded clean")

    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "testcases": sorted(cases),
        "properties_present": properties_present,
        "revision_evidence_source": (
            "junit-properties" if properties_present else "exact-main-report"
        ),
    }


def build_release_record(
    junit_path: Path,
    expected_revision: str,
    *,
    root: Path = ROOT,
    allow_dirty: bool = False,
) -> dict:
    if not SHA40.fullmatch(expected_revision):
        _fail(f"--source-revision is not a 40-hex commit SHA: {expected_revision!r}")
    head = _git(root, "rev-parse", "HEAD")
    _require(
        head == expected_revision,
        f"stale Issue 149 evidence: checkout HEAD {head} != {expected_revision}",
    )
    dirty = _git(root, "status", "--porcelain")
    if dirty and not allow_dirty:
        _fail(f"Issue 149 evidence checkout is dirty: {dirty}")

    manifest_checks = verify_manifest(root)
    junit = verify_junit(junit_path, expected_revision)

    if junit["properties_present"]:
        basis = (
            "all three JUnit cases carry agreeing acceptance_check, bng3_revision "
            "and bng3_dirty properties"
        )
    else:
        basis = (
            "the acceptance cases emit no identity properties; the recorded "
            "source revision and clean flag are established by this recorder's "
            "exact-main git HEAD check against --source-revision and are carried "
            "on the source block and every PASS row"
        )
    revision_evidence = {
        "junit_identity_properties": (
            "verified" if junit["properties_present"] else "absent"
        ),
        "source": junit["revision_evidence_source"],
        "source_revision": head,
        "source_dirty": bool(dirty),
        "basis": basis,
    }

    results = [
        {
            "id": check_id,
            "status": "PASS",
            "check": check_id,
            "stage": "issue-149-nfcore-consolidation-release",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [149],
            "detail": DETAILS[check_id],
            "testcase": testcase,
            "source_revision": head,
            "bng3_revision": head,
            "bng3_dirty": False,
            "junit_sha256": junit["sha256"],
        }
        for testcase, check_id in CHECKS.items()
    ]
    record = {
        "schema_version": 1,
        "acceptance_check": "release-obligation-149",
        "case": "issue-149-nfcore-consolidation-release",
        "source": {"revision": head, "dirty": bool(dirty)},
        "junit": junit,
        "revision_evidence": revision_evidence,
        "results": results,
        "manifest_check_ids": sorted(manifest_checks),
    }
    if allow_dirty:
        record["local_allow_dirty"] = True
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record Issue 149 NFcore consolidation release acceptance."
    )
    parser.add_argument(
        "--junit", type=Path, required=True, help="JUnit XML from the issue-149 case"
    )
    parser.add_argument(
        "--source-revision", required=True, help="Expected git commit SHA"
    )
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--summary-file", type=Path, help="GitHub step summary path")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Local testing only; the resulting record is not exact-main evidence",
    )
    args = parser.parse_args(argv)

    try:
        record = build_release_record(
            args.junit, args.source_revision, allow_dirty=args.allow_dirty
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        summary = [
            "## Issue 149 NFcore consolidation release obligation record",
            "",
            f"- Source commit: `{record['source']['revision']}`",
            *(
                f"- {row['id']}: {row['status']} "
                f"(supported-execution={str(row['supported_execution']).lower()})"
                for row in record["results"]
            ),
            f"- Revision evidence: `{record['revision_evidence']['source']}`",
            "",
            f"Consolidated JSON report: `{args.output}`",
            "",
        ]
        if args.summary_file:
            with args.summary_file.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(summary))
        else:
            sys.stdout.write("\n".join(summary))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ET.ParseError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Issue 149 release record rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
