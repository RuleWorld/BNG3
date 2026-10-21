# ADR 0003: BNGsim as canonical finite-network numerical backend

- Status: Accepted (intended canonical backend; migration in phases)
- Date: 2026-09-17
- Scope: Finite-network numerical execution (ODE/SSA/PSA); NFsim explicitly out of scope
- Supersedes: nothing; ADR 0002 remains historical decision record for the adapter evaluation phase

> Current implementation status is tracked in
> [`docs/CURRENT_PROGRESS.md`](../CURRENT_PROGRESS.md) and
> [`docs/bngsim-migration-status.md`](../bngsim-migration-status.md).
> This ADR records the intended backend ownership; it does not imply that the
> migration is complete.

## Context

BNG3 currently duplicates finite-network numerical execution:

- `cpp/engine/OdeIntegrator.cpp` owns CVODE/Euler/RK4, SSA, observable projection,
  and TFUN handling for generated networks.
- `lanl/bngsim` independently implements modern finite-network numerical
  capabilities: CVODE ODE integration, SSA/PSA, CVODES sensitivities, KINSOL
  steady states, Jacobian sparsity and sparse linear algebra, conservation-law
  reduction, and event handling.

Maintaining two full numerical stacks is unnecessary. BNG3's comparative
advantage is BNGL rule semantics, parsing, compilation (`CompiledModel`),
rule expansion, network generation, observable semantics, and interchange
(BNGL, BNGXML, `.net`, SBML). BNGsim is externally maintained and its public
C++/Python interfaces must be treated as an external dependency — BNG3 cannot
redesign or vendor it.

The existing adapter (`cpp/engine/BngsimAdapter.*`) already constructs a
`bngsim::NetworkModel` in memory without `.net` serialization and was validated
against BNGsim `49dc939035f5a272da663f8c9586e3c9f0e1c041` as a bounded feasibility
spike. ADR 0002 kept `BUILD_BNGSIM_ADAPTER=OFF` and deferred selection of a
preferred solver pending parity evidence. That evidence boundary remains: the
adapter is not proof of BNG2/NFsim semantic parity.

## Decision

**BNGsim is the intended canonical numerical backend for generated finite
reaction networks in BNG3.**

Concretely:

- Finite-network methods (`ode`, `ssa`, `psa`, `pla` where equivalent) route
  through a narrow BNG3→BNGsim lowering layer when the model is faithfully
  representable and a compatible BNGsim build is available.
- BNG3-native finite solvers remain available during migration as
  compatibility, reference, and fallback implementations. They are not deleted
  until semantic coverage and parity gates pass.
- BNGsim remains optional (`BUILD_BNGSIM_ADAPTER=OFF` by default) while
  migration and parity are incomplete. Phase 2 prefers BNGsim automatically
  for the supported subset with native fallback; Phase 3 (packaged dependency)
  requires explicit maintainer decision.
- Network-free execution through NFsim/NFnext remains a separate BNG3 path
  and is **explicitly out of scope** for this backend decision. `method="nf"`
  is not routed through BNGsim.
- PyBioNetGen-facing syntax remains stable. Internal architecture may change
  radically; user syntax (`bionetgen.load`, `model.simulate(method="ode", ...)`,
  `bionetgen.run`, `bionetgen.bngmodel`) must not be gratuitously broken.
- Unsupported semantic forms fail closed (explicit fallback or precise
  `unsupported-capability` error). No silent approximation.

## Ownership boundary

### BNG3 owns

BNGL lexical/syntactic parsing, AST (`ast::Model`), `CompiledModel`,
rule/molecule/component/state/bond graph semantics, canonical graph handling,
rule matching, reaction-center semantics, rule expansion, finite network
generation (`GeneratedNetwork`), observable semantics, BNGL functions and local
functions as source-language constructs, compartment semantics, energy/barrier
pattern semantics, population maps, action/protocol parsing, TFUN source
semantics, exporters, BNGXML, `.net` generation, SBML/SBML-Multi interchange,
BNGIR, Python `bionetgen` interface, and NFsim/NFnext lowering and execution.

### BNGsim owns (for a finite generated network, where supported)

ODE RHS execution, CVODE, SSA, PSA, numerical Jacobians (analytical when
available), Jacobian sparsity, sparse linear solves, forward sensitivities,
steady-state solving (KINSOL), conservation-law numerical reduction, numerical
event handling, solver tolerances, batch finite-network solves, and
finite-network numerical state management.

BNG3 must not grow a competing high-level numerical-analysis framework for
these features.

## Integration contract

- The lowering input moves incrementally away from raw `ast::Model` access
  toward `CompiledModel` / resolved semantic structures; no blocking IR rewrite.
  The adapter translates a fully resolved finite network into the public
  representation expected by BNGsim — it does not reinterpret BNGL.
- Ideally only `BngsimAdapter.*`, `BngsimBackend.*`, `FiniteBackend.*`, tests,
  and CMake wiring directly include BNGsim headers. The boundary is narrow
  (`buildBngsimNetwork` / `toBngsim` / `simulateFinite`); BNGsim APIs are not
  part of BNG3's public Python surface and `bngsim::NetworkModel` is not
  exposed to normal users.
- Public dependency is pinned and version-aware
  (`provenance/upstreams.lock.yml`, `BNGSIM_INCLUDE_DIR`/`BNGSIM_LIBRARY`);
  only public BNGsim APIs are consumed.

## Capability and lowering checks

BNG3 distinguishes two questions:

1. **Is BNGsim available and which version/API was built against?**
   `BngsimCapabilities { available, version, supportsOde, supportsSsa, supportsPsa }`

2. **Can this particular generated network and requested simulation be
   faithfully lowered?**
   `BngsimLoweringCheck { supported, blockers: UnsupportedFeature[] }`

Both are explicit objects, not exception-text parsing. Blockers are classified
(Type A = BNG3 lowering gap, Type B = BNGsim capability gap, Type C =
inherently rule-level/network-free semantics resolved before the boundary).

## Simulation routing

```
model.simulate(method="ode")       ─┐
model.simulate(method="ssa")       ─┼─ finite network → BNGsim (preferred, with fallback)
model.simulate(method="psa"/"pla") ─┘  evaluated per-method for equivalence
model.simulate(method="nf")        ─── rule model → NFsim (independent)
```

During migration an opt-in switch selects the backend:

```python
model.simulate(method="ode", backend="bngsim")  # backend ∈ {"auto","native","bngsim"}
# or
BIONETGEN_FINITE_BACKEND=bngsim  # env var for CI/developers
```

`backend="auto"` is the default: BNGsim when available and faithfully
lowerable, otherwise explicit native fallback with diagnostic metadata
(`result.backend` or log). Result adaptation converts the BNGsim result to
the existing BNG3 `SimResult` semantics — time coordinates, concentration
ordering, observable names/values, initial/final point behavior, explicit
sample times, and error handling must be parity-checked. The rest of BNG3
does not know which backend ran.

## Rejection surface (summary)

The adapter currently rejects — before solver construction — at least:

- compartments (volume-aware bridge required)
- energy/barrier patterns and `driven_by()` reservoir work (eBNGL rate bridge)
- population maps (generated-network vs population semantics)
- simulation protocol / actions other than `generate_network`
- local-function arguments (`function(args)` bridge)
- relative TFUN paths lacking source-directory provenance
- non-reference reaction rate expressions (not a direct parameter or bounded function reference)

The full inventory is in `docs/bngsim-migration-status.md` and is
machine-readable via `checkBngsimLowering` and tested per feature.

## Consequences

- Adapter/lowering coverage becomes a first-class roadmap with explicit
  Type A/B/C classification.
- BNG3 stops adding duplicate numerical-analysis features where BNGsim already
  owns them (Jacobians, sparse solves, sensitivities, steady states,
  conservation laws).
- CI exercises both native and BNGsim paths during migration; parity gates
  (RHS-level, trajectory at 1e-8–1e-10, observables, failure parity, seed
  reproducibility for SSA, distributional checks) must pass before promotion.
- Promotion to default requires trajectory parity across the supported corpus
  (`simple_system`, `gene_expr`, `michment`, `blbr`, `Motivating_example`,
  `egfr_net`, `Repressilator`, `CaOscillate_Func`, `localfunc`, `test_tfun_*`,
  etc.) and independent-oracle evidence where applicable.
- Deletion of native solvers requires explicit parity evidence and maintainer
  review; tests remain before deletion.
- BNG3→BNGsim execution remains in-memory (no `.net` serialization).

## Validation

Use the existing validation spine (`scripts/validate*.py`,
`tests/validation/`, `tests/cpp/test_bngsim_adapter.cpp`, `ctest`, and
Python `pytest`), extended with:

- adapter construction tests (species ordering, parameters, ICs, reactants/
  products, stoichiometry, elementary/functional rates, observables, TFUN)
- rejection tests per unsupported semantic class
- ODE/SSA parity tests (native vs BNGsim differential harness)
- compatibility tests (user syntax unchanged)
- NFsim regression tests (unchanged)

See `docs/architecture.md` for the runtime layer diagram.

## Alternatives considered

- **Keep native solvers as primary:** retains duplication, diverges from
  externally maintained numerics, and requires BNG3 to reimplement sensitivities,
  sparse Jacobians, and steady-state solvers already in BNGsim.
- **Vendor/fork BNGsim:** would make BNG3 own an external project's numerics
  and is explicitly rejected.
- **Catalyst/SciML-style public API (`ODEProblem`/`solve`/`remake`):** cleaner
  for a greenfield numerical library but violates BioNetGen/PyBioNetGen
  compatibility; rejected per §3.1.

## References

- `docs/adr/0002-bngsim-adapter-scope.md` (evaluation phase, not selected as default)
- `docs/architecture.md`
- `docs/bngsim-migration-status.md` (live rejection inventory & Type A/B/C)
- `provenance/upstreams.lock.yml` (pinned BNGsim revision)
