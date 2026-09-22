# Changelog

## [Unreleased] - 2026-09-15

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
