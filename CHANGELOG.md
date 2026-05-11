# Changelog

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
