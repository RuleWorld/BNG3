# Archived Prototype: NFcore2

> **Archived historical prototype:** NFcore2 was an exploratory network-free engine prototype consolidated into **NFnext** (`cpp/nfnext/`) under [Maintainer Decision 4 (`docs/DECISIONS.md`)](../../docs/DECISIONS.md) and issue [#149](https://github.com/RuleWorld/BNG3/issues/149).

## Status

- **Not shipped in BNG3 production artifacts:** `bng_nfcore2` is excluded from `bionetgen_core`, wheels, sdists, and standalone CLI binaries (`bng_cpp`, `NFsim`).
- **Fail-closed at the public API:** `model.simulate(method="nfcore2")` raises `ValueError` explicitly directing callers to `method="nf"` (NFnext) or `method="nfcore"` (embedded NFsim).
- **Retained only for historical parity and architecture contracts:** `bng_nfcore2` is compiled only when `BUILD_TESTS=ON` so that `tests/cpp/test_nfcore2_parity.cpp`, `tests/architecture_contracts/nfcore2/`, and `tests/architecture_contracts/test_native_reader.cpp` continue to verify the preserved capability fixtures.

## What Remained Active in `cpp/nfsim/`

The NFsim pattern-lowering helper (`nfsim_pattern_lowering.{hh,cpp}`) is actively used by `nfsim_core` (`NFinput_fromCompiled.cpp`, `NFinput_reactions_fromCompiled.cpp`, `NFinput_fromAst.cpp`) and was moved into `cpp/nfsim/NFinput/` rather than archived here.

## Capability Destination Map to NFnext

All validated NFcore2 capabilities map to production NFnext (`cpp/nfnext/`):

| NFcore2 capability | Preserved NFcore2 fixture | Production NFnext contract |
|---|---|---|
| Reversible isomerization & elementary transforms | `tests/cpp/test_nfcore2_parity.cpp` | `tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp` |
| Compartment products & multi-compartment binding | `tests/cpp/test_nfcore2_parity.cpp` | `tests/architecture_contracts/nfnext/future_contract/test_compartment_rate_contract.cpp` |
| Molecule compartment overrides | `tests/cpp/test_nfcore2_parity.cpp` | `tests/architecture_contracts/nfnext/test_bng_lowering_bridge.cpp` |
| `MoveConnected` complex relocation | `tests/cpp/test_nfcore2_parity.cpp` | `tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp` |
| Compartment placement refusal boundaries | `tests/cpp/test_nfcore2_parity.cpp` | `tests/architecture_contracts/nfnext/future_contract/test_compartment_rate_contract.cpp` |
| Non-root pattern transformations | `tests/cpp/test_nfcore2_parity.cpp` | `tests/architecture_contracts/nfnext/future_contract/test_transformations_contract.cpp` |
