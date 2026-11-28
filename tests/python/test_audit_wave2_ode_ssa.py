"""Regression tests for Wave 2 audit fixes (OdeIntegrator ODE/DAE/DDE/Events/SSA).

Covers all verified Wave 2 defects in OdeIntegrator.hpp / OdeIntegrator.cpp:
1.  ODE-01 & ODE-10: Multi-constant Sat(k, K1, K2, ...), 1-arg Sat(k), and numeric
    literals / arithmetic expressions in Sat/MM/Hill arguments
2.  ODE-02: Reversible rules with Sat/MM/Hill on forward OR reverse direction
3.  ODE-04: Refresh lastRootValues_ after applyDueEvents in CVODE & IDA
4.  ODE-05: Falling-edge root monitoring for persistent: false events in CVODE & IDA
5.  ODE-06: Simultaneous conjunction (&&) event trigger alongside another event
6.  ODE-07 / EXPR-15: File-backed tfun & print_functions=>1 (including local functions)
7.  SBML-03 & ODE-12: delay(expr, tau) initial-time clamp and small dynamic delay interpolation
8.  ODE-15: setConcentration between continued phases crossing an event threshold
9.  ODE-16: IDA DAE sub-1e-12 span, strict time>0 t=0 preservation, scaled algebraic Jacobian
10. ODE-17: stop_if resolving model functions
11. ODE-19: tfun(..., method=>"step") narrow pulses via CVODE stop-time knots
12. ODE-20: rk4 / euler throw on NaN/Inf blowup and preserve negative states by default
13. ODE-22: Hill(Vmax, Kh, 0) nonnegative substrate on both CompiledRateLaw and Expression paths
14. ODE-23: cvodeStateScale_ bounded on stiff multi-scale linear systems
15. RULEHUB-07 / SSA-17: User parameter named `t` not shadowed or rejected as clock
16. SSA-01: Non-adjacent repeated reactants `A + B + A -> C` combinatorial count
17. SSA-09, SSA-12, SSA-13, SSA-14: Scale-relative SSA time tolerance, negative propensity
    clamping, batch SSA max_sim_steps mass conservation & output_step_interval guard,
    unseeded batch SSA randomness
18. PERF-08 & PERF-11: Fenwick-tree SSA (>64 reactions, drift-free) and indexed function lookup
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as _cpp


def _parse_and_sim(
    source: str,
    *,
    method: str = "ode",
    t_start: float = 0.0,
    t_end: float = 1.0,
    n_steps: int = 10,
    rtol: float = 1e-8,
    atol: float = 1e-12,
    **kwargs,
):
    model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    return model.simulate(
        method=method,
        t_start=t_start,
        t_end=t_end,
        n_steps=n_steps,
        rtol=rtol,
        atol=atol,
        **kwargs,
    )


def _read_gdat(path: Path) -> tuple[list[str], np.ndarray]:
    lines = [
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    header = lines[0].lstrip("#").split()
    data = np.array(
        [[float(tok) for tok in ln.split()] for ln in lines[1:]], dtype=float
    )
    return header, data


# ---------------------------------------------------------------------------
# 1. ODE-01 & ODE-10: Multi-constant Sat, 1-arg Sat, literals & expressions
# ---------------------------------------------------------------------------


def test_ode01_sat_multi_constant_heterodimer_and_homodimer():
    hetero = """begin model
begin parameters
  k 10.0
  K1 5.0
  K2 20.0
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 10
  B() 20
  C() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
  Molecules C_obs C()
end observables
begin reaction rules
  A() + B() -> C() Sat(k, K1, K2)
end reaction rules
end model
"""
    res = _parse_and_sim(hetero, t_end=2.0, n_steps=10, rtol=1e-10, atol=1e-12)
    # Canonical BNG2 / exact ODE values
    assert res.observables["A_obs"][-1] == pytest.approx(4.63955431, rel=1e-5)
    assert res.observables["B_obs"][-1] == pytest.approx(14.63955431, rel=1e-5)
    assert res.observables["C_obs"][-1] == pytest.approx(5.36044569, rel=1e-5)

    homo = """begin model
begin parameters
  k 10.0
  K1 5.0
  K2 20.0
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
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() + A() -> B() Sat(k, K1, K2)
end reaction rules
end model
"""
    res_h = _parse_and_sim(homo, t_end=2.0, n_steps=10, rtol=1e-10, atol=1e-12)
    # Canonical BNG2.pl oracle (0.5*Sat k K1 K2): A(2) = 13.13199803419, B(2) = 3.434000982905
    assert res_h.observables["A_obs"][-1] == pytest.approx(13.13199803419, rel=1e-5)
    assert res_h.observables["B_obs"][-1] == pytest.approx(3.434000982905, rel=1e-5)


def test_ode10_sat_one_arg_and_literals_and_expressions():
    src = """begin model
begin parameters
  kcat 5.0
  Km 10.0
end parameters
begin molecule types
  S1()
  P1()
  S2()
  P2()
  S3()
  P3()
  S4()
  E4()
  P4()
  S5()
  P5()
end molecule types
begin seed species
  S1() 100
  P1() 0
  S2() 100
  P2() 0
  S3() 100
  P3() 0
  S4() 100
  E4() 10
  P4() 0
  S5() 100
  P5() 0
end seed species
begin observables
  Molecules P1_obs P1()
  Molecules P2_obs P2()
  Molecules P3_obs P3()
  Molecules P4_obs P4()
  Molecules P5_obs P5()
end observables
begin reaction rules
  S1() -> P1() Sat(kcat)
  S2() -> P2() Sat(10.0, 5.0)
  S3() -> P3() Sat(2*kcat, Km/2)
  S4() + E4() -> P4() + E4() MM(2*kcat, Km/2)
  S5() -> P5() Hill(10.0, 5.0, 2)
end reaction rules
end model
"""
    res = _parse_and_sim(src, t_end=2.0, n_steps=20, rtol=1e-10, atol=1e-12)
    # 1-arg Sat(kcat): zeroth-order rate = kcat = 5 -> P1(2) = 10.0
    assert res.observables["P1_obs"][-1] == pytest.approx(10.0, rel=1e-6)
    # Sat(10.0, 5.0) == Sat(2*kcat, Km/2)
    assert res.observables["P2_obs"][-1] > 15.0
    assert res.observables["P2_obs"][-1] == pytest.approx(
        res.observables["P3_obs"][-1], rel=1e-6
    )
    # MM(2*kcat, Km/2) active (not silently zeroed)
    assert res.observables["P4_obs"][-1] > 50.0
    # Hill(10.0, 5.0, 2) active (not silently zeroed)
    assert res.observables["P5_obs"][-1] > 15.0


# ---------------------------------------------------------------------------
# 2. ODE-02: Reversible rules with Sat / MM / Hill on forward or reverse
# ---------------------------------------------------------------------------


def test_ode02_reversible_sat_mm_both_directions():
    # Case 1: MM forward, elementary reverse
    m1 = """begin model
begin parameters
  kcat 1.0
  Km 10.0
  kr 0.05
end parameters
begin molecule types
  S()
  E()
  P()
end molecule types
begin seed species
  S() 100
  E() 10
  P() 50
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  R1: S() + E() <-> P() + E() MM(kcat, Km), kr
end reaction rules
end model
"""
    r1 = _parse_and_sim(m1, t_end=5.0, n_steps=25, rtol=1e-10, atol=1e-12)
    assert r1.observables["S_obs"][-1] == pytest.approx(129.00490748, rel=1e-4)
    assert r1.observables["P_obs"][-1] == pytest.approx(20.99509252, rel=1e-4)

    # Case 2: Sat forward, 1-char elementary reverse `k` (previously crashed with std::out_of_range)
    m2 = """begin model
begin parameters
  kcat 5.0
  Km 10.0
  k 0.1
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 100
  P() 50
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  R1: S() <-> P() Sat(kcat, Km), k
end reaction rules
end model
"""
    r2 = _parse_and_sim(m2, t_end=5.0, n_steps=25, rtol=1e-10, atol=1e-12)
    assert r2.observables["S_obs"][-1] == pytest.approx(101.77185833, rel=1e-4)
    assert r2.observables["P_obs"][-1] == pytest.approx(48.22814167, rel=1e-4)

    # Case 3: Elementary forward, Sat reverse
    m3 = """begin model
begin parameters
  kf 0.1
  kcat 5.0
  Km 10.0
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 100
  P() 50
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  R1: S() <-> P() kf, Sat(kcat, Km)
end reaction rules
end model
"""
    r3 = _parse_and_sim(m3, t_end=5.0, n_steps=25, rtol=1e-10, atol=1e-12)
    assert r3.observables["S_obs"][-1] == pytest.approx(77.61513897, rel=1e-4)
    assert r3.observables["P_obs"][-1] == pytest.approx(72.38486103, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. ODE-04: Stale lastRootValues_ must not re-fire discrete events
# ---------------------------------------------------------------------------


def test_ode04_no_spurious_event_refire_cvode_and_ida():
    src = """begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  X()
  C()
  D()
  Z()
end molecule types
begin seed species
  X() 0
  C() 0
  D() 0
  Z() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules C_obs C()
  Molecules D_obs D()
  Molecules Z_obs Z()
end observables
begin reaction rules
  0 -> D() k
end reaction rules
begin bng3_events version 1
  event "E_A"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: X_obs = 10
  end event
  event "E_B"
    trigger: X_obs >= 5.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: C_obs = C_obs + 1
  end event
  event "E_C"
    trigger: time >= 2.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: D_obs = D_obs + 100
  end event
end bng3_events
end model
"""
    # CVODE
    res = _parse_and_sim(src, t_end=3.0, n_steps=6)
    assert res.observables["C_obs"][-1] == pytest.approx(1.0, abs=1e-9)
    assert res.observables["D_obs"][-1] == pytest.approx(100.03, rel=1e-5)

    # IDA (DAE)
    model = _cpp.parse_string(src)
    net = _cpp.generate_network(model)
    res_ida = _cpp.simulate_ode(
        model,
        net,
        t_end=3.0,
        n_steps=6,
        algebraic_rules=[("Z_obs", "Z_obs - 2 * X_obs")],
    )
    assert res_ida["observables"]["C_obs"][-1] == pytest.approx(1.0, abs=1e-9)
    assert res_ida["observables"]["Z_obs"][-1] == pytest.approx(20.0, rel=1e-5)


# ---------------------------------------------------------------------------
# 4. ODE-05: Non-persistent events cancel on continuous falling edges
# ---------------------------------------------------------------------------


def test_ode05_nonpersistent_continuous_falling_edge_cancels_delayed_event():
    src = """begin model
begin parameters
  pi 3.141592653589793
end parameters
begin molecule types
  X()
  Y()
  Fired()
end molecule types
begin seed species
  X() 0
  Y() 0
  Fired() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Y_obs Y()
  Molecules F_obs Fired()
end observables
begin functions
  rx() = 5 * (1 + cos(2 * pi * time))
end functions
begin reaction rules
  0 -> X() rx()
  0 -> Y() 5
end reaction rules
begin bng3_events version 1
  event "np_osc"
    trigger: X_obs - Y_obs >= 0.5
    initial_value: true
    persistent: false
    use_values_from_trigger_time: true
    delay: 1.1
    assignment: F_obs = F_obs + 1
  end event
end bng3_events
end model
"""
    res = _parse_and_sim(src, t_end=1.5, n_steps=15, rtol=1e-10, atol=1e-12)
    assert np.allclose(res.observables["F_obs"], 0.0, atol=1e-9)


# ---------------------------------------------------------------------------
# 5. ODE-06: Simultaneous conjunction (&&) event alongside another event
# ---------------------------------------------------------------------------


def test_ode06_simultaneous_conjunction_event_fires():
    src = """begin model
begin molecule types
  X()
  Y()
  A()
  B()
  Z()
end molecule types
begin seed species
  X() 0
  Y() 0
  A() 0
  B() 0
  Z() 0
end seed species
begin observables
  Molecules X_obs X()
  Molecules Y_obs Y()
  Molecules A_obs A()
  Molecules B_obs B()
  Molecules Z_obs Z()
end observables
begin reaction rules
  0 -> X() 1.0
  0 -> Y() 1.0
end reaction rules
begin bng3_events version 1
  event "E_A"
    trigger: time >= 1.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 10
    assignment: A_obs = 1
    assignment: X_obs = 0
  end event
  event "E_B"
    trigger: X_obs >= 1.0 && Y_obs >= 0.5
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    priority: 1
    assignment: B_obs = 1
  end event
end bng3_events
end model
"""
    # CVODE
    res = _parse_and_sim(src, t_end=1.5, n_steps=3, rtol=1e-10, atol=1e-12)
    assert res.observables["A_obs"][-1] == pytest.approx(1.0, abs=1e-9)
    assert res.observables["B_obs"][-1] == pytest.approx(1.0, abs=1e-9)

    # IDA
    model = _cpp.parse_string(src)
    net = _cpp.generate_network(model)
    res_ida = _cpp.simulate_ode(
        model,
        net,
        t_end=1.5,
        n_steps=3,
        rtol=1e-10,
        atol=1e-12,
        algebraic_rules=[("Z_obs", "Z_obs - Y_obs")],
    )
    assert res_ida["observables"]["A_obs"][-1] == pytest.approx(1.0, abs=1e-9)
    assert res_ida["observables"]["B_obs"][-1] == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 6. ODE-07 / EXPR-15: File-backed tfun & print_functions=>1 with local funcs
# ---------------------------------------------------------------------------


def test_ode07_expr15_file_tfun_and_print_functions_skips_arg_functions(tmp_path: Path):
    (tmp_path / "drive.tfun").write_text(
        "# time val\n0 1\n1 3\n2 5\n", encoding="utf-8"
    )
    bngl = tmp_path / "tfun_and_local.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 0
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin functions
  f_drive() = tfun("drive.tfun", time)
  scale_arg(x) = 2 * x
end functions
begin reaction rules
  0 -> A() f_drive()
  0 -> B() tfun("drive.tfun", time)
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>2, n_steps=>4, print_functions=>1})
""",
        encoding="utf-8",
    )
    model = _cpp.parse_file(str(bngl))
    _cpp.execute(model, str(bngl))
    header, data = _read_gdat(tmp_path / "tfun_and_local.gdat")
    assert "f_drive" in header
    assert "scale_arg" not in header
    a_idx = header.index("A_obs")
    b_idx = header.index("B_obs")
    f_idx = header.index("f_drive")
    assert data[-1, a_idx] == pytest.approx(6.0, rel=1e-4)
    assert data[-1, b_idx] == pytest.approx(6.0, rel=1e-4)
    assert data[-1, f_idx] == pytest.approx(5.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 7. SBML-03 & ODE-12: delay(expr, tau) clamping at t < tau & small dynamic tau
# ---------------------------------------------------------------------------


def test_sbml03_delay_clamps_time_to_initial_time():
    src = """begin model
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 10
  B() 0
  C() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
  Molecules C_obs C()
end observables
begin functions
  f_time() = 2 + time
  conc_a() = A_obs / (1 + time)
  r_b() = delay(f_time(), 1.0)
  r_c() = delay(conc_a(), 1.0)
end functions
begin reaction rules
  0 -> B() r_b()
  0 -> C() r_c()
end reaction rules
end model
"""
    res = _parse_and_sim(src, t_end=3.0, n_steps=30, rtol=1e-9, atol=1e-11)
    # delay(2 + time, 1) = 2 on [0, 1], 1 + t on [1, 3]
    # B(1) = 2.0, B(2) = 2 + 2.5 = 4.5, B(3) = 2 + 6.0 = 8.0
    assert res.observables["B_obs"][10] == pytest.approx(2.0, rel=1e-5)
    assert res.observables["B_obs"][20] == pytest.approx(4.5, rel=1e-5)
    assert res.observables["B_obs"][-1] == pytest.approx(8.0, rel=1e-5)
    # delay(10 / (1 + time), 1) = 10 on [0, 1], 10/t on [1, 3] => C(3) = 10 + 10*ln(3)
    assert res.observables["C_obs"][-1] == pytest.approx(
        10.0 + 10.0 * math.log(3.0), rel=1e-4
    )


def test_ode12_small_dynamic_delay_interpolates_accurately():
    src = """begin model
begin molecule types
  X()
end molecule types
begin seed species
  X() 1.0
end seed species
begin observables
  Molecules X_obs X()
end observables
begin functions
  f_dyn() = 2.0 * delay(X_obs, 0.0001 + 1e-6 * time)
end functions
begin reaction rules
  0 -> X() f_dyn()
end reaction rules
end model
"""
    res_default = _parse_and_sim(src, t_end=5.0, n_steps=1, rtol=1e-8, atol=1e-8)
    # Fine-step reference: X(5.0) ~= 21981.37329489
    assert res_default.observables["X_obs"][-1] == pytest.approx(21981.3733, rel=1e-4)


# ---------------------------------------------------------------------------
# 8. ODE-15, 16, 17, 19, 20, 22, 23
# ---------------------------------------------------------------------------


def test_ode15_continue_setconcentration_triggers_event(tmp_path: Path):
    bngl = tmp_path / "cont_setconc_event.bngl"
    bngl.write_text(
        """begin model
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
begin reaction rules
  0 -> X() 0.1
end reaction rules
begin bng3_events version 1
  event "e_x"
    trigger: X_obs >= 5.0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: Y_obs = 99
  end event
end bng3_events
end model
simulate({method=>"ode", t_end=>1, n_steps=>2})
setConcentration("X()", 10.0)
simulate({method=>"ode", t_end=>2, n_steps=>2, continue=>1})
""",
        encoding="utf-8",
    )
    model = _cpp.parse_file(str(bngl))
    _cpp.execute(model, str(bngl))
    header, data = _read_gdat(tmp_path / "cont_setconc_event.gdat")
    y_idx = header.index("Y_obs")
    assert data[-1, y_idx] == pytest.approx(99.0, abs=1e-6)


def test_ode16_ida_tiny_span_strict_t0_and_scaled_constraint():
    # Sub-1e-12 span
    m_tiny = _cpp.parse_string("""begin model
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
begin reaction rules
  0 -> X() 1e13
end reaction rules
end model
""")
    n_tiny = _cpp.generate_network(m_tiny)
    res_tiny = _cpp.simulate_ode(
        m_tiny,
        n_tiny,
        t_end=5e-13,
        n_steps=5,
        algebraic_rules=[("Z_obs", "Z_obs - 2 * X_obs")],
    )
    assert res_tiny["observables"]["X_obs"][-1] == pytest.approx(5.0, rel=1e-5)
    assert res_tiny["observables"]["Z_obs"][-1] == pytest.approx(10.0, rel=1e-5)

    # Strict time > 0 event must preserve t = 0 output state
    m_strict = _cpp.parse_string("""begin model
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
begin bng3_events version 1
  event "e0"
    trigger: time > 0
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: X_obs = 0
  end event
end bng3_events
end model
""")
    n_strict = _cpp.generate_network(m_strict)
    res_strict = _cpp.simulate_ode(
        m_strict,
        n_strict,
        t_end=1.0,
        n_steps=2,
        algebraic_rules=[("Z_obs", "Z_obs - 2 * X_obs")],
    )
    assert res_strict["observables"]["X_obs"][0] == pytest.approx(10.0, abs=1e-9)
    assert res_strict["observables"]["Z_obs"][0] == pytest.approx(20.0, abs=1e-9)
    assert res_strict["observables"]["X_obs"][-1] == pytest.approx(0.0, abs=1e-9)
    assert res_strict["observables"]["Z_obs"][-1] == pytest.approx(0.0, abs=1e-9)

    # Small-scaled nonsingular constraint 1e-15 * (Z - 2*X) = 0
    m_scaled = _cpp.parse_string("""begin model
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 10
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
""")
    n_scaled = _cpp.generate_network(m_scaled)
    res_scaled = _cpp.simulate_ode(
        m_scaled,
        n_scaled,
        t_end=1.0,
        n_steps=2,
        atol=1e-18,
        algebraic_rules=[("Z_obs", "1e-15 * (Z_obs - 2 * X_obs)")],
    )
    assert res_scaled["observables"]["Z_obs"][-1] == pytest.approx(20.0, rel=1e-5)


def test_ode17_stop_if_resolves_model_functions():
    src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_obs A()
end observables
begin functions
  frac() = A_obs / 100
end functions
begin reaction rules
  A() -> 0 1.0
end reaction rules
end model
"""
    res = _parse_and_sim(src, t_end=5.0, n_steps=50, stop_if="frac() < 0.5")
    assert res.time[-1] == pytest.approx(0.7, abs=1e-9)
    assert res.observables["A_obs"][-1] == pytest.approx(
        100.0 * math.exp(-0.7), rel=1e-4
    )


def test_ode19_tfun_step_narrow_pulse_not_skipped():
    src = """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules A_obs A()
end observables
begin functions
  pulse() = tfun([0, 1.0, 1.01, 2.0], [0, 1000, 0, 0], time, method=>"step")
end functions
begin reaction rules
  0 -> A() pulse()
end reaction rules
end model
"""
    res = _parse_and_sim(src, t_end=2.0, n_steps=4, rtol=1e-10, atol=1e-12)
    assert res.observables["A_obs"][-1] == pytest.approx(10.0, rel=1e-5)


def test_ode20_rk4_and_euler_blowup_throws_and_negative_preserved():
    stiff = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() <-> B() 1e6, 1e6
end reaction rules
end model
"""
    m_stiff = _cpp.parse_string(stiff)
    n_stiff = _cpp.generate_network(m_stiff)
    with pytest.raises(RuntimeError, match="non-finite"):
        _cpp.simulate_ode(m_stiff, n_stiff, method="rk4", t_end=1.0, n_steps=1)

    neg = """begin model
begin molecule types
  X()
end molecule types
begin seed species
  X() 1
end seed species
begin observables
  Molecules X_obs X()
end observables
begin reaction rules
  0 -> X() -2
end reaction rules
end model
"""
    m_neg = _cpp.parse_string(neg)
    n_neg = _cpp.generate_network(m_neg)
    for meth in ("euler", "rk4"):
        r = _cpp.simulate_ode(m_neg, n_neg, method=meth, t_end=2.0, n_steps=10)
        assert r["observables"]["X_obs"][-1] == pytest.approx(-3.0, rel=1e-6)


def test_ode22_hill_zero_exponent_nonnegative_with_and_without_delay():
    # With delay in model so ODE exercises Expression::evaluate fallback path too
    src = """begin model
begin parameters
  Vmax 10.0
  Kh 5.0
  n 0.0
end parameters
begin molecule types
  S()
  P()
  D()
end molecule types
begin seed species
  S() 10
  P() 0
  D() 1
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
  Molecules D_obs D()
end observables
begin functions
  d_rate() = 0.0 * delay(D_obs, 0.5)
end functions
begin reaction rules
  S() -> P() Hill(Vmax, Kh, n)
  0 -> D() d_rate()
end reaction rules
end model
"""
    res = _parse_and_sim(src, t_end=5.0, n_steps=50)
    assert float(np.min(res.observables["S_obs"])) >= -1e-6


def test_ode23_cvode_state_scale_stiff_conservation():
    src = """begin model
begin molecule types
  A()
  B()
  C()
  D()
end molecule types
begin seed species
  A() 1
  B() 0
  C() 1
  D() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
  Molecules C_obs C()
  Molecules D_obs D()
end observables
begin reaction rules
  A() <-> B() 1e12, 1e12
  C() -> D() 1e-10
end reaction rules
end model
"""
    res = _parse_and_sim(src, t_end=1e10, n_steps=10, rtol=1e-10, atol=1e-12)
    a_end = res.observables["A_obs"][-1]
    b_end = res.observables["B_obs"][-1]
    assert a_end == pytest.approx(0.5, abs=1e-6)
    assert b_end == pytest.approx(0.5, abs=1e-6)
    assert (a_end + b_end) == pytest.approx(1.0, abs=1e-6)
    assert res.observables["C_obs"][-1] == pytest.approx(math.exp(-1.0), rel=1e-6)


# ---------------------------------------------------------------------------
# 9. RULEHUB-07 / SSA-17: User parameter named `t`
# ---------------------------------------------------------------------------


def test_rulehub07_ssa17_user_parameter_t_not_shadowed_or_rejected():
    src = """begin model
begin parameters
  t 2.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules A_obs A()
end observables
begin functions
  rate_f() = t
end functions
begin reaction rules
  0 -> A() rate_f()
end reaction rules
end model
"""
    res_ode = _parse_and_sim(src, method="ode", t_end=5.0, n_steps=5)
    # dA/dt = 2.0 -> A(5) = 10.0 (not 12.5 from shadowing with clock time)
    assert res_ode.observables["A_obs"][-1] == pytest.approx(10.0, rel=1e-6)

    # SSA must NOT reject constant user parameter `t` as time-dependent
    res_ssa = _parse_and_sim(src, method="ssa", t_end=5.0, n_steps=5, seed=42)
    assert res_ssa.observables["A_obs"][-1] >= 0.0


# ---------------------------------------------------------------------------
# 10. SSA-01: Non-adjacent identical reactants A + B + A -> C
# ---------------------------------------------------------------------------


def test_ssa01_non_adjacent_identical_reactants_conserve_mass():
    src = """begin model
begin parameters
  k 1.0
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
    for seed in (1, 2, 3):
        res = _parse_and_sim(src, method="ssa", t_end=10.0, n_steps=5, seed=seed)
        assert res.observables["Atot"][-1] == 1.0
        assert res.observables["Btot"][-1] == 1.0
        assert res.observables["Ctot"][-1] == 0.0


# ---------------------------------------------------------------------------
# 11. SSA-09, SSA-12, SSA-13, SSA-14
# ---------------------------------------------------------------------------


def test_ssa09_fast_timescale_not_flat():
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
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() 2e12
end reaction rules
end model
"""
    res = _parse_and_sim(src, method="ssa", t_end=1e-12, n_steps=10, seed=1)
    # Exact E[A(1e-12)] = 100 * exp(-2) ~= 13.53; must not stay flat at 100
    assert res.observables["A_obs"][-1] < 50.0
    assert res.observables["A_obs"][-1] + res.observables["B_obs"][-1] == 100.0


def test_ssa12_negative_propensity_clamped_not_corrupting_other_channels():
    src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 0
  B() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin functions
  f_neg() = Atot - 15
end functions
begin reaction rules
  0 -> A() 10.0
  0 -> B() f_neg()
end reaction rules
end model
"""
    res = _parse_and_sim(
        src,
        method="ssa",
        t_end=5.0,
        n_steps=5,
        seed=7,
        batch_size=100,
        batch_gpu_preferred=False,
    )
    # Exact E[A(5)] = 50.0 (previously halted at 0.0!)
    assert res.observables["Atot"][-1] == pytest.approx(50.0, rel=0.15)
    assert res.observables["Btot"][-1] > 50.0


def test_ssa13_batch_ssa_max_sim_steps_conserves_mass_and_rejects_output_step_interval():
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
    res = _parse_and_sim(
        src,
        method="ssa",
        t_end=5.0,
        n_steps=10,
        seed=42,
        batch_size=20,
        batch_gpu_preferred=False,
        max_sim_steps=20,
    )
    totals = res.observables["Atot"] + res.observables["Btot"]
    assert np.allclose(totals, 100.0, atol=1e-9)
    assert res.observables["Atot"][-1] == pytest.approx(80.0, abs=1e-9)

    model = _cpp.parse_string(src)
    net = _cpp.generate_network(model)
    with pytest.raises((ValueError, RuntimeError), match="output_step_interval"):
        _cpp.simulate_ssa(
            model,
            net,
            t_end=5.0,
            n_steps=10,
            seed=42,
            batch_size=10,
            output_step_interval=5,
        )


def test_ssa14_unseeded_batch_ssa_produces_distinct_ensembles():
    src = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 200
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
    r1 = _parse_and_sim(
        src,
        method="ssa",
        t_end=1.0,
        n_steps=5,
        seed=0,
        batch_size=32,
        batch_gpu_preferred=False,
    )
    r2 = _parse_and_sim(
        src,
        method="ssa",
        t_end=1.0,
        n_steps=5,
        seed=0,
        batch_size=32,
        batch_gpu_preferred=False,
    )
    assert not np.array_equal(r1.observables["Atot"], r2.observables["Atot"])


# ---------------------------------------------------------------------------
# 12. PERF-08 & PERF-11: Fenwick-tree SSA (>64 rxns) & O(1) function lookup
# ---------------------------------------------------------------------------


def test_perf08_fenwick_ssa_accuracy_and_no_slow_channel_starvation():
    # > 64 reactions so OdeIntegrator::integrateSSA uses the Fenwick tree path,
    # with one fast channel (1e6) emptying next to a slow channel (1e-7) over t_end=1e8
    lines = [
        "begin model",
        "begin molecule types",
        "  A()",
        "  B()",
        "  C()",
        "  D()",
    ]
    n_dormant = 80
    for i in range(n_dormant):
        lines.append(f"  Z{i}()")
    lines += [
        "end molecule types",
        "begin seed species",
        "  A() 100",
        "  B() 100",
        "  C() 0",
        "  D() 0",
    ]
    for i in range(n_dormant):
        lines.append(f"  Z{i}() 0")
    lines += [
        "end seed species",
        "begin observables",
        "  Molecules Ctot C()",
        "  Molecules Dtot D()",
        "end observables",
        "begin reaction rules",
        "  A() + B() -> C() 1e6",
        "  0 -> D() 1e-7",
    ]
    for i in range(n_dormant):
        lines.append(f"  Z{i}() -> 0 1.0")
    lines += ["end reaction rules", "end model"]
    src = "\n".join(lines) + "\n"

    d_counts = []
    for seed in range(1, 11):
        res = _parse_and_sim(src, method="ssa", t_end=1e8, n_steps=1, seed=seed)
        assert res.observables["Ctot"][-1] == 100.0
        d_counts.append(float(res.observables["Dtot"][-1]))
    # Exact D ~ Poisson(10.0); mean across 10 seeds must be clearly nonzero (not starved at 0!)
    assert sum(d_counts) > 30.0


def test_perf11_indexed_function_lookup_matches_inline_ode():
    n_rxns = 50
    mol_lines = [f"  S{i}()" for i in range(n_rxns)]
    seed_lines = [f"  S{i}() 10.0" for i in range(n_rxns)]
    obs_lines = ["  Molecules S0_obs S0()"]
    func_lines = [f"  f{i}() = 1.0 / (1.0 + 0.05 * S0_obs)" for i in range(n_rxns)]
    rule_func = [f"  S{i}() -> 0 f{i}()" for i in range(n_rxns)]
    rule_inline = [f"  S{i}() -> 0 1.0 / (1.0 + 0.05 * S0_obs)" for i in range(n_rxns)]

    def build(funcs, rules):
        return (
            "\n".join(
                [
                    "begin model",
                    "begin molecule types",
                    *mol_lines,
                    "end molecule types",
                    "begin seed species",
                    *seed_lines,
                    "end seed species",
                    "begin observables",
                    *obs_lines,
                    "end observables",
                    "begin functions",
                    *funcs,
                    "end functions",
                    "begin reaction rules",
                    *rules,
                    "end reaction rules",
                    "end model",
                ]
            )
            + "\n"
        )

    r_func = _parse_and_sim(build(func_lines, rule_func), t_end=2.0, n_steps=10)
    r_inline = _parse_and_sim(build([], rule_inline), t_end=2.0, n_steps=10)
    assert np.allclose(
        r_func.observables["S0_obs"],
        r_inline.observables["S0_obs"],
        rtol=1e-6,
        atol=1e-9,
    )
