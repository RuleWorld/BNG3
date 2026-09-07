# BNG3 energy compiler architecture

**Base:** `RuleWorld/BNG3` PR #2, head `3bc7b4ff131f8927421bc8eae170e3b248b75318`

## Goal

Preserve existing eBNGL/NFsim semantics while moving energy evaluation from
special-case NFsim expansion code toward a compiled, backend-neutral execution
plan.

```text
BNGL -> ast::Model -> compile::CompiledModel
                        |-- CompiledRule / mutation signatures
                        |-- energy::EnergyDeltaPlan
                        `-- dependency/update metadata
                                  |
                     +------------+------------+
                     |                         |
             network generation             NFsim
```

The compiler layer is immutable and contains no trajectory state.  Simulation
backends lower its plans into their own storage and scheduling structures.

## Phase-1 objects

### `CompiledRule`

`CompiledRule` converts `ast::ReactionRule::TransformOp` into a compact mutation
signature.  This makes rule locality explicit without reparsing BNGL or
reconstructing the reaction center in each backend.

### `EnergyDeltaPlan`

An energy plan represents

\[
\Delta G(c) = G_0 + \sum_j I_j(c)\epsilon_j,
\]

where each conditional term is guarded by a conjunction of local predicates.
For a complete context mask, the plan can evaluate `deltaG` or the Arrhenius
factor used by existing eBNGL semantics.  Small plans can compile directly to a
lookup table.

The current NFsim `EnergyBindingContext` becomes a compatibility view of this
plan.  Existing `EnergyRxnClass` execution and the materialized Sekar expansion
remain unchanged in phase 1.

### Reaction-center energy index

`EnergyFunction` now indexes energy factors by normalized binding center and by
state-changing component when factors are registered.  Relevance lookup therefore
queries candidate factors instead of scanning the complete energy-pattern list for
every energy rule.  Each factor is deduplicated per center so the index preserves
the legacy finder contract.

### `CompiledRateLaw`

Existing rate expressions are classified into typed compiler metadata without
changing evaluation.  In particular, `Arrhenius(phi,Ea)` becomes an
`ArrheniusEnergy` compiler object while retaining the original expression and
arguments.  This creates a safe seam for later energy-aware lowering without
changing BNGL semantics during convergence.

### `CompiledModel`

`CompiledModel` owns execution-facing rule metadata and a normalized catalog of
energy factors (source pattern, structural fingerprint, and energy expression).
It is deliberately immutable and is the future home for the energy dependency
index and trajectory-shareable model state.

## Compatibility contract

1. Existing BNGL/eBNGL syntax and accepted NFsim behavior remain the oracle.
2. The materialized Sekar expansion path remains available until compact
   lowering is independently qualified for a topology.
3. Unsupported plans fail closed; compilation must never silently weaken a
   pattern constraint.
4. Event work should eventually scale with the affected reaction neighborhood,
   not the total number of rules or energy patterns.
5. New thermodynamic semantics (barrier patterns, reservoirs, driven-rule
   annotations) are out of scope until existing eBNGL parity is complete.
6. `EnergyDeltaPlan` supports signed terms now so state-change plans and future
   graph-rewrite plans do not need a second mathematical representation.

## Next implementation slices

1. Lower constant and factorized binding plans directly from the compiler into
   NFsim while retaining materialized expansion as the fallback.
2. Promote the new reaction-center energy index into `CompiledModel` and join it
   with rule mutation signatures, giving the runtime explicit invalidation
   metadata in addition to compile-time candidate filtering.
3. Generalize context predicates beyond the current occupancy-only compact
   slice, including state predicates and safe context on either reactant.
4. Lower state-change `EnergyDeltaPlan`s into a weighted reaction class after
   independent parity tests establish the semantics.
5. Add immutable compiled-model caching and reuse across parameter sweeps and
   independent trajectories.
6. After parity, lower the already-typed `ArrheniusEnergy` compiler metadata
   directly instead of reinterpreting the source expression in each backend.
7. Only then add new language semantics such as barrier-energy factors and
   driven reservoirs.
8. Separately add indexed/parametric rule families for Rasi/genome-scale
   models, lowering them to compiled rule schemas rather than text expansion.

## Performance invariant

For an event changing local structure `d`, the target behavior is

```text
work(event) = O(affected local dependencies(d))
```

rather than work proportional to the total number of rules or energy patterns.
