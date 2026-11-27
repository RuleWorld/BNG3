# NFcore2 implementation status — continuation milestone

> Historical status record. Do not use its checkpoint as current evidence;
> consult `docs/CURRENT_PROGRESS.md`.

Base target: `akutuva21/nfsim` branch `perf/rasi-translation-optimization`, observed head `d13086bd3cf2fd268be5efea4d83089301479de3`.

## Implemented in the VM

NFcore2 remains an additive backend; the validated legacy NFsim execution path is not replaced.

### Compact execution core
- immutable `ExecutableModel` / `CompiledModel` separated from mutable `SimulationState`
- generational molecule handles
- type-local structure-of-arrays molecule state storage
- **typed cross-molecule bond references** (fixes the initial milestone's same-type/handle-only limitation)
- multi-reactant `MatchContext`
- population store
- dense or sparse first-class linear scaffolds; a 100,000,000-position sparse scaffold materializes only exceptions/occupants

### Compiled matcher and transform programs
Matcher bytecode now covers:
- molecule existence
- masked state tests
- bond present/free
- exact bond-to-another-reactant tests
- population thresholds
- scaffold state and occupancy tests

Transform bytecode now covers:
- state changes
- scaffold state changes
- scaffold occupant movement
- population changes
- cross-type bind/unbind
- molecule create/delete

This establishes a real general-graph path in addition to the Rasi/scaffold path.

### Rule-family compiler
- normalized `RuleInstanceIR`
- structural matcher/transform signatures
- repeated logical rules canonicalized into one `RuleFamilyDescriptor`
- per-member rate, parameter index, and coordinate arrays
- reverse mapping from original rule instance -> family/member

Synthetic result in this VM (C++11, `-O3`):
- 1,000,000 repeated logical rule instances -> 1 family / 1,000,000 compact members in ~0.20 s

### Legacy semantic lowering bridge
Added parser-independent `LegacyModelIR` / `LegacyRuleIR` and `LegacyLowerer`:
- deduplicates identical matcher programs
- deduplicates identical transformation programs
- performs rule-family canonicalization
- builds feature -> matcher invalidation edges
- returns explicit per-rule fallback reasons rather than approximating unsupported semantics

Currently explicit fallbacks include local functions, `connectedTo`, topology-changing rules not represented by the local transform IR, and unknown predicates/transforms. These remain assigned to the legacy oracle until individually implemented and parity-tested.

### Local dependency/scheduler path
- CSR feature -> matcher dependency index
- matcher -> rule-family reverse index
- `FeatureDelta` -> affected matcher -> affected family propagation
- hierarchical Fenwick family/member scheduler
- rate-aware member multiplicity updates (`rate * exact local multiplicity`)

### Shadow parity infrastructure
Added backend-neutral `ShadowState` / `ShadowEvent` and `ShadowComparator`:
- compares selected logical rule/member
- propensity
- time
- populations
- observables
- canonical semantic state hash

This is the contract intended for the old `System`/`ReactionClass` backend adapter and NFcore2 to compare event-by-event.

### Compile-once model image
Added versioned `ModelImage` binary serialization:
- molecule type descriptors
- feature descriptors
- matcher bytecode
- transform bytecode
- rule families + member arrays
- feature/matcher dependency index

Round-trip tests verify dependency edges survive loading. This is the foundation of the planned `.nfc` compile-once/load-many workflow for SBI and ensemble simulation. Memory mapping is not implemented yet.

## Validation completed

All standalone NFcore2 tests pass with both GCC and Clang in the internal VM under C++11.

Tests cover:
- stale generational handles and slot reuse
- hierarchical scheduler sampling
- rate-aware multiplicities
- rule-family canonicalization
- 100M-position sparse scaffold behavior
- scaffold elongation matcher/transform
- cross-type graph binding
- legacy lowering + explicit fallback
- shadow mismatch detection
- binary model-image round trip including dependency preservation

Current synthetic scaling smoke test:

```
instances=1000000 families=1 members=1000000 compile_ms≈200
genome_length=100000000 materialized_states=1 occupied=1 setup_ms≈0.025
```

## Critical next integration work

1. Add a thin adapter in the existing XML/BNGL construction path that emits `LegacyModelIR` from real `ReactionClass`/`TransformationSet` semantics.
2. Add canonical state extraction from legacy `System` into `ShadowState`.
3. Run initialization parity on existing small NFsim fixtures.
4. Run event-by-event parity on Rasi-500 and uORF with the legacy engine still selecting/firing events.
5. Implement exact context enumeration/indexing for supported ordinary graph patterns and implicit coordinate enumeration for scaffold families.
6. Route only parity-proven families through NFcore2; unsupported families continue through legacy NFsim.
7. Add expression/local-function DAG, `connectedTo` compiled predicate, topology-changing graph transforms, observables, and time-dependent rates.
8. Add `.nfc` CLI integration and mmap/read-only model-image loading.
9. Add trajectory snapshot/fork and batch API.
10. Benchmark against the optimized Rasi branch, not stock NFsim.

## Integration constraint in this session

The internal VM cannot resolve GitHub directly, and the connected GitHub installation returned HTTP 403 for branch creation. Therefore these changes are delivered as an additive patch/overlay rather than pushed commits. No validated branch was modified.
