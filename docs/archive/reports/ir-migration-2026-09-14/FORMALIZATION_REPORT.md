# BNG3 Lean formalization — expanded milestone report

## Scope

This package extends the experimental Lean 4 semantic/reference layer for BNG3.
It is **not CRNT-Lean** and does not attempt to prove biological models true.
Its purpose is to define the language/compiler/backend contract precisely enough
that optimized BNG3 backends can be tested or selectively proved against one
reference meaning.

The architecture remains:

```text
BNGL
  -> ast::Model                    parser/editing compatibility layer
  -> compile / resolve exactly once
  -> Document
       - CompiledModel             canonical semantic backend contract
       - SimulationProtocol
  -> backend lowering
       - network generation
       - NFsim
       - NFnext
```

## What is implemented in this milestone

### Semantic compiler boundary

- strongly typed declaration IDs;
- resolved expression trees;
- parser-facing expression name resolution;
- parser-facing pattern name resolution for molecule/component/state/compartment names;
- semantic pattern graphs;
- deterministic molecule correspondence across rule arrows;
- component correspondence with tag-aware matching;
- creation/deletion detection;
- structural mutation derivation:
  - state change;
  - exact bond creation/deletion;
  - clear-bonds for product-only/free component edits;
  - molecule creation/deletion;
  - direct compartment transport;
- explicit forward/reverse direction representation.

### Operational molecular-graph semantics

- concrete molecule instances and sites;
- explicit undirected bonds;
- connected-component traversal;
- same-complex semantics;
- brute-force pattern embeddings;
- `.` same-complex semantics;
- `+` different-complex reactant semantics;
- exact/free/bound/state/state-set predicates;
- explicit whole-rule matches;
- semantic mutation execution;
- connected-complex delete/move helpers;
- modifier-aware reference execution for `DeleteMolecules`/`MoveConnected` policy;
- include/exclude contextual filters;
- product-pattern validation after mutation;
- product `+` molecularity validation after mutation.

### Observable/stochastic/model-execution contracts

- Molecules observable counts;
- Species observable counts using whole-complex matching;
- whole-rule stochastic match multiplicity;
- explicit `MatchOnce` counting layer;
- explicit `TotalRate` distinction;
- symbolic channel propensity contract separating per-match versus total-channel interpretation;
- deterministic seed-species construction;
- typed simulation protocol;
- deliberately partial arithmetic/function evaluation with explicit unsupported cases.

### Species/network/hybrid semantics

- runtime-ID-independent brute-force species graph isomorphism;
- species-pool deduplication modulo graph isomorphism;
- safe particle->population conversion requiring whole connected species coverage;
- bounded reference network generation as a species-pool closure;
- multimolecular rules are evaluated by cloning selected pool species into disjoint runtime-ID ranges;
- generated product mixtures are split back into connected product species;
- canonical reaction edges record rule direction plus reactant/product species-pool indices.

### Structural interchange

- structural BNGIR v0.2 semantic envelope;
- encode/decode round-trip theorem at the semantic-object level;
- no BNGL reparsing in structural decode.

### NFnext contract

- proof-friendly mirror of current generic PatternIR/TransformationIR concepts;
- explicit semantic-ID -> type-local compact NFnext packing;
- state/state-set/free/bound constraints;
- SameComplex/ DifferentComplex lowering;
- exact reactant bond lowering;
- created-molecule table;
- supported generic transformation lowering for:
  - SetState;
  - AddBond;
  - DeleteBond;
  - CreateMolecule;
  - AddBondExistingToCreated;
  - AddBondCreated;
  - DestroyMolecule;
- capability/rejection matrix for unsupported semantics such as clear-bonds,
  compartment movement, filters/local scopes/modifiers, and product-only edits.

### Formal proof architecture

- source text erasure invariant;
- pattern-lowering size invariants;
- abstract backend action refinement for single mutation, mutation list, and supported rule step;
- independent proposition-level `EmbeddingSpec`;
- explicit `MatcherSound` and `MatcherComplete` proof obligations;
- structural BNGIR round-trip theorem;
- no `sorry`, `admit`, or `axiom` placeholders.

## Design findings produced by the formalization

The work identified several semantic requirements that should influence the C++ target IR:

1. Site bond constraints must preserve multiple simultaneous specifications.
2. Molecule-level bond wildcards are separate semantics.
3. Product-only components require `.byType` mutation targets.
4. `clearBonds` is not equivalent to deleting one named bond.
5. `DeleteMolecules` is not equivalent to deleting one matched molecule.
6. `MoveConnected` is not equivalent to moving one matched molecule.
7. `.` and `+` are connected-component constraints, not formatting.
8. Product molecularity must be validated after graph edits; deleting one edge may not disconnect a ring.
9. Molecule/component cross-arrow correspondence belongs in the compiled rule.
10. NFnext site/state integers are type-local packing indices, not BNG semantic IDs.
11. Runtime molecule IDs cannot define generated species identity.
12. Hybrid population conversion must require whole-species matching.
13. Network generation is a closure over a species pool, not a single-state trajectory.
14. Stochastic propensity semantics must count legal whole-rule matches rather than assign a full channel hazard independently to every embedding.

## Real C++ conformance validation

The package contains `formal/lean/cpp_contract/nfnext_contract.cpp` and a script
that compiles it against the repository's actual NFnext implementation.

Current result:

```text
NFNEXT CONTRACT PASS: 18/18 checks
```

The fixture exercises matcher and transformation behavior including states,
state sets, free sites, same/different complex, exact bonds, automorphism
canonicalization, indirect `connected_to`, state editing, bond add/delete,
creation, existing-created/created-created bonds, molecule deletion,
whole-complex deletion, and initial created states.

## Validation status

Run:

```bash
cd BNG3-main/formal/lean
./scripts/validate_all.sh
```

Current result in this environment:

```text
STATIC VALIDATION PASSED (36 Lean files checked)
NFNEXT HEADER CONTRACT PASS
NFNEXT CONTRACT PASS: 18/18 checks
LEAN KERNEL CHECK SKIPPED: lake is not installed
```

Formal source size:

```text
36 Lean files
4639 lines of Lean source
```

### Important limitation

The environment does not contain Lean/Lake/Elan, so this package has **not**
been kernel-built. Static checks and real C++ NFnext checks are not a substitute
for Lean typechecking.

Mandatory external gate:

```bash
cd formal/lean
lake build
lake env lean tests/Smoke.lean
```

under the pinned:

```text
leanprover/lean4:v4.33.1
```

Until that succeeds, theorem source should be described as authored/formalized,
not as kernel-verified.

## Production C++ migration blockers

`formal/lean/CXX_MIGRATION_BLOCKERS.md` now records the concrete reasons a full
production refinement theorem would be premature: the current C++
`CompiledModel` is incomplete, compile-layer patterns still retain executable
string semantics, `CompiledRule` mutations still leak AST component references,
local/special-rate semantics are not fully represented independently of legacy
backends, and there is not yet one source-string-free
`CompiledModel -> nfnext::ModelIR` production lowering seam.

## What remains genuinely unfinished

The remaining work is narrower than the initial project, but still important:

1. kernel compile and fix any Lean type/elaboration issues;
2. prove `Pattern.embeddingMatches = true <-> EmbeddingSpec`;
3. prove/test a production species canonicalizer against the brute-force graph-isomorphism oracle;
4. implement the production C++ `CompiledModel -> nfnext::ModelIR/TransformationIR` boundary and connect it to the checked lowering contract;
5. define exact semantics for special rate laws/builtins/table functions/local functions that backends actually support;
6. extend stochastic semantics from match multiplicity to complete numerical propensities/event selection;
7. add generated differential/property tests against NFsim/network generation/NFnext;
8. settle/document intentional `MoveConnected` semantics where current engines differ;
9. move current C++ transitional string/AST fields out of the compiled backend contract as the BNG3 IR migration proceeds.

The most important point is that these limitations are explicit: unsupported
semantics fail or remain named proof obligations rather than being silently
assumed correct.
