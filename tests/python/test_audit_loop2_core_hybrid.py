"""Regression tests for Loop 2 core graph matching, compartments, barriers, and hybrid refinement.

Covers:
- L2-03-01: UllmannSGIso single-site wildcard bond sharing (!+, !?) on double bonds, rings, and self-bonds
- BUG-L2-01: PatternMatching deduplication of wildcard bond embeddings on multi-bonded components
- L2-01-01 / L2-03-07d: 2D-surface precedence compartment inference for multi-molecule per-molecule compartments
- L2-11-05: Cycle detection in SpeciesGraph compartment parent traversal
- L2-10-12: Rejection of illegal wildcard bond-breaking rules
- L2-03-10: check_iso=>0 deduplication against post-canonical printed species keys
- L2-03-03..07 & L2-05-02: Hybrid model generation (molecule removal, rule-automorphism symmetry,
  complex synthesis, intramolecular bond breaking, scoped rates, identifier sanitization,
  compartment-aware StringID/serialization, CountUnique observables)
- L2-08-05, L2-08-07, L2-08-08, L2-08-09, L2-08-10, L2-10-08a: Barrier pattern context guards,
  Arrhenius/driven_by/TotalRate compile-time validation, and one-sided reversible local scopes
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from unittest import mock

import pytest

from _extdep import require_extension

require_extension()
import bionetgen
import bionetgen._bionetgen_cpp as cpp


def _load(bngl: str, tmp_path: Path, name: str = "model") -> bionetgen.BioNetGenModel:
    path = tmp_path / f"{name}.bngl"
    path.write_text(bngl, encoding="utf-8")
    return bionetgen.load(str(path))


def _generate_hybrid(bngl: str, tmp_path: Path, name: str = "model") -> Path:
    src = bngl.rstrip() + "\ngenerate_hybrid_model({overwrite=>1})\n"
    path = tmp_path / f"{name}.bngl"
    path.write_text(src, encoding="utf-8")
    m = bionetgen.load(str(path))
    m.execute()
    hpp = tmp_path / f"{name}_hpp.bngl"
    assert hpp.exists(), f"Expected hybrid output at {hpp}"
    return hpp


# ==============================================================================
# L2-03-01: Single-site wildcard bond sharing (!+, !?) in UllmannSGIso
# ==============================================================================


def test_l2_03_01_wildcard_bond_parallel_double_bond(tmp_path: Path):
    """A(b!1,c!+).B(a!1,d!+) and !? must match parallel double-bonded A(b!1,c!2).B(a!1,d!2)."""
    bngl = """
begin model
begin parameters
  k1 0.5
  k2 0.3
end parameters
begin molecule types
  A(b,c,s~0~1)
  B(a,d,s~0~1)
end molecule types
begin seed species
  A(b!1,c!2,s~0).B(a!1,d!2,s~0) 100
end seed species
begin observables
  Molecules ObsPlus A(b!1,c!+).B(a!1,d!+)
  Molecules ObsWild A(b!1,c!?).B(a!1,d!?)
  Molecules A_s1 A(s~1)
  Molecules B_s1 B(s~1)
end observables
begin reaction rules
  R_plus: A(b!1,c!+,s~0).B(a!1,d!+) -> A(b!1,c!+,s~1).B(a!1,d!+) k1
  R_wild: A(b!1,c!?).B(a!1,d!?,s~0) -> A(b!1,c!?).B(a!1,d!?,s~1) k2
end reaction rules
end model
"""
    model = _load(bngl, tmp_path, "double_bond")
    net = model.generate_network(max_iter=10)
    assert net.num_species == 4
    assert net.num_reactions == 4
    res = model.simulate(method="ode", t_end=5.0, n_steps=10)
    assert float(res.observables["ObsPlus"][-1]) == pytest.approx(100.0, rel=1e-6)
    assert float(res.observables["ObsWild"][-1]) == pytest.approx(100.0, rel=1e-6)
    assert float(res.observables["A_s1"][-1]) == pytest.approx(
        100.0 * (1.0 - math.exp(-0.5 * 5.0)), rel=1e-4
    )
    assert float(res.observables["B_s1"][-1]) == pytest.approx(
        100.0 * (1.0 - math.exp(-0.3 * 5.0)), rel=1e-4
    )


def test_l2_03_01_wildcard_bond_closed_ring_and_self_bond(tmp_path: Path):
    """Wildcard !+ pairs must match closing bonds of 3-rings and intra-molecule self-bonds."""
    ring_bngl = """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(l,r,s~0~1)
end molecule types
begin seed species
  A(l!1,r!2,s~0).A(l!2,r!3,s~0).A(l!3,r!1,s~0) 100
end seed species
begin observables
  Molecules ObsRing A(l!+,r!1).A(l!1,r!2).A(l!2,r!+)
  Molecules S1 A(s~1)
end observables
begin reaction rules
  R_ring: A(l!+,r!1,s~0).A(l!1,r!2).A(l!2,r!+) -> A(l!+,r!1,s~1).A(l!1,r!2).A(l!2,r!+) k
end reaction rules
end model
"""
    m_ring = _load(ring_bngl, tmp_path, "ring3")
    net_ring = m_ring.generate_network(max_iter=10)
    assert net_ring.num_species == 4
    assert net_ring.num_reactions == 3
    res_ring = m_ring.simulate(method="ode", t_end=5.0, n_steps=10)
    assert float(res_ring.observables["ObsRing"][0]) == pytest.approx(300.0, rel=1e-6)
    assert float(res_ring.observables["S1"][-1]) == pytest.approx(
        300.0 * (1.0 - math.exp(-0.5 * 5.0)), rel=1e-4
    )

    self_bngl = """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(b,b,s~0~1)
end molecule types
begin seed species
  A(b!1,b!1,s~0) 100
end seed species
begin observables
  Molecules S1 A(s~1)
end observables
begin reaction rules
  R_self: A(b!+,b!+,s~0) -> A(b!+,b!+,s~1) k
end reaction rules
end model
"""
    m_self = _load(self_bngl, tmp_path, "self_bond")
    net_self = m_self.generate_network(max_iter=10)
    assert net_self.num_species == 2
    assert net_self.num_reactions == 1
    res_self = m_self.simulate(method="ode", t_end=5.0, n_steps=10)
    assert float(res_self.observables["S1"][-1]) == pytest.approx(
        100.0 * (1.0 - math.exp(-0.5 * 5.0)), rel=1e-4
    )


# ==============================================================================
# BUG-L2-01: Multi-bonded component wildcard deduplication
# ==============================================================================


def test_bug_l2_01_multibond_wildcard_counted_once(tmp_path: Path):
    """A(b!+) and A(b!?) must count A(b!1!2).B(x!1,y!2) once, not twice."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b)
  B(x,y)
  P()
end molecule types
begin seed species
  A(b!1!2).B(x!1,y!2) 10
end seed species
begin observables
  Molecules A_bound A(b!+)
  Molecules A_any A(b!?)
  Molecules P_obs P()
end observables
begin reaction rules
  A(b!+) -> A(b!+) + P() k
end reaction rules
end model
"""
    model = _load(bngl, tmp_path, "multibond_wildcard")
    model.generate_network(max_iter=5)
    res = model.simulate(method="ode", t_end=1.0, n_steps=2)
    assert float(res.observables["A_bound"][0]) == pytest.approx(10.0, rel=1e-6)
    assert float(res.observables["A_any"][0]) == pytest.approx(10.0, rel=1e-6)
    assert float(res.observables["P_obs"][-1]) == pytest.approx(10.0, rel=1e-4)


# ==============================================================================
# L2-01-01: 2D-surface precedence for multi-molecule per-molecule compartments
# ==============================================================================


@pytest.mark.parametrize(
    "product_pattern",
    [
        "R(l,c!1)@PM.A(r!1)@CP",
        "A(r!1)@CP.R(l,c!1)@PM",
    ],
)
def test_l2_01_01_zero_order_synthesis_2d_surface_precedence(
    tmp_path: Path, product_pattern: str
):
    """Zero-order synthesis of R@PM.A@CP uses 2D surface PM (V_PM=2), not trailing CP (V_CP=5)."""
    bngl = f"""
begin model
begin parameters
  V_EC 10.0
  V_PM 2.0
  V_CP 5.0
  ksynRA 5.0
  kbind 0.001
end parameters
begin compartments
  EC 3 V_EC
  PM 2 V_PM EC
  CP 3 V_CP PM
end compartments
begin molecule types
  L(r)
  R(l,c)
  A(r)
end molecule types
begin seed species
  @EC:L(r) 100
end seed species
begin observables
  Molecules RA R(c!1)@PM.A(r!1)@CP
  Molecules LRA L(r!1)@EC.R(l!1,c!2)@PM.A(r!2)@CP
end observables
begin reaction rules
  0 -> {product_pattern} ksynRA
  L(r)@EC + R(l)@PM -> L(r!1)@EC.R(l!1)@PM kbind
end reaction rules
end model
"""
    model = _load(bngl, tmp_path, "comp_synth")
    net = model.generate_network(max_iter=10)
    # 3 species: @EC::L(r), @PM::A(r!1)@CP.R(c!1,l), @PM::A(r!1)@CP.L(r!2)@EC.R(c!1,l!2)
    assert net.num_species == 3
    assert net.num_reactions == 2
    res = model.simulate(method="ode", t_end=5.0, n_steps=10)
    # Total RA (free + L-bound) = V_PM * ksynRA * t = 2 * 5 * 5 = 50.0 (NOT V_CP * 5 * 5 = 125.0)
    assert float(res.observables["RA"][-1]) == pytest.approx(50.0, rel=1e-4)
    assert float(res.observables["LRA"][-1]) > 1.0


# ==============================================================================
# L2-11-05: Cyclic compartment parent hierarchy must fail fast, never hang
# ==============================================================================


@pytest.mark.parametrize(
    "comp_block",
    [
        "C1 3 1 C1\n  C2 3 1 C1",
        "C1 3 1 C2\n  C2 3 1 C1",
    ],
)
def test_l2_11_05_cyclic_compartment_hierarchy_fails_fast(comp_block: str):
    """Cyclic compartment parent chains must raise an error rather than hanging."""
    bngl = f"""
begin model
begin compartments
  {comp_block}
end compartments
begin molecule types
  A(b)
  B(b)
end molecule types
begin seed species
  A(b!1)@C1.B(b!1)@C2 10
end seed species
end model
"""
    with pytest.raises(RuntimeError, match="[Cc]ycl"):
        cpp.parse_string(bngl)


# ==============================================================================
# L2-10-12: Illegal wildcard bond-breaking rules must be rejected
# ==============================================================================


def test_l2_10_12_illegal_wildcard_bond_breaking_rejected(tmp_path: Path):
    """R(lig!+,p~P) -> R(lig,p~U) must abort instead of silently preserving the bond."""
    illegal_bngl = """
begin model
begin molecule types
  R(lig,p~U~P)
  L(r)
end molecule types
begin seed species
  R(lig!1,p~P).L(r!1) 10
end seed species
begin reaction rules
  R(lig!+,p~P) -> R(lig,p~U) 1.0
end reaction rules
end model
"""
    with pytest.raises(RuntimeError, match="wildcard bond breaking"):
        cpp.parse_string(illegal_bngl)

    # Valid rule that keeps !+ while breaking an explicit bond must still succeed
    valid_bngl = """
begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1!2).B(a!1).B(a!2) 10
end seed species
begin reaction rules
  A(b!1!+).B(a!1) -> A(b!+) + B(a) 1.0
end reaction rules
end model
"""
    m_valid = _load(valid_bngl, tmp_path, "valid_wildcard_unbind")
    net = m_valid.generate_network(max_iter=5)
    assert net.num_reactions >= 1


# ==============================================================================
# L2-03-10: check_iso=>0 must not emit duplicate printed species strings
# ==============================================================================


def test_l2_03_10_check_iso_zero_no_duplicate_printed_species(tmp_path: Path):
    """generate_network({check_iso=>0, max_agg=>3}) on A(b,b) must produce 3 unique species."""
    bngl = """
begin model
begin parameters
  kf 0.01
  kr 0.1
end parameters
begin molecule types
  A(b,b)
end molecule types
begin seed species
  A(b,b) 50
end seed species
begin observables
  Molecules Bound A(b!+)
end observables
begin reaction rules
  Bind: A(b) + A(b) <-> A(b!1).A(b!1) kf, kr
end reaction rules
end model
generate_network({overwrite=>1, max_agg=>3, check_iso=>0})
"""
    model = _load(bngl, tmp_path, "check_iso_0_trimer")
    net = model.generate_network(max_iter=10)
    assert net.num_species == 3
    assert net.num_reactions == 4


# ==============================================================================
# L2-03-03..07 & L2-05-02: HybridModelGenerator & RefineRule fixes
# ==============================================================================


def test_l2_03_03_hybrid_molecule_removal_degradation(tmp_path: Path):
    """Molecule-removal degradation A() -> 0 must delete A and liberate bonded B into B_pop."""
    bngl = """
begin model
begin parameters
  lumping_rate 1000
  kdeg 0.5
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 100
  A(b) 50
  B(a) 50
end seed species
begin observables
  Molecules Bfree B(a)
  Molecules Atot A()
end observables
begin reaction rules
  DegA: A() -> 0 kdeg DeleteMolecules
end reaction rules
begin population maps
  A(b!1).B(a!1) -> AB_pop() lumping_rate
  B(a) -> B_pop() lumping_rate
end population maps
end model
"""
    hpp = _generate_hybrid(bngl, tmp_path, "deg_bonded")
    hybrid = bionetgen.load(str(hpp))
    hybrid.generate_network(max_iter=10)
    res = hybrid.simulate(method="ode", t_end=5.0, n_steps=10)
    assert float(res.observables["Atot"][-1]) == pytest.approx(
        150.0 * math.exp(-0.5 * 5.0), rel=1e-3
    )
    assert float(res.observables["Bfree"][-1]) == pytest.approx(
        50.0 + 100.0 * (1.0 - math.exp(-0.5 * 5.0)), rel=1e-3
    )


def test_l2_03_04_hybrid_symmetry_asymmetric_homodimer_and_ring(tmp_path: Path):
    """Hybrid refinement must match exact rule-automorphism symmetry for asymmetric bind,
    symmetric homodimer dissociation, and symmetric 3-ring opening."""
    asym_bngl = """
begin model
begin parameters
  lumping_rate 1000
  k 0.01
end parameters
begin molecule types
  A(a,b)
end molecule types
begin seed species
  A(a,b) 100
end seed species
begin observables
  Molecules Afree A(a,b)
  Molecules Adimer A(a!1,b).A(a,b!1)
end observables
begin reaction rules
  R1: A(a,b) + A(a,b) -> A(a!1,b).A(a,b!1) k
end reaction rules
begin population maps
  A(a,b) -> A_pop() lumping_rate
end population maps
end model
"""
    orig = _load(asym_bngl, tmp_path, "asym_orig")
    orig.generate_network(max_iter=5)
    orig_res = orig.simulate(method="ode", t_end=5.0, n_steps=10)

    hpp_asym = _generate_hybrid(asym_bngl, tmp_path, "asym_hyb")
    hyb_asym = bionetgen.load(str(hpp_asym))
    hyb_asym.generate_network(max_iter=5)
    hyb_res = hyb_asym.simulate(method="ode", t_end=5.0, n_steps=10)
    assert float(hyb_res.observables["Afree"][-1]) == pytest.approx(
        float(orig_res.observables["Afree"][-1]), rel=1e-3
    )

    homodimer_bngl = """
begin model
begin parameters
  lumping_rate 1000
  kf 0.01
  kr 0.5
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 200
end seed species
begin observables
  Molecules Monomer A(b)
  Molecules Dimer A(b!1).A(b!1)
end observables
begin reaction rules
  Bind: A(b) + A(b) <-> A(b!1).A(b!1) kf, kr
end reaction rules
begin population maps
  A(b) -> A_pop() lumping_rate
  A(b!1).A(b!1) -> AA_pop() lumping_rate
end population maps
end model
"""
    orig_hd = _load(homodimer_bngl, tmp_path, "hd_orig")
    orig_hd.generate_network(max_iter=5)
    orig_hd_res = orig_hd.simulate(method="ode", t_end=5.0, n_steps=10)

    hpp_hd = _generate_hybrid(homodimer_bngl, tmp_path, "hd_hyb")
    hyb_hd = bionetgen.load(str(hpp_hd))
    hyb_hd.generate_network(max_iter=5)
    hyb_hd_res = hyb_hd.simulate(method="ode", t_end=5.0, n_steps=10)
    assert float(hyb_hd_res.observables["Monomer"][-1]) == pytest.approx(
        float(orig_hd_res.observables["Monomer"][-1]), rel=1e-3
    )
    assert float(hyb_hd_res.observables["Dimer"][-1]) == pytest.approx(
        float(orig_hd_res.observables["Dimer"][-1]), rel=1e-3
    )


def test_l2_03_05_hybrid_complex_synthesis_and_intramolecular_unbinding(tmp_path: Path):
    """Complex synthesis 0 -> A(b!1).B(a!1) and intramolecular ring opening must be preserved."""
    synth_bngl = """
begin model
begin parameters
  lumping_rate 1000
  ksyn 2.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  Syn: 0 -> A(b!1).B(a!1) ksyn
end reaction rules
begin population maps
  A(b) -> A_pop() lumping_rate
end population maps
end model
"""
    hpp_synth = _generate_hybrid(synth_bngl, tmp_path, "synth_complex")
    hyb_synth = bionetgen.load(str(hpp_synth))
    hyb_synth.generate_network(max_iter=5)
    res = hyb_synth.simulate(method="ode", t_end=5.0, n_steps=5)
    assert float(res.observables["AB"][-1]) == pytest.approx(10.0, rel=1e-4)

    intra_bngl = """
begin model
begin parameters
  lumping_rate 1000
  kr 0.2
end parameters
begin molecule types
  A(l,r)
end molecule types
begin seed species
  A(l!1,r!2).A(l!2,r!3).A(l!3,r!1) 100
end seed species
begin observables
  Molecules Ring3 A(l!1,r!2).A(l!2,r!3).A(l!3,r!1)
end observables
begin reaction rules
  Open: A(r!1).A(l!1) -> A(r).A(l) kr
end reaction rules
begin population maps
  A(l!1,r!2).A(l!2,r!3).A(l!3,r!1) -> Ring3_pop() lumping_rate
end population maps
end model
"""
    hpp_intra = _generate_hybrid(intra_bngl, tmp_path, "intra_open")
    text_intra = hpp_intra.read_text(encoding="utf-8")
    assert "Open_v1:" in text_intra
    assert "Open_v2:" in text_intra
    hyb_intra = bionetgen.load(str(hpp_intra))
    hyb_intra.generate_network(max_iter=5)
    res_intra = hyb_intra.simulate(method="ode", t_end=1.0, n_steps=2)
    # 3 equivalent bonds open at rate 3*kr = 0.6; Ring3 has rotational symmetry 3 -> 300 * exp(-0.6)
    assert float(res_intra.observables["Ring3"][-1]) == pytest.approx(
        300.0 * math.exp(-0.6), rel=1e-3
    )


def test_l2_03_06_hybrid_scoped_function_executable(tmp_path: Path):
    """generate_hybrid_model must preserve %x: on particle children and specialize population children."""
    bngl = """
begin model
begin parameters
  lumping_rate 1000
  k0 0.1
end parameters
begin molecule types
  A(b,s~0~1)
  B(a)
end molecule types
begin seed species
  A(b,s~0) 50
  B(a) 50
end seed species
begin observables
  Molecules nB B()
  Molecules Ap A(s~1)
end observables
begin functions
  f(x) = k0 * (1 + nB(x))
end functions
begin reaction rules
  Bind: A(b) + B(a) <-> A(b!1).B(a!1) 0.01, 0.1
  Phos: %x:A(s~0) -> %x:A(s~1) f(x)
end reaction rules
begin population maps
  A(b,s~0) -> A0_pop() lumping_rate
  B(a) -> B_pop() lumping_rate
end population maps
end model
"""
    orig = _load(bngl, tmp_path, "scoped_orig")
    orig.generate_network(max_iter=10)
    orig_res = orig.simulate(method="ode", t_end=3.0, n_steps=6)

    hpp = _generate_hybrid(bngl, tmp_path, "scoped_hyb")
    hyb = bionetgen.load(str(hpp))
    hyb.generate_network(max_iter=10)
    hyb_res = hyb.simulate(method="ode", t_end=3.0, n_steps=6)
    assert float(hyb_res.observables["Ap"][-1]) == pytest.approx(
        float(orig_res.observables["Ap"][-1]), rel=2e-2
    )


def test_l2_03_07_hybrid_param_names_compartments_and_serialization(tmp_path: Path):
    """Covers L2-03-07a (scaled expr param name), b (compartment StringID), c (no || leak), d (R@PM.L@EC + S@CP)."""
    # 7a: scaled compound rate 2*k must not emit invalid `(2 * k)_1`
    expr_rate_bngl = """
begin model
begin parameters
  lumping_rate 1000
  k 0.05
end parameters
begin molecule types
  A(b,b)
  L(r)
end molecule types
begin seed species
  A(b,b) 50
  L(r) 50
end seed species
begin observables
  Molecules AL A(b!1).L(r!1)
end observables
begin reaction rules
  R1: A(b) + L(r) -> A(b!1).L(r!1) 2*k
end reaction rules
begin population maps
  A(b,b) -> A_pop() lumping_rate
end population maps
end model
"""
    hpp_expr = _generate_hybrid(expr_rate_bngl, tmp_path, "expr_scaled")
    expr_text = hpp_expr.read_text(encoding="utf-8")
    assert "(2 * k)_" not in expr_text
    hyb_expr = bionetgen.load(str(hpp_expr))
    hyb_expr.generate_network(max_iter=5)

    # 7b: distinct compartment children @EC:Au_pop() and @CP:Au_pop() must not merge
    comp_pop_bngl = """
begin model
begin parameters
  lumping_rate 1000
  k 0.5
end parameters
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  A(s~u~p)
end molecule types
begin seed species
  @EC:A(s~u) 100
  @CP:A(s~u) 100
end seed species
begin observables
  Molecules Ap_EC @EC:A(s~p)
  Molecules Ap_CP @CP:A(s~p)
end observables
begin reaction rules
  Phos: A(s~u) -> A(s~p) k
end reaction rules
begin population maps
  @EC:A(s~u) -> Au_pop() lumping_rate
  @CP:A(s~u) -> Au_pop() lumping_rate
end population maps
end model
"""
    hpp_comp = _generate_hybrid(comp_pop_bngl, tmp_path, "comp_pop")
    hyb_comp = bionetgen.load(str(hpp_comp))
    hyb_comp.generate_network(max_iter=5)
    res_comp = hyb_comp.simulate(method="ode", t_end=2.0, n_steps=4)
    expected = 100.0 * (1.0 - math.exp(-0.5 * 2.0))
    assert float(res_comp.observables["Ap_EC"][-1]) == pytest.approx(expected, rel=1e-2)
    assert float(res_comp.observables["Ap_CP"][-1]) == pytest.approx(expected, rel=1e-2)

    # 7c & 7d: no `||EC,` syntax leak and R@PM.L@EC + S@CP retained
    comp_complex_bngl = """
begin model
begin parameters
  lumping_rate 1000
  k 0.5
  kf 0.01
end parameters
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  L(r)
  R(l,c,s~0~1)
  S(r)
end molecule types
begin seed species
  L(r!1)@EC.R(l!1,c,s~0)@PM 50
  S(r)@CP 50
end seed species
begin observables
  Molecules BoundS R(c!1)@PM.S(r!1)@CP
end observables
begin reaction rules
  Phos: L(r!1)@EC.R(l!1,s~0) -> L(r!1)@EC.R(l!1,s~1) k
  BindS: R(l!1,c)@PM.L(r!1)@EC + S(r)@CP -> R(l!1,c!2)@PM.L(r!1)@EC.S(r!2)@CP kf
end reaction rules
begin population maps
  S(r)@CP -> S_pop() lumping_rate
end population maps
end model
"""
    hpp_cc = _generate_hybrid(comp_complex_bngl, tmp_path, "comp_complex")
    cc_text = hpp_cc.read_text(encoding="utf-8")
    assert "||" not in cc_text
    assert "BindS_v" in cc_text
    hyb_cc = bionetgen.load(str(hpp_cc))
    hyb_cc.generate_network(max_iter=5)


def test_l2_03_02_hybrid_count_unique_observables(tmp_path: Path):
    """HybridModelGenerator must honor MoleculesObservables and SpeciesObservables CountUnique."""
    bngl = """
begin model
setOption("MoleculesObservables","CountUnique")
setOption("SpeciesObservables","CountUnique")
begin parameters
  kg 1000
  k 0.1
end parameters
begin molecule types
  A(b,s~0~1)
end molecule types
begin seed species
  A(b!1,s~0).A(b!1,s~0) 100
end seed species
begin observables
  Molecules Dimer_M A(b!1).A(b!1)
  Species S_TwoPatt A(s~0) A(b!+)
end observables
begin reaction rules
  R1: A(s~0) -> A(s~1) k
end reaction rules
begin population maps
  A(b!1,s~0).A(b!1,s~0) -> AA_pop() kg
end population maps
end model
"""
    hpp = _generate_hybrid(bngl, tmp_path, "hybrid_cu")
    hpp_text = hpp.read_text(encoding="utf-8")
    obs_block = hpp_text.split("begin observables", 1)[1].split("end observables", 1)[0]
    obs_lines = {
        line.split()[1]: [p.strip() for p in " ".join(line.split()[2:]).replace(",", " ").split() if p.strip()]
        for line in obs_block.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert obs_lines["Dimer_M"].count("AA_pop()") == 1
    assert obs_lines["S_TwoPatt"].count("AA_pop()") == 1


# ==============================================================================
# L2-08-05, 07, 08, 09, 10 & L2-10-08a: Energy, Barriers, Driven Work & Scopes
# ==============================================================================


@pytest.mark.parametrize(
    "barrier_line,comp_block,mol_block,seed_block,rule_line",
    [
        # Compartment constraint on barrier pattern
        (
            "B_pm: A(s~U)@PM -> A(s~P)@PM Gbar",
            "begin compartments\n  EC 3 1.0\n  PM 2 1.0 EC\n  CP 3 1.0 PM\nend compartments",
            "A(s~U~P)",
            "A(s~U)@PM 10\n  A(s~U)@CP 10",
            "R_pm: A(s~U)@PM <-> A(s~P)@PM Arrhenius(phi, Ea)",
        ),
        # Center-site !+ bond constraint on state-change barrier
        (
            "B_bound: A(s~U!+) -> A(s~P!+) Gbar",
            "",
            "A(s~U~P)\n  B(a)",
            "A(s~U) 10\n  A(s~U!1).B(a!1) 10",
            "R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)",
        ),
        # Intramolecular bond barrier
        (
            "B_intra: A(x,y) -> A(x!1,y!1) Gbar",
            "",
            "A(x,y)",
            "A(x,y) 10",
            "R1: A(x,y) + A(x,y) <-> A(x!1,y).A(x,y!1) Arrhenius(phi, Ea)",
        ),
    ],
)
def test_l2_08_05_conditional_barrier_patterns_rejected(
    tmp_path: Path,
    barrier_line: str,
    comp_block: str,
    mol_block: str,
    seed_block: str,
    rule_line: str,
):
    """Compartment, center-site !+, and intramolecular barriers must fail closed."""
    bngl = f"""
begin model
begin parameters
  G_P 0.0
  Gbar 5.0
  phi 0.5
  Ea 0.0
end parameters
{comp_block}
begin molecule types
  {mol_block}
end molecule types
begin seed species
  {seed_block}
end seed species
begin energy patterns
  A() G_P
end energy patterns
begin barrier patterns
  {barrier_line}
end barrier patterns
begin reaction rules
  {rule_line}
end reaction rules
end model
"""
    with mock.patch.dict(os.environ, {"BNG_NFSIM_GENERAL_ENERGY": "1"}):
        model = _load(bngl, tmp_path, "cond_barrier")
        with pytest.raises(RuntimeError):
            model.to_xml()


@pytest.mark.parametrize(
    "rate_spec",
    [
        "Arrhenius(0.3, 1.0), Arrhenius(0.7, 2.0)",
        "Arrhenius(0.5, 0.0), 10.0",
    ],
)
def test_l2_08_07_bidirectional_two_rate_arrhenius_rejected(
    tmp_path: Path, rate_spec: str
):
    """Reversible rules with two rate laws where either is Arrhenius must fail closed."""
    bngl = f"""
begin model
begin parameters
  G_P 2.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  A(s~P) G_P
end energy patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) {rate_spec}
end reaction rules
end model
"""
    model = _load(bngl, tmp_path, "two_rate_arrhenius")
    with pytest.raises(RuntimeError, match="Arrhenius"):
        model.generate_network(max_iter=5)


def test_l2_08_08_driven_by_time_rejected(tmp_path: Path):
    """driven_by(time) must fail closed rather than silently freezing time=0."""
    bngl = """
begin model
begin parameters
  G_P 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  A(s~P) G_P
end energy patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(0.5, 0.0) driven_by(time)
end reaction rules
end model
"""
    with mock.patch.dict(os.environ, {"BNG_NFSIM_GENERAL_ENERGY": "1"}):
        model = _load(bngl, tmp_path, "driven_time")
        with pytest.raises(RuntimeError, match="statically evaluable"):
            model.generate_network(max_iter=5)


def test_l2_08_09_driven_by_non_arrhenius_rejected(tmp_path: Path):
    """driven_by(W) on a mass-action rule must fail closed on network generation."""
    bngl = """
begin model
begin parameters
  kf 1.0
  kr 1.0
  W 3.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin reaction rules
  R1: A(s~U) <-> A(s~P) kf, kr driven_by(W)
end reaction rules
end model
"""
    with mock.patch.dict(os.environ, {"BNG_NFSIM_GENERAL_ENERGY": "1"}):
        model = _load(bngl, tmp_path, "driven_mass_action")
        with pytest.raises(RuntimeError, match="Arrhenius"):
            model.generate_network(max_iter=5)


def test_l2_08_10_arrhenius_with_totalrate_rejected(tmp_path: Path):
    """Arrhenius combined with TotalRate must fail closed."""
    bngl = """
begin model
begin parameters
  G_AB -2.0
  phi 0.5
  Ea 3.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 50
  B(a) 50
end seed species
begin energy patterns
  A(b!1).B(a!1) G_AB
end energy patterns
begin reaction rules
  R1: A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea) TotalRate
end reaction rules
end model
"""
    model = _load(bngl, tmp_path, "arrhenius_totalrate")
    with pytest.raises(RuntimeError, match="TotalRate"):
        model.generate_network(max_iter=5)


def test_l2_10_08a_reversible_one_sided_scope_bngir_roundtrip(tmp_path: Path):
    """Reversible rule with one-sided %x: scope (Hlavacek2018Restructuration) must serialize cleanly."""
    bngl = """
begin model
begin parameters
  lp2 0.5
  lm2 0.2
end parameters
begin molecule types
  R(P~1~x)
end molecule types
begin seed species
  R(P~1) 100
end seed species
begin observables
  Molecules Crosslink R(P~x)
end observables
begin reaction rules
  %x:R(P~1) <-> R(P~x) if(Crosslink(x)>0,0,lp2), lm2
end reaction rules
end model
"""
    model = _load(bngl, tmp_path, "rev_one_sided_scope")
    doc = json.loads(bionetgen.to_bngir(model))
    rev = doc["model"]["rules"][0]["reverse"]
    assert rev["local_scopes"] == []
    restored = bionetgen.from_bngir(doc)
    assert bionetgen.semantic_equal(model, restored) is True
