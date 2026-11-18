# Issue #137: Establish the Complete Release Capability Inventory

This directory contains the independent release acceptance suite for **Issue #137** (A06: Approve the BNG3 capability-union inventory and support policy).

## Acceptance Criteria

- `release-inventory`: Enumerate all pinned upstream entry points, option values, and public API mappings, and verify that all inventory rows in `provenance/capability-matrix.yml` and `docs/CAPABILITY_UNION_INVENTORY.md` are aligned with no unmapped entry points or dangling check references.
- `release-inventory-links`: Verify that `README.md`, `docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md`, and `provenance/capability-matrix.yml` all link to and agree on `docs/CAPABILITY_UNION_INVENTORY.md`.
- `release-capability-coverage-137`: All 16 assigned inventory rows execute against their row's named independent oracle and pass on main.

## Covered Capability Inventory Rows

The 16 assigned capability inventory rows for Issue #137:
1. `bngl.ast.model`: BNGL AST model representation, nodes, and hierarchy.
2. `bngl.actions.setoption`: `setOption` action parsing, option setting, and configuration propagation.
3. `bngl.observables.counting-modes`: Molecules vs Species counting evaluation in observables.
4. `nfsim.options.parameters`: NFsim CLI parameters parsing and simulation options.
5. `nfsim.compartments`: Compartment definitions and volume scaling under network-free execution.
6. `nfsim.molecule-types`: Molecule type declaration and site/state validation under NFIR.
7. `nfsim.global-functions.safe-subset`: Global mathematical functions in kinetic rate evaluation.
8. `nfsim.seed-species`: Multi-molecule complex seed species initialization.
9. `nfsim.observables`: Pattern observables matching across complexes.
10. `nfsim.reaction-rules`: Elementary reaction rule firing with totalRate / mass-action semantics.
11. `nfsim.energy-and-time-functions`: Energy pattern evaluations and time-dependent rates.
12. `io.sbml.structured-bng2`: SBML export with structured BNG compartments and species annotations.
13. `pybionetgen.api-cli-atomizer`: Atomizer CLI and API entry points (`bionetgen.atomize`).
14. `validation.oracles-goldens-release`: Validation contract integrity and independent oracle verification.
15. `core.graph.canonicalization.single-nauty`: Nauty/Traces canonical labeling produces identical canonical representations for isomorphic graphs.
16. `expression.builtins.shared-table`: Shared mathematical expression function table evaluation.
