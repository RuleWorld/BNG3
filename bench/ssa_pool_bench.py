#!/usr/bin/env python3
"""Lane benchmark for the CPU batch SSA pool (SSA_BATCH in bench/run_bench.py).

Measures the exact harness configuration of the ssa_batch component —
isomerization 200k trajectories t=20 and gene_expr_simple 800k trajectories
t=500, n_steps=10, threads=0 (all cores), base_seed=12345 — in a fresh child
interpreter per run, timing only the simulate_batch_ssa_cpu call and reporting
both wall and child CPU (user+sys, all threads).

Diagnostic phases attribute the pool's cost (same seed derivation, same code
path, only the horizon/grid changes — these are diagnostics, not guards):

  full    harness configuration (guarded: event counts must match across
          every rep and both arms)
  setup   same batches, t_end=0, n_steps=10: no events fire, so this is the
          per-trajectory setup plus the 11-row observable recording
  rows    same batches, t_end=0, n_steps=1: 2 output rows, so full - setup
          isolates the event loop and setup - rows isolates the extra rows

Paired mode interleaves two build roots (A/B) in one session, alternating
which arm runs first each round, and fails closed on any event-count mismatch
between arms or reps.

Usage:
  PYTHONPATH= python3 bench/ssa_pool_bench.py                 # single tree, full phase
  PYTHONPATH= python3 bench/ssa_pool_bench.py --phase all --reps 3
  PYTHONPATH= python3 bench/ssa_pool_bench.py \
      --a /path/to/base --b /path/to/candidate --rounds 4 --phases full,setup,rows
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Exact SSA_BATCH / SSA_BASE_SEED of bench/run_bench.py.
SSA_BATCH = {
    "iso": ("models/isomerization.bngl", 20.0, 200_000),
    "ge": ("models/gene_expr_simple.bngl", 500.0, 800_000),
}
BASE_SEED = 12345

# Diagnostic phases: (t_end, n_steps) overrides per phase; None = harness value.
PHASES = {
    "full": None,  # (20/500, 10) — the guarded configuration
    "setup": (0.0, 10),  # no events, full output grid
    "rows": (0.0, 1),  # no events, minimal output grid
}

BOOTSTRAP = """\
import sys, resource, json, time
ROOT = sys.argv[1]
sys.path.insert(0, ROOT + "/build/cpp")
sys.path.insert(0, ROOT + "/python")
sys.meta_path[:] = [
    f for f in sys.meta_path
    if not type(f).__module__.startswith("_editable")
]
import _bionetgen_cpp as cpp
assert cpp.__file__.startswith(ROOT), "extension outside root: " + cpp.__file__

phase = sys.argv[2]
threads = int(sys.argv[3])
overrides = json.loads(sys.argv[4])
BATCH = json.loads('''%s''')
BASE_SEED = %d
out = {"phase": phase, "models": {}}
for key, (path, t_end, batch) in BATCH.items():
    t_end, n_steps = overrides.get(key, (t_end, 10))
    model = cpp.parse_file(path)
    network = cpp.generate_network(model)
    r0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.perf_counter()
    res = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=batch, t_end=t_end, n_steps=n_steps,
        threads=threads, base_seed=BASE_SEED,
    )
    wall = time.perf_counter() - t0
    r1 = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)
    out["models"][key] = {
        "wall": wall, "cpu": cpu, "events": res["total_events"],
    }
print(json.dumps(out))
""" % (json.dumps(SSA_BATCH), BASE_SEED)


def load1() -> float:
    return os.getloadavg()[0]


def run_child(root: Path, phase: str, threads: int) -> dict:
    override = PHASES[phase]
    overrides = (
        json.dumps({k: [override[0], override[1]] for k in SSA_BATCH})
        if override is not None
        else json.dumps({k: [SSA_BATCH[k][1], 10] for k in SSA_BATCH})
    )
    proc = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP, str(root), phase, str(threads), overrides],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise SystemExit(f"child failed (phase={phase}): {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def events_of(res: dict) -> dict:
    return {k: v["events"] for k, v in res["models"].items()}


def sum_field(res: dict, field: str) -> float:
    return sum(v[field] for v in res["models"].values())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--a", type=Path, help="build root of arm A")
    ap.add_argument("--b", type=Path, help="build root of arm B (enables paired mode)")
    ap.add_argument("--rounds", type=int, default=4, help="paired rounds (default 4)")
    ap.add_argument("--reps", type=int, default=3, help="reps per single-tree run")
    ap.add_argument(
        "--phases",
        default="full",
        help="comma list from full,setup,rows (default full)",
    )
    ap.add_argument(
        "--threads",
        type=int,
        default=0,
        help="pool size; 0 = all cores (harness value)",
    )
    args = ap.parse_args()

    phases = [p.strip() for p in args.phases.split(",") if p.strip()]
    for p in phases:
        if p not in PHASES:
            raise SystemExit(f"unknown phase {p!r}; choose from {sorted(PHASES)}")

    print(
        f"ssa_pool_bench load1={load1():.1f} threads={args.threads} "
        f"phases={phases} python={sys.version.split()[0]}"
    )

    # ---- paired mode: interleave two roots in one session ------------------
    if args.a and args.b:
        arms = {"A": args.a.resolve(), "B": args.b.resolve()}
        for name, root in arms.items():
            if not (root / "build/cpp").is_dir():
                raise SystemExit(f"arm {name}: no build/cpp under {root}")
        guard = None
        rows = []
        for rnd in range(args.rounds):
            order = ("A", "B") if rnd % 2 == 0 else ("B", "A")
            for arm in order:
                for phase in phases:
                    res = run_child(arms[arm], phase, args.threads)
                    ev = events_of(res)
                    if phase == "full":
                        if guard is None:
                            guard = ev
                        elif ev != guard:
                            print(
                                f"GUARD MISMATCH arm={arm} round={rnd}: "
                                f"{guard} -> {ev}",
                                file=sys.stderr,
                            )
                            return 2
                    rows.append({"round": rnd, "arm": arm, "phase": phase, "res": res})
                    print(
                        f"round={rnd} arm={arm} phase={phase} "
                        f"wall={sum_field(res, 'wall'):.4f} "
                        f"cpu={sum_field(res, 'cpu'):.4f} "
                        f"iso_wall={res['models']['iso']['wall']:.4f} "
                        f"ge_wall={res['models']['ge']['wall']:.4f} "
                        f"events={ev} load1={load1():.1f}"
                    )
        print(f"guard(full events, both arms, all rounds): {guard}")
        for phase in phases:
            a = [r["res"] for r in rows if r["phase"] == phase and r["arm"] == "A"]
            b = [r["res"] for r in rows if r["phase"] == phase and r["arm"] == "B"]
            for field in ("wall", "cpu"):
                va = sorted(sum_field(x, field) for x in a)
                vb = sorted(sum_field(x, field) for x in b)
                ma, mb = va[len(va) // 2], vb[len(vb) // 2]
                pct = 100.0 * (mb - ma) / ma if ma else 0.0
                print(
                    f"summary phase={phase} {field} "
                    f"A_median={ma:.4f} B_median={mb:.4f} delta={pct:+.1f}% "
                    f"A={['%.4f' % v for v in va]} B={['%.4f' % v for v in vb]} "
                    f"load1={load1():.1f}"
                )
        return 0

    # ---- single-tree mode ---------------------------------------------------
    guard = None
    per_phase = {p: {"wall": [], "cpu": []} for p in phases}
    for rep in range(args.reps):
        for phase in phases:
            res = run_child(ROOT, phase, args.threads)
            ev = events_of(res)
            if phase == "full":
                if guard is None:
                    guard = ev
                elif ev != guard:
                    print(f"GUARD MISMATCH rep={rep}: {guard} -> {ev}", file=sys.stderr)
                    return 2
            per_phase[phase]["wall"].append(sum_field(res, "wall"))
            per_phase[phase]["cpu"].append(sum_field(res, "cpu"))
            print(
                f"rep={rep} phase={phase} wall={sum_field(res, 'wall'):.4f} "
                f"cpu={sum_field(res, 'cpu'):.4f} "
                f"iso_wall={res['models']['iso']['wall']:.4f} "
                f"ge_wall={res['models']['ge']['wall']:.4f} "
                f"events={ev} load1={load1():.1f}"
            )
    if guard is not None:
        print(f"guard(full events, all reps): {guard}")
    for phase in phases:
        w = per_phase[phase]["wall"]
        c = per_phase[phase]["cpu"]
        print(
            f"summary phase={phase} wall_median={sorted(w)[len(w) // 2]:.4f} "
            f"cpu_median={sorted(c)[len(c) // 2]:.4f} "
            f"wall={['%.4f' % v for v in w]} cpu={['%.4f' % v for v in c]} "
            f"load1={load1():.1f}"
        )
    if "full" in phases and "setup" in phases:

        def med(vals):
            s = sorted(vals)
            return s[len(s) // 2]

        fe = med(per_phase["full"]["cpu"])
        se = med(per_phase["setup"]["cpu"])
        print(
            f"split(event loop cpu ~= full - setup = {fe - se:.4f}s; "
            f"setup+recording cpu = {se:.4f}s)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
