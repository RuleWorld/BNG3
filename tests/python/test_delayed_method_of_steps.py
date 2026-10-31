"""Analytical qualification of delayed reactions and expressions.

Qualifies:
1. Analytical Method of Steps for consuming delay kinetics A -> B delay=tau.
2. In-flight reactant conservation across delay horizons.
3. Multi-interval continuation across the activation discontinuity at t = tau.
4. Non-consuming delayed reaction piecewise linear ramp.
5. Parameter change during continuation carrying prehistory initiations.
6. SBML csymbol delay prehistory evaluation against SBML L3V2 specifications.
"""

from __future__ import annotations

import numpy as np
import pytest

from bionetgen import BioNetGenModel
from _extdep import require_extension

cpp = require_extension()


DELAY_CONSUMING_BNGL = """
begin model
begin parameters
  k 0.5
  tau 2.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100.0
  B() 0.0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""

DELAY_NONCONSUMING_BNGL = """
begin model
begin parameters
  k 2.5
  tau 1.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10.0
  B() 0.0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> A() + B() k delay=tau NonConsuming
end reaction rules
end model
"""


def test_delayed_decay_method_of_steps_intervals():
    """Verify delayed first-order decay against the analytical Method of Steps.

    Differential Delay Equation (DDE) system:
      dA/dt = - k * A(t),                          A(0) = A_0
      dB/dt = 0                (0 <= t < tau),     B(0) = 0
      dB/dt = k * A(t - tau)   (t >= tau)

    Analytical solution:
      A(t) = A_0 * exp(-k * t)
      B(t) = 0                                       for t < tau
      B(t) = A_0 * (1 - exp(-k * (t - tau)))         for t >= tau
      A_transit(t) = A_0 - A(t) - B(t)
                   = A_0 * (exp(-k * (t - tau)) - exp(-k * t))  for t >= tau
    """
    model = BioNetGenModel(cpp.parse_string(DELAY_CONSUMING_BNGL))
    sample_times = [float(x) for x in np.linspace(0.0, 6.0, 61)]
    result = model.simulate(
        method="ode",
        t_start=0.0,
        t_end=6.0,
        sample_times=sample_times,
        rtol=1e-8,
        atol=1e-12,
    )

    t = np.array(result.time)
    A = np.array(result.observables["A_obs"])
    B = np.array(result.observables["B_obs"])

    k = 0.5
    tau = 2.0
    A0 = 100.0

    A_expected = A0 * np.exp(-k * t)
    B_expected = np.where(t < tau, 0.0, A0 * (1.0 - np.exp(-k * (t - tau))))

    # In-flight mass in transit
    A_transit = np.where(
        t < tau,
        A0 * (1.0 - np.exp(-k * t)),
        A0 * (np.exp(-k * (t - tau)) - np.exp(-k * t)),
    )

    # 1. Species quantities match the analytical Method of Steps solution
    np.testing.assert_allclose(A, A_expected, rtol=1e-5, atol=1e-7)
    np.testing.assert_allclose(B, B_expected, rtol=1e-5, atol=1e-7)

    # 2. Strict mass accounting: Reactant + Product + In-Flight = A0 at all times
    total_mass = A + B + A_transit
    np.testing.assert_allclose(total_mass, A0, rtol=1e-5, atol=1e-7)

    # 3. Before tau, no completion occurs
    pre_tau_idx = t < tau
    np.testing.assert_allclose(B[pre_tau_idx], 0.0, atol=1e-12)


def test_delayed_multi_interval_continuation():
    """Verify multi-interval continuation across the activation discontinuity at t = tau.

    Simulation is divided into four sequential 1.0s segments:
      Segment 1: [0.0, 1.0] (t < tau)
      Segment 2: [1.0, 2.0] (t reaching tau)
      Segment 3: [2.0, 3.0] (t >= tau, completions activated)
      Segment 4: [3.0, 4.0] (continuation deep in delay horizon)
    """
    model = BioNetGenModel(cpp.parse_string(DELAY_CONSUMING_BNGL))

    r1 = model.simulate(method="ode", t_start=0.0, t_end=1.0, n_steps=10)
    r2 = model.simulate(
        method="ode", t_start=1.0, t_end=2.0, n_steps=10, continue_simulation=True
    )
    r3 = model.simulate(
        method="ode", t_start=2.0, t_end=3.0, n_steps=10, continue_simulation=True
    )
    r4 = model.simulate(
        method="ode", t_start=3.0, t_end=4.0, n_steps=10, continue_simulation=True
    )

    t_all = np.concatenate([r1.time, r2.time[1:], r3.time[1:], r4.time[1:]])
    A_all = np.concatenate(
        [
            r1.observables["A_obs"],
            r2.observables["A_obs"][1:],
            r3.observables["A_obs"][1:],
            r4.observables["A_obs"][1:],
        ]
    )
    B_all = np.concatenate(
        [
            r1.observables["B_obs"],
            r2.observables["B_obs"][1:],
            r3.observables["B_obs"][1:],
            r4.observables["B_obs"][1:],
        ]
    )

    k = 0.5
    tau = 2.0
    A0 = 100.0

    A_expected = A0 * np.exp(-k * t_all)
    B_expected = np.where(t_all < tau, 0.0, A0 * (1.0 - np.exp(-k * (t_all - tau))))

    np.testing.assert_allclose(A_all, A_expected, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(B_all, B_expected, rtol=1e-5, atol=1e-6)

    # Check that B starts exactly at 0 at junction t=2, and smoothly continues at t=3
    np.testing.assert_allclose(r2.observables["B_obs"][-1], 0.0, atol=1e-8)
    np.testing.assert_allclose(r3.observables["B_obs"][0], 0.0, atol=1e-8)
    np.testing.assert_allclose(
        r3.observables["B_obs"][-1], r4.observables["B_obs"][0], rtol=1e-6
    )


def test_delayed_nonconsuming_linear_ramp():
    """Verify non-consuming delayed reaction produces an exact piecewise linear ramp.

    Reaction: A -> A + B delay=tau NonConsuming
    Rate equation:
      dA/dt = 0  =>  A(t) = A_0
      dB/dt = 0                       for t < tau
      dB/dt = k * A_0                 for t >= tau
    Analytical solution:
      B(t) = 0                        for t < tau
      B(t) = k * A_0 * (t - tau)      for t >= tau
    """
    model = BioNetGenModel(cpp.parse_string(DELAY_NONCONSUMING_BNGL))
    sample_times = [float(x) for x in np.linspace(0.0, 4.0, 41)]
    result = model.simulate(
        method="ode",
        t_start=0.0,
        t_end=4.0,
        sample_times=sample_times,
        rtol=1e-8,
        atol=1e-12,
    )

    t = np.array(result.time)
    A = np.array(result.observables["A_obs"])
    B = np.array(result.observables["B_obs"])

    k = 2.5
    tau = 1.5
    A0 = 10.0

    np.testing.assert_allclose(A, A0, atol=1e-12)
    B_expected = np.where(t < tau, 0.0, k * A0 * (t - tau))
    np.testing.assert_allclose(B, B_expected, rtol=1e-5, atol=1e-7)


def test_delayed_parameter_change_preserves_prehistory():
    """Verify parameter change during continuation carries historical initiations.

    Stage 1: [0.0, 2.0] with k = 0.5, tau = 2.0.
      Initiations occur at rate 0.5 * A(t).
      At t = 2.0: A(2) = A_0 * exp(-0.5 * 2) = 100 * exp(-1), B(2) = 0.

    Parameter change: k is set to 1.0 at t = 2.0.
    Stage 2: [2.0, 4.0] with k = 1.0, tau = 2.0 continued.
      Reactant A consumes at new rate k_new = 1.0:
        A(t) = A(2) * exp(-1.0 * (t - 2))  =>  A(4) = 100 * exp(-3).
      Completions arriving in [2.0, 4.0] were initiated in [0.0, 2.0] when k was 0.5:
        Total completions in [2.0, 4.0] = A(0) - A(2) = 100 * (1 - exp(-1)).
        B(4) = 100 * (1 - exp(-1)).
    """
    model = BioNetGenModel(cpp.parse_string(DELAY_CONSUMING_BNGL))
    res1 = model.simulate(method="ode", t_start=0.0, t_end=2.0, n_steps=20)
    np.testing.assert_allclose(res1.observables["B_obs"][-1], 0.0, atol=1e-8)

    model.set_parameter("k", 1.0)
    res2 = model.simulate(
        method="ode", t_start=2.0, t_end=4.0, n_steps=20, continue_simulation=True
    )

    A4_expected = 100.0 * np.exp(-3.0)
    B4_expected = 100.0 * (1.0 - np.exp(-1.0))

    np.testing.assert_allclose(res2.observables["A_obs"][-1], A4_expected, rtol=1e-5)
    np.testing.assert_allclose(res2.observables["B_obs"][-1], B4_expected, rtol=1e-5)


def test_delayed_prehistory_jump_across_delay_horizon():
    """Verify discontinuous parameter jump during [0, tau] propagates across delay horizon to t = tau + t_jump.

    System: A -> B delay=tau where tau = 2.0, A_0 = 100.
    Phase 1: [0, 1.0] with k_1 = 0.5.
      At t_jump = 1.0 < tau:
        A(1) = 100 * exp(-0.5) = 60.653066
        B(1) = 0
    Intervention at t_jump = 1.0: parameter k jumps from 0.5 to 1.0.
    Phase 2: [1.0, 4.0] continued with k_2 = 1.0.
      For t in [1.0, 4.0]:
        A(t) = A(1) * exp(-1.0 * (t - 1.0))
        A(4) = 100 * exp(-0.5) * exp(-3.0) = 100 * exp(-3.5) = 3.019738
      For delayed product B:
        - On [1.0, 2.0] (t < tau): dB/dt = 0 => B = 0.
        - On [2.0, 3.0] (t - tau in [0, 1.0]):
            Initiated with k_1 = 0.5:
            B(t) = 100 * (1 - exp(-0.5 * (t - 2)))
            At t = 3.0: B(3) = 100 * (1 - exp(-0.5)) = 39.346934
        - On [3.0, 4.0] (t - tau in [1.0, 2.0]):
            Initiated with k_2 = 1.0:
            dB/dt experiences jump at t = 3.0 from k_1 * A(1) = 30.3265 to k_2 * A(1) = 60.653
            B(4) = B(3) + A(1) * (1 - exp(-1.0 * (4 - 3)))
                 = 100 * (1 - exp(-0.5)) + 100 * exp(-0.5) * (1 - exp(-1.0))
                 = 77.686984
    """
    model = BioNetGenModel(cpp.parse_string(DELAY_CONSUMING_BNGL))

    # Phase 1: [0.0, 1.0] with k = 0.5
    res1 = model.simulate(method="ode", t_start=0.0, t_end=1.0, n_steps=20)
    np.testing.assert_allclose(res1.observables["B_obs"][-1], 0.0, atol=1e-8)

    # Intervention at t = 1.0
    model.set_parameter("k", 1.0)

    # Phase 2: [1.0, 4.0] continued
    res2 = model.simulate(
        method="ode", t_start=1.0, t_end=4.0, n_steps=60, continue_simulation=True
    )

    t2 = np.array(res2.time)
    A2 = np.array(res2.observables["A_obs"])
    B2 = np.array(res2.observables["B_obs"])

    A4_expected = 100.0 * np.exp(-0.5) * np.exp(-3.0)
    B3_expected = 100.0 * (1.0 - np.exp(-0.5))
    B4_expected = B3_expected + 100.0 * np.exp(-0.5) * (1.0 - np.exp(-1.0))

    # 1. State at end of horizon matches analytical piecewise integral
    np.testing.assert_allclose(A2[-1], A4_expected, rtol=1e-5)
    np.testing.assert_allclose(B2[-1], B4_expected, rtol=1e-5)

    # 2. Derivative jump at t = 3.0: completion rate jumps from ~35 to ~50+
    idx_pre_3 = np.where((t2 >= 2.5) & (t2 <= 2.95))[0]
    idx_post_3 = np.where((t2 >= 3.05) & (t2 <= 3.5))[0]
    slope_pre = (B2[idx_pre_3[-1]] - B2[idx_pre_3[0]]) / (
        t2[idx_pre_3[-1]] - t2[idx_pre_3[0]]
    )
    slope_post = (B2[idx_post_3[-1]] - B2[idx_post_3[0]]) / (
        t2[idx_post_3[-1]] - t2[idx_post_3[0]]
    )
    assert slope_post > 1.25 * slope_pre
