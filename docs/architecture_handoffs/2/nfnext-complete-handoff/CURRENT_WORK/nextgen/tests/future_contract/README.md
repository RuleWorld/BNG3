# NFnext future-contract test suite

This directory is an executable specification of the clean-slate NFsim/NFnext
architecture. It is deliberately **not built by default**. Existing green tests
remain the regression gate for implemented functionality; this suite defines
what future implementation must satisfy.

## TDD rule

For each subsystem:

1. Enable one contract executable.
2. Observe RED from a missing API or failed semantic invariant.
3. Implement the smallest correct behavior.
4. Make the contract green.
5. Only then optimize.

Unsupported semantics must reject explicitly. A fallback to legacy NFsim is
acceptable; silent approximation is not.

## Coverage map

| Contract file | Proposed improvement exercised |
|---|---|
| `test_nfir_canonicalization_contract.cpp` | canonical NFIR, stable IDs, semantic fingerprints |
| `test_rule_family_contract.cpp` | semantic rule-family detection/collapse |
| `test_dependency_scheduler_contract.cpp` | exact mutation→dependency DAG and hierarchical scheduler |
| `test_generic_matcher_contract.cpp` | arbitrary graph matching, symmetry, topology, molecularity |
| `test_transformations_contract.cpp` | exact product mapping and atomic transformations |
| `test_lattice_interval_contract.cpp` | genome/lattice backend and sparse interval state |
| `test_population_hybrid_contract.cpp` | exact population and particle/population hybrid backend |
| `test_observable_function_contract.cpp` | incremental observables and compiled functions |
| `test_xml_adapter_contract.cpp` | strict BNGL/NFsim XML→NFIR lowering |
| `test_cache_contract.cpp` | persistent compiled model cache/invalidation/corruption |
| `test_rng_replay_concurrency_contract.cpp` | counter RNG, replay, thread independence |
| `test_differential_oracle_contract.cpp` | legacy-vs-NFnext semantic differential harness |
| `test_compartment_rate_contract.cpp` | compartments, local/global/DOR/energy rate semantics |
| `test_backend_equivalence_contract.cpp` | reference/generic/lattice/population backend equivalence |
| `test_memory_arena_contract.cpp` | generational IDs, SoA storage, allocation-free event loop |
| `test_scaling_stress_contract.cpp` | startup/runtime/memory scaling invariants |
| `test_fuzz_metamorphic_contract.cpp` | randomized/metamorphic semantic validation |
| `test_codegen_accelerator_contract.cpp` | native codegen/SIMD/GPU equivalence contracts |
| `test_rasi_translation_contract.cpp` | Rasi/uORF/genome-scale translational semantics |

The suite intentionally includes edge cases that should be rejected, because
exact stochastic simulation is harmed more by silent semantic approximation
than by a clean compiler fallback.
