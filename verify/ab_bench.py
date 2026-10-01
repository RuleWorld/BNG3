#!/usr/bin/env python3
"""Independent interleaved A/B SSA throughput benchmark (perfOracle).

usage:
  ab_bench.py --bin NAME=/path/to/bng_cpp [--bin ...] --reps 9 \
              [--species 150] [--events 2000000] [--seed 4242] [--json out.json]

Design notes (deliberately not a copy of the originating harness):

- Metric: fixed-event-cap SSA runs.  ``max_sim_steps`` caps fired events
  exactly, so every rep of every binary performs the same number of SSA steps
  and writes the same .gdat.  Rate = events / child CPU seconds (user+sys),
  which is immune to co-tenant preemption; wall time is recorded too.
- Two statistics per variant: raw whole-process CPU/events (includes parse,
  network generation and output) and overhead-corrected CPU/events using a
  paired 2-event probe run of the same model through the same binary.
- A/B variants are interleaved round-robin with the order flipped every
  round, so machine drift hits both variants equally.
- The .gdat written by every full run is hashed; the run is only meaningful
  if all variants and all reps produced the same trajectory.

The bench model is the same synthetic ring shape the originating agent used
(species birth/death plus nearest-neighbour conversion, 3n reactions), so the
numbers are comparable, but the generator, statistics and event cap here are
independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def model_text(species: int, events: int, seed: int) -> str:
    n = species
    lines = [
        "begin model",
        "begin parameters",
        "  kb 8",
        "  kd 0.005",
        "  kc 0.002",
        "end parameters",
        "begin molecule types",
        "  X()",
        "end molecule types",
        "begin seed species",
    ]
    lines += [f"  X_{i}()  800" for i in range(n)]
    lines += [
        "end seed species",
        "begin observables",
        "  Molecules  Xt  X()",
        "end observables",
        "begin reaction rules",
    ]
    lines += [f"  0 -> X_{i}()  kb" for i in range(n)]
    lines += [f"  X_{i}() -> 0  kd" for i in range(n)]
    lines += [f"  X_{i}() <-> X_{(i + 1) % n}()  kc, kc" for i in range(n)]
    lines += [
        "end reaction rules",
        "end model",
        "",
        "## actions ##",
        "generate_network({overwrite=>1})",
        'simulate_ssa({suffix=>"bench",t_start=>0,t_end=>1e9,n_steps=>3,'
        f"seed=>{seed},max_sim_steps=>{events}}})",
        "",
    ]
    return "\n".join(lines)


def run_once(binary: Path, model: Path) -> dict:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    done = subprocess.run([str(binary), str(model)], cwd=model.parent,
                          capture_output=True, text=True, timeout=1800)
    wall = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if done.returncode != 0:
        raise RuntimeError(f"{binary} exit {done.returncode}: "
                           f"{(done.stdout + done.stderr)[:800]}")
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return {"cpu_s": cpu, "wall_s": wall, "maxrss_kb": after.ru_maxrss}


def stats(values: list[float]) -> dict:
    mean = statistics.fmean(values) if values else 0.0
    sd = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": mean,
        "stdev": sd,
        "max": max(values),
        "cv_pct": (100.0 * sd / mean) if mean else 0.0,
        "samples": values,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", action="append", required=True, metavar="NAME=PATH")
    ap.add_argument("--reps", type=int, default=9)
    ap.add_argument("--species", type=int, default=150)
    ap.add_argument("--events", type=int, default=2_000_000)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    bins = {}
    for spec in args.bin:
        name, _, path = spec.partition("=")
        bins[name] = Path(path).resolve()
    names = list(bins)

    raw: dict[str, list[float]] = {n: [] for n in names}
    corr: dict[str, list[float]] = {n: [] for n in names}
    wall: dict[str, list[float]] = {n: [] for n in names}
    probe_cpu: dict[str, list[float]] = {n: [] for n in names}
    rss: dict[str, int] = {n: 0 for n in names}
    gdat: dict[str, set[str]] = {n: set() for n in names}

    with tempfile.TemporaryDirectory(prefix="oracle-ab-") as tmp:
        root = Path(tmp)
        full = root / "full.bngl"
        probe = root / "probe.bngl"
        full.write_text(model_text(args.species, args.events, args.seed))
        probe.write_text(model_text(args.species, 2, args.seed))

        for rep in range(args.reps):
            order = names if rep % 2 == 0 else list(reversed(names))
            for name in order:
                f = run_once(bins[name], full)
                p = run_once(bins[name], probe)
                raw[name].append(args.events / f["cpu_s"])
                corr[name].append(args.events / (f["cpu_s"] - p["cpu_s"]))
                wall[name].append(args.events / f["wall_s"])
                probe_cpu[name].append(p["cpu_s"])
                rss[name] = max(rss[name], f["maxrss_kb"])
                gdat[name].add(hashlib.sha256(
                    (root / "full_bench.gdat").read_bytes()).hexdigest())
            print(f"  rep {rep + 1}/{args.reps} done", file=sys.stderr)

    result: dict = {
        "species": args.species,
        "reactions": 3 * args.species,
        "events_per_rep": args.events,
        "reps": args.reps,
        "raw_events_per_cpu_s": {n: stats(v) for n, v in raw.items()},
        "corrected_events_per_cpu_s": {n: stats(v) for n, v in corr.items()},
        "events_per_wall_s": {n: stats(v) for n, v in wall.items()},
        "probe_cpu_s": {n: stats(v) for n, v in probe_cpu.items()},
        "max_rss_kb": rss,
        "gdat_hashes": {n: sorted(v) for n, v in gdat.items()},
    }
    all_hashes = {h for v in gdat.values() for h in v}
    result["gdat_identical_across_variants"] = len(all_hashes) == 1

    ref = names[0]
    ratios = {}
    for n in names[1:]:
        ratios[f"{n}_vs_{ref}"] = {
            "raw_min": (result["raw_events_per_cpu_s"][n]["min"]
                        / result["raw_events_per_cpu_s"][ref]["min"]),
            "raw_median": (result["raw_events_per_cpu_s"][n]["median"]
                           / result["raw_events_per_cpu_s"][ref]["median"]),
            "corrected_min": (result["corrected_events_per_cpu_s"][n]["min"]
                              / result["corrected_events_per_cpu_s"][ref]["min"]),
            "corrected_median": (result["corrected_events_per_cpu_s"][n]["median"]
                                 / result["corrected_events_per_cpu_s"][ref]["median"]),
            "wall_min": (result["events_per_wall_s"][n]["min"]
                         / result["events_per_wall_s"][ref]["min"]),
        }
    result["ratios"] = ratios

    print(f"\n== events/sec (species={args.species}, R={3 * args.species}, "
          f"events/rep={args.events}, reps={args.reps})")
    for label, key in (("raw cpu", "raw_events_per_cpu_s"),
                       ("corrected cpu", "corrected_events_per_cpu_s"),
                       ("wall", "events_per_wall_s")):
        print(f"-- {label}")
        for n in names:
            s = result[key][n]
            print(f"  {n:<10} min={s['min']:>12,.0f}  median={s['median']:>12,.0f}  "
                  f"mean={s['mean']:>12,.0f}  sd={s['stdev']:>9,.0f}  "
                  f"cv={s['cv_pct']:.2f}%")
    print(f"\n== ratios vs {ref}")
    for k, v in ratios.items():
        print(f"  {k}: raw min={v['raw_min']:.4f} median={v['raw_median']:.4f} | "
              f"corrected min={v['corrected_min']:.4f} "
              f"median={v['corrected_median']:.4f} | wall min={v['wall_min']:.4f}")
    print(f"\n== peak child max RSS (kB): "
          + ", ".join(f"{n}={rss[n]}" for n in names))
    print(f"== full-run .gdat identical across all variants and reps: "
          f"{result['gdat_identical_across_variants']}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
