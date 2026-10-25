import numpy as np
import pytest

from bionetgen import BioNetGenModel
from _extdep import require_extension

cpp = require_extension()


SOURCE = """
begin model
begin parameters
  tau 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  A() -> B() 0.5 delay=tau
end reaction rules
end model
"""


def test_python_native_continuation_reset_and_default_fresh_run():
    model = BioNetGenModel(cpp.parse_string(SOURCE))
    first = model.simulate(method="ode", t_end=2.0, n_steps=4)
    continued = model.simulate(
        method="ODE",
        t_start=2.0,
        t_end=4.0,
        n_steps=4,
        continue_simulation=True,
    )
    a = continued.observables["A_count"]
    b = continued.observables["B_count"]
    np.testing.assert_allclose(a[-1], 10.0 * np.exp(-2.0), rtol=1e-5)
    np.testing.assert_allclose(b[-1], 10.0 * (1.0 - np.exp(-1.0)), rtol=1e-5)
    np.testing.assert_allclose(first.observables["B_count"][-1], 0.0, atol=1e-8)

    # A plain call starts from model seeds even though the binding updates the
    # cached generated network after each native simulation.
    fresh = model.simulate(method="ode", t_end=4.0, n_steps=8)
    np.testing.assert_allclose(fresh.observables["A_count"][-1], a[-1], rtol=1e-5)
    np.testing.assert_allclose(fresh.observables["B_count"][-1], b[-1], rtol=1e-5)

    model.reset_simulation()
    reset = model.simulate(method="ode", t_end=2.0, n_steps=4)
    np.testing.assert_allclose(reset.observables["A_count"][0], 10.0)
    np.testing.assert_allclose(reset.observables["B_count"][-1], 0.0, atol=1e-8)


def test_python_parameter_change_preserves_explicit_continuation():
    source = SOURCE.replace("  tau 2\n", "  tau 2\n  k 0.5\n").replace(
        "A() -> B() 0.5 delay=tau", "A() -> B() k delay=tau"
    )
    model = BioNetGenModel(cpp.parse_string(source))
    model.simulate(method="ode", t_end=1.0, n_steps=10)
    model.set_parameter("k", 1.0)
    continued = model.simulate(
        method="ode",
        t_start=1.0,
        t_end=3.0,
        n_steps=20,
        continue_simulation=True,
    )
    np.testing.assert_allclose(
        continued.observables["B_count"][-1],
        10.0 * (1.0 - np.exp(-0.5)),
        rtol=1e-5,
    )


def test_python_parameter_change_uses_new_seed_for_fresh_run():
    source = SOURCE.replace("  tau 2\n", "  tau 2\n  N 10\n").replace("A() 10", "A() N")
    model = BioNetGenModel(cpp.parse_string(source))
    model.simulate(method="ode", t_end=1.0, n_steps=2)
    model.set_parameter("N", 20)

    fresh = model.simulate(method="ode", t_end=2.0, n_steps=4)

    np.testing.assert_allclose(fresh.observables["A_count"][0], 20.0)
    np.testing.assert_allclose(fresh.observables["B_count"][-1], 0.0, atol=1e-8)


def test_failed_fresh_run_preserves_pending_continuation_after_parameter_change():
    source = SOURCE.replace("  tau 2\n", "  tau 2\n  k 0.5\n").replace(
        "A() -> B() 0.5 delay=tau", "A() -> B() k delay=tau"
    )
    model = BioNetGenModel(cpp.parse_string(source))
    model.simulate(method="ode", t_end=1.0, n_steps=2)
    model.set_parameter("k", 1.0)

    with pytest.raises(RuntimeError, match="__missing_recovery_name__"):
        model.simulate(
            method="ode",
            t_end=2.0,
            n_steps=4,
            stop_if="__missing_recovery_name__ > 0",
        )

    continued = model.simulate(
        method="ode",
        t_start=1.0,
        t_end=3.0,
        n_steps=4,
        continue_simulation=True,
    )
    np.testing.assert_allclose(
        continued.observables["B_count"][-1],
        10.0 * (1.0 - np.exp(-0.5)),
        rtol=1e-5,
    )


def test_python_direct_ssa_continues_pending_completion():
    source = SOURCE.replace("A() 10", "A() 1").replace(
        "A() -> B() 0.5 delay=tau", "A() -> B() 1000000 delay=tau"
    )
    model = BioNetGenModel(cpp.parse_string(source))
    first = model.simulate(method="ssa", t_end=1.0, n_steps=2, seed=17)
    continued = model.simulate(
        method="ssa",
        t_start=1.0,
        t_end=3.0,
        n_steps=4,
        seed=17,
        continue_simulation=True,
    )
    np.testing.assert_allclose(first.observables["B_count"][-1], 0.0, atol=1e-8)
    np.testing.assert_allclose(continued.observables["B_count"][-1], 1.0, atol=1e-8)
    fresh = model.simulate(method="ssa", t_end=1.0, n_steps=2, seed=17)
    np.testing.assert_array_equal(
        fresh.observables["A_count"], first.observables["A_count"]
    )
    np.testing.assert_array_equal(
        fresh.observables["B_count"], first.observables["B_count"]
    )


@pytest.mark.parametrize(
    "stop_if",
    [
        "__missing_recovery_name__ > 0",
        "if(time > 0, __missing_recovery_name__, 0)",
    ],
)
def test_failed_fresh_run_preserves_network_and_delayed_continuation(stop_if):
    model = BioNetGenModel(cpp.parse_string(SOURCE))
    model.simulate(method="ode", t_end=2.0, n_steps=4)
    network = model._network

    with pytest.raises(RuntimeError, match="__missing_recovery_name__"):
        model.simulate(method="ode", t_end=2.0, n_steps=4, stop_if=stop_if)

    assert model._network is network
    continued = model.simulate(
        method="ode",
        t_start=2.0,
        t_end=4.0,
        n_steps=4,
        continue_simulation=True,
    )
    np.testing.assert_allclose(
        continued.observables["B_count"][-1],
        10.0 * (1.0 - np.exp(-1.0)),
        rtol=1e-5,
    )
