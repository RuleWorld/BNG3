"""JAX ODE backend for static mass-action and dynamic time-dependent reaction networks (opt-in)."""

from __future__ import annotations

import math
import operator
import os
import sys
from typing import Any, Callable, Dict, Optional

# On Darwin (macOS), the experimental jax-metal plugin is incompatible with
# recent StableHLO bytecode (error code 22). Default to CPU unless explicitly overridden.
if (
    sys.platform == "darwin"
    and "JAX_PLATFORMS" not in os.environ
    and "JAX_PLATFORM_NAME" not in os.environ
):
    os.environ["JAX_PLATFORMS"] = "cpu"

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
    try:
        _ = jnp.zeros(1) + 1.0
    except Exception:
        jax.config.update("jax_platform_name", "cpu")


def _extract_ode_data(model: Any) -> Dict[str, Any]:
    """Return the ODE compiler's reaction data for a parsed or loaded model."""
    native_model = getattr(model, "_model", model)
    if not isinstance(native_model, cpp.Model):
        raise TypeError("model must be a BNG3 Model or BioNetGenModel")

    network = cpp.generate_network(native_model)
    data = cpp.jax_ode_flatten(native_model, network)
    snapshot = cpp._compiled_snapshot(native_model)
    data["snapshot"] = snapshot
    data["reaction_rules"] = list(network.reaction_rules)
    data["reaction_factors"] = list(network.reaction_factors)
    return data


def _as_jax_float(values: Any, name: str, dtype: Any) -> jax.Array:
    """Reject overflow and subnormal inputs before casting native values."""
    values = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"JAX ODE requires finite {name}")
    dtype = np.dtype(dtype)
    if np.issubdtype(dtype, np.floating):
        limits = np.finfo(dtype)
        magnitude = np.abs(values)
        if np.any(magnitude > limits.max) or np.any(
            (magnitude != 0) & (magnitude < limits.tiny)
        ):
            raise ValueError(f"{name} lie outside JAX {dtype} normal dtype range")
    return jnp.asarray(values, dtype=dtype)


def _expr_contains_observable(node: Any, functions: Dict[int, Any]) -> bool:
    """Check whether a resolved expression tree references observables."""
    if not isinstance(node, dict):
        return False
    kind = node.get("kind")
    if kind == "observable_ref":
        return True
    if kind == "function_ref":
        fn_idx = node.get("symbol", {}).get("index")
        if fn_idx in functions:
            return _expr_contains_observable(
                functions[fn_idx].get("expression", {}), functions
            )
    for arg in node.get("arguments", []):
        if _expr_contains_observable(arg, functions):
            return True
    return False


def _eval_expr(
    node: Dict[str, Any],
    time: Any,
    params: Any,
    functions: Dict[int, Any],
    dtype: Any,
) -> Any:
    """Recursively evaluate a resolved expression using JAX primitives."""
    if not isinstance(node, dict):
        raise ValueError(f"Invalid expression node: {node}")
    kind = node.get("kind")
    if kind == "number":
        return jnp.asarray(node["value"], dtype=dtype)
    elif kind == "time_ref":
        return time
    elif kind == "builtin_call":
        builtin = node.get("builtin")
        args = [
            _eval_expr(arg, time, params, functions, dtype)
            for arg in node.get("arguments", [])
        ]
        if builtin == "time":
            return time
        elif builtin == "abs":
            return jnp.abs(args[0])
        elif builtin == "acos":
            return jnp.arccos(args[0])
        elif builtin == "acosh":
            return jnp.arccosh(args[0])
        elif builtin == "asin":
            return jnp.arcsin(args[0])
        elif builtin == "asinh":
            return jnp.arcsinh(args[0])
        elif builtin == "atan":
            return jnp.arctan(args[0])
        elif builtin == "atanh":
            return jnp.arctanh(args[0])
        elif builtin == "ceil":
            return jnp.ceil(args[0])
        elif builtin == "cos":
            return jnp.cos(args[0])
        elif builtin == "cosh":
            return jnp.cosh(args[0])
        elif builtin == "e":
            return jnp.asarray(math.e, dtype=dtype)
        elif builtin == "exp":
            return jnp.exp(args[0])
        elif builtin == "floor":
            return jnp.floor(args[0])
        elif builtin == "if":
            return jnp.where(args[0], args[1], args[2])
        elif builtin == "ln":
            return jnp.log(args[0])
        elif builtin == "log10":
            return jnp.log10(args[0])
        elif builtin == "log2":
            return jnp.log2(args[0])
        elif builtin == "max":
            return jnp.maximum(args[0], args[1])
        elif builtin == "min":
            return jnp.minimum(args[0], args[1])
        elif builtin == "pi":
            return jnp.asarray(math.pi, dtype=dtype)
        elif builtin == "rint":
            return jnp.round(args[0])
        elif builtin == "sign":
            return jnp.sign(args[0])
        elif builtin == "sin":
            return jnp.sin(args[0])
        elif builtin == "sinh":
            return jnp.sinh(args[0])
        elif builtin == "sqrt":
            return jnp.sqrt(args[0])
        elif builtin == "tan":
            return jnp.tan(args[0])
        elif builtin == "tanh":
            return jnp.tanh(args[0])
        else:
            raise NotImplementedError(
                f"JAX ODE does not support builtin function '{builtin}'"
            )
    elif kind == "parameter_ref":
        idx = node["symbol"]["index"]
        return params[idx]
    elif kind == "function_ref":
        idx = node["symbol"]["index"]
        if idx in functions:
            return _eval_expr(
                functions[idx]["expression"], time, params, functions, dtype
            )
        raise NotImplementedError(f"Function index {idx} not found in model functions")
    elif kind == "unary":
        op = node.get("operator")
        arg = _eval_expr(node["arguments"][0], time, params, functions, dtype)
        if op == "plus":
            return +arg
        elif op == "negate":
            return -arg
        elif op == "not":
            return jnp.logical_not(arg)
        else:
            raise NotImplementedError(f"JAX ODE does not support unary operator '{op}'")
    elif kind == "binary":
        op = node.get("operator")
        left = _eval_expr(node["arguments"][0], time, params, functions, dtype)
        right = _eval_expr(node["arguments"][1], time, params, functions, dtype)
        if op == "add":
            return left + right
        elif op == "subtract":
            return left - right
        elif op == "multiply":
            return left * right
        elif op == "divide":
            return left / right
        elif op == "power":
            return left**right
        elif op == "less":
            return left < right
        elif op == "less_equal":
            return left <= right
        elif op == "greater":
            return left > right
        elif op == "greater_equal":
            return left >= right
        elif op == "equal":
            return left == right
        elif op == "not_equal":
            return left != right
        elif op == "and":
            return jnp.logical_and(left, right)
        elif op == "or":
            return jnp.logical_or(left, right)
        else:
            raise NotImplementedError(
                f"JAX ODE does not support binary operator '{op}'"
            )
    elif kind == "observable_ref":
        raise NotImplementedError("JAX ODE does not support functional rate laws")
    else:
        raise NotImplementedError(f"JAX ODE does not support expression kind '{kind}'")


def _compile_mass_action_rhs(
    data: Dict[str, Any], custom_rate_constants: Optional[Any] = None
) -> Callable:
    """Build a JIT-compiled RHS from native ODE compiler output."""
    initial_state_native = np.asarray(data["initial_state"], dtype=np.float64)
    initial_state = _as_jax_float(
        initial_state_native, "initial species amounts", jnp.asarray(0.0).dtype
    )
    n_species = initial_state.shape[0]
    rate_constants = np.asarray(data["rate_constants"], dtype=np.float64)
    if not np.all(np.isfinite(rate_constants)):
        raise ValueError("JAX ODE requires finite mass-action rate constants")

    reactant_offsets = np.asarray(data["reactant_offsets"], dtype=np.int64)
    reactant_species = np.asarray(data["reactant_species"], dtype=np.int32)
    product_offsets = np.asarray(data["product_offsets"], dtype=np.int64)
    product_species = np.asarray(data["product_species"], dtype=np.int32)
    absolute_flux = np.asarray(data["absolute_flux"], dtype=bool)
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

    if custom_rate_constants is not None:
        rate_constants_jax = jnp.asarray(custom_rate_constants)
    else:
        rate_constants_jax = _as_jax_float(
            rate_constants, "mass-action rate constants", initial_state.dtype
        )
    reactants_jax = jnp.asarray(padded_reactants)
    reactant_mask_jax = jnp.asarray(reactant_mask)
    absolute_flux_jax = jnp.asarray(absolute_flux)
    clamped_mask = jnp.asarray(data["fixed" + "_species"], dtype=bool)
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
            absolute_flux_jax,
            jnp.ones_like(mass_action_factors),
            mass_action_factors,
        )
        derivative = (
            jnp.zeros((n_species,), dtype=state.dtype)
            .at[change_species_jax]
            .add(change_stoichiometry_jax * fluxes[change_reactions_jax])
        )
        return jnp.where(clamped_mask, 0.0, derivative)

    return rhs


def _compile_dynamic_time_rhs(
    data: Dict[str, Any],
    custom_rate_constants: Optional[Any] = None,
    custom_parameters: Optional[Any] = None,
) -> Callable:
    """Build a JIT-compiled RHS for reaction networks with dynamic time-dependent rates."""
    initial_state_native = np.asarray(data["initial_state"], dtype=np.float64)
    initial_state = _as_jax_float(
        initial_state_native, "initial species amounts", jnp.asarray(0.0).dtype
    )
    n_species = initial_state.shape[0]
    rate_constants = np.asarray(data["rate_constants"], dtype=np.float64)
    reactant_offsets = np.asarray(data["reactant_offsets"], dtype=np.int64)
    reactant_species = np.asarray(data["reactant_species"], dtype=np.int32)
    product_offsets = np.asarray(data["product_offsets"], dtype=np.int64)
    product_species = np.asarray(data["product_species"], dtype=np.int32)
    absolute_flux = np.asarray(data["absolute_flux"], dtype=bool)
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

    if custom_rate_constants is not None:
        rate_constants_jax = jnp.asarray(custom_rate_constants)
    else:
        rate_constants_jax = _as_jax_float(
            rate_constants, "mass-action rate constants", initial_state.dtype
        )

    snapshot = data.get("snapshot", {})
    param_defs = snapshot.get("parameters", [])
    param_name_to_idx = {p["name"]: p.get("id", i) for i, p in enumerate(param_defs)}

    if custom_parameters is not None:
        if isinstance(custom_parameters, dict):
            param_list = [p.get("constant_value", 0.0) for p in param_defs]
            for k, v in custom_parameters.items():
                if isinstance(k, int):
                    param_list[k] = v
                elif k in param_name_to_idx:
                    param_list[param_name_to_idx[k]] = v
            params_jax = jnp.asarray(param_list)
        else:
            params_jax = jnp.asarray(custom_parameters)
    else:
        param_list = [p.get("constant_value", 0.0) for p in param_defs]
        params_jax = _as_jax_float(param_list, "parameters", initial_state.dtype)

    functions_by_id = {f["id"]: f for f in snapshot.get("functions", []) if "id" in f}
    rules_by_name = {r["name"]: r for r in snapshot.get("rules", []) if "name" in r}

    reaction_rules = data.get("reaction_rules", [])
    reaction_factors = data.get("reaction_factors", [1.0] * n_reactions)
    time_dependent = np.asarray(
        data.get("time_dependent_rates", [0] * n_reactions), dtype=bool
    )

    # Validate that none of the time-dependent rates depend on observables
    for rxn_idx in range(n_reactions):
        if time_dependent[rxn_idx]:
            r_name = reaction_rules[rxn_idx] if rxn_idx < len(reaction_rules) else ""
            if r_name.startswith("_reverse__"):
                base_name = r_name[len("_reverse__") :]
                rule = rules_by_name.get(base_name, {})
                expr = rule.get("reverse", {}).get("rate", {}).get("expression")
            else:
                rule = rules_by_name.get(r_name, {})
                expr = rule.get("forward", {}).get("rate", {}).get("expression")
            if expr is not None and _expr_contains_observable(expr, functions_by_id):
                raise NotImplementedError(
                    "JAX ODE does not support functional rate laws"
                )

    reactants_jax = jnp.asarray(padded_reactants)
    reactant_mask_jax = jnp.asarray(reactant_mask)
    absolute_flux_jax = jnp.asarray(absolute_flux)
    clamped_mask = jnp.asarray(data["fixed" + "_species"], dtype=bool)
    change_species_jax = jnp.asarray(change_species, dtype=jnp.int32)
    change_reactions_jax = jnp.asarray(change_reactions, dtype=jnp.int32)
    change_stoichiometry_jax = jnp.asarray(
        change_stoichiometry, dtype=initial_state.dtype
    )

    # Pre-extract expressions and stat factors for each reaction
    rxn_exprs = []
    rxn_stat_factors = []
    for rxn_idx in range(n_reactions):
        r_factor = (
            float(reaction_factors[rxn_idx]) if rxn_idx < len(reaction_factors) else 1.0
        )
        is_abs = bool(absolute_flux[rxn_idx])
        is_tot = bool(total_rate[rxn_idx])
        stat_f = 1.0 if (is_abs or is_tot) else r_factor
        rxn_stat_factors.append(stat_f)

        r_name = reaction_rules[rxn_idx] if rxn_idx < len(reaction_rules) else ""
        if r_name.startswith("_reverse__"):
            base_name = r_name[len("_reverse__") :]
            rule = rules_by_name.get(base_name, {})
            expr = rule.get("reverse", {}).get("rate", {}).get("expression")
        else:
            rule = rules_by_name.get(r_name, {})
            expr = rule.get("forward", {}).get("rate", {}).get("expression")
        rxn_exprs.append(expr)

    stat_factors_jax = jnp.asarray(rxn_stat_factors, dtype=initial_state.dtype)

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

        rate_list = []
        for i in range(n_reactions):
            if (time_dependent[i] or custom_parameters is not None) and rxn_exprs[
                i
            ] is not None:
                rate_val = stat_factors_jax[i] * _eval_expr(
                    rxn_exprs[i], time, params_jax, functions_by_id, state.dtype
                )
            else:
                rate_val = rate_constants_jax[i]
            rate_list.append(rate_val)

        if rate_list:
            rates = jnp.stack(rate_list)
        else:
            rates = jnp.zeros((0,), dtype=state.dtype)

        fluxes = rates * jnp.where(
            absolute_flux_jax,
            jnp.ones_like(mass_action_factors),
            mass_action_factors,
        )
        derivative = (
            jnp.zeros((n_species,), dtype=state.dtype)
            .at[change_species_jax]
            .add(change_stoichiometry_jax * fluxes[change_reactions_jax])
        )
        return jnp.where(clamped_mask, 0.0, derivative)

    return rhs


def _compile_rhs_from_data(
    data: Dict[str, Any],
    custom_rate_constants: Optional[Any] = None,
    custom_parameters: Optional[Any] = None,
) -> Callable:
    functional = np.asarray(data["functional_rates"], dtype=bool)
    time_dependent = np.asarray(data["time_dependent_rates"], dtype=bool)
    if np.any(functional & ~time_dependent):
        raise NotImplementedError("JAX ODE does not support functional rate laws")
    if np.any(time_dependent) or custom_parameters is not None:
        return _compile_dynamic_time_rhs(
            data,
            custom_rate_constants=custom_rate_constants,
            custom_parameters=custom_parameters,
        )
    return _compile_mass_action_rhs(data, custom_rate_constants=custom_rate_constants)


def compile_rhs(
    model: Any,
    rate_constants: Optional[Any] = None,
    parameters: Optional[Any] = None,
) -> Callable:
    """Compile a JAX RHS from BNG3's native ODE representation.

    Supports static mass-action and dynamic time-dependent rate laws.
    Observable-dependent functional rates remain unsupported.
    The configured JAX floating dtype is used (normally float32); coefficients
    and initial amounts outside its normal finite range are rejected.
    """
    _check_jax()
    return _compile_rhs_from_data(
        _extract_ode_data(model),
        custom_rate_constants=rate_constants,
        custom_parameters=parameters,
    )


def simulate_jax_ode(
    model: Any,
    t_end: float,
    n_steps: int = 1000,
    method: str = "rk4",
    initial_state: Optional[Any] = None,
    rate_constants: Optional[Any] = None,
    parameters: Optional[Any] = None,
    return_jax: bool = False,
) -> Dict[str, Any]:
    """Integrate a mass-action or time-dependent model with a fixed-step JAX RK4 solver.

    The returned ``time`` and ``concentrations`` arrays use the same keys and
    axis order as :func:`bionetgen._bionetgen_cpp.simulate_ode`.
    This fixed-step solver has no adaptive error control. It uses the configured
    JAX floating dtype and rejects inputs outside its normal finite range.
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
    rhs = _compile_rhs_from_data(
        data,
        custom_rate_constants=rate_constants,
        custom_parameters=parameters,
    )
    if initial_state is not None:
        init_state = jnp.asarray(initial_state)
    else:
        init_state = jnp.asarray(data["initial_state"])
    time_points = np.linspace(0.0, final_time, n_steps + 1)
    scan_times = _as_jax_float(time_points[:-1], "time points", init_state.dtype)
    step_size = _as_jax_float(final_time / n_steps, "time step", init_state.dtype)
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
    _, later_states = lax.scan(rk4_step, init_state, scan_times)
    trajectory = jnp.concatenate((init_state[None, :], later_states), axis=0)
    concs = trajectory if return_jax else np.asarray(trajectory)
    return {
        "time": time_points,
        "concentrations": concs,
    }


__all__ = ["compile_rhs", "simulate_jax_ode", "_check_jax"]
