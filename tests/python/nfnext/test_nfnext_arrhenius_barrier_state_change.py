import math
import importlib.util
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


def test_nfnext_barrier_energy_state_change_matches_analytic_ctmc():
    """Barrier+energy Arrhenius state change expands to elementary rates in NFnext."""
    bngl = """begin model
begin parameters
  Gbar 2.4
  phi 0.4
  Ea 1.2
  GU 0.5
  GP 1.8
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin observables
  Molecules A_U A(s~U)
  Molecules A_P A(s~P)
end observables
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model"""
    m = cpp.parse_string(bngl)
    Ea, B, GU, GP, phi = 1.2, 2.4, 0.5, 1.8, 0.4
    dG = GP - GU
    kf = math.exp(-(Ea + B + phi * dG))
    kr = math.exp(-(Ea + B + (phi - 1.0) * dG))
    lam = kf + kr
    peq = kf / lam
    t_end = 20.0
    n_steps = 20
    times = [i * t_end / n_steps for i in range(n_steps + 1)]
    analytic_p = [100.0 * (peq + (0.0 - peq) * math.exp(-lam * t)) for t in times]

    n = 64
    final = []
    for seed in range(n):
        r = cpp.simulate_nfnext(m, times, seed=seed)
        u = [float(x) for x in r["observables"]["A_U"]]
        p = [float(x) for x in r["observables"]["A_P"]]
        assert len(u) == len(times) and len(p) == len(times)
        for ui, pi in zip(u, p):
            assert abs(ui + pi - 100.0) < 1e-9
        final.append(p[-1])

    mean = sum(final) / n
    var = sum((x - mean) ** 2 for x in final) / n
    se = math.sqrt(var / n) if n else 0.0
    assert abs(mean - analytic_p[-1]) <= 4.0 * se
    # Wrong model without barrier (B=0) gives much faster relaxation.
    kf_nb = math.exp(-(Ea + phi * dG))
    kr_nb = math.exp(-(Ea + (phi - 1.0) * dG))
    lam_nb = kf_nb + kr_nb
    peq_nb = kf_nb / lam_nb
    wrong_mean = 100.0 * (peq_nb + (0.0 - peq_nb) * math.exp(-lam_nb * t_end))
    assert abs(mean - wrong_mean) > 4.0 * se
