"""Independent qualification of a coupled immigration-death CTMC in NFnext.

Two channels act simultaneously on one species A:

    birth: 0 -> A()   at constant rate lam
    death: A() -> 0   at mass-action rate mu*A()

This is a linear birth-death-with-immigration process with an exact,
closed-form mean starting from N0 molecules:

    E[N(t)] = N0*exp(-mu*t) + (lam/mu)*(1 - exp(-mu*t))

and a stationary mean lam/mu. Both are standard results for the linear
immigration-death generator (not derived from BNG3). An independently written
exact Gillespie SSA with its own RNG cross-checks the full transient, and two
wrong-implementation laws (no birth / no death) are shown to be rejected.
This qualifies a coupled constant + mass-action two-channel system, distinct
from prior single-channel and reversible cases.
"""

import importlib.util
import math
import random
from pathlib import Path

build_so = (
    Path(__file__).resolve().parents[3]
    / "build"
    / "cpp"
    / "_bionetgen_cpp.cpython-314-darwin.so"
)
if build_so.exists():
    spec = importlib.util.spec_from_file_location("_bionetgen_cpp", str(build_so))
    cpp = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(cpp)
else:
    import bionetgen._bionetgen_cpp as cpp


MODEL = """begin model
begin parameters
  lam 3.0
  mu 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules N A()
end observables
begin reaction rules
  birth: 0 -> A() lam
  death: A() -> 0 mu
end reaction rules
end model
"""

LAM = 3.0
MU = 0.5
N0 = 5
TIMES = (0.5, 1.0, 2.0, 4.0)
SEEDS = 512
SEED_BASE = 50000
ORACLE_SEED_BASE = 60000


def _analytic_mean(t):
    return N0 * math.exp(-MU * t) + (LAM / MU) * (1.0 - math.exp(-MU * t))


def _exact_ssa(seed, mode="both"):
    """Independent exact SSA for the coupled two-channel system, own RNG."""
    rng = random.Random(seed)
    t, n = 0.0, N0
    out = {}
    for target in TIMES:
        while t < target:
            a_b = LAM if mode in ("both", "no_death") else 0.0
            a_d = MU * n if mode in ("both", "no_birth") else 0.0
            a0 = a_b + a_d
            if a0 <= 0.0:
                break
            tau = rng.expovariate(a0)
            if t + tau > target:
                break
            t += tau
            if rng.random() < a_b / a0:
                n += 1
            else:
                n -= 1
        out[target] = float(n)
    return out


def _nfnext_ensemble():
    times = [0.0] + list(TIMES)
    rows = {tt: [] for tt in TIMES}
    for i in range(SEEDS):
        result = cpp.simulate_nfnext(cpp.parse_string(MODEL), times, seed=SEED_BASE + i)
        for j, tt in enumerate(TIMES):
            rows[tt].append(float(result["observables"]["N"][j + 1]))
    return rows


def _mean(col):
    return sum(col) / len(col)


def _se(a, b):
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    return math.sqrt((va + vb) / len(a))


def test_immigration_death_matches_analytic_mean_and_ssa():
    """NFnext transient matches the closed-form mean and an independent SSA."""
    nf = _nfnext_ensemble()
    oracle = [_exact_ssa(ORACLE_SEED_BASE + i) for i in range(SEEDS)]
    for tt in TIMES:
        mu_nf = _mean(nf[tt])
        expected = _analytic_mean(tt)
        # Error scale from the independently simulated ensemble variance.
        col_or = [o[tt] for o in oracle]
        sd = math.sqrt(sum((x - _mean(col_or)) ** 2 for x in col_or) / (SEEDS - 1))
        se = sd / math.sqrt(SEEDS)
        assert abs(mu_nf - expected) <= 4.0 * se, (
            f"t={tt}: NFnext {mu_nf:.3f} vs analytic mean {expected:.3f} "
            f"({abs(mu_nf - expected) / se:.2f} sigma)"
        )
        err_ssa = _se(nf[tt], col_or)
        assert (
            abs(mu_nf - _mean(col_or)) <= 4.0 * err_ssa
        ), f"t={tt}: NFnext {mu_nf:.3f} vs independent SSA {_mean(col_or):.3f}"


def test_immigration_death_stationary_mean():
    """At long time the mean approaches lam/mu, not zero or unbounded growth."""
    nf = _nfnext_ensemble()
    mu = _mean(nf[TIMES[-1]])
    expected = LAM / MU
    col_or = [_exact_ssa(70000 + i)[TIMES[-1]] for i in range(SEEDS)]
    se = _se(nf[TIMES[-1]], col_or)
    assert (
        abs(mu - expected) <= 4.0 * se
    ), f"stationary mean {mu:.3f} vs lam/mu {expected:.3f}"


def test_wrong_single_channel_laws_are_rejected():
    """Laws dropping either channel are discriminated at t=4."""
    nf = _nfnext_ensemble()
    tt = TIMES[-1]
    mu_nf = _mean(nf[tt])
    sd = math.sqrt(sum((x - _mean(nf[tt])) ** 2 for x in nf[tt]) / (SEEDS - 1))
    se = sd / math.sqrt(SEEDS)
    no_birth = [_exact_ssa(80000 + i, mode="no_birth")[tt] for i in range(SEEDS)]
    no_death = [_exact_ssa(90000 + i, mode="no_death")[tt] for i in range(SEEDS)]
    assert abs(mu_nf - _mean(no_birth)) > 8.0 * se
    assert abs(mu_nf - _mean(no_death)) > 8.0 * se
