"""Qualification and regression tests for events changing parameters used by algebraic constraints.

Semantics & Oracles:
--------------------
When an event changes a static parameter `p` at time `t_event`:
1. For all time points t < t_event, any algebraic constraint or function S(t)
   depending on `p` must evaluate using the pre-event parameter value p_0.
2. For all time points t >= t_event, S(t) must evaluate using the post-event
   parameter value p_1.
3. The oracle is an independently derived closed-form analytic law for a nonlinearly
   decaying species dA/dt = -2 A^2, A(0) = 10 -> A(t) = 10 / (1 + 20t).
   The event threshold A < 5 is crossed exactly at t* = 0.05.
"""

from __future__ import annotations

import numpy as np
import pytest

import bionetgen
from bionetgen.model import _cpp


def _analytic_A(t: float) -> float:
    """Exact solution of dA/dt = -2 A^2 with A(0) = 10."""
    return 10.0 / (1.0 + 20.0 * t)


def _make_model_bngl(
    p0: float,
    p1: float,
    thresh: float = 5.0,
    delay: float = 0.0,
) -> str:
    delay_str = f"    delay: {delay}\n" if delay > 0.0 else ""
    return f"""
begin model
begin parameters
  p {p0}
  thresh {thresh}
end parameters
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
begin functions
  S() = p
  doubled_S() = 2 * S()
  coupled_S() = p + A_obs
end functions
begin reaction rules
  r1: A() + A() -> B() 1 TotalRate
end reaction rules
begin bng3_events version 1
  event "ev1"
    trigger: A_obs < thresh
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
{delay_str}    assignment: p = {p1}
  end event
end bng3_events
end model
"""


@pytest.mark.parametrize(
    ("p0", "p1"),
    [
        (1.0, 5.0),
        (2.0, 10.0),
        (0.5, 2.5),
    ],
)
def test_ordinary_event_parameter_algebraic_constraint(p0: float, p1: float):
    """Ordinary case: Event assignment updates parameter used in algebraic function S() = p."""
    bngl = _make_model_bngl(p0=p0, p1=p1, thresh=5.0)
    model = bionetgen.BioNetGenModel(_cpp.parse_string(bngl))

    # Analytical event crossing time: A(t*) = 5 -> t* = 0.05
    t_event = 0.05
    sim = model.simulate(method="ode", t_start=0.0, t_end=1.0, n_steps=5)

    time_pts = sim.time
    # Time points are [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert time_pts[0] == 0.0
    assert time_pts[1] == pytest.approx(0.2)

    # 1. Independent oracle check for continuous state A(t)
    for t_val, a_sim in zip(time_pts, sim.observables["A_obs"]):
        a_exact = _analytic_A(t_val)
        assert a_sim == pytest.approx(a_exact, rel=1e-3, abs=1e-3)

    # 2. Algebraic constraint S() = p:
    # At t=0 (< t_event=0.05), S must equal p0 (pre-event value).
    # At t>=0.2 (> t_event=0.05), S must equal p1 (post-event value).
    s_vals = sim.functions["S"]
    assert s_vals[0] == pytest.approx(p0, rel=1e-6)
    for s_post in s_vals[1:]:
        assert s_post == pytest.approx(p1, rel=1e-6)


def test_boundary_delayed_event_parameter_preserves_prehistory():
    """Boundary case: Event with delay triggers at t=0.05 but executes at t=0.15.

    Prehistory must be preserved for all times t < 0.15.
    """
    bngl = _make_model_bngl(p0=1.0, p1=5.0, thresh=5.0, delay=0.1)
    model = bionetgen.BioNetGenModel(_cpp.parse_string(bngl))

    # Simulation with points [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    sim = model.simulate(method="ode", t_start=0.0, t_end=0.5, n_steps=5)
    time_pts = sim.time
    s_vals = sim.functions["S"]

    # At t = 0.0 and t = 0.1 (< 0.15), event has not executed yet: S == 1.0
    assert time_pts[0] == pytest.approx(0.0)
    assert s_vals[0] == pytest.approx(1.0, rel=1e-6)
    assert time_pts[1] == pytest.approx(0.1)
    assert s_vals[1] == pytest.approx(1.0, rel=1e-6)

    # At t >= 0.2 (> 0.15), event has executed: S == 5.0
    for s_post in s_vals[2:]:
        assert s_post == pytest.approx(5.0, rel=1e-6)


def test_interaction_stale_state_coupled_algebraic_functions():
    """Interaction case: Coupled algebraic expressions reading the event-assigned parameter.

    Verifies that zero-argument result functions, linear multiples, and state-coupled
    expressions all evaluate with historical parameter state without stale state leakage.
    """
    bngl = _make_model_bngl(p0=1.0, p1=5.0, thresh=5.0)
    model = bionetgen.BioNetGenModel(_cpp.parse_string(bngl))
    sim = model.simulate(method="ode", t_start=0.0, t_end=1.0, n_steps=5)

    s_vals = sim.functions["S"]
    doubled_s = sim.functions["doubled_S"]
    coupled_s = sim.functions["coupled_S"]
    a_obs = sim.observables["A_obs"]

    # At t = 0: p=1.0, A(0)=10.0
    assert s_vals[0] == pytest.approx(1.0, rel=1e-6)
    assert doubled_s[0] == pytest.approx(2.0, rel=1e-6)
    assert coupled_s[0] == pytest.approx(1.0 + a_obs[0], rel=1e-6)

    # At t >= 0.2: p=5.0
    for i in range(1, len(s_vals)):
        assert s_vals[i] == pytest.approx(5.0, rel=1e-6)
        assert doubled_s[i] == pytest.approx(10.0, rel=1e-6)
        assert coupled_s[i] == pytest.approx(5.0 + a_obs[i], rel=1e-6)


def test_native_ida_algebraic_residual_parameter_interaction():
    """DAE interaction: Implicit algebraic constraint in native IDA with event parameter change."""
    bngl = """
begin model
begin parameters
  p 2
  thresh 5
end parameters
begin molecule types
  A()
  S()
end molecule types
begin seed species
  A() 10
  S() 2
end seed species
begin observables
  Molecules A_obs A()
  Species S_obs S()
end observables
begin functions
  F_p() = p
  F_s() = S_obs
end functions
begin reaction rules
  r1: A() + A() -> 0 1 TotalRate
end reaction rules
begin bng3_events version 1
  event "ev1"
    trigger: A_obs < thresh
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: p = 10
  end event
end bng3_events
end model
"""
    model = bionetgen.BioNetGenModel(_cpp.parse_string(bngl))
    net = model.generate_network()

    res = _cpp.simulate_ode(
        model._model,
        net,
        1.0,
        5,
        0.0,
        1e-6,
        1e-9,
        "cvode",
        0.0,
        False,
        1e-6,
        "",
        [],
        0,
        0,
        False,
        0.0,
        False,
        False,
        [("S_obs", "S_obs - p")],
        0,
    )

    times = res["time"]
    s_obs = res["observables"]["S_obs"]
    fns = res.get("functions", {})

    # At t = 0: p = 2, so S_obs = 2 and F_p = 2
    assert times[0] == pytest.approx(0.0)
    assert s_obs[0] == pytest.approx(2.0, rel=1e-5)
    assert fns["F_p"][0] == pytest.approx(2.0, rel=1e-5)
    assert fns["F_s"][0] == pytest.approx(2.0, rel=1e-5)

    # At t >= 0.2: p = 10, so S_obs = 10 and F_p = 10
    for i in range(1, len(times)):
        assert s_obs[i] == pytest.approx(10.0, rel=1e-5)
        assert fns["F_p"][i] == pytest.approx(10.0, rel=1e-5)
        assert fns["F_s"][i] == pytest.approx(10.0, rel=1e-5)
