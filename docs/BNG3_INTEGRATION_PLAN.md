# BNG3 Integration and Convergence Plan

**Status:** Proposed
**Plan date:** 2026-08-28
**Scope:** BioNetGen, NFsim, and PyBioNetGen convergence into one maintained BNG3 codebase
**Implementation:** Out of scope for this document

## Executive decision

BNG3 should become the sole forward-development repository for the BioNetGen modeling language, the network-based and network-free simulation engines, and the Python interface. It should not remain a downstream repository that repeatedly copies or merges three independently evolving codebases.

The migration should proceed from a pinned, auditable baseline; preserve the union of supported capabilities; establish independent behavioral oracles before replacing implementations; converge one semantic boundary at a time; and retire redundant code only after its replacement passes deterministic, statistical, API, and packaging gates.

The central architecture is:

```text
                          Product runtime

 .bngl files ───────────────┐
 Python ModelBuilder ────────┼──> canonical ast::Model
 SBML ─> Atomizer ─> BNGL ───┘            │
                                           ├──> semantic validation
                                           ├──> network generation ─> ODE/SSA/PLA/PSA
                                           ├──> direct NFsim adapter ─> network-free engine
                                           └──> canonical writers and graph exports
                                                        │
                                             Python API / CLI / results

                         Validation boundary

 pinned BNG2 Perl ───────────────> network and trajectory oracle
 pinned pre-convergence NFsim ───> network-free oracle
 pinned PyBioNetGen release ─────> Python compatibility contracts
 pinned RuleHub snapshot ────────> validation corpus and metadata
 reviewed golden bundle ─────────> reproducible regression artifact
```

BNG2 Perl and the pre-convergence NFsim executable remain outside the normal product dependency graph. They are validation oracles, not runtime fallbacks except where an explicitly supported compatibility mode says otherwise.

## 1. Goals, non-goals, and constraints

### 1.1 Goals

1. Establish one authoritative repository, release process, issue tracker, and review policy.
2. Preserve the capability union of BioNetGen, NFsim, and PyBioNetGen.
3. Establish one canonical model representation and explicit adapters at domain boundaries.
4. Make Python and the CLI thin, stable interfaces over the same in-process implementation.
5. Prove scientific compatibility using independent pinned oracles and a versioned corpus.
6. Make every release reproducible from recorded source, dependency, corpus, and oracle revisions.
7. Detect ongoing source-repository drift without reintroducing uncontrolled recurring merges.
8. Retire redundant implementations only when their replacement has an explicit passing gate.

### 1.2 Non-goals

- Rewriting BioNetGen or NFsim wholesale in TypeScript, Rust, or another language.
- Treating textual output identity as the only definition of scientific equivalence.
- Preserving every internal implementation detail or undocumented Python import path forever.
- Automatically merging future commits from the three source repositories.
- Using Playground implementations as the sole scientific oracle.
- Deleting BNG2 Perl, native NFsim, or legacy Python code before replacement behavior is demonstrated.

### 1.3 Capability-preservation constraint

The unified system must preserve, or explicitly deprecate through a reviewed compatibility policy, the union of:

- BNGL parsing, diagnostics, actions, and model construction.
- Network generation and network-free execution.
- ODE, SSA, PLA, PSA, and NF simulation methods.
- Local and global functions, rate laws, observables, compartments, molecule types, rules, and seed species.
- One- and two-dimensional scans and local sensitivity analysis.
- SBML import through Atomizer.
- BNGL, BNG-XML, NET, SBML, SBML-Multi, MATLAB/MEX, LaTeX, SSC, MDL, and graph exports.
- Supported Python APIs, CLI behavior, result objects, plotting helpers, and compatibility modes.

Capability removal requires a separate deprecation decision, migration path, release-note entry, and contract test. Deduplication alone is not authorization to remove a capability.

## 2. Current BNG3 baseline

This section is a dated planning snapshot, not a permanently current status report. It should be refreshed at the start of Phase 0.

### 2.1 What already exists

BNG3 is already structurally a monorepo:

- `cpp/` contains the BioNetGen C++ parser, AST, graph core, network/simulation engines, writers, embedded NFsim, and pybind11 bindings.
- `python/bionetgen/` contains a unified API and Atomizer alongside legacy PyBioNetGen modules.
- `legacy/perl/` contains BNG2 Perl as a compatibility and validation implementation.
- `tests/validation/`, model fixtures, CMake targets, package metadata, documentation, and GitHub Actions workflows already exist.
- [BNG3_unification_spec.md](../BNG3_unification_spec.md) defines tactical work orders WO-0 through WO-7.
- [BNG3_overcount_analysis.md](../BNG3_overcount_analysis.md) records the network-overcount investigation.
- [architecture.md](architecture.md) describes the current runtime, including the XML bridge into NFsim.

The work therefore starts from an incomplete convergence, not from four empty repositories.

### 2.2 Important gaps observed in the current tree

| Area | Current condition | Planning consequence |
|---|---|---|
| Source provenance | No single lock file records all imported source revisions and reconciliation status. | Freeze and record the common ground before further convergence. |
| Direct NFsim bridge | `NFinput_fromAst.cpp` maps parameters, but molecule types, functions, observables, species, and rules are incomplete. | Treat direct construction as a staged migration with shadow comparison. |
| Active NFsim path | The binding still serializes `ast::Model` to XML and reparses it. | Keep the XML path as a temporary comparator, then remove it from runtime after parity. |
| Graph identity | BioNetGen network canonicalization and NFsim complex identity are different scientific contracts. | Share the low-level Nauty dependency, but do not force both through one unproven high-level labeling algorithm. |
| Expression evaluation | BioNetGen and NFsim still carry different expression paths, including exprtk-related build logic. | Define one expression contract and migrate consumers incrementally. |
| Python convergence | Legacy `core`, `modelapi`, `network`, and `simulator` trees remain. | Inventory public compatibility before deletion; use contract tests to govern removal. |
| Golden references | `tests/validation/golden/` does not yet contain a frozen reference bundle. | Build provenance-aware oracle generation before using parity as a release claim. |
| Stochastic parity | Distributional validation is not yet a completed gate. | Define fixed ensembles and statistical acceptance rules; execution success is insufficient. |
| RuleHub integration | The local corpus loader does not use a pinned RuleHub snapshot. | Add an exact RuleHub revision and generated selection manifest. |
| CI truthfulness | Some jobs suppress failures, label parse checks as NFsim validation, or push autofixes; hosted builds are not currently a reliable green baseline. | Make CI honest and green before expanding it. |
| Documentation | The architecture document, unification spec, analysis notes, and live implementation disagree in places. | Add documentation consistency checks and name one governing decision record. |
| Packaging | Project metadata and supported-platform behavior need reconciliation with the unified repository. | Make wheel, CLI, import, and embedded-data tests release gates. |

### 2.3 Source revisions observed on 2026-08-28

These revisions are evidence for the initial reconciliation inventory. Phase 0 must verify them again and write the accepted values to a committed lock file.

| Source | Observed branch and revision | Role |
|---|---|---|
| [RuleWorld/BNG3](https://github.com/RuleWorld/BNG3) | `main` at `59b774a14aa956a2c25daa6d904e7ad476feda15` | Destination and future authority |
| [RuleWorld/bionetgen](https://github.com/RuleWorld/bionetgen) | `master` at `43ddf3afe165192a222fd13e4917a1902ffe3446` | BioNetGen reconciliation source and BNG2 oracle lineage |
| [RuleWorld/NFsim](https://github.com/RuleWorld/NFsim) | `master` at `5962ea9ad4248522f6170a61367b1d7242e2824b` | NFsim reconciliation source and oracle lineage |
| [RuleWorld/PyBioNetGen](https://github.com/RuleWorld/PyBioNetGen) | `main` at `43b09a5346402986d48b1defba5eaec0ae2f7802` | Python and Atomizer reconciliation source |
| [RuleWorld/bngplayground](https://github.com/RuleWorld/bngplayground) | `main` at `1914b8ccc8c2d4da2b1c1bb2b90b2bfc98224f6c` | CI and validation design reference |
| [akutuva21/julesplayground](https://github.com/akutuva21/julesplayground) | `main` at `c59d74482290aab90b29ecc330cc2110a728ef12` | Independent implementation reference, not an oracle |
| [RuleWorld/RuleHub](https://github.com/RuleWorld/RuleHub) | `master` at `b84f0a72ad21dc70cb99d4880b49a40f17046357` | Canonical model and metadata corpus |

The source revisions are not automatically the revisions BNG3 should import. Maintainers must explicitly choose the Phase 0 baseline after reviewing any newer changes.

## 3. Architecture decisions

### 3.1 Repository authority

**Decision:** BNG3 becomes the canonical forward-development monorepo. Once a component completes convergence, feature and bug-fix development for that component occurs in BNG3 first.

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| Continue independent development and periodically copy code | Minimal governance change | Permanent merge debt, unclear ownership, divergent fixes, weak provenance | Reject |
| Use Git submodules | Preserves repository boundaries | Does not solve duplicated abstractions, cross-repo CI, atomic releases, or API convergence | Reject |
| Repeated subtree merges | Retains some history | Recurring conflicts and ambiguous authority remain | Use only for a bounded historical import if helpful |
| Rewrite all components | Clean conceptual start | Highest scientific regression risk and longest time without trusted parity | Reject |
| Canonical BNG3 monorepo with pinned external oracles | Atomic change/review/release, explicit ownership, testable boundaries | Requires coordinated migration and deprecation | Adopt |

After convergence, the old repositories should be placed in maintenance mode and clearly direct new work to BNG3. Critical fixes may be backported to supported legacy releases, but those backports must not re-establish dual feature development.

### 3.2 Canonical model and runtime boundaries

**Decision:** `ast::Model` is the canonical in-memory model representation. All front doors produce it, and each execution backend consumes it through an explicit typed interface.

The canonical AST must represent source locations, symbol resolution, units where available, molecule types, seed species, observables, functions, compartments, rules, actions, and simulation settings without losing source semantics.

Boundary rules:

1. BNGL is parsed exactly once by the ANTLR-based parser.
2. Python `ModelBuilder` constructs the same AST through bindings rather than a parallel Python model implementation.
3. Atomizer may continue to generate BNGL during migration, but that BNGL must pass through the canonical parser and retain input/provenance metadata. A later direct Atomizer-to-AST interface is optional, not required for initial convergence.
4. Network generation consumes the AST through a stable engine interface.
5. NFsim consumes the AST through a dedicated adapter that maps into NFsim runtime objects without an XML round trip.
6. Writers consume the AST or generated-network result through typed writer interfaces.
7. Python owns orchestration and ergonomics; it does not reimplement parsing, simulation, graph identity, or scientific writers.

### 3.3 Canonicalization and graph identity

**Decision:** Deduplicate the raw Nauty library and common graph primitives, but preserve separate, tested domain contracts for:

- BioNetGen network-generation species/reaction canonicalization.
- NFsim runtime complex identity and symmetry/counting behavior.

The current unification spec's proposal for one high-level `canonicalLabel` used unchanged by both engines is too strong until equivalence is demonstrated. A shared dependency does not imply that the two domains have identical labels, partitions, automorphism treatment, or lifecycle requirements.

The revised work is:

- **WO-1a:** Correct and prove BioNetGen network canonicalization against BNG2 Perl, including the known overcounting models.
- **WO-1b:** Build and link one copy of the low-level Nauty library; migrate NFsim without changing its validated complex-identity semantics.

Any later unification of the high-level algorithms requires a separate ADR and parity evidence for both domains.

### 3.4 Expression contract

**Decision:** Establish one parsed expression representation, symbol-table contract, evaluation semantics, and error model. Backends may use specialized evaluators temporarily, but they must consume the same resolved expression program and pass cross-backend contract tests.

The contract must specify:

- numeric types and precision;
- operator precedence and supported functions;
- local/global function scoping;
- time and observable references;
- parameter mutation and event-time behavior;
- undefined symbols, domain errors, and diagnostics;
- deterministic serialization of an expression program.

Removing exprtk or another evaluator is the last step of this migration, not the first.

### 3.5 Public API and compatibility

**Decision:** The supported Python surface is small, documented, versioned, and tested independently of internal module layout.

The intended public front doors are:

- `bionetgen.load(...)`
- model construction through the supported builder API
- `model.simulate(method=...)`
- scans and sensitivity analysis
- supported model/result/export methods
- the `bionetgen` CLI

Before deleting legacy packages, capture a compatibility inventory from current PyBioNetGen releases, documentation, examples, and downstream usage. Classify each interface as:

- preserved unchanged;
- preserved through a compatibility shim;
- deprecated with a removal release;
- intentionally unsupported, with rationale and migration instructions.

Import-path compatibility and scientific-result compatibility are separate contracts and need separate tests.

## 4. Common-ground and source-reconciliation process

### 4.1 Freeze a source manifest

Create a committed machine-readable source manifest, proposed as `provenance/upstreams.lock.yml`, containing:

```yaml
schema_version: 1
baseline_date: YYYY-MM-DD
sources:
  bng3:
    repository: https://github.com/RuleWorld/BNG3.git
    revision: <sha>
  bionetgen:
    repository: https://github.com/RuleWorld/bionetgen.git
    revision: <sha>
  nfsim:
    repository: https://github.com/RuleWorld/NFsim.git
    revision: <sha>
  pybionetgen:
    repository: https://github.com/RuleWorld/PyBioNetGen.git
    revision: <sha>
  rulehub:
    repository: https://github.com/RuleWorld/RuleHub.git
    revision: <sha>
oracles:
  bng2: <build recipe and artifact digest>
  nfsim: <build recipe and artifact digest>
dependencies:
  compiler_images: <immutable image digests>
  python_lock: <lock-file digest>
```

The manifest should be changed only in a source-update PR with an automatically generated reconciliation report.

### 4.2 Build a commit-reconciliation ledger

For each source repository, enumerate commits after the revision already represented in BNG3 and classify every commit as:

- `incorporated-identically`
- `incorporated-equivalently`
- `superseded-by-bng3`
- `not-applicable`
- `pending-port`
- `blocked-on-design`

Each entry should record the source SHA, affected capability, BNG3 PR/commit, associated tests, reviewer, and rationale. A commit is not considered reconciled because a similar filename exists in BNG3.

Prioritize reconciliation in this order:

1. correctness and security fixes;
2. parser and model-semantics changes;
3. numerical solver and NFsim behavior changes;
4. Atomizer and public API behavior;
5. packaging and platform fixes;
6. performance changes with benchmarks;
7. documentation-only changes.

Where possible, port the source regression test first or in the same PR as the implementation. Avoid bulk source replacement after BNG3-specific integration work has begun.

### 4.3 Monitor future drift without automatic merging

A scheduled read-only job should compare the pinned source SHAs with the current upstream heads and publish a drift report. It may open or update a tracking issue or draft PR containing only the report. It must not copy code, merge branches, regenerate goldens, or push fixes automatically.

Each reported commit follows the reconciliation process above. Once an upstream component is formally retired, remove it from drift monitoring and record the retirement revision.

## 5. Validation architecture

### 5.1 Evidence roles

| Evidence source | Accepted role | Not sufficient for |
|---|---|---|
| Pinned BNG2 Perl | Network generation and supported deterministic/stochastic compatibility | NFsim-only semantics |
| Pinned pre-convergence native NFsim | Network-free behavior and NFsim-specific regression tests | BNG2 network-generation semantics |
| Pinned PyBioNetGen release | Public Python/CLI compatibility | Scientific correctness by itself |
| Reviewed golden bundle | Fast, reproducible regression comparison | Establishing correctness if provenance is absent |
| Pinned RuleHub | Corpus selection, metadata, feature coverage | Claiming a model passes without executing it |
| BNG Playground | Layered-CI patterns and independent behavioral comparison | Sole reference oracle |
| Jules Playground | Independent TypeScript implementation and differential investigation | Replacement for native BNG2/NFsim evidence |

RuleHub compatibility fields are selection metadata, not proof. In the 2026-08-28 snapshot, the manifest contained 482 entries, including 426 marked BNG2-compatible and 145 marked NFsim-compatible, while only 29 explicitly listed an `nf` method. Those categories must be interpreted and frozen by a generated selection manifest rather than inferred ad hoc in CI.

### 5.2 Corpus tiers

A model may belong to more than one tier.

| Tier | Purpose | Typical trigger |
|---|---|---|
| Tier-S | Small, feature-balanced smoke suite | Every supported change and every PR |
| Tier-P | Deterministic BNG2 parser, network, ODE, and export parity | Required PR shards, main, nightly |
| Tier-NF | NFsim construction, rule behavior, observables, functions, and stochastic parity | NFsim changes, main, nightly/weekly |
| Tier-X | Translation and round-trip coverage for BNGL, XML, SBML, SBML-Multi, Atomizer, and writers | I/O/Atomizer changes, nightly |
| Tier-B | Benchmarks, large models, memory stress, sanitizers, and performance budgets | Weekly and release qualification |

Tier-S must be hand-curated for feature coverage and runtime stability. The broader tiers should be generated from the pinned RuleHub manifest plus repository-specific fixtures, with the exact resulting model IDs committed as a manifest.

### 5.3 Oracle and golden provenance

Golden outputs must be generated by a dedicated, reviewed workflow, never silently by normal tests. Each golden bundle records:

- model path and content digest;
- RuleHub revision and selection-manifest digest;
- oracle repository revision and binary digest;
- build compiler, flags, dependencies, platform, and container image digest;
- command line, simulation method, seed set, time grid, tolerances, and comparator version;
- output digest and generation timestamp.

CI should consume a content-addressed golden artifact and verify its manifest before comparison. Regeneration is a visible scientific change and requires domain review.

### 5.4 Comparators

#### Parser and semantic model

- Compare parse success/failure and normalized diagnostics on valid and invalid fixtures.
- Compare normalized AST content, symbol resolution, defaults, actions, functions, and source-sensitive cases.
- Do not require source-format whitespace or ordering identity where semantics are order-independent.

#### Network generation

- Parse NET output into typed species, reactions, rate laws, stoichiometry, and observables.
- Compare canonical structural sets or multisets, not raw line order.
- Require equal species and reaction multiplicities and equivalent kinetic expressions.
- Keep model-specific normalization explicit and reviewed.
- Make known overcount regressions first-class tests, not permanent broad exclusions.

#### Deterministic trajectories

- Align declared time points explicitly.
- Compare every observable and species that is part of the contract.
- Use documented absolute and relative tolerances appropriate to solver precision.
- Record solver, tolerances, and version in provenance.
- Diagnose conservation-law and event-time differences separately from floating-point drift.

#### Stochastic trajectories

- Verify same-engine repeatability for fixed seeds where the engine promises it.
- Compare fixed, predeclared seed ensembles; never retry until a run passes.
- Start with at least 200 runs for designated small models, then calibrate sample size through power and variance analysis.
- Compare means, variances, selected quantiles, zero-inflation/extinction probabilities where relevant, and time-correlated summaries.
- Correct for multiple comparisons or use a predeclared aggregate acceptance statistic.
- Version and review statistical thresholds; do not weaken them in an implementation PR.

#### NFsim direct adapter

During migration, compare three paths:

1. BNG3 direct `ast::Model` to NFsim adapter.
2. BNG3's existing AST-to-XML-to-NFsim bridge.
3. The pinned independent native NFsim oracle.

Validate molecule types, seed complexes, reaction rules, transformations, symmetry factors, product molecularity, observables, functions, compartments, options, and seeded/stochastic results. The XML bridge leaves the default runtime only after the direct path passes the agreed Tier-NF gate.

#### Atomizer and format conversion

- Validate XML/SBML against their schemas when the relevant validator is available.
- Use semantic round trips rather than raw text comparison.
- Compare molecule types, rules, observables, initial conditions, units, and supported annotations.
- Preserve source/provenance information through conversion.
- Maintain an explicit unsupported-feature report rather than silently dropping constructs.

#### Python and CLI contracts

- Test documented imports, signatures, default values, result shapes/dtypes, exceptions, warnings, serialization, and context management.
- Test every supported method through both the Python API and CLI where applicable.
- Test installed wheels in clean environments rather than only editable installs.
- Assert that removed internal modules are not imported on the default path.
- Test the sanctioned Perl compatibility path separately from the default path.

### 5.5 Exceptions and suppression budget

All expected failures and skips belong in a machine-readable exception ledger. Each entry requires:

- model and test identity;
- affected method/platform;
- issue URL;
- technical reason;
- owner;
- date introduced;
- expiry or review date;
- expected failure signature.

Expected failures must be strict: an unexpected pass fails the test until the exception is removed. Required jobs must fail if an oracle, corpus, or validator is unavailable; they must not convert missing evidence into a passing skip. CI enforces a non-increasing exception budget unless an explicitly approved compatibility decision changes it.

Before freezing the initial ledger, reconcile contradictory documentation about which overcounting models are currently expected to fail.

## 6. CI, review, and release design

### 6.1 Immediate CI integrity rules

Before scientific expansion, make the existing CI truthful and green:

1. Repair cross-platform compilation, including platform-scoping assembler options such as `-mbig-obj`.
2. Remove `|| true` or equivalent suppression from required tests.
3. Rename or replace parse-only checks that currently imply NFsim simulation validation.
4. Stop autofix workflows from committing or pushing to contributor branches. Formatting jobs should report a patch or fail with a local remediation command.
5. Make every required job emit a terminal summary with test counts, failures, skips, exception count, corpus revision, and artifact digests.
6. Treat missing native NFsim, Perl, RuleHub, or validator assets as infrastructure failure in jobs that claim to validate them.

### 6.2 CI layers

| Layer | Required checks | Merge/release role |
|---|---|---|
| PR fast | Formatting, lint/static analysis, C++ unit tests, Python unit/API tests, Tier-S, build on Linux/macOS/Windows, documentation/link checks | Required for every PR |
| PR targeted | Component-specific Tier-P, Tier-NF, Tier-X, sanitizer, or packaging shards selected from changed paths and labels | Required when relevant; override requires owner approval |
| Main | Full deterministic parity shards, native-oracle availability, installed-wheel smoke tests, exception-budget check | Protects the integration branch |
| Nightly | Full pinned RuleHub Tier-P/NF/X corpus, broader platform matrix, source-drift report | Finds broad and external drift |
| Weekly | Statistical ensembles, Tier-B, sanitizers, leak checks, benchmarks, reproducibility rebuild | Long-running scientific and quality evidence |
| Release candidate | All required main/nightly/weekly gates on the exact candidate SHA and locked corpus/oracles; signed artifact provenance | Blocks release publication |

The release workflow must promote artifacts from the validated release-candidate SHA or reproduce them with an attested identical build. A tag alone must not bypass scientific validation.

### 6.3 Change-aware selection without coverage loss

Path-based selection makes PR feedback faster but cannot be the sole gate. Maintain a capability-to-test map connecting parser, AST, graph core, network engine, NFsim, expressions, writers, Atomizer, Python API, CLI, packaging, and documentation to their required suites. Changes to shared semantic layers run all dependent suites.

All merged changes still receive the full main/nightly coverage, preventing an incorrect path map from becoming a permanent blind spot.

### 6.4 Review ownership

Add `CODEOWNERS` or equivalent ownership for:

- parser/AST and language semantics;
- network generation and graph algorithms;
- NFsim internals;
- numerical solvers and stochastic validation;
- expressions and functions;
- Atomizer/SBML;
- Python API and packaging;
- CI/release/provenance;
- documentation and compatibility policy.

Changes to scientific semantics, oracle generation, comparators, tolerances, exception policy, or compatibility require at least one domain-owner approval in addition to the implementing reviewer. Changes that modify both implementation and acceptance thresholds should normally be split into separate PRs.

### 6.5 Lessons to adopt from Playground repositories

Adopt from BNG Playground:

- fast, build-check, sharded full, reference, and deterministic-parity layers;
- dedicated Atomizer validation;
- tool/entry-point initialization checks;
- CodeQL or equivalent security analysis;
- suppression-budget enforcement;
- RuleHub manifest validation and generated-file diff checks.

Improve on it by pinning RuleHub, BNG2, NFsim, compilers, package-manager state, and golden artifacts in every scientific claim. A structurally green fast/full suite is not by itself release-wide native parity.

Use Jules Playground as a valuable independently implemented differential target. Disagreements among BNG3, native oracles, and the TypeScript implementation are useful triage signals, but BNG3 should not automatically assume either rewrite is correct.

## 7. Phased roadmap

Each phase has deliverables and an exit gate. Later phases may prepare in parallel, but deletion and authority changes follow the stated dependencies.

### Phase 0 — Establish authority and freeze the common ground

**Deliverables**

- Approve this architecture decision and name maintainers/owners.
- Verify source heads and choose the accepted baseline revisions.
- Add `provenance/upstreams.lock.yml` and the reconciliation-ledger schema.
- Inventory capabilities, public APIs, command-line behavior, formats, platforms, and known failures.
- Map current BNG3 code to BioNetGen, NFsim, and PyBioNetGen source revisions.
- Pin RuleHub and generate initial tier manifests.
- Define support and deprecation policy for the legacy repositories.

**Exit gate**

Every source revision and capability has an owner and status. No unclassified source delta remains hidden behind a copied directory.

### Phase 1 — Make CI honest and green

**Deliverables**

- Fix the current cross-platform build failures.
- Remove failure suppression and direct-push autofixes.
- Correct misleading job names and missing-oracle behavior.
- Establish required PR platform builds, unit tests, Tier-S, and installed-package smoke tests.
- Publish machine-readable terminal summaries and exception counts.

**Exit gate**

The exact main-branch SHA is green on required platforms, and every green job corresponds to the behavior its name claims to validate.

### Phase 2 — Build independent validation foundations

**Deliverables**

- Build pinned BNG2 and NFsim oracle artifacts from recorded revisions.
- Complete the typed comparison library.
- Generate and review the first provenance-complete golden bundle.
- Add pinned RuleHub corpus discovery and tier manifests.
- Add strict exception-ledger and suppression-budget checks.
- Complete deterministic and stochastic validation designs.

**Exit gate**

Tier-S runs end-to-end against independent oracles. A clean machine can reproduce or verify the golden bundle from the manifest.

### Phase 3 — Reconcile source-repository drift

**Deliverables**

- Review every post-baseline BioNetGen, NFsim, and PyBioNetGen commit.
- Port correctness/security fixes and their tests first.
- Complete the reconciliation ledger with BNG3 PR links.
- Add the scheduled read-only upstream drift report.

**Exit gate**

Every source commit through the selected cutoff is incorporated, superseded, rejected with rationale, or tracked as an explicit blocker.

### Phase 4 — Converge semantic core components

**Workstreams**

- **WO-1a:** Correct BioNetGen network canonicalization and eliminate network overcount differences.
- **WO-1b:** Deduplicate the Nauty build while preserving NFsim identity behavior.
- **WO-3:** Converge expression representation and evaluation contracts.
- **WO-5:** Route all supported writers through the C++ writer layer and bindings.

**Exit gate**

Tier-S is green, relevant Tier-P/NF/X shards pass, the known overcount cases are resolved or have reviewed semantic explanations, and no capability has been lost.

### Phase 5 — Complete direct NFsim integration

**Deliverables**

- Complete typed mapping for parameters, molecule types, species, rules, transformations, observables, functions, compartments, and options.
- Define memory ownership, lifecycle, diagnostics, and seed handling at the adapter boundary.
- Run the direct adapter and XML bridge in shadow comparison.
- Validate against the independent native NFsim oracle.
- Remove the XML round trip and temporary files from the default simulation path only after parity.
- Retain BNG-XML as a supported interchange/export format.

**Exit gate**

The complete pinned Tier-NF suite passes the predeclared deterministic and distributional criteria through the direct adapter, with no fallback on the default path.

### Phase 6 — Consolidate Python, CLI, and Atomizer

**Deliverables**

- Freeze and test the supported public Python and CLI contracts.
- Route all simulation methods through the unified C++ engine.
- Route ModelBuilder into the canonical AST.
- Route Atomizer output through the canonical parser with provenance.
- Add compatibility shims and warnings for approved legacy entry points.
- Remove legacy `core`, `modelapi`, `network`, and `simulator` implementations only after zero-reference and contract gates pass.
- Correct package metadata, repository URLs, dependency policy, and wheel contents.

**Exit gate**

Clean installed wheels pass API/CLI/scientific smoke tests on supported platforms; default imports contain no retired parse or simulation implementation; documented compatibility behavior is verified.

### Phase 7 — Remove redundancy and retire independent development

**Deliverables**

- Delete duplicated libraries, adapters, model copies, and unreachable compatibility code with explicit delete lists.
- Archive or maintenance-mode legacy repositories according to policy.
- Redirect contribution documentation and issues to BNG3.
- Preserve pinned oracle source/artifacts for supported validation windows.
- Publish migration guidance for developers and Python users.

**Exit gate**

No production component has two authoritative implementations; all deletions pass full parity and package gates; repository authority is unambiguous.

### Phase 8 — Release qualification and steady-state governance

**Deliverables**

- Produce the first release candidate from a locked source/corpus/oracle manifest.
- Run all release gates on the exact candidate SHA.
- Publish signed or attested binaries/wheels, source manifest, validation report, exception ledger, and migration notes.
- Establish a recurring compatibility, benchmark, dependency, and upstream-drift review cadence.

**Exit gate**

BNG3 can be rebuilt and its scientific validation claims independently inspected from published provenance.

## 8. Work-order dependency map

The current work-order specification remains useful as a tactical file-level guide, with the WO-1 correction described above.

```text
Phase 0 authority/source lock
          │
          v
WO-0 validation and provenance spine
          │
          ├────────> WO-1a network canonicalization ──> WO-1b Nauty dedup
          ├────────> WO-3 expression contract
          ├────────> WO-5 writers
          └────────> WO-7 CI/review enforcement
                              │
WO-1 evidence ────────────────┴──> WO-2 direct NFsim adapter
WO-1/2/3/5 proven ───────────────> WO-4 Python/CLI consolidation
WO-1 through WO-5 proven ────────> WO-6 redundant-tree deletion
all gates and provenance green ──> first qualified BNG3 release
```

Parallel work is safe only when branches do not change the same semantic contract or its acceptance threshold. Shared AST, expression, graph, or result-schema changes must be serialized or coordinated through an integration branch with complete dependent testing.

## 9. PR structure and execution discipline

Use small, reviewable PRs organized around one behavior and one gate. A typical convergence PR should contain:

1. Source/issue provenance and the affected capability.
2. A regression or differential test that fails before the change.
3. The minimal implementation or adapter change.
4. Passing targeted and Tier-S gates.
5. Reconciliation-ledger update.
6. Documentation/API update if the contract changed.
7. No unrelated golden, tolerance, or exception changes.

Recommended PR sequence for a master-function replacement:

1. Add comparator and oracle fixture.
2. Add the replacement behind an explicit development switch.
3. Run old and new paths in shadow mode.
4. Make the new path default after evidence is green.
5. Remove the old path in a later PR after a stabilization window.

This sequence keeps defects attributable and rollback straightforward.

## 10. Risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| False parity from shared code or shared bugs | Regressions appear validated | Keep independent pinned oracles outside the product graph and use multiple evidence types. |
| Uncontrolled upstream drift | Endless merge work and lost fixes | Canonicalize BNG3 authority; use a report-only drift bot and a reconciliation ledger. |
| Overaggressive deduplication | Scientific behavior changes | Unify contracts before implementations; preserve domain-specific graph identity where required. |
| Stochastic flakiness | Retry-driven false greens or developer distrust | Fixed ensembles, power-calibrated thresholds, aggregate statistics, no retry-until-pass. |
| Golden files without provenance | Irreproducible correctness claims | Content-addressed bundles with model, source, build, command, and comparator manifests. |
| Platform-specific build failures | Releases differ from CI or omit users | Required Linux/macOS/Windows builds and clean-wheel tests on the exact release SHA. |
| Python compatibility breakage | Downstream users cannot migrate | Public-surface inventory, contract tests, deprecation releases, migration guide. |
| Atomizer semantic loss | Valid-looking but incorrect converted models | Feature-aware semantic round trips and explicit unsupported-feature reports. |
| CI becomes too slow | Developers bypass or ignore gates | Tiered, sharded, change-aware PR tests plus mandatory full main/nightly coverage. |
| Documentation drift | Contributors implement contradictory designs | One governing architecture decision, link checks, and docs updated in contract-changing PRs. |
| Performance regression during abstraction | Correct but impractical simulator | Versioned benchmarks in Tier-B; require measured evidence for optimizations. |
| Premature deletion of oracles | No way to prove migration correctness | Retain buildable pinned oracle artifacts through at least the supported migration window. |

## 11. Definition of done

BNG3 integration is complete only when all of the following are true:

- BNG3 is the documented and operational source of truth for new development.
- The accepted BioNetGen, NFsim, and PyBioNetGen source ranges are completely reconciled in a reviewed ledger.
- One canonical AST serves BNGL, ModelBuilder, Atomizer output, simulation backends, and writers through explicit boundaries.
- BioNetGen network canonicalization matches the accepted BNG2 semantics across the pinned Tier-P corpus.
- One low-level Nauty dependency is built, without changing unproven NFsim identity semantics.
- NFsim runs from the direct AST adapter without XML serialization or temporary files on the default path.
- Expression semantics are defined once and pass cross-backend tests.
- Python and CLI public contracts are versioned, documented, and validated from installed artifacts.
- Legacy parse/simulation implementations are absent from the default path and redundant trees are deleted only after their gates pass.
- Pinned RuleHub Tier-S/P/NF/X/B manifests are committed and reproducible.
- Deterministic, stochastic, conversion, API, platform, and packaging gates pass on the exact release SHA.
- Every skip/expected failure is strict, owned, linked, dated, and visible in a non-increasing exception budget.
- Golden and release artifacts include source, dependency, corpus, oracle, command, and comparator provenance.
- CI never reports scientific success when a required oracle or corpus is unavailable.
- The release workflow cannot publish an unqualified tag.
- Legacy repositories have a documented maintenance/retirement state and contribution path to BNG3.

## 12. Maintainer decisions required before implementation

The implementation should not begin until maintainers decide:

1. The exact source cutoffs recorded in the initial lock file.
2. The supported Python, compiler, operating-system, and architecture matrix.
3. Which PyBioNetGen imports and CLI behaviors are public compatibility commitments.
4. The precise BNG2 and NFsim oracle build recipes and retention window.
5. The initial RuleHub tier selectors and the treatment of ambiguous compatibility metadata.
6. Numerical tolerances and stochastic acceptance procedures, reviewed by domain experts.
7. Owners and required approvals for each semantic area.
8. The deprecation and maintenance timeline for the three legacy repositories.
9. Whether the sanctioned Perl compatibility mode remains a release feature or becomes a developer-only validation tool after migration.

Once these decisions are recorded, [BNG3_unification_spec.md](../BNG3_unification_spec.md) can be revised into implementation-ready work orders whose file lists, tests, and deletion gates agree with this plan.
