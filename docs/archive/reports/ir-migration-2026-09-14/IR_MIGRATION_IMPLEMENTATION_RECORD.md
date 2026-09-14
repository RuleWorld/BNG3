# BNG3 IR Migration — Complete Implementation Record

## Purpose and scope

This document records the implementation state packaged in this archive. It is intended for maintainers who need to understand exactly what changed, why it changed, what was validated, and what still sits behind compatibility boundaries.

The archive was reconstructed from the latest packaged `BNG3-ir-migration-implemented.zip` recoverable from the user's ChatGPT Library, then the later un-packaged continuation work from this conversation was replayed against that actual tree. This matters because the execution workspace was reset more than once. No claim below is based merely on a chat statement: the final package was inspected and validation was rerun on the reconstructed tree.

The recovered packaged baseline already included extensive earlier BNG3 work: energy compiler/NFcore2/NFnext imports, semantic compilation infrastructure, `compile::Document`, typed IDs and symbols, structured patterns, resolved expression trees, capabilities/preflight, NFIR work, validation/provenance infrastructure, BNGIR scaffolding, and architecture contracts. See `docs/BNG3_HANDOFF_PORT_STATUS.md` and the handoff documents for provenance of that inherited baseline.

This record focuses primarily on the additional IR migration and semantic-boundary work performed in the present effort.

---

## Architectural target

The desired layering is:

```text
source BNGL
  -> parser / AST
  -> compile::Document
       -> CompiledModel (immutable semantic model)
       -> protocol/actions (execution requests, not model meaning)
  -> backend-specific lowering
       -> network generation
       -> NFsim / NFIR
       -> NFnext
       -> BNGsim
       -> exporters and graph writers
       -> BNGIR serialization
```

The design rule applied throughout is:

> Source spelling is provenance; typed resolved structures are execution semantics.

Backends may retain compatibility shims that accept `ast::Model`, but the shim should compile once and delegate. Semantic backends should not call ANTLR, parse BNGL fragments, or recover symbol meaning by string heuristics when equivalent information is already present in `CompiledModel`.

---

## A. Core matching semantics

### New files

`cpp/core/PatternMatching.hpp`

`cpp/core/PatternMatching.cpp`

### Reason

BioNetGen's actual match semantics were embedded in `ast::ReactionRule` even when callers only had already-lowered pattern/species graphs. This created an inverted dependency from semantic/runtime code back to a source rule class.

### Implementation

The new core matcher exposes:

```cpp
bool patternMatches(const BNGcore::PatternGraph&, const BNGcore::PatternGraph&);
std::size_t countPatternMatches(...);
std::size_t countPatternMatchesForScopedMolecule(...);
```

The implementation still uses the established Ullmann subgraph matcher but filters candidate embeddings using BioNetGen rules:

| Concern | Behavior |
|---|---|
| node type | must match |
| node state | must match |
| molecule compartment | explicit pattern compartment constrains target |
| `!?` | no bond-cardinality requirement |
| `!+` | target site must have at least one bond |
| explicit/free cardinality | target bond count must match required count |
| scoped count | first molecule of the *observable pattern* must map to supplied scoped target molecule |

`ast::ReactionRule` compatibility methods now delegate to this layer.

### Important distinction

The “first molecule” rule inside `countPatternMatchesForScopedMolecule` describes the anchor convention of the *observable pattern being counted*. Separately, the rule's local scope now records which molecule occurrence in the **rule reactant** supplies the scoped target. Those are different concepts and both are represented.

---

## B. Exact local-function scope representation

### Modified files

`cpp/compile/CompiledRule.hpp`

`cpp/compile/CompiledRule.cpp`

`cpp/ast/ReactionRule.hpp`

`cpp/ast/ReactionRule.cpp`

`cpp/engine/NetworkRulePlan.cpp`

`cpp/nfsim/NFinput/NFinput_reactions_fromCompiled.cpp`

### Previous defect

`CompiledLocalScope` only identified the reactant pattern. Runtime fingerprinting commonly selected the first molecule node from that pattern. A symbolic scope attached to another molecule occurrence could therefore be evaluated against the wrong molecule.

### New representation

```cpp
struct CompiledLocalScope {
    std::string name;
    std::size_t reactantPatternIndex;
    std::size_t moleculeIndex;
    LocalScopeKind kind;
};
```

`ExecutionHooks::localRateFingerprint` now includes `moleculeIndex`.

The mature `ReactionRule` execution loop enumerates molecule nodes instead of breaking after the first one. `NetworkRulePlan` indexes local observable dependencies by `(patternIndex, moleculeIndex, scopeKind, observableIndex)`.

### Scope parsing rules

Symbolic tags such as `%x` may define molecule-local lexical scope.

`%x::` is recorded as species scope.

Numeric tags such as `%1` and `%2` are mapping labels and are explicitly excluded from lexical local-scope discovery.

Ambiguous reuse of one local name on distinct molecule occurrences emits a compile diagnostic.

Reverse-direction local scopes are discovered from the forward product side and retained on the compiled reverse direction.

---

## C. NFsim exact molecule scope lowering

### Problem

NFsim compilation previously kept `roots`, one `TemplateMolecule*` per reactant pattern. That cannot identify molecule occurrence 1+ within one connected reactant.

### Implementation

The compiled NFsim lowering now threads a `ReactantTemplates` matrix containing all `TemplateMolecule*` objects for each reactant pattern.

`templateForLocalScope()` resolves:

```text
reactantPatternIndex -> moleculeIndex -> TemplateMolecule*
```

This exact template is used by local-rate references and local-scope references. The full template matrix is propagated through dynamic compiled-rate construction, local arithmetic/FunctionProduct cases, ordinary reaction construction, and symmetric reactant expansion.

### Validation

The translation unit was syntax-compiled using a temporary interface-only ExprTk header matching the functions/types used by the source. The real ExprTk dependency is not installed in the packaging runtime; no runtime propensity-parity claim is made from this stub check.

---

## D. Explicit legacy network kernel

### New files

`cpp/engine/LegacyNetworkRuleKernel.hpp`

`cpp/engine/LegacyNetworkRuleKernel.cpp`

### Modified file

`cpp/engine/NetworkRulePlan.cpp`

### Reason

A full rewrite of mature `ast::ReactionRule::expandRule()` would combine an architectural refactor with a large behavioral rewrite. That would make parity regressions difficult to localize.

### Boundary

`LegacyNetworkRuleKernel` is the explicit quarantine for the mature source-era expansion object. It receives compiled directions, lowers them through established compatibility functions, owns `ReactionRule::ExecutionState`, and exposes the narrow operations required by `NetworkRulePlan`.

`NetworkRulePlan` itself now handles compiled filters and local-observable fingerprints without including `ReactionRule` directly.

This allows the dependency checker to ratchet general engine code away from the AST while preserving a clearly named compatibility oracle.

---

## E. BNGIR v0.2 local scopes and referential integrity

### Modified files

`cpp/bindings/bind_compile_snapshot.cpp`

`provenance/schemas/bngir-0.2.schema.json`

`python/bionetgen/bngir.py`

`tests/python/test_bngir_structural_helpers.py`

### Structural local scopes

Each compiled rule direction now emits:

```json
{
  "name": "x",
  "kind": "molecule",
  "pattern_index": 0,
  "molecule_index": 1
}
```

The v0.2 schema requires `local_scopes` on directions. The BNGL reconstruction path uses these bindings to re-emit molecule or species scope notation.

### ID semantics

`_name_for_symbol` no longer indexes directly into arrays. `_entities_by_id()` builds a validated ID map. Sparse IDs are therefore legal and duplicate IDs are rejected.

### New structural validators

`_validate_model_v02()` recursively verifies semantic references. It calls validators for expressions, patterns, rule endpoints, directions, population maps, and declaration namespaces.

Checks include typed symbol existence, type-name/ID agreement, component and state agreement, compartment parent references, exact-bond arity, mutation endpoints, filter target indexes, local scopes, local expression references, reactant-count references, reverse-direction contracts, and rule mapping endpoints.

The goal is not only schema shape validation. JSON Schema can say “this field is an integer”; semantic validation must say “that integer actually refers to a valid component of this molecule type.”

### Tests

The focused pure-Python suite currently contains eight v0.2 structural tests covering feature negotiation, schema conformance, expression/pattern reconstruction, sparse IDs, local scopes, dangling references, and population-map preservation.

---

## F. Population-map semantic repair

### Modified files

`cpp/ast/PopulationMap.hpp`

`cpp/parser/BNGAstVisitor.cpp`

`cpp/compile/SymbolTable.hpp/.cpp`

`cpp/compile/CompiledModel.hpp/.cpp`

`cpp/engine/HybridModelGenerator.cpp`

`cpp/bindings/bind_model.cpp`

`cpp/bindings/bind_compile_snapshot.cpp`

BNGIR schema/adapter files

### Defect

Existing models contain population-map forms equivalent to:

```text
particle_pattern -> PopulationType() k_gather
```

The old AST named the RHS target `populationFunction` and did not retain the trailing rate. Hybrid mapping rule generation substituted a zero rate.

### New semantic model

The historical public fields remain for API compatibility, but the semantics are now explicit:

```text
populationName
populationArguments
rate expression
hasRate
```

The symbol table adds `SymbolKind::PopulationType` and `PopulationTypeId` as a namespace separate from user functions.

`CompiledModel` adds `CompiledPopulationType` and changes `CompiledPopulationMap` to contain a typed population reference and resolved rate expression.

### Parser bridge

Because the checked-in generated ANTLR parser does not accept the trailing population-map rate and the packaging runtime cannot regenerate ANTLR, `normalizePopulationMapRates()` encodes the rate as a synthetic parser-safe marker inside the already accepted argument list. `visitPopulation_map_def` decodes and parses it as an expression.

This bridge is intentionally documented as temporary. The preferred final implementation is a grammar update plus normal ANTLR regeneration.

### Hybrid behavior

`HybridModelGenerator` now uses `pm.rate` when `hasRate` is true. Zero remains only as the compatibility fallback for old programmatic maps that never supplied a rate.

---

## G. Shared observable projection

### New files

`cpp/engine/ObservableProjection.hpp`

`cpp/engine/ObservableProjection.cpp`

### Old pattern

Several consumers ran ANTLR over observable pattern strings repeatedly for each generated species.

### New behavior

Compiled observable patterns are lowered once. `projectObservables()` computes sparse `(speciesIndex, weight)` entries for every compiled observable.

Molecules observables count embeddings. Species observables apply the compiled stoichiometric relation and contribute one unit per satisfied term/species.

Supported Species relations are `==`, `!=`, `>`, `>=`, `<`, and `<=`. `CompiledModel` observable parsing and the BNGIR schema were updated to include `!=`.

### Consumers migrated

`RegulatoryGraphWriter`, C++ exporter, Python exporter, MATLAB exporter, MEX exporter, standard SBML, and BNGsim use the shared service.

---

## H. Graph and visualization writer migration

### ContactMapWriter

Canonical API accepts `CompiledModel`.

Exact bond groups are read from structured pattern descriptors. `AddBond` mutations also create possible contacts. Endpoint order is canonicalized because the contact map is undirected. The implementation avoids counting the first compatibility bond descriptor twice when `bondConstraints` is authoritative.

### RegulatoryGraphWriter

Canonical API accepts `CompiledModel`; observable weights come from `ObservableProjection`.

### RulevizPatternWriter

Canonical API accepts compiled rules and directions. It no longer needs the source model for semantic grouping.

### RulevizOperationWriter

Operation nodes come from compiled mutation kinds (`AddBond`, `DeleteBond`, `ChangeState`, `AddMolecule`, `DeleteMolecule`). Rules without an explicit mutation list receive a generic transformation node rather than a guessed source operation.

### ProcessGraphWriter / ReactionNetworkGraphWriter / RuleInfluenceGraphWriter

These writers derive entirely from `GeneratedNetwork`. Canonical APIs therefore no longer request an unused source model. Compatibility overloads remain.

---

## I. Generated-code/text exporter migration

Canonical `CompiledModel` entry points were added for:

| Exporter | Semantic changes |
|---|---|
| `CppExportWriter` | shared observable projection; compiled parameters |
| `PythonExportWriter` | shared observable projection; compiled parameters |
| `MatlabWriter` | shared observable projection; compiled parameters |
| `MexWriter` | shared observable projection; compiled parameters |
| `MdlWriter` | compiled metadata/model name |
| `SscWriter` | compiled metadata/parameters; fail closed on unevaluable value |
| `LatexWriter` | compiled parameters/observable source patterns; parser dependencies removed |

AST overloads are retained as compatibility shims that construct `CompiledModel` once.

Where the target format fundamentally requires numeric constants, missing `constantValue` now throws rather than silently substituting zero.

---

## J. Typed expression to MathML lowering

### New files

`cpp/io/ResolvedExpressionMathML.hpp`

`cpp/io/ResolvedExpressionMathML.cpp`

### Purpose

SBML exporters should not turn resolved model semantics back into text and then guess what the text means. This helper converts `ResolvedExpression` directly to Content MathML.

Handled forms include numbers; typed parameter/function/observable refs; function application; time; declared locals; unary/binary arithmetic; comparisons; Boolean operators; common mathematical builtins; `if` as `piecewise`; and base-2/base-10 logs.

Unsupported or context-dependent constructs fail closed, particularly unresolved expressions, standalone `reactant_N`, and generic TFUN data without an explicit SBML lowering.

---

## K. Standard SBML migration

`SbmlWriter` now has a `CompiledModel` semantic entry point. The legacy AST entry point compiles and delegates.

Model metadata, compartments, parameters, seeds, functions, and observable groups come from the compiled model. Argument-taking functions are emitted as SBML `FunctionDefinition` lambdas using typed MathML. Zero-argument functions retain the established assignment-rule treatment.

Generated reaction objects still carry the mature generated-network reaction/rate payload, so the generated-reaction helper remains a compatibility-level formatter. This is intentionally distinct from traversing the source model AST.

---

## L. SBML-Multi migration

`SbmlMultiWriter` now traverses `CompiledModel` declarations and rule directions. It emits molecule-type/species-type definitions, compartments, parameters, seed species, pattern species for rules, and structured forward kinetic laws.

Unspecified site binding state is not converted into an explicit `either` constraint; only an actual wildcard/binding constraint is emitted as such.

AST overloads are compile-on-entry shims.

The current implementation remains conservative: Multi v1 does not provide a native BioNetGen reaction-rule vocabulary, so rule patterns remain represented via core species objects with BNGL-compatible names, as before.

---

## M. BNGsim adapter migration

The optional BNGsim adapter now has a canonical `CompiledModel` overload.

Parameters use compiled constant values. Observables use `projectObservables()`. Global functions are serialized from typed resolved-expression trees. TFUN payloads use the structured table data retained in `ResolvedExpression`.

The bridge rejects model semantics it cannot faithfully express instead of dropping them. Generated reaction rate references must resolve as a direct parameter or function reference.

The external real `bngsim/model_builder.hpp` is not installed in the packaging environment. A temporary header implementing the exact interface used by the adapter was used for a C++ syntax check. That is compile-interface evidence, not behavioral parity evidence.

The inherited project handoff document records older, independent tests against a pinned real BNGsim checkout; those results were not rerun during this packaging pass.

---

## N. Architecture dependency ratchet

`tools/check_architecture_dependencies.py` rejects unauthorized AST/parser dependencies in backend-sensitive directories.

At the recovered packaged baseline:

```text
45 explicit compatibility files
```

At this package checkpoint:

```text
21 explicit compatibility files
```

The remaining allowlist is stored in `provenance/architecture/ast_compat_allowlist.txt`. The deliberately isolated `LegacyNetworkRuleKernel.cpp` is one of those exceptions.

This number is not a quality score by itself. It is a concrete migration ledger: dependency reductions are explicit and regressions are machine-detectable.

---

## O. Validation performed for this package

### Passing automated checks

```text
python tools/check_architecture_dependencies.py
    PASS: 21 explicit compatibility files

pytest -q tests/python/test_bngir_structural_helpers.py
    8 passed

pytest -q tests/python/test_bngir_structural_helpers.py \
          tests/python/test_architecture_dependencies.py
    9 passed

python -m py_compile python/bionetgen/bngir.py
    PASS

git diff --check
    PASS
```

### Direct C++ syntax compilation

The packaging pass syntax-compiled the modified units that do not require unavailable external toolchains, including:

```text
core/PatternMatching
compile/SymbolTable
compile/CompiledModel
compile/CompiledRule
ast/ReactionRule
engine/LegacyNetworkRuleKernel
engine/NetworkRulePlan
engine/ObservableProjection
ContactMapWriter
RegulatoryGraphWriter
RulevizPatternWriter
RulevizOperationWriter
ProcessGraphWriter
ReactionNetworkGraphWriter
RuleInfluenceGraphWriter
MdlWriter
SscWriter
LatexWriter
CppExportWriter
PythonExportWriter
MatlabWriter
MexWriter
ResolvedExpressionMathML
SbmlWriter
SbmlMultiWriter
```

### Interface-stub syntax checks

`NFinput_reactions_fromCompiled.cpp` was checked using a temporary minimal ExprTk API header.

`BngsimAdapter.cpp` was checked using a temporary minimal `bngsim::ModelBuilder` API header.

Neither stub is included in the archive.

---

## P. Validation that was not possible in this environment

The packaging runtime lacks the full ANTLR C++ toolchain/runtime and the real external BNGsim dependency. Therefore this package does not claim a fresh full CMake build, generated-parser rebuild, hybrid population-map integration run, or real BNGsim execution.

It also does not claim a fresh rerun of the historical full CTest/Python/NFsim/BNG2 parity matrix documented in the inherited handoff status. Those historical results remain provenance for their original checkpoint, not automatic evidence for the new diff.

A maintainer should treat the parser population-map bridge, hybrid population-map path, exact non-root local function behavior, and external BNGsim adapter as high-priority full-environment regression targets.

---

## Q. Files intentionally left behind the compatibility boundary

The current allowlist contains 21 paths. Broadly, they fall into these categories:

```text
source/action dispatch
hybrid and legacy simulation engines
LegacyNetworkRuleKernel
GeneratedNetwork source-facing declaration boundary
BNGL/net/XML legacy IO
legacy NFsim input bridges
```

The precise list is the checked-in allowlist file; it should be consulted rather than copied into downstream documents, because the point of the ratchet is for the list to shrink.

---

## R. Design decisions that should not be undone casually

### Do not make raw source text authoritative again

`sourceText`, `sourceExpression`, and source patterns remain useful for diagnostics and round-trip friendliness. Execution should use resolved IDs, structured patterns, and typed expression trees.

### Do not replace fail-closed behavior with silent approximations

Several exporters/adapters now throw when a required semantic form is not representable. That is intentional. A scientific modeling tool should not silently produce a different model merely because an export format is inconvenient.

### Do not rewrite the mature network kernel without an independent oracle

The legacy kernel is isolated specifically so replacement can proceed under parity tests. Its existence is not an excuse for new code to depend on the AST.

### Keep IDs semantic

Wire-format identifiers must not be treated as array positions. This matters for stable serialization, caching, model transformation, external tooling, and future compiler passes.

### Keep model meaning separate from execution protocol

Simulation actions are requests to do things with a model. They are not declaration semantics. `compile::Document` and the BNGIR protocol split should preserve that distinction.

---

## S. Recommended next validation sequence

In a full development environment, the next maintainer should perform the following sequence before extending the migration further:

```text
1. install/use the repository's intended ANTLR C++ toolchain
2. replace the population-rate normalization bridge with a grammar production
3. regenerate parser sources
4. configure and build the complete CMake tree
5. run full CTest
6. run the complete Python regression suite
7. run hybrid population-map fixtures with nonzero gather/lump rate
8. run rules whose symbolic local scope is molecule occurrence > 0
9. run reversible local-function examples
10. run direct compiled NFsim against the compatibility/oracle path
11. build the BNGsim adapter against the pinned real dependency
12. test SBML and SBML-Multi round trips on representative rule/function models
13. only then continue reducing the remaining compatibility allowlist
```

---

## T. Package provenance and recovery note

The execution workspace for this long conversation was reset multiple times. To avoid presenting a stale or imaginary tree, the packaging process recovered the latest generated `BNG3-ir-migration-implemented.zip` from the user's persistent ChatGPT Library and replayed the later continuation work against that concrete source tree.

The final archive therefore contains real source files corresponding to this record. The README and record were generated only after the replay and focused validation completed.

This recovery note is included so a future maintainer understands why the package has one baseline commit plus an uncommitted migration diff rather than a neat historical commit series. A clean PR should split the work into reviewable commits after full-environment validation.
