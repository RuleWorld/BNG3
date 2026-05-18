# cpp/CMakeLists.txt — Unified C++ build for BioNetGen core + NFSim

# =============================================================================
# nauty (graph isomorphism)
# =============================================================================
file(GLOB NAUTY_SOURCES "nauty/*.c")
add_library(nauty STATIC ${NAUTY_SOURCES})
target_include_directories(nauty PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/nauty)

# =============================================================================
# bng_core (pattern graph, node, state, transformations)
# =============================================================================
file(GLOB BNG_CORE_SOURCES "core/*.cpp")
list(FILTER BNG_CORE_SOURCES EXCLUDE REGEX ".*_wrap\\.cxx")
add_library(bng_core STATIC ${BNG_CORE_SOURCES})
target_include_directories(bng_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/core)
target_link_libraries(bng_core PUBLIC nauty)

# =============================================================================
# bng_ast (model AST nodes)
# =============================================================================
file(GLOB BNG_AST_SOURCES "ast/*.cpp")
add_library(bng_ast STATIC ${BNG_AST_SOURCES})
target_include_directories(bng_ast PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/ast
    ${CMAKE_CURRENT_SOURCE_DIR}/parser/generated
    ${CMAKE_CURRENT_SOURCE_DIR}/parser
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
)
target_link_libraries(bng_ast PUBLIC bng_core antlr4_static)
if(MSVC)
    target_compile_definitions(bng_ast PRIVATE _USE_MATH_DEFINES)
endif()

# =============================================================================
# bng_parser (ANTLR4 BNGL parser)
# =============================================================================
set(ANTLR_GEN_DIR ${CMAKE_CURRENT_SOURCE_DIR}/parser/generated)
add_library(bng_parser STATIC
    ${ANTLR_GEN_DIR}/BNGLexer.cpp
    ${ANTLR_GEN_DIR}/BNGParser.cpp
    ${ANTLR_GEN_DIR}/BNGParserBaseVisitor.cpp
    ${ANTLR_GEN_DIR}/BNGParserVisitor.cpp
    parser/BNGAstVisitor.cpp
    parser/PatternGraphBuilder.cpp
)
target_include_directories(bng_parser PUBLIC
    ${ANTLR_GEN_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/parser
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
)
target_link_libraries(bng_parser PUBLIC antlr4_static bng_ast)

# =============================================================================
# bng_engine (simulators, I/O writers, actions, console)
# =============================================================================
add_library(bng_engine STATIC
    engine/NetworkGenerator.cpp
    engine/OdeIntegrator.cpp
    engine/PlaSimulator.cpp
    engine/PsaSimulator.cpp
    engine/HybridModelGenerator.cpp
    io/NetWriter.cpp
    io/NetReader.cpp
    io/XmlWriter.cpp
    io/BnglWriter.cpp
    io/SbmlWriter.cpp
    io/SbmlMultiWriter.cpp
    io/MatlabWriter.cpp
    io/CppExportWriter.cpp
    io/PythonExportWriter.cpp
    io/ContactMapWriter.cpp
    io/MexWriter.cpp
    io/RegulatoryGraphWriter.cpp
    io/ReactionNetworkGraphWriter.cpp
    io/RulevizPatternWriter.cpp
    io/RulevizOperationWriter.cpp
    io/ProcessGraphWriter.cpp
    io/RuleInfluenceGraphWriter.cpp
    io/LatexWriter.cpp
    io/MdlWriter.cpp
    io/SscWriter.cpp
    actions/ActionDispatch.cpp
    console/Console.cpp
)
target_include_directories(bng_engine PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${ANTLR_GEN_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/parser
    ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
    ${sundials_SOURCE_DIR}/include
    ${sundials_BINARY_DIR}/include
)
target_link_libraries(bng_engine PUBLIC
    bng_parser
    bng_ast
    bng_core
    antlr4_static
    sundials_cvode_static
    sundials_nvecserial_static
    sundials_sunlinsoldense_static
    sundials_sunlinsolspgmr_static
    sundials_sunmatrixdense_static
)
target_compile_definitions(bng_engine PUBLIC BNG_CPP_SOURCE_DIR="${CMAKE_SOURCE_DIR}")

# =============================================================================
# nfsim_core (Network-free stochastic simulator)
# =============================================================================
set(NFSIM_DIR ${CMAKE_CURRENT_SOURCE_DIR}/nfsim)

file(GLOB NFSIM_CORE_SRC "${NFSIM_DIR}/NFcore/*.cpp")
file(GLOB NFSIM_CORE_MOLLISTS "${NFSIM_DIR}/NFcore/moleculeLists/*.cpp")
file(GLOB NFSIM_CORE_RXNSEL "${NFSIM_DIR}/NFcore/reactionSelector/*.cpp")
file(GLOB NFSIM_INPUT_SRC "${NFSIM_DIR}/NFinput/*.cpp")
file(GLOB NFSIM_INPUT_XML "${NFSIM_DIR}/NFinput/TinyXML/*.cpp")
file(GLOB NFSIM_RXN_SRC "${NFSIM_DIR}/NFreactions/*.cpp")
file(GLOB NFSIM_RXN_TRANS "${NFSIM_DIR}/NFreactions/transformations/*.cpp")
file(GLOB NFSIM_RXN_RXN "${NFSIM_DIR}/NFreactions/reactions/*.cpp")
file(GLOB NFSIM_RXN_RLISTS "${NFSIM_DIR}/NFreactions/reactantLists/*.cpp")
file(GLOB NFSIM_RXN_MAPS "${NFSIM_DIR}/NFreactions/mappings/*.cpp")
file(GLOB NFSIM_FUNC_SRC "${NFSIM_DIR}/NFfunction/*.cpp")
file(GLOB NFSIM_FUNC_MUPARSER "${NFSIM_DIR}/NFfunction/muParser/*.cpp")
file(GLOB NFSIM_OUTPUT_SRC "${NFSIM_DIR}/NFoutput/*.cpp")
file(GLOB NFSIM_SCHED_SRC "${NFSIM_DIR}/NFscheduler/*.cpp")
file(GLOB NFSIM_UTIL_SRC "${NFSIM_DIR}/NFutil/*.cpp")
file(GLOB NFSIM_UTIL_MTRAND "${NFSIM_DIR}/NFutil/MTrand/*.cpp")
file(GLOB NFSIM_NAUTY_C "${NFSIM_DIR}/nauty24/*.c")

# Exclude NFsim.cpp (main) and NFtest sources from the library
set(NFSIM_LIB_SOURCES
    ${NFSIM_CORE_SRC}
    ${NFSIM_CORE_MOLLISTS}
    ${NFSIM_CORE_RXNSEL}
    ${NFSIM_INPUT_SRC}
    ${NFSIM_INPUT_XML}
    ${NFSIM_RXN_SRC}
    ${NFSIM_RXN_TRANS}
    ${NFSIM_RXN_RXN}
    ${NFSIM_RXN_RLISTS}
    ${NFSIM_RXN_MAPS}
    ${NFSIM_FUNC_SRC}
    ${NFSIM_FUNC_MUPARSER}
    ${NFSIM_OUTPUT_SRC}
    ${NFSIM_SCHED_SRC}
    ${NFSIM_UTIL_SRC}
    ${NFSIM_UTIL_MTRAND}
    ${NFSIM_NAUTY_C}
)

# Remove NFsim.cpp (contains main())
list(FILTER NFSIM_LIB_SOURCES EXCLUDE REGEX ".*/NFsim\\.cpp$")

add_library(nfsim_core STATIC ${NFSIM_LIB_SOURCES})
target_include_directories(nfsim_core PUBLIC
    ${NFSIM_DIR}
    ${NFSIM_DIR}/NFcore
    ${NFSIM_DIR}/NFcore/moleculeLists
    ${NFSIM_DIR}/NFcore/reactionSelector
    ${NFSIM_DIR}/NFinput
    ${NFSIM_DIR}/NFinput/TinyXML
    ${NFSIM_DIR}/NFreactions
    ${NFSIM_DIR}/NFreactions/transformations
    ${NFSIM_DIR}/NFreactions/reactions
    ${NFSIM_DIR}/NFreactions/reactantLists
    ${NFSIM_DIR}/NFreactions/mappings
    ${NFSIM_DIR}/NFfunction
    ${NFSIM_DIR}/NFfunction/muParser
    ${NFSIM_DIR}/NFoutput
    ${NFSIM_DIR}/NFscheduler
    ${NFSIM_DIR}/NFutil
    ${NFSIM_DIR}/NFutil/MTrand
    ${NFSIM_DIR}/nauty24
)
target_compile_definitions(nfsim_core PRIVATE TIXML_USE_STL)
if(NOT MSVC)
    target_compile_options(nfsim_core PRIVATE -Wno-deprecated-declarations)
endif()

# =============================================================================
# bionetgen_core — combined static library for all C++ components
# =============================================================================
add_library(bionetgen_core INTERFACE)
target_link_libraries(bionetgen_core INTERFACE
    bng_engine
    bng_parser
    bng_ast
    bng_core
    nauty
    nfsim_core
)

# =============================================================================
# bng_cpp executable (CLI)
# =============================================================================
if(BUILD_CLI)
    add_executable(bng_cpp main.cpp)
    target_link_libraries(bng_cpp PRIVATE bionetgen_core)
    target_compile_definitions(bng_cpp PRIVATE BNG_CPP_SOURCE_DIR="${CMAKE_SOURCE_DIR}")
endif()

# =============================================================================
# NFsim executable (optional, for backward compatibility)
# =============================================================================
if(BUILD_NFSIM_CLI)
    file(GLOB NFSIM_TEST_SRC
        "${NFSIM_DIR}/NFtest/*.cpp"
        "${NFSIM_DIR}/NFtest/simple_system/*.cpp"
        "${NFSIM_DIR}/NFtest/transcription/*.cpp"
        "${NFSIM_DIR}/NFtest/tlbr/*.cpp"
        "${NFSIM_DIR}/NFtest/agentcell/*.cpp"
        "${NFSIM_DIR}/NFtest/agentcell/cell/*.cpp"
    )
    add_executable(NFsim ${NFSIM_DIR}/NFsim.cpp ${NFSIM_TEST_SRC})
    target_link_libraries(NFsim PRIVATE nfsim_core)
    target_include_directories(NFsim PRIVATE
        ${NFSIM_DIR}/NFtest
        ${NFSIM_DIR}/NFtest/simple_system
        ${NFSIM_DIR}/NFtest/transcription
        ${NFSIM_DIR}/NFtest/tlbr
        ${NFSIM_DIR}/NFtest/agentcell
        ${NFSIM_DIR}/NFtest/agentcell/cell
    )
    target_compile_definitions(NFsim PRIVATE TIXML_USE_STL)
endif()

# =============================================================================
# Python bindings (pybind11)
# =============================================================================
if(BUILD_PYTHON_BINDINGS)
    pybind11_add_module(_bionetgen_cpp
        bindings/module.cpp
        bindings/bind_model.cpp
        bindings/bind_parser.cpp
        bindings/bind_engine.cpp
        bindings/bind_nfsim.cpp
        bindings/bind_io.cpp
        bindings/bind_viz.cpp
    )
    target_link_libraries(_bionetgen_cpp PRIVATE bionetgen_core)
    target_include_directories(_bionetgen_cpp PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/ast
        ${CMAKE_CURRENT_SOURCE_DIR}/core
        ${CMAKE_CURRENT_SOURCE_DIR}/engine
        ${CMAKE_CURRENT_SOURCE_DIR}/io
        ${CMAKE_CURRENT_SOURCE_DIR}/actions
        ${CMAKE_CURRENT_SOURCE_DIR}/parser
        ${CMAKE_CURRENT_SOURCE_DIR}/parser/generated
        ${NFSIM_DIR}
        ${NFSIM_DIR}/NFcore
        ${NFSIM_DIR}/NFinput
        ${antlr4_runtime_SOURCE_DIR}/runtime/Cpp/runtime/src
        ${sundials_SOURCE_DIR}/include
        ${sundials_BINARY_DIR}/include
    )
    target_compile_definitions(_bionetgen_cpp PRIVATE TIXML_USE_STL)

    install(TARGETS _bionetgen_cpp DESTINATION bionetgen COMPONENT python)
endif()
