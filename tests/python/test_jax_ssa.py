"""Tests for the unavailable JAX SSA API and native network flattening."""

import subprocess
import sys

import numpy as np
import pytest

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ssa


def test_jax_ssa_unavailable_before_model_processing():
    """An unavailable backend must reject before requiring a valid network."""
    with pytest.raises(NotImplementedError, match="JAX SSA simulation is unavailable"):
        jax_ssa.simulate(None, None, batch_size=1, t_end=1.0, base_seed=42)


def test_jax_ssa_unavailable_without_optional_dependencies():
    """Missing JAX must still produce the public unavailable disposition."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.modules['jax'] = None; sys.modules['jaxlib'] = None; "
            "from bionetgen import jax_ssa\n"
            "try:\n"
            "    jax_ssa.simulate(None, None, 1, 1.0, 42)\n"
            "except NotImplementedError as exc:\n"
            "    assert 'JAX SSA simulation is unavailable' in str(exc)\n"
            "else:\n"
            "    raise AssertionError('unavailable SSA returned a result')\n",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_jax_ssa_flatten_exists():
    """Verify the flattening binding exists."""
    assert hasattr(cpp, "jax_ssa_flatten")


def test_jax_ssa_flatten_output():
    """Test that flattening produces expected structure."""
    model = cpp.parse_file("models/isomerization.bngl")
    network = cpp.generate_network(model)
    flat = cpp.jax_ssa_flatten(model, network)

    # Check required keys
    required_keys = [
        "num_species",
        "num_reactions",
        "num_observables",
        "initial_species",
        "rate_constants",
        "reactant_offsets",
        "reactant_species",
        "reactant_stoich_offsets",
        "react_change_offsets",
        "react_change_species",
        "prod_change_offsets",
        "prod_change_species",
        "obs_offsets",
        "obs_species",
        "obs_weights",
        "observable_names",
    ]
    for key in required_keys:
        assert key in flat, f"Missing key: {key}"

    # Check types and shapes
    assert flat["num_species"] == 2
    assert flat["num_reactions"] == 2
    assert len(flat["initial_species"]) == 2
    assert len(flat["rate_constants"]) == 2
    assert len(flat["reactant_offsets"]) == 3  # num_reactions + 1
    assert len(flat["obs_offsets"]) >= 1


def test_jax_ssa_import_safety():
    """Package import in a fresh interpreter must not eagerly load JAX."""
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; import bionetgen; assert 'jax' not in sys.modules",
        ],
        check=True,
    )


def test_jax_ssa_executes_batch_simulation():
    """Verify batch SSA execution produces valid trajectories with mass conservation."""
    pytest.importorskip("jax")
    model = cpp.parse_file("models/isomerization.bngl")
    network = cpp.generate_network(model)

    result = jax_ssa.simulate(
        model,
        network,
        batch_size=100,
        t_end=5.0,
        base_seed=42,
        n_steps=10,
    )

    assert result["batch_size"] == 100
    assert result["total_events"] > 0
    assert len(result["time"]) == 11
    assert "A_confR" in result["observable_means"]
    assert "A_total" in result["observable_means"]

    # Check shape of final observables and species
    assert result["final_observables"].shape == (100, 3)
    assert result["final_species"].shape == (100, 2)

    # Conservation: A + B == 20 for all trajectories in the batch
    final_sums = np.sum(result["final_species"], axis=1)
    np.testing.assert_array_equal(final_sums, np.full(100, 20))

    # Timing and throughput metrics exist and are positive
    assert result["trajectories_per_sec_sim"] > 0
    assert result["simulation_time_ms"] > 0


def test_jax_ssa_batch_reproducibility():
    """Identical base seeds must produce identical batch results."""
    pytest.importorskip("jax")
    model = cpp.parse_file("models/isomerization.bngl")
    network = cpp.generate_network(model)

    res1 = jax_ssa.simulate(model, network, batch_size=50, t_end=2.0, base_seed=12345)
    res2 = jax_ssa.simulate(model, network, batch_size=50, t_end=2.0, base_seed=12345)
    res3 = jax_ssa.simulate(model, network, batch_size=50, t_end=2.0, base_seed=99999)

    np.testing.assert_array_equal(res1["final_species"], res2["final_species"])
    np.testing.assert_array_equal(res1["final_observables"], res2["final_observables"])
    assert not np.array_equal(res1["final_species"], res3["final_species"])


def test_jax_ssa_bimolecular_conservation():
    """Verify stoichiometry and conservation on bimolecular binding model."""
    pytest.importorskip("jax")
    model = cpp.parse_string("""begin model
begin parameters
kf 0.1
kr 0.05
end parameters
begin molecule types
A(b)
B(a)
end molecule types
begin seed species
A(b) 15
B(a) 25
end seed species
begin observables
Molecules FreeA A(b)
Molecules FreeB B(a)
Molecules Complex A(b!1).B(a!1)
end observables
begin reaction rules
A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
end model""")
    network = cpp.generate_network(model)
    res = jax_ssa.simulate(model, network, batch_size=80, t_end=3.0, base_seed=777)

    # Species: A(b), B(a), A(b!1).B(a!1)
    # Total A = A + Complex == 15
    # Total B = B + Complex == 25
    final_sp = res["final_species"]
    assert final_sp.shape == (80, 3)
    np.testing.assert_array_equal(final_sp[:, 0] + final_sp[:, 2], np.full(80, 15))
    np.testing.assert_array_equal(final_sp[:, 1] + final_sp[:, 2], np.full(80, 25))


def test_jax_ssa_max_steps_guard():
    """When max_steps is set, event count per trajectory must not exceed it."""
    pytest.importorskip("jax")
    model = cpp.parse_file("models/isomerization.bngl")
    network = cpp.generate_network(model)
    res = jax_ssa.simulate(
        model, network, batch_size=50, t_end=100.0, base_seed=42, max_steps=5
    )
    assert np.all(res["event_counts"] <= 5)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
