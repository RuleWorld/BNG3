"""Opt-in JAX backend for batched direct-SSA simulation.

This module provides batched Stochastic Simulation Algorithm (SSA) execution
accelerated by JAX. It consumes the flattened reaction network exported by
`cpp.jax_ssa_flatten`, matching the exact CSR structure and stoichiometry
used by the native and accelerator engines.
"""

from __future__ import annotations

import math
import operator
import os
import sys
import time as _time
from typing import Any, Dict, Optional

# On Darwin (macOS), the experimental jax-metal plugin is incompatible with
# recent StableHLO bytecode (error code 22). Default to CPU unless explicitly overridden.
if sys.platform == "darwin" and "JAX_PLATFORMS" not in os.environ and "JAX_PLATFORM_NAME" not in os.environ:
    os.environ["JAX_PLATFORMS"] = "cpu"

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

import numpy as np
from bionetgen import _bionetgen_cpp as cpp


def _check_jax() -> None:
    if not _JAX_AVAILABLE:
        raise NotImplementedError(
            "JAX SSA simulation is unavailable in BNG3. "
            "The 'jax' and 'jaxlib' packages are required. "
            "Install with: pip install 'bionetgen[jax]'"
        )
    try:
        _ = jnp.zeros(1) + 1.0
    except Exception:
        jax.config.update("jax_platform_name", "cpu")


def simulate(
    model: Any,
    network: Any = None,
    batch_size: int = 1000,
    t_end: float = 10.0,
    base_seed: int = 42,
    n_steps: int = 10,
    max_steps: int = 0,
) -> Dict[str, Any]:
    """Run batched Gillespie direct SSA simulation using JAX.

    Args:
        model: A BNG3 Model or BioNetGenModel.
        network: Optional GeneratedNetwork; generated automatically if None.
        batch_size: Number of parallel stochastic trajectories to simulate.
        t_end: Final simulation time (must be positive).
        base_seed: Base integer seed for the random number generator.
        n_steps: Number of uniform output time intervals.
        max_steps: Optional maximum number of reaction events per trajectory (0 for unlimited).

    Returns:
        Dict matching the BatchSsaMetrics schema:
        - "batch_size": number of trajectories
        - "total_events": total reaction events fired across all trajectories
        - "time": 1D array of output time points
        - "observable_means": dict of {name: 1D mean trajectory}
        - "observable_stds": dict of {name: 1D std dev trajectory}
        - "final_observables": 2D array [batch_size, num_observables]
        - "observable_names": list of observable names
        - "final_species": 2D array [batch_size, num_species]
        - "event_counts": 1D array of event counts per trajectory
        - "simulation_time_ms": simulation wall time in milliseconds
        - "total_wall_time_ms": total elapsed time in milliseconds
        - "trajectories_per_sec_sim": throughput in trajectories/sec
    """
    _check_jax()
    if model is None:
        raise NotImplementedError(
            "JAX SSA simulation is unavailable in BNG3: model must not be None."
        )

    t_wall_start = _time.perf_counter()

    native_model = getattr(model, "_model", model)
    if network is None:
        network = cpp.generate_network(native_model)

    flat = cpp.jax_ssa_flatten(native_model, network)

    try:
        final_time = float(t_end)
    except (TypeError, ValueError) as exc:
        raise ValueError("t_end must be finite and positive") from exc
    if not math.isfinite(final_time) or final_time <= 0.0:
        raise ValueError("t_end must be finite and positive")

    try:
        batch_size = operator.index(batch_size)
    except TypeError as exc:
        raise TypeError("batch_size must be a positive integer") from exc
    if batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")

    try:
        n_steps = operator.index(n_steps)
    except TypeError as exc:
        raise TypeError("n_steps must be a positive integer") from exc
    if n_steps <= 0:
        raise ValueError("n_steps must be a positive integer")

    S = flat["num_species"]
    R = flat["num_reactions"]
    G = flat["num_observables"]

    delta_V = np.zeros((R, S), dtype=np.int32)
    react_offsets = flat["react_change_offsets"]
    react_species = flat["react_change_species"]
    prod_offsets = flat["prod_change_offsets"]
    prod_species = flat["prod_change_species"]

    for r in range(R):
        for i in range(react_offsets[r], react_offsets[r + 1]):
            delta_V[r, react_species[i]] -= 1
        for i in range(prod_offsets[r], prod_offsets[r + 1]):
            delta_V[r, prod_species[i]] += 1

    obs_W = np.zeros((S, G), dtype=np.float32)
    obs_offsets = flat["obs_offsets"]
    obs_species = flat["obs_species"]
    obs_weights = flat["obs_weights"]
    for g in range(G):
        for i in range(obs_offsets[g], obs_offsets[g + 1]):
            obs_W[obs_species[i], g] = obs_weights[i]

    reactant_offsets = flat["reactant_offsets"]
    reactant_counts = np.diff(reactant_offsets)
    max_reactants = max(1, int(reactant_counts.max(initial=0)))
    padded_reactants = np.zeros((R, max_reactants), dtype=np.int32)
    padded_offsets = np.zeros((R, max_reactants), dtype=np.float32)
    reactant_mask = np.zeros((R, max_reactants), dtype=bool)

    for r in range(R):
        count = reactant_offsets[r + 1] - reactant_offsets[r]
        if count > 0:
            padded_reactants[r, :count] = flat["reactant_species"][
                reactant_offsets[r] : reactant_offsets[r + 1]
            ]
            padded_offsets[r, :count] = flat["reactant_stoich_offsets"][
                reactant_offsets[r] : reactant_offsets[r + 1]
            ]
            reactant_mask[r, :count] = True

    j_delta_V = jnp.asarray(delta_V)
    j_obs_W = jnp.asarray(obs_W)
    j_rate_constants = jnp.asarray(flat["rate_constants"], dtype=jnp.float32)
    j_padded_reactants = jnp.asarray(padded_reactants)
    j_padded_offsets = jnp.asarray(padded_offsets)
    j_reactant_mask = jnp.asarray(reactant_mask)
    j_initial_species = jnp.asarray(flat["initial_species"], dtype=jnp.int32)
    time_grid = np.linspace(0.0, final_time, n_steps + 1)
    j_time_grid = jnp.asarray(time_grid, dtype=jnp.float32)

    def compute_propensities(y):
        pops = y[j_padded_reactants].astype(jnp.float32)
        eff = jnp.maximum(0.0, pops - j_padded_offsets)
        factors = jnp.where(j_reactant_mask, eff, 1.0)
        return j_rate_constants * jnp.prod(factors, axis=-1)

    def simulate_one(rng_key):
        init_obs = j_initial_species.astype(jnp.float32) @ j_obs_W
        obs_history = (
            jnp.zeros((n_steps + 1, G), dtype=jnp.float32).at[0].set(init_obs)
        )

        init_val = (
            jnp.float32(0.0),
            j_initial_species,
            rng_key,
            jnp.uint32(0),
            obs_history,
            jnp.int32(1),
        )

        def cond_fun(val):
            t, y, key, events, obs, next_idx = val
            not_done = (t < final_time) & (next_idx <= n_steps)
            if max_steps > 0:
                not_done = not_done & (events < max_steps)
            return not_done

        def body_fun(val):
            t, y, key, events, obs, next_idx = val
            props = compute_propensities(y)
            a0 = jnp.sum(props)

            key, k1, k2 = jax.random.split(key, 3)
            u1 = jax.random.uniform(k1, minval=1e-12, maxval=1.0)
            u2 = jax.random.uniform(k2, minval=0.0, maxval=1.0)

            tau = jnp.where(a0 > 0.0, -jnp.log(u1) / a0, jnp.float32(1e30))
            t_event = t + tau

            grid_t = j_time_grid[jnp.minimum(next_idx, n_steps)]
            reach_grid = (grid_t <= t_event) & (grid_t <= final_time)

            def step_grid():
                curr_obs = y.astype(jnp.float32) @ j_obs_W
                new_obs = obs.at[next_idx].set(curr_obs)
                return (grid_t, y, key, events, new_obs, next_idx + 1)

            def step_event():
                cum = jnp.cumsum(props)
                target = u2 * a0
                r_idx = jnp.argmax(cum >= target)
                new_y = y + j_delta_V[r_idx]
                return (t_event, new_y, key, events + 1, obs, next_idx)

            return lax.cond(reach_grid, step_grid, step_event)

        final_t, final_y, final_key, final_events, final_obs, final_idx = (
            lax.while_loop(cond_fun, body_fun, init_val)
        )

        def fill_remaining(val):
            idx, obs = val
            curr_obs = final_y.astype(jnp.float32) @ j_obs_W
            return (idx + 1, obs.at[idx].set(curr_obs))

        def fill_cond(val):
            idx, obs = val
            return idx <= n_steps

        _, completed_obs = lax.while_loop(
            fill_cond, fill_remaining, (final_idx, final_obs)
        )

        return final_y, final_events, completed_obs

    master_key = jax.random.PRNGKey(base_seed)
    keys = jax.random.split(master_key, batch_size)

    t_sim_start = _time.perf_counter()
    vmapped_sim = jax.jit(jax.vmap(simulate_one))
    final_y_batch, events_batch, obs_batch = vmapped_sim(keys)
    final_y_batch.block_until_ready()
    t_sim_end = _time.perf_counter()

    sim_time_sec = max(1e-6, t_sim_end - t_sim_start)
    wall_time_sec = max(1e-6, _time.perf_counter() - t_wall_start)

    np_final_species = np.asarray(final_y_batch)
    np_event_counts = np.asarray(events_batch)
    np_obs_batch = np.asarray(obs_batch)

    mean_obs = np.mean(np_obs_batch, axis=0)
    std_obs = np.std(np_obs_batch, axis=0)
    final_observables = np_obs_batch[:, -1, :]

    obs_names = flat["observable_names"]
    obs_means_dict = {
        name: mean_obs[:, g] for g, name in enumerate(obs_names)
    }
    obs_stds_dict = {
        name: std_obs[:, g] for g, name in enumerate(obs_names)
    }

    return {
        "batch_size": batch_size,
        "total_events": int(np.sum(np_event_counts)),
        "time": time_grid,
        "observable_means": obs_means_dict,
        "observable_stds": obs_stds_dict,
        "final_observables": final_observables,
        "observable_names": obs_names,
        "final_species": np_final_species,
        "event_counts": np_event_counts,
        "trajectories_per_sec_sim": float(batch_size / sim_time_sec),
        "trajectories_per_sec_total": float(batch_size / wall_time_sec),
        "simulation_time_ms": float(sim_time_sec * 1000.0),
        "total_wall_time_ms": float(wall_time_sec * 1000.0),
    }


__all__ = ["simulate", "_check_jax"]
