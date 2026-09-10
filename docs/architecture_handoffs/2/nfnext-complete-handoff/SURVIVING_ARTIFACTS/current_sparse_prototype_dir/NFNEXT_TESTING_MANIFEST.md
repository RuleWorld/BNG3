# NFnext testing expansion manifest

> Historical manifest from the reconstructed prototype. Current test targets
> and verification state are maintained in the live repository docs, starting
> with [`docs/CURRENT_PROGRESS.md`](../../../../../CURRENT_PROGRESS.md).

## Purpose

This package turns the proposed NFnext/NFsim rewrite architecture into a TDD
contract suite. Implemented behavior stays behind the normal green regression
gates. Proposed behavior lives in `nextgen/tests/future_contract/` and is
opt-in/RED until its subsystem exists.

## Current size

- Future-contract architecture files: **19**
- Future-contract C++ cases: **424**
- Meta-tests: **3**
- Physical C/C++ test LOC in the working tree at packaging: **3,790**
- Reconstructed baseline implementation C/C++ LOC: **1,386**
- Logical/non-comment test-to-production LOC ratio from meta-test: **2.924x**
- Required minimum ratio: **1.5x**

The ratio is automatically enforced by `tests/meta/test_test_budget.py`.

## Architecture coverage

1. Canonical NFIR and deterministic semantic fingerprints.
2. Semantic rule-family detection and exact collapse/expand equivalence.
3. Mutation-to-dependency DAG and hierarchical/adaptive scheduler.
4. Arbitrary graph pattern matching, topology, symmetry and molecularity.
5. Atomic transformations and exact product mapping.
6. Sparse interval genome and production lattice backend.
7. Exact population backend and particle/population hybrid backend.
8. Incremental observables and compiled function VM.
9. Strict NFsim/BioNetGen XML to NFIR lowering.
10. Persistent cache v2, invalidation, corruption, atomic replacement.
11. Counter RNG, replay, checkpointing and schedule-independent concurrency.
12. Legacy NFsim vs NFnext differential oracle.
13. Compartments, DOR, energy, time- and observable-dependent rate laws.
14. Exact backend equivalence and fallback semantics.
15. Generational IDs, SoA arena and allocation-free hot-loop invariants.
16. Startup/runtime/memory asymptotic scaling contracts.
17. Fuzzing, shrinking and metamorphic semantic validation.
18. Optional native codegen/SIMD/GPU equivalence contracts.
19. Rasi/uORF/whole-genome translation-specific gates.

## Important validation state

The reconstructed additive prototype still builds with future contracts OFF and
its baseline `nfnext_tests` passes. Enabling future contracts is intentionally
RED: the first canonical-NFIR target stops with the explicit message that
`nfnext/canonical.hpp` and `nfnext/validator.hpp` must be implemented.

This is deliberate. Future tests are requirements, not fake-green stubs.

The advanced test files from the preceding implementation session are retained
in `nextgen/tests/`, but the implementation files from that later session were
not present in the runtime when this package was created. Therefore this package
does not falsely claim to have re-executed those later green suites against the
older reconstructed source snapshot.

## Build behavior

Normal build:

```bash
cmake -S nextgen -B build -DNFNEXT_BUILD_FUTURE_CONTRACT_TESTS=OFF
cmake --build build -j
ctest --test-dir build --output-on-failure
```

TDD contract mode:

```bash
cmake -S nextgen -B build-contract \
  -DNFNEXT_BUILD_TESTS=OFF \
  -DNFNEXT_BUILD_BENCHMARKS=OFF \
  -DNFNEXT_BUILD_FUTURE_CONTRACT_TESTS=ON

# Build one subsystem at a time and turn it from RED to green.
cmake --build build-contract --target test_nfir_canonicalization_contract -j
```

Meta-tests:

```bash
python3 nextgen/tests/meta/test_test_budget.py
python3 nextgen/tests/meta/test_contract_coverage.py
python3 nextgen/tests/meta/test_no_silent_skip.py
```
