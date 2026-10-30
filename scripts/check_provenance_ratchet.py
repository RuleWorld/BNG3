#!/usr/bin/env python3
"""Fail when the strict provenance gate's current error set drifts from its ratchet.

The checker runs ``validate_provenance.py --require-approved`` and compares
its complete error set to ``provenance/strict-gate-ratchet.json``. Both a new
blocker and a stale recorded blocker fail. An empty ratchet is valid only when
the strict gate passes; it therefore detects later unaccepted pins or hashes.
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

    # The validator's return code 2 means it could not parse or run the gate.
    # Surface that error instead of treating it as a blocker-set comparison.
    if returncode not in (0, 1):
        print(raw, file=sys.stderr, end="")
        print(
            f"ERROR: strict provenance gate exited {returncode}; it did not report "
            "a normal blocker set",
            file=sys.stderr,
        )
        return 2
    if returncode == 1 and not actual:
        print(raw, file=sys.stderr, end="")
        print(
            "ERROR: strict provenance gate failed without reporting a blocker",
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
            "\nReconcile the blocker set against the accepted source lock and "
            "recorded maintainer decision. Do not change locked pins or hashes "
            "to make this check pass.",
            file=sys.stderr,
        )
        return 1

    if returncode == 0:
        print(
            "provenance ratchet holds: strict gate passes with "
            f"{len(actual_set)} blocker(s) recorded in {args.ratchet.relative_to(REPO) if args.ratchet.is_relative_to(REPO) else args.ratchet}."
        )
    else:
        print(
            f"provenance ratchet holds: {len(actual_set)} known strict-gate "
            "blocker(s), unchanged."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
