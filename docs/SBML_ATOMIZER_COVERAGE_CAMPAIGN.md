# SBML Atomizer coverage campaign

Target: make the BNG3 modern Atomizer the most correct, comprehensive and
robust SBML-to-BNGL converter, with **demonstrable** mathematical equivalence
rather than merely successful conversion.

This document records the campaign's measurement baseline, the failure
clusters derived from it, and the state of each workstream. The
machine-readable form of the same data is
[`provenance/sbml-campaign/baseline-2026-10-19.json`](../provenance/sbml-campaign/baseline-2026-10-19.json);
regenerate it with `scripts/ci/sbml_campaign_inventory.py`.

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

### Official SBML Test Suite — 1923 pinned cases (1823 semantic + 100 stochastic)

| Stage | Passed | Unsupported | Failed | Timed out |
| --- | --- | --- | --- | --- |
| Conversion (SBML → BNGL) | 1712 | 211 | 0 | 0 |
| Round-trip structure | 1712 | 211 not tested | — | — |
| Independent libRoadRunner comparison | 1712 | 211 not tested | — | — |
| **Official reference comparison** | **1115** | **701** | **107** | 0 |

### Curated BioModels — 1096 records (1075 declared SBML, 10 archive, 11 other)

| Mode | Passed | Unsupported | Failed | Timed out |
| --- | --- | --- | --- | --- |
| Flat | 943 | 117 (+11 unsupported format) | 13 | 12 |

Denominators: 1096 inventory records; 1083 records reach the SBML path.

## Failure clustering

The 701 official-reference "unsupported" verdicts split into **harness
limitations** and **Atomizer limitations**. This distinction is the single
most important fact in the campaign: most of the remaining official coverage
gap is not an Atomizer defect.

| Count | Blocking reason | Owner |
| --- | --- | --- |
| 433 | `generated BNGL contains scheduled actions; the in-memory CVODE reference runner cannot execute actions on the official output grid` | harness |
| 100 | `official stochastic conformance requires repeated-run mean and standard-deviation evaluation` | harness |
| 34 | `case does not define an official time-course reference` | not applicable |
| ~35 | `Reaction "…" is marked fast (fast="true")` | Atomizer diagnostic |
| ~24 | state-dependent / non-constant SBML events untranslated | Atomizer |
| ~17 | `SBML math function "delay" is not losslessly representable in the C++ SBML writer` | C++ writer |
| ~15 | `<sec>/<csc>/<cot>/<arcsec>/<arccot>/… have no BNGL builtin` | Atomizer diagnostic |
| ~15 | `no exact BNG3 result mapping for: <reaction id>` | harness mapping |
| ~12 | `… has no MathML expression` (empty math) | Atomizer |
| ~33 | `N reaction(s) have no MathML kinetic law` | Atomizer |

### The 107 official-reference failures, clustered by SBML feature tag

Derived from each case's own `componentTags` metadata in the suite's
`NNNNN-model.m` notes:

| Cluster | n | Cases |
| --- | --- | --- |
| `InitialAssignment` | 19 | 00785 00786 00879 01494 01498 01513 01514 01516 01631 01633 01642 01643 01644 01651 01652 01653 01766 01781 01821 |
| `CSymbolAvogadro` | 15 | 00960 00961 01121 01316 01323 01479 01641 01665 01722 01723 01762 01763 01775 01776 01777 |
| unclassified | 14 | 00951 01002 01003 01005 01006 01009 01010 01307 01773 01774 01807 01808 01809 01820 |
| `CSymbolDelay` | 13 | 00938 00940 00941 00942 00943 01174 01400 01401 01403 01406 01409 01419 01534 |
| `AssignmentRule` | 13 | 00999 01015 01198 01205 01206 01207 01208 01216 01478 01492 01493 01767 01796 |
| `RateRule` | 12 | 01017 01103 01637 01718 01727 01728 01729 01736 01737 01738 01742 01768 |
| `CSymbolRateOf` | 5 | 01455 01456 01460 01542 01822 |
| `AlgebraicRule` | 1 | 01575 |

## Known root causes (verified)

1. **Initial-value resolution order** (fixed in PR #316). A
   `constant="false"` parameter with no `value` attribute was seeded with the
   default `0`, shadowing the value its `assignmentRule` supplies, and
   `initialAssignment`s were evaluated before `assignmentRule`s. SBML L3 Core
   §4.8/§4.11 fixes the order. 15 official cases move `failed → passed`.

2. **SBML `avogadro` csymbol conflated with BNGL's `__Avogadro__`.** SBML's
   `avogadro` csymbol has the fixed value `6.02214179e+23` (SBML L3 Core
   §4.2.5); BNGL's `__Avogadro__` is `1`. The modern Atomizer maps the
   `csymbol` to `__Avogadro__`, and the operator-position `csymbol` path keys
   on the element *text* rather than on `definitionURL`, so
   `<csymbol definitionURL="…/avogadro">time</csymbol>` is read as the symbol
   `time`. 15 official failures.

3. **Amount-based (`hasOnlySubstanceUnits="true"`) rate laws in a
   non-unity compartment.** SBML L3 Core §4.11.5: an amount-based rate is a
   flux (mol/s), while BNGL's rate law is a concentration rate. The
   transformation needs a factor of `V^(m-1)` for a rate with `m` reactant
   species factors. Cases 01002/01003/01005/01006/01009/01010 diverge from
   the official reference by exactly the missing volume factor; the
   volume-1 sibling case 00061 passes.

## Workstreams

| ID | Cluster | Owner | State |
| --- | --- | --- | --- |
| A | Initial-value resolution order | agent A | PR #316 (review pending) |
| B | Over-conservative diagnostics (MathML reciprocals, `fast`) | agent B | in progress |
| C | Empty MathML / reactions without a kinetic law | agent C | pending |
| D | Harness: scheduled actions + stochastic ensembles + reaction extents | agent D | pending |
| E | `delay` / `rateOf` in the C++ SBML writer | agent E | pending |
| F | State-dependent SBML event triggers | agent F | pending |
| G | Structural atomization (molecular identity, sites, uncertainty) | agent G | pending |
| — | Independent review of each implementation PR | separate reviewer | required before merge |

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
