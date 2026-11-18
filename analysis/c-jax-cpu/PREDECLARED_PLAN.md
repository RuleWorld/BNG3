# Predeclared plan — new installed CPU JAX SSA capability case

Owner: Agent C (independent qualification lane). Written before executing any
new stochastic run for this case. Scope: one previously unqualified real input
class for the installed optional JAX CPU SSA backend under #473.

## Case (real input, not a contrived fixture)

Linear immigration–death CTMC in BNGL:

- `0 -> A()` at rate `k_on = 2.0` (zero-order creation channel; no reactant)
- `A() -> 0` at rate `k_off = 0.5` (first-order death channel)
- `A(0) = 0`

This combines a zero-order creation channel with a first-order decay channel in
one flattened network — a real mass-action input class not exercised by the
existing JAX SSA tests (which cover no-reaction, pure first-order survival,
reversible two-state equilibrium, and A+B bimolecular binding).

## Independent analytic laws (source-derived, not from BNG3)

Master equation for this birth–death process gives, exactly:

- Transient mean `E[A(t)] = (k_on/k_off) * (1 - exp(-k_off t)) = 4 * (1 - exp(-0.5 t))`.
- Stationary distribution `A(infty) ~ Poisson(lambda = k_on/k_off) = Poisson(4)`.
- Stationary variance `Var[A] = 4`.
- Relaxation rate `k_off = 0.5` per second, so `t_end = 20 s` is 10 relaxation
  time constants — sufficient to be at stationarity to well below the DKW
  resolution used here.

The Poisson CDF and the transient mean are computed from these closed forms
using only Python's `math`/`numpy`, with no BNG3 or native-engine call.

## Predeclared execution and error control

- Installed subject: exact main revision `0d42c6666525debeed61a6e7731fedefd1196df6`.
- Device: JAX forced to CPU (`JAX_PLATFORMS=cpu`); record `jax.devices()`.
- Fixed base seed `20261118` (not used by existing JAX SSA tests).
- Transient check: one run, `batch_size=4096`, `t_end=20.0`, `n_steps=20`
  (grid 0,1,...,20). At each grid time require
  `|mean_A(t) - 4(1-e^{-0.5t})| <= 3*SE(t) + 0.05`, `SE = std/sqrt(4096)`.
- Stationary distribution check: one run, `batch_size=8192`, `t_end=20.0`,
  `n_steps=1`, same base seed. Compare empirical CDF of `A(20)` to the exact
  Poisson(4) CDF with the DKW inequality at `alpha = 0.001`:
  `bound = sqrt(ln(2/alpha)/(2N))`.
- Power/wrong-law control (diagnostic only, not a support claim): compute the
  KS statistic of the same samples against a deliberately wrong Poisson(6)
  law and require it to exceed the DKW bound, demonstrating the distributional
  check can reject a wrong law at this budget.
- Invariant controls: `A >= 0` for every trajectory; conservation is not
  expected here (open system).

## Decision rule

Supported for this case only if all predeclared checks pass against the exact
installed revision with the recorded seed and budgets. Any failure is reported
as a concrete product/diagnostic finding, not waived by changing the seed,
batch size, alpha, law, tolerance or case. A retained failure cannot be
relabelled as pass or as unsupported without a documented cause. Unavailable
optional-extra diagnostics are reported separately and never counted as an
installed execution.

The scope is one CPU JAX SSA input class; it does not claim full #473 acceptance
or any GPU behavior.
