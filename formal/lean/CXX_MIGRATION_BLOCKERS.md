# C++ migration blockers revealed by the Lean semantics

This note records places where the formal semantic target is more precise than
BNG3's **current** transitional C++ compile layer.  These are not reasons to
weaken the formalization.  They are the concrete tasks required before one can
honestly prove that production C++ lowering preserves the semantic model.

Reviewed 2026-10-07 at [main `e1836c32`](https://github.com/RuleWorld/BNG3/tree/e1836c3274e685996d5e86883761e00e98257e09).
The remaining work is tracked in issues [#138–#143](https://github.com/RuleWorld/BNG3/issues/138),
[#147–#148](https://github.com/RuleWorld/BNG3/issues/147), and
[#166](https://github.com/RuleWorld/BNG3/issues/166); those issues own scope and
acceptance. Existing typed declarations and endpoints are foundations, not
missing implementations or proof of complete backend refinement.

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

The C++ [CompiledModel](../../cpp/compile/CompiledModel.hpp) now owns those
declaration families, including resolved expressions, typed patterns, energy
factors and population metadata. The remaining gap is consumer migration:
[LegacyNetworkRuleKernel](../../cpp/engine/LegacyNetworkRuleKernel.cpp) still
constructs an AST execution rule. The
[compatibility allowlist](../../provenance/architecture/ast_compat_allowlist.txt)
records remaining dependencies; its current count and evidence revision live in
[CURRENT_PROGRESS.md](../../docs/CURRENT_PROGRESS.md). The audited allowance was
43 entries, and the compile-owned unit/export migration in #196 reduced it to 41; declaration storage alone does not remove them.

**Required migration:** move remaining consumers to the resolved model and
retire each compatibility path after parity (#138–#139).

## 2. `Pattern` still carries executable meaning in strings

The current [PatternDescriptor.hpp](../../cpp/compile/PatternDescriptor.hpp)
defines `Pattern` with typed occurrence IDs, optional resolved semantic IDs,
explicit bond kinds/groups and `PatternStateConstraint`. `PatternDescriptor`
is a compatibility alias; [Pattern.hpp](../../cpp/compile/Pattern.hpp) includes
that definition. Human-readable names remain for diagnostics and round trips.
The formal model uses:

- `MoleculeTypeId`
- `ComponentTypeId`
- `StateId`
- `CompartmentId`
- explicit state/bond constraint variants
- explicit graph bonds

**Required migration:** make remaining consumers use the resolved constraints
and IDs instead of compatibility spellings (#138), rather than adding another
typed pattern representation.

## 3. Typed rule directions exist; execution migration remains

[CompiledRule.hpp](../../cpp/compile/CompiledRule.hpp) now uses `PatternSiteRef`
and `PatternMoleculeRef` in `MutationSignature`, with a resolved `StateId` when
available. `CompiledRuleDirection` carries separately compiled forward/reverse
patterns, rates, mutations, filters and local scopes. AST component references
are no longer the mutation endpoint contract.

The formal layer instead stores typed reactant/product endpoints plus explicit
molecule/component correspondence and an already-derived mutation program.

**Required migration:** eliminate the remaining AST reconstruction in execution
and qualify the typed directions, including incomplete transformation programs
that still require a declared compatibility route (#139).

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

Candidate PR [#198](https://github.com/RuleWorld/BNG3/pull/198) at
`5cc1fd576a0d4aff7a75ee8a10af2d827e979ebd` adds a production preflight for
canonical declaration positions and NFIR v5 field widths, plus a parser-to-
lowering contract that rejects component index 65,536. This is bounded
candidate evidence for ID packing; the PR remains unmerged, so it is not current
`main` behavior. Its checks cover the named molecule-rule graph subset and do
not prove general pattern, rate, bond, or transformation refinement. The
[candidate CXX mapping](https://github.com/RuleWorld/BNG3/blob/5cc1fd576a0d4aff7a75ee8a10af2d827e979ebd/formal/lean/CXX_MAPPING.md#issue-166-production-declaration-to-nfnext-id-packing)
records the tested boundary.

**Remaining migration:** retain fail-closed packing checks and qualify the
production/reference correspondence beyond this bounded candidate slice (#166).

## 8. Backend parity needs an actual production lowering seam

The formal project can already compare a semantic rule with an independent
NFnext-like interpreter, and the C++ conformance harness checks the real
GenericMatcher/Transformation implementation. The production function now
exists in [from_bng.cpp](../../cpp/nfnext/src/from_bng.cpp):

```text
CompiledModel
             ->
        nfnext::ModelIR
```

whose entire input is the source-string-free compiled semantic object.

`nfnext::lowerFromBioNetGen(const bng::compile::CompiledModel&)` consumes the
compiled object and rejects unsupported constructs. Its restricted supported
surface and concrete production fixtures do not establish general lowering
correspondence or a complete execution boundary. Those remain #147–#148 and
[#166](https://github.com/RuleWorld/BNG3/issues/166).

## Recommended C++ order

```text
1. Migrate execution consumers to existing compiled declarations and typed patterns.
2. Retire AST rule reconstruction after independent parity.
3. Qualify rate-law and local-function semantics across backends.
4. Extend the existing fail-closed NFnext lowering for approved capabilities.
5. Qualify initial state, observables, protocol and output semantics.
6. Establish production/reference correspondence beyond concrete fixtures.
```

This is intentionally the same architectural direction as the original BNG3
migration proposal; the formalization has simply made the hidden edge cases
more concrete.
