# Findings from formalizing BNG3 semantics

This file records design conclusions produced by trying to make the proposed
BNG3 compiler IR executable enough to define real rule application.

## 1. The target should still be `Document / CompiledModel`, not another model class

The proposed architecture remains the right one:

```text
BNGL -> ast::Model -> compile once -> Document/CompiledModel -> backend lowering
```

The operational formalization strengthens, rather than weakens, the case for a
single resolved backend contract. A matcher/executor needs declaration identity,
patterns, correspondence, and edits in one coherent semantic object.

## 2. A pattern IR needs explicit graph semantics, not just structured printing

Once matching is defined, the requirements become concrete. A pattern must
provide enough information to answer:

- which concrete molecule can satisfy each molecule occurrence?
- which concrete component corresponds to each site occurrence?
- is the requested state exact, set-valued, or unconstrained?
- does `!+`, `!?`, `!-`, or an exact bond group hold?
- what exact graph edge does a bond-group ID denote?
- does a molecule-level bond wildcard hold?

This justifies explicit endpoint and bond structures in Pattern V2.

## 3. Multiple site bond specifications must remain representable

Current BNGL/BNG3 supports sites carrying multiple bond specifications. A single
`BondConstraint` field would lose information.

The Lean representation keeps:

```text
PatternSite.bonds : List BondRequirement
```

A C++ Pattern V2 can choose another layout, but capability must be preserved.

## 4. Matching and rule application are separate semantic operations

This is important architecturally.

A match answers:

```text
"where in this concrete graph does the reactant pattern occur?"
```

Rule application answers:

```text
"given that match, which concrete graph edits happen?"
```

Do not fuse these into one opaque backend operation in the semantic IR. Keeping
them separate enables reference matching, generated match fixtures, and
backend refinement tests.

## 5. Cross-arrow correspondence is required for executable semantics

To apply a product-side mutation to an existing molecule, the semantic layer
must know which reactant molecule survives as that product molecule.

Therefore resolved molecule correspondence is not optional cache data. It is
part of rule meaning.

Likewise, component correspondence or an equivalent resolved transformation map
is needed for product-only component specifications and repeated/symmetric
components.

## 6. Product patterns should not be reinterpreted independently by every backend

The operational formalization executes the **compiled mutation list** rather
than replacing a matched reactant graph wholesale with the product graph.

That is important because BNGL rules preserve unmentioned molecular context.
The compiler should derive the edit program once. NFsim, network generation,
and NFnext should consume that resolved program rather than rediscover edits
from source-like product patterns.

## 7. The minimal five-mutation sketch is insufficient

The first design pass already found required concepts beyond:

```text
ChangeState
CreateBond
DeleteBond
CreateMolecule
DeleteMolecule
```

At minimum the semantic layer also needs homes for:

- clearing all bonds from a component;
- direct compartment movement;
- connected-component movement (`MoveConnected`) or an explicit modifier whose
  operational semantics is centralized;
- complete-species deletion vs matched-molecule deletion distinctions.

The current Lean reference executes `clearBonds` and direct
`moveCompartment`; the more complicated deletion/connected transport semantics
remain intentionally gated out.

## 8. Failure behavior should be explicit

The reference executor returns `Option` rather than silently no-oping invalid
mutations.

Examples:

- deleting a nonexistent exact bond fails;
- mutating a component that cannot be resolved fails;
- creating the same product molecule twice fails;
- creating a duplicate exact bond fails.

C++ does not have to use `std::optional` at runtime, but the semantic contract
should define whether an impossible compiled edit is unreachable, an error, or
a no-op. Different backends should not guess differently.

## 9. New-molecule construction exposes a missing compiler obligation

A product-created molecule needs concrete initial component states. A pattern
constraint like:

```text
state ∈ {u,p}
```

is a matcher constraint, not a unique constructor value.

Therefore the compiler needs a clear invariant for product-created molecules:
creation templates must determine concrete initial state values (or define a
separate nondeterministic semantics, which would be surprising for BNGL).

The Lean reference currently accepts exact states, singleton state sets, or an
unselected state and rejects genuinely multi-valued construction.

## 10. Concrete graph identity is distinct from pattern occurrence identity

Pattern IDs identify syntactic/semantic occurrences inside one pattern. Runtime
IDs identify actual molecule instances in a mixture.

They should never be the same type.

The operational semantics uses:

```text
PatternMoleculeId     -- occurrence in a pattern
MoleculeInstanceId    -- concrete molecule in a mixture
Embedding             -- mapping between them
```

This type distinction is worth preserving conceptually in C++.

## 11. A slow reference matcher is valuable even if never used in production

The brute-force Lean matcher is intentionally inefficient. That is a feature for
its role.

It can serve as an oracle for small generated fixtures:

```text
random small mixture + pattern
        ↓
reference embeddings
        vs
NFsim/NFnext/network matcher embeddings
```

This is a strong use of modern AI/property-testing capability: generate many
weird but valid graphs and compare optimized matching against an obvious
reference.

## 12. The first backend theorem is now meaningful but still not NFsim correctness

The project now has a distinct backend action vocabulary and proves:

```text
execute(lower(mutation)) = executeReference(mutation)
```

for one mutation, arbitrary mutation lists, and the public supported rule-step
function.

That establishes the proof architecture. It does **not** prove that current
NFsim or NFnext implements `BackendAction` correctly.

The next bridge must connect a real backend representation to this vocabulary or
directly to the semantic rule.

## 13. NFnext is probably the best first real refinement target

A typed NFIR/ActionIR is structurally closer to this formal backend language than
legacy NFsim's transformation machinery.

A practical sequence is:

```text
CompiledRule subset
  ↓ C++ lowerToNFIR
NFIR predicates/actions
  ↓ execute on small graph
result
```

and compare/prove that against the Lean reference step.

Once that pattern works, use the same semantic fixtures to test NFsim lowering.

## 14. `DeleteMolecules` / complete-species deletion is a high-risk semantic target

Inspection of the current C++ code shows substantial special handling around:

- `-> 0`;
- `DeleteMolecules`;
- matched molecules versus entire connected species;
- orphan fragments;
- symmetry-related deletion cases.

This is exactly the kind of behavior that should **not** be compressed into an
underspecified generic `deleteMolecule` operation.

It should be one of the first feature expansions after the basic real-backend
refinement works.

## 15. `MoveConnected` is another high-risk target

Current C++ contains explicit logic for transporting connected cargo and for
interactions with orphan fragments. The first formal operational subset only
implements direct movement of one molecule.

The semantic IR should either compile `MoveConnected` into explicit connected
movement operations or give the modifier one authoritative operational
semantics before backend lowering.

## 16. Symmetry/multiplicity remains outside this graph-edit theorem

Two rule implementations can produce the same graph edit yet assign different
propensities because of automorphisms, reaction-path degeneracy, or reactant
multiplicity.

Therefore "one-step graph refinement" is necessary but not sufficient for full
stochastic semantic equivalence.

A later theorem/test layer must separately address:

```text
same legal matches
same multiplicity / symmetry correction
same propensity
same graph transformation
```

## 17. Formalization is most useful here as a language/backend contract

This exercise continues to support the earlier conclusion:

**Need**

- stable typed CompiledModel;
- one explicit semantic rule contract;
- differential/property tests;
- architecture boundaries;
- parity across backends.

**Useful formal-methods layer**

- executable reference matcher;
- explicit reference rule application;
- machine-checked lowering/refinement for high-risk cases.

**Likely detractor**

- formalizing every grammar quirk;
- formalizing biological truth;
- proving numerical integrators before semantic backend convergence;
- making Lean a runtime dependency.

## 18. `.` and `+` are graph semantics, not formatting

Formal matching exposed a critical distinction:

```text
A.B     -> molecules must be in the same connected complex
A + B   -> top-level reactants must be in different complexes
```

The same requirement applies to products.  A dissociation rule cannot be
accepted merely because one bond was deleted; if another path keeps the product
patterns connected, the advertised `A + B` product molecularity is not met.

NFnext lowering therefore needs explicit `SameComplex` constraints within a
flattened top-level pattern and `DifferentComplex` constraints across top-level
reactants.

## 19. Semantic IDs cannot be emitted directly as NFnext site/state integers

NFnext's current C++ representation stores site indices local to one molecule
type and state indices/values local to one site. BNG semantic IDs are global
typed identities.

Therefore this is wrong in principle:

```text
ComponentTypeId.value -> PatternIR::site
StateId.value         -> PatternIR::state
```

without an explicit packing map. `NFnextPacking` now makes the conversion
checked and reviewable.

## 20. Product validation belongs in the reference step

Executing a mutation list successfully is weaker than satisfying the declared
product graph.  The extended reference semantics therefore reconstructs the
product-side embedding from compiled correspondence/created molecules and
checks the product patterns and product molecularity after editing.

This catches ring/path cases and correspondence bugs that an edit-only oracle
would miss.

## 21. Population conversion must require a whole-species match

A population map for `A(x)` must not consume the A subgraph out of
`A(x!1).B(y!1)` and leave B behind.  The formal hybrid semantics requires the
particle-pattern embedding to cover the entire connected component before
collapsing it into a population count.

## 22. Network generation is a species-pool closure, not a trajectory

A reference network generator must combine separate pool species for
multimolecular rules.  Modeling network generation as repeated execution from
one seed state cannot generate `A.B` from separate A and B species.

The new bounded reference generator chooses one pool species per top-level
reactant, clones those species into disjoint runtime-ID ranges, fires the rule,
splits the result into connected product species, and deduplicates modulo graph
isomorphism.

## 23. Runtime allocation IDs cannot define generated-species identity

`A#1.B#2` and `A#40.B#41` are the same generated species if their typed
molecular graphs are isomorphic.  The formal layer now contains a brute-force
runtime-ID-independent graph-isomorphism oracle specifically for checking fast
canonicalization implementations.

## 24. Real NFnext contract testing is practical today

A small C++ fixture now compiles directly against current NFnext
`GenericMatcher`, `GenericGraphState`, and `TransformationIR` implementation.
It currently passes 18/18 semantic checks.  This is exactly the useful middle
ground between "prove all legacy C++" and "trust unit tests that restate the
implementation".

## 25. Formalization is finding design bugs before proving anything deep

The exercise has already forced explicit treatment of:

- product-only component edits;
- exact-vs-clear bond deletion;
- `.`/`+` molecularity;
- product molecularity after ring/path edits;
- type-local NFnext packing;
- connected deletion/movement;
- species identity modulo runtime IDs;
- whole-species population conversion;
- whole-channel stochastic multiplicity rather than one hazard per match.

That design-audit value is likely the highest-return use of Lean during BNG3's
IR migration even before the deeper backend-refinement proofs are completed.
