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

The following are test-reference mappings, not demonstrated production capability
transfers. In particular, `future_contract` unit checks and lowering tests cannot
qualify production compartment or MoveConnected execution, which NFnext still
refuses. NFcore2 remains linked into `bionetgen_core`; retirement and default
promotion required by #149 are not complete. Keeping NFcore as default is the
correct interim behavior, not satisfaction of the final promotion gate.

Candidate mappings retained for follow-up:

1. **Reversible Isomerization & Transformation**: Validated in `tests/cpp/test_nfcore2_parity.cpp` (case 1) and mapped to NFnext transformation contract `tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp` and `test_execution_boundary.cpp`.
2. **Compartment Production & Multi-Compartment Binding**: Validated in `test_nfcore2_parity.cpp` (cases 2, 6, 8) and mapped to `tests/architecture_contracts/nfnext/future_contract/test_compartment_rate_contract.cpp`.
3. **Molecule vs. Species Compartment Resolution**: Validated in `test_nfcore2_parity.cpp` (case 3) and mapped to `tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp`.
4. **MoveConnected Relocation**: Validated in `test_nfcore2_parity.cpp` (cases 4, 5) and mapped to `test_transformations_contract.cpp`.
5. **Compartment Placement Validation & Refusal**: Validated in `test_nfcore2_parity.cpp` (case 7) and mapped to `test_compartment_rate_contract.cpp`.
6. **Non-Root Pattern Transformations**: Validated in `test_nfcore2_parity.cpp` (cases 9-14: state change, molecule deletion, binding, molecule creation, bond deletion, combined state/bond changes) and mapped to `test_transformations_contract.cpp`.

## Acceptance limits

`release-engine-consolidation` currently runs the existing NFcore2/architecture
executables and checks test-reference presence. `release-nf-default` checks the
current NFcore default and explicit route, not full-corpus promotion readiness.
`release-obligation-149` checks metadata and containment. Passing these bounded
checks does not satisfy the complete live work clauses or authorize #149 closure.

## Intended release acceptance checks (not yet fully demonstrated)

1. `release-engine-consolidation`: Verifies that every NFcore2 capability maps to passing tests in NFcore2 parity and NFnext architecture contracts with preserved fixtures.
2. `release-nf-default`: Verifies that `method="nf"` defaults to production NFcore, explicit `method="nfcore"` selects NFcore with identical output on deterministic seeds, and both match analytical continuous-time Markov chain laws and pinned native NFsim within 4.0-sigma.
3. `release-obligation-149`: Verifies the closure record, schema compliance, workload ownership documentation, and negative containment (fail-closed refusal of `method="nfcore2"` and invalid methods).
