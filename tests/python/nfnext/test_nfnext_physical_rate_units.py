import importlib.util
import math
import sys
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
    sys.modules["bionetgen._bionetgen_cpp"] = cpp
else:
    import bionetgen._bionetgen_cpp as cpp


def _mean_observable(bngl: str, obs: str, t: float, seeds):
    m = cpp.parse_string(bngl)
    vals = []
    for seed in seeds:
        r = cpp.simulate_nfnext(m, [0.0, t], seed=seed)
        vals.append(float(r["observables"][obs][1]))
    return sum(vals) / len(vals)


def test_nfnext_physical_unimolecular_decay_matches_count_law_mean():
    # k = 0.5 s^-1 is unchanged by unimolecular physical-unit conversion.
    bngl = r"""begin model
  setOption("units", "strict")
  begin units
    timeunits second
  end units
  begin parameters
    k = 0.5 [second^-1]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 100
  end seed species
  begin observables
    Molecules A_count A()@cell
  end observables
  begin reaction rules
    decay: A()@cell -> 0 k
  end reaction rules
end model
"""
    t = 1.0
    seeds = range(64)
    obs_mean = _mean_observable(bngl, "A_count", t, seeds)
    expected = 100.0 * math.exp(-0.5 * t)
    # Pure death: Var = N*p*(1-p), SE = sqrt(Var/n)
    p = math.exp(-0.5 * t)
    se = math.sqrt(100.0 * p * (1.0 - p) / len(seeds))
    assert abs(obs_mean - expected) <= 4.0 * se


def test_nfnext_physical_zero_order_synthesis_matches_count_law_mean():
    # 1.660538863127e-7 M/s in 1 fL with N_A => 100 count/s.
    bngl = r"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits second
  end units
  begin parameters
    k_synth = 1.660538863127e-7 [M/second]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin observables
    Molecules A_count A()@cell
  end observables
  begin reaction rules
    synth: 0 -> A()@cell k_synth
  end reaction rules
end model
"""
    t = 0.5
    seeds = range(64)
    obs_mean = _mean_observable(bngl, "A_count", t, seeds)
    expected = 100.0 * t
    # Poisson: Var = mean, SE = sqrt(mean/n)
    se = math.sqrt(expected / len(seeds))
    assert abs(obs_mean - expected) <= 4.0 * se
