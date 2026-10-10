# Proof roadmap for BNG3

The goal is not "prove BioNetGen all at once." The goal is to spend formal
methods where independent backend implementations could silently disagree.

The current continuation adds a bounded bridge checkpoint: the Lean example
and production C++ architecture contract both lower
`A(x~u) + B(y) -> A(x~p!1).B(y!1) k`, while the C++ side crosses BNGL parsing,
`CompiledModel`, and `nfnext::lowerFromBioNetGen`. This gives a concrete
regression seam for one rule; it does not close the broader refinement or
kernel-verification work below.

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

## Stage 4 — Lean kernel validation: IMPLEMENTED

The pinned Lean 4.33.1 workflow builds the `BNG/**` library, runs
`tests/Smoke.lean` and `tests/Coverage.lean` explicitly, and audits named axiom
dependencies. The package's default Lake target does not include either test
file, so the explicit commands are required. A weekly/manual run also mutates
scratch copies to verify that the harness gates reject representative defects.

These checks validate Lean declarations and executable fixtures within their
stated trust boundaries. They do not prove that production C++ implements the
Lean reference semantics; see `VALIDATION.md` and `CXX_MAPPING.md` for the
separate native-test evidence and remaining correspondence boundary.

## Stage 5 — connect Boolean checks to propositions: DONE FOR LEAN REFERENCE MATCHER

PR [#194](https://github.com/RuleWorld/BNG3/pull/194) merged into `main` at
`c3b20f3e4a863300ac79dc9dfe71f0b406b6eda6` on 2026-10-09. It proves
`BNG.embeddingMatches_iff_EmbeddingSpec` and soundness/completeness of the Lean
reference enumerator. Completeness compares node lookups independently of
association-list order, and `EmbeddingSpec` requires the exact duplicate-free
pattern occurrence domain. The theorems retain all-input quantification without
a hidden well-formed-input premise.

This closes the proposition-level matcher obligation for the Lean reference
implementation only. Production C++ matcher/lowering correspondence remains
separate work (#166).

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
- structural BNGIR v0.2 semantic envelope: IMPLEMENTED, extended to the
  multi-version (0.1/0.2) decode contract with format check and fail-closed
  feature gating;
- standard Molecules/Species observable counting: IMPLEMENTED;
- stochastic whole-rule multiplicity + MatchOnce/TotalRate distinction:
  IMPLEMENTED at the combinatorial-contract level;
- parser-facing name resolution for expressions/patterns: IMPLEMENTED;
- NFnext compact-ID packing + proof-friendly Pattern/Transformation lowering:
  IMPLEMENTED for the capability-gated subset;
- real C++ NFnext matcher/transformation conformance harness: IMPLEMENTED and
  passing 18/18 checks in this environment.

The highest-priority remaining work is:

1. qualify production C++ `CompiledModel -> NFnext` correspondence beyond the
   bounded declaration-ID and field-width checks merged in PR
   [#198](https://github.com/RuleWorld/BNG3/pull/198) at
   `2038e18693e29a0c646c723998d7a59d737b8cff`. The merge adds preflight and a
   parser-to-lowering bridge case; it does not prove general
   pattern/rate/bond/transformation refinement;
2. prove/test a production species canonicalizer against the brute-force graph
   isomorphism oracle;
3. formalize exact special-rate/local-function/builtin conventions that are
   actually used by supported backends;
4. extend stochastic refinement from channel multiplicity to complete
   propensities and event selection;
5. add generated differential fixtures across BNG3 network generation, NFsim,
   and NFnext.
