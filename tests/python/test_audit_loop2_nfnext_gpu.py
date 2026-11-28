"""Regression tests for Loop 2 audit fixes in NFnext CPU and GPU graph backends.

Covers:
- GPU Graph Kernel: L2-06-01 through L2-06-10
- CPU NFnext: L2-06-11 through L2-06-16, L2-01-03, L2-01-15, L2-08-02, L2-08-04
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp


def _usable_gpu_backend() -> str | None:
    for entry in bionetgen.gpu_backend_capabilities():
        if entry.get("available") and "nfnext_graph_corpus" in entry.get(
            "implemented_routes", []
        ):
            return str(entry["name"])
    return None


def _run_nfnext_cpu_ensemble(
    source: str,
    obs_names: list[str],
    t_end: float,
    n_runs: int = 32,
    seed_base: int = 4000,
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
        method="ode", t_start=0.0, t_end=t_end, n_steps=40, rtol=1e-9, atol=1e-12
    )
    return {name: float(res.observables[name][-1]) for name in obs_names}


def _load_model(tmp_path: Path, name: str, source: str):
    path = tmp_path / f"{name}.bngl"
    path.write_text(source, encoding="utf-8")
    return bionetgen.load(str(path))


def _assert_close(
    mean: float, se: float, expected: float, z_max: float = 4.5, min_tol: float = 1.0
):
    tol = max(z_max * se, min_tol)
    assert (
        abs(mean - expected) <= tol
    ), f"mean={mean:.3f} +/- {se:.3f} deviates from expected={expected:.3f} (tol={tol:.3f})"


# ---------------------------------------------------------------------------
# GPU Graph Kernel Regressions (L2-06-01 .. L2-06-10)
# ---------------------------------------------------------------------------


def test_l2_06_01_gpu_different_complex_reactant_and_product(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    # 1. Reactant '+' forbids intramolecular ring closure on a single A-B dimer.
    src_reactant = """begin model
begin molecule types
  A(l,r)
  B(l,r)
end molecule types
begin seed species
  A(r!1,l).B(l!1,r) 1
end seed species
begin observables
  Molecules Ring A(l!1,r!2).B(l!2,r!1)
end observables
begin reaction rules
  R_bind: A(l) + B(r) -> A(l!1).B(r!1) 5.0
end reaction rules
end model
"""
    m_react = _load_model(tmp_path, "gpu_diffcomp_react", src_reactant)
    gpu_r = m_react.simulate_nfnext_gpu(
        [0.0, 2.0], seed=8101, batch_size=128, backend=backend, mode="graph"
    )
    assert np.all(gpu_r.observables["Ring"] == 0.0)

    # 2. Product '+' forbids ring opening on 2-rings A(l!1,r!2).A(l!2,r!1).
    src_product = """begin model
begin molecule types
  A(l,r)
end molecule types
begin seed species
  A(l!1,r!2).A(l!2,r!1) 30
end seed species
begin observables
  Molecules Rings A(l!1,r!2).A(l!2,r!1)
  Molecules FreeL A(l)
end observables
begin reaction rules
  R_unbind: A(l!1).A(r!1) -> A(l) + A(r) 5.0
end reaction rules
end model
"""
    m_prod = _load_model(tmp_path, "gpu_diffcomp_prod", src_product)
    gpu_p = m_prod.simulate_nfnext_gpu(
        [0.0, 2.0], seed=8102, batch_size=128, backend=backend, mode="graph"
    )
    assert np.all(gpu_p.observables["Rings"] == 60.0)
    assert np.all(gpu_p.observables["FreeL"] == 0.0)

    # 3. Intermolecular chains with reactant '+' match CPU NFnext ensemble.
    src_chain = """begin model
begin molecule types
  A(l,r)
  B(l,r)
end molecule types
begin seed species
  A(r!1,l).B(l!1,r) 12
end seed species
begin observables
  Molecules FreeL A(l)
  Molecules Ring2 A(l!1,r!2).B(l!2,r!1)
end observables
begin reaction rules
  R_bind: A(l) + B(r) -> A(l!1).B(r!1) 0.05
end reaction rules
end model
"""
    m_chain = _load_model(tmp_path, "gpu_diffcomp_chain", src_chain)
    gpu_c = m_chain.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8103, batch_size=512, backend=backend, mode="graph"
    )
    assert np.all(gpu_c.observables["Ring2"] == 0.0)
    cpu_c = _run_nfnext_cpu_ensemble(
        src_chain, ["FreeL"], 1.0, n_runs=128, seed_base=8103
    )
    gpu_mean = float(np.mean(gpu_c.observables["FreeL"][:, -1]))
    gpu_se = float(np.std(gpu_c.observables["FreeL"][:, -1], ddof=1) / math.sqrt(512))
    comb_se = math.sqrt(gpu_se**2 + cpu_c["FreeL"][1] ** 2)
    _assert_close(gpu_mean, comb_se, cpu_c["FreeL"][0], z_max=4.5, min_tol=0.3)


def test_l2_06_02_gpu_symmetric_bonded_unbind_and_destroy_complex(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src_unbind = """begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 50
end seed species
begin observables
  Molecules A_free A(b)
end observables
begin reaction rules
  R_u: A(b!1).A(b!1) -> A(b) + A(b) 1.0
end reaction rules
end model
"""
    m_u = _load_model(tmp_path, "gpu_sym_unbind", src_unbind)
    gpu_u = m_u.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8201, batch_size=512, backend=backend, mode="graph"
    )
    expected_free = 100.0 * (1.0 - math.exp(-1.0))
    arr_u = gpu_u.observables["A_free"][:, -1]
    _assert_close(
        float(np.mean(arr_u)),
        float(np.std(arr_u, ddof=1) / math.sqrt(len(arr_u))),
        expected_free,
        z_max=4.5,
        min_tol=0.5,
    )

    src_del = """begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 50
end seed species
begin observables
  Molecules D_mol A(b!1).A(b!1)
end observables
begin reaction rules
  R_d: A(b!1).A(b!1) -> 0 1.0
end reaction rules
end model
"""
    m_d = _load_model(tmp_path, "gpu_sym_del", src_del)
    gpu_d = m_d.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8202, batch_size=512, backend=backend, mode="graph"
    )
    expected_d = 100.0 * math.exp(-1.0)
    arr_d = gpu_d.observables["D_mol"][:, -1]
    _assert_close(
        float(np.mean(arr_d)),
        float(np.std(arr_d, ddof=1) / math.sqrt(len(arr_d))),
        expected_d,
        z_max=4.5,
        min_tol=0.5,
    )


def test_l2_06_03_gpu_duplicate_site_homodimerization_no_self_bonds(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin molecule types
  A(b,b)
end molecule types
begin seed species
  A(b,b) 15
end seed species
begin observables
  Molecules FreeSites A(b)
  Molecules SelfBond A(b!1,b!1)
end observables
begin reaction rules
  R_bind: A(b) + A(b) -> A(b!1).A(b!1) 0.01
end reaction rules
end model
"""
    m = _load_model(tmp_path, "gpu_dup_homodimer", src)
    gpu = m.simulate_nfnext_gpu(
        [0.0, 0.5], seed=8301, batch_size=512, backend=backend, mode="graph"
    )
    assert np.all(gpu.observables["SelfBond"] == 0.0)
    cpu = _run_nfnext_cpu_ensemble(src, ["FreeSites"], 0.5, n_runs=128, seed_base=8301)
    gpu_vals = gpu.observables["FreeSites"][:, -1]
    comb_se = math.sqrt(
        (float(np.std(gpu_vals, ddof=1)) ** 2) / len(gpu_vals)
        + cpu["FreeSites"][1] ** 2
    )
    _assert_close(
        float(np.mean(gpu_vals)), comb_se, cpu["FreeSites"][0], z_max=4.5, min_tol=0.4
    )


def test_l2_06_04_gpu_two_hop_anchor_refresh_on_delete(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin molecule types
  A(b)
  B(a,c)
  C(b,s~0~1)
end molecule types
begin seed species
  A(b!1).B(a!1,c!2).C(b!2,s~0) 40
end seed species
begin observables
  Molecules C_s1 C(s~1)
end observables
begin reaction rules
  R_del: A() -> 0 2.0 DeleteMolecules
  R_act: C(b!1,s~0).B(c!1,a) -> C(b!1,s~1).B(c!1,a) 5.0
end reaction rules
end model
"""
    m = _load_model(tmp_path, "gpu_twohop_del", src)
    gpu = m.simulate_nfnext_gpu(
        [0.0, 2.0], seed=8401, batch_size=512, backend=backend, mode="graph"
    )
    # Exact two-stage cascade A-B-C -> B-C (k1=2) -> B-C* (k2=5):
    k1, k2, t = 2.0, 5.0, 2.0
    p_s1 = 1.0 - (k2 * math.exp(-k1 * t) - k1 * math.exp(-k2 * t)) / (k2 - k1)
    expected = 40.0 * p_s1
    arr = gpu.observables["C_s1"][:, -1]
    _assert_close(
        float(np.mean(arr)),
        float(np.std(arr, ddof=1) / math.sqrt(len(arr))),
        expected,
        z_max=4.5,
        min_tol=0.5,
    )


def test_l2_06_05_gpu_runtime_arrhenius_refused(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin parameters
  G_3mol -2.0
  phi 0.5
  Ea 0.0
end parameters
begin molecule types
  A(s~0~1,b)
  B(a,c)
  C(b)
end molecule types
begin seed species
  A(s~0,b!1).B(a!1,c!2).C(b!2) 20
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1,b!1).B(a!1,c!2).C(b!2) G_3mol
end energy patterns
begin reaction rules
  R1: A(s~0) <-> A(s~1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    m = _load_model(tmp_path, "gpu_runtime_arrh", src)
    with pytest.raises(RuntimeError):
        m.simulate_nfnext_gpu(
            [0.0, 1.0], seed=8501, batch_size=16, backend=backend, mode="graph"
        )


def test_l2_06_06_gpu_local_scope_unbound_refused_and_bound_allowed(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    # 1-copy A with unbound B(): global Bcnt != local Bcnt(x), must refuse on GPU.
    src_bad = """begin model
begin molecule types
  A(s~0~1,b)
  B(a)
end molecule types
begin seed species
  A(s~0,b) 1
  B(a) 5
end seed species
begin observables
  Molecules Bcnt B()
  Molecules A1 A(s~1)
end observables
begin functions
  f(x) = 10.0 * Bcnt(x)
end functions
begin reaction rules
  R1: %x::A(s~0) -> %x::A(s~1) f(x)
end reaction rules
end model
"""
    m_bad = _load_model(tmp_path, "gpu_local_unbound", src_bad)
    with pytest.raises(RuntimeError):
        m_bad.simulate_nfnext_gpu(
            [0.0, 1.0], seed=8601, batch_size=16, backend=backend, mode="graph"
        )

    # 1-copy A where observable explicitly contains A: global == local, allowed on GPU.
    src_ok = """begin model
begin molecule types
  A(s~0~1,b)
  B(a)
end molecule types
begin seed species
  A(s~0,b!1).B(a!1) 1
  B(a) 5
end seed species
begin observables
  Molecules AB_cnt A(b!1).B(a!1)
  Molecules A1 A(s~1)
end observables
begin functions
  f(x) = 2.0 * AB_cnt(x)
end functions
begin reaction rules
  R1: %x::A(s~0) -> %x::A(s~1) f(x)
end reaction rules
end model
"""
    m_ok = _load_model(tmp_path, "gpu_local_bound", src_ok)
    gpu_ok = m_ok.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8602, batch_size=512, backend=backend, mode="graph"
    )
    expected = 1.0 - math.exp(-2.0)
    arr = gpu_ok.observables["A1"][:, -1]
    _assert_close(
        float(np.mean(arr)),
        float(np.std(arr, ddof=1) / math.sqrt(len(arr))),
        expected,
        z_max=4.5,
        min_tol=0.05,
    )


def test_l2_06_07_gpu_dynamic_observables_over_32_safe_and_over_64_refused(
    tmp_path: Path,
):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    def make_model_with_n_obs(n_obs: int) -> str:
        obs_lines = [f"  Molecules O{i} A(s~0)" for i in range(n_obs - 1)]
        obs_lines.append(f"  Molecules O{n_obs - 1} A(s~1)")
        obs_block = "\n".join(obs_lines)
        last = f"O{n_obs - 1}"
        return f"""begin model
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 30
  A(s~1) 10
end seed species
begin observables
{obs_block}
end observables
begin functions
  rate_fn() = 0.02 * ({last} + 1.0)
end functions
begin reaction rules
  R1: A(s~0) -> A(s~1) rate_fn()
end reaction rules
end model
"""

    # 36 observables (>32, <=64): runs safely and matches CPU NFnext!
    src_36 = make_model_with_n_obs(36)
    m_36 = _load_model(tmp_path, "gpu_obs_36", src_36)
    gpu_36 = m_36.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8701, batch_size=256, backend=backend, mode="graph"
    )
    cpu_36 = _run_nfnext_cpu_ensemble(src_36, ["O35"], 1.0, n_runs=96, seed_base=8701)
    arr_36 = gpu_36.observables["O35"][:, -1]
    comb_se = math.sqrt(
        (float(np.std(arr_36, ddof=1)) ** 2) / len(arr_36) + cpu_36["O35"][1] ** 2
    )
    _assert_close(
        float(np.mean(arr_36)), comb_se, cpu_36["O35"][0], z_max=4.5, min_tol=0.6
    )

    # 66 observables (>64) with dynamic rate: cleanly refused (no OOB)!
    src_66 = make_model_with_n_obs(66)
    m_66 = _load_model(tmp_path, "gpu_obs_66", src_66)
    with pytest.raises(RuntimeError):
        m_66.simulate_nfnext_gpu(
            [0.0, 1.0], seed=8702, batch_size=16, backend=backend, mode="graph"
        )


def test_l2_06_08_gpu_species_observable_substructure_and_multiterm(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 10
  B(a) 7
end seed species
begin observables
  Species SpA A()
  Species SpB B()
  Species SpAB A() B()
  Species SpDimer A(b!1).B(a!1)
end observables
begin reaction rules
  R_noop: A(b) -> A(b) 0.0
end reaction rules
end model
"""
    m = _load_model(tmp_path, "gpu_species_obs", src)
    gpu = m.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8801, batch_size=16, backend=backend, mode="graph"
    )
    assert np.all(gpu.observables["SpA"] == 10.0)
    assert np.all(gpu.observables["SpB"] == 17.0)
    assert np.all(gpu.observables["SpAB"] == 27.0)
    assert np.all(gpu.observables["SpDimer"] == 10.0)


def test_l2_06_09_gpu_molecules_automorphism_weights(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src = """begin model
begin molecule types
  A(b,b,p~0~1,p~0~1)
  B(a)
end molecule types
begin seed species
  A(b!1,b,p~1,p~1).A(b!1,b,p~0,p~0) 5
  A(b!1,b!2,p~0,p~0).B(a!1).B(a!2) 4
end seed species
begin observables
  Molecules D A(b!1).A(b!1)
  Molecules Ap2 A(p~1,p~1)
  Molecules Star A(b!1,b!2).B(a!1).B(a!2)
  Molecules Aany A()
end observables
begin reaction rules
  R_noop: B(a) -> B(a) 0.0
end reaction rules
end model
"""
    m = _load_model(tmp_path, "gpu_mol_aut", src)
    gpu = m.simulate_nfnext_gpu(
        [0.0, 1.0], seed=8901, batch_size=16, backend=backend, mode="graph"
    )
    cpu = _run_nfnext_cpu_ensemble(
        src, ["D", "Ap2", "Star", "Aany"], 1.0, n_runs=1, seed_base=8901
    )
    assert np.all(gpu.observables["D"] == 10.0) and cpu["D"][0] == 10.0
    assert np.all(gpu.observables["Ap2"] == 10.0) and cpu["Ap2"][0] == 10.0
    assert np.all(gpu.observables["Star"] == 8.0) and cpu["Star"][0] == 8.0
    assert np.all(gpu.observables["Aany"] == 14.0) and cpu["Aany"][0] == 14.0


def test_l2_06_10_gpu_constant_seed_refused_when_mutated_and_allowed_as_catalyst(
    tmp_path: Path,
):
    backend = _usable_gpu_backend()
    if backend is None:
        return

    src_mut = """begin model
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  $A(s~0) 50
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
end observables
begin reaction rules
  R1: A(s~0) -> A(s~1) 1.0
end reaction rules
end model
"""
    m_mut = _load_model(tmp_path, "gpu_const_mut", src_mut)
    with pytest.raises(RuntimeError):
        m_mut.simulate_nfnext_gpu(
            [0.0, 1.0], seed=9001, batch_size=16, backend=backend, mode="graph"
        )
    with pytest.raises(RuntimeError):
        m_mut.simulate_nfnext_gpu(
            [0.0, 1.0], seed=9002, batch_size=16, backend=backend, mode="unary_state"
        )

    # Pure catalyst $A(s~0) producing distinct non-constant A(s~1) must succeed.
    src_cat = """begin model
begin molecule types
  A(s~0~1)
  B()
end molecule types
begin seed species
  $A(s~0) 20
  B() 10
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
end observables
begin reaction rules
  R1: A(s~0) + B() -> A(s~0) + B() + A(s~1) 0.05
end reaction rules
end model
"""
    m_cat = _load_model(tmp_path, "gpu_const_cat", src_cat)
    gpu_cat = m_cat.simulate_nfnext_gpu(
        [0.0, 1.0], seed=9003, batch_size=256, backend=backend, mode="graph"
    )
    assert np.all(gpu_cat.observables["A0"] == 20.0)
    expected_a1 = 20.0 * 10.0 * 0.05 * 1.0
    arr = gpu_cat.observables["A1"][:, -1]
    _assert_close(
        float(np.mean(arr)),
        float(np.std(arr, ddof=1) / math.sqrt(len(arr))),
        expected_a1,
        z_max=4.5,
        min_tol=0.6,
    )


# ---------------------------------------------------------------------------
# CPU NFnext Regressions (L2-06-11 .. L2-06-16, L2-01-03, L2-01-15, L2-08-02/04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "barrier_line,comp_block,seed_block,rule_block",
    [
        # Context molecule / site bond constraint
        (
            "  B1: A(s~0,b!1).B(a!1) -> A(s~1,b!1).B(a!1) Gbar",
            "",
            "  A(s~0,b) 10\n  A(s~0,b!1).B(a!1) 10",
            "  R1: A(s~0) <-> A(s~1) Arrhenius(phi, Ea)",
        ),
        # Center-site bond constraint !+
        (
            "  B2: A(s~0!+) -> A(s~1!+) Gbar",
            "",
            "  A(s~0,b) 10",
            "  R1: A(s~0) <-> A(s~1) Arrhenius(phi, Ea)",
        ),
        # Compartment constraint on barrier pattern
        (
            "  B3: A(s~0)@PM -> A(s~1)@PM Gbar",
            "begin compartments\n  EC 3 1.0\n  PM 2 1.0 EC\n  CP 3 1.0 PM\nend compartments\n",
            "  A(s~0,b)@PM 10\n  A(s~0,b)@CP 10",
            "  R1: A(s~0)@PM <-> A(s~1)@PM Arrhenius(phi, Ea)\n  R2: A(s~0)@CP <-> A(s~1)@CP Arrhenius(phi, Ea)",
        ),
        # Intramolecular bond barrier
        (
            "  B4: A(s~0,b) -> A(s~0!1,b!1) Gbar",
            "",
            "  A(s~0,b) 10",
            "  R1: A(s~0) + A(b) <-> A(s~0!1).A(b!1) Arrhenius(phi, Ea)",
        ),
    ],
)
def test_l2_06_11_nfnext_conditional_barrier_patterns_refused(
    barrier_line: str, comp_block: str, seed_block: str, rule_block: str
):
    src = f"""begin model
begin parameters
  Gbar 5.0
  phi 0.5
  Ea 0.0
end parameters
{comp_block}begin molecule types
  A(s~0~1,b)
  B(a)
end molecule types
begin seed species
{seed_block}
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin energy patterns
  A(s~1) 0.0
end energy patterns
begin barrier patterns
{barrier_line}
end barrier patterns
begin reaction rules
{rule_block}
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    with pytest.raises(Exception):
        cpp.simulate_nfnext(model, [0.0, 1.0], seed=9101)


def test_l2_06_12_nfnext_mixed_lumped_invariants():
    # 8a: Product molecularity ('+') forbids ring opening in mixed-lumped rules.
    src_8a = """begin model
begin molecule types
  A(l,r)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(l!1,r!2).A(l!2,r!1) 30
  P() 20
end seed species
begin observables
  Molecules Rings A(l!1,r!2).A(l!2,r!1)
  Molecules FreeL A(l)
end observables
begin reaction rules
  R1: A(l!1).A(r!1) + P() -> A(l) + A(r) + P() 0.5
end reaction rules
end model
"""
    m_8a = cpp.parse_string(src_8a)
    r_8a = cpp.simulate_nfnext(m_8a, [0.0, 1.0], seed=9201)
    assert r_8a["observables"]["Rings"][-1] == 60.0
    assert r_8a["observables"]["FreeL"][-1] == 0.0

    # 8b: exclude_products in mixed-lumped rule.
    src_8b = """begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(b) 30
  B(a) 30
  P() 20
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  R1: A(b) + B(a) + P() -> A(b!1).B(a!1) + P() 0.01 exclude_products(1, B())
end reaction rules
end model
"""
    m_8b = cpp.parse_string(src_8b)
    r_8b = cpp.simulate_nfnext(m_8b, [0.0, 1.0], seed=9202)
    assert r_8b["observables"]["AB"][-1] == 0.0

    # 8c: Scoped function in mixed-lumped rule evaluates locally on matched complex.
    src_8c = """begin model
begin molecule types
  A(s~0~1,b)
  B(a)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(s~0,b!1).B(a!1) 40
  A(s~0,b) 40
  P() 10
end seed species
begin observables
  Molecules Bcnt B()
  Molecules A1_bound A(s~1,b!+)
  Molecules A1_free A(s~1,b)
end observables
begin functions
  f(x) = 0.2 * Bcnt(x)
end functions
begin reaction rules
  R1: %x::A(s~0) + P() -> %x::A(s~1) + P() f(x)
end reaction rules
end model
"""
    ens_8c = _run_nfnext_cpu_ensemble(
        src_8c, ["A1_bound", "A1_free"], 0.5, n_runs=48, seed_base=9203
    )
    assert ens_8c["A1_free"][0] == 0.0
    expected_bound = 40.0 * (1.0 - math.exp(-0.2 * 10.0 * 0.5))
    _assert_close(
        ens_8c["A1_bound"][0],
        ens_8c["A1_bound"][1],
        expected_bound,
        z_max=4.5,
        min_tol=1.0,
    )

    # 8d: Homodimer DestroyComplex deduplication in mixed-lumped rule (no 2x rate).
    src_8d = """begin model
begin molecule types
  A(b)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(b!1).A(b!1) 50
  P() 10
end seed species
begin observables
  Molecules D A(b!1).A(b!1)
end observables
begin reaction rules
  R1: A(b!1).A(b!1) + P() -> P() 0.1
end reaction rules
end model
"""
    ens_8d = _run_nfnext_cpu_ensemble(src_8d, ["D"], 1.0, n_runs=64, seed_base=9204)
    expected_d = 100.0 * math.exp(-0.1 * 10.0 * 1.0)
    _assert_close(ens_8d["D"][0], ens_8d["D"][1], expected_d, z_max=4.5, min_tol=1.5)

    # 8e: Compartment adjacency across particle & population reactants separated by 2D PM.
    src_8e = """begin model
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  A(s~0~1)
end molecule types
begin population types
  P()
end population types
begin seed species
  A(s~0)@EC 30
  P()@CP 20
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin reaction rules
  R1: A(s~0) + P()@CP -> A(s~1) + P()@CP 1.0
end reaction rules
end model
"""
    m_8e = cpp.parse_string(src_8e)
    r_8e = cpp.simulate_nfnext(m_8e, [0.0, 1.0], seed=9205)
    assert r_8e["observables"]["A1"][-1] == 0.0


def test_l2_06_13_and_l2_01_03_nfnext_observable_quantifiers():
    src = """begin model
begin molecule types
  A(b)
  B()
end molecule types
begin seed species
  B() 7
  A(b) 5
  A(b!1).A(b!1) 6
end seed species
begin observables
  Molecules M_eq1 A()==1
  Species S_eq0 A()==0
  Species S_lt2 A()<2
  Species S_le1 A()<=1
  Species S_eq1 A()==1
  Species S_gt1 A()>1
end observables
begin reaction rules
  R_noop: B() -> B() 0.0
end reaction rules
end model
"""
    obs = ["M_eq1", "S_eq0", "S_lt2", "S_le1", "S_eq1", "S_gt1"]
    m = cpp.parse_string(src)
    res = cpp.simulate_nfnext(m, [0.0, 0.5], seed=9301)
    ode = _run_ode_final(src, obs, 0.5)
    # Molecules ignores quantifier (5 + 2*6 = 17); Species zero-matchers include B() (7).
    expected = {
        "M_eq1": 17.0,
        "S_eq0": 7.0,
        "S_lt2": 12.0,
        "S_le1": 12.0,
        "S_eq1": 5.0,
        "S_gt1": 6.0,
    }
    for name in obs:
        assert res["observables"][name][-1] == expected[name]
        assert abs(ode[name] - expected[name]) < 1e-6


def test_l2_06_14_nfnext_match_once_unbiased_selection():
    src = """begin model
begin molecule types
  A(s~0~1,t~0~1,b)
end molecule types
begin seed species
  A(s~0,t~0,b!1).A(s~0,t~1,b!1) 100
end seed species
begin observables
  Molecules Modified_t0 A(s~1,t~0)
  Molecules Modified_t1 A(s~1,t~1)
end observables
begin reaction rules
  {MatchOnce}A(s~0) -> A(s~1) 0.5
end reaction rules
end model
"""
    ens = _run_nfnext_cpu_ensemble(
        src, ["Modified_t0", "Modified_t1"], 0.4, n_runs=64, seed_base=9401
    )
    m0, se0 = ens["Modified_t0"]
    m1, se1 = ens["Modified_t1"]
    # Both t~0 and t~1 must receive ~50% of events (previously 100% / 0%).
    assert m0 > 5.0 and m1 > 5.0
    diff_se = math.sqrt(se0**2 + se1**2)
    assert abs(m0 - m1) < max(
        4.5 * diff_se, 2.0
    ), f"biased MatchOnce: t0={m0:.2f}, t1={m1:.2f}"


def test_l2_06_15_nfnext_totalrate_with_scoped_function_refused():
    src = """begin model
begin molecule types
  A(s~0~1,c)
  C(a)
end molecule types
begin seed species
  A(s~0,c!1).C(a!1) 20
  A(s~0,c) 20
end seed species
begin observables
  Molecules Ccnt C()
  Molecules A1 A(s~1)
end observables
begin functions
  f(x) = 10.0 * Ccnt(x)
end functions
begin reaction rules
  %x::A(s~0) -> %x::A(s~1) f(x) TotalRate
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    with pytest.raises(Exception):
        cpp.simulate_nfnext(model, [0.0, 1.0], seed=9501)


def test_l2_06_16_nfnext_3d_transport_without_moveconnected():
    # Molecule-level A()@EC -> A()@CP WITHOUT MoveConnected must NOT auto-move bound cargo B@EC,
    # while still transporting unbound A(b)@EC.
    src_no_mc = """begin model
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  @EC:A(b!1).B(a!1) 50
  @EC:A(b) 50
end seed species
begin observables
  Molecules A_free_CP A(b)@CP
  Molecules B_CP B()@CP
  Molecules B_EC B()@EC
end observables
begin reaction rules
  A()@EC -> A()@CP 2.0
end reaction rules
end model
"""
    m_no = cpp.parse_string(src_no_mc)
    r_no = cpp.simulate_nfnext(m_no, [0.0, 1.0], seed=9601)
    assert r_no["observables"]["B_CP"][-1] == 0.0
    assert r_no["observables"]["B_EC"][-1] == 50.0
    assert r_no["observables"]["A_free_CP"][-1] > 30.0

    # Species-level @EC:A() -> @CP:A() AND MoveConnected BOTH move connected cargo B@EC -> B@CP.
    for tag, rule_line in [
        ("prefix", "@EC:A() -> @CP:A() 2.0"),
        ("moveconn", "A()@EC -> A()@CP 2.0 MoveConnected"),
    ]:
        src_yes = f"""begin model
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  @EC:A(b!1).B(a!1) 50
end seed species
begin observables
  Molecules A_CP A()@CP
  Molecules B_CP B()@CP
end observables
begin reaction rules
  {rule_line}
end reaction rules
end model
"""
        ens = _run_nfnext_cpu_ensemble(
            src_yes, ["A_CP", "B_CP"], 1.0, n_runs=24, seed_base=9610
        )
        expected = 50.0 * (1.0 - math.exp(-2.0))
        _assert_close(ens["A_CP"][0], ens["A_CP"][1], expected, z_max=4.5, min_tol=1.5)
        _assert_close(ens["B_CP"][0], ens["B_CP"][1], expected, z_max=4.5, min_tol=1.5)


def test_l2_01_15_nfnext_asymmetric_include_reactants_homodimer_symmetry():
    # Canonical BNG2.pl emits stat_factor = 0.5 for BOTH homotypic and mixed pairs.
    src_mixed = """begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A(b,c)
  C(a)
end molecule types
begin seed species
  A(b,c!1).C(a!1) 40
  A(b,c) 40
end seed species
begin observables
  Molecules Dim_CC C(a!1).A(c!1,b!2).A(b!2,c!3).C(a!3)
  Molecules Dim_CF C(a!1).A(c!1,b!2).A(b!2,c)
end observables
begin reaction rules
  R1: A(b) + A(b) -> A(b!1).A(b!1) k include_reactants(1, C())
end reaction rules
end model
"""
    ode = _run_ode_final(src_mixed, ["Dim_CC", "Dim_CF"], 1.0)
    ens = _run_nfnext_cpu_ensemble(
        src_mixed, ["Dim_CC", "Dim_CF"], 1.0, n_runs=64, seed_base=9701
    )
    _assert_close(
        ens["Dim_CC"][0], ens["Dim_CC"][1], ode["Dim_CC"], z_max=4.5, min_tol=1.5
    )
    _assert_close(
        ens["Dim_CF"][0], ens["Dim_CF"][1], ode["Dim_CF"], z_max=4.5, min_tol=1.5
    )


def test_l2_08_02_and_04_nfnext_compartment_and_unbound_energy_patterns():
    # L2-08-02: Compartmentalized energy patterns on state change (PM vs CP).
    src_comp = """begin model
begin parameters
  V_PM 1.0
  V_CP 1.0
  G_pm -2.0
  G_cp 2.0
  phi 0.5
  Ea 0.0
end parameters
begin compartments
  EC 3 1.0
  PM 2 V_PM EC
  CP 3 V_CP PM
end compartments
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U)@PM 400
  A(s~U)@CP 400
end seed species
begin observables
  Molecules AP_pm A(s~P)@PM
  Molecules AP_cp A(s~P)@CP
end observables
begin energy patterns
  A(s~P)@PM G_pm
  A(s~P)@CP G_cp
end energy patterns
begin reaction rules
  R_pm: A(s~U)@PM <-> A(s~P)@PM Arrhenius(phi, Ea)
  R_cp: A(s~U)@CP <-> A(s~P)@CP Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ens_c = _run_nfnext_cpu_ensemble(
        src_comp, ["AP_pm", "AP_cp"], 5.0, n_runs=16, seed_base=9801
    )
    exp_pm = 400.0 / (1.0 + math.exp(-2.0))
    exp_cp = 400.0 / (1.0 + math.exp(2.0))
    _assert_close(ens_c["AP_pm"][0], ens_c["AP_pm"][1], exp_pm, z_max=4.5, min_tol=4.0)
    _assert_close(ens_c["AP_cp"][0], ens_c["AP_cp"][1], exp_cp, z_max=4.5, min_tol=4.0)

    # L2-08-04: Unbound-site energy pattern A(b) G_free on binding.
    src_free = """begin model
begin parameters
  G_free -5.0
  phi 0.5
  Ea 4.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 200
  B(a) 200
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b) G_free
end energy patterns
begin reaction rules
  R1: A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    ode_f = _run_ode_final(src_free, ["AB"], 25.0)
    ens_f = _run_nfnext_cpu_ensemble(src_free, ["AB"], 25.0, n_runs=16, seed_base=9802)
    _assert_close(ens_f["AB"][0], ens_f["AB"][1], ode_f["AB"], z_max=4.5, min_tol=3.0)
