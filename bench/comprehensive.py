#!/usr/bin/env python3
"""Comprehensive BNG3 speed + bottleneck report (performance-swarm foundation).

One command, three sections, one JSON:

  1. harness   bench/run_bench.py --reps N --json <tmp>: the fixed 6-component
               weighted harness with determinism guards (composite =
               sum(weight*seconds), lower is better). Printed output passes
               through live.
  2. gpu       benchmark_gpu_batch_ssa.py: CPU single-worker vs CPU multi-core
               vs the compiled GPU backend, 4 models x 3 batch sizes. The
               script's benchmark_batch_ssa_results.json is embedded here and
               then removed. Recorded as {error: ...} (not fatal) when no GPU
               backend is usable or the script is absent.
  3. profile   cProfile top-20 by self time, one fresh child per case:
                 import     -- `import bionetgen`
                 load       -- bionetgen.load(models/egfr_net.bngl) + property reads
                 ode        -- simulate_ode on bench/fixtures/ode_many_functions.bngl
                               (parse+generate outside the profiler)
                 ssa        -- simulate_batch_ssa_cpu, isomerization, 50k traj
                               (parse+generate outside the profiler)
               cProfile sees Python frames only: C++ work collapses into the
               pybind11 call it sits under, which is exactly the layer split
               (import / parse / generate / simulate) this section reports.

  python3 bench/comprehensive.py [--reps 5] [--json FILE]
                                 [--skip-gpu] [--skip-profile] [--skip-harness]

Prerequisites are those of bench/run_bench.py (an already-built worktree
providing build/cpp/bng_cpp and the _bionetgen_cpp extension). Every timing is
host-dependent: quote load1 with it, and use bench/ab.py for any A/B claim
(see bench/README.md -- ~11% cross-session drift is the resolution floor).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Bootstrapped into every profile child: this worktree's extension first, and
# scikit-build editable finders removed, so the child cannot import another
# checkout (same contract as run_bench.BOOTSTRAP).
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

# Each case: setup runs OUTSIDE the profiler (parse+generate there, so the
# profiled region is the operation itself); profiled is what cProfile wraps.
# _extra is filled by the profiled block and merged into the child's JSON.
_PROFILE_CASES: dict[str, dict[str, str]] = {
    "import": {
        "setup": "pass",
        "profiled": "import bionetgen",
    },
    "load": {
        "setup": "import bionetgen",
        "profiled": """\
m = bionetgen.load("models/egfr_net.bngl")
_counts = [
    len(getattr(m, p))
    for p in ("parameters", "molecule_types", "seed_species", "observables",
              "reaction_rules", "functions", "compartments", "actions")
]""",
    },
    "ode": {
        "setup": """\
import bionetgen
import _bionetgen_cpp as cpp
model = cpp.parse_file("bench/fixtures/ode_many_functions.bngl")
network = cpp.generate_network(model)""",
        "profiled": """\
res = cpp.simulate_ode(model, network, t_end=100.0, n_steps=5000)
assert res.get("concentrations"), "no concentrations" """,
    },
    "ssa": {
        "setup": """\
import bionetgen
import _bionetgen_cpp as cpp
model = cpp.parse_file("models/isomerization.bngl")
network = cpp.generate_network(model)""",
        "profiled": """\
res = cpp.simulate_batch_ssa_cpu(model, network, batch_size=50000,
                                 t_end=20.0, n_steps=10, threads=0,
                                 base_seed=12345)
_EXTRA = {"events": int(res["total_events"])}""",
    },
}

_TOP_N = 20


def _load1() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return float("nan")


def _indent(block: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in block.splitlines())


def run_harness(reps: int) -> dict:
    """Section 1: run_bench.py into a temp JSON; stdout passes through live."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "bench" / "run_bench.py"),
             "--reps", str(reps), "--json", str(tmp_path)],
            cwd=str(ROOT),
        )
        if proc.returncode != 0 or not tmp_path.is_file():
            raise SystemExit(
                f"run_bench.py failed (exit {proc.returncode}); "
                "fix the harness before profiling anything"
            )
        return json.loads(tmp_path.read_text())
    finally:
        tmp_path.unlink(missing_ok=True)


def run_gpu() -> dict:
    """Section 2: the existing GPU batch-SSA benchmark, embedded or recorded."""
    script = ROOT / "benchmark_gpu_batch_ssa.py"
    if not script.is_file():
        return {"error": "benchmark_gpu_batch_ssa.py not present in this tree"}
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=900,
    )
    results_path = ROOT / "benchmark_batch_ssa_results.json"
    out: dict = {"returncode": proc.returncode, "backend_line": None}
    match = re.search(r"Active GPU backend: (\S+)", proc.stdout)
    if match:
        out["backend_line"] = match.group(1)
    if proc.returncode == 0 and results_path.is_file():
        out["results"] = json.loads(results_path.read_text())
    else:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
        out["error"] = " | ".join(tail) if tail else "no output"
    results_path.unlink(missing_ok=True)
    return out


def _run_profile_child(case: dict) -> dict:
    """Fresh interpreter: setup, then cProfile around only the profiled block.

    StatEntry fields (CPython): inlinetime = pstats "tottime" (self time,
    excluding subcalls), totaltime = pstats "cumtime". `code` is a code object
    for Python functions and a plain string for C/builtin calls.
    """
    child = BOOTSTRAP + "\n".join([
        "import cProfile, json, time",
        case["setup"],
        "_prof = cProfile.Profile()",
        "_t0 = time.perf_counter()",
        "_prof.enable()",
        "try:",
        _indent(case["profiled"], "    "),
        "finally:",
        "    _prof.disable()",
        "_wall = time.perf_counter() - _t0",
        "_EXTRA = locals().get('_EXTRA', {})",
        "_rows = []",
        "for _e in _prof.getstats():",
        "    _code = _e.code",
        "    if hasattr(_code, 'co_filename'):",
        "        _where = _code.co_filename + ':' + str(_code.co_firstlineno)",
        "        _name = _code.co_name",
        "    else:",
        "        _where = str(_code)",
        "        _name = str(_code)",
        "    _rows.append({'where': _where, 'func': _name,",
        "                  'calls': int(_e.callcount),",
        "                  'tottime': float(_e.inlinetime),",
        "                  'cumtime': float(_e.totaltime)})",
        "_rows.sort(key=lambda r: -r['tottime'])",
        "print(json.dumps({'wall': _wall, 'top': _rows[:%d], **_EXTRA}))" % _TOP_N,
        "",
    ])
    proc = subprocess.run(
        [sys.executable, "-c", child, str(ROOT)],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        return {"error": f"child exit {proc.returncode}: {proc.stderr.strip()[-500:]}"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": f"unparseable child output: {proc.stdout[:300]!r}"}


def run_profile() -> dict:
    """Section 3: one cProfile child per case, top-20 self time per case."""
    out = {}
    for name, case in _PROFILE_CASES.items():
        t0 = time.perf_counter()
        data = _run_profile_child(case)
        data["case_wall_s"] = round(time.perf_counter() - t0, 4)
        data["note"] = (
            "cProfile: Python frames only; C++ time sits in the pybind11 "
            "call named by where/func"
        )
        out[name] = data
    return out


def _print_profile(profile: dict) -> None:
    for case, data in profile.items():
        wall = data.get("wall")
        header = f"\n--- profile: {case}"
        if wall is not None:
            header += f" (wall {wall:.3f}s inside profiler)"
        print(header + " ---")
        if "error" in data:
            print(f"  ERROR: {data['error']}")
            continue
        if "events" in data:
            print(f"  events={data['events']} (guard for comparability)")
        print(f"  {'tottime':>9} {'per-call':>10} {'calls':>8} "
              f"{'cumtime':>9}  location")
        for row in data["top"]:
            per = row["tottime"] / row["calls"] if row["calls"] else 0.0
            where = row["where"].replace(str(ROOT) + "/", "")
            print(f"  {row['tottime']:>9.4f} {per:>10.6f} {row['calls']:>8} "
                  f"{row['cumtime']:>9.4f}  {row['func']}  ({where})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full machine-readable report here")
    ap.add_argument("--skip-gpu", action="store_true")
    ap.add_argument("--skip-profile", action="store_true")
    ap.add_argument("--skip-harness", action="store_true",
                    help="gpu/profile only (harness needs a quiet host)")
    args = ap.parse_args()

    git_rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(ROOT), capture_output=True, text=True,
    ).stdout.strip() or "unknown"

    print("=" * 78)
    print(f"BNG3 comprehensive benchmark  git={git_rev}  "
          f"python={sys.version.split()[0]}  platform={platform.platform()}")
    print(f"load1={_load1():.1f} at start -- quote with every timing")
    print("=" * 78)

    report: dict = {
        "meta": {
            "git": git_rev,
            "host": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
            "load1_start": _load1(),
            "argv": sys.argv[1:],
        }
    }
    failed = False

    if not args.skip_harness:
        print("\n########## 1. harness (bench/run_bench.py) ##########")
        report["harness"] = run_harness(args.reps)

    if not args.skip_gpu:
        print("\n########## 2. gpu (benchmark_gpu_batch_ssa.py) ##########")
        report["gpu"] = run_gpu()
        gpu = report["gpu"]
        if "error" in gpu:
            print(f"gpu: not run ({gpu['error']})")
        else:
            print(f"gpu backend: {gpu.get('backend_line')}")
            for model in gpu.get("results", []):
                for run in model.get("runs", []):
                    mc = run["cpu_mc"]
                    g = run.get("gpu") or {}
                    if g.get("sim_time_ms"):
                        speedup = mc["sim_time_ms"] / g["sim_time_ms"]
                        print(f"  {model['model_id']:<16} "
                              f"batch={run['batch_size']:>6}  "
                              f"CPU-MC={mc['sim_time_ms']:>9.2f}ms  "
                              f"GPU={g['sim_time_ms']:>9.2f}ms  "
                              f"speedup={speedup:>6.2f}x")

    if not args.skip_profile:
        print("\n########## 3. profile (cProfile, top-20 self time) ##########")
        report["profile"] = run_profile()
        _print_profile(report["profile"])
        failed = any("error" in data for data in report["profile"].values())

    report["meta"]["load1_end"] = _load1()
    print(f"\nload1 at end: {report['meta']['load1_end']:.1f}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
