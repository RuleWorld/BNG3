# Changelog

## [Unreleased] - 2026-09-10

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
- Final consolidated verification passed: build, CTest (305/305), Python
  regression (353 passed, 27 skipped), and validation smoke (4 passed, 14
  environment/reference skips).

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
