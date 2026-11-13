# Issue #141: Qualify Compile-Once Execution and Isolated Trajectories

This directory contains the independent release acceptance suite for **Issue #141** (B04: Qualify compile-once model reuse and independent trajectory state).

## Acceptance Checks

- `release-instance-isolation`: Concurrent and serial runs match independent expectations with independent RNG streams and separate solver states.
- `release-lifecycle`: ASan/TSan lifecycle and mutation/invalidation cases pass without races, leaks, or stale results.
- `release-obligation-141`: Complete independent evaluation of all assigned obligations and contracts for compile-once reuse.

## Scope and Semantics

1. **Instance Isolation**:
   - An immutable compiled model structure is reused across serial and concurrent execution paths.
   - Separate simulation runs own independent RNG seeds and solver states.
   - Concurrent ODE and SSA executions do not race or corrupt shared state.
   - Deterministic simulations across threads yield identical trajectories matching independent analytic laws.
   - Stochastic simulations with identical seeds reproduce identical trajectories; distinct seeds produce distinct, mass-conserving trajectories.

2. **Lifecycle and Invalidation**:
   - Parameter mutations (`model.set_parameter(...)`) invalidate dependent cached network data (`_network is None`), and subsequent simulation regenerates the network matching a fresh compilation.
   - Transitive rate reclassification: changing a parameter from dynamic `time()` to a constant scalar reclassifies rates from time-dependent to static.
   - Exception recovery: simulating with an invalid condition (e.g., malformed `stop_if`) raises `RuntimeError` cleanly, leaves model state intact, and allows subsequent simulations to run without memory corruption or stale state.
