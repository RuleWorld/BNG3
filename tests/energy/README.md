# BNG3 energy/compiler validation suite

See [`../../docs/CURRENT_PROGRESS.md`](../../docs/CURRENT_PROGRESS.md) for the
current branch and verification state. This suite is now partly integrated;
its remaining future contracts are still intentionally opt-in and fail closed.

This bundle is a tests-first expansion for the proposed BNG3 compiler + generalized energy runtime work.
It is intentionally test-heavy: completed contracts may be promoted into the
default CTest set only after their implementation and exact-tree evidence are
verified, while unresolved `future_*.cpp` files remain RED specifications.

Target source checkpoint: RuleWorld/BNG3 PR #2 head `3bc7b4ff131f8927421bc8eae170e3b248b75318`.

## Test tiers

- **T0: pure math / data-structure contracts** — no NFsim simulation required.
- **T1: compiler semantic contracts** — AST -> compiled rule/factor/dependency plan.
- **T2: lowering contracts** — compiled energy plan -> selected backend, including fail-closed fallback.
- **T3: NFsim construction contracts** — transactionality, initial propensity, reaction-class counts.
- **T4: stochastic equivalence** — generalized backend OFF vs ON across a fixed seed manifest.
- **T5: independent oracle** — BNG3 direct NF vs pinned standalone NFsim/BNG2 where semantics overlap.
- **T6: performance** — construction time, reaction-class explosion, event throughput, memory.
- **T7: robustness** — sanitizers, randomized/property tests, invalid inputs, concurrency/cache races.

## Promotion rule

Do not make the generalized energy backend default-on until all non-future T0–T7 gates are green.
Byte-identical trajectories are required only when the lowering preserves RNG call structure. When a factorized
backend aggregates legacy reaction classes and therefore changes RNG consumption, use exact propensity/event-weight
parity plus the prespecified multi-seed distributional gate.

## Suggested install location

Copy:

- `tests/cpp/*` -> `tests/cpp/`
- `tests/python/*` -> `tests/python/`
- `fixtures/energy/*` -> `tests/fixtures/energy/`
- `scripts/*` -> `scripts/`
- `cmake/energy_tests.cmake` -> include from `tests/cpp/CMakeLists.txt`

Keep `future_*.cpp` behind `BNG_ENABLE_FUTURE_ENERGY_CONTRACTS` until the matching API exists.
