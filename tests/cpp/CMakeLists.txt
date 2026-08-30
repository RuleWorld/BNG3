include(Catch)

# localfunc_test
add_executable(localfunc_test localfunc_test.cpp)
target_include_directories(localfunc_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/mocks
    ${sundials_SOURCE_DIR}/include
    ${sundials_BINARY_DIR}/include
)
target_link_libraries(localfunc_test PRIVATE
    Catch2::Catch2WithMain
    sundials_nvecserial_static
    sundials_cvode_static
)
catch_discover_tests(localfunc_test)

# test_run_network
add_executable(test_run_network test_run_network.cpp)
target_link_libraries(test_run_network PRIVATE Catch2::Catch2WithMain Catch2::Catch2)
catch_discover_tests(test_run_network)

# test_pla_simulator
add_executable(test_pla_simulator test_pla_simulator.cpp)
target_include_directories(test_pla_simulator PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
    ${sundials_SOURCE_DIR}/include
    ${sundials_BINARY_DIR}/include
)
target_link_libraries(test_pla_simulator PRIVATE
    Catch2::Catch2WithMain
    Catch2::Catch2
    bng_engine
    bng_ast
    bng_core
    antlr4_static
)
catch_discover_tests(test_pla_simulator)

# test_ode_options
add_executable(test_ode_options test_ode_options.cpp)
target_include_directories(test_ode_options PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
    ${sundials_SOURCE_DIR}/include
    ${sundials_BINARY_DIR}/include
)
target_link_libraries(test_ode_options PRIVATE
    Catch2::Catch2WithMain
    Catch2::Catch2
    bng_engine
    bng_ast
    antlr4_static
)
catch_discover_tests(test_ode_options)

# test_hybrid_model_generator
add_executable(test_hybrid_model_generator test_hybrid_model_generator.cpp)
target_link_libraries(test_hybrid_model_generator PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_engine bng_ast)
catch_discover_tests(test_hybrid_model_generator)

# test_network_generator
add_executable(test_network_generator test_network_generator.cpp)
target_include_directories(test_network_generator PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
)
target_link_libraries(test_network_generator PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_engine bng_ast)
catch_discover_tests(test_network_generator)

# test_node_operator
add_executable(test_node_operator test_node_operator.cpp)
target_include_directories(test_node_operator PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/core
)
target_link_libraries(test_node_operator PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_core)
catch_discover_tests(test_node_operator)

# test_expression_evaluator
add_executable(test_expression_evaluator test_expression_evaluator.cpp)
target_include_directories(test_expression_evaluator PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
)
target_link_libraries(test_expression_evaluator PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_ast)
catch_discover_tests(test_expression_evaluator)

# test_reaction_rule_expansion
add_executable(test_reaction_rule_expansion test_reaction_rule_expansion.cpp)
target_include_directories(test_reaction_rule_expansion PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
)
target_link_libraries(test_reaction_rule_expansion PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_engine bng_ast)
catch_discover_tests(test_reaction_rule_expansion)

# test_hnauty
add_executable(test_hnauty test_hnauty.cpp)
target_include_directories(test_hnauty PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
)
target_link_libraries(test_hnauty PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_engine bng_ast)
catch_discover_tests(test_hnauty)

# test_ullmann
add_executable(test_ullmann test_ullmann.cpp)
target_include_directories(test_ullmann PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
)
target_link_libraries(test_ullmann PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_engine bng_ast)
catch_discover_tests(test_ullmann)

# test_compartment_transport
add_executable(test_compartment_transport test_compartment_transport.cpp)
target_include_directories(test_compartment_transport PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/parser
    ${CMAKE_SOURCE_DIR}/cpp/parser/generated
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
)
target_link_libraries(test_compartment_transport PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bng_engine bng_ast)
catch_discover_tests(test_compartment_transport)

# test_nfsim_ast_adapter
add_executable(test_nfsim_ast_adapter test_nfsim_ast_adapter.cpp)
target_include_directories(test_nfsim_ast_adapter PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/nfsim
    ${CMAKE_SOURCE_DIR}/cpp/nfsim/NFcore
    ${CMAKE_SOURCE_DIR}/cpp/nfsim/NFinput
    ${exprtk_SOURCE_DIR}
)
target_link_libraries(test_nfsim_ast_adapter PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2
    bionetgen_core
    # ReactionRule's local-observable fingerprinting reaches parser symbols
    # through bng_ast. Repeat the parser archive after the aggregate target so
    # GNU ld resolves the static-archive cycle on this test target.
    bng_parser)
catch_discover_tests(test_nfsim_ast_adapter)

# test_sbml_reader
add_executable(test_sbml_reader test_sbml_reader.cpp)
target_include_directories(test_sbml_reader PRIVATE
    ${CMAKE_SOURCE_DIR}/cpp
    ${CMAKE_SOURCE_DIR}/cpp/nfsim
    ${CMAKE_SOURCE_DIR}/cpp/nfsim/NFinput
    ${CMAKE_SOURCE_DIR}/cpp/nfsim/NFinput/TinyXML
)
target_link_libraries(test_sbml_reader PRIVATE
    Catch2::Catch2WithMain Catch2::Catch2 bionetgen_core)
catch_discover_tests(test_sbml_reader)
