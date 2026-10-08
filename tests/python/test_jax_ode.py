"""Numerical contracts for the optional JAX ODE backend."""

from pathlib import Path

import numpy as np
import pytest

jax = pytest.importorskip("jax")
pytest.importorskip("jaxlib")

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ode
from bionetgen.model import BioNetGenModel


def _model(rule, seeds="A() 20\nB() 0", extra="", rate="0.2"):
    return cpp.parse_string(f"""begin model
begin parameters
k {rate}
end parameters
begin molecule types
A()
B()
end molecule types
begin seed species
{seeds}
end seed species
{extra}
begin reaction rules
{rule}
end reaction rules
end model
""")


@pytest.mark.parametrize("seeds,state", [("A() 3", [3.0]), ("", [])])
def test_no_reaction_network_has_zero_rhs_and_constant_trajectory(seeds, state):
    model = _model("", seeds=seeds)
    network = cpp.generate_network(model)
    assert network.num_reactions == 0
    assert network.num_species == len(state)

    rhs = jax_ode.compile_rhs(model)
    np.testing.assert_array_equal(
        rhs(0.0, jax.numpy.asarray(state)), np.zeros(len(state))
    )
    result = jax_ode.simulate_jax_ode(model, t_end=1.0, n_steps=4)
    np.testing.assert_array_equal(result["concentrations"], np.tile(state, (5, 1)))


def test_rate_overflowing_jax_state_dtype_is_rejected():
    model = _model("A() -> B() k", rate="1e50")
    rhs = jax_ode.compile_rhs
    if jax.config.read("jax_enable_x64"):
        derivative = rhs(model)(0.0, jax.numpy.array([20.0, 0.0]))
        assert np.isfinite(np.asarray(derivative)).all()
    else:
        with pytest.raises(ValueError, match="rate constants.*JAX.*dtype range"):
            rhs(model)


def test_rate_underflowing_jax_state_dtype_is_rejected():
    model = _model("A() -> B() k", rate="1e-50")
    if jax.config.read("jax_enable_x64"):
        actual = np.asarray(
            jax_ode.compile_rhs(model)(0.0, jax.numpy.array([20.0, 0.0]))
        )
        np.testing.assert_allclose(actual, [-2e-49, 2e-49], rtol=1e-12, atol=0)
    else:
        with pytest.raises(ValueError, match="rate constants.*JAX.*dtype range"):
            jax_ode.compile_rhs(model)


@pytest.mark.parametrize(
    "rule,seeds,state,expected",
    [
        ("A() -> B() k", "A() 20\nB() 0", [20.0, 0.0], [-4.0, 4.0]),
        # The compiled coefficient includes the identical-reactant factor 1/2.
        ("A() + A() -> B() k", "A() 20\nB() 0", [20.0, 0.0], [-80.0, 40.0]),
        ("A() -> B() k TotalRate", "A() 20\nB() 0", [20.0, 0.0], [-0.2, 0.2]),
        ("A() -> B() k", "$A() 20\nB() 0", [20.0, 0.0], [0.0, 4.0]),
        ("0 -> A() k", "A() 0\nB() 0", [0.0, 0.0], [0.2, 0.0]),
        ("A() -> 0 k", "A() 20\nB() 0", [-2.0, 0.0], [0.4, 0.0]),
    ],
)
def test_rhs_matches_analytic_and_native(rule, seeds, state, expected):
    model = _model(rule, seeds)
    network = cpp.generate_network(model)
    rhs = jax_ode.compile_rhs(model)
    actual = np.asarray(rhs(0.0, jax.numpy.asarray(state)))
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)
    native = cpp._validation_ode_rhs(model, network, 0.0, state)
    np.testing.assert_allclose(actual, native, rtol=1e-6, atol=1e-6)


def test_generated_species_and_trajectory_match_analytic_and_native():
    path = Path(__file__).resolve().parents[2] / "models" / "isomerization.bngl"
    model = cpp.parse_file(str(path))
    network = cpp.generate_network(model)
    assert network.num_species == 2  # one seed species; the other is generated
    result = jax_ode.simulate_jax_ode(model, t_end=10.0, n_steps=100)
    time = result["time"]
    concentrations = result["concentrations"]
    assert time.shape == (101,)
    assert concentrations.shape == (101, 2)
    b = (20.0 / 6.0) * (1.0 - np.exp(-1.2 * time))
    np.testing.assert_allclose(concentrations[:, 0], 20.0 - b, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(concentrations[:, 1], b, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(concentrations.sum(axis=1), 20.0, atol=1e-4)
    native = cpp.simulate_ode(model, network, t_end=10.0, n_steps=100)
    np.testing.assert_allclose(time, native["time"], rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(
        concentrations, native["concentrations"], rtol=1e-5, atol=1e-5
    )


def test_public_model_wrapper():
    model = BioNetGenModel(_model("A() -> B() k"))
    rhs = jax_ode.compile_rhs(model)
    np.testing.assert_allclose(rhs(0.0, jax.numpy.array([20.0, 0.0])), [-4.0, 4.0])


@pytest.mark.parametrize(
    "rule,extra",
    [
        (
            "A() -> B() f()",
            "begin observables\nMolecules count A()\nend observables\nbegin functions\nf() k*count\nend functions",
        ),
        ("A() -> B() k*time", ""),
    ],
)
def test_jax_ode_functional_unsupported(rule, extra):
    model = _model(rule, extra=extra)
    with pytest.raises(NotImplementedError, match="functional|time-dependent"):
        jax_ode.compile_rhs(model)
    with pytest.raises(NotImplementedError, match="functional|time-dependent"):
        jax_ode.simulate_jax_ode(model, t_end=1.0)


def test_solver_method_is_not_silently_ignored():
    with pytest.raises(ValueError, match="method"):
        jax_ode.simulate_jax_ode(_model("A() -> B() k"), t_end=1.0, method="cvode")


@pytest.mark.parametrize(
    "t_end,n_steps", [(0.0, 1), (-1.0, 1), (float("nan"), 1), (1.0, 0)]
)
def test_invalid_time_grid_rejected(t_end, n_steps):
    with pytest.raises(ValueError):
        jax_ode.simulate_jax_ode(_model("A() -> B() k"), t_end=t_end, n_steps=n_steps)


def test_noninteger_step_count_rejected():
    with pytest.raises(TypeError, match="n_steps"):
        jax_ode.simulate_jax_ode(_model("A() -> B() k"), t_end=1.0, n_steps=1.5)
