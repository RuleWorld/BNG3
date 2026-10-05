#!/usr/bin/env python3
"""Isolated ODE right-hand-side benchmark for the ode_many_functions fixture.

The harness `ode` component times three models together; this script isolates
bench/fixtures/ode_many_functions.bngl (150 zero-argument rate functions,
5000 output steps -- the F x output-steps regime) so a per-RHS change can be
measured directly against an untouched tree.

Modes
-----
paired (default): for each round, run one fresh child interpreter per tree in
    alternating order, timing only simulate_ode; report median/min/cv per arm
    plus the final-state digest (arms must agree bit-for-bit).

hold: run `--iters` in-process repetitions in one long-lived child and print
    the child pid, so an external sampler (sample(1)/xctrace) can attach while
    it runs; per-iteration timings are printed at the end.

Usage
-----
  python3 bench/ode_rhs_bench.py --tree /path/to/tree --tree /path/to/other \
      --reps 7 --json out.json
  python3 bench/ode_rhs_bench.py --tree . --hold 40
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

FIXTURE = "bench/fixtures/ode_many_functions.bngl"
T_END = 100.0
N_STEPS = 5000

CHILD_CODE = """\
import json, os, sys, time
root = sys.argv[1]
iters = int(sys.argv[2])
fixture = sys.argv[3]
t_end = float(sys.argv[4])
n_steps = int(sys.argv[5])
hold = sys.argv[6] == "1"
sys.path.insert(0, root + "/build/cpp")
sys.path.insert(0, root + "/python")
sys.meta_path[:] = [
    f for f in sys.meta_path
    if not type(f).__module__.startswith("_editable")
]
if hold:
    print(os.getpid(), flush=True)
import _bionetgen_cpp as cpp
mod_path = os.path.abspath(cpp.__file__ or "")
if mod_path and not mod_path.startswith(os.path.abspath(root)):
    raise SystemExit("extension outside tree: " + mod_path)
times = []
digest = None
for _ in range(iters):
    model = cpp.parse_file(fixture)
    network = cpp.generate_network(model)
    t0 = time.perf_counter()
    res = cpp.simulate_ode(model, network, t_end=t_end, n_steps=n_steps)
    times.append(time.perf_counter() - t0)
    conc = res.get("concentrations")
    if conc is None:
        raise SystemExit("simulate_ode returned no concentrations")
    digest = [float(x) for x in conc[-1]]
print(json.dumps({"times": times, "digest": digest}))
"""


def spawn_child(tree: Path, iters: int, hold: bool) -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            CHILD_CODE,
            str(tree),
            str(iters),
            str(Path(tree) / FIXTURE),
            repr(T_END),
            str(N_STEPS),
            "1" if hold else "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if hold:
        pid_line = proc.stdout.readline().strip()
        if not pid_line.isdigit():
            err = proc.stderr.read()
            raise SystemExit(f"hold child failed to start: {pid_line} {err}")
        print(f"hold child pid={pid_line}", flush=True)
    return proc


def finish_child(proc: subprocess.Popen) -> dict:
    out, err = proc.communicate(timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"child exited {proc.returncode}: {err.strip()}")
    return json.loads(out)


def load1() -> float:
    return os.getloadavg()[0]


def run_paired(trees: list[Path], reps: int, json_out: Path | None) -> int:
    if len(trees) < 2:
        raise SystemExit("paired mode needs at least two --tree arms")
    per_arm: dict[str, list[float]] = {str(t): [] for t in trees}
    digests: dict[str, str] = {}
    start_load = load1()
    for rep in range(reps):
        order = trees if rep % 2 == 0 else list(reversed(trees))
        for tree in order:
            res = finish_child(spawn_child(tree, iters=1, hold=False))
            per_arm[str(tree)].append(res["times"][0])
            digests[str(tree)] = json.dumps(res["digest"])
    end_load = load1()

    print(f"load1 start={start_load:.1f} end={end_load:.1f}")
    ok = True
    for tree, times in per_arm.items():
        med = statistics.median(times)
        mn = min(times)
        avg = statistics.mean(times)
        cv = statistics.pstdev(times) / avg if avg else 0.0
        print(
            f"{tree}: median {med * 1e3:.3f} ms  min {mn * 1e3:.3f} ms  "
            f"cv {cv * 100:.1f}%  reps={[round(t * 1e3, 2) for t in times]}"
        )
    unique = set(digests.values())
    if len(unique) == 1:
        print(f"digests identical across arms: {next(iter(unique))[:120]}...")
    else:
        ok = False
        print("DIGEST MISMATCH across arms:")
        for tree, d in digests.items():
            print(f"  {tree}: {d}")

    # Paired ratios: same-round pairing regardless of execution order.
    ratios = []
    a, b = trees[0], trees[1]
    for i in range(reps):
        ratios.append(per_arm[str(a)][i] / per_arm[str(b)][i])
    print(
        f"paired A/B ratio (arm0/arm1): median {statistics.median(ratios):.4f} "
        f"min {min(ratios):.4f} max {max(ratios):.4f}"
    )

    if json_out:
        payload = {
            "meta": {
                "load1_start": start_load,
                "load1_end": end_load,
                "reps": reps,
                "fixture": FIXTURE,
                "t_end": T_END,
                "n_steps": N_STEPS,
            },
            "arms": {
                t: {"times_s": v, "median_s": statistics.median(v), "min_s": min(v)}
                for t, v in per_arm.items()
            },
            "digests": digests,
            "paired_ratios": ratios,
        }
        json_out.write_text(json.dumps(payload, indent=2))
        print(f"wrote {json_out}")
    return 0 if ok else 1


def run_hold(tree: Path, iters: int) -> int:
    proc = spawn_child(tree, iters=iters, hold=True)
    res = finish_child(proc)
    times = res["times"]
    print(
        f"{tree}: iters={len(times)} median {statistics.median(times) * 1e3:.3f} ms "
        f"min {min(times) * 1e3:.3f} ms max {max(times) * 1e3:.3f} ms"
    )
    print(f"digest={json.dumps(res['digest'])[:120]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--tree",
        action="append",
        type=Path,
        required=True,
        help="worktree root (repeatable; >=2 for paired mode)",
    )
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument(
        "--hold",
        type=int,
        default=0,
        help="run N in-process repetitions in one child (for sampling)",
    )
    args = ap.parse_args()
    trees = [t.resolve() for t in args.tree]
    if args.hold > 0:
        return run_hold(trees[0], args.hold)
    return run_paired(trees, args.reps, args.json)


if __name__ == "__main__":
    sys.exit(main())
