# SBML Atomizer coverage campaign

Target: make the BNG3 modern Atomizer the most correct, comprehensive and
robust SBML-to-BNGL converter, with **demonstrable** mathematical equivalence
rather than merely successful conversion.

This document records the campaign's measurement baseline, the failure
clusters derived from it, the result the campaign reached, and the boundaries
that are still open. The scope record of what the Atomizer refuses, and why,
is [`ATOMIZER_LIMITATIONS.md`](ATOMIZER_LIMITATIONS.md); it is generated from
the same expectation manifest this document's tables are generated from.

Every result table in this document is **generated** from the harness report it
names, by `scripts/ci/sbml_campaign_tables.py`; the exact command is in
[Regenerating the tables](#regenerating-the-tables). The generated regions are
marked, so a table can never state a number the measured run does not
support.

The machine-readable forms of the same data are:

* [`provenance/sbml-campaign/expectations.json`](../provenance/sbml-campaign/expectations.json)
  — the **expectation manifest**: the expected verdict of every official suite
  case at every stage of the gate, used to fail a coverage regression
  automatically (see [Expectation manifest](#expectation-manifest)).
* [`provenance/sbml-campaign/baseline-2026-10-19.json`](../provenance/sbml-campaign/baseline-2026-10-19.json)
  and [`provenance/sbml-campaign/integrated-2026-10-20.json`](../provenance/sbml-campaign/integrated-2026-10-20.json)
  — the measured inventories, regenerated with
  `scripts/ci/sbml_campaign_inventory.py`.
* [`provenance/sbml-campaign/audit-2026-10-21.json`](../provenance/sbml-campaign/audit-2026-10-21.json)
  — the independent audit of the campaign's claims, with the transition and the
  mechanism of every verdict change it measured (see
  [The campaign's invariant, audited](#the-campaigns-invariant-audited)).
* [`provenance/sbml-campaign/atomizer-limitations.json`](../provenance/sbml-campaign/atomizer-limitations.json)
  — the narrative behind `ATOMIZER_LIMITATIONS.md`: what each construct is,
  what the specification requires, what BNG3 does instead, and whether the
  boundary is reducible.

## How to reproduce the baseline

The commands in this document write their reports and their artifacts to a
working directory of your choosing; `$REPORTS` stands for it below. The
report the committed tables were generated from is named — together with its
SHA-256 — in the generated region itself, so the committed measurement is
identifiable even when the report file is not at hand.

```bash
# Official SBML Test Suite, pinned revision cf38585fac5de8e0e90112febb62851ee2181816
PYTHONPATH=python:build/cpp python scripts/ci/validate_sbml_test_suite.py \
  --suite-dir /path/to/sbml-test-suite \
  --categories semantic stochastic --isolate-cases --case-timeout 120 --jobs 6 \
  --artifacts-dir "$REPORTS/artifacts-baseline" \
  --json "$REPORTS/baseline-ssts.json"

# Curated BioModels, flat and atomized modes
python scripts/ci/validate_published_biomodels.py \
  --cache-dir /path/to/biomodels-cache \
  --json "$REPORTS/biomodels-baseline.json" \
  --mode flat --isolate-models --model-timeout 120 --jobs 4
```

## Baseline (base commit `219c76da`, measured 2026-10-19)

The official SBML Test Suite has 1923 pinned cases (1823 semantic + 100
stochastic). The curated BioModels corpus has 1096 records.

<!-- BEGIN GENERATED: sbml-campaign-baseline -->



<!-- END GENERATED: sbml-campaign-baseline -->

## Failure clustering

The official-reference "unsupported" verdicts split into **harness
limitations** and **Atomizer limitations**. This distinction is the single
most important fact in the campaign: most of the remaining official coverage
gap is not an Atomizer defect. The generated baseline table above gives the
exact counts, grouped by the component that owns each blocking reason.

The gap taxonomy counts every gap at every stage of the gate, and the side
each gap falls on is the most important remaining structural fact about the
campaign's coverage:

| Side | n | What it is |
| --- | --- | --- |
| harness | 16 | a **measurement** limitation: the gate cannot evaluate a source-faithful comparison (12 random-event order cases, 2 ensemble-budget cases, and 2 scheduled-action phase-boundary cases) |
| Atomizer | 216 | a **representational** limitation: the model uses a construct BNGL cannot say (91 at the official-reference stage and 125 at the conversion stage) |
| not applicable | 34 | the case defines no official time-course reference |

A harness-side gap is a statement about the *measurement*, not about the
model: the official suite exercises a construct BNG3 can represent and the
gate is what cannot yet evaluate it. An Atomizer-side gap is a statement
about the *representation*: the model uses something BNGL cannot say. The
first kind is the campaign's remaining instrumentation work, the second is
its remaining coverage work, and they need different fixes.

_Source: the expectation manifest's gap taxonomy
(`provenance/sbml-campaign/expectations.json`), as of the measurement the
generated current tables below record: 266 unsupported outcomes in all — 125
at conversion and 141 at the official-reference stage. Of these, 216 are
Atomizer-side, 16 are harness-side, and 34 are not applicable because the
case has no official time-course reference._

The Atomizer-side gaps are the constructs the scope record describes one by
one, each with the cases it covers and whether the boundary is reducible:
untranslated events, the `fbc` package, the `delay`/`rateOf` operators, a
fast reaction whose pseudo steady state cannot be written as a BNGL rule, a
state trigger the runtime cannot schedule, an infinite or not-a-number
constant, a compartment with more than three spatial dimensions, and a small
bucket of refusals the taxonomy does not yet name. Earlier action-runner and
reaction-extent measurement limits were closed by PR #337 and PR #378. The
current 16 harness gaps include 12 random-event order comparisons, 2
ensemble-budget cases that cannot meet the documented run count within the
fixed work budget, and 2 scheduled-action phase-boundary comparisons. The
budget cases are not Atomizer refusals.

The baseline official-reference failures are also grouped by each case's own
official `componentTags` metadata, read from the pinned suite's own
`NNNNN-model.m` notes. The generated baseline table lists every failing case,
so a cluster table can no longer omit the cases it forgot.

## Known root causes (verified)

1. **Initial-value resolution order** (PR #316). A `constant="false"`
   parameter with no `value` attribute was seeded with the default `0`,
   shadowing the value its `assignmentRule` supplies, and `initialAssignment`s
   were evaluated before `assignmentRule`s. SBML L3 Core §3.4.8 (the order in
   which the values at `t ≤ 0` are established) and §4.9.3 (an assignment
   rule's value overrides the value its target's own definition carries)
   fix the order. 15 official cases move `failed → passed`.

2. **SBML `avogadro` csymbol conflated with BNGL's `__Avogadro__`, and
   `csymbol` identified by its text** (PR #318). SBML's `avogadro` csymbol
   has the fixed value `6.02214179e+23` (SBML L3 Core §3.4.6, which requires
   readers of this version to use exactly that number); BNGL's
   `__Avogadro__` is BNG's molecule-count factor and is `1`. The
   operator-position `csymbol` path also keyed on the element *text* rather
   than on `definitionURL`, so
   `<csymbol definitionURL="…/avogadro">time</csymbol>` was read as the
   symbol `time`. A static `initialAssignment` for a parameter was also
   re-evaluated at every time point instead of being folded into the
   parameter's value. 20 official cases move `failed → passed`.

3. **Amount-based (`hasOnlySubstanceUnits="true"`) rate laws in a
   non-unity compartment** (PR #319). SBML L3 Core §4.11: a kinetic law's
   value is the reaction's *extent* rate, and a species' amount changes by
   `stoichiometry × extent rate`. BNGL rate laws are always *concentration*
   rates, so an amount-based law needs a factor of `V^(m-1)` for a law with
   `m` reactant factors. 19 official cases move `failed → passed`.

4. **Rate-ruled species-reference stoichiometry** (PR #323). SBML L3 Core
   §4.11.3 gives a `speciesReference` id the meaning of a model-level symbol
   whose value is that reference's `stoichiometry`. When a `rateRule` drives
   that symbol, its time-zero value is the reference's declared
   `stoichiometry`. The Atomizer lowered such a reaction into
   species-specific `TotalRate` rules whose rate carries the stoichiometry,
   but it seeded the synthetic rate-rule state from `0` instead, so every
   such model integrated a different trajectory.

5. **SBML `delay` / `rateOf` semantics** (PR #324). MathML has no `delay` or
   `rateOf` operator: SBML L3 Core §3.4.6 defines both as `csymbol`
   operators, and §3.4.8 gives the rules for the values before `t = 0`. The
   C++ SBML writer emitted `<ci>delay</ci>`, which is invalid SBML. The
   writer now emits the `csymbol` form that libSBML 5.21.1 itself emits and
   the native reader reads it back. That C++ work is real and is covered by
   new C++ unit tests, but it is **not reachable through this campaign's
   harness**: the refusal a model with an unlowerable `delay` receives is
   emitted by the *Python Atomizer* (`writer.py`), whose wording names the
   C++ writer, and the harness classifies such a model as `unsupported` at
   the conversion stage, which returns before `cpp.io.write_sbml` is ever
   called. The baseline's `delay`-related bucket of unsupported verdicts is
   therefore untouched: those cases stay unsupported for the same reason.
   The generated "unsupported verdicts, by owner" table above still lists
   that bucket under the C++ writer, because that is how the Atomizer's
   refusal names it; the refusal itself is the Atomizer's.

   On the measured surface the change moved **7 official-reference cases
   from `failed` to `passed`** — 00938 00940 00942 01460 01498 01534 01542 —
   with the maximum absolute difference against the published
   `-results.csv` dropping from 0.4–20 to ≤ 4.6e-7; **no conversion verdict
   changed in either direction**; and 10 further cases changed only in their
   diagnostic text and stayed `unsupported` (00985 01142 01410 01411 01412
   01480 01481 01535 01539 01593), so no diagnostic was weakened. The 15
   cases the change originally claimed were official-reference *failures*
   in the baseline, not `unsupported` cases, and 8 of them are untouched:
   00941 and 00943, where a `delay` of a parameter whose `initialAssignment`
   is time-dependent is silently dropped (no diagnostic, wrong numbers);
   01400, 01401, 01403, 01406 and 01409, which all fail at exactly one
   sample, `t = 0`, with a maximum absolute difference of 0.5–1.5, because
   the rule that "the `rateOf` value for any valid target in SBML for time
   `t < 0` will always be zero" is not implemented; and 01419, whose BNGL is
   byte-identical between the base and the branch and which was fixed by
   the sibling PR #323.

6. **MathML built-ins folded in the static evaluator, and a signed
   stoichiometry carried** (PR #335). The static evaluator now folds the
   built-in MathML functions and their arguments instead of emitting them
   verbatim, and a rate-ruled species reference whose stoichiometry is
   signed carries that sign. The 95 `dropped` diagnostics it removed were
   each a *false* refusal, so the cases they blocked are now `passed`
   rather than `unsupported`: eight official cases move forward, and the
   official-reference residual falls from 18 to 17.

7. **The SBML `fast` attribute is part of the model's definition, not a solver
   hint** (PRs #354 and #370). SBML Level 3 Version 1 Sec. 4.11 and SBML Level 2
   Sec. 4.13 (Sec. 4.9 in Level 2 Version 1) do not
   describe a `fast="true"` reaction as merely faster: "Fast reactions are
   considered to be instantaneous relative to the slow reactions", and
   "software tools should use a pseudo steady-state approximation for the set
   of fast reactions **when constructing the system of equations for the
   model**". The same section says the attribute "has a significant effect on
   the mathematical interpretation of a model and cannot be safely ignored if
   a software tool does not implement support for the corresponding
   concept". Level 3 Version 2 removes the attribute outright ("every
   Reaction in a L3V2 model is equivalent to an SBML Level 3 Version 1
   Reaction with a `fast` value of false"), and the appendix *Mathematical
   consequences of the `fast` attribute on Reaction* gives the reduction
   itself: the fast subsystem contributes the algebraic constraint
   `A1·v_f(x) = 0` while the slow dynamics follow from `B·dx/dt = B·A2·v_s`
   with `B` the left null space of `A1`.

   The official references agree, and this is the finding that decided the
   cluster: every published `-results.csv` for these cases is the
   pseudo-steady-state trajectory, not the trajectory of the raw rate
   equations. Case 00870 is already at its equilibrium (`Kf1·A4 = Kr1·A2`) at
   `t = 0`, 00986 is exactly `B(t) = e^{-t}`, and the cases' own notes say
   "the 'fast' reaction should go to completion instantly". Measured
   independently with libRoadRunner 2.10.0's exact CVODE on the same models
   with the attribute cleared, the raw-ODE solution deviates from every
   reference by 100x-53000x the suite's own tolerance, and libRoadRunner
   itself refuses to load a `fast="true"` model ("Unable to support 'fast'
   reactions"). **Lowering a fast reaction as an ordinary reaction would
   therefore have turned 35 refused cases into 35 failed ones.**

   The Atomizer now lowers the two shapes whose pseudo steady state is
   closed-form.  A rate that vanishes with one of the two species the
   reaction converts - `c*X`, `c*Y` or `c*X*Y` with a time-independent
   constant `c` - holds that species at zero and lets the other absorb its
   amount, scaled by the stoichiometry ratio and by the conversion factors;
   the sign of `c` says which of the two the reaction runs towards.  A rate
   that *balances* the two species - `k_f*X - k_r*Y` - is held on the
   algebraic balance `k_f*X = k_r*Y`, and the slow reactions move along that
   balance: the eliminated species carries the reduced rate as a rate rule
   and the fast subsystem's conserved combination changes at the slow
   reactions' own rate.  That reduction is a closed-form pre-solve of the
   initial condition plus an exact rate substitution, not a numerical
   algebraic solve, so it needs no engine feature.  Independent fast
   reactions each reduce on their own as long as they do not share a
   species, and a rate constant an algebraic rule fixes is a constant.  29
   official cases move `unsupported → passed` (00870 00871
   00872 00873 00874 00875 00986 01051 01052 01053 01396 01397 01399 01544
   01545 01546 01547 01548 01549 01550 01551 01558 01559 01560 01565 01567
   01569 01571 01572) — 14 of them by PR #354, which reduced the shape whose
   rate vanishes with a converted species, and the other 15 by PR #370,
   which added the algebraic balance — and 6 stay `unsupported` with a
   construct-naming reason: a rate constant an event or a rule sets (00987
   00988 01568 01570), a stoichiometry an event changes (01398), and a
   `delay` of the converted species (01539).

8. **A rate law on a concentration-valued species, and a scheduled action's
   concentration** (PRs #361 and #363). SBML L3V2 Core §4.11 makes a kinetic
   law's value the reaction's *extent* rate, and §4.6 makes a species' value
   in an expression its amount when it has `hasOnlySubstanceUnits="true"`
   and its concentration otherwise, so a law with `m` reactant factors of
   which `a` are amount-valued has the value `k * n**m / V**(m - a)`. BNGL's
   rate laws are always *concentration* rates, so the equivalent BNGL
   constant is `k * V**(a - 1)`. PR #363 scales the law by that factor; PR
   #361 makes an event's assignment to a concentration-valued species reach
   the species' *amount*, as canonical BNG2 does, by scaling the assigned
   concentration with the compartment volume.  Between them they move 39
   official-reference cases `failed → passed` (PR #361) and 11 more
   `failed → passed` or `unsupported → passed` (PR #363).

9. **A reference that names a reaction** (PR #378). The official suite asks
   for a reaction's rate by naming the reaction id as a result variable.
   SBML L3V2 Core §4.11.8 says such a symbol "represents the rate of the
   given reaction as given by the reaction's KineticLaw object", and §4.2.5
   says that rate is the rate of change of the reaction's extent. A
   reaction's rate is not an observable — the engine's observables count
   pattern matches — but a zero-argument BNGL *function* already is what the
   engine treats as an algebraic model output, so the Atomizer states each
   reaction's rate that way and the gate maps the reference's variable onto
   it. 22 official cases move `unsupported → passed`.

The combined effect of all of these changes is recorded in the merged
result below.

## What the campaign set out to do, and what it reached

The campaign set out to make the modern Atomizer the most correct, most
comprehensive and most robust SBML-to-BNGL converter it can be, with
**demonstrable** mathematical equivalence rather than merely successful
conversion. It set itself one rule above all others: *a conversion success
is not a conformance claim*. A model that BNG3 cannot represent exactly is
refused, with the refusal naming the construct that blocks it; it is never
approximated and counted as supported.

The method was a measurement, not an opinion:

* a **baseline** of the official SBML Test Suite and of a curated
  BioModels corpus, measured on a pinned suite revision and a pinned corpus
  inventory, so that every later claim is a comparison against a recorded
  measurement rather than a recollection;
* a **per-case gate** with four stages — conversion, round-trip structure,
  an independent libRoadRunner comparison, and a comparison against the
  suite's own published reference — so that "it converted" and "it is
  correct" are separate results;
* an **expectation manifest** that records the expected verdict of every
  case at every stage, so that a coverage regression fails a comparison
  instead of waiting to be noticed;
* **independent oracles** wherever one exists: libRoadRunner 2.10.0 on the
  source SBML, the suite's own `-results.csv` at the suite's own per-case
  tolerance, and canonical Perl BNG2 2.9.3 for the rate-law semantics;
* a **scope record** ([`ATOMIZER_LIMITATIONS.md`](ATOMIZER_LIMITATIONS.md))
  that names every construct the Atomizer still refuses, whether the
  boundary is reducible, and when it was recorded.

What it reached is in the generated tables below: on the measured tree the
conversion stage has **no failures**, while the official-reference comparison
has one retained failure, `stochastic/00003`, and no timeouts. Other remaining
gaps are declared refusals or comparisons the gate cannot make under its
current measurement budget; they are not successful scientific executions.

**How to read the numbers.** The figures in this document come from three
kinds of statement, and they are not interchangeable:

| Where | What it states | How fresh it is |
| --- | --- | --- |
| the generated regions | the measured state of the tree, with the report, that report's SHA-256 and the commit it measured | the current measurement, and the only place the current figures appear |
| the baseline section | the tree at the campaign's base commit, measured on 2026-10-19 | a historical fact; it is not rewritten |
| the merged-pull-request table | what each merged pull request changed and which cases it moved, measured on that pull request's own branch | a historical per-branch record; the numbers overlap where one change enables another |

**What remains.** The campaign is not finished, and this document does not
present it as finished. The open work is:

* **The Atomizer-side boundaries**, each described with its cases and its
  reducibility in `ATOMIZER_LIMITATIONS.md`: an event the Atomizer cannot
  lower or cannot order (the largest open cluster), the `fbc` package, the
  `delay`/`rateOf` operators, a fast reaction whose pseudo steady state
  cannot be written as a BNGL rule, a state trigger the runtime cannot
  schedule, an infinite or not-a-number constant, a compartment with more
  than three spatial dimensions, and a small bucket of refusals the
  taxonomy does not yet name.
* **The harness-side measurement limits**, which are not Atomizer refusals:
  12 official references for equal-priority events provide only one draw of
  a random execution order; 2 stochastic cases cannot fit the documented
  ensemble count within the fixed event-work budget; and 2 scheduled-action
  cases stop at a phase boundary the native dispatcher reports before the
  phase assignment is applied.
* **The cases the campaign could not make comparable**: the official suite
  itself records that 34 of its cases define no time-course reference, so
  there is nothing to compare against and nobody should go looking for a
  fix; two stochastic cases sit on the boundary of the generated
  scheduled actions, which the native dispatcher reports before the
  phase's assignment is applied.
* **The curated-BioModels corpus**, whose figures in the generated table
  are the campaign's **flat-mode** measurement. The corpus has not been
  re-measured since, so those figures are a dated record of a flat-mode
  run rather than a current statement about the corpus, and they must not
  be read as one. The corpus's own expectation manifest and its per-record
  inventory exist, and the last corpus failures are being triaged
  separately (PR #381).
* **The one pull request that is still open**: one that carries a reversible
  `TotalRate` rule into both directions of the SBML writer (PR #381). The
  corrected repair of the statistical factor of identical reactants
  (PR #382) has been merged; see
  [The ODE regression and the revert that closed it](#the-ode-regression-and-the-revert-that-closed-it).

## Merged result

The campaign's pull requests merge into `main` one at a time and the tree
advances with each merge, so **every number in this section is a moving
target**. The tables below are regenerated from a harness report by
`scripts/ci/sbml_campaign_tables.py`; they are never maintained by hand, and
each one names the report it came from, that report's SHA-256, and the BNG3
commit it measured. **The current figures live in those tables, and this
section states none of them**: a figure quoted here could outlive the
measurement it came from, and a path under a temporary directory is not a
durable record in any case.

| PR | What it changed | Official cases moved | Merge commit |
| --- | --- | --- | --- |
| #316 | Initial-value resolution order in atomizer seed species | 15 `failed → passed` | `3910dccd` |
| #317 | The machine-readable coverage inventory and the campaign baseline | — (measurement) | `25451a65` |
| #318 | `csymbol` by `definitionURL`; static parameter initial assignments | 20 `failed → passed` | `d4ec1ee2` |
| #319 | Amount-based rate laws in a non-unity compartment | 19 `failed → passed` | `0fbda8fd` |
| #320 | n-ary MathML relations | 3 `failed → passed` | `aa427e70` |
| #321 | Parameter assignment rules: the amount/concentration distinction | 10 `failed → passed` | `451884f5` |
| #322 | MathML trigonometric reciprocals; numeric fidelity; assigned stoichiometry | 14 `failed → passed` | `fa53a8e8` |
| #323 | Rate-ruled species-reference stoichiometry's initial value | 14 `failed → passed` | `9268d220` |
| #324 | SBML `delay` / `rateOf` semantics in the Atomizer and the C++ writer | 7 `failed → passed` | `a4453c7d` |
| #325 | Black formatting compliance on `main` | — (no behaviour change) | `03a577dd` |
| #326 | A static Python-floor compatibility check | — (CI only) | `d647aede` |
| #327 | The merge-gate exception record for #323 and #324 | — (record) | `c672c61f` |
| #328 | A state-dependent SBML event trigger lowered into the native event runtime | 24 `unsupported → passed` | `6c52c737` |
| #329 | SBML initial values resolved from the model's assignment statements as a whole | — (no verdict change on its own measurement) | `cf9afe42` |
| #330 | A batched SSA sweep that checks the stochastic consistency of converted models | — (verification) | `48315b95` |
| #331 | The pooled SBML conformance gate: one worker pool instead of a process per case | — (measurement speed) | `5c9ec354` |
| #332 | The SBML conformance expectation manifest and the table generator | — (measurement) | `6c61d59f` |
| #333 | A compartment's initial assignment applied; a non-finite parameter value reported | 4 `failed → passed` (00785 00786 01514 01820); 1 `passed → unsupported` (00951) | `2eb52050` |
| #334 | SBML L3V2 semantics for the elements that carry no MathML | 16 `unsupported → passed` | `a8499fbb` |
| #335 | The static evaluator's MathML built-ins and a signed stoichiometry | 1 `failed → passed` (`semantic/00879`) | `cee96c9a` |
| #336 | The assigned-stoichiometry diagnostic's reason, and always-on regression tests | — (diagnostic) | `d06cfc69` |
| #337 | The official references of action-bearing and stochastic cases validated | 424 `unsupported → passed`; 56 `unsupported → failed` (newly measured) | `d7b18d05` |
| #338 | Classify an unparsable changed file as needing a newer interpreter | — (CI only) | `c0190fb2` |
| #339 | Structural inference on the `atomize=True` path | — (the flat measurement path is byte identical) | `d1d0c1c7` |
| #340 | The curated BioModels inventory and the two Atomizer defects it exposed | — (corpus) | `5c9d8e1e` |
| #342 | The SBML specification citations, and a multiplicative compartment factor lowered exactly | — (no verdict change: the model text changes) | `71f84307` |
| #345 | The expectation-manifest gate and the manifest re-measured on current main | — (measurement) | `f2cb2acc` |
| #346 | The public helper's MathML built-ins from the shared table | — (no behaviour change) | `57736a19` |
| #347 | The parser's `package:fbc` diagnostic in the flux guards | — (diagnostic) | `eafd6deb` |
| #348 | A reaction's rate guarded on the sign of its derivative | — (diagnostic) | `89f19428` |
| #349 | The independent audit of the campaign's claims | — (record) | `a08215a5` |
| #350 | The stochastic-consistency sweep on the reproducible single-worker pool | — (measurement) | `8c617bf9` |
| #351 | CVODE, the state vector and the SUNContext released when an exception unwinds | — (no verdict change) | `0a3e7749` |
| #352 | The two curated-BioModels corpus regressions the audit found | — (corpus) | `ba5d2f63` |
| #353 | A species concentration rate rule in an event-driven compartment | 2 `failed → passed` (`semantic/01505`, `semantic/01506`) | `c7550723` |
| #354 | A fast reaction reduced to its pseudo steady state | 14 `unsupported → passed` | `48040e34` |
| #355 | The assignment-rule, algebraic-rule and `csymbol` conformance cases | 3 `failed → passed` (01121 01492 01493); 1 `failed → unsupported` (01575) | `55d66bbc` |
| #356 | An expectation manifest and a report comparison for the curated corpus | — (record) | `2d38c9a7` |
| #357 | A campaign status command and a single harness contract suite | — (measurement) | `a432e252` |
| #358 | The assignment-rule branch of the assigned-stoichiometry diagnostic, and its built-in guard | — (diagnostic) | `b202cd5e` |
| #359 | A random-event case and an unmodelled boundary species reported as not comparable | 3 `failed → unsupported` (`stochastic/00006`, `00024`, `00026`) | `387fe6d8` |
| #360 | The gate refuses to measure when the imported package is not this checkout | — (measurement) | `a195c901` |
| #361 | A scheduled action's concentration set as BNG2 does, and a boundary species as an action target | 39 `failed → passed` | `bef88c1c` |
| #362 | Each batch-SSA worker its own observable scratch, so a fixed seed is reproducible | — (no verdict change) | `b4171576` |
| #363 | A rate law on a concentration-valued species scaled by its compartment volume | 11 `failed → passed` or `unsupported → passed`; 2 `failed → unsupported` (00963 00967) | `1f4a2fa6` |
| #364 | The expectation manifest refreshed on the merged tree | — (record) | `8f095cd6` |
| #365 | The structural inference kept mathematically exact | — (the flat measurement path is byte identical) | `5d8e78b0` |
| #366 | A rate-ruled parameter assigned through its state; the phase budget widened | 4 `failed → passed` (01701 01702 01715 01716) | `248405ed` |
| #367 | The artifacts two gate runs produced, diffed and not only their verdicts | — (measurement) | `2d08ea70` |
| #368 | The official cases the action phase budget used to exclude | — (measurement) | `0b87c475` |
| #369 | The expectation manifest refreshed: the official-reference failure count is zero | — (record) | `7f8bebe1` |
| #370 | A fast reaction reduced to its algebraic balance | 15 `unsupported → passed` | `161017ee` |
| #371 | Several native SBML events executed in the order the specification defines | — (no verdict change) | `2053f3b0` |
| #372 | The expectation manifest refreshed after the fast reduction and the multi-event runtime | — (record) | `a1496fb1` |
| #373 | A dated, generated record of the Atomizer's limitations | — (record) | `1873ad5a` |
| #374 | The campaign's three records brought onto one measurement | — (record) | `ba892814` |
| #375 | The folded mass-action constant independent of the interpreter's hash seed | — (no verdict change) | `c673935b` |
| #376 | A state-triggered event group ordered by the priority it has at that instant | — (no verdict change) | `51fe8e00` |
| #377 | The SBML section references in the Atomizer's diagnostics | — (diagnostic) | `bf24830c` |
| #378 | A reference that names a reaction mapped to the reaction's extent rate | 22 `unsupported → passed` | `2cb9f2c3` |
| #379 | **Revert of #315**, which made the ODE engine apply a statistical factor to a total-rate reaction | — (revert: it restored the 63 official cases #315 broke) | `9213008f` |
| #380 | A boundary species honoured by the direct SSA path | 3 `unsupported → passed` (`stochastic/00006`, `00024`, `00026`) | `baa37832` |
| #382 | The statistical factor of identical reactants applied to a special rate law, and the compartment-volume conversion the engine was dropping from the same rate law | — (no official case carries a special rate law; the defect was an engine/network disagreement) | `52882969` |
| #383 | The three records onto the current measurement, and the two closed limitations | — (record) | `faf09c03` |

The "Official cases moved" column is measured per branch, so the numbers
overlap where one change enables another; it is a historical per-branch record
and not part of the generated region.

One row is not an improvement, and it is marked as such: **#379 is a
revert**. It removes what #315 did, and the reason is in
[The ODE regression and the revert that closed it](#the-ode-regression-and-the-revert-that-closed-it).
The table lists the campaign's *merged* pull requests, so the one that is
still open — #381 — is not in it.

The generated tables below give the measured before/after state of every
stage, the exact cases that changed verdict, and the cases that regressed.
They also cover the changes whose effect is not broken out per branch above.

### The campaign's invariant, audited

The campaign's central invariant is that **no case becomes `passed` because
a diagnostic was removed, a tolerance was widened, a reference file was
edited, or a comparison was skipped**. It is not an assertion; it is an
audited result.

The independent audit is recorded in
[`provenance/sbml-campaign/audit-2026-10-21.json`](../provenance/sbml-campaign/audit-2026-10-21.json)
(PR #349). It measured the tree at `d7b18d05` against the campaign's base
commit `219c76da`, on 2026-10-21, in an isolated worktree with a private
clone of the pinned suite revision, and it recorded for every case whose
verdict moved both the transition at each stage and the **mechanism** of the
change. Its conclusion, for the set it audited: the input, settings and
results digests are byte-identical to the baseline for all 1923 cases, so no
reference file was edited, no tolerance was widened and no comparison was
skipped; every case the gate reports as `passed` has a non-empty official
comparison with zero failed points, a passing independent libRoadRunner
round trip, and a passing round-trip structure.

The audit also recorded the one place where a removed diagnostic could have
hidden an approximation, and showed that it did not. Its record attributes
a removed `dropped`/`approximated` warning to 51 of the cases it measured,
and the audit checked each of them: where the case moved to a passing
verdict, the construct became exactly representable — the MathML
trigonometric reciprocals are lowered to exact algebraic identities, a
negative stoichiometry is represented rather than omitted — and the published
reference agrees. The other five are the audit's findings rather than wins:
four cases became `failed` because a comparison that had never been made was
made and disagreed, and one stayed `unsupported`. The audit then
re-simulated every case that moved to a passing official-reference verdict
from its own SBML with libRoadRunner 2.10.0 and compared it with the
published `-results.csv` at the official per-case tolerance: 500 of the 551
reproduce the published reference within that tolerance, and the other 51 are
models libRoadRunner itself refuses to load (`delay`, an algebraic rule, a
`fast` reaction), for which the published reference is the only witness.

**The invariant has been checked again since.** The audit measured a tree
that has since moved a long way; the current measurement is in the
generated tables below. It has one official-reference failure,
`stochastic/00003`, and no conversion failure. Every verdict-changing merge since has been
gated by the expectation manifest's ratchet, which fails a change that
drops a case from `passed` unless the manifest is updated explicitly, and
the manifest was refreshed on the merged tree as the campaign's work landed
(PRs #364, #369, #372, #374 and #383). The one regression the campaign
introduced was caught by the official-suite conformance measurement and
reverted — see
[The ODE regression and the revert that closed it](#the-ode-regression-and-the-revert-that-closed-it).

**The audited record describes the tree the audit measured.** Its counts are
a historical fact about that tree, not a description of the current one, and
this document does not use them as one.

<!-- BEGIN GENERATED: sbml-campaign-current -->

#### Official SBML Test Suite — current stage results

| Stage | Passed | Unsupported | Failed | Not tested |
| --- | --- | --- | --- | --- |
| Conversion (SBML → BNGL) | 1798 | 125 | 0 | 0 |
| Round-trip structure | 1798 | 0 | 0 | 125 |
| Independent libRoadRunner comparison | 1798 | 0 | 0 | 125 |
| Official reference comparison | 1781 | 141 | 1 | 0 |
_Source: `/tmp/bng3-campaign/run39878668497/ssts-31ae76c19fdd03c9d4af788f58dd5187726e14a1-1/report.json` (SHA-256 `49601d78bac943c536e111d575765e3823a808a1af11a66d9f88e83977a8833f`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `31ae76c19fdd03c9d4af788f58dd5187726e14a1`; a timed-out case is recorded as failed and an unevaluated stage as not tested._

#### Official-reference unsupported verdicts, by owner

| Count | Owner | Blocking reason |
| --- | --- | --- |
| 70 | Atomizer | state-dependent / non-constant SBML events untranslated |
| 34 | not applicable | case does not define an official time-course reference |
| 15 | Atomizer | other Atomizer-side limitation |
| 9 | C++ writer | SBML math function "…" is not losslessly representable in the C++ SBML writer |
| 6 | Atomizer diagnostic | Reaction "…" is marked fast (fast="true") |
| 3 | Atomizer | <infinity>/<notanumber> constant encountered in math |
| 2 | Atomizer | a compartment declares unsupported spatialDimensions |
| 2 | harness | the documented ensemble budget does not fit the gate's per-case ensemble work budget |

Total official-reference unsupported verdicts: 141.
_Source: `/tmp/bng3-campaign/run39878668497/ssts-31ae76c19fdd03c9d4af788f58dd5187726e14a1-1/report.json` (SHA-256 `49601d78bac943c536e111d575765e3823a808a1af11a66d9f88e83977a8833f`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `31ae76c19fdd03c9d4af788f58dd5187726e14a1`._

#### Remaining official-reference failures, by official feature

| Cluster | n | Cases |
| --- | --- | --- |
| other | 1 | 00003 |

Total official-reference failures: 1.
_Source: `/tmp/bng3-campaign/run39878668497/ssts-31ae76c19fdd03c9d4af788f58dd5187726e14a1-1/report.json` (SHA-256 `49601d78bac943c536e111d575765e3823a808a1af11a66d9f88e83977a8833f`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `31ae76c19fdd03c9d4af788f58dd5187726e14a1`; clusters read from `/tmp/bng3-ssts-20261016` case notes._

<!-- END GENERATED: sbml-campaign-current -->

`stochastic/00003` remains an official-reference failure in this report. The
recorded 40,000-run ensemble violates 5 of 100 DSMTS mean/standard-deviation
tests; the report estimates a `3.04e-7` tail probability under the guide's
approximate-normal null assumptions. A separate exact linear birth-death
source-law calibration of the registered 40,000-run seed-2,000,000 ensemble
is retained in
[`stochastic-00003-heldout-run-39881927354.json`](../provenance/sbml-campaign/stochastic-00003-heldout-run-39881927354.json)
and
[`stochastic-00003-heldout-source-law-calibration-39881927354.json`](../provenance/sbml-campaign/stochastic-00003-heldout-source-law-calibration-39881927354.json).
The run executed on product revision `f9a9880f`, where the exact source-law
diagnostic was registered before execution. It passes the official comparison
with 2 of 100 DSMTS tests outside the reference bounds; the calibrated
source-law maximum-statistic tail estimate is 0.665 (95% Wilson interval
0.635–0.694) at diagnostic alpha 0.01. The official run's estimated tail under
the guide's approximate-normal null is 0.00827 at case error rate 0.001. The
diagnostic reconstructs its statistic from the report's rounded summary
arrays, and its PASS is scoped to this one ensemble. Its seed and result hash
match an earlier replay, so it is not an independent second engine ensemble
or general simulator qualification. The default-seed full report still
records the original official failure; the expectation manifest keeps
`stochastic/00003` failed.

The generated comparison above lists every case whose verdict changed, the
stage it changed at, and every case that regressed. A stage that stops being
`passed` is a regression: the run then delivers less than the expectation
manifest records, and the manifest must be updated before the change is
accepted. The four cases the comparison lists as regressions are the
campaign's own *corrections*, not a loss of coverage: each is a case that
was reported as supported while the model it produced was wrong or the
construct it used was untranslated, and each is now an explicit refusal that
names the construct. `semantic/00951` is a parameter with an infinite value,
`semantic/01466` and `semantic/01575` and `semantic/01576` are events the
lowering could not carry out.

The curated-BioModels row in the generated table is an **aggregate**, and an
aggregate hid two reproducible regressions: `BIOMD0000000638` and
`BIOMD0000000954` both changed behaviour while the corpus-wide counts stayed
the same. The two were found by the corpus inventory (PR #340) and are fixed
there. The claim and the correction belong together: the aggregate number
was never evidence that nothing changed, and the corpus is now inventoried
per record so that it cannot be again.

That row is also the campaign's **flat-mode** measurement, and the report it
came from names the date it was taken. The corpus has not been re-measured
since, so the row is a dated record of a flat-mode run and not a current
statement about the corpus; the generated table names its report and that
report's SHA-256, and this document does not restate its numbers. The
corpus's own expectation manifest and per-record inventory exist (PR #356),
so a corpus regression is now a comparison rather than a human reading two
large reports side by side, and the corpus's remaining failures are being
triaged separately (PR #381).

## Python test suite

<!-- BEGIN GENERATED: sbml-campaign-python -->

#### Result

_Python suite counts were not measured in this run (pass `--pytest-junit`)._

<!-- END GENERATED: sbml-campaign-python -->

The row above is the Python suite as it ran on the measured tree, and it
carries **47 failures**, not one. They are two different things:

* **1 failure** — `test_generated_notebooks_execute_in_qualified_kernel` —
  needs a Jupyter kernel and fails identically on the campaign's base
  commit.
* **46 failures** — all of `tests/python/test_sbml_reaction_rate_outputs.py`
  (PR #378) — fail with `FileNotFoundError` on the fixture the test reads,
  `tests/fixtures/sbml_test_suite_reaction_rate/NNNNN-sbml-l3v2.xml`. The
  fixture directory is committed with each case's `-results.csv` and
  `-settings.txt` but **not** with the case's SBML source model, so the test
  cannot read the model it is supposed to atomize. These failures are
  present on the merged tree and are a defect in the test's own fixtures,
  not a failure of the Atomizer; the reaction-rate behaviour they cover is
  measured against the official reference by the generated tables above.

This is a prose change, so the defect is recorded here and not repaired
here; it needs a commit that adds the missing fixture files, or a test that
resolves the source model from the pinned suite checkout.

### A regression the campaign's own validation caught

The first form of PR #319 multiplied the recovered mass-action constant by
`V**(m-1)` for every amount-based law. The generated integrated-validation
case `dimerization-v1-n20-r0-a0` uses the law `k * A * A / cell`, which
already states its own volume dependence, so the correction changed the
model: a kinetic law's value is the reaction's extent rate and a species'
amount changes by `stoichiometry × extent rate` (SBML L3 Core §4.11), while
BNGL's rate laws are always *concentration* rates, so the amount-based law
`k * n^m` needs `V^(m-1)` and a law that already divides by the compartment
size needs `V^(m-2)` — for the two-reactant form, the constant it was
recovered with. The integrated cross-component validation failed, and the
correction was narrowed to a law that does not name a compartment.

Narrowing it that way also exempted a law that *multiplies* by the
compartment (`cell * k * A * A`), whose volume dependence is the opposite of
the divisive form's: its extent rate scales with the compartment size, so
its BNGL constant needs `V^m` rather than the constant it was recovered
with. On a size-10 compartment BNG3 gave `A_amt(5) = 2.222222` where the
SBML extent-rate reading gives `0.024969`, a factor of `V**2`. The
exemption now distinguishes the two shapes, and the multiplicative form is
lowered exactly.

### The ODE regression and the revert that closed it

PR #315 ("Reconcile issue obligations and detect native BNGIR rule reference
corruption", merged as `25f13c5b`) was merged into `main` and **reverted**
by PR #379 (`9213008f`). It is the one regression the campaign introduced,
and it is recorded here because a reader of the merged-pull-request table
must not read the revert as an improvement.

#315 made the native ODE engine apply a reaction's **statistical (symmetry)
factor** to a **total-rate** reaction's flux. In `cpp/engine/OdeIntegrator.cpp`
the guard

```cpp
if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) combinedFactor *= rxn.getFactor();
```

lost its `!crxn.isTotalRate` half at **two** sites: the special-rate-law
branch and the functional (total-rate) branch. The special-rate-law site was
the intended one — #315's own reconciliation record says the statistical
factor "is a property of the rule's reactants, not of the rate law's shape" —
and the total-rate site was a collateral removal. A total-rate rule's value
**is** the reaction's extent rate (SBML L3V2 Core §4.11), and the Atomizer
encodes the stoichiometry in the rule's pattern, so multiplying such a rule's
flux by `1/2` changes the model. **Every one of the 63 affected cases has a
converted rule of the shape `A + A -> ... <rate> TotalRate`.**

The failure was numeric, not tolerance noise: for `semantic/00069` the
comparison failed 148 of 153 output points, with a maximum scaled error of
62.4, 56.8 and 435.6 on the three species. The measurement of `main` while
#315 was in it reported 63 failures at the official-reference stage and 63
at the conversion stage, where the tree before it reported none.

**The Atomizer is not implicated, and the revert shows it on the model text
rather than asserting it.** The generated BNGL for the failing cases is
byte-identical between the reverted tree and the tree carrying #315. The
only thing that differs is the native binary, and the verdict follows the
binary: the same model text, a different trajectory.

PR #379 reverts `25f13c5b` in full and restores the state in which the
official suite measures zero failures. It changes no verdict, no tolerance,
no reference file and no excluded case. **#315's content is not lost**: it
remains in the repository's history, and its fixes are being re-applied
selectively, each on its own, each gated on the official-suite conformance
measurement — which is what the revert makes possible again. #315's intended
repair of the statistical factor is *not* being discarded on its merits: the
guard it removed was doing real work for total-rate reactions. The correct
repair applies the factor to a **special** rate law, where canonical Perl
BNG2 2.9.3 writes it as a prefix on the rate law for every rate-law type
(`my $sf = ($rxn->RxnRule && $rxn->RxnRule->TotalRate) ? 1 : $rxn->StatFactor;`),
and leaves a **total-rate** law alone. That repair was separate work, with
its own evidence, and it has been merged (PR #382): the engine now applies
both the conversion and the statistical factor to a special rate law, so it
agrees with the network it exports.

### Merge-gate exception: PRs #323 and #324

The campaign's stated merge gate is that all required CI checks pass. Two
further campaign pull requests — #323 (carry a rate-ruled species-reference
stoichiometry's initial value) and #324 (preserve SBML `delay`/`rateOf`
semantics in the Atomizer and the C++ SBML writer) — were merged with that
gate not fully met, by an explicit decision of the repository owner, so that
a saturated CI queue would not serialize the campaign. On both pull requests
three jobs were genuinely red; every other job marked red on those pull
requests was `cancelled` in flight, not failed.

The gate is the campaign's own convention, not a rule GitHub enforces: the
repository has no branch protection and no rulesets on `main`
(`GET /repos/RuleWorld/BNG3/branches/main/protection` returns 404 and
`GET /repos/RuleWorld/BNG3/rulesets` returns an empty list), so nothing in
the platform required the merge — the exception was a decision of the
repository owner.

* `Lint & Format` and `Check formatting and suggest patch` (the
  `autofix` workflow's `black --check --target-version py312 .` gate). This
  was a formatting-only defect: the campaign's Python was not formatted with
  the repository's pinned `black==26.10.0`. The same formatting-only change
  was landed on `main` afterwards, in PR #325 (commit `b3de638e`, merged as
  `03a577dd`); `black --check --diff --target-version py312 .` and
  `ruff check python/ tests/ scripts/ formal/` are clean on the merged tree,
  and no semantics changed (the three reformatted files parse to an
  identical AST before and after).
* `C++ ASan (Ubuntu)`, failing at the step `Qualify issue 141 late CVODE
  exception cleanup`. This failure is **not** attributable to the merged
  changes. The same job fails on `main` itself at the campaign's base commit
  `219c76da` (run `39345689608`, job `118377593427`), at the same step, with
  the same LeakSanitizer signature (`SUMMARY: AddressSanitizer: 12592 byte(s)
  leaked in 137 allocation(s)`). PR #323's `cpp/` tree is byte-identical to
  `219c76da` — the campaign changed no C++ before #324 — and PR #324's only
  C++ changes are in `cpp/io/SbmlReader.cpp` and `cpp/io/SbmlWriter.cpp`,
  which the leak stacks do not reach: the reported leaks originate in
  `__static_initialization_and_destruction_0` frames under
  `BNGcore::BondNodeFunction::clone()`, not in the ODE integrator. The
  *functional* issue-141 test passes: in the same ASan job, the `Run tests
  under ASan` step reports `100% tests passed, 0 tests failed out of 677`
  (`681` on #324), including `OdeIntegrator recovers after late stop
  condition failure`, and `ctest --test-dir build -R '^OdeIntegrator recovers
  after late stop condition failure$'` passes locally. The red is therefore a
  **source-confirmed defect in the `OdeIntegrator` exception path — a CVODE
  cleanup leak — that the ASan job was deliberately wired up to expose**, and
  it is tracked as issue 141 (`docs/PACKET4_141_ACCEPTANCE.md` and
  `docs/packet4-141-acceptance.json`, whose acceptance criteria are still
  `INCOMPLETE`). The mechanism is in the source:
  `cpp/engine/OdeIntegrator.cpp` allocates
  `void* cvode_mem = CVodeCreate(CV_BDF, sunctx)` together with an
  `N_Vector y` and a `SUNContext`, and frees them by hand on each error
  path, but there is no unwinding-safe cleanup, so an exception thrown out
  of the right-hand-side evaluation after CVODE has allocated leaks all
  three. The source-confirmed exception path is
  `stop_if='if(time > 0, missing_name, 0)'`: the lazy `if` succeeds at
  `t=0` and raises after CVODE allocation, so the exception bypasses the
  normal CVODE cleanup. This is a real defect, not a timing or environment
  artefact.

The repair of the CVODE cleanup leak has since landed, in PR #351
(`0a3e7749`): `cvode_mem`, `y` and `sunctx` now have an unwinding-safe
lifetime, and the `C++ ASan (Ubuntu)` job's qualification step reports an
**empty** LeakSanitizer report and `100% tests passed, 0 tests failed out of
682`, where the same step on `main` reported `SUMMARY: AddressSanitizer:
12592 byte(s) leaked in 137 allocation(s)` and failed (CI run `39525857115`,
job `118980209432`, against run `39451902614`, job `118728607326` on
`main`). The repair's own per-case diff against the campaign's measurement
is empty, because the ODE engine is involved and the SBML verdicts must not
move. The issue-141 acceptance record itself
(`docs/PACKET4_141_ACCEPTANCE.md`, `docs/packet4-141-acceptance.json`) is a
separate, live qualification effort and was not modified by the repair.

The discriminating checks were green at the merged heads. The `Official SBML
references (128 PR cases; full scheduled suite)` job passed on both pull
requests, and the campaign's own pinned-suite runs with per-case diffs against
the merged baseline were the primary evidence: #323 ran all 1923 pinned
cases (1823 semantic plus 100 stochastic) and moved 14 cases `failed →
passed` with 0 regressions; #324 ran the 1823 semantic cases and moved 7
cases `failed → passed` with 0 regressions. The independent reviews of #323
and #324 were still outstanding at merge time and were completed after the
fact.

## Expectation manifest

[`provenance/sbml-campaign/expectations.json`](../provenance/sbml-campaign/expectations.json)
records the **expected verdict of every official SBML Test Suite case at every
stage of the gate**. It turns a coverage regression into a failing comparison
instead of a human reading two large reports side by side.

### Schema

```json
{
  "schema_version": 1,
  "kind": "sbml-test-suite-expectations",
  "generator": "scripts/ci/sbml_campaign_inventory.py",
  "stages": ["conversion", "roundtrip_structure", "independent_comparison", "official_reference"],
  "statuses": ["passed", "unsupported", "failed", "not_tested"],
  "status_mapping": { "conversion": "…", "roundtrip_structure": "…", "independent_comparison": "…", "official_reference": "…" },
  "suite": {
    "repository": "https://github.com/sbmlteam/sbml-test-suite.git",
    "revision": "cf38585fac5de8e0e90112febb62851ee2181816",
    "categories": ["semantic", "stochastic"],
    "case_count": 1923
  },
  "source_report": {
    "sha256": "<sha256 of the harness report the manifest was generated from>",
    "bng3_commit": "<BNG3 commit the manifest describes>",
    "measured_at_commit": "<BNG3 commit the run actually executed>",
    "python_version": "3.14.6",
    "measurement_date": "2026-10-21"
  },
  "provenance": {
    "measured_commit": "<the commit the manifest describes>",
    "measured_at_commit": "<the commit the run executed>",
    "measurement_environment": {
      "source_tree": "<the Python package the run imported>",
      "native_extension_sha256": "<sha256 of the native extension>",
      "platform": "<platform>",
      "libsbml_version": "<version>",
      "roadrunner_version": "<version>"
    },
    "notes": ["<why the two commits are equivalent for the gate>"]
  },
  "stage_counts": {
    "conversion": {"passed": 1798, "unsupported": 125},
    "roundtrip_structure": {"not_tested": 125, "passed": 1798},
    "independent_comparison": {"not_tested": 125, "passed": 1798},
    "official_reference": {"passed": 1784, "unsupported": 139}
  },
  "cases": {
    "semantic/00001": {"conversion": "passed", "roundtrip_structure": "passed", "independent_comparison": "passed", "official_reference": "passed"},
    "semantic/01133": {"conversion": "unsupported", "roundtrip_structure": "not_tested", "independent_comparison": "not_tested", "official_reference": "unsupported", "gap": {"conversion": {"construct": "compartment:unsupported-spatial-dimensions", "causes": ["constraints"], "side": "atomizer"}}}
  }
}
```

* `cases` has one entry per case, keyed `category/id`, and one status per
  stage. The status vocabulary is closed: `passed`, `unsupported`, `failed`,
  `not_tested`.
* `not_tested` means the stage produced no verdict (never executed, no
  reference defined, or the source was invalid). A timed-out case is recorded
  as `failed`, because the stage was attempted and did not succeed.
* `passed` is a result. `failed` is a result too: the stage ran and
  disagreed with the reference, which is a finding to investigate.
  `unsupported` is the only **gap**: the case was refused because a
  construct is not representable today, and its `gap` entry names the
  construct and the harness's cause labels for it. No entry claims that a
  currently-unsupported construct should become supported, and a case that
  stops being refused is a finding to be reported, not a pass.
* `status_mapping` states how each harness field becomes a verdict, so the
  mapping is auditable rather than implicit.
* `stage_counts` is the recorded summary of the four stages. It is derived
  from the per-case verdicts, so the summary and the detail cannot drift
  apart.
* `provenance` records the measurement environment: the commit the manifest
  describes, the commit the run actually executed, the source tree and the
  native extension's SHA-256. A run may execute a branch head whose Atomizer
  behaviour is identical to the described commit; that difference is stated
  rather than left implicit.

### Regenerating the manifest

Refreshing the manifest is an explicit, reviewable act: it rewrites a
committed file, and the diff is the review.

```bash
# 1. Run the gate against the pinned suite.
PYTHONPATH=python:build/cpp python scripts/ci/validate_sbml_test_suite.py \
  --suite-dir /path/to/sbml-test-suite \
  --categories semantic stochastic --isolate-cases --case-timeout 120 --jobs 3 \
  --json "$REPORTS/report.json"

# 2. Regenerate the manifest from that report.
python scripts/ci/sbml_campaign_inventory.py \
  --suite-report "$REPORTS/report.json" \
  --expectations-out provenance/sbml-campaign/expectations.json \
  --measurement-date "$(date -u +%Y-%m-%d)" \
  --measured-commit "$(git rev-parse HEAD)" \
  --expectations-provenance provenance/sbml-campaign/provenance-current-2026-10-22.json
```

`--measured-commit` is the commit the manifest *describes*; the commit the run
actually executed is kept as `measured_at_commit`, together with the native
extension's SHA-256 and the source tree, so a reader can tell which build
produced the numbers.

### What the pull-request gate covers, and the merge-flow convention

The official conformance workflow compares a run against the manifest, but a
pull-request run executes only the **128-case feature-cover selection** of
the official suite. The comparison covers the cases that run executed; the
rest are reported as *not executed* rather than as differences. Only the
**scheduled** workflow run executes the full 1923 cases and compares every
one of them. **A green pull-request gate is therefore not evidence that the
manifest is current.**

The manifest is a ratchet: a merge that changes a verdict leaves `main`'s
manifest stale, and the gate then fails on `main` until the manifest is
regenerated. After each such merge the manifest is regenerated from the new
`main` and landed as a small follow-up commit; the exact command is in
[`provenance/sbml-campaign/README.md`](../provenance/sbml-campaign/README.md).

### Comparing a run against the manifest

```bash
python scripts/ci/sbml_campaign_inventory.py \
  --suite-report "$REPORTS/report.json" \
  --expectations provenance/sbml-campaign/expectations.json
```

The comparison is strict about every difference:

* a stage that was `passed` and no longer is is a **regression**;
* a stage that was `failed` and is now `passed` is an **improvement**, and is
  only accepted once the manifest is explicitly updated;
* any other verdict change is reported as a **change**.

The command exits non-zero and prints one line per differing case and stage.
An example — a manifest that expected a pass where the run still refuses the
case:

```
semantic/01133 [conversion]: expected passed, observed unsupported (regression)
```

`tests/validation/test_sbml_expectations.py` exercises the same generator and
comparator, checks the committed manifest against the committed inventory, and
runs a bounded live gate when `BNG3_SBML_SUITE_DIR` names a pinned suite
checkout.

## Regenerating the tables

Every table in this document is produced by
`scripts/ci/sbml_campaign_tables.py`, which reads the harness reports and the
pinned suite's own case notes and writes the marked regions above.

The `--measured-commit` argument is the commit the committed expectation
manifest *describes*, and the report is the one that manifest names, so the
command below reproduces the committed regions exactly when `$REPORTS` holds
that report as `current-suite.json` with the baseline reports beside it. The
report's own name and SHA-256 are in the generated region, so the file to
point at is identifiable from the document alone:

```bash
# The commit the committed manifest describes, and the report it names.
MEASURED_COMMIT="$(python -c 'import json; print(json.load(open("provenance/sbml-campaign/expectations.json"))["provenance"]["measured_commit"])')"

python scripts/ci/sbml_campaign_tables.py \
  --baseline-suite-report "$REPORTS/baseline-ssts.json" \
  --suite-report "$REPORTS/current-suite.json" \
  --baseline-biomodels-report "$REPORTS/biomodels-baseline.json" \
  --biomodels-report "$REPORTS/biomodels-main-flat.json" \
  --suite-dir /path/to/sbml-test-suite \
  --pytest-junit "$REPORTS/pytest-current.xml" \
  --measured-commit "$MEASURED_COMMIT" \
  --doc docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md
```

Each generated region names the report it came from and that report's
SHA-256, so a reader who does not have the report on this machine can still
tell which measurement the numbers describe. The `--measured-commit`
argument is the **full** commit hash: the generator compares it with the
commit the report says it executed, and it adds a note that the two differ
when the two strings are not equal, so an abbreviated hash would change the
region's text.

The Python-suite row is read from a pytest JUnit report:

```bash
PYTHONPATH=python:build/cpp python -m pytest -q tests/python \
  --junitxml="$REPORTS/pytest-current.xml"
```

The generator never runs the harness, never changes a verdict and never
edits reference data. Each generated table states the report, the report's
SHA-256, the SBML Test Suite revision and the BNG3 commit it came from.

A document hands a section to the generator with two HTML comments. The
generator rewrites everything between them, and `--check` verifies that the
content still matches the reports without touching the document:

```markdown
<!-- BEGIN GENERATED: sbml-campaign-current -->
…generated markdown…
<!-- END GENERATED: sbml-campaign-current -->
```

The recognised region names are `sbml-campaign-baseline`,
`sbml-campaign-current` and `sbml-campaign-python`. A document may place the
regions wherever the surrounding prose needs them.

```bash
python scripts/ci/sbml_campaign_tables.py \
  --baseline-suite-report "$REPORTS/baseline-ssts.json" \
  --suite-report "$REPORTS/current-suite.json" \
  --baseline-biomodels-report "$REPORTS/biomodels-baseline.json" \
  --biomodels-report "$REPORTS/biomodels-main-flat.json" \
  --suite-dir /path/to/sbml-test-suite \
  --pytest-junit "$REPORTS/pytest-current.xml" \
  --measured-commit "$MEASURED_COMMIT" \
  --check --doc docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md
```

A drifted region is reported as a unified diff and the command exits
non-zero.

## Reading the campaign's state in one command

The tables above are assembled by a generator, and the numbers they carry
come from reports that are produced by different tools. `scripts/ci/sbml_campaign_status.py`
reads the reports themselves and answers, in one place: what the Atomizer
supports now, what changed since the previous measurement, and whether the
committed expectation manifest still describes reality.

```bash
python scripts/ci/sbml_campaign_status.py \
  --suite-report "$REPORTS/report.json" \
  --previous-suite-report "$REPORTS/previous.json" \
  --biomodels-report "$REPORTS/biomodels.json" \
  --corpus-inventory provenance/curated-biomodels-corpus-inventory.json \
  --suite-dir /path/to/sbml-test-suite \
  --checkout-root .
```

It reports the per-stage counts of the SBML suite and of the curated corpus
with the report's SHA-256, the commit the run executed and the native
extension's digest; the remaining official-reference failures grouped by the
campaign's official-feature clusters; the unsupported cases split by the side
of the gap — a *harness-side* gap is a measurement limitation, an
*Atomizer-side* gap is a representational one, and the two are different kinds
of work; the per-case diff against the previous report, classified as a
regression, an improvement or a change, with the regressions first; and
whether the expectation manifest is current.

The command is a reporter. It never changes a verdict, a tolerance, a
reference file, or the harness's own behaviour.

Its exit status is a bit mask, so that every condition is separately visible:

| Bit | Condition |
| --- | --- |
| 1 | a regression is present (a stage that was `passed` and no longer is) |
| 2 | the expectation manifest is stale against this report |
| 4 | the report's provenance does not match the checkout it is read against |
| 8 | the report does not account for every case it ran |

The provenance bit is the important one. The harness inserts the *repository
root* into `sys.path`, not `python/`, so a run without
`PYTHONPATH=python:build/cpp` silently measures the installed copy of
`bionetgen` in `site-packages`. The status command does not depend on a
guard for that: it reports the package path, the native extension's path and
digest, and the commit the run executed, and it refuses to present a report
it cannot tie to the checkout as a clean result.

```bash
python scripts/ci/sbml_campaign_status.py \
  --suite-report "$REPORTS/report.json" --json "$REPORTS/status.json"
```

## The harness's own contract suite

The harness's invariants were asserted in four or five scattered files.
`tests/test_harness_contracts.py` is the single entry point for them:

```bash
PYTHONPATH=python:build/cpp python -m pytest -q tests/test_harness_contracts.py
```

Where an invariant is already asserted elsewhere, that suite *calls* the
assertion instead of repeating it, so there is one place to keep in step.
Beside each call it shows that a deliberately broken copy of the thing the
invariant guards is detected, because an invariant that cannot fail is not an
invariant. The invariants are:

1. every case is accounted for — the stage counts sum to the cases that ran,
   no case is silently dropped, and a new outcome bucket has to be added to
   the vocabulary deliberately;
2. provenance is present and checkable — a report names the package, the
   native build, the suite revision and the tool versions, and a package that
   is not traceable to the checkout cannot be presented as this checkout's
   measurement;
3. the comparison tool reports verdicts, not provenance or order;
4. the gate's isolation is real — a case cannot observe another case's state,
   and the case order is not significant;
5. the expectation manifest's ratchet behaves — a regression fails, an
   improvement needs an explicit manifest update, a foreign suite revision is
   rejected, and every gap names a construct and records its side;
6. the verification slot fails open and never deadlocks, and the `--jobs`
   guard caps the worker count;
7. the artifacts are reproducible under a pinned `PYTHONHASHSEED`, and an
   artifact that is not comparable is detected rather than reported as a
   difference;
8. the Python-floor check reaches the same verdict on every interpreter from
   the declared floor upwards, including a construct the host cannot parse.

## Invariants for this campaign

* A conversion success is not a conformance claim. Official conformance is
  reported separately from conversion, and unsupported is never counted as a
  pass.
* An explicit refusal is always better than a silent approximation.
* No tolerance is weakened, no reference data is edited, no test is removed
  to obtain a pass.
* A BNG3-generated artifact is never used as BNG3's own oracle.
* Structural inference must never change the mathematics; where several
  molecular interpretations fit, the ambiguity is reported rather than
  resolved silently.
* A coverage regression fails a test. The expectation manifest is the
  recorded expectation; changing it is an explicit, reviewable act.
