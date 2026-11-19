# Issue 473: Supported JAX ODE and SSA backends

This directory defines the release acceptance contract and qualification tests for Issue #473.

The accepting checks execute the real installed CPU JAX extra (hosted
`python-jax` job): mass-action, TotalRate, time-dependent and
observable-dependent functional rates, protocol/continuation with parameter
interventions, declared physical-unit lowering, supported float32/float64
dtypes, the common compiled-model/rate/result/backend interfaces and the
advertised autodiff gradients for ODE; independent analytic and
native-reference distributions with fixed run counts and error control for
SSA; and separate installed-extra and unavailable-dependency diagnostics.
Bounded per-case support statements and predeclared plans live under
`analysis/c-jax-cpu`, `analysis/c-jax-protocol` and `analysis/c-jax-extended`.

## Coverage
- `release-jax-ode`: source-derived analytic and native-reference cases cover mass action, TotalRate, constant/time-dependent rates, observable-dependent functional rates (polynomial, MM, Hill, coupled feedback), declared physical-unit lowering, time grids, protocols (`t_start`, multi-phase continuation with/without intervention), supported float dtypes, the common compiled-model/rate/result/backend interfaces, and automatic differentiation.
- `release-jax-ssa`: actual batch trajectories pass analytic first-order survival, stationary equilibrium (Binomial(20, 1/6)), immigration–death Poisson and competing-decay multinomial distribution tests (fixed seeds/budgets, DKW and standard-error control, wrong-law power controls), native-reference distribution parity, trajectory mean convergence, bimolecular conservation, reproducibility, and max-steps guards.
- `release-jax-install`: the installed optional extra is verified separately from unavailable-dependency diagnostics; end-to-end simulation executes when installed, while isolated interpreters confirm clean package import and actionable ODE/SSA diagnostics when absent.
- `release-capability-coverage-473`: full capability matrix and issue obligation crosswalk verification.
