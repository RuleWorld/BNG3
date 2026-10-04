"""Tests for JAX batch-SSA backend."""

import pytest

# Skip if JAX not available
jax = pytest.importorskip("jax")
jaxlib = pytest.importorskip("jaxlib")
pytest.importorskip("bionetgen")

from bionetgen import _bionetgen_cpp as cpp


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
        "num_species", "num_reactions", "num_observables",
        "initial_species", "rate_constants",
        "reactant_offsets", "reactant_species", "reactant_stoich_offsets",
        "react_change_offsets", "react_change_species",
        "prod_change_offsets", "prod_change_species",
        "obs_offsets", "obs_species", "obs_weights",
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
    """Ensure import bionetgen doesn't eagerly import jax."""
    import sys
    # Remove jax from modules if present
    for mod in list(sys.modules.keys()):
        if "jax" in mod:
            del sys.modules[mod]

    # Fresh import should not pull in jax
    import bionetgen
    assert "jax" not in sys.modules


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
