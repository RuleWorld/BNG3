# Handoff contracts are promoted individually against the real BNG3 AST.
include(Catch)
add_subdirectory(tests/cpp)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_test(NAME energy_validation_harness
    COMMAND ${CMAKE_COMMAND} -E env
        "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}"
        "PYTHONDONTWRITEBYTECODE=1"
        ${Python3_EXECUTABLE} -m pytest -q -p no:cacheprovider tests/python)
set_tests_properties(energy_validation_harness PROPERTIES
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    LABELS "energy;harness" TIMEOUT 120)
