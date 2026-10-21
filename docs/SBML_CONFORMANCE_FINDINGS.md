# SBML conformance findings from the official-reference comparison

These are the defects the official SBML Test Suite comparison exposed once the
harness could actually measure the two families it had been refusing to
compare: models with **scheduled actions** and **stochastic** cases.  Before
that, 537 of the campaign's gaps were *harness-side* - the comparison could
not be made, so nothing was known about the model.  Each finding below is a
real defect in BNG3's own behaviour (or an explicit scope boundary) that
nothing else in the campaign could see.

Every finding records the case ids, the mechanism, the expected behaviour with
its specification citation, the observed behaviour, a minimal reproducer, and
its classification:

* **Atomizer defect** - the generated model does not implement the source
  semantics.
* **Engine defect** - the native engine executes the generated model
  differently from the specification or from BNG2.
* **Harness defect** - the comparison did not measure what it should.
* **Scope boundary** - the case cannot be compared point-wise by design.

The reproducer commands assume the pinned suite checkout at
`/tmp/bng3-ssts-20261016` and the worktree source on the path:

```bash
PYTHONPATH=python:build/cpp python scripts/ci/validate_sbml_test_suite.py \
  --suite-dir /tmp/bng3-ssts-20261016 --only-case semantic/00369 \
  --json /tmp/finding-00369.json
```

---

## 1. `setConcentration` sets the species amount, not its concentration

* **Classification:** engine defect (BNG2 parity).
* **Cases:** 39 official-reference failures, all of them action-bearing
  semantic cases whose trajectory diverges at the first scheduled action:
  `00369 00370 00371 00372 00373 00426 00427 00428 00429 00430 00431
  00679 00680 00681 00682 00683 00684 00689 00690 00743 00744 00745 00746
  00747 00749 00750 00763 00764 00765 00766 00767 00768 00769 00770 01504
  01507 01508 01509 01511`.
* **Mechanism:** an SBML event assigns a species' *value*.  For a species
  with `hasOnlySubstanceUnits="false"` that value is the **concentration**;
  the species' amount is `value * compartmentSize`.  The Atomizer lowers the
  assignment to the BNGL action `setConcentration("<pattern>", "<value>")`,
  but BNG3's `setconcentration` action writes the value straight into the
  network species' **amount**
  (`cpp/actions/ActionDispatch.cpp`, `setconcentration` ->
  `network->species.get(*found).setAmount(value)`).  For a compartment whose
  size differs from 1 the post-event state is therefore off by the volume
  factor.
* **Expected behaviour:** the SBML specification, Level 3 Version 2 Core,
  section 4.11 ("Events") and section 3.1.5 ("Species"): the quantity a
  species carries is its amount, and its *value* in expressions is the
  concentration unless `hasOnlySubstanceUnits="true"`.  An event assignment
  sets that value.  BNG2 agrees: `legacy/perl/Perl2/BNGModel.pm`
  `sub setConcentration` writes `$model->Concentrations->[$spec->Index - 1]`,
  the concentration array, not the amount.
* **Observed behaviour:** for `semantic/00369` (compartment volume 0.1) the
  official reference and libRoadRunner on the *source* SBML both give
  `S2(0.5) = 0.1326567`; the scheduled action gives `S2(0.5) = 0.9951` -
  exactly the "amount 1" reading instead of the "concentration 1" reading.
* **Minimal reproducer:** `semantic/00369`; the divergence appears at the
  first official output point after the scheduled action (index 5 of 51) and
  the other two species agree until then.
* **Note:** the same defect is visible in the semantic cases only when the
  compartment size differs from 1; with a unit compartment the amount and the
  concentration coincide.

## 2. A `boundaryCondition` species is unreachable by the scheduled action

* **Classification:** Atomizer defect.
* **Cases:** 14 official-reference failures, all with the same dispatcher
  refusal: `00375 00377 00378 00380 00381 00383 00432 00434 00435 00437
  00438 00440 01779 01780`.
* **Mechanism:** for a source species with `boundaryCondition="true"` the
  Atomizer emits a `$`-prefixed seed pattern (`@C:$M_S2()`), which marks
  the species fixed in the generated network, while the event assignment
  still names the unprefixed pattern (`@C:M_S2()`).  The dispatcher's
  species lookup matches the network label (`@C::$M_S2()`) and refuses the
  action: `setConcentration target species not found: @C:M_S2()`.
* **Expected behaviour:** the SBML specification, Level 3 Version 2 Core,
  section 3.1.3 (`boundaryCondition`): a boundary species may not be changed
  by a *reaction*, but an **event assignment may change it**.  The generated
  model therefore has to keep the species assignable, or the Atomizer has to
  refuse the case explicitly.
* **Observed behaviour:** the action block cannot be executed at all, so the
  case cannot be compared with the official reference; the harness reports
  the dispatcher's own refusal.
* **Minimal reproducer:** `semantic/00375`; the generated action block is
  `setConcentration("@C:M_S2()", "1")` while the seed is
  `@C:$M_S2() 2`.
* **Possible fixes:** emit the action target with the same `$` prefix the
  seed uses, or drop the `$` prefix and let the model keep the species
  assignable, or refuse the case with an Atomizer diagnostic when a boundary
  species is the target of an event assignment.

## 3. A rate law on a concentration-valued species is not scaled by the compartment volume

* **Classification:** Atomizer defect.
* **Cases:** `stochastic/00011` and `stochastic/00018` (100 of 100 official
  mean/standard-deviation acceptance tests violated in each).
* **Mechanism:** both models use the kinetic law `Lambda * X` where `X` is a
  species with `hasOnlySubstanceUnits="false"` (so `X` is the concentration)
  in a compartment of size 2 (case 00011) or 0.5 (case 00018).  The
  generated rule keeps the rate constant unscaled
  (`Birth: @Cell:M_X() -> @Cell:M_X() + @Cell:M_X() 0.1`), so the propensity
  is `Lambda * amount` instead of `Lambda * amount / V`.
* **Expected behaviour:** the SBML specification, Level 3 Version 2 Core,
  section 3.1.5 and the kinetic-law rules of section 4.3: a rate law is
  evaluated with the species' *values*, and the value of a species with
  `hasOnlySubstanceUnits="false"` is `amount / compartmentSize`.  The
  equivalent BNGL rate constant is therefore `Lambda / V`.
* **Observed behaviour:** the BNG3 ensemble decays like `Lambda * amount`
  and misses the official mean by up to 91 standard errors.
* **Minimal reproducer / confirmation:** re-running the same model with the
  rate constant divided by the compartment volume reproduces the official
  reference exactly (`X(t=1) = 99.50125` against the reference
  `99.50125`), and the same model with the unscaled constant gives
  `99.005` (`100*exp(-0.01)`), which is the amount-based reading.

## 4. The multi-worker CPU batch SSA is not reproducible for a fixed seed

* **Classification:** engine defect (reproducibility).
* **Cases:** not a per-case verdict - it invalidates the *measurement* of
  every stochastic case that uses the CPU batched sampler.
* **Mechanism:** `simulate_batch_ssa_cpu(..., threads=4)` draws different
  trajectories for the same `base_seed` and batch size than
  `threads=1`, and repeats differently on each invocation.  The single-worker
  path and the GPU path are both exactly reproducible.
* **Expected behaviour:** a seeded sampler is reproducible: the same seed
  must select the same trajectory streams.  The repository's own GPU
  evaluation (`docs/GPU_BATCH_SSA_EVALUATION.md`) states the CPU and GPU
  samplers are validated against each other with trajectory-wide two-sample
  Z-tests, which requires a deterministic CPU reference.
* **Observed behaviour:** the same command twice gives different ensemble
  means (for `stochastic/00030` at `t=50`: `3.618` and `3.938`, against an
  ensemble standard deviation of `3.75`), and the trajectories differ from
  the single-worker result.
* **Minimal reproducer:** run `simulate_batch_ssa_cpu` twice with
  `base_seed=1000000`, `batch_size=2000`, `threads=4` and compare
  `event_counts` per trajectory.
* **Mitigation in the harness:** the conformance gate uses a single CPU
  worker so that a verdict is reproducible, and records the engine and the
  seed policy with every case.

## 5. `semantic/01592` is a random-event-execution test

* **Classification:** scope boundary.
* **Cases:** `semantic/01592`.
* **Mechanism:** the model fires one of two events every 0.01 s **at
  random** (the case notes: "every .01 seconds, one fires and the other does
  not, at random"), and the official reference is one sample of that
  stochastic process.  The Atomizer lowers the case into 10,000 scheduled
  phases, one per firing period.
* **Expected behaviour:** the official reference cannot be reproduced
  point-wise by a deterministic simulator; the case belongs with the
  stochastic suite.
* **Observed behaviour:** the generated model's `S` differs from the
  reference by up to 99.99, and the 10,000 phases do not fit the gate's
  per-case time budget.
* **Minimal reproducer:** `semantic/01592`; the case notes name it a
  "RandomEventExecution" test.
* **Handling in the harness:** the case is reported as `unsupported` with
  the reason that the generated scheduled actions exceed the documented
  phase budget - an explicit refusal, never a pass and never a failure.

## 6. The official reference does not track the boundary "Sink" species

* **Classification:** scope boundary (reference data).
* **Cases:** `stochastic/00006`, `stochastic/00024`, `stochastic/00026`.
* **Mechanism:** the models add a boundary species `Sink` that accumulates
  the deaths, but the analytic reference the suite inherited from the DSMTS
  reports the `Sink` as identically zero (the DSMTS mean/sd files carry
  zeros for the column).
* **Expected behaviour:** the official reference is what the suite
  publishes; a correct simulator cannot match a placeholder.
* **Observed behaviour:** the harness detects that the reference reports the
  variable as identically zero at every output time and says so in the
  failure reason instead of reporting a bare numeric mismatch.
* **Minimal reproducer:** `stochastic/00006`; the reference's `Sink-mean`
  and `Sink-sd` columns are zero for all 51 output points while the model
  accumulates the sink.

## 7. A generated network with no reaction is not comparable

* **Classification:** Atomizer defect (degenerate lowering), reported as
  *not comparable* by the harness.
* **Cases:** `semantic/01423` and `semantic/01431` (their generated network
  contains no reaction: the Atomizer lowers the source's negative-rate
  reaction to a self-loop, `J0: @C:M_A() -> @C:M_A() 1 TotalRate`).
* **Expected behaviour:** a reaction whose rate is negative is not a valid
  SBML model; the Atomizer already reports it
  (`Reaction "J0" has a negative numeric rate (-1); reversed the reaction
  sides and emitted ...`), but the emitted model has no reaction at all.
* **Observed behaviour:** the generated trajectory is flat.
* **Handling in the harness:** a case whose generated network has no
  reaction while the source model has some is reported as `unsupported` -
  "the generated network contains no reaction ... the generated model is
  degenerate, so its flat trajectory is not comparable with the official
  reference".  It is never reported as a pass over a flat trajectory.

## 8. Other newly measured mismatches

* **Classification:** Atomizer defects, not yet reduced to a single
  mechanism.
* **Cases:** `semantic/00963 00967 01701 01702 01715 01716` (the
  trajectory diverges at a scheduled action that assigns a *rate-rule state*,
  so the assignment does not have the effect the source event has) and
  `semantic/00707 00736 00929 01466 01717 01719 01720 01721` (the
  trajectory diverges before the first scheduled action).
* **Handling:** the harness reports the numeric mismatch with the official
  reference, which is the correct verdict; the next agent reduces them.

---

## Measurements that are *not* findings

* `semantic/01592` timed out in one hosted run.  Re-run uncontended it
  completes in 11 s of wall time; the timeout was contention plus the
  10,000-phase action block, and the phase budget now reports the case as
  not comparable before any comparison runs.
* The `Lean 4.33.1 kernel and NFnext contracts` job failed with
  `SSL connect error ... releases.lean-lang.org/...` - a download error
  inside the runner image, in a workflow this change does not touch.
* The first full-suite measurement of this work resolved the *stale
  installed* `bionetgen` from `site-packages` instead of the worktree
  source, which moved 76 unrelated cases.  A measurement that runs a
  different package than the one under test is a measurement error; the
  harness records `runtime_provenance.bionetgen_package_path` so that this
  is checkable.
