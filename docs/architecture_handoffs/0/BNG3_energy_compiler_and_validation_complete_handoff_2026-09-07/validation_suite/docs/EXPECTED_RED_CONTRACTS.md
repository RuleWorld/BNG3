# Intentional RED contracts

These tests are specifications for proposed APIs and are excluded unless
`BNG_ENABLE_FUTURE_ENERGY_CONTRACTS=ON`.

They should be enabled one subsystem at a time as implementation lands.

- `future_dependency_graph*`: `compile/dependency/DependencyGraph.hpp`
- `future_energy_pattern_compiler`: generalized `EnergyPatternCompiler`
- `future_energy_lowering_plan`: backend-neutral lowering policy
- `future_energy_pattern_store`: versioned/orientation-safe plan cache
- `future_energy_context_weights`: tested aggregation math
- `future_thermodynamic_constraints`: cycle/rank/gauge analysis
- `future_indexed_rule_family`: parametric rule-family IR
- `future_compiled_model_cache`: concurrent immutable model cache
- `future_ast_native_pattern_descriptor`: direct `SpeciesGraph` compilation
- `future_reaction_build_batch`: transactional NFsim construction
- `future_runtime_*`: generalized mapping-local/pair-factorized NFsim reactions
- `future_compiled_blueprint`, `future_batch_nf_api`, `future_blueprint_concurrency`:
  compile-once/many-trajectory execution
- `future_parameter_rebinding`: parameter-safe blueprint reuse
- `future_dynamic_energy_expression_policy`: explicit policy for dynamic energies
- `future_energy_serialization_roundtrip`: no energy loss through compatibility writers
- `future_direct_xml_energy_parity`: direct AST vs XML semantic parity
- `future_compound_graph_rewrite`: energy delta of a general graph edit
- `future_energy_factor_index`: sublinear candidate discovery
- `future_barrier_driving_syntax`: deliberately last; parser syntax must not be enabled
  until existing eBNGL semantics and runtime parity are complete.

A RED contract becoming green is not enough to enable a feature by default; the
promotion matrix in `docs/VALIDATION_MATRIX.md` still applies.
