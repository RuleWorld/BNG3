# AGENTS.md

Build/test/conventions for agents working on BNG3. Terse on purpose.

## What BNG3 is
Monorepo merging three tools into one in-process platform:
`cpp/` (C++ engine, = bionetgen-master/src + embedded NFsim + pybind11),
`python/bionetgen/` (unified Python API + atomizer; legacy modules being removed),
`legacy/perl/` (BNG2 Perl, kept only as validation oracle).

## Build
```bash
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build                  # produces build/bng_cpp and the _bionetgen_cpp extension
pip install -e .                     # scikit-build-core compiles the extension
cmake -B build -DBUILD_NFSIM_CLI=ON  # also build the native NFsim oracle (for -m nf)
```
Deps fetched via CMake FetchContent (ANTLR4 4.13.1, SUNDIALS 7.6.0, Catch2, pybind11; exprtk until WO-3b). Network required for a clean build.

## Test
```bash
ctest --test-dir build                              # C++ unit tests (Catch2)
pytest tests/validation -m smoke                    # Tier-S parity, every commit
pytest tests/validation -m "parity and not slow"    # full corpus
pytest tests/validation -m nf --bng-cpp build/bng_cpp
python scripts/regen_golden.py --tier p             # rebuild golden oracles (reviewed, committed)
```
Engine discovery for the harness: `--bng-cpp PATH` / `BNG_CPP`; the Python API is `import bionetgen`.

## The rule that matters
No master function lands until its validation gate is green. Gates live in `tests/validation/` and compare against Perl (`.net`, ODE) and native NFsim (network-free). `blbr` and `Motivating_example_cBNGL` are `xfail(strict)` on net parity until WO-1a; do not relax that without fixing the canonicalizer.

## Conventions
- Read the tree, not memory. Grep before asserting state.
- Two-round rule: if a "defect" survives two targeted fixes, question whether it's real (see BNG3_overcount_analysis.md for the cause-1-vs-cause-2 decision before a second attempt). Beware patch-encoding mojibake — verify against the repo tree, never a `.patch` file's text.
- Surgical diffs. One WO = one master function + its deletions + its gate.
- No regression: a change that turns a passing Tier-S model red is not done.
- Don't count lines. Don't write changelogs unless asked.

## Default vs legacy
Default path imports no legacy parse/sim modules. `BIONETGEN_USE_PERL=1` routes through `compat/legacy_runner.py` (subprocess Perl) — the only sanctioned legacy path; it stays.

## Where the merge work is tracked
`BNG3_unification_spec.md` (work-orders WO-0..WO-7), `BNG3_overcount_analysis.md` (WO-1a), `cpp/CMakeLists.unify.snippet.cmake` (WO-1b/3b/4 build edits), `cpp/nfsim/NFinput/NFinput_fromAst.*` (WO-2), `cpp/ast/ExpressionEval.hpp` (WO-3).
