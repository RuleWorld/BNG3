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

## Pushed checkpoints and pause

Work is paused at the user's request after pushing the current workstreams.
No PR was merged. The GitHub snapshot has 54 open audit issues and one closed
review/disposition issue (#134). An open PR is a candidate, not an integrated
baseline or automatic issue closure. The issue acceptance criteria still govern.

| Issue | PR and recorded head | Evidence and remaining boundary |
| --- | --- | --- |
| #132 | [#130](https://github.com/RuleWorld/BNG3/pull/130), `2f05ce2e` | Assignment-rate parity repair; 509 CTest, focused Python and independent BNG2 checks pass. Hosted snapshot: 40 success, 5 skipped. |
| #133 | [#190](https://github.com/RuleWorld/BNG3/pull/190), `dbffdda2` | JAX ODE uses native compiled rates; installed targeted and x64 tests pass. Static supported subset; dynamic/local functions remain explicit refusals. |
| #173 | [#191](https://github.com/RuleWorld/BNG3/pull/191), `9525d908` | Broken JAX SSA prototype removed; explicit unavailable result, undefined-name lint and JAX CPU CI. Stacked on #190. |
| #134 | [#128](https://github.com/RuleWorld/BNG3/pull/128), `2cf7f6eb`; [#204](https://github.com/RuleWorld/BNG3/pull/204), `dd75fe28` | Review completed at `d0d695d7`; subsequent automated edits reintroduced a pyparsing 3.0.9 molecule-list defect. Separate stacked repair: reproduced failure, then 5 parser/regression tests pass with current and actual 3.0.9 pyparsing. Review both PRs together. |
| #135 | [#187](https://github.com/RuleWorld/BNG3/pull/187) | Current issue-linked checklist and this handoff; documentation does not qualify scientific behavior. |
| #136 | [#189](https://github.com/RuleWorld/BNG3/pull/189), `a2e598ed` | Stale architecture and validation claims corrected; historical results retain their dates and limits. |
| #137 | [#195](https://github.com/RuleWorld/BNG3/pull/195), `e530328e` | Capability inventory and decision worksheet; policy and review ownership remain unapproved. |
| #138 | [#196](https://github.com/RuleWorld/BNG3/pull/196), `07921382` | Compile-owned resolved unit metadata and exporter consumers; AST allowlist 43 → 42, 14 focused checks. Remaining runtime consumers are still open. |
| #163 | [#197](https://github.com/RuleWorld/BNG3/pull/197), `6d44354f` | SBML version-aware unit attributes/defaults and unit-aware seed counts; 33 SBML/unit checks and libSBML fixture with zero diagnostics. Stacked on #196; broader Tier-X inventory/consumer qualification remains open. |
| #165 | [#194](https://github.com/RuleWorld/BNG3/pull/194), `c5fafad0` | General Lean reference matcher soundness/completeness, using the user-approved exact-domain and order-independent mapping contract. Kernel/Smoke/Coverage and axiom audit pass; production C++ correspondence is separate. |
| #169 | [#192](https://github.com/RuleWorld/BNG3/pull/192), `0ee57fe3` | Explicit trust accounting and scheduled/manual mutation harness; 32/32 harness cases on the semantic checkpoint, 56 CI contracts and formatting checks on final head. Resolve documentation overlap with #189. |
| #166 | [#198](https://github.com/RuleWorld/BNG3/pull/198), `5cc1fd57` | Checked declaration IDs and NFIR packing widths; native bridge and Lean packing theorems pass. Full production rule-lowering refinement remains unproved. |
| #171 | [#193](https://github.com/RuleWorld/BNG3/pull/193), `866058a3` | 89 installed compatibility tests, including executed notebooks, API/CLI methods, SBML, SymPy and independent RoadRunner analytic decay. Review the explicit compatibility matrix before closure. |
| #141 | [#203](https://github.com/RuleWorld/BNG3/pull/203), `74fccb47` | Thread-scoped compartment context, parameter refresh and network-cache invalidation; 13 native cases/129 assertions and 9 Python tests. Spawned workers still import shared-checkout Python sources; exact-clone worker identity is unresolved. |
| #143 | [#201](https://github.com/RuleWorld/BNG3/pull/201), `d4019f96` | Typed ODE rate dependency classification; 21 ODE cases, 118 compiler-contract cases and 6 independent BNG2 RHS checks. Cross-backend local scopes/propensities remain open. Frozen michment SSA remains 10/306 outside 3 pooled SE, worst |z| 9.3449. |
| #145 | [#200](https://github.com/RuleWorld/BNG3/pull/200) | Shared semantic lowerability and separate build availability; adapter ON/OFF and Python dispatch checks pass locally. The initial hosted architecture failure is repaired by relocating the shared implementation into an existing compatibility consumer; the checker passes with the unchanged 43-entry allowlist. Review final-head build evidence separately from earlier functional checks. |
| #179 | [#202](https://github.com/RuleWorld/BNG3/pull/202), `78543775` | Live immutable source verification, fresh pinned BNG2/NFsim builds, smoke artifact receipts, Linux dependency hashes and compiler-image manifest. 79 provenance/corpus/CI contract tests pass; 14 actual approvals remain pending. Corpus selection is unchanged; its source-lock digest is refreshed. Linux execution and release-gate wiring remain open. |
| #182 | [#199](https://github.com/RuleWorld/BNG3/pull/199), `c8c065f9` | Required RHS/ODE/SSA determinism/export lanes, installed identity preflight and unchanged scheduled/manual ensembles. Local workflow contracts pass; new hosted numerical execution is not yet qualified. |

Hosted checks were sampled without waiting for runs. At the sampled heads,
#128/#190 had 41 successful and 5 skipped checks; #130/#189/#192/#194/#196 had
40 successful and 5 skipped checks. Newer work has pending checks; stacked
#191/#197/#204 had no recorded rollup in that snapshot. The initial #202 lint
failure was a stale corpus source-lock digest, repaired without changing model
selection. The initial #200 architecture failure is corrected by relocation without expanding the allowlist; review its final-head build evidence.
Neither a skipped job nor absent rollup is a pass. Requery the final candidate
SHA after any push, rebase or integration.

## Plan when work resumes

1. Review current PRs against every issue criterion and integrate in dependency
   order: #190 before #191, #196 before #197, #128 with #204. Reconcile the
   overlapping formal documentation in #189/#192/#194/#198. Verify exact-head
   required checks; do not infer permission to merge from this plan.
2. Resolve actual capability/support decisions (#137), scientific/formal review
   owners (#185), and source/oracle/toolchain/dependency approvals (#179).
   Wire strict provenance into release qualification after substantiated
   decisions; do not approve by changing strings alone.
3. Finish trustworthy baseline qualification: identify the frozen michment
   reference/SSA discrepancy under #143, resolve #141 worker-source identity,
   and qualify the newly wired #182 numerical lanes. Keep seeds, horizons,
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
