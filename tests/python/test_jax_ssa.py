"""Tests for the unavailable JAX SSA API and native network flattening."""

import subprocess
import sys

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
