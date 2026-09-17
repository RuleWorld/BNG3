# C++ migration blockers revealed by the Lean semantics

This note records places where the formal semantic target is more precise than
BNG3's **current** transitional C++ compile layer.  These are not reasons to
weaken the formalization.  They are the concrete tasks required before one can
honestly prove that production C++ lowering preserves the semantic model.

## ELI15 summary

The Lean side now describes the model using stable IDs and explicit graph
operations.  Some C++ compile objects still say things like "component named
`x`" or keep a pointer/reference back into the parser AST.

That is like a compiler's machine-code backend asking the source-code parser
what a variable meant.  It can work, but it prevents one clean semantic
boundary and makes independent backends more likely to disagree.

The continuation now tests a small exception to this missing complete boundary:
a production C++ contract lowers one parsed rule through
`CompiledModel -> nfnext::lowerFromBioNetGen` and checks its molecularity, state,
and bond actions. This is useful regression coverage, but it does not remove
the blockers below or establish a complete source-free production lowering.

## 1. `CompiledModel` is not yet the whole resolved model

The formal `CompiledModel` owns parameters, molecule/component/state
declarations, compartments, seeds, observables, functions, energy factors,
population maps, and rules.

Current C++ `cpp/compile/CompiledModel.hpp` is still missing several of those
resolved declaration families.  Until they are owned by the compiled model, a
backend cannot be constructed solely from the canonical semantic object.

**Required migration:** complete `bng::compile::CompiledModel` before treating it
as the production proof boundary.

## 2. `Pattern` still carries executable meaning in strings

Current `PatternDescriptor.hpp` retains molecule/component/state/compartment
names and textual bond/state constraints.  The formal model instead uses:

- `MoleculeTypeId`
- `ComponentTypeId`
- `StateId`
- `CompartmentId`
- explicit state/bond constraint variants
- explicit graph bonds

**Required migration:** implement the proposed typed Pattern V2 and keep source
text only as provenance/diagnostics.

## 3. `CompiledRule` still leaks AST component references

Current `CompiledRule::MutationSignature` uses
`ast::ReactionRule::ComponentRef` for mutation endpoints.  That means the
compile layer has not fully severed rule execution from parser representation.

The formal layer instead stores typed reactant/product endpoints plus explicit
molecule/component correspondence and an already-derived mutation program.

**Required migration:** replace AST component references with compile-layer
endpoint IDs and compile forward/reverse rule meaning once.

## 4. Rate-law classification is ahead of rate-law semantics

C++ currently classifies special rate forms (`Sat`, `MM`, `Hill`,
`FunctionProduct`, `Hybrid`, Arrhenius/energy) and resolves ordinary expression
references, but several execution semantics remain backend/legacy specific.

The formal evaluator therefore intentionally returns failure for special forms
whose exact contract has not been encoded.

**Required migration:** define one semantic contract for each special rate form
before proving backend numerical refinement.

## 5. Local functions need more semantic metadata

NFsim distinguishes molecule-scoped and species/complex-scoped local functions
and maintains dependency/caching machinery.  The current compile IR does not
fully describe all of that behavior independently of NFsim.

A proof layer should not reverse-engineer NFsim caches and call that the BNGL
language definition.

**Required migration:** decide the language-level local-function semantics
(scope, anchor, legal observable dependencies, evaluation timing), encode them
in the compiled IR, then prove NFsim implements that contract.

## 6. Generic NFnext cannot represent every compiled mutation directly

The current generic NFnext `TransformationIR` directly supports:

- `SetState`
- `AddBond`
- `DeleteBond`
- `CreateMolecule`
- existing-to-created bonds
- created-to-created bonds
- `DestroyMolecule`
- `DestroyComplex`

It does **not** directly encode every semantic operation represented by the
formal BNG layer, notably generic bond clearing and compartment movement.
Product-only by-type edits also require resolution before generic lowering.

**Required migration:** capability-gate lowering and reject unsupported
semantics rather than approximate them silently.

## 7. NFnext compact indices are not BNG semantic IDs

NFnext site/state integers are indices local to a molecule type's compact
schema.  They are not globally meaningful `ComponentTypeId` or `StateId`
values.

The formal `NFnextPacking` layer exists specifically to make this conversion
checked and explicit.

**Required migration:** production lowering must own an equivalent packing map
and test it at the boundary.

## 8. Backend parity needs an actual production lowering seam

The formal project can already compare a semantic rule with an independent
NFnext-like interpreter, and the C++ conformance harness checks the real
GenericMatcher/Transformation implementation.  What does not yet exist is the
single production function:

```text
CompiledModel / CompiledRule
             ->
        nfnext::ModelIR
```

whose entire input is the source-string-free compiled semantic object.

Until that exists, a theorem claiming complete BNG3 -> NFnext refinement would
be dishonest.

## Recommended C++ order

```text
1. Complete CompiledModel declarations.
2. Replace Pattern strings with typed semantic IDs/constraints.
3. Remove AST refs from CompiledRule mutations/correspondence.
4. Compile reversible directions completely once.
5. Add CompiledModel -> NFnext lowering with an explicit packing context.
6. Feed lowering fixtures to this formal/reference harness.
7. Only then promote lowering/refinement obligations to CI gates.
```

This is intentionally the same architectural direction as the original BNG3
migration proposal; the formalization has simply made the hidden edge cases
more concrete.
