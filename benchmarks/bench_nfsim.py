#!/usr/bin/env python3
"""NFsim (simulate_nf) throughput benchmark for the BNG3 C++ simulation lane.

Constructs a self-contained rule-based model (receptor/enzyme binding,
phosphorylation, synthesis/degradation over ~3.8k seed molecules) and runs it
through ``bng_cpp``'s in-process NFsim path. NFsim itself prints

    You just simulated <N> reactions in <T>s
    ( <rate> reactions/sec, ... )

so the primary number is simulation-loop throughput parsed from the process
stdout: **NFsim reactions per second, best of >=5 interleaved reps**, with
median, worst, and stdev alongside. The printed time is the simulator loop's
own CPU time (``clock()``), excluding parse/network/output; wall time is also
recorded per rep.

Variants are interleaved round-robin (order alternating by round) so
shared-host noise hits every variant equally; the fastest rep bounds
achievable throughput because co-tenants can only slow a run down.

Fixed seed: the seeded trajectory must stay byte-identical across a
performance change (see benchmarks/check_engine_ssa_identity.sh for the SSA
equivalent; for NFsim, diff the .gdat of two binaries over the same model).

Example:

    python benchmarks/bench_nfsim.py \
        --variant baseline=/path/to/pristine/bng_cpp \
        --variant current=build/cpp/bng_cpp \
        --reps 9 --json /tmp/nfsim-bench.json
"""

from __future__ import annotations

import argparse
import json
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_RATE_RE = re.compile(
    r"You just simulated\s+(\d+)\s+reactions in\s+([0-9.eE+-]+)s"
)
_REACTIONS_PER_SEC_RE = re.compile(r"\(\s*([0-9.eE+-]+)\s+reactions/sec")


def model_text(t_end: float, n_steps: int, seed: int) -> str:
    """Rule network exercising binding, catalysis, and turnover.

    800 receptors x 400 enzymes x 600 scaffolds give multi-molecule complexes
    (so pattern matching and complex traversal run on every event), and the
    phosphorylation/dephos/synthesis/degradation rules keep events firing for
    the whole simulated span.
    """
    return f"""begin model
begin parameters
    kbind    0.0005
    kunbind  0.05
    kphos    0.05
    kdephos  0.02
    kdeg     0.001
    ksyn     1.0
end parameters
begin molecule types
    R(b, p1~u~p, p2~u~p)
    K(a)
    S(b)
    X()
    M()
end molecule types
begin seed species
    R(b, p1~u~p, p2~u~p)  800
    K(a)                   400
    S(b)                   600
    X()                   1000
    M()                      0
end seed species
begin observables
    Molecules Rtot R
    Molecules Rp1 R(p1~p)
    Molecules Rp2 R(p2~p)
    Molecules RKS  R(b!1).K(a!1)
    Molecules Mtot M()
end observables
begin reaction rules
    R(b) + K(a)        <-> R(b!1).K(a!1)      kbind, kunbind
    R(b) + S(b)        <-> R(b!1).S(b!1)      kbind, kunbind
    R(p1~u).K(a)       -> R(p1~p).K(a)         kphos
    R(p2~u).K(a)       -> R(p2~p).K(a)         kphos
    R(p1~p)            -> R(p1~u)              kdephos
    R(p2~p)            -> R(p2~u)              kdephos
    M()                -> M() + M()            ksyn
    M()                -> 0                    kdeg
end reaction rules
end model
## actions ##
generate_network({{overwrite=>1}})
simulate_nf({{prefix=>"nfsim_bench",t_end=>{t_end},n_steps=>{n_steps},seed=>{seed}}})
"""


def run_once(bng_cpp: Path, model: Path) -> dict:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    completed = subprocess.run(
        [str(bng_cpp), str(model)],
        cwd=model.parent,
        capture_output=True,
        text=True,
        timeout=600,
    )
    wall = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if completed.returncode != 0:
        detail = "\n".join((completed.stdout, completed.stderr)).strip()
        raise RuntimeError(
            f"bng_cpp failed (exit {completed.returncode}): {detail[:4000]}"
        )
    rate = _REACTIONS_PER_SEC_RE.search(completed.stdout)
    counts = _RATE_RE.search(completed.stdout)
    if not rate or not counts:
        raise RuntimeError(
            f"no NFsim throughput line in output: {completed.stdout[:2000]}"
        )
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return {
        "reactions": int(counts.group(1)),
        "loop_cpu_s": float(counts.group(2)),
        "reactions_per_sec": float(rate.group(1)),
        "wall_s": wall,
        "proc_cpu_s": cpu,
        "stdout": completed.stdout,
    }


def summarize(values: list[float]) -> dict:
    return {
        "best": max(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="benchmark variant binary (repeatable; default: current build)",
    )
    parser.add_argument("--reps", type=int, default=7, help="reps per variant")
    parser.add_argument("--t-end", type=float, default=50000.0)
    parser.add_argument("--n-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--json", type=Path, help="write full results here")
    args = parser.parse_args()

    variants: list[tuple[str, Path]] = []
    if args.variant:
        for spec in args.variant:
            name, sep, raw = spec.partition("=")
            if not sep:
                parser.error(f"--variant needs NAME=PATH, got {spec!r}")
            variants.append((name, Path(raw).resolve()))
    else:
        variants.append(("current", (REPO_ROOT / "build/cpp/bng_cpp").resolve()))
    for name, path in variants:
        if not path.is_file():
            parser.error(f"variant {name!r}: no such binary: {path}")
    if args.reps < 5:
        parser.error("--reps must be at least 5 (noise control)")

    per_variant: dict[str, list[dict]] = {name: [] for name, _ in variants}
    with tempfile.TemporaryDirectory(prefix="bng3-nfsim-bench-") as temp:
        workdir = Path(temp)
        for rep in range(args.reps):
            order = variants if rep % 2 == 0 else list(reversed(variants))
            for name, path in order:
                model = workdir / f"{name}.bngl"
                model.write_text(
                    model_text(args.t_end, args.n_steps, args.seed),
                    encoding="utf-8",
                )
                row = run_once(path, model)
                row["rep"] = rep
                per_variant[name].append(row)
                print(
                    f"[rep {rep}] {name}: {row['reactions_per_sec']:,.0f} "
                    f"reactions/s (loop {row['loop_cpu_s']:.3f}s, "
                    f"wall {row['wall_s']:.3f}s)",
                    flush=True,
                )

    results = {
        "primary_metric": "nfsim_reactions_per_sec_best_of_reps",
        "t_end": args.t_end,
        "n_steps": args.n_steps,
        "seed": args.seed,
        "reps_per_variant": args.reps,
        "variants": {
            name: {
                "binary": str(path),
                **summarize([r["reactions_per_sec"] for r in per_variant[name]]),
                "reactions_median": summarize(
                    [r["reactions"] for r in per_variant[name]]
                )["median"],
                "runs": per_variant[name],
            }
            for name, path in variants
        },
    }

    print(
        f"\nprimary metric: NFsim reactions/sec (simulator-loop CPU time, "
        f"best of {args.reps} interleaved reps)"
    )
    for name, _ in variants:
        s = results["variants"][name]
        print(
            f"  {name:>10}: best={s['best']:,.0f}  median={s['median']:,.0f}  "
            f"worst={s['min']:,.0f}  stdev={s['stdev']:,.0f}"
        )
    if len(variants) == 2:
        a, b = (results["variants"][n] for n, _ in variants)
        print(
            f"  speedup({variants[1][0]}/{variants[0][0]}) = "
            f"{b['best'] / a['best']:.3f}x (best-based), "
            f"{b['median'] / a['median']:.3f}x (median-based)"
        )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
