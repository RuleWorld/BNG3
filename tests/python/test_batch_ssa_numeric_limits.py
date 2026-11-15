"""Representability checks at the native batch-SSA and flattened-input boundaries."""

import numpy as np
import pytest

from bionetgen import _bionetgen_cpp as cpp


def _model_and_network(*, rate=0, population=3):
    model = cpp.parse_string(f"""begin model
begin parameters
k {rate}
end parameters
begin molecule types
A()
B()
end molecule types
begin seed species
A() {population}
B() 0
end seed species
begin reaction rules
A() -> B() k
end reaction rules
end model""")
    return model, cpp.generate_network(model)


@pytest.mark.parametrize("rate", [1e50, 1e-50])
def test_flatten_rejects_rate_overflow_and_underflow(rate):
    model, network = _model_and_network(rate=rate)
    with pytest.raises(RuntimeError, match="rate constant.*float32 range"):
        cpp.jax_ssa_flatten(model, network)


@pytest.mark.parametrize(
    "rate", [0.0, 0.2, 3.4028234663852886e38, 1.401298464324817e-45]
)
def test_flatten_keeps_representable_float32_rates(rate):
    model, network = _model_and_network(rate=rate)
    flat = cpp.jax_ssa_flatten(model, network)
    np.testing.assert_array_equal(
        flat["rate_constants"], np.asarray([rate], dtype=np.float32)
    )


@pytest.mark.parametrize("population", [2147483647.5, 2147483648, 1e100])
def test_flatten_rejects_population_outside_int32(population):
    model, network = _model_and_network(population=population)
    with pytest.raises(RuntimeError, match="population.*int32 range"):
        cpp.jax_ssa_flatten(model, network)


@pytest.mark.parametrize(
    "population, expected", [(0, 0), (3.4, 3), (3.5, 4), (2147483647, 2147483647)]
)
def test_flatten_preserves_population_rounding_within_int32(population, expected):
    model, network = _model_and_network(population=population)
    flat = cpp.jax_ssa_flatten(model, network)
    index = network.species_names.index("A()")
    assert flat["initial_species"][index] == expected


@pytest.mark.parametrize("threads", [1, 2])
def test_cpu_batch_rejects_final_population_outside_int32(threads):
    model, network = _model_and_network(population=3000000000)
    with pytest.raises(RuntimeError, match="population.*int32 range"):
        cpp.simulate_batch_ssa_cpu(
            model, network, batch_size=2, t_end=1.0, n_steps=1, threads=threads
        )


@pytest.mark.parametrize("threads", [1, 2])
def test_cpu_batch_preserves_largest_int32_population(threads):
    model, network = _model_and_network(population=2147483647)
    result = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=2, t_end=1.0, n_steps=1, threads=threads
    )
    index = network.species_names.index("A()")
    np.testing.assert_array_equal(result["final_species"][:, index], [2147483647] * 2)
    np.testing.assert_array_equal(result["event_counts"], [0, 0])
