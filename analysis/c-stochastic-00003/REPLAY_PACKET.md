# Replay packet — official SSTS stochastic/00003 failure at 98b310af

Prepared by Agent C (independent lane). All identities verified from A's retained hosted artifact.

## Source / build / oracle identities

- Product revision: `98b310afdda85b9628d7c9cdcbb48b139da15ee3` (clean main at official run).
- Hosted run: `44199524269`; artifact `ssts-98b310afdda85b9628d7c9cdcbb48b139da15ee3-1`.
- Suite: official SSTS `cf38585fac5de8e0e90112febb62851ee2181816`; case `stochastic/00003` l3v2.
- Original report: `/private/tmp/ssts-baseline-98b310af/report.json`, sha256 `1d8c17b44a3457fde9adab9ff38c0c4f928050128282b4ac0ba5eee4808c59fa`.
- Case inputs (match record `input_sha256` exactly):
  - source.xml sha256 `c58a50dd86f981150b533dd9af25c38f9ef3aeeedad2f679400e022add77f50e`
  - 00003-settings.txt sha256 `9472de7498a16b035f60764a99512d2ee3e3e06968f0d37774cbcb51b6e1471d`
  - 00003-results.csv sha256 `dc73fa905b0e4dbfa963d8a86e581529591464a580e20c5bd52cd5954e57ab5d`
- Runtime: native extension sha256 `09687676ac82678d86d8001def26a31c9856cd979c9d27a3a49313175b268e8b`; python package source sha256 `45408f6a…`; numpy 2.5.3; libSBML 5.21.2; libRoadRunner 2.10.0; Python 3.12.16; `PYTHONHASHSEED=0`.
- Source process (verified from source.xml + translated.bngl): X -> 2X at `1*X`, X -> 0 at `1.1*X`, X(0)=100, Cell volume 1. Generated network: 1 species, 2 reactions; ODE comparison max scaled error 3.2e-7 vs libRoadRunner 2.10.0.
- Reference column `X-mean/X-sd` equals the exact subcritical birth–death law `mu(t)=100 e^{-0.1t}`, `sigma(t)=sqrt(2100(e^{-0.1t}-e^{-0.2t}))` to CSV rounding (max relative deviation 7.0e-6). Reference is correct.

## Original official result (retained, unchanged)

- Engine `cpu:batch`, 40,000 trajectories, seed base 1,000,000, splitmix per-trajectory seed, grid t=0..49 (50 steps), work budget 4e8.
- 5/100 violations, all SD-side at t=41/43/44/45/46; `max|Z_mean|=2.846` (within ±3); `max|Y_sd|=8.567` (band ±5); F = 1.713.
- Sample SD systematically ~2–3% above reference, all positive. Report `violation_tail_probability=3.0e-7` is diagnostic-only and assumes independent tests, which is invalid because all observation times reuse the same trajectories.
- `roundtrip_passed=true`, `core_passed=true`, deterministic failures none — run completed normally, not a harness error.

## Exact reproduction commands

1. Native product reproduction (native ext from primary checkout `build/cpp`; SSA source byte-identical to 98b310af — only recorder plumbing changed):
```bash
cd /Users/akutuva/Documents/BioNetGen/BNG3
PYTHONPATH=python:build/cpp python3 - <<'PY'
from bionetgen import _bionetgen_cpp as cpp
bngl=open('/private/tmp/ssts-baseline-98b310af/cases/stochastic/00003/translated.bngl').read().split('begin actions')[0]
m=cpp.parse_string(bngl); n=cpp.generate_network(m)
r=cpp.simulate_batch_ssa_cpu(m,n,batch_size=40000,t_start=0,t_end=50,n_steps=50,base_seed=1000000,threads=1)
# r['observable_stds']['X_amt'] / ['observable_means']['X_amt'] reproduce report sample arrays exactly (max relative diff 0.0)
PY
```
2. Independent source-law diagnostic (predeclared plan hashed `194a60d67a7651bedb6ab83dbc28d6450fdd7adb4a868a496c689c333ef3f0b6`):
```bash
cd /tmp/bng3-c-stochastic-00003/analysis/c-stochastic-00003
python3 independent_diagnostic.py --report /private/tmp/ssts-baseline-98b310af/report.json --replicates 1000 --json c-diagnostic.json
```
3. Engine seed sweep (same model, base_seed in 1e6..8e6): observed violation counts 5, 1, 9, 15, 6, 0, 11, 0; F 1.71, 1.08, 2.85, 2.59, 3.33, 0.77, 2.04, 0.85.
4. Predeclared source-law confirmation receipt `c-diagnostic.json` sha256 `248145dcf065d6cf63e8bbf937d1707e71aac6226e7dc017c95062a696d4bc02`: P(F>=F_obs)=0.415 [0.385,0.446], P(count>=5)=0.473 [0.442,0.504], null mean F=1.713. Corrected power control `wrong_law_control.json` (mu=1.05 scored against the true reference): F~594, 50/50 violations, true-law p-value ~0 (rejected); `P_wrong(F>=F_obs)=1.0` is the complementary power statement under the wrong-law distribution, not the acceptance null. The primary tail null is the true birth–death law. Plan addendum documents the correction and the direction/null labeling.

## Disposition summary

Quantified oracle/statistic limitation — the official ±5 normal-theory SD band is too tight for this strongly non-Gaussian birth-death law (excess kurtosis rises to ~56 at t=45), so a correct engine produces clustered SD-side violations at 40k trajectories. No product or comparator defect demonstrated. Official failed verdict retained. See `FINDING.md` for the independent diagnostic result, uncertainty, and excluded alternatives.
