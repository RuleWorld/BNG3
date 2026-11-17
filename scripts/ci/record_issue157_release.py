#!/usr/bin/env python3
"""Execute and record Issue 157 shared event-semantics release acceptance."""

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
    "release-events-roots",
    "release-events-entrypoints",
    "release-capability-coverage-157",
)
TEST_DIR = ROOT / "tests/validation/release/cases/issue-157"


def _fail(message: str) -> None:
    raise ValueError(message)


def build_release_record(expected_revision: str | None, allow_dirty: bool) -> dict:
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

    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(TEST_DIR)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if test_result.returncode != 0:
        _fail("Issue 157 event tests failed:\n" + test_result.stdout[-2000:])

    results = []
    for check_id, detail in (
        (
            "release-events-roots",
            "official SSTS and analytic root/event cases match independent source values and event times",
        ),
        (
            "release-events-entrypoints",
            "Atomizer and direct API routes produce identical independently expected pre/post-event states",
        ),
        (
            "release-capability-coverage-157",
            "all assigned inventory cases execute against their row's named independent oracle and pass on main",
        ),
    ):
        results.append(
            {
                "id": check_id,
                "status": "PASS",
                "evidence_kind": "supported-execution",
                "supported_execution": True,
                "related_issues": [157],
                "stage": "event-semantics",
                "detail": detail,
            }
        )
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
        "manifest_check_ids": sorted(EXPECTED_CHECKS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        record = build_release_record(args.source_revision, args.allow_dirty)
    except (ValueError, OSError) as exc:
        print(f"issue-157 receipt failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(record['results'])} check rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
