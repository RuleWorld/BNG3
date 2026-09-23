# BNG3 current progress

**Audited:** 2026-09-23 (scoped source-reconciliation update; full convergence checklist not re-audited)
**Repository:** `RuleWorld/BNG3`
**Branch:** `main`
**Status:** merged convergence, nonequilibrium energy, and SBML material-gap work; release validation remains incomplete

This is the live status page for the combined BNG3 migration tree. The older
IR migration reports and formalization reports retained in the repository are
historical inputs and provenance records; their embedded prose is not a new
execution instruction.

## Upstream source reconciliation — 2026-09-23

The observed RuleWorld heads for BioNetGen, NFsim, and PyBioNetGen have been
refreshed in [`../provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml)
and all 35 commits since the prior recorded source revisions have a
per-commit disposition in
[`UPSTREAM_RECONCILIATION_2026-09-23.md`](UPSTREAM_RECONCILIATION_2026-09-23.md)
and [`../provenance/reconciliation/`](../provenance/reconciliation/). Applicable
legacy behavior and the PyBioNetGen runtime dependency are ported; newer
native engine behavior already present in BNG3 is recorded as equivalent.
Source-site tutorials, generated source references, and repository-specific
automation are documented as not transplanted.

This was a scoped source and documentation pass, not a full convergence audit.
No test suites were run for this pass. The source-lock baseline is still
`pending-maintainer-approval`; the observed source heads do not by themselves
close any release or independent-oracle gate.

## Merged convergence + nonequilibrium energy — 2026-09-17 (locally build-verified)

This branch merges the two source zips on top of `91fe936`:

- `BNG3-convergence-2026-09-17.zip` — offline convergence pass (WO-1b single-nauty, WO-3/3b shared evaluator, `rint`/`sign`/`log`/`avg`, case-sensitive gate, `ModelOptions` validation, observable counting modes, per-stage NFsim fallback reasons)
- `BNG3-nonequilibrium-energy.zip` — experimental `begin barrier patterns` / `driven_by(W)` layer gated by `BNG_NFSIM_GENERAL_ENERGY`

Both trees were applied on `feat/merge-nonequilibrium-convergence` (`6fe02c5` on top of `ba35fba`). Build verification was performed in this environment:

- `cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build` — succeeds after three merge fixes (`BNGAstVisitor.cpp:1852` qualified free function, `NetWriter.cpp:24` missing `BarrierCompiler`/`DrivenEnergy` includes, `BNGAstVisitor.cpp:1520` `stripQuotes` vs `getText()`)
- `ctest --test-dir build --output-on-failure` — **408/408 passed** (was 404/408 before fixes: 4 observable-counting cases failed on dangling `BNGcoreLoweringContext` + double-quoted `setOption` values)
- `PYTHONPATH=build/cpp:python python -m pytest tests/python -q` — **411 passed, 28 skipped** (3 `test_bngir.py` schema failures are expected: experimental `barrier_patterns`/`driving_work` not in published schema)
- `tests/energy/standalone/run_checks.sh` — all check groups passed
- `tools/check_architecture_dependencies.py` and `provenance/architecture-contracts.json` — updated and passing; `tests/energy/tests/cpp/test_barrier_*` etc. now listed as `required` with `test_energy_compiler_contracts`

Remaining gaps per `AGENTS.md` §Validation: hosted CI (MSVC matrix, full corpus `71/71` strict, wheel matrix), independent BNG2/NFsim oracle parity for the new counting modes and for barrier/driven semantics (no oracle for the latter by design), and formal Lean checks.

## Offline convergence pass — 2026-09-17

A restricted-container static audit and low-risk fix pass. No build, no
network, and no Git checkout were available at authoring time, so the original pass was **not build-verified**. Full detail, including the gap table, changed-files table,
and deferred validation commands, is in
[`OFFLINE_CONVERGENCE_PASS_2026-09-17.md`](OFFLINE_CONVERGENCE_PASS_2026-09-17.md).

Previously `Implemented, awaiting build validation`; now **locally build-verified** on the merged branch (see above):

- **One nauty build (WO-1b).** `cpp/nfsim/nauty24/` is deleted; `nfsim_core`
  links the shared `nauty` target. The trees were identical modulo the
  documented `set`->`nset` rename, and unifying on the NFsim variant also
  fixed a missing MSVC `HAVE_SYSTYPES_H` guard. Locked by
  `tests/python/test_single_nauty_contract.py` (10/10 locally).
- **`rint` corrected in both expression engines.** BNG2 defines it as
  `floor(x + 0.5)`; the shared evaluator used `std::rint` (half-to-even) and
  NFsim used `std::round` (half-away-from-zero), so the two disagreed with
  each other and each disagreed with the oracle. Oracle values were produced
  by executing `legacy/perl/Perl2/Expression.pm:74` directly.
- **One builtin table** (`cpp/ast/ExpressionBuiltins.hpp`) consumed by both
  the shared evaluator and the direct-NFsim gate. Closed the `sign`/`log`
  asymmetry, admitted `avg` (removing a false XML fallback), and made the gate
  case-sensitive to match the ExprTk shim.
- **`setOption` validation** (`cpp/ast/ModelOptions.hpp`) at the single
  `Model::setOption` seam. `SpeciesLabel=Quasi` and invalid option values now
  fail closed instead of being stored and ignored; corpus-present options
  still load.
- **Observable counting modes implemented** (`engine/ObservableProjection.cpp`).
  `MoleculesObservables`/`SpeciesObservables` did not exist in BNG3 at all, so
  a model requesting `CountUnique` silently received `CountAll` values. The two
  keys are not the same operation: Molecules `CountUnique` divides each match
  count by the pattern's automorphism number, while Species `CountUnique`
  short-circuits the term loop so a species counts once. BNG2 has the symmetry
  correction commented out on the Species branch. The Molecules division is
  asserted exact rather than truncated.
- **Per-stage direct-NFsim fallback reasons**, surfaced at both call sites and
  as `Result.direct_unavailable_reason`.

All six above are now linked in `bng_parser`/`nfsim_core`/`bng_engine` and exercised locally: `test_single_nauty_contract` (10/10), `test_expression_evaluator` (incl. `rint`/`sign`/`log`/engine-agreement, 4 new cases), `test_model_options` (4 cases), `test_observable_counting` (5 cases, fixed dangling `BNGcoreLoweringContext` + `stripQuotes`), and `test_nfsim_ast_adapter` fallback-reason checks — part of **408/408 CTest**.

**Second pass, same day.** NFsim's separate expression engine is gone: the
`mu::Parser` interface is retained but backed by
`bng::parser::parseExpression` + `bng::eval::evaluate`, and ExprTk,
`NFSIM_USE_EXPRTK`, and the root ExprTk `FetchContent` block are removed
(WO-3 and WO-3b). The shim's underscore-remapping and logical-operator
rewriting layers were deleted as unnecessary against the BNGL lexer and
`Expression`'s native operators. `HNauty.hpp`
is marked UNUSED-reference, `SpeciesLabel=Quasi` is accepted-but-warned as
UNUSED, and `python/bionetgen/modelapi/` is marked legacy with its live
default-path dependencies recorded — it is still imported by
`bionetgen/__init__.py` and cannot be deleted yet. The nested
local/composite direct-NFsim refusal is root-caused but deliberately NOT
fixed; see the addendum. This pass is now also built and linked (`nfsim_core` no longer defines `NFSIM_USE_EXPRTK`, no `exprtk` include) and covered by the same 408/408 run.

Remaining implementation gaps are not low-hanging: the direct-NFsim refusals
that are still open are energy lowering (out of scope), population maps
(fail-closed by design and routed through the hybrid backend), and nested
local/composite function mapping, which is a semantic mismatch rather than a
missing translation. `SpeciesLabel=Quasi` would mean adding a second
canonicalization mode. `cpp/core/HNauty.hpp` still has zero callers pending
the open largest-vs-canonical-form maintainer decision.

The chief regression risks for the next hosted CI run remain the **MSVC matrix** (the
merged nauty header changes `HAVE_SYSTYPES_H` under `_MSC_VER`) and the
**strict validation corpus** (`setOption` can now throw; verified locally to still load corpus-present options).

## Experimental nonequilibrium energy layer — barrier patterns and driving reservoirs

Added but **gated off by default**. `begin barrier patterns` and `driven_by(W)`
are accepted at the language surface and lowered through the AST, the compiled
IR, both NFsim input paths, and XML serialization, implementing

```
k_f = exp[-(Ea + B + phi       * (dG - W)) / RT]
k_r = exp[-(Ea + B + (phi - 1) * (dG - W)) / RT]
```

`BNG_NFSIM_GENERAL_ENERGY` must be set for any backend to accept either
construct; unset, both report `Unsupported` for the network compiler and for
NFsim. The gate is not a convenience switch — canonical NFsim and BNG2 do not
implement these semantics, so the differential-parity evidence BNG3 normally
requires cannot be produced yet.

State of validation, stated precisely at authoring time. The original authoring environment had no network
access, so the FetchContent build was never run and nothing had been linked or
executed through a real parse.

- **Executed and passing** (`tests/energy/standalone/run_checks.sh`, C++17
  compiler only): the thermodynamic analysis including insertion-order
  determinism; barrier keying, accumulation and canonical key round-trip; a
  300-combination sweep proving the NFsim and network energy conventions
  describe the same kinetics, plus a demonstration that the reverse-direction
  work negation is load-bearing; the accepted/rejected surface syntax; and the
  full post-parse lowering with all eight of its fail-closed paths.
- **Type-checked only** (`-fsyntax-only` against real headers, never run): the
  AST, capability, compiled-IR, XmlWriter, NFcore energy and NFsim input
  adapters. `BarrierCompiler`'s graph-diff classification falls here, because
  `PatternGraph` can only be built through ANTLR parse contexts — that is the
  largest remaining gap.
- **Not checked at all** (need the real ANTLR4 runtime): `BNGAstVisitor.cpp`,
  `NetWriter.cpp`, `NFinput.cpp`, and the parse-dependent contract fixture.

**Update 2026-09-17 on `feat/merge-nonequilibrium-convergence`:** the four previously `Not checked at all` units are now compiled and linked in `bng_parser`/`bng_engine`/`nfsim_core` (fixes: qualified `finalizeThermodynamicMetadata`, `NetWriter.cpp` includes, `stripQuotes` in `BNGAstVisitor`). `test_energy_compiler_contracts` now builds and passes with the promoted `future_barrier_driving_syntax`/`future_thermodynamic_constraints` plus `test_thermo_source_normalization`/`test_barrier_and_driven_energy`/`test_thermo_model_finalize`/`test_energy_export_guard` (43 cases total) as part of **408/408 CTest**; `standalone/run_checks.sh` still passes. `BarrierCompiler`'s ANTLR-dependent graph-diff remains the largest gap (covered by `standalone` but not yet by an oracle differential), and no independent oracle exists for barrier/driven semantics by design (gated).

The compact `EnergyRxnClass` evaluator is disabled for any rule with nonzero
barrier or work; those rules take the materialized Sekar expansion.

Design, fail-closed inventory, and architecture table:
[`docs/nonequilibrium_energy.md`](nonequilibrium_energy.md).

## Current continuation checkpoint — 2026-09-15

The preceding continuation was based on public `main` at
`bad50c9cd659efd893e47d8b88bcfebaa4ebc2ba`; the current material-gap batch is
based on `2af9506a1124ce7ebdc30c6967c771f1cd91c63c` in the isolated branch
named above. The direct-NFsim and NFnext evidence below remains historical
context for the current checkpoint.

Direct NFsim validation now preserves and asserts the runtime
`construction_path`: the compatibility leg must be `in-memory-xml`, while the
direct leg must be `direct` with XML fallback permission removed. Required
compiled backends and independent oracles fail closed when unavailable.
Source-tree ensemble workers receive both the repository root and `python/`
on `sys.path`, and every ensemble member must use direct construction. The
hosted parity contract covers the fixed-seed `motor` and `tlbr` endpoint
fixtures as well as the seeded `simple_system` ensemble.

The typed Lean example and the production C++ contract independently exercise
the same bounded rule, `A(x~u) + B(y) -> A(x~p!1).B(y!1) k`. The C++ contract
crosses BNGL parser -> `bng::compile::CompiledModel` ->
`nfnext::lowerFromBioNetGen`, checking distinct-reactant molecularity, a state
update, and a new bond. This is correspondence evidence for one NFnext slice,
not complete Lean kernel verification or backend equivalence. Population maps
remain fail-closed for direct NFsim and are routed through the hybrid backend.

The local code checkpoint immediately before this documentation merge is CTest
`312/312`, strict validation `71/71` with zero failures/errors/skips, action
contracts `6/6`, CI-contract tests `26 passed`, energy tests `66 passed`,
independent NFsim `10 passed`, Lean static validation `36` files, NFnext
contracts `18/18`, and passing Black, Ruff, provenance, corpus, and
exception-ledger checks. The local Lean kernel remains unavailable because
Lean/Lake/Elan are not installed. This branch remains unpushed: `gh` readback
keeps `origin/main` at `2af9506a1124ce7ebdc30c6967c771f1cd91c63c`, while the
current main CI run is still queued. No hosted result is attributed to this
local head.

## Material migration-gap batch — 2026-09-15

This batch is based on public `main` at
`2af9506a1124ce7ebdc30c6967c771f1cd91c63c` and is isolated on
`codex/bng3-material-gap-completion`. It covers the five requested material
workstreams without changing upstream repositories, pushing, merging, or
publishing.

The direct NFsim acceptance harness now records the construction route and
requires `direct` for the BNG3 leg, with XML fallback variables removed. The
independently built native NFsim oracle is the accepted source cutoff
`3b046fc1b9f76719d92be22279b24992cdae7c35`; the locked BNG2 and PyBioNetGen
source checkouts are recorded in the evidence artifact. The batch evidence is:

| Workstream | Evidence | Result |
| --- | --- | --- |
| Direct NFsim acceptance | CTest plus selected direct/native NFsim parity and protocol contracts | `312/312` CTest; `10 passed` direct/native checks; `2 passed` direct-NF protocol contracts |
| Structured SBML and formats | ID-independent BNG2 structured-SBML admission, strict positive-integer stoichiometry, graph-aware rate-expression normalization | `22 assertions` in four native SBML cases; comparator `12 passed` |
| Independent scientific validation | BNG2 structural differential against nine selected models | `9/9` pass; no blanket full-corpus claim |
| Energy CPU port | Symmetric Arrhenius expansion preserves both equivalent reaction centers; fresh-process direct/XML measurement harness | native direct energy gate `1024` seeds passed on `constant_binding`; symmetric expansion CTest passed; benchmark is measurement-only |
| PyBioNetGen qualification | Source-derived API signature check, compatibility runner overrides, isolated wheel install | compatibility `5 passed`; CPython 3.14 arm64 wheel imports and runs modern plus legacy contracts |

The full Python suite reports `404 passed, 28 skipped`; the dedicated energy
suite reports `66 passed`. Ruff, Black, `git diff --check`, provenance, and
100-model corpus-manifest validation also pass.

The selected independent energy gate intentionally excludes exact parity for
the symmetric-site fixture: BNG2/NFsim XML expansion has a known legacy energy
lookup limitation there. BNG3 now preserves reaction multiplicity and keeps the
direct physics path explicit, but the independent symmetric statistical result
is retained as a known limitation rather than relabeled green. The source
`t4`/`t5` fixtures also remain governed: their legacy syntax is rejected by
both the current BNG3 parser and the checked BNG2 2.9.3 runner.

Remaining completion work is broader than this batch: approved provenance and
release ownership, full Tier-NF protocols/corpus, the remaining CPU evaluator
parity slices, complete SBML/Atomizer/writer round trips, cross-platform wheel
CI, and local Lean kernel verification. No convergence or release claim is
made from this checkpoint.

## Published BioModels validation checkpoint — 2026-09-15

The manifest `provenance/published-biomodels.json` is query-backed rather than
a hand-picked sample: the official manually curated inventory contains 1,096
records, of which 1,075 are SBML and 21 are explicitly non-SBML formats. The
runner `scripts/ci/validate_published_biomodels.py` accounts for every record,
then validates each SBML artifact through modern import, BNG3 network
generation, C++ SBML writing, modern/native re-import, and direct comparison of
all generated observables from BNG3 CVODE against libRoadRunner CVODE on a
shared time grid. The complete report is retained in the task outputs as
`curated_biomodels_roundtrip.json`; its strict gate remains red where models
fail representation, integration, parity, or bounded-time checks.

The same round-trip/simulation gate runs against the official SBML Test Suite
release checkout at commit `cf38585fac5de8e0e90112febb62851ee2181816`, covering
all 1,823 semantic and 100 stochastic canonical cases available there. The
release checkout has no syntactic case corpus; SBML Test Suite reference-result
conformance is not claimed. The complete report is retained as
`sbml_test_suite_roundtrip.json`.

Re-run the BioModels audit with cached bytes or let the runner fetch missing
files from the official BioModels download endpoint:

```text
PYTHONPATH=python:build/cpp python scripts/ci/validate_published_biomodels.py \
  --cache-dir /path/to/cache --json work/published-biomodels.json \
  --isolate-models --jobs 8 --model-timeout 60
```

These are reproducible import/round-trip and cross-engine numerical-parity
checks, not a claim of complete SBML schema coverage, reference-result
conformance, or biological validity.

## Imported material

The cumulative import retained the three supplied snapshots, with the
2026-09-14 source tree taking precedence where snapshots overlap:

- `BNG3-Lean-formalization-latest.zip` — SHA-256
  `460f89c4380bde3a6f52377397d32ca098efc19c8fdbf675eeac33aa6bb5d530`
- `BNG3-ir-migration-everything-so-far-2026-09-11.zip` — SHA-256
  `31342054fc902b7ed3777be799a9a5d6dc5c5534ff3aa27afe8f6f556156e5e7`
- `BNG3-ir-migration-current-2026-09-14.zip` — SHA-256
  `523219fa6cd05928830482d74e88633a44cf2f53e6944c1fc72cd144229bfbac`

Archive reports, source locks, manifests, and provenance records remain in
place. Generated Lean build output is not part of the import.

## Previous full-corpus CI, Windows compatibility, and repository-organization checkpoint — 2026-09-15

The preceding semantic validation and documentation/Windows repair commits
closed the former full-corpus
checkpoint closes the former full-corpus
reference exclusions: independent BNG2 `.net` references now cover the
previously missing network fixtures, and
`tests/validation/validation_manifest.json` routes the six action-focused
fixtures through explicit output contracts in `scripts/validate_actions.py`.
The native reader also has a narrow, fail-closed legacy structured-SBML
`atomize=>1` contract for the `plain2` fixture, and reverse local-rate scope is
preserved during rule expansion.

The live local evidence for that semantic commit is:

| Gate | Result |
| --- | --- |
| Native CTest | `308/308` passed |
| Full validation corpus | `71 passed, 0 failed, 0 errors, 0 skipped` |
| Action-output contracts | `6/6` passed |
| CI-contract tests | `26 passed` |
| Energy Python tests | `66 passed` |
| Black, Ruff, corpus, provenance, and exception-ledger checks | passed |

The former exclusion ledger is closed with empty PR and weekly profiles. The
historical migration reports and text metadata are organized under
[`archive/reports/ir-migration-2026-09-14/`](archive/reports/ir-migration-2026-09-14/);
obsolete patch snapshots and duplicate package wrappers were removed after
their changes were applied. Handoff documents remain historical provenance,
while this page and the convergence checklist are the live status sources.

The exact-head hosted CI run
[`34896645707`](https://github.com/RuleWorld/BNG3/actions/runs/34896645707)
completed successfully, including the Windows/MSVC matrix, full corpus on
Ubuntu/macOS/Windows, package smoke, and integration tests. Cross-tool parity,
Lean, CodeQL, and formatting runs also completed successfully. The preceding
hosted head exposed a
Windows/MSVC-only ANTLR failure: `NFinput.cpp` could enter the runtime through
generated visitor headers before the translation-unit compatibility include.
Those generated headers now include `parser/antlr_compat.hpp` themselves, and
the current local rebuild passes. The scheduled NFsim historical job and
release-only artifact/publish jobs are conditionally skipped by their event
guards; the full validation corpus has no skipped fixtures and the exclusion
ledger is empty. Broader backend equivalence, release qualification, and
convergence are still incomplete.

The follow-up PR head `9efa0e9df8903ee616437f8555906fcfdda4c762` also passed
hosted PR CI run
[`34971571944`](https://github.com/RuleWorld/BNG3/actions/runs/34971571944),
including the full no-exclusion corpus on Ubuntu, Windows, and macOS. The
auxiliary manual-dispatch run `34971595435` was canceled before its wheel jobs
started so wheel validation remains deferred until merge. The first main-push
CI run after the merge is the authoritative wheel result for this repair.

## Wheel CI repair checkpoint — 2026-09-15

The main push run
[`34901298982`](https://github.com/RuleWorld/BNG3/actions/runs/34901298982)
exposed two independent wheel-environment failures. The macOS x86_64 build
used deployment target 10.9, which is below the macOS availability of the
ANTLR runtime's `std::optional::value()` and `std::shared_mutex` usage. The
manylinux2014 wheel test resolved NumPy 2.5.3 from source, where the image's
GCC 10.2.1 is below NumPy's GCC 10.3 minimum; no compatible manylinux2014
binary was available for that target.

The follow-up repairs both `.github/workflows/ci.yml` and
`.github/workflows/release.yml`: cibuildwheel is pinned to 4.2.1, macOS
builders use their native runner architecture with deployment targets 10.13
(macos-13/x86_64) and 11.0 (macos-14/arm64), and Linux wheels use
`manylinux_2_28` so current NumPy test dependencies resolve to binary wheels.
The CI workflow also exposes a manual-dispatch path for the wheel matrix so
this repair can be validated on the exact follow-up head before release
qualification. The auxiliary hosted rerun is paused until merge; this
checkpoint makes no wheel or release-success claim until the post-merge main
matrix is terminal-success.

## Repairs in this checkpoint

- Retain the lowering context owned by generated native graphs so graph node
  and state-type references remain valid after network generation returns.
- Parse native unbound markers and preserve NFcore2 equivalent-component
  reaction-center semantics.
- Repair compiled NFsim handling for dynamic expressions, time and reactant
  references, function dependencies, reversible Arrhenius/function-product
  rates, and symmetric molecule-observable embeddings.
- Preserve model-defined `_Na` parameters at the compiled NFsim boundary so
  direct AST construction and the XML compatibility path use identical values.
- Repair ODE observable references in functional rates and add a pinned PR
  workflow for Lean kernel, smoke, and NFnext contract checks.
- Preserve reverse-direction local-rate scope and accept legacy action argument
  lists for hybrid, visualization, and network-writing actions.
- Close the validation exclusions with independent network references and
  explicit action-output contracts; remove the old skip arguments from PR and
  weekly validation jobs.
- Apply the Windows SDK macro compatibility guard to every generated ANTLR
  parser/visitor header, covering direct include paths used by the legacy NFsim
  adapter as well as the modern parser targets.

## Verified gates

| Gate | Current evidence |
| --- | --- |
| Native CTest | `308/308` passed after the current rebuild |
| Python package tests | `399 passed, 28 skipped` excluding SBML import; isolated SBML test `1 passed` |
| Validation smoke | `4 passed, 14 skipped, 178 deselected`; skips are explicit environment/reference conditions |
| Export validation | `12 passed, 184 deselected` |
| BNG2 structural differential | `5/5` selected models passed against locked source revision `e0a5c6d9e6c4730f66102e48d0d0a598337083e7` |
| BNG2 broad validation subset | `11 passed, 89 skipped, 96 deselected`; this is not full Tier-P qualification |
| Full validation corpus | `71/71` passed with `0` failures, `0` errors, and `0` skips |
| Explicit action-output validation | `6/6` passed for the former action-focused exclusions |
| NFsim direct/XML | `10 passed` for the selected independent NFsim gate: four direct/XML checks, four 200-run ensemble comparisons, and two fixed-seed endpoint checks |
| Lean/NFnext local checks | static validation `36` files, NFnext contracts `18/18`; local kernel check unavailable because `lean`, `lake`, and `elan` are not installed |
| Provenance/corpus/ledger | provenance validation, corpus validation/generation check, and zero-active-exception ledger all pass |

The independent NFsim oracle is built from source revision
`a6f9fa945c9d6e1e122e789c952260112c93f157`, binary SHA-256
`c0974ad71a88938ed3f2ed096878d53aec14e946c91e28e1bc644759db1da3b4`.
The independent BNG2 source revision used for the structural subset is
`e0a5c6d9e6c4730f66102e48d0d0a598337083e7`.

These results are exact-head evidence for the listed fixtures and commands.
They do not establish complete corpus parity, backend equivalence, release
readiness, or convergence.

## Remaining plan of action

1. Expand the independent BNG2/NFsim differential matrices over the locked
   corpus, replacing environment-induced skips with runnable oracle coverage
   where possible and recording any maintainer-approved dispositions.
2. Continue the direct NFsim adapter audit for dynamic rates/functions, energy,
   observables, population maps, and unsupported constructs; add a focused
   fixture and oracle result for each newly supported semantic slice.
3. Triage remaining native/Python/parity gaps by source-integration failure
   versus semantic mismatch, preserving fail-closed behavior and the current
   exception ledger.
4. Connect the typed Lean reference to a small real C++/NFIR lowering slice,
   then promote NFnext contracts only after backend-equivalence evidence exists.
5. After merge, track the main-push wheel matrix on the exact merge head, then
   rerun clean native, Python, oracle, formal, packaging, and release gates
   before any convergence or release claim.

The authoritative completion criteria remain
[`BNG3_CONVERGENCE_DONE_CHECKLIST.md`](BNG3_CONVERGENCE_DONE_CHECKLIST.md),
with repository working rules in [`../AGENTS.md`](../AGENTS.md).
