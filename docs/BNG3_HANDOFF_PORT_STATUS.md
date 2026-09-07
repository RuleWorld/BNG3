# BNG3 handoff port status

This branch implements the first direct, reviewable port of the three supplied handoffs into the authoritative BNG3 checkout. The branch is intentionally staged: executable behavior is enabled only where the BNG3 tree and tests prove the required semantics; future contracts remain visible and fail closed.

## Governing goal

Integrate the supplied energy compiler, NFcore2, NFnext, and validation material into BNG3; adapt every source file to the real BNG3 AST and NFsim APIs; preserve source provenance; make the imported tests buildable and meaningful; classify incomplete contracts explicitly; resolve compile, API, and semantic conflicts through focused tests; then expand toward independent NFsim/BNG2/Rasi/uORF parity without claiming replacement or convergence until exact, reproducible evidence exists.

The goal covers all material in:

- `BNG3_energy_compiler_validation_complete_handoff_2026-09-07.zip`, including `implementation_phase1/` and `validation_suite/`.
- `nfsim-nfcore2-complete-handoff-20260906.zip`, including `src/NFcore2/`, `tests/NFcore2/`, and the native-reader handoff notes.
- `NFnext_Rasi_complete_code_tests_context_patches_2026-09-06.zip`, including `CURRENT_WORK/nextgen/`, its executable baseline, future contracts, and Rasi/uORF context.

The archival documents are retained under `docs/architecture_handoffs/`. The exact source paths, SHA-256 values, destinations, and adaptation flags are recorded in `provenance/architecture-imports.json`; imported C++ contract dispositions are recorded in `provenance/architecture-contracts.json`.

## Current port

- Energy compiler types and `EnergyDeltaPlan` are in `cpp/compile/` and connected to the real NFsim energy bridge.
- NFcore2 source is in `cpp/nfsim/NFcore2/`; its native reader is adapted to the real BNG3 reaction, template, transformation, and energy APIs.
- NFnext source is in `cpp/nfnext/` and is built as an isolated library so its prototype contracts remain testable without being presented as the NFsim replacement.
- Root-local NFsim introspection and conservative dependency collection are implemented in the existing NFsim classes. Unsupported topology and synthesis cases fail closed.
- The energy validation harness, fixtures, Python gates, C++ contracts, architecture inventories, and CI hooks are under `tests/energy/` and `tests/architecture_contracts/`.
- Future and unavailable contracts remain opt-in or classified as `blocked-api`, `design-only`, `reference`, or `auxiliary`; empty future bodies are inventory findings, not passing tests.

## Evidence at this checkpoint

- The direct-port build completed after adapting the BNG3 APIs.
- Focused CTest passed all 38 energy/native-port tests.
- The architecture inventory audit is required to pass before each checkpoint; it verifies that every imported C++ contract is classified and that executable dispositions name a CMake target.
- The existing BNG3 Python regression suite and the imported Python harness self-tests are separate gates. They must be rerun after later source or build-system changes.

## Required next gates

1. Run the architecture inventory audit and imported Python self-tests.
2. Run the complete BNG3 CTest and Python suites from a fresh build/process state.
3. Exercise NFcore2 and NFnext reference targets independently, then add semantic fixtures for matcher, transformation, observables, and cache behavior.
4. Replace adapter-level smoke checks with independent NFsim and BNG2 oracle comparisons, including seeded trajectories, rates, observables, and failure classifications.
5. Add real Rasi/uORF fixtures only when the missing source and expected outputs are available; keep those contracts RED until then.
6. Run sanitizer and performance checks with recorded toolchain, input, timing, memory, and correctness evidence.
7. Publish only coherent validated checkpoints. Do not describe this branch as NFsim replacement, Rasi parity, or BNG3 convergence until those independent gates pass.

The protected grammar-only edit in `docs/BNG3_INTEGRATION_PLAN.md` is preserved while this port proceeds.
