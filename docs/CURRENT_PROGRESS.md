# BNG3 current progress

**Audited:** 2026-09-10
**Repository:** `RuleWorld/BNG3`
**Branch:** `codex/bng3-rest-of-port-20260909`
**Committed base:** `a8d2a8b` (`origin/main`)
**Validation state:** implementation pass verified; convergence remains incomplete

This is the live snapshot for the current implementation pass. It supersedes
branch names, counts, and “current” claims in older handoff archives. The
working tree was already dirty when this branch was created, so the changes
listed below are intentionally preserved as one consolidated batch. The final
combined-state verification for this pass is now recorded below.

## Implemented in the current batch

- NFnext now contains the expanded NFIR/rule-family surface, deterministic
  family collapse and expansion, canonicalization, dependency indexing,
  generic graph matching, transformations, validation, cache v2, function and
  observable helpers, compartment/rate helpers, lattice/interval helpers, and
  replay/batched-trajectory support.
- The completed NFnext contracts for canonicalization, dependency scheduling,
  generic matching, transformations, memory arenas, cache, observables,
  lattice/interval, compartments/rates, replay/RNG, and rule families are
  registered in the architecture CTest spine. The remaining future contracts
  stay opt-in and fail closed.
- NFsim mapping storage now uses lazy paged allocation with active-membership
  tracking, while preserving the existing multi-mapping API and recycling
  empty pages.
- The modern SBML-Multi parser now retains structured molecule, complex,
  species, component-alias, compartment-reference, and product-map metadata;
  it resolves bounded single-level structures and reports unsupported or
  ambiguous forms explicitly. Runtime injection remains gated by independent
  execution evidence.
- The recent committed NFsim work includes graph-function transport and
  deletion semantics, complex observable scopes, expression time-dependency
  tracking, compartment-scoped observables, and multi-bond symmetric-site
  lowering.

## Still open

- The final combined-state build passed. CTest passed 305/305 tests; the
  project Python suite passed 353 tests with 27 expected skips; and validation
  smoke passed 4 checks with 14 environment/reference skips. These results are
  evidence for this branch and supersede earlier checkpoint results for this
  pass.
- Full independent NFsim/BNG2/PyBioNetGen parity, complete Tier-P/Tier-NF/X
  corpus coverage, structured SBML atomization, end-to-end SBML-Multi
  execution, XML-bridge retirement, legacy-tree deletion, packaging/release,
  maintainer approvals, and hosted CI remain open under the convergence
  checklist.
- NFnext backend equivalence, XML-to-NFIR lowering, code generation,
  accelerator, population/hybrid, differential-oracle, fuzz/metamorphic,
  scaling, and Rasi/uORF contracts remain explicit future work unless their
  real implementation and independent evidence are added.

## Verification policy for this pass

Implementation and documentation changes were accumulated before one final
verification sequence. One stale contract-inventory entry and one missing
structured Python type were corrected together after that sequence exposed
them; the affected verification was then rerun as a grouped correction pass.
Tests were not run after each individual edit.

The authoritative completion criteria remain
[`BNG3_CONVERGENCE_DONE_CHECKLIST.md`](BNG3_CONVERGENCE_DONE_CHECKLIST.md),
with working rules in [`../AGENTS.md`](../AGENTS.md).
