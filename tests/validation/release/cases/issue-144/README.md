# Release Acceptance Case: Issue #144

## Title
B07: Resolve and execute the canonical finite-backend migration

## Contract and Architecture (ADR 0003)
- Native BNG3 solvers (CVODE ODE, direct SSA, PLA, PSA) are the default finite backends.
- BNGsim is a supported optional backend behind the common backend interface.
- Backend selection is explicit (`native`, `bngsim`, `auto`), with `auto` conservatively resolving to `native` during migration.
- Lowering to BNGsim checks model compatibility; unsupported constructs (e.g., compartments, energy patterns, user functions) fail closed with explicit diagnostic messages.
- Availability is queryable via `bngsim_capabilities()` without throwing exceptions in non-BNGsim builds.

## Acceptance Criteria
- `release-bngsim`: Availability reporting across build configurations, default solver selection, and environment variable opt-in/reversion.
- `release-bngsim-parity`: Analytic and native agreement on lowerable models, fail-closed diagnostics on unsupported features.
- `release-capability-coverage-144`: Full coverage of inventory row `backend.bngsim`.
