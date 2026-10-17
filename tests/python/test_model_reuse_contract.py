"""Mutation/reuse must match fresh compilation across parameter roles (#141)."""

import numpy as np
import pytest

from bionetgen import BioNetGenModel
from _extdep import require_extension

cpp = require_extension()


def source(volume=2, population=40, rate=0.03):
    return f"""
begin model
begin parameters
    V0 {volume}
    N0 {population}
    k {rate}
    twice_k 2*k
end parameters
begin compartments
    cell 3 V0
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @cell:A() N0
    @cell:B() N0
end seed species
begin observables
    Molecules A_count @cell:A()
    Molecules B_count @cell:B()
end observables
begin reaction rules
    @cell:A() + @cell:B() -> 0 twice_k
end reaction rules
end model
"""


@pytest.mark.parametrize("method", ["ode", "ssa"])
@pytest.mark.parametrize(
    "parameter,argument,values",
    [
        ("V0", "volume", [0.5, 3, 2]),
        ("N0", "population", [10, 65, 40]),
        ("k", "rate", [0.01, 0.07, 0.03]),
    ],
)
def test_reused_model_matches_fresh_after_parameter_mutation(
    method, parameter, argument, values
):
    model = BioNetGenModel(cpp.parse_string(source()))
    options = dict(method=method, t_end=2, n_steps=8, seed=31415)
    baseline = model.simulate(**options)
    for value in values:
        previous_network = model._network
        model.set_parameter(parameter, value)
        assert model._network is None
        reused = model.simulate(**options)
        assert model._network is not previous_network
        fresh = BioNetGenModel(cpp.parse_string(source(**{argument: value})))
        expected = fresh.simulate(**options)
        np.testing.assert_array_equal(reused.time, expected.time)
        if method == "ssa":
            np.testing.assert_array_equal(
                reused.concentrations, expected.concentrations
            )
        else:
            np.testing.assert_allclose(
                reused.concentrations, expected.concentrations, rtol=1e-10, atol=1e-10
            )
            parameters = dict(volume=2, population=40, rate=0.03)
            parameters[argument] = value
            n = parameters["population"]
            analytic = n / (
                1 + 2 * parameters["rate"] * n / parameters["volume"] * reused.time
            )
            np.testing.assert_allclose(
                reused.observables["A_count"], analytic, rtol=1e-6, atol=1e-8
            )
        np.testing.assert_allclose(
            reused.observables["A_count"],
            reused.observables["B_count"],
            rtol=1e-12,
            atol=1e-12,
        )
    # Returning to the initial parameter must restore both initial state and RNG.
    np.testing.assert_allclose(
        reused.concentrations, baseline.concentrations, rtol=1e-10, atol=1e-10
    )
