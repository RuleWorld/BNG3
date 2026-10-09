# BNG3 current progress

**Reviewed:** 2026-10-08. **Implementation baseline:** main `e1836c3274e685996d5e86883761e00e98257e09`.
**Status:** integration is substantial; semantic convergence and release
qualification remain incomplete.

The [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) is the current
55-item issue index. The [repository audit](REPOSITORY_AUDIT_2026-10-07.md) records
scope and source evidence. The old progress log is preserved at its
[audited revision](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/CURRENT_PROGRESS.md).

## Verified at the implementation baseline

| Evidence | Result | Limit |
| --- | --- | --- |
| Exact-head hosted checks | 46 successful, 2 skipped | Configured scope, not full convergence. |
| Skipped jobs | PyPI publishing; scheduled historical NFsim | No release or historical-suite claim from those jobs. |
| Local architecture ratchet | Pass; 43 compatibility files | Transitional AST dependencies remain. |
| Local corpus checks | Pass; 106 model records, manifest current | S=10, P=106, NF=4, expression=5; X=0, B=0. |
| Local strict provenance | Fail; 14 approval/lock errors | H01 must resolve decisions and evidence. |
| Local Lean static/header gates | Pass; 37 Lean files | Static validation is not kernel checking. |
| Local native NFnext contract | 18/18 pass | Bounded matcher/transformation fixtures. |
| Hosted Lean kernel/Smoke/Coverage/axiom gate | Pass | No general production-C++ refinement theorem. |

Exact-head runs: [CI](https://github.com/RuleWorld/BNG3/actions/runs/37548838421),
[parity](https://github.com/RuleWorld/BNG3/actions/runs/37548838423),
[Lean](https://github.com/RuleWorld/BNG3/actions/runs/37548838419).
These results describe the baseline above; reread checks for any later SHA.

## Pushed checkpoints and resumed work

Work resumed on 2026-10-08 in isolated checkouts with Luna max workers.
No PR was merged. The live resumption snapshot has 54 open audit issues and one closed
review/disposition issue (#134). An open PR is a candidate, not an integrated
baseline or automatic issue closure. The issue acceptance criteria still govern.

| Issue | PR and recorded head | Evidence and remaining boundary |
| --- | --- | --- |
| #132 | [#130](https://github.com/RuleWorld/BNG3/pull/130), `2f05ce2e` | Assignment-rate parity repair; 509 CTest, focused Python and independent BNG2 checks pass. Hosted snapshot: 40 success, 5 skipped. |
| #133 | [#190](https://github.com/RuleWorld/BNG3/pull/190), `dbffdda2` | JAX ODE uses native compiled rates; installed targeted and x64 tests pass. Static supported subset; dynamic/local functions remain explicit refusals. |
| #173 | [#191](https://github.com/RuleWorld/BNG3/pull/191), `9525d908` | Broken JAX SSA prototype removed; explicit unavailable result, undefined-name lint and JAX CPU CI. Stacked on #190. |
| #134 | [#128](https://github.com/RuleWorld/BNG3/pull/128), `2cf7f6eb`; [#204](https://github.com/RuleWorld/BNG3/pull/204), `dd75fe28` | Review completed at `d0d695d7`; subsequent automated edits reintroduced a pyparsing 3.0.9 molecule-list defect. Separate stacked repair: reproduced failure, then 5 parser/regression tests pass with current and actual 3.0.9 pyparsing. Review both PRs together. |
| #135 | [#187](https://github.com/RuleWorld/BNG3/pull/187) | Current issue-linked checklist and this handoff; documentation does not qualify scientific behavior. |
| #136 | [#189](https://github.com/RuleWorld/BNG3/pull/189), `50d754e3` | Stale architecture/validation claims corrected; formal blocker index now includes #166 and distinguishes #198 bounded packing candidate from the general production correspondence gap. Historical results retain dates and limits. |
| #137 | [#195](https://github.com/RuleWorld/BNG3/pull/195), `e530328e` | Capability inventory and decision worksheet; policy and review ownership remain unapproved. |
| #138 | [#196](https://github.com/RuleWorld/BNG3/pull/196), `24241dbc` | Resolved unit metadata plus compiled-model energy export guard; AST allowlist 43 → 42 → 41. Final guard slice: 129 energy and 16 SBML/unit checks pass; actual exporter refusal and false-positive boundaries covered. Guard compatibility wrapper compiles per call; broader runtime migration remains open. |
| #140 | [#207](https://github.com/RuleWorld/BNG3/pull/207), `082e66ae` | Compile-owned typed generate_network.max_iter, consumed by execution; preserved default 100/direct Python numeric overrides. Pinned BNG2 probes exposed 1+1 truncation and negative unsigned wrap. Arithmetic dialect is explicitly bounded; divide-by-zero hidden by exponentiation was reproduced and repaired. Final focused 12 CTests and Python override 1 pass; broader compiler checks belong to preceding checkpoint. Other action options/dispatch remain untyped. |
| #163 | [#197](https://github.com/RuleWorld/BNG3/pull/197), `6d44354f` | SBML version-aware unit attributes/defaults and unit-aware seed counts; 33 SBML/unit checks and libSBML fixture with zero diagnostics. Stacked on #196; broader Tier-X inventory/consumer qualification remains open. |
| #165 | [#194](https://github.com/RuleWorld/BNG3/pull/194), `c5fafad0` | General Lean reference matcher soundness/completeness, using the user-approved exact-domain and order-independent mapping contract. Kernel/Smoke/Coverage and axiom audit pass; production C++ correspondence is separate. |
| #169 | [#192](https://github.com/RuleWorld/BNG3/pull/192), `a4e14bdb` | Trust accounting and scheduled/manual mutation harness; earlier `0ee57fe3` evidence remains 32/32 harness cases and 56 CI contracts. Docs-only synchronization records #194 all-input reference matcher/axioms and #198 bounded packing separately from main; retain both audit-script entry sets during integration. |
| #166 | [#198](https://github.com/RuleWorld/BNG3/pull/198), `5cc1fd57` | Checked declaration IDs and NFIR packing widths; native bridge and Lean packing theorems pass. Full production rule-lowering refinement remains unproved. |
| #171 | [#193](https://github.com/RuleWorld/BNG3/pull/193), `b99c231c` | Windows notebook path assertion and macOS/Python 3.9 libSBML architecture failures repaired; 89 focused installed tests and 55 CI contracts pass. Replacement 5.21.1 wheel verified as arm64. Earlier independent RoadRunner/notebook qualification remains scoped; new platform checks require final-head results. |
| #141 | [#203](https://github.com/RuleWorld/BNG3/pull/203), `cacee1ab` | Fixed reproduced shared-iterator races in graph reset/index and map lookup; instrumented ASan 13 cases/129 assertions plus 20 concurrent repeats. Worker initialization binds and checks parent Python/native paths; 9 source and 9 clean-installed scan tests pass, including shadowed sources and 2D workers. Broader graph/topology/solver/NFsim isolation remains unqualified. |
| #143 | [#201](https://github.com/RuleWorld/BNG3/pull/201), `d4019f96` | Typed ODE rate dependency classification; 21 ODE cases, 118 compiler-contract cases and 6 independent BNG2 RHS checks. Cross-backend local scopes/propensities remain open. Frozen michment SSA remains 10/306 outside 3 pooled SE, worst |z| 9.3449. Fresh pinned BNG2 reproduces all 200 golden bytes; macOS C rand initialization under seeds 1–200 biases the first wait (0.03473 versus expected 0.00467). Source/probe receipts and analytic conditioning are in [#143](https://github.com/RuleWorld/BNG3/issues/143#issuecomment-6069308392); controls and red gate are unchanged. |
| #145 | [#200](https://github.com/RuleWorld/BNG3/pull/200), `d9227862` | Final-head requalification: adapter ON finite 8 cases/34 assertions and adapter 8/41; OFF finite 8/34; Python dispatch 9; architecture CTest 1/1 in each build, unchanged 43 entries. Pinned BNGsim source and loaded library hashes verified. No broad numerical parity or backend-promotion claim. |
| #179 | [#202](https://github.com/RuleWorld/BNG3/pull/202), `78543775` | Live immutable source verification, fresh pinned BNG2/NFsim builds, smoke artifact receipts, Linux dependency hashes and compiler-image manifest. 79 provenance/corpus/CI contract tests pass; 14 actual approvals remain pending. Corpus selection is unchanged; its source-lock digest is refreshed. Linux execution and release-gate wiring remain open. |
| #182 | [#199](https://github.com/RuleWorld/BNG3/pull/199), `4996311d` | Repaired the zero-job hosted workflow failure: runner.temp expressions moved from forbidden job-level env to step env. Actionlint reproduces the old failure and passes the repair; final strict-head checkout/preflight follow-up passes 65 CI/wiring contracts. Hosted run at PR head `58a6641d` executes 59 required parity tests plus one worker identity check; scheduled ensembles skip. Actual checkout was synthetic merge `c9b9b49b`, with verified identical Git tree `e935910f`; final `4996311d` now checks out the declared SHA and requires it to match actual Git HEAD; its new hosted numerical execution is pending. Frozen ensembles unchanged. |
| #183 | [#206](https://github.com/RuleWorld/BNG3/pull/206), `42f61aa0` | Pinned, hashed Linux Python 3.12 inputs; 32-case official-reference workflow with bounded workers and durable artifacts. Local semantic checkpoint `5f9a7b9d`: round-trip/RoadRunner 32 pass; official 31 pass/1 unsupported; all 32 worker identities match. 69 contracts and 64 runner/trigger checks pass. Broader Python at `5d6fc641`: 1009 pass/34 skip/1 xfail. Hosted setup fixture failure reproduced/repaired; final exact-head Linux run [37854179945](https://github.com/RuleWorld/BNG3/actions/runs/37854179945) passes: round-trip/RoadRunner 32, official 31 pass/1 unsupported. Source SHA equals checkout HEAD, all 32 worker native hashes match, artifact digests verified. Full-suite flags remain false. |

Historical pre-resumption snapshots recorded #128/#190 with 41 successful
and 5 skipped checks, and #130/#189/#192/#194/#196 with 40 successful and
5 skipped checks at their preceding heads. Those counts do not validate the
new revisions above. Newer work has pending checks; stacked #191/#197/#204
had no recorded rollup in that snapshot. The initial #202 lint
failure was a stale corpus source-lock digest, repaired without changing model
selection. The initial #200 architecture failure is corrected without expanding the allowlist, and its final-head functional evidence is now recorded. The #199 zero-job workflow failure and #206 setup fixture failure were reproduced and repaired; those fixes do not themselves prove hosted numerical execution.
Neither a skipped job nor absent rollup is a pass. Requery the final candidate
SHA after any push, rebase or integration.

## Continuing dependency order

1. Review current PRs against every issue criterion and integrate in dependency
   order: #190 before #191, #196 before #197, #128 with #204. Reconcile the
   formal documentation in #189/#192 with unmerged #194/#198 evidence now
   reconciled. Preserve both matcher and packing axiom-audit entries when
   synchronizing #194/#198, and keep #197 synchronized with the new #196 head. Verify exact-head
   required checks; do not infer permission to merge from this plan.
2. Resolve actual capability/support decisions (#137), scientific/formal review
   owners (#185), and source/oracle/toolchain/dependency approvals (#179).
   Wire strict provenance into release qualification after substantiated
   decisions; do not approve by changing strings alone.
3. Finish trustworthy baseline qualification: qualify #143 reference RNG/seed/platform behavior after the reproduced
   first-wait bias, broaden #141 isolation beyond the repaired worker paths,
   and qualify the newly executable #182 numerical lanes. Keep seeds, horizons,
   tolerances and goldens unchanged until the cause is established.
4. Continue dependency-ready canonical runtime tasks (#138–#140) and structural
   BNGIR integration (#153–#156), then the finite-backend decision (#144),
   graph identity (#142), and NFsim/NFnext/hybrid/unit tasks (#146–#152).
   Select each next issue from its current explicit dependencies.
5. Follow those semantic boundaries with events and SBML/export qualification
   (#157–#164), production formal correspondence (#166–#170), and proven Python
   compatibility retirement (#172). Curated BioModels work (#162) remains
   stopped until explicitly authorized; historical SSTS totals are not current
   official conformance evidence (#159/#183).
6. Measure stable paths and qualify performance/hardware (#174–#178), then
   complete reconciliation, corpus, packaging and release criteria (#180–#186).
   CUDA qualification (#175) requires actual NVIDIA hardware, not a no-toolkit
   build. Reopen the relevant issue before each task; do not create a second
   backlog or treat this priority framework as new acceptance criteria.

## Maintaining current state

Keep implementation details, owners, dependencies and closure evidence in the
linked issues. Update this page only for a new verified baseline or a material
scope change. Preserve exact revisions, skipped gates and the distinction
between theorem, fixture, independent oracle and release evidence.
