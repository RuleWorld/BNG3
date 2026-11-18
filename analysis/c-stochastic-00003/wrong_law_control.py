#!/usr/bin/env python3
"""Corrected wrong-law power control for the 00003 source-law diagnostic.

Scoring an ensemble generated under a WRONG law against the TRUE law's
reference is what a product defect would look like to the official comparator.
The first implementation accidentally scored the wrong ensemble against its
own moments; this script corrects that. See PLAN_ADDENDUM.md.
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np

from independent_diagnostic import (
    K,
    STEPS,
    MEAN_LIMIT,
    SD_LIMIT,
    SEED,
    WRONG_MU,
    source_moments,
    transition_params,
    wilson,
)


def score_against_true_reference(
    ensemble: dict,
) -> dict:
    z = ensemble["z_true"]
    y = ensemble["y_true"]
    viol = (np.abs(z) > MEAN_LIMIT) | (np.abs(y) > SD_LIMIT)
    return {
        "F": float(max(np.max(np.abs(z)) / MEAN_LIMIT, np.max(np.abs(y)) / SD_LIMIT)),
        "n_viol": int(viol.sum()),
        "max_abs_z": float(np.max(np.abs(z))),
        "max_abs_y": float(np.max(np.abs(y))),
    }


def run(replicates: int, mu_wrong: float, seed: int) -> dict:
    p_survive, q = transition_params(mu_wrong)
    rng = np.random.Generator(np.random.PCG64(seed))
    Fs = np.empty(replicates)
    nv = np.empty(replicates, dtype=np.int64)
    for i in range(replicates):
        pop = np.full(K, 100, dtype=np.int64)
        z = np.empty(STEPS)
        y = np.empty(STEPS)
        for step in range(1, STEPS + 1):
            survivors = rng.binomial(pop, p_survive)
            extra = rng.negative_binomial(np.maximum(survivors, 1), 1.0 - q)
            pop = survivors + np.where(survivors > 0, extra, 0)
            m_true, v_true = source_moments(step, 1.1)  # TRUE reference
            z[step - 1] = (
                math.sqrt(K) * (float(pop.mean()) - m_true) / math.sqrt(v_true)
            )
            y[step - 1] = math.sqrt(K / 2.0) * (float(pop.var()) / v_true - 1.0)
        s = score_against_true_reference({"z_true": z, "y_true": y})
        Fs[i], nv[i] = s["F"], s["n_viol"]
    # Observed F_obs from the retained report (matches c-diagnostic.json).
    F_obs = 1.71332478721316
    n_ge = int(np.count_nonzero(Fs >= F_obs))
    return {
        "purpose": "power control: wrong law mu vs true reference mu=1.1",
        "mu_wrong": mu_wrong,
        "mu_reference": 1.1,
        "replicates": replicates,
        "seed": seed,
        "trajectories": K,
        "F_obs": F_obs,
        "F_mean": float(Fs.mean()),
        "F_p05": float(np.percentile(Fs, 5)),
        "F_p95": float(np.percentile(Fs, 95)),
        "n_viol_mean": float(nv.mean()),
        "n_viol_p95": float(np.percentile(nv, 95)),
        "P_wrong_F_ge_F_obs": n_ge / replicates,
        "P_wrong_F_ge_F_obs_wilson95": wilson(n_ge, replicates),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicates", type=int, default=300)
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    r = run(a.replicates, WRONG_MU, SEED + 1)
    with open(a.json, "w") as f:
        json.dump(r, f, indent=2, sort_keys=True)
    print(
        json.dumps(
            {k: r[k] for k in ("F_mean", "F_p05", "n_viol_mean", "P_wrong_F_ge_F_obs")},
            indent=2,
        )
    )
