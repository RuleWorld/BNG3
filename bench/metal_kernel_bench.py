#!/usr/bin/env python3
"""Interleaved A/B instrument for the Metal batch-SSA GPU path.

Measures what benchmark_gpu_batch_ssa.py measures (the engine's in-run
sim timer) but with:

  * A/B arms run as alternating child processes in ONE session, so host
    drift cancels out (A/B or B/A order flips every round);
  * per-phase breakdown (model prep, sim, h2d, d2h, wall) so a sim-time
    change can be attributed to the dispatch rather than the readback;
  * trajectory identity: sha256 over event_counts, final_species,
    final_observables and the observable mean/std grids for a fixed
    baseSeed, compared across arms and across reps. On Metal a change
    must keep every hash equal unless it is a documented intentional
    stream change.

Usage:
  PYTHONPATH= python3 bench/metal_kernel_bench.py \
      --a /path/to/baseline/tree --b /path/to/candidate/tree \
      --model egfr_net --batch 10000 --rounds 5 --json out.json

Each arm child imports its own tree's extension in a fresh interpreter,
so the two arms never share a binary. Exit is non-zero if any arm's
outputs differ from each other (identity failure) or a child errors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS = {
    "isomerization": ("models/isomerization.bngl", 20.0),
    "gene_expr_simple": ("models/gene_expr_simple.bngl", 500.0),
    "toy_jim": ("models/toy-jim.bngl", 50.0),
    "egfr_net": ("models/performance_test_models/egfr_net.bngl", 0.02),
}


def _sha(arr) -> str:
    return hashlib.sha256(arr.tobytes()).hexdigest()


def run_child(tree: str, model_id: str, batch: int, seed: int, n_steps: int,
              backend: str) -> dict:
    """Run one GPU simulation in this process against `tree`'s extension."""
    sys.path.insert(0, os.path.join(tree, "build", "cpp"))
    sys.path.insert(0, os.path.join(tree, "python"))
    try:
        import _bionetgen_cpp as cpp
    except ImportError:
        from bionetgen import _bionetgen_cpp as cpp

    path, t_end = MODELS[model_id]
    abs_path = path if os.path.isabs(path) else os.path.join(tree, path)
    model = cpp.parse_file(abs_path)
    net = cpp.generate_network(model)
    gpu = cpp.simulate_batch_ssa_gpu(
        model, net,
        batch_size=batch,
        t_end=t_end,
        n_steps=n_steps,
        base_seed=seed,
        backend=backend,
    )
    out = {
        "tree": tree,
        "model": model_id,
        "batch": batch,
        "seed": seed,
        "num_species": net.num_species,
        "num_reactions": net.num_reactions,
        "backend": gpu.get("backend", "?"),
        "model_prep_ms": gpu["model_prep_time_ms"],
        "sim_ms": gpu["sim_time_ms"],
        "h2d_ms": gpu["h2d_transfer_ms"],
        "d2h_ms": gpu["d2h_transfer_ms"],
        "wall_ms": gpu["total_wall_time_ms"],
        "total_events": int(gpu["total_events"]),
        "sha_event_counts": _sha(gpu["event_counts"]),
        "sha_final_species": _sha(gpu["final_species"]),
    }
    if "final_observables" in gpu:
        out["sha_final_observables"] = _sha(gpu["final_observables"])
        means = gpu["observable_means"]
        stds = gpu["observable_stds"]
        h = hashlib.sha256()
        for name in sorted(means.keys()):
            h.update(name.encode())
            h.update(means[name].tobytes())
            h.update(stds[name].tobytes())
        out["sha_mean_std"] = h.hexdigest()
    return out


def spawn_child(tree: str, model_id: str, batch: int, seed: int, n_steps: int,
                backend: str) -> dict:
    cmd = [
        sys.executable, os.path.abspath(__file__),
        "--child", tree,
        "--model", model_id,
        "--batch", str(batch),
        "--seed", str(seed),
        "--n-steps", str(n_steps),
        "--backend", backend,
    ]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    # A scikit-build editable install can redirect `import bionetgen` to
    # another checkout; strip its meta_path hook the way bench/run_bench.py does.
    env["SKBUILD_EDITABLE_SKIP"] = "1"
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                          cwd=REPO_ROOT, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"child failed (rc={proc.returncode}) tree={tree} model={model_id}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    lines = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"child produced no JSON\n{proc.stdout}\n{proc.stderr}")
    return json.loads(lines[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", help="baseline tree root")
    ap.add_argument("--b", help="candidate tree root (default: this tree)")
    ap.add_argument("--model", default="egfr_net",
                    choices=sorted(MODELS.keys()))
    ap.add_argument("--batch", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=300)
    ap.add_argument("--n-steps", type=int, default=10)
    ap.add_argument("--backend", default="metal")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--json", help="write full results here")
    # internal child mode
    ap.add_argument("--child", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child:
        res = run_child(args.child, args.model, args.batch, args.seed,
                        args.n_steps, args.backend)
        print(json.dumps(res))
        return 0

    if not args.a:
        ap.error("--a (baseline tree) is required")
    tree_b = args.b or REPO_ROOT

    load1_start = os.getloadavg()[0]
    print(f"model={args.model} batch={args.batch} seed={args.seed} "
          f"rounds={args.rounds} load1={load1_start:.1f}")
    print(f"A={args.a}\nB={tree_b}")

    rounds = []
    for r in range(args.rounds):
        order = ("a", "b") if r % 2 == 0 else ("b", "a")
        row = {"round": r, "order": order}
        for arm in order:
            tree = args.a if arm == "a" else tree_b
            row[arm] = spawn_child(tree, args.model, args.batch, args.seed,
                                   args.n_steps, args.backend)
            print(f"  round {r} {arm.upper()}: sim={row[arm]['sim_ms']:.3f} ms "
                  f"prep={row[arm]['model_prep_ms']:.3f} "
                  f"d2h={row[arm]['d2h_ms']:.3f} wall={row[arm]['wall_ms']:.3f} "
                  f"events={row[arm]['total_events']}")
        rounds.append(row)

    load1_end = os.getloadavg()[0]

    sims_a = [row["a"]["sim_ms"] for row in rounds]
    sims_b = [row["b"]["sim_ms"] for row in rounds]
    med_a = statistics.median(sims_a)
    med_b = statistics.median(sims_b)
    delta = (med_b - med_a) / med_a * 100.0

    # Identity: every run of either arm must hash identically for a fixed seed.
    id_keys = sorted(k for k in rounds[0]["a"] if k.startswith("sha_"))
    identity_ok = True
    identity_detail = {}
    for k in id_keys:
        vals = {row[arm].get(k) for row in rounds for arm in ("a", "b")}
        vals.discard(None)
        identity_detail[k] = sorted(vals)
        if len(vals) != 1:
            identity_ok = False

    ev_a = {row["a"]["total_events"] for row in rounds}
    ev_b = {row["b"]["total_events"] for row in rounds}
    if ev_a != ev_b or len(ev_a) != 1:
        identity_ok = False

    def cv(vals):
        m = statistics.mean(vals)
        return statistics.pstdev(vals) / m * 100.0 if m else float("nan")

    report = {
        "model": args.model,
        "batch": args.batch,
        "seed": args.seed,
        "rounds": args.rounds,
        "load1_start": load1_start,
        "load1_end": load1_end,
        "a_tree": args.a,
        "b_tree": tree_b,
        "sim_ms_a": sims_a,
        "sim_ms_b": sims_b,
        "sim_median_a": med_a,
        "sim_median_b": med_b,
        "sim_delta_pct": delta,
        "cv_a_pct": cv(sims_a),
        "cv_b_pct": cv(sims_b),
        "prep_median_a": statistics.median([r["a"]["model_prep_ms"] for r in rounds]),
        "prep_median_b": statistics.median([r["b"]["model_prep_ms"] for r in rounds]),
        "d2h_median_a": statistics.median([r["a"]["d2h_ms"] for r in rounds]),
        "d2h_median_b": statistics.median([r["b"]["d2h_ms"] for r in rounds]),
        "wall_median_a": statistics.median([r["a"]["wall_ms"] for r in rounds]),
        "wall_median_b": statistics.median([r["b"]["wall_ms"] for r in rounds]),
        "total_events_a": sorted(ev_a),
        "total_events_b": sorted(ev_b),
        "identity_ok": identity_ok,
        "identity_hashes": identity_detail,
        "rounds_data": rounds,
    }
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)

    print(f"\nsim_ms A (baseline) median={med_a:.3f} cv={report['cv_a_pct']:.1f}% "
          f"samples={[round(x, 3) for x in sims_a]}")
    print(f"sim_ms B (candidate) median={med_b:.3f} cv={report['cv_b_pct']:.1f}% "
          f"samples={[round(x, 3) for x in sims_b]}")
    print(f"delta = {delta:+.1f}%  (load1={load1_start:.1f}-{load1_end:.1f})")
    print(f"identity_ok = {identity_ok}")
    return 0 if identity_ok else 2


if __name__ == "__main__":
    sys.exit(main())
