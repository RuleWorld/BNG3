# Proof roadmap for BNG3

The goal is not "prove BioNetGen all at once." The goal is to spend formal
methods where independent backend implementations could silently disagree.

## Stage 0 — semantic vocabulary: DONE

Implemented:

- typed declaration IDs;
- structured expressions;
- semantic patterns;
- compiled forward/reverse rule directions;
- explicit correspondence and mutations;
- completed `CompiledModel` shape;
- executable well-formedness checks.

## Stage 1 — concrete mixture + pattern matching: IMPLEMENTED FOR CORE SUBSET

Implemented in `BNG/Runtime.lean` and `BNG/Operational.lean`:

- concrete molecule-instance IDs;
- concrete sites/states;
- explicit undirected concrete bonds;
- concrete mixture structural checks;
- candidate pattern embeddings;
- exact type/compartment/state checking;
- free/bound/any/exact-bond predicates;
- molecule-level bond predicate;
- brute-force enumeration of valid embeddings;
- non-overlapping whole-rule matches.

Still needed here:

- proposition-level soundness/completeness theorems for the Boolean matcher;
- explicit automorphism/equivalence treatment for embeddings;
- connected-component/species semantics;
- formal relation to current BNG/NFsim matcher behavior.

## Stage 2 — rule application: IMPLEMENTED FOR LOCAL GRAPH-EDIT SUBSET

Implemented:

- state change;
- exact bond creation;
- exact bond deletion;
- clear-all-bonds on one site;
- molecule creation;
- molecule deletion + incident-bond cleanup;
- direct molecule compartment movement;
- resolution of product-side addresses through compiled correspondence;
- sequential mutation programs with explicit failure.

The public theorem-backed subset currently requires no filters, local scopes, or
modifiers.

Still needed:

- full `DeleteMolecules` semantics;
- ordinary complete-species deletion;
- `MoveConnected`;
- product creation invariants for all legal BNGL forms;
- filters;
- component correspondence cases that cannot be represented by simple resolved
  component type lookup.

## Stage 3 — abstract backend refinement: IMPLEMENTED

`BNG/Lowering.lean` now defines an independent `BackendAction` vocabulary and
proves:

```text
execute(lower(single mutation)) = reference single mutation
```

then by induction:

```text
execute(lower(mutation list)) = reference mutation list
```

and finally:

```text
executeLoweredAt?(rule, mixture, match)
=
applyAt?(rule, mixture, match)
```

for the current supported feature gate.

This is the first substantive refinement theorem in the project.

## Stage 4 — kernel validation: IMMEDIATE BLOCKER

Before treating any theorem as trusted:

```bash
lake build
lake env lean tests/Smoke.lean
```

must succeed under the pinned Lean toolchain.

The packaging environment currently lacks Lean, so this stage must happen in CI
or on a developer machine.

## Stage 5 — connect Boolean checks to propositions

Define proposition-level relations such as:

```text
EmbeddingIsMatch p mix e
WellFormedMixture sig mix
WellFormedRule sig scope d
```

and prove executable checker correspondence, e.g.:

```text
p.embeddingMatches mix e = true
↔
EmbeddingIsMatch p mix e
```

This matters before deeper proofs depend heavily on Boolean validators.

## Stage 6 — canonical semantic interchange

Add a canonical structural export of the C++ `CompiledModel` / `CompiledRule`
subset.

Targets:

```text
C++ export contains no execution-critical unresolved names.
encode/decode preserves semantic equality.
source spelling does not affect canonical semantic serialization.
```

This can evolve into structural BNGIR v0.2 once the semantic object is stable.

## Stage 7 — first REAL backend refinement: NFnext recommended

Mirror only the relevant NFnext types in Lean:

```text
PatternIR
PredicateIR
ActionIR
```

Then relate the actual C++ lowering contract to the reference semantics.

Desired theorem/test shape:

```text
well-formed CompiledRule subset
+ valid match
      ↓
reference apply
      =
CompiledRule -> NFIR -> NFIR execute
```

This is higher-value than growing the abstract Lean backend further.

## Stage 8 — generated differential/property testing

Use the reference matcher/executor as an oracle for thousands of tiny generated
cases:

```text
generate legal declarations
→ generate small mixtures
→ generate legal patterns/rules
→ compare reference matches/results to NFnext/NFsim
```

This is where AI/code-generation capability can make the formal semantics
practically useful without proving every line of legacy C++.

## Stage 9 — high-risk BNGL semantics

Add in approximately this order:

1. `DeleteMolecules` vs complete-species deletion;
2. `MoveConnected`;
3. product-only component/bond clearing edge cases;
4. include/exclude filters;
5. local functions and local scopes;
6. compartments/transport adjacency/inference;
7. state sets in all construction/matching contexts;
8. population species;
9. special rate laws.

Each feature should arrive with real BNG2/BNG3/NFsim parity fixtures.

## Stage 10 — symmetry, multiplicity, and stochastic propensity

Graph-edit equality is not enough for stochastic equivalence.

Formalize/check:

```text
match equivalence classes
reaction-path degeneracy
automorphism corrections
reactant multiplicity
propensity calculation
```

Then state a stronger one-event theorem that includes both selected graph edit
and propensity.

## Stage 11 — finite network-generation equivalence

For a bounded subset with finite reachable state space, relate repeated
reference rule application to generated reaction-network edges.

This is mathematically attractive but should come after real backend refinement
because it is much larger in scope.

## Stage 12 — optional CRNT bridge

Only after a finite reaction-network projection has an explicit semantic
contract should CRNT tooling enter:

```text
BNG3 semantics
→ finite explicit CRN projection
→ CRNT analysis
```

CRNT remains downstream; it should not define BNGL semantics.

---

# Current milestone update

Several items originally listed as later stages now have executable reference
implementations:

- connected-component semantics: IMPLEMENTED;
- independent proposition-level matcher spec: IMPLEMENTED;
- explicit matcher soundness/completeness obligations: IMPLEMENTED;
- deterministic molecule/component correspondence inference: IMPLEMENTED;
- structural mutation derivation from correspondence: IMPLEMENTED for the
  represented subset;
- filters + product validation: IMPLEMENTED reference semantics;
- `DeleteMolecules` / `MoveConnected`: IMPLEMENTED as explicit reference-policy
  behavior, still requiring production-backend parity decisions;
- runtime-ID-independent species graph isomorphism: IMPLEMENTED brute-force
  oracle;
- safe whole-complex population conversion: IMPLEMENTED;
- bounded species-pool network generation: IMPLEMENTED;
- typed simulation protocol: IMPLEMENTED;
- structural BNGIR v0.2 semantic envelope: IMPLEMENTED;
- standard Molecules/Species observable counting: IMPLEMENTED;
- stochastic whole-rule multiplicity + MatchOnce/TotalRate distinction:
  IMPLEMENTED at the combinatorial-contract level;
- parser-facing name resolution for expressions/patterns: IMPLEMENTED;
- NFnext compact-ID packing + proof-friendly Pattern/Transformation lowering:
  IMPLEMENTED for the capability-gated subset;
- real C++ NFnext matcher/transformation conformance harness: IMPLEMENTED and
  passing 18/18 checks in this environment.

The highest-priority remaining work is now narrower:

1. kernel-build every Lean file under the pinned toolchain;
2. prove `Pattern.embeddingMatches = true <-> EmbeddingSpec`;
3. connect the actual production C++ `CompiledModel -> NFnext` lowering to the
   checked packing/lowering contract;
4. prove/test a production species canonicalizer against the brute-force graph
   isomorphism oracle;
5. formalize exact special-rate/local-function/builtin conventions that are
   actually used by supported backends;
6. extend stochastic refinement from channel multiplicity to complete
   propensities and event selection;
7. add generated differential fixtures across BNG3 network generation, NFsim,
   and NFnext.
