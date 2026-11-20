"""Independent analytic qualification of NFnext dynamic-energy Arrhenius rates.

The energy pattern ``ep1: A(x~u) G0 * NB()`` is dynamic: its value depends on
the runtime observable ``NB()``.  For the reversible Arrhenius state change the
signed energy delta is the energy of the product center state minus that of the
reactant center state, so with NB=10, G0=0.1, phi=0.5 and Ea=1:

    G(u) = 0.1 * 10 = 1,  G(p) = 0
    forward dG = G(p) - G(u) = -1 -> kf = exp(-(Ea + phi*dG))     = exp(-0.5)
    reverse dG = G(u) - G(p) = +1 -> kr = exp(-(Ea + (1-phi)*dG)) = exp(-1.5)

Starting from state u at T=2 the two-state CTMC has the closed-form law

    P_p(T) = kf/(kf+kr) * (1 - exp(-(kf+kr)*T)).

This law is derived from detailed balance, not from BNG3 output or its RNG.
The comparator uses fixed seeds, an explicit DKW tolerance, and a wrong-law
(zeroed-energy) discriminator; a silently zeroed dynamic energy would instead
produce kf = kr = exp(-1) and a markedly different equilibrium.
"""

from __future__ import annotations

import importlib.util
import math
from functools import lru_cache
from pathlib import Path

# Use the freshly built extension from this worktree when available.  This is
# the same public binding (cpp.simulate_nfnext -> executeFromBioNetGen) the
# other NFnext tests exercise; loading it explicitly avoids an unrelated
# editable install pointing at a different worktree's build.
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
  G0 0.1
  phi 0.5
  Ea 1
end parameters
begin molecule types
  A(x~u~p)
  B()
end molecule types
begin observables
  Molecules NB B()
  Molecules P_count A(x~p)
end observables
begin seed species
  A(x~u) 1
  B() 10
end seed species
begin energy patterns
  ep1: A(x~u) G0 * NB()
end energy patterns
begin reaction rules
  fwd: A(x~u) -> A(x~p) Arrhenius(phi, Ea)
  rev: A(x~p) -> A(x~u) Arrhenius(phi, Ea)
end reaction rules
end model
"""

N = 512
SEED_BASE = 20261119
T = 2.0
ALPHA = 0.01  # DKW confidence 1 - ALPHA


def _analytic_pp():
    kf = math.exp(-0.5)
    kr = math.exp(-1.5)
    lam = kf + kr
    return kf / lam * (1.0 - math.exp(-lam * T))


def _zeroed_energy_wrong_pp():
    """Law if the dynamic energy were silently folded to zero: kf = kr = exp(-Ea)."""
    k = math.exp(-1.0)
    return 0.5 * (1.0 - math.exp(-2.0 * k * T))


def _dkw_epsilon(n, alpha):
    return math.sqrt(math.log(2.0 / alpha) / (2.0 * n))


@lru_cache(maxsize=1)
def _empirical_pp():
    """NFnext ensemble fraction in state p at T, with invariants and route check."""
    model = cpp.parse_string(MODEL)
    values = []
    for i in range(N):
        result = cpp.simulate_nfnext(model, [0.0, T], seed=SEED_BASE + i)
        # The API route is NFnext itself, not a network-generated fallback.
        assert result["engine"] == "nfnext"
        obs = result["observables"]
        assert set(obs) == {"NB", "P_count"}
        assert float(obs["NB"][0]) == float(obs["NB"][-1]) == 10.0
        initial = float(obs["P_count"][0])
        final = float(obs["P_count"][-1])
        assert initial == 0.0 and final in (0.0, 1.0)
        values.append(final)
    p_hat = sum(values) / N
    se = math.sqrt(p_hat * (1.0 - p_hat) / N)
    return p_hat, se


def test_nfnext_route_is_selected_for_dynamic_energy_model():
    """The public Python route executes this model through NFnext."""
    _empirical_pp()  # asserts engine == "nfnext" and the carried invariants
    assert N >= 200


def test_dynamic_energy_arrhenius_matches_independent_analytic_law():
    """P_p(2) over fixed seeds obeys the independently derived two-state law."""
    p_hat, se = _empirical_pp()
    expected = _analytic_pp()
    epsilon = _dkw_epsilon(N, ALPHA)
    assert abs(p_hat - expected) <= epsilon, (
        f"P_p(2)={p_hat:.4f} vs analytic {expected:.4f} "
        f"(DKW eps={epsilon:.4f} at alpha={ALPHA}, N={N})"
    )
    assert abs(p_hat - expected) <= 4.0 * se


def test_zeroed_energy_wrong_law_is_discriminated():
    """A dynamic energy folded to zero would give a different equilibrium."""
    p_hat, se = _empirical_pp()
    wrong = _zeroed_energy_wrong_pp()
    epsilon = _dkw_epsilon(N, ALPHA)
    assert p_hat - wrong > epsilon, (
        f"observed {p_hat:.4f} not separated from zeroed-energy law {wrong:.4f} "
        f"by DKW eps={epsilon:.4f}"
    )
    assert p_hat - wrong > 4.0 * se
