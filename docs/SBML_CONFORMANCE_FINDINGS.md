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
* **Cases:** 25 official-reference failures, all of them action-bearing
  semantic cases whose trajectory diverges at the first scheduled action:
  `00369 00370 00371 00373 00426 00427 00428 00429 00430 00431 00682 00683
  00684 00690 00744 00745 00747 00763 00764 00765 00766 00767 00768 00769
  00770`.
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
  section 4.12 ("Events") and section 4.6 ("Species"): the quantity a
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
  section 4.6.6 ("The constant and boundaryCondition attributes"): a boundary
  species may not be changed
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

* **Classification:** Atomizer defect.  **CLOSED** on
  `campaign/fix-concentration-rate-law` (pull request #363): the lowering now
  carries the compartment volume, `stochastic/00011` reproduces the official
  reference, and the rule is stated in general below.
* **Cases:** `stochastic/00011` (all official mean/standard-deviation
  acceptance tests violated).  The companion case `stochastic/00018` was
  fixed on `main` by the multiplicative compartment factor (PR #342) after
  this finding was recorded, and now reproduces the reference.
* **Mechanism:** both models use the kinetic law `Lambda * X` where `X` is a
  species with `hasOnlySubstanceUnits="false"` (so `X` is the concentration)
  in a compartment of size 2 (case 00011) or 0.5 (case 00018).  The
  generated rule keeps the rate constant unscaled
  (`Birth: @Cell:M_X() -> @Cell:M_X() + @Cell:M_X() 0.1`), so the propensity
  is `Lambda * amount` instead of `Lambda * amount / V`.
* **Expected behaviour:** the SBML specification, Level 3 Version 2 Core,
  section 4.6 ("Species") and the kinetic-law rules of section 4.11.7: a rate
  law is
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
* **The general rule the fix implements.**  Section 4.11 ("Reactions") makes
  the kinetic law's value the reaction's *extent* rate, and section 4.6
  ("Species") makes a species' value its amount when it has
  `hasOnlySubstanceUnits="true"` and its concentration otherwise.  A law with
  `m` reactant factors of which `a` are amount-valued therefore has the
  value `k * n**m / V**(m - a)`, and BNGL's own mass-action rate divides the
  extent rate by one volume factor per reactant beyond the first, so the
  equivalent BNGL constant is

      k * V**(a - 1)

  plus one power of `V` when the law multiplies by the compartment's size and
  minus one when it divides by it.  The case `a = m` is the amount-based
  correction of PR #319, so the two compose instead of double-counting.  The
  mixed law (one amount-valued and one concentration-valued operand) needs
  `V**0`: the concentration reading and BNGL's own volume factor cancel.
  The rule is checked against libRoadRunner 2.10.0 on the source SBML for
  every operand shape, and it does not double-count the volume with the
  scheduled-action conversion of PR #361: a model that combines a
  concentration-valued rate law with a concentration-valued event assignment
  states the volume once in each place.
* **Numbers:** `stochastic/00011` went from 100 of 100 official mean and
  standard-deviation acceptance tests violated to 0 violated; the official
  mean at `t = 1` is `99.50125` and the ensemble gives `99.5135` with a
  standard deviation of `3.2148` against the reference's `3.228244105`.
  Against libRoadRunner 2.10.0 on the source SBML, the maximum relative error
  of the lowered model's amount trajectory is 5.4e-11 (unimolecular), 2.9e-11
  (bimolecular) and 1.1e-10 (mixed); before the fix the concentration-valued
  shapes were 83%, 28% and 80% off.


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

* **Classification:** scope boundary, now reported as *not comparable*.
* **Cases:** `semantic/01592` and the other cases of the same construct
  (`00952 00953 00962 00964 01589 01591 01599 01605 01626 01627`).
* **Mechanism:** the model fires one of two events every 0.01 s **at
  random** (the case notes: "every .01 seconds, one fires and the other does
  not, at random"), and the official reference is one sample of that
  stochastic process.  The Atomizer lowers the case into 10,000 scheduled
  phases, one per firing period.
* **Expected behaviour:** the official reference cannot be reproduced
  point-wise by a deterministic simulator; the case belongs with the
  stochastic suite.  The SBML specification, Level 3 Version 2 Core, Release
  2, section 4.12.3 ("Priority") requires two events that are executed
  simultaneously and whose priority values are mathematically equal to "be
  triggered in a random order", and section 4.12.2 ("The persistent attribute
  on Trigger") requires a simultaneous event whose trigger is not persistent
  and whose trigger expression has become false again not to be executed at
  all.  `Qinc` and `Rinc` satisfy both rules, so exactly one of them
  executes and the choice is a random draw.  The suite's own test tag
  `RandomEventExecution` states the same: "correct simulation of the model
  depends on randomly choosing which event to execute first".
* **Observed behaviour:** the generated model's `S` differs from the
  reference by up to 99.99, and the 10,000 phases do not fit the gate's
  per-case time budget.
* **Minimal reproducer:** `semantic/01592`; the case notes name it a
  "RandomEventExecution" test.
* **Handling in the harness:** the case is reported as `unsupported` - the
  gate's *not comparable* verdict - with the reason that names the
  construct: "the source model's events Qinc, Rinc share one trigger and one
  priority, so SBML Level 3 Version 2 Core, Release 2, section 4.12.3
  requires them to be executed in a random order; the official reference is
  one draw of that random process, so the case is not comparable
  point-wise".  It is never a pass and never a failure.  The manifest
  records the gap's `side` as `harness`, because nothing is wrong with the
  model.

## 6. The official reference does not track the boundary "Sink" species - FIXED

* **Classification:** scope boundary (reference data), now reported as *not
  comparable*.  **CLOSED** on `campaign/ssa-boundary-and-rate-rules`: the
  boundary was a *symptom* of the engine defect in section 13, and with that
  defect fixed the three cases reproduce the published reference exactly.
* **Cases:** `stochastic/00006`, `stochastic/00024`, `stochastic/00026`.
* **Mechanism:** the models add a boundary species `Sink` that accumulates
  the deaths, but the analytic reference the suite inherited from the DSMTS
  reports the `Sink` as identically zero (the DSMTS mean/sd files carry
  zeros for the column).
* **Expected behaviour:** the official reference is what the suite
  publishes; a correct simulator cannot match a placeholder.  The SBML
  specification, Level 3 Version 2 Core, Release 2, section 4.6.6 ("The
  constant and boundaryCondition attributes on Species") puts a species with
  `boundaryCondition="true"` on the boundary of the reaction system: its
  "amount is not determined by the reactions", so no differential equation is
  derived from the reaction definitions for it.  The official reference
  describes the reaction system, so it reports such a species as identically
  zero and does not describe it at all.
* **Observed behaviour (before the fix of section 13):** the harness detects
  that the reference reports the variable as identically zero at every output
  time while the model accumulates it.
* **Minimal reproducer:** `stochastic/00006`; the reference's `Sink-mean`
  and `Sink-sd` columns are zero for all 51 output points while the model
  accumulates the sink.
* **Handling in the harness (before the fix of section 13):** the case is
  reported as `unsupported` - the gate's *not comparable* verdict - with the
  reason that names the quantity: "the official reference does not track the
  boundary species Sink: the reference reports Sink as identically zero at
  every output time because a boundary species is not determined by the
  reactions, while the BNG3 model accumulates it, so the comparison on that
  quantity does not apply".  The comparison on every other quantity of the
  case - `X` in these cases - is unchanged, and a mismatch there is still a
  failure.  The manifest records the gap's `side` as `harness`, because
  nothing is wrong with the model.
* **What closed it.**  That guard is a *guard*, not a verdict: it fires when
  the model **accumulates** a boundary species, and the model accumulated it
  because the direct SSA did not honour the model's constant-species marker
  (section 13).  With the marker honoured the model keeps `Sink` at 0, the
  reference's identically-zero column is exactly what the model produces, the
  mismatch the guard was written for does not occur, the guard no longer
  fires, and the three cases pass the published reference.  The reference was
  never the problem.

## 7. A generated network with no reaction is not comparable

* **Classification:** harness defect (the guard could not tell an inert
  source model from a degenerate lowering).  **CLOSED** on
  `campaign/fix-concentration-rate-law` (pull request #363): the guard now
  refuses only when a source reaction can change a species, so the three
  affected cases are measured and pass.
* **Cases:** `semantic/01422`, `semantic/01423` and `semantic/01431` (their
  generated network contains no reaction: the Atomizer lowers the source's
  reaction to a self-loop, `J0: @C:M_A() -> @C:M_A() 1 TotalRate`).
* **Why the network has no reaction.**  Section 4.11 ("Reactions") of the SBML
  Level 3 Version 2 Core makes a species' amount change by
  `stoichiometry * extent rate`, so a reaction whose *net* stoichiometry is
  zero for every one of its species cannot change any species' amount.  All
  three source models have exactly one reaction and its net stoichiometry is
  zero (`A -> A`, `A + B -> A + B` and `A + A -> A`).  The Atomizer lowers
  such a reaction to a self-loop, which is the correct BNGL spelling, and the
  network generator drops a rule with no effect on the state - the same
  thing BNG2 does.  The generated model is therefore *flat because the source
  model is flat*, not because the lowering dropped an effect.
* **Expected behaviour:** a source model built only from inert reactions has
  a flat trajectory by construction, so the generated model's flat
  trajectory is the same dynamics and the two are comparable.  For
  `semantic/01423` the rate is negative (`-1`), which is not a valid SBML
  kinetic law; the Atomizer reports that
  (`Reaction "J0" has a negative numeric rate (-1); reversed the reaction
  sides and emitted ...`) and reverses the sides, which leaves the net
  stoichiometry - and therefore the dynamics - unchanged.
* **Observed behaviour:** the harness reported the cases as `unsupported` -
  "the generated network contains no reaction ... the generated model is
  degenerate, so its flat trajectory is not comparable with the official
  reference" - even though the official reference is flat for the same reason.
* **Handling in the harness:** the guard now asks whether a source reaction
  can change a species and refuses only then, so a degenerate *lowering* is
  still never reported as agreement over a flat trajectory.  The three cases
  are measured against the official reference and pass.  The suite's other
  degenerate lowerings are unaffected: thirteen cases in the pinned suite have
  only inert reactions, and the other ten still produce a network with a
  reaction.

## 8. Other newly measured mismatches

* **Classification:** Atomizer defects.  **REDUCED** to four mechanisms on
  `campaign/fix-concentration-rate-law` (pull request #363) and
  `campaign/fix-rate-rule-event-assignment` (pull request #366); all four are
  fixed.
* **Cases:** `semantic/00963 00967 01530 01531 01532 01533 01701 01702
  01715 01716` and `semantic/00707 00736 00929`.

### 8a. The `arccot` folding disagreed with the emitted model - FIXED

* **Cases:** `semantic/01530`, `semantic/01531`, `semantic/01532`,
  `semantic/01533`; all four now pass.
* **Mechanism:** the shared MathML built-in table lowers `arccot(x)` onto
  `atan(1/(x))` and evaluates the call the same way, but the event
  assignment's folder used `atan2(1, x)`, whose result lies in `(0, pi)`.
  For a negative argument the two differ by `pi`, so the folded parameter
  and the emitted model described different systems.  The suite's own
  reference for these cases reports `P44 = -1.47112767` for
  `P44 = arccot(-0.1)`, which is `atan(1/x)`, and libRoadRunner 2.10.0 on
  the source SBML reports the same value.
* **Fix:** the event folder uses `atan(1/x)`, the convention the emitted
  model computes.

### 8b. A trigger's truth was computed two different ways - FIXED

* **Cases:** `semantic/00963`, `semantic/00967`.  The Atomizer defect is
  fixed; the corrected lowering needs 1001 simulation phases, one more than
  the harness's documented budget of 1000, so the harness reported the two
  cases as *not comparable* instead of as a numeric mismatch.  The budget is
  now 2000, so both cases are compared and both reproduce the official
  reference (about 2 s per case).
* **Mechanism:** the event expander detects a trigger's crossing with a
  tolerance, then re-evaluated the trigger's own expression to decide
  whether a scheduled firing was still valid.  For
  `time - reset >= 0.01` with `reset = 0.02` at `t = 0.03` the two
  disagree: `0.03 - 0.02` is `0.009999999999999998` in binary floating
  point, so the direct evaluation says the trigger is false at the very
  moment it crossed, and the expander cancelled the firing it had just
  scheduled.  A recurring reset event then stopped after its second firing:
  the generated action block had three phases instead of the 1001 the
  recurrence needs.
* **Fix:** every place that asks whether a trigger holds asks it the same
  way, through one helper that keeps the crossing tolerance.
* **Phase count.** The 1001 phases are the count the source itself implies:
  both models' events fire every 0.01 s over the official horizon, so the
  recurrence has 1000 firings and the action block one phase per firing.
  The harness sees the source's own count, not an artifact of the lowering.
* **The phase budget was too tight, and it is a cost limit.**  The budget
  guards the conformance gate's per-case time budget, not correctness: every
  phase is a separate integration and every phase adds a row to the
  dispatcher's trajectory file.  Measured on the pinned suite, the 1,001
  phases of `semantic/00963` cost about 2 s and the 10,000 phases of
  `semantic/01588` about 46 s, so about 4 ms per phase, against the CI's
  60 s per-case timeout.  The budget is now 2000: above every phase count
  the suite's models legitimately imply, below the one whose action
  execution alone does not fit the per-case budget.  It stays a phase count
  rather than a wall-clock limit because the per-phase cost depends on the
  model and the runner's load, so a time limit would make a case's verdict
  depend on where it ran.
* **The budget no longer hides a comparison that would succeed.**  The
  harness used to refuse *any* case whose official grid contained a phase
  boundary, before comparing it, because the dispatcher reports the
  phase-boundary sample before the phase's assignment is applied while the
  official reference reports the state after it.  The comparison now runs
  first and the convention only matters when it changes the verdict: a
  disagreement confined to those points is *not comparable*, and a
  comparison the official tolerance accepts is a pass.  `semantic/00967`'s
  only disagreement is 0.01 at its last grid point, inside the official
  tolerance of 0.06, so it passes on its merits.  `stochastic/00028` and
  `stochastic/00032` disagree by much more at their boundary and stay *not
  comparable*, with the reason naming the boundary rather than reporting a
  failure that is not a statement about the model.

### 8b-2. A phase-boundary sample is taken before the assignment - KNOWN

* **Cases:** `semantic/00967` (inside the official tolerance, so it passes),
  `stochastic/00028`, `stochastic/00032` (outside it, so they are *not
  comparable*).
* **Mechanism:** the native action dispatcher writes the sample at a phase's
  end time from the state before the phase's assignment is applied; the
  assignment takes effect for the following phase.  A probe on the native
  dispatcher confirms it: a block that integrates to `t = 1`, assigns a
  species and continues reports `1.0` at `t = 1` and `5.0` at the next
  sample.  The official reference reports the post-assignment state at the
  same instant, so the two conventions differ at a boundary by exactly the
  assignment's effect.  The harness cannot recover the post-assignment value
  at that instant from the trajectory, because the dispatcher never writes
  it.
* **Consequence:** a case whose official grid contains a phase boundary and
  whose assignment moves a requested output is not comparable point-wise.
  The harness says so with a reason that names the boundary.

### 8b-3. A random-order event model was refused for the wrong reason - FIXED

* **Cases:** `semantic/01588`.
* **Mechanism:** `semantic/01588` is a random-order event model like
  `semantic/01592`: its two competing events share one trigger and one
  priority, both are non-persistent, and both reset the trigger, so exactly
  one of them fires and which one is a random draw.  The harness detected
  that shape by grouping the events on the *text* of their priority, so it
  recognised `semantic/01592` (whose priorities are both written `1`) but
  not `semantic/01588` (whose priorities are `k1` and `0.01`, numerically
  equal because `k1` has the initial value `1 * 0.01`).  `semantic/01588`
  therefore fell through to the action path and was refused by the phase
  budget, with a cost reason, although the reason it cannot be compared
  point-wise is the random order.  This is the harness's own grouping, not
  the Atomizer's lowering: the Atomizer lowers both models the same way.
* **Why it matters:** the refusal was accurate about the cost but it named
  the wrong cause, and it hid that the case is not comparable for a reason
  no budget can fix.  Comparing it once the budget is raised shows the
  expected disagreement: the reference's `S` grows by 0.01 per firing and
  the run's `S` grows twice as fast, because the run picks the same event
  every time where the source requires a random choice.
* **Fix:** the grouping compares the folded *value* of the priority when
  the expression can be folded and falls back to its text when it cannot.
  Only constant parameters are resolved, so a priority that varies over
  time still falls back to the text and no pair is merged that the
  specification does not merge.  `semantic/01588` is now refused with the
  random-order reason, the same reason `semantic/01592` gets.

### 8c. A state-triggered event ignored the reaction's local parameters - FIXED

* **Cases:** `semantic/00707`, `semantic/00736`; both now pass.
* **Mechanism:** section 4.11.6 ("LocalParameter") of the SBML Level 3
  Version 2 Core makes a reaction's local parameters shadow the model's
  parameters of the same name, but the species trajectory that a crossing
  time is computed from resolved the rate law's symbols against the model's
  parameters only.  `semantic/00707` fires its event at `ln(4) / 0.75`
  instead of `ln(4) / 5`, because the global `k = 0.75` shadowed the
  reaction's local `k = 5`; `semantic/00736` has the same shape with the
  global and local `k1`.
* **Fix:** the rate law a species' trajectory is read from is resolved with
  the reaction's local parameters substituted.

### 8d. An event with an initially true trigger fired - FIXED

* **Case:** `semantic/00929`; it now passes.
* **Mechanism:** section 4.12.2 ("Trigger") of the SBML Level 3
  Version 2 Core initializes a trigger's value from `triggerInitialValue`
  and fires the event only when that value *transitions* from false to true.
  A trigger that is already true when the simulation starts never rises, so
  the event does not fire at all.  The Atomizer scheduled the event anyway
  and set `S1 = 1` at `t = 0`, against the source's initial amount of
  `1.5e-4`.
* **Fix:** a trigger that is already true at `t = 0` with
  `triggerInitialValue="true"` does not fire the event.

### 8e. A scheduled action assigns a parameter, not the rate-rule state - FIXED

* **Cases:** `semantic/01701`, `semantic/01702`, `semantic/01715`,
  `semantic/01716`; all four now pass.
* **Mechanism:** a parameter that carries a rate rule is lowered to a
  synthetic state species (`M___rate_rule_state__k1()`), and the model's
  observable reports that species.  The event's assignment was lowered to
  `setParameter("k1", "3.2")`, which sets the *parameter*; the rate rule
  keeps driving the *species*, so the assignment had no effect on the
  quantity the reference reports - the reported value simply did not move
  with the assignment.
* **What the specification requires.**  Section 4.9.4 ("RateRule") makes a
  rate rule determine the variable's rate of change for the whole
  simulation, and section 4.12.5 ("EventAssignment") makes an event
  assignment set the variable's *value*, from which the rule then
  continues.  The two are not in conflict: the rule is in effect for
  `t > 0` and the assignment sets the value the rule owns.  The
  specification's restriction is the other way round - "a variable cannot
  be assigned a value in an EventAssignment object instance and also be
  assigned a value by an AssignmentRule" - because an assignment rule
  holds at all times; a rate rule does not, and the corpus contains the
  case (`semantic/01701` and its companions) with the official reference
  spelling out the result.  BNG2 has no event support at all, so there is
  no BNG2 behaviour to match; libRoadRunner 2.10.0 on the source SBML is
  the independent oracle, and it agrees with the official reference: the
  value is set at the event's *execution* time and the rate rule continues
  from it (`semantic/01701`: `P1` is 11.9 at `t = 3.1` and 11.5 at
  `t = 3.5`).
* **Fix:** the scheduled action reaches the state species that carries the
  rate-ruled parameter's value, so the assignment has the effect the source
  event has and the rate rule continues from the assigned value.
* **Numbers:** against `main` at `0b87c475` (conversion 1782 passed / 141
  unsupported / 0 failed), the official-reference stage goes from **1739
  passed / 180 unsupported / 4 failed** to **1743 passed / 180 unsupported /
  0 failed**: `semantic/01701`, `01702`, `01715` and `01716` move failed ->
  passed and nothing else moves.  The official-reference stage has no
  failures left.


## 9. A fast reaction's pseudo steady state is not an ordinary reaction

* **Classification:** Atomizer defect (model semantics).  **CLOSED** on
  `campaign/fast-equilibrium-solve` (pull request #370): the two shapes whose
  pseudo steady state is closed-form are now lowered exactly, and the rest
  stay refused with the construct that blocks them.
* **Cases:** the official SBML Test Suite cases whose source marks a reaction
  `fast="true"`: 34 cases in the pinned suite.  29 of them now reproduce the
  published reference (`unsupported` -> `passed`) and 5 stay `unsupported`
  with a construct-naming reason.

### The specification's requirement

SBML Level 3 Version 1 Core, section 4.11 ("Reactions"), and SBML Level 2
Core, section 4.13 ("Reactions"), which is section 4.9 in Level 2 Version 1,
do not describe a `fast="true"` reaction as merely faster.
The text reads:

> "The set of reactions having `fast`=`true` (known as *fast reactions*)
> should be assumed to be operating on a time scale significantly faster than
> the other reactions (the *slow reactions*). Fast reactions are considered to
> be instantaneous relative to the slow reactions. **Software tools should
> use a pseudo steady-state approximation for the set of fast reactions when
> constructing the system of equations for the model.**"

and

> "Note that the `fast` attribute has a significant effect on the mathematical
> interpretation of a model and **cannot be safely ignored** if a software
> tool does not implement support for the corresponding concept."

Level 3 Version 2 removes the attribute outright: "every Reaction in an
L3V2 model is equivalent to an SBML Level 3 Version 1 Reaction with a `fast`
value of false".  The appendix *Mathematical consequences of the `fast`
attribute on Reaction* gives the reduction itself: the fast subsystem
contributes the algebraic constraint `A1*v_f(x) = 0`, and the slow dynamics
follow from `B*dx/dt = B*A2*v_s` with `B` the left null space of `A1`.

So `fast` is a property of the *model*, not of the solver: the model is the
system of equations with the fast subsystem in equilibrium, and a tool that
does not build that system describes a different model.

### The published references agree

Every published `-results.csv` of these cases is the pseudo-steady-state
trajectory.  `semantic/00870` is already at `Kf1*A4 = Kr1*A2` at `t = 0`;
`semantic/00986` is exactly `B(t) = e^{-t}`, the solution of the reduced
one-reaction system; the cases' own notes say "the 'fast' reaction should go
to completion instantly".  Measured with libRoadRunner 2.10.0's exact CVODE on
the same models with the attribute cleared, the raw-ODE solution deviates
from every reference by 100x-53000x the suite's own tolerance, and
libRoadRunner refuses to load a `fast="true"` model at all ("Unable to
support 'fast' reactions").  Lowering a fast reaction as an ordinary
reaction would therefore have turned every refused case into a failed one.

### What the reduction is

The pseudo steady state of a fast reaction is an *algebraic* condition, not a
differential one, and it is closed-form for two shapes:

* **A rate that vanishes with one of the two species it converts.**  A rate
  of the form `c*X`, `c*Y` or `c*X*Y` (with `c` a time-independent constant)
  is zero exactly when the species it is proportional to is zero, so the
  infinitely fast relaxation holds that species at zero and lets the other
  absorb its amount, scaled by the stoichiometry ratio.  The fast
  subsystem's conserved combination `nu_P*R + nu_R*P` does not change while
  it relaxes.  The sign of `c` says which of the two species the reaction
  runs towards: a positive coefficient runs the reaction forwards and holds
  the reactant at zero, a negative one runs it backwards and holds the
  product at zero.  A conversion factor scales the amount a reaction moves
  (SBML Level 3 Version 2 Core, Sec. 4.11.7), so it scales the absorbed
  amount as well.
* **A rate that balances the two species it converts.**  A rate of the form
  `k_f*X - k_r*Y` is zero on the algebraic balance `k_f*X = k_r*Y`, and the
  slow reactions then move *along* that balance: the eliminated species
  changes at the slow reactions' scaled rate
  `k_r/(k_f*nu_X + k_r*nu_Y)` of the flux, and the fast subsystem's
  conserved combination changes at the slow reactions' own rate.  The
  reduction is a closed-form pre-solve of the initial condition (the fast
  subsystem is placed on the balance, conserving its combination) plus an
  exact rate substitution (the two species carry the reduced rates as rate
  rules, and the slow reaction keeps its own flux).

### What the cases show

| case | construct | outcome |
| --- | --- | --- |
| 00870 00872 00873 01051 01052 01053 | the reversible fast reaction `A4 <-> A2` with the rate `(Kf1*A4 - Kr1*A2)*C` | the balance `Kf1*A4 = Kr1*A2`; passed |
| 01399 | a rate over both converted species with a negative coefficient | the product is held at zero; passed |
| 01544 01545 01546 | a species or model conversion factor | the absorbed amount follows the conversion factors; passed |
| 01565 | 52 independent fast reactions whose rates carry a MathML built-in | each reduces on its own; passed |
| 01569 | two independent fast reactions whose rate constants an initial assignment sets | each reduces on its own; passed |
| 01567 | an algebraic rule fixes the fast reaction's rate constant | the fixed constant is a constant, so the reaction runs backwards; passed |
| 01571 01572 | a rate over both converted species with a non-unity stoichiometry | the absorbed amount follows the stoichiometry ratio; passed |
| 00871 00874 00875 00986 01396 01397 01547 01548 01549 01550 01551 01558 01559 01560 | a rate proportional to one species | the species is held at zero; passed |
| 00987 00988 | an event sets the fast reaction's rate constant | refused: "the fast reaction's rate constant is not a time-independent value" |
| 01398 | an event changes the fast reaction's stoichiometry | refused: "the fast reaction's stoichiometry is not a constant" |
| 01539 | a `delay` expression reads the converted species | refused: "species \"S1\" is read by a delay expression" |
| 01568 01570 | the fast reaction's rate constant follows a rule | refused: "the fast reaction's rate constant is not a time-independent value" |

The refused cases name the construct that blocks the reduction, and the
diagnostic keeps the `is marked fast` wording the campaign's gap taxonomy
matches, so the construct they are filed under does not change.

### Numbers

Against the published references, with the suite's own tolerance
(`abs(expected-actual) <= absolute + relative*abs(expected)`, read from each
case's `-settings.txt`):

| case | tolerance (abs, rel) | worst scaled error | variable |
| --- | --- | --- | --- |
| 00870 01051 | 1e-2, 1e-4 | 0.046 | A1 |
| 00872 01052 | 1e-2, 1e-4 | 0.331 | A3 |
| 00873 01053 | 1e-2, 1e-4 | 0.002 | A1 |
| 01399 | 1e-4, 1e-4 | 0.000 | S1 |
| 01544 01545 01546 | 1e-4, 1e-4 | 0.000 | S2 |
| 01565 | 1e-4, 1e-4 | 0.0001 | S33 |
| 01567 | 1e-4, 1e-4 | 0.000 | S1 |
| 01569 | 1e-4, 1e-4 | 0.000 | S1 |
| 01571 01572 | 1e-4, 1e-4 | 0.000 | S2 |

The residual of the six reversible cases is the reference's own integration
error: the published trajectory satisfies `A4 = 2*A2` to machine precision
(the balance holds exactly) and conserves `A1 + A3` to machine precision, and
the deviation from the exact reduced solution oscillates with the sign of a
fixed-step integrator's truncation error.

### The per-case diff over the whole pinned suite

Both whole-suite runs are against the pinned suite
`cf38585fac5de8e0e90112febb62851ee2181816` with `PYTHONHASHSEED=0` and
`PYTHONPATH=python:build/cpp`, and each report's
`runtime_provenance.bionetgen_package_path` points at the worktree under
test.

| stage | `origin/main` (`7f8bebe1`) | the branch |
| --- | --- | --- |
| conversion | 1782 passed / 141 unsupported / 0 failed / 0 timeout | 1797 passed / 126 unsupported / 0 failed / 0 timeout |
| round-trip structure | 1782 passed / 179 not tested | 1797 passed / 126 not tested |
| independent libRoadRunner comparison | 1782 passed / 179 not tested | 1797 passed / 126 not tested |
| official reference | 1743 passed / 180 unsupported / 0 failed / 0 timeout | 1758 passed / 165 unsupported / 0 failed / 0 timeout |

* **15 verdicts moved**, all of them this cluster's cases, all from
  `unsupported` to `passed`: 00870 00872 00873 01051 01052 01053 01399
  01544 01545 01546 01565 01567 01569 01571 01572.
* **0 regressions**: no case that passed on the base commit stopped
  passing, and the official-reference failure count is 0 on both sides.
* **No other record of the 1923 moved at all.**


---

## 10. The remaining official-suite event gap is not a scheduling gap - KNOWN

* **Cases:** `semantic/00965`, `00966`, `01000`, `01466`, `01590`
  (`events:untranslated`), `semantic/00988`, `01466` (`events:state-trigger-not-schedulable`),
  and `stochastic/00033`.
* **Mechanism:** the native `bng3_events` runtime now executes *several*
  events: it registers one root function per trigger, orders the events that
  are executed simultaneously by their priority (SBML L3V2 Core Sec. 4.12.3),
  does not execute a non-persistent event whose trigger has become false
  again (Sec. 4.12.2), and re-tests every trigger after an execution
  (Sec. 4.12.7).  The cases above still do not reach that runtime, and each
  of them is blocked by a construct the runtime does not have:
  * `00965`, `00966`, `01466` and `01590` assign **parameters** (`Q`, `R`,
    `reset`, ...), and the native runtime writes observable state.  Their two
    competing events also share one trigger *and* one priority, so the
    specification requires a random execution order: the official reference
    is one draw of that random process and the case is not comparable
    point-wise.  The harness already reports that shape with the
    `harness:random-event-execution` reason.
  * `00988` assigns the parameter `k2`, which is a reaction rate constant,
    and its model also carries a `fast` reaction.
  * `01000` mixes five time-triggered events with three state-triggered ones,
    assigns parameters, and watches a rate-ruled compartment.
  * `stochastic/00033` needs a state-triggered event in a **stochastic** run:
    the native runtime finds the trigger's rising edge with the continuous
    ODE solver, and a stochastic run needs jump scheduling instead.
* **What an event assignment to a parameter means, and what the Atomizer
  does with it.**  SBML L3V2 Core Sec. 4.12.4 (`EventAssignment`) makes the
  assignment set the *value* of the variable, and Sec. 4.12.5 fixes the
  instant at which that value is computed.  A parameter without a rule is
  therefore a mutable quantity, and the assignment is representable: the
  parameter becomes a state whose amount is the parameter's value, exactly as
  a rate-rule parameter does.  Sec. 4.9.3 draws the line: an `EventAssignment`
  may not share a variable with an `AssignmentRule`, because an assignment
  rule holds at all times while an event assignment sets the variable at one
  instant.  Such a model is invalid SBML, so the Atomizer must refuse it and
  name the construct rather than lower one of the two.
  The corpus shows that the parameter target is *not* what blocks the
  remaining cases: `semantic/01169` is blocked by its *dynamic* priority (see
  below) and `semantic/01000` by the mixture of scheduled and native events.
  The parameter target itself is a separate piece of work: it needs the
  state, the assignment action that reaches that state, and the harness's
  mapping of the reference's parameter onto it.
* **Consequence:** the event construct remains the largest Atomizer-side
  cluster of the campaign.  What is missing is a parameter as an event
  target, the random ordering of a same-priority group, and the stochastic
  jump scheduler.  Each of those is a separate piece of work, and none of
  them may be approximated: a model whose execution order is a random draw
  stays *not comparable*, and a model the runtime cannot execute stays an
  explicit refusal that names the construct.

## 11. A conjunction's root function is not monotone - KNOWN

* **Cases:** none of the pinned suite's cases is *failing* because of it; the
  cases that use a conjunction trigger (`semantic/00932`, `00933`, `01511`,
  `01675`-`01680`, `01703`, `01704`, `01710`, `01711`, `01717`, `01718`, ...)
  all pass.  `semantic/01575` and `semantic/01576` cannot be lowered at all
  today (see section 10 and section 12), so the defect is latent.
* **Mechanism:** the native runtime locates a trigger's rising edge with
  continuous root finding, and the root function of a *conjunction* is the
  **smallest** of the conjunct differences, because a conjunction holds only
  where every conjunct holds.  That function is continuous but not
  monotone: where the conjuncts cross, the minimum has a kink and a local
  maximum.  CVODE interpolates the crossing with a secant over the step that
  brackets it, and the solver's steps follow the output grid, so a step that
  contains the kink can return a crossing that is not the trigger's rising
  edge.  The event's execution time then depends on the output grid.
* **Evidence:** with the alias of section 12 in place, `semantic/01575`'s
  event (the trigger `k2 > 3.5 && k2 < 4` on a state that grows by one per
  second, so the rising edge is at `t = 2.5`) fires at `t = 2.5`, `t = 2.8` and
  `t = 3.37` with 20, 11 and 101 output steps respectively.
* **Consequence:** a conjunction trigger must not use the minimum as its
  root function.  The runtime needs **one root per conjunct** and has to
  decide the conjunction's rising edge from the conjuncts' truth at the
  crossing, which is also what removes the dependence on the output grid.

## 12. An algebraic rule the Atomizer cannot solve is a different construct - KNOWN

* **Cases:** `semantic/00761` (an algebraic rule the Atomizer does not
  apply), `semantic/01575` and `semantic/01576` (a rule it does apply).
* **Mechanism:** an `AlgebraicRule` states an equation, not a value, and the
  specification's own reading (Sec. 4.9.3) is that the equation *determines*
  the value of one of the symbols it mentions: "for at least one of the
  entities referenced in the rule's math element the value of that entity
  must not be completely determined by other constructs in the model ...
  there must also not be a rate rule or assignment rule for it".  That
  symbol is the dependent variable of the rule, and the rule is its
  definition.
  The modern Atomizer already applies the tractable form of this: the
  parser solves a *linear* rule for its dependent variable and lowers it
  as an assignment rule, so `semantic/01575`'s `k1 - k2 = 0` becomes the
  assignment rule `k2 = k1` (`k2` is the dependent variable, because `k1`
  carries the rate rule).  The generated model reports `k2` through the
  state of `k1`, so the event's assignment to `k1` carries `k2` with it,
  exactly as the published reference does.
  `semantic/00761`'s rule is a constant (`k2 - 0.9`), which the parser
  cannot turn into a dependent variable, so the model keeps the refusal.
* **What is still missing:** the *nonlinear* and *multi-equation* forms.
  Those are differential-algebraic systems: a simulator has to solve the
  equation together with the model's other rules and reactions, and the
  dependent variable's rate follows from the differentiated constraint.
  That is a DAE capability, not a diagnostic, and the Atomizer has no such
  solver.  Until it has one, such a model stays an explicit refusal that
  names the algebraic rule, and the event it carries stays untranslated.
* **Consequence:** `semantic/01575` and `semantic/01576` are blocked by
  section 11, not by the algebraic rule: their rule is applied today, and
  their trigger is a conjunction that the native runtime cannot yet locate
  reliably.
## 13. A boundary species is not honoured by the direct SSA - FIXED

* **Classification:** engine defect (the native engine executed the generated
  model differently from the specification).  **CLOSED** on
  `campaign/ssa-boundary-and-rate-rules`.
* **Cases:** 15 converted models whose deterministic and stochastic readings
  disagreed: `semantic/01537 01541 01555 01556 01557 01638 01639 01640
  01730 01731 01752 01795` and `stochastic/00006 00024 00026`.
* **Mechanism:** a species with `boundaryCondition="true"` is lowered to a
  **constant seed species** (`@C:$M_S1()`), and the generated network carries
  that marker per species (`ast::Species::isConstant()`).  Three of BNG3's four
  engines honoured it: the deterministic path zeroes the species' derivative
  (`OdeIntegrator::derivs`), and the partitioned simulators skip the species
  in their state update (`PsaSimulator::updateConcentrationsPsa`,
  `PlaSimulator`).  The **direct method** did not:
  `OdeIntegrator::integrateSSA` decremented a constant reactant and
  incremented a constant product like any other species, and the batched GPU
  flattening put a constant species into the state-change lists it hands to
  the kernels.  The same converted model therefore meant two different things
  depending on which engine simulated it.
* **The specification's requirement.**  SBML Level 3 Version 2 Core, section
  4.6.6 ("The constant and boundaryCondition attributes on Species"):

  > "In practice, a boundaryCondition value of 'true' means a differential
  > equation derived from the reaction definitions should not be generated for
  > the species."

  and, on what the attribute means when the species *does* occur in a
  reaction:

  > "When a species is a product or reactant of one or more reactions, its
  > amount is determined by those reactions.  In SBML, it is possible to
  > indicate that a given species' amount is not determined by the set of
  > reactions even when that species occurs as a product or reactant; i.e.,
  > the species is on the boundary of the reaction system, and its amount is
  > not determined by the reactions."

  So the restriction belongs to the **model**: the species' amount is constant
  whether or not a reaction names it.  Section 4.11 ("Reactions") makes the
  kinetic law's value the reaction's *extent* rate, and section 4.6.6 says no
  equation is derived for a boundary species - which is why the reaction that
  names it still runs at the kinetic law's own rate.
* **Which side owns the fix, and why.**  The **engine's state update**, not the
  propensity and not the Atomizer.
  * *Not the propensity.*  A constant species still contributes its amount to
    the rate law it appears in: the deterministic reading integrates
    `dB/dt = k*A` with `A` held at its initial value, so the discrete reading
    has to fire the reaction at that same constant rate.  Zeroing the
    propensity would have stopped the reaction that produces the *other*
    species - in `semantic/01537` `S2` has to grow at the reaction's rate.
  * *Not the Atomizer.*  The lowering is already exact for the deterministic
    reading: the converted model's own CVODE trace reproduces the published
    reference to 3.3e-9 on `semantic/01638`.  Dropping the boundary species
    from the reaction's pattern would make the reaction effect-less in
    `semantic/01638` (whose only reaction produces the boundary species), and
    the network generator drops an effect-less rule - so the case would stop
    being measured at all instead of being measured correctly.
  * *The engine.*  The constant-species marker is a property of the generated
    network, and the direct method was the only engine that did not read it.
* **Observed behaviour.**  `semantic/01638` (one reaction `J0: -> S1` whose
  product is a boundary species): the published reference keeps `S1` at 2 and
  the model's own CVODE trace reproduces it to 3.3e-9, while the batched
  direct SSA drives `S1` to 5.31 at `t = 10` (max |z| = 183 against the
  ensemble standard error).  `stochastic/00006` (a `Sink` boundary species):
  the published mean is 0 and the ensemble accumulates 432 molecules
  (max |z| = 1294).
* **The independent oracle agrees with the fix.**  libRoadRunner 2.10.0 on the
  **source** SBML: `semantic/01638` reports `S1 = 2` at `t = 0` and at
  `t = 10`; `semantic/01639` reports `S1 = 2` and `S2 = 3.333333333` at
  `t = 10` (the reaction's extent rate is the kinetic law's `1/3`, not
  `1/3 * S1`); `semantic/01752` reports `S1 = 2` and `S2 = 4` at `t = 10`
  (`3 + 10 * 0.1`); `stochastic/00006` reports `Sink = 0` and
  `X = 90.48374187` at `t = 10`.  BNG2 reaches the same *amount* semantics a
  different way: `legacy/perl/Perl2/RxnRule.pm` adds a `Fixed` reactant to the
  product list "to insure concentration does not change" and does not add a
  `Fixed` product at all "to avoid silent model changes".  BNG2 has no SBML
  extent-rate (`TotalRate`) concept, so it is not an oracle for the *rate
  law* of these models; libRoadRunner and the published references are.
* **The fix.**  `OdeIntegrator::integrateSSA` skips a constant species in the
  state update, and `FlattenedReactionNetwork::fromModelAndNetwork` omits a
  constant species from the flattened state-change lists the GPU kernels
  apply.  The CPU batch pool calls the direct method, so it inherits the fix;
  the GPU kernels consume the flattened lists, so they inherit it too.  The
  propensity is untouched.
* **Numbers.**  The campaign's stochastic-consistency sweep over the pinned
  suite (1923 cases; batch 10 000; `base_seed = 20261020 + int(case_id)`;
  single-worker CPU pool; the Metal backend for networks with at least 100
  reactions or 50 species and the CPU pool otherwise; `k_sigma = 5`), run on
  the branch's base (`origin/main`, `51fe8e00`):

  | outcome | base | this branch |
  | --- | --- | --- |
  | consistent | 195 | **210** |
  | inconsistent | 25 | **10** |
  | not comparable | 1575 | 1575 |
  | unsupported | 127 | 127 |
  | no valid propensity | 1 | 1 |

  **15 verdicts moved**, all of them `inconsistent -> consistent`, and they
  are exactly the 15 cases above.  **No other record of the 1923 moved**, and
  the GPU/CPU sampler-agreement check is unchanged (the same six cases, the
  same maximum |z| to every digit).
* **The per-case diff over the whole pinned suite.**  The official SBML Test
  Suite gate, the pinned suite at revision `cf38585f`, `PYTHONHASHSEED=0`,
  `PYTHONPATH=python:build/cpp`, `--isolate-cases --case-timeout 300 --jobs 3`,
  with the report's `runtime_provenance.bionetgen_package_path` naming this
  worktree on both sides:

  | stage | base | this branch |
  | --- | --- | --- |
  | conversion | 1735 passed / 125 unsupported / 63 failed / 0 timeout | 1735 / 125 / 63 / 0 (identical) |
  | official reference | 1697 passed / 163 unsupported / 63 failed / 0 timeout | **1700 passed / 160 unsupported / 63 failed / 0 timeout** |

  The conversion stage is **identical on all 1923 records** - the same status,
  the same unsupported reason, the same round-trip and independent-comparison
  verdicts.  The official-reference stage moved **3 records**, all of them
  `unsupported -> passed`: `stochastic/00006`, `stochastic/00024` and
  `stochastic/00026`, the three boundary-species cases of section 6.  Their
  reason field changes from the "the official reference does not track the
  boundary species Sink" verdict to a pass, because the model now keeps the
  boundary species at the value the reference reports.  **No case moved the
  other way.**
* **The 63 failures are not this branch's.**  They are an upstream regression
  in the *deterministic* path, present on the base commit and unchanged by
  this branch: `origin/main` applies a rule's symmetry factor to a
  `TotalRate` rule, so a converted reaction whose source carries a
  stoichiometry of 2 (`semantic/00069`'s `reaction2: S3 + S3 -> S1 + S2
  k2*S3 TotalRate`) runs at half its extent rate.  The published reference and
  libRoadRunner 2.10.0 both report the *unhalved* rate, and the same BNGL
  text produces the reference's trajectory on the pre-`#315` engine and a
  different one on `origin/main`.  See the note below.
* **The remaining ten, with their mechanism.**  Both mechanisms are the
  sweep's, and neither is an engine defect:
  * `conversion-differs-from-the-published-reference` - `semantic/01130
    01131 01132 01307 01308`.  The *deterministic* reading departs from the
    published reference here (`cvode_versus_official_reference` is
    non-zero), so the disagreement is a conversion difference on the Atomizer
    side, not a stochastic-versus-deterministic one.
  * `stoichiometry-lowered-to-a-deterministic-flux-loses-the-reaction-event-coupling`
    - `semantic/01432 01516 01517 01561 01562`.  The source model's
    reaction carries a **time-varying stoichiometry**, which the Atomizer
    lowers to a deterministic ODE flux and explicitly declines to claim for
    the stochastic reading ("Stochastic shared-event trajectories are not
    claimed").  The discrete reading of a shared reaction event cannot carry
    a stoichiometry that changes between events, so this is a scope boundary
    of the lowering rather than an engine defect.

## 14. The recorded rate-rule disagreement was the multi-worker pool's data race - NOT A RATE-RULE DEFECT

* **Classification:** not an engine defect on `main`; the recorded verdict was
  a misattribution, and the underlying defect is already fixed.
* **The recorded finding.**  The stochastic-consistency sweep reported
  `semantic/00990` as inconsistent with the mechanism
  `ssa-does-not-apply-rate-rules`: "a variable that carries a rate rule is
  driven by the rule in the ODE path, and the SSA path does not apply it".
* **What the SSA path actually does.**  The Atomizer lowers a rate rule into a
  **state species** whose amount *is* the rule variable's value, plus a
  `TotalRate` source rule that applies the rule's own rate:

      __rate_rule_p1: 0 -> M___rate_rule_state__p1() __rate_rule__p1() TotalRate

  The deterministic reading integrates that rule; the direct method fires the
  rule's rate as a propensity.  **Both readings apply the rule**, so the
  restriction is not a refusal and not a different number: the two readings
  agree in the mean, which is what the sweep measures.  The generated model is
  byte-identical at `d7b18d05` (the tree the recorded measurement was taken
  on) and at `a1496fb1`, so nothing in the lowering changed.
* **What the recorded disagreement actually was.**  A **data race in the
  multi-worker CPU batch pool**.  `OdeIntegrator::evaluateFunctionalRateCoefficients()`
  filled a *member* scratch (`groupValues_`) from the current state and
  `integrateSSA()` calls it on every propensity recomputation, so two workers
  sharing one integrator resolved a rate expression that reads an observable
  - `semantic/00990`'s reaction reads the rate-ruled variable - against
  *another* trajectory's state.  Pull request #362 (`b4171576`, "Give each
  batch-SSA worker its own observable scratch so a fixed seed is
  reproducible") moved the scratch to per-worker storage, and that commit is
  on `main`.
* **The evidence.**  On `origin/main` (`a1496fb1`) the sweep reports
  `semantic/00990` as **consistent**, with a maximum |z| of **2.1253** - the
  number #362 recorded after its fix - and the single-worker and multi-worker
  ensembles are now bit-identical.  The recorded measurement that produced
  the finding was taken with the **multi-worker** pool (`cpu_threads: 0`); the
  sweep's `--cpu-threads` default stays at 1 precisely so that the recorded
  measurement stays comparable.
* **What the sweep's mechanism label is.**  The attribution in
  `scripts/ci/check_stochastic_consistency.py` labels *any* disagreement in a
  model that has a rate rule as `ssa-does-not-apply-rate-rules`.  That is a
  guess about the mechanism, not a diagnosis of it, and it fired on a case
  whose disagreement had nothing to do with rate rules.  The label is a
  reporting field: it does not change a verdict, and the verdict on
  `semantic/00990` on `main` is `consistent`.
* **The regression test.**  `tests/python/test_ssa_rate_rule.py` pins the
  property in the campaign's form - the **stochastic** reading of a converted
  rate rule must agree with the **deterministic** reading, for the
  rate-ruled variable and for the species whose rate reads it - and
  `tests/validation/test_stochastic_consistency.py` keeps the sweep's own
  comparison under test.

## 15. An official reference that names a reaction is not comparable - FIXED

* **Classification:** harness-side gap over an Atomizer-side feature gap.
  **CLOSED** on `campaign/reaction-rate-outputs`.
* **Cases:** the twenty-two official cases whose reference names a reaction id
  as a result variable: `semantic/01344 01345 01346 01347 01348 01349 01350
  01351 01352 01360 01369 01378 01380 01381 01382 01383 01384 01385 01386
  01387 01388 01389`.  Every one of them was recorded as
  `reference:no-result-mapping`, the only *harness* construct in the manifest
  that was not a measurement limitation.
* **Mechanism:** the official reference asks for a reaction's rate by naming
  the reaction id in its `variables:` list (`variables: S1, J1, C, A__x`).
  The harness maps every reference variable onto an exact BNGL output symbol
  (`scripts/ci/validate_sbml_test_suite.py`, `_reference_output_target`),
  and a reaction id had no such symbol: the Atomizer emitted nothing that
  carried a reaction's rate, so the case was recorded as *no result mapping*
  instead of compared.  The comparison itself was never wrong; it could not
  be made.
* **What the reference asks for, and what the specification says it is.**
  The reference's column is the reaction's **extent rate**.  SBML Level 3
  Version 2 Core, Sec. 4.11.8: "The value of the `id` attribute of a
  Reaction can be used as the content of a `ci` element in MathML formulas
  elsewhere in the model.  Such a `ci` element or symbol represents the rate
  of the given reaction as given by the reaction's KineticLaw object."  Sec.
  4.2.5: "The extent of a reaction is a measure of how many times the
  reaction has occurred, while the time derivative of the extent gives the
  instantaneous rate at which the reaction is occurring.  Thus, what is
  colloquially referred to as the 'rate of the reaction' is in fact equal to
  the rate of change of reaction extent."  Sec. 4.11.7 gives the resulting
  equation, `dnSi/dt = sum_j stoichSi,Rj * vRj`, with `vRj` the kinetic
  law's value.  The quantity is therefore the kinetic law's value, and it is
  a function of the state - a species' value is its amount when it has
  `hasOnlySubstanceUnits="true"` and its concentration otherwise (Sec. 4.6).
* **What BNGL and the engine can express.**  The BNGL grammar's
  `observable_type` accepts `Molecules`, `Species`, `Counter` and a custom
  name (`cpp/parser/BNGParser.g4`), but the engine's observable machinery
  evaluates an observable by *counting pattern matches*: the type only
  selects between the `Molecules` and the `Species` reading
  (`cpp/engine/OdeIntegrator.cpp`), and the projection that the exporters use
  refuses every other type outright - `unsupported observable type 'Counter'
  for observable 'Cnt'` (`cpp/engine/ObservableProjection.cpp`).  A reaction's
  rate is therefore **not** expressible as an observable, custom types
  included.  A BNGL **function**, on the other hand, already is what the
  engine treats as an algebraic model output: zero-argument functions are
  evaluated along the trajectory and reported as results
  (`cpp/engine/OdeIntegrator.cpp`, `updateFunctions` and `isResultFunction`),
  and the C++ SBML writer emits them as native assignment rules.  No engine
  feature was needed; the construct the model needed already existed.
* **What changed.**  The Atomizer now states each reaction's rate as a
  zero-argument function in the generated model (`<reaction id>_rate`), built
  from the source kinetic law with the source species' values
  (`python/bionetgen/atomizer/modern/writer.py`,
  `_reaction_rate_expression`), and it reports the mapping from the source
  reaction id to that function (`AtomizerResult.reaction_rate_functions`).
  The harness maps a reference variable that names a reaction onto that
  function.  The function is a function of the state and is evaluated along
  the trajectory; it is never frozen at `t = 0`.  A reaction whose rate
  cannot be stated in the generated model's own symbols states no rate at
  all, and its case stays *no result mapping* - the refusal is unchanged
  rather than approximated.
* **The numbers.**  Each case reproduces the official reference on the
  official grid, at the suite's own per-case tolerance from its
  `-settings.txt` (`absolute: 0.0001`, `relative: 0.0001`): the rate
  columns are `5` for `01344`-`01352`, `01360`, `01369`, `01378` and `1` for
  `01380`-`01389`, and `01351`/`01387` carry a second reaction column
  (`A__J2`) that is `5` in both.  Every rate column matches the official
  reference *exactly* - a maximum absolute difference of `0` on all
  twenty-two cases - and the worst scaled error over all of the cases'
  variables is `1.4e-11`.  `tests/python/test_sbml_reaction_rate_outputs.py`
  reproduces each case from the pinned suite revision
  `cf38585fac5de8e0e90112febb62851ee2181816` and asserts the official
  reference's own numbers.
* **The per-case diff over the whole pinned suite.**  One full run per tree
  against the pinned suite `cf38585fac5de8e0e90112febb62851ee2181816`, with
  `PYTHONHASHSEED=0` and `PYTHONPATH=python:build/cpp`, both trees clean,
  both runs against the *same* native extension - built once in this
  branch's own worktree from the branch's C++ sources, which are
  byte-identical to the base's - and each report naming its own worktree in
  `runtime_provenance.bionetgen_package_path`:

  | stage | `origin/main` (`ba892814`) | this branch |
  | --- | --- | --- |
  | conversion | 1797 passed / 126 unsupported / 0 failed / 0 timeout | 1797 passed / 126 unsupported / 0 failed / 0 timeout |
  | round-trip structure | 1797 passed / 126 not tested | 1797 passed / 126 not tested |
  | independent libRoadRunner comparison | 1797 passed / 126 not tested | 1797 passed / 126 not tested |
  | official reference | 1758 passed / 165 unsupported / 0 failed / 0 timeout | **1780 passed / 143 unsupported / 0 failed / 0 timeout** |

  * **22 verdicts moved**, all of them this cluster's cases, all from
    `unsupported` to `passed`.
  * **0 regressions**, and **no other record of the 1923 moved at all** - the
    conversion, round-trip and independent-comparison stages are unchanged,
    which is the check that the new function does not disturb the generated
    model or its libRoadRunner parity.

---

## 16. The stochastic verdict depended on the runner's speed - FIXED

* **Classification:** harness defect (reproducibility of the measurement).
* **Cases:** `stochastic/00023` and `stochastic/00005`.  Both are the two
  heaviest cases of the pinned suite, and they are the two cases whose
  official-reference comparison the harness could not run at the documented
  ensemble budget.  Every other stochastic case of the suite runs the
  documented 40,000-trajectory budget and is unaffected.
* **Mechanism:** `_stochastic_ensemble_plan` probed the batched sampler,
  measured the runner's throughput, and *reduced* the trajectory count to the
  largest count the runner could afford inside a 30-second wall-clock
  budget.  The verdict was then computed from the reduced ensemble.  The
  count therefore depended on the machine, and so did the verdict.
* **Expected behaviour:** a conformance verdict is a statement about the
  model.  It must not depend on how fast the machine that produced it ran.
  The SBML discrete stochastic model test suite (DSMTS) user guide, section
  3, asks for `n` independent simulation runs, says that "the value of `n`
  should not be less than 1,000", and that "for the statistical tests to have
  reasonable power to detect problems, `n` should be set to at least 10,000";
  section 3.4 repeats that "n = 10,000 is needed to have any chance of
  picking up minor issues".  Section 3.1 defines the standardised mean
  statistic `Z = sqrt(n) * (X_bar - mu) / sigma`, section 3.2 the
  standardised variance statistic `Y = sqrt(n/2) * (S^2 / sigma^2 - 1)`, and
  the guide motivates with an approximate-normal null; its acceptance ranges
  are stated on those standardised statistics - "most
  values will lie in the range (-3, 3)" for `Z` and, because the variance
  test rests on an approximation, "only values outside the range (-5, 5)" for
  `Y` - and the suite's own `-settings.txt` files carry the same two ranges
  (`meanRange: (-3, 3)`, `sdRange: (-5, 5)`).
* **Observed behaviour:** the harness already computes the guide's statistics
  with the `n` it actually ran, so its *per-test* criterion follows the guide's
  formula: the acceptance band does not widen for a smaller ensemble.  This
  preserves the guide's approximate-normal null; it does not establish that
  approximation or the same per-test chance rate for every source distribution
  and every `n`.  What is not n-correct
  is the *verdict*, because a verdict is a property of the realised ensemble
  and not of its distribution: the batched samplers derive one engine seed
  per trajectory from the base seed, so the ensemble of `n` trajectories is a
  prefix of the ensemble of 40,000 trajectories, and a different `n` is a
  different draw from the same null.  Measured on `stochastic/00023` with
  the campaign's base seed (1,000,000), the largest standardised mean
  statistic of the ensemble was

  | `n` | 1,000 | 2,000 | 4,000 | 8,000 | 16,000 | 32,000 |
  | --- | --- | --- | --- | --- | --- | --- |
  | largest `\|Z\|` | 4.51 | 4.15 | 2.83 | 2.78 | 1.75 | 1.63 |
  | violated tests | 6 | 5 | 0 | 0 | 0 | 0 |

  The case-level criterion fails a case at three violated acceptance tests,
  so the case failed below `n = 3,000` and passed above it.  The reduction
  the harness applied on a loaded runner therefore decided the verdict: four
  repeats of the same case, tree and seed reported `failed` with 2,872
  trajectories and `passed` with 5,356, 4,016 and 3,964, and the campaign's
  own full-suite measurements of the case reported `passed` with 5,594,
  8,711, 8,948, 10,604, 11,688 and 12,477 trajectories - seven different
  ensemble sizes, every one of them decided by how fast the runner was.  The
  committed expectation manifest recorded `passed` for a verdict the tree
  does not reproduce.
* **Decision:** **the documented budget, or a verdict at all - never a
  verdict from a truncated ensemble.**  The alternative - "make the
  acceptance statistic correct for the ensemble size actually used" - cannot
  work here, for two reasons that the guide settles.  First, the statistic
  is already the guide's statistic and is already n-correct under the guide's
  approximate-normal null: `Z` and `Y` are approximately standard normal at
  every `n`, the acceptance ranges are stated on them, and the difference
  between the normal and Student's `t` reference at
  `n = 1,000` is 0.03 in the 3-sigma quantile, so there is no band to widen.
  Second, and decisively, no acceptance statistic can make the *verdict*
  machine-independent, because the verdict is a property of the realised
  ensemble: a different `n` is a different draw from the same null, and the
  4.51-sigma excursion above is a legitimate rejection of the null at
  `n = 1,000` and a legitimate acceptance of it at `n = 32,000`.  A
  criterion that accepted both would have to accept every excursion, which
  is no test at all.  So the ensemble size has to be fixed, and a case that
  cannot be run at the documented budget has to be reported as *not
  comparable* - the campaign's own vocabulary for "the comparison could not
  be made", which is neither a pass nor a failure.
* **The fix:** the harness uses a fixed-seed 64-trajectory CPU probe to
  estimate event work and elapsed CPU time, then projects that work to the
  documented ensemble.  The 4e8 event-work threshold is a planning threshold,
  not an enforced cap on the full ensemble.  It makes the planned trajectory
  count independent of probe elapsed time for the same model, seed, and
  implementation; it does not guarantee the full ensemble's actual event
  count or runtime.  On the reference runner, the CPU sampler measured about
  1.4e7 to 2.6e7 reaction events per second, so the threshold projects to
  about 15 to 30 CPU seconds against the gate's 60-second per-case timeout.
  This is a projection, not a runtime bound, and the actual full ensemble may
  exceed it.  The documented 40,000-trajectory ensembles for
  `stochastic/00005` and `stochastic/00023` project to about 3.3e9 and 3.6e9
  events, while every other case projects to at most 2.3e8 events.  Cases
  projected above the threshold are not compared when the projected affordable
  count falls below the guide's power floor of 10,000 repetitions; they are
  reported as not comparable with the shortfall named.
* **The evidence that planning no longer follows probe speed:** the
  deterministic probe's projected event work, rather than its elapsed time,
  determines the planned count.  For the same model, seed, and implementation,
  `tests/python/test_sbml_official_reference.py` asserts that a 0.5-second
  probe and a 50-second probe plan the same trajectory count while reporting
  different CPU projections.  This establishes deterministic planning for
  those probe inputs; it does not establish a hard cap on the full ensemble's
  actual work or runtime.  Measured on the tree, with
  background CPU load added to the runner:

  | Background load | `stochastic/00001` | | | `stochastic/00023` | | |
  | --- | --- | --- | --- | --- | --- | --- |
  | | trajectories | projected work | verdict | projected work | affordable | verdict |
  | none | 40,000 | 32,131,250 | passed | 3,605,337,500 | 4,437 | not comparable |
  | 4 processes | 40,000 | 32,131,250 | passed | 3,605,337,500 | 4,437 | not comparable |
  | 8 processes | 40,000 | 32,131,250 | passed | 3,605,337,500 | 4,437 | not comparable |

  Only the reported CPU projection moves (2.1 s, 2.7 s and 3.0 s for the
  three loads); the planned trajectory count and projected work do not.  This
  probe-level comparison does not assert equal full-ensemble event totals or
  runtime across machines or backends.
* **What changed in the records:** `stochastic/00005` and `stochastic/00023`
  move from `passed` to `unsupported` at the official-reference stage, with
  the gap construct `harness:stochastic-ensemble-budget` and the cause
  `ensemble_budget`.  The conversion, round-trip and independent-comparison
  stages of both cases are unchanged: the model converts, the generated
  network round-trips, and libRoadRunner agrees with it.  The expectation
  manifest, the committed current inventory and the campaign document's
  generated tables are refreshed together from the one measurement this
  change was taken from.
* **Two related observations that this change does not close.**  The
  case-level criterion models the 100 acceptance tests as independent
  Bernoulli trials, but the statistics at successive output times are
  strongly correlated - the ensemble-mean path is one mean-reverting
  process - so a single chance excursion produces a *cluster* of violations
  and the binomial model understates the chance probability of the observed
  count.  The measured false-failure rate of the criterion is therefore
  nearer 1% than the 1e-3 it claims; the criterion is unchanged here,
  because correcting it is a separate change to the campaign's conformance
  semantics, not a repair of this defect.  And the CPU and Metal samplers
  derive their per-trajectory seeds differently, so a stochastic verdict also
  depends on whether the runner has a GPU - a hardware dependence, recorded
  here and not repaired here.

## Measurements that are *not* findings

* **The base commit fails 63 of the 1923 pinned cases, and this branch does
  not change that.**  `origin/main` (`51fe8e00`) reports
  `1735 passed / 125 unsupported / 63 failed / 0 timeout` where the committed
  expectation manifest (`provenance/sbml-campaign/current-2026-10-22.json`,
  measured at `5d8e78b0`) reports no failure.  The regression is in the
  *deterministic* path, and it is the symmetry factor of a `TotalRate` rule:
  pull request #315 removed the `!crxn.isTotalRate` guard in
  `OdeIntegrator::compile()`'s functional-rate branch, so a rule with
  identical reactants now carries its `1/2` factor into the rate law.  A
  `TotalRate` rule's value *is* the reaction's extent rate (SBML Level 3
  Version 2 Core, section 4.11), and the Atomizer encodes a species
  reference's stoichiometry in the rule's pattern, so the factor must not be
  applied to it.  Every one of the 63 failing cases has a converted rule of
  the shape `A + A -> ... <rate> TotalRate`.
  The A/B evidence, on the *same* BNGL text for `semantic/00069`
  (`reaction1: S1 + S2 -> S3 17` and
  `reaction2: S3 + S3 -> S1 + S2 k2*S3 TotalRate`):

  | engine | `S1(t=0.1)` | `S3(t=0.1)` |
  | --- | --- | --- |
  | the published reference (`00069-results.csv`) | 0.06026999450447567 | 0.1325638225527571 |
  | the engine before `#315` | 0.060269994 | 0.132563823 |
  | `origin/main` (`51fe8e00`) | 0.057837268 | 0.138490236 |

  and the system `origin/main` integrates is the one with `r2 = k2*S3/2`
  instead of `r2 = k2*S3`.  This branch does not touch that code path, and
  the per-case diff above shows the 63 records are identical on both sides.
  It is recorded here because the campaign's gate is red on the base commit
  and the owner has to decide whether the symmetry factor belongs to a
  `TotalRate` rule at all.

* `semantic/01592` timed out in one hosted run.  Re-run uncontended it
  completes in 11 s of wall time; the timeout was contention plus the
  10,000-phase action block, and the harness now reports the case as not
  comparable - for the random event execution the source model defines -
  before any comparison runs.
* The `Lean 4.33.1 kernel and NFnext contracts` job failed with
  `SSL connect error ... releases.lean-lang.org/...` - a download error
  inside the runner image, in a workflow this change does not touch.
* The first full-suite measurement of this work resolved the *stale
  installed* `bionetgen` from `site-packages` instead of the worktree
  source, which moved 76 unrelated cases.  A measurement that runs a
  different package than the one under test is a measurement error; the
  harness records `runtime_provenance.bionetgen_package_path` so that this
  is checkable.

## 2026-10-22 — stochastic repeated-reactant counts for special laws

Canonical BNG2 2.9.3 (RuleWorld/bionetgen source revision
`9601746f8884ed19ab2acea49fe87fc4660ace46`, recorded in
`provenance/upstreams.lock.yml`) defines two count evaluations for a repeated
population reactant.  In `bng2/Network3/src/network.cpp`, `rxn_rate`'s `ELEMENTARY`
branch applies `X - n` to each repeated discrete reactant (lines 2486-2512),
while its continuous branch applies `X` (lines 2508-2512).  `SATURATION`
uses `X - n` in each discrete numerator factor (lines 2542-2568), preserving
the saturation denominator `K + X`; `HILL` applies `X - n` to repeated
co-reactants after its Hill substrate (lines 2593-2606).  `FUNCTIONAL` uses the
same discrete distinct-copy count (lines 2617-2637).  Canonical Perl BNG2
rejects identical MM substrate/enzyme reactants in `bng2/Perl2/RateLaw.pm`
(lines 1243-1249).  Its ODE calls `rxn_rate(..., 0)` while its stochastic path
calls `rxn_rate(..., 1)` (`network.cpp`, lines 3192-3193 and 5283-5284).

Canonical NFsim (RuleWorld/NFsim source revision
`9b00d42f734dcc3e695205600f12cae5b44d1daa`, recorded in
`provenance/upstreams.lock.yml`) independently applies a per-reactant
repeated-population correction: `reactionClass.cpp` builds `identicalPopCountCorrection` (lines 289-306), and
`BasicRxnClass::getCorrectedReactantCount` clamps `population - correction` at
zero (`reaction.cpp`, lines 709-736).  Thus the native SSA's continuous
population factor in a functional special-law co-reactant was the outlier.

BNG3 preserves the canonical identical-MM refusal at the shared native
`OdeIntegrator` compilation boundary: `MM(kcat,Km)` with the same generated
species in both substrate and enzyme positions returns an explicit
unsupported error instead of applying the self-consistent two-reactant
formula. This guard is tested through both ODE and native SSA entry points;
it does not establish support or parity for this configuration in NFsim.

The native engine now carries the repeat offset on compiled special-law
reactant references and resolves it as `population - offset` in the stochastic
functional-rate evaluation.  Its deterministic resolver keeps the unshifted
population.  Native SSA, PLA, and batch flattening share the same helper for
reactant offsets.  Elementary mass-action already used this count in native
SSA and the batched path.  Batch SSA continues to fail closed on functional
rate laws and `TotalRate`; this change does not claim to add those law types to
the accelerator.  `TotalRate` still returns its complete flux without
multiplying by reactant counts, and BNG2's writer assigns it statistical
factor one (`bng2/Perl2/Rxn.pm`, line 70).

The independent analytic master equation and source agree on the saturation
law's discrete propensity:
`0.5 * kcat * n * (n - 1) / (Km + n)`.  With seeds 1-4000, one trajectory
per seed, `t_end=1`, and `A(0)=20`, the uncorrected native SSA measured
`2.282750 +/- 0.020151` mean events while NFsim measured `2.110500 +/-
0.019835`; the campaign's analytic discrete mean is `2.145819`.  The old
native mean differs from this law by 6.80 standard errors, while the NFsim
mean differs by 1.78.  The canonical BNG2 standalone SSA was also attempted
for this saturating network in the campaign and exited with SIGSEGV, so it
provides no trustworthy trajectory ensemble for this law; the decision uses
BNG2's executable rate-law source plus the independently integrated master
equation.  The BNG2 ODE remains the continuous-law oracle for deterministic
behavior.

On the patched native build, the same seed policy measured native SSA at
`2.176000 +/- 0.019786` events (z=+1.53 against the analytic discrete mean)
and NFsim at `2.110500 +/- 0.019835` (z=-1.78).  The old native mean was
`2.282750 +/- 0.020151`, a change of `-0.106750` events; the old SSA/NFsim
residual was `+0.172250 +/- 0.028275` (z=+6.09), while the patched residual
is `+0.065500 +/- 0.028031` (z=+2.34).  These are ensemble comparisons under
the recorded seeds, not pathwise-equality claims.

Regression coverage in `tests/python/test_special_rate_statistical_factor.py`
checks the native SSA and NFsim ensembles against the discrete analytic law
and compares their means under the same 4,000-seed policy.  The existing
`tests/python/test_ssa_closed_form_parity.py::test_identical_reactant_propensity_is_the_combinatorial_one`
continues to exercise the batch path's mass-action `k * C(n, 2)` law. Focused
tests also exercise the repeated co-reactant count in Hill SSA against its
analytic one-firing probability, the third-order PLA propensity against an
independently integrated pure-death master equation, and the native refusal
for identical MM substrate/enzyme reactants.
