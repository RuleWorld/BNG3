"""JAX-based ODE rate law JIT compilation (opt-in).

This module provides a JAX-compiled version of the ODE right-hand side
for models where the rate laws can be expressed as pure functions of
state and time. The compiled RHS can be used with JAX's ODE solvers
or as a drop-in replacement for the C++ RHS in simple cases.

Usage:
    import bionetgen
    import bionetgen.jax_ode as jax_ode

    model = bionetgen.load("models/isomerization.bngl")
    jax_rhs = jax_ode.compile_rhs(model)
    # Use with jax.experimental.ode.odeint or similar
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

try:
    import jax
    import jax.numpy as jnp
    from jax import jit, vmap

    _JAX_AVAILABLE = True
except ImportError:
    _JAX_AVAILABLE = False
    jax = None
    jnp = None
    jit = None
    vmap = None

from bionetgen import _bionetgen_cpp as cpp


def _check_jax() -> None:
    if not _JAX_AVAILABLE:
        raise ImportError(
            "JAX ODE backend requires 'jax' and 'jaxlib' packages. "
            "Install with: pip install 'bionetgen[jax]'"
        )


def _extract_rate_laws(model) -> List[Dict[str, Any]]:
    """Extract rate law expressions from a loaded model."""
    # Use the C++ binding to get compiled reaction data
    _ = cpp.generate_network(model)
    integrator = cpp.OdeIntegrator(model, network)
    compiled_rxns = integrator.getCompiledReactions()

    rate_laws = []
    for rxn in compiled_rxns:
        if rxn.isFunctional:
            # Functional rate laws need special handling
            rate_laws.append(
                {
                    "type": "functional",
                    "expression": (
                        rxn.functionalRateExpr.toString()
                        if rxn.functionalRateExpr
                        else ""
                    ),
                    "reactants": list(rxn.reactantIndices),
                    "products": list(rxn.productIndices),
                }
            )
        else:
            rate_laws.append(
                {
                    "type": "mass_action",
                    "rate_constant": rxn.rateConstant,
                    "stat_factor": rxn.statFactor,
                    "reactants": list(rxn.reactantIndices),
                    "products": list(rxn.productIndices),
                    "is_total_rate": rxn.isTotalRate,
                }
            )
    return rate_laws


def _compile_mass_action_rhs(rate_laws: List[Dict], n_species: int) -> Callable:
    """Compile mass-action RHS using JAX."""
    # Build stoichiometry matrix
    import numpy as np

    stoich = np.zeros((n_species, len(rate_laws)), dtype=np.float32)
    rate_constants = np.zeros(len(rate_laws), dtype=np.float32)

    for i, rl in enumerate(rate_laws):
        if rl["type"] != "mass_action":
            raise ValueError("Only mass-action reactions supported in this stub")
        rate_constants[i] = rl["rate_constant"]
        for react_idx in rl["reactants"]:
            stoich[react_idx, i] -= 1
        for prod_idx in rl["products"]:
            stoich[prod_idx, i] += 1

    stoich_jax = jnp.array(stoich)
    rate_constants_jax = jnp.array(rate_constants)

    @jit
    def rhs(t: float, y: jnp.ndarray) -> jnp.ndarray:
        # Compute propensities
        props = rate_constants_jax
        for r_idx, rl in enumerate(rate_laws):
            for react_idx in rl["reactants"]:
                pop = y[react_idx]
                props = props.at[r_idx].multiply(jnp.maximum(pop, 0.0))
        # dy/dt = S @ props
        return stoich_jax @ props

    return rhs


def compile_rhs(model) -> Callable:
    """Compile the ODE RHS for a model using JAX.

    Returns a function rhs(t, y) -> dydt that can be used with JAX ODE solvers.

    Currently supports only mass-action kinetics. Functional rate laws
    and time-dependent rates are not yet supported.
    """
    _check_jax()

    rate_laws = _extract_rate_laws(model)

    # Check if all reactions are mass-action
    if all(rl["type"] == "mass_action" for rl in rate_laws):
        return _compile_mass_action_rhs(rate_laws, n_species=len(model.getSpecies()))
    else:
        raise NotImplementedError(
            "JAX ODE RHS compilation currently only supports mass-action kinetics. "
            f"Found {sum(1 for rl in rate_laws if rl['type'] != 'mass_action')} "
            "functional/time-dependent reactions."
        )


def simulate_jax_ode(
    model, t_end: float, n_steps: int = 1000, method: str = "rk4", **kwargs
) -> Dict[str, Any]:
    """Simulate ODE using JAX-compiled RHS.

    Returns dict with 'time', 'concentrations' matching C++ simulate_ode output format.
    """
    _check_jax()
    from jax.experimental.ode import odeint

    # Get initial state
    from bionetgen import _bionetgen_cpp as cpp

    _ = cpp.generate_network(model)
    _ = len(model.getSpecies())
    initial_state = jnp.array(
        [float(s.getAmount()) for s in model.getSpecies()], dtype=jnp.float32
    )

    rhs = compile_rhs(model)
    t_span = jnp.linspace(0.0, t_end, n_steps + 1)

    # Use JAX's odeint (RK4/5 adaptive)
    trajectory = odeint(rhs, initial_state, t_span)

    return {
        "time": np.array(t_span),
        "concentrations": np.array(trajectory),
    }


__all__ = ["compile_rhs", "simulate_jax_ode", "_check_jax"]
