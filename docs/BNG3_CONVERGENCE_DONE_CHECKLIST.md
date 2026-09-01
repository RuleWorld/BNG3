# BNG3 Convergence: Definition of Done and Remaining Checklist

**Status:** Active; not complete
**Last audited:** 2026-09-01
**Repository:** RuleWorld/BNG3
**Working branch:** codex/bng3-integration-foundations
**Audited semantic code head:** 2940a021b6dad33894f93f8fdf405090e2a79b1f
**Checklist refresh base:** 2940a02 (refresh after each semantic checkpoint)
**PR:** RuleWorld/BNG3#2
**Independent implementation reference:** RuleWorld/bngplayground Atomizer
**Energy-evaluator source reference:** akutuva21/nfsim PR #475, merged at
6690fda5d9e053df822d0248ebae185f5caca82a; accepted energy-source cutoff
3b046fc1b9f76719d92be22279b24992cdae7c35. The current public NFsim checkout
is a6f9fa945c9d6e1e122e789c952260112c93f157; later non-energy source changes
are not silently included in the BNG3 port.

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
- [x] The latest pushed semantic checkpoint is
  2940a021b6dad33894f93f8fdf405090e2a79b1f; this checklist refresh is a
  documentation-only checkpoint layered after it and does not alter its
  semantic test evidence.
- [x] The small documentation grammar fix remains the only unrelated tracked
  BNG3 worktree modification. It remains intentionally unstaged and must not
  be mixed into semantic or checklist commits.
- [x] Exact-head CTest passes `144/144` on 2940a02 (local Release/Ninja
  build; `ctest --test-dir build --output-on-failure`).
- [x] The full NFsim AST adapter executable passes 96 test cases and 942
  assertions on 2940a02, including compact energy evaluation, cached compact
  rate factors, specialized reverse propensities, sparse selector ordering,
  cached single- and multi-term Arrhenius factors, direct-product endpoint
  identity propagation, safe direct-product traversal, cached pre-fire binding
  rejection, compact partner mapping-slot compaction, indexed cross-type
  partner refresh, shared partner-pool updates, dense and sparse type-invariant
  membership decisions, deferred weighted-side propensity capture,
  endpoint-refined membership refresh decisions, materialized fallback,
  all-forward compact partner-pool refresh early return,
  pure-context homodimer/trimer/scaffold counting,
  transformed homodimer binding multiplicity, and pure DOR context counting.
- [x] Exact-head Python/API tests pass on the current public checklist head
  `ab489cae` (semantic code head `2940a02`): `229 passed, 27 skipped, 8
  warnings` from `PYTHONPATH=python:build/cpp python -m pytest tests/python -q`,
  and the same result from the installed-wheel target.
- [x] Local CI workflow contract tests pass 10/10, including the pull-request
  source-distribution smoke gate.
- [x] Local canonical Black check passes: `177 files would be left unchanged`
  (Jupyter files are skipped because optional Jupyter dependencies are absent);
  Ruff and git diff checks pass.
- [x] Local validation smoke on semantic head `2940a02` reports 4 passed and
  15 skipped. A sandbox-external rerun removes process-inspection noise; the
  remaining skips are visible `run_network`/reference-oracle gaps and must not
  be treated as parity.
- [x] Non-strict provenance, corpus-manifest, generated-manifest, and exception
  ledger checks pass. The strict provenance gate remains intentionally red with
  10 pending source/oracle/compiler/Python-lock approval errors.
- [x] A no-build-isolation sdist and wheel were rebuilt from the current public
  checklist head `ab489ca` (semantic code `2940a02`) and the wheel was
  installed into an isolated target. Artifact SHA-256 digests are
  `2047835cc20fc6ffb95bcb1c087d645c85bf811073c1531e57cad8af691d9ce9`
  (sdist) and
  `dd6fe81bd14b41007a707ce41de0bdc6cbe197733d890f849bca45f51d7e6f3f`
  (CPython 3.14 arm64 wheel); the installed-target Python suite is recorded
  above.
- [ ] Hosted PR checks at the preceding exact public checklist head
  `b128e4a0ce852a9a293ae2f956f4e25b16637e7b` (documentation-only after
  semantic head `2940a021b6dad33894f93f8fdf405090e2a79b1f`) are currently
  queued or in progress and have
  not yet produced a complete terminal set across the C++ matrix, Python
  matrix, ASan, integration, validation, package smoke, formatter, and
  CodeQL. Older runs are historical and do not establish evidence for this
  head. The subsequent checklist documentation checkpoint requires a fresh
  exact-head set of its own.
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
- [ ] Tier-NF includes localfunc, motor, TQSSA, tlbr, simple_system,
  fceRI/multisite fixtures where supported, and the relevant nfsim-master/test
  inputs.
- [ ] The AN2 trajectory mismatch is resolved with a source-level diagnosis,
  discriminating fixture, and independent evidence.
- [ ] Protocol NF support and remaining RNA/t4/t5/IfTest direct behavior are
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
- [x] Source-derived BNG3 tests define compact binding-context extraction,
  rejection of duplicate weighted molecule topologies, compact conjunction
  masks, factorized runtime propensity evaluation, shared partner-pool
  registration/indexing and selector batch updates, and materialized fallback.
  Current checkpoints are `b9ab125`, `2b1c02f`, `92543ca`, `6ed6e97`,
  `a77ceb8`, `b8f44e4`, `4a2fc3e`, `738c881`, `6b6e246`, `bd29714`,
  `401becf`, `6c681269`, `a97c02e`, `7b2a199`, `dbadea6`, `c0d1bb5`,
  `bb3ae01432adfd8bb92240af3e1e947e49b017ee`, `464bd8d`, and `2940a02`.
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
  energy rules because the current direct AST Arrhenius helper requires a
  bidirectional rule; one-way direct-AST energy mapping remains an explicit
  unsupported gap.
- [ ] Port and test the remaining supported CPU evaluator slices from the
  merged NFSIM source: the broader full incremental-membership machinery and
  the remaining direct-product path.
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
  `a97c02e`, reverse specialization at `dbadea6`, partner endpoint/indexed
  decision refresh at `bb3ae014`, pure-context counting at `bb14a207`, and
  sparse membership-decision indexing at `fbfda3f`, and all-forward compact-pool
  early return at `2940a02` from NFsim `fd01d015`;
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

- [ ] Current exact semantic PR head
  `2940a021b6dad33894f93f8fdf405090e2a79b1f` has a complete terminal hosted
  check set for C++, Python, validation, integration, formatting, ASan, and
  CodeQL. Exact run links and terminal results must be recorded with `gh`;
  older `464bd8d` and earlier runs are not evidence for this head. This
  documentation refresh creates a new public head and requires another exact-
  head check readback after push.
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
  sparse selector integration (`a97c02e`), indexed cross-type partner
  endpoint/decision refresh (`bb3ae014`), source-derived pure-context
  complex counting (`bb14a207`), sparse type-invariant membership-decision
  indexing (`fbfda3f`), and endpoint-refined membership refresh decisions
  from NFsim commit `ced6f60` (`464bd8d`), and all-forward compact partner-pool
  early return from NFsim commit `fd01d015` (`2940a02`). The direct-AST energy
  fixture documents that one-way Arrhenius rules currently do not reach the
  compact energy helper because it requires bidirectionality. Merged NFSIM PR
  #475 full incremental-membership
  semantics, remaining direct-product parity, independent energy parity,
  benchmark provenance, and source reconciliation are still open.
- cpp/nfsim/nauty24 and the NFsim ExprTk path remain in the build; the
  canonical-label and shared-expression master-function migrations are not
  complete.
- Direct NFsim remains a bounded subset with visible XML fallback/shadow
  machinery; AN2, protocol-NF, remaining function/rate-law, and full
  independent Tier-NF evidence remain open.
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
