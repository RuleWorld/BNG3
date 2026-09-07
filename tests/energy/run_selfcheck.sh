#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
cd "$root"
python -m compileall -q scripts tests/python
python -m pytest -q tests/python
python scripts/generate_boolean_context_fixture.py 8 /tmp/bng3_energy_context8.bngl
test "$(grep -c '^  A(x!1' /tmp/bng3_energy_context8.bngl)" -eq 8
if [[ $# -ge 1 ]]; then
  repo=$(cd "$1" && pwd)
  cxx=${CXX:-c++}
  "$cxx" -std=c++17 -Wall -Wextra -Werror -pedantic \
    -I"$repo/cpp" \
    tests/cpp/standalone_energy_delta_plan_smoke.cpp \
    "$repo/cpp/compile/energy/EnergyDeltaPlan.cpp" \
    -o /tmp/bng3_energy_delta_smoke
  /tmp/bng3_energy_delta_smoke
fi
echo "energy validation suite self-check passed"
