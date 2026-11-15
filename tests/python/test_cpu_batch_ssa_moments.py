"""CPU ensemble moments must reflect the returned trajectory samples."""

import numpy as np
import pytest

from bionetgen import _bionetgen_cpp as cpp


def _model_and_network(population, rule=""):
    model = cpp.parse_string(f"""begin model
begin molecule types
A()
end molecule types
begin seed species
A() {population}
end seed species
begin observables
Molecules CountA A()
end observables
begin reaction rules
{rule}
end reaction rules
end model""")
    return model, cpp.generate_network(model)


@pytest.mark.parametrize("threads", [1, 2])
def test_constant_cpu_batch_has_zero_standard_deviation(threads):
    model, network = _model_and_network(123456789)
    result = cpp.simulate_batch_ssa_cpu(
        model, network, batch_size=17, t_end=1.0, n_steps=2, threads=threads
    )

    np.testing.assert_array_equal(result["final_species"], [[123456789]] * 17)
    np.testing.assert_array_equal(result["event_counts"], np.zeros(17))
    np.testing.assert_array_equal(result["observable_stds"]["CountA"], np.zeros(3))


@pytest.mark.parametrize("threads", [1, 2])
@pytest.mark.parametrize("population", [0, 100000000])
def test_cpu_batch_standard_deviation_matches_raw_samples(threads, population):
    model, network = _model_and_network(population, "0 -> A() 2")
    result = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=32,
        t_end=1.0,
        n_steps=2,
        threads=threads,
        base_seed=42,
    )

    samples = np.asarray(result["final_species"][:, 0], dtype=np.float64)
    expected_std = np.std(samples, ddof=0)
    assert expected_std > 0.0
    np.testing.assert_allclose(
        result["observable_stds"]["CountA"][-1],
        expected_std,
        rtol=8 * np.finfo(np.float32).eps,
        atol=0.0,
    )
    assert result["observable_stds"]["CountA"][0] == 0.0
    assert result["observable_means"]["CountA"][-1] == np.float32(samples.mean())
