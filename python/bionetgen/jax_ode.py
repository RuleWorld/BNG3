"""JAX ODE backend for static mass-action reaction networks (opt-in)."""

from __future__ import annotations

import math
import operator
from typing import Any, Callable, Dict

import numpy as np

try:
    import jax
    import jax.numpy as jnp
    from jax import jit, lax

    _JAX_AVAILABLE = True
except ImportError:
    _JAX_AVAILABLE = False
    jax = None
    jnp = None
    jit = None
    lax = None

from bionetgen import _bionetgen_cpp as cpp


def _check_jax() -> None:
    if not _JAX_AVAILABLE:
        raise ImportError(
            "JAX ODE backend requires 'jax' and 'jaxlib' packages. "
            "Install with: pip install 'bionetgen[jax]'"
        )


def _extract_ode_data(model: Any) -> Dict[str, Any]:
    """Return the ODE compiler's reaction data for a parsed or loaded model."""
    native_model = getattr(model, "_model", model)
    if not isinstance(native_model, cpp.Model):
        raise TypeError("model must be a BNG3 Model or BioNetGenModel")

    network = cpp.generate_network(native_model)
    return cpp.jax_ode_flatten(native_model, network)


def _compile_mass_action_rhs(data: Dict[str, Any]) -> Callable:
    """Build a JIT-compiled RHS from native ODE compiler output."""
    initial_state = jnp.asarray(data["initial_state"])
    n_species = initial_state.shape[0]
    rate_constants = np.asarray(data["rate_constants"], dtype=np.float64)
    if not np.all(np.isfinite(rate_constants)):
        raise ValueError("JAX ODE requires finite mass-action rate constants")

    reactant_offsets = np.asarray(data["reactant_offsets"], dtype=np.int64)
    reactant_species = np.asarray(data["reactant_species"], dtype=np.int32)
    product_offsets = np.asarray(data["product_offsets"], dtype=np.int64)
    product_species = np.asarray(data["product_species"], dtype=np.int32)
    total_rate = np.asarray(data["total_rate"], dtype=bool)
    n_reactions = rate_constants.size

    reactant_counts = np.diff(reactant_offsets)
    max_reactants = max(1, int(reactant_counts.max(initial=0)))
    padded_reactants = np.zeros((n_reactions, max_reactants), dtype=np.int32)
    reactant_mask = np.zeros((n_reactions, max_reactants), dtype=bool)
    change_species = []
    change_reactions = []
    change_stoichiometry = []

    for reaction_index in range(n_reactions):
        start, end = reactant_offsets[reaction_index : reaction_index + 2]
        reactants = reactant_species[start:end]
        count = end - start
        if count:
            padded_reactants[reaction_index, :count] = reactants
            reactant_mask[reaction_index, :count] = True

        product_start, product_end = product_offsets[
            reaction_index : reaction_index + 2
        ]
        products = product_species[product_start:product_end]
        net_stoichiometry = {}
        for species_index in reactants:
            net_stoichiometry[species_index] = (
                net_stoichiometry.get(species_index, 0) - 1
            )
        for species_index in products:
            net_stoichiometry[species_index] = (
                net_stoichiometry.get(species_index, 0) + 1
            )
        for species_index, coefficient in net_stoichiometry.items():
            if coefficient:
                change_species.append(species_index)
                change_reactions.append(reaction_index)
                change_stoichiometry.append(coefficient)

    rate_constants_jax = jnp.asarray(rate_constants, dtype=initial_state.dtype)
    reactants_jax = jnp.asarray(padded_reactants)
    reactant_mask_jax = jnp.asarray(reactant_mask)
    total_rate_jax = jnp.asarray(total_rate)
    fixed_species_jax = jnp.asarray(data["fixed_species"], dtype=bool)
    change_species_jax = jnp.asarray(change_species, dtype=jnp.int32)
    change_reactions_jax = jnp.asarray(change_reactions, dtype=jnp.int32)
    change_stoichiometry_jax = jnp.asarray(
        change_stoichiometry, dtype=initial_state.dtype
    )

    @jit
    def rhs(time: float, state: jax.Array) -> jax.Array:
        if state.ndim != 1 or state.shape[0] != n_species:
            raise ValueError("state length must match generated network species count")

        reactant_values = jnp.where(
            reactant_mask_jax,
            state[reactants_jax],
            jnp.ones((), dtype=state.dtype),
        )
        mass_action_factors = jnp.prod(reactant_values, axis=1)
        fluxes = rate_constants_jax * jnp.where(
            total_rate_jax, jnp.ones_like(mass_action_factors), mass_action_factors
        )
        derivative = (
            jnp.zeros((n_species,), dtype=state.dtype)
            .at[change_species_jax]
            .add(change_stoichiometry_jax * fluxes[change_reactions_jax])
        )
        return jnp.where(fixed_species_jax, 0.0, derivative)

    return rhs


def _compile_rhs_from_data(data: Dict[str, Any]) -> Callable:
    functional = np.asarray(data["functional_rates"], dtype=bool)
    time_dependent = np.asarray(data["time_dependent_rates"], dtype=bool)
    if np.any(functional) or np.any(time_dependent):
        if np.any(time_dependent):
            reason = "time-dependent rate laws"
        else:
            reason = "functional rate laws"
        raise NotImplementedError(f"JAX ODE does not support {reason}")
    return _compile_mass_action_rhs(data)


def compile_rhs(model: Any) -> Callable:
    """Compile a JAX RHS from BNG3's native mass-action ODE representation.

    The native engine provides evaluated coefficients, reaction participants,
    and fixed-species flags, so this function does not parse BNGL text itself.
    Functional and time-dependent rate laws are explicitly unsupported.
    """
    _check_jax()
    return _compile_rhs_from_data(_extract_ode_data(model))


def simulate_jax_ode(
    model: Any, t_end: float, n_steps: int = 1000, method: str = "rk4"
) -> Dict[str, Any]:
    """Integrate a static mass-action model with a fixed-step JAX RK4 solver.

    The returned ``time`` and ``concentrations`` arrays use the same keys and
    axis order as :func:`bionetgen._bionetgen_cpp.simulate_ode`.
    """
    _check_jax()
    if method != "rk4":
        raise ValueError("JAX ODE currently supports only method='rk4'")
    try:
        final_time = float(t_end)
    except (TypeError, ValueError) as exc:
        raise ValueError("t_end must be finite and positive") from exc
    if not math.isfinite(final_time) or final_time <= 0.0:
        raise ValueError("t_end must be finite and positive")
    if isinstance(n_steps, bool):
        raise TypeError("n_steps must be a positive integer")
    try:
        n_steps = operator.index(n_steps)
    except TypeError as exc:
        raise TypeError("n_steps must be a positive integer") from exc
    if n_steps <= 0:
        raise ValueError("n_steps must be a positive integer")

    data = _extract_ode_data(model)
    rhs = _compile_rhs_from_data(data)
    initial_state = jnp.asarray(data["initial_state"])
    time_points = np.linspace(0.0, final_time, n_steps + 1)
    scan_times = jnp.asarray(time_points[:-1], dtype=initial_state.dtype)
    step_size = jnp.asarray(final_time / n_steps, dtype=initial_state.dtype)
    half_step = step_size * 0.5

    def rk4_step(state, time):
        k1 = rhs(time, state)
        k2 = rhs(time + half_step, state + half_step * k1)
        k3 = rhs(time + half_step, state + half_step * k2)
        k4 = rhs(time + step_size, state + step_size * k3)
        next_state = state + (step_size / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        return next_state, next_state

    # JAX lowers a fixed-length scan as one loop instead of unrolling Python iterations.
    # Source: https://docs.jax.dev/en/latest/_autosummary/jax.lax.scan.html
    _, later_states = lax.scan(rk4_step, initial_state, scan_times)
    trajectory = jnp.concatenate((initial_state[None, :], later_states), axis=0)
    return {
        "time": time_points,
        "concentrations": np.asarray(trajectory),
    }


__all__ = ["compile_rhs", "simulate_jax_ode", "_check_jax"]
