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

    algebraic_rules = list(getattr(model, "_algebraic_rules", None) or [])
    if algebraic_rules:
        raise NotImplementedError("JAX ODE does not support SBML algebraic rules")
    for rule in getattr(native_model, "reaction_rules", []):
        if getattr(rule, "has_delay", False):
            raise NotImplementedError("JAX ODE does not support delayed reactions")

    network = cpp.generate_network(native_model)
    try:
        data = cpp.jax_ode_flatten(native_model, network, algebraic_rules)
    except TypeError:
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


def _expr_param_deps(node: Any, functions: Dict[int, Any]) -> set[int]:
    """Return parameter IDs referenced directly or via model functions."""
    deps: set[int] = set()
    if not isinstance(node, dict):
        return deps
    kind = node.get("kind")
    if kind == "parameter_ref":
        sym = node.get("symbol", {})
        if isinstance(sym, dict) and "index" in sym:
            deps.add(int(sym["index"]))
    elif kind == "function_ref":
        sym = node.get("symbol", {})
        if isinstance(sym, dict) and "index" in sym:
            fn_idx = sym["index"]
            if fn_idx in functions:
                deps |= _expr_param_deps(functions[fn_idx].get("expression", {}), functions)
    for arg in node.get("arguments", []):
        deps |= _expr_param_deps(arg, functions)
    return deps


def _is_special_rate_law_expr(node: Any) -> bool:
    if not isinstance(node, dict) or node.get("kind") != "builtin_call":
        return False
    return node.get("builtin") in (
        "michaelis_menten",
        "mm",
        "hill",
        "Hill",
        "sat",
        "saturation",
    )


def _eval_expr(
    node: Dict[str, Any],
    time: Any,
    params: Any,
    observables: Any,
    functions: Dict[int, Any],
    obs_id_to_idx: Dict[int, int],
    obs_name_to_idx: Dict[str, int],
    dtype: Any,
    locals_dict: Optional[Dict[str, Any]] = None,
    rxn_reactant_vals: Optional[list[Any]] = None,
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
            _eval_expr(
                arg,
                time,
                params,
                observables,
                functions,
                obs_id_to_idx,
                obs_name_to_idx,
                dtype,
                locals_dict,
            )
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
        elif builtin in ("michaelis_menten", "mm"):
            if len(args) == 4:
                kcat, Km, St, Et = args[0], args[1], args[2], args[3]
                b = St - Km - Et
                q = jnp.sqrt(b * b + 4.0 * St * Km)
                S = jnp.where(b >= 0.0, 0.5 * (b + q), 2.0 * St * Km / (q - b))
                return jnp.where(Km + S != 0.0, (kcat * Et * S) / (Km + S), 0.0)
            elif len(args) == 3:
                Vmax, Km, S = args[0], args[1], args[2]
                val = jnp.where(Km + S != 0.0, (Vmax * S) / (Km + S), 0.0)
                if rxn_reactant_vals is not None and len(rxn_reactant_vals) > 1:
                    for extra_r in rxn_reactant_vals[1:]:
                        val = val * extra_r
                return val
            elif len(args) == 2 and rxn_reactant_vals:
                kcat, Km = args[0], args[1]
                if len(rxn_reactant_vals) >= 2:
                    St, Et = rxn_reactant_vals[0], rxn_reactant_vals[1]
                    b = St - Km - Et
                    q = jnp.sqrt(b * b + 4.0 * St * Km)
                    S = jnp.where(b >= 0.0, 0.5 * (b + q), 2.0 * St * Km / (q - b))
                    return jnp.where(Km + S != 0.0, (kcat * Et * S) / (Km + S), 0.0)
                S = rxn_reactant_vals[0]
                return jnp.where(Km + S != 0.0, (kcat * S) / (Km + S), 0.0)
            else:
                raise ValueError("michaelis_menten requires at least 2 arguments with substrate")
        elif builtin in ("hill", "Hill"):
            if len(args) >= 4:
                Vmax, Kh, n, S = args[0], args[1], args[2], args[3]
                safe_S = jnp.where(S > 0.0, S, jnp.ones_like(S))
                Sn = safe_S**n
                Khn = Kh**n
                raw = jnp.where(Khn + Sn != 0.0, (Vmax * Sn) / (Khn + Sn), 0.0)
                return jnp.where(S > 0.0, raw, 0.0)
            elif len(args) in (2, 3) and rxn_reactant_vals:
                Vmax = args[0]
                Kh = args[1]
                n = args[2] if len(args) >= 3 else jnp.asarray(1.0, dtype=dtype)
                S = rxn_reactant_vals[0]
                safe_S = jnp.where(S > 0.0, S, jnp.ones_like(S))
                Sn = safe_S**n
                Khn = Kh**n
                raw = jnp.where(Khn + Sn != 0.0, (Vmax * Sn) / (Khn + Sn), 0.0)
                smooth = jnp.where(n <= 0.0, S / (S + 1e-9), 1.0)
                val = jnp.where(S > 0.0, smooth * raw, 0.0)
                for extra_r in rxn_reactant_vals[1:]:
                    val = val * extra_r
                return val
            else:
                raise ValueError("Hill function requires 3 arguments (with reactant) or 4 arguments")
        elif builtin in ("sat", "saturation"):
            if len(args) == 1:
                return args[0]
            elif len(args) == 2 and rxn_reactant_vals:
                k_val, Km = args[0], args[1]
                S = rxn_reactant_vals[0]
                val = jnp.where(Km + S != 0.0, (k_val * S) / (Km + S), 0.0)
                for extra_r in rxn_reactant_vals[1:]:
                    val = val * extra_r
                return val
            elif len(args) >= 3:
                if (
                    rxn_reactant_vals is not None
                    and len(rxn_reactant_vals) >= 2
                    and (len(args) - 1) <= len(rxn_reactant_vals)
                ):
                    n_denom = min(len(args) - 1, len(rxn_reactant_vals))
                    S0 = rxn_reactant_vals[0]
                    val = jnp.where(
                        args[1] + S0 != 0.0, (args[0] * S0) / (args[1] + S0), 0.0
                    )
                    for ri in range(1, n_denom):
                        Si = rxn_reactant_vals[ri]
                        denom = args[ri + 1] + Si
                        val = val * jnp.where(denom != 0.0, Si / denom, 0.0)
                    for ri in range(n_denom, len(rxn_reactant_vals)):
                        val = val * rxn_reactant_vals[ri]
                    return val
                Vmax, Km, S = args[0], args[1], args[2]
                return jnp.where(Km + S != 0.0, (Vmax * S) / (Km + S), 0.0)
            else:
                raise ValueError("saturation requires at least 2 arguments (with reactant) or 3 arguments")
        else:
            raise NotImplementedError(
                f"JAX ODE does not support builtin function '{builtin}'"
            )
    elif kind == "parameter_ref":
        idx = node["symbol"]["index"]
        return params[idx]
    elif kind == "observable_ref":
        g_idx = None
        if "symbol" in node and isinstance(node["symbol"], dict):
            sym_idx = node["symbol"].get("index")
            if sym_idx in obs_id_to_idx:
                g_idx = obs_id_to_idx[sym_idx]
        if g_idx is None and "name" in node:
            g_idx = obs_name_to_idx.get(node["name"])
        if g_idx is None:
            raise NotImplementedError(
                f"Observable '{node.get('name', node)}' not found in compiled groups"
            )
        return observables[g_idx]
    elif kind == "local_ref":
        name = node.get("name")
        if locals_dict is not None and name in locals_dict:
            return locals_dict[name]
        raise NotImplementedError(f"Local reference '{name}' not found in local scope")
    elif kind == "function_ref":
        idx = node["symbol"]["index"]
        if idx in functions:
            fn = functions[idx]
            call_args = [
                _eval_expr(
                    arg,
                    time,
                    params,
                    observables,
                    functions,
                    obs_id_to_idx,
                    obs_name_to_idx,
                    dtype,
                    locals_dict,
                )
                for arg in node.get("arguments", [])
            ]
            fn_param_names = fn.get("arguments", [])
            if call_args and fn_param_names:
                new_locals = dict(locals_dict) if locals_dict else {}
                for p_name, p_val in zip(fn_param_names, call_args):
                    new_locals[p_name] = p_val
            else:
                new_locals = locals_dict
            return _eval_expr(
                fn["expression"],
                time,
                params,
                observables,
                functions,
                obs_id_to_idx,
                obs_name_to_idx,
                dtype,
                new_locals,
            )
        raise NotImplementedError(f"Function index {idx} not found in model functions")
    elif kind == "unary":
        op = node.get("operator")
        arg = _eval_expr(
            node["arguments"][0],
            time,
            params,
            observables,
            functions,
            obs_id_to_idx,
            obs_name_to_idx,
            dtype,
            locals_dict,
        )
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
        left = _eval_expr(
            node["arguments"][0],
            time,
            params,
            observables,
            functions,
            obs_id_to_idx,
            obs_name_to_idx,
            dtype,
            locals_dict,
        )
        right = _eval_expr(
            node["arguments"][1],
            time,
            params,
            observables,
            functions,
            obs_id_to_idx,
            obs_name_to_idx,
            dtype,
            locals_dict,
        )
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


def _compile_dynamic_rhs(
    data: Dict[str, Any],
    custom_rate_constants: Optional[Any] = None,
    custom_parameters: Optional[Any] = None,
) -> Callable:
    """Build a JIT-compiled RHS for reaction networks with dynamic time- or observable-dependent rates."""
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
    functions_by_id = {f["id"]: f for f in snapshot.get("functions", []) if "id" in f}

    group_names = list(data.get("group_names", []))
    group_offsets = np.asarray(data.get("group_offsets", [0]), dtype=np.int64)
    group_species = np.asarray(data.get("group_species", []), dtype=np.int32)
    group_weights = np.asarray(data.get("group_weights", []), dtype=np.float64)
    n_groups = len(group_names)

    obs_matrix = np.zeros((n_groups, n_species), dtype=np.float64)
    for g in range(n_groups):
        start = int(group_offsets[g])
        end = int(group_offsets[g + 1])
        if end > start:
            specs = group_species[start:end]
            wts = group_weights[start:end]
            np.add.at(obs_matrix[g], specs, wts)
    obs_matrix_jax = _as_jax_float(
        obs_matrix, "observable weights", initial_state.dtype
    )

    obs_name_to_idx = {name: i for i, name in enumerate(group_names)}
    obs_id_to_idx = {}
    for obs in snapshot.get("observables", []):
        if "id" in obs and "name" in obs and obs["name"] in obs_name_to_idx:
            obs_id_to_idx[obs["id"]] = obs_name_to_idx[obs["name"]]

    if custom_parameters is not None:
        if isinstance(custom_parameters, dict):
            overridden_ids: Dict[int, Any] = {}
            for k, v in custom_parameters.items():
                if isinstance(k, int):
                    overridden_ids[k] = v
                elif k in param_name_to_idx:
                    overridden_ids[param_name_to_idx[k]] = v
            n_params = (
                max((int(p.get("id", i)) for i, p in enumerate(param_defs)), default=-1)
                + 1
            )
            param_by_id = {int(p.get("id", i)): p for i, p in enumerate(param_defs)}
            direct_deps: Dict[int, set[int]] = {}
            for pid, pdef in param_by_id.items():
                if pid in overridden_ids:
                    direct_deps[pid] = set()
                else:
                    direct_deps[pid] = _expr_param_deps(
                        pdef.get("expression"), functions_by_id
                    )

            # Determine which non-overridden parameters transitively depend on
            # an overridden parameter, and evaluate them in topological order so
            # jax.grad propagates through dependent parameter expressions (k2 = 2*k1).
            topo_order: list[int] = []
            visit_state: Dict[int, int] = {}

            def _dfs_param(pid: int) -> None:
                st = visit_state.get(pid, 0)
                if st != 0:
                    return
                visit_state[pid] = 1
                for dep in direct_deps.get(pid, ()):
                    if dep in param_by_id:
                        _dfs_param(dep)
                visit_state[pid] = 2
                topo_order.append(pid)

            for pid in sorted(param_by_id):
                _dfs_param(pid)

            depends_on_override: set[int] = set(overridden_ids)
            for pid in topo_order:
                if pid in overridden_ids:
                    continue
                if any(dep in depends_on_override for dep in direct_deps.get(pid, ())):
                    depends_on_override.add(pid)

            evaluated_params: list[Any] = [
                jnp.asarray(0.0, dtype=initial_state.dtype) for _ in range(n_params)
            ]
            zero_time = jnp.asarray(0.0, dtype=initial_state.dtype)
            empty_obs = jnp.zeros((n_groups,), dtype=initial_state.dtype)
            for pid in topo_order:
                if pid in overridden_ids:
                    evaluated_params[pid] = jnp.asarray(
                        overridden_ids[pid], dtype=initial_state.dtype
                    )
                elif pid in depends_on_override and param_by_id[pid].get("expression"):
                    evaluated_params[pid] = jnp.asarray(
                        _eval_expr(
                            param_by_id[pid]["expression"],
                            zero_time,
                            evaluated_params,
                            empty_obs,
                            functions_by_id,
                            obs_id_to_idx,
                            obs_name_to_idx,
                            initial_state.dtype,
                        ),
                        dtype=initial_state.dtype,
                    )
                else:
                    evaluated_params[pid] = jnp.asarray(
                        param_by_id[pid].get("constant_value", 0.0),
                        dtype=initial_state.dtype,
                    )
            params_jax = (
                jnp.stack(evaluated_params)
                if evaluated_params
                else jnp.zeros((0,), dtype=initial_state.dtype)
            )
        else:
            params_jax = jnp.asarray(custom_parameters)
    else:
        param_list = [p.get("constant_value", 0.0) for p in param_defs]
        params_jax = _as_jax_float(param_list, "parameters", initial_state.dtype)

    rules_by_name = {r["name"]: r for r in snapshot.get("rules", []) if "name" in r}
    for r in snapshot.get("rules", []):
        lbl = r.get("label", "")
        if lbl:
            rules_by_name[lbl.rstrip(":")] = r

    reaction_rules = data.get("reaction_rules", [])
    reaction_factors = data.get("reaction_factors", [1.0] * n_reactions)
    effective_stat_factors = data.get("effective_stat_factors")
    volume_scales = data.get("volume_scales")
    functional = np.asarray(data.get("functional_rates", [0] * n_reactions), dtype=bool)
    time_dependent = np.asarray(
        data.get("time_dependent_rates", [0] * n_reactions), dtype=bool
    )
    is_dynamic = functional | time_dependent

    reactants_jax = jnp.asarray(padded_reactants)
    reactant_mask_jax = jnp.asarray(reactant_mask)
    absolute_flux_jax = jnp.asarray(absolute_flux)
    clamped_mask = jnp.asarray(data["fixed" + "_species"], dtype=bool)
    change_species_jax = jnp.asarray(change_species, dtype=jnp.int32)
    change_reactions_jax = jnp.asarray(change_reactions, dtype=jnp.int32)
    change_stoichiometry_jax = jnp.asarray(
        change_stoichiometry, dtype=initial_state.dtype
    )

    # Pre-extract expressions, reactant index lists, and effective stat*volume factors
    rxn_exprs = []
    rxn_stat_factors = []
    rxn_reactant_indices: list[list[int]] = []
    for rxn_idx in range(n_reactions):
        start = int(reactant_offsets[rxn_idx])
        end = int(reactant_offsets[rxn_idx + 1])
        rxn_reactant_indices.append([int(x) for x in reactant_species[start:end]])

        r_name = reaction_rules[rxn_idx] if rxn_idx < len(reaction_rules) else ""
        if r_name.startswith("_reverse__"):
            base_name = r_name[len("_reverse__") :]
            rule = rules_by_name.get(base_name, {})
            expr = rule.get("reverse", {}).get("rate", {}).get("expression")
        else:
            rule = rules_by_name.get(r_name, {})
            expr = rule.get("forward", {}).get("rate", {}).get("expression")
        rxn_exprs.append(expr)

        r_factor = (
            float(reaction_factors[rxn_idx]) if rxn_idx < len(reaction_factors) else 1.0
        )
        authored_total_rate = any(
            isinstance(m, dict) and m.get("kind") == "total_rate"
            for m in rule.get("modifiers", [])
        )
        if _is_special_rate_law_expr(expr):
            v_scale = (
                float(volume_scales[rxn_idx])
                if volume_scales is not None and rxn_idx < len(volume_scales)
                else 1.0
            )
            stat_f = 1.0 if authored_total_rate else (r_factor * v_scale)
        elif effective_stat_factors is not None and rxn_idx < len(
            effective_stat_factors
        ):
            stat_f = float(effective_stat_factors[rxn_idx])
        else:
            is_abs = bool(absolute_flux[rxn_idx])
            is_tot = bool(total_rate[rxn_idx])
            v_scale = (
                float(volume_scales[rxn_idx])
                if volume_scales is not None and rxn_idx < len(volume_scales)
                else 1.0
            )
            stat_f = 1.0 if (is_abs or is_tot) else (r_factor * v_scale)
        rxn_stat_factors.append(stat_f)

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

        if n_groups > 0:
            obs_values = jnp.dot(obs_matrix_jax, state)
        else:
            obs_values = jnp.zeros((0,), dtype=state.dtype)

        rate_list = []
        for i in range(n_reactions):
            if (is_dynamic[i] or custom_parameters is not None) and rxn_exprs[
                i
            ] is not None:
                r_vals = (
                    [state[sp_i] for sp_i in rxn_reactant_indices[i]]
                    if _is_special_rate_law_expr(rxn_exprs[i])
                    else None
                )
                rate_val = stat_factors_jax[i] * _eval_expr(
                    rxn_exprs[i],
                    time,
                    params_jax,
                    obs_values,
                    functions_by_id,
                    obs_id_to_idx,
                    obs_name_to_idx,
                    state.dtype,
                    rxn_reactant_vals=r_vals,
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
    functional = np.asarray(data.get("functional_rates", []), dtype=bool)
    time_dependent = np.asarray(data.get("time_dependent_rates", []), dtype=bool)
    if np.any(functional) or np.any(time_dependent) or custom_parameters is not None:
        return _compile_dynamic_rhs(
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

    Supports static mass-action, dynamic time-dependent, and observable-dependent functional rate laws.
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
    t_start: float = 0.0,
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
        start_time = float(t_start)
    except (TypeError, ValueError) as exc:
        raise ValueError("t_start must be finite and non-negative") from exc
    if not math.isfinite(start_time) or start_time < 0.0:
        raise ValueError("t_start must be finite and non-negative")
    try:
        final_time = float(t_end)
    except (TypeError, ValueError) as exc:
        raise ValueError("t_end must be finite and positive") from exc
    if not math.isfinite(final_time) or final_time <= 0.0:
        raise ValueError("t_end must be finite and positive")
    if final_time <= start_time:
        raise ValueError("t_end must be strictly greater than t_start")
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
    time_points = np.linspace(start_time, final_time, n_steps + 1)
    scan_times = _as_jax_float(time_points[:-1], "time points", init_state.dtype)
    step_size = _as_jax_float(
        (final_time - start_time) / n_steps, "time step", init_state.dtype
    )
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
