# Issue 473: Supported JAX ODE and SSA backends

This directory defines the release acceptance contract and qualification tests for Issue #473.

## Coverage
- `release-jax-ode`: source-derived analytic and native-reference cases cover mass action, TotalRate, constant/time-dependent rates, time grids, and automatic differentiation.
- `release-jax-ssa`: actual batch trajectories pass analytic first-order survival distribution tests, bimolecular conservation laws, batch reproducibility, and max-steps guards.
- `release-jax-install`: optional dependency install and unavailable-dependency diagnostics pass cleanly.
- `release-capability-coverage-473`: full capability matrix and issue obligation crosswalk verification.
