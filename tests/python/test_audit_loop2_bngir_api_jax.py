"""Regression tests for Loop 2 audit bugs in BNGIR, Python API, JAX, CLI, and legacy bngmodel."""

from __future__ import annotations

import math
from pathlib import Path

import jax
import numpy as np
import pytest
import sympy as sp
from click.testing import CliRunner

import bionetgen
from bionetgen import export_sympy_odes, jax_ssa
from bionetgen.bngir import EqualityUndecided, from_bngir, semantic_equal, to_bngir
from bionetgen.cli import main as cli_main
from bionetgen.jax_ode import simulate_jax_ode
from bionetgen.model import BioNetGenModel, _cpp


def _load_bngl(source: str) -> BioNetGenModel:
    return BioNetGenModel(_cpp.parse_string(source))


def _load_sbml_algebraic(tmp_path: Path) -> BioNetGenModel:
    sbml_alg = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="alg_test">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="C" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Y" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="1" constant="true"/>
    </listOfParameters>
    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/>
            <apply><plus/><apply><power/><ci>Y</ci><cn>3</cn></apply><ci>Y</ci></apply>
            <ci>X</ci>
          </apply>
        </math>
      </algebraicRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants><speciesReference species="X" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>X</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
    sbml_path = tmp_path / "alg_rule.xml"
    sbml_path.write_text(sbml_alg, encoding="utf-8")
    return bionetgen.from_sbml(str(sbml_path))


def test_l2_12_01_bngir_v01_fails_closed_on_bng3_events() -> None:
    b_ev = """
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules X A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin bng3_events version 1
  event "reset"
  trigger: time > 0.5
  initial_value: false
  persistent: true
  use_values_from_trigger_time: true
  assignment: X = 100
  end event
end bng3_events
end model
"""
    b_no = b_ev.split("begin bng3_events")[0] + "end model\n"
    m_ev = _load_bngl(b_ev)
    m_no = _load_bngl(b_no)

    for version in ("0.1", "0.2"):
        with pytest.raises(RuntimeError):
            to_bngir(m_ev, version=version)
        with pytest.raises(EqualityUndecided):
            semantic_equal(m_ev, m_no, version=version)


def test_l2_12_02_bngir_fails_closed_on_algebraic_rules(tmp_path: Path) -> None:
    m_alg = _load_sbml_algebraic(tmp_path)
    m_no = BioNetGenModel(m_alg._model, algebraic_rules=[])
    assert m_alg._algebraic_rules

    for version in ("0.1", "0.2"):
        with pytest.raises(ValueError, match="algebraic rules"):
            to_bngir(m_alg, version=version)
        with pytest.raises(EqualityUndecided):
            semantic_equal(m_alg, m_no, version=version)


def test_l2_12_03_and_l2_10_08b_bngir_v02_no_duplicate_compartment_suffix() -> None:
    b_single = """
begin model
begin parameters
  k 1
end parameters
begin compartments
  C 3 1
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A()@C 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  @C:A() -> @C:B() k
end reaction rules
end model
"""
    m1 = _load_bngl(b_single)
    rt1 = from_bngir(to_bngir(m1, version="0.2"))
    assert "@C@C" not in rt1.to_bngl()
    assert semantic_equal(m1, rt1) is True

    b_cross = """
begin model
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin molecule types
  V(t)
  S(y)
end molecule types
begin seed species
  V(t!1)@CP.S(y!1)@PM 10
end seed species
begin observables
  Molecules VS V(t!1)@CP.S(y!1)@PM
end observables
begin reaction rules
  0 -> V(t!1)@CP.S(y!1)@PM 1.0
end reaction rules
end model
"""
    m2 = _load_bngl(b_cross)
    rt2 = from_bngir(to_bngir(m2, version="0.2"))
    bngl2 = rt2.to_bngl()
    assert "@PM@PM" not in bngl2
    assert "@CP@CP" not in bngl2
    assert semantic_equal(m2, rt2) is True


def test_l2_12_04_semantic_equal_fixed_species() -> None:
    b_fix = """
begin model
begin parameters
  k1 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  $A() 10
end seed species
begin observables
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k1
end reaction rules
end model
"""
    b_fix_param_rename = b_fix.replace("k1", "k2")
    b_fix_mol_rename = (
        b_fix.replace("A()", "X()").replace("B()", "Y()").replace("B_obs", "Y_obs")
    )
    b_unfix = b_fix.replace("$A()", "A()")

    m_fix = _load_bngl(b_fix)
    assert semantic_equal(m_fix, _load_bngl(b_fix_param_rename)) is True
    assert semantic_equal(m_fix, _load_bngl(b_fix_mol_rename)) is True
    assert semantic_equal(m_fix, _load_bngl(b_unfix)) is False

    # Compartmented fixed species with parent hierarchy
    b_comp_fix = """
begin model
begin parameters
  k1 1.5
end parameters
begin compartments
  EC 3 1
  PM 2 1 EC
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  $A(b!1)@EC.B(a!1)@PM 10
end seed species
begin observables
  Molecules FreeA A(b)@EC
end observables
begin reaction rules
  A(b!1)@EC.B(a!1)@PM -> A(b)@EC + B(a)@PM k1
end reaction rules
end model
"""
    m_cfix = _load_bngl(b_comp_fix)
    m_cfix_ren = _load_bngl(b_comp_fix.replace("k1", "k2"))
    m_cunfix = _load_bngl(b_comp_fix.replace("$A(", "A("))
    assert semantic_equal(m_cfix, m_cfix_ren) is True
    assert semantic_equal(m_cfix, m_cunfix) is False


def test_l2_12_05_jax_ode_parameter_dependent_seed_amounts_and_grad() -> None:
    b_seed = """
begin model
begin parameters
  k 1.0
  A0 10.0
  B0 3*A0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() A0
  B() B0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""
    m = _load_bngl(b_seed)
    res = simulate_jax_ode(m, t_end=1.0, n_steps=200, parameters={"A0": 50.0})
    assert math.isclose(float(res["concentrations"][0, 0]), 50.0, rel_tol=1e-5)
    assert math.isclose(float(res["concentrations"][0, 1]), 150.0, rel_tol=1e-5)
    expected_a1 = 50.0 * math.exp(-1.0)
    expected_b1 = 150.0 + 50.0 * (1.0 - math.exp(-1.0))
    assert math.isclose(float(res["concentrations"][-1, 0]), expected_a1, rel_tol=1e-4)
    assert math.isclose(float(res["concentrations"][-1, 1]), expected_b1, rel_tol=1e-4)

    grad_a = float(
        jax.grad(
            lambda a0: simulate_jax_ode(
                m, t_end=1.0, n_steps=200, parameters={"A0": a0}, return_jax=True
            )["concentrations"][-1, 0]
        )(10.0)
    )
    grad_b = float(
        jax.grad(
            lambda a0: simulate_jax_ode(
                m, t_end=1.0, n_steps=200, parameters={"A0": a0}, return_jax=True
            )["concentrations"][-1, 1]
        )(10.0)
    )
    assert math.isclose(grad_a, math.exp(-1.0), rel_tol=1e-4)
    assert math.isclose(grad_b, 3.0 + (1.0 - math.exp(-1.0)), rel_tol=1e-4)


def test_l2_12_06_jax_ode_parameter_dependent_compartment_volume_and_grad() -> None:
    b_vol = """
begin model
begin parameters
  V 1.0
  k 1.0
end parameters
begin compartments
  C 3 V
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  @C:A() 10
  @C:B() 10
end seed species
begin observables
  Molecules A_obs @C:A()
end observables
begin reaction rules
  @C:A() + @C:B() -> 0 k
end reaction rules
end model
"""
    mv = _load_bngl(b_vol)
    t_end = 0.5
    v_override = 10.0
    res_jax = simulate_jax_ode(
        mv, t_end=t_end, n_steps=400, parameters={"V": v_override}
    )
    a_jax = float(res_jax["concentrations"][-1, 0])
    # Exact analytical solution for A(0)=B(0)=10, dA/dt = -(k/V)*A^2:
    # A(t) = A0 / (1 + (k/V)*A0*t)
    a_exact = 10.0 / (1.0 + (1.0 / v_override) * 10.0 * t_end)
    assert math.isclose(a_jax, a_exact, rel_tol=1e-4)

    # Analytical derivative dA/dV = A0^2 * k * t / (V + k * A0 * t)^2 at V = 1.0
    grad_v = float(
        jax.grad(
            lambda v: simulate_jax_ode(
                mv, t_end=t_end, n_steps=400, parameters={"V": v}, return_jax=True
            )["concentrations"][-1, 0]
        )(1.0)
    )
    expected_grad_v = (10.0**2 * 1.0 * t_end) / ((1.0 + 1.0 * 10.0 * t_end) ** 2)
    assert math.isclose(grad_v, expected_grad_v, rel_tol=1e-4)

    # Zero-order synthesis scales linearly with compartment volume V
    b_synth = """
begin model
begin parameters
  V 1.0
  k 2.0
end parameters
begin compartments
  C 3 V
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @C:A() 0
end seed species
begin observables
  Molecules A_obs @C:A()
end observables
begin reaction rules
  0 -> @C:A() k
end reaction rules
end model
"""
    ms = _load_bngl(b_synth)
    res_s = simulate_jax_ode(ms, t_end=1.0, n_steps=50, parameters={"V": 4.0})
    assert math.isclose(float(res_s["concentrations"][-1, 0]), 8.0, rel_tol=1e-6)
    grad_s = float(
        jax.grad(
            lambda v: simulate_jax_ode(
                ms, t_end=1.0, n_steps=50, parameters={"V": v}, return_jax=True
            )["concentrations"][-1, 0]
        )(4.0)
    )
    assert math.isclose(grad_s, 2.0, rel_tol=1e-6)


def test_l2_12_07_jax_ode_accepts_integer_initial_state() -> None:
    b = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""
    m = _load_bngl(b)
    res = simulate_jax_ode(m, t_end=1.0, n_steps=100, initial_state=[10, 0])
    assert math.isclose(
        float(res["concentrations"][-1, 0]), 10.0 * math.exp(-1.0), rel_tol=1e-6
    )


def test_l2_12_08_jax_ssa_and_batch_ssa_fail_closed_on_algebraic_rules(
    tmp_path: Path,
) -> None:
    m_alg = _load_sbml_algebraic(tmp_path)

    with pytest.raises(NotImplementedError, match="algebraic rules"):
        jax_ssa.simulate(m_alg, batch_size=8, t_end=1.0, n_steps=5, base_seed=42)

    with pytest.raises(ValueError, match="algebraic rules"):
        m_alg.simulate_batch_ssa(
            batch_size=8, t_end=1.0, n_steps=5, base_seed=42, backend="cpu"
        )


def test_l2_12_09_export_sympy_odes_functions_hill_and_time() -> None:
    b = """
begin model
begin parameters
  k 2.0
  Vmax 2.0
  Km 5.0
  n 2.0
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 10
  B() 5
  C() 5
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin functions
  f() = k * (1 + 0.1 * B_obs)
end functions
begin reaction rules
  A() -> B() f()
  B() -> C() Hill(Vmax, Km, n)
  C() -> A() k * (1 + sin(time))
end reaction rules
end model
"""
    m = _load_bngl(b)
    so = export_sympy_odes(m)
    assert so.t in so.odes[0].free_symbols
    assert so.t in so.odes[2].free_symbols
    assert all("time" not in str(sym) for ode in so.odes for sym in ode.free_symbols)
    assert not any(
        str(fn).startswith(("f(", "Hill("))
        for ode in so.odes
        for fn in ode.atoms(sp.Function)
    )

    # Evaluate ODEs numerically at (t=0.5, A=10, B=5, C=5, k=2, Vmax=2, Km=5, n=2)
    subs = {
        so.t: 0.5,
        so.species[0]: 10.0,
        so.species[1]: 5.0,
        so.species[2]: 5.0,
        so.params[0]: 2.0,
        so.params[1]: 2.0,
        so.params[2]: 5.0,
        so.params[3]: 2.0,
    }
    flux_ab = 10.0 * (2.0 * (1.0 + 0.1 * 5.0))
    flux_bc = 2.0 * (5.0**2) / (5.0**2 + 5.0**2)
    flux_ca = 5.0 * 2.0 * (1.0 + math.sin(0.5))
    assert math.isclose(float(so.odes[0].subs(subs)), flux_ca - flux_ab, rel_tol=1e-12)
    assert math.isclose(float(so.odes[1].subs(subs)), flux_ab - flux_bc, rel_tol=1e-12)
    assert math.isclose(float(so.odes[2].subs(subs)), flux_bc - flux_ca, rel_tol=1e-12)


def test_l2_12_10_and_l2_08_11_bngmodel_preserves_arrhenius_barriers_driven_and_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BNG_NFSIM_GENERAL_ENERGY", "1")
    b_arr = """
begin model
begin parameters
  phi 0.5
  Ea 1.0
  GA 0.0
  GB -2.0
  Gbar 0.5
  W 1.0
end parameters
begin molecule types
  A(s~u~p)
end molecule types
begin seed species
  A(s~u) 10
end seed species
begin observables
  Molecules Ap A(s~p)
end observables
begin energy patterns
  A(s~u) GA
  A(s~p) GB
end energy patterns
begin barrier patterns
  B1: A(s~u) -> A(s~p) Gbar
end barrier patterns
begin reaction rules
  R1: A(s~u) <-> A(s~p) Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
"""
    p_arr = tmp_path / "arr_barrier_driven.bngl"
    p_arr.write_text(b_arr, encoding="utf-8")

    m_orig = bionetgen.load(str(p_arr))
    bm = bionetgen.bngmodel(str(p_arr))
    bm_text = str(bm)

    assert "<->" in bm_text
    assert "begin barrier patterns" in bm_text
    assert "driven_by(W)" in bm_text

    m_rt = _load_bngl(bm_text)
    ap_orig = float(
        m_orig.simulate(method="ode", t_end=20.0, n_steps=20).observables["Ap"][-1]
    )
    ap_rt = float(
        m_rt.simulate(method="ode", t_end=20.0, n_steps=20).observables["Ap"][-1]
    )
    # Local detailed balance: k_f / k_r = exp(-(dG - W)) = exp(-(-2 - 1)) = exp(3)
    exact_eq = 10.0 * math.exp(3.0) / (1.0 + math.exp(3.0))
    assert math.isclose(ap_orig, exact_eq, rel_tol=1e-4)
    assert math.isclose(ap_rt, ap_orig, rel_tol=1e-6)

    # Verify include_reactants filter preservation
    b_filt = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
  A(b!1).B(a!1) 10
end seed species
begin observables
  Molecules A_free A(b)
  Molecules A_bound A(b!+)
end observables
begin reaction rules
  R1: A() -> 0 k include_reactants(1, B())
end reaction rules
end model
"""
    p_filt = tmp_path / "filter_rule.bngl"
    p_filt.write_text(b_filt, encoding="utf-8")
    mf_orig = bionetgen.load(str(p_filt))
    bm_f = bionetgen.bngmodel(str(p_filt))
    assert "include_reactants(1," in str(bm_f)
    mf_rt = _load_bngl(str(bm_f))
    r_orig = mf_orig.simulate(method="ode", t_end=1.0, n_steps=10)
    r_rt = mf_rt.simulate(method="ode", t_end=1.0, n_steps=10)
    assert math.isclose(
        float(r_rt.observables["A_free"][-1]),
        float(r_orig.observables["A_free"][-1]),
        rel_tol=1e-6,
    )
    assert math.isclose(float(r_rt.observables["A_free"][-1]), 10.0, rel_tol=1e-6)
    assert math.isclose(
        float(r_rt.observables["A_bound"][-1]),
        10.0 * math.exp(-1.0),
        rel_tol=1e-5,
    )


def test_l2_12_11_cli_check_accepts_paren_free_molecule_types(tmp_path: Path) -> None:
    b = """
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""
    p1 = tmp_path / "orig.bngl"
    p2 = tmp_path / "exported.bngl"
    p1.write_text(b, encoding="utf-8")

    runner = CliRunner()
    r_exp = runner.invoke(cli_main, ["export", str(p1), "-f", "bngl", "-o", str(p2)])
    assert r_exp.exit_code == 0, r_exp.output
    r_chk = runner.invoke(cli_main, ["check", str(p2)])
    assert r_chk.exit_code == 0, r_chk.output
    assert "OK:" in r_chk.output

    # Genuinely undeclared molecule type must still fail closed
    p_bad = tmp_path / "undeclared.bngl"
    p_bad.write_text(
        """
begin model
begin molecule types
  A
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() 1
end reaction rules
end model
""",
        encoding="utf-8",
    )
    r_bad = runner.invoke(cli_main, ["check", str(p_bad)])
    assert r_bad.exit_code == 1
    assert "Undeclared molecule type(s): B" in r_bad.output


def test_l2_10_08a_and_08c_bngir_rev_local_scope_and_arithmetic_action_args() -> None:
    b_scope = """
begin model
begin molecule types
  R(p~0~1)
end molecule types
begin seed species
  R(p~0) 10
end seed species
begin observables
  Molecules R1 R(p~1)
end observables
begin reaction rules
  %x:R(p~0) <-> R(p~1) if(R1(x)>0, 0, 1.0), 0.5
end reaction rules
end model
"""
    m_scope = _load_bngl(b_scope)
    rt_scope = from_bngir(to_bngir(m_scope, version="0.2"))
    assert semantic_equal(m_scope, rt_scope) is True

    b_expr_act = """
begin model
begin parameters
  t0 10
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  A() -> 0 0.01
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>30*60, n_steps=>24*60})
"""
    m_act = _load_bngl(b_expr_act)
    rt_act = from_bngir(to_bngir(m_act, version="0.2"))
    bngl_act = rt_act.to_bngl()
    assert 't_end=>"30*60"' not in bngl_act
    assert 'n_steps=>"24*60"' not in bngl_act
    assert semantic_equal(m_act, rt_act) is True
