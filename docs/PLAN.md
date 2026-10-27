# BNG3 Phase 2 release plan

BNG3 will deliver the entire 994-row capability inventory with the source semantics of BNG2, NFsim and PyBioNetGen and the BNG3 additions. Exact-main independent checks determine release readiness.

The five largest obstacles are unverified inventory statuses; incomplete independent acceptance and expected outputs; shared compiled-model and backend semantics; SBML and network-free semantic coverage; and CI latency with incomplete per-case evidence. Consolidate the two capability lists, duplicated workflow-property checks, status reporting and backend decisions without removing evidence or weakening distinct checks.

Use two Luna agents: one performs a product slice while the other owns independent acceptance work, with exclusive files and serialized shared product ownership. The first three packages are #472 documentation standardization, the anti-gaming CI checks, and auditing every inventory row. The remaining sequence expands independent BNG2 expected outputs, builds issue-specific checks, and implements the dependency-ordered product slices.

## 4.1 Process infrastructure

Baseline: `eb70e7bef25b2460741f975e23faab42420e8ade` (PR #469). Sizes below count physical lines in the checked-out files, including JSON and fixtures, and bytes on disk; they are not token counts. Agent-context cost means the amount an agent would have to ingest if reading an entire item; agents should instead consult the specific entry or generated index. CI time is runner elapsed time, not queue time or billed minutes; per-item timing is unavailable because current jobs combine steps. Section 4.3 will measure job-level costs from recorded runs. Do not infer a per-check cost from the combined job.

| Item | Failure prevented; users | Size and context cost | Action |
|---|---|---|---|
| `provenance/` | Locks source/oracle identity, records selection, schema, expectations, obligations and campaign evidence; validation scripts and workflows consume individual files (`tests/validation/conformance.py:603`, `tests/validation/issue_queue.py:719`, `.github/workflows/sbml-conformance.yml:128`). | 64 files, 313,571 lines, 11,783,590 bytes. High if loaded wholesale; per-step CI minutes not separately measured. | Keep all records; index by role and digest, retrieve on demand, and retain generated evidence as bounded artifacts where reproducibility and retention are secured. Validate canonical source and hashes in PR CI. |
| `provenance/issue-obligations.json` | Declares issue/check identities independently of execution; `issue_queue.py:185` and `integrated.py:1250` read it. | 13,374 lines, 780,400 bytes; high context. Its time is embedded in integrated validation. | Strengthen: schema-validate uniqueness and nonempty requirements, require exact revision and consumer receipts, and expose a compact per-issue projection. Keep all obligations and history. |
| `tests/validation/evidence/lane-status.json` | Historical coordination/status evidence, not a current acceptance receipt. `scripts/ci/validate_sbml_test_suite.py:893` explicitly excludes it from source comparisons. | 498 lines, 29,259 bytes; medium context; no standalone job timing established. | Keep as history, generate current status from verified receipts, distinguish historical status from current main evidence, and read on demand. |
| `tests/test_ci_contract.py`, `tests/test_workflow_contract.py`, `tests/test_workflow_guard_selftests.py` | Detect workflow wiring or selectors that would silently bypass tests; lint executes both contract groups (`ci.yml:85-92`). | 1,956 + 568 + 87 = 2,611 lines, 99,818 bytes; high context. Combined lint step time is not attributable from these files. | Strengthen semantic assertions and self-tests; consolidate duplicated workflow-property assertions by property, retaining all cases and protections. Do not eliminate separate genuinely different properties. |
| `tests/validation/exceptions.json` and `exception_ledger.py` | Prevent silent expected-failure expansion, stale approvals and false passes; ledger checks uniqueness and expiry (`exception_ledger.py:170-201`); lint enforces the budget (`ci.yml:81-82`). | Ledger code 267 lines/9,217 bytes; ledger currently empty (`exceptions.json:3`); low default context. Timing included in lint. | Keep and strengthen: independent owner, matching failure signature, expiration, strict unexpected-pass failure; no exception counts as release support. |
| `tests/validation/` evidence, comparison, reporting and oracle code | Preserves classifications, first differences, source identity and issue receipts; `integrated.py:1184-1261`, `ci_report.py:265-269`, `issue_queue.py:185` are consumers. | 1,002 files, 177,817 lines, 13,603,625 bytes including fixtures; high context; many jobs share these files, so no single measured cost. | Keep checks, evidence and records; expose a small documented API and per-case manifest, shard and stream receipts, index fixtures rather than loading them wholesale. |

**Overlap and consolidation.** The 994 `rows` and 85 `validation_capabilities` entries in `provenance/capability-matrix.yml` represent two inventories consumed separately (`conformance.py:598`, `integrated.py:1186`, `ci_report.py:269`). Reconcile each legacy capability and its checks to one or more stable release row IDs; preserve the complete legacy metadata and historical IDs as aliases/relations on canonical rows, including any orphan by explicitly adding or documenting it. Update all three consumers and schema together; prove lossless coverage and unchanged classifications with a dual-read migration test. The committed 994 rows are authoritative: `build_inventory.py` produces only 941 and must not overwrite them. Do not deduplicate distinct semantic checks merely because they share a capability.

Workflow contract files overlap in *structural validation of workflow YAML*. Build one canonical property registry and one parametrized checker for each identical invariant, with mutation fixtures proving each property can fail; leave distinct coverage (e.g. path wiring versus selector collection versus guard self-tests) intact. Manifest shape, generated-selection consistency and oracle-source identity are related but different properties (`ci.yml:59-79`); share parsing/schema utilities and report each property once, rather than collapse them into a weaker single assertion. Issue reports and lane summaries both present status: generate both views from a common immutable, revision-bound case-receipt store; do not equate a producer receipt, status summary or historical record with a consumer check.

**All workflow jobs.** Run the following independently and retain each check's content and artifacts. `ci.yml`: lint, harness, windows-harness-reexec, cpp-build, cpp-asan, python-native-lifecycle, cpp-cuda, batch-ssa-cpu-reference, validation, corpus-parse, python-jax, python-test, python-integration, package-smoke, wheels, sdist, publish, docker. `parity.yml`: oracle-lock, bng2-parity, integrated-semantic-validation, conformance-findings, nfsim-parity, nfsim-source-validation, pybionetgen-compat. `sbml-conformance.yml`: conformance and curated-biomodels. `weekly.yml`: bng-validation, nfsim-execution-smoke, python-full, benchmarks, cross-validation. `formal.yml`: lean-kernel. `codeql.yml`: analyze. `autofix.yml`: formatting-patch. `release.yml`: qualify, build-binaries, build-wheels, build-sdist, release, publish-pypi. Definitions are at the job headings in those workflows. Their existing run-time costs are job-level data, not attributable to individual components; section 4.3 will report the available measurements. Required PR checks should be a fast representative subset, full matrix/corpora run independently on relevant PRs and main, scheduled and release tiers retain full qualification. Publish steps remain dependent on verified qualification and artifacts; unrelated test jobs should not wait on lint or another platform's build.

## 4.2 Independent semantic qualification

**Current evidence and boundaries.** `tests/validation/golden/` contains only three models: `gene_expr`, `michment`, and `simple_system`, with 200 trajectories each. All other BNG2 comparisons run BNG2 live. `scripts/regen_golden.py:1-5,200-231` describes and invokes the Perl/BNG2 generator; `oracle_perl.py:154-180` uses a golden or live Perl and reports unavailability. Do not treat provenance as verified merely because a file is in that directory: associate every output with a valid source/oracle/version/command/seed/digest manifest; `provenance/golden/README.md:7-31` describes that contract, but its statement about approved bundles must be checked against actual manifests and the current lock rather than assumed to be current. Unverified files remain historical evidence, not a release oracle.

`oracle_nfsim.py:24-35` requires an explicitly supplied native binary, and `:46-57` generates the XML with BNG3; therefore this is an independent execution oracle for *that XML*, but not an independent BNGL-to-XML translation oracle. Generate XML separately with pinned BNG2 or compare source and lowered XML with a separately derived semantic oracle. `integrated_source.py:76-118` runs raw SBML in libRoadRunner; `sbml-conformance.yml:93-94,144` runs the official suite and installs RoadRunner. Official expected data comes from the upstream suite, not BNG3; source-road-runner values come from the original SBML executed by that independent implementation. `integrated_marginals.py:218-245` also compares to computed source laws. BNG3-written networks, XML, round trips and BNG3-vs-BNG3 solver comparisons are useful stage/invariant checks but are not independent expected behavior. The complete fixture-level provenance audit is an explicit first framework deliverable; unknown origin is *unverified*, not falsely labeled BNG3-produced or independent.

**Framework and case contract.** Independently owned acceptance code declares required check IDs and inventory IDs before execution, case input and SHA-256, independently verified source validity, source/oracle version and build digest, command and platform, quantity and units, exact or numeric expectation, predeclared tolerance or statistical test, parameters, seeds, and revision of the product under test. A producer and every intended consumer emit separate receipts with SHA-256 digests recorded in each shard manifest. Compare the raw source model to each consumer output in source coordinates, with separately validated unit and name mapping. Independently pin BNG2, native NFsim, PyBioNetGen, libRoadRunner and official SBML source and binaries using `provenance/upstreams.lock.yml`. Analytic laws and invariant proofs need reviewed derivations, not values generated by the SUT. Failure, unsupported, invalid source, timeout, harness error and success remain distinct. A failed source-validation stage cannot yield a supported result. `release-inventory` fails if even one row lacks a passing independently grounded `release-capability[ID]` check on exact main.

**Breadth and initial minimum case budget.** These are planned minimums, not existing pass counts, and can be exceeded without limit. Count a case once in its primary area; multiple independent checks can cover one row and a case may map to multiple IDs. For inventory-owning issues, use at least one independently sourced case *per row*: #171 384 API/CLI/Atomizer; #140 144 compiled/parser; #160 117 SBML core; #163 94 package/composition; #143 68 engine/execution; #146 50 network-free; #161 45 Multi; #138 28 compiled inputs; #139 19 rule plans; #137 16 protocol; #150 8; #157 6 and #158 6 events; #156 2 equality; #177 2; #153, #170, #148, #144 and #176 one each. Total minimum 994 row-linked cases before extra boundary/combination cases. Include the entire official SBML Test Suite, curated BioModels and independently pinned BNG2, native NFsim and PyBioNetGen corpora in addition. Add at least 100 generated valid models per semantic area and all pairwise interactions among syntax, rates, compartments, events and execution method; grow whenever a defect exposes a gap. The issue number is an initial inventory ownership mapping, not evidence of present behavior. For packaging, CLI, analysis, graph equality or other areas without a suitable simulator, use separately implemented specification-derived analytic/structural oracle or independently verified executable contract, not a simulated proxy.

**Public tests and change control.** CODEOWNERS documents ownership; it does not enforce approval because agents and PR author use the maintainer account. Every test, case and expected output is public. Each of the following checks runs in CI using the base revision's copy of the check:

- Generated cases use a fresh seed every CI run; the shard manifest records the seed for replay.
- Fail a PR that changes product code together with expected outputs, tolerances, skips or exclusions, or removes or renames case IDs relative to base.
- Fail a PR if product code contains test fixture names, case model IDs or test paths.
- Run mutation testing on a schedule; a drop in the number of mutants caught fails release qualification.

Independent checking agents own tests and do not implement the product slice they assess.

**Mutation testing.** Deliberately introduce one semantically wrong product change at a time (rate multiplier, symmetry factor, volume conversion, event priority/persistence, delay scheduling, graph bond identity and numerical output), build the mutated product, and run the unchanged independent suite. Record killed, survived, invalid/equivalent and infrastructure-error mutants, by feature and row; a timeout is not automatically a kill. Require every curated, demonstrably non-equivalent semantic mutant to be caught, investigate survivors, and publish denominators and justified equivalent classifications. `tests/validation/test_campaign_mutations.py:42,98-106` mutates network/trajectory data to exercise the harness; this is useful harness self-testing, not a measurement of product mutant detection.

**Stochastic design.** For each source-law case preregister the full distribution or explicitly named marginal, observation times, null, detectable effect and family of tests. Start with 10,000 independently seeded trajectories per model/backend and 10,000 independently seeded oracle trajectories where no analytic CDF exists; derive sample-size/power calculations for the declared effect and increase the budget if necessary. Use an exact binomial/multinomial or prespecified empirical-CDF test appropriate to the law; allocate family-wise alpha 0.01 using Holm adjustment across declared model/time/observable comparisons, record seeds and run budgets, and report effect sizes and confidence intervals. Calibrate false positives and power with simulated known laws. Independence and proper unit mapping must be verified; same-seed pathwise comparisons only assert parity where construction and draw order are demonstrably comparable. Conservation and ODE agreement are narrower invariant checks, not evidence of distributional equality.

**Metamorphic and generated tests.** A separate generator produces valid source models, records seed/grammar/version and shrinks failures without changing the failure's independently validated source semantics. For each model check species/type renaming and inverse observable mapping, rule/site ordering, sum-preserving splitting of eligible rules, and rates multiplied by `c` with time divided by `c`, only when the model's time-dependent inputs, delays and event semantics make the relation valid. Compare to independent BNG2/native NFsim or analytic laws in addition to metamorphic relations. Use every equal and unequal pair in `docs/design/semantic-equal-design.md` for exact `semantic_equal`: test proofs/certificates and counterexamples on models, not simulated observables; undecided must remain undecided and must not become false.

Research basis: [McKeeman's differential testing paper](https://www.cs.tufts.edu/comp/150FP/archive/bill-mckeeman/DifferentailTesting.pdf); [test oracle survey](https://discovery.ucl.ac.uk/id/eprint/1471263/); [metamorphic testing in scientific software](https://pmc.ncbi.nlm.nih.gov/articles/PMC7252536/); [QuickCheck generated properties](https://www.cs.tufts.edu/~nr/cs257/archive/john-hughes/quick.pdf); [mutation testing survey](https://kelloggm.github.io/martinjkellogg.com/teaching/cs684-sp24/assets/mutation-testing.pdf); and [EvilGenie reward-hacking benchmark](https://futuretech.mit.edu/publication/evilgenie-a-reward-hacking-benchmark), which studies coding agents manipulating accessible tests or hardcoding cases. These methods reduce blind spots; none individually proves complete scientific correctness.

## 4.3 CI under unlimited submissions and uncontrolled queues

**Measured baseline, not a prediction.** Phase 1 evidence captures two exact revisions; each number sums `completed_at - started_at` for non-skipped jobs including cancelled jobs, without OS billing multipliers. Wall time is workflow creation to last observed completed job; queue is each job's `started_at - created_at`, and does not include time waiting for upstream `needs` to make a job eligible. One completed PR revision `ff6dc7775`: [CI 40551013979](https://github.com/RuleWorld/BNG3/actions/runs/40551013979) failed, 36 observed jobs, 270.4 runner-min, 45.5 min wall, median/max eligible-job queue 0.1/16.3 min; [parity 40551014244](https://github.com/RuleWorld/BNG3/actions/runs/40551014244) 36.0 runner-min/14.8 wall, [CodeQL 40551014075](https://github.com/RuleWorld/BNG3/actions/runs/40551014075) 16.4/14.7, [SBML 40551013906](https://github.com/RuleWorld/BNG3/actions/runs/40551013906) 7.1/7.8, [Lean 40551014258](https://github.com/RuleWorld/BNG3/actions/runs/40551014258) 0.9/1.0, and [format patch 40551014125](https://github.com/RuleWorld/BNG3/actions/runs/40551014125) 0.6/0.6: 331.4 observed runner-min across those six workflows, with workflow-specific triggers and an unsuccessful CI, not the cost of a successful PR. 

One successful main revision `1881854d1`: [CI 40529821210](https://github.com/RuleWorld/BNG3/actions/runs/40529821210), 42 observed jobs, 428.4 runner-min, 216.5 min wall and 21.1 min maximum eligible-job queue; [parity 40529821139](https://github.com/RuleWorld/BNG3/actions/runs/40529821139) 36.3/41.9, [CodeQL 40529821052](https://github.com/RuleWorld/BNG3/actions/runs/40529821052) 22.6/42.1, and [Lean 40529821389](https://github.com/RuleWorld/BNG3/actions/runs/40529821389) 0.8/2.5, totalling 488.1 observed runner-min. These are sampled historical runs, not current averages, budgets, billed minutes, or guarantees. They exclude workflows not triggered or not present in collected job pages. `ci.yml:136,163,554,718,855,1007` demonstrates dependency chains; downstream wait can dominate even when an individual job's queue is small. Capture job creation, start, completion, all attempts, trigger, revision and workflow using artifacts/telemetry going forward; report median and tail by workflow/event with explicit missing/cancelled populations.

**Tiers.** The required PR tier runs from the protected base policy, a small deterministic Linux build, focused independent smoke cases for changed surfaces, lint/contract and trust checks concurrently; within each job run known high-yield inexpensive assertions before expensive setup. One stable always-created required aggregator reports PASS/FAIL/SKIPPED-with-reason from the exact SHA, including path-filter decisions. Never allow filtered or missing checks to produce a scientific pass. Path maps come from reviewed base and include transitive consumers; unknown/shared changes trigger all affected checks.

Submit all platform builds, sanitizer, full API, oracle parity, formal, security, corpus, devices, packaging and benchmarks concurrently for relevant PRs and every main merge; also run complete scheduled and release qualification. Job inputs include exact product SHA, oracle-lock digest, selection digest and environment. Independent jobs build their own prerequisites or fetch a verified content-addressed build artifact keyed by exact SHA/ABI/platform; do not put a global `needs: lint` or `needs: cpp-build` in front of unrelated jobs. Fan in only where actual artifacts or publish/qualification require it. Each shard has deterministic case membership, can be dispatched and retried independently, and uses stable case IDs. Tests not chosen by the path map still run on main/scheduled/release. Release publishing remains gated on exact-main qualification, artifacts and independently owned required checks; the small PR tier does not replace release coverage.

Cache compiler (`ccache`/`sccache` keyed on compiler, flags, dependencies and source), pip wheels keyed by lock/platform/Python, and reference BNG2/NFsim binaries keyed by upstream commit, build recipe/toolchain/platform and digest. Cache reference outputs only with input, source revision, oracle binary, options, seeds, time grid and comparator/tolerance digests; a cache miss builds/executes, and any mismatch invalidates the entry. Cache is never evidence by itself. Treat caches from untrusted PRs as untrusted and do not permit them to poison trusted main or release runs.

A case runner writes an immutable result and digest immediately after each case to durable remote storage or small batch artifacts (upload step `always()` plus resumable checkpoints; forced runner termination can still lose the current batch). A final shard manifest states expected, completed, missing and aborted cases, with exact revision; a partial shard cannot claim full completion. First output on failure: `model=<id> oracle=<identity> quantity=<name/unit> expected=<value> actual=<value> tolerance=<rule>`; for a setup/source failure where a quantity or value does not yet exist use explicit `unavailable: <reason>`, followed by classification and replay packet. Each shard exports a bounded reproduction bundle and supports re-running by case ID. This is a planned log contract, not a claim that existing jobs already satisfy it.

## 4.4 Common interfaces and shared foundations

`docs/DECISIONS.md:7-9,13-14,22-30` sets native finite solvers as default, requires a common simulator interface and prescribes NFnext consolidation. Today `FiniteBackend.cpp:57-118` parses a finite-backend enum, selects native or BNGsim and dispatches ODE/SSA; `BngsimAdapter.cpp:307-319,326-360` independently resolves rates and rejects capability combinations. `OdeIntegrator.cpp:194,379-404,661-666` receives an AST model, compiles some rate dependencies and reconstructs rate text; `ActionDispatch.cpp:114-123,291-294,361-406` mixes action dispatch and net/rate interpretation. Several exporters read/clean rate strings themselves (`cpp/io/PythonExportWriter.cpp:173-174`, `MatlabWriter.cpp:229-231`), although `NetWriter.cpp:68-73` already delegates one TotalRate decision. `cpp/compile/CompiledModel.hpp:255-257` establishes an existing compiled-model type. Preserve and extend these rather than add a parallel semantic engine.

**Contract.** Conceptually every backend registers a stable ID and immutable capability descriptor (methods, semantic features and supported option domains, installation/device availability and explanation); `prepare(const CompiledModel&, const CompiledProtocol&, const SimulationOptions&) -> Session`, then `Session.run(initial_state, output_schedule, seed_or_rng) -> SimulationResult`. A result contains time coordinates, named observables/species and units, deterministic or ensemble dimension, metadata (backend/version, seed, model/protocol digest, solver options) and diagnostics; all failures use typed errors with source location and capability reason. Adapter-specific device state belongs inside Session. Compile-owned inputs outlive parsing; sessions have independent mutable state and can share immutable compiled inputs. An explicit unavailable or unsupported backend errors with its reason; automatic selection chooses the documented native default and never silently drops a semantic feature. Common option validation handles method defaults, invalid combinations and protocol semantics once; a backend declares limits rather than reinterpreting semantics. The registry can use native adapters and a versioned Python/plugin bridge for JAX or third parties, preserving the same logical contract without requiring a Python/GPU backend to implement a C++ ABI directly. PLA/PSA, BNGsim, NFcore, NFnext and GPU must run actual requested capabilities, not merely register names.

**Ownership and removal of duplication.** Compile expressions, rule modifiers, unit conversion and reaction-rate meaning into a typed semantic representation once; keep source-specific formatting in writers only. `ActionDispatch` translates typed actions into validated protocol requests and invokes the registry; `OdeIntegrator` consumes compiled laws and an optional generated network rather than reparsing NetWriter strings; `FiniteBackend` becomes a compatibility facade over the common resolver; `BngsimAdapter` translates typed rates/options and reports unsupported combinations through its descriptor. Exporters lower the same typed rate structures to target syntax while respecting target-specific representability; test each target against BNG2 or the specification. The common interface does not force NF engines to materialize an infinite finite network: the compiled model is common, and a finite generated network is a derived optional view.

CRN F06/#170 reads species, complexes, reactions, exact stoichiometry and rate structures from the compiled model and generated-network view, exposes a versioned public consumer format, and tests it with an independent `crnt-lean` consumer (`release-crn-api`, `release-crn-consumer`). BNGIR D04/#156 serializes and reconstructs the same compiled semantics losslessly with versioned schemas; exact equality compares process models and certificates, never trajectories as a definition. Do not equate CRN finite-network projection with complete rule-based BNGIR.

Shared changes, in dependency order, with acceptance owned separately: (1) #139 network-rule plan and #138 B01 compile-owned inputs unblock #143, #144, #147–#150, #153, #156, #170 and #178; eliminate AST runtime dependence only after parity and input-destruction tests. (2) #140 typed action/option protocol unblocks #137, #143, #144, #157/#158, #171 and #178, with source-default and interaction parity. (3) #178/#470 common interface unblocks #144, #149, #170, #171, #173's successor #473, #474 and backend parity, but adapters can be delivered in serialized slices after the shared contract. (4) #157/#158 event state and scheduling semantics unblock Core/comp and backend checks #159–#164. (5) #147 compiled-model→NFIR, then #148 general execution, then #149 consolidation/default and #176 performance follow the recorded NFnext order. Dependencies indicate enabling relationships and do not waive the issue's other acceptance checks.

## 4.5 Work packages for Luna delegation
Run **two Luna agents**. One owns an implementation slice while the other prepares independently owned acceptance checks; only one may change product files at a time. This matches the file overlap and avoids idle serialization of independent test work. Agents do not delegate. Create each worktree from current main under `/tmp/bng3-p2-<package>` on branch `codex/p2-<package>`. Merge each prerequisite before dependent work starts. Every package forbids changing expected outputs, tolerances, skips or exclusions except the separately assigned oracle/acceptance packages, and forbids touching files reserved to another active package. Acceptance tests for product packages are authored by the other agent. Normal execution tiers are PR, full main, scheduled and release as defined in 4.3. An issue closes only when every named check passes on main with artifacts; a package may contribute without closing it.
| Priority and package | Goal and exclusive files | Inputs and dependencies | Acceptance and tier; issue closed |
|---|---|---|---|
| 1 `docs` | Standardize active docs; owns `README.md`, `docs/` and `AGENTS.md` | Decisions and inventory; independent docs checks | `release-docs-links`, `release-docs-decisions`; PR and release; #472 after #137/#179 checks |
| 2 `antigaming` | Four base-revision checks: fresh recorded seed, protected diffs/case IDs, fixture-name scanning and scheduled mutation ratchet; owns `.github/workflows/` and `tests/validation/policy/` | 4.2; before any product implementation | Separate negative-fixture acceptance by the other agent, PR and scheduled/release; contributes #471 |
| 3 `audit` | Check all 994 status values against code and evidence; owns `provenance/capability-matrix.yml` | 4.1 and pinned source | `release-inventory`; PR/release; contributes #137 |
| 4 `matrix` | Reconcile all legacy capabilities into canonical rows and update three consumers; owns matrix, `tests/validation/conformance.py`, `integrated.py`, `ci_report.py` | audit | lossless migration and `release-inventory`, independently checked; PR/release; contributes #471/#137 |
| 5 `golden` | Expand independently generated BNG2 expected outputs from three models to every applicable inventory row; owns `tests/validation/golden/`, `provenance/golden/` and generation tools | matrix, pinned BNG2, 4.2 | provenance validation plus per-row independent comparison; PR/scheduled/release; contributes #471/#181 |
| 6 `checks-N` | Build issue N release checks separately from product work; owns only `tests/validation/release/cases/issue-N/` | anti-gaming, matrix and relevant oracle cases; one agent never implements same issue | every release identity named by issue N, including negative and mutation controls; PR/full/release; closes #154/#155/#159/#162/#177 when all own checks pass, otherwise contributes to N |
| 7 `product-N` | Implement issue N in its listed component; reserve all `cpp/`, `python/` and product scripts to this single active product package; paths listed below identify entry points, not exhaustive files | corresponding `checks-N` landed first; dependencies in each issue and section 4.4 | every listed issue check passes independently on main; PR/full/release; closes N |

Assign each `checks-N` and `product-N` to different agents, including across time. The checks agent may add only case inputs and expectations in its exclusive test directory; only the separate `golden` package updates shared goldens. Workflow wiring is serialized through the `antigaming` owner. Shared registries, docs and matrix likewise have a single owner; other packages submit requested edits for that owner. Changes to independent expectations occur in a separate PR from product changes.

Implementation queue: #139 → #140/#142/#143 → #138 → #178/#470 and #144 → #146/#147 → #148 → #149 → #150/#151/#176. #157/#158 event work precedes dependent #160/#161/#163/#164; #156 precedes #153 and #170 follows compiled input. #141, #152, #171/#172, #473/#474/#475, formal #166–#168, performance #174, provenance #179/#180, corpus #181, and release #184–#186 proceed after their issue dependencies. #154/#155, #159/#162 and #177 are independent-check packages, not product packages. Where issue dependencies form a cycle, deliver an independently checked contract slice first; closure still requires the complete union of checks. The release critical path is anti-gaming → inventory and oracle framework → compiled semantics/protocol → backend and NFnext/SBML implementation → full independent corpus and install qualification → #184.

Issue-specific worktree/branch names follow the package rule above, e.g. `checks-153` uses `/tmp/bng3-p2-checks-153` and `codex/p2-checks-153`; `product-153` uses `/tmp/bng3-p2-product-153` and `codex/p2-product-153`. The following inventory provides each package’s exact check identities and starting files; read its rewritten issue for the full acceptance and dependencies before starting.

| Issue / goal | Product starting files; test ownership | Required checks |
|---|---|---|
| #137 Establish the complete release capability inventory | `docs/CAPABILITY_UNION_INVENTORY.md`; `provenance/capability-matrix.yml`; `tests/validation/release/cases/issue-137/` | `release-inventory`, `release-inventory-links`, `release-capability-coverage-137` |
| #138 Execute from the compile-owned semantic model | `cpp/compile/CompiledModel.hpp`; `provenance/architecture/ast_compat_allowlist.txt`; `tests/validation/release/cases/issue-138/` | `release-compiled-inputs`, `release-compiled-parity`, `release-capability-coverage-138` |
| #139 Replace reconstructed AST network-rule execution | `cpp/engine/LegacyNetworkRuleKernel.cpp`; `cpp/engine/NetworkRulePlan.cpp`; `tests/validation/release/cases/issue-139/` | `release-network-rule-plan`, `release-network-rule-mutations`, `release-capability-coverage-139` |
| #140 Type and unify every BNGL action and option | `cpp/compile/Document.hpp`; `cpp/actions/ActionDispatch.cpp`; `tests/validation/release/cases/issue-140/` | `release-actions`, `release-entrypoints`, `release-capability-coverage-140` |
| #141 Qualify compile-once execution and isolated trajectories | `cpp/compile/CompiledModel.hpp`; `cpp/engine/NetworkGenerator.cpp`; `python/bionetgen/scan.py`; `tests/validation/release/cases/issue-141/` | `release-instance-isolation`, `release-lifecycle`, `release-obligation-141` |
| #142 Unify graph identity semantics across engines | `cpp/ast/SpeciesGraph.cpp`; `cpp/nfsim/NFcore/complex.cpp`; `tests/validation/release/cases/issue-142/` | `release-graph-identity`, `release-graph-observables`, `release-obligation-142` |
| #143 Complete shared rate and function semantics | `cpp/compile/CompiledRateLaw.hpp`; `cpp/nfsim/NFfunction/nfsim_funcparser.h`; `tests/validation/release/cases/issue-143/` | `release-rates`, `release-rate-invalidation`, `release-capability-coverage-143` |
| #144 Support optional BNGsim through the common backend interface | `cpp/engine/FiniteBackend.cpp`; `cpp/engine/BngsimAdapter.cpp`; `docs/adr/0003-bngsim-canonical-finite-backend.md`; `tests/validation/release/cases/issue-144/` | `release-bngsim`, `release-bngsim-parity`, `release-capability-coverage-144` |
| #146 Qualify all NFcore input and execution routes against native NFsim | `cpp/nfsim/NFinput/NFinput_fromAst.cpp`; `tests/validation/release/cases/issue-146/` | `release-nfcore`, `release-nfcore-statistics`, `release-capability-coverage-146` |
| #147 Complete NFnext lowering for every BNGL semantic family | `cpp/nfnext/src/from_bng.cpp`; `cpp/nfnext/include/nfnext/nfir.hpp`; `tests/validation/release/cases/issue-147/` | `release-nfir-lowering`, `release-nfir-roundtrip`, `release-obligation-147` |
| #148 Complete general NFnext execution of real BNG3 models | `cpp/nfnext/src/from_bng.cpp`; `tests/validation/release/cases/issue-148/` | `release-nfnext-execution`, `release-nfnext-routes`, `release-capability-coverage-148` |
| #149 Consolidate NFcore2 into NFnext and promote NFnext | `cpp/nfsim/NFcore2/driver.cpp`; `cpp/nfnext/src/from_bng.cpp`; `cpp/nfsim/NFinput/NFinput.cpp`; `tests/validation/release/cases/issue-149/` | `release-engine-consolidation`, `release-nf-default`, `release-obligation-149` |
| #150 Implement complete particle-population hybrid execution | `cpp/engine/HybridModelGenerator.cpp`; `cpp/ast/PopulationMap.hpp`; `formal/lean/BNG/Hybrid.lean`; `tests/validation/release/cases/issue-150/` | `release-hybrid`, `release-hybrid-conservation`, `release-capability-coverage-150` |
| #151 Complete physical-unit count and rate conversion for NFsim | `cpp/compile/Capabilities.cpp`; `cpp/nfsim/NFinput/NFinput_fromAst.cpp`; `tests/validation/release/cases/issue-151/` | `release-nf-units`, `release-unit-scaling`, `release-obligation-151` |
| #152 Complete energy and protocol capabilities in the release | `provenance/reconciliation/nfsim.yml`; `docs/nonequilibrium_energy.md`; `tests/validation/release/cases/issue-152/` | `release-energy-protocols`, `release-extension-protocols`, `release-obligation-152` |
| #153 Reconstruct every BNGIR construct natively | `python/bionetgen/bngir.py`; `cpp/bindings/bind_compile_snapshot.cpp`; `tests/validation/release/cases/issue-153/` | `release-bngir-native`, `release-bngir-native-invalid`, `release-capability-coverage-153` |
| #154 Verify lossless BNGIR round trips for all BNGL | `python/bionetgen/bngir.py`; `tests/validation/release/cases/issue-154/` | `release-bngir-roundtrip`, `release-bngir-version`, `release-obligation-154` |
| #155 Build independent adversarial native BNGIR contracts | see issue; `tests/validation/release/cases/issue-155/` | `release-bngir-adversarial`, `release-bngir-consumer`, `release-obligation-155` |
| #156 Make BNGIR v0.2 lossless and implement exact semantic equality | `python/bionetgen/bngir.py`; `tests/validation/release/cases/issue-156/` | `release-bngir-schema`, `release-semantic-equality`, `release-capability-coverage-156` |
| #157 Complete native dynamic event execution | `cpp/engine/OdeIntegrator.cpp`; `python/bionetgen/atomizer/modern/events.py`; `tests/validation/release/cases/issue-157/` | `release-events-roots`, `release-events-entrypoints`, `release-capability-coverage-157` |
| #158 Complete delayed, prioritized and stochastic event queues | `python/bionetgen/atomizer/modern/events.py`; `tests/validation/release/cases/issue-158/` | `release-event-queue`, `release-event-stochastic`, `release-capability-coverage-158` |
| #159 Qualify every SBML Core requirement against official expectations | `scripts/ci/validate_sbml_test_suite.py`; `tests/validation/release/cases/issue-159/` | `release-ssts`, `release-ssts-coverage`, `release-obligation-159` |
| #160 Complete SBML Core and comp semantics | `python/bionetgen/atomizer/modern/parser.py`; `python/bionetgen/atomizer/modern/writer.py`; `python/bionetgen/atomizer/modern/fast_reactions.py`; `tests/validation/release/cases/issue-160/` | `release-sbml-core-comp`, `release-sbml-source-fidelity`, `release-capability-coverage-160` |
| #161 Complete structural Atomizer and SBML Multi execution | `python/bionetgen/atomizer/modern/multi.py`; `tests/validation/release/cases/issue-161/` | `release-sbml-multi`, `release-atomizer-structure`, `release-capability-coverage-161` |
| #162 Complete curated BioModels source qualification | `scripts/ci/validate_biomodels.py`; `python/bionetgen/atomizer/modern/writer.py`; `tests/validation/release/cases/issue-162/` | `release-biomodels`, `release-biomodels-triage`, `release-obligation-162` |
| #163 Qualify every export and interchange format through its consumer | `cpp/io/`; `tests/validation/release/cases/issue-163/` | `release-formats`, `release-format-semantics`, `release-capability-coverage-163` |
| #164 Separate Atomizer responsibilities without duplicating semantics | `python/bionetgen/atomizer/modern/parser.py`; `python/bionetgen/atomizer/modern/writer.py`; `tests/validation/release/cases/issue-164/` | `release-atomizer-modules`, `release-atomizer-refactor`, `release-obligation-164` |
| #166 Prove production lowering correspondence | `formal/lean/BNG/Correspondence.lean`; `formal/lean/BNG/Lowering.lean`; `formal/lean/cpp_contract/nfnext_contract.cpp`; `tests/validation/release/cases/issue-166/` | `release-lowering-proof`, `release-lowering-bridge`, `release-obligation-166` |
| #167 Complete formal rate and stochastic semantics | `formal/lean/BNG/Stochastic.lean`; `formal/lean/BNG/Propensity.lean`; `tests/validation/release/cases/issue-167/` | `release-stochastic-proof`, `release-stochastic-correspondence`, `release-obligation-167` |
| #168 Prove canonicalization and exact network identity contracts | `formal/lean/BNG/Graph.lean`; `formal/lean/BNG/Network.lean`; `tests/validation/release/cases/issue-168/` | `release-identity-proof`, `release-identity-bridge`, `release-obligation-168` |
| #170 Expose a public chemical reaction network API | `cpp/engine/NetworkGenerator.hpp`; `python/bionetgen/model.py`; `tests/validation/release/cases/issue-170/` | `release-crn-api`, `release-crn-consumer`, `release-capability-coverage-170` |
| #171 Provide every PyBioNetGen capability in the public API | `python/bionetgen/__init__.py`; `python/bionetgen/model.py`; `tests/validation/release/cases/issue-171/` | `release-python-api`, `release-python-install`, `release-capability-coverage-171` |
| #172 Consolidate legacy Python implementations behind the maintained API | `python/bionetgen/modelapi/`; `python/bionetgen/compat/`; `tests/validation/release/cases/issue-172/` | `release-python-consolidation`, `release-python-legacy`, `release-obligation-172` |
| #174 Publish representative performance and memory measurements | `scripts/benchmark_atomizer_nfsim.py`; `tests/validation/release/cases/issue-174/` | `release-benchmarks`, `release-benchmark-correctness`, `release-obligation-174` |
| #176 Complete NFnext CPU, ensemble and GPU performance work | `cpp/nfnext/`; `cpp/engine/BatchSsa.cpp`; `tests/validation/release/cases/issue-176/` | `release-nf-ensemble`, `release-nf-gpu`, `release-capability-coverage-176` |
| #177 Independently verify barrier and driven-reservoir extensions | `docs/nonequilibrium_energy.md`; `cpp/compile/Capabilities.cpp`; `tests/validation/release/cases/issue-177/` | `release-barrier-energy`, `release-reservoir-energy`, `release-capability-coverage-177` |
| #178 Centralize option, rate and capability decisions | `cpp/actions/ActionDispatch.cpp`; `cpp/engine/OdeIntegrator.cpp`; `cpp/engine/FiniteBackend.cpp`; `cpp/engine/BngsimAdapter.cpp`; `tests/validation/release/cases/issue-178/` | `release-shared-decisions`, `release-interface-parity`, `release-obligation-178` |
| #179 Record accepted pins and enforce strict provenance | `provenance/upstreams.lock.yml`; `scripts/validate_provenance.py`; `.github/workflows/release.yml`; `tests/validation/release/cases/issue-179/` | `release-provenance`, `release-provenance-negative`, `release-obligation-179` |
| #180 Complete upstream source reconciliation | `provenance/reconciliation/bionetgen.yml`; `provenance/reconciliation/nfsim.yml`; `provenance/reconciliation/pybionetgen.yml`; `tests/validation/release/cases/issue-180/` | `release-reconciliation`, `release-reconciliation-pins`, `release-obligation-180` |
| #181 Populate complete capability-driven corpus tiers | `provenance/corpus/selection.json`; `tests/validation/release/cases/issue-181/` | `release-corpus-coverage`, `release-corpus-results`, `release-obligation-181` |
| #184 Qualify the public release on main | `.github/workflows/release.yml`; `.github/workflows/weekly.yml`; `tests/validation/release/cases/issue-184/` | `release-candidate`, `release-installed-artifacts`, `release-obligation-184` |
| #185 Assign all review ownership to akutuva21 | `.github/CODEOWNERS`; `tests/validation/release/cases/issue-185/` | `release-codeowners`, `release-review-rules`, `release-obligation-185` |
| #186 Publish the BNG3 installation and migration contract | `docs/migration_guide.md`; `tests/validation/release/cases/issue-186/` | `release-migration-docs`, `release-maintenance-docs`, `release-obligation-186` |

New issues: #470 shares #178 product ownership and checks `release-backend-contract` and `release-backend-oracles`; #471 owns anti-gaming and oracle consolidation; #472 owns docs; #473 owns JAX; #474 owns physical-device qualification; #475 owns delayed-rule completion. Their `checks-N` and `product-N` packages follow the same paths, separation, tier and closing rules. Required checks are #471 `release-oracle-independence`, `release-oracle-tamper`, `release-ci-topology`; #472 `release-docs-links`, `release-docs-decisions`; #473 `release-jax-ode`, `release-jax-ssa`, `release-jax-install`; #474 `release-cuda-device`, `release-cuda-performance`; #475 `release-delay-formats`, `release-delay-ode`, `release-delay-ssa`.

**Issue merges, applied later.** Merge #158 into #157 because both modify the event system; merge #470 into #178 because both own the backend interface files. Preserve all checks, history, links and inventory IDs in each surviving issue. Keep #139 separate from #138 and keep #154 and #155 separate from #153 because they hold independent checks. #173, #175, #135 and #136 are already closed; retain historical links and close nothing for those proposals. Keep #147/#148/#149/#176 and #159/#161/#162 separate.

The seven-lane `tasks/plan.md:19-23,38-50,107-113` used seven concurrent worktrees, shared-file coordination and a late integration lane. This schedule uses two agents, explicit test/product separation and exclusive file ownership, with integration after each small slice and exact-main checks. Preserve the old plan as history.

## 4.6 Standardize documentation — first package (#472)

Keep a single active navigation path: `README.md` and `docs/index.md`; `docs/DECISIONS.md` as the final decisions; `docs/CAPABILITY_UNION_INVENTORY.md` plus authoritative `provenance/capability-matrix.yml`; `docs/CURRENT_PROGRESS.md` as one concise issue-keyed table (issue, intended check IDs, current main SHA, exact artifact links, result/status and outstanding obligations); `docs/architecture.md`, ADRs 0001–0004, `docs/api_reference.md`, `docs/cli_reference.md`, `docs/user_guide.md`, `docs/migration_guide.md`, `docs/contributing.md`, and `docs/BNG3_UNITS.md`; `docs/design/semantic-equal-design.md` and `docs/design/sbml-packages.md`; and `docs/PLAN.md` for this work plan. Align each active document with final decisions once, then maintain it at the owning interface. `CURRENT_PROGRESS.md:8-48,87-99,957-965` shows why dated narrative and candidate evidence should not be treated as live status.

Move dated reports and obsolete plans to `docs/archive/`, preserving content, evidence, history and links; place a short header in each moved document saying it is historical and pointing to its replacement. In particular review `CONVERGENCE_CONTINUATION_2026-09-14.md`, `OFFLINE_CONVERGENCE_PASS_2026-09-17.md`, `REPOSITORY_AUDIT_2026-10-07.md`, `SBML_CONVERGENCE_STATUS_2026-09-16.md`, `SBML_FEATURE_INVENTORY_2026-09-16.md`, `UPSTREAM_RECONCILIATION_2026-09-23.md` and dated `docs/architecture_handoffs/` for archival; preserve specialized operational references such as `CI_PARITY.md` and `VALIDATION_EVIDENCE.md` as active if still used, otherwise move with a replacement link. Resolve inbound links and generated references. Retain every record rather than delete it. The plan PR itself installs both design files and corrects decision item 2 to `provenance/upstreams.lock.yml` and item 6 to `docs/design/semantic-equal-design.md`. #472 then implements `release-docs-links` and `release-docs-decisions` through a separately owned acceptance package. The Luna concurrency limit is decided in section 4.5. This package goes first; #137/#179 remain actual closure dependencies, not prerequisites for beginning documentation cleanup.


### Issue-body corrections for the maintainer

- #471: replace the held-out-case and code-owner-approval language with the public-test and base-revision checks in section 4.2.
- #472: replace the hard-coded Luna limit with the concurrency decision in section 4.5.
- #157 and #158: when applying the planned merge, transfer every check and dependency to #157.
- #178 and #470: when applying the planned merge, transfer every check and dependency to #178.

## 4.7 Public API conventions
Use snake_case for functions and methods and PascalCase for classes. `BioNetGenModel` is the explicit model object; simulations and analyses return separate result objects. `set_parameter` mutates (`python/bionetgen/model.py:121`); document mutation and provide explicit copies. Model methods operate on model state; module functions perform analysis. Computation and plotting are separate, with plotting functions in a `pl` namespace. Select optional backends explicitly and report unavailable features. The current top-level `run` changes return type based on arguments (`python/bionetgen/__init__.py:34`); introduce separate simulation and file-output entry points.
[Scanpy usage principles](https://scanpy.readthedocs.io/en/latest/usage-principles.html) describe a central object and separate tools and plots. [PySB’s tutorial](https://pysb.readthedocs.io/en/stable/tutorial.html) uses implicit self-export and wildcard imports; avoid implicit namespace mutation and make ownership explicit. Its [simulator API](https://pysb.readthedocs.io/en/stable/modules/simulator.html) uses different simulator classes and backend-specific options; provide one capability-aware selection and consistent results. These are design tradeoffs.
Migration inventory below lists every `py.*` inventory row. “Candidate” means the same symbol exists at the listed BNG3 path, not that semantic equivalence has been established; “implement” means no same-named definition was found at that candidate path. Package #171 must verify each against pinned PyBioNetGen behavior, establish a stable new API name, and run `release-python-api`; never treat this static table as evidence of equivalence. CLI entries describe commands or arguments rather than Python functions.
| PyBioNetGen inventory ID | BNG3 candidate or required work |
|---|---|
| `py.core.defaults.get_latest_bng_version` | candidate; verify behavior: `python/bionetgen/core/defaults.py:16` |
| `py.core.defaults.BNGDefaults` | candidate; verify behavior: `python/bionetgen/core/defaults.py:50` |
| `py.core.exc.BNGError` | candidate; verify behavior: `python/bionetgen/core/exc.py:1` |
| `py.core.exc.BNGVersionError` | candidate; verify behavior: `python/bionetgen/core/exc.py:7` |
| `py.core.exc.BNGPerlError` | candidate; verify behavior: `python/bionetgen/core/exc.py:17` |
| `py.core.exc.BNGParseError` | candidate; verify behavior: `python/bionetgen/core/exc.py:27` |
| `py.core.exc.BNGFileError` | candidate; verify behavior: `python/bionetgen/core/exc.py:41` |
| `py.core.exc.BNGModelError` | candidate; verify behavior: `python/bionetgen/core/exc.py:50` |
| `py.core.exc.BNGRunError` | candidate; verify behavior: `python/bionetgen/core/exc.py:62` |
| `py.core.exc.BNGCompileError` | candidate; verify behavior: `python/bionetgen/core/exc.py:85` |
| `py.core.exc.BNGFormatError` | implement equivalent: `python/bionetgen/core/exc.py` |
| `py.core.exc.BNGSimError` | implement equivalent: `python/bionetgen/core/exc.py` |
| `py.core.exc.BNGSimulatorError` | candidate; verify behavior: `python/bionetgen/core/exc.py:98` |
| `py.core.main.runCLI` | candidate; verify behavior: `python/bionetgen/core/main.py:10` |
| `py.core.main.plotDAT` | candidate; verify behavior: `python/bionetgen/core/main.py:42` |
| `py.core.main.runAtomizeTool` | candidate; verify behavior: `python/bionetgen/core/main.py:93` |
| `py.core.main.printInfo` | candidate; verify behavior: `python/bionetgen/core/main.py:138` |
| `py.core.main.visualizeModel` | candidate; verify behavior: `python/bionetgen/core/main.py:152` |
| `py.core.main.graphDiff` | candidate; verify behavior: `python/bionetgen/core/main.py:174` |
| `py.core.main.generate_notebook` | candidate; verify behavior: `python/bionetgen/core/main.py:196` |
| `py.core.notebook.BNGNotebook` | candidate; verify behavior: `python/bionetgen/core/notebook.py:4` |
| `py.core.notebook.BNGNotebook.write` | candidate; verify behavior: `python/bionetgen/core/notebook.py:33` |
| `py.core.tools.bngsim_backend_helper.BackendHelperJob` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_backend_helper.load_backend_job` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_backend_helper.direct_job_from_backend_job` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_backend_helper.execute_backend_payload` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_backend_helper.serve` | implement equivalent: `cpp/io/SscWriter.hpp:30; cpp/engine/HybridModelGenerator.cpp:220` |
| `py.core.tools.bngsim_backend_helper.main` | implement equivalent: `cpp/nfsim/NFsim.cpp:123; cpp/nfsim/NFinput/parseSymRxns.cpp:305` |
| `py.core.tools.bngsim_bridge.is_bngsim_available` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.get_bngsim_unavailable_reason` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.BngsimRouteDecision` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.BngsimDirectJob` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.detect_input_format` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.execute_bngsim_direct_job` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.run_nfsim` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.run_with_bngsim` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.classify_bngsim_route` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.run_bngl_with_bngsim_backend_hook` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_bridge.run_bngl_with_bngsim` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_parameter_scan.ScanRequest` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_parameter_scan.detect_inprocess_scan` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_parameter_scan.scan_values` | implement equivalent: `python/bionetgen/scan.py:454` |
| `py.core.tools.bngsim_parameter_scan.run_inprocess_scan` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_parameter_scan.run_parameter_scan_with_bngsim` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.bngsim_parameter_scan.run_bifurcate_with_bngsim` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.core.tools.cli.BNGCLI` | candidate; verify behavior: `python/bionetgen/core/tools/cli.py:6` |
| `py.core.tools.cli.BNGCLI.run` | candidate; verify behavior: `python/bionetgen/core/tools/cli.py:97` |
| `py.core.tools.gdiff.BNGGdiff` | candidate; verify behavior: `python/bionetgen/core/tools/gdiff.py:6` |
| `py.core.tools.gdiff.BNGGdiff.diff_graphs` | candidate; verify behavior: `python/bionetgen/core/tools/gdiff.py:86` |
| `py.core.tools.gdiff.BNGGdiff.run` | candidate; verify behavior: `python/bionetgen/core/tools/gdiff.py:684` |
| `py.core.tools.info.BNGInfo` | candidate; verify behavior: `python/bionetgen/core/tools/info.py:4` |
| `py.core.tools.info.BNGInfo.gatherInfo` | candidate; verify behavior: `python/bionetgen/core/tools/info.py:22` |
| `py.core.tools.info.BNGInfo.messageGeneration` | candidate; verify behavior: `python/bionetgen/core/tools/info.py:101` |
| `py.core.tools.info.BNGInfo.run` | candidate; verify behavior: `python/bionetgen/core/tools/info.py:123` |
| `py.core.tools.plot.BNGPlotter` | candidate; verify behavior: `python/bionetgen/core/tools/plot.py:6` |
| `py.core.tools.plot.BNGPlotter.plot` | candidate; verify behavior: `python/bionetgen/core/tools/plot.py:46` |
| `py.core.tools.result.BNGResult` | candidate; verify behavior: `python/bionetgen/core/tools/result.py:7` |
| `py.core.tools.result.BNGResult.load` | candidate; verify behavior: `python/bionetgen/core/tools/result.py:87` |
| `py.core.tools.result.BNGResult.find_dat_files` | candidate; verify behavior: `python/bionetgen/core/tools/result.py:105` |
| `py.core.tools.result.BNGResult.load_results` | candidate; verify behavior: `python/bionetgen/core/tools/result.py:129` |
| `py.core.tools.visualize.VisResult` | candidate; verify behavior: `python/bionetgen/core/tools/visualize.py:7` |
| `py.core.tools.visualize.BNGVisualize` | candidate; verify behavior: `python/bionetgen/core/tools/visualize.py:67` |
| `py.core.tools.visualize.BNGVisualize.run` | candidate; verify behavior: `python/bionetgen/core/tools/visualize.py:134` |
| `py.core.utils.logging.BNGLogger` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:22` |
| `py.core.utils.logging.BNGLogger.get_logger` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:89` |
| `py.core.utils.logging.BNGLogger.debug` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:114` |
| `py.core.utils.logging.BNGLogger.info` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:128` |
| `py.core.utils.logging.BNGLogger.warning` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:142` |
| `py.core.utils.logging.BNGLogger.error` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:156` |
| `py.core.utils.logging.BNGLogger.critical` | candidate; verify behavior: `python/bionetgen/core/utils/logging.py:170` |
| `py.core.utils.utils.ActionList` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:8` |
| `py.core.utils.utils.ActionList.is_before_model` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:486` |
| `py.core.utils.utils.ActionList.validate_action` | implement equivalent: `python/bionetgen/core/utils/utils.py` |
| `py.core.utils.utils.ActionList.define_parser` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:491` |
| `py.core.utils.utils.find_BNG_path` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:567` |
| `py.core.utils.utils.test_perl` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:629` |
| `py.core.utils.utils.test_bngexec` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:652` |
| `py.core.utils.utils.run_command` | candidate; verify behavior: `python/bionetgen/core/utils/utils.py:671` |
| `py.core.version.get_version` | candidate; verify behavior: `python/bionetgen/core/version.py:26` |
| `py.main.versionAction` | candidate; verify behavior: `python/bionetgen/main.py:58` |
| `py.main.requireAction` | candidate; verify behavior: `python/bionetgen/main.py:104` |
| `py.main.BNGBase` | candidate; verify behavior: `python/bionetgen/main.py:124` |
| `py.main.BNGBase.run` | candidate; verify behavior: `python/bionetgen/main.py:211` |
| `py.main.BNGBase.notebook` | candidate; verify behavior: `python/bionetgen/main.py:253` |
| `py.main.BNGBase.plot` | candidate; verify behavior: `python/bionetgen/main.py:342` |
| `py.main.BNGBase.info` | candidate; verify behavior: `python/bionetgen/main.py:369` |
| `py.main.BNGBase.visualize` | candidate; verify behavior: `python/bionetgen/main.py:410` |
| `py.main.BNGBase.graphdiff` | candidate; verify behavior: `python/bionetgen/main.py:484` |
| `py.main.BNGBase.atomize` | candidate; verify behavior: `python/bionetgen/main.py:643` |
| `py.main.BioNetGen` | candidate; verify behavior: `python/bionetgen/main.py:647` |
| `py.main.BioNetGenTest` | candidate; verify behavior: `python/bionetgen/main.py:707` |
| `py.main.get_default_app` | implement equivalent: `python/bionetgen/main.py` |
| `py.main.get_conf` | implement equivalent: `python/bionetgen/main.py` |
| `py.main.get_default_bng_path` | implement equivalent: `python/bionetgen/main.py` |
| `py.main.main` | candidate; verify behavior: `python/bionetgen/main.py:717` |
| `py.modelapi.blocks.ModelBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:20` |
| `py.modelapi.blocks.ModelBlock.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:119` |
| `py.modelapi.blocks.ModelBlock.reset_compilation_tags` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:139` |
| `py.modelapi.blocks.ModelBlock.add_item` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:151` |
| `py.modelapi.blocks.ModelBlock.add_items` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:188` |
| `py.modelapi.blocks.ParameterBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:196` |
| `py.modelapi.blocks.ParameterBlock.add_item` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:151` |
| `py.modelapi.blocks.ParameterBlock.add_parameter` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:248` |
| `py.modelapi.blocks.CompartmentBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:253` |
| `py.modelapi.blocks.CompartmentBlock.add_compartment` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:299` |
| `py.modelapi.blocks.ObservableBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:304` |
| `py.modelapi.blocks.ObservableBlock.add_observable` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:344` |
| `py.modelapi.blocks.SpeciesBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:349` |
| `py.modelapi.blocks.SpeciesBlock.add_species` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:395` |
| `py.modelapi.blocks.MoleculeTypeBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:401` |
| `py.modelapi.blocks.MoleculeTypeBlock.add_molecule_type` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:441` |
| `py.modelapi.blocks.FunctionBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:446` |
| `py.modelapi.blocks.FunctionBlock.add_function` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:486` |
| `py.modelapi.blocks.RuleBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:491` |
| `py.modelapi.blocks.RuleBlock.add_rule` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:536` |
| `py.modelapi.blocks.RuleBlock.consolidate_rules` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:540` |
| `py.modelapi.blocks.ActionBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:569` |
| `py.modelapi.blocks.ActionBlock.add_item` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:151` |
| `py.modelapi.blocks.ActionBlock.add_action` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:635` |
| `py.modelapi.blocks.ActionBlock.clear_actions` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:648` |
| `py.modelapi.blocks.ActionBlock.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:119` |
| `py.modelapi.blocks.ProtocolBlock` | implement equivalent: `python/bionetgen/modelapi/blocks.py` |
| `py.modelapi.blocks.ProtocolBlock.add_item` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:151` |
| `py.modelapi.blocks.ProtocolBlock.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:119` |
| `py.modelapi.blocks.EnergyPatternBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:660` |
| `py.modelapi.blocks.EnergyPatternBlock.add_energy_pattern` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:700` |
| `py.modelapi.blocks.PopulationMapBlock` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:705` |
| `py.modelapi.blocks.PopulationMapBlock.add_population_map` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:745` |
| `py.modelapi.bngfile.BNGFile` | candidate; verify behavior: `python/bionetgen/modelapi/bngfile.py:17` |
| `py.modelapi.bngfile.BNGFile.generate_xml` | candidate; verify behavior: `python/bionetgen/modelapi/bngfile.py:58` |
| `py.modelapi.bngfile.BNGFile.strip_actions` | candidate; verify behavior: `python/bionetgen/modelapi/bngfile.py:167` |
| `py.modelapi.bngfile.BNGFile.write_xml` | candidate; verify behavior: `python/bionetgen/modelapi/bngfile.py:227` |
| `py.modelapi.bngparser.BNGParser` | candidate; verify behavior: `python/bionetgen/modelapi/bngparser.py:21` |
| `py.modelapi.bngparser.BNGParser.parse_model` | candidate; verify behavior: `python/bionetgen/modelapi/bngparser.py:59` |
| `py.modelapi.bngparser.BNGParser.parse_actions` | candidate; verify behavior: `python/bionetgen/modelapi/bngparser.py:105` |
| `py.modelapi.bngparser.BNGParser.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/bngparser.py:252` |
| `py.modelapi.model.bngmodel` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:29` |
| `py.modelapi.model.bngmodel.recompile` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:117` |
| `py.modelapi.model.bngmodel.changes` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:125` |
| `py.modelapi.model.bngmodel.add_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:174` |
| `py.modelapi.model.bngmodel.add_empty_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:190` |
| `py.modelapi.model.bngmodel.add_parameters_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:206` |
| `py.modelapi.model.bngmodel.add_compartments_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:228` |
| `py.modelapi.model.bngmodel.add_molecule_types_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:252` |
| `py.modelapi.model.bngmodel.add_species_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:276` |
| `py.modelapi.model.bngmodel.add_observables_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:298` |
| `py.modelapi.model.bngmodel.add_functions_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:320` |
| `py.modelapi.model.bngmodel.add_rules_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:342` |
| `py.modelapi.model.bngmodel.add_energy_patterns_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:364` |
| `py.modelapi.model.bngmodel.add_population_maps_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:388` |
| `py.modelapi.model.bngmodel.add_protocol_block` | implement equivalent: `python/bionetgen/modelapi/model.py` |
| `py.modelapi.model.bngmodel.add_actions_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:412` |
| `py.modelapi.model.bngmodel.reset_compilation_tags` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:434` |
| `py.modelapi.model.bngmodel.add_action` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:412` |
| `py.modelapi.model.bngmodel.write_model` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:469` |
| `py.modelapi.model.bngmodel.setup_simulator` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:476` |
| `py.modelapi.model.bngmodel.export_sympy_odes` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:529` |
| `py.modelapi.pattern.Pattern` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:7` |
| `py.modelapi.pattern.Pattern.canonicalize` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:77` |
| `py.modelapi.pattern.Pattern.print_canonical` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:226` |
| `py.modelapi.pattern.Pattern.compartment` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:319` |
| `py.modelapi.pattern.Pattern.consolidate_molecule_compartments` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:329` |
| `py.modelapi.pattern.Pattern.label` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:339` |
| `py.modelapi.pattern.Molecule` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:387` |
| `py.modelapi.pattern.Molecule.print_canonical` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:226` |
| `py.modelapi.pattern.Molecule.name` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:525` |
| `py.modelapi.pattern.Molecule.components` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:535` |
| `py.modelapi.pattern.Molecule.compartment` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:319` |
| `py.modelapi.pattern.Molecule.label` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:339` |
| `py.modelapi.pattern.Molecule.add_component` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:571` |
| `py.modelapi.pattern.Component` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:577` |
| `py.modelapi.pattern.Component.print_canonical` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:226` |
| `py.modelapi.pattern.Component.name` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:525` |
| `py.modelapi.pattern.Component.label` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:339` |
| `py.modelapi.pattern.Component.state` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:713` |
| `py.modelapi.pattern.Component.states` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:723` |
| `py.modelapi.pattern.Component.bonds` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:733` |
| `py.modelapi.pattern.Component.add_state` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:745` |
| `py.modelapi.pattern.Component.add_bond` | candidate; verify behavior: `python/bionetgen/modelapi/pattern.py:751` |
| `py.modelapi.pattern_reader.BNGParsers` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:6` |
| `py.modelapi.pattern_reader.BNGPatternReader` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:15` |
| `py.modelapi.pattern_reader.BNGPatternReader.define_parsers` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:63` |
| `py.modelapi.pattern_reader.BNGPatternReader.define_component_parser` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:68` |
| `py.modelapi.pattern_reader.BNGPatternReader.define_molecule_parser` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:99` |
| `py.modelapi.pattern_reader.BNGPatternReader.define_pattern_parser` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:141` |
| `py.modelapi.pattern_reader.BNGPatternReader.make_pattern` | candidate; verify behavior: `python/bionetgen/modelapi/pattern_reader.py:181` |
| `py.modelapi.rulemod.RuleMod` | candidate; verify behavior: `python/bionetgen/modelapi/rulemod.py:1` |
| `py.modelapi.rulemod.RuleMod.add_modifier` | implement equivalent: `python/bionetgen/modelapi/rulemod.py` |
| `py.modelapi.rulemod.RuleMod.type` | candidate; verify behavior: `python/bionetgen/modelapi/rulemod.py:21` |
| `py.modelapi.runner.run` | candidate; verify behavior: `python/bionetgen/modelapi/runner.py:29` |
| `py.modelapi.structs.ModelObj` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:7` |
| `py.modelapi.structs.ModelObj.comment` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:51` |
| `py.modelapi.structs.ModelObj.line_label` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:63` |
| `py.modelapi.structs.ModelObj.print_line` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:75` |
| `py.modelapi.structs.Parameter` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:87` |
| `py.modelapi.structs.Parameter.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Compartment` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:114` |
| `py.modelapi.structs.Compartment.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Observable` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:151` |
| `py.modelapi.structs.Observable.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Observable.add_pattern` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:193` |
| `py.modelapi.structs.MoleculeType` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:200` |
| `py.modelapi.structs.MoleculeType.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Species` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:226` |
| `py.modelapi.structs.Species.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Function` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:254` |
| `py.modelapi.structs.Function.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Action` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:290` |
| `py.modelapi.structs.Action.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Action.print_line` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:75` |
| `py.modelapi.structs.Rule` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:385` |
| `py.modelapi.structs.Rule.set_rate_constants` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:433` |
| `py.modelapi.structs.Rule.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.Rule.side_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:462` |
| `py.modelapi.structs.EnergyPattern` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:466` |
| `py.modelapi.structs.EnergyPattern.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.structs.PopulationMap` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:494` |
| `py.modelapi.structs.PopulationMap.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:110` |
| `py.modelapi.sympy_odes.SympyOdes` | candidate; verify behavior: `python/bionetgen/modelapi/sympy_odes.py:16` |
| `py.modelapi.sympy_odes.export_sympy_odes` | candidate; verify behavior: `python/bionetgen/modelapi/sympy_odes.py:82` |
| `py.modelapi.sympy_odes.extract_odes_from_mexfile` | candidate; verify behavior: `python/bionetgen/modelapi/sympy_odes.py:148` |
| `py.modelapi.xmlparsers.XMLObj` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:12` |
| `py.modelapi.xmlparsers.XMLObj.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:52` |
| `py.modelapi.xmlparsers.XMLObj.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.XMLObj.resolve_ratelaw` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:595` |
| `py.modelapi.xmlparsers.BondsXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:62` |
| `py.modelapi.xmlparsers.BondsXML.set_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:72` |
| `py.modelapi.xmlparsers.BondsXML.get_bond_id` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:75` |
| `py.modelapi.xmlparsers.BondsXML.get_tpl_from_id` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:91` |
| `py.modelapi.xmlparsers.BondsXML.tpls_from_bond` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:98` |
| `py.modelapi.xmlparsers.BondsXML.resolve_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:107` |
| `py.modelapi.xmlparsers.PatternXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:129` |
| `py.modelapi.xmlparsers.PatternXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.PatternListXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:257` |
| `py.modelapi.xmlparsers.PatternListXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.ParameterBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:285` |
| `py.modelapi.xmlparsers.ParameterBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.CompartmentBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:320` |
| `py.modelapi.xmlparsers.CompartmentBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.ObservableBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:355` |
| `py.modelapi.xmlparsers.ObservableBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.SpeciesBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:384` |
| `py.modelapi.xmlparsers.SpeciesBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.MoleculeTypeBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:411` |
| `py.modelapi.xmlparsers.MoleculeTypeBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.MoleculeTypeBlockXML.add_molecule_type_to_block` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:437` |
| `py.modelapi.xmlparsers.FunctionBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:471` |
| `py.modelapi.xmlparsers.FunctionBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.FunctionBlockXML.get_arguments` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:513` |
| `py.modelapi.xmlparsers.RuleBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:523` |
| `py.modelapi.xmlparsers.RuleBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.RuleBlockXML.resolve_ratelaw` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:595` |
| `py.modelapi.xmlparsers.RuleBlockXML.resolve_rxn_side` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:623` |
| `py.modelapi.xmlparsers.RuleBlockXML.get_operations` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:660` |
| `py.modelapi.xmlparsers.RuleBlockXML.get_rule_mod` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:693` |
| `py.modelapi.xmlparsers.EnergyPatternBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:762` |
| `py.modelapi.xmlparsers.EnergyPatternBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.PopulationMapBlockXML` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:795` |
| `py.modelapi.xmlparsers.PopulationMapBlockXML.parse_xml` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:55` |
| `py.modelapi.xmlparsers.PopulationMapBlockXML.resolve_ratelaw` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:595` |
| `py.modelapi.xmlparsers.Operation` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:874` |
| `py.network.blocks.NetworkBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkBlock.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.blocks.NetworkBlock.add_item` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:49` |
| `py.network.blocks.NetworkBlock.add_items` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:52` |
| `py.network.blocks.NetworkParameterBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkParameterBlock.add_item` | candidate; verify behavior: `python/bionetgen/modelapi/blocks.py:49` |
| `py.network.blocks.NetworkParameterBlock.add_parameter` | implement equivalent: `cpp/engine/BngsimAdapter.cpp:501; python/bionetgen/modelapi/xmlparsers.py:306` |
| `py.network.blocks.NetworkCompartmentBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkCompartmentBlock.add_compartment` | implement equivalent: `python/bionetgen/modelapi/xmlparsers.py:340; python/bionetgen/modelapi/blocks.py:259` |
| `py.network.blocks.NetworkGroupBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkGroupBlock.add_group` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkSpeciesBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkSpeciesBlock.add_species` | implement equivalent: `cpp/engine/BngsimAdapter.cpp:505; python/bionetgen/modelapi/xmlparsers.py:401` |
| `py.network.blocks.NetworkFunctionBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkFunctionBlock.add_function` | implement equivalent: `cpp/engine/BngsimAdapter.cpp:522; python/bionetgen/modelapi/xmlparsers.py:501` |
| `py.network.blocks.NetworkReactionBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkReactionBlock.add_reaction` | implement equivalent: `cpp/engine/BngsimAdapter.cpp:543` |
| `py.network.blocks.NetworkEnergyPatternBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkEnergyPatternBlock.add_energy_pattern` | implement equivalent: `python/bionetgen/modelapi/xmlparsers.py:782; python/bionetgen/modelapi/blocks.py:666` |
| `py.network.blocks.NetworkPopulationMapBlock` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.blocks.NetworkPopulationMapBlock.add_population_map` | implement equivalent: `python/bionetgen/modelapi/xmlparsers.py:826; python/bionetgen/modelapi/blocks.py:711` |
| `py.network.network.Network` | implement equivalent: `cpp/nfsim/NFsim.cpp:3; cpp/io/SbmlWriter.cpp:177` |
| `py.network.network.Network.add_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:68; python/bionetgen/modelapi/bngparser.py:250` |
| `py.network.network.Network.add_empty_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:70` |
| `py.network.network.Network.add_parameters_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:206` |
| `py.network.network.Network.add_species_block` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:276` |
| `py.network.network.Network.add_groups_block` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.network.Network.add_reactions_block` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.network.Network.write_model` | candidate; verify behavior: `python/bionetgen/modelapi/model.py:63` |
| `py.network.networkparser.BNGNetworkParser` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.networkparser.BNGNetworkParser.parse_network` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkObj` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkObj.comment` | implement equivalent: `cpp/parser/ThermoSourceNormalization.cpp:28; cpp/parser/BNGAstVisitor.cpp:106` |
| `py.network.structs.NetworkObj.line_label` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:15` |
| `py.network.structs.NetworkObj.print_line` | candidate; verify behavior: `python/bionetgen/modelapi/structs.py:20; python/bionetgen/modelapi/blocks.py:130` |
| `py.network.structs.NetworkParameter` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkParameter.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkCompartment` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkCompartment.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkGroup` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkGroup.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkSpecies` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkSpecies.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkFunction` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkFunction.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkReaction` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkReaction.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkEnergyPattern` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkEnergyPattern.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.network.structs.NetworkPopulationMap` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.network.structs.NetworkPopulationMap.gen_string` | candidate; verify behavior: `python/bionetgen/modelapi/xmlparsers.py:37; python/bionetgen/modelapi/structs.py:23` |
| `py.simulator.bngsimulator.BNGSimulator` | candidate; verify behavior: `python/bionetgen/simulator/bngsimulator.py:1` |
| `py.simulator.bngsimulator.BNGSimulator.model_file` | candidate; verify behavior: `python/bionetgen/simulator/bngsimulator.py:43` |
| `py.simulator.bngsimulator.BNGSimulator.model_str` | candidate; verify behavior: `python/bionetgen/simulator/bngsimulator.py:56` |
| `py.simulator.bngsimulator.BNGSimulator.simulate` | candidate; verify behavior: `python/bionetgen/simulator/bngsimulator.py:68` |
| `py.simulator.csimulator.RESULT` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.simulator.csimulator.CSimWrapper` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.simulator.csimulator.CSimWrapper.set_species_init` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.simulator.csimulator.CSimWrapper.set_parameters` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.simulator.csimulator.CSimWrapper.simulate` | implement equivalent: `cpp/parser/generated/BNGParser.cpp:95; cpp/parser/generated/BNGLexer.cpp:123` |
| `py.simulator.csimulator.CSimulator` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.simulator.csimulator.CSimulator.compile_shared_lib` | implement equivalent: `python/bionetgen/model.py (new equivalent required)` |
| `py.simulator.csimulator.CSimulator.simulator` | implement equivalent: `cpp/nfsim/NFsim.cpp:23; cpp/nfsim/NFcore/reactionSelector/logClassSelector.cpp:191` |
| `py.simulator.csimulator.CSimulator.simulate` | implement equivalent: `cpp/parser/generated/BNGParser.cpp:95; cpp/parser/generated/BNGLexer.cpp:123` |
| `py.simulator.librrsimulator.libRRSimulator` | candidate; verify behavior: `python/bionetgen/simulator/librrsimulator.py:4` |
| `py.simulator.librrsimulator.libRRSimulator.simulator` | candidate; verify behavior: `python/bionetgen/simulator/librrsimulator.py:30` |
| `py.simulator.librrsimulator.libRRSimulator.sbml` | candidate; verify behavior: `python/bionetgen/simulator/librrsimulator.py:52` |
| `py.simulator.librrsimulator.libRRSimulator.simulate` | candidate; verify behavior: `python/bionetgen/simulator/librrsimulator.py:66` |
| `py.simulator.simulators.sim_getter` | candidate; verify behavior: `python/bionetgen/simulator/simulators.py:4` |
| `py.cli.run` | candidate; verify behavior: `python/bionetgen/cli.py:run` |
| `py.cli.notebook` | candidate; verify behavior: `python/bionetgen/cli.py:notebook` |
| `py.cli.plot` | candidate; verify behavior: `python/bionetgen/cli.py:plot` |
| `py.cli.info` | candidate; verify behavior: `python/bionetgen/cli.py:info` |
| `py.cli.visualize` | candidate; verify behavior: `python/bionetgen/cli.py:visualize` |
| `py.cli.graphdiff` | candidate; verify behavior: `python/bionetgen/cli.py:graphdiff` |
| `py.cli.atomize` | candidate; verify behavior: `python/bionetgen/cli.py:atomize` |
| `py.cli.option.annotation` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.atomize` | candidate; verify behavior: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.colors` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.convention-file` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.convert-units` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.detail` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.format` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.ignore` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.input` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.input2` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.isomorphism-check` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.keep-local-parameters` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.legend` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.log` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.log-level` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.memoized-resolver` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.method` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.mode` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.molecule-id` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.naming-conventions` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.no-bngsim` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.obs-map-file` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.open` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.output` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.output2` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.pathwaycommons` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.quiet-mode` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.require` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.sedml` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.timeout` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.title` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.traceback-depth` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.type` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.user-structures` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.version` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.write-sct-graphs` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.write-scts` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.xlabel` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.xmax` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.xmin` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.ylabel` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.ymax` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.cli.option.ymin` | implement equivalent: `python/bionetgen/cli.py (map accepted command/option behavior)` |
| `py.atomizer.AtomizeTool` | candidate; verify behavior: `python/bionetgen/atomizer/atomizeTool.py` |
| `py.atomizer.AtomizeTool.checkConfig` | candidate; verify behavior: `python/bionetgen/atomizer/atomizeTool.py` |
| `py.atomizer.AtomizeTool.run` | candidate; verify behavior: `python/bionetgen/atomizer/atomizeTool.py` |
