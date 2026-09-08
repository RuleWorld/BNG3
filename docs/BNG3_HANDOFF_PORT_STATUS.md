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
- The staged semantic layer now has typed symbols/rate-law references, structured
  feature diagnostics, an immutable `compile::Document` protocol split, and a
  value-like `compile::Pattern` with explicit BNGcore and NFsim
  `TemplateMolecule` lowerings. The NFsim adapter validates names, states,
  bonds, compartments, and disconnected components before allocating runtime
  templates; backend capability preflight now rejects population maps before
  direct NFsim construction, and compiled function/rate expressions preserve
  typed lexical-local references. Namespace-specific dense IDs and semantic
  pattern equality are covered by contracts; the legacy `PatternDescriptor`
  spelling remains a compatibility alias.
- The latest BioNetGen native isolated parallel batch feature from source
  revision `d132702da784237aa10576c7373f691ffdc05071` is ported into the
  BNG3 CLI as `--parallel`/`--jobs`, with private staged model directories,
  deterministic job reporting, and child-failure propagation.
- The validated NFsim single-reactant product-collection fast path from
  source revision `7d0f5bf954a11a90167861edac016697cb66d139` is ported with
  a behavior regression test.
- The energy validation harness, fixtures, Python gates, C++ contracts, architecture inventories, and CI hooks are under `tests/energy/` and `tests/architecture_contracts/`.
- Future and unavailable contracts remain opt-in or classified as `blocked-api`, `design-only`, `reference`, or `auxiliary`; empty future bodies are inventory findings, not passing tests.
- The expanded goal keeps five broader ceilings explicit and fail-closed:
  arbitrary internal graph expressions; general local-function/DOR evaluation;
  compartment hierarchy/species-carrying moves; conditional deletion; and
  independent full NFsim/BNG2 parity. These are tracked as open contracts,
  not implied by the bounded semantic checkpoint.

## Evidence at this checkpoint

- The direct-port build completed after adapting the BNG3 APIs.
- Full Release/Ninja CTest passed all `264/264` tests, including `58/58`
  tests under the exact `energy` label, one NFcore2 and one NFnext
  architecture-reference test, and the sanitizer smoke test.
- The imported energy Python self-tests passed `66/66` under the repository's
  intended `PYTHONPATH=tests/energy` environment.
- The full BNG3 Python regression suite passed `340/340` with `27` expected
  skips under the base Anaconda 3.14 environment; the narrower `exth17`
  environment is missing optional collection dependencies.
- The isolated batch CLI tests passed `2/2`, covering private generated
  outputs and child failure propagation.
- The architecture inventory audit is required to pass before each checkpoint; it verifies that every imported C++ contract is classified and that executable dispositions name a CMake target.
- The existing BNG3 Python regression suite and the imported Python harness self-tests are separate gates. They must be rerun after later source or build-system changes.

## Required next gates

1. Exercise NFcore2 and NFnext reference targets independently, then add
   semantic fixtures for matcher, transformation, observables, and cache
   behavior.
2. Replace adapter-level smoke checks with independent NFsim and BNG2 oracle
   comparisons, including seeded trajectories, rates, observables, and failure
   classifications.
3. Add real Rasi/uORF fixtures only when the missing source and expected outputs
   are available; keep those contracts RED until then.
4. Run sanitizer and performance checks with recorded toolchain, input, timing,
   memory, and correctness evidence.
5. Publish only coherent validated checkpoints. Do not describe this branch as
   NFsim replacement, Rasi parity, or BNG3 convergence until those independent
   gates pass.

The protected grammar-only edit in `docs/BNG3_INTEGRATION_PLAN.md` is preserved while this port proceeds.
