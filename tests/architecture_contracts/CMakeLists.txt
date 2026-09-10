# Tests for the directly ported NFcore2 and NFnext libraries.
option(BNG_BUILD_ARCHITECTURE_REFERENCE_TESTS "Test isolated handoff prototypes" ON)
if(NOT BNG_BUILD_ARCHITECTURE_REFERENCE_TESTS)
    message(STATUS "BNG3 architecture prototype reference tests disabled")
    return()
endif()
add_executable(bng3_nfcore2_reference_tests
    nfcore2/test_compiled_scheduler.cpp
    nfcore2/test_dependency_exhaustive.cpp
    nfcore2/test_exhaustive_matcher_matrix.cpp
    nfcore2/test_graph_state_machine_extended.cpp
    nfcore2/test_ids_state.cpp
    nfcore2/test_main.cpp
    nfcore2/test_model_image_shadow.cpp
    nfcore2/test_nfsim_adapter_contract.cpp
    nfcore2/test_nfsim_pattern_lowering.cpp
    nfcore2/test_nfsim_system_reader.cpp
    nfcore2/test_nfsim_transform_decoder.cpp
    nfcore2/test_paged_mapping.cpp
    nfcore2/test_randomized_invariants.cpp
    nfcore2/test_rule_family_stress.cpp
    nfcore2/test_rule_legacy.cpp
    nfcore2/test_scaffold_matcher.cpp
    nfcore2/test_scaffold_reference_model.cpp
    nfcore2/test_scheduler_reference_model.cpp
    nfcore2/test_shadow_semantic_matrix.cpp
    nfcore2/test_transform_engine.cpp
    nfcore2/test_validation_dependency.cpp
)
target_link_libraries(bng3_nfcore2_reference_tests PRIVATE bng_nfcore2)
target_include_directories(bng3_nfcore2_reference_tests PRIVATE ${exprtk_SOURCE_DIR})
add_test(NAME architecture_nfcore2_reference COMMAND bng3_nfcore2_reference_tests)
set_tests_properties(architecture_nfcore2_reference PROPERTIES
    LABELS "architecture-reference;nfcore2" TIMEOUT 180)
add_executable(bng3_nfnext_reference_tests nfnext/test_nfnext.cpp)
target_link_libraries(bng3_nfnext_reference_tests PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_reference COMMAND bng3_nfnext_reference_tests)
set_tests_properties(architecture_nfnext_reference PROPERTIES
    LABELS "architecture-reference;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_canonicalization_contract
    nfnext/future_contract/test_nfir_canonicalization_contract.cpp)
target_link_libraries(bng3_nfnext_canonicalization_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_canonicalization
    COMMAND bng3_nfnext_canonicalization_contract)
set_tests_properties(architecture_nfnext_canonicalization PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_dependency_scheduler_contract
    nfnext/future_contract/test_dependency_scheduler_contract.cpp)
target_link_libraries(bng3_nfnext_dependency_scheduler_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_dependency_scheduler
    COMMAND bng3_nfnext_dependency_scheduler_contract)
set_tests_properties(architecture_nfnext_dependency_scheduler PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_generic_matcher_contract
    nfnext/future_contract/test_generic_matcher_contract.cpp)
target_link_libraries(bng3_nfnext_generic_matcher_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_generic_matcher
    COMMAND bng3_nfnext_generic_matcher_contract)
set_tests_properties(architecture_nfnext_generic_matcher PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_transformations_contract
    nfnext/future_contract/test_transformations_contract.cpp)
target_link_libraries(bng3_nfnext_transformations_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_transformations
    COMMAND bng3_nfnext_transformations_contract)
set_tests_properties(architecture_nfnext_transformations PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_memory_arena_contract
    nfnext/future_contract/test_memory_arena_contract.cpp)
target_link_libraries(bng3_nfnext_memory_arena_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_memory_arena
    COMMAND bng3_nfnext_memory_arena_contract)
set_tests_properties(architecture_nfnext_memory_arena PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_cache_contract
    nfnext/future_contract/test_cache_contract.cpp)
target_link_libraries(bng3_nfnext_cache_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_cache
    COMMAND bng3_nfnext_cache_contract)
set_tests_properties(architecture_nfnext_cache PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_observable_function_contract
    nfnext/future_contract/test_observable_function_contract.cpp)
target_link_libraries(bng3_nfnext_observable_function_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_observable_function
    COMMAND bng3_nfnext_observable_function_contract)
set_tests_properties(architecture_nfnext_observable_function PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_lattice_interval_contract
    nfnext/future_contract/test_lattice_interval_contract.cpp)
target_link_libraries(bng3_nfnext_lattice_interval_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_lattice_interval
    COMMAND bng3_nfnext_lattice_interval_contract)
set_tests_properties(architecture_nfnext_lattice_interval PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_compartment_rate_contract
    nfnext/future_contract/test_compartment_rate_contract.cpp)
target_link_libraries(bng3_nfnext_compartment_rate_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_compartment_rate
    COMMAND bng3_nfnext_compartment_rate_contract)
set_tests_properties(architecture_nfnext_compartment_rate PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

add_executable(bng3_nfnext_rng_replay_contract
    nfnext/future_contract/test_rng_replay_concurrency_contract.cpp)
target_link_libraries(bng3_nfnext_rng_replay_contract PRIVATE bng_nfnext)
add_test(NAME architecture_nfnext_rng_replay
    COMMAND bng3_nfnext_rng_replay_contract)
set_tests_properties(architecture_nfnext_rng_replay PROPERTIES
    LABELS "architecture-future;nfnext" TIMEOUT 180)

# Keep the first completed future contract in the normal regression suite. More
# RED contracts can still be selected one at a time while their APIs are ported.
set(BNG_NFNEXT_CONTRACT "test_rule_family_contract" CACHE STRING
    "NFnext contract stem to build (empty disables)")
if(BNG_NFNEXT_CONTRACT)
    file(GLOB candidates RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}/nfnext/future_contract"
        "${CMAKE_CURRENT_SOURCE_DIR}/nfnext/future_contract/test_*_contract.cpp")
    if(NOT "${BNG_NFNEXT_CONTRACT}.cpp" IN_LIST candidates)
        message(FATAL_ERROR "Unknown NFnext contract: ${BNG_NFNEXT_CONTRACT}")
    endif()
    add_executable(bng3_nfnext_future_contract
        "nfnext/future_contract/${BNG_NFNEXT_CONTRACT}.cpp")
    target_link_libraries(bng3_nfnext_future_contract PRIVATE bng_nfnext)
    add_test(NAME architecture_nfnext_future COMMAND bng3_nfnext_future_contract)
    set_tests_properties(architecture_nfnext_future PROPERTIES
        LABELS "architecture-future" TIMEOUT 180)
endif()

add_executable(test_nfcore2_native_reader test_native_reader.cpp)
target_include_directories(test_nfcore2_native_reader PRIVATE ${exprtk_SOURCE_DIR})
target_link_libraries(test_nfcore2_native_reader PRIVATE
    Catch2::Catch2WithMain bng_nfcore2 bng_parser)
include(Catch)
catch_discover_tests(test_nfcore2_native_reader TEST_PREFIX "native-port::")
