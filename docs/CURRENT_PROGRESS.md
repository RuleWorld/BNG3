# BNG3 current progress

**Audited:** 2026-09-15
**Repository:** `RuleWorld/BNG3`
**Branch:** `codex/bng3-convergence-continuation-20260915`
**Status:** implementation and validation checkpoint; convergence and release remain incomplete

This is the live status page for the combined BNG3 migration tree. The older
IR migration reports and formalization reports retained in the repository are
historical inputs and provenance records; their embedded prose is not a new
execution instruction.

## Offline convergence pass — 2026-09-17

A restricted-container static audit and low-risk fix pass. No build, no
network, and no Git checkout were available, so **nothing in this pass is
build-verified**. Full detail, including the gap table, changed-files table,
and deferred validation commands, is in
[`OFFLINE_CONVERGENCE_PASS_2026-09-17.md`](OFFLINE_CONVERGENCE_PASS_2026-09-17.md).

Implemented, awaiting build validation:

- **One nauty build (WO-1b).** `cpp/nfsim/nauty24/` is deleted; `nfsim_core`
  links the shared `nauty` target. The trees were identical modulo the
  documented `set`->`nset` rename, and unifying on the NFsim variant also
  fixed a missing MSVC `HAVE_SYSTYPES_H` guard. Locked by
  `tests/python/test_single_nauty_contract.py` (10/10 locally).
- **`rint` corrected in both expression engines.** BNG2 defines it as
  `floor(x + 0.5)`; the shared evaluator used `std::rint` (half-to-even) and
  NFsim used `std::round` (half-away-from-zero), so the two disagreed with
  each other and each disagreed with the oracle. Oracle values were produced
  by executing `legacy/perl/Perl2/Expression.pm:74` directly.
- **One builtin table** (`cpp/ast/ExpressionBuiltins.hpp`) consumed by both
  the shared evaluator and the direct-NFsim gate. Closed the `sign`/`log`
  asymmetry, admitted `avg` (removing a false XML fallback), and made the gate
  case-sensitive to match the ExprTk shim.
- **`setOption` validation** (`cpp/ast/ModelOptions.hpp`) at the single
  `Model::setOption` seam. `SpeciesLabel=Quasi` and invalid option values now
  fail closed instead of being stored and ignored; corpus-present options
  still load.
- **Observable counting modes implemented** (`engine/ObservableProjection.cpp`).
  `MoleculesObservables`/`SpeciesObservables` did not exist in BNG3 at all, so
  a model requesting `CountUnique` silently received `CountAll` values. The two
  keys are not the same operation: Molecules `CountUnique` divides each match
  count by the pattern's automorphism number, while Species `CountUnique`
  short-circuits the term loop so a species counts once. BNG2 has the symmetry
  correction commented out on the Species branch. The Molecules division is
  asserted exact rather than truncated.
- **Per-stage direct-NFsim fallback reasons**, surfaced at both call sites and
  as `Result.direct_unavailable_reason`.

**Second pass, same day.** NFsim's separate expression engine is gone: the
`mu::Parser` interface is retained but backed by
`bng::parser::parseExpression` + `bng::eval::evaluate`, and ExprTk,
`NFSIM_USE_EXPRTK`, and the root ExprTk `FetchContent` block are removed
(WO-3 and WO-3b). The shim's underscore-remapping and logical-operator
rewriting layers were deleted as unnecessary against the BNGL lexer and
`Expression`'s native operators. Expect a performance regression on
function-heavy models: this is a tree walk where ExprTk compiled. `HNauty.hpp`
is marked UNUSED-reference, `SpeciesLabel=Quasi` is accepted-but-warned as
UNUSED, and `python/bionetgen/modelapi/` is marked legacy with its live
default-path dependencies recorded — it is still imported by
`bionetgen/__init__.py` and cannot be deleted yet. The nested
local/composite direct-NFsim refusal is root-caused but deliberately NOT
fixed; see the addendum.

Remaining implementation gaps are not low-hanging: the direct-NFsim refusals
that are still open are energy lowering (out of scope), population maps
(fail-closed by design and routed through the hybrid backend), and nested
local/composite function mapping, which is a semantic mismatch rather than a
missing translation. `SpeciesLabel=Quasi` would mean adding a second
canonicalization mode. `cpp/core/HNauty.hpp` still has zero callers pending
the open largest-vs-canonical-form maintainer decision.

The chief regression risks for the next CI run are the **MSVC matrix** (the
merged nauty header changes `HAVE_SYSTYPES_H` under `_MSC_VER`) and the
**strict validation corpus** (`setOption` can now throw).

## Experimental nonequilibrium energy layer — barrier patterns and driving reservoirs

Added but **gated off by default**. `begin barrier patterns` and `driven_by(W)`
are accepted at the language surface and lowered through the AST, the compiled
IR, both NFsim input paths, and XML serialization, implementing

```
k_f = exp[-(Ea + B + phi       * (dG - W)) / RT]
k_r = exp[-(Ea + B + (phi - 1) * (dG - W)) / RT]
```

`BNG_NFSIM_GENERAL_ENERGY` must be set for any backend to accept either
construct; unset, both report `Unsupported` for the network compiler and for
NFsim. The gate is not a convenience switch — canonical NFsim and BNG2 do not
implement these semantics, so the differential-parity evidence BNG3 normally
requires cannot be produced yet.

State of validation, stated precisely. The authoring environment had no network
access, so the FetchContent build was never run and nothing has been linked or
executed through a real parse.

- **Executed and passing** (`tests/energy/standalone/run_checks.sh`, C++17
  compiler only): the thermodynamic analysis including insertion-order
  determinism; barrier keying, accumulation and canonical key round-trip; a
  300-combination sweep proving the NFsim and network energy conventions
  describe the same kinetics, plus a demonstration that the reverse-direction
  work negation is load-bearing; the accepted/rejected surface syntax; and the
  full post-parse lowering with all eight of its fail-closed paths.
- **Type-checked only** (`-fsyntax-only` against real headers, never run): the
  AST, capability, compiled-IR, XmlWriter, NFcore energy and NFsim input
  adapters. `BarrierCompiler`'s graph-diff classification falls here, because
  `PatternGraph` can only be built through ANTLR parse contexts — that is the
  largest remaining gap.
- **Not checked at all** (need the real ANTLR4 runtime): `BNGAstVisitor.cpp`,
  `NetWriter.cpp`, `NFinput.cpp`, and the parse-dependent contract fixture.

The compact `EnergyRxnClass` evaluator is disabled for any rule with nonzero
barrier or work; those rules take the materialized Sekar expansion.

Design, fail-closed inventory, and architecture table:
[`docs/nonequilibrium_energy.md`](nonequilibrium_energy.md).

## Current continuation checkpoint — 2026-09-15

The continuation is based on public `main` at
`bad50c9cd659efd893e47d8b88bcfebaa4ebc2ba`. Its purpose is to make the
direct-NFsim and NFnext evidence auditable and to merge the dated
continuation note into the current documentation set.

Direct NFsim validation now preserves and asserts the runtime
`construction_path`: the compatibility leg must be `in-memory-xml`, while the
direct leg must be `direct` with XML fallback permission removed. Required
compiled backends and independent oracles fail closed when unavailable.
Source-tree ensemble workers receive both the repository root and `python/`
on `sys.path`, and every ensemble member must use direct construction. The
hosted parity contract covers the fixed-seed `motor` and `tlbr` endpoint
fixtures as well as the seeded `simple_system` ensemble.

The typed Lean example and the production C++ contract independently exercise
the same bounded rule, `A(x~u) + B(y) -> A(x~p!1).B(y!1) k`. The C++ contract
crosses BNGL parser -> `bng::compile::CompiledModel` ->
`nfnext::lowerFromBioNetGen`, checking distinct-reactant molecularity, a state
update, and a new bond. This is correspondence evidence for one NFnext slice,
not complete Lean kernel verification or backend equivalence. Population maps
remain fail-closed for direct NFsim and are routed through the hybrid backend.

The local code checkpoint immediately before this documentation merge is CTest
`308/308`, strict validation `71/71` with zero failures/errors/skips, action
contracts `6/6`, CI-contract tests `26 passed`, energy tests `66 passed`,
independent NFsim `10 passed`, Lean static validation `36` files, NFnext
contracts `18/18`, and passing Black, Ruff, provenance, corpus, and
exception-ledger checks. The local Lean kernel remains unavailable because
Lean/Lake/Elan are not installed. Final hosted status is recorded from
exact-head `gh` readback after the documentation push.

## Imported material

The cumulative import retained the three supplied snapshots, with the
2026-09-14 source tree taking precedence where snapshots overlap:

- `BNG3-Lean-formalization-latest.zip` — SHA-256
  `460f89c4380bde3a6f52377397d32ca098efc19c8fdbf675eeac33aa6bb5d530`
- `BNG3-ir-migration-everything-so-far-2026-09-11.zip` — SHA-256
  `31342054fc902b7ed3777be799a9a5d6dc5c5534ff3aa27afe8f6f556156e5e7`
- `BNG3-ir-migration-current-2026-09-14.zip` — SHA-256
  `523219fa6cd05928830482d74e88633a44cf2f53e6944c1fc72cd144229bfbac`

Archive reports, source locks, manifests, and provenance records remain in
place. Generated Lean build output is not part of the import.

## Previous full-corpus CI, Windows compatibility, and repository-organization checkpoint — 2026-09-15

The preceding semantic validation and documentation/Windows repair commits
closed the former full-corpus
checkpoint closes the former full-corpus
reference exclusions: independent BNG2 `.net` references now cover the
previously missing network fixtures, and
`tests/validation/validation_manifest.json` routes the six action-focused
fixtures through explicit output contracts in `scripts/validate_actions.py`.
The native reader also has a narrow, fail-closed legacy structured-SBML
`atomize=>1` contract for the `plain2` fixture, and reverse local-rate scope is
preserved during rule expansion.

The live local evidence for that semantic commit is:

| Gate | Result |
| --- | --- |
| Native CTest | `308/308` passed |
| Full validation corpus | `71 passed, 0 failed, 0 errors, 0 skipped` |
| Action-output contracts | `6/6` passed |
| CI-contract tests | `26 passed` |
| Energy Python tests | `66 passed` |
| Black, Ruff, corpus, provenance, and exception-ledger checks | passed |

The former exclusion ledger is closed with empty PR and weekly profiles. The
historical migration reports and text metadata are organized under
[`archive/reports/ir-migration-2026-09-14/`](archive/reports/ir-migration-2026-09-14/);
obsolete patch snapshots and duplicate package wrappers were removed after
their changes were applied. Handoff documents remain historical provenance,
while this page and the convergence checklist are the live status sources.

The exact-head hosted CI run
[`34896645707`](https://github.com/RuleWorld/BNG3/actions/runs/34896645707)
completed successfully, including the Windows/MSVC matrix, full corpus on
Ubuntu/macOS/Windows, package smoke, and integration tests. Cross-tool parity,
Lean, CodeQL, and formatting runs also completed successfully. The preceding
hosted head exposed a
Windows/MSVC-only ANTLR failure: `NFinput.cpp` could enter the runtime through
generated visitor headers before the translation-unit compatibility include.
Those generated headers now include `parser/antlr_compat.hpp` themselves, and
the current local rebuild passes. The scheduled NFsim historical job and
release-only artifact/publish jobs are conditionally skipped by their event
guards; the full validation corpus has no skipped fixtures and the exclusion
ledger is empty. Broader backend equivalence, release qualification, and
convergence are still incomplete.

The follow-up PR head `9efa0e9df8903ee616437f8555906fcfdda4c762` also passed
hosted PR CI run
[`34971571944`](https://github.com/RuleWorld/BNG3/actions/runs/34971571944),
including the full no-exclusion corpus on Ubuntu, Windows, and macOS. The
auxiliary manual-dispatch run `34971595435` was canceled before its wheel jobs
started so wheel validation remains deferred until merge. The first main-push
CI run after the merge is the authoritative wheel result for this repair.

## Wheel CI repair checkpoint — 2026-09-15

The main push run
[`34901298982`](https://github.com/RuleWorld/BNG3/actions/runs/34901298982)
exposed two independent wheel-environment failures. The macOS x86_64 build
used deployment target 10.9, which is below the macOS availability of the
ANTLR runtime's `std::optional::value()` and `std::shared_mutex` usage. The
manylinux2014 wheel test resolved NumPy 2.5.3 from source, where the image's
GCC 10.2.1 is below NumPy's GCC 10.3 minimum; no compatible manylinux2014
binary was available for that target.

The follow-up repairs both `.github/workflows/ci.yml` and
`.github/workflows/release.yml`: cibuildwheel is pinned to 4.2.1, macOS
builders use their native runner architecture with deployment targets 10.13
(macos-13/x86_64) and 11.0 (macos-14/arm64), and Linux wheels use
`manylinux_2_28` so current NumPy test dependencies resolve to binary wheels.
The CI workflow also exposes a manual-dispatch path for the wheel matrix so
this repair can be validated on the exact follow-up head before release
qualification. The auxiliary hosted rerun is paused until merge; this
checkpoint makes no wheel or release-success claim until the post-merge main
matrix is terminal-success.

## Repairs in this checkpoint

- Retain the lowering context owned by generated native graphs so graph node
  and state-type references remain valid after network generation returns.
- Parse native unbound markers and preserve NFcore2 equivalent-component
  reaction-center semantics.
- Repair compiled NFsim handling for dynamic expressions, time and reactant
  references, function dependencies, reversible Arrhenius/function-product
  rates, and symmetric molecule-observable embeddings.
- Preserve model-defined `_Na` parameters at the compiled NFsim boundary so
  direct AST construction and the XML compatibility path use identical values.
- Repair ODE observable references in functional rates and add a pinned PR
  workflow for Lean kernel, smoke, and NFnext contract checks.
- Preserve reverse-direction local-rate scope and accept legacy action argument
  lists for hybrid, visualization, and network-writing actions.
- Close the validation exclusions with independent network references and
  explicit action-output contracts; remove the old skip arguments from PR and
  weekly validation jobs.
- Apply the Windows SDK macro compatibility guard to every generated ANTLR
  parser/visitor header, covering direct include paths used by the legacy NFsim
  adapter as well as the modern parser targets.

## Verified gates

| Gate | Current evidence |
| --- | --- |
| Native CTest | `308/308` passed after the current rebuild |
| Python package tests | `399 passed, 28 skipped` excluding SBML import; isolated SBML test `1 passed` |
| Validation smoke | `4 passed, 14 skipped, 178 deselected`; skips are explicit environment/reference conditions |
| Export validation | `12 passed, 184 deselected` |
| BNG2 structural differential | `5/5` selected models passed against locked source revision `e0a5c6d9e6c4730f66102e48d0d0a598337083e7` |
| BNG2 broad validation subset | `11 passed, 89 skipped, 96 deselected`; this is not full Tier-P qualification |
| Full validation corpus | `71/71` passed with `0` failures, `0` errors, and `0` skips |
| Explicit action-output validation | `6/6` passed for the former action-focused exclusions |
| NFsim direct/XML | `10 passed` for the selected independent NFsim gate: four direct/XML checks, four 200-run ensemble comparisons, and two fixed-seed endpoint checks |
| Lean/NFnext local checks | static validation `36` files, NFnext contracts `18/18`; local kernel check unavailable because `lean`, `lake`, and `elan` are not installed |
| Provenance/corpus/ledger | provenance validation, corpus validation/generation check, and zero-active-exception ledger all pass |

The independent NFsim oracle is built from source revision
`a6f9fa945c9d6e1e122e789c952260112c93f157`, binary SHA-256
`c0974ad71a88938ed3f2ed096878d53aec14e946c91e28e1bc644759db1da3b4`.
The independent BNG2 source revision used for the structural subset is
`e0a5c6d9e6c4730f66102e48d0d0a598337083e7`.

These results are exact-head evidence for the listed fixtures and commands.
They do not establish complete corpus parity, backend equivalence, release
readiness, or convergence.

## Remaining plan of action

1. Expand the independent BNG2/NFsim differential matrices over the locked
   corpus, replacing environment-induced skips with runnable oracle coverage
   where possible and recording any maintainer-approved dispositions.
2. Continue the direct NFsim adapter audit for dynamic rates/functions, energy,
   observables, population maps, and unsupported constructs; add a focused
   fixture and oracle result for each newly supported semantic slice.
3. Triage remaining native/Python/parity gaps by source-integration failure
   versus semantic mismatch, preserving fail-closed behavior and the current
   exception ledger.
4. Connect the typed Lean reference to a small real C++/NFIR lowering slice,
   then promote NFnext contracts only after backend-equivalence evidence exists.
5. After merge, track the main-push wheel matrix on the exact merge head, then
   rerun clean native, Python, oracle, formal, packaging, and release gates
   before any convergence or release claim.

The authoritative completion criteria remain
[`BNG3_CONVERGENCE_DONE_CHECKLIST.md`](BNG3_CONVERGENCE_DONE_CHECKLIST.md),
with repository working rules in [`../AGENTS.md`](../AGENTS.md).
