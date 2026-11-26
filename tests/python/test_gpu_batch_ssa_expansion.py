"""Focused tests for expanded finite batch SSA GPU (TotalRate, functional VM, fail-closed)."""

from __future__ import annotations

import math
import numpy as np
import pytest
from scipy import stats

import bionetgen
from bionetgen import _bionetgen_cpp as cpp


def _usable_finite_gpu_backend() -> str | None:
    backend = cpp.default_gpu_backend()
    return backend if backend in {"metal", "cuda"} else None


def _assert_statistical_parity(cpu_res: dict, gpu_res: dict, z_limit: float = 4.0) -> None:
    obs_names = cpu_res["observable_names"]
    assert gpu_res["observable_names"] == obs_names
    batch_cpu = cpu_res["batch_size"]
    batch_gpu = gpu_res["batch_size"]

    for idx, name in enumerate(obs_names):
        c_mean = np.asarray(cpu_res["observable_means"][name], dtype=float)
        g_mean = np.asarray(gpu_res["observable_means"][name], dtype=float)
        c_std = np.asarray(cpu_res["observable_stds"][name], dtype=float)
        g_std = np.asarray(gpu_res["observable_stds"][name], dtype=float)

        se = np.sqrt((c_std**2) / batch_cpu + (g_std**2) / batch_gpu)
        mask = se > 1e-6
        if np.any(mask):
            z_scores = np.abs(g_mean[mask] - c_mean[mask]) / se[mask]
            assert float(np.max(z_scores)) < z_limit, (
                f"{name}: max |Z| = {float(np.max(z_scores)):.2f} >= {z_limit}"
            )
        if np.any(~mask):
            np.testing.assert_allclose(g_mean[~mask], c_mean[~mask], atol=1e-4)

        c_final = np.asarray(cpu_res["final_observables"], dtype=float)[:, idx]
        g_final = np.asarray(gpu_res["final_observables"], dtype=float)[:, idx]
        if float(np.std(c_final)) > 1e-6 or float(np.std(g_final)) > 1e-6:
            ks = stats.ks_2samp(c_final, g_final)
            assert ks.pvalue > 1e-3, (
                f"{name}: two-sample KS failed (stat={ks.statistic:.4f}, p={ks.pvalue:.4g})"
            )


def test_gpu_batch_ssa_authored_totalrate_parity():
    source = """begin model
begin parameters
  k_fwd 0.02
  k_rev 0.15
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 25
  B(a) 25
end seed species
begin observables
  Molecules A_free A(b)
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  bind: A(b) + B(a) -> A(b!1).B(a!1) k_fwd TotalRate
  unbind: A(b!1).B(a!1) -> A(b) + B(a) k_rev
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    cpu_res = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=2000, t_end=3.0, n_steps=6, base_seed=5101, threads=4
    )
    cpu_single = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=2000, t_end=3.0, n_steps=6, base_seed=5101, threads=1
    )
    np.testing.assert_array_equal(cpu_res["event_counts"], cpu_single["event_counts"])
    np.testing.assert_array_equal(cpu_res["final_species"], cpu_single["final_species"])

    backend = _usable_finite_gpu_backend()
    if backend is None:
        return
    gpu_res = cpp.simulate_batch_ssa_gpu(
        model, network, batch_size=2000, t_end=3.0, n_steps=6, base_seed=5101, backend=backend
    )
    assert gpu_res["backend"] == backend
    np.testing.assert_allclose(
        np.asarray(gpu_res["observable_means"]["A_free"])
        + np.asarray(gpu_res["observable_means"]["AB"]),
        25.0,
        atol=1e-4,
    )
    _assert_statistical_parity(cpu_res, gpu_res)


def test_gpu_batch_ssa_absolute_flux_totalrate_availability_and_analytic_poisson():
    # Case 1: A + A -> B with A(0) = 1 under BNG3AbsoluteFluxRules must never fire.
    unavail_src = """setOption("BNG3AbsoluteFluxRules", "dimer")
begin model
begin parameters
  k 10.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
  B() 0
end seed species
begin observables
  Molecules B_cnt B()
end observables
begin reaction rules
  dimer: A() + A() -> B() k TotalRate
end reaction rules
end model
"""
    # Case 2: constant zero-count source under BNG3AbsoluteFluxRules (analytic Poisson).
    imm_src = """setOption("BNG3AbsoluteFluxRules", "imm")
begin model
begin parameters
  Alpha 8.0
  Mu 0.25
end parameters
begin molecule types
  Source()
  X()
  Sink()
end molecule types
begin seed species
  $Source() 0
  X() 0
  $Sink() 0
end seed species
begin observables
  Molecules X_cnt X()
end observables
begin reaction rules
  imm: Source() -> X() Alpha TotalRate
  death: X() -> Sink() Mu
end reaction rules
end model
"""
    backend = _usable_finite_gpu_backend()
    if backend is None:
        return

    m1 = cpp.parse_string(unavail_src)
    n1 = cpp.generate_network(m1)
    g1 = cpp.simulate_batch_ssa_gpu(
        m1, n1, batch_size=256, t_end=5.0, n_steps=5, base_seed=5201, backend=backend
    )
    assert g1["total_events"] == 0
    np.testing.assert_array_equal(g1["observable_means"]["B_cnt"], np.zeros(6))

    m2 = cpp.parse_string(imm_src)
    n2 = cpp.generate_network(m2)
    batch = 3000
    g2 = cpp.simulate_batch_ssa_gpu(
        m2, n2, batch_size=batch, t_end=4.0, n_steps=4, base_seed=5202, backend=backend
    )
    c2 = cpp.simulate_batch_ssa_cpu(
        m2, n2, batch_size=batch, t_end=4.0, n_steps=4, base_seed=5202, threads=4
    )
    expected_final = (8.0 / 0.25) * (1.0 - math.exp(-0.25 * 4.0))
    gpu_final_mean = float(g2["observable_means"]["X_cnt"][-1])
    assert abs(gpu_final_mean - expected_final) < 4.5 * math.sqrt(expected_final / batch)
    _assert_statistical_parity(c2, g2)


def test_gpu_batch_ssa_observable_functional_mm_and_hill_parity():
    source = """begin model
begin parameters
  Vmax 12.0
  Km 15.0
  Kh 10.0
  nHill 2.0
  k_deg 0.05
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 40
  P() 0
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin functions
  mm_per_mol() = Vmax / (Km + S_obs)
  hill_back() = if(P_obs > 0, 0.2 * (P_obs^nHill) / (Kh^nHill + P_obs^nHill), 0)
end functions
begin reaction rules
  r_mm: S() -> P() mm_per_mol()
  r_hill: P() -> S() hill_back()
  r_deg: P() -> 0 k_deg
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    cpu_multi = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=2000, t_end=5.0, n_steps=5, base_seed=5301, threads=4
    )
    cpu_single = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=2000, t_end=5.0, n_steps=5, base_seed=5301, threads=1
    )
    np.testing.assert_array_equal(cpu_multi["event_counts"], cpu_single["event_counts"])
    np.testing.assert_array_equal(cpu_multi["final_species"], cpu_single["final_species"])

    backend = _usable_finite_gpu_backend()
    if backend is None:
        return
    gpu_res = cpp.simulate_batch_ssa_gpu(
        model, network, batch_size=2000, t_end=5.0, n_steps=5, base_seed=5301, backend=backend
    )
    assert gpu_res["backend"] == backend
    _assert_statistical_parity(cpu_multi, gpu_res)


def test_gpu_batch_ssa_sat_and_hill_special_rate_laws_parity():
    source = """begin model
begin parameters
  kcat 6.0
  Km 10.0
  Vmax 4.0
  Kh 8.0
  n 2
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 30
  P() 5
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  r_sat: S() -> P() Sat(kcat, Km)
  r_hill: P() -> S() Hill(Vmax, Kh, n)
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    backend = _usable_finite_gpu_backend()
    if backend is None:
        return

    cpu_res = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=2000, t_end=4.0, n_steps=4, base_seed=5401, threads=4
    )
    gpu_res = cpp.simulate_batch_ssa_gpu(
        model, network, batch_size=2000, t_end=4.0, n_steps=4, base_seed=5401, backend=backend
    )
    np.testing.assert_allclose(
        np.asarray(gpu_res["observable_means"]["S_obs"])
        + np.asarray(gpu_res["observable_means"]["P_obs"]),
        35.0,
        atol=1e-4,
    )
    _assert_statistical_parity(cpu_res, gpu_res)


def test_gpu_batch_ssa_fails_closed_on_time_delay_events_and_invalid_runtime_rate():
    backend = _usable_finite_gpu_backend()

    time_src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin functions
  f() = 1.0 + time()
end functions
begin reaction rules
  A() -> B() f()
end reaction rules
end model
"""
    m_time = cpp.parse_string(time_src)
    n_time = cpp.generate_network(m_time)
    with pytest.raises(RuntimeError, match="time-dependent|time|unsupported"):
        cpp.simulate_batch_ssa_gpu(
            m_time, n_time, batch_size=8, t_end=1.0, n_steps=2, backend=backend or "metal"
        )

    delay_src = """begin model
begin parameters
  tau 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() 1.0 delay=tau
end reaction rules
end model
"""
    m_delay = cpp.parse_string(delay_src)
    n_delay = cpp.generate_network(m_delay)
    with pytest.raises(RuntimeError, match="Delayed|delay"):
        cpp.simulate_batch_ssa_gpu(
            m_delay, n_delay, batch_size=8, t_end=2.0, n_steps=2, backend=backend or "metal"
        )

    if backend is not None:
        divzero_src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
  B() 0
end seed species
begin observables
  Molecules B_obs B()
end observables
begin functions
  bad_rate() = 1.0 / B_obs
end functions
begin reaction rules
  A() -> B() bad_rate()
end reaction rules
end model
"""
        m_div = cpp.parse_string(divzero_src)
        n_div = cpp.generate_network(m_div)
        with pytest.raises(RuntimeError, match="invalid/non-finite functional rate"):
            cpp.simulate_batch_ssa_gpu(
                m_div, n_div, batch_size=8, t_end=1.0, n_steps=2, backend=backend
            )
