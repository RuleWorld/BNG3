# BNG3 convergence checklist

**Release scope:** [Capability inventory](CAPABILITY_UNION_INVENTORY.md) · [Machine-readable capability matrix](../provenance/capability-matrix.yml). **Final policy:** [Maintainer decisions](DECISIONS.md). Every inventory row is a release requirement; completion requires the issue acceptance checks and exact-main evidence recorded in [current progress](CURRENT_PROGRESS.md).

**Status (reconciled 2026-11-26 at `90832910`):** task index — **all 55 convergence
issues (`#132`–`#186`) and follow-up release issues (`#470`–`#475`) are CLOSED
(`0` open issues in `RuleWorld/BNG3`)**. Live verification evidence and exact-main
check receipts are tracked in [current progress](CURRENT_PROGRESS.md) and the
closed issue records. The historical audit baseline
(`e1836c3274e685996d5e86883761e00e98257e09`) is preserved in the
[archived audit](archive/reports/REPOSITORY_AUDIT_2026-10-07.md); it is not a
current qualification snapshot.

The target is one maintained C++/Python project containing the approved capability
union of BioNetGen, PyBioNetGen, NFsim and Atomizer. C++ owns performance-critical
representation, compilation and execution; Python owns APIs, orchestration and
suitable translation/tools. Backends share a resolved semantic contract and
reject constructs they cannot preserve.

This is the convergence task index. Issues own scope, acceptance criteria,
sequencing, assignees and closure evidence. [Current progress](CURRENT_PROGRESS.md)
records verification boundaries; the
[audit](archive/reports/REPOSITORY_AUDIT_2026-10-07.md) explains the 55 tasks.
The former append-only checklist is preserved at its
[audited revision](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md).

## Implemented foundations

These capabilities were established before or during the convergence campaign
and qualified through the closed issues indexed below:

- [x] Native BNGL parser, network generation, ODE/SSA/PLA/PSA, embedded NFsim,
  Python bindings/API, CLI, builders, scans, local sensitivities and exporters.
- [x] Compile-owned model declarations, typed symbols/pattern constraints,
  mutation endpoints and separate forward/reverse rule directions.
- [x] `CompiledModel -> NFIR` lowering, architecture dependency ratchet, and
  compiled-input runtime migration (closed under `#138`, `#147`, `#148`, `#149`).
- [x] One bundled nauty build, shared expression infrastructure replacing
  NFsim's ExprTk dependency, and unified graph-identity semantics (closed under
  `#142`).
- [x] Direct NFsim initialization by default; explicit opt-in XML fallback.
- [x] BNGIR 0.1/0.2 serialization, structural snapshots, validation, and direct
  native structural deserialization (closed under `#153`–`#156`).
- [x] Modern Atomizer, supported SBML Core/Multi/comp lowerings, physical-unit
  infrastructure, analytic event lowerings, native ODE event runtime with
  continuous per-conjunct root detection and queued-execution semantics, and
  stochastic/priority/delay event handling (closed under `#157`, `#159`–`#164`);
  see [ADR 0004](adr/0004-native-sbml-event-runtime.md).
- [x] Lean semantic/reference modules, scoped interpreter-refinement and
  correspondence proofs, explicit Smoke/Coverage/axiom gates and native NFnext
  contract tests (closed under `#165`–`#170`).
- [x] SSTS revision-lock, official-reference comparison machinery, and hosted
  conformance CI with permanent receipts (closed under `#159`, `#183`).
- [x] CPU/Metal/CUDA batch-SSA infrastructure and platform/package CI (closed
  under `#175` and `#474`).

## Convergence work items (all issues closed)

P0: immediate failure triage; P1: core convergence; P2: broader qualification
and maintenance; P3: optional expansion. D: defect/comparison failure;
I: implementation; Q: qualification; R: refactoring/documentation;
M: maintainer/product decision.

All 55 items below (`#132`–`#186`) and the follow-up release issues (`#470`–`#475`)
were verified `CLOSED` on 2026-11-26 (`gh issue list --repo RuleWorld/BNG3 --state open`
returns `0` open issues). Note that `#158` (E02) was merged into `#157` (E01),
`#470` was merged into `#178` (G08), and GPU-specific implementation/device
qualification from `#175` (G05) was completed under `#474`. Closure commits,
check receipts, and remaining explicit scope boundaries live in the closed
issue threads and [current progress](CURRENT_PROGRESS.md).

### Triage, documentation and product scope

- [x] **A01 · P0 D** — Resolve PR #130 assignment-rate parity failures. [#132](https://github.com/RuleWorld/BNG3/issues/132)
- [x] **A02 · P1 D** — Repair and qualify the optional JAX ODE backend. [#133](https://github.com/RuleWorld/BNG3/issues/133)
- [x] **A03 · P1 Q** — Review and disposition the legacy parser optimizations in PR #128. [#134](https://github.com/RuleWorld/BNG3/issues/134)
- [x] **A04 · P1 R** — Replace historical convergence logs with a current issue-linked checklist. [#135](https://github.com/RuleWorld/BNG3/issues/135)
- [x] **A05 · P1 R** — Correct stale architecture and validation documentation. [#136](https://github.com/RuleWorld/BNG3/issues/136)
- [x] **A06 · P1 M** — Approve the BNG3 capability-union inventory and support policy. [#137](https://github.com/RuleWorld/BNG3/issues/137)

### C++ semantic and runtime boundaries

- [x] **B01 · P1 I** — Migrate remaining runtime consumers to the resolved semantic model. [#138](https://github.com/RuleWorld/BNG3/issues/138)
- [x] **B02 · P1 I** — Separate network-rule execution from reconstructed AST rules. [#139](https://github.com/RuleWorld/BNG3/issues/139)
- [x] **B03 · P1 I** — Type simulation protocol actions and share option semantics. [#140](https://github.com/RuleWorld/BNG3/issues/140)
- [x] **B04 · P1 Q** — Qualify compile-once model reuse and independent trajectory state. [#141](https://github.com/RuleWorld/BNG3/issues/141)
- [x] **B05 · P1 I** — Unify network and NFsim graph-identity semantics. [#142](https://github.com/RuleWorld/BNG3/issues/142)
- [x] **B06 · P1 I** — Complete the shared rate-law and local-function semantic contract. [#143](https://github.com/RuleWorld/BNG3/issues/143)
- [x] **B07 · P1 M** — Resolve and execute the canonical finite-backend migration. [#144](https://github.com/RuleWorld/BNG3/issues/144)
- [x] **B08 · P2 R** — Use one BNGsim capability and rejection implementation. [#145](https://github.com/RuleWorld/BNG3/issues/145)

### NFsim, NFcore2, NFnext and hybrid execution

- [x] **C01 · P1 Q** — Expand independent direct-NFsim and XML-path qualification. [#146](https://github.com/RuleWorld/BNG3/issues/146)
- [x] **C02 · P1 I** — Extend NFnext lowering for approved unsupported semantic families. [#147](https://github.com/RuleWorld/BNG3/issues/147)
- [x] **C03 · P1 I** — Qualify a complete model-to-NFnext execution boundary. [#148](https://github.com/RuleWorld/BNG3/issues/148)
- [x] **C04 · P2 M** — Decide maintained roles for NFcore, NFcore2 and NFnext. [#149](https://github.com/RuleWorld/BNG3/issues/149)
- [x] **C05 · P1 I** — Complete or disposition hybrid particle-population execution. [#150](https://github.com/RuleWorld/BNG3/issues/150)
- [x] **C06 · P1 I** — Implement the verified NFsim physical-unit count-rate bridge. [#151](https://github.com/RuleWorld/BNG3/issues/151)
- [x] **C07 · P2 Q** — Reconcile newer NFsim energy, Rasi and protocol capabilities. [#152](https://github.com/RuleWorld/BNG3/issues/152)

### BNG-IR

- [x] **D01 · P1 I** — Deserialize structural BNGIR directly into the native semantic model. [#153](https://github.com/RuleWorld/BNG3/issues/153)
- [x] **D02 · P1 Q** — Qualify BNGIR round trips across the supported semantic surface. [#154](https://github.com/RuleWorld/BNG3/issues/154)
- [x] **D03 · P1 I** — Add independent native BNGIR contracts and adversarial fixtures. [#155](https://github.com/RuleWorld/BNG3/issues/155)
- [x] **D04 · P2 M** — Define BNGIR version defaults, compatibility and semantic equality. [#156](https://github.com/RuleWorld/BNG3/issues/156)

### Atomizer, SBML, events and exporters

- [x] **E01 · P1 I** — Execute native dynamic events with continuous root detection. [#157](https://github.com/RuleWorld/BNG3/issues/157)
- [x] **E02 · P1 I** — Complete delayed, prioritized and stochastic event-queue semantics (merged into `#157`). [#158](https://github.com/RuleWorld/BNG3/issues/158)
- [x] **E03 · P1 Q** — Publish current revision-locked official SBML conformance evidence. [#159](https://github.com/RuleWorld/BNG3/issues/159)
- [x] **E04 · P1 I** — Disposition unsupported SBML semantics by feature class. [#160](https://github.com/RuleWorld/BNG3/issues/160)
- [x] **E05 · P2 Q** — Expand structural Atomizer and SBML Multi execution qualification. [#161](https://github.com/RuleWorld/BNG3/issues/161)
- [x] **E06 · P2 Q** — Resume curated BioModels and cross-engine Atomizer qualification when authorized. [#162](https://github.com/RuleWorld/BNG3/issues/162)
- [x] **E07 · P1 Q** — Populate format Tier-X with semantic and consumer-level checks. [#163](https://github.com/RuleWorld/BNG3/issues/163)
- [x] **E08 · P2 R** — Split Atomizer lowering and emission by semantic responsibility. [#164](https://github.com/RuleWorld/BNG3/issues/164)

### Lean and mathematical checks

- [x] **F01 · P1 I** — Prove ReferenceMatcherCorrect soundness and completeness. [#165](https://github.com/RuleWorld/BNG3/issues/165)
- [x] **F02 · P1 I** — Establish production lowering correspondence for a named supported subset. [#166](https://github.com/RuleWorld/BNG3/issues/166)
- [x] **F03 · P2 I** — Extend formal rate, propensity and stochastic execution semantics. [#167](https://github.com/RuleWorld/BNG3/issues/167)
- [x] **F04 · P2 I** — Qualify and formalize canonicalization and bounded network equivalence. [#168](https://github.com/RuleWorld/BNG3/issues/168)
- [x] **F05 · P1 Q** — Maintain explicit proof trust accounting and harness qualification. [#169](https://github.com/RuleWorld/BNG3/issues/169)
- [x] **F06 · P3 M** — Decide the optional CRNT model-property verification bridge. [#170](https://github.com/RuleWorld/BNG3/issues/170)

### Python compatibility, performance and maintainability

- [x] **G01 · P1 Q** — Complete the PyBioNetGen public compatibility matrix. [#171](https://github.com/RuleWorld/BNG3/issues/171)
- [x] **G02 · P2 R** — Retire redundant legacy Python paths after compatibility qualification. [#172](https://github.com/RuleWorld/BNG3/issues/172)
- [x] **G03 · P1 D** — Disposition JAX SSA stubs and gate optional backends and undefined names. [#173](https://github.com/RuleWorld/BNG3/issues/173)
- [x] **G04 · P2 Q** — Publish current representative speed and memory baselines. [#174](https://github.com/RuleWorld/BNG3/issues/174)
- [x] **G05 · P2 Q** — Qualify CUDA batch SSA on actual NVIDIA hardware (GPU work consolidated into `#474`, also closed). [#175](https://github.com/RuleWorld/BNG3/issues/175)
- [x] **G06 · P2 M** — Refresh the NFsim CPU, ensemble and GPU roadmap from measurements. [#176](https://github.com/RuleWorld/BNG3/issues/176)
- [x] **G07 · P2 Q** — Independently qualify barrier and reservoir energy extensions. [#177](https://github.com/RuleWorld/BNG3/issues/177)
- [x] **G08 · P2 R** — Consolidate action, numerical and exporter semantic decisions (includes merged `#470`). [#178](https://github.com/RuleWorld/BNG3/issues/178)

### Validation, provenance and release

- [x] **H01 · P1 M** — Resolve strict provenance approvals and enforce the release gate. [#179](https://github.com/RuleWorld/BNG3/issues/179)
- [x] **H02 · P1 Q** — Refresh upstream reconciliation and map behavior claims to tests. [#180](https://github.com/RuleWorld/BNG3/issues/180)
- [x] **H03 · P1 Q** — Approve complete capability-based corpus tiers and budgets. [#181](https://github.com/RuleWorld/BNG3/issues/181)
- [x] **H04 · P1 Q** — Wire numerical, expression and export parity into explicit CI gates. [#182](https://github.com/RuleWorld/BNG3/issues/182)
- [x] **H05 · P1 Q** — Add budgeted official SBML conformance CI with durable artifacts. [#183](https://github.com/RuleWorld/BNG3/issues/183)
- [x] **H06 · P2 Q** — Complete release-candidate scientific and packaging qualification. [#184](https://github.com/RuleWorld/BNG3/issues/184)
- [x] **H07 · P2 M** — Assign scientific, formal and compatibility review ownership. [#185](https://github.com/RuleWorld/BNG3/issues/185)
- [x] **H08 · P2 M** — Publish alpha migration, backend-support and repository-maintenance guidance. [#186](https://github.com/RuleWorld/BNG3/issues/186)

### Follow-up release issues

- [x] **#470** — Merged into `#178` (common backend interface). [#470](https://github.com/RuleWorld/BNG3/issues/470)
- [x] **#471** — Anti-gaming policy and oracle consolidation. [#471](https://github.com/RuleWorld/BNG3/issues/471)
- [x] **#472** — Documentation standardization and acceptance checks. [#472](https://github.com/RuleWorld/BNG3/issues/472)
- [x] **#473** — Optional JAX backend qualification. [#473](https://github.com/RuleWorld/BNG3/issues/473)
- [x] **#474** — GPU implementation and Metal/CUDA device qualification. [#474](https://github.com/RuleWorld/BNG3/issues/474)
- [x] **#475** — Delayed-rule interchange and native execution completion. [#475](https://github.com/RuleWorld/BNG3/issues/475)

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
- Curated BioModels qualification (E06 / `#162`) was resumed and closed; see
  [curated BioModels corpus](CURATED_BIOMODELS_CORPUS.md) and
  [current progress](CURRENT_PROGRESS.md) for current manifest status.
- Do not merge/publish a release merely because the configured main CI is green.
  Approval locks, complete supported-surface coverage and exact-candidate release
  evidence remain required.

Update this index when an issue closes or scope changes. Keep detailed run
histories in linked artifacts/issues instead of appending them here.
