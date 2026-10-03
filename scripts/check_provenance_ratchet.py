#!/usr/bin/env python3
"""Fail when the strict provenance gate's failure set drifts from the ratchet.

``scripts/validate_provenance.py --require-approved`` fails at every head to
date because no maintainer has approved the upstream baseline. That gate used
to run in no CI job at all, so it read as a passing gate to anyone who saw it
in the tree. This checker makes the failure set machine-checked instead:

* it runs the strict gate and compares the error set to
  ``provenance/strict-gate-ratchet.json``;
* it fails if the set *grows* (new unrecorded provenance debt) or *shrinks*
  (a decision was made, so the ratchet is now stale);
* it fails if the strict gate starts passing, because the ratchet exists only
  to describe that failure and would otherwise hide it.

The ratchet records unapproved status transitions, not unsupported claims. It
is not a waiver: no entry may be removed to make the gate green.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RATCHET = REPO / "provenance" / "strict-gate-ratchet.json"
VALIDATOR = REPO / "scripts" / "validate_provenance.py"
LOCK = REPO / "provenance" / "upstreams.lock.yml"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def run_strict_gate(lock: Path) -> tuple[int, list[str], str]:
    """Run the strict gate and return (returncode, errors, raw stderr)."""
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--lock", str(lock), "--require-approved"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    errors = [
        line[len("ERROR: ") :]
        for line in proc.stderr.splitlines()
        if line.startswith("ERROR: ")
    ]
    return proc.returncode, errors, proc.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratchet", type=Path, default=DEFAULT_RATCHET)
    parser.add_argument("--lock", type=Path, default=LOCK)
    args = parser.parse_args()

    try:
        ratchet = load_json(args.ratchet)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not isinstance(ratchet, dict) or not isinstance(ratchet.get("errors"), list):
        print(
            f"ERROR: {args.ratchet} must be an object with an 'errors' array",
            file=sys.stderr,
        )
        return 2
    expected = ratchet["errors"]
    if not all(isinstance(item, str) for item in expected):
        print(
            f"ERROR: {args.ratchet}: every entry in 'errors' must be a string",
            file=sys.stderr,
        )
        return 2
    if len(set(expected)) != len(expected):
        print(f"ERROR: {args.ratchet}: 'errors' contains duplicates", file=sys.stderr)
        return 2

    returncode, actual, raw = run_strict_gate(args.lock)

    # The strict gate passing is itself drift: the ratchet exists to describe
    # this failure, so a green gate means the ratchet is hiding a real change.
    if returncode == 0:
        print(
            "ERROR: the strict provenance gate now passes, but "
            f"{args.ratchet} still records {len(expected)} blocker(s).\n"
            "The baseline was approved. Delete the ratchet and the CI step that "
            "runs this checker, and record the decision in "
            "provenance/upstreams.lock.yml in the same change.",
            file=sys.stderr,
        )
        return 1

    # A returncode of 2 means the gate could not run at all. Surface it raw
    # rather than reporting an empty error set as a ratchet mismatch.
    if returncode not in (0, 1):
        print(raw, file=sys.stderr, end="")
        print(
            f"ERROR: strict provenance gate exited {returncode}; it did not report "
            "a normal blocker set",
            file=sys.stderr,
        )
        return 2

    expected_set, actual_set = set(expected), set(actual)
    new = sorted(actual_set - expected_set)
    gone = sorted(expected_set - actual_set)

    if new:
        print(
            f"ERROR: {len(new)} strict-gate blocker(s) not recorded in {args.ratchet}:",
            file=sys.stderr,
        )
        for item in new:
            print(f"  + {item}", file=sys.stderr)
    if gone:
        print(
            f"ERROR: {len(gone)} recorded blocker(s) no longer raised by the strict "
            f"gate; {args.ratchet} is stale:",
            file=sys.stderr,
        )
        for item in gone:
            print(f"  - {item}", file=sys.stderr)

    if new or gone:
        print(
            "\nUpdate the ratchet in the same change that moves the baseline. "
            "Do not delete an entry to make this check pass.",
            file=sys.stderr,
        )
        return 1

    print(
        f"provenance ratchet holds: {len(actual_set)} known strict-gate blocker(s), "
        "unchanged. The strict gate still fails by design; see "
        f"{args.ratchet.relative_to(REPO) if args.ratchet.is_relative_to(REPO) else args.ratchet} "
        "for what each one is waiting on."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
