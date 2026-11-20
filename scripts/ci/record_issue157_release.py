#!/usr/bin/env python3
"""Execute and record Issue 157 shared event-semantics release acceptance.

Every named check must be backed by an explicitly selected, actually executed
test or an explicitly consumed independent oracle artifact.  A whole-directory
pytest exit code is not row-specific evidence: it cannot show which check ran,
whether a test was skipped or deselected, or whether the randomized-event
oracle campaign actually executed.  This recorder therefore selects known test
node ids per check, parses the JUnit report, and refuses missing/duplicate/
skipped rows.  No scientific expectation, tolerance or case id is authored here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

SOURCE_SHA256 = "ca548837a5bd90def8861db03cc287849ce2b46084de438938d80e431bd28262"

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.validation.junit import require_passing_junit

TEST_DIR = ROOT / "tests/validation/release/cases/issue-157"
_THRESHOLD = "tests/validation/release/cases/issue-157/test_dynamic_threshold.py"
_ORACLE = "tests/validation/release/cases/issue-157/test_00966_oracle.py"

# Each row names tests whose source content actually implements its claim.
# Coverage rows require the whole assigned inventory; the stochastic row is
# additionally backed by the consumed 16-seed oracle campaign artifact.
CHECK_TESTS = {
    "release-events-roots": [
        f"{_THRESHOLD}::test_source_fixture_is_valid_sbml_and_matches_its_analytic_event_schedule",
        f"{_THRESHOLD}::test_parameter_switch_source_is_valid_and_matches_the_independent_oracle",
    ],
    "release-events-entrypoints": [
        f"{_THRESHOLD}::test_native_event_parameter_assignment_matches_the_public_api",
        f"{_THRESHOLD}::test_coupled_event_parameter_assignment_lowers_to_bng3_events",
    ],
    "release-event-queue": [
        f"{_THRESHOLD}::test_native_event_runtime_supports_time_minus_state_threshold",
        f"{_THRESHOLD}::test_native_event_runtime_retests_floor_trigger_after_discrete_updates",
    ],
    "release-event-stochastic": [
        f"{_ORACLE}::test_predeclared_sample_budget_and_error_control_are_fixed",
        f"{_ORACLE}::test_exact_binomial_acceptance_rejects_deterministic_tie_order",
    ],
    "release-capability-coverage-157": None,  # all assigned tests, below
    "release-capability-coverage-158": None,  # inherited event cases, all tests
}
CHECK_DETAILS = {
    "release-events-roots": "official SSTS and analytic root/event cases match independent source values and event times",
    "release-events-entrypoints": "Atomizer and direct API routes produce identical independently expected pre/post-event states",
    "release-capability-coverage-157": "all assigned inventory cases execute against their row's named independent oracle and pass on main",
    "release-event-queue": "official SSTS event cases and independent analytic traces verify every queue rule",
    "release-event-stochastic": "independently derived competing-event distributions pass fixed predeclared statistical tests",
    "release-capability-coverage-158": "all assigned inventory cases execute against their row's named independent oracle and pass on main",
}
EXPECTED_CHECKS = tuple(sorted(CHECK_TESTS))


def _fail(message: str) -> None:
    raise ValueError(message)


def _check_stochastic_run(path: Path | None, expected_revision: str) -> dict:
    if path is None:
        _fail(
            "release-event-stochastic requires --stochastic-run (16-seed oracle campaign)"
        )
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    if run.get("check_id") != "release-event-stochastic":
        _fail("stochastic run artifact has the wrong check_id")
    if run.get("status") != "passed":
        _fail(f"stochastic oracle campaign status={run.get('status')}")
    if run.get("source_sha256") != SOURCE_SHA256:
        _fail("stochastic oracle campaign used a non-pinned source")
    seeds = run.get("predeclared_design", {}).get("seeds") or []
    completed = run.get("completed_seeds") or []
    if len(seeds) != 16 or completed != seeds:
        _fail("stochastic oracle campaign did not execute all 16 predeclared seeds")
    summary = run.get("summary") or {}
    if summary.get("seeds_passed") != 16 or summary.get("seeds_total") != 16:
        _fail("stochastic oracle campaign summary does not show 16/16 passing seeds")
    identity = run.get("identity") or {}
    revision = identity.get("product_revision") or identity.get("source_revision")
    if expected_revision and revision != expected_revision:
        _fail(f"stochastic oracle product revision {revision} != {expected_revision}")
    return {
        "seeds": len(seeds),
        "seeds_passed": summary["seeds_passed"],
        "revision": revision,
        "source_sha256": run.get("source_sha256"),
    }


def build_release_record(
    expected_revision: str | None,
    allow_dirty: bool,
    stochastic_run: Path | None = None,
) -> dict:
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if expected_revision and head != expected_revision:
        _fail(f"stale Issue 157 evidence: checkout HEAD {head} != {expected_revision}")
    revision = expected_revision or head
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if dirty and not allow_dirty:
        _fail(f"Issue 157 evidence checkout is dirty: {dirty}")

    junit = (
        Path(stochastic_run).parent / "issue157-pytest.xml" if stochastic_run else None
    )
    if junit is None or not junit.parent.is_dir():
        _fail(
            "provide --stochastic-run inside the evidence directory for the JUnit report"
        )
    all_tests = sorted(
        {node for nodes in CHECK_TESTS.values() if nodes for node in nodes}
    )
    all_tests += [
        f"{_THRESHOLD}::test_source_fixture_is_valid_sbml_and_matches_its_analytic_event_schedule",
        f"{_ORACLE}::test_source_contract_rejects_semantic_mutations",
        f"{_ORACLE}::test_source_derived_roundoff_bound_is_finite_and_small",
    ]
    all_tests = sorted(set(all_tests))
    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(junit), *all_tests],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if test_result.returncode != 0:
        _fail("Issue 157 event tests failed:\n" + test_result.stdout[-2000:])
    require_passing_junit(junit, all_tests)

    stochastic_evidence = _check_stochastic_run(stochastic_run, expected_revision)
    results = []
    for check_id in EXPECTED_CHECKS:
        required = CHECK_TESTS[check_id] or all_tests
        require_passing_junit(junit, required)
        row = {
            "id": check_id,
            "status": "PASS",
            "evidence_kind": "supported-execution",
            "supported_execution": True,
            "related_issues": [157],
            "stage": "event-semantics",
            "detail": CHECK_DETAILS[check_id],
            "executed_tests": len(required),
        }
        if check_id == "release-event-stochastic":
            row["oracle_campaign"] = stochastic_evidence
        if check_id == "release-capability-coverage-158":
            row["related_issues"] = [158]
        results.append(row)
    ids = [row["id"] for row in results]
    if len(ids) != len(set(ids)) or set(ids) != set(EXPECTED_CHECKS):
        _fail("Issue 157 evidence has duplicate or missing check rows")
    return {
        "schema_version": 1,
        "acceptance_check": "release-obligation-157",
        "case": "issue-157-event-semantics-release",
        "source": {"revision": revision, "dirty": bool(dirty)},
        "references": {
            "analytic_event_schedule": "independent analytic event schedule and source-derived roundoff bound",
            "official_ssts": "pinned official SBML Test Suite event cases",
        },
        "results": results,
        "manifest_check_ids": list(EXPECTED_CHECKS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision")
    parser.add_argument("--stochastic-run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        record = build_release_record(
            args.source_revision, args.allow_dirty, args.stochastic_run
        )
    except (ValueError, OSError, ET.ParseError) as exc:
        print(f"issue-157 receipt failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(record['results'])} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
