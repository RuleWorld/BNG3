# BNG3 Energy Compiler / Generalized NFsim Runtime — Complete Context, Implementation, Validation, and Handoff

> Archived snapshot from 2026-09-07. See `docs/CURRENT_PROGRESS.md` for the
> live branch and current verification state; counts and branch names below
> are historical evidence only.

**Prepared:** 2026-09-07  
**Repository:** `RuleWorld/BNG3`  
**Primary development branch / PR:** PR #2, `codex/bng3-integration-foundations`  
**Exact source checkpoint used for all grounded integration work:** `3bc7b4ff131f8927421bc8eae170e3b248b75318`

---

## 1. Purpose of this archive

This archive is intended to be a complete handoff of the BNG3 energy-compiler work that was actually preserved as files during the development sessions, plus the much larger tests-first validation suite that was created to constrain the remainder of the redesign.

The central objective was **not** to rewrite BioNetGen yet again. The existing BNG3 branch is already the clean-sheet integration effort. The goal was to evolve that branch into an architecture that can support:

- first-class energy-based modeling without exponential context-rule materialization;
- large rule systems such as Rasi/uORF/genome-scale models;
- a canonical compiled representation shared by backends;
- safe, local free-energy-change compilation based on graph edits;
- eventually indexed/parametric rule families rather than explicitly enumerated thousands of nearly identical rules;
- repeated NFsim trajectory generation for inference workloads without recompiling the structural model each time;
- explicit thermodynamic extensions such as barriers and driven/non-equilibrium transitions, but only after compatibility and parity are proven.

This handoff also records what **was not completed**, what could not be validated in the execution environment, and which parts of the later design are represented only by tests/contracts rather than finished runtime code.

The distinction between **persisted implementation** and **planned/tested future implementation** is important. This archive does not claim more than is actually present on disk.

---

# 2. Repository and branch context

The work was grounded against the already-active BNG3 integration branch rather than against `main`.

The active branch had already made several important architectural decisions:

1. **ANTLR4 BNGL parser → C++ AST** is the canonical modern input route.
2. The preferred NFsim route is **direct AST → NFsim**, not XML.
3. XML remains an explicit compatibility/shadow-oracle path.
4. Direct construction is intended to fail closed rather than silently switch semantics.
5. BNG2/legacy Perl remains a validation oracle, not the long-term implementation substrate.
6. Embedded NFsim already contains accepted performance and energy-pattern work from a pinned standalone NFsim lineage.
7. The convergence work is governed by parity and independent-oracle expectations in the branch documentation.

At the inspected checkpoint, the branch already contained:

- `ast::EnergyPattern`;
- rich `ReactionRule::TransformOp` graph edits;
- `EnergyPatternInfo` in NFsim;
- compact binding context structures;
- `EnergyRxnClass` for a restricted compact Arrhenius binding path;
- legacy materialized Sekar-style energy expansion as fallback;
- direct AST → NFsim construction;
- substantial NFsim performance work.

Therefore the architectural recommendation became:

```text
BNGL
  ↓
ANTLR4
  ↓
ast::Model                canonical source representation
  ↓
model compiler
  ↓
CompiledModel             canonical execution representation
  ↓
 ├── network generation
 ├── NFsim
 ├── analysis / dependency inspection
 └── later cached/batched trajectory construction
```

The key missing abstraction was not another parser or simulator rewrite. It was a **compiled semantic layer** between the source AST and the execution backends.

---

# 3. Architectural objectives

## 3.1 Canonical compiled model

The proposed `CompiledModel` is meant to be immutable, execution-facing metadata derived from `ast::Model`.

The source AST answers:

> “What did the user write?”

The compiled representation should answer:

> “What does each rule change, what can that change affect, what rate-law semantics apply, and how should the backend execute it?”

This separation is particularly valuable for large models and repeated simulations.

## 3.2 Energy changes as local plans

Instead of treating energy-based rules primarily as a request to enumerate all context combinations, the compiler should derive a local plan:

\[
\Delta G(c) = G_0 + \sum_j I_j(c)\epsilon_j
\]

where each term is gated by a compact predicate mask.

The compiler's central question should be:

> Which energy factors can the graph edit performed by this rule change?

This enables runtime cost to depend on **local context around the mutation**, rather than the total number of energy patterns or the number of globally possible context combinations.

## 3.3 Conservative failure

A recurring design rule throughout this work is:

> **No false-negative dependency or energy lowering is acceptable.**

When the compiler cannot prove a compact representation is semantically complete, it should use a conservative fallback.

Examples include:

- ambiguous same-type molecule topologies;
- correlated longer-range context that cannot be represented as independent predicates;
- unresolved AST component references;
- malformed legacy energy factors;
- unsupported runtime lowering.

The correct fallback is slower execution, not silently wrong propensity.

## 3.4 Tests before semantic expansion

The user explicitly requested tests before implementation. The work therefore evolved into a deliberate sequence:

```text
write RED contract
     ↓
confirm expected failure
     ↓
implement minimal semantic layer
     ↓
make contract GREEN
     ↓
add adversarial/property/oracle tests
     ↓
only then expose runtime behavior
```

This proved useful because the tests exposed multiple subtle architecture bugs before default behavior could be changed.

---

# 4. Persisted implementation: Phase 1

The actual implementation source preserved in this archive is under:

```text
implementation_phase1/
```

The main patch is:

```text
implementation_phase1/bng3_energy_compiler_phase1.patch
```

A duplicate of the original root-level patch is also preserved for provenance.

## 4.1 `compile::energy::EnergyDeltaPlan`

Files:

```text
implementation_phase1/source/cpp/compile/energy/EnergyDeltaPlan.hpp
implementation_phase1/source/cpp/compile/energy/EnergyDeltaPlan.cpp
```

The plan represents:

- constant free-energy changes;
- factorized conditional free-energy changes;
- conjunctive condition masks;
- signed energy terms;
- backend fallback state;
- Arrhenius rate factors derived from the plan;
- small lookup tables for compact condition spaces.

The strategy enum distinguishes:

- `Constant`;
- `BitmaskFactorized`;
- `MaterializedFallback`.

The intended semantics are:

```text
condition bitmask
       ↓
EnergyDeltaPlan::tryDeltaG(mask)
       ↓
ΔG
       ↓
tryArrheniusFactor(...)
```

The design deliberately allows signed energy contributions so binding and state transitions can eventually use the same execution representation.

## 4.2 `compile::CompiledRateLaw`

Files:

```text
implementation_phase1/source/cpp/compile/CompiledRateLaw.hpp
implementation_phase1/source/cpp/compile/CompiledRateLaw.cpp
```

This layer classifies existing rate expressions without replacing the original expression tree.

The planned typed categories include:

- ordinary expression;
- Arrhenius energy law;
- saturation law;
- Michaelis-Menten;
- Hill;
- function product;
- hybrid/other typed combinations.

The important design choice is that typing is **metadata**, not a second evaluator. The original AST expression remains available.

## 4.3 `compile::CompiledRule`

Files:

```text
implementation_phase1/source/cpp/compile/CompiledRule.hpp
implementation_phase1/source/cpp/compile/CompiledRule.cpp
```

This translates the existing rich `ReactionRule::TransformOp` information into an execution-oriented mutation signature.

The mutations cover:

- add bond;
- delete bond;
- state change;
- add molecule;
- delete molecule.

The compiled rule also records conservative affected-component information.

This is the beginning of the dependency compiler needed for selective propensity invalidation and local energy-factor lookup.

## 4.4 `compile::CompiledModel`

Files:

```text
implementation_phase1/source/cpp/compile/CompiledModel.hpp
implementation_phase1/source/cpp/compile/CompiledModel.cpp
```

The initial compiled model contains:

- compiled rules;
- compiled energy-factor metadata;
- structural fingerprints;
- source expressions and patterns needed for provenance.

The intended model is immutable and shareable across trajectories.

That immutability is important for future inference workloads where thousands of stochastic simulations may reuse the same model topology.

## 4.5 Existing `EnergyFunction` bridge

The phase-1 patch was designed to extend the existing NFsim energy infrastructure rather than replace it abruptly.

The intended additions include:

- `compileBindingDeltaPlan(...)`;
- `compileStateChangeDeltaPlan(...)`.

The existing `EnergyBindingContext` is treated as a compatibility view reconstructed from the more general `EnergyDeltaPlan` where safe.

This gives the migration path:

```text
EnergyDeltaPlan
    ↓
old context representable?
    ├── yes → existing EnergyRxnClass
    └── no  → legacy materialized fallback
```

State-change plans were compiled but the phase-1 patch intentionally did **not** switch state-change runtime execution.

## 4.6 Reaction-center inverted energy indexes

The phase-1 design also replaces repeated global energy-pattern scans with local indexes keyed by reaction center.

Conceptually:

```text
energy patterns
    ↓ one-time indexing
binding center → candidate factors
state site     → candidate factors
```

The binding key is normalized for factor lookup, so `A.x–B.y` and `B.y–A.x` identify the same factor set.

A later test-driven review discovered that this normalization is appropriate for **factor discovery** but not automatically for **compiled-plan caching**, because logical reactant orientation can differ. That bug is documented below.

---

# 5. Phase-1 tests preserved in the implementation bundle

The phase-1 source contains:

```text
implementation_phase1/source/tests/cpp/test_energy_compiler.cpp
```

The tests cover the initial compiler seam:

- conjunction-based energy terms;
- Arrhenius factor tables;
- binding-plan compilation;
- old/new binding-context equivalence;
- signed state-change plans;
- typed Arrhenius rate-law classification;
- compiled mutation signatures.

These were intentionally narrow compared with the later validation suite.

---

# 6. Large tests-first validation suite

The second major persisted artifact is under:

```text
validation_suite/
```

This is substantially larger than the phase-1 implementation itself.

At packaging time it contains:

- **39 C++ contract files**;
- **139 C++ `TEST_CASE`s**;
- **10 Python test files**;
- **40 Python tests**;
- **13 BNGL fixtures/policy files**;
- **9 validation/oracle scripts**.

The detailed inventory is preserved in:

```text
validation_suite/docs/TEST_INVENTORY.md
```

and the gate matrix in:

```text
validation_suite/docs/VALIDATION_MATRIX.md
```

## 6.1 Important distinction: green-compatible vs future RED contracts

The suite intentionally separates:

- tests that should work with current/phase-1 behavior;
- contracts for proposed future APIs.

Future contracts are named:

```text
future_*.cpp
```

They are intended to be kept behind:

```text
BNG_ENABLE_FUTURE_ENERGY_CONTRACTS=OFF
```

until the corresponding implementation exists.

This prevents unfinished architectural work from making ordinary CI permanently red.

---

# 7. Validation hierarchy

The validation plan became more concrete over the course of development.

## T0 — Pure math and data structures

No simulator required.

Examples:

- energy-mask algebra;
- Arrhenius identities;
- invalid-mask rejection;
- cache behavior;
- index-domain math;
- thermodynamic rank/cycle calculations.

## T1 — Compiler semantic contracts

Tests source AST → compiled semantics.

Examples:

- mutation signatures;
- AST-native dependency extraction;
- energy-factor relevance;
- state/bond predicates;
- conservative unresolved references.

## T2 — Lowering contracts

Tests compiled plan → backend selection.

Expected categories:

- constant;
- mapping-local;
- two-reactant pair-factorized;
- connected-context;
- materialized fallback.

## T3 — NFsim construction contracts

Tests object construction and propensity semantics.

Examples:

- transactional reversible build;
- reaction-class counts;
- initial propensity;
- exact literal-vs-factorized context weight.

## T4 — Stochastic equivalence

Generalized backend OFF vs ON across a fixed seed manifest.

Importantly, **byte-identical trajectories are not universally required**.

If a generalized lowering merges multiple legacy reaction classes into one aggregate class, it can consume random numbers differently even when the stochastic process is correct.

Therefore:

- require exact byte parity when RNG call structure is preserved;
- otherwise require exact local propensity/event-weight semantics plus prespecified multi-seed distributional equivalence.

## T5 — Independent oracle

Where semantics overlap, compare against a separately built pinned standalone NFsim and/or BNG2.

The embedded NFsim cannot serve as an independent oracle for itself.

## T6 — Performance

The proposed gates include:

- feature disabled: ≤2% median overhead;
- generalized non-energy path: ≤3% median overhead;
- ≥6 predicates: ≥16× reduction in reaction-class count;
- ≥8 predicates: target ≥4× construction speedup;
- no exponential memory growth with Boolean context count.

## T7 — Robustness

Includes:

- ASan;
- UBSan;
- randomized energy-plan tests;
- randomized dependency graphs;
- concurrency/cache stress;
- invalid inputs;
- fuzz hooks.

---

# 8. Exhaustive semantic oracle strategy

A central validation idea is to avoid relying only on stochastic trajectories for local correctness.

For plans with a manageable number of predicates, enumerate every context mask.

For each mask compare:

1. literal energy-pattern evaluation;
2. compiled `EnergyDeltaPlan` evaluation;
3. forward Arrhenius factor;
4. reverse Arrhenius factor.

The preferred numeric tolerance is approximately `1e-12` for pure double-precision algebraic identities.

This catches semantic mistakes much more efficiently than waiting for a trajectory divergence.

The validation suite includes scripts intended to support this style of checking.

---

# 9. Stochastic equivalence scheme

The final statistical scheme became more careful than the initial proposal.

For stochastic backends that cannot retain identical RNG consumption, compare distributions over many seeds.

The prespecified defaults were approximately:

- normally at least 1024 seeds;
- 4096 for small finite-state systems where cheap.

Primary gates:

### Mean

Difference should be no more than roughly 5 pooled standard errors.

### Variance

Variance ratio should lie approximately in:

```text
0.80 – 1.25
```

### Distribution shape

The initial design used empirical total-variation distance everywhere.

During review, that was recognized as too fragile for broad integer-valued count distributions, because finite samples fragment support.

The improved rule is:

- **small categorical support** → empirical TV distance;
- **broad count-valued distributions** → two-sample KS distance;
- retain independent mean/variance gates.

The Python validation scripts and tests were adjusted around this distinction.

---

# 10. Adversarial cases represented by the test suite

The suite intentionally focuses on cases that are easy to mishandle silently.

## 10.1 Reactant orientation

A binding factor lookup may be symmetric under endpoint swap, but a compiled plan is not necessarily orientation-free because predicates carry logical reactant indices.

A regression test was introduced for:

```text
compile(A, B)
compile(B, A)
```

The factor index may be symmetric; the cached compiled plans must remain orientation-correct.

## 10.2 Same molecule type on both endpoints

Same-type binding creates ambiguity if the compact evaluator cannot prove which logical molecule owns which context.

Tests require either correct handling or conservative fallback.

## 10.3 Shared predicates

Multiple energy factors may depend on the same context predicate.

The compiler should deduplicate the predicate but keep separate factor contributions.

## 10.4 State predicates

The old compact `EnergyBindingContext` path primarily understands occupancy-style conditions.

Tests therefore distinguish:

```text
A(x!+)
```

from richer semantics such as:

```text
A(x~P)
A(x!B.y)
A(x!1).B(y!1,s~P)
```

The richer predicates must not be silently collapsed to ordinary occupancy.

## 10.5 One-hop partner state

An energy factor may depend on the state of the molecule bound to the reaction-center molecule.

Tests require the dependency and runtime invalidation logic to notice this indirect state change.

## 10.6 Correlated longer-range topology

Some patterns cannot be represented as independent Boolean local predicates.

The correct behavior is materialization/fallback unless a backend can prove the required graph correlation.

## 10.7 More than 63 Boolean conditions

The bitmask representation is deliberately bounded.

Tests require overflow to fail closed rather than wrap masks.

## 10.8 Partial reversible construction failure

A generalized reversible rule must not leave the system half-mutated.

The intended transaction is:

```text
stage forward
stage reverse
all valid?
  yes → commit both
  no  → destroy staged objects; system unchanged
```

Tests were written around this requirement before runtime integration.

## 10.9 Parameter rebinding

A compiled structural model reused across trajectories must not freeze numerical parameters such as:

- energy values;
- `phi`;
- `RT`;
- activation energies.

Tests require structural compilation to be reusable while numerical parameters remain trajectory/run-specific where appropriate.

## 10.10 Runtime invalidation without membership changes

A particularly dangerous bug class is:

> context changes, reaction membership remains valid, but propensity is stale.

Tests cover state changes and bonded-partner state changes that should update the rate factor even if the molecule remains a legal reactant.

---

# 11. Bugs / design flaws discovered through tests-first review

## 11.1 Orientation-normalized plan cache bug

The first cache design reused normalized binding keys.

That is correct for finding candidate factors but wrong for compiled plans when predicates contain `reactantIndex`.

Example:

```text
A.x + B.y
```

and

```text
B.y + A.x
```

can refer to the same energy factor, while context ownership swaps between logical reactants.

The design was corrected conceptually to:

- normalized key for factor index;
- orientation-sensitive key for compiled plan cache.

The validation suite contains the regression contract.

## 11.2 Re-parsing BNGL strings beneath the AST

An early dependency-compiler approach reconstructed molecule/component meaning from stored BNGL pattern strings.

That would create a second parser beneath the canonical AST.

This conflicts with the clean BNG3 architecture and risks semantic drift.

The improved requirement is:

```text
ReactionRule::getReactantPatterns()
        ↓
SpeciesGraph
        ↓
PatternGraph / Node structure
        ↓
compiled dependency descriptor
```

String parsing should exist only as a conservative compatibility fallback for legacy/programmatically constructed rules lacking graph objects.

Tests for AST-native descriptors were added before this refactor was considered acceptable.

## 11.3 Overly broad use of TV distance

As described above, raw empirical TV was recognized as a poor universal stochastic metric for broad count support.

The validation design was corrected to categorical TV vs count-distribution KS.

---

# 12. Proposed generalized runtime architecture represented by future tests

The later design work proposed two important runtime classes.

These concepts are extensively represented in `future_*.cpp` contracts, but **their complete production integration is not preserved as finished source in this archive**.

## 12.1 `EnergyContextRxnClass`

Intended use:

- one logical reactant carries the energy context;
- DOR-style weighted mappings;
- state, bond, and one-hop partner-state predicates;
- no Boolean context rule materialization.

Conceptual propensity:

\[
a = k_0 \sum_m w(m)
\]

where `w(m)` is obtained from the compiled energy plan for that mapping's context.

## 12.2 `EnergyPairRxnClass`

Intended for binding where predicates are distributed across both reactants.

Instead of enumerating every context rule, aggregate mappings by local context mask:

\[
a = k_0\sum_{c_1,c_2}N_1(c_1)N_2(c_2)F(c_1,c_2)
\]

For molecularity-sensitive or RuleMonkey-style paths, exact valid-pair enumeration may still be required.

The validation suite contains exact pair-sum tests and event-weight contracts for this proposed backend.

## 12.3 Transactional construction

The future tests also specify a `ReactionBuildBatch`-style transaction object so reversible generalized rules cannot be partially registered.

Again, this is strongly specified by tests, but the complete production source is not part of the persisted implementation archive.

---

# 13. Dependency compiler and invalidation graph plan

The intended next layer after phase 1 is a graph connecting:

```text
rule graph mutation
      ↓
affected molecule/site keys
      ↓
energy factors that depend on those keys
      ↓
reaction propensities that depend on those factors
```

This should support selective updates and large-model scalability.

The tests cover:

- state edits;
- bond edits;
- molecule add/delete;
- unresolved references;
- conservative global invalidation;
- randomized dependency properties.

The guiding rule remains:

> an unnecessary update is acceptable; missing a required update is not.

---

# 14. Indexed / parametric rule-family plan

A major long-term goal is to better support Rasi/genome/ordered-polymer models where thousands of rules differ mainly by integer position.

The proposed compiler IR includes concepts such as:

```text
IndexDomain
AffineIndexExpression
IndexedMutation
IndexedRuleFamily
```

Example conceptual rule family:

```text
for i in 1..N-1:
    R(i,state=elongating) -> R(i+1,state=elongating)
```

The backend should reason over the family rather than forcing BNGL source expansion into thousands of unrelated rules.

The validation suite contains future contracts for:

- affine index mapping;
- boundaries;
- local affected-index queries;
- out-of-domain rejection.

What is **not** implemented in the persisted code:

- BNGL grammar for indexed rules;
- parser support;
- NFsim parametric runtime storage;
- ordered-polymer specialized state representation.

These should be added only after the compiled semantic seam is stable.

---

# 15. Thermodynamic extension plan

The future architecture also contemplates separating equilibrium energy from kinetic barriers and non-equilibrium driving.

Conceptual components:

- state free-energy contribution;
- activation barrier;
- barrier modifier;
- external work / driving contribution.

Desired properties include:

### Barrier change

Changes forward/reverse timescale without changing equilibrium ratio.

### Driving work

Changes cycle affinity and therefore can encode non-equilibrium behavior.

The future validation suite contains contracts for:

- barrier invariance of equilibrium ratio;
- driven cycle affinity;
- graph rank;
- cycle rank;
- gauge degrees of freedom;
- state-potential reconstruction.

What is **not** implemented in the persisted phase-1 code:

- BNGL syntax for barriers;
- BNGL syntax for reservoirs/driving;
- parser integration;
- production NFsim execution of driven rules.

This was deliberately deferred because thermodynamic semantics should not be exposed before legacy energy parity is solid.

---

# 16. Compiled-model cache / trajectory blueprint plan

A major practical reason for the compiled representation is inference workloads.

For example, stochastic parameter inference may require thousands of NFsim trajectories from one structural model.

The desired future lifecycle is:

```text
BNGL parse               once
CompiledModel             once
NFsim structural blueprint once
      ↓
instantiate numerical trajectory state repeatedly
      ├── parameters θ1 + seed 1
      ├── parameters θ2 + seed 2
      └── ...
```

Tests were written for:

- immutable cache reuse;
- concurrent lookup;
- version invalidation;
- parameter rebinding;
- blueprint concurrency;
- batch NF API.

The current archive does **not** contain a fully integrated production NFsim blueprint/cache implementation.

---

# 17. BNGL / model fixtures included

The validation suite contains concrete BNGL fixtures designed to exercise the real parser and direct AST/NF path rather than only synthetic C++ objects.

Included cases include:

- constant binding energy;
- reactant-0 state context;
- reactant-1 state context;
- mixed-reactant state context;
- local state-change context;
- same-type binding;
- shared predicate factors;
- symmetric sites;
- reverse mixed bound context;
- correlated two-hop fallback;
- no-relevant-factor behavior.

See:

```text
validation_suite/fixtures/energy/
```

---

# 18. Validation and oracle scripts included

The archive includes reusable scripts for:

- semantic energy oracle evaluation;
- stochastic OFF-vs-ON parity;
- exact output parity;
- numeric-table comparison against external oracles;
- performance measurement;
- performance threshold gating;
- Boolean context fixture generation;
- orchestration of energy validation.

See:

```text
validation_suite/scripts/
```

The scripts were designed to emit machine-readable output suitable for CI rather than only human-readable plots.

---

# 19. CI design

The suite contains:

```text
validation_suite/cmake/energy_tests.cmake
validation_suite/docs/CI_SNIPPET.yml
```

The intended policy is:

1. normal green-compatible energy/compiler tests run by default;
2. future contracts remain disabled until implementation lands;
3. sanitizer and stochastic/performance jobs can run separately because they are more expensive;
4. promotion of generalized runtime to default-on requires the full gate stack, not merely unit-test success.

---

# 20. What was actually validated in the development environment

The preserved implementation's local validation record is in:

```text
implementation_phase1/VALIDATION.md
```

The checks that were actually performed included:

- standalone C++17 compile of `EnergyDeltaPlan` with strict warnings;
- standalone/API-compatible compile of compiled-rule/rate/model classes;
- energy index standalone compile/run;
- energy-plan bridge compile against compatible NFcore contracts;
- patch syntax/application check on a synthetic preimage constructed from exact source contexts;
- `git diff --check` on the applied synthetic patch;
- later Python validation-suite self-tests, which reached 40/40 passing;
- standalone smoke validation of pure compiler energy math.

These checks are meaningful, but they do **not** replace a full repository build.

---

# 21. What could not be validated, and why

This is one of the most important sections of the handoff.

## 21.1 No ordinary full repository checkout in the execution VM

The shell environment could not resolve `github.com` for a normal `git clone`.

Therefore a complete mutable checkout was not available in the local container.

## 21.2 GitHub integration was read-only for repository mutation

Repository source could be inspected through the connected GitHub integration, including exact files at the target SHA.

However attempts to:

- create a branch;
- update a ref;
- create/update source files;

returned HTTP 403 (`Resource not accessible by integration`).

Therefore the work could not be committed or pushed into PR #2 from this session.

## 21.3 Full CMake build was not run

Because there was no complete writable checkout, the following were not run against the cumulative implementation:

- full configure/build;
- complete CTest suite;
- linked real `test_energy_compiler` target;
- all compiler/runtime integration tests.

## 21.4 Independent NFsim oracle was not run

The branch explicitly requires an independently built native NFsim when claiming network-free parity.

That oracle was not available in the environment for the cumulative work.

Therefore no claim is made that the generalized future backend has passed independent NFsim parity.

## 21.5 BNG2 oracle suite was not run

The legacy BNG2 validation corpus was not executed against the cumulative proposed changes.

## 21.6 Sanitizers/toolchain matrix was not run

The future validation policy calls for:

- ASan;
- UBSan;
- Linux GCC;
- Linux Clang;
- macOS Clang/Apple Silicon;
- relevant Windows/MSVC paths.

Those gates remain to be executed in real CI or a complete checkout.

## 21.7 Performance claims for the new generalized compiler/runtime are not established

The project has strong prior standalone NFsim performance results for Rasi/uORF models, but those should not be conflated with performance of the new generalized energy compiler/runtime.

The included performance scripts are **gates to run**, not evidence already collected for this new code.

---

# 22. Important relationship to prior NFsim optimization work

Separate optimization work on standalone NFsim had already demonstrated very large improvements for Rasi/uORF-style workloads, including:

- large kernel speedups;
- dramatic startup reduction;
- large memory reduction from mapping storage redesign;
- improved parallel trajectory feasibility;
- exact fixed-seed output parity on tested fixtures.

Those results motivated several architectural priorities here:

1. avoid global scans;
2. index dependencies locally;
3. avoid dense per-reaction/per-molecule storage;
4. do not expand structurally repetitive rules if a parametric representation can preserve semantics;
5. compile once and reuse across trajectories.

However, this BNG3 handoff does not assume that every later standalone NFsim optimization is already present in the inspected BNG3 branch. Exact source-cutoff auditing remains necessary before porting any missing optimization.

---

# 23. Why the observation operator was not included

For the user's biology/inference project, NFsim is intended to generate latent molecular dynamics that are later mapped to assay data such as RNA/ATAC through an observation operator.

That observation operator should remain **outside BioNetGen/NFsim**.

BNG3 should model biological dynamics and expose simulated latent states/observables. Assay-specific measurement distortion belongs in the inference pipeline, not in the rule-based simulator core.

Therefore this compiler redesign deliberately does not absorb the multiome observation operator.

---

# 24. Recommended next implementation order

Given the current state of the archive, the safest continuation is:

## Step 1 — Apply phase-1 implementation to an exact checkout

Start from:

```text
RuleWorld/BNG3@3bc7b4ff131f8927421bc8eae170e3b248b75318
```

Use:

```bash
cd implementation_phase1
./apply.sh
```

or apply the patch manually.

## Step 2 — Build and run existing branch tests before adding future functionality

Run the repository's standard build/CTest gates.

If phase 1 is not green, fix integration before continuing.

## Step 3 — Install the validation suite

Use:

```text
validation_suite/install_tests_into_bng3.sh
```

Keep `future_*.cpp` disabled initially.

Run all green-compatible contracts.

## Step 4 — Finish AST-native dependency compilation

The normal path should consume `SpeciesGraph` directly.

Do not reparse BNGL source strings as a second semantic implementation.

## Step 5 — Implement explicit dependency graph

Compile:

```text
rule mutation → site/type keys → energy factors → dependent reactions
```

Require all D-series tests to pass.

## Step 6 — Implement generalized `EnergyPatternStore` / lowering selector

Add versioned plan caching and backend-neutral lowering selection.

Require:

- orientation-cache tests;
- opaque-factor fallback;
- >63-condition fallback;
- same-type safety.

## Step 7 — Implement mapping-local generalized runtime

Implement the one-reactant weighted context backend first.

This is simpler to qualify than mixed-reactant binding.

Require exact local propensity tests plus materialized-path semantic parity.

## Step 8 — Implement transactional reversible construction

Do this before mixed-reactant runtime promotion.

Partial construction must never mutate the final system.

## Step 9 — Implement pair-factorized binding runtime

Use the independently tested context-weight aggregation object.

Qualify molecularity and RuleMonkey behavior separately.

## Step 10 — Run independent stochastic/oracle gates

Only after local semantic tests are green:

- native NFsim oracle;
- BNG2 overlap corpus;
- multi-seed distributional parity.

## Step 11 — Benchmark context explosion

Use generated Boolean-context models to prove that the generalized backend changes scaling rather than only constant factors.

## Step 12 — Build structural blueprint/cache

After runtime semantics are stable, add compile-once/instantiate-many NFsim support.

This is especially valuable for SBI and other parameter inference.

## Step 13 — Indexed/parametric rule families

Only after canonical compiled semantics are stable should the BNGL grammar grow indexed rule syntax.

## Step 14 — Barrier/driving syntax

Expose thermodynamic extensions last, after legacy equilibrium-energy semantics are fully qualified.

---

# 25. Promotion criteria for default generalized energy execution

The generalized backend should remain opt-in until all of the following are demonstrated:

1. compiler semantic contracts green;
2. exhaustive context oracle green;
3. legacy fallback verified for unsupported topology;
4. no incorrect use of old occupancy-only compact path;
5. initial propensity parity;
6. physical event-weight parity;
7. molecularity/symmetry tests green;
8. stochastic distributional equivalence;
9. independent native NFsim/BNG2 overlap validation;
10. sanitizers clean;
11. disabled-path performance regression within threshold;
12. generalized path shows meaningful reaction-class/construction scaling improvement.

Only then should the environment feature gate be considered for default-on behavior.

---

# 26. Archive layout

Top-level structure:

```text
CONTEXT_IMPLEMENTATION_VALIDATION_HANDOFF.md   this document
FILE_MANIFEST.txt                              complete file inventory
SHA256SUMS.txt                                 archive-internal checksums

implementation_phase1/
    README.md
    VALIDATION.md
    apply.sh
    bng3_energy_compiler_phase1.patch
    source/
        cpp/compile/...
        tests/cpp/test_energy_compiler.cpp
        BNG3_ENERGY_COMPILER_PLAN.md

validation_suite/
    README.md
    bng3_energy_validation_tests_additions.patch
    cmake/
    docs/
    fixtures/
    scripts/
    tests/cpp/
    tests/python/
    install_tests_into_bng3.sh
    run_selfcheck.sh

reference_docs/
    BNG3_ENERGY_COMPILER_PLAN_earlier_copy.md

original_archives/
    original phase-1 tar.gz
    original validation tar.gz
    original validation zip
```

The nested original archives are intentionally preserved for provenance, even though their contents are also unpacked at top level.

---

# 27. What is *not* in this archive despite being discussed during development

This section prevents overinterpretation of the handoff.

The conversations described/prototyped later runtime/compiler pieces beyond phase 1. The current filesystem does **not** preserve all of those as complete production source files.

In particular, do not assume this archive contains finished implementations of:

- production `EnergyContextRxnClass` integrated into NFsim;
- production `EnergyPairRxnClass` integrated into NFsim;
- final `EnergyPatternStore` implementation;
- final dependency graph implementation;
- final `ReactionBuildBatch` implementation;
- final compiled NFsim blueprint/cache;
- final batch trajectory API;
- indexed BNGL parser syntax;
- barrier/driving BNGL parser syntax;
- ordered-polymer specialized runtime.

Many of these are instead represented by **detailed future RED contracts** in the validation suite.

That is intentional and useful: the tests encode the desired semantics so the implementation can be reconstructed without relying on vague prose.

---

# 28. Why the tests are arguably the most valuable part of the handoff

The implementation architecture is still evolving, but the failure modes are now much better specified.

The test suite encodes decisions such as:

- when orientation matters;
- when factor lookup may be symmetric;
- when plan caching may not be symmetric;
- when fallback is mandatory;
- how state and partner-state context should behave;
- how transactional construction must work;
- how structural caching must separate topology from numerical parameters;
- how stochastic equivalence should be measured;
- what performance improvement is required to justify complexity.

This makes future implementation work much less likely to optimize the wrong semantics.

---

# 29. Suggested first commands in a real checkout

From an exact clean checkout:

```bash
# verify source
printf 'HEAD: '
git rev-parse HEAD

# inspect patch first
git apply --stat /path/to/handoff/implementation_phase1/bng3_energy_compiler_phase1.patch

git apply --check /path/to/handoff/implementation_phase1/bng3_energy_compiler_phase1.patch

git apply /path/to/handoff/implementation_phase1/bng3_energy_compiler_phase1.patch

git diff --check
```

Then configure/build using the branch's documented CMake workflow and run CTest.

Only after phase-1 integration is green should the validation suite be installed.

For the test suite itself:

```bash
cd /path/to/handoff/validation_suite
./run_selfcheck.sh
```

Then install it into the BNG3 checkout and keep future contracts disabled until their APIs exist.

---

# 30. Final status

The project now has two strong persisted products:

### Product A — a concrete phase-1 compiler implementation

This establishes the compiled-model seam, typed rate metadata, mutation signatures, local energy-delta plan, and initial bridge into existing NFsim energy machinery.

### Product B — a much larger tests-first specification for the remainder

This specifies the dependency compiler, generalized local/pair runtime, transactional construction, caching, thermodynamic constraints, indexed rules, stochastic parity, independent oracle comparisons, fuzzing, sanitizer checks, and performance requirements.

The largest remaining gap is not lack of design detail. It is **full integration and qualification in a real writable BNG3 checkout with the independent oracle/toolchain matrix available**.

The recommended discipline is therefore:

> apply the preserved implementation, install the preserved tests, make each future RED contract green in small slices, and do not remove the legacy fallback or enable generalized execution by default until the complete semantic/oracle/performance gates pass.
