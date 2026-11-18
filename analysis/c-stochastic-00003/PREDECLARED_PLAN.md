# Predeclared diagnostic plan — SSTS stochastic/00003 at 98b310af

Written: 2026-11-18T00:37:45Z. This plan is hashed (`sha256sum PREDECLARED_PLAN.md`) before any new Monte Carlo result is generated. The observed 98b310af failing sample is analyzed **retrospectively**; the plan, statistic, budget and seed below are declared before running the new confirmation ensembles.

## Question

Is the official 5/100 SD-side failure at 98b310af (seed base 1,000,000; cpu:batch; 40,000 trajectories; grid t=0..49) consistent with a correct BNG3 batch-SSA implementation of the exact subcritical birth–death law X->2X at 1*X, X->0 at 1.1*X, X(0)=100, or does it indicate a product/comparator defect?

## Statistic (reuse the existing predeclared familywise statistic)

Per ensemble of K=40,000 trajectories observed at the 50 integer times t=1..49 (t=0 is the deterministic initial state, variance 0, excluded from variance tests):

- `Z_mean(t) = (sample_mean(t) - mu(t)) / sqrt(var(t)/K)`
- `Y_sd(t)  = sqrt(K/2) * (sample_var(t)/var(t) - 1)`   (population variance, ddof=0, matching the official checker and the retained source-law calibrations)

with exact source moments `mu(t)=100*exp(-0.1 t)`, `var(t)=2100*(exp(-0.1 t)-exp(-0.2 t))`.

Familywise statistic: `F = max over the 100 official tests of ( |Z_mean(t)|/3 , |Y_sd(t)|/5 )` (the statistic predeclared in `provenance/sbml-campaign/stochastic-00003-source-law-calibration.json`, `familywise_statistic_alpha=0.01`). Also record the violation count `N_viol = #{tests: |Z_mean|>3 or |Y_sd|>5}` and the joint SD-threshold exceedance indicator `J = 1` iff `Y_sd(t) >= observed_Y_sd(t)` at every observed violation time t in {41,43,44,45,46} (retrospective joint threshold).

## Fixed replicate / seed budgets (declared now, not tuned)

- `R = 1000` independent ensembles.
- `K = 40,000` trajectories per ensemble (matches official).
- New RNG seed `20261118` (not used by any retained calibration: prior seeds were 20261022, 20261024, 20261026, 2581028), numpy PCG64.
- Exact conditional transition per unit step from a lineage: survive with prob `p_s = (mu-lambda)*a/(mu-lambda*a)`, and a surviving lineage has `1 + Geometric(1-q)` total descendants with `q = lambda*(1-a)/(mu-lambda*a)`, `a=exp(-0.1)`. Equivalently `survivors ~ Binomial(pop, p_s)` and `extra ~ NegativeBinomial(survivors, 1-q)`. Trajectories are carried forward across all 50 times (common trajectories across observation times), so the familywise/joint dependence is preserved.
- Same grid, population, ddof=0 normalization and ensemble budget as the official run. A distinct, independently coded geometric sampling route is cross-checked against the negative-binomial route for one ensemble.

## Uncertainty

Wilson 95% intervals for `P(F >= F_obs)`, `P(N_viol >= 5)` and `P(J=1)`; Monte Carlo SE `sqrt(p(1-p)/R)`. Report the null distribution of F, max|Y_sd| and N_viol (mean, sd, 95th percentile). Reproduce the independent oracle's ensemble mean variance per time against the analytic variance and flag any drift beyond Monte Carlo error.

## Decision rule (declared now)

- **Oracle/statistic limitation** if `P(F >= F_obs)` is not small (>= 0.05) AND the observed `N_viol=5` lies within the central 95% of the null N_viol distribution. Then the official failure is a typical outcome of a correct implementation under a normal-theory ±5 SD band that is too tight for this non-Gaussian law (excess kurtosis rises to ~56 at t=45). Retain the official failed verdict unchanged; do not reroll seeds or widen tolerance.
- **Product/comparator defect** if `P(F >= F_obs) < 0.01` AND the observed N_viol is in the extreme tail of the null. Then investigate seed correlation / variance inflation / comparator arithmetic and trace the CPU SSA path.
- **Inconclusive** if the two criteria disagree or Monte Carlo uncertainty spans the threshold.

## Alternative hypotheses to separate

1. Oracle/statistic limitation: non-normal source law makes the normal-theory Y_sd null far wider than ±5.
2. Seed correlation / per-trajectory seeding defect producing inflated variance (A inspected `BatchSsa.hpp`: `base + 0x9E3779B97F4A7C15*(traj+1)` splitmix-style).
3. Comparator arithmetic: variance denominator (ddof), accumulator/narrowing bug (numeric-limit fixes already merged on main — verify rather than assume).
4. Genuine wrong law (wrong mu / rate / scaling) — must be rejected by the diagnostic for it to have power.

## Wrong-law control (power check)

Run a second ensemble set under a deliberately wrong death rate `mu_wrong = 1.05` (birth 1.0, X0=100), same K/grid/seed/statistic. Predeclared expectation: `F` grows with t without bound relative to the true-law reference because the mean trajectory diverges; `P(N_viol>=5)` under the wrong law evaluated against the TRUE reference must be ~1 and `P(F>=F_obs)` must be small for at least the late-time Z/SD component. If the diagnostic cannot separate the wrong law, the result is inconclusive.

## Reuse of prior evidence

- Retrospective `stochastic-00003-source-law-calibration.json` (seed 20261022, R=1000) already scores THIS observed sample: P(F>=F_obs)=0.391 [0.361,0.422], P(N_viol>=5)=0.446 [0.415,0.477], joint P=0.013 [0.0076,0.0221]. Reuse with its retrospective label; do not present as predeclared.
- Held-out predeclared calibrations (runs 39881927354 / 39877752652, seed base 2,000,000, observed F=1.341, 2 violations, verdict passed) are reusable as predeclared support for the general claim that this familywise statistic is well-calibrated, but they are a different seed/run and do not dispose of the 98b310af sample.
- This plan's new R=1000 seed-20261118 run is the predeclared confirmation for the 98b310af sample.

Retain unfavorable outcomes. Nothing here changes official seeds, tolerances, exclusions, expected outputs or run budgets.
