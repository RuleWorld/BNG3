#!/usr/bin/env python3
"""Large-model ODE (CVODE) lane benchmark for the round-2 perf swarm.

The composite harness's ``ode`` fixtures are N=2/2/1, so CVODE's large-network
path -- linear-solver choice, finite-difference Jacobian cost, step control at
356 species -- is never exercised by ``bench/run_bench.py``. This benchmark
runs ``simulate_ode`` (method=cvode) on

  * ``models/performance_test_models/egfr_net.bngl`` (356 species, 3749
    generated reactions) long enough for the baseline to cost >= 2 s, and
  * ``models/isomerization.bngl`` as a small sanity case.

Each sample runs in a fresh child interpreter bound to one worktree (same
bootstrap as bench/run_bench.py), so peak RSS is per-sample. Reported per
case: simulate wall time, network-generation wall time (untimed by the
simulator but recorded), peak RSS, and a digest of the final concentration
vector. When the C++ extension emits its optional CVODE profile line (set
``BNG3_CVODE_STATS=1`` in the environment; one ``BNG3_CVODE_STATS {...}``
stderr line from OdeIntegrator::integrateCvode), the counters are captured
too: steps, RHS evals, Jacobian evals, linear setups, nonlinear iterations.

Single tree::

    PYTHONPATH= python3 bench/ode_large_bench.py --reps 5 --json out.json

Paired interleaved A/B of two worktrees (this is the form that counts on this
~11%-drifting host; the order of the two arms swaps every round)::

    PYTHONPATH= python3 bench/ode_large_bench.py \
        --a /path/to/base/tree --b /path/to/candidate \
        --expect-a 29f2c03e --expect-b <HEAD> --rounds 4

Correctness gates (exit non-zero):
  * within one tree, every rep of a case must be bit-identical;
  * across trees, the max relative deviation of the final concentration
    vector per case must be <= 1e-6 (denominator floor 1e-12, i.e. at or
    below the solver's absolute tolerance), unless --allow-deviation raises
    it deliberately for a documented intentional numerics change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Same pre-import bootstrap as bench/run_bench.py: worktree-local sys.path
# first, then drop scikit-build editable MetaPathFinders.
BOOTSTRAP = """\
import sys
ROOT = sys.argv[1]
sys.path.insert(0, ROOT + "/build/cpp")
sys.path.insert(0, ROOT + "/python")
sys.meta_path[:] = [
    f for f in sys.meta_path
    if not type(f).__module__.startswith("_editable")
]
"""

# (case name, model path, t_end, n_steps). The large case repeats the same
# integration within one sample so the timed span is >= 2 s at the untouched
# baseline (a single egfr integration is ~0.45 s); repeats are summed into
# sim_s. t_end=500 covers the model's transient and is integrated in 1000
# output steps. The sanity case mirrors the composite harness's isomerization
# ode fixture.
CASES = [
    ("egfr_large", "models/performance_test_models/egfr_net.bngl", 500.0, 1000),
    ("sanity_iso", "models/isomerization.bngl", 100.0, 1000),
]
REPEAT = {"egfr_large": 5, "sanity_iso": 1}

DEV_FLOOR = 1e-12  # denominator floor for the max-relative-deviation metric

_CHILD_CODE = """\
import json, resource, time
import _bionetgen_cpp as cpp
CASES = %s
REPEAT = %s
out = {"cases": {}}
for name, path, t_end, steps in CASES:
    model = cpp.parse_file(path)
    network = cpp.generate_network(model)
    sim_s = 0.0
    res = None
    for _ in range(REPEAT[name]):
        t0 = time.perf_counter()
        res = cpp.simulate_ode(model, network, t_end=t_end, n_steps=steps)
        sim_s += time.perf_counter() - t0
    conc = res.get("concentrations")
    if conc is None:
        raise SystemExit("simulate_ode returned no concentrations for " + path)
    final = [float(x) for x in conc[-1]]
    out["cases"][name] = {
        "sim_s": sim_s,
        "n_species": len(final),
        "final": final,
    }
out["peak_rss"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
print(json.dumps(out))
""" % (json.dumps(CASES), json.dumps(REPEAT))

_STATS_PREFIX = "BNG3_CVODE_STATS "


def _extract_stats(stderr: str) -> dict | None:
    for line in stderr.splitlines():
        if line.startswith(_STATS_PREFIX):
            try:
                return json.loads(line[len(_STATS_PREFIX):])
            except json.JSONDecodeError:
                return None
    return None


def run_child(tree: Path, *, timeout: float) -> dict:
    """Run one fresh interpreter bound to `tree`; parse its JSON result."""
    env = dict(os.environ)
    env["BNG3_CVODE_STATS"] = "1"  # ask the extension for its CVODE counters
    proc = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP + _CHILD_CODE, str(tree)],
        cwd=str(tree),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"child failed in {tree} (exit {proc.returncode}):\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f"child in {tree} produced no output\n{proc.stderr[-2000:]}")
    result = json.loads(lines[-1])
    result["cvode_stats"] = _extract_stats(proc.stderr)
    return result


def final_digest(final: list[float]) -> str:
    return hashlib.sha256(struct.pack(f"<{len(final)}d", *final)).hexdigest()


def max_rel_dev(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return float("inf")
    worst = 0.0
    for x, y in zip(a, b):
        den = max(abs(x), abs(y), DEV_FLOOR)
        dev = abs(x - y) / den
        if dev > worst:
            worst = dev
    return worst


def check_tree_shape(tree: Path) -> None:
    # The bench script itself may live in this lane's worktree while an arm
    # points at the untouched base tree; an arm only needs its own Python
    # package and built extension.
    if not (tree / "python" / "bionetgen").is_dir():
        raise SystemExit(f"{tree} has no python/bionetgen package")
    if not any((tree / "build" / "cpp").glob("_bionetgen_cpp*.so")):
        raise SystemExit(f"{tree} has no built _bionetgen_cpp extension under build/cpp")


def git_head(tree: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=str(tree),
        capture_output=True, text=True,
    ).stdout.strip()


def sample_set(tree: Path, reps: int, timeout: float) -> dict:
    """`reps` fresh-child samples of every case, interleaved across cases."""
    samples: dict[str, list[dict]] = {name: [] for name, *_ in CASES}
    for _ in range(reps):
        for name, *_ in CASES:
            one = run_child(tree, timeout=timeout)
            samples[name].append(one["cases"][name])
            samples[name][-1]["peak_rss"] = one["peak_rss"]
            samples[name][-1]["cvode_stats"] = one["cvode_stats"]
    return samples


def summarize(samples: dict[str, list[dict]]) -> dict:
    out = {}
    for name, rows in samples.items():
        walls = [r["sim_s"] for r in rows]
        digests = {final_digest(r["final"]) for r in rows}
        stats = rows[-1]["cvode_stats"]
        out[name] = {
            "n_species": rows[0]["n_species"],
            "sim_median": statistics.median(walls),
            "sim_min": min(walls),
            "sim_all": walls,
            "peak_rss": statistics.median(r["peak_rss"] for r in rows),
            "final_digest": sorted(digests),
            "final": rows[-1]["final"],
            "cvode_stats": stats,
        }
        out[name]["stable"] = len(digests) == 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reps", type=int, default=5,
                    help="samples per case in single-tree mode (default 5)")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full result JSON here (single-tree mode)")
    ap.add_argument("--a", type=Path, default=None, help="baseline worktree root")
    ap.add_argument("--b", type=Path, default=None, help="candidate worktree root")
    ap.add_argument("--rounds", type=int, default=4, help="A/B rounds (default 4)")
    ap.add_argument("--reps-per-round", type=int, default=1,
                    help="samples per case per arm invocation in A/B mode")
    ap.add_argument("--expect-a", default=None,
                    help="fail unless arm A's git SHA starts with this prefix")
    ap.add_argument("--expect-b", default=None,
                    help="fail unless arm B's git SHA starts with this prefix")
    ap.add_argument("--max-deviation", type=float, default=1e-6,
                    help="cross-tree max relative deviation gate (default 1e-6)")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()

    load1_start = os.getloadavg()[0]
    print(f"ode_large_bench: load1={load1_start:.1f} at start "
          f"(quote as a band with any timing; interleave within one session)")

    if args.a or args.b:
        if not (args.a and args.b):
            raise SystemExit("--a and --b must be given together")
        for arm, tree, expect in (("A", args.a, args.expect_a),
                                  ("B", args.b, args.expect_b)):
            check_tree_shape(tree)
            if expect is not None:
                head = git_head(tree)
                if not head.startswith(expect):
                    raise SystemExit(
                        f"arm {arm} is at {head}, not the expected {expect} ({tree})"
                    )
        arms: dict[str, list[dict]] = {"A": [], "B": []}
        for rnd in range(1, args.rounds + 1):
            order = ("A", "B") if rnd % 2 else ("B", "A")
            for arm in order:
                tree = args.a if arm == "A" else args.b
                samples = sample_set(tree, args.reps_per_round, args.timeout)
                arms[arm].append(summarize(samples))
                print(f"  round {rnd}/{args.rounds} arm {arm} done", flush=True)

        failures = []
        for name, *_ in CASES:
            a_final = arms["A"][-1][name]["final"]
            b_final = arms["B"][-1][name]["final"]
            # across arms and rounds, every digest must match within tolerance
            devs = [
                max_rel_dev(arms[arm][r][name]["final"], a_final)
                for arm in ("A", "B")
                for r in range(len(arms[arm]))
            ]
            worst = max(devs)
            if worst > args.max_deviation:
                failures.append(f"{name}: max relative deviation {worst:.3e} "
                                f"> {args.max_deviation:g}")
            print(f"\n[{name}] n_species={arms['A'][-1][name]['n_species']} "
                  f"max rel dev vs A-final = {worst:.3e}")
            for arm in ("A", "B"):
                for r, summ in enumerate(arms[arm]):
                    s = summ[name]
                    print(f"  arm {arm} round {r + 1}: sim={s['sim_median']:.4f}s "
                          f"rss={s['peak_rss']} stats={s['cvode_stats']}")

        if any(not arms[arm][r][name]["stable"]
               for arm in ("A", "B") for r in range(len(arms[arm]))
               for name, *_ in CASES):
            failures.append("reps within an arm are not bit-identical")

        load1_end = os.getloadavg()[0]
        print(f"\nload1={load1_start:.1f} start / {load1_end:.1f} end "
              f"(~11% cross-session floor on this host; quote a band)")
        print(f"\n{'case':<14}{'A median':>11}{'B median':>11}{'B/A':>9}{'delta':>9}")
        for name, *_ in CASES:
            a = statistics.median(arms["A"][r][name]["sim_median"]
                                  for r in range(len(arms["A"])))
            b = statistics.median(arms["B"][r][name]["sim_median"]
                                  for r in range(len(arms["B"])))
            print(f"{name:<14}{a:>11.4f}{b:>11.4f}{b / a:>9.3f}"
                  f"{(b / a - 1) * 100:>+8.1f}%")
        if failures:
            print("\nCORRECTNESS FAILURE:", file=sys.stderr)
            for f in failures:
                print(f"  {f}", file=sys.stderr)
            return 1
        print("\nguards: within-arm bit-identical; cross-arm deviation within gate")
        return 0

    # Single-tree mode
    check_tree_shape(ROOT)
    samples = sample_set(ROOT, args.reps, args.timeout)
    summary = summarize(samples)
    load1_end = os.getloadavg()[0]
    report = {
        "meta": {
            "tree": str(ROOT),
            "head": git_head(ROOT),
            "load1_start": load1_start,
            "load1_end": load1_end,
            "cases": CASES,
            "reps": args.reps,
        },
        "cases": summary,
    }
    print(f"\nload1={load1_start:.1f} start / {load1_end:.1f} end")
    for name, s in summary.items():
        stats = s["cvode_stats"] or {}
        print(f"[{name}] n_species={s['n_species']} "
              f"sim median={s['sim_median']:.4f}s min={s['sim_min']:.4f}s "
              f"rss={s['peak_rss']}B stable={s['stable']}")
        if stats:
            print(f"    cvode: {stats}")
    if not all(s["stable"] for s in summary.values()):
        print("REPS NOT BIT-IDENTICAL", file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
