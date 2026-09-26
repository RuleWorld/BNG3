# BNG3 current progress

**Last targeted audit:** 2026-09-25 (full convergence checklist not re-audited)
**Repository:** `RuleWorld/BNG3`
**Branch:** `main`
**Status:** merged convergence, nonequilibrium energy, and SBML material-gap work; release validation remains incomplete

This is the live status page for the combined BNG3 migration tree. The older
IR migration reports and formalization reports retained in the repository are
historical inputs and provenance records; their embedded prose is not a new
execution instruction.

## Current-head Atomizer and oracle validation — 2026-09-25

Current BNG3 committed `main` base is `a5f65ae05e26926b013f4ec3305dab34a3e9c84f`
after `git pull --ff-only`; the working tree also has a SymbolTable diagnostic
fix, BNGIR schema updates, and the Atomizer molecule-type writer fix recorded
below. Focused PR review covered #16 (SBML/Atomizer round-trip validation),
#24 (Atomizer structure-copy optimization), and #25 (selected compatibility
and issue ports).

PR #24 is the current merge head. Its hosted C++ and Python platform matrices,
independent BNG2/NFsim parity, full-corpus validation, and integration checks
are green. Release-only wheel, source-distribution, Docker, and PyPI jobs were
skipped by their event guards. PR #16's earlier head `192dfff` had build-job
failures across its platform matrix; those results are historical and are
separate from the later green PR #24 merge-head checks.

The Python extension was rebuilt from this source with
`BUILD_PYTHON_BINDINGS=ON`. The prior `build/CMakeCache.txt` had bindings
disabled and contained a Sep 17 extension without the current SBML metadata
writer signature. The initial suite report from that stale module was
discarded. The corrected full SBML Test Suite run selected all 1,923 cases at
suite revision `cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054
explicitly unsupported, 0 failed, 0 timed out. The full run was repeated after
the initial-assignment and species-pattern changes with the same counts. Each
pass includes modern Atomizer import, BNG3 network generation, SBML
write/reimport, native reader, and all-observable BNG3 CVODE/libRoadRunner
CVODE comparison. Current report:
`/private/tmp/bng3-sbml-suite-current-patternfix.json`, SHA-256
`9499f41242ec04d4ea850cfcab4a8c35bfea23354a58081ccc70f74530ea1827`.
All 100 stochastic cases remain unsupported. SBML Test Suite reference-result
conformance was not run. A selected regression also passes for
`semantic/00001`; the one-case invocation reports the corpus-level core gate
false because it is not a complete suite run.

Independent compatibility checkpoints on this BNG3 head:

- BNG2 `8726b30b` structural NET comparison: 9/9 selected models pass using
  the canonical sibling checkout at `bng2/BNG2.pl`.
- PyBioNetGen `43b09a53` source-derived API compatibility: 5 tests pass.
- Native NFsim `c51c7a34`, rebuilt from its independent checkout; BNG3 direct
  versus native NFsim parity: 10 tests pass. Binary SHA-256 is
  `093707031f70e0c376179e1d8bf89ab1373b3132b6211d7d9759f1d646c4ce9e`.

The post-writer-fix offline BioModels run completed all 1,075 declared SBML
records (the inventory also includes eight SBML files extracted from
archives). Flat mode passed 650, marked 290 unsupported, and failed 2;
atomized mode passed 649, marked 290 unsupported, and failed 3. Another 133
models timed out in the combined per-model run. Across the full inventory,
649/1,083 SBML records passed, 298 were unsupported, 3 failed, and 133 timed
out. Successful records were compared on all generated BNGL observables
against libRoadRunner. The aggregate core gate remains **failed**. Full report:
`/private/tmp/bng3-curated-a5f65ae-hyphenfix-both.json`, SHA-256
`9590a5bfc01027ffdf08b25b799648082f03a18d5de6fad7ed8895ecb6cdb582`.
The run used BioModels manifest inventory version `provenance/published-biomodels.json`.
Correctness counts do not measure runtime speed. A controlled before/after
performance comparison for PR #24's Atomizer copy optimization remains open.
The missing `SymbolKind::BarrierPattern` display name is fixed in the working
tree. The new duplicate-barrier-label regression was observed failing with
`duplicate symbol declaration`, then passed as CTest case 82 after adding the
specific kind name (1/1). Rebuilding this working tree passed all 440 CTest
cases. The full Python suite initially found three BNGIR schema mismatches;
the 0.1 and 0.2 schemas now describe the emitted optional barrier-pattern and
driving-work fields while accepting older documents. The suite now passes
471 tests with 28 skipped.

The curated rerun also exposed a shared Atomizer self-parse bug: generated
patterns normalized hyphens in site/state names, but the molecule-type writer
did not. A red-first regression and the writer fix now pass; all 15 curated
models previously failing Atomized-mode parsing parse on the current tree.
Two now pass the full two-mode validation. Thirteen proceed to network
generation but exceed the combined 90-second per-model timeout; a staged
debug run for `BIOMD0000000049` shows the size cause: after 30 seconds network
generation was still in iteration 3 with 88,030 species and 99,600 reactions.
The 12.7 MB debug log is `/private/tmp/bng3-biomodel-0049-network-profile.log`,
SHA-256 `786fddfe0967c9109d2ac4859c484f21989a4f9b4a1c3e7cfe0269618ab448ff`.
Four other selected Atomized models timed out with 180-second limits when run
concurrently. These remain timeouts, not passes.

A local alpha wheel was rebuilt from this tree and installed into a clean
target directory. The installed extension imports, the hyphen-normalized
molecule-type output parses natively, and the smoke check passes. Artifact:
`/private/tmp/bng3-wheel-a5f65ae-hyphenfix/bionetgen-3.0.0a1-cp314-cp314-macosx_26_0_arm64.whl`,
SHA-256 `066d4491cad2fd0beb0439db47d1cb2cc99ff82aab800d602055d80564af8c0c`.
This is a local CPython 3.14 macOS arm64 preview wheel, not a release
candidate; Windows `.exe`, other platform wheels, clean dependency resolution,
hosted release jobs, and corpus gates remain open.

## Initial-assignment seed follow-up — 2026-09-25

Triage of the curated BioModels failure `BIOMD0000000429` found that static
initial assignments chained through SBML `piecewise` conditions remained as
symbolic BNGL seed amounts. BNG3 then rejected network generation. The writer's
restricted constant folder now handles arithmetic, comparisons, logical
conditions, and lazy `if` branches; unknown expression forms remain
unresolved. A red-first regression checks a two-species dependency chain and
confirms an unselected divide-by-zero branch is not evaluated.

The isolated record now passes in both flat and Atomized modes: SBML
write/reimport, native-reader/network checks, and all 30 observables versus
libRoadRunner 2.10.0. Both routes used CVODE on `t=0..1` with 10 steps;
comparison passed at the existing tolerances. Input SHA-256:
`a1353c11190c33b80c881cb4ed5ad9a8cd41facf89d1efc5c73a22cde561c839`.
Report: `/private/tmp/bng3-biomodel-0429-final-roundtrip.json`, SHA-256
`ea33737bae5efb0e7de27ac4fab180ddb92add092bd42af2c3255f93b8165b5e`.
The previous full inventory report predates this fix and has not been rerun;
its aggregate counts remain historical until that run completes.

## SBML pattern-name round-trip follow-up — 2026-09-25

Curated BioModels `BIOMD0000000202` exposed a second round-trip defect.
BNG3-written SBML stores explicit BNGL molecule patterns in species names;
the Atomizer discarded site-free `M_...()` names in favor of SBML IDs, while
the molecule-type writer duplicated an existing `M_` prefix. Reimport also
turned active numeric state `0` into `_0`. The Atomizer now preserves explicit
prefixed patterns, type declarations reuse an existing prefix, and numeric
active states remain numeric. Red-first regressions cover all three rules.

The selected model now passes flat and Atomized import, network generation,
SBML write/reimport, native-reader checks, and all 17 observable comparisons
against libRoadRunner 2.10.0. Each reimport network has 8 species and 16
reactions. Input SHA-256:
`c841590d8ed0e219d5a0cc0d761030ddf00f898a1bfafb2fa705d9aa07322506`.
Report: `/private/tmp/bng3-biomodel-0202-final-roundtrip.json`, SHA-256
`40a5e1c8863b8f18b539ebcf90c1a39dc630b25b4dd6a54ff8ba9d21e1a43f18`.
At the time of this targeted check, the full-corpus status was still pending;
the completed rerun below supersedes that status.

## Post-fix full-corpus validation — 2026-09-25

The full offline BioModels inventory was rerun in both flat and Atomized modes
after the initial-assignment and species-pattern round-trip fixes. Inventory
completeness matched all 1,096 curated records, including 1,075 declared SBML
records and 21 non-SBML records. The SBML path covered 1,083 records after
including 8 archive-extracted SBML files. Each mode passed 651 records,
reported 298 unsupported SBML records, and retained one numerical failure;
133 records timed out across the combined run. The remaining failure is
`BIOMD0000000584` in both modes. Aggregate core gate remains failed.

Both newly fixed models now pass in the full rerun: `BIOMD0000000429` and
`BIOMD0000000202`, each in flat and Atomized modes with SBML write/reimport
and libRoadRunner comparisons. Report:
`/private/tmp/bng3-curated-current-post-patternfix.json`, SHA-256
`5e5f46244c71f8bea7f34c23eb784e504abdf3cef9b07ef57cec1f8cb02767da`.

Before the ODE rate-lookup fix below, `BIOMD0000000584` failed in both modes
on `proAUR1`, `proSLS1`, `proSLS4`, and dependent assignment-rule observables.
Direct libRoadRunner runs on source and BNG3-written SBML agreed at sampled
times while BNG3 CVODE differed; later isolation found the rate-lookup cause.

## ODE derived-rate name collision fix — 2026-09-25

`OdeIntegrator` fallback searched parameter names for a reaction label as an
unanchored substring. Network rule label `R1` therefore matched unrelated
parameter `proAUR1_degradation_rate` and changed a zero-order synthesis rate
from `1` to `0.1`. Fallback now requires the NetWriter prefix `R1Rate_`; a
regression checks both the collision and a legitimate `R1Rate_2` lookup.

The isolated BioModels record now passes flat and Atomized routes, including
all 56 observable comparisons against libRoadRunner. Report:
`/private/tmp/bng3-biomodel-0584-after-ratefix.json`, SHA-256
`dea4af9150c7622d0ecc6781c5a1600caa1dc409328640af15ca2e057970df72`.
The full BioModels corpus rerun after this C++ fix is in progress; the prior
aggregate counts remain the latest completed full run until it finishes.

After formatting the Atomizer core change, final local checks pass: Black,
Ruff, `git diff --check`, all 477 Python tests (28 skipped), and all 441 CTest
cases. CTest command: `ctest --test-dir build --output-on-failure -j 8`.

The full offline curated BioModels inventory has now been rerun on this tree
after the ODE derived-rate name collision fix. Both flat and Atomized modes
pass 652 of 1,083 SBML records, classify 298 as unsupported, time out on 133,
and report zero failed records. The prior `BIOMD0000000584` numerical failure
now passes in both modes, including all 56 observables against libRoadRunner.
The inventory remains complete at 1,096 records (1,075 declared SBML, 8
archive-extracted SBML, and 13 other/non-SBML formats). The aggregate core gate
remains failed because unsupported records and timeouts remain. Report:
`/private/tmp/bng3-curated-post-ode-ratefix.json`, SHA-256
`ec12c4c1b41947346c963c867280d831512a5e254cbd6f2ab6e6270f258ba108`.

The full SBML Test Suite rerun after this fix completed all 1,923 cases:
869 passed, 1,054 were explicitly unsupported, and none failed or timed out.
The 1,823 semantic cases yielded 869 passed and 954 unsupported; all 100
stochastic cases remain unsupported. Each pass completed SBML input validation,
modern Atomizer import, network generation, SBML write/reimport, native-reader
checks, and all-observable BNG3 CVODE versus libRoadRunner CVODE comparison.
SBML Test Suite reference-result conformance was not run. Report:
`/private/tmp/bng3-sbml-suite-post-ode-ratefix.json`, SHA-256
`afc05cec62e1453a025a00d01052e17e66691ebbbee16ff7b3a6fd452087c61f`.
Release qualification remains open.

## Matcher and benchmark continuation — 2026-09-25

A candidate optimization changed the molecule-type prefilter from one graph
scan per required type to one scan for all required types. A paired BNG3
comparison used 25 fresh generation runs of the `blbr` model, which exercises
a two-type complex reactant. Both versions generated 20 species and 92
reactions. Baseline median generation time was 19.079 ms (SD 0.278 ms);
candidate median was 18.996 ms (SD 0.421 ms). The 0.084 ms difference is
inside run variation, so the candidate was reverted. The earlier five-model
benchmark process was still active during both runs, so CPU contention also
limits this comparison. That unbounded process was later terminated with
SIGTERM (exit 143) without a result report. Before/after reports:
`/private/tmp/bng3-blbr-generation-before.json`, SHA-256
`697e4726818cb8f3e4b1d98ccb6f92f33b3b08cbad6525022fdbbea3d00e805f`; and
`/private/tmp/bng3-blbr-generation-after.json`, SHA-256
`aa9bc9e4c14d9af97a40ee6eb1c0beaec9265ab25a245b55c75a06b41c508a29`.
The independent multi-type matching regression remains under its general
behavior name. After restoring the baseline implementation, the build and
full CTest pass `441/441`; the full Python suite passes `471` tests with `28`
skipped.

The candidate also received a 30-second debug profile on Atomized
`BIOMD0000000049`, but the five-model runner was active concurrently and debug
logging changes throughput. It reached iteration 3, rule R25, with 77,954
species and 106,164 reactions; the earlier profile ended at rule R22 with
88,030 species and 99,600 reactions. These counts are diagnostic only, not a
before/after performance comparison. Candidate log:
`/private/tmp/bng3-biomodel-0049-prefilter-profile.log`, SHA-256
`904af205b9260d5c8929a1a8cb0c7b0fa3ef6749874ef6f2909de42d2cbe478a`.

The benchmark runner now accepts a model subset, generation-only mode, and
repeated fresh loads; it records per-run durations and checks species/reaction
counts before reporting medians. Its `simple_system` smoke completed three
repetitions at 4 species/4 reactions; JSON:
`/private/tmp/bng3-simple-system-generation.json`, SHA-256
`3034af37d84717221582572d5f0dc47e411a7c79f91556941d378a48b85de97e`.
This validates the harness, not the PR #24 Atomizer copy optimization.

After restoring the baseline matcher, SBML Test Suite `semantic/00001` passed
Atomizer import, network generation, SBML write/reimport, native-reader checks,
and comparison of all four observables against libRoadRunner 2.10.0. Report:
`/private/tmp/bng3-sbml-case-00001-final-pattern-roundtrip.json`, SHA-256
`6eb1281a24165ec12b5e5bc3f0203b0166ac46bff3df32ce3bba7524e024afc`.
Curated BioModels `BIOMD0000000832` passed both flat and Atomized routes, each
comparing 40 observables against libRoadRunner 2.10.0; record-level core
status passed. Report:
`/private/tmp/bng3-biomodel-0832-final-roundtrip.json`, SHA-256
`b8ecf106528322a0b96bc1dffbd53afe7bcda4ff391426bb62b8f31dc2125630`.
The one-record commands report corpus-level failure because they do not cover
the full corpus. These selected passes do not replace either full gate.

The BNG2 tier-S parity harness was attempted; one model had a usable local
reference and nine were skipped because the sandbox blocks Perl's `ps` call
and the required `run_network` executable is absent. This attempt adds no new
parity claim; the earlier selected 9/9 BNG2 result remains at its recorded
source checkpoint. The full BioModels report still records 13 Atomized-mode
network-generation timeouts after the earlier parser fix. The unresolved
performance comparison for PR #24's Atomizer copy path now has a controlled
timing sample. A new fresh-process runner,
[`../benchmarks/benchmark_legacy_atomizer.py`](../benchmarks/benchmark_legacy_atomizer.py),
repeats the legacy CLI and records implementation/input hashes, raw output
hashes, a canonical model hash, and per-run timings. On curated BioModels
`BIOMD0000000832` (input SHA-256
`b35ee199b0b2a7ee7bdfb50ef78e76edf649f280f7131b2e4ca170efd26e424e`), 10
interleaved fresh-process runs per revision produced identical canonical
BNGL SHA-256
`e53e0d2c256df2ff7a01c2f8b9bb2971f1579149aa0da77a797f3f7bad4c2b47`.
Parent `1ccf76d` median was `1152.704 ms` (SD `44.779 ms`); current
`a5f65ae` median was `1148.664 ms` (SD `82.756 ms`), with paired median
ratio `0.9982`. This is within observed run variation and shows no measurable
speedup. The peak-memory comparison and full performance gate remain open.
The report is `/private/tmp/bng3-legacy-atomizer-0832-pr24-interleaved.json`
(SHA-256 `c171fe22a2b395b6cffd4f4bc68b6159461e7ae11128597eabfc87b855490039`).

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
- `PYTHONPATH=build/cpp:python python -m pytest tests/python -q` — **411 passed, 28 skipped** at this historical 2026-09-17 snapshot. The three schema failures at that time were fixed in the 2026-09-25 current working tree; current result is 470 passed, 28 skipped.
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

## NFsim final-sample boundary — 2026-09-25

The direct NFsim adapter had been firing a pending event beyond the last
requested sample before recording that sample. Removed this special endpoint
behavior and added a regression that confirms a birth event after the stopping
time is excluded. The focused sampling tests pass (2 passed). An exact-seed
comparison against native NFsim still differs by one event at the last point
for `motor` and `tlbr`, so no exact-trajectory claim is made for those fixtures.

After the correction, the 200-run Atomizer benchmark for `BIOMD0000001038`
passed in flat and Atomized modes: 200 valid trajectories per engine and all
66 sampled mean comparisons within the pooled-error criterion (worst z 0.0).
Report `/private/tmp/bng3-atomizer-nfsim-1038-post-endpoint-fix-200runs.json`,
SHA-256 `2587d27ff7430e50c57742757facffdfc29966f459567573fa37db7871afbd2d`.
`BIOMD0000000485` also passes after the correction: 200 valid trajectories per
engine in each mode and all 44 sampled mean comparisons within the
pooled-error criterion (worst z 0.0). Report
`/private/tmp/bng3-atomizer-nfsim-0485-post-endpoint-fix-200runs.json`,
SHA-256 `d2e6f444a05980b5413b45b42bc92b6f6d632a35c5b51068cbd9f24fa3e0af2f`.
`BIOMD0000000414` also passes 200 runs per engine in both modes at 22 sampled
points (worst z 0.0). Report `/private/tmp/bng3-atomizer-nfsim-0414-200runs.json`,
SHA-256 `24f5e3dd133e28a76ccf22c9d5ff0d3861f416183ee14e032fb2303ddc6c8af5`.
`BIOMD0000000425` passes the same 200-run matrix at 22 sampled points (worst
z 0.0). Report `/private/tmp/bng3-atomizer-nfsim-0425-200runs.json`, SHA-256
`ddf0f49dd104df5fac89e71573c54063e89515ff13000855956e17a54c81422e`.
`BIOMD0000000850` also passes 200 runs per engine in each mode across 66
sampled points (worst z 0.0). Report
`/private/tmp/bng3-atomizer-nfsim-0850-200runs.json`, SHA-256
`ee739d211722cb8b6a3cc3c67d0f9af6c39a3a82216a54af8ac47bc3ecc5478f`.
`BIOMD0000000906` passes 200 runs per engine in both modes across 66 points
(worst z 0.0). Report `/private/tmp/bng3-atomizer-nfsim-0906-200runs.json`,
SHA-256 `43e110a36e07c4c2f27ec566879900ff199a587f3ac58255fa60cbd8852d1f7c`.
These are bounded checks; full NFsim corpus parity and release criteria remain
open.

The molecular Atomizer case `BIOMD0000000584` does not yet have an independent
NFsim result: BNG3 direct completed 200 runs in each mode, but standalone
NFsim rejected all BNG2 XML trajectories because nested function `LAMDAR()`
was undefined in a generated rate law. No ensemble comparison was made. Report
`/private/tmp/bng3-atomizer-nfsim-0584-post-endpoint-fix-200runs.json`, SHA-256
`bd40306f9560d496b98f57a3e9e38bfaa676579ccf7f25a6031bd5118ec950ec`. This
records an oracle gap, not a BNG3 pass.

## Atomizer cross-engine benchmark — 2026-09-25

Added `benchmarks/benchmark_atomizer_cross_engine.py` and run instructions in
`benchmarks/README.md`. The harness times repeated modern BNG3 and independent
PyBioNetGen legacy Atomizer conversions, runs each BNGL result through BNG3 and
Perl BNG2, and reports structural and rate-expression parity separately.

The bounded run covered curated BioModels `BIOMD0000000584` and
`BIOMD0000000202`, flat and Atomized modes, three repetitions per route. All
12 modern BNG3 conversions generated structurally matching BNG2/BNG3 networks:
21 species/14 reactions for `0584`, 8 species/16 reactions for `0202`. Rate
comparison failed closed in every case because the two network writers
serialize generated function/rate expressions differently. No rate or
trajectory parity claim is made from this result.

The legacy PyBioNetGen Atomizer produced no BNG2-parseable networks in the
successful conversion runs; observed failures include unresolved generated
rate symbols, BNGL syntax rejection, and two legacy Atomizer exceptions on
`0202` Atomized mode. Repeated raw BNGL hashes varied for two routes. Report:
`/private/tmp/bng3-atomizer-cross-engine-584-0202.json`, SHA-256
`484d3f6e4ed8b40729ac09ac91458cfc0d512ce9431bf1a776aa06fa661fdcf8`.

The latest report records source Git heads, dirty-state hashes, and relevant
BNG3 source hashes; its SHA-256 is
`170c11f7965c601d42d60591b38633df29e45b05776b4d98e929e161ff6513f1`.
Modern Atomizer medians were 25.4–25.6 ms on `0202` and 267.7–296.4 ms on
`0584`; successful legacy medians ranged from 354.9–546.5 ms. BNG3/BNG2
network process medians on modern output ranged from 12.3–16.6/87.6–111.4 ms.
These are local timing observations only. The report is a two-model harness
smoke; full-suite cross-engine intersections, rate serialization semantics,
eligible NFsim trajectories, and release qualification remain open.

## NFsim invalid-propensity probe — 2026-09-25

Reproduced a seed-specific crash for curated BioModels `BIOMD0000001037` in
both embedded BNG3 and standalone NFsim. ASan located the embedded crash in the
negative-propensity diagnostic: composite functional reactions have no global
function pointer, but the error path dereferenced one. BNG3 now raises a named
`ValueError` and leaves negative rates invalid. A 200-seed flat and Atomized
probe found the same invalid seeds (8, 149, 194) in both modes; the benchmark
records these failures and suppresses biased means. Standalone NFsim still
exits with signal 11 on them, so there is no valid ensemble comparison for
this model. Report SHA-256:
`ac3976e97346286976a5e2f81a891d0880df724c3f0fd2c49362b81c7b0f2f29`.

The molecular Atomizer models exposed two additional NFsim boundaries.
`BIOMD0000000584` produced 200 valid BNG3 trajectories per mode, but
standalone NFsim rejected BNG2 XML because nested function `LAMDAR()` was
undefined inside a generated rate law. `BIOMD0000000202` produced no valid
runs: BNG3 direct rejected fractional seed amounts and standalone NFsim
rejected composite functions that reference observables. Reports:
`/private/tmp/bng3-atomizer-nfsim-0584-post-endpoint-fix-200runs.json`
(SHA-256 `bd40306f9560d496b98f57a3e9e38bfaa676579ccf7f25a6031bd5118ec950ec`)
and `/private/tmp/bng3-atomizer-nfsim-0202-post-endpoint-fix-200runs.json`
(SHA-256 `2c64b24e845e62efc6837bc4eae1fc47fcf72539528bc2ea1c6eea6453eb9de9`).
The NFsim benchmark now groups identical failure signatures while retaining
failed seed lists; a two-seed 0584 smoke confirmed the report summary.

## Atomizer compartment fixed-seed syntax — 2026-09-25

Modern Atomizer fixed seeds inside compartments previously used
`$@cell:Molecule()`. BNG2 2.9.3 rejects that spelling; its accepted form is
`@cell:$Molecule()`. The writer now emits the BNG2 form, retains lookup aliases
for both conventions, and the BNG3 parser normalizes either input to its
canonical fixed-seed representation.

Validation on the built CPython 3.14 extension: all 70 C++ backend tests and
all 85 modern Atomizer tests pass. The curated BioModel `BIOMD0000000033`
round-trip passed in flat and Atomized modes: both generated 32 species and 26
reactions, wrote and re-imported SBML, and passed libRoadRunner comparisons on
64 observables per mode. This was a one-record selection from the 1,096-record curated
inventory; the validator's corpus-level exit remains nonzero for that partial
selection. Report `/private/tmp/bng3-curated-0033-final-seed-prefix.json`,
SHA-256 `678f73ceecfc855837b3ee06344d4230454f7b0a9783b064f817e1d57c99c9d3`.

A separate manual Perl BNG2 2.9.3 conversion of the corrected fixed-seed
spelling generated a 32-species/26-reaction network and XML. No 200-seed NFsim
result is claimed for this high-population model. Full SBML Test Suite and
curated BioModels gates, broad cross-engine measurements, and release
qualification remain open.

## Full SBML gates and expanded Atomizer comparison — 2026-09-25

After the compartment fixed-seed parser/writer fix, the complete curated
BioModels inventory returned 652 passed SBML records, 298 unsupported SBML
records, 133 timeouts, and zero hard failures across all 1,096 inventory
entries. Its supported-surface gate remains open. Report
`/private/tmp/bng3-curated-fixed-seed-full.json`, SHA-256
`fb5023510d46c87e4d25c32a1ea01aae9c59f914c0148355bc96245f8724eda4`.

The full SBML Test Suite rerun at revision
`cf38585fac5de8e0e90112febb62851ee2181816` returned 869 passed and 1,054
unsupported cases, with no failures or timeouts. Its pass path includes
Atomizer conversion, network generation, SBML write/re-import, native-reader
checks, and all-observable BNG3 CVODE/libRoadRunner CVODE comparisons. All 100
stochastic cases and 954 semantic cases remain unsupported. Reference-result
conformance is not run. Report `/private/tmp/bng3-sbml-suite-fixed-seed-full.json`,
SHA-256 `2a60212f9a69fac936d28cc22c3afca76ea82bfbb9836f09b7875a5a0eb6f379`.

Expanded the cross-engine Atomizer benchmark to ten curated models, both
output modes, and three repeats. Modern BNG3 output generated structurally
matching BNG2/BNG3 networks in all 60 comparisons. The strict rate comparator
passed 48/60 after a narrow normalization for compartment-scaled observable
serialization (`(A/cell)()` versus `A/cell()`). Its regression confirms
different rate constants remain unequal. The remaining 12 modern mismatches
are in `BIOMD0000000202` (including a small constant-rate difference) and
nested function wrappers in `BIOMD0000000584`; these remain fail-closed pending
semantic evidence. PyBioNetGen produced BNGL in 54/60 cases; 21/60 had matching
network structure and 3/60 passed strict rate comparison. Legacy Atomized
failures are retained as failures. The report records the native CLI and
parser/comparator source hashes:
`/private/tmp/bng3-atomizer-cross-engine-curated-10-rate-normalized.json`,
SHA-256 `94c7333c4eb17b54368de09f983fa9874d471d2675b136e6764e5b06d98d5a91`.
The `bng_cpp` executable SHA-256 is
`115fbfbbb80773e5f716894eedcadba2ccdbfb8ec3d749394deb8f6eef1312d8`.
These results do not establish legacy trajectory or broad NFsim parity.

A second three-repeat cross-engine slice covered eight SBML Test Suite
semantic cases that passed the full BNG3/libRoadRunner round-trip gate:
`00001`, `01232`, `00829`, `00142`, `00015`, `00270`, `00308`, and `01564`.
Across both output modes, modern BNG3 had 47/48 structural comparisons and
42/48 strict rate comparisons. PyBioNetGen generated all 48 outputs, with
36/48 structural and 30/48 rate comparisons passing. Legacy unresolved
`fRate*` symbols, unsupported math symbols, and Atomized syntax failures remain
open. The modern Atomized network for `01564` has one structural mismatch.
Report `/private/tmp/bng3-atomizer-cross-engine-sbml-suite-8-rate-normalized.json`,
SHA-256 `19048c0e65205de967529b0a36acb7e53151425c444675591599d29f802287bd`.

## Species deduplication repair — 2026-09-25

The 01564 Atomized mismatch came from a missed exact-key lookup after
canonical labeling reordered a generated product graph. `SpeciesList` now
checks the canonicalized compartment-aware key before graph isomorphism, and
the isomorphism fallback confirms per-molecule compartments on mapped nodes.
The first repeat run then exposed hash-seed-dependent Atomized BNGL: a
dependency set was converted directly to a list when constructing a complex.
Dependencies are now ordered by SBML species order. Four separate processes
at hash seeds 0, 0, 1, and 7 emitted byte-identical BNGL. The focused
`SpeciesList` CTest and 37 core/Rulifier Python tests pass. A fresh three-repeat
BNG3/BNG2 comparison generated 52 species and 52 reactions in all six modern
Atomizer runs and matched species, reactions, and observable groups in all
six. The Atomized output hash was stable. Strict rate equality passed in 0/6:
`NetWriter` currently formats the rate factors to 8 significant digits, while
BNG2 emits these values to 12. Align output precision and rerun this slice
before claiming rate parity. The legacy PyBioNetGen Atomizer still fails to
parse this input. Report
`/private/tmp/bng3-atomizer-cross-engine-01564-final-source.json`,
SHA-256 `9647795e68abd8001039d2fce4460581c3540783d29dbc352ac4e2631d89204f`;
the rebuilt `bng_cpp` SHA-256 is
`1a50ed38cfc63312888203b566dafc6195f3a214f9171f3b91f8ef7758531859`.
The `SpeciesList checks exact keys again after canonical labeling` CTest also
passes: isomorphic connected graphs in two insertion orders have different
raw keys, the same canonicalized key, and deduplicate on insertion.
The 20-seed NFsim comparison found no valid ensemble: both direct BNG3 and
standalone NFsim rejected `J47` because `1*atanh(-0.7)` is a negative
propensity. Report `/private/tmp/bng3-atomizer-nfsim-01564-stable-fix.json`,
SHA-256 `ad73f013a305c3862dd65f7407c75735c7b04e3e513b84e2dc59afbd9e0aa003`.
The full SBML Test Suite round-trip was refreshed at pinned revision
`cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054 unsupported,
zero failed, and zero timed out. This gate tests imports and round trips;
SBML Test Suite reference-result conformance remains unrun. Report
`/private/tmp/bng3-sbml-suite-species-dedup-stable-fix.json`, SHA-256
`697f6ff362829b5d889e69de1a68084a6f7d7472e11787d247a08b4f462d5d6c`.
The full curated BioModels rerun against this source completed in both modes
with per-model isolation and a 90-second timeout. The inventory has 1,096
records, including 1,083 SBML records: 654 passed, 298 SBML records were
unsupported, 131 timed out, and there were zero hard failures. The most common
unsupported classes include fractional stoichiometry, state-dependent events,
FBC models, reaction-local symbols referenced globally, and delayed math.
Report `/private/tmp/bng3-curated-species-dedup-stable-fix.json`, SHA-256
`be79a50587ecbf13b6ae2812f8d624e334606a0d54231dd642bb1a2c01a6d5ef`. The
supported-surface gate remains open; the 131 timeouts and 298 unsupported SBML
records need resolution or explicit governance.

## Package repository metadata — 2026-09-25

Corrected `pyproject.toml`'s repository URL to the current `RuleWorld/BNG3`
repository. The edit is recorded in the convergence checklist. Clean source
distribution/wheel builds and installed-package validation remain outstanding;
no release is qualified by this metadata correction.

## Numeric expression rendering and refreshed gates — 2026-09-25

The strict-rate mismatch in the three-repeat 01564 cross-engine report came
from `Expression::toString()` emitting doubles at the stream's default
precision. A regression first failed on pi rendered as `3.14159`; rendering
now uses `std::numeric_limits<double>::max_digits10`. The focused C++ regression
and all 17 expression CTest cases pass. Rebuilt `bng_cpp` and the Python extension. Modern BNG3/BNG2 network
structure and strict rate comparisons now pass in all six flat/Atomized runs;
modern Atomizer output is repeatable. Legacy PyBioNetGen still cannot generate
the 01564 network. Report
`/private/tmp/bng3-atomizer-cross-engine-01564-precision-fix.json`, SHA-256
`ff25298b20a9778cd90cd1bc44b3ca5c8cf92f1aea05161941e33140d8fd5496`; rebuilt
`bng_cpp` SHA-256
`54095750f38c327bd4e99f05a60a4cbc83aaad6a08cc89184dd29d7533b6c95a`.

The exact-source SBML Test Suite refresh completed at pinned revision
`cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054 unsupported,
zero failed, zero timed out. All 869 supported cases pass XML validation,
Atomizer conversion, network generation, SBML write/reimport, native-reader
checks, and all-observable BNG3 CVODE/libRoadRunner CVODE comparisons. The 954
unsupported semantic cases and 100 stochastic cases remain unsupported, and
reference-result conformance is not run. The report marks its supported-surface
gate passed, but overall core status failed due to the inventory's unsupported
cases. Report
`/private/tmp/bng3-sbml-suite-expression-precision-fix.json`, SHA-256
`0cf26c1efa4760db2327dad4bf64ebd271230550c7ef76041ad3aafb3232f0f8`.

The repeated eight-case cross-engine benchmark now passes modern BNG3/BNG2
structure and strict numeric rates in all 48 flat and Atomized comparisons.
Modern Atomizer output remained stable by model and mode. Legacy PyBioNetGen
had 36/48 structural and 30/48 rate matches; the remaining gaps include its
zero-rate mismatch rows for `00270` and `00308`, plus network-generation errors
for `01564`. Report
`/private/tmp/bng3-atomizer-cross-engine-sbml-suite-8-precision-fix.json`,
SHA-256 `e3316389e6f88a717e466e20d3253b1e782b579f2775bc0e536a37593de3f528`.

The refreshed ten-model curated cross-engine sample has 60/60 structural
modern BNG3/BNG2 matches across flat and Atomized modes. Strict rates match
48/60; the 12 remaining modern rate mismatches remain concentrated in
`BIOMD0000000202` and `BIOMD0000000584`. PyBioNetGen produced 54/60 outputs,
with 21/60 structurally matching networks and 3/60 rate matches. Report
`/private/tmp/bng3-atomizer-cross-engine-curated-10-precision-fix.json`,
SHA-256 `ea04f672f62baaea6f31df3807427e09209053c330f8e37f477ad0f958c787cf`.

Six curated models passed refreshed 200-seed-per-engine NFsim ensembles in
both modes: all 12 ensembles had 200 valid BNG3 direct runs and 200 valid
standalone NFsim runs, with zero mean-comparison violations. The aggregate
`/private/tmp/bng3-atomizer-nfsim-curated-6-precision-fix.json` has SHA-256
`335354192736464793d826b04ff9ddda515684b907e6611242aef2b84cbe686d`. `0202`
had invalid non-integer seed amounts and legacy composite-function errors;
`0584` had standalone `LAMDAR` resolution errors. A current-source `0033`
200-run attempt took over six minutes to produce three native trajectories;
it was interrupted and is not an ensemble result.

The exact-source curated BioModels refresh completed in both modes using the
cached offline inventory, isolated model processes, a 90-second per-model
timeout, and six workers. Across 1,096 inventory records (1,083 SBML), 654
SBML records passed, 298 SBML records were unsupported, 131 timed out, and
zero hard failures occurred. Report
`/private/tmp/bng3-curated-expression-precision-fix.json`, SHA-256
`1f21b340aee754e01f75c4784e4387e1560cf6c4b5b86f6969e3a9edee15abf1`.
Each passed model's round-trip gate includes the BNG3/libRoadRunner observable
simulation comparison. The 298 unsupported records and 131 timeouts remain
open; the full inventory is not release-qualified.

## Dynamic NET rate serialization — 2026-09-25

The new `NetWriter` regression showed that a composite `k * f()` rate, where
`f()` was a model function, was treated as a constant because the classifier
looked only for direct observable names. The unresolved function call then
evaluated as zero in NET output. `NetWriter` now walks the rate AST and keeps
nested model-function references as dynamic functions. The regression failed
before the fix and passes after it; all 20 Expression and NetWriter CTests pass.

The repeated ten-model curated cross-engine benchmark keeps 60/60 modern
BNG3/BNG2 structural matches and 48/60 strict-rate matches. `0202` no longer
serializes the affected rates as zero; expression-form differences remain for
0202 and 0584. Legacy PyBioNetGen has 54/60 generated outputs, 21/60 structural
matches, and 3/60 rate matches. Report
`/private/tmp/bng3-atomizer-cross-engine-curated-10-dynamic-rate-fix.json`,
SHA-256 `3d71dbde754db2396a4ef98e7d2dc64a6768268c00b49ef4a0e9ba0e5174bbfa`;
`bng_cpp` SHA-256
`b43f9733fe979e23ff7c71a340d7f3f0a61d2537a02965c2a475c768edc741a1`.

The full SBML Test Suite was refreshed at revision
`cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054 unsupported,
zero failed, zero timed out. The supported-surface gate passed; overall core
status remains failed, and reference-result conformance is not run. Report
`/private/tmp/bng3-sbml-suite-dynamic-rate-fix.json`, SHA-256
`dba04385da6ff768f4f5c777544c72dfbf1fc345301a92f3707171c0068dbdb3`.

The exact-source full curated BioModels rerun after this writer change was
active when this section was first recorded; its terminal counts are below.

The current-source curated BioModels rerun has now completed. In the 1,096
record inventory (1,083 SBML), 654 SBML records passed, 298 were explicitly
unsupported, 131 timed out, and zero SBML records failed hard; 13 additional
records are non-SBML/unsupported-format entries. This matches the prior
full-corpus counts, so the NET serialization repair fixes the targeted zero
rates without expanding the corpus supported surface. Report
`/private/tmp/bng3-curated-dynamic-rate-fix.json`, SHA-256
`f470fdd1993ced1fc52fc33fb096ae27d45a08d0bacf5235bff9e6c40a42b14e`.
The 298 unsupported cases, 131 timeouts, 1,054 unsupported SBML Test Suite
cases, full platform/package qualification, and release gate remain open.

## SBML semantic support slices — 2026-09-25

Modern Atomizer now uses libSBML to flatten inline `comp` hierarchies before
import. Required package conversion is fail-closed. The initial slice did not
resolve external references; a later source-backed slice now resolves safe
local references and is recorded below. The inline-hierarchy slice moved 47
cases from unsupported to passing.

BNG3 now simulates zero-species models without a zero-length CVODE vector and
evaluates time/parameter-only output functions. Suite cases 00174, 00920, and
00921 pass, as does curated BioModels `BIOMD0000000673`. The parity harness
now compares parameter assignment rules and initial-assignment outputs with
libRoadRunner, not only species observables.

MathML `implies` lowers to BNGL `if`; `arccoth(x)` lowers to `atanh(1/x)` on
the real domain. Targeted former failures 00957, 01274, and 01497 pass. The
full suite now has 1,042 passes, 881 unsupported, zero failures, zero timeouts;
supported-surface gate passes but overall core remains open. Report
`/private/tmp/bng3-sbml-suite-final-slices.json`, SHA-256
`52e03b789a7019497493af2c26414d47dd3088e36506757e7a9ec1d34993bdb2`.
Curated BioModels full refresh completed against the offline manifest, in flat
and Atomized modes with isolated workers, six workers, and a 90-second model
timeout. Of 1,083 SBML records, 657 passed, 293 were unsupported, 2 failed
numerical comparison, and 131 timed out; 13 inventory rows are non-SBML.
Raw report `/private/tmp/bng3-curated-comp-empty-mathml.json`, SHA-256
`a57150abb837bb8018943cb14837bde95a4f9ecb27525a672b8bc4afbce94eca`.
Strict-JSON workbook input (non-finite comparison metrics converted to JSON
`null`) `/private/tmp/bng3-curated-comp-empty-mathml-strict.json`, SHA-256
`4a2fafc68c1e82ffcb5b9ea0042f4da494a25006671acef0d196149c59cbffc5`.
BIOMD0000000731 and BIOMD0000000973 fail on non-finite derived assignment
outputs at the initial time (`log_Treg = ln(0)` and `s = 0/0`, respectively).
Both flat and Atomized routes show the same failure. The workbook refresh is
complete: `bng3_unsupported_model_triage.xlsx` lists all 1,096 BioModels
inventory records and 1,923 suite cases with pass/fail status, per-mode
round-trip evidence, numerical comparisons, exact diagnostics, source links,
input hashes, cause tags, and provenance.

The large remaining gap is semantic: state-triggered event scheduling, DAE
algebraic constraints, and fractional/dynamic reaction stoichiometry have no
faithful general lowering to the current reaction-oriented BNGL runtime. Latest
suite cause tags overlap: events=515; stoichiometry=180, including 132 dynamic
or MathML-defined; algebraic rules=83; FBC=34. FBC remains excluded; the other
groups stay on the implementation checklist.

Latest continuation (2026-09-25): external local SBML `comp` model definitions
now resolve relative to the source file and flatten before Atomizer import;
remote and directory-escaping references fail closed. `rateOf` lowering also
handles undriven mutable parameters/compartments and simple reaction species in
rate-ruled compartments, including concentration dilution. Suite cases
semantic/01249 and semantic/01822 now pass. Atomizer tests pass 257 (1 skipped).
Full suite: 1,054 passed, 869 unsupported, 0 failed, 0 timed out; supported
surface passes, core remains open. Report `/private/tmp/bng3-sbml-suite-rateof.json`,
SHA-256 `6abe9c80631d0809d647ea0461336787347ecb6e277a9cae1316fef37960e871`.
Remaining rateOf examples are explicitly unlowered missing-rule-math and dynamic
stoichiometry cases; both are semantic limits rather than parser crashes.

Algebraic constraints now lower when one otherwise-uncontrolled mutable
parameter is the unique unknown in a linear rule with finite numeric
coefficient. Nonlinear, coupled, species-variable, and multiply-constrained
rules stay unsupported. Nine representative official cases pass, including
MathML `if` and exponent expressions. Full Atomizer Python tests pass 260
(1 skipped), Ruff and `git diff --check` pass. Stable-source full suite reports
1,080 passed, 843 unsupported (0 failed/timeouts); algebraic-rule causes
decrease from 125 to 84. Report
`/private/tmp/bng3-sbml-suite-algebraic-verified.json`, SHA-256
`0ae76dd61447a4bd694ad68a3cb6fa9ebafc8c5297c91d828a1a93172af39dc6`.

Fixed-time event calculations now evaluate time-dependent assignment values at
trigger or execution time per `useValuesFromTriggerTime`, evaluate delays at
trigger time, and fold safe real math functions of known time. Positive
constant-scaled triggers of the form `time / scale > threshold` are lowered;
nonpositive/mutable scales remain unsupported. Official cases 01177, 01528,
01529, 01597, 01598, and 01604 pass. Case 01142 lowers its scheduled action but
remains unsupported for independent SBML `delay` function semantics. Atomizer
tests pass 264 (1 skipped), Ruff and diff checks pass. Full suite: 1,086 passed,
837 unsupported, 0 failed/timeouts; event cause tags now 508. Report
`/private/tmp/bng3-sbml-suite-event-time-final.json`, SHA-256
`ef6dda150f3b8cddf6682b6913eea864bd7b661c85568399a56bd24a5e0ae20c`.

Atomizer now removes `delay(value, duration)` only when `value` cannot change
during the run. Time, dynamic/rule-controlled parameters, algebraic unknowns,
and dynamic species remain explicit. Official suite cases 00941, 00943, and
01174 pass. Atomizer tests pass 265 (1 skipped); Ruff and diff checks pass.
Full suite advances to 1,089 passed, 834 unsupported, 0 failed/timeouts; MathML
cause tags=69. Report `/private/tmp/bng3-sbml-suite-static-delay.json`, SHA-256
`5112cf447c9f156b6e1ecece01cd855ad6d98768f26ce306660aca20dbd60c10`. Curated
BioModels has not yet been rerun against this slice.

Latest continuation (2026-09-25): the unambiguous linear algebraic solver now
also lowers a unique mutable compartment; static species-only event triggers
are evaluated exactly at t=0 with `trigger.initialValue` handling. Newly
passing suite cases: algebraic `00539`, `00540`, `00541`, `00542`, `00544`,
`00545`, `00547`, `00548`, `01785`, `01786`, `01791`; events `00995`,
`01373`-`01376`, `01527`. Atomizer tests pass 267 (1 skipped). Full pinned
suite: 1,106 passed, 817 unsupported, 0 failed/timeouts; event causes=502 and
algebraic-rule causes=73. Supported-surface gate passes; core remains open.
Report `/private/tmp/bng3-sbml-suite-static-events.json`, SHA-256
`8582bd4a35c6a7e42812a35ea22febcc549bc5b4f48f6c32def3d681fc171ae6`.
Dynamic triggers remain unsupported. The curated BioModels rerun begun after
the static-delay slice is still in progress and must be refreshed after these
new Atomizer paths.

Latest suite slice: SBML Level 3 species-reference IDs are treated as
model-level stoichiometry symbols. Literal/static values are promoted for
global formulas and fixed reaction patterns; rate/event-controlled references
remain dynamic. This follows the [SBML Level 3 Version 2 Core specification](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf).
Cases `00974`, `01380`-`01388`, `01395`, `01566`, `01651`-`01656`, and
`01764`-`01768`/`01774` now pass, along with all applicable stochastic
`00001`-`00039` cases. Atomizer tests pass 270 (1 skipped), Ruff and diff
checks pass. Full suite: 1,169 passed, 754 unsupported, 0 failed/timeouts;
stoichiometry causes=132, local-scope causes=1. Report
`/private/tmp/bng3-sbml-suite-static-stoich-ids.json`, SHA-256
`7c09ca58396fb5f99446bfac081d62e86bd379937d6db605d1ff4b1f2eb4e845`.
Supported-surface gate passes; overall core remains open. The full curated
BioModels baseline completed with 657/1,083 SBML records passed, 293
unsupported, 2 failed, and 131 timeouts; report
`/private/tmp/bng3-curated-current-atomizer.json`, SHA-256
`5e44c2695b55747969785485b90b7cf490e9298b9284fb78f34019b9f6bbb73f`.

Remaining stoichiometry triage: 55 semantic records carry a constant-noninteger
stoichiometry cause across 60 reactions. A read-only rational scan finds 47
records with fixed nonnegative values representable using a shared quantum
and scaled coefficients at most 100. This is a candidate set only; ODE
preservation, event/conversion-factor interactions, and SSA jump semantics
still need an exact implementation and libRoadRunner validation. FBC and
other overlapping blockers reduce the possible suite gain.

2026-09-25 continuation: corrected a false positive in reaction-local symbol
scope validation. SBML function-definition lambda formals are function-scoped,
so their bodies are no longer scanned as model-global expressions; global
rules, initial assignments, and event formulas remain checked. A regression
passes for local kinetic parameter `k` passed to a function with formal `k`.
Atomizer test files: 91 passed, 24 skipped; Ruff and diff checks pass.

Focused two-mode revalidation of the 90 curated records formerly blocked by
`local_scope`: 58 passed, 16 remain unsupported for independent event/species
assignment limits, 15 timed out, and 1 failed. `BIOMD0000000174` now passes
the Atomizer/BNG3/SBML roundtrip and libRoadRunner comparison. Report
`/private/tmp/bng3-curated-scope-targeted.json`, SHA-256
`6b7ac2038ed92218ae5d86c2c28a94dc600f8f9fb6b35c453833f1b5c589ef91`.
The first post-scope full rerun was interrupted before summary. A subsequent
full rerun completed; its aggregate is recorded below. The focused cohort is
not the full-inventory rate.

The fixed-time event parser now also recognizes equality crossings
`time == t` and MathML `eq(time, t)` and schedules compile-time-constant
assignments at `t`. Direct tests cover parsing and action output. Curated
`BIOMD0000001043` now passes; its static assignment was triggered by
`eq(time, 20)`. The pinned suite has no newly supported case using this exact
trigger form. The
focused rerun of `semantic/01626` remains unsupported for dynamic
stoichiometry and six state-dependent events; the obsolete `scope` cause is
absent.

Fixed-time event thresholds and constant event-assignment expressions now
inline SBML user-defined functions before numeric folding. An end-to-end
regression covers zero-argument threshold and argument-taking assignment
functions. The current pinned-suite and curated BioModels event-blocker
inventories have no fixed-time assignments calling user-defined functions;
therefore no benchmark count gain is claimed for this slice.
Final Atomizer suite before compartment-event correction: `248 passed, 26 skipped`; Ruff and
`git diff --check` pass.

The full current curated inventory rerun completed: `715/1,083` SBML records
passed, `218` were unsupported, `3` failed, and `147` timed out; `13` non-SBML
records are explicit unsupported formats. Compared with the previous complete
snapshot, 58 former local-scope blockers now pass and `BIOMD0000001043` adds one
pass through equality-trigger lowering. Report
`/private/tmp/bng3-curated-post-scope-equality-functions.json`, SHA-256
`420d7e038407bf4340d1ec11f3105d7c7c59e6c0ced3745473f7abaa5ace8495`.
Every passed model completed the two-mode Atomizer/BNG3 SBML roundtrip and
libRoadRunner comparison. Core remains open.

A final scope audit now treats all `SpeciesReference` IDs as model-global,
while leaving dynamic stoichiometry values unsupported. This removes the last
spurious `local_scope` cause from `semantic/01626`; it remains unsupported for
variable stoichiometry and six state-dependent events. The refreshed full
SBML Test Suite is still `1,169 passed, 754 unsupported, 0 failed, 0 timeouts`;
all other cause counts are unchanged. Report
`/private/tmp/bng3-sbml-suite-post-all-scope-fixes.json`, SHA-256
`9150a27e3b954a4945fe611e3f2019a5c065b0c722ae2fca9ef6faab12086f2b`.

Fixed-time compartment assignments now emit the native BNG3 `setVolume` action
with its structured target/value arguments. An end-to-end generated BNGL run
successfully executes a `setVolume` between two ODE phases. Atomizer regression
suite: `250 passed, 26 skipped`; Ruff and diff checks pass. Curated
`BIOMD0000000338` and `BIOMD0000000339` contain this event shape, but remain
unsupported because each also has state-triggered events. Their targeted
reports are `/private/tmp/bng3-curated-0338-volume-event.json` and
`/private/tmp/bng3-curated-0339-volume-event.json`. Current pinned-suite
inventory contains no fixed-time compartment-assignment events; no suite pass
gain is claimed.

2026-09-25: fixed-time event folding now recognizes SBML's built-in Avogadro
constant at its exact value, while retaining BNG3's normalized `__Avogadro__`
parameter for model expressions. This lowers triggers whose source-unit time is
computed from Avogadro. Atomizer suite: `251 passed, 26 skipped`; Ruff and
`git diff --check` pass. The full pinned SBML Test Suite now reports `1,174`
passed, `749` unsupported, `0` failed, and `0` timed out; five cases newly pass
(`semantic/01658`, `01659`, `01662`, `01663`, `01664`) with no regressions.
Report `/private/tmp/bng3-sbml-suite-post-avogadro.json`, SHA-256
`8640210892d72b05780ce6ed411e0c05d16a9af3216282bcb045e5035128d33b`.
No unsupported curated BioModels event record was found to reference this
built-in constant, so no BioModels count gain is claimed.

Fixed-time conjunctions of constant time bounds now lower at their rising
edge. For delayed nonpersistent events, lowering is allowed only when the
event fires before the trigger window closes; state predicates, empty windows,
and cancellation cases remain explicit. The Atomizer suite passes `253`, with
`26` skips. Pinned-suite cases `semantic/01525` and `01660` newly pass; `01526`
remains unsupported because its nonpersistent delay exceeds its one-unit
trigger window. Full suite: `1,176 passed, 747 unsupported, 0 failed, 0
timeouts`, no regressions. Report `/private/tmp/bng3-sbml-suite-post-time-window.json`,
SHA-256 `f5b3e2d23e1d702c8d9fc790ec89fefa4487763a54e2861eadf1caeed091a770`.

Targeted two-mode BioModels/libRoadRunner validation of 15 unsupported models
with this time-window shape recovered four complete passes: `BIOMD0000000121`,
`0126`, `0943`, and `0976`. Ten still fail only on additional event
semantics; `BIOMD0000000149` exceeded the outer timeout. Per-model reports and
the aggregate are under `/private/tmp/bng3-curated-time-window-cohort/`; summary
`/private/tmp/bng3-curated-time-window-cohort-summary.json`, SHA-256
`05ff17da2ac5831f6a92c20d67035eb2853f46e217feea7e1d469c5d348b7ae2`.
The full curated inventory has not been rerun, so its previous aggregate is
not refreshed by these targeted results.

The recovered-scope cross-engine benchmark was narrowed from 58 models after
its full run exceeded the practical window without producing a report. The
completed smallest-eight sample uses three repeats and both output modes;
report `/private/tmp/bng3-atomizer-cross-engine-scope-sample.json`, SHA-256
`76d5f5393e1c05315e39130ebd3b9d4e33e7611ab9f1a3da0b4bd54adda06ebd`. Modern
Atomizer outputs all built with BNG3 and BNG2 in both modes. Modern structural
parity: flat 24/24 repeats, atomized 21/24; rate parity: flat 21/24 and
atomized 18/24. Legacy flat had structural parity 24/24 but rate parity 0/24;
legacy atomized converted 15/24 repeats and did not produce comparable
networks for the rest. This is cross-engine network evidence; the separate
full suite and targeted BioModels gates provide libRoadRunner comparisons.

The event constant folder now handles chained SBML relational comparisons and
short-circuits `and`/`or` when one operand proves the result. This marks a
provably false event as informational instead of a dropped feature. It
recovers `semantic/01211`; the full suite is now `1,177 passed, 746
unsupported, 0 failed, 0 timeouts`, with no regressions. Event causes fell to
490. Atomizer tests: `255 passed, 26 skipped`; Ruff and diff checks pass.
Report `/private/tmp/bng3-sbml-suite-post-static-window-logic.json`, SHA-256
`15a01a0e033aceec0b5dcc56f37239bc202b30fa20b3ab4dcecf267beab6e515`.

The simple algebraic-rule solver now also selects one mutable, non-boundary
species when it is not a reaction participant or event target. Its linear
constraint becomes a species assignment rule and is emitted as a derived
function; constraints involving mutable reaction species still fail closed.
The full suite newly passes 31 cases (no regressions): `1,208 passed, 715
unsupported, 0 failed, 0 timeouts`. Algebraic-rule causes fell from 73 to 34;
constraint-tagged records fell from 106 to 67. Atomizer tests: `256 passed,
26 skipped`; Ruff and diff checks pass. Report
`/private/tmp/bng3-sbml-suite-post-algebraic-species.json`, SHA-256
`9b0e847576431ca336a2d0d67d6393773133665d74a614c224afc3b28acf0ba7`.
The unsupported curated inventory has no algebraic-rule cause, so no curated
pass gain is claimed for this change.

Fixed finite fractional stoichiometry now lowers to deterministic per-species
signed `TotalRate` source/sink rules. Import notes state stochastic shared-event
coupling is not retained; dynamic stoichiometry, fast reactions, FBC, and
executable Multi remain rejected. The full SBML Test Suite gains 19 passes
with no regressions: `1,227 passed, 696 unsupported, 0 failed, 0 timeouts`.
New pass IDs are recorded in the convergence checklist. Three formerly blocked
curated models (`BIOMD0000000039`, `0059`, `0206`) pass flat and Atomized
round-trips and all-observable BNG3/libRoadRunner comparisons. Reports live in
`/private/tmp/`; exact suite digest and paths are in the checklist.
Irreversible fractional rules now use one direction-specific TotalRate rule per
affected species; reversible laws retain signed-flux splitting. Optimized
three-repeat BNG3/BNG2 comparison has 18/18 structure matches and 6/18 strict
rate-string matches (up from 0/18). PyBioNetGen flat output matched structure
6/6, rates 0/6; atomized output failed conversion. Independent libRoadRunner
ODE comparisons still pass for all three selected models. This is deterministic
support only; NFsim shared-event parity is not claimed.

Full curated inventory run before this compacting change: 730/1,083 SBML
records passed, 192 unsupported, 4 failed, 157 timed out, with all 1,096
inventory entries accounted for. Nine models with a stoichiometry-only blocker
newly pass; total passes rose by 78 versus prior full report, including gains
from scope/event changes in the worktree. Failures: worker signal -11 on
BIOMD0000000081 (targeted rerun timed out at 180 s), CVODE failure on 0606, and
new all-observable non-finite parameter comparisons on 0731/0973. Compacting
did not change full suite counts. Full curated inventory after compaction
remains open. Exact report paths/digests are in the checklist.

Focused Atomizer/parity/event and curated gate checks: `129 passed`; Ruff and
whitespace checks pass. Full Python suite has one unrelated BNGIR
float-serialization assertion failure (`0.1` vs `0.10000000000000001`);
`515` other tests pass and `28` skip. Full curated inventory rerun after
compacting remains open.

Fixed-time event scheduling now treats `constant="false"` parameters and
compartments as constant only when no rule, initial assignment, or event targets
them. Regression covers both safe folding and retained diagnostics for a
controlled value. Atomizer, event, and SBML parity checks pass (`128 passed`);
Ruff and whitespace checks pass. The active full curated BioModels run began
before this change, so its results will not measure the new behavior.

The full compact-fractional curated refresh completed with all 1,096 inventory
records accounted for: 731/1,083 SBML pass, 191 unsupported, 3 failed, and 158
timed out. Relative to the pre-compaction report, BIOMD0000000040 moved from
unsupported to pass; BIOMD0000000081 moved from failed to timeout. This run
started before the uncontrolled-mutable-symbol event edit. Remaining failures:
libRoadRunner CVODE failure on BIOMD0000000606, and non-finite all-observable
comparisons for `log_Treg` in BIOMD0000000731 and `s` in BIOMD0000000973. Exact
report digest and boundaries are in the convergence checklist.

Reaction-participating algebraic assignment targets now become BNGL functions;
their reaction state patterns are removed while their values remain in kinetic
laws. Deterministic semantics are explicitly bounded from NFsim-style stochastic
trajectories. Thirty-seven selected previously blocked BioModels pass flat and
Atomized paths and all-observable BNG3/libRoadRunner comparisons. Report index
and digest are in the convergence checklist. Focused checks: 131 pass. Full
curated and SBML Test Suite refreshes remain in progress.

Fixed integer stoichiometry above 100 now lowers to deterministic per-species
TotalRate rules; high dynamic stoichiometry remains rejected. The curated
prefilter delegates fixed values to Atomizer. Flat-mode all-observable
libRoadRunner comparisons pass for BIOMD0000000463 and BIOMD0000000608; both
mode selected runs timed out at 90 seconds. Exact report digests and this
validation boundary are in the convergence checklist.

The final-code pinned SBML Test Suite refresh passes `1,282/1,923` cases, with
641 unsupported, zero failed, and zero timed out. This is 55 more passes than
the prior exact-source run and has no regressions; every gain is a stochastic
case with an event proven never to fire. The gate checks BNG3 CVODE/libRoadRunner
parity, not official SBML Test Suite reference-trajectory conformance. Report
`/private/tmp/bng3-sbml-suite-final-code.json`, SHA-256
`f4df13b873836a4931edb117aec238938fa1227aec6a0e624697148010470b84`.

The final-code curated BioModels inventory accounts for all 1,096 entries:
`774/1,083` SBML pass, `134` unsupported, `5` fail, and `170` time out. Versus
the prior assignment-species full report, passes rise by 2, unsupported fall
by 4, failures fall by 2, and timeouts rise by 4. Rate-rule mapping recovers
BIOMD0000000245; fixed large stoichiometry recovers BIOMD0000000353 in both
modes with all-observable BNG3/libRoadRunner parity. BIOMD0000000463 times out
in the full both-mode scan despite its targeted flat-mode pass. Report
`/private/tmp/bng3-curated-atomizer-final-code-full.json`, SHA-256
`aa1fcaebd8b69beeb4c3274d6e3813f9b3e98d1d787dcc0bdcb71f4771b209ad`.

The three-model cross-engine slice covers BIOMD0000000307, 0384, and 0503 in
flat and Atomized modes with three repeats. Modern BNG3 output is deterministic
in all 18 samples; BNG3 and BNG2 generate all networks and have 18/18 structural
parity. Strict rate-string parity is 0/18, so this does not imply exact
serializer agreement. PyBioNetGen emits output in 9/18 samples; the other nine
fail in legacy code, including an undefined `longEnough` error, and its outputs
do not produce comparable networks. Report
`/private/tmp/bng3-atomizer-assignment-cross-engine.json`, SHA-256
`86d75a81691c85cbcaa22698e0bea00d57a6cad5381ee244d5e984f716c3ae7d`.

Dynamic SBML species-reference coefficients now lower into deterministic
species-specific `TotalRate` ODE rules. This handles rate-rule/MathML values
without expanding dynamic stoichiometry into BNGL patterns and also replaces
dynamic reference symbols inside kinetic laws. Fast, Multi, FBC, unresolvable
expressions, and shared stochastic event semantics remain explicit boundaries.
The full SBML Test Suite gains 43 cases with zero regressions: `1,325 passed,
598 unsupported, 0 failed, 0 timeouts`. Remaining stoichiometry causes are six
negative coefficients and ten dynamic cases overlapping state-dependent events
or fast reactions. Report `/private/tmp/bng3-sbml-suite-dynamic-stoichiometry.json`,
SHA-256 `770c8a46b81a4ab2e0eeb54bdd184e903f1babc851de158004cd4e057fa31190`.
Focused Atomizer tests pass (`131 passed`). Full Python suite: `519 passed,
28 skipped`, with one unrelated BNGIR float-serialization assertion failure
(`0.1` vs `0.10000000000000001`). Ruff and `git diff --check` pass. The curated
BioModels inventory needs a refreshed check against this latest writer
revision. The three-model dynamic-stoichiometry BNG2/PyBioNetGen comparison is
complete; report details are in the convergence checklist.

Reaction-derived `rateOf(species)` now supports finite dynamic stoichiometry
when reference value has an assignment/rate rule, initial assignment, or
MathML expression; event-controlled references remain fail-closed. Fixed
fractional coefficients are supported for deterministic ODE derivatives.
`delay(expression, 0)` now simplifies exactly; nonzero history-dependent delay
remains unsupported. SBML Test Suite is `1,326 passed, 597 unsupported, 0
failed, 0 timed out`; `semantic/01543` newly passes with four all-observable
BNG3/libRoadRunner comparisons. Three-repeat BNG2 parity matches structure
`6/6`, but strict rate-string parity is `0/6` due algebraically equivalent
directional expressions. PyBioNetGen fails to produce output for this model.
The full curated BioModels refresh completed: `774/1,083` SBML pass, `134`
unsupported, `5` fail, `170` timeout, all 1,096 inventory records accounted.
No model status changed versus the prior full-code run, so this `rateOf` gain is
SBML Test Suite-only. Report digest is in `docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md`.

Closed-form time-dependent assignment rules now lower safely inside SBML
`delay`: inline only assignment chains using time and immutable symbols, then
substitute `time - delay`. General history remains unsupported. The full SBML
Test Suite rises to `1,331 passed, 592 unsupported, 0 failed, 0 timed out`,
with five new passes and no regressions: `00937`, `01173`, `01176`, `01318`,
`01319`. `00937` matches libRoadRunner exactly. Modern output is deterministic
across three repeats in flat/Atomized modes; BNG2 has no reaction network to
compare and legacy PyBioNetGen fails dependency resolution. Targeted checks of
all seven cached curated models containing delay found no new pass. Exact
reports and boundaries are in the convergence checklist.

Atomizer now lowers fixed, nonnegative delays of scalar affine histories from
rate rules or reaction fluxes, including `rateOf` expressions and fixed
conversion factors. Static species-reference values fold before delay lowering.
The pinned SBML Test Suite reaches `1,349 passed, 574 unsupported, 0 failed,
0 timed out`, with 18 new passes and no regressions; ten representative
cases pass direct BNG3/libRoadRunner comparisons (maximum absolute error
`1.45e-6`). Seven cached curated BioModels containing delay math remain
unsupported because they need general history or event execution; a full
curated inventory refresh accounted for all 1,096 records (`774/1,083` SBML
pass, `134` unsupported, `5` failed, `170` timeouts), with no model-status
change from the preceding full-code report. A second safe delay slice now
supports nonnegative affine time lengths (`time/2`, including assignment and
algebraic aliases): `1,352 passed, 571 unsupported, 0 failed, 0 timed out`,
three new passes since the affine-history report, no regressions. `00981–00983`
match libRoadRunner to `3.6e-15`; the seven cached curated delay models remain
blocked by general history/events. Modern Atomizer tests: `291 passed,
1 skipped`; Ruff, compileall, and diff checks pass. Linear algebraic rules can
also define an unreacted boundary species: `semantic/00554` is newly supported
and matches libRoadRunner on seven observables (max absolute error
`6.93e-12`). Full SBML suite now reports `1,353 passed, 570 unsupported, 0
failed, 0 timed out`, one gain and no regressions. Modern Atomizer tests are
`292 passed, 1 skipped`.
See `docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md` for report paths and boundaries.

SBML events with `trigger initialValue=false` now schedule an exact t=0 rising
edge when their initial trigger evaluates true. This is restricted to immediate
events and excludes rule- or initial-assignment-controlled variables. The full
suite rose to `1,366 passed, 557 unsupported, 0 failed, 0 timed out`, with 13
new passes and no regressions. Three new cases (`01684`-`01686`) also passed
four-observable BNG3/libRoadRunner comparisons each (maximum absolute error
`6.94e-18`). `01332` roundtrips but has no observables, so its simulation
comparison is vacuous. Modern Atomizer tests: `293 passed, 1 skipped`; Ruff,
compileall, and diff checks pass. Curated BioModels refresh remains pending.
See `docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md` for the exact report digest.

Event translation now also solves direct thresholds of single parameters with
constant rate rules, with fail-closed guards for mutable/coupled trajectories.
MathML constant folding covers SBML n-ary arithmetic and inverse trig/hyperbolic
functions used by scheduled delays. `semantic/01530`, `01532`, and `01533` now
pass; the 53 events in `01532` match libRoadRunner's one observable within
`1.8e-15`. Full SBML suite is `1,369 passed, 554 unsupported, 0 failed, 0
timed out`, with no regressions. Modern Atomizer: `295 passed, 1 skipped`.
Cached-source triage covered 1,084 BioModels XML files (nine parse failures):
no direct affine-rate trigger candidates. Only one non-time initialValue=false
case was found; `BIOMD0000000825` starts with its trigger false and remains
unsupported because execution requires later state-event scheduling. No
curated gain is claimed; the redundant full scan was stopped after this
targeted audit. See the convergence checklist for the targeted run report.

The full Python suite now passes: `532 passed, 28 skipped`. This also fixes
the existing BNGIR float formatting regression (`0.10000000000000001` now
serializes as shortest round-tripping `0.1`). Ruff, compileall, and diff checks
pass. The prior complete curated baseline remains `774/1,083` SBML pass,
`134` unsupported, `5` failed, `170` timed out; this event slice has no newly
supported curated model.

Periodic reset events (`time - reset >= interval`, `reset := time`) now expand
to repeated exact actions using prior scheduled parameter values. Parameter-
only triggers proven false through those updates are marked never-firing; other
dynamic triggers stay fail-closed. The full SBML suite is `1,373 passed, 550
unsupported, 0 failed, 0 timed out`, with four new passes and no regressions:
`00952`, `00953`, `00963`, and `00964`. The three nonempty observable
comparisons match libRoadRunner exactly. Modern Atomizer: `298 passed,
1 skipped`. No matching periodic-reset pattern appeared in the cached curated
BioModels source scan. Detailed evidence is in the convergence checklist.

Constant-rate reset, delayed periodic events, bounded delayed assignment
history, and constant initial-assignment folding now pass eight additional
official SBML cases: `00962`, `01588`-`01593`, and `01599`. The full pinned suite
is `1,381 passed, 542 unsupported, 0 failed, 0 timed out`, with zero
regressions; event-related unsupported records fell to 401. Cases `01588` and
`01590`-`01593` match libRoadRunner on all generated observables (maximum
absolute difference `0`). The suite runners now pass simulation horizon and
step count into Atomizer for source and reimport conversion. Full Python suite:
`537 passed, 28 skipped`; Modern Atomizer: `303 passed, 1 skipped`.
Full offline BioModels inventory: `773 passed, 134 unsupported, 5 failed, 171
timed out` among 1,083 SBML records. No feature-related curated gain; one
previously passing model (`BIOMD0000000637`) timed out in the full run but
passed an isolated both-mode recheck, consistent with runtime variance.

Horizon-bounded SBML delay history now folds to exact initial values across
rules, reaction rates, events, function expressions, and time-varying
stoichiometry when the delay is fixed and at least as long as the simulation.
This added seven official cases (`01410`-`01412`, `01419`, `01480`-`01481`,
`01535`), with no regressions. Static event triggers on unchanging species
added `00699` and `00701`. The full SBML suite now reports `1,390 passed, 533
unsupported, 0 failed, 0 timed out`, with no regressions. Targeted curated
roundtrip plus BNG3/libRoadRunner checks also pass for BioModels `0025`, `0154`,
and `0034`. Mutable delay lengths and later-state event/history semantics
remain unsupported. Full Python: `544 passed, 28 skipped`; Modern Atomizer:
`310 passed, 1 skipped`. See the convergence checklist for report digests and
case details.

The Atomizer now lowers single-unknown linear algebraic rules whose
coefficients fold from immutable SBML symbols. Twenty-nine more official
cases pass with no regressions; `00531` matches libRoadRunner over seven
observables to `2.23e-16`. Static species-trigger handling adds two further
passes. The full SBML suite is now `1,419 passed, 504 unsupported, 0 failed,
0 timed out`; 399 event blockers remain, alongside the explicitly unsupported
FBC/flux-balance models and other dynamic semantics. Full Python: `546 passed,
28 skipped`; modern Atomizer: `312 passed, 1 skipped`. Detailed per-case data
and digest are in the convergence checklist.

The Atomizer now also schedules exact crossings for species with constant net
reaction flux. Delayed assignments read the trigger-time or execution-time
species value according to SBML semantics, when the affine trajectory is
provable. This adds 12 SBML Test Suite passes with no regressions: the pinned
suite is `1,431 passed, 492 unsupported, 0 failed, 0 timed out`. Full Python:
`548 passed, 28 skipped`; modern Atomizer: `314 passed, 1 skipped`. Ruff,
compileall, and diff checks pass. The full curated BioModels refresh predates
this slice and is still running. See the convergence checklist for the exact
report digest and case list.

The full offline curated BioModels refresh completed with `781 passed, 127
unsupported, 5 failed, 170 timed out` among 1,083 SBML records. Six unsupported
records passed versus the prior full run; two timeouts recovered, one
unsupported record timed out, and no prior pass regressed. Those three status
changes are run-to-run variance. This refresh predates constant-flux event
lowering; a cached-source scan found no curated model matching that new shape,
so no curated gain is attributed to it. Exact IDs and the report digest are in
the convergence checklist.

Event scheduling now also handles exact first-order exponential trajectories
whose reaction rates are provably linear in one species with immutable
coefficients. It adds 37 official SBML cases with no regressions; the full
suite is `1,468 passed, 455 unsupported, 0 failed, 0 timed out`. Full Python:
`550 passed, 28 skipped`; modern Atomizer: `316 passed, 1 skipped`. A cached
scan of 1,084 curated BioModels found no matching event shape. See the
convergence checklist for the exact case list and report digest. For
`semantic/00619`, generated-model CVODE matches libRoadRunner across five
observables to `1.69e-13` maximum absolute difference.

Affine delayed history now lowers through an exact initial-history branch and
shifted trajectory for fixed delays. Three more official cases pass with no
regressions: `1,471 passed, 452 unsupported, 0 failed, 0 timed out`. For
`00938`, `00940`, and `00942`, generated-model CVODE matches libRoadRunner on
all three observables per model (maximum absolute error `4.44e-16`). Full
Python: `551 passed, 28 skipped`; modern Atomizer: `317 passed, 1 skipped`.
See the checklist for the report digest and scope limits.

SBML event translation now resolves assignments and delays that read exact
affine or exponential state trajectories, and lowers simple parameter
rate-rule thresholds including `rateOf`-style scaled expressions. Five more
official cases pass without regressions: `1,476 passed, 447 unsupported, 0
failed, 0 timed out`. Five 10-time-unit generated-model comparisons match
libRoadRunner within `4.06e-12` maximum absolute error. Full Python: `554
passed, 28 skipped`. Full BioModels was not rerun; the cached `rateOf` source
screen found no model matching the new simple parameter threshold form. See
the convergence checklist for report digest and detailed scope.

Event lowering now handles a single conjunction defining a bounded interval
over one proven affine state, including delayed trigger-time snapshots,
nonpersistent cancellation, and static model/species conversion factors.
Thirteen additional official SBML cases pass with no regressions: `01580`-
`01582`, `01675`-
`01680`, `01687`-
`01688`, and `01690`-
`01691`. The full pinned suite is `1,489 passed, 434 unsupported, 0 failed,
0 timed out`; event blockers fell from 345 to 332. All 13 new cases match
libRoadRunner on generated observables (maximum absolute difference
`1.78e-15`). Full Python: `556 passed, 28 skipped`; Ruff, compileall, and diff
checks pass. Curated BioModels was not rerun. See the convergence checklist
for report digest, exact scope, and validation limits.

The full offline curated BioModels roundtrip was then rerun in both flat and
atomized modes against the same 1,096-record inventory. Statuses were
identical to the prior full refresh: 781/1,083 SBML records passed, 127 were
unsupported, 5 failed, and 170 timed out; 13 non-SBML records remain explicit
inventory exclusions. No curated gain or regression is attributable to this
slice. All 1,562 passing per-mode comparisons and 260 nonpassing comparison
statuses are unchanged. Report digest and comparison details are recorded in
the convergence checklist.

Single-event models with no reactions, rules, or initial assignments can now
prove a direct state threshold static from its initial value. Permanently
false triggers are omitted; a true-at-zero trigger with
`initialValue=false` schedules its one initial edge, including fixed delay.
Official `semantic/01335` now passes. Full SBML suite: `1,490 passed, 433
unsupported, 0 failed, 0 timed out`, one gain and no regressions; event
blockers fell to 331. Full Python: `558 passed, 28 skipped`; Ruff, compileall,
and diff checks pass. The case has no observables, so its libRoadRunner
simulation comparison is vacuous. Rate-rule-driven parameters and models with
other dynamics remain outside this proof. The full curated BioModels refresh
predates this slice. See the checklist for the report digest and scope.

Event-value folding now evaluates constant SBML `piecewise` branches and
n-ary chained equality/inequality predicates. A nonpersistent event whose
fixed delay places execution at or after its proven time-window end is safely
omitted as canceled. Five more official cases pass with no regressions:
`01212`, `01213`, `01214`, `01526`, and `01661`. The full suite is `1,495
passed, 428 unsupported, 0 failed, 0 timed out`; event blockers fell from 331
to 326. Full Python: `560 passed, 28 skipped`; Ruff, compileall, and diff
checks pass. All five new cases have no observables, so their libRoadRunner
simulation comparisons are vacuous. A cached BioModels source scan found no
matching piecewise event or nonpersistent time-window cancellation shape; the
full curated report predates this slice. See the convergence checklist.

The Atomizer now lowers repeated delayed or immediate events that reset a
single exponentially evolving parameter/species to a fixed value on the false
side of its threshold. It computes each rising edge and recurrence from the
proven exponential trajectory; coupled events, mutable coefficients, and
unsafe assignments stay unsupported. The full one-unit SBML suite gained
`semantic/00684` with no regressions: `1,496 passed, 427 unsupported, 0
failed, 0 timed out`, and event blockers fell to 325. At a 10-unit/100-step
horizon, `00026`, `00071`, `00073`, `00074`, and `00172` also pass targeted
roundtrip and BNG3/libRoadRunner comparison (maximum absolute error
`1.88e-14`). Full Python: `561 passed, 28 skipped`; Ruff, compileall, and diff
checks pass. A cached scan of 1,084 BioModels XML files found no matching
single-state exponential self-reset event; the prior full curated result
remains the current inventory evidence. See the checklist for the exact
report digest and limits.
