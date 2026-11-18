# Addendum to PREDECLARED_PLAN.md (2026-11-18)

Two transparent corrections/additions after the predeclared run:

1. **Wrong-law power control bug fix.** In `independent_diagnostic.py` the wrong-law ensemble (mu=1.05) was scored with `source_moments(step, mu)` using `mu=1.05`, i.e. against its OWN reference, not the TRUE mu=1.1 reference. That did not test the predeclared hypothesis ("wrong law evaluated against the true reference must be rejected"). The primary disposition does not depend on this control; it is established by the true-law tail probabilities, the retrospective calibration, the analytic kurtosis argument and the engine seed sweep. `wrong_law_control.py` recomputes the control correctly by scoring a mu=1.05 ensemble against the TRUE mu=1.1 reference. Result in `wrong_law_control.json`.

2. **Reduced budget for the corrected power control.** The corrected control is a power check, not the primary tail estimate; it was run with R=300 (Wilson CI still tight because the effect is large). The predeclared R=1000 budget applies to the primary true-law confirmation in `c-diagnostic.json`.

3. **Sampler identity cross-check.** `sampler_crosscheck.json`: the independently coded negative-binomial and geometric sampling routes each reproduce the exact analytic mean to <0.7% and variance to <1.9% over 30 ensembles of 40,000, within Monte Carlo error for this heavy-tailed law. Coarse `geometric_route_matches_nb` in `c-diagnostic.json` remains a sanity check only.

4. **Formatting only.** The two analysis Python files were reformatted with pinned `black 26.10.0` (`--target-version py312`) to satisfy the repo-wide `black --check` CI gate, and an unused import was removed. Statistical parameters, logic and the predeclared plan are unchanged; sanity reruns reproduce the same behavior.

5. **Direction / null labeling of the power control.** The predeclared plan (item 4 "genuine wrong law … must be rejected" and the wrong-law-control paragraph) wrote "`P(F>=F_obs)` must be small" for the wrong-law case using the same notation as the primary true-law tail probability. These are different distributions. The acceptance null is the TRUE law (mu=1.1); the primary decision uses `P_true(F>=F_obs)=0.415`. The corrected wrong-law control scores mu=1.05 data against the TRUE reference: it gives F~594, whose p-value under the true-law null is ~0 (rejected). The printed `P_wrong(F>=F_obs)=1.0` is the wrong-law distribution's probability of exceeding the observed threshold — the complementary power statement, read in the opposite direction — not a p-value and not the acceptance null. Both quantify that the diagnostic has power against a genuinely wrong law; neither changes the official verdict or the predeclared statistic, seed, budget, decision rule, thresholds or acceptance bands.

No change to the predeclared statistic, seed (20261118), ensemble budget for the primary run, decision rule, thresholds, or acceptance bands.
