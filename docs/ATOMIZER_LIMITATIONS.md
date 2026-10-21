<!-- BEGIN GENERATED: atomizer-limitations -->

# BNG3 SBML Atomizer limitations

This is the scope record of BNG3's SBML Atomizer: what it does not support, what the specification requires in those cases, what BNG3 does instead, and whether each boundary is reducible. It is generated from the campaign's expectation manifest, so it cannot drift away from the measurement it describes.

A limitation is **not** a defect. It is a case the Atomizer refuses, and a refusal is the honest outcome for a construct BNG3 cannot represent exactly. Defects are the other class: a case that BNG3 converts and then gets wrong. Those are tracked in the conformance findings backlog, not here.

## Header

| Field | Value |
| --- | --- |
| Generated on | 2026-10-21 |
| Tree described | `5d8e78b061337874d5a575a3987bde630bfe54d7` |
| Measured at commit | `5d8e78b061337874d5a575a3987bde630bfe54d7` |
| Official suite revision | `cf38585fac5de8e0e90112febb62851ee2181816` (https://github.com/sbmlteam/sbml-test-suite.git) |
| Report SHA-256 | `e82db1729153b592a95b4ea91fb9b025a4e44d88a7c129da1ecb3269acf7e576` |
| BNG3 version | 3.0.0a1 |
| Native extension SHA-256 | `6f82e81131d2a33cb48049ffab080d5f04b0003cfffdc3d56ca758f0812ec5c1` |
| Source tree of the measurement | `/private/tmp/bng3-campaign/wt-f2/python/bionetgen/__init__.py` |

The measurement is a full run of the pinned official SBML Test Suite; its per-case verdicts are recorded in the expectation manifest, which the campaign regenerates whenever a merge changes a verdict.

## How to read this document

A case's official reference ends in exactly one of three states, and the difference is the whole point:

| State | What it means |
| --- | --- |
| passed | the case was compared against the official reference and the two agree |
| failed | the case was compared and the two **disagree** — a defect, not a limitation |
| unsupported | the case was **not compared**: the Atomizer refused it, or the comparison could not be made |

So a *limitation* is a case the Atomizer refuses, and it is a scope boundary rather than a defect. The manifest records which side of the boundary each refusal sits on, and the two sides are different kinds of work:

| Side | What it means | What it asks for |
| --- | --- | --- |
| `atomizer` | a construct is not representable today; the case is refused | extending the Atomizer's semantics, or a documented boundary that will not move |
| `harness` | the model may be perfectly good, but the comparison could not be made | a better measurement — these are the **reducible** ones, and they are kept in their own section so that a measurement limit is never mistaken for a limitation of the Atomizer |
| `not-applicable` | the official suite itself says the case defines no time-course reference | nothing: there is no comparison to make and nobody should go looking for a fix |

Every limitation below carries the date it was recorded. A limitation that is closed does not vanish: it moves to [Resolved limitations](#resolved-limitations) with the date it was closed.

## Summary

| Construct | Side | Cases | What it is | First recorded |
| --- | --- | --- | --- | --- |
| `events:untranslated` | atomizer | 68 | An event the Atomizer cannot lower, or cannot order | 2026-10-20 |
| `package:fbc` | atomizer | 34 | The fbc package: a flux-balance model, not a time course | 2026-10-20 |
| `sbml-writer:unrepresentable-function` | atomizer | 9 | A math function the engine cannot execute | 2026-10-20 |
| `fast-reaction:no-fast-equilibrium-solve` | atomizer | 5 | A fast reaction whose pseudo steady state cannot be used | 2026-10-20 |
| `events:state-trigger-not-schedulable` | atomizer | 4 | A state trigger the runtime cannot schedule | 2026-10-20 |
| `other` | atomizer | 3 | Refusals the cause taxonomy does not yet name | 2026-10-20 |
| `compartment:unsupported-spatial-dimensions` | atomizer | 2 | A compartment with more than three spatial dimensions | 2026-10-20 |
| `mathml:infinity` | atomizer | 2 | An infinite constant | 2026-10-20 |
| `mathml:not-a-number` | atomizer | 1 | A not-a-number constant | 2026-10-20 |
| `reference:no-result-mapping` | harness | 22 | The official reference names a quantity BNG3 cannot observe | 2026-10-20 |
| `harness:random-event-execution` | harness | 12 | The official reference is one draw of a random execution order | 2026-10-21 |
| `harness:reference-does-not-track-variable` | harness | 3 | The official reference does not report a boundary species | 2026-10-21 |
| `reference:not-applicable` | not-applicable | 34 | The suite says the case has no official time-course reference | 2026-10-20 |

Cases with a recorded gap: 128 atomizer-side, 37 harness-side, 34 not-applicable-side. A case may carry a gap at more than one stage, so the counts above count distinct cases per construct.

## The Atomizer's limitations

These are the constructs BNG3's SBML Atomizer cannot represent exactly today. Each one is refused explicitly, and the refusal names the condition.

### An event the Atomizer cannot lower, or cannot order

- **Construct**: `events:untranslated`
- **Cases**: 68 — semantic/00761 semantic/00965 semantic/00966 semantic/01000 semantic/01169 semantic/01590 stochastic/00033 stochastic/00040 stochastic/00041 stochastic/00042 stochastic/00043 stochastic/00044 stochastic/00045 stochastic/00046 stochastic/00047 stochastic/00048 stochastic/00049 stochastic/00050 stochastic/00051 stochastic/00052 stochastic/00053 stochastic/00054 stochastic/00055 stochastic/00056 … (44 more)
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.12 defines an Event as a two-phase operation: a Trigger (Sec. 4.12.2) decides when the event may fire, and the execution phase applies the EventAssignments (Sec. 4.12.5). Sec. 4.12.7 says the order in which events occur is resolved, that this order can be significant for a simulation's outcome, and that an event may carry a special priority through a Priority subobject (Sec. 4.12.3).
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12, Sec. 4.12.2, Sec. 4.12.3, Sec. 4.12.7
- **What BNG3 does instead**: The Atomizer lowers an event whose trigger is a constant time threshold to a scheduled BNGL action and refuses the rest: it reports "N SBML event(s) parsed; M fixed-time event(s) lowered to scheduled actions, while K state-dependent or non-constant event(s) remain untranslated", and the case is not claimed to be supported. The refusal names the specific condition, for example "state-triggered SBML events require stochastic jump scheduling", "the model's algebraic rule is not applied, so the event's trigger cannot be evaluated", "volume change can cause the state trigger to re-enter within the simulation horizon" or "trigger time ... does not reduce to a constant".
- **Reducible?**: Partly reduced, and the work is continuing. A state trigger the native event runtime can evaluate is now lowered (PR #328, 2026-10-21) and several simultaneous events execute in the order the specification defines (PR #371, 2026-10-21). What remains needs a trigger value the engine does not poll, a trigger whose value depends on a construct the Atomizer does not apply, or an event whose effect is not a scheduled action.

### The fbc package: a flux-balance model, not a time course

- **Construct**: `package:fbc`
- **Cases**: 34 — semantic/01186 semantic/01187 semantic/01188 semantic/01189 semantic/01190 semantic/01191 semantic/01192 semantic/01193 semantic/01194 semantic/01195 semantic/01196 semantic/01606 semantic/01607 semantic/01608 semantic/01609 semantic/01610 semantic/01611 semantic/01612 semantic/01613 semantic/01614 semantic/01615 semantic/01616 semantic/01617 semantic/01618 … (10 more)
- **First recorded**: 2026-10-20
- **What SBML requires**: The SBML Level 3 Package for Flux Balance Constraints (FBC) adds goals and constraints to a model. A model that carries FBC elements is a constraint-based model, not a kinetic time course, so the Core's reaction semantics (Sec. 4.11.7) and event semantics (Sec. 4.12.7) do not give it a trajectory to compare.
- **Citation**: SBML Level 3 Package for Flux Balance Constraints (FBC) Version 1 Release 3; the Core itself is SBML Level 3 Version 2 Core Sec. 4.11.7 and Sec. 4.12.7
- **What BNG3 does instead**: The Atomizer reports that the package is declared and that the affected structure is missing from the converted model, and it says why the model is out of scope: "This is a constraint-based flux-balance model, not a kinetic time-course model."
- **Reducible?**: No, not as a time course. BNG3 has no flux-balance solver, so a flux-balance model is not convertible; the honest boundary is to refuse it and to say that it is a different kind of model.

### A math function the engine cannot execute

- **Construct**: `sbml-writer:unrepresentable-function`
- **Cases**: 9 — semantic/00985 semantic/01142 semantic/01410 semantic/01411 semantic/01412 semantic/01480 semantic/01481 semantic/01535 semantic/01593
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 3.4 defines the delay and rateOf operators as csymbol elements with a fixed definitionURL, and requires a reader to give delay(x, d) the value x had at time t - d.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.4
- **What BNG3 does instead**: The C++ SBML writer serializes the call back out, but the engine cannot execute it: it reports "SBML math function \"delay\" is not losslessly representable in the BNG3 engine/libRoadRunner path: the C++ SBML writer serializes the call, but neither the BNG3 engine nor libRoadRunner can evaluate SBML delay semantics".
- **Reducible?**: No, not in the engine. BNG3 has no delayed-history semantics and libRoadRunner rejects a model that uses delay at all, so a model that needs them cannot be executed by either engine; the writer boundary itself was already removed.

### A fast reaction whose pseudo steady state cannot be used

- **Construct**: `fast-reaction:no-fast-equilibrium-solve`
- **Cases**: 5 — semantic/00987 semantic/01398 semantic/01539 semantic/01568 semantic/01570
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 1 Core Sec. 4.11 asks that software tools use a pseudo steady-state approximation for the set of reactions whose fast attribute is true. SBML Level 3 Version 2 removed the fast attribute (Sec. 4.11), so a Level 3 Version 2 model says nothing about fast reactions.
- **Citation**: SBML Level 3 Version 1 Core Sec. 4.11; SBML Level 3 Version 2 Core Sec. 4.11
- **What BNG3 does instead**: The Atomizer reduces a fast reaction to its pseudo steady state where it can (PR #370, 2026-10-21) and refuses the remainder, saying that it treats such a reaction as an ordinary reaction and that this changes the trajectory.
- **Reducible?**: Largely reduced already: the reduction closed most of these cases. The remainder needs a fast reaction whose pseudo steady state cannot be written as a BNGL rule.

### A state trigger the runtime cannot schedule

- **Construct**: `events:state-trigger-not-schedulable`
- **Cases**: 4 — semantic/00988 semantic/01466 semantic/01575 semantic/01576
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.12.2 requires the Trigger to be evaluated against the model's current state, and Sec. 4.12.7 requires the event to be executed when the trigger becomes true.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12.2, Sec. 4.12.7
- **What BNG3 does instead**: The Atomizer refuses the event and says why: "trigger is not a simple time threshold (state-dependent triggers cannot be scheduled)", or, when the trigger names an identifier that is not a legal SBML SId, that the identifier "contains a character outside the SBML SId class and cannot be matched".
- **Reducible?**: Yes, in two directions. A trigger the native event runtime can evaluate is lowered rather than refused (PR #328, 2026-10-21); an identifier that is not a legal SId is a source defect the user can fix by renaming it, and the diagnostic says so.

### Refusals the cause taxonomy does not yet name

- **Construct**: `other`
- **Cases**: 3 — semantic/00951 stochastic/00028 stochastic/00032
- **First recorded**: 2026-10-20
- **What SBML requires**: No single construct: each case is refused for a reason the campaign's cause taxonomy has no label for yet.
- **Citation**: SBML Level 3 Version 2 Core, the section the case's own reason names
- **What BNG3 does instead**: The Atomizer refuses the case and reports the reason; the campaign's classification records it as "other" because no known construct class matches.
- **Reducible?**: Unknown until each reason is read. This bucket is a request to extend the taxonomy, not a claim that the cases are alike.

### A compartment with more than three spatial dimensions

- **Construct**: `compartment:unsupported-spatial-dimensions`
- **Cases**: 2 — semantic/01133 semantic/01197
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.5.2 lets a compartment declare any floating-point spatialDimensions value, and Sec. 4.5.4 uses that value to choose between the model's volumeUnits, areaUnits and lengthUnits.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.5.2, Sec. 4.5.4
- **What BNG3 does instead**: The Atomizer refuses the compartment and says why: "Compartment \"C\" has spatialDimensions 7; BNG3 does not support spatialDimensions values greater than 3." It also refuses a negative dimension and, for a Level 2 model, any value outside 0 through 3.
- **Reducible?**: No, not as a compartment. BNGL compartments carry a volume; a compartment with a fractal or higher dimension has no BNGL counterpart, and the unit selection Sec. 4.5.4 describes cannot be expressed.

### An infinite constant

- **Construct**: `mathml:infinity`
- **Cases**: 2 — semantic/00950 semantic/01811
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 3.4 permits the MathML infinity constant in a model's formulas, and Sec. 3.1 makes positive infinity a value of the double type.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.1, Sec. 3.4
- **What BNG3 does instead**: The Atomizer reports "<infinity> constant encountered in math; the source is valid SBML (validation rule 10202 permits <infinity>), but an infinite value cannot be represented in BNG3's finite-double model, so it is emitted as a large finite value and the model is not claimed to be supported".
- **Reducible?**: Only by changing what BNG3's value domain is. The source is valid SBML and the boundary is BNG3's finite-double model, not a conversion defect; a large finite stand-in is an approximation, so the case is refused rather than claimed.

### A not-a-number constant

- **Construct**: `mathml:not-a-number`
- **Cases**: 1 — semantic/01813
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 3.4 permits the MathML notanumber constant in a model's formulas, and Sec. 3.1 makes not-a-number a value of the double type.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.1, Sec. 3.4
- **What BNG3 does instead**: The Atomizer reports "<notanumber> constant encountered in math; the source is valid SBML (validation rule 10202 permits <notanumber>), but a not-a-number value cannot be represented in BNG3's finite-double model, so the model is not claimed to be supported".
- **Reducible?**: Only by changing BNG3's value domain. There is no finite value that stands for not-a-number, so no approximation is offered.

## The harness's measurement limits

**These are measurement limits, not limitations of the Atomizer.** The model converts and nothing is refused; the comparison against the official reference simply could not be made. They are the reducible ones, and they are kept apart so that a reader does not mistake a measurement limit for something BNG3 cannot do.

### The official reference names a quantity BNG3 cannot observe

- **Construct**: `reference:no-result-mapping`
- **Cases**: 22 — semantic/01344 semantic/01345 semantic/01346 semantic/01347 semantic/01348 semantic/01349 semantic/01350 semantic/01351 semantic/01352 semantic/01360 semantic/01369 semantic/01378 semantic/01380 semantic/01381 semantic/01382 semantic/01383 semantic/01384 semantic/01385 semantic/01386 semantic/01387 semantic/01388 semantic/01389
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.11.8 says the id of a Reaction may be used in a MathML formula and then represents that reaction's rate. The official SBML Test Suite's results file for such a case reports that rate as the quantity to compare.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.11.8
- **What BNG3 does instead**: Nothing is refused: the model converts. The harness cannot map the reference's quantity onto a BNG3 observable and reports "no exact BNG3 result mapping for: <reaction id>".
- **Reducible?**: Yes, on the measurement side. BNGL has no observable for a reaction's rate, so the reference's quantity has to be mapped onto something BNG3 produces, or the reference has to name something it does. It is a measurement limit, not a limitation of the Atomizer.

### The official reference is one draw of a random execution order

- **Construct**: `harness:random-event-execution`
- **Cases**: 12 — semantic/00952 semantic/00953 semantic/00962 semantic/00964 semantic/01588 semantic/01589 semantic/01591 semantic/01592 semantic/01599 semantic/01605 semantic/01626 semantic/01627
- **First recorded**: 2026-10-21
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.12.3 and Sec. 4.12.7 define the order in which simultaneously triggered events are executed; a case that draws the events in a random order is a valid instance of that semantics.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12.3, Sec. 4.12.7
- **What BNG3 does instead**: Nothing is refused: the model converts and the engine executes the events in the order the specification defines. The harness cannot compare point-wise, because the reference is one draw of a random order and no deterministic simulator reproduces it point-wise.
- **Reducible?**: Yes, on the measurement side: the comparison has to be distributional rather than point-wise, or the reference has to pin the order. It is a measurement limit, not a limitation of the Atomizer.

### The official reference does not report a boundary species

- **Construct**: `harness:reference-does-not-track-variable`
- **Cases**: 3 — stochastic/00006 stochastic/00024 stochastic/00026
- **First recorded**: 2026-10-21
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.6.5 lets a species carry the boundaryCondition attribute, in which case the species is a boundary rather than an integrated quantity.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.6.5
- **What BNG3 does instead**: Nothing is refused: the model converts and the boundary species is set. The harness cannot compare, because the reference reports the boundary species as identically zero while BNG3's value follows the model's boundary definition.
- **Reducible?**: Yes, on the measurement side: the comparison has to exclude a quantity the two engines define differently, or the reference has to report it. It is a measurement limit, not a limitation of the Atomizer.

## Cases the official suite says do not apply

The official suite itself records that these cases define no time-course reference, so there is nothing to compare against. This is not a limitation of the Atomizer and not a defect; nobody should go looking for a fix.

### The suite says the case has no official time-course reference

- **Construct**: `reference:not-applicable`
- **Cases**: 34 — semantic/01186 semantic/01187 semantic/01188 semantic/01189 semantic/01190 semantic/01191 semantic/01192 semantic/01193 semantic/01194 semantic/01195 semantic/01196 semantic/01606 semantic/01607 semantic/01608 semantic/01609 semantic/01610 semantic/01611 semantic/01612 semantic/01613 semantic/01614 semantic/01615 semantic/01616 semantic/01617 semantic/01618 … (10 more)
- **First recorded**: 2026-10-20
- **What SBML requires**: Nothing in the Core applies: the official suite itself records that the case defines no official time-course reference, so there is nothing to compare against.
- **Citation**: the official SBML Test Suite's own case notes; no Core section applies
- **What BNG3 does instead**: Nothing is refused and nothing is claimed. The case is recorded as having no official reference, which is not a limitation of the Atomizer and not a defect.
- **Reducible?**: Not applicable. The official suite defines no reference for these cases, so there is no comparison to make and no work to do.

## Resolved limitations

A limitation that is closed does not vanish from the record. This section names the constructs the campaign no longer refuses, and when it stopped refusing them. The "no longer exercised" entries are different: the Atomizer still refuses that construct, but the official suite no longer reaches the refusal.

| Construct | What it is | Status | Date | What happened |
| --- | --- | --- | --- | --- |
| `harness:scheduled-actions-not-executed` | The reference runner could not execute a model with actions | closed | 2026-10-21 | Closed by PR #337, validated 2026-10-20: the harness now validates official references for action-bearing cases, so these cases are compared rather than skipped. First measured as closed on 2026-10-21. |
| `harness:stochastic-ensemble-not-evaluated` | The official reference needed an ensemble the harness did not run | closed | 2026-10-21 | Closed by PR #337, validated 2026-10-20: the harness now evaluates the official stochastic references, so these cases are compared rather than skipped. First measured as closed on 2026-10-21. |
| `rules:algebraic-not-applied` | An algebraic rule is not applied | not-exercised | 2026-10-20 | The refusal still exists in the Atomizer; the official suite no longer reaches it, because the campaign resolved the suite's algebraic-rule cases by carrying the rule as an assignment (PR #355, 2026-10-20). The general implicit-DAE boundary is still open, so the construct is recorded as no longer exercised rather than closed. |
| `stoichiometry:assigned-stoichiometry-unresolved` | An assigned stoichiometry that could not be resolved | not-exercised | 2026-10-20 | The refusal still exists in the Atomizer; the official suite no longer reaches it, because the campaign resolved the suite's cases by carrying the assigned value through the parameter's state (PR #366, 2026-10-21). A symbol that still cannot be resolved at initialization remains refused. |
| `stoichiometry:unsupported` | A reaction with a stoichiometry BNGL cannot express | not-exercised | 2026-10-20 | The refusal still exists in the Atomizer; the official suite no longer reaches it. The boundary is only reducible by extending BNGL's reaction semantics: a negative or fractional stoichiometry has no BNGL counterpart, and substituting a rounded count would change the chemistry. |

## What changed

The expectation manifest records one measurement, not a history, so this log is the one part of the document that is maintained by hand. It is a dated record of the limitations that were opened and closed.

- **2026-10-20** — The campaign's baseline measurement is recorded: 1712 of the 1923 official suite cases convert, 211 are refused, and 107 official-reference comparisons fail.
- **2026-10-20** — The machine-readable expectation manifest is added, so every case's expected verdict at every stage is recorded rather than re-derived by hand.
- **2026-10-20** — Closed: the harness now validates official references for action-bearing and stochastic cases (PR #337), so the harness-side limits 'scheduled actions not executed' and 'stochastic ensemble not evaluated' are gone.
- **2026-10-20** — The suite no longer exercises the algebraic-rule and assigned-stoichiometry refusals: the campaign resolved those cases (PRs #355 and #366). The refusals themselves still exist in the Atomizer.
- **2026-10-21** — Opened: two harness-side classes were named, so the measurement limits 'random event execution' and 'reference does not track variable' are now visible as such instead of being counted as Atomizer limitations (PR #359).
- **2026-10-21** — Reduced: a fast reaction is lowered to its pseudo steady state instead of being refused (PR #370), and several simultaneous events execute in the order the specification defines (PR #371). The official-reference failure count is zero.

## How to regenerate

This document is generated. Do not edit it by hand: the generator overwrites the marked region below, and `--check` fails when the document no longer matches the manifest.

```bash
python scripts/ci/atomizer_limitations.py \
    --manifest provenance/sbml-campaign/expectations.json \
    --narrative provenance/sbml-campaign/atomizer-limitations.json \
    --doc docs/ATOMIZER_LIMITATIONS.md

# verify the document against the manifest
python scripts/ci/atomizer_limitations.py \
    --manifest provenance/sbml-campaign/expectations.json \
    --narrative provenance/sbml-campaign/atomizer-limitations.json \
    --doc docs/ATOMIZER_LIMITATIONS.md --check
```

The counts, the case ids and the side of every boundary come from the expectation manifest. The narrative — what the specification requires, what BNG3 does instead, whether the boundary is reducible, and the dates — comes from `provenance/sbml-campaign/atomizer-limitations.json`, which is the one hand-maintained input this document has.

## Related documents

- [SBML Atomizer coverage campaign](SBML_ATOMIZER_COVERAGE_CAMPAIGN.md) — how the coverage numbers were measured and how the campaign changed the Atomizer.
- [SBML conformance findings](SBML_CONFORMANCE_FINDINGS.md) — the **backlog** of open findings. A finding is a case that was compared and got wrong; a limitation is a case that was refused.
- [Curated BioModels corpus](CURATED_BIOMODELS_CORPUS.md) — the record of the published-model corpus.
- [Documentation index](index.md) — the rest of BNG3's documentation.

<!-- END GENERATED: atomizer-limitations -->
