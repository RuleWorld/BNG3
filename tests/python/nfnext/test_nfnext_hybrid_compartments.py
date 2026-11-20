"""Compartment-scoped lumped populations in the public NFnext executor."""

import math

import bionetgen
import numpy as np
import pytest

MODEL = """begin model
begin parameters
  k 0.8
end parameters
begin compartments
  left 3 1
  right 3 1
end compartments
begin molecule types
  P() population
  A()
end molecule types
begin seed species
  @left:P() 20
  @right:P() 7
end seed species
begin observables
  Molecules L @left:P()
  Molecules R @right:P()
  Molecules AllP P()
  Molecules Products @left:A()
  Species L_species @left:P()
end observables
begin reaction rules
  release: @left:P() -> @left:A() k
end reaction rules
end model
"""


@pytest.mark.parametrize("particle_to_population", [False, True])
def test_nfnext_hybrid_compartment_counts_and_distribution(
    tmp_path, particle_to_population
):
    source = MODEL
    if particle_to_population:
        source = source.replace("@left:P() 20", "@left:A() 20").replace(
            "@left:P() -> @left:A() k", "@left:A() -> @left:P() k"
        )
    model_path = tmp_path / "compartments.bngl"
    model_path.write_text(source, encoding="utf-8")
    model = bionetgen.load(str(model_path))
    end = 1.0
    samples = []
    for seed in range(256):
        result = model.simulate(method="nfnext", seed=seed, t_end=end, n_steps=4)
        assert result.backend == "nfnext"
        obs = result.observables
        assert obs["L"][0] == (0 if particle_to_population else 20)
        np.testing.assert_array_equal(obs["R"], 7)
        np.testing.assert_array_equal(obs["AllP"], obs["L"] + obs["R"])
        np.testing.assert_array_equal(obs["L_species"], obs["L"])
        np.testing.assert_array_equal(obs["L"] + obs["Products"], 20)
        samples.append(obs["Products" if particle_to_population else "L"][-1])

    # Each of the twenty occupied sources independently survives with exp(-k t).
    probability = math.exp(-0.8 * end)
    expected = 20 * probability
    standard_error = math.sqrt(20 * probability * (1 - probability) / len(samples))
    assert np.mean(samples) == pytest.approx(expected, abs=5 * standard_error)


def test_nfnext_refuses_unqualified_compartmentalized_population_reactant(tmp_path):
    source = MODEL.replace("release: @left:P()", "release: P()")
    model_path = tmp_path / "ambiguous.bngl"
    model_path.write_text(source, encoding="utf-8")
    model = bionetgen.load(str(model_path))
    with pytest.raises(RuntimeError, match="unqualified reactant"):
        model.simulate(method="nfnext", seed=0, t_end=1.0, n_steps=2)


def test_nfnext_transports_lumped_population_without_loss(tmp_path):
    source = MODEL.replace("@left:P() -> @left:A() k", "@left:P() -> @right:P() k")
    model_path = tmp_path / "transport.bngl"
    model_path.write_text(source, encoding="utf-8")
    result = bionetgen.load(str(model_path)).simulate(
        method="nfnext", seed=0, t_end=1.0, n_steps=4
    )
    obs = result.observables
    np.testing.assert_array_equal(obs["AllP"], 27)
    np.testing.assert_array_equal(obs["L"] + obs["R"], 27)
    assert obs["L"][-1] < 20
    assert obs["R"][-1] > 7
