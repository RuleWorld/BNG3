# Architecture

The live branch and validation snapshot for this architecture are maintained
in [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md). This page describes the
architecture, not completion of every convergence gate.

The canonical semantic-model boundary and staged migration policy are defined
in [ADR 0001](adr/0001-canonical-semantic-model-and-layer-boundaries.md).
This page describes the current implementation layout; it does not imply
that every planned semantic/backend seam is complete.

The current continuation adds a bounded production-boundary NFnext contract
and makes the direct
NFsim construction path observable to validation. These contracts strengthen
the migration boundary without claiming complete backend equivalence.

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

The first production NFnext bridge is exercised by an architecture contract:
BNGL parser -> `bng::compile::CompiledModel` ->
`nfnext::lowerFromBioNetGen`. For the bounded rule
`A(x~u) + B(y) -> A(x~p!1).B(y!1) k`, it checks two distinct reactants,
`DifferentComplex`, the state transition, and `Bind`. The corresponding Lean
example checks the same typed NFnext shape independently. This is one tested
slice, not a proof of complete source-free lowering.

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
Validation records `construction_path` and requires the direct leg to report
`direct`; the XML shadow leg must report `in-memory-xml`. Source-tree workers
also receive explicit repository-root and `python/` import paths so ensemble
evidence cannot depend on the caller's environment.

### Finite-network backend boundary (ADR 0003)

BNG3 treats finite-network numerics as an external concern owned by **BNGsim**
where semantics are supported. The boundary is narrow and explicit:

- `cpp/engine/FiniteBackend.{hpp,cpp}` owns the `FiniteBackend` enum
  (`native`/`bngsim`), `BngsimCapabilities` (`available`, `version`,
  `supportsOde/Ssa/Psa`), and `BngsimLoweringCheck` (`supported`, `blockers`).
  It never throws on capability queries and centralizes the
  `resolveFiniteBackend()` decision.
- `cpp/engine/BngsimAdapter.{hpp,cpp}` is the sole lowering that translates a
  `GeneratedNetwork` into `bngsim::NetworkModel` in memory (no `.net`
  serialization). It compiles BNGL `Molecules`/`Species` observables with the
  same BNGcore/Ullmann semantics as the native path and lowers bounded
  inline/absolute-path TFUN expressions to BNGsim table functions.
- `cpp/engine/BngsimBackend.{hpp,cpp}` owns simulation execution on the lowered
  model (`simulateOdeViaBngsim`, `simulateSsaViaBngsim`) and the single result-
  adaptation boundary `convertBngsimResult → OdeResult` (time, concentration
  ordering, observable names/values, initial/final point, sample-times,
  error handling).

The Python layer (`python/bionetgen/model.py:BioNetGenModel.simulate`) is the
primary dispatch:

```
model.simulate(method="ode") ─┐
model.simulate(method="ssa") ─┼─ finite network → FiniteBackend → BNGsim (preferred, opt-in)
model.simulate(method="nf")  ─── rule model → NFsim (independent)
```

- `backend="auto"` (default) keeps `native` during migration for stability;
  developers/CI may set `backend="bngsim"` or `BIONETGEN_FINITE_BACKEND=bngsim`
  to exercise the BNGsim path for supported models.
- Unsupported forms fail closed before solver construction with
  `BNGsim adapter rejected …` and are surfaced as
  `BioNetGen finite-network backend cannot represent …`; `method="nf"` is never
  routed through BNGsim.
- The BNGsim bridge is available only when configured with
  `BUILD_BNGSIM_ADAPTER=ON`, `BNGSIM_INCLUDE_DIR`, and `BNGSIM_LIBRARY`. The
  default build does not require BNGsim. The adapter rejects non-reference rate
  expressions, unsupported TFUN provenance, and unsupported model/protocol
  surfaces (compartments, energy/barrier patterns, `driven_by()`, population
  maps, protocol actions, local-function arguments) before solver construction.
- Result adaptation converts the BNGsim trajectory to the existing BNG3
  `SimResult` semantics; `SimResult.backend` (`"native"`/`"bngsim"`/`"nfsim"`)
  is exposed for test/diagnostics without breaking result compatibility.

The evaluated adapter preserves generated species, statistical factors, direct
elementary/function rate references, and pattern-weighted observables.
It was tested against BNGsim commit
`49dc939035f5a272da663f8c9586e3c9f0e1c041`. The selection of BNGsim as the
intended canonical finite backend and the full rejection inventory are recorded
in [ADR 0003](adr/0003-bngsim-canonical-finite-backend.md) and
[bngsim-migration-status.md](bngsim-migration-status.md); ADR 0002 remains the
historical evaluation record.

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
