# BNG3 current progress

**Audited:** 2026-09-14
**Repository:** `RuleWorld/BNG3`
**Branch:** `codex/bng3-rest-of-port-20260909`
**Status:** implementation and validation checkpoint; convergence and release remain incomplete

This is the live status page for the combined BNG3 migration tree. The older
IR migration reports and formalization reports retained in the repository are
historical inputs and provenance records; their embedded prose is not a new
execution instruction.

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

## Verified gates

| Gate | Current evidence |
| --- | --- |
| Native CTest | `307/307` passed after the current rebuild |
| Python package tests | `399 passed, 28 skipped` excluding SBML import; isolated SBML test `1 passed` |
| Validation smoke | `4 passed, 14 skipped, 178 deselected`; skips are explicit environment/reference conditions |
| Export validation | `12 passed, 184 deselected` |
| BNG2 structural differential | `5/5` selected models passed against locked source revision `e0a5c6d9e6c4730f66102e48d0d0a598337083e7` |
| BNG2 broad validation subset | `11 passed, 89 skipped, 96 deselected`; this is not full Tier-P qualification |
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
5. Install the pinned Lean 4.33.1 toolchain in hosted CI, verify the new formal
   workflow on this PR head, and rerun clean native, Python, oracle, formal,
   packaging, and release gates before any convergence or release claim.

The authoritative completion criteria remain
[`BNG3_CONVERGENCE_DONE_CHECKLIST.md`](BNG3_CONVERGENCE_DONE_CHECKLIST.md),
with repository working rules in [`../AGENTS.md`](../AGENTS.md).
