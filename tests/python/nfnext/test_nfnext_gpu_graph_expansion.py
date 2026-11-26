"""Focused tests for NFnext GPU mode='graph' expansion (TotalRate, filters, energy Arrhenius)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

import bionetgen


def _usable_gpu_backend() -> str | None:
    for entry in bionetgen.gpu_backend_capabilities():
        if entry.get("available") and "nfnext_graph_corpus" in entry.get(
            "implemented_routes", []
        ):
            return str(entry["name"])
    return None


def _run_nfnext_cpu_ensemble(
    model, times: list[float], n_runs: int, seed_base: int
) -> dict[str, np.ndarray]:
    samples: dict[str, list[np.ndarray]] = {}
    for run in range(n_runs):
        res = model.simulate(
            method="nfnext",
            t_end=times[-1],
            sample_times=times,
            seed=seed_base + run + 1,
        )
        for name, values in res.observables.items():
            samples.setdefault(name, []).append(np.asarray(values, dtype=float))
    return {name: np.vstack(rows) for name, rows in samples.items()}


def _assert_ensemble_parity(
    cpu_samples: dict[str, np.ndarray],
    gpu_res,
    names: tuple[str, ...],
    z_limit: float = 4.0,
) -> None:
    for name in names:
        c = cpu_samples[name]
        g = np.asarray(gpu_res.observables[name], dtype=float)
        c_mean = np.mean(c, axis=0)
        g_mean = np.mean(g, axis=0)
        c_std = np.std(c, axis=0)
        g_std = np.std(g, axis=0)
        se = np.sqrt((c_std**2) / c.shape[0] + (g_std**2) / g.shape[0])
        mask = se > 1e-6
        if np.any(mask):
            z = np.abs(g_mean[mask] - c_mean[mask]) / se[mask]
            assert float(np.max(z)) < z_limit, f"{name}: max |Z|={float(np.max(z)):.2f}"
        if np.any(~mask):
            np.testing.assert_allclose(g_mean[~mask], c_mean[~mask], atol=1e-4)
        if float(np.std(c[:, -1])) > 1e-6 or float(np.std(g[:, -1])) > 1e-6:
            ks = stats.ks_2samp(c[:, -1], g[:, -1])
            assert ks.pvalue > 1e-3, f"{name}: KS p={ks.pvalue:.4g}"


def test_nfnext_gpu_graph_totalrate_parity(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin parameters
  k_prod 6.0
  k_decay 0.25
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20
  B() 0
end seed species
begin observables
  Molecules A_cnt A()
  Molecules B_cnt B()
end observables
begin reaction rules
  R_tr: A() -> A() + B() k_prod TotalRate
  R_dec: B() -> 0 k_decay
end reaction rules
end model
"""
    path = tmp_path / "nfnext_totalrate.bngl"
    path.write_text(src, encoding="utf-8")
    model = bionetgen.load(str(path))
    times = [0.0, 1.0, 2.0, 4.0]
    gpu = model.simulate_nfnext_gpu(
        times, seed=7101, batch_size=1024, backend=backend, mode="graph"
    )
    # With TotalRate on A() -> A() + B(), propensity is constant k_prod=6.0 (not 6*20=120),
    # so B(t) ~ Poisson((k_prod/k_decay) * (1 - exp(-k_decay * t))).
    expected_final = (6.0 / 0.25) * (1.0 - math.exp(-0.25 * 4.0))
    gpu_mean = float(np.mean(gpu.observables["B_cnt"][:, -1]))
    assert abs(gpu_mean - expected_final) < 4.0 * math.sqrt(expected_final / 1024.0)
    assert np.all(gpu.observables["A_cnt"] == 20.0)

    cpu = _run_nfnext_cpu_ensemble(model, times, n_runs=256, seed_base=7101)
    _assert_ensemble_parity(cpu, gpu, ("A_cnt", "B_cnt"))


def test_nfnext_gpu_graph_include_and_exclude_reactant_filters_parity(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin parameters
  k_bind 0.05
  k_unbind 0.4
  k_phos 2.0
  k_dephos 1.5
end parameters
begin molecule types
  A(b,p~u~p)
  B(a)
end molecule types
begin seed species
  A(b,p~u) 15
  B(a) 10
end seed species
begin observables
  Molecules Ap A(p~p)
  Molecules AB A(b!1).B(a!1)
  Molecules Atot A()
end observables
begin reaction rules
  bind: A(b) + B(a) <-> A(b!1).B(a!1) k_bind, k_unbind
  phos_only_with_B: A(p~u) -> A(p~p) k_phos include_reactants(1, B())
  dephos_only_without_B: A(p~p) -> A(p~u) k_dephos exclude_reactants(1, B())
end reaction rules
end model
"""
    path = tmp_path / "nfnext_filters.bngl"
    path.write_text(src, encoding="utf-8")
    model = bionetgen.load(str(path))
    times = [0.0, 0.5, 1.5, 3.0]
    gpu = model.simulate_nfnext_gpu(
        times, seed=7201, batch_size=1024, backend=backend, mode="graph"
    )
    assert np.all(gpu.observables["Atot"] == 15.0)
    assert int(np.sum(gpu.event_counts)) > 0

    cpu = _run_nfnext_cpu_ensemble(model, times, n_runs=256, seed_base=7201)
    _assert_ensemble_parity(cpu, gpu, ("Ap", "AB", "Atot"))


def test_nfnext_gpu_graph_energy_folded_arrhenius_parity(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin parameters
  gf_p -1.2
  phi 0.5
  Ea 0.4
end parameters
begin molecule types
  A(s~u~p)
end molecule types
begin seed species
  A(s~u) 40
end seed species
begin observables
  Molecules Au A(s~u)
  Molecules Ap A(s~p)
end observables
begin energy patterns
  A(s~p) gf_p
end energy patterns
begin reaction rules
  flip: A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    path = tmp_path / "nfnext_energy.bngl"
    path.write_text(src, encoding="utf-8")
    model = bionetgen.load(str(path))
    times = [0.0, 0.5, 2.0, 6.0]
    gpu = model.simulate_nfnext_gpu(
        times, seed=7301, batch_size=1024, backend=backend, mode="graph"
    )
    assert np.all(gpu.observables["Au"] + gpu.observables["Ap"] == 40.0)
    # Exact Boltzmann equilibrium: P(s~p) = 1 / (1 + exp(gf_p))
    p_eq = 1.0 / (1.0 + math.exp(-1.2))
    expected_ap = 40.0 * p_eq
    se_ap = math.sqrt(40.0 * p_eq * (1.0 - p_eq) / 1024.0)
    assert abs(float(np.mean(gpu.observables["Ap"][:, -1])) - expected_ap) < 4.0 * se_ap

    cpu = _run_nfnext_cpu_ensemble(model, times, n_runs=256, seed_base=7301)
    _assert_ensemble_parity(cpu, gpu, ("Au", "Ap"))


def test_nfnext_gpu_graph_refuses_product_filters_and_totalrate_with_filter(
    tmp_path: Path,
):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    prod_filter = """begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 5
  B(a) 5
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 1.0 exclude_products(1, B())
end reaction rules
end model
"""
    p1 = tmp_path / "prod_filter.bngl"
    p1.write_text(prod_filter, encoding="utf-8")
    with pytest.raises(RuntimeError, match="product include/exclude filters"):
        bionetgen.load(str(p1)).simulate_nfnext_gpu(
            [0.0, 1.0], seed=1, batch_size=4, backend=backend, mode="graph"
        )

    tr_filter = """begin model
begin molecule types
  A(p~u~p)
  B()
end molecule types
begin seed species
  A(p~u) 5
end seed species
begin observables
  Molecules Ap A(p~p)
end observables
begin reaction rules
  A(p~u) -> A(p~p) 1.0 TotalRate exclude_reactants(1, B())
end reaction rules
end model
"""
    p2 = tmp_path / "tr_filter.bngl"
    p2.write_text(tr_filter, encoding="utf-8")
    with pytest.raises(
        RuntimeError, match="TotalRate combined with include/exclude filters"
    ):
        bionetgen.load(str(p2)).simulate_nfnext_gpu(
            [0.0, 1.0], seed=1, batch_size=4, backend=backend, mode="graph"
        )
