"""Opt-in JAX backend for batched direct-SSA.

This module is only importable when `jax` and `jaxlib` are installed.
The C++ binding `jax_ssa_flatten` exports the flattened reaction network
in the same CSR layout consumed by the Metal/CUDA kernels.

Usage:
    import bionetgen
    import bionetgen.jax_ssa as jax_ssa
    result = jax_ssa.simulate(model, batch_size=10000, t_end=20.0, base_seed=12345)
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

try:
    import jax
    import jax.numpy as jnp
    from jax import lax
    _JAX_AVAILABLE = True
except ImportError:
    _JAX_AVAILABLE = False
    jax = None
    jnp = None
    lax = None

from bionetgen import _bionetgen_cpp as cpp


def _check_jax() -> None:
    if not _JAX_AVAILABLE:
        raise ImportError(
            "JAX backend requires 'jax' and 'jaxlib' packages. "
            "Install with: pip install 'bionetgen[jax]'"
        )


# JAX-compatible PCG32 matching Metal/CUDA kernels exactly
@jax.jit
def _pcg32_step(state: jnp.uint64, inc: jnp.uint64) -> Tuple[jnp.uint64, jnp.uint64]:
    """PCG32 step function (Metal/CUDA kernel exact port)."""
    new_state = state * jnp.uint64(6364136223846793005) + inc
    return new_state, inc


@jax.jit
def _pcg32_next_u32(state: jnp.uint64, inc: jnp.uint64) -> Tuple[jnp.uint64, jnp.uint32, jnp.uint64]:
    """PCG32 next_u32 exact port."""
    old_state = state
    new_state, new_inc = _pcg32_step(state, inc)
    xorshifted = ((old_state >> jnp.uint64(18)) ^ old_state) >> jnp.uint64(27)
    rot = (old_state >> jnp.uint64(59)).astype(jnp.uint32)
    xorshifted_32 = xorshifted.astype(jnp.uint32)
    result = (xorshifted_32 >> rot) | (xorshifted_32 << ((-rot.astype(jnp.int32)) & jnp.uint32(31)))
    return new_state, new_inc, result


@jax.jit
def _pcg32_next_float01(state: jnp.uint64, inc: jnp.uint64) -> Tuple[jnp.uint64, jnp.uint64, jnp.float32]:
    """PCG32 next_float01 exact port."""
    new_state, new_inc, u32 = _pcg32_next_u32(state, inc)
    # (u32 >> 8) + 1.0) / 16777218.0
    val = ((u32 >> jnp.uint32(8)).astype(jnp.float32) + 1.0) / jnp.float32(16777218.0)
    return new_state, new_inc, val


@jax.jit
def _compute_propensity(r: int, rate_constants: jnp.ndarray,
                        reactant_offsets: jnp.ndarray,
                        reactant_species: jnp.ndarray,
                        reactant_stoich_offsets: jnp.ndarray,
                        y: jnp.ndarray) -> jnp.float32:
    """Compute propensity for reaction r."""
    prop = rate_constants[r]
    r_start = reactant_offsets[r]
    r_end = reactant_offsets[r + 1]
    # Note: for simplicity, we don't handle the <=64 species local_y path here
    # The JAX implementation uses the general path
    for i in range(r_start, r_end):
        pop = y[reactant_species[i]]
        offset = reactant_stoich_offsets[i]
        eff = jnp.maximum(jnp.float32(0.0), pop - offset)
        prop = prop * eff
    return prop


def _simulate_trajectory_jax(
    flat: Dict[str, Any],
    initial_species: jnp.ndarray,
    base_seed: int,
    traj_id: int,
    t_end: float,
    max_steps: int,
) -> Tuple[jnp.ndarray, int]:
    """Simulate one trajectory using JAX (lax.while_loop)."""
    _ = flat["num_species"]
    num_reactions = flat["num_reactions"]
    num_observables = flat["num_observables"]
    num_output_points = flat["obs_offsets"].shape[0] - 1
    output_times = flat["output_times"] if "output_times" in flat else jnp.linspace(0.0, t_end, 11)

    # Initialize state
    y = initial_species.astype(jnp.int32)

    # RNG seeding matching Metal/CUDA: PCG32 with seed = 123456789 + base_seed, seq = traj_id
    rng_state = jnp.uint64(123456789 + base_seed)
    rng_inc = (jnp.uint64(traj_id) << jnp.uint64(1)) | jnp.uint64(1)
    rng_state, rng_inc = _pcg32_step(rng_state, rng_inc)
    rng_state += jnp.uint64(123456789 + base_seed)
    rng_state, rng_inc = _pcg32_step(rng_state, rng_inc)

    # Output recording
    obs_buffer = jnp.zeros((num_output_points, num_observables), dtype=jnp.float32)
    next_output_idx = 0
    _ = 0

    # Record initial state
    def record_obs(y_state, time_idx):
        for g in range(num_observables):
            start = int(flat["obs_offsets"][g])
            end = int(flat["obs_offsets"][g + 1])
            species_idx = flat["obs_species"][start:end]
            weights = flat["obs_weights"][start:end]
            pops = y_state[species_idx].astype(jnp.float32)
            obs_buffer = obs_buffer.at[time_idx, g].set(jnp.sum(pops * weights))
        return obs_buffer

    # Initial outputs
    t = jnp.float32(0.0)
    while next_output_idx < num_output_points and output_times[next_output_idx] <= t + 1e-6:
        obs_buffer = record_obs(y, next_output_idx)
        next_output_idx += 1

    # Main SSA loop
    def cond_fn(state):
        t, y_state, rng_s, rng_i, next_out, events, _ = state
        return t < flat["t_end"]

    def body_fn(state):
        t, y_state, rng_s, rng_i, next_out, events, obs_buf = state

        # Record outputs up to current time
        def record_up_to(t_val, next_out_idx, obs_buffer):
            while next_out_idx < num_output_points and output_times[next_out_idx] <= t_val + 1e-6:
                for g in range(num_observables):
                    start = int(flat["obs_offsets"][g])
                    end = int(flat["obs_offsets"][g + 1])
                    species_idx = flat["obs_species"][start:end]
                    weights = flat["obs_weights"][start:end]
                    pops = y_state[species_idx].astype(jnp.float32)
                    obs_buffer = obs_buffer.at[next_out_idx, g].set(jnp.sum(pops * weights))
                next_out_idx += 1
            return next_out_idx, obs_buffer

        next_out, obs_buf = record_up_to(t, next_out, obs_buf)

        # Pass 1: compute total propensity
        total_prop = jnp.float32(0.0)
        for r in range(num_reactions):
            total_prop += _compute_propensity(r, flat["rate_constants"],
                                             flat["reactant_offsets"],
                                             flat["reactant_species"],
                                             flat["reactant_stoich_offsets"],
                                             y_state)

        # Check for termination
        def terminate(state):
            t, y_state, rng_s, rng_i, next_out, events, obs_buf = state
            return (state[0], state[1], state[2], state[3], state[4], state[5], state[6])

        def continue_sim(state):
            t, y_state, rng_s, rng_i, next_out, events, obs_buf = state

            # Sample tau
            rng_s, rng_i, r1 = _pcg32_next_float01(rng_s, rng_i)
            tau = -jnp.log(r1) / total_prop

            def event_too_late(state):
                t, y_state, rng_s, rng_i, next_out, events, obs_buf = state
                return (flat["t_end"], y_state, rng_s, rng_i, next_out, events, obs_buf)

            def event_ok(state):
                t, y_state, rng_s, rng_i, next_out, events, obs_buf = state
                event_time = t + tau

                # Record outputs before event
                next_out2, obs_buf2 = record_up_to(event_time, next_out, obs_buf)

                # Update time
                t2 = event_time

                # Pass 2: reaction selection
                rng_s, rng_i, r2 = _pcg32_next_float01(rng_s, rng_i)
                _ = r2 * total_prop
                cum = jnp.float32(0.0)
                _ = num_reactions - 1

                for r in range(num_reactions):
                    prop = _compute_propensity(r, flat["rate_constants"],
                                              flat["reactant_offsets"],
                                              flat["reactant_species"],
                                              flat["reactant_stoich_offsets"],
                                              y_state)
                    cum = cum + prop
                    # We can't break in JAX, so use argmax on (cum >= target)
                    # Simplified: find first index where cum >= target
                    # For now, use lax.cond chain (simplified)
                    pass

                # This is a simplified version - full implementation needs
                # proper JAX control flow for the reaction selection
                # For now, return the state for continuation
                return (t2, y_state, rng_s, rng_i, next_out2, events + 1, obs_buf2)

            # Simplified: just check if tau would exceed t_end
            return lax.cond(t + tau > flat["t_end"],
                           terminate, continue_sim, state)

        # This is a placeholder - full implementation requires
        # proper JAX control flow with lax.while_loop
        pass

    # For now, raise not implemented
    raise NotImplementedError(
        "Full JAX direct-SSA implementation requires complete lax.while_loop "
        "with proper control flow. The binding and flattening are ready; "
        "the kernel implementation is in progress."
    )


def simulate(model, network, batch_size: int, t_end: float, base_seed: int,
             n_steps: int = 10, max_steps: int = 0) -> Dict[str, Any]:
    """Simulate batch SSA using JAX backend (opt-in).

    Args:
        model: BNGL model
        network: GeneratedNetwork
        batch_size: Number of trajectories
        t_end: Simulation end time
        base_seed: Base seed for PCG32
        n_steps: Number of output time points
        max_steps: Maximum SSA steps per trajectory (0 = unlimited)

    Returns:
        Dict with 'observables', 'event_counts', 'device'
    """
    _check_jax()

    # Flatten the network using C++ binding
    flat = cpp.jax_ssa_flatten(model, network)

    # Convert to JAX arrays
    _ = jnp.array(flat["initial_species"], dtype=jnp.int32)

    # For now, this is a stub - full implementation in progress
    raise NotImplementedError(
        "JAX batch-SSA backend is under development. "
        "The C++ binding for network flattening is available via "
        "`cpp.jax_ssa_flatten(model, network)`. "
        "Full JAX kernel with lax.while_loop and exact PCG32 port "
        "is being implemented."
    )


__all__ = ["simulate", "_check_jax"]
