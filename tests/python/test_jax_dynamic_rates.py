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


def test_observable_dependent_functional_rate_rhs():
    """Analytic evaluation of dA/dt = -f(count_A)*A = -(k*count_A)*A."""
    source = """begin model
begin parameters
k 0.1
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
Molecules count_A A()
end observables
begin functions
f() k*count_A
end functions
begin reaction rules
A() -> B() f()
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    rhs = jax_ode.compile_rhs(model)
    # At t=0, A=10: dA/dt = -(0.1*10)*10 = -10.0, dB/dt = +10.0
    deriv = rhs(0.0, jax.numpy.array([10.0, 0.0]))
    np.testing.assert_allclose(deriv, [-10.0, 10.0], atol=1e-6)

    # At t=0, A=5: dA/dt = -(0.1*5)*5 = -2.5, dB/dt = +2.5
    deriv5 = rhs(0.0, jax.numpy.array([5.0, 5.0]))
    np.testing.assert_allclose(deriv5, [-2.5, 2.5], atol=1e-6)


def test_observable_dependent_functional_rate_simulation():
    """Analytic integration: dA/dt = -k * A^2 with A(0)=10, k=0.1 -> A(t) = 10 / (1 + t)."""
    source = """begin model
begin parameters
k 0.1
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
Molecules count_A A()
end observables
begin functions
f() k*count_A
end functions
begin reaction rules
A() -> B() f()
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    result = jax_ode.simulate_jax_ode(model, t_end=4.0, n_steps=400)
    time = result["time"]
    concs = result["concentrations"]

    # Analytic expectation
    expected_A = 10.0 / (1.0 + time)
    expected_B = 10.0 - expected_A
    np.testing.assert_allclose(concs[:, 0], expected_A, rtol=1e-3, atol=1e-3)
    np.testing.assert_allclose(concs[:, 1], expected_B, rtol=1e-3, atol=1e-3)

    # Also compare with independent native BNG3 ODE integrator
    network = cpp.generate_network(model)
    native = cpp.simulate_ode(model, network, t_end=4.0, n_steps=400)
    np.testing.assert_allclose(concs, native["concentrations"], rtol=1e-3, atol=1e-3)


def test_observable_dependent_functional_rate_differentiation():
    """Verify JAX automatic differentiation through observable-dependent rate ODE."""
    source = """begin model
begin parameters
k 0.1
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
Molecules count_A A()
end observables
begin functions
f() k*count_A
end functions
begin reaction rules
A() -> B() f()
end reaction rules
end model
"""
    model = cpp.parse_string(source)

    def loss(k_val):
        res = jax_ode.simulate_jax_ode(
            model,
            t_end=4.0,
            n_steps=400,
            parameters={"k": k_val},
            return_jax=True,
        )
        return res["concentrations"][-1, 0]

    grad_fn = jax.grad(loss)
    # Analytical: A(t) = A0 / (1 + k * A0 * t)
    # dA/dk = - (A0^2 * t) / (1 + k * A0 * t)^2
    # At t=4, k=0.1, A0=10: dA/dk = - (100 * 4) / (1 + 4)^2 = -400 / 25 = -16.0
    computed_grad = float(grad_fn(0.1))
    expected_grad = -16.0
    np.testing.assert_allclose(computed_grad, expected_grad, rtol=1e-3, atol=1e-3)


def test_observable_dependent_michaelis_menten():
    """Verify Michaelis-Menten functional rate law against native BNG3 ODE."""
    source = """begin model
begin parameters
Vmax 2.0
Km 5.0
end parameters
begin molecule types
S()
P()
end molecule types
begin seed species
S() 20.0
P() 0.0
end seed species
begin observables
Molecules Sub S()
end observables
begin functions
rate_mm() MM(Vmax, Km, Sub)
end functions
begin reaction rules
S() -> P() rate_mm() TotalRate
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    result = jax_ode.simulate_jax_ode(model, t_end=10.0, n_steps=200)
    native = cpp.simulate_ode(model, network, t_end=10.0, n_steps=200)
    np.testing.assert_allclose(
        result["concentrations"], native["concentrations"], rtol=1e-3, atol=1e-3
    )


def test_observable_dependent_hill_kinetics():
    """Verify Hill functional rate law against native BNG3 ODE."""
    source = """begin model
begin parameters
Vmax 1.5
Kh 4.0
nH 2.0
end parameters
begin molecule types
S()
P()
end molecule types
begin seed species
S() 15.0
P() 0.0
end seed species
begin observables
Molecules Sub S()
end observables
begin functions
rate_hill() Hill(Vmax, Kh, nH, Sub)
end functions
begin reaction rules
S() -> P() rate_hill() TotalRate
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    result = jax_ode.simulate_jax_ode(model, t_end=8.0, n_steps=200)
    native = cpp.simulate_ode(model, network, t_end=8.0, n_steps=200)
    np.testing.assert_allclose(
        result["concentrations"], native["concentrations"], rtol=1e-3, atol=1e-3
    )


def test_observable_dependent_coupled_feedback():
    """Verify coupled multi-observable feedback system against native BNG3 ODE."""
    source = """begin model
begin parameters
k1 0.1
k2 0.05
end parameters
begin molecule types
A()
B()
end molecule types
begin seed species
A() 10.0
B() 2.0
end seed species
begin observables
Molecules count_A A()
Molecules count_B B()
end observables
begin functions
f_act() k1 * count_B
f_rep() k2 / (1.0 + count_A)
end functions
begin reaction rules
0 -> A() f_act()
0 -> B() f_rep()
A() -> 0 0.1
B() -> 0 0.1
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    result = jax_ode.simulate_jax_ode(model, t_end=5.0, n_steps=200)
    native = cpp.simulate_ode(model, network, t_end=5.0, n_steps=200)
    np.testing.assert_allclose(
        result["concentrations"], native["concentrations"], rtol=1e-3, atol=1e-3
    )
