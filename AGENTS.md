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
cmake -B build -DBUILD_NFSIM_CLI=ON  # BNG3 standalone NFsim CLI/smoke executable
```
Dependencies are fetched by CMake FetchContent (ANTLR4 4.13.2, SUNDIALS
7.6.0, Catch2, pybind11, and ExprTk while the expression work order remains
open). A clean build needs network access or a populated dependency cache.

## Test
```bash
ctest --test-dir build --output-on-failure
PYTHONPATH=python:build/cpp python -m pytest -q tests/python
PYTHONPATH=python:build/cpp python -m pytest -q \
  -c tests/validation/pytest.ini tests/validation -m smoke
NFSIM_BIN=/absolute/path/to/pinned/native/NFsim \
  PYTHONPATH=python:build/cpp python -m pytest tests/validation -m nf \
  --bng-cpp build/cpp/bng_cpp
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
- A source-derived fixture for an unsupported capability may land only as an
  explicitly named rejection contract test while its implementation is open;
  a red acceptance test must not remain on a public checkpoint.
- A local green suite, parse inventory, or BNG3-generated output is not
  independent parity evidence. Missing oracles and validators remain visible
  failures/skips with an owner and expiry in the exception ledger.
- `NFSIM_BIN` must name an independently built native NFsim binary from the
  pinned pre-convergence source. The embedded BNG3 `NFsim` target is a smoke
  executable only; the validation harness must not silently substitute it for
  an absent or invalid oracle path.
- Keep the XML NFsim path as a temporary comparator. The default NFsim route
  is the direct AST adapter; XML compatibility requires an explicit
  `BNG_NFSIM_ALLOW_XML_FALLBACK=1`, and `BNG_NFSIM_FORCE_XML=1` selects the
  shadow path. Do not retire XML until the checklist's three-way Tier-NF gate
  passes.
- The direct NFsim API uses the native-compatible endpoint-inclusive
  `stepTo` form only for its final output checkpoint; the ordinary one-argument
  `stepTo` contract remains exclusive for intermediate callers. Keep the
  source-derived fixed-seed `motor`/`tlbr` endpoint test green.
- Species-observable maintenance must use semantic `add`/`subtract` so
  dependent functional propensities refresh; reserve `straightAdd`/
  `straightSubtract` for count-only initialization or rebuild paths. Keep the
  source-derived Issue86 rate-refresh test green.
- NF absolute `t_start` is the simulation clock origin: set it before
  `prepareForSimulation()`, pass `t_end - t_start` to duration-based NFsim
  loops, keep direct-API/action sample times within `[t_start, t_end]`, and
  make `equilibrate(duration)` advance from then restore the absolute clock.
  Keep the source-derived Issue78 direct-API/action and equilibrate tests
  green.
- Energy-function ports must be source-anchored to the accepted
  `akutuva21/nfsim` energy-evaluation cutoff: PR #475, merge
  `6690fda5d9e053df822d0248ebae185f5caca82a`, source commit
  `3b046fc1b9f76719d92be22279b24992cdae7c35`. Audit later fork-head changes
  separately; do not bulk-merge unrelated PRs. Land ports tests-first. The
  compact `EnergyBindingContext`/`EnergyRxnClass` path is only for proven
  factorized contexts; retain materialized expansion as the compatibility
  fallback until broader energy parity, provenance, and direct-NFsim gates
  pass.
- Release builds default `NFSIM_ENABLE_LTO=ON`; CMake must probe IPO support
  before applying it to embedded NFsim and its consumers. Keep the explicit
  ON/OFF contract green, and do not treat LTO build success as benchmark or
  parity evidence.
- Non-main `akutuva21/bionetgen` branches are source inputs, not merge bases:
  inspect exact branch/PR tips and diffs, port relevant behavior with
  source-derived tests first, and classify each source commit as equivalent,
  superseded, non-applicable, pending, or blocked in the convergence
  checklist. Do not bulk-merge generated benchmark/docs/`.jules` artifacts or
  parallel branch stacks without a capability-level decision.
- The convergence session is single-agent: do not delegate implementation or
  validation work. Use the checklist as the authoritative work queue, keep
  every open gap visible, and never claim completion while a mandatory item is
  unchecked or lacks exact evidence.
- Public GitHub state, commits, pushes, and checks are inspected with `gh`
  where supported; record full SHAs and revalidate the exact final SHA after
  every semantic or documentation checkpoint. Preserve unrelated worktree
  edits, especially the small grammar-only change in
  `docs/BNG3_INTEGRATION_PLAN.md`.
- CI pull-request concurrency must key runs by the exact PR head and must not
  cancel an in-flight head when a later checklist/documentation push lands;
  preserve this contract with a local workflow test.
- Before each checkpoint, inspect and preserve unrelated edits, fast-forward
  pull the selected branch when possible, and record the resulting full SHA;
  a documentation-only checkpoint still requires fresh exact-head evidence.
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
