# NFcore2 semantic expansion checkpoint

This checkpoint extends the tests-first NFsim/NFcore2 port on
`main`. It carries the six earlier semantic
families forward and opens four formerly explicit ceilings:

- population transforms;
- root-local graph and `connectedTo` predicates;
- synthesis transforms;
- root-local compartments and molecule moves;
- bounded local-function and DOR rate-law descriptors;
- complete species deletion.

The additional ceiling work is deliberately finite and fail-closed:

- arbitrary finite internal graph expressions with anchored and unanchored
  nodes, multiple exact bonds, state, compartment, free-site, and bound-site
  constraints;
- parsed local/DOR expressions with time, named state bindings, constants,
  conditionals, arithmetic, and built-in functions;
- parent-linked compartment ancestry and atomic connected-species movement;
- finite local-function/DOR expression scopes for reactant counts,
  connected-species counts, and compartment volumes;
- conditional single-molecule deletion that is suppressed when it would split
  a connected species, with conservative invalidation and malformed-bond
  rejection.

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

Before each implementation slice, assertions were added to
`tests/architecture_contracts/nfcore2/test_nfsim_adapter_contract.cpp`,
`test_transform_engine.cpp`, and `test_model_image_shadow.cpp`. RED evidence
covered missing graph constraints, named expression bindings, atomic move
validation, volume lookup/transport validation, and conditional deletion
invalidation/reciprocity. Earlier RED
evidence also covered population deltas, compartment metadata, move and
species-delete opcodes, and local/DOR rate-law fields.

After implementation, the focused CTest target passed:

```text
ctest --test-dir build --output-on-failure -R 'native-port|architecture_nfcore2_reference'
20/20 native-port tests ... Passed
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
complete species deletion, population decrement, internal graph topology,
compartment hierarchy metadata, species-carrying MoveConnected, and finite
connectedTo graph edges. Internal graph-node state, free/bound-site, and
compartment constraints are retained through lowering and model-image round
trips. Native local/DOR function objects and unresolved connectedTo forms remain
on the compatibility path until their scope and dependency extraction are
proven independently. The executable
NFcore2 slice resolves explicit reactant-count, connected-species-count, and
positive compartment-volume bindings; it does not claim native object-level
LocalFunction/DOR evaluation.

An independent literal oracle and JSON fixture cover all six family IDs under
`tests/energy/tests/python/test_nfcore2_semantic_expansion_oracle.py` and
`tests/energy/fixtures/semantic/nfcore2_semantic_expansion.json`. The oracle
does not import NFcore2 implementation code.

The post-fix validation set is also green:

```text
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure       # 281/281 passed
tests/energy/tests/python                         # 66 passed
tests/python                                       # 348 passed, 27 skipped
tests/validation -m smoke                         # 4 passed, 14 skipped
audit_architecture_contracts.py                   # passed; no failures
```

The repository sanitizer smoke executable also passed as CTest test
`energy_sanitizer_smoke`. No separate ASan/UBSan NFcore2 rebuild was present
for this checkpoint. LeakSanitizer detection is unavailable on this platform,
so leak coverage is not claimed here.

## Bounded direct support

Population molecule types receive a population feature and a `PopulationStore`
entry. Increment/decrement transforms lower to checked signed deltas, including
underflow/overflow protection. Zero-reactant population synthesis uses the
explicit added molecule type rather than an inferred reactant position.

Root-local state, bond, and compartment constraints are lowered directly.
Finite graph expressions use exact backtracking over live molecules, preserving
anchors, multiple internal bonds, state values, exact compartments, free/bound
sites, and reciprocal-bond requirements. Finite symmetric equivalent-site
constraints use injective candidate assignment; malformed, negative,
molecularity, richer-child, or unbounded forms fail closed. Root `connectedTo`
uses a graph search over live reciprocal bonds. Zero-reactant rules are eligible for synthesis/population lowering
rather than being classified as graph fallback.

Particle synthesis creates the requested molecule type and publishes it in the
transform context. Population `AddMoleculeTransform` is decoded as a signed
population increment. Complete species removal walks the live connected
component and removes every molecule while invalidating reciprocal bonds.

Compartment IDs use a stable FNV-1a hash of the legacy compartment identifier,
so the snapshot is parser-independent. A root-local compartment predicate,
ancestry predicate, single-molecule move, and atomic connected-species move are
executable and report compartment feature changes; positive volume lookup and
same-dimension transport ratios are validated, and unknown destinations are
rejected before mutation. Legacy scalar IDs are retained when no hierarchy
table exists. Dependency ownership follows the molecule type even when the
reactant position differs. Species deletion requires a mapped reactant before
it can execute.

The rate-law descriptor supports constant, local-linear, DOR-product, and
parsed expression laws. Expressions can bind arbitrary names to matched state
words, finite constants, reactant counts, connected-species molecule counts,
or positive compartment volumes and can use time, conditionals, arithmetic,
and the BNG expression built-ins. Results are checked for finite,
non-negative propensities. Rate-law fields participate in rule-family
signatures and state-feature dependencies, and model-image version 6
preserves the metadata.

## Deliberate remaining fallbacks

The broader unresolved goal remains: arbitrary internal graph expressions, general local-function/DOR evaluation, compartment hierarchy/species-carrying moves, conditional deletion, and independent full NFsim/BNG2 parity. The bounded contracts above are the proven subset of each ceiling.

The port remains fail-closed for semantics not proven by these contracts:

- richer native graph automorphisms beyond finite symmetric equivalent-site
  assignment, negative graph expressions, molecularity constraints,
  unsupported child constraints, and malformed or unbounded `connectedTo`
  forms;
- native local-function/DOR object evaluation with observable/complex scopes,
  function DAGs, TFUN counters, or complete DOR2 composition;
- compartment volume/region scaling beyond explicit volume bindings, dimension
  conversion, and transport that changes species topology while carrying
  spatial counts;
- native conditional-deletion spellings whose component ownership or
  post-delete invalidation cannot be established; unknown removal codes remain
  explicit lowering fallbacks;
- independent full NFsim/BNG2 parity, including seeded trajectories,
  propensity distributions, and failure classifications against independently
  built oracle binaries.

These residual ceilings are intentional in this checkpoint. They are tracked as
explicit fail-closed contracts so future work cannot silently replace the
compatibility path with an approximation.

These cases retain explicit fallback reasons. No NFsim, NFnext, Rasi, or uORF
parity claim follows from this checkpoint.
