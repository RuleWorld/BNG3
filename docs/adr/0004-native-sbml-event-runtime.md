# ADR 0004: Native BNG3 runtime for dynamic SBML events

- Status: Accepted for staged implementation
- Date: 2026-09-29
- Scope: Modern Atomizer output, BNGL parsing, ODE and stochastic event execution

## Context

The modern Atomizer exactly lowers event systems when it can prove a finite
schedule of BNGL actions. The remaining official SSTS event cases include
threshold crossings in coupled nonlinear reaction systems, delayed and
nonpersistent events, priority interactions, and recurring/reset behavior.
These cannot be represented by a finite list of precomputed `at` actions.
The current CVODE integrator also has no root-function registration, and
general event execution is not represented in the BNGL semantic model.

SBML event behavior includes trigger transitions, trigger-time or
execution-time assignment values, delays, persistence, and priorities. Equal
priority events can require random ordering. Those requirements rule out
fixed-grid trigger polling and arbitrary execution order. SUNDIALS CVODE
provides root finding through `CVodeRootInit`, `CVodeGetRootInfo`, and root
direction controls; this can locate continuous trigger crossings without
sampling the trajectory at a chosen output interval.

## Decision

Keep exact finite schedule lowering as the preferred path where it proves
equivalence. Add a first-class, versioned BNG3 event representation for
dynamic events that need execution-time trigger detection. The representation
will be carried by the canonical model/document and serialized in an explicit
BNG3 event block, rather than hidden in comments or an external sidecar.

The native runtime will own event evaluation and an execution queue. The ODE
backend will use solver root finding for continuous state-trigger conditions
and scheduled wakeups for time triggers and delayed events. After each firing,
the runtime will apply trigger-time or execution-time assignments as
specified, recheck trigger persistence, reevaluate eligible priorities, and
reinitialize the solver when assignments change its state or rate parameters.
The stochastic backend will check state triggers at reaction-state changes,
process delayed events in the same event queue, and use the run seed for
required random event ordering.

Implementation proceeds in slices, while this complete semantic contract
remains the acceptance target. A supported ODE slice does not imply support
for delays, priorities, parameter/compartment assignments, stochastic
execution, or the full SSTS event set. If a model requires semantics that the
selected runtime cannot preserve, import fails closed with a specific reason.
The BNG3 event block is an explicit BNG3 extension; it makes no promise that
legacy BNG2 can parse or execute that block. No legacy BNG2 source is changed.

## Options considered

### Continue symbolic finite-schedule lowering only

**Pros:** Keeps generated files compatible with ordinary BNGL action syntax;
retains strong proofs for the currently supported analytic families.

**Cons:** Cannot represent finite-horizon crossings for general coupled
trajectories or recurring events with non-finite schedules. Further analytic
special cases do not close the runtime event gap.

### Poll triggers at fixed time intervals

**Pros:** Small initial implementation and works with the existing output
grid.

**Cons:** Can miss a trigger that becomes true and false between samples;
execution time then depends on output resolution. Rejected as semantically
incorrect.

### Delegate dynamic events to libRoadRunner

**Pros:** Avoids implementing another event queue and offers an independent
SBML execution engine.

**Cons:** Does not execute the generated BNGL model in BNG3, adds a second
runtime semantic path, and makes Atomizer output depend on translating the
model back to SBML. Rejected as the product execution path; libRoadRunner
remains an independent validation oracle.

### Add native BNG3 event representation and execution

**Pros:** Executes the model through BNG3's own ODE and stochastic engines;
supports dynamic crossings without weakening the analytic proof path; makes
the BNG3-only compatibility boundary explicit.

**Cons:** Requires coordinated changes to the semantic model, parser/writer,
ODE solver, event queue, stochastic engine, and conformance tests.

## Consequences

- Existing exact analytic event lowerings remain in place and are tested
  against the new runtime path where both apply.
- Root finding locates continuous crossings; event queue logic, not CVODE,
  implements SBML delays, persistence, snapshots, and priority ordering.
- A same-priority event set that requires random ordering must not be
  serialized as one arbitrarily ordered deterministic action sequence.
- BNG2 and PyBioNetGen remain read-only comparators. Reports must distinguish
  standard BNGL parity from BNG3 extension behavior.
- Overall Atomizer completion still requires the full feature checklist,
  cross-engine round trips, SSTS evidence, and the authorized BioModels gate.

## Action items

1. Define the versioned event-block grammar and structured event model types.
2. Add root-function and event-queue support to native CVODE execution.
3. Add trigger transition, delayed execution, persistence, snapshot, and
   priority tests grounded in official SBML cases.
4. Add stochastic event-queue semantics and seeded random ordering.
5. Round-trip the event block through BNG3 writers and verify it through the
   installed CLI; retain explicit rejection diagnostics outside the supported
   semantic surface.
6. Re-run full SSTS only after a meaningful implementation batch; keep
   BioModels validation stopped until requested.

## References

- [SBML Level 3 Version 2 Core, Release 2](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf)
- [SUNDIALS CVODE usage and rootfinding](https://sundials.readthedocs.io/en/latest/cvode/Usage/index.html)
- `docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md`
- `python/bionetgen/atomizer/modern/events.py`
- `cpp/engine/OdeIntegrator.cpp`
