"""Mutation/reuse must match fresh compilation across parameter roles (#141)."""

import numpy as np
import pytest

import bionetgen
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


@pytest.mark.parametrize("rate", [0.01, 0.07])
def test_replacing_timed_parameter_reclassifies_transitive_rate(rate):
    model = BioNetGenModel(cpp.parse_string(source(rate="time()")))
    timed = model.simulate(method="ode", t_end=2, n_steps=8)
    population = 40
    volume = 2
    np.testing.assert_allclose(
        timed.observables["A_count"],
        population / (1 + population * timed.time**2 / volume),
        rtol=2e-5,
        atol=1e-8,
    )

    model.set_parameter("k", rate)
    options = dict(t_end=2, n_steps=8)
    reused = model.simulate(method="ode", **options)
    fresh_static = BioNetGenModel(cpp.parse_string(source(rate=rate)))
    expected = fresh_static.simulate(method="ode", **options)
    np.testing.assert_array_equal(reused.time, expected.time)
    np.testing.assert_allclose(
        reused.concentrations, expected.concentrations, rtol=1e-10, atol=1e-10
    )
    np.testing.assert_allclose(
        reused.observables["A_count"],
        population / (1 + 2 * rate * population / volume * reused.time),
        rtol=1e-6,
        atol=1e-8,
    )

    reused_nf = model.simulate(method="nf", seed=31415, **options)
    fresh_nf = fresh_static.simulate(method="nf", seed=31415, **options)
    np.testing.assert_array_equal(reused_nf.time, fresh_nf.time)
    np.testing.assert_array_equal(reused_nf.concentrations, fresh_nf.concentrations)


def _action_source(actions):
    return f"""
begin model
begin parameters
    k 0.4
    N 20
    V 1
end parameters
begin compartments
    cell 3 V
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @cell:A() N
    @cell:B() 0
end seed species
begin observables
    Molecules A_count @cell:A()
    Molecules B_count @cell:B()
end observables
begin reaction rules
    forward: @cell:A() -> @cell:B() k
end reaction rules
begin actions
{actions}
end actions
end model
"""


def test_action_execution_invalidates_the_cached_generated_network(tmp_path):
    """A topology-changing action must not leave a stale network cached."""
    fragment = tmp_path / "fragment.bngl"
    fragment.write_text("""begin model
begin molecule types
    D()
end molecule types
begin seed species
    @cell:D() 5
end seed species
begin observables
    Molecules D_count @cell:D()
end observables
end model
""")
    source = tmp_path / "control.bngl"
    source.write_text(_action_source('  include_model({file=>"fragment.bngl"})'))
    model = bionetgen.load(str(source))
    before = model.generate_network()
    assert "@cell::D()" not in list(before.species_names)

    model.execute()

    # The action added a species, so the network compiled before the action
    # no longer describes the model.
    assert model._network is None
    after = model.generate_network()
    assert "@cell::D()" in list(after.species_names)

    merged = tmp_path / "merged.bngl"
    merged.write_text("""begin model
begin parameters
    k 0.4
    N 20
    V 1
end parameters
begin compartments
    cell 3 V
end compartments
begin molecule types
    A()
    B()
    D()
end molecule types
begin seed species
    @cell:A() N
    @cell:B() 0
    @cell:D() 5
end seed species
begin observables
    Molecules A_count @cell:A()
    Molecules B_count @cell:B()
    Molecules D_count @cell:D()
end observables
begin reaction rules
    forward: @cell:A() -> @cell:B() k
end reaction rules
end model
""")
    options = dict(method="ode", t_end=2, n_steps=8, rtol=1e-10, atol=1e-12)
    reused = model.simulate(**options)
    fresh = bionetgen.load(str(merged)).simulate(**options)
    np.testing.assert_array_equal(reused.time, fresh.time)
    np.testing.assert_allclose(
        reused.observables["D_count"],
        fresh.observables["D_count"],
        rtol=1e-10,
        atol=1e-10,
    )
    assert float(reused.observables["D_count"][0]) == pytest.approx(5.0)


def test_volume_action_invalidates_the_cached_generated_network(tmp_path):
    """A compartment-volume action must not leave a stale network cached."""
    source = tmp_path / "volume.bngl"
    source.write_text(_action_source('  setVolume({target=>"cell",value=>4})'))
    model = bionetgen.load(str(source))
    model.generate_network()

    model.execute()

    assert model._network is None
    reference = tmp_path / "volume-reference.bngl"
    reference.write_text(_action_source("").replace("cell 3 V", "cell 3 4"))
    options = dict(method="ode", t_end=2, n_steps=8, rtol=1e-10, atol=1e-12)
    reused = model.simulate(**options)
    fresh = bionetgen.load(str(reference)).simulate(**options)
    np.testing.assert_array_equal(reused.time, fresh.time)
    np.testing.assert_allclose(
        reused.concentrations, fresh.concentrations, rtol=1e-10, atol=1e-10
    )
