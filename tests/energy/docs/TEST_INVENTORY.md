# Test inventory

The counts below are a historical bundle snapshot. The active repository test
inventory is defined by the current CMake files and the live status record in
[`docs/CURRENT_PROGRESS.md`](../../../docs/CURRENT_PROGRESS.md).

- C++ contract files: **42**
- C++ `TEST_CASE`s: **156**
- Python test files: **12**
- Python tests: **51**
- Energy fixtures/policies: **13**
- Validation/oracle scripts: **9**

## C++ contracts

- `tests/cpp/future_ast_native_pattern_descriptor.cpp` — 1 cases
- `tests/cpp/future_barrier_driving_syntax.cpp` — 2 cases
- `tests/cpp/future_batch_nf_api.cpp` — 1 cases
- `tests/cpp/future_blueprint_concurrency.cpp` — 1 cases
- `tests/cpp/future_compiled_blueprint.cpp` — 2 cases
- `tests/cpp/future_compiled_model_cache.cpp` — 6 cases
- `tests/cpp/future_compiled_model_determinism.cpp` — 2 cases
- `tests/cpp/future_compound_graph_rewrite.cpp` — 2 cases
- `tests/cpp/future_dependency_graph.cpp` — 4 cases
- `tests/cpp/future_dependency_graph_property.cpp` — 1 cases
- `tests/cpp/future_direct_xml_energy_parity.cpp` — 1 cases
- `tests/cpp/future_dynamic_energy_expression_policy.cpp` — 2 cases
- `tests/cpp/future_energy_context_evaluator.cpp` — 7 cases
- `tests/cpp/future_energy_context_weights.cpp` — 2 cases
- `tests/cpp/future_energy_context_weights_numeric.cpp` — 3 cases
- `tests/cpp/future_energy_factor_index.cpp` — 3 cases
- `tests/cpp/future_energy_feature_flag.cpp` — 2 cases
- `tests/cpp/future_energy_lowering_plan.cpp` — 7 cases
- `tests/cpp/future_energy_pattern_compiler.cpp` — 8 cases
- `tests/cpp/future_energy_pattern_store.cpp` — 3 cases
- `tests/cpp/future_energy_plan_canonicalization.cpp` — 5 cases
- `tests/cpp/future_energy_runtime_event_weights.cpp` — 1 cases
- `tests/cpp/future_energy_serialization_roundtrip.cpp` — 2 cases
- `tests/cpp/future_indexed_rule_family.cpp` — 8 cases
- `tests/cpp/future_legacy_binding_compatibility.cpp` — 3 cases
- `tests/cpp/future_molecularity_energy.cpp` — 1 cases
- `tests/cpp/future_parameter_rebinding.cpp` — 4 cases
- `tests/cpp/future_reaction_build_batch.cpp` — 5 cases
- `tests/cpp/future_runtime_invalidation.cpp` — 2 cases
- `tests/cpp/future_runtime_model_contracts.cpp` — 6 cases
- `tests/cpp/future_runtime_reverse_context.cpp` — 1 cases
- `tests/cpp/future_thermodynamic_constraints.cpp` — 9 cases
- `tests/cpp/fuzz_energy_delta_plan.cpp` — 0 cases
- `tests/cpp/standalone_energy_delta_plan_smoke.cpp` — 0 cases
- `tests/cpp/test_compiled_model_contracts.cpp` — 10 cases
- `tests/cpp/test_compiled_rate_law_contracts.cpp` — 4 cases
- `tests/cpp/test_pattern_descriptor_contracts.cpp` — 5 cases
- `tests/cpp/test_energy_compiler_phase1.cpp` — 5 cases
- `tests/cpp/test_energy_delta_plan_edge_cases.cpp` — 16 cases
- `tests/cpp/test_energy_delta_plan_property.cpp` — 1 cases

## Python self-tests

- `tests/python/test_cmake_inventory.py` — 2 tests
- `tests/python/test_compare_numeric_tables.py` — 5 tests
- `tests/python/test_env_isolation.py` — 2 tests
- `tests/python/test_exact_output_parity.py` — 2 tests
- `tests/python/test_fixture_generator.py` — 3 tests
- `tests/python/test_performance_gate.py` — 5 tests
- `tests/python/test_semantic_oracle.py` — 5 tests
- `tests/python/test_statistical_parity_metrics.py` — 12 tests
- `tests/python/test_validation_manifest.py` — 2 tests
- `tests/python/test_validation_policy.py` — 2 tests

## Fixtures and policy

- `fixtures/energy/bound_mixed_reverse.bngl`
- `fixtures/energy/constant_binding.bngl`
- `fixtures/energy/correlated_two_hop_fallback.bngl`
- `fixtures/energy/mixed_reactant_state_context.bngl`
- `fixtures/energy/no_relevant_factor.bngl`
- `fixtures/energy/reactant0_state_context.bngl`
- `fixtures/energy/reactant1_state_context.bngl`
- `fixtures/energy/same_type_binding.bngl`
- `fixtures/energy/shared_predicate_factors.bngl`
- `fixtures/energy/state_change_local_context.bngl`
- `fixtures/energy/symmetric_sites.bngl`
- `fixtures/energy/validation_manifest.json`
- `fixtures/energy/validation_policy.json`

## Scripts

- `scripts/__init__.py`
- `scripts/compare_numeric_tables.py`
- `scripts/energy_performance_gate.py`
- `scripts/energy_semantic_oracle.py`
- `scripts/exact_output_parity.py`
- `scripts/generate_boolean_context_fixture.py`
- `scripts/measure_command.py`
- `scripts/nf_energy_statistical_parity.py`
- `scripts/run_energy_validation.py`
