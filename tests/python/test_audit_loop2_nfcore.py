"""Regression tests for Loop 2 audit fixes in embedded NFcore, NFinput & RNF runner.

Covers all verified Loop 2 NFcore defects:
1.  L2-07-01: Bivalent homodimer binding symmetry (`A(b,b) + A(b,b) -> A(b!1,b).A(b!1,b)`)
2.  L2-07-02 & L2-01-09: Intra-molecule self-bond formation & breaking (`A(b,b) <-> A(b!1,b!1)`)
3.  L2-07-03: Identical-reactant rules with non-TotalRate modifiers (`DeleteMolecules`)
4.  L2-07-04 & L2-01-07: Arrhenius homodimer binding/unbinding 0.5 symmetry & shadowed `baseRate`
5.  L2-07-05: `ScopedCompositeRate` DOR refreshing global observable dependencies (`g() * f(x)`)
6.  L2-07-06 & L2-01-05: Dynamic runtime `include_products` / `exclude_products` evaluation
7.  L2-07-07: `SpeciesObservable::clone()` & `LocalFunction` evaluating `Species` observables without `exit(1)`
8.  L2-07-08: Quantified `Molecules` & `Species` observables on symmetric components (`A(b,b)`)
9.  L2-07-11: Logical XOR (`^^`) and modulo (`%`) in NFcore functions and inline rule rates
10. L2-07-12: Symmetric-component rules with reactant filters (`exclude_reactants`) and modifiers
11. L2-07-13 & L2-11-10c: RNF header syntax errors, duplicate flags, and negative `sim`/`eq` durations
12. L2-08-02: Compartmentalized energy patterns (`@PM`/`@CP`) in NFcore
13. L2-08-03: Multi-hop (>1 bond) and cyclic (3-ring) energy patterns fail closed in NFcore
14. L2-08-12: Pure kinetic barrier patterns (without `energy patterns`) in NFcore
15. L2-11-05: Cyclic compartment parent hierarchy rejected without infinite loop
16. L2-11-07: `gml` limit throws catchable Python `RuntimeError` instead of calling `exit(1)`
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp


def _run_nfcore_ensemble(
    source: str,
    obs_names: list[str],
    t_end: float,
    n_steps: int = 2,
    n_runs: int = 20,
    seed_base: int = 100,
    require_direct: bool = True,
) -> dict[str, tuple[float, float]]:
    model = cpp.parse_string(source)
    samples: dict[str, list[float]] = {name: [] for name in obs_names}
    for i in range(n_runs):
        res = cpp.simulate_nf(
            model,
            t_end=t_end,
            n_steps=n_steps,
            seed=seed_base + i,
            require_direct=require_direct,
        )
        for name in obs_names:
            samples[name].append(float(res["observables"][name][-1]))
    out: dict[str, tuple[float, float]] = {}
    for name, vals in samples.items():
        arr = np.asarray(vals, dtype=float)
        mean = float(arr.mean())
        se = float(arr.std(ddof=1) / math.sqrt(len(arr))) if len(arr) > 1 else 0.0
        out[name] = (mean, se)
    return out


def _run_ode_final(source: str, obs_names: list[str], t_end: float) -> dict[str, float]:
    model = bionetgen.BioNetGenModel(cpp.parse_string(source))
    res = model.simulate(
        method="ode", t_start=0.0, t_end=t_end, n_steps=20, rtol=1e-9, atol=1e-12
    )
    return {name: float(res.observables[name][-1]) for name in obs_names}


def _assert_close_to_oracle(
    mean: float, se: float, expected: float, rel_tol: float = 0.04, z_max: float = 4.5
) -> None:
    tol = max(z_max * se, abs(expected) * rel_tol, 1.0)
    assert abs(mean - expected) <= tol, (
        f"NFcore mean={mean:.3f} (se={se:.3f}) diverged from oracle={expected:.3f} "
        f"(diff={mean - expected:+.3f}, tol={tol:.3f})"
    )


def test_l2_07_01_bivalent_homodimer_symmetry() -> None:
    """L2-07-01: Bivalent homodimer binding must run at 2k, not 3k (1.5x error)."""
    source = """
begin model
begin parameters
  k 0.0005
end parameters
begin molecule types
  A(b,b)
end molecule types
begin seed species
  A(b,b) 1000
end seed species
begin observables
  Molecules Bonds A(b!1).A(b!1)
  Molecules FreeB A(b)
end observables
begin reaction rules
  A(b,b) + A(b,b) -> A(b!1,b).A(b!1,b) k
end reaction rules
end model
"""
    # Exact analytical: [A](1) = 1000 / (1 + 2) = 333.333, Bonds = 666.667 (not 750.0!)
    expected_bonds = 2000.0 / 3.0
    expected_free_b = 4000.0 / 3.0
    ens = _run_nfcore_ensemble(source, ["Bonds", "FreeB"], t_end=1.0, n_runs=20)
    _assert_close_to_oracle(*ens["Bonds"], expected_bonds)
    _assert_close_to_oracle(*ens["FreeB"], expected_free_b)


def test_l2_07_02_intra_molecule_self_bond_symmetry() -> None:
    """L2-07-02 & L2-01-09: Intra-molecule self-bond breaking & formation must not run 2x too fast."""
    break_source = """
begin model
begin parameters
  k 0.25
end parameters
begin molecule types
  A(b,b,b)
end molecule types
begin seed species
  A(b!1,b!1,b) 2000
end seed species
begin observables
  Species BoundA A(b!1,b!1)
  Molecules FreeB A(b)
end observables
begin reaction rules
  A(b!1,b!1) -> A(b,b) k
end reaction rules
end model
"""
    expected_bound = 2000.0 * math.exp(-0.25 * 2.0)  # 1213.061 (2x bug gave ~735.8)
    ens = _run_nfcore_ensemble(break_source, ["BoundA", "FreeB"], t_end=2.0, n_runs=20)
    _assert_close_to_oracle(*ens["BoundA"], expected_bound)

    rev_source = """
begin model
begin parameters
  kself 0.4
  kunself 0.2
end parameters
begin molecule types
  A(b,b)
end molecule types
begin seed species
  A(b,b) 400
end seed species
begin observables
  Molecules A_self A(b!1,b!1)
end observables
begin reaction rules
  A(b,b) <-> A(b!1,b!1) kself, kunself
end reaction rules
end model
"""
    ode = _run_ode_final(rev_source, ["A_self"], t_end=1.0)
    ens_rev = _run_nfcore_ensemble(rev_source, ["A_self"], t_end=1.0, n_runs=20)
    _assert_close_to_oracle(*ens_rev["A_self"], ode["A_self"])


def test_l2_07_03_identical_reactants_with_delete_molecules_modifier() -> None:
    """L2-07-03: Non-TotalRate modifiers (DeleteMolecules) must preserve 0.5 homodimer symmetry."""
    source = """
begin model
begin parameters
  k 0.0005
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 2000
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A(b) + A(b) -> 0 k DeleteMolecules
end reaction rules
end model
"""
    # Exact analytical: 2000 / (1 + 2 * 0.5 * 0.0005 * 2000 * 2) = 666.667 (bug gave ~400)
    expected_a = 2000.0 / 3.0
    ens = _run_nfcore_ensemble(source, ["Atot"], t_end=2.0, n_runs=20)
    _assert_close_to_oracle(*ens["Atot"], expected_a)


def test_l2_07_04_and_l2_01_07_arrhenius_homodimer_symmetry() -> None:
    """L2-07-04 & L2-01-07: Arrhenius homodimer binding & unbinding must apply 0.5 symmetry."""
    bidir_source = """
begin model
begin parameters
  phi 0.5
  Ea0 7.0
  G -1.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1000
end seed species
begin energy patterns
  A(b!1).A(b!1) G
end energy patterns
begin observables
  Molecules Bonds A(b!1).A(b!1)
end observables
begin reaction rules
  A(b) + A(b) <-> A(b!1).A(b!1) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    ode_bidir = _run_ode_final(bidir_source, ["Bonds"], t_end=1.0)
    ens_bidir = _run_nfcore_ensemble(bidir_source, ["Bonds"], t_end=1.0, n_runs=20)
    _assert_close_to_oracle(*ens_bidir["Bonds"], ode_bidir["Bonds"])

    unbind_source = """
begin model
begin parameters
  phi 0.5
  Ea0 2.0
  G 2.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 1000
end seed species
begin energy patterns
  A(b!1).A(b!1) G
end energy patterns
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b!1).A(b!1) -> A(b) + A(b) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    ode_unbind = _run_ode_final(unbind_source, ["Afree"], t_end=2.0)
    ens_unbind = _run_nfcore_ensemble(unbind_source, ["Afree"], t_end=2.0, n_runs=20)
    _assert_close_to_oracle(*ens_unbind["Afree"], ode_unbind["Afree"])


def test_l2_07_05_scoped_composite_rate_dor_global_observable_updates() -> None:
    """L2-07-05: ScopedCompositeRate DOR (`g() * f(x)`) must track live global observable changes."""
    source = """
begin model
begin parameters
  k 0.001
  kd 3.0
end parameters
begin molecule types
  A(s~0~1)
  B()
end molecule types
begin seed species
  A(s~0) 1000
  B() 1000
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules Btot B()
end observables
begin functions
  f(x) = k * A0(x)
  g() = Btot
end functions
begin reaction rules
  %x:A(s~0) -> A(s~1) g() * f(x)
  B() -> 0 kd
end reaction rules
end model
"""
    # Exact analytical: integral_0^2 k*1000*exp(-3t) dt = (1/3)*(1 - exp(-6)) = 0.332507
    # A0(2) = 1000 * exp(-0.332507) = 717.124 (frozen Btot(0) bug gave ~135.3)
    expected_a0 = 1000.0 * math.exp(-(1.0 / 3.0) * (1.0 - math.exp(-6.0)))
    ens = _run_nfcore_ensemble(source, ["A0", "Btot"], t_end=2.0, n_runs=20)
    _assert_close_to_oracle(*ens["A0"], expected_a0)


def test_l2_07_06_and_l2_01_05_dynamic_product_filters() -> None:
    """L2-07-06 & L2-01-05: include_products / exclude_products evaluate dynamically on products."""
    excl_x = """
begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(b,x)
  B(a)
  X(a)
end molecule types
begin seed species
  A(b,x!1).X(a!1) 100
  A(b,x) 100
  B(a) 200
end seed species
begin observables
  Molecules AB_with_X X(a!1).A(x!1,b!2).B(a!2)
  Molecules AB_no_X A(x,b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) k exclude_products(1,X())
end reaction rules
end model
"""
    ode_ex = _run_ode_final(excl_x, ["AB_with_X", "AB_no_X"], t_end=2.0)
    ens_ex = _run_nfcore_ensemble(excl_x, ["AB_with_X", "AB_no_X"], t_end=2.0, n_runs=15)
    assert ens_ex["AB_with_X"][0] == 0.0
    _assert_close_to_oracle(*ens_ex["AB_no_X"], ode_ex["AB_no_X"])

    incl_x = excl_x.replace("exclude_products(1,X())", "include_products(1,X())")
    ode_in = _run_ode_final(incl_x, ["AB_with_X", "AB_no_X"], t_end=2.0)
    ens_in = _run_nfcore_ensemble(incl_x, ["AB_with_X", "AB_no_X"], t_end=2.0, n_runs=15)
    _assert_close_to_oracle(*ens_in["AB_with_X"], ode_in["AB_with_X"])
    assert ens_in["AB_no_X"][0] == 0.0

    excl_stateful = """
begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(b,p~0~1)
  B(a)
end molecule types
begin seed species
  A(b,p~0) 100
  A(b,p~1) 100
  B(a) 200
end seed species
begin observables
  Molecules AB_p0 A(p~0,b!1).B(a!1)
  Molecules AB_p1 A(p~1,b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) k exclude_products(1,A(p~1))
end reaction rules
end model
"""
    ode_st = _run_ode_final(excl_stateful, ["AB_p0", "AB_p1"], t_end=2.0)
    ens_st = _run_nfcore_ensemble(excl_stateful, ["AB_p0", "AB_p1"], t_end=2.0, n_runs=15)
    _assert_close_to_oracle(*ens_st["AB_p0"], ode_st["AB_p0"])
    assert ens_st["AB_p1"][0] == 0.0


def test_l2_07_07_species_observable_in_local_function_does_not_exit() -> None:
    """L2-07-07: Local function referencing a Species observable must not call exit(1)."""
    source = """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(b,s~0~1)
  B(a)
end molecule types
begin seed species
  A(b!1,s~0).B(a!1) 400
end seed species
begin observables
  Species SpAB A(b!1).B(a!1)
  Molecules A0 A(s~0)
end observables
begin functions
  f(x) = k * (1 + SpAB(x))
end functions
begin reaction rules
  %x:A(s~0) -> A(s~1) f(x)
end reaction rules
end model
"""
    # Each A is bound to B so SpAB(x) = 1 -> rate = k * (1 + 1) = 1.0 -> A0(1) = 400 * exp(-1) = 147.15
    expected_a0 = 400.0 * math.exp(-1.0)
    ens = _run_nfcore_ensemble(source, ["A0"], t_end=1.0, n_runs=15)
    _assert_close_to_oracle(*ens["A0"], expected_a0)


def test_l2_07_08_quantified_observables_on_symmetric_components() -> None:
    """L2-07-08: Quantified Molecules & Species observables on A(b,b) must not crash or return 0."""
    source = """
begin model
begin parameters
  kf 0.05
end parameters
begin molecule types
  A(b,b)
  B(a)
end molecule types
begin seed species
  A(b,b) 100
  B(a) 200
end seed species
begin observables
  Molecules MolAbound A(b!+)>0
  Species Sp_gt0 A(b!+)>0
  Species Sp_gt1 A(b!+)>1
  Species Sp_both A(b!1,b!2).B(a!1).B(a!2)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) kf
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    res = cpp.simulate_nf(model, t_end=2.0, n_steps=2, seed=1, require_direct=True)
    obs = res["observables"]
    # Sp_gt1 must equal Sp_both identically at every time point!
    assert np.allclose(obs["Sp_gt1"], obs["Sp_both"]), (
        f"Sp_gt1={obs['Sp_gt1']} != Sp_both={obs['Sp_both']}"
    )
    assert obs["Sp_gt1"][-1] > 50.0
    assert obs["Sp_gt0"][-1] >= obs["Sp_gt1"][-1]
    assert obs["MolAbound"][-1] >= 2.0 * obs["Sp_both"][-1]


def test_l2_07_11_logical_xor_and_modulo_in_nfcore() -> None:
    """L2-07-11: Logical XOR (^^) and modulo (%) work in functions and inline rule rates."""
    xor_source = """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  f() = if((Atot > 50) ^^ (Atot > 200), 2.0, 0.0)
end functions
begin reaction rules
  A() -> 0 f()
end reaction rules
end model
"""
    model = cpp.parse_string(xor_source)
    res = cpp.simulate_nf(model, t_end=2.0, n_steps=4, seed=1, require_direct=True)
    # Decays until Atot drops to 50, where (50 > 50) ^^ (50 > 200) becomes 0 -> stops at 50!
    assert float(res["observables"]["Atot"][-1]) == 50.0

    mod_source = """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 101
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 if((Atot % 2) == 1, 10.0, 0.0)
end reaction rules
end model
"""
    model_mod = cpp.parse_string(mod_source)
    res_mod = cpp.simulate_nf(model_mod, t_end=2.0, n_steps=2, seed=1, require_direct=True)
    # 101 % 2 == 1 -> decays by 1 to 100, then 100 % 2 == 0 -> stops at 100!
    assert float(res_mod["observables"]["Atot"][-1]) == 100.0


def test_l2_07_12_symmetric_component_with_reactant_filter() -> None:
    """L2-07-12: Rules on duplicate component names (A(b,b)) support reactant filters."""
    source = """
begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(b,b,p~0~1)
  B(a)
end molecule types
begin seed species
  A(b,b,p~0) 100
  A(b,b,p~1) 100
  B(a) 100
end seed species
begin observables
  Molecules AB_p0 A(p~0,b!1).B(a!1)
  Molecules AB_p1 A(p~1,b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) k exclude_reactants(1,A(p~1))
end reaction rules
end model
"""
    ode = _run_ode_final(source, ["AB_p0", "AB_p1"], t_end=2.0)
    ens = _run_nfcore_ensemble(source, ["AB_p0", "AB_p1"], t_end=2.0, n_runs=15)
    _assert_close_to_oracle(*ens["AB_p0"], ode["AB_p0"])
    assert ens["AB_p1"][0] == 0.0


def test_l2_07_13_and_l2_11_10c_rnf_errors_and_negative_times(tmp_path: Path) -> None:
    """L2-07-13 & L2-11-10c: RNF header errors, duplicate flags, and negative eq/sim fail cleanly."""
    base_bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
simulate_nf({{param=>"-rnf {rnf_path}"}})
"""
    cases = [
        ("bad_header.rnf", "GARBAGE_NO_DASH\n-seed 1\nbegin\nsim 1 2\nend\n"),
        ("dup_flag.rnf", "-seed 1\n-seed 2\nbegin\nsim 1 2\nend\n"),
        ("neg_eq.rnf", "-seed 1\nbegin\neq -5 2\nsim 1 2\nend\n"),
        ("neg_eq_steps.rnf", "-seed 1\nbegin\neq 1 -5\nsim 1 2\nend\n"),
        ("neg_sim.rnf", "-seed 1\nbegin\nsim -5 2\nend\n"),
    ]
    for rnf_name, rnf_content in cases:
        rnf_file = tmp_path / rnf_name
        rnf_file.write_text(rnf_content, encoding="utf-8")
        bngl_file = tmp_path / f"{rnf_file.stem}.bngl"
        bngl_file.write_text(
            base_bngl.format(rnf_path=str(rnf_file)), encoding="utf-8"
        )
        model = cpp.parse_file(str(bngl_file))
        with pytest.raises(Exception):
            cpp.execute(model, str(bngl_file), False)


def test_l2_08_02_compartmentalized_energy_patterns_in_nfcore() -> None:
    """L2-08-02: Compartmentalized energy patterns (@PM vs @CP) must preserve Boltzmann equilibrium."""
    source = """
begin model
begin parameters
  V_PM 1.0
  V_CP 1.0
  G_pm -2.0
  G_cp  2.0
  phi   0.5
  Ea    0.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin compartments
  EC 3 1.0
  PM 2 V_PM EC
  CP 3 V_CP PM
end compartments
begin seed species
  A(s~U)@PM 1000
  A(s~U)@CP 1000
end seed species
begin observables
  Molecules AP_pm A(s~P)@PM
  Molecules AP_cp A(s~P)@CP
end observables
begin energy patterns
  A(s~P)@PM G_pm
  A(s~P)@CP G_cp
end energy patterns
begin reaction rules
  R_pm: A(s~U)@PM <-> A(s~P)@PM Arrhenius(phi, Ea)
  R_cp: A(s~U)@CP <-> A(s~P)@CP Arrhenius(phi, Ea)
end reaction rules
end model
"""
    # Exact Boltzmann equilibrium: AP_pm = 1000 / (1 + exp(-2)) = 880.80, AP_cp = 119.20
    expected_pm = 1000.0 / (1.0 + math.exp(-2.0))
    expected_cp = 1000.0 / (1.0 + math.exp(2.0))
    ens = _run_nfcore_ensemble(source, ["AP_pm", "AP_cp"], t_end=10.0, n_runs=15)
    _assert_close_to_oracle(*ens["AP_pm"], expected_pm)
    _assert_close_to_oracle(*ens["AP_cp"], expected_cp)


def test_l2_08_03_multihop_and_ring_energy_patterns_fail_closed_in_nfcore() -> None:
    """L2-08-03: 3-molecule chain & 3-ring energy patterns must fail closed in NFcore."""
    chain_source = """
begin model
begin parameters
  G_3mol -3.0
  phi 0.5
  Ea 0.0
end parameters
begin molecule types
  A(s~U~P,b)
  B(a,c)
  C(b)
end molecule types
begin seed species
  A(s~U,b!1).B(a!1,c) 200
  A(s~U,b!1).B(a!1,c!2).C(b!2) 200
end seed species
begin observables
  Molecules AP_AB A(s~P,b!1).B(a!1,c)
  Molecules AP_ABC A(s~P,b!1).B(a!1,c!2).C(b!2)
end observables
begin energy patterns
  A(s~P,b!1).B(a!1,c!2).C(b!2) G_3mol
end energy patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    with pytest.raises(Exception):
        cpp.simulate_nf(cpp.parse_string(chain_source), t_end=1.0, n_steps=2, seed=1)

    ring_source = """
begin model
begin parameters
  G_ring 6.0
  phi 0.5
  Ea 4.0
end parameters
begin molecule types
  A(l,r)
  B(l,r)
  C(l,r)
end molecule types
begin seed species
  A(l,r!1).B(l!1,r) 50
  B(l,r!2).C(l!2,r) 50
end seed species
begin observables
  Molecules Ring3 A(l!3,r!1).B(l!1,r!2).C(l!2,r!3)
end observables
begin energy patterns
  A(l!3,r!1).B(l!1,r!2).C(l!2,r!3) G_ring
end energy patterns
begin reaction rules
  R_bind: C(r) + A(l) <-> C(r!1).A(l!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    with pytest.raises(Exception):
        cpp.simulate_nf(cpp.parse_string(ring_source), t_end=1.0, n_steps=2, seed=1)


def test_l2_08_12_pure_kinetic_barrier_pattern_in_nfcore(monkeypatch: pytest.MonkeyPatch) -> None:
    """L2-08-12: Pure kinetic barrier patterns (without energy patterns) work in NFcore."""
    monkeypatch.setenv("BNG_NFSIM_GENERAL_ENERGY", "1")
    source = """
begin model
begin parameters
  Gbar 3.0
  phi 0.5
  Ea 0.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 1000
end seed species
begin observables
  Molecules AP A(s~P)
end observables
begin barrier patterns
  B1: A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    # Exact analytical: k_f = k_r = exp(-3.0), AP(2) = 500 * (1 - exp(-2 * 2 * exp(-3.0)))
    k = math.exp(-3.0)
    expected_ap = 500.0 * (1.0 - math.exp(-2.0 * k * 2.0))
    ens = _run_nfcore_ensemble(source, ["AP"], t_end=2.0, n_runs=20)
    _assert_close_to_oracle(*ens["AP"], expected_ap)


def test_l2_11_05_cyclic_compartment_parent_rejected() -> None:
    """L2-11-05: Cyclic compartment parent hierarchy must fail cleanly instead of hanging."""
    source = """
begin model
begin compartments
  C1 3 1 C2
  C2 3 1 C1
end compartments
begin molecule types
  A(b)
  B(b)
end molecule types
begin seed species
  A(b!1)@C1.B(b!1)@C2 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A(b!1).B(b!1) -> A(b) + B(b) 1.0
end reaction rules
end model
"""
    with pytest.raises(Exception):
        model = cpp.parse_string(source)
        cpp.simulate_nf(model, t_end=1.0, n_steps=2, seed=1)


def test_l2_11_07_gml_limit_raises_python_exception_not_exit(tmp_path: Path) -> None:
    """L2-11-07: Exceeding NFsim gml limit must raise a catchable RuntimeError, not call exit(1)."""
    source = """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  0 -> A() 100
end reaction rules
end model
simulate_nf({t_end=>10, n_steps=>2, gml=>5, seed=>1})
"""
    bngl_path = tmp_path / "gml_exceed.bngl"
    bngl_path.write_text(source, encoding="utf-8")
    model = cpp.parse_file(str(bngl_path))
    with pytest.raises(RuntimeError, match="gml"):
        cpp.execute(model, str(bngl_path), False)
