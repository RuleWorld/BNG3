"""Public fresh/continuation lifecycle checks against pure-death laws."""

import numpy as np
import pytest

from _extdep import require_extension

from bionetgen import BioNetGenModel

cpp = require_extension()

A0 = 24
INITIAL_RATE = 0.3
UPDATED_RATE = 0.6


def _model():
    source = f"""
begin model
begin parameters
    A0 {A0}
    k {INITIAL_RATE}
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() A0
    B() 0
end seed species
begin observables
    Molecules A_count A()
    Molecules B_count B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    return BioNetGenModel(cpp.parse_string(source))


def _assert_death_law(result, hazard):
    expected_a = A0 * np.exp(-hazard)
    np.testing.assert_allclose(
        result.observables["A_count"], expected_a, rtol=2e-8, atol=2e-8
    )
    np.testing.assert_allclose(
        result.observables["B_count"], A0 - expected_a, rtol=2e-8, atol=2e-8
    )


def _ode_options(t_start, t_end):
    return dict(
        method="ode",
        t_start=t_start,
        t_end=t_end,
        n_steps=8,
        rtol=1e-11,
        atol=1e-13,
    )


def test_fresh_continuation_reset_setter_and_exception_recovery():
    model = _model()
    parsed_model = model._model

    first = model.simulate(**_ode_options(0.0, 1.0))
    compiled_network = model._network
    first_snapshot = first.concentrations.copy()
    _assert_death_law(first, INITIAL_RATE * first.time)

    repeated_fresh = model.simulate(**_ode_options(0.0, 1.0))
    assert model._model is parsed_model
    assert model._network is compiled_network
    np.testing.assert_array_equal(repeated_fresh.time, first.time)
    np.testing.assert_allclose(
        repeated_fresh.concentrations, first.concentrations, rtol=0.0, atol=0.0
    )
    _assert_death_law(repeated_fresh, INITIAL_RATE * repeated_fresh.time)

    continued = model.simulate(**_ode_options(1.0, 2.0), continue_simulation=True)
    _assert_death_law(continued, INITIAL_RATE * continued.time)

    model.reset_simulation()
    assert model._network is None
    reset_run = model.simulate(**_ode_options(0.0, 1.0))
    assert model._model is parsed_model
    _assert_death_law(reset_run, INITIAL_RATE * reset_run.time)

    continued_to_two = model.simulate(
        **_ode_options(1.0, 2.0), continue_simulation=True
    )
    _assert_death_law(continued_to_two, INITIAL_RATE * continued_to_two.time)

    model.set_parameter("k", UPDATED_RATE)
    assert model._network is None
    assert model._continuation_network is not None
    with pytest.raises(RuntimeError, match="__s4_missing_stop_name__"):
        model.simulate(
            **_ode_options(2.0, 3.0),
            continue_simulation=True,
            stop_if="if(time > 2.0, __s4_missing_stop_name__, 0)",
        )
    assert model._network is not None
    assert model._network_from_continuation

    recovered = model.simulate(**_ode_options(2.0, 3.0), continue_simulation=True)
    expected_hazard = INITIAL_RATE * 2.0 + UPDATED_RATE * (recovered.time - 2.0)
    _assert_death_law(recovered, expected_hazard)
    np.testing.assert_array_equal(first.concentrations, first_snapshot)


def test_analytic_comparator_rejects_terminal_inheritance_and_continuation_reset():
    model = _model()
    first = model.simulate(**_ode_options(0.0, 1.0))
    continued = model.simulate(**_ode_options(1.0, 2.0), continue_simulation=True)

    inherited_terminal = model.simulate(**_ode_options(0.0, 1.0))
    inherited_terminal.observables["A_count"][0] = first.observables["A_count"][-1]
    with pytest.raises(AssertionError):
        _assert_death_law(inherited_terminal, INITIAL_RATE * inherited_terminal.time)

    reset_continuation = type(continued)(
        {
            "time": continued.time,
            "observables": {
                "A_count": A0 * np.exp(-INITIAL_RATE * (continued.time - 1.0)),
                "B_count": A0 - A0 * np.exp(-INITIAL_RATE * (continued.time - 1.0)),
            },
            "concentrations": continued.concentrations,
        }
    )
    with pytest.raises(AssertionError):
        _assert_death_law(reset_continuation, INITIAL_RATE * reset_continuation.time)


def test_ssa_fresh_runs_match_the_independent_survivor_mean():
    """Check the Binomial(24, exp(-0.3)) final survivor marginal.

    The fixed budget is 512 runs with distinct recorded seeds 41000..41511.
    Hoeffding's two-sided bound sets the acceptance width to 24 * sqrt(log(2000)
    / (2 * 512)), which limits the false-rejection probability to 0.001 without
    a normal approximation. The claim is limited to the final survivor mean.
    """
    model = _model()
    seed_budget = range(41000, 41512)
    survivors = []
    compiled_network = None
    for seed in seed_budget:
        result = model.simulate(
            method="ssa",
            t_start=0.0,
            t_end=1.0,
            n_steps=1,
            seed=seed,
        )
        assert result.observables["A_count"][0] == A0
        if compiled_network is None:
            compiled_network = model._network
        else:
            assert model._network is compiled_network
        survivors.append(result.observables["A_count"][-1])

    probability = np.exp(-INITIAL_RATE)
    expected_mean = A0 * probability
    acceptance_width = A0 * np.sqrt(np.log(2000.0) / (2.0 * len(survivors)))
    assert abs(float(np.mean(survivors)) - expected_mean) <= acceptance_width
