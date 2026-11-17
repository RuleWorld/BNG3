"""Independent qualification of NFnext reversible two-state conversion.

``A(x~u) -> A(x~p)`` (rate kf) and ``A(x~p) -> A(x~u)`` (rate kr) form a
two-state continuous-time Markov chain for every molecule.  Starting with N
molecules in state u, the number in state p at time t is exactly binomial:

    P(p, t) = kf/(kf+kr) * (1 - exp(-(kf+kr)*t))
    E[P(t)] = N * P(p, t)
    Var[P(t)] = N * P(p, t) * (1 - P(p, t))

This oracle is a closed-form solution of the source CTMC law.  It is written
from the two-state transition probabilities and does not use the BNG3 engine,
its random stream, or generated-network propensities.  An ensemble of
independent NFnext seeds is compared with that analytic mean; a wrong
implementation that omits the reverse rate is shown to be rejected.
"""

import importlib.util
import math
from pathlib import Path

# Use freshly built extension from this worktree when available.
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
  kf 0.5
  kr 0.3
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) -> A(x~p) kf
  A(x~p) -> A(x~u) kr
end reaction rules
end model
"""

N = 100
KF = 0.5
KR = 0.3
TIMES = (0.5, 1.0, 2.0, 5.0)
SEEDS = 512
SEED_BASE = 10000


def _analytic_p(t):
    return KF / (KF + KR) * (1.0 - math.exp(-(KF + KR) * t))


def _wrong_no_reverse_p(t):
    # Wrong implementation: ignore the reverse rate, so p -> 1 and P -> N.
    # Equilibrium must instead be kf/(kf+kr) = 0.625 of the population.
    return 1.0 - math.exp(-KF * t)


def _ensemble():
    times = [0.0] + list(TIMES)
    rows = []
    for i in range(SEEDS):
        result = cpp.simulate_nfnext(cpp.parse_string(MODEL), times, seed=SEED_BASE + i)
        rows.append(
            [float(x) for x in result["observables"]["P"]]
            + [float(x) for x in result["observables"]["U"]]
        )
    return times, rows


def _mean(col):
    return sum(col) / len(col)


def test_reversible_conversion_matches_analytic_ctmc():
    """NFnext ensemble mean matches the exact two-state law within 4 sigma."""
    times, rows = _ensemble()
    j = {t: i for i, t in enumerate(times)}
    n = len(TIMES)
    for t in TIMES:
        k = j[t]
        p = _analytic_p(t)
        mean_analytic = N * p
        mean_nf = _mean([row[k] for row in rows])
        se = math.sqrt(N * p * (1.0 - p) / SEEDS)
        assert abs(mean_nf - mean_analytic) <= 4.0 * se, (
            f"t={t}: NFnext {mean_nf:.3f} vs analytic {mean_analytic:.3f} "
            f"({abs(mean_nf - mean_analytic) / se:.2f} sigma)"
        )
        # Conservation: every molecule is in exactly one state at all times.
        # U values are stored after all (n+1) P values in each row.
        for row in rows:
            assert abs(row[k] + row[(n + 1) + k] - N) < 1e-6


def test_reversible_conversion_equilibrium_ratio():
    """At long time the p population approaches kf/(kf+kr), not all molecules."""
    times, rows = _ensemble()
    k = times.index(TIMES[-1])
    mean_nf = _mean([row[k] for row in rows])
    # Analytic equilibrium fraction is 0.625; at t=5 the transient law gives
    # 0.6136.  The ensemble-mean standard error is sqrt(p(1-p)/SEEDS); use a
    # 4-sigma band so the check is not flaky, while the no-reverse wrong law
    # (p -> 1.0) is still far outside it.
    p_long = _analytic_p(TIMES[-1])
    se = math.sqrt(p_long * (1.0 - p_long) / SEEDS)
    assert abs(mean_nf / N - p_long) <= 4.0 * se
    assert mean_nf / N < 0.70


def test_no_reverse_wrong_implementation_is_rejected():
    """The comparator must reject a law that drops the reverse conversion."""
    times, rows = _ensemble()
    k = times.index(TIMES[-1])
    mean_nf = _mean([row[k] for row in rows])
    p = _analytic_p(TIMES[-1])
    mean_wrong = N * _wrong_no_reverse_p(TIMES[-1])
    se = math.sqrt(N * p * (1.0 - p) / SEEDS)
    # At t=5 the wrong law predicts ~91.8 vs analytic ~61.4: far outside noise.
    assert mean_wrong - mean_nf > 8.0 * se, (
        f"wrong no-reverse law {mean_wrong:.3f} not discriminated "
        f"from NFnext {mean_nf:.3f}"
    )
