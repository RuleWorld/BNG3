# Changelog

## [Unreleased] — post-`v3.0.0a1` `main` (through `90832910`)

### Added

- **Prepublication user documentation & licensing:** added workflow-oriented [Capability Guide](docs/capabilities.md), searchable [Detailed BNG2 & PyBioNetGen Change Reference](docs/bng2_migration_reference.md), standalone [Network-Free Simulation Guide (NFsim & NFnext)](docs/network_free_simulation.md), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (bundled alongside `LICENSE` in release CLI archives); synchronized `README.md`, `docs/index.md`, `docs/user_guide.md`, `docs/cli_reference.md`, `docs/api_reference.md`, `docs/migration_guide.md`, `docs/architecture.md`, and `docs/contributing.md` with verified `v3.0.0a1` vs. `main` installation and usage contracts.
- **NFnext GPU graph mode (`#474`):** added `mode="graph"` to `BioNetGenModel.simulate_nfnext_gpu()` for Apple Metal and NVIDIA CUDA covering `TIER_NF` graph SSA (PRs `#1040`, `#1041`, `#1044`).
- **CLI & action parity:** added `bng_cpp --outdir` / `--output_dir` (PR `#1056`), `NFsim -i` initial start time flag (PR `#1052`), `writeMfile_all` / `writeLaTeXfile` and `prefix`/`suffix` handling across `write*` and `visualize` actions (PR `#1050`), `bifurcate` continuation and per-observable `.scan` output (PR `#1053`), and `readModel` refresh, `setModelName`, `print_net`, `simulate_protocol`, `readNFspecies`, `readSBML`, `LPS`, and `codename` (PR `#1054`).

### Changed

- **Repository housekeeping & archival:** archived the retired NFcore2 prototype engine from `cpp/nfsim/NFcore2/` to `legacy/nfcore2/` (moving active `nfsim_pattern_lowering.{hh,cpp}` to `cpp/nfsim/NFinput/` and gating `bng_nfcore2` behind `BUILD_TESTS=ON`), archived superseded plans/reports/handoffs under `docs/archive/`, aligned stale pre-`#832` doc-check regexes and `(implementation to add)` inventory location strings, and excluded non-build repo directories from Python source distributions (`pyproject.toml`).
- **Upstream oracle pins refreshed (2026-11-25):** synced with `RuleWorld/bionetgen` through 2.9.5 (`740006ff`, PR `#1046`) and `RuleWorld/NFsim` through `v2.0.1` + `#160` (`d45b7d99`, PR `#1047`); aligned 33 PyBioNetGen API signatures and `assets/VERSION` (`0.8.7`, PRs `#1051`, `#1058`).
- **Capability matrix:** promoted all 997 rows in `provenance/capability-matrix.yml` to `implemented` following hosted-verified oracle receipts (PRs `#1048`, `#1059`).

### Fixed

- **Direct-path NFsim time-indexed `TFUN` parity:** propagated `addTimeTable`, `addFunctionReference`, and `useTimeTablesReadBy` in the direct compiled/AST NFsim adapters so time-indexed `TFUN` breakpoint stepping and linear ramp integration match the XML NFsim path (`test_tfun_validation`).
- **`bng_cpp --version`:** replaced the hardcoded `"bng_cpp version 4.0"` string with `BNG3_VERSION_STRING` (`3.0.0a1`).

## [3.0.0a1] — 2026-11-25 (GitHub Pre-release, commit `8482215c`)

First public alpha pre-release published on [GitHub Releases](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1).

- **Published assets:** 24 CPython 3.9–3.14 wheels (`manylinux_2_28_x86_64`, `macosx_11_0_arm64`, `macosx_11_0_x86_64`, `win_amd64`), source distribution (`bionetgen-3.0.0a1.tar.gz`), and 4 standalone C++ CLI archives (`bng_cpp` + `NFsim` for Linux x86_64, macOS arm64, macOS x86_64, Windows x86_64).
- **Distribution note:** PyPI upload did not complete in Release run `45662137697` (`invalid-publisher` Trusted Publisher configuration error), so `pip install bionetgen` on PyPI currently installs legacy PyBioNetGen `0.8.7`. Install `v3.0.0a1` from GitHub Releases or from source.
- **Included highlights:** in-process C++17 ANTLR4 parser, semantic compiler, single bundled `nauty` graph layer, native CVODE/SSA/PLA/PSA finite solvers, CPU/Metal/CUDA batched direct SSA, NFnext promoted as the Python `method="nf"` default with embedded NFcore selectable via `method="nfcore"`, hybrid particle–population execution, modern SBML L3 Core/comp/Multi Atomizer, CRN JSON export, BNGIR v0.2 default with exact `semantic_equal`, runtime model topology edits, 1D/2D scans, local sensitivities, and 12-subcommand Click CLI.

---

## Historical pre-release development checkpoints

### 2026-11-06 — main implementation checkpoint (unreleased)

### Changed

- Merged [PR #602](https://github.com/RuleWorld/BNG3/pull/602) at
  [`29d8320`](https://github.com/RuleWorld/BNG3/commit/29d8320659832fb2d411e2a51972e227559a9499):
  legacy Atomizer `rulifier/componentGroups.py` replaces `deepcopy` of the
  reaction-center state dictionary with a two-level mapping copy whose inner
  values use shallow `.copy()`; legacy `writer/bnglWriter.py` uses the
  domain-specific `Species.copy()` path (which copies molecules and components)
  instead of `deepcopy` while balancing reactant/product translators. Unused
  imports were also removed.

### Verification boundary

- PR #602 changes copy mechanics, not the supported SBML/BNGL feature set.
  Its two-file merge diff adds no regression tests or benchmark measurements.
  Confirm output equivalence and that the shallow inner copies do not alias
  nested mutable state, and confirm any performance gain, before treating the
  change as a qualified optimization.
- This entry records source changes on the named main commit, not release
  acceptance or current results for the wider capability inventory.

## [Unreleased] - 2026-09-15


### Added

- Added a GPU stochastic-simulation benchmark harness at
  `benchmarks/gpu/` (`run_gpu_bench.py`, `selftest.py`, and the `gpu` package),
  stdlib-only, intended as the common instrument for every accelerator lane.
  It exists because GPU results in this project were previously unreadable: a
  reported speedup carried no measured noise floor, so a real effect and a
  contended host were indistinguishable on the page.

  What it guarantees:

  - **The A/A null is on by default.** Every run measures the instrument
    against itself — the same arm in the same session under the same
    order-alternation discipline — and prints the resulting band *before*
    reporting any effect. An effect inside the band is reported as
    indistinguishable, never as a win. `--no-null` suppresses it and the report
    then says so on its face.
  - **CPU time decides; wall clock never does alone.** Host CPU time is
    contention-immune; wall clock on a shared host is not. Both are recorded,
    and the divergence between them is itself checked, because the two can
    disagree in *direction* for an accelerator that offloads work: a device
    consumes little host CPU while still consuming elapsed time. When they
    disagree, no single speedup number is licensed and both costs must be
    reported separately.
  - **Raw per-round paired deltas with alternating arm order**, and a median
    aggregate. No min-of-K anywhere: that estimator was measured reaching
    +10.5% on identical code.
  - **Accelerator arms carry their own evidence.** An arm refuses to measure
    unless the engine reports a usable device, unless requesting an unusable
    backend demonstrably raises (a `TypeError` from the argument list does not
    count as evidence), and unless the backend the engine reports matches the
    one requested. A silent substitution of a host run wearing a device label
    is structurally excluded; `--verify-no-fallback` exits non-zero if it is
    not.
  - **Equivalence is statistical, and is labelled as such.** Device and host
    trajectories use different random streams and, on hardware without a
    double-precision path, different arithmetic, so bit-identity is not a
    target that could be met. Three independent distributional tests run (a
    per-observable mean z-test with a Bonferroni threshold scaled by the number
    of cells, two-sample Kolmogorov-Smirnov, and a moment comparison), and the
    report states how much agreement the sample size can actually resolve.
  - **Controllable model shapes.** `benchmarks/gpu/models.py` generates
    synthetic networks of an exact reaction count and calibrates their event
    density by running a probe batch and reporting the density *achieved*
    rather than the one requested, so an accelerator can be measured at a
    chosen point on the (reactions x events) plane instead of against the two
    tiny shipped fixtures.
  - **Import provenance is checked.** An editable install can place a
    meta-path finder that redirects project imports to a different checkout
    while producing entirely plausible numbers; the loader neutralises such
    finders before importing and reports which ones it removed alongside the
    resolved module path.

  `benchmarks/gpu/selftest.py` verifies the harness itself (64 checks): that
  the null band catches a planted null, detects a planted effect, and refuses
  to call a real-but-in-the-noise effect a result; that a time ratio is never
  labelled with an inverted direction; that the device and precision guards
  reject what they are supposed to reject.

  No production source and no runtime dependency was changed.

### In progress

- Added an experimental nonequilibrium energy layer: `begin barrier patterns`
  (transition-state contributions keyed by reaction center) and `driven_by(W)`
  (signed reservoir work on a reversible Arrhenius rule), implementing
  `k = exp[-(Ea + B + phi*(dG - W))/RT]`. A barrier cancels in `k_f/k_r` while
  work does not. Every backend boundary refuses both constructs unless
  `BNG_NFSIM_GENERAL_ENERGY` is set, because canonical NFsim and BNG2 do not
  implement these semantics and no independent oracle exists yet. The compact
  `EnergyRxnClass` evaluator is disabled for nonzero barrier or work in favor
  of the materialized Sekar expansion. See `docs/nonequilibrium_energy.md`.
- Fixed a silent data-loss defect on the Python parse path: `python/bionetgen`
  could not previously round-trip a `driven_by(W)` model, or a
  `begin barrier patterns` block, at all. `_bionetgen_cpp.parse_file` /
  `parse_string` drove `BNGAstVisitor` without the post-visit
  `finalizeThermodynamicMetadata()` pass that `parseModel` runs, so the barrier
  came back as an ordinary reaction rule, the surviving rules were renumbered,
  `driving_work` read the neutral zero on every rule, and the synthetic
  `__bng3_*` options were consumed with nothing put back — all with no
  diagnostic. Both bindings now share the single parse pipeline in
  `parseModelSource`, so the two paths can no longer diverge; source parameter
  comments are preserved on the Python path for the same reason.
- Closed the serialization gaps for the new energy constructs: `BnglWriter`
  now emits `begin energy patterns` (previously dropped entirely) and
  `begin barrier patterns`, and appends `driven_by()` to rule lines, so a
  written model round-trips; `XmlWriter` propagates reservoir work to a
  synthesized reverse rule; the Python IR gained a `barrier_patterns` section
  and per-rule `driving_work` with matching feature flags; the BNGsim adapter
  rejects barrier patterns and driven rules rather than ignoring them; and
  barrier patterns are registered under a new `SymbolKind::BarrierPattern`
  instead of sharing the energy-pattern namespace.
- Made the remaining kinetics exporters fail closed on energy semantics. SBML,
  SBML-multi, MATLAB, LaTeX, MCell MDL, SSC, C++, Python and MEX export now
  reject models using energy patterns, barrier patterns, `driven_by()` work, or
  an Arrhenius rate law, via the shared `io::requireNoEnergySemantics()` guard.
  Only the .net writer resolves `Arrhenius(phi, Ea)` into numeric rates, so
  these formats previously emitted a literal Arrhenius call or dropped the
  energy contribution. Structural and visualization writers are intentionally
  unguarded, as are .net, BNGL and XML, which do carry the semantics.
- Barrier-only rules keep the compact `EnergyRxnClass` path: a barrier is a
  direction- and context-independent prefactor, so it folds into the DOR base
  rate exactly. Only reservoir work forces the materialized Sekar expansion.
- Added `compile/energy/ThermodynamicConstraints`: cycle rank, gauge degrees of
  freedom, cycle affinity, and state-potential reconstruction over an abstract
  annotated state graph. The analysis is deterministic with respect to state
  and edge insertion order; an earlier formulation let the cycle-affinity sign
  depend on it.
- Promoted `future_thermodynamic_constraints` and `future_barrier_driving_syntax`
  out of `BNG_ENABLE_FUTURE_ENERGY_CONTRACTS`. Both fixtures in the latter
  opened a model with `end model` and no `begin model`, which the `prog`
  grammar rule cannot accept; corrected.
- Added the consolidated NFnext semantic/runtime contract batch, including
  rule-family compilation, canonicalization, matching, transformations,
  cache v2, replay/RNG, and selected default architecture contracts.
- Added lazy paged NFsim reaction-mapping storage with active-membership
  tracking.
- Reconciled the modern SBML-Multi parser toward bounded structured
  reconstruction with explicit diagnostics and fail-closed execution.
- Added the shared structured SBML-Multi component-map type and synchronized
  the architecture-contract inventory.
- Closed the former PR/weekly validation exclusions with committed independent
  BNG2 network references and explicit action-output contracts; the full
  validation command now reports 71/71 passed with zero failures, errors, or
  skips.
- Repaired reverse local-rate scope preservation, legacy action argument lists,
  visualization/network output naming, and the validation summary contract.
- Repaired the Windows/MSVC ANTLR entry path by applying the existing SDK-macro
  compatibility header to every generated parser and visitor header that can be
  included before a translation-unit-level compatibility include.
- Organized historical migration reports under
  `docs/archive/reports/ir-migration-2026-09-14/` and removed applied patch
  snapshots and redundant package-wrapper files.
- Final local verification for semantic commit `78a1591`: CTest 308/308,
  action contracts 6/6, CI-contract tests 26 passed, and energy Python tests
  66 passed. Final hosted PR run `34896645707` at `ed4c59e` is terminal-success
  for all PR-required build, Python, corpus, parity, formal, package-smoke,
  and integration gates; release-only and scheduled-only jobs are conditionally
  skipped by their event guards.
- Repaired the wheel workflows after main push run `34901298982` exposed a
  macOS 10.9 deployment-target failure in the ANTLR runtime and a
  manylinux2014/GCC 10.2 failure while resolving NumPy 2.5.3. The workflows
  now pin cibuildwheel 4.2.1, use native macOS targets at 10.13/11.0, and use
  `manylinux_2_28`; the auxiliary wheel run `34971595435` was canceled before
  its wheel jobs started, so exact-head wheel validation is deferred to the
  first main-push run after merge.
- Added the 2026-09-15 convergence continuation: direct NFsim checks now
  assert the construction path and disallow implicit XML fallback; spawned
  source-tree workers have stable imports; fixed-seed `motor` and `tlbr`
  endpoint checks are required; and a bounded Lean/production-NFIR bridge
  contract checks state and bond lowering for distinct reactants. Population
  maps remain fail-closed on the direct NFsim path.
- Sped up the Gillespie SSA engine without touching the RNG stream or any
  trajectory byte: each fired event now refreshes only the propensities that
  read a species whose amount changed (species-to-reaction index), and
  reaction selection reads prefix sums stored during the existing in-order
  total-propensity accumulation instead of re-accumulating on the fly
  (binary search for non-negative rates, exact linear scan otherwise).
  `benchmarks/bench_engine_ssa.py` measures simulation-only events/sec with
  interleaved reps: 1.44x at 450 reactions and 1.22x at 150 reactions
  (best-of interleaved reps), 1.04x at 45 reactions; seeded `.gdat`/`.cdat`
  bytes are unchanged on the identity corpus. See `benchmarks/README.md`.

## [3.0.0a1] - 2026-05-11

### Added

- C++ simulation engine with CVODE/SUNDIALS ODE integration and Gillespie SSA
- pybind11 bindings providing zero-copy data transfer between C++ and Python
- Click-based CLI with `run`, `check`, and `export` subcommands
- NFSim integration for network-free simulation via `method="nf"`
- Network generation from rule-based models directly in C++
- ODE, SSA, and network-free (NF) simulation methods accessible from Python
- ANTLR4-based BNGL parser replacing legacy Perl/XML pipeline
- Validation framework for model syntax checking (`bionetgen check`)

### Changed

- Architecture rewrite from Perl (BNG2.pl) to C++ with Python frontend
- New Python API: `bionetgen.load()` / `bionetgen.run()` / `model.simulate()` replacing `bngmodel` and subprocess calls
- Packaging with scikit-build-core for seamless C++ extension builds via pip

### Deprecated

- Legacy Cement CLI (`bionetgen.main`) replaced by Click-based interface
- Subprocess runner (`BNGCLI`) replaced by in-process C++ execution
- CSimulator (ctypes-based ODE solver) replaced by C++ OdeIntegrator

### Breaking Changes

- New model API: `bionetgen.load()` returns `BioNetGenModel` instead of legacy `bngmodel`
- Different return types from `run()`: returns `SimulationResult` with NumPy arrays instead of file paths
- Requires C++ build: the package must be compiled (handled automatically by pip/scikit-build-core)
