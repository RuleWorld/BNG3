# BNG3 Lean semantic kernel

> **Status:** experimental formal specification / reference semantics for BNG3.
>
> **Audience:** BioNetGen/BNG3 developers and modelers. You do **not** need to
> know Lean to understand the design.
>
> **Relationship to CRNT-Lean:** none. This project formalizes the meaning of
> the BNG3 language/compiled IR. CRNT can be a downstream analysis after a
> finite reaction network has been derived.

## The one-sentence idea

BNGL is friendly text for humans; this Lean project describes the **resolved
semantic object and rule behavior that the text should compile into**.

The intended BNG3 compiler architecture is:

```text
BNGL
  ↓ parse
ast::Model
  ↓ resolve names + compile once
bng::compile::Document
  ├── CompiledModel          ← reusable semantic model
  └── SimulationProtocol     ← what the user asked to run
  ↓ lower
backend-specific representation
  ├── network generator
  ├── NFsim
  └── NFnext / NFIR
```

The Lean project lives beside that implementation. It is not in the simulation
hot loop. Its job is to provide a small, readable **reference meaning** against
which optimized backends can eventually be checked.

---

# What changed in this iteration

The previous prototype mostly formalized the *shape* of the target IR. This
iteration implements the first important operational step:

```text
semantic Pattern
     ↓ match
concrete molecular Mixture
     ↓ apply compiled Mutation list
resulting Mixture
```

and then a separate lowering path:

```text
semantic Mutation list
     ↓ lower
BackendAction list
     ↓ execute
resulting Mixture
```

with machine-stated refinement theorems asserting that the two execution paths
are equal for the explicitly supported subset.

That is the first point where this stops being only a typed schema and begins
to be a **formal operational semantics**.

---

# ELI15: what problem are we solving?

Suppose a user writes:

```bngl
A(x~u) + B(y) -> A(x~p!1).B(y!1)  k
```

A human reads this as:

1. find one `A` whose `x` site is in state `u`;
2. find one `B` with site `y`;
3. change `A.x` from `u` to `p`;
4. create a bond between `A.x` and `B.y`.

A production simulator does not literally execute those four English steps.
NFsim has graph objects, mappings, transformation sets, caches, reaction
centers, symmetry handling, and many other optimizations. Network generation
uses different machinery. NFnext may use another representation again.

The danger is that each backend can accidentally implement a slightly different
interpretation of the same BNGL rule.

The formal reference semantics says:

> Here is a deliberately slow and obvious definition of what a match is and
> what applying this compiled rule does to a molecular graph.

Then a backend can be tested—or for selected pieces, proved—to refine that
reference behavior.

---

# What is now formalized?

## 1. Resolved semantic model

The project contains typed representations for:

```text
CompiledModel
├── parameters
├── molecule types
│   └── components
│       └── allowed states
├── compartments
├── seed species
├── observables
├── functions
├── energy factors
├── population maps
└── compiled reaction rules
    ├── forward direction
    └── optional fully compiled reverse direction
```

Names remain useful for diagnostics/round-tripping. Semantic relationships use
strongly typed IDs.

## 2. Structured expressions

Expressions are trees with explicit operators and typed references rather than
strings that a backend must reparse.

For example, conceptually:

```text
k1 * A + k2 * B
```

becomes a tree like:

```text
add
├── multiply(parameter k1, ...)
└── multiply(parameter k2, ...)
```

## 3. Semantic molecular patterns

A pattern is a constrained molecular graph with:

- molecule occurrence IDs;
- resolved molecule type IDs;
- site occurrence IDs;
- resolved component IDs;
- exact / set / unconstrained states;
- free / bound / wildcard / exact bond requirements;
- explicit exact bond edges;
- optional compartments;
- molecule-level bond wildcards.

The representation deliberately preserves capabilities present in current BNG3
that a simplified `PatternV2` sketch could accidentally lose, such as multiple
bond specifications on one site.

## 4. Compiled reaction rules

A `RuleDirection` contains:

- reactant patterns;
- product patterns;
- a resolved rate law;
- explicit semantic mutations;
- molecule correspondence across the arrow;
- component correspondence;
- local-scope bindings;
- filters;
- modifiers.

Reversible rules are intended to contain complete forward and reverse
directions so a backend does not reconstruct reverse semantics itself.

## 5. Concrete runtime mixtures — **new**

`BNG/Runtime.lean` introduces a small concrete graph:

```text
Mixture
├── concrete molecule instances
│   ├── unique runtime ID
│   ├── molecule type
│   ├── optional compartment
│   └── concrete sites + optional states
└── explicit undirected bonds between concrete sites
```

This is not meant to mimic NFsim's memory layout. It is intentionally boring.
A reference model should optimize for clarity, not event throughput.

## 6. Pattern embeddings and matching — **new**

An `Embedding` maps pattern molecule occurrences to concrete molecule IDs.

For one candidate embedding, `Pattern.embeddingMatches` checks:

1. every pattern molecule is mapped;
2. the mapping is injective;
3. concrete molecules exist;
4. molecule types agree;
5. specified compartments agree;
6. exact state constraints agree;
7. `free`, `bound`, `any`, and exact-bond requirements agree;
8. explicit pattern bonds exist in the concrete graph;
9. molecule-level bond requirements agree.

`Pattern.matches` then **enumerates all valid embeddings** by brute force.

This is intentionally slow. If a pattern has `n` molecule occurrences and the
mixture has `m` molecules, the raw search can be on the order of `m^n` before
filtering. That is unacceptable for NFsim and excellent for a tiny correctness
oracle because the algorithm is easy to inspect.

## 7. Whole-rule matches — **new**

A BNGL rule may have several top-level reactant patterns. `RuleMatch` stores one
embedding per top-level reactant.

`RuleDirection.ruleMatchValid` additionally checks that those embeddings do not
reuse the same concrete molecule across distinct top-level reactants.

`RuleDirection.matches` enumerates all such non-overlapping whole-rule matches.

## 8. Concrete mutation execution — **new**

The reference semantics now executes these compiled mutations:

```text
changeState
createBond
deleteBond
clearBonds
createMolecule
deleteMolecule
moveCompartment
```

Mutation targets are resolved through the rule match and the compiled
reactant↔product correspondence table.

Failures are explicit as `Option.none`. For example, trying to delete a bond
that is not present is not silently treated as success.

## 9. Independent backend action language — **new**

`BNG/Lowering.lean` defines a distinct target vocabulary:

```text
setState
addBond
removeBond
removeAllBonds
allocateMolecule
eraseMolecule
relocateMolecule
```

Semantic `Mutation`s lower into those backend actions. The backend executor
never pattern-matches on `Mutation` itself.

This separation is small, but important: it gives us two independently named
layers to relate with a refinement theorem.

---

# The substantive theorem now present

The core theorem family is:

```text
semantic mutation
       │ lower
       ▼
backend action

execute semantic mutation
       =
execute lowered backend action
```

The project proves the equality first for one mutation, then by induction for an
arbitrary finite mutation list, and finally at the public rule-step boundary.

In Lean terms, the important theorem is:

```lean
backend_rule_step_refines_semantics
```

Conceptually:

```text
                 reference semantics
Mixture + Match --------------------------> Mixture'
      |                                        ^
      | lower rule edits                       |
      v                                        | equal result
Backend action program ------------------------+
```

This is still a **model of a backend**, not yet NFsim itself. The next serious
engineering bridge is to map this backend action vocabulary onto a real NFnext
or NFsim lowering and establish parity/refinement there.

---

# Worked example

`BNG/Examples.lean` contains the semantic form of:

```bngl
A(x~u) + B(y) -> A(x~p!1).B(y!1)  k
```

It also creates the concrete mixture:

```text
A#0(x~u)    B#1(y)
```

The reference matcher should find exactly one whole-rule match. Applying the
rule should produce a mixture in which:

```text
A#0.x state = p
A#0.x -- B#1.y bond exists
```

The smoke file evaluates both facts and also type-checks an instance of the
general backend-refinement theorem.

---

# What does "supported subset" mean?

A formal result is useful only if its assumptions are visible.

The current rule-step refinement theorem covers local graph edits for directions
where:

```text
filters     = []
localScopes = []
modifiers   = []
```

Within that gate, the implemented graph-edit vocabulary includes state changes,
bond creation/deletion/clearing, molecule creation/deletion, and direct
compartment movement.

Why exclude those other features?

Because several of them alter **match selection, rate calculation, multiplicity,
or connected-component behavior**, not merely the local edit list. Pretending
they were already covered would make the theorem sound stronger than it is.

### Explicitly not yet covered by the refinement theorem

- `DeleteMolecules` modifier semantics;
- ordinary `-> 0` complete-species-removal semantics;
- `MoveConnected` connected-component transport;
- `MatchOnce`;
- `TotalRate`;
- rule priorities;
- include/exclude filters;
- local-function evaluation;
- symmetry factors / reaction-path degeneracy;
- automorphism handling;
- reactant multiplicity corrections;
- population species semantics;
- special rate-law numerical semantics;
- event scheduling / propensities;
- stochastic time evolution;
- canonical labeling / graph-isomorphism algorithms.

Those are future feature-by-feature proof obligations.

---

# Important semantic simplifications in the concrete mixture

## Sparse concrete sites

The reference `RuntimeMolecule` does not require every declared component to be
materialized. Every site that *is* present must be legal for the molecule type.

This keeps the first operational semantics compact. A future NFsim-refinement
model may instead use complete molecule-type site vectors.

## New-molecule initialization

For product-created molecules:

- `exact s` initializes to state `s`;
- `oneOf [s]` initializes to `s`;
- `any` initializes to no selected state;
- a multi-valued `oneOf [s1,s2,...]` is rejected because creation needs one
  concrete value, not a set of possibilities.

Bonds for a new molecule are established by explicit `createBond` mutations,
not by silently interpreting the product pattern a second time.

## Exact bonds are undirected

The reference mixture treats `(A.x,B.y)` and `(B.y,A.x)` as the same bond.
Duplicate exact edges and self-bonds are rejected.

---

# Why the formalization does not execute product patterns directly

A common temptation is:

> Match the reactants, then simply replace them with the product graph.

That is not a good semantic model for BNGL because rule application can preserve
unmentioned context. A rule changes only specified parts of a potentially much
larger matched molecular complex.

The formal layer therefore treats **compiled mutations** as the executable
meaning of the arrow, with explicit cross-arrow correspondence telling us which
runtime molecules survive.

That architecture matches the direction BNG3 already needs for NFsim/network
backend convergence.

---

# Why this is useful for BNG3 rather than just mathematically cute

The theorem itself is not the product. The useful engineering consequence is a
future workflow like:

```text
BNGL fixture
   ↓ C++ compile
canonical CompiledModel / rule semantics
   ├──→ NFsim lowering
   ├──→ NFnext lowering
   └──→ Lean/reference execution

compare resulting graph edits
```

This gives BNG3 several layers of defense:

1. ordinary unit tests;
2. differential tests against legacy BioNetGen/NFsim;
3. property-based generated molecular graphs;
4. an executable slow reference semantics;
5. selected machine-checked refinement theorems.

AI makes this more attractive because agents can generate large numbers of weird
rules and mixtures. A simple reference semantics gives those generated tests a
strong oracle instead of relying on one backend to validate another backend.

---

# Directory map

```text
formal/lean/
├── README.md
├── FINDINGS.md
├── CXX_MAPPING.md
├── PROOF_ROADMAP.md
├── VALIDATION.md
├── lakefile.lean
├── lean-toolchain
├── BNG.lean
├── BNG/
│   ├── Util.lean
│   ├── Ids.lean
│   ├── Source.lean
│   ├── Expression.lean
│   ├── Declarations.lean
│   ├── Pattern.lean
│   ├── Rule.lean
│   ├── Model.lean
│   ├── Runtime.lean          ← concrete molecular graph
│   ├── Operational.lean      ← embeddings, matching, rule application
│   ├── Lowering.lean         ← backend actions + refinement proofs
│   ├── Examples.lean
│   └── Theorems.lean
└── tests/
    └── Smoke.lean
```

---

# ELI15: how to read the Lean

A structure is roughly a record/class:

```lean
structure ConcreteEndpoint where
  molecule : MoleculeInstanceId
  component : ComponentTypeId
```

An `inductive` type is like a safe enum whose alternatives can carry data:

```lean
inductive BackendAction where
  | setState (target : ComponentTarget) (state : StateId)
  | addBond (left right : ComponentTarget)
  | eraseMolecule (target : RuleMoleculeEndpoint)
```

A function returning `Option X` either succeeds with `some x` or explicitly
fails with `none`.

A theorem like:

```lean
theorem execute_lowered_mutation_eq_reference ... := by
  cases mutation <;> rfl
```

means:

> Check every possible kind of mutation. After unfolding the definition of its
> lowering and the two executors, both sides are literally the same computation.

The program-level theorem then uses induction: if one lowered edit behaves the
same and the rest of the lowered edit list behaves the same, the entire finite
program behaves the same.

---

# Relationship to the C++ migration plan

The formalization reinforces the proposed sequence:

```text
PR 1  complete CompiledModel
PR 2  Pattern V2
PR 3  typed expressions + resolved Rule V2
PR 4  NFsim from CompiledModel
```

The new operational work adds an important constraint to PR 3/4:

> The mutation list and correspondence map must be complete enough that a
> backend can apply a rule **without rereading product/reactant source syntax to
> rediscover semantics**.

The existing C++ tree shows why this matters: current `ReactionRule` and NFsim
translation code carry substantial special logic for deletion, transport,
product-only operations, and transformation construction. That behavior needs
to migrate deliberately rather than disappear behind an overly simple
five-mutation IR.

See `CXX_MAPPING.md` and `FINDINGS.md` for the concrete implications.

---

# How C++ and Lean should eventually communicate

Do not call Lean from an NFsim event loop.

A sensible architecture is:

```text
BNGL
 ↓
C++ parser/compiler
 ↓
CompiledModel
 ├────────────────→ normal optimized backends
 │
 └── CI/debug export → canonical semantic JSON
                       ↓
                 reference/Lean checks
```

A future structural BNGIR can become that canonical interchange once the
semantic IR is stable.

The highest-value next bridge is probably **NFnext first**, because a typed NFIR
is easier to model than legacy NFsim internals. After that, the same semantic
fixtures can test NFsim lowering.

---

# How to run

The project pins:

```text
leanprover/lean4:v4.33.1
```

and intentionally has no Mathlib dependency.

With `elan`/Lean installed:

```bash
cd formal/lean
./scripts/static_validate.py   # packaging sanity check; not a proof
lake build                    # actual Lean kernel check
lake env lean tests/Smoke.lean
```

Expected smoke values include:

```text
true    -- model.wellFormed
true    -- runtimeMixture.wellFormed
1       -- number of whole-rule matches in the worked fixture
true    -- A.x became p
true    -- A.x-B.y bond exists
```

---

# Verification status

The local execution environment used for this package does not provide `lean`,
`lake`, or `elan`. Therefore the Lean kernel could not type-check the project
locally at the 2026-09-14 checkpoint.

That means:

- this is concrete Lean source, not pseudocode;
- imports/delimiters/placeholders can be checked statically here;
- **theorems are not trusted artifacts until `lake build` succeeds on a machine
  with the pinned toolchain**.

See `VALIDATION.md` for the exact checks and limitations.

Pull requests run the pinned kernel and smoke gate in
[`../../.github/workflows/formal.yml`](../../.github/workflows/formal.yml).
This keeps kernel evidence attached to the exact PR head; local static
validation and NFnext contract success remain useful preflight checks but are
not theorem-validation evidence.

---

# What should be done next?

The next step should **not** be "formalize all of BNGL." It should connect this
reference semantics to one real backend representation.

Best sequence:

```text
1. Kernel-build/fix this Lean project under Lean 4.33.1.
2. Add canonical C++ export for a small CompiledRule/Pattern subset.
3. Generate parity fixtures from real BNGL models.
4. Mirror the relevant NFnext PredicateIR/ActionIR subset in Lean.
5. Prove/validate that CompiledRule -> NFIR lowering preserves one-step graph edits.
6. Add generated/property tests comparing C++ backend results to the reference matcher.
7. Expand semantic coverage only when a real BNGL feature requires it.
```

After that, the difficult high-value features are `DeleteMolecules`, complete
species deletion, `MoveConnected`, and symmetry/multiplicity. Those are exactly
the cases where independent backend implementations are most likely to drift.

---

# What this project does *not* prove

Even after every theorem above succeeds, it would **not** establish:

```text
"this biological model is true"
```

It establishes statements of the form:

```text
"given this compiled rule meaning, this lowering/executor preserves that meaning"
```

Biological validity still comes from experiments, data, model comparison, and
scientific reasoning. This formalization is about making the software/language
contract less ambiguous.

---

# Expanded semantic coverage (current milestone)

The formalization now goes substantially beyond the original local-edit proof.
The following layers are present as separate modules so each contract can be
reviewed independently:

```text
NameResolution.lean
  parser-facing names -> typed semantic IDs

Correspondence.lean
  deterministic molecule/component pairing across a rule arrow

MutationCompiler.lean
  resolved arrow -> explicit structural mutation program

Graph.lean / Species.lean
  connected complexes + runtime-ID-independent graph isomorphism

Filters.lean / ExtendedOperational.lean
  include/exclude context filters, DeleteMolecules/MoveConnected policy,
  product-pattern and product-molecularity validation

Observables.lean
  Molecules/Species count semantics

Stochastic.lean
  whole-channel match multiplicity and MatchOnce/TotalRate distinctions

Propensity.lean
  symbolic channel-propensity contract (per-match versus total-rate meaning)

Hybrid.lean
  whole-complex-only particle -> population conversion

Network.lean
  bounded species-pool network generation modulo graph isomorphism

ReactionNetwork.lean
  canonical reaction edges: rule/direction + reactant/product species indices

Seeds.lean
  deterministic concrete seed-species construction

Protocol.lean
  typed simulation/action protocol instead of string dispatch

BNGIR.lean
  structural semantic interchange envelope with no BNGL reparsing

NFnextIR.lean
  checked semantic-ID -> compact NFnext packing, PatternIR-like lowering,
  and generic TransformationIR-like lowering for the supported subset

MatcherSpec.lean
  independent proposition-level match specification and explicit
  soundness/completeness obligations

Evaluation.lean
  deliberately partial arithmetic/function evaluator; unsupported special
  numerical conventions fail explicitly
```

## Important semantics made explicit

Several details that are easy to lose in an IR rewrite are now represented in
code rather than prose:

* molecules inside one top-level pattern (`.`) must occupy the same connected
  complex;
* different top-level reactants/products (`+`) must occupy different complexes;
* a mentioned site with no bond wildcard is treated as explicitly free where
  that is what the compiled pattern encodes;
* product molecularity is checked after graph edits, so deleting one bond does
  not falsely imply dissociation when another path still connects the products;
* `DeleteMolecules` is distinct from deleting one matched molecule;
* `MoveConnected` is distinct from moving one matched molecule;
* product-only component edits use `.byType` targets instead of inventing a
  nonexistent reactant-side `PatternSiteId`;
* molecule/component correspondence is a compiler artifact, not backend cache
  data;
* species identity ignores runtime allocation IDs and uses molecular graph
  equivalence;
* network generation combines species from a pool, so rules like `A + B -> A.B`
  are representable;
* hybrid population conversion requires a whole connected species match;
* NFnext site/state integers are type-local packing indices, not BNG semantic
  IDs.

## Real C++ NFnext conformance oracle

Run:

```bash
./scripts/validate_all.sh
```

In addition to Lean-source static checks, this compiles a temporary C++ program
against the actual NFnext headers and implementations and checks matcher /
transformation behavior. The current fixture covers state predicates/sets,
free sites, same/different-complex constraints, exact bonds, automorphism
canonicalization, indirect `connected_to`, state edits, all generic bond edit
forms, molecule creation, initial states, molecule destruction, and whole-
complex destruction.

No binary is checked into the repository.

## What is still not a theorem

The formalization is intentionally explicit about the remaining boundary:

1. `lake build` has not run in this packaging environment because Lean/Lake is
   not installed.
2. `ReferenceMatcherCorrect` is a proof obligation; the independent
   proposition-level specification exists, but the full iff proof is not being
   assumed.
3. The C++ repository still lacks one complete production
   `CompiledModel -> nfnext::ModelIR/TransformationIR` boundary matching this
   target architecture. Therefore no theorem claims that current production
   BNG3->NFnext lowering is fully refined.
4. Exact semantics of every special rate law, every builtin/table function,
   and floating-point/numerical backend behavior are not formalized. The
   evaluator is intentionally partial.
5. A fast canonical-label algorithm is not proved correct; graph isomorphism is
   currently a brute-force reference oracle.

These are deliberate trust boundaries, not hidden TODOs.


## Production C++ migration blockers

See `CXX_MIGRATION_BLOCKERS.md` for the exact current C++ seams that prevent a
fully honest production-lowering proof.  The most important are string-bearing
patterns, AST references inside `CompiledRule`, incomplete `CompiledModel`
declarations, and the absence of one complete source-string-free
`CompiledModel -> nfnext::ModelIR` lowering boundary.
