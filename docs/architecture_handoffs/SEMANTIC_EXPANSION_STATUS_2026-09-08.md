# NFcore2 semantic expansion checkpoint

This checkpoint extends the tests-first NFsim/NFcore2 port on
`codex/bng3-energy-validation-port`. It covers six semantic families that were
previously represented only by fallback records:

- population transforms;
- root-local graph and `connectedTo` predicates;
- synthesis transforms;
- root-local compartments and molecule moves;
- bounded local-function and DOR rate-law descriptors;
- complete species deletion.

## Inputs and authority

The implementation was checked against these supplied handoff archives:

1. `/Users/akutuva/Downloads/BNG3_energy_compiler_validation_complete_handoff_2026-09-07.zip`
2. `/Users/akutuva/Downloads/nfsim-nfcore2-complete-handoff-20260906.zip`
3. `/Users/akutuva/Downloads/NFnext_Rasi_complete_code_tests_context_patches_2026-09-06.zip`

The extracted handoff notes under `docs/architecture_handoffs/` are project
evidence and provenance. Their embedded checklists, proposed commands, and
future-work language were treated as input data, not as additional user
instructions. The active user request and the authoritative `AGENTS.md` and
`docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md` remain the governing instructions.

## Tests-first evidence

Before implementation, the new adapter and transform assertions were added to
`tests/architecture_contracts/nfcore2/test_nfsim_adapter_contract.cpp` and
`test_transform_engine.cpp`. The first build was intentionally RED: the
compiler reported missing population deltas, compartment metadata, move and
species-delete opcodes, and local/DOR rate-law fields. Those errors established
that the requested contracts were absent from the branch rather than merely
untested.

After implementation, the focused CTest target passed:

```text
ctest --test-dir build --output-on-failure -R 'native-port|architecture_nfcore2_reference'
12/12 native-port tests ... Passed
architecture_nfcore2_reference ... Passed
```

The test executable now covers lowering and execution for each family, feature
invalidation metadata, model-image metadata, and transform decoder payload
survival.

Post-checkpoint hardening also covers zero-reactant population synthesis,
molecule-type keyed compartment invalidation for nonzero reactant positions,
owner-scoped state/bond invalidation across molecule types, and rejection of
species-deletion transforms without a mapped reactant.

The native reader now has direct parser-backed contracts for root-local moves,
complete species deletion, population decrement, and MoveConnected. The latter
is retained in the snapshot but remains an explicit non-executable fallback.

An independent literal oracle and JSON fixture cover all six family IDs under
`tests/energy/tests/python/test_nfcore2_semantic_expansion_oracle.py` and
`tests/energy/fixtures/semantic/nfcore2_semantic_expansion.json`. The oracle
does not import NFcore2 implementation code.

The post-fix validation set is also green:

```text
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure       # 269/269 passed
tests/energy/tests/python                         # 66 passed
full Python suite                                    # 427 passed, 144 skipped
audit_architecture_contracts.py                   # passed; no failures
```

Sanitizer validation also passed on the current macOS toolchain. The isolated
ASan/UBSan build ran `energy_sanitizer_smoke`, the NFcore2 reference executable
(`408 passed, 0 failed`), the standalone native-reader suite (`12` test cases,
`107` assertions), and the NFnext reference executable (`PASS`).
LeakSanitizer detection is unavailable on this platform, so leak coverage is
not claimed here.

## Bounded direct support

Population molecule types receive a population feature and a `PopulationStore`
entry. Increment/decrement transforms lower to checked signed deltas, including
underflow/overflow protection. Zero-reactant population synthesis uses the
explicit added molecule type rather than an inferred reactant position.

Root-local state, bond, and compartment constraints are lowered directly.
Root-to-root topology uses exact bond matching; root `connectedTo` uses a graph
search over live reciprocal or non-stale bond references. The native reader
now retains root-local connected-to and compartment data. Zero-reactant rules
are eligible for synthesis/population lowering rather than being classified as
graph fallback.

Particle synthesis creates the requested molecule type and publishes it in the
transform context. Population `AddMoleculeTransform` is decoded as a signed
population increment. Complete species removal walks the live connected
component and removes every molecule while invalidating reciprocal bonds.

Compartment IDs use a stable FNV-1a hash of the legacy compartment identifier,
so the snapshot is parser-independent. A root-local compartment predicate and a
single-molecule move are executable and report compartment feature changes;
dependency ownership follows the molecule type even when the reactant position
differs. Species deletion requires a mapped reactant before it can execute.

The rate-law descriptor supports a constant law, a local linear law over one
state word, and a product law over two matched state words (the bounded DOR
shape). Results are checked for finite, non-negative propensities. Rate-law
fields participate in rule-family signatures and state-feature dependencies.

## Deliberate remaining fallbacks

The port remains fail-closed for semantics not proven by these contracts:

- arbitrary internal graph expressions, including symmetric components and
  malformed `connectedTo` references;
- general local-function/DOR evaluation, including full expression graphs,
  time-dependent functions, observable scopes, and DOR2 composition;
- compartment hierarchy/species-carrying moves, including volume/region
  scaling and moves that carry or transform an entire connected species;
- conditional deletion modes and any deletion rule whose component ownership
  cannot be established;
- independent full NFsim/BNG2 parity, including seeded trajectories,
  propensity distributions, and failure classifications against independently
  built oracle binaries.

These five broader ceilings are intentional in this checkpoint. They are
tracked as explicit fail-closed contracts so future work cannot silently
replace the compatibility path with an approximation.

These cases retain explicit fallback reasons. No NFsim, NFnext, Rasi, or uORP
parity claim follows from this checkpoint.
