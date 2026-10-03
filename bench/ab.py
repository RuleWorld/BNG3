#!/usr/bin/env python3
"""Interleaved A/B of two worktrees through bench/run_bench.py.

The fitness harness scores one worktree at a time, and this host drifts ~11%
between sessions, so a candidate measured in its own session cannot be called a
win from the composite alone. This runs both arms alternately inside one
session and reports paired per-round deltas.

    python3 bench/ab.py --a /path/treeA --b /path/treeB --rounds 4

Both trees must already be built (build/cpp/bng_cpp and the _bionetgen_cpp
extension); run_bench.py fails closed otherwise. The order of the two arms
swaps every round so a monotone drift cannot favour one side, and the
determinism guards (.net sha, SSA event counts, ODE digests, .cdat/.gdat shas)
must agree between the arms -- a guard mismatch is a correctness failure, not a
timing result, and exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WEIGHTS = {
    "netgen": 0.27,
    "ssa_batch": 0.33,
    "ode": 0.15,
    "out_write": 0.10,
    "py_import": 0.08,
    "py_load": 0.07,
}

# Below this the delta is inside the host's measured cross-session drift and is
# not a claim. bench/README.md: ~11% composite drift across sessions.
RESOLUTION_FLOOR = 0.11


def run_arm(tree: Path, reps: int) -> dict:
    """One run_bench.py invocation in `tree`; returns its parsed --json result."""
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        proc = subprocess.run(
            [sys.executable, str(tree / "bench" / "run_bench.py"),
             "--reps", str(reps), "--json", tmp.name],
            cwd=str(tree), capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"run_bench.py failed in {tree} (exit {proc.returncode}):\n"
                f"{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
            )
        return json.loads(Path(tmp.name).read_text())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", type=Path, required=True, help="baseline worktree root")
    ap.add_argument("--b", type=Path, required=True, help="candidate worktree root")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--reps", type=int, default=2,
                    help="reps per run_bench.py invocation (>= 2)")
    args = ap.parse_args()

    for tree in (args.a, args.b):
        if not (tree / "bench" / "run_bench.py").is_file():
            raise SystemExit(f"{tree} is not a BNG3 worktree with bench/run_bench.py")

    print(f"load1={os.getloadavg()[0]:.1f} at start "
          f"(quote with any timing; also check `ps -axo pid,etime,command`)")

    arms: dict[str, list[dict]] = {"A": [], "B": []}
    for rnd in range(1, args.rounds + 1):
        order = ("A", "B") if rnd % 2 else ("B", "A")
        for arm in order:
            tree = args.a if arm == "A" else args.b
            arms[arm].append(run_arm(tree, args.reps))
            print(f"  round {rnd}/{args.rounds} arm {arm} done", flush=True)

    guards_a = arms["A"][0]["guards"]
    guards_b = arms["B"][0]["guards"]
    if guards_a != guards_b:
        print("GUARD MISMATCH -- correctness failure, not a timing result:",
              file=sys.stderr)
        for key in sorted(set(guards_a) | set(guards_b)):
            if guards_a.get(key) != guards_b.get(key):
                print(f"  {key}:\n    A={guards_a.get(key)}\n    B={guards_b.get(key)}",
                      file=sys.stderr)
        return 1
    if any(arms[a][i]["guards"] != arms[a][0]["guards"] for a in arms
           for i in range(len(arms[a]))):
        print("GUARD UNSTABLE WITHIN AN ARM -- nondeterminism", file=sys.stderr)
        return 1

    def med(arm: str, comp: str) -> float:
        return statistics.median(r["components"][comp]["median"] for r in arms[arm])

    def comp_med(arm: str) -> float:
        return statistics.median(
            sum(WEIGHTS[n] * r["components"][n]["median"] for n in WEIGHTS)
            for r in arms[arm]
        )

    a_c, b_c = comp_med("A"), comp_med("B")
    print("\nguards: identical across A and B, stable within each arm")
    print(f"\n{'component':<12}{'A median':>11}{'B median':>11}{'B/A':>9}{'weight':>9}")
    for name in WEIGHTS:
        a, b = med("A", name), med("B", name)
        print(f"{name:<12}{a:>11.4f}{b:>11.4f}{(b / a if a else float('nan')):>9.3f}"
              f"{WEIGHTS[name]:>9.2f}")
    print(f"\nCOMPOSITE  A={a_c:.4f}  B={b_c:.4f}  "
          f"B/A={b_c / a_c:.4f}  ({(b_c / a_c - 1) * 100:+.1f}%)")
    delta = b_c / a_c - 1
    if abs(delta) < RESOLUTION_FLOOR:
        print(f"VERDICT: inside the {RESOLUTION_FLOOR * 100:.0f}% host resolution "
              f"floor -- not a win and not a regression; re-measure before claiming")
    else:
        print(f"VERDICT: {'B faster' if delta < 0 else 'B slower'} by "
              f"{abs(delta) * 100:.1f}% (outside the {RESOLUTION_FLOOR * 100:.0f}% floor)")
    print(f"\nA git={arms['A'][0]['meta']['git']} ({args.a})")
    print(f"B git={arms['B'][0]['meta']['git']} ({args.b})")
    print(f"measured {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())