# SBML Atomizer coverage campaign

Target: make the BNG3 modern Atomizer the most correct, comprehensive and
robust SBML-to-BNGL converter, with **demonstrable** mathematical equivalence
rather than merely successful conversion.

This document records the campaign's measurement baseline, the failure
clusters derived from it, and the state of each workstream.

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

## How to reproduce the baseline

```bash
# Official SBML Test Suite, pinned revision cf38585fac5de8e0e90112febb62851ee2181816
PYTHONPATH=python:build/cpp python scripts/ci/validate_sbml_test_suite.py \
  --suite-dir /path/to/sbml-test-suite \
  --categories semantic stochastic --isolate-cases --case-timeout 120 --jobs 6 \
  --artifacts-dir /tmp/bng3-campaign/artifacts-baseline \
  --json /tmp/bng3-campaign/baseline-ssts.json

# Curated BioModels, flat and atomized modes
python scripts/ci/validate_published_biomodels.py \
  --cache-dir /path/to/biomodels-cache \
  --json /tmp/bng3-campaign/biomodels-baseline.json \
  --mode flat --isolate-models --model-timeout 120 --jobs 4
```

## Baseline (base commit `219c76da`, measured 2026-10-19)

The official SBML Test Suite has 1923 pinned cases (1823 semantic + 100
stochastic). The curated BioModels corpus has 1096 records.

<!-- BEGIN GENERATED: sbml-campaign-baseline -->

#### Official SBML Test Suite — baseline stage results

| Stage | Passed | Unsupported | Failed | Not tested |
| --- | --- | --- | --- | --- |
| Conversion (SBML → BNGL) | 1712 | 211 | 0 | 0 |
| Round-trip structure | 1712 | 0 | 0 | 211 |
| Independent libRoadRunner comparison | 1712 | 0 | 0 | 211 |
| Official reference comparison | 1115 | 701 | 107 | 0 |
_Source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `219c76dac38655c0f15a12ee294e4a4ac10d02ef`; a timed-out case is recorded as failed and an unevaluated stage as not tested._

#### Official-reference unsupported verdicts at the baseline, by owner

| Count | Owner | Blocking reason |
| --- | --- | --- |
| 433 | harness | the in-memory CVODE reference runner cannot execute actions on the official output grid |
| 100 | harness | official stochastic conformance requires repeated-run mean and standard-deviation evaluation |
| 35 | Atomizer diagnostic | Reaction "…" is marked fast (fast="true") |
| 34 | not applicable | case does not define an official time-course reference |
| 28 | Atomizer | state-dependent / non-constant SBML events untranslated |
| 19 | harness mapping | no exact BNG3 result mapping for: <reaction id> |
| 16 | Atomizer | … has no MathML expression (empty math) |
| 14 | Atomizer diagnostic | <sec>/<csc>/… in math; BNGL has no built-in function |
| 9 | C++ writer | SBML math function "…" is not losslessly representable in the C++ SBML writer |
| 5 | Atomizer | … has unsupported stoichiometry; the reaction is omitted |
| 3 | Atomizer | <infinity>/<notanumber> constant encountered in math |
| 2 | Atomizer | a compartment declares unsupported spatialDimensions |
| 2 | Atomizer | a species concentration rate rule requires an explicit compartment derivative |
| 1 | Atomizer | algebraic rule(s) present |

Total official-reference unsupported verdicts: 701.
_Source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `219c76dac38655c0f15a12ee294e4a4ac10d02ef`._

#### Baseline official-reference failures, by official feature

| Cluster | n | Cases |
| --- | --- | --- |
| InitialAssignment | 34 | 00616 00617 00618 00631 00632 00633 00676 00677 00678 00688 00697 00698 00706 00785 00786 00787 00788 00879 01494 01498 01513 01514 01516 01631 01633 01642 01643 01644 01651 01652 01653 01766 01781 01821 |
| CSymbolAvogadro | 15 | 00960 00961 01121 01316 01323 01479 01641 01665 01722 01723 01762 01763 01775 01776 01777 |
| other | 14 | 00951 01002 01003 01005 01006 01009 01010 01307 01773 01774 01807 01808 01809 01820 |
| AssignmentRule | 13 | 00999 01015 01198 01205 01206 01207 01208 01216 01478 01492 01493 01767 01796 |
| CSymbolDelay | 13 | 00938 00940 00941 00942 00943 01174 01400 01401 01403 01406 01409 01419 01534 |
| RateRule | 12 | 01017 01103 01637 01718 01727 01728 01729 01736 01737 01738 01742 01768 |
| CSymbolRateOf | 5 | 01455 01456 01460 01542 01822 |
| AlgebraicRule | 1 | 01575 |

Total official-reference failures: 107.
_Source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `219c76dac38655c0f15a12ee294e4a4ac10d02ef`; clusters read from `/tmp/bng3-ssts-20261016` case notes._

#### Curated BioModels — baseline

| Mode | Records | Passed | Unsupported | Unsupported format | Failed | Timed out |
| --- | --- | --- | --- | --- | --- | --- |
| flat | 1096 | 943 | 117 | 11 | 13 | 12 |

Denominators: 1096 inventory records; 1083 records reach the SBML path; 1075 declare SBML; 10 are archives.
_Source: `/tmp/bng3-campaign/biomodels-baseline.json` (SHA-256 `47ce9deb3507d5cae24fd33c735f22651e83e980aecee14cadc0dc8f6773df65`); mode `flat`._

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
| harness | 558 | a **measurement** limitation: the model converts and runs, but the gate cannot evaluate it (439 scheduled actions, 100 stochastic ensembles, 19 result mappings) |
| Atomizer | 286 | a **representational** limitation: the model uses a construct BNGL cannot say (95 at the official-reference stage — 35 fast reactions, 28 untranslated events, 16 empty MathML, 9 delay, … — and 191 at the conversion stage) |
| not applicable | 34 | the case defines no official time-course reference |

A harness-side gap is a statement about the *measurement*, not about the
model: the official suite exercises a construct BNG3 can represent and the
gate is what cannot yet evaluate it. An Atomizer-side gap is a statement
about the *representation*: the model uses something BNGL cannot say. The
first kind is the campaign's remaining instrumentation work, the second is
its remaining coverage work, and they need different fixes.

_Source: the measurement of `main` in the generated current tables above
(878 gaps in all: 191 at the conversion stage and 687 at the
official-reference stage)._

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

5. **MathML built-ins folded in the static evaluator, and a signed
   stoichiometry carried** (PR #335). The static evaluator now folds the
   built-in MathML functions and their arguments instead of emitting them
   verbatim, and a rate-ruled species reference whose stoichiometry is
   signed carries that sign. The 95 `dropped` diagnostics it removed were
   each a *false* refusal, so the cases they blocked are now `passed`
   rather than `unsupported`: eight official cases move forward, and the
   official-reference residual falls from 18 to 17.

6. **The SBML `fast` attribute is part of the model's definition, not a solver
   hint** (PR #354). SBML Level 2 and Level 3 Version 1 Sec. 4.11 do not
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
   01569 01571 01572) and 5 stay `unsupported` with a construct-naming
   reason: a rate constant an event or a rule sets (00987 00988 01568
   01570), a stoichiometry an event changes (01398), and a `delay` of the
   converted species (01539).

The combined effect of all nine changes is recorded in the integrated
result below.

## Workstreams

| ID | Cluster | Owner | State |
| --- | --- | --- | --- |
| A | Initial-value resolution order | agent A | PR #316 (review pending) |
| — | `csymbol` semantics + static parameter initial assignments | coordinator | PR #318 (review pending) |
| H | Amount-based rate laws / extent-rate volume factor | coordinator | PR #319 (review pending) |
| — | n-ary MathML relations | coordinator | PR #320 (review pending) |
| — | Baseline inventory and campaign record | coordinator | PR #317 (review pending) |
| B | Over-conservative diagnostics (MathML reciprocals, `fast`) | agent B | partial work in `/tmp/bng3-campaign/wt-atomizer-diagnostics` |
| C | Empty MathML / reactions without a kinetic law | agent C | partial work in `/tmp/bng3-campaign/wt-atomizer-empty-math` |
| D | Harness: scheduled actions + stochastic ensembles + reaction extents | agent D | **not started — highest remaining leverage** |
| E | `delay` / `rateOf` in the C++ SBML writer | agent E | PR #324 (merged) |
| F | State-dependent SBML event triggers | agent F | not started |
| G | Structural atomization (molecular identity, sites, uncertainty) | agent G | partial work in `/tmp/bng3-campaign/wt-atomizer-structure` |
| I | Assignment rules whose target is a parameter | agent I | not started |
| J | Time-dependent stoichiometry (rate-ruled `speciesReference`) | agent J | PR #323 (merged) |
| — | Independent review of each implementation PR | separate reviewer | required before merge |
| — | The SBML `fast` reaction's pseudo steady state | agent AA | PR #354 (review pending) |

## Merged result (2026-10-20)

The campaign's pull requests merge into `main` one at a time and the tree
advances with each merge, so **every number in this section is a moving
target**. The tables below are regenerated from a harness report by
`scripts/ci/sbml_campaign_tables.py`; they are never maintained by hand, and
each one names the report it came from, that report's SHA-256, and the BNG3
commit it measured. The figures they currently carry are **conversion
1732 passed / 191
unsupported / 0 failed / 0
timeout** and **official reference 1225 passed /
687 unsupported / 11 failed
/ 0 timeout**, from the report
`/tmp/bng3-campaign/current-main-2026-10-20b.json` (SHA-256 `3aee9d9012bb137bbb1e007ecf9e254ed64e8b2c972c5d1d2b03ceb1e0015b4c`), which measured the BNG3 commit `c7550723b7ccc3a2cc3c2992e791fa922b118504`.

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
| #330 | A batched SSA sweep that checks the stochastic consistency of converted models | — (verification) | `48315b95` |
| #331 | The pooled SBML conformance gate: one worker pool instead of a process per case | — (measurement speed) | `5c9ec354` |
| #332 | The SBML conformance expectation manifest and the table generator | — (measurement) | `6c61d59f` |
| #335 | The static evaluator's MathML built-ins and a signed stoichiometry | 1 `failed → passed` (`semantic/00879`) | `cee96c9a` |
| #338 | Classify an unparsable changed file as needing a newer interpreter | — (CI only) | `c0190fb2` |
| #339 | Structural inference on the `atomize=True` path | — (the flat measurement path is byte identical) | `d1d0c1c7` |
| #340 | The curated BioModels inventory and the two Atomizer defects it exposed | — (corpus) | `5c9d8e1e` |
| #345 | The expectation-manifest gate and the manifest re-measured on current main | — (measurement) | `f2cb2acc` |
| #346 | The public helper's MathML built-ins from the shared table | — (no behaviour change) | `57736a19` |
| #347 | The parser's `package:fbc` diagnostic in the flux guards | — (diagnostic) | `eafd6deb` |
| #348 | A reaction's rate guarded on the sign of its derivative | — (diagnostic) | `89f19428` |
| #353 | A species concentration rate rule in an event-driven compartment | 2 `failed → passed` (`semantic/01505`, `semantic/01506`) | `c7550723` |

The "Official cases moved" column is measured per branch, so the numbers
overlap where one change enables another; it is a historical per-branch record
and not part of the generated region.

The generated tables below give the measured before/after state of every
stage, the exact cases that changed verdict, and the cases that regressed.
They also cover the changes whose effect is not broken out per branch above.

### The campaign's invariant, audited

The independent audit of the merged set confirms the campaign's central
invariant: **no case became `passed` because a diagnostic was removed, a
tolerance was widened, a reference file was edited, or a comparison was
skipped.** Of the 98 cases whose verdict moved, 88 changed nothing but the
trajectory and 9 more became genuinely representable, each verified against an
independent libRoadRunner reproduction of the official reference. No
tolerance, reference file, mapping or comparison changed anywhere.

The audit's detail is the specific evidence that no case passed because the
comparison had become lenient: of the 88 `failed → passed` changes, **87 were
qualitative** — beyond 100× the official tolerance before the change — and
**one was numeric**, and **no moved case was already within tolerance before
the change**.

_Source: the independent campaign audit, recorded in
`provenance/sbml-campaign/audit-2026-10-20.json` (PR #349)._

<!-- BEGIN GENERATED: sbml-campaign-current -->

#### Official SBML Test Suite — current stage results

| Stage | Passed | Unsupported | Failed | Not tested |
| --- | --- | --- | --- | --- |
| Conversion (SBML → BNGL) | 1797 | 126 | 0 | 0 |
| Round-trip structure | 1797 | 0 | 0 | 126 |
| Independent libRoadRunner comparison | 1797 | 0 | 0 | 126 |
| Official reference comparison | 1758 | 165 | 0 | 0 |
_Source: `/tmp/bng3-campaign/coordinator/f3.json` (SHA-256 `e82db1729153b592a95b4ea91fb9b025a4e44d88a7c129da1ecb3269acf7e576`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `5d8e78b061337874d5a575a3987bde630bfe54d7`; a timed-out case is recorded as failed and an unevaluated stage as not tested._

#### Official-reference unsupported verdicts, by owner

| Count | Owner | Blocking reason |
| --- | --- | --- |
| 71 | Atomizer | state-dependent / non-constant SBML events untranslated |
| 34 | not applicable | case does not define an official time-course reference |
| 22 | harness mapping | no exact BNG3 result mapping for: <reaction id> |
| 18 | Atomizer | other Atomizer-side limitation |
| 9 | C++ writer | SBML math function "…" is not losslessly representable in the C++ SBML writer |
| 6 | Atomizer diagnostic | Reaction "…" is marked fast (fast="true") |
| 3 | Atomizer | <infinity>/<notanumber> constant encountered in math |
| 2 | Atomizer | a compartment declares unsupported spatialDimensions |

Total official-reference unsupported verdicts: 165.
_Source: `/tmp/bng3-campaign/coordinator/f3.json` (SHA-256 `e82db1729153b592a95b4ea91fb9b025a4e44d88a7c129da1ecb3269acf7e576`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `5d8e78b061337874d5a575a3987bde630bfe54d7`._

#### Remaining official-reference failures, by official feature

| Cluster | n | Cases |
| --- | --- | --- |

Total official-reference failures: 0.
_Source: `/tmp/bng3-campaign/coordinator/f3.json` (SHA-256 `e82db1729153b592a95b4ea91fb9b025a4e44d88a7c129da1ecb3269acf7e576`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit the run executed `5d8e78b061337874d5a575a3987bde630bfe54d7`; clusters read from `/tmp/bng3-ssts-20261016` case notes._

#### Curated BioModels — current

| Mode | Records | Passed | Unsupported | Unsupported format | Failed | Timed out |
| --- | --- | --- | --- | --- | --- | --- |
| flat | 1096 | 943 | 117 | 11 | 13 | 12 |

Denominators: 1096 inventory records; 1083 records reach the SBML path; 1075 declare SBML; 10 are archives.
_Source: `/tmp/bng3-campaign/biomodels-main-flat.json` (SHA-256 `0e0583d1f568892085b1c3fe07902da92df508cfbab1a7983be27f3325aa25ba`); mode `flat`._

#### Stage verdict changes, baseline to current

| Stage | Before | After | Cases |
| --- | --- | --- | --- |
| conversion | passed | unsupported | 5 |
| conversion | unsupported | passed | 90 |
| independent_comparison | not_tested | passed | 90 |
| independent_comparison | passed | not_tested | 5 |
| official_reference | failed | passed | 105 |
| official_reference | failed | unsupported | 2 |
| official_reference | passed | unsupported | 1 |
| official_reference | unsupported | passed | 539 |
| roundtrip_structure | not_tested | passed | 90 |
| roundtrip_structure | passed | not_tested | 5 |

Cases with at least one stage change: 649.

Regressions (a stage that was `passed` and no longer is):

- `semantic/00951` [conversion]: passed → unsupported
- `semantic/00951` [roundtrip_structure]: passed → not_tested
- `semantic/00951` [independent_comparison]: passed → not_tested
- `semantic/01169` [conversion]: passed → unsupported
- `semantic/01169` [roundtrip_structure]: passed → not_tested
- `semantic/01169` [independent_comparison]: passed → not_tested
- `semantic/01466` [conversion]: passed → unsupported
- `semantic/01466` [roundtrip_structure]: passed → not_tested
- `semantic/01466` [independent_comparison]: passed → not_tested
- `semantic/01575` [conversion]: passed → unsupported
- `semantic/01575` [roundtrip_structure]: passed → not_tested
- `semantic/01575` [independent_comparison]: passed → not_tested
- `semantic/01576` [conversion]: passed → unsupported
- `semantic/01576` [roundtrip_structure]: passed → not_tested
- `semantic/01576` [independent_comparison]: passed → not_tested
- `semantic/01576` [official_reference]: passed → unsupported

A stage that becomes `passed` is accepted only when the expectation manifest is explicitly updated.

Baseline source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); current source: `/tmp/bng3-campaign/coordinator/f3.json` (SHA-256 `e82db1729153b592a95b4ea91fb9b025a4e44d88a7c129da1ecb3269acf7e576`).

<!-- END GENERATED: sbml-campaign-current -->

The generated comparison above lists every case whose verdict changed, the
stage it changed at, and every case that regressed. A stage that stops being
`passed` is a regression: the run then delivers less than the expectation
manifest records, and the manifest must be updated before the change is
accepted.

The curated-BioModels row in the generated table is an **aggregate**, and an
aggregate hid two reproducible regressions: `BIOMD0000000638` and
`BIOMD0000000954` both changed behaviour while the corpus-wide counts stayed
the same. The two were found by the corpus inventory (PR #340) and are fixed
there. The claim and the correction belong together: the aggregate number
was never evidence that nothing changed, and the corpus is now inventoried
per record so that it cannot be again.

## Python test suite

<!-- BEGIN GENERATED: sbml-campaign-python -->

#### Result

| Suite | Passed | Skipped | Xfailed | Failed |
| --- | --- | --- | --- | --- |
| tests/python | 1572 | 28 | 2 | 1 |

Source: `/tmp/bng3-campaign/pytest-current.xml` (SHA-256 `3da9b66de4abf957a25843ad0ddcd9344ef12cfa2cabfac726509c1adcd5be8e`).

<!-- END GENERATED: sbml-campaign-python -->

The one failure (`test_generated_notebooks_execute_in_qualified_kernel`) also
fails on the unmodified base commit.

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
  was a formatting-only defect: the agents' Python was not formatted with the
  repository's pinned `black==26.10.0`. The same formatting-only change was
  landed on `main` afterwards, in PR #325 (commit `b3de638e`, merged as
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

A repair of the CVODE cleanup leak is in flight: a scope-guarded lifetime for
`cvode_mem`, `y` and `sunctx`, with the expectation that the `C++ ASan
(Ubuntu)` job turns green on every pull request afterwards. It has not
landed in this tree, so no outcome is claimed here; the repair has to show
the LeakSanitizer summary before and after, the full C++ suite count, and an
**empty** SBML per-case diff, because the ODE engine is involved.

The discriminating checks were green at the merged heads. The `Official SBML
references (128 PR cases; full scheduled suite)` job passed on both pull
requests, and the agents' own pinned-suite runs with per-case diffs against
the merged baseline were the primary evidence: #323 ran all 1923 pinned
cases (1823 semantic plus 100 stochastic) and moved 14 cases `failed →
passed` with 0 regressions; #324 ran the 1823 semantic cases and moved 7
cases `failed → passed` with 0 regressions. The independent subagent reviews
of #323 and #324 were still outstanding at merge time and are being completed
after the fact.

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
    "measurement_date": "2026-10-20"
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
    "conversion": {"passed": 1731, "unsupported": 192},
    "roundtrip_structure": {"not_tested": 192, "passed": 1731},
    "independent_comparison": {"not_tested": 192, "passed": 1731},
    "official_reference": {"failed": 17, "passed": 1220, "unsupported": 686}
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
  --json /tmp/bng3-campaign/report.json

# 2. Regenerate the manifest from that report.
python scripts/ci/sbml_campaign_inventory.py \
  --suite-report /tmp/bng3-campaign/report.json \
  --expectations-out provenance/sbml-campaign/expectations.json \
  --measurement-date "$(date -u +%Y-%m-%d)" \
  --measured-commit "$(git rev-parse HEAD)" \
  --expectations-provenance provenance/sbml-campaign/provenance-current-2026-10-20.json
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
  --suite-report /tmp/bng3-campaign/report.json \
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

```bash
python scripts/ci/sbml_campaign_tables.py \
  --baseline-suite-report /tmp/bng3-campaign/baseline-ssts.json \
  --suite-report /tmp/bng3-campaign/current-main-2026-10-20b.json \
  --baseline-biomodels-report /tmp/bng3-campaign/biomodels-baseline.json \
  --biomodels-report /tmp/bng3-campaign/biomodels-main-flat.json \
  --suite-dir /path/to/sbml-test-suite \
  --pytest-junit /tmp/bng3-campaign/pytest-cee96c9a.xml \
  --measured-commit "$(git rev-parse main)" \
  --doc docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md
```

The Python-suite row is read from a pytest JUnit report:

```bash
PYTHONPATH=python:build/cpp python -m pytest -q tests/python \
  --junitxml=/tmp/bng3-campaign/pytest-cee96c9a.xml
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
  --baseline-suite-report /tmp/bng3-campaign/baseline-ssts.json \
  --suite-report /tmp/bng3-campaign/current-main-2026-10-20b.json \
  --baseline-biomodels-report /tmp/bng3-campaign/biomodels-baseline.json \
  --biomodels-report /tmp/bng3-campaign/biomodels-main-flat.json \
  --suite-dir /path/to/sbml-test-suite \
  --pytest-junit /tmp/bng3-campaign/pytest-cee96c9a.xml \
  --measured-commit "$(git rev-parse main)" \
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
  --suite-report /tmp/bng3-campaign/report.json \
  --previous-suite-report /tmp/bng3-campaign/previous.json \
  --biomodels-report /tmp/bng3-campaign/biomodels.json \
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
  --suite-report /tmp/bng3-campaign/report.json --json /tmp/bng3-campaign/status.json
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
