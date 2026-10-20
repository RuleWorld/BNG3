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

1. **Initial-value resolution order** (PR #316). A `constant="false"`
   parameter with no `value` attribute was seeded with the default `0`,
   shadowing the value its `assignmentRule` supplies, and `initialAssignment`s
   were evaluated before `assignmentRule`s. SBML L3 Core §4.8/§4.11 fixes the
   order. 15 official cases move `failed → passed`.

2. **SBML `avogadro` csymbol conflated with BNGL's `__Avogadro__`, and
   `csymbol` identified by its text** (PR #318). SBML's `avogadro` csymbol
   has the fixed value `6.02214179e+23` (SBML L3 Core §4.2.5, which requires
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

The combined effect of all six changes is recorded in the integrated
result below.

## Integrated result (PRs #316, #318, #319, #320, #321, #322)

Measured on the merged tree at base commit `219c76da`:

| Stage | Before | After |
| --- | --- | --- |
| Conversion | 1712 passed / 211 unsupported / 0 failed | **1724 passed / 199 unsupported / 0 failed** |
| Round-trip structure | 1712 passed | **unchanged** |
| Independent libRoadRunner comparison | 1712 passed | **unchanged** |
| Official reference | 1115 passed / 701 unsupported / 107 failed | **1191 passed / 693 unsupported / 39 failed** |

81 official-reference cases change status and **none regresses**. The Python
suite is 1551 passed / 28 skipped / 2 xfailed, with one pre-existing failure
(`test_generated_notebooks_execute_in_qualified_kernel`) that also fails on
the unmodified base commit.

Per-change contribution (measured per branch, so the numbers overlap where
one change enables another):

| PR | Change | Official cases fixed |
| --- | --- | --- |
| #316 | Initial-value resolution order | 15 |
| #318 | `csymbol` by `definitionURL`; static parameter initial assignments | 20 |
| #319 | Amount-based rate laws in a non-unity compartment | 19 |
| #320 | n-ary MathML relations | 3 |
| #321 | Parameter assignment rules: the amount/concentration distinction | 10 |
| #322 | MathML trigonometric reciprocals; numeric fidelity; assigned stoichiometry | 14 |

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
| D | Harness: scheduled actions + stochastic ensembles + reaction extents | agent D | **not started — highest remaining leverage** (533 cases) |
| E | `delay` / `rateOf` in the C++ SBML writer | agent E | not started (~18 cases) |
| F | State-dependent SBML event triggers | agent F | not started (~35 cases) |
| G | Structural atomization (molecular identity, sites, uncertainty) | agent G | partial work in `/tmp/bng3-campaign/wt-atomizer-structure` |
| I | Assignment rules whose target is a parameter | agent I | not started (~8 cases) |
| J | Time-dependent stoichiometry (rate-ruled `speciesReference`) | agent J | not started (~10 cases) |
| — | Independent review of each implementation PR | separate reviewer | required before merge |

### Remaining official-reference failures (39), by cluster

| Cluster | n | Cases |
| --- | --- | --- |
| `CSymbolDelay` | 12 | 00938 00940 00941 00942 00943 01400 01401 01403 01406 01409 01419 01534 |
| `RateRule` (variable stoichiometry) | 10 | 01103 01637 01718 01727 01728 01729 01736 01737 01738 01742 |
| `InitialAssignment` | 7 | 00785 00786 00879 01514 01516 01631 01633 |
| `CSymbolRateOf` | 3 | 01460 01542 01822 |
| `AssignmentRule` | 3 | 01216 01492 01493 |
| `CSymbolAvogadro` | 2 | 01121 01723 |
| other | 2 | 00951 01820 |
| `AlgebraicRule` | 1 | 01575 |

## Merged result (2026-10-20)

All seven campaign pull requests are merged into `main`:

| PR | Title | Merge commit |
| --- | --- | --- |
| #316 | Fix SBML initial-value resolution order in atomizer seed values | `3910dccd` |
| #317 | Add machine-readable SBML Atomizer coverage inventory and campaign baseline | `25451a65` |
| #318 | Interpret SBML csymbols by definitionURL and fold static parameter initial assignments | `d4ec1ee2` |
| #319 | Preserve amount-based SBML rate laws in non-unity compartments | `0fbda8fd` |
| #320 | Lower an n-ary MathML relation as the conjunction of its successive pairs | `aa427e70` |
| #321 | Report a parameter assignment rule's value as the quantity SBML defines | `451884f5` |
| #322 | Support MathML trigonometric reciprocals and report an unresolvable assigned stoichiometry | `fa53a8e8` |

Measured on the merged `main` (`fa53a8e8`) against the campaign baseline
(`219c76da`):

| Stage | Before | After |
| --- | --- | --- |
| Conversion | 1712 passed / 211 unsupported / 0 failed | **1724 passed / 199 unsupported / 0 failed** |
| Official reference | 1115 passed / 701 unsupported / 107 failed | **1191 passed / 693 unsupported / 39 failed** |

81 cases change status: 67 move `failed → passed`, 9 move `unsupported →
passed`, 4 move `unsupported → unsupported` (the conversion stage improves
while the official reference stays unevaluated), and 1 moves `failed →
unsupported` (a case whose defect is now reported explicitly instead of
producing a wrong trajectory). **No case regresses.**

The Python suite on the merged tree is 1552 passed / 28 skipped / 2 xfailed,
with one pre-existing failure
(`test_generated_notebooks_execute_in_qualified_kernel`) that also fails on
the unmodified base commit.

### A regression the campaign's own validation caught

The first form of PR #319 multiplied the recovered mass-action constant by
`V**(m-1)` for every amount-based law. The generated integrated-validation
case `dimerization-v1-n20-r0-a0` uses the law `k * A * A / cell`, which
already states its own volume dependence; the correction produced the rate law
`0.8 * (__compartment_cell__)**1`, which BNG2's expression parser rejects
("Unexpected operator \"*\" found at position 26") and BioNetGen 2.9.3 cannot
simulate. The integrated cross-component validation failed, and the correction
was narrowed to a law that does not name a compartment.

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
