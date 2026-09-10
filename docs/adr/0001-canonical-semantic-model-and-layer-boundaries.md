# ADR 0001: Canonical semantic model and layer boundaries

- Status: Accepted for staged migration
- Date: 2026-09-07
- Scope: BNG3 parser, semantic model, compilers, and execution backends

> Current implementation status is tracked in
> [`docs/CURRENT_PROGRESS.md`](../CURRENT_PROGRESS.md). This ADR remains the
> architectural decision; it is not a completion claim for the active port.

## Context

BNG3 currently uses `bng::ast::Model` as both the result of parsing and the
input to multiple backend-specific compilers. That is practical for source
compatibility, but it blurs three different kinds of state:

1. source syntax and unresolved names;
2. the resolved BNGL model and its scientific semantics;
3. mutable compiler/runtime structures such as graph caches, matcher indexes,
   generated species, solver state, and NFsim reaction objects.

The ambiguity makes backend replacement risky. It also encourages semantic
dispatch from source strings and makes it difficult to compile one model for
multiple independent trajectories.

## Decision

BNG3 will use three explicit conceptual layers:

```text
ModelDraft / parser state
        -> resolved semantic Model
        -> backend-specific compiled representation
```

The existing `bng::ast::Model` remains the compatibility-facing class during
the migration. We will not create a second independent full model IR beside
it. Instead, the class is progressively cleaned up and gains explicit
resolution and compilation seams.

The durable model boundary is conceptually a `Document` containing:

- a resolved `Model` for molecule types, compartments, parameters, functions,
  initial conditions, observables, energy patterns, reaction rules, and
  semantic options;
- a `SimulationProtocol` for simulate actions, solver/output settings,
  scans, execution limits, and writer/export actions;
- feature declarations, metadata/provenance, and source mapping.

Backends own their compiled and mutable state. Examples include
`BNGcore::PatternGraph`, canonicalization and matcher caches, generated
network arrays, ODE structures, NFsim templates/mappings/reaction classes,
and trajectory state. These objects must not become semantic ownership in the
canonical model.

## Invariants

- Parsing may retain source spelling, source spans, aliases, and unresolved
  identifiers; backend compilation may not rely on those unresolved forms.
- Semantic names are resolved once before backend compilation. Names remain in
  symbol tables for diagnostics and round-tripping, but runtime dispatch does
  not identify semantic families by reparsing raw strings.
- The staged `bng::compile::SymbolTable` owns namespace-specific typed IDs;
  `CompiledRateLaw` records resolved parameter/function/observable references,
  and `CompiledRule` records typed modifiers while preserving source spelling
  for compatibility and diagnostics.
- `bng::compile::Pattern` is the first backend-independent pattern seam: it can
  compile a resolved `SpeciesGraph` into value-like molecule/site constraints
  with typed occurrence IDs and bond groups, without reparsing source text.
  `PatternDescriptor` remains a source-compatible alias; explicit backend
  lowering to BNGcore and NFsim `TemplateMolecule` graphs is covered by
  separate adapters and contract tests. The full direct Model-to-NFsim
  migration remains independently gated by parity evidence.
- `bng::compile::Document` separates immutable compiled model metadata from a
  copied `SimulationProtocol`; protocol actions are not part of model identity.
- A resolved model has no mutable trajectory state and can be compiled more
  than once without changing its meaning.
- Unsupported backend features fail closed with a stable diagnostic or an
  explicitly selected compatibility path; they must not silently change model
  semantics.
- Backend-specific optimization is allowed to change representation, not the
  resolved model contract.

## Migration sequence

1. Keep `bng::ast::Model` and existing public behavior stable while current
   BNG2/NFsim parity gates are frozen.
2. Extract compiler caches and runtime state from semantic entities. The first
   checkpoint moves `ReactionRule` matcher, iteration, synthesis, and reverse
   rule state into `ReactionRule::ExecutionState`; `NetworkGenerator` owns one
   context per generation, while legacy no-state calls remain shims.
3. Add typed symbol resolution, diagnostics, rate-law families, and modifier
   representations. The compile layer now has the first structured feature
   inference, fail-closed capability-reporting seam, and expression-reference
   validation.
4. Introduce a backend-independent value-like `Pattern`, then add explicit
   lowering to BNGcore and NFsim representations.
5. Separate document protocol state from reusable model state.
6. Add BNGIR serialization only after the resolved model and backend seams are
   stable.

The current `bng::compile` seam and NFcore2/NFnext prototypes are staged
compiler work, not a claim that the migration is complete. Direct NFsim
lowering remains independently gated against the compatibility/XML path until
the full parity matrix is green.

## Consequences

Positive:

- one semantic model can serve network, NFsim, Python, and future backends;
- compile-once/instantiate-many becomes possible without sharing trajectory
  state;
- diagnostics, dependency analysis, serialization, and code generation gain a
  stable input;
- specialized NFsim and Rasi representations remain possible without forcing
  their data structures into the semantic model.

Costs and constraints:

- adapters and temporary compatibility seams are required during migration;
- existing source and public API compatibility takes priority over namespace
  cleanup;
- every backend change needs semantic tests plus parity evidence, not only
  type-level compilation.

## Validation

The architecture is accepted as a staged decision, not as a completion claim.
The current checkpoint is validated by the full local Release/Ninja CTest
suite, energy Python contracts, architecture inventory audit, and native
NFcore2 lowering tests. Independent BNG2/NFsim oracle locks, full direct-path
parity, real Rasi/uORF fixtures, and BNGIR round-trip tests remain required
before the corresponding migration phases can be closed.

See [architecture.md](../architecture.md),
[BNG3_HANDOFF_PORT_STATUS.md](../BNG3_HANDOFF_PORT_STATUS.md), and the
convergence checklist for current evidence and open gates.
