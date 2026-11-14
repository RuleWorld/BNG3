# Issue #149 Release Case Package: Network-Free Engine Roles and NFcore2 Consolidation

This package provides bounded route, containment and test-mapping checks toward the release acceptance criteria and obligations for **Issue #149** ("C04: Decide maintained roles for NFcore, NFcore2 and NFnext") under maintainer Decision 4 (`docs/DECISIONS.md`).

## Workload Ownership Matrix

| Workload | Owning Engine | Entry Point | Status |
| :--- | :--- | :--- | :--- |
| Finite Network ODE | Native C++ Engine (CVODE) | `bionetgen.simulate(method="ode")` | Production default for ODE |
| Finite Network SSA | Native C++ Engine (Gillespie SSA) | `bionetgen.simulate(method="ssa")` | Production default for discrete SSA |
| Production Network-Free Simulation | NFcore | `bionetgen.simulate(method="nf")` / `bionetgen.simulate(method="nfcore")` | Production default for network-free simulation |
| Next-Generation Network-Free Engine | NFnext | `bionetgen.simulate(method="nfnext")` | Next-generation engine consolidating NFcore2 capabilities |
| Contained Prototype Oracle | NFcore2 | `cpp/nfsim/NFcore2` / `tests/cpp/test_nfcore2_parity.cpp` | In-tree validation oracle only; not exposed as a simulation route |

## Maintainer Decision 4 Summary

- **Single Next-Gen Engine**: NFnext is the single next-generation network-free engine consolidating NFcore2 capabilities.
- **Input Representation**: `lowerPatternToNFsim` is retained for NFcore input; NFnext consumes `CompiledModel -> NFIR`.
- **Production Default**: NFcore remains production/default (`method="nf"`) and the in-repo comparator until NFnext matches NFcore and pinned native NFsim on the full network-free corpus.
- **Selectable Route**: Explicit selection of NFcore via `method="nfcore"` is fully supported and routes through the common interface (`_cpp.simulate_nf`).
- **Containment of NFcore2**: NFcore2 remains an unpromoted prototype within `cpp/nfsim/NFcore2`. Any direct call specifying `method="nfcore2"` fails closed with an explicit `ValueError`.

## Capability Destination Mapping (NFcore2 -> NFnext)

The following capabilities have been transferred from NFcore2 and verified
executing in production NFnext (`method="nfnext"`):

1. **Reversible Isomerization & Transformation**: Validated in `tests/cpp/test_nfcore2_parity.cpp` (case 1) and executed in production NFnext via `m.simulate(method="nfnext")`.
2. **Compartment Production & Multi-Compartment Binding**: Validated in `test_nfcore2_parity.cpp` (cases 2, 6, 8) and executed in production NFnext with volume scaling and multi-compartment transport.
3. **Molecule vs. Species Compartment Resolution**: Validated in `test_nfcore2_parity.cpp` (case 3) and executed in production NFnext.
4. **MoveConnected Relocation**: Validated in `test_nfcore2_parity.cpp` (cases 4, 5) and executed in production NFnext with connected cargo relocation.
5. **Compartment Placement Validation & Refusal**: Validated in `test_nfcore2_parity.cpp` (case 7) and enforced fail-closed in NFnext.
6. **Non-Root Pattern Transformations**: Validated in `test_nfcore2_parity.cpp` (cases 9-14: state change, molecule deletion, binding, molecule creation, bond deletion, combined state/bond changes) and executed in production NFnext on complexes.

## Build Architecture and Retirement

In accordance with maintainer Decision 4 (C04):
- `bng_nfcore2` is retired from the default `bionetgen_core` interface library in `cpp/CMakeLists.txt`.
- `bng_nfcore2` is retained as an in-tree static library solely for the test oracles (`test_nfcore2_parity` and `bng3_nfcore2_reference_tests`).
- `lowerPatternToNFsim` is preserved for NFcore input lowering.
- `method="nf"` defaults to production NFcore, with explicit `method="nfcore"` producing identical deterministic trajectories matching pinned native NFsim within 4.0-sigma.
- Prototype `method="nfcore2"` remains contained and refuses execution fail-closed with `ValueError`.

## Release Acceptance Checks

1. `release-engine-consolidation`: Verifies that every NFcore2 capability maps to passing tests in NFcore2 parity and NFnext architecture contracts with preserved fixtures, and verifies production NFnext execution on isomerization, compartments, MoveConnected, and non-root transformations.
2. `release-nf-default`: Verifies that `method="nf"` defaults to production NFcore, explicit `method="nfcore"` selects NFcore with identical output on deterministic seeds, and both match analytical continuous-time Markov chain laws and pinned native NFsim within 4.0-sigma.
3. `release-obligation-149`: Verifies the closure record, schema compliance, workload ownership documentation, retirement of `bng_nfcore2` from `bionetgen_core`, and negative containment (fail-closed refusal of `method="nfcore2"` and invalid methods).
