# BNG3 current progress

**Refreshed:** 2026-10-10 UTC against RuleWorld/BNG3 main
`9a1de7ed7fb617df4cf8828748de45fac486e14e`. Semantic convergence and release
qualification remain incomplete. The authoritative backlog is issues
[#132–#186](BNG3_CONVERGENCE_DONE_CHECKLIST.md): 46 open and nine closed
(#133/#134/#135/#136/#145/#165/#169/#173/#183).

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
| #133/#173 | #190/#191 | Native-compiled static mass-action JAX ODE, fixed-step RK4; public JAX SSA explicitly unavailable. Installed CPU qualification satisfies these scoped issues; functional/time-dependent rates and adaptive integration remain unsupported. |
| #134 | #128/#204 | Combined parser grammar reuse, cardinality guards and pyparsing 3.0.9 fallback. Source-only shape/fallback checks pass; same-cardinality equality asymmetry remains pre-existing. |
| #135/#136 | #187/#189 | Current issue-linked ledger and corrected architecture/validation claims. Closed after review; historical reports remain historical. |
| #140 | #207/#220 | Compile-owned numeric max_iter/max_agg, fractional/negative aggregate thresholds and product-only filtering. Broader protocol typing remains open. |
| #141/#142 | #203/#211 | Worker identity, graph-cache race repairs, compartmental seed association and exact species identity. Broader isolation and backend graph encoding unification remain open. |
| #144/#145 | #200/#214 | Shared fail-closed BNGsim capability boundary, adapter ON/OFF agreement and scoped steady-state options. No default backend promotion; #145 closed. |
| #138/#163 | #196/#197 | Compile-owned units and version-aware SBML units; broader runtime migration/export qualification remains open. |
| #146 | #210/#215 | Deletion scope, pending waits and output clocks. Strict native -oSteps endpoint comparison remains red. |
| #147/#148 | #219 | Whole-species DestroyComplex, same-complex matcher constraints and native index-width refusal. Runtime tests use an action adapter; production ActionIR execution and formal correspondence remain open. |
| #153–#155 | #209/#212/#213/#217 | Narrow parser-free BNGIR v0.2 import, strict envelopes and boolean-reference rejection. Full structural round trips remain open. |
| #165/#166 | #194/#198 | All-input Lean reference matcher and bounded packing/native guards; #165 closed, production lowering correspondence remains open. |
| #169 | #192 | Proof trust accounting and harness qualification. Closed after review. |
| #171/#172 | #193/#208 | Legacy positional run compatibility and defaults/version without optional Cement. Broader public matrix and legacy retirement remain open. |
| #182 | #199/#216 | Numerical/expression/export CI wiring and source-selected harness isolation; scientific acceptance remains open. |
| #183 | #206 | Budgeted locked SSTS CI, per-case classifications/digests and permanent receipts. This bounded workflow issue is closed; full #159 qualification remains open. |

Root merged #187, #219, #206, #193, #208, #190, #191, the combined #128/#204 stack, and #220 during this continuation.
PR #205 integrated the Rasi performance port separately. The shared checkout
remains on perf/nfsim-rasi-translation-port-v2 at `07ea87d3`, with its unrelated
untracked audit file preserved. Work continues in isolated checkouts. Only root
may merge reviewed changes or close satisfied issues; release/publication remain
unauthorized.

## Current qualification receipts

- max_agg #220: exact source `ffd4043a8798dd20d708b26b1e370c6a294b371d`,
  merge `9a1de7ed7fb617df4cf8828748de45fac486e14e`. Root reviewed the five-file
  diff and reran five focused CTests. Four Python regressions passed in verified
  source mode; an earlier auto-mode run resolving an installed extension was
  excluded. Seven fresh probes against clean pinned BNG2 cover arithmetic,
  negative/fractional thresholds, seed/product filtering and empty products.
  Quoted numeric-prefix coercion stays explicitly unsupported. Direct Python
  max_iter/default behavior is preserved; no new max_agg API keyword. Hosted
  Linux C++, Lean, SSTS and compatibility checks passed at integration; other
  C++/parity jobs were still running/queued. No full #140 completion.
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
| #132 | #130 `2f05ce2e` | Preserved isolated main merge plus scoped time-function repair in progress; retain integrated whole-deletion bond suppression. New scoped-time acceptance is not qualified by old-head CI. |
| #143 | #201 `95075d19` | ODE dependency classification. Root reran 22 ODE cases and 124 compiler cases successfully; independent review in progress. Coefficient/RHS checks against five pinned live BNG2 models are separate from frozen SSA failures. |
| #137 | #195 `e530328e` | Capability inventory; policy/owners remain unapproved. |
| #179 | #202 `78543775` | 14 approvals pending; strict validation intentionally reports 14 errors. |
| #174 | #188 `9456b290`, #218 `65e8ef09` | Performance candidates need source review and controlled measurements; green checks alone are insufficient. |

## Unchanged stop conditions

- Frozen `michment` SSA: 10/306 points outside three pooled standard errors,
  worst |z| about 9.3449 at ScT. Fresh pinned BNG2 reproduced all 200 golden
  files. Preserve seeds, horizons, tolerances, exclusions and goldens while
  investigating source/harness/output/RNG behavior.
- NFsim strict pinned native `-oSteps`: final-row mismatch on four deletion
  fixtures remains red. Supplemental `-oTimes` agreement and passing unchanged
  distributional checks are separate evidence; receipts remain under
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

Continue existing candidates and explicit issue dependencies. Three Luna max helpers
are reviewing shared rates, runtime reuse/invalidation and the preserved XML/rate
slice. Preserve exact source/artifact/oracle identity, commit tested checkpoints,
and update this ledger after integration. Do not create a replacement roadmap.
