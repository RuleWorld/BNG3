#!/usr/bin/env python3
"""Execute and record the Issue 164 Atomizer acceptance evidence.

The generated symbol-resolution and seam-ownership characterization rows are
necessary but *not sufficient* for the three named release checks. A bounded
characterization run cannot certify ``release-atomizer-modules`` (one owner per
semantic transformation), ``release-atomizer-refactor`` (before/after official
SSTS and BioModels reports over the same pinned inputs) or
``release-obligation-164``. Those rows stay ``NOT_TESTED`` until real,
exact-revision evidence artifacts are supplied and validated here.

The recorder never authors a scientific expectation and never self-issues a
coverage PASS. A missing, partial, skipped, stale or dirty input fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SELECTOR = "tests/validation/test_atomizer_characterization.py::test_every_named_check_executes_and_passes"
PRODUCER = ".github/workflows/parity.yml#atomizer-characterization"
LIVE_CHECKS = (
    "release-atomizer-modules",
    "release-atomizer-refactor",
    "release-obligation-164",
)
BOUNDARY_CHECK = "release-boundary-extraction-164"

ARCHITECTURE_TESTS = ("test_atomizer_transformation_ownership",)
HONESTY_TESTS = (
    "test_characterization_cannot_certify_full_refactor",
    "test_dirty_checkout_is_reported_dirty",
    "test_partial_before_after_report_is_rejected",
    "test_stale_pin_is_rejected",
)

NOT_TESTED_DETAIL = {
    "release-atomizer-modules": (
        "No architecture ownership report was consumed; characterization of "
        "symbol resolution and one rate-rule seam does not show one owner per "
        "semantic transformation."
    ),
    "release-atomizer-refactor": (
        "No before/after official SSTS and BioModels comparison was consumed; "
        "a bounded characterization run is not a corpus preservation check."
    ),
    "release-obligation-164": (
        "Named work clauses are not all backed by real evidence: architecture "
        "ownership and before/after corpus comparison are required."
    ),
    BOUNDARY_CHECK: (
        "The total-rate seam owner is characterized, but the qualified checks "
        "that cover the affected surface have not been compared before/after."
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _junit_passed(path: Path | None, required: tuple[str, ...]) -> bool:
    """Return True only when every required test ran and none was skipped/failed.

    A file that is missing, empty, unreadable, or contains a failure, error or
    skipped case cannot satisfy an evidence requirement.
    """
    if path is None or not path.is_file():
        return False
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return False
    passed: set[str] = set()
    for suite in suites:
        if suite.get("failures", "0") not in ("0", None):
            return False
        if suite.get("errors", "0") not in ("0", None):
            return False
        if suite.get("skipped", "0") not in ("0", None):
            return False
        for case in suite.findall("testcase"):
            if any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            ):
                return False
            passed.add(case.get("name", "").split("[")[0])
    return all(name in passed for name in required)


def _valid_comparison(document: dict, expected_revision: str) -> tuple[bool, list[str]]:
    """Validate a before/after corpus comparison artifact; fail closed."""
    problems: list[str] = []
    if document.get("schema_version") != 1:
        problems.append("unsupported comparison schema_version")
    sources = {}
    for side in ("before", "after"):
        block = document.get(side)
        if not isinstance(block, dict):
            problems.append(f"missing {side} report block")
            continue
        source = block.get("source") or {}
        if side == "after" and source.get("revision") != expected_revision:
            problems.append(
                f"after report revision {source.get('revision')!r} != {expected_revision}"
            )
        if not source.get("revision"):
            problems.append(f"{side} report has no source revision")
        if source.get("dirty") is not False:
            problems.append(f"{side} report was not produced from a clean checkout")
        if block.get("full_run") is not True:
            problems.append(f"{side} report is not a full (non-partial) run")
        if block.get("report_sha256") is None:
            problems.append(f"{side} report has no artifact hash")
        sources[side] = source

    before_pins = (document.get("before") or {}).get("pins")
    after_pins = (document.get("after") or {}).get("pins")
    if not isinstance(before_pins, dict) or not before_pins:
        problems.append("before inputs are not pinned")
    elif before_pins != after_pins:
        problems.append("before/after reports do not use the same pinned inputs")

    references = document.get("references") or {}
    for name in ("ssts", "biomodels"):
        ref = references.get(name) or {}
        if not ref.get("revision") or not ref.get("sha256"):
            problems.append(f"{name} independent reference identity is incomplete")

    comparison = document.get("record_comparison") or {}
    if comparison.get("all_match") is not True:
        problems.append("before/after records do not match")
    for key in ("missing", "extra", "status_changed", "stale"):
        if comparison.get(key):
            problems.append(f"comparison has {key} records: {comparison[key]}")
    counts = document.get("counts") or {}
    for key in ("failed", "timeout", "invalid_source", "skipped"):
        if counts.get(key, 0) != 0:
            problems.append(f"report has {counts[key]} {key} cases")
    if not (document.get("reference_laws") or {}).get("independent"):
        problems.append("no independent reference law identity recorded")
    return not problems, problems


def build_receipt(
    *,
    head: str,
    dirty: bool,
    rows: list[dict],
    bng_cpp: Path,
    architecture_report: Path | None,
    refactor_comparison: Path | None,
    honesty_report: Path | None,
) -> dict:
    """Build a queue-ready receipt. Every live check is evidence-gated."""
    from tests.validation import atomizer_characterization as ac

    by_id = {r["id"]: r for r in rows}
    expected = set(ac.check_ids())
    if set(by_id) != expected or any(r["status"] != "PASS" for r in rows):
        raise SystemExit(
            "characterization did not execute every named check successfully"
        )

    comparison = None
    comparison_problems: list[str] = []
    if refactor_comparison is not None and refactor_comparison.is_file():
        try:
            comparison = json.loads(refactor_comparison.read_text(encoding="utf-8"))
            ok, comparison_problems = _valid_comparison(comparison, head)
            if not ok:
                comparison = None
        except (OSError, json.JSONDecodeError) as exc:
            comparison_problems.append(f"unreadable comparison: {exc}")
    else:
        comparison_problems.append("no before/after comparison artifact supplied")

    architecture_ok = _junit_passed(architecture_report, ARCHITECTURE_TESTS)
    honesty_ok = _junit_passed(honesty_report, HONESTY_TESTS)

    results = [dict(row) for row in rows]
    for identity in LIVE_CHECKS:
        if identity == "release-atomizer-modules":
            supported = architecture_ok
        elif identity == "release-atomizer-refactor":
            supported = comparison is not None
        else:
            supported = architecture_ok and comparison is not None and honesty_ok
        results.append(
            {
                "id": identity,
                "status": "PASS" if supported else "NOT_TESTED",
                "check": identity,
                "related_issues": [164],
                "evidence_kind": "supported-execution" if supported else "not-tested",
                "supported_execution": bool(supported),
                "stage": "atomizer-characterization",
                "detail": (
                    "Real exact-revision evidence validated for this check."
                    if supported
                    else NOT_TESTED_DETAIL[identity]
                ),
                "selector": SELECTOR,
            }
        )

    boundary_supported = comparison is not None and honesty_ok
    results.append(
        {
            "id": BOUNDARY_CHECK,
            "status": "PASS" if boundary_supported else "NOT_TESTED",
            "check": BOUNDARY_CHECK,
            "related_issues": [164],
            "evidence_kind": (
                "supported-execution" if boundary_supported else "not-tested"
            ),
            "supported_execution": bool(boundary_supported),
            "stage": "atomizer-characterization",
            "detail": (
                "Seam owner characterized and the affected qualified checks "
                "compared before/after."
                if boundary_supported
                else NOT_TESTED_DETAIL[BOUNDARY_CHECK]
            ),
        }
    )

    results.append(
        {
            "id": "release-closure-record-164",
            "status": "PASS",
            "check": "release-closure-record-164",
            "related_issues": [164],
            "evidence_kind": "disposition",
            "supported_execution": False,
            "stage": "atomizer-characterization",
            "detail": (
                f"Exact-revision characterization evidence recorded. "
                f"Evidence gaps: {comparison_problems}; "
                f"architecture_report_pass={architecture_ok}; honesty_report_pass={honesty_ok}."
            ),
        }
    )

    references: dict = {}
    if comparison is not None:
        references["refactor_comparison_sha256"] = _sha256(refactor_comparison)
        references["ssts"] = comparison["references"]["ssts"]
        references["biomodels"] = comparison["references"]["biomodels"]
    if architecture_report is not None and architecture_report.is_file():
        references["architecture_report_sha256"] = _sha256(architecture_report)
    if honesty_report is not None and honesty_report.is_file():
        references["honesty_report_sha256"] = _sha256(honesty_report)

    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-164",
        "case": "issue-164/atomizer-characterization",
        "source": {"revision": head, "dirty": dirty},
        "subject": {
            "binary": str(bng_cpp),
            "sha256": hashlib.sha256(bng_cpp.read_bytes()).hexdigest(),
        },
        "references": references,
        "evidence_gaps": comparison_problems,
        "results": results,
        "selector": SELECTOR,
        "receipt_producer": PRODUCER,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, default=ROOT / "build/cpp/bng_cpp")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow receipt generation in a dirty checkout (the receipt still records dirty=true)",
    )
    parser.add_argument(
        "--architecture-report",
        type=Path,
        help="JUnit from tests/validation/test_atomizer_module_ownership.py",
    )
    parser.add_argument(
        "--refactor-comparison",
        type=Path,
        help="JSON from scripts/ci/compare_atomizer_refactor_reports.py",
    )
    parser.add_argument(
        "--honesty-report",
        type=Path,
        help="JUnit from tests/validation/test_issue164_recorder_honesty.py",
    )
    args = parser.parse_args(argv)

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if head != args.source_revision:
        raise SystemExit(f"requested source revision does not match checkout: {head}")
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    )
    if dirty and not args.allow_dirty:
        raise SystemExit("Issue 164 receipt requires a clean checkout")

    from tests.validation import atomizer_characterization as ac

    with tempfile.TemporaryDirectory() as work_dir:
        rows = ac.run_worker(work_dir, bng_cpp=str(args.bng_cpp))

    receipt = build_receipt(
        head=head,
        dirty=dirty,
        rows=rows,
        bng_cpp=args.bng_cpp,
        architecture_report=args.architecture_report,
        refactor_comparison=args.refactor_comparison,
        honesty_report=args.honesty_report,
    )
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {args.output} with {len(receipt['results'])} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
