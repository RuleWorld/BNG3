# Curated BioModels corpus: coverage, failure taxonomy, and mode comparison

This document records one measurement of the curated BioModels corpus: what
the modern SBML Atomizer does with every manually curated BioModels record,
why a record is not supported, and how the *flat* translation compares with
the *atomized* (structural-inference) translation.

The machine-readable form of the same measurement is
[`provenance/curated-biomodels-corpus-inventory.json`](../provenance/curated-biomodels-corpus-inventory.json).
It is produced by
[`scripts/ci/curated_biomodels_corpus_inventory.py`](../scripts/ci/curated_biomodels_corpus_inventory.py)
from the harness reports, so the numbers here and the numbers in the
inventory are the same numbers.

## Corpus identity

| Field | Value |
| --- | --- |
| Source | BioModels manually curated records (`curationstatus:Manually curated`) |
| Search API | `https://www.ebi.ac.uk/biomodels/search` |
| Snapshot date | 2026-09-15 (`provenance/published-biomodels.json`) |
| Records in the inventory | 1096 (1075 declared SBML, 10 archives, 11 other formats) |
| Records that reach the Atomizer | 1083 (declared SBML plus 8 archives with an extractable SBML member) |
| Gate | `scripts/ci/validate_published_biomodels.py` |
| Comparison | every generated BNGL observable against libRoadRunner CVODE on the same time grid |
| Simulation window | `t_end = 1.0`, 10 steps, `rtol = 1e-7`, `atol = 1e-12` |
| Per-model budget | 180 s |

Every record is retained. A record that is not an SBML artifact is reported
as `unsupported_format` with its format, not silently dropped.

## How the statuses are read

The harness owns the vocabulary, and the categories are kept apart:

| Status | Meaning |
| --- | --- |
| `passed` | the Atomizer converted the record, the network generated, the written SBML re-imported with the same species and reaction counts, the native SBML reader agreed, and libRoadRunner reproduced every observable |
| `unsupported` | the record uses an SBML construct the Atomizer refuses to approximate; the reason is recorded |
| `unsupported_format` | the record is not an SBML artifact |
| `failed` | the record did not convert, or the conversion did not reproduce the source's mathematics |
| `timeout` | the record did not finish inside the per-model budget |

`unsupported` is an expected outcome, not a defect: a curated BioModels
record is allowed to use SBML that BNGL cannot represent. What must never
happen is a record that *converts* and then means something other than its
source. The residual failures below are the records where that distinction
still has to be made.

## The Atomizer's output is not reproducible across runs

This is a measurement caveat that applies to every number in this document,
and it is a defect in the Atomizer rather than in the corpus.

The modern Atomizer emits a different document for the same source model
depending on the process's `PYTHONHASHSEED`. A set iteration order leaks into
the emitted text, and the text's numeric constants change with it. One
curated record, `BIOMD0000001058`, is enough to show it:

```
PYTHONHASHSEED=0   Autocatalytic_synthesis_of_ClbMt: 0 -> @compartment:M_ClbMt() 0.01999940124825325
PYTHONHASHSEED=1   Autocatalytic_synthesis_of_ClbMt: 0 -> @compartment:M_ClbMt() 0.019998734476196073
PYTHONHASHSEED=2   Autocatalytic_synthesis_of_ClbMt: 0 -> @compartment:M_ClbMt() 0.019999159775260743
```

The same source, the same tree and the same native extension produce three
different constants. A corpus run therefore measures a slightly different
model on every pass, and a record whose observable sits at the edge of the
comparison's tolerance can pass on one pass and fail on the next. That is
the likely explanation for the records in this corpus whose status does not
reproduce.

The measurement in this document is taken with `PYTHONHASHSEED=0`, and the
per-record comparison between the branch and `main` is taken with the same
fixed seed, so that the diff shows the change under review and not the hash
order. With the seed fixed, a forty-record sample of the corpus produces
byte-identical BNGL on `main` and on the branch that carries the two Atomizer
fixes, and only the four records those fixes target differ.

## Residual failures

Thirteen records failed and twelve timed out. Each one is classified by the
SBML construct that causes it and by the layer that owns the outcome:

* **atomizer** — the Atomizer's lowering is wrong or incomplete;
* **harness** — the corpus harness or its independent oracle cannot judge the
  record; the Atomizer's own output is not the cause;
* **source** — the source model itself is degenerate and the Atomizer
  reproduces it faithfully;
* **writer** — the C++ SBML writer does not reproduce the generated model.

### What the two Atomizer fixes rely on

Both fixes are semantic, and both are anchored in the SBML Level 3 Version 2
Core specification:

* **A reaction id in a rule is that reaction's rate.** Sec. 4.2.8 ("Use of
  reaction identifiers in mathematical expressions"): "The value of the `id`
  attribute of a `Reaction` can be used as the content of a `ci` element in
  MathML formulas elsewhere in the model. Such a `ci` element or symbol
  represents the rate of the given reaction as given by the reaction's
  `KineticLaw` object." The rate of a reaction is the rate of change of its
  extent (Sec. 4.3.5, `extentUnits`): "what is colloquially referred to as the
  'rate of the reaction' is in fact equal to the rate of change of reaction
  extent", and the product of that rate with a species' stoichiometry is the
  species' contribution to its rate of change (Sec. 4.11, "Semantics of rate
  law and stoichiometry"). A rule that names a reaction therefore has to
  carry the reaction's own kinetic law, and every reference has to be
  replaced.
* **An initial assignment overrides the symbol's declared value.** Sec. 4.8.4
  ("Semantics of initial assignments"): "The value calculated by an
  `InitialAssignment` object overrides the value assigned to the given symbol
  by the object defining that symbol. For example, if a `Compartment`'s
  `size` is set in its definition, and the model also contains an
  `InitialAssignment` having that compartment's `id` as its `symbol` value,
  then the interpretation is that the `size` assigned in the `Compartment`
  object definition should be ignored and the value assigned based on the
  computation defined in the `InitialAssignment`." A rule that names such a
  compartment therefore has to use the assigned size, not the declared one.

| Record | Layer | Construct | What happens |
| --- | --- | --- | --- |
| `BIOMD0000000245` | atomizer | reaction id used as a rate in a rule | The rule names seven reaction ids. The flux inlining replaced one reaction per pass and stopped after four passes, so the remaining ids reached the emitted rule as unresolved expression symbols. **Fixed.** |
| `BIOMD0000000570` | atomizer | reaction id used as a rate in a rate rule | The same four-pass limit left three of seven reaction ids unresolved. **Fixed.** |
| `BIOMD0000000353` | atomizer | compartment size set by an `initialAssignment` | A species assignment rule names a compartment whose size an initial assignment sets. The compartment was rewritten to the constant volume parameter, producing `__compartment_X__()`: a call to an undeclared function. **Fixed.** |
| `BIOMD0000001098` | atomizer | MathML `<apply>` without an operator | Every reaction's kinetic law is an `<apply>` whose operator is a `<ci>` naming a parameter. MathML reads that as a call to an undeclared function, the Atomizer translated it faithfully, and the emitted rule does not parse. **Now reported as unsupported.** |
| `BIOMD0000000674` | writer | reversible rule with a `TotalRate` modifier | The Atomizer's translation matches the source (see below), but the C++ SBML writer writes the reverse direction of a reversible `TotalRate` rule with an extra factor for the product species and without the `bng:totalRate` annotation, so the written SBML does not reproduce the source's mathematics. **Not fixed here: the defect is in `cpp/io/SbmlWriter.cpp`, not in the Atomizer.** |
| `BIOMD0000000338`, `BIOMD0000000339` | harness | event-driven compartment size with a species rate rule | The Atomizer refuses explicitly: a species rate rule in a compartment whose size an event changes has no exact BNGL lowering. The harness does not recognise the refusal string and records the record as failed rather than unsupported. |
| `BIOMD0000000404` | harness | ill-conditioned product observable | The failing observable is a seven-fold product of species concentrations in a 1.41e-15 L compartment. The comparison sits at the edge of the tolerance, and the stored failure does not reproduce on the merged tree with the rebuilt native extension: three consecutive re-runs pass. |
| `BIOMD0000000451` | harness | stiff model rejected by the independent oracle | libRoadRunner's CVODE fails to converge on the written SBML at t ≈ 1.5e-8; BNG3's own solver produces a trajectory. The comparison needs both. |
| `BIOMD0000000601` | harness | stiff model rejected by a solver | A CVODE convergence failure that does not reproduce on the merged tree with the rebuilt native extension. |
| `BIOMD0000000731` | source | observable undefined at t=0 | The observable is `ln` of a quantity that is zero at t=0, so BNG3 and libRoadRunner both return `-inf`. The corpus comparison requires finite values in both engines. |
| `BIOMD0000000803` | source | observable undefined at t=0 | The observable is a ratio of two species that both start at zero, so both engines return NaN. |
| `BIOMD0000000973` | source | observable undefined at t=0 | The observable divides by a species that starts at zero, so both engines return NaN. |

For the three `source` records the two engines *agree*: BNG3 and libRoadRunner
return the same non-finite value at the same time point, and every other
observable agrees to round-off. The corpus comparison rejects a non-finite
value, so the record is reported as failed even though the translation is
faithful.

### The `BIOMD0000000674` evidence

`BIOMD0000000674` (Reyes-Palomares2012) is the one failure whose cause is
neither the Atomizer nor the harness. The generated BNGL and the *source*
SBML agree:

```
libRoadRunner on the source SBML     BNG3 on the generated BNGL
  t=0.50   glc = 9.676929              glc_amt = 9.676929
  t=1.00   glc = 9.907090              glc_amt = 9.907090
```

but libRoadRunner on the *written* SBML does not:

```
libRoadRunner on the written SBML
  t=0.10   glc = 84.062232
  t=1.00   glc = 662.870745
```

The written SBML contains the reversible rule as two irreversible reactions.
The forward direction reproduces the BNGL's forward rate, and the reverse
direction does not: the BNGL's reverse rate is

```
((V_cgly * _c_c_gly) / (K_cgly + _c_c_gly)) * __compartment_cytosol__
```

and the writer emitted

```
((V_cgly * _c_c_gly) / (K_cgly + _c_c_gly)) * __compartment_cytosol__ * S23
```

The extra `S23` factor multiplies the reverse flux by the amount of the
product species, and the reaction is also the only one in the document that
is missing the `<bng:totalRate/>` annotation that marks a `TotalRate` rule.
The defect is in `cpp/io/SbmlWriter.cpp`, in the reverse direction of a
reversible rule.

## Residual timeouts

Twelve records time out. For all twelve the cost is in the Atomizer's
Python expression translation, not in the C++ network generator: the
translation is measured directly, and the network generation that follows it
takes one to three seconds.

| Record | Model | Translation time | Network generation |
| --- | --- | --- | --- |
| `BIOMD0000000574` | Lai2014, hemiconcerted MWC | 180 s | 1.0 s |
| `BIOMD0000000255` | Chen2009, ErbB signalling | 520 s | 0.4 s |
| `BIOMD0000000471` | Smallbone2013, yeast linlog | 296 s | 3.0 s |

The remaining nine are the genome-scale metabolic reconstructions
(`BIOMD0000000469`, `BIOMD0000000470`, `BIOMD0000000472`, `BIOMD0000000473`,
`BIOMD0000001096`, `BIOMD0000001099`) and the large regulatory networks
(`BIOMD0000000235`, `BIOMD0000000474`, `BIOMD0000000595`). Their source
documents are 1.1 MB to 2.7 MB and carry hundreds of reactions with
function-definition rate laws; the Atomizer inlines every function
definition at every call site, and the resulting expression rewriting is
quadratic in the size of the model.

A timeout is a performance verdict, not a semantic one. None of these
records has been shown to convert incorrectly.

## Flat versus atomized mode

`atomize=False` translates each SBML species into one BNGL molecule.
`atomize=True` asks the Atomizer to recover molecules, binding sites and
modification states from the species names. The structural trigger lives in
`python/bionetgen/atomizer/modern/core.py`: a species is only given a
molecular interpretation when its name carries a bond character.

The consequence for a real corpus is quantified in the inventory:

* `modes.flat` and `modes.atomized` hold the per-mode status counts, with
  the same denominators (the 1083 records that reach the Atomizer).
* `mode_comparison.lost_in_atomized` lists the records that convert in flat
  mode and do not convert in atomized mode. A record that is lost between the
  modes is a defect in the structural lowering, because the atomized
  translation has to preserve the mathematics of the flat one.
* `mode_comparison.moved_between_modes` and `modes.atomized.status_counts`
  give the size of the difference between the two modes.

### The atomized mode is not an equivalent translation of the flat mode

On the merged tree the atomized mode loses records that the flat mode
converts, and it gains none. Every movement between the two modes is a
`passed` record that becomes a `timeout`, and every loss is a timeout of the
C++ network generation: the inferred structure multiplies the number of
complexes the generator has to expand.

Where the structural inference *does* fire, the atomized translation is not
mathematically equivalent to the flat one. Seventeen records produce a
different network in the two modes, and in all seventeen the deterministic
trajectories of the shared observables differ:

| Measure | Value |
| --- | --- |
| Records with a different network in atomized mode | 17 of the 782 that produced a network in both modes |
| Of those, records with the same species and reaction counts | 0 |
| Of those, records with equivalent trajectories | 0 |
| Median scaled trajectory difference | 1.0 (the observable's own magnitude) |
| Largest scaled trajectory difference | 1.93 |

Two examples: `BIOMD0000000581` has 31 species and 32 reactions in flat mode
and 29 species and 32 reactions in atomized mode, and the observable
`species_14` differs by its own magnitude; `BIOMD0000000105` grows from 39
species and 139 species, and `MisP_Ub7_Proteasome` differs by its own
magnitude.

The atomized mode is therefore a *different model*, not a different spelling
of the same model. It is not a defect of the flat mode, and the flat mode is
not wrong because of it, but the atomized mode cannot be offered as an
equivalent translation of the same SBML model, and a record that only
converts in one of the two modes has to say which mode it was measured in.

The structural-atomization rate is reported separately, because "the atomizer
emitted a different document" and "the atomizer recovered a molecular
structure" are different claims. The trigger in
`python/bionetgen/atomizer/modern/core.py` is

```python
has_real_structure = ("." in item_name or "(" in item_name) and "!" in item_name
```

so a species only receives a name-parsed molecular interpretation when its
name carries a bond character and a component separator.
`scripts/ci/measure_structural_trigger.py` counts that over the corpus
without a second translation pass:

| Measure | Value |
| --- | --- |
| Records measured | 1075 of 1096 (the other 21 are non-SBML records or archives) |
| Records with at least one species carrying the structural trigger | **2 (0.19 %)** |
| Records whose species are all elemental | 1073 (99.81 %) |
| Species carrying the trigger | 18 of 42 222 (0.043 %) |

The structural-atomization rate of the real corpus is therefore close to
zero: the name-parsed molecular structure almost never fires, and a model
that is translated in atomized mode degrades to one molecule per species.
What the atomized mode *does* change for most records is nothing at all: of
the records that produced a network in both modes, the median species
inflation is 1.0 and only a small minority of records produce a different
network. The records that do change are the ones where the dependency-based
inference splits a species into its components, and there the network grows
by an order of magnitude or more (see the lost-records list).

That growth is the reason the atomized mode loses records: the C++ network
generation has to expand the inferred complexes, and the expansion is
combinatorial in the number of inferred binding sites. For example
`BIOMD0000000002` translates to 13 species and 17 reactions in flat mode and
to 413 species and 417 reactions in atomized mode, and the network generation
alone takes 10.9 s. On the larger records the same expansion does not finish
inside the per-model budget.

## Reading the inventory

The inventory is derived from the harness reports; it never re-judges a
record.

| Key | Meaning |
| --- | --- |
| `corpus` | the BioModels inventory query, the snapshot date and the expected record counts |
| `measurement` | the base commit, the measurement date, the tool versions and the SHA-256 of each harness report |
| `modes.flat`, `modes.atomized` | per-mode status counts, unsupported-cause counts and the harness summary |
| `cases` | one row per record: the format, the flat and the atomized status, the unsupported causes of each, and whether the status differs between the modes |
| `residuals` | the failed and timed-out records, their identifiers, and the count per owning layer |
| `mode_comparison` | the number of records that move between the modes, the records lost in atomized mode and the records gained |

## Reproducing the measurement

```bash
# one full corpus pass at a time; the shared slot serialises the passes
python3 /tmp/bng3-campaign/with-verify-slot.py -- \
  python scripts/ci/validate_published_biomodels.py \
    --cache-dir <corpus cache> --json <flat report>.json \
    --offline --isolate-models --jobs 3 --model-timeout 180 --mode flat

python3 /tmp/bng3-campaign/with-verify-slot.py -- \
  python scripts/ci/validate_published_biomodels.py \
    --cache-dir <corpus cache> --json <atomized report>.json \
    --offline --isolate-models --jobs 3 --model-timeout 180 --mode atomized

# reduce the two reports to the committed inventory
python scripts/ci/curated_biomodels_corpus_inventory.py \
  --flat-report <flat report>.json \
  --atomized-report <atomized report>.json \
  --base-commit <sha> --measurement-date <date> \
  --out provenance/curated-biomodels-corpus-inventory.json
```

A record that times out inside a full pass is re-measured on its own with
`--only-id` before the timeout is reported, because a per-model budget that
fires under machine contention is not a semantic verdict.
