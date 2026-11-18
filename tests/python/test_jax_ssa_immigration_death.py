"""Independently qualified installed CPU JAX SSA case: immigration-death.

This is a NEW capability case under #473, authored with an analytic oracle that
is independent of BNG3 and of the JAX kernel. See analysis/c-jax-cpu/
PREDECLARED_PLAN.md (hashed before execution) for the predeclared law, seed,
budgets and error control. It does not claim full #473 acceptance.
"""

import math
import os
import sys

if (
    sys.platform == "darwin"
    and "JAX_PLATFORMS" not in os.environ
    and "JAX_PLATFORM_NAME" not in os.environ
):
    os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np
import pytest

jax = pytest.importorskip("jax")
pytest.importorskip("jaxlib")

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ssa

K_ON = 2.0
K_OFF = 0.5
LAMBDA = K_ON / K_OFF
SEED = 20261118
ALPHA = 0.001

MODEL = f"""begin model
begin parameters
k_on {K_ON}
k_off {K_OFF}
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
"""


def _poisson_cdf(lam, values):
    return np.array(
        [
            sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(int(x) + 1))
            for x in values
        ]
    )


def _model_and_network():
    model = cpp.parse_string(MODEL)
    network = cpp.generate_network(model)
    flat = cpp.jax_ssa_flatten(model, network)
    # one zero-order creation channel, one first-order death channel
    assert flat["num_reactions"] == 2
    return model, network


def test_installed_cpu_jax_ssa_immigration_death_transient_mean():
    """E[A(t)] = (k_on/k_off)(1 - exp(-k_off t)) within 3 SE at every grid time."""
    model, network = _model_and_network()
    res = jax_ssa.simulate(
        model, network, batch_size=4096, t_end=20.0, n_steps=20, base_seed=SEED
    )
    times = np.asarray(res["time"])
    mean = np.asarray(res["observable_means"]["CountA"])
    sd = np.asarray(res["observable_stds"]["CountA"])
    se = sd / math.sqrt(4096)
    expected = LAMBDA * (1.0 - np.exp(-K_OFF * times))
    assert np.all(np.abs(mean - expected) <= 3.0 * se + 0.05)
    assert np.all(np.asarray(res["final_species"]) >= 0)


def test_installed_cpu_jax_ssa_immigration_death_stationary_poisson():
    """A(infty) ~ Poisson(k_on/k_off) by DKW; wrong Poisson is rejected."""
    model, network = _model_and_network()
    res = jax_ssa.simulate(
        model, network, batch_size=8192, t_end=20.0, n_steps=1, base_seed=SEED
    )
    samples = np.asarray(res["final_species"][:, 0]).astype(int)
    grid = np.arange(0, int(samples.max()) + 1)
    empirical = np.array([(samples <= k).mean() for k in grid])
    dkw = math.sqrt(math.log(2.0 / ALPHA) / (2.0 * 8192))
    ks = float(np.max(np.abs(empirical - _poisson_cdf(LAMBDA, grid))))
    assert ks <= dkw
    # Power/direction control: a deliberately wrong Poisson(6) is rejected.
    ks_wrong = float(np.max(np.abs(empirical - _poisson_cdf(6.0, grid))))
    assert ks_wrong > dkw
