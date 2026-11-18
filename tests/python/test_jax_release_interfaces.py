"""Independent coverage of JAX ODE units, dtypes and the common interfaces (#473).

The laws here are analytic and independent of the native BNG3 integrator:
declared-concentration unit conversion, first-order decay and the implicit
Michaelis-Menten solution. Interface checks exercise the same compiled model,
rate and result contracts consumed by the native engines.
"""

from __future__ import annotations

import math
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
jnp = pytest.importorskip("jax.numpy")
pytest.importorskip("jaxlib")

from bionetgen import _bionetgen_cpp as cpp  # noqa: E402
from bionetgen import jax_ode  # noqa: E402
from bionetgen.model import BioNetGenModel  # noqa: E402

AVOGADRO = 6.02214076e23


def _tolerance(arr):
    dt = np.asarray(arr).dtype
    if np.issubdtype(dt, np.floating) and dt.itemsize <= 4:
        return 5e-3
    return 2e-4


def _unit_model(volume, concentration=1.0, k=0.5):
    return cpp.parse_string(f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", {AVOGADRO!r})
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    unit per_s = second^-1
  end units
  begin parameters
    k {k} [per_s]
  end parameters
  begin compartments
    cell 3 {volume:g} [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell {concentration:g} [M]
  end seed species
  begin observables
    Molecules nA A()
  end observables
  begin reaction rules
    A() -> 0 k
  end reaction rules
end model
""")


@pytest.mark.parametrize("volume", [0.5, 1.0, 2.0])
def test_jax_ode_units_match_analytic_declared_concentration(volume):
    """C [M] in V fL seeds C*V*1e-15*N_A items; decay is exp(-k t)."""
    model = _unit_model(volume)
    network = cpp.generate_network(model)
    flat = cpp.jax_ode_flatten(model, network)
    # The common rate interface exposes the declared numeric first-order rate.
    np.testing.assert_allclose(np.asarray(flat["rate_constants"]), [0.5])

    result = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=20)
    conc = np.asarray(result["concentrations"])[:, 0]
    a0 = 1.0 * volume * 1e-15 * AVOGADRO
    expected = a0 * np.exp(-0.5 * np.asarray(result["time"]))
    tol = _tolerance(conc)
    np.testing.assert_allclose(conc, expected, rtol=tol, atol=tol * a0)
    assert conc[0] > 0.0 and conc[-1] < conc[0]

    # Native ODE consumes the same converted numeric network (parity, not oracle).
    native = cpp.simulate_ode(model, network, t_end=2.0, n_steps=20)
    np.testing.assert_allclose(
        conc, np.asarray(native["concentrations"])[:, 0], rtol=tol, atol=tol * a0
    )


def _mm_implicit(vmax, km, s0, t):
    """Independent root for dS/dt = -Vmax*S^2/(Km+S).

    Integration gives Km/S - ln(S) = Km/S0 - ln(S0) + Vmax*t. The left side
    decreases monotonically in S, so a plain bisection is sufficient.
    """
    target = km / s0 - math.log(s0) + vmax * t
    lo, hi = 1e-12, s0

    def f(s):
        return km / s - math.log(s) - target

    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def test_jax_ode_observable_dependent_mm_matches_independent_implicit_law():
    """A functional (Michaelis-Menten) rate against an analytic implicit law."""
    model = cpp.parse_string("""begin model
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
""")
    result = jax_ode.simulate_jax_ode(model, t_end=10.0, n_steps=100)
    s = np.asarray(result["concentrations"])[:, 0]
    expected = np.array(
        [_mm_implicit(2.0, 5.0, 20.0, float(t)) for t in result["time"]]
    )
    tol = _tolerance(s)
    np.testing.assert_allclose(s, expected, rtol=max(tol, 1e-4), atol=tol)


def test_common_compiled_model_and_rate_interfaces():
    """ODE and SSA flatteners share the compiled model, species and rates."""
    model = cpp.parse_file("models/isomerization.bngl")
    network = cpp.generate_network(model)
    ode_data = cpp.jax_ode_flatten(model, network)
    ssa_flat = cpp.jax_ssa_flatten(model, network)
    snapshot = cpp._compiled_snapshot(model)
    assert isinstance(model, cpp.Model)
    assert isinstance(snapshot, dict)

    # The flatteners expose the same numeric rates/state (the SSA binding
    # returns float32 constants, so compare with a dtype-appropriate tolerance).
    np.testing.assert_allclose(
        np.asarray(ode_data["rate_constants"]),
        np.asarray(ssa_flat["rate_constants"], dtype=float),
        rtol=1e-6,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        np.asarray(ode_data["initial_state"]),
        np.asarray(ssa_flat["initial_species"], dtype=float),
        rtol=0,
        atol=0,
    )
    assert (
        ode_data["num_species"] == ssa_flat["num_species"] == len(network.species_names)
    )
    assert ode_data["group_names"] == ssa_flat["observable_names"]

    # The same rate override interface is honoured by both backends' compile path.
    rhs_default = jax_ode.compile_rhs(model)
    rhs_override = jax_ode.compile_rhs(model, rate_constants=np.array([1.0, 0.5]))
    state = jnp.asarray([20.0, 0.0])
    np.testing.assert_allclose(rhs_default(0.0, state), [-4.0, 4.0], rtol=1e-5)
    np.testing.assert_allclose(rhs_override(0.0, state), [-20.0, 20.0], rtol=1e-5)

    # Wrapper model and native model expose the same compiled interface.
    wrapped = BioNetGenModel(model)
    np.testing.assert_allclose(
        np.asarray(jax_ode.compile_rhs(wrapped)(0.0, state)),
        np.asarray(rhs_default(0.0, state)),
        rtol=1e-6,
    )


def test_common_result_and_backend_interfaces():
    """ODE and SSA results use the documented key sets, shapes and dtypes."""
    model = cpp.parse_file("models/isomerization.bngl")
    network = cpp.generate_network(model)

    ode = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=10)
    native_ode = cpp.simulate_ode(model, network, t_end=2.0, n_steps=10)
    # The JAX ODE adapter returns the common time/concentrations core keys;
    # the native binding additionally exposes batch/observable bookkeeping.
    assert {"time", "concentrations"} <= set(ode)
    assert {"time", "concentrations"} <= set(native_ode)
    assert ode["time"].shape == (11,)
    assert ode["concentrations"].shape == (11, 2)
    assert isinstance(ode["time"], np.ndarray)
    assert isinstance(ode["concentrations"], np.ndarray)
    expected_dtype = np.dtype(jnp.asarray(0.0).dtype)
    assert ode["concentrations"].dtype == expected_dtype

    jax_result = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=10, return_jax=True)
    assert isinstance(jax_result["concentrations"], jax.Array)
    np.testing.assert_allclose(
        np.asarray(jax_result["concentrations"]), ode["concentrations"], rtol=1e-6
    )

    from bionetgen import jax_ssa

    ssa = jax_ssa.simulate(
        model, network, batch_size=32, t_end=2.0, n_steps=4, base_seed=42
    )
    native_ssa = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=32, t_end=2.0, n_steps=4, base_seed=42, threads=1
    )
    required = {
        "batch_size",
        "total_events",
        "time",
        "observable_means",
        "observable_stds",
        "final_observables",
        "observable_names",
        "final_species",
        "event_counts",
    }
    assert required <= set(ssa)
    assert required <= set(native_ssa)
    assert ssa["observable_names"] == native_ssa["observable_names"]
    assert ssa["final_species"].shape == (32, 2)
    assert ssa["final_observables"].shape == (32, 3)
    assert ssa["event_counts"].shape == (32,)

    # Only the declared, distribution-level comparison is valid across engines.
    for name in ssa["observable_names"]:
        np.testing.assert_allclose(
            ssa["observable_means"][name].mean(),
            native_ssa["observable_means"][name].mean(),
            rtol=0.25,
            atol=0.5,
        )


def test_supported_dtypes_and_finite_input_guards():
    """The configured JAX float dtype is used; out-of-range values fail closed."""
    model = cpp.parse_string("""begin model
begin parameters
k 0.2
end parameters
begin molecule types
A()
B()
end molecule types
begin seed species
A() 20
B() 0
end seed species
begin reaction rules
A() -> B() k
end reaction rules
end model
""")
    res = jax_ode.simulate_jax_ode(model, t_end=1.0, n_steps=10, return_jax=True)
    assert res["concentrations"].dtype == jnp.asarray(0.0).dtype

    # Lists are accepted for the rate/state override interface.
    with_list = jax_ode.simulate_jax_ode(
        model, t_end=1.0, n_steps=10, rate_constants=[0.4], initial_state=[10.0, 0.0]
    )
    assert np.isfinite(with_list["concentrations"]).all()

    x64 = bool(jax.config.read("jax_enable_x64"))
    huge = cpp.parse_string("""begin model
begin parameters
k 1e50
end parameters
begin molecule types
A()
B()
end molecule types
begin seed species
A() 20
B() 0
end seed species
begin reaction rules
A() -> B() k
end reaction rules
end model
""")
    if x64:
        assert np.isfinite(
            np.asarray(jax_ode.compile_rhs(huge)(0.0, jnp.asarray([20.0, 0.0])))
        ).all()
    else:
        with pytest.raises(ValueError, match="dtype range"):
            jax_ode.compile_rhs(huge)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
