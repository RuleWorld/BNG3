"""JAX SSA simulation is currently unavailable in BNG3.

The native ``jax_ssa_flatten`` binding exports network data. It does not
provide a JAX simulation backend, so the public simulation entry point fails
explicitly until a complete, validated implementation is available.
"""

from __future__ import annotations

from typing import Any, Dict


def simulate(
    model: Any,
    network: Any,
    batch_size: int,
    t_end: float,
    base_seed: int,
    n_steps: int = 10,
    max_steps: int = 0,
) -> Dict[str, Any]:
    """Raise because the JAX batch-SSA simulation backend is unavailable."""
    raise NotImplementedError(
        "JAX SSA simulation is unavailable in BNG3. "
        "The native jax_ssa_flatten binding only exports network data."
    )


__all__ = ["simulate"]
