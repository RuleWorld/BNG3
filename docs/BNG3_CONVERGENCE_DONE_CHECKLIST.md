# BNG3 Convergence: Definition of Done and Remaining Checklist

**Status:** Active; not complete
**Last targeted audit:** 2026-09-25 (full convergence checklist remains open)
**Repository:** RuleWorld/BNG3
**Working branch:** `main`
**Current base:** `main` at PR #24 merge `a5f65ae05e26926b013f4ec3305dab34a3e9c84f`; working tree also contains targeted SymbolTable, BNGIR schema, and Atomizer writer fixes
**Historical audited heads:** Earlier local-only and hosted heads remain
recorded in the historical sections below; they are not current-head evidence.
**Independent implementation reference:** RuleWorld/bngplayground Atomizer
**Energy-evaluator source reference:** akutuva21/nfsim PR #475, merged at
6690fda5d9e053df822d0248ebae185f5caca82a; accepted energy-source cutoff
3b046fc1b9f76719d92be22279b24992cdae7c35. The public
`akutuva21/nfsim` fork currently has master at
`c51c7a34128d188189485bd318aeae4d936bcb29` (observed 2026-09-01); later
non-energy PRs #476 and #477 are deliberately not silently included in the
BNG3 port.

## Scoped source-lock refresh — 2026-09-23

The live RuleWorld BioNetGen, NFsim, and PyBioNetGen heads were refreshed and
their 35 commits since the previously recorded source revisions were
classified in [`UPSTREAM_RECONCILIATION_2026-09-23.md`](UPSTREAM_RECONCILIATION_2026-09-23.md)
and `provenance/reconciliation/`. This does not re-audit the full checklist,
approve the observed source cutoffs, or change any convergence item to
complete. No test suites were run for this scoped source update; historical
evidence below retains its original date and scope.

This is the execution checklist for the BNG3 convergence goal. It turns the
completion charter and Section 11 of BNG3_INTEGRATION_PLAN.md into auditable
work items. The unification work orders in docs/BNG3_unification_spec.md remain the
detailed dependency map; provenance/capability-matrix.yml remains the
capability inventory.

## Historical audit — 2026-09-10

The active worktree is on `codex/bng3-rest-of-port-20260909` at committed base
`a8d2a8b`, with a consolidated uncommitted implementation batch. The live
summary is [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md). The batch includes
NFnext semantic/runtime contracts, lazy paged NFsim mapping storage, and the
reconciled modern SBML-Multi parser. The final combined-tree verification for
this pass passed: build, CTest 305/305, Python 353 passed with 27 skips, and
validation smoke 4 passed with 14 environment/reference skips. These results
are recorded as branch evidence, but they do not by themselves close the
remaining convergence checklist items.

The pre-existing unresolved or unvalidated worktree changes were preserved;
the only conflict encountered, in `python/bionetgen/atomizer/modern/multi.py`,
was resolved in favor of the newer spec-aware implementation and marked
resolved. Ruff, Black, and `git diff --check` also pass for the final worktree
state; the mandatory semantic convergence gates remain open until
independently evidenced.

The project is done only when every mandatory item below is checked or has an
explicitly approved compatibility disposition. A green unit suite, a green
PR, a partial port, a documented limitation, or a known mismatch is not
completion.

## How to use this checklist

- Use [x] only when current evidence is attached by path, command output,
  artifact digest, hosted check, or maintainer decision.
- Use [ ] for work that is absent, partial, unverified, or awaiting approval.
- Treat a compatibility disposition as valid only when it has an owner,
  rationale, affected interfaces, migration path, release-note entry, contract
  test, and review/expiry date.
- Add the source revision, BNG3 commit, test/fixture, oracle, and gate to every
  completed semantic item.
- Never widen tolerances, broaden skips, regenerate goldens silently, or change
  the exception ledger merely to make this file easier to check.
- Re-audit the whole checklist on the exact release-candidate SHA. Earlier
  evidence is stale after a rebase, autofix, merge, or semantic change.

## Physical units / dimensional-analysis checkpoint — 2026-09-15

The BNG3-native units work is documented in [`BNG3_UNITS.md`](BNG3_UNITS.md).
It uses explicit bracket annotations and a normalized `begin units` metadata
block, while preserving ordinary BNGL identifiers and the legacy
`substanceUnits`/`NumberPerQuantityUnit` compatibility fields.

- [x] Unit algebra and explicit mole/item bridge are covered by
  `tests/cpp/test_units` (41 assertions, 7 cases), including metric conversion,
  concentration-to-item conversion and context-dependent second-order rate
  conversion.
- [x] Parser collision behavior, dependency inference, strict dimensional
  diagnostics and backend capability fail-closed behavior are covered by
  `tests/cpp/test_parser_units` (42 assertions, 6 cases).
- [x] Native seed/rate lowering and shared SBML Core/SBML-Multi writer mapping
  are covered by `tests/cpp/test_sbml_units` (33 assertions, 5 cases); the Multi
  writer reuses Core unit definitions and emits no `multi:units` system.
- [x] SBML Core unit-definition/default/object metadata extraction is covered by
  `tests/cpp/test_sbml_reader` (21 assertions, 3 cases), and the executable
  action path imports that metadata before reconstruction.
- [x] Python model/binding/snapshot smoke coverage confirms unit metadata is
  exposed and unit-free snapshots retain their legacy shape.
- [ ] Validate emitted Core and Multi documents with libSBML/schema and
  independent SBML semantic oracles across Level 2 and Level 3 package modes.
- [ ] Complete cross-backend parity for direct NFsim. BNG3 currently rejects
  unit-bearing models at that adapter boundary until its count-rate bridge is
  independently validated.
- [ ] Re-run the complete release/hosted convergence matrix on the final PR
  head; focused green tests are not release convergence evidence.

## Current continuation checkpoint — 2026-09-15

The continuation from the current public `main` base is deliberately narrow
and evidence-oriented:

- [x] Direct NFsim evidence records `construction_path`, requires the XML leg
  to report `in-memory-xml` and the direct leg to report `direct`, clears XML
  fallback permission before the direct leg, and keeps missing compiled
  backends/oracles fail-closed.
- [x] Spawned source-tree validation workers receive both the repository root
  and `python/` on `sys.path`, so the independent NFsim ensemble does not
  depend on the caller's import context.
- [x] Hosted independent NFsim parity includes the fixed-seed `motor` and
  `tlbr` endpoint contracts in addition to the seeded `simple_system` ensemble;
  every ensemble member must report direct construction.
- [x] The typed Lean example and production C++ NFIR contract use the same
  rule, `A(x~u) + B(y) -> A(x~p!1).B(y!1) k`. The C++ contract crosses
  BNGL parser -> `bng::compile::CompiledModel` ->
  `nfnext::lowerFromBioNetGen` and checks distinct-reactant molecularity, a
  state update, and a new bond.
- [x] Population maps remain fail-closed for direct NFsim and route through
  the hybrid population backend; no unsupported direct semantics are inferred.

The exact local evidence for the code head immediately before this
documentation merge is: CTest `312/312`; strict full validation `71/71` with
zero failures, errors, or skips; action contracts `6/6`; CI-contract tests
`26 passed`; energy tests `66 passed`; independent NFsim `10 passed`; Lean
static validation `36` files; NFnext contracts `18/18`; Black, Ruff,
provenance, corpus, and exception-ledger checks passed. The local Lean kernel
check remains unavailable because Lean/Lake/Elan are not installed.

This branch remains unpushed. `gh` readback keeps `origin/main` at
`2af9506a1124ce7ebdc30c6967c771f1cd91c63c`; the current main CI run
[`35004180160`](https://github.com/RuleWorld/BNG3/actions/runs/35004180160) was
queued at final inspection. No hosted result is attributed to local head
`c491f9bcc50301af635ad0203b43a69088b68d6d`.
The unchecked completion items below remain open.

## Material migration-gap batch — 2026-09-15

The isolated batch on `codex/bng3-material-gap-completion` adds bounded,
source-derived completion evidence for all five requested workstreams. The
full checklist remains active because the batch does not replace maintainer
approval, cross-platform CI, or broad Tier-NF/Tier-X qualification.

- [x] Direct NFsim acceptance records `construction_path`, clears XML fallback
  for the direct leg, and runs selected native-oracle checks. Exact local
  evidence: CTest `312/312` and `10 passed` in the selected direct/native
  NFsim validation command, plus `2 passed` direct-NF protocol contracts.
- [x] Structured SBML admission is identified by species/parameter/rule/
  reaction semantics rather than incidental `plain2` and `S1`-`S5` IDs. The
  reader now rejects fractional, zero, negative, nonfinite, and overflowing
  stoichiometry instead of silently rounding. The native SBML fixture bank
  reports `22 assertions` in four cases.
- [x] The graph-aware NET comparator normalizes equivalent arithmetic spelling
  only inside a supported AST subset; unsupported rate syntax remains
  fail-closed. The focused comparator gate reports `12 passed`.
- [x] Independent scientific validation runs the BNG2 structural oracle over
  nine selected representative models with `9/9` pass. This is selected
  differential evidence, not complete Tier-P corpus approval.
- [x] The CPU energy slice preserves both equivalent reaction centers for a
  symmetric Arrhenius binding rule. Its source-derived direct test passes, the
  independent `constant_binding` energy gate passes for `1024` seeds, and the
  fresh-process direct/XML benchmark records five repeats per route. The
  benchmark is measurement-only; no speedup or memory claim is made.
- [x] PyBioNetGen compatibility now supports the bounded method/time override
  contract through the modern simulator and materializes a legacy `.gdat`.
  Source-derived compatibility tests report `5 passed`; an isolated CPython
  3.14 arm64 wheel install runs both modern and legacy contracts.
- [ ] Symmetric-site independent statistical energy parity remains open and is
  explicitly retained as a limitation: the legacy BNG2/NFsim XML expansion
  has a known energy-pattern lookup mismatch on that fixture. The BNG3 direct
  path preserves multiplicity and does not convert this mismatch into a green
  parity claim.
- [ ] Remaining protocol NF/t4/t5 behavior, full CPU evaluator parity, full
  SBML/Atomizer/writer round trips, complete PyBioNetGen public-contract
  qualification, approved provenance, cross-platform wheel CI, and release
  artifacts remain open.

The complete machine-readable run is retained as
`material_gap_evidence.json` in the task output directory. It records exact
BNG3, BNG2, NFsim, and PyBioNetGen revisions, oracle paths, commands, and
bounded output tails.

## SBML semantic-gate correction — 2026-09-16

- [x] The SBML Test Suite and curated BioModels numerical gates now treat
  semantic `approximated` warnings as unsupported, while retaining
  informational unit-scale notes as non-blocking. This closes the validator
  integrity gap where variable stoichiometry, fast reactions, lossy MathML,
  or partial Multi semantics could otherwise be reported as numerical passes.
  The focused report-contract tests pass `6/6`; full local gates pass CTest
  `315/315`, Python `420 passed, 28 skipped`, and validation
  `84 passed, 117 skipped`.
- [x] The C++ SBML writer/native reader canonicalize BNGL inverse-trigonometric
  names to the SBML `arcsin`/`arccos`/`arctan` family and hyperbolic variants;
  the focused regression passes and the fresh suite moved from `670/1,253`
  passed/unsupported to `673/1,250`.
- [x] Fixed-time, constant-valued SBML events are classified as lowered after
  the generated action phase is present; only untranslated events remain a
  dropped semantic warning. Focused event/lowering and warning-merge tests
  pass `3/3`.
- [x] The post-change full SBML Test Suite report is
  `/private/tmp/bng3-sbml-suite-post-factorial.json` (schema 3): `1,923` cases,
  `687` passed, `1,235` explicitly unsupported, `1` failed, and `0` timed out.
- [x] The post-gate flat curated BioModels report is
  `/private/tmp/bng3-curated-biomodels-flat-final-audited.json` (schema 4):
  `1,096` records, `591` passed, `459` SBML records explicitly unsupported,
  `31` failed, `2` timed out, plus `11` non-SBML records.
- [x] The reports retain exact unsupported IDs/reasons, non-exclusive cause
  intersections, and stoichiometry subcauses: suite `188` dynamic/
  `stoichiometryMath`, `23` constant noninteger, `6` constant negative;
  curated SBML-only `52` constant noninteger, `2` dynamic/
  `stoichiometryMath`, `1` integer above expansion limit.
- [x] Cause-set projection is recorded as an upper bound: resolving events,
  MathML, local scope, species assignment, and constraints touches `836` suite
  records (`455` target-only) and `399` curated SBML records (`378`
  target-only); it is not a predicted pass count.
- [x] The follow-up Core MathML batch adds exact non-negative-integer factorial
  execution across the evaluator, typed compiler/lowering, BNGL visitor,
  C++ SBML writer/native reader, and validator diagnostics. Targeted
  `semantic/00028` and `semantic/00269` pass the full selected round-trip and
  BNG3-vs-libRoadRunner gate; `semantic/00173` remains failed at its
  discontinuous rate-rule CVODE comparison and is not relabeled as supported.
- [x] The follow-up MathML batch removes the false unspecified-rational warning
  from valid `e-notation` values. All 12 affected selected suite cases pass
  their semantic checks; the post-change full suite report records the updated
  aggregate above.
- [x] The 2026-09-25 full two-mode curated BioModels refresh has a terminal
  report (see the current-head checkpoint below). This supersedes the older
  bounded run note; the core gate itself remains open because unsupported,
  failed, and timed-out models remain.

## Exact-head SBML Test Suite rerun — 2026-09-25

- [x] Rebuilt the Python extension with `BUILD_PYTHON_BINDINGS=ON` before
  validation. The checked-in `build/CMakeCache.txt` had bindings disabled and
  its Sep 17 extension lacked `write_sbml(..., source_metadata=...)`; the
  first run therefore produced 869 harness-induced `failed` records. That
  report is invalid as semantic evidence and is excluded below.
- [x] On BNG3 `a5f65ae05e26926b013f4ec3305dab34a3e9c84f`, reran all 1,923
  canonical cases from SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`.
  The latest full rerun, after the initial-assignment and species-pattern
  fixes, is `/private/tmp/bng3-sbml-suite-current-patternfix.json`, SHA-256
  `9499f41242ec04d4ea850cfcab4a8c35bfea23354a58081ccc70f74530ea1827`.
  Results: 869 passed, 1,054 explicitly unsupported, 0 failed, and 0 timed
  out. The 1,823 semantic cases yielded 869 passed and 954 unsupported; all
  100 stochastic cases remain unsupported. Each pass completed SBML input
  validation, modern Atomizer import, C++ network generation, SBML write and
  reimport, native-reader checks, and all-observable BNG3 CVODE versus
  libRoadRunner CVODE comparison. SBML Test Suite reference-result conformance
  was not run. Unsupported cause counts overlap: events 499, no state
  variables 254, stoichiometry 180, constraints 151, SBML comp package 123,
  algebraic rules 118, and MathML 70.
- [ ] The expanded supported surface still has 1,054 unsupported suite cases;
  this targeted rerun does not satisfy the complete Tier-X or release gate.
- [x] SBML Test Suite `semantic/00001` passed Atomizer import, network
  generation, SBML write/reimport, native-reader checks, and all-observable
  comparison against libRoadRunner 2.10.0 after the current Atomizer pattern
  round-trip fixes. This is a selected regression, not a full-suite pass.
  Report: `/private/tmp/bng3-sbml-case-00001-final-pattern-roundtrip.json`,
  SHA-256 `6eb1281a24165ec12b5e5bc3f0203b0166ac46bff3df32ce3bba7524e024afc`.

## Current independent-oracle checks — 2026-09-25

- [x] Full curated BioModels inventory rerun after the 2026-09-25
  initial-assignment and SBML-pattern fixes. All 1,096 inventory records are
  accounted for (1,075 declared SBML and 21 non-SBML); the SBML path includes
  8 archive-extracted SBML files. Each mode passed 651 records, reported 298
  unsupported SBML records, and failed on `BIOMD0000000584`; 133 records
  timed out across the combined run. The two newly fixed models,
  `BIOMD0000000429` and `BIOMD0000000202`, pass both modes. Aggregate core
  gate: **failed**. Report:
  `/private/tmp/bng3-curated-current-post-patternfix.json`, SHA-256
  `5e5f46244c71f8bea7f34c23eb784e504abdf3cef9b07ef57cec1f8cb02767da`.
- [x] After restoring the baseline matcher, curated BioModels
  `BIOMD0000000832` passed flat and Atomized routes, each comparing 40
  observables against libRoadRunner 2.10.0. Its record core status passed;
  the one-record command's corpus-level gate remained false by design. Report:
  `/private/tmp/bng3-biomodel-0832-final-roundtrip.json`, SHA-256
  `b8ecf106528322a0b96bc1dffbd53afe7bcda4ff391426bb62b8f31dc2125630`.
- [ ] The BioModels core gate remains failed until unsupported semantics,
  failures, and timeouts are resolved or explicitly excluded by an approved
  support boundary.
- [x] Fixed the `BIOMD0000000584` numerical mismatch. ODE derived-rate
  fallback matched reaction label `R1` as a substring of unrelated parameter
  `proAUR1_degradation_rate`, replacing synthesis rate `1` with `0.1`. The
  fallback now requires the NetWriter prefix `R1Rate_`. Red-first regressions
  cover the collision and the valid `R1Rate_2` fallback. The selected model
  passes flat and Atomized routes, all 56 observables versus libRoadRunner:
  `/private/tmp/bng3-biomodel-0584-after-ratefix.json`, SHA-256
  `dea4af9150c7622d0ecc6781c5a1600caa1dc409328640af15ca2e057970df72`.
- [ ] Full BioModels inventory rerun after the ODE rate-name fix is still
  running. Reconcile its aggregate counts and failures before treating the
  full-corpus gate as current.

- [x] BNG2 structural NET comparison on BNG3 `a5f65ae`: 9/9 selected models
  pass with the canonical sibling `bng2/BNG2.pl` at BNG2 revision
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`. Result summary:
  `/private/tmp/bng3-crossvalidate-a5f65ae-vs-bng2-8726b30.txt`.
- [x] PyBioNetGen source-derived public API compatibility against revision
  `43b09a5346402986d48b1defba5eaec0ae2f7802`: 5 tests pass.
- [x] Direct BNG3/native NFsim selected parity against independently rebuilt
  `RuleWorld/nfsim` revision `c51c7a34128d188189485bd318aeae4d936bcb29`:
  10 tests pass. Binary SHA-256:
  `093707031f70e0c376179e1d8bf89ab1373b3132b6211d7d9759f1d646c4ce9e`.
- [x] The SymbolTable now names duplicate `BarrierPattern` declarations
  explicitly. `tests/cpp/test_symbol_table.cpp` failed first on the generic
  diagnostic, then CTest case `duplicate barrier labels name their symbol
  kind` passed 1/1 after the minimal `kindName` mapping fix.
- [x] Rebuilt the current working tree after the diagnostic fix: full CTest
  passed 441/441; Python suite passed 477 with 28 skipped. The Python suite
  initially exposed BNGIR 0.1/0.2 schema drift for emitted barrier-pattern and
  driving-work fields. Both schemas now describe those optional fields while
  remaining compatible with older documents.
- [x] Final formatting and whitespace checks after the Atomizer round-trip
  fixes: Black, Ruff, and `git diff --check` pass.
- [x] Fixed an Atomizer self-parse defect in molecule-type output: component
  and state names had hyphens normalized in generated patterns but not in the
  molecule-type declaration. The regression was red before the writer change
  and green after; all 15 curated models previously failing Atomized-mode
  BNGL parsing now parse on the current tree. Two of those models pass the
  full two-mode validation. The other 13 exceed the combined 90-second
  per-model timeout after reaching network generation; a staged reproduction
  for `BIOMD0000000049` showed network explosion: at 30 seconds it was still
  on iteration 3, with 88,030 species and 99,600 reactions. The bounded debug
  log is `/private/tmp/bng3-biomodel-0049-network-profile.log` (12,658,622
  bytes; SHA-256 `786fddfe0967c9109d2ac4859c484f21989a4f9b4a1c3e7cfe0269618ab448ff`).
  Four other selected Atomized models also timed out under concurrent
  180-second limits. The current full report retains these as timeouts, not
  passes.
- [x] Built and smoke-installed the local alpha wheel
  `/private/tmp/bng3-wheel-a5f65ae-hyphenfix/bionetgen-3.0.0a1-cp314-cp314-macosx_26_0_arm64.whl`
  from the current working tree. Installation, native extension import, valid
  hyphen-normalized writer output, and native parsing pass. SHA-256:
  `066d4491cad2fd0beb0439db47d1cb2cc99ff82aab800d602055d80564af8c0c`.
  This is a macOS arm64 CPython 3.14 local preview; it is not a qualified
  release. Windows `.exe`, other platform wheels, clean-user dependency
  installation, hosted release jobs, and the failed corpus gates remain open.
- [x] PR #24 hosted checks are green at this merge head, including platform
  C++/Python matrices, independent BNG2/NFsim parity, full-corpus validation,
  and integration checks. Release-only wheels, sdist, Docker, and PyPI jobs
  were skipped by event guards. PR #16's earlier head `192dfff` had build
  failures; do not use that historical head as current validation evidence.
- [ ] PR #24's legacy Atomizer structure-copy optimization has a controlled
  wall-time comparison on curated BioModels `BIOMD0000000832`: 10 interleaved
  fresh-process runs per revision, with the parent `1ccf76d` and current
  `a5f65ae` producing the same canonical BNGL SHA-256
  `e53e0d2c256df2ff7a01c2f8b9bb2971f1579149aa0da77a797f3f7bad4c2b47`.
  Parent median was `1152.704 ms` (SD `44.779 ms`); current median was
  `1148.664 ms` (SD `82.756 ms`); paired median ratio was `0.9982`. This does
  not show a measurable speedup. Peak-memory comparison remains open. Input
  SHA-256: `b35ee199b0b2a7ee7bdfb50ef78e76edf649f280f7131b2e4ca170efd26e424e`.
  Runner: [`benchmarks/benchmark_legacy_atomizer.py`](../benchmarks/benchmark_legacy_atomizer.py).
  Report: `/private/tmp/bng3-legacy-atomizer-0832-pr24-interleaved.json`
  (SHA-256 `c171fe22a2b395b6cffd4f4bc68b6159461e7ae11128597eabfc87b855490039`).
  The benchmark's all-model memory/latency budgets remain open; round-trip
  pass counts are correctness evidence, not performance evidence.

## Published BioModels validation checkpoint — 2026-09-15

- [x] The manifest `provenance/published-biomodels.json` is query-backed and
  accounts for the complete manually curated BioModels inventory: `1,096`
  records (`1,075` SBML and `21` explicitly non-SBML formats). The runner
  `scripts/ci/validate_published_biomodels.py` performs modern import, BNG3
  network generation, C++ SBML writing, modern/native re-import, and direct
  all-observable BNG3 CVODE versus libRoadRunner CVODE comparison.
- [x] The official SBML Test Suite checkout is pinned to
  `cf38585fac5de8e0e90112febb62851ee2181816`; the round-trip runner covers all
  `1,823` semantic and `100` stochastic canonical cases available in that
  release checkout, with the absence of a syntactic corpus recorded.
- [ ] The complete numerical gates are intentionally not green: model
  representation limits, solver failures, cross-engine observable mismatches,
  and bounded timeouts remain explicit in the machine-readable reports. This
  evidence does not establish full SBML schema coverage, SBML Test Suite
  reference-result conformance, or biological validity.

## Historical checkpoint — 2026-09-15

The preceding combined-tree evidence is summarized in
[`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md). The native CTest gate is
`308/308`; the full validation corpus is `71/71` with zero failures, errors,
or skips; the six explicit action-output contracts are `6/6`; CI-contract
tests are `26 passed`; and the energy Python tests are `66 passed`. Black,
Ruff, corpus/provenance validation, and the zero-active-exception ledger also
pass.

Local Lean static validation checks 36 files and the NFnext contract binary
reports `18/18`; the Lean kernel is not installed locally. The PR now has a
pinned formal workflow that performs the hosted Lean 4.33.1 kernel build and
smoke check, which has passed for the published PR head. The former
reference-exclusion profiles are closed; the PR and weekly validation jobs now
run the full corpus using independent BNG2 network references plus explicit
action contracts. These results are exact-head checkpoint evidence only. The
exact hosted PR run
[34896645707](https://github.com/RuleWorld/BNG3/actions/runs/34896645707)
completed successfully at `ed4c59e`; the cross-tool parity run
[34896645694](https://github.com/RuleWorld/BNG3/actions/runs/34896645694), Lean
run [34896645788](https://github.com/RuleWorld/BNG3/actions/runs/34896645788),
CodeQL run [34896645673](https://github.com/RuleWorld/BNG3/actions/runs/34896645673),
and formatting run
[34896645763](https://github.com/RuleWorld/BNG3/actions/runs/34896645763) also
completed successfully. All PR-required build, Python, corpus, parity,
formal, package-smoke, and integration checks are terminal-success. The
scheduled-only NFsim job and release-only source-distribution, wheel, Docker,
and PyPI jobs remain conditionally skipped by their workflow event guards;
they are not validation-test exclusions. Complete backend equivalence, release
qualification, and every other unchecked item below remain open.

The main push run
[`34901298982`](https://github.com/RuleWorld/BNG3/actions/runs/34901298982)
then exposed two wheel-only environment failures: macOS x86_64 used a 10.9
deployment target although the ANTLR runtime requires APIs available from
10.12/10.13, and the manylinux2014 test image attempted to build NumPy 2.5.3
with GCC 10.2.1 although NumPy requires GCC 10.3 or newer. The follow-up
workflow repair pins cibuildwheel 4.2.1, selects native macOS architectures
with 10.13/11.0 deployment targets, and changes the Linux image to
`manylinux_2_28`. The CI workflow permits a manual-dispatch wheel run on an
exact branch head, but auxiliary run `34971595435` was canceled before its
wheel jobs started so validation could remain paused until merge. The wheel
checkpoint remains unchecked until the first post-merge main-push run has all
four platform jobs pass; this does not alter the zero-skip full-corpus result.

## Historical verified checkpoint

These items describe the current checkpoint. They do not satisfy the full
completion gate.

- [x] Full-corpus validation and exclusion-closure checkpoint
  `78a1591422ccbe6c4a5607eb748b426bbdbc303f` adds committed independent BNG2
  `.net` references for the previously missing network fixtures and the
  explicit action manifest `tests/validation/validation_manifest.json` for
  `ANx`, `hybrid_test`, `test_tfun`, `test_tfun_xml`,
  `test_write_sbml_multi`, and `visualize`. The PR and weekly workflows no
  longer pass reference-exclusion skip arguments. The exact local command
  `python scripts/validate.py --bng-cpp build/cpp/bng_cpp
  --strict-references --validation-manifest
  tests/validation/validation_manifest.json` reports `71 passed, 0 failed, 0
  errors, 0 skipped`; `python scripts/validate_actions.py --bng-cpp
  build/cpp/bng_cpp` reports `6/6` action contracts; CTest reports `308/308`;
  CI-contract tests report `26 passed`; and the energy Python suite reports
  `66 passed`. The former exclusion ledger is now `closed` with empty PR and
  weekly profiles. This closes the explicit PR/weekly validation exclusions,
  not the broader backend-equivalence or release gates.

- [x] Repository documentation and artifact-organization checkpoint moves the
  historical IR-migration reports and text metadata into
  `docs/archive/reports/ir-migration-2026-09-14/`, with an index directing
  readers to the live progress, checklist, integration, and validation docs.
  Obsolete package-wrapper files and the four applied patch snapshots were
  removed; model/test fixture text files and dated handoff provenance remain
  in their operational directories. The final documentation head is covered by
  hosted CI run `34896645707`, whose required jobs completed successfully.

- [x] Windows/MSVC ANTLR compatibility checkpoint applies the existing
  `cpp/parser/antlr_compat.hpp` guard to `BNGParser.h`, `BNGParserVisitor.h`,
  and `BNGParserBaseVisitor.h`. This closes the direct generated-header include
  path that caused the preceding Windows jobs to fail on the SDK `constant`
  macro before ANTLR's `ParseTreeType` and parser enums were parsed. The local
  Release/Ninja rebuild passes, and the exact-head hosted Windows C++ and
  Python matrix checks pass in CI run `34896645707`.

- [x] Exact-head hosted validation checkpoint at
  `ed4c59e028b2799a7b8025a8b37dccdc1dec0888` completed with terminal-success
  PR-required jobs: all C++ platforms and ASan, the Python 3.9–3.14 matrix on
  Linux/macOS/Windows, full corpus on all three operating-system families,
  package smoke, integration, independent BNG2/NFsim parity, PyBioNetGen API
  compatibility, Lean 4.33.1/NFnext, CodeQL, lint, and formatting. The full
  corpus reports zero skipped fixtures, and `reference_exclusions.json` has
  empty PR and weekly profiles. Release-only and scheduled-only jobs are
  recorded as conditional skips in the hosted UI and are not part of the PR
  validation gate.

- [ ] Cross-platform wheel repair checkpoint: main push run `34901298982`
  exposed the macOS deployment-target and manylinux2014/NumPy compiler
  failures described above. The CI and release workflows now use cibuildwheel
  4.2.1, native macOS targets, and `manylinux_2_28`; the exact post-merge
  main-push matrix must pass before this item can be checked.

- [x] Local-only initial-assignment writer checkpoint
  `1662820a0222add1cd9d44e8dd64724590c4bce8` ports the pinned Playground
  `src/lib/atomizer/writer/bnglWriter.ts:34,1592-1594,2161-2170` contract at
  source revision `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c`. The Python writer
  now promotes non-species SBML initial assignments into stable assignment
  functions, skips species and duplicate assignment targets, rewrites
  assignment-rule references as zero-argument BNGL calls, and emits the
  `__assign_rule__` metadata functions used by the source's reverse-format
  seam. Source-derived tests in
  `tests/python/test_modern_atomizer_writer_parameters.py` and
  `tests/python/test_modern_atomizer_helpers.py` were red first with three
  assertion failures on the old writer; the repaired focused command reports
  `10 passed in 0.42s`. The modern Atomizer gate reports `158 passed in
  0.66s`; the full local command
  `PYTHONPATH=python:build/cpp python -m pytest tests/python -q -p
  no:cacheprovider` reports `333 passed, 27 skipped, 8 warnings in 15.31s`;
  and `ctest --test-dir build --output-on-failure` reports `190/190` in
  `1.61s`. Black (`--target-version py39`), Ruff, and `git diff --check` pass.
  The BNG3 native binary remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`, and
  the independent accepted-cutoff NFsim binary remains SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`.
  No hosted run or public SHA readback is claimed while `gh` and push are
  paused. Full reverse SBML consumption of assignment metadata, complete
  writer/schema validation, independent corpus parity, and release gates
  remain open.

- [x] Local-only unified Atomizer rate-processing checkpoint
  `700cbdeb0d539e8a84c9a68c628386b0b9f33437` ports the pinned Playground
  `src/lib/atomizer/writer/bnglWriter.ts:2972-3091,3321-3647,3683-3864`
  contract at source revision
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c`. The Python writer now exposes
  a source-shaped `ProcessedRate` result and `processReactionRate` facade,
  performs a bounded safe numerical mass-action check after concentration/
  amount normalization, folds only finite low-variance constants, cleans
  compartment factors before reversible splitting, and preserves nonlinear
  and denominator-sensitive rates as functional fallbacks. The tests-first
  red command failed during collection with
  `ImportError: cannot import name 'ProcessedRate'`; the repaired focused
  command
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=python:build/cpp python -m pytest
  tests/python/test_modern_atomizer_writer_rate_helpers.py -q
  -p no:cacheprovider` reports `11 passed in 0.25s`. The touched modern
  writer/parameter/rate tests report `86 passed in 0.35s`; the full local
  command
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=python:build/cpp python -m pytest
  tests/python -q -p no:cacheprovider` reports `337 passed, 27 skipped, 8
  warnings in 10.90s`; the CI contract file reports `20 passed in 0.28s`;
  and exact-tree `ctest --test-dir build --output-on-failure` reports
  `190/190` in `1.42s`. Black (`--target-version py39`), Ruff, and
  `git diff --check` pass. The BNG3 native `build/cpp/bng_cpp` artifact
  remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  No hosted run or public SHA readback is claimed while `gh` and push are
  paused. The bounded evaluator does not close full function/rate-law,
  SBML/schema, independent corpus, round-trip, SBML-Multi, direct-NFsim,
  packaging, release, or hosted validation gates.

- [x] Local-only modern writer facade and scoped-local-parameter checkpoint
  `b75e724b8bbd1301b6643c1ca1fe94683ebc827b` ports the pinned Playground
  `src/lib/atomizer/writer/bnglWriter.ts:1654-1810,1998-2050,3683-3915`
  entry-point split at source revision
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c`. BNG3 now exposes distinct
  `writeReactionRulesFlat`, `writeReactionRulesAtomized`, and
  `writeReactionRulesFlat_V2` facades while reusing the existing validated
  rate-processing path, and carries the source
  `config/types.ts:350-393` `replaceLocParams` option through BNGL generation.
  When local parameters are preserved, the writer emits stable reaction-scoped
  names and declarations, including rate-rule/assignment-flux paths; the
  default value-replacement behavior remains unchanged. The source-derived
  tests were red first against the previous exact head, failing during
  collection with `ImportError: cannot import name 'writeReactionRulesAtomized'`;
  the repaired focused writer/facade command reports `14 passed in 0.43s`.
  The action-aware expression validation repair now compares emitted rate
  networks against independent BNG2 rather than mislabeling solver-trajectory
  drift as direct RHS parity; its exact command reports `3 passed in 0.55s`
  using BNG2 source revision
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b` at
  `/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl` (SHA-256
  `cf5fd82d3df9b84835d29234bd32268b87eaa985dd221bd5d39aadef744795f4`).
  Exact-head local gates report `340 passed, 27 skipped, 8 warnings` for
  `tests/python`, `190/190` for Release/Ninja CTest, `189 files would be left
  unchanged` for Black, and Ruff plus `git diff --check` pass. The native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  No hosted run or public SHA readback is claimed under local-only mode. This
  closes only the bounded writer-entry/local-parameter and emitted-rate-network
  slices; direct expression-vector/RHS parity, complete writer/schema and
  round-trip parity, independent corpus coverage, SBML-Multi, direct-NFsim,
  packaging, release, and hosted gates remain open.

- [x] Local-only deterministic ODE gate hygiene checkpoint
  `1106ddf273f7c3f76b01d339a0d62a58e09175b4` removes `gene_expr` from
  `tests/validation/test_parity_ode.py`: its action block contains SSA and
  NF simulations, not a deterministic ODE simulation, so its randomly sampled
  `.gdat` outputs cannot be compared as ODE trajectories. The stochastic
  model remains covered by the separate stochastic validation path. Before
  this repair the action-aware gate reported a real but invalid comparison
  failure for `gene_expr`; the corrected independent BNG2-backed command
  `PYTHONDONTWRITEBYTECODE=1 BNG2_PERL=/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation/test_parity_ode.py -q -p no:cacheprovider`
  reports `5 passed in 4.62s`. Ruff, Black (`1 file would be left
  unchanged`), and `git diff --check` pass. This fixes validation scope only;
  complete deterministic/stochastic corpus parity, direct expression-vector
  and RHS parity, NFsim, SBML, Atomizer, round-trip, release, and hosted gates
  remain open.

- [x] Local-only validation-artifact selection checkpoint
  `ccb3ef9efd069bb9375a39ddb64b1861909b4aa8` makes the CLI validation runner
  select `<model>.net` and `<model>.gdat` before any suffixed action artifacts,
  and return no artifact when multiple non-preferred candidates are ambiguous.
  This removes filesystem-iteration-order dependence observed for action-heavy
  models such as `gene_expr`, which emit burn-in, SSA, and NF trajectories in
  one run. Source-derived harness tests in
  `tests/validation/test_harness_paths.py` report `2 passed, 7 deselected in
  0.10s`. The independent BNG2-backed ODE and emitted-rate-network gates report
  `8 passed in 5.03s`, and the export-format gate reports `12 passed in
  12.94s`; Ruff, Black on the focused harness test, and `git diff --check`
  pass. This closes artifact selection determinism only; complete trajectory
  selection policy, independent stochastic ensembles, direct expression-vector
  and RHS parity, NFsim, SBML, Atomizer, round-trip, release, and hosted gates
  remain open.

- [x] Local-only CI provenance-summary checkpoint
  `ce4575f5c31b94ded5dfac1842a9c8e438f608d4` adds source-revision and binary
  SHA-256 tables to the PR BNGL corpus-parse inventory and weekly NFsim
  execution-smoke summaries in `.github/workflows/ci.yml` and
  `.github/workflows/weekly.yml`. Both scripts now use `set -euo pipefail`.
  Source-derived workflow contracts were red first: the focused command
  reported `2 failed, 20 deselected`; after the workflow repair the full
  `tests/test_ci_contract.py` command reports `22 passed in 0.20s`. Ruff,
  Black, and `git diff --check` pass. `actionlint` was unavailable locally;
  no hosted run or public SHA readback is claimed under the local-only
  instruction. This closes only terminal provenance for these two inventory
  jobs; terminal summaries and fail-closed behavior for every required CI,
  validation, release, and hosted job remain open.

- [x] Fresh accepted-cutoff Tier-NF evidence at the current exact integration
  head `6cd401e470b46a528b3e6578d698bc879a41ad0a` used the independent NFsim
  source cutoff `3b046fc1b9f76719d92be22279b24992cdae7c35` and binary
  `/private/tmp/bng3-nfsim-3b046/build/NFsim` (SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`). The
  exact command
  `PYTHONDONTWRITEBYTECODE=1 NFSIM_BIN=/private/tmp/bng3-nfsim-3b046/build/NFsim BNG_CPP=/Users/akutuva/Documents/BioNetGen/BNG3/build/cpp/bng_cpp PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m nf --bng-cpp /Users/akutuva/Documents/BioNetGen/BNG3/build/cpp/bng_cpp -q -p no:cacheprovider`
  completed `10 passed, 185 deselected, 3 warnings in 151.88s`. It covers the
  selected `localfunc`, `motor`, `simple_system`, and `tlbr` native ensembles,
  direct/XML shadow checks, and fixed-seed endpoint checks. The warnings are
  the known zero-denominator invalid-divide diagnostic at
  `tests/validation/compare.py:1278`. This qualifies the selected slice at
  the current exact integration head only; full Tier-NF coverage, broader
  direct-NFsim three-way parity, and energy/provenance/release gates remain
  open.

- [x] Fresh independent BNG2 differential evidence at exact integration head
  `0fd370bcb200a6c83211d0c4d3b83b6f39e89865` used BNG2 source revision
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b` from
  `/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl`; the oracle script
  SHA-256 is `cf5fd82d3df9b84835d29234bd32268b87eaa985dd221bd5d39aadef744795f4`.
  The exact command
  `PYTHONDONTWRITEBYTECODE=1 BNG2_PERL=/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m "parity and not slow" --bng-cpp /Users/akutuva/Documents/BioNetGen/BNG3/build/cpp/bng_cpp -q -p no:cacheprovider`
  completed `54 passed, 46 skipped, 95 deselected in 109.06s`, with no
  assertion failures. The skips are explicit missing-reference, legacy-syntax,
  missing-asset, missing-NFsim, missing-test-data, or sandbox-`ps` conditions;
  this is a refreshed external subset result, not full Tier-P qualification.

- [x] Zero-baseline trajectory comparisons now fail closed at
  `5a7e31866c9c5cc87caa1ec7735b6b5c3ea76080`: exact zero/zero comparisons
  produce finite zero error, while nonzero differences at an exact zero
  baseline produce infinite error instead of NaN and a false pass. Tests-first
  evidence was `2 failed, 4 passed` on the old comparator; the repaired focused
  command reports `6 passed in 0.06s`, and accepted-cutoff direct/XML NF checks
  report `4 passed, 6 deselected in 4.19s` without the prior divide warnings.
  Ruff, focused Black, and `git diff --check` pass. This hardens comparator
  truthfulness only; it does not expand the independent corpus or close the
  remaining parity, provenance, or release gates.

- [x] Local-only structural C++/Perl validation checkpoint
  `c6780bb3f7f65c46233f23750047b5c45e52afca` replaces the weekly shell
  species-count comparison with `scripts/cross_validate.py:1-376`. Both
  engines now receive a staged network-only model in isolated temporary
  directories; model construction and `generate_network` are retained while
  simulation/output actions are removed, and the generated NETs are compared
  through `tests/validation/compare.py` graph-aware species, reaction, rate,
  and observable-group semantics. The weekly job wiring is at
  `.github/workflows/weekly.yml:199-225`; it installs NumPy, records the exact
  BNG3 source revision, and emits a terminal provenance summary with both
  engine digests. Source/oracle tests in `tests/test_ci_contract.py:134-330`
  were red first during collection (`ModuleNotFoundError` before the new
  runner existed) and the repaired focused command reports `20 passed in
  0.24s`; Black (`--target-version py39`), Ruff, and `git diff --check` pass.
  Against independent BNG2 source revision
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b` at
  `/private/tmp/bng2-oracle.TToh58/source/bng2`, the bounded generation-only
  matrix (`simple_system`, `test_assignment`, `test_compartment_XML`,
  `test_sbml_flat`, `test_tfun_observable`, `test_time`) was run with
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=python:build/cpp python -u
  scripts/cross_validate.py --bng-cpp build/cpp/bng_cpp --bng-perl
  /private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl --models-dir
  tests/validation/Validate --timeout 30 --model simple_system --model
  test_assignment --model test_sbml_flat --model test_compartment_XML --model
  test_time --model test_tfun_observable --verbose`. It reports `5` passes,
  `0` failures, and `1` error; `test_sbml_flat` is an explicit BNG2
  `test_sbml_flat` is an explicit BNG2
  `sbmlTranslator` asset error. The independent and repository BNG2.pl
  scripts both have SHA-256
  `cf5fd82d3df9b84835d29234bd32268b87eaa985dd221bd5d39aadef744795f4`, and
  the BNG3 native binary has SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  A full 71-model local sweep was stopped before a terminal result because a
  large model exceeded the efficient local loop; no full-corpus parity claim
  is made. Full Python remains `333 passed, 27 skipped, 8 warnings`, and CTest
  remains `190/190`; no hosted run or public SHA readback is claimed while
  `gh` and push are paused. Independent oracle asset/build retention, full
  cross-corpus parity, SBML translator coverage, and all broader convergence
  gates remain open.

- [x] Local-only modern-writer identifier and fixed-seed lookup checkpoint
  `0d921d6639619b99ae08f35379af07bea940a2b1` ports the pinned Playground
  `src/lib/atomizer/writer/bnglWriter.ts:80-103,1050-1060,1244-1246,1427-1446`
  contract at source revision
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c`. The Python writer now uses the
  source's function-only reserved identifier set for function names and formal
  arguments, rewrites calls in emitted function bodies, and adds the `$` form
  of fixed seed patterns to the returned `pattern_to_id` lookup while keeping
  the canonical mapping unchanged. Source-derived tests in
  `tests/python/test_modern_atomizer_writer_parameters.py` and
  `tests/python/test_modern_atomizer.py` were red first: the strict identifier
  test reported `1 failed, 6 deselected` and the fixed-seed mapping test
  reported `1 failed, 66 deselected`; the repaired focused command reported
  `5 passed, 69 deselected in 0.69s`. The modern Atomizer gate reports `155
  passed in 0.65s`; the full local command
  `PYTHONPATH=python:build/cpp python -m pytest tests/python -q -p no:cacheprovider`
  reports `330 passed, 27 skipped, 8 warnings in 15.59s`; and
  `ctest --test-dir build --output-on-failure` reports `190/190` in `1.72s`.
  Black (`--target-version py39`), Ruff, and `git diff --check` pass. No
  generated artifacts were committed; the BNG3 native binary remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`, and
  the independent NFsim binary remains SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`.
  No hosted run or public SHA readback is claimed while `gh` and push are
  paused. Full writer/schema validation, complete SBML/SBML-Multi round trips,
  independent corpus parity, and release gates remain open.

- [x] Local-only BNG-XML fallback source-alignment checkpoint
  `983e5cd4473fddf8849fdaf9e4861fac521ecd66` aligns
  `python/bionetgen/atomizer/modern/bng_xml.py` with the pinned Playground
  `src/lib/atomizer/parser/bngXmlParser.ts:160-172,268-294` at source revision
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c`. Source-derived tests in
  `tests/python/test_modern_atomizer_annotations.py` cover the source's
  Expression-over-math priority and its search for the first compartmented
  reactant when scaling MM/Sat constants. The focused red-first command
  `PYTHONPATH=python:build/cpp pytest -q tests/python/test_modern_atomizer_annotations.py -k 'bng_xml_converter_prefers_expression_over_math or bng_xml_converter_scales_from_first_compartmented_reactant'`
  reported `2 failed, 9 deselected in 0.39s`; after the targeted fix it
  reported `2 passed, 9 deselected in 0.37s`. The grouped modern Atomizer
  command covering annotations, SBML-Multi, and units reported `22 passed in
  0.36s`; Black, Ruff, and `git diff --check` passed. The full local command
  `PYTHONPATH=python:build/cpp pytest -q` reported `329 passed, 27 skipped,
  8 warnings in 2.85s`, and `ctest --test-dir build --output-on-failure`
  reported `190/190` in `1.24s`. No generated artifacts were committed; the
  BNG3 native binary remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`, and
  the independent NFsim binary remains SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`.
  No hosted run or public SHA readback is claimed while public inspection and
  push are paused. Full BNG-XML schema/semantic validation, complete
  SBML/SBML-Multi round trips, and independent corpus parity remain open.

- [x] Local-only reference-validation reporting checkpoint
  `575246a39688e84d0bca856dd1a16da838e97159` adds the reusable
  `--summary-file` contract in `scripts/validate.py` and wires the PR
  `validation` and weekly `bng-validation` jobs to append terminal Markdown
  summaries to `$GITHUB_STEP_SUMMARY`. The summary records the checked-out
  BNG3 revision when `GITHUB_SHA` is available, the validation corpus, the
  bng_cpp path and SHA-256, strict skip policy, and pass/fail/error/skip counts.
  The tests-first command
  `PYTHONPATH=python:build/cpp pytest -q tests/test_ci_contract.py -k 'terminal_validation_summaries or validation_summary_records_counts_source_and_binary_digest'`
  first failed during collection because the summary writer was absent; the
  repaired command reports `2 passed, 13 deselected in 0.06s`, and the full CI
  contract file reports `15 passed in 0.07s`. The actual profiled local command
  with a temporary summary artifact reports `40` pass, `0` fail, `0` error,
  and `31` explicit skips; the artifact records bng_cpp SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Black, Ruff, and `git diff --check` pass; the full local command
  `PYTHONPATH=python:build/cpp pytest -q` reports `329 passed, 27 skipped,
  8 warnings in 3.77s`, and `ctest --test-dir build --output-on-failure`
  reports `190/190` in `1.68s`. No generated repository artifacts were
  committed. No hosted run or public SHA readback is claimed while public
  inspection and push are paused. Terminal summaries for every remaining
  required job, exception-budget/source-lock fields, complete independent
  oracle validation, and release gates remain open.

- [x] Local-only validation-harness checkpoint `21d453f25254f0d55d1374e683233629480d80b4`
  repairs the independent Perl oracle invocation in
  `tests/validation/oracle_perl.py`: the harness now runs BNG2 from the
  fixture's source directory, passes an absolute source path, directs generated
  output to the temporary work directory with `--outdir`, and derives
  `BNGPATH` from the BNG2 script when the caller has not supplied one. The
  source-derived regression in
  `tests/validation/test_harness_paths.py` was red first (`1 failed, 6
  deselected`) and then passed (`1 passed, 6 deselected in 0.05s`); the complete
  focused path file reports `6 passed, 1 skipped in 0.66s`. The independent
  BNG2 Perl oracle is source revision
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b` in the temporary checkout
  `/private/tmp/bng2-oracle.TToh58/source/bng2`; the independent NFsim oracle
  is the accepted source cutoff
  `3b046fc1b9f76719d92be22279b24992cdae7c35`, with binary SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`;
  the BNG3 native binary SHA-256 is
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  With those independent paths, the smoke gate reports `17 passed, 2 skipped,
  176 deselected in 22.92s`; the two skips are `gene_expr` oracle cases because
  this temporary BNG2 root has no `bin/NFsim`. The broader non-slow parity
  gate reports `54 passed, 46 skipped, 95 deselected in 102.99s`; remaining
  skips expose unsupported legacy fixtures, missing model sidecars, unsupported
  BNG2 action/rule constructs, and the absent BNG2-side NFsim executable rather
  than being hidden by the harness. Current local gates are Ruff/Black/diff
  clean, full Python `320 passed, 27 skipped, 8 warnings in 3.23s`, and exact
  Release/Ninja CTest `190/190` in `1.51s`. No generated golden/reference
  artifacts were committed, no hosted run was created, and no public SHA
  readback is claimed for this local-only checkpoint. Independent oracle
  retention, complete corpus/provenance, full Tier-P/NF/X parity, and all
  broader validation gaps remain open.

- [x] Local-only SBML unit-normalization checkpoint
  `fd6d26f2522eab3d20bc863bb91fb3423bc04730` completes the bounded
  Playground `src/lib/atomizer/validation/units.ts` contract at pinned source
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c`. Source-derived tests in
  `tests/python/test_modern_atomizer_units.py` cover the full multiplier/scale/
  exponent product, base/unknown-unit no-ops, global and kinetic-law-local
  parameters, dimensional compartment defaults for volume/area/length,
  amount/concentration scaling, audit warnings, and the source's finite-value
  guard. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider
  tests/python/test_modern_atomizer_units.py -q` reported `1 failed, 3
  passed in 0.37s` because a non-finite parameter was coerced to zero; the
  targeted fix preserves the non-finite value and the repaired command reports
  `4 passed in 0.23s`. The modern Atomizer gate reports `149 passed in 0.31s`,
  the full Python gate reports `324 passed, 27 skipped, 8 warnings in 2.63s`,
  exact Release/Ninja CTest reports `190/190` in `1.22s`, and Ruff/Black pass.
  The independent NFsim binary remains SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`, and
  the BNG3 native binary remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  No generated artifacts were committed, no hosted run was created, and no
  public SHA readback is claimed for this local-only checkpoint. Full SBML
  semantics, schema validation, SBML-Multi execution, independent format
  parity, and the remaining convergence gates stay open.

- [x] Local-only SBML-Multi namespace-presence checkpoint
  `23f698b2a6f19def72c1e19f7d373bcde3e8b4d1` aligns the bounded
  Playground `src/lib/atomizer/validation/multiPackage.ts` extractor at pinned
  source `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` with XML namespace
  declarations that have no child Multi elements. The source-derived tests in
  `tests/python/test_modern_atomizer_multi.py` preserve all four existing
  contracts and add shallow singleton-site bond fallback, deep Simmune-style
  hierarchy detection without flattening, and the missing
  `listOfSpeciesTypes` diagnostic. The new namespace regression was red first
  (`1 failed, 2 passed in 0.38s`), then the corrected complete file reports
  `7 passed in 0.38s`; the pre-existing tests were restored before commit and
  rerun. The modern Atomizer gate reports `152 passed in 0.34s`, the full
  Python gate reports `327 passed, 27 skipped, 8 warnings in 2.80s`, and exact
  Release/Ninja CTest reports `190/190` in `1.42s`. No generated artifacts
  were committed, no hosted run was created, and no public SHA readback is
  claimed for this local-only checkpoint. Multi remains diagnostic/comment-only:
  complete species-feature/seed semantics, writer/schema validation, execution,
  and independent SBML-Multi parity remain open.

- [x] Required fast-forward pull completed before this documentation change.
- [x] Historical semantic checkpoint
  `44d8655d3b0d838dc33420c0d7800c12bb465785` passes the full local
  Release/Ninja CTest gate and the legacy Macro security contract. The
  current semantic checkpoint supersedes it and requires fresh exact-head
  evidence.
- [x] The previous local semantic checkpoint was
  `ead6b8e1513f819ec91571aa0e5ead49aa119a8c`; its parent
  `7705c488c3ce4e1e64b47b001146f981b9e68d48` is the tests-first
  reverse-rate derivation checkpoint. `ead6b8e` makes the compartment-aware
  species deduplication guard semantic rather than serialization-order based.
  The source-derived cBNGL iteration-3 contract passes (`16` species), and
  the full root cBNGL fixture converges to `78` species and `354` reactions,
  matching `tests/validation/Validate/DAT_validate/Motivating_example_cBNGL.net`.
- [x] The previous public code/test checkpoint was
  `ead6b8e1513f819ec91571aa0e5ead49aa119a8c`; it includes the source-derived
  cBNGL compartment-deduplication regression and is the exact public branch
  head read back with `gh api` before the Macro checkpoint.
- [x] The previous local semantic checkpoint is
  `4edf4df57f01d22f15d83ee6635b82e974b0e6dc`; it completes the previously
  unlinked `MacroBNGModel::trans_specie` source port, wires the source
  `pre_rules`/`pre_obs1` pipeline, and ports the accepted `num_site`
  allocation rewrite. Its source-derived Macro contract passes in
  `tests/cpp/test_network_generator.cpp`.
- [x] The previous public code/test checkpoint is
  `4edf4df57f01d22f15d83ee6635b82e974b0e6dc`; `gh api` and `gh pr view 2`
  agreed on the exact public branch/PR head before this semantic checkpoint.
- [x] The latest local semantic checkpoint is
  `88f4e548ed8b7ef43cfc57aa62ad7b7914205613`; it ports the accepted NFsim
  `4bb24b3119684e9ec6e870bb4b517866e2aa15a4` cached-old-propensity lookup
  for implicit sparse selector batches and adds a source-derived fired-event
  regression in `tests/cpp/test_nfsim_ast_adapter.cpp`.
- [x] The latest public code/test checkpoint is
  `88f4e548ed8b7ef43cfc57aa62ad7b7914205613`; `gh api` and `gh pr view 2`
  agree on the exact public branch/PR head after push.
- [x] The latest local semantic checkpoint is
  `7241746a50ed0f87f23ad93eda38b2a9e7cca180`; it ports the accepted-cutoff
  NFsim `301bfbeb5ec5007532f713f488ff9954da9ebe1f` guarded Release-LTO probe
  and applies the detected IPO property to embedded NFsim and its built
  consumers. The source-derived CMake contract is
  `tests/cpp/test_release_lto.cmake`.
- [x] The latest public semantic code/test checkpoint is
  `7241746a50ed0f87f23ad93eda38b2a9e7cca180`; exact `gh api` branch and
  `gh pr view 2` readback agree, and PR #2 remains open.
- [x] The latest local semantic checkpoint is
  `413523620b1903f7152a27ee6441b0b4d07b933b`; it ports Playground commit
  `9bbad7b63968c18ccd1936c664e681360dd0b014` by adding an opt-in
  `keep_parameterized` path to `modern.write_functions`, with sanitized
  formal arguments and source-derived coverage in
  `tests/python/test_modern_atomizer_writer_parameters.py`.
- [x] The latest public semantic code/test checkpoint is
  `413523620b1903f7152a27ee6441b0b4d07b933b`; exact `gh api` branch and
  `gh pr view 2` readback agree, and PR #2 remains open.
- [x] A bounded audit of the Python-relevant Playground writer fixes at source
  commits `d95fe58c65751135f76a18034039105f5eaf7f0`,
  `98ca8f3bd215ec97babba528b9c768246f3d9b2f`,
  `9f2044089cc30e72ea4e346ea18de69466455286`, and
  `9bbad7b63968c18ccd1936c664e681360dd0b014` found no unported supported
  slice: assignment-rule/seed resolution and time-rate wrapping are covered
  by the earlier modern-writer ports, reaction-flux inlining is covered by
  `9124fc5`, two-argument `log(base,value)` conversion is present in
  `modern/writer.py`, and `keepParameterized` is covered by `4135236` and
  `tests/python/test_modern_atomizer_writer_parameters.py`. This is a source
  reconciliation note only; comprehensive writer, parser, SBML-writer, and
  independent round-trip parity remain open.
- [x] Accepted-cutoff NFsim commit
  `59423016cb2b30ac2dbc058bf8ef7cc5efb6bdf3` (small-`Km` Michaelis-Menten
  root-stability fix) is represented equivalently by BNG3 implementation
  `4dac1c74977493718b2ef7891bddad8a07842548` and its source-derived
  red-first regression `d7510f4f95e6af9e135b6fe361458bfb400f9251` in
  `tests/cpp/test_nfsim_ast_adapter.cpp`. This closes that accepted source
  slice only; independent full NFsim energy parity, benchmark provenance, and
  the remaining evaluator reconciliation gates stay open.
- [x] The applicable legacy function-dependency-cycle repair from the
  user-owned non-main source commit
  `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported exactly in
  `legacy/perl/Perl2/ParamList.pm` and covered by the source-derived
  `tests/python/test_legacy_function_cycles.py`. The red-first fixture now
  fails cleanly with `Function dependency cycle` rather than Perl deep
  recursion; the focused test reports `1 passed`, the Perl syntax check
  reports `syntax OK`, and the full Python suite reports `242 passed, 27
  skipped, 8 warnings`. This qualifies only the bounded cycle-detection slice;
  the remaining legacy/API deletion, serializer, parser, and independent
  BNG2 parity work stays open. Public branch and PR #2 read back to exact
  code head `1ff6d7bb9f0199ac8be09fa35174e0cd81e8a548`; CI
  [33580037044](https://github.com/RuleWorld/BNG3/actions/runs/33580037044),
  formatting [33580037040](https://github.com/RuleWorld/BNG3/actions/runs/33580037040),
  and CodeQL [33580037037](https://github.com/RuleWorld/BNG3/actions/runs/33580037037)
  were queued at readback, so they are not completion evidence.
- [x] The legacy CVODE export repair from the same user-owned source commit
  `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported in
  `legacy/perl/Perl2/Expression.pm`: `toCVodeString` now maps BNGL `~=` and
  `~` to C `!=` and `!`, uses numeric arity comparison for `sum`/`avg`, and
  reports its own CVODE diagnostic for anonymous-function expansion. The
  source-derived `tests/python/test_legacy_cvode_export.py` passes after the
  red-first export retained `~=`/`~`; focused legacy coverage reports `1
  passed`, Perl syntax reports `syntax OK`, exact-tree CTest reports `185/185`,
  and the full Python suite reports `243 passed, 27 skipped, 8 warnings`.
  This qualifies only the bounded CVODE-export slice; complete legacy/API
  retirement, serializer coverage, and independent BNG2 parity remain open.
  Public branch and PR #2 read back to exact code head
  `772adf55a8a8dafa1d49fabd940eec38fbf26187`; CI
  [33580496563](https://github.com/RuleWorld/BNG3/actions/runs/33580496563),
  formatting [33580496561](https://github.com/RuleWorld/BNG3/actions/runs/33580496561),
  and CodeQL [33580496583](https://github.com/RuleWorld/BNG3/actions/runs/33580496583)
  were queued at readback, so they are not completion evidence.
- [x] The legacy pattern-modifier/XML repair from the same user-owned source
  commit `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported in
  `legacy/perl/Perl2/Molecule.pm` and `legacy/perl/Perl2/SpeciesGraph.pm`:
  graph-level `{MatchOnce|Fixed}` modifiers now survive molecule parsing when
  adjacent to the final molecule or separated by whitespace, and XML
  quantifier relations escape `<`, `>`, `<=`, and `>=`. The exact source
  fixtures are covered by `tests/python/test_legacy_pattern_xml.py`; focused
  coverage reports `2 passed`, both touched Perl modules report `syntax OK`,
  exact-tree CTest reports `185/185`, and the full Python suite reports `245
  passed, 27 skipped, 8 warnings`. This qualifies only the bounded
  pattern/XML slice; complete legacy/API retirement, all serializer/parser
  compatibility, and independent BNG2 parity remain open. Public branch and
  PR #2 read back to exact code head
  `d1602bab0215c72352a21b10d0f6c54f396c88dd`; CI
  [33580739835](https://github.com/RuleWorld/BNG3/actions/runs/33580739835),
  formatting [33580739836](https://github.com/RuleWorld/BNG3/actions/runs/33580739836),
  and CodeQL [33580739837](https://github.com/RuleWorld/BNG3/actions/runs/33580739837)
  were queued at readback, so they are not completion evidence.
- [x] The legacy reactant-pattern symmetry correction from source commit
  `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported in
  `legacy/perl/Perl2/RxnRule.pm`. Aggregate-graph automorphisms are now
  filtered to preserve complete reactant-pattern boundaries before statistical
  factor calculation. The exact `issue_090_implicit_bonds` source fixture is
  covered by `tests/python/test_legacy_symmetry_factor.py`; red-first output
  was `0.25*_rateLaw1`, and the repaired output is `0.5*_rateLaw1`. Focused
  legacy coverage reports `1 passed`, all touched Perl modules report `syntax
  OK`, exact-tree CTest reports `185/185`, and the full Python suite reports
  `246 passed, 27 skipped, 8 warnings`. This qualifies only the bounded
  symmetry-factor slice; complete legacy/API retirement, broader reaction
  parity, and independent BNG2 evidence remain open. Public branch and PR #2
  read back to exact code head
  `7b6feae0c4052ad249a5b166e9b8c7f14347cf0a`; CI
  [33581009534](https://github.com/RuleWorld/BNG3/actions/runs/33581009534),
  formatting [33581009537](https://github.com/RuleWorld/BNG3/actions/runs/33581009537),
  and CodeQL [33581009550](https://github.com/RuleWorld/BNG3/actions/runs/33581009550)
  were queued at readback, so they are not completion evidence.
- [x] The legacy console error-routing repair from source commit
  `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported in
  `legacy/perl/Perl2/BNGUtils.pm` and `legacy/perl/Perl2/Console.pm` by
  exporting and using `send_error` for command/action failures while retaining
  warnings for unrecognized input. The source-derived
  `tests/python/test_legacy_console_streams.py` proves the red-first
  `WARNING:`/stdout behavior is replaced by `ERROR:`/stderr; focused coverage
  reports `1 passed`, touched Perl modules report `syntax OK`, exact-tree CTest
  reports `185/185`, and the full Python suite reports `247 passed, 27
  skipped, 8 warnings`. This qualifies only the bounded console stream slice;
  complete legacy/API retirement, CLI parity, and independent BNG2 evidence
  remain open. Public branch and PR #2 read back to exact code head
  `4d403ecc5c1627340f9c259cb7d9be745fbb814c`; CI
  [33581281331](https://github.com/RuleWorld/BNG3/actions/runs/33581281331),
  formatting [33581281347](https://github.com/RuleWorld/BNG3/actions/runs/33581281347),
  and CodeQL [33581281317](https://github.com/RuleWorld/BNG3/actions/runs/33581281317)
  were queued at readback, so they are not completion evidence.
- [x] The legacy NetworkGraph synthetic-zero trimming repair from source
  commit `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported in
  `legacy/perl/Perl2/Visualization/NetworkGraph.pm`. Empty rule-side zeros are
  removed only at the `->` boundary, preserving molecule labels that begin or
  end with `0`. The source-derived
  `tests/python/test_legacy_network_graph_labels.py` reports `1 passed` after
  red-first corruption of `0A`/`B0`; the touched Perl module reports `syntax
  OK`, exact-tree CTest reports `185/185`, and the full Python suite reports
  `248 passed, 27 skipped, 8 warnings`. This qualifies only the bounded graph
  label slice; complete visualization/API parity, legacy retirement, and
  independent BNG2 evidence remain open. Public branch and PR #2 read back to
  exact code head `99e99506cea1733c6a7e8dfe90531ec0f826c318`; CI
  [33581519666](https://github.com/RuleWorld/BNG3/actions/runs/33581519666),
  formatting [33581519687](https://github.com/RuleWorld/BNG3/actions/runs/33581519687),
  and CodeQL [33581519622](https://github.com/RuleWorld/BNG3/actions/runs/33581519622)
  were queued at readback, so they are not completion evidence.
- [x] The bounded legacy diagnostic/output repairs from source commit
  `dca95a6aa80e249f1adf981037b61bf020f7b5ad` are ported in
  `legacy/perl/Perl2/BNGAction.pm` and `legacy/perl/Perl2/BNGOutput.pm`:
  `retrieve` and `Writing` diagnostics are corrected, `QueryNames.m` uses an
  explicit three-argument open with error propagation, and generated MATLAB
  comments use `names`/`species`. The source-derived
  `tests/python/test_legacy_output_contract.py` reports `2 passed`; all
  touched legacy Perl modules report `syntax OK`; exact-tree CTest reports
  `185/185`; and the full Python suite reports `250 passed, 27 skipped, 8
  warnings`. This qualifies only the bounded output/diagnostic slice;
  complete legacy/API retirement, serializer/parser parity, packaging, and
  independent BNG2 evidence remain open. Public branch and PR #2 read back to
  exact semantic code head
  `bf2900b330868e78ca2833a6d6bd9d977859d2b9`; CI
  [33581941200](https://github.com/RuleWorld/BNG3/actions/runs/33581941200),
  formatting
  [33581941209](https://github.com/RuleWorld/BNG3/actions/runs/33581941209),
  and CodeQL
  [33581941228](https://github.com/RuleWorld/BNG3/actions/runs/33581941228)
  were queued at readback, so they are not completion evidence.
- [x] The bounded legacy Macro site-count repair from source commit
  `dca95a6aa80e249f1adf981037b61bf020f7b5ad` is ported in
  `legacy/perl/Perl2/MacroBNGModel.pm`: the `pre_species1` duplicate-site
  count now uses numeric `>` rather than lexicographic `gt`. The source-derived
  `tests/python/test_legacy_macro_numeric_compare.py` failed red-first on the
  old operator and passes after the port; the focused legacy suite reports
  `3 passed`, the Macro C++ contracts report `2/2`, the touched Perl module
  reports `syntax OK`, exact-tree CTest reports `185/185`, and the full Python
  suite reports `251 passed, 27 skipped, 8 warnings`. This qualifies only the
  bounded Macro comparison slice; complete legacy/API parity, serialization,
  packaging, and independent BNG2 evidence remain open. Public branch and PR
  #2 read back to exact semantic code head
  `7977966724246626a7c22c99489d99074427d8d6`; CI
  [33582369743](https://github.com/RuleWorld/BNG3/actions/runs/33582369743),
  formatting
  [33582369701](https://github.com/RuleWorld/BNG3/actions/runs/33582369701),
  and CodeQL
  [33582369686](https://github.com/RuleWorld/BNG3/actions/runs/33582369686)
  were queued at readback, so they are not completion evidence.
- [x] The latest CI truthfulness repair checkpoint is
  `e7cd59bd793a30d31bf2b8822725e05ba097b3d0`; it makes weekly C++/Perl
  cross-validation fail closed on engine, output, or corpus errors and adds
  the source-derived contract `test_weekly_cross_validation_fails_closed_on_engine_or_output_errors`.
  The focused local contract reports `8 passed`; exact branch and PR
  readback agree and PR #2 remains open. Hosted CI
  [33575648537](https://github.com/RuleWorld/BNG3/actions/runs/33575648537),
  formatting [33575648574](https://github.com/RuleWorld/BNG3/actions/runs/33575648574),
  and CodeQL [33575648533](https://github.com/RuleWorld/BNG3/actions/runs/33575648533)
  are queued for this exact SHA; queued status is not completion evidence.
- [x] The latest strict-reference validation checkpoint is
  `0e2642aa239c569f66eb550db6c0952219060142`; `scripts/validate.py` now has
  `--strict-references`, and the PR/weekly reference jobs use it while listing
  the current 35 known exclusions explicitly. The exact local validation
  subset reports `36` structural reference passes, `35` explicit exclusions,
  and `0` errors; the source-derived CI contracts report `10 passed`.
  This makes future unlisted missing `.net` oracles fail closed; it does not
  close the excluded validation or provenance gaps. Hosted CI
  [33577070603](https://github.com/RuleWorld/BNG3/actions/runs/33577070603),
  formatting [33577070621](https://github.com/RuleWorld/BNG3/actions/runs/33577070621),
  and CodeQL [33577070593](https://github.com/RuleWorld/BNG3/actions/runs/33577070593)
  are queued for this exact SHA.
- [x] Exact-head strict-reference validation at semantic code checkpoint
  `277e0b66a3bb911ed2faf1f069975cdb2108c592` used
  `PYTHONPATH=python:build/cpp python scripts/validate.py --bng-cpp
  build/cpp/bng_cpp --strict-references --skip-file
  tests/validation/reference_exclusions.json --skip-profile pull_request
  --verbose` and reports `40` passes, `0` failures, `0` errors, and `31`
  explicit skips. The current `build/cpp/bng_cpp` artifact has SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  This is current local structural NET evidence only; the 31 explicitly
  excluded models, independent-oracle/provenance requirements, and complete
  Tier-P/Tier-NF parity remain open. The semantic checkpoint's hosted CI
  [33592147684](https://github.com/RuleWorld/BNG3/actions/runs/33592147684),
  CodeQL [33592147712](https://github.com/RuleWorld/BNG3/actions/runs/33592147712),
  and formatting [33592147725](https://github.com/RuleWorld/BNG3/actions/runs/33592147725)
  were queued at exact-head readback.
- [x] Historical published CI-repair checkpoint is
  `9a2475a0af360d685dc41eb9bb376f6517d74b4d`; `gh api` and `gh pr view 2`
  agreed on this branch/PR source head immediately after push, and PR #2
  remains open.
- [x] The small documentation grammar fix remains the only unrelated tracked
  BNG3 worktree modification. It remains intentionally unstaged and must not
  be mixed into semantic or checklist commits.
- [x] The current checklist evidence checkpoint
  `85f2aff31865f9dfaba2147e6bccd8e791157a3f` is the exact public branch and
  PR #2 head read back with `gh api` and `gh pr view`; PR #2 remains open. Its
  exact-head CI
  [33583845197](https://github.com/RuleWorld/BNG3/actions/runs/33583845197),
  Formatting patch
  [33583845090](https://github.com/RuleWorld/BNG3/actions/runs/33583845090),
  and CodeQL
  [33583845085](https://github.com/RuleWorld/BNG3/actions/runs/33583845085)
  were queued at readback, so none is completion evidence yet.
- [x] Historical exact-head CTest passes `177/177` on `73757ea` (local
  Release/Ninja build; `ctest --test-dir build --output-on-failure`), including the exact
  compartment-aware dedup contract, compact ODE derivative contract, empty
  graph, exact Node serialization, t4 rejection contract, inferred-state/
  type-order gates, and IfTest parity assertions.
- [x] Historical semantic checkpoint `d502e47` passes the full local
  Release/Ninja CTest gate: `178/178` from `ctest --test-dir build
  --output-on-failure`, including the user-defined ODE-rate contract.
- [x] Current semantic checkpoint `4ea7157` passes the full local Release/Ninja
  CTest gate: `180/180` from `ctest --test-dir build --output-on-failure`,
  including the source-derived multi-pattern ODE and repeated-pattern NetWriter
  contracts. This evidence qualifies `4ea7157` only; later semantic or
  documentation heads require fresh exact-head readback.
- [x] Current semantic checkpoint `1c03bc1` passes the full local Release/Ninja
  CTest gate: `181/181` from `ctest --test-dir build --output-on-failure`,
  including the source-derived CLI action-error contract. This evidence
  qualifies `1c03bc1` only; later semantic or documentation heads require
  fresh exact-head readback.
- [x] Historical semantic checkpoint `44d8655` passes the full local
  Release/Ninja CTest gate: `181/181`; the full Python suite passes `237`
  tests with `27` skips and `8` warnings, and the legacy security contract
  passes `2/2` with `perl -c legacy/perl/Perl2/MacroBNGModel.pm` reporting
  syntax OK.
- [x] Exact-head local gates pass at `ead6b8e`: `ctest --test-dir build
  --output-on-failure` reports `100% tests passed out of 181`, and
  `PYTHONPATH=build/cpp:python python -m pytest tests/python -q` reports
  `240 passed, 27 skipped, 8 warnings` in `15.83s`. These local results do
  not substitute for terminal hosted checks or independent full-corpus
  parity.
- [x] Exact-head local gates pass at `4edf4df`: `ctest --test-dir build
  --output-on-failure` reports `100% tests passed out of 183`, including the
  two source-derived MacroBNGModel contracts, and
  `PYTHONPATH=build/cpp:python python -m pytest tests/python -q` reports
  `240 passed, 27 skipped, 8 warnings` in `11.81s`. These local results do
  not substitute for terminal hosted checks or independent full-corpus
  parity.
- [x] Exact-head local gates pass at `88f4e54`: `ctest --test-dir build
  --output-on-failure` reports `100% tests passed out of 184`, including the
  source-derived cached sparse-selector batch contract;
  `PYTHONPATH=build/cpp:python python -m pytest tests/python -q` reports
  `240 passed, 27 skipped, 8 warnings` in `11.28s`; and
  `PYTHONPATH=build/cpp:python python -m pytest tests/test_ci_contract.py -q`
  reports `7 passed`. These local results do not substitute for terminal
  hosted checks or independent full-corpus parity.
- [x] Exact-head local gates pass at `7241746`: the default Release/Ninja
  build with `NFSIM_ENABLE_LTO=ON` completes and `ctest --test-dir build
  --output-on-failure` reports `100% tests passed out of 185`, including the
  source-derived LTO contract; the same contract passes with explicit
  `NFSIM_ENABLE_LTO=OFF`; the optional `BUILD_NFSIM_CLI=ON` standalone NFsim
  target also builds and passes that contract; Python reports `240 passed,
  27 skipped, 8 warnings`; the CI contracts report `7 passed`; Black reports
  `178 files would be left unchanged`; Ruff and `git diff --check` pass.
  These local results do not substitute for terminal hosted checks or
  independent full-corpus parity.
- [x] The CI truthfulness repair test gate at `e7cd59b` reports `8 passed` via
  `PYTHONPATH=build/cpp:python python -m pytest tests/test_ci_contract.py -q`;
  `git diff --check` is clean. This verifies the workflow contract locally,
  not hosted execution or full weekly validation.
- [x] The strict-reference validation gate at `0e2642a` reports `10 passed`
  for the source-derived CI contracts; the supported local reference subset
  reports `36` passes, `35` explicit exclusions, and `0` errors. This is
  truthful coverage accounting, not complete Tier-P parity.
- [x] Exact-head deletion and ODE-validation checkpoint
  `5933584c3ae26690b35612bd589eeff37f37822a` is grounded in diagnostic BNG2
  source revision `fde0cd6a522c9f988d5495db31c70ce0f98e744b`: its
  `src/core/Transformation.cpp:397-410` `DeleteBond::transform` deletes the
  bound bond and restores two explicit `UNBOUND` endpoints, while
  `bng2/Perl2/Component.pm:153-188` omits an unbound edge marker from the
  serialized component. BNG3 now restores markers only for surviving endpoints
  in `cpp/ast/ReactionRule.cpp:495-559`; deletion endpoints are excluded from
  the restoration to prevent orphan marker-only species. The source-derived
  regression is `tests/cpp/test_reaction_rule_expansion.cpp:103-140`.
  Red-first focused execution reported `targetCount 2` before restoration and
  a marker-only species after the initial broad restoration; the final focused
  test reports `5 assertions in 1 test case`. The action-aware repair in
  `tests/validation/test_parity_ode.py:1-43` runs the model action block through
  the CLI, preserving setup actions that the direct API path discarded. The
  focused Motivation NET parity reports `2 passed`; focused action-aware ODE
  parity reports `1 passed`; full BNG2-backed smoke reports `17 passed, 2
  skipped` (both `gene_expr` because the external oracle cannot find NFsim);
  the complete native CTest gate reports `186/186`; Python reports `276 passed,
  27 skipped, 9 warnings`; Ruff and Black pass. One hundred isolated
  `Motivating_example` CLI runs all exit `0` and produce `78` species; the
  BNG2/B3 semantic NET comparator passes, with temporary NET digests
  `5ed6ddfd25b770bd7614f689e277d9ce6dd2371f293468bca10336d4a38d3025` and
  `8ee09b27cda0908c2dfd8039712b5c40fe59b16196380a1cb4de2d1395b2680a`.
  The rebuilt `build/cpp/bng_cpp` digest is
  `0f2b5d1357ed700241bb7326adebb546f0c51d249c58a3a2bc05b14523848227`.
  Public PR #2 readback agrees on this exact open head; CI
  [33642690870](https://github.com/RuleWorld/BNG3/actions/runs/33642690870),
  CodeQL [33642690911](https://github.com/RuleWorld/BNG3/actions/runs/33642690911),
  and formatting [33642690862](https://github.com/RuleWorld/BNG3/actions/runs/33642690862)
  were queued at readback and are not completion evidence. This closes only
  the deletion/validator defects; broad NET/ODE parity, independent oracle
  provenance, and the remaining checklist gaps stay open.
- [x] Fresh independent native-NFsim validation was rerun against semantic
  head `5933584c3ae26690b35612bd589eeff37f37822a` using the absolute oracle
  `/Users/akutuva/Documents/BioNetGen/nfsim/build/NFsim`, whose SHA-256 is
  `7302fe29b16d1ebe86369f752f2a49d2c87ef16539faaec11b82294a9fa56d22`.
  `test_nf_vs_native` used the committed four-model Tier-NF selection
  (`simple_system`, `tlbr`, `motor`, `localfunc`), 200 runs per model,
  seeds `1..200`, `t_end=50`, 50 output steps, and four isolated workers:
  `4 passed, 1 warning in 158.85s`.
  The current direct-vs-in-memory-XML localfunc contract reports `2 passed`,
  and the exact seeded native endpoint contract for motor/tlbr reports
  `2 passed` using the same oracle. This is fresh subset evidence only:
  TQSSA has no approved fixture in this checkout, and protocol-NF,
  three-way construction parity, and the full approved Tier-NF gate remain
  open.
- [x] Fresh diagnostic BNG2-backed non-slow parity at semantic head
  `5933584c3ae26690b35612bd589eeff37f37822a` used the isolated Perl/native
  oracle at source revision
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b` and the command
  `env BNG2_PERL=/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl
  PYTHONPATH=python:build/cpp python -m pytest -c
  tests/validation/pytest.ini tests/validation -m "parity and not slow"
  --bng-cpp build/cpp/bng_cpp -q`: `54 passed, 46 skipped, 94 deselected`
  in `110.02s`. No test failed; skips remain explicit for unavailable
  legacy/oracle inputs and assets. This improves current differential
  evidence but does not establish complete Tier-P parity or approve the
  diagnostic oracle as the release oracle.
- [x] The source-derived modern Atomizer gates at `4135236` report `76 passed`
  across the modern Atomizer test modules, and the full Python suite reports
  `241 passed, 27 skipped, 8 warnings`. This qualifies the Python semantic
  checkpoint only; independent oracle parity, full writer coverage, and
  hosted checks remain open.
- [x] Diagnostic independent BNG2 execution is now available from an isolated
  clone of source revision `fde0cd6a522c9f988d5495db31c70ce0f98e744b` using
  the repository's `bng2/Makefile`; the arm64 `run_network` artifact has
  SHA-256 `0dcde86b0e29a05e1af9ea1fb027cf2441641fd297906701ada37343c442977a`.
  A copied `simple_system` fixture generated a NET and completed CVODE through
  that binary. This is diagnostic evidence only: the source revision is not
  yet the approved lock cutoff and the temporary build is not a retained
  oracle artifact.
- [x] With that diagnostic BNG2 Perl/native oracle, the non-slow Tier-P NET
  parity command produced `50 passed, 46 skipped, 4 failed, 10 deselected` in
  `342.61s`. The four failures are concrete open gaps: a 180-second
  `Motivating_example_cBNGL` generation timeout, Repressilator degradation-rate
  mismatch, NFKB illustrating-protocol expression-rate serialization mismatch,
  and BNG3 rejection of the legacy `test_time` `f_correct` parameter. The
  skips remain honest where BNG2 cannot process legacy syntax/assets or lacks
  NFsim; this historical run does not qualify complete Tier-P parity. Targeted
  repairs now cover the four recorded signatures (`ead6b8e`, `418db22`,
  `7705c48`, and `d7536f5` respectively); the full differential command still
  needs a fresh terminal run against the approved independent oracle.
- [x] Exact historical BNG3 checkpoint `5f6da0747beda7d5c4d1728b2aa9caf6f3883dfa`
  was rebuilt in detached worktree `/private/tmp/bng3-asan-5f6da07` with the
  CI sanitizer flags and `BUILD_PYTHON_BINDINGS=OFF`, `BUILD_CLI=ON`, and
  `BUILD_TESTS=ON`. The exact local recipe used AppleClang 21.0.0 arm64,
  CMake 4.4.3, and Ninja 1.13.2; `cmake --build build-clang --parallel 4`
  completed, and `ASAN_OPTIONS=detect_leaks=0 ctest --test-dir build-clang
  --output-on-failure` reports `100% tests passed out of 161`. The resulting
  `build-clang/cpp/bng_cpp` artifact has SHA-256
  `891c7f4203af9d9cdddeb8e565489dfec5ed9742990cab15a463579e71828d54`.
  The requested Ubuntu/GCC-12 compiler was unavailable on this macOS host,
  so this is supplemental historical Clang-ASan evidence only; hosted Ubuntu
  ASan, UBSan/leak, Release, and cross-platform gates remain open.
- [x] Fresh local Debug/ASan validation at BNG3 head
  `3fc1ea546117fe9844d3bed3bd962fcf781cb6ab` configured the exact CI sanitizer
  flags in a separate `/private/tmp/bng3-asan-f1ee` tree: CMake 4.4.3, Ninja,
  AppleClang 21.0.0, `BUILD_PYTHON_BINDINGS=OFF`, `BUILD_CLI=ON`, and
  `BUILD_TESTS=ON`. `cmake --build /private/tmp/bng3-asan-f1ee --parallel 4`
  completed, and
  `ASAN_OPTIONS=detect_leaks=0 ctest --test-dir /private/tmp/bng3-asan-f1ee --output-on-failure`
  reported `100% tests passed out of 185` in 20.87 seconds. The temporary
  `cpp/bng_cpp` artifact has SHA-256
  `753a245ab667454234f55aa07ff7b501b118f05260986e71c02b6fd9f684a299`.
  This is supplementary local arm64 evidence only; hosted Ubuntu ASan,
  UBSan/leak, Release, and cross-platform gates remain open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:3386-3414` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` removes a leading compartment
  volume factor before mass-action normalization. The tests-first BNG3 port is
  `19a90ed83fad4529bb8e85e1a538e00ade274cb2`: the red-first output was
  `r: M_A()@cell -> M_P()@cell __compartment_cell__ * k`, while the repaired
  contract is
  `tests/python/test_modern_atomizer.py::test_playground_writer_strips_leading_compartment_factor_from_mass_action`
  with `r: M_A()@cell -> M_P()@cell k`. The modern Atomizer suite reports `80
  passed`, the full Python gate reports `255 passed, 27 skipped, 9 warnings`,
  and exact-tree CTest reports `185/185`. This closes only the bounded
  elementary leading-factor slice; nonlinear and broader rate normalization
  parity remain open.
- [x] The same Playground source block at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` strips internal multiplicative and
  divisive compartment factors before mass-action normalization. The
  tests-first BNG3 port is `c5429140e7436770bcb996d17a2fbdd9d0db2de9`; the
  red-first outputs were `r: M_A()@cell -> M_P()@cell k *
  __compartment_cell__` for multiplication and `r: M_A()@cell -> M_P()@cell
  k * _c_A() / __compartment_cell__` for division. The repaired contract is
  `tests/python/test_modern_atomizer.py::test_playground_writer_strips_internal_compartment_factor_from_mass_action`
  with both rates emitted as `r: M_A()@cell -> M_P()@cell k`. The focused
  test command
  `PYTHONPATH=build/cpp:python python -m pytest tests/python/test_modern_atomizer.py -q -k internal_compartment_factor`
  reports `2 passed`; the modern Atomizer glob reports `82 passed`; the full
  Python gate reports `257 passed, 27 skipped, 9 warnings` in `11.28s`; exact
  tree `ctest --test-dir build --output-on-failure` reports `185/185`; Ruff
  passes; and Black reports `186 files would be left unchanged`. The existing
  native smoke artifact `build/cpp/bng_cpp` remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public head readback is `c5429140e7436770bcb996d17a2fbdd9d0db2de9`;
  hosted CI run
  [33588500334](https://github.com/RuleWorld/BNG3/actions/runs/33588500334),
  matrix run
  [33588500343](https://github.com/RuleWorld/BNG3/actions/runs/33588500343),
  and formatting run
  [33588500425](https://github.com/RuleWorld/BNG3/actions/runs/33588500425)
  were pending when read back. The exact-head smoke command
  `PYTHONPATH=build/cpp:python python -m pytest -c tests/validation/pytest.ini tests/validation -m smoke --bng-cpp build/cpp/bng_cpp -q`
  reports `4 passed, 15 skipped, 175 deselected, 1 warning` in `8.24s`;
  skips remain explicit missing-reference/legacy-oracle and sandbox
  `run_network`/process-inspection gaps. This closes only the bounded
  elementary internal-factor slice; remaining source factor placement,
  zero-order/nonlinear normalization, and broader writer/parser/SBML parity
  remain open.
- [x] Playground `src/lib/atomizer/writer/eventActions.ts:293-294` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` uses JavaScript
  `Math.max(1, Math.round(...))` for scheduled event phase steps. The
  tests-first BNG3 port is
  `6b71ecc613f670667328cd49fa451196e0cebe29` in
  `python/bionetgen/atomizer/modern/events.py`: red-first Python banker's
  rounding emitted `n_steps=>2` for both half-step phases, while the repaired
  source-compatible contract emits `n_steps=>3` for both. The regression is
  `tests/python/test_modern_atomizer.py::test_playground_event_actions_use_source_half_up_step_rounding`;
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -q -k half_up_step_rounding` reports
  `1 passed, 42 deselected, 1 warning`; the modern Atomizer command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer*.py -q` reports `83 passed, 1 warning`,
  and `PYTHONPATH=build/cpp:python python -m pytest tests/python -q` reports
  `258 passed, 27 skipped, 9 warnings` in `10.53s`. The exact-tree command
  `ctest --test-dir build --output-on-failure` reports `185/185`; `ruff check
  --no-cache python/ tests/python/ scripts/` passes; and
  `black --check python/ tests/python/ scripts/` reports `186 files would be
  left unchanged`. This Python-only checkpoint changes no native artifact; the
  existing `build/cpp/bng_cpp` smoke artifact remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public head readback is
  `6b71ecc613f670667328cd49fa451196e0cebe29`; hosted CI run
  [33589168226](https://github.com/RuleWorld/BNG3/actions/runs/33589168226),
  matrix run
  [33589168215](https://github.com/RuleWorld/BNG3/actions/runs/33589168215),
  and formatting run
  [33589168250](https://github.com/RuleWorld/BNG3/actions/runs/33589168250)
  were pending when read back. This closes only nonnegative half-tie step
  rounding; broader event semantics and Atomizer writer/event parity remain
  open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:32-44,73-103` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` reports dependency
  cycles as bounded `DEP001` warnings with the traversed path and suppresses
  further messages after `ATOMIZER_DEP_CYCLE_LOG_LIMIT`. The tests-first BNG3
  port is `7323ae8685d83343204c38fa3a6bc4b055affc40` in
  `python/bionetgen/atomizer/modern/core.py`; its red-first focused test
  observed the expected sorted order but `0` warnings, and the repaired
  command `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_core.py -q -k dependency_cycles` reports
  `1 passed, 3 deselected, 1 warning`. The modern Atomizer suite reports `84
  passed, 1 warning`; the full Python gate reports `259 passed, 27 skipped, 9
  warnings`; exact-tree Release/Ninja CTest reports `185/185`; Ruff passes;
  and Black reports `186 files would be left unchanged`. This Python-only
  checkpoint leaves the native `build/cpp/bng_cpp` artifact unchanged at
  SHA-256 `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `7323ae8685d83343204c38fa3a6bc4b055affc40`; hosted CI run
  [33590840330](https://github.com/RuleWorld/BNG3/actions/runs/33590840330),
  CodeQL run
  [33590840321](https://github.com/RuleWorld/BNG3/actions/runs/33590840321),
  and formatting run
  [33590840350](https://github.com/RuleWorld/BNG3/actions/runs/33590840350)
  were queued when read back. This closes only dependency-cycle diagnostics;
  the remaining modern core, parser, writer, SBML, and independent parity
  gaps remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:2703-2721` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes
  `getAnnotationsByQualifier`, filtering raw annotation resources by the
  biological/model qualifier kind and numeric qualifier. The tests-first BNG3
  port is `c00c9bace01dbbc7c0e5fa4969cfaed9e35f2879` in
  `python/bionetgen/atomizer/modern/annotation.py` and the modern package
  facade; its red-first focused test failed at import because the public name
  was absent, and the repaired command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_annotations.py -q -k qualifier_helper`
  reports `1 passed, 6 deselected, 1 warning`. The modern Atomizer suite
  reports `85 passed, 1 warning`; the full Python gate reports `260 passed, 27
  skipped, 9 warnings`; exact-tree Release/Ninja CTest reports `185/185`;
  Ruff passes; and Black reports `186 files would be left unchanged`. This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `c00c9bace01dbbc7c0e5fa4969cfaed9e35f2879`; hosted CI run
  [33591261066](https://github.com/RuleWorld/BNG3/actions/runs/33591261066),
  CodeQL run
  [33591261064](https://github.com/RuleWorld/BNG3/actions/runs/33591261064),
  and formatting run
  [33591261083](https://github.com/RuleWorld/BNG3/actions/runs/33591261083)
  were queued when read back. This closes only the qualifier-resource helper
  facade; the remaining parser, annotation, writer, SBML, and independent
  parity gaps remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:2721-2750` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes
  `extractUniProtIds` and `extractGOTerms`, matching identifier substrings,
  preserving source order, and normalizing GO matches to `GO:<digits>`. The
  tests-first BNG3 port is `50da22fcba58782fa4d258294262ba89cf137198` in
  `python/bionetgen/atomizer/modern/parser.py` and the modern facade; its
  red-first focused test failed because both camelCase names were absent (and
  the existing GO extractor returned no match), while the repaired command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_annotations.py -q -k annotation_id_helpers`
  reports `1 passed, 7 deselected, 1 warning`. The modern Atomizer suite
  reports `86 passed, 1 warning`; the full Python gate reports `261 passed, 27
  skipped, 9 warnings`; exact-tree Release/Ninja CTest reports `185/185`;
  Ruff passes; and Black reports `186 files would be left unchanged`. This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `50da22fcba58782fa4d258294262ba89cf137198`; hosted CI run
  [33591493598](https://github.com/RuleWorld/BNG3/actions/runs/33591493598),
  CodeQL run
  [33591493608](https://github.com/RuleWorld/BNG3/actions/runs/33591493608),
  and formatting run
  [33591493576](https://github.com/RuleWorld/BNG3/actions/runs/33591493576)
  were queued when read back. This closes only the parser identifier-helper
  facade; the remaining parser, annotation, writer, SBML, and independent
  parity gaps remain open.
- [x] Playground `src/lib/atomizer/utils/helpers.ts:172-190` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` keeps memoization caches in
  process-global storage keyed by the explicit `cacheKey`, so separately
  wrapped functions share a named cache. BNG3 matches that explicit-key
  contract at `eecbdce646d06a9bd4c117379ee191b0dc6a1cc5` in
  `python/bionetgen/atomizer/modern/helpers.py`. The tests-first contract is
  `tests/python/test_modern_atomizer_helpers.py::test_playground_pmemoize_shares_explicit_cache_keys`.
  The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_helpers.py -q -k pmemoize_shares_explicit_cache_keys`
  reported `1 failed, 4 deselected in 0.24s`; the repaired focused command
  reports `1 passed, 4 deselected in 0.24s`. The complete helper test file
  reports `5 passed in 0.24s`; the modern Atomizer glob reports `143 passed in
  0.46s`; the full Python gate reports `318 passed, 27 skipped, 8 warnings`
  in `11.21s`; exact Release/Ninja CTest reports `190/190` in `1.32s`.
  Changed-file Ruff (`--no-cache`) passes, Black with the configured
  `--target-version py312` reports `2 files would be left unchanged`, and
  `git diff --check` passes. The native `build/cpp/bng_cpp` artifact remains
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `eecbdce646d06a9bd4c117379ee191b0dc6a1cc5`; hosted CI
  [33717664851](https://github.com/RuleWorld/BNG3/actions/runs/33717664851),
  CodeQL [33717664913](https://github.com/RuleWorld/BNG3/actions/runs/33717664913),
  and formatting
  [33717664952](https://github.com/RuleWorld/BNG3/actions/runs/33717664952)
  remain queued and are not completion evidence. This closes only explicit
  named-cache sharing; BNG3's default function key uses Python's module and
  qualified-name representation rather than JavaScript `fn.toString()`, and
  argument serialization remains Python-specific, so broader helper parity
  remains open.
- [x] Playground `src/lib/atomizer/config/types.ts:93-152,329-393` and
  `src/lib/atomizer/index.ts:130-150,390-397` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` expose the complete default
  `NamingConventions` data and accept a custom `namingConventions` option in
  the Atomizer facade. BNG3 matches the configuration fields, camel-case
  compatibility views, custom pattern resolution, default option, and facade
  wiring at `094f7ac62a2baae0abebfcac134f558a324a6744`. The tests-first
  contracts are
  `tests/python/test_modern_atomizer_core.py::test_playground_naming_conventions_export_and_custom_patterns_contract`
  and
  `tests/python/test_modern_atomizer.py::test_playground_atomizer_uses_source_naming_conventions_option`.
  The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_core.py tests/python/test_modern_atomizer.py -q -k 'naming_conventions_export_and_custom_patterns_contract or uses_source_naming_conventions_option'`
  reported `2 failed, 94 deselected in 0.60s`; the repaired focused command
  reports `2 passed, 94 deselected in 0.32s`. The modern Atomizer glob reports
  `145 passed in 0.42s`; the full Python gate reports `320 passed, 27 skipped,
  8 warnings` in `10.28s`; exact Release/Ninja CTest reports `190/190` in
  `1.25s`. Changed-file Ruff passes, Black with the configured
  `--target-version py312` reports `5 files would be left unchanged`, and
  `git diff --check` passes. The native `build/cpp/bng_cpp` artifact remains
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `094f7ac62a2baae0abebfcac134f558a324a6744`; hosted CI
  [33767541435](https://github.com/RuleWorld/BNG3/actions/runs/33767541435),
  CodeQL [33767541537](https://github.com/RuleWorld/BNG3/actions/runs/33767541537),
  and formatting
  [33767541467](https://github.com/RuleWorld/BNG3/actions/runs/33767541467)
  remain queued and are not completion evidence. This closes the default and
  custom naming-configuration slice only; user-structure equivalences,
  broader Atomizer core/parser/writer/SBML behavior, and independent parity
  remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:227-265` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` emits an `INFO`-level `NAM001`
  summary after naming-convention analysis, reporting similar-pair and
  classification counts. The tests-first BNG3 port is
  `71e25111f30eac8d33bdeca6faf1f78949f158f1` in
  `python/bionetgen/atomizer/modern/core.py`; its red-first focused test
  observed `0` info messages, and the repaired command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_core.py -q -k naming_analysis_reports_summary`
  reports `1 passed, 4 deselected`. The modern Atomizer suite reports `87
  passed`; the full Python gate reports `262 passed, 27 skipped, 8 warnings`;
  exact-tree Release/Ninja CTest reports `185/185`; and changed-file Ruff and
  Black checks pass (`2 files would be left unchanged` for Black). This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `71e25111f30eac8d33bdeca6faf1f78949f158f1`; hosted CI run
  [33591884302](https://github.com/RuleWorld/BNG3/actions/runs/33591884302),
  CodeQL run
  [33591884261](https://github.com/RuleWorld/BNG3/actions/runs/33591884261),
  and formatting run
  [33591884259](https://github.com/RuleWorld/BNG3/actions/runs/33591884259)
  were queued when read back. This closes only the naming-diagnostic facade;
  broader Atomizer core/parser/writer/SBML behavior and independent parity
  remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:536-616` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` emits an `INFO`-level `RXN001`
  summary after reaction analysis, reporting binding and modification counts.
  The tests-first BNG3 port is
  `277e0b66a3bb911ed2faf1f069975cdb2108c592` in
  `python/bionetgen/atomizer/modern/core.py`; its red-first focused test
  observed `0` info messages while preserving the expected binding map, and
  the repaired command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_core.py -q -k reaction_analysis_reports_summary`
  reports `1 passed, 5 deselected`. The modern Atomizer suite reports `88
  passed`; the full Python gate reports `263 passed, 27 skipped, 8 warnings`;
  exact-tree Release/Ninja CTest reports `185/185`; and changed-file Ruff and
  Black checks pass (`2 files would be left unchanged` for Black). This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `277e0b66a3bb911ed2faf1f069975cdb2108c592`; hosted CI run
  [33592147684](https://github.com/RuleWorld/BNG3/actions/runs/33592147684),
  CodeQL run
  [33592147712](https://github.com/RuleWorld/BNG3/actions/runs/33592147712),
  and formatting run
  [33592147725](https://github.com/RuleWorld/BNG3/actions/runs/33592147725)
  were queued when read back. This closes only the reaction-diagnostic
  facade; broader Atomizer core/parser/writer/SBML behavior and independent
  parity remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:924-1126` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` emits an `INFO`-level `SCT001`
  summary after building the species-composition table, reporting total,
  elemental, and complex counts. The tests-first BNG3 port is
  `90c36849e9d24feb4ad1d720cad218aef184ed22` in
  `python/bionetgen/atomizer/modern/core.py`; its red-first focused test
  built the expected one-entry table but observed no `SCT001` message, and
  the repaired command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_core.py -q -k sct_builder_reports_summary`
  reports `1 passed, 6 deselected`. The modern Atomizer suite reports `89
  passed`; the full Python gate reports `264 passed, 27 skipped, 8 warnings`;
  exact-tree Release/Ninja CTest reports `185/185`; and changed-file Ruff and
  Black checks pass (`2 files would be left unchanged` for Black). This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `90c36849e9d24feb4ad1d720cad218aef184ed22`; hosted CI run
  [33592851760](https://github.com/RuleWorld/BNG3/actions/runs/33592851760),
  CodeQL run
  [33592851732](https://github.com/RuleWorld/BNG3/actions/runs/33592851732),
  and formatting run
  [33592851748](https://github.com/RuleWorld/BNG3/actions/runs/33592851748)
  were queued when read back. This closes only the SCT-diagnostic facade;
  broader Atomizer core/parser/writer/SBML behavior and independent parity
  remain open.
- [x] Playground `src/lib/atomizer/index.ts:56-58,80-84,104-194,453-458` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` configures the shared
  logger, emits the successful conversion lifecycle diagnostics `ATM003` through
  `ATM009` (including exact model and artifact counts), emits `ATM010` on
  conversion failure, and clears logger state from `clear()`. The tests-first
  BNG3 port is `16fee366755b73a4691d6c854e901471f8399b1c` in
  `python/bionetgen/atomizer/modern/__init__.py` and
  `tests/python/test_modern_atomizer.py`. The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -q -k lifecycle_diagnostics` reported
  `1 failed, 43 deselected` because the expected ATM messages were absent; the
  repaired command reports `1 passed, 43 deselected`. The modern Atomizer glob
  reports `90 passed`; the full Python gate reports `265 passed, 27 skipped, 9
  warnings`; Ruff passes; Black reports the two changed files unchanged; and
  exact-tree `ctest --test-dir build --output-on-failure` reports `185/185`.
  The native `build/cpp/bng_cpp` artifact is unchanged at SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `16fee366755b73a4691d6c854e901471f8399b1c`; hosted CI run
  [33593502778](https://github.com/RuleWorld/BNG3/actions/runs/33593502778),
  CodeQL run
  [33593502821](https://github.com/RuleWorld/BNG3/actions/runs/33593502821),
  and formatting run
  [33593502779](https://github.com/RuleWorld/BNG3/actions/runs/33593502779)
  were queued when read back. This closes only the facade's logger side
  effects: `AtomizerResult.log` remains the existing `List[str]` compatibility
  field rather than source `LogMessage[]`, and BNG3's synchronous parser has no
  source `initialize()`/`ATM001`-`ATM002` lifecycle; broader Atomizer
  parser/writer/SBML and independent parity gaps remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:1529-1534` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` emits the `SBM004`
  parsed-model summary before returning the structured model. The tests-first
  BNG3 port is `6b4e96182ab9032bc61ee58c42afbda3bfed9bfb` in
  `python/bionetgen/atomizer/modern/parser.py`; the red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -q -k parser_reports_model_summary`
  reported `1 failed, 44 deselected, 2 warnings` because no summary was
  logged, and the repaired command reported `1 passed, 44 deselected, 1
  warning`. The following modern Atomizer suite reports `91 passed`; the full
  Python gate reports `266 passed, 27 skipped, 9 warnings`; Ruff and Black
  pass; and exact-tree `ctest --test-dir build --output-on-failure` reports
  `185/185`. The native `build/cpp/bng_cpp` artifact remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public checkpoint readback is `6b4e96182ab9032bc61ee58c42afbda3bfed9bfb`;
  CI [33593884993](https://github.com/RuleWorld/BNG3/actions/runs/33593884993),
  CodeQL [33593884974](https://github.com/RuleWorld/BNG3/actions/runs/33593884974),
  and formatting [33593884986](https://github.com/RuleWorld/BNG3/actions/runs/33593884986)
  were queued. This closes only the parser summary diagnostic; parser
  extraction parity and independent SBML/BNGL parity remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:1531-1534` at the
  same pinned reference maps import-warning severities to `SBM020` dropped,
  `SBM021` approximated, and `SBM022` informational diagnostics, preserving
  category brackets and repeated-warning counts. The tests-first BNG3 port is
  `6476e4271edb652f5dee8bbe03f2df9fdd5543dd`; its red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -q -k parser_emits_import_warning_codes_and_counts`
  reported `1 failed, 45 deselected, 2 warnings`, and the repaired command
  reported `1 passed, 45 deselected, 1 warning`. The modern suite then reports
  `92 passed`; the full Python gate reports `267 passed, 27 skipped, 9
  warnings`; Ruff and Black pass; and CTest remains `185/185`. Exact public
  head readback is `6476e4271edb652f5dee8bbe03f2df9fdd5543dd`; CI
  [33594023815](https://github.com/RuleWorld/BNG3/actions/runs/33594023815),
  CodeQL [33594023785](https://github.com/RuleWorld/BNG3/actions/runs/33594023785),
  and formatting [33594023819](https://github.com/RuleWorld/BNG3/actions/runs/33594023819)
  were queued. This closes only diagnostic severity/count mapping; parser
  semantics and independent oracle coverage remain open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:58-76,3365-3369`
  at the pinned reference reports `BNW011` when an eligible reaction has no
  kinetic law, applies the documented fallback rate, and bounds repeated
  logs. The tests-first BNG3 port is
  `78430997d4f828bd8c92e7f9806c0553bbbc43a2` in
  `python/bionetgen/atomizer/modern/writer.py`; the red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -q -k reports_missing_kinetic_laws`
  reported `1 failed, 46 deselected, 2 warnings`, and the repaired command
  reported `1 passed, 46 deselected, 1 warning`. The modern suite reports `93
  passed`; the full Python gate reports `268 passed, 27 skipped, 9 warnings`;
  Ruff and Black pass; CTest reports `185/185`; and the native artifact remains
  SHA-256 `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public head readback is `78430997d4f828bd8c92e7f9806c0553bbbc43a2`;
  CI [33594217262](https://github.com/RuleWorld/BNG3/actions/runs/33594217262),
  CodeQL [33594217315](https://github.com/RuleWorld/BNG3/actions/runs/33594217315),
  and formatting [33594217279](https://github.com/RuleWorld/BNG3/actions/runs/33594217279)
  were queued. This closes only missing-kinetic-law observability and does not
  establish a scientifically validated fallback-rate policy for all models.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:2280-2284` at the
  pinned reference emits `BNW012` when non-species rate-rule targets are
  materialized as synthetic state species. The tests-first BNG3 port is
  `7166ef8b45c1a1ffefe6a3e8528f8bddd059daab`; the red-first focused command
  reported `1 failed, 46 deselected, 2 warnings` with the synthetic species
  present but no diagnostic, and the repaired command reported `1 passed, 46
  deselected, 1 warning`. The modern suite reports `93 passed`; the full
  Python gate reports `268 passed, 27 skipped, 9 warnings`; Ruff and Black
  pass; CTest reports `185/185`; and exact public head readback is
  `7166ef8b45c1a1ffefe6a3e8528f8bddd059daab`. Hosted CI
  [33594335170](https://github.com/RuleWorld/BNG3/actions/runs/33594335170),
  CodeQL [33594335190](https://github.com/RuleWorld/BNG3/actions/runs/33594335190),
  and formatting [33594335172](https://github.com/RuleWorld/BNG3/actions/runs/33594335172)
  were queued. This closes only the synthetic-rate-rule diagnostic; the
  full rate-rule execution and independent parity gates remain open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:60-67,1639-1649,
  1737-1740,3774-3777` at the pinned reference reports `BNW004` for
  non-adjacent-compartment transport, bounded by the source log limit, while
  adjacent transport remains quiet. The tests-first BNG3 port is
  `a19d1ccdea7b698709c708d8716998fedfd20f7a`; the red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -q -k reports_nonadjacent_transport_reactions`
  reported `1 failed, 47 deselected, 2 warnings`, and the repaired command
  reported `1 passed, 47 deselected, 1 warning`. The modern suite reports `94
  passed`; the full Python gate reports `269 passed, 27 skipped, 9 warnings`;
  Ruff and Black pass; CTest reports `185/185`; and the native artifact remains
  SHA-256 `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public head readback is `a19d1ccdea7b698709c708d8716998fedfd20f7a`;
  CI [33594536507](https://github.com/RuleWorld/BNG3/actions/runs/33594536507),
  CodeQL [33594536494](https://github.com/RuleWorld/BNG3/actions/runs/33594536494),
  and formatting [33594536626](https://github.com/RuleWorld/BNG3/actions/runs/33594536626)
  were queued. This closes only non-adjacent transport observability; transport
  dynamics, all writer parity, and independent SBML/BNGL parity remain open.
- [x] Playground `src/lib/atomizer/index.ts:105-124,208-274` at the pinned
  reference enables the flat-only large-model fast path when
  `ATOMIZER_LARGE_FASTPATH` is enabled and any of the source thresholds
  (`1500` species, `800` reactions, or `5000000` SBML characters) is reached;
  it emits `ATM011` and creates one elemental molecule/seed per SBML species,
  deliberately bypassing structure inference. The tests-first BNG3 port is
  `a288a235fd7d2c1a317d2db8fe2e3e01f695cb70` in
  `python/bionetgen/atomizer/modern/__init__.py` and
  `tests/python/test_modern_atomizer.py`. The threshold-forced red-first
  command `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -k large_flat_fast_path -q` reported
  `1 failed, 48 deselected` because the normal SCT path emitted `ATM005`
  instead of `ATM011`; the repaired command reported `1 passed, 48
  deselected`. The complete modern Atomizer gate reports `95 passed`; the full
  Python gate reports `270 passed, 27 skipped, 8 warnings`; Ruff and Black
  pass; exact-tree CTest reports `185/185`; and the native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `a288a235fd7d2c1a317d2db8fe2e3e01f695cb70`; hosted CI
  [33595341449](https://github.com/RuleWorld/BNG3/actions/runs/33595341449),
  CodeQL [33595341429](https://github.com/RuleWorld/BNG3/actions/runs/33595341429),
  and formatting [33595341400](https://github.com/RuleWorld/BNG3/actions/runs/33595341400)
  were queued, while `gh pr checks 2` still reports pending jobs. This closes
  only the source-shaped flat fast path. It deliberately does not claim large-
  model speedup, structure-inference parity, annotation parity, or release
  qualification; the broad Atomizer, API, SBML, Multi, NFsim, provenance,
  packaging, and hosted terminal gates remain open.
- [x] Playground `src/lib/atomizer/parser/bngXmlParser.ts:294-315` at the
  pinned reference emits `BNGXML002` when the BNG-SBML fallback rescales an
  MM/Sat constant for a compartment and emits `BNGXML001` after conversion.
  The tests-first BNG3 port is
  `d288387395d9537be7bd93933c79dbb112d6a9fc` in
  `python/bionetgen/atomizer/modern/bng_xml.py` and
  `tests/python/test_modern_atomizer_annotations.py`. The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_annotations.py -k reports_source_diagnostics -q`
  reported `1 failed, 8 deselected, 1 warning` because both source diagnostics
  were absent; the repaired command reported `1 passed, 8 deselected`. The
  complete modern Atomizer gate reports `96 passed`; the full Python gate
  reports `271 passed, 27 skipped, 8 warnings`; Ruff and Black pass; exact-tree
  CTest reports `185/185`; and `build/cpp/bng_cpp` remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `d288387395d9537be7bd93933c79dbb112d6a9fc`; hosted CI
  [33595883009](https://github.com/RuleWorld/BNG3/actions/runs/33595883009),
  CodeQL [33595882979](https://github.com/RuleWorld/BNG3/actions/runs/33595882979),
  and formatting [33595882989](https://github.com/RuleWorld/BNG3/actions/runs/33595882989)
  were queued. This closes only fallback-converter observability; BNG-XML
  semantic round trips, schema validation, and independent format parity remain
  open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:3321-3647` and
  `3683-3864` at the pinned reference preserve a reversible SBML net rate as
  one irreversible functional rule when reactant neutralization would corrupt
  a saturation-like denominator (`split_rxn` fallback). The tests-first BNG3
  port is `29b7687a1c49617715cacba1e0985e7b8568d5b9` in
  `python/bionetgen/atomizer/modern/writer.py`, with the source-derived
  regression `tests/python/test_modern_atomizer.py::test_playground_writer_falls_back_for_unsplittable_reversible_nonlinear_rate`.
  The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer.py -k
  unsplittable_reversible_nonlinear_rate -q` reported `1 failed, 49
  deselected, 2 warnings` because BNG3 emitted `<->` and stripped the
  denominator-sensitive direction; the repaired command reported `1 passed,
  49 deselected, 1 warning` and retained the full net expression on `->`. The
  complete modern Atomizer gate reports `97 passed`; the full Python gate
  reports `272 passed, 27 skipped, 8 warnings`; Ruff and Black pass; exact-tree
  CTest reports `185/185`; provenance and corpus-manifest checks pass with the
  baseline still pending maintainer approval; the exception ledger reports
  `0 active`; and validation smoke reports `4 passed, 15 skipped`. The native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `29b7687a1c49617715cacba1e0985e7b8568d5b9`; hosted CI
  [33596704800](https://github.com/RuleWorld/BNG3/actions/runs/33596704800),
  CodeQL [33596704673](https://github.com/RuleWorld/BNG3/actions/runs/33596704673),
  and formatting [33596704771](https://github.com/RuleWorld/BNG3/actions/runs/33596704771)
  were queued. This closes only the source-shaped reversible-rate fallback;
  broader writer/parser/SBML and independent parity remain open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:1316-1385` at the
  pinned reference inlines calls to proven constant zero-argument functions so
  BNG2's function-block reordering cannot leave a dynamic function dependent on
  a later constant definition. The tests-first BNG3 port is
  `e847eaa89aae8bc6421be78f93fa261709b2cb9d` in
  `python/bionetgen/atomizer/modern/writer.py`; the source-derived regression
  is `tests/python/test_modern_atomizer_writer_parameters.py::test_write_functions_inlines_constant_calls_into_dynamic_bodies`.
  The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_writer_parameters.py -k constant_calls -q`
  reported `1 failed, 5 deselected, 2 warnings`; the repaired command reported
  `1 passed, 5 deselected, 1 warning`. The focused writer/helper gate reports
  `14 passed`; the complete modern Atomizer gate reports `98 passed`; the full
  Python gate reports `273 passed, 27 skipped, 9 warnings`; Ruff and Black pass;
  exact-tree CTest reports `185/185`; provenance and corpus-manifest checks pass
  with the baseline still pending maintainer approval; the exception ledger
  reports `0 active`; and validation smoke reports `4 passed, 15 skipped, 175
  deselected`. The native `build/cpp/bng_cpp` artifact remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `e847eaa89aae8bc6421be78f93fa261709b2cb9d`; hosted CI
  [33597684992](https://github.com/RuleWorld/BNG3/actions/runs/33597684992),
  CodeQL [33597685061](https://github.com/RuleWorld/BNG3/actions/runs/33597685061),
  and formatting [33597685018](https://github.com/RuleWorld/BNG3/actions/runs/33597685018)
  are queued. This closes only the source-shaped BNG2 function-ordering
  workaround; broad writer/parser/SBML parity and independent validation
  remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:348-371` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` recognizes saturation-like
  reaction rates only for explicit `Sat`/`MM`/`Hill` terms or the source's
  quotient-plus-two-products shape. The tests-first BNG3 repair is
  `6f7573f40ff04cfaed517bbcd11c606eeca7cb87` in
  `python/bionetgen/atomizer/modern/core.py`, with the source-derived
  regression `tests/python/test_modern_atomizer_core.py::test_reaction_classification_requires_reference_saturation_shape`.
  The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_core.py -k reference_saturation_shape -q`
  reported `1 failed, 7 deselected`; the repaired command reported `1 passed,
  7 deselected`. The focused core gate reports `8 passed`; the complete modern
  Atomizer gate reports `99 passed`; the full Python gate reports `274 passed,
  27 skipped, 9 warnings`; Ruff and Black pass; the native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `6f7573f40ff04cfaed517bbcd11c606eeca7cb87`; hosted CI
  [33629097334](https://github.com/RuleWorld/BNG3/actions/runs/33629097334),
  CodeQL [33629097260](https://github.com/RuleWorld/BNG3/actions/runs/33629097260),
  and formatting
  [33629097206](https://github.com/RuleWorld/BNG3/actions/runs/33629097206)
  are queued. This closes only the source-shaped saturation classifier
  guard; broader Atomizer core/writer/parser/SBML, direct-NFsim, and
  independent parity remain open.
- [x] Playground `src/lib/atomizer/utils/helpers.ts:543-545` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` emits the source's fixed
  `2.302585093` denominator for `log10(x)` conversion. The tests-first BNG3
  repair is `5ad75244662278f18485864352fd104698115a74` in
  `python/bionetgen/atomizer/modern/helpers.py`, with the source-derived
  contract in `tests/python/test_modern_atomizer_helpers.py::test_playground_helpers_string_and_math_contract`.
  The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_helpers.py -k string_and_math -q`
  reported `1 failed, 3 deselected`; the repaired command reported `1 passed,
  3 deselected`. The focused helper gate reports `4 passed`; the complete
  modern Atomizer gate reports `99
  passed`; the full Python gate reports `274 passed, 27 skipped, 9 warnings`;
  Ruff and Black pass. Exact public PR/ref head readback is
  `5ad75244662278f18485864352fd104698115a74`; hosted CI
  [33629555826](https://github.com/RuleWorld/BNG3/actions/runs/33629555826),
  CodeQL [33629555887](https://github.com/RuleWorld/BNG3/actions/runs/33629555887),
  and formatting
  [33629555830](https://github.com/RuleWorld/BNG3/actions/runs/33629555830)
  are queued. This closes only the source-shaped `log10` spelling; broader
  expression, Atomizer, SBML, and independent parity remain open.
- [x] Playground `src/lib/atomizer/core/structures.ts:752-765` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` deletes bonds from the selected
  molecule's component whose name matches the other supplied pair member,
  case-insensitively. The tests-first BNG3 repair is
  `167d6b8ab4ca6f8c709a5ab6cb894317b2f24272` in
  `python/bionetgen/atomizer/modern/structures.py`, with the source-derived
  regression `tests/python/test_modern_atomizer_structures.py::test_delete_bond_matches_playground_component_pair_semantics`.
  The red-first command
  `PYTHONPATH=build/cpp:python python -m pytest
  tests/python/test_modern_atomizer_structures.py -k delete_bond -q` reported
  `1 failed, 4 deselected, 2 warnings`; the repaired command reported `5
  passed` for the focused structures file. The complete modern Atomizer gate
  reports `100 passed`; the full Python gate reports `275 passed, 27 skipped,
  9 warnings`; Ruff and Black pass. The native `build/cpp/bng_cpp` artifact
  remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `167d6b8ab4ca6f8c709a5ab6cb894317b2f24272`; hosted CI
  [33630013174](https://github.com/RuleWorld/BNG3/actions/runs/33630013174),
  CodeQL [33630013218](https://github.com/RuleWorld/BNG3/actions/runs/33630013218),
  and formatting
  [33630013175](https://github.com/RuleWorld/BNG3/actions/runs/33630013175)
  are queued. This closes only the source-shaped component-pair helper;
  broader structure, parser/writer/SBML, direct-NFsim, and independent parity
  remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:1338-1348` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` uses nullish presence semantics
  for `initialAmountSet` and `initialConcentrationSet`: an explicit `false`
  suppresses the corresponding value, while an unavailable flag falls back to
  a non-zero parsed value. The tests-first BNG3 port is
  `27ae8d63e5cef1a1af005b2e567a6ad5447e5f28` in
  `python/bionetgen/atomizer/modern/types.py` and
  `python/bionetgen/atomizer/modern/core.py`, with the source-derived
  regression `tests/python/test_modern_atomizer.py::test_playground_seed_selection_honors_explicit_unset_initial_values`.
  The red-first command
  `env PYTHONPATH=python pytest -q tests/python/test_modern_atomizer.py -k explicit_unset_initial_values`
  reported `1 failed, 50 deselected` after checkout import resolution; the
  repaired command reported `1 passed, 50 deselected`. The complete modern
  Atomizer gate reports `83 passed, 18 skipped`; the full Python gate reports
  `276 passed, 27 skipped, 9 warnings` with `PYTHONPATH=python:build/cpp`;
  root Release/Ninja CTest reports `185/185`; Ruff and Black pass; and
  `build/cpp/bng_cpp` remains SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Exact public PR/ref head readback is
  `27ae8d63e5cef1a1af005b2e567a6ad5447e5f28`; hosted CI
  [33631116459](https://github.com/RuleWorld/BNG3/actions/runs/33631116459),
  CodeQL [33631116350](https://github.com/RuleWorld/BNG3/actions/runs/33631116350),
  and formatting
  [33631116335](https://github.com/RuleWorld/BNG3/actions/runs/33631116335)
  remain queued. The no-extension full-Python invocation is not a valid
  completion gate because it reports the known missing native backend; this
  closes only seed-value presence semantics, while broader parser/writer/SBML,
  direct-NFsim, provenance, and release parity remain open.
- [x] Fresh external-Perl Tier-P NET parity at semantic head `88f4e54` used
  `BNG2_PERL=/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl` from source
  revision `fde0cd6a522c9f988d5495db31c70ce0f98e744b`. The exact command
  selected 100 tests and completed `54 passed, 46 skipped, 94 deselected` in
  `125.70s`, with no assertion failures. The 46 skips are still honest
  oracle/asset/environment gaps (including legacy syntax, missing NFsim,
  missing test data, and the sandbox's blocked `ps`), so this is an improved
  external subset result, not complete Tier-P qualification.
- [x] Fresh selected Tier-NF native-oracle evidence at semantic head `88f4e54`
  used the independent binary `/Users/akutuva/Documents/BioNetGen/nfsim/build/NFsim`
  from source checkout `a6f9fa945c9d6e1e122e789c952260112c93f157`, SHA-256
  `7302fe29b16d1ebe86369f752f2a49d2c87ef16539faaec11b82294a9fa56d22`.
  The full selected command completed `10 passed, 184 deselected, 3 warnings`
  in `175.92s`; direct/XML shadow-only selection separately completed
  `4 passed, 190 deselected, 3 warnings` in `4.87s`. This qualifies the
  selected four-model subset only; full Tier-NF corpus and three-way evidence
  remain open.
- [x] An independent accepted-cutoff NFsim oracle was built from source
  revision `3b046fc1b9f76719d92be22279b24992cdae7c35` in the isolated
  worktree `/private/tmp/bng3-nfsim-3b046` with Release/Ninja, executable-only,
  and LTO-disabled settings. The exact configure/build recipe was
  `cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
  -DNFSIM_BUILD_EXECUTABLE=ON -DNFSIM_BUILD_LIBRARY=OFF
  -DNFSIM_ENABLE_LTO=OFF` followed by `cmake --build build --parallel 4`;
  the build completed at `[92/92] Linking CXX executable NFsim` with only
  pre-existing legacy muParser/C++11 warnings. Using that binary as
  `NFSIM_BIN` against the BNG3 semantic checkpoint `7977966` (the current
  public `b82e08c` adds documentation only), the exact selected NF command
  completed `10 passed, 184 deselected, 3 warnings` in `138.03s`. This is
  independent accepted-cutoff evidence for the selected validation slice;
  it does not close the full Tier-NF corpus, distributional gate, broader
  direct-NFsim parity, or energy/provenance qualification.
- [x] Fresh selected Tier-NF independent evidence at semantic head
  `871d261442be2f4808cbcabed51f6a017ba5488a` used the accepted-cutoff source
  revision `3b046fc1b9f76719d92be22279b24992cdae7c35` and binary
  `/private/tmp/bng3-nfsim-3b046/build/NFsim` (SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`). The
  exact command
  `env NFSIM_BIN=/private/tmp/bng3-nfsim-3b046/build/NFsim BNG_CPP=/Users/akutuva/Documents/BioNetGen/BNG3/build/cpp/bng_cpp PYTHONPATH=python:build/cpp python -m pytest tests/validation -m nf -q`
  completed `10 passed, 184 deselected, 3 warnings` in `135.81s`. It covers
  the selected `localfunc`, `motor`, `simple_system`, and `tlbr` native
  ensembles, direct/XML shadow checks, and fixed-seed endpoint checks. The
  three warnings are the known zero-denominator invalid-divide diagnostic at
  `tests/validation/compare.py:1278` for the affected localfunc/motor/
  simple_system comparisons. This qualifies the selected slice only; full
  Tier-NF, broader direct-NFsim three-way parity, and energy/provenance gates
  remain open.
- [x] The full NFsim AST adapter executable passes 118 test cases and 1280
  assertions on `2c498af`. It covers compact energy evaluation, cached compact
  rate factors, specialized reverse propensities, sparse selector ordering,
  cached single- and multi-term Arrhenius factors, direct-product endpoint
  identity propagation, safe direct-product traversal, cached pre-fire binding
  rejection, compact partner mapping-slot compaction, indexed cross-type
  partner refresh, shared partner-pool updates, dense and sparse type-invariant
  membership decisions, deferred weighted-side propensity capture,
  endpoint-refined membership refresh decisions, compact sorted and inline
  reaction-membership IDs, connected t3 trajectory
  parity, materialized fallback,
  all-forward compact partner-pool refresh early return,
  pure-context homodimer/trimer/scaffold counting,
  transformed homodimer binding multiplicity, and pure DOR context counting.
  It also covers the source-derived functional symmetry/TotalRate correction,
  repeated connectivity direct-endpoint scratch refresh with lazy connectivity
  product lookup allocation, and one-way direct
  Arrhenius binding/state-change expansion including the compact forward-only
  runtime path, the source-derived bulk molecule-pool reuse regression, and
  source-derived multi-bond product-molecularity checks on direct and XML
  paths, including a negative single-bond ring control. It also covers the
  source-derived NFsim `t3.xml` LocalFunction XML contract: a plain scoped
  local-function reaction rate is serialized through a generated composite
  wrapper, while a nested CompositeFunction remains direct (5 assertions).
  It also covers the
  source-derived `reactant_1()` compatibility placeholder and dynamic
  reactant-count rate on direct and in-memory XML paths (11 assertions), plus
  XML preservation of the `TotalRate` modifier (9 assertions), and the IfTest
  conditional global functions with legacy `&&` expressions and live-threshold
  trajectory branch semantics on direct and XML paths (74 assertions). It also
  covers BNG2 inferred integer-state handling for wildcard/PLUS/MINUS tokens,
  lexical molecule-type registration, canonical inferred component order, and
  direct/XML/BNGL writer order. It also covers the source-derived NFsim Issue86
  species-observable dependency refresh: after one `A()` degradation, both
  `Species` and `Molecules` observables and their dependent propensities update
  from 100 to 99. It also covers the source-derived NFsim Issue78 absolute
  clock/equilibrate contract: a nonzero current time is preserved across
  equilibration and a time-backed rate observes that absolute origin.
- [x] The accepted NFsim EnergyFunction unit contract from source commit
  `f63d676` is covered at `9378000` by 22 assertions: pattern storage,
  binding expansion, state-change expansion, forward/reverse names and
  rates, and the expected ΔG values. This is a local source-derived unit
  gate, not independent native-NFsim parity.
- [ ] The source-derived historical NFsim `test/testSuite/t4.bngl` and related
  `t5.bngl` syntax remain open capability gaps. At semantic parent `7186b65`,
  BNG3's parser
  rejects the t4 fixture with the stable diagnostic `Cannot build model from
  source with syntax errors`. Independent inspection found the fixtures were
  introduced by NFsim commit `3c7b6a3` as preliminary tests, current BNG2
  rejects `sum(m)`, and the current NFsim `StateCounter` implementation is
  retained debug/dead support rather than an active parser/XML contract.
  Do not mark this row complete without a maintainer disposition, active
  independent oracle, canonical-AST design, runtime semantics, and direct/XML
  contract tests.
- [x] The full NFsim tree/system executable passes 157 assertions in 8 test
  cases on `7186b65`. This includes the source-derived unsafe output-name
  rejection port from NFsim `3527edb` and continuous-vs-chunked `stepTo`
  checkpoint tests from NFsim `e3ef4a0` (50 assertions across the two new
  cases, including the zero-propensity boundary).
- [x] Full Python/API tests pass on the latest Python-affecting checkpoint
  `9c60ca4`: `235 passed, 27 skipped, 8 warnings` from
  `PYTHONPATH=python:build/cpp python -m pytest tests/python -q`. The later
  `73757ea`, `2d69b99`, `d502e47`, and `4ea7157` checkpoints change only C++
  internals and have been
  requalified by targeted native C++ gates; rerun the full Python suite on the
  final candidate.
  The installed-wheel target still has only historical evidence and is not
  release evidence for this head.
- [x] Source-derived NFsim Issue78 coverage is green at `7186b65`: the direct
  Python API and `simulate_nf` action both preserve output times
  `[100, 101, 102]` and evaluate `time()`-backed synthesis from the absolute
  start, while the CLI accepts a nonzero NF `--t-start`; the C++ equilibrate
  test verifies duration-based equilibration from a nonzero current clock.
  These are targeted local contracts, not independent native-NFsim parity.
- [x] The exact NFsim `IfTest/ifTest.bngl` source fixture now parses through
  `build/cpp/bng_cpp --check` on `7186b65`, including its empty `reactant_1()`
  placeholder declaration; parser acceptance is not execution parity.
- [x] The independent native-NFsim stochastic subset was rerun against the
  absolute native binary `/Users/akutuva/Documents/BioNetGen/nfsim/build/NFsim`
  (binary SHA-256
  `7302fe29b16d1ebe86369f752f2a49d2c87ef16539faaec11b82294a9fa56d22`) with
  `NFSIM_BIN` set to that absolute path. The `motor` and `tlbr` Tier-NF
  ensemble cases passed the declared 200-run gate, the direct/XML shadow
  cases passed, and the fixed-seed direct endpoint cases passed:
  `6 passed, 4 deselected, 6 warnings` in 131.87 seconds at `7186b65`.
  This is subset evidence only; it does not close the full Tier-NF gate.
- [x] The C++-unchanged native checkpoint `c754544` passes the four-model local Tier-NF
  200-run gate (`simple_system`, `tlbr`, `motor`, `localfunc`) against the
  independently built native binary: `4 passed, 6 deselected, 5 warnings` in
  168.62 seconds. Its direct-vs-in-memory-XML shadow suite passes `4 passed,
  6 deselected, 8 warnings` in 4.17 seconds. The focused localfunc XML output
  is also accepted by that native binary; the focused native test passes
  `1 passed, 9 deselected, 5 warnings`. These are current subset/checkpoint
  results, not full approved Tier-NF or three-way parity evidence.
- [x] The source-derived NFsim Issue86 species-observable refresh test remains
  green in the full current AST adapter run at `9378000` (13 assertions).
  The independent native-NFsim cross-check on a reduced fixture derived from
  `nfsim/test/Issue86/issue86.bngl` (seed `1`, `t_end=0.1`, 20 output
  intervals, 4 observables) is historical evidence from `852793f`, producing
  exact direct/native results at all 21 checkpoints; it has not been rerun
  after the Issue78-only change. This closes only the targeted
  dependency-refresh regression; broader direct-NFsim, protocol, and
  three-way evidence remains open.
- [x] The validation harness now fails closed when `NFSIM_BIN` is missing or
  invalid instead of silently selecting BNG3's embedded `build/cpp/NFsim`.
  Source-derived path tests pass `5 passed, 1 skipped` in
  `tests/validation/test_harness_paths.py`; the skip is the intentionally
  absent local explicit oracle after the repair. The exact repair is
  `b13fe23`; use an absolute independently built native path for claimed
  parity.
- [x] Exact-head local CI workflow contract tests pass 7/7 on `9a2475a`,
  including the pull-request source-distribution smoke gate and the contract
  that PR-head concurrency preserves in-flight hosted evidence.
- [x] Source-derived Playground Atomizer `Species.extend` coverage passes
  `4 passed, 34 deselected` in
  `tests/python/test_modern_atomizer.py -k species_extend` after the expected
  red-first run. The implementation is in
  `python/bionetgen/atomizer/modern/structures.py` and follows the reference
  branch `src/lib/atomizer/core/structures.ts:637-672`.
- [x] Local canonical Black check passes: `177 files would be left unchanged`
  under `black --check --diff --target-version py312 python/ tests/python/
  scripts/` (Jupyter files are skipped because optional Jupyter dependencies
  are absent); Ruff and git diff checks pass. The broader ad hoc check that
  included `tests/validation/` remains red on pre-existing formatting drift
  and is not the hosted CI command.
- [x] Local validation smoke on current semantic head `7186b65` reports 4
  passed, 15 skipped, and 174 deselected. The remaining skips are visible
  `run_network`/reference-oracle gaps, with sandbox process-inspection noise
  also present, and must not be treated as parity.
- [x] Current local validation smoke at BNG3 semantic head
  `19a90ed83fad4529bb8e85e1a538e00ade274cb2` used
  `PYTHONPATH=build/cpp:python python -m pytest -c tests/validation/pytest.ini
  tests/validation -m smoke --bng-cpp build/cpp/bng_cpp -q` and reports `4
  passed, 15 skipped, 175 deselected, 1 warning` in 8.07 seconds. The local
  `build/cpp/bng_cpp` artifact has SHA-256
  `8e80832c8a347a303fcfb21fa8c4c35a98b13ffd8967cc9192f964784287a7f3`.
  Skips remain explicit missing-reference/legacy-oracle and sandbox
  `run_network`/process-inspection gaps; this is smoke evidence only, not
  complete parity evidence.
- [x] Non-strict provenance, corpus-manifest, generated-manifest, and exception
  ledger checks pass. The strict provenance gate remains intentionally red with
  10 pending source/oracle/compiler/Python-lock approval errors; the exception
  ledger itself is valid with 0 active entries under the CI budget check.
- [x] Fresh provenance-spine audit at semantic head
  `871d261442be2f4808cbcabed51f6a017ba5488a` and public checklist head
  `e95fe022292339c82d29fb9a22d73ea8dab9f9ed` used the exact commands
  `python scripts/validate_provenance.py`,
  `python scripts/validate_corpus_manifest.py`,
  `python scripts/generate_corpus_manifest.py --check`, and
  `python -m tests.validation.exception_ledger --max-exceptions 1`. They
  reported `provenance validation passed: 1 source lock, 0 ledger(s)`,
  `corpus manifest validation passed: 100 model(s)`, `corpus manifest is
  current`, and `exception ledger valid: 0 active`. The baseline remains
  pending maintainer approval. The corresponding strict command
  `python scripts/validate_provenance.py --require-approved` still fails with
  exactly 10 approval/lock errors for the baseline, five sources, two oracles,
  compiler images, and the Python lock; this is a governance blocker, not a
  silently accepted pass.
- [x] Fresh external-Perl Tier-P network parity at semantic head
  `871d261442be2f4808cbcabed51f6a017ba5488a` used
  `BNG2_PERL=/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl` from source
  revision `fde0cd6a522c9f988d5495db31c70ce0f98e744b` and the exact command
  `env BNG2_PERL=/private/tmp/bng2-oracle.TToh58/source/bng2/BNG2.pl NFSIM_BIN=/private/tmp/bng3-nfsim-3b046/build/NFsim PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m "parity and not slow" --bng-cpp build/cpp/bng_cpp -q`.
  It completed `54 passed, 46 skipped, 94 deselected` in `103.14s`. The skips
  remain explicit BNG2 fixture failures or missing references/support assets,
  including legacy syntax, missing NFsim/run_network support, and the sandbox
  `ps` restriction; they are not parity passes. The current exception ledger
  is empty, so these remain environment/capability limitations rather than
  silently admitted expected failures.
- [x] Fresh export-format validation at the same semantic head used
  `PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini
  tests/validation -m export --bng-cpp build/cpp/bng_cpp -q` and completed
  `12 passed, 182 deselected` in `12.18s`. This is export-format evidence only;
  SBML-Multi, broader writer parity, and release qualification remain open.
- [x] Historical package evidence: a no-build-isolation sdist and wheel were
  rebuilt from semantic checkpoint `ba52c20` and the wheel was installed into
  an isolated target. These artifact digests and installed-wheel test results
  are not current release evidence for 6b953c5.
  Artifact SHA-256 digests are
  `7ce09d700a5ff8fc42982c71eeaa448873811d4f3a10464bb67a8aac728a8780`
  (sdist) and
  `419bb2bd29f319bfc638c50b9c29cec0934b6d87eb7ce8fcdefed70a01f618c2`
  (CPython 3.14 arm64 wheel); the installed-target Python suite is recorded
  above.
- [ ] Superseded hosted checks for semantic head `c754544` were not terminal
  as one set: [CI run
  33531304777](https://github.com/RuleWorld/BNG3/actions/runs/33531304777) was
  cancelled, [CodeQL run
  33531304750](https://github.com/RuleWorld/BNG3/actions/runs/33531304750)
  was still in progress at the last readback, and [formatting run
  33531304766](https://github.com/RuleWorld/BNG3/actions/runs/33531304766) had
  passed. These runs do not qualify the current repair.
- [ ] Historical exact public semantic code checkpoint `73757ea` had hosted
  evidence beginning with [CI run
  33539030113](https://github.com/RuleWorld/BNG3/actions/runs/33539030113),
  [CodeQL run
  33539030155](https://github.com/RuleWorld/BNG3/actions/runs/33539030155),
  and [formatting run
  33539030353](https://github.com/RuleWorld/BNG3/actions/runs/33539030353).
  All three were queued at readback. Queued or partial results are not
  completion evidence for any later head.
- [x] Historical hosted PR checks for semantic head
  `0f833470950fc47329f5b7381c64533e623b45ce` were terminal-success: [CI run
  33493581633](https://github.com/RuleWorld/BNG3/actions/runs/33493581633)
  completed all required C++, Python, ASan, integration, validation, lint,
  package-smoke, and parse-inventory jobs successfully; release-only Docker,
  source-distribution, wheel, and publication jobs were skipped by the pull
  request event. [CodeQL run
  33493581605](https://github.com/RuleWorld/BNG3/actions/runs/33493581605)
  passed both C++ and Python analysis, and [formatting run
  33493581573](https://github.com/RuleWorld/BNG3/actions/runs/33493581573)
  passed. Results were read back with `gh` against the exact public head;
- [x] Historical readback before the later refresh: `gh api
  repos/RuleWorld/BNG3/git/ref/heads/codex/bng3-integration-foundations` and
  `gh pr view 2 --repo RuleWorld/BNG3` read back the same full public code
  checkpoint SHA `73757ead732156f5d4b1a0f9a50901263631a93f`; PR #2 was open.
- [x] Modern Atomizer checkpoints exist for annotations, BNG-XML conversion,
  Rulifier, UniProt, structure helpers, and conservative SBML-Multi discovery,
  helper/rate-rule constants, each with source-derived tests.
- [ ] The release candidate has independent oracle, provenance-complete
  golden, full parity, direct-NFsim, SBML-Multi, legacy, installed-package,
  and release-artifact evidence.

## 1. Authority, ownership, and source reconciliation

### 1.1 Accepted source baseline

- [ ] Maintainers choose exact accepted source cutoffs for BNG3, BioNetGen,
  NFsim, PyBioNetGen, and RuleHub.
- [ ] provenance/upstreams.lock.yml changes from observed/pending status to an
  approved baseline only after the decisions are recorded.
- [ ] The lock records repository URL, branch/tag, exact revision, observation
  date, role, license/provenance note, and the reason for selecting the cutoff.
- [ ] The supported Python, compiler, operating-system, architecture, and
  dependency matrix is approved and recorded.
- [ ] Public PyBioNetGen imports, result objects, CLI forms, defaults,
  warnings, exceptions, and file behaviors are classified as supported,
  deprecated, or intentionally private.
- [ ] The sanctioned BIONETGEN_USE_PERL=1 compatibility mode is classified as
  a release feature or developer-only oracle path.
- [ ] Numerical tolerances, stochastic acceptance statistics, seed policy,
  solver versions, and review owners are approved.

### 1.2 Ownership and decisions

- [ ] Every capability-matrix row has an owner, source path/revision,
  implementation path, regression fixture, independent oracle, and acceptance
  gate.
- [ ] CODEOWNERS or equivalent ownership exists for parser/AST, graph/network,
  NFsim, expressions/solvers, Atomizer/SBML, Python/packaging,
  CI/release/provenance, and documentation/compatibility policy.
- [ ] Architecture decisions are recorded for canonical AST boundaries, graph
  identity, expression evaluation, direct NFsim lifecycle, writer ownership,
  public API compatibility, and legacy retirement.
- [ ] Maintainer decisions in Section 12 of BNG3_INTEGRATION_PLAN.md are
  recorded before release qualification.

### 1.3 Reconciliation ledger

- [ ] A non-empty reconciliation ledger exists for every selected source
  repository under provenance/reconciliation/.
- [ ] Every post-baseline source commit is classified exactly once as
  incorporated identically, incorporated equivalently, superseded,
  not-applicable, pending-port, or blocked-on-design.
- [ ] Each ledger entry records source SHA, affected capability, BNG3 commit or
  issue, tests, reviewer, rationale, and disposition date.
- [ ] Correctness/security, parser/semantic, numerical/NFsim, Atomizer/API,
  packaging/platform, performance, and documentation changes are reviewed in
  that priority order.
- [ ] A scheduled read-only upstream drift report compares locked SHAs with
  current upstream heads without copying code, changing goldens, or pushing
  fixes automatically.

### 1.4 `akutuva21/bionetgen` non-main branch audit

- [x] The fork was audited read-only through its exact branch tips and public
  PR list on 2026-09-01. The fork is
  `https://github.com/akutuva21/bionetgen`, with `master` at
  `b00410628484f639efbf294f8a150f21c4e8bb29`; open PR heads are #508 at
  `e67850cfc5b2d65322970b77b9e145152e2da0f6` and #509 at
  `5cf5cd4747efa9961b8b3d63127499fce945000e`. Parallel branch tips were
  recorded before porting; they are not treated as one mergeable stack.
- [x] Source commit `46da45c4` (`fix: handle empty pattern graph
  canonicalization`) is ported equivalently at BNG3 `b610992`; the
  source-derived empty-graph canonicalization test is green.
- [x] Source commits `556099d3` (`perf: reduce BNG2 graph string
  allocations`) and `b73d9e3d` (`perf: streamline canonical node labels`) are
  ported equivalently at BNG3 `2c498af`; exact BNG2-string and canonical-label
  tests are green. These are performance ports with preserved output
  contracts, not a claim of benchmark parity.
- [x] Source commit `77c8bd8` (`portability: constrain BNGcore inequality
  overloads`) is classified non-applicable to the current BNG3 tree: BNG3
  already uses type/member-scoped inequality operators rather than the generic
  overload removed by that source patch.
- [x] Source commits `5291159d` (compartment-aware dedup test) and `533ac26`
  (`perf: skip canonical labels for exact product duplicates`) were ported
  equivalently at BNG3 `084090e`, with the source-derived compartment-aware
  dedup test and full CTest `176/176` green.
- [x] Source commit `92ca4c03` (`perf: preserve canonical product ordering in
  exact dedup fast path`) was ported equivalently at BNG3 `d52f18a`, with the
  source-derived no-canonicalization exact-probe test and full CTest `176/176`
  green.
- [x] Source commit `70acc9e2` (`perf: reuse exact dedup keys across product
  insertion`) was ported equivalently at BNG3 `7100f5e`: the exact-key output
  overload and keyed insertion API are covered by a source-derived
  `SpeciesList` test, and all three product insertion paths reuse the computed
  key. BNG3 retains the required compartmented-species key recomputation after
  canonicalization from the earlier `533ac26` port; full CTest `176/176` is
  green. This closes the source/API slice, not independent benchmark parity.
- [x] Source commit `7ee2db11` (`perf: cache immutable reaction pattern
  metadata`) was ported equivalently at BNG3 `73757ea`: cached immutable
  `PatternInfo` is rebuilt by `initialize()` and reused by all former
  per-expansion description sites, with source-derived reinitialization/move
  coverage and full CTest `177/177` green. This closes the source/API slice;
  independent BNG3 benchmark reproduction remains open.
- [x] Source commit `f30898b6` (`Bolt: Optimize string lowercasing
  allocations in engine loops`) was ported equivalently at BNG3 `2d69b99` for
  `parseBooleanLike`; the source-derived accepted-spelling test remains green.
  Its ODE allocation portion was reconciled with the newer ODE match work
  below rather than duplicated.
- [x] Open Bolt PR #508 head
  `e67850cfc5b2d65322970b77b9e145152e2da0f6` and PR #509 head
  `5cf5cd4747efa9961b8b3d63127499fce945000e` were audited and their supported
  allocation-only ODE portions were ported equivalently at BNG3 `d502e47`:
  lowercase function names are prepared once, raw rate-law matching avoids a
  lowercased temporary, and the source-derived user-defined ODE-rate contract
  passes. A probe that changed the declared function's case was rejected from
  the port because BNG3's parser/runtime function-name semantics are not
  case-insensitive; no public language behavior was silently broadened.
- [x] Source commit `60ac7e5f` (`Bolt: Pre-parse observable patterns in loops`)
  was ported equivalently at BNG3 `4ea7157`: ODE group compilation and NetWriter
  group serialization cache parsed graphs while retaining compartment,
  quantifier, state, structural-role, and species-observable behavior. The
  source-derived multi-pattern ODE and repeated-pattern NetWriter contracts
  pass in the targeted `6/6` CTest selection; independent BNG3 benchmark
  reproduction remains open.
- [x] Branch `codex/portable-cpu-20260831` at
  `305b7482febe3dd52ccd517fa4cd2e02504e834c` was audited. Its listed
  exact-dedup/canonical-label source commits are ported above; remaining
  branch content is documentation/benchmark material plus the separate
  `0463a1f4` Macro allocation candidate. Independent BNG3 benchmark evidence
  and the supported Macro executable path remain open below; the branch is not
  a clean merge target.
- [x] Branch `codex/ode-integration` at
  `9c7c0aa3e031330b7421a8e93a2340dc65c43cbb` and source commit `dd665873`
  were audited and ported tests-first at BNG3 `3b284a5`. The focused
  multi-species 512-reaction derivative contract and full CTest `175/175` are
  green; representative performance benchmark evidence remains open. Branch
  `codex/ode-jtimes-20260901` at
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b` adds no code beyond that ODE
  lineage and must not be bulk-merged.
- [x] Branch `codex/graph-string-20260901` at
  `62f4dc6bd2a191d89a593e2d952e6c74c5b47271` and
  `codex/canonical-redesign-20260901` at
  `901ce2d94db6d423e81745cb5f1ef1e82e1c865a` were audited. Their residual
  tips are documentation-only records beyond the already ported Node/string
  and canonical behavior; no unreviewed source change is pending from them.
- [x] Branch `codex/parallel-optin-20260901` at
  `e52e8e41751f389eb8187b7e6d0ab946f0e5b8e8` was classified as an opt-in
  independent-model launcher/benchmark branch, not a default runtime port.
  Branch `codex/gpu-optin-20260901` at
  `0c5217531ebb9e692cc5cff4d76535ed8b4cca91` is documentation-only and
  records no retained GPU capability; both require a separate approved
  capability/performance decision before inclusion.
- [x] The remaining non-main fork tips were audited read-only, including issue
  branch `codex/bionetgen-issues-20260901` at
  `1f92663066cfccfa33876f8e3b61c8dd21e10742`, ODE-JTimes branch
  `fde0cd6a522c9f988d5495db31c70ce0f98e744b`, closed/superseded Bolt heads
  `8aff40f6ddc017ece0eb03c5251edbcd0a27dd82`,
  `06d8c9f2947594b38664c929c625d9164e09fd91`,
  `0351eba9d4827c6c86e07fb06a1c56cd9dfd2160`,
  `07240c0774d51073259205cf78f44e31314d5a98`, and
  `abecfecb339f7ba2dc66580abf4c584f859caf0b`, plus the Jules and Sentinel
  security branches. Source changes were classified as already ported,
  superseded, non-applicable to BNG3, or pending below; `.jules` and generated
  artifacts were not imported. A durable per-commit reconciliation ledger is
  still required by Section 1.3.
- [x] The issue branch's native fixes were reconciled: empty-graph handling,
  pure-bond rejection, and CLI action exception reporting are already covered
  by BNG3 checkpoints `b610992`, `0f83347`, and `1c03bc1`. Its BNG2 `Network3`
  memory/tfun/output fixes are not native BNG3 source and remain a separate
  legacy compatibility audit.
- [x] The exact issue-branch tip `20fe141452e79d01fd4a669d801da59c73d38588`
  was re-audited against the BNG3 tree. Its native changes are already
  represented by the checkpoints above; the repeated generic-`operator!=`
  portability patch `897e8a29a93dc42db8c1af74b0fbce968e52cb23` is likewise
  non-applicable because BNG3 has type/member-scoped inequality operators.
  No native issue-branch code was bulk-merged.
- [x] Source performance commit
  `5fab87788a4d6253ea83fd2cb35312be0c99c725` (`Cache OdeIntegrator rate-law
  normalization`) is ported equivalently at BNG3
  `1de39f4d3bb040dc5a2844c7432aadba5595d4c6`. The source parent is
  `31155dc049a77057eb9a0afa5a41bf44b7bbaa81`; BNG3 adds the explicit
  `<cctype>` dependency, retains the existing lowercase-function and raw-rate
  caches, and records the completed function scan so the fallback block cannot
  rescan a rate expression. The source-derived case-classification contract is
  `tests/cpp/test_ode_options.cpp:107-158`; it was green before the production
  edit with `8 assertions`, and the focused post-edit target is `9/9` CTest
  cases. A temporary benchmark harness, removed before commit, generated the
  production `models/nfkb_illustrating_protocols.bngl` network (22 species,
  31 reactions) and constructed 512 OdeIntegrator instances per fresh process.
  Twelve alternating baseline/candidate pairs using `/usr/bin/time -p` gave
  coarse real-time medians of `0.78s` without and `0.775s` with the guard;
  this is a sub-percent signal under timer noise, not a release performance
  claim. Temporary baseline/candidate test artifacts were hashed as
  `404777ab7161acc855830bdbb934adb9b9d73054d77a140308b3e4dc73c3e65f` and
  `8d0c7e06944cb013ae6b97052ea7312a79b7c7331c6e3d7b113be521455342c2`.
  Full local gates at the candidate report `187/187` CTest and
  `276 passed, 27 skipped, 8 warnings` in Python. This closes the source/API
  reconciliation only; cross-platform performance budgets, release
  reproducibility, and broader benchmark provenance remain open.
- [x] Sentinel ContactMap server branches were classified non-applicable to
  the current BNG3 tree, which has no `parsers/ContactMap/server.py`; their
  exact security findings remain recorded for inventory. The Sentinel Perl
  open-injection branch was applicable to the bundled legacy Macro module and
  is ported and tested below.
- [x] The applicable legacy Perl open-mode hardening is ported and tested at
  BNG3 `44d8655`. Sentinel commit `cdbd6ee98a7a546a7c8fa774e8d97bec6d9104d0`
  is an empty duplicate of payload commit
  `2b95afe90a41b52343596ac4adf396782e648a43`; the final contract also retains
  the prior `.rab` diagnostic correction from `b13533cc`. The source-derived
  `tests/python/test_legacy_security_contract.py` and Perl syntax gate pass.
  Unrelated ContactMap server fixes remain non-applicable to BNG3.
- [x] Reconcile the applicable Macro portion of source performance commit
  `0463a1f4906a7e4e0d51a4ac79fe16fee6a58ac`
  (`num_site`/`cor_net` allocation changes) at BNG3 `4edf4df`: the
  source-derived Macro executable contract now links, `trans_specie` is
  implemented, and the source `pre_rules`/`pre_obs1` calls are active.
  `num_site` uses the source `find`/`rfind` extraction and `cor_net` already
  had the equivalent allocation-free extraction. The source ODE allocation
  portion is reconciled separately with BNG3's newer ODE matching/cache path;
  independent benchmarks and full Macro/legacy parity remain open.
- [x] The NFsim XML energy bridge is implemented at semantic code head
  `567b39105bebaf9dd090104a584da9f9f424088a` and its Arrhenius directionality
  repair is at `5a1594f39d0d51b1220e7f5278302cad253fed3f`. The source contract
  is diagnostic BNG2 revision `fde0cd6a522c9f988d5495db31c70ce0f98e744b`
  (`bng2/Perl2/BNGOutput.pm:619-630`, `EnergyPattern.pm:146-164`, and
  `RxnRule.pm:1737-1919`) plus the accepted NFsim energy source cutoff
  `3b046fc1b9f76719d92be22279b24992cdae7c35` (`src/NFinput/NFinput_energy.cpp`);
  no later NFsim source was imported. `XmlWriter` now emits BNG2-shaped
  `<ListOfEnergyPatterns>`/`EPn`/nested pattern graphs, preserving omitted
  bond `numberOfBonds="0"` semantics from the source pattern instead of the
  AST wildcard serializer. The XML loader routes explicit Arrhenius
  `StateChange` operations through the existing energy expansion helper,
  continues to later reaction rules, applies XML rate/match metadata, and
  carries BNG3-generated one-way directionality with
  `energyIncludeReverse="0"`; files without that attribute retain the legacy
  reverse-on default. Red-first executions were
  `ctest --test-dir build -R '^NFsim XML bridge preserves energy patterns$'
  --output-on-failure` (7 failed assertions),
  `ctest --test-dir build -R '^NFsim XML bridge expands Arrhenius state
  changes$' --output-on-failure` (1 failed assertion, XML had 0 reactions),
  and the one-way direction test (2 failed assertions). Final focused bridge
  coverage reports `3/3`, the adjacent energy/Arrhenius selection reports
  `17/17`, `ctest --test-dir build --output-on-failure` reports `190/190`, and
  `env PYTHONPATH=python:build/cpp python -m pytest -q tests/python` reports
  `276 passed, 27 skipped, 8 warnings` in `10.22s`. The rebuilt
  `build/cpp/bng_cpp` digest is
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`, and
  the final temporary `isingspin_energy` XML digest is
  `c5d60e576023b06cb620b7a2f0794ff34a88642c9869eefa170e48fc4ba35f0d`.
  A paired BNG3 direct-versus-forced-in-memory-XML `isingspin_energy` harness
  using seeds `1..200`, `t_end=1.0`, `20` output steps, and four workers
  reports `200/200` runs, `different_runs=0`, `max_per_run_diff=0.0`, and
  `max_final_abs_diff=0.0`; output is retained in
  `/private/tmp/bng3-energy-final-ensemble.log`. This closes only BNG3
  direct/XML semantic parity. The independently built accepted-cutoff NFsim
  binary `/private/tmp/bng3-nfsim-3b046/build/NFsim` (source
  `3b046fc1b9f76719d92be22279b24992cdae7c35`, SHA-256
  `c30a80b6ff9cf1fae04bc9f45556c4d5fa9c3b00d053fb6abade80436ee46394`) still
  skips XML Arrhenius state-change expansion and leaves `0 reactions`; its
  fixed-seed comparison differs by at most `8` and its 200-run comparison
  had `60/105` points outside `3` pooled SE, worst `z=53.88` at `Misaligned`.
  Independent NFsim energy parity, legacy XML without the direction marker,
  broader evaluator coverage, and benchmark/provenance approval remain open.

## 2. Independent validation and provenance spine

### 2.1 Independent oracles

- [ ] BNG2 Perl is built from the accepted BioNetGen source revision with a
  recorded recipe, compiler/runtime details, artifact digest, and retention
  location.
- [ ] Native pre-convergence NFsim is built independently from the accepted
  NFsim revision with the same evidence.
- [ ] The accepted PyBioNetGen source/release is available for public API and
  CLI compatibility comparisons and has a recorded digest.
- [ ] BNG3-generated output is never the sole oracle for BNG3 behavior.
- [ ] RuleWorld/bngplayground and Jules Playground remain independent
  differential references, not scientific replacements for BNG2/NFsim.

### 2.2 Corpus and goldens

- [ ] RuleHub selectors and external tier membership are maintainer-approved.
- [ ] The generated selection manifest is linked to the accepted source lock
  and has verified content digests for every fixture.
- [ ] Tier-S is feature-balanced and completes within its declared budget.
- [ ] Tier-P contains the complete approved BNG2-compatible corpus and models/
  fixtures, including all known graph-overcount cases.
- [ ] Tier-NF contains the approved NFsim corpus and all required NFsim
  function/rate-law fixtures.
- [ ] Tier-X covers BNGL, BNG-XML, NET, SBML, SBML-Multi, Atomizer, and every
  supported writer/converter.
- [ ] Tier-B covers benchmarks, large models, memory stress, sanitizers, leak
  checks, and reproducibility rebuilds.
- [ ] A reviewed provenance-complete golden bundle exists. Each manifest
  records model/content digest, RuleHub and source revisions, oracle/binary
  digest, compiler/dependency/platform/image details, command, method, seeds,
  time grid, tolerances, comparator version, output digests, and generation
  metadata.
- [ ] A clean machine can verify the golden bundle without regenerating it.
- [ ] Golden regeneration is an explicit reviewed scientific change and never
  occurs silently in ordinary tests.

### 2.3 Comparator and exception integrity

- [ ] Parser comparisons cover success/failure, normalized diagnostics, symbol
  resolution, defaults, actions, functions, includes, and source-sensitive
  behavior.
- [ ] NET comparisons are graph-aware and preserve species/reaction
  multiplicity, stoichiometry, rates, compartments, observables, and
  duplicates.
- [x] NET validation performs actual write/read/write idempotence at BNG3
  checkpoint `845bc8c`: `tests/validation/test_export_formats.py` now writes
  a generated `.net`, creates a separate `readFile`/`writeNetwork` BNGL source,
  reads that exact file through `runner.run_cli_path`, and compares the two
  graph-aware parses. The source-derived BNG2 read/write contract is represented
  by `tests/validation/Validate/michment.bngl` and
  `tests/validation/Validate/michment_cont.bngl`; the exact local gate
  `PYTHONPATH=python:build/cpp python -m pytest tests/validation/test_export_formats.py -q`
  reports `12 passed` (four XML, four SBML, and four actual NET round trips).
  This closes the validator-contract gap, not complete independent Tier-P
  NET parity.
- [ ] Deterministic trajectories align explicit time points and compare all
  contracted observables/species at approved absolute and relative tolerances.
- [ ] Expression/rate-law validation compares direct expression vectors/RHS,
  not only downstream trajectories, at the approved 1e-9 criterion where
  applicable.
- [ ] Stochastic validation uses fixed, predeclared ensembles; verifies
  repeatability; compares means, variances, relevant quantiles,
  extinction/zero-inflation behavior, and time-correlated summaries; and uses
  the approved pooled independent-ensemble standard error.
- [ ] Designated stochastic gates contain at least 200 complete runs per side
  or have an approved power-based alternative.
- [ ] Every skip and expected failure is in the machine-readable ledger with
  exact test/model/platform scope, issue, technical reason, owner,
  introduction date, expiry/review date, and expected signature.
- [ ] Required missing oracles, corpus files, schemas, or validators fail the
  claiming job; they do not become passing skips.
- [ ] The exception budget is non-increasing unless a maintainer-approved
  compatibility decision changes it.

## 3. Parser, AST, graph identity, and network generation

### 3.1 Canonical parsing and model semantics

- [ ] ANTLR BNGL parsing is the sole default front door for BNGL into the
  canonical ast::Model.
- [ ] BNGL syntax, diagnostics, block aliases, includes, actions, parameters,
  compartments, molecule types/states, seed species, observables, rules,
  functions, protocols, scans, and source metadata are covered.
- [ ] Invalid constructs fail with stable, documented diagnostics rather than
  being dropped or routed to a weaker parser.
- [ ] ModelBuilder, Python load(), Atomizer output, CLI input, network
  generation, simulation, and writers consume explicit canonical AST
  boundaries.
- [ ] Parser/AST behavior is differentially compared with accepted BNG2 and
  PyBioNetGen behavior for the supported contract.

### 3.2 One graph canonicalizer

- [ ] One bng::core::canonicalLabel implementation is used by network
  canonicalization and NFsim complex identity.
- [x] The duplicate cpp/nfsim/nauty24 build is removed. **Locally build-verified 2026-09-17.** `cpp/nauty` is now the only compiled nauty
  tree; `nfsim_core` links the shared `nauty` target and
  `cpp/nfsim/NFcore/complex.cpp` includes its header. The two trees were
  verified identical after normalizing the documented `set`->`nset` rename
  (`diff` clean on all five translation units), and unifying on the NFsim
  variant also picked up an MSVC `HAVE_SYSTYPES_H` guard the `cpp/nauty` copy
  lacked. Previously statically verified plus `tests/python/test_single_nauty_contract.py` (10/10); now also **linked in `bng_core`/`nfsim_core` and exercised by 408/408 CTest** (incl. `test_observable_counting`, `test_network_generator`, `test_nfsim_*`). The
  *independent identity evidence* this item also asks for — that one low-level
  Nauty dependency does not alter NFsim complex identity, reaction counts, or
  seeded trajectories — still **requires hosted CI and an independent NFsim
  oracle**, tracked by the last item in this subsection.
- [ ] NFsim private canonicalization is replaced or explicitly governed without
  changing complex identity semantics.
- [ ] The HNauty largest-versus-canonical-form decision is resolved against
  BNG2 semantics and recorded.
- [ ] Species graph equality preserves site states, bonds, connectivity,
  stoichiometry, compartments, and symmetry; it does not reduce to string
  normalization.
- [ ] blbr, Motivating_example_cBNGL, test_network_gen, tlbr, and all other
  known overcount fixtures match the independent BNG2 oracle.
- [ ] Tier-P NET parity passes across the complete approved corpus with no
  unreviewed overcount exception.
- [ ] A single low-level Nauty dependency is proven not to alter NFsim
  runtime identity, reaction counts, or seeded trajectories.

### 3.3 Network and numerical simulation

- [ ] Network generation matches accepted BNG2 species/reaction sets and
  multisets, including deletion, product molecularity, bond cardinality,
  symmetry, observables, fixed species, compartments, and rate laws.
- [ ] ODE/CVODE, SSA, PLA, and PSA methods preserve documented controls,
  output shapes, sample grids, conservation behavior, and failure modes.
- [ ] Protocols, time-dependent functions, events, scans, continuation, and
  solver options are covered by source-derived and independent tests.
- [ ] One-dimensional and two-dimensional parameter scans match the supported
  PyBioNetGen contract.
- [ ] Local sensitivity analysis matches the supported finite-difference
  contract, including parameter ordering, perturbation controls, and result
  schema.
- [ ] Benchmarks establish performance and memory budgets for representative
  small, medium, and large models; abstractions do not silently regress them.

## 4. One expression and rate-law contract

- [x] A single parsed/resolved expression representation and error model is
  shared across ODE RHS, SSA/PLA/PSA propensity evaluation, and NFsim
  local/global functions. **Locally build-verified 2026-09-17 (WO-3).** `bng::ast::Expression` is now the single representation: `cpp/nfsim/NFfunction/nfsim_funcparser.h` retains the `mu::Parser` interface but is backed by `bng::parser::parseExpression` + `bng::eval::evaluate` (`cpp/ast/ExpressionEval.hpp` now has consumers in `nfsim_core`), and the builtin metadata is unified in `cpp/ast/ExpressionBuiltins.hpp`. `NFSIM_USE_EXPRTK` and the root `FetchContent(ExprTk)` block are removed. Previously `bng::eval` had zero consumers; now it is the NFsim evaluator.
- [x] NFsim ExprTk compilation and the NFSIM_USE_EXPRTK build path are removed
  only after the shared evaluator passes all dependent gates. **Locally build-verified 2026-09-17 (WO-3b).** `cpp/CMakeLists.txt` no longer defines `NFSIM_USE_EXPRTK` or adds `exprtk_SOURCE_DIR`, `nfsim_core` no longer links `exprtk`, and `CMakeLists.txt` root no longer fetches `exprtk`. Part of 408/408 CTest.
- [ ] Numeric literals, parameters, observables, time, roots, logs/bases,
  constants, function definitions, nested functions, and domain errors have
  cross-backend tests. **Partial.** A shared-table contract test now asserts
  that every NFsim-evaluable builtin is also implemented by the shared
  evaluator, and three previously divergent cases have focused regressions in
  `tests/cpp/test_expression_evaluator.cpp`:
    - `rint` disagreed between backends *and* with the BNG2 oracle. BNG2
      defines it as `floor(x + 0.5)` (`legacy/perl/Perl2/Expression.pm:74`);
      the shared evaluator used `std::rint` (half-to-even, wrong at 4 of 7
      half-integers) and NFsim used `std::round` (half-away-from-zero, wrong at
      3 of 7). Both now use the oracle definition, checked against values
      produced by executing the Perl oracle directly.
    - `sign` was accepted by the NFsim gate and registered in the ExprTk shim
      but unimplemented in the shared evaluator, so it evaluated under NFsim
      and fell through to the user-function resolver under ODE/SSA. Now
      implemented with the shim's definition.
    - `log` was accepted by the NFsim gate, where ExprTk treats it as natural
      log, while BNGL has no bare `log` at all. It is now rejected everywhere
      with a diagnostic naming `ln`, `log10`, and `log2`.
    - `avg` is a BNG2 builtin implemented in the shared evaluator and native
      to ExprTk, but the gate rejected it and forced an unnecessary XML
      fallback. Now admitted.
    - The gate matched case-insensitively while the shim is compiled with
      `exprtk_disable_caseinsensitivity`, so `SIN(x)` passed and then failed
      inside `GlobalFunction::prepareForSimulation()`. The gate is now
      case-sensitive and reports a "did you mean" hint.
  These are **locally build-verified 2026-09-17** (`test_expression_evaluator` 4 new cases, part of 408/408 CTest); genuine cross-backend
  numerical comparison still **requires hosted CI and an independent oracle**.
- [ ] Global functions, local functions, molecule/species scopes, TFUN linear
  and step forms, file-backed files, observable/time/parameter counters,
  composite functions, bounded nested functions, and function-counter forms
  match independent references.
- [ ] Michaelis-Menten, Sat, Hill, elementary, FunctionProduct, Arrhenius,
  energy-pattern, reversible, zero-order, and scoped-rate laws are validated.
- [ ] Unsupported function/rate-law combinations remain fail-closed with a
  diagnostic and a tracked capability status.
- [ ] Direct expression-vector/RHS parity reaches the approved tolerance for
  localfunc, isingspin_localfcn, isingspin_energy, CaOscillate_Func, and all
  approved test_tfun_* fixtures.
- [ ] Direct NFsim function-bearing models localFunction, motor, TQSSA, and
  the accepted NFsim test corpus pass through the shared contract.

## 5. Direct NFsim convergence

### 5.1 Adapter completeness

- [ ] Typed direct mapping covers options and flags, parameters, compartments
  and hierarchy, molecule types and integer/symmetric states, seed species,
  populations, fixed species, observables, reaction rules, transformations,
  functions, TFUNs, rate laws, energy patterns, and runtime metadata.
- [ ] Direct mapping preserves bond labels/cardinality, product molecularity,
  deletion modes, symmetry factors, molecule/template observables,
  include/exclude filters, compartment movement, and MoveConnected behavior.
- [ ] Direct mapping preserves dynamic rates and generated live functions for
  symmetric state-change/bond permutations.
- [ ] Unsupported local-function, TFUN, energy, rate-law, filter, and scope
  combinations fail closed and are listed in the capability matrix.
- [ ] Adapter ownership, destruction/lifecycle, memory ownership, diagnostics,
  seed handling, options, and error propagation are documented and tested.
- [x] Bounded NFcore2 semantic-expansion checkpoint on
  `codex/bng3-energy-validation-port` adds tests-first
  direct support for population transforms, root-local graph/`connectedTo`,
  synthesis, root-local compartments/moves, bounded local-function/DOR rate
  descriptors, and whole-species deletion. The independent literal oracle and
  fixture are recorded in `provenance/semantic-expansion-2026-09-08.json`;
  the current CTest run reports `269/269` with twelve parser-backed native
  reader cases, while the reference executables report NFcore2 `408/408` and
  NFnext `PASS`. The current macOS ASan/UBSan run also passes the energy smoke,
  NFcore2/NFnext references, and all twelve native-reader cases. This closes
  only the bounded forms; arbitrary internal graph expressions, general
  local-function/DOR evaluation, compartment hierarchy/species-carrying moves,
  conditional deletion, and independent full NFsim/BNG2 parity remain
  intentional fail-closed ceilings below.

### 5.2 Three-way evidence

- [ ] Direct ast::Model construction is compared with the existing
  AST-to-XML-to-NFsim path in memory and, where required, on disk.
- [ ] Direct construction is compared with an independently built native NFsim
  oracle, not a BNG3-generated oracle.
- [ ] Comparisons cover molecule types, seed complexes, transformations,
  observables, functions, compartments, options, reaction rules, seeded
  deterministic behavior, and stochastic distributions.
- [x] Current exact seeded native-NFsim trajectory parity is closed for the
  source-derived `IfTest` fixture at `e92b2c9`. Direct BNG3 loaded the exact
  `nfsim/test/IfTest/ifTest.bngl` source through `bng_cpp --console` and ran
  with seed `1`, `t_end=5`, ten output steps, and `-utl 3`; independent native
  NFsim `a6f9fa9` ran the unmodified XML oracle from the same fixture with the
  same seed/time grid. Both produced 29,177 events and byte-identical output;
  the direct BNG3 `.gdat` and native artifact have SHA-256
  `6f262eaf40044ba844063f6f572d4a58fde3a5d814011e6da40d40b75d54abe4`.
  BNG3 direct and explicit XML fallback also produced the same digest. The
  historical checkpoint at `300724b` remains recorded separately by digest
  `85fef92118f5effffec6e8f179c0912f4f28efd5a53c2b5a79ef9807de6ffe88` and
  `Ton = 0, 2236, 3944, 6306, 7787, 8656, 9176`. The source-derived
  `stepTo` event-cache port from NFsim `e3ef4a0` preserves
  continuous-vs-chunked checkpoint timing. BNG3 mirrors current NFsim's split:
  reaction timing/selection stays per-System, while legacy molecule/mapping
  selectors identified in source commits `64d225f` and `a6f9fa9` use a second
  per-System stream seeded identically (exact direct and XML assertions in
  `tests/cpp/test_nfsim_ast_adapter.cpp`).
- [ ] Tier-NF includes localfunc, motor, TQSSA, tlbr, simple_system,
  fceRI/multisite fixtures where supported, and the relevant nfsim-master/test
  inputs.
- [x] The source-derived AN2 trajectory is exact through the direct AST at
  current checkpoint `e92b2c9`. The unmodified NFsim fixture
  `nfsim/test/AN_chemotaxis/an2.bngl` was parsed by BNG3 `e92b2c9` and run
  with seed `1`, `t_end=10`, and ten output steps; an independent native
  NFsim `a6f9fa9` run from `nfsim/test/AN_chemotaxis/an2.xml` used the same
  seed/time grid. Both produced 7,807 events and byte-identical `.gdat`
  output with SHA-256
  `0fdb80a8e151a30b3051be2e1fced2dafc6ccc5223e96e4d474ab5f386032d64`.
  The discriminating source ports were position-major repeated-seed
  allocation (`bdddbd4`), BNG2 canonical seed graph/type ordering
  (`41b12f2`), and numeric-site wildcard/PLUS/MINUS handling (`3be1b40`).
- [x] Fixed-seed direct/API NFsim endpoint parity is closed for the source-
  derived `motor` and `tlbr` fixtures at `7186b65`. With seed `1`, the
  independently built native binary above, BNG3-generated XML, and twenty
  output checkpoints, `tests/validation/test_parity_nfsim.py::test_nf_fixed_seed_direct_matches_native_at_final_endpoint`
  passes with exact observable arrays and time coordinates within `1e-12`.
  The full `motor`/`tlbr` subset passed `6 passed, 4 deselected, 1 warning` in
  124.43 seconds. The direct binding invokes endpoint-inclusive `stepTo` only
  for the final checkpoint, while the ordinary one-argument `stepTo` contract
  remains exclusive for intermediate callers. The full Tier-NF gate remains
  open.
- [ ] Protocol NF support and remaining RNA/t4/t5 behavior are
  implemented or explicitly governed with tests and owners.
- [ ] The full fixed-seed and distributional Tier-NF gate passes at the
  approved criteria.

### 5.3 XML bridge retirement

- [ ] The direct path is demonstrably selected and the test asserts the actual
  construction route.
- [ ] The XML bridge remains available only as a temporary shadow comparator
  and supported interchange path during migration.
- [ ] Direct and XML paths are statistically identical on the approved shadow
  corpus.
- [ ] Only after the full gate passes, remove XML serialization, temporary-file
  machinery, and XML reparse from the default NF simulation path.
- [ ] Retain BNG-XML export/interchange support and its schema/semantic tests.

### 5.4 Energy-function evaluator convergence

- [x] The merged `akutuva21/nfsim` energy-evaluation source is pinned for this
  work: PR #475, merge `6690fda5d9e053df822d0248ebae185f5caca82a`, accepted
  energy-source cutoff `3b046fc1b9f76719d92be22279b24992cdae7c35`.
- [x] The accepted PR #475 source is already reconciled equivalently in BNG3:
  the compact evaluator, partner-pool scale groups, and direct-selector
  integration are represented by the source-derived BNG3 checkpoints through
  `a97c02e`, with the corresponding AST/lifecycle/RNG adaptations retained.
  A file-level comparison against the accepted NFsim cutoff found no missing
  PR #475 implementation that should be merged wholesale. This closes source
  incorporation only; independent native-NFsim parity, benchmark provenance,
  and the remaining evaluator slices below remain open.
- [x] Source-derived BNG3 tests define compact binding-context extraction,
  rejection of duplicate weighted molecule topologies, compact conjunction
  masks, factorized runtime propensity evaluation, shared partner-pool
  registration/indexing and selector batch updates, and materialized fallback.
  Current checkpoints are `b9ab125`, `2b1c02f`, `92543ca`, `6ed6e97`,
  `a77ceb8`, `b8f44e4`, `4a2fc3e`, `738c881`, `6b6e246`, `bd29714`,
  `401becf`, `6c681269`, `a97c02e`, `7b2a199`, `dbadea6`, `c0d1bb5`,
  `bb3ae01432adfd8bb92240af3e1e947e49b017ee`, `464bd8d`, and `2940a02`.
  The source-derived MoleculeList ownership/reuse regression is covered at
  `f510e49` and fixed at `ec42926`.
- [x] BNG3 carries the compact `EnergyBindingContext` and mapping-local
  `EnergyRxnClass` path for supported contexts while retaining legacy
  materialized expansion for unsupported topologies.
- [x] BNG3 carries the compact partner-pool index for simple forward binding
  rules, including shared pool registration and batched selector updates on
  partner add/remove membership changes.
- [x] BNG3 carries a source-derived deferred membership lifecycle for compact
  direct-product events, including coalesced partner-pool changes and selector
  updates that capture BNG3's live compact propensity before membership
  mutation (`6c681269`; `tests/cpp/test_nfsim_ast_adapter.cpp`, 30 assertions).
- [x] BNG3 carries source-derived sparse direct-selector behavior for compact
  reactions: active propensity bits, block prefix sums, cached sparse
  propensities, indexed updates, and shared compact-pool scale groups
  (`a97c02e`; `tests/cpp/test_nfsim_ast_adapter.cpp`, 51 assertions).
- [x] BNG3 carries the accepted NFsim `4bb24b3119684e9ec6e870bb4b517866e2aa15a4`
  sparse-batch refinement: indexed sparse updates use the selector's cached
  pre-update propensity instead of rereading a post-event `get_a()` value.
  The source-derived fired-event regression is
  `NFsim sparse selector reuses cached propensities in implicit batches` in
  `tests/cpp/test_nfsim_ast_adapter.cpp`, implemented at `88f4e54` and green
  in the exact-head `184/184` CTest gate.
- [x] BNG3 carries the accepted-cutoff NFsim
  `301bfbeb5ec5007532f713f488ff9954da9ebe1f` guarded Release-LTO build
  capability at `7241746`: `CheckIPOSupported` controls the embedded
  `nfsim_core` and each built consumer, with explicit ON/OFF and optional
  standalone-NFsim contract coverage. This is build/performance evidence
  only; reproducible speedup, memory, and cross-platform benchmark evidence
  remain open.
- [x] BNG3 carries source-derived compact reverse propensity specialization
  and factorization guards (`dbadea6`), plus indexed cross-type partner
  endpoint propagation and a dense type-invariant membership-decision cache
  (`bb3ae014`; `tests/cpp/test_nfsim_ast_adapter.cpp`, 15 mixed-fixture
  assertions).
- [x] BNG3 carries source-derived pure-context counting for transformed-rule
  discrimination and complex-level deduplication (`bb14a207`): homodimer,
  homotrimer, distinguishable scaffold, transformed homodimer binding, and
  local-function DOR fixtures pass in
  `tests/cpp/test_nfsim_ast_adapter.cpp` (18 assertions across the four
  pure-context cases).
- [x] BNG3 carries source-derived sparse membership-decision indexing from
  NFsim commit `ba7466c386c0cf72920863472d8382f8011e1811`: type-invariant
  direct-product decisions retain an ordered affected-reaction index list when
  fewer than half the registered reactions are affected, and the adapter
  refreshes that list without scanning unrelated rules (`fbfda3f`; the
  unrelated-partner fixture passes 42 assertions in
  `tests/cpp/test_nfsim_ast_adapter.cpp`).
- [x] BNG3 carries the endpoint-refined membership decision from NFsim commit
  `ced6f6046dc3e9a5bf1680d9367ecdf64facd7a4`: partial context changes are
  rejected when the changed molecule remains context-incomplete, while the
  full-mask case retains the source fallback (`464bd8d`; the compact
  factorized-energy fixture passes 49 assertions in
  `tests/cpp/test_nfsim_ast_adapter.cpp`).
- [x] BNG3 carries the source-derived all-forward compact partner-pool early
  return from NFsim commit `fd01d015ea70552fe2196a1029317ac8f08674fe`:
  when every candidate reaction uses the shared compact pool, only that pool's
  registered reactions are refreshed before returning from generic membership
  scanning (`2940a02`; the direct AST fixture passes 18 assertions in
  `tests/cpp/test_nfsim_ast_adapter.cpp`). The fixture uses bidirectional
  energy rules to exercise both directions; one-way direct-AST energy mapping
  is covered separately below.
- [x] BNG3 carries the source-derived connected-membership refresh from NFsim
  commits `051e7e2` and `23436e2`: native MoleculeType reaction order,
  precomputed `areReactionsConnected` lookup, compatible explicit template
  connectivity, and indexed `tryToAddWithIndex` for incremental reactions
  (`c7dd52d`; the source-derived t3 XML bridge test passes bytewise seeded
  no-connect/connect trajectory comparison in
  `tests/cpp/test_nfsim_ast_adapter.cpp`).
- [x] BNG3 carries the source-derived functional symmetry/TotalRate correction
  from NFsim commits `2778162` and `1b19611`: constructor symmetry factors
  land on the member rate, ordinary functional propensities apply that factor,
  and TotalRate propensities do not (`53a3d3d`; the XML bridge fixture in
  `tests/cpp/test_nfsim_ast_adapter.cpp` passes both cases, based on
  `test/symmetry/symmetry_factor_total_rate`).
- [x] BNG3 carries the source-derived reusable connectivity direct-product
  lookup scratch from NFsim commit `96be0b1`, while retaining the ordered
  direct-product vector required by compact energy preparation (`a2d7f6c`;
  `tests/cpp/test_nfsim_ast_adapter.cpp`, 11 assertions in the repeated
  connectivity refresh fixture).
- [x] BNG3 carries compact sorted reaction-membership IDs from NFsim commit
  `ad4b56a`: the direct-AST adapter uses a dense first-ID plus inline/overflow
  representation, preserving ordered iteration and set semantics while
  avoiding one heap-backed ordered container per mapping index (`3fb3373`,
  `0560c3b`; `tests/cpp/test_nfsim_ast_adapter.cpp`, compact-ID and inline-ID
  fixtures).
- [x] BNG3 carries the source-derived lazy direct-product molecule lookup from
  NFsim commit `2b3c643`: the connectivity-only hash set is allocated on first
  use and remains separate from the compact ordered direct-product vector
  (`2c0b999`; compact factorized-energy and repeated connectivity-refresh
  fixtures pass without changing event behavior).
- [x] BNG3 preserves BNG2 one-way Arrhenius directionality for the supported
  direct AST binding and state-change slices: one forward reaction is emitted,
  no implicit reverse reaction is synthesized, and contextual compact binding
  remains forward-only. Source-derived BNG2 formulas are locked by the three
  AST fixtures in `tests/cpp/test_nfsim_ast_adapter.cpp` (21 assertions), with
  implementation at `72dd033` and compact-path coverage at `ba52c20`.
- [x] BNG3 ports NFsim commit `4b4e514` product-molecularity evaluation for
  multi-bond dissociation: all bonds deleted by one firing are excluded from a
  single connectivity check, allowing genuine ring opening while retaining the
  single-bond ring rejection. Direct AST and XML-compatibility fixtures in
  `tests/cpp/test_nfsim_ast_adapter.cpp` pass 30 assertions at `6b953c5`.
- [ ] Port and test the remaining supported CPU evaluator slices from the
  merged NFSIM source: the broader full incremental-membership machinery and
  the remaining direct-product paths. The connected direct-product refresh
  path and reusable direct-product lookup scratch are now covered above, but
  full source parity is not implied.
  Source context-count semantics now have a BNG3 adapter port and focused
  source-derived tests, but their full source parity is not implied.
  Cross-type changed-endpoint propagation is now indexed in the
  BNG3-adapted path, but source parity is not implied.
  Direct-product endpoint identity is snapshot-tested and
  propagated through fired membership refresh at `4a2fc3e`, safe direct-product
  traversal is checkpointed at `738c881`, cached single-/multi-term rate factors
  at `6b6e246`, cached simple pre-fire binding rejection at `bd29714`, and
  candidate bitset/mapping-slot indexing at `401becf`, deferred multi-product
  propensity accounting at `6c681269`, sparse selector integration at
  `a97c02e`, cached implicit sparse-batch old-propensity reuse at `88f4e54`
  (NFsim `4bb24b3`), reverse specialization at `dbadea6`, partner endpoint/indexed
  decision refresh at `bb3ae014`, pure-context counting at `bb14a207`, and
  sparse membership-decision indexing at `fbfda3f`, and all-forward compact-pool
  early return at `2940a02` from NFsim `fd01d015`, compact sorted/inline
  reaction-membership IDs from NFsim commits `ad4b56a` and `4007795`
  (`3fb3373`, `0560c3b`), and lazy direct-product lookup allocation from
  NFsim commit `2b3c643` (`2c0b999`);
  the other listed slices remain open.
  Preserve BNG3 lifecycle and direct-AST adapters while porting.
- [ ] Compare compact and fallback event semantics against an independently
  built native NFsim at the pinned source revision, including zero crossings,
  conjunction contexts, reversible binding/unbinding, RuleMonkey selection,
  complex-bookkeeping modes, and fixed-seed trajectories.
- [ ] Record the energy benchmark fixture, compiler/platform, event counts,
  memory, and non-additive CPU measurements with reproducible artifact
  digests; performance evidence must not substitute for parity evidence.
- [ ] Reconcile every remaining energy-specific source commit as identical,
  equivalent, superseded, not-applicable, pending-port, or blocked-on-design
  in `provenance/reconciliation/`.

## 6. Python API, CLI, and compatibility consolidation

### 6.1 Public contract

- [ ] Inventory current BioNetGen/PyBioNetGen documentation, examples,
  downstream imports, and CLI usage.
- [ ] Freeze supported signatures, defaults, result objects, array shapes and
  dtypes, parameter ordering, warnings, exceptions, serialization, context
  management, and file behavior.
- [ ] load(), ModelBuilder, model.simulate(), scans, sensitivity, exports,
  visualization, and checks route through the canonical in-process backend.
- [ ] All methods ode, ssa, pla, psa, and nf are tested through both Python
  API and CLI where applicable.
- [ ] CLI run, scan, sensitivity, visualize, check, and export commands work
  on the approved Tier-S and representative Tier-P fixtures.
- [ ] Plotting/helpers, embedded notebooks/data, optional integrations, and
  result display behavior have explicit supported/deprecated status.
- [ ] The default package import has no hidden import of legacy parse or
  simulation modules.
- [ ] BIONETGEN_USE_PERL=1 remains an isolated, tested compatibility/oracle
  path with explicit warnings and no default-path leakage.

### 6.2 Legacy implementation removal

- [ ] Search proves zero default-path references before deleting any legacy
  implementation.
- [ ] Contract tests pass before removing python/bionetgen/modelapi/,
  python/bionetgen/network/networkparser.py, python/bionetgen/simulator/, or
  legacy Cement parser/simulation entry points.
- [ ] The sanctioned compatibility runner and only the needed core exceptions,
  defaults, result, plot, or notebook helpers are retained deliberately.
- [ ] Deletion lists, deprecation warnings, migration guidance, and release
  notes are reviewed and committed separately from semantic changes.
- [ ] Full build, Tier-P, Tier-NF, Tier-X, API, CLI, and clean-wheel tests pass
  after each deletion checkpoint.

## 7. Atomizer, SBML, and format capability union

### 7.1 Playground-derived Atomizer

- [ ] Reconcile the modern Python port against the pinned
  RuleWorld/bngplayground source paths, preserving source-level provenance.
- [x] Source-derived modern tests cover the current annotation API,
  BNG-XML conversion, Rulifier, UniProt seam/cache behavior, structure helpers,
  conservative Multi discovery, and the public helper/rate-rule-constant
  surface.
- [x] The public `utils/helpers` surface and
  `writer/rateRuleConstants` values are ported at 53289e2 with
  source-derived coverage in tests/python/test_modern_atomizer_helpers.py.
- [x] The selected public `atomization/core` facade helpers are ported at
  7de3194 with source-derived coverage in
  tests/python/test_modern_atomizer_core.py; the remaining core and writer
  surface is still open.
- [x] The public `bnglReaction`, `inlineSBMLFunctions`, and
  `splitReversibleRate` writer facades are ported at 7e91acc with
  source-derived coverage in tests/python/test_modern_atomizer_writer_facade.py
  and tests/python/test_modern_atomizer_writer_rate_helpers.py.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts` at reference main
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` maps bare compartment IDs in
  function definitions and assignment-rule bodies to emitted BNGL volume
  parameters. BNG3 ports this bounded `mapCompartments` behavior at `5760be1`
  with source-derived coverage in
  `tests/python/test_modern_atomizer_writer_parameters.py`; the focused modern
  Atomizer suite reports `77 passed`, and the full Python suite reports
  `252 passed, 27 skipped, 8 warnings`. Broader writer, parser, SBML, and
  independent round-trip parity remain open.
- [x] The same Playground writer reference stably topologically orders
  assignment-rule functions before dependent rules, with cycles falling back
  to source order. BNG3 ports this bounded behavior at `5adb545` with the
  source-derived dependency-order contract in
  `tests/python/test_modern_atomizer_writer_parameters.py`; the focused modern
  Atomizer suite reports `78 passed`, and the full Python gate reports `253
  passed, 27 skipped, 8 warnings`. This does not close broader function,
  parser, or independent SBML/BNGL parity.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts` at reference main
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` keeps time-only reaction rates
  live by wrapping rates that contain `time()` but no species/observable
  marker in generated zero-argument functions. The tests-first BNG3 port is
  `f1eeebf91b2bcc976e0c2c49f54261bcfda9bcc5` in
  `python/bionetgen/atomizer/modern/writer.py`; the red-first output was
  `light: 0 -> M_B() 2 + time()`, and the repaired contract is
  `tests/python/test_modern_atomizer.py::test_playground_writer_wraps_time_only_rates_in_live_functions`.
  The focused modern Atomizer suite reports `79 passed`, the full Python gate
  reports `254 passed, 27 skipped, 9 warnings`, and exact-head Release/Ninja
  CTest reports `185/185`. This closes only the bounded time-rate writer
  slice; broader writer/parser/SBML parity remains open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:1331-1353,1650-1721,2374-2392`
  at reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` coalesces duplicate
  global parameter declarations when their values match, canonicalizes raw
  parameter IDs with `standardizeName`, remaps conflicting IDs to the next
  available suffix while emitting `SBM010`, and normalizes registered ID/name
  aliases in extracted math with local-parameter precedence. Its local-parameter
  loop also suffixes a duplicate canonical local ID using the source position
  before registering raw-ID and name aliases under the suffixed ID.
  The tests-first BNG3 checkpoints are `18e8d8fad1871fdda826c395af878ada5614382b`
  and `871d261442be2f4808cbcabed51f6a017ba5488a` plus the parameter-ID
  checkpoints `0810dc6c6e9fda597f3ced78119d95457631dbf0` and
  `6871518f50a3d1cb6b66490d7ba31f3cfe6531ab` in
  `python/bionetgen/atomizer/modern/parser.py`, with contracts in
  `tests/python/test_modern_atomizer.py::test_playground_parser_disambiguates_duplicate_global_parameters`,
  `tests/python/test_modern_atomizer.py::test_playground_parser_normalizes_duplicate_parameter_name_aliases_in_math`,
  `tests/python/test_modern_atomizer.py::test_playground_parser_standardizes_parameter_ids_before_formula_aliasing`,
  and `tests/python/test_modern_atomizer.py::test_playground_parser_suffixes_duplicate_local_parameter_ids`.
  The alias red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k normalizes_duplicate`
  reported `1 failed, 52 deselected`; the repaired duplicate-focused command
  reports `2 passed, 51 deselected`. The parameter-ID red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k standardizes_parameter_ids`
  reported `1 failed, 53 deselected`; the repaired combined command reports
  `3 passed, 51 deselected`. The duplicate-local red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k suffixes_duplicate_local`
  reported `1 failed, 54 deselected` with both emitted IDs equal to
  `time_id`; the repaired command reports `1 passed, 54 deselected`. The
  combined parser contract command reports `4 passed, 51 deselected`. The
  modern Atomizer glob reports `105 passed`, the full Python gate reports
  `280 passed, 27 skipped, 8 warnings` in `10.17s`, exact CTest reports
  `190/190` in `1.39s`, Ruff passes, and
  Black reports `186 files would be left unchanged`. This Python-only
  checkpoint leaves the native `build/cpp/bng_cpp` artifact unchanged at
  SHA-256 `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public PR/ref head readback is
  `6871518f50a3d1cb6b66490d7ba31f3cfe6531ab`; hosted CI
  [33700655331](https://github.com/RuleWorld/BNG3/actions/runs/33700655331),
  CodeQL [33700655336](https://github.com/RuleWorld/BNG3/actions/runs/33700655336),
  and formatting [33700655365](https://github.com/RuleWorld/BNG3/actions/runs/33700655365)
  were queued at readback. This closes duplicate-ID recovery and formula
  alias normalization plus canonical and duplicate-local parameter-ID recovery
  for the modern parser; broader parser/SBML parity, output alias propagation,
  and independent round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:1025-1065` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` groups seed declarations
  by canonical emitted pattern and fixedness, retains the first concentration
  for each group, and maps every source species ID to that grouped pattern.
  The tests-first BNG3 checkpoint is
  `bb3c116aeebcccbc8a7f123b2cc62d563308f57e` in
  `python/bionetgen/atomizer/modern/writer.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer.py::test_playground_writer_groups_duplicate_seed_patterns`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k groups_duplicate_seed_patterns`
  reported `1 failed, 55 deselected` because BNG3 emitted two identical seed
  declarations; the repaired command reports `1 passed, 55 deselected`. The
  contract also verifies that fixed and dynamic groups remain separate. The
  modern Atomizer glob reports `106 passed`, the full Python gate reports
  `281 passed, 27 skipped, 8 warnings` in `10.17s`, exact CTest reports
  `190/190` in `1.44s`, changed-file Ruff passes, and changed-file Black
  reports `2 files would be left unchanged`. This Python-only checkpoint
  leaves the native `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public PR/ref head readback is
  `bb3c116aeebcccbc8a7f123b2cc62d563308f57e`; hosted CodeQL
  [33701338037](https://github.com/RuleWorld/BNG3/actions/runs/33701338037),
  CI [33701338055](https://github.com/RuleWorld/BNG3/actions/runs/33701338055),
  and formatting
  [33701338204](https://github.com/RuleWorld/BNG3/actions/runs/33701338204)
  were queued at readback. This closes only duplicate seed-pattern grouping;
  broader writer/parser/SBML parity, fixed-seed provenance, and independent
  round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/core/structures.ts:337-360` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` builds a component-name `Map`
  before `Molecule.extend`; when a molecule contains repeated component names,
  the last existing component is the mapped target, while absent components are
  deep-copied and registered. The tests-first BNG3 checkpoint is
  `cd8d6faff52a188a3aff809bd2c7cd8bbab5bc14` in
  `python/bionetgen/atomizer/modern/structures.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer.py::test_playground_molecule_extend_updates_last_duplicate_component`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k updates_last_duplicate_component`
  reported `1 failed, 56 deselected` because Python updated the first duplicate;
  the repaired command reports `1 passed, 56 deselected`. The related structure
  contract command reports `6 passed, 51 deselected`, the modern Atomizer glob
  reports `107 passed`, the full Python gate reports `282 passed, 27 skipped,
  8 warnings` in `9.95s`, exact CTest reports `190/190` in `1.15s`, changed-file
  Ruff passes, changed-file Black reports `2 files would be left unchanged`,
  and `git diff --check` passes. This Python-only checkpoint leaves the native
  `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `cd8d6faff52a188a3aff809bd2c7cd8bbab5bc14`; hosted CodeQL
  [33701930187](https://github.com/RuleWorld/BNG3/actions/runs/33701930187), CI
  [33701930243](https://github.com/RuleWorld/BNG3/actions/runs/33701930243), and
  formatting [33701930296](https://github.com/RuleWorld/BNG3/actions/runs/33701930296)
  were queued at readback. This closes only the duplicate-component `extend`
  lookup slice; broader structure/core parity, repeated-site model semantics,
  and independent round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:271-330` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` returns modification inference as
  a named `{base, modification, confidence}` result, including the empty
  fallback result. The tests-first BNG3 checkpoint is
  `33cbd138f5dca0b4a0804601948fcf3cca329631` in
  `python/bionetgen/atomizer/modern/core.py`, with the facade export in
  `python/bionetgen/atomizer/modern/__init__.py` and the source-derived
  contract in
  `tests/python/test_modern_atomizer_core.py::test_playground_infer_modification_returns_named_result`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k infer_modification`
  reported `1 failed, 8 deselected` because the BNG3 result was a bare tuple
  without named fields. The repaired command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k infer_modification`
  reports `1 passed, 8 deselected` and verifies both named-field access and
  backward-compatible tuple unpacking. The core-plus-rulifier command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py tests/python/test_modern_atomizer_rulifier.py -q`
  reports `15 passed`; the modern Atomizer glob
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer*.py -q`
  reports `108 passed`; the full Python gate
  `env PYTHONPATH=python:build/cpp python -m pytest -q` reports
  `283 passed, 27 skipped, 8 warnings` in `12.51s`; exact CTest
  `ctest --test-dir build --output-on-failure` reports `190/190` in `1.52s`;
  `ruff check python/bionetgen/atomizer/modern/core.py python/bionetgen/atomizer/modern/__init__.py tests/python/test_modern_atomizer_core.py`
  passes; `black --check python/bionetgen/atomizer/modern/core.py
  python/bionetgen/atomizer/modern/__init__.py
  tests/python/test_modern_atomizer_core.py` reports `3 files would be left
  unchanged`; and `git diff --check` passes. This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `33cbd138f5dca0b4a0804601948fcf3cca329631`; hosted CI
  [33702740615](https://github.com/RuleWorld/BNG3/actions/runs/33702740615),
  CodeQL [33702740608](https://github.com/RuleWorld/BNG3/actions/runs/33702740608),
  and formatting
  [33702740639](https://github.com/RuleWorld/BNG3/actions/runs/33702740639)
  were queued at readback. This closes only the named-result API slice;
  broader atomization/core behavior, parser/writer parity, independent
  round-trip evidence, and provenance remain open.
- [x] Playground `src/lib/atomizer/index.ts:502-512` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` re-exports the eight core
  Atomizer APIs `buildSpeciesCompositionTable`,
  `disambiguateCollidingSpecies`, `getMoleculeTypes`, `getSeedSpecies`,
  `analyzeReactions`, `analyzeNamingConventions`, `topologicalSort`, and
  `classifyReaction`. The tests-first BNG3 checkpoint is
  `7afeb80c7969e93068ba19f8d030cf193fed5769` in
  `python/bionetgen/atomizer/modern/core.py` and
  `python/bionetgen/atomizer/modern/__init__.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer_core.py::test_playground_facade_exports_camel_case_core_functions`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k camel_case_core`
  reported `1 failed, 9 deselected` because the camel-case exports were
  absent. The repaired command reports `1 passed, 9 deselected`; the
  core-plus-rulifier command reports `16 passed`; the modern Atomizer glob
  reports `109 passed`; the full Python gate reports
  `284 passed, 27 skipped, 8 warnings` in `10.36s`; exact CTest
  `ctest --test-dir build --output-on-failure` reports `190/190` in `1.16s`;
  changed-file Ruff passes; changed-file Black reports `3 files would be
  left unchanged`; and `git diff --check` passes. This Python-only
  checkpoint leaves the native `build/cpp/bng_cpp` artifact unchanged at
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `7afeb80c7969e93068ba19f8d030cf193fed5769`; hosted CodeQL
  [33703241274](https://github.com/RuleWorld/BNG3/actions/runs/33703241274),
  formatting [33703241265](https://github.com/RuleWorld/BNG3/actions/runs/33703241265),
  and CI [33703241255](https://github.com/RuleWorld/BNG3/actions/runs/33703241255)
  were queued at readback. This closes only the public core-facade export
  slice; deeper Atomizer behavior, parser/writer/SBML parity, independent
  round-trip evidence, and provenance remain open.
- [x] Playground `src/lib/atomizer/index.ts:514-518` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` re-exports the existing writer
  functions `generateBNGL`, `bnglFunction`, and `bnglReaction`. The
  tests-first BNG3 checkpoint is
  `503541c25575622313c12e05c08e53861f47d4f3` in
  `python/bionetgen/atomizer/modern/writer.py` and
  `python/bionetgen/atomizer/modern/__init__.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer_writer_rate_helpers.py::test_playground_writer_facade_exports_reference_function_names`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_writer_rate_helpers.py -q -k writer_facade`
  reported `1 failed, 4 deselected` because the reference spellings were
  absent. The repaired command reports `1 passed, 4 deselected`; the writer
  glob
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_writer*.py -q`
  reports `15 passed`; the modern Atomizer glob
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer*.py -q`
  reports `110 passed`; the full Python gate
  `env PYTHONPATH=python:build/cpp python -m pytest -q` reports
  `285 passed, 27 skipped, 8 warnings` in `10.27s`; exact CTest
  `ctest --test-dir build --output-on-failure` reports `190/190` in `1.60s`;
  `ruff check python/bionetgen/atomizer/modern/writer.py python/bionetgen/atomizer/modern/__init__.py tests/python/test_modern_atomizer_writer_rate_helpers.py`
  passes; `black --check python/bionetgen/atomizer/modern/writer.py
  python/bionetgen/atomizer/modern/__init__.py
  tests/python/test_modern_atomizer_writer_rate_helpers.py` reports `3 files
  would be left unchanged`; and `git diff --check` passes. This Python-only
  checkpoint leaves the native `build/cpp/bng_cpp` artifact unchanged at
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `503541c25575622313c12e05c08e53861f47d4f3`; hosted CodeQL
  [33703490479](https://github.com/RuleWorld/BNG3/actions/runs/33703490479),
  formatting [33703490602](https://github.com/RuleWorld/BNG3/actions/runs/33703490602),
  and CI [33703490651](https://github.com/RuleWorld/BNG3/actions/runs/33703490651)
  were queued at readback. This closes only the writer facade-name slice;
  atomized/flat writer behavior, broader writer/parser/SBML parity,
  independent round-trip evidence, and provenance remain open.
- [x] Playground `src/lib/atomizer/core/structures.ts:19-181,191-489,490-1015`
  at reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes the
  camel-case Component, Molecule, and Species method surface used by the
  Atomizer core. The tests-first BNG3 implementation checkpoint is
  `0663b2effcaf8814fe9702f98c4690348655f810` in
  `python/bionetgen/atomizer/modern/structures.py`; the follow-up public
  cleanup checkpoint `220b1e2455968e12a987da777740c580f973a84e` removes
  redundant Action/Rule/Databases aliases without changing the tested
  structure surface. The source-derived contract is
  `tests/python/test_modern_atomizer_structures.py::test_playground_structures_expose_camel_case_object_methods`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_structures.py -q -k camel_case_object`
  reported `1 failed, 5 deselected` because `Component.addState` was absent;
  the repaired full structures-file command reports `6 passed in 0.40s`.
  The modern Atomizer glob reports `111 passed in 0.48s`; the full Python gate
  reports `286 passed, 27 skipped, 8 warnings` in `10.46s`; exact CTest reports
  `190/190` in `1.59s`; changed-file Ruff passes; changed-file Black reports
  `2 files would be left unchanged`; and `git diff --check` passes. This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `220b1e2455968e12a987da777740c580f973a84e`; hosted formatting
  [33704215080](https://github.com/RuleWorld/BNG3/actions/runs/33704215080), CI
  [33704215073](https://github.com/RuleWorld/BNG3/actions/runs/33704215073), and
  CodeQL [33704215158](https://github.com/RuleWorld/BNG3/actions/runs/33704215158)
  were queued at readback. This closes only the tested public method-name
  compatibility slice; broader structure behavior, repeated-site semantics,
  parser/writer/SBML parity, and independent round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/index.ts:64-453,468-500` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes camel-case Atomizer
  lifecycle/accessor methods (`setOptions`, `getOptions`, `flatTranslation`,
  `fullAtomization`, `getModel`, `getSCT`, `getUniProtIds`, `getDatabases`,
  `analyzeNaming`, and `analyzeReactionPatterns`) and the convenience
  functions `sbmlToBngl`, `sbmlToBnglFlat`, and `sbmlToBnglAtomized`. The
  tests-first BNG3 checkpoint is
  `d58c2a6fb2ed2c478ef6a6152077bc21d0ad42bc` in
  `python/bionetgen/atomizer/modern/__init__.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer.py::test_playground_atomizer_facade_exposes_reference_method_names`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k atomizer_facade`
  reported `1 failed, 57 deselected` because the reference facade names were
  absent; the repaired command reports `1 passed, 57 deselected`. The modern
  Atomizer glob reports `112 passed`; the full Python gate reports `287 passed,
  27 skipped, 8 warnings` in `10.24s`; exact CTest reports `190/190` in
  `1.24s`; changed-file Ruff passes; changed-file Black reports `2 files would
  be left unchanged`; and `git diff --check` passes. This Python-only
  checkpoint leaves the native `build/cpp/bng_cpp` artifact unchanged at
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `d58c2a6fb2ed2c478ef6a6152077bc21d0ad42bc`; hosted CodeQL
  [33704586351](https://github.com/RuleWorld/BNG3/actions/runs/33704586351), CI
  [33704586367](https://github.com/RuleWorld/BNG3/actions/runs/33704586367), and
  formatting
  [33704586407](https://github.com/RuleWorld/BNG3/actions/runs/33704586407)
  were queued at readback. This closes only the tested facade-name slice; the
  TypeScript async lifecycle, Databases/result object shapes, broader Atomizer
  behavior, parser/writer/SBML parity, and independent round-trip evidence
  remain open.
- [x] Playground `src/lib/atomizer/writer/bnglWriter.ts:2114-2857` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` returns the named
  `BNGLGenerationResult` fields `bngl`, `observableMap`, and `warnings`. The
  tests-first BNG3 checkpoint is
  `5afc84ecbb558092fca9ff2528655c175b574707` in
  `python/bionetgen/atomizer/modern/writer.py`, with the facade export in
  `python/bionetgen/atomizer/modern/__init__.py` and the source-derived
  contract in
  `tests/python/test_modern_atomizer_writer_rate_helpers.py::test_playground_generate_bngl_returns_named_generation_result`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_writer_rate_helpers.py -q -k named_generation`
  reported `1 failed, 5 deselected` because `generate_bngl` returned a bare
  tuple; the repaired command reports `1 passed, 5 deselected` and verifies
  named fields, the camel-case map alias, warnings, and legacy two-value
  unpacking. The writer glob reports `16 passed`; the modern Atomizer glob
  reports `113 passed`; the full Python gate reports `288 passed, 27 skipped,
  8 warnings` in `10.19s`; exact CTest reports `190/190` in `1.62s`;
  changed-file Ruff passes; changed-file Black reports `3 files would be left
  unchanged`; and `git diff --check` passes. This Python-only checkpoint
  leaves the native `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch head readback is
  `5afc84ecbb558092fca9ff2528655c175b574707`; hosted formatting
  [33704892921](https://github.com/RuleWorld/BNG3/actions/runs/33704892921), CI
  [33704892945](https://github.com/RuleWorld/BNG3/actions/runs/33704892945), and
  CodeQL [33704892981](https://github.com/RuleWorld/BNG3/actions/runs/33704892981)
  were queued at readback. This closes only the named generation-result and
  backward-compatible unpacking slice; warning-production parity, atomized and
  flat writer behavior, broader parser/SBML parity, and independent
  round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/config/types.ts:460-690` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes camel-case SBML,
  species-composition-table, seed-species, and result fields, including
  `spatialDimensions`, `initialConcentration`, `initialAmount`,
  `hasOnlySubstanceUnits`, `stoichiometrySet`, `mathML`, `localParameters`,
  `kineticLaw`, `useValuesFromTriggerTime`, `functionDefinitions`,
  `speciesByCompartment`, `importWarnings`, `sbmlId`, `isElemental`,
  `reverseDependencies`, `sortedSpecies`, and `observableMap`. The
  tests-first BNG3 checkpoint is
  `a2a35118bb6fa15cb772b4dfd02459dfae5d7190` in
  `python/bionetgen/atomizer/modern/types.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer_core.py::test_playground_data_contract_exposes_camel_case_fields`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k data_contract`
  reported `1 failed, 10 deselected` because `spatialDimensions` was absent;
  the repaired command reports `1 passed, 10 deselected`. The core file
  reports `11 passed`, the modern Atomizer glob reports `114 passed`, and the
  full Python gate reports `289 passed, 27 skipped, 8 warnings` in `15.63s`.
  Exact CTest reports `190/190` in `2.54s`; changed-file Ruff and Black pass;
  and `git diff --check` passes. This Python-only checkpoint leaves the native
  `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `a2a35118bb6fa15cb772b4dfd02459dfae5d7190`; the hosted checks listed at
  the top remain queued and are not completion evidence. This closes only the
  bounded data-field naming/mutability slice; broader source/Python result
  shapes, parser/writer/SBML behavior, and independent round-trip evidence
  remain open.
- [x] Playground `src/lib/atomizer/config/types.ts:481-546,643-651` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` defines the
  `compartmentType` field, `SBMLModifierSpeciesReference`, and structured
  `SBMLImportWarning` (`category`, `message`, `count`, and `severity`) record
  contracts. The tests-first BNG3 checkpoint is
  `667935b327409f07f74bb81fc7066b8295947b95` in
  `python/bionetgen/atomizer/modern/types.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer_core.py::test_playground_data_contract_exposes_missing_sbml_record_types`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k missing_sbml_record_types`
  reported `1 failed, 11 deselected` because `SBMLImportWarning` was absent;
  the repaired command reports `1 passed, 11 deselected`. The core file
  reports `12 passed`, the modern Atomizer glob reports `115 passed`, and the
  full Python gate reports `290 passed, 27 skipped, 8 warnings` in `14.85s`.
  Exact CTest reports `190/190` in `1.97s`; changed-file Ruff and Black pass;
  and `git diff --check` passes. This Python-only checkpoint leaves the native
  `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `667935b327409f07f74bb81fc7066b8295947b95`; hosted CI
  [33705751711](https://github.com/RuleWorld/BNG3/actions/runs/33705751711),
  CodeQL [33705751714](https://github.com/RuleWorld/BNG3/actions/runs/33705751714),
  and formatting [33705751719](https://github.com/RuleWorld/BNG3/actions/runs/33705751719)
  remain queued and are not completion evidence. This closes only the
  bounded record-type contract; parser warning instances remain dictionary
  shaped, modifier/reaction behavior remains broader work, and complete
  parser/writer/SBML parity and independent round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:376-390` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` maps each
  `SBMLModifierSpeciesReference` through its `species` field before returning
  a reaction pattern. The tests-first BNG3 checkpoint is
  `b9df8db49d574ccb5fc1f35bddf649073bd975ef` in
  `python/bionetgen/atomizer/modern/core.py` and
  `python/bionetgen/atomizer/modern/types.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer_core.py::test_playground_reaction_classification_normalizes_modifier_records`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k normalizes_modifier_records`
  reported `1 failed, 12 deselected` because the record object leaked into
  `ReactionPattern.modifiers`; the repaired command reports `1 passed, 12
  deselected`. The core file reports `13 passed`, the modern Atomizer glob
  reports `116 passed`, and the full Python gate reports `291 passed, 27
  skipped, 8 warnings` in `15.30s`. Exact CTest reports `190/190` in `1.92s`;
  changed-file Ruff and Black pass; and `git diff --check` passes. This
  Python-only checkpoint leaves the native `build/cpp/bng_cpp` artifact
  unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `b9df8db49d574ccb5fc1f35bddf649073bd975ef`; hosted CI
  [33706954325](https://github.com/RuleWorld/BNG3/actions/runs/33706954325),
  CodeQL [33706954333](https://github.com/RuleWorld/BNG3/actions/runs/33706954333),
  and formatting [33706954323](https://github.com/RuleWorld/BNG3/actions/runs/33706954323)
  remain queued and are not completion evidence. This closes only object
  modifier normalization in reaction classification; constructors and
  downstream classification retain legacy string compatibility while the XML
  parser now emits source-shaped records, and broader reaction/parser,
  writer/SBML, and independent round-trip parity remain open.
- [x] Playground `src/lib/atomizer/writer/eventActions.ts:30-44,138-158,178-207`
  at reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes the
  `EventSet`, `EventTranslationContext`, and `EventActionsResult` contracts
  plus the `foldNumeric` and `parseTimeThreshold` helper spellings. The
  tests-first BNG3 checkpoint is
  `43afe69b83b9d994b9bb103dfad304e0e3b4509c` in
  `python/bionetgen/atomizer/modern/events.py` and
  `python/bionetgen/atomizer/modern/__init__.py`, with the source-derived
  contract in
  `tests/python/test_modern_atomizer_events.py::test_playground_event_actions_exposes_reference_names_and_result_fields`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_events.py -q`
  reported `1 failed` because `EventActionsResult` was absent; the repaired
  command reports `1 passed`. The existing event behavior contract reports
  `3 passed, 55 deselected`; the modern Atomizer glob reports `117 passed`;
  the full Python gate reports `292 passed, 27 skipped, 8 warnings` in
  `14.91s`; exact CTest reports `190/190` in `1.89s`; changed-file Ruff and
  Black pass; and `git diff --check` passes. This Python-only checkpoint
  leaves the native `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `43afe69b83b9d994b9bb103dfad304e0e3b4509c`; hosted CI
  [33707224496](https://github.com/RuleWorld/BNG3/actions/runs/33707224496),
  CodeQL [33707224180](https://github.com/RuleWorld/BNG3/actions/runs/33707224180),
  and formatting [33707224186](https://github.com/RuleWorld/BNG3/actions/runs/33707224186)
  remain queued and are not completion evidence. This closes only the
  bounded reference names and writable context/result aliases; Python keeps
  tuple-shaped untranslated diagnostics and existing scheduling internals,
  while complete event semantics and broader writer/SBML parity remain open.
- [x] Playground `src/lib/atomizer/core/structures.ts:143-151` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes `Component.toString()` as
  the rule-style string representation. The tests-first BNG3 checkpoint is
  `99e12f5920bbb5d830fee08bd9fa896dffc3cecd` in
  `python/bionetgen/atomizer/modern/structures.py`, with the source-derived
  assertion in
  `tests/python/test_modern_atomizer_structures.py::test_playground_structures_expose_camel_case_object_methods`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_structures.py -q -k camel_case_object`
  reported `1 failed, 5 deselected` because the alias was absent; the repaired
  command reports `1 passed, 5 deselected`. The structure file reports `6
  passed`; the modern Atomizer glob reports `117 passed`; the full Python gate
  reports `292 passed, 27 skipped, 8 warnings` in `14.67s`; exact CTest reports
  `190/190` in `1.89s`; changed-file Ruff and Black pass; and
  `git diff --check` passes. This Python-only checkpoint leaves the native
  `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `99e12f5920bbb5d830fee08bd9fa896dffc3cecd`; hosted CI
  [33707406164](https://github.com/RuleWorld/BNG3/actions/runs/33707406164),
  CodeQL [33707406204](https://github.com/RuleWorld/BNG3/actions/runs/33707406204),
  and formatting [33707406092](https://github.com/RuleWorld/BNG3/actions/runs/33707406092)
  remain queued and are not completion evidence. This closes only the
  remaining tested Component method-name alias; broader structure behavior,
  repeated-site semantics, parser/writer/SBML parity, and independent
  round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/core/structures.ts:1179-1205` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exports the
  `readFromString` BNGL-pattern parser helper. The tests-first BNG3 checkpoint
  is `4c84b37c302e4a4ec9d59cf40c106729b8085e97` in
  `python/bionetgen/atomizer/modern/structures.py` and
  `python/bionetgen/atomizer/modern/__init__.py`, with the source-derived
  assertion in
  `tests/python/test_modern_atomizer_structures.py::test_playground_structures_expose_camel_case_object_methods`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_structures.py -q -k camel_case_object`
  reported `1 failed, 5 deselected` because the facade alias was absent; the
  repaired command reports `1 passed, 5 deselected`. The structure file
  reports `6 passed`; the modern Atomizer glob reports `117 passed`; the full
  Python gate reports `292 passed, 27 skipped, 8 warnings` in `14.88s`; exact
  CTest reports `190/190` in `1.93s`; changed-file Ruff and Black pass; and
  `git diff --check` passes. This Python-only checkpoint leaves the native
  `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `4c84b37c302e4a4ec9d59cf40c106729b8085e97`; hosted CI
  [33707604898](https://github.com/RuleWorld/BNG3/actions/runs/33707604898),
  CodeQL [33707604817](https://github.com/RuleWorld/BNG3/actions/runs/33707604817),
  and formatting [33707604823](https://github.com/RuleWorld/BNG3/actions/runs/33707604823)
  remain queued and are not completion evidence. This closes only the
  source-compatible helper spelling; broader parser semantics, structure
  behavior, writer/SBML parity, and independent round-trip evidence remain
  open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:1559-1570` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` preserves an SBML
  compartment's `compartmentType` reference when extracting the model. The
  tests-first BNG3 checkpoint is
  `e25766e2867adf07925bdedf0244b370f9f43b95` in
  `python/bionetgen/atomizer/modern/parser.py`, with the source-derived XML
  contract in
  `tests/python/test_modern_atomizer.py::test_playground_parser_preserves_compartment_type_reference`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k preserves_compartment_type_reference`
  reported `1 failed, 58 deselected` because the parsed field was `None`; the
  repaired command reports `1 passed, 58 deselected`. The parser subset reports
  `14 passed, 46 deselected`; the modern Atomizer glob reports `118 passed`;
  the full Python gate reports `293 passed, 27 skipped, 8 warnings` in
  `15.04s`; exact CTest reports `190/190` in `2.08s`; changed-file Ruff and
  Black pass; and `git diff --check` passes. This Python-only checkpoint
  leaves the native `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `e25766e2867adf07925bdedf0244b370f9f43b95`; hosted CI
  [33707794248](https://github.com/RuleWorld/BNG3/actions/runs/33707794248),
  CodeQL [33707794247](https://github.com/RuleWorld/BNG3/actions/runs/33707794247),
  and formatting [33707794244](https://github.com/RuleWorld/BNG3/actions/runs/33707794244)
  remain queued and are not completion evidence. This closes only the
  compartment-type extraction slice; broader SBML parser behavior, writer
  parity, and independent round-trip evidence remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:2339-2346` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` extracts reaction
  modifiers as `SBMLModifierSpeciesReference` records. The tests-first BNG3
  checkpoint is `753e57b42b9562ca1f2b6e06c948579d6e4f0b82` in
  `python/bionetgen/atomizer/modern/parser.py`, with the source-derived XML
  contract in
  `tests/python/test_modern_atomizer.py::test_playground_parser_preserves_modifier_species_records`.
  The red-first command
  `env PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k preserves_modifier_species_records`
  reported `1 failed, 59 deselected` because the parser returned a bare string;
  the repaired command reports `1 passed, 59 deselected`. The parser subset
  reports `14 passed, 46 deselected`; the modern Atomizer glob reports `119
  passed`; the full Python gate reports `294 passed, 27 skipped, 8 warnings`
  in `15.04s`; exact CTest reports `190/190` in `2.01s`; changed-file Ruff
  and Black pass; and `git diff --check` passes. This Python-only checkpoint
  leaves the native `build/cpp/bng_cpp` artifact unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `753e57b42b9562ca1f2b6e06c948579d6e4f0b82`; hosted CI
  [33707948107](https://github.com/RuleWorld/BNG3/actions/runs/33707948107),
  CodeQL [33707948104](https://github.com/RuleWorld/BNG3/actions/runs/33707948104),
  and formatting [33707948098](https://github.com/RuleWorld/BNG3/actions/runs/33707948098)
  remain queued and are not completion evidence. This closes only XML parser
  modifier-record extraction; constructor compatibility is retained, while
  broader reaction/parser, writer/SBML, and independent round-trip parity
  remain open.
- [x] Playground `src/lib/atomizer/config/types.ts:640-651` and
  `src/lib/atomizer/parser/sbmlParser.ts:803-809,1517-1519` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` represent `importWarnings` as
  structured records with `category`, `message`, `count`, and the
  `dropped`/`approximated`/`info` severity contract. The tests-first BNG3
  checkpoint is `be9d6a25a02f20bad7182b9ea8409c37fdc137e9` in
  `python/bionetgen/atomizer/modern/types.py`, `parser.py`, and `writer.py`;
  `SBMLImportWarning` exposes the source-shaped attributes and a mapping view
  so existing dictionary consumers remain compatible, while parser and writer
  paths normalize legacy dictionaries at their model boundary. The red-first
  command
  `PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer_core.py -q -k structured_import_warning_records`
  reported `1 failed, 13 deselected`; the repaired command reports `1 passed,
  13 deselected`. The focused modern-core/parser regression command reports
  `74 passed`; the modern Atomizer glob reports `120 passed`; the full Python
  gate reports `295 passed, 27 skipped, 8 warnings` in `15.97s`; the exact
  Release/Ninja CTest gate reports `190/190` in `2.31s`; the export gate reports
  `12 passed`; Ruff/Black and `git diff --check` pass. The native
  `build/cpp/bng_cpp` artifact remains unchanged at SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `be9d6a25a02f20bad7182b9ea8409c37fdc137e9`; hosted CI
  [33708860933](https://github.com/RuleWorld/BNG3/actions/runs/33708860933),
  CodeQL [33708860926](https://github.com/RuleWorld/BNG3/actions/runs/33708860926),
  and formatting
  [33708860908](https://github.com/RuleWorld/BNG3/actions/runs/33708860908)
  remain queued and are not completion evidence. This closes only the
  structured-warning data contract; complete parser diagnostics, writer/SBML
  parity, independent round trips, and release validation remain open.
- [x] Playground `src/lib/atomizer/config/types.ts:579-594` and
  `src/lib/atomizer/parser/sbmlParser.ts:2645-2682` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` represent event assignments as
  structured `{variable, math}` records. The tests-first BNG3 checkpoint is
  `eefdf3b9fb147b1d0558b7b213ecd315f98017cb` in
  `python/bionetgen/atomizer/modern/types.py`, `events.py`, and `writer.py`;
  `SBMLEventAssignment` exposes source-shaped attributes, string-key mapping
  access, and legacy tuple equality while event translation and diagnostics
  accept the structured record. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k source_shaped_event_assignment_records`
  reported `1 failed, 60 deselected` because the public record type was absent;
  the repaired event/record command reports `4 passed, 57 deselected`. The
  modern regression command reports `76 passed`; the modern Atomizer glob
  reports `121 passed`; the full Python gate reports `296 passed, 27 skipped,
  8 warnings` in `15.30s`; exact Release/Ninja CTest reports `190/190` in
  `1.81s`; and export validation reports `12 passed` in `18.54s`. Changed-file
  Ruff and Black pass (`4 files would be left unchanged`), and `git diff
  --check` passes. The native `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `eefdf3b9fb147b1d0558b7b213ecd315f98017cb`; hosted CI
  [33712428796](https://github.com/RuleWorld/BNG3/actions/runs/33712428796),
  CodeQL [33712428667](https://github.com/RuleWorld/BNG3/actions/runs/33712428667),
  and formatting
  [33712428660](https://github.com/RuleWorld/BNG3/actions/runs/33712428660)
  remain pending and are not completion evidence. This closes only the
  source-shaped event-assignment data contract; broader event semantics,
  parser/writer/SBML parity, independent round trips, and release validation
  remain open.
- [x] Playground `src/lib/atomizer/utils/helpers.ts:608-616,645-721` and
  `src/lib/atomizer/index.ts:99-205` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` return structured `LogMessage`
  records in every successful or failed `AtomizerResult.log`. The tests-first
  BNG3 checkpoint is `4be16b1b904087b3db0f01cd5ab2c801d7c5ddee` in
  `python/bionetgen/atomizer/modern/__init__.py`, `types.py`, and
  `tests/python/test_modern_atomizer.py`; the existing logger records are now
  returned instead of summary strings on both fast and normal paths, including
  failure diagnostics. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest tests/python/test_modern_atomizer.py -q -k result_returns_structured_log_records`
  reported `1 failed, 61 deselected, 2 warnings`; the repaired command with
  `-p no:cacheprovider` reports `1 passed, 61 deselected`. The focused
  lifecycle/fast-path/facade command reports `3 passed`; the modern Atomizer
  glob reports `122 passed`; the full Python gate reports `297 passed, 27
  skipped, 8 warnings` in `15.97s`; exact Release/Ninja CTest reports `190/190`
  in `1.93s`; and export validation reports `12 passed` in `18.71s`. Changed-
  file Ruff (`--no-cache`) passes, Black reports `3 files would be left
  unchanged`, and `git diff --check` passes. The native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `4be16b1b904087b3db0f01cd5ab2c801d7c5ddee`; hosted CI
  [33712957959](https://github.com/RuleWorld/BNG3/actions/runs/33712957959),
  CodeQL [33712957955](https://github.com/RuleWorld/BNG3/actions/runs/33712957955),
  and formatting
  [33712957961](https://github.com/RuleWorld/BNG3/actions/runs/33712957961)
  remain pending and are not completion evidence. This closes only structured
  result-log records; the source asynchronous `initialize()` lifecycle has no
  direct synchronous Python equivalent, and broader parser/writer/SBML parity,
  independent round trips, and release validation remain open.
- [x] Playground `src/lib/atomizer/core/structures.ts:1113-1152` and
  `src/lib/atomizer/index.ts:43-59,129-132,184-199,375-380,453-457` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` construct and return a
  `Databases` container from the Atomizer accessor, result, and `clear()` lifecycle.
  The tests-first BNG3 checkpoint is
  `fc65e25292927e7c3a8e02d684cda63f5921738f` in
  `python/bionetgen/atomizer/modern/__init__.py` and
  `tests/python/test_modern_atomizer.py`; the prior dictionary substitution is
  removed from both fast and normal paths, and the result/accessor now preserve
  the same `Databases` object. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer.py -q -k returns_databases_container`
  reported `1 failed, 62 deselected`; the repaired focused command reports
  `4 passed, 59 deselected`. The modern Atomizer glob reports `123 passed`; the
  full Python gate reports `298 passed, 27 skipped, 8 warnings` in `14.98s`;
  exact Release/Ninja CTest reports `190/190` in `1.64s`; and export validation
  reports `12 passed` in `18.45s`. Changed-file Ruff (`--no-cache`) passes,
  Black reports `2 files would be left unchanged`, and `git diff --check`
  passes. The native `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `fc65e25292927e7c3a8e02d684cda63f5921738f`; hosted CI
  [33713386928](https://github.com/RuleWorld/BNG3/actions/runs/33713386928),
  CodeQL [33713386951](https://github.com/RuleWorld/BNG3/actions/runs/33713386951),
  and formatting
  [33713386952](https://github.com/RuleWorld/BNG3/actions/runs/33713386952)
  remain queued and are not completion evidence. This closes the result
  container shape only; the source TypeScript `Map` containers are represented
  by existing Python mapping fields, and broader parser/writer/SBML parity,
  independent round trips, direct-NFsim, and release validation remain open.
- [x] Playground `src/lib/atomizer/validation/multiPackage.ts:30-41,78-91,167-176,226-242`
  at reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` types every
  `MultiParseResult.warnings` entry as an `SBMLImportWarning` record. The
  tests-first BNG3 checkpoint is
  `c52cc97986dd2fd09d44a0d276e54a92596af162` in
  `python/bionetgen/atomizer/modern/multi.py` and
  `tests/python/test_modern_atomizer_multi.py`; direct Multi parsing now
  returns the structured record while its mapping view preserves existing
  dictionary-style consumers. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_multi.py -q -k structured_warning`
  reported `1 failed, 2 deselected`; the repaired full Multi-file command
  reports `3 passed`. The modern Atomizer glob reports `124 passed`; the full
  Python gate reports `299 passed, 27 skipped, 8 warnings` in `15.59s`;
  exact Release/Ninja CTest reports `190/190` in `1.77s`; and export validation
  reports `12 passed` in `19.49s`. Changed-file Ruff (`--no-cache`) passes,
  Black reports `2 files would be left unchanged`, and `git diff --check`
  passes. The native `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `c52cc97986dd2fd09d44a0d276e54a92596af162`; hosted CI
  [33713756152](https://github.com/RuleWorld/BNG3/actions/runs/33713756152),
  CodeQL [33713756197](https://github.com/RuleWorld/BNG3/actions/runs/33713756197),
  and formatting
  [33713756179](https://github.com/RuleWorld/BNG3/actions/runs/33713756179)
  remain queued and are not completion evidence. This closes the direct
  Multi warning-record shape only; canonical/deep Multi structures remain
  commented diagnostics and are not injected into the simulated network,
  with full Multi reconstruction, writer/schema, execution, and broader
  parser/SBML parity still open.
- [x] Playground `src/lib/atomizer/validation/multiPackage.ts:30-41,179-242`
  at reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` exposes camel-case
  `MultiParseResult` fields and object-shaped `complexPatterns` entries with
  `typeId` and `pattern`. The tests-first BNG3 checkpoint is
  `0b611ec6b72e1390ff1b48f923ae756574e3afbc` in
  `python/bionetgen/atomizer/modern/multi.py` and
  `tests/python/test_modern_atomizer_multi.py`; Python now returns the
  source-shaped record while retaining tuple unpacking for existing parser
  consumers. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_multi.py -q -k reference_result`
  reported `1 failed, 3 deselected`; the repaired full Multi-file command
  reports `4 passed`. The modern Atomizer glob reports `125 passed`; the full
  Python gate reports `300 passed, 27 skipped, 8 warnings` in `14.95s`;
  exact Release/Ninja CTest reports `190/190` in `1.57s`; and export validation
  reports `12 passed` in `18.60s`. Changed-file Ruff (`--no-cache`) passes,
  Black reports `2 files would be left unchanged`, and `git diff --check`
  passes. The native `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `0b611ec6b72e1390ff1b48f923ae756574e3afbc`; hosted CI
  [33714138583](https://github.com/RuleWorld/BNG3/actions/runs/33714138583),
  CodeQL [33714138588](https://github.com/RuleWorld/BNG3/actions/runs/33714138588),
  and formatting
  [33714138602](https://github.com/RuleWorld/BNG3/actions/runs/33714138602)
  remain queued and are not completion evidence. This closes only the direct
  Multi result-record shape; seed patterns remain unconstructed, extracted
  structures remain commented diagnostics, full Multi writer/schema and
  simulation validation remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:1963-1989,2083-2109`
  at reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` records explicit,
  deduplicated diagnostics for lossy `<cn>/<sep/>`, `<infinity>`,
  `<notanumber>`, `<factorial>`, `<gcd>`, and `<lcm>` MathML constructs. The
  tests-first BNG3 checkpoint is
  `6ff6911d643a02d3ee9d064c762471fe50d9972f` in
  `python/bionetgen/atomizer/modern/parser.py` and
  `tests/python/test_modern_atomizer.py`. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer.py -q -k lossy_mathml_constants_and_operators`
  reported `1 failed, 63 deselected in 0.52s`; the repaired focused command
  reports `1 passed, 63 deselected in 0.40s`. The modern Atomizer glob reports
  `126 passed in 0.58s`; the full Python gate reports
  `301 passed, 27 skipped, 8 warnings` in `14.85s`; exact Release/Ninja CTest
  reports `190/190` in `1.46s`; and export validation reports `12 passed` in
  `18.29s`. Changed-file Ruff (`--no-cache`) passes, Black with the configured
  `--target-version py312` reports `2 files would be left unchanged`, and
  `git diff --check` passes. The native `build/cpp/bng_cpp` artifact remains
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `6ff6911d643a02d3ee9d064c762471fe50d9972f`; hosted CI
  [33715166102](https://github.com/RuleWorld/BNG3/actions/runs/33715166102),
  CodeQL [33715166047](https://github.com/RuleWorld/BNG3/actions/runs/33715166047),
  and formatting
  [33715166057](https://github.com/RuleWorld/BNG3/actions/runs/33715166057)
  remain queued and are not completion evidence. This closes only the
  explicit diagnostics slice; complete MathML translation, schema and
  round-trip coverage, remaining parser/writer/SBML parity, SBML-Multi,
  direct-NFsim, legacy, packaging, release, and hosted validation gaps remain
  open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:1129-1160` and
  `src/lib/atomizer/index.ts:22-30` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` export the source-shaped
  `reconcileSCT` facade for filling missing molecule components from finalized
  molecule types. BNG3 already carried the matching snake-case implementation;
  the tests-first compatibility checkpoint is
  `dd7c0dec44278bf62b03497089ad0e777bf482a6` in
  `python/bionetgen/atomizer/modern/core.py`,
  `python/bionetgen/atomizer/modern/__init__.py`, and
  `tests/python/test_modern_atomizer_core.py`. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_core.py -q -k camel_case_core`
  reported `1 failed, 13 deselected in 0.55s`; the repaired command reports
  `1 passed, 13 deselected in 0.37s`. The modern Atomizer glob reports
  `126 passed in 0.59s`; the full Python gate reports
  `301 passed, 27 skipped, 8 warnings` in `15.58s`; exact Release/Ninja CTest
  reports `190/190` in `1.57s`. Changed-file Ruff (`--no-cache`) passes, Black
  with the configured `--target-version py312` reports `3 files would be left
  unchanged`, and `git diff --check` passes. The native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `dd7c0dec44278bf62b03497089ad0e777bf482a6`; hosted CI
  [33715585114](https://github.com/RuleWorld/BNG3/actions/runs/33715585114),
  CodeQL [33715585019](https://github.com/RuleWorld/BNG3/actions/runs/33715585019),
  and formatting
  [33715585115](https://github.com/RuleWorld/BNG3/actions/runs/33715585115)
  remain queued and are not completion evidence. This closes only the
  source-compatible facade name; deeper core behavior, parser/writer/SBML
  parity, independent round trips, SBML-Multi, direct-NFsim, and release
  validation remain open.
- [x] Playground `src/lib/atomizer/parser/sbmlParser.ts:2293-2302` at
  reference `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` preserves L2 rational
  species-reference stoichiometry by dividing the parsed numerator by a finite,
  nonzero `denominator` attribute. The tests-first BNG3 checkpoint is
  `7d729a041a4aba6eacb8f23c6b0e0af262379ee9` in
  `python/bionetgen/atomizer/modern/parser.py` and
  `tests/python/test_modern_atomizer.py`. The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer.py -q -k preserves_l2_rational_stoichiometry`
  reported `1 failed, 64 deselected in 0.66s`; the repaired focused command
  reports `1 passed, 64 deselected in 0.40s`. The modern Atomizer glob reports
  `127 passed in 0.57s`; the full Python gate reports
  `302 passed, 27 skipped, 8 warnings` in `14.89s`; exact Release/Ninja CTest
  reports `190/190` in `1.63s`. Changed-file Ruff (`--no-cache`) passes, Black
  with the configured `--target-version py312` reports `2 files would be left
  unchanged`, and `git diff --check` passes. The native
  `build/cpp/bng_cpp` artifact remains SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `7d729a041a4aba6eacb8f23c6b0e0af262379ee9`; hosted CI
  [33716014298](https://github.com/RuleWorld/BNG3/actions/runs/33716014298),
  CodeQL [33716014300](https://github.com/RuleWorld/BNG3/actions/runs/33716014300),
  and formatting
  [33716014299](https://github.com/RuleWorld/BNG3/actions/runs/33716014299)
  remain queued and are not completion evidence. This closes only L2 rational
  denominator preservation; broader stoichiometry, parser/writer/SBML,
  independent round-trip, SBML-Multi, direct-NFsim, and release validation
  gaps remain open.
- [x] Playground `src/lib/atomizer/config/types.ts:325-405` and
  `src/lib/atomizer/index.ts:43-91` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` names the supported constructor
  and `setOptions` fields `useId`, `quietMode`, `logLevel`, `tEnd`, and
  `nSteps`. BNG3 normalizes those source spellings to its existing snake-case
  option mapping at `beb0cee6424e94b64d6014febde355e30908299f` in
  `python/bionetgen/atomizer/modern/__init__.py`; other source
  `AtomizerOptions` fields remain explicitly outside this bounded port. The
  tests-first contract is
  `tests/python/test_modern_atomizer.py::test_playground_atomizer_accepts_supported_source_option_spellings`.
  The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer.py -q -k accepts_supported_source_option_spellings`
  reported `1 failed, 65 deselected in 0.58s`; the repaired focused command
  reports `1 passed, 65 deselected in 0.40s`. The modern Atomizer glob reports
  `128 passed in 0.55s`; the full Python gate reports `303 passed, 27 skipped,
  8 warnings` in `16.14s`; exact Release/Ninja CTest reports `190/190` in
  `1.70s`. Changed-file Ruff (`--no-cache`) passes, Black with the configured
  `--target-version py312` reports `2 files would be left unchanged`, and
  `git diff --check` passes. The native `build/cpp/bng_cpp` artifact remains
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `beb0cee6424e94b64d6014febde355e30908299f`; hosted CI
  [33716598867](https://github.com/RuleWorld/BNG3/actions/runs/33716598867),
  CodeQL [33716598872](https://github.com/RuleWorld/BNG3/actions/runs/33716598872),
  and formatting
  [33716598870](https://github.com/RuleWorld/BNG3/actions/runs/33716598870)
  remain queued and are not completion evidence. This closes only the source
  option spelling boundary; broader Atomizer behavior, parser/writer/SBML
  parity, independent round trips, SBML-Multi, direct-NFsim, legacy,
  packaging, release, and hosted validation gaps remain open.
- [x] Playground `src/lib/atomizer/config/types.ts:154-228` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` classifies the documented long
  modification, binding, localization, dimerization, and trimerization name
  patterns in `DEFAULT_NAMING_CONVENTIONS.patterns`. BNG3 ports the complete
  pattern-map slice at `f64f46791db06e4204ed49e5a33cb9e923fde3cc` in
  `python/bionetgen/atomizer/modern/types.py`, preserving the existing
  tuple-key Python representation. The tests-first contract is
  `tests/python/test_modern_atomizer_core.py::test_playground_default_naming_patterns_cover_source_words`.
  The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_core.py -q -k default_naming_patterns_cover_source_words`
  reported `13 failed, 14 deselected in 0.53s`; the repaired focused command
  reports `13 passed, 14 deselected in 0.35s`. The complete core test file
  reports `27 passed in 0.36s`; the modern Atomizer glob reports `141 passed in
  0.60s`; the full Python gate reports `316 passed, 27 skipped, 8 warnings`
  in `15.38s`; exact Release/Ninja CTest reports `190/190` in `1.72s`.
  Changed-file Ruff (`--no-cache`) passes, Black with the configured
  `--target-version py312` reports `2 files would be left unchanged`, and
  `git diff --check` passes. The native `build/cpp/bng_cpp` artifact remains
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `f64f46791db06e4204ed49e5a33cb9e923fde3cc`; hosted CI
  [33716982357](https://github.com/RuleWorld/BNG3/actions/runs/33716982357),
  CodeQL [33716982281](https://github.com/RuleWorld/BNG3/actions/runs/33716982281),
  and formatting
  [33716982433](https://github.com/RuleWorld/BNG3/actions/runs/33716982433)
  remain queued and are not completion evidence. This closes only the default
  pattern-map slice; the richer TypeScript naming-convention configuration,
  broader Atomizer behavior, parser/writer/SBML parity, independent round
  trips, SBML-Multi, direct-NFsim, legacy, packaging, release, and hosted
  validation gaps remain open.
- [x] Playground `src/lib/atomizer/atomization/core.ts:227-265` at reference
  `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` serializes each distinct naming
  difference list as a compact JSON string in the `analyzeNamingConventions`
  result's `keys` field. BNG3 matches that result shape at
  `655810d5e2ea65dc25204f234333a30f170229b1` in
  `python/bionetgen/atomizer/modern/core.py`. The tests-first contract is
  `tests/python/test_modern_atomizer_core.py::test_playground_naming_analysis_returns_json_string_keys`.
  The red-first command
  `PYTHONPATH=python:build/cpp python -m pytest -p no:cacheprovider tests/python/test_modern_atomizer_core.py -q -k naming_analysis_returns_json_string_keys`
  reported `1 failed, 27 deselected in 0.39s`; the repaired focused command
  reports `1 passed, 27 deselected in 0.33s`. The complete core test file
  reports `28 passed in 0.39s`; the modern Atomizer glob reports `142 passed in
  0.61s`; the full Python gate reports `317 passed, 27 skipped, 8 warnings`
  in `14.92s`; exact Release/Ninja CTest reports `190/190` in `1.42s`.
  Changed-file Ruff (`--no-cache`) passes, Black with the configured
  `--target-version py312` reports `2 files would be left unchanged`, and
  `git diff --check` passes. The native `build/cpp/bng_cpp` artifact remains
  SHA-256
  `949bfff3ea4581a5158df1aa107c21687ef6b848e4692c66215483f315e87d82`.
  Exact public branch and PR #2 head readback is
  `655810d5e2ea65dc25204f234333a30f170229b1`; hosted CI
  [33717241703](https://github.com/RuleWorld/BNG3/actions/runs/33717241703),
  CodeQL [33717241701](https://github.com/RuleWorld/BNG3/actions/runs/33717241701),
  and formatting
  [33717241763](https://github.com/RuleWorld/BNG3/actions/runs/33717241763)
  remain queued and are not completion evidence. This closes only the naming
  analysis key-shape slice; the richer TypeScript naming-convention
  configuration, broader Atomizer behavior, parser/writer/SBML parity,
  independent round trips, SBML-Multi, direct-NFsim, legacy, packaging,
  release, and hosted validation gaps remain open.
- [ ] Complete or explicitly govern remaining modern reference modules:
  atomization/core, parser/bngXmlParser and parser/sbmlParser,
  validation/units, writer/bnglWriter, writer/eventActions, and
  writer/sbmlWriter.
- [ ] Compare Atomizer molecule/site/state semantics, bond/wildcard handling,
  compartments, seed species, observables, rules, rate laws, annotations,
  names, and provenance against source-derived fixtures.
- [ ] Route Atomizer output through the canonical parser/AST boundary or record
  a reviewed reason for any supported exception.
- [ ] Network failures, missing annotations, unsupported constructs, and
  partial conversions produce explicit diagnostics rather than silent loss.

### 7.2 SBML import/export

- [ ] SBML XML is schema-valid when the relevant validator is available and
  always well-formed with stable diagnostics otherwise.
- [ ] MathML translation covers approved arithmetic, functions, constants,
  roots/log bases, identifiers, namespaces, and escaping.
- [ ] Compartments, units, conversion factors, NumberPerQuantityUnit,
  concentration/amount semantics, non-finite values, non-integer
  stoichiometry, and zero stoichiometry have semantic round-trip tests.
- [ ] Rate rules, assignment rules, initial assignments, events, algebraic
  rules, constraints, fast reactions, and package declarations are either
  implemented with evidence or fail with an explicit governed diagnostic.
- [ ] SBML IDs and display names remain distinct and stable through generated
  parameters, observables, functions, seeds, and reaction rates.
- [x] The validation-corpus structured-SBML `atomize=>1` fixture `plain2` now
  passes the native reader and graph-aware `.net` comparison at
  `78a1591422ccbe6c4a5607eb748b426bbdbc303f`. The implementation is deliberately
  narrow and fail-closed for other structured SBML models.
- [x] Static, acyclic initial-assignment seed dependencies with piecewise
  conditions fold to numeric BNGL seed amounts. Regression:
  `tests/python/test_modern_atomizer.py::test_playground_writer_resolves_piecewise_initial_assignment_seed_dependencies`
  (including an unselected divide-by-zero branch). Curated BioModels
  `BIOMD0000000429` now passes flat and Atomized SBML round trips and all 30
  observable comparisons against libRoadRunner 2.10.0; input SHA-256
  `a1353c11190c33b80c881cb4ed5ad9a8cd41facf89d1efc5c73a22cde561c839`;
  report `/private/tmp/bng3-biomodel-0429-final-roundtrip.json`
  (SHA-256 `ea33737bae5efb0e7de27ac4fab180ddb92add092bd42af2c3255f93b8165b5e`).
  The full curated inventory has not been rerun, so this closes only the
  selected model path.
- [ ] The structured SBML atomize=>1 failure is resolved or receives a
  maintainer-approved compatibility disposition with a replacement gate.
- [ ] Unsupported SBML packages, qualitative models, dictionaries, and
  topology cases are reported in an inspectable unsupported-feature report.

### 7.3 SBML-Multi

- [x] Current parser detects and exposes conservative canonical single-level
  Multi structures as reference diagnostics.
- [x] Executable SBML Multi v1 reconstruction checkpoint
  `c48c758` on dedicated branch `codex/sbml-multi-full-work-v2` expands the
  modern Atomizer path to resolve the released namespace and package grammar,
  spec-valid unqualified attributes on Multi-defined elements plus strict
  namespace placement for Multi extensions to core/MathML elements, SBML
  primitive lexical rules,
  spec-scoped identifier collisions, scoped/nested component indexes, atomic
  binding-site types, species types, feature states and occurrences,
  in-species bonds, explicit/don't-care species patterns, fully defined
  positive initial pools including core `initialAssignment` targets, Multi
  product component maps, compartment references,
  `intraSpeciesReaction`, MathML `sum`/`numericValue` representations,
  component-scoped feature IDs, one-to-one bond validation, and strict
  reaction/map identifier checks, and core initial-assignment target/MathML
  validation. Component-index resolution is declaration-order independent and
  accepts valid SpeciesType identifying parents; compartment-type instances,
  nested compartment propagation, binding-site feature inheritance, outward
  binding-site ID uniqueness, relation=`and` occurrence constraints, and
  type-only definitions are covered. Nested component indexes resolve through
  indexed parents for feature and bond scopes; component indexes may target
  either a component instance or a nested SpeciesType object. Multi hierarchies
  without an unambiguous BNGL molecule boundary fail closed instead of being
  flattened. Repeated nested features on binding-site components and
  unsupported feature-count or sub-compartment-reference MathML `ci` semantics
  also fail closed with explicit diagnostics. Core
  Reaction-derived Multi identifiers, species-feature identifiers, and
  compartment-reference identifiers are checked in their complete SBML/Multi
  scopes. Invalid or non-representable structures fail closed with structured
  diagnostics.
  Core metadata and foreign package annotations are preserved without false
  rejection. The real fixture
  `tests/validation/Validate/test_write_sbml_multi_sbml_sbmlmulti.xml`
  produces executable BNGL and parses through the native `bng_cpp` oracle.
  Focused Multi tests report `45 passed, 3 skipped`; full Python reports `390
  passed, 30 skipped`; CTest reports `291/291`; Ruff, C++ syntax, and `git
  diff --check` pass.
- [x] Canonical Multi molecule types, components, states, complexes,
  species/seed patterns, bonds, compartments, product maps, and diagnostics
  are reconstructed from the real fixture plus spec-derived tests.
- [x] Multi output is emitted through the supported C++ writer with libSBML
  consistency checks and semantic parser round-trip tests.
- [x] Independent NFsim execution parity is covered for a representative
  Multi binding model; the local gate builds standalone NFsim from source
  revision `a6f9fa945c9d6e1e122e789c952260112c93f157` outside BNG3 and runs a
  positive-time `0.1` simulation, producing a time-series output. The tested
  binary SHA-256 is
  `b5c5c4c82855a5084301bfe4a8d0c2bdc20b7ee996b6e3c868f9575862e916eb`.
  Multi-derived structures enter execution only after the parser and oracle
  gates pass; hosted/pinned Tier-NF qualification remains open.
- [ ] Full SBML-Multi simulation, not merely diagnostics/comments, passes Tier-X
  and representative NF/network gates.

### 7.4 All supported formats and graph writers

- [ ] BNGL import/export is semantically round-trippable.
- [x] Curated BioModels `BIOMD0000000202` now completes flat and Atomized
  SBML-to-BNGL-to-SBML routes after preserving explicit site-free `M_...()`
  molecule names through reimport and keeping numeric active state `0`
  unchanged. Regressions cover both behaviors. Both round-trip networks
  contain 8 species and 16 reactions; all 17 observables pass against
  libRoadRunner 2.10.0.
  Source SHA-256 `c841590d8ed0e219d5a0cc0d761030ddf00f898a1bfafb2fa705d9aa07322506`;
  report `/private/tmp/bng3-biomodel-0202-final-roundtrip.json` (SHA-256
  `40a5e1c8863b8f18b539ebcf90c1a39dc630b25b4dd6a54ff8ba9d21e1a43f18`).
  This closes one selected model path, not the general format gate.
- [ ] BNG-XML import/export is well-formed, schema/semantic validated, and
  preserves supported annotations and rate laws.
- [ ] NET write/read/write is idempotent and graph-aware.
- [ ] SBML and SBML-Multi round trips preserve supported dynamics and metadata.
- [ ] MATLAB/MEX, LaTeX, SSC, MDL, and all documented graph exports have
  non-empty, valid, semantically checked outputs.
- [ ] Contact-map, regulatory, rule-influence, reaction-network, RuleViz
  pattern/operation, and process graph writers are covered.
- [ ] Every writer has one authoritative implementation or an approved
  compatibility disposition; Python and Perl duplicates are not silently used
  on the default path.

## 8. CI, platform, security, and release

### 8.1 CI truthfulness

- [x] Historical exact semantic PR head
  `0f833470950fc47329f5b7381c64533e623b45ce` has a complete terminal hosted
  check set for C++, Python, validation, integration, formatting, ASan, and
  CodeQL: CI run [33493581633](https://github.com/RuleWorld/BNG3/actions/runs/33493581633),
  CodeQL run [33493581605](https://github.com/RuleWorld/BNG3/actions/runs/33493581605),
  and formatting run [33493581573](https://github.com/RuleWorld/BNG3/actions/runs/33493581573)
  all passed for this SHA. Pull-request release-only jobs were skipped by
  event conditions and remain release-candidate work. This documentation
  refresh creates a new public head and requires another exact-head check
  readback after push.
- [ ] Historical public semantic checkpoint
  `44d8655d3b0d838dc33420c0d7800c12bb465785` has not yet acquired a terminal
  hosted check set. At exact-head readback, CI run
  [33565168766](https://github.com/RuleWorld/BNG3/actions/runs/33565168766),
  formatting run
  [33565168844](https://github.com/RuleWorld/BNG3/actions/runs/33565168844),
  and CodeQL run
  [33565168898](https://github.com/RuleWorld/BNG3/actions/runs/33565168898)
  were queued; queued or partial results are not completion evidence. The PR
  #2 metadata and branch ref agreed on
  `44d8655d3b0d838dc33420c0d7800c12bb465785` immediately after push. Every
  later semantic or documentation checkpoint requires a fresh exact-head
  readback.
- [ ] Historical public checklist head
  `b8dfd027e50b81737c5e8b59f225f9085149f3c0` had fresh hosted runs, all
  queued at readback: CI
  [33567163033](https://github.com/RuleWorld/BNG3/actions/runs/33567163033),
  formatting patch
  [33567163155](https://github.com/RuleWorld/BNG3/actions/runs/33567163155),
  and CodeQL
  [33567163054](https://github.com/RuleWorld/BNG3/actions/runs/33567163054).
  Queued status is not validation evidence.
- [ ] Latest published checklist checkpoint
  `7b53663d32b35ec1df4057b6a2832d79b0152577` has fresh hosted runs, all
  pending at readback: CI
  [33568454975](https://github.com/RuleWorld/BNG3/actions/runs/33568454975),
  formatting patch
  [33568454932](https://github.com/RuleWorld/BNG3/actions/runs/33568454932),
  and CodeQL
  [33568454970](https://github.com/RuleWorld/BNG3/actions/runs/33568454970).
  These checks qualify only `7b53663`; pending status is not validation
  evidence.
- [ ] Current public semantic checkpoint
  `ead6b8e1513f819ec91571aa0e5ead49aa119a8c` has not yet acquired a terminal
  hosted check set. At exact-head readback, CI run
  [33570349978](https://github.com/RuleWorld/BNG3/actions/runs/33570349978),
  formatting patch run
  [33570350028](https://github.com/RuleWorld/BNG3/actions/runs/33570350028),
  and CodeQL run
  [33570349982](https://github.com/RuleWorld/BNG3/actions/runs/33570349982)
  were pending for this exact SHA. Queued or partial results are not
  completion evidence; the checklist refresh itself requires another
  exact-head readback.
- [ ] Current public semantic checkpoint
  `4edf4df57f01d22f15d83ee6635b82e974b0e6dc` has not yet acquired a terminal
  hosted check set. At exact-head readback, CI run
  [33571418085](https://github.com/RuleWorld/BNG3/actions/runs/33571418085),
  formatting patch run
  [33571418104](https://github.com/RuleWorld/BNG3/actions/runs/33571418104),
  and CodeQL run
  [33571418139](https://github.com/RuleWorld/BNG3/actions/runs/33571418139)
  were queued for this exact SHA. Queued or partial results are not
  completion evidence; the next checklist documentation head requires a
  fresh exact-head readback.
- [ ] Current public semantic checkpoint
  `88f4e548ed8b7ef43cfc57aa62ad7b7914205613` has not yet acquired a terminal
  hosted check set. At exact-head readback, CI run
  [33572711786](https://github.com/RuleWorld/BNG3/actions/runs/33572711786),
  formatting patch run
  [33572711779](https://github.com/RuleWorld/BNG3/actions/runs/33572711779),
  and CodeQL run
  [33572711794](https://github.com/RuleWorld/BNG3/actions/runs/33572711794)
  were queued for this exact SHA. Queued or partial results are not
  completion evidence; the next checklist documentation head requires a
  fresh exact-head readback.
- [ ] Current public semantic checkpoint
  `7241746a50ed0f87f23ad93eda38b2a9e7cca180` has not yet acquired a terminal
  hosted check set. At exact-head readback, CI run
  [33574600510](https://github.com/RuleWorld/BNG3/actions/runs/33574600510),
  formatting patch run
  [33574600516](https://github.com/RuleWorld/BNG3/actions/runs/33574600516),
  and CodeQL run
  [33574600570](https://github.com/RuleWorld/BNG3/actions/runs/33574600570)
  were queued for this exact SHA. Queued or partial results are not
  completion evidence; the next checklist documentation head requires a
  fresh exact-head readback.
- [ ] Current public semantic checkpoint
  `413523620b1903f7152a27ee6441b0b4d07b933b` has not yet acquired a terminal
  hosted check set. At exact-head readback, CI
  [33576632616](https://github.com/RuleWorld/BNG3/actions/runs/33576632616),
  formatting patch
  [33576632625](https://github.com/RuleWorld/BNG3/actions/runs/33576632625),
  and CodeQL [33576632624](https://github.com/RuleWorld/BNG3/actions/runs/33576632624)
  were queued for this exact SHA. Queued or partial results are not
  completion evidence; the next checklist documentation head requires a
  fresh exact-head readback.
- [x] CI truthfulness repair checkpoint
  `e7cd59bd793a30d31bf2b8822725e05ba097b3d0` has a source-derived local
  fail-closed workflow contract (`8 passed`) and an exact public branch/PR
  readback. Its CI, formatting, and CodeQL runs
  [33575648537](https://github.com/RuleWorld/BNG3/actions/runs/33575648537),
  [33575648574](https://github.com/RuleWorld/BNG3/actions/runs/33575648574),
  and [33575648533](https://github.com/RuleWorld/BNG3/actions/runs/33575648533)
  were queued at readback. This repair does not check the final hosted gate,
  weekly corpus, independent oracle, or release-candidate requirements.
- [x] Strict-reference validation checkpoint
  `0e2642aa239c569f66eb550db6c0952219060142` is wired into the PR and weekly
  reference jobs, with the current exclusions explicit. Hosted CI
  [33577070603](https://github.com/RuleWorld/BNG3/actions/runs/33577070603),
  formatting [33577070621](https://github.com/RuleWorld/BNG3/actions/runs/33577070621),
  and CodeQL [33577070593](https://github.com/RuleWorld/BNG3/actions/runs/33577070593)
  were queued at readback. Queued status is not completion evidence, and the
  35 exclusions remain validation gaps.
- [x] CI validation-governance checkpoint
  `4ed849f98f80b9139e0df018f8835025aa6b6410` centralizes the PR and weekly
  reference exclusions in `tests/validation/reference_exclusions.json`, adds
  strict profile loading to `scripts/validate.py`, and runs the source-derived
  CI contract tests in the hosted lint job. Six stale passing exclusions
  (`michment_cont`, `test_sbml_flat`, `Repressilator`, `SHP2_base_model`,
  `Motivating_example_cBNGL`, and `blbr`) were removed; the current local
  profiled validation reports `40` passes, `0` failures, `0` errors, and `31`
  explicit skips. The focused contract reports `13 passed`; the proportional
  exact-tree CTest/Python gates report `185/185` and `241 passed, 27 skipped,
  8 warnings`. The manifest remains pending maintainer approval, and its 30
  missing-reference entries plus one unsupported native SBML path remain open
  validation gaps rather than completion evidence. Public branch and PR #2
  read back to this exact SHA; CI [33579480347](https://github.com/RuleWorld/BNG3/actions/runs/33579480347),
  formatting [33579480344](https://github.com/RuleWorld/BNG3/actions/runs/33579480344),
  and CodeQL [33579480349](https://github.com/RuleWorld/BNG3/actions/runs/33579480349)
  were queued at readback.
- [ ] Every required job emits a terminal summary with counts, failures,
  skips, exception budget, corpus/source revision, and artifact digests.
- [ ] Required jobs fail when a claimed oracle, corpus, validator, or compiler
  asset is unavailable.
- [ ] No required test is suppressed by || true or an equivalent mechanism.
- [ ] Parse-only inventory jobs are named and described as parse-only; they do
  not imply NFsim execution or scientific parity.
- [ ] Formatting/autofix jobs report a patch or fail with remediation; they do
  not commit or push to contributor branches.
- [ ] Path-based selection is connected to a complete capability-to-test map;
  full main/nightly coverage prevents a path-map omission from becoming a
  permanent blind spot.
- [ ] Required PR fast, targeted, main, nightly, weekly, and release-candidate
  layers are enabled and reviewed.
- [ ] CODEOWNERS and domain approval requirements cover scientific semantics,
  comparators, tolerances, exceptions, provenance, and compatibility changes.

### 8.2 Platform and quality gates

- [ ] Supported Linux, macOS, Windows, compiler, Python, and architecture
  builds pass on the exact release candidate.
- [ ] C++ unit tests, Python API tests, validation tiers, ASan/UBSan/leak
  checks, and integration tests pass without hidden infrastructure failures.
- [ ] Performance benchmarks, memory budgets, and reproducibility rebuilds
  pass their approved thresholds.
- [x] The benchmark runner supports selected models, repeated fresh
  parse/generation runs, generation-only mode, and cross-run network-count
  checks. Its three-run `simple_system` smoke produced 4 species/4 reactions;
  see `/private/tmp/bng3-simple-system-generation.json` (SHA-256
  `3034af37d84717221582572d5f0dc47e411a7c79f91556941d378a48b85de97e`). This
  does not establish the Atomizer matcher speedup or satisfy benchmark gates.
- [x] Evaluated and reverted a candidate one-pass molecule-type prefilter
  after 25-run BNG3 measurements on `blbr`: baseline 19.079 ms median
  (0.278 ms SD), candidate 18.996 ms median (0.421 ms SD), with identical
  20-species/92-reaction output. The difference is within run variation; the
  pre-existing repeated per-type scan remains in production. Reports:
  `/private/tmp/bng3-blbr-generation-before.json` (SHA-256
  `697e4726818cb8f3e4b1d98ccb6f92f33b3b08cbad6525022fdbbea3d00e805f`) and
  `/private/tmp/bng3-blbr-generation-after.json` (SHA-256
  `aa9bc9e4c14d9af97a40ee6eb1c0beaec9265ab25a245b55c75a06b41c508a29`). The
  standard five-model benchmark was active during both runs, so this remains
  exploratory and establishes no speedup.
- [ ] Complete a controlled before/after network-generation and memory
  benchmark for PR #24's Atomizer copy path. The original unbounded five-model
  runner was terminated with SIGTERM after producing no result report; bounded
  repeated runs now use selectable model sets and generation-only mode.
- [x] The multi-type reactant matching regression verifies an
  `A().B()` rule fires on the mixed species and does not match the `A()`-only
  seed; it passes in the exact-tree CTest run `441/441`.
- [ ] CodeQL or equivalent security analysis passes on the exact release head.
- [ ] Hosted weekly full validation and cross-validation complete with
  independent BNG2/NFsim inputs, not just parser inventory.

### 8.3 Packaging and release

- [x] Corrected the package repository URL in `pyproject.toml` to
  `https://github.com/RuleWorld/BNG3`.
- [ ] Complete the pyproject metadata audit: supported Python range, dependency
  policy, package data, and extension contents still require isolated artifact
  builds and installed-package checks.
- [x] The pull-request package-smoke job builds and installs a source
  distribution on the exact head (CI run
  [33449613101](https://github.com/RuleWorld/BNG3/actions/runs/33449613101));
  release-candidate provenance and the complete artifact matrix remain open.
- [ ] Clean isolated wheels build for every supported platform/architecture.
- [ ] Installed-wheel tests cover import, compiled extension loading, API,
  CLI, embedded assets, plotting/data helpers, and representative scientific
  smoke behavior.
- [ ] CLI binaries and optional native NFsim artifacts are built and tested
  where promised.
- [ ] Docker/container artifacts build, run, and have recorded base-image
  digests where supported.
- [ ] Release artifacts are content-addressed, reproducible, and tied to the
  exact validated SHA.
- [ ] The release workflow cannot publish an unqualified tag or artifacts
  lacking the approved provenance/golden report.
- [ ] PyPI/test-index publication is staged or dry-run verified before the
  first public release.
- [ ] Hosted release jobs for source distribution, wheels, Docker, and
  publication are actually exercised for the release candidate; PR-only
  skipped jobs are not counted as evidence.

## 9. Legacy repositories and governance

- [ ] BioNetGen, NFsim, and PyBioNetGen source deltas through the accepted
  cutoff are reconciled, rejected with rationale, or tracked as blockers.
- [ ] Duplicate Nauty, redundant Network3 solver trees, duplicate model copies,
  unreachable notebook wrappers, and other redundant code have explicit
  delete lists and zero-reference evidence before removal.
- [ ] BNG2 Perl and native NFsim oracle sources/artifacts remain buildable and
  retained for the supported validation window.
- [ ] BNG3 is documented as the sole forward-development repository.
- [ ] External repositories have documented maintenance/retirement state,
  migration guidance, contribution redirects, and issue-routing policy.
- [ ] No production component retains two authoritative implementations after
  consolidation.
- [ ] Every deletion has a separate reviewable checkpoint after its parity,
  compatibility, packaging, and rollback gates pass.

## 10. Documentation and operational consistency

- [ ] BNG3_INTEGRATION_PLAN.md, docs/BNG3_unification_spec.md, AGENTS.md,
  provenance/README.md, validation/README.md, and this checklist agree on
  current gates, command paths, statuses, and ownership.
- [ ] Dated progress counts and hosted run references are refreshed after each
  semantic checkpoint; stale historical numbers are labeled as historical.
- [ ] The small pre-existing grammar fix remains preserved and is not mixed
  into implementation commits.
- [ ] Every unsupported capability has a user-visible diagnostic, owner,
  tracking issue, migration path, and review/expiry date.
- [ ] Developer build/test/release commands are reproducible from a clean
  checkout and document required oracle assets.
- [ ] API, CLI, compatibility, deprecation, and release migration documents
  are published before deleting supported legacy entry points.
- [ ] Documentation/link checks run in CI.

## 11. Exact release-candidate qualification

Run the following on a clean checkout of the exact candidate SHA. Adapt paths
only when the approved environment requires it; record the actual commands and
versions in the release evidence.

    git pull --ff-only
    git status --short
    git rev-parse HEAD
    cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
    cmake --build build
    ctest --test-dir build --output-on-failure
    PYTHONPATH=python:build/cpp python -m pytest tests/python -q
    black --check --target-version py312 python/ tests/python/ scripts/
    ruff check python/ tests/python/ scripts/
    git diff --check
    python scripts/validate_provenance.py --require-approved
    python scripts/validate_corpus_manifest.py
    python scripts/generate_corpus_manifest.py --check
    python -m tests.validation.exception_ledger --max-exceptions APPROVED_BUDGET
    python scripts/validate.py --bng-cpp build/cpp/bng_cpp --strict-references --validation-manifest tests/validation/validation_manifest.json
    python scripts/validate_actions.py --bng-cpp build/cpp/bng_cpp
    PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m smoke --bng-cpp build/cpp/bng_cpp
    PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m "parity and not slow" --bng-cpp build/cpp/bng_cpp
    NFSIM_BIN=build/cpp/NFsim PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m nf --bng-cpp build/cpp/bng_cpp
    PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m export --bng-cpp build/cpp/bng_cpp
    python -m build --sdist --wheel
    gh pr view 10 --repo RuleWorld/BNG3
    gh pr checks 10 --repo RuleWorld/BNG3

The qualification record must include:

- exact candidate SHA and clean-tree status;
- compiler, Python, CMake, dependency, platform, and container versions;
- complete local test counts and terminal summaries;
- independent BNG2/NFsim/PyBioNetGen artifact digests;
- RuleHub selection and golden-manifest digests;
- comparator versions, tolerances, seeds, time grids, and statistical results;
- every skip/error and its approved ledger entry;
- installed wheel, source distribution, CLI, Docker, and publication results;
- hosted CI, validation, integration, and CodeQL links for the same SHA.

## 12. Current blockers at the audited checkpoint

These are known unchecked requirements, not reasons to claim completion:

- Source lock, oracle recipes/artifact digests, compiler images, Python lock
  digest, owners, and RuleHub selectors remain pending maintainer approval.
- No provenance-complete approved golden bundle or complete reconciliation
  ledger is present.
- Capability-matrix oracle fields remain pending; broad independent BNG2,
  NFsim, and PyBioNetGen parity is not established by local tests.
- The compact energy evaluator is ported through shared partner-pool indexing,
  batched add/remove propensity updates, cached compact rate-factor refresh
  (`963d01b`), specialized reverse propensities (`dbadea6`), a source-derived
  direct-product endpoint identity snapshot used by fired membership refresh
  (`4a2fc3e`), safe direct-product traversal (`738c881`), and cached
  single-/multi-term Arrhenius rate factors (`6b6e246`), cached simple pre-fire
  binding rejection (`bd29714`), candidate bitset/mapping-slot indexing
  (`401becf`), deferred multi-product propensity accounting (`6c681269`),
  sparse selector integration (`a97c02e`) and cached implicit sparse-batch
  old-propensity reuse (`88f4e54`, source `4bb24b3`), guarded Release-LTO
  configuration (`7241746`, source `301bfbeb`), indexed cross-type partner
  endpoint/decision refresh (`bb3ae014`), source-derived pure-context
  complex counting (`bb14a207`), sparse type-invariant membership-decision
  indexing (`fbfda3f`), and endpoint-refined membership refresh decisions
  from NFsim commit `ced6f60` (`464bd8d`), and all-forward compact partner-pool
  early return from NFsim commit `fd01d015` (`2940a02`), plus connected
  membership order/template coverage from NFsim commits `051e7e2` and
  `23436e2` (`c7dd52d`), plus reusable connectivity direct-product lookup
  scratch from NFsim commit `96be0b1` (`a2d7f6c`), plus the functional
  symmetry/TotalRate correction from NFsim commits `2778162` and `1b19611`
  (`53a3d3d`), plus compact sorted/inline reaction-membership IDs from NFsim
  commits `ad4b56a` and `4007795` (`3fb3373`, `0560c3b`), plus lazy
  direct-product lookup allocation from NFsim commit `2b3c643` (`2c0b999`).
  The direct-AST energy fixtures now cover BNG2-compatible
  one-way binding and state-change directionality, including the compact
  forward-only path (`72dd033`, `ba52c20`). Merged NFSIM PR #475 full
  incremental-membership semantics, remaining direct-product parity,
  independent energy parity, benchmark provenance, and source reconciliation
  are still open.
- cpp/nfsim/nauty24 and the NFsim ExprTk path remain in the build; the
  canonical-label and shared-expression master-function migrations are not
  complete.
- Direct NFsim remains a bounded subset with visible XML fallback/shadow
  machinery; protocol-NF, remaining function/rate-law, broader Tier-NF, and
  full independent evidence remain open. The exact AN2 and IfTest trajectories
  are green checkpoints, not substitutes for that broader gate.
- Fixed-seed direct/API NFsim endpoint parity for `motor` and `tlbr` is now
  covered by the independent native-oracle contract at `7186b65`; broader
  direct-NFsim corpus, protocol, and three-way evidence remain open.
- The source-derived NFsim Issue86 species-observable dependency-refresh
  regression is covered by the current `7186b65` 13-assertion AST adapter
  test; its independent native-NFsim reduced-fixture cross-check is historical
  `852793f` evidence and does not close the broader function/rate-law or
  Tier-NF gates.
- The NFsim validation harness now refuses to infer independence from a
  BNG3-built binary when `NFSIM_BIN` is absent or invalid. The required
  independently built oracle path, source revision, binary digest, and
  reproducibility recipe still need maintainer approval and hosted execution.
- The source-derived IfTest conditional-function branch and current-head direct
  console route are green, including the `reactant_1` mapper and independent
  seeded trajectory. The source-derived AN2 trajectory is exact at `e92b2c9`;
  remaining direct-NFsim parity work is the broader Tier-NF corpus, protocol,
  and other capability gates below.
- Source performance commit `0463a1f4`'s applicable Macro slice is now ported
  and linked at `4edf4df`, with source-derived `num_site` and `pre_macr`
  contracts. Full Macro/legacy compatibility, independent benchmark evidence,
  and release qualification remain open.
- Structured SBML atomization now has a native, independently compared
  `plain2` validation-corpus path; other `atomize=>1` requests still fail
  closed pending broader support or an approved compatibility disposition.
  Broader validation tiers retain explicitly classified environment/reference
  skips, while the full PR/weekly corpus gate reports zero fixture skips.
- SBML-Multi v1 representable structures now enter executable modern
  Atomizer/BNGL paths with native writer/parser and NFsim evidence;
  unsupported shapes still fail closed, and full Tier-X capability remains
  open.
- Legacy Python core/modelapi/network/simulator trees remain and have not
  passed zero-reference deletion gates.
- Atomizer writer/helper/parser parity and all format round trips remain
  broader than the current modern test slices.
- Package metadata/repository URL review, current-head clean release
  sdist/wheel matrices,
  Docker, publication, and release-artifact provenance remain open; hosted
  PR release jobs were skipped by event conditions.
- Focused source-derived checkpoints now cover modern helper/rate-rule
  constants, selected atomization/core helpers, and selected writer facades;
  broad Atomizer writer/parser/SBML parity is still open.
- CODEOWNERS and complete domain approval enforcement remain open even though
  AGENTS.md exists.
- Historical progress text in the integration plan must be refreshed as later
  checkpoints land.

## 13. Recommended execution order

1. Obtain maintainer decisions and complete the source/oracle/provenance
   baseline without changing scientific tolerances.
2. Build independent golden and reconciliation evidence; repair validation
   infrastructure so missing assets fail honestly.
3. Complete graph canonicalization and expression master functions, then run
   full BNG2/NFsim differential gates.
4. Finish the direct NFsim mapping and three-way shadow gate before removing
   XML fallback.
5. Finish Atomizer/SBML/SBML-Multi semantics and all supported format
   round trips.
6. Freeze Python/CLI compatibility, then remove redundant default-path trees
   in isolated deletion checkpoints.
7. Complete CI ownership, platform, benchmark, clean-package, release, and
   provenance gates on one exact candidate SHA.
8. Publish migration/maintenance decisions and only then claim BNG3
   convergence.

No completion claim is valid until the checklist, the capability matrix, the
unification work orders, and the exact release evidence all agree.

## Full curated BioModels refresh after ODE rate-name fix — 2026-09-25

- [x] Reran all 1,096 curated records in flat and Atomized modes after fixing
  `OdeIntegrator`'s unanchored derived-rate fallback. Inventory matched 1,075
  declared SBML records plus 8 archive-extracted SBML files; 13 other records
  remain explicit non-SBML/unsupported-format inventory entries.
- [x] Both modes now pass 652 SBML records, classify 298 SBML records as
  unsupported, and time out on 133. There are zero numerical or other failed
  records. `BIOMD0000000584` now passes both modes, including all 56 observable
  comparisons against libRoadRunner. Aggregate corpus gate remains open due to
  unsupported records and timeouts.
- [x] Exact report:
  `/private/tmp/bng3-curated-post-ode-ratefix.json`, SHA-256
  `ec12c4c1b41947346c963c867280d831512a5e254cbd6f2ab6e6270f258ba108`.
  Command used the offline published-BioModels manifest, both modes, isolated
  model processes, 8 workers, and the existing 90-second per-model cutoff.
- [x] Rerun the full SBML Test Suite on this exact working tree after the ODE
  rate-name fix; prior suite counts predate that fix.
- [ ] The curated and SBML Test Suite gates still require explicit support or
  reviewed compatibility dispositions for unsupported semantics and model
  timeouts. No release qualification follows from this corpus update.
- [x] The post-fix full SBML Test Suite rerun completed all 1,923 canonical
  cases at suite revision `cf38585fac5de8e0e90112febb62851ee2181816` on the
  current working tree: 869 passed, 1,054 unsupported, 0 failed, and 0 timed
  out. Semantic cases: 869 passed and 954 unsupported; all 100 stochastic
  cases remain unsupported. Each pass includes Atomizer import, network
  generation, SBML write/reimport, native-reader checks, and all-observable
  BNG3 CVODE/libRoadRunner CVODE comparison. Reference-result conformance was
  not run. Report `/private/tmp/bng3-sbml-suite-post-ode-ratefix.json`,
  SHA-256 `afc05cec62e1453a025a00d01052e17e66691ebbbee16ff7b3a6fd452087c61f`.
- [ ] The SBML Test Suite core gate remains open because 1,054 cases are
  explicitly unsupported; the full result does not qualify release.

## Atomizer cross-engine benchmark — 2026-09-25

- [x] Added repeatable harness
  `benchmarks/benchmark_atomizer_cross_engine.py`. It runs modern BNG3 and
  independent PyBioNetGen legacy Atomizers in flat and Atomized modes, feeds
  each output BNGL model to both BNG3 and Perl BNG2, records three-repeat
  conversion and network timings, hashes outputs, and reports structural
  parity separately from rate-expression parity. Run instructions are in
  `benchmarks/README.md`.
- [x] Ran two curated models, `BIOMD0000000584` and `BIOMD0000000202`, in both
  modes, three repetitions each. Modern BNG3 Atomizer outputs generated
  structurally matching BNG2/BNG3 networks in all 12 runs: 21 species/14
  reactions for `0584`, and 8 species/16 reactions for `0202`. Rate-expression
  comparison remains fail-closed and failed all 12 runs due to differing
  function/rate serialization; this is not reported as rate equivalence.
- [x] The legacy PyBioNetGen Atomizer completed only some conversions and did
  not produce a BNG2-parseable network in any successful run. Observed causes
  include unresolved `LAMDAR_ar`, `fRate*`, and `S2_ar` symbols, BNGL parse
  errors, `NameError: longEnough`, and an `IndexError` in annotation matching.
  Its raw output hash also varied between repeats on two model/mode cases.
  These failures are recorded as compatibility gaps, not waived.
- [x] Report:
  `/private/tmp/bng3-atomizer-cross-engine-584-0202.json`, SHA-256
  `170c11f7965c601d42d60591b38633df29e45b05776b4d98e929e161ff6513f1`.
  It records Git heads, dirty-state hashes, and relevant BNG3 Atomizer/C++
  source hashes. On this macOS arm64 / CPython 3.14 host, modern Atomizer
  medians ranged from 25.4–25.6 ms for `0202` to 267.7–296.4 ms for `0584`;
  successful legacy medians ranged from 354.9–546.5 ms. BNG3/BNG2 network
  process medians were 12.3–16.6/87.6–111.4 ms on the modern outputs. These
  are bounded timings from this host, not cross-platform performance claims.
- [ ] Extend Atomizer cross-engine measurements to the full supported curated
  and SBML Test Suite intersections; resolve rate serializer comparisons and
  add eligible NFsim trajectory comparisons. This two-model report is a
  harness smoke and partial evidence only.

## NFsim invalid-propensity handling and Atomizer ensemble boundary — 2026-09-25

- [x] Fixed embedded NFsim's negative functional-propensity path to raise a
  named error instead of calling `GlobalFunction::printDetails()` when the
  reaction is backed by a composite function. The old path dereferenced null
  and crashed the Python process. ASan reproduced the null dereference; the
  same seed after the change returns a clear invalid-propensity error.
- [x] Added `benchmarks/benchmark_atomizer_nfsim.py` to compare fresh-process
  BNG3 direct NFsim and standalone NFsim ensembles, with the latter consuming
  BNG-XML written by Perl BNG2. Failed seeds are recorded and suppress ensemble
  mean comparisons to avoid censoring bias.
- [x] Ran 200 seeds in flat and Atomized modes on curated model
  `BIOMD0000001037`. Both modes had 197 valid trajectories and the same invalid
  seeds (8, 149, 194); each invalid trajectory produces a negative propensity
  in reaction `R3`. BNG3 now reports this cleanly. Standalone NFsim segfaults
  on those invalid trajectories, so this model is not eligible for an
  unbiased NFsim ensemble comparison. No ensemble-parity result is claimed.
- [x] Report `/private/tmp/bng3-atomizer-nfsim-1037-flat-atomized-200runs.json`,
  SHA-256 `ac3976e97346286976a5e2f81a891d0880df724c3f0fd2c49362b81c7b0f2f29`.
  Its process medians include Python startup and are not simulator-only
  performance measurements.
- [ ] Select curated models with valid stochastic semantics and complete
  matched BNG3/standalone NFsim ensemble gates. Six eligible cases are now
  covered by the endpoint correction below; broad corpus coverage remains
  open. The invalid-model probe does not qualify a release.

## NFsim final-sample boundary and Atomizer ensemble parity — 2026-09-25

- [x] Traced the direct-vs-standalone discrepancy to the BNG3 binding firing
  the pending reaction that crossed the final requested sample. Native NFsim
  writes the sample before firing that event. Removed the special final-step
  event inclusion from `System::stepTo` and the binding; all sampled values now
  use the same exclusive stopping-time semantics.
- [x] Added a focused regression: a birth reaction with a waiting time beyond
  a very short simulation horizon leaves the final observable at zero. The
  prior exact-seed native test encoded an incorrect endpoint assumption and
  was removed; exact trajectories remain separate from ensemble evidence.
- [x] Rebuilt the CPython 3.14 extension. Focused Python tests for final-sample
  exclusion and accumulated sample-grid parity pass (2 passed); the full
  `test_cpp_backend.py` file passes (68 passed). An exact-seed comparison
  against standalone NFsim still shows a one-event difference at the last
  point on `motor` and `tlbr`; those cases are not claimed as exact trajectory
  matches. Rebuilt the native adapter test target and passed all 85 NFsim AST
  adapter CTest cases.
- [x] Repeated 200-run Atomizer flat and Atomized comparisons for
  `BIOMD0000001038`. Both modes had 200 valid runs per engine; all 66 sampled
  comparisons pass the pooled-error criterion (worst z 0.0). Report
  `/private/tmp/bng3-atomizer-nfsim-1038-post-endpoint-fix-200runs.json`,
  SHA-256 `2587d27ff7430e50c57742757facffdfc29966f459567573fa37db7871afbd2d`.
- [x] Repeated 200-run Atomizer flat and Atomized comparisons for
  `BIOMD0000000485`. Both modes had 200 valid runs per engine; all 44 sampled
  comparisons pass the pooled-error criterion (worst z 0.0). Report
  `/private/tmp/bng3-atomizer-nfsim-0485-post-endpoint-fix-200runs.json`,
  SHA-256 `d2e6f444a05980b5413b45b42bc92b6f6d632a35c5b51068cbd9f24fa3e0af2f`.
- [x] Added `BIOMD0000000414` to the same 200-run flat and Atomized matrix.
  Both modes had 200 valid runs per engine; all 22 sampled comparisons pass
  (worst z 0.0). Report `/private/tmp/bng3-atomizer-nfsim-0414-200runs.json`,
  SHA-256 `24f5e3dd133e28a76ccf22c9d5ff0d3861f416183ee14e032fb2303ddc6c8af5`.
- [x] Added `BIOMD0000000425`: 200 valid runs per engine in both modes, with
  all 22 sampled comparisons passing (worst z 0.0). Report
  `/private/tmp/bng3-atomizer-nfsim-0425-200runs.json`, SHA-256
  `ddf0f49dd104df5fac89e71573c54063e89515ff13000855956e17a54c81422e`.
- [x] Added `BIOMD0000000850`: 200 valid runs per engine in both modes, with
  all 66 sampled comparisons passing (worst z 0.0). Report
  `/private/tmp/bng3-atomizer-nfsim-0850-200runs.json`, SHA-256
  `ee739d211722cb8b6a3cc3c67d0f9af6c39a3a82216a54af8ac47bc3ecc5478f`.
- [x] Added `BIOMD0000000906`: 200 valid runs per engine in both modes, with
  all 66 sampled comparisons passing (worst z 0.0). Report
  `/private/tmp/bng3-atomizer-nfsim-0906-200runs.json`, SHA-256
  `43e110a36e07c4c2f27ec566879900ff199a587f3ac58255fa60cbd8852d1f7c`.
- [x] Rechecked molecular Atomizer model `BIOMD0000000584` in both modes.
  BNG3 direct produced 200 valid runs per mode; the independent NFsim rejected
  all runs while parsing the BNG2 XML because nested function `LAMDAR()` was
  undefined inside a generated rate law. No ensemble comparison was made.
  This repeats the existing legacy-function compatibility gap with a hashed
  native-run report: `/private/tmp/bng3-atomizer-nfsim-0584-post-endpoint-fix-200runs.json`,
  SHA-256 `bd40306f9560d496b98f57a3e9e38bfaa676579ccf7f25a6031bd5118ec950ec`.
- [x] Rechecked molecular Atomizer model `BIOMD0000000202` in both modes. No
  runs were valid: BNG3 direct rejected fractional seed amounts, while
  standalone NFsim rejected composite functions that reference observables.
  No comparison was made. Report
  `/private/tmp/bng3-atomizer-nfsim-0202-post-endpoint-fix-200runs.json`,
  SHA-256 `2c64b24e845e62efc6837bc4eae1fc47fcf72539528bc2ea1c6eea6453eb9de9`.
- [x] Updated the benchmark reporter to group repeated seed failures by
  engine/signature while retaining each affected seed in JSON. A two-seed
  `0584` smoke confirms correct grouping and concise console output.
- [ ] Expand the valid-model ensemble matrix across the supported curated
  corpus. These bounded results do not close broad NFsim parity or qualify a
  release.

## Atomizer compartment fixed-seed syntax — 2026-09-25

- [x] Corrected modern Atomizer output for fixed seeds in compartments to the
  BNG2-compatible form `@cell:$Molecule()`. The prior `$@cell:Molecule()` form
  was rejected by BNG2. Kept the parser tolerant of both spellings by
  normalizing the compartment-prefix form before parsing.
- [x] Added regression coverage for both fixed-seed spellings and updated the
  Atomizer writer mapping/output test. The C++ backend suite passes (70
  passed), and the modern Atomizer suite passes (85 passed) with the locally
  built CPython 3.14 extension loaded.
- [x] Rechecked curated BioModel `BIOMD0000000033` through both flat and
  Atomized BNG3 conversion, network generation, SBML write/re-import, and
  libRoadRunner comparison. Each mode generated 32 species and 26 reactions;
  all 64 observables per mode passed the numerical comparison. The selected record
  passed, while the validator's full-corpus gate correctly remains incomplete
  because this invocation selected one of 1,096 records. Report
  `/private/tmp/bng3-curated-0033-final-seed-prefix.json`, SHA-256
  `678f73ceecfc855837b3ee06344d4230454f7b0a9783b064f817e1d57c99c9d3`.
- [x] Manually rewrote the emitted fixed-seed marker in the captured BNGL and
  confirmed Perl BNG2 2.9.3 parsed it and generated a 32-species/26-reaction
  network and XML. This isolates and confirms the BNG2 syntax compatibility;
  it is not a 200-run NFsim comparison.
- [x] Re-ran the complete curated BioModels and SBML Test Suite gates after
  this compartment seed parser/writer change; see the exact full-run reports
  below.
- [ ] Expand matched BNG2, PyBioNetGen, standalone NFsim, and libRoadRunner
  benchmarks across the supported intersection. Broad corpus parity,
  cross-platform packaging, and release qualification remain open.

## Full SBML gates and expanded Atomizer comparison — 2026-09-25

- [x] Re-ran the complete curated BioModels inventory after the compartment
  fixed-seed syntax change: all 1,096 inventory entries accounted for, 652
  SBML records passed, 298 SBML records unsupported, 311 total unsupported
  entries, 133 timeouts, and no hard failures. The supported-surface gate is
  still open. Report `/private/tmp/bng3-curated-fixed-seed-full.json`,
  SHA-256 `fb5023510d46c87e4d25c32a1ea01aae9c59f914c0148355bc96245f8724eda4`.
- [x] Re-ran the full SBML Test Suite at pinned revision
  `cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054 unsupported,
  zero failures, and zero timeouts. Semantic cases: 869 passed and 954
  unsupported; stochastic cases: all 100 unsupported. The pass path includes
  Atomizer, network generation, SBML write/re-import, native-reader checks,
  and all-observable BNG3 CVODE/libRoadRunner CVODE comparisons. Reference
  result conformance remains unrun. Report
  `/private/tmp/bng3-sbml-suite-fixed-seed-full.json`, SHA-256
  `2a60212f9a69fac936d28cc22c3afca76ea82bfbb9836f09b7875a5a0eb6f379`.
- [x] Expanded the three-repeat BNG3/BNG2/PyBioNetGen Atomizer benchmark to
  ten curated models, both flat and Atomized modes. BNG3 modern output had
  60/60 successful structural network comparisons against BNG2. Added a
  narrowly scoped rate normalizer for BNG3's `(A/cell)()` serialization of the
  BNG2 `A/cell()` compartment-scaled observable form; a regression confirms a
  changed constant remains a mismatch. Rate comparison now passes 48/60
  modern cases. Remaining failures are concentrated in `0202` (including a
  small constant-rate difference) and nested rate wrappers in `0584`.
  PyBioNetGen generated output in 54/60 cases; only 21/60 produced
  structurally matching BNG2/BNG3 networks, and 3/60 passed the strict rate
  comparison. Legacy Atomized failures remain reported, not waived.
- [x] Ran `tests/validation/test_compare_net.py`: 14 passed. Black, Ruff, and
  `git diff --check` pass for the comparator and benchmark changes.
- [x] The benchmark now records the exact `bng_cpp` executable SHA-256 and
  parser source hash; the earlier trial exposed that the CLI can be stale
  relative to the Python extension. The exact-binary report is
  `/private/tmp/bng3-atomizer-cross-engine-curated-10-rate-normalized.json`,
  SHA-256 `94c7333c4eb17b54368de09f983fa9874d471d2675b136e6764e5b06d98d5a91`;
  `bng_cpp` SHA-256 is `115fbfbbb80773e5f716894eedcadba2ccdbfb8ec3d749394deb8f6eef1312d8`.
- [ ] Expand cross-engine network/rate/trajectory checks across the supported
  curated set and SBML Test Suite intersection; resolve the remaining 12
  modern rate-expression cases only with semantic evidence. The 10-model
  sample and full BNG3/libRoadRunner gates do not close legacy Atomizer,
  NFsim, reference conformance, or release qualification.

## SBML Test Suite cross-engine slice — 2026-09-25

- [x] Ran the three-repeat cross-engine harness on eight SBML Test Suite
  semantic cases already passed by the full BNG3/libRoadRunner round-trip
  gate: `00001`, `01232`, `00829`, `00142`, `00015`, `00270`, `00308`, and
  `01564` (2–52 source species, 1–52 source reactions). Both flat and
  Atomized outputs were compared.
- [x] Modern BNG3 output had 47/48 structural BNG2/BNG3 network comparisons
  and 42/48 strict rate comparisons. PyBioNetGen output succeeded in all 48
  conversions; 36/48 had structural parity and 30/48 passed rate comparison.
  Legacy `fRate*`, unsupported math symbol, and Atomized syntax failures on
  `00270`, `00308`, and `01564` remain explicit gaps. The modern `01564`
  Atomized structure mismatch remains open.
- [x] Report `/private/tmp/bng3-atomizer-cross-engine-sbml-suite-8-rate-normalized.json`,
  SHA-256 `19048c0e65205de967529b0a36acb7e53151425c444675591599d29f802287bd`.
- [ ] Extend this from the selected eight cases to the supported SBML Test
  Suite intersection, and add matched NFsim trajectories where stochastic
  semantics and legacy network inputs are valid.

## Species deduplication repair — 2026-09-25

- [x] Traced the modern Atomized `01564` extra network row to a missed
  compartment-aware exact-key lookup after canonical labeling reordered the
  generated product graph. `SpeciesList::addChecked` now checks the normalized
  key after canonicalization, and graph-isomorphism matches verify molecule
  compartments node by node.
- [x] Reproduced nondeterministic Atomized output across separate Python
  hash seeds. `build_species_composition_table` converted dependency sets to
  ordered complexes; dependencies are now ordered by SBML species order.
  Four subprocess runs at hash seeds 0, 0, 1, and 7 emitted byte-identical
  BNGL; the targeted core and Rulifier tests pass (37 total).
- [x] Rebuilt `bng_cpp` and the Python extension, passed the focused C++
  `SpeciesList` CTest, and reran modern Atomizer `01564` three times in flat
  and Atomized modes. All six runs generated 52 species and 52 reactions and
  matched BNG2 species, reactions, and observable groups. The Atomized output
  hash was identical across repeats. Strict rates matched in 0/6 because
  `NetWriter`'s scientific formatter retains 8 significant digits while BNG2
  emits these rates to 12. Align output precision and rerun this slice before
  treating rate parity as complete. The PyBioNetGen legacy Atomizer did not
  parse this model, so it has no network comparison.
- [x] Latest focused report:
  `/private/tmp/bng3-atomizer-cross-engine-01564-final-source.json`,
  SHA-256 `9647795e68abd8001039d2fce4460581c3540783d29dbc352ac4e2631d89204f`;
  rebuilt `bng_cpp` SHA-256 `1a50ed38cfc63312888203b566dafc6195f3a214f9171f3b91f8ef7758531859`.
- [x] Refreshed the complete SBML Test Suite round-trip after both source
  changes: revision `cf38585fac5de8e0e90112febb62851ee2181816`, 869 passed,
  1,054 unsupported, zero failed, and zero timed out. This remains an import
  and round-trip result; reference-result conformance is not run. Report
  `/private/tmp/bng3-sbml-suite-species-dedup-stable-fix.json`, SHA-256
  `697f6ff362829b5d889e69de1a68084a6f7d7472e11787d247a08b4f462d5d6c`.
- [x] Ran a 20-seed NFsim comparison for `01564` in both modes. Both direct
  BNG3 and standalone NFsim rejected every run because generated reaction
  `J47` has negative propensity `1*atanh(-0.7)`; no ensemble comparison is
  valid. Report `/private/tmp/bng3-atomizer-nfsim-01564-stable-fix.json`,
  SHA-256 `ad73f013a305c3862dd65f7407c75735c7b04e3e513b84e2dc59afbd9e0aa003`.
- [x] Added a focused C++ `SpeciesList` regression using isomorphic reordered
  connected graphs. It confirms the original serialization keys differ,
  canonicalized keys match, and insertion reuses the existing species. Both
  compartment-aware and canonical-key CTests pass.
- [x] Refreshed the full curated BioModels gate in both modes with per-model
  isolation and a 90-second timeout: 654 passed SBML records, 298 unsupported
  SBML records, 131 timed out, and zero hard failures across 1,096 inventory
  records (1,083 SBML records). Report
  `/private/tmp/bng3-curated-species-dedup-stable-fix.json`, SHA-256
  `be79a50587ecbf13b6ae2812f8d624e334606a0d54231dd642bb1a2c01a6d5ef`.
- [ ] Resolve or explicitly govern the 298 unsupported SBML records and 131
  timeouts; this inventory refresh is not a full supported-surface pass and
  does not qualify a release.

## Numeric expression rendering and refreshed gates — 2026-09-25

- [x] Cross-engine 01564 benchmarking isolated numeric truncation to
  `Expression::toString()`, which used default stream precision. Added a
  regression that failed with `3.14159`; numeric AST rendering now uses
  `max_digits10` so serialized values round-trip as doubles.
- [x] The focused numeric regression and all 17 CTest cases tagged
  `Expression` pass.
- [x] Rebuilt `bng_cpp` and the Python extension. The three-repeat modern
  BNG3/BNG2 comparison passes structure and strict rates in all six cases
  (flat and Atomized); modern Atomizer output hashes are stable across repeats.
  Legacy PyBioNetGen Atomizer output is repeatable but its 01564 network
  generation still errors. Report
  `/private/tmp/bng3-atomizer-cross-engine-01564-precision-fix.json`, SHA-256
  `ff25298b20a9778cd90cd1bc44b3ca5c8cf92f1aea05161941e33140d8fd5496`;
  `bng_cpp` SHA-256
  `54095750f38c327bd4e99f05a60a4cbc83aaad6a08cc89184dd29d7533b6c95a`.
- [x] Refreshed the complete SBML Test Suite at revision
  `cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054 unsupported,
  zero failed, and zero timed out. The 869 supported cases pass the XML,
  Atomizer, network, SBML write/reimport, native-reader, and BNG3 CVODE versus
  libRoadRunner CVODE all-observable gate. The 954 unsupported semantic cases
  and all 100 stochastic cases remain outside the supported surface; SBML
  reference-result conformance remains unrun. Overall core status is failed
  due to the unsupported inventory. Report
  `/private/tmp/bng3-sbml-suite-expression-precision-fix.json`, SHA-256
  `0cf26c1efa4760db2327dad4bf64ebd271230550c7ef76041ad3aafb3232f0f8`.
- [x] Repeated the same eight-case, three-repeat cross-engine benchmark after
  the precision fix, in flat and Atomized modes. Modern Atomizer BNG3 matched
  BNG2 structure and strict numeric rates in all 48 comparisons, with stable
  output per model and mode. Legacy PyBioNetGen had 36/48 structural and 30/48
  strict-rate matches; its remaining failures include zero-rate rows on
  `00270`/`00308` and network-generation failures on `01564`. Report
  `/private/tmp/bng3-atomizer-cross-engine-sbml-suite-8-precision-fix.json`,
  SHA-256 `e3316389e6f88a717e466e20d3253b1e782b579f2775bc0e536a37593de3f528`.
- [x] Refreshed the ten curated-model, three-repeat cross-engine sample after
  numeric rendering. Modern BNG3 had 60/60 structural BNG2 matches and 48/60
  strict-rate matches across flat and Atomized modes; the 12 rate mismatches
  remain concentrated in `BIOMD0000000202` and `BIOMD0000000584`. PyBioNetGen
  emitted 54/60 BNGL outputs; 21/60 generated structurally matching networks
  and 3/60 passed the
  rate comparison. Report
  `/private/tmp/bng3-atomizer-cross-engine-curated-10-precision-fix.json`,
  SHA-256 `ea04f672f62baaea6f31df3807427e09209053c330f8e37f477ad0f958c787cf`.
- [x] Refreshed 200-seed-per-engine Atomizer NFsim ensembles on six curated
  models in flat and Atomized modes: all 12 model/mode ensembles passed with
  200 valid runs per side and zero stochastic mean violations. Aggregate
  `/private/tmp/bng3-atomizer-nfsim-curated-6-precision-fix.json`, SHA-256
  `335354192736464793d826b04ff9ddda515684b907e6611242aef2b84cbe686d`, records
  the six source hashes, each report checksum, and the standalone NFsim binary
  checksum. `0202` has non-integer seed amounts and legacy composite-function
  failures; `0584` has standalone `LAMDAR` resolution failure, so neither has
  a valid matched ensemble. A current-source `0033` 200-run attempt produced
  only three native trajectories in over six minutes before interruption; it
  has no ensemble result and remains outside this passing sample.
- [x] Refreshed the full curated BioModels gate after numeric rendering using
  both modes, isolated model processes, a 90-second per-model timeout, and six
  workers. Across 1,096 inventory records (1,083 SBML), 654 SBML records
  passed, 298 SBML records were unsupported, 131 timed out, and zero hard
  failures occurred. Report
  `/private/tmp/bng3-curated-expression-precision-fix.json`, SHA-256
  `1f21b340aee754e01f75c4784e4387e1560cf6c4b5b86f6969e3a9edee15abf1`.
- [ ] Resolve or explicitly govern the 298 unsupported SBML records and 131
  timeouts; the broad curated supported-surface gate and release qualification
  remain open.

## Dynamic NET rate serialization — 2026-09-25

- [x] Reproduced `BIOMD0000000202` NET rates for `S2a` and `S4` as zero even
  though the BNGL rate calls a model function. `NetWriter` only classified
  direct observable references as dynamic. It now walks rate ASTs for nested
  model-function calls, so those rates are emitted in the functions block.
- [x] Added a regression that failed before the fix; it checks a composite
  rate `k * f()` where `f()` depends on an observable. All 20 Expression and
  NetWriter CTests pass.
- [x] Repeated the ten-model, three-repeat curated cross-engine benchmark.
  Modern BNG3 retained 60/60 structural matches and 48/60 rate matches; the
  former zero-valued `0202` rates are now dynamic expressions, but strict
  expression-form comparisons still fail for 0202 and 0584. PyBioNetGen remains
  at 54/60 generated outputs, 21/60 structural matches, and 3/60 rate matches.
  Report `/private/tmp/bng3-atomizer-cross-engine-curated-10-dynamic-rate-fix.json`,
  SHA-256 `3d71dbde754db2396a4ef98e7d2dc64a6768268c00b49ef4a0e9ba0e5174bbfa`;
  rebuilt `bng_cpp` SHA-256
  `b43f9733fe979e23ff7c71a340d7f3f0a61d2537a02965c2a475c768edc741a1`.
- [x] Reran the full SBML Test Suite at pinned revision
  `cf38585fac5de8e0e90112febb62851ee2181816`: 869 passed, 1,054 unsupported,
  zero failed, zero timed out. The supported-surface gate passed; overall core
  status remains failed by the unsupported inventory. Reference-result
  conformance remains unrun. Report
  `/private/tmp/bng3-sbml-suite-dynamic-rate-fix.json`, SHA-256
  `dba04385da6ff768f4f5c777544c72dfbf1fc345301a92f3707171c0068dbdb3`.
- [x] Completed the full curated BioModels rerun against this writer change
  using the offline published-model manifest, both flat and Atomized modes,
  isolated model processes, a 90-second per-model timeout, and six workers.
  The 1,096-record inventory contains 1,083 SBML records: 654 passed the
  round-trip and libRoadRunner observable comparison, 298 were unsupported,
  131 timed out, and zero SBML records failed hard. The other 13 records are
  explicit non-SBML/unsupported-format inventory entries. The counts match the
  prior exact-source run; the NET fix repaired the affected 0202 serialization
  but did not expand the full-corpus supported surface. Report
  `/private/tmp/bng3-curated-dynamic-rate-fix.json`, SHA-256
  `f470fdd1993ced1fc52fc33fb096ae27d45a08d0bacf5235bff9e6c40a42b14e`.
- [ ] Resolve or explicitly govern the 298 unsupported SBML records and 131
  timeouts; the broad curated supported-surface gate and release qualification
  remain open.

## Package repository metadata — 2026-09-25

- [x] Corrected the PyPI project repository link from the legacy BioNetGen
  repository to the current BNG3 repository. This metadata edit has not yet
  been validated by a clean sdist or wheel build; the broader package audit
  and release gates remain open.

## SBML composition, empty-state models, and MathML — 2026-09-25

- [x] Modern Atomizer now flattens self-contained SBML `comp` hierarchies
  through libSBML before import. Flattening refuses partial conversion when a
  required package has no flattener. At the time of this report, external
  model definitions were unsupported; source-relative local-file resolution
  was implemented in the later section below.
- [x] BNG3 ODE simulation now handles zero-species networks without passing an
  empty vector to CVODE. It returns requested time points and evaluates
  time/parameter-only functions. SBML suite 00174, 00920, and 00921 pass,
  including comparison of initial-assignment and parameter-rule outputs with
  libRoadRunner.
- [x] Atomizer lowers MathML `implies` to BNGL `if` and `arccoth(x)` to
  `atanh(1/x)` on SBML's real-valued domain. Former compiler failures on
  00957–00959, 01274, 01279, 01486, 01488, and 01497 now pass targeted suite
  round-trip/numerical comparisons.
- [x] Full pinned SBML Test Suite now reports 1,042 passed, 881 unsupported,
  zero failed, and zero timeouts (revision
  `cf38585fac5de8e0e90112febb62851ee2181816`). Supported-surface gate passes;
  overall core gate remains open because 881 cases are unsupported. Report
  `/private/tmp/bng3-sbml-suite-final-slices.json`, SHA-256
  `52e03b789a7019497493af2c26414d47dd3088e36506757e7a9ec1d34993bdb2`.
- [x] Refresh the full curated BioModels comparison after zero-state support
  and expanded parameter/initial-assignment comparisons. In the 1,083 SBML
  records, 657 passed, 293 were unsupported, 2 failed numerical comparison,
  and 131 timed out. The 13 non-SBML inventory entries remain unsupported
  format. Raw report `/private/tmp/bng3-curated-comp-empty-mathml.json`, SHA-256
  `a57150abb837bb8018943cb14837bde95a4f9ecb27525a672b8bc4afbce94eca`;
  normalized strict-JSON copy for spreadsheet import
  `/private/tmp/bng3-curated-comp-empty-mathml-strict.json`, SHA-256
  `4a2fafc68c1e82ffcb5b9ea0042f4da494a25006671acef0d196149c59cbffc5` (IEEE
  non-finite metric values represented as JSON `null`).
  Failed records are BIOMD0000000731 (`log_Treg = ln(func_TRegs)`, with the
  source `func_TRegs` initially zero) and BIOMD0000000973 (`s =
  (ModelValue_6 - P) / N`, with `N` initially zero); both expose non-finite
  derived values at the initial time. They remain failures, not parity passes.
- [x] Refresh the full unsupported-model triage workbook using this BioModels
  report and the final SBML Test Suite report. It contains all 1,096 curated
  BioModels inventory entries and 1,923 SBML Test Suite records, with per-mode
  round-trip evidence, precise diagnostics, source links, hashes, and cause
  summaries: `bng3_unsupported_model_triage.xlsx`.
- [ ] Resolve remaining event scheduling, fractional/variable stoichiometry,
  algebraic-rule, unsupported MathML, and other non-FBC semantics; rerun full
  BNG2/PyBioNetGen/NFsim and libRoadRunner gates after each material slice.

The remaining supported-surface gap is semantic: the reaction-oriented BNGL
runtime does not yet represent state-triggered event scheduling, DAE algebraic
constraints, or fractional/dynamic reaction stoichiometry. In the latest suite,
cause tags overlap: events=508, stoichiometry=180 (132 dynamic/MathML-defined),
algebraic rules=84, and FBC=34. Flux balance remains intentionally out of scope;
the other groups remain implementation targets.

## SBML external comp references and additional rateOf lowering — 2026-09-25

- [x] Source-backed Atomizer imports now flatten local external `comp` model
  definitions. Resolution is restricted to existing local files below the
  source model directory; network and path-escape references remain fail-closed.
  Focused tests cover source-relative flattening, path escape rejection, and
  explicit unsupported behavior when source provenance is absent.
- [x] `rateOf` lowering now resolves mutable parameters/compartments with no
  rule or event driver to zero, and derives concentration `rateOf` expressions
  for simple reactions in rate-ruled compartments, including volume dilution.
  Suite cases `semantic/01249` and `semantic/01822` now pass.
- [x] Atomizer tests: `257 passed, 1 skipped`. Full pinned SBML Test Suite:
  `1,054` passed, `869` explicitly unsupported, `0` failed, `0` timed out;
  supported-surface gate passes, overall core gate remains open. Report
  `/private/tmp/bng3-sbml-suite-rateof.json`, SHA-256
  `6abe9c80631d0809d647ea0461336787347ecb6e277a9cae1316fef37960e871`.
- [ ] `semantic/01461` remains unsupported because its rate rule has no MathML
  expression; `semantic/01543` remains unsupported because the reaction uses
  dynamic stoichiometry, which cannot be represented as a fixed BNGL pattern.
  Broader event, algebraic-rule, and stoichiometry support and independent
  reference-result conformance remain open.

## Explicit linear algebraic-parameter rules — 2026-09-25

- [x] A single algebraic constraint now lowers to an assignment rule when one
  otherwise-uncontrolled mutable parameter is its unique unknown and the
  expression is linear with finite numeric coefficient. Nonlinear equations,
  coupled unknowns, species targets, and multiply-constrained parameters stay
  explicit and unsupported.
- [x] Added regression coverage for successful `k - 0.9 = 0` lowering and
  fail-closed nonlinear/coupled cases. Nine official cases (`00533`, `00534`,
  `00536`, `00537`, `00538`, `00569`, `00570`, `01502`, `01503`) pass, including
  suite round-trip checks.
- [x] Full Atomizer Python tests pass `260`, with `1` skipped; Ruff and
  `git diff --check` pass. Full pinned SBML Test Suite now reports `1,080`
  passed, `843` unsupported, zero failed, zero timed out. The supported-surface
  gate passes; overall core and reference-result conformance remain open.
- [x] Stable-source report `/private/tmp/bng3-sbml-suite-algebraic-verified.json`,
  SHA-256 `0ae76dd61447a4bd694ad68a3cb6fa9ebafc8c5297c91d828a1a93172af39dc6`.
- [ ] Algebraic-rule cause tags fell from `125` to `84`; the remaining
  unsupported cases include constraints without a single safe parameter
  assignment (often species variables, nonlinear/coupled equations, or cases
  that also have other blockers). Continue case-level triage; this subset does
  not add a general DAE solver.

## Fixed-time event calculations — 2026-09-25

- [x] Fixed-time event folding substitutes trigger or execution time according
  to `useValuesFromTriggerTime`; delays evaluate at trigger time, priorities at
  execution time. Safe constant real math calls (including `cosh`) can be
  folded after time substitution. Positive constant-scaled triggers of the
  form `time / scale > threshold` are solved for the trigger time; nonpositive
  or mutable scales remain unsupported.
- [x] Six official cases now pass: `01177`, `01528`, `01529`, `01597`, `01598`,
  and `01604`. `01142` now lowers its event schedule but remains unsupported
  for separate SBML `delay` function semantics.
- [x] Atomizer Python suite passes `264`, `1` skipped; Ruff and diff checks
  pass. Full pinned SBML Test Suite: `1,086` passed, `837` unsupported, no hard
  failures or timeouts. Supported-surface gate passes; core remains open.
  Report `/private/tmp/bng3-sbml-suite-event-time-final.json`, SHA-256
  `ef6dda150f3b8cddf6682b6913eea864bd7b661c85568399a56bd24a5e0ae20c`.
- [ ] State-dependent triggers still require runtime event scheduling. General
  SBML `delay` functions and their history semantics also remain unsupported.

## Exact static-operand delay lowering — 2026-09-25

- [x] `delay(value, duration)` now reduces to `value` only when the value
  expression references no changing model state. Dynamic rules, event targets,
  time, dynamic species, and algebraic unknowns remain protected and retain the
  delay call.
- [x] Added a parser regression for an unruled mutable parameter delayed by a
  finite duration. Suite cases `00941`, `00943`, and `01174` now pass.
- [x] Atomizer Python tests pass `265`, `1` skipped; Ruff and diff checks pass.
  Full pinned suite now reports `1,089` passed, `834` unsupported, no failed or
  timed-out cases. Supported-surface gate passes; core remains open. Report
  `/private/tmp/bng3-sbml-suite-static-delay.json`, SHA-256
  `5112cf447c9f156b6e1ecece01cd855ad6d98768f26ce306660aca20dbd60c10`.
- [ ] General state-history delays remain unsupported. Re-run curated BioModels
  round-trip and libRoadRunner comparisons to measure whether the static-delay
  slice expands that corpus.

## Algebraic compartments and static-state events — 2026-09-25

- [x] The safe single-unknown linear algebraic lowering now also accepts an
  otherwise-uncontrolled mutable compartment. Nonlinear, coupled, species-
  constrained, and multiple-constraint cases remain explicit. Official cases
  `00539`, `00540`, `00541`, `00542`, `00544`, `00545`, `00547`, `00548`,
  `01785`, `01786`, and `01791` now pass.
- [x] Event triggers depending only on species that cannot change during the
  simulation are evaluated at time zero with SBML `trigger.initialValue`
  semantics. Constant-true events schedule at zero only for a false initial
  trigger; constant-false events are safely discarded. Dynamic/state-dependent
  events remain unsupported. Official cases `00995`, `01373`-`01376`, and
  `01527` now pass.
- [x] Atomizer tests pass `267`, with `1` skipped. Ruff and `git diff --check`
  pass. The stable-source pinned suite reports `1,106` passed, `817`
  unsupported, `0` failed, `0` timed out; supported-surface passes and core
  remains open. Event causes fell to `502`, algebraic-rule causes to `73`.
  Report `/private/tmp/bng3-sbml-suite-static-events.json`, SHA-256
  `8582bd4a35c6a7e42812a35ea22febcc549bc5b4f48f6c32def3d681fc171ae6`.
- [ ] Re-run the complete curated BioModels flat/Atomized and libRoadRunner
  comparison after these changes. General dynamic event scheduling, DAE
  constraints, and fractional or time-varying reaction stoichiometry remain
  the largest non-FBC feature gaps.

## Static species-reference symbol scope — 2026-09-25

- [x] SBML Level 3 `SpeciesReference` IDs now resolve as model-level
  stoichiometry symbols. A literal reference value or a value determined only
  by static assignment/initial-assignment expressions is promoted to a
  dimensionless parameter for global formulas and folded into fixed BNGL
  reaction patterns. Dynamic rate/event-controlled references remain explicit.
  Authority: [SBML Level 3 Version 2 Core, SpeciesReference](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf).
- [x] Official cases `00974`, `01380`-`01388`, `01395`, `01566`, `01651`-
  `01656`, and `01764`-`01768`/`01774` now pass. All applicable stochastic
  cases `stochastic/00001`-`00039` now pass; `00033` is not in the canonical
  inventory. The full suite moved from 1,106 to 1,169 passed; unsupported
  stoichiometry causes fell from 180 to 132 and local-scope causes from 26 to
  1. No failed or timed-out cases.
- [x] Atomizer tests pass `270`, with `1` skipped; Ruff and
  `git diff --check` pass. Stable-source full suite report
  `/private/tmp/bng3-sbml-suite-static-stoich-ids.json`, SHA-256
  `7c09ca58396fb5f99446bfac081d62e86bd379937d6db605d1ff4b1f2eb4e845`;
  supported-surface passes, core remains open.
- [x] Every SBML `SpeciesReference` ID is model-global even when its
  stoichiometry is dynamic. The ID is now distinguished from lowering its
  dynamic value. `semantic/01626` no longer has a local-scope cause; its
  remaining blockers are variable stoichiometry and six state-triggered events.
- [ ] Fractional-stoichiometry triage found `55` semantic records with a
  `constant_noninteger` blocker across `60` reactions. A conservative numeric
  scan identifies `47` records whose affected reactions have fixed,
  nonnegative coefficients that can be represented by a common rational
  quantum with scaled coefficients no larger than `100`; this is only a
  candidate set, not a proven ODE lowering. Determine an exact, mode-aware
  representation and validate it against libRoadRunner before enabling it;
  do not silently change SSA molecule jumps. Several records also carry FBC
  or other blockers, so the maximum suite gain is smaller than 47.

## SBML function-local scope and curated cohort — 2026-09-25

- [x] Stop treating SBML `FunctionDefinition` lambda bodies as model-global
  expressions when detecting reaction-local symbol leaks. Lambda arguments
  have function scope; scanning them falsely rejected models that pass a
  local kinetic parameter as a function argument. Global rules, initial
  assignments, and event formulas remain in the scope check.
- [x] Regression covers a local kinetic parameter named `k` passed into an
  SBML function whose lambda formal is also `k`. Atomizer target suite:
  `91 passed, 24 skipped`; Ruff and `git diff --check` pass.
- [x] Fixed-time event triggers `time == t` and MathML `eq(time, t)` now lower
  to scheduled actions when assignments are compile-time constants. Direct
  event tests pass. Curated `BIOMD0000001043` now passes, recovering one model
  previously blocked on its `eq(time, 20)` event trigger. The pinned suite had
  no previously unsupported case with this exact trigger form.
- [x] Fixed-time event thresholds and constant assignments now inline SBML
  user-defined functions before safe numeric folding. End-to-end regression
  uses zero-argument and argument-taking functions. Current curated and pinned
  suite event-blocker inventories contain no fixed-time assignments calling
  user-defined functions, so no additional benchmark gain is claimed.
- [x] Final Atomizer suite before compartment-event action correction:
  `248 passed, 26 skipped`; Ruff and `git diff --check` pass.
- [x] Of the 90 curated BioModels records previously tagged `local_scope`,
  focused two-mode revalidation passed 58, left 16 unsupported for independent
  event/species-assignment features, timed out 15, and failed 1. Representative
  `BIOMD0000000174` passes Atomizer, BNG3/SBML roundtrip, and libRoadRunner.
  Cohort report `/private/tmp/bng3-curated-scope-targeted.json`, SHA-256
  `6b7ac2038ed92218ae5d86c2c28a94dc600f8f9fb6b35c453833f1b5c589ef91`.
- [x] Full 1,096-record BioModels rerun: 715/1,083 SBML records passed, 218
  unsupported, 3 failed, and 147 timed out; 13 non-SBML records are explicit
  unsupported formats. Versus the baseline, 58 additional records passed;
  one equality-trigger event model also passed. Full report
  `/private/tmp/bng3-curated-post-scope-equality-functions.json`, SHA-256
  `420d7e038407bf4340d1ec11f3105d7c7c59e6c0ced3745473f7abaa5ace8495`.
  Cross-engine comparison remains part of each passing model's gate. Full core
  gate remains open.
- [x] Fixed-time SBML compartment assignments now emit BNG3's `setVolume`
  action, rather than changing a same-named parameter. End-to-end generation
  regression and BNG3 CLI execution with an ODE phase before and after resizing
  pass. The curated models `BIOMD0000000338` and `BIOMD0000000339` contain this
  event shape but remain unsupported due to other state-triggered events; no
  whole-model gain is claimed. The pinned suite has no fixed-time events
  assigning compartments.
- [x] Atomizer suite after the compartment-event fix: `250 passed, 26
  skipped`; Ruff and `git diff --check` pass.
- [x] Full pinned SBML Test Suite rerun: `1,169 passed, 754 unsupported`,
  with `0 failed` and `0 timeouts`. The previous `local_scope=1` diagnostic
  is now gone; other cause counts are unchanged. `semantic/01626` remains
  unsupported for the actual dynamic-stoichiometry and dynamic-event features.
  Report `/private/tmp/bng3-sbml-suite-post-all-scope-fixes.json`, SHA-256
  `9150a27e3b954a4945fe611e3f2019a5c065b0c722ae2fca9ef6faab12086f2b`.

## SBML Avogadro constant in fixed-time events — 2026-09-25

- [x] Event folding resolves the SBML built-in Avogadro symbol to its exact
  numeric value for scheduling; emitted model expressions still use BNG3's
  normalized `__Avogadro__` parameter.
- [x] Atomizer suite: `251 passed, 26 skipped`; Ruff and `git diff --check`
  pass. End-to-end regression covers an Avogadro-derived event time.
- [x] Full pinned SBML Test Suite: `1,174 passed, 749 unsupported`, `0 failed`,
  `0 timed out`; five newly passing cases (`semantic/01658`, `01659`, `01662`,
  `01663`, `01664`) and no regressions. Report
  `/private/tmp/bng3-sbml-suite-post-avogadro.json`, SHA-256
  `8640210892d72b05780ce6ed411e0c05d16a9af3216282bcb045e5035128d33b`.
- [ ] Re-run the full curated BioModels benchmark only if the current
  unsupported inventory gains a model using this constant in a fixed-time
  event. The current unsupported event records contain no such reference.
- [ ] Full 58-model cross-engine benchmark against BNG2 and PyBioNetGen was
  interrupted before a report was written because its runtime exceeded the
  practical window. A completed eight-model sample is recorded in the
  continuation section below; complete cohort evidence remains open.

## Fixed-time event windows and recovered-cohort benchmarks — 2026-09-25

- [x] Conjunctions containing only direct monotone comparisons against time
  now schedule at the constant lower bound. For delayed nonpersistent events,
  lowering requires execution strictly before the upper window bound; the
  official `semantic/01526` cancellation case remains unsupported. State
  predicates, equality windows, and nonconstant bounds remain unsupported.
- [x] Atomizer tests: `253 passed, 26 skipped`; Ruff and `git diff --check`
  pass. Pinned suite cases `semantic/01525` and `01660` newly pass; no
  regressions. Full pinned suite: `1,176 passed, 747 unsupported`, zero failed
  or timed out. Report `/private/tmp/bng3-sbml-suite-post-time-window.json`,
  SHA-256 `f5b3e2d23e1d702c8d9fc790ec89fefa4487763a54e2861eadf1caeed091a770`.
- [x] Targeted flat/Atomized plus libRoadRunner checks recover four curated
  models (`BIOMD0000000121`, `0126`, `0943`, `0976`) from 15 selected
  time-window candidates; ten remain blocked by additional event semantics
  and one exceeded the outer timeout. Per-model outputs and the digest-pinned
  summary are under `/private/tmp/bng3-curated-time-window-cohort/` and
  `/private/tmp/bng3-curated-time-window-cohort-summary.json`.
- [x] Cross-engine sample compares modern and legacy PyBioNetGen Atomizers,
  BNG3 and Perl BNG2 networks, with 3 repeats for 8 newly recovered curated
  models in both modes. Modern structural parity: 24/24 flat, 21/24 atomized;
  rates: 21/24 flat, 18/24 atomized. Legacy flat structural parity: 24/24,
  rate parity: 0/24; legacy atomized produced comparable networks in 15/24
  repeats. Report `/private/tmp/bng3-atomizer-cross-engine-scope-sample.json`,
  SHA-256 `76d5f5393e1c05315e39130ebd3b9d4e33e7611ab9f1a3da0b4bd54adda06ebd`.
- [ ] Re-run the full curated BioModels inventory after this event change and
  finish cross-engine comparison for all 58 recovered local-scope models.

## Constant Boolean event simplification — 2026-09-25

- [x] Numeric folding now implements n-ary chained `lt`/`leq`/`gt`/`geq` and
  short-circuits partially unknown `and`/`or` expressions when a constant term
  determines the result. SBML events proven never to fire are informational;
  no action block is emitted.
- [x] `semantic/01211` newly passes because its time predicate is conjoined
  with a constant-false three-argument `leq`. Full pinned suite:
  `1,177 passed, 746 unsupported`, zero failures and timeouts, no regressions;
  event causes=490. Report
  `/private/tmp/bng3-sbml-suite-post-static-window-logic.json`, SHA-256
  `15a01a0e033aceec0b5dcc56f37239bc202b30fa20b3ab4dcecf267beab6e515`.
- [x] Atomizer tests: `255 passed, 26 skipped`; Ruff and `git diff --check`
  pass.
- [ ] Full BioModels inventory and the remaining cross-engine cohort are still
  open; keep state-dependent events and delayed cancellation fail-closed.

## Linear algebraic species constraints — 2026-09-25

- [x] Extend the exact one-unknown linear solver to a mutable species only when
  it is not a reaction participant, event target, or boundary species. The
  result is a normal species assignment rule and uses the existing derived
  function writer. Reaction-connected algebraic unknowns remain unsupported.
- [x] Regression covers `A + B = 10` where `B` is a reaction species and `A`
  is algebraically derived. Atomizer suite: `256 passed, 26 skipped`; Ruff and
  `git diff --check` pass.
- [x] Full pinned suite gains 31 passes with no regressions: `1,208 passed,
  715 unsupported`, zero failed or timed out. Algebraic-rule causes fell from
  73 to 34; constraint-tagged records fell from 106 to 67. Report
  `/private/tmp/bng3-sbml-suite-post-algebraic-species.json`, SHA-256
  `9b0e847576431ca336a2d0d67d6393773133665d74a614c224afc3b28acf0ba7`.
- [x] Curated unsupported inventory has no algebraic-rule cause; no curated
  model gain is expected from this solver slice.
- [ ] Re-audit eligible cases that retain other independent blockers and keep
  the full curated and full 58-model cross-engine checklists open.

## Fixed fractional stoichiometry — 2026-09-25

- [x] Lower fixed finite fractional stoichiometry into per-species signed
  `TotalRate` source/sink rules. Species conversion factors and rate-rule-owned,
  constant, and boundary species semantics are retained. Dynamic stoichiometry,
  fast reactions, FBC, and executable Multi remain fail-closed.
- [x] State semantic boundary in import notes: deterministic SBML derivatives
  are preserved; stochastic trajectories do not preserve shared reaction-event
  coupling. No NFsim parity claim applies to these decomposed reactions.
- [x] Remove fixed fractional stoichiometry from curated validator's structural
  prefilter so writer output and direct simulation comparison determine support.
- [x] Full pinned SBML Test Suite has 19 new passes and no regressions:
  `1,227 passed, 696 unsupported`, zero failed or timed out. Report
  `/private/tmp/bng3-sbml-suite-fixed-fractional.json`, SHA-256
  `505cfece23ab511544e432cdc03ddf62e66dd3450b285411ab1ea60348eb4678`.
  New passes: `semantic/00022`, `00519`–`00521`, `01080`–`01082`, `01498`,
  `01516`, `01542`, `01561`, `01724`–`01726`, `01733`–`01735`, `01746`–`01747`.
- [x] Curated BioModels `BIOMD0000000039`, `0059`, and `0206` pass both flat
  and Atomized routes, including all-observable BNG3 CVODE/libRoadRunner 2.10.0
  comparisons. Their per-model reports are `/private/tmp/BIOMD0000000039-fractional.json`,
  `/private/tmp/BIOMD0000000059-fractional.json`, and
  `/private/tmp/BIOMD0000000206-fractional.json`.
- [x] Three-repeat Atomizer benchmark across those models and both modes:
  modern BNG3 output has BNG3/BNG2 structural network parity in `18/18`
  repeats; strict serialized-rate parity is `0/18`. Legacy PyBioNetGen output
  has structure parity in `6/6` completed comparisons and rate parity `0/6`.
  Textual rate mismatches remain separate from the independent numerical
  BNG3/libRoadRunner trajectory passes above. Report
  `/private/tmp/bng3-atomizer-cross-engine-fractional-3.json`, SHA-256
  `269b05c8b653af57dd06c49ac6003e58480ec38de0c1e52a21724bd0905e3ed5`.
- [x] Compact irreversible fractional lowering to one direction-specific
  species flux rule; retain sign-splitting only for reversible reactions. The
  repeated BNG3/BNG2 cross-engine sample remains structurally `18/18` and strict
  rate-string parity improves to `6/18`; PyBioNetGen flat output is `6/6`
  structural and `0/6` strict-rate matches, while its Atomized route fails
  conversion. Updated report `/private/tmp/bng3-atomizer-cross-engine-fractional-optimized-3.json`,
  SHA-256 `ca786e55e080101eedfa78f7dbba1526509f7b750f8cd87acf49f4f28aa24472`.
- [x] Re-ran full pinned SBML Test Suite after compact lowering: unchanged
  `1,227 passed, 696 unsupported`, zero failures/timeouts. Report
  `/private/tmp/bng3-sbml-suite-fractional-optimized.json`, SHA-256
  `1f598ce650f8603796ab9421baf025302dd39ba1bae5196e8a3ab75ee68d70df`.
- [x] Full curated inventory run before compact lowering: `730/1,083` SBML
  records passed, `192` SBML records unsupported, `4` failed, `157` timed out;
  inventory completeness is `1,096/1,096`. Relative to prior full report,
  passes rose by `78`; SBML-only unsupported count fell by `106`. Nine newly
  passing models had fractional stoichiometry as their only reported blocker.
  Report `/private/tmp/bng3-curated-fixed-fractional-full.json`, SHA-256
  `69860198b51955d80ff6346238f2fbfb8241993d0e5f4803c417b4c3541092ff`.
  Remaining failures include a worker `-11` on `BIOMD0000000081` (targeted
  rerun also timed out at 180 s), a libRoadRunner CVODE failure on `0606`, and
  newly checked non-finite parameter observables on `0731` and `0973`. The
  latter two observables were absent from prior all-observable comparisons.
- [x] Revalidated fractional curated models after compact lowering:
  `BIOMD0000000039`, `0059`, and `0206` pass flat and Atomized round-trips and
  all-observable BNG3/libRoadRunner comparisons. Current reports are
  `/private/tmp/BIOMD0000000039-fractional-optimized.json`,
  `/private/tmp/BIOMD0000000059-fractional-optimized.json`, and
  `/private/tmp/BIOMD0000000206-fractional-optimized.json`.
- [x] Focused Atomizer, parity, event, and curated validator tests:
  `129 passed`; Ruff and `git diff --check` pass.
- [ ] Full Python suite has one unrelated BNGIR float-serialization failure:
  `tests/python/test_bngir.py::test_bngir_is_deterministic_and_source_free`
  expects `0.1`, receives `0.10000000000000001`; remaining tests pass.
- [x] Re-run complete curated inventory after irreversible-rule compaction;
  benchmark fractional deterministic trajectories against BNG2/PyBioNetGen and
  continue broader Atomizer feature work.

## Fixed-time event values from uncontrolled mutable symbols — 2026-09-26

- [x] Fold a parameter or compartment marked `constant="false"` when no rule,
  initial assignment, or event targets it. SBML permits these symbols to change,
  but this model defines no mechanism that changes them during a run; their
  initial values therefore give exact scheduled-event times and values.
- [x] Preserve fail-closed handling when a rule, initial assignment, or event
  can change the symbol. Regression checks both the schedulable and controlled
  parameter cases in one generated BNGL model.
- [x] Atomizer, event, and SBML parity tests pass (`128 passed`); Ruff and
  `git diff --check` pass.
- [ ] Validate curated BioModels and the full pinned SBML Test Suite with this
  change. The currently running BioModels inventory process started before this
  edit and does not include it.

## Curated BioModels refresh after fractional-rule compaction — 2026-09-26

- [x] Re-ran all `1,096/1,096` curated inventory records after compaction:
  `731/1,083` SBML records passed, `191` were unsupported, `3` failed, and
  `158` timed out. Compared with the pre-compaction report this is one additional
  pass (`BIOMD0000000040`), one fewer unsupported SBML record, one fewer failed
  record (`BIOMD0000000081` now timed out), and one additional timeout. The
  total pass difference is not attributed to fractional lowering alone.
  Report `/private/tmp/bng3-curated-fixed-fractional-optimized-full.json`,
  SHA-256 `e7fbd2635d03a56208cd31a4e62285c1d3c2ca4aa37df44c411a15818ab0e0fd`.
- [x] The three remaining failures are `BIOMD0000000606` (libRoadRunner CVODE
  failure), `BIOMD0000000731` (non-finite `log_Treg` comparison), and
  `BIOMD0000000973` (non-finite `s` comparison). The latter two are all-observable
  checks absent from older reports, not identified Atomizer conversion errors.
- [ ] This inventory process started before the uncontrolled-mutable-symbol
  event change; run targeted checks and refresh the full report before claiming
  any curated gain from that implementation.

## Reaction-participating algebraic species — 2026-09-26

- [x] Emit noncyclic, unique species assignment rules as BNGL functions even
  when the target occurs in a reaction. Remove algebraic targets from reaction
  state patterns while preserving the assignment function in kinetic laws.
  Event targets, duplicate rules, and cyclic assignments remain fail-closed.
- [x] Warn that deterministic ODE semantics are preserved, while stochastic
  event trajectories are not claimed for algebraic participants. Fractional
  lowering skips these assignment-owned variables.
- [x] Focused Atomizer/validator tests pass (`131 passed`); Ruff and
  `git diff --check` pass. Full Python suite: `517 passed, 28 skipped`, with
  one unrelated BNGIR float-serialization failure (`0.1` vs
  `0.10000000000000001`).
- [x] Selected previously blocked models pass both flat and Atomized routes,
  including all-observable BNG3 CVODE/libRoadRunner comparisons: `37` models.
  Per-model reports and result details are indexed in
  `/private/tmp/bng3-assignment-species-targeted-index.json`, SHA-256
  `ed13f24a6e6e6e972038fa8bf06adf2fac1db028c38573ad321d0edb4086c083`.
  A single-ID validator process exits nonzero because the inventory-wide gate
  is incomplete; each indexed model record itself has `status=passed`.
- [x] Pinned SBML Test Suite refreshed after assignment-species and event
  changes: `1,282 passed, 641 unsupported, 0 failed, 0 timeouts` (1,923 total).
  Compared with the prior exact-source report, 55 cases newly pass and none
  regress; all gains are stochastic cases whose events were proven never to
  fire. Report `/private/tmp/bng3-sbml-suite-final-code.json`, SHA-256
  `f4df13b873836a4931edb117aec238938fa1227aec6a0e624697148010470b84`.
  The gate checks BNG3/libRoadRunner all-observable parity; official suite
  reference-trajectory conformance was not run.
- [x] Complete the full curated BioModels inventory with the rate-rule
  reference fix and oversized-stoichiometry lowering: `774/1,083` SBML models
  pass, `134` are explicitly unsupported, `5` fail, and `170` time out; all
  1,096 inventory entries are accounted for. Against the previous assignment
  run, passes rise by 2, unsupported fall by 4, failures fall by 2, and
  timeouts rise by 4. `BIOMD0000000245` now passes after fixing assignment
  functions that read rate-rule state; `BIOMD0000000353` passes both routes and
  BNG3/libRoadRunner comparison with fixed large stoichiometry. `BIOMD0000000463`
  reaches timeout in the full both-mode run despite its targeted flat pass.
  Report `/private/tmp/bng3-curated-atomizer-final-code-full.json`, SHA-256
  `aa1fcaebd8b69beeb4c3274d6e3813f9b3e98d1d787dcc0bdcb71f4771b209ad`.
  Core and supported-surface gates remain open.

## Fixed oversized integer stoichiometry — 2026-09-26

- [x] Lower fixed integer stoichiometry above 100 into per-species `TotalRate`
  rules instead of expanding thousands of repeated BNGL patterns. Dynamic
  oversized stoichiometry and fast/Multi/FBC conflicts remain fail-closed.
  Deterministic ODE derivatives are preserved; shared stochastic event
  trajectories are not claimed.
- [x] Curated surface prefilter now lets oversized fixed values reach the
  writer. Regression covers fixed oversized lowering and dynamic oversized
  rejection.
- [x] Focused Atomizer and curated-manifest checks pass (`131 passed`); Ruff
  and `git diff --check` pass.
- [x] Flat-route all-observable BNG3/libRoadRunner comparisons pass for
  `BIOMD0000000463` and `BIOMD0000000608`. Reports:
  `/private/tmp/BIOMD0000000463-large-stoich-flat.json` (SHA-256
  `8c325fa19460bb79004825c2698a3e70162e863970e157f2c2b3d77de88ee209`) and
  `/private/tmp/BIOMD0000000608-large-stoich-flat.json` (SHA-256
  `ab0010bf807e9e0e0c0ce2971b1e3c83e1da081cad7b064553afb439d8b24b71`).
- [ ] Full curated refresh began before this change; both-mode selected runs
  for these two large models timed out at 90 seconds. Recheck their Atomized
  routes and aggregate full-inventory status.

## Never-firing event proof and exact-source validation — 2026-09-26

- [x] Event analysis now proves additional state-independent triggers cannot
  fire and reports them as informational instead of untranslated events.
- [x] Refreshed the pinned SBML Test Suite: `1,282 passed, 641 unsupported,
  0 failed, 0 timeouts`; 55 new stochastic cases pass, with zero regressions.
  These cases contain events proven never to fire. The gate includes BNG3
  CVODE/libRoadRunner comparison but not official SBML Test Suite reference
  trajectory validation. Report `/private/tmp/bng3-sbml-suite-final-code.json`,
  SHA-256 `f4df13b873836a4931edb117aec238938fa1227aec6a0e624697148010470b84`.
- [x] Full curated BioModels inventory rerun against final code: `774/1,083`
  SBML pass, `134` unsupported, `5` fail, `170` timeout. Rate-rule assignment
  mapping recovers `BIOMD0000000245`; fixed oversized stoichiometry recovers
  `BIOMD0000000353`. Full both-mode run for `BIOMD0000000463` times out even
  though selected flat-mode parity passes. Report `/private/tmp/bng3-curated-atomizer-final-code-full.json`,
  SHA-256 `aa1fcaebd8b69beeb4c3274d6e3813f9b3e98d1d787dcc0bdcb71f4771b209ad`.
- [x] Three-model, three-repeat modern Atomizer/BNG2/PyBioNetGen comparison
  completed in flat and Atomized modes. BNG3 modern output is deterministic
  across all 18 model/mode/repeat samples; BNG3 and BNG2 both generate all 18
  networks and structural parity is `18/18`. Strict rate-string parity is
  `0/18`; this measures serializer expression matching, not numerical parity.
  PyBioNetGen emits output for 9/18 samples; the other 9 fail in legacy code
  (including unresolved `longEnough`). Its generated outputs did not yield
  comparable networks. Report `/private/tmp/bng3-atomizer-assignment-cross-engine.json`,
  SHA-256 `86d75a81691c85cbcaa22698e0bea00d57a6cad5381ee244d5e984f716c3ae7d`.

## Dynamic stoichiometry in deterministic ODE export — 2026-09-26

- [x] Lower rate-rule- or MathML-driven species-reference coefficients into
  per-species `TotalRate` rules. Dynamic coefficients in kinetic laws are
  expanded through the same rule/state mapping. Dynamic large values no longer
  require huge repeated BNGL patterns.
- [x] Preserve fail-closed boundaries for coefficients without a lowerable
  expression and fast, executable Multi, or FBC semantics. Generated notes
  bound this feature to deterministic ODE equivalence; NFsim-style shared
  stochastic reaction events are not claimed.
- [x] Regression and focused Atomizer checks pass (`131 passed`). Full pinned
  SBML Test Suite: `1,325 passed, 598 unsupported, 0 failed, 0 timeouts`,
  with 43 new passes and zero regressions. New cases include
  `semantic/00973`, `00989`, `00990`, `01103`-`01105`, `01107`-`01109`,
  `01121`, `01449`-`01453`, `01517`, `01562`-`01563`, `01631`-`01637`,
  `01723`, `01727`-`01729`, `01736`-`01738`, and `01742`-`01751`.
  Report `/private/tmp/bng3-sbml-suite-dynamic-stoichiometry.json`, SHA-256
  `770c8a46b81a4ab2e0eeb54bdd184e903f1babc851de158004cd4e057fa31190`.
- [x] Remaining stoichiometry blockers: six negative coefficients and ten
  dynamic cases blocked by state-dependent events or fast-reaction semantics.
  The suite's 429 state-triggered events, 70 unsupported MathML cases, and
  flux/FBC constraints remain separate unsupported surfaces.
- [ ] Recheck the curated BioModels inventory after this writer change. The
  final-code inventory before dynamic coefficient lowering passed `774/1,083`
  and had no standalone dynamic-stoichiometry cause.

## Dynamic stoichiometry in `rateOf` and zero-delay simplification — 2026-09-26

- [x] Extend reaction-derived `rateOf(species)` lowering to finite dynamic
  stoichiometry defined by an assignment/rate rule, initial assignment, or
  MathML expression. Keep event-controlled reference symbols fail-closed.
  Fixed fractional coefficients are accepted for deterministic ODE derivatives.
- [x] Simplify SBML `delay(expression, 0)` to `expression`; nonzero delays of
  dynamic values remain unsupported because they require state history.
- [x] Official `semantic/01543` now passes Atomizer roundtrip and all-observable
  BNG3/libRoadRunner comparison (4 observables; max absolute difference below
  `1.2e-12`). Full pinned suite moved from `1,325/598` to `1,326/597`, with no
  failures or timeouts. Unsupported MathML cause fell `70` to `69`; events stay
  the main blocker at `429`. Report `/private/tmp/bng3-sbml-atomizer-final-after-rateof.json`,
  SHA-256 `7eab13bc3cfe5231b34a9491e657eafda200b402c60eb4d759afc31795aeedc6`.
- [x] Three repeats in flat and Atomized modes are deterministic; BNG2 network
  structures match `6/6`. Strict rate-string matching is `0/6` because generated
  BNGL uses algebraically equivalent directional `if` expressions. Legacy
  PyBioNetGen failed to produce output for this model. Report
  `/private/tmp/bng3-rateof-dynamic-cross-engine-01543.json`, SHA-256
  `8dcf83c294c89dfa18723e8b3573496915768fd646c52c3638aabda90490a7fa`.
- [x] Full curated BioModels refresh completed against the updated parser:
  `774/1,083` SBML pass, `134` unsupported, `5` fail, `170` timeout; all 1,096
  inventory entries accounted. No model status changed from the previous
  full-code report, so the SBML Test Suite `rateOf` gain is not a curated-model
  gain. `BIOMD0000000353` and `BIOMD0000000245` remain passes; `BIOMD0000000463`
  still times out. Report `/private/tmp/bng3-curated-final-rateof.json`,
  SHA-256 `c1ef3ee2e2c4385a4ac2adafcf4bf431bab11f6c28630e3afb253479b05a8cc4`.

## Closed-form time delays — 2026-09-26

- [x] Lower `delay(x, tau)` when `x` is an assignment-rule expression that can
  be reduced to simulation time plus immutable symbols: inline the rule chain
  and substitute `time - tau`. General delay history, reaction/rate-rule
  history, and dynamic delay lengths remain unsupported.
- [x] Full pinned SBML Test Suite: `1,331 passed, 592 unsupported, 0 failed,
  0 timeouts`; five additional cases pass with no regressions. MathML blockers
  fell from `69` to `63`. Newly passing: `semantic/00937`, `01173`, `01176`,
  `01318`, and `01319`. `00937` matches libRoadRunner on all observables
  exactly. Report `/private/tmp/bng3-sbml-dynamic-assignment-delay-final.json`,
  SHA-256 `79e07b8fba7a2b875b0ed7b5c177511755f71a37814001898cff9ffbe400d4cd`.
- [x] BNG3 output is deterministic across three repeats in both modes for
  `semantic/00937`. BNG2 cannot generate a network for this zero-reaction model
  (`ABORT: Nothing to do`); legacy PyBioNetGen fails dependency resolution
  (`KeyError: 'x_ar'`). These are not counted as parity passes. Report
  `/private/tmp/bng3-time-delay-cross-engine-00937.json`, SHA-256
  `f08ee9c7cfda21cab598941f9af6d1b4c871d711c590a557d917f811b695e827`.
- [x] Targeted both-mode refresh of every cached curated BioModels source with
  a delay expression (`BIOMD0000000024`, `0034`, `0025`, `0154`, `0155`,
  `0196`, `0841`) found no new pass. Remaining delay/history or event blockers
  keep these seven unsupported; per-model reports are
  `/private/tmp/BIOMD0000000024-delay-refresh.json` through
  `/private/tmp/BIOMD0000000841-delay-refresh.json` for the listed IDs.

## Affine state-history delays and fixed stoichiometry — 2026-09-26

- [x] Lower nonnegative fixed delays of scalar states with exact affine
  histories `x' = a*x + b`. Accept explicit rate rules or reaction-derived
  affine fluxes with constant conversion factors; substitute histories into
  affine expressions, including `rateOf`, and fold static species-reference
  stoichiometry before delay lowering. Delayed assignment-rule time functions
  remain supported. Dynamic delays, nonlinear or coupled state systems,
  event/initial-assignment histories, and unresolved stoichiometry remain
  fail-closed.
- [x] Full pinned SBML Test Suite now reports `1,349 passed, 574 unsupported,
  0 failed, 0 timeouts`: 18 additional passes over the closed-time-delay
  report, with zero regressions. New passes: `00939`, `01320`, `01400`,
  `01401`, `01403`, `01404`, `01406`, `01407`, `01409`, `01413`-`01415`,
  `01417`, `01418`, `01454`, `01534`, `01537`, and `01538`. Report
  `/private/tmp/bng3-sbml-final-after-rateof-stoich.json`, SHA-256
  `e39aa662fba9c12103540f5df2e3017d87e9721a1a80b273dda851381e6defad`.
- [x] Ten representative time-course cases pass direct BNG3/libRoadRunner
  observable comparison (`00939`, `01400`, `01401`, `01403`, `01406`, `01409`,
  `01413`, `01417`, `01418`, `01538`); maximum observed absolute error is
  `1.45e-6`, below each model's comparison tolerance. Individual reports are
  `/private/tmp/bng3-delay-simulation-00939.json`,
  `/private/tmp/bng3-delay-rateof-sim-01400.json` through
  `/private/tmp/bng3-delay-rateof-sim-01409.json`,
  `/private/tmp/bng3-delay-simulation-01413.json`, and
  `/private/tmp/bng3-delay-simulation-01538.json`, plus
  `/private/tmp/bng3-delay-stoich-sim-01417.json` and
  `/private/tmp/bng3-delay-stoich-sim-01418.json`.
- [x] Modern Atomizer parity checks: `30` focused SBML parity tests pass;
  Ruff, compileall, and `git diff --check` pass. Targeted flat+atomized refresh
  of all seven cached curated BioModels with delay math still reports
  unsupported, due to general history or state-dependent events. Full current-
  parser inventory accounts for all 1,096 entries: `774/1,083` SBML pass,
  `134` unsupported, `5` failed, and `170` timed out. No model status changed
  from the prior full-code report. Report
  `/private/tmp/bng3-curated-final-delay-features.json`, SHA-256
  `fcd92da8d6389394d7b44c1ca163d79cb9259c555986b639d36edab06e2b5fdb`.

## Nonnegative affine time-dependent delay lengths — 2026-09-26

- [x] Lower `delay(value, tau(time))` when `tau` simplifies to `a*time + b`
  with finite, statically known `a >= 0` and `b >= 0`. This covers time, `time/c`,
  `c*time`, and nonnegative fixed offsets. For `tau > time`, the exact initial
  history is used; negative, nonlinear, state-driven, or event-driven delay
  lengths remain unsupported.
- [x] Official cases `semantic/00981`, `00982`, and `00983` now pass. Their
  trajectories match libRoadRunner on 2, 3, and 3 observables respectively;
  maximum absolute error is `3.6e-15`. `00984` remains unsupported because its
  delay is event-controlled. The full pinned suite remains `1,352 passed, 571
  unsupported, 0 failed, 0 timeouts`; no regressions from the preceding full
  report. Report `/private/tmp/bng3-sbml-time-affine-final.json`,
  SHA-256 `9f08285e54914d00587c1e3ae805de08ec2c7800262e9c52a3fecec8542096fe`.
- [x] Modern Atomizer test suite passes (`291 passed, 1 skipped`), including
  `32` focused SBML parity tests; Ruff, compileall, and `git diff --check` pass.
  Final-code targeted both-mode refresh of all seven curated BioModels with
  delay math still finds no supported-history model: they remain blocked by
  general history or events. The full inventory report immediately before this
  slice accounts for all 1,096 records with `774/1,083` SBML passes, `134`
  unsupported, `5` failed, and `170` timeouts; no delay-bearing model changes
  status in the targeted refresh.

## Linear algebraic boundary species — 2026-09-26

- [x] Permit the existing unique-linear-unknown lowering to target an
  unreacted mutable boundary species. Reaction participants, event-controlled
  species, and coupled/nonlinear algebraic systems remain unsupported.
- [x] `semantic/00554` now roundtrips and passes seven-observable
  BNG3/libRoadRunner comparison (maximum absolute error `6.93e-12`). Full
  pinned suite: `1,353 passed, 570 unsupported, 0 failed, 0 timeouts`, one new
  pass and zero regressions. Report
  `/private/tmp/bng3-sbml-algebraic-boundary-final.json`, SHA-256
  `2180c26495081d725967570aa56d52440d7371a9bd15d3d4d3cea451051142e4`.
- [x] Modern Atomizer tests pass (`292 passed, 1 skipped`); Ruff, compileall,
  and `git diff --check` pass. A source scan of all cached curated BioModels
  found no unreacted boundary-species algebraic target, so the preceding full
  curated report remains applicable.

## Immediate SBML trigger edges from initial values — 2026-09-26

- [x] Evaluate a state's initial value when `trigger initialValue="false"` and
  lower the exact rising edge at `t=0`. Use this path only for immediate
  events; delayed events and triggers that may change later remain fail-closed.
  Rule- and initial-assignment-controlled symbols are excluded from initial
  value folding.
- [x] Full pinned SBML Test Suite: `1,366 passed, 557 unsupported, 0 failed,
  0 timeouts`; 13 additional passes with zero regressions. Newly passing
  `semantic/01332`-`01334`, `01336`-`01337`, and `01684`-`01686`,
  `01693`-`01697`. Report `/private/tmp/bng3-sbml-initial-event-full.json`,
  SHA-256 `64eca75abf850812f8fc12c576a03546f8763ae431c2fd34815229c3af2caa1c`.
- [x] Three newly supported cases (`01684`-`01686`) pass four-observable
  BNG3/libRoadRunner trajectory comparison each; maximum absolute difference
  is `6.94e-18`. `01332` also passes conversion/roundtrip, but has no
  observables, so its simulation comparison is vacuous.
- [x] Modern Atomizer tests: `293 passed, 1 skipped`; Ruff, compileall, and
  `git diff --check` pass. Curated BioModels inventory not refreshed yet.

## Affine rate-rule event thresholds — 2026-09-26

- [x] Solve direct one-state event thresholds for parameters with a finite
  initial value and constant rate rule. Accept only strict rising crossings
  toward the true side; reject coupled/nonconstant rates, assignment- or
  initial-assignment-controlled values, event-modified trigger states, and
  non-direct comparison triggers. Numeric MathML folding now handles n-ary
  `plus`/`times`, inverse trigonometric/hyperbolic functions, and the SBML
  constants `pi` and `exponentiale` used by fixed event delays.
- [x] `semantic/01530`, `01532`, and `01533` now pass. In `01532`, all 53
  events are scheduled; its `trig_amt` trajectory matches libRoadRunner with
  maximum absolute error `1.78e-15`.
- [x] Full pinned suite: `1,369 passed, 554 unsupported, 0 failed, 0 timeouts`;
  three new passes beyond the initial-edge report, zero regressions. Event
  cause count is now `413` (from `429` before these two event slices). Report
  `/private/tmp/bng3-sbml-affine-event-full.json`, SHA-256
  `dc3b6e726474b3fea6822d1f278d448c4c23b2f04cd2398ce3535b08eb84a0f4`.
- [x] Modern Atomizer tests: `295 passed, 1 skipped`; Ruff, compileall, and
  `git diff --check` pass. Cached-source triage covered 1,084 BioModels XML
  sources (nine failed source parsing); no direct affine-rate trigger matched.
  Ten models contain 21 `trigger initialValue=false` events; all are fixed-time
  except `BIOMD0000000825`, whose initial state makes its state trigger false.
  Its targeted both-mode run remains unsupported for the expected dynamic
  state-event reason. No curated gain is claimed; the broad refresh was stopped
  after source triage showed no additional candidate models.

## BNGIR numeric expression canonicalization — 2026-09-26

- [x] Serialize numeric-only C++ expressions with Python's shortest
  round-tripping float representation. This fixes `0.10000000000000001` in
  BNGIR JSON while preserving symbolic expression text.
- [x] Existing BNGIR regression failed before the change and passes after it;
  BNGIR tests: `11 passed`.
- [x] Full Python suite now passes: `537 passed, 28 skipped`; Ruff,
  compileall, and `git diff --check` pass. The earlier float-serialization
  failure is resolved.

## Periodic event schedules driven by reset parameters — 2026-09-26

- [x] Expand `time - reset >= interval` events into exact repeated scheduled
  actions when a parameter reset is assigned to `time`, event assignments are
  parameter-only and finite, and no competing event/rule controls the state.
  Evaluate each recurrence against the previously scheduled parameter values;
  preserve the requested simulation horizon and cap expansion at 10,000
  firings per group. Prove a non-time event never fires only when its
  parameter-only trigger stays false through every periodic update.
- [x] `semantic/00952`, `00953`, `00963`, and `00964` now pass. Three have
  observable parity checks with zero maximum error; `00963` has no observables.
  In `00952`, simultaneous `Q`/`R` increments preserve `Q-R=0`, so the
  `abs(Q-R) >= 4` event is proven never to fire.
- [x] Full pinned suite: `1,373 passed, 550 unsupported, 0 failed, 0 timeouts`;
  four more pass than the affine event report, no regressions. Event cause
  count is `409`. Report `/private/tmp/bng3-sbml-periodic-event-full-final.json`,
  SHA-256 `5448cd5ec2c1de49086afc4c1f6f15aa250b3f646cb0dcb09fbce255bd12751f`.
- [x] Full Python suite: `532 passed, 28 skipped`; Modern Atomizer tests:
  `298 passed, 1 skipped`. Ruff, compileall, and `git diff --check` pass.
  Scan of 1,084 cached BioModels XML sources found no matching periodic-reset
  trigger, so no curated-model gain is claimed.

## Periodic events driven by constant-rate reset states — 2026-09-26

- [x] Lower repeated events for a parameter reset by the event while a
  constant rate rule drives it across a fixed threshold. Support rising
  `gt/geq/lt/leq` crossings, static reset values, same-time disjoint parameter
  assignments, constant priorities, and finite horizons. Evaluate supported
  `delay(reset, duration)` assignment expressions from the exact piecewise
  linear reset history; reject delay history for other state variables.
- [x] Prove coupled invariant/error-check events never fire when their
  parameter-only triggers stay false through every scheduled update. Prove
  time lower-bound checks false only when their threshold lies beyond the
  requested simulation horizon.
- [x] Add delayed periodic clock-reset support for fixed nonnegative delays
  with execution-time assignments. Recurrence interval starts from the prior
  reset's execution time; reject trigger-time assignment semantics when a
  positive delay would make reset history ambiguous.
- [x] Support bounded delay history for event-updated parameters in assignment
  rules when every delay is at least the requested simulation horizon. Such
  queries stay at or before t=0, so lowering to initial values is exact over
  the requested run. Keep the delay and dropped diagnostic when the run
  extends beyond a delay. The suite runners now pass their simulation horizon
  and step count into both source and reimport Atomizers.
- [x] Fold acyclic, finite, constant initial assignments when resolving
  compile-time event parameters and priorities; cycles, duplicate targets,
  and dynamically controlled values remain non-foldable. `semantic/01588`
  now passes with exact BNG3 / libRoadRunner parity.
- [x] SBML Test Suite gains: `semantic/00962`, `01588`-`01593`, and `01599`.
  Cases `01588` and `01590`-`01593` pass BNG3 / libRoadRunner CVODE observable
  comparisons with maximum absolute error `0`.
- [x] Full pinned suite: `1,381 passed, 542 unsupported, 0 failed, 0 timeouts`;
  eight new passes and no regressions from the prior full periodic-event
  report. Event unsupported cause count: `401`. Report
  `/private/tmp/bng3-sbml-initial-assignment-priority-full.json`, SHA-256
  `f86ba5cf12406febf9b406b88d0baf216a88fa19631e707f04192246d3f99480`.
- [x] Full Python suite: `537 passed, 28 skipped`; Modern Atomizer tests:
  `303 passed, 1 skipped`. Ruff, compileall, and `git diff --check` pass.
- [x] Full offline curated BioModels inventory refresh before initial-assignment
  event folding: `773 passed, 134
  unsupported, 5 failed, 171 timed out` among 1,083 SBML records. Relative to
  the previous full report, no model status improved; one formerly passing
  record (`BIOMD0000000637`) timed out in the full run but passed an isolated
  both-mode recheck. This is timeout variance, not a feature regression or
  curated gain. Report `/private/tmp/bng3-biomodel-bounded-history-full.json`,
  SHA-256 `6392e688218a1c5efea4880d2b536c354a1d14893189812a58a52c2cfdd19b08`.
- [x] Cached-source triage found 40 BioModels XML files with both events and
  initial assignments, but none has event priority math referencing an
  initial-assigned symbol; no curated-model gain is expected from this narrow
  foldability change.

## Horizon-bounded SBML delay history — 2026-09-26

- [x] Fold `delay(expression, duration)` to the exact initial-state value when
  the duration is a nonnegative compile-time constant at least as large as the
  requested simulation horizon. Resolve species amount/concentration,
  parameters, compartments, species-reference coefficients, and pure SBML
  functions. Apply this to rules, reaction rates, events, initial assignments,
  functions, and time-varying stoichiometry. Keep mutable delay lengths,
  assignment-rule-controlled history, unknown initial values, and ambiguous
  t=0 event edges fail-closed.
- [x] The strict baseline-horizon full SBML suite is `1,388 passed, 535
  unsupported, 0 failed, 0 timeouts`, seven new passes and no regressions from
  the prior full report. New passes: `semantic/01410`-`01412`, `01419`,
  `01480`-`01481`, and `01535`. Report
  `/private/tmp/bng3-sbml-bounded-delay-immutable-full.json`, SHA-256
  `0cc45f13158b3bb04071bf4b995c4ac1af6c610e1f5a32ff45c76ef256678994`.
- [x] Targeted both-mode offline BioModels roundtrip and CVODE/libRoadRunner
  checks now pass for `BIOMD0000000025`, `BIOMD0000000154`, and
  `BIOMD0000000034`. Other targeted delay models remain blocked by state-event
  execution or delays shorter than the test horizon.
- [x] Add exact time-window lowering when all non-time gates are immutable
  compile-time predicates; prove false gates never fire. Mutable gates stay
  untranslated. No official suite gain was attributable to this gate slice.
- [x] Full Python suite: `542 passed, 28 skipped`; all modern Atomizer tests:
  `308 passed, 1 skipped`. Ruff, compileall, and `git diff --check` pass.

## Static state event triggers — 2026-09-26

- [x] Resolve direct SBML event thresholds over unchanged constant, boundary,
  or unreacted species, including thresholds expressed using a second static
  species. Constant triggers are proven never to fire; a true initial state
  with `triggerInitialValue=false` becomes the exact t=0 edge. Dynamic species
  remain untranslated.
- [x] Official cases `semantic/00699` and `00701` now pass. Six nearby cases
  still have another dynamic event, so remain unsupported. Cached curated
  BioModels event-blocker audit found no equivalent static-species candidate.
- [x] Full pinned suite: `1,390 passed, 533 unsupported, 0 failed, 0 timeouts`,
  two new passes and no regressions. Report
  `/private/tmp/bng3-sbml-static-boundary-full.json`, SHA-256
  `ebb03b86c4c56e95667807060777c2923913801e12b1569a6ab2c516ba09bfbe`.
- [x] Full Python suite: `544 passed, 28 skipped`; modern Atomizer tests:
  `310 passed, 1 skipped`. Ruff, compileall, and `git diff --check` pass.

## Linear algebraic constraints with immutable coefficients — 2026-09-26

- [x] Resolve constant parameters, compartments, and species as numeric
  coefficients when reducing a single-unknown linear algebraic rule to an
  explicit assignment. Dynamic coefficients, nonlinear equations, and coupled
  unknowns remain implicit constraints and stay fail-closed.
- [x] Twenty-nine official cases now pass: `00531`, `00543`, `00549`-`00551`,
  `00555`, `00557`-`00558`, `00561`-`00562`, `00565`, `00567`, `00571`,
  `00573`, `00613`-`00615`, `00628`-`00630`, `00673`-`00675`, `00687`,
  `00695`-`00696`, `00705`, and `01083`-`01084`. Case `00531` matches
  libRoadRunner across seven observables with maximum absolute error
  `2.23e-16`.
- [x] Combined full pinned suite: `1,419 passed, 504 unsupported, 0 failed,
  0 timeouts`; 29 new passes, zero regressions. Only two algebraic-rule
  blockers remain, each combined with a separate unsupported feature. Event
  blockers: `399`. Report
  `/private/tmp/bng3-sbml-algebraic-static-full-final.json`, SHA-256
  `4f2212777119e99511591aa721a89dd30edd4341550c729aa361276ce35468bb`.
- [x] Full Python suite: `546 passed, 28 skipped`; modern Atomizer tests:
  `312 passed, 1 skipped`. Ruff, compileall, and `git diff --check` pass.

## Exact constant-flux event crossings — 2026-09-26

- [x] Derive affine trajectories for species whose net reaction flux is
  constant, with concentration/amount and fixed compartment-volume handling.
  Lower a single threshold crossing only when rules, initial assignments,
  events, mutable rates, fast reactions, and conversion factors cannot alter
  the trajectory. Delayed event assignments now read an exact state snapshot
  at trigger time or execution time according to `useValuesFromTriggerTime`.
- [x] Twelve additional official cases pass: `semantic/01324`-`01327`,
  `01584`-`01587`, and `01769`-`01772`. Full pinned suite: `1,431 passed,
  492 unsupported, 0 failed, 0 timeouts`; no regressions. Report
  `/private/tmp/bng3-sbml-event-snapshot-full-final.json`, SHA-256
  `65c48e10c88e6e285d97ec321556139b53c549b87d8c04c6d57226c35d0bd774`.
- [x] Full Python suite: `548 passed, 28 skipped`; modern Atomizer tests:
  `314 passed, 1 skipped`. Ruff, compileall, and `git diff --check` pass.
- [x] Full curated BioModels refresh completed before this constant-flux event
  slice: `781 passed, 127 unsupported, 5 failed, 170 timed out` among 1,083
  SBML records (13 non-SBML inventory entries remain explicit exclusions).
  Relative to the preceding full report, six unsupported models passed
  (`BIOMD0000000960`, `0570`, `0025`, `0154`, `0034`, `0955`), two timeouts
  recovered (`0579`, `0637`), and one unsupported model timed out
  (`BIOMD0000000735`); no prior pass regressed. The two timeout recoveries and
  one timeout regression are run-to-run variance. A cached-source scan found
  no curated model with the exact constant-flux event shape, so no curated
  gain is attributed to the newer event slice. Report
  `/private/tmp/bng3-biomodel-final-feature-refresh.json`, SHA-256
  `5c323485bc9ea61a3d26018750b59f43cafc54ea0de0ad68790866289c4feb74`.

## First-order exponential event crossings — 2026-09-26

- [x] Solve direct species thresholds when every affecting reaction rate is
  symbolically first-degree in that species with immutable coefficients,
  yielding an exact `x(t) = x(0) * exp(k*t)` trajectory. Compute crossing times
  logarithmically and evaluate delayed event assignments at trigger or
  execution time as declared. Nonlinear, coupled, rule-controlled, mutable,
  fast-reaction, and conversion-factor trajectories remain untranslated.
- [x] The latest full pinned SBML suite reports `1,468 passed, 455
  unsupported, 0 failed, 0 timeouts`; 37 new passes and no regressions from
  `1,431/492`. Event blockers fell from 387 to 350. New cases:
  `00619`-`00624`, `00634`-`00639`, `00646`, `00648`-`00649`, `00651`,
  `00679`-`00683`, `00689`-`00690`, `00700`, `00702`, `00707`-`00708`,
  `00723`, `00730`, `00736`-`00737`, `00749`-`00750`, `00769`-`00770`,
  `00996`, and `01094`. Report
  `/private/tmp/bng3-sbml-exponential-event-full.json`, SHA-256
  `c7eba8e7929477cf22fbebfdc93a719f6be372ec3483995d60d1f3af96253830`.
- [x] Full Python suite: `550 passed, 28 skipped`; modern Atomizer tests:
  `316 passed, 1 skipped`. Changed-file Ruff, compileall, and diff checks pass.
- [x] A generated-model ODE comparison for `semantic/00619` passes against
  libRoadRunner across five observables at `t_end=10`, 100 steps; maximum
  absolute difference is `1.69e-13`.
- [x] A cached-source scan of 1,084 curated BioModels XML files found no
  first-order threshold event matching this exact lowering shape.

## Affine delayed-history lowering — 2026-09-26

- [x] Lower `delay(x, d)` exactly for zero delay, initial-only history bounded
  by the requested horizon, or an independently affine state with constant
  nonnegative delay. The generated piecewise expression uses the SBML initial
  history for `t <= d` and the exact shifted affine trajectory afterward.
  Resolve a unique time-zero initial assignment when its expression is
  compile-time evaluable; keep ambiguous or coupled histories untranslated.
- [x] Three official cases now pass: `semantic/00938`, `00940`, and `00942`.
  Full pinned suite: `1,471 passed, 452 unsupported, 0 failed, 0 timeouts`,
  three new passes and no regressions. Report
  `/private/tmp/bng3-sbml-affine-delay-full.json`, SHA-256
  `d5fb9c846058d242b84b809d8772c75ab7360dcbd8e6b444936f944d4a135a60`.
- [x] Targeted generated-model ODE comparisons against libRoadRunner passed
  for all three cases (three observables each), maximum absolute differences:
  `00938: 4.44e-16`, `00940: 0`, `00942: 0`.
- [x] Full Python suite: `551 passed, 28 skipped`; modern Atomizer:
  `317 passed, 1 skipped`. Changed-file Ruff, compileall, and diff checks pass.
- [x] A cached scan of 1,084 curated BioModels XML files found no fixed-delay
  call whose history target is a single symbol of this lowering shape.

## Exponential rate-rule event values and delays — 2026-09-26

- [x] Lower threshold events over a parameter with a rate rule of the exact
  form `p' = k*p` when `k` is immutable and no event or initial assignment can
  reset `p`. Also resolve fixed-time event assignments and event delays from
  independently proven affine or exponential trajectories. Mutable, coupled,
  nonlinear, or reset-controlled states remain untranslated.
- [x] Extend exact state-threshold parsing to constant-scaled state expressions
  such as `0.01*p`; reject dynamic or zero scales.
- [x] Five additional official cases pass: `semantic/01261`, `01266`, `01268`,
  `01297`, and `01299`. Full pinned suite: `1,476 passed, 447 unsupported,
  0 failed, 0 timeouts`; five gains, zero regressions from `1,471/452`. Event
  blockers fell from 350 to 345. Report
  `/private/tmp/bng3-sbml-exp-rate-param-final.json`, SHA-256
  `c8c23ebfb0bf079004c29b65e5cf4f78f694927f081067cf2d3559ef71f0c9f4`.
- [x] Extended-horizon (10 time units, 100 steps) generated-model CVODE
  comparisons against libRoadRunner passed for all five cases. Maximum
  absolute errors were `0` for `01261` and `4.06e-12` for each other case.
- [x] Full Python suite: `554 passed, 28 skipped`; Ruff, compileall, and
  `git diff --check` pass. Full BioModels inventory was not rerun; a cached
  source screen found four XML files using `rateOf`, none matching the simple
  immutable-coefficient parameter rate-rule trigger implemented here.
