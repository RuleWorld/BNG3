#!/usr/bin/env python3
"""Bounded stable propensity/counting correspondence bridge (#167-adjacent).

Compares Lean formal counting/interpretation contract outputs to an independent
reference computation for the same explicit finite artifacts.

Assumptions/scope (exact):
- Supported cases are the named fixtures in PropensityCountingBridge.lean:
  bimolecular per-match counting, TotalRate interpretation flag, unimolecular
  bound-site matching in a symmetric dimer, MatchOnce dedup by ordered complex
  key (min molecule id in the connected complex of the first mapped molecule),
  and MatchOnce across distinct complexes.
- The independent oracle re-derives expected multiplicity/enabled/perMatch
  values from the stated mixture/rule semantics without invoking Lean internals.
- This is a bounded semantic correspondence/consistency check for stable
  counting semantics; it does not claim stochastic trajectory equivalence and
  does not follow NFnext-moving behavior.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run_lean(formal_dir: Path) -> dict[str, dict[str, str]]:
    proc = subprocess.run(
        ["lake", "env", "lean", "--run", "PropensityCountingBridge.lean"],
        cwd=formal_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"lean propensity bridge failed ({proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    rows = {}
    for line in proc.stdout.strip().splitlines():
        parts = dict(item.split("=", 1) for item in line.split("\t"))
        rows[parts["case"]] = parts
    return rows


# Independent reference expectations derived from explicit fixture semantics:
# - mixAB = {A0(x~u), A1(x~u), B2(y)} all separate; rule A(x~u)+B(y) matches
#   ordered non-overlapping distinct-complex pairs (A0,B2),(A1,B2) => 2.
#   TotalRate changes interpretation (total channel) not match count.
# - mixDimer = A0(x~u!1).A1(x~u!1); unimolecular A(x~u!+) matches A0 and A1 in
#   same complex => 2 matches; MatchOnce dedup by ordered complex key
#   (min id in connected component of first/only mapped molecule) collapses to 1.
# - mixTwoDimers = two separate dimers; 4 bound A(x~u) molecules in 2 complexes
#   => 4 raw matches, MatchOnce keeps one per complex => 2.
EXPECTED = {
    "bimol_twoA_oneB": {"multiplicity": "2", "enabled": "true", "perMatch": "true"},
    "bimol_twoA_oneB_totalRate": {
        "multiplicity": "2",
        "enabled": "true",
        "perMatch": "false",
    },
    "unimol_bound_in_dimer": {
        "multiplicity": "2",
        "enabled": "true",
        "perMatch": "true",
    },
    "unimol_bound_in_dimer_matchOnce": {
        "multiplicity": "1",
        "enabled": "true",
        "perMatch": "true",
    },
    "unimol_bound_in_two_dimers_matchOnce": {
        "multiplicity": "2",
        "enabled": "true",
        "perMatch": "true",
    },
}

# Negative/consistency mutations: altered assumptions must not match.
NEGATIVE = [
    (
        "matchOnce_must_not_keep_per_molecule_in_single_complex",
        "unimol_bound_in_dimer_matchOnce",
        {"multiplicity": "2", "enabled": "true", "perMatch": "true"},
    ),
    (
        "totalRate_must_not_be_per_match",
        "bimol_twoA_oneB_totalRate",
        {"multiplicity": "2", "enabled": "true", "perMatch": "true"},
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formal-dir", default=str(ROOT / "formal/lean"))
    args = ap.parse_args()

    lean = run_lean(Path(args.formal_dir))
    failures = []
    for name, exp in EXPECTED.items():
        got = lean.get(name)
        if got is None:
            failures.append(f"{name}: missing from Lean output")
            continue
        g = {
            "multiplicity": got.get("multiplicity"),
            "enabled": got.get("enabled"),
            "perMatch": got.get("perMatch"),
        }
        print(f"[{name}] lean={g} expected={exp}")
        if g != exp:
            failures.append(f"{name}: lean {g} != expected {exp}")

    for label, name, bad in NEGATIVE:
        got = lean.get(name)
        if got is None:
            failures.append(f"negative {label}: missing case {name}")
            continue
        g = {
            "multiplicity": got.get("multiplicity"),
            "enabled": got.get("enabled"),
            "perMatch": got.get("perMatch"),
        }
        print(f"[negative:{label}] got={g} must_not_equal={bad}")
        if g == bad:
            failures.append(
                f"negative {label}: Lean output incorrectly matched forbidden value {bad}"
            )

    if failures:
        print("\nBRIDGE FAILURES:")
        for f in failures:
            print(f"- {f}")
        return 1
    print("\nPROPENSITY COUNTING BRIDGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
