import math
import os
import importlib.util
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


def test_nfnext_plain_arrhenius_matches_analytic_pure_death():
    """Plain Arrhenius(phi,Ea) without energy patterns/barriers is exp(-Ea)."""
    bngl = """begin model
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
  A(x~u) -> A(x~p) Arrhenius(0.5,1.0)
end reaction rules
end model"""
    m = cpp.parse_string(bngl)
    net = cpp.generate_network(m)
    ode = cpp.simulate_ode(m, net, t_end=2.0, n_steps=4)
    k = math.exp(-1.0)
    expected_ode = [100.0 * math.exp(-k * t) for t in [0.0, 0.5, 1.0, 1.5, 2.0]]
    for got, exp in zip(ode["observables"]["U"], expected_ode):
        assert abs(float(got) - exp) < 1e-5

    t = 2.0
    p_surv = math.exp(-k * t)
    mean = 100.0 * p_surv
    var = 100.0 * p_surv * (1.0 - p_surv)
    n = 64
    se = math.sqrt(var / n)
    samples = []
    for seed in range(n):
        r = cpp.simulate_nfnext(m, [0.0, t], seed=seed)
        assert r["observables"]["U"][0] + r["observables"]["P"][0] == 100
        assert r["observables"]["U"][1] + r["observables"]["P"][1] == 100
        samples.append(float(r["observables"]["U"][1]))
    obs_mean = sum(samples) / n
    assert abs(obs_mean - mean) <= 4.0 * se
    wrong_mean = 100.0 * math.exp(-math.exp(-0.5) * t)
    assert abs(obs_mean - wrong_mean) > 4.0 * se
