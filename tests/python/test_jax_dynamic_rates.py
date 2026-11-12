"""Numerical contracts and analytic benchmarks for JAX ODE dynamic time-dependent rates."""

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

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ode


def _model(rule: str, seeds: str = "A() 0", parameters: str = "k 1.0") -> cpp.Model:
    return cpp.parse_string(f"""begin model
begin parameters
{parameters}
end parameters
begin molecule types
A()
end molecule types
begin seed species
{seeds}
end seed species
begin reaction rules
{rule}
end reaction rules
end model
""")


def test_time_dependent_rhs_matches_analytic_law():
    """Analytic evaluation of dA/dt = time() at instantaneous time points."""
    model = _model("0 -> A() time()")
    rhs = jax_ode.compile_rhs(model)

    state = jax.numpy.array([0.0])
    np.testing.assert_allclose(rhs(0.0, state), [0.0], atol=1e-6)
    np.testing.assert_allclose(rhs(1.5, state), [1.5], atol=1e-6)
    np.testing.assert_allclose(rhs(3.0, state), [3.0], atol=1e-6)


def test_time_dependent_simulation_matches_analytic_integral():
    """Analytic integration: dA/dt = t, A(0)=0 -> A(t) = 0.5 * t^2."""
    model = _model("0 -> A() time()")
    result = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=100)

    time = result["time"]
    concentrations = result["concentrations"][:, 0]
    expected = 0.5 * (time**2)

    np.testing.assert_allclose(concentrations, expected, rtol=1e-4, atol=1e-4)
    # Check exact value at endpoint t = 2.0
    np.testing.assert_allclose(concentrations[-1], 2.0, rtol=1e-4, atol=1e-4)


def test_parameterized_time_dependent_rate_simulation():
    """Analytic integration: dA/dt = k * t, k=2.5, A(0)=0 -> A(t) = 1.25 * t^2."""
    model = _model("0 -> A() k*time()", parameters="k 2.5")
    result = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=100)

    time = result["time"]
    concentrations = result["concentrations"][:, 0]
    expected = 0.5 * 2.5 * (time**2)

    np.testing.assert_allclose(concentrations, expected, rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(concentrations[-1], 5.0, rtol=1e-4, atol=1e-4)


def test_time_dependent_decay_matches_analytic_gaussian():
    """Analytic integration: dA/dt = -k * t * A, k=1.0, A(0)=10 -> A(t) = 10 * exp(-0.5 * t^2)."""
    model = _model("A() -> 0 k*time()", seeds="A() 10.0", parameters="k 1.0")
    result = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=200)

    time = result["time"]
    concentrations = result["concentrations"][:, 0]
    expected = 10.0 * np.exp(-0.5 * (time**2))

    np.testing.assert_allclose(concentrations, expected, rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(
        concentrations[-1], 10.0 * np.exp(-2.0), rtol=1e-4, atol=1e-4
    )


def test_time_dependent_automatic_differentiation():
    """Verify JAX automatic differentiation through time-dependent rate ODE."""
    model = _model("0 -> A() k*time()", parameters="k 1.0")

    def loss(k_val):
        res = jax_ode.simulate_jax_ode(
            model,
            t_end=2.0,
            n_steps=100,
            parameters=jax.numpy.atleast_1d(k_val),
            return_jax=True,
        )
        return res["concentrations"][-1, 0]

    grad_fn = jax.grad(loss)
    k_test = 2.0
    computed_grad = float(grad_fn(k_test))
    # Analytical: A(t) = 0.5 * k * t^2 -> dA/dk = 0.5 * t^2. At t=2.0: dA/dk = 2.0
    expected_grad = 0.5 * (2.0**2)
    np.testing.assert_allclose(computed_grad, expected_grad, rtol=1e-3, atol=1e-3)


def test_unsupported_functional_rates_still_raise_not_implemented():
    """Verify that observable-dependent functional rates continue to raise NotImplementedError."""
    source = """begin model
begin parameters
k 1.0
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
Molecules count A()
end observables
begin functions
f() k*count
end functions
begin reaction rules
A() -> B() f()
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    with pytest.raises(NotImplementedError, match="functional rate laws"):
        jax_ode.compile_rhs(model)
