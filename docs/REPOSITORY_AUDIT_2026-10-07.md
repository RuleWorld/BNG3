# BNG3 repository audit and outstanding work — 2026-10-07

BNG3 already combines the main codebases and has a substantial native C++ implementation. It has not yet completed the semantic consolidation, capability union, independent qualification, or formal refinement required to call that integration finished. The best next step is to finish and qualify the shared semantic boundary, rather than start another wholesale rewrite.

**Audit basis.** `RuleWorld/BNG3`, fetched main `e1836c3274e685996d5e86883761e00e98257e09`. The chat's initial directory was the legacy `bionetgen` repository; the requested architecture and checklist belong to `/Users/akutuva/Documents/BioNetGen/BNG3`. Ran `git pull --ff-only` there: its clean `fix/bng3-xml-parser-report` branch was already up to date at `3b6c61d499d7d09499bb56f3960587a5f5fed53b`; the fetch advanced `origin/main` from `744073ea` to `e1836c32`. Main was inspected from an isolated archive at `/private/tmp/bng3-audit-20261007`. The PR branch was not switched, merged, or reset. This report is the only added repository file.

This is a broad source, documentation, test-selection, and live GitHub audit, with bounded local checks. It is not an exhaustive correctness proof or a fresh run of every scientific corpus. “Outstanding” below includes demonstrated gaps, unfinished accepted designs, release qualification, and explicitly labeled engineering recommendations. An unsupported feature is not automatically a bug; retaining its rejection may be the correct maintained product scope.

**Verified state at the 2026-10-07 audit baseline.**

This historical snapshot predates the issue backlog and subsequent integrations.
Use the [issue-linked checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) and
[current progress](CURRENT_PROGRESS.md) for current disposition and evidence.

| Check | Result and boundary |
| --- | --- |
| Main exact-head GitHub checks | **46 success, 2 skipped, 0 failing/nonterminal**, all 48 check runs read with `per_page=100`. Includes native/Python platform matrices, ASan, CodeQL, wheels, sdist smoke, configured BNG2/NFsim/API parity, and Lean. Skips: Publish to PyPI and scheduled historical NFsim validation. [CI run](https://github.com/RuleWorld/BNG3/actions/runs/37548838421), [parity run](https://github.com/RuleWorld/BNG3/actions/runs/37548838423), [Lean run](https://github.com/RuleWorld/BNG3/actions/runs/37548838419). |
| Open GitHub work | Two PRs: [#130](https://github.com/RuleWorld/BNG3/pull/130), and draft [#128](https://github.com/RuleWorld/BNG3/pull/128). No open issues returned. This does not mean the backlog is empty. |
| PR #130, exact head `3b6c61d4` | Four failing checks: independent BNG2 networks and all three full-corpus platform jobs. All fail on `test_assignment`: generated rate `0.0` versus reference `if((0==1),1,if((0>0),2,if((0>0),3,0)))`. Other network counts match. This is a confirmed comparison failure, **not yet a demonstrated dynamic-semantic defect**; the displayed constant expressions evaluate equally. Full-corpus jobs report 70 pass / 1 fail / 0 error / 0 skip. [Parity failure](https://github.com/RuleWorld/BNG3/actions/runs/37532097603), [validation failure](https://github.com/RuleWorld/BNG3/actions/runs/37532097407). |
| PR #128, exact head `d5f6ad90` | Reported checks successful except conditional skips; still draft. Optimization and grammar/equality changes require review, not automatic acceptance from CI. |
| Local architecture dependency ratchet | PASS, **43 explicit AST compatibility files**. The check is registered in CTest and Python tests. |
| Local strict provenance | FAIL, **14 errors**: baseline approval; nine accepted source cutoffs; two locked oracles; compiler-image lock; Python lock. Ordinary non-strict CI does not enforce these approvals. |
| Local corpus validation | PASS, 106 models; generated selection manifest current. Tier sizes: S=10, P=106, NF=4, expression=5, X=0, B=0. The 71-model validation workflow is a separate selected gate. |
| Local Lean static/header checks | PASS, 37 Lean files; header contract PASS. These are not kernel builds. |
| Local actual C++ NFnext contract | PASS, **18/18**. This compiled and executed the native contract in the audited snapshot. |
| Lean kernel build | Exact-head hosted workflow passed; not rerun locally. Local installed toolchain inventory lacked the pinned 4.33.1. `native_decide` fixtures remain distinct from kernel-reduced general theorems. |
| Local JAX ODE defect reproduction | Extracted the unchanged `_extract_rate_laws` function with Python AST and supplied a minimal `cpp` test double: **`NameError: name 'network' is not defined`**. This proves the helper's undefined variable, not end-to-end JAX behavior. |
| Other local validation | Full native/Python/oracle suites were not rerun. The system Python lacked pytest, so the exception-ledger CLI could not run; its JSON was inspected and contains zero exceptions. No full SSTS or BioModels run was started. |

**What is already implemented, and should not be re-added.**

- C++ BNGL parsing, network generation, native ODE/SSA/PLA/PSA, embedded NFsim, pybind11, Python model/results APIs, CLI, scans, local sensitivities, builders, and multiple exporters.
- A substantially richer `CompiledModel`: typed symbols, declarations, seeds, observables, functions, energy/barrier factors, population types/maps; typed mutation endpoints and separately compiled forward/reverse directions.
- Typed pattern constraints and a `CompiledModel -> NFIR` lowering for a restricted supported subset; a dependency ratchet prevents new unapproved parser/AST dependencies.
- One bundled nauty build and removal of the NFsim ExprTk dependency. Shared build dependency does not imply one graph-identity semantic implementation.
- Direct NFsim initialization is the default; XML fallback requires explicit opt-in. It is incorrect to list default XML-bridge removal as entirely unstarted.
- BNGIR 0.1/0.2, structured snapshots, feature/refusal validation, schema and round-trip tests. Native structural deserialization remains missing.
- Modern Atomizer, substantial exact analytic event lowering, SBML Core/Multi handling, units, energy extensions, Metal/CUDA batch-SSA infrastructure, and optional BNGsim/JAX work.
- Lean semantic definitions, reference interpreters, scoped lowering equalities, smoke/coverage execution, axiom auditing, native NFnext contract tests, and CI.
- Official SBML-suite revision locking and official-reference comparison code now exist in `scripts/ci/validate_sbml_test_suite.py`; the older checklist claim that neither exists is stale. That does not establish a current aggregate conformance result.

**Priority and effort.** P0 = immediate correctness/integration triage; P1 = core convergence; P2 = broader qualification/maintainability; P3 = optional expansion. Type D = demonstrated defect/failure, I = implementation gap, Q = qualification gap, R = refactoring recommendation, M = maintainer/product decision. Effort S ≈ up to 2 engineering days, M ≈ 3–10 days, L ≈ 2–6 weeks, XL = multi-milestone work. These are planning ranges, not measured estimates; scientific qualification can dominate implementation time.

**1. Immediate triage and a usable source of truth.**

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| A01 | P0 D/M | Resolve PR #130's `test_assignment` parity failures. Determine whether the change is safe constant folding, inappropriate freezing of live expressions, or comparator normalization. Add a focused constant-vs-dynamic regression; require the five-model independent gate and all 71-model platform gates to pass. Reconcile overlapping XML deletion changes already merged in #131. |
| A02 | P1 D/M | Repair or explicitly withdraw the advertised JAX ODE path. Fix the undefined `network` in `_extract_rate_laws`, then verify the actual exported native APIs and numerical conventions end to end. The existing functional-unsupported test is only `pass`; replace it with a real rejection assertion. |
| A03 | P1 Q/M | Review draft #128's equality and PyParsing changes against legacy semantic cases and benchmark it reproducibly. Decide whether to retain this compatibility optimization or retire the path under the API migration plan. |
| A04 | P1 R/M | Replace the historical 9,625-line convergence log and 2,754-line “current” progress file as the operational task list with a compact ledger: task ID, owner, supported scope, current status, dependency, acceptance test, and evidence SHA. Preserve historical reports separately. |
| A05 | P1 R/S | Correct stale architecture/validation docs: missing compiled declarations/AST endpoint claims; absent SSTS locking/reference comparison; blocked `priority` grammar; permanent queued-CI banners; open PR #26; blanket missing export/RHS-test claims. Each correction must cite current code/tests rather than globally checking old boxes. |
| A06 | P1 M/M | Freeze the capability-union inventory across BioNetGen, PyBioNetGen, canonical NFsim, the newer NFsim fork, Atomizer/Playground, and optional tools. Each behavior must be supported, explicitly experimental, compatibility-only, deprecated, or deliberately out of scope, with an owner. “Port everything” is not an executable acceptance contract. |

**2. Finish the C++ semantic and runtime boundaries.**

Evidence: `cpp/compile/{CompiledModel,CompiledRule,PatternDescriptor,Document}.hpp`, `cpp/engine/{NetworkRulePlan,LegacyNetworkRuleKernel,FiniteBackend}.*`, `provenance/architecture/ast_compat_allowlist.txt`, and ADRs 0001–0003.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| B01 | P1 I/XL | Migrate remaining execution consumers to resolved compile-owned inputs. Shrink the 43-file compatibility allowlist in parity-preserving slices; existing typed declarations are the starting point. Solvers/writers/adapters should not independently rediscover source semantics. |
| B02 | P1 I/L | Complete network-rule execution separation. `LegacyNetworkRuleKernel` still reconstructs `ast::ReactionRule` and lowers resolved expressions back to AST objects. Move required runtime behavior behind a semantic execution contract, then retire the reconstruction where evidence permits. |
| B03 | P1 I/L | Make the separated simulation protocol semantically typed. `ProtocolAction` still stores action names and argument values as strings. Centralize option decoding, units/defaults, validation, and execution semantics shared by CLI/Python/actions. Test equivalent entry points and invalid combinations. |
| B04 | P1 Q/L | Qualify compile-once/instantiate-many: independent trajectory/RNG/cache ownership, parameter overrides, topology/volume changes, exception cleanup, and parallel scans. Add meaningful repeated-run and concurrent-instance contracts before relying on reuse for speed. |
| B05 | P1 I/L | Unify graph-identity semantics. NFsim `complex.cpp` still performs its own nauty encoding/canonicalization while network species use `SpeciesGraph::canonicalLabel`. Compare both against independent graph isomorphism, including symmetric and compartmental complexes, then share the justified invariant/implementation. |
| B06 | P1 I/L | Finish one rate-law/local-function semantic contract across backends: special rates, TFUN provenance, molecule/complex scopes, multiplicity, parameter/time/observable dependencies, and cache invalidation. Existing shared expression infrastructure and five-fixture RHS tests are progress, not complete coverage. |
| B07 | P1 M/L | Resolve and execute ADR 0003's finite-backend direction. BNGsim is described as the intended canonical finite engine but remains opt-in and rejects substantial input classes. Decide the supported boundary, implement adapter gaps with native-vs-BNGsim parity, and document deliberate native fallback instead of maintaining two indefinite numerical stacks. |
| B08 | P2 R/M | Remove duplicated BNGsim capability/rejection logic between `FiniteBackend.cpp` and `BngsimAdapter.cpp`. Compile one semantic lowering/capability boundary even without the external solver; verify diagnostics and support results agree in adapter-enabled and adapter-disabled builds. |

**3. NFsim, NFcore2, NFnext, and hybrid models.**

Evidence: `cpp/nfnext/src/from_bng.cpp`, `cpp/nfsim/NFcore2/driver.cpp`, `cpp/nfsim/NFinput/NFinput_fromAst.cpp`, `cpp/compile/Capabilities.cpp`, `cpp/ast/PopulationMap.hpp`, and `cpp/engine/HybridModelGenerator.cpp`.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| C01 | P1 Q/L | Expand direct-NFsim vs XML vs independent-native comparisons across local functions, observables, dynamic rates, symmetric transformations, deletion, filters, compartment movement, options, and lifecycle. Assert the actual route and retain fixed-seed plus distributional evidence. The manifest's NF tier currently contains only four models. |
| C02 | P1 I/XL | Extend NFnext's accepted lowering surface deliberately: currently dynamic rate graphs, include/exclude filters, most modifiers, energy factors, population maps, and compartment semantics remain unsupported or incomplete. Preserve fail-closed checks until each has representation, execution, and independent comparison. |
| C03 | P1 I/XL | Qualify a complete NFnext execution boundary including initial state, observables, parameters/functions, protocol and output semantics, not just molecule types and expanded rules. Connect the real production lowering to richer Lean/reference fixtures before promoting it as an NFsim replacement. |
| C04 | P2 M/L | Decide the maintained role of NFcore2 versus NFnext versus embedded NFcore. NFcore2's driver still rejects expression rate laws, limits roots, and is not a general replacement. Either complete a specifically supported production route or label/contain the prototype; avoid three competing owners of the same semantics. |
| C05 | P1 I/L | Complete or explicitly scope out particle/population execution refinement. Population-map parsing/storage and generated hybrid BNGL are not equivalent to a verified hybrid simulator. Cover whole-complex conversion, mapped rates, observables, conservation, and the generator's compartment boundary. |
| C06 | P1 I/L | Integrate and independently validate the physical-unit count/rate bridge for direct NFsim. The compiler explicitly rejects unit annotations there today. Cover mole/item conversion, reaction molecularity, compartment dimensions, and avoiding duplicate volume scaling. |
| C07 | P2 Q/L | Refresh per-commit reconciliation for newer NFsim energy/performance/Rasi work and expand real RNA/uORF, TQSSA, motor, fceRI and multisite protocol evidence. Do not blindly port old “remaining” lists; assign each source behavior a current equivalence test or maintained exclusion. |

**4. BNG-IR as a durable interchange and compilation boundary.**

Evidence: `python/bionetgen/bngir.py`, `cpp/bindings/bind_compile_snapshot.cpp`, `provenance/schemas/bngir-*.schema.json`, `formal/lean/BNG/BNGIR.lean`.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| D01 | P1 I/L | Implement native structural BNGIR deserialization into the resolved model. `from_bngir` currently renders BNGL and calls `_cpp.parse_string` for both versions. Demonstrate reconstruction without parser/source-string dependence and then compile/run the reconstructed model. |
| D02 | P1 Q/L | Audit structural round trips over the complete supported semantic surface: ID references, reversible directions, correspondence/mutations, filters/local scopes, units/compartments, energy, population metadata, and protocol. Test behavior as well as payload shape; reject anything the wire version cannot preserve. |
| D03 | P1 I/M | Add an independent native BNGIR contract, schema/version migration tests, malformed-reference/property tests, and deterministic serialization fixtures. Python JSON validation and Lean envelope theorems alone do not qualify the C++ import boundary. |
| D04 | P2 M/M | Decide the default wire version and compatibility policy: public serialization/equality still default to 0.1, which rejects physical units and population-map import. Specify supported upgrades, canonical identity versus provenance, and exactly what `semantic_equal` promises; it currently compares serialized documents. |

**5. Atomizer, SBML, events, and exports.**

Evidence: ADR 0004; `cpp/ast/Model.hpp`, `cpp/compile/CompiledModel.cpp`, `python/bionetgen/atomizer/modern/`, `scripts/ci/validate_sbml_test_suite.py`, and the export tests.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| E01 | P1 I/XL | Implement native dynamic events through the canonical model and execution layers. Grammar/AST/writer support exists, but compilation/simulation explicitly reject `bng3_events`. Add continuous root detection, trigger transitions, initial edges, state/parameter/compartment updates, and solver reinitialization. |
| E02 | P1 I/XL | Complete event queue semantics: delays, trigger-time versus execution-time snapshots, persistence/cancellation, reevaluated priorities, cascades/recurrence, and seeded equal-priority ordering. Add stochastic integration at reaction-state changes. Qualify each supported slice against official reference outputs and an independent engine. |
| E03 | P1 Q/L | Produce a current, revision-locked SSTS report with import, round trip, official-reference conformance, and independent numerical comparison reported separately. The runner now supports source locking and reference comparison; the historical 1,744/179/0/0 is not current-head evidence. Check event targets and non-observable state, not only declared observables. |
| E04 | P1 I/L | Triage the current unsupported SBML surface by semantic class rather than isolated model count: coupled/nonlinear dynamic rules/events, delay/history, algebraic constraints, variable stoichiometry, fast reactions, and packages. For each class implement exact semantics or publish an explicit supported-subset decision. Do not make full SBML support a hidden requirement. |
| E05 | P2 Q/L | Qualify structural Atomizer and SBML Multi end-to-end reconstruction/execution across reaction/bond changes, compartments, quantities and metadata. These already have implementations; broaden independent execution and round-trip evidence rather than treating them as parser-only. |
| E06 | P2 Q/L | Complete curated BioModels and modern-vs-legacy Atomizer cross-engine qualification on a fixed final source, with per-case pass/unsupported/fail/timeout/invalid-source categories and stable artifacts. The prior user-stopped full BioModels run remains stopped; this audit did not restart it. A future full rerun needs explicit resumption. |
| E07 | P1 Q/L | Build a nonempty format Tier-X and consumer-level checks for BNGL, BNG-XML, NET, SBML/Multi, MATLAB/MEX, Python/C++ exports, SSC, MDL, LaTeX and graph writers. Existing tests disprove the old claim of “no coverage”; remaining work is complete supported-feature round trips, valid downstream consumption, and explicit unsupported loss. |
| E08 | P2 R/L | Split Atomizer by semantic responsibility with characterization tests: `writer.py` is 10,063 lines and `events.py` 8,042. Isolate symbol resolution, capability checks, trajectory proofs/event planning, unit lowering, structural mapping and text emission. Preserve behavior; file size alone is not justification for a rewrite. |

**6. Lean and mathematical checks.**

Evidence: `formal/lean/BNG/MatcherSpec.lean`, `NFnextIR.lean`, `Evaluation.lean`, `Stochastic.lean`, `Propensity.lean`, `Network.lean`, and `formal/lean/VALIDATION.md`.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| F01 | P1 I/L | Prove `ReferenceMatcherCorrect`: executable embedding matching iff its proposition-level specification, including soundness and completeness. It is currently a defined obligation, not a proved theorem. |
| F02 | P1 I/XL | Establish a general production lowering correspondence for a named supported subset. Existing universal equalities connect Lean interpreters; the C++ bridge is a concrete fixture. Specify serialization/ID packing correspondence and validate/prove the actual compiler boundary without assuming its correctness. |
| F03 | P2 I/XL | Extend exact reference semantics/refinement for supported special rate laws, local functions, builtins/TFUN, full propensities, event selection, and stochastic behavior. Numerical floating-point solver correctness is a separate boundary; do not infer it from algebraic or combinatorial proofs. |
| F04 | P2 I/L | Qualify production species canonicalization and finite network generation against the independent graph-isomorphism/reference semantics, with generated differential cases; then state and prove the intended bounded equivalence. |
| F05 | P1 Q/M | Maintain explicit proof trust accounting: separate general theorems, `decide`/`rfl` proofs, `native_decide` fixtures, native C++ tests, and assumptions. Refresh stale migration blockers; keep Smoke/Coverage/axiom audit explicit. Consider running the existing harness-mutation self-test in scheduled CI. |
| F06 | P3 M/XL | Define the optional CRNT bridge scope if mathematical model-property checks are a product requirement: which networks can be exported, what assumptions accompany them, and which theorems are actually proved. The current semantic kernel does not establish biological truth or arbitrary model stability. |

**7. Public API, compatibility, performance, and engineering quality.**

Evidence: `python/bionetgen/{__init__,model,compat/runner,jax_ode,jax_ssa}.py`, `cpp/actions/ActionDispatch.cpp`, `cpp/engine/gpu/`, `pyproject.toml`, and benchmark tooling.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| G01 | P1 Q/L | Finish the PyBioNetGen compatibility matrix: signatures/defaults, positional dispatch, timeout behavior, actions, result/file shapes, exceptions, optional imports, notebooks and integrations. Contract-test API and installed CLI across each supported simulation method; distinguish intended incompatibilities from missing implementation. |
| G02 | P2 R/L | Retire redundant `modelapi`, legacy parser/network/simulator and Cement paths only after import/caller tracing and compatibility evidence. Preserve a deliberately supported legacy adapter. Audit broad import fallbacks/`None` exports so missing required functionality gives actionable diagnostics. |
| G03 | P1 D/M | Complete or explicitly label JAX SSA as unavailable: both the trajectory path and public `simulate` raise `NotImplementedError`. Provide a dedicated optional-dependency CI lane before advertising a supported accelerator. Extend lint beyond F401/F841 to undefined-name checks such as F821, which would catch A02. |
| G04 | P2 Q/L | Refresh representative performance baselines on the final revision: parse/compile/generate, ODE/SSA/NFsim, scans, cold/warm setup, peak memory and allocations. Use independent semantic oracles and controlled A/A timing; retain rejected/no-win experiments. A C++ implementation by itself is not a speed acceptance result. |
| G05 | P2 Q/L | Run actual NVIDIA-device CUDA parity and crossover benchmarks. The current CUDA CI compiles with required nvcc and validates CPU fallback without a GPU; it is no longer a vacuous no-toolkit check, but it does not execute device kernels. Maintain Metal/CPU comparisons and backend result-shape/RNG contracts. |
| G06 | P2 M/L | Reassess the NFsim CPU/ensemble/GPU roadmap against current measurements and implemented work. Network batch SSA is not network-free GPU execution. Qualify NFsim ensemble APIs and isolation if retained in scope; only pursue device kernels after a measured supported class wins. |
| G07 | P2 Q/L | Qualify experimental barrier/reservoir energy semantics with independent analytic expectations and a reference implementation, plus detailed-balance/affinity, reversal, unit and exporter checks. Keep opt-in status until the evidence exists; canonical BNG2/NFsim cannot independently validate extensions they do not implement. |
| G08 | P2 R/L | Reduce large dispatch/numerical modules through existing seams: `ActionDispatch.cpp` (~4k lines), `OdeIntegrator.cpp` (~3.2k), and rate-aware exporters. Centralize shared option/rate/capability logic, retain separate backend state, and remove duplicated decisions rather than adding another framework. |

**8. Validation, provenance, release, and project maintenance.**

Evidence: `provenance/upstreams.lock.yml`, `provenance/reconciliation/`, `provenance/corpus/selection.json`, `tests/validation/`, `.github/workflows/`, and `pyproject.toml`.

| ID | Priority/type/effort | Outstanding task and completion criterion |
| --- | --- | --- |
| H01 | P1 M/M | Resolve all 14 strict provenance errors with maintainer decisions and reproducible records. Approve actual source cutoffs/oracle recipes/toolchains; do not simply flip status strings. Wire strict approval validation into release qualification after decisions are made. |
| H02 | P1 Q/L | Refresh source drift and complete behavior-to-test reconciliation. Ledgers currently have 29 BioNetGen, 4 NFsim and 2 PyBioNetGen entries with unassigned owners; many have no tests, including some substantive equivalence claims. Documentation/merge-only entries need no artificial tests; behavior claims need exact evidence. |
| H03 | P1 Q/L | Approve full corpus selection and budgets. Tier-P=106 and the 71-fixture workflow are not the historical 512-model aspiration; Tier-NF=4, Tier-X=0 and Tier-B=0. Populate justified format/stress tiers and map coverage to the capability inventory instead of treating any “full corpus” job name as universal coverage. |
| H04 | P1 Q/L | Wire existing numerical/expression/export parity modules into explicit required or scheduled lanes. Current parity workflow selects NFsim modules and five BNG2 network cases; `test_parity_rhs`, ODE/stochastic and broader export modules do not become hosted gates merely by existing in `tests/validation`. Use isolated exact-source package/native builds and fail on missing required oracles. |
| H05 | P1 Q/L | Add a budgeted SSTS conformance workflow and durable per-case artifacts, pinned suite/runtime dependencies and report digests. Keep official reference outputs distinct from libRoadRunner agreement and conversion-only passes. Retain zero-observable/non-comparable cases separately. |
| H06 | P2 Q/M | Establish release-candidate gates beyond normal main CI: scheduled historical NFsim completion, approved provenance/corpora, clean installs/upgrade paths, optional extras, installed CLI and representative scientific execution, platform/architecture and sanitizer/memory evidence, licenses/notices and reproducible build metadata. Main's green wheels are existing evidence, not a reason to redo them without a changed candidate. |
| H07 | P2 M/M | Assign domain review ownership for semantic core, scientific comparators/tolerances, provenance, formal proofs and public compatibility. No `.github/CODEOWNERS` is present. Review branch protection separately; its configuration was not queried in this audit. |
| H08 | P2 M/M | Complete user-facing migration/release guidance: alpha installation command versus legacy stable package, supported/experimental backend matrix, optional dependency behavior, compatibility deprecations, canonical repository contribution policy, and eventual upstream retirement/maintenance arrangements. Avoid presenting current alpha APIs as the behavior of an unspecified `pip install bionetgen` release. |

**Suggested execution order.**

1. **Stabilize the known surface:** A01–A06, A02/G03 optional-path defects, H01/H03. Establish the live capability/task ledger and classify failures before changing semantics.
2. **Complete the core boundary:** B01–B08 and D01–D03, with C01 evidence in parallel where independent. This unlocks reuse, robust serialization, simpler backend adapters and meaningful formal correspondence.
3. **Close required capability gaps:** C02–C07 and E01–E07 according to the approved feature matrix. Keep optional backend promotion separate from preserving existing NFsim functionality.
4. **Strengthen guarantees:** F01/F02, H02/H04/H05, G01/G04/G05/G07 and generated differential coverage; qualify each completed semantic slice rather than deferring all evidence to the end.
5. **Consolidate and release:** E08/G02/G08 refactors and retirement after parity, then H06–H08. Optional CRNT/JAX/GPU expansion should not obscure core convergence.

The architecture should keep C++ responsible for performance-critical representation, compilation, matching and simulation, with Python responsible for orchestration and suitable translation/tooling. “Full C++ rewrite” should mean a complete native execution path with one scientific semantic contract; mechanically porting every Python helper would add work without establishing correctness or speed.

This backlog contains **55 scoped tasks**. Some are alternative product decisions, and several qualification tasks may close by documenting an intentionally unsupported capability. None of the old aggregate pass counts or unchecked historical boxes was treated as proof of current completion or current failure.
