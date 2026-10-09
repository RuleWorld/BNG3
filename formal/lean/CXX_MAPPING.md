# Mapping between the Lean semantic kernel and BNG3 C++

This file is a migration aid.  It is not a demand that C++ copy Lean field names
exactly.

| Lean | Current/proposed BNG3 concept | Notes |
|---|---|---|
| `CompiledModel` | `bng::compile::CompiledModel` | Both are semantic model boundaries; the Lean and C++ models remain independently implemented. |
| `Document` | `bng::compile::Document` | Keeps simulation protocol separate from reusable model semantics. |
| `ParameterDecl` | proposed `CompiledParameter` | Expression is already resolved. |
| `MoleculeType` | `CompiledMoleculeType` | Contains typed component declarations. |
| `ComponentType` | `CompiledComponentType` | Owns the molecule-local component ID and ordered allowed state names. |
| `StateDecl` | `CompiledComponentType::stateNames` plus resolved `StateId` | State IDs carry their owning component and declaration-local index. |
| `CompartmentDecl` | proposed `CompiledCompartment` | Parent is an ID; size is a resolved expression. |
| `Pattern` | proposed `PatternV2` / current `compile::Pattern` | Lean preserves multi-bond and molecule-wildcard cases. |
| `PatternMoleculeId` | proposed `PatternMoleculeId` | Pattern-local occurrence identity. |
| `PatternSiteId` | proposed `PatternSiteId` | Molecule-local occurrence identity; combine with molecule ID for a unique endpoint. |
| `StateConstraint` | proposed state constraint variant | `any`, `exact`, `oneOf`. |
| `BondRequirement` | proposed bond constraint, expanded | List-valued per site to preserve `!0!1`. |
| `Expr` | `ResolvedExpression` target | No unresolved global name constructor. |
| `UnaryOp`/`BinaryOp`/`Builtin` | proposed enum operators | Replaces `ResolvedExpression.operation` strings. |
| `RateLaw` | `CompiledRateLaw` target | Source text is intentionally outside semantics. |
| `RuleDirection` | proposed `RuleDirection` | Adds correspondence and local-scope data. |
| `CompiledRule.forward/reverse` | proposed canonical directions | Reverse semantics compiled once. |
| `MoleculeCorrespondence` | current AST `moleculeMappings_` concept | Should move to compile layer. |
| `ComponentCorrespondence` | current `componentMappings_` / tag map concepts | Should move to compile layer. |
| `Mutation.changeState` | current/proposed state edit | Uses typed state ID. |
| `Mutation.createBond` | current/proposed AddBond | Structured endpoints. |
| `Mutation.deleteBond` | current/proposed DeleteBond | Structured endpoints. |
| `Mutation.clearBonds` | current product-only unbound behavior | Proposed sketch had no direct home. |
| `Mutation.createMolecule` | current/proposed AddMolecule | Product-side target. |
| `Mutation.deleteMolecule` | current/proposed DeleteMolecule | Reactant-side target. |
| `Mutation.moveCompartment` | current molecule compartment transport | Proposed sketch had no direct home. |
| `LocalScopeBinding` | `%x::` / local-function scope behavior | Must be resolved before backend lowering. |
| `RuleFilter` | current `CompiledFilter` | Typed side + index + semantic patterns. |
| `Modifier` | current `CompiledModifier` | Should ultimately remove semantic string dispatch. |
| `PopulationMapDecl` | proposed compiled population map | Exact execution semantics still future formal work. |
| `BackendPattern` | proof-only stand-in for NFIR pattern | Replace/extend with real NFIR formal model later. |

## Issue #166: production declaration-to-NFnext ID packing

The named production boundary is the **NFIR v5 molecule-rule graph subset**
accepted by `nfnext::lowerFromBioNetGen(const CompiledModel&)`. At this boundary,
declaration positions become compact NFnext IDs:

| C++ semantic declaration | NFnext representation | Lean reference packing |
|---|---|---|
| `MoleculeTypeId.value()` and molecule declaration index | `TypeId` in `MoleculeTypeIR` and rule nodes (`uint32_t`) | `NFnextPacking.types`: `MoleculeTypeId` paired with `PackedType(index)` |
| `ComponentTypeId{moleculeType, index}` | molecule-local site position; `PredicateIR` and `ActionIR` store it as `uint16_t` | `NFnextPacking.sites`: owner/type component key paired with `PackedSite(index)` |
| `StateId{component, index}` | component-local state position and state value (`int32_t`) | `NFnextPacking.states`: owner/type/component/state key paired with `PackedState(index)` |

Before emitting IR, the production lowerer checks that molecule IDs match the
declaration order, component IDs match their molecule and local declaration
order, and each ID fits the destination NFIR v5 field width. In particular,
component index 65,536 is rejected because it cannot be represented by the
runtime's 16-bit predicate/action site fields. The check prevents a narrowing
cast from aliasing it to site zero. The ordered site/state vectors emitted by
the same loop retain the declaration order used by this mapping.

`NFnextPacking.fromSignature_type_entry`,
`NFnextPacking.fromSignature_site_entry`, and
`NFnextPacking.fromSignature_state_entry` are general Lean theorems: for any
signature and any molecule/component/state selected by list position, the
packing table contains its semantic key paired with that declaration position.
The Lean `Nat` packing has no machine-width limit; the production preflight is
the separate check that makes those positions representable in NFIR v5.

The named subset also excludes population maps and energy factors, filters,
unsupported modifiers, compartment-dependent patterns, incomplete rule
transformations, and rates that do not resolve to finite nonnegative constants.
The current lowerer reports model-level compartment declarations as a warning
and does not emit them, so this contract makes no exact whole-model claim for
models whose behavior depends on compartment semantics. Rule-level support for
created states, bond edits, deletions, and orphan context is further limited by
the explicit rejection cases in `from_bng.cpp`.

This is a molecule-type and rule-graph correspondence only. The current
`lowerFromBioNetGen` path does not encode compiled seed species, observables, or
simulation protocol, so the contract does not claim equivalence for those
`CompiledModel` fields.

`tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp` exercises the
actual BNGL parser -> `CompiledModel` -> `lowerFromBioNetGen` path. Its ordinary
case checks a nonzero local site and state index, free-site predicates, a state
change, and a bond action. Its overflow case constructs 65,537 components and
checks that the unrepresentable last site is rejected. These native tests are
implementation evidence, separate from the Lean packing theorem.

The theorem establishes declaration-order ID packing only. It does not prove
that all production C++ pattern, rate, bond, or transformation lowering is
equivalent to the Lean rule semantics, nor does the native fixture prove a
general C++ refinement theorem.

## Suggested C++ consequences

### `PatternV2`

Prefer something conceptually like:

```cpp
struct PatternSite {
    PatternSiteId occurrence;
    ComponentTypeId component;
    StateConstraint state;
    std::vector<BondRequirement> bonds; // not one bond only
    std::optional<ResolvedTagId> tag;    // if tags remain semantically needed here
};

struct PatternMolecule {
    PatternMoleculeId occurrence;
    MoleculeTypeId type;
    std::optional<CompartmentId> compartment;
    std::vector<PatternSite> sites;
    MoleculeBondConstraint moleculeBond;
};

struct Bond {
    BondGroupId id;
    PatternEndpoint a;
    PatternEndpoint b;
};
```

The exact representation of multiple bonds can differ; the capability should
not.

### `CompiledRule`

Do not assume this is enough:

```cpp
std::vector<Mutation> mutations;
```

unless `Mutation` plus explicit correspondence fully captures current behaviors
now stored in `ast::ReactionRule` side tables.

A safer conceptual shape is:

```cpp
struct RuleDirection {
    std::vector<Pattern> reactants;
    std::vector<Pattern> products;
    CompiledRateLaw rate;

    ResolvedCorrespondence correspondence;
    std::vector<Mutation> mutations;
    std::vector<CompiledModifier> modifiers;
    std::vector<CompiledFilter> filters;
    std::vector<LocalScopeBinding> localScopes;
};
```

### Source text

Fields such as these are fine as metadata:

```text
sourceText
sourcePattern
sourceExpression
```

but downstream execution should never branch on or reparse them.

## Operational semantics additions

The second formalization pass adds runtime/reference concepts that are **not**
a proposal to copy these exact data structures into production C++.

| Lean operational type | C++ concept it clarifies | Intended use |
|---|---|---|
| `MoleculeInstanceId` | runtime molecule identity / NFsim molecule object identity | Keep distinct from pattern occurrence IDs. |
| `ConcreteEndpoint` | runtime molecule + component/site address | Target of concrete state/bond edits. |
| `RuntimeMolecule` | deliberately simple concrete molecule state | Reference oracle, not a performance layout. |
| `RuntimeBond` | explicit undirected concrete edge | Reference bond semantics. |
| `Mixture` | finite concrete molecular graph | Tiny semantic execution state. |
| `Embedding` | pattern occurrence -> runtime molecule mapping | Makes graph matching an explicit semantic operation. |
| `RuleMatch` | one embedding per top-level reactant | Makes multi-reactant non-overlap explicit. |
| `ExecutionEnv` | resolved selected reactants + newly allocated product molecules | Reference equivalent of backend transformation/mapping context. |
| `BackendAction` | proof-level stand-in for NFnext/NFsim action vocabulary | First refinement target. |

### Important C++ consequence: distinguish three identities

A future CompiledModel/backend API should be conceptually clear about:

```text
MoleculeTypeId       -- declaration identity: "this is type A"
PatternMoleculeId    -- occurrence identity: "this A in this pattern"
RuntimeMoleculeId    -- instance identity: "this actual A molecule in this mixture"
```

They solve different problems and should not be casually represented as one
untyped integer namespace.

### Matching boundary

The formal semantics separates:

```text
Pattern + Mixture -> Embeddings
```

from:

```text
Compiled mutations + chosen Embedding(s) -> edited Mixture
```

A production backend can fuse these for speed internally. The **semantic
contract** should still let us reason about them separately, because that is
what makes differential/reference testing possible.

### Backend action mapping candidate

The proof-only backend vocabulary currently suggests this rough correspondence:

```text
Lean BackendAction         NFnext/NFsim-style operation
--------------------------------------------------------------
setState                   state-change action/transformation
addBond                    binding action/transformation
removeBond                 unbinding action/transformation
removeAllBonds             product-side bond clearing semantics
allocateMolecule           add-molecule template/action
eraseMolecule              deletion transformation
relocateMolecule           compartment move transformation
```

Do not treat that table as proof of current backend parity. The next task is to
map actual `nfnext::ActionIR` or NFsim `TransformationSet` cases and compare
their execution with the reference semantics.
