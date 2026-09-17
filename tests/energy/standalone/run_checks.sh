#!/usr/bin/env bash
#
# Network-free verification of the independent thermodynamic layer.
#
# The normal build pulls Catch2, the ANTLR4 runtime, SUNDIALS, pybind11 and
# ExprTk through FetchContent. That is the right way to run the full suite, but
# it needs network access. These checks cover the parts of the barrier/driven
# energy work that have no ANTLR, Catch2 or NFsim dependency, so they can be
# compiled and run with nothing but a C++17 compiler.
#
# This is a convenience harness, not a replacement for ctest. The Catch2
# equivalents live in tests/energy/tests/cpp/ and are what CI runs:
#   future_thermodynamic_constraints.cpp
#   future_barrier_driving_syntax.cpp
#   test_thermo_source_normalization.cpp
#   test_barrier_and_driven_energy.cpp
#
# Usage: tests/energy/standalone/run_checks.sh [CXX]

set -uo pipefail

CXX="${1:-${CXX:-g++}}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../../.." && pwd)"
SRC="${ROOT}/cpp"
OUT="$(mktemp -d)"
trap 'rm -rf "${OUT}"' EXIT

THERMO="${SRC}/compile/energy/ThermodynamicConstraints.cpp"
BARRIER="${SRC}/compile/energy/BarrierTable.cpp"
DRIVEN="${SRC}/compile/energy/DrivenEnergy.cpp"
NORMALIZE="${SRC}/parser/ThermoSourceNormalization.cpp"
FINALIZE="${SRC}/parser/ThermoModelFinalize.cpp"
GUARD="${SRC}/io/EnergyExportGuard.cpp"

# check_model_finalize links the real AST. PopulationMappingRule.cpp needs the
# generated parser headers, and core/PatternGraph.cpp needs nauty's sparse
# header, so the include path covers nauty and that one AST unit is excluded.
AST_SOURCES=()
while IFS= read -r unit; do AST_SOURCES+=("${unit}"); done < <(
    find "${SRC}/ast" -maxdepth 1 -name '*.cpp' ! -name 'PopulationMappingRule.cpp' | sort)
while IFS= read -r unit; do AST_SOURCES+=("${unit}"); done < <(
    find "${SRC}/core" -maxdepth 1 -name '*.cpp' | sort)
while IFS= read -r unit; do AST_SOURCES+=("${unit}"); done < <(
    find "${SRC}/nauty" -maxdepth 1 -name '*.c' | sort)
AST_SOURCES+=("${SRC}/units/Unit.cpp")

# check name -> extra translation units it needs
run_check() {
    local name="$1"; shift
    local binary="${OUT}/${name}"
    if ! "${CXX}" -std=c++17 -O1 -I"${SRC}" -I"${SRC}/parser" -I"${SRC}/nauty" \
            -I"${SRC}/io" "${HERE}/${name}.cpp" "$@" -o "${binary}" 2>"${OUT}/${name}.log"; then
        echo "=== ${name}: COMPILE FAILED"
        cat "${OUT}/${name}.log"
        return 1
    fi
    if ! "${binary}"; then
        echo "=== ${name}: CHECKS FAILED"
        return 1
    fi
    return 0
}

failures=0
run_check check_thermodynamics       "${THERMO}"                        || failures=$((failures + 1))
run_check check_determinism          "${THERMO}"                        || failures=$((failures + 1))
run_check check_barrier_table        "${BARRIER}"                       || failures=$((failures + 1))
run_check check_key_roundtrip        "${BARRIER}"                       || failures=$((failures + 1))
run_check check_driven_rates         "${DRIVEN}" "${THERMO}"            || failures=$((failures + 1))
run_check check_source_normalization "${NORMALIZE}"                     || failures=$((failures + 1))
run_check check_convention_parity    "${DRIVEN}"                        || failures=$((failures + 1))
run_check check_model_finalize       "${FINALIZE}" "${AST_SOURCES[@]}"  || failures=$((failures + 1))
run_check check_export_guard         "${GUARD}" "${AST_SOURCES[@]}"     || failures=$((failures + 1))

echo
if [ "${failures}" -ne 0 ]; then
    echo "standalone energy checks: ${failures} check group(s) failed"
    exit 1
fi
echo "standalone energy checks: all check groups passed"
