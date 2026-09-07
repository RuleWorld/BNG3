# NFnext implementation status

Target source lineage: `akutuva21/nfsim:perf/rasi-translation-optimization`.

## What was executable in the VM in this tranche

- NFIR model representation with primitive predicates/actions.
- Conservative indexed-rule family collapsing with coordinate normalization.
- Stable family ordering by original expanded reaction order.
- Dependency index from primitive molecular features to rule families.
- Backend classification (`Reference`, `Generic`, `Lattice`).
- Immutable compiled-model wrapper suitable for sharing across trajectories.
- Generational integer particle identities.
- Generic compact graph state with contiguous fixed-stride site-state and bond arrays.
- Local generic matcher for state/bound/free predicates.
- Native coordinate lattice with configurable particle footprint.
- Initiation, elongation, and termination kernels.
- Local propensity repair after occupancy changes.
- Fenwick weighted selector and two-level family/channel scheduler.
- Counter-based RNG keyed by seed + trajectory ID + event counter.
- Deterministic threaded trajectory batches.
- Binary NFIR cache with semantic fingerprint verification.
- Unit tests for RNG determinism, stale-ID rejection, scheduler selection, family-collapse safety,
  cache round-trip, generic graph matching/bonding, footprint exclusion, lattice simulation, and
  serial-vs-parallel trajectory identity.

## VM validation

Standalone build:

```text
ctest: 1/1 passed
```

Synthetic Rasi-shaped scaling benchmark:

```text
expanded_rules=9401
compiled_families=1
collapsed_rules=9401
dependency_features=2
backend=Lattice
compile_seconds=0.012945
events=1000000
null_events=0
simulation_seconds=0.221730
events_per_second=4509984.399648
```

This is a prototype microbenchmark, not a speed comparison against the existing NFsim branch.
The important result is that the runtime representation contains one parameterized family rather
than 9,401 reaction objects/channels.

## What is still required before this can replace NFsim for arbitrary BNGL

1. **Legacy XML/runtime -> NFIR adapter.** The optimized branch currently builds `ReactionClass`,
   `TemplateMolecule`, `TransformationSet`, functions, observables and compartments directly. A
   lossless compiler adapter must translate those semantics into NFIR.
2. **Full arbitrary-complex generic matcher.** The current generic backend handles compact graph
   storage and local state/bond predicates, but not arbitrary connected-pattern embedding,
   symmetry, molecularity constraints, local functions, DOR/Energy rules, or RuleMonkey semantics.
3. **Transformation lowering.** Every legacy transformation must be converted into primitive
   actions with exact product mapping semantics.
4. **Observable lowering.** Existing molecule/species/complex observables need compiled NFIR forms.
5. **Reference differential runner.** The new and legacy engines must execute fixed-seed models
   side-by-side and compare event selection/state/observable traces at defined semantic gates.
6. **Real Rasi/uORF compiler validation.** The family recognizer must operate on semantic rule
   structure from the adapter, not merely indexed names, before claiming collapse on real XML.
7. **Cache invalidation contract.** Cache keys need parser version, source-model hash, options and
   ABI/format compatibility.
8. **Optional SIMD/GPU backend.** Not implemented here. It should be attempted only after CPU NFIR
   kernels are correct and profiling proves a regular batch worth offloading.

## Important limitation of this session

The VM's ordinary network namespace could not resolve `github.com`, so `git clone` was impossible.
Repository inspection was performed through the authenticated GitHub connector, and the prototype
was built as an additive patch package. The included installer applies it to an actual checkout
without changing the default legacy build.
