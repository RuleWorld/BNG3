#!/usr/bin/env python3
"""Execute the predeclared installed CPU JAX SSA immigration-death case.

Only analytic laws (transient mean, stationary Poisson CDF, DKW bound) are used
as oracles; no BNG3/native simulation is consulted. See PREDECLARED_PLAN.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

if sys.platform == "darwin" and "JAX_PLATFORMS" not in os.environ:
    os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ssa

K_ON = 2.0
K_OFF = 0.5
LAMBDA = K_ON / K_OFF  # 4.0
SEED = 20261118
ALPHA = 0.001
REVISION = "0d42c6666525debeed61a6e7731fedefd1196df6"

MODEL = """begin model
begin parameters
k_on {kon}
k_off {koff}
end parameters
begin molecule types
A()
end molecule types
begin seed species
A() 0
end seed species
begin observables
Molecules CountA A()
end observables
begin reaction rules
0 -> A() k_on
A() -> 0 k_off
end reaction rules
end model
""".format(kon=K_ON, koff=K_OFF)


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _poisson_cdf(lam: float, k: np.ndarray) -> np.ndarray:
    """Exact Poisson CDF from the pmf recursion, independent of BNG3."""
    return np.array(
        [
            sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(int(x) + 1))
            for x in k
        ]
    )


def run() -> dict:
    import jax

    devices = [str(d) for d in jax.devices()]
    model = cpp.parse_string(MODEL)
    network = cpp.generate_network(model)
    flat = cpp.jax_ssa_flatten(model, network)
    rate_constants = [float(x) for x in flat["rate_constants"]]

    # --- transient mean check (predeclared) -------------------------------
    tr = jax_ssa.simulate(
        model, network, batch_size=4096, t_end=20.0, n_steps=20, base_seed=SEED
    )
    times = np.asarray(tr["time"])
    mean = np.asarray(tr["observable_means"]["CountA"])
    sd = np.asarray(tr["observable_stds"]["CountA"])
    se = sd / math.sqrt(4096)
    expected_mean = LAMBDA * (1.0 - np.exp(-K_OFF * times))
    err = np.abs(mean - expected_mean)
    allowed = 3.0 * se + 0.05
    transient_ok = bool(np.all(err <= allowed))

    # --- stationary distribution check (predeclared) ----------------------
    st = jax_ssa.simulate(
        model, network, batch_size=8192, t_end=20.0, n_steps=1, base_seed=SEED
    )
    samples = np.asarray(st["final_species"][:, 0]).astype(int)
    kgrid = np.arange(0, int(samples.max()) + 1)
    empirical = np.array([(samples <= k).mean() for k in kgrid])
    exact = _poisson_cdf(LAMBDA, kgrid)
    dkw = math.sqrt(math.log(2.0 / ALPHA) / (2.0 * 8192))
    ks = float(np.max(np.abs(empirical - exact)))
    stationary_ok = bool(ks <= dkw)

    # --- wrong-law power control (diagnostic only) ------------------------
    wrong_lambda = 6.0
    wrong_exact = _poisson_cdf(wrong_lambda, kgrid)
    ks_wrong = float(np.max(np.abs(empirical - wrong_exact)))
    power_ok = bool(ks_wrong > dkw)

    invariant_ok = bool(
        np.all(samples >= 0) and np.all(np.asarray(tr["final_species"]) >= 0)
    )

    plan = Path(__file__).with_name("PREDECLARED_PLAN.md")
    return {
        "case": "jax_ssa_immigration_death_installed_cpu",
        "revision": REVISION,
        "jax_version": jax.__version__,
        "devices": devices,
        "plan_sha256": _sha256(plan),
        "law": {
            "k_on": K_ON,
            "k_off": K_OFF,
            "lambda": LAMBDA,
            "transient_mean": "4*(1-exp(-0.5t))",
            "stationary": "Poisson(4)",
            "seed": SEED,
            "alpha": ALPHA,
        },
        "flatten": {
            "num_species": flat["num_species"],
            "num_reactions": flat["num_reactions"],
            "rate_constants": rate_constants,
        },
        "transient": {
            "batch_size": 4096,
            "n_steps": 20,
            "t_end": 20.0,
            "max_abs_error": float(np.max(err)),
            "max_allowed": float(np.max(allowed)),
            "passed": transient_ok,
        },
        "stationary": {
            "batch_size": 8192,
            "n_steps": 1,
            "t_end": 20.0,
            "sample_mean": float(samples.mean()),
            "sample_var": float(samples.var()),
            "dkw_bound": dkw,
            "ks_stat": ks,
            "passed": stationary_ok,
        },
        "wrong_law_control": {
            "law": "Poisson(6)",
            "ks_stat": ks_wrong,
            "dkw_bound": dkw,
            "rejected": power_ok,
        },
        "invariants": {"nonnegative": invariant_ok},
        "all_passed": bool(
            transient_ok and stationary_ok and power_ok and invariant_ok
        ),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, required=True)
    a = ap.parse_args()
    result = run()
    a.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "devices",
                    "transient",
                    "stationary",
                    "wrong_law_control",
                    "all_passed",
                )
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["all_passed"] else 1)
