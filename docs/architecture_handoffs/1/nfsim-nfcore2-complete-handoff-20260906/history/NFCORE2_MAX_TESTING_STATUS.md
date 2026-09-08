# NFcore2 maximum-testing expansion

This milestone intentionally prioritizes test construction over production implementation.

## Executable green suite

- 377 registered executable tests.
- GCC Release: 377/377 passing.
- GCC Debug: 377/377 passing.
- Existing milestone production sources were not expanded in this pass.
- New live suites add exhaustive/reference-model coverage for matcher bytecode, dense-vs-sparse scaffolds, Fenwick/hierarchical scheduling, rule-family compression, dependency invalidation, shadow semantic comparison, and graph/generational state-machine behavior.
- Stress workloads include up to 1,000,000 logical rule instances, 200,000 randomized scaffold updates, 200,000 molecule create/delete operations, 100,000 Fenwick updates, and 20,000 scheduler sampling grid points.

## Future-red specification suite

219 additional test contracts are written under `tests/NFcore2/future_spec/` and intentionally excluded from the default build until the corresponding subsystem is implemented. These tests are meant to be enabled before implementation so development proceeds red -> green.

Coverage includes:

- snapshots, restore, copy-on-write and trajectory fork semantics;
- batch trajectories, thread-count invariance and RNG isolation;
- expression/rate DAGs, observables, piecewise and continuous time hazards;
- generic graph fallback, automorphisms, symmetric sites, connectedTo and match-once semantics;
- indexed scaffold detection/lowering and genome-length scaling acceptance;
- hybrid particle/population execution;
- memory-mapped compiled model images and corruption handling;
- reference-vs-optimized differential execution including Rasi-500/uORF parity gates;
- SIMD/JIT specialization equivalence;
- optional GPU homogeneous kernels;
- low-overhead profiling contracts;
- compiler/frontend determinism and rule-family discovery;
- incremental connected-component correctness;
- reproducibility and NFsim-compatible RNG policy;
- end-to-end performance/scaling acceptance gates.

## Test/code density

- Live test source/header lines: 2,982.
- Future-red spec test lines: 296.
- Total testing/specification lines: 3,278.
- NFcore2 implementation lines: 1,586.
- Testing/specification to implementation ratio: ~2.07x.

The line ratio understates effective testing density because many new tests are parameterized loops that check tens of thousands to millions of states/operations per registered test.
