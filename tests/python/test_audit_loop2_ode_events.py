from __future__ import annotations

import math
import pytest

import bionetgen._bionetgen_cpp as cpp


def _parse_and_generate(bngl: str):
    model = cpp.parse_string(bngl)
    network = cpp.generate_network(model)
    return model, network


def test_l2_04_01_same_instant_and_delayed_parameter_cascades():
    """L2-04-01: Live event-assigned parameters must not be shadowed by stale history snapshots."""
    bngl_immediate = """
begin model
begin parameters
  p 1
end parameters
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 1
  Y() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Y_obs Y()
end observables
begin functions
  p_view() = p
end functions
begin reaction rules
  X() -> X() + X() 0.1
end reaction rules
begin bng3_events version 1
  event "E_A"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 10
    assignment: p = 10
  end event
  event "E_B"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: false
    priority: 1
    assignment: Y_obs = p
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl_immediate)
    res = cpp.simulate_ode(
        m, n, method="cvode", t_end=2.0, n_steps=4, rtol=1e-10, atol=1e-12
    )
    assert math.isclose(
        res["observables"]["Y_obs"][-1], 10.0, rel_tol=1e-9, abs_tol=1e-9
    )
    # Post-integration function replay must preserve pre-event p=1 at t=0 and post-event p=10 at t=2.
    assert math.isclose(res["functions"]["p_view"][0], 1.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        res["functions"]["p_view"][-1], 10.0, rel_tol=1e-9, abs_tol=1e-9
    )

    bngl_delayed = """
begin model
begin parameters
  p 1
end parameters
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 1
  Y() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Y_obs Y()
end observables
begin reaction rules
  X() -> X() + X() 0.01
end reaction rules
begin bng3_events version 1
  event "E_A"
    trigger: time >= 0.5
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    delay: 0.5
    priority: 10
    assignment: p = 42
  end event
  event "E_B"
    trigger: time >= 0.5
    initial_value: true
    persistent: true
    use_values_from_trigger_time: false
    delay: 0.5
    priority: 1
    assignment: Y_obs = p
  end event
end bng3_events
end model
"""
    m2, n2 = _parse_and_generate(bngl_delayed)
    res2 = cpp.simulate_ode(
        m2, n2, method="cvode", t_end=2.0, n_steps=4, rtol=1e-10, atol=1e-12
    )
    assert math.isclose(
        res2["observables"]["Y_obs"][-1], 42.0, rel_tol=1e-9, abs_tol=1e-9
    )

    bngl_same_instant_prio = """
begin model
begin parameters
  p 1
end parameters
begin molecule types
  X()
  Out()
end molecule types
begin seed species
  X() 0
  Out() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Out_obs Out()
end observables
begin reaction rules
  X() -> X() 0
end reaction rules
begin bng3_events version 1
  event "E_set"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 100
    assignment: p = 20
  end event
  event "E_B"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: X_obs + p
    assignment: Out_obs = 1
  end event
  event "E_C"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 10
    assignment: Out_obs = 2
  end event
end bng3_events
end model
"""
    m3, n3 = _parse_and_generate(bngl_same_instant_prio)
    res3 = cpp.simulate_ode(
        m3, n3, method="cvode", t_end=2.0, n_steps=4, rtol=1e-10, atol=1e-12
    )
    assert math.isclose(
        res3["observables"]["Out_obs"][-1], 2.0, rel_tol=1e-9, abs_tol=1e-9
    )


def test_l2_04_02_parameter_dependent_event_priority():
    """L2-04-02: Event priority depending on an event-mutated parameter must be evaluated dynamically."""
    bngl = """
begin model
begin parameters
  p 1
end parameters
begin molecule types
  X()
  Out()
end molecule types
begin seed species
  X() 1
  Out() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Out_obs Out()
end observables
begin reaction rules
  X() -> X() + X() 0.01
end reaction rules
begin bng3_events version 1
  event "E_set"
    trigger: time >= 0.5
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: p = 20
  end event
  event "E_B"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: p
    assignment: Out_obs = 1
  end event
  event "E_C"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 10
    assignment: Out_obs = 2
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl)
    res = cpp.simulate_ode(
        m, n, method="cvode", t_end=2.0, n_steps=4, rtol=1e-10, atol=1e-12
    )
    # p becomes 20 at t=0.5, so E_B (prio 20) runs before E_C (prio 10) at t=1.0 -> Out = 2.
    assert math.isclose(
        res["observables"]["Out_obs"][-1], 2.0, rel_tol=1e-9, abs_tol=1e-9
    )


def test_l2_04_03_same_instant_false_to_true_retriggering():
    """L2-04-03: Event whose trigger drops false during a cascade must re-trigger on a second rising edge."""
    bngl = """
begin model
begin molecule types
  X()
  C()
  D()
end molecule types
begin seed species
  X() 0
  C() 0
  D() 1
end seed species
begin observables
  Molecules X_obs X()
  Molecules C_obs C()
  Molecules D_obs D()
end observables
begin reaction rules
  D() -> D() + D() 0.01
end reaction rules
begin bng3_events version 1
  event "E_A"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 3
    assignment: X_obs = 10
  end event
  event "E_B"
    trigger: X_obs >= 5.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: false
    priority: 2
    assignment: X_obs = 0
    assignment: C_obs = C_obs + 1
  end event
  event "E_C"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 1
    assignment: X_obs = 10
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl)
    res = cpp.simulate_ode(
        m, n, method="cvode", t_end=2.0, n_steps=4, rtol=1e-10, atol=1e-12
    )
    assert math.isclose(
        res["observables"]["C_obs"][-1], 2.0, rel_tol=1e-9, abs_tol=1e-9
    )
    assert math.isclose(
        res["observables"]["X_obs"][-1], 0.0, rel_tol=1e-9, abs_tol=1e-9
    )


def test_l2_04_04_ida_algebraic_reenforced_between_cascading_events():
    """L2-04-04: IDA must re-enforce algebraic rules after each event in a cascade."""
    bngl = """
begin model
begin molecule types
  X()
  Z()
  Y()
  Trig()
end molecule types
begin seed species
  X() 1
  Z() 2
  Y() 0
  Trig() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Z_obs Z()
  Molecules Y_obs Y()
  Molecules Trig_obs Trig()
end observables
begin reaction rules
  X() -> 0 0.01
end reaction rules
begin bng3_events version 1
  event "E_A"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 10
    assignment: X_obs = 5
  end event
  event "E_B"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: false
    priority: 1
    assignment: Y_obs = Z_obs
  end event
  event "E_C"
    trigger: Z_obs >= 8.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: Trig_obs = 1
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl)
    res = cpp.simulate_ode(
        m,
        n,
        method="cvode",
        t_end=2.0,
        n_steps=4,
        rtol=1e-10,
        atol=1e-12,
        algebraic_rules=[("Z_obs", "Z_obs - 2 * X_obs")],
    )
    assert math.isclose(
        res["observables"]["Y_obs"][-1], 10.0, rel_tol=1e-7, abs_tol=1e-7
    )
    assert math.isclose(
        res["observables"]["Trig_obs"][-1], 1.0, rel_tol=1e-9, abs_tol=1e-9
    )


def test_l2_04_05_delay_only_in_event_delay_enables_dense_history():
    """L2-04-05: delay() appearing only inside event.delay must record dense history."""
    bngl = """
begin model
begin molecule types
  X()
  T_exec()
end molecule types
begin seed species
  X() 0
  T_exec() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules T_exec_obs T_exec()
end observables
begin functions
  dx() = 4.0 * time^3
end functions
begin reaction rules
  0 -> X() dx()
end reaction rules
begin bng3_events version 1
  event "E_only_del"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: false
    delay: delay(X_obs, 0.5)
    assignment: T_exec_obs = time
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl)
    res = cpp.simulate_ode(
        m, n, method="cvode", t_end=2.0, n_steps=2, rtol=1e-10, atol=1e-12
    )
    # X(t) = t^4, so delay(X_obs, 0.5) at t=1.0 is 0.5^4 = 0.0625 -> T_exec = 1.0625.
    assert math.isclose(
        res["observables"]["T_exec_obs"][-1], 1.0625, rel_tol=1e-6, abs_tol=1e-6
    )


def test_l2_04_13_ida_rejects_delay_in_algebraic_residual():
    """L2-04-13: setAlgebraicRules must scan residuals for delay() and fail closed in IDA."""
    bngl = """
begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 0
  Z() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Z_obs Z()
end observables
begin functions
  dx() = 4.0 * time^3
end functions
begin reaction rules
  0 -> X() dx()
end reaction rules
end model
"""
    m, n = _parse_and_generate(bngl)
    with pytest.raises(RuntimeError, match="delayed expressions is not supported"):
        cpp.simulate_ode(
            m,
            n,
            method="cvode",
            t_end=2.0,
            n_steps=2,
            algebraic_rules=[("Z_obs", "Z_obs - delay(X_obs, 0.5)")],
        )


def test_l2_04_07_ida_time_varying_algebraic_rules_with_zero_diff_rhs():
    """L2-04-07: IDA with IDASetSuppressAlg(SUNTRUE) must track time-varying algebraic rules."""
    bngl = """
begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 1
  Z() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Z_obs Z()
end observables
begin reaction rules
  X() -> X() 0
end reaction rules
end model
"""
    cases = [
        ("Z_obs - sin(time)", math.sin(3.0)),
        ("Z_obs - time", 3.0),
        ("Z_obs - exp(time)", math.exp(3.0)),
    ]
    for residual, expected in cases:
        m, n = _parse_and_generate(bngl)
        res = cpp.simulate_ode(
            m,
            n,
            method="cvode",
            t_end=3.0,
            n_steps=15,
            rtol=1e-10,
            atol=1e-12,
            algebraic_rules=[("Z_obs", residual)],
        )
        assert math.isclose(
            res["observables"]["Z_obs"][-1], expected, rel_tol=1e-7, abs_tol=1e-7
        )


def test_l2_04_08_cvode_root_and_pending_event_coincidence():
    """L2-04-08: Root return within machine epsilon of pending delayed event must not hit CV_TOO_CLOSE."""
    bngl = """
begin model
begin molecule types
  X()
  Y()
  T1()
  T2()
end molecule types
begin seed species
  X() 0
  Y() 0
  T1() 0
  T2() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Y_obs Y()
  Molecules T1_obs T1()
  Molecules T2_obs T2()
end observables
begin reaction rules
  0 -> X() 1.0
end reaction rules
begin bng3_events version 1
  event "E_dtrig"
    trigger: delay(X_obs, 0.5) >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: T1_obs = time
    assignment: Y_obs = delay(X_obs, 0.2)
  end event
  event "E_ddel"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: false
    delay: delay(X_obs, 0.5)
    assignment: T2_obs = time
  end event
end bng3_events
end model
"""
    for max_step in (0.5, 1.0, 2.0):
        m, n = _parse_and_generate(bngl)
        res = cpp.simulate_ode(
            m,
            n,
            method="cvode",
            t_end=2.5,
            n_steps=25,
            max_step=max_step,
            rtol=1e-10,
            atol=1e-12,
        )
        assert math.isclose(
            res["observables"]["T1_obs"][-1], 1.5, rel_tol=1e-6, abs_tol=1e-6
        )
        assert math.isclose(
            res["observables"]["T2_obs"][-1], 1.5, rel_tol=1e-6, abs_tol=1e-6
        )
        assert math.isclose(
            res["observables"]["Y_obs"][-1], 1.3, rel_tol=1e-6, abs_tol=1e-6
        )


def test_l2_04_09_event_mutated_compartment_volume_and_scoped_rate():
    """L2-04-09: Event-assigned parameters must dynamically update compartment volumes and scoped rates."""
    bngl_vol = """
begin model
begin parameters
  V 1.0
  kf 1.0
end parameters
begin compartments
  cell 3 V
end compartments
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  @cell:A() 10
  @cell:B() 10
  @cell:C() 0
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  @cell:A() + @cell:B() -> @cell:C() kf
end reaction rules
begin bng3_events version 1
  event "E_vol"
    trigger: time >= 0.5
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: V = 10.0
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl_vol)
    res = cpp.simulate_ode(
        m, n, method="cvode", t_end=1.0, n_steps=10, rtol=1e-10, atol=1e-12
    )
    # Exact: 1/A(0.5) = 1/10 + 0.5/1 = 0.6; 1/A(1.0) = 0.6 + 0.5/10 = 0.65 -> A(1.0) = 1/0.65.
    assert math.isclose(
        res["observables"]["A_obs"][-1], 1.0 / 0.65, rel_tol=1e-6, abs_tol=1e-6
    )

    bngl_scoped = """
begin model
begin parameters
  k0 1.0
end parameters
begin molecule types
  A(s~0~1)
  B()
end molecule types
begin seed species
  A(s~0) 10
  B() 0
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules B_obs B()
end observables
begin functions
  f_loc(x) = k0 * (1 + A0(x))
end functions
begin reaction rules
  %x:A(s~0) -> %x:A(s~0) + B() f_loc(x)
end reaction rules
begin bng3_events version 1
  event "E_k0"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: k0 = 10.0
  end event
end bng3_events
end model
"""
    m2, n2 = _parse_and_generate(bngl_scoped)
    res2 = cpp.simulate_ode(
        m2, n2, method="cvode", t_end=2.0, n_steps=10, rtol=1e-10, atol=1e-12
    )
    # Exact: 10 * 2 * 1.0 * 1.0 + 10 * 2 * 10.0 * 1.0 = 220.0.
    assert math.isclose(
        res2["observables"]["B_obs"][-1], 220.0, rel_tol=1e-6, abs_tol=1e-6
    )


def test_l2_08_06_events_mutating_arrhenius_energy_parameters():
    """L2-08-06: Native bng3_events mutating Arrhenius energy parameters must update ODE and SSA rates."""
    bngl = """
begin model
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
begin bng3_events version 1
  event "flip"
    trigger: time >= 5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: G_P = 2.0
  end event
end bng3_events
end model
"""
    m, n = _parse_and_generate(bngl)
    res_ode = cpp.simulate_ode(
        m, n, method="cvode", t_end=15.0, n_steps=15, rtol=1e-10, atol=1e-12
    )
    eq_before = 1000.0 * math.exp(2.0) / (1.0 + math.exp(2.0))
    eq_after = 1000.0 * math.exp(-2.0) / (1.0 + math.exp(-2.0))
    # At t=4 (index 4), equilibrium is ~880.80; at t=15 (index 15), equilibrium shifts to ~119.20.
    assert math.isclose(
        res_ode["observables"]["AP"][4], eq_before, rel_tol=1e-3, abs_tol=0.5
    )
    assert math.isclose(
        res_ode["observables"]["AP"][-1], eq_after, rel_tol=1e-3, abs_tol=0.5
    )

    m_ssa, n_ssa = _parse_and_generate(bngl)
    res_ssa = cpp.simulate_ssa(m_ssa, n_ssa, t_end=15.0, n_steps=15, seed=42)
    assert res_ssa["observables"]["AP"][4] > 800.0
    assert res_ssa["observables"]["AP"][-1] < 200.0


def test_l2_04_10_non_ida_methods_reject_algebraic_rules():
    """L2-04-10: Euler, RK4, and SSA must reject algebraic_rules instead of silently ignoring them."""
    bngl = """
begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 1
  Z() 2
end seed species
begin observables
  Molecules X_obs X()
  Molecules Z_obs Z()
end observables
begin reaction rules
  0 -> X() 2.0
end reaction rules
end model
"""
    for method in ("euler", "rk4", "ssa"):
        m, n = _parse_and_generate(bngl)
        with pytest.raises(RuntimeError, match="DAE algebraic rules require"):
            cpp.simulate_ode(
                m,
                n,
                method=method,
                t_end=2.0,
                n_steps=10,
                algebraic_rules=[("Z_obs", "Z_obs - 2 * X_obs")],
            )


def test_l2_04_11_euler_rk4_continue_and_max_step_and_step_knots():
    """L2-04-11: Euler and RK4 must honor continue_simulation, max_step, and tfun step knots."""
    bngl_decay = """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  A() -> 0 1.0
end reaction rules
end model
"""
    for method, tol in (("rk4", 1e-6), ("euler", 5e-2)):
        m, n = _parse_and_generate(bngl_decay)
        r1 = cpp.simulate_ode(m, n, method=method, t_start=0.0, t_end=1.0, n_steps=100)
        r2 = cpp.simulate_ode(
            m,
            n,
            method=method,
            t_start=1.0,
            t_end=2.0,
            n_steps=100,
            continue_simulation=True,
        )
        assert math.isclose(
            r2["observables"]["A_obs"][0], r1["observables"]["A_obs"][-1], rel_tol=1e-12
        )
        assert math.isclose(
            r2["observables"]["A_obs"][-1], 100.0 * math.exp(-2.0), rel_tol=tol
        )

    bngl_pulse = """
begin model
begin molecule types
  Y()
end molecule types
begin seed species
  Y() 0
end seed species
begin observables
  Molecules Y_obs Y()
end observables
begin functions
  pulse() = tfun([0.0, 0.5, 0.5005, 1.0], [0.0, 2000.0, 0.0, 0.0], time, method=>"step")
end functions
begin reaction rules
  0 -> Y() pulse()
end reaction rules
end model
"""
    for method in ("euler", "rk4"):
        m, n = _parse_and_generate(bngl_pulse)
        res = cpp.simulate_ode(
            m,
            n,
            method=method,
            t_end=1.0,
            n_steps=10,
            max_step=1e-4,
        )
        assert math.isclose(
            res["observables"]["Y_obs"][-1], 1.0, rel_tol=1e-6, abs_tol=1e-6
        )


def test_l2_04_12_steady_state_does_not_stop_prematurely():
    """L2-04-12: steady_state=True must not stop early on time-varying IDA rules or upcoming events."""
    bngl_ida = """
begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 1
  Z() 1
end seed species
begin observables
  Molecules X_obs X()
  Molecules Z_obs Z()
end observables
begin reaction rules
  X() -> X() 0
end reaction rules
end model
"""
    m, n = _parse_and_generate(bngl_ida)
    res_ida = cpp.simulate_ode(
        m,
        n,
        method="cvode",
        t_end=3.0,
        n_steps=30,
        steady_state=True,
        rtol=1e-10,
        atol=1e-12,
        algebraic_rules=[("Z_obs", "Z_obs - cos(time)")],
    )
    assert math.isclose(res_ida["time"][-1], 3.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        res_ida["observables"]["Z_obs"][-1], math.cos(3.0), rel_tol=1e-6, abs_tol=1e-6
    )

    bngl_event = """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  A() -> 0 1.0
end reaction rules
begin bng3_events version 1
  event "E_pulse"
    trigger: time >= 2.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: A_obs = 10
  end event
end bng3_events
end model
"""
    m2, n2 = _parse_and_generate(bngl_event)
    res_ev = cpp.simulate_ode(
        m2,
        n2,
        method="cvode",
        t_end=3.0,
        n_steps=30,
        steady_state=True,
        rtol=1e-10,
        atol=1e-12,
    )
    assert math.isclose(res_ev["time"][-1], 3.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        res_ev["observables"]["A_obs"][-1],
        10.0 * math.exp(-1.0),
        rel_tol=1e-6,
        abs_tol=1e-6,
    )


def test_l2_04_14_observable_indexed_step_tfun_captures_narrow_pulse():
    """L2-04-14: Observable-indexed tfun(..., obs, method=>'step') must capture narrow step pulses."""
    bngl = """
begin model
begin molecule types
  X()
  Y()
end molecule types
begin seed species
  X() 0
  Y() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Y_obs Y()
end observables
begin functions
  pulse() = tfun([0.0, 0.5, 0.501, 2.0], [0.0, 1000.0, 0.0, 0.0], X_obs, method=>"step")
end functions
begin reaction rules
  0 -> X() 1.0
  0 -> Y() pulse()
end reaction rules
end model
"""
    for n_steps in (20, 2):
        m, n = _parse_and_generate(bngl)
        res = cpp.simulate_ode(
            m,
            n,
            method="cvode",
            t_end=2.0,
            n_steps=n_steps,
            rtol=1e-10,
            atol=1e-12,
        )
        assert math.isclose(
            res["observables"]["Y_obs"][-1], 1.0, rel_tol=1e-5, abs_tol=1e-5
        )


def test_l2_01_03_species_zero_matching_quantifiers():
    """L2-01-03: Species observables with ==0, <2, <=1 quantifiers must count zero-matching species."""
    bngl = """
begin model
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
    m, n = _parse_and_generate(bngl)
    res_ode = cpp.simulate_ode(m, n, method="cvode", t_end=1.0, n_steps=2)
    assert math.isclose(res_ode["observables"]["Sp_B_eq0"][0], 500.0, rel_tol=1e-12)
    assert math.isclose(res_ode["observables"]["Sp_B_lt2"][0], 900.0, rel_tol=1e-12)
    assert math.isclose(res_ode["observables"]["Sp_B_le1"][0], 900.0, rel_tol=1e-12)
    assert math.isclose(res_ode["observables"]["Mol_A_gt0"][0], 200.0, rel_tol=1e-12)

    m2, n2 = _parse_and_generate(bngl)
    res_ssa = cpp.simulate_ssa(m2, n2, t_end=1.0, n_steps=2, seed=42)
    assert math.isclose(res_ssa["observables"]["Sp_B_eq0"][0], 500.0, rel_tol=1e-12)
    assert math.isclose(res_ssa["observables"]["Sp_B_lt2"][0], 900.0, rel_tol=1e-12)
    assert math.isclose(res_ssa["observables"]["Sp_B_le1"][0], 900.0, rel_tol=1e-12)


def test_l2_03_02_count_unique_molecules_and_species_observables():
    """L2-03-02: MoleculesObservables and SpeciesObservables CountUnique must be honored in ODE and SSA."""
    bngl = """
begin model
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
    m, n = _parse_and_generate(bngl)
    res = cpp.simulate_ode(
        m, n, method="cvode", t_end=1.0, n_steps=2, rtol=1e-10, atol=1e-12
    )
    assert math.isclose(res["observables"]["M_Dimer"][0], 100.0, rel_tol=1e-12)
    assert math.isclose(res["observables"]["S_TwoPatt"][0], 100.0, rel_tol=1e-12)
    expected_b = 100.0 * (1.0 - math.exp(-1.0))
    assert math.isclose(
        res["observables"]["B_active"][-1], expected_b, rel_tol=1e-6, abs_tol=1e-6
    )

    m_ssa, n_ssa = _parse_and_generate(bngl)
    res_ssa = cpp.simulate_ssa(m_ssa, n_ssa, t_end=1.0, n_steps=2, seed=42)
    assert math.isclose(res_ssa["observables"]["M_Dimer"][0], 100.0, rel_tol=1e-12)
    assert math.isclose(res_ssa["observables"]["S_TwoPatt"][0], 100.0, rel_tol=1e-12)


def test_l2_05_05_batch_ssa_cpu_welford_variance_stability():
    """L2-05-05: integrateBatchSSA must avoid catastrophic cancellation on large-mean populations."""
    bngl = """
begin model
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
    m, n = _parse_and_generate(bngl)
    res = cpp.simulate_ssa(
        m,
        n,
        t_end=1.0,
        n_steps=2,
        seed=42,
        batch_size=2000,
        batch_gpu_preferred=False,
        batch_gpu_backend="none",
    )
    std_a_t0 = float(res["batch_std_devs"]["obsA"][0])
    std_a_t1 = float(res["batch_std_devs"]["obsA"][-1])
    std_b_t1 = float(res["batch_std_devs"]["obsB"][-1])
    # Deterministic initial condition must have zero std dev.
    assert std_a_t0 == 0.0
    # Exact conservation A + B = 2e7 requires std(A) == std(B).
    assert math.isclose(std_a_t1, std_b_t1, rel_tol=1e-8, abs_tol=1e-8)
    assert 0.8 < std_a_t1 < 1.2
