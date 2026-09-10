# ADR 0002: BNGsim adapter scope and solver status

- Status: Evaluated; not selected as the default network solver
- Date: 2026-09-08
- Scope: Optional BNG3-to-BNGsim network adapter

> Current implementation status is tracked in
> [`docs/CURRENT_PROGRESS.md`](../CURRENT_PROGRESS.md). This ADR records the
> adapter decision and does not supersede the active convergence gates.

## Context

BNGsim provides a native `ModelBuilder` API that can consume a generated
network without an intermediate `.net` file. BNG3 needs an independent
backend evaluation, but a numerically successful adapter is not evidence of
BNGL/NFsim semantic parity. The current BNGsim API also does not expose every
BNGL model or protocol construct.

## Decision

Keep `BUILD_BNGSIM_ADAPTER=OFF` by default. When explicitly configured with a
pinned external BNGsim build, BNG3 may lower the proven bounded subset directly
to `bngsim::NetworkModel`:

- generated species, constants, elementary and bounded functional rates;
- BNGL `Molecules` and `Species` observable pattern matching;
- inline and absolute-path TFUNs with supported counters and interpolation;
- direct CVODE execution for the constructed network.

The adapter must reject before solver construction when semantics cannot be
carried faithfully. This currently includes compartments, energy patterns,
population maps, simulation protocol actions, local-function arguments,
relative TFUN paths without source-directory provenance, and non-reference
reaction rate expressions. Rejection is a correctness boundary, not a solver
failure to hide.

This decision does not select BNGsim over NFsim, BNG3 ODE, or another backend.
Selection requires independent seeded trajectory, observable, rate, failure,
performance, and broad-model parity evidence, followed by maintainer review.

## Evidence

The adapter was built against BNGsim commit
`49dc939035f5a272da663f8c9586e3c9f0e1c041` in an isolated external build.
BNG3's focused adapter suite passed `8/8`; BNGsim's managed suite passed
`6/6`; the optional BNG3 build passed `278/278`. The default BNG3
Release/Ninja suite passed `271/271`. These are
feasibility and regression results for the bounded subset, not release-level
BNGsim, NFsim, or BNG2 parity.

## Consequences

- BNG3 can test a native independent backend without adding a mandatory
  dependency or silently changing the default solver.
- New adapter features require a red semantic test, a green focused test, and
  an explicit capability/provenance decision.
- Compartment, protocol, energy, full expression, and broad parity work stays
  visible as open gates rather than being approximated.

See [architecture.md](../architecture.md),
[BNG3_HANDOFF_PORT_STATUS.md](../BNG3_HANDOFF_PORT_STATUS.md), and the
convergence checklist for the live evidence and remaining gates.
