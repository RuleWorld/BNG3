"""Independent qualification of NFnext observable-dependent (dynamic) rates.

The rate of ``A(x~u) -> A(x~p)`` is ``k*U()`` where ``U()`` counts the
reactant species. BNG2 mass-action with an observable rate gives propensity
``a(U) = k * U() * (# reactant embeddings) = k * U^2``. The oracle below is
an independently written exact Gillespie SSA for that law with its own RNG;
it is not derived from the BNG3 engine or its random stream.
"""

import math
import random

import bionetgen._bionetgen_cpp as cpp

MODEL = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
end observables
begin reaction rules
  A(x~u) -> A(x~p) k*U()
end reaction rules
end model
"""

TIMES = (0.0, 0.005, 0.010, 0.020, 0.050)
N = 512


def _exact_ssa(k, u0, target, rng, propensity):
    """Independent exact SSA: U -> U-1 with the given propensity function."""
    t, u = 0.0, u0
    while t < target and u > 0:
        tau = rng.expovariate(propensity(k, u))
        if t + tau > target:
            break
        t += tau
        u -= 1
    return float(u)


def _law(k, u):
    return k * u * u


def _frozen_wrong_law(k, u):
    # Wrong implementation: observable sampled once (k*U0) instead of
    # invalidated after every event -> propensity k*U0*U (exponential decay).
    return k * 100.0 * u


def _ensemble(propensity, seed_base):
    return [
        [
            _exact_ssa(0.5, 100, t, random.Random(seed_base + i), propensity)
            for t in TIMES
        ]
        for i in range(N)
    ]


def test_dynamic_observable_rate_matches_independent_exact_ssa():
    model = cpp.parse_string(MODEL)
    nf = [
        [
            float(x)
            for x in cpp.simulate_nfnext(model, list(TIMES), seed=i)["observables"]["U"]
        ]
        for i in range(N)
    ]
    oracle = _ensemble(_law, 10000)
    for j, t in enumerate(TIMES):
        col_nf = [row[j] for row in nf]
        col_or = [row[j] for row in oracle]
        mean_nf = sum(col_nf) / N
        mean_or = sum(col_or) / N
        var_nf = sum((x - mean_nf) ** 2 for x in col_nf) / (N - 1)
        var_or = sum((x - mean_or) ** 2 for x in col_or) / (N - 1)
        se = math.sqrt((var_nf + var_or) / N)
        if j == 0:
            assert mean_nf == mean_or == 100.0
            continue
        assert abs(mean_nf - mean_or) <= 4.0 * se, (
            f"t={t}: NFnext {mean_nf:.3f} vs independent SSA {mean_or:.3f} "
            f"({abs(mean_nf - mean_or) / se:.2f} sigma)"
        )


def test_frozen_observable_wrong_implementation_is_rejected():
    """The comparator must reject a rate that never invalidates its observable."""
    model = cpp.parse_string(MODEL)
    nf = [
        [
            float(x)
            for x in cpp.simulate_nfnext(model, list(TIMES), seed=i)["observables"]["U"]
        ]
        for i in range(N)
    ]
    wrong = _ensemble(_frozen_wrong_law, 20000)
    j = TIMES.index(0.020)
    col_nf = [row[j] for row in nf]
    col_wrong = [row[j] for row in wrong]
    mean_nf = sum(col_nf) / N
    mean_wrong = sum(col_wrong) / N
    var_nf = sum((x - mean_nf) ** 2 for x in col_nf) / (N - 1)
    var_wrong = sum((x - mean_wrong) ** 2 for x in col_wrong) / (N - 1)
    se = math.sqrt((var_nf + var_wrong) / N)
    assert (
        mean_nf - mean_wrong > 8.0 * se
    ), "frozen-rate law was not discriminated from dependency-updating rate"
