# Issue 473: Supported JAX ODE and SSA backends

**Closure audit (2026-11-14): incomplete acceptance.** Existing JAX CPU mass-action/time-dependent ODE, gradients and first-order SSA-law tests are retained. jax_ode.py explicitly refuses observable-dependent functional rates (including an existing refusal regression). The new wrapper does not complete all protocol/continuation/rate families, and its install check tests unavailable/import behavior rather than an installed-extra campaign. No semantic implementation changed in #663. See docs/CURRENT_PROGRESS.md for the assessed revision and retained evidence.

This directory defines the release acceptance contract and qualification tests for Issue #473.

## Coverage
- `release-jax-ode`: source-derived analytic and native-reference cases cover mass action, TotalRate, constant/time-dependent rates, observable-dependent functional rates (polynomial, MM, Hill, coupled feedback), time grids, and automatic differentiation.
- `release-jax-ssa`: actual batch trajectories pass analytic first-order survival distribution tests, bimolecular conservation laws, batch reproducibility, and max-steps guards.
- `release-jax-install`: optional dependency install and unavailable-dependency diagnostics pass cleanly.
- `release-capability-coverage-473`: full capability matrix and issue obligation crosswalk verification.
