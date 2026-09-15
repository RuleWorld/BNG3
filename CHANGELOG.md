# Changelog

## [Unreleased] - 2026-09-15

### In progress

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
