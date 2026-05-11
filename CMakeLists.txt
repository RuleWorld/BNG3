cmake_minimum_required(VERSION 3.14)
project(BioNetGen LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(FETCHCONTENT_UPDATES_DISCONNECTED ON)

option(BUILD_PYTHON_BINDINGS "Build pybind11 Python module" ON)
option(BUILD_CLI "Build bng_cpp command-line executable" ON)
option(BUILD_NFSIM_CLI "Build NFsim command-line executable" OFF)
option(BUILD_TESTS "Build C++ tests" ON)

include(FetchContent)

# --- Catch2 (Tests) ---
if(BUILD_TESTS)
    if(EXISTS "${CMAKE_SOURCE_DIR}/build/_deps/catch2-src/CMakeLists.txt")
        set(FETCHCONTENT_SOURCE_DIR_CATCH2 "${CMAKE_SOURCE_DIR}/build/_deps/catch2-src")
    endif()
    FetchContent_Declare(
        Catch2
        GIT_REPOSITORY https://github.com/catchorg/Catch2.git
        GIT_TAG        v3.4.0
    )
    FetchContent_MakeAvailable(Catch2)
endif()

# --- ANTLR4 C++ Runtime ---
if(EXISTS "${CMAKE_SOURCE_DIR}/build/_deps/antlr4_runtime-src/runtime/Cpp/CMakeLists.txt")
    set(FETCHCONTENT_SOURCE_DIR_ANTLR4_RUNTIME "${CMAKE_SOURCE_DIR}/build/_deps/antlr4_runtime-src")
endif()

FetchContent_Declare(
    antlr4_runtime
    GIT_REPOSITORY https://github.com/antlr/antlr4.git
    GIT_TAG        4.13.2
    SOURCE_SUBDIR  runtime/Cpp
)

set(ANTLR4_INSTALL ON CACHE INTERNAL "")
set(ANTLR4_WITH_LIBCXX OFF CACHE INTERNAL "")
set(ANTLR_BUILD_CPP_TESTS OFF CACHE INTERNAL "")
set(ANTLR4_STATIC ON CACHE INTERNAL "")
set(ANTLR4_SHARED OFF CACHE INTERNAL "")

FetchContent_MakeAvailable(antlr4_runtime)

if(MSVC AND TARGET antlr4_static)
    target_compile_options(antlr4_static PRIVATE /FI"chrono")
endif()

# --- SUNDIALS (CVODE solver) ---
if(EXISTS "${CMAKE_SOURCE_DIR}/build/_deps/sundials-src/CMakeLists.txt")
    set(FETCHCONTENT_SOURCE_DIR_SUNDIALS "${CMAKE_SOURCE_DIR}/build/_deps/sundials-src")
endif()

FetchContent_Declare(
    sundials
    GIT_REPOSITORY https://github.com/LLNL/sundials.git
    GIT_TAG        v7.6.0
    GIT_SUBMODULES ""
)

set(BUILD_CVODE ON CACHE INTERNAL "")
set(BUILD_CVODES OFF CACHE INTERNAL "")
set(BUILD_IDA OFF CACHE INTERNAL "")
set(BUILD_IDAS OFF CACHE INTERNAL "")
set(BUILD_KINSOL OFF CACHE INTERNAL "")
set(BUILD_ARKODE OFF CACHE INTERNAL "")
set(BUILD_SHARED_LIBS OFF CACHE INTERNAL "")
set(BUILD_STATIC_LIBS ON CACHE INTERNAL "")
set(BUILD_TESTING OFF CACHE INTERNAL "")
set(EXAMPLES_ENABLE OFF CACHE INTERNAL "")
set(EXAMPLES_ENABLE_C OFF CACHE INTERNAL "")
set(EXAMPLES_INSTALL OFF CACHE INTERNAL "")
set(SUNDIALS_INDEX_SIZE 64 CACHE INTERNAL "")

FetchContent_MakeAvailable(sundials)

# --- pybind11 ---
if(BUILD_PYTHON_BINDINGS)
    if(EXISTS "${CMAKE_SOURCE_DIR}/build/_deps/pybind11-src/CMakeLists.txt")
        set(FETCHCONTENT_SOURCE_DIR_PYBIND11 "${CMAKE_SOURCE_DIR}/build/_deps/pybind11-src")
    endif()
    FetchContent_Declare(
        pybind11
        GIT_REPOSITORY https://github.com/pybind/pybind11.git
        GIT_TAG        v2.13.6
    )
    FetchContent_MakeAvailable(pybind11)
endif()

# Enable testing after FetchContent
if(BUILD_TESTS)
    enable_testing()
    include(CTest)
endif()

# C++ source
add_subdirectory(cpp)

# Tests
if(BUILD_TESTS AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/tests/cpp/CMakeLists.txt)
    add_subdirectory(tests/cpp)
endif()
