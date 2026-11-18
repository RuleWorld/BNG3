# Predeclared plan — extended installed CPU JAX qualification (#473)

Scope: bounded, independent qualification of families not covered by the
immigration–death SSA case (`analysis/c-jax-cpu`) or the ODE protocol case
(`analysis/c-jax-protocol`). This plan is written before executing any new
statistical case; it fixes laws, seeds, run budgets and error control.

## A. JAX ODE units, dtypes, common interfaces

No stochastic seeds. Analytic laws:

* Declared-concentration seed in a 3-D compartment with the mole/item bridge:
  `A0 = C * V * 1e-15 * N_A` items (`N_A = 6.02214076e23`).
* First-order decay `A() -> 0 k` with `k` declared `[per_s]`:
  `A(t) = A0 * exp(-k t)`.
* Functional Michaelis–Menten flux `Vmax*S^2/(Km+S)` (mass-action factor is
  retained for functional-rate rules in BNG3) gives implicit law
  `Km/S(t) - ln(S(t)) = Km/S0 - ln(S0) + Vmax*t` (root found independently).

Tolerance: rtol/atol `2e-4` for float64, `5e-3` for float32. Rate constants from
`jax_ode_flatten` must equal the declared numeric rate. Interface checks are
exact (key sets, shapes, dtypes) and use both `cpp.Model` and the
`BioNetGenModel` wrapper.

## B. JAX SSA beyond immigration–death: competing first-order decay

Model: `A()` seeded at `N0 = 30`; channels `A() -> B() k1` (`k1 = 0.3`) and
`A() -> C() k2` (`k2 = 0.1`). Total hazard `k = k1 + k2 = 0.4`.

Independent analytic law at `t = 3.0`: each initial molecule follows a
3-category multinomial,

* `p_A = exp(-k t) = exp(-1.2)`,
* `p_B = (k1/k) (1 - p_A)`,
* `p_C = (k2/k) (1 - p_A)`.

So `A(t) ~ Binomial(N0, p_A)`, `B(t) ~ Binomial(N0, p_B)`,
`C(t) ~ Binomial(N0, p_C)`, and `A+B+C = N0` pathwise.

Predeclared run budget and error control:

* device: CPU (`JAX_PLATFORMS=cpu`), batch size `N = 8192`, `n_steps = 1`,
  base seed `20261119`, `t_end = 3.0`.
* family-wise `alpha = 0.001`; Bonferroni over 3 marginals gives
  `alpha_m = alpha/3`; per-marginal DKW bound
  `eps = sqrt(ln(2/alpha_m) / (2 N))`. Every marginal must satisfy
  `KS_i <= eps`.
* mean control: `|mean_i - N0*p_i| <= 3 * sqrt(N0*p_i*(1-p_i)/N)` for each i.
* wrong-law control: swapping `k1` and `k2` must be rejected, i.e.
  `KS_B(swapped) > eps`.
* native-reference distribution parity: identical model/network executed with
  `cpp.simulate_batch_ssa_cpu(..., batch_size=N, t_end=3.0, n_steps=1,
  threads=1, base_seed=20261119)`. Two-sample DKW bound
  `eps2 = sqrt(2 * ln(2/alpha_m) / N)`; each marginal KS between the JAX and
  native empirical CDFs must satisfy `KS_i <= eps2`.

Stochastic seeds establish pathwise reproducibility only for identical
backend/seed; JAX and native use different RNG streams, therefore only the
declared distributional comparisons are made. No equality claim is made.

## C. Installation

Two separate checks:

1. Installed campaign: `pip install '.[jax]'`; assertions that `jax`, `jaxlib`
   are importable on CPU and that a real ODE+SSA run completes through the
   installed package (`BNG3_PYTHON_TEST_MODE=installed`).
2. Unavailable diagnostics: in isolated interpreters with `jax` imports
   blocked, `bionetgen` imports cleanly while `jax_ode` raises `ImportError`
   and `jax_ssa` raises `NotImplementedError`, both naming
   `pip install 'bionetgen[jax]'`.

No GPU claim is made. Passing these bounded cases does not by itself prove the
whole release matrix; hosted CI remains authoritative.
