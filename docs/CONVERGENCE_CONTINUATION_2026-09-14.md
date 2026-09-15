# Convergence continuation note

This dated continuation note has been merged into the current operational
documentation. It is retained as a stable pointer so links from the supplied
archive remain useful; the live facts belong in the documents below.

## Canonical homes

- [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md) — current implementation,
  local evidence, and remaining work.
- [`BNG3_CONVERGENCE_DONE_CHECKLIST.md`](BNG3_CONVERGENCE_DONE_CHECKLIST.md) —
  auditable completion criteria and exact-head evidence.
- [`CI_PARITY.md`](CI_PARITY.md) — independent-oracle contracts and hosted CI
  parity rules.
- [`BNG3_HANDOFF_PORT_STATUS.md`](BNG3_HANDOFF_PORT_STATUS.md) — imported
  handoff scope and implementation dispositions.
- [`BNG3_INTEGRATION_PLAN.md`](BNG3_INTEGRATION_PLAN.md) — backlog, phases,
  and definition of done.
- [`../formal/lean/VALIDATION.md`](../formal/lean/VALIDATION.md) — Lean and
  NFnext validation boundary.

## Merged continuation scope

The continuation added three related evidence and documentation themes:

1. Direct NFsim checks now record `construction_path`, require the XML leg to
   be `in-memory-xml` and the direct leg to be `direct`, clear XML fallback
   permission before the direct leg, anchor repository imports for spawned
   source-tree workers, and fail closed when a required compiled backend or
   independent BNG2/NFsim oracle is unavailable. Hosted parity includes the
   fixed-seed `motor` and `tlbr` endpoint contracts in addition to the seeded
   `simple_system` ensemble.
2. The Lean example and a production C++ contract cross-check the same small
   rule, `A(x~u) + B(y) -> A(x~p!1).B(y!1) k`, through typed NFnext lowering.
   The C++ side exercises BNGL parsing, `CompiledModel`, and
   `nfnext::lowerFromBioNetGen`, checking distinct-reactant molecularity, a
   state update, and bond creation. This is a bounded correspondence slice,
   not complete backend equivalence.
3. Population-map behavior remains fail closed for direct NFsim and is routed
   through the hybrid population backend; no unsupported semantics are
   inferred from a green structural contract.

These themes are now summarized once in the current docs rather than being
maintained as a second, potentially stale status narrative. Historical reports
under [`archive/reports/`](archive/reports/) and
[`architecture_handoffs/`](architecture_handoffs/) remain historical records
and are intentionally not rewritten as current evidence.
