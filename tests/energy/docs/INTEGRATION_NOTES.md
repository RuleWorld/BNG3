# Integration notes

The layout and sequence below describe the original energy-bundle handoff.
For the current branch, use [`docs/CURRENT_PROGRESS.md`](../../../docs/CURRENT_PROGRESS.md)
and the active CMake test registration as the source of truth; final combined-
tree verification for the current batch is recorded in
[`docs/CURRENT_PROGRESS.md`](../../../docs/CURRENT_PROGRESS.md): the final
build and CTest pass completed successfully.

The suite assumes the phase-1 compiler patch (or equivalent interfaces) is present for the non-future C++ tests.
The future contracts are OFF by default and intentionally reference APIs that are not yet guaranteed to exist.

Recommended integration order:

1. Apply the current compiler implementation.
2. Copy this suite into the repository with `install_tests_into_bng3.sh`.
3. Include `cmake/energy_tests.cmake` from `tests/cpp/CMakeLists.txt`.
4. Build/run only label `energy` first.
5. Implement one future subsystem.
6. Move its `future_*.cpp` file(s) from the future target to the required target once green.
7. Keep `BNG_NFSIM_GENERAL_ENERGY` default-off until the stochastic/oracle/performance gates pass.

The suite is deliberately stricter about fallback than optimization. A false-positive fallback costs speed; a false-negative dependency or unsafe lowering changes the stochastic process.
