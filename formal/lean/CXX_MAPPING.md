# Mapping between the Lean semantic kernel and BNG3 C++

This file is a migration aid.  It is not a demand that C++ copy Lean field names
exactly.

| Lean | Current/proposed BNG3 concept | Notes |
|---|---|---|
| `CompiledModel` | `bng::compile::CompiledModel` | Lean includes the proposed missing declaration classes. |
| `Document` | `bng::compile::Document` | Keeps simulation protocol separate from reusable model semantics. |
| `ParameterDecl` | proposed `CompiledParameter` | Expression is already resolved. |
| `MoleculeType` | proposed `CompiledMoleculeType` | Contains typed component declarations. |
| `ComponentType` | proposed `CompiledComponentType` | Contains typed allowed state IDs. |
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

## Current tested bridge

The first production-boundary bridge is intentionally narrower than this
mapping table. `tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp` parses the
rule `A(x~u) + B(y) -> A(x~p!1).B(y!1) k`, builds a real
`bng::compile::CompiledModel`, and calls `nfnext::lowerFromBioNetGen`. It then
checks `DifferentComplex`, `SetSiteState`, and `Bind`. The Lean example in
`BNG/Examples.lean` checks the corresponding typed NFnext shape independently.
The bridge is a regression contract, not a complete refinement theorem.

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
