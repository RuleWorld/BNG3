"""Regression tests for Wave 1 audit fixes (actions, compiled rate laws/rules, bindings, security)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp


def _read_gdat(path: Path) -> dict[str, np.ndarray]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    header = next(line for line in lines if line.startswith("#"))
    cols = [c for c in header.lstrip("#").split() if c]
    rows = np.loadtxt([line for line in lines if not line.startswith("#")], ndmin=2)
    return {col: rows[:, idx] for idx, col in enumerate(cols)}


# ---------------------------------------------------------------------------
# 1. MEM-01: Unchecked .net reaction species indices
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rxn_line",
    [
        "1 0 5 k",
        "1 -5 1 k",
        "1 0,1 1 k",
        "1 1 999999 k",
        "1 abc 1 k",
    ],
)
def test_mem01_net_reaction_species_index_bounds(tmp_path: Path, rxn_line: str):
    net = tmp_path / "bad.net"
    net.write_text(
        f"""begin parameters
  1 k 1
end parameters
begin species
  1 A() 10
end species
begin reactions
  {rxn_line}
end reactions
begin groups
  1 Aobs 1
end groups
""",
        encoding="utf-8",
    )
    bngl = tmp_path / "model.bngl"
    bngl.write_text(
        """readFile({file=>"bad.net"})
simulate({method=>"ode",t_end=>1,n_steps=>5})
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        bionetgen.load(str(bngl)).execute()


# ---------------------------------------------------------------------------
# 2. SEC-02: Output path confinement against directory traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_line",
    [
        'writeFile({prefix=>"../escaped_wf", format=>"bngl", overwrite=>1})',
        'simulate({method=>"ode", t_end=>1, n_steps=>5, prefix=>"../escaped_sim"})',
        'writeXML({prefix=>"../escaped_xml"})',
        'writeSBML({prefix=>"../escaped_sbml"})',
        'writeNetwork({prefix=>"../escaped_net", overwrite=>1})',
    ],
)
def test_sec02_rejects_relative_parent_traversal(tmp_path: Path, action_line: str):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    bngl = sandbox / "traversal.bngl"
    bngl.write_text(
        f"""begin model
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
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({{overwrite=>1}})
{action_line}
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="escapes output directory"):
        bionetgen.load(str(bngl)).execute()
    escaped = list(tmp_path.glob("escaped_*"))
    assert escaped == []


def test_sec02_rejects_external_absolute_prefix_but_allows_sub_prefix(tmp_path: Path):
    sandbox = tmp_path / "sandbox"
    sub = sandbox / "sub"
    outside = tmp_path / "outside"
    sub.mkdir(parents=True)
    outside.mkdir()

    # External absolute prefix must be rejected.
    bngl_abs = sandbox / "abs_escape.bngl"
    bngl_abs.write_text(
        f"""begin model
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
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({{overwrite=>1}})
writeXML({{prefix=>"{outside / 'escaped'}"}})
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="escapes output directory"):
        bionetgen.load(str(bngl_abs)).execute()
    assert not (outside / "escaped.xml").exists()

    # Confined relative subdirectory prefix must work cleanly.
    bngl_ok = sandbox / "ok_sub.bngl"
    bngl_ok.write_text(
        """begin model
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
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeXML({prefix=>"sub/confined"})
simulate({method=>"ode", t_end=>1, n_steps=>2, prefix=>"sub/sim_out"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl_ok)).execute()
    assert (sub / "confined.xml").is_file()
    assert (sub / "sim_out.gdat").is_file()


# ---------------------------------------------------------------------------
# 3. MEM-05 & MEM-06: Integer option validation (negative n_steps, seed, level)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_line",
    [
        "simulate_nf({t_end=>1, n_steps=>-5, seed=>1})",
        "simulate_nf({t_end=>1, n_steps=>5, seed=>-1})",
        'simulate({method=>"ssa", t_end=>1, n_steps=>5, seed=>-1})',
        "writeSBML({level=>1e30})",
        'writeFile({format=>"sbml", level=>1e30, overwrite=>1})',
        "writeMfile({n_steps=>-5})",
        "writeCppfile({n_steps=>-5})",
        "writeCPYfile({n_steps=>-5})",
        "writeMEXfile({n_steps=>-5})",
    ],
)
def test_mem05_mem06_rejects_invalid_integer_action_options(
    tmp_path: Path, action_line: str
):
    bngl = tmp_path / "bad_int.bngl"
    bngl.write_text(
        f"""begin model
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
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({{overwrite=>1}})
{action_line}
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        bionetgen.load(str(bngl)).execute()


# ---------------------------------------------------------------------------
# 4. NFC-06: ActionDispatch uses suggestedTraversalLimit when utl omitted
# ---------------------------------------------------------------------------


def test_nfc06_nfcore_action_uses_suggested_traversal_limit(tmp_path: Path):
    bngl = tmp_path / "utl_chain.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k1 100.0
  k2 1.0
end parameters
begin molecule types
  M1(r, s~0~1)
  M2(l, r)
  M3(l, r)
  M4(l, r)
  M5(l, s~0~1)
end molecule types
begin seed species
  M1(r!1, s~0).M2(l!1, r!2).M3(l!2, r!3).M4(l!3, r!4).M5(l!4, s~0) 500
end seed species
begin observables
  Molecules M1_on M1(s~1)
  Molecules M5_on M5(s~1)
end observables
begin reaction rules
  R_flip: M1(s~0) -> M1(s~1) k1
  R_chain: M5(l!4, s~0).M4(r!4, l!3).M3(r!3, l!2).M2(r!2, l!1).M1(r!1, s~1) -> M5(l!4, s~1).M4(r!4, l!3).M3(r!3, l!2).M2(r!2, l!1).M1(r!1, s~1) k2
end reaction rules
end model
begin actions
  simulate({method=>"nfcore", t_end=>2.0, n_steps=>2, seed=>1, suffix=>"default"})
end actions
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    gdat = _read_gdat(tmp_path / "utl_chain_default.gdat")
    assert gdat["M1_on"][-1] == pytest.approx(500.0)
    # Theoretical mean = 500 * (1 - exp(-2)) ~= 432.3; with hardcoded UTL=3 it was 0.
    assert gdat["M5_on"][-1] > 350.0


# ---------------------------------------------------------------------------
# 5. ODE-07 / EXPR-15: Direct file-backed tfun in rules & print_functions=>1
# ---------------------------------------------------------------------------


def test_ode07_expr15_direct_rule_tfun_and_print_functions(tmp_path: Path):
    (tmp_path / "drive.tfun").write_text(
        "# time val\n0 1\n1 3\n2 5\n", encoding="utf-8"
    )
    bngl = tmp_path / "tfun_direct.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 0
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin functions
  f_drive() = tfun("drive.tfun", time)
end functions
begin reaction rules
  0 -> A() f_drive()
  0 -> B() tfun("drive.tfun", time)
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>2, n_steps=>4, print_functions=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    gdat = _read_gdat(tmp_path / "tfun_direct.gdat")
    # Integral of (1 + 2*t) from 0 to 2 is 6.0.
    assert gdat["A_obs"][-1] == pytest.approx(6.0, rel=1e-5)
    assert gdat["B_obs"][-1] == pytest.approx(6.0, rel=1e-5)
    assert gdat["f_drive"][0] == pytest.approx(1.0, rel=1e-6)
    assert gdat["f_drive"][-1] == pytest.approx(5.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 6. ODE-13 & ODE-14: continue=>1 after t_end <= 0 & setParameter after event
# ---------------------------------------------------------------------------


def test_ode13_continue_after_nonpositive_tend(tmp_path: Path):
    bngl = tmp_path / "cont_neg.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_start=>-3, t_end=>-1, n_steps=>4})
simulate({method=>"ode", t_end=>1, n_steps=>4, continue=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    gdat = _read_gdat(tmp_path / "cont_neg.gdat")
    assert len(gdat["time"]) == 9
    assert gdat["time"][0] == pytest.approx(-3.0)
    assert gdat["time"][-1] == pytest.approx(1.0)
    assert gdat["A_obs"][-1] == pytest.approx(100.0 * math.exp(-0.5 * 4.0), rel=1e-4)


def test_ode14_set_parameter_overrides_event_assigned_parameter(tmp_path: Path):
    bngl = tmp_path / "evt_setparam.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  0 -> A() k
end reaction rules
begin bng3_events version 1
  event "boost_k"
    trigger: time >= 0.5
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: k = 5.0
  end event
end bng3_events
end model
simulate({method=>"ode", t_end=>1.0, n_steps=>4})
setParameter("k", 10.0)
simulate({method=>"ode", t_end=>2.0, n_steps=>4, continue=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    gdat = _read_gdat(tmp_path / "evt_setparam.gdat")
    # Phase 1: 0.5*1 + 0.5*5 = 3.0; Phase 2: 3.0 + 1.0*10.0 = 13.0.
    assert gdat["A_obs"][4] == pytest.approx(3.0, rel=1e-4)
    assert gdat["A_obs"][-1] == pytest.approx(13.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 7. RULEHUB-10: setConcentration / addConcentration canonical matching
# ---------------------------------------------------------------------------


def test_rulehub10_set_and_add_concentration_noncanonical_component_order(
    tmp_path: Path,
):
    bngl = tmp_path / "setconc_order.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  X(b,a)
  MKK4(Y~0~P,KKK,AKT~0~P)
end molecule types
begin seed species
  X(b,a) 1
  MKK4(Y~0,KKK,AKT~0) 2
end seed species
begin observables
  Molecules X_obs X()
  Molecules M_obs MKK4()
end observables
begin reaction rules
  X(b,a) -> 0 0.0
end reaction rules
end model
generate_network({overwrite=>1})
setConcentration("X(b,a)", 50)
addConcentration("X(b,a)", 25)
setConcentration("MKK4(Y~0,KKK,AKT~0)", 40)
simulate({method=>"ode", t_end=>1, n_steps=>2})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    gdat = _read_gdat(tmp_path / "setconc_order.gdat")
    assert gdat["X_obs"][0] == pytest.approx(75.0)
    assert gdat["M_obs"][0] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# 8. EXPR-18: Unknown / misspelled actions fail cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_action", ["totallyBogusAction()", "writeBogus()"])
def test_expr18_unknown_action_raises(tmp_path: Path, bad_action: str):
    bngl = tmp_path / "bad_action.bngl"
    bngl.write_text(
        f"""begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
end model
{bad_action}
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Unknown action"):
        bionetgen.load(str(bngl)).execute()


# ---------------------------------------------------------------------------
# 9. NFC-04: Symmetry factor for symmetric vs asymmetric identical reactants
# ---------------------------------------------------------------------------


def test_nfc04_symmetry_factor_symmetric_vs_asymmetric_rules(tmp_path: Path):
    # Symmetric state-change rule must emit symmetry_factor="0.5"
    sym_bngl = tmp_path / "sym_state.bngl"
    sym_bngl.write_text(
        """begin model
begin parameters
  k 0.005
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 200
end seed species
begin observables
  Molecules A0 A(s~0)
end observables
begin reaction rules
  R_sym: A(s~0) + A(s~0) -> A(s~1) + A(s~1) k
end reaction rules
end model
""",
        encoding="utf-8",
    )
    sym_model = bionetgen.load(str(sym_bngl))
    sym_xml = tmp_path / "sym_state.xml"
    sym_model.write_xml(str(sym_xml))
    assert 'symmetry_factor="0.5"' in sym_xml.read_text(encoding="utf-8")

    # Asymmetric rules must NOT emit symmetry_factor="0.5"
    asym_bngl = tmp_path / "asym_rules.bngl"
    asym_bngl.write_text(
        """begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(s~0~1~2,a,b)
end molecule types
begin seed species
  A(s~0,a,b) 100
end seed species
begin observables
  Molecules A0 A(s~0)
end observables
begin reaction rules
  R_trans: A(s~0) + A(s~0) -> A(s~0) + A(s~1) k
  R_split: A(s~0) + A(s~0) -> A(s~1) + A(s~2) k
  R_htt: A(a,b) + A(a,b) -> A(a!1,b).A(a,b!1) k
end reaction rules
end model
""",
        encoding="utf-8",
    )
    asym_model = bionetgen.load(str(asym_bngl))
    asym_xml = tmp_path / "asym_rules.xml"
    asym_model.write_xml(str(asym_xml))
    assert "symmetry_factor=" not in asym_xml.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 10. ODE-11 / ODE-18 / ODE-22: MM(Km=0), Hill(n=0), div-by-zero
# ---------------------------------------------------------------------------


def test_ode11_mm_zero_km_exact_limiting_rate(tmp_path: Path):
    bngl = tmp_path / "mm_zero_km.bngl"
    bngl.write_text(
        """begin model
begin parameters
  kcat 1.0
  Km 0.0
end parameters
begin molecule types
  S()
  E()
  P()
end molecule types
begin seed species
  S() 200
  E() 100
  P() 0
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  S() + E() -> P() + E() MM(kcat, Km)
end reaction rules
end model
""",
        encoding="utf-8",
    )
    res = bionetgen.load(str(bngl)).simulate(method="ode", t_end=3.0, n_steps=30)
    # Exact Km->0+ limit: S(1)=100, then S(t)=100*exp(-(t-1)) => S(3)=100*exp(-2).
    assert res.observables["S_obs"][-1] == pytest.approx(
        100.0 * math.exp(-2.0), rel=1e-3
    )


def test_ode22_hill_zero_exponent_nonnegative_substrate(tmp_path: Path):
    bngl = tmp_path / "hill_n0.bngl"
    bngl.write_text(
        """begin model
begin parameters
  Vmax 10.0
  Kh 5.0
  n 0.0
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 10
  P() 0
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  S() -> P() Hill(Vmax, Kh, n)
end reaction rules
end model
""",
        encoding="utf-8",
    )
    res = bionetgen.load(str(bngl)).simulate(method="ode", t_end=5.0, n_steps=50)
    assert float(np.min(res.observables["S_obs"])) >= -1e-6


def test_ode18_direct_rate_div_by_zero_does_not_silently_zero(tmp_path: Path):
    bngl = tmp_path / "div0.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 0
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  0 -> B() k / A_obs
end reaction rules
end model
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        bionetgen.load(str(bngl)).simulate(method="ode", t_end=1.0, n_steps=5)


# ---------------------------------------------------------------------------
# 11. B5, B6, B11, NFC-22: bind_model & bind_nfsim fixes
# ---------------------------------------------------------------------------


def test_b5_b6_bind_model_preserves_arrhenius_casing_and_local_scope_prefix(
    tmp_path: Path,
):
    arr_bngl = tmp_path / "arr_case.bngl"
    arr_bngl.write_text(
        """begin model
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
  A(s~u) <-> A(s~p) Arrhenius(phi,Ea)
end reaction rules
end model
""",
        encoding="utf-8",
    )
    m_arr = bionetgen.load(str(arr_bngl))
    assert m_arr._model.reaction_rules[0].rates[0].startswith("Arrhenius(")

    scope_bngl = tmp_path / "local_scope.bngl"
    scope_bngl.write_text(
        """begin model
begin parameters
  k0 0.1
  k1 0.5
end parameters
begin molecule types
  A(b,s~u~p)
  B(a)
end molecule types
begin seed species
  A(b,s~u) 10
  A(b!1,s~u).B(a!1) 10
end seed species
begin observables
  Molecules Bcount B()
  Molecules Ap A(s~p)
end observables
begin functions
  rate_fn(x) = k0 + k1 * Bcount(x)
end functions
begin reaction rules
  %x:A(s~u) -> %x:A(s~p) rate_fn(x)
end reaction rules
end model
""",
        encoding="utf-8",
    )
    m_scope = bionetgen.load(str(scope_bngl))
    rule = m_scope._model.reaction_rules[0]
    assert rule.reactant_patterns[0].startswith("%x:")
    assert rule.product_patterns[0].startswith("%x:")


def test_b11_snapshot_and_restore_parameters_preserves_dependent_expressions(
    tmp_path: Path,
):
    bngl = tmp_path / "dep_param.bngl"
    bngl.write_text(
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
end observables
begin reaction rules
  A() -> B() k2
end reaction rules
end model
""",
        encoding="utf-8",
    )
    m = bionetgen.load(str(bngl))
    snap = m._model.snapshot_parameters()
    m._model.set_parameter("k2", 99.0)
    assert m._model.get_parameter("k2").value == pytest.approx(99.0)

    # Restoring the snapshot preserves k2's symbolic expression `2 * k1`.
    m._model.restore_parameters(snap)
    m._model.set_parameter("k1", 3.0)
    assert m._model.get_parameter("k2").value == pytest.approx(6.0)


def test_nfc22_simulate_nf_rejects_negative_seed(tmp_path: Path):
    bngl = tmp_path / "neg_seed.bngl"
    bngl.write_text(
        """begin model
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
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
""",
        encoding="utf-8",
    )
    m = bionetgen.load(str(bngl))
    with pytest.raises(ValueError, match="seed must be non-negative"):
        cpp.simulate_nf(m._model, t_end=1.0, n_steps=2, seed=-7)
