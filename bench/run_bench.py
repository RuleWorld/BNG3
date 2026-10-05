#!/usr/bin/env python3
"""BNG3 fitness harness (swarm/autobench).

Single documented command (run from the repo root of any configured worktree):

    python3 bench/run_bench.py --reps 5 --json bench/baseline.json

Prerequisites (fail-closed, checked up front):
  * an already-configured Release build:
        cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=ON
        cmake --build build
    providing build/cpp/bng_cpp (override with BNG3_BNG_CPP=<path>).
  * python3 able to import the _bionetgen_cpp extension from build/cpp.

Components and weights (composite = sum(weight * seconds); LOWER is better):

    netgen     0.27   C++ network generation: bng_cpp on bench/fixtures/
                      netgen_egfr.bngl (generate_network only), full process
                      wall time; output .net sha256 must be stable across reps.
    ssa_batch  0.33   simulation throughput: in-process batch SSA (CPU pool,
                      fixed base_seed) on models/isomerization.bngl and
                      models/gene_expr_simple.bngl; event counts must be
                      identical across reps (seed determinism guard).
    ode        0.15   ODE integration: in-process simulate_ode on
                      models/isomerization.bngl, models/gene_expr_simple.bngl
                      and bench/fixtures/ode_many_functions.bngl (150
                      zero-argument rate functions -> the F x output-steps
                      regime); final concentration vectors must be identical
                      across reps.
    out_write  0.10   output writing: full CLI run of
                      bench/fixtures/out_write.bngl (simulate_ode,
                      40001 rows x 8 fields); .cdat and .gdat sha256 must be
                      stable across reps.
    py_import  0.08   Python-side: cold-ish `import bionetgen` timed inside a
                      fresh interpreter; must resolve inside this worktree.
    py_load    0.07   Python-side: `bionetgen.load(...)` (real Python API op
                      over the C++ engine), same fresh-interpreter guard.

    (v1 weights, superseded and NOT comparable to v2 composites:
     netgen 0.35, ssa_batch 0.40, py_import 0.10, py_load 0.15 — see README.)

Editable-install guard: this host has a scikit-build editable install whose
site-packages .pth inserts a MetaPathFinder that redirects `bionetgen` to
another checkout. Every child process removes sys.meta_path entries whose
type module starts with "_editable" BEFORE importing, prepends this worktree's
python/ and build/cpp to sys.path, and then asserts the imported module paths
live inside this worktree. SKBUILD_EDITABLE_SKIP does NOT do this (it is a
rebuild-recursion marker), so path assertions are what make it fail closed.

No network access; stdlib only; minutes-scale (typically well under one
minute for the default 5 reps).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WEIGHTS = {
    "netgen": 0.27,
    "ssa_batch": 0.33,
    "ode": 0.15,
    "out_write": 0.10,
    "py_import": 0.08,
    "py_load": 0.07,
}
V1_WEIGHTS = {  # superseded metric; kept for the README's old-composite note
    "netgen": 0.35,
    "ssa_batch": 0.40,
    "py_import": 0.10,
    "py_load": 0.15,
}

# In-process ODE runs: (path, t_end, n_steps). ode_many_functions.bngl is the
# 100+ function model that makes per-step F x steps function bookkeeping
# visible; the other two are the standard small models.
ODE_MODELS = [
    ("models/isomerization.bngl", 100.0, 1000),
    ("models/gene_expr_simple.bngl", 1000.0, 1000),
    ("bench/fixtures/ode_many_functions.bngl", 100.0, 5000),
]

# CLI run whose actions write .cdat/.gdat at 40001 rows x 8 fields.
OUT_WRITE_FIXTURE = "bench/fixtures/out_write.bngl"

# Batch SSA sizing: calibrated on this machine so the component lands around
# half a second while staying deterministic (fixed seed => fixed event counts).
SSA_BATCH = {
    "iso": ("models/isomerization.bngl", 20.0, 200_000),
    "ge": ("models/gene_expr_simple.bngl", 500.0, 800_000),
}
SSA_BASE_SEED = 12345

NETGEN_FIXTURE = "bench/fixtures/netgen_egfr.bngl"

# Pre-import bootstrap shared by every child interpreter: worktree-local
# sys.path first, then drop scikit-build editable MetaPathFinders.
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


class ComponentError(RuntimeError):
    pass


def _run_child(code: str, *, what: str, timeout: float = 300.0) -> dict:
    """Run BOOTSTRAP+code in a fresh interpreter with this worktree's ROOT."""
    proc = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP + code, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise ComponentError(
            f"{what}: child exited {proc.returncode}\n{proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ComponentError(
            f"{what}: unparseable child output: {proc.stdout!r}"
        ) from exc


def _assert_under_root(path_str: str, *, what: str) -> None:
    path = Path(path_str).resolve()
    if not str(path).startswith(str(ROOT)):
        raise ComponentError(
            f"{what}: imported outside this worktree ({path}); "
            "an editable install or PYTHONPATH is hijacking the import"
        )


def find_bng_cpp() -> Path:
    override = os.environ.get("BNG3_BNG_CPP")
    candidates = [Path(override)] if override else []
    candidates.append(ROOT / "build" / "cpp" / "bng_cpp")
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    raise ComponentError(
        "bng_cpp not found. Configure and build first: "
        "cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=ON "
        "&& cmake --build build  (or set BNG3_BNG_CPP=<path>)"
    )


# ---------------------------------------------------------------- components


def bench_netgen(bng_cpp: Path) -> float:
    """Full process wall time for generate_network on the egfr fixture."""
    fixture = ROOT / NETGEN_FIXTURE
    net_out = fixture.with_suffix(".net")
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(bng_cpp), str(fixture)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        raise ComponentError(
            f"netgen: bng_cpp exited {proc.returncode}\n{proc.stderr.strip()}"
        )
    if not net_out.is_file() or net_out.stat().st_size == 0:
        raise ComponentError("netgen: fixture produced no .net output")
    digest = hashlib.sha256(net_out.read_bytes()).hexdigest()
    return wall, digest


_SSA_CODE = """\
import json, time
import _bionetgen_cpp as cpp
BATCH = %s
BASE_SEED = %d
out = {}
for key, (path, t_end, batch) in BATCH.items():
    model = cpp.parse_file(path)
    network = cpp.generate_network(model)
    t0 = time.perf_counter()
    res = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=batch, t_end=t_end, n_steps=10,
        threads=0, base_seed=BASE_SEED,
    )
    out[key] = time.perf_counter() - t0
    out[key + "_events"] = res["total_events"]
print(json.dumps(out))
""" % (json.dumps(SSA_BATCH), SSA_BASE_SEED)


def bench_ssa_batch() -> tuple[float, dict]:
    """In-process batch SSA wall time (both models), fixed seed."""
    out = _run_child(_SSA_CODE + "\n", what="ssa_batch")
    iso_s = out["iso"]
    ge_s = out["ge"]
    events = {"iso": out["iso_events"], "ge": out["ge_events"]}
    return iso_s + ge_s, events


_ODE_CODE = """\
import json, time
import _bionetgen_cpp as cpp
MODELS = %s
out = {"models": {}}
digest = {}
for path, t_end, steps in MODELS:
    model = cpp.parse_file(path)
    network = cpp.generate_network(model)
    t0 = time.perf_counter()
    res = cpp.simulate_ode(model, network, t_end=t_end, n_steps=steps)
    dt = time.perf_counter() - t0
    out["models"][path] = dt
    conc = res.get("concentrations")
    if conc is None:
        raise SystemExit("simulate_ode returned no concentrations for " + path)
    digest[path] = [float(x) for x in conc[-1]]
out["digest"] = digest
print(json.dumps(out))
""" % json.dumps(ODE_MODELS)


def bench_ode() -> tuple[float, dict]:
    """In-process ODE wall time across the three models; final-state digest."""
    out = _run_child(_ODE_CODE + "\n", what="ode")
    total = sum(out["models"].values())
    return total, out["digest"]


def bench_out_write(bng_cpp: Path) -> tuple[float, dict]:
    """Full CLI run writing .cdat/.gdat (40001 rows x 8 fields); hashes."""
    fixture = ROOT / OUT_WRITE_FIXTURE
    outs = [fixture.with_suffix(".cdat"), fixture.with_suffix(".gdat")]
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(bng_cpp), str(fixture)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        raise ComponentError(
            f"out_write: bng_cpp exited {proc.returncode}\n{proc.stderr.strip()}"
        )
    hashes = {}
    for out in outs:
        if not out.is_file() or out.stat().st_size == 0:
            raise ComponentError(f"out_write: missing output {out.name}")
        hashes[out.suffix] = hashlib.sha256(out.read_bytes()).hexdigest()
    return wall, hashes


def bench_py_import() -> tuple[float, str]:
    code = """\
import json, time
t0 = time.perf_counter()
import bionetgen
dt = time.perf_counter() - t0
print(json.dumps({"s": dt, "path": bionetgen.__file__ or ""}))
"""
    out = _run_child(code, what="py_import")
    _assert_under_root(out["path"], what="py_import")
    return out["s"], out["path"]


def bench_py_load() -> tuple[float, str]:
    code = """\
import json, time
import bionetgen
t0 = time.perf_counter()
model = bionetgen.load("models/egfr_net.bngl")
counts = tuple(
    len(getattr(model, prop))
    for prop in ("parameters", "molecule_types", "seed_species",
                 "observables", "reaction_rules", "functions",
                 "compartments", "actions")
)
dt = time.perf_counter() - t0
if model is None or not any(counts):
    raise SystemExit("bionetgen.load produced an empty model")
print(json.dumps({"s": dt, "counts": list(counts),
                  "path": bionetgen.__file__ or ""}))
"""
    out = _run_child(code, what="py_load")
    _assert_under_root(out["path"], what="py_load")
    counts = tuple(out["counts"])
    return out["s"], counts


# ------------------------------------------------------------------ harness


def _stats(values: list[float]) -> dict:
    return {
        "reps": values,
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="write machine-readable results to this file",
    )
    args = parser.parse_args()
    if args.reps < 2:
        parser.error("--reps must be >= 2 (variance is part of the score)")

    try:
        bng_cpp = find_bng_cpp()
    except ComponentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    git_rev = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "unknown"
    )

    print(f"BNG3 fitness harness  reps={args.reps}  git={git_rev}")
    print(f"bng_cpp={bng_cpp}")
    try:
        load1_start = os.getloadavg()[0]
    except OSError:
        load1_start = float("nan")
    # Resolve and PRINT which compiled extension every child will load, so a
    # reader can see whether this worktree built its own or is inheriting
    # another tree's build/ (visibility, not a pass/fail decision).
    ext_path = _run_child(
        "import json\n"
        "import _bionetgen_cpp as _c\n"
        'print(json.dumps({"path": _c.__file__ or ""}))\n',
        what="extension preflight",
    )["path"]
    ext_scope = (
        "worktree"
        if str(Path(ext_path).resolve()).startswith(str(ROOT))
        else "OUTSIDE WORKTREE (shared/other build)"
    )
    print(f"_bionetgen_cpp={ext_path}  [{ext_scope}]")
    print(
        f"load1={load1_start:.1f} (1-min loadavg at start; quote this with "
        f"any timing, plus concurrent benchmark processes)"
    )
    print(f"weights={WEIGHTS}  composite = sum(weight*seconds); lower is better")

    per_rep: dict[str, list[float]] = {name: [] for name in WEIGHTS}
    guards: dict[str, object] = {}
    errors: list[str] = []

    for rep in range(1, args.reps + 1):
        # Interleave components per rep so machine contention drifts all of
        # them together rather than biasing one.
        try:
            t, net_sha = bench_netgen(bng_cpp)
            per_rep["netgen"].append(t)
            if "netgen_sha" in guards and guards["netgen_sha"] != net_sha:
                raise ComponentError("netgen: .net output changed across reps")
            guards["netgen_sha"] = net_sha
        except (ComponentError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))

        try:
            t, events = bench_ssa_batch()
            per_rep["ssa_batch"].append(t)
            if "ssa_events" in guards and guards["ssa_events"] != events:
                raise ComponentError(
                    f"ssa_batch: event counts changed across reps "
                    f"{guards['ssa_events']} -> {events} (seed determinism broken)"
                )
            guards["ssa_events"] = events
        except (ComponentError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))

        try:
            t, digest = bench_ode()
            per_rep["ode"].append(t)
            if "ode_digest" in guards and guards["ode_digest"] != digest:
                raise ComponentError(
                    f"ode: final concentrations changed across reps "
                    f"(determinism broken)"
                )
            guards["ode_digest"] = digest
        except (ComponentError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))

        try:
            t, hashes = bench_out_write(bng_cpp)
            per_rep["out_write"].append(t)
            if "out_write_hashes" in guards and guards["out_write_hashes"] != hashes:
                raise ComponentError(
                    f"out_write: emitted .cdat/.gdat bytes changed across reps "
                    f"{guards['out_write_hashes']} -> {hashes}"
                )
            guards["out_write_hashes"] = hashes
        except (ComponentError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))

        try:
            t, _ = bench_py_import()
            per_rep["py_import"].append(t)
        except (ComponentError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))

        try:
            t, counts = bench_py_load()
            per_rep["py_load"].append(t)
            if "py_load_counts" in guards and guards["py_load_counts"] != counts:
                raise ComponentError(
                    f"py_load: model counts changed across reps "
                    f"{guards['py_load_counts']} -> {counts}"
                )
            guards["py_load_counts"] = counts
        except (ComponentError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))

        line = "  ".join(
            f"{name}={per_rep[name][-1]:.4f}s" for name in WEIGHTS if per_rep[name]
        )
        print(f"rep {rep}/{args.reps}: {line}", flush=True)

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    stats = {name: _stats(vals) for name, vals in per_rep.items()}
    composite_reps = [
        sum(WEIGHTS[name] * vals[i] for name, vals in per_rep.items())
        for i in range(args.reps)
    ]
    composite = _stats(composite_reps)

    print()
    print(f"{'component':<12}{'min':>10}{'median':>10}{'stdev':>10}{'weight':>9}")
    for name in WEIGHTS:
        s = stats[name]
        print(
            f"{name:<12}{s['min']:>10.4f}{s['median']:>10.4f}"
            f"{s['stdev']:>10.4f}{WEIGHTS[name]:>9.2f}"
        )
    cv = (composite["stdev"] / composite["mean"] * 100.0) if composite["mean"] else 0.0
    print()
    print(
        f"COMPOSITE (weighted seconds, lower=better): "
        f"mean={composite['mean']:.4f}  stdev={composite['stdev']:.4f}  "
        f"min={composite['min']:.4f}  cv={cv:.1f}%"
    )
    print(f"per-rep composites: {[round(x, 4) for x in composite_reps]}")
    print(
        f"determinism guards: netgen .net sha256 stable "
        f"({str(guards['netgen_sha'])[:16]}...); "
        f"ssa events {guards['ssa_events']} stable across {args.reps} reps; "
        f"ode final-state digests stable; "
        f"out_write hashes {
            {k: v[:16] + '...' for k, v in guards['out_write_hashes'].items()}
        } stable"
    )

    if args.json:
        try:
            load1_end = os.getloadavg()[0]
        except OSError:
            load1_end = float("nan")
        result = {
            "meta": {
                "git": git_rev,
                "host": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version.split()[0],
                "cpu_count": os.cpu_count(),
                "bng_cpp": str(bng_cpp),
                "extension": ext_path,
                "load1_start": load1_start,
                "load1_end": load1_end,
                "reps": args.reps,
                "weights": WEIGHTS,
                "v1_weights_superseded": V1_WEIGHTS,
                "ssa_base_seed": SSA_BASE_SEED,
                "ssa_batch": SSA_BATCH,
                "ode_models": ODE_MODELS,
                "note": "shared machine; quote load1_start with these timings; "
                "compare min and stdev, not single runs; ~11% "
                "cross-session drift is the resolution floor",
            },
            "components": stats,
            "composite": composite,
            "guards": {k: str(v) for k, v in guards.items()},
        }
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
