"""Regression tests for Wave 3 audit fixes in embedded NFcore / NFsim (`cpp/nfsim/`).

Covers all verified Wave 3 NFcore defects:
1.  NFC-01: `TotalRate` symmetric binding/unbinding & RNF `set`/`update` (Hlavacek #90)
2.  NFC-02: `TotalRate` rules in compartments are NOT divided by compartment volume V
3.  NFC-05: Symmetric compiled rules (`A(b,b)`) apply compartment volume scaling `1/V`
4.  NFC-03: `DORRxnClass::pickMappingSets()` right-subtree balance on pure-context complexes (#156)
5.  NFC-08: `System::replenishFixedSpecies()` preserves exact state, non-fixed states, and multi-compartment fixed specs
6.  NFC-09: RNF `saveConcentrations` + `resetConcentrations` no crash & preserves intramolecular self-bonds
7.  NFC-13: Zero-rate `BASIC_RXN` rules retained when parameter/expression-backed (Hlavacek #137)
8.  NFC-14: RNF `set`/`update` propagates to expression rates, derived params, `MM`/`Sat`/`Hill` expr args, and Arrhenius rules (#136)
9.  NFC-15: Compiled muParser syntax handles `-(-k)` and `!(...)` cleanly
10. MEM-09 / NFC-21: Bare `eq` in RNF script handled cleanly without `std::out_of_range`
11. ETH-05: State-coupled binding & allosteric models (MWC square, 8-state cube) satisfy detailed balance
12. ETH-06: Arrhenius binding rules apply compartment volume scaling (`1/V`, `1/(NA*V)`)
13. ETH-07: Rule-level state and bond context constraints preserved on Arrhenius rules
14. ETH-08: Multi-condition energy patterns use logical AND (not OR) in materialized expansion
15. ETH-09: Bond-partner identity & partner state checked in both materialized & compact Arrhenius paths
16. ETH-10: Homotypic neighbor-coupled Ising spin dimer & 4-spin ring match exact Boltzmann equilibrium
17. ETH-11: Unbound-site (`A(b)`) and wildcard-bond (`A(b!+)`, `R(s!+,s!+)`) energy patterns supported
18. BUG-18: One-way Arrhenius unbinding works on default compiled `nfcore` path
19. MEM-03: TinyXML recursion depth limit rejects deeply nested XML without stack-overflow SIGSEGV
20. MEM-04: High-rate NFsim models avoid float-to-int overflow UB and library `exit(1)`
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp

REPO_ROOT = Path(__file__).resolve().parents[2]


def _require_bng_cpp() -> Path:
    configured = os.environ.get("BNG_CPP")
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        pytest.fail(f"BNG_CPP points to missing binary: {path}")
    for rel in ("build/cpp/bng_cpp", "build/bng_cpp"):
        candidate = REPO_ROOT / rel
        if candidate.is_file():
            return candidate
    pytest.fail(f"bng_cpp not found under {REPO_ROOT / 'build'}")


def _run_nf_ensemble(
    source: str,
    obs_names: list[str],
    t_end: float,
    n_runs: int = 20,
    seed_base: int = 100,
    n_steps: int = 2,
) -> dict[str, tuple[float, float]]:
    model = cpp.parse_string(source)
    samples: dict[str, list[float]] = {name: [] for name in obs_names}
    for i in range(n_runs):
        res = cpp.simulate_nf(model, t_end=t_end, n_steps=n_steps, seed=seed_base + i)
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
    mean: float,
    se: float,
    expected: float,
    z_max: float = 4.5,
    min_tol: float = 1.5,
):
    tol = max(z_max * se, min_tol)
    assert (
        abs(mean - expected) <= tol
    ), f"ensemble mean {mean:.3f} +/- {se:.3f} deviates from expected {expected:.3f} (tol={tol:.3f})"


def _run_bng_cpp_rnf(
    tmp_path: Path,
    model_text: str,
    rnf_text: str,
    env_extra: dict[str, str] | None = None,
):
    bng_cpp = _require_bng_cpp()
    (tmp_path / "run.rnf").write_text(rnf_text, encoding="utf-8")
    bngl_path = tmp_path / "run.bngl"
    bngl_path.write_text(
        model_text
        + '\nbegin actions\n  simulate({method=>"nfcore", param=>"-rnf run.rnf"})\nend actions\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [str(bng_cpp), str(bngl_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc


# 1. NFC-01: TotalRate symmetric binding, unbinding, and RNF set/update
def test_nfc01_totalrate_symmetric_binding_and_unbinding():
    bind_model = """begin model
begin parameters
  k 10.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1000
end seed species
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) k TotalRate
end reaction rules
end model
"""
    stats = _run_nf_ensemble(bind_model, ["Afree"], t_end=10.0, n_runs=25, seed_base=1)
    # Exact mean: 1000 - 2 * k * t = 800.0 (0.5x bug gives 900.0)
    _assert_close_ensemble(*stats["Afree"], expected=800.0, min_tol=15.0)

    unbind_model = """begin model
begin parameters
  k 10.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 500
end seed species
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b!1).A(b!1) -> A(b) + A(b) k TotalRate
end reaction rules
end model
"""
    ustats = _run_nf_ensemble(
        unbind_model, ["Afree"], t_end=10.0, n_runs=25, seed_base=50
    )
    # Exact mean: 2 * k * t = 200.0 (0.5x bug gives 100.0)
    _assert_close_ensemble(*ustats["Afree"], expected=200.0, min_tol=15.0)


def test_nfc01_totalrate_symmetric_rnf_update(tmp_path):
    model = """begin model
begin parameters
  k 10.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1000
end seed species
begin observables
  Molecules Afree A(b)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) k TotalRate
end reaction rules
end model
"""
    vals = []
    for seed in range(1, 16):
        sub = tmp_path / f"s{seed}"
        sub.mkdir()
        proc = _run_bng_cpp_rnf(
            sub, model, f"-seed {seed}\nbegin\n  set k 20\n  update\n  sim 10 1\nend\n"
        )
        assert proc.returncode == 0, proc.stderr
        arr = np.loadtxt(sub / "run.gdat")
        vals.append(float(arr[-1, 1]))
    arr = np.asarray(vals, dtype=float)
    mean = float(arr.mean())
    se = float(arr.std(ddof=1) / math.sqrt(len(arr)))
    # Exact mean: 1000 - 2 * 20 * 10 = 600 (halved bug gives 800)
    _assert_close_ensemble(mean, se, expected=600.0, min_tol=25.0)


# 2. NFC-02: TotalRate rules in compartments NOT divided by V
def test_nfc02_totalrate_in_compartment_not_scaled_by_volume():
    for rate_block, rate_expr in [
        ("", "k"),
        ("begin functions\n  f_rate() = k\nend functions\n", "f_rate()"),
    ]:
        source = f"""begin model
begin parameters
  k 10.0
end parameters
begin compartments
  EC 3 10
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@EC 1000
  B(a)@EC 1000
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
{rate_block}begin reaction rules
  A(b)@EC + B(a)@EC -> A(b!1)@EC.B(a!1)@EC {rate_expr} TotalRate
end reaction rules
end model
"""
        stats = _run_nf_ensemble(source, ["AB"], t_end=10.0, n_runs=20, seed_base=10)
        # Exact mean = k * t = 100.0 (1/V bug gives 10.0)
        _assert_close_ensemble(*stats["AB"], expected=100.0, min_tol=12.0)


# 3. NFC-05: Symmetric compiled rules apply 1/V compartment volume scaling
def test_nfc05_symmetric_compiled_rule_compartment_volume_scaling():
    source = """begin model
begin parameters
  kf 0.1
end parameters
begin compartments
  EC 3 10
end compartments
begin molecule types
  A(b,b)
  B(a)
end molecule types
begin seed species
  A(b,b)@EC 100
  B(a)@EC 100
end seed species
begin observables
  Molecules Bonds A(b!1).B(a!1)
end observables
begin reaction rules
  A(b)@EC + B(a)@EC -> A(b!1)@EC.B(a!1)@EC kf
end reaction rules
end model
"""
    ode = _run_ode_final(source, ["Bonds"], t_end=0.2)
    stats = _run_nf_ensemble(source, ["Bonds"], t_end=0.2, n_runs=20, seed_base=20)
    # ODE ~30.7; missing 1/V bug gives ~89
    _assert_close_ensemble(*stats["Bonds"], expected=ode["Bonds"], min_tol=4.0)


# 4. NFC-03: DORRxnClass::pickMappingSets right-subtree balance on pure-context complexes
def test_nfc03_dor_pick_no_right_subtree_starvation():
    source_non_dor_homodimer = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~0~1, tag~0~1)
  E(d)
end molecule types
begin seed species
  A(s~0, tag~0) 1
  A(s~0, tag~1) 1
  E(d!1).E(d!1) 1
end seed species
begin observables
  Molecules A1_t0 A(s~1, tag~0)
  Molecules A1_t1 A(s~1, tag~1)
  Molecules is_t1 A(tag~1)
end observables
begin functions
  f(x) = k * (1 + 1e-6*is_t1(x))
end functions
begin reaction rules
  %x:A(s~0) + E(d!1).E(d!1) -> A(s~1) + E(d!1).E(d!1) f(x)
end reaction rules
end model
"""
    stats = _run_nf_ensemble(
        source_non_dor_homodimer, ["A1_t0", "A1_t1"], t_end=5.0, n_runs=30, seed_base=1
    )
    # Both tags must fire (exact p = 1 - exp(-5) ≈ 0.993; bug gave A1_t1 = 0.0!)
    assert stats["A1_t0"][0] > 0.85
    assert stats["A1_t1"][0] > 0.85

    source_self_trimer = """begin model
begin parameters
  k 5.0
end parameters
begin compartments
  EC 3 1
  CP 3 1
end compartments
begin molecule types
  E(d, d, t~0~1)
  P()
end molecule types
begin seed species
  E(d!1,d!2,t~1)@CP.E(d!1,d!3,t~1)@CP.E(d!2,d!3,t~1)@CP 1
  E(d,d,t~0)@EC 1
end seed species
begin observables
  Molecules P_EC P()@EC
  Molecules P_CP P()@CP
  Molecules is_t1 E(t~1)
end observables
begin functions
  f(x) = k * (1 + 1e-6*is_t1(x))
end functions
begin reaction rules
  %x:E()@EC -> E()@EC + P()@EC f(x)
  %x:E()@CP -> E()@CP + P()@CP f(x)
end reaction rules
end model
"""
    tstats = _run_nf_ensemble(
        source_self_trimer, ["P_EC", "P_CP"], t_end=10.0, n_runs=15, seed_base=1
    )
    # Each complex produces ~50 products (bug gave P_EC=0 or wrong rate)
    _assert_close_ensemble(*tstats["P_EC"], expected=50.0, min_tol=8.0)
    _assert_close_ensemble(*tstats["P_CP"], expected=50.0, min_tol=8.0)


# 5. NFC-08: System::replenishFixedSpecies preserves state, non-fixed states, and compartments
def test_nfc08_fixed_species_state_isolation_and_multi_compartments():
    # Case A: Non-default fixed state $A(b, s~1)
    src_state = """begin model
begin molecule types
  A(b, s~0~1)
  B(a)
end molecule types
begin seed species
  $A(b, s~1) 50
  B(a) 50
end seed species
begin observables
  Molecules A0_free A(b, s~0)
  Molecules A1_free A(b, s~1)
  Molecules AB A(b!1, s~1).B(a!1)
end observables
begin reaction rules
  A(b, s~1) + B(a) -> A(b!1, s~1).B(a!1) 0.05
end reaction rules
end model
"""
    stats_a = _run_nf_ensemble(
        src_state, ["A0_free", "A1_free", "AB"], t_end=2.0, n_runs=10, seed_base=1
    )
    assert stats_a["A0_free"][0] == pytest.approx(0.0)
    assert stats_a["A1_free"][0] == pytest.approx(50.0)
    assert stats_a["AB"][0] > 45.0

    # Case B: Fixed $A(s~0) + untouched non-fixed A(s~1)
    src_mix = """begin model
begin molecule types
  A(s~0~1)
  P()
end molecule types
begin seed species
  $A(s~0) 100
  A(s~1) 50
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
  Molecules Ptot P()
end observables
begin reaction rules
  A(s~0) -> P() 2.0
end reaction rules
end model
"""
    stats_b = _run_nf_ensemble(
        src_mix, ["A0", "A1", "Ptot"], t_end=1.0, n_runs=10, seed_base=1
    )
    assert stats_b["A0"][0] == pytest.approx(100.0)
    assert stats_b["A1"][0] == pytest.approx(50.0)
    _assert_close_ensemble(*stats_b["Ptot"], expected=200.0, min_tol=15.0)

    # Case C: Two fixed species of same MoleculeType in different compartments
    src_comp = """begin model
begin compartments
  EC 3 1
  CP 3 1
end compartments
begin molecule types
  A()
  P()
  Q()
end molecule types
begin seed species
  $A()@EC 50
  $A()@CP 100
end seed species
begin observables
  Molecules A_EC A()@EC
  Molecules A_CP A()@CP
  Molecules Ptot P()@EC
  Molecules Qtot Q()@CP
end observables
begin reaction rules
  A()@EC -> P()@EC 2.0
  A()@CP -> Q()@CP 2.0
end reaction rules
end model
"""
    stats_c = _run_nf_ensemble(
        src_comp, ["A_EC", "A_CP", "Ptot", "Qtot"], t_end=1.0, n_runs=10, seed_base=1
    )
    assert stats_c["A_EC"][0] == pytest.approx(50.0)
    assert stats_c["A_CP"][0] == pytest.approx(100.0)
    _assert_close_ensemble(*stats_c["Ptot"], expected=100.0, min_tol=12.0)
    _assert_close_ensemble(*stats_c["Qtot"], expected=200.0, min_tol=18.0)


# 6. NFC-09: RNF saveConcentrations + resetConcentrations no crash & preserves self-bonds
def test_nfc09_rnf_save_and_reset_concentrations_and_self_bonds(tmp_path):
    model = """begin model
begin molecule types
  A(b, c, s~0~1)
end molecule types
begin seed species
  A(b!1, c!1, s~0) 50
end seed species
begin observables
  Molecules A0_ring A(b!1, c!1, s~0)
  Molecules A1_ring A(b!1, c!1, s~1)
  Molecules A_open A(b, c)
end observables
begin reaction rules
  A(s~0) -> A(s~1) 5.0
end reaction rules
end model
"""
    rnf = "-seed 1\nbegin\n  saveConcentrations\n  sim 2.0 1\n  resetConcentrations\n  sim 1e-6 1\nend\n"
    proc = _run_bng_cpp_rnf(tmp_path, model, rnf)
    assert proc.returncode == 0, proc.stderr
    arr = np.loadtxt(tmp_path / "run.gdat")
    # Last row is right after resetConcentrations: all 50 self-bonded rings restored to s~0!
    assert arr[-1, 1] == pytest.approx(50.0)
    assert arr[-1, 2] == pytest.approx(0.0)
    assert arr[-1, 3] == pytest.approx(0.0)


# 7. NFC-13: Zero-rate elementary rule retained and activated by RNF set/update
def test_nfc13_zero_rate_rule_activated_by_rnf_set(tmp_path):
    model = """begin model
begin parameters
  kon 0
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 500
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
end observables
begin reaction rules
  R1: A(s~0) -> A(s~1) kon
end reaction rules
end model
"""
    rnf = "-seed 1\nbegin\n  set kon 5\n  update\n  sim 2.0 2\nend\n"
    proc = _run_bng_cpp_rnf(tmp_path, model, rnf)
    assert proc.returncode == 0, proc.stderr
    arr = np.loadtxt(tmp_path / "run.gdat")
    assert arr[-1, 2] > 480.0


# 8. NFC-14: RNF set/update propagates to expr rates, derived params, MM/Sat/Hill exprs, and Arrhenius
def test_nfc14_rnf_update_expr_derived_saturating_and_arrhenius(tmp_path):
    # A. Derived parameter + arithmetic expression rate
    m_expr = """begin model
begin parameters
  p1 0.0
  k 2*p1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 300
  B() 300
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> 0 k
  B() -> 0 2*p1
end reaction rules
end model
"""
    sub_a = tmp_path / "expr"
    sub_a.mkdir()
    proc_a = _run_bng_cpp_rnf(
        sub_a, m_expr, "-seed 1\nbegin\n  set p1 5\n  update\n  sim 1.0 1\nend\n"
    )
    assert proc_a.returncode == 0, proc_a.stderr
    arr_a = np.loadtxt(sub_a / "run.gdat")
    assert arr_a[-1, 1] < 10.0
    assert arr_a[-1, 2] < 10.0

    # B. MM / Sat / Hill with expression arguments
    m_sat = """begin model
begin parameters
  k0 0.0
  Km 10.0
end parameters
begin molecule types
  S1()
  E1()
  S2()
  S3()
end molecule types
begin seed species
  S1() 100
  E1() 10
  S2() 100
  S3() 100
end seed species
begin observables
  Molecules O1 S1()
  Molecules O2 S2()
  Molecules O3 S3()
end observables
begin reaction rules
  S1() + E1() -> E1() MM(2*k0, Km)
  S2() -> 0 Sat(2*k0, Km)
  S3() -> 0 Hill(2*k0, Km, 2)
end reaction rules
end model
"""
    sub_b = tmp_path / "sat"
    sub_b.mkdir()
    proc_b = _run_bng_cpp_rnf(
        sub_b, m_sat, "-seed 1\nbegin\n  set k0 50\n  update\n  sim 5.0 1\nend\n"
    )
    assert proc_b.returncode == 0, proc_b.stderr
    arr_b = np.loadtxt(sub_b / "run.gdat")
    assert arr_b[-1, 1] < 5.0
    assert arr_b[-1, 2] < 5.0
    assert arr_b[-1, 3] < 5.0

    # C. Arrhenius rule updated by set Ea0
    m_arr = """begin model
begin parameters
  phi 0.5
  Ea0 20.0
  G -4.0
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 200
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1) G
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    sub_c = tmp_path / "arr"
    sub_c.mkdir()
    proc_c = _run_bng_cpp_rnf(
        sub_c, m_arr, "-seed 1\nbegin\n  set Ea0 0.0\n  update\n  sim 5.0 1\nend\n"
    )
    assert proc_c.returncode == 0, proc_c.stderr
    arr_c = np.loadtxt(sub_c / "run.gdat")
    # Equilibrium A1 ≈ 200 / (1 + exp(-4)) ≈ 196.4 (frozen Ea0=20 gives 0)
    assert arr_c[-1, 1] > 180.0


# 9. NFC-15: Unary double negation and logical not in compiled nfcore
def test_nfc15_muparser_double_negation_and_logical_not():
    source = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 200
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  frate() = -(-k) + !(k == 0)
end functions
begin reaction rules
  A() -> 0 frate()
end reaction rules
end model
"""
    stats = _run_nf_ensemble(source, ["Atot"], t_end=1.0, n_runs=10, seed_base=1)
    # frate() = 1.0 + 1.0 = 2.0 => 200 * exp(-2) ≈ 27.1
    _assert_close_ensemble(*stats["Atot"], expected=200.0 * math.exp(-2.0), min_tol=6.0)


# 10. MEM-09 / NFC-21: Bare eq in RNF script handled without crashing
def test_mem09_rnf_bare_eq_no_crash(tmp_path):
    model = """begin model
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
  A() -> 0 1.0
end reaction rules
end model
"""
    proc = _run_bng_cpp_rnf(tmp_path, model, "-seed 1\nbegin\n  eq\n  sim 1.0 1\nend\n")
    assert proc.returncode == 0, proc.stderr


# 11. ETH-05: MWC allosteric 4-state square & 8-state cube detailed balance
def test_eth05_mwc_square_and_8state_cube_detailed_balance():
    mwc_square = """begin model
begin parameters
  phi 0.5
  Ea_s 0.0
  Ea_b 2.0
  G_R  2.0
  G_L  -1.0
  G_coop -5.0
end parameters
begin molecule types
  R(t~T~R, l)
  L(r)
end molecule types
begin seed species
  R(t~T, l) 50
  L(r)      50
end seed species
begin observables
  Molecules RT_free  R(t~T, l)
  Molecules RR_free  R(t~R, l)
  Molecules RT_bound R(t~T, l!1).L(r!1)
  Molecules RR_bound R(t~R, l!1).L(r!1)
end observables
begin energy patterns
  R(t~R) G_R
  R(l!1).L(r!1) G_L
  R(t~R, l!1).L(r!1) G_coop
end energy patterns
begin reaction rules
  R(t~T) <-> R(t~R) Arrhenius(phi, Ea_s)
  R(l) + L(r) <-> R(l!1).L(r!1) Arrhenius(phi, Ea_b)
end reaction rules
end model
"""
    ode = _run_ode_final(
        mwc_square, ["RT_free", "RR_free", "RT_bound", "RR_bound"], t_end=150.0
    )
    stats = _run_nf_ensemble(
        mwc_square,
        ["RT_free", "RR_free", "RT_bound", "RR_bound"],
        t_end=150.0,
        n_runs=25,
        seed_base=1,
    )
    for k in ("RT_free", "RR_free", "RT_bound", "RR_bound"):
        _assert_close_ensemble(*stats[k], expected=ode[k], min_tol=1.5)

    cube = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  J   -2.0
end parameters
begin molecule types
  A(x~0~1, y~0~1, z~0~1)
end molecule types
begin seed species
  A(x~0, y~0, z~0) 100
end seed species
begin observables
  Molecules A111 A(x~1, y~1, z~1)
  Molecules A000 A(x~0, y~0, z~0)
end observables
begin energy patterns
  A(x~1, y~1) J
  A(y~1, z~1) J
  A(x~1, z~1) J
end energy patterns
begin reaction rules
  A(x~0) <-> A(x~1) Arrhenius(phi, Ea)
  A(y~0) <-> A(y~1) Arrhenius(phi, Ea)
  A(z~0) <-> A(z~1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode_c = _run_ode_final(cube, ["A111", "A000"], t_end=30.0)
    stats_c = _run_nf_ensemble(
        cube, ["A111", "A000"], t_end=30.0, n_runs=20, seed_base=10
    )
    _assert_close_ensemble(*stats_c["A111"], expected=ode_c["A111"], min_tol=2.5)
    _assert_close_ensemble(*stats_c["A000"], expected=ode_c["A000"], min_tol=1.5)


# 12. ETH-06: Arrhenius binding compartment volume scaling (1/V and 1/(NA*V))
def test_eth06_arrhenius_binding_compartment_volume_scaling():
    source = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  GAB -2.0
end parameters
begin compartments
  EC 3 10
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@EC 100
  B(a)@EC 100
end seed species
begin observables
  Molecules AB A(b!1)@EC.B(a!1)@EC
end observables
begin energy patterns
  A(b!1)@EC.B(a!1)@EC GAB
end energy patterns
begin reaction rules
  A(b)@EC + B(a)@EC <-> A(b!1)@EC.B(a!1)@EC Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode = _run_ode_final(source, ["AB"], t_end=50.0)
    stats = _run_nf_ensemble(source, ["AB"], t_end=50.0, n_runs=20, seed_base=1)
    # Exact ODE ~89.02 (missing 1/V bug gave 96.6)
    _assert_close_ensemble(*stats["AB"], expected=ode["AB"], min_tol=1.8)


# 13. ETH-07: Rule-level state and bond context constraints preserved on Arrhenius rules
def test_eth07_arrhenius_rule_level_context_constraints():
    bind_ctx = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  G   -3.0
end parameters
begin molecule types
  A(b, s~U~P)
  B(a)
end molecule types
begin seed species
  A(b, s~U) 50
  B(a)      50
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b!1).B(a!1) G
end energy patterns
begin reaction rules
  A(b, s~P) + B(a) <-> A(b!1, s~P).B(a!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    res1 = cpp.simulate_nf(cpp.parse_string(bind_ctx), t_end=5.0, n_steps=2, seed=1)
    assert float(res1["observables"]["AB"][-1]) == pytest.approx(0.0)

    state_ctx = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  G   -2.0
end parameters
begin molecule types
  A(s~0~1, x~0~1, b)
end molecule types
begin seed species
  A(s~0, x~0, b) 50
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1) G
end energy patterns
begin reaction rules
  A(s~0, x~1) <-> A(s~1, x~1) Arrhenius(phi, Ea)
  A(s~0, b!+) <-> A(s~1, b!+) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    res2 = cpp.simulate_nf(cpp.parse_string(state_ctx), t_end=5.0, n_steps=2, seed=1)
    assert float(res2["observables"]["A1"][-1]) == pytest.approx(0.0)


# 14. ETH-08: Multi-condition energy pattern uses AND, not OR
def test_eth08_multi_condition_energy_pattern_uses_conjunction(monkeypatch):
    monkeypatch.setenv("BNG_NFSIM_GENERAL_ENERGY", "1")
    source = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  G   -4.0
end parameters
begin molecule types
  A(s~0~1, x~0~1, y~0~1)
end molecule types
begin seed species
  A(s~0, x~1, y~0) 100
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1, x~1, y~1) G
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    stats = _run_nf_ensemble(source, ["A1"], t_end=20.0, n_runs=20, seed_base=1)
    # x=1, y=0 => EP does NOT match => deltaG=0 => A1 = 50.0 (OR bug gives ~98.2)
    _assert_close_ensemble(*stats["A1"], expected=50.0, min_tol=4.0)

    scaffold = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  GSA 2.0
  GSABC -6.0
end parameters
begin molecule types
  S(a, b, c)
  A(s)
  B(s)
  C(s)
end molecule types
begin seed species
  S(a, b!1, c).B(s!1) 30
  A(s) 30
end seed species
begin observables
  Molecules SA S(a!1).A(s!1)
end observables
begin energy patterns
  S(a!1).A(s!1) GSA
  S(a!1, b!2, c!3).A(s!1).B(s!2).C(s!3) GSABC
end energy patterns
begin reaction rules
  S(a) + A(s) <-> S(a!1).A(s!1) Arrhenius(phi, Ea) driven_by(1e-6)
end reaction rules
end model
"""
    ode = _run_ode_final(scaffold, ["SA"], t_end=30.0)
    sstats = _run_nf_ensemble(scaffold, ["SA"], t_end=30.0, n_runs=20, seed_base=1)
    # Exact ODE ~18.35 (OR bug gave 29.5)
    _assert_close_ensemble(*sstats["SA"], expected=ode["SA"], min_tol=2.0)


# 15. ETH-09: Bond-partner identity checked in both state-change and compact binding
def test_eth09_bond_partner_identity_checked():
    state_src = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  G   -4.0
end parameters
begin molecule types
  A(s~0~1, c)
  X(a)
  Y(a)
end molecule types
begin seed species
  A(s~0, c!1).Y(a!1) 100
  X(a)               0
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1, c!1).X(a!1) G
end energy patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    stats = _run_nf_ensemble(state_src, ["A1"], t_end=20.0, n_runs=20, seed_base=1)
    # Partner is Y, not X => deltaG=0 => A1 = 50.0 (bug gave 97.9)
    _assert_close_ensemble(*stats["A1"], expected=50.0, min_tol=4.0)

    bind_src = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  GAB 2.0
  GCOOP -6.0
end parameters
begin molecule types
  A(b, c)
  B(a)
  X(a)
  Y(a)
end molecule types
begin seed species
  A(b, c!1).Y(a!1) 50
  B(a) 50
  X(a) 0
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b!1).B(a!1) GAB
  A(b!1, c!2).B(a!1).X(a!2) GCOOP
end energy patterns
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode = _run_ode_final(bind_src, ["AB"], t_end=30.0)
    bstats = _run_nf_ensemble(bind_src, ["AB"], t_end=30.0, n_runs=20, seed_base=1)
    # ODE ~26.8 (bug gave 48.6)
    _assert_close_ensemble(*bstats["AB"], expected=ode["AB"], min_tol=2.5)


# 16. ETH-10: Homotypic Ising spin dimer and 4-spin ring match exact Boltzmann equilibrium
def test_eth10_ising_spin_dimer_and_ring():
    dimer = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  h   0.5
  JUU -3.0
end parameters
begin molecule types
  S(l, r, spin~D~U)
end molecule types
begin seed species
  S(l, r!1, spin~D).S(l!1, r, spin~D) 50
end seed species
begin observables
  Molecules UpSpins S(spin~U)
end observables
begin energy patterns
  S(spin~U) h
  S(r!1, spin~U).S(l!1, spin~U) JUU
end energy patterns
begin reaction rules
  S(spin~D) <-> S(spin~U) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode_d = _run_ode_final(dimer, ["UpSpins"], t_end=30.0)
    stats_d = _run_nf_ensemble(dimer, ["UpSpins"], t_end=30.0, n_runs=20, seed_base=1)
    # Exact Boltzmann = 83.27 (bug gave 99.75)
    _assert_close_ensemble(*stats_d["UpSpins"], expected=ode_d["UpSpins"], min_tol=3.0)

    ring = """begin model
begin parameters
  phi 0.5
  Ea  0.0
  h   0.5
  J   -1.5
end parameters
begin molecule types
  S(l, r, spin~D~U)
end molecule types
begin seed species
  S(l!4,r!1,spin~D).S(l!1,r!2,spin~D).S(l!2,r!3,spin~D).S(l!3,r!4,spin~D) 40
end seed species
begin observables
  Molecules UpSpins S(spin~U)
  Molecules AlignedUU S(r!1,spin~U).S(l!1,spin~U)
  Molecules AlignedDD S(r!1,spin~D).S(l!1,spin~D)
end observables
begin energy patterns
  S(spin~U) h
  S(r!1, spin~U).S(l!1, spin~U) J
  S(r!1, spin~D).S(l!1, spin~D) J
end energy patterns
begin reaction rules
  S(spin~D) <-> S(spin~U) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode_r = _run_ode_final(ring, ["UpSpins", "AlignedUU", "AlignedDD"], t_end=50.0)
    stats_r = _run_nf_ensemble(
        ring, ["UpSpins", "AlignedUU", "AlignedDD"], t_end=50.0, n_runs=20, seed_base=1
    )
    _assert_close_ensemble(*stats_r["UpSpins"], expected=ode_r["UpSpins"], min_tol=5.0)
    aligned_mean = stats_r["AlignedUU"][0] + stats_r["AlignedDD"][0]
    aligned_ode = ode_r["AlignedUU"] + ode_r["AlignedDD"]
    assert abs(aligned_mean - aligned_ode) < 12.0


# 17. ETH-11 & ETH-02: Unbound-site and wildcard-bond energy patterns
def test_eth11_unbound_site_and_wildcard_bond_energy_patterns():
    unbound_src = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  G_free 5.0
  GAB 3.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 30
  B(a) 30
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b) G_free
  A(b!1).B(a!1) GAB
end energy patterns
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode_u = _run_ode_final(unbound_src, ["AB"], t_end=30.0)
    stats_u = _run_nf_ensemble(unbound_src, ["AB"], t_end=30.0, n_runs=20, seed_base=1)
    # Exact ~28.05 (bug gave 13.1)
    _assert_close_ensemble(*stats_u["AB"], expected=ode_u["AB"], min_tol=2.0)

    wild_src = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  Gb -3.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 30
  B(a) 30
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b!+) Gb
end energy patterns
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode_w = _run_ode_final(wild_src, ["AB"], t_end=30.0)
    stats_w = _run_nf_ensemble(wild_src, ["AB"], t_end=30.0, n_runs=20, seed_base=1)
    _assert_close_ensemble(*stats_w["AB"], expected=ode_w["AB"], min_tol=2.0)


# 18. BUG-18: One-way Arrhenius unbinding on default compiled nfcore
def test_bug18_one_way_arrhenius_unbinding():
    source = """begin model
begin parameters
  phi 0.5
  Ea0 0.0
  GAB -2.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 500
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b!1).B(a!1) GAB
end energy patterns
begin reaction rules
  A(b!1).B(a!1) -> A(b) + B(a) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    ode = _run_ode_final(source, ["AB"], t_end=1.0)
    stats = _run_nf_ensemble(source, ["AB"], t_end=1.0, n_runs=15, seed_base=1)
    # k = exp(-(0 + 0.5 * (+2))) = exp(-1) => 500 * exp(-exp(-1)) ≈ 346.1
    _assert_close_ensemble(*stats["AB"], expected=ode["AB"], min_tol=15.0)


# 19. MEM-03: TinyXML recursion depth limit prevents stack overflow
def test_mem03_tinyxml_depth_limit_fails_cleanly(tmp_path):
    bng_cpp = _require_bng_cpp()
    depth = 1500
    deep_xml = tmp_path / "deep.xml"
    deep_xml.write_text("<a>" * depth + "</a>" * depth, encoding="utf-8")
    driver = tmp_path / "driver.bngl"
    driver.write_text(f'readFile({{file=>"{deep_xml.name}"}})\n', encoding="utf-8")
    proc = subprocess.run(
        [str(bng_cpp), str(driver)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Must fail cleanly (non-zero return code > 0), NOT crash with signal (returncode < 0)
    assert (
        proc.returncode > 0
    ), f"Expected clean error, got rc={proc.returncode}, stderr={proc.stderr}"


# 20. MEM-04: High-rate NFsim model avoids float-to-int overflow UB
def test_mem04_high_rate_nfsim_no_float_to_int_ub():
    source = """begin model
begin parameters
  k 1e11
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
"""
    res = cpp.simulate_nf(cpp.parse_string(source), t_end=1e-10, n_steps=2, seed=1)
    assert float(res["observables"]["Aobs"][-1]) < 100.0
