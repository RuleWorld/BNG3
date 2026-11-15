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


def test_nfnext_barrier_only_arrhenius_state_change_matches_analytic_ctmc():
    """Barrier-only Arrhenius state change (no energy patterns) is exp(-(Ea+Gbar))."""
    bngl = """begin model
begin parameters
  Gbar 1.0
  phi 0.5
  Ea 0.0
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
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model"""
    m = cpp.parse_string(bngl)
    k = math.exp(-(0.0 + 1.0))
    lam = 2.0 * k
    times = [0.0, 1.0, 2.0]
    analytic = [100.0 * (0.5 + (0.0 - 0.5) * math.exp(-lam * t)) for t in times]
    n = 128
    vals1, vals2 = [], []
    for seed in range(n):
        r = cpp.simulate_nfnext(m, times, seed=seed)
        u = [float(x) for x in r["observables"]["A_U"]]
        p = [float(x) for x in r["observables"]["A_P"]]
        assert len(u) == len(times) and len(p) == len(times)
        for ui, pi in zip(u, p):
            assert abs(ui + pi - 100.0) < 1e-9
        vals1.append(p[1])
        vals2.append(p[2])
    m1 = sum(vals1) / n
    m2 = sum(vals2) / n
    var1 = sum((x - m1) ** 2 for x in vals1) / n
    var2 = sum((x - m2) ** 2 for x in vals2) / n
    se1 = math.sqrt(var1 / n)
    se2 = math.sqrt(var2 / n)
    assert abs(m1 - analytic[1]) <= 4.0 * se1
    assert abs(m2 - analytic[2]) <= 4.0 * se2
