"""Bounded #176 slice: reproducible, independent per-run NFnext ensemble state.

The public NFnext entry point is used only. Three properties are checked with
an independently derived analytic mean:

1. The same seed reproduces the same trajectory (no process-global drift).
2. Different seeds produce different trajectories (no single shared stream).
3. Repeating a seed after another run reproduces the first result exactly
   (no state leaking between calls).

No tolerance or expected value is derived from BNG3 output. The analytic mean
of the immigration-death process is a standard result independent of BNG3.
"""

import importlib.util
import math
from pathlib import Path

try:
    import bionetgen._bionetgen_cpp as cpp  # type: ignore
except ImportError:
    build_cpp = Path(__file__).resolve().parents[3] / "build" / "cpp"
    build_so = next(iter(sorted(build_cpp.glob("_bionetgen_cpp*.so"))), None)
    if build_so is not None:
        spec = importlib.util.spec_from_file_location("_bionetgen_cpp", str(build_so))
        cpp = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cpp)
    else:
        raise

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

TIMES = [0.0, 0.5, 1.0]
N0, LAM, MU = 5.0, 3.0, 0.5
RUNS = 64
SEED_BASE = 70000


def _trajectory(seed):
    result = cpp.simulate_nfnext(cpp.parse_string(MODEL), TIMES, seed=seed)
    return tuple(float(x) for x in result["observables"]["N"])


def test_same_seed_is_reproducible():
    assert _trajectory(12345) == _trajectory(12345)


def test_different_seeds_are_independent():
    a = _trajectory(1)
    b = _trajectory(2)
    assert a != b


def test_repeat_seed_after_other_run_is_unchanged():
    first = _trajectory(4242)
    _trajectory(9999)  # interleave a different run
    assert _trajectory(4242) == first


def test_ensemble_mean_matches_analytic_law():
    rows = [_trajectory(SEED_BASE + i) for i in range(RUNS)]
    for index, t in enumerate(TIMES):
        expected = N0 * math.exp(-MU * t) + (LAM / MU) * (1.0 - math.exp(-MU * t))
        mean = sum(row[index] for row in rows) / RUNS
        # Binomial-like spread of a birth-death count; predeclared 4-SE control.
        variance = LAM / (2.0 * MU) * (1.0 - math.exp(-2.0 * MU * t)) + max(
            expected * math.exp(-MU * t), 0.0
        )
        se = math.sqrt(variance / RUNS)
        assert abs(mean - expected) <= 4.0 * se, (
            f"t={t}: ensemble mean {mean:.3f} vs analytic {expected:.3f} "
            f"({abs(mean - expected) / se:.2f} SE)"
        )
