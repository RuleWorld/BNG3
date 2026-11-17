"""Independent qualification of NFnext TotalRate modifier execution.

With the TotalRate modifier the rule propensity is the declared rate k while
at least one reactant exists, independent of reactant count. Starting from
N0 molecules, the number of events by time t is therefore min(N0, Poisson(k t)),
so E[A(t)] = N0 - k t for k t <= N0.

The oracle below samples that exact counting process with its own RNG; it is
not derived from the BNG3 engine or its draw ordering.
"""

import math
import random

import bionetgen._bionetgen_cpp as cpp

MODEL = """begin model
begin parameters
  k 2.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_tot A()
end observables
begin reaction rules
  decay: A() -> 0 k TotalRate
end reaction rules
end model
"""

TIMES = (0.1, 0.5, 1.0)
N = 512
N0 = 100
K = 2.0


def _exact_total_rate(seed, target):
    """Independent Poisson(k*target) event count, capped at N0."""
    rng = random.Random(seed)
    # Knuth: Poisson sampler with its own uniform stream.
    limit = math.exp(-K * target)
    count, p = 0, 1.0
    while p > limit:
        p *= rng.random()
        count += 1
    return N0 - min(N0, count - 1)


def test_total_rate_matches_exact_poisson_law():
    model = cpp.parse_string(MODEL)
    for j, t in enumerate(TIMES):
        observed = []
        for seed in range(N):
            value = cpp.simulate_nfnext(model, [0.0, t], seed=seed)["observables"][
                "A_tot"
            ][-1]
            observed.append(float(value))
        oracle = [_exact_total_rate(90000 + j * N + seed, t) for seed in range(N)]
        mo = sum(observed) / N
        mr = sum(oracle) / N
        vo = sum((x - mo) ** 2 for x in observed) / (N - 1)
        vr = sum((x - mr) ** 2 for x in oracle) / (N - 1)
        se = math.sqrt((vo + vr) / N)
        assert abs(mo - mr) <= 4.0 * se, (
            f"t={t}: NFnext {mo:.3f} vs exact TotalRate law {mr:.3f} "
            f"({abs(mo - mr) / se:.2f} sigma)"
        )


def test_elementary_rate_wrong_implementation_is_rejected():
    """Propensity k*A (no TotalRate) must be excluded by this comparator."""
    model = cpp.parse_string(MODEL)
    t = 1.0
    # Under elementary mass action, A(t) = N0*exp(-k*t) ~= 13.5, far below the
    # TotalRate law value N0 - k*t = 98.
    elementary_mean = N0 * math.exp(-K * t)
    observed = [
        float(cpp.simulate_nfnext(model, [0.0, t], seed=s)["observables"]["A_tot"][-1])
        for s in range(N)
    ]
    mean = sum(observed) / N
    var = sum((x - mean) ** 2 for x in observed) / (N - 1)
    se = math.sqrt(var / N)
    assert abs(mean - (N0 - K * t)) <= 4.0 * se
    assert abs(mean - elementary_mean) > 8.0 * se
