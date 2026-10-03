# BNG3 execution plan — 2026-10-02

Target: RuleWorld/BNG3. Base: c345f3aa635aac0048681b79c6a4ff1e75a298f7. The other BioNetGen/NFsim/PyBioNetGen repositories are reference/oracle inputs. User authorized separate GPT-6 Luna chats with max thinking, each running goal mode in its own worktree, plus periodic coordinator checks.

## Verified state

- git pull --ff-only origin main completed; BNG3 already up to date. Existing formal/lean/.lake/ remains untracked and preserved.
- Exact-main CI run 36812376393 failed; parity run 36812376327 failed. CodeQL 36812376307 and Lean kernel 36812376260 succeeded. CI is active, so the 2026-09-29 queued-only diagnosis is historical.
- Black fails two Python tests. All 18 Python matrix jobs fail importing bare _bionetgen_cpp from test_thermodynamic_parse_path.py. Windows fails compiling test_gdat_output_format.cpp at unistd.h. Compatibility fails resolving bionetgen._bionetgen_cpp after tree-selection plumbing. These causes were read in current-main job logs.
- Open PRs: 42,59,67,78,81,82,83,84,85,86. PR59 is conflicting with no check rollup; others carry failures. PR42 is a harness-only WIP. Do not confuse shared baseline failures with patch-introduced regressions.
- PR59's advertised three fixes already landed: 44664f1, 9d45825, 341866f and 9572846. Audit residual coverage; avoid duplicate application.
- Latest complete SSTS headline is at historical bf210ab... with suite cf38585fac5de8e0e90112febb62851ee2181816; 1744 passed/179 unsupported/0 failed/0 timed out. It is import/roundtrip + cross-engine evidence, not official expected-output conformance. Current-head reproducibility and reference conformance remain open.
- Curated BioModels sweep remains paused under the prior explicit user stop. Do not restart it.
- Direct expression-vector/RHS 1e-9 acceptance remains unimplemented; historical tests only compare network/rate text. NF protocol, energy, canonicalization and general dynamic-event claims require code-level inventories and independent evidence.
- Strict provenance was recorded at 13 errors, and PR81 proposes visibility/ratcheting. Pending maintainer approval and missing artifacts must remain explicit.

## Execution and dependencies

Seven isolated branches/worktrees start from the same immutable base. CI foundation is integrated first. Core, parity, SBML, performance and formal tasks can inspect/develop independently. Final cross-engine gates must use repaired import/build provenance and the final integrated SHA. Only the integration lane reconciles current status documents. Only CI lane reconciles workflows. SBML-specific source-lock additions are coordinated with integration; regenerating/checking corpus lock hashes is mandatory when relevant.

Each lane uses small test-first slices and its own environment/binaries, commits verified changes, and opens a draft PR with exact-head evidence. Goal mode is activated with create_goal in each child chat, without an invented token budget. No subagents are requested. Existing author branches, shared main checkout and reference repositories are preserved. Publication/merging is outside this execution batch.

Use at most -j2 per build and modest corpus worker counts; performance lane serializes timing-dependent benchmarks under a host lock. Benchmarks run after correctness constraints are established and carry matched artifact provenance.

Codex's saved project named BNG3 currently points at the legacy bionetgen checkout. To prevent misrouting, these are separate projectless chats explicitly assigned the actual BNG3 git worktrees below; every shell command specifies that workdir. Native saved-project worktree creation would select the wrong repository.

## Assignments

### 1. BNG3 CI and installed package repair

Worktree: /private/tmp/bng3-20261002-ci
Branch: codex/bng3-20261002-ci
Goal: Repair the demonstrated lint, Windows, Python wheel-import and PyBioNetGen compatibility failures; deliver a reviewed draft PR with focused local evidence and exact-head hosted CI results.

1. Reproduce main's Black failures in tests/python/test_mm_free_substrate_root.py and test_observable_type_support.py; format only the demonstrated offenders.
2. Repair tests/cpp/test_gdat_output_format.cpp's unconditional unistd.h/getpid use with the smallest portable implementation; preserve the same output assertions.
3. Repair tests/python/test_thermodynamic_parse_path.py's bare _bionetgen_cpp import against an installed wheel. Diagnose tests/python/conftest.py plus scripts/ci/check_pybionetgen_compat.py and parity.yml so source-tree and installed-package tests exercise the intended package AND native binary. Preserve fail-loudly checks; do not use importorskip or tolerate a shadowed extension. Test clean wheel and clean sdist environments; print Python package and extension paths and binary/source identity.
4. Review and carry forward the justified changes from PR85 (workflow parsing and runner repair) and PR86 (.lake ignore), preserving authors' branches. Own .github/workflows/ci.yml, parity.yml, release.yml, tests/test_ci_contract.py, tests/test_workflow_contract.py, tests/workflow_yaml.py, .gitignore, Python conftest and test-import plumbing. Other lanes provide workflow patches for you to reconcile.
5. Verify Black/Ruff, workflow and CI contracts, native output test, clean installed CLI/import smoke, and current-head jobs on all four C++ compiler configurations and 3 OS x Python 3.9-3.14. Report unrun release-only jobs and CUDA no-op status separately. The same failure on older PRs is shared baseline failure; do not attribute it to each patch without comparison. Keep separate small commits for formatting, portability, and import provenance.

### 2. BNG3 parser and core correctness

Worktree: /private/tmp/bng3-20261002-core
Branch: codex/bng3-20261002-core
Goal: Verify the current determinism, observable and seed fixes and implement the reproduced priority-identifier parser defect with synchronized generated parser and visitor, or deliver the exact external blocker and preserved patch.

1. Audit PR59 against main. The three advertised fixes already have main commits: 44664f1 (Ullmann row order), 9d45825 (Molecules count filters), 341866f and 9572846 (seed derivation and remaining CpuBatchSsa sites). Re-measure rather than blindly cherry-pick. Produce a precise disposition recommending PR59 be closed as superseded if all changed behavior/tests are covered. Do not close it yourself.
2. Verify fresh-process network byte determinism for tlbr, Motivating_example_cBNGL and SHP2_base_model; verify Molecules and Species observable count behavior against pinned independent BNG2; verify batch seed independence and reproducibility, including backends available locally. Correct reproduced residual defects with focused regression tests.
3. Read docs/known-blocked/priority-keyword-parser-fix.md. Reproduce molecule/type, parameter, observable and observable-reference keyword cases plus rule priority modifiers and bng3_events priority fields. Establish ANTLR generator/runtime version before obtaining official generator/JRE prerequisites. Apply a minimal grammar+visitor change and regenerate the committed cpp/parser/generated files atomically. Preserve emitted names and both existing priority meanings.
4. Own cpp/parser grammar/generated/visitor, core correctness tests and demonstrated engine fixes only. Coordinate engine files with performance lane before editing. Run focused parser/observable/seed tests plus CTest. Do not replace a metadata-preserving parse with a silently dropped name. If generator installation is truly blocked, preserve the tested patch and exact dependency; do not claim parser support from .g4 alone.

### 3. BNG3 independent semantic parity

Worktree: /private/tmp/bng3-20261002-parity
Branch: codex/bng3-20261002-parity
Goal: Deliver trustworthy independent network, expression/RHS, deterministic trajectory and stochastic/NFsim parity gates over frozen tiers, with classified results and preserved oracle identity.

1. Review PR84 and carry forward exact observable-column checks at scientifically appropriate trajectory/ensemble callers. Preserve explicit intersection use where intentional. Fault-inject dropped, phantom, reordered and duplicated observable columns; ensure a missing required observable fails. Own tests/validation/compare.py and parity harness/tests.
2. Implement the still-open direct expression-vector/RHS gate over provenance/corpus/selection.json's expr tier, using canonical BNG2 behavior and independently computed source expression/RHS values at documented state/time vectors. Existing test_parity_expressions.py compares networks for three hardcoded models, so that alone does not close the 1e-9 gate. Justify numeric metrics; preserve fixed tolerances and fail on unexercised cases.
3. Run selected independent BNG2 network/rate, ODE trajectory and stochastic ensemble comparisons; keep structural/network, numeric RHS, trajectory, endpoint and distribution claims distinct. Use native NFsim from the pinned external checkout, never embedded BNG3 as its own oracle. Include direct/XML construction, seed state, energy multiplicity and supported protocol coverage. Triage NF/t4/t5 or symmetric Arrhenius mismatches at their actual layer; no silent XML fallback.
4. Inventory all tests/validation modules and existing CI wiring at current head (docs are stale; seed module is already wired). Supply CI lane a minimal scoped wiring patch for fast deterministic comparator/policy tests and frozen semantic tiers; separate slow ensembles from per-PR tests. Strict missing oracles must fail.
5. Audit current network/NFsim graph identity contracts using BNGcore::SpeciesGraph::canonicalLabel and NFsim's private nauty path. Demonstrate equivalence obligations before any shared-label refactor; preserve domain-specific semantics. Make a concrete tested residual-capability inventory, and fix reproduced bounded defects. Coordinate cpp/nfsim changes before touching them; do not force an architecture rewrite.
6. Verify pytest -c tests/validation/pytest.ini with explicit paths/markers, strict oracle mode, package and binary identities, immutable oracle revisions/digests. Commit machine-readable per-case evidence including failures, unsupported and timeouts.

### 4. BNG3 reproducible SBML conformance

Worktree: /private/tmp/bng3-20261002-sbml
Branch: codex/bng3-20261002-sbml
Goal: Make official SBML Test Suite evidence reproducible at the tested BNG3 SHA and distinguish official reference conformance from import, round-trip and libRoadRunner comparison; fix bounded demonstrated semantic defects without approximation.

1. The latest full 1744/179/0/0 SSTS report is historical at bf210ab..., is not a current-head gate and has no committed report. The runner does not enforce the suite revision and no CI job installs libRoadRunner. Add an immutable suite-lock entry (the historical suite revision cf38585fac5de8e0e90112febb62851ee2181816 is an explicit candidate, not silently approved governance) and validate-only/check-before-run behavior. Own the SSTS-specific lock entry, scripts/ci/validate_sbml_test_suite.py and related runner tests; notify integration lane before modifying the shared lock and regenerate/check frozen corpus if its source-lock hash depends on your change.
2. Implement official expected-output conformance using suite settings, sampling grid, amount/concentration meanings and published tolerances. Keep that result separate from BNG3-versus-libRoadRunner numerical agreement and schema/native-reader/round-trip checks. Do not globally widen solver tolerances or change horizon to admit cases.
3. Build and install this worktree's extension in an isolated environment. Refresh the supported SSTS surface and save machine-readable source SHA, suite SHA, dependency versions, commands, digests and per-case passed/unsupported/failed/timed-out/invalid-source statuses in a durable artifact. A full aggregate needs the actual full frozen suite; do not extrapolate a cohort.
4. Use the failure/unsupported inventory to select the smallest semantics-preserving fixes first: source identifiers, rate/math constructs, metadata/units/compartments/conversion factors, supported event cohorts, structured-SBML/native writer path. Verify each against SBML specification plus independent reference. Preserve AST event rejection where a backend cannot execute them.
5. General dynamic event scheduling remains a substantive architecture boundary. Define the precise remaining trigger/delay/priority/persistence/snapshot semantics and backend requirements from code; implement only bounded provable subclasses in small slices. Do not mark general event runtime complete from analytic folding.
6. The user's curated BioModels sweep is paused. Do not restart it. Send CI lane a scoped proposed SSTS job/dependency patch rather than editing workflows concurrently. Coordinate source-lock changes with integration. Focused regression tests, pinned event cohorts, and final full frozen supported-surface run are separate checkpoints.

### 5. BNG3 performance PR qualification

Worktree: /private/tmp/bng3-20261002-performance
Branch: codex/bng3-20261002-performance
Goal: Qualify the remaining performance and measurement PRs against current corrected semantics with reproducible measurements and an independent correctness guard, delivering defensible small PRs or explicit no-win dispositions.

1. Review PR82 host benchmark exclusion and PR67 documentation corrections; preserve justified changes on your own branch. Establish one timing-sensitive benchmark lock for all lanes using the reviewed benchlock tool; serialize timing-sensitive measurements and record undeclared co-tenants. Correctness/build work does not itself claim timing evidence.
2. Review PR42's 11-fixture network-generation harness. Its tlbr nondeterminism exemption predates main's 44664f1 fix. Re-measure baseline determinism and remove obsolete exemptions only when demonstrated. Preserve graph/rate correctness as well as output reproducibility; counts-only comparison is inadequate.
3. Review PR78's SSA measurement harness. Its byte-identity claim predates seed changes in 341866f/9572846; choose an immutable matched baseline/candidate pair and distinguish intentional RNG-stream changes from physics regressions. Verify conservation, reproducibility, distribution parity, and allocations before quoting timings.
4. Re-measure pending netgen/SSA/batch candidates one change at a time at matched compiler/options/fixtures. Report exact source/binary digests, event counts, min/median/reps, RSS units, interleaving, load and benchmark co-tenants. Inspect the historical PR78 RSS units rather than copying them blindly. A harness-only PR is not a production speedup.
5. Implement one profile-supported candidate only after proving a bottleneck and measuring a baseline. Keep it separate from measurement tooling/doc fixes. Reject within-noise/no-win candidates honestly; no target speedup was specified.
6. Own bench/, verify/, tools/benchlock/ and docs/PERF_EXPRESSION_CODEGEN_NO_WIN.md; coordinate any cpp/engine/core changes with core lane. Verify the measurement harness, CTest/affected semantic parity and A/B correctness before a draft PR. Supply integration precise PR42/67/78/82 dispositions without closing or merging them.

### 6. BNG3 Lean kernel validation scope

Worktree: /private/tmp/bng3-20261002-formal
Branch: codex/bng3-20261002-formal
Goal: Revalidate current Lean/NFnext/MatchOnce claims and axiom dependencies, land the justified PR83 documentation correction, and expose the exact boundary between executable fixture checks and general semantic theorems.

1. Review PR83 at current main and preserve its correct NFnext C++ bridge citation and validation wording. The real lowering mirror is tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp, not test_nfnext.cpp's hand-built ModelIR cache round-trip.
2. Current main already contains formal gate fault-injection work (#62), connected-complex MatchOnce fix (#79), and corrected characterization values (#80). Verify current tests, not stale Smoke or Coverage claims.
3. Using the pinned formal/lean toolchain, run lake build, tests/Smoke.lean and Coverage.lean, scripts/check_axiom_dependencies.sh, and corresponding NFnext C++ contracts. Record exact theorem declarations and axiom lists; native_decide extensions must remain explicitly disclosed. No sorry/admit/new axioms or weakened premises.
4. Review correspondence boundaries: a compiled example, value characterization, kernel theorem and C++ implementation refinement are different claims. Check population/hybrid/runtime contracts against actual native code and fix a demonstrated bounded mismatch with regression coverage if found.
5. Own formal/lean and its evidence docs/tests; supply CI lane any necessary formal.yml patch. Deliver exact commands, theorem/axiom audit and a small PR. General formal equivalence that is unproved remains a named gap, never hidden behind fixtures.

### 7. BNG3 integration and convergence acceptance

Worktree: /private/tmp/bng3-20261002-integration
Branch: codex/bng3-20261002-integration
Goal: Produce a reviewed integration candidate containing validated lane changes, an accurate current convergence checklist, reproducible acceptance evidence and explicit maintainer/release blockers.

1. Read this plan and own tasks/plan.md, tasks/todo.md, docs/VALIDATION_EVIDENCE.md, CURRENT_PROGRESS.md and the convergence checklist's current-state preamble. Keep historical entries intact. Reconcile code and exact CI evidence before treating an open box as current.
2. Review PR81's strict-provenance visibility/ratchet approach. Its 13 errors include real missing recipes/digests and human approval decisions. Preserve pending status; never invent accepted/approved values. Coordinate with CI lane for workflow edits and with SBML lane for suite source-lock changes. Own provenance ratchet/tests and reconciliation evidence; do not race over shared lock files.
3. Build independent locked BNG2 and NFsim oracle recipes/artifact digests, fill technical evidence for reconciliation entries, and record unresolved owner/baseline/compiler-image/Python-lock decisions. A ratchet can prevent regressions while still being explicitly not strict provenance success. CODEOWNERS requires real designated maintainers; do not invent owners.
4. Read lane status files under /private/tmp/bng3-20261002-<lane>/lane-status.json and inspect commits/diffs/tests/gh checks. You are authorized to communicate with the six newly-created lane chats listed in chat-manifest.json for coordination; do not message unrelated chats. Wait until each dependent change is available and verified before applying it.
5. Integrate on your codex branch, sequentially: CI/import/portability foundation; core parser fixes; comparator/parity and SSTS changes; performance tools/candidates and Lean docs; provenance ratchet plus unified evidence. Cherry-pick reviewed minimal commits, resolve overlaps explicitly, and rerun affected gates. Preserve original lane branches and existing PR authors' branches.
6. Final RC checks: policy/provenance/corpus/frozen-manifest/exception budget/workflow contracts, native CTest, Python suite from isolated installed package, strict independent BNG2 networks/NFsim/compatibility, numeric RHS and trajectories/ensembles, official SSTS supported-surface/reference conformance, Lean kernel/axioms, clean sdist and wheels/CLI/embedded data. Use exact final SHA for hosted Linux/macOS/Windows and Python3.9-3.14 evidence; distinguish skipped release-only/CUDA no-op from passes.
7. Publish a draft integration PR and the precise disposition for open PR42,59,67,78,81-86. Existing PR59's behaviors already landed; verify test coverage and recommend superseded closure rather than cherry-picking duplicate fixes. Keep release publication and merging for later authorization.
8. Mark this bounded goal complete only when the integration candidate and factual acceptance report exist and required verification is terminal, or when explicit external decisions/data prevent remaining gates and the result clearly reports that boundary. Do not claim overall convergence/release readiness with unresolved semantic, governance or cross-platform gates. Use a blocked status only following the goal tool's repeated-blocker rules.


## Review checkpoints

1. Foundation: the demonstrated formatting/import/Windows failures are repaired without weakening fail-loudly guards; installed wheel and source-tree testing have explicit identity.
2. Semantic acceptance: current determinism/observable/seed behavior passes; priority keyword parser retains names and modifiers; numeric RHS, required columns, native NFsim and official SSTS conformance are separately classified and tested.
3. Candidate: integrated final SHA has terminal relevant native/Python/parity/formal jobs, clean artifacts and durable evidence. Nonterminal, skipped, unsupported, no-op and maintainer-blocked gates remain distinct.
4. Queue disposition: each open PR has an exact reviewed retain/rebase/superseded/hold rationale. No global convergence or release claim from historical counts or partial checks.

## Follow-up after this batch

General event scheduling, unsupported SBML classes, full direct NFsim/protocol/energy qualification, graph identity equivalence and release governance stay explicitly open unless their assigned bounded work establishes the full claimed semantics. Expand in prioritized vertical slices from reproduced user-facing failures, not from stale unchecked boxes or pass-count incentives. The integration report records a precise remaining inventory and the next acceptance case for each open capability.

