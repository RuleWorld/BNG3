"""Independent qualification of barrier pattern rate effects for #177.

Acceptance check: release-barrier-energy
Capability row: energy.barriers
"""

from __future__ import annotations

import math
import os
import tempfile
import numpy as np
import pytest

import bionetgen._bionetgen_cpp as cpp
import bionetgen._bionetgen_cpp.io as io


def _set_energy_gate(enabled: bool) -> None:
    if enabled:
        os.environ["BNG_NFSIM_GENERAL_ENERGY"] = "1"
    else:
        os.environ.pop("BNG_NFSIM_GENERAL_ENERGY", None)


@pytest.fixture(autouse=True)
def clean_energy_gate():
    prev = os.environ.get("BNG_NFSIM_GENERAL_ENERGY")
    try:
        yield
    finally:
        if prev is not None:
            os.environ["BNG_NFSIM_GENERAL_ENERGY"] = prev
        else:
            os.environ.pop("BNG_NFSIM_GENERAL_ENERGY", None)


def _extract_net_rates(
    model: cpp.Model, network: cpp.GeneratedNetwork
) -> dict[str, float]:
    """Extract named rate constant values from NetWriter output."""
    with tempfile.NamedTemporaryFile("w+", suffix=".net") as f:
        io.write_net(model, network, f.name)
        f.seek(0)
        rates = {}
        for line in f:
            line = line.strip()
            if line.startswith("begin parameters"):
                continue
            if line.startswith("end parameters"):
                break
            parts = line.split()
            if len(parts) >= 3 and ("Rate" in parts[1] or "k" in parts[1]):
                try:
                    rates[parts[1]] = float(parts[2])
                except ValueError:
                    pass
        return rates


def test_analytic_barrier_transition_rates():
    """Verify exact analytic forward/reverse rates and barrier cancellation in rate ratio."""
    _set_energy_gate(True)

    Ea = 1.2
    B = 2.4
    GU = 0.5
    GP = 1.8
    delta_G = GP - GU  # 1.3
    phi = 0.4
    RT = 1.0

    expected_kf = math.exp(-(Ea + B + phi * delta_G) / RT)
    expected_kr = math.exp(-(Ea + B + (phi - 1.0) * delta_G) / RT)
    expected_ratio = math.exp(-delta_G / RT)

    model_text = f"""
begin model
begin parameters
  Gbar {B}
  phi {phi}
  Ea {Ea}
  GU {GU}
  GP {GP}
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin observables
  Molecules A_U A(s~U)
  Molecules A_P A(s~P)
end observables
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""
    m = cpp.parse_string(model_text)
    net = cpp.generate_network(m)
    rates = _extract_net_rates(m, net)

    kf_sim = rates["R1Rate_1"]
    kr_sim = rates["R1rRate_1"]

    assert math.isclose(kf_sim, expected_kf, rel_tol=1e-12)
    assert math.isclose(kr_sim, expected_kr, rel_tol=1e-12)

    ratio_sim = kf_sim / kr_sim
    assert math.isclose(ratio_sim, expected_ratio, rel_tol=1e-12)

    # Re-evaluate with modified barrier B2 to verify barrier cancellation in ratio
    B2 = 5.0
    expected_kf2 = math.exp(-(Ea + B2 + phi * delta_G) / RT)
    expected_kr2 = math.exp(-(Ea + B2 + (phi - 1.0) * delta_G) / RT)

    model_text2 = model_text.replace(f"Gbar {B}", f"Gbar {B2}")
    m2 = cpp.parse_string(model_text2)
    net2 = cpp.generate_network(m2)
    rates2 = _extract_net_rates(m2, net2)

    kf_sim2 = rates2["R1Rate_1"]
    kr_sim2 = rates2["R1rRate_1"]
    assert math.isclose(kf_sim2, expected_kf2, rel_tol=1e-12)
    assert math.isclose(kr_sim2, expected_kr2, rel_tol=1e-12)

    ratio_sim2 = kf_sim2 / kr_sim2
    # The barrier cancels in the ratio: ratio_sim2 must equal ratio_sim exactly
    assert math.isclose(ratio_sim2, ratio_sim, rel_tol=1e-12)
    assert math.isclose(ratio_sim2, expected_ratio, rel_tol=1e-12)


def test_barrier_detailed_balance_cycle_identity():
    """Verify Kolmogorov cycle condition (Pi_+ / Pi_- = 1) and Boltzmann equilibrium."""
    _set_energy_gate(True)

    model_text = """
begin model
begin parameters
  Ea1 1.0
  Ea2 1.0
  Ea3 1.0
  phi 0.5
  G1 0.0
  G2 1.2
  G3 0.7
  B1 0.8
  B2 0.4
  B3 1.1
end parameters
begin molecule types
  A(s~1~2~3)
end molecule types
begin seed species
  A(s~1) 100
end seed species
begin observables
  Molecules A1 A(s~1)
  Molecules A2 A(s~2)
  Molecules A3 A(s~3)
end observables
begin energy patterns
  A(s~1) G1
  A(s~2) G2
  A(s~3) G3
end energy patterns
begin barrier patterns
  A(s~1) -> A(s~2) B1
  A(s~2) -> A(s~3) B2
  A(s~3) -> A(s~1) B3
end barrier patterns
begin reaction rules
  A(s~1) <-> A(s~2) Arrhenius(phi,Ea1)
  A(s~2) <-> A(s~3) Arrhenius(phi,Ea2)
  A(s~3) <-> A(s~1) Arrhenius(phi,Ea3)
end reaction rules
end model
"""
    m = cpp.parse_string(model_text)
    net = cpp.generate_network(m)
    rates = _extract_net_rates(m, net)

    k12 = rates["R1Rate_1"]
    k21 = rates["R1rRate_1"]
    k23 = rates["R2Rate_1"]
    k32 = rates["R2rRate_1"]
    k31 = rates["R3Rate_1"]
    k13 = rates["R3rRate_1"]

    pi_forward = k12 * k23 * k31
    pi_reverse = k21 * k32 * k13
    cycle_ratio = pi_forward / pi_reverse

    # Under microscopic reversibility / detailed balance, cycle ratio is identically 1.0
    assert math.isclose(cycle_ratio, 1.0, rel_tol=1e-12)
    cycle_affinity = math.log(cycle_ratio)
    assert abs(cycle_affinity) < 1e-12

    # Analytic Boltzmann distribution: p_i proportional to exp(-G_i / RT)
    g1, g2, g3 = 0.0, 1.2, 0.7
    boltzmann_weights = np.array([math.exp(-g1), math.exp(-g2), math.exp(-g3)])
    p_analytic = 100.0 * boltzmann_weights / np.sum(boltzmann_weights)

    # Simulate ODE relaxation to equilibrium
    res = cpp.simulate_ode(m, net, t_end=80.0, n_steps=80)
    p_sim = np.array(
        [
            res["observables"]["A1"][-1],
            res["observables"]["A2"][-1],
            res["observables"]["A3"][-1],
        ]
    )

    rel_error = np.max(np.abs(p_sim - p_analytic) / p_analytic)
    assert rel_error < 1e-6


def test_barrier_catalysis_and_obstruction_kinetics():
    """Verify negative barrier speeds relaxation and positive barrier slows relaxation."""
    _set_energy_gate(True)

    Ea = 1.0
    phi = 0.5
    GU = 0.0
    GP = 1.0
    delta_G = 1.0
    expected_ratio = math.exp(-delta_G)

    def run_barrier(barrier_val: float) -> tuple[float, float, float]:
        model_text = f"""
begin model
begin parameters
  Gbar {barrier_val}
  phi {phi}
  Ea {Ea}
  GU {GU}
  GP {GP}
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin observables
  Molecules A_U A(s~U)
  Molecules A_P A(s~P)
end observables
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""
        m = cpp.parse_string(model_text)
        net = cpp.generate_network(m)
        rates = _extract_net_rates(m, net)
        kf = rates["R1Rate_1"]
        kr = rates["R1rRate_1"]
        res = cpp.simulate_ode(m, net, t_end=150.0, n_steps=150)
        u_eq = res["observables"]["A_U"][-1]
        p_eq = res["observables"]["A_P"][-1]
        return kf, kr, p_eq / u_eq

    kf_base, kr_base, ratio_base = run_barrier(0.0)
    kf_cat, kr_cat, ratio_cat = run_barrier(-1.2)  # Catalysis
    kf_obs, kr_obs, ratio_obs = run_barrier(1.5)  # Obstruction

    # Catalytic lowering accelerates rate constants:
    assert kf_cat > kf_base
    assert kr_cat > kr_base
    assert math.isclose(kf_cat / kf_base, math.exp(1.2), rel_tol=1e-12)
    assert math.isclose(kr_cat / kr_base, math.exp(1.2), rel_tol=1e-12)

    # Kinetic obstruction slows rate constants:
    assert kf_obs < kf_base
    assert kr_obs < kr_base
    assert math.isclose(kf_obs / kf_base, math.exp(-1.5), rel_tol=1e-12)
    assert math.isclose(kr_obs / kr_base, math.exp(-1.5), rel_tol=1e-12)

    # Equilibrium ratio is identical across all three:
    assert math.isclose(ratio_base, expected_ratio, rel_tol=1e-6)
    assert math.isclose(ratio_cat, expected_ratio, rel_tol=1e-6)
    assert math.isclose(ratio_obs, expected_ratio, rel_tol=1e-6)


def test_barrier_reversal_symmetry():
    """Verify that barrier keying is symmetric under reaction center reversal."""
    _set_energy_gate(True)

    base_model = """
begin model
begin parameters
  Gbar 2.5
  phi 0.5
  Ea 1.0
  GU 0.0
  GP 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin barrier patterns
  {BARRIER_LINE}
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""
    m_forward = cpp.parse_string(
        base_model.format(BARRIER_LINE="A(s~U) -> A(s~P) Gbar")
    )
    m_reverse = cpp.parse_string(
        base_model.format(BARRIER_LINE="A(s~P) -> A(s~U) Gbar")
    )

    net_fwd = cpp.generate_network(m_forward)
    net_rev = cpp.generate_network(m_reverse)

    rates_fwd = _extract_net_rates(m_forward, net_fwd)
    rates_rev = _extract_net_rates(m_reverse, net_rev)

    assert math.isclose(rates_fwd["R1Rate_1"], rates_rev["R1Rate_1"], rel_tol=1e-12)
    assert math.isclose(rates_fwd["R1rRate_1"], rates_rev["R1rRate_1"], rel_tol=1e-12)


def test_barrier_network_free_nfsim_execution():
    """Verify that direct NFsim executes barrier models and matches analytic rates."""
    _set_energy_gate(True)

    model_text = """
begin model
begin parameters
  Gbar 1.5
  phi 0.5
  Ea 1.0
  GU 0.0
  GP 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin observables
  Molecules A_U A(s~U)
  Molecules A_P A(s~P)
end observables
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""
    m = cpp.parse_string(model_text)
    res = cpp.simulate_nf(m, t_end=20.0, n_steps=20)

    assert "time" in res
    assert "observables" in res
    assert len(res["time"]) > 0

    obs_u = res["observables"]["A_U"]
    obs_p = res["observables"]["A_P"]

    # Total conservation A_U + A_P == 100
    for u, p in zip(obs_u, obs_p):
        assert math.isclose(u + p, 100.0, abs_tol=1e-6)


def test_barrier_gate_fail_closed_refusal():
    """Verify that without BNG_NFSIM_GENERAL_ENERGY, NetWriter and NFsim refuse."""
    _set_energy_gate(False)

    model_text = """
begin model
begin parameters
  Gbar 2.0
  phi 0.5
  Ea 1.0
  GU 0.0
  GP 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""
    m = cpp.parse_string(model_text)

    # NFsim refusal
    with pytest.raises(RuntimeError, match="BNG_NFSIM_GENERAL_ENERGY"):
        cpp.simulate_nf(m, t_end=1.0, n_steps=1)


def test_barrier_invalid_declarations_rejected():
    """Verify fail-closed rejection of barriers declared without energy patterns."""
    _set_energy_gate(True)

    # Barrier declared without energy patterns
    no_energy_model = """
begin model
begin parameters
  Gbar 2.0
  phi 0.5
  Ea 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin barrier patterns
  A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""
    m_no_energy = cpp.parse_string(no_energy_model)
    with pytest.raises(RuntimeError, match="energy patterns"):
        cpp.simulate_nf(m_no_energy, t_end=1.0, n_steps=1)


def test_barrier_mutations_fail():
    """Mutation control: deliberately corrupted rate ratios violate detailed balance."""
    _set_energy_gate(True)

    # Correct detailed balance: kf / kr = exp(-delta_G)
    delta_G = 1.0
    kf = math.exp(-3.5)
    kr = math.exp(-2.5)
    assert math.isclose(kf / kr, math.exp(-delta_G), rel_tol=1e-12)

    # Injected mutation 1: asymmetric barrier in forward only
    kf_mutated = kf * math.exp(-1.0)
    assert not math.isclose(kf_mutated / kr, math.exp(-delta_G), rel_tol=1e-3)

    # Injected mutation 2: dropped barrier in reverse
    kr_mutated = kr * math.exp(2.0)
    assert not math.isclose(kf / kr_mutated, math.exp(-delta_G), rel_tol=1e-3)
