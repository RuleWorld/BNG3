"""Separate installed-extra and unavailable-dependency checks for #473.

The installed campaign and the absent-dependency diagnostics are intentionally
independent: a passing diagnostic control must never be counted as installed
JAX scientific execution.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys

if (
    sys.platform == "darwin"
    and "JAX_PLATFORMS" not in os.environ
    and "JAX_PLATFORM_NAME" not in os.environ
):
    os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np
import pytest

from bionetgen import _bionetgen_cpp as cpp


def _isolated(code):
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_unavailable_jax_diagnostics_are_separate_and_actionable():
    """ODE raises ImportError; SSA raises NotImplementedError; both name the extra."""
    _isolated("""
import sys
sys.modules['jax'] = None
sys.modules['jaxlib'] = None
from bionetgen import jax_ode
try:
    jax_ode.compile_rhs(None)
except ImportError as exc:
    assert "bionetgen[jax]" in str(exc), str(exc)
else:
    raise AssertionError('missing JAX did not raise from jax_ode')
""")
    _isolated("""
import sys
sys.modules['jax'] = None
sys.modules['jaxlib'] = None
from bionetgen import jax_ssa
try:
    jax_ssa.simulate(None, None, 1, 1.0, 42)
except NotImplementedError as exc:
    assert "bionetgen[jax]" in str(exc), str(exc)
else:
    raise AssertionError('missing JAX did not raise from jax_ssa')
""")


def test_package_import_does_not_require_jax():
    """Importing bionetgen (and both adapters) stays safe without the extra."""
    _isolated("""
import sys
sys.modules['jax'] = None
sys.modules['jaxlib'] = None
import bionetgen
from bionetgen import jax_ode, jax_ssa
assert 'jax' not in sys.modules or sys.modules['jax'] is None
assert jax_ode._JAX_AVAILABLE is False
assert jax_ssa._JAX_AVAILABLE is False
""")


def test_installed_optional_extra_is_real_and_executes_end_to_end():
    """With JAX installed, the CPU extra runs ODE and SSA through the package."""
    jax = pytest.importorskip("jax")
    pytest.importorskip("jaxlib")
    requirements = importlib.metadata.requires("bionetgen") or []
    jax_extra = [r for r in requirements if r.startswith("jax")]
    assert any("jax" in r for r in jax_extra), jax_extra
    assert jax.default_backend() == "cpu", jax.devices()

    from bionetgen import jax_ode, jax_ssa

    model = cpp.parse_string("""begin model
begin parameters
kf 0.2
kr 0.1
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
Molecules ObsA A()
Molecules ObsB B()
end observables
begin reaction rules
A() <-> B() kf, kr
end reaction rules
end model
""")
    network = cpp.generate_network(model)
    ode = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=20)
    assert np.isfinite(ode["concentrations"]).all()
    np.testing.assert_allclose(ode["concentrations"].sum(axis=1), 10.0, atol=1e-4)
    ssa = jax_ssa.simulate(
        model, network, batch_size=64, t_end=2.0, n_steps=5, base_seed=42
    )
    np.testing.assert_array_equal(ssa["final_species"].sum(axis=1), np.full(64, 10))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
