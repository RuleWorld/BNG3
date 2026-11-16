import importlib.util
import math
import sys
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
    sys.modules["bionetgen._bionetgen_cpp"] = cpp
else:
    import bionetgen._bionetgen_cpp as cpp


def _simulate(bngl: str, seed: int):
    model = cpp.parse_string(bngl)
    return cpp.simulate_nfnext(model, [0.0, 1.0, 2.0], seed=seed)


def test_nfnext_executes_whole_species_replacement_in_compartment():
    bngl = r"""
begin model
begin parameters
  k 0.01
end parameters
begin compartments
  c 3 1.0
end compartments
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  @c:A() 100
  @c:B() 100
  @c:C() 0
end seed species
begin observables
  Molecules Cobs @c:C()
end observables
begin reaction rules
  @c:A() + @c:B() -> @c:C() k
end reaction rules
end model
"""
    r = _simulate(bngl, seed=1)
    obs = [float(x) for x in r["observables"]["Cobs"]]
    assert obs[0] == 0.0
    assert obs[1] >= 0.0 and obs[1] <= 100.0
    assert obs[2] >= obs[1]
    assert obs[2] <= 100.0
    # Conservation of the transformed mass in this closed system: A+B+2*C constant in molecule count change?
    # Each event consumes 1 A and 1 B and creates 1 C, so (A0-A)=C and (B0-B)=C => A+B+2*C = 200.
    # NFnext reports observables only; this regression asserts executable lowering and monotone product formation.
    assert all(math.isfinite(x) for x in obs)


def test_nfnext_whole_species_replacement_matches_nfcore_distribution():
    bngl = r"""
begin model
begin parameters
  k 0.01
end parameters
begin compartments
  c 3 1.0
end compartments
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  @c:A() 100
  @c:B() 100
  @c:C() 0
end seed species
begin observables
  Molecules Cobs @c:C()
end observables
begin reaction rules
  @c:A() + @c:B() -> @c:C() k
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    sample_times = [0.0, 2.0]
    seeds = range(64)
    nfcore_vals = []
    nfnext_vals = []
    for seed in seeds:
        nfcore = cpp.simulate_nf(model, t_end=2.0, n_steps=2, seed=seed, sample_times=sample_times)
        nfnext = cpp.simulate_nfnext(model, sample_times, seed=seed)
        nfcore_vals.append(float(nfcore["observables"]["Cobs"][-1]))
        nfnext_vals.append(float(nfnext["observables"]["Cobs"][-1]))
    nfcore_mean = sum(nfcore_vals) / len(nfcore_vals)
    nfnext_mean = sum(nfnext_vals) / len(nfnext_vals)
    # Independent stochastic implementations should agree on the mean within
    # sampling error for the same model/law. Use pooled empirical SE with a
    # conservative 5-SE tolerance.
    def se(vals):
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
        return math.sqrt(var / len(vals))

    tol = 5.0 * math.sqrt(se(nfcore_vals) ** 2 + se(nfnext_vals) ** 2)
    assert abs(nfnext_mean - nfcore_mean) <= max(tol, 1.0)
