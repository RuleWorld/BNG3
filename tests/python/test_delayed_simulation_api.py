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


def test_delayed_ssa_independent_jump_distribution():
    """Verify consuming and NonConsuming delayed jump processes against independent analytic laws.

    1. Consuming delayed reaction A -> B (rate k=1.0, delay tau=0.5, A0=100, B0=0):
       - For t < tau (t=0.4): zero completions (B == 0 identically).
         Initiations follow a pure death process: A(t) ~ Binomial(A0, exp(-k*t)).
       - For t >= tau (t=0.8): completions follow delayed initiations:
         B(t) ~ Binomial(A0, 1 - exp(-k*(t - tau))).
    2. NonConsuming delayed reaction A -> A + B (rate k=1.0, delay tau=0.5, A0=10, B0=0):
       - Reactant A is never consumed: A(t) == A0 constantly across all runs.
       - For t < tau (t=0.4): zero completions (B == 0 identically).
       - For t >= tau (t=0.8): initiations occurred at constant propensity k*A0 = 10,
         so completions B(t) ~ Poisson(k * A0 * (t - tau)) = Poisson(3.0).
    """
    source_consuming = """
begin model
begin parameters
  tau 0.5
  k 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    model_cons = BioNetGenModel(cpp.parse_string(source_consuming))
    n_runs = 500
    a_04_list = []
    b_04_list = []
    b_08_list = []

    for i in range(n_runs):
        model_cons.reset_simulation()
        res = model_cons.simulate(
            method="ssa",
            t_start=0.0,
            t_end=1.0,
            sample_times=[0.4, 0.8],
            seed=1000 + i,
        )
        a_04_list.append(res.observables["A"][0])
        b_04_list.append(res.observables["B"][0])
        b_08_list.append(res.observables["B"][1])

    a_04 = np.array(a_04_list)
    b_04 = np.array(b_04_list)
    b_08 = np.array(b_08_list)

    # Pre-delay horizon: exactly zero completions
    assert np.all(b_04 == 0.0), "Consuming delay produced completions before tau=0.5"

    # Initiation distribution at t=0.4: Binomial(100, exp(-0.4))
    mean_theory_a04 = 100.0 * np.exp(-0.4)
    std_theory_a04 = np.sqrt(100.0 * np.exp(-0.4) * (1.0 - np.exp(-0.4)))
    sem_a04 = std_theory_a04 / np.sqrt(n_runs)
    assert (
        abs(np.mean(a_04) - mean_theory_a04) < 4.0 * sem_a04
    ), f"A(0.4) empirical mean {np.mean(a_04)} deviated from theory {mean_theory_a04}"

    # Delayed completion distribution at t=0.8: Binomial(100, 1 - exp(-0.3))
    mean_theory_b08 = 100.0 * (1.0 - np.exp(-0.3))
    std_theory_b08 = np.sqrt(100.0 * (1.0 - np.exp(-0.3)) * np.exp(-0.3))
    sem_b08 = std_theory_b08 / np.sqrt(n_runs)
    assert (
        abs(np.mean(b_08) - mean_theory_b08) < 4.0 * sem_b08
    ), f"B(0.8) empirical mean {np.mean(b_08)} deviated from theory {mean_theory_b08}"

    # NonConsuming delay
    source_nonconsuming = """
begin model
begin parameters
  tau 0.5
  k 1.0
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
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> A() + B() k delay=tau NonConsuming
end reaction rules
end model
"""
    model_nc = BioNetGenModel(cpp.parse_string(source_nonconsuming))
    a_nc_04_list = []
    b_nc_04_list = []
    b_nc_08_list = []

    for i in range(n_runs):
        model_nc.reset_simulation()
        res = model_nc.simulate(
            method="ssa",
            t_start=0.0,
            t_end=1.0,
            sample_times=[0.4, 0.8],
            seed=2000 + i,
        )
        a_nc_04_list.append(res.observables["A"][0])
        b_nc_04_list.append(res.observables["B"][0])
        b_nc_08_list.append(res.observables["B"][1])

    a_nc_04 = np.array(a_nc_04_list)
    b_nc_04 = np.array(b_nc_04_list)
    b_nc_08 = np.array(b_nc_08_list)

    # NonConsuming reactant must remain constant across all runs
    assert np.all(
        a_nc_04 == 10.0
    ), "NonConsuming reactant A was altered during initiation"
    assert np.all(
        b_nc_04 == 0.0
    ), "NonConsuming delay produced completions before tau=0.5"

    # Post-delay completions: Poisson(k * A0 * (t - tau)) = Poisson(10 * 0.3) = Poisson(3.0)
    mean_theory_nc = 3.0
    std_theory_nc = np.sqrt(3.0)
    sem_nc = std_theory_nc / np.sqrt(n_runs)
    assert (
        abs(np.mean(b_nc_08) - mean_theory_nc) < 4.0 * sem_nc
    ), f"NonConsuming B(0.8) mean {np.mean(b_nc_08)} deviated from theory {mean_theory_nc}"
    assert (
        abs(np.var(b_nc_08) - mean_theory_nc) < 0.6
    ), f"NonConsuming B(0.8) variance {np.var(b_nc_08)} deviated from Poisson variance {mean_theory_nc}"
