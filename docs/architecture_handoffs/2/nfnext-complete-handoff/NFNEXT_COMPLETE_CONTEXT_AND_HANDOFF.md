# NFnext / NFsim Rasi Rewrite — Complete Context, Current State, Test-First Handoff, and Remaining Work

> Archived snapshot from 2026-09-06. Current branch state and qualification
> status are in `docs/CURRENT_PROGRESS.md`.

**Handoff date:** 2026-09-06  
**Primary target lineage:** `akutuva21/nfsim`, branch `perf/rasi-translation-optimization`  
**Project:** NFsim Rasi / genome-scale rule-based simulation  
**Status of this archive:** preservation snapshot + executable prototype + comprehensive future-contract test suite. It is **not** a claim that NFnext is a complete replacement for NFsim.

---

## 0. Why this document exists

This archive is intended to be sufficient for another engineer, another ChatGPT/Codex session, or a future continuation of this project to understand the motivation, recover the surviving code, know which results are real, know which claims are only architectural targets, and continue implementation without having to reconstruct the reasoning from chat history.

The project began from a practical problem: the existing NFsim architecture can simulate large rule-based systems without fully enumerating the reaction network, but Rasi-style translation models and eventual genome-scale models introduce a second kind of redundancy that the classic architecture still represents very explicitly. Thousands or millions of rules can be structurally identical except for a coordinate or other regular index. Even after substantial optimization of the legacy engine, those position-expanded rules still create avoidable startup work, dependency bookkeeping, memory consumption, matching work, and runtime scheduling overhead.

The clean-slate proposal therefore changes the unit of compilation. Instead of merely making each legacy `ReactionClass` faster, NFnext treats BNGL/NFsim input as a language to compile into a compact semantic intermediate representation. Repeated positional rules can then be represented as one parameterized rule family, regular genome/transcript dynamics can be handled by a dedicated sparse coordinate backend, and arbitrary graph chemistry remains available through a generic exact backend. The existing optimized NFsim implementation remains the semantic oracle until the new implementation passes strong differential gates.

The user subsequently imposed an explicit engineering discipline: **tests first, implementation second**, with at least **1.5× as much testing code as new implementation code**. The most recent tranche emphasized writing as much testing code as possible for every proposed architectural improvement. That is why a large portion of this archive consists of opt-in RED executable specifications for functionality that is not yet implemented.

---

# 1. Executive summary

## 1.1 What is in this archive

This ZIP contains four kinds of material:

1. **`CURRENT_WORK/`** — the current reconstructed NFnext source tree that is available in the runtime now. This is an executable initial prototype plus the expanded test corpus and future contracts.
2. **`PATCHES/`** — both the historical additive NFnext patch and a newly generated patch capturing the current testing/contracts changes relative to the initial executable prototype.
3. **`REFERENCE_SNAPSHOTS/`** — the initial executable prototype extracted from the original prototype ZIP, retained as a stable reference/baseline for interpreting the fresh patch.
4. **`SURVIVING_ARTIFACTS/`** — the standalone prototype ZIP, standalone testing-suite ZIP, and the surviving sparse artifact directories from the session. These are included even when they duplicate files elsewhere because this package is intended as a preservation archive.

The archive also contains this document, validation output, file inventory, and SHA-256 checksums.

## 1.2 What is currently demonstrably executable

The reconstructed baseline prototype builds successfully with future contracts disabled. Its original baseline test passes:

```text
1/1 tests passed
```

The currently available synthetic Rasi-shaped benchmark also runs. On the packaging validation run it reported:

```text
expanded_rules=9401
compiled_families=1
collapsed_rules=9401
dependency_features=2
backend=2
compile_seconds=0.006306
events=1000000
initiations=341
hops=999659
terminations=0
null_events=0
simulation_seconds=0.159965
events_per_second=6251359.827046
```

This is a **synthetic NFnext microbenchmark**, not a speed comparison against legacy NFsim and not proof of real Rasi XML parity. The important architectural result is that 9,401 structurally repeated position-specific rules were represented as **one parameterized family**, eliminating the expanded rule count from the execution representation.

## 1.3 What the large testing tranche contains

The future-contract suite contains:

- **19 architecture-specific C++ contract files**
- **424 future contract cases**
- **3 meta-tests**
- **3,790 physical lines of C/C++ test code** in the packaged testing tree at the time the suite was created
- current meta-test measurement of **3,328 logical/non-comment test LOC** versus **1,138 production LOC**, or **2.924× test-to-production LOC**
- a hard meta-test floor of **1.5×**, matching the user requirement

The 19 architecture areas are:

1. Canonical NFIR and deterministic semantic fingerprints
2. Semantic rule-family detection and exact collapse/expand equivalence
3. Mutation-to-dependency DAG and hierarchical/adaptive scheduler
4. Arbitrary graph pattern matching, topology, symmetry and molecularity
5. Atomic transformations and exact product mapping
6. Sparse interval genome and production lattice backend
7. Exact population backend and particle/population hybrid backend
8. Incremental observables and compiled function VM
9. Strict NFsim/BioNetGen XML → NFIR lowering
10. Persistent cache invalidation, corruption detection and atomic replacement
11. Counter RNG, replay, checkpointing and schedule-independent concurrency
12. Legacy NFsim ↔ NFnext differential oracle
13. Compartments, DOR, energy, time-dependent and observable-dependent rate laws
14. Backend equivalence and exact fallback semantics
15. Generational IDs, SoA arena and allocation-free hot-loop invariants
16. Startup/runtime/memory asymptotic scaling contracts
17. Fuzzing, shrinking and metamorphic semantic validation
18. Optional native codegen/SIMD/GPU equivalence contracts
19. Rasi/uORF/whole-genome translation-specific gates

These tests are intentionally **opt-in and RED**. They are executable specifications for the rewrite, not fake-green stubs.

---

# 2. Original optimization context: why a rewrite became attractive

Before NFnext, the existing NFsim branch had already received substantial targeted optimization for Rasi/uORF-style models. That work demonstrated two things simultaneously:

1. The old engine has considerable headroom when carefully optimized.
2. Some remaining scaling costs are structural rather than local implementation inefficiencies.

The optimized legacy line achieved large improvements on the known Rasi/uORF fixtures. Prior validated project results included:

- Rasi/uORF membership-filter and matching optimizations with fixed-seed parity.
- Rasi synthetic/real fixture event throughput improvements reported in earlier validation as roughly:
  - Rasi sim 2: ~47.4×
  - Rasi sim 4: ~134.6×
  - Rasi sim 8: ~233.8×
  - uORF sim 30: ~53.1×
  - uORF sim 200: ~171.3×
- Startup/model construction reduction from approximately:
  - `prepareForSimulation`: ~10.73 s → ~0.03 s
  - total startup: ~12.1 s → ~1.81 s
- Rasi peak RSS reduction from approximately:
  - ~1.686 GB → ~125 MB
  - ~13.5× lower memory
- A DirectSelector block-size optimization around 128 entries that gave approximately another 5% net improvement while preserving RNG behavior.
- An adaptive membership-filter activation threshold around 16 registrations/type to avoid slowing tiny models.
- Paged/lazy mapping storage replacing very dense per-molecule mapping structures.
- Strong fixed-seed differential checks, including known Rasi-500 parity gates.

Those changes are valuable and should not be discarded. They are also important because the optimized branch is the best available correctness and performance oracle for NFnext.

However, the legacy architecture still fundamentally creates and manages a large object graph reflecting expanded rules and match structures. For a model where `elongate_1`, `elongate_2`, ..., `elongate_50000` are semantically the same local transition shifted along a coordinate axis, the best asymptotic representation is not “50,000 very cheap reaction objects.” The best representation is “one elongation family plus compact per-coordinate state/rates.”

That observation is the central motivation for NFnext.

---

# 3. Clean-slate architectural thesis

The rewrite proposal can be summarized in one sentence:

> **Turn NFsim from primarily a runtime object interpreter into a compiler from rule-based model semantics to specialized execution representations.**

The intended pipeline is:

```text
BNGL / NFsim XML
        ↓
strict semantic parser / legacy adapter
        ↓
canonical NFIR
        ↓
static semantic analysis
        ↓
rule-family collapse + dependency compilation + backend selection
        ↓
immutable CompiledModel
        ↓
┌───────────────────────────────────────────────────────┐
│ generic graph │ lattice/interval │ population │ hybrid│
└───────────────────────────────────────────────────────┘
        ↓
exact SSA / specialized event kernels
```

The goal is not to compromise NFsim semantics for speed. The goal is to preserve exact semantics while removing dimensions of representation that are artifacts of the input encoding.

## 3.1 Core scaling principle

Classic optimized NFsim:

```text
N expanded rules
   → sparse candidate filtering
   → optimized matching
   → propensity maintenance
   → event
```

NFnext for a regular translational family:

```text
N position-expanded rules
   → one semantic indexed family
   → sparse local coordinate kernel
   → local propensity repair
   → event
```

A ribosome hop from coordinate `i` to `i+1` should change only local occupancy and a bounded neighborhood of eligibility/propensities. Runtime work should not scale with the total number of genomic positions or expanded rule instances.

---

# 4. The initial executable NFnext prototype

The initial prototype was deliberately additive. It was designed to sit beside the old NFsim engine rather than replacing it prematurely.

## 4.1 NFIR

A compact intermediate representation was introduced for:

- molecule types
- sites/states
- primitive predicates
- primitive actions
- expanded rules
- rule families
- dependency indices
- backend hints
- model fingerprints

The long-term purpose of NFIR is to make NFsim semantics explicit and serializable, decoupling parsing/semantic interpretation from execution.

## 4.2 Rule-family collapse

The prototype recognizes conservative indexed rule sequences whose structural shape is identical after coordinate normalization. A sequence such as:

```text
elongate_1
elongate_2
...
elongate_9401
```

can be represented by one `RuleFamilyIR` with indexed data rather than 9,401 independently scheduled runtime rule objects.

The implementation was intentionally conservative: unsafe or structurally different rules should remain expanded rather than being incorrectly collapsed.

## 4.3 Dependency indexing

Primitive model features are mapped to affected rule-family IDs so local state changes can update only semantically dependent propensities. This carries forward the dependency-aware ideas that proved useful in the optimized legacy branch, but applies them at the compiled-family level.

## 4.4 Backend classification

The initial prototype provides a contract for selecting among:

- `Reference`
- `Generic`
- `Lattice`

The lattice compatibility test is conservative. A model should fall back to a more generic representation whenever the specialized backend cannot prove semantic support.

## 4.5 Generational particle identity

The new engine core avoids pointer identity as the semantic particle handle. Instead it uses compact integer handles with generations. This allows arena slot reuse while reliably detecting stale IDs.

This is important for:

- compact storage
- serialization/checkpointing
- cache-friendly arrays
- safe parallel/batch handling
- eventual accelerator representations

## 4.6 Structure-of-arrays storage

Hot fields such as type, coordinate, generation and liveness are stored in contiguous arrays. This is intended to replace the very pointer-heavy/heap-heavy access patterns of a traditional object graph for the hot simulation path.

The future tests further require no allocations in critical inner loops after reserve/warm-up.

## 4.7 Native lattice backend

The prototype includes a coordinate occupancy representation and kernels for:

- initiation
- elongation/hopping
- termination
- finite particle footprints
- local eligibility/propensity repair

The intended future representation is sparse enough that a billion-coordinate model with sparse activity should consume memory proportional to active state/interval boundaries, not to genome length.

## 4.8 Hierarchical scheduler

A Fenwick-tree weighted selector is included. The direction is toward hierarchical scheduling:

```text
family → channel/coordinate → concrete event
```

with local `O(log N)` updates or better specialized repairs rather than rescanning all events.

## 4.9 Counter-based RNG

Randomness is keyed from values such as:

- seed
- trajectory ID
- event counter
- stream/subcounter

The intended benefit is deterministic reproducibility independent of thread scheduling. This becomes especially useful when simulating many independent trajectories in parallel.

## 4.10 Deterministic batched trajectories

The prototype includes threaded trajectory execution with deterministic trajectory identity. The project has consistently favored independent-trajectory CPU parallelism before attempting a full GPU-native simulator because this is simple, exact, and already scales well on ordinary multicore hardware.

## 4.11 Binary cache foundation

The prototype includes an NFIR cache/fingerprint foundation. The complete future contract requires stronger invalidation guarantees including source hash, parser/compiler version, options, ABI/format version, corruption detection, deterministic bytes and atomic replacement.

---

# 5. Test-first expansion that followed

After the initial architecture prototype, the user explicitly requested a strict test-first process and substantially more testing code than implementation code. Several TDD cycles were performed in the conversation before the later “test everything possible” tranche.

There is an important preservation caveat explained in Section 12: **the later implementation source files from those cycles are no longer present in the active filesystem tree**. The test files and conversation-derived record remain, but the current normal source tree is the reconstructed initial prototype. Therefore this handoff records what those cycles implemented and validated at the time, but does not falsely mark those features as currently revalidated against the reconstructed source.

## 5.1 Semantic validation / XML / differential TDD cycle

A large test file (`test_semantic_validation.cpp`) was written first. It originally contained roughly 1,000 lines and dozens of semantic checks. The initial compile intentionally failed due missing APIs, establishing RED before implementation.

The implementation performed in that cycle added or targeted:

### Model validation

Checks included concepts such as:

- duplicate molecule type IDs
- duplicate molecule type names
- duplicate site names
- duplicate pattern node IDs
- dangling bond nodes
- illegal site references
- illegal state references
- predicate/action node references
- molecule type mismatches
- symmetry class mismatches
- invalid initial-particle references
- initial bond errors
- multiple use of the same site in incompatible bonds
- duplicate rule IDs
- duplicate family IDs

### Generic state safety

State-setting was strengthened to reject out-of-range site states.

A deterministic generic-state fingerprint was introduced/planned so differential snapshots could compare exact semantic state rather than pointers/addresses.

### Atomic transformations

A correctness-first strategy was implemented in that cycle by applying transformations to a trial copy and committing only if the complete transformation succeeded. That is not the eventual performance design, but it is a useful reference semantic implementation because it guarantees all-or-nothing mutation.

Primitive actions covered during that phase included:

- set state
- bind
- unbind
- create
- destroy
- rejecting unsupported coordinate movement in the generic backend

The eventual optimized generic backend should replace whole-state copying with preflight validation and a compact undo/commit strategy, while retaining the same atomic behavior.

### Differential snapshots

A trajectory snapshot/differential harness was introduced conceptually and in the lost later source to compare:

- event counts
- time
- exhaustion condition
- state fingerprint
- observables
- event trace

The long-term requirement is a much stronger legacy-NFsim ↔ NFnext oracle described below.

### Strict XML import

A libxml2-based strict importer was created during that TDD cycle. It was designed to parse XML namespace-insensitively by local element name and support a useful initial subset:

- model ID
- constant parameters
- molecule types/components/states
- initial species
- particle multiplicity
- initial bonds
- reactant patterns
- site-state predicates
- free/bound predicates
- elementary mass-action rates
- state changes
- add bond
- delete bond
- observables

The design principle was **strict diagnostics instead of semantic guessing**.

### Cache hardening

The later TDD implementation also strengthened cache fingerprints, deterministic dependency serialization and trailing-byte rejection.

Again: these source additions were reported and validated during the TDD session but are not present as normal production source files in the current reconstructed tree.

## 5.2 Invariant TDD cycle

A separate invariant suite tested:

- duplicate rule/family IDs
- duplicate type/site names
- one-bond-per-site constraints
- intramolecular bond handling
- complex splitting after unbind/destroy
- family-collapse safety when topology or symmetry differs
- reactant molecularity
- initial population-like semantics
- deterministic cache bytes regardless of unordered insertion order
- corruption detection

One particularly important semantic finding was that separate reactant patterns imply different-complex constraints in XML lowering. That distinction is easy to lose in a generic graph matcher and must remain an explicit future contract.

## 5.3 Real NFsim `<Add>` / `<Delete>` semantics cycle

The optimized branch parser source was inspected to avoid inventing XML semantics.

The relevant legacy behaviors included:

- `<Add id="...">` for product creation
- `<Delete id="..." DeleteMolecules="...">`
- `DeleteMolecules=1` on a molecule corresponds to direct molecule deletion
- whole-reactant-pattern deletion with `DeleteMolecules=0` corresponds to complete-species/complex removal
- some molecule-level conditional-delete forms are rejected or have legacy-special behavior and should not be casually generalized
- AddBond may target newly created product molecules

Tests were written first, then a `DestroyComplex`-style primitive action and connected-component enumeration were introduced in the later implementation.

The XML lowering work also handled product molecule creation, initial product states and newly created product site IDs.

## 5.4 `stateSet` XML extension cycle

The optimized branch contains a `stateSet` extension relevant to compact generated Rasi models. Tests were written first for:

- legal state sets
- state + stateSet conflict
- empty sets
- empty entries
- duplicate values
- unknown states
- symmetric-site restrictions where applicable

A finite-set site-state predicate was then added in the later TDD implementation. Matchers, validator, fingerprinting, cache serialization, rule-family shape and dependency compilation all had to include the state set; otherwise a seemingly minor parser feature would silently break compilation equivalence.

## 5.5 Multi-pattern observable semantics cycle

Legacy NFsim behavior was inspected to determine whether multiple observable patterns are unioned or summed. The relevant behavior is additive: each template can contribute independently, including overlapping terms.

Tests were written before adding an `ObservableTermIR` representation in the later implementation. The intended semantics are:

- **Embeddings**: sum independent match counts
- **Molecules**: unique anchors within each term, then sum terms
- **Complexes/Species**: unique complex keys within each term, then sum terms
- overlap across distinct terms is counted separately, matching legacy behavior

## 5.6 Randomized independent-oracle validation

A randomized oracle suite was written to avoid simply testing one implementation against itself. At the time it was run it reported:

```text
11 test groups
171,446 checks
0 failures
```

It covered concepts such as:

- single-node predicates versus an independently written oracle
- two-node bonded patterns versus brute-force enumeration
- molecularity versus a separate oracle
- symmetry count checks such as `n choose 2`
- randomized Fenwick updates/prefixes versus a plain vector
- Fenwick lower-bound selection versus linear scanning
- lattice hop eligibility versus brute occupancy checks
- lattice total propensity versus eligible-head count × rate
- repeated lattice hops preserving occupancy/propensity invariants
- initiation/termination predicates
- selected hops always being eligible
- multiple random-seed lattice runs with zero null events and consistent event accounting

This style of independent oracle is strongly recommended for every future subsystem.

## 5.7 Population backend TDD cycle — interrupted/incomplete

A substantial population-backend test suite was written before implementation. It covered approximately 33 cases including:

- count initialization
- unknown types
- set/add/remove
- underflow atomicity
- duplicate initial populations
- particle/population storage firewalls
- unary propensity
- A+B propensity
- exact `2A` combinatorics (`C(n,2)`)
- exact `3A` combinatorics
- insufficient counts
- source reactions
- unsupported rate laws
- decay/conversion firing
- failed-fire atomicity
- duplicate stoichiometric term normalization
- deterministic traces
- trajectory stream separation
- maximum-time behavior
- invalid population rule IDs/rates/stoichiometry
- fingerprint/cache storage

Population source scaffolding was started during that cycle, but the cycle was **not completed and not revalidated** before the later filesystem reconstruction. Do not treat population execution as currently green.

---

# 6. The comprehensive future-contract suite

The most recent instruction was to “make as much testing code as possible for all proposed improvements.” Rather than making missing features compile through placeholder stubs, the suite is intentionally structured as an **opt-in RED specification**.

Normal development/CI can keep the future contracts off. During subsystem implementation, one target is enabled and driven from RED to green.

## 6.1 Canonical NFIR contracts

These tests specify that NFIR must be a true semantic canonical form rather than merely parser output.

They cover requirements such as:

- deterministic ordering independent of input map iteration
- canonical IDs
- semantically equivalent models producing identical canonical fingerprints
- semantically different models producing different fingerprints
- stable representation of predicates/actions/rules/families
- validation before compilation
- exact round-trip expectations
- canonicalization not depending on pointer values or process address layout

Why this matters: persistent caching, cross-backend equivalence, differential debugging, reproducible compilation and minimized fuzz failures all depend on a stable semantic representation.

## 6.2 Rule-family contracts

These tests make rule-family collapse prove its safety rather than infer it from names.

They cover:

- same structural rule translated along an index axis
- varying rates as compact indexed data
- nonconsecutive indexes
- unsafe differences in topology
- unsafe differences in predicates
- unsafe differences in transformations
- symmetry-sensitive rules
- collapse→expand semantic equality
- randomized families checked against independently expanded forms
- stable original ordering where RNG/event ordering semantics require it

A major design rule is: **if the compiler cannot prove equivalence, do not collapse**.

## 6.3 Dependency DAG and scheduler contracts

These tests specify:

- exact mutation-feature → affected-rule/family dependencies
- no false negatives in dependency repair
- bounded/local update sets for local lattice changes
- hierarchical family/channel propensity composition
- weighted event selection versus a linear reference oracle
- dynamic propensity updates
- zero-propensity handling
- stable deterministic selection under fixed random draws

This generalizes lessons from the optimized membership-filter branch: sparse candidate filtering is only safe when false negatives are impossible.

## 6.4 Arbitrary generic graph matcher contracts

The specialized lattice backend cannot cover all BNGL semantics, so the generic backend must remain exact.

Contracts cover:

- arbitrary connected graph patterns
- state predicates
- free/bound predicates
- explicit bond topology
- cycles
- disconnected reactants
- molecularity constraints
- symmetry classes
- automorphism handling
- no double counting from symmetric embeddings
- intracomplex versus intercomplex matches
- overlapping matches
- local/global predicate behavior
- deterministic enumeration/canonical match keys where required

The generic matcher should become the correctness anchor for specialized backend equivalence tests.

## 6.5 Transformation contracts

These tests specify exact and atomic semantics for:

- site-state changes
- binding
- unbinding
- molecule creation
- molecule destruction
- whole-complex destruction
- product mapping
- complex merge
- complex split
- multiple transformations in one event
- invalid-late-action rollback
- stale-handle protection
- newly created molecule references
- no partial mutations after failed preflight

The correctness-first trial-copy approach from the TDD cycle is acceptable as a reference implementation but not as the final hot-path design.

## 6.6 Sparse interval/lattice genome contracts

These tests are central to the genome-scale objective.

They specify:

- 64-bit coordinates
- sparse occupancy
- billion-coordinate spaces without billion-entry allocation
- finite particle footprint exclusion
- legal initiation
- legal elongation
- legal termination
- collision conditions
- local neighborhood repair
- dense-reference versus sparse-lattice equivalence on small random systems
- memory scaling proportional to active state rather than coordinate domain
- no full-genome propensity rebuild after a local event
- no null-event dependence for ordinary local hops

The intended representation may eventually use sparse ordered structures, chunked occupancy, run/interval encoding, or specialized arrays depending on density. The tests define semantics/scaling, not the one mandatory data structure.

## 6.7 Population and particle/population hybrid contracts

NFsim already has concepts that motivate population-like representations, and genome-scale models may contain species better represented as counts than explicit particles.

Contracts specify:

- exact integer population counts
- exact mass-action combinatorics (`C(n,k)` for repeated reactants)
- source/decay/conversion reactions
- atomic count mutation
- particle-vs-population storage firewall
- hybrid events that consume/produce both representations
- deterministic propensity accounting
- exact backend fallback when a hybrid rule cannot use a specialized kernel

No approximate tau-leaping behavior is implied by these tests; the initial target remains exact stochastic simulation.

## 6.8 Observables and compiled function contracts

The final engine should not rescan the entire world after every event if an observable depends only on local mutations.

Contracts cover:

- molecule observables
- species/complex observables
- embeddings
- multi-pattern additive semantics
- incremental observable repair
- reference full-rescan equivalence
- compiled arithmetic/logical function evaluation
- parameter dependencies
- observable-dependent functions
- time-dependent functions
- deterministic function bytecode/IR
- correct invalidation when source observables change

The long-term design is a small safe compiled function VM or equivalent expression evaluator whose dependencies are statically known.

## 6.9 Strict XML adapter contracts

The XML adapter is one of the highest-risk semantic layers because silently guessing unsupported NFsim constructs could produce plausible but wrong simulation results.

Contracts cover:

- streaming parsing versus DOM/reference equivalence
- model/types/sites/states
- initial particles/bonds
- reactant/product patterns
- `stateSet`
- `<Add>`
- `<Delete>` and `DeleteMolecules`
- AddBond/DeleteBond
- rate law variants
- observables
- functions
- compartments
- local/global functions where semantically supportable
- malformed references
- duplicate IDs/names
- unsupported constructs producing explicit diagnostics
- partial-support parser rejecting rather than approximating

The eventual best integration path may be a direct adapter from existing NFsim parsed runtime structures into NFIR first, followed by a native XML compiler. That reduces semantic duplication during migration.

## 6.10 Cache contracts

Persistent compiled-model caching is potentially a major startup win, but stale caches are unacceptable.

Contracts specify:

- deterministic cache bytes
- source-model hash
- canonical semantic fingerprint
- parser version
- compiler version
- NFIR format version
- ABI/options compatibility
- trailing byte rejection
- corruption detection
- truncated file rejection
- atomic write/replace behavior
- crash/fault safety
- deterministic dependency ordering
- safe migration/rejection across format versions
- resource-budget defenses against malformed lengths

The cache should be considered an optimization only; deleting it must never change semantics.

## 6.11 RNG, checkpoint, replay and concurrency contracts

Contracts specify:

- deterministic counter RNG vectors
- independent trajectory streams
- no dependence on worker scheduling
- serial vs parallel identity for a trajectory ID
- reproducible checkpoint/restart
- event counter preservation
- deterministic replay
- thread-count invariance
- no shared mutable compiled-model state

The ultimate objective is to make many-trajectory simulation naturally parallel while retaining exact reproducibility.

## 6.12 Legacy differential oracle contracts

This is the gate that should prevent a rewrite from silently drifting away from NFsim semantics.

The future runner should be able to compare legacy NFsim and NFnext at fixed seeds and progressively stronger levels:

1. model/NFIR structural audit
2. initial state fingerprint
3. initial observables
4. initial rule/family propensities
5. selected event identity or normalized semantic event identity
6. post-event state
7. post-event observables
8. repeated per-event trajectory trace
9. terminal output/hash where byte-compatible output is expected

The suite also asks for useful mismatch diagnostics and reduced/minimized failing models so semantic drift can be localized rather than only reported as a final hash mismatch.

## 6.13 Compartments and advanced rate laws

Contracts were written for features the prototype does not yet cover, including:

- compartments
- volume/compartment-dependent scaling
- DOR-style behavior
- energy-based rules
- time-dependent rates
- observable-dependent rates
- local/global functions
- exact dependency invalidation for those rate laws

These are deliberately later-phase features. They should not block making Rasi translation work, but they are required before claiming arbitrary BNGL/NFsim compatibility.

## 6.14 Backend equivalence

A specialized backend is only acceptable if it agrees with the reference semantics on their common domain.

Contracts cover combinations such as:

- generic versus reference
- lattice versus generic/reference on representable models
- population versus generic/reference for count-equivalent systems
- hybrid versus reference
- fallback when a specialized backend does not support a rule
- equivalent propensity totals and state trajectories under controlled random draws

This allows optimized kernels to be aggressive internally while keeping a strong semantic boundary.

## 6.15 Memory arena and allocation contracts

Contracts specify:

- generational IDs
- stale-handle rejection after reuse
- deterministic slot behavior where required
- structure-of-arrays invariants
- compact site/bond fields
- reserve/warm-up behavior
- no per-event heap allocation in declared hot loops
- bounded temporary storage
- safe growth/reallocation outside hot regions

These tests exist because some of the legacy NFsim memory problems were caused by enormous counts of small bookkeeping structures rather than large biological state itself.

## 6.16 Scaling stress contracts

Performance tests should verify asymptotic behavior, not merely one favorable benchmark.

Contracts target:

- startup versus number of expanded rules
- family collapse reducing runtime representation count
- local event cost versus genome length
- memory versus sparse active state
- scheduler update complexity
- increasing coordinate domain without proportional memory
- multiple trajectories sharing one immutable compiled model
- no accidental reintroduction of `O(number of rules)` per-event work

Exact time thresholds should remain hardware-aware, but scaling slopes and operation counts can often be tested deterministically.

## 6.17 Fuzzing, shrinking and metamorphic tests

This suite is designed to catch semantic bugs that hand-written examples miss.

Examples include:

- randomized small models checked against a brute/reference engine
- randomized rule family collapse→expand equivalence
- randomized matcher enumeration
- randomized scheduler selection versus linear oracle
- model transformations that should preserve semantics
- renaming IDs without changing behavior
- permuting declaration order without changing canonical semantics
- adding unreachable rules without affecting trajectories
- shrinking failing random models to minimal reproductions

Long-term CI should include deterministic fixed-seed fuzz corpora and a slower nightly randomized run.

## 6.18 Native codegen / SIMD / GPU contracts

These are intentionally optional and late.

The project previously concluded that a full GPU-native NFsim rewrite should **not** be the first move. CPU specialization and independent trajectories offer better complexity/benefit initially.

Nevertheless, future contracts are included for:

- native codegen producing identical semantic results
- SIMD kernels matching scalar kernels
- accelerator kernels matching CPU reference
- unsupported cases falling back safely
- deterministic result handling where required
- no separate accelerator semantics

The purpose of writing these tests now is to prevent a later performance experiment from becoming an untestable parallel implementation.

## 6.19 Rasi/uORF-specific translation contracts

These tests encode the actual motivating workload rather than only generic abstractions.

They include requirements around:

- collapse of repeated elongation/translation rule families
- separation of collision/elongation/pretermination/endocleavage rule classes
- sparse transcript/genome state
- local candidate correctness
- local propensity repair
- exact occupancy semantics
- fixed-seed differential gates
- known Rasi-500 event/hash fixtures where available
- uORF fixture event gates
- whole-genome coordinate scaling
- maintaining semantics while avoiding explicit empty-coordinate objects

One known Rasi-500 oracle from previous validated work is retained in the project context:

```text
seed 424242
sim horizon 4
3,489 reactions/events in the known gate
SHA-256:
a1e661a995a80f5ec65267d0c907d637e30f137d6dad4eb47dcf959717921011
```

This should be treated as a strong regression gate once a real legacy XML→NFIR adapter and exact output bridge are wired up.

---

# 7. Meta-tests and testing discipline

The test corpus includes three meta-tests because test coverage itself is a project requirement.

## 7.1 Test/implementation LOC budget

`test_test_budget.py` calculates logical/non-comment production and testing LOC and fails if the ratio drops below the configured threshold.

Current packaging validation:

```text
production_loc=1138
test_loc=3328
test_to_production_ratio=2.924
required_ratio=1.500
```

This is intentionally stricter than simply counting test cases; it discourages implementation tranches that grow large without corresponding semantic contracts.

## 7.2 Contract coverage

`test_contract_coverage.py` counts explicit future-contract cases by architecture file.

Current validation:

```text
test_nfir_canonicalization_contract.cpp: 22
test_rule_family_contract.cpp: 16
test_dependency_scheduler_contract.cpp: 15
test_generic_matcher_contract.cpp: 20
test_transformations_contract.cpp: 20
test_lattice_interval_contract.cpp: 20
test_population_hybrid_contract.cpp: 19
test_observable_function_contract.cpp: 22
test_xml_adapter_contract.cpp: 37
test_cache_contract.cpp: 27
test_rng_replay_concurrency_contract.cpp: 25
test_differential_oracle_contract.cpp: 23
test_compartment_rate_contract.cpp: 24
test_backend_equivalence_contract.cpp: 22
test_memory_arena_contract.cpp: 21
test_scaling_stress_contract.cpp: 22
test_fuzz_metamorphic_contract.cpp: 24
test_codegen_accelerator_contract.cpp: 19
test_rasi_translation_contract.cpp: 26
total_future_contract_cases=424
```

## 7.3 No silent skips

`test_no_silent_skip.py` prevents the future-contract files from quietly hiding unsupported behavior behind skip markers. Missing functionality should remain visibly RED until implemented.

---

# 8. How the future-contract suite is intended to be used

Normal build:

```bash
cmake -S nextgen -B build \
  -DNFNEXT_BUILD_FUTURE_CONTRACT_TESTS=OFF
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Contract/TDD mode:

```bash
cmake -S nextgen -B build-contract \
  -DNFNEXT_BUILD_TESTS=OFF \
  -DNFNEXT_BUILD_BENCHMARKS=OFF \
  -DNFNEXT_BUILD_FUTURE_CONTRACT_TESTS=ON
```

Then build one subsystem at a time, for example:

```bash
cmake --build build-contract \
  --target test_nfir_canonicalization_contract -j
```

The intended workflow is:

```text
choose one contract subsystem
        ↓
build it and observe RED
        ↓
implement the smallest semantically correct API
        ↓
make the subsystem green
        ↓
run baseline + randomized oracle + sanitizers
        ↓
run related differential gates
        ↓
move to the next contract
```

Do **not** add placeholders that satisfy compilation while bypassing semantics. A compile-time `#error` naming the missing API is preferable to a fake implementation that turns tests superficially green.

---

# 9. What is NOT done yet

This section is intentionally explicit. The project should not be described as a finished NFsim rewrite.

## 9.1 No complete direct adapter from the optimized NFsim runtime to NFIR

This is the most important missing integration piece.

The current prototype does not take arbitrary existing NFsim parser/runtime objects (`System`, `ReactionClass`, `TemplateMolecule`, `TransformationSet`, observables, functions, compartments, etc.) and losslessly compile them into NFIR.

**Why not done yet:** the project first established the target architecture and semantic tests. A direct adapter is substantial and must be differential-tested against the legacy engine; guessing it without enough tests would create a large semantic risk.

**Recommended approach:** implement the adapter before attempting to replace the full XML parser. Reuse the existing optimized NFsim parser as the source of truth, emit NFIR from its already-resolved semantic structures, and compare both engines event by event.

## 9.2 No fully general arbitrary-complex matcher in the current reconstructed source

The initial executable generic matcher/state is intentionally limited compared with full NFsim matching semantics.

Missing/generalized areas include:

- arbitrary connected-pattern embeddings
- full automorphism/symmetry treatment
- all molecularity constraints
- all connectivity conditions
- local functions
- DOR/Energy-specific semantics
- RuleMonkey-like or unusual rule forms if present

**Why not done yet:** this is one of the hardest correctness components and should be implemented against a brute-force/reference matcher using the large contract suite.

## 9.3 No complete transformation lowering

The lost later TDD implementation covered an initial subset, but the current reconstructed production source is not a complete transformation compiler.

**Why not done yet:** exact product mapping, component symmetry, molecule deletion and complex deletion are subtle and require full legacy semantic inspection.

## 9.4 No complete observables/functions compiler

The future tests specify the behavior, but the current reconstructed production source does not provide the complete incremental observable/function VM architecture.

**Why not done yet:** correct dependency tracking must be established first; otherwise incremental updates can easily miss invalidations.

## 9.5 No real Rasi/uORF XML → NFnext parity run in the current reconstructed tree

The synthetic 9,401-rule benchmark demonstrates representation collapse and lattice throughput. It does **not** establish real model parity.

**Why not done yet:** the missing legacy adapter/full parser bridge prevents compiling the real Rasi/uORF semantic model into NFIR with complete confidence.

## 9.6 No full persistent compiled-model cache contract implemented

The initial binary cache foundation exists, but complete cache keying/invalidation, atomic replacement and all corruption defenses remain future work.

**Why not done yet:** the canonical NFIR/parser/compiler contract should stabilize before locking a durable on-disk format.

## 9.7 No hybrid scheduler spanning all generic/lattice/population backends

Each specialized representation needs a common exact event-selection layer and dependency repair mechanism.

**Why not done yet:** population/hybrid semantics were only beginning when that TDD cycle was interrupted.

## 9.8 No complete population backend currently validated

Tests exist. Partial later source was started but is not preserved in the current production tree and was not fully green before interruption.

**Why not done yet:** the previous implementation cycle ended before cache/fingerprint/validation integration and before a complete build/test pass.

## 9.9 No native codegen/SIMD/GPU implementation

Contracts exist only.

**Why not done yet:** deliberate prioritization. Earlier feasibility work showed CPU optimization plus independent trajectory parallelism is already highly effective. A GPU-native port would add enormous semantic and maintenance complexity before the compact CPU architecture is stable.

## 9.10 No proof of arbitrary BNGL replacement

The project cannot yet claim “NFnext replaces NFsim.”

A replacement claim requires at minimum:

- lossless adapter/parser coverage
- full generic matcher
- complete transformations
- observables/functions
- compartments/rate laws
- extensive legacy differential corpus
- Rasi/uORF parity
- ordinary NFsim regression suite parity
- robust cache/replay behavior

---

# 10. Why some work could not be completed/preserved

## 10.1 GitHub clone/network limitation

During the original executable-prototype session, the ordinary VM/container network namespace could not resolve `github.com`, so a literal `git clone` of the target branch was not possible.

Repository inspection was performed through the authenticated GitHub connector instead, and the work was packaged as an **additive patch** intended to be applied to a real checkout.

This is why the archive contains `HISTORICAL_nfnext_additive.patch` and the `apply_nfnext.sh` helper rather than a complete `.git` checkout.

## 10.2 Loss of later implementation source from the active filesystem

The subsequent TDD cycles created additional implementation files/APIs for validation, XML import, differential snapshots, finite state sets, observable terms and partial population support. Those files were reported and tested during the conversation.

By the time the comprehensive future-contract packaging work began, the active `/mnt/data/nfsim-nextgen-prototype` directory had lost most implementation files and retained mainly test additions plus the older additive patch. The executable source was therefore reconstructed from the original prototype ZIP into `/mnt/data/nfsim-nextgen-work`, and the newer test corpus was preserved on top of it.

Consequences:

- The current archive contains the **initial executable production implementation**.
- It contains the **newer tests**, including files that refer to APIs not present in that reconstructed production implementation.
- It contains this detailed record of the later TDD implementation behavior.
- It does **not** claim the lost implementation sources were magically reconstructed exactly from memory.
- The future-contract mode remains deliberately RED.

This is a major reason the archive includes the original standalone ZIP, the extracted initial reference snapshot, surviving sparse directories, and both patches: preserve every recoverable artifact rather than flattening history into one misleading tree.

---

# 11. What the two patches mean

## 11.1 `PATCHES/HISTORICAL_nfnext_additive.patch`

This is the original additive NFnext prototype patch.

Its purpose is to add the initial `nextgen/` implementation beside a real NFsim checkout while leaving the default legacy build unchanged.

Use this patch when starting from the actual optimized NFsim repository branch and you want to recreate the initial NFnext prototype integration.

Because this patch predates the broad future-contract tranche, it should be considered a historical integration base, not the final current test state.

## 11.2 `PATCHES/CURRENT_vs_INITIAL_EXECUTABLE_PROTOTYPE.patch`

This patch was freshly generated during this packaging step. It is approximately 4,005 lines and compares:

```text
REFERENCE_SNAPSHOTS/initial_executable_prototype
```

against the current reconstructed working source/tests/docs/tools in:

```text
CURRENT_WORK/
```

Its primary content is the later testing/contracts tranche and related CMake/test wiring.

Use this patch **after** recreating the initial executable prototype if you want to reproduce the current reconstructed working state.

The two-patch conceptual sequence is therefore:

```text
optimized NFsim checkout
    + HISTORICAL_nfnext_additive.patch
        = initial executable NFnext prototype
    + CURRENT_vs_INITIAL_EXECUTABLE_PROTOTYPE.patch
        = current reconstructed prototype + large contract suite
```

Because file paths in a raw `diff -ruN` patch contain snapshot paths, inspect/normalize prefixes when applying manually. The complete `CURRENT_WORK/` snapshot is included specifically so recovery does not depend solely on patch-prefix handling.

---

# 12. Current validation evidence

Validation performed while creating this complete archive:

## 12.1 Baseline executable test

```text
Test project: reconstructed current work
nfnext_tests: PASS
1/1 tests passed
```

This only proves the initial executable baseline target remains intact with future-contract tests disabled.

## 12.2 Meta-test coverage

```text
19 future architecture files
424 future contract cases
no silent skip markers
```

## 12.3 Test-code ratio

```text
production_loc=1138
test_loc=3328
ratio=2.924×
minimum=1.500×
PASS
```

## 12.4 Synthetic Rasi-shaped benchmark

Packaging run:

```text
expanded_rules=9401
compiled_families=1
collapsed_rules=9401
dependency_features=2
backend=2
compile_seconds=0.006306
events=1000000
initiations=341
hops=999659
terminations=0
null_events=0
simulation_seconds=0.159965
events_per_second=6251359.827046
```

This benchmark is useful for sanity/scaling development but must **not** be presented as a validated speedup over the existing NFsim branch.

## 12.5 Future contracts intentionally RED

When future contracts are enabled, missing architecture APIs are expected to fail compilation with explicit RED-contract messages. This is the desired TDD state.

---

# 13. Recommended implementation order from here

The best next work is not “make all RED tests compile at once.” Implement semantic layers in dependency order.

## Phase 1 — Canonical semantic foundation

1. Reintroduce/implement robust NFIR validation.
2. Implement canonicalization and stable semantic fingerprinting.
3. Make `test_nfir_canonicalization_contract` green.
4. Run meta-tests and baseline regression.
5. Add ASAN/UBSAN.

Reason: every later subsystem, cache, fuzz shrinker and differential runner benefits from canonical model identity.

## Phase 2 — Direct legacy NFsim → NFIR adapter

1. Use the optimized NFsim parser/runtime as the semantic source of truth.
2. Convert molecule types/sites/states.
3. Convert initial state.
4. Convert reactant/product patterns.
5. Convert transformations.
6. Convert rates/functions/observables incrementally.
7. Reject unsupported constructs explicitly.
8. Produce semantic audit dumps for both sides.

This is more valuable than immediately writing another standalone XML parser because it gives direct access to already-resolved NFsim semantics.

## Phase 3 — Reference generic engine

Implement correctness before performance:

1. arbitrary graph matcher
2. molecularity/connectivity
3. symmetry/automorphism handling
4. transformations
5. observables
6. functions
7. exact SSA

A slow but exact reference engine is extremely valuable. Every specialized backend can then be differential-tested against it.

## Phase 4 — Real differential oracle

Wire the existing optimized NFsim executable/runtime and the NFnext reference engine together.

Required gates:

- same parsed semantics
- same initial state/observables
- same propensity totals
- normalized event correspondence
- same post-event state
- same observable updates
- fixed-seed trajectories
- final known output hashes

Start on tiny generated models, then the existing NFsim regression corpus, then uORF/Rasi fixtures.

## Phase 5 — Semantic rule-family compiler

Once adapter/reference parity exists:

1. detect position/index parameterization from semantics rather than names
2. canonicalize shifted rule structure
3. collapse safe families
4. preserve rates/index mapping
5. prove collapse→expand equivalence
6. randomized family fuzzing
7. differential execution against expanded reference

This phase delivers the core asymptotic benefit.

## Phase 6 — Production lattice/interval backend

Implement sparse genome/transcript state:

- 64-bit coordinates
- sparse occupancy/interval representation
- local initiation/hop/termination kernels
- footprint/collision rules
- local dependency repair
- bounded event allocation
- Rasi-specific rule family lowering

Then make the lattice, scaling and Rasi contract files green.

## Phase 7 — Incremental observables/functions

Compile observable/function dependencies and update only affected values after events. Compare every incremental result to a full reference rescan in tests.

## Phase 8 — Population and hybrid backend

Finish exact population combinatorics, hybrid reactions and common scheduling. Do not add approximate methods until exact behavior is fully validated.

## Phase 9 — Persistent compiled cache

Only after NFIR/compiler semantics stabilize:

- canonical cache key
- source hash
- parser/compiler/options versions
- deterministic serialization
- corruption/truncation defenses
- atomic writes
- cache-hit startup benchmark

## Phase 10 — In-process trajectory batches

Share one immutable `CompiledModel` across many trajectories. Preserve counter-based RNG and trajectory-ID reproducibility. Measure throughput and memory versus spawning independent processes.

## Phase 11 — Native codegen / SIMD

Profile first. Compile only hot, regular kernels. Keep reference and generic fallback paths.

## Phase 12 — GPU/accelerator experiments

Only after the CPU compact representation is stable and profiling identifies a regular batch large enough to amortize transfer/launch overhead. The earlier project direction remains: do not begin with a full GPU-native NFsim port.

---

# 14. Performance goals and how to measure them correctly

NFnext should be judged on more than raw events/second.

## 14.1 Startup complexity

Measure:

- parser time
- NFIR canonicalization time
- family compilation time
- dependency compilation time
- backend compilation time
- cache hit/miss time

Plot against:

- expanded rule count
- semantic family count
- active coordinates

The desired outcome is that models with 100× more position-expanded rules but the same semantic family structure do not require 100× more compiled runtime objects.

## 14.2 Runtime event complexity

Instrument operation counts for:

- candidate/family updates
- propensity repairs
- matcher invocations
- allocations
- coordinate/index lookups

A local elongation event should not perform work proportional to total genome length or total expanded rule count.

## 14.3 Memory

Track:

- immutable compiled model
- per-trajectory state
- scheduler structures
- matcher temporary storage
- cache footprint

Desired scaling:

```text
compiled representation ~ semantic families + compact indexed data
trajectory memory ~ active particles/populations/sparse state
```

not:

```text
memory ~ genome coordinate domain × rule expansion × particle bookkeeping
```

## 14.4 Correctness before speed

Every speed benchmark should be paired with:

- exact seed
- fixture/model hash
- engine revision
- semantic mode
- output/state hash or differential result
- event count
- whether RNG sequence is intentionally identical or semantically normalized

The prior NFsim optimization effort was successful largely because speed changes were continuously gated by byte-level or event-level parity. NFnext should preserve that discipline.

---

# 15. Rasi-specific engineering observations to retain

The Rasi optimization work exposed several recurring classes of rules, including elongation, collision, pretermination and endocleavage families. Candidate filtering must distinguish them correctly; an earlier direction-aware candidate experiment produced false negatives specifically in some of these classes, demonstrating why aggressive indexing must be shadow-validated before activation.

The architecture should therefore favor explicit semantic dependency descriptions over heuristic name/direction rules.

For long transcripts/genome coordinates:

- avoid one runtime object per empty coordinate
- avoid one matcher registration per position when rules are translational copies
- avoid rebuilding global propensities after a local occupancy change
- keep footprints/collisions local
- represent sparse active positions directly
- keep exact state semantics for weird/irregular rules through the generic fallback backend

The rewrite should be optimized first for models that exhibit these regular structures, without making arbitrary BNGL models depend on those assumptions.

---

# 16. Design decisions that should NOT be reversed casually

## 16.1 Keep legacy NFsim as semantic oracle during migration

A clean rewrite without a differential oracle is too risky. The legacy engine may be architecturally awkward, but it encodes years of edge-case semantics.

## 16.2 Prefer strict rejection to silent approximation

If NFnext cannot yet represent a construct, emit a precise compiler diagnostic and use the legacy/reference backend. Do not reinterpret it into a “close enough” rule.

## 16.3 Preserve a generic exact backend

Specialized lattice/population kernels should not become the only execution semantics.

## 16.4 Collapse by semantics, not naming convention

Rule names can help discovery/debugging, but family equivalence must be established from canonical predicates/actions/topology/rates.

## 16.5 CPU first, accelerator later

The project already obtained enormous gains through CPU representation and filtering improvements. The compact compiled representation is a prerequisite for a useful accelerator backend anyway.

## 16.6 Test each asymptotic claim

If the architecture says “local update,” add a test or counter proving the update set is bounded/local. If it says “sparse billion-coordinate genome,” test memory allocation behavior at billion-scale coordinate domains.

---

# 17. Archive directory guide

## `CURRENT_WORK/`

Current reconstructed working tree:

```text
CURRENT_WORK/
├── doc/
├── nextgen/
│   ├── bench/
│   ├── include/nfnext/
│   ├── src/
│   └── tests/
│       ├── future_contract/
│       └── meta/
└── tools/
```

This is the easiest place to continue development.

## `PATCHES/`

- `HISTORICAL_nfnext_additive.patch`
- `CURRENT_vs_INITIAL_EXECUTABLE_PROTOTYPE.patch`

See Section 11 for their meanings.

## `REFERENCE_SNAPSHOTS/initial_executable_prototype/`

Exact extraction of the original initial-prototype ZIP. Use this to inspect what the fresh current patch changed.

## `SURVIVING_ARTIFACTS/`

Preservation copies of:

- original prototype ZIP
- testing-suite ZIP
- current sparse prototype artifact directory
- current standalone testing suite directory

These are intentionally somewhat redundant.

## `VALIDATION_CURRENT.txt`

Machine-captured packaging-time validation output.

## `CURRENT_WORK_FILE_INVENTORY.txt`

Sorted list of the current source/docs/tools files.

## `CHECKSUMS.sha256`

SHA-256 hashes for all archive files except the checksum file itself.

---

# 18. Immediate “next session” checklist

A future coding session can begin with this exact sequence:

1. Extract this archive.
2. Work from `CURRENT_WORK/`.
3. Configure normal mode and verify baseline test passes.
4. Run all three meta-tests.
5. Enable future contracts.
6. Pick **canonical NFIR** as the first RED target.
7. Implement it without touching unrelated contracts.
8. Run baseline + target contract + meta-tests.
9. Add sanitizer run.
10. Move to the legacy adapter.
11. Once the adapter supports a tiny model, add an event-by-event differential test immediately.
12. Keep the old optimized NFsim branch untouched as the oracle.
13. Do not claim Rasi parity until the real Rasi XML passes the known fixed-seed gates.
14. Do not claim whole-genome scalability from the synthetic 9,401-rule microbenchmark alone; run explicit sparse billion-coordinate and large-family tests.

---

# 19. Bottom line

The key accomplishment is not that NFsim has already been fully rewritten. It has not.

The project now has:

- a concrete executable prototype of the compiler-oriented architecture;
- evidence that thousands of repeated coordinate rules can collapse to one runtime family;
- compact particle/lattice/scheduler/RNG/cache foundations;
- a documented migration strategy that preserves legacy NFsim as the semantic oracle;
- extensive TDD work capturing subtle NFsim XML/observable/transformation semantics;
- randomized independent-oracle testing experience;
- and, most importantly for continued development, a **424-case future-contract suite spanning essentially every proposed subsystem**, with an enforced test-code budget and no silent skips.

The most productive next step is to use those tests to build the semantic foundation and direct legacy adapter, then establish real fixed-seed differential parity before expanding specialized execution. Once that bridge is in place, the architectural advantage—compiling repeated genomic rule expansions into parameterized local kernels—can be evaluated on the actual Rasi and uORF models rather than synthetic proxies.

Until those gates pass, treat NFnext as an ambitious, heavily specified experimental engine beside the already optimized NFsim branch—not as its replacement.
