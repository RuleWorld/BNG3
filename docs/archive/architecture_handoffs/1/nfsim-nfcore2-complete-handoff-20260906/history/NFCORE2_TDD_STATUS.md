# NFcore2 test-first continuation status

> Historical TDD checkpoint. Current contract promotion is governed by the
> live convergence checklist and [`docs/CURRENT_PROGRESS.md`](../../../../../CURRENT_PROGRESS.md).

Base target: `akutuva21/nfsim`, branch `perf/rasi-translation-optimization`, previously evaluated at `d13086bd3cf2fd268be5efea4d83089301479de3`.

This continuation changed the development rule for NFcore2 to test-first. New behavior was first expressed as failing conformance tests, then the implementation was changed until the tests passed. The production NFsim execution path remains untouched; these tests validate the adjacent NFcore2 backend and its semantic lowering/runtime contracts.

## Test density

- NFcore2 implementation: **1,136 lines** across `.hh`/`.cpp`.
- NFcore2 test code: **2,439 lines** across the test harness and `test_*.cpp` sources.
- Test/implementation ratio: **2.15x**.
- Registered conformance tests: **263**.
- Required target was 1.5x; current suite exceeds it substantially.

## Validation matrix

All 263 tests pass in each completed configuration:

- GCC Debug, C++11
- GCC Release, C++11
- Clang Debug, C++11
- GCC Debug with AddressSanitizer + UndefinedBehaviorSanitizer

Randomized/stress tests additionally execute 10,000–100,000-step invariant loops for graph mutation, population conservation, sparse scaffold behavior, scheduler sampling, state-slot reuse, and copied-trajectory isolation.

## Test-first defects found and fixed

The first expanded red suite produced 16 genuine implementation failures. Fixes include:

1. Population arithmetic now rejects negative initialization, underflow including `INT64_MIN`, and positive `int64_t` overflow.
2. Simulation time now rejects negative, NaN, and infinite values.
3. `MATCH_BOND_FREE` rejects missing secondary reactants instead of treating them as implicitly free.
4. Scaffold matcher offsets reject 32-bit coordinate overflow.
5. Scaffold occupant moves reject empty sources and occupied destinations without destructive overwrite.
6. Bind transforms reject occupied endpoints before mutation.
7. Molecule deletion now clears reciprocal bonds from surviving partners before generation invalidation.
8. Fenwick/scheduler activity and multiplicity reject NaN/infinite values.
9. Rule-family and rule-instance rates must be finite and nonnegative.
10. Malformed matcher/transform opcodes now fail explicitly.
11. Rule-family descriptors reject invalid program IDs and invalid member rates at construction.
12. Feature dependency construction is now based on matcher reads, not on which matcher happened to write a feature.
13. Duplicate structurally equivalent rules no longer duplicate matcher dependency edges.
14. State-word, bond-slot, and population dependencies are kept distinct, reducing false invalidation.
15. Executable-model validation now rejects rule-family and dependency references outside matcher/transform registries before an engine starts.
16. Model-image loading performs executable validation before returning a runnable model.

The sanitizer pass then found an additional representation-level issue: constructing an out-of-range C++ enum for corrupted bytecode can itself trigger undefined behavior before validation. Matcher and transform opcodes therefore now use raw validated integer storage; valid enums remain the symbolic constants used by normal code, while malformed serialized values can be rejected safely.

## Test coverage added

The suite covers:

- typed IDs, invalid sentinels, generational molecule handles, ABA/stale-handle safety;
- type-local molecule stores, state-word bounds, slot reuse and clearing;
- typed cross-molecule bond references and reciprocal bond invariants;
- population arithmetic boundaries and conservation;
- simulation-time invariants;
- sparse and dense scaffolds, huge sparse lengths, state exception removal, occupancy counts and bounds;
- all matcher opcodes, multi-reactant targets, compound predicates and malformed opcodes;
- all transform opcodes, cross-type bind/unbind, create/delete, scaffold motion and feature deltas;
- engine counters, rejected fires, affected matcher/family deduplication, trajectory copies;
- dependency CSR construction and exact reader-based invalidation;
- Fenwick updates/prefixes/sampling vs naive implementations;
- hierarchical family/member scheduling and zero-weight behavior;
- structural rule-family canonicalization, rate variation, member ordering and 100k repeated logical rules;
- legacy lowering, explicit fallback reasons, matcher/transform program deduplication and executable behavior;
- compiled model-image round trips, truncation/magic/version/file errors, byte stability and dependency preservation;
- semantic hashing and shadow state/event mismatch reporting;
- executable-model structural validation before runtime;
- randomized graph, population, scaffold, scheduler, slot-reuse and trajectory-isolation invariants.

## Files

- `nfcore2-tdd-full.patch`: complete additive NFcore2 + test suite patch intended for the original Rasi branch before NFcore2 files exist.
- `nfcore2-tdd-continuation.patch`: delta from the previously delivered `nfcore2-continuation` milestone to this test-first state.
- `src/NFcore2/`: complete current implementation overlay.
- `tests/NFcore2/`: source-only conformance suite and CMake harness. Build directories/binaries are excluded from the delivery archive.

## Remaining critical work

This does **not** yet prove parity with real Rasi/uORF models. The next critical implementation gate is still the real NFsim adapter: emit `LegacyModelIR` from the existing `ReactionClass` / `TransformationSet` construction path, then compare initialization, match counts, propensities, selected logical events, post-event semantic state, observables and hashes against the validated legacy backend on Rasi-500 and uORF.

The new testing rule should remain in force for that work: add adapter/parity fixtures first, observe them fail, then add the lowering/integration code. No NFcore2 family should become a production execution path until its legacy-vs-NFcore2 differential suite is green.
