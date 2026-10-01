#!/usr/bin/env python3
"""Engine SSA throughput benchmark for the BNG3 C++ simulation lane.

Constructs a self-contained synthetic reaction network, runs it through
``bng_cpp`` with a fixed seed and an exact internal-step cap, and reports one
primary number: simulated network events per second (best rep over >=5
interleaved reps, with median and stdev).

Method notes:

- ``max_sim_steps`` caps the number of fired SSA events exactly, so the event
  count per rep is the cap itself (the model's birth/death balance keeps the
  network alive for the whole run).
- Each full run is paired with a probe run of the same process shape at
  ``max_sim_steps=2``. The probe measures parse/network-generation/output
  overhead that is not simulation; subtracting it isolates simulation.
- The primary statistic uses child CPU time (user+sys), not wall time, so
  preemption by other users of this shared host does not inflate the
  measurement. Wall times are still recorded.
- Variants are interleaved round-robin (order alternating by round), and the
  primary number is the best (fastest) rep: co-tenants can only slow a run
  down, so the fastest rep bounds the machine's achievable throughput.
  Median and stdev are reported alongside as the spread.

Example (A/B against a saved baseline binary):

    python benchmarks/bench_engine_ssa.py \
        --variant baseline=/tmp/bng3-baseline/bng_cpp \
        --variant current=build/cpp/bng_cpp \
        --reps 7 --json /tmp/ssa_bench.json
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def model_text(species: int, events: int, seed: int) -> str:
    """Ring network: per-species birth/death plus nearest-neighbour conversion.

    ``species`` seed species X_0..X_{n-1} give 3n reactions (n births,
    n deaths, n reversible ring conversions), so the compiled network size
    scales linearly and the per-event propensity work is non-trivial.
    """
    n = species
    lines = [
        "begin model",
        "begin parameters",
        "    kb  8",
        "    kd  0.005",
        "    kc  0.002",
        "end parameters",
        "begin molecule types",
        "    X()",
        "end molecule types",
        "begin seed species",
    ]
    lines += [f"    X_{i}()  800" for i in range(n)]
    lines += [
        "end seed species",
        "begin observables",
        "    Molecules  Xt  X()",
        "end observables",
        "begin reaction rules",
    ]
    lines += [f"    0 -> X_{i}()  kb" for i in range(n)]
    lines += [f"    X_{i}() -> 0  kd" for i in range(n)]
    lines += [f"    X_{i}() <-> X_{(i + 1) % n}()  kc, kc" for i in range(n)]
    lines += [
        "end reaction rules",
        "end model",
        "",
        "## actions ##",
        "generate_network({overwrite=>1})",
        # t_end is effectively unreachable: max_sim_steps stops the run first.
        'simulate_ssa({suffix=>"bench",t_start=>0,t_end=>1e9,n_steps=>3,'
        f"seed=>{seed},max_sim_steps=>{events}}})",
        "",
    ]
    return "\n".join(lines)


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
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return {"wall_s": wall, "cpu_s": cpu}


def variant_rate(
    bng_cpp: Path, workdir: Path, name: str, species: int, events: int, seed: int
) -> dict:
    full_model = workdir / f"{name}_s{species}_full.bngl"
    probe_model = workdir / f"{name}_s{species}_probe.bngl"
    full_model.write_text(model_text(species, events, seed), encoding="utf-8")
    probe_model.write_text(model_text(species, 2, seed), encoding="utf-8")
    full = run_once(bng_cpp, full_model)
    probe = run_once(bng_cpp, probe_model)
    sim_cpu = full["cpu_s"] - probe["cpu_s"]
    sim_wall = full["wall_s"] - probe["wall_s"]
    if sim_cpu <= 0:
        raise RuntimeError(
            f"non-positive simulated CPU time for {name}: full={full} probe={probe}"
        )
    return {
        "events": events,
        "cpu_full_s": full["cpu_s"],
        "cpu_probe_s": probe["cpu_s"],
        "sim_cpu_s": sim_cpu,
        "wall_full_s": full["wall_s"],
        "wall_probe_s": probe["wall_s"],
        "sim_wall_s": sim_wall,
        "events_per_sec": events / sim_cpu,
        "wall_events_per_sec": events / sim_wall if sim_wall > 0 else None,
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
    parser.add_argument(
        "--events", type=int, default=1_000_000, help="exact SSA event cap"
    )
    parser.add_argument("--species", type=int, default=150, help="ring size")
    parser.add_argument("--seed", type=int, default=12345)
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
    with tempfile.TemporaryDirectory(prefix="bng3-ssa-bench-") as temp:
        workdir = Path(temp)
        for rep in range(args.reps):
            order = variants if rep % 2 == 0 else list(reversed(variants))
            for name, path in order:
                row = variant_rate(
                    path, workdir, name, args.species, args.events, args.seed
                )
                row["rep"] = rep
                per_variant[name].append(row)
                print(
                    f"[rep {rep}] {name}: {row['events_per_sec']:,.0f} events/s "
                    f"(sim cpu {row['sim_cpu_s']:.3f}s, "
                    f"sim wall {row['sim_wall_s']:.3f}s)",
                    flush=True,
                )

    results = {
        "primary_metric": "ssa_network_events_per_sec_best_of_reps",
        "events_per_rep": args.events,
        "species": args.species,
        "reactions": 3 * args.species,
        "seed": args.seed,
        "reps_per_variant": args.reps,
        "variants": {
            name: {
                "binary": str(path),
                **summarize([r["events_per_sec"] for r in per_variant[name]]),
                "wall_median": summarize(
                    [r["wall_full_s"] for r in per_variant[name]]
                )["median"],
                "runs": per_variant[name],
            }
            for name, path in variants
        },
    }

    print(
        f"\nprimary metric: SSA network events/sec (child CPU time, best of "
        f"{args.reps} interleaved reps)"
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
