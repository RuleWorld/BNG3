<!-- BEGIN GENERATED: atomizer-limitations -->

# BNG3 SBML Atomizer limitations

This is the scope record of BNG3's SBML Atomizer: what it does not support, what the specification requires in those cases, what BNG3 does instead, and whether each boundary is reducible. It is generated from the campaign's expectation manifest, so it cannot drift away from the measurement it describes.

A limitation is **not** a defect. It is a case the Atomizer refuses, and a refusal is the honest outcome for a construct BNG3 cannot represent exactly. Defects are the other class: a case that BNG3 converts and then gets wrong. Those are tracked in the conformance findings backlog, not here.

## Header

| Field | Value |
| --- | --- |
| Generated on | 2026-10-23 |
| Tree described | `31ae76c19fdd03c9d4af788f58dd5187726e14a1` |
| Measured at commit | `31ae76c19fdd03c9d4af788f58dd5187726e14a1` |
| Official suite revision | `cf38585fac5de8e0e90112febb62851ee2181816` (https://github.com/sbmlteam/sbml-test-suite.git) |
| Report SHA-256 | `49601d78bac943c536e111d575765e3823a808a1af11a66d9f88e83977a8833f` |
| BNG3 version | 3.0.0a1 |
| Native extension SHA-256 | `aa947dc7da940bf24605eda8f22914e16ccfc4efbe7cf04026468843dea78246` |
| Source tree of the measurement | `/home/runner/work/_temp/ssts-venv/lib/python3.12/site-packages/bionetgen/__init__.py` |

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
| `events:untranslated` | atomizer | 57 | An event the Atomizer cannot lower, or cannot order | 2026-10-20 |
| `package:fbc` | atomizer | 34 | The fbc package: a flux-balance model, not a time course | 2026-10-20 |
| `sbml-writer:unrepresentable-function` | atomizer | 9 | A math function the engine cannot execute | 2026-10-20 |
| `mathml:infinity` | atomizer | 8 | An infinite constant | 2026-10-20 |
| `fast-reaction:no-fast-equilibrium-solve` | atomizer | 5 | A fast reaction whose pseudo steady state cannot be used | 2026-10-20 |
| `mathml:non-finite-parameter-approximation` | atomizer | 5 | A non-finite parameter value is replaced by a finite diagnostic placeholder | 2026-10-22 |
| `events:state-trigger-not-schedulable` | atomizer | 4 | A state trigger the runtime cannot schedule | 2026-10-20 |
| `compartment:unsupported-spatial-dimensions` | atomizer | 2 | A compartment with more than three spatial dimensions | 2026-10-20 |
| `mathml:not-a-number` | atomizer | 1 | A not-a-number constant | 2026-10-20 |
| `harness:random-event-execution` | harness | 12 | The official reference is one draw of a random execution order | 2026-10-21 |
| `harness:scheduled-action-phase-boundary` | harness | 2 | The official reference samples a scheduled-action phase boundary | 2026-10-22 |
| `harness:stochastic-ensemble-budget-not-comparable` | harness | 2 | Projected stochastic work exceeds the comparison-planning threshold | 2026-10-22 |
| `reference:not-applicable` | not-applicable | 34 | The suite says the case has no official time-course reference | 2026-10-20 |

Cases with a recorded gap: 125 atomizer-side, 16 harness-side, 34 not-applicable-side. A case may carry a gap at more than one stage, so the counts above count distinct cases per construct.

## The Atomizer's limitations

These are the constructs BNG3's SBML Atomizer cannot represent exactly today. Each one is refused explicitly, and the refusal names the condition.

### An event the Atomizer cannot lower, or cannot order

- **Construct**: `events:untranslated`
- **Cases**: 57 — semantic/00761 semantic/00965 semantic/00966 semantic/01000 semantic/01590 stochastic/00033 stochastic/00040 stochastic/00041 stochastic/00042 stochastic/00043 stochastic/00044 stochastic/00045 stochastic/00046 stochastic/00047 stochastic/00048 stochastic/00049 stochastic/00050 stochastic/00051 stochastic/00052 stochastic/00053 stochastic/00054 stochastic/00055 stochastic/00056 stochastic/00057 … (33 more)
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.12 defines an Event as a two-phase operation: a Trigger (Sec. 4.12.2) decides when the event may fire, and the execution phase applies the EventAssignments (Sec. 4.12.5). Sec. 4.12.7 says the order in which events occur is resolved, that this order can be significant for a simulation's outcome, and that an event may carry a special priority through a Priority subobject (Sec. 4.12.3).
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12, Sec. 4.12.2, Sec. 4.12.3, Sec. 4.12.7
- **What BNG3 does instead**: The Atomizer lowers an event whose trigger is a constant time threshold to a scheduled BNGL action and refuses the rest: it reports "N SBML event(s) parsed; M fixed-time event(s) lowered to scheduled actions, while K state-dependent or non-constant event(s) remain untranslated", and the case is not claimed to be supported. The refusal names the specific condition, for example "state-triggered SBML events require stochastic jump scheduling", "the model's algebraic rule is not applied, so the event's trigger cannot be evaluated", "volume change can cause the state trigger to re-enter within the simulation horizon" or "trigger time ... does not reduce to a constant".
- **Reducible?**: Partly reduced, and the work is continuing. A state trigger the native event runtime can evaluate is now lowered (PR #328, 2026-10-21) and several simultaneous events execute in the order the specification defines (PR #371, 2026-10-21), and a simultaneous group whose priority is read from the model state is now ordered by the priority it has at the execution instant, which SBML L3V2 Core Sec. 4.12.3 requires (PR #376, 2026-10-21). What remains needs a trigger value the engine does not poll, a trigger whose value depends on a construct the Atomizer does not apply, or an event whose effect is not a scheduled action.

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
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 3.4.6 defines the delay and rateOf operators as csymbol elements with a fixed definitionURL, and requires a reader to give delay(x, d) the value x had at time t - d.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.4.6
- **What BNG3 does instead**: The C++ SBML writer serializes the call back out, but the engine cannot execute it: it reports "SBML math function \"delay\" is not losslessly representable in the BNG3 engine/libRoadRunner path: the C++ SBML writer serializes the call, but neither the BNG3 engine nor libRoadRunner can evaluate SBML delay semantics".
- **Reducible?**: No, not in the engine. BNG3 has no delayed-history semantics and libRoadRunner rejects a model that uses delay at all, so a model that needs them cannot be executed by either engine; the writer boundary itself was already removed.

### An infinite constant

- **Construct**: `mathml:infinity`
- **Cases**: 8 — semantic/00950 semantic/01811 stochastic/00069 stochastic/00070 stochastic/00071 stochastic/00072 stochastic/00077 stochastic/00078
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 3.4.1 permits the MathML infinity constant in a model's formulas, and Sec. 3.1.5 makes positive infinity a value of the double type.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.1.5, Sec. 3.4.1
- **What BNG3 does instead**: The Atomizer reports "<infinity> constant encountered in math; the source is valid SBML (validation rule 10202 permits <infinity>), but an infinite value cannot be represented in BNG3's finite-double model, so it is emitted as a large finite value and the model is not claimed to be supported".
- **Reducible?**: Only by changing what BNG3's value domain is. The source is valid SBML and the boundary is BNG3's finite-double model, not a conversion defect; a large finite stand-in is an approximation, so the case is refused rather than claimed.

### A fast reaction whose pseudo steady state cannot be used

- **Construct**: `fast-reaction:no-fast-equilibrium-solve`
- **Cases**: 5 — semantic/00987 semantic/01398 semantic/01539 semantic/01568 semantic/01570
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 1 Core Sec. 4.11 asks that software tools use a pseudo steady-state approximation for the set of reactions whose fast attribute is true. SBML Level 3 Version 2 removed the fast attribute (Sec. 4.11), so a Level 3 Version 2 model says nothing about fast reactions.
- **Citation**: SBML Level 3 Version 1 Core Sec. 4.11; SBML Level 3 Version 2 Core Sec. 4.11
- **What BNG3 does instead**: The Atomizer reduces a fast reaction to its pseudo steady state where it can (PR #370, 2026-10-21) and refuses the remainder, saying that it treats such a reaction as an ordinary reaction and that this changes the trajectory.
- **Reducible?**: Largely reduced already: the reduction closed most of these cases. The remainder needs a fast reaction whose pseudo steady state cannot be written as a BNGL rule.

### A non-finite parameter value is replaced by a finite diagnostic placeholder

- **Construct**: `mathml:non-finite-parameter-approximation`
- **Cases**: 5 — semantic/00951 stochastic/00096 stochastic/00097 stochastic/00098 stochastic/00099
- **First recorded**: 2026-10-22
- **What SBML requires**: The source values use non-finite numeric values, which are distinct from any finite value. A finite-double target cannot preserve them by substituting an arbitrary finite parameter.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.1.4; MathML 2 Sec. 4.2.3
- **What BNG3 does instead**: The case source validates with libSBML, but parameter values include infinity and NaN. The writer emits finite placeholder numbers to produce a diagnostic artifact and marks the conversion unsupported; these placeholders do not preserve the source values.
- **Reducible?**: No within BNG3's finite numeric state; conversion must keep refusing rather than treating the emitted finite placeholder as equivalent.

### A state trigger the runtime cannot schedule

- **Construct**: `events:state-trigger-not-schedulable`
- **Cases**: 4 — semantic/00988 semantic/01466 semantic/01575 semantic/01576
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.12.2 requires the Trigger to be evaluated against the model's current state, and Sec. 4.12.7 requires the event to be executed when the trigger becomes true.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12.2, Sec. 4.12.7
- **What BNG3 does instead**: The Atomizer refuses the event and says why: "trigger is not a simple time threshold (state-dependent triggers cannot be scheduled)", or, when the trigger names an identifier that is not a legal SBML SId, that the identifier "contains a character outside the SBML SId class and cannot be matched".
- **Reducible?**: Yes, in two directions. A trigger the native event runtime can evaluate is lowered rather than refused (PR #328, 2026-10-21); an identifier that is not a legal SId is a source defect the user can fix by renaming it, and the diagnostic says so.

### A compartment with more than three spatial dimensions

- **Construct**: `compartment:unsupported-spatial-dimensions`
- **Cases**: 2 — semantic/01133 semantic/01197
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.5.2 lets a compartment declare any floating-point spatialDimensions value, and Sec. 4.5.4 uses that value to choose between the model's volumeUnits, areaUnits and lengthUnits.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.5.2, Sec. 4.5.4
- **What BNG3 does instead**: The Atomizer refuses the compartment and says why: "Compartment \"C\" has spatialDimensions 7; BNG3 does not support spatialDimensions values greater than 3." It also refuses a negative dimension and, for a Level 2 model, any value outside 0 through 3.
- **Reducible?**: No, not as a compartment. BNGL compartments carry a volume; a compartment with a fractal or higher dimension has no BNGL counterpart, and the unit selection Sec. 4.5.4 describes cannot be expressed.

### A not-a-number constant

- **Construct**: `mathml:not-a-number`
- **Cases**: 1 — semantic/01813
- **First recorded**: 2026-10-20
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 3.4.1 permits the MathML notanumber constant in a model's formulas, and Sec. 3.1.5 makes not-a-number a value of the double type.
- **Citation**: SBML Level 3 Version 2 Core Sec. 3.1.5, Sec. 3.4.1
- **What BNG3 does instead**: The Atomizer reports "<notanumber> constant encountered in math; the source is valid SBML (validation rule 10202 permits <notanumber>), but a not-a-number value cannot be represented in BNG3's finite-double model, so the model is not claimed to be supported".
- **Reducible?**: Only by changing BNG3's value domain. There is no finite value that stands for not-a-number, so no approximation is offered.

## The harness's measurement limits

**These are measurement limits, not limitations of the Atomizer.** The model converts and nothing is refused; the comparison against the official reference simply could not be made. They are the reducible ones, and they are kept apart so that a reader does not mistake a measurement limit for something BNG3 cannot do.

### The official reference is one draw of a random execution order

- **Construct**: `harness:random-event-execution`
- **Cases**: 12 — semantic/00952 semantic/00953 semantic/00962 semantic/00964 semantic/01588 semantic/01589 semantic/01591 semantic/01592 semantic/01599 semantic/01605 semantic/01626 semantic/01627
- **First recorded**: 2026-10-21
- **What SBML requires**: SBML Level 3 Version 2 Core Sec. 4.12.3 and Sec. 4.12.7 define the order in which simultaneously triggered events are executed; a case that draws the events in a random order is a valid instance of that semantics.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12.3, Sec. 4.12.7
- **What BNG3 does instead**: Nothing is refused: the model converts and the engine executes the events in the order the specification defines. The harness cannot compare point-wise, because the reference is one draw of a random order and no deterministic simulator reproduces it point-wise.
- **Reducible?**: Yes, on the measurement side: the comparison has to be distributional rather than point-wise, or the reference has to pin the order. It is a measurement limit, not a limitation of the Atomizer.

### The official reference samples a scheduled-action phase boundary

- **Construct**: `harness:scheduled-action-phase-boundary`
- **Cases**: 2 — stochastic/00028 stochastic/00032
- **First recorded**: 2026-10-22
- **What SBML requires**: SBML event execution applies EventAssignments when the event fires; the reporting convention at an event time must distinguish pre-event from post-event state.
- **Citation**: SBML Level 3 Version 2 Core Sec. 4.12.5, Sec. 4.12.7; campaign reference-comparison contract
- **What BNG3 does instead**: The source model converts, round-trips, and passes the independent trajectory comparison. The official reference grid includes the exact scheduled-action boundary, where the official convention reports the assignment as already applied while the native action dispatcher exposes the pre-assignment phase value. The point-wise reference comparison therefore remains unsupported.
- **Reducible?**: Yes, in the comparison contract: sample the post-event value at the defined boundary, or compare according to the event execution phase. This is a harness/runtime observation-boundary issue, not an Atomizer refusal.

### Projected stochastic work exceeds the comparison-planning threshold

- **Construct**: `harness:stochastic-ensemble-budget-not-comparable`
- **Cases**: 2 — stochastic/00005 stochastic/00023
- **First recorded**: 2026-10-22
- **What SBML requires**: The official stochastic reference specifies an ensemble size and reports an ensemble outcome; comparison requires the harness to execute that ensemble and evaluate its statistics.
- **Citation**: DSMTS user guide and the pinned official test case settings
- **What BNG3 does instead**: The SBML model converts. A fixed-seed CPU probe projects ensemble work above the configured planning threshold, so the harness marks the official comparison not comparable. The projection is an estimate; it is not an enforced cap or a runtime guarantee.
- **Reducible?**: Yes, on the harness side: improve planning or execution so the specified ensemble can be evaluated, then compare it without changing the official statistics or thresholds.

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
| `harness:reference-does-not-track-variable` | The official reference does not report a boundary species | closed | 2026-10-21 | Closed by PR #380, validated 2026-10-21: the direct SSA path no longer decrements or increments a boundary species, so the model's value matches the official reference and the three cases are compared instead of skipped. The defect had been a symptom of the engine honouring a boundary species in three of its four engines. First measured as closed on 2026-10-21. |
| `harness:scheduled-actions-not-executed` | The reference runner could not execute a model with actions | closed | 2026-10-21 | Closed by PR #337, validated 2026-10-20: the harness now validates official references for action-bearing cases, so these cases are compared rather than skipped. First measured as closed on 2026-10-21. |
| `harness:stochastic-ensemble-not-evaluated` | The official reference needed an ensemble the harness did not run | closed | 2026-10-21 | Closed by PR #337, validated 2026-10-20: the harness now evaluates the official stochastic references, so these cases are compared rather than skipped. First measured as closed on 2026-10-21. |
| `reference:no-result-mapping` | The official reference names a quantity BNG3 cannot observe | closed | 2026-10-21 | Closed by PR #378, validated 2026-10-21: the Atomizer states each reaction's rate as a zero-argument function and the harness maps a reference variable naming a reaction onto it, so the twenty-two cases are compared against the official reference instead of being skipped. First measured as closed on 2026-10-21. |
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
- **2026-10-21** — Closed: a reference that names a reaction's rate is now compared, because the Atomizer states the rate as a zero-argument function and the harness maps the reference's quantity onto it (PR #378); and a boundary species is now honoured by the direct SSA path, so the reference's value for it is compared rather than skipped (PR #380). The event limit 'an event the Atomizer cannot lower, or cannot order' shrinks by one case: an event group whose priority is read from the model state is now ordered by the priority it has at the execution instant (PR #376).
- **2026-10-22** — Corrected three previously unclassified cause/owner labels without changing verdicts or stage counts: semantic/00950 is MathML infinity, semantic/00951 is a non-finite parameter approximation, and stochastic/00028 and stochastic/00032 are scheduled-action phase-boundary comparison limits owned by the harness.

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
