# AGENTS.md

Build/test/conventions for agents working on BNG3. Terse on purpose. The
authoritative convergence exit gate is
[`docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md`](docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md);
this file gives working rules, not a completion claim.

## What BNG3 is
Monorepo merging three tools into one in-process platform:
`cpp/` (C++ engine, = bionetgen-master/src + embedded NFsim + pybind11),
`python/bionetgen/` (unified Python API + modern atomizer; legacy modules remain
until their deletion gate passes),
`legacy/perl/` (BNG2 Perl, kept only as validation oracle).

## Build
```bash
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build                  # bng_cpp and, when enabled, bindings
pip install -e .                     # scikit-build-core package build
cmake -B build -DBUILD_NFSIM_CLI=ON  # native NFsim oracle executable
```
Dependencies are fetched by CMake FetchContent (ANTLR4 4.13.1, SUNDIALS
7.6.0, Catch2, pybind11, and ExprTk while the expression work order remains
open). A clean build needs network access or a populated dependency cache.

## Test
```bash
ctest --test-dir build --output-on-failure
PYTHONPATH=python:build/cpp python -m pytest -q tests/python
PYTHONPATH=python:build/cpp python -m pytest -q \
  -c tests/validation/pytest.ini tests/validation -m smoke
NFSIM_BIN=build/cpp/NFsim PYTHONPATH=python:build/cpp \
  python -m pytest tests/validation -m nf --bng-cpp build/cpp/bng_cpp
```
Engine discovery for the validation harness is `--bng-cpp PATH` or `BNG_CPP`.
The local development build places executables and the extension under
`build/cpp/`. Run the full validation and golden-generation workflows only
with the pinned oracles and provenance required by the checklist; never make
them pass by widening tolerances or hiding skips. The Python API is
`import bionetgen`.

## The rules that matter

- No semantic master function lands until its source-derived tests and the
  dependent validation gate are green. Gates live in `tests/validation/` and
  must compare against independent BNG2 Perl and native NFsim artifacts when
  they claim parity.
- A local green suite, parse inventory, or BNG3-generated output is not
  independent parity evidence. Missing oracles and validators remain visible
  failures/skips with an owner and expiry in the exception ledger.
- Keep the XML NFsim path as a temporary comparator. The default NFsim route
  is the direct AST adapter; XML compatibility requires an explicit
  `BNG_NFSIM_ALLOW_XML_FALLBACK=1`, and `BNG_NFSIM_FORCE_XML=1` selects the
  shadow path. Do not retire XML until the checklist's three-way Tier-NF gate
  passes.
- Do not broaden the exception ledger to hide a new mismatch. The current
  checklist, not a historical model-specific exception, defines completion.

## Conventions
- Read the tree, not memory. Grep before asserting state.
- Two-round rule: if a "defect" survives two targeted fixes, question whether it's real (see BNG3_overcount_analysis.md for the cause-1-vs-cause-2 decision before a second attempt). Beware patch-encoding mojibake — verify against the repo tree, never a `.patch` file's text.
- Surgical diffs. One WO = one master function + its deletions + its gate.
- No regression: a change that turns a passing Tier-S model red is not done.
- Don't count lines. Don't write changelogs unless asked.

## Default vs legacy
The default path must not import legacy parse/sim modules. `BIONETGEN_USE_PERL=1`
routes through `compat/legacy_runner.py` (subprocess Perl), but its release
status and the deletion of the remaining legacy trees are still checklist
decisions, not completed work.

## Where the merge work is tracked
`docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md` (exit criteria),
`docs/BNG3_INTEGRATION_PLAN.md` (completion charter),
`BNG3_unification_spec.md` (work orders WO-0..WO-7),
`BNG3_overcount_analysis.md` (WO-1a),
`cpp/CMakeLists.unify.snippet.cmake` (WO-1b/3b/4 build edits),
`cpp/nfsim/NFinput/NFinput_fromAst.*` (WO-2), and
`cpp/ast/ExpressionEval.hpp` (WO-3).
