"""Regression tests for Wave 1 network generation, symmetry, compartment, and core fixes.

Covers:
- NET-01 / RULEHUB-01: Exact rule-automorphism symmetry factor (MultScale)
- NET-02: Ordered reaction-center signature (no dropped isomers / 2x-8x rate undercounting)
- NET-03 & NET-04: Direct binary binding/unbinding & unary deletion fast-path symmetry/wildcards
- RULEHUB-03: cBNGL interacting-set enforcement (no cross-compartment teleportation)
- RULEHUB-04: Explicit bond (!1) vs dangling wildcard (!+) cardinality distinction
- NET-06: MoveConnected restricted to original compartment
- NET-08: {MatchOnce} honored in network generation
- NET-09: Product molecularity (+) enforced under DeleteMolecules with detached orphans
- NET-10: Provenance/backtracking product-pattern ordering for include_products/exclude_products
- NET-11: Non-positional species-level compartment transport
- NET-12: Species-level compartment prefix (@COMP:) honored in reactant/product filters
- NET-13: Tag state propagation (%1/%2) scoped to exact cloned product component
- NET-14: MoleculesObservables CountUnique on asymmetric wildcard patterns
- NET-16: check_iso=>0 retains exact canonical-string species deduplication
- PERF-03 & NET-19: State-change network generation without stale canonical labels
"""

from __future__ import annotations

from pathlib import Path
import pytest

from _extdep import require_extension

require_extension()
import bionetgen


def _load_model(bngl: str, tmp_path: Path, name: str = "model") -> bionetgen.BioNetGenModel:
    path = tmp_path / f"{name}.bngl"
    path.write_text(bngl, encoding="utf-8")
    return bionetgen.load(str(path))


def _generate(bngl: str, tmp_path: Path, name: str = "model", max_iter: int = 20):
    model = _load_model(bngl, tmp_path, name)
    return model, model.generate_network(max_iter=max_iter)


# ==============================================================================
# NET-01 / RULEHUB-01: Rule automorphism symmetry factor
# ==============================================================================


def test_net01_asymmetric_homotypic_rule_and_ode(tmp_path: Path):
    """A(s~0) + A(s~0) -> A(s~1) + A(s~2) k has symmetry 1 (rate k, not 0.5*k)."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~0~1~2)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
  Molecules A2 A(s~2)
end observables
begin reaction rules
  A(s~0) + A(s~0) -> A(s~1) + A(s~2) k
end reaction rules
end model
"""
    model, net = _generate(bngl, tmp_path, "asym_homotypic")
    assert net.num_species == 3
    assert net.num_reactions == 1
    assert net.reaction_factors == [pytest.approx(1.0)]

    # Exact closed-form ODE: d[A0]/dt = -2*k*[A0]^2 => [A0](1) = 10 / (1 + 2*1*10*1) = 10/21
    res = model.simulate(method="ode", t_end=1.0, n_steps=10)
    a0_final = float(res.observables["A0"][-1])
    assert a0_final == pytest.approx(10.0 / 21.0, rel=1e-4)


def test_net01_self_catalysis_and_three_catalyst_symmetry(tmp_path: Path):
    """Self-catalysis A+A->A+B has factor 1.0; A+A+A->A+A+B has factor 0.5."""
    bngl_2 = """
begin model
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
  Molecules A0 A(s~0)
end observables
begin reaction rules
  A(s~0) + A(s~0) -> A(s~0) + A(s~1) k
end reaction rules
end model
"""
    model2, net2 = _generate(bngl_2, tmp_path, "self_cat_2")
    assert net2.num_reactions == 1
    assert net2.reaction_factors == [pytest.approx(1.0)]
    res2 = model2.simulate(method="ode", t_end=1.0, n_steps=10)
    assert float(res2.observables["A0"][-1]) == pytest.approx(10.0 / 11.0, rel=1e-4)

    bngl_3 = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin reaction rules
  A(s~0) + A(s~0) + A(s~0) -> A(s~0) + A(s~0) + A(s~1) k
end reaction rules
end model
"""
    _, net3 = _generate(bngl_3, tmp_path, "self_cat_3")
    assert net3.num_reactions == 1
    assert net3.reaction_factors == [pytest.approx(0.5)]


def test_net01_coalescence_and_directed_3ring(tmp_path: Path):
    """Coalescence A+A->A has factor 1.0; directed 3-ring has rotational C3 factor 1/3."""
    bngl_coal = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin reaction rules
  A(b) + A(b) -> A(b) k
end reaction rules
end model
"""
    _, net_coal = _generate(bngl_coal, tmp_path, "coalescence")
    assert net_coal.num_reactions == 1
    assert net_coal.reaction_factors == [pytest.approx(1.0)]

    bngl_ring = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin molecule types
  A(a,b)
end molecule types
begin seed species
  A(a,b) 10
end seed species
begin reaction rules
  A(a,b) + A(a,b) + A(a,b) <-> A(a!1,b!3).A(a!2,b!1).A(a!3,b!2) kf, kr
end reaction rules
end model
"""
    _, net_ring = _generate(bngl_ring, tmp_path, "directed_3ring")
    assert net_ring.num_species == 2
    assert net_ring.num_reactions == 2
    factors_by_rate = dict(zip(net_ring.reaction_rate_laws, net_ring.reaction_factors))
    assert factors_by_rate["kf"] == pytest.approx(1.0 / 3.0)
    assert factors_by_rate["kr"] == pytest.approx(1.0)


def test_net01_cross_compartment_homodimer_and_symmetric_control(tmp_path: Path):
    """A(b)@EC + A(b)@PM has factor 1.0; standard A(b) + A(b) keeps 0.5 and 1.0."""
    bngl_comp = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin compartments
  EC 3 1
  PM 2 1 EC
end compartments
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b)@EC 100
  A(b)@PM 100
end seed species
begin reaction rules
  A(b)@EC + A(b)@PM <-> A(b!1)@EC.A(b!1)@PM kf, kr
end reaction rules
end model
"""
    _, net_comp = _generate(bngl_comp, tmp_path, "cross_comp_homo")
    assert net_comp.num_species == 3
    assert net_comp.num_reactions == 2
    factors_comp = dict(zip(net_comp.reaction_rate_laws, net_comp.reaction_factors))
    assert factors_comp["kf"] == pytest.approx(1.0)
    assert factors_comp["kr"] == pytest.approx(1.0)

    bngl_sym = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 100
end seed species
begin reaction rules
  A(b) + A(b) <-> A(b!1).A(b!1) kf, kr
end reaction rules
end model
"""
    _, net_sym = _generate(bngl_sym, tmp_path, "sym_homo")
    assert net_sym.num_species == 2
    assert net_sym.num_reactions == 2
    factors_sym = dict(zip(net_sym.reaction_rate_laws, net_sym.reaction_factors))
    assert factors_sym["kf"] == pytest.approx(0.5)
    assert factors_sym["kr"] == pytest.approx(1.0)


# ==============================================================================
# NET-02: Ordered reactionCenterSignature (isomers & multi-site rates)
# ==============================================================================


def test_net02_asymmetric_multistate_reaction_center_preserves_both_isomers(tmp_path: Path):
    """Ordered reaction-center signature emits both product isomers and 2*k on symmetric dimer."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(x,y~0~1~2,z~a~b)
end molecule types
begin seed species
  A(x!1,y~0,z~a).A(x!1,y~0,z~b) 100
  A(x!1,y~0,z~a).A(x!1,y~0,z~a) 100
end seed species
begin reaction rules
  A(x!1,y~0).A(x!1,y~0) -> A(x!1,y~1).A(x!1,y~2) k
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "asym_multistate_rc")
    assert net.num_species == 5
    assert net.num_reactions == 3
    assert sorted(net.reaction_factors) == pytest.approx([1.0, 1.0, 2.0])


def test_net02_double_bond_and_symmetric_3ring_rates(tmp_path: Path):
    """Double-bond binding gets 2*kf; symmetric bivalent 3-ring gets 4/3*kf (was 8x too slow)."""
    bngl_double = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin molecule types
  A(b,b)
  B(a,a)
end molecule types
begin seed species
  A(b,b) 10
  B(a,a) 10
end seed species
begin reaction rules
  A(b,b) + B(a,a) <-> A(b!1,b!2).B(a!1,a!2) kf, kr
end reaction rules
end model
"""
    _, net_double = _generate(bngl_double, tmp_path, "double_bond")
    assert net_double.num_species == 3
    assert net_double.num_reactions == 2
    factors_double = dict(zip(net_double.reaction_rate_laws, net_double.reaction_factors))
    assert factors_double["kf"] == pytest.approx(2.0)
    assert factors_double["kr"] == pytest.approx(1.0)

    bngl_3ring = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin molecule types
  A(b,b)
end molecule types
begin seed species
  A(b,b) 10
end seed species
begin reaction rules
  A(b,b) + A(b,b) + A(b,b) <-> A(b!1,b!3).A(b!1,b!2).A(b!2,b!3) kf, kr
end reaction rules
end model
"""
    _, net_3ring = _generate(bngl_3ring, tmp_path, "sym_bivalent_3ring")
    assert net_3ring.num_species == 2
    assert net_3ring.num_reactions == 2
    factors_3ring = dict(zip(net_3ring.reaction_rate_laws, net_3ring.reaction_factors))
    assert factors_3ring["kf"] == pytest.approx(4.0 / 3.0)
    assert factors_3ring["kr"] == pytest.approx(1.0)

    bngl_cross = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b,b)
  B(a)
end molecule types
begin seed species
  A(b,b) 10
end seed species
begin reaction rules
  A(b,b) -> A(b!1,b!2).B(a!1).B(a!2) k
end reaction rules
end model
"""
    _, net_cross = _generate(bngl_cross, tmp_path, "cross_bond_dup_sites")
    assert net_cross.num_species == 2
    assert net_cross.num_reactions == 1
    assert net_cross.reaction_factors == [pytest.approx(2.0)]


# ==============================================================================
# NET-03 & NET-04: Direct binary binding/unbinding & unary deletion fast paths
# ==============================================================================


def test_net03_head_to_tail_and_reordered_site_homodimers(tmp_path: Path):
    """Head-to-tail homodimer gets (1.0, 1.0); reordered-site symmetric dimer gets (0.5, 1.0)."""
    bngl_ht = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin molecule types
  A(a,b)
end molecule types
begin seed species
  A(a,b) 10
end seed species
begin reaction rules
  A(a,b) + A(a,b) <-> A(a!1,b).A(a,b!1) kf, kr
end reaction rules
end model
"""
    _, net_ht = _generate(bngl_ht, tmp_path, "head_to_tail")
    assert net_ht.num_species == 2
    assert net_ht.num_reactions == 2
    factors_ht = dict(zip(net_ht.reaction_rate_laws, net_ht.reaction_factors))
    assert factors_ht["kf"] == pytest.approx(1.0)
    assert factors_ht["kr"] == pytest.approx(1.0)

    bngl_reordered = """
begin model
begin parameters
  kf 1.0
  kr 2.0
end parameters
begin molecule types
  A(a,b)
end molecule types
begin seed species
  A(a,b) 10
end seed species
begin reaction rules
  A(a,b) + A(b,a) <-> A(a!1,b).A(b,a!1) kf, kr
end reaction rules
end model
"""
    _, net_reordered = _generate(bngl_reordered, tmp_path, "reordered_sites")
    assert net_reordered.num_species == 2
    assert net_reordered.num_reactions == 2
    factors_reordered = dict(zip(net_reordered.reaction_rate_laws, net_reordered.reaction_factors))
    assert factors_reordered["kf"] == pytest.approx(0.5)
    assert factors_reordered["kr"] == pytest.approx(1.0)


def test_net03_polyvalent_wildcard_unbinding_and_net04_dup_comp_deletion(tmp_path: Path):
    """Polyvalent !1!+ unbinding must not enter dimer fast path; A(b,b,b)->0 gets factor 1.0."""
    bngl_poly = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1!2).B(a!1).B(a!2) 10
end seed species
begin reaction rules
  A(b!1!+).B(a!1) -> A(b!+) + B(a) k
end reaction rules
end model
"""
    _, net_poly = _generate(bngl_poly, tmp_path, "polyvalent_unbind")
    assert net_poly.num_species == 3
    assert net_poly.num_reactions == 1
    assert net_poly.reaction_factors == [pytest.approx(2.0)]

    bngl_del = """
begin model
begin parameters
  kd 1.0
end parameters
begin molecule types
  A(b,b,b)
end molecule types
begin seed species
  A(b,b,b) 100
end seed species
begin reaction rules
  A(b,b,b) -> 0 kd
end reaction rules
end model
"""
    _, net_del = _generate(bngl_del, tmp_path, "dup_comp_deletion")
    assert net_del.num_species == 1
    assert net_del.num_reactions == 1
    assert net_del.reaction_factors == [pytest.approx(1.0)]


# ==============================================================================
# RULEHUB-03: cBNGL interacting-set compartment enforcement
# ==============================================================================


def test_rulehub03_no_cross_compartment_teleportation(tmp_path: Path):
    """Disconnected 3D compartments cannot react under uncompartmented bimolecular rules."""
    bngl_teleport = """
begin model
begin compartments
  C1 3 1.0
  C2 3 1.0
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A()@C1 10
  B()@C2 10
end seed species
begin reaction rules
  A() + B() -> B() 1.0
end reaction rules
end model
"""
    _, net_tp = _generate(bngl_teleport, tmp_path, "comp_teleport")
    assert net_tp.num_species == 2
    assert net_tp.num_reactions == 0

    bngl_lv = """
begin model
begin parameters
  k_eat 0.1
end parameters
begin compartments
  Patch1 3 1.0
  Patch2 3 1.0
end compartments
begin molecule types
  Prey()
  Pred()
end molecule types
begin seed species
  Prey()@Patch1 50
  Pred()@Patch1 10
  Prey()@Patch2 20
  Pred()@Patch2 5
end seed species
begin reaction rules
  Pred() + Prey() -> Pred() + Pred() k_eat
end reaction rules
end model
"""
    _, net_lv = _generate(bngl_lv, tmp_path, "lv_two_patches")
    assert net_lv.num_species == 4
    assert net_lv.num_reactions == 2
    assert all(name.startswith("@Patch") for name in net_lv.species_names)

    bngl_ca = """
begin model
begin compartments
  Cyt 3 10
  ER_M 2 1 Cyt
  ER 3 1 ER_M
end compartments
begin molecule types
  IP3()
  Ca()
end molecule types
begin seed species
  IP3()@Cyt 10
  Ca()@ER 100
end seed species
begin reaction rules
  IP3()@Cyt + Ca()@ER -> IP3()@Cyt + Ca()@Cyt 0.5
end reaction rules
end model
"""
    _, net_ca = _generate(bngl_ca, tmp_path, "nonadjacent_3d_transport")
    assert net_ca.num_reactions == 0


# ==============================================================================
# RULEHUB-04: Explicit bond (!1) vs wildcard (!+) cardinality
# ==============================================================================


def test_rulehub04_explicit_bond_does_not_match_multibond_as_wildcard(tmp_path: Path):
    """Explicit bond !1 requires exact bond count (prevents unbounded multi-bond explosion)."""
    bngl = """
begin model
begin molecule types
  A(b)
  B(b)
  C(b)
end molecule types
begin seed species
  A(b!1).B(b!1) 10
  C(b) 10
end seed species
begin reaction rules
  C(b) + A(b!1).B(b!1) -> C(b!2).B(b!1!2).A(b!1) 1.0
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "explicit_bond_cardinality", max_iter=4)
    assert net.num_species == 3
    assert net.num_reactions == 1


# ==============================================================================
# NET-06: MoveConnected restricted to original compartment
# ==============================================================================


def test_net06_moveconnected_only_moves_same_original_compartment(tmp_path: Path):
    """MoveConnected moves cargo in original compartment (CP->NU) without yanking NP@NM."""
    bngl_pore = """
begin model
begin parameters
  k 1.0
end parameters
begin compartments
  CP 3 1
  NM 2 1 CP
  NU 3 1 NM
end compartments
begin molecule types
  NP(c)
  C(r,x)
  X(c)
end molecule types
begin seed species
  @NM:NP(c!1).C(r!1,x!2)@CP.X(c!2)@CP 10
end seed species
begin reaction rules
  C()@CP -> C()@NU k MoveConnected
end reaction rules
end model
"""
    _, net_pore = _generate(bngl_pore, tmp_path, "moveconnected_pore")
    assert net_pore.num_species == 2
    assert net_pore.num_reactions == 1
    assert any(
        name.startswith("@NM::") and "@NU" in name for name in net_pore.species_names
    )
    assert not any(name.startswith("@NU::") for name in net_pore.species_names)

    bngl_invalid = """
begin model
begin parameters
  k 1.0
end parameters
begin compartments
  EC 3 1
  PM 2 1 EC
  CP 3 1 PM
  NM 2 1 CP
  NU 3 1 NM
end compartments
begin molecule types
  L(r)
  R(l,c)
  C(r,x)
  X(c)
end molecule types
begin seed species
  @PM:L(r!1)@EC.R(l!1,c!2).C(r!2,x!3)@CP.X(c!3)@CP 10
end seed species
begin reaction rules
  C()@CP -> C()@NU k MoveConnected
end reaction rules
end model
"""
    _, net_invalid = _generate(bngl_invalid, tmp_path, "moveconnected_invalid")
    assert net_invalid.num_reactions == 0


# ==============================================================================
# NET-08, NET-09, NET-10, NET-11, NET-12, NET-13, NET-14, NET-16
# ==============================================================================


def test_net08_matchonce_in_network_generation(tmp_path: Path):
    """{MatchOnce} limits reactant matching to 1 embedding per species."""
    bngl_uni = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b,s~u~p)
end molecule types
begin seed species
  A(b!1,s~u).A(b!1,s~u) 10
end seed species
begin reaction rules
  {MatchOnce}A(s~u) -> A(s~p) k
end reaction rules
end model
"""
    _, net_uni = _generate(bngl_uni, tmp_path, "matchonce_uni")
    assert net_uni.num_species == 3
    assert net_uni.num_reactions == 2
    assert all(f == pytest.approx(1.0) for f in net_uni.reaction_factors)

    bngl_bi = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b,c)
  B(a)
end molecule types
begin seed species
  A(b!1,c).A(b!1,c) 10
  B(a) 10
end seed species
begin reaction rules
  {MatchOnce}A(c) + B(a) -> A(c!1).B(a!1) k
end reaction rules
end model
"""
    _, net_bi = _generate(bngl_bi, tmp_path, "matchonce_bi")
    assert net_bi.num_reactions >= 1
    assert net_bi.reaction_factors[0] == pytest.approx(1.0)


def test_net09_deletemolecules_enforces_product_molecularity(tmp_path: Path):
    """Ring-keeping bond break violating `+` is rejected even when DeleteMolecules frees an orphan."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b,x,d)
  B(a,x)
  D(a,e)
  E(d)
end molecule types
begin seed species
  A(b!1,x!2,d!3).B(a!1,x!2).D(a!3,e!4).E(d!4) 10
end seed species
begin reaction rules
  A(b!1,d!3).B(a!1).D(a!3) -> A(b,d) + B(a) k DeleteMolecules
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "dm_ring_molecularity")
    assert net.num_species == 1
    assert net.num_reactions == 0


def test_net10_product_pattern_matching_for_exclude_products(tmp_path: Path):
    """Exact provenance/backtracking orders products properly for exclude_products(1, ...)."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b,s~u~p)
end molecule types
begin seed species
  A(b!1,s~p).A(b!1,s~u) 10
  A(b!1,s~p).A(b!1,s~p) 10
end seed species
begin reaction rules
  A(b!1,s).A(b!1,s~p) -> A(b,s) + A(b,s~p) k exclude_products(1,A(s~p))
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "exclude_products_order")
    assert net.num_species == 4
    assert net.num_reactions == 1


def test_net11_nonpositional_species_level_transport(tmp_path: Path):
    """Reordered products in species-level compartment transport still transport A from EC to CP."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin compartments
  EC 3 10
  PM 2 2 EC
  CP 3 5 PM
end compartments
begin molecule types
  E()
  A()
end molecule types
begin seed species
  @PM:E() 10
  @EC:A() 10
end seed species
begin reaction rules
  @PM:E() + @EC:A() -> @CP:A() + @PM:E() k
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "reordered_transport")
    assert net.num_species == 3
    assert net.num_reactions == 1
    assert "@CP::A()" in net.species_names


def test_net12_filter_honors_species_level_compartment_prefix(tmp_path: Path):
    """exclude_reactants(1, @EC:A()) excludes only @EC species, not @PM."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin compartments
  EC 3 1
  PM 2 1 EC
end compartments
begin molecule types
  A(s~u~p)
end molecule types
begin seed species
  A(s~u)@EC 10
  A(s~u)@PM 10
end seed species
begin reaction rules
  A(s~u) -> A(s~p) k exclude_reactants(1,@EC:A())
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "filter_comp_prefix")
    assert net.num_species == 3
    assert net.num_reactions == 1
    assert "@PM::A(s~p)" in net.species_names
    assert "@EC::A(s~p)" not in net.species_names


def test_net13_tag_state_propagation_scoped_to_mapped_product(tmp_path: Path):
    """%1 and %2 tags on two synthesized sibling B molecules keep their distinct states."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~0~1)
  C(s~0~1)
  B(s~0~1)
end molecule types
begin seed species
  A(s~0) 10
  C(s~1) 10
end seed species
begin reaction rules
  A(s%1) + C(s%2) -> B(s%1) + B(s%2) k
end reaction rules
end model
"""
    _, net = _generate(bngl, tmp_path, "tag_sibling_mols")
    assert net.num_species == 4
    assert net.num_reactions == 1
    assert "B(s~0)" in net.species_names
    assert "B(s~1)" in net.species_names


def test_net14_countunique_asymmetric_wildcard_observables(tmp_path: Path):
    """MoleculesObservables CountUnique succeeds on asymmetric wildcard patterns."""
    bngl = """
setOption("MoleculesObservables","CountUnique")
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~u~p,s~u~p,b,b)
  B(a)
end molecule types
begin seed species
  A(s~u,s~p,b,b) 10
  A(s~u,s~u,b!1,b).B(a!1) 5
end seed species
begin observables
  Molecules M_state A(s~u,s)
  Molecules M_bond A(b!+,b!?)
end observables
begin reaction rules
  A(s~u) -> A(s~p) k
end reaction rules
end model
"""
    model, net = _generate(bngl, tmp_path, "countunique_asym_wildcard")
    assert net.num_species >= 2
    res = model.simulate(method="ode", t_end=0.01, n_steps=1)
    # At t=0: A(s~u,s~p) has 1 match (aut=1), A(s~u,s~u) has 2 matches (aut=1) -> 10*1 + 5*2 = 20
    assert float(res.observables["M_state"][0]) == pytest.approx(20.0)
    # At t=0: A(b!1,b) has 1 match for A(b!+,b!?) (aut=1) -> 5*1 = 5
    assert float(res.observables["M_bond"][0]) == pytest.approx(5.0)


def test_net16_check_iso_zero_keeps_exact_string_dedup(tmp_path: Path):
    """check_iso=>0 skips Nauty isomorphism while keeping exact string deduplication."""
    bngl = """
begin model
begin parameters
  kf 1.0
  kr 1.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
  B(a) 10
end seed species
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
end model
generate_network({overwrite=>1, check_iso=>0, max_iter=>4})
"""
    _, net = _generate(bngl, tmp_path, "check_iso_zero", max_iter=4)
    assert net.num_species == 3
    assert net.num_reactions == 2


def test_rulehub04_observable_engines_enforce_exact_bond_cardinality(tmp_path: Path):
    """ODE, SSA, PSA, and PLA observable groups must reject !1 matching b!1!2."""
    bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  CDK(b)
  Cyclin(b)
  p21(b)
end molecule types
begin seed species
  CDK(b!1).Cyclin(b!2!1).p21(b!2) 10
  Cyclin(b!1).p21(b!1) 3
end seed species
begin observables
  Molecules ExactSingleBond Cyclin(b!1).p21(b!1)
  Molecules AnyBond Cyclin(b!+).p21(b!1)
end observables
begin reaction rules
  CDK(b!1).Cyclin(b!2!1).p21(b!2) -> CDK(b!1).Cyclin(b!2!1).p21(b!2) k
end reaction rules
end model
"""
    path = tmp_path / "obs_bond_card.bngl"
    path.write_text(bngl, encoding="utf-8")
    model = bionetgen.load(str(path))
    for method in ("ode", "ssa", "psa", "pla"):
        kwargs = {"method": method, "t_end": 0.01, "n_steps": 1}
        if method != "ode":
            kwargs["seed"] = 7
        res = model.simulate(**kwargs)
        # Only Cyclin(b!1).p21(b!1) (count=3) has bond degree 1 on Cyclin(b);
        # CDK.Cyclin(b!2!1).p21 (count=10) has degree 2 and must NOT match !1.
        assert float(res.observables["ExactSingleBond"][0]) == pytest.approx(3.0), method
