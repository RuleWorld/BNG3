# BNG3 Convergence: Definition of Done and Remaining Checklist

**Status:** Active; not complete
**Last audited:** 2026-09-02
**Repository:** RuleWorld/BNG3
**Working branch:** codex/bng3-integration-foundations
**Audited semantic code head:** 7241746a50ed0f87f23ad93eda38b2a9e7cca180
**Checklist refresh base:** 7241746 (source-derived guarded release-LTO checkpoint; refresh after each checkpoint)
**Latest workflow checkpoint:** e7cd59bd793a30d31bf2b8822725e05ba097b3d0 (fail-closed weekly cross-validation repair)
**PR:** RuleWorld/BNG3#2
**Independent implementation reference:** RuleWorld/bngplayground Atomizer
**Energy-evaluator source reference:** akutuva21/nfsim PR #475, merged at
6690fda5d9e053df822d0248ebae185f5caca82a; accepted energy-source cutoff
3b046fc1b9f76719d92be22279b24992cdae7c35. The public
`akutuva21/nfsim` fork currently has master at
`c51c7a34128d188189485bd318aeae4d936bcb29` (observed 2026-09-01); later
non-energy PRs #476 and #477 are deliberately not silently included in the
BNG3 port.

This is the execution checklist for the BNG3 convergence goal. It turns the
completion charter and Section 11 of BNG3_INTEGRATION_PLAN.md into auditable
work items. The unification work orders in BNG3_unification_spec.md remain the
detailed dependency map; provenance/capability-matrix.yml remains the
capability inventory.

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

## Current verified checkpoint

These items describe the current checkpoint. They do not satisfy the full
completion gate.

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
- [x] Historical published CI-repair checkpoint is
  `9a2475a0af360d685dc41eb9bb376f6517d74b4d`; `gh api` and `gh pr view 2`
  agreed on this branch/PR source head immediately after push, and PR #2
  remains open.
- [x] The small documentation grammar fix remains the only unrelated tracked
  BNG3 worktree modification. It remains intentionally unstaged and must not
  be mixed into semantic or checklist commits.
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
- [ ] Separate local Debug/ASan evidence has not yet been rerun for 5f6da07;
  prior 0f83347 evidence was supplemental memory-safety coverage, not a
  substitute for hosted sanitizer and leak/UBSan gates.
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
- [x] Non-strict provenance, corpus-manifest, generated-manifest, and exception
  ledger checks pass. The strict provenance gate remains intentionally red with
  10 pending source/oracle/compiler/Python-lock approval errors; the exception
  ledger itself is valid with 0 active entries under the CI budget check.
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
- [ ] NET validation performs actual write/read/write idempotence.
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
- [ ] The duplicate cpp/nfsim/nauty24 build is removed only after independent
  identity evidence is green.
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

- [ ] A single parsed/resolved expression representation and error model is
  shared across ODE RHS, SSA/PLA/PSA propensity evaluation, and NFsim
  local/global functions.
- [ ] NFsim ExprTk compilation and the NFSIM_USE_EXPRTK build path are removed
  only after the shared evaluator passes all dependent gates.
- [ ] Numeric literals, parameters, observables, time, roots, logs/bases,
  constants, function definitions, nested functions, and domain errors have
  cross-backend tests.
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
- [ ] The structured SBML atomize=>1 failure is resolved or receives a
  maintainer-approved compatibility disposition with a replacement gate.
- [ ] Unsupported SBML packages, qualitative models, dictionaries, and
  topology cases are reported in an inspectable unsupported-feature report.

### 7.3 SBML-Multi

- [x] Current parser detects and exposes conservative canonical single-level
  Multi structures as reference diagnostics.
- [ ] Canonical Multi molecule types, components, states, complexes,
  species/seed patterns, bonds, compartments, and annotations are fully
  reconstructed from approved fixtures.
- [ ] Multi output is emitted through a supported writer with schema and
  semantic round-trip tests.
- [ ] An independent oracle and end-to-end execution semantics are approved.
- [ ] Multi-derived structures are injected into the simulated network only
  after the oracle and execution gate pass.
- [ ] Full SBML-Multi simulation, not merely diagnostics/comments, passes Tier-X
  and representative NF/network gates.

### 7.4 All supported formats and graph writers

- [ ] BNGL import/export is semantically round-trippable.
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
- [x] CI truthfulness repair checkpoint
  `e7cd59bd793a30d31bf2b8822725e05ba097b3d0` has a source-derived local
  fail-closed workflow contract (`8 passed`) and an exact public branch/PR
  readback. Its CI, formatting, and CodeQL runs
  [33575648537](https://github.com/RuleWorld/BNG3/actions/runs/33575648537),
  [33575648574](https://github.com/RuleWorld/BNG3/actions/runs/33575648574),
  and [33575648533](https://github.com/RuleWorld/BNG3/actions/runs/33575648533)
  were queued at readback. This repair does not check the final hosted gate,
  weekly corpus, independent oracle, or release-candidate requirements.
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
- [ ] CodeQL or equivalent security analysis passes on the exact release head.
- [ ] Hosted weekly full validation and cross-validation complete with
  independent BNG2/NFsim inputs, not just parser inventory.

### 8.3 Packaging and release

- [ ] pyproject metadata has the correct BNG3 project/repository URLs,
  supported Python range, dependency policy, package data, and extension
  contents.
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

- [ ] BNG3_INTEGRATION_PLAN.md, BNG3_unification_spec.md, AGENTS.md,
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
    PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m smoke --bng-cpp build/cpp/bng_cpp
    PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m "parity and not slow" --bng-cpp build/cpp/bng_cpp
    NFSIM_BIN=build/cpp/NFsim PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m nf --bng-cpp build/cpp/bng_cpp
    PYTHONPATH=python:build/cpp python -m pytest -c tests/validation/pytest.ini tests/validation -m export --bng-cpp build/cpp/bng_cpp
    python -m build --sdist --wheel
    gh pr view 2 --repo RuleWorld/BNG3
    gh pr checks 2 --repo RuleWorld/BNG3

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
- Structured SBML atomization still has a deliberate visible error, and
  local validation has environment-dependent skips; hosted validation green
  does not prove full Tier-P/NF/X parity.
- SBML-Multi is currently diagnostic/reference extraction, not approved
  end-to-end simulated execution.
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
