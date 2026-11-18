# Finding — official SSTS stochastic/00003 failure at 98b310af

Agent C independent lane. Scope: one official case on one revision. This finding does not change the official verdict, seeds, tolerances, exclusions, expected outputs or run budgets, and does not claim full stochastic-surface equivalence.

## Disposition

**Quantified oracle/statistic limitation; no product or comparator defect demonstrated.** The official failure (5/100 SD-side violations, seed base 1e6, 40k trajectories) is a typical realization of a *correct* BNG3 batch-SSA ensemble under a source law whose variance sampling distribution is strongly non-Gaussian. The official ±5 standard-normal SD band is mis-calibrated for this law: the true asymptotic scale of `Y_sd` grows to ~4.4–5.7 at the flagged late times, so `|Y_sd|=8.6` is only ~1.7 true-law sigma, not 8.6. The official failed verdict is retained.

## Original official result (retained)

- Run 44199524269 at 98b310af; case stochastic/00003 l3v2; suite cf38585f.
- cpu:batch, 40,000 trajectories, base seed 1,000,000, grid t=0..49, work budget 4e8.
- 5/100 violations, all SD-side at t=41/43/44/45/46; `max|Z_mean|=2.846` (within ±3); `max|Y_sd|=8.567` (band ±5); familywise `F=max(|Z|/3,|Y|/5)=1.713`.
- All mean and SD deviations positive (shared-trajectory ensemble realization). Report binomial tail 3.0e-7 is diagnostic-only and assumes independent tests, invalid on the reused-trajectory grid.

## Core quantitative argument: the ±5 band is mis-calibrated

For a normal source law `Y_sd = sqrt(N/2)(S^2/sigma^2 - 1)` has unit variance, so ±5 is a ~5-sigma band. For a non-Gaussian law its asymptotic variance is `(kurtosis - 1)/2`. At the flagged late times the source law is strongly non-Gaussian (excess kurtosis 37–62), so the true `Y_sd` scale is ~4.4–5.7, not 1:

| t | exact SD | excess kurtosis | true Y_sd scale `sqrt((k-1)/2)` | observed Y_sd | observed in true-law sigma |
|---:|---:|---:|---:|---:|---:|
| 41 | 5.850 | 37.3 | 4.43 | 7.655 | 1.73 |
| 43 | 5.302 | 45.7 | 4.89 | 8.567 | 1.75 |
| 44 | 5.046 | 50.6 | 5.13 | 8.554 | 1.67 |
| 45 | 4.803 | 56.0 | 5.39 | 6.882 | 1.28 |
| 46 | 4.571 | 61.9 | 5.66 | 5.757 | 1.02 |

The five "5–8.6 sigma" violations are 1.0–1.8 sigma under the law that actually generated the data. The normal-theory band is the reason for the official failure.

## Independent evidence

1. **Inputs verified.** source/settings/results hashes match record `input_sha256` exactly. Reference results column equals the exact subcritical birth–death law (`mu=100e^{-0.1t}`, `sigma^2=2100(e^{-0.1t}-e^{-0.2t})`) to 7e-6. The comparator reference is correct.
2. **Exact native reproduction.** Re-running the prebuilt extension (SSA source byte-identical to 98b310af) at base_seed=1e6 reproduces the report sample mean and SD arrays with 0.0 max relative difference. The report faithfully reflects the product and is deterministic under the official seed.
3. **Seed sweep (engine).** At seed bases 1e6..8e6 the violation count is 5,1,9,15,6,0,11,0 and F is 1.71,1.08,2.85,2.59,3.33,0.77,2.04,0.85. The official count 5 is typical; several seeds are worse. No systematic seed bias.
4. **Code trace.** Linear birth–death propensities lower to 2 mass-action channels (verified from source.xml/translated.bngl and generated network 1 species/2 reactions; ODE comparison 3.2e-7 vs libRoadRunner 2.10.0). Per-trajectory seeding is a SplitMix64 finalizer with per-thread scratch (adjacent-seed overlap regression-tested). Variance is Welford with population variance (ddof=0). The comparator uses exactly `Z=sqrt(N)(mean-mu)/sigma`, `Y=sqrt(N/2)(S^2/sigma^2-1)`. Numeric-narrowing and accumulator fixes are already merged and 23/23 moment/numeric-limit + 10/10 closed-form parity tests pass. No arithmetic, seeding or aggregation defect.
5. **Retrospective source-law calibration (reused, retrospectively).** `stochastic-00003-source-law-calibration.json` (seed 20261022, R=1000) scores this exact observed sample: `P(F>=F_obs)=0.391 [0.361,0.422]`, `P(N_viol>=5)=0.446 [0.415,0.477]`, joint 5-threshold exceedance `P=0.013 [0.0076,0.0221]`. The observed sample is compatible with the true law.
6. **Predeclared independent confirmation (NEW).** Plan `PREDECLARED_PLAN.md` written and hashed (`194a60d6…`) before any new Monte Carlo; independent code `independent_diagnostic.py`, R=1000, K=40000, seed 20261118, exact conditional branching with common trajectories across times, Wilson 95% uncertainty. Receipt `c-diagnostic.json` (sha256 `248145dc…`). Results:
   - `P(F>=F_obs) = 0.415` [0.385, 0.446] — the observed familywise statistic is at the median of its true-law null (null mean F = 1.713, essentially equal to F_obs = 1.713).
   - `P(N_viol>=5) = 0.473` [0.442, 0.504] — observed 5 violations is near the null mean (5.36).
   - `P(joint exceedance of all 5 observed SD thresholds) = 0.019` [0.012, 0.029] (retrospective joint contrast; F and count are the predeclared familywise statistic).
   - Null max|Y_sd| 95th percentile = 16.16 (observed 8.57 is well inside); ensemble-mean variance reproduces the analytic variance to within 0.1–0.4% (ratio 1.001 at the flagged times).
   - Independent geometric-vs-negative-binomial sampler routes each reproduce the exact analytic moments (<0.7% mean, <1.9% variance over 30 ensembles; `sampler_crosscheck.json`).
   - Wrong-law power control (corrected, `wrong_law_control.py`, scored against the TRUE reference — see `PLAN_ADDENDUM.md`): a mu=1.05 ensemble produces F ~ 594 (5th pct 573), 50/50 violations, `P(F>=F_obs)=1.0` [0.987,1.0]. The diagnostic decisively rejects a genuinely wrong law, so its acceptance of the observed sample is informative. The first wrong-law implementation scored against the wrong law's own reference and was corrected; the primary disposition does not depend on it.

## Competing explanations

- **Comparator / harness defect:** excluded — formula matches DSMTS, ddof=0 matches Welford, reference equals analytic law, exact reproduction.
- **Seed correlation:** excluded by inspection (SplitMix64 finalizer, adjacent-seed test) and engine seed sweep (0–15 violations across seeds).
- **Accumulator / numeric narrowing:** excluded — already fixed and regression-tested; exact reproduction at official seed.
- **Wrong source law / lowering:** excluded — 1 species/2 reactions, correct rates, ODE parity, reference = analytic law.
- **Oracle/statistic limitation:** supported — non-Gaussian `Y_sd` null (excess kurtosis ~56 at t=45), predeclared source-law confirmation `P(F>=F_obs)=0.415` / `P(N_viol>=5)=0.473` and retrospective calibration 0.391/0.446 both accept the observed sample, the engine seed sweep shows the same spread, and a corrected wrong-law control is rejected at `P(F>=F_obs)=1.0`.
- **Still open:** none for this case's disposition. The result is a bounded compatibility result for this case; it does not prove the engine equivalent to the law across the full stochastic surface.

## Next action for A

Record this finding on #159. Retain the official failed verdict for stochastic/00003 at 98b310af as a known seed-sensitive case under a normal-theory SD band that is too tight for a non-Gaussian source law; do not reroll seeds or widen tolerance. The existing release contract for a retained official failure applies. No product fix; no shared harness edit.
