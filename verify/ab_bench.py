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
import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any
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


def maxrss_to_bytes(value: int, platform: str | None = None) -> int:
    """Normalize wait4's platform-specific peak-RSS unit to bytes."""
    platform = platform or sys.platform
    if platform == "darwin":
        return int(value)
    if platform.startswith("linux"):
        return int(value) * 1024
    raise RuntimeError(f"per-child peak RSS units are unsupported on {platform}")


def wait4_child(process: subprocess.Popen, timeout: float) -> resource.struct_rusage:
    """Wait for one child and return its own rusage, including peak RSS."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        except InterruptedError:
            continue
        if pid == process.pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return usage
        if time.monotonic() >= deadline:
            process.kill()
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            raise subprocess.TimeoutExpired(process.args, timeout)
        time.sleep(0.01)


def run_once(binary: Path, model: Path, timeout: float = 1800.0) -> dict:
    """Run in a fresh directory so no prior artifact can satisfy this run."""
    run_dir = Path(tempfile.mkdtemp(prefix=f"pr78-{model.stem}-",
                                    dir=model.parent))
    try:
        run_model = run_dir / model.name
        shutil.copyfile(model, run_model)
        log_path = run_dir / "child.log"
        start = time.perf_counter()
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [str(binary), str(run_model)], cwd=run_dir,
                stdout=log, stderr=subprocess.STDOUT,
            )
            usage = wait4_child(process, timeout)
        wall = time.perf_counter() - start
        if process.returncode != 0:
            detail = log_path.read_text(errors="replace").strip()
            raise RuntimeError(f"{binary} exit {process.returncode}: {detail[-800:]}")

        gdat = sorted(run_dir.glob("*.gdat"))
        net = sorted(run_dir.glob("*.net"))
        if len(gdat) != 1:
            raise RuntimeError(f"{binary} produced {len(gdat)} fresh .gdat files")
        if len(net) != 1:
            raise RuntimeError(f"{binary} produced {len(net)} fresh .net files")
        return {
            "cpu_s": usage.ru_utime + usage.ru_stime,
            "wall_s": wall,
            "max_rss_bytes": maxrss_to_bytes(usage.ru_maxrss),
            "gdat_sha256": hashlib.sha256(gdat[0].read_bytes()).hexdigest(),
            "net_sha256": hashlib.sha256(net[0].read_bytes()).hexdigest(),
        }
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_context() -> list[float] | None:
    try:
        return list(os.getloadavg())
    except (AttributeError, OSError):
        return None


def git_revision(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root,
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _main() -> int:
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
        if not name or not path:
            ap.error(f"--bin needs NAME=PATH, got {spec!r}")
        if name in bins:
            ap.error(f"duplicate binary name: {name}")
        bins[name] = Path(path).resolve()
    names = list(bins)
    if args.reps < 1 or args.species < 1 or args.events < 1:
        ap.error("--reps, --species, and --events must be positive")
    for name, path in bins.items():
        if not path.is_file():
            ap.error(f"binary {name!r} does not exist: {path}")

    context_start = load_context()

    raw: dict[str, list[float]] = {n: [] for n in names}
    corr: dict[str, list[float]] = {n: [] for n in names}
    wall: dict[str, list[float]] = {n: [] for n in names}
    probe_cpu: dict[str, list[float]] = {n: [] for n in names}
    rss_bytes: dict[str, int] = {n: 0 for n in names}
    rss_samples: dict[str, list[float]] = {n: [] for n in names}
    gdat: dict[str, set[str]] = {n: set() for n in names}
    net: dict[str, set[str]] = {n: set() for n in names}
    runs: dict[str, list[dict[str, Any]]] = {n: [] for n in names}

    with tempfile.TemporaryDirectory(prefix="oracle-ab-") as tmp:
        root = Path(tmp)
        full = root / "full.bngl"
        probe = root / "probe.bngl"
        full_text = model_text(args.species, args.events, args.seed)
        probe_text = model_text(args.species, 2, args.seed)
        full.write_text(full_text)
        probe.write_text(probe_text)

        for rep in range(args.reps):
            order = names if rep % 2 == 0 else list(reversed(names))
            for name in order:
                f = run_once(bins[name], full)
                p = run_once(bins[name], probe)
                corrected_cpu = f["cpu_s"] - p["cpu_s"]
                if corrected_cpu <= 0:
                    raise RuntimeError(
                        f"non-positive corrected CPU time for {name}: "
                        f"full={f['cpu_s']:.6f}s probe={p['cpu_s']:.6f}s")
                raw[name].append(args.events / f["cpu_s"])
                corr[name].append(args.events / corrected_cpu)
                wall[name].append(args.events / f["wall_s"])
                probe_cpu[name].append(p["cpu_s"])
                rss_bytes[name] = max(rss_bytes[name], f["max_rss_bytes"])
                rss_samples[name].append(f["max_rss_bytes"])
                gdat[name].add(f["gdat_sha256"])
                net[name].add(f["net_sha256"])
                runs[name].append({
                    "rep": rep + 1,
                    "full_cpu_s": f["cpu_s"],
                    "probe_cpu_s": p["cpu_s"],
                    "corrected_cpu_s": corrected_cpu,
                    "full_wall_s": f["wall_s"],
                    "full_max_rss_bytes": f["max_rss_bytes"],
                    "gdat_sha256": f["gdat_sha256"],
                    "net_sha256": f["net_sha256"],
                })
            print(f"  rep {rep + 1}/{args.reps} done", file=sys.stderr)

    result: dict = {
        "repository_head": git_revision(Path(__file__).resolve().parent.parent),
        "benchmark_script": str(Path(__file__).resolve()),
        "benchmark_script_sha256": sha256_file(Path(__file__).resolve()),
        "species": args.species,
        "reactions": 3 * args.species,
        "events_per_rep": args.events,
        "reps": args.reps,
        "seed": args.seed,
        "arm_order": "alternating; reverse variant order every rep",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "context_loadavg_start": context_start,
        "context_loadavg_end": load_context(),
        "binary_paths": {n: str(bins[n]) for n in names},
        "binary_sha256": {n: sha256_file(bins[n]) for n in names},
        "model_sha256": {
            "full": hashlib.sha256(full_text.encode()).hexdigest(),
            "probe": hashlib.sha256(probe_text.encode()).hexdigest(),
        },
        "raw_events_per_cpu_s": {n: stats(v) for n, v in raw.items()},
        "corrected_events_per_cpu_s": {n: stats(v) for n, v in corr.items()},
        "events_per_wall_s": {n: stats(v) for n, v in wall.items()},
        "probe_cpu_s": {n: stats(v) for n, v in probe_cpu.items()},
        "max_rss_bytes": rss_bytes,
        "rss_bytes_per_rep": {n: stats(v) for n, v in rss_samples.items()},
        "rss_unit": "bytes",
        "gdat_hashes": {n: sorted(v) for n, v in gdat.items()},
        "net_hashes": {n: sorted(v) for n, v in net.items()},
        "runs": runs,
    }
    all_gdat_hashes = {h for v in gdat.values() for h in v}
    all_net_hashes = {h for v in net.values() for h in v}
    result["gdat_identical_across_variants"] = len(all_gdat_hashes) == 1
    result["net_identical_across_variants"] = len(all_net_hashes) == 1
    result["identity_gate_pass"] = (
        result["gdat_identical_across_variants"]
        and result["net_identical_across_variants"]
    )

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

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, indent=2) + "\n")
    if not result["identity_gate_pass"]:
        print("ERROR: raw output identity gate failed; do not report throughput "
              "as a valid matched-pair result", file=sys.stderr)
        return 2

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
    print(f"\n== peak child max RSS (bytes): "
          + ", ".join(f"{n}={rss_bytes[n]}" for n in names))
    print(f"== raw .gdat and .net identity across variants and reps: "
          f"{result['identity_gate_pass']}")
    return 0


def main() -> int:
    try:
        return _main()
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
