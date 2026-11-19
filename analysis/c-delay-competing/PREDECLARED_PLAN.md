# Predeclared plan — delayed NonConsuming completion with a competing transition (#475)

Author: Agent C. Written before executing any new stochastic case in this slice.

## Scope

One previously unqualified required interaction under `release-delay-ssa` and
`release-delay-formats`: a delayed **NonConsuming** initiation with a *competing*
immediate decay of the product, with pending completions carried across a split
run boundary, plus BNGIR v0.1/v0.2 reconstruction into a real downstream consumer.

## Source model (fixed before execution)

Parameters `tau=1.0`, `k=2.0`, `kd=0.5`; species `A,B`; seeds `A() 20`, `B() 0`;
observables `Molecules A A()`, `Molecules B B()`; rules:

```
A() -> A() + B() k delay=tau NonConsuming
B() -> 0 kd
```

## Predeclared analytic laws (independent of BNG3)

NonConsuming reactant stays `A(t)=20`. Initiations are a Poisson process of rate
`k*A0 = 40` on `[0,inf)`; each completion occurs `tau=1.0` later and adds one `B`;
each `B` decays independently at per-particle rate `kd=0.5`. Therefore for
`t >= tau`:

`B(t) ~ Poisson( (k*A0/kd) * (1 - exp(-kd*(t-tau))) ) = Poisson(80*(1-exp(-0.5(t-1))))`

and `B(t)=0` for `t < tau`. ODE expectation obeys `dB/dt = k*A0 - kd*B` for
`t >= tau`, `B=0` before, with exact solution `80*(1-exp(-0.5(t-1)))`.

Split runs at `t=0.5` (initiations pending, zero completions yet) and `t=2.0`
(completions active) must reproduce the uninterrupted law; the split boundary
must preserve the observable state and the pending initiations.

## Predeclared stochastic protocol

- SSA seeds: base `7000`, consecutive `7000..7299` (N=300) for the uninterrupted
  ensemble; identical seeds for the split ensemble with continuation.
- Sample times `1.5, 2.0, 3.0, 4.0`; law above evaluated at each point.
- Error control: two-sided `4*sigma` band on the sample mean, with
  `sigma = sqrt(lambda/N)` from the analytic Poisson variance; variance within
  `0.5*lambda`; pre-horizon `B=0` identically; invariant all `B>=0`.
- Wrong-implementation controls (diagnostic, must be rejected): (a) no-decay law
  `B(t)=40*(t-1)`; (b) rate-halved law `Poisson(40*(1-exp(-0.5(t-1))))`.
- BNGIR reconstruction check uses ODE with the same law (deterministic) and a
  separate small SSA ensemble (N=100, seeds `8100..8199`) at `t=3.0`, same
  4-sigma mean band, comparing reconstructed v0.1/v0.2 models to the source.
- Semantic-equality counterexamples: changing `tau` or `NonConsuming` must not
  yield a verified-equal certificate (`False` or explicit `EqualityUndecided`).

## Wire-format semantics

BNGIR v0.1/v0.2 documents represent the **model specification** (rules, delay
parameter, NonConsuming flag, competing decay), not a live checkpoint of pending
initiations. Reconstruction therefore restarts from the initial state and is
compared by law and by source-level execution, not by a pending-queue snapshot.

## Toolchain identity (recorded at execution)

Native extension path/sha256, Python/JAX/numpy versions, package path and exact
git revision are written to the execution receipt.

## Support boundary

This qualifies only the fixed model above. It does not close #475, does not claim
general delayed-SSA support for arbitrary state-dependent hazards, and makes no
claim about network-free delayed execution beyond the recorded fail-closed guard.
