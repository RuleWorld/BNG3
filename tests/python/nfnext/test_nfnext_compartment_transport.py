"""Independent qualification of NFnext compartment transport.

BNG2 2.9.3 lowers the source below to two compartment-tagged species and one
reaction ``@c1::A() -> @c2::A()`` with rate k. This is a pure-death CTMC for the
source compartment with per-molecule rate k, so N_c1(t) is Binomial(N0, e^-kt)
and N_c2 = N0 - N_c1. Both the mean and the conservation law are checked
against an independently seeded binomial oracle.
"""

import math
import random

import bionetgen._bionetgen_cpp as cpp

MODEL = """begin model
begin parameters
  k 0.5
end parameters
begin compartments
  c1 3 1
  c2 3 1
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  A()@c1 100
end seed species
begin observables
  Molecules A_c1 A()@c1
  Molecules A_c2 A()@c2
end observables
begin reaction rules
  transport: A()@c1 -> A()@c2 k
end reaction rules
end model
"""

TIMES = (0.0, 0.5, 1.0, 2.0, 4.0)
N = 512


def test_compartment_transport_matches_independent_binomial_law():
    model = cpp.parse_string(MODEL)
    runs = []
    for seed in range(N):
        observables = cpp.simulate_nfnext(model, list(TIMES), seed=seed)["observables"]
        runs.append(
            (
                [float(x) for x in observables["A_c1"]],
                [float(x) for x in observables["A_c2"]],
            )
        )
    for j, t in enumerate(TIMES):
        col = [pair[0][j] for pair in runs]
        mean = sum(col) / N
        variance = sum((x - mean) ** 2 for x in col) / (N - 1)
        p = math.exp(-0.5 * t)
        rng = random.Random(70000 + j)
        oracle = [sum(1 for _ in range(100) if rng.random() < p) for _ in range(N)]
        oracle_mean = sum(oracle) / N
        oracle_var = sum((x - oracle_mean) ** 2 for x in oracle) / (N - 1)
        se = math.sqrt((variance + oracle_var) / N)
        if j == 0:
            assert mean == oracle_mean == 100.0
            continue
        assert abs(mean - oracle_mean) <= 4.0 * se, (
            f"t={t}: NFnext {mean:.3f} vs independent binomial {oracle_mean:.3f} "
            f"({abs(mean - oracle_mean) / se:.2f} sigma)"
        )
        assert abs(mean - 100.0 * p) <= 4.0 * se


def test_compartment_transport_conserves_total():
    model = cpp.parse_string(MODEL)
    for seed in range(N):
        result = cpp.simulate_nfnext(model, list(TIMES), seed=seed)
        c1 = result["observables"]["A_c1"]
        c2 = result["observables"]["A_c2"]
        for j in range(len(TIMES)):
            assert abs(float(c1[j]) + float(c2[j]) - 100.0) < 1e-9


def test_wrong_transport_rate_is_rejected():
    """A doubled rate (exp(-t)) must be outside the accepted k=0.5 bound."""
    model = cpp.parse_string(MODEL)
    j = TIMES.index(2.0)
    col = [
        float(cpp.simulate_nfnext(model, list(TIMES), seed=s)["observables"]["A_c1"][j])
        for s in range(N)
    ]
    mean = sum(col) / N
    variance = sum((x - mean) ** 2 for x in col) / (N - 1)
    se = math.sqrt(variance / N)
    assert abs(mean - 100.0 * math.exp(-0.5 * 2.0)) <= 4.0 * se
    assert abs(mean - 100.0 * math.exp(-1.0 * 2.0)) > 8.0 * se
