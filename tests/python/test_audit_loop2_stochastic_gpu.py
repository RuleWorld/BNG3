"""Loop 2 regression tests for PSA, PLA, and GPU Batch SSA (Metal/CUDA).

Covers confirmed Loop 2 audit findings:
  - L2-01-02 / L2-03-08: PSA TotalRate preserves compartment volume conversion (1/V)
  - L2-01-03: PSA & PLA Species observables with zero-matching quantifiers (==0, <2, <=1)
  - L2-01-04 / L2-08-01: PSA & PLA Energy BNGL Arrhenius rates + energy patterns
  - L2-01-08: PSA & PLA per-reaction scoped rates & FunctionProduct
  - L2-01-14 / L2-05-06: PSA Sat/MM/Hill rate laws & PSA/PLA observable tfun() evaluation
  - L2-03-02: PSA & PLA MoleculesObservables / SpeciesObservables CountUnique
  - L2-05-03: PLA ExactStochastic unbiased Gillespie SSA (no Poisson+rollback bias)
  - L2-05-04: PLA Langevin variance preservation & checkType/p/q config execution
  - L2-05-05: GPU Batch SSA (Metal/CUDA) exact int32->double Welford moments above 2^24
  - L2-05-07: PSA poplevel validation & PLA config parameter validation
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


def test_psa_and_pla_species_zero_matching_quantifiers() -> None:
    """L2-01-03: Zero-matching Species quantifiers (==0, <2, <=1) in PSA & PLA."""
    src = """begin model
begin parameters
  kon 0.002
  koff 0.2
end parameters
begin molecule types
  A(b,c)
  B(a)
  X()
end molecule types
begin seed species
  A(b,c) 200
  B(a) 400
  X() 300
end seed species
begin observables
  Species Sp_B_eq0 B()==0
  Species Sp_B_lt2 B()<2
  Species Sp_B_le1 B()<=1
  Molecules Mol_A_gt0 A()>0
end observables
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) kon, koff
  A(c) + B(a) <-> A(c!1).B(a!1) kon, koff
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    for res in (
        cpp.simulate_psa(model, net, t_end=2.0, n_steps=4, poplevel=10.0, seed=11),
        cpp.simulate_pla(model, net, t_end=2.0, n_steps=4, seed=11),
    ):
        assert res["observables"]["Sp_B_eq0"][0] == pytest.approx(500.0)
        assert res["observables"]["Sp_B_lt2"][0] == pytest.approx(900.0)
        assert res["observables"]["Sp_B_le1"][0] == pytest.approx(900.0)
        assert res["observables"]["Mol_A_gt0"][0] == pytest.approx(200.0)
        # At t=2, some A.B.B trimers form so Sp_B_lt2 drops below 900
        assert res["observables"]["Sp_B_eq0"][-1] >= 300.0
        assert res["observables"]["Mol_A_gt0"][-1] == pytest.approx(200.0)


def test_psa_and_pla_energy_bngl_arrhenius_rates() -> None:
    """L2-01-04 / L2-08-01: PSA & PLA evaluate Energy BNGL Arrhenius rates accurately."""
    src = """begin model
begin parameters
  Gf_AA -2.0
  Gf_As1 -1.0
  phi 0.5
  Ea_bind 6.0
  Ea_state 2.0
end parameters
begin molecule types
  A(b,s~0~1)
end molecule types
begin seed species
  A(b,s~0) 400
end seed species
begin observables
  Molecules A_mono A(b)
  Molecules A_dim A(b!1).A(b!1)
  Molecules A_s1 A(s~1)
end observables
begin energy patterns
  A(b!1).A(b!1) Gf_AA
  A(s~1) Gf_As1
end energy patterns
begin reaction rules
  A(b) + A(b) <-> A(b!1).A(b!1) Arrhenius(phi, Ea_bind)
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea_state)
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    ode = cpp.simulate_ode(model, net, t_end=5.0, n_steps=10)
    ode_mono = float(ode["observables"]["A_mono"][-1])
    ode_dim = float(ode["observables"]["A_dim"][-1])
    ode_s1 = float(ode["observables"]["A_s1"][-1])
    assert ode_dim > 300.0 and ode_s1 > 180.0

    psa_mono, psa_dim, psa_s1 = [], [], []
    pla_mono, pla_dim, pla_s1 = [], [], []
    for seed in range(101, 117):
        rp = cpp.simulate_psa(
            model, net, t_end=5.0, n_steps=10, poplevel=10.0, seed=seed
        )
        psa_mono.append(float(rp["observables"]["A_mono"][-1]))
        psa_dim.append(float(rp["observables"]["A_dim"][-1]))
        psa_s1.append(float(rp["observables"]["A_s1"][-1]))

        rl = cpp.simulate_pla(model, net, t_end=5.0, n_steps=10, seed=seed)
        pla_mono.append(float(rl["observables"]["A_mono"][-1]))
        pla_dim.append(float(rl["observables"]["A_dim"][-1]))
        pla_s1.append(float(rl["observables"]["A_s1"][-1]))

    assert abs(float(np.mean(psa_mono)) - ode_mono) < 12.0
    assert abs(float(np.mean(psa_dim)) - ode_dim) < 12.0
    assert abs(float(np.mean(psa_s1)) - ode_s1) < 15.0

    assert abs(float(np.mean(pla_mono)) - ode_mono) < 12.0
    assert abs(float(np.mean(pla_dim)) - ode_dim) < 12.0
    assert abs(float(np.mean(pla_s1)) - ode_s1) < 15.0

    # Also verify Boltzmann equilibrium when Ea = 0 (previously gave AP ~ 500 instead of 880.8)
    boltz_src = """begin model
begin parameters
  G_P -2.0
  phi  0.5
  Ea   0.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 1000
end seed species
begin observables
  Molecules AP A(s~P)
end observables
begin energy patterns
  A(s~P) G_P
end energy patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    bm = cpp.parse_string(boltz_src)
    bn = cpp.generate_network(bm)
    exact_ap = 1000.0 / (1.0 + math.exp(-2.0))
    psa_ap = float(
        np.mean(
            [
                cpp.simulate_psa(bm, bn, t_end=10.0, n_steps=10, poplevel=20.0, seed=s)[
                    "observables"
                ]["AP"][-1]
                for s in range(1, 17)
            ]
        )
    )
    pla_ap = float(
        np.mean(
            [
                cpp.simulate_pla(bm, bn, t_end=10.0, n_steps=10, seed=s)["observables"][
                    "AP"
                ][-1]
                for s in range(1, 17)
            ]
        )
    )
    assert abs(psa_ap - exact_ap) < 25.0
    assert abs(pla_ap - exact_ap) < 25.0


def test_psa_and_pla_per_reaction_scoped_rates_and_function_product() -> None:
    """L2-01-08: PSA & PLA evaluate per-reaction scoped rates and FunctionProduct."""
    # Multi-reaction scoped rate (previously hardcoded _local1 for all reactions)
    scoped_src = """begin model
begin parameters
  k0 0.05
  k1 0.4
end parameters
begin molecule types
  A(b,s~0~1)
  B(a)
end molecule types
begin seed species
  A(b,s~0) 300
  A(b!1,s~0).B(a!1) 300
end seed species
begin observables
  Molecules B_obs B()
  Molecules A1_free A(b,s~1)
  Molecules A1_bound A(b!1,s~1).B(a!1)
end observables
begin functions
  f_loc(x) = k0 + k1 * B_obs(x)
end functions
begin reaction rules
  %x::A(s~0) -> %x::A(s~1) f_loc(x)
end reaction rules
end model
"""
    m1 = cpp.parse_string(scoped_src)
    n1 = cpp.generate_network(m1)
    exact_free = 300.0 * (1.0 - math.exp(-0.05 * 5.0))
    exact_bound = 300.0 * (1.0 - math.exp(-0.45 * 5.0))

    psa_free, psa_bound = [], []
    pla_free, pla_bound = [], []
    for seed in range(1, 17):
        rp = cpp.simulate_psa(m1, n1, t_end=5.0, n_steps=10, poplevel=10.0, seed=seed)
        psa_free.append(float(rp["observables"]["A1_free"][-1]))
        psa_bound.append(float(rp["observables"]["A1_bound"][-1]))

        rl = cpp.simulate_pla(m1, n1, t_end=5.0, n_steps=10, seed=seed)
        pla_free.append(float(rl["observables"]["A1_free"][-1]))
        pla_bound.append(float(rl["observables"]["A1_bound"][-1]))

    assert abs(float(np.mean(psa_free)) - exact_free) < 12.0
    assert abs(float(np.mean(psa_bound)) - exact_bound) < 12.0
    assert abs(float(np.mean(pla_free)) - exact_free) < 12.0
    assert abs(float(np.mean(pla_bound)) - exact_bound) < 12.0

    # FunctionProduct with two distinct scoped reactants
    fp_src = """begin model
begin parameters
  kA 0.001
  kB 1.0
end parameters
begin molecule types
  A(b,s~0~1)
  B(a,s~0~1)
end molecule types
begin seed species
  A(b,s~0) 150
  A(b,s~1) 150
  B(a,s~0) 150
  B(a,s~1) 150
end seed species
begin observables
  Molecules As1 A(s~1)
  Molecules Bs1 B(s~1)
  Molecules AB A(b!1).B(a!1)
end observables
begin functions
  fA(x) = kA * (1 + 2 * As1(x))
  fB(y) = kB * (1 + 2 * Bs1(y))
end functions
begin reaction rules
  %x::A(b) + %y::B(a) -> %x::A(b!1).%y::B(a!1) FunctionProduct("fA(x)","fB(y)")
end reaction rules
end model
"""
    m2 = cpp.parse_string(fp_src)
    n2 = cpp.generate_network(m2)
    ode_ab = float(
        cpp.simulate_ode(m2, n2, t_end=2.0, n_steps=10)["observables"]["AB"][-1]
    )

    psa_ab = float(
        np.mean(
            [
                cpp.simulate_psa(m2, n2, t_end=2.0, n_steps=10, poplevel=10.0, seed=s)[
                    "observables"
                ]["AB"][-1]
                for s in range(1, 17)
            ]
        )
    )
    pla_ab = float(
        np.mean(
            [
                cpp.simulate_pla(m2, n2, t_end=2.0, n_steps=10, seed=s)["observables"][
                    "AB"
                ][-1]
                for s in range(1, 17)
            ]
        )
    )
    assert abs(psa_ab - ode_ab) < 15.0
    assert abs(pla_ab - ode_ab) < 15.0


def test_psa_totalrate_preserves_compartment_volume_conversion() -> None:
    """L2-01-02 / L2-03-08: PSA applies 1/V compartment conversion on authored TotalRate."""
    src = """begin model
begin parameters
  V_EC 5.0
  V_PM 3.0
  V_CP 4.0
  k2 0.0005
  ku 0.2
end parameters
begin compartments
  EC 3 V_EC
  PM 2 V_PM EC
  CP 3 V_CP PM
end compartments
begin molecule types
  S(d)
end molecule types
begin seed species
  S(d)@PM 400
end seed species
begin observables
  Molecules S_dim S(d!1)@PM.S(d!1)@PM
end observables
begin reaction rules
  S(d)@PM + S(d)@PM -> S(d!1)@PM.S(d!1)@PM k2 TotalRate
  S(d!1)@PM.S(d!1)@PM -> S(d)@PM + S(d)@PM ku TotalRate
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    # Canonical BNG2 ODE with 1/V_PM = 1/3 gives S_dim(5.0) ~ 108.6 (buggy 1.0 gave ~181).
    psa_dim = float(
        np.mean(
            [
                cpp.simulate_psa(
                    model, net, t_end=5.0, n_steps=10, poplevel=10.0, seed=s
                )["observables"]["S_dim"][-1]
                for s in range(1, 21)
            ]
        )
    )
    assert (
        90.0 < psa_dim < 128.0
    ), f"Expected S_dim ~ 108.6 (with 1/V_PM), got {psa_dim:.2f}"


def test_psa_builtin_sat_mm_hill_rate_laws() -> None:
    """L2-01-14 / L2-05-06: PSA supports Sat, MM (with compartments), and Hill rate laws."""
    src = """begin model
begin parameters
  V_CP 5.0
end parameters
begin compartments
  CP 3 V_CP
end compartments
begin molecule types
  S()
  P()
  X()
  E()
  Y()
  U()
  V()
end molecule types
begin seed species
  S()@CP 300
  P()@CP 0
  X()@CP 350
  E()@CP 200
  Y()@CP 0
  U()@CP 300
  V()@CP 0
end seed species
begin observables
  Molecules P_obs P()@CP
  Molecules Y_obs Y()@CP
  Molecules V_obs V()@CP
end observables
begin reaction rules
  S()@CP -> P()@CP Sat(50.0, 100.0)
  X()@CP + E()@CP -> Y()@CP + E()@CP MM(0.5, 150.0)
  U()@CP -> V()@CP Hill(40.0, 120.0, 2.5)
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    ode = cpp.simulate_ode(model, net, t_end=5.0, n_steps=10)
    ode_p = float(ode["observables"]["P_obs"][-1])
    ode_y = float(ode["observables"]["Y_obs"][-1])
    ode_v = float(ode["observables"]["V_obs"][-1])

    for poplevel in (0.0, 10.0):
        ps, ys, vs = [], [], []
        for seed in range(1, 13):
            res = cpp.simulate_psa(
                model, net, t_end=5.0, n_steps=10, poplevel=poplevel, seed=seed
            )
            ps.append(float(res["observables"]["P_obs"][-1]))
            ys.append(float(res["observables"]["Y_obs"][-1]))
            vs.append(float(res["observables"]["V_obs"][-1]))
        assert abs(float(np.mean(ps)) - ode_p) < 20.0
        assert abs(float(np.mean(ys)) - ode_y) < 15.0
        assert abs(float(np.mean(vs)) - ode_v) < 20.0


def test_psa_and_pla_tfun_observable_rates(tmp_path: Path) -> None:
    """L2-05-06: PSA & PLA evaluate file-backed and inline tfun(obs) cleanly."""
    tfun_file = tmp_path / "rates.tfun"
    tfun_file.write_text("# obs rate\n0 0.2\n50 1.0\n100 2.0\n", encoding="utf-8")

    src = f"""begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules obsA A()
  Molecules obsB B()
end observables
begin functions
  f_tfun() = tfun('{tfun_file.as_posix()}', obsA, method=>'linear')
end functions
begin reaction rules
  A() -> B() f_tfun()
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)

    psa_b = float(
        np.mean(
            [
                cpp.simulate_psa(
                    model, net, t_end=1.0, n_steps=5, poplevel=5.0, seed=s
                )["observables"]["obsB"][-1]
                for s in range(1, 21)
            ]
        )
    )
    pla_b = float(
        np.mean(
            [
                cpp.simulate_pla(model, net, t_end=1.0, n_steps=5, seed=s)[
                    "observables"
                ]["obsB"][-1]
                for s in range(1, 21)
            ]
        )
    )
    # Exact trajectory with k(A) = 0.2 + 0.018*A drops A from 100 to ~30 -> B ~ 70.
    assert 50.0 < psa_b < 88.0
    assert 50.0 < pla_b < 88.0
    assert abs(psa_b - pla_b) < 10.0

    # Missing tfun file fails cleanly without leaking internal __tfun_file_hex_ tokens
    missing_src = src.replace(
        tfun_file.as_posix(), (tmp_path / "missing.tfun").as_posix()
    )
    m_miss = cpp.parse_string(missing_src)
    n_miss = cpp.generate_network(m_miss)
    for fn in (
        lambda: cpp.simulate_psa(
            m_miss, n_miss, t_end=1.0, n_steps=2, poplevel=5.0, seed=1
        ),
        lambda: cpp.simulate_pla(m_miss, n_miss, t_end=1.0, n_steps=2, seed=1),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            fn()
        assert "__tfun_file_hex_" not in str(exc_info.value)


def test_psa_and_pla_count_unique_observables() -> None:
    """L2-03-02: PSA & PLA honor MoleculesObservables and SpeciesObservables CountUnique."""
    src = """begin model
setOption("MoleculesObservables","CountUnique")
setOption("SpeciesObservables","CountUnique")
begin parameters
  k 0.01
end parameters
begin molecule types
  A(b,s~0~1)
  B(s~0~1)
end molecule types
begin seed species
  A(b!1,s~0).A(b!1,s~0) 100
  B(s~0) 100
end seed species
begin observables
  Molecules M_Dimer A(b!1).A(b!1)
  Species S_TwoPatt A(s~0) A(b!+)
  Molecules B_active B(s~1)
end observables
begin functions
  f_rate() = k * M_Dimer
end functions
begin reaction rules
  R_B: B(s~0) -> B(s~1) f_rate()
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    exact_b = 100.0 * (1.0 - math.exp(-1.0))  # 63.21 (CountAll bug gave 86.47)

    psa_b, pla_b = [], []
    for seed in range(1, 25):
        rp = cpp.simulate_psa(model, net, t_end=1.0, n_steps=2, poplevel=5.0, seed=seed)
        assert rp["observables"]["M_Dimer"][0] == pytest.approx(100.0)
        assert rp["observables"]["S_TwoPatt"][0] == pytest.approx(100.0)
        psa_b.append(float(rp["observables"]["B_active"][-1]))

        rl = cpp.simulate_pla(model, net, t_end=1.0, n_steps=2, seed=seed)
        assert rl["observables"]["M_Dimer"][0] == pytest.approx(100.0)
        assert rl["observables"]["S_TwoPatt"][0] == pytest.approx(100.0)
        pla_b.append(float(rl["observables"]["B_active"][-1]))

    assert abs(float(np.mean(psa_b)) - exact_b) < 6.0
    assert abs(float(np.mean(pla_b)) - exact_b) < 6.0


def test_pla_exact_stochastic_unbiased_survival_and_nsteps_invariance() -> None:
    """L2-05-03: PLA ExactStochastic steps exact SSA without Poisson+rollback bias."""
    for a0 in (1, 5):
        src = f"""begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() {a0}
end seed species
begin observables
  Molecules obsA A()
end observables
begin reaction rules
  A() -> B() 1.0
end reaction rules
end model
"""
        model = cpp.parse_string(src)
        net = cpp.generate_network(model)
        exact_mean = a0 * math.exp(-1.0)
        exact_std = math.sqrt(a0 * math.exp(-1.0) * (1.0 - math.exp(-1.0)))

        n_traj = 1200
        for n_steps in (1, 10):
            vals = [
                float(
                    cpp.simulate_pla(
                        model, net, t_end=1.0, n_steps=n_steps, seed=1000 + i
                    )["observables"]["obsA"][-1]
                )
                for i in range(n_traj)
            ]
            mean = float(np.mean(vals))
            se = exact_std / math.sqrt(n_traj)
            z = (mean - exact_mean) / se
            assert abs(z) < 4.0, (
                f"PLA biased for A0={a0}, n_steps={n_steps}: mean={mean:.4f}, "
                f"exact={exact_mean:.4f}, z={z:+.2f}"
            )


def test_pla_langevin_stationary_variance_and_config_options() -> None:
    """L2-05-04 & L2-05-07: PLA Langevin variance, checkType/p/q options, and input guards."""
    # Stationary 0 <-> A: exact Poisson(1000) => mean=1000, std=31.62 (dead Langevin gave 11.22)
    bd_src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 1000
end seed species
begin observables
  Molecules obsA A()
end observables
begin reaction rules
  0 -> A() 1000.0
  A() -> 0 1.0
end reaction rules
end model
"""
    m_bd = cpp.parse_string(bd_src)
    n_bd = cpp.generate_network(m_bd)
    vals = [
        float(
            cpp.simulate_pla(m_bd, n_bd, t_end=5.0, n_steps=10, seed=5000 + i)[
                "observables"
            ]["obsA"][-1]
        )
        for i in range(200)
    ]
    mean = float(np.mean(vals))
    std = float(np.std(vals, ddof=1))
    assert abs(mean - 1000.0) < 12.0, f"Expected mean ~1000, got {mean:.2f}"
    assert 22.0 < std < 50.0, f"Expected Langevin std near 31.6-37, got {std:.2f}"

    # Distinct checkType/p/q configs on A <-> B must not collapse to identical deterministic output
    rev_src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 500
  B() 0
end seed species
begin observables
  Molecules obsA A()
  Molecules obsB B()
end observables
begin reaction rules
  A() <-> B() 1.0, 1.0
end reaction rules
end model
"""
    m_rev = cpp.parse_string(rev_src)
    n_rev = cpp.generate_network(m_rev)
    trajs = {}
    for cfg in (
        "fEuler|pre-neg:sb|eps=0.1",
        "fEuler|pre-eps:sb|eps=0.1",
        "fEuler|post-neg:sb|eps=0.1,p=0.5,q=1.5",
        "fEuler|post-eps:sb|eps=0.1,p=0.5,q=1.5,w=0.75",
        "fEuler|post-eps:sb|eps=0.1,p=0.2,q=3.0,w=0.5",
    ):
        res = cpp.simulate_pla(
            m_rev, n_rev, t_end=5.0, n_steps=5, config_str=cfg, seed=12345
        )
        a_arr = np.asarray(res["observables"]["obsA"], dtype=float)
        b_arr = np.asarray(res["observables"]["obsB"], dtype=float)
        np.testing.assert_allclose(a_arr + b_arr, 500.0, atol=1e-9)
        trajs[cfg] = tuple(a_arr.tolist())
    assert len(set(trajs.values())) >= 3, f"Expected distinct config paths, got {trajs}"

    # L2-05-07: invalid poplevel / eps / tau must fail closed
    with pytest.raises((ValueError, RuntimeError)):
        cpp.simulate_psa(
            m_rev, n_rev, t_end=1.0, n_steps=2, poplevel=float("nan"), seed=1
        )
    for bad_cfg in (
        "fEuler|pre-neg:sb|eps=0",
        "fEuler|pre-neg:sb|eps=-0.1",
        "fEuler|pre-neg:sb|tau=-1.0",
        "fEuler|fixed:sb|tau=0",
    ):
        with pytest.raises((ValueError, RuntimeError)):
            cpp.simulate_pla(
                m_rev, n_rev, t_end=1.0, n_steps=2, config_str=bad_cfg, seed=1
            )


def test_gpu_batch_ssa_large_population_welford_moments() -> None:
    """L2-05-05: GPU Batch SSA preserves exact std on populations > 2^24 without cancellation."""
    backend = _usable_gpu_backend()
    if backend is None:
        import bionetgen

        caps = bionetgen.gpu_backend_capabilities()
        assert all(not entry.get("available") for entry in caps)
        return

    src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20000000
end seed species
begin observables
  Molecules obsA A()
  Molecules obsB B()
end observables
begin reaction rules
  A() -> B() 5e-8
end reaction rules
end model
"""
    model = cpp.parse_string(src)
    net = cpp.generate_network(model)
    gpu = cpp.simulate_batch_ssa_gpu(
        model, net, batch_size=2000, t_end=1.0, n_steps=2, base_seed=42, backend=backend
    )

    std_a_t0 = float(gpu["observable_stds"]["obsA"][0])
    std_a_t1 = float(gpu["observable_stds"]["obsA"][-1])
    std_b_t1 = float(gpu["observable_stds"]["obsB"][-1])

    # Exact: A(0)=2e7 is deterministic => std(A, t=0) == 0; A + B == 2e7 => std(A, t=1) == std(B, t=1) ~ 1.0
    assert std_a_t0 == 0.0, f"Spurious non-zero t=0 std: {std_a_t0}"
    assert 0.7 < std_a_t1 < 1.3, f"Expected std(obsA, t=1) ~ 1.0, got {std_a_t1}"
    assert (
        abs(std_a_t1 - std_b_t1) < 1e-4
    ), f"Conservation std(A)==std(B) violated: stdA={std_a_t1}, stdB={std_b_t1}"

    # Functional rate with population > 2^24 must fail closed to CPU fallback
    func_large_src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20000000
end seed species
begin observables
  Molecules obsA A()
end observables
begin functions
  f_rate() = if(obsA > 19999999, 5e-8, 0)
end functions
begin reaction rules
  A() -> B() f_rate()
end reaction rules
end model
"""
    mf = cpp.parse_string(func_large_src)
    nf = cpp.generate_network(mf)
    with pytest.raises(RuntimeError, match="2\\^24|CPU"):
        cpp.simulate_batch_ssa_gpu(
            mf, nf, batch_size=64, t_end=1.0, n_steps=2, base_seed=42, backend=backend
        )
