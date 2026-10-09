# BNG3 current progress

**Refreshed:** 2026-10-09 UTC. **Live implementation baseline:** main
`030f7beda88fd764af849805dc0ee8d551804277`, after PR #205 merged at
`2026-10-09T03:42:32Z`. The qualification table below records the earlier
audited main baseline `e1836c3274e685996d5e86883761e00e98257e09`; it is not a
full requalification of main after #205.
**Status:** integration is substantial; semantic convergence and release
qualification remain incomplete.

The [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) is the current
55-item issue index. The [repository audit](REPOSITORY_AUDIT_2026-10-07.md) records
scope and source evidence. The old progress log is preserved at its
[audited revision](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/CURRENT_PROGRESS.md).

## Historical qualification at the audited baseline

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

Work resumed on 2026-10-08 in isolated checkouts with Luna max workers. At the
live refresh, 54 audit issues remain open and review/disposition issue #134 is
closed. PR #205, from GitHub branch `perf/nfsim-rasi-translation-port` at
`07ea87d3e186c7529558f290d466cbc8fcd68196`, merged at
`2026-10-09T03:42:32Z` and advanced main to `030f7beda88fd764af849805dc0ee8d551804277`.
The shared implementation checkout remains on local branch
`perf/nfsim-rasi-translation-port-v2` at `07ea87d3`, with
the unrelated untracked `docs/REPOSITORY_AUDIT_2026-10-07.md` preserved. PR #187's
prior pushed documentation checkpoint was `3860a00b4b8797ed15643f4f2f4cadf5794f7c42`;
its recorded validation matrix below predates the #205 integration. Audit PRs
remain candidates, not automatic issue completion; the live issue criteria
still govern.

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
| #146 | [#210](https://github.com/RuleWorld/BNG3/pull/210), `b4c38fdc5406c9216004adc703a2bef11ef21f7d` | Based on post-#205 main `030f7bed`. Whole-pattern deletion now preserves connected context until removal; DeleteMolecules removes every named molecule, and unsupported conditional partial deletion declines direct construction. Existing matcher decision is reused by compiler-owned scope metadata and writer/NFsim consumers. Final local C++ NFsim 131 cases/1451 assertions, including 65 deletion/reverse assertions; network 40/5, rule expansion 22/9, run-network 1/1, architecture CTest 1/1 and unchanged 43-entry ratchet pass. Clean installed Python 3.12 wheel: 24 deletion/seed checks, 6 existing direct/XML parity checks (6 deselected), 3 XML/architecture checks pass; native SHA-256 `fd2563743f3feedfde92e7e09ab9cf3350f8d6d77f55b9ed01bf58eb150c35df`. Independent BNG2 `9601746f` emits XML, native NFsim `9b00d42f` executes it (binary SHA-256 `7621bb850efc6cf203ec2c42004c2cffcc0115af7e3ce03d62aabab100bf31a1`). Four fixed-seed comparisons FAIL only at final row 20: native CLI reports 7 remaining A molecules versus 8 from the API; earlier samples agree. Each unchanged 200-run pooled-SE check has 0/84 violations, worst |z| about 2.9968. Strict probe intentionally exits 1 and retains every endpoint/control. Committed receipt `tests/validation/evidence/nfsim-deletion-cfdc91e.json` records executed source `cfdc91e3`; The first pushed `adb3f620` hosted C++ lanes failed one reader fixture that depended on admitting unsupported conditional BNGL. Final `b4c38fdc` preserves all reader assertions using a public native descriptor fixture, adds direct-source refusal coverage, and passes 297 reader assertions/34 cases (root independently reran 8/2 conditional controls); it adds no conditional NFsim runtime support. Production backend code is unchanged from `5ddecd5f`; the later commits add tests, probe and evidence. New exact-head hosted qualification remains pending. This does not qualify the broader #146 surface or NFnext's separate deletion lowering. Preserve these guards when integrating #130's reordered XmlWriter. |
| #153 | [#209](https://github.com/RuleWorld/BNG3/pull/209), `7722d31f68a1dfd23641c646efc73a821eca5c04` | Stacked on #196 at `24241dbc`. Explicit keyword-only `from_bngir(..., native=True)` route imports a narrow v0.2 class directly, without rendering or parser fallback: plain metadata, numeric/parameter arithmetic, site-free molecule declarations/seeds and one-pattern-to-one-pattern forward expression-rate rules. At initial `e97de69c`, the clean regular CPython 3.14 arm64 wheel run passed 61 tests with 2 existing xfails. Root review then reproduced blank seeds/rules in BNGL and missing molecules in XML export. Final `7722d31f` rejects source-dependent export, visualization and action paths before artifacts are created; native NFsim calls require the direct route and cannot enter XML fallback. Finite RHS/ODE and v0.2 serialization remain supported. Final installed-wheel checks: 81 pass, 2 existing xfails (bond-marker ordering and population-map vocabulary), no skips, plus 5 NFsim route controls (66 deselected); Root installed-wheel reruns passed the 12 initial native-import tests and all 32 final native-import tests. The A()→B() fixture produced two species/one reaction and RHS (-10,+10) at A=100, k=0.1; v0.2 serialization round-tripped exactly. Final wheel SHA-256 `5dce182aec20e5800df0d9e83792850fe435090fecb5235b472eb6035af50378`; installed `bngir.py` SHA-256 `bcc47649986c04c195b3974fdb5f9022c2b65cf72d84ba2507d397772637cb89`; final extension SHA-256 `639935e35b9e25c696a2e72443fb6ee3888c0d56c7ea8a4b1c7f7d1eb67895ff`. The isolated venv disabled system-site packages and had no editable finder; CMake reused symlinks into the primary checkout's verified pinned dependency cache (ANTLR 4.13.2, Catch2 v3.4.0, pybind11 v2.13.6, SUNDIALS v7.6.0), not private source copies. Public preflight validates input; the private C++ builder trusts that preflight. Typed observables and the remaining structural/model families are unqualified; no independent BNG2 parity or full #153 completion is claimed. |
| #140 | [#207](https://github.com/RuleWorld/BNG3/pull/207), `082e66ae` | Compile-owned typed generate_network.max_iter, consumed by execution; preserved default 100/direct Python numeric overrides. Pinned BNG2 probes exposed 1+1 truncation and negative unsigned wrap. Arithmetic dialect is explicitly bounded; divide-by-zero hidden by exponentiation was reproduced and repaired. Final focused 12 CTests and Python override 1 pass; broader compiler checks belong to preceding checkpoint. Other action options/dispatch remain untyped. |
| #163 | [#197](https://github.com/RuleWorld/BNG3/pull/197), `6d44354f` | SBML version-aware unit attributes/defaults and unit-aware seed counts; 33 SBML/unit checks and libSBML fixture with zero diagnostics. Stacked on #196; broader Tier-X inventory/consumer qualification remains open. |
| #165 | [#194](https://github.com/RuleWorld/BNG3/pull/194), `c5fafad0` | General Lean reference matcher soundness/completeness, using the user-approved exact-domain and order-independent mapping contract. Kernel/Smoke/Coverage and axiom audit pass; production C++ correspondence is separate. |
| #169 | [#192](https://github.com/RuleWorld/BNG3/pull/192), `a4e14bdb` | Trust accounting and scheduled/manual mutation harness; earlier `0ee57fe3` evidence remains 32/32 harness cases and 56 CI contracts. Docs-only synchronization records #194 all-input reference matcher/axioms and #198 bounded packing separately from main; retain both audit-script entry sets during integration. |
| #166 | [#198](https://github.com/RuleWorld/BNG3/pull/198), `5cc1fd57` | Checked declaration IDs and NFIR packing widths; native bridge and Lean packing theorems pass. Full production rule-lowering refinement remains unproved. |
| #171 | [#193](https://github.com/RuleWorld/BNG3/pull/193), `b99c231c` | Windows notebook path assertion and macOS/Python 3.9 libSBML architecture failures repaired; 89 focused installed tests and 55 CI contracts pass. Replacement 5.21.1 wheel verified as arm64. The recorded completed hosted checks used synthetic merge SHA `86e2db1b6c8d96f87d5644ec994e2c7dc66952df`, whose tree matched candidate tree `8651146a54a0955a28c1f38cf18f52874b30d8a7`; this is same-tree evidence, not literal exact-head CI at `b99c231c`. Earlier independent RoadRunner/notebook qualification remains scoped, and #171 acceptance remains open. |
| #172 | [#208](https://github.com/RuleWorld/BNG3/pull/208), `b4c4f941` | Stacked on #193 at `b99c231c`. With optional Cement absent, defaults configuration, CLI and `main` imports remain available; required `core.defaults` import failures propagate, while legacy Cement-app construction gives installation guidance. The explicit Perl adapter remains covered. Clean installed-wheel compatibility group: 93 passed, 3 Cement deprecation warnings; source/Git/PR head identity matched `b4c4f9413c7d1aaa2a42d8f06e311392856860a6`; extension SHA-256 `d7145affad834974001ea92004fa0846c1d79713d55bbde8191ca2c450eb0e8c`. Black, Ruff and diff-check pass. This does not retire `modelapi`, legacy imports or compatibility fallbacks. PR #193's hosted checks were same-tree synthetic-merge evidence, not literal exact-head checks. |
| #141 | [#203](https://github.com/RuleWorld/BNG3/pull/203), `cacee1ab` | Fixed reproduced shared-iterator races in graph reset/index and map lookup; instrumented ASan 13 cases/129 assertions plus 20 concurrent repeats. Worker initialization binds and checks parent Python/native paths; 9 source and 9 clean-installed scan tests pass, including shadowed sources and 2D workers. Broader graph/topology/solver/NFsim isolation remains unqualified. |
| #142 | [#211](https://github.com/RuleWorld/BNG3/pull/211), `451671c24d5e41a812f4ccc436e7aa77509e11e0` | Based on post-#205 main `030f7bed`; first checkpoint `498068a4`, then exact edge-multiplicity repair. NetWriter preserves separate compartmental seed amounts (2 and 7) using structural-label filtering, outer compartments and the shared exact SpeciesGraph identity predicate reused by SpeciesList. Reproduced and fixed equal-size subgraph false positives, wildcard-state identity and duplicate-edge multiplicity errors. Independent brute-force labeled-graph bijection oracle and embedded NFsim encoder partition cases cover symmetry, states, topology and mixed compartments. Final HNauty 74 assertions/10 cases (58/4 issue-tagged), ODE options 112/20, network generation 40/5, NFsim adapter 1386/129 and architecture CTest 1/1 pass. Root independently reran the 58 identity and 112 ODE assertions. Structural canonical labels remain compartment-blind; NFsim keeps its separate encoding, and the tests do not imply byte-identical encodings or standalone pinned-NFsim trajectory qualification. Malformed non-member edge construction remains unsupported/unqualified; broader identity/lowering consumer work remains open. |
| #143 | [#201](https://github.com/RuleWorld/BNG3/pull/201), `d4019f96` | Typed ODE rate dependency classification; 21 ODE cases, 118 compiler-contract cases and 6 independent BNG2 RHS checks. Cross-backend local scopes/propensities remain open. Frozen michment SSA remains 10/306 outside 3 pooled SE, worst |z| 9.3449. Fresh pinned BNG2 reproduces all 200 golden bytes; macOS C rand initialization under seeds 1–200 biases the first wait (0.03473 versus expected 0.00467). Source/probe receipts and analytic conditioning are in [#143](https://github.com/RuleWorld/BNG3/issues/143#issuecomment-6069308392); controls and red gate are unchanged. |
| #145 | [#200](https://github.com/RuleWorld/BNG3/pull/200), `d9227862` | Final-head requalification: adapter ON finite 8 cases/34 assertions and adapter 8/41; OFF finite 8/34; Python dispatch 9; architecture CTest 1/1 in each build, unchanged 43 entries. Pinned BNGsim source and loaded library hashes verified. No broad numerical parity or backend-promotion claim. |
| #179 | [#202](https://github.com/RuleWorld/BNG3/pull/202), `78543775` | Live immutable source verification, fresh pinned BNG2/NFsim builds, smoke artifact receipts, Linux dependency hashes and compiler-image manifest. 79 provenance/corpus/CI contract tests pass; 14 actual approvals remain pending. Corpus selection is unchanged; its source-lock digest is refreshed. The locked Linux runtime/image qualification and strict release-gate wiring remain open. |
| #182 | [#199](https://github.com/RuleWorld/BNG3/pull/199), `4996311d` | Repaired the zero-job hosted workflow failure: runner.temp expressions moved from forbidden job-level env to step env. Actionlint reproduces the old failure and passes the repair; strict-head checkout/preflight follow-up passes 65 CI/wiring contracts. Final exact-head run [37855427009](https://github.com/RuleWorld/BNG3/actions/runs/37855427009) completed successfully at `4996311d847e5ff8dddaa72d5c046a8dcae63993`: numerical lane `113582393871` passed 59 tests/3 deselected plus one spawned-worker identity test; `source_revision=git_head=pr_head_sha=4996311d...`; installed native extension SHA-256 `ab06468dde4d5001aa02236e7cd5c1ab1c70ed71afb06c2ff651d93f9fdd6ba4`. Independent NFsim lane `113582393832` also passed with exact source/Git/PR-head identity and worker identity; direct/XML checks 6 passed/6 deselected, seed contracts 15 passed, simple-system ensemble 1 passed, and fixed-seed final-endpoint comparison 1 passed; its extension SHA-256 was `7f17937dc2525399504e99100474d116336618dbcf6385347dfa48028d8ff064`. The frozen 200-member BNG2 ensemble job was skipped, as was the scheduled historical NFsim job; this does not resolve #143's michment mismatch or establish broader distributional parity. These checks validate PR head `4996311d`, not integration with post-#205 main. |
| #183 | [#206](https://github.com/RuleWorld/BNG3/pull/206), `42f61aa0` | Pinned, hashed Linux Python 3.12 inputs; 32-case official-reference workflow with bounded workers and durable artifacts. Local semantic checkpoint `5f9a7b9d`: round-trip/RoadRunner 32 pass; official 31 pass/1 unsupported; all 32 worker identities match. 69 contracts and 64 runner/trigger checks pass. Broader Python at `5d6fc641`: 1009 pass/34 skip/1 xfail. Hosted setup fixture failure reproduced/repaired; final exact-head Linux run [37854179945](https://github.com/RuleWorld/BNG3/actions/runs/37854179945) passes: round-trip/RoadRunner 32, official 31 pass/1 unsupported. Source SHA equals checkout HEAD, all 32 worker native hashes match, artifact digests verified. Full-suite flags remain false. |

Historical pre-resumption snapshots recorded #128/#190 with 41 successful
and 5 skipped checks, and #130/#189/#192/#194/#196 with 40 successful and
5 skipped checks at their preceding heads. Those counts do not validate the
new revisions above. Newer work has pending checks; stacked #191/#197/#204/#208/#209
had no recorded rollup in that snapshot. The initial #202 lint
failure was a stale corpus source-lock digest, repaired without changing model
selection. The initial #200 architecture failure is corrected without expanding the allowlist, and its final-head functional evidence is now recorded. The #199 zero-job workflow failure and #206 setup fixture failure were reproduced and repaired; each repair needed separate hosted execution evidence. The exact-head #199 numerical and NFsim lane results are recorded above, while the frozen 200-member ensemble remains skipped.
The earlier #199 synthetic-merge run at `58a6641d` checked out synthetic merge
`c9b9b49b` with the same Git tree `e935910f`; it remains historical same-tree
evidence. The exact-head run above supersedes it for the listed #199 lanes.
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
