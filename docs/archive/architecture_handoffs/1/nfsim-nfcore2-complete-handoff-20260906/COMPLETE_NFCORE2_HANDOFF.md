# NFsim / NFcore2 Complete Engineering Handoff

> Archived snapshot from 2026-09-06. See `docs/CURRENT_PROGRESS.md` for the
> live branch and current verification state.

**Date:** 2026-09-06  
**Target repository:** `akutuva21/nfsim`  
**Target working branch:** `perf/rasi-translation-optimization`  
**Last branch head observed during this work:** `d13086bd3cf2fd268be5efea4d83089301479de3` (`d13086b`)  
**Status:** substantial additive prototype + extensive executable tests + future-red architectural specification; **not merged or pushed to GitHub**.

---

## 1. Why this work exists

The immediate motivation is NFsim performance on Rasi-style transcription/translation models and, beyond Rasi, the desire to support models whose logical rule count or structured state approaches genome scale. Stock/general NFsim is designed to avoid explicit species-network generation, but large Rasi models expose a different scaling problem: thousands to potentially millions of syntactically expanded rules that are structurally repetitive, plus long polymer/scaffold-like state. The architectural goal of NFcore2 is therefore not merely to micro-optimize existing NFsim classes. It is to build an execution core in which cost is dominated by the **local state affected by an event**, rather than by total rule count, total genome length, or dense molecule×rule bookkeeping.

The long-term conceptual target is to solve three independent explosions:

1. **Species compression** — the original network-free motivation.
2. **Rule compression** — repeated positional/logically equivalent rules should become compact rule families.
3. **State-structure compression** — long DNA/RNA/polymer/genome structures should use representations appropriate to their topology instead of millions of generic heap graph objects.

The intended end state is still a general BNGL/NFsim-compatible simulator. Rasi-specific optimizations should be semantics-preserving lowerings, with arbitrary unsupported BNGL semantics retaining an exact generic/reference fallback.

---

## 2. Existing optimized NFsim baseline that motivated the rewrite

This work was designed against the user's already heavily optimized Rasi branch, **not stock NFsim**. Important previously validated results on that branch included:

- Rasi-500 and uORF fixtures with byte-identical parity across legacy/filter/differential modes.
- Rasi kernel speedups independently reproduced on representative horizons of roughly **47× to 234×**, depending on horizon.
- uORF speedups of roughly **53× to 171×** on tested horizons.
- Dense per-molecule mapping membership storage replaced with lazy paged storage, reducing Rasi-500 peak RSS from about **1.686 GB to 125 MB (~13.5×)**.
- Initial membership preparation reduced from roughly **10.7 s to ~0.03 s**.
- Total startup reduced from roughly **12.1 s to ~1.81 s** in the measured Rasi setup.
- Eight concurrent Rasi processes became possible on the 24 GB development machine where four previously OOM'd.
- Sparse/local membership filtering, cached rate factors, sparse selector blocks, batched propensity updates, compact partner pools, and related hot-path work were already present or being developed.

Those results are important because they validate the direction of the rewrite: the largest wins came from eliminating dense rule-membership work and avoiding broad candidate processing. However, the optimized branch still fundamentally inherits NFsim's original runtime architecture: syntactic rules remain heavy runtime reaction objects, arbitrary molecular graphs remain the universal representation, and local optimizations are layered on top of that structure.

NFcore2 attempts to make the successful ideas architectural rather than incremental.

---

## 3. Original ground-up architecture proposed

The proposed successor architecture was:

`BNGL/XML -> semantic AST -> normalized graph-rewrite IR -> static analysis -> compact executable model -> mutable trajectory state`

The principal design goals were:

- Event cost approximately `O(local affected state + log active propensity groups)`, not `O(number of rules)`.
- Memory approximately `O(particles + structured state + active matches + rule-family metadata)`, not `O(particles × rules)`.
- Compile once and reuse a compact model image for many trajectories/parameter sets.
- Separate immutable `CompiledModel` / executable metadata from mutable `SimulationState`.
- Use integer/generational handles rather than pointer identity in the new core.
- Use data-oriented type-local storage instead of per-molecule STL-heavy object graphs in hot paths.
- Compile matchers and transformations into compact instruction programs.
- Share matcher logic between many rules.
- Maintain feature-level dependencies so an event invalidates only matchers that actually read changed features.
- Compress repeated rules into `RuleFamily` objects containing shared matcher/transform programs plus compact member/coordinate/rate arrays.
- Introduce first-class indexed scaffold storage for DNA/RNA/polymer tracks.
- Support population variables/structured pools for abundant simple species.
- Use hierarchical propensity selection: family first, then member/coordinate.
- Keep a generic exact graph fallback for BNGL constructs that cannot be specialized safely.
- Eventually support snapshot/fork, batch trajectories, expression/rate DAGs, compiled `.nfc` images, profiling, SIMD/JIT specialization, and optional GPU kernels for homogeneous workloads.
- Preserve a reference execution path and perform event-by-event differential validation before optimized routing is enabled.

A particularly important Rasi transformation is the intended conversion of rules such as:

`elongate_1`, `elongate_2`, ..., `elongate_50000`

from 50,000 independent heavyweight reaction objects into something conceptually like:

- one matcher program,
- one transformation program,
- one rule family,
- arrays of 50,000 coordinates/rates/parameter references,
- local feature dependencies around the fired coordinate.

That is the main route by which a future engine could make event cost nearly independent of the number of logical genome positions.

---

## 4. What has actually been implemented in NFcore2

Everything in `src/NFcore2/` is additive prototype code. The legacy NFsim execution path has not been replaced.

### 4.1 Strong IDs and generational molecule handles

NFcore2 defines compact strongly typed IDs for molecule types, matchers, rule families, scaffolds, populations, features, and transform programs. Molecules use slot + generation handles. Reusing a storage slot increments its generation so stale references can be detected instead of silently aliasing a newly allocated molecule.

This was a deliberate response to the hazards of pointer-heavy pool reuse in graph simulators.

### 4.2 Mutable simulation state separated from immutable executable metadata

The prototype separates model metadata from per-trajectory state. `SimulationState` owns mutable molecule/population state, while compiled model structures own immutable descriptors, matcher programs, transform programs, rule-family metadata, and dependency indices.

This is foundational for later shared-model batch simulation, snapshots, copy-on-write forks, and SBI workloads.

### 4.3 Type-local molecule storage and typed graph references

`MoleculeStore` provides compact type-local storage. An early prototype stored bonds as untyped molecule handles; testing identified that this was insufficient for arbitrary cross-type BNGL bonds. It was corrected to use typed `MoleculeRef { MoleculeTypeId, MoleculeHandle }` references.

The graph layer now supports reciprocal cross-type bonds and validates stale handles.

### 4.4 Safe graph bind/unbind/create/delete primitives

The transformation runtime includes operations for:

- state assignment,
- checked state increment/decrement,
- bind,
- unbind,
- molecule creation,
- molecule deletion,
- scaffold state changes,
- scaffold occupant movement,
- population changes.

Testing exposed a critical deletion problem: deleting a molecule without clearing reciprocal partner bonds leaves dangling graph state. The implementation was hardened so graph deletion clears reciprocal references safely.

Legacy NFsim unbinding presented another mismatch: NFsim can encode only the local unbinding site and discover the reciprocal partner site dynamically, while the first NFcore2 transform representation expected both sites. Tests were written first, then reciprocal-site inference was implemented transactionally. NFcore2 now verifies the reciprocal edge before mutating either endpoint; malformed asymmetric graphs fail without producing a half-unbound state.

### 4.5 Compiled matcher bytecode

A compact matcher interpreter exists for the supported subset. It includes checks for:

- molecule/type existence,
- masked state predicates,
- bond present/free,
- exact bond-to another reactant,
- population thresholds,
- scaffold state/free conditions.

`MatchContext` supports multiple reactants. This is still a small interpreter rather than the complete planned generic graph matcher/shared matcher DAG.

### 4.6 Compiled transformation bytecode

A compact transformation interpreter exists for supported local operations. This is the beginning of replacing virtual transformation dispatch with compact data-oriented programs.

A sanitizer-driven correction changed opcode storage from unchecked enum representations to validated raw integer opcodes. Corrupted serialized bytecode could otherwise create an out-of-range C++ enum value and trigger undefined behavior before validation code had a chance to reject it.

### 4.7 Feature descriptors and local dependency propagation

`FeatureDelta` represents local changes. `CompiledModel` contains feature -> matcher dependencies and matcher -> rule-family reverse dependencies. An event can therefore identify affected matchers/families without scanning every rule.

An important test-driven refinement changed dependency construction from conservatively invalidating writers to invalidating based on **features matchers actually read**. Duplicate structural rules are also prevented from producing duplicate dependency edges.

This is a prototype of the intended event-local invalidation architecture.

### 4.8 Rule-family canonicalization

`RuleCompiler` groups repeated logical rule instances that share matcher and transformation signatures into a compact family. Each family stores compact member metadata such as rate, parameter index, and coordinate.

Synthetic tests include compression of **1,000,000 logical rule instances into one family**. Earlier smoke benchmarking compiled one million repeated instances into one family in roughly **0.20 seconds** in the internal VM. This is an architectural smoke test, not a production NFsim benchmark.

### 4.9 Hierarchical scheduler / Fenwick selection

A Fenwick-based scheduler supports outer family and inner member activity. Member activity can be expressed as rate × multiplicity. Tests compare it repeatedly against naive reference selection/update implementations.

This is the prototype for hierarchical family/member scheduling. It does not yet implement all planned aggregate interval/run-length/segment-tree strategies for genome-scale homogeneous regions.

### 4.10 Dense and sparse first-class scaffold representation

`ScaffoldStore` supports dense and sparse linear scaffolds. Sparse storage keeps default state plus exceptions/occupants, allowing a logically enormous scaffold to exist without one general molecule object per coordinate.

A 100-million-position sparse scaffold smoke test materializes only changed/occupied positions. Reference-model tests compare sparse behavior against dense naive representations across large randomized mutation sequences.

This is storage infrastructure only. Automatic compiler detection/lowering of real BNGL polymers into this representation has **not** yet been implemented.

### 4.11 Legacy semantic bridge

`LegacyModelIR`, `LegacyRuleIR`, predicate/transform IRs, and `LegacyLowerer` provide a parser-independent boundary between old NFsim semantics and NFcore2.

The bridge:

- deduplicates matcher programs,
- deduplicates transformation programs,
- canonicalizes rules into families,
- preserves original rule -> family/member mappings,
- builds local dependency information,
- explicitly classifies unsupported constructs rather than approximating them.

This is intentionally conservative. A construct that cannot be proven equivalent remains on the legacy path.

### 4.12 NFsim adapter contract and normalized reader

A normalized NFsim snapshot/adapter layer was written so extraction of legacy semantics is separated from validation/lowering. This keeps most correctness logic testable without linking the full legacy executable.

The supported safe subset includes ordinary root-local state predicates/exclusions, free/bound conditions, state assignment, increment/decrement, ordinary binding, unbinding, and single-molecule deletion.

Fallback is intentional for semantics that have not been represented exactly, including examples such as:

- `connectedTo`,
- unresolved internal graph topology/pattern nodes,
- some partner-state graph predicates,
- local-function semantics/rates,
- compartment moves,
- whole-species deletion,
- more complex creation/population semantics,
- other arbitrary graph constructs not proven by the specialized reader.

### 4.13 NFsim binding transform decoder

Inspection of the real Rasi branch showed that NFsim's `BindingTransform` stores `otherReactantIndex` and `otherMappingIndex`. The second half transformation contains the reciprocal component index. A tested decoder therefore reconstructs ordinary binding exactly from stored NFsim metadata instead of parsing rule names or guessing partner sites.

Tests cover cross-reactant binding, same-reactant binding, and malformed/inconsistent transformation tables.

### 4.14 Thin native NFsim reader

A real legacy-facing reader has been written against the APIs observed on `perf/rasi-translation-optimization`. It is intentionally thin and pushes semantics into the already heavily tested normalized adapter layer.

It requires a tiny read-only introspection patch to legacy NFsim. The patch adds access to:

- a `ReactionClass`'s `TransformationSet`,
- the target/final state value of `StateChangeTransform`,
- stored binding partner indices.

A legacy-specific hazard was discovered during audit: `RemoveMoleculeTransform::getComponentIndex()` intentionally exits the process. The reader was corrected so it only asks for component indices on transform classes where that accessor is semantically valid.

**Important:** because the complete repository could not be cloned into the VM, this native reader has not yet been compiled as part of the full NFsim tree. The normalized/standalone layers are tested, but full-tree compilation remains a required integration gate.

### 4.15 Shadow/differential comparison infrastructure

`ShadowState`, `ShadowEvent`, `ShadowComparator`, and stable semantic hashing provide backend-neutral structures for future event-by-event parity checking.

The design intentionally hashes canonical semantic state rather than pointer addresses. The intended next use is:

legacy NFsim selects/fires event -> capture canonical before/event/after -> NFcore2 evaluates corresponding semantics -> compare state, propensity, event identity, and result.

Actual Rasi/uORF event-by-event shadow execution has **not** yet been performed.

### 4.16 Versioned binary model image prototype

`ModelImage` serializes/deserializes the current executable metadata subset, including molecule descriptors, features, matcher bytecode, transform bytecode, rule families/members, and dependency indices.

Round-trip and malformed-image tests exist. Dependency edges are preserved across serialization.

This is only a prototype of the planned `.nfc` format. It is **not yet** a production portable/mmap format. The current format still needs explicit portable endian/schema rules, checksums/compatibility policy, scaffold layouts, expressions, observables, debug/symbol metadata, and read-only mmap support.

---

## 5. Test-first policy and current testing status

After the initial prototype, the user explicitly requested that development become test-first and that testing code be at least 1.5× implementation code. The workflow was changed accordingly:

1. write failing tests,
2. run and confirm the failure,
3. implement the minimum semantic change,
4. rerun regression/stress tests,
5. use sanitizers to look for defects normal tests cannot expose.

The latest packaged tree contains approximately:

- **1,586 implementation lines** in `src/NFcore2`,
- **2,961 live test lines** in the main NFcore2 test suite,
- **296 future-red specification lines**,
- **3,257 total live + future specification test lines**,
- roughly **2.05× test/specification code per implementation line**.

The latest live suite reached **377/377 passing tests** in the maximum-testing milestone. Earlier adapter/TDD milestones were also checked under multiple compilers/configurations, including GCC Debug, GCC Release, Clang Debug, and GCC ASan+UBSan. Sanitizers were particularly valuable in finding invalid-enum UB in malformed bytecode handling.

### 5.1 Major live test categories

The live suite includes tests for:

- strong ID behavior,
- stale generational handles,
- slot reuse,
- molecule create/delete cycles,
- typed cross-molecule bonds,
- reciprocal graph invariants,
- transactional bind/unbind behavior,
- graph deletion cleanup,
- state assignment/increment/decrement overflow and underflow,
- population arithmetic overflow/underflow,
- simulation-time validity,
- matcher target/reactant validity,
- exhaustive matcher state-mask truth tables,
- scaffold bounds and occupant collision behavior,
- dense-vs-sparse scaffold reference equivalence,
- very large sparse scaffold storage,
- Fenwick scheduler correctness,
- hierarchical scheduler correctness,
- rate × multiplicity activity,
- randomized scheduler updates/sampling against naive references,
- rule-family canonicalization,
- million-rule compression stress,
- feature dependency construction,
- matcher -> family reverse dependency lookup,
- duplicate dependency suppression,
- malformed/non-finite rule metadata rejection,
- executable-model structural validation,
- model-image round trips,
- malformed/corrupted model-image rejection,
- opcode validation,
- shadow-state/event equality and mismatch localization,
- stable semantic hashing,
- legacy semantic lowering,
- explicit fallback classification,
- normalized NFsim dependency categories,
- normalized NFsim transform categories,
- binding-table decoding,
- inferred unbinding,
- native-reader normalized contracts,
- randomized trajectory-copy isolation.

### 5.2 High-volume stress/reference tests

The suite is deliberately not just hundreds of tiny assertion cases. It contains long-running logical stress loops such as:

- up to **1,000,000 logical rules** in rule-family compression tests,
- roughly **200,000 randomized scaffold mutations** against a reference representation,
- roughly **200,000 molecule create/delete operations**,
- roughly **100,000 scheduler updates**,
- large population-conservation loops,
- repeated graph bind/unbind reciprocity checks,
- exhaustive state-mask matrices.

The purpose is to make the tests approximate a semantic specification and catch state-machine failures that simple examples miss.

---

## 6. Important defects found by the tests

The test-first work was not cosmetic. It found real design/implementation defects, including:

1. **Untyped bond references** could not represent arbitrary cross-type graph bonds. Replaced by typed `MoleculeRef`.
2. **Deletion left reciprocal stale bonds.** Graph deletion was hardened.
3. **Population underflow/overflow** was insufficiently guarded.
4. **Invalid/non-finite simulation times** were accepted.
5. **Missing secondary reactants** could be misinterpreted by bond matching.
6. **Binding onto already occupied sites** could destructively overwrite graph state.
7. **Scaffold occupant movement** could overwrite an existing occupant.
8. **Scaffold bounds/coordinate arithmetic** required stronger validation.
9. **Scheduler non-finite values** needed rejection.
10. **Dependency invalidation was overly conservative** and could invalidate writers unnecessarily; it was changed toward read-based dependencies.
11. **Duplicate structural rules could duplicate dependency edges.** Deduplication was added.
12. **Malformed rule/program references** needed engine-boundary validation.
13. **Corrupted opcode enum values caused UB before validation.** Bytecode opcode storage was changed to validated raw integers.
14. **Legacy NFsim unbinding does not encode reciprocal site directly.** NFcore2 gained tested transactional reciprocal-site inference.
15. **Legacy `RemoveMoleculeTransform::getComponentIndex()` exits the process.** Native introspection now avoids invalid generic getter calls.
16. Several new maximum-testing failures turned out to be **incorrect test assumptions**, and those tests were corrected rather than changing correct production behavior. This is recorded because test suites themselves must be treated as fallible specifications until validated.

---

## 7. Future-red specification suite

The directory `tests/NFcore2/future_spec/` contains tests/specification code for architecture that is deliberately **not implemented yet**. These are not part of the default green build. The intended development process is to enable a subsystem's specification first, obtain red tests, and only then implement it.

Current future specification areas include:

### 7.1 Snapshot/fork and copy-on-write trajectories

Planned requirements include cheap state snapshots, independent mutation after fork, shared immutable model metadata, and eventually page-level COW where useful. This is especially important for SBI and perturbation ensembles.

### 7.2 Batch trajectory execution

The eventual API should run many independent trajectories sharing one compiled model. CPU multicore parallelism should primarily target independent trajectories rather than forcing parallelism into a single exact SSA event loop.

### 7.3 Expression/rate dependency DAG and continuous hazards

Rates should be classified as constant, local-state dependent, observable dependent, time dependent, or combinations. Piecewise changes should be schedulable; genuinely continuous time-dependent hazards require mathematically correct integration/inversion rather than naive propensity refreshes.

### 7.4 Generic graph fallback and automorphisms

The optimized matcher cannot replace arbitrary BNGL semantics until exact handling exists for general graph patterns, symmetric sites, automorphism factors, cycles, overlapping reactants, and other difficult cases. The specification requires a generic exact fallback rather than approximation.

### 7.5 Compiler frontend and scaffold lowering

A future compiler should recognize repeated linear/circular scaffold constructions and positional rule families and lower them to indexed scaffold operations. It must prove the lowering semantics before replacing generic graphs.

### 7.6 Hybrid populations

Abundant simple species should be representable as population variables while still interacting exactly with particle/scaffold rules where supported.

### 7.7 Portable/mmap model image

The prototype model image should evolve into a fixed, versioned, portable format that can be loaded read-only/mmap and shared between trajectories/processes where appropriate.

### 7.8 Reference-vs-optimized differential execution

This is the central correctness gate. Every supported optimized semantic domain should be compared to a simple/reference implementation. Rasi-500 and uORF are explicit acceptance targets.

### 7.9 Reproducibility/RNG policy

The eventual engine should distinguish semantic stochastic reproducibility from strict historical NFsim internal ordering/RNG compatibility. Compatibility mode may be slower if necessary; architecture should not be permanently constrained by accidental old ordering unless scientifically required.

### 7.10 Connectivity/components

General mutable complexes need exact component tracking. Proposed direction: cheap union on bond addition, split detection on deletion, relabel smaller side, version component predicates, and only adopt sophisticated dynamic-connectivity structures if profiling justifies them.

### 7.11 Profiling

Low-overhead counters should include events/sec, matcher executions/event, dependency updates/event, propensity updates/event, bytes/molecule/match, rejection rates, family activity distributions, and scaffold update radius. Profiling should compile out or be near-zero overhead when disabled.

### 7.12 SIMD/JIT specialization

Only after the architecture is correct and profiled: specialize hot matcher programs, use packed/bitset/SIMD operations, and optionally JIT very hot programs. The project should not JIT the old pointer-heavy architecture.

### 7.13 Optional GPU kernels

GPU work remains intentionally late. Suitable targets are thousands of independent trajectories or highly homogeneous scaffold/lattice kernels. A generic pointer-heavy graph port is explicitly not the plan.

### 7.14 Scaling acceptance

The eventual killer benchmark is that event throughput remains approximately flat as a local-rule scaffold grows from kilobases toward megabases/genome scale, assuming unchanged local event structure. Memory should depend primarily on active/non-default state rather than logical genome length where sparse representations apply.

---

## 8. What is NOT done

This section is intentionally explicit so another agent does not mistake the prototype for a completed simulator.

### 8.1 NFcore2 is not yet the NFsim production execution engine

The code is additive. Existing NFsim has not been routed wholesale through NFcore2. There is no claim that current Rasi simulations run through this engine.

### 8.2 No real Rasi-500 or uORF event-by-event parity has been completed

The infrastructure for shadow comparison exists, but the actual full-tree integration needed to run legacy and NFcore2 side by side on the known Rasi/uORF fixtures has not been performed.

Required future gates include:

1. full NFsim build with the native reader/introspection patch,
2. initialization extraction parity,
3. matcher/match-count parity,
4. propensity parity,
5. selected-event identity/member parity,
6. post-event molecular/scaffold/population state parity,
7. long-horizon trajectory differential testing,
8. only then routing supported families to NFcore2.

### 8.3 No full arbitrary graph matcher

Current matcher bytecode covers a useful local subset. It is not yet a complete BNGL graph isomorphism/mapping engine. Complex graph patterns must remain legacy/reference fallback.

### 8.4 No shared matcher DAG/discrimination network

Matcher program deduplication exists, but the larger planned shared matcher DAG with selective partial-match materialization and cost-based planning does not.

### 8.5 No automatic BNGL rule-family/scaffold compiler

The family compiler works on normalized rule instances. It does not yet parse arbitrary BNGL/XML and automatically prove that thousands of positional rules are instances of one family.

### 8.6 No automatic genome/polymer lowering

Scaffold storage exists, but real DNA/RNA/polymer patterns are not yet automatically converted from NFsim graphs to indexed scaffold state.

### 8.7 No exact context enumeration/match-count maintenance engine

The scheduler can consume member activity/multiplicity, but the complete runtime machinery that incrementally maintains exact eligible contexts for all supported matcher families is not finished. This is a major missing execution component.

### 8.8 No expression/observable DAG

Local/global functions, observables, time-dependent rate laws, and continuous hazards are not yet represented by the new core.

### 8.9 No complete population/hybrid execution

A population store and basic transforms exist, but complete exact hybrid particle/population semantics are not integrated.

### 8.10 No snapshot/COW/batch API

These are specified but not implemented.

### 8.11 No production `.nfc` mmap format

The current binary image is a prototype serializer, not the final portable format.

### 8.12 No SIMD/JIT/GPU implementation

These remain deliberately deferred until correctness and architecture are proven.

### 8.13 No proof of genome-length-independent throughput

The sparse scaffold storage and local architecture are prerequisites, but the actual end-to-end benchmark cannot be claimed until the compiler, exact matching/activity maintenance, and execution path are integrated.

---

## 9. What could not be done in this session and why

### 9.1 The internal VM could not clone GitHub

A direct clone of the target branch was attempted:

`git clone --branch perf/rasi-translation-optimization https://github.com/akutuva21/nfsim.git ...`

The VM had no usable outbound GitHub network path (`Could not resolve host: github.com`; direct-IP attempts also failed). Therefore the complete target repository could not be placed in the container through ordinary git.

### 9.2 GitHub integration was effectively read-only for branch creation

The connected GitHub interface could read repository files and was used extensively to inspect real NFsim headers/implementation. However, attempting to create a working branch returned **403 Resource not accessible by integration**. Therefore this work was **not pushed**, and no claim should be made that a GitHub branch contains NFcore2.

### 9.3 Consequence: native full-tree compilation was impossible here

Because the VM lacked the complete branch checkout and the GitHub connector could not create/write the branch, the thin native reader and legacy introspection patch could not be compiled inside the exact complete NFsim tree in this session.

This is why the handoff contains patches/overlay code rather than a pushed commit.

### 9.4 Consequence: true Rasi/uORF parity could not yet run

The known Rasi/uORF validation fixtures require the real full NFsim build and model inputs. The standalone NFcore2 tests can validate its internal contracts, but they cannot substitute for real event-by-event differential execution against the optimized NFsim branch.

---

## 10. Repository/package layout

This ZIP is intended to be self-contained as an engineering handoff.

### `src/NFcore2/`

Latest NFcore2 implementation source.

### `tests/NFcore2/`

Latest executable test suite, standalone CMake harness, synthetic benchmark, and future-red specifications.

### `patches/nfcore2-native-adapter-full.patch`

Additive NFcore2/native-adapter patch from the native-adapter milestone. This is the primary large implementation patch available from that milestone.

### `patches/legacy-nfcore2-introspection.patch`

Small read-only changes needed in legacy NFsim for the native reader.

### `patches/nfcore2-max-testing-tests-only.patch`

Incremental maximum-testing patch containing the later testing expansion.

### `patches/nfcore2-max-testing.patch`

Combined maximum-testing patch artifact generated in the latest testing phase.

### `history/`

Earlier milestone patches/status reports are retained for provenance and debugging. They should generally not be stacked blindly on top of the latest combined state. They document how the implementation evolved.

---

## 11. How to use this handoff

### Preferred approach: overlay latest source/tests into a clean target branch checkout

1. Obtain a clean checkout of `akutuva21/nfsim` at the intended Rasi branch/commit.
2. Create a new development branch.
3. Copy `src/NFcore2/` into the repository's `src/NFcore2/`.
4. Copy `tests/NFcore2/` into `tests/NFcore2/`.
5. Apply `patches/legacy-nfcore2-introspection.patch` carefully and resolve only if the target branch has moved.
6. Compile the standalone NFcore2 suite first.
7. Then compile the complete NFsim tree with the native reader included.
8. Do **not** enable NFcore2 as the default execution path yet.

The root NFsim CMake observed on the target branch recursively globbed `src/*cpp`, so `.cpp` files placed under `src/NFcore2` should be picked up by the normal build. Verify this against the actual current branch before relying on it.

### Patch-based approach

The included patches are useful for review/reconstruction, but because work proceeded through multiple milestones without a writable full git checkout, the safest source of truth is the **latest `src/` + `tests/` overlay in this ZIP**. Treat historical patches as provenance rather than a mandatory patch stack.

---

## 12. Recommended next implementation order — still test first

### Gate 1: full-tree compilation

Before adding features, compile the current native reader against the real branch. Write/enable compile-level adapter tests first. Fix only actual API mismatches; do not broaden semantics.

### Gate 2: real model semantic extraction

On tiny existing NFsim fixtures, compare the normalized `LegacyModelIR` produced from real `System` objects against expected predicates/transforms/rates. Explicitly assert fallback reasons for unsupported constructs.

### Gate 3: Rasi/uORF initialization inventory

For Rasi-500 and uORF, produce a report of:

- total reactions,
- supported vs fallback reactions,
- unique matcher programs,
- unique transform programs,
- resulting rule families,
- family member counts,
- feature/dependency counts,
- unsupported semantic reasons.

This alone will show how much of Rasi can be compressed before executing a single event.

### Gate 4: exact context enumeration for supported local patterns

Write tests against legacy NFsim match lists first. Implement exact context/multiplicity enumeration for the simple/local matcher subset. Compare counts and sampled mappings.

### Gate 5: propensity parity

For every supported family/member, compare NFcore2 activity against legacy NFsim before selection. Zero tolerance unless floating-point semantics require a documented tolerance.

### Gate 6: shadow event execution

Let legacy NFsim choose the event initially. Apply the corresponding event to a mirrored NFcore2 state and compare canonical post-state. This isolates transform/state parity from scheduler/RNG parity.

### Gate 7: NFcore2 selection parity/statistical validation

Once propensity state is exact, test hierarchical selection. Strict event identity under identical RNG is desirable where ordering is intentionally compatible; otherwise validate distributional equivalence separately from compatibility mode.

### Gate 8: route only proven families

Add an opt-in flag. A rule family executes through NFcore2 only when its semantic class has passed the differential gates. Everything else remains legacy.

### Gate 9: scaffold compiler lowering

After ordinary local rules are proven, tackle the major architectural win: recognize Rasi positional polymer rules and convert them into indexed scaffold families. Tests must prove equivalence against the graph representation across boundaries, collisions, initiation/termination, deletion, symmetric/overlap cases, and randomized trajectories.

### Gate 10: scaling benchmark

Measure startup, RSS, events/sec, matcher updates/event, propensity updates/event, and logical rule count for Rasi ladders and synthetic genome lengths. The key acceptance criterion is that local event cost should stop growing materially with total logical genome length.

### Gate 11: snapshots/batch API and SBI-oriented execution

Once single-trajectory semantics are proven, implement shared immutable models, snapshots/forks, and batch trajectory execution. This is likely a very high practical payoff for parameter inference/SBI.

### Gate 12: expressions, generic graph fallback, populations

Expand semantic coverage without weakening the fallback contract.

### Gate 13: specialization only after profiling

SIMD, JIT, and GPU kernels should be driven by measured bottlenecks in the new architecture, not added because they sound fast.

---

## 13. Technical debt / risks to keep visible

- The native reader is based on source inspection of the real branch but still needs exact full-tree compile validation.
- The model image prototype should not become a compatibility promise in its current form.
- Match contexts currently model a limited set of reactant/scaffold relationships; arbitrary multi-scaffold patterns are not solved.
- Symmetry/automorphism factors require rigorous reference testing.
- Creation/deletion semantics need complete feature-count/existence invalidation once exact runtime matching is integrated.
- Sparse scaffolds may eventually need typed occupants if multiple occupant classes share a track; do not assume a single implicit type unless compiler proof guarantees it.
- Whole-complex deletion and topology-sensitive rules are particularly dangerous to specialize prematurely.
- Continuous time-dependent rates need correct hazard mathematics, not just periodic updates.
- Reproducibility policy must be explicit before changing selector ordering.
- Performance tests must compare against the **already optimized Rasi branch**, not stock NFsim, otherwise improvements will be overstated.

---

## 14. Bottom line

This package is **not a completed NFsim rewrite**. It is a fairly substantial architectural prototype plus a disproportionately large test/specification suite designed to make the rest of the rewrite safer.

The most important accomplishments are:

1. the new core has concrete representations for compact model metadata, mutable state, typed/generational graph references, local matcher/transform bytecode, rule families, hierarchical scheduling, sparse scaffolds, dependency invalidation, serialization, legacy lowering, and shadow comparison;
2. the project moved to a genuine test-first workflow and the tests have already found multiple nontrivial correctness defects;
3. the legacy adapter boundary is now narrow enough that the next meaningful milestone is no longer abstract architecture work—it is **compiling inside the real NFsim tree and performing real Rasi/uORF differential validation**;
4. unsupported semantics are intentionally explicit fallbacks, preserving the principle that performance optimization must never silently change BNGL meaning;
5. future architectural work is represented by red-test specifications so implementation can proceed from contracts rather than retrospective tests.

The strongest next move is therefore **not** to add more speculative optimization. It is to get this overlay into a real checkout of `perf/rasi-translation-optimization`, compile it, run the real adapter against Rasi-500/uORF, and turn the existing shadow infrastructure into event-by-event parity gates. Once those gates are green, the scaffold/rule-family architecture can start replacing the old runtime path family by family.
