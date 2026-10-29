# Issue 159: stochastic case 00003 calibration

`stochastic_00003_law.py` derives the exact source law for the official
birth–death model (birth rate `1 * X`, death rate `1.1 * X`, initial amount
100). The tests compare its exact mean and standard deviation with pinned
SSTS result rows and calculate the fourth-moment scale of the standardized
variance statistic. These tests validate the independent oracle and its
calibration only; they do not execute BNG3 or establish a product pass.

Run the deterministic prerequisite checks with:

```sh
python -m pytest \
  --confcutdir=tests/validation/release/cases/issue-159 \
  -q tests/validation/release/cases/issue-159/test_stochastic_00003_law.py
```

They require Python and pytest only.

`calibrate_stochastic_00003.py` is a separate, fixed-seed simulation of the
exact birth–death transition law. It estimates how often the official
standard-deviation statistic exceeds the configured `(-5, 5)` band under the
correct source model. Its output is diagnostic evidence only and never
overrides the official SSTS classification. The calibration command is:

```sh
python tests/validation/release/cases/issue-159/calibrate_stochastic_00003.py \
  --output /tmp/stochastic-00003-calibration.json
```

It requires NumPy. Defaults are fixed at 100 independent ensembles, 40,000
trajectories per ensemble, seed `2581028`, and the 50 official output times.
The sample-size, seed, and statistic are recorded in its JSON output.

The archived run 40797931585 used BNG3 commit
`da285a8b8311ad4b959919649a5682b77d995dcb`, official suite commit
`cf38585fac5de8e0e90112febb62851ee2181816`, base seed `1000000`, and 40,000
trajectories. It reported five official SD violations at output indices
41, 43, 44, 45, and 46, while all mean checks passed. The independent
source-law calibration run used PCG64 seed `2581028`: 49/100 exact-law
ensembles had at least five SD-band violations (Wilson 95% interval
0.3942–0.5865), and 30/100 had at least five consecutive violations (Wilson
95% interval 0.2189–0.3958). These rates support a statistical-calibration
hypothesis; they do not establish the final-main SSTS result or prove the
archived BNG3 sample was correct.

The full hosted acceptance command remains the SSTS validator, with the
official suite revision and environment lock from provenance:

```sh
python scripts/ci/validate_sbml_test_suite.py \
  --suite-dir "$OFFICIAL_SSTS_DIR" \
  --product-checkout "$BNG3_PRODUCT_CHECKOUT" \
  --categories semantic stochastic \
  --stochastic-seed-base 1000000 \
  --isolate-cases --case-timeout 60 --jobs 4 \
  --lock-file "$SSTS_VERIFICATION_LOCK" --lock-wait 1800 \
  --artifacts-dir "$SSTS_ARTIFACTS_DIR/cases" \
  --gate-selected-cases --json "$SSTS_ARTIFACTS_DIR/report.json"
```

The release workflow owner must wire the prerequisite pytest command and
calibration artifact separately; this case directory is not automatically
discovered by CI. Keep the official verdict unchanged until final-main evidence
and a separately reviewed harness diagnostic are available.
