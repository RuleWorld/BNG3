# Predeclared plan — installed CPU JAX ODE protocol/parameter-intervention qualification (#473)

Author: Agent C. Written before executing any new case in this slice.

## Scope

One previously unqualified required family of the installed optional CPU JAX ODE
backend under `release-jax-ode`: a **public continuation protocol with a parameter
intervention on a time-dependent rate law**, plus the same protocol on an
observable-dependent functional rate. Both are deterministic ODE paths, so no
stochastic seeds or run budgets apply. This does not establish full `release-jax-ode`
or any GPU claim.

## Source models (fixed before execution)

1. Time-dependent: parameters `k`; species `A`; rule `0 -> A() k*time()`; seed `A() 0`;
   observable `Molecules CountA A()`.
2. Functional: parameters `k`; species `A,B`; rule `A() -> B() f()` with
   `f() k*CountA`; seeds `A() 10`, `B() 0`; observable `Molecules CountA A()`.

## Predeclared analytic laws

Time-dependent, phase 1 `[0,2]` with `k=k1`, phase 2 `[2,4]` with `k=k2`,
initial state carried from phase 1 (`A(t)` is the only species):

- `A(t) = A(t0) + 0.5 * k * (t^2 - t0^2)` for a phase starting at `t0`.
- `A(2) = 2*k1`; `A(4) = 2*k1 + 6*k2`.
- Gradient `dA(4)/dk2 = 0.5*(4^2 - 2^2) = 6` (analytic; independent of the kernel).

Functional (nonlinear) rate, phase 1 `[0,1]` with `k=k1`, phase 2 `[1,3]` with
`k=k2`, `A(0)=10`, `B=10-A`:

- `A(t) = A(t0) / (1 + k*A(t0)*(t-t0))` within a phase (exact solution of
  `dA/dt = -k*A^2`).
- `dA(3)/dk2 = -A(1)^2 * 2 / (1 + k2*A(1)*2)^2`.

## Predeclared checks

- Returned grid: `len(time) == n_steps+1`; `time[0] == t_start`; `time[-1] == t_end`.
- Piecewise law holds at all phase grid points within dtype-dependent tolerance:
  float64 `rtol=2e-5, atol=2e-5`; float32 `rtol=5e-3, atol=5e-3`.
- Gradients hold within the same tolerances (relative to the analytic value).
- Error behavior: `t_start < 0`, `t_end <= t_start`, noninteger `n_steps`, and
  an initial-state vector with wrong length each raise.
- Wrong-implementation control (diagnostic, must be rejected): freezing the rate
  at the phase-1 value during phase 2 predicts `A(4)=2*k1+6*k1=8` (time-dependent)
  and `A(3)=A(1)/(1+k1*A(1)*2)` (functional). Both must lie outside the declared
  tolerance of the actual piecewise result; the assertions bind to the correct
  law, so a frozen-rate implementation fails them.

## Toolchain identity (recorded at execution)

JAX/jaxlib version, `jax.devices()`, `JAX_ENABLE_X64`, package and native
extension paths and sha256 are written to the execution receipt.

## Support boundary

This qualifies only the two fixed models above under the installed CPU backend.
It does not cover time-varying SSA hazards, GPU execution, or full #473 closure.
