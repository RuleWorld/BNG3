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
_Source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit `219c76dac38655c0f15a12ee294e4a4ac10d02ef`; a timed-out case is recorded as failed and an unevaluated stage as not tested._

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
_Source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit `219c76dac38655c0f15a12ee294e4a4ac10d02ef`._

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
_Source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit `219c76dac38655c0f15a12ee294e4a4ac10d02ef`; clusters read from `/tmp/bng3-ssts-20261016` case notes._

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

The baseline official-reference failures are also grouped by each case's own
official `componentTags` metadata, read from the pinned suite's own
`NNNNN-model.m` notes. The generated baseline table lists every failing case,
so a cluster table can no longer omit the cases it forgot.

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
| E | `delay` / `rateOf` in the C++ SBML writer | agent E | not started |
| F | State-dependent SBML event triggers | agent F | not started |
| G | Structural atomization (molecular identity, sites, uncertainty) | agent G | partial work in `/tmp/bng3-campaign/wt-atomizer-structure` |
| I | Assignment rules whose target is a parameter | agent I | not started |
| J | Time-dependent stoichiometry (rate-ruled `speciesReference`) | agent J | not started |
| — | Independent review of each implementation PR | separate reviewer | required before merge |

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

Per-change contribution, measured per branch, so the numbers overlap where one
change enables another. This table is a historical per-branch record; it is
not part of the generated region and is not regenerated by the table
generator.

| PR | Change | Official cases fixed |
| --- | --- | --- |
| #316 | Initial-value resolution order | 15 |
| #318 | `csymbol` by `definitionURL`; static parameter initial assignments | 20 |
| #319 | Amount-based rate laws in a non-unity compartment | 19 |
| #320 | n-ary MathML relations | 3 |
| #321 | Parameter assignment rules: the amount/concentration distinction | 10 |
| #322 | MathML trigonometric reciprocals; numeric fidelity; assigned stoichiometry | 14 |

The generated tables below give the measured before/after state of every
stage, the exact cases that changed verdict, and the cases that regressed.

<!-- BEGIN GENERATED: sbml-campaign-current -->

#### Official SBML Test Suite — current stage results

| Stage | Passed | Unsupported | Failed | Not tested |
| --- | --- | --- | --- | --- |
| Conversion (SBML → BNGL) | 1724 | 199 | 0 | 0 |
| Round-trip structure | 1724 | 0 | 0 | 199 |
| Independent libRoadRunner comparison | 1724 | 0 | 0 | 199 |
| Official reference comparison | 1191 | 693 | 39 | 0 |
_Source: `/tmp/bng3-campaign/main-merged-report.json` (SHA-256 `a066b68e79457238d6438776a495ba87fe4fa6043664f0dc7f7cef7d548ac44b`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit `fa53a8e804b4919d2c5ec379908311c5f3422a63`; a timed-out case is recorded as failed and an unevaluated stage as not tested._

#### Official-reference unsupported verdicts, by owner

| Count | Owner | Blocking reason |
| --- | --- | --- |
| 437 | harness | the in-memory CVODE reference runner cannot execute actions on the official output grid |
| 100 | harness | official stochastic conformance requires repeated-run mean and standard-deviation evaluation |
| 35 | Atomizer diagnostic | Reaction "…" is marked fast (fast="true") |
| 34 | not applicable | case does not define an official time-course reference |
| 28 | Atomizer | state-dependent / non-constant SBML events untranslated |
| 19 | harness mapping | no exact BNG3 result mapping for: <reaction id> |
| 16 | Atomizer | … has no MathML expression (empty math) |
| 9 | C++ writer | SBML math function "…" is not losslessly representable in the C++ SBML writer |
| 5 | Atomizer | … has unsupported stoichiometry; the reaction is omitted |
| 3 | Atomizer | <infinity>/<notanumber> constant encountered in math |
| 2 | Atomizer | a compartment declares unsupported spatialDimensions |
| 2 | Atomizer | a species concentration rate rule requires an explicit compartment derivative |
| 2 | Atomizer | an assigned stoichiometry could not be resolved at initialization |
| 1 | Atomizer | algebraic rule(s) present |

Total official-reference unsupported verdicts: 693.
_Source: `/tmp/bng3-campaign/main-merged-report.json` (SHA-256 `a066b68e79457238d6438776a495ba87fe4fa6043664f0dc7f7cef7d548ac44b`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit `fa53a8e804b4919d2c5ec379908311c5f3422a63`._

#### Remaining official-reference failures, by official feature

| Cluster | n | Cases |
| --- | --- | --- |
| CSymbolDelay | 12 | 00938 00940 00941 00942 00943 01400 01401 01403 01406 01409 01419 01534 |
| RateRule | 10 | 01103 01637 01718 01727 01728 01729 01736 01737 01738 01742 |
| InitialAssignment | 8 | 00785 00786 00879 01498 01514 01631 01633 01821 |
| AssignmentRule | 2 | 01492 01493 |
| CSymbolAvogadro | 2 | 01121 01723 |
| CSymbolRateOf | 2 | 01460 01542 |
| other | 2 | 00951 01820 |
| AlgebraicRule | 1 | 01575 |

Total official-reference failures: 39.
_Source: `/tmp/bng3-campaign/main-merged-report.json` (SHA-256 `a066b68e79457238d6438776a495ba87fe4fa6043664f0dc7f7cef7d548ac44b`); SBML Test Suite revision `cf38585fac5de8e0e90112febb62851ee2181816`; BNG3 commit `fa53a8e804b4919d2c5ec379908311c5f3422a63`; clusters read from `/tmp/bng3-ssts-20261016` case notes._

#### Curated BioModels — current

| Mode | Records | Passed | Unsupported | Unsupported format | Failed | Timed out |
| --- | --- | --- | --- | --- | --- | --- |
| flat | 1096 | 943 | 117 | 11 | 13 | 12 |

Denominators: 1096 inventory records; 1083 records reach the SBML path; 1075 declare SBML; 10 are archives.
_Source: `/tmp/bng3-campaign/biomodels-main-flat.json` (SHA-256 `0e0583d1f568892085b1c3fe07902da92df508cfbab1a7983be27f3325aa25ba`); mode `flat`._

#### Stage verdict changes, baseline to current

| Stage | Before | After | Cases |
| --- | --- | --- | --- |
| conversion | passed | unsupported | 1 |
| conversion | unsupported | passed | 13 |
| independent_comparison | not_tested | passed | 13 |
| independent_comparison | passed | not_tested | 1 |
| official_reference | failed | passed | 67 |
| official_reference | failed | unsupported | 1 |
| official_reference | unsupported | passed | 9 |
| roundtrip_structure | not_tested | passed | 13 |
| roundtrip_structure | passed | not_tested | 1 |

Cases with at least one stage change: 81.

Regressions (a stage that was `passed` and no longer is):

- `semantic/01516` [conversion]: passed → unsupported
- `semantic/01516` [roundtrip_structure]: passed → not_tested
- `semantic/01516` [independent_comparison]: passed → not_tested

A stage that becomes `passed` is accepted only when the expectation manifest is explicitly updated.

Baseline source: `/tmp/bng3-campaign/baseline-ssts.json` (SHA-256 `1743bbd77513679e675a4a748acd0d15911e9e1bb648e4ba0f8deb15787c16c7`); current source: `/tmp/bng3-campaign/main-merged-report.json` (SHA-256 `a066b68e79457238d6438776a495ba87fe4fa6043664f0dc7f7cef7d548ac44b`).

<!-- END GENERATED: sbml-campaign-current -->

81 cases change verdict at one or more stages: 67 move `failed → passed` at
the official-reference stage, 9 move `unsupported → passed`, and 13 become
convertible. One case, `semantic/01516`, no longer converts: its assigned
stoichiometry cannot be resolved to a number at initialization, so the
Atomizer now refuses it explicitly instead of emitting a reaction with a
silently wrong stoichiometry. That refusal is a `passed → unsupported`
conversion change and is reported as a regression by the mechanical
comparison, even though it replaces a wrong conversion with an explicit
refusal.

## Python test suite

<!-- BEGIN GENERATED: sbml-campaign-python -->

#### Result

| Suite | Passed | Skipped | Xfailed | Failed |
| --- | --- | --- | --- | --- |
| tests/python | 1552 | 28 | 2 | 1 |

Source: `/tmp/bng3-campaign/pytest-main.xml` (SHA-256 `3e368688675824d097743cfe8a99ba7efcf581dc2f58701fdaf51c8021ded365`).

<!-- END GENERATED: sbml-campaign-python -->

The one failure (`test_generated_notebooks_execute_in_qualified_kernel`) also
fails on the unmodified base commit.

### A regression the campaign's own validation caught

The first form of PR #319 multiplied the recovered mass-action constant by
`V**(m-1)` for every amount-based law. The generated integrated-validation
case `dimerization-v1-n20-r0-a0` uses the law `k * A * A / cell`, which
already states its own volume dependence; the correction produced the rate law
`0.8 * (__compartment_cell__)**1`, which BNG2's expression parser rejects
("Unexpected operator \"*\" found at position 26") and BioNetGen 2.9.3 cannot
simulate. The integrated cross-component validation failed, and the correction
was narrowed to a law that does not name a compartment.

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
    "bng3_commit": "<BNG3 commit the report was measured at>",
    "python_version": "3.14.6",
    "measurement_date": "2026-10-20"
  },
  "cases": {
    "semantic/00001": {"conversion": "passed", "roundtrip_structure": "passed", "independent_comparison": "passed", "official_reference": "passed"}
  }
}
```

* `cases` has one entry per case, keyed `category/id`, and one status per
  stage. The status vocabulary is closed: `passed`, `unsupported`, `failed`,
  `not_tested`.
* `not_tested` means the stage produced no verdict (never executed, no
  reference defined, or the source was invalid). A timed-out case is recorded
  as `failed`, because the stage was attempted and did not succeed.
* `status_mapping` states how each harness field becomes a verdict, so the
  mapping is auditable rather than implicit.

### Regenerating the manifest

Refreshing the manifest is an explicit, reviewable act: it rewrites a
committed file, and the diff is the review.

```bash
# 1. Run the gate against the pinned suite.
PYTHONPATH=python:build/cpp python scripts/ci/validate_sbml_test_suite.py \
  --suite-dir /path/to/sbml-test-suite \
  --categories semantic stochastic --isolate-cases --case-timeout 120 --jobs 6 \
  --json /tmp/bng3-campaign/report.json

# 2. Regenerate the manifest from that report.
python scripts/ci/sbml_campaign_inventory.py \
  --suite-report /tmp/bng3-campaign/report.json \
  --expectations-out provenance/sbml-campaign/expectations.json \
  --measurement-date "$(date -u +%Y-%m-%d)"
```

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

The command exits non-zero and prints one line per differing case and stage:

```
semantic/01516 [conversion]: expected passed, observed unsupported (regression)
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
  --suite-report /tmp/bng3-campaign/main-merged-report.json \
  --baseline-biomodels-report /tmp/bng3-campaign/biomodels-baseline.json \
  --biomodels-report /tmp/bng3-campaign/biomodels-main-flat.json \
  --suite-dir /path/to/sbml-test-suite \
  --pytest-junit /tmp/bng3-campaign/pytest-main.xml \
  --doc docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md
```

The Python-suite row is read from a pytest JUnit report:

```bash
PYTHONPATH=python:build/cpp python -m pytest -q tests/python \
  --junitxml=/tmp/bng3-campaign/pytest-main.xml
```

The generator never runs the harness, never changes a verdict and never
edits reference data. Each generated table states the report, the report's
SHA-256, the SBML Test Suite revision and the BNG3 commit it came from.

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
