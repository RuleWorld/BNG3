# BNG3 IR Migration — ELI15 Guide

## What this branch is trying to do

BioNetGen starts with **BNGL text**. A BNGL file is written for humans: it has molecule names, sites, bonds, rules, functions, observables, simulation actions, and a lot of syntax whose meaning depends on context.

Historically, many parts of BNG3 reached back into that parser/AST representation whenever they needed meaning. That works while the program is small, but it creates a long-term problem: every simulator, exporter, graph writer, and optimization can accidentally become a second BNGL interpreter. Two backends can read the same model and subtly disagree because each one reparses strings or makes slightly different assumptions.

The central idea of this migration is simple:

> **Parse BNGL once, resolve its meaning once, and give every backend the same typed semantic model.**

Think of a compiler such as Clang, Rust, LLVM, or MLIR. The parser's syntax tree is not the object every machine-code backend uses forever. The frontend resolves names and meaning, constructs an intermediate representation, validates it, and then lower-level systems consume that stable representation. This work moves BNG3 in that direction.

The intended flow is:

```text
BNGL source
   |
   v
parser / AST                  Human syntax lives here
   |
   v
compile::Document             Compile once; separate model from protocol
   |
   +----> compile::CompiledModel
   |          |
   |          +--> typed symbols / IDs
   |          +--> structured patterns
   |          +--> resolved expressions
   |          +--> compiled rules and edits
   |          +--> observables, functions, population maps, energy factors
   |
   +----> protocol/actions
              |
              v
semantic backends / lowerings
   |
   +--> network generation
   +--> NFsim / NFIR
   +--> NFnext experiments
   +--> BNGsim bridge
   +--> SBML / SBML-Multi
   +--> MATLAB / Python / C++ / MEX exports
   +--> contact maps / Ruleviz / regulatory graphs
   +--> BNGIR JSON wire format
```

The important word is **meaning**. The IR is not merely a cleaner copy of the BNGL string. It should know, for example, that a symbol refers to parameter 7, that a site state is state 2 of component 1 of molecule type 4, that a rule mutation changes a particular reactant site, or that a local function is scoped to the second molecule occurrence in the first reactant pattern.

---

## The easiest mental model: source code versus resolved instructions

Suppose BNGL contains something conceptually like:

```text
A(x~u) -> A(x~p)  k
```

A syntax-oriented representation mostly remembers text such as `A`, `x`, `u`, `p`, and `k`.

A semantic IR wants something closer to:

```text
Rule #12
  reactant pattern #0
    molecule occurrence #0 -> MoleculeTypeId(A)
      site occurrence #0 -> ComponentTypeId(x)
        exact state -> StateId(u)

  product pattern #0
    molecule occurrence #0 -> MoleculeTypeId(A)
      site occurrence #0 -> ComponentTypeId(x)
        exact state -> StateId(p)

  mutation
    ChangeState(
      reactant pattern 0,
      molecule 0,
      site 0,
      new StateId(p)
    )

  rate
    ParameterRef(ParameterId(k))
```

That form is much harder for a backend to misunderstand. It also means renaming things, serializing the model, optimizing the runtime, or writing a new backend does not require reinventing BNGL parsing.

---

## What was already in the recovered packaged baseline

This archive starts from the latest packaged BNG3 checkpoint that was recoverable from the user's Library. That baseline already contained a substantial amount of prior BNG3 work, including the energy compiler/NFcore2/NFnext handoff ports, semantic compilation infrastructure, capability checks, `compile::Document`, typed symbol resolution, structured patterns, compiled rate expressions, NFIR/NFsim adapter work, BNGIR v0.1/v0.2 scaffolding, validation/provenance infrastructure, and architecture dependency checks.

The existing project documents under `docs/`, especially `docs/BNG3_HANDOFF_PORT_STATUS.md`, remain the authority for that inherited work. This README does **not** claim that all of that pre-existing baseline was created in this particular IR-migration conversation.

The work in this package extends that baseline by removing more parser/AST interpretation from execution and export paths, making important pieces of the IR more lossless, and tightening validation.

---

## 1. BioNetGen graph matching was moved below the AST

A major architectural smell was that useful graph-matching semantics lived as static helpers on `ast::ReactionRule`. Code that merely wanted to answer “does this already-lowered BioNetGen pattern match this species?” had to depend on a source-level reaction-rule class.

This package adds:

```text
cpp/core/PatternMatching.hpp
cpp/core/PatternMatching.cpp
```

The core matcher wraps the Ullmann graph-isomorphism machinery with BioNetGen-specific rules that Ullmann alone does not know about:

- node type and state equality;
- molecule compartment constraints;
- explicit bond cardinality;
- `!+` meaning “must be bound”;
- `!?` meaning “bond state unconstrained”;
- exact/free-site behavior;
- molecule-anchored match counting for local functions.

`ast::ReactionRule` retains compatibility wrappers, but those wrappers now delegate downward to `bng::core`. This reverses the dependency direction: semantic/runtime code can use the matcher without pretending it needs the source AST.

### Why this matters

Matching semantics are foundational. Observables, rule filters, local functions, regulatory graphs, and several backend operations all need them. One matcher means fewer places where “same BNGL, different result” bugs can hide.

---

## 2. The remaining mature network-expansion code is quarantined

The mature BNG3 network-generation implementation still uses `ast::ReactionRule` internally. Rewriting that entire algorithm at once would be high risk because it contains years of subtle matching/transformation behavior.

Instead of pretending it has already been replaced, this work creates an explicit compatibility boundary:

```text
cpp/engine/LegacyNetworkRuleKernel.hpp
cpp/engine/LegacyNetworkRuleKernel.cpp
```

`NetworkRulePlan` now consumes compiled semantic structures and delegates the final mature expansion operation through this one named bridge. The architecture dependency allowlist therefore points to **one deliberate legacy kernel** rather than letting general engine code reach back into `ReactionRule`.

This is the same strategy used in mature compiler migrations: put old behavior behind a narrow adapter, prove the new representations around it, then replace the adapter from the inside later.

### What was *not* done

The underlying expansion algorithm was **not** rewritten merely for architectural purity. The package deliberately keeps the known mature implementation while isolating it.

---

## 3. Local-function scopes now identify the exact molecule occurrence

This was one of the most important correctness holes found during the migration.

BNGL local-function notation can attach a local identifier to a particular molecule occurrence. For example, conceptually:

```text
C() + W%x(site) -> ...  localObservable%x
```

It is not enough to record “`x` belongs to reactant pattern 0.” If that reactant contains multiple molecules, the runtime must know which molecule `x` refers to.

Previously, the local-rate fingerprint hook effectively looked at the first molecule of a reactant pattern. That can be wrong when the tagged molecule is occurrence 1, 2, etc.

`CompiledLocalScope` now records:

```text
name
reactantPatternIndex
moleculeIndex
kind = molecule | species
```

The rule execution hook now receives both the pattern index and molecule index. Network generation fingerprints local observable dependencies only for the exact scoped molecule.

### Numeric tags are not local scopes

BNGL also uses numeric mapping tags such as `%1` and `%2`. Those are mapping labels, not lexical local-function names.

The compiled scope discovery now accepts symbolic identifiers such as `%x` but rejects numeric-only tags as local scopes. This prevents a very subtle namespace collision where mapping metadata could accidentally become an expression variable.

### Reverse rules

For reversible rules, reverse local scopes are discovered from the forward product side rather than being silently cleared. The rate-expression compile environment incorporates the relevant local names for both directions.

---

## 4. NFsim receives the exact local molecule template

Fixing `CompiledLocalScope` would be incomplete if NFsim still received only one root `TemplateMolecule*` per reactant.

The compiled NFsim reaction lowering now threads the full matrix:

```text
reactant pattern
    -> all TemplateMolecule* occurrences in that pattern
```

Local-function binding uses:

```text
scope.reactantPatternIndex
scope.moleculeIndex
```

instead of always selecting the root/first molecule.

This affects local rate references, local scope references, dynamic compiled functions, FunctionProduct-style expressions, and symmetric-reactant expansion.

The modified NFsim unit was syntax-checked with a temporary ExprTk interface stub because this execution environment does not ship the real ExprTk header. The stub is **not** included in this archive and is not production code; it was only used to validate C++ type/signature consistency.

---

## 5. BNGIR v0.2 is much more structural

BNGIR is the JSON wire representation of the semantic model. A useful IR file must be able to survive process boundaries: Python should not need the original parser AST or raw BNGL strings to understand model meaning.

The v0.2 work in this package strengthens that contract in several ways.

### Local scopes are explicit

Rule directions now serialize local scopes as structural references containing:

```text
name
kind
pattern_index
molecule_index
```

The BNGL compatibility renderer can therefore reconstruct molecule scopes and species scopes without guessing from unrelated rule text.

### IDs mean IDs, not list positions

A major wire-format bug class is treating an identifier like an array offset. This breaks as soon as IDs are sparse, reordered, merged, or generated by another producer.

BNGIR symbol lookup now resolves the declared `id` values. A parameter with ID 7 may be stored at array position 0 and still be referenced as parameter 7.

### Referential integrity is checked

The pure-Python validator now checks structural relationships before reconstruction. It catches things such as:

- duplicate semantic IDs;
- unknown molecule-type IDs;
- component index/name disagreements;
- state index/value disagreements;
- unknown compartment parents;
- malformed exact bonds;
- dangling rule mutation endpoints;
- invalid filter targets;
- out-of-range local-scope molecule references;
- unbound local references;
- out-of-range `reactant_N` references;
- invalid reversible-rule direction contracts;
- population-map type/name mismatches.

That is the difference between “JSON that looks plausible” and an actual IR contract.

---

## 6. Population maps had a real semantic-loss bug; it is repaired

Repository fixtures contain population maps like:

```text
L(r) -> L_pop() k_gather
```

The old representation treated `L_pop` as if it were a function name and, more seriously, the parser/AST path did not preserve the trailing gather/lump rate expression. Hybrid rule generation then substituted a zero rate.

That changes the model.

This package separates the concepts:

```text
source particle pattern
population target type/name
population target arguments
mapping/gather rate expression
```

The compile symbol table now has a separate `PopulationTypeId` namespace. `CompiledModel` exposes `CompiledPopulationType` and a structured `CompiledPopulationMap` containing a resolved rate expression.

BNGIR v0.2 serializes population types and the mapping rate explicitly.

`HybridModelGenerator` uses the declared rate. Programmatically constructed legacy maps that truly lack a rate keep the historical zero-rate fallback rather than fabricating a new value.

### Parser compatibility bridge

The checked-in generated ANTLR parser grammar did not include that trailing rate in its population-map production, and this runtime does not contain the ANTLR generator/runtime needed to safely regenerate it.

Rather than hand-editing ANTLR's serialized automaton, `normalizePopulationMapRates()` temporarily encodes the trailing expression into a synthetic parser-safe parameter marker. The AST visitor decodes that marker and parses the recovered expression into the normal `ast::Expression` representation.

This is explicitly a **compatibility bridge**, not the ideal final grammar. A future environment with the ANTLR toolchain should update the grammar and regenerate parser sources normally.

---

## 7. Observable projection is now one shared semantic service

Several exporters previously did this independently:

```text
for every observable
  for every generated species
    lex/parse the observable BNGL text again
    build another graph
    run another matcher
```

That is slow and dangerous: each exporter was effectively implementing observable semantics again.

This package adds:

```text
cpp/engine/ObservableProjection.hpp
cpp/engine/ObservableProjection.cpp
```

Compiled observable patterns are lowered once. The shared service then projects them onto a generated network.

It preserves the important distinction:

- **Molecules observables** count pattern embeddings;
- **Species observables** count a species once when its term condition is satisfied.

Species stoichiometric relations include:

```text
==  !=  >  >=  <  <=
```

This service is now used by the regulatory graph, generated-code exporters, standard SBML, and the BNGsim bridge.

---

## 8. Graph/visualization writers now consume semantic data

Several graph writers either reparsed strings or accepted an `ast::Model` they did not actually use.

### Contact map

`ContactMapWriter` now builds contacts from structured compiled bond groups and `AddBond` mutations. It canonicalizes undirected endpoints and avoids double-counting the compatibility mirror of an authoritative bond descriptor.

### Regulatory graph

`RegulatoryGraphWriter` uses `CompiledModel` and `ObservableProjection`; it no longer invokes ANTLR for every species/observable pair.

### Ruleviz

The Ruleviz pattern and operation writers now use compiled rule directions and compiled mutation programs. AST overloads are compatibility shims.

### Network-only graphs

`ProcessGraphWriter`, `ReactionNetworkGraphWriter`, and `RuleInfluenceGraphWriter` never needed the source model at all. Their canonical APIs now take only `GeneratedNetwork`; old AST signatures simply delegate.

This is a small change with an important design message: APIs should ask only for the information they actually need.

---

## 9. Generated-code exporters no longer reparse observables

The following exporters now have canonical `CompiledModel` entry points:

```text
C++/CVODE exporter
Python exporter
MATLAB exporter
MEX exporter
MDL writer
SSC writer
LaTeX writer
```

The first four use the shared observable projection instead of parser/Ullmann loops.

Where an exporter requires a numeric parameter value, it now **fails closed** if a parameter is not compile-time evaluable. It does not silently turn an unknown expression into `0`.

The AST API remains available for compatibility and performs one compile-on-entry conversion.

---

## 10. SBML and SBML-Multi now consume compiled semantics

Both SBML writers gained semantic-model entry points.

A shared helper:

```text
cpp/io/ResolvedExpressionMathML.hpp
cpp/io/ResolvedExpressionMathML.cpp
```

turns typed `ResolvedExpression` trees into Content MathML.

This avoids the anti-pattern of parsing or guessing from expression strings at export time.

Supported expression families include numeric literals, typed parameter/function/observable references, time, local identifiers where a lambda declares them, arithmetic, comparisons, Boolean operators, common math built-ins, conditional piecewise output, and logarithm bases.

Constructs without a faithful generic SBML lowering—such as unresolved expressions, free `reactant_N` references, or table functions without explicit data lowering—fail closed.

Standard SBML also emits argument-taking BioNetGen functions as actual MathML lambda `FunctionDefinition`s. Zero-argument global functions remain assignment-rule parameters.

SBML-Multi consumes compiled molecule types, compartments, seeds, rules, and structured rates. It does not need the source `ast::Model` for semantic traversal.

---

## 11. The BNGsim bridge is a compiled-model adapter

The optional BNGsim bridge now takes:

```text
CompiledModel + GeneratedNetwork
```

It uses structured parameters/functions/observables rather than reparsing model source.

It deliberately rejects semantic surfaces for which this bridge has no proven representation, including unsupported compartment semantics, energy-pattern behavior, population maps, local-function argument binding, unresolved expressions, and rate laws that cannot be identified as direct parameter/function references.

That is intentional. An adapter that refuses unsupported semantics is safer than one that produces a numerically valid but scientifically different model.

The real external BNGsim development headers are not installed in this execution environment. The rewritten translation unit was syntax-checked against a local interface stub matching exactly the methods it calls. The existing project handoff document contains earlier independent evidence against a pinned real BNGsim build; this packaging pass does not claim to have rerun that external test.

---

## 12. Architecture enforcement is part of the implementation

The repository has an architecture dependency checker and an explicit compatibility allowlist.

At the recovered packaged checkpoint, the allowlist contained **45 files**. After the migrations in this package it contains **21 files**.

That count is useful because it converts an architectural aspiration into a ratchet: new parser/AST dependencies cannot casually appear in backend directories, and each migration can remove an explicit exception.

The remaining files are not hidden. They include genuinely parser-facing/action code, the deliberately isolated legacy network kernel, legacy simulation engines, native BNGL/net/XML compatibility surfaces, and legacy NFsim bridge files.

The goal is not “zero AST references at any cost.” The goal is that source syntax stays at source-facing boundaries and semantic backends do not independently interpret it.

---

## What is proven in this package

The packaging validation performed in this environment includes:

```text
architecture dependency checker: PASS
pure structural BNGIR tests:       8/8 PASS
architecture pytest:               PASS
combined focused pytest:           9/9 PASS
Python BNGIR bytecode compile:     PASS
git diff --check:                  PASS
```

Direct C++ syntax compilation passed for the modified core matcher, semantic compile layer, rule execution wrappers, network plan/kernel, observable projection, graph writers, generated-code exporters, MathML helper, and both SBML writers.

The NFsim compiled local-scope translation unit also syntax-checks with a temporary ExprTk interface stub. The BNGsim adapter syntax-checks against a temporary ModelBuilder interface stub.

These stubs validate C++ interfaces/types only. They are not solver substitutes and are not included in the package.

---

## What is *not* proven here

This runtime does not contain the complete dependency/tool environment needed to rerun the repository's full historical validation matrix.

In particular, this packaging pass does **not** claim:

- a full clean CMake build of every target;
- regeneration of ANTLR parser artifacts;
- complete parser/hybrid end-to-end tests after the population-map compatibility bridge;
- execution against the real external BNGsim headers/library;
- fresh full NFsim stochastic trajectory parity;
- fresh BNG2 parity across the full model corpus;
- replacement of the mature `ReactionRule` expansion algorithm;
- elimination of all compatibility code.

The package keeps these limitations visible instead of converting missing evidence into a success claim.

---

## What should happen next

The most valuable next step is **validation before more architecture churn**. In a complete developer environment, regenerate the parser from the corrected population-map grammar/contract, build the full CMake tree, run the complete CTest/Python validation suites, exercise hybrid population maps, run local-function rules where the scope is not molecule occurrence 0, and test the BNGsim adapter against the pinned real dependency.

After that, continue shrinking the compatibility allowlist. The biggest remaining architectural item is the mature network expansion implementation behind `LegacyNetworkRuleKernel`. It should only be replaced when independent behavior tests prove the replacement—not because the old class name is aesthetically inconvenient.

---

## Short version

BNG3 is being changed from:

> “Parse BNGL, then let lots of subsystems keep interpreting the parser's objects and strings.”

into:

> “Parse once, compile once into a typed semantic model, validate it, and make every backend consume that same meaning.”

Most of this package is infrastructure that makes that sentence true in more places, plus fixes for several real correctness issues uncovered while doing the migration: exact local-function molecule scopes, lost population-map rates, duplicate/ambiguous IDs in BNGIR, repeated observable reparsing, and exporters that silently invented zero values.
