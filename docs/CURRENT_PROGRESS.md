# BNG3 current progress

**Reviewed:** 2026-10-07. **Implementation baseline:** main `e1836c3274e685996d5e86883761e00e98257e09`.
**Status:** integration is substantial; semantic convergence and release
qualification remain incomplete.

The [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) is the current
55-item issue index. The [repository audit](REPOSITORY_AUDIT_2026-10-07.md) records
scope and source evidence. The old progress log is preserved at its
[audited revision](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/CURRENT_PROGRESS.md).

## Verified at the implementation baseline

| Evidence | Result | Limit |
| --- | --- | --- |
| Exact-head hosted checks | 46 successful, 2 skipped | Configured scope, not full convergence. |
| Skipped jobs | PyPI publishing; scheduled historical NFsim | No release or historical-suite claim from those jobs. |
| Local architecture ratchet | Pass; 43 compatibility files | Transitional AST dependencies remain. |
| Local corpus checks | Pass; 106 model records, manifest current | S=10, P=106, NF=4, expression=5; X=0, B=0. |
| Local strict provenance | Fail; 14 approval/lock errors | H01 must resolve decisions and evidence. |
| Local Lean static/header gates | Pass; 37 Lean files | Static validation is not kernel checking. |
| Local native NFnext contract | 18/18 pass | Bounded matcher/transformation fixtures. |
| Hosted Lean kernel/Smoke/Coverage/axiom gate | Pass | No general production-C++ refinement theorem. |

Exact-head runs: [CI](https://github.com/RuleWorld/BNG3/actions/runs/37548838421),
[parity](https://github.com/RuleWorld/BNG3/actions/runs/37548838423),
[Lean](https://github.com/RuleWorld/BNG3/actions/runs/37548838419).
These results describe the baseline above; reread checks for any later SHA.

## Immediate open work and boundaries

- PR [#130](https://github.com/RuleWorld/BNG3/pull/130), head `3b6c61d4`, fails
  independent BNG2 and three platform validation jobs on `test_assignment`.
  The observed difference is constant `0.0` versus an equivalent-looking
  conditional expression; runtime-semantic impact is not established. A01
  owns reproduction and classification; do not weaken the comparator by guess.
- Draft PR [#128](https://github.com/RuleWorld/BNG3/pull/128), head `d5f6ad90`,
  has successful configured checks except conditional skips; A03 owns review.
- The JAX ODE helper has a reproduced undefined `network`; JAX SSA still raises
  `NotImplementedError` (A02/G03). Native-engine results do not qualify JAX.
- Native dynamic-event execution is rejected; BNGIR import still reparses BNGL;
  NFnext has a restricted capability surface (E01/D01/C02).
- The historical SSTS 1,744 passed / 179 unsupported result is not a current
  report. Locking and official-reference code now exist; new aggregate
  conformance evidence and a hosted lane remain open (E03/H05).
- Full curated BioModels validation remains stopped at the user's request.
  No current aggregate result exists; issue creation does not resume it (E06).
- This documentation update ran no new full native/Python/scientific suites.
  The audit's local exception-ledger CLI was unavailable because its Python
  lacked pytest; the inspected JSON contained no exceptions.

## Maintaining current state

Keep implementation details, owners, dependencies and closure evidence in the
linked issues. Update this page only for a new verified baseline or a material
scope change. Preserve exact revisions, skipped gates and the distinction
between theorem, fixture, independent oracle and release evidence.
