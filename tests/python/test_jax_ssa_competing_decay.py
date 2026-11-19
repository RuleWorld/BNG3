"""Extended installed CPU JAX SSA qualification: competing first-order decay.

A new capability case under #473, beyond the qualified immigration–death
case. The oracle is an independent 3-category multinomial law, plus a native
batch-SSA distributional reference. Plan, seed, budgets and error control are
predeclared in analysis/c-jax-extended/PREDECLARED_PLAN.md
(sha256 c9adacfa57dd752b780171bb11074a63b83abe68b24bcc797180a2845ce2d772).
"""

from __future__ import annotations

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

from bionetgen import _bionetgen_cpp as cpp  # noqa: E402
from bionetgen import jax_ssa  # noqa: E402

N0 = 30
K1 = 0.3
K2 = 0.1
K = K1 + K2
T_END = 3.0
BATCH = 8192
SEED = 20261119
ALPHA = 0.001
ALPHA_MARGINAL = ALPHA / 3.0
DKW_ONE = math.sqrt(math.log(2.0 / ALPHA_MARGINAL) / (2.0 * BATCH))
DKW_TWO = math.sqrt(2.0 * math.log(2.0 / ALPHA_MARGINAL) / BATCH)

MODEL = f"""begin model
begin parameters
k1 {K1}
k2 {K2}
end parameters
begin molecule types
A()
B()
C()
end molecule types
begin seed species
A() {N0}
B() 0
C() 0
end seed species
begin observables
Molecules CountA A()
Molecules CountB B()
Molecules CountC C()
end observables
begin reaction rules
A() -> B() k1
A() -> C() k2
end reaction rules
end model
"""


def _law(k1=K1, k2=K2):
    total = k1 + k2
    p_a = math.exp(-total * T_END)
    decayed = 1.0 - p_a
    return np.array([p_a, (k1 / total) * decayed, (k2 / total) * decayed])


def _binomial_cdf(p, n, values):
    return np.array(
        [
            sum(
                math.comb(n, i) * p**i * (1.0 - p) ** (n - i) for i in range(int(v) + 1)
            )
            for v in values
        ]
    )


def _cdf(samples, grid):
    return np.array([(samples <= v).mean() for v in grid])


def _model_and_network():
    model = cpp.parse_string(MODEL)
    network = cpp.generate_network(model)
    flat = cpp.jax_ssa_flatten(model, network)
    assert flat["num_reactions"] == 2
    assert flat["num_species"] == 3
    return model, network


def _jax_samples():
    model, network = _model_and_network()
    res = jax_ssa.simulate(
        model, network, batch_size=BATCH, t_end=T_END, n_steps=1, base_seed=SEED
    )
    return np.asarray(res["final_species"])


def test_competing_decay_matches_independent_multinomial_law():
    """Each marginal matches its analytic Binomial law under DKW control."""
    samples = _jax_samples()
    assert samples.shape == (BATCH, 3)
    np.testing.assert_array_equal(samples.sum(axis=1), np.full(BATCH, N0))

    p = _law()
    limits = np.arange(0, N0 + 1)
    for column, prob in enumerate(p):
        empirical = _cdf(samples[:, column], limits)
        exact = _binomial_cdf(prob, N0, limits)
        ks = float(np.max(np.abs(empirical - exact)))
        assert ks <= DKW_ONE, f"marginal {column}: KS {ks} > {DKW_ONE}"

        mean = float(samples[:, column].mean())
        expected_mean = N0 * prob
        bound = 3.0 * math.sqrt(N0 * prob * (1.0 - prob) / BATCH)
        assert (
            abs(mean - expected_mean) <= bound
        ), f"marginal {column}: mean {mean} vs {expected_mean}, bound {bound}"


def test_competing_decay_wrong_rate_law_is_rejected():
    """Swapping the two channel rates must violate the DKW control."""
    samples = _jax_samples()
    limits = np.arange(0, N0 + 1)
    wrong = _law(k1=K2, k2=K1)
    empirical = _cdf(samples[:, 1], limits)
    ks_wrong = float(np.max(np.abs(empirical - _binomial_cdf(wrong[1], N0, limits))))
    assert ks_wrong > DKW_ONE, f"wrong law not rejected: KS {ks_wrong}"


def test_competing_decay_matches_native_batch_distribution():
    """JAX SSA marginals agree with native batch SSA under two-sample DKW."""
    jax_samples = _jax_samples()
    model, network = _model_and_network()
    native = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=BATCH,
        t_end=T_END,
        n_steps=1,
        threads=1,
        base_seed=SEED,
    )
    native_samples = np.asarray(native["final_species"])
    assert native_samples.shape == (BATCH, 3)
    np.testing.assert_array_equal(native_samples.sum(axis=1), np.full(BATCH, N0))

    limits = np.arange(0, N0 + 1)
    for column in range(3):
        ks = float(
            np.max(
                np.abs(
                    _cdf(jax_samples[:, column], limits)
                    - _cdf(native_samples[:, column], limits)
                )
            )
        )
        assert ks <= DKW_TWO, f"marginal {column}: two-sample KS {ks} > {DKW_TWO}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
