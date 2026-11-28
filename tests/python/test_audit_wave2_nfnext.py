"""Regression tests for Wave 2 audit fixes in NFnext.

Covers all verified Wave 2 NFnext defects:
1.  RULEHUB-05: Simultaneous DeleteBond + AddBond (bond transfer) emits Unbind before Bind
2.  MEM-03: FunctionVM recursion depth guard prevents stack overflow on deeply nested expressions
3.  NFN-01: Duplicate component names (`A(b,b)`, `A(p~0~1,p~0~1)`) match & mutate all sites
4.  NFN-02: Product molecularity (`+` vs `.`) blocks ring splitting (#48) and allows ring opening (#61)
5.  NFN-03: Local functions (`%x:... f(x)`) evaluate observables locally on the matched complex (#156)
6.  NFN-04 / ETH-12: Exact within-pattern symmetry, pure-context catalysts (#87), whole-species
    deletion (#148), and symmetric population maps
7.  NFN-05: Constant seed species (`$A()`, `$Trash()`) maintain fixed copy number
8.  NFN-06 & NFN-07: `include_products`/`exclude_products` (#63) and unbound reactant filter sites
9.  NFN-08 & PERF-02: `Molecules` observables without `aut^2`/`k!*k!` double-counting, fast automorphism
10. NFN-09a-e: Compartment inheritance, adjacency, cross-membrane transport, 2D `@PM:` matching,
    unqualified bimolecular volume scaling, and `NumberPerQuantityUnit`
11. NFN-10 / ETH-08..11 / ETH-13: Arrhenius energy patterns (AND vs OR, partner type/state, `!+`,
    3-mol cooperativity, Ising homodimer, state-constrained binding crash, `R(s,s)` cooperativity)
12. NFN-11..14: `DeleteMolecules`/filter symmetry, `MatchOnce` complexId dedup, `TotalRate` without
    volume/popFactor scaling, population `MatchOnce`, and mixed-lumped `MoveConnected`
13. NFN-15: Canonical `.species` output merges isomorphic complexes into one line
14. PERF-01 / PERF-05 / RULEHUB-06: O(N) independent same-type counting and complex-scoped filters
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp


def _run_nfnext_ensemble(
    source: str,
    obs_names: list[str],
    t_end: float,
    n_runs: int = 20,
    seed_base: int = 1000,
) -> dict[str, tuple[float, float]]:
    model = cpp.parse_string(source)
    samples: dict[str, list[float]] = {name: [] for name in obs_names}
    for i in range(n_runs):
        res = cpp.simulate_nfnext(model, [0.0, t_end], seed=seed_base + i)
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


def _assert_close_ensemble(
    mean: float, se: float, expected: float, z_max: float = 4.5, min_tol: float = 1.5
):
    tol = max(z_max * se, min_tol)
    assert (
        abs(mean - expected) <= tol
    ), f"ensemble mean {mean:.3f} +/- {se:.3f} deviates from expected {expected:.3f} (tol={tol:.3f})"


# 1. RULEHUB-05: Simultaneous DeleteBond + AddBond
def test_rulehub05_simultaneous_unbind_and_bind_bond_transfer():
    source = """begin model
begin molecule types
  A(b)
  B(a)
  C(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 30
  C(a) 30
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
  Molecules AC A(b!1).C(a!1)
  Molecules Bfree B(a)
end observables
begin reaction rules
  transfer: A(b!1).B(a!1) + C(a) -> A(b!1).C(a!1) + B(a) 0.1
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    res = cpp.simulate_nfnext(model, [0.0, 2.0], seed=7)
    ab = float(res["observables"]["AB"][-1])
    ac = float(res["observables"]["AC"][-1])
    bfree = float(res["observables"]["Bfree"][-1])
    assert ab + ac == 30.0
    assert bfree == ac
    assert ac > 15.0


# 2. MEM-03: Deeply nested expression recursion depth guard in FunctionVM
def test_mem03_deeply_nested_function_expression_rejected_cleanly():
    depth = 350
    expr = "(" * depth + "k + A_obs()" + ")" * depth
    source = f"""begin model
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
  Molecules A_obs A()
end observables
begin functions
  deep_f() = {expr}
end functions
begin reaction rules
  A() -> 0 deep_f()
end reaction rules
end model
"""
    with pytest.raises(Exception, match="depth|limit|function"):
        model = cpp.parse_string(source)
        cpp.simulate_nfnext(model, [0.0, 1.0], seed=1)


# 3. NFN-01: Duplicate component names
def test_nfn01_duplicate_component_names_binding_and_states():
    # (a) Bivalent A(b,b) must bind BOTH b sites.
    bind_src = """begin model
begin molecule types
  A(b,b)
  B(a)
end molecule types
begin seed species
  A(b,b) 40
  B(a) 80
end seed species
begin observables
  Molecules AB2 A(b!1,b!2).B(a!1).B(a!2)
  Molecules Bfree B(a)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 0.1
end reaction rules
end model
"""
    ode = _run_ode_final(bind_src, ["AB2", "Bfree"], t_end=2.0)
    ens = _run_nfnext_ensemble(
        bind_src, ["AB2", "Bfree"], t_end=2.0, n_runs=16, seed_base=1100
    )
    assert ode["AB2"] > 30.0
    _assert_close_ensemble(ens["AB2"][0], ens["AB2"][1], ode["AB2"], min_tol=2.5)
    _assert_close_ensemble(ens["Bfree"][0], ens["Bfree"][1], ode["Bfree"], min_tol=2.5)

    # (b) Two identical stateful sites A(p~0~1,p~0~1) must both phosphorylate.
    state_src = """begin model
begin molecule types
  A(p~0~1,p~0~1)
end molecule types
begin seed species
  A(p~0,p~0) 60
end seed species
begin observables
  Species A11 A(p~1,p~1)
  Molecules P1 A(p~1)
end observables
begin reaction rules
  A(p~0) -> A(p~1) 1.0
end reaction rules
end model
"""
    ens_s = _run_nfnext_ensemble(
        state_src, ["A11", "P1"], t_end=2.0, n_runs=20, seed_base=1200
    )
    p = 1.0 - math.exp(-2.0)
    expected_a11 = 60.0 * p * p
    expected_p1 = 120.0 * p
    _assert_close_ensemble(ens_s["A11"][0], ens_s["A11"][1], expected_a11, min_tol=2.5)
    _assert_close_ensemble(ens_s["P1"][0], ens_s["P1"][1], expected_p1, min_tol=3.0)


# 4. NFN-02: Product molecularity ('+' vs '.') on rings (#48, #61)
def test_nfn02_product_molecularity_blocks_ring_splitting_and_allows_ring_opening():
    # '+' requires two disconnected product complexes: must NOT fire on a 3-ring!
    split_src = """begin model
begin molecule types
  A(b,c)
end molecule types
begin seed species
  A(b!1,c!3).A(b!2,c!1).A(b!3,c!2) 30
end seed species
begin observables
  Molecules FreeB A(b)
end observables
begin reaction rules
  A(b!1).A(c!1) -> A(b) + A(c) 1.0
end reaction rules
end model
"""
    model_split = cpp.parse_string(split_src)
    res_split = cpp.simulate_nfnext(model_split, [0.0, 2.0], seed=42)
    assert float(res_split["observables"]["FreeB"][-1]) == 0.0

    # '.' requires one connected product complex: opens 3-ring (3 bonds, rate 3*k),
    # and must NOT break a linear dimer!
    open_src = """begin model
begin molecule types
  A(b,c)
  D(b,c)
end molecule types
begin seed species
  A(b!1,c!3).A(b!2,c!1).A(b!3,c!2) 40
  D(b!1,c).D(b,c!1) 40
end seed species
begin observables
  Molecules FreeB_A A(b)
  Molecules FreeB_D D(b)
end observables
begin reaction rules
  A(b!1).A(c!1) -> A(b).A(c) 0.5
  D(b!1).D(c!1) -> D(b).D(c) 2.0
end reaction rules
end model
"""
    ens_o = _run_nfnext_ensemble(
        open_src, ["FreeB_A", "FreeB_D"], t_end=1.0, n_runs=20, seed_base=1300
    )
    # Each closed ring opens once at rate 3*0.5 = 1.5; once opened into linear trimer,
    # remaining bonds cannot break under '.' without disconnecting!
    expected_opened = 40.0 * (1.0 - math.exp(-1.5))
    _assert_close_ensemble(
        ens_o["FreeB_A"][0], ens_o["FreeB_A"][1], expected_opened, min_tol=2.5
    )
    # Linear dimer D-D starts with 1 free b per dimer (40 total) and must NEVER unbind under '.'.
    assert ens_o["FreeB_D"][0] == 40.0


# 5. NFN-03: Local functions (%x:... f(x))
def test_nfn03_local_functions_evaluated_on_matched_complex():
    source = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(s~0~1,b)
  B(a)
end molecule types
begin seed species
  A(s~0,b!1).B(a!1) 30
  A(s~0,b) 30
end seed species
begin observables
  Molecules A1 A(s~1)
  Molecules B_obs B()
end observables
begin functions
  f_loc(x) = k * (1 + B_obs(x))
end functions
begin reaction rules
  %x:A(s~0) -> %x:A(s~1) f_loc(x)
end reaction rules
end model
"""
    expected_a1 = 30.0 * (1.0 - math.exp(-2.0)) + 30.0 * (1.0 - math.exp(-1.0))
    ens = _run_nfnext_ensemble(source, ["A1"], t_end=2.0, n_runs=24, seed_base=1400)
    _assert_close_ensemble(ens["A1"][0], ens["A1"][1], expected_a1, min_tol=2.5)


# 6. NFN-04 & ETH-12: Within-pattern symmetry, pure-context catalyst, whole-species deletion, pop map
def test_nfn04_symmetry_homodimer_unbinding_ring_closure_catalyst_whole_species_popmap():
    # (a) Homodimer unbinding
    unbind_src = """begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 60
end seed species
begin observables
  Species AA A(b!1).A(b!1)
end observables
begin reaction rules
  A(b!1).A(b!1) -> A(b) + A(b) 0.5
end reaction rules
end model
"""
    expected = 60.0 * math.exp(-1.0)
    ens = _run_nfnext_ensemble(unbind_src, ["AA"], t_end=2.0, n_runs=24, seed_base=1500)
    _assert_close_ensemble(ens["AA"][0], ens["AA"][1], expected, min_tol=2.5)

    # (b) Intramolecular symmetric ring closure
    ring_src = """begin model
begin molecule types
  A(b,c)
  C(a1,a2)
end molecule types
begin seed species
  A(b,c!1).C(a1!1,a2!2).A(b,c!2) 60
end seed species
begin observables
  Species Closed A(b!1).A(b!1)
end observables
begin reaction rules
  A(b).A(b) -> A(b!1).A(b!1) 0.5
end reaction rules
end model
"""
    expected_closed = 60.0 * (1.0 - math.exp(-1.0))
    ens_r = _run_nfnext_ensemble(
        ring_src, ["Closed"], t_end=2.0, n_runs=24, seed_base=1600
    )
    _assert_close_ensemble(
        ens_r["Closed"][0], ens_r["Closed"][1], expected_closed, min_tol=2.5
    )

    # (c) Pure-context symmetric catalyst (#87) vs asymmetric control
    cat_src = """begin model
begin molecule types
  A(s~0~1)
  B(s~0~1)
  E(d)
  F(d)
  G(d)
end molecule types
begin seed species
  A(s~0) 60
  B(s~0) 60
  E(d!1).E(d!1) 10
  F(d!1).G(d!1) 10
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules B0 B(s~0)
end observables
begin reaction rules
  A(s~0) + E(d!1).E(d!1) -> A(s~1) + E(d!1).E(d!1) 0.05
  B(s~0) + F(d!1).G(d!1) -> B(s~1) + F(d!1).G(d!1) 0.05
end reaction rules
end model
"""
    ens_c = _run_nfnext_ensemble(
        cat_src, ["A0", "B0"], t_end=2.0, n_runs=24, seed_base=1700
    )
    _assert_close_ensemble(ens_c["A0"][0], ens_c["A0"][1], expected, min_tol=2.5)
    _assert_close_ensemble(ens_c["B0"][0], ens_c["B0"][1], expected, min_tol=2.5)

    # (d) Whole-species deletion (#148)
    del_src = """begin model
begin molecule types
  M(n)
  N(m1,m2)
end molecule types
begin seed species
  M(n!1).N(m1!1,m2!2).M(n!2) 60
end seed species
begin observables
  Species MNM M(n!1).N(m1!1,m2!2).M(n!2)
end observables
begin reaction rules
  M() -> 0 0.5
end reaction rules
end model
"""
    ens_d = _run_nfnext_ensemble(del_src, ["MNM"], t_end=2.0, n_runs=24, seed_base=1800)
    _assert_close_ensemble(ens_d["MNM"][0], ens_d["MNM"][1], expected, min_tol=2.5)

    # (e) Symmetric population map
    popmap_src = """begin model
begin molecule types
  A(b)
end molecule types
begin population types
  P_AA()
end population types
begin seed species
  A(b!1).A(b!1) 60
end seed species
begin observables
  Species AA_part A(b!1).A(b!1)
  Molecules AA_pop P_AA()
end observables
begin population maps
  A(b!1).A(b!1) -> P_AA() 0.5
end population maps
end model
"""
    ens_p = _run_nfnext_ensemble(
        popmap_src, ["AA_part", "AA_pop"], t_end=2.0, n_runs=24, seed_base=1900
    )
    _assert_close_ensemble(
        ens_p["AA_part"][0], ens_p["AA_part"][1], expected, min_tol=2.5
    )
    _assert_close_ensemble(
        ens_p["AA_pop"][0], ens_p["AA_pop"][1], 60.0 - expected, min_tol=2.5
    )


# 7. NFN-05: Constant seed species ($A(), $Trash())
def test_nfn05_constant_seed_species_preserved():
    source = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
  B()
  Trash()
end molecule types
begin seed species
  $A() 100
  B() 0
  $Trash() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
  Molecules Ttot Trash()
end observables
begin reaction rules
  A() -> B() k
  B() -> Trash() 0.0
end reaction rules
end model
"""
    ens = _run_nfnext_ensemble(
        source, ["Atot", "Btot", "Ttot"], t_end=2.0, n_runs=16, seed_base=2000
    )
    assert ens["Atot"][0] == 100.0
    assert ens["Ttot"][0] == 0.0
    _assert_close_ensemble(ens["Btot"][0], ens["Btot"][1], 200.0, min_tol=12.0)


# 8. NFN-06 & NFN-07: Product filters and unbound reactant filter sites
def test_nfn06_and_nfn07_product_and_unbound_reactant_filters():
    # exclude_products must block all product formation
    excl_prod = """begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 50
  B(a) 50
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 0.05 exclude_products(1, A(b!1).B(a!1))
end reaction rules
end model
"""
    res_ep = cpp.simulate_nfnext(cpp.parse_string(excl_prod), [0.0, 2.0], seed=11)
    assert float(res_ep["observables"]["AB"][-1]) == 0.0

    # include_products allowing the formed product must match ODE
    incl_prod = excl_prod.replace("exclude_products", "include_products")
    ode_ip = _run_ode_final(incl_prod, ["AB"], t_end=2.0)
    ens_ip = _run_nfnext_ensemble(
        incl_prod, ["AB"], t_end=2.0, n_runs=16, seed_base=2100
    )
    _assert_close_ensemble(ens_ip["AB"][0], ens_ip["AB"][1], ode_ip["AB"], min_tol=2.5)

    # NFN-07: include_reactants(1, A(c)) must require site c to be UNBOUND
    unbound_filter = """begin model
begin molecule types
  A(b,c)
  B(a)
  C(a)
end molecule types
begin seed species
  A(b,c!1).C(a!1) 40
  B(a) 40
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 0.1 include_reactants(1, A(c))
end reaction rules
end model
"""
    res_uf = cpp.simulate_nfnext(cpp.parse_string(unbound_filter), [0.0, 2.0], seed=12)
    assert float(res_uf["observables"]["AB"][-1]) == 0.0


# 9. NFN-08 & PERF-02: Molecules observables & fast automorphism counting
def test_nfn08_and_perf02_molecules_observables_exact_and_fast():
    sym_src = """begin model
begin molecule types
  A(b,p~0~1,p~0~1,p~0~1)
end molecule types
begin seed species
  A(b!1,p~1,p~1,p~1).A(b!1,p~1,p~1,p~1) 5
end seed species
begin observables
  Molecules AA A(b!1).A(b!1)
  Molecules Ap111 A(p~1,p~1,p~1)
end observables
begin reaction rules
  A(b) -> A(b) 0.0
end reaction rules
end model
"""
    res = cpp.simulate_nfnext(cpp.parse_string(sym_src), [0.0, 1.0], seed=1)
    # 5 homodimers * 2 orientations = 10 (NOT 20!)
    assert float(res["observables"]["AA"][0]) == 10.0
    # 10 A molecules * 3! site permutations = 60 (NOT 360!)
    assert float(res["observables"]["Ap111"][0]) == 60.0

    # PERF-02: 12-mer chain observable must not hang on 12! permutations
    chain_pat = ".".join(
        (
            f"A(l!{i},r!{i + 1})"
            if 0 < i < 11
            else (f"A(l,r!1)" if i == 0 else f"A(l!11,r)")
        )
        for i in range(12)
    )
    chain_src = f"""begin model
begin molecule types
  A(l,r)
end molecule types
begin seed species
  {chain_pat} 1
end seed species
begin observables
  Molecules Chain12 {chain_pat}
end observables
begin reaction rules
  A(l,r) -> A(l,r) 0.0
end reaction rules
end model
"""
    t0 = time.monotonic()
    res_c = cpp.simulate_nfnext(cpp.parse_string(chain_src), [0.0, 1.0], seed=2)
    elapsed = time.monotonic() - t0
    assert float(res_c["observables"]["Chain12"][0]) == 1.0
    assert elapsed < 3.0


# 10. NFN-09a-e: All 5 compartment bugs
def test_nfn09_compartments_inheritance_adjacency_surface_volume_npqu():
    # 09a: Created molecule inherits reactant compartment (both standalone and bound)
    inherit_src = """begin model
begin compartments
  EC 3 1
  PM 2 1 EC
  CP 3 1 PM
end compartments
begin molecule types
  A(b)
  B(a)
  C()
end molecule types
begin seed species
  A(b)@EC 20
  A(b)@PM 20
  A(b)@CP 20
end seed species
begin observables
  Molecules C_EC C()@EC
  Molecules C_PM C()@PM
  Molecules C_CP C()@CP
  Molecules B_EC B()@EC
  Molecules B_CP B()@CP
end observables
begin reaction rules
  A() -> A() + C() 0.5
  A(b)@CP -> A(b!1)@CP.B(a!1) 1.0
end reaction rules
end model
"""
    ens_a = _run_nfnext_ensemble(
        inherit_src,
        ["C_EC", "C_PM", "C_CP", "B_EC", "B_CP"],
        t_end=2.0,
        n_runs=16,
        seed_base=2200,
    )
    _assert_close_ensemble(ens_a["C_EC"][0], ens_a["C_EC"][1], 20.0, min_tol=4.0)
    _assert_close_ensemble(ens_a["C_PM"][0], ens_a["C_PM"][1], 20.0, min_tol=4.0)
    _assert_close_ensemble(ens_a["C_CP"][0], ens_a["C_CP"][1], 20.0, min_tol=4.0)
    assert ens_a["B_EC"][0] == 0.0
    _assert_close_ensemble(
        ens_a["B_CP"][0], ens_a["B_CP"][1], 20.0 * (1.0 - math.exp(-2.0)), min_tol=2.5
    )

    # 09b: Non-adjacent binding blocked + cross-membrane transport moves bound cargo
    adj_src = """begin model
begin compartments
  EC 3 1
  PM 2 1 EC
  CP 3 1 PM
end compartments
begin molecule types
  L(r)
  R(l)
  A(b)
  B(a)
end molecule types
begin seed species
  L(r)@EC 30
  R(l)@CP 30
  A(b!1)@EC.B(a!1)@EC 40
end seed species
begin observables
  Molecules LR L(r!1).R(l!1)
  Molecules A_CP A()@CP
  Molecules B_CP B()@CP
  Molecules B_EC B()@EC
end observables
begin reaction rules
  L(r) + R(l) -> L(r!1).R(l!1) 0.1
  A()@EC -> A()@CP 2.0
end reaction rules
end model
"""
    res_b = cpp.simulate_nfnext(cpp.parse_string(adj_src), [0.0, 2.0], seed=15)
    assert float(res_b["observables"]["LR"][-1]) == 0.0
    assert float(res_b["observables"]["A_CP"][-1]) == float(
        res_b["observables"]["B_CP"][-1]
    )
    assert (
        float(res_b["observables"]["B_CP"][-1])
        + float(res_b["observables"]["B_EC"][-1])
        == 40.0
    )
    assert float(res_b["observables"]["B_CP"][-1]) > 30.0

    # 09c: Species-level @PM:L.R matches spanning complex L@EC.R@PM
    surf_src = """begin model
begin compartments
  EC 3 1
  PM 2 1 EC
  CP 3 1 PM
end compartments
begin molecule types
  L(r)
  R(l)
end molecule types
begin seed species
  L(r!1)@EC.R(l!1)@PM 50
end seed species
begin observables
  Molecules LR_pm @PM:L(r!1).R(l!1)
end observables
begin reaction rules
  @PM:L(r!1).R(l!1) -> L(r)@EC + R(l)@PM 1.0
end reaction rules
end model
"""
    res_c0 = cpp.simulate_nfnext(cpp.parse_string(surf_src), [0.0, 2.0], seed=16)
    assert float(res_c0["observables"]["LR_pm"][0]) == 50.0
    ens_c = _run_nfnext_ensemble(
        surf_src, ["LR_pm"], t_end=2.0, n_runs=20, seed_base=2300
    )
    _assert_close_ensemble(
        ens_c["LR_pm"][0], ens_c["LR_pm"][1], 50.0 * math.exp(-2.0), min_tol=2.5
    )

    # 09d: Unqualified bimolecular rule scales by 1/V
    vol_src = """begin model
begin compartments
  EC 3 10
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@EC 40
  B(a)@EC 40
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 0.1
end reaction rules
end model
"""
    ode_d = _run_ode_final(vol_src, ["AB"], t_end=2.0)
    ens_d = _run_nfnext_ensemble(vol_src, ["AB"], t_end=2.0, n_runs=20, seed_base=2400)
    _assert_close_ensemble(ens_d["AB"][0], ens_d["AB"][1], ode_d["AB"], min_tol=2.5)

    # 09e: NumberPerQuantityUnit scales bimolecular rate even without typed physical units
    npqu_src = """setOption("NumberPerQuantityUnit", 5)
begin model
begin compartments
  EC 3 1
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@EC 40
  B(a)@EC 40
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b)@EC + B(a)@EC -> A(b!1)@EC.B(a!1)@EC 0.1
end reaction rules
end model
"""
    ode_e = _run_ode_final(npqu_src, ["AB"], t_end=2.0)
    ens_e = _run_nfnext_ensemble(npqu_src, ["AB"], t_end=2.0, n_runs=20, seed_base=2500)
    _assert_close_ensemble(ens_e["AB"][0], ens_e["AB"][1], ode_e["AB"], min_tol=2.5)


# 11. NFN-10 / ETH-08..11 / ETH-13: Arrhenius energy patterns
def test_nfn10_and_eth08_to_13_arrhenius_energy_exact():
    # (a) ETH-09 / NFN-10a: Partner type and partner state must be checked!
    partner_src = """begin model
begin molecule types
  A(s~0~1,x)
  B(a,y~0~1)
  C(a)
end molecule types
begin seed species
  A(s~0,x!1).B(a!1,y~0) 50
  A(s~0,x!1).C(a!1) 50
end seed species
begin observables
  Molecules A1_B A(s~1,x!1).B(a!1)
  Molecules A1_C A(s~1,x!1).C(a!1)
end observables
begin energy patterns
  A(s~1,x!1).B(a!1,y~1) -4.0
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(0.5, 0.0)
end reaction rules
end model
"""
    ens_a = _run_nfnext_ensemble(
        partner_src, ["A1_B", "A1_C"], t_end=3.0, n_runs=20, seed_base=2600
    )
    _assert_close_ensemble(ens_a["A1_B"][0], ens_a["A1_B"][1], 25.0, min_tol=3.0)
    _assert_close_ensemble(ens_a["A1_C"][0], ens_a["A1_C"][1], 25.0, min_tol=3.0)

    # (b) ETH-08 / NFN-10b: Multi-condition EP uses logical AND (not OR)
    and_src = """begin model
begin molecule types
  A(s~0~1,x,y~0~1)
  B(a)
end molecule types
begin seed species
  A(s~0,x,y~1) 50
  A(s~0,x!1,y~0).B(a!1) 50
end seed species
begin observables
  Molecules A1_onlyY A(s~1,x,y~1)
  Molecules A1_onlyX A(s~1,x!1,y~0).B(a!1)
end observables
begin energy patterns
  A(s~1,x!1,y~1).B(a!1) -4.0
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(0.5, 0.0)
end reaction rules
end model
"""
    ens_b = _run_nfnext_ensemble(
        and_src, ["A1_onlyY", "A1_onlyX"], t_end=3.0, n_runs=20, seed_base=2700
    )
    _assert_close_ensemble(
        ens_b["A1_onlyY"][0], ens_b["A1_onlyY"][1], 25.0, min_tol=3.0
    )
    _assert_close_ensemble(
        ens_b["A1_onlyX"][0], ens_b["A1_onlyX"][1], 25.0, min_tol=3.0
    )

    # (c) ETH-11 / NFN-10c: Wildcard !+ in EP does not apply to unbound molecule
    wild_src = """begin model
begin molecule types
  A(s~0~1,x)
end molecule types
begin seed species
  A(s~0,x) 50
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1,x!+) -4.0
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(0.5, 0.0)
end reaction rules
end model
"""
    ens_c = _run_nfnext_ensemble(wild_src, ["A1"], t_end=3.0, n_runs=20, seed_base=2800)
    _assert_close_ensemble(ens_c["A1"][0], ens_c["A1"][1], 25.0, min_tol=3.0)

    # (d) ETH-11 / NFN-10d: 3-molecule cooperativity EP on binding/unbinding
    coop3_src = """begin model
begin molecule types
  A(b)
  B(a,c)
  C(b)
end molecule types
begin seed species
  A(b!1).B(a!1,c) 40
  C(b) 40
end seed species
begin observables
  Molecules ABC A(b!1).B(a!1,c!2).C(b!2)
end observables
begin energy patterns
  B(c!1).C(b!1) 2.0
  A(b!1).B(a!1,c!2).C(b!2) -6.0
end energy patterns
begin reaction rules
  B(c) + C(b) <-> B(c!1).C(b!1) Arrhenius(0.5, 2.0)
end reaction rules
end model
"""
    ode_d = _run_ode_final(coop3_src, ["ABC"], t_end=5.0)
    ens_d = _run_nfnext_ensemble(
        coop3_src, ["ABC"], t_end=5.0, n_runs=16, seed_base=2900
    )
    _assert_close_ensemble(ens_d["ABC"][0], ens_d["ABC"][1], ode_d["ABC"], min_tol=2.5)

    # (e) ETH-10: Homodimer Ising coupling A(s~1,b!1).A(s~1,b!1)
    ising_src = """begin model
begin molecule types
  A(s~0~1,b)
end molecule types
begin seed species
  A(s~0,b!1).A(s~0,b!1) 50
end seed species
begin observables
  Species Both1 A(s~1,b!1).A(s~1,b!1)
end observables
begin energy patterns
  A(s~1,b!1).A(s~1,b!1) -3.0
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(0.5, 0.0)
end reaction rules
end model
"""
    # Exact Boltzmann partition function: Z = 1 (00) + 2 (01/10) + e^3 (11)
    z = 3.0 + math.exp(3.0)
    expected_both1 = 50.0 * math.exp(3.0) / z
    ens_i = _run_nfnext_ensemble(
        ising_src, ["Both1"], t_end=8.0, n_runs=20, seed_base=3000
    )
    _assert_close_ensemble(
        ens_i["Both1"][0], ens_i["Both1"][1], expected_both1, min_tol=3.0
    )

    # (f) ETH-13: State-constrained Arrhenius binding must not crash on conflicting branch
    conflict_src = """begin model
begin molecule types
  A(b,y~0~1)
  B(a)
end molecule types
begin seed species
  A(b,y~0) 30
  B(a) 30
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b!1,y~1).B(a!1) -3.0
end energy patterns
begin reaction rules
  A(b,y~0) + B(a) <-> A(b!1,y~0).B(a!1) Arrhenius(0.5, 2.0)
end reaction rules
end model
"""
    ode_f = _run_ode_final(conflict_src, ["AB"], t_end=3.0)
    ens_f = _run_nfnext_ensemble(
        conflict_src, ["AB"], t_end=3.0, n_runs=16, seed_base=3100
    )
    _assert_close_ensemble(ens_f["AB"][0], ens_f["AB"][1], ode_f["AB"], min_tol=2.5)

    # (g) ETH-13: Duplicate-site R(s,s) cooperativity
    rss_src = """begin model
begin molecule types
  R(s,s)
  L(r)
end molecule types
begin seed species
  R(s,s) 30
  L(r) 60
end seed species
begin observables
  Species RL2 R(s!1,s!2).L(r!1).L(r!2)
end observables
begin energy patterns
  R(s!1).L(r!1) 1.0
  R(s!1,s!2).L(r!1).L(r!2) -5.0
end energy patterns
begin reaction rules
  R(s) + L(r) <-> R(s!1).L(r!1) Arrhenius(0.5, 2.0)
end reaction rules
end model
"""
    ode_g = _run_ode_final(rss_src, ["RL2"], t_end=6.0)
    ens_g = _run_nfnext_ensemble(rss_src, ["RL2"], t_end=6.0, n_runs=16, seed_base=3200)
    _assert_close_ensemble(ens_g["RL2"][0], ens_g["RL2"][1], ode_g["RL2"], min_tol=3.0)


# 12. NFN-11, NFN-12, NFN-13, NFN-14
def test_nfn11_nfn12_nfn13_nfn14_symmetry_matchonce_totalrate_population():
    # NFN-11: DeleteMolecules and symmetric exclude_reactants preserve 1/2 symmetry
    delmol_src = """begin model
begin molecule types
  A(b)
  B()
end molecule types
begin seed species
  A(b) 100
end seed species
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b) + A(b) -> 0 0.005 DeleteMolecules
end reaction rules
end model
"""
    ode_dm = _run_ode_final(delmol_src, ["Afree"], t_end=2.0)
    ens_dm = _run_nfnext_ensemble(
        delmol_src, ["Afree"], t_end=2.0, n_runs=20, seed_base=3300
    )
    _assert_close_ensemble(
        ens_dm["Afree"][0], ens_dm["Afree"][1], ode_dm["Afree"], min_tol=4.0
    )

    symfilt_src = """begin model
begin molecule types
  A(b)
  B()
end molecule types
begin seed species
  A(b) 100
end seed species
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) 0.005 exclude_reactants(1, B()) exclude_reactants(2, B())
end reaction rules
end model
"""
    ode_sf = _run_ode_final(symfilt_src, ["Afree"], t_end=2.0)
    ens_sf = _run_nfnext_ensemble(
        symfilt_src, ["Afree"], t_end=2.0, n_runs=20, seed_base=3400
    )
    _assert_close_ensemble(
        ens_sf["Afree"][0], ens_sf["Afree"][1], ode_sf["Afree"], min_tol=4.0
    )

    # NFN-12: MatchOnce deduplicates by complexId (not particle set)
    mo_src = """begin model
begin molecule types
  M(n)
  N(m1,m2)
end molecule types
begin seed species
  M(n!1).N(m1!1,m2!2).M(n!2) 60
end seed species
begin observables
  Species MNM M(n!1).N(m1!1,m2!2).M(n!2)
end observables
begin reaction rules
  M() -> 0 0.5 MatchOnce
end reaction rules
end model
"""
    ens_mo = _run_nfnext_ensemble(mo_src, ["MNM"], t_end=2.0, n_runs=24, seed_base=3500)
    _assert_close_ensemble(
        ens_mo["MNM"][0], ens_mo["MNM"][1], 60.0 * math.exp(-1.0), min_tol=2.5
    )

    # NFN-13: TotalRate NOT multiplied by compartment volume_factor
    tr_src = """begin model
begin compartments
  EC 3 10
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@EC 80
  B(a)@EC 80
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b)@EC + B(a)@EC -> A(b!1)@EC.B(a!1)@EC 20.0 TotalRate
end reaction rules
end model
"""
    ens_tr = _run_nfnext_ensemble(tr_src, ["AB"], t_end=1.0, n_runs=24, seed_base=3600)
    _assert_close_ensemble(ens_tr["AB"][0], ens_tr["AB"][1], 20.0, min_tol=4.0)

    # NFN-14a: Population-only rule with MatchOnce executes cleanly
    pop_mo_src = """begin model
begin population types
  P()
end population types
begin seed species
  P() 60
end seed species
begin observables
  Molecules Ptot P()
end observables
begin reaction rules
  P() -> 0 0.5 MatchOnce
end reaction rules
end model
"""
    ens_pmo = _run_nfnext_ensemble(
        pop_mo_src, ["Ptot"], t_end=2.0, n_runs=20, seed_base=3700
    )
    _assert_close_ensemble(
        ens_pmo["Ptot"][0], ens_pmo["Ptot"][1], 60.0 * math.exp(-1.0), min_tol=3.0
    )

    # NFN-14b: Mixed-lumped TotalRate NOT multiplied by popFactor
    mixed_tr_src = """begin model
begin molecule types
  A(s~0~1)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(s~0) 80
  P() 100
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin reaction rules
  P() + A(s~0) -> P() + A(s~1) 15.0 TotalRate
end reaction rules
end model
"""
    ens_mtr = _run_nfnext_ensemble(
        mixed_tr_src, ["A1"], t_end=1.0, n_runs=24, seed_base=3800
    )
    _assert_close_ensemble(ens_mtr["A1"][0], ens_mtr["A1"][1], 15.0, min_tol=3.5)

    # NFN-14c: Mixed-lumped MoveConnected captures beforeCompartments BEFORE SetCompartment
    mixed_mc_src = """begin model
begin compartments
  c1 3 1
  c2 3 1
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(b!1)@c1.B(a!1)@c1 30
  P()@c1 50
end seed species
begin observables
  Molecules A_c2 A()@c2
  Molecules B_c2 B()@c2
end observables
begin reaction rules
  P()@c1 + A()@c1 -> P()@c1 + A()@c2 0.2 MoveConnected
end reaction rules
end model
"""
    res_mc = cpp.simulate_nfnext(cpp.parse_string(mixed_mc_src), [0.0, 2.0], seed=21)
    assert float(res_mc["observables"]["A_c2"][-1]) > 20.0
    assert float(res_mc["observables"]["B_c2"][-1]) == float(
        res_mc["observables"]["A_c2"][-1]
    )


# 13. NFN-15: Canonical final .species output merges isomorphic species
def test_nfn15_canonical_final_species_merges_isomorphic_complexes(tmp_path: Path):
    bngl = tmp_path / "canon_species.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  A(b,s~0~1)
end molecule types
begin seed species
  A(b!1,s~0).A(b!1,s~1) 5
  A(b!1,s~1).A(b!1,s~0) 5
end seed species
begin observables
  Species Dim A(b!1,s~0).A(b!1,s~1)
end observables
begin reaction rules
  A(b) -> A(b) 0.0
end reaction rules
end model
begin actions
  simulate({method=>"nfnext", prefix=>"canon_out", t_end=>1, n_steps=>1, seed=>1})
end actions
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    species_lines = [
        line.strip()
        for line in (tmp_path / "canon_out.species")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert (
        len(species_lines) == 1
    ), f"Expected 1 canonical species line, got: {species_lines}"
    assert species_lines[0].endswith(" 10")


# 14. PERF-01 / PERF-05 / RULEHUB-06: O(N) same-type counting & scoped reactant filters
def test_perf01_perf05_homodimerization_and_filter_scaling():
    homo_src = """begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 400
end seed species
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) 0.002
end reaction rules
end model
"""
    ode_h = _run_ode_final(homo_src, ["Afree"], t_end=1.0)
    t0 = time.monotonic()
    res_h = cpp.simulate_nfnext(cpp.parse_string(homo_src), [0.0, 1.0], seed=101)
    elapsed_h = time.monotonic() - t0
    assert elapsed_h < 2.0
    assert abs(float(res_h["observables"]["Afree"][-1]) - ode_h["Afree"]) < 35.0

    filt_src = """begin model
begin molecule types
  A(b,c)
  B(a)
end molecule types
begin seed species
  A(b,c) 150
  B(a) 150
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 0.005 include_reactants(1, A(c))
end reaction rules
end model
"""
    t1 = time.monotonic()
    res_f = cpp.simulate_nfnext(cpp.parse_string(filt_src), [0.0, 1.0], seed=102)
    elapsed_f = time.monotonic() - t1
    assert elapsed_f < 3.0
    assert float(res_f["observables"]["AB"][-1]) > 50.0
