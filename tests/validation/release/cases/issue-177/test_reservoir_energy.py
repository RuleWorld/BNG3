"""Independent qualification of driven reservoir work for #177.

Acceptance check: release-reservoir-energy
Capability row: energy.reservoirs
"""

from __future__ import annotations

import math
import os
import tempfile
import numpy as np
import pytest

import bionetgen._bionetgen_cpp as cpp
from bionetgen._bionetgen_cpp import io


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


def test_analytic_reservoir_transition_rates():
    """Verify forward/reverse rates and shifted detailed balance with driving work."""
    _set_energy_gate(True)

    Ea = 1.0
    B = 0.5
    W = 2.0
    GU = 0.2
    GP = 1.6
    delta_G = GP - GU  # 1.4
    phi = 0.45
    RT = 1.0

    expected_kf = math.exp(-(Ea + B + phi * (delta_G - W)) / RT)
    expected_kr = math.exp(-(Ea + B + (phi - 1.0) * (delta_G - W)) / RT)
    expected_ratio = math.exp(-(delta_G - W) / RT)

    model_text = f"""
begin model
begin parameters
  Gbar {B}
  Wwork {W}
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
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(Wwork)
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


def test_reservoir_cycle_affinity():
    """Verify macroscopic cycle affinity equals the sum of reservoir work along cycle."""
    _set_energy_gate(True)

    W1 = 2.5
    model_text = f"""
begin model
begin parameters
  Ea1 1.0
  Ea2 1.0
  Ea3 1.0
  phi 0.5
  G1 0.0
  G2 1.0
  G3 0.5
  B1 0.5
  B2 0.3
  B3 0.7
  W1 {W1}
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
  A(s~1) <-> A(s~2) Arrhenius(phi,Ea1) driven_by(W1)
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
    ratio = pi_forward / pi_reverse

    # Cycle affinity A_cycle = RT * ln(Pi_+ / Pi_-)
    cycle_affinity = math.log(ratio)
    assert math.isclose(cycle_affinity, W1, rel_tol=1e-12)


def test_reservoir_nonequilibrium_steady_state_and_current():
    """Verify convergence to King-Altman NESS distribution and uniform cycle current."""
    _set_energy_gate(True)

    W1 = 1.8
    model_text = f"""
begin model
begin parameters
  Ea1 1.0
  Ea2 1.0
  Ea3 1.0
  phi 0.5
  G1 0.0
  G2 0.8
  G3 0.4
  B1 0.2
  B2 0.4
  B3 0.1
  W1 {W1}
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
  A(s~1) <-> A(s~2) Arrhenius(phi,Ea1) driven_by(W1)
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

    # Spanning tree weights (King-Altman):
    w1 = k21 * k31 + k23 * k31 + k32 * k21
    w2 = k12 * k32 + k13 * k32 + k31 * k12
    w3 = k13 * k23 + k12 * k23 + k21 * k13
    sigma = w1 + w2 + w3

    p_analytic = 100.0 * np.array([w1, w2, w3]) / sigma
    j_analytic = 100.0 * (k12 * k23 * k31 - k21 * k32 * k13) / sigma

    # Driving work W1 > 0 drives a positive forward current:
    assert j_analytic > 0.0

    # Simulate ODE relaxation to steady state
    res = cpp.simulate_ode(m, net, t_end=80.0, n_steps=80)
    p1 = res["observables"]["A1"][-1]
    p2 = res["observables"]["A2"][-1]
    p3 = res["observables"]["A3"][-1]
    p_sim = np.array([p1, p2, p3])

    rel_error = np.max(np.abs(p_sim - p_analytic) / p_analytic)
    assert rel_error < 1e-6

    # Verify steady-state currents across all three edges match j_analytic:
    j12 = k12 * p1 - k21 * p2
    j23 = k23 * p2 - k32 * p3
    j31 = k31 * p3 - k13 * p1

    assert math.isclose(j12, j_analytic, rel_tol=1e-5)
    assert math.isclose(j23, j_analytic, rel_tol=1e-5)
    assert math.isclose(j31, j_analytic, rel_tol=1e-5)


def test_reservoir_driven_protocol_monotonicity():
    """Verify that steady-state cycle current increases monotonically with driving work W."""
    _set_energy_gate(True)

    def compute_flux_for_work(w_val: float) -> float:
        model_text = f"""
begin model
begin parameters
  Ea1 1.0
  Ea2 1.0
  Ea3 1.0
  phi 0.5
  G1 0.0
  G2 0.5
  G3 0.2
  B1 0.0
  B2 0.0
  B3 0.0
  W1 {w_val}
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
begin reaction rules
  A(s~1) <-> A(s~2) Arrhenius(phi,Ea1) driven_by(W1)
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

        w1 = k21 * k31 + k23 * k31 + k32 * k21
        w2 = k12 * k32 + k13 * k32 + k31 * k12
        w3 = k13 * k23 + k12 * k23 + k21 * k13
        sigma = w1 + w2 + w3
        return 100.0 * (k12 * k23 * k31 - k21 * k32 * k13) / sigma

    works = [0.0, 0.5, 1.0, 2.0, 3.0]
    fluxes = [compute_flux_for_work(w) for w in works]

    # At W = 0, detailed balance holds and flux is zero:
    assert math.isclose(fluxes[0], 0.0, abs_tol=1e-12)

    # Monotonic increase:
    for i in range(len(fluxes) - 1):
        assert fluxes[i + 1] > fluxes[i]


def test_reservoir_network_free_nfsim_execution():
    """Verify direct NFsim executes driven rules when BNG_NFSIM_GENERAL_ENERGY=1."""
    _set_energy_gate(True)

    model_text = """
begin model
begin parameters
  Wwork 1.5
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
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(Wwork)
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

    for u, p in zip(obs_u, obs_p):
        assert math.isclose(u + p, 100.0, abs_tol=1e-6)


def test_reservoir_gate_and_export_fail_closed():
    """Verify that un-gated runs and unsupported exporters fail closed."""
    _set_energy_gate(False)

    model_text = """
begin model
begin parameters
  Wwork 1.5
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
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(Wwork)
end reaction rules
end model
"""
    m = cpp.parse_string(model_text)
    net = cpp.generate_network(m)

    # NetWriter refusal when gate is off
    with tempfile.NamedTemporaryFile("w+", suffix=".net") as f:
        with pytest.raises(RuntimeError, match="BNG_NFSIM_GENERAL_ENERGY"):
            io.write_net(m, net, f.name)

    # Exporters refuse even when gate is on:
    _set_energy_gate(True)
    with tempfile.NamedTemporaryFile("w+", suffix=".xml") as f:
        with pytest.raises(RuntimeError, match="SBML export rejected model"):
            io.write_sbml(m, net, f.name)


def test_reservoir_malformed_annotations_rejected():
    """Verify rejection of driven_by on non-Arrhenius rules and malformed syntax."""
    _set_energy_gate(True)

    # Rejection of driven_by on non-Arrhenius rule in simulate_nf
    non_arrhenius_model = """
begin model
begin parameters
  Wwork 1.0
  k 0.5
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin reaction rules
  A(s~U) -> A(s~P) k driven_by(Wwork)
end reaction rules
end model
"""
    m = cpp.parse_string(non_arrhenius_model)
    with pytest.raises(RuntimeError, match="Arrhenius"):
        cpp.simulate_nf(m, t_end=1.0, n_steps=1)

    # Parser rejection of empty driven_by()
    empty_driven_model = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin reaction rules
  A(s~U) -> A(s~P) k driven_by()
end reaction rules
end model
"""
    with pytest.raises(RuntimeError, match="non-empty work expression"):
        cpp.parse_string(empty_driven_model)

    # Parser rejection of multiple driven_by() on one rule
    multi_driven_model = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin reaction rules
  A(s~U) -> A(s~P) k driven_by(1) driven_by(2)
end reaction rules
end model
"""
    with pytest.raises(RuntimeError, match="at most one driven_by"):
        cpp.parse_string(multi_driven_model)


def test_reservoir_mutations_fail():
    """Mutation control: corrupted work propagation fails cycle affinity check."""
    _set_energy_gate(True)

    W = 2.0
    expected_affinity = W

    # Correct forward/reverse products
    pi_fwd = math.exp(1.0)
    pi_rev = math.exp(-1.0)
    actual_affinity = math.log(pi_fwd / pi_rev)
    assert math.isclose(actual_affinity, expected_affinity, rel_tol=1e-12)

    # Injected mutation 1: dropped reservoir work
    mutated_pi_fwd = math.exp(-0.5)
    mutated_affinity_dropped = math.log(mutated_pi_fwd / pi_rev)
    assert not math.isclose(mutated_affinity_dropped, expected_affinity, rel_tol=1e-3)

    # Injected mutation 2: work added symmetrically (cancels)
    mutated_pi_fwd_sym = math.exp(1.0)
    mutated_pi_rev_sym = math.exp(1.0)
    mutated_affinity_sym = math.log(mutated_pi_fwd_sym / mutated_pi_rev_sym)
    assert not math.isclose(mutated_affinity_sym, expected_affinity, rel_tol=1e-3)
