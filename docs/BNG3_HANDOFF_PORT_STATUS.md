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
- Root-local NFsim introspection and conservative dependency collection are implemented in the existing NFsim classes. Unsupported richer topology and broader transport cases fail closed; bounded graph matching, synthesis, root-local moves, and species-carrying `MoveConnected` execute directly. Explicit rate bindings resolve reactant counts, connected-species molecule counts, and positive compartment volumes.
- Symmetric graph automorphisms now lower through the native reader as finite equivalent-site candidate sets. The matcher assigns candidates injectively, checks state and occupancy constraints, and verifies reciprocal bonds; malformed candidate or partner payloads remain rejected.
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
- The latest opt-in NFsim execution-profiler lineage from source commits
  `33e9c9b`, `35c7b88`, `8c737fb`, and `2ce8449` is ported into the embedded
  NFsim runtime. `-profile [filename]` emits the source-compatible v4
  tab-separated report; phase, reaction, membership, template, connectivity,
  binding, transformation, product, observable, mapping, and component-reuse
  counters are instrumented. This is diagnostic evidence only, with profiling
  disabled by default and no optimization or parity claim.
- The energy validation harness, fixtures, Python gates, C++ contracts, architecture inventories, and CI hooks are under `tests/energy/` and `tests/architecture_contracts/`.
- Future and unavailable contracts remain opt-in or classified as `blocked-api`, `design-only`, `reference`, or `auxiliary`; empty future bodies are inventory findings, not passing tests.
- The expanded goal keeps five full-parity ceilings explicit and fail-closed:
  richer internal graph expressions beyond the now-supported finite symmetric
  automorphism slice; full local-function/DOR evaluation;
  volume-aware compartment scaling and transport; complete deletion semantics;
  and independent full NFsim/BNG2 parity. Bounded direct contracts now cover
  graph state/bond/compartment constraints, finite symmetric automorphisms,
  expression bindings, hierarchy
  metadata, species-carrying `MoveConnected`, explicit volume/transport
  validation, and conditional deletion; these
  do not imply the broader ceilings.
- An opt-in `BUILD_BNGSIM_ADAPTER` path maps a generated BNG3 network directly
  into an external BNGsim `NetworkModel`, with strict dependency, observable,
  index, and rate-reference checks. It remains OFF by default; this checkout
  has no default BNGsim dependency, so adapter tests run only in an explicitly
  configured external build and make no broad BNGsim parity claim.

  The adapter spike was also built and tested against BNGsim commit
  `49dc939035f5a272da663f8c9586e3c9f0e1c041` in an isolated build. Its focused
  suite passed `8/8`, covering direct mapping, fail-closed composite rates,
  functional rates, unsupported semantic surfaces, pattern-weighted
  observables, inline and absolute-file TFUN rates, relative-TFUN provenance
  rejection, and bounded CVODE decay parity. BNGsim's own managed suite passed
  `6/6`; the optional BNG3 build passed `278/278` including the adapter tests.
  This remains feasibility evidence, not a solver-selection decision.
  The scope and non-selection decision are recorded in
  `docs/adr/0002-bngsim-adapter-scope.md`.
- Python now exposes deterministic, source-free BNGIR JSON v0.1 through
  `BioNetGenModel.to_bngir()`, `to_bngir()`, `from_bngir()`, and
  `semantic_equal()`. The published schema is
  `provenance/schemas/bngir-0.1.schema.json`; protocol actions retain their
  model versus simulation scope, while population-map reconstruction remains
  explicitly fail-closed. Its focused Python contract suite passes `8/8`.

## Evidence at this checkpoint

- The direct-port build completed after adapting the BNG3 APIs.
- Full Release/Ninja CTest passed all `276/276` tests, including `58/58`
  tests under the exact `energy` label, one NFcore2 and one NFnext
  architecture-reference test, and the 14 native-port semantic tests.
  The NFcore2 reference suite passed 431/431; the native-reader suite
  passed 16 cases and 152 assertions.
- The imported energy Python self-tests passed `66/66` under the repository's
  intended `PYTHONPATH=tests/energy` environment.
- The fresh current-main BNG3 Python regression suite passed `348` tests with
  `27` expected skips under the base Anaconda 3.14 environment.
- The validation smoke gate passed `4` checks with `14` visible skips; the
  skipped parity checks require the unavailable legacy `run_network` helper
  or an independently built native NFsim oracle.
- Current ASan/UBSan focused checks passed the NFcore2 reference (`431/431`)
  and ODE/observable/solver regressions (`10/10`).
- BNG2 `master` was rebuilt from merged main revision `e0a5c6d9` and its CTest
  suite passed `81/81`.
- The isolated batch CLI tests passed `2/2`, covering private generated
  outputs and child failure propagation.
- The architecture inventory audit is required to pass before each checkpoint; it verifies that every imported C++ contract is classified and that executable dispositions name a CMake target.
- The existing BNG3 Python regression suite and the imported Python harness self-tests are separate gates. They must be rerun after later source or build-system changes.
- A pinned native NFsim oracle was built in an isolated temporary tree from
  source revision `a6f9fa945c9d6e1e122e789c952260112c93f157`. The NF validation
  gate passed `4/4` 200-run stochastic comparisons, `4/4` direct-versus-
  in-memory-XML trajectory comparisons, and `2/2` fixed-seed endpoint checks.
- Against the 41 checked-in DAT `.net` fixtures with resolvable BNG3 sources,
  the bounded comparison passed `36/41`; five fixtures require unavailable
  legacy actions/input files or do not emit a network. This is evidence for
  the available subset, not release-level BNG2 parity.

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
