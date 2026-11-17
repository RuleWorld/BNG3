"""Independent qualification of NFnext include_reactants/exclude_reactants filters.

A molecule A with site b bound to B is the only reactant satisfying the filter
A(b!+). With only bound A present, the rule A(x~u)->A(x~p) k include_reactants(1,A(b!+))
has propensity k per bound A, so bound_u(t) ~ Binomial(20, exp(-k t)). The oracle
samples that exact law with its own RNG. The exclude variant must leave bound A
strictly untouched.
"""

import math
import random

import bionetgen._bionetgen_cpp as cpp

BOUND_ONLY = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(b,x~u~p)
  B(a)
end molecule types
begin seed species
  A(b!1,x~u).B(a!1) 20
end seed species
begin observables
  Molecules Bound_u A(b!1,x~u).B(a!1)
  Molecules Bound_p A(b!1,x~p).B(a!1)
end observables
begin reaction rules
  phos: A(x~u) -> A(x~p) k include_reactants(1,A(b!+))
end reaction rules
end model
"""

EXCLUDE = BOUND_ONLY.replace(
    "phos: A(x~u) -> A(x~p) k include_reactants(1,A(b!+))",
    "phos: A(x~u) -> A(x~p) k exclude_reactants(1,A(b!+))",
)

N = 512
N0 = 20
K = 0.5
TIMES = (0.5, 1.0, 2.0)


def _binomial_oracle(seed, t):
    rng = random.Random(seed)
    p = math.exp(-K * t)
    return sum(1 for _ in range(N0) if rng.random() < p)


def test_include_filter_matches_binomial_law():
    model = cpp.parse_string(BOUND_ONLY)
    for j, t in enumerate(TIMES):
        observed = []
        for s in range(N):
            o = cpp.simulate_nfnext(model, [0.0, t], seed=s)["observables"]
            observed.append(float(o["Bound_u"][-1]))
            assert float(o["Bound_p"][-1]) == N0 - observed[-1]
        oracle = [_binomial_oracle(70000 + j * N + s, t) for s in range(N)]
        mo, mr = sum(observed) / N, sum(oracle) / N
        vo = sum((x - mo) ** 2 for x in observed) / (N - 1)
        vr = sum((x - mr) ** 2 for x in oracle) / (N - 1)
        se = math.sqrt((vo + vr) / N)
        assert abs(mo - mr) <= 4.0 * se, (
            f"t={t}: include filter {mo:.3f} vs binomial {mr:.3f} "
            f"({abs(mo - mr) / se:.2f} sigma)"
        )


def test_exclude_filter_leaves_bound_reactant_untouched():
    model = cpp.parse_string(EXCLUDE)
    for s in range(N):
        o = cpp.simulate_nfnext(model, [0.0, 2.0], seed=s)["observables"]
        assert float(o["Bound_u"][-1]) == N0
        assert float(o["Bound_p"][-1]) == 0.0
