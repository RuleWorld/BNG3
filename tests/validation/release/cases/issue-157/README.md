# Issue 157 dynamic-event acceptance

## Official semantic/00966 tie-order acceptance

`semantic-00966-source.xml` is the pinned official SBML Test Suite input
`semantic/00966` from revision
`cf38585fac5de8e0e90112febb62851ee2181816` (SHA-256
`ca548837a5bd90def8861db03cc287849ce2b46084de438938d80e431bd28262`).
The copied official case settings are pinned in
`semantic-00966-settings.txt` (SHA-256
`1004504c1034c3d0141221ff9cd8b4c2e57f2932a7515840222c87f6c1a13053`) and
validate the start time, 1000-unit duration, 1000 requested steps, and
`S, error` official outputs.
`oracle_00966.py` validates the source with libSBML and checks the exact
equal-priority, nonpersistent event structure before applying any expected
law. The two 0.01-increment events share a trigger and reset the same clock;
when either executes, the competing nonpersistent trigger is no longer true.
The 16-event source groups then classify Q increments into the 17 `chi0` to
`chi16` counters.

The acceptance runner freshly translates the original SBML for each fixed seed
and runs the generated BNGL through the native BNG3 ODE/event runtime. Read-only
BNGL functions expose the source parameters for checking; they do not change
event semantics. There is no pointwise comparison to the official random
trajectory and no BNG3-generated expectation.

The statistical design is fixed before draws: seeds 1–16, 0–1000 time units,
1001 unit-spaced output samples, 100,000 tie decisions per seed, and 6,250
source-defined groups of 16 decisions. Each seed checks Q's total against
`Binomial(100000, 1/2)` and every histogram counter `chi_k` against
`Binomial(6250, choose(16,k)/2^16)`. These are two-sided exact binomial tests.
Bonferroni controls familywise error at `1e-6` across 16 × 18 = 288 tests;
the per-test cutoff is `1e-6/288`. This control does not require the histogram
tests to be mutually independent. The source law assumes independent, fair
resolution of each tie; finite seeded runs check that randomized tie behavior,
not a source-mandated stochastic interpretation or pathwise parity.

The deterministic invariant is `S = Q + R`, with one total increment of 0.01
per 0.01 time interval and 100,000 total increments at time 1000. The allowed
sum error is the standard `gamma_n` floating-point bound for 100,000 additions
of 0.01 plus one final addition of Q and R. Each seed directory retains the
fresh translation, translation digest, full sampled observations and check
report. `run.json` records the source, official suite identity, upstream-lock,
product revision, native extension and CLI digests, predeclared seed budget,
and partial/completed status.

Pure oracle and negative-fixture checks:

```sh
PYTHONPATH=tests/validation/release/cases/issue-157 \
  python -m pytest -q tests/validation/release/cases/issue-157/test_00966_oracle.py
```

Run the full acceptance against a built product. Supply the `suite-identity.json`
produced by the upstream-locked SSTS fetch, and use the repo's freshly built
native extension and `bng_cpp`. The runner requires `bionetgen` from exactly
`<repo-root>/python/bionetgen` and the imported native extension from the same
build directory as `bng_cpp`; it rejects an installed package from another
checkout. Ensure the current product has both targets built with Python
bindings enabled:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=ON
cmake --build build --target bng_cpp _bionetgen_cpp
```

Then run:

```sh
PYTHONPATH=python:build/cpp:tests/validation/release/cases/issue-157 \
  python tests/validation/release/cases/issue-157/run_00966_acceptance.py \
  --source /path/to/sbml-test-suite/cases/semantic/00966/source.xml \
  --suite-identity /path/to/ssts-evidence/suite-identity.json \
  --repo-root "$PWD" --bng-cpp "$PWD/build/cpp/bng_cpp" \
  --work-dir /path/to/retained-artifacts/semantic-00966
```

The runner stops on a harness error but retains all finished seed artifacts.
A green run is limited to this pinned source, product build, fixed seeds,
1000-unit horizon and the statistics/invariant above. Full suite qualification
and hosted issue acceptance remain separate.

## Reduced analytic event controls

`test_dynamic_threshold.py` isolates the failed trigger shape in official SBML
Test Suite case `semantic/00966`: a recurring `time - reset >= 0.01` event
increments a discrete counter, and a second event fires when
`floor(ticks / 16) >= 1`. The official source model has two equal-priority
increment events; that random execution order makes its single official
reference trajectory unsuitable for pointwise conformance. This reduced model
uses one increment per period and checks the independent analytic schedule:
8 events at `t=0.085`, then 16 events and `complete=1` at `t=0.165`.

The first test validates the authored SBML source with libSBML and checks its
sampled trajectory with libRoadRunner. The native tests run a manually lowered
BNGL `bng3_events` model through the public API. A control containing only the
recurring `time - reset` trigger checks that root independently; the second
adds the floor trigger and checks that it fires after the sixteenth discrete
update. These tests isolate native event execution and do not test Atomizer's
translation. The floor-trigger test is expected to fail on current source at
the root-surface guard because `floor(ticks / 16)` is not recognized as a
dynamic trigger side.

Run from the repository root after the SBML dependency preflight has installed
NumPy, pytest, libSBML, libRoadRunner and this worktree's freshly built native
extension:

```sh
PYTHONPATH=python:build/cpp python -m pytest -q \
  tests/validation/release/cases/issue-157/test_dynamic_threshold.py
```

The full official suite and issue acceptance remain CI work. This directory is
not yet discovered by a CI workflow; wire this command into the issue-157
acceptance job when that lane is added.
