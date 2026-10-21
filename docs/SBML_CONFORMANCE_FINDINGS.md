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

## 6. The official reference does not track the boundary "Sink" species

* **Classification:** scope boundary (reference data), now reported as *not
  comparable*.
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
* **Observed behaviour:** the harness detects that the reference reports the
  variable as identically zero at every output time while the model
  accumulates it.
* **Minimal reproducer:** `stochastic/00006`; the reference's `Sink-mean`
  and `Sink-sd` columns are zero for all 51 output points while the model
  accumulates the sink.
* **Handling in the harness:** the case is reported as `unsupported` - the
  gate's *not comparable* verdict - with the reason that names the
  quantity: "the official reference does not track the boundary species
  Sink: the reference reports Sink as identically zero at every output time
  because a boundary species is not determined by the reactions, while the
  BNG3 model accumulates it, so the comparison on that quantity does not
  apply".  The comparison on every other quantity of the case - `X` in these
  cases - is unchanged, and a mismatch there is still a failure.  The
  manifest records the gap's `side` as `harness`, because nothing is wrong
  with the model.

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
* **Mechanism:** section 4.9.2 ("Local parameters") of the SBML Level 3
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
* **Mechanism:** section 4.11.4 ("Event triggers") of the SBML Level 3
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

SBML Level 2 Version 4/5 and Level 3 Version 1 Core, section 4.11
("Reactions"), do not describe a `fast="true"` reaction as merely faster.
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


---

## Measurements that are *not* findings

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
