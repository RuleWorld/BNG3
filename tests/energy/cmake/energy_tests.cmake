# Include from tests/cpp/CMakeLists.txt after Catch2 and bionetgen_core are available.
option(BNG_ENABLE_FUTURE_ENERGY_CONTRACTS "Build RED contracts for planned energy/compiler APIs" OFF)
option(BNG_BUILD_ENERGY_FUZZERS "Build libFuzzer targets for energy compiler" OFF)

set(BNG_ENERGY_CURRENT_TEST_SOURCES
    test_energy_compiler_phase1.cpp
    test_energy_delta_plan_edge_cases.cpp
    test_energy_delta_plan_property.cpp
    test_compiled_rate_law_contracts.cpp
    test_compiled_model_contracts.cpp
)

add_executable(test_energy_compiler_contracts ${BNG_ENERGY_CURRENT_TEST_SOURCES})
target_include_directories(test_energy_compiler_contracts PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${exprtk_SOURCE_DIR}
)
target_link_libraries(test_energy_compiler_contracts PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_compile bionetgen_core bng_parser)
catch_discover_tests(test_energy_compiler_contracts
    TEST_PREFIX "energy::"
    PROPERTIES LABELS "energy;compiler")

# Keep source-original contracts separate because their Catch2 names overlap
# with the adapted phase-1 contracts.
add_executable(test_energy_compiler_original test_energy_compiler_original.cpp)
target_include_directories(test_energy_compiler_original PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${exprtk_SOURCE_DIR}
)
target_link_libraries(test_energy_compiler_original PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_compile bionetgen_core bng_parser)
catch_discover_tests(test_energy_compiler_original
    TEST_PREFIX "energy-original::"
    PROPERTIES LABELS "energy;compiler;source-original")

set(BNG_ENERGY_FUTURE_CONTRACT "" CACHE STRING "Single future energy contract stem to build")
if(BNG_ENABLE_FUTURE_ENERGY_CONTRACTS OR BNG_ENERGY_FUTURE_CONTRACT)
    set(BNG_ENERGY_FUTURE_TEST_SOURCES
        future_dependency_graph.cpp
        future_dependency_graph_property.cpp
        future_energy_pattern_compiler.cpp
        future_energy_lowering_plan.cpp
        future_energy_pattern_store.cpp
        future_energy_context_weights.cpp
        future_energy_context_evaluator.cpp
        future_energy_context_weights_numeric.cpp
        future_energy_plan_canonicalization.cpp
        future_thermodynamic_constraints.cpp
        future_indexed_rule_family.cpp
        future_compiled_model_cache.cpp
        future_compiled_model_determinism.cpp
        future_ast_native_pattern_descriptor.cpp
        future_reaction_build_batch.cpp
        future_runtime_model_contracts.cpp
        future_energy_runtime_event_weights.cpp
        future_compiled_blueprint.cpp
        future_batch_nf_api.cpp
        future_legacy_binding_compatibility.cpp
        future_barrier_driving_syntax.cpp
        future_direct_xml_energy_parity.cpp
        future_energy_serialization_roundtrip.cpp
        future_compound_graph_rewrite.cpp
        future_energy_factor_index.cpp
        future_parameter_rebinding.cpp
        future_dynamic_energy_expression_policy.cpp
        future_blueprint_concurrency.cpp
        future_runtime_invalidation.cpp
        future_runtime_reverse_context.cpp
        future_molecularity_energy.cpp
        future_energy_feature_flag.cpp
    )
    if(BNG_ENERGY_FUTURE_CONTRACT)
        if(NOT "${BNG_ENERGY_FUTURE_CONTRACT}.cpp" IN_LIST BNG_ENERGY_FUTURE_TEST_SOURCES)
            message(FATAL_ERROR "Unknown energy contract: ${BNG_ENERGY_FUTURE_CONTRACT}")
        endif()
        set(BNG_ENERGY_FUTURE_TEST_SOURCES "${BNG_ENERGY_FUTURE_CONTRACT}.cpp")
    endif()
    add_executable(test_energy_future_contracts ${BNG_ENERGY_FUTURE_TEST_SOURCES})
    target_include_directories(test_energy_future_contracts PRIVATE
        ${CMAKE_SOURCE_DIR}/cpp
        ${CMAKE_SOURCE_DIR}/cpp/nfsim
        ${CMAKE_SOURCE_DIR}/cpp/nfsim/NFcore
        ${CMAKE_SOURCE_DIR}/cpp/nfsim/NFinput
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${exprtk_SOURCE_DIR}
    )
    target_compile_definitions(test_energy_future_contracts PRIVATE
        BNG_ENERGY_FIXTURE_DIR="${CMAKE_SOURCE_DIR}/tests/energy/fixtures/energy")
    target_link_libraries(test_energy_future_contracts PRIVATE
        Catch2::Catch2WithMain Catch2::Catch2 bng_compile bionetgen_core bng_parser)
    catch_discover_tests(test_energy_future_contracts
        TEST_PREFIX "energy-future::"
        PROPERTIES LABELS "energy;energy-future")
endif()

option(BNG_ENERGY_SANITIZER_SMOKE "Build instrumented deterministic energy input checks" OFF)
if(BNG_ENERGY_SANITIZER_SMOKE)
    if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
        message(FATAL_ERROR "Energy sanitizer checks require Clang or GCC")
    endif()
    add_executable(energy_sanitizer_smoke
        energy_fuzz_smoke.cpp fuzz_energy_delta_plan.cpp
        ${CMAKE_SOURCE_DIR}/cpp/compile/energy/EnergyDeltaPlan.cpp)
    target_include_directories(energy_sanitizer_smoke PRIVATE ${CMAKE_SOURCE_DIR}/cpp)
    target_compile_options(energy_sanitizer_smoke PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(energy_sanitizer_smoke PRIVATE -fsanitize=address,undefined)
    add_test(NAME energy_sanitizer_smoke COMMAND energy_sanitizer_smoke)
    set_tests_properties(energy_sanitizer_smoke PROPERTIES LABELS "energy-robustness" TIMEOUT 120)
endif()

if(BNG_BUILD_ENERGY_FUZZERS)
    if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        message(FATAL_ERROR "Energy libFuzzer target requires Clang")
    endif()
    add_executable(fuzz_energy_delta_plan fuzz_energy_delta_plan.cpp
        ${CMAKE_SOURCE_DIR}/cpp/compile/energy/EnergyDeltaPlan.cpp)
    target_include_directories(fuzz_energy_delta_plan PRIVATE
        ${CMAKE_SOURCE_DIR}/cpp ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_options(fuzz_energy_delta_plan PRIVATE -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer)
    target_link_options(fuzz_energy_delta_plan PRIVATE -fsanitize=fuzzer,address,undefined)
endif()
