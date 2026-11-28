"""Wave 2 regression tests for PSA, PLA, Batch SSA (CPU/GPU), HybridModelGenerator, and engine bindings.

Covers verified audit findings:
  - SSA-01: Non-adjacent identical reactants (A + B + A -> C) in PSA & PLA
  - SSA-02 / ODE-08: PsaSimulator statFactor not squared (statFactor * k, not statFactor^2 * k)
  - SSA-03 / PERF-07: PsaSimulator & PlaSimulator observable matching (unbound sites, Species clamp, @COMP:)
  - SSA-04 (Hlavacek #123): PsaSimulator periodic Fenwick/aTot rebuild preventing slow-channel starvation
  - SSA-05: PsaSimulator mass conservation & non-freezing for poplevel <= reactant stoichiometry
  - SSA-06: PlaSimulator computeTau does not skip zero-count non-fixed species (0 -> A, $A -> B)
  - SSA-07: PlaSimulator classifies channels by expected firings a[r] * tau (not raw a[r])
  - SSA-08: PlaSimulator rollback shrinks tau without infinite loop
  - SSA-09: Relative output-time tolerance in Metal/CUDA GPU Batch SSA on fast timescales
  - SSA-10: Relative GPU clock & float32 dynamic-range fail-closed / CPU fallback
  - SSA-11: HybridModelGenerator unbound site matching (treatUnspecifiedBondAsWildcard=false)
  - SSA-13: Batch SSA max_sim_steps grid synchronization & output_step_interval rejection
  - SSA-14: Unseeded (seed=0) Batch SSA draws fresh random seeds
  - SSA-15: bind_engine.cpp simulate_psa / simulate_pla expose seed, sample_times, check_product_scale
  - SSA-16 / ODE-09 / MEM-04: PlaSimulator volume scaling, functional rates, full grid on a0==0,
    no 32-bit int overflow UB, fail-closed unsupported configs, no post-eps mass creation
  - SSA-18: PsaSimulator dynamic observable-dependent functional rates
  - B14 / B16: jax_ode_flatten volume_scales export and fail-closed delay/algebraic-rule guards
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from bionetgen import _bionetgen_cpp as cpp


def _usable_gpu_backend() -> str | None:
    backend = cpp.default_gpu_backend()
    return backend if backend in {"metal", "cuda"} else None


# ---------------------------------------------------------------------------
# PSA tests (SSA-01, SSA-02/ODE-08, SSA-03, SSA-04, SSA-05, SSA-15, SSA-18)
# ---------------------------------------------------------------------------


def test_psa_stat_factor_not_squared_homodimer_and_symmetric_site():
    """SSA-02 / ODE-08: PsaSimulator must apply statFactor once, not statFactor^2."""
    # Case 1: 2A -> A2 (statFactor = 0.5). Exact ODE A(10) = 100/(1 + 100*0.001*10) = 50.0.
    # Buggy statFactor^2 gave 66.67.
    dimer_src = """begin model
begin parameters
  k 0.001
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 100
end seed species
begin observables
  Molecules A_free A(b)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) k
end reaction rules
end model
"""
    m1 = cpp.parse_string(dimer_src)
    n1 = cpp.generate_network(m1)
    finals = [
        float(
            cpp.simulate_psa(m1, n1, t_end=10.0, n_steps=5, poplevel=1000.0, seed=s)[
                "observables"
            ]["A_free"][-1]
        )
        for s in range(1, 61)
    ]
    mean_a = float(np.mean(finals))
    assert (
        abs(mean_a - 50.0) < 4.0
    ), f"Expected ~50.0 (statFactor=0.5), got {mean_a:.2f}"

    # Case 2: A(b~U,b~U) -> A(b~U,b~P) (statFactor = 2.0). Exact E[AUU(1)] = 100*exp(-1) = 36.79.
    # Buggy statFactor^2 gave 100*exp(-2) = 13.53. Use Species AUU (weight 1 per species).
    sym_src = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A(b~U~P,b~U~P)
end molecule types
begin seed species
  A(b~U,b~U) 100
end seed species
begin observables
  Species AUU A(b~U,b~U)
end observables
begin reaction rules
  A(b~U) -> A(b~P) k
end reaction rules
end model
"""
    m2 = cpp.parse_string(sym_src)
    n2 = cpp.generate_network(m2)
    finals2 = [
        float(
            cpp.simulate_psa(m2, n2, t_end=1.0, n_steps=5, poplevel=1000.0, seed=s)[
                "observables"
            ]["AUU"][-1]
        )
        for s in range(1, 61)
    ]
    mean_auu = float(np.mean(finals2))
    exact_auu = 100.0 * math.exp(-1.0)
    assert (
        abs(mean_auu - exact_auu) < 4.0
    ), f"Expected ~{exact_auu:.2f} (statFactor=2), got {mean_auu:.2f}"


def test_psa_and_pla_non_adjacent_identical_reactants():
    """SSA-01: A + B + A -> C with A(0)=1, B(0)=1 must have zero propensity."""
    src = """begin model
begin parameters
  k 10.0
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 1
  B() 1
  C() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
  Molecules Ctot C()
end observables
begin reaction rules
  A() + B() + A() -> C() k
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    for poplevel in (0.0, 10.0):
        res_psa = cpp.simulate_psa(
            model, net, t_end=10.0, n_steps=5, poplevel=poplevel, seed=1
        )
        assert res_psa["observables"]["Atot"][-1] == 1.0
        assert res_psa["observables"]["Btot"][-1] == 1.0
        assert res_psa["observables"]["Ctot"][-1] == 0.0

    res_pla = cpp.simulate_pla(model, net, t_end=10.0, n_steps=5, seed=1)
    assert res_pla["observables"]["Atot"][-1] == 1.0
    assert res_pla["observables"]["Btot"][-1] == 1.0
    assert res_pla["observables"]["Ctot"][-1] == 0.0


def test_psa_and_pla_observables_unbound_species_and_compartments():
    """SSA-03 / SSA-16 / PERF-07: unbound site matching, Species weight=1, and @COMP:."""
    dimer_src = """begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 100
end seed species
begin observables
  Molecules A_free A(b)
  Species A2_spec A(b!1).A(b!1)
  Molecules A2_mol A(b!1).A(b!1)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) k
end reaction rules
end model
"""
    m1 = cpp.parse_string(dimer_src)
    n1 = cpp.generate_network(m1)

    for fn in (
        lambda: cpp.simulate_psa(m1, n1, t_end=5.0, n_steps=5, poplevel=1000.0, seed=7),
        lambda: cpp.simulate_pla(m1, n1, t_end=5.0, n_steps=5, seed=7),
    ):
        res = fn()
        a_free = np.asarray(res["observables"]["A_free"])
        a2_spec = np.asarray(res["observables"]["A2_spec"])
        a2_mol = np.asarray(res["observables"]["A2_mol"])
        assert a2_spec[-1] > 0.0
        np.testing.assert_allclose(a_free + 2.0 * a2_spec, 100.0, atol=1e-9)
        np.testing.assert_allclose(a2_mol, 2.0 * a2_spec, atol=1e-9)

    comp_src = """begin model
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @EC:A() 200
  @CP:A() 100
end seed species
begin observables
  Molecules A_EC @EC:A()
  Molecules A_CP @CP:A()
end observables
begin reaction rules
  @EC:A() -> @EC:A() 0.0
end reaction rules
end model
"""
    m2 = cpp.parse_string(comp_src)
    n2 = cpp.generate_network(m2)
    for res in (
        cpp.simulate_psa(m2, n2, t_end=1.0, n_steps=2, poplevel=10.0, seed=1),
        cpp.simulate_pla(m2, n2, t_end=1.0, n_steps=2, seed=1),
    ):
        assert res["observables"]["A_EC"][0] == 200.0
        assert res["observables"]["A_CP"][0] == 100.0


def test_psa_fenwick_drift_does_not_starve_slow_channel_hlavacek_123():
    """SSA-04 (Hlavacek #123): Slow channel must fire after fast channel empties."""
    src = """begin model
begin parameters
  kf 1e6
  ks 1e-7
end parameters
begin molecule types
  A()
  B()
  C()
  D()
end molecule types
begin seed species
  A() 100
  B() 100
  C() 0
  D() 0
end seed species
begin observables
  Molecules Dtot D()
end observables
begin reaction rules
  A() + B() -> C() kf
  0 -> D() ks
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    d_counts = [
        float(
            cpp.simulate_psa(model, net, t_end=1e8, n_steps=1, poplevel=1000.0, seed=s)[
                "observables"
            ]["Dtot"][-1]
        )
        for s in range(1, 16)
    ]
    mean_d = float(np.mean(d_counts))
    # Exact D ~ Poisson(10.0). Buggy PSA returned 0.0 on every seed.
    assert (
        mean_d > 5.0 and mean_d < 16.0
    ), f"Expected Poisson(10) mean, got {mean_d:.2f}"


def test_psa_small_poplevel_preserves_mass_and_does_not_freeze():
    """SSA-05: poplevel <= reactant stoichiometry must conserve mass and not freeze."""
    src = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 100
end seed species
begin observables
  Molecules A_free A(b)
  Species A2_spec A(b!1).A(b!1)
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) k
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    for check_prod in (True, False):
        res = cpp.simulate_psa(
            model,
            net,
            t_end=10.0,
            n_steps=5,
            poplevel=1.0,
            seed=1,
            check_product_scale=check_prod,
        )
        a_free = np.asarray(res["observables"]["A_free"])
        a2_spec = np.asarray(res["observables"]["A2_spec"])
        # Exact mass conservation at every timepoint (buggy check_product_scale=1 gave 128).
        np.testing.assert_allclose(a_free + 2.0 * a2_spec, 100.0, atol=1e-9)
        # Reaction must progress (buggy check_product_scale=0 froze at A_free=100).
        assert (
            a_free[-1] < 20.0
        ), f"check_product_scale={check_prod} froze at {a_free[-1]}"


def test_psa_observable_functional_rates():
    """SSA-18: PsaSimulator evaluates observable-dependent functional rates."""
    src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  f_rate() = 0.5 * Atot
end functions
begin reaction rules
  0 -> A() 10.0
  A() -> 0 f_rate()
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    # Exact ODE steady state: 0.5 * A^2 = 10 => A* = sqrt(20) ~ 4.472.
    finals = [
        float(
            cpp.simulate_psa(model, net, t_end=5.0, n_steps=5, poplevel=100.0, seed=s)[
                "observables"
            ]["Atot"][-1]
        )
        for s in range(1, 41)
    ]
    mean_a = float(np.mean(finals))
    assert 3.0 < mean_a < 6.5, f"Expected steady state near 4.47, got {mean_a:.2f}"

    # Time-dependent functional rates must still fail closed.
    time_src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin functions
  f_t() = 1.0 + time()
end functions
begin reaction rules
  A() -> 0 f_t()
end reaction rules
end model
"""
    m_time = cpp.parse_string(time_src)
    n_time = cpp.generate_network(m_time)
    with pytest.raises(RuntimeError, match="time-dependent"):
        cpp.simulate_psa(m_time, n_time, t_end=1.0, n_steps=2, poplevel=10.0, seed=1)


# ---------------------------------------------------------------------------
# PLA tests (SSA-06, SSA-07, SSA-08, SSA-16, ODE-09, MEM-04)
# ---------------------------------------------------------------------------


def test_pla_zero_initial_species_zeroth_order_and_buffered():
    """SSA-06: PlaSimulator must not skip simulation when non-fixed species start at 0."""
    src_zero = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  0 -> A() 10.0
end reaction rules
end model
"""
    m1 = cpp.parse_string(src_zero)
    n1 = cpp.generate_network(m1)
    vals1 = [
        float(
            cpp.simulate_pla(m1, n1, t_end=2.0, n_steps=5, seed=s)["observables"][
                "Atot"
            ][-1]
        )
        for s in range(1, 31)
    ]
    assert 15.0 < float(np.mean(vals1)) < 25.0

    src_buf = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  $A() 10
  B() 0
end seed species
begin observables
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() 1.0
end reaction rules
end model
"""
    m2 = cpp.parse_string(src_buf)
    n2 = cpp.generate_network(m2)
    vals2 = [
        float(
            cpp.simulate_pla(m2, n2, t_end=2.0, n_steps=5, seed=s)["observables"][
                "Btot"
            ][-1]
        )
        for s in range(1, 31)
    ]
    assert 15.0 < float(np.mean(vals2)) < 25.0


def test_pla_classifies_by_expected_firings_not_raw_propensity():
    """SSA-07: Medium-fast channel (a=200, a*tau << 1) must not freeze at 0."""
    src = """begin model
begin parameters
  kf 1e4
  kz 200.0
end parameters
begin molecule types
  X()
  Y()
  Z()
end molecule types
begin seed species
  X() 1000
  Y() 1000
  Z() 0
end seed species
begin observables
  Molecules Ztot Z()
end observables
begin reaction rules
  X() -> Y() kf
  Y() -> X() kf
  0 -> Z() kz
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    res = cpp.simulate_pla(model, net, t_end=0.5, n_steps=5, seed=1)
    z_end = float(res["observables"]["Ztot"][-1])
    # Exact E[Z(0.5)] = 100.0 (SD = 10). Buggy PLA produced 0.0.
    assert 60.0 < z_end < 140.0, f"Expected Z(0.5) ~ 100, got {z_end}"


def test_pla_rollback_terminates_and_preserves_mass_across_check_types():
    """SSA-08 & SSA-16: Rollback shrinks tau cleanly; post-eps never creates mass."""
    # Bug 8 reproducer (previously infinite loop)
    src_loop = """begin model
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
  A() -> 0 1000.0
end reaction rules
end model
"""
    m1 = cpp.parse_string(src_loop)
    n1 = cpp.generate_network(m1)
    res1 = cpp.simulate_pla(
        m1,
        n1,
        t_end=1.0,
        n_steps=10,
        config_str="fEuler|post-neg:sb|tau=1.0,w=0.5",
        seed=1,
    )
    assert len(res1["time"]) == 11
    assert np.all(np.asarray(res1["observables"]["Atot"]) >= 0.0)
    assert res1["observables"]["Atot"][-1] == 0.0

    # Bug 16 #5 reproducer (post-eps mass creation: previously A=0, B=200 from A=20)
    src_mass = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20
  B() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() 10.0
end reaction rules
end model
"""
    m2 = cpp.parse_string(src_mass)
    n2 = cpp.generate_network(m2)
    res2 = cpp.simulate_pla(
        m2, n2, t_end=1.0, n_steps=5, config_str="fEuler|post-eps:sb|tau=1.0", seed=1
    )
    total = np.asarray(res2["observables"]["Atot"]) + np.asarray(
        res2["observables"]["Btot"]
    )
    np.testing.assert_allclose(total, 20.0, atol=1e-9)


def test_pla_compartment_volume_scaling_functional_rates_full_grid_and_high_rate():
    """ODE-09, SSA-16, MEM-04: volume scaling, functional rates, a0==0 grid, high rate."""
    # ODE-09: compartment volume scaling (V=10 => k_eff = 0.001 => AB(1) ~ 500, not 909)
    comp_src = """begin model
begin parameters
  k 0.01
end parameters
begin compartments
  C 3 10
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@C 1000
  B(a)@C 1000
end seed species
begin observables
  Molecules A_free A(b)
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b)@C + B(a)@C -> A(b!1)@C.B(a!1)@C k
end reaction rules
end model
"""
    mc = cpp.parse_string(comp_src)
    nc = cpp.generate_network(mc)
    resc = cpp.simulate_pla(mc, nc, t_end=1.0, n_steps=10, seed=42)
    ab_end = float(resc["observables"]["AB"][-1])
    assert 420.0 < ab_end < 580.0, f"Expected AB(1) ~ 500 (V=10), got {ab_end}"

    # SSA-16 #1: functional rate evaluation (not silently 0.0)
    func_src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  f_deg() = 0.5 * Atot
end functions
begin reaction rules
  0 -> A() 10.0
  A() -> 0 f_deg()
end reaction rules
end model
"""
    mf = cpp.parse_string(func_src)
    nf = cpp.generate_network(mf)
    vals_f = [
        float(
            cpp.simulate_pla(mf, nf, t_end=5.0, n_steps=5, seed=s)["observables"][
                "Atot"
            ][-1]
        )
        for s in range(1, 26)
    ]
    assert 3.0 < float(np.mean(vals_f)) < 6.5

    # SSA-16 #4: unsupported midpt / rk4 / :rb fail closed
    for bad_cfg in (
        "midpt|pre-neg:sb|eps=0.03",
        "rk4|pre-neg:sb|eps=0.03",
        "fEuler|pre-neg:rb|eps=0.03",
    ):
        with pytest.raises(RuntimeError):
            cpp.simulate_pla(mf, nf, t_end=1.0, n_steps=2, config_str=bad_cfg, seed=1)

    # SSA-16 #6: full output grid emitted when a0 == 0
    zero_src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 1.0
end reaction rules
end model
"""
    mz = cpp.parse_string(zero_src)
    nz = cpp.generate_network(mz)
    resz = cpp.simulate_pla(mz, nz, t_end=10.0, n_steps=20, seed=1)
    assert len(resz["time"]) == 21
    np.testing.assert_allclose(resz["time"], np.linspace(0.0, 10.0, 21))

    # MEM-04: high-rate reaction exceeding INT_MAX firings (no UB/overflow)
    hi_src = """begin model
begin parameters
  k 1e12
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1e9
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  0 -> A() k
end reaction rules
end model
"""
    mh = cpp.parse_string(hi_src)
    nh = cpp.generate_network(mh)
    resh = cpp.simulate_pla(mh, nh, t_end=1.0, n_steps=5, seed=1)
    a_end = float(resh["observables"]["Aobs"][-1])
    assert math.isfinite(a_end) and abs(a_end - (1e9 + 1e12)) / 1e12 < 0.05


# ---------------------------------------------------------------------------
# Batch SSA (CPU & GPU) tests (SSA-09, SSA-10, SSA-13, SSA-14)
# ---------------------------------------------------------------------------


def test_batch_ssa_cpu_max_sim_steps_grid_and_output_step_interval_guard():
    """SSA-13: max_sim_steps holds frozen state on full grid; output_step_interval rejected."""
    src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() 1.0
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    for threads in (1, 2):
        res = cpp.simulate_batch_ssa_cpu(
            model,
            net,
            batch_size=32,
            t_end=5.0,
            n_steps=10,
            base_seed=77,
            threads=threads,
            max_sim_steps=20,
        )
        assert len(res["time"]) == 11
        np.testing.assert_allclose(res["time"], np.linspace(0.0, 5.0, 11), atol=1e-5)
        a_mean = np.asarray(res["observable_means"]["Atot"], dtype=float)
        b_mean = np.asarray(res["observable_means"]["Btot"], dtype=float)
        # Exact mass conservation across the entire grid
        np.testing.assert_allclose(a_mean + b_mean, 100.0, atol=1e-4)
        # Final state frozen at A=80, B=20 after 20 steps
        np.testing.assert_allclose(a_mean[-1], 80.0, atol=1e-4)
        np.testing.assert_allclose(b_mean[-1], 20.0, atol=1e-4)

    # output_step_interval with batch_size > 0 must fail closed
    with pytest.raises((ValueError, RuntimeError), match="output_step_interval"):
        cpp.simulate_ssa(
            model,
            net,
            t_end=5.0,
            n_steps=10,
            batch_size=16,
            output_step_interval=5,
            seed=1,
        )


def test_batch_ssa_unseeded_produces_distinct_ensembles():
    """SSA-14: Unseeded (seed=0) batch SSA must not hardcode a fixed seed."""
    src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> B() 1.0
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    # CPU direct batch API with base_seed=0
    c1 = cpp.simulate_batch_ssa_cpu(
        model, net, batch_size=64, t_end=1.0, n_steps=4, base_seed=0, threads=2
    )
    c2 = cpp.simulate_batch_ssa_cpu(
        model, net, batch_size=64, t_end=1.0, n_steps=4, base_seed=0, threads=2
    )
    assert not np.array_equal(c1["final_species"], c2["final_species"])

    # simulate_ssa batch mode with seed=0
    s1 = cpp.simulate_ssa(
        model,
        net,
        t_end=1.0,
        n_steps=4,
        seed=0,
        batch_size=64,
        batch_gpu_preferred=False,
    )
    s2 = cpp.simulate_ssa(
        model,
        net,
        t_end=1.0,
        n_steps=4,
        seed=0,
        batch_size=64,
        batch_gpu_preferred=False,
    )
    assert not np.array_equal(s1["observables"]["Atot"], s2["observables"]["Atot"])

    backend = _usable_gpu_backend()
    if backend is not None:
        g1 = cpp.simulate_batch_ssa_gpu(
            model,
            net,
            batch_size=64,
            t_end=1.0,
            n_steps=4,
            base_seed=0,
            backend=backend,
        )
        g2 = cpp.simulate_batch_ssa_gpu(
            model,
            net,
            batch_size=64,
            t_end=1.0,
            n_steps=4,
            base_seed=0,
            backend=backend,
        )
        assert not np.array_equal(g1["final_species"], g2["final_species"])


def test_gpu_batch_ssa_fast_timescale_offset_clock_and_stiff_fallback():
    """SSA-09 & SSA-10: GPU fast timescale, t_start=1000 offset clock, and stiff fallback."""
    backend = _usable_gpu_backend()
    if backend is None:
        import bionetgen

        caps = bionetgen.gpu_backend_capabilities()
        assert all(not entry.get("available") for entry in caps)
        return

    # SSA-09: Fast timescale t_end=1e-6 (buggy 1e-6f tolerance returned flat 100.0)
    fast_src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 2e6
end reaction rules
end model
"""
    mf = cpp.parse_string(fast_src)
    nf = cpp.generate_network(mf)
    gf = cpp.simulate_batch_ssa_gpu(
        mf, nf, batch_size=512, t_end=1e-6, n_steps=5, base_seed=123, backend=backend
    )
    a_means = np.asarray(gf["observable_means"]["Atot"], dtype=float)
    exact_end = 100.0 * math.exp(-2.0)  # 13.5335
    assert (
        abs(a_means[-1] - exact_end) < 2.0
    ), f"Expected ~{exact_end:.2f}, got {a_means}"
    assert a_means[1] < 80.0  # must decay, not stay flat at 100

    # SSA-10 #1: t_start=1000.0, t_end=1000.01 (relative GPU clock eliminates float32 stall)
    offset_src = """begin model
begin parameters
  k 100.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1000
  B() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> B() k
  B() -> A() k
end reaction rules
end model
"""
    mo = cpp.parse_string(offset_src)
    no = cpp.generate_network(mo)
    go = cpp.simulate_batch_ssa_gpu(
        mo,
        no,
        batch_size=256,
        t_start=1000.0,
        t_end=1000.01,
        n_steps=2,
        base_seed=42,
        max_sim_steps=50000,
        backend=backend,
    )
    exact_offset = 500.0 + 500.0 * math.exp(-2.0)  # 567.67 (buggy Metal gave 501.4)
    got_offset = float(go["observable_means"]["Atot"][-1])
    assert (
        abs(got_offset - exact_offset) < 10.0
    ), f"Expected ~{exact_offset:.2f} at t=1000.01, got {got_offset:.2f}"

    # SSA-10 #2: Propensity dynamic range > 1e5 must fail closed on GPU backend
    stiff_src = """begin model
begin parameters
  kf 2e4
  ks 3.0
end parameters
begin molecule types
  A()
  B()
  D()
end molecule types
begin seed species
  A() 2500
  B() 2500
  D() 0
end seed species
begin observables
  Molecules Dtot D()
end observables
begin reaction rules
  A() -> B() kf
  B() -> A() kf
  0 -> D() ks
end reaction rules
end model
"""
    ms = cpp.parse_string(stiff_src)
    ns = cpp.generate_network(ms)
    with pytest.raises(RuntimeError, match="float32|dynamic range"):
        cpp.simulate_batch_ssa_gpu(
            ms, ns, batch_size=64, t_end=0.002, n_steps=2, base_seed=1, backend=backend
        )


# ---------------------------------------------------------------------------
# HybridModelGenerator test (SSA-11)
# ---------------------------------------------------------------------------


def test_hybrid_model_generator_unbound_observable_does_not_match_bound_dimer(
    tmp_path: Path,
):
    """SSA-11: Molecules A_free A(b) must NOT add bound dimer population P_A2()."""
    src = """begin model
begin parameters
  k_on 0.01
  k_map 1000
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 100
end seed species
begin observables
  Molecules A_free A(b)
  Molecules A_all A()
end observables
begin reaction rules
  A(b) + A(b) -> A(b!1).A(b!1) k_on
end reaction rules
begin population maps
  A(b!1).A(b!1) -> P_A2() k_map
end population maps
end model
begin actions
  generate_hybrid_model({suffix=>"hpp", overwrite=>1})
end actions
"""
    bngl_path = tmp_path / "hyb_free.bngl"
    bngl_path.write_text(src)
    model = cpp.parse_file(str(bngl_path))
    cpp.execute(model, str(bngl_path), verbose=False)

    hybrid_path = tmp_path / "hyb_free_hpp.bngl"
    assert hybrid_path.exists()
    hybrid_text = hybrid_path.read_text()
    obs_lines = {
        line.split()[1]: line.strip()
        for line in hybrid_text.splitlines()
        if line.strip().startswith("Molecules ")
    }
    assert "A_free" in obs_lines
    assert (
        "P_A2" not in obs_lines["A_free"]
    ), f"A_free must not count bound dimer P_A2: {obs_lines['A_free']}"
    assert "P_A2" in obs_lines["A_all"]


# ---------------------------------------------------------------------------
# Bindings & JAX ODE export tests (SSA-15, B14, B16)
# ---------------------------------------------------------------------------


def test_psa_and_pla_bindings_seed_sample_times_and_check_product_scale():
    """SSA-15: bind_engine.cpp simulate_psa and simulate_pla honor seed & sample_times."""
    src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 50
  B() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> B() 0.5
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    # Seed reproducibility for PSA and PLA
    psa1 = cpp.simulate_psa(model, net, t_end=2.0, n_steps=5, poplevel=10.0, seed=42)
    psa2 = cpp.simulate_psa(model, net, t_end=2.0, n_steps=5, poplevel=10.0, seed=42)
    np.testing.assert_array_equal(
        psa1["observables"]["Atot"], psa2["observables"]["Atot"]
    )

    pla1 = cpp.simulate_pla(model, net, t_end=2.0, n_steps=5, seed=42)
    pla2 = cpp.simulate_pla(model, net, t_end=2.0, n_steps=5, seed=42)
    np.testing.assert_array_equal(
        pla1["observables"]["Atot"], pla2["observables"]["Atot"]
    )

    # Custom sample_times for PSA and PLA
    st = [0.0, 0.3, 1.5]
    psa_st = cpp.simulate_psa(
        model, net, t_end=2.0, n_steps=100, poplevel=10.0, seed=7, sample_times=st
    )
    pla_st = cpp.simulate_pla(
        model, net, t_end=2.0, n_steps=100, seed=7, sample_times=st
    )
    np.testing.assert_allclose(psa_st["time"], st)
    np.testing.assert_allclose(pla_st["time"], st)
    assert len(psa_st["observables"]["Atot"]) == 3
    assert len(pla_st["observables"]["Atot"]) == 3


def test_jax_ode_flatten_volume_scales_and_fail_closed_guards():
    """B14 & B16: jax_ode_flatten exports volume_scales and rejects delays & algebraic rules."""
    # B14: compartment volume scaling preserved in jax_ode_flatten
    comp_src = """begin model
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
begin reaction rules
  @c:A() + @c:B() -> @c:C() k
  @c:A() + @c:B() -> @c:C() k TotalRate
end reaction rules
end model
"""
    mc = cpp.parse_string(comp_src)
    nc = cpp.generate_network(mc)
    flat = cpp.jax_ode_flatten(mc, nc)
    assert "volume_scales" in flat
    assert "effective_stat_factors" in flat
    np.testing.assert_allclose(flat["volume_scales"], [0.1, 1.0], rtol=1e-12)
    np.testing.assert_allclose(flat["effective_stat_factors"], [0.1, 1.0], rtol=1e-12)
    np.testing.assert_allclose(flat["rate_constants"], [0.1, 1.0], rtol=1e-12)

    # B16 #1: delayed reactions fail closed
    delay_src = """begin model
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
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    md = cpp.parse_string(delay_src)
    nd = cpp.generate_network(md)
    with pytest.raises(RuntimeError, match="Delayed|delay"):
        cpp.jax_ode_flatten(md, nd)

    # B16 #2: SBML algebraic rules (residual function marker or explicit arg) fail closed
    alg_src = """begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 10
  Z() 20
end seed species
begin observables
  Molecules X_obs X()
  Molecules Z_obs Z()
end observables
begin functions
  __algebraic_residual_0() = Z_obs - 2 * X_obs
end functions
begin reaction rules
  0 -> X() 1.0
end reaction rules
end model
"""
    ma = cpp.parse_string(alg_src)
    na = cpp.generate_network(ma)
    with pytest.raises(RuntimeError, match="algebraic"):
        cpp.jax_ode_flatten(ma, na)

    plain_src = """begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 10
  Z() 20
end seed species
begin reaction rules
  0 -> X() 1.0
end reaction rules
end model
"""
    mp = cpp.parse_string(plain_src)
    np_net = cpp.generate_network(mp)
    with pytest.raises(RuntimeError, match="algebraic"):
        cpp.jax_ode_flatten(mp, np_net, algebraic_rules=[("Z", "Z - 2*X")])
