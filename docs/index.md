# BioNetGen 3 Documentation

Welcome to the BioNetGen 3 (BNG3) documentation. BNG3 unifies the BioNetGen rule-based modeling engine (C++17), network-free simulation (**NFnext** and embedded **NFcore/NFsim**), SBML Atomizer, and Python/CLI workflows into a single in-process package that requires no Perl on the default path.

> **Release status:** The latest published pre-release is **`v3.0.0a1`** on [GitHub Releases](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1) (commit `8482215c`). BNG3 is not yet on PyPI—running `pip install bionetgen` today installs legacy PyBioNetGen `0.8.7`. See the [Installation section in the README](../README.md#installation) for verified wheel, standalone CLI, and source-checkout commands.

## Start Here

- **New to BioNetGen 3?** Follow the self-contained [Quickstart](../README.md#quickstart), then work through the [User Guide](user_guide.md).
- **Wondering what BNG3 supports?** Read the [Capability Guide](capabilities.md) for a workflow-oriented overview of defaults, optional backends, SBML boundaries, and platform limits.
- **Moving from BNG2 or PyBioNetGen?** Start with the task-oriented [Migration Guide](migration_guide.md) and search the [Detailed BNG2 & PyBioNetGen Change Reference](bng2_migration_reference.md).
- **Running network-free simulations?** Read the [Network-Free Simulation Guide (NFsim & NFnext)](network_free_simulation.md) to choose an engine and confirm which backend ran.

## User Documentation

- [User Guide](user_guide.md) — Loading models, inspecting components, simulating, scanning, sensitivities, programmatic building, exports, and SBML import
- [Capability Guide](capabilities.md) — What BNG3 supports by user workflow, optional backends, and qualification boundaries
- [Network-Free Simulation (NFsim & NFnext)](network_free_simulation.md) — Standalone NFsim, embedded NFcore, NFnext, GPU boundaries, seeds, and roadmap
- [Migration Guide](migration_guide.md) — Moving from BNG2 and PyBioNetGen with tested before/after recipes and a lab checklist
- [Detailed BNG2 & PyBioNetGen Change Reference](bng2_migration_reference.md) — Searchable family-by-family reference of changes in CLI, syntax, actions, solvers, seeds, outputs, and Python APIs
- [CLI Reference](cli_reference.md) — All `bionetgen` subcommands, standalone `bng_cpp` / `NFsim` binaries, and environment variables
- [Python API Reference](api_reference.md) — Module exports, `BioNetGenModel`, `SimResult`, scans, sensitivities, CRN export, BNGIR, and `ModelBuilder`
- [SBML Atomizer Limitations](ATOMIZER_LIMITATIONS.md) — Generated scope record of SBML Test Suite constructs refused by the Atomizer vs. harness measurement limits
- [Physical Units](BNG3_UNITS.md) — Unit declarations, dimensional checking, and compartment/NFsim unit conventions
- [Nonequilibrium Energy Extensions](nonequilibrium_energy.md) — Experimental `begin barrier patterns` and `driven_by()` reservoir work (opt-in via `BNG_NFSIM_GENERAL_ENERGY`)

## Architecture, Contributing, and Maintenance

- [Architecture](architecture.md) — C++ libraries, semantic compile layer, finite/network-free dispatch, BNGIR, and Python package layout
- [Contributing & Bug Reporting](contributing.md) — Source builds, running tests, code style, and how to file a reproducible issue
- [BNGsim Optional Backend Status](bngsim-migration-status.md) — Lowering coverage and fail-closed rejection inventory for `backend="bngsim"` (see [ADR 0003](adr/0003-bngsim-canonical-finite-backend.md))
- [Architecture Decision Records (ADRs)](adr/) — Recorded design boundaries (`0001`–`0004`)

## Release Scope, Decisions, and Validation Evidence

These maintainer documents trace release scope and qualification evidence; end users rarely need to read them first:

- [Capability Union Inventory](CAPABILITY_UNION_INVENTORY.md) — Complete 997-row release scope table linked to [the machine-readable matrix](../provenance/capability-matrix.yml)
- [Maintainer Decisions](DECISIONS.md) — Final release policies and accepted upstream pins ([`provenance/upstreams.lock.yml`](../provenance/upstreams.lock.yml))
- [Current Progress](CURRENT_PROGRESS.md) — Issue-keyed qualification evidence and remaining obligations
- [CI Parity](CI_PARITY.md) — Independent BNG2, NFsim, and PyBioNetGen CI gates
- [Validation Harness](../tests/validation/README.md) — Corpus commands, differential comparators, and oracle boundaries
- [Benchmarks](../benchmarks/README.md) — CPU benchmark scripts and methodology ([GPU Batch SSA Evaluation](GPU_BATCH_SSA_EVALUATION.md))
- [Curated BioModels Corpus](CURATED_BIOMODELS_CORPUS.md) & [SBML Conformance Findings](SBML_CONFORMANCE_FINDINGS.md) — SBML corpus measurements and defect backlog
- [Convergence Checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) — Operational task index
- [Historical Reports Archive](archive/reports/) — Dated historical audits and migration records (archived; not current instructions)
