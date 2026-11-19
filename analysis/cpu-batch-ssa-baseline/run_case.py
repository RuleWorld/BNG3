#!/usr/bin/env python3
"""Replayable native CPU batch-SSA immigration-death ensemble baseline.

Executes the predeclared plan in PREDECLARED_PLAN.md. Uses the maintained
public entry point bionetgen._bionetgen_cpp.simulate_batch_ssa_cpu, an
independent closed-form Poisson law as correctness oracle, interleaved A/A
runs of the identical build as a noise baseline, and records host/compiler/
revision/binary identity plus peak RSS with units and collection method.

Only analytic laws are consulted for correctness; no BNG3/native engine is
used as the oracle. See PREDECLARED_PLAN.md. This is a baseline task, not a
performance-tuning or product change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "build" / "cpp"))
sys.path.insert(0, str(ROOT / "python"))

import numpy as np  # noqa: E402

try:
    from bionetgen import _bionetgen_cpp as cpp  # maintained public entry point
except ImportError:  # bare extension on CI runners without an installed package
    import _bionetgen_cpp as cpp  # type: ignore

# ---- predeclared constants (see PREDECLARED_PLAN.md) -----------------------
K_ON = 2.0
K_OFF = 0.5
LAMBDA_INF = K_ON / K_OFF  # 4.0
INITIAL_POP = 0
SEED = 20261119
T_END = 20.0
N_STEPS = 20
BATCH = 20000
THREADS_PRIMARY = 1
THREADS_SUPPLEMENTAL = 0
WARMUPS = 2
ROUNDS = 7
ALPHA = 1e-3  # KS_ALPHA (tests/test_batch_ssa_statistical_parity.py)
MEAN_Z_LIMIT = 5.0  # MEAN_Z_LIMIT (same file)
VARIANCE_RATIO_MIN = 0.90  # VARIANCE_RATIO_MIN (same file)
VARIANCE_RATIO_MAX = 1.10  # VARIANCE_RATIO_MAX (same file)
HOST_RESOLUTION_FLOOR = 0.11  # ~11% resolution floor (bench/README.md)
WRONG_LAMBDA = 6.0

MODEL = """begin model
begin parameters
k_on {kon}
k_off {koff}
end parameters
begin molecule types
A()
end molecule types
begin seed species
A() {pop}
end seed species
begin observables
Molecules CountA A()
end observables
begin reaction rules
0 -> A() k_on
A() -> 0 k_off
end reaction rules
end model
""".format(kon=K_ON, koff=K_OFF, pop=INITIAL_POP)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(p: Path) -> str:
    return _sha256_bytes(p.read_bytes())


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _cpu_model() -> str:
    if sys.platform == "darwin":
        try:
            return subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unavailable"


def _compiler() -> dict:
    cache = ROOT / "build" / "CMakeCache.txt"
    cxx = "unavailable"
    if cache.exists():
        for line in cache.read_text().splitlines():
            if line.startswith("CMAKE_CXX_COMPILER:"):
                cxx = line.split("=", 1)[1].strip()
    version = ""
    if cxx != "unavailable":
        try:
            version = subprocess.run(
                [cxx, "--version"], capture_output=True, text=True, check=True
            ).stdout.splitlines()[0].strip()
        except (OSError, subprocess.CalledProcessError, IndexError):
            pass
    return {"cxx": cxx, "version": version}


def _peak_rss() -> dict:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS/Darwin ru_maxrss is bytes; Linux reports KiB.
    unit = "bytes" if sys.platform == "darwin" else "KiB"
    rss_bytes = int(raw) if sys.platform == "darwin" else int(raw) * 1024
    return {
        "ru_maxrss_raw": int(raw),
        "ru_maxrss_unit": unit,
        "peak_rss_bytes": rss_bytes,
        "collection_method": (
            "resource.getrusage(RUSAGE_SELF).ru_maxrss at end of replay process "
            "(bytes on Darwin, KiB on Linux converted to bytes); max over process "
            "lifetime"
        ),
    }


def _law(t):
    return LAMBDA_INF * (1.0 - math.exp(-K_OFF * float(t)))


def _poisson_cdf(lam: float, k: np.ndarray) -> np.ndarray:
    """Exact Poisson CDF from the pmf recursion; independent of BNG3."""
    return np.array(
        [
            sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(int(x) + 1))
            for x in k
        ]
    )


def _simulate(model, network, *, threads: int, base_seed: int = SEED) -> dict:
    return cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=BATCH,
        t_end=T_END,
        n_steps=N_STEPS,
        threads=threads,
        base_seed=base_seed,
    )


def _check_correctness(res: dict) -> dict:
    t = np.asarray(res["time"], dtype=float)
    mean = np.asarray(res["observable_means"]["CountA"], dtype=float)
    sd = np.asarray(res["observable_stds"]["CountA"], dtype=float)
    var = sd**2  # batch stds are ddof=0 over raw trajectory samples

    # transient mean: one-sample Z against known law, using the project MEAN_Z_LIMIT
    zs, allowed, means, lams = [], [], [], []
    for i in range(len(t)):
        if t[i] <= 0:
            continue
        se = sd[i] / math.sqrt(BATCH)
        lam = _law(t[i])
        z = (mean[i] - lam) / se if se > 0 else 0.0
        zs.append(abs(z))
        allowed.append(MEAN_Z_LIMIT)
        means.append(float(mean[i]))
        lams.append(float(lam))
    transient_mean_ok = bool(max(zs) <= MEAN_Z_LIMIT) if zs else False

    # transient variance: ratio band from the CPU reference gate
    ratios = []
    for i in range(len(t)):
        if t[i] <= 0:
            continue
        ratios.append(float(var[i] / _law(t[i])))
    transient_variance_ok = bool(
        ratios and all(VARIANCE_RATIO_MIN <= r <= VARIANCE_RATIO_MAX for r in ratios)
    )

    # stationary distribution: DKW vs Poisson(4) at final time
    samples = np.asarray(res["final_observables"])[:, 0].astype(int)
    kgrid = np.arange(0, int(samples.max()) + 1)
    empirical = np.array([(samples <= k).mean() for k in kgrid])
    exact = _poisson_cdf(LAMBDA_INF, kgrid)
    dkw = math.sqrt(math.log(2.0 / ALPHA) / (2.0 * BATCH))
    ks = float(np.max(np.abs(empirical - exact)))
    stationary_ok = bool(ks <= dkw)
    wrong_exact = _poisson_cdf(WRONG_LAMBDA, kgrid)
    ks_wrong = float(np.max(np.abs(empirical - wrong_exact)))
    wrong_law_rejected = bool(ks_wrong > dkw)

    invariant_ok = bool(
        np.all(samples >= 0) and np.all(np.asarray(res["final_species"]) >= 0)
    )
    all_passed = bool(
        transient_mean_ok
        and transient_variance_ok
        and stationary_ok
        and wrong_law_rejected
        and invariant_ok
    )
    return {
        "transient_mean": {
            "max_abs_z": float(max(zs)) if zs else None,
            "z_limit": MEAN_Z_LIMIT,
            "max_abs_error": float(max(abs(m - l) for m, l in zip(means, lams))),
            "passed": transient_mean_ok,
        },
        "transient_variance": {
            "min_ratio": float(min(ratios)) if ratios else None,
            "max_ratio": float(max(ratios)) if ratios else None,
            "band": [VARIANCE_RATIO_MIN, VARIANCE_RATIO_MAX],
            "passed": transient_variance_ok,
        },
        "stationary": {
            "t_end": float(t[-1]),
            "sample_mean": float(samples.mean()),
            "sample_var": float(samples.var()),
            "poisson_lambda": LAMBDA_INF,
            "ks_stat": ks,
            "dkw_bound": dkw,
            "alpha": ALPHA,
            "passed": stationary_ok,
        },
        "wrong_law_control": {
            "law": f"Poisson({WRONG_LAMBDA})",
            "ks_stat": ks_wrong,
            "dkw_bound": dkw,
            "rejected": wrong_law_rejected,
        },
        "invariants": {"nonnegative": invariant_ok},
        "all_passed": all_passed,
    }


def _timing(res: dict) -> dict:
    return {
        "model_prep_time_ms": float(res["model_prep_time_ms"]),
        "sim_time_ms": float(res["sim_time_ms"]),
        "total_wall_time_ms": float(res["total_wall_time_ms"]),
        "trajectories_per_sec_sim": float(res["trajectories_per_sec_sim"]),
        "events_per_sec_sim": float(res["events_per_sec_sim"]),
        "total_events": int(res["total_events"]),
    }


def _median(vals):
    a = sorted(vals)
    n = len(a)
    return a[n // 2] if n % 2 else 0.5 * (a[n // 2 - 1] + a[n // 2])


def run() -> dict:
    model = cpp.parse_string(MODEL)
    network = cpp.generate_network(model)

    # correctness (also the first invocation, before warmups)
    correctness_res = _simulate(model, network, threads=THREADS_PRIMARY)
    observable_names = list(correctness_res.get("observable_names", []))
    if observable_names != ["CountA"]:
        raise RuntimeError(f"unexpected observables: {observable_names}")
    correctness = _check_correctness(correctness_res)

    # untimed warmups
    for _ in range(WARMUPS):
        _simulate(model, network, threads=THREADS_PRIMARY)

    # interleaved A/A rounds (identical build), alternating arm order
    rounds = []
    for r in range(1, ROUNDS + 1):
        order = ["A", "B"] if r % 2 == 1 else ["B", "A"]
        results = {arm: _timing(_simulate(model, network, threads=THREADS_PRIMARY))
                   for arm in order}
        rounds.append({"round": r, "order": order, "A": results["A"], "B": results["B"]})

    def diffs(key):
        out = []
        for rd in rounds:
            a, b = rd["A"][key], rd["B"][key]
            denom = (a + b) / 2.0
            out.append((a - b) / denom if denom else 0.0)
        return out

    all_sim = [rd[arm]["trajectories_per_sec_sim"] for rd in rounds for arm in ("A", "B")]
    all_prep = [rd[arm]["model_prep_time_ms"] for rd in rounds for arm in ("A", "B")]
    sim_mean = float(np.mean(all_sim))
    prep_mean = float(np.mean(all_prep))
    sim_cv = float(np.std(all_sim) / sim_mean) if sim_mean else 0.0
    prep_cv = float(np.std(all_prep) / prep_mean) if prep_mean else 0.0
    prep_diffs, sim_diffs = diffs("model_prep_time_ms"), diffs("trajectories_per_sec_sim")
    noise = {
        "rounds": rounds,
        "warmups": WARMUPS,
        "measurement_repetitions": 2 * ROUNDS,
        "model_prep_time_ms": {
            "mean": prep_mean,
            "per_round_signed_rel_diff": prep_diffs,
            "median_signed_rel_diff": _median(prep_diffs),
            "max_abs_rel_diff": max(abs(x) for x in prep_diffs),
            "cv_across_reps": prep_cv,
        },
        "trajectories_per_sec_sim": {
            "mean": sim_mean,
            "per_round_signed_rel_diff": sim_diffs,
            "median_signed_rel_diff": _median(sim_diffs),
            "max_abs_rel_diff": max(abs(x) for x in sim_diffs),
            "cv_across_reps": sim_cv,
        },
        "event_count_mismatch_rounds": [
            rd["round"] for rd in rounds
            if rd["A"]["total_events"] != rd["B"]["total_events"]
        ],
        "host_resolution_floor": HOST_RESOLUTION_FLOOR,
    }
    # Predeclared plan reports startup and warm throughput separately: startup
    # (model_prep_time_ms) is sub-millisecond and expected to be noisy in
    # relative terms; warm trajectory throughput is the stable statistic.
    def verdict(max_abs: float) -> str:
        return (
            "noisy: A/A spread exceeds host resolution floor"
            if max_abs > HOST_RESOLUTION_FLOOR
            else "within host resolution floor (A/A difference is noise, not a code effect)"
        )

    noise["assessments"] = {
        key: verdict(noise[key]["max_abs_rel_diff"])
        for key in ("model_prep_time_ms", "trajectories_per_sec_sim")
    }
    noise["assessment"] = "; ".join(
        f"{key}: {v}" for key, v in noise["assessments"].items()
    )

    # one supplemental representative multi-core observation (not part of A/A)
    supplemental = _timing(_simulate(model, network, threads=THREADS_SUPPLEMENTAL))
    supplemental["threads"] = THREADS_SUPPLEMENTAL

    so = sorted(ROOT.glob("build/cpp/_bionetgen_cpp*.so"))
    ext_sha = _sha256(so[0]) if so else "unavailable"
    rss = _peak_rss()

    return {
        "case": "native_cpu_batch_ssa_immigration_death_baseline",
        "predeclared_plan_sha256": _sha256(Path(__file__).with_name("PREDECLARED_PLAN.md")),
        "revision": os.environ.get("BNG3_SOURCE_REVISION") or _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "engine_source_revision": _git("merge-base", "HEAD", "origin/main"),
        "engine_source_note": (
            "Revision of origin/main from which the native C++/Python extension "
            "in build/cpp was compiled. This case commit changes only analysis/ "
            "files, so the benchmarked engine source is identical to that revision."
        ),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "cpu_model": _cpu_model(),
            "cpu_count": os.cpu_count(),
            "compiler": _compiler(),
            "extension": str(so[0]) if so else "unavailable",
            "extension_sha256": ext_sha,
            "entry_point": "bionetgen._bionetgen_cpp.simulate_batch_ssa_cpu",
        },
        "predeclared": {
            "k_on": K_ON,
            "k_off": K_OFF,
            "lambda_inf": LAMBDA_INF,
            "initial_population": INITIAL_POP,
            "base_seed": SEED,
            "horizon_s": T_END,
            "n_steps": N_STEPS,
            "batch_size": BATCH,
            "threads_primary": THREADS_PRIMARY,
            "threads_supplemental": THREADS_SUPPLEMENTAL,
            "warmups": WARMUPS,
            "rounds": ROUNDS,
            "alpha": ALPHA,
            "mean_z_limit": MEAN_Z_LIMIT,
            "variance_ratio_band": [VARIANCE_RATIO_MIN, VARIANCE_RATIO_MAX],
            "law": "A(t) ~ Poisson(4*(1-exp(-0.5t))); mean=variance=lambda(t)",
        },
        "correctness": correctness,
        "noise_baseline": noise,
        "supplemental_multicore": supplemental,
        "peak_rss": rss,
        "replay_command": os.environ.get("BNG3_REPLAY_COMMAND", "see PREDECLARED_PLAN.md"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, required=True, help="artifact destination")
    args = ap.parse_args()
    t0 = time.time()
    result = run()
    result["script_wall_s"] = time.time() - t0
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "revision": result["revision"],
        "correctness_all_passed": result["correctness"]["all_passed"],
        "noise_assessment": result["noise_baseline"]["assessment"],
        "peak_rss_bytes": result["peak_rss"]["peak_rss_bytes"],
        "artifact": str(args.json),
    }, indent=2))
    return 0 if result["correctness"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
