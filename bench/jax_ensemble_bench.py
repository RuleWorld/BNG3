#!/usr/bin/env python3
"""JAX-ensemble lane: classify what dominates a parameter scan / sensitivity run.

Motivation
----------
The opt-in-JAX hypothesis for scan/sensitivity ensembles is only viable if a
large share of end-to-end scan time is *pure-array* work that JAX could fuse.
This benchmark measures the split directly on a real model:

  scan_wall      parameter_scan(...) end-to-end (n grid points, ODE)
  post_array     ScanResult.final() + ScanResult.at_time() calls
                 (the pure-array post-processing JAX could replace)
  df_wall        ScanResult.to_dataframe() (needs pandas regardless)
  cpp_ode_wall   bare _bionetgen_cpp.simulate_ode loop, network cached
                 (per-point C++ solve — not batchable, not JAX-reachable)
  netgen_wall    bare _bionetgen_cpp.generate_network loop
                 (forced per point by _simulate_serial's network invalidation)
  model_sim      model.simulate() loop with cached network
                 (Python validation/dispatch + C++ solve)
  sens_wall      sensitivity_analysis(...) end-to-end
  matrix_wall    sensitivity matrix assembly arithmetic on same-shaped inputs
                 (the other pure-array JAX candidate)

Verdict arithmetic (classify_shares):
  bound = 1 / (1 - jax_addressable_share) is the fastest end-to-end scan
  conceivable if ALL JAX-addressable work became free and nothing else
  changed.  bound < 2.0 means the >=2x acceptance target is arithmetically
  unreachable: NO-WIN, with the per-point C++ share quoted.

All blocks are interleaved per round; per-block best-of-reps is reported with
mean/cv.  load1 is printed with every run.

Usage:
  PYTHONPATH=python:build/cpp python3 bench/jax_ensemble_bench.py \
      --model models/gene_expr_simple.bngl --param d1 --points 64 --reps 5 \
      --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path


def _strip_editable_meta_path() -> None:
    """Drop scikit-build editable finders that redirect `import bionetgen`.

    Same guard as bench/run_bench.py: the finder runs before sys.path, so a
    worktree benchmark must remove it or it scores another checkout's code.
    """
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if not type(finder).__module__.startswith("_editable")
    ]


def classify_shares(
    scan_wall: float,
    cpp_ode_wall: float,
    netgen_wall: float,
    post_array_wall: float,
    matrix_wall: float = 0.0,
) -> dict:
    """Pure share arithmetic for the NO-WIN/WIN decision. Times in seconds.

    ``max_speedup_if_jax_free`` assumes every JAX-addressable nanosecond
    vanishes while the C++ solve, network generation, and Python dispatch
    stay untouched — the ceiling for any opt-in JAX path that keeps the
    existing simulation semantics.
    """
    if scan_wall <= 0.0:
        raise ValueError("scan_wall must be positive")
    cpp_share = cpp_ode_wall / scan_wall
    net_share = netgen_wall / scan_wall
    post_share = post_array_wall / scan_wall
    matrix_share = matrix_wall / scan_wall
    jax_addressable = post_share + matrix_share
    if jax_addressable >= 1.0:
        bound = float("inf")
    else:
        bound = 1.0 / (1.0 - jax_addressable)
    return {
        "cpp_ode_share": cpp_share,
        "netgen_share": net_share,
        "python_residual_share": max(0.0, 1.0 - cpp_share - net_share),
        "post_array_share": post_share,
        "sensitivity_matrix_share": matrix_share,
        "jax_addressable_share": jax_addressable,
        "max_speedup_if_jax_free": bound,
        "reaches_2x": bound >= 2.0,
    }


def _best_stats(samples: list[float]) -> dict:
    return {
        "best_s": min(samples),
        "mean_s": statistics.fmean(samples),
        "cv": (
            (statistics.pstdev(samples) / statistics.fmean(samples))
            if len(samples) > 1 and statistics.fmean(samples) > 0
            else 0.0
        ),
        "samples_s": samples,
    }


def _post_array_time(scan, times: tuple[float, ...]) -> float:
    """Representative pure-array post-processing over a ScanResult."""
    t0 = time.perf_counter()
    for observable in scan.observable_names:
        scan.final(observable)
        for t in times:
            scan.at_time(t, observable)
    return time.perf_counter() - t0


def _jax_post_time(scan, times: tuple[float, ...]):
    """Same post-processing through JAX. Returns (seconds, values, np_values).

    Lazy import: jax is touched only here, i.e. only when the caller asks
    for the JAX comparison.  Returns None if jax is not installed.
    """
    try:
        import jax.numpy as jnp
    except ImportError:
        return None

    import numpy as np

    names = scan.observable_names
    finals_np = [scan.final(name) for name in names]
    at_np = [scan.at_time(t, name) for t in times for name in names]

    # Stack once (identical input materialisation for both sides is not the
    # point: the numpy numbers above already include their own extraction).
    time0 = np.asarray(scan.results[0].time, dtype=float)
    stacked = jnp.stack(
        [
            jnp.asarray(np.asarray(r.observables[names[0]], dtype=float))
            for r in scan.results
        ]
    )
    t_end = time0[-1]

    t0 = time.perf_counter()
    finals_j = [stacked[:, -1] for _ in names]
    at_j = [
        jnp.interp(t, jnp.asarray(scan.parameter_values), stacked[:, idx])
        for t in times
        for idx in range(len(time0) // 2, len(time0) // 2 + 1)
    ]
    # Final values per observable require per-observable stacks; do the full
    # job properly below (the loop above only touched observable 0).
    finals_j = []
    for name in names:
        st = jnp.stack(
            [
                jnp.asarray(np.asarray(r.observables[name], dtype=float))
                for r in scan.results
            ]
        )
        finals_j.append(st[:, -1])
    at_j = []
    for t in times:
        for name in names:
            st = jnp.stack(
                [
                    jnp.asarray(np.asarray(r.observables[name], dtype=float))
                    for r in scan.results
                ]
            )
            at_j.append(
                jnp.interp(
                    t, jnp.asarray(scan.parameter_values), st[:, len(st[0]) // 2]
                )
            )
    _ = t_end
    elapsed = time.perf_counter() - t0

    vals = (
        [np.asarray(v, dtype=float) for v in finals_j],
        [float(v) for v in at_j],
    )
    ref = (finals_np, at_np)
    return elapsed, vals, ref


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="models/gene_expr_simple.bngl")
    parser.add_argument("--param", default="d1")
    parser.add_argument("--points", type=int, default=64)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--t-end", type=float, default=100.0)
    parser.add_argument("--n-steps", type=int, default=100)
    parser.add_argument("--json", default=None, help="write full report here")
    parser.add_argument(
        "--skip-jax", action="store_true", help="skip the JAX comparison block"
    )
    args = parser.parse_args(argv)

    _strip_editable_meta_path()
    import numpy as np

    import bionetgen
    from bionetgen import _bionetgen_cpp as _cpp
    from bionetgen.scan import _simulate_serial, _simulation_kwargs

    model = bionetgen.load(args.model)
    if model._network is None:
        model.generate_network()
    network = model._network

    scan_kwargs = dict(
        parameter=args.param,
        min=0.1,
        max=1.0,
        n_points=args.points,
        method="ode",
        t_end=args.t_end,
        n_steps=args.n_steps,
    )
    sim_kwargs = _simulation_kwargs(
        method="ode",
        t_end=args.t_end,
        n_steps=args.n_steps,
        t_start=0.0,
        rtol=1e-8,
        atol=1e-12,
        seed=0,
        pla_config="",
        psa_poplevel=100.0,
        verbose=False,
        max_step=0.0,
        steady_state=False,
        steady_state_tol=None,
        stop_if="",
        sample_times=None,
        max_sim_steps=0,
        output_step_interval=0,
        sparse=False,
        check_product_scale=0.0,
    )
    bare_kwargs = dict(
        t_end=args.t_end,
        n_steps=args.n_steps,
        t_start=0.0,
        rtol=1e-8,
        atol=1e-12,
        method="cvode",
        max_step=0.0,
        steady_state=False,
        steady_state_tol=1e-12,
        stop_if="",
        sample_times=[],
        max_sim_steps=0,
        output_step_interval=0,
        sparse=False,
        check_product_scale=0.0,
    )
    at_times = tuple(float(v) for v in np.linspace(0.0, args.t_end, 5)[1:-1])

    def block_scan():
        return bionetgen.parameter_scan(model, **scan_kwargs)

    # A scan result is needed for the post-processing blocks; reuse one.
    reference_scan = block_scan()

    def block_post():
        return _post_array_time(reference_scan, at_times)

    def block_df():
        return reference_scan.to_dataframe()

    def block_cpp():
        t0 = time.perf_counter()
        for _ in range(args.points):
            _cpp.simulate_ode(model._model, network, **bare_kwargs)
        return time.perf_counter() - t0

    def block_netgen():
        t0 = time.perf_counter()
        for _ in range(args.points):
            _cpp.generate_network(model._model, max_iter=100)
        return time.perf_counter() - t0

    def block_model_sim():
        t0 = time.perf_counter()
        for _ in range(args.points):
            model.simulate(method="ode", t_end=args.t_end, n_steps=args.n_steps)
        return time.perf_counter() - t0

    def block_serial():
        t0 = time.perf_counter()
        for i in range(args.points):
            _simulate_serial(
                model,
                {args.param: 0.1 + i * 0.9 / max(args.points - 1, 1)},
                sim_kwargs,
            )
        return time.perf_counter() - t0

    # Sensitivity: same model, one parameter perturbed around its nominal.
    _ = model.get_parameter(args.param).value
    sens_params = [args.param]

    def block_sens():
        return bionetgen.sensitivity_analysis(
            model,
            parameters=sens_params,
            method="ode",
            t_end=args.t_end,
            n_steps=args.n_steps,
            delta=0.01,
        )

    def block_matrix():
        # Same arithmetic as sensitivity_analysis's assembly loop, on
        # same-shaped inputs: P x O pure-array work (the JAX candidate).
        p = len(sens_params)
        o = len(reference_scan.observable_names)
        plus = np.linspace(1.0, 2.0, p * o).reshape(p, o)
        minus = np.linspace(0.5, 1.5, p * o).reshape(p, o)
        base = np.linspace(2.0, 3.0, o)
        delta = 0.01
        t0 = time.perf_counter()
        matrix = np.zeros((p, o), dtype=float)
        for pi in range(p):
            npar = 1.0 + pi
            for oi, nval in enumerate(base):
                if nval == 0.0 or npar == 0.0:
                    matrix[pi, oi] = np.nan
                else:
                    matrix[pi, oi] = (
                        (plus[pi, oi] - minus[pi, oi])
                        / (2.0 * delta * npar)
                        * (npar / nval)
                    )
        return time.perf_counter() - t0

    blocks = {
        "scan_wall": block_scan,
        "post_array": block_post,
        "df_wall": block_df,
        "cpp_ode_wall": block_cpp,
        "netgen_wall": block_netgen,
        "model_sim_wall": block_model_sim,
        "serial_point_wall": block_serial,
        "sens_wall": block_sens,
        "matrix_wall": block_matrix,
    }

    # Warm-up pass so first-call costs (pybind caches, pandas import, ...)
    # do not land in the measured rounds.
    for fn in blocks.values():
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report, do not hide
            print(f"WARN: block warm-up failed: {exc}")

    load1_start = os.getloadavg()[0]
    samples: dict[str, list[float]] = {name: [] for name in blocks}
    for _ in range(args.reps):
        for name, fn in blocks.items():
            t0 = time.perf_counter()
            fn()
            samples[name].append(time.perf_counter() - t0)
    load1_end = os.getloadavg()[0]

    stats = {name: _best_stats(vals) for name, vals in samples.items()}
    shares = classify_shares(
        scan_wall=stats["scan_wall"]["best_s"],
        cpp_ode_wall=stats["cpp_ode_wall"]["best_s"],
        netgen_wall=stats["netgen_wall"]["best_s"],
        post_array_wall=stats["post_array"]["best_s"],
        matrix_wall=stats["matrix_wall"]["best_s"],
    )
    # With the measured JAX/numpy ratio on the array math, the realistic
    # end-to-end ceiling is even lower than the free-JAX bound.
    jax_block = None
    if not args.skip_jax:
        try:
            result = _jax_post_time(reference_scan, at_times)
        except ImportError:
            result = None
        if result is not None:
            elapsed, vals, ref = result
            np_finals, np_at = ref
            j_finals, j_at = vals
            max_abs = max(
                float(np.max(np.abs(a - b))) for a, b in zip(np_finals, j_finals)
            )
            denom = max(float(np.max(np.abs(a))) for a in np_finals)
            max_rel = max_abs / denom if denom else max_abs
            jax_ratio = elapsed / stats["post_array"]["best_s"]
            addr = shares["jax_addressable_share"]
            realistic = 1.0 / ((1.0 - addr) + addr / jax_ratio)
            jax_block = {
                "jax_post_s": elapsed,
                "jax_vs_numpy_ratio": jax_ratio,
                "max_abs_diff": max_abs,
                "max_rel_diff": max_rel,
                "end_to_end_bound_with_measured_ratio": realistic,
            }
            shares["max_speedup_with_measured_jax_ratio"] = realistic
            shares["reaches_2x_with_measured_ratio"] = realistic >= 2.0

    verdict = (
        "WIN-candidate"
        if shares.get("reaches_2x_with_measured_jax_ratio", shares["reaches_2x"])
        else "NO-WIN"
    )

    report = {
        "meta": {
            "model": args.model,
            "param": args.param,
            "points": args.points,
            "reps": args.reps,
            "t_end": args.t_end,
            "n_steps": args.n_steps,
            "load1_start": load1_start,
            "load1_end": load1_end,
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "blocks": stats,
        "shares": shares,
        "jax": jax_block,
        "verdict": verdict,
    }

    print(
        f"model={args.model} param={args.param} points={args.points} "
        f"reps={args.reps} load1={load1_start:.1f}->{load1_end:.1f}"
    )
    for name, st in stats.items():
        print(
            f"  {name:18s} best={st['best_s'] * 1e3:9.3f} ms  "
            f"mean={st['mean_s'] * 1e3:9.3f} ms  cv={st['cv'] * 100:5.1f}%"
        )
    print("shares (of scan_wall best):")
    for key in (
        "cpp_ode_share",
        "netgen_share",
        "python_residual_share",
        "post_array_share",
        "sensitivity_matrix_share",
        "jax_addressable_share",
    ):
        print(f"  {key:26s} {shares[key] * 100:6.2f}%")
    print(
        f"max speedup if JAX array math free: {shares['max_speedup_if_jax_free']:.3f}x"
    )
    if jax_block:
        print(
            "jax post vs numpy post: ratio="
            f"{jax_block['jax_vs_numpy_ratio']:.3f} "
            f"max_rel_diff={jax_block['max_rel_diff']:.3e} "
            "end-to-end bound="
            f"{jax_block['end_to_end_bound_with_measured_ratio']:.3f}x"
        )
    print(f"verdict: {verdict}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=float))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
