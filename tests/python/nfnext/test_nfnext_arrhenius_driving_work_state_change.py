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


def test_nfnext_driving_work_energy_state_change_matches_analytic_ctmc():
    """Static driving work in energy-modulated Arrhenius state change matches NFcore/analytic law."""
    bngl = """begin model
begin parameters
  Gbar 1.0
  phi 0.3
  Ea 0.8
  GU 0.2
  GP 1.1
  W 0.6
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
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(W)
end reaction rules
end model"""
    m = cpp.parse_string(bngl)
    Ea, B, GU, GP, phi, W = 0.8, 1.0, 0.2, 1.1, 0.3, 0.6
    dG = GP - GU
    kf = math.exp(-(Ea + B + phi * (dG - W)))
    kr = math.exp(-(Ea + B + (phi - 1.0) * (dG - W)))
    lam = kf + kr
    peq = kf / lam
    t_end = 20.0
    n_steps = 20
    times = [i * t_end / n_steps for i in range(n_steps + 1)]
    analytic_p = [100.0 * (peq + (0.0 - peq) * math.exp(-lam * t)) for t in times]

    # NFcore oracle (same compiled semantics) when general energy support is enabled.
    import os

    n = 64
    nx_final = []
    nf_final = []
    prev = os.environ.get("BNG_NFSIM_GENERAL_ENERGY")
    os.environ["BNG_NFSIM_GENERAL_ENERGY"] = "1"
    try:
        for seed in range(n):
            rx = cpp.simulate_nfnext(m, times, seed=seed)
            ux = [float(x) for x in rx["observables"]["A_U"]]
            px = [float(x) for x in rx["observables"]["A_P"]]
            for ui, pi in zip(ux, px):
                assert abs(ui + pi - 100.0) < 1e-9
            nx_final.append(px[-1])

            rn = cpp.simulate_nf(m, t_end, n_steps, seed=seed)
            un = [float(x) for x in rn["observables"]["A_U"]]
            pn = [float(x) for x in rn["observables"]["A_P"]]
            for ui, pi in zip(un, pn):
                assert abs(ui + pi - 100.0) < 1e-9
            nf_final.append(pn[-1])
    finally:
        if prev is None:
            os.environ.pop("BNG_NFSIM_GENERAL_ENERGY", None)
        else:
            os.environ["BNG_NFSIM_GENERAL_ENERGY"] = prev

    nx_mean = sum(nx_final) / n
    nf_mean = sum(nf_final) / n
    nx_var = sum((x - nx_mean) ** 2 for x in nx_final) / n
    nf_var = sum((x - nf_mean) ** 2 for x in nf_final) / n
    se = math.sqrt((nx_var + nf_var) / n)
    assert abs(nx_mean - analytic_p[-1]) <= 4.0 * math.sqrt(nx_var / n)
    assert abs(nf_mean - analytic_p[-1]) <= 4.0 * math.sqrt(nf_var / n)
    assert abs(nx_mean - nf_mean) <= 4.0 * se
    # No-driving-work model (W=0) should differ materially.
    kf0 = math.exp(-(Ea + B + phi * dG))
    kr0 = math.exp(-(Ea + B + (phi - 1.0) * dG))
    lam0 = kf0 + kr0
    peq0 = kf0 / lam0
    wrong_mean = 100.0 * (peq0 + (0.0 - peq0) * math.exp(-lam0 * t_end))
    assert abs(nx_mean - wrong_mean) > 4.0 * math.sqrt(nx_var / n)
