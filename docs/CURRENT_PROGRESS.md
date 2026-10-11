# BNG3 current progress

**Refreshed:** 2026-10-11 against RuleWorld/BNG3 main
`af6afb00279a236031dc50afde452a6bfb913175`. Semantic convergence and release
qualification remain incomplete. The authoritative backlog is issues
[#132–#186](BNG3_CONVERGENCE_DONE_CHECKLIST.md): 44 open and eleven closed
(#132/#133/#134/#135/#136/#145/#165/#169/#173/#182/#183).

The [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) maps all 55 tasks
one-to-one. Issues own acceptance criteria, dependencies and detailed evidence;
unassigned work has no implied review owner. The
[repository audit](REPOSITORY_AUDIT_2026-10-07.md) is a dated source snapshot.
Historical [progress](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/CURRENT_PROGRESS.md)
and [checklist](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md)
retain the earlier reports.

## Integrated acceptance slices

A bounded repair does not close its broader issue.

| Issues | Merged PRs | Scope and remaining boundary |
| --- | --- | --- |
| #132 | #130 | Scoped constant/live assignment rates, XML rule parity and reporting repairs; exact-head installed BNG2 and all three platform corpus gates pass. Broader rate semantics remain open in #143. |
| #133/#173 | #190/#191 | Native-compiled static mass-action JAX ODE, fixed-step RK4; public JAX SSA explicitly unavailable. Installed CPU qualification satisfies these scoped issues; functional/time-dependent rates and adaptive integration remain unsupported. |
| #134 | #128/#204 | Combined parser grammar reuse, cardinality guards and pyparsing 3.0.9 fallback. Source-only shape/fallback checks pass; same-cardinality equality asymmetry remains pre-existing. |
| #135/#136 | #187/#189 | Current issue-linked ledger and corrected architecture/validation claims. Closed after review; historical reports remain historical. |
| #140 | #207/#220/#236 | Compile-owned numeric max_iter/max_agg and product filtering; merged PR [#236](https://github.com/RuleWorld/BNG3/pull/236) adds validated finite ODE/SSA n_steps expressions. Broader protocol typing and shared CLI/Python semantics remain open. |
| #141/#142 | #203/#211/#222/#224 | Worker identity, graph-cache race repairs, compartmental seed association and exact species identity. Concurrent ODE instances with distinct rate snapshots have a shared-topology contract; serial scan exceptions restore base/dependent parameters and the original network before successful analytic/fresh-model recovery. Broader invalidation/lifecycle and graph encoding unification remain open. |
| #144/#145 | #200/#214 | Shared fail-closed BNGsim capability boundary, adapter ON/OFF agreement and scoped steady-state options. No default backend promotion; #145 closed. |
| #138/#163 | #196/#197/#228/#230/#233/#237 | Compile-owned units and version-aware SBML units; NET has an independent Network3 analytic consumer contract. Observable projection preserves graph-prefix context, counting modes, inert Molecules qualifiers and qualified Species CountUnique termination; #237 explicitly rejects unsupported Counter/Fraction kinds before opening the NET destination, without adding runtime support. Broader runtime migration/export qualification remains open. |
| #139 | #225 | Compiler-owned direction-specific whole-deletion and typed DeleteMolecules hooks drive compatibility execution; full kernel retirement remains open. |
| #151 | #231 | Verified static zero-order physical count rates and bound parameter updates in one explicit positive 3D compartment. Physical XML fallback refuses; broader molecularity, unit seeds and dynamic contexts remain unsupported. |
| #143 | #201 | Typed ODE dependency classification and time/state reevaluation; broader backend scope, propensity and cache-invalidation criteria remain open. |
| #146 | #210/#215/#235/#238 | Deletion scope, pending waits, output clocks, canonical leading %label: XML scope and direct-NFsim compiled local-function binding. Independent native checks now cover four scoped cases; the original unmapped conditional remains unsupported, composite XML is not native parity, and strict native -oSteps final-endpoint rows remain red. |
| #147/#148 | #219 | Whole-species DestroyComplex, same-complex matcher constraints and native index-width refusal. Runtime tests use an action adapter; production ActionIR execution and formal correspondence remain open. |
| #153–#155 | #209/#212/#213/#217/#226/#227 | Narrow parser-free BNGIR v0.2 import, strict envelopes and boolean-reference rejection; seed-only zero-reaction models execute static ODE/SSA. Direct-builder malformed dense IDs, boolean references and nonempty known unsupported top-level sections now reject; broader structural round trips and nested validation remain open. |
| #165/#166 | #194/#198 | All-input Lean reference matcher and bounded packing/native guards; #165 closed, production lowering correspondence remains open. |
| #169 | #192 | Proof trust accounting and harness qualification. Closed after review. |
| #171/#172 | #193/#208 | Legacy positional run compatibility and defaults/version without optional Cement. Broader public matrix and legacy retirement remain open. |
| #182 | #199/#216 | Required numerical/expression/export and scheduled/manual frozen ensemble CI wiring, exact-source package/native/worker checks and permanent receipts; #182 closed. Scientific stochastic and historical NFsim qualification remain open. |
| #183 | #206 | Budgeted locked SSTS CI, per-case classifications/digests and permanent receipts. This bounded workflow issue is closed; full #159 qualification remains open. |

Root merged #187, #219, #206, #193, #208, #190, #191, the combined #128/#204 stack, and #220, #201, #222, #188, #224, #226, #227, #130, #228, #225, #231, #230, #233, #235, #236, #237, #238 plus ledger refreshes #221/#223/#229/#232 during this continuation.
PR #205 integrated the Rasi performance port separately. The shared checkout
remains on perf/nfsim-rasi-translation-port-v2 at `07ea87d3`, with its unrelated
untracked audit file preserved. PR #236 is a merged, bounded #140 slice; the
umbrella issue remains open. Work continues in isolated checkouts. Only root may
merge reviewed changes or close satisfied issues; no release publication is
authorized.

## Current qualification receipts

- Observable scope/counting #233: exact source `e03a750108330cf0f5434184db05bb741ac7c5e7`,
  merge `9bf28a0b0b89d30560f5920339101b2d5ef82de1`, tree
  `ccec8ad7c6ca6d38e8826d9972119601f187e80e`. Root/fresh Luna reviewed
  required candidate compartment context and per-term typed prefix IDs in the
  NET, C++ and regulatory graph writers. A prefix miss yields zero before
  Species predicates; qualified Species CountUnique stops even when false,
  matching pinned BNG2. NET groups reuse the compile-owned projection.
  Final clean-head cached Release validation: 11 native cases/93 assertions,
  count-filter contracts 2/18 and 18 strict exporter/NET round-trip/independent
  Network3 tests (37 deselected) pass. Architecture check passes with 41 explicit
  compatibility files. Inverting the prefix-ID comparison caused eight assertions
  in four cases to fail; restoring source returned all 93 assertions to green.
  CLI SHA256 `ed2a30a170860e6b74610d13c069de49a9631396b2b607ae464b1ec7f4caf35b`.
  Independent fixtures use pinned BNG2 `9601746` and locally source-rebuilt
  Network3 `9f39d22e`; the latter is not the separately locked binary artifact.
  At merge: five hosted successes, 12 in progress, one neutral and one skip;
  these are separate from local exact-head evidence. All-explicit-node coverage
  is a validity guard. Zero-count `<1` coverage uses the AST API; CLI grammar
  still rejects that form. Full generated solver consumption, installed package
  qualification and general compartment correspondence remain open. Outer AST
  dependencies remain; #138/#142/#163 stay open. The final #233 hosted Python
  matrix is red in 18 jobs across Python 3.9–3.14 on Ubuntu, macOS and Windows;
  the failures are the same Counter/Fraction `unknown compiled observable kind: At`
  error. The separate #235 PR-event [Linux Python 3.12 job](https://github.com/RuleWorld/BNG3/actions/runs/38152302145/job/114510215542)
  at exact head `b54ed0076166003b9f1a5c0af241b512a71e136d` reproduces the same
  two failures, with 1,142 passes, 58 skips and two xfails. Merged PR #237 adds the bounded fail-closed and destination-preservation
  behavior; its PR-head checks were absent after retargeting.
- Observable-kind fail-closed repair #237, merged
  [PR #237](https://github.com/RuleWorld/BNG3/pull/237)
  ([root review](https://github.com/RuleWorld/BNG3/pull/237#issuecomment-6113295483)):
  exact source `9561dd058519ce0d10f301bd56a1a752e167b1b1`, merge
  `e3dc33a4d272d621b2f969f1423253468f884a64`, base
  `eeb22cb4fed34a71f9ef11b904cf3963c2bfc981`, three files, tested tree
  `c4cc8d2a7655c54663c658935d4353c0aefb31a8`. Unsupported `Counter` and
  `Fraction` remain unsupported; NET now fails before opening the destination,
  preserving an existing file or leaving a missing output path absent. Root's
  restored source-mode qualification passed 36 Python tests (9 observable-type,
  27 BNGIR), 34 strict CLI tests (37 deselected), and 93 native projection
  assertions across 11 cases; the architecture scan found 41 explicit
  compatibility files. Inverting the unknown-kind predicate failed seven
  tests while two passed; restoring it returned the focused Python/native
  checks to green. PR-head hosted checks did not rerun after retargeting. At the
  2026-10-11 20:44:36 UTC query, merge commit `e3dc33a4` had Formatting
  patch, Lean semantic kernel, CodeQL and Cross-tool parity passed. Its CI run
  reported nine successes and 22 queued jobs, no failures, and remained queued
  overall ([run 38171605273](https://github.com/RuleWorld/BNG3/actions/runs/38171605273)).
  No full hosted matrix or #138 closure is claimed.
- Local-function XML scope #235: exact source
  `b54ed0076166003b9f1a5c0af241b512a71e136d`, merge
  `bc952d4f76235d4710de9528a76505f99ccb664d`. The canonical leading `%label:`
  header is compiled as species-level local-function scope; XML binds both
  directions from checked scope metadata and refuses missing or ambiguous
  anchors. Restored focused qualification: NFsim adapter 138 cases/1,592
  assertions, XML writer 11/47, ODE options 23/132, projection 11/93, 18 strict
  exporter checks passed (37 deselected), and the architecture scan found 41
  explicit compatibility files. The review mutation failed two assertions before restoration. This covers
  the canonical prefix form only; installed packaging remains unqualified,
  and strict native `-oSteps` final-endpoint rows remain red. The final #235
  PR hosted-check aggregate at exact source
  `b54ed0076166003b9f1a5c0af241b512a71e136d` was 22 successes, 18 failures and
  7 skips. Run 38152302145 is that pull-request workflow; its [Linux Python
  3.12 job](https://github.com/RuleWorld/BNG3/actions/runs/38152302145/job/114510215542)
  reports 1,142 passes, 58 skips and two xfails, including the Counter/Fraction
  failures above. Full #146 remains open.
- C++ observable coefficients #230: exact source `bfbeeff497097da76539024b86d7055e0c01a99e`,
  merge `4795179ef16ae679d58e03e03444c28fc079b1fd`. Root/fresh Luna reviewed
  the shared-projection migration and repaired valid Molecules qualifier refusal:
  Molecules thresholds are inert in BNG2, while Species predicates stay active.
  Root preserved the unit artifacts and reused that cached build at the exact PR
  tree `1b1c0a5b00e00e0ac2ca3236cc72e5d7d28419ec`, avoiding another full build.
  Native projection 6 cases/49 assertions, existing ODE count-filter contracts
  2/18, strict live pinned-BNG2 exporter 10 tests and the architecture scan
  with 41 explicit compatibility files pass.
  CLI SHA256 `59dba6c49a93e8ed22569eeb1bf9f66f4d08ef710b43bbb9024fb9bcafb0d2c8`.
  Oracle inputs require the locked revision/script digest, clean tracked tree and
  no index-hiding flags; emitted coefficients match independent BNG2 group rows.
  At merge: three hosted successes and eleven pending checks. This is observable
  emission, not full generated CVODE solver consumption or general compartment
  correspondence. Outer AST dependencies remain; #138/#142/#163 stay open.
  NET groups were not qualified at that checkpoint; #233 supplies the bounded
  shared-projection repair above.
- CI wiring #182: root/fresh Luna accepted the existing #199/#216 implementation
  after [manual run 38076443040](https://github.com/RuleWorld/BNG3/actions/runs/38076443040)
  executed exact source `dfc4ba9cdefa62c96617d26ddba93151ef16b2be`.
  Installed source/git/expected head, package/native/model and worker identities
  verified on Linux Python 3.12.15; worker 1, assignment 32, live BNG2 network 5
  and required RHS/ODE/SSA determinism/export 60 tests pass. Three frozen
  200-member cohorts executed: two pass, michment fails with unchanged 10/306
  violations and worst |z|=9.344938257977688 at ScT. Both JUnit reports have
  zero skips/errors; the scheduled report explicitly records one failure.
  Native SHA256 `1965bfde6cc8269eaef95acb159033fd38f262e141f8f293496b6c25bbeecd8e`;
  CLI `a57825af859fc18a54245d38cd67c08fcad5132e1d69f9c8a6b00e216ac310ad`.
  The [permanent receipt](../tests/validation/evidence/issue182-parity-linux-py312-dfc4ba9.tar.gz)
  retains original JUnit, identity, limitations and four internal checksums;
  archive SHA256 `d4313dd1266d71646a0739ad492b461f4ad3af7aad1956f4f3535af8d124c999`.
  Overall workflow FAILED: historical NFsim also has three failures/three errors
  in 74 tests (v17 scoped-rate rejection, v19 parser errors, r21 statistics and
  empty-reference assertions). Source/oracle follow-up classifies v17 as a
  canonical leading `%x:` scope/serialization defect; v19 is malformed source
  accepted with a warning by BNG2; r42/r43 are missing XML input artifacts in the
  historical harness; r21 remains unresolved without retained trajectories. No
  seeds, retries, cohorts or thresholds changed. #182 closed for wiring with these reds retained;
  #146 and broader numerical qualification remain open. Later #231/#230 are
  excluded from this artifact, as is #233. #202's 14 provenance approval decisions stay pending.
- Physical units #231: exact source `4637d8e340c8fdc1004e3a7e8d6ce7de996d4fc1`,
  merge `35af757ae1143d1679d63317859b2b3220f18374`. Root/fresh Luna review
  repaired time/volume, capability/raw-lowering disagreement, aliases/mixed
  rates, geometry, parameter lifecycle, overflow and XML fallback admission.
  Final native adapter 136 cases/1,574 assertions, units 7/41, parser units 21/141,
  XML writer 8/32, forced-XML CLI gate and targeted source-mode Python checks pass.
  Root's guarded Python direct API returns [0,2,4,4] at [0,1,2,3], seed42;
  module SHA256 `09f57276889decb8f7fb9222b92eba7c4a9cbcb29cee80750cacfeb7f6c5f3d4`,
  CLI `37c9799ca223fd9899653ab2f426bfe7874a1d6df4602daacb22aa308e3cf789`.
  Fresh pinned BNG2 count-model XML `d0563b3a5bc38f1ac0079f9da57c7ae513ad666eee9ce1c6916d379dbcae9c4f`
  records rounded value=1.2044282, expr=1.204428152; pinned native NFsim explicit
  times agree with direct gdat SHA256 `cf9fe03790a4e6a249c6d4178d621e1aff9284e05acb081a5f716cda8d0bc5df`.
  Analytic native propensity asserts prove the conversion separately; this
  fixed-time agreement does not prove full stochastic or -oSteps equivalence.
  One explicit positive 3D-volume static zero-order subset only. Source-mode,
  not an installed wheel. At merge: five hosted successes, one neutral, one
  scheduled skip and 13 pending checks. Broader #151 remains open.
- Typed deletion #225: final synced source `0094dfe9f249fd6f2caa026d49006f980112258f`,
  merge `dfc4ba9cdefa62c96617d26ddba93151ef16b2be`. Root/fresh Luna review
  preserves #130's orphan guard. Final 19 native cases/276 assertions,
  architecture ratchet 41 and four fresh full-network comparisons against pinned
  BNG2 pass. Root independently regenerated both engines' networks; parameter,
  species/count and complete reaction/rate fields agree. CLI SHA256
  `6d1e38f74c821a8f185bbe39bbc8942bc754729f22f3b532065ac0b8d7e4a2af`.
  Final-head hosted snapshot: 41 successes, one neutral, five skips, no failures
  or pending checks. This migrates deletion decisions, not the full AST kernel;
  #138/#139 remain open.
- NET consumer #228: exact source `bd41199fbf08e4b484c4303f2ee6adc640bab829`,
  merge `0bf3a0446f46515b6ab09ed54d90f4e6fac228a4`. Root reviewed and reran
  the strict test on the tested #130 CLI against independent pinned-source Network3;
  one pass, 40 deselected. Local full export file: 33 passes, eight API/native skips.
  The local Network3 rebuild digest differs from the lock's binary artifact.
  [Exact-head installed parity](https://github.com/RuleWorld/BNG3/actions/runs/38074830773/job/114279587382)
  verifies source/git/PR head and package/native/model/worker identities; native
  SHA256 `b7897fcd2d20faf58c9eeefa412fa8f178b4fa32c6bbca4320d967483d6bc552`.
  Worker 1, assignment 32, network 5 and required parity/export 60 tests pass;
  three scheduled ensembles deselected. At merge: 17 successful checks, one
  scheduled skip and 22 pending platform/Python checks. Final exact-head snapshot
  has 41 successes and five skips, no failures or pending checks. No full #163 closure.
- Assignment/XML #130: exact source `5f2b5c1fd01d1bbeaa3a9bc9aa61a2393e0dae81`,
  merge `7f6b1969d369171064ff01e29ac4d5cb6d266996`; #132 closed after review.
  Local 32 assignment, 71 strict CLI corpus, five live pinned BNG2 network and
  106 comparator/CI contracts pass. Root read the exact-head installed
  [parity log](https://github.com/RuleWorld/BNG3/actions/runs/38053916751/job/114218464840):
  source/git/PR head agree; package/native/model and spawned worker identity
  verified, 32 assignment contracts, five original networks and 59 required
  parity tests pass. Three scheduled ensemble tests were deselected on the PR.
  Ubuntu, macOS and Windows each pass 71 corpus tests with no failures/errors/skips.
  Final exact-head snapshot: 42 successful checks, five scheduled/release skips,
  none pending. Linux Python 3.12.15 native SHA256
  `f6f88bcb95635727632bb6923ee296a4783a49a18685197f229295c85f953c86`;
  CLI `065a5f20ba90c40e19d0c03bae7b05d6218caddd2c46eb7d3dbaf4b83b84af70`.
  Scoped time ODE has analytic evidence where BNG2 only supplies a network oracle.
  Frozen michment and strict NFsim endpoint discrepancies remain open.
- Native BNGIR validation #227: exact source
  `25b12456eb012584da5752cca7d8eaa3e9e3b1eb`, merge
  `3accee429183a7f6c8a15e4f075daf1b25757233`. Root/fresh Luna review and
  four modules on a freshly built candidate native extension: 115 passes,
  two existing population-map xfails. Raw native calls reject boolean/invalid
  indices, duplicate/misordered IDs and nonempty known unsupported sections.
  macOS CPython 3.14 native SHA256
  `ed40bd2d54bc7c71f68f0c0754f6b9dda66578a66b95ca6c1c845cc71eb0b6c2`;
  source-mode qualification, not an installed wheel. Hosted jobs were pending
  at merge. Unknown fields/deeper nested validation and broader #155 remain open.
- Scan exception cleanup #224: exact source `18c4245eb394fd0c9537b06f5dacbbfa7c4941c2`,
  merge `c1210f170459444043edf1747b2c7d102c2745fc`. Root/fresh Luna review
  and root's guarded full scan suite passed all 11 tests. The runtime failure
  follows parameter mutation/cache clear; base and dependent parameters and exact
  network identity restore, then analytic/fresh-model trajectories agree.
- Seed-only BNGIR #226: exact source `e8c1dac8589f313fe7a5555ce39ae1209c2e477c`,
  merge `7536f6ae7dc6acb02a1b2134c589fafe7e01cc68`. Root/fresh Luna review;
  root reran four BNGIR modules: 91 passes and two existing population-map xfails.
  Import forbids parsing/rendering, preserves structural/semantic equality,
  generates one species/zero reactions, and executes static ODE/SSA trajectories.
  At least one seed and other malformed/unsupported gates remain required.
  Both slices used candidate Python with the recorded b842 native extension:
  source C++ b842 is byte-identical to their integration baselines (480/c121).
  Native SHA256 `620f40b6be5fcc40b71edee602188407c7bed6680b734bd7e24bd23c3aea17e5`.
  These are source-mode receipts, not freshly installed current-head artifacts;
  hosted jobs were queued/in progress at merge. Broader #141/#153/#154 remain open.

- Shared rates #201: exact source `b8428dc6fe1f8ebbdd3189ff430777c350abb9af`,
  merge `dbf1dac0faaf2b2cfdd65d09e1da54c80aae5ad3`. Focused ODE 22/120,
  compiler 124/2,572,270 and reaction-rule 14/239 tests passed, plus 75 verified
  source-mode Python backend tests. Root reran six live pinned BNG2 RHS items
  at the final source with cached goldens disabled and source=perl asserted.
  CLI SHA256 `8653f9283912719e3d6ff842a28e3975b362fb1ea5749c677277a56f6306da69`;
  native `620f40b6be5fcc40b71edee602188407c7bed6680b734bd7e24bd23c3aea17e5`.
  Final-head hosted native, Python, corpus, JAX and parity checks passed;
  release-only jobs were skipped. No full #143 closure.
- ODE reuse #222: merge `3118fa66a7fa33ebc066bd940ebac9f12e727faa`, test-only
  source `8d1d0005442c75acdab6867c896ae91f81419900`. Root verified b842 source
  cpp/python equals integration main dbf1, then ran all ten scan contracts with
  the proposed test on that verified runtime. A guarded file entry point passed;
  an earlier stdin launch failed worker startup and is excluded. The older
  installed source9712 receipt remains historical. This qualifies independent
  parameter snapshots sharing unchanged topology, not concurrent mutation,
  broader topology/volume invalidation, exception cleanup or NFsim lifecycle.
- CPython 3.14 full CPU suite and parallel-scan diagnosis: the run was launched
  from commit `ed49cfa3a6dc4144a20b26357f600cbef2b7899c` plus a frozen three-file
  #237 fail-closed patch. That patch content was later committed as source
  `9561dd058519ce0d10f301bd56a1a752e167b1b1` with tested tree
  `c4cc8d2a7655c54663c658935d4353c0aefb31a8`; the suite was not run from a clean
  checkout of that final source head. It reported 1,208 passed, 28 skipped, two
  xfailed and 10 failed. For eight subprocess tests, the global editable finder
  resolved package modules from the shared Anaconda installation at `07ea87d3`;
  those results do not qualify the source checkpoint. The other two failures
  occurred before worker startup because a stdin-launched pytest process could
  not be re-imported as `<stdin>` by multiprocessing. On the separate base-
  `e3dc33` plus two-file NFscope prototype, root reran those same two scan tests
  through a guarded file-based entry point without changing source, tests or
  tolerances: two passed, nine were deselected, in 0.63 seconds. Existing tests
  assert source/native/worker identity. The eight shadowed checks still need an
  isolated installed-package run; the full suite remains red and is not full-suite
  qualification for #237 or main.
- Direct-NFsim compiled local-function scope #238, merged
  [PR #238](https://github.com/RuleWorld/BNG3/pull/238)
  ([root review](https://github.com/RuleWorld/BNG3/pull/238#issuecomment-6113492546)):
  exact source `4566e38b33ed5536fbd758ef7d976a9f33d51629`, merge
  `af6afb00279a236031dc50afde452a6bfb913175`, base
  `e3dc33a4d272d621b2f969f1423253468f884a64`, tested tree
  `c7f058957666691f76df422404ce41bba9f196b0`. The code binds compiled
  local-function scopes to the intended molecule occurrences for direct NFsim.
  Final restored source-mode qualification passed 142 NFsim cases/1,621
  assertions, XML writer 11/47, ODE options
  23/132, observable projection 11/93, 36 Python tests, 34 strict CLI tests
  (37 deselected), and the architecture scan with 41 explicit compatibility
  files. The scope-inversion mutation produced two failures across 29 assertions
  while both control cases passed; restoring the candidate returned the focused
  checks green. The pinned independent native receipt passed four scoped cases
  (prefix, mapped M1, RP1 M2 and RP2 M2); M2/RP2 M2 also matched six exact
  seed-17 rows. The original unmapped conditional remains unsupported by native
  NFsim. The new composite direct test passes, but native NFsim rejects the
  same-source BNG2 XML with `ObservableRefinComposite` (exit 1), so that case
  is not an independent parity pass. During the 2026-10-11 20:49:40–20:49:44 UTC
  exact-head PR check refresh for `4566e38b33ed5536fbd758ef7d976a9f33d51629`,
  the rollup was 14 successes, 3 in progress, 1 neutral and 1 skipped ([PR checks](https://github.com/RuleWorld/BNG3/pull/238/checks)).
  The separate main push at merge `af6afb00279a236031dc50afde452a6bfb913175`,
  checked during the 2026-10-11 20:49:40–20:49:44 UTC refresh, showed CI queued,
  CodeQL and Cross-tool parity in progress, and Lean semantic kernel passed
  ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38173018621),
  [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38173018637),
  [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38173018628),
  [cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38173018623)).
  No installed-package qualification is claimed; strict `-oSteps` final-endpoint
  rows remain red, and full #146 remains open.

- max_agg #220: exact source `ffd4043a8798dd20d708b26b1e370c6a294b371d`,
  merge `9a1de7ed7fb617df4cf8828748de45fac486e14e`. Root reviewed the five-file
  diff and reran five focused CTests. Four Python regressions passed in verified
  source mode; an earlier auto-mode run resolving an installed extension was
  excluded. Seven fresh probes against clean pinned BNG2 cover arithmetic,
  negative/fractional thresholds, seed/product filtering and empty products.
  Quoted numeric-prefix coercion stays explicitly unsupported. Direct Python
  max_iter/default behavior is preserved; no new max_agg API keyword. Hosted
  Linux C++, Lean, SSTS and compatibility checks passed at integration. All native
  C++/ASan/parity, Python and corpus checks subsequently passed; release-only
  jobs were skipped. No full #140 completion.
- Simulation n_steps #140, merged [PR #236](https://github.com/RuleWorld/BNG3/pull/236)
  ([merge review](https://github.com/RuleWorld/BNG3/pull/236#issuecomment-6113249716)):
  exact source `ed49cfa3a6dc4144a20b26357f600cbef2b7899c`, merge
  `eeb22cb4fed34a71f9ef11b904cf3963c2bfc981`, base
  `bc952d4f76235d4710de9528a76505f99ccb664d`. All five source files matched
  the restored green identity before the formatting-only commit. Static finite
  ODE/SSA actions use compiled, validated counts; parameter-backed expressions
  resolve after argfile merge and earlier
  protocol mutations; `^` is refused as Safe-Perl XOR. PLA/PSA/NF keep their
  existing path. Verified source-mode checks: 16 action regressions passed, C++
  reaction-rule expansion 23 cases/387 assertions, and architecture scan with
  41 explicit compatibility files; pinned BNG2 and candidate produce eight
  intervals (nine rows) for `2**3`, while the prior BNG3 baseline produced six
  intervals.
  The numeric-literal `2**3` result is the pinned-BNG2 parity case. Separately,
  a BNG3 execution-time protocol mutation to N=4 yielded 17 rows for `2**N`; this
  is a BNG3 regression/count result only, not dynamic-action parity against
  pinned BNG2. The separate dynamic-N probe exposes an unresolved unqualified
  Safe-Perl identifier boundary: pinned BNG2 leaves `k=1`, while BNG3 evaluates
  `k=8`; the 17-row result does not validate a 16-row expectation. The
  inverted-condition
  mutation failed focused assertions and the restored candidate passed. Pinned
  Black 26.10.0, Ruff 0.15.1 and the final local formatting checks passed. During
  the 2026-10-11 20:49:40–20:49:44 UTC exact-head PR check refresh for source
  `ed49cfa3a6dc4144a20b26357f600cbef2b7899c`, the rollup was 21 successes,
  14 failures, four in progress, one skipped and one neutral; all 14 failing
  jobs were Python-platform jobs ([PR checks](https://github.com/RuleWorld/BNG3/pull/236/checks)).
  The Linux Python 3.12 job in run 38170926789 had exactly the Counter/Fraction
  failures, with 1,142 passed, 58 skipped and two xfailed ([job](https://github.com/RuleWorld/BNG3/actions/runs/38170926789/job/114565376022)).
  This pre-#237 hosted snapshot is not full-matrix qualification. This is a
  partial #140 slice; broader typed
  protocol values, shared CLI/Python semantics, defaults/invalid-option coverage
  and installed-package qualification remain open.
- Parser #128/#204: combined source preview on main `f4adb7b7` passed 68 parsed
  field/text comparisons against baseline on actual pyparsing 3.0.9 and 3.3.2;
  root independently reran 68 round trips and separator/fallback/cardinality
  assertions on 3.3.2. Three-run alternating microbenchmarks improved 580 parses
  from median 2297.387ms to 252.987ms and 50 unequal 300/299-molecule comparisons
  from 3091.732ms to 0.288ms. These are source-only microbenchmarks, not native
  or full-application qualification. #128's 41 successful/five skipped checks
  do not qualify #204's exact stacked head, which had no hosted checks. The
  old branch had no dispatch trigger; retargeting #204 starts combined checks.
  Both landed atomically through #204 at `f917a3a7a706bc80b9cc15ed5dd793ab3ef19a95`.

- JAX: exact combined source `7e3e3d5cfe078b1a450f28e1d4a2eeb26db65e9e`
  has the same tree as merged main `58654f3b`. The
  [installed CPU lane](https://github.com/RuleWorld/BNG3/actions/runs/38000802875/job/114058116699)
  verified source/package/model/native identity with Linux Python 3.12 and
  JAX/JAXlib 0.11.2: 25 tests with x64 disabled, 20 ODE tests with x64 enabled.
  Wheel SHA256 `a27d46468757aa72ce59333f8f6ca2515ad8ae0d91cb15733553a1aa6dbbfd70`;
  native SHA256 `3049ae440e0706b7fbbaf9b73a1971d903492e883efcdae257b786ba382d085f`.
  Exact-head C++, ASan, 18 Python, three corpus, integration and sdist-smoke
  jobs passed. The whole exact-source dispatch subsequently completed successfully,
  including all four wheel platforms; release jobs were skipped. CUDA compilation/CPU fallback do not qualify GPU execution.
- NFnext #219: final source `58f097e8d829df752179cf1df3ee2301742e5cbe`,
  merge `a9b9d7e143888aafbd674f5778815d1294fcebe8`. Root reran 15 architecture
  contracts with effective Release assertions after two review-found repairs.
  Independent pinned BNG2/NFsim probes distinguish whole-species deletion,
  DeleteMolecules and connected/disconnected pattern matches. Exact fixtures,
  commands and digests are in the PR. Simultaneous replacement stays refused;
  the test-only runtime adapter does not establish production ActionIR execution.
- Compatibility #193/#208: fresh isolated macOS arm64 CPython 3.14.7 wheel of
  source `9712ba30b28c8dc27f70e7a61e4bdb04761ede28`: 227 helper-installed passes,
  106 independent root API/CLI/worker/notebook checks. All 167 tracked package
  files and installed paths verified. Wheel SHA256
  `0aa91cc3973dc047a32cc00d66cf8d124335ca7867b4fce0f8ec60f5ceb2d108`;
  native SHA256 `e49be78a04fc4be943b91d1dbf3b08fd42fe8512243d313acd80dd4915a94849`.
  Positional run semantics checked against canonical PyBioNetGen
  `28bf351a9bbfc197e19487c26dedda683716bb64`. Non-None timeout stays unsupported.
  This is that candidate's artifact, not a new wheel of current main.
- SSTS #206: exact source `13344aa4cb480d30e0dcb6f324f67c0d58dd775d` passed
  [run 37996312024](https://github.com/RuleWorld/BNG3/actions/runs/37996312024).
  Locked suite `cf38585fac5de8e0e90112febb62851ee2181816`; unchanged 32/1,923
  selection: round-trip/RoadRunner 32 passed, official 31 passed/one unsupported
  scheduled-action case, zero failures/timeouts. Full-suite flags remain false.
  The final receipt-only commit `67e5f4a7` adds
  [the permanent archive](../tests/validation/evidence/ssts-ci32-linux-py312-13344aa4.tar.gz),
  SHA256 `4e8d5ca5c1f850efac7cfdd0ee697474025520852eeaec660dea7c2560f9802e`.
  Root verified six internal digests and reran 73 gate/CI contracts. Later main
  integrations are not automatically qualified by this receipt.

Historical main `dd23c267` completed 46 successful/two skipped hosted checks.
Its previous local installed receipt had 178 passes/two existing xfails and
required an external pinned BNGsim dylib through DYLD_LIBRARY_PATH; it does not
establish current artifact identity or self-contained packaging. Queued,
skipped, synthetic-merge and historical checks must stay distinct from exact-head
execution.

The closure audit found no accepted disposition for #146/#154. Both remain
reopened with their full unmet criteria:
[#146](https://github.com/RuleWorld/BNG3/issues/146#issuecomment-6089843989),
[#154](https://github.com/RuleWorld/BNG3/issues/154#issuecomment-6089844484).

## Candidates under review

| Issues | PR / head | Qualification boundary |
| --- | --- | --- |
| #137 | #195 `e530328e` | Capability inventory; policy/owners remain unapproved. |
| #179 | #202 `78543775` | 14 approvals pending; strict validation intentionally reports 14 errors. |
| #174 | #188 merged; #218 closed as superseded, former head `2f51b79f` | #188 was narrowed to a bounded 128-entry function-call regex cache and merged after root/Luna review; slower copy changes were removed. #218’s branch and commits are preserved. Broader representative speed/memory qualification remains open. |

The [initial #188 review](https://github.com/RuleWorld/BNG3/pull/188#issuecomment-6093309268)
and [initial #218 review](https://github.com/RuleWorld/BNG3/pull/218#issuecomment-6093309400)
record the historical overlapping copy regressions and unbounded cache. Those
findings motivated the narrowed #188 candidate. Five alternating fresh-process
runs measured a 4.9% median gain for 40,000 function expansions and a 1.6% median
gain for 200 existing event-fixture exports, with identical output hashes. These
are source-level workload measurements, not native simulation or broad application
speed claims. The representative export difference is inconclusive for noise. Final-head native, Python, corpus, parity and package-smoke checks pass;
release-only jobs were skipped. Root merged exact head
`67b46804d0be63636bca28b59967f2075f9e1bc8` as
`2c3ebf2126071e2a0189ab2d537f768239ff519d`; the
[final review](https://github.com/RuleWorld/BNG3/pull/188#issuecomment-6097669630)
records source-only test limitations and excludes broad speed/RSS claims.

## Unchanged stop conditions

- Frozen `michment` SSA: 10/306 points outside three pooled standard errors,
  worst |z| about 9.3449 at ScT. Fresh pinned BNG2 reproduced all 200 golden
  files. Preserve seeds, horizons, tolerances, exclusions and goldens while
  investigating source/harness/output/RNG behavior.
- NFsim strict pinned native `-oSteps`: final-row mismatch on four deletion
  fixtures remains red. For the unchanged whole_species fixture, root/Luna traced
  the pinned native `System::sim` fallback: accumulated sample 2.0000000000000004
  skips the in-loop endpoint, then writes after a post-horizon firing (93 events
  versus 92 in stepTo/direct). The [causal review](https://github.com/RuleWorld/BNG3/issues/146#issuecomment-6093362793)
  retains the red strict gate; BNG3 horizon semantics are unchanged. Supplemental
  `-oTimes` and distributional checks remain separate; receipts remain under
  `tests/validation/evidence/`.
- Reference pins: BNG2 `9601746f8884ed19ab2acea49fe87fc4660ace46`;
  NFsim `9b00d42f734dcc3e695205600f12cae5b44d1daa`. BNG3-generated artifacts
  cannot serve as independent oracles for BNG3.
- #165 proves the Lean reference matcher, including exact embedding domains
  and mapping equality independent of association-list order. No `sorry`,
  new axiom or hidden premise; #166 production lowering remains unproved.
- Full curated BioModels #162 remains stopped until explicitly authorized.
  CUDA #175 requires actual NVIDIA hardware. #195 policy/owners and #202's
  14 approval decisions remain unresolved.

Continue existing candidates and explicit issue dependencies. Current work covers
NET group counting/compartment investigation and classification of the historical NFsim failures.
The bounded unit/deletion checkpoints are integrated; higher-order units and
remaining writer/runtime consumers still need qualified slices. Preserve exact source/artifact/oracle identity,
commit tested checkpoints and update this ledger after integration. Do not create
a replacement roadmap.
