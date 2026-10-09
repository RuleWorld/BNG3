# BNG3 convergence checklist

**Status:** incomplete; 50 of 55 audit issues are open. #134/#136/#145/#165/#169
are closed; #146/#154 were reopened after auditing their unmet acceptance criteria.
**Refreshed:** 2026-10-09 UTC against live main
`dd23c2679ead1335d6aeefa47835f850e154256c`. See
[current progress](CURRENT_PROGRESS.md) for scoped integrations, exact evidence
boundaries and candidates. The earlier audited qualification baseline was
`e1836c3274e685996d5e86883761e00e98257e09`.

The target is one maintained C++/Python project containing the approved capability
union of BioNetGen, PyBioNetGen, NFsim and Atomizer. C++ owns performance-critical
representation, compilation and execution; Python owns APIs, orchestration and
suitable translation/tools. Backends share a resolved semantic contract and
reject constructs they cannot preserve.

This is the current task index. Issues own scope, acceptance criteria, sequencing,
assignees and closure evidence. [Current progress](CURRENT_PROGRESS.md) records
verification boundaries; the [audit](REPOSITORY_AUDIT_2026-10-07.md) explains the
55 tasks. The former append-only checklist is preserved at its
[audited revision](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md).
Historical unchecked boxes are not current defects.

## Implemented foundations

These capabilities exist; the open work below qualifies their completeness and
supported scope rather than reimplementing them.

- [x] Native BNGL parser, network generation, ODE/SSA/PLA/PSA, embedded NFsim,
  Python bindings/API, CLI, builders, scans, local sensitivities and exporters.
- [x] Compile-owned model declarations, typed symbols/pattern constraints,
  mutation endpoints and separate forward/reverse rule directions.
- [x] Restricted `CompiledModel -> NFIR` lowering and an enforced architecture
  dependency ratchet; 43 compatibility files remain at the audited revision.
- [x] One bundled nauty build and shared expression infrastructure replacing
  NFsim's ExprTk dependency. Graph-identity unification remains open (B05).
- [x] Direct NFsim initialization by default; explicit opt-in XML fallback.
- [x] BNGIR 0.1/0.2 serialization, structural snapshots and validation;
  native structural import remains open (D01).
- [x] Modern Atomizer, supported SBML Core/Multi lowerings, physical-unit
  infrastructure and exact analytic event subsets. Native dynamic events
  remain rejected (E01–E02).
- [x] Lean semantic/reference modules, scoped interpreter-refinement proofs,
  explicit Smoke/Coverage/axiom gates and native NFnext contract tests.
- [x] SSTS revision-lock and official-reference comparison machinery;
  current aggregate evidence and hosted conformance remain open (E03/H05).
- [x] CPU/Metal/CUDA batch-SSA infrastructure and platform/package CI;
  real CUDA-device qualification remains open (G05).

## Outstanding work

P0: immediate failure triage; P1: core convergence; P2: broader qualification
and maintenance; P3: optional expansion. D: defect/comparison failure;
I: implementation; Q: qualification; R: refactoring/documentation;
M: maintainer/product decision. R/M items require a reviewed scope decision,
not automatic expansion. Estimates and detailed acceptance tests live in issues.

An unchecked item remains open until its issue has a verified implementation or
an approved disposition. A03 is the closed review/disposition issue; later PR
#128 changes and the compatibility repair in #204 still need integration review.
A04 is implemented by this documentation change and awaits merge. A05, B08, F01 and F05 closed after their documentation, shared capability, reference-matcher and trust-accounting acceptance criteria were met; broader semantic/proof issues remain open. The bounded merged runtime and BNGIR repairs are listed in current progress and did not close their broader audit issues.
The pushed candidate ledger and next dependency order are in
[current progress](CURRENT_PROGRESS.md); no other item is completed merely by
an open PR or by filing an issue.

### Triage, documentation and product scope

- [ ] **A01 · P0 D** — Resolve PR #130 assignment-rate parity failures. [#132](https://github.com/RuleWorld/BNG3/issues/132)
- [ ] **A02 · P1 D** — Repair and qualify the optional JAX ODE backend. [#133](https://github.com/RuleWorld/BNG3/issues/133)
- [x] **A03 · P1 Q** — Review and disposition the legacy parser optimizations in PR #128. [#134](https://github.com/RuleWorld/BNG3/issues/134)
- [ ] **A04 · P1 R** — Replace historical convergence logs with a current issue-linked checklist. [#135](https://github.com/RuleWorld/BNG3/issues/135)
- [x] **A05 · P1 R** — Correct stale architecture and validation documentation. [#136](https://github.com/RuleWorld/BNG3/issues/136)
- [ ] **A06 · P1 M** — Approve the BNG3 capability-union inventory and support policy. [#137](https://github.com/RuleWorld/BNG3/issues/137)

### C++ semantic and runtime boundaries

- [ ] **B01 · P1 I** — Migrate remaining runtime consumers to the resolved semantic model. [#138](https://github.com/RuleWorld/BNG3/issues/138)
- [ ] **B02 · P1 I** — Separate network-rule execution from reconstructed AST rules. [#139](https://github.com/RuleWorld/BNG3/issues/139)
- [ ] **B03 · P1 I** — Type simulation protocol actions and share option semantics. [#140](https://github.com/RuleWorld/BNG3/issues/140)
- [ ] **B04 · P1 Q** — Qualify compile-once model reuse and independent trajectory state. [#141](https://github.com/RuleWorld/BNG3/issues/141)
- [ ] **B05 · P1 I** — Unify network and NFsim graph-identity semantics. [#142](https://github.com/RuleWorld/BNG3/issues/142) Merged PR [#211](https://github.com/RuleWorld/BNG3/pull/211) repairs compartmental seed association and exact identity checks; separate backend encodings and broader qualification remain open.
- [ ] **B06 · P1 I** — Complete the shared rate-law and local-function semantic contract. [#143](https://github.com/RuleWorld/BNG3/issues/143)
- [ ] **B07 · P1 M** — Resolve and execute the canonical finite-backend migration. [#144](https://github.com/RuleWorld/BNG3/issues/144)
- [x] **B08 · P2 R** — Use one BNGsim capability and rejection implementation. [#145](https://github.com/RuleWorld/BNG3/issues/145)

### NFsim, NFcore2, NFnext and hybrid execution

- [ ] **C01 · P1 Q** — Expand independent direct-NFsim and XML-path qualification. [#146](https://github.com/RuleWorld/BNG3/issues/146) Merged PR [#210](https://github.com/RuleWorld/BNG3/pull/210) repairs a bounded deletion slice; fixed-seed native final-endpoint parity remains red.
- [ ] **C02 · P1 I** — Extend NFnext lowering for approved unsupported semantic families. [#147](https://github.com/RuleWorld/BNG3/issues/147)
- [ ] **C03 · P1 I** — Qualify a complete model-to-NFnext execution boundary. [#148](https://github.com/RuleWorld/BNG3/issues/148)
- [ ] **C04 · P2 M** — Decide maintained roles for NFcore, NFcore2 and NFnext. [#149](https://github.com/RuleWorld/BNG3/issues/149)
- [ ] **C05 · P1 I** — Complete or disposition hybrid particle-population execution. [#150](https://github.com/RuleWorld/BNG3/issues/150)
- [ ] **C06 · P1 I** — Implement the verified NFsim physical-unit count-rate bridge. [#151](https://github.com/RuleWorld/BNG3/issues/151)
- [ ] **C07 · P2 Q** — Reconcile newer NFsim energy, Rasi and protocol capabilities. [#152](https://github.com/RuleWorld/BNG3/issues/152)

### BNG-IR

- [ ] **D01 · P1 I** — Deserialize structural BNGIR directly into the native semantic model. [#153](https://github.com/RuleWorld/BNG3/issues/153) Merged PR [#209](https://github.com/RuleWorld/BNG3/pull/209) qualifies a narrow parser-free v0.2 import subset with explicit unqualified-export refusal; observables and the remaining model families are still open.
- [ ] **D02 · P1 Q** — Qualify BNGIR round trips across the supported semantic surface. [#154](https://github.com/RuleWorld/BNG3/issues/154)
- [ ] **D03 · P1 I** — Add independent native BNGIR contracts and adversarial fixtures. [#155](https://github.com/RuleWorld/BNG3/issues/155)
- [ ] **D04 · P2 M** — Define BNGIR version defaults, compatibility and semantic equality. [#156](https://github.com/RuleWorld/BNG3/issues/156)

### Atomizer, SBML, events and exporters

- [ ] **E01 · P1 I** — Execute native dynamic events with continuous root detection. [#157](https://github.com/RuleWorld/BNG3/issues/157)
- [ ] **E02 · P1 I** — Complete delayed, prioritized and stochastic event-queue semantics. [#158](https://github.com/RuleWorld/BNG3/issues/158)
- [ ] **E03 · P1 Q** — Publish current revision-locked official SBML conformance evidence. [#159](https://github.com/RuleWorld/BNG3/issues/159)
- [ ] **E04 · P1 I** — Disposition unsupported SBML semantics by feature class. [#160](https://github.com/RuleWorld/BNG3/issues/160)
- [ ] **E05 · P2 Q** — Expand structural Atomizer and SBML Multi execution qualification. [#161](https://github.com/RuleWorld/BNG3/issues/161)
- [ ] **E06 · P2 Q** — Resume curated BioModels and cross-engine Atomizer qualification when authorized. [#162](https://github.com/RuleWorld/BNG3/issues/162)
- [ ] **E07 · P1 Q** — Populate format Tier-X with semantic and consumer-level checks. [#163](https://github.com/RuleWorld/BNG3/issues/163)
- [ ] **E08 · P2 R** — Split Atomizer lowering and emission by semantic responsibility. [#164](https://github.com/RuleWorld/BNG3/issues/164)

### Lean and mathematical checks

- [x] **F01 · P1 I** — Prove ReferenceMatcherCorrect soundness and completeness. [#165](https://github.com/RuleWorld/BNG3/issues/165)
- [ ] **F02 · P1 I** — Establish production lowering correspondence for a named supported subset. [#166](https://github.com/RuleWorld/BNG3/issues/166)
- [ ] **F03 · P2 I** — Extend formal rate, propensity and stochastic execution semantics. [#167](https://github.com/RuleWorld/BNG3/issues/167)
- [ ] **F04 · P2 I** — Qualify and formalize canonicalization and bounded network equivalence. [#168](https://github.com/RuleWorld/BNG3/issues/168)
- [x] **F05 · P1 Q** — Maintain explicit proof trust accounting and harness qualification. [#169](https://github.com/RuleWorld/BNG3/issues/169)
- [ ] **F06 · P3 M** — Decide the optional CRNT model-property verification bridge. [#170](https://github.com/RuleWorld/BNG3/issues/170)

### Python compatibility, performance and maintainability

- [ ] **G01 · P1 Q** — Complete the PyBioNetGen public compatibility matrix. [#171](https://github.com/RuleWorld/BNG3/issues/171)
- [ ] **G02 · P2 R** — Retire redundant legacy Python paths after compatibility qualification. [#172](https://github.com/RuleWorld/BNG3/issues/172) PR [#208](https://github.com/RuleWorld/BNG3/pull/208) preserves defaults without optional Cement but does not retire `modelapi`, legacy imports, or compatibility fallbacks.
- [ ] **G03 · P1 D** — Disposition JAX SSA stubs and gate optional backends and undefined names. [#173](https://github.com/RuleWorld/BNG3/issues/173)
- [ ] **G04 · P2 Q** — Publish current representative speed and memory baselines. [#174](https://github.com/RuleWorld/BNG3/issues/174)
- [ ] **G05 · P2 Q** — Qualify CUDA batch SSA on actual NVIDIA hardware. [#175](https://github.com/RuleWorld/BNG3/issues/175)
- [ ] **G06 · P2 M** — Refresh the NFsim CPU, ensemble and GPU roadmap from measurements. [#176](https://github.com/RuleWorld/BNG3/issues/176)
- [ ] **G07 · P2 Q** — Independently qualify barrier and reservoir energy extensions. [#177](https://github.com/RuleWorld/BNG3/issues/177)
- [ ] **G08 · P2 R** — Consolidate action, numerical and exporter semantic decisions. [#178](https://github.com/RuleWorld/BNG3/issues/178)

### Validation, provenance and release

- [ ] **H01 · P1 M** — Resolve strict provenance approvals and enforce the release gate. [#179](https://github.com/RuleWorld/BNG3/issues/179)
- [ ] **H02 · P1 Q** — Refresh upstream reconciliation and map behavior claims to tests. [#180](https://github.com/RuleWorld/BNG3/issues/180)
- [ ] **H03 · P1 Q** — Approve complete capability-based corpus tiers and budgets. [#181](https://github.com/RuleWorld/BNG3/issues/181)
- [ ] **H04 · P1 Q** — Wire numerical, expression and export parity into explicit CI gates. [#182](https://github.com/RuleWorld/BNG3/issues/182)
- [ ] **H05 · P1 Q** — Add budgeted official SBML conformance CI with durable artifacts. [#183](https://github.com/RuleWorld/BNG3/issues/183)
- [ ] **H06 · P2 Q** — Complete release-candidate scientific and packaging qualification. [#184](https://github.com/RuleWorld/BNG3/issues/184)
- [ ] **H07 · P2 M** — Assign scientific, formal and compatibility review ownership. [#185](https://github.com/RuleWorld/BNG3/issues/185)
- [ ] **H08 · P2 M** — Publish alpha migration, backend-support and repository-maintenance guidance. [#186](https://github.com/RuleWorld/BNG3/issues/186)

## Execution and completion rules

1. Triage A01/A02/G03; complete the support inventory (A06), source approvals
   (H01) and corpus decisions (H03). Review existing work before new ports.
2. Complete shared semantic/runtime and BNGIR boundaries (B/D) while expanding
   independent NFsim evidence (C01). Preserve working compatibility paths.
3. Implement approved capability gaps (C/E), strengthen formal correspondence
   (F), and wire scientific qualification (H04/H05) for each supported slice.
4. Remove redundancy only after parity (G02/G08/E08); qualify the exact release
   candidate and publish migration guidance (H06–H08).

- Close an item with its implementation/disposition, exact revision, test
  commands/results and remaining limits. Do not close on parser acceptance,
  generated-file validity, or unit-test counts alone.
- Require independent BNG2/NFsim or appropriate SBML/reference evidence for
  claimed equivalence; distinguish passed, unsupported, failed, timed out,
  invalid-source and skipped results.
- Keep reference theorems, kernel-reduced proofs, `native_decide` fixtures and
  production C++ tests distinct. No general compiler proof is implied.
- Keep model semantics and capability checks centralized; unsupported behavior
  must fail explicitly. Performance changes require correctness evidence and
  controlled measurements.
- The full BioModels run remains stopped until explicit user resumption (E06).
- Do not merge/publish a release merely because the configured main CI is green.
  Approval locks, complete supported-surface coverage and exact-candidate release
  evidence remain required.

Update this index when an issue closes or scope changes. Keep detailed run
histories in linked artifacts/issues instead of appending them here.
