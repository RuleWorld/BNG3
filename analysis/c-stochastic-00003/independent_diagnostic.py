#!/usr/bin/env python3
"""Independent source-law diagnostic for SSTS stochastic/00003 at 98b310af.

Independently coded (not imported from the historical scripts). Samples the
exact conditional transition law of the subcritical linear birth-death process
X -> 2X at 1*X, X -> 0 at mu*X, X(0)=100, with common trajectories across the
50 official observation times. Scores the predeclared familywise statistic
F = max(|Z_mean|/3, |Y_sd|/5), the violation count, and a retrospective joint
SD-threshold exceedance. Includes an analytic-moment reproduction check and a
wrong-law (mu_wrong) power control.

This does not run BNG3 and cannot change the official SSTS verdict.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

LAMBDA = 1.0
INITIAL = 100
K = 40_000
STEPS = 50
MEAN_LIMIT = 3.0
SD_LIMIT = 5.0
SEED = 20_261_118  # new, predeclared seed
WRONG_MU = 1.05  # wrong-law power control
OBS_TIMES = (41, 43, 44, 45, 46)


def source_moments(t: int, mu: float) -> tuple[float, float]:
    """Exact mean and variance of X(t) for the linear birth-death law."""
    delta = mu - LAMBDA
    a = math.exp(-delta * t)
    mean = INITIAL * a
    var = INITIAL * (LAMBDA + mu) / delta * a * (1.0 - a)
    return mean, var


def transition_params(mu: float) -> tuple[float, float]:
    """Per-unit-time lineage survival prob and geometric tail parameter."""
    delta = mu - LAMBDA
    a = math.exp(-delta)
    denom = mu - LAMBDA * a
    p_survive = delta * a / denom
    q = LAMBDA * (1.0 - a) / denom
    return p_survive, q


def wilson(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    p = successes / trials if trials else 0.0
    d = 1.0 + z * z / trials if trials else 1.0
    c = (p + z * z / (2.0 * trials)) / d if trials else 0.0
    r = (
        z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials**2)) / d
        if trials
        else 0.0
    )
    return [max(0.0, c - r), min(1.0, c + r)]


def simulate_ensemble(
    rng: np.random.Generator, mu: float, route: str = "nb"
) -> dict[str, np.ndarray]:
    """One ensemble of K trajectories carried across t=1..STEPS."""
    p_survive, q = transition_params(mu)
    pop = np.full(K, INITIAL, dtype=np.int64)
    zs = np.empty(STEPS, dtype=np.float64)
    ys = np.empty(STEPS, dtype=np.float64)
    means = np.empty(STEPS, dtype=np.float64)
    variances = np.empty(STEPS, dtype=np.float64)
    for step in range(1, STEPS + 1):
        if route == "nb":
            survivors = rng.binomial(pop, p_survive)
            r = np.maximum(survivors, 1)
            extra = rng.negative_binomial(r, 1.0 - q)
            pop = survivors + np.where(survivors > 0, extra, 0)
        elif route == "geometric":
            # Independent coding path: per surviving lineage draw 1+Geometric.
            survivors = rng.binomial(pop, p_survive)
            npos = int(np.count_nonzero(survivors))
            pop = np.zeros_like(pop)
            if npos:
                pos = np.nonzero(survivors)[0]
                # numpy geometric(1-q) has support {1,2,...} and equals the
                # TOTAL descendants (ancestor + geometric extras) of one
                # surviving lineage. Sum one draw per surviving lineage.
                expanded = rng.geometric(1.0 - q, size=int(survivors[pos].sum()))
                offsets = np.concatenate([[0], np.cumsum(survivors[pos])])
                pop[pos] = np.add.reduceat(expanded, offsets[:-1])
        else:
            raise ValueError(route)
        m, v = source_moments(step, mu)
        sm = float(pop.mean())
        sv = float(pop.var())  # ddof=0, matches official checker
        means[step - 1] = sm
        variances[step - 1] = sv
        zs[step - 1] = (sm - m) / math.sqrt(v / K)
        ys[step - 1] = math.sqrt(K / 2.0) * (sv / v - 1.0)
    return {"z": zs, "y": ys, "mean": means, "var": variances}


def score(env: dict[str, np.ndarray]) -> dict[str, float]:
    z, y = env["z"], env["y"]
    viol = (np.abs(z) > MEAN_LIMIT) | (np.abs(y) > SD_LIMIT)
    return {
        "F": float(max(np.max(np.abs(z)) / MEAN_LIMIT, np.max(np.abs(y)) / SD_LIMIT)),
        "max_abs_z": float(np.max(np.abs(z))),
        "max_abs_y": float(np.max(np.abs(y))),
        "n_viol": int(viol.sum()),
        "n_sd_viol": int(np.count_nonzero(np.abs(y) > SD_LIMIT)),
        "n_mean_viol": int(np.count_nonzero(np.abs(z) > MEAN_LIMIT)),
    }


def observed_from_report(report_path: Path) -> dict[str, float]:
    report = json.loads(report_path.read_text())
    rec = next(
        x
        for x in report["records"]
        if x.get("category") == "stochastic" and x.get("id") == "00003"
    )
    oc = rec["official_conformance"]
    yv = oc["statistics"]["X-sd"]["sd_violations"]
    thresholds = {int(x["index"]): float(x["statistic"]) for x in yv}
    F = max(
        oc["statistics"]["X-mean"]["max_abs_mean_statistic"] / MEAN_LIMIT,
        oc["statistics"]["X-sd"]["max_abs_sd_statistic"] / SD_LIMIT,
    )
    return {
        "F": F,
        "n_viol": int(oc["violations"]),
        "max_abs_y": float(oc["statistics"]["X-sd"]["max_abs_sd_statistic"]),
        "max_abs_z": float(oc["statistics"]["X-mean"]["max_abs_mean_statistic"]),
        "sd_thresholds": thresholds,
    }


def run(report_path: Path, replicates: int, include_wrong: bool) -> dict:
    obs = observed_from_report(report_path)
    ref_sd_thr = np.array([obs["sd_thresholds"][t] for t in OBS_TIMES])

    # Analytic-moment reproduction check: ensemble-mean sample variance at each
    # time should track the exact variance within Monte Carlo error.
    rng = np.random.Generator(np.random.PCG64(SEED))
    Fs = np.empty(replicates)
    nv = np.empty(replicates, dtype=np.int64)
    maxy = np.empty(replicates)
    maxz = np.empty(replicates)
    J = np.empty(replicates, dtype=bool)
    var_ratio_at = {t: [] for t in OBS_TIMES}
    for i in range(replicates):
        env = simulate_ensemble(rng, 1.1, route="nb")
        s = score(env)
        Fs[i], nv[i] = s["F"], s["n_viol"]
        maxy[i], maxz[i] = s["max_abs_y"], s["max_abs_z"]
        J[i] = bool(np.all(env["y"][np.array(OBS_TIMES) - 1] >= ref_sd_thr))
        for t in OBS_TIMES:
            var_ratio_at[t].append(float(env["var"][t - 1] / source_moments(t, 1.1)[1]))
    # Distinct geometric-route cross-check for one ensemble.
    rng2 = np.random.Generator(np.random.PCG64(SEED + 7))
    a_nb = simulate_ensemble(np.random.Generator(np.random.PCG64(SEED + 7)), 1.1, "nb")
    a_geo = simulate_ensemble(rng2, 1.1, "geometric")
    route_agree = bool(np.allclose(a_nb["mean"], a_geo["mean"], rtol=0.05, atol=0.5))

    n_F = int(np.count_nonzero(Fs >= obs["F"]))
    n_nv = int(np.count_nonzero(nv >= obs["n_viol"]))
    n_J = int(np.count_nonzero(J))
    result = {
        "scope": "independent source-law diagnostic; official verdict unchanged",
        "observed": obs,
        "config": {
            "replicates": replicates,
            "trajectories": K,
            "steps": STEPS,
            "seed": SEED,
            "mu": 1.1,
            "wrong_mu": WRONG_MU,
            "rng": "numpy PCG64",
            "variance_ddof": 0,
            "statistic": "F=max(|Z|/3,|Y|/5); Y=sqrt(K/2)*(S^2/sigma^2-1)",
        },
        "identity_checks": {
            "geometric_route_matches_nb": route_agree,
            "ensemble_mean_var_ratio_range": {
                str(t): [
                    float(np.mean(var_ratio_at[t])),
                    float(np.std(var_ratio_at[t])),
                ]
                for t in OBS_TIMES
            },
        },
        "null": {
            "F_mean": float(Fs.mean()),
            "F_sd": float(Fs.std(ddof=1)),
            "F_p95": float(np.percentile(Fs, 95)),
            "max_y_mean": float(maxy.mean()),
            "max_y_sd": float(maxy.std(ddof=1)),
            "max_y_p95": float(np.percentile(maxy, 95)),
            "n_viol_mean": float(nv.mean()),
            "n_viol_sd": float(nv.std(ddof=1)),
            "n_viol_p95": float(np.percentile(nv, 95)),
        },
        "tail_probabilities": {
            "P_F_ge_observed": n_F / replicates,
            "P_F_ge_observed_wilson95": wilson(n_F, replicates),
            "P_nviol_ge_observed": n_nv / replicates,
            "P_nviol_ge_observed_wilson95": wilson(n_nv, replicates),
            "P_joint_sd_thresholds": n_J / replicates,
            "P_joint_sd_thresholds_wilson95": wilson(n_J, replicates),
        },
        "decision_inputs": {"alpha_familywise": 0.01},
    }
    if include_wrong:
        rngw = np.random.Generator(np.random.PCG64(SEED + 1))
        wF, wnv = [], []
        for _ in range(replicates):
            s = score(simulate_ensemble(rngw, WRONG_MU, "nb"))
            wF.append(s["F"])
            wnv.append(s["n_viol"])
        wF = np.asarray(wF)
        wnv = np.asarray(wnv)
        nwF = int(np.count_nonzero(wF >= obs["F"]))
        result["wrong_law_control"] = {
            "mu": WRONG_MU,
            "F_mean": float(wF.mean()),
            "F_p05": float(np.percentile(wF, 5)),
            "n_viol_mean": float(wnv.mean()),
            "P_wrong_F_ge_observed": nwF / replicates,
            "P_wrong_F_ge_observed_wilson95": wilson(nwF, replicates),
        }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--replicates", type=int, required=True)
    ap.add_argument("--no-wrong", action="store_true")
    ap.add_argument("--json", type=Path, required=True)
    a = ap.parse_args()
    r = run(a.report, a.replicates, include_wrong=not a.no_wrong)
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(json.dumps(r, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: r[k] for k in ("null", "tail_probabilities")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
