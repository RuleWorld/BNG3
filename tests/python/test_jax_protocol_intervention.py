"""Installed CPU JAX ODE protocol/parameter-intervention qualification (#473).

Uncovered family: a public continuation protocol with a parameter intervention
on a time-dependent rate, and the same protocol on an observable-dependent
functional rate. Deterministic ODE path; no stochastic seeds apply.
Predeclared analytic laws and tolerances: analysis/c-jax-protocol/PREDECLARED_PLAN.md.
"""

from __future__ import annotations

import os
import sys

if (
    sys.platform == "darwin"
    and "JAX_PLATFORMS" not in os.environ
    and "JAX_PLATFORM_NAME" not in os.environ
):
    os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np
import pytest

jax = pytest.importorskip("jax")
pytest.importorskip("jaxlib")

from bionetgen import _bionetgen_cpp as cpp  # noqa: E402
from bionetgen import jax_ode  # noqa: E402

PLAN_SHA256 = "a2bbc42d6dfef61567b30be40670187bdd1d8c65d2d701c7b289ea43fe3ecbbf"


def _time_dependent_model() -> cpp.Model:
    return cpp.parse_string("""begin model
begin parameters
k 1.0
end parameters
begin molecule types
A()
end molecule types
begin seed species
A() 0
end seed species
begin observables
Molecules CountA A()
end observables
begin reaction rules
0 -> A() k*time()
end reaction rules
end model
""")


def _functional_model() -> cpp.Model:
    return cpp.parse_string("""begin model
begin parameters
k 0.1
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
Molecules CountA A()
end observables
begin functions
f() k*CountA
end functions
begin reaction rules
A() -> B() f()
end reaction rules
end model
""")


def _tol(concentrations):
    """Predeclared dtype-dependent tolerance (float32 vs float64)."""
    dt = np.asarray(concentrations).dtype
    if np.issubdtype(dt, np.floating) and dt.itemsize <= 4:
        return 5e-3, 5e-3
    return 2e-5, 2e-5


def test_jax_ode_time_dependent_parameter_intervention_continuation():
    """Piecewise analytic law, returned grid and wrong-implementation control."""
    model = _time_dependent_model()
    p1 = jax_ode.simulate_jax_ode(
        model,
        t_end=2.0,
        t_start=0.0,
        n_steps=40,
        parameters={"k": 1.0},
        return_jax=True,
    )
    p2 = jax_ode.simulate_jax_ode(
        model,
        t_end=4.0,
        t_start=2.0,
        n_steps=40,
        initial_state=p1["concentrations"][-1],
        parameters={"k": 3.0},
        return_jax=True,
    )
    a1 = np.asarray(p1["concentrations"])[:, 0]
    a2 = np.asarray(p2["concentrations"])[:, 0]
    rtol, atol = _tol(a2)

    # Returned grid (predeclared).
    assert p2["time"][0] == 2.0 and p2["time"][-1] == 4.0
    assert len(p2["time"]) == 41 and len(a2) == 41

    # Piecewise analytic law: A(t) = A(t0) + 0.5*k*(t^2 - t0^2).
    np.testing.assert_allclose(
        a1, 0.5 * 1.0 * np.asarray(p1["time"]) ** 2, rtol=rtol, atol=atol
    )
    expected2 = 2.0 + 0.5 * 3.0 * (np.asarray(p2["time"]) ** 2 - 2.0**2)
    np.testing.assert_allclose(a2, expected2, rtol=rtol, atol=atol)
    np.testing.assert_allclose(a2[-1], 20.0, rtol=rtol, atol=atol)

    # Wrong-implementation control: a frozen phase-1 rate predicts A(4)=8.
    frozen_final = 2.0 + 0.5 * 1.0 * (4.0**2 - 2.0**2)
    assert abs(a2[-1] - frozen_final) > 100 * atol


def test_jax_ode_time_dependent_intervention_gradient():
    """Automatic differentiation through the piecewise rate switch."""
    model = _time_dependent_model()
    p1 = jax_ode.simulate_jax_ode(
        model,
        t_end=2.0,
        t_start=0.0,
        n_steps=40,
        parameters={"k": 1.0},
        return_jax=True,
    )

    def loss(k2):
        res = jax_ode.simulate_jax_ode(
            model,
            t_end=4.0,
            t_start=2.0,
            n_steps=40,
            initial_state=p1["concentrations"][-1],
            parameters={"k": k2},
            return_jax=True,
        )
        return res["concentrations"][-1, 0]

    grad = float(jax.grad(loss)(3.0))
    # Analytic dA(4)/dk2 = 0.5*(4^2-2^2) = 6.
    np.testing.assert_allclose(grad, 6.0, rtol=5e-3, atol=5e-3)


def test_jax_ode_functional_rate_intervention_continuation_and_gradient():
    """Observable-dependent rate with a parameter switch, law and gradient."""
    model = _functional_model()
    p1 = jax_ode.simulate_jax_ode(
        model,
        t_end=1.0,
        t_start=0.0,
        n_steps=50,
        parameters={"k": 0.1},
        return_jax=True,
    )
    p2 = jax_ode.simulate_jax_ode(
        model,
        t_end=3.0,
        t_start=1.0,
        n_steps=100,
        initial_state=p1["concentrations"][-1],
        parameters={"k": 0.3},
        return_jax=True,
    )
    a1 = np.asarray(p1["concentrations"])[:, 0]
    a2 = np.asarray(p2["concentrations"])[:, 0]
    rtol, atol = _tol(a2)
    a1_exact = 10.0 / (1.0 + 0.1 * 10.0 * np.asarray(p1["time"]))
    a2_exact = a1[-1] / (1.0 + 0.3 * a1[-1] * (np.asarray(p2["time"]) - 1.0))
    np.testing.assert_allclose(a1, a1_exact, rtol=max(rtol, 1e-4), atol=atol)
    np.testing.assert_allclose(a2, a2_exact, rtol=max(rtol, 1e-4), atol=atol)

    def loss(k2):
        res = jax_ode.simulate_jax_ode(
            model,
            t_end=3.0,
            t_start=1.0,
            n_steps=100,
            initial_state=p1["concentrations"][-1],
            parameters={"k": k2},
            return_jax=True,
        )
        return res["concentrations"][-1, 0]

    grad = float(jax.grad(loss)(0.3))
    a1_final = 10.0 / (1.0 + 0.1 * 10.0 * 1.0)
    expected = -(a1_final**2) * 2.0 / (1.0 + 0.3 * a1_final * 2.0) ** 2
    np.testing.assert_allclose(grad, expected, rtol=5e-3, atol=5e-3)

    # Wrong-implementation control: a frozen rate is rejected.
    frozen = a1_final / (1.0 + 0.1 * a1_final * 2.0)
    assert abs(a2[-1] - frozen) > 100 * atol


def test_jax_ode_intervention_error_behavior():
    """Continuation-specific error behavior is preserved."""
    model = _time_dependent_model()
    with pytest.raises(ValueError):
        jax_ode.simulate_jax_ode(model, t_end=2.0, t_start=-1.0, n_steps=10)
    with pytest.raises(ValueError):
        jax_ode.simulate_jax_ode(model, t_end=2.0, t_start=2.0, n_steps=10)
    with pytest.raises(TypeError):
        jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=1.5)
    with pytest.raises(ValueError):
        jax_ode.simulate_jax_ode(
            model, t_end=2.0, initial_state=np.array([1.0, 2.0]), n_steps=10
        )
