# Architecture

The canonical semantic-model boundary and staged migration policy are defined
in [ADR 0001](adr/0001-canonical-semantic-model-and-layer-boundaries.md).
This page describes the current implementation layout; it does not imply
that every planned semantic/backend seam is complete.

## Overview

BioNetGen 3 is a monorepo combining three previously separate projects:

```
User (Python API / CLI)
    │
    ▼
python/bionetgen/         ← High-level Python interface
    │
    ▼ (pybind11, in-process)
cpp/bindings/             ← pybind11 binding layer
    │
    ├──► cpp/parser/      ← ANTLR4 BNGL parser → AST
    ├──► cpp/ast/         ← Model AST (Parameters, Rules, Species, ...)
    ├──► cpp/core/        ← Graph operations (PatternGraph, Ullmann, nauty)
    ├──► cpp/engine/      ← NetworkGenerator, OdeIntegrator, SSA
    ├──► cpp/io/          ← Writers (XML, SBML, .net, MATLAB, LaTeX, ...)
    ├──► cpp/actions/     ← ActionDispatch (execute model actions)
    ├──► cpp/cli/         ← Isolated parallel batch orchestration
    └──► cpp/nfsim/       ← NFSim network-free engine
```

## Data Flow

### ODE/SSA Path

```
.bngl file → ANTLR4 Parser → ast::Model
                                   │
                                   ▼
                         NetworkGenerator::generateNative()
                                   │
                                   ▼
                         GeneratedNetwork (SpeciesList + RxnList)
                                   │
                                   ▼
                         OdeIntegrator::integrate()  [CVODE / Euler / RK4 / SSA]
                                   │
                                   ▼
                              OdeResult → numpy arrays (via pybind11)
```

`ReactionRule` stores compiled semantic metadata only. `NetworkGenerator`
creates one `ReactionRule::ExecutionState` per rule for matcher caches,
iteration bookkeeping, synthesis guards, and bidirectional reverse state.
Legacy no-state calls remain compatibility shims over a private context.

The compile layer also resolves declarations into namespace-specific typed IDs
through `SymbolTable`, builds a resolved expression tree with typed parameter,
observable, function, lexical-local, and time references, and compiles
rate-law and model-function references against that table. It retains typed
rule modifiers plus parsed filter patterns alongside their source spelling.
Unresolved expression names and malformed filters become structured errors.
`featuresUsed(Model)` and the fail-closed `capabilitiesFor(Model, BackendKind)`
preflight distinguish exact lowering, compatibility-only, and unsupported
features before a backend allocates runtime state; direct NFsim rejects
population maps instead of silently ignoring them.

### Semantic compile stage

```
ast::Model → SymbolTable / diagnostics → CompiledModel
                                      ├── CompiledRule
                                      │    ├── typed rate-law references
                                      │    └── typed modifiers
                                      └── energy-factor metadata

`compile::Document` now keeps this reusable compiled model separate from a
copied `SimulationProtocol`. The AST remains the construction/compatibility
surface; protocol actions do not become part of compiled model identity.
```

This is the migration seam toward a resolved semantic model. It is not yet a
replacement for every legacy AST consumer; the compiled model now carries
value-like `Pattern` records for rules, energy factors, observables, and seeds.
Compiled model entities expose namespace-specific dense IDs, and semantic
pattern equality ignores source-only bond numbering and formatting.

`compile::Pattern` is the first concrete pattern seam. It is a
value-like descriptor that can be built directly from a resolved
`SpeciesGraph` (without reparsing source text) or from compact BNGL pattern
text for compiler-side fixtures. It carries molecule, site, state, bond, label,
and compartment constraints while keeping BNGcore graph ownership behind the
adapter. `PatternDescriptor` remains a source-compatible alias during
migration. Typed occurrence IDs are now part of the value contract, while
`compile::lowerPatternToBNGcore` is an explicit graph lowering boundary with
fingerprint parity coverage. `NFcore2::lowerPatternToNFsim` is the parallel
NFsim boundary: it validates molecule, state, bond, compartment, and
disconnected-pattern references before creating `TemplateMolecule` objects.
The adapter exists independently of the still-gated full Model-to-NFsim parity
migration.

The NFcore2 semantic expansion now carries finite graph expressions through matching and model-image serialization, resolves named local/DOR expression bindings, validates parent-linked compartment ancestry, and applies atomic species-carrying moves plus fail-closed conditional deletion. Native parser surfaces that require richer automorphisms, observable/function-scope evaluation, volume-aware transport, or unproven deletion spellings remain explicit compatibility fallbacks.

### Network-Free Path

```
.bngl file → ANTLR4 Parser → ast::Model
                                   │
                                   ▼
                         NFinput::buildSystemFromAst() → NFcore::System
                                   │
                                   ▼
                         System::sim() [Gillespie SSA on molecule instances]
                                   │
                                   ▼
                              Observable counts → numpy arrays
```

## C++ Libraries

| Library | Contents | Dependencies |
|---------|----------|--------------|
| `nauty` | Graph canonicalization (C) | None |
| `bng_core` | PatternGraph, Node, State, Ullmann | nauty |
| `bng_ast` | Model, Parameter, ReactionRule, Observable, ... | bng_core, ANTLR4 |
| `bng_parser` | ANTLR4 lexer/parser, BNGAstVisitor | bng_ast, ANTLR4 |
| `bng_compile` | Symbol resolution, capability reports, pattern descriptors, compiled rules/rate laws, energy plans | bng_ast |
| `bng_engine` | NetworkGenerator, OdeIntegrator, I/O writers, Actions, isolated batch CLI | bng_parser, SUNDIALS, Threads |
| `nfsim_core` | NFcore, NFinput, NFreactions, NFfunction | TinyXML, muParser |
| `bionetgen_core` | Interface library linking all above | All |

## External Dependencies

All fetched via CMake FetchContent and statically linked:

- **ANTLR4 C++ Runtime 4.13.1** — Parser generator runtime (~2MB)
- **SUNDIALS 7.6.0** (CVODE only) — ODE solver
- **Catch2 3.4.0** — C++ test framework
- **pybind11 2.13.6** — Python ↔ C++ bindings

## Build System

- **CMake 3.14+** — C++ build configuration
- **scikit-build-core** — Python packaging with CMake integration
- **pybind11** — Generates `_bionetgen_cpp` Python extension module

## Python Package Structure

```
python/bionetgen/
├── __init__.py         # Public API: load(), run()
├── model.py            # BioNetGenModel (wraps C++ Model)
├── result.py           # SimResult (numpy-based results)
├── cli.py              # Click CLI (bionetgen command)
├── compat/             # Legacy backward-compatibility
│   └── legacy_runner.py  # Perl subprocess fallback
├── atomizer/           # SBML→BNGL converter (pure Python)
├── core/               # Legacy PyBioNetGen core (retained)
├── modelapi/           # Legacy model API (retained)
├── simulator/          # Legacy simulator wrappers (retained)
└── network/            # Network representation (retained)
```

## NFSim Integration Strategy

The default NFSim route now constructs `NFcore::System` directly from the
canonical AST:

1. BNG C++ parses BNGL → `ast::Model`
2. `NFinput::buildSystemFromAst()` maps parameters, molecule types, species,
   observables, functions, energy patterns, and reaction rules
3. The model-derived universal traversal limit is applied (or an explicit
   Python `traversal_limit`/action `utl` value is honored)
4. `System::prepareForSimulation()` and `System::stepTo()` run the network-free
   simulation
5. Observable values are copied into NumPy arrays

The explicit `NFcore2::lowerPatternToNFsim` adapter is the value-pattern seam
for the direct path. The in-memory XML initializer remains an explicit
compatibility fallback and a shadow-comparison oracle while direct parity is
qualified. The on-disk XML
initializer is a last-resort compatibility path for legacy models. Direct
construction is fail-closed: unsupported AST constructs do not silently change
semantics by falling back unless the caller opts into XML compatibility.

An independent solver bridge is available only when configured explicitly with
`BUILD_BNGSIM_ADAPTER=ON`, `BNGSIM_INCLUDE_DIR`, and `BNGSIM_LIBRARY`. It maps
the generated network directly to BNGsim without writing a `.net` file, and
compiles BNGL `Molecules`/`Species` observable patterns with the same
BNGcore/Ullmann semantics used by the native network path, and lowers bounded
inline/absolute-path TFUN expressions to BNGsim table functions. It rejects
non-reference rate expressions, unsupported TFUN provenance, and unsupported
model/protocol surfaces before solver construction. The default build does not
require BNGsim; the optional path therefore does not establish NFsim/BNG2
parity.

The evaluated adapter preserves generated species, statistical factors, direct
elementary/function rate references, and pattern-weighted observables.
It was tested against BNGsim commit
`49dc939035f5a272da663f8c9586e3c9f0e1c041`; this evidence does not choose a
long-term network solver.
The scope and non-selection decision are recorded in
[ADR 0002](adr/0002-bngsim-adapter-scope.md).

### BNGIR document boundary

Python exposes deterministic, source-free BNGIR JSON v0.1 for the semantic
model and a separately scoped action protocol. The schema is versioned under
`provenance/schemas/bngir-0.1.schema.json`; generated networks, solver state,
and caches are excluded. Deserialization reconstructs supported model-only
documents and fails closed for population-map reconstruction or unsupported
protocol forms.

## Memory Management

- C++ `Model` is heap-allocated, owned by Python via `std::unique_ptr` + pybind11 holder
- `GeneratedNetwork` is returned by value (moved)
- `OdeResult` vectors are copied into numpy arrays at the binding boundary
- NFSim `System*` is explicitly deleted after simulation
- GIL is released during all long-running C++ operations
