"""Independent qualification of a cross-species dynamic observable rate in NFnext.

The rule ``A(x~u) -> A(x~p)`` has rate ``k*NB()`` where ``NB()`` counts a
*different* species B, and B independently decays (``B() -> 0`` at ``kdeg``).
Under mass-action, the two channel propensities are

    a_conv(U,B) = k * NB * (embeddings of A(x~u)) = k * B * U
    a_decay(B)  = kdeg * B

so the conversion hazard changes every time B decays — a dynamic dependency
on another species' observable, distinct from the self-observable k*U() case.

The oracle is an independently written exact Gillespie SSA for these two
channels with its own RNG. It is not derived from the BNG3 engine, its random
stream, or generated-network propensities. A wrong implementation that samples
NB once (frozen at B0) is shown to be rejected, demonstrating that dependency
invalidation on the second species is actually exercised.
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
  k 0.02
  kdeg 0.5
end parameters
begin molecule types
  A(x~u~p)
  B()
end molecule types
begin seed species
  A(x~u) 50
  B() 20
end seed species
begin observables
  Molecules NB B()
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  conv: A(x~u) -> A(x~p) k*NB()
  decay: B() -> 0 kdeg
end reaction rules
end model
"""

K = 0.02
KDEG = 0.5
U0 = 50
B0 = 20
TIMES = (0.5, 1.0, 2.0)
SEEDS = 512
SEED_BASE = 20000
ORACLE_SEED_BASE = 30000


def _exact_ssa(seed, frozen_nb=False):
    """Independent exact SSA for the two-channel U/B system, own RNG."""
    rng = random.Random(seed)
    t, u, b = 0.0, U0, B0
    out = {}
    for target in TIMES:
        while t < target:
            nb = B0 if frozen_nb else b
            a_conv = K * nb * u
            a_decay = KDEG * b
            a0 = a_conv + a_decay
            if a0 <= 0.0:
                break
            tau = rng.expovariate(a0)
            if t + tau > target:
                break
            t += tau
            if rng.random() < a_conv / a0:
                u -= 1
            else:
                b -= 1
        out[target] = (float(u), float(b))
    return out


def _nfnext_ensemble():
    times = [0.0] + list(TIMES)
    u_rows = {tt: [] for tt in TIMES}
    b_rows = {tt: [] for tt in TIMES}
    for i in range(SEEDS):
        result = cpp.simulate_nfnext(cpp.parse_string(MODEL), times, seed=SEED_BASE + i)
        for j, tt in enumerate(TIMES):
            u_rows[tt].append(float(result["observables"]["U"][j + 1]))
            b_rows[tt].append(float(result["observables"]["NB"][j + 1]))
    return u_rows, b_rows


def _mean(col):
    return sum(col) / len(col)


def _se(a, b):
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    return math.sqrt((va + vb) / len(a))


def test_cross_species_dynamic_rate_matches_independent_ssa():
    """Both converted U and decaying modulator B match an independent SSA."""
    u_rows, b_rows = _nfnext_ensemble()
    oracle = [_exact_ssa(ORACLE_SEED_BASE + i) for i in range(SEEDS)]
    for tt in TIMES:
        ou = [o[tt][0] for o in oracle]
        ob = [o[tt][1] for o in oracle]
        for label, nf, orc in (("U", u_rows[tt], ou), ("NB", b_rows[tt], ob)):
            mu_nf, mu_or = _mean(nf), _mean(orc)
            err = _se(nf, orc)
            assert abs(mu_nf - mu_or) <= 4.0 * err, (
                f"t={tt} {label}: NFnext {mu_nf:.3f} vs independent SSA "
                f"{mu_or:.3f} ({abs(mu_nf - mu_or) / err:.2f} sigma)"
            )


def test_modulator_obeys_independent_pure_death_law():
    """B's mean follows the exact linear pure-death law B0*exp(-kdeg*t)."""
    _, b_rows = _nfnext_ensemble()
    for tt in TIMES:
        expected = B0 * math.exp(-KDEG * tt)
        mu = _mean(b_rows[tt])
        # Binomial-like spread of a death process; use a generous absolute band.
        assert (
            abs(mu - expected) < 1.0
        ), f"t={tt}: NB mean {mu:.3f} vs pure-death law {expected:.3f}"


def test_frozen_modulator_wrong_implementation_is_rejected():
    """A rate that never invalidates NB (frozen at B0) must be rejected."""
    u_rows, _ = _nfnext_ensemble()
    frozen = [_exact_ssa(40000 + i, frozen_nb=True) for i in range(SEEDS)]
    tt = TIMES[-1]
    fu = [o[tt][0] for o in frozen]
    mu_nf, mu_wrong = _mean(u_rows[tt]), _mean(fu)
    err = _se(u_rows[tt], fu)
    assert abs(mu_nf - mu_wrong) > 8.0 * err, (
        f"t={tt}: frozen-NB law {mu_wrong:.3f} not discriminated from "
        f"NFnext {mu_nf:.3f}"
    )
