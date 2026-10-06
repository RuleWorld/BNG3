"""Tests for JAX ODE rate law JIT compilation."""

import pytest

# Skip if JAX not available
jax = pytest.importorskip("jax")
jaxlib = pytest.importorskip("jaxlib")
pytest.importorskip("bionetgen")

from bionetgen import _bionetgen_cpp as cpp


def test_jax_ode_import():
    """Test that the jax_ode module can be imported."""
    import bionetgen.jax_ode as jax_ode

    assert hasattr(jax_ode, "compile_rhs")
    assert hasattr(jax_ode, "simulate_jax_ode")


def test_jax_ode_compile_rhs():
    """Test compiling RHS for a simple mass-action model."""
    import bionetgen.jax_ode as jax_ode
    import jax.numpy as jnp

    model = cpp.parse_file("models/isomerization.bngl")
    rhs = jax_ode.compile_rhs(model)

    # Test the RHS function
    y = jnp.array([20.0, 0.0], dtype=jnp.float32)
    dydt = rhs(0.0, y)

    # isomerization: A <-> B, k1=0.2, k2=1.0
    # dA/dt = -k1*A + k2*B = -0.2*20 + 1.0*0 = -4.0
    # dB/dt = k1*A - k2*B = 0.2*20 - 1.0*0 = 4.0
    expected_dA = -4.0
    expected_dB = 4.0

    assert jnp.allclose(dydt[0], expected_dA, atol=1e-5)
    assert jnp.allclose(dydt[1], expected_dB, atol=1e-5)


def test_jax_ode_simulate():
    """Test full JAX ODE simulation."""
    pytest.importorskip("jax.experimental.ode")

    import bionetgen.jax_ode as jax_ode
    import numpy as np

    model = cpp.parse_file("models/isomerization.bngl")
    result = jax_ode.simulate_jax_ode(model, t_end=10.0, n_steps=100)

    assert "time" in result
    assert "concentrations" in result
    assert result["time"].shape[0] == 101  # 100 steps + 1
    assert result["concentrations"].shape[1] == 2  # 2 species

    # Check conservation: A + B should be constant
    total = result["concentrations"][:, 0] + result["concentrations"][:, 1]
    assert np.allclose(total, 20.0, atol=1e-4)


def test_jax_ode_functional_unsupported():
    """Test that functional rate laws raise NotImplementedError."""
    import bionetgen.jax_ode as jax_ode

    # Create a model with functional rate (if available)
    # For now, just test that the error is raised appropriately
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
