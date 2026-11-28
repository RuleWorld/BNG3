"""Focused regression tests for Audit Wave 3: BNGIR, semantic_equal, CRN API,
scan/sensitivity, JAX ODE/SSA, CLI, and PyBioNetGen modelapi fixes.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pytest
from click.testing import CliRunner

import bionetgen
from bionetgen import _bionetgen_cpp as _cpp
from bionetgen.bngir import (
    EqualityUndecided,
    _as_bngl_v02,
    _parse_document,
    from_bngir,
    semantic_equal,
    to_bngir,
)
from bionetgen.cli import main as cli_main


def _load_bngl(source: str, tmp_path=None, name: str = "model.bngl"):
    if tmp_path is not None:
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        return bionetgen.load(str(path))
    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


# ---------------------------------------------------------------------------
# RULEHUB-09 & ETH-17: BNGIR unbound site formatting, setConcentration, eBNGL
# ---------------------------------------------------------------------------


def test_rulehub09_numeric_state_unbound_site_roundtrip():
    src = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin reaction rules
  A(s~0) -> A(s~1) k
end reaction rules
end model
"""
    m = _load_bngl(src)
    ir = to_bngir(m, version="0.2")
    rendered = _as_bngl_v02(_parse_document(ir))
    assert "s~0." not in rendered
    assert "s~1." not in rendered
    m_rt = from_bngir(ir)
    assert semantic_equal(m, m_rt) is True


def test_rulehub09_setconcentration_action_roundtrip_no_double_quoting():
    src = """begin model
begin molecule types
  Epi(r)
end molecule types
begin seed species
  Epi(r) 0
end seed species
begin observables
  Molecules EpiTot Epi()
end observables
begin reaction rules
  Epi(r) -> 0 0.1
end reaction rules
end model
begin actions
  generate_network({overwrite=>1})
  setConcentration("Epi(r)", 100)
end actions
"""
    m = _load_bngl(src)
    ir = to_bngir(m, version="0.2")
    m_rt = from_bngir(ir)
    orig_acts = [(a.name, dict(a.arguments)) for a in m._model.actions]
    rt_acts = [(a.name, dict(a.arguments)) for a in m_rt._model.actions]
    assert rt_acts == orig_acts
    assert semantic_equal(m, m_rt) is True


def test_eth17_ebngl_roundtrip_single_arrhenius_and_unbound_energy_pattern():
    src = """begin model
begin parameters
  phi 0.5
  Ea 1.0
  G 0.5
  W 0.2
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1) G
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
"""
    m = _load_bngl(src)
    ir = to_bngir(m, version="0.2")
    rendered = _as_bngl_v02(_parse_document(ir))
    assert "A(s~1!?)" not in rendered
    assert "s~0." not in rendered
    assert "s~1." not in rendered
    assert rendered.count("Arrhenius(") == 1
    m_rt = from_bngir(ir)
    assert semantic_equal(m, m_rt) is True


# ---------------------------------------------------------------------------
# B1, B2, B3, B4, B5, B8, PERF-10: BNGIR & semantic_equal soundness
# ---------------------------------------------------------------------------


def test_b1_semantic_equal_respects_bound_parameters_in_observable_rates_and_functions():
    obs_tpl = """begin model
begin parameters
  k {k}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules ObsA A()
  Molecules ObsB B()
end observables
begin reaction rules
  A() -> B() k*ObsA
end reaction rules
end model
"""
    m1 = _load_bngl(obs_tpl.format(k=1))
    m2 = _load_bngl(obs_tpl.format(k=999))
    assert semantic_equal(m1, m2) is False

    fn_tpl = """begin model
begin parameters
  p {p}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin functions
  f() = p * 2
end functions
begin reaction rules
  A() -> B() 1
end reaction rules
end model
"""
    assert (
        semantic_equal(_load_bngl(fn_tpl.format(p=1)), _load_bngl(fn_tpl.format(p=999)))
        is False
    )

    arg_fn_1 = """begin model
begin parameters
  p 1
end parameters
begin molecule types
  A()
end molecule types
begin functions
  f(x) = p * x
end functions
end model
"""
    arg_fn_2 = """begin model
begin parameters
  p 999
end parameters
begin molecule types
  A()
end molecule types
begin functions
  f(x) = x * p
end functions
end model
"""
    with pytest.raises(EqualityUndecided):
        semantic_equal(_load_bngl(arg_fn_1), _load_bngl(arg_fn_2))


def test_b2_semantic_equal_detects_swapped_totalrate_in_compartmental_models():
    m1 = _load_bngl("""begin model
begin parameters
  k 0.05
end parameters
begin compartments
  c 3 10
end compartments
begin molecule types
  A()
  B()
  C()
  D()
  E()
end molecule types
begin seed species
  @c:A() 10
  @c:B() 10
  @c:D() 10
end seed species
begin observables
  Molecules ObsC @c:C()
  Molecules ObsE @c:E()
end observables
begin reaction rules
  @c:A() + @c:B() -> @c:C() k TotalRate
  @c:A() + @c:D() -> @c:E() k
end reaction rules
end model
""")
    m2 = _load_bngl("""begin model
begin parameters
  k 0.05
end parameters
begin compartments
  c 3 10
end compartments
begin molecule types
  A()
  B()
  C()
  D()
  E()
end molecule types
begin seed species
  @c:A() 10
  @c:B() 10
  @c:D() 10
end seed species
begin observables
  Molecules ObsC @c:C()
  Molecules ObsE @c:E()
end observables
begin reaction rules
  @c:A() + @c:B() -> @c:C() k
  @c:A() + @c:D() -> @c:E() k TotalRate
end reaction rules
end model
""")
    assert semantic_equal(m1, m2) is False


def test_b3_symmetric_energy_pattern_automorphism_divisor():
    tpl = """begin model
begin parameters
  phi 0.5
  Ea 1.0
  Gdim 2.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin observables
  Molecules Dimer A(b!1).A(b!1)
end observables
begin energy patterns
  {ep}
end energy patterns
begin reaction rules
  A(b) + A(b) <-> A(b!1).A(b!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    m_dimer = _load_bngl(tpl.format(ep="A(b!1).A(b!1) Gdim"))
    m_bound = _load_bngl(tpl.format(ep="A(b!+) Gdim"))
    m_dimer_2x = _load_bngl(tpl.format(ep="A(b!1).A(b!1) 2*Gdim"))

    # A(b!1).A(b!1) has |Aut|=2 -> 1*Gdim per dimer; A(b!+) matches twice -> 2*Gdim
    assert semantic_equal(m_dimer, m_bound) is False
    assert semantic_equal(m_dimer_2x, m_bound) is True


def test_b4_renamed_symmetric_models_with_undecided_function_raise_undecided():
    m1 = _load_bngl("""begin model
begin parameters
  k 1
  x 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules ObsA A()
end observables
begin functions
  f() = sin(x)^2 + cos(x)^2
end functions
begin reaction rules
  A() -> 0 k
  B() -> 0 k
end reaction rules
end model
""")
    m2 = _load_bngl("""begin model
begin parameters
  k 1
  x 2
end parameters
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 10
  Y() 0
end seed species
begin observables
  Molecules ObsX X()
end observables
begin functions
  f() = 1
end functions
begin reaction rules
  X() -> 0 k
  Y() -> 0 k
end reaction rules
end model
""")
    with pytest.raises(EqualityUndecided):
        semantic_equal(m1, m2)


def test_b5_v01_preserves_arrhenius_casing_and_semantic_equal_distinguishes_case():
    tpl = """begin model
begin parameters
  phi 0.5
  Ea 1.0
  G 0.5
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
  A(s~p) G
end energy patterns
begin reaction rules
  A(s~u) <-> A(s~p) {law}(phi, Ea)
end reaction rules
end model
"""
    m_upper = _load_bngl(tpl.format(law="Arrhenius"))
    m_lower = _load_bngl(tpl.format(law="arrhenius"))

    ir_v01 = to_bngir(m_upper, version="0.1")
    assert "Arrhenius(" in ir_v01
    m_rt = from_bngir(ir_v01)
    orig_val = m_upper.simulate(t_end=2.0, n_steps=5).observables["Ap"][-1]
    rt_val = m_rt.simulate(t_end=2.0, n_steps=5).observables["Ap"][-1]
    assert rt_val == pytest.approx(orig_val, rel=1e-6)
    assert rt_val > 2.5

    # semantic_equal must NEVER certify valid Arrhenius equal to lowercase arrhenius
    with pytest.raises(EqualityUndecided):
        semantic_equal(m_upper, m_lower)


def test_b8_bngir_preserves_symbolic_compartment_volume_expressions():
    src = """begin model
begin parameters
  Vc 5.0
  k 0.2
end parameters
begin compartments
  c 3 Vc
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  @c:A() 10
end seed species
begin observables
  Molecules ObsB @c:B()
end observables
begin reaction rules
  @c:A() + @c:A() -> @c:B() k
end reaction rules
end model
"""
    m = _load_bngl(src)
    for ver in ("0.1", "0.2"):
        m_rt = from_bngir(to_bngir(m, version=ver))
        assert "c 3 Vc" in m_rt.to_bngl()
        m_rt.set_parameter("Vc", 50.0)
        m_ref = _load_bngl(src)
        m_ref.set_parameter("Vc", 50.0)
        v_rt = m_rt.simulate(t_end=2.0, n_steps=10).observables["ObsB"][-1]
        v_ref = m_ref.simulate(t_end=2.0, n_steps=10).observables["ObsB"][-1]
        assert v_rt == pytest.approx(v_ref, rel=1e-6)


def test_b21_v01_preserves_prefix_compartment_transport_semantics():
    src = """begin model
begin parameters
  k1 0.5
end parameters
begin compartments
  EC 3 1
  PM 2 1 EC
  CP 3 1 PM
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  @PM:A(b!1).B(a!1) 10
end seed species
begin observables
  Molecules A_cp @CP:A()
  Molecules B_cp @CP:B()
end observables
begin reaction rules
  @PM:A(b!+) -> @CP:A(b!+) k1 MoveConnected
end reaction rules
end model
"""
    m = _load_bngl(src)
    m_rt = from_bngir(to_bngir(m, version="0.1"))
    orig_res = m.simulate(t_end=2.0, n_steps=5)
    rt_res = m_rt.simulate(t_end=2.0, n_steps=5)
    assert rt_res.observables["A_cp"][-1] == pytest.approx(
        orig_res.observables["A_cp"][-1], abs=1e-9
    )
    assert rt_res.observables["B_cp"][-1] == pytest.approx(
        orig_res.observables["B_cp"][-1], abs=1e-9
    )


def test_perf10_large_state_space_does_not_oom_or_hang():
    states_l = "~".join(f"s{i}" for i in range(12))
    states_r = "~".join(f"t{i}" for i in range(12))
    m1 = _load_bngl(f"""begin model
begin molecule types
  A(c~{states_l})
end molecule types
begin seed species
  A(c~s0) 10
end seed species
begin reaction rules
  A(c~s0) -> A(c~s1) 1.0
end reaction rules
end model
""")
    m2 = _load_bngl(f"""begin model
begin molecule types
  B(d~{states_r})
end molecule types
begin seed species
  B(d~t0) 10
end seed species
begin reaction rules
  B(d~t0) -> B(d~t1) 1.0
end reaction rules
end model
""")
    t0 = time.perf_counter()
    res = semantic_equal(m1, m2)
    elapsed = time.perf_counter() - t0
    assert res is True
    assert elapsed < 5.0


# ---------------------------------------------------------------------------
# B9, B10, SSA-15: BioNetGenModel, CRN API, PSA/PLA options
# ---------------------------------------------------------------------------


def test_b9_remove_parameter_after_set_parameter_no_keyerror():
    m = _load_bngl("""begin model
begin parameters
  k 1.0
  unused 2.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules ObsB B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    m.set_parameter("unused", 5.0)
    m.remove_parameter("unused")
    assert all(p.name != "unused" for p in m.parameters)
    # Subsequent topology edit must also succeed cleanly.
    m.add_parameter("fresh", 3.0)
    assert m.get_parameter("fresh").value == pytest.approx(3.0)


def test_b10_crn_rate_law_types_constant_species_and_reverse_labels():
    m = _load_bngl("""begin model
begin parameters
  km 2.0
  kcat 3.0
  kf 1.0
  kr 0.5
  n 2.0
end parameters
begin molecule types
  S()
  P()
  X()
  A()
  B()
end molecule types
begin seed species
  S() 10
  $X() 10
  A() 5
end seed species
begin observables
  Molecules ObsS S()
end observables
begin functions
  mm_rate() = kcat * ObsS / (km + ObsS)
  time_rate() = kf * (1 + time())
end functions
begin reaction rules
  R_mm_tot: S() -> P() mm_rate() TotalRate
  R_func: S() -> P() mm_rate()
  R_sat: S() -> P() Sat(kcat, km)
  R_hill: S() -> P() Hill(kcat, km, n)
  R_time: S() -> P() time_rate()
  R_fix: X() -> P() kcat
  R_rev: A() <-> B() kf, kr
end reaction rules
end model
""")
    crn = m.to_crn()
    by_rule = {
        r["rate_law"]["rule_name"]: r["rate_law"]["type"] for r in crn["reactions"]
    }
    assert by_rule["R_mm_tot"] == "total_rate"
    assert by_rule["R_func"] == "functional"
    assert by_rule["R_sat"] == "sat"
    assert by_rule["R_hill"] == "hill"
    assert by_rule["R_time"] == "time_dependent"
    assert by_rule["R_fix"] == "mass_action"
    assert by_rule["R_rev"] == "mass_action"
    assert by_rule["_reverse__R_rev"] == "mass_action"

    # Fixed species $X() must expose is_constant=True and have zero net stoichiometry row
    const_species = [s for s in m.species if s.is_constant]
    assert len(const_species) == 1
    assert "$X()" in const_species[0].name
    assert crn["species"][const_species[0].index]["is_constant"] is True
    assert np.all(m.stoichiometric_matrix[const_species[0].index, :] == 0)


def test_ssa15_psa_and_pla_forward_seed_sample_times_and_check_product_scale():
    m = _load_bngl("""begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 200
end seed species
begin observables
  Molecules ObsA A()
  Molecules ObsB B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
""")
    for method in ("psa", "pla"):
        r1 = m.simulate(method=method, t_end=2.0, n_steps=5, seed=42)
        r2 = m.simulate(method=method, t_end=2.0, n_steps=5, seed=42)
        np.testing.assert_array_equal(r1.observables["ObsA"], r2.observables["ObsA"])

        rs = m.simulate(
            method=method, t_end=1.5, n_steps=0, sample_times=[0.0, 0.3, 1.5], seed=7
        )
        np.testing.assert_allclose(rs.time, [0.0, 0.3, 1.5])

    # check_product_scale must be accepted for PSA (both truthy and falsy)
    r_on = m.simulate(
        method="psa", t_end=1.0, n_steps=4, seed=42, check_product_scale=1.0
    )
    r_off = m.simulate(
        method="psa", t_end=1.0, n_steps=4, seed=42, check_product_scale=False
    )
    assert len(r_on.time) == 5
    assert len(r_off.time) == 5


# ---------------------------------------------------------------------------
# B11, B12, B13: Scan & sensitivity analysis
# ---------------------------------------------------------------------------


def test_b11_sensitivity_preserves_dependent_parameter_expressions(tmp_path):
    m = _load_bngl(
        """begin model
begin parameters
  k2 2 * k1
  k1 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10.0
end seed species
begin observables
  Molecules ObsA A()
  Molecules ObsB B()
end observables
begin reaction rules
  A() -> B() k2
end reaction rules
end model
""",
        tmp_path=tmp_path,
        name="sens_dep.bngl",
    )
    sens = m.sensitivity_analysis(t_end=1.0, n_steps=10, delta=1e-4)
    k1_idx = sens.parameter_names.index("k1")
    # Exact: A(t) = 10 * exp(-2 * k1 * t) => d ln A / d ln k1 = -2.0 at t=1
    assert sens.matrix[k1_idx, 0] == pytest.approx(-2.0, rel=1e-3)
    # Dependency k2 = 2*k1 must still be intact after sensitivity_analysis
    m.set_parameter("k1", 3.0)
    assert m.get_parameter("k2").value == pytest.approx(6.0)


def test_b12_parallel_scan_and_sensitivity_respect_in_memory_mutations(tmp_path):
    m = _load_bngl(
        """begin model
begin parameters
  k1 1.0
  k2 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10.0
end seed species
begin observables
  Molecules ObsA A()
end observables
begin reaction rules
  A() -> B() k1 + k2
end reaction rules
end model
""",
        tmp_path=tmp_path,
        name="sens_par.bngl",
    )
    m.set_parameter("k2", 5.0)

    sens_ser = m.sensitivity_analysis(
        parameters=["k1"], t_end=1.0, n_steps=10, delta=1e-3, parallel=0
    )
    sens_par = m.sensitivity_analysis(
        parameters=["k1"], t_end=1.0, n_steps=10, delta=1e-3, parallel=2
    )
    assert sens_par.matrix[0, 0] == pytest.approx(-1.0, rel=1e-3)
    assert sens_par.matrix[0, 0] == pytest.approx(sens_ser.matrix[0, 0], rel=1e-9)

    scan_ser = m.parameter_scan(
        "k1", values=[1.0, 2.0], t_end=1.0, n_steps=10, parallel=0
    )
    scan_par = m.parameter_scan(
        "k1", values=[1.0, 2.0], t_end=1.0, n_steps=10, parallel=2
    )
    np.testing.assert_allclose(
        scan_par.final("ObsA"), scan_ser.final("ObsA"), rtol=1e-9
    )

    scan2d_ser = m.parameter_scan_2d(
        "k1", [1.0, 2.0], "k2", [5.0, 6.0], t_end=1.0, n_steps=10, parallel=0
    )
    scan2d_par = m.parameter_scan_2d(
        "k1", [1.0, 2.0], "k2", [5.0, 6.0], t_end=1.0, n_steps=10, parallel=2
    )
    np.testing.assert_allclose(
        scan2d_par.final("ObsA"), scan2d_ser.final("ObsA"), rtol=1e-9
    )


def test_b13_sensitivity_rank_sorts_nan_last():
    m = _load_bngl("""begin model
begin parameters
  k0 0.0
  k1 1.0
  k2 2.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10.0
end seed species
begin observables
  Molecules ObsA A()
end observables
begin reaction rules
  A() -> B() k0 + k1 + k2
end reaction rules
end model
""")
    sens = m.sensitivity_analysis(t_end=1.0, n_steps=10, delta=1e-3)
    ranked = sens.rank("ObsA")
    assert [name for name, _ in ranked[:2]] == ["k2", "k1"]
    assert ranked[-1][0] == "k0"
    assert math.isnan(ranked[-1][1])


# ---------------------------------------------------------------------------
# B14, B15, B16, B17, B18: JAX ODE & JAX SSA
# ---------------------------------------------------------------------------


def test_b14_jax_ode_compartment_volume_scaling_dynamic_and_parameters():
    jax_ode = pytest.importorskip("bionetgen.jax_ode")
    pytest.importorskip("jax")

    m = _load_bngl("""begin model
begin parameters
  k 1.0
end parameters
begin compartments
  c 3 10.0
end compartments
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  @c:A() 10.0
  @c:B() 10.0
end seed species
begin observables
  Molecules ObsC @c:C()
end observables
begin reaction rules
  @c:A() + @c:B() -> @c:C() k
end reaction rules
end model
""")
    native_c = m.simulate(t_end=1.0, n_steps=100).observables["ObsC"][-1]
    static_c = jax_ode.simulate_jax_ode(m, t_end=1.0, n_steps=100)["concentrations"][
        -1, 2
    ]
    params_c = jax_ode.simulate_jax_ode(
        m, t_end=1.0, n_steps=100, parameters={"k": 1.0}
    )["concentrations"][-1, 2]
    assert native_c == pytest.approx(5.0, rel=1e-4)
    assert static_c == pytest.approx(native_c, rel=1e-4)
    assert params_c == pytest.approx(native_c, rel=1e-4)

    m_dyn = _load_bngl("""begin model
begin parameters
  k 1.0
end parameters
begin compartments
  c 3 10.0
end compartments
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  @c:A() 10.0
  @c:B() 10.0
end seed species
begin observables
  Molecules ObsC @c:C()
end observables
begin reaction rules
  @c:A() + @c:B() -> @c:C() k + 0*time()
end reaction rules
end model
""")
    dyn_c = jax_ode.simulate_jax_ode(m_dyn, t_end=1.0, n_steps=100)["concentrations"][
        -1, 2
    ]
    assert dyn_c == pytest.approx(native_c, rel=1e-4)


def test_b15_jax_ode_differentiates_through_dependent_parameter_expressions():
    jax = pytest.importorskip("jax")
    jnp = pytest.importorskip("jax.numpy")
    jax_ode = pytest.importorskip("bionetgen.jax_ode")

    m = _load_bngl("""begin model
begin parameters
  k2 2 * k1
  k1 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10.0
end seed species
begin observables
  Molecules ObsA A()
end observables
begin reaction rules
  A() -> B() k2
end reaction rules
end model
""")

    def f(k1):
        return jax_ode.simulate_jax_ode(
            m, t_end=1.0, n_steps=200, parameters={"k1": k1}, return_jax=True
        )["concentrations"][-1, 0]

    val_k5 = float(f(jnp.array(5.0)))
    assert val_k5 == pytest.approx(10.0 * math.exp(-10.0), rel=1e-3)

    grad_k1 = float(jax.grad(f)(jnp.array(1.0)))
    assert grad_k1 == pytest.approx(-20.0 * math.exp(-2.0), rel=1e-3)


def test_b16_jax_ode_fails_closed_on_delayed_reactions_and_algebraic_rules():
    jax_ode = pytest.importorskip("bionetgen.jax_ode")
    pytest.importorskip("jax")

    m_delay = _load_bngl("""begin model
begin parameters
  k 1.0
  tau 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules ObsB B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
""")
    with pytest.raises((NotImplementedError, RuntimeError)):
        jax_ode.simulate_jax_ode(m_delay, t_end=2.0, n_steps=20)

    m_alg = _load_bngl("""begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
end model
""")
    m_alg._algebraic_rules = [("alg_0", "A - 10")]
    with pytest.raises((NotImplementedError, RuntimeError)):
        jax_ode.simulate_jax_ode(m_alg, t_end=1.0, n_steps=10)


def test_b17_jax_ode_supports_standard_sat_mm_and_hill_arities():
    jax_ode = pytest.importorskip("bionetgen.jax_ode")
    pytest.importorskip("jax")

    for rule_line in (
        "A() -> B() Sat(kcat, Km)",
        "A() -> B() MM(kcat, Km)",
        "A() -> B() Hill(kcat, Km, n)",
    ):
        m = _load_bngl(f"""begin model
begin parameters
  kcat 2.0
  Km 5.0
  n 2.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10.0
end seed species
begin observables
  Molecules ObsB B()
end observables
begin reaction rules
  {rule_line}
end reaction rules
end model
""")
        native_b = m.simulate(t_end=2.0, n_steps=50).observables["ObsB"][-1]
        jax_b = jax_ode.simulate_jax_ode(m, t_end=2.0, n_steps=200)["concentrations"][
            -1, 1
        ]
        assert jax_b == pytest.approx(native_b, rel=1e-3), f"Mismatch on {rule_line}"

    # Two-reactant self-consistent MM(kcat, Km)
    m_mm2 = _load_bngl("""begin model
begin parameters
  kcat 2.0
  Km 5.0
end parameters
begin molecule types
  S()
  E()
  P()
end molecule types
begin seed species
  S() 10.0
  E() 2.0
end seed species
begin observables
  Molecules ObsP P()
end observables
begin reaction rules
  S() + E() -> P() + E() MM(kcat, Km)
end reaction rules
end model
""")
    native_p = m_mm2.simulate(t_end=2.0, n_steps=50).observables["ObsP"][-1]
    jax_p = jax_ode.simulate_jax_ode(m_mm2, t_end=2.0, n_steps=200)["concentrations"][
        -1, 2
    ]
    assert jax_p == pytest.approx(native_p, rel=1e-3)


def test_b18_jax_ssa_never_fires_zero_propensity_or_goes_negative():
    jax_ssa = pytest.importorskip("bionetgen.jax_ssa")
    pytest.importorskip("jax")

    # Overflowing propensity on channel 1 must fail closed rather than firing channel 0 (A=0)
    m_overflow = _load_bngl("""begin model
begin molecule types
  A()
  B()
  Z()
end molecule types
begin seed species
  A() 0
  B() 1000
end seed species
begin observables
  Molecules ObsA A()
end observables
begin reaction rules
  A() -> Z() 1.0
  B() + B() -> B() 1e35
end reaction rules
end model
""")
    with pytest.raises(ValueError, match="overflow"):
        jax_ssa.simulate(
            m_overflow, batch_size=5, t_end=1.0, n_steps=2, max_steps=10, base_seed=1
        )

    # Large finite dynamic range with zero-propensity channel 0: A must remain 0
    m_stiff = _load_bngl("""begin model
begin molecule types
  A()
  B()
  C()
  Z()
end molecule types
begin seed species
  A() 0
  B() 1000
  C() 50
end seed species
begin observables
  Molecules ObsA A()
end observables
begin reaction rules
  A() -> Z() 1.0
  B() -> B() 1e3
  C() -> Z() 0.49
end reaction rules
end model
""")
    res = jax_ssa.simulate(
        m_stiff, batch_size=16, t_end=0.05, n_steps=2, max_steps=200, base_seed=42
    )
    assert np.all(res["final_species"][:, 0] == 0)
    assert np.all(res["final_species"] >= 0)


# ---------------------------------------------------------------------------
# B21: CLI & PyBioNetGen modelapi
# ---------------------------------------------------------------------------


def test_b21_cli_method_choices_and_check_semantic_validation(tmp_path):
    runner = CliRunner()
    valid_path = tmp_path / "valid.bngl"
    valid_path.write_text(
        """begin model
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
begin observables
  Molecules ObsB B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
""",
        encoding="utf-8",
    )

    # nfcore and nfnext must be accepted; cvode and rm must be rejected
    for m_name in ("nfcore", "nfnext"):
        res = runner.invoke(
            cli_main,
            [
                "run",
                str(valid_path),
                "--method",
                m_name,
                "--t-end",
                "0.5",
                "--n-steps",
                "2",
            ],
        )
        assert res.exit_code == 0, res.output
    for bad in ("cvode", "rm"):
        res = runner.invoke(cli_main, ["run", str(valid_path), "--method", bad])
        assert res.exit_code != 0

    # check must reject undefined parameter with clean ERROR message (no traceback)
    bad_param = tmp_path / "bad_param.bngl"
    bad_param.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 undefined_param
end reaction rules
end model
""",
        encoding="utf-8",
    )
    res_p = runner.invoke(cli_main, ["check", str(bad_param)])
    assert res_p.exit_code == 1
    assert "ERROR:" in res_p.output
    assert "Traceback" not in res_p.output

    # check must reject undeclared molecule type when molecule types block exists
    bad_mol = tmp_path / "bad_mol.bngl"
    bad_mol.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  NonExistent() 10
end seed species
end model
""",
        encoding="utf-8",
    )
    res_m = runner.invoke(cli_main, ["check", str(bad_mol)])
    assert res_m.exit_code == 1
    assert "ERROR:" in res_m.output
    assert "NonExistent" in res_m.output


def test_b21_modelapi_block_setattr_setitem_and_delay_preservation(tmp_path):
    from bionetgen.modelapi.blocks import ModelBlock

    blk = ModelBlock()
    blk._recompile = True
    assert blk._recompile is True

    path = tmp_path / "delay_nc.bngl"
    path.write_text(
        """begin model
begin parameters
  k1 1.0
  tau 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules ObsB B()
end observables
begin reaction rules
  R1: A() -> B() k1 delay=tau NonConsuming
end reaction rules
end model
""",
        encoding="utf-8",
    )
    bm = bionetgen.bngmodel(str(path))
    bm.parameters["k1"] = 5.0
    text = str(bm)
    assert "k1 5.0" in text
    assert "delay=tau" in text
    assert "NonConsuming" in text

    out = tmp_path / "written.bngl"
    bm.write_model(str(out))
    written = out.read_text(encoding="utf-8")
    assert "k1 5.0" in written
    assert "delay=tau" in written
    assert "NonConsuming" in written


def test_bngir_roundtrip_preserves_hash_and_list_action_arguments(tmp_path):
    """from_bngir must not quote hash/list action args like max_stoich=>{A=>20}."""
    path = tmp_path / "hash_action.bngl"
    path.write_text(
        """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1, max_stoich=>{A=>20}})
simulate({method=>"ode", t_end=>1, n_steps=>5})
""",
        encoding="utf-8",
    )
    m = bionetgen.load(str(path))
    ir = bionetgen.to_bngir(m)
    m2 = bionetgen.from_bngir(ir)
    assert bionetgen.semantic_equal(m, m2) is True
    assert dict(m2.actions[0].arguments)["max_stoich"] == "{A=>20}"
