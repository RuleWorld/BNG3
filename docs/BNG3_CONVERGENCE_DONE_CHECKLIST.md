# BNG3 Convergence: Definition of Done and Remaining Checklist

**Status:** Active; not complete
**Last targeted audit:** 2026-09-28 (full convergence checklist remains open)
**Repository:** RuleWorld/BNG3
**Working branch:** `main`.
**Latest full pinned SBML Test Suite report:** exact BNG3 commit `bf210ab73950646db655559ba2dd7aa56aeb2c15`, suite commit `cf38585fac5de8e0e90112febb62851ee2181816`, `1,744 passed / 179 unsupported / 0 failed / 0 timed out` (`t_end=1`, 10 samples). Six cases gained and none regressed against the preceding full report. Aggregate Core remains open. Report `/private/tmp/bng3-time-dependent-quadratic-delay-full-sbml.json`, SHA-256 `46951ae3ece7f02b45d932ac946a394df021d375811d9daaa00a8419abf7e02c`.
**Latest current-source curated BioModels report:** none. The user's current-source flat and Atomized rerun was stopped at their request; it remains stopped and has no aggregate report. Earlier BioModels counts below are historical only.
**Last queried hosted CI before this checklist update:** exact head `88e560b3bbe9cbed7e0f113f55913d27ac94208b` was queried at 2026-09-29 03:52 UTC. CI `36517648525`, CodeQL `36517648572`, Cross-tool parity `36517648546`, and Lean semantic kernel `36517648522` were queued; all remain nonterminal.
**Historical audited heads:** Earlier local-only and hosted heads remain
recorded in the historical sections below; they are not current-head evidence.
## Claim audit at d04f648 — verified stale vs still real

This is the only section of this checklist verified line-by-line against the
source tree at `d04f648`. Every dated section below it is a snapshot taken at the
head named in its own heading; those entries are retained as the evidence record
and are **not** re-verified here. Where an entry below says `- [ ]`, that box
describes what was true when it was written, not necessarily what is true now.
Read the table below before treating any unchecked box as an open defect.

| Claim under audit | Verdict | Evidence at `d04f648` |
|---|---|---|
| `NFcore2::simulateNfcore2` is an unresolved link error blocking the native extension | STALE | No such symbol exists in `cpp/` or `python/`; the entry point is `NFcore2::SsaDriver` (`cpp/nfsim/NFcore2/driver.hh:54`), exercised by `tests/cpp/test_nfcore2_parity.cpp:100`. |
| One `bng::core::canonicalLabel` serves both engines | STALE (as named) / PARTIAL (as intent) | No `bng::core` namespace or that signature exists. The real symbol is `BNGcore::SpeciesGraph::canonicalLabel()` (`cpp/ast/SpeciesGraph.cpp:19`), used by network dedup. NFsim complex identity still has a *private* nauty path (`cpp/nfsim/NFcore/complex.cpp:315,413`), so the unification intent is genuinely still open. |
| The strict provenance gate fails with 10 pending errors | STALE | `python scripts/validate_provenance.py --require-approved` reports **13** errors at this head: baseline, 8 sources, 2 oracles, compiler images, Python lock. |
| The strict provenance gate is enforced somewhere | STALE | The non-strict call is the only one wired into CI (`.github/workflows/ci.yml:46`, `.github/workflows/parity.yml:45`). No workflow passes `--require-approved`, so the 13 errors cannot fail any job. |
| SBML round trip loses compartments, units, and conversion factors | STALE | Compartments and species are tagged and emitted (`writer.py:246-256`); unit normalization and conversion-factor handling are implemented (`writer.py:5448-5476`); unit exponents are parsed and validated in C++ (`cpp/io/SbmlReader.cpp:123,395`). |
| The eight SBML constructs (rate/assignment rules, initial assignments, events, algebraic rules, constraints, fast reactions, packages) are all unlowered | STALE | Rate rules inline to `TotalRate` rules (`writer.py:4884-4890`), variable stoichiometry is substituted (`writer.py:1768-1806`), packages carry governed diagnostics. Each either lowers or fails closed with a named diagnostic. |
| Structured-SBML `atomize=>1` still fails | STALE (duplicate entry) | The same checklist carries both a completed `- [x]` entry at line 5020 and this stale `- [ ]` at line 5035. The `- [ ]` contradicts its own completed entry. |
| SBML-Multi is "parsing-only" | STALE | `parse_multi_package` (`multi.py:339`) feeds executable BNGL reconstruction via `_parse_multi_package_complete` (`multi.py:2080`), and `multi_executable` gates deterministic flux lowering in `writer.py:5165`. |
| `t4`/`t5` are blocked on missing `sum()` | STALE | `sum()` is supported and passes through the writer unchanged (`bnglFunction("sum(1,2,3)")` -> `sum(1,2,3)`). The remaining NF protocol gaps are elsewhere and are not caused by `sum()`. |
| Non-collinear reaction stoichiometry is blocked in `events.py` | PARTIAL | The blocker is the rank-one collinearity guard in **`writer.py:8607-8612`**, which rejects any target reaction whose stoichiometric vector is not a scalar multiple of the trigger's. `events.py` consumes that lowered verdict rather than originating it. |
| ADR 0003's rejection inventory counts and line numbers | STALE (corrected) | The inventory is `docs/bngsim-migration-status.md:101`, which states "22 rejection sites, resolving to 19 distinct message texts"; three line numbers were wrong and are corrected in `d04f648`. ADR 0003 itself (`docs/adr/0003-bngsim-canonical-finite-backend.md:144-157`) only summarizes the list and carries no counts. |
| The Batch SSA parity gaps are real | REAL (fixed in `d04f648`) | The gaps were genuine defects, not stale entries, and were fixed in this commit. Unlike every other row, this box was accurate. |

### The four real defects fixed in `d04f648`

Each silently produced a *different model* rather than an error, which is why
they are the only items in this audit that were defects at all:

1. **Identifier collisions** — distinct SBML ids (e.g. `A-B` and `A_B`) collapsed to one BNGL name, merging species and rewriting a reaction. Now a governed `identifier`/`dropped` warning (`writer.py:2554-2557`).
2. **Silent missing-`kineticLaw` rate** — a reaction with no MathML was given rate `1` by an environment-tunable fallback and still generated a network. Now a governed `missingMath` record.
3. **`arcsinh`/`arccosh`/`arctanh` MathML names** — lowered to functions BNGL does not have (BNGL spells them `asinh`/`acosh`/`atanh`). The writer already had this map (`writer.py:490-494`); the parser did not, and now does (`parser.py:883-888`).
4. **Undeclared SBML packages** — a document declaring an SBML L3 package outside the eleven the parser knew (e.g. `topology:required="true"`) produced no diagnostic at all. Now a catch-all records the package as dropped and surfaces the requirement (`parser.py:3152-3181`).

Note the pattern: items 1, 2, and 4 were all cases where the code produced a
plausible-looking model instead of refusing one, which is the specific failure
mode this repository's own rule exists to prevent.

#### Measured blast radius of `d04f648`

Both trees were extracted and run side by side over every SBML input reachable
in this repository — 216 distinct documents (24 on-disk plus 192 inline
literals recovered by an AST walk of the test and source trees) under four
option modes, 864 runs per version:

| | |
|---|---|
| success/failure changed | 0 / 864 |
| raised exception changed | 0 / 864 |
| **non-comment BNGL bytes changed** | **0 / 864** |
| documents gaining appended `# [dropped]` comment lines | 7 / 216 |
| lines removed anywhere | 0 |

So the change is behaviour-preserving on everything it could be exercised
against, and its whole effect is to add diagnostics. Two of the seven changed
documents are the commit's own new tests. Of the five new code paths, only
`missingMath` fires on pre-existing inputs; `identifier` and `package:` fire only
on the new tests, and the `arcsinh` and `logbase` paths fire on **no** document in
the corpus at all — those two are covered by fragment-level tests only.

**This is not evidence about the pinned SBML Test Suite.** That corpus is not in
this repository, so the 1,744/179/0 result remains unmeasured against these
changes and must be re-run before any of them are claimed as suite-validated.

### Ready to apply, blocked on the ANTLR generator — `priority` as a model identifier

`priority` is a lexer keyword, so a molecule, observable, or parameter literally
named `priority` does not parse. Long-standing, not a regression. The fix touches
`keyword_as_mol_name`, `arg_name`, and a new `observable_name` subrule in
`BNGParser.g4`, plus `BNGAstVisitor.cpp` — the visitor change is required, not
optional: widening the grammar alone would make the name parse and then be
**silently dropped**, trading a parse error for data loss. The BNG2 `priority=5`
modifier is unaffected and was verified by parse-tree inspection, not merely by
the absence of an error.

Not applied. The generated parser is committed and is what the build compiles,
so a `.g4` change has no effect until regeneration; meanwhile the visitor
change breaks the build. The ANTLR generator is not vendored and no JRE is
installed. Patch and full analysis:
`docs/known-blocked/priority-keyword-parser-fix.md`.

## BNG3 dynamic-event representation boundary — 2026-09-29

- [x] Added versioned `bng3_events` syntax to the BNG3 parser and structured
  event records to the canonical AST. Trigger, delay, priority, initial value,
  persistence, trigger-time snapshot policy, and assignment expressions
  survive a BNGL writer/parser round trip.
- [x] The compiled-model boundary rejects this extension with an explicit
  unsupported-feature diagnostic. BNG3 does not execute these events yet;
  this parser/AST slice cannot be counted as simulation support.
- [x] Parser-unit coverage passed: 11 test cases, 86 assertions, including
  multi-event parsing, optional delay/priority, assignments, round trip,
  unknown format-version rejection, and ordinary identifiers matching event
  field words. The new syntax contract failed against the old parser first.
- [x] Full configured CMake build passed, and the full CTest suite passed
  `448/448` tests. This is local BNG3 evidence, not hosted CI or an SSTS
  rerun.
- [ ] No SSTS case was rebenchmarked or gained from this slice. Full dynamic
  event execution, solver roots, event queues, and cross-engine event parity
  remain open. Legacy BNG2 Atomizer remains incomplete and has not been
  benchmarked against all SBML; no BNG2 source was changed. Curated BioModels
  validation remains stopped at the user's request.

## Quadratic crossing at an equilibrium root — 2026-09-28

- [x] BNG3's quadratic event solver now returns no finite crossing when the
  requested threshold is exactly an equilibrium root of the scalar quadratic
  trajectory. Previously, the root-ratio formula divided by zero.
- [x] Added `test_quadratic_crossing_to_equilibrium_root_has_no_finite_time`.
  It failed first with `ZeroDivisionError`; after the guard, both focused
  modern Atomizer modules passed (`190 passed`) and the full Python suite
  passed (`692 passed, 28 skipped`). That full run emitted 1,380 existing
  deprecation warnings. Ruff, Black targeting Python 3.9, and
  `git diff --check` also passed.
- [x] Rechecked pinned SSTS `semantic/00374` after the fix. It remains
  unsupported because its state-triggered event is not lowered; one-case report
  `/private/tmp/bng3-current-00374-after-crossing-guard.json`, SHA-256
  `e5130e47626e5bc36a318fe6e940f5d4fde763c7b61e0def94b451c70e3e65ba`.
  The full SSTS suite was not rerun for this isolated numerical guard.
- [x] A libRoadRunner diagnostic run of `00374` at 200,001 samples resolved
  14 event resets from `t=0.45753` through `t=0.87893`; consecutive intervals
  shrink by approximately one half. This is evidence of Zeno-like recurrence,
  not proof of an infinite event sequence or a finite BNGL action schedule.
- [ ] This does not add an SSTS pass or establish full Atomizer coverage.
  Legacy BNG2 Atomizer remains incomplete and has not been benchmarked against
  all SBML; no BNG2 source was changed. Curated BioModels validation remains
  stopped at the user's request.

## Read-only review of open BNG3 Batch SSA PR #26 — 2026-09-28

- [x] Reviewed PR head `7b1d7ec57300911bbf2b8bceb7ac3c9a1ed5b6dd` and its
  `tests/test_batch_ssa_statistical_parity.py`. The mean-trajectory check
  assigns zero Z-scores whenever pooled SEM is at most `1e-6`, so deterministic
  CPU/GPU mismatches at those points are ignored. The advertised
  Kolmogorov-Smirnov section checks only whether both samples are constant; it
  does not call `ks_2samp` or otherwise compare nonconstant distributions.
  Therefore the PR's distributional-parity claim is not established by this
  test script.
- [x] PR checks passed for its C++/Python matrix, full-corpus validation,
  scoped BNG3/BNG2/NFsim and PyBioNetGen parity, CodeQL, formatting, and integration.
  Docker, source-distribution, wheel, PyPI, and scheduled historical-NFsim
  checks were skipped. No PR comment or source change was made.
- [ ] This scoped PR parity check is not an all-SBML BNG2 Atomizer benchmark.
- [ ] PR #26 remains open; its statistical assertions and skipped release/NFsim
  checks remain review and qualification gaps.

## BNG3 threshold-event cohort refresh — 2026-09-29

- [x] Revalidated ten pinned semantic cases at BNG3 head
  `ad742da46f5ecb67a9c1fd92abd45c39609b9934` against suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`: `00387`, `00393`, `00444`,
  `00445`, `00450`, `00451`, `01071`, `01073`, `01074`, and `01076`. All ten
  remain unsupported due to untranslated state-dependent events; 0 passed,
  0 failed, 0 timed out at `t_end=1` with 10 intervals. Index:
  `/private/tmp/bng3-atomizer-threshold-cohort-ad742da.json`, SHA-256
  `fc19684ef95d4b3dbe63c2509ee909726fc0d5b62b81da85e9e379ff3f7365e5`.
- [ ] This refresh establishes no new event lowering or SSTS gain. Related
  threshold cases with non-collinear reaction stoichiometry remain outside the
  existing exact-trajectory proof; no rank-one assumptions were loosened.
  Legacy BNG2 Atomizer remains incomplete and has not been benchmarked against
  all SBML. No BNG2 source was changed.

## Quadratic event groups with unrelated rate-rule targets — 2026-09-28

- [x] Modern Atomizer now supplies initial values for all event-assignment
  targets to quadratic trajectory resolvers, while requiring only trigger and
  assignment-expression dependencies to appear in reconstructed snapshots.
  This lets one event's rate law use a species assigned by another event
  without requiring unrelated targets governed by independent rate rules to
  have a trajectory in that reaction subsystem.
- [x] Added `test_quadratic_event_group_allows_unrelated_rate_rule_targets`.
  The synthetic model has coupled quadratic reaction dynamics, one event that
  resets a rate-law species, a second event assigning a separate rate-rule
  target, and a rate rule depending on the reaction subsystem. BNG3 execution
  matched libRoadRunner for all four species at 401 samples; focused event and
  parity tests passed (`187 passed`). Ruff, Black targeting Python 3.9, and
  `git diff --check` passed.
- [x] Pinned SSTS `semantic/00752` passed its one-case import/round-trip,
  native-reader, and BNG3 CVODE/libRoadRunner simulation checks at `t_end=4`
  with 400 intervals. Eight observables passed; maximum absolute difference
  was `1.56e-10`. Report `/private/tmp/bng3-ssts-00752-quadratic-group.json`,
  SHA-256 `1aabeab8335e5df1097223558d0ad2224620c5a43114e83d54e7c1d0de691820`.
  The partial invocation's aggregate Core flag is false by design; it is not a
  full-suite run. Report records base commit `886efb4` and a dirty tracked tree.
- [ ] This is one official SSTS case plus a synthetic parity test. It does not
  establish all-SSTS or all-SBML Atomizer coverage. Legacy BNG2 Atomizer
  remains incomplete and has not been benchmarked against all SBML; no BNG2
  source was changed.

## Delayed multi-event quadratic trajectories — 2026-09-28

- [x] Modern Atomizer now expands SBML function definitions before checking
  whether a quadratic event-group delay depends only on compile-time constants.
  A delayed event's assignments no longer count as immediate trigger changes;
  the scheduler evaluates other triggers again when the pending assignment
  executes.
- [x] Added `test_quadratic_event_group_accepts_constant_delay_function` with
  coupled quadratic reaction dynamics, a cross-event rate-law reset, and a
  constant delay represented through an SBML function. BNG3 trajectories
  matched libRoadRunner for all three species away from event times. Focused
  event and parity tests passed (`188 passed`); Ruff, Black targeting Python
  3.9, and `git diff --check` passed.
- [x] Pinned SSTS `semantic/00759` passed its one-case import/round-trip,
  native-reader, and BNG3 CVODE/libRoadRunner simulation checks at `t_end=4`
  with 400 intervals. Six observables passed; maximum absolute difference was
  `3.77e-12`. Report `/private/tmp/bng3-ssts-00759-delayed-quadratic-group.json`,
  SHA-256 `ca628aa91873fcfb4c8dcb6b8c84098e238ff4ff2a8b528c21583a14b9f2eeef`.
  The partial invocation's aggregate Core flag is false; report records base
  commit `fd9a065` and a dirty tracked tree.
- [ ] This adds one selected SSTS case, not full-suite or all-SBML Atomizer
  coverage. Legacy BNG2 Atomizer remains incomplete and has not been benchmarked
  against all SBML; no BNG2 source was changed.

## Cross-engine parity for quadratic delayed-event cases — 2026-09-28

- [x] Ran three repeats for each combination of SSTS `semantic/00752`, `00758`,
  and `00759`, flat/Atomized conversion, and modern BNG3/PyBioNetGen legacy
  Atomizers. Each output was parsed by both BNG3 and Perl BNG2. All 36
  Atomizer attempts succeeded; all 72 network generations succeeded; all
  36/36 BNG2/BNG3 network structure and strict rate comparisons passed. Raw
  BNGL output was deterministic across repeats in all 12 model/mode/Atomizer
  combinations.
- [x] Report `/private/tmp/bng3-atomizer-cross-engine-quadratic-delayed-events.json`,
  SHA-256 `18f2d1f240a2cdfaa188182ba246f123db49604cd86a93cca4c2cfbe5c087de0`.
  It records BNG3 `4b89d95`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`; BNG2's
  tracked tree was clean and BNG3's tracked diff was empty. Separate selected
  SSTS reports above compare BNG3 trajectories with libRoadRunner.
- [ ] This is a three-case interoperability sample; the benchmark checks
  network structure and rates, not trajectories or all-SBML coverage. It does
  not make an all-SBML claim for the incomplete legacy BNG2 Atomizer.

## Trigger-time-dependent quadratic event delay — 2026-09-28

- [x] Quadratic event groups now accept delay expressions that depend only on
  trigger time and compile-time constants. The delay is evaluated at the
  crossing time; dynamic model-state dependencies, negative or nonfinite
  delays, nonpersistent triggers, and unsupported delayed-value semantics
  remain fail-closed.
- [x] Added `test_quadratic_event_group_evaluates_time_dependent_delay_at_trigger`.
  It compares BNG3 and libRoadRunner trajectories for three species after a
  `delayScale * time` event. Focused event and parity tests passed (`189
  passed`); Ruff, Black targeting Python 3.9, and `git diff --check` passed.
- [x] Pinned SSTS `semantic/00887` passed one-case import/round-trip,
  native-reader, and BNG3 CVODE/libRoadRunner simulation checks at `t_end=4`
  with 400 intervals. Six observables passed; maximum absolute difference was
  `3.77e-12`. Report `/private/tmp/bng3-ssts-00887-time-dependent-quadratic-delay.json`,
  SHA-256 `3b2c61b0ae8f6943069b1668401026750978c2d2d8da60599ac4f80fee802a34`.
  This one-case report has aggregate Core false and records base commit
  `25faefb` with a dirty tracked tree.
- [ ] This adds one selected SSTS case, not all-SSTS or all-SBML coverage.
  Legacy BNG2 Atomizer remains incomplete and has not been benchmarked against
  all SBML; no BNG2 source was changed.

## Expanded cross-engine quadratic-delay cohort — 2026-09-28

- [x] Repeated the flat/Atomized, modern BNG3/PyBioNetGen, BNG3/Perl BNG2
  interoperability benchmark on four SSTS cases: `00752`, `00758`, `00759`,
  and `00887`. All 48 Atomizer attempts and all 96 network generations
  succeeded. BNG2/BNG3 network structure and strict rate comparisons passed
  48/48; raw outputs were deterministic in all 16 model/mode/Atomizer groups.
- [x] Report
  `/private/tmp/bng3-atomizer-cross-engine-quadratic-delay-cohort-4.json`,
  SHA-256 `8ad378e79eb8cb1b18f1395d3f58e4238d73cdabd208460f0081b217048c92ae`.
  It records BNG3 `25faefb`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`.
  BNG2's tracked tree was clean; PyBioNetGen had no tracked diff.
- [ ] This is a four-case network interoperability cohort; it does not
  establish trajectory parity with BNG2/NFsim or all-SBML coverage. The legacy
  BNG2 Atomizer remains incomplete and unbenchmarked against all SBML.

## Full pinned SBML Test Suite after quadratic delayed-event support — 2026-09-28

- [x] Ran all 1,923 pinned semantic and stochastic cases on exact BNG3
  commit `bf210ab73950646db655559ba2dd7aa56aeb2c15` at `t_end=1` with 10
  samples. Result: `1,744 passed / 179 unsupported / 0 failed / 0 timed out`.
  The source report records a clean tracked worktree and suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`.
- [x] Compared case IDs with the preceding full report: six gains and no
  regressions. Newly passing cases: `semantic/00752`, `00758`, `00759`,
  `00887`, `01626`, and `01627`. Report
  `/private/tmp/bng3-time-dependent-quadratic-delay-full-sbml.json`,
  SHA-256 `46951ae3ece7f02b45d932ac946a394df021d375811d9daaa00a8419abf7e02c`.
- [ ] The aggregate Core gate remains open with 179 unsupported cases. This
  run does not replace the stopped curated BioModels validation or complete
  the broader BNG2, PyBioNetGen, NFsim, packaging, and historical-PR work.

**Independent implementation reference:** RuleWorld/bngplayground Atomizer
**Energy-evaluator source reference:** akutuva21/nfsim PR #475, merged at
6690fda5d9e053df822d0248ebae185f5caca82a; accepted energy-source cutoff
3b046fc1b9f76719d92be22279b24992cdae7c35. The public
`akutuva21/nfsim` fork currently has master at
`c51c7a34128d188189485bd318aeae4d936bcb29` (observed 2026-09-01); later
non-energy PRs #476 and #477 are deliberately not silently included in the
BNG3 port.

## Quadratic events with downstream-only reactions — 2026-09-28

- [x] Modern Atomizer quadratic event analysis now projects the trigger
  trajectory onto reactions that change the trigger coordinate. It ignores a
  connected downstream reaction only when that reaction does not change a
  dynamic species read by the trigger or trigger-affecting kinetic laws.
  Species without a proven trajectory are excluded from trigger-time
  snapshots. A negative regression keeps lowering unsupported when another
  reaction changes a rate-law species.
- [x] Added an SBML model with `A + B -> P`, downstream `P -> Q`, and an event
  triggered by `A < 0.5`. BNG3 schedules the event and its generated trajectory
  matches libRoadRunner for `A`, `B`, `P`, and `Q` away from the event time.
  The focused event and SBML parity files pass (`186 passed`); Ruff, Black
  targeting Python 3.9, and `git diff --check` pass.
- [ ] This synthetic case adds no official SSTS pass. `semantic/00387` remains
  unsupported: its reverse reaction also changes the trigger's rate-law
  species, so it does not meet this lowering's proof conditions. This is not
  full SSTS, BioModels, or cross-engine coverage. The legacy BNG2 Atomizer
  remains incomplete and has not been benchmarked against all SBML; no BNG2
  source was changed.

## Event-target species-reference initial assignments — 2026-09-28

- [x] Fixed modern Atomizer output for a species-reference ID that has both
  an SBML initial assignment and a later event assignment. The parser resolves
  its numeric time-zero coefficient while retaining the reference as dynamic;
  the writer emits a parameter instead of a same-named fixed assignment
  function. Unresolvable initial values receive a dropped-semantics diagnostic.
- [x] Added regression `test_event_target_species_reference_initial_assignment_stays_dynamic`.
  It failed first because BNGL declared the SBML coefficient `4` instead of
  initial-assignment value `2`; it now verifies the initial value, no colliding
  function, and scheduled event update to `3`.
- [x] The Python suite passed: 685 passed, 28 skipped. Ruff, Black targeting
  Python 3.9, and `git diff --check` passed. The suite emitted 1,380 existing
  deprecation warnings.
- [x] At modified BNG3 source based on commit `f885c9a`, selected SSTS cases
  `semantic/01446`, `01447`, and `01448` passed conversion, round-trip, native
  reader, and BNG3 CVODE/libRoadRunner comparisons at `t_end=10` with 100
  intervals. Each individual record passed; each report is a one-case partial
  invocation, so the aggregate Core flag is false. Maximum BNG3/libRoadRunner
  absolute errors were `2.14e-14`, `2.14e-14`, and `5.33e-15`, respectively.
- [x] Perl BNG2 2.9.3 parsed the generated modern-BNG3 BNGL, generated
  networks, and ran scheduled ODE actions through `t=10` for all three cases.
  Comparing BNG2 observables with libRoadRunner on the same 101-point grids
  matched `01446` (`A`: `1.42e-14`). It did not match `01447` (`A`:
  `45.0879`; `B`: `1.42e-14`) or `01448` (`A` and `B`: `3.20821`). These
  are open cross-engine trajectory discrepancies, despite successful parsing
  and network generation.
- [x] Reports:
  - `01446`: `/private/tmp/bng3-ssts-01446-t10-after-initial-fix.json`, SHA-256
    `9de47254b34f3ff2ef45bd95d1d319e189bc8c5866ce187386e3fa1bbfee93b8`.
  - `01447`: `/private/tmp/bng3-ssts-01447-t10-after-initial-fix.json`, SHA-256
    `41a5fa80448f12f5cecaade290c0622d878e145a3579fd13bd1ea3a737f8ad4a`.
  - `01448`: `/private/tmp/bng3-ssts-01448-t10-after-initial-fix.json`, SHA-256
    `2a3554cb4c3b78579b5097432769cbd5b2adee9c89709f4fab51bfdcb182abfc`.
  - Cross-engine summary `/private/tmp/bng3-event-target-initial/cross-engine-summary.json`,
    SHA-256 `f3b7cc8c87cdbe2daffc193c2c995ed75d62c6f59f73a3a4543f7444e3b3c369`.
- [ ] This is a three-case modern-BNG3 Atomizer comparison. It does not test
  the legacy BNG2/PyBioNetGen Atomizer, establish all-SSTS or all-SBML
  coverage, or clear the BNG2 trajectory mismatches above. BNG2 Atomizer
  remains incomplete and has not been benchmarked against all SBML.

## Event-target parameter initial assignments — 2026-09-28

- [x] Extended modern BNG3 parsing and writing for a model parameter with an
  SBML initial assignment that is later changed by an event. The parser stores
  the resolved time-zero value on the parameter; the writer keeps it mutable
  and emits no fixed assignment function with the same name. Unresolved values
  receive a dropped-semantics diagnostic.
- [x] Regression starts with declared `p=4`, initial assignment `p=2`, and an
  event changing `p` to `3`. It asserts BNGL emits the correct initial value
  and scheduled update, then compares BNG3 and libRoadRunner trajectories at
  `t_end=2`. Maximum absolute error was `5.72e-8` away from the event boundary;
  acceptance bound is `1e-7` for the default BNG3 solver tolerance.
- [x] After this change, the full Python suite passed: 686 passed, 28 skipped,
  with 1,380 existing deprecation warnings. Ruff, Black (`--target-version
  py39`), and `git diff --check` passed.
- [x] Seven selected SSTS cases (`01698`–`01700`, `01754`–`01757`) passed
  individual conversion, round-trip, native-reader, and case status gates at
  `t_end=10`. Each contains event-assigned initially assigned parameter `P1`,
  but each has zero observables; these reports therefore provide no numerical
  trajectory comparison. The one-case partial-run aggregate Core flag remains
  false. Manifest `/private/tmp/bng3-event-parameter-cohort.json`, SHA-256
  `171fa16b41f7595d4887fc628ab2a625c69595815cdb5f2c60b6749e65383236`.
- [ ] This is a synthetic trajectory regression plus seven selected import
  cases. It is not full SSTS or all-SBML coverage. No BNG2 code was changed;
  the legacy BNG2 Atomizer remains incomplete and has not been benchmarked
  against all SBML.

## Periodic variable-stoichiometry event thresholds — 2026-09-28

- [x] The modern Atomizer resolves an event-updated species-reference symbol's
  initial value from its uniquely identified numeric coefficient, then proves
  an absolute species threshold inactive across exact periodic parameter
  updates when its reaction-derived derivative stays piecewise constant. The
  proof rejects duplicate or rule-controlled reference IDs, MathML
  stoichiometry, algebraic rules, FBC, changing target species, fast or
  conversion-factor reactions, and changing compartment volumes.
- [x] Regression covers the positive zero-net-flux case and a negative case
  where another event changes the species. Focused modern Atomizer event and
  SBML parity tests passed: 182 passed. Ruff, Black (`--target-version py39`),
  and `git diff --check` passed.
- [x] At exact BNG3 commit `dc05e81cf93db94cc02c2a12ce58d902796b040f`, pinned
  SSTS cases `semantic/01626` and `semantic/01627` passed isolated conversion,
  round-trip, native-reader, and BNG3/libRoadRunner simulation comparisons at
  `t_end=1` and `t_end=100`. All four selected reports have clean tracked-tree
  provenance. `01626` compared four observables with maximum absolute error
  `3.55e-14` at `t_end=100`; `01627` compared five with the same maximum.
  Each invocation selected one case, so its aggregate Core-gate flag remains
  false. Reports and SHA-256 digests:
  - `01626`, `t_end=1`: `/private/tmp/bng3-ssts-01626-dc05e81-t1.json`,
    `cd7b0712dc4e9a8b55b63e63788c0b3224cb28f9f70ee592c3f336dd08c87409`.
  - `01626`, `t_end=100`: `/private/tmp/bng3-ssts-01626-dc05e81-t100.json`,
    `90a9ed64fba1c1afd8e4dc7078a91646fb6c287b683debbf83f018f95e5bc748`.
  - `01627`, `t_end=1`: `/private/tmp/bng3-ssts-01627-dc05e81-t1.json`,
    `436e542a6d0a7a93d942e1abe1d7f19484bfa95a6767d055e135a724c28a0e52`.
  - `01627`, `t_end=100`: `/private/tmp/bng3-ssts-01627-dc05e81-t100.json`,
    `3b178eea01c42978842a1fd5cf9b769a6ba8a76a5d11088c4281d993408c263c`.
- [ ] This selected modern-BNG3 cohort is not a full SSTS or all-SBML
  benchmark. It does not benchmark the legacy BNG2 Atomizer, which remains
  incomplete and has not been benchmarked against all SBML. Wider cross-engine
  coverage remains open.

## Cross-engine network check for periodic stoichiometry cases — 2026-09-28

- [x] Ran the existing cross-engine benchmark on `semantic/01626` and
  `semantic/01627`, with three repeats in flat and Atomized modes. Modern BNG3
  converted all 12 attempts and generated networks in both BNG3 and Perl BNG2
  for all 12. Network structure matched 12/12; strict normalized rate
  expressions matched 6/12. All six `01626` BNG2 comparisons were structurally
  equal but failed strict rates because BNG2 retained the symbolic zero-flux
  expression while BNG3's network simplified it to zero. `01627` matched
  structure and rates in all six comparisons.
- [x] PyBioNetGen legacy Atomizer produced BNGL for all 12 attempts. For
  `01627`, BNG3 and BNG2 generated networks and matched structure and rates in
  all six comparisons. For `01626`, neither engine generated networks from the
  six legacy outputs: flat output referenced undefined `Q` and `R`, and
  Atomized output also contained unresolved `fRate0` expressions.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-stoich-events-9ae7323.json`,
  SHA-256 `3540386e106d904269e708aaa30c89590d3181f406c085cd73f70f47dd7e6c48`.
  It records BNG3 `9ae7323`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`.
  Tracked source trees were clean; the report's dirty flags reflect the
  preserved untracked BNG3 offline bundle and PyBioNetGen `examples/` directory.
- [ ] This is a two-case selected interoperability benchmark. It does not
  measure trajectory parity across engines or establish all-SBML coverage.
  The legacy Atomizer remains incomplete and has not been benchmarked against
  all SBML. Broader BNG2, NFsim, PyBioNetGen, and BioModels comparisons remain
  open.

## Two-step first-order state-event cohort — 2026-09-28

- [x] Added exact scheduled-event lowering for a narrow deterministic system:
  an irreversible two-step first-order chain, with one event that triggers on
  the terminal species and assigns that species a constant. The matcher accepts
  a single derived assignment rule when it is either the chain's conserved pool
  or a positive scalar alias used as the second reaction's modifier. Delayed,
  prioritized, stochastic, and other chain/event forms remain unsupported.
- [x] The focused Atomizer event and SBML parity tests passed: 174 passed.
  Black, Ruff, and `git diff --check` passed.
- [x] Pinned SBML Test Suite cases `semantic/00661` and `semantic/00662` each
  passed the isolated round-trip gate (one selected case per run). These partial
  reports intentionally do not pass the aggregate Core gate:
  `/private/tmp/bng3-ssts-00661-after-chain.json` (SHA-256
  `14179dde95662aad97735a498d525f101676a795c8ba37f75da062cb746f4338`) and
  `/private/tmp/bng3-ssts-00662-after-chain.json` (SHA-256
  `d22973ba26b603a8c02e29bdad0c201612ab677927dab3893420816c4e7c0cf4`).
- [x] For `00661`, BNG3 execution after Atomization matched the pinned SSTS
  reference CSV at `t=10`: absolute errors were `1.68e-8` for `X0`, `1.82e-8`
  for `X1`, `2.07e-8` for `T`, and `2.21e-8` for the derived pool `S1`.
  The scheduled threshold crossing was `t=2.77917484418`. Direct
  libRoadRunner execution was unavailable for this model because it rejects its
  algebraic rule; this comparison uses the pinned SSTS result file instead.
- [x] Perl BNG2 2.9.3 also executed the modern BNG3-generated `00661` BNGL,
  including its scheduled `setConcentration` action. At `t=10`, BNG2 and BNG3
  differed by `6.99e-8` for `X0`, `2.93e-8` for `X1`, and `1.94e-8` for `T`.
  This checks BNG2 engine execution on one BNG3 conversion; it does not test the
  legacy BNG2 Atomizer.
- [ ] This is two selected modern-BNG3 cases, not complete SSTS or
  cross-engine coverage. BNG2 Atomizer remains incomplete and has not been
  benchmarked against all SBML. The full suite, broader trajectory comparisons,
  NFsim, and curated BioModels validation remain open; the user's BioModels run
  remains stopped.

## Expanded SBML Test Suite Atomizer network benchmark — 2026-09-28

- [x] Extended the official SSTS cross-engine sample with eight additional
  supported semantic cases: `00002`, `00224`, `00336`, `00565`, `00801`,
  `01038`, `01100`, and `01638`. Ran three repeats in flat and Atomized modes
  using modern BNG3 and the independent PyBioNetGen legacy Atomizer; each
  generated BNGL was sent to BNG3 and Perl BNG2 2.9.3 for network comparison.
- [x] Modern BNG3 converted all 48 samples and generated all 48 BNG3 networks.
  BNG2 generated 42/48 networks; all 42 matched structure, while 30/42 also
  matched strict normalized rate expressions. BNG2 rejected `00224` because
  its compartment has `spatialDimension=1`.
- [x] The legacy Atomizer converted 36/48 samples. Both engines generated
  networks for 30/48 samples; all 30 had structural and rate parity. Conversion
  failures affected `00565` and `01100`; legacy Atomized output for `00801`
  and `01638` retained unresolved `fRate0` expressions. The benchmark isolated
  the PyBioNetGen import from the globally installed editable BNG3 package and
  records the verified legacy module path.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-additional-8-637f5ac-isolated.json`,
  SHA-256 `9b175ba3456af3d47b4aea334362a081dbac5184b69c97f01dd406e5c03b1541`;
  BNG3 head `637f5ac`, BNG2 head `8726b30`, and PyBioNetGen head `43b09a5`.
  This measures network structure and rate expressions, not trajectories.
  Legacy BNG2/PyBioNetGen Atomizer remains incomplete and was tested on these
  eight SSTS cases only; it was not benchmarked against all SBML or the full
  SBML Test Suite. The larger cross-engine intersection remains open.

## Additional supported SSTS Atomizer cross-engine sample — 2026-09-28

- [x] Extended the selected SSTS Atomizer network benchmark with eight more
  cases: `00003`, `00010`, `00018`, `00025`, `00034`, `00048`, `00057`, and
  `00076`. Each source case is in the current full BNG3/libRoadRunner passing
  set. Ran three repeats in flat and Atomized modes with modern BNG3 and the
  independent PyBioNetGen legacy Atomizer; each output was sent to BNG3 and
  Perl BNG2 2.9.3 for network comparison.
- [x] Modern BNG3 converted and generated networks for all 48 samples; all 48
  BNG2 comparisons matched structure, and 42/48 also passed the strict rate
  comparison. All six strict-rate mismatches are from `00076`'s generated
  binding rate expression; structure remains equal.
- [x] PyBioNetGen legacy Atomizer converted all 48 samples. Both BNG3 and BNG2
  generated networks for 42/48; all 42 matched structure and 36/42 passed
  strict rates. Both network engines rejected the six `00048` attempts because
  the legacy Atomizer emitted an undefined `nan` parameter. The six `00076`
  strict-rate mismatches have equal structure and differ only in the binding
  rate value (`107.14285714275` versus `107.142855`).
- [x] Report `/private/tmp/bng3-cross-engine-ssts-extended-8-20260928.json`,
  SHA-256 `6ae0a642b8ef21ca33036410cc2124e2a90cc676b806a13e3f2548b1233cff68`.
  It records BNG3 `23822c6`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`.
  The report marks BNG3 and PyBioNetGen checkouts dirty only due to preserved
  untracked `bng3-offline-bundle/` and `examples/`; both tracked-diff hashes
  are empty.
  This is selected-case network and rate evidence; it does not measure
  trajectories, cover the complete supported SSTS intersection, or validate
  Atomizer support against all SBML. BNG2 Atomizer remains incomplete and has
  not been benchmarked against all SBML. NFsim trajectory comparison and
  curated BioModels validation remain open; the user's BioModels run remains
  stopped.

## SSTS event and variable-stoichiometry cross-engine sample — 2026-09-28

- [x] Compared eight more current BNG3/libRoadRunner-supported records:
  `00350`, `00353`, `00366`, `00368`, `00972`, `00991`, `01444`, and `01445`.
  The benchmark used three repeats in flat and Atomized modes with modern BNG3
  and the independent PyBioNetGen legacy Atomizer, then compared BNG3 and BNG2
  generated networks.
- [x] Modern BNG3 converted all 48 samples and generated all 48 BNG3 networks.
  BNG2 generated 36/48 networks; every generated network matched structure,
  and 30/36 passed strict rate comparison. BNG2 rejected the 12 `01444` and
  `01445` samples because generated function `A1_sr` collides with a parameter.
  All six `00972` strict-rate differences preserve structure and differ only
  in formatting of equivalent `if` expressions.
- [x] PyBioNetGen legacy Atomizer converted 42/48 samples. Both network engines
  generated networks for 36/48; all 36 matched both structure and strict
  rates. Six `00368` legacy outputs contain undefined `nan` and fail in both
  engines; six Atomized conversions for `01444` and `01445` failed in the
  legacy Atomizer.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-event-stoich-8-20260928.json`,
  SHA-256 `e4f9b93068335896c0d7fe8dc24371e0d833e4d0de39073350d022c890ec11df`.
  It records BNG3 `ffa1112`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`.
  This sample adds network and rate evidence only. It does not measure
  trajectories or establish all-SBML coverage. BNG2 Atomizer remains
  incomplete and has not been benchmarked against all SBML. The attempted
  broader batch including `01561` was interrupted during BNG2 network
  generation and produced no aggregate report; a separate bounded run for
  that case is recorded below.
  NFsim trajectory comparison and curated BioModels validation remain open;
  the user's BioModels run remains stopped.

## Bounded cross-engine check for large SSTS case `01561` — 2026-09-28

- [x] Ran flat mode for three repeats with a 30-second timeout per network
  generation against `semantic/01561`, a current BNG3/libRoadRunner passing
  case with 38 species and 1 reaction.
- [x] Modern BNG3 Atomizer converted all three times and generated BNG3
  networks all three times. Perl BNG2 timed out on all three modern outputs
  at the 30-second cap.
- [x] PyBioNetGen legacy Atomizer converted all three times; BNG3 and BNG2
  generated networks on all three outputs, with structure and strict rate
  comparisons passing all three times.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-01561-bounded-20260928.json`,
  SHA-256 `f58942c64a01b7f5f301049bfc2494834187f2d562f5d0bab2792d5843127775`.
  This covers one case, flat mode, and three repeats. It does not establish
  general runtime behavior or BNG2 Atomizer completeness; that remains
  incomplete and unbenchmarked against all SBML. The atomized mode and a larger
  cohort remain open.

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

## Bounded assignment-rule delay aliases — 2026-09-27

- [x] Delay lowering now follows a single acyclic assignment-rule alias when
  its value is provably constant for the complete requested simulation
  horizon. Affine-in-time conditions use exact rational endpoint checks;
  other event-controlled values, initial-assignment targets, cycles, and
  changing lag values remain unsupported. A narrow single fixed-time
  event-controlled lag is covered in the following section.
- [x] A focused regression grounded in `semantic/00985` confirms the nested
  delay reduces at `t_end=1` when the lag is zero throughout the interval, and
  remains a delay at `t_end=2` when the lag changes. The full Python suite
  passes: `637 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] The official one-case run passes `semantic/00985` conversion,
  round-trip, native-reader, and BNG3/libRoadRunner comparison. Four
  observables match across 11 samples with zero maximum absolute difference.
  This is a partial report, not a full-suite result; SBML Test Suite reference
  conformance was not run. Report
  `/private/tmp/bng3-delay-alias-00985-final2.json`, SHA-256
  `e868fed657b220957f0a48131007a183d7ec835a95aacb2228373d27d7731be5`.
- [ ] No full SBML Test Suite or curated BioModels aggregate was rerun for
  this one-case change. Later full SBML Suite and BioModels refreshes are
  recorded below; the BioModels rerun had no status changes against its prior
  full report. The cached BioModels
  screen found 16 delay calls and
  no direct assignment-rule-symbol lag among 1,084 primary XML files; no
  curated BioModels gain is claimed. Aggregate reports below remain based on
  source `a0ff898`.

## Single fixed-time event-controlled delay lag — 2026-09-27

- [x] Delay lowering now handles a nonnegative lag parameter that changes
  once through a sole `geq(time, constant)` event with one constant-valued
  assignment, when the delayed state has a proven affine trajectory. It emits
  a piecewise expression across the event boundary and preserves the initial
  history before the delayed time reaches zero. Multiple events, priorities,
  delayed events, nonconstant assignments, non-affine states, and other lag
  controls remain unsupported. Assignment-rule references preserve dynamic
  rate-rule values through their generated amount observables.
- [x] The focused `semantic/00984` regression verifies both sides of the
  event transition at `t_end=1` and the post-history branch at `t_end=2`. The
  official one-case reports pass conversion, round-trip, native-reader, and
  BNG3/libRoadRunner comparison. At `t_end=1`, 2 observables match across 11
  samples with zero maximum absolute difference. At `t_end=2`, 2 observables
  match across 21 samples with maximum difference `8.88e-16`. Reports:
  `/private/tmp/bng3-delay-event-lag-00984-t1-final.json` (SHA-256
  `c4ee31b428ae6b012b28af936c5ea42ef79c482dee7abdbc4b04173f1cc404b8`) and
  `/private/tmp/bng3-delay-event-lag-00984-t2-final.json` (SHA-256
  `dce2514cc327601c48bd9aced456965ff2bd11ce1f2d5e693cd8882b6a585a16`).
  Both are one-case partial reports; reference-result conformance was not run.
- [x] Full Python suite: `638 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass. The cached BioModels screen parsed 1,084 primary
  XML files (9 parse errors), found 16 delay calls and no direct lag symbol
  controlled by an event. No curated BioModels gain is claimed. The full SBML
  Suite was refreshed later at `be5bdcf`; a later full BioModels rerun showed
  no per-record status changes against its prior aggregate.

## Event-controlled deterministic species-reference stoichiometry — 2026-09-27

- [x] A variable species-reference expression controlled by a static
  assignment rule can supply the pre-event stoichiometry for a state-trigger
  trajectory when the current event is its only future controller. Cycles,
  multiple controllers, and prior event control remain unsupported.
- [x] Focused regression covers `semantic/01106`; the official case passes
  conversion, round-trip, native reader, and libRoadRunner comparison at
  `t_end=1.5` (3 observables, maximum absolute difference
  `4.44e-16`). Full Python suite: `626 passed, 28 skipped`.
- [x] Full pinned SBML Test Suite: `1,659 passed, 264 unsupported, 0 failed,
  0 timed out`; only `semantic/01106` gained against the preceding full report,
  with no regressions. Report `/private/tmp/bng3-variable-stoich-full-sbml.json`,
  SHA-256 `68e3ad3008dc7ce765257e29b580a87c3751c906d65821cacc5d1f7233984d0e`.
- [x] The later full curated BioModels rerun includes this stoichiometry
  change; its counts, status comparison, and report digest are recorded in the
  following event-batch section. No pass gain is attributed specifically to
  this one-case change.

## Quadratic state events in independent reaction components — 2026-09-27

- [x] Rank-one trajectory analysis now closes the stoichiometric component
  containing the trigger coordinate. Unrelated dynamic components no longer
  block an exact trigger trajectory; kinetic dependence on an external dynamic
  species still fails closed. State snapshots contain only the solved
  component and non-dynamic species.
- [x] Focused tests cover independent reversible components, delayed events,
  reversed reaction orientation, trigger-time snapshots, kinetic coupling that
  must stay unsupported, and SSA actions that must not use deterministic
  no-fire proofs. Stochastic SBML Test Suite cases now request SSA during event
  translation; `stochastic/00033` remains unsupported because jump-trigger
  scheduling is not implemented.
- [x] Official semantic cases `00846`, `00849`, `01046`, and `01049` pass
  conversion, round-trip, native-reader, and BNG3/libRoadRunner comparison at
  `t_end=5` with 50 steps. Each compares 8 observables; maximum absolute
  difference is `4.84e-12`. SBML Test Suite reference-result conformance was
  not run.
- [x] Full pinned SBML Test Suite at `t_end=1`, 10 steps: `1,623 passed, 300
  unsupported, 0 failed, 0 timed out`. Five cases gained against the prior
  report: `semantic/00367`, `00846`, `00849`, `01046`, and `01049`; the
  `00367` gain reflects the earlier horizon-proof change. Fifty-five cases
  previously counted as passed are now unsupported because stochastic
  categories use SSA and state-triggered events need jump-time semantics:
  `stochastic/00040`-`00068`, `00073`-`00076`, and `00079`-`00100`. This is a
  validation-method change, so the total is not directly comparable with the
  previous ODE-selected report. There are no failures or timeouts; the report's
  supported surface passes. Report
  `/private/tmp/bng3-independent-components-full-sbml.json`, SHA-256
  `29076a828262a0f1aff0cd8c05bc621321f120cc4b06bbe046a04981d4728bce`.
- [x] Full Python suite: `636 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full offline curated BioModels both-mode run on source `a0ff898`, using
  the retained cache and matched `t_end=1`, 10-step, 60-second timeout
  configuration: `792/1,083` SBML passed, 109 unsupported, 5 failed, and 177
  timed out. The prior report had 794 passes, 109 unsupported, 6 failed, and
  174 timeouts. No record changed between pass and unsupported; the three
  status changes were `BIOMD0000000579` and `BIOMD0000000637` (pass to
  timeout), and `BIOMD0000000081` (failure to timeout). Isolated retries passed
  `BIOMD0000000637`, reproduced the worker crash for `BIOMD0000000081`, and
  passed `BIOMD0000000579` with a 120-second timeout after its 60-second
  timeout. `BIOMD0000000579` has no SBML events. This supports timeout
  variance, not a measured BioModels feature gain. The report remains
  incomplete: `core_passed=false` and `supported_surface_passed=false`. Report
  `/private/tmp/bng3-independent-components-biomodels-both.json`, SHA-256
  `d2b88728d842b3d443783b11d8f546013d91ca94421865c1b40ee6d477487d03`.

## Quadratic event proofs with rules outside the trigger component — 2026-09-27

- [x] The rank-one event resolver now allows assignment and rate rules when
  they do not target the active trigger species or its compartment, and are
  not referenced by the event trigger or an active reaction rate. Initial
  assignments, algebraic rules, active-component rule targets, and competing
  assigned events remain fail-closed. Focused regressions confirm that a rule
  on the trigger species or a rule-controlled trigger threshold keeps the
  event untranslated.
- [x] Official `semantic/00652`-`00654` records pass individually at
  `t_end=1`, 10 steps. Each passes conversion, round-trip, native-reader, and
  BNG3/libRoadRunner comparison for seven observables; maximum absolute
  difference is `1.67e-11`. The horizon proof establishes no event action is
  needed in this interval. `semantic/00652` also passes when its event is
  scheduled at `t_end=2` and `5` (21 and 51 samples, respectively; maxima
  `1.67e-11` and `1.77e-11`). All are partial one-case reports; reference-result
  conformance was not run.
- [x] Full Python suite: `639 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Three-repeat cross-engine benchmark on `semantic/00652` is deterministic
  in flat and atomized modes. Modern BNG3 has BNG2 structural parity in 3/3
  repeats per mode; the rate comparator reports 0/3 because the `S2` rate
  expressions differ by an explicit multiplicative `1` (`1*(...)` versus
  `(...)`). This is recorded as a comparator failure, not a rate-parity pass.
  Legacy PyBioNetGen has structure and rate parity in 3/3 repeats per mode.
  This is network-level evidence, not trajectory parity.
- [x] Full pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`
  at `t_end=1`, 10 steps: `1,637 passed, 286 unsupported, 0 failed, 0 timed
  out`. Comparing exact status IDs with the prior full report
  `/private/tmp/bng3-independent-components-full-sbml.json` (`1,623/300/0/0`)
  gives 14 gains and no regressions: `semantic/00647`, `00650`, `00652`-`00657`,
  `00731`, `00751`, `00753`, `00984`, `00985`, and `01095`. The supported
  surface passes; the aggregate gate remains open because unsupported models
  remain. This refresh covers cumulative changes since `a0ff898`, including
  the two earlier delay-lowering changes; the 14 gains are not attributed only
  to rule isolation. Report
  `/private/tmp/bng3-rules-outside-trigger-component-full-sbml.json`,
  SHA-256 `9cab759cdb6f1cd62e71423a51bb81775e4fbe5029e7c9fb98abcd00b39f0875`.
- [x] Full offline curated BioModels run at the same `t_end=1`, 10-step,
  60-second-per-model settings, with both Atomizer modes and all 1,096 curated
  records: `792/1,083` SBML-path records passed, 109 were unsupported, 5
  failed, and 177 timed out. The inventory matches the manifest. Exact status
  comparison with the prior full report
  `/private/tmp/bng3-independent-components-biomodels-both.json` found no
  changed records among all 1,096 models. The report has
  `core_passed=false` and `supported_surface_passed=false`. Report
  `/private/tmp/bng3-rules-outside-trigger-component-biomodels-both.json`,
  SHA-256 `c1ed08fb093b77aacda341fd17a5b457d1bbc90617d7f716ae1cbc14a5ba6678`.

Targeted report SHA-256 values: `00652` at `t_end=1`,
`6de1084d7b716f2669c650b5b5e8e86fb978f85a84f38dfcb0df32b241282a9b`;
`00653`, `7ee907a4e8ea5e6ac2333a8cba4f334ac2e1a995ab3dae944c1bb76b52d89563`;
`00654`, `fa3ee36161ba65dcc09f7729e70bcdfb7854f6c2e5e300017b50e1b4fadd4430`;
`00652` at `t_end=2`, `135a9f71b83df0dc12a39011b533e8b0e5a8ac85cbe4f2cb75f5a5f8a7d55d15`;
at `t_end=5`, `536a2d80a85df33498b175f5f87b138a62ca6b24ccd102b89f20386386172c95`.
The longer-horizon event reports at `t_end=5` are `00647`,
`a208ffcc900ca1e9a924604cfad7f29c45cb36335405f18245cbfc466a5cdde5`;
`00650`, `a511c0b3341fe2144f26d13a23026355af09aecebd8938604b571c9d800db517`;
`00655`, `0563896da530e6ca7bb6ef252334294d00617a1e8657566c2a18326bb131fc2e`;
`00656`, `01294d5b2559617d8919989b161b50332b31d5d604f9ebae9fecee589b016092`;
and `00657`, `bf22b5d41c61fc7f10063fb462104b1ff2a2b8b957f98724bd7227e6cb81d775`.
Cases `00731`, `00751`, `00753`, and `01095` also pass at `t_end=5`, each
with eight observables across 51 samples; maximum differences range from
`9.52e-12` to `1.32e-10`. Their report hashes are `00731`,
`e6b1e3b83e2d5a43f7c72e492d50c157aea793f70f0e958a144629aa88d03c34`;
`00751`, `7f0dac1ca23c94c1cb91416b60f595bf8e1f15ae98a45569d33286fb9fead4e7`;
`00753`, `08cfec126e9fbe0074244094165b6ce56235378733c323a58183ae256f81c985`;
and `01095`, `e70a8e1a25f23c3919cb706da3b2556ac47c18acf39c0be28b4b85cdb0b5c28c`.
Cross-engine report `/private/tmp/bng3-atomizer-cross-engine-event-rules-00652-20260927.json`,
SHA-256 `517057f7cd8f9cb40a22177787d21f2663ce32efa75922e49472f7fa0a4aedad`.
Its recorded BNG3 writer hash `fcee307ad3cc452fd41493c93742daacdbdb67d1139a4d67cf1a1f8a4f4f7d28`
matches the writer in `be5bdcf`; the benchmark metadata records the prior base
HEAD `a9a5bc3` with the implementation as a dirty tracked diff.

## Remaining unsupported SBML Test Suite triage — prior ODE-selected baseline

- [x] Prior full pinned SBML Test Suite after the quadratic recurrence batch,
  before correcting stochastic-category validation to request SSA:
  `1,673 passed, 250 unsupported, 0 failed, 0 timed out` (`t_end=1`, 10
  samples). Fourteen cases changed from unsupported to passed, with no status
  regressions: `00350`, `00353`, `00358`, `00359`, `00366`, `00368`, `00371`,
  `00381`-`00383`, `00395`, `00399`, `00745`, and `00748`. Report
  `/private/tmp/bng3-quadratic-reentrant-full-sbml.json`, SHA-256
  `401164dfb6f6696e2d46f3e9378bba315abc60fc33521ef3585507e345beff28`.
- [x] Triage of that prior full report: events affect 147 unsupported models (136
  event-only); fast reactions 35 (33 fast-only); FBC 34 (30 FBC-only); MathML
  22 (18 MathML-only); stoichiometry 16 (5 stoichiometry-only); other edge
  cases 11; algebraic rules 2. Feature counts overlap. Per-model diagnostics,
  conversion/round-trip status, and source paths are in
  `/private/tmp/outputs/01a0d6e3-6845-7d61-9e25-0e70f3884b4d/bng3-unsupported-sbml-triage-2026-09-27.xlsx`.
- [x] After adding exact no-fire horizon proofs, targeted
  `semantic/00367` passes the official validator at `t_end=1`; the current
  full SSA-selected report above includes that pass. Targeted
  `semantic/00374` remains unsupported by current recurrence lowering.
  Historical focused event/parity tests: `135 passed`; full Python suite:
  `631 passed, 28 skipped`; Black, Ruff, and `git diff --check` passed then.
- [x] Conversion-only triage of the original 161 event-affected cases found 151 with
  the same root diagnostic: a state-dependent trigger cannot be lowered to a
  scheduled action. Common test-suite shapes are reversible mass-action
  systems (`S1 + S2 <-> S3`, and `S3 <-> S1 + S2`) whose events can reset a
  trigger species and later cross again. Supporting these models requires
  tracking trigger state and executing re-entrant events during integration;
  deriving one first-crossing time is insufficient.
- [x] A tightly scoped recurrence cohort had 41 event-only cases with one
  relational state trigger, no delay, and no priority. The full-suite gains
  in the prior ODE-selected report establish 14 official passes at the suite's
  `t_end=1`. The later horizon proof made `semantic/00367` pass; the current
  SSA-selected report above also records that pass. `00374` remains unsupported
  in current targeted conversion; earlier `t_end=10` reports are stale and not
  support evidence. `stochastic/00033` still requires stochastic jump-trigger
  semantics. Eight similar cases also have unsupported variable stoichiometry
  or fast reactions.
- [x] FBC accounts for 34 models, all overlapping constraint blockers; these
  are flux-balance/optimization models rather than kinetic time-course models.
  Fast-equilibrium semantics affect 35 models (33 fast-only). MathML gaps
  affect 22, stoichiometry gaps 16, and other edge cases 11; cause totals
  overlap and are not additive.
- [x] After the independent-component event batch, run one full pinned SBML
  Test Suite and compare exact case IDs. Current counts and status changes are
  recorded in the preceding section. Do not rerun the full corpus for
  one- or two-model patches.
- [ ] Next high-yield event work: support more trajectory families and event
  semantics (delayed triggers, priority, trigger-time snapshots, and events
  whose resets cross trigger boundaries) without relying only on exact
  quadratic paths. General solution likely needs event-aware ODE integration.
- [ ] Keep FBC separately scoped: 34 cases require flux constraints/objectives
  and optimization semantics, not kinetic Atomizer conversion. Fast reactions
  need equilibrium/DAE execution; do not silently lower them as ordinary
  reactions. MathML/stoichiometry edge cases should be batched by executable,
  valid semantics; source cases with absent MathML or non-BNGL coefficients
  need explicit compatibility policy.
- [x] Curated BioModels rerun completed after the independent-component event
  batch and was compared against
  `/private/tmp/bng3-conjunction-biomodels-both.json`; counts, changed IDs, and
  isolated timeout retries are recorded above. No BioModels pass gain is
  claimed.

## Affine species-difference event thresholds — 2026-09-26

- [x] Atomizer can schedule a two-species difference threshold when both
  species have independently proven affine trajectories. Trigger-time event
  assignments receive both species values at the crossing; events assigning
  either trigger species remain fail-closed.
- [x] Focused event tests pass (`29 passed`); full Python suite passes
  (`585 passed, 28 skipped`). Black, Ruff, and `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,592 passed, 330 unsupported, 1 failed,
  0 timed out`. Compared with the preceding exact report, no cases gained or
  regressed; `01148` remains the same CVODE internal-step-budget failure.
  Report `/private/tmp/bng3-sbml-affine-difference-full.json`, SHA-256
  `7917fde9b7c37132eca4cd3f54b7ac45c64f8a7a22680a61f881121ab7e82979`.
- [ ] Five initial targeted cases did not gain support because their species
  lack independent affine trajectories; no corpus gain is claimed.
- [ ] Curated BioModels inventory run for this earlier slice was later
  interrupted before a terminal report; no pass/fail conclusion is claimed.
- [ ] Exact-head CI for `0fbf50981b4bd5ffbe75bc6840a62d1f3d13ce9b`:
  cross-tool parity `36280195964` queued, formatting `36280195946` in progress,
  CodeQL `36280195915` queued, CI `36280195874` queued, Lean `36280195870` in
  progress.

## SBML numerical parity for matching nonfinite results — 2026-09-26

- [x] The comparison gate now compares finite samples numerically and requires
  exact pointwise agreement for NaN, positive infinity, and negative infinity
  masks. It no longer rejects a model solely because both engines produce the
  same SBML MathML domain result.
- [x] SBML Test Suite cases `00955` and `01487` now pass. BNG3 and
  libRoadRunner produce identical nonfinite masks for `P4`-`P7`, with finite
  samples compared under the existing model-wide tolerance. No case regressed.
- [x] Full pinned suite: `1,592 passed, 330 unsupported, 1 failed, 0 timed
  out`. Remaining failure is `01148`, CVODE internal step budget exhaustion.
  Report `/private/tmp/bng3-sbml-nonfinite-equivalence.json`, SHA-256
  `7917fde9b7c37132eca4cd3f54b7ac45c64f8a7a22680a61f881121ab7e82979`.
- [x] Full Python suite: `584 passed, 28 skipped`; the focused validation
  contracts pass (`8 passed`); Black, Ruff, and `git diff --check` pass.
- [x] On the immediately preceding pushed head `c588e9ef`, cross-tool parity,
  Lean semantic kernel, CodeQL, and formatting passed; the CI matrix remains
  queued. The latest exact-head checks are listed above.

## Quadratic species-difference event thresholds — 2026-09-26

- [x] A trigger comparing two species can use the exact rank-one quadratic
  trajectory of their difference when both species share the same reaction
  coordinate and the resulting ODE remains autonomous quadratic. The resolver
  rejects event assignments that alter either component or read either
  component at a snapshot where the supported lowering cannot preserve it.
  A fixed or boundary component is allowed as the non-coordinate side; the
  dynamic component supplies the reaction coordinate. At a proven quadratic
  crossing, trigger-time assignments can read any species value mapped onto
  that same rank-one coordinate.
- [x] Eight SBML Test Suite cases gained relative to the earlier
  `1,582 passed / 338 unsupported / 3 failed` working report:
  `00351`, `00384`, `00408`, `00429`, `00441`, `00746`, `00766`, and `00885`.
  No case regressed against that report. Current pinned suite: `1,590 passed,
  330 unsupported, 3 failed, 0 timed out`; the three CVODE failures are
  `00955`, `01148`, and `01487`. Report
  `/private/tmp/bng3-sbml-difference-snapshot-working.json`, SHA-256
  `44cdb83bf4bbc0b2bc43c6104131d013e4b31ae8964ed5eb101fa5360d1a4b42`.
- [x] All eight gains pass BNG3/libRoadRunner 2.10.0 comparisons over eight
  observables each (10-unit horizon, 100 steps). Maximum absolute error is
  `4.72e-8`; maximum scaled error is `0.0352`.
- [x] Composite-trigger full Python suite: `581 passed, 28 skipped`; Black, Ruff, and
  `git diff --check` pass.
- [x] Scalar quadratic triggers now expose the same rank-one species snapshot
  to trigger-time assignments. The updated full Python suite passes
  `582 passed, 28 skipped`; all 1,923 SBML cases retain their prior status
  (`1,590 passed, 330 unsupported, 3 failed, 0 timed out`), with no gains or
  regressions. The full report hash remains
  `44cdb83bf4bbc0b2bc43c6104131d013e4b31ae8964ed5eb101fa5360d1a4b42`.
- [x] Cached BioModels screen parsed 6,759 XML files (9 parse errors), found
  no two-species event-threshold triggers, and identified three scalar-event
  assignment candidates: `BIOMD0000000144`, `0195`, and `0196`. Targeted
  round-trip attempts leave all three unsupported for other event/path limits;
  no curated gain is claimed and the full inventory was not rerun.
- [ ] Exact-head CI for `2ddb80dc5bfb1203260923f42c4614e837d0cfbc` is queued:
  CI `36278416862`, cross-tool parity `36278416900`, CodeQL `36278416850`.

## Scalar quadratic event threshold crossing — 2026-09-26

- [x] A rank-one reaction network with no rules or initial assignments can
  resolve a single species trajectory when its kinetic laws reduce to an
  autonomous quadratic ODE `dx/dt = a*x^2 + b*x + c`. The exact first
  threshold crossing is scheduled for simple state triggers. Variable
  stoichiometry, conversion factors, dynamic compartments, unsupported kinetic
  math, and nonpersistent delayed triggers fail closed.
- [x] Full Python suite: `578 passed, 28 skipped`; Black, Ruff, and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`:
  `1,589 passed, 334 unsupported, 0 failed, 0 timed out`. Compared per case
  with the previous full report, 31 cases gained and none regressed:
  `00348`, `00354`, `00360`-`00362`, `00369`, `00372`, `00375`-`00377`,
  `00386`, `00389`, `00405`, `00411`, `00417`-`00419`, `00426`, `00432`-
  `00434`, `00443`, `00446`, `00743`, `00763`, `00845`, `00848`, `00883`,
  `00886`, `01045`, and `01048`. Report
  `/private/tmp/bng3-sbml-riccati-full.json`, SHA-256
  `bcb141eb61f9533acc525dc578fdf0cc055d9dfe56281d56127c493a07c83dd8`.
- [x] All 31 gains pass 10-unit/100-step BNG3 vs libRoadRunner 2.10.0
  comparisons across 184 observables; maximum scaled error is `0.0476`.
- [x] Cached BioModels scan parsed 6,759 XML files (9 parse errors) and found
  no single-event, rank-one state-threshold candidates. No curated gain is
  claimed; the complete curated inventory remains open.
- [x] Hosted Python logs showed libSBML crashes parsing an inline comp parent
  and an external child file. The XML-only fallback now handles one simple
  inline model and one source-relative external child, each limited to core
  compartments, species, parameters, and reactions. Complex hierarchies remain
  on the guarded general libSBML path. Comp tests pass (`4 passed`), including
  an assertion that the supported external path never calls
  `libsbml.readSBMLFromFile`.

## SBML event comparison aliases — 2026-09-26

- [x] Exact affine threshold analysis accepts SBML's comparison names
  `lessThan`, `greaterThan`, and inclusive forms in addition to short aliases.
  This unlocks `00355`, `00412`, `01701`, and `01702`.
- [x] All four cases pass 10-unit/100-step libRoadRunner 2.10.0 comparisons
  across 14 observables; maximum absolute error `3.36e-12`.
- [x] Full Python suite: `579 passed, 28 skipped`; Black, Ruff, and
  `git diff --check` pass.
- [ ] Full pinned-suite result is not a clean gate: `1,582 passed, 338
  unsupported, 3 failed, 0 timed out`. Report
  `/private/tmp/bng3-sbml-alias-final.json`. Three cases fail CVODE in
  `00955`, `01148`, and `01487`; seven earlier delay-history cases became
  unsupported. Continue triage before claiming zero regressions.
- [ ] Exact-head hosted CI for external comp flattening remains pending push.
  The prior `107da3c` run still segfaulted in the external child file parser;
  the supported path now avoids that call and needs a fresh hosted check.

## Empty comp declarations and fixed-time-gated event thresholds — 2026-09-26

- [x] A comp namespace declaration with no comp elements now bypasses libSBML
  conversion unchanged. The original package declaration remains available to
  report as informational metadata. Regression test checks the no-op path.
- [x] Exact affine state threshold lowering can handle one monotone state
  threshold conjoined with fixed time bounds and static predicates, provided
  the initial state is outside the trigger and the state crossing falls inside
  the time window. Thresholds outside the window remain unsupported. A focused
  fixture verifies both the accepted crossing and fail-closed late gate.
- [x] Full Python suite: `580 passed, 28 skipped`; Black, Ruff, and
  `git diff --check` pass.
- [ ] The full pinned SBML report remains `1,582 passed, 338 unsupported, 3
  failed, 0 timed out`; no new official gain came from the gated-threshold
  slice. `00935` remains unsupported because it has three same-trigger events
  with conflicting assignments and priorities. Report
  `/private/tmp/bng3-sbml-final-60efb85-working.json`, SHA-256
  `ea15c9b2e3038a6bd9146ebb6de19e70767059b9760ed00cf153d58415f50bb1`.
- [ ] Hosted Ubuntu Python CI at `60efb85` passed all four comp-specific tests,
  then segfaulted in libSBML conversion of the empty declared comp package.
  The no-op fast path fixes that case locally; next exact-head CI is pending.

## Static event assignment histories — 2026-09-26

- [x] For models with no reactions, rules, or initial assignments, fixed-time
  events are evaluated in execution-time order. Assignment expressions can
  read a prior parameter, species, or compartment value at the selected SBML
  snapshot: trigger time when `useValuesFromTriggerTime=true`, execution time
  otherwise. Dynamic ordering remains unsupported.
- [x] Full Python suite: `577 passed, 28 skipped`; Black, Ruff, and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`:
  `1,558 passed, 365 unsupported, 0 failed, 0 timed out`. Compared per case
  with the prior full report, seven cases gained and none regressed:
  `00979`, `00980`, `01152`, and `01328`-`01331`. All seven have no comparable
  simulation observables; this is structural round-trip evidence only. Report
  `/private/tmp/bng3-sbml-prior-event-history-full.json`, SHA-256
  `3988764e9238e693307955b88c8b01658fa678b5446e3f49bc399543493ac2ba`.
- [ ] Hosted CI for `da36c91` remains in progress; checks for this slice start
  after its push.

## Constant reaction IDs in event math — 2026-09-26

- [x] Event triggers, delays, priorities, and assignment expressions can fold
  a reaction ID when its kinetic-law rate reduces to a finite constant. Local
  kinetic-law parameters and compile-time constants are allowed; a mutable
  parameter is allowed only when this event alone assigns it and no rule,
  initial assignment, or other event controls it. Dynamic/species-dependent
  fluxes remain unsupported.
- [x] Full Python suite: `576 passed, 28 skipped`; Black, Ruff, and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`:
  `1,551 passed, 372 unsupported, 0 failed, 0 timed out`. Compared per case
  with the prior full report, 10 cases gained and none regressed:
  `01227`, `01228`, `01230`, and `01303`-`01305`, `01346`-`01349`. The
  validator exits nonzero because the remaining unsupported cases keep its
  aggregate core gate red. Report `/private/tmp/bng3-sbml-event-reaction-final.json`,
  SHA-256 `8dcd4ce858349252964cdbbf51f395aa8d3800e0cb9ffb766b43b2e8e3da6e42`.
- [x] Targeted 10-unit/100-step comparisons pass against libRoadRunner 2.10.0
  for all 10 gains. Eight models have two observables each; two models have no
  comparable observables. Maximum absolute error among compared observables is
  `3.91e-14`.
- [x] Cached curated BioModels screen parsed 6,759 XML files (9 parse errors)
  and found no event expressions referencing reaction IDs. No curated-model
  gain is claimed; the full curated inventory remains unrefreshed.
- [ ] Hosted CI remains unverified; GitHub CLI could not connect to
  `api.github.com` on the prior push.

## RateOf histories and dynamic event delays — 2026-09-26

- [x] Event-value folding evaluates `rateOf(x)` from a proven affine,
  exponential, or square-linear trajectory at the SBML trigger or execution
  time. Exact nonnegative delays derived from those histories are scheduled.
  Two same-trigger delayed events can use dynamic priority only when resolved
  delays match and the dynamic priority is strictly greater than the other
  event's static priority.
- [x] Pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`:
  `1,541 passed, 382 unsupported, 0 failed, 0 timed out`. Compared per case
  with the previous report, five cases gained pass and none regressed:
  `01270`, `01507`, and `01672`-`01674`. Event blockers fell from 285 to 280.
  Full report `/private/tmp/bng3-sbml-rateof-events-full.json`, SHA-256
  `3250bee4f7ea11e97a1a44d3d38424611ef788ad91a623d6507c30f7b88364f4`.
- [x] Targeted 10-unit/100-step comparisons pass against libRoadRunner 2.10.0
  for all five gains, across 3-5 observables each. Maximum absolute error is
  `1.61e-10`, below configured comparison tolerance. Summary
  `/private/tmp/bng3-sbml-rateof-h10-summary.json`, SHA-256
  `aff2338c393e9380fe654bec43a4120cbafa0cd58ebd5446cd5554e61df0ebb7`.
- [x] Full Python suite: `575 passed, 28 skipped` with compiled extension;
  repository-wide Black, Ruff, and `git diff --check` pass.
- [x] Cached curated BioModels screening parsed 6,759 XML files with 9 parse
  errors and found zero identical-trigger two-event models using `rateOf` in
  event delays, priorities, or assignments. No curated gain claimed; full
  curated inventory remains unrefreshed.
- [ ] Hosted CI after the latest push remains unverified; GitHub CLI could not
  connect to `api.github.com`.

## Event-local delayed values and simultaneous priorities — 2026-09-26

- [x] Event-value folding now uses event-local affine trajectories for the
  pre-execution snapshot, so a future assignment by that event does not
  invalidate its own exact delayed value. Dynamic priority is also folded
  from an exact affine state only for two no-delay events with identical
  triggers, one state-dependent priority, and a strictly higher value than
  the other event's static priority. Unsupported ordering cases fail closed.
- [x] Pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`:
  `1,536 passed, 387 unsupported, 0 failed, 0 timed out`. Compared per case
  with the previous report, 11 cases gained pass and none regressed:
  `01267`, `01298`, `01508`, `01509`, `01512`, `01681`-`01683`, and
  `01705`-`01707`. Event blockers fell from 296 to 285. Full report
  `/private/tmp/bng3-sbml-priority-full.json`, SHA-256
  `3231f4a6d1e8259ea91a452fcc7a4832ee7486af1c44450dc366d129269c1525`.
- [x] Targeted 10-unit/100-step comparisons pass against libRoadRunner 2.10.0
  for all 11 gains, across 1-5 observables each. Largest absolute difference
  is `6.51e-11`, below configured comparison tolerance. Summary
  `/private/tmp/bng3-sbml-priority-h10-summary.json`, SHA-256
  `36011f242f6087f43978b0ef9fdc136bd07cb8067c899f054617dfe3335e54ba`.
- [x] Full Python suite: `574 passed, 28 skipped` with compiled extension;
  repository-wide Black, Ruff, and `git diff --check` pass.
- [x] Cached curated BioModels screen parsed 6,759 XML files, with 9 parse
  errors, and found zero two-event identical-trigger priority pairs. Full
  curated inventory was not rerun; previous full inventory remains last
  round-trip/oracle evidence, and no curated gain is claimed.
- [ ] Hosted CI remains unverified: GitHub CLI could not connect to
  `api.github.com` after push.

## Reciprocal-flux threshold events — 2026-09-26

- [x] Exact trigger scheduling now handles a positive concentration whose
  isolated net reaction flux has the form `k/S`, giving
  `S(t)^2 = S(0)^2 + 2*k*t`. Proof rejects nonpositive initial/threshold
  values, variable compartments, variable stoichiometry, conversion factors,
  coupled or controlled species, and unsupported kinetic-law forms.
- [x] Synthetic regression verifies event at `t=1.705` for `S(0)=1`,
  `S'=1/S`, threshold `S>2.1`, and event assignment `k=10`.
- [x] Full Python suite: `573 passed, 28 skipped` with compiled extension.
- [x] Pinned SBML Test Suite `cf38585fac5de8e0e90112febb62851ee2181816`:
  `1,525 passed, 398 unsupported, 0 failed, 0 timed out`; only
  `semantic/00944` gained pass vs prior `1,524/399`; no regressions. Full
  report `/private/tmp/bng3-sbml-reciprocal-full.json`, SHA-256
  `6b3dd84145054f52ed7667c6c8b847122c6f00576b99e90c9479ca29d4b581c9`.
- [x] `semantic/00944` matches libRoadRunner 2.10.0 at 10 units / 100 steps
  across both observables; maximum absolute error `3.56e-15`. Target report
  `/private/tmp/bng3-sbml-reciprocal-00944.json`, SHA-256
  `94a194c7b00a865384bcaf1bfed58ecf55bbef4a23244fdfbb8033fd26911c13`.
- [x] `semantic/00945` and `00947` remain unsupported because event-driven
  compartment changes alter species concentration discontinuously; trajectory
  proof correctly fails closed.
- [x] Cached curated BioModels screening parsed 6,756 XML files with 9 parse
  errors and found zero models with the reciprocal-flux species threshold
  shape. No curated gain is claimed; prior full matched-timeout BioModels
  report remains last full-inventory evidence. A full offline refresh was
  canceled after screening because it was substantially slower and could not
  affect this feature's curated coverage.
- [ ] Hosted checks have not been queried successfully; `gh` could not connect
  to `api.github.com` during this pass.

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

## Amount-based affine event checkpoint — 2026-09-26

- [x] An event assignment syntactically identical to its rate-rule trigger
  target is treated as a no-op for affine trajectory proof, preserving the
  state value and one rising-edge schedule.
- [x] Full Python suite: `570 passed, 28 skipped`.
- [x] Full pinned SBML Test Suite at
  `cf38585fac5de8e0e90112febb62851ee2181816`: `1,518 passed, 405 unsupported,
  0 failed, 0 timed out`. Compared per-case with the prior full report, only
  `semantic/01798` changed from unsupported to passed.
- [x] The gained case matches libRoadRunner 2.10.0 exactly across three
  observables. Report: `/private/tmp/bng3-sbml-identity-event-full.json`,
  SHA-256 `d4e48b75fad1b71f9aba73f26d729952d99eed39a0da112411fd643444d7fc7d`.
- [ ] Curated BioModels inventory not rerun for this slice.
- [x] Formatting workflow failure on `31d4b8a` is fixed: repository-wide
  Black and Ruff pass, and exact-head Formatting patch succeeds on `c9c5a0b`.
- [x] Fixed-seed direct BNG3/native NFsim endpoint parity test was restored
  after the `c9c5a0b` Cross-tool parity run exposed its missing selector
  target. Local run with independent NFsim `c51c7a34128d188189485bd318aeae4d936bcb29`
  passes `1/1`.
- [ ] Hosted Cross-tool parity must be rerun on the corrective commit; hosted
  CI and CodeQL for `c9c5a0b` are still pending.

## Amount-based affine event checkpoint — 2026-09-26

- [x] Rate-rule species with `hasOnlySubstanceUnits=true` resolve exact affine
  event trigger trajectories in amount units.
- [x] Full Python suite: `569 passed, 28 skipped`.
- [x] Full pinned SBML Test Suite at
  `cf38585fac5de8e0e90112febb62851ee2181816`: `1,517 passed, 406 unsupported,
  0 failed, 0 timed out`. Compared per-case with the prior full report, only
  `semantic/01703`, `01704`, `01708`, and `01709` changed from unsupported to
  passed.
- [x] All four gains match libRoadRunner 2.10.0 across two observables;
  maximum absolute difference is `1.78e-15`.
- [x] Report: `/private/tmp/bng3-sbml-amount-affine-events-full.json`, SHA-256
  `877372a20ed07fbfdd8bd2a16085115714b4cc978a3bad0ade184c5393130186`.
- [x] Cached BioModels scan found no amount-based rate-rule species used by an
  event trigger; no curated gain is claimed.

## Affine species-reference event checkpoint — 2026-09-26

- [x] A variable species-reference ID with one constant rate rule now resolves
  as an affine trigger trajectory when its initial stoichiometry and derivative
  are finite and no competing initial assignment or event controls it.
- [x] Full Python suite: `568 passed, 28 skipped`.
- [x] Full pinned SBML Test Suite at
  `cf38585fac5de8e0e90112febb62851ee2181816`: `1,513 passed, 410 unsupported,
  0 failed, 0 timed out`. Compared per-case with the prior full report, only
  `semantic/01717`–`01721` changed from unsupported to passed.
- [x] All five gains match libRoadRunner 2.10.0 across three observables;
  maximum absolute difference is `3.85e-12`.
- [x] Report: `/private/tmp/bng3-sbml-affine-stoich-events-full.json`,
  SHA-256 `2802c1a1fd66d15e0e550b3be71ef590dcd16bb789e52b259c1c007157311054`.
- [x] Cached BioModels XML scan found no rate-ruled species-reference IDs in
  event triggers; no curated BioModels gain is claimed.

## Fixed-delay affine event trigger interval checkpoint — 2026-09-26

- [x] The isolated two-bound trigger `and(gt(delay(S, d), lower),
  lt(delay(S, d), upper))` now lowers when both bounds use the same state and
  nonnegative constant delay and that state has a proven affine trajectory.
  The delay shifts interval entry/exit; nonpersistent scheduled events are
  omitted when canceled at interval end.
- [x] Full Python suite: `567 passed, 28 skipped`; targeted modern Atomizer
  event and SBML parity suites: `75 passed`.
- [x] Full pinned SBML Test Suite at
  `cf38585fac5de8e0e90112febb62851ee2181816`: `1,508 passed, 415 unsupported,
  0 failed, 0 timed out`. Compared per-case with the prior full report, only
  `semantic/01518`, `01519`, and `01520` changed from unsupported to passed.
- [x] All three new cases match libRoadRunner 2.10.0 on their one observable;
  maximum absolute difference is `0` for each.
- [x] Report: `/private/tmp/bng3-sbml-delayed-interval-full.json`, SHA-256
  `aacfee4d80f33e83cb1a7664bc9e11f7ba31dec8b9534674c53f1cb52fdc8851`.
- [ ] Curated BioModels inventory and BNG2/PyBioNetGen/NFsim cross-engine
  benchmarks have not been rerun for this slice.

## Fixed-delay affine event assignment checkpoint — 2026-09-26

- [x] Event assignment folding evaluates finite fixed delays against a proven
  affine/exponential state history at the selected trigger-time or execution-
  time snapshot. Regression coverage is in
  `tests/python/test_modern_atomizer_sbml_parity.py::test_event_assignment_delay_function_uses_affine_state_history`.
- [x] Full Python suite: `566 passed, 28 skipped`; targeted modern Atomizer
  event and SBML parity suites: `74 passed`.
- [x] Full pinned SBML Test Suite at
  `cf38585fac5de8e0e90112febb62851ee2181816`: `1,505 passed, 418 unsupported,
  0 failed, 0 timed out`. Compared per-case with the prior full report, only
  `semantic/01523` and `01524` changed from unsupported to passed.
- [x] Report: `/private/tmp/bng3-sbml-event-delay-affine-full.json`, SHA-256
  `b4efc6b3462a1e48103ccb406f571c938d64dab85e7273b2388c40e3a9fe9f94`.
- [ ] Numerical libRoadRunner parity is not claimed: these two cases have no
  observables. Delayed interval triggers `01518`–`01520` remain unsupported.
- [ ] Curated BioModels inventory and cross-engine benchmarks have not been
  rerun for this slice.

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

## Historical PR #25 final-head audit — 2026-09-28

- [x] Rechecked merged PR #25 at tip `f935272` / merge commit `1ccf76d`. Its
  selected historical issue ports, finite-network `FunctionProduct` handling,
  reverse local-rate binding, and portable MSVC math constants are recorded in
  [`HISTORICAL_ISSUE_PORT.md`](HISTORICAL_ISSUE_PORT.md). Hosted C++ Linux,
  macOS, Windows, ASan, Python 3.9–3.14 platform matrix, CodeQL, full-corpus
  validation, PyBioNetGen API, independent BNG2 network, and independent
  NFsim parity checks all pass. Scheduled NFsim history validation and
  event-guarded wheel, sdist, Docker, and PyPI publication jobs were skipped;
  no release qualification is implied.

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
- [x] Rebuilt the alpha wheel from code commit `e36ba90` and installed it in a
  temporary Python 3.14 environment. The installed package and compiled
  extension imported from that environment, `bionetgen --version` reported
  `3.0.0a1`, and its CLI ran an ODE birth model and wrote the expected samples
  at `t=0`, `0.5`, and `1`. Wheel metadata identifies
  `bionetgen-3.0.0a1-cp314-cp314-macosx_26_0_arm64.whl`, requires Python `>=3.9`,
  and includes the native extension. SHA-256:
  `16c2eb1f549d3d8dae0f5b0272f8bb2a987fc7c27ff01de1b3c15c8259134185`.
  Artifact: `/private/tmp/bng3-pip-current/dist/bionetgen-3.0.0a1-cp314-cp314-macosx_26_0_arm64.whl`.
  This verifies one local platform artifact; cross-platform installed-wheel
  coverage and publication remain open.
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
- [x] Partial metadata audit: the package declares Python `>=3.9`; classifiers
  now include Python 3.14. Isolated source and wheel builds, installed-package
  checks, and the remaining cross-platform gaps are recorded in the
  2026-09-28 artifact audit below. Dependency policy and complete package-data
  coverage still need review.
- [ ] Complete the pyproject metadata audit: supported Python range, dependency
  policy, full package data, and extension contents across the supported
  platform matrix remain under audit.
- [x] The pull-request package-smoke job builds and installs a source
  distribution on the exact head (CI run
  [33449613101](https://github.com/RuleWorld/BNG3/actions/runs/33449613101));
  release-candidate provenance and the complete artifact matrix remain open.
- [ ] Clean isolated wheels build for every supported platform/architecture.
- [ ] Installed-wheel tests cover import, compiled extension loading, API,
  CLI, embedded assets, plotting/data helpers, and representative scientific
  smoke behavior.
- [x] The release workflow smoke-checks `bng_cpp --version` and `NFsim -help`
  on each binary runner before archiving; `tests/test_ci_contract.py` guards
  the step and its ordering.
- [ ] CLI binaries and optional native NFsim artifacts have not yet completed
  an exact-tag hosted release build and smoke test.
- [ ] Docker/container artifacts build, run, and have recorded base-image
  digests where supported.
- [ ] Release artifacts are content-addressed, reproducible, and tied to the
  exact validated SHA.
- [x] The release workflow now blocks tags whose commit is not reachable from
  `main` and requires successful completed push runs for `CI`, `Cross-tool
  parity`, `Lean semantic kernel`, and `CodeQL` at the exact tagged SHA before
  building or publishing. The fail-closed workflow-run matcher and dependency
  wiring pass `tests/test_ci_contract.py`; the hosted tag workflow has not been
  exercised. This gate does not yet verify artifact provenance or the approved
  golden report.
- [ ] Release artifacts carry approved provenance and golden-report evidence.
- [ ] PyPI/test-index publication is staged or dry-run verified before the
  first public release.
- [ ] Hosted release jobs for source distribution, wheels, Docker, and
  publication are actually exercised for the release candidate; PR-only
  skipped jobs are not counted as evidence.

### Isolated package artifact audit — 2026-09-28

- [x] Built isolated source distribution and wheel with `scikit-build-core`
  for CPython 3.14 on macOS arm64. Corrected source distribution contains
  1,543 members and excludes every `bng3-offline-bundle/` member; compressed
  size is 4,791,673 bytes. The direct wheel is 3,079,617 bytes. SHA-256:
  sdist `09017d011be5e73418ac0c2e80009fd582f29632c0a39d14c12d2f1f609fff2d`,
  wheel `d58765c8ff9de7aaa6fdc8a4eef8f4718c6aab213652dccfc8cc347890c81347`.
- [x] Rebuilt a wheel from the corrected source archive in a clean virtual
  environment. Clean wheel install passes `pip check`; `bionetgen --version`
  reports `3.0.0a1`; Python imports the installed package and CPython 3.14
  native extension from that environment. An installed-package ODE smoke
  produced 11 points and `A_total` from 10.0 to 3.6787942479103934.
  Rebuilt wheel SHA-256:
  `6b02b55442214becc257afb6904585ae347067e406cf4179bde112bbd5a318d1`.
- [ ] This validates one local macOS arm64 / CPython 3.14 artifact path only.
  Linux, Windows, other Python versions and architectures, complete package
  data, and release workflow gates remain unverified.
- [x] Declared scikit-build-core's wheel-build CMake floor explicitly as
  `>=3.15`, while preserving the standalone CMake project minimum of 3.14.
  This removes the backend's minimum-version warning without changing the
  project's direct CMake requirement.
- [x] Rebuilt the macOS arm64 / CPython 3.14 wheel from source commit `3283779`.
  It is 3,083,636 bytes, SHA-256
  `cedbb2e723b83adebe8f2da6f1cb8760cff487cb208fcbaf4becaf5a8d715ac4`.
  Installed it with declared runtime dependencies in a clean temporary
  environment (`numpy 2.5.3`, `click 8.5.0`, `packaging 26.3`). `pip check`,
  CLI version, native extension import, and modern Atomizer scheduling of the
  delayed `semantic/00778` event at `t=7.07917484418` pass. Cross-platform and
  release gates remain open.

### Current-main local wheel and source archive audit — 2026-09-28

- [x] Built the source distribution and macOS arm64 / CPython 3.14 wheel from
  current `main` at `362c100b0b15db5cd1321200f4196bc8939b4958`, using the
  installed `scikit-build-core 1.0.3`, `pybind11 3.1.0`, CMake 4.4.3, and
  AppleClang 21.0.0. The isolated PEP 517 attempt could not fetch build
  requirements because PyPI was unreachable; the `--no-isolation` build
  completed successfully.
- [x] The source archive has 1,544 members and excludes all
  `bng3-offline-bundle/` and `bng3-offline-deps.tar.gz` files. Sdist size is
  4,806,090 bytes, SHA-256
  `513fe950c407f86d81bdf92de0279ce12b33f17927adffadffbe45c0c12cc6ed`.
  Wheel size is 3,083,730 bytes, SHA-256
  `393f2ccd2c602645622186dc354c4474ef21c2a250309df5ab473a0dc3316532`.
- [x] Installed the wheel into a temporary CPython 3.14 virtual environment.
  The installed CLI reports `3.0.0a1`; a fresh process imported the wheel's
  Python package and native extension and ran an ODE smoke to 11 points, with
  `A_total` changing from 10.0 to 3.6787942479103934. Runtime dependencies
  came from the host Python installation. `pip check` on that host-visible
  environment reported unrelated existing conflicts in `jedi`, `numpy`, and
  `ipykernel`; this is not clean dependency-resolution evidence.
- [ ] This is one local macOS arm64 / CPython 3.14 artifact path, not a
  cross-platform wheel matrix, clean runtime dependency solve, complete package
  data audit, hosted release workflow, or publication test.

### Current-main package refresh — 2026-09-28

- [x] Built sdist and wheel with `python -m build --no-isolation --sdist
  --wheel` from `main` at `15ea1b56f36b89c12fee6347913024d6cb04c311` on macOS
  arm64 / CPython 3.14.6 using scikit-build-core 1.0.3, CMake 4.4.3, and
  AppleClang 21.0.0. The sdist has 1,544 members and contains no offline-bundle
  files. Sdist SHA-256 `5bd96fdf8431d203312a4a95123c2048840ac7cf2ca512169eeb601c1da02710`;
  wheel SHA-256 `861a1eaa6123bf2d4c28baf58386f3f1ac01ff3a678934d22c35185796c87ff1`.
- [x] Installed the wheel into a temporary CPython 3.14 environment and loaded
  its native extension. The installed package's stationary-event regression
  passed, and the CLI ODE smoke wrote 11 points with `A_total` changing from
  `10` to `3.6787942479103934` at `t=2`.
- [ ] The environment exposed host runtime packages. `pip check` reports
  existing host conflicts involving Jedi, NumPy, and ipykernel; clean dependency
  resolution, other operating systems/Python versions, hosted release jobs, and
  publication remain unverified.

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

## Affine interval events and static conversion factors — 2026-09-26

- [x] Lower a single event whose trigger is a conjunction of one state's
  lower and upper bounds when the state has a proven affine trajectory. Schedule
  the rising edge and interval end exactly; preserve trigger-time values and
  nonpersistent cancellation. Permit the event's own update only when its next
  rising edge is proven outside the simulation horizon. Reject coupled,
  dynamically controlled, ambiguous, or unsafe re-entry cases.
- [x] Include immutable species/model conversion factors in the affine
  trajectory proof, with the species factor taking precedence. Dynamic factors,
  fast reactions, and reaction-level conversion factors remain unsupported.
- [x] Thirteen additional official cases pass: `semantic/01580`-`01582`,
  `01675`-`01680`, `01687`-`01688`, and `01690`-`01691`. Full pinned suite:
  `1,489 passed, 434 unsupported, 0 failed, 0 timeouts`; 13 gains and zero
  regressions from `1,476/447`. Event blockers fell from 345 to 332. Report
  `/private/tmp/bng3-sbml-affine-interval-full.json`, SHA-256
  `0a4fe386e23fec4841980f7164a72d5af383ab16f5c534577736e40bb8278b4c`.
- [x] The generated-model CVODE comparison in the full report passed against
  libRoadRunner 2.10.0 for all 13 newly passing cases. Each had 3 or 4
  observables; maximum absolute difference was `1.78e-15`. The harness used
  the suite model's one-unit horizon and 10 steps. Separately, cases
  `01675`-`01679` passed the targeted 20-unit/100-step validator run. This is
  BNG3/libRoadRunner parity evidence, not SBML Test Suite reference-result
  conformance.
- [x] Full Python suite: `556 passed, 28 skipped`; changed-file Ruff,
  compileall, and `git diff --check` pass. Full curated BioModels was not
  rerun, so no curated-model gain is claimed.
- [x] After the SBML suite completed, reran the full offline curated BioModels
  inventory in both Atomizer modes. All 1,096 records were present. Counts and
  per-mode outcomes exactly match the prior full refresh: 781/1,083 SBML
  records passed, 127 unsupported, 5 failed, and 170 timed out; 13 additional
  non-SBML records are explicit inventory exclusions. Across 1,826 per-mode
  results, 1,562 passed, 254 were unsupported, and 10 failed. Of 1,822
  numerical comparisons, 1,562 passed and 260 did not; all mode and comparison
  statuses match the prior report. Report
  `/private/tmp/bng3-biomodel-affine-interval-full.json`, SHA-256
  `7ed6cb084c9b9c6759b9fd02ad411928e7f95004fe80b66f359291dde2dcc66c`.

## Static state-trigger events — 2026-09-26

- [x] For one-event models with no reactions, rules, or initial assignments,
  evaluate a direct state threshold from its initial value. Omit it only when
  it stays false, or when it starts true and `trigger.initialValue` suppresses
  the initial edge. When it starts true with `initialValue=false`, schedule
  the one initial event edge and its fixed delay. Rate-rule-driven symbols and
  models with other dynamic state remain untranslated.
- [x] Official `semantic/01335` now passes. The full pinned SBML suite reports
  `1,490 passed, 433 unsupported, 0 failed, 0 timeouts`; one new pass, no
  regressions from `1,489/434`, and event blockers fell from 332 to 331. Report
  `/private/tmp/bng3-sbml-static-events-full.json`, SHA-256
  `ae3d91d7e0575975eac6a5e1a045d56b0e81c769f05e6e907778c940b00479fc`.
- [x] `01335` has no observables, so the report's libRoadRunner simulation
  comparison is vacuous; its pass establishes import, event lowering, network
  generation, SBML write/reimport, and native-reader checks only.
- [x] Full Python suite: `558 passed, 28 skipped`; changed-file Ruff,
  compileall, and `git diff --check` pass. The full curated BioModels rerun
  predates this slice.

## Constant piecewise event values and exact window cancellation — 2026-09-26

- [x] Fold constant `piecewise` and `if` branches lazily so unselected
  expressions may remain dynamic; evaluate n-ary chained equality predicates
  according to their adjacent comparisons. For nonpersistent events, omit the
  scheduled action when a proven fixed time-window end occurs at or before its
  delayed execution time.
- [x] Five official cases now pass: `semantic/01212`, `01213`, `01214`,
  `01526`, and `01661`. Full pinned suite: `1,495 passed, 428 unsupported,
  0 failed, 0 timeouts`; five gains and zero regressions from `1,490/433`.
  Event blockers fell from 331 to 326. Report
  `/private/tmp/bng3-sbml-piecewise-events-full.json`, SHA-256
  `9a0ce425da2b887492ba1c9a9e75767585ff6c219e1f2e1afa36037ab7069474`.
- [x] The full SBML report records all five new cases as having zero
  observables; generated-model/libRoadRunner comparisons are therefore
  vacuous. This slice establishes event parsing/lowering and roundtrip checks,
  not numerical simulation parity.
- [x] Full Python suite: `560 passed, 28 skipped`; changed-file Ruff,
  compileall, and `git diff --check` pass. The prior cached-source screen
  covered 1,084 curated BioModels XML files: 167 had events, only three events
  used a piecewise expression, and those had a complex dynamic trigger. A
  second screen found no model with a literal-delay, nonpersistent bounded-time
  event whose delay reaches the window end. The prior full curated report
  remains the only full-inventory result for this slice; no curated gain is
  claimed.

## Repeated exponential threshold resets — 2026-09-26

- [x] When one event resets its own parameter/species threshold state to a
  constant on the trigger's false side, and its exact exponential trajectory
  has immutable coefficients, schedule each subsequent rising edge and fixed
  delayed execution time. Other assignments must be unique, constant, and
  parameter/species targets. Require one event and reject nonpositive resets,
  non-rising thresholds, dynamic/coupled coefficients, or non-finite times.
- [x] The full pinned one-unit suite reports `1,496 passed, 427 unsupported,
  0 failed, 0 timeouts`; one gain (`semantic/00684`) and zero regressions from
  `1,495/428`. Event blockers fell from 326 to 325. Report
  `/private/tmp/bng3-sbml-exp-reset-full.json`, SHA-256
  `1d02fd20bbed61a3094f73c4c17032de51e48c1d8b9004064b4493bee5a0fdc1`.
  `00684` matched libRoadRunner across five observables at the suite's
  one-unit horizon (maximum absolute difference `2.50e-11`).
- [x] With a 10-unit, 100-step horizon, targeted cases `semantic/00026`,
  `00071`, `00073`, `00074`, and `00172` pass and match libRoadRunner across
  all generated observables; maximum absolute difference was `1.88e-14`.
  These events occur after the one-unit suite horizon, so targeted long-horizon
  results are listed separately from the full-suite count.
- [x] Full Python suite: `561 passed, 28 skipped`; changed-file Ruff,
  compileall, and `git diff --check` pass. A cached scan of 1,084 curated
  BioModels XML files found no direct single-state exponential self-reset
  event candidate; no curated gain is claimed and the previous full inventory
  report remains the current curated benchmark evidence.

## Delayed affine rate-rule self-reset events — 2026-09-26

- [x] For one event with a constant-slope parameter rate rule, lower a direct
  rising threshold crossing and delayed self-assignment when event assignment
  depends only on proven affine trajectories. Preserve both
  `useValuesFromTriggerTime` modes. Schedule repeated events only when a
  self-reset returns the trigger to its false side; schedule a single event
  when its assignment leaves the monotone trigger true.
- [x] Resolve reaction-local SBML parameters before global symbols when
  proving constant reaction flux. This preserves SBML local scope in exact
  affine trajectory analysis; dynamic/coupled fluxes remain unsupported.
- [x] Full pinned one-unit suite: `1,500 passed, 423 unsupported, 0 failed,
  0 timeouts`; four gains (`semantic/01710`, `01711`, `01715`, `01716`) and no
  regressions from `1,496/427`. Report
  `/private/tmp/bng3-sbml-affine-self-reset-full.json`, SHA-256
  `61c3554b914955f5ea86d17844f1ca7d4ba02d45675dc2da1ffbe0ce5b7dbc8c`.
  The default one-unit horizon still leaves `01701` and `01702` unsupported
  because their first trigger occurs after that horizon.
- [x] At a 10-unit/100-step horizon, `semantic/01701`, `01702`, `01715`, and
  `01716` pass SBML roundtrip and BNG3-CVODE/libRoadRunner comparison. Maximum
  absolute differences: `5.33e-15` for `01701`/`01702` (one observable) and
  `2.85e-14` for `01715`/`01716` (three observables). Individual targeted
  reports are `/private/tmp/bng3-affine-01701.json` through
  `/private/tmp/bng3-affine-01716.json` for the four case IDs.
- [x] Full Python suite with the compiled extension on `PYTHONPATH`:
  `562 passed, 28 skipped`; changed-file Ruff, compileall, and diff checks
  pass. Default-environment run without `build/cpp` had 23 unrelated
  compatibility/backend failures; the supported build environment passed.
- [x] Full curated BioModels inventory rerun with the prior 120-second
  per-model limit: all 1,096 records; 781/1,083 SBML records passed, 127 were
  unsupported, 5 failed, and 170 timed out. Both modes and every comparison
  status match the prior full run across all records; no curated gain or
  regression. Report `/private/tmp/bng3-biomodel-affine-self-reset-biomodels-120s.json`,
  SHA-256 `61277f9c247f78cac66079e60750a714fbf9c3967cd2ead32d79b76633c973b9`.
  Thirteen inventory records remain non-SBML exclusions. The aggregate core
  gate remains failed.

## Rate-rule species threshold events — 2026-09-26

- [x] Resolve a direct rate rule for a species symbol as an affine
  concentration trajectory when `hasOnlySubstanceUnits=false`, its derivative
  is constant-foldable, and no initial assignment or other event changes the
  species. This supports time-zero initial edges and self-assignments through
  the matching BNGL species pattern; unknown/coupled states remain rejected.
- [x] `semantic/01510` and `01511` now pass the full one-unit suite. Aggregate
  result: `1,502 passed, 421 unsupported, 0 failed, 0 timeouts`; two gains and
  zero regressions from `1,500/423`. Report
  `/private/tmp/bng3-sbml-rate-rule-species-event-full-corrected.json`, SHA-256
  `598cd9b1c5f04e1f457894b1b36ca51c5366c8faccd198e461c36842a7f629a8`.
  Both new cases pass all five observable comparisons versus libRoadRunner
  2.10.0: maximum absolute differences are `0` and `3.34e-16`.
- [x] Full Python suite: `563 passed, 28 skipped`; changed-file Ruff,
  compileall, and `git diff --check` pass. Cached curated BioModels XML screen
  found no matching unsupported one-event, species rate-rule self-assignment;
  no curated gain is claimed. Prior full BioModels status remains unchanged.

## Multiple assignments on affine reset events — 2026-09-26

- [x] Exact affine rate-rule self-reset events can schedule multiple unique
  parameter/species assignments together when the self-reset assignment is
  affine and each companion assignment folds to a finite static value. Dynamic
  companion values remain untranslated to avoid using stale event snapshots in
  later recurrence cycles.
- [x] Added a synthetic regression for repeated delayed event execution with a
  static companion assignment. Focused event regressions pass (`3 passed`);
  full Python suite passes `564 passed, 28 skipped`. Ruff, compileall, and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite remains `1,502 passed, 421 unsupported,
  0 failed, 0 timeouts`, identical to the prior report (SHA-256
  `598cd9b1c5f04e1f457894b1b36ca51c5366c8faccd198e461c36842a7f629a8`). This
  slice adds no official-suite pass. A cached scan of 6,538 BioModels XML files
  found zero multi-assignment events that target a rate-rule variable; no
  curated-model gain is claimed and the full inventory was not rerun.

## Constant Boolean terms in affine event triggers — 2026-09-26

- [x] An affine state threshold parser now drops statically true terms from an
  `and(...)` trigger before solving its exact crossing time. It leaves false
  or dynamic conjunctions untranslated unless the remaining trigger reduces
  to one supported state threshold.
- [x] Official `semantic/01531` now passes; its three previously untranslated
  triggers were affine rate-rule thresholds conjoined with constant-true
  Boolean terms. The full pinned SBML suite reports `1,503 passed, 420
  unsupported, 0 failed, 0 timeouts`: one gain and zero regressions from
  `1,502/421`. Report `/private/tmp/bng3-sbml-bool-affine-events-final.json`,
  SHA-256 `8558585d47a4fe2c6683709a35432f7348e0c12238614a8f50bab59dcae71d64`.
- [x] Full Python suite: `565 passed, 28 skipped`; `semantic/01531` passes the
  import, schedule, SBML roundtrip, and native-reader checks. It has no
  observables, so no numerical libRoadRunner comparison is claimed. A cached
  scan of 6,538 curated BioModels XML files found no rate-rule threshold
  conjunction with explicit Boolean terms; the full BioModels inventory was
  not rerun and no curated gain is claimed.

## Affine rate-rule compartment thresholds — 2026-09-26

- [x] Resolve a compartment's finite initial size and unique constant-foldable
  rate rule as an affine trajectory for event threshold scheduling. Initial
  assignments, competing event assignments, duplicate/non-rate rules, and
  non-constant derivatives remain fail-closed.
- [x] `semantic/01120` now passes. Full pinned SBML Test Suite: `1,519 passed,
  404 unsupported, 0 failed, 0 timeouts`; one gain and no regressions from
  `1,518/405`. Report `/private/tmp/bng3-sbml-compartment-full.json`, SHA-256
  `fd363ed5719db29c9266eef791b38d8677d3ed7800562a4fc04cdd310da6bae0`.
  BNG3 CVODE agrees with libRoadRunner 2.10.0 across all three observables at
  the suite's one-unit horizon (maximum absolute difference `8.88e-16`); a
  targeted three-unit run also passes after the delayed event executes.
- [x] Full Python suite: `571 passed, 28 skipped`; repository-wide Black,
  Ruff, and `git diff --check` pass. A targeted screen of 6,724 cached
  BioModels XML files found no compartment rate-rule event triggers; no
  curated-model gain is claimed.

## Exponential self-reset events beyond the requested horizon — 2026-09-26

- [x] A single exponential threshold-reset event whose first rising crossing
  occurs after the configured simulation horizon is now classified as having
  no state changes within that run. The event is omitted with an informational
  horizon-bounded diagnostic; longer horizons retain exact recurrence
  scheduling. Other events and unsupported trajectories remain fail-closed.
- [x] `semantic/00026`, `00071`, `00073`, `00074`, and `00172` now pass the
  one-unit gate. Full pinned suite: `1,524 passed, 399 unsupported, 0 failed,
  0 timeouts`; five gains, no regressions, and supported-surface gate passes.
  Report `/private/tmp/bng3-sbml-horizon-full.json`, SHA-256
  `5a959bb2fbb3d5de1f71db0b59e64319f959e9ddedf3c146808499aeee70fcba`.
  All five match libRoadRunner 2.10.0 exactly across generated observables at
  the one-unit horizon.
- [x] Full Python suite: `572 passed, 28 skipped`; repository-wide Black,
  Ruff, and `git diff --check` pass. A targeted scan of 6,724 cached BioModels
  XML files found no single-event exponential self-reset candidate (9 XML
  parse errors); no curated-model gain is claimed. The earlier full curated
  refresh was canceled because it predated this code and the compartment
  source screen had no matching models; the prior inventory report remains the
  last full BioModels benchmark.

## Curated BioModels CVODE refinement — 2026-09-26

- [x] On an existing numerical observable mismatch, retry both BNG3 and
  libRoadRunner with stricter relative/absolute tolerances. Keep the original
  mismatch as the result unless the refined comparison passes the same
  numerical predicate; record the refined settings and attempt result.
- [x] Targeted `BIOMD0000000702` flat/atomized roundtrip passes both modes.
  Flat mode passes with `rtol=1e-11`, `atol=1e-20`, `max_step=1e-4`; atomized
  mode passes at original tolerances. This targeted benchmark recovery is
  included in the aggregate comparison below. Report
  `/private/tmp/bng3-0702-refined.json`.
- [x] Full curated inventory with the refinement retry completed in both flat
  and atomized modes: 775/1,083 SBML records passed, 128 were unsupported,
  8 failed, and 172 timed out. Compared with
  `/private/tmp/bng3-curated-after-events-nonfinite.json`, two model statuses
  improved (`BIOMD0000000183` timeout→pass and `BIOMD0000000702` fail→pass),
  with no regressions. Report `/private/tmp/bng3-curated-e9797d0-refined.json`,
  SHA-256 `6260059bfa282a6f82818891613448b0761a3144b094f674a8ab5692a6c82542`.

## Time-only sinusoidal assignment-rule event crossings — 2026-09-26

- [x] A narrow, exact lowering handles event thresholds on a time-only
  `piecewise(sin(a*time+b), time < cutoff, fallback)` assignment rule when its
  coefficients and fallback are static. It enumerates false-to-true crossings
  through the configured horizon and schedules persistent delayed events.
  Unsupported boundaries, dynamic coefficients, and nonpersistent delayed
  events remain untranslated.
- [x] Official SBML Test Suite `semantic/00936` passes the source import,
  generated SBML validation, and reimport. BNG3 CVODE agrees with libRoadRunner
  2.10.0 for all three observables over 10 time units / 100 intervals, with
  maximum absolute difference `0`. Report
  `/private/tmp/bng3-00936-after-sine-final.json`, SHA-256
  `d8049a30646b3344ad75412eb13522f81dd64ceae4e3cd6d89a2ef677086a2ab`.
- [x] Full pinned SBML Test Suite at commit `1db689e`: `1,600 passed, 323
  unsupported, 0 failed, 0 timeouts`. Relative to the previous full report
  (`1,524/399`), 76 cases changed from unsupported to passed and none regressed.
  All 1,522 passed cases with observables pass the configured BNG3/libRoadRunner
  comparison; 78 passed cases have no observables, so their comparison is
  vacuous.
  Report `/private/tmp/bng3-sbml-sinusoidal-full.json`, SHA-256
  `955514a936b551cfc7bf8958f5c0647c98ec20575c4bfa0b277978f2b84addf2`.
- [x] Full curated BioModels report completed at source commit `e9797d0` and
  is recorded above. The subsequent `cosh(time)` slice was screened against
  the cached corpus: only four SBML models contain `cosh`, and all four have
  zero SBML events, so no curated result can change.
- [x] Full Python suite: `588 passed, 28 skipped`; changed-file Ruff, Black,
  and `git diff --check` pass.

## Time-only cosh assignment-rule event windows — 2026-09-26

- [x] Lower a conjunction of constant lower/upper thresholds on a time-only
  `cosh(time)` assignment-rule trajectory to exact `acosh` time bounds when
  both thresholds exceed one. Preserve event delay, values-from-trigger-time,
  initial trigger value, and persistence. A single rising threshold already
  true at t=0 lowers to a zero-time edge when `triggerInitialValue=false`.
  Leave nonmatching trigger shapes untranslated.
- [x] Official cases `semantic/01594`, `01595`, and `01596` now pass. The full
  pinned one-unit suite reports `1,603 passed, 320 unsupported, 0 failed,
  0 timeouts`, three gains and no regressions against `1,600/323/0/0`. Report
  `/private/tmp/bng3-cosh-full-horizon1-01596.json`, SHA-256
  `2614f3137f7ae32822f30323127b0f8f58767d3c58d8fd66a16f167cc1a15fd8`. Each
  case's one reported observable matches libRoadRunner 2.10.0 on all 101
  samples with maximum absolute error `0`; event-assigned `P2` is not included
  in the report's observable comparison.
- [x] The full curated baseline at source commit `e9797d0` covers all 1,096
  records: 775/1,083 SBML records passed, 128 were unsupported, 8 failed, and
  172 timed out. A cached-corpus screen found four XML files with `cosh`
  (`BIOMD0000000280`, `0324`, `0693`, `0844`); all have zero SBML events. The
  full replay was stopped because this slice cannot affect any model or mode;
  no curated gain is claimed.
- [x] Full Python suite: `589 passed, 28 skipped`; focused event tests:
  `33 passed`. Ruff, Black (`py39` target), and
  `git diff --check` pass. Local tests used a temporary `telnetlib` import
  shim because Python 3.14 removed the module imported by the legacy Atomizer
  package initializer; the shim does not change BNG3 code.

## Parameter-only discrete SBML event systems — 2026-09-26

- [x] Compile parameter-only event systems to absolute-time BNGL actions when
  triggers and assignments can be simulated exactly. Support finite parameter
  initial assignments, discrete parameter comparisons, time-evaluated delays,
  `useValuesFromTriggerTime`, persistent and nonpersistent delayed events, and
  at most one fixed rising comparison against time per trigger. Reject
  species/reaction/rule dynamics, unsupported time predicates, priorities,
  conflicting simultaneous assignments, invalid delays, and event loops
  exceeding 10,000 firings.
- [x] Official cases `semantic/01754`–`01759` pass conversion, SBML write and
  reimport, and supported-surface checks. Cases `01754`–`01757` match
  libRoadRunner 2.10.0 on one reported observable over 101 samples with max
  absolute error `0`; `01758` and `01759` have no reported observables, so
  their numerical comparison is vacuous. The full pinned one-unit suite
  reports `1,618 passed, 305 unsupported, 0 failed, 0 timeouts`: 15 gains and
  no regressions against `1,603/320/0/0`. Seven gained cases have observables,
  each with max absolute error `0`; eight have none. Report
  `/private/tmp/bng3-static-events-final-horizon1.json`, SHA-256
  `8af5a5f64138202f454eafdb7b59ff3339e8634f86d80658ced0f93bb5f6a537`. The
  aggregate suite gate remains incomplete because 305 cases are still
  unsupported.
- [x] Cached screen of 4,515 BioModels SBML files found no parameter-only
  event-only models within this feature's scope; no curated-model gain claimed.
- [x] Full Python suite: `596 passed, 28 skipped`; focused event tests:
  `38 passed`. Ruff, Black (`py39` target), and `git diff --check` pass.

## Parameter-only event priorities and clock resets — 2026-09-26

- [x] Extend parameter-only event lowering for same-time event priorities,
  recalculating priority after each firing and rechecking nonpersistent
  cancellations. Simultaneous ties are lowered only when their assignments,
  triggers, and priorities are independent; unsupported interactions remain
  untranslated.
- [x] Recompute the next clock crossing for the restricted rising trigger
  `time - parameter >= constant` after parameter resets. Continue to reject
  unsupported time-dependent trigger forms. Drop events with missing triggers
  and coerce numeric nonzero trigger values to true.
- [x] Official cases `semantic/00967`, `00978`, `00997`, `01238`, `01239`, and
  `01284` pass the conversion, write/reimport, native-reader, and
  supported-surface checks. The full pinned one-unit suite reports `1,624
  passed, 299 unsupported, 0 failed, 0 timeouts`, six net gains and no
  regressions versus `1,618/305/0/0`. Report
  `/private/tmp/bng3-static-events-priority-final.json`, SHA-256
  `dd4129d633683c888c842a88d021f7663e7abbdbeffb4dd6eecc39e61b51fe5f`.
  All six new cases report zero observables; their numerical comparison is
  therefore vacuous, and SBML Test Suite reference-result conformance was not
  run. The aggregate SBML support gate remains open with 299 unsupported
  cases.
- [x] Focused event tests: `41 passed`; the full Python suite on this code was
  `599 passed, 28 skipped`. Ruff, Black (`py39` target), and
  `git diff --check` pass. The previous cached BioModels screen found no
  parameter-only event-only candidates; no curated-model gain is claimed.

## Exponential state interval event crossings — 2026-09-27

- [x] Lower a single event whose trigger is a two-bound interval over one
  exactly exponential state, with positive finite bounds and monotone rate.
  Compute the first entry and exit times logarithmically; preserve delayed
  assignment time and trigger-time state evaluation. Keep unsupported
  delayed-history intervals and events that assign the trigger state
  untranslated.
- [x] Official SBML Test Suite case `semantic/00932` now passes conversion,
  SBML write/reimport, native-reader checks, and BNG3/libRoadRunner comparison
  for six observables at the one-unit/10-step horizon. Maximum absolute
  difference: `2.8247452283063773e-11`. Its nonpersistent delayed assignment
  is correctly canceled: the state interval lasts about `0.2231` time units,
  shorter than its fixed delay of `3`. Full pinned suite: `1,625 passed,
  298 unsupported, 0 failed, 0 timeouts`; one net gain and no regressions
  against `1,624/299/0/0`. Report
  `/private/tmp/bng3-exponential-interval-full.json`, SHA-256
  `789fba1ab83b7bceb95b92344f08196c9c37610da163d28a0a039f344c993b58`.
  Supported-surface gate passes; aggregate core gate remains open. SBML Test
  Suite reference-result conformance was not run.
- [x] Added a synthetic exponential-decay interval regression with an
  observed failing-before/passing-after TDD cycle. Full Python suite:
  `601 passed, 28 skipped`; focused event and parity tests: `105 passed`.
  A second fixture executes generated BNGL actions and compares A/B output
  trajectories with libRoadRunner; post-event samples match within the
  configured `max(5e-12, 1e-5 * scale)` tolerance. The exact event-boundary
  sample is excluded because BNG3 records the pre-action side while
  libRoadRunner reports the right-continuous post-action side. Ruff, Black
  (`py39`), and `git diff --check` pass. Cached source scan of 7,733 BioModels
  XML files found zero matching single-event exponential interval candidates;
  no curated-model gain is claimed.

## Delayed exponential state interval crossings — 2026-09-27

- [x] Lower a delayed-history interval over an exactly exponential state by
  shifting its analytic entry and exit times by the fixed history delay. For
  trigger-time assignments, use the current state at the shifted trigger time,
  not the historical bound value. Unsupported or overflowing trajectories
  remain untranslated.
- [x] Added a regression for `delay(P1, 1)` crossing `[0.4, 0.5]` on
  `P1(t)=exp(-t)`: event time is `1 + ln(2)`, and the trigger-time snapshot is
  `exp(-(1 + ln(2))) = 0.183939720586`. Delayed affine persistence and interval
  tests remain green; focused event and Atomizer parity tests: `106 passed`.
  Full Python suite: `602 passed, 28 skipped`. Official targeted suite cases
  `01518`-`01520` remain passed; `01522` remains unsupported because its
  delayed trigger is a time-history predicate, outside this state-trajectory
  slice. No status changes in those four cases. Full suite and curated
  inventory not rerun; no corpus gain is claimed.

## Initial-time evaluation of shifted time triggers — 2026-09-27

- [x] Evaluate `time` as `0` in the initial trigger-state check, after
  expanding pure SBML functions. This preserves the declared
  `triggerInitialValue` edge when an event trigger contains a shifted time
  expression such as `delay(time-valued-parameter, fixed-delay)` after SBML
  normalization.
- [x] Official case `semantic/01522` now passes. Its normalized trigger is
  `(time - 1) < -0.5`, true at t=0 with `triggerInitialValue=false`; generated
  BNGL schedules `P2=3` at t=0. Its `P1` observable matches libRoadRunner 2.10.0
  exactly at 11 samples (max absolute difference 0); the event target is not
  an observable, so that comparison alone does not validate `P2` numerically.
  Full pinned suite: `1,626 passed, 297 unsupported, 0 failed, 0 timeouts`;
  exactly one gain (`01522`), no regressions from `1,625/298/0/0`. Report
  `/private/tmp/bng3-time-shifted-trigger-full.json`, SHA-256
  `3e1a791e95231f690243f30789f14bd137cd3c32bbc00875420095be1aba1b1c`.
  Supported-surface gate passes; aggregate core gate remains open. Reference-
  result conformance was not run. Full Python suite: `604 passed, 28 skipped`;
  Ruff, Black (`py39`), and `git diff --check` pass. Full curated BioModels
  refresh is running; record its terminal report separately.
- [x] The reaction-bearing `semantic/00932` cohort also passes the
  BNG3-modern and PyBioNetGen-legacy Atomizer cross-engine benchmark against
  both BNG3 and Perl BNG2 network generation: 3/3 structural and rate-parity
  repetitions in flat and atomized modes. Report
  `/private/tmp/bng3-atomizer-cross-engine-00932.json`, SHA-256
  `9492f3ea454fbef18e0361eb50ef0ce79597ad10a5b630a81b25e0f8b2c77db0`.
  This benchmark covers network structure and rates, not simulation parity;
  libRoadRunner trajectory parity is recorded separately above.

## Simultaneous fixed-time reaction-rate priorities — 2026-09-27

- [x] Lower dynamic reaction-rate priorities for exactly two events sharing
  one positive fixed-time trigger and delay, the same `triggerInitialValue`,
  and trigger-time assignment snapshots. Evaluate both priorities against
  the common pre-event state before emitting their deterministic execution
  order. Reaction rates depending on species, rules, initial assignments, or
  parameters changed by earlier or differently triggered events remain
  untranslated.
- [x] Add a regression covering simultaneous events that both assign `k1`
  and have priorities `J0` and `J0 - 1`; prove the emitted action order.
  Focused event/parity tests: `109 passed`; full Python suite: `605 passed,
  28 skipped`. Ruff, Black (`py39`), and `git diff --check` pass.
- [x] Official `semantic/01229` now passes conversion, SBML write/reimport,
  native-reader checks, and BNG3/libRoadRunner 2.10.0 comparison through
  `t=7`: 2 observables, 71 samples each, maximum absolute error
  `1.7763568394002505e-15`. Report
  `/private/tmp/bng3-semantic-01229-priority-t7-final.json`, SHA-256
  `1dc5d0474b588a77baf7583950f642a678b4c655863d00dd9a8ad220bbf53e45`.
- [x] Full pinned suite: `1,627 passed, 296 unsupported, 0 failed, 0
  timeouts`; exactly one gain (`semantic/01229`) and no regressions from
  `1,626/297/0/0`. Report `/private/tmp/bng3-priority-rates-final.json`,
  SHA-256 `588377bf138d2c5afdada4a04d5b318046c03d754791e389cca646987c259ef3`.
  Overall core gate remains open; reference-result conformance was not run.
- [ ] Re-run the full curated BioModels inventory in flat and atomized modes
  against the final source; the exact-source run was interrupted to continue
  implementation, so no current-source result is available.

## Recomputed simultaneous event priorities — 2026-09-27

- [x] Recalculate each pending event's priority after applying the previously
  selected event's trigger-time assignment snapshot. Require one complete,
  compatible simultaneous group; reject the group if any candidate priority
  cannot be folded safely.
- [x] Add regressions for A → C1 → B priority recalculation and for a partially
  foldable group. The latter emptied the execution schedule and raised
  `IndexError`; it now yields a normal unsupported translation.
- [x] Full Python suite: `607 passed, 28 skipped`. Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,628 passed, 295 unsupported, 0 failed,
  0 timeouts`; net +1 (`semantic/00934`) and no regressions from
  `1,627/296/0/0`. `semantic/01577` is unsupported because its rate-rule and
  algebraic-rule priority state cannot be soundly evaluated, no longer failed.
  Report `/private/tmp/bng3-multi-priority-fixed-full.json`, SHA-256
  `977050ef6443d9bbaba4835547aa6a487cf73395746e085a7bb8be3e3eef1345`.
- [x] `semantic/00934` passes round-trip plus BNG3/libRoadRunner 2.10.0
  comparison for four observables through t=1.1 (12 samples, maximum absolute
  difference 0). Report `/private/tmp/bng3-semantic-00934-priority-t1.1.json`,
  SHA-256 `1dcb76830bdfa48c78f9d88de24e047c6d773a6b94841a1e5ae2e53fa214a7d4`.
  `semantic/01229` still matches through t=7 (two observables, maximum absolute
  difference `1.7763568394002505e-15`); report
  `/private/tmp/bng3-semantic-01229-priority-t7-final2.json`, SHA-256
  `1dc5d0474b588a77baf7583950f642a678b4c655863d00dd9a8ad220bbf53e45`.
- [ ] Rerun the full curated BioModels inventory in flat and atomized modes
  against this source. The earlier run was interrupted to continue feature
  work, so it does not provide final-source evidence.

## Assignment-rule priorities from analytic state — 2026-09-27

- [x] Fold simple SBML assignment rules while evaluating simultaneous event
  priorities, using only supported state values and analytic affine or
  exponential trajectories. Cycles, duplicate rules, and unresolved inputs
  remain unsupported.
- [x] Add a unit regression for a priority derived from an assignment rule.
  The official `semantic/01577` model (`k2 = 10 - k1`, with `k1' = 1`) now
  passes conversion, round-trip, native-reader checks, and BNG3/libRoadRunner
  comparison for two observables. Report
  `/private/tmp/bng3-semantic-01577-assignment-priority.json`, SHA-256
  `18ddfeb773b4ed6abdcc7692b2eabce3aa099c92ff30fbb414df21694c4f46fc`.
- [x] Full Python suite: `608 passed, 28 skipped`. Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,629 passed, 294 unsupported, 0 failed,
  0 timeouts`; +1 (`semantic/01577`) and no regressions against
  `1,628/295/0/0`. Report `/private/tmp/bng3-priority-assignment-full.json`,
  SHA-256 `cb2a68ed2c27c6fd6b23221645e5e0f2c8a8d65e1fdc0af3b3cbb59407c44c95`.
- [ ] Rerun the full curated BioModels inventory in flat and atomized modes
  against this source; the interrupted run is not final-source evidence.

## SBML L3V2 EventAssignments without MathML — 2026-09-27

- [x] Pass SBML Level 3 Version 2 to event parsing. Omit an EventAssignment
  whose optional `math` is absent; preserve assignments with valid MathML.
- [x] Add parser regression for one missing-math assignment alongside a valid
  assignment in the same event.
- [x] Official `semantic/01605` passes conversion, SBML write/reimport,
  native-reader checks, and BNG3/libRoadRunner comparison for two observables.
  Report `/private/tmp/bng3-semantic-01605-empty-assignment.json`, SHA-256
  `722d2a22a923b3d8f5f5ce721ac79986b92eda32554614c19ce94ac5ae3e6b78`.
- [x] Full Python suite: `609 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,630 passed, 293 unsupported, 0 failed,
  0 timeouts`; +1 (`semantic/01605`) with no regressions from
  `1,629/294/0/0`. Report `/private/tmp/bng3-l3v2-empty-event-assignment-full.json`,
  SHA-256 `6c538b4f75e5e0bf3e517e83ca183283723fe5280973b89cb76092c7518c2320`.
- [ ] Rerun the full curated BioModels inventory in flat and atomized modes
  against this exact source; the earlier run predates this parser change.

## Mutable parameter event priorities — 2026-09-27

- [x] Evaluate a same-time event priority from a parameter's initial value only
  when it has no assignment/rate rule and no earlier scheduled event changed
  it. Existing priority recomputation applies subsequent same-time changes.
- [x] Add a regression for mutable `k1` priority 2 versus fixed priority 2.5;
  the fixed-priority assignment executes first, then `k1` is reevaluated.
- [x] Official `semantic/01714` passes conversion, SBML write/reimport,
  native-reader checks, and BNG3/libRoadRunner 2.10.0 comparison for two
  observables (11 samples; max absolute difference `3.552713678800501e-15`).
  Report `/private/tmp/bng3-semantic-01714-parameter-priority.json`, SHA-256
  `8eb1bd98390162368f0e1f6191a135a9469c39d6a8c1ed5cd44ca1ad15211c97`.
- [x] Full Python suite: `610 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,631 passed, 292 unsupported, 0 failed,
  0 timeouts`; only `semantic/01714` gained status and no prior pass regressed.
  Report `/private/tmp/bng3-mutable-priority-full-final.json`, SHA-256
  `3b11d9f1943fbaf2965d45c82731cbe50e34da5ffc7f508f7108a6e566d8bcf8`.
- [ ] Rerun full curated BioModels flat/atomized inventory against final source.

## Compartment-volume event thresholds and action horizons — 2026-09-27

- [x] Lower a reciprocal-flux trigger for one positive concentration species
  with exact `dS/dt = k/S` dynamics only when all participating reaction
  numerators scale linearly with the species compartment volume and one event
  assigns a statically resolved, positive volume. Keep models with additional
  controllers, delays, nonlinear volume scaling, or unresolved assignments
  unsupported.
- [x] Prove the post-volume concentration jump cannot produce a second trigger
  edge within the requested horizon before lowering. Case with horizon 3 fires
  once at `t=1.705`; horizon 5 remains untranslated because a second edge can
  occur at about `t=3.888`.
- [x] Keep generated volume state consistent by emitting `setVolume` and the
  corresponding `__compartment_<name>__` parameter update. Fix continuation
  phases to pass elapsed duration rather than absolute end time, so scheduled
  event runs end at the requested simulation horizon.
- [x] Synthetic BNG3/libRoadRunner amount parity passes over the 3-unit run
  (maximum absolute difference `2.7631467560240708e-5`); the exact event
  boundary is excluded. Official cases `semantic/00945` and `semantic/00947`
  pass import/write/reimport and native-reader validation.
- [x] Full Python suite: `620 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,650 passed, 273 unsupported, 0 failed,
  0 timeouts`. Gains are `semantic/00945` and `semantic/00947`; no previously
  passing case regressed. Report `/private/tmp/bng3-volume-event-full-sbml.json`,
  SHA-256 `f42c161579b696f9f00b28fed8fdd2a88e6b70c516aa6116f493cc249b2d790b`.
  Aggregate core gate remains open.
- [x] Full curated BioModels flat/atomized inventory completed as the pre-change
  baseline on source `546897b`: `793/1,083` SBML passed, `110` unsupported,
  `7` failed, `173` timed out. Relative to the previous full report, 18
  unsupported cases and one timeout moved to pass; 6 unsupported cases timed
  out and 2 prior timeouts failed. Report
  `/private/tmp/bng3-curated-546897b-both.json`, SHA-256
  `6186337abdf6968e3e196c84f0949b8496e853e38ee781635d4edecdcc2b16b0`.
- [x] Full 1,096-record flat/atomized curated BioModels rerun on exact source
  `e53ad4244707ef071b65879204954e39da2d1e09`: `793/1,083` SBML passed, `110`
  unsupported, `5` failed, `175` timed out. No record moved to `passed`; the
  only status changes were `BIOMD0000001098` and `BIOMD0000000081`, both from
  `failed` to `timeout`, so these are not confirmed fixes. Report
  `/private/tmp/bng3-curated-e53ad42-both.json`, SHA-256
  `3a40ef03e1104a4b4248148fba9cfd7ba556b072204600236c42065f6e9b071a`.
- [x] Probe generated volume-event BNGL with BNG2 2.9.3. Parsing and network
  generation succeed; runtime aborts at `setVolume` because BNG2's
  `CompartmentList` has no `setVolume` method. Cross-engine runtime parity for
  this action is not available; BNG3/libRoadRunner parity remains the evidence.
- [x] Lower a volume change through a simple compartment assignment rule such
  as `C = fakeC`. Preserve both the alias parameter and simulator volume state;
  require one positive static assignment and reject re-entry within the run.
  Cases `semantic/00946` and `00948` now pass alongside `00945` and `00947`.
- [x] Add a bounded scalar exponential self-reset path: one undelayed event,
  proven independent exponential trajectory, trigger-state assignment, and no
  next rising edge through the configured horizon. Coupled cyclic systems
  `semantic/00400` and `00401` remain unsupported.
- [x] Full pinned SBML Test Suite on `eb528bd`: `1,652 passed, 271 unsupported,
  0 failed, 0 timeouts`. Only `semantic/00946` and `00948` moved from
  unsupported to passed; no previous passes regressed. Report
  `/private/tmp/bng3-volume-alias-full-sbml.json`, SHA-256
  `3f9e1e2cf9d22c690f114d7ffa2baa8a20613f972fe4064a4e88d7826a1db9f6`.
- [x] Full Python suite: `623 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass. Focused 3-unit BNG3/libRoadRunner parity includes
  the event firing; horizon 5 remains untranslated due to trigger re-entry.
- [x] Complete the full curated BioModels flat/atomized/libRoadRunner rerun on
  exact implementation source `eb528bd`: 793/1,083 SBML records passed, 110
  unsupported, 6 failed, and 174 timed out. Against `e53ad42`, all 793 passes
  remained passes, with no unsupported-to-pass gains or pass regressions; one
  model changed from timeout to syntax failure. This change adds no measured
  curated-model coverage. Report
  `/private/tmp/bng3-curated-eb528bd-both.json`, SHA-256
  `2e44194e3276cf901498a16537ab88f908f6d0143b8734b035c70e93f9580e05`.

## Horizon proof for conjunctive event triggers — 2026-09-27

- [x] For an AND trigger, omit only when a necessary affine or exponential
  state comparison is false at both endpoints of the requested horizon. A
  monotone trajectory then keeps that condition false throughout the run; a
  longer horizon reaching the threshold leaves the event unsupported.
- [x] Official `semantic/00933` passes round trip and BNG3/libRoadRunner
  comparison (4 observables, 11 samples, zero difference). Full pinned suite:
  `1,658 passed, 265 unsupported, 0 failed, 0 timeouts`; `00933` is the only
  gain and no prior pass regressed. Report
  `/private/tmp/bng3-conjunction-full-sbml.json`, SHA-256
  `d7f4691a7950ea2377738e1679bdd265622274f072121ea23dabebf8c68c1a3d`.
- [x] Full curated BioModels run: `794/1,083` SBML passed, 109 unsupported,
  6 failed, 174 timed out. No pass gain or regression; `BIOMD0000000081`
  varied timeout-to-failure. Report
  `/private/tmp/bng3-conjunction-biomodels-both.json`, SHA-256
  `217601693a6611da8819a797fd16290bad7c10705447bcb55fb4450d34c71440`.
- [x] Full Python suite: `625 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.

## Static assignment-rule parameters in event trajectories — 2026-09-27

- [x] Fold a parameter assignment rule into event trajectory analysis only
  when exactly one assignment rule resolves to a finite static value. Follow
  static chains with cycle detection; leave dynamic, multiply controlled, and
  cyclic rules unresolved.
- [x] Add a regression for algebraic `k2 = 2.5` in an exponential state trigger;
  event is scheduled at `1.55451774445` with delay 1. A time-dependent rule
  `k2 = time` remains untranslated.
- [x] Full pinned SBML Test Suite: `1,657 passed, 266 unsupported, 0 failed,
  0 timeouts`. Five gains: `semantic/00777`, `01169`, `01466`, `01575`, and
  `01576`; no previous pass regressed. All five pass libRoadRunner comparison,
  maximum absolute difference `9.78e-10`. Report
  `/private/tmp/bng3-algebraic-rule-final-sbml.json`, SHA-256
  `22fa93a7cb61e2d58a4cbdc34d17641c6bddaa7e73013ed1d5a00270865379cc`.
- [x] Full 1,096-record curated BioModels run: `794/1,083` SBML passed, 109
  unsupported, 5 failed, 175 timed out. `BIOMD0000000301` moved
  unsupported-to-passed in flat and atomized modes; no passing record
  regressed. `BIOMD0000001098` varied failed-to-timeout. The gained model's
  18 observables match libRoadRunner in both modes within `1.78e-15`. Report
  `/private/tmp/bng3-algebraic-rule-biomodels-both.json`, SHA-256
  `3bcabe78cc673cd9bd2d7127aafa51c6fa232c15be2246e1a4b14f4122ce3364`.
  BioModels ran before a Black-only formatting pass; implementation behavior
  did not change afterward.
- [x] Full Python suite: `624 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.

## Current-source Atomizer cross-engine refresh — 2026-09-27

- [x] Refreshed the 10-model, three-repeat benchmark on BNG3 source
  `22e5f3e`, using both flat and atomized modes. Modern BNG3 produced 60/60
  structurally matching BNG2 networks and 48/60 exact normalized rate matches.
  Legacy PyBioNetGen produced 21/60 flat structural matches and 3/60 strict
  rate matches; its atomized path produced no BNG2-parseable network in this
  cohort. BNG3 tracked source was clean; preserved offline bundle artifacts
  account for the dirty worktree marker. Report
  `/private/tmp/bng3-atomizer-cross-engine-curated-10-22e5f3e.json`, SHA-256
  `29c739acf82eb259df6157637b369738e67b067fef6c77aadc8cde2aa228de42`.
- [x] Official SBML Test Suite case `semantic/01293` runs through the modern
  BNG3 Atomizer and independent PyBioNetGen Atomizer, with both outputs checked
  by BNG3 and Perl BNG2. Modern BNG3 passes structure and rate checks in flat
  and atomized modes, all three repeats. Legacy PyBioNetGen passes both checks
  in flat mode; its atomized output fails on unresolved `fRate0`. Report
  `/private/tmp/bng3-cross-engine-01293-current.json`, SHA-256
  `e991eb4f2802d1c82046c96ec48a13c2e2bbe4dff1c74d66b8f9295c986d8002`.
- [x] Curated `BIOMD0000000414` runs 200 valid seeds per engine in each mode.
  BNG3 direct NFsim and standalone NFsim have zero run errors and matching
  ensemble means over 24 points (`worst_z=0`). Report
  `/private/tmp/bng3-atomizer-nfsim-0414-546897b-200runs.json`, SHA-256
  `0703e1999a419831085901ef2369ad739860a5cb9665e0e0dfa5c3d44bb8d443`.
- [x] Full curated 1,096-model flat/atomized BNG3/libRoadRunner run completed
  on source commit `e53ad4244707ef071b65879204954e39da2d1e09`; see the report and
  status transition analysis above.

## Scaled exponential reaction-state triggers — 2026-09-27

- [x] Lower event thresholds for a single state multiplied by a folded
  constant expression. The parser isolates a homogeneous linear state term;
  nonconstant scales, offsets, and nonlinear state terms remain unsupported.
- [x] Official SBML Test Suite case `semantic/01293` passes conversion,
  round-trip, native-reader, and libRoadRunner comparison.
- [x] Full Python suite: `619 passed, 28 skipped`; Black (`py39`), Ruff, and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,648 passed, 275 unsupported, 0 failed,
  0 timeouts`. Gain: `semantic/01293`; no previous pass regressed. Report
  `/private/tmp/bng3-scaled-trigger-full.json`, SHA-256
  `eca4a83b3bf7da176b9002a75e7d31dd6dbb9206f76749668ad1f874b3165bfc`.
  The aggregate core gate remains open on 275 unsupported cases.
- [ ] Rerun the full curated BioModels inventory against final source.

## Algebraic rules in initial event triggers — 2026-09-27

- [x] Resolve supported assignment-rule values when evaluating an event's
  initial trigger. This covers algebraic rules that safely lower to one
  assignment rule; recursive cycles and multiply controlled variables fail
  closed.
- [x] Official SBML Test Suite case `semantic/01578` passes import,
  write/reimport, native-reader, and libRoadRunner parity checks. Its observable
  matches exactly over 11 samples. Report
  `/private/tmp/bng3-semantic-01578-algebraic-initial.json`, SHA-256
  `0aaeb10984277d36333239e2e3a08a95ee5e80bd88d95f553816b6fa2c688e44`.
- [x] Full Python suite: `618 passed, 28 skipped`; Black (`py39`), Ruff, and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,647 passed, 276 unsupported, 0 failed,
  0 timeouts`. Nine gains: `semantic/00398`, `00402`-`00404`, `00455`,
  `00459`-`00461`, and `01578`; no previous passes regressed. Every gained
  case passed BNG3/libRoadRunner comparison. Report
  `/private/tmp/bng3-algebraic-initial-full.json`, SHA-256
  `4c008f381b48d4a171427bae13eee26a4a562dd4e28ce39dca62355c056aaba3`.
  The aggregate core gate remains open on 276 unsupported cases.
- [ ] Rerun the full curated BioModels inventory against final source.

## Delayed event assignment-rule values — 2026-09-27

- [x] Evaluate a supported assignment rule from proven event-time trajectories
  when folding delayed event assignment values. Reject dependencies controlled
  by another event or otherwise lacking an exact trajectory; preserve the
  existing stricter behavior for simultaneous-priority evaluation.
- [x] Official `semantic/01579` passes conversion, write/reimport, and native
  reader checks. At the suite's one-unit horizon, all three observables match
  libRoadRunner 2.10.0 exactly over 11 samples. With a 10-unit, 100-step
  comparison that includes the delayed assignment at t=6.5, the same observables
  match over 101 samples with maximum absolute difference
  `1.7763568394002505e-15`. Reports:
  `/private/tmp/bng3-semantic-01579-assignment-rule.json`, SHA-256
  `ca8bf8edbc0741bd52a4d0944f9c4d2baa797e6f6c962085e06be004c0b68e03`; and
  `/private/tmp/bng3-semantic-01579-assignment-rule-t10.json`, SHA-256
  `d73b317ed5e5c8abbdfd2a99172057216be3f2975e776b766f1df5efc83b07df`.
- [x] Full Python suite: `617 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,638 passed, 285 unsupported, 0 failed,
  0 timeouts`; `semantic/01579` gained status, with no prior pass regressed.
  Report `/private/tmp/bng3-assignment-rule-events-full.json`, SHA-256
  `74a9e48ff491f3b7161f68bab7d8fd0c9fc78136eb4e294dab2f8b8eb22ad940`.
  Supported-surface gate passes; aggregate core gate remains open.
- [ ] Full curated BioModels rerun is still required. An earlier run on commit
  `a8479a9` was interrupted after roughly 112 of 1,096 models to keep its
  results from mixing source revisions; it produced no complete report.

## Delayed affine state-reset events — 2026-09-27

- [x] Schedule a self-reset event over a proven affine state trajectory, including
  delayed execution, trigger-time versus execution-time assignment values, and
  repeated crossings. If the first delayed state change is beyond the requested
  horizon, omit the event from that run; retain recurrence scheduling when it
  falls within the horizon.
- [x] Official `semantic/01701` and `semantic/01702` convert, roundtrip, and
  match libRoadRunner 2.10.0 at the one-unit horizon. Both have no observable
  state change before the delayed reset at t=3.1 (11 samples, one observable,
  max absolute difference `1.7763568394002505e-15` each). Reports:
  `/private/tmp/bng3-semantic-01701-final.json`, SHA-256
  `740610e5f19c64b2c85bc0ae9859a201141e56ac395e4924be5bc261010942ef`; and
  `/private/tmp/bng3-semantic-01702-final.json`, SHA-256
  `24120587b3a86d0178e7b0f393b4fe04dd729d16781629094807925dab5b44d7`.
- [x] Seven focused event/parity regressions pass; full Python suite:
  `616 passed, 28 skipped`. Black (`py39`), Ruff, and `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,637 passed, 286 unsupported, 0 failed,
  0 timeouts`; gains are `semantic/01689`, `01692`, `01701`, and `01702`, with
  no prior pass regressed. Report
  `/private/tmp/bng3-affine-state-reset-final.json`, SHA-256
  `95ab59783cef4bb63bc640d514b3c198cd44a80566e0591cc6b61126637bfcfc`.
  The supported-surface gate passes; aggregate core gate remains open due to
  the 286 remaining unsupported cases.
- [ ] Rerun the full curated BioModels flat/atomized inventory against the
  finalized implementation.

## Static parameter event edges — 2026-09-27

- [x] Omit a parameter-only event proven unable to fire: its initial predicate
  is false, the trigger contains only parameters with resolved initial values,
  and no rule or other event can change those values. Keep events with another
  potential writer unsupported.
- [x] Lower the time-zero rising edge when `triggerInitialValue=false` and a
  constant parameter predicate is already true. Preserve the trigger snapshot
  and delay; do not treat time-dependent triggers as static.
- [x] Official `semantic/01712` and `semantic/01713` pass conversion, SBML
  write/reimport, native-reader checks, and BNG3/libRoadRunner 2.10.0 comparison
  for two observables each (11 samples; max absolute difference
  `3.552713678800501e-15`). Reports:
  `/private/tmp/bng3-semantic-01712-inactive-events.json`, SHA-256
  `7241ad52ae8beb553495f0255f126bf1650d8f349d6ce93ca77f24b2753332b0`; and
  `/private/tmp/bng3-semantic-01713-initial-trigger.json`, SHA-256
  `ac3884f260842545ed303af2a6b8dd85afb82dfdb5cec767ce04cdcd5d4339a5`.
- [x] Full Python suite: `613 passed, 28 skipped`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,633 passed, 290 unsupported, 0 failed,
  0 timeouts`; only `semantic/01712` and `01713` gained status and no prior
  pass regressed. Report `/private/tmp/bng3-inactive-event-full.json`, SHA-256
  `d073c2068e2c416098cc42875bc5176f2445bc2c55826d615b32d5de603571a6`.
- [ ] Rerun full curated BioModels flat/atomized inventory against final source.

## Independent state-trigger events in separate reaction components — 2026-09-27

- [x] Scope quadratic event trajectory proofs to the symbols read by the
  active trigger, reaction component, and compartment. Ignore another event's
  assignments only when they cannot change those values; retain the
  unsupported path for kinetic coupling or shared active state.
- [x] Add a regression with two reversible first-order components and delayed
  events in each. Both scheduled assignments execute, and all four species
  match libRoadRunner away from the action boundaries.
- [x] Pinned SBML Test Suite cases `semantic/00847`, `00850`, `01047`, and
  `01050` pass their full per-record gates. All observables pass BNG3/
  libRoadRunner comparison (maximum absolute difference `4.84e-12`).
- [x] Focused quadratic-event regressions: `8 passed`; full Python suite:
  `641 passed, 28 skipped`. Ruff, Black (`py39`), and `git diff --check` pass.
- [x] Full pinned SBML Test Suite: `1,641 passed, 282 unsupported, 0 failed,
  0 timeouts`, four gains (`00847`, `00850`, `01047`, `01050`) and no
  regressions versus `1,637/286/0/0`. Report
  `/private/tmp/bng3-independent-events-full-sbml.json`, SHA-256
  `7a707af67afce91b4bc9808b9738cad41ee32dbf9065df48c11dfdae81cc2b93`.
  Aggregate core support remains incomplete.
- [x] Full offline flat/atomized curated BioModels inventory: `792/1,083` SBML
  records passed, `109` unsupported, `5` failed, and `177` timed out across
  `1,096` inventory records. Every record retained its prior status; this
  change produced no confirmed curated-model gains or regressions. Report
  `/private/tmp/bng3-independent-events-biomodels-both.json`, SHA-256
  `e34738f57db500da19fe2f28618c0772c729c4ae36fda5452f8a68dd8747d9c5`.
  The aggregate curated-model gates remain incomplete.

## Re-entrant events in closed first-order cycles — 2026-09-27

- [x] Add an exact trajectory resolver for a closed three-species,
  three-reaction first-order transfer cycle. Admit only positive constant
  rates, unit stoichiometry, one fixed positive compartment, and models with
  no rules, initial assignments, or conversion factors; reject unsupported
  topologies and kinetic laws.
- [x] Schedule one persistent, unprioritized state-threshold event across
  repeated rising and falling crossings, with constant nonnegative delay and
  trigger-time species snapshots. Recompute the trajectory after event
  assignments. SSA, non-snapshot events, and inclusive threshold tangencies
  remain unsupported.
- [x] Add parity coverage for immediate and delayed events, two and three
  simultaneous species assignments, and both real and complex cycle spectra.
  The inclusive-tangency regression verifies that the event is left
  untranslated instead of being incorrectly proved inactive.
- [x] Refresh official SBML Test Suite cases `semantic/00400`, `00401`,
  `00457`, and `00458` individually at `t_end=20` with 1,200 steps. Every
  record passes conversion, XML roundtrip, native-reader, and direct
  BNG3/libRoadRunner CVODE comparison for six observables; the maximum
  absolute difference is `3.0815350271495845e-12`. Isolated reports do not
  establish the aggregate suite gates or SBML reference-result conformance:
  `00400` `/private/tmp/bng3-first-order-cycle-00400-verified.json`, SHA-256
  `28bdfadb54c58595eb499aa9fb0d9cbd7d6f1dadc93b5e36a4ad768b5a70b051`;
  `00401` `/private/tmp/bng3-first-order-cycle-00401-verified.json`, SHA-256
  `f9c5799a5ffdd5fc3e4463223ad968803a076c925f6d66e5ea98eed37c33e114`;
  `00457` `/private/tmp/bng3-first-order-cycle-00457-verified.json`, SHA-256
  `acff7790d1ba842b5e3877fefac963376d92ef268ee22ec27e14f779435a0170`;
  and `00458` `/private/tmp/bng3-first-order-cycle-00458-verified.json`,
  SHA-256 `f8abb23225d81017a38710cd873a1fb54259a21fe21941d76a5281a3273a55a1`.
- [x] Focused event suite: `61 passed`; SBML parity module: `86 passed`; full
  Python suite: `644 passed, 28 skipped`. Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Full pinned SBML Test Suite at suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, and 10 samples:
  `1,645 passed, 278 unsupported, 0 failed, 0 timed out`. The supported-surface
  gate passes; the aggregate core gate remains open. Against the saved
  `1,673 passed, 250 unsupported` report, 27 semantic cases gained status,
  including these four cycle cases. Fifty-five prior stochastic passes became
  unsupported when the runner began selecting SSA for stochastic-category
  records; the validation-method change makes the aggregate counts
  non-comparable as a direct regression total. Reference-result conformance
  was not run. Report `/private/tmp/bng3-first-order-cycle-full-verified.json`,
  SHA-256 `4440ab3e496b8f6027d156ab176f16067d49e241c2e1224889d9bdd0b8c8c7cd`.
- [ ] Rerun the complete curated BioModels inventory against this source.

## Delayed quadratic state events with trigger-time snapshots — 2026-09-27

- [x] Schedule a constant nonnegative delay for re-entrant events whose
  trigger has a proven scalar quadratic trajectory. Support only persistent
  triggers with trigger-time assignment snapshots; recompute the trajectory
  after each action. Other delay expressions and state-triggered SSA remain
  unsupported.
- [x] Add a libRoadRunner parity regression for repeated delayed crossings.
  The focused Atomizer suite passes `406` tests with `1` skipped; Ruff, Black
  (`py39`), and `git diff --check` pass.
- [x] Full pinned SBML Test Suite at suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, and 10 samples:
  `1,661 passed, 262 unsupported, 0 failed, 0 timed out`. Sixteen semantic
  cases gained status and no previous pass regressed:
  `00407`, `00410`, `00415`, `00416`, `00423`, `00424`, `00425`, `00428`,
  `00431`, `00438`, `00439`, `00440`, `00452`, `00456`, `00765`, and `00768`.
  The supported-surface gate passes; the aggregate core gate remains open.
  Reference-result conformance was not run. Report
  `/private/tmp/bng3-delayed-quadratic-full-current.json`, SHA-256
  `2192db808c6c01f0bb6549a2726cf151b0d997783ddb163abbe112cfc509cddc`.
- [x] All 16 gained records pass individual conversion, XML roundtrip,
  native-reader, and BNG3/libRoadRunner checks through `t=20` with 1,200
  samples. The maximum absolute errors range from
  `1.2040992016665048e-11` to `9.517548000825826e-07`. Cohort summary:
  `/private/tmp/bng3-delayed-quadratic-t20-cohort-summary.json`, SHA-256
  `41735803f4cde719fc84979f343fa3459c8307ba2311112c019c16c2bf72e328`.
- [x] Keep `semantic/00451` and `01076` unsupported: their
  `stoichiometryMath` is carried through generated initial-assignment metadata
  and is outside this resolver's proof.
- [ ] The full Python suite did not complete after concurrent NFsim changes
  were present; it remained CPU-bound in `tests/python/test_cpp_backend.py`
  until stopped. The 406-test Atomizer result above is the completed Python
  validation for this slice.
- [ ] Rerun the full curated BioModels inventory against the finalized source.

## Quadratic state events with species initial assignments — 2026-09-27

- [x] Resolve finite, acyclic species initial assignments when constructing
  the event trajectory at simulation start. Reject duplicate, cyclic,
  unresolved, and non-species targets. In particular, species-reference
  stoichiometry and other non-species initial assignments remain unsupported.
  This follows SBML's definition that initial assignments set values through
  `t=0` ([SBML Level 3 Version 2 Core, §4.8](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf)).
- [x] Add a libRoadRunner parity regression where the declared initial amount
  differs from the value produced by an initial assignment. Focused Atomizer
  suite: `407 passed, 1 skipped`; Ruff, Black (`py39`), and `git diff --check`
  pass.
- [x] Full pinned SBML Test Suite at suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, and 10 samples:
  `1,670 passed, 253 unsupported, 0 failed, 0 timed out`. Nine cases gained
  status and no previous pass regressed: `semantic/00754`, `00755`, `00756`,
  `00771`, `00772`, `00773`, `00789`, `00790`, and `00791`. The supported
  surface passes; the aggregate core gate remains open. Reference-result
  conformance was not run. Report
  `/private/tmp/bng3-initial-assignment-full-verified.json`, SHA-256
  `f284d39ad69146fb4eac0900c17a5fd8ace7ff1e3804124efba89646238b4079`.
- [x] All nine gained cases pass individual conversion, XML roundtrip,
  native-reader, and BNG3/libRoadRunner CVODE checks at `t=20` with 1,200
  steps and six observables per case. Maximum absolute difference across all
  observables is `5.771522149089492e-11`. Cohort summary:
  `/private/tmp/bng3-initial-assignment-t20-cohort-summary.json`, SHA-256
  `0bb7125da7e15d31603d6be74ff54dca53f49375c03e9db3066a6c419c458c56`.
- [ ] The full Python suite remains incomplete: its earlier run stalled in
  `tests/python/test_cpp_backend.py` while concurrent NFsim changes were
  present. Focused Atomizer tests above completed for this slice.
- [ ] Rerun the full curated BioModels inventory against the finalized source.

## Affine parameter event priorities — 2026-09-27

- [x] Lower parameter-only events whose trigger crosses a direct threshold on
  a parameter with an independent constant-slope rate rule. Evaluate
  simultaneous priority expressions at execution time, support affine
  `delay(parameter, duration)` history in priorities, and reevaluate remaining
  priorities after each event action. Events that update a rate-rule target or
  change one of its slope dependencies remain unsupported. Priority evaluation
  and reevaluation follow [SBML Level 3 Version 2 Core, §4.12.3](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf).
- [x] Add a regression for two simultaneous assignments where the history-based
  priority is lower than a constant priority. A third event reads a parameter
  that the first action changes, verifying that the remaining priorities are
  reevaluated. Focused Atomizer suite: `408 passed, 1 skipped`; Ruff, Black
  (`py39`), and `git diff --check` pass.
- [x] Official SBML Test Suite `semantic/01521` passes conversion, XML
  roundtrip, native-reader, and BNG3/libRoadRunner CVODE checks at `t=20` with
  1,200 steps. `P1_amt` maximum absolute difference is
  `1.0658141036401503e-14`. Report
  `/private/tmp/bng3-affine-priority-semantic-01521-final.json`, SHA-256
  `99e04bf231791d5816e14c95bf64710d04faa942f433ba6eed944f951321a72e`.
- [x] Full pinned SBML Test Suite at suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, and 10 samples:
  `1,671 passed, 252 unsupported, 0 failed, 0 timed out`. Only
  `semantic/01521` gained status versus the preceding full report; no prior
  pass regressed. The supported surface passes; the aggregate core gate remains
  open. Reference-result conformance was not run. Report
  `/private/tmp/bng3-affine-priority-full-sbml.json`, SHA-256
  `670702b064bf4d764b2c431cc571e2fb21f62ae33d913d6c83264dca997a53e6`.
- [ ] Full curated BioModels inventory rerun against this source is pending.

## Simultaneous state-gated event priorities — 2026-09-27

- [x] Lower a same-trigger, zero-delay event group whose state gate is proven
  static, with constant priorities. After each assignment, cancel pending
  nonpersistent events whose trigger has become false; keep persistent events
  scheduled. The narrow proof excludes reactions, rules, and initial
  assignments through `static_event_state`.
- [x] Add a regression reduced from official SBML Test Suite
  `semantic/00935`. Priority-10 event A clears the gate, nonpersistent
  priority-8 event B is canceled, and persistent priority-9 event C1 executes.
  The emitted assignments leave `S1=3`, `S2=2` at `t=1`, matching the official
  51-row reference output. Direct libRoadRunner comparison to that reference
  has maximum absolute difference `2.220446049250313e-16`.
- [x] Focused event/parity tests: `153 passed`; Ruff, Black (`py39`), and
  `git diff --check` pass. The exact SSTS source translates to the expected
  A-then-C1 action sequence. Regressions also drop a false static gate and
  keep the initial-state shortcut closed across distinct event edges.
- [ ] Refresh the full pinned SBML Test Suite aggregate and run the native
  BNG3 case check after the local C++ extension loads successfully. The
  existing extension currently fails to load because `NFcore2::simulateNfcore2`
  is unresolved; the latest complete aggregate remains the affine-priority
  report above.
- [ ] Re-run the full curated BioModels inventory after the extension issue is
  resolved. The latest attempted run did not produce usable aggregate results.

## Re-entrant first-order transfer event systems — 2026-09-27

- [x] Lower the bounded two-species, one-reaction source-to-sink case with a
  constant positive rate, fixed positive volume, and two persistent,
  no-priority triggers (`source < threshold`, `sink > threshold`). Zero or
  compile-time constant nonnegative delays are supported. Assignments use
  trigger-time state; delayed assignments execute after analytically advancing
  the transfer state to their due time. Compatible simultaneous sets are
  grouped, then future crossings are recomputed. Dynamic delays, SSA, rules,
  initial assignments, and other trigger/assignment shapes remain unsupported;
  ambiguous simultaneous crossings and due actions fail closed.
- [x] Continued action phases now carry explicit absolute `t_start` and
  `t_end`, retaining phase times in Perl BNG2 as well as the current BNG3
  action path. Perl BNG2 2.9.3 ran the exact official SSTS
  `semantic/00041` model to `t=5` with six event actions and no continuation
  time warnings. Against its official final reference row, the maximum
  absolute difference for `S1` and `S2` is `1.652592283019061e-7`.
- [x] Perl BNG2 2.9.3 ran the delayed official SSTS `semantic/00072` model to
  `t=5` with three event assignments and 51 output rows. Its final `S1` and
  `S2` values differ from the official reference row by at most
  `9.394649663763133e-8`. The sandboxed process discovery printed a `ps`
  permission warning; the run exited successfully without continuation-time
  warnings. This is a final-row comparison only; phase splitting changes the
  output timestamps, so full parity at the official sampling grid remains
  unverified.
- [x] Targeted Atomizer Python suite: `434 passed, 3 skipped`; Ruff, Black
  (`py39`), and `git diff --check` pass.
- [ ] Native BNG3 validation and refreshed full SSTS/BioModels aggregates were
  not part of this slice. The last recorded native extension attempt failed on
  unresolved `NFcore2::simulateNfcore2`; that result has not been rechecked
  against the concurrent C++ worktree state.

## Shared quadratic multi-event triggers — 2026-09-27

- [x] Lower the bounded group of two or more deterministic, persistent,
  initially false state triggers that each compare one species with a strict
  threshold. Triggers and assignments must share a proven quadratic reaction
  component; events have no delay or priority and use values from trigger
  time. The scheduler tracks trigger entries and exits, snapshots each
  assignment at its firing time, and recomputes the coupled trajectory after
  every firing. Constant inactive boundary-species triggers can be proven
  inactive. Other event shapes, delayed or prioritized actions, and ambiguous
  simultaneous or assignment-induced transitions remain untranslated.
- [x] Add source-derived parity regressions for official SBML Test Suite
  `semantic/00349` and `00884`, boundary-species assignments, constant
  inactive boundary triggers (`00379` and `00380`), and simultaneous crossings
  that must remain unsupported. The focused event/parity suites pass:
  `162 passed`. Ruff, Black (`py39`), and `git diff --check` pass.
- [x] All seven official cohort records `semantic/00349`, `00363`, `00378`,
  `00379`, `00380`, `00744`, and `00884` pass isolated SBML roundtrip and
  BNG3/libRoadRunner CVODE comparison with six observables each. At `t_end=2`
  with 50 samples, maximum absolute differences range from `3.55e-12` to
  `9.51e-7`, within configured tolerances. These are cross-engine comparisons,
  not official reference-result conformance.
- [x] Full pinned SBML Test Suite at commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, and 10 samples:
  `1,687 passed, 236 unsupported, 0 failed, 0 timed out`; the supported
  surface passes, while the aggregate core gate remains open. Compared with
  `/private/tmp/bng3-quadratic-reentrant-full-sbml.json`, 69 cases gained and
  55 lost status. The 55 losses are stochastic-category models whose events
  remain untranslated; this status change is outside the seven-case target
  cohort and is not attributed to this feature. Report
  `/private/tmp/bng3-quadratic-multievent-full-sbml-after-zero-entry.json`, SHA-256
  `4362668167e21c2cdf941d385a831ddc63f7183a3b8dc4358b09aef22c4679d8`.
- [ ] Full curated BioModels inventory and official SBML reference-result
  conformance have not been rerun for this slice.

## Initial-time event entries and legacy copy regressions — 2026-09-27

- [x] A supported quadratic trigger whose initial value equals its strict
  threshold now schedules its false-to-true entry at time zero. A regression
  compares positive-time BNG3 and libRoadRunner trajectories; a simultaneous
  initial entry remains explicitly unsupported. This follows the
  [SBML event trigger semantics](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf).
  BNG3 records the event-updated state at time zero, so the parity assertion
  compares subsequent sample times.
- [x] Reviewed merged Atomizer PRs #22, #23, and #24. The modern structure copy
  path from #22 preserves its fields. In the legacy `utils/structures.py` and
  `utils/smallStructures.py` paths, `Component.copy()` passed states and bonds
  to constructors that discarded both lists. The copies now assign independent
  lists explicitly. Molecule copies use shallow object copies before replacing
  the nested component list, avoiding throwaway random hash-array and identifier
  generation while preserving metadata.
- [x] Added four focused copy regressions covering both legacy Component
  implementations, nested molecule copies, metadata, and constructor side
  effects. The full Atomizer-focused Python suite (`test_*atomizer*.py` and
  `test_smallStructures.py`) passes: `436 passed, 3 skipped`. Ruff, Black
  (`py39`), and `git diff --check` pass.
- [x] The complete pinned SSTS run after the time-zero event fix remains at
  `1,687 passed, 236 unsupported, 0 failed, 0 timed out`; supported surface
  passes and the core gate remains open. Report hash is unchanged at
  `4362668167e21c2cdf941d385a831ddc63f7183a3b8dc4358b09aef22c4679d8`.
- [ ] Full Python suite was last run after the event fix and before the legacy
  copy repair: `654 passed, 30 skipped, 1 failed`. The failure was
  `tests/python/test_cli.py::test_cli_nf_honors_nonzero_start_time` (`CaughtSignal`)
  in the concurrent NFsim area. The repaired copy paths have targeted coverage;
  the full suite has not been rerun on this exact worktree state.
- [ ] Current-source curated BioModels flat/atomized rerun was stopped at the
  user's request. `/private/tmp/bng3-quadratic-multievent-biomodels-both.json`
  has no aggregate report. Official reference-result conformance is separate
  and unverified; do not restart the run without a new request.

## Quadratic state events in parameter rate-rule systems — 2026-09-28

- [x] Extend the exact quadratic state-event path to models with no species or
  reactions when every mutable parameter has a rate rule and all rate-rule
  vector fields are proportional quadratic polynomials. The proportionality
  check proves one shared state coordinate. Constant nonnegative delays are
  supported for persistent events that use trigger-time values; priorities and
  unsupported rule shapes remain untranslated.
- [x] Add source-derived parity coverage for the undelayed one- and two-event
  forms (`semantic/00396`, `00397`) and delayed one- and two-event forms
  (`semantic/00453`, `00454`). All four BNG3 rate-rule state trajectories
  match libRoadRunner between event jumps; tests also verify expected reset
  counts. The Atomizer-focused Python suite passes: `440 passed, 3 skipped`.
  Ruff, Black (`py39`), and `git diff --check` pass.
- [x] Isolated current-source SSTS round-trip: all four cohort cases passed
  without unsupported cases. Their report records are
  `/private/tmp/bng3-quadratic-rate-rule-00396-final.json` and
  `/private/tmp/bng3-quadratic-rate-rule-00397-final.json`,
  `/private/tmp/bng3-quadratic-rate-rule-00453-final.json`, and
  `/private/tmp/bng3-quadratic-rate-rule-00454-final.json`.
- [x] Full pinned SSTS run at commit `cf38585fac5de8e0e90112febb62851ee2181816`,
  `t_end=1`, 10 samples: `1,691 passed, 232 unsupported, 0 failed, 0 timed out`.
  Compared with `/private/tmp/bng3-quadratic-multievent-full-sbml-after-zero-entry.json`,
  the exact case comparison shows four gains (`00396`, `00397`, `00453`,
  `00454`) and no losses. Supported surface passes; aggregate Core gate remains
  open. Report `/private/tmp/bng3-quadratic-rate-rule-full-sbml.json`, SHA-256
  `53d15a4b458b1889c6e50d74a974271614cb3650a06b336dad751108a1684d11`.
- [ ] The earlier curated BioModels run was stopped at the user's request;
  `/private/tmp/bng3-quadratic-multievent-biomodels-both.json` has no aggregate
  report and must not be restarted without a new request.

## Delayed quadratic multi-event triggers — 2026-09-28

- [x] Extend shared quadratic reaction-event scheduling to support independent
  finite compile-time delays for persistent, trigger-time-valued assignments.
  Trigger entries enqueue assignment snapshots; the exact quadratic trajectory
  continues until each execution time, then assignments are applied and the
  coupled trajectory is resolved again. Simultaneous executions and ties with
  another trigger crossing remain untranslated because priority is absent.
- [x] Add an oracle-grounded reaction-model regression with two distinct delays
  and a state-valued assignment. BNG3 state trajectories match libRoadRunner
  away from event jumps. The focused event/parity suite passes: `167 passed`;
  Ruff, Black (`py39`), and `git diff --check` pass.
- [x] Pinned SSTS full run at commit `cf38585fac5de8e0e90112febb62851ee2181816`,
  `t_end=1`, 10 samples: `1,706 passed, 217 unsupported, 0 failed, 0 timed out`.
  Compared with `/private/tmp/bng3-quadratic-rate-rule-full-sbml.json`, 15 cases
  gained and none lost: `00406`, `00413`, `00414`, `00420`, `00421`, `00422`,
  `00427`, `00435`, `00436`, `00437`, `00442`, `00757`, `00764`, `00774`,
  `00776`. Supported surface passes; aggregate Core gate remains open. Report
  `/private/tmp/bng3-quadratic-multievent-delayed-full-sbml.json`, SHA-256
  `24d9e64d03ef4aa7f873783db1425964adf4ddc1f521ce7ad533ac9d3cfdf23a`.
- [x] The next slice below adds species-to-species triggers to the same proven
  quadratic cohort. Curated BioModels validation remains unverified and stays
  stopped per user request.

## NF CLI start-time regression test cost — 2026-09-28

- [x] Replace the CLI smoke test's 5,500-molecule `simple_system.bngl` input
  with a minimal birth model and assert the emitted sample-time column is
  `[1.0, 2.0]`. This keeps CLI forwarding coverage while avoiding the large
  network-free workload. The isolated test passes in `0.03s`; all 16 CLI tests
  pass (3 existing Cement deprecation warnings).
- [x] The preceding full Python run ended after `19:20` with `665 passed`,
  `30 skipped`, and one `CaughtSignal` failure in the old large-fixture CLI
  test. After reducing the fixture, full `pytest -q` passes: `668 passed`,
  `30 skipped` in `11.36s` (1,380 existing deprecation warnings).

## Species-difference triggers in delayed quadratic groups — 2026-09-28

- [x] Support strict comparisons between two species in delayed, persistent,
  unprioritized multi-event groups when both species resolve on the same proven
  quadratic reaction coordinate. The difference is checked against an affine
  state projection before crossing times are scheduled; unsupported projections
  and non-rank-one reaction groups remain untranslated.
- [x] Add an SBML-derived two-delay regression for `S4 > S2`, compare all four
  species against libRoadRunner away from jumps, and add a non-proportional
  stoichiometry case that must remain untranslated. The combined event, parity,
  and CLI suites pass: `185 passed`; Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Pinned SSTS full run at commit `cf38585fac5de8e0e90112febb62851ee2181816`,
  `t_end=1`, 10 samples: `1,721 passed, 202 unsupported, 0 failed, 0 timed out`.
  Compared with `/private/tmp/bng3-quadratic-multievent-delayed-full-sbml.json`,
  15 cases gained and none lost: `00352`, `00373`, `00390`–`00392`, `00409`,
  `00430`, `00447`–`00449`, `00747`, `00767`, `00775`, `01072`, `01075`.
  Supported surface passes; aggregate Core gate remains open. Report
  `/private/tmp/bng3-quadratic-species-difference-full-sbml.json`, SHA-256
  `0f9e748655b9e1809de03099cb2144ce5bd23ea3f5a214a9b2258444e6a07f4d`.
- [x] Independent legacy BNG2 2.9.3 executed the BNG3 Atomizer-generated BNGL
  for the delayed species-difference fixture. The BNG3 and BNG2 `.gdat` files
  each contain 801 rows with matching output columns, event rows, and time grid
  (maximum time difference `1.0e-12`). With both engines set to `rtol=1e-8` and
  `atol=1e-8`, the largest species difference away from event jumps is
  `5.1e-15`. At BNG3's default `atol=1e-12`, the maximum difference was
  `4.6e-8`, consistent with the looser absolute tolerance used by BNG2.
  This is a single-model execution comparison of BNG3-generated BNGL. It does
  not benchmark BNG2 Atomizer, establish BNG2 Atomizer completeness, or measure
  BNG2 Atomizer against all SBML or the full SBML Test Suite. BNG2 Atomizer is
  incomplete; full SBML-wide cross-engine benchmark coverage remains open.
- [x] Full repository `pytest -q` passes after the CLI fixture reduction:
  `668 passed`, `30 skipped` in `11.36s` (1,380 existing deprecation
  warnings). Curated BioModels validation remains stopped.

## State-event updates to parameter-backed stoichiometry — 2026-09-28

- [x] Support the pinned SBML Test Suite `semantic/00991` form: a rising
  species threshold changes a parameter used by a variable reaction
  stoichiometry. The event crossing time is derived from the proven
  pre-event constant flux; generated `TotalRate` math keeps the event-updated
  parameter live so the post-event trajectory uses the new coefficient.
- [x] Add a regression copied from the official model and compare BNG3 ODE
  output against libRoadRunner. The focused Atomizer event/parity tests pass
  (`170 passed`); the full Python suite passes (`671 passed, 28 skipped`,
  1,380 existing warnings). A prior test run caught an existing
  event-controlled species-reference case that this change initially
  regressed; the assignment-rule stoichiometry path is preserved and the
  complete focused suite now passes.
- [x] Current-source isolated SSTS record `semantic/00991` passes at
  `t_end=2`, 20 intervals, with BNG3 and libRoadRunner trajectories matching
  exactly at all 21 samples. Report `/private/tmp/bng3-ssts-00991-after.json`,
  SHA-256 `6dea1f18e08b66541da6c75d837aed8af879e3110fa9ce6d1be22a6c53ac42e8`.
  This is one targeted record; aggregate full-SBML counts were not rerun.
- [ ] This does not benchmark BNG2 Atomizer, establish its completeness, or
  benchmark BNG2 Atomizer against all SBML. BNG2 Atomizer is incomplete; full
  SBML-wide cross-engine coverage remains open. Curated BioModels validation
  remains stopped per the user's instruction.

## Direct species-reference event stoichiometry — 2026-09-28

- [x] Support Level 3 event assignments that change a reaction's variable
  species-reference stoichiometry. The reference's initial value is emitted as
  a live BNGL parameter; a proven pre-event affine trajectory schedules the
  crossing; the post-event `TotalRate` expression reads the updated reference.
  Regression compares the full trajectory against libRoadRunner.
- [x] Focused Atomizer event/parity tests pass (`171 passed`). Full Python
  suite passes (`672 passed, 28 skipped`, 1,380 existing warnings). Ruff,
  Black (`py39`), and `git diff --check` pass.
- [x] Seven selected SSTS event/stoichiometry records pass at extended
  horizons: `00972` (`t_end=10`), `00991` (`t_end=2`), and `01444`–`01448`
  (`t_end=10`). Each BNG3 trajectory matches libRoadRunner at sampled points;
  maximum absolute differences are at most `3.56e-15`.
- [x] Full pinned SSTS run at commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, 10 samples:
  `1,730 passed, 193 unsupported, 0 failed, 0 timed out`. Exact comparison
  with `/private/tmp/bng3-quadratic-species-difference-full-sbml.json`
  (`1,721 passed, 202 unsupported`) shows nine gains and no losses:
  `00972`, `00991`, `01444`–`01448`, `01536`, `01583`. The supported surface
  passes; the aggregate Core gate remains open. Report
  `/private/tmp/bng3-atomizer-event-stoich-full-sbml.json`, SHA-256
  `509692d123cca41f13084a005b64a73876d56750b156ed4acd3ca2de48d54dd3`.
- [ ] This is BNG3-to-libRoadRunner SSTS evidence. It does not benchmark
  BNG2 Atomizer, prove BNG2 Atomizer complete, or benchmark it against all
  SBML. BNG2 Atomizer remains incomplete; full cross-engine coverage remains
  open. Curated BioModels validation remains stopped per the user's request.

## Persistent delayed first-order chain state event — 2026-09-28

- [x] Extend the proven irreversible first-order three-species chain scheduler
  to one constant terminal-species assignment after a folded nonnegative delay,
  including static initial assignments whose targets are chain species and
  whose values resolve to finite numbers. Other initial-assignment targets,
  nonpersistent delayed events, and priorities remain unsupported. The chain
  trajectory advances analytically from threshold crossing to execution time.
- [x] Add a regression asserting the event fires at the analytic crossing plus
  its 4.3 time-unit delay with a static source initial assignment. Focused event
  and SBML parity suites pass (`175 passed`); full Python suite passes (`676
  passed, 28 skipped`, 1,380 existing warnings). Ruff, Black (`py39`), and
  `git diff --check` pass.
- [x] Pinned SSTS cases `semantic/00665` (`t_end=10`), `00666` (`t_end=40`),
  `00778` (`t_end=10`), `00779` (`t_end=20`), and `00780` (`t_end=15`), each
  with 50 intervals, pass against libRoadRunner 2.10.0. All seven observables
  pass all 51 samples; maximum absolute differences are respectively
  `2.36e-12`, `0`, `2.36e-12`, `2.68e-12`, and `2.72e-12`. Each is a selected
  one-case report, so its runner exit code is 1 due to incomplete aggregate
  Core status; every selected case status is `passed`.
- [x] Full pinned SSTS run at suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, 10 samples:
  `1,738 passed, 185 unsupported, 0 failed, 0 timed out`. Exact comparison
  with `/private/tmp/bng3-atomizer-event-stoich-full-sbml.json`
  (`1,730 passed, 193 unsupported`) shows eight gains and no losses:
  `00661`, `00662`, `00665`, `00666`, `00760`, and `00778`–`00780`. Report
  `/private/tmp/bng3-delayed-chain-initial-assignment-full-sbml.json`, SHA-256
  `f539a2aeb8de9353ffc2e68957829007accfd867c9c79a0ad4d0cd8022062c60`.
  Supported surface passes; aggregate Core gate remains open.
- [x] Perl BNG2 2.9.3 and native BNG3 both execute the same tolerance-annotated
  BNGL emitted by the BNG3 modern Atomizer for `semantic/00778`. Their networks
  match at 3 species and 2 reactions. On the identical 51-point time grid, all
  six species observables match with `atol=rtol=1e-8`; maximum absolute
  difference is `1.01e-13`. BNG2 returned zero and wrote `.cdat`/`.gdat`; two
  stderr notices report sandbox-blocked `ps` discovery. Report and hashed
  `.bngl`, `.net`, `.gdat`, `.cdat`, and logs:
  `/private/tmp/bng3-bng2-00778-parity-ov_fig51/report.json`, SHA-256
  `59e2ee8dc7a84b15fee537291b4f19a7611c7fc4346c79b024ca23ade7f37873`.
  This is BNG2 engine execution of BNG3-generated BNGL; it does not benchmark
  BNG2 Atomizer or establish its completeness or all-SBML coverage.
- [ ] This selected BNG3 SSTS comparison does not benchmark BNG2 Atomizer or
  establish BNG2 Atomizer completeness. BNG2 Atomizer remains incomplete and
  has not been benchmarked against all SBML. Full cross-engine coverage remains
  open; curated BioModels validation remains stopped per the user's request.

## Required SBML Distrib symbols in recurring stochastic events — 2026-09-28

- [x] The parser now counts package `csymbol` definition URLs such as
  `http://www.sbml.org/sbml/symbols/distrib/normal` when diagnosing declared
  SBML packages. This fixes a false `distrib` “contains no package elements;
  core kinetic model is unaffected” message: distribution functions are
  MathML symbols, not elements in the package namespace.
- [x] The official stochastic SSTS cohort `00040`–`00100` contains 61 models
  with `distrib:required="true"`. All share trigger `t >= 0.5` and assign a
  fresh distribution draw to `X` while resetting `t`; 47 reset it to `0.5` and
  14 to `-0.5`. Across the cohort, draws use 12 distribution functions. The
  reference for `00040` reports mean `0` and standard deviation `1.5` after
  the first firing. The package specification describes `distrib` as encoding
  sampling from statistical distributions: [SBML Level 3 Distributions
  Package](https://sbml.org/documents/specifications/level-3/version-1/distrib/).
- [x] A parser regression derived from `stochastic/00040` first failed with
  severity `info` and the false empty-package diagnostic. It now passes with a
  dropped, one-element `distrib` warning. A direct parser sweep of all 61
  official L3V2 cohort files produced the expected dropped package warning for
  all 61, with no failures. The full Python suite passes
  (`677 passed, 28 skipped`); Ruff and Black stdin formatting checks pass.
  `stochastic/00040` remains unsupported because required distribution
  sampling and recurring state-trigger event execution are not implemented in
  the BNGL runtime. The schema 4 selected report
  `/private/tmp/bng3-ssts-source-provenance-00040.json`, SHA-256
  `527b49c1dcd03891cee7bd6014574f8c42bb924efdc6053b12fc7d40df1a1415`, records
  suite commit `cf38585fac5de8e0e90112febb62851ee2181816`, BNG3 commit
  `b47c36e1934b4f7874d8cae9b47414312acd5ac4`, and a clean tracked worktree.
- [ ] Supporting this cohort needs an executable random-distribution event
  path plus the predeclared seeded ensemble and statistical acceptance gate.
  A deterministic scheduled assignment cannot preserve these model semantics.
  This work does not benchmark BNG2 Atomizer; BNG2 Atomizer remains incomplete
  and has not been benchmarked against all SBML.

## Exact BNG3 source provenance in SSTS reports — 2026-09-28

- [x] SBML Test Suite report schema 4 records the BNG3 Git commit and whether
  the tracked worktree is clean, alongside the pinned suite commit. Existing
  schema 3 full-suite reports do not record BNG3 source revision and cannot be
  treated as exact-head evidence.
- [x] A regression uses a temporary Git repository to verify clean and dirty
  tracked-worktree reporting. The CI-contract and Python suites pass together:
  `706 passed, 28 skipped`; Ruff and Black stdin checks pass.
- [x] The schema 4 selected report for `stochastic/00040` records BNG3 commit
  `b47c36e1934b4f7874d8cae9b47414312acd5ac4`, a clean tracked worktree, and
  suite commit `cf38585fac5de8e0e90112febb62851ee2181816`. The selected case
  remains unsupported for required `distrib` sampling and state-triggered
  event execution. See the hashed report recorded above.
- [ ] Refresh the complete SSTS report with schema 4 before using it as exact
  source-head evidence; the latest aggregate count remains an older report.

## Additional supported SSTS Atomizer network and rate sample — 2026-09-28

- [x] Benchmarked eight more cases already marked passed by the pinned BNG3
  SSTS report: `00004`–`00009`, `00011`, and `00012`. Ran three repeats in
  flat and Atomized modes with modern BNG3 and the independent PyBioNetGen
  legacy Atomizer, then generated each BNGL network with BNG3 and Perl BNG2.
- [x] All 96 Atomizer conversions succeeded. All 192 network generations
  succeeded, and all 96 paired BNG3/BNG2 comparisons passed structural and
  strict rate-expression checks.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-basic-next-8-20260928.json`,
  SHA-256 `37c1c8f4cf997bdfd6230dc1540197aed5a02fc4320cde2b92113e11c9782985`.
  It records BNG3 source head `17cca65`, BNG2 `8726b30`, PyBioNetGen
  `43b09a5`, and the `bng_cpp` SHA-256
  `67699832444759c9166f51b14b7aaa8387b0f7b7f5a1d011b4d9043fcd972268`.
  Tracked-diff hashes are empty; dirty status flags come from preserved
  untracked artifacts in the BNG3 and PyBioNetGen checkouts.
- [ ] This is selected network/rate evidence and makes no trajectory parity
  claim. BNG2 Atomizer remains incomplete and has not been benchmarked against
  all SBML. Broader SSTS intersections, NFsim trajectories, and the stopped
  curated BioModels validation remain open.

## Mixed-complexity SSTS Atomizer network sample — 2026-09-28

- [x] Benchmarked eight selected SSTS L3V2 models (`01164`, `01168`, `00287`,
  `00291`, `00292`, `00023`, `00024`, and `00019`) in flat and Atomized modes
  with three repeats. The cohort includes external `comp` model resolution.
- [x] Fixed the benchmark's modern BNG3 worker to pass each SBML file's source
  path to Atomizer, so relative external-model references resolve as they do
  in the SSTS validator. Added a regression fixture asserting the flattened
  child species and reaction rule. The test passes.
- [x] All 96 modern and legacy Atomizer conversions completed. Modern BNG3
  produced usable networks for all 48 mode/repeat rows; all 48 BNG3/BNG2
  network pairs passed structural and strict rate-expression comparisons.
- [x] The legacy PyBioNetGen Atomizer produced passing network comparisons
  for 36 rows across six models. For `01164` and `01168`, all six flat/Atomized
  repeats emitted BNGL with no reaction rules; BNG2 reported “Nothing to do:
  no reaction rules defined,” so those 12 legacy comparisons did not produce
  parseable networks. This is recorded as a legacy coverage gap, not a pass.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-mixed-complexity-8-20260928-sourcepath-6cc1ca2.json`,
  SHA-256 `83f6a218dc6c62e9190346047691307165299bcfe82f73acf176a713f8d80189`.
  It records BNG3 commit `6cc1ca2fee69d7f6c11f85416be589dbe8d1369f`,
  BNG2 `8726b30`, PyBioNetGen `43b09a5`, and the `bng_cpp` SHA-256
  `67699832444759c9166f51b14b7aaa8387b0f7b7f5a1d011b4d9043fcd972268`.
  BNG3 tracked-diff hash is empty; the dirty status flag reflects the preserved
  untracked offline bundle.
- [ ] This is a selected eight-model network/rate comparison, not trajectory
  parity, full supported-intersection coverage, or all-SBML benchmarking.
  BNG2 Atomizer remains incomplete and has not been benchmarked against all
  SBML. The full SSTS source-head refresh, NFsim trajectory cohort, and stopped
  curated BioModels validation remain open.

## Event and variable-stoichiometry SSTS Atomizer network sample — 2026-09-28

- [x] Benchmarked selected official SSTS cases `semantic/00388` (L2V5),
  `00389` (L3V2), `00393` (L3V2), and `00394` (L2V5) in flat and Atomized
  modes with three repeats. Both modern BNG3 and legacy PyBioNetGen Atomizer
  outputs were sent to BNG3 and Perl BNG2 for network comparison.
- [x] Modern BNG3 completed all 24 conversions and produced structurally
  matching networks in all 24 comparisons; strict rate-expression parity
  passed 6/24 comparisons, all for `00389`. Legacy PyBioNetGen completed 21/24
  conversions, with structural parity in all 21 resulting comparisons and
  strict rate-expression parity in 18/21. Its Atomized conversion of `00393`
  failed all three repeats with a `TypeError` in legacy `sbml2bngl.py:2010`.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-event-rank-4-20260928-42360e7.json`,
  SHA-256 `044468d843549615294fb3f0330a98e1424a9f90c718ff165a829e6b5263c2a2`.
  It records BNG3 `42360e782bc104d900780964f129bffacb1523b9`, Perl BNG2
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`, and PyBioNetGen
  `43b09a5346402986d48b1defba5eaec0ae2f7802`. Tracked source diffs were empty;
  dirty status reflects untracked artifacts in the BNG3 and PyBioNetGen
  checkouts.
- [ ] This is a four-case SSTS network/rate sample, not trajectory parity,
  complete SSTS coverage, or an all-SBML benchmark. The BNG2/legacy Atomizer
  remains incomplete and has not been benchmarked against all SBML. Broader
  cross-engine intersections, NFsim trajectories, and the stopped curated
  BioModels validation remain open.

## Review of open performance PRs — 2026-09-28

- [x] Reviewed PR #26 at head `7b1d7ec57300911bbf2b8bceb7ac3c9a1ed5b6dd`
  and PR #27 at head `b105d54ae971a18eca36a061e2ac6c89abf21dc3`. Both target
  base `148a031`; current `main` is `7fd5dd6b5303e8f018b8ff7744f696cfd1babe06`.
- [ ] Both PRs contain Metal batch SSA code whose GPU path builds
  `meanSpecies` with one row while retaining a multi-row time grid. The default
  `.cdat` writer indexes concentrations for every time row, so GPU batch runs
  can read out of bounds. PR #26's checks pass but do not cover this shape;
  PR #27 contains the same path.
- [ ] PR #27's NFcore2 `SsaDriver::canonicalPair` orders same-type reactant
  roots solely by molecule handle. Matcher root roles can differ, so
  asymmetric same-type bimolecular patterns may lose valid matches. Add a
  role-asymmetric homotypic test and preserve all valid orientations.
- [ ] PR #26 and #27 cast parsed `batch_size` values to `size_t` before
  checking range or integrality. Reject negative, non-finite, fractional, and
  out-of-range values before conversion.
- [x] PR #26 hosted checks passed on its head, while wheel, source-distribution,
  Docker, and publish jobs were skipped. GitHub reported merge state `DIRTY`.
  PR #27's C++ matrix and ASan checks failed at its exact head; Python matrix,
  parity jobs, lint, and CodeQL passed. C++ failures include a missing
  architecture disposition for `tests/architecture_contracts/nfcore2/test_ssa_driver.cpp`;
  Windows also reported a segfault in `tests/cpp/test_ode_options.cpp:529`.
  GitHub reported merge state `UNSTABLE`.
- [ ] This is source review only. PRs were not modified or approved; resolve
  the correctness findings, rebase on current `main`, and rerun exact-head
  checks before treating either PR as merge-ready.

## Proven inactive stationary state-triggered events — 2026-09-28

- [x] The modern Atomizer now omits a state-threshold event when its exact
  quadratic trajectory is stationary and starts outside the trigger region.
  This also handles pairwise state comparisons when their difference is
  proven stationary. Event assignments cannot change the proof because the
  event never has a rising edge.
- [x] Added focused regressions for a stationary scalar state and a stationary
  species difference whose event assignments include a trigger species. The
  complete event test module passes (`73 passed`); Ruff, Black (`py39`), and
  `git diff --check` pass.
- [ ] This slice adds no verified official SSTS pass or trajectory-parity
  result. Exact-head report
  `/private/tmp/bng3-stationary-event-00374-82e3f52.json`, SHA-256
  `fc757b293eed41f3526f0eb3b3965bca4f4b2f6f085ac7533100bf1700230517`, records
  `semantic/00374` as unsupported because dynamic event scheduling is outside
  the BNGL action engine. BNG2/legacy Atomizer remains incomplete and has not
  been benchmarked against all SBML; broader Atomizer and cross-engine gates
  remain open.

## Full SBML Test Suite source-head refresh — 2026-09-28

- [x] Ran the complete pinned SSTS (`cf38585fac5de8e0e90112febb62851ee2181816`)
  with schema 4 at BNG3 `ef53506c2cc02bdbd26283e167aa429255fa6c21`, with a clean
  tracked worktree, `t_end=1`, and 10 output intervals. The 1,923 records yield
  `1,738 passed, 185 unsupported, 0 failed, 0 timed out`; semantic records are
  `1,700/123` passed/unsupported, and stochastic records are `38/62`. The
  supported-surface gate passes; the aggregate Core gate remains open.
- [x] Exact case-ID comparison with the prior full report
  `/private/tmp/bng3-delayed-chain-initial-assignment-full-sbml.json` finds no
  status changes across all 1,923 cases. That earlier aggregate has no source
  provenance; this schema-4 report provides the exact BNG3 source revision:
  `/private/tmp/bng3-ssts-full-ef53506.json`, SHA-256
  `85ecf0f7c8bc02b3959330de2438b72685f154016216aa02d7d2f38c2518e9af`.
- [x] The unsupported cause counts overlap: events `90`, required `distrib`
  package `61`, constraints `35`, fast reactions `35`, FBC `34`, MathML `20`,
  stoichiometry `7`, and other `5`. Twenty-seven records have events as their
  only reported cause. The complete unsupported inventory is in the report.
- [ ] This is modern BNG3 SSTS round-trip and BNG3/libRoadRunner validation;
  it does not benchmark BNG2 Atomizer against all SBML. BNG2/legacy Atomizer
  remains incomplete, and full cross-engine parity and the stopped curated
  BioModels validation remain open.

## Remaining event-only SSTS cohort triage — 2026-09-28

- [x] Inspected all 27 event-only records in the schema-4 full report against
  their pinned SBML source. They do not form one safe scheduling cohort:
  `00387`/`00388` and related threshold cases include rank-two reaction
  trajectories; `00374` has coupled quadratic dynamics; `00663`/`00664` and
  `00762` use state-difference triggers with self-multiplying assignments;
  `00965`/`00966` and `01626`/`01627` exercise recurring or multi-event state
  interactions.
- [x] Re-ran `01626` and `01627` individually at the earlier `main` head
  (`a911ccfcddeddf3e309f5184b6364eadf2c59d43`, `t_end=1`, 10 intervals).
  Both remain unsupported: `01626` lowers 0/6 events and `01627` lowers 5/6;
  the latter still has one state-dependent event. Reports:
  `/private/tmp/bng3-ssts-reset-01626-a911ccf.json` and
  `/private/tmp/bng3-ssts-reset-pair-a911ccf.json`.
- [ ] No new event behavior or SSTS gain is claimed by this triage. The
  remaining event gap needs a semantic implementation that handles dynamic
  trigger crossings and recurring/reset interactions; rank-two cases are not
  evidence for loosening the existing exact-trajectory proof. BNG2/legacy
  PyBioNetGen Atomizer remains incomplete and has not been benchmarked against
  all SBML. Cross-engine and stopped curated BioModels gates remain open.

## Periodic rate-rule event lowering — 2026-09-28

- [x] The modern Atomizer can prove an absolute threshold event inactive when
  its rate-rule state has a piecewise-constant derivative determined by
  already-lowered periodic parameter events, and every segment stays strictly
  inside the threshold by a floating-point margin. It fails closed when a
  dependency has its own rate rule or is the continuously changing reset
  state.
- [x] The translator can schedule a positive fixed-time event behind a
  parameter gate when the gate is proven true at the time crossing and remains
  true after every later periodic update. This lowering is limited to
  undelayed events with static parameter assignments.
- [x] Added regressions for the supported piecewise-constant case, continuous
  dependency drift, and a periodic gate that ceases to be provable. Focused
  event tests pass (`76 passed`), SBML parity tests pass (`104 passed`), and
  Ruff, Black (`py39`), and `git diff --check` pass.
- [x] Pinned SSTS `semantic/01627` passes at exact clean source head
  `722cfba8e8a22a14b4171c08b088b953cb328d5e` at both `t_end=1` / 10 intervals
  and `t_end=100` / 100 intervals. The BNG3/libRoadRunner comparison passes
  all 5 observables at both horizons; maximum absolute difference is 0 at
  `t_end=1`, and `3.552713678800501e-14` at `t_end=100`. Reports:
  `/private/tmp/bng3-ssts-01627-722cfba-t1.json` (SHA-256
  `dc6d9d8f6b068e4076bf8d4f515afedb06ce6730a0b56ab18f20676598fd9f70`) and
  `/private/tmp/bng3-ssts-01627-722cfba-t100.json` (SHA-256
  `a0424e3503806ac94f8436e389d544ef411ac7aa1809c0b176053a3fd8947316`).
- [ ] This is focused evidence for one current BNG3 SSTS case, not a refreshed
  full-suite aggregate. `semantic/01626` remains unsupported
  (`/private/tmp/bng3-ssts-01626-722cfba.json`, SHA-256
  `a3ef1cd5cacd7b13704126fdadd7eafdef46e7ebd3e6118bf5b362d0a65e423f`).
  BNG2/legacy PyBioNetGen Atomizer remains incomplete and has not been
  benchmarked against all SBML; full cross-engine and stopped curated
  BioModels gates remain open.

## Exact-head event-cohort refresh — 2026-09-28

- [x] Re-ran seven pinned SSTS semantic cases against clean tracked BNG3
  source head `783580905f3726a7e5a4467073a49f373edf8ec4`: `00663`, `00664`,
  `00762`, `00965`, `00966`, `01626`, and `01627`. Per-case status records
  show `01626` and `01627` passing; the other five remain unsupported due to
  untranslated state-dependent events. Reports follow
  `/private/tmp/bng3-event-triage-{CASE_ID}-7835809.json` for those seven IDs.
- [x] Source inspection found no safe shared lowering among the five
  unsupported records. `00663`/`00664`/`00762` trigger on `S4 > S3` and
  rewrite `S4` multiplicatively; reaction-driven changes can alter the trigger
  after firing, and current analysis does not prove that it cannot re-enter.
  A single pre-event crossing is therefore insufficient.
  `00965`/`00966` use recurring timer/reset and counter events with interacting
  assignments. General dynamic event re-entry remains unsupported.
- [ ] This is a seven-case modern BNG3 Atomizer refresh, not trajectory parity,
  full SSTS coverage, or an all-SBML benchmark. The BNG2/legacy PyBioNetGen
  Atomizer remains incomplete and has not been benchmarked against all SBML;
  no BNG2 source was changed. Full cross-engine and stopped curated BioModels
  gates remain open.

## PR #28 regex-precompile source review — 2026-09-28

- [x] Reviewed draft PR #28 at head
  `1a5008b4163109d85e0503af4eefe49074572152`, based on
  `d6eef9b035ebdfd61e1fc80f95f119aef645a25e`. The change precompiles static
  patterns in `helpers.py` and caches `_replace_calls` patterns by name. All
  current `_replace_calls` call sites use fixed names, and existing helper
  tests cover representative conversion behavior; no source-level correctness
  defect was identified in this review.
- [ ] The PR body reports roughly 30% improvement from tight-loop microbenchmarks,
  but benchmark scripts/results are not included in the diff, so the claimed
  gain is not independently reproducible from the PR. Current `main` is ahead
  of the PR base; rebase and rerun exact-head checks before approval. All 29
  checks were pending at review time. No PR review comment or approval was
  posted.

## Event-only SSTS cohort refresh — 2026-09-28

- [x] Re-ran all 26 semantic case IDs classified as event-only unsupported
  by the prior full report (`ef53506c`) against BNG3
  `fdefe2cdf21b2a31ee1e864091d79a6233607d9c`. Current per-case records show
  2 passed (`01626`, `01627`), 24 unsupported, 0 failed, and 0 timed out. The
  per-case reports and SHA-256 digests are indexed in
  `/private/tmp/bng3-event-only-cohort-fdefe2c.json` (SHA-256
  `595de65cff3a6bf91e25c7047cc2e957faec714a502aedd6fb2e8657dc0f6a7d`).
- [ ] This is a modern BNG3 Atomizer round-trip cohort, not numerical
  trajectory parity or full SSTS coverage. Cases span nonlinear bimolecular
  threshold crossings, trigger-state feedback, and recurrent timer/reset
  interactions; no single additional lowering was justified by this triage.
  BNG2/legacy PyBioNetGen Atomizer remains incomplete and has not been
  benchmarked against all SBML. No BNG2 source was changed.

## NFsim ensemble seed-independence correction — 2026-09-28

- [x] Audited the prior `benchmark_atomizer_nfsim.py` reports and found both
  engines had received the same seed range, while `compare_stochastic` uses a
  pooled standard error for independent samples. Treat those earlier pooled-SE
  results as correlated same-seed checks, not independent ensemble evidence.
  The exact-seed SSTS `00001` run at seed `17` remains a separate exact
  trajectory check.
- [x] Fixed the BNG3 benchmark to use non-overlapping seed ranges by default,
  record both ranges, benchmark-script SHA-256, and BNG3 worktree state, and
  reject overlap. Added regression tests. Focused benchmark tests pass (`5
  passed`); Ruff, Black (`py39`), and Python 3.9 syntax checks pass. Commits
  `e5342fd` and `07d7b36` are pushed.
- [x] Re-ran four pinned SSTS stochastic cases (`00001`, `00006`, `00024`,
  `00030`) in flat and Atomized modes, with 200 BNG3-direct runs (seeds
  `1`–`200`) and 200 standalone-NFsim runs (seeds `201`–`400`) per mode. All
  3,200 trajectories completed with no run errors; all eight independent
  ensemble comparisons passed, with zero points beyond 3 pooled standard
  errors. The current-source SSTS round-trip/libRoadRunner records pass all
  four cases individually; each one-case invocation has aggregate `core=FAIL`
  because it is partial, and SSTS reference-result conformance was not run.
  Manifest `/private/tmp/bng3-ssts-nfsim-independent-4-manifest-07d7b36.json`,
  SHA-256 `2e4699b578b1c863592da95e71e7343a926b12fefbe0cc1cf0773bfe5f26141c`.
- [ ] This is a four-case modern BNG3 Atomizer/NFsim sample, not full SSTS or
  all-SBML coverage. Perl BNG2 was used only to write BNG-XML for standalone
  NFsim; this does not benchmark the incomplete BNG2/legacy PyBioNetGen
  Atomizer. At this checkpoint the selected curated BioModels NFsim reports
  still used correlated same-seed ensembles; their independent-seed refresh is
  recorded below. The user-stopped full BioModels validation remains stopped.

## Curated NFsim independent-seed refresh — 2026-09-28

- [x] Re-ran six previously selected cached curated models (`0414`, `0425`,
  `0485`, `0850`, `0906`, `1038`) in flat and Atomized modes with 200 direct
  BNG3 runs (seeds `1`–`200`) and 200 standalone NFsim runs (seeds `201`–`400`)
  per mode. All 12 mode comparisons passed; all 4,800 trajectories completed
  without run errors, with zero points outside 3 pooled standard errors. Worst
  observed `|z|` was `2.4791` for `BIOMD0000001038`.
- [x] Aggregate manifest
  `/private/tmp/bng3-nfsim-curated-6-independent-manifest-2bd9813.json`,
  SHA-256 `63ac58be0732de64ffcb3a765a078cec3d9d6c91943fb3534e99ccb4412c7be4`,
  records all six source hashes, report hashes, seed ranges, BNG3 and BNG2
  revisions, and standalone NFsim binary hash. This is a selected stochastic
  simulator benchmark, not a restart of the stopped full BioModels validator.
- [ ] This remains a six-model NFsim sample; full curated flat/Atomized
  validation, broader supported-intersection coverage, and all-SBML coverage
  remain open. Perl BNG2 only emitted XML for standalone NFsim. No BNG2 source
  or legacy Atomizer was changed or benchmarked.

## Full SBML Test Suite refresh — 2026-09-28

- [x] Ran the complete pinned SSTS (`cf38585fac5de8e0e90112febb62851ee2181816`)
  against clean tracked BNG3 source head `2deea2dc6f397acdd390504c4f720861d6553d96`,
  at `t_end=1` with 10 output intervals. All 1,923 records completed:
  `1,740 passed, 183 unsupported, 0 failed, 0 timed out`. The supported-surface
  gate passes; aggregate Core remains open. Semantic records are `1,702/121`
  passed/unsupported and stochastic records are `38/62`.
- [x] Compared all case statuses with the prior full report at `ef53506`:
  `semantic/01626` and `semantic/01627` changed from unsupported to passed;
  the other 1,921 statuses are unchanged. Overlapping unsupported causes are
  events `88`, `distrib` package `61`, constraints `35`, fast reactions `35`,
  FBC `34`, MathML `20`, stoichiometry `7`, algebraic rules `2`, and other `5`.
  Report `/private/tmp/bng3-ssts-full-current-2deea2d.json`, SHA-256
  `a6fe6b581e718ded580bfbe049b12877c17a6de97619589fba54696b261a4fff`.
- [ ] This is modern BNG3 Atomizer/C++ round-trip and BNG3/libRoadRunner
  all-observable comparison over the pinned SSTS, not a complete all-SBML
  benchmark. It does not establish BNG2/legacy PyBioNetGen Atomizer coverage:
  that Atomizer remains incomplete and has not been benchmarked against all
  SBML. No BNG2 code was changed. Full cross-engine parity, SSTS reference
  result conformance, and the user-stopped full curated BioModels validation
  remain open.

## Cross-engine benchmark import isolation correction — 2026-09-28

- [x] Audited `benchmark_atomizer_cross_engine.py` after a legacy worker
  traceback resolved inside the BNG3 editable install. The old worker's
  `PYTHONPATH` did not defeat the installed editable import hook: previous
  selected reports labeled the BNG3-bundled legacy Atomizer as independent
  PyBioNetGen. At the audited checkouts, the BNG3 and PyBioNetGen
  `atomizeTool.py` SHA-256 values differ (`c862389b...` vs
  `29f1505e...`). Treat legacy-Atomizer results in the earlier selected
  `bng3-cross-engine-ssts-*.json` reports as non-independent; their BNG3/BNG2
  engine runs remain evidence for the particular BNGL files they consumed.
- [x] Fixed the BNG3 benchmark worker to disable Python site hooks for the
  legacy subprocess, load dependencies from site-packages, record the imported
  module path, and fail closed if that path is outside the requested
  PyBioNetGen checkout. Added a regression test that first failed on the old
  worker and now passes. The focused benchmark tests pass (`2 passed`). A
  fresh three-repeat `semantic/00004` end-to-end check imported the actual
  PyBioNetGen module and passed structural and rate comparisons in all three
  repeats for both Atomizers.
- [x] Re-ran the 50 unique SSTS inputs appearing in the prior selected
  cross-engine reports (both modes, three repeats) with module-path
  verification. Modern BNG3 Atomizer conversions passed `300/300`; independent
  PyBioNetGen conversions passed `273/300`, with 27 errors: 15 formatting
  `TypeError`s, 6 `no symbols given` errors, and 6 NaN-to-integer errors.
  Among successful network comparisons, BNG3-generated BNGL passed structural
  parity `288/288` and rate parity `210/288`; independently generated
  PyBioNetGen BNGL passed structural parity `234/234` and rate parity
  `225/234`. Perl BNG2 network generation errored for six BNG3 outputs from
  `semantic/00224` and timed out at 30 seconds for six outputs from
  `semantic/01561`.
- [x] Source-isolated report
  `/private/tmp/bng3-cross-engine-ssts-import-isolated-50-20260928.json`,
  SHA-256 `5cd5c6c38a89c9e5003a2660a5faced0479208a593d46986f150511e91589ea3`,
  records BNG3 `2b81c42`, BNG2 `8726b30`, PyBioNetGen `43b09a5`, suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, and verifies every successful
  legacy module path. This replaces the independent-PyBioNetGen interpretation
  of the earlier selected runs.
- [ ] This remains a 50-case selected benchmark. It is not full SSTS or an
  all-SBML benchmark of the incomplete BNG2/legacy PyBioNetGen Atomizer.
  Broader cross-engine coverage, trajectory parity, and curated BioModels
  validation remain open. No BNG2 or PyBioNetGen source was modified.

## TotalRate network serialization parity — 2026-09-28

- [x] Fixed BNG3 `NetWriter` to preserve complete `TotalRate` fluxes by omitting
  reaction-pattern symmetry and compartment unit-conversion factors, including
  generated reverse-rule origins. Added a C++ regression for a repeated
  reactant pattern. It failed before the fix and passed after it.
- [x] Updated the BNG3 network comparator to remove neutral multiplication by
  one from supported rate expressions. Added a regression for the exact
  redundant-prefix form produced by the BNG2 network writer.
- [x] C++ `test_ode_options`: 16 cases and 61 assertions passed. Python network
  comparator tests: 15 passed. Ruff, Black (`py39`), and `git diff --check`
  passed. `clang-format` is not installed in this environment.
- [x] Refreshed the three-repeat `semantic/00388` (L2V5) cross-engine sample in
  flat and Atomized modes. Modern BNG3 and independent PyBioNetGen each passed
  structural and rate comparisons against Perl BNG2 in all six comparisons.
  Report `/private/tmp/bng3-cross-engine-00388-totalrate-fixed-final.json`,
  SHA-256 `324b48cd62b1ce1feebf45a1d5be8c21d5643b02e2ba203040220f7745ebc035`;
  source head `667f783ecde838f6d8e25264cd2974dacf0ad430`, rebuilt `bng_cpp`
  SHA-256 `6fda97e8be9dcbbc34617ab5e1e00a8253108eda5b859378c8fc922d4fe88285`.
- [ ] This is one SSTS interoperability case, not trajectory parity or a
  complete SBML benchmark. BNG2/legacy Atomizer remains incomplete and has not
  been benchmarked against all SBML. Broader SSTS/BioModels intersections,
  NFsim validation, and release packaging remain open.

## Refreshed selected 50-case cross-engine sample — 2026-09-28

- [x] Re-ran the same 50 SBML inputs from the prior selected sample with three
  repeats in flat and Atomized modes, using a 30-second per-network timeout.
  Pinned SSTS checkout is `cf38585fac5de8e0e90112febb62851ee2181816`.
- [x] Modern BNG3 completed all 300 conversions; BNG3/BNG2 network generation
  completed 588/600 rows (6 BNG2 errors and 6 BNG2 timeouts). All 288 paired
  networks matched structurally; rate parity passed 234/288, up from 210/288
  in the prior report. Cases `00388`, `00393`, `00394`, and `01100` gained
  parity in both modes after the `TotalRate` serialization fix.
- [x] Independent PyBioNetGen completed 273/300 conversions, with 27 errors.
  It produced 234 paired comparisons; all 234 matched structurally and 225
  matched rates. Imported module path resolved to the requested
  `/Users/akutuva/Documents/BioNetGen/PyBioNetGen` checkout.
- [x] Report `/private/tmp/bng3-cross-engine-ssts-totalrate-fixed-50-20260928-30s.json`,
  SHA-256 `f90449e9d42b6530788631b753bd025964ef22342feb51de144ea8cbed3e045e`.
  It records BNG3 head `0146464501d2884ef55c52ecbb5c728e137f7485`, rebuilt
  `bng_cpp` SHA-256 `6fda97e8be9dcbbc34617ab5e1e00a8253108eda5b859378c8fc922d4fe88285`,
  BNG2 `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`, and PyBioNetGen
  `43b09a5346402986d8e25264cd2974dacf0ad430`. Benchmark script SHA-256:
  `3aea58f172e0de4011c123f0b63975cb82b71516cead6f0c9122743a8d37f2f8`.
- [ ] This is a selected 50-input network/rate sample; it does not establish
  trajectory parity, full SSTS coverage, or an all-SBML benchmark of the
  incomplete BNG2/legacy Atomizer. BioModels validation remains stopped.

## Second selected 50-case cross-engine sample — 2026-09-28

- [x] Benchmarked 50 distinct semantic SSTS inputs not present in the prior
  50-input sample from pinned suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`. Selection was evenly spaced
  across the 1,655 remaining semantic cases marked passed in the full report
  at ancestor head `2deea2d`.
  Each input ran three times in flat and Atomized modes, with a 30-second
  per-network timeout, against the current BNG3 build, Perl BNG2, and the
  independently imported PyBioNetGen checkout. All 255 successful legacy
  Atomizer imports resolved to that checkout.
- [x] Modern BNG3 Atomizer completed `300/300` conversions. BNG3 network
  generation and parsing completed `300/300` rows after the comparator began
  accepting valid empty species/reaction blocks. Perl BNG2 completed `240/300`.
  All 240 paired networks matched structurally; rate-expression parity passed
  `180/240`.
  Independent PyBioNetGen completed `255/300` conversions and yielded 141
  paired networks; all 141 matched structurally and 135 matched rates.
- [x] Added regressions that accept BNG3’s valid empty `.net` files and still
  reject parameter-only text. `tests/validation/test_compare_net.py` passes
  (`17 passed`); Ruff and Black (`py39`) pass. BNG3 SSTS cases `01157`, `01242`,
  `01277`, and `01311` now parse as zero-species, zero-reaction networks in
  both modes.
- [x] Exact-head report `/private/tmp/bng3-cross-engine-next50-empty-net-fixed-20260928-30s.json`,
  SHA-256 `892d41e33fe2fa89d261a0bebb238b8194cdad7201da604558ed0e457a771956`,
  records BNG3 head `a144d6757324862f3b0ce013417c7a9642c03bab`, BNG2
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`, PyBioNetGen
  `43b09a5346402986d48b1defba5eaec0ae2f7802`.
- [ ] This is a 50-case network/rate sample. It is not trajectory parity, full
  SSTS coverage, or an all-SBML benchmark of BNG2/legacy PyBioNetGen Atomizer;
  that Atomizer remains incomplete. No BNG2 or PyBioNetGen source was changed.
  Curated BioModels validation remains stopped.

## Refreshed open BNG3 PR review — 2026-09-28

- [x] PR #26 remains open at head `7b1d7ec57300911bbf2b8bceb7ac3c9a1ed5b6dd`
  against old base `148a0314685c71cfeece1db7a13b17a79ec42557`. Current checks:
  39 pass, 5 skipped. Existing review findings remain; no PR changes were made.
- [x] PR #27 remains open at head `b105d54ae971a18eca36a061e2ac6c89abf21dc3`
  against the same old base. Current checks: 29 pass, 5 fail, 7 skipped. The
  failures are C++ jobs on macOS/Clang, Ubuntu/GCC, Ubuntu/Clang, Windows/MSVC,
  and Ubuntu/ASan. Existing correctness findings remain; no PR changes were
  made.
- [x] Refreshed PR #27 failure logs in run
  [36358966258](https://github.com/RuleWorld/BNG3/actions/runs/36358966258).
  All five C++ failures reach `energy_validation_harness`, where
  `test_imported_contracts_have_explicit_dispositions` rejects the new
  `tests/architecture_contracts/nfcore2/test_ssa_driver.cpp`: the PR adds it to
  CMake but does not add it to `provenance/architecture-contracts.json`. The
  Windows job also reports a separate segfault in `OdeIntegrator preserves
  multi-species derivative updates`; that failure is not diagnosed yet. The PR
  remains unmodified and unreviewed on GitHub.
- [x] Reviewed new draft PR #28 at head
  `1a5008b4163109d85e0503af4eefe49074572152`. Its regex cache call sites use a
  fixed built-in function-name set, so the dictionary is bounded in current
  code. No performance benchmark was included in the inspected patch. Latest
  exact-head checks show C++/ASan, CodeQL, Lean, lint, and Python matrix jobs
  passed; full-corpus validation, integration, parity, and package smoke remain
  pending. Docker, wheel/sdist publication, and scheduled NFsim jobs were
  skipped. No PR was modified, approved, or commented on.

## Local pip artifact build and install smoke — 2026-09-28

- [x] Built a CPython 3.14.6 macOS ARM64 wheel and source distribution from
  BNG3 head `d673c31e8f46180f7e770564afbdb566f879060a`. Wheel SHA-256:
  `bf42a75657bcd1413af9f609c70cd75e776e63c71dc3169ef61eab486c1b1859`;
  sdist SHA-256:
  `ca9621c53c8f79acfbc133442aebf710f2695c636f868a4baaf0cc539e60486b`.
  The sdist excludes the pre-existing offline bundle.
- [x] Installed the wheel in a fresh CPython 3.14 venv with declared
  dependencies and confirmed imports resolve from that venv. `bionetgen
  --version`, `--help`, and `check` passed; a short ODE run produced 11 finite
  rows through `t=1`. Built a second wheel from the sdist, installed it in the
  same clean venv, and repeated version, parse, and simulation smoke checks.
  The sdist-built wheel SHA-256 is
  `9fd94e123b0733975959977f34ada7bf6d8919b6642f29e3ef42be9d07cf9d16`.
- [ ] This verifies only the local `cp314-cp314-macosx_26_0_arm64` artifact,
  not the release platform matrix or publication flow. Building from the sdist
  needs network access for CMake's ANTLR fetch. CMake also emitted deprecation
  warnings from pybind11 and SUNDIALS. The exact-head hosted CI workflows for
  `a144d6757324862f3b0ce013417c7a9642c03bab` remain queued; no release was
  published and Windows packaging remains unverified.

## Exact-head event cohort refresh — 2026-09-28

- [x] Re-ran the same 26 pinned SSTS semantic event cases against clean tracked
  BNG3 source head `bd302d17094ab1cdfc118b7e4f59c406c795cf10` and suite commit
  `cf38585fac5de8e0e90112febb62851ee2181816`: 2 passed, 24 unsupported, 0
  failed, 0 timed out. Aggregate index:
  `/private/tmp/bng3-event-only-cohort-bd302d1.json` (SHA-256
  `b7293ef3ab0aa2fdd96e4c263c4709e46d6862913d8d44ed25a9cb808208c7c8`);
  it records per-case report paths and digests.
- [x] Separately revalidated `semantic/00991` on the same BNG3 and suite heads:
  1 passed, core passed, 0 unsupported/failed/timeouts. Report
  `/private/tmp/bng3-ssts-00991-bd302d1.json` (SHA-256
  `bece8c4d59372cf0670b3229eab18b60529975cc9507736216a2e3fe58bc298d`).
- [x] Source inspection ruled out a superficially similar trajectory cohort:
  `00388` and related cases use Level 2 `stoichiometryMath` (`2*p1` or `4*p1`,
  each resolving to an `S2` coefficient of 2) and have rank-two reaction vectors, plus
  bimolecular `S1*S2` kinetics. Ignoring `stoichiometryMath` would misclassify
  their stoichiometric rank. Passing `00389` has different rank-one reaction
  semantics and does not justify lowering the rank-two cases. No shared
  lowering was justified by this refresh.
- [ ] This remains a selected BNG3 event cohort, not full SSTS coverage or an
  all-SBML BNG2/legacy Atomizer benchmark. BNG2 Atomizer remains incomplete;
  no BNG2 code changed. Curated BioModels validation remains stopped.

## Current-head local wheel install smoke — 2026-09-29

- [x] Built a CPython 3.14 macOS ARM64 wheel from BNG3 head `b03d833` and
  installed it into a clean venv without dependencies. The package and compiled
  `_bionetgen_cpp` extension both imported from that venv; `bionetgen
  --version`, `--help`, `info`, and `check` on `simple_system.bngl` passed.
  Wheel SHA-256:
  `95bbb9cc39056fce4c23f35a96bdfc206c0110de1c5e67d7525f28d6c1f70117`.
- [x] For this offline smoke, the clean venv used host-installed NumPy, Click,
  and Packaging through symlinks. The first check with system-site-packages
  was discarded after it resolved BNG3 from the editable checkout. The
  clean-venv check resolves BNG3 and its extension from the installed wheel.
- [ ] This is local macOS CPython 3.14 evidence only. It does not qualify the
  release matrix, normal online dependency resolution, publication flow, or
  Windows executable. The initial hosted CI and PR query failed with
  `error connecting to api.github.com`; the successful retry and current state
  are recorded below. User-stopped curated BioModels validation remains stopped.

## Exact-head CI and open PR refresh — 2026-09-29

- [x] Verified `origin/main` at `8ba19e2f8d9bfb338e792e39ebf20c39fff8cb7b`.
  Exact-head CI (`36509479334`), CodeQL (`36509479386`), Cross-tool parity
  (`36509479428`), and Lean semantic kernel (`36509479449`) were queued at the
  last query; none is reported as passing yet.
- [x] Refreshed open PRs. PR #26 remains based on stale `148a031`; it has 39
  successful and 5 skipped checks and GitHub reports `DIRTY`. PR #27 remains
  based on that stale base; it has 29 successful, 5 failed, and 7 skipped
  checks, including the previously recorded architecture-contract failure and
  a separate Windows `OdeIntegrator` segfault. PR #28 remains a draft on stale
  base `d6eef9b`; it has 37 successful, 5 skipped, and 2 running checks. No PR
  was changed, approved, or commented on.
- [x] Reviewed `.github/workflows/release.yml`: a `v*` tag must point to a
  commit reachable from `main` and have successful exact-SHA main push runs
  for CI, Cross-tool parity, Lean semantic kernel, and CodeQL. The workflow
  defines Linux, macOS Intel/ARM, and Windows executable artifacts, CPython
  wheels, an sdist, a GitHub release, and PyPI publication. The release matrix
  and publication have not run.
- [ ] The exact-head checks are nonterminal; the PRs remain stale, dirty, or
  failing as listed. Keep BNG3 convergence active and keep the stopped curated
  BioModels validation stopped.

## Current sdist-to-wheel install and simulation smoke — 2026-09-29

- [x] Built an sdist from exact BNG3 head `453eeb5828fc779c6eec27ec87fc294076823d5d`,
  then built a CPython 3.14 macOS ARM64 wheel from that archive using cached
  ANTLR, SUNDIALS, and pybind11 sources. The sdist omits the pre-existing
  `bng3-offline-bundle/`. Sdist SHA-256:
  `269487180aa58f286a74c4f2b6ceb062ab31343d066afeadb20d0e4b5dcc849c`.
  Wheel SHA-256:
  `d09e784a6618b505f647446d038d6355cdcc219128b9db7250149cdf2bea38d9`.
- [x] Installed that wheel in a clean CPython 3.14 venv. Imports resolved to
  the venv's BNG3 package and compiled extension; `bionetgen --version`,
  `--help`, `info`, and `check` passed. An ODE smoke run produced 11 finite
  rows through `t=1`.
- [x] NumPy, Click, and Packaging were linked from host site-packages for this
  offline check. CMake used cached native dependency sources; this does not
  verify online dependency resolution.
- [ ] This is local macOS ARM64 evidence. Cross-platform wheel builds, Windows
  executable artifacts, release qualification, GitHub release, and PyPI
  publication remain open.

## Third selected 50-case cross-engine Atomizer sample — 2026-09-29

- [x] Benchmarked 50 unique pinned SSTS semantic inputs absent from the prior
  two selected 50-case sets. The selection was stratified across the remaining
  supported inputs. Each input ran three repeats in flat and atomized modes
  through modern BNG3 Atomizer, independent PyBioNetGen Atomizer, BNG3 network
  generation, and Perl BNG2 network generation. Network timeout was 30 seconds.
- [x] Modern BNG3 converted all 300 mode/repeat inputs and generated all 300
  BNG3 networks. Perl BNG2 generated 228/300 networks. All 228 paired networks
  had matching structure; strict normalized rate parity passed 180/228.
  Independent PyBioNetGen converted 261/300 mode/repeat inputs (135/150 flat,
  126/150 atomized); conversion and network-generation errors are retained in
  the report. Its paired BNG3/BNG2 network structures matched for 153/153
  comparisons; normalized rates matched for 141/153.
- [x] The eight BNG3/BNG2 rate mismatches repeated in both modes and all three
  repeats: `00330`, `00481`, `00687`, `00859`, `01084`, `01309`, `01719`, and
  `01822`. They include BNG2 compartment-size scaling differences, rounded
  numeric literals, and expression serialization differences. Each case is
  marked passed in the pinned full SSTS report, which compares BNG3 against
  libRoadRunner. No BNG3 semantics or strict comparator rules were changed to
  force network-rate parity.
- [x] Report:
  `/private/tmp/bng3-cross-engine-third50-20260929-30s.json`, SHA-256
  `aa75410c1be02c4d9ccd1fac408a55c8c6e3c3343877c00cdcc25547002375e9`.
  It records BNG3 `5c33a0811a725ecc7ec4ffcdb904e0c107ab40f9`, BNG2
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`, PyBioNetGen
  `43b09a5346402986d48b1defba5eaec0ae2f7802`, and suite
  `cf38585fac5de8e0e90112febb62851ee2181816`. Tracked source diffs were empty;
  the benchmark also records pre-existing untracked files in those checkouts.
- [ ] This is a selected 50-input network interoperability sample, not
  trajectory parity, full SSTS cross-engine coverage, or an all-SBML benchmark.
  BNG2/legacy PyBioNetGen Atomizer remains incomplete and has not been
  benchmarked against all SBML. No BNG2 or PyBioNetGen source was changed.
  Curated BioModels validation remains stopped.

## SSTS stochastic NFsim sample expansion — 2026-09-29

- [x] Added pinned `stochastic/00002` to the independent NFsim ensemble sample.
  In both flat and atomized modes, 200 fresh-process BNG3-direct runs (seeds
  `1`–`200`) and 200 standalone-NFsim runs (seeds `201`–`400`) completed with
  zero errors. Both 22-point comparisons passed the 3 pooled-standard-error
  criterion; worst `|z|` was `0.7486`. The source case independently passes in
  the pinned full BNG3/libRoadRunner SSTS report.
- [x] Report `/private/tmp/bng3-atomizer-nfsim-ssts-00002-independent-200runs-20260929.json`,
  SHA-256 `30a19296e240c79955a3960bd0d1d78c1c34f0d35142b00e53b81228a4900e76`.
  It records BNG3 `7b481e93090762b6562b1d0862f3bd5a5c65f551`, BNG2
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`, standalone NFsim source
  `c51c7a34128d188189485bd318aeae4d936bcb29`, and binary SHA-256
  `093707031f70e0c376179e1d8bf89ab1373b3132b6211d7d9759f1d646c4ce9e`.
  Tracked source diffs were empty; the BNG2 Perl path only wrote XML for
  standalone NFsim.
- [ ] This is a selected fifth SSTS stochastic model, not full-suite NFsim
  parity or an all-SBML benchmark. It does not benchmark the incomplete
  BNG2/legacy PyBioNetGen Atomizer against all SBML. The user-stopped full
  curated BioModels validation remains stopped.

## SSTS NFsim sample addition: stochastic/00003 — 2026-09-29

- [x] Pinned `stochastic/00003` passed the independent NFsim ensemble in both
  flat and atomized modes. Each mode completed 200 BNG3-direct runs (seeds
  `1`–`200`) and 200 standalone-NFsim runs (seeds `201`–`400`), with zero run
  errors. Each 22-point mean comparison passed the 3 pooled-standard-error
  criterion; worst `|z|` was `0.7642`. The source case also passes in the
  pinned full BNG3/libRoadRunner SSTS report.
- [x] Report
  `/private/tmp/bng3-atomizer-nfsim-ssts-00003-independent-200runs-20260929.json`,
  SHA-256 `b92c43a2549e62562b43e14895b04edd77e7faa05734597d722ef4dfe7ff120a`.
  It records BNG3 `f71c2593f0835cda276225feddb3b3267c073cc5`, source XML SHA-256
  `c58a50dd86f981150b533dd9af25c38f9ef3aeeedad2f679400e022add77f50e`, BNG2
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc`, standalone NFsim source
  `c51c7a34128d188189485bd318aeae4d936bcb29`, and binary SHA-256
  `093707031f70e0c376179e1d8bf89ab1373b3132b6211d7d9759f1d646c4ce9e`.
  BNG2 Perl only emitted the XML consumed by standalone NFsim.
- [ ] This expands the selected sample by one model only. Full-suite NFsim and
  all-SBML cross-engine coverage remain open; the BNG2/legacy PyBioNetGen
  Atomizer is incomplete and has not been benchmarked against all SBML. The
  stopped full curated BioModels validation remains stopped.

## Aggregated current-source SSTS NFsim cohort — 2026-09-29

- [x] Aggregated independent-seed results for `stochastic/00002` through
  `stochastic/00012` (11 models) in flat and atomized modes. All 22 ensemble
  comparisons passed; 8,800 total trajectories completed with zero run errors
  and zero points outside the 3 pooled-standard-error threshold. Worst `|z|`
  was `2.01191`.
- [x] Manifest
  `/private/tmp/bng3-ssts-nfsim-independent-11-manifest-20260929.json`,
  SHA-256 `f63f6a0d29a737a4f21749102d163b78fb78dbfe5f07a60d42bfd9fa85d7bc9f`,
  records each SBML source hash, individual report hash, BNG3 report head, and
  the common BNG2/NFsim reference revisions. The reports span BNG3 documentation
  heads `7b481e9`, `f71c259`, and `042594a`; a source-tree comparison confirms
  changes from the full SSTS source head `bf210ab` through current `main` are
  limited to this checklist.
- [ ] This is an 11-model stochastic SSTS sample, not full SSTS NFsim coverage
  or an all-SBML benchmark of the incomplete BNG2/legacy PyBioNetGen Atomizer.
  Perl BNG2 only emitted BNG-XML for standalone NFsim. The full curated
  BioModels validation remains stopped.

## Expanded selected SSTS NFsim cohort — 2026-09-29

- [x] Extended independent-seed coverage to 15 consecutive passing stochastic
  SSTS models (`00002`–`00016`), in flat and atomized modes. All 30 ensemble
  comparisons passed; 12,000 trajectories completed with zero run errors and
  zero points beyond the 3 pooled-standard-error threshold. Worst `|z|` was
  `2.01191`.
- [x] Manifest
  `/private/tmp/bng3-ssts-nfsim-independent-15-manifest-20260929.json`,
  SHA-256 `973e8be725e4d03067bbb23ff533eb7e49bd4408b9e24230342104b9424b92cf`,
  records each source/report digest, each BNG3 report head, and shared engine
  provenance. The pinned full SSTS report is SHA-256
  `46951ae3ece7f02b45d932ac946a394df021d375811d9daaa00a8419abf7e02c` at
  source head `bf210ab`; Git confirms only this checklist changed between that
  source head and current `main`.
- [ ] This remains a selected 15-model NFsim sample, not full SSTS coverage or
  an all-SBML benchmark of the incomplete BNG2/legacy PyBioNetGen Atomizer.
  Perl BNG2 only emitted BNG-XML for standalone NFsim. Full curated BioModels
  validation remains stopped.

## Stratified SSTS NFsim structures — 2026-09-29

- [x] Added six distinct stochastic SSTS structures beyond the consecutive
  birth/death variants: `00017`, `00019`, `00020`, `00027`, `00030`, and
  `00034`. The sample covers compartment-scaled rates, zero-order production,
  multi-species models, and nonlinear `P`/`P2` kinetics. All 12 flat/atomized
  comparisons passed with 200 independent runs per engine and zero run errors;
  4,800 trajectories and 308 observable-time points were checked. Standalone
  NFsim reported 23,034 reaction events across the cohort; worst `|z|` was
  `2.25284`.
- [x] Excluded `00024` from dynamic parity counts despite its nominal
  comparator pass: standalone NFsim reported zero reaction events in both
  modes, making its 66-point result a static no-op. Its report is retained in
  the manifest with that disposition.
- [x] Manifest
  `/private/tmp/bng3-ssts-nfsim-stratified-6-manifest-20260929.json`, SHA-256
  `f496ac88e72c9e0af0258e9e94e5a5f1d38a3dc55e2ce4c1570fad669d1ddf28`, records
  every accepted and excluded report hash, source hash, seed range, and engine
  revision. All six accepted reports use BNG3 `57e994d`; only documentation
  differs from the pinned full SSTS source head `bf210ab`.
- [ ] This is a six-structure stochastic sample, not full SSTS NFsim coverage
  or an all-SBML benchmark of the incomplete BNG2/legacy PyBioNetGen Atomizer.
  Perl BNG2 only emitted BNG-XML for standalone NFsim. Full curated BioModels
  validation remains stopped.

## Five-case SSTS NFsim cohort extension — 2026-09-29

- [x] Revalidated `stochastic/00035`–`00039` against the pinned suite at
  current BNG3 head `88e560b3bbe9cbed7e0f113f55913d27ac94208b`; all five
  individual records passed. For `00035`–`00038`, compared 200 independent
  BNG3-direct and 200 standalone-NFsim runs in each of flat and Atomized modes.
  All eight 22-point ensemble comparisons passed the 3 pooled-standard-error
  criterion, with zero run errors; the worst `|z|` was `2.26328`. This adds
  3,200 completed trajectories across dimerization and zero-order production
  structures.
- [x] `00039` passed the BNG3/libRoadRunner SSTS case check, but BNG2 timed out
  while generating NFsim XML from BNG3 Atomizer output in both modes at the
  benchmark's 60-second conversion limit. NFsim did not run for this case. A
  longer retry remained blocked in the same Perl conversion subprocess and
  was interrupted without producing a retry report. No BNG2 source was
  changed.
- [x] Manifest
  `/private/tmp/bng3-ssts-nfsim-independent-5-manifest-20260929.json`,
  SHA-256 `f5ed95a5547a51688f07a4fb48076f4cdf90c4b18357846ba9c4e97d2323dd1c`,
  records each SBML and per-case report digest plus the benchmark and engine
  provenance: BNG3 `88e560b`, BNG2 `8726b30`, standalone NFsim `c51c7a3`.
- [ ] This is a five-case stochastic sample, not full-suite NFsim parity or an
  all-SBML benchmark of the incomplete BNG2/legacy PyBioNetGen Atomizer. Perl
  BNG2 only generated the XML input used by standalone NFsim for the four
  completed cases. Full curated BioModels validation remains stopped.

## BNG3 NFsim benchmark initial-network export correction — 2026-09-29

- [x] Fixed `benchmarks/benchmark_atomizer_nfsim.py` to remove pre-existing
  executable BNGL action blocks before appending network-generation and XML
  export actions. `stochastic/00028` exposed the bug: its scheduled event
  changed `X` to about `20.3696` before Perl BNG2 wrote XML, while BNG3 direct
  started at `X=0`. The BNG3 harness now exports the initial network and keeps
  the external standalone-NFsim leg aligned with BNG3's initial state. No BNG2
  or PyBioNetGen source was changed.
- [x] Regression test verifies embedded `simulate` and `setConcentration`
  actions do not reach the export invocation, while generated network and XML
  actions do. Focused benchmark tests passed (`5 passed`); full BNG3 Python
  suite passed (`692 passed, 28 skipped`); Ruff, Black (`py39`), and
  `git diff --check` passed.
- [x] Re-ran `stochastic/00028`, `00029`, `00031`, and `00032` with 200
  independent BNG3-direct runs (seeds `1`–`200`) and 200 standalone-NFsim runs
  (seeds `201`–`400`) per mode. Both flat and Atomized comparisons passed for
  all four cases: 3,200 trajectories, 264 observable-time points, zero run
  errors, and worst `|z|` of `2.25284`. Case `00028` now passes both modes.
- [x] Manifest
  `/private/tmp/bng3-ssts-nfsim-action-export-fix-cohort-20260929.json`,
  SHA-256 `de11ade936077fc0256be40827ffa9ee12161bc0e87368d5675851f562db1218`,
  records each source/report digest, benchmark-script digest, seed range, and
  BNG2/NFsim provenance. The corrected per-case `00028` report is
  `/private/tmp/bng3-atomizer-nfsim-ssts-00028-independent-200runs-20260929-action-strip-fix.json`.
- [ ] This is a selected four-case BNG3 benchmark/export validation sample,
  not full SSTS coverage, full cross-engine parity, or an all-SBML benchmark.
  BNG2/legacy PyBioNetGen Atomizer remains incomplete and has not been
  benchmarked against all SBML. Perl BNG2 only generated the XML consumed by
  standalone NFsim. Curated BioModels validation remains stopped.

## BNG3 cross-engine initial-network export correction — 2026-09-29

- [x] Fixed `benchmarks/benchmark_atomizer_cross_engine.py` to strip existing
  executable action blocks before generating an initial network. Previously,
  an Atomizer action block suppressed the benchmark's `generate_network`
  action, allowing event or simulation actions to run while the report still
  described the result as an initial-network comparison. The shared stripping
  helper is in `benchmarks/bngl_utils.py`; the NFsim export harness uses it too.
  No BNG2 or PyBioNetGen source was changed.
- [x] Added a regression proving that embedded `simulate` and
  `setConcentration` actions are removed and one network-generation action is
  passed to the external engine. Red run failed on the embedded `simulate`;
  focused benchmark tests passed (`6 passed`). Full BNG3 Python suite passed
  (`692 passed, 28 skipped`); Ruff and Black (`py39`) passed.
- [x] Ran three repeats in flat and Atomized modes for SSTS stochastic cases
  `00028`, `00029`, `00031`, and `00032`. Modern BNG3 Atomizer produced 24/24
  valid network comparisons against Perl BNG2; all 24 structural and all 24
  rate-expression comparisons passed. These are initial-network comparisons,
  not event-execution or trajectory parity.
- [x] Manifest
  `/private/tmp/bng3-ssts-action-stripping-crossengine-manifest-20260929.json`,
  SHA-256 `2c775329c67cbb71e7abb548723b4bc47019ec5e0e1178f84732efac834dc5ee`,
  records source and report hashes plus BNG3, BNG2, and PyBioNetGen revisions.
  The bounded raw report is
  `/private/tmp/bng3-atomizer-cross-engine-ssts-action-export-4-20260929.json`,
  SHA-256 `5455479bc7e884c7b77d4e7b1e6a702fa493b91b83cd879aad7c55b06375e755`.
- [ ] The selected legacy PyBioNetGen outputs did not produce valid networks
  in this sample: flat outputs referenced undefined `nan` parameters, and
  Atomized conversion for `00031` and `00032` raised a legacy `TypeError`.
  This does not characterize all legacy inputs. BNG2/legacy Atomizer remains
  incomplete and has not been benchmarked against all SBML; no legacy source
  was changed. Curated BioModels validation remains stopped.

## Corrected-harness rerun of third 50-case cross-engine sample — 2026-09-29

- [x] Re-ran the same 50 pinned SSTS semantic inputs from the third selected
  sample with the corrected initial-network exporter at BNG3 head
  `1e0c1fb19b502fdc73d3388f465dcfc0ae3cad91`. Three repeats ran in flat and
  Atomized modes. Modern BNG3 converted all 300 inputs and generated all 300
  BNG3 networks; Perl BNG2 generated 228/300. All 228 paired networks matched
  structurally, and strict normalized rate parity passed 180/228.
- [x] The eight repeated BNG3/BNG2 rate mismatches remain
  `00330`, `00481`, `00687`, `00859`, `01084`, `01309`, `01719`, and `01822`.
  Independent PyBioNetGen converted 261/300 inputs; 39 conversions failed.
  Its paired networks matched structurally in 153/153 comparisons and passed
  rate parity in 141/153. Warnings and failed conversions remain in the raw
  report; neither reference checkout was modified.
- [x] Report
  `/private/tmp/bng3-cross-engine-third50-initial-network-fixed-20260929.json`,
  SHA-256 `fd54fc08d6c6f3f9fef7901fc9cfdb986027a683dcca9fd107b3a0a15943046f`.
  It records BNG3 `1e0c1fb`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`.
- [ ] This is a corrected 50-input interoperability sample, not trajectory
  parity, full SSTS cross-engine coverage, or an all-SBML benchmark.
  BNG2/legacy PyBioNetGen Atomizer remains incomplete and has not been
  benchmarked against all SBML. Curated BioModels validation remains stopped.

## Fourth selected 50-case cross-engine Atomizer sample — 2026-09-29

- [x] Selected 50 additional pinned SSTS semantic inputs, excluding the prior
  150 sampled inputs. Selection drew from the prior full-report passed surface
  and round-robined across available species/reaction-count bands. Ran three
  repeats in flat and Atomized modes. Modern BNG3 converted all 300 inputs and
  generated all 300 networks. Perl BNG2 generated 282/300 networks; all 282
  paired structures matched, and strict rate parity passed 246/282.
- [x] BNG2 network generation timed out for `01562` and errored for `01563`
  and `00255`. Six rate mismatches repeated across both modes and all three
  repeats: `01516`, `01395`, `00372`, `00562`, `01718`, and `00630`.
  Independent PyBioNetGen converted 252/300 inputs; eight model/mode groups
  errored (`01395`, `01101`, `00538`, `01091`, `00780`, `01102`, `00562`,
  and `00630`). Its paired networks matched structurally in 195/195
  comparisons and passed rate parity in 183/195; rate mismatches were
  `00372` and `00817`. Reference checkouts were not modified.
- [x] Selection manifest
  `/private/tmp/bng3-cross-engine-fourth50-manifest-20260929.json`, SHA-256
  `273aec56510a6a31179531525ce5890a2bd444fddb6c80848fa170adcdba10d4`;
  raw report `/private/tmp/bng3-cross-engine-fourth50-20260929.json`, SHA-256
  `1f1a0578053d30c1d2907642a2adb7450d3641f31d52c03876763ef9a42a1367`.
  Report records BNG3 `38b2b8c`, BNG2 `8726b30`, and PyBioNetGen `43b09a5`.
- [ ] This extends selected SSTS interoperability evidence; it is not
  trajectory parity, full SSTS cross-engine coverage, or an all-SBML
  benchmark. BNG2/legacy PyBioNetGen Atomizer remains incomplete and has not
  been benchmarked against all SBML. Curated BioModels validation remains
  stopped.

## Current-source audit of strict rate mismatches — 2026-09-29

- [x] Re-ran the seven cases with strict BNG2/PyBioNetGen rate mismatches in
  the fourth selected sample (`00372`, `00562`, `00630`, `00817`, `01395`,
  `01516`, and `01718`) at BNG3 source head `dc6fe0410849efa3b42ae0ca3f996c2a9b385237`.
  All seven per-case records passed, and their BNG3 CVODE / libRoadRunner
  comparisons passed for all observables at `t_end=1` with 10 intervals.
  Across the cohort, maximum absolute difference was `2.009e-7`; maximum
  scaled error was `0.02707` against the case-specific comparison tolerances.
- [x] The strict network mismatches include piecewise-expression simplification,
  function/parenthesis serialization, and numeric precision differences.
  Current BNG3/libRoadRunner trajectories do not show a BNG3 behavior failure
  for these cases, so no BNG3 implementation or comparator threshold was
  changed. This does not prove BNG2 or PyBioNetGen trajectory parity.
- [x] Summary
  `/private/tmp/bng3-crossengine-rate-mismatches-current-verification-dc6fe04.json`,
  SHA-256 `565f279db626a7c2b1e458804a9b3aecf423c53f78743817c6852a44a1d06c2f`.
  It links each individual report and digest. The isolated validator prints
  `core=FAIL` and exits 1 for these seven-case invocations because a partial
  selection cannot pass the full-core gate; each selected case record itself
  passed. No BNG2 or PyBioNetGen source was changed.
- [ ] This is a seven-case, `t_end=1` current-source cross-check, not full
  SSTS numerical conformance, trajectory parity against BNG2/PyBioNetGen, or
  all-SBML cross-engine coverage. BNG2/legacy PyBioNetGen Atomizer remains
  incomplete and unbenchmarked against all SBML.

## Current-head sdist-to-wheel install and ODE smoke — 2026-09-29

- [x] Built an sdist from BNG3 source head
  `a4f92c8e65cd2b2fe9beb1a00071ecf68d50ac4f`, then built a CPython 3.14
  macOS ARM64 wheel from that archive using cached ANTLR, SUNDIALS, and
  pybind11 source trees. The sdist excludes the pre-existing untracked
  `bng3-offline-bundle/`. Sdist SHA-256:
  `90025c175fe80315dcf480f33e318e856d74277ed8b007de305ae4bf34ea1544`.
  Wheel SHA-256:
  `422d28087f0a092a8114366a8334e426afde17db8075e3fed389e1d054eb5b2b`.
- [x] Installed the wheel into a clean CPython 3.14 venv. Package and compiled
  extension imports resolved inside that venv. `bionetgen --version`,
  `--help`, `info`, and `check` passed. The installed CLI ran
  `tests/python/models/simple_system.bngl` with ODE through `t=1`; output had
  11 rows, 7 columns, and all values were finite. TSV SHA-256:
  `b78c99a401d9e4071a1c3b98db8db2a913d86478995734ea28bb33d52cc7da6b`.
- [x] This offline build linked host NumPy, Click, and Packaging into the venv
  and used cached native dependency sources. It verifies this local sdist,
  wheel, installed CLI, and ODE path, not online dependency resolution.
- [ ] This is local macOS ARM64 evidence only. Cross-platform wheel builds,
  Windows executable artifacts, release qualification, GitHub release, and
  PyPI publication remain open. BNG2/legacy PyBioNetGen Atomizer remains
  incomplete and has not been benchmarked against all SBML; curated BioModels
  validation remains stopped.

## Historical open-PR review refresh — 2026-09-29

- [x] Refreshed PRs #26, #27, and #28 at their current heads. PR #26
  (`7b1d7ec`, base `148a031`) and PR #28 (`1a5008b`, base `d6eef9b`) each
  show 39 passing and 5 skipped checks. Their bases predate current `main`;
  PR #26 reports `DIRTY`, while #28 is still a draft. Release-only skips are
  not release qualification.
- [x] PR #27 (`b105d54`, base `148a031`) has 29 passing, 5 failing, and 7
  skipped checks. Its five C++ matrix failures all include the architecture
  inventory test rejecting the new
  `tests/cpp/test_nfcore2_parity.cpp` contract disposition. Windows also
  fails `OdeIntegrator preserves multi-species derivative updates` with a
  segfault. Its BNG3-vs-BNG2-network and BNG3-vs-NFsim jobs pass, but those
  bounded engine jobs do not establish Atomizer coverage over all SBML.
- [x] Source review of PR #27's NFcore2 driver found a correctness risk in
  `SsaDriver::canonicalPair`: it canonicalizes every pair with equal molecule
  type by slot, even though the two matcher root positions can carry different
  patterns. For asymmetric same-type reactants, the retained ordering can be
  the one that fails matching while the discarded ordering would match. A
  focused regression case is needed before accepting this implementation.
- [x] PR #28's helper patch preserves the existing substitutions and its
  current checks pass. `_REPLACE_CALLS_CACHE` is a process-global unbounded
  dictionary keyed by function name; bound it if names can grow from
  user-supplied or generated model symbols. PR #28 remains a draft.
- [ ] No PR was merged, edited, or commented on during this review. Current
  BNG3 work remains on `main`; legacy BNG2 code was not modified. The
  incomplete BNG2/legacy PyBioNetGen Atomizer has not been benchmarked against
  all SBML, and curated BioModels validation remains stopped.

## Current-head refresh of prior event-only SSTS cohort — 2026-09-29

- [x] Rechecked the 24 semantic cases previously unsupported for events at
  BNG3 `d9a349a82f28be78d4b7d0005d9a327a7f77d936`, using pinned SSTS commit
  `cf38585fac5de8e0e90112febb62851ee2181816`, `t_end=1`, and 10 intervals.
  Four selected case records pass (`00752`, `00758`, `00759`, `00887`); 20
  remain unsupported; none fail or time out. This is a selected cohort, not a
  full-suite rerun. Per-case reports and summary are under
  `/private/tmp/bng3-event-only-cohort-d9a349a`; summary SHA-256
  `63586ee1b25476c54156282d3c906a62e6b9e53ec81213eb9f8645a567df95f4`.
- [x] Traced `semantic/00374`'s exact quadratic event recurrence without
  changing source. Forty crossings are scheduled from `t=0.0327571` through
  `t=0.8789998988097419`; the final interval shrinks geometrically to
  `1.77e-12` (recent interval ratios are approximately `0.5`), after which
  the next crossing is below the scheduler's `1e-12` minimum. The finite-time
  event accumulation cannot be represented by a finite BNGL action list, so
  this case remains unsupported. Rank-two trajectory cases also remain
  outside the exact scalar proof; no proof guard was relaxed.
- [ ] Partial validator invocations report aggregate `core=FAIL` by design;
  case statuses above are per-record outcomes. This evidence does not establish
  full SSTS conformance, BNG2 parity, or broad SBML coverage. BNG2/legacy
  PyBioNetGen Atomizer remains incomplete and has not been benchmarked against
  all SBML. Curated BioModels validation remains stopped.

## Full pinned SSTS verification at current main — 2026-09-29

- [x] Re-ran all 1,923 canonical cases from pinned SSTS commit
  `cf38585fac5de8e0e90112febb62851ee2181816` against tracked-clean BNG3
  `1bfe6d3a1a238cc731328effc6c2fbd67f2026af`, isolated per case with a 120 s
  timeout, `t_end=1`, and 10 intervals. Results: `1,744 passed, 179
  unsupported, 0 failed, 0 timed out`; semantic `1,706/117` and stochastic
  `38/62` passed/unsupported. The supported-surface gate passes; aggregate
  Core remains open because unsupported cases remain.
- [x] Exact case-ID status comparison with the prior complete report from
  BNG3 `bf210ab73950646db655559ba2dd7aa56aeb2c15` found no changes among all
  1,923 cases. Current report:
  `/private/tmp/bng3-current-main-1bfe6d3-ssts.json`, SHA-256
  `b123d6fbe18e38de839aa2f32762f3c0910664c703a110899f2cd96767636736`.
- [ ] This validates BNG3 SSTS import/round-trip and BNG3/libRoadRunner checks;
  it is not full numerical SBML Test Suite conformance, full BNG2/PyBioNetGen
  parity, or an all-SBML benchmark of their Atomizers. BNG2/legacy
  PyBioNetGen Atomizer remains incomplete and unbenchmarked against all SBML.
  Curated BioModels validation remains stopped.

## Species-reference parameter ordering and bounded cross-engine sample — 2026-09-29

- [x] Reproduced hash-seed-dependent ordering of synthetic parameters generated
  from constant Level 2 `stoichiometryMath` species references. The unordered
  `folded_reference_ids` set was traversed while inserting into the ordered
  parameter collection. A subprocess regression test failed across hash seeds
  before the fix; sorting those IDs makes it pass. BNG3 source and regression
  test are in commit `007fa0f1612baf95a4bc3155e08666d3539dca35`.
- [x] At that exact BNG3 head, focused Atomizer tests passed (`5 passed, 108
  deselected`), and Ruff, Black, and `git diff --check` passed. Three SSTS
  records (`01516`, `01517`, `01562`) passed individually in the core validator
  under flat and Atomized paths. Partial validator invocations return exit 1
  because the aggregate suite gate remains open; each record reported
  `status=passed` and `core_passed=true` with tracked-clean source at
  `007fa0f`. Summary:
  `/private/tmp/bng3-stoichiometry-determinism-007fa0f/summary.json`, SHA-256
  `cf943489a42e4735f54c2e4d844b9d2a8dcc636ffb1b1d75bddbefb3ece75316`.
- [x] Repeated atomization for those three records under `PYTHONHASHSEED=1` and
  `2`; flat and Atomized output hashes matched across seeds for every record.
- [x] A separate three-repeat, 50-case SSTS cross-engine sample at BNG3
  `17e0eed` produced 300 BNG3-modern Atomizer/network successes; 282/300
  corresponding BNG2 network runs succeeded, with 282/282 structure matches
  and 246/282 strict rate matches. Legacy PyBioNetGen Atomizer succeeded on
  252/300 runs. These are bounded results, not full-suite parity. Reports:
  `/private/tmp/bng3-cross-engine-fourth50-current-main.json` (SHA-256
  `446357f83cab9b72a6fc047610f42d319ccbf53b99c92e081251162ff54ee4fac`) and
  `/private/tmp/bng3-cross-engine-fourth50-current-main-manifest.json` (SHA-256
  `72a1bcc6ba24f32cc028755d10a9edb4969b99033afaf81f3ea17d4f39c7e092`).
- [ ] The cross-engine sample predates the ordering fix and is not a rerun of
  the full sample at `007fa0f`. BNG2/legacy PyBioNetGen Atomizer remains
  incomplete and has not been benchmarked against all SBML. This result does
  not establish full SSTS, all-SBML, or curated BioModels parity; BioModels
  validation remains stopped.

## Exact-cohort cross-engine rerun after Atomizer determinism fix — 2026-09-29

- [x] Repeated the same 50 pinned SSTS inputs, flat and Atomized modes, and
  three repeats at current BNG3 `0f05ed16d643d8225439f1fc6d583ce64e164f73`
  (the Atomizer implementation is unchanged from `007fa0f`). BNG2
  `8726b30b94c081d5f0ce8b8d38338e27be1b38fc` and PyBioNetGen
  `43b09a5346402986d48b1defba5eaec0ae2f7802` were read-only references. The
  tracked BNG3 worktree was clean; the preserved offline bundle remains
  untracked.
- [x] Modern BNG3 succeeded on all 300 conversions and generated all 300 BNG3
  networks. BNG2 generated 282/300 networks; all 282 paired structures matched
  and 246/282 strict rates matched. Legacy PyBioNetGen converted 252/300
  inputs; its networks matched structurally in 195/195 paired comparisons and
  passed strict rates in 183/195. Every aggregate count matches the
  pre-fix-head rerun.
- [x] Modern Atomizer outputs now repeat byte-identically for all three
  affected cases (`01516`, `01517`, `01562`) in both modes. Their final hashes
  match the two-hash-seed verification recorded above. The other 47 sampled
  models' modern output hashes were unchanged; all modern network and parity
  outcomes were unchanged across the complete cohort.
- [x] Raw report:
  `/private/tmp/bng3-cross-engine-fourth50-post-determinism-007fa0f.json`,
  SHA-256 `ad6bb4d39cdbc80ec7db7801d0b03637d942d2a33f9c43bcc92f6a18154dbad7`.
- [ ] This is a bounded 50-model rerun, not full SSTS cross-engine coverage or
  an all-SBML benchmark. BNG2/legacy PyBioNetGen Atomizer remains incomplete
  and has not been benchmarked against all SBML. Curated BioModels validation
  remains stopped.

## Persistent simultaneous parameter-event assignments — 2026-09-29

- [x] BNG3 now lowers simultaneous parameter-only events that share a target
  only when both assignments evaluate to the same finite value under their
  own trigger-time snapshots or common execution-time state. Shared writes with
  different values remain unsupported. Trigger-target interference remains
  disqualifying for nonpersistent events; persistent events already in the
  execution queue are retained as SBML requires. Implementation and regression
  are in `6012f776c7a834cd03ee7bf7e82fd54b46973372`.
- [x] Regression was observed failing before the implementation, then passing
  with the fix. It checks two repeated, simultaneous timer events sharing
  `reset := time`, distinct counter updates through `t=0.02`, and continued
  rejection when those triggers are nonpersistent. The full Python suite
  passed `694`, skipped `28`, with `1,380` existing dependency/parser
  deprecation warnings. Ruff, Black (`py39`), and `git diff --check` passed.
- [x] Rechecked official SSTS cases `semantic/00965` and `semantic/00966` on
  the clean source commit. Both remain unsupported, as intended: each has
  simultaneously triggered, equal-priority, nonpersistent timer events that
  share `reset := time`. After one event resets the trigger, SBML requires the
  other nonpersistent queued event to be canceled; choosing an execution order
  would change its result. This follows the
  [SBML Level 3 Core event persistence rules](https://sbml.org/specifications/sbml-level-3/version-2/core/sbml-level-3-version-2-core.pdf).
  Per-case reports: `/private/tmp/bng3-00965-6012f77.json`, SHA-256
  `fec1e9af72cff014362fd26d8b74d19edf486bef231209445e4161aa8ccd4aba`; and
  `/private/tmp/bng3-00966-6012f77.json`, SHA-256
  `064774d27ed6fba397f85c3c1c45a50275f3cd49de7ad36b888cfa7bc7e2d48f`.
- [ ] This exact, persistent-event capability adds no SSTS pass in the current
  unsupported cohort; the two similar official cases are nonpersistent and
  remain fail-closed. It does not claim full SSTS/event support, all-SBML
  Atomizer coverage, BNG2/PyBioNetGen Atomizer completeness, or BioModels
  validation. BNG2 code was not changed; curated BioModels validation remains
  stopped.

## Current-head pip artifact build — 2026-09-29

- [x] At source commit `0b1ca8145d61c758ec0383b687adc098ac06595f`, built
  both an sdist and a CPython 3.14 macOS ARM64 wheel with
  `python -m build --no-isolation --sdist --wheel`. Sdist SHA-256:
  `c6e4c556deb0f3908012461bb8d5aa6eaba961c963384de9b14d7a892934cca0`;
  wheel SHA-256:
  `766f87ebfc8ab4a22e5bdc7418906dea0aba3c26b20dfb1159484e5ac90f1bdb`.
- [x] Installed the wheel with `pip install --no-deps` into a CPython 3.14
  venv. With Python site hooks disabled and the venv site-packages selected
  explicitly to bypass the host's global editable BNG3 path, both the Python
  package and compiled extension imported from the installed wheel. The
  installed CLI's `--version`, `--help`, and `atomize --help` commands passed.
- [x] With the installed wheel selected and `libsbml` import explicitly
  blocked, the installed CLI atomized official SSTS `semantic/00389`; BNG3's
  native `check` command accepted the generated BNGL. This verifies the modern
  parser's basic SBML path without libSBML on this sample. BNGL SHA-256:
  `ca118fe37aa6144e17c0372abcf02fae06997efcfa6c6da2cdea893e43241bd3`.
- [ ] This verifies local sdist/wheel construction and selected installed
  import, CLI, and Atomizer paths only. It does not validate dependency
  resolution or an installed ODE simulation. Cross-platform artifacts,
  Windows executable, release qualification, GitHub release, and PyPI
  publication remain open. BNG2 and legacy PyBioNetGen Atomizer remain
  incomplete and have not been benchmarked
  against all SBML; no BNG2 code was changed. Curated BioModels validation
  remains stopped.

## BNG3 event AST execution gates — 2026-09-29

- [x] Reproduced that direct construction of BNG3's ODE, PLA, and PSA
  simulators accepted a model containing `bng3_events` even though those
  backends do not execute event semantics. Added fail-closed checks to all
  three constructors, the NFsim AST adapter, the action-dispatch NFsim route,
  and the Python NFsim binding before its optional XML fallback. NFsim's
  direct adapter now returns the specific event capability reason.
- [x] Added regressions for all four direct construction APIs. Each regression
  failed before the change and passes afterward. Full configured C++ build
  passed; CTest passed all 452/452 tests. The Python binding containing the
  NFsim guard compiled as part of the full build. `git diff --check` passed.
- [ ] This is a BNG3 execution-safety correction only. No Atomizer behavior or
  SSTS status changed, and no SBML cohort was rerun. It establishes neither
  BNG2 parity nor all-SBML coverage. BNG2 code was not modified; its legacy
  Atomizer remains incomplete and unbenchmarked against all SBML. Curated
  BioModels validation remains stopped.

## Current-main threshold-event cohort refresh — 2026-09-29

- [x] Revalidated the ten previously unsupported threshold-trigger cases
  `00393`, `00394`, `00444`, `00445`, `00450`, `00451`, `01071`, `01073`,
  `01074`, and `01076` against BNG3 `4b35e958672c6da20683257c00a2eabe6edb9245`
  and pinned SSTS `cf38585fac5de8e0e90112febb62851ee2181816`, at `t_end=1`
  with 10 intervals. All ten remain unsupported; there were no failed or
  timed-out cases. Per-case reports are
  `/private/tmp/bng3-threshold-refresh-4b35e95-<case-id>.json`.
- [x] Source inspection with the BNG3 Atomizer parser resolves the variable
  first-reactant stoichiometry to 2 in all ten models. Their two reaction
  vectors are `(-1,-2,1)` and `(1,1,-1)`, so the event-driving dynamics are
  rank two. These cases are outside the existing scalar quadratic trajectory
  proof; no trajectory assumption was loosened.
- [ ] This cohort refresh adds no Atomizer or SSTS capability. It is selected
  event triage, not full SSTS or all-SBML validation. BNG2 code was not
  modified; the legacy BNG2/PyBioNetGen Atomizer remains incomplete and has
  not been benchmarked against all SBML. Curated BioModels validation remains
  stopped.
