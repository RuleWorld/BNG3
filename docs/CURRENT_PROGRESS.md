# BNG3 current progress

This file records the live verification state. The scope boundary of the
SBML atomizer — the constructs it refuses, why, and whether each boundary is
reducible — is recorded separately in
[`ATOMIZER_LIMITATIONS.md`](ATOMIZER_LIMITATIONS.md).

## Curated BioModels #162 (2026-10-23)

The previously paused full curated BioModels lane was explicitly resumed and
run as [workflow run 40003233859](https://github.com/RuleWorld/BNG3/actions/runs/40003233859)
at exact main source `2eeb244f896e54b55335f918d10f4034fb322571`. The
independent main CI run [39959629615](https://github.com/RuleWorld/BNG3/actions/runs/39959629615)
completed successfully; it is separate from the corpus result. The run's
retained artifact [12529835188](https://github.com/RuleWorld/BNG3/actions/runs/40003233859/artifacts/12529835188)
is 3,612,605 bytes, SHA-256
`d024971a913d72dd0025b1b7d33f002c675a5c8d613b8189afdf8e1e6ce1f581`. Its
runtime pins libRoadRunner 2.10.0 and python-libsbml 5.21.2. The full run
selected all 1,096 curated records and retained both flat and modern atomized
reports. The 2026-09-15 offline snapshot verified all 1,096 inventory mappings
and 1,084 source payloads. The live membership endpoint's HTTP 403 was recorded
as unavailable; the verified offline snapshot supplied the run inputs.

Flat results: 946 passed, 112 unsupported, 11 unsupported-format,
21 timed out, one failed, four not comparable, and one source-acquisition
harness error. Atomized results: 945 passed, 112 unsupported,
11 unsupported-format, 23 timed out, one failed, three not comparable, and one
source-acquisition harness error. The report's 1,083 SBML records include
eight SBML files extracted from COMBINE archives. The trajectory comparator
ran libRoadRunner on BNG3-written SBML, not the original source SBML. Thus
the 946 / 945 passes measure written-export cross-engine consistency; they
do not establish Atomizer source fidelity. Original-source trajectory
comparison remains an acceptance gap. These are historical raw counts: the
comparer also used a global magnitude floor that can mask a smaller series'
mismatch when another observable is much larger. Per-observable scaling
requires its own regression and requalification.

`BIOMD0000000638` is the only product execution/numerical `failed` record in
both modes; that report alone does not establish an SBML semantic mismatch.
Its exact 203,221-byte source payload (SHA256
`1f62b7e92938b686d29039bc4aaa2a6fa024d6b6fc927ed773dd82d48a9c7657`) matches
the offline snapshot. The failed report record does not retain a libSBML source
validation result. BNG3 CVODE fails with flag `-3` in both modes before a
cross-engine trajectory comparison is produced. A separate source-side
control, run with libSBML 5.21.1 and libRoadRunner 2.10.0, found zero libSBML
errors and produced 11 finite time rows when selecting time plus all floating
species (shape 11 by 22) at `t=0..1`, 10 intervals, `rtol=1e-7`, and
`atol=1e-12`. The exact selections and command used for both source controls
are:

```sh
SOURCE=/path/to/source.xml python - <<'PY'
import os

import libsbml
import numpy as np
import roadrunner

source = os.environ["SOURCE"]
assert libsbml.readSBMLFromFile(source).getNumErrors() == 0
rr = roadrunner.RoadRunner(open(source, encoding="utf-8").read())
rr.timeCourseSelections = ["time", *rr.model.getFloatingSpeciesIds()]
rr.setIntegrator("cvode")
rr.integrator.setValue("relative_tolerance", 1e-7)
rr.integrator.setValue("absolute_tolerance", 1e-12)
values = rr.simulate(0, 1, 11)
assert values.shape[0] == 11 and np.isfinite(values).all()
PY
```

The source SHA-256 above is for `BIOMD0000000638`. A subsequent local
one-reaction reproducer establishes a source-fidelity defect in unit
normalization: for a custom `1e-15 litre` volume unit, `cell=2`, concentration
`A=1`, undeclared-unit `k=0.1`, and flux `cell*k*A*A`, normalization changes
the initial numerical flux from `0.2` to `2e14`. The original-source
libRoadRunner trajectory and translated native trajectory disagree. This
isolates a transformation defect; it does not establish that repairing it
will resolve the full model's integration failure. A committed regression,
principled repair, and hosted replay remain pending.

The report's 21 flat / 23 atomized timeouts all hit the per-record 180-second
budget. The current report and execution logs do not record the stage reached
by any of these timeouts. Twelve-record timeout cohorts in older inventory
expectations are historical triage hints only; they do not establish stages in
this run. These remain unresolved performance outcomes, not product semantic
failures. Twenty-eight unique source payloads spanning the failure, timeout,
and not-comparable cohorts were independently checked with libSBML 5.21.1
against the snapshot hashes and byte lengths; each parses as SBML with a model
and zero errors.

Three shared not-comparable records (`BIOMD0000000803`, `0731`, and `0973`)
have a translated/written observable undefined at `t=0`; BNG3 and
libRoadRunner reading BNG3-written SBML report the same undefined value, so
that pointwise comparison is not measurable. Undefinedness in the original
source has not been established. Flat-mode
`BIOMD0000000451` is a distinct concern: the report records that BNG3
simulation and written-SBML validation completed, but libRoadRunner CVODE
could not integrate the BNG3-written SBML. A separate source-side control, with
libSBML 5.21.1 and libRoadRunner 2.10.0, validates the exact source payload and
produces 11 finite time rows with time plus all floating species selected
(shape 11 by 60) on the same grid and tolerances; its SHA-256 is
`ba8e4a50a0e477906f96a66cc49494c825eaab0a489083f7bcdec5adf25b79c5`. The
reproduction command above applies with `SOURCE` set to this payload. Retain
the report's `not_comparable` classification, but treat this as unresolved
writer/output numerical risk rather than an unavailable-source oracle.

The run did not close issue #162: it exercised the modern Atomizer's flat and
atomized modes with BNG3 CVODE and libRoadRunner 2.10.0, but did not run the
legacy Atomizer cross-engine comparator requested by the issue. The hosted
workflow also failed its corpus-inventory comparison because it did not pass
the report's exact source revision to the inventory checker; this harness
wiring issue is separate from the scientific outcomes. A separate
non-SBML `Other` record, `BIOMD0000001075`, is a source-acquisition harness
error (HTTP 403), not a semantic result. Preserve the raw per-mode reports and
all record classifications; do not infer closure from the passing counts.

## Structural SBML atomization recovers molecular identity

The atomized SBML translation (`atomize=True`) recognized a molecular
structure only when a species name spelled a BNGL pattern that also
contained a bond, so most real BioModels species names silently degraded
to the elemental flat representation and lost every binding site, bond and
modification state.

The structural path now recognizes a structure from four sources, in
decreasing order of confidence.

1. An explicit BNGL pattern in the species name. A name that names more
   than one molecule, or one molecule with a binding or modification site,
   is a molecular pattern; the previous trigger required a bond and
   therefore rejected `A.B`, `A(B)` and every site-only name.
2. The SBML `sboTerm` of a species that a one-reactant/one-product
   reaction produces. The SBO term is the only machine-readable
   statement in the SBML source that names the modification, so it outranks
   any name heuristic. The supported terms are the SBO ids for
   phosphorylation, glycosylation, methylation, acetylation,
   ubiquitination, hydroxylation, the lipidation family, activation and
   inactivation, plus dephosphorylation for the unmodified form.
3. Reaction topology. A species produced by a reaction with two or more
   reactant molecules is a complex of those molecules, and the composition
   follows the source stoichiometry. A species that a reaction dissociates
   into several products is a complex of them; the previous heuristic
   required the complex name to contain every product name.
4. A name fragment. A trailing `-P`, `_P`, `.P` or `_act` fragment names a
   modification state of the base species the reaction derives it from, and
   a `-`/`_` separated name names a complex when every part names an
   existing species.

Every decision is recorded. `AtomizerResult.structural_inference` and
`Atomizer.structural_report()` return, per species, the inferred
molecules, sites, bonds and states, the confidence of the decision
(`explicit-pattern`, `sbo-term`, `reaction-topology`, `name-heuristic` or
`elemental`), the reason for it, and the alternative readings that remain
consistent with the SBML source. A name fragment that is not a valid BNGL
molecule identifier is reported as an informational diagnostic instead of
being dropped silently; the species keeps its exact flat representation in
that case.

The flat translation is unchanged. The structural evidence is consulted only
by the atomized path, so the official suite results are the same before and
after the change.

## Native BNGIR v0.2 model functions (2026-10-19 candidate)

The native BNGIR v0.2 importer refused the whole `model.functions` section, so
every generated case of the integrated semantic validation reported
`UNSUPPORTED` with the detail "native BNGIR does not support model.functions",
even though the only thing those documents used was a helper function.

The native C++ importer now rebuilds model functions. A declaration keeps its
name, its arguments and its body, and the body is rebuilt with the same
representation the BNGL parser produces: an argument is a plain identifier, a
call to another model function is a function call, and the body is resolved
against the parameters, the arguments, the other model functions and the
observables of the model. The supported body expressions are numbers,
parameter references, the function's own arguments, calls to other model
functions, a global observable reference, and the ordinary unary and binary
operators. Everything else stays an explicit refusal at the native boundary:
builtin calls, table functions, clock references, reactant-count references,
unresolved expressions, scoped observable references, and every expression kind
outside that list.

A declaration is refused when the compiler could not resolve it faithfully: a
function name that collides with a parameter, an observable or a builtin, a
duplicate function name, a duplicate argument name, an argument that shadows a
parameter the body still reads, a reference to an unknown function, and a call
whose arity does not match the declaration. The native reader's dense-id,
unique-name and cross-reference rules are applied to the section as well.

The reconstructed model executes. A model whose rate law runs through a model
function reconstructs natively, round trips to the same BNGIR v0.2 document,
and produces the same ODE and SSA numbers as the same model written in BNGL;
the trajectory is written to a `.gdat` and compared against the BNGL model.
The Playground-derived Atomizer cases, whose helper functions name an
observable, reconstruct and run unchanged.

The `bngir-v02` consumer therefore changes from `UNSUPPORTED` to `PASS` for
the generated cases: 45 of the 61 generated cases now pass the semantic
equality, network and simulation checks. The 16 dimerization cases stay
`UNSUPPORTED`, now for the reason that actually applies to them, a rule
direction with two reactant patterns, which is outside the native slice. The
native import boundary names that boundary in the established
"native BNGIR does not support ..." wording so the consumer reports a
support boundary instead of a harness failure.

## A skipped test case is a declared absence

The conformance gate requires every selected applicable diagnostic contract. A
pytest case that skipped states that it does not apply in this environment, and
the record said so, but the report classified it as an unexplained gap and the
strict gate failed on it. A skipped or expected-failure case is now recorded
with the applicability `not-applicable` and is not a gating failure. The record
stays visible in the report, and a case that was never executed at all still
gates.

## Native NFsim runs on the same model the embedded engine executes

The native NFsim stage ran the pinned oracle on BNG2's XML verbatim. The oracle
applies a compartment size only to zero-order synthesis, so for a
reactant-bearing rule it sampled a different model than BNG2's network and
than the embedded engine: the equal-seed comparison was not exact for any
compartment model, and the harness recorded the difference as a rounding
concern.

The stage now normalises BNG2's XML into BNG2's count-rate convention first,
the same conversion the XML rate probe already applies, so the oracle samples
the model the embedded engine executes. The rewrite reads the compartment of a
rule pattern, drops the symmetry factor the coefficient now carries, and
removes the compartment factor the oracle applies itself for a zero-order rule
whose product molecule states a compartment. An export the rewrite cannot
state is an explicit refusal rather than an approximation.

With the oracle on the same model, the seeded native and embedded NFsim
trajectories compare exactly for every generated case, so the exact
native-versus-embedded comparison covers the compartment and reversible
families as well.

## Native BNGIR rule directions with several patterns

The native importer rebuilt exactly one reactant and one product pattern, so
every generated dimerization case of the integrated semantic validation
reported `UNSUPPORTED` even though the document states a rule the importer can
rebuild. The importer now rebuilds every pattern the direction states.

A direction with more than one pattern is only rebuilt faithfully when the
document states the same operations the pattern structure implies: every
reactant molecule deleted and every product molecule added, with no molecule
carried over. A direction that declares a molecule mapping, states different
operations, or has a product molecule whose type matches a reactant molecule is
an explicit refusal at the native boundary, in the Python gate and in the
native importer alike. The reconstructed rule consumes both reactants and
creates the product, and the reconstructed model produces the same numbers as
the same model written in BNGL. The `bngir-v02` consumer changes from
`UNSUPPORTED` to `PASS` for the dimerization family: 25 case families now
qualify, 19 before.

## Non-finite rate coefficients are refused where they enter the engine

A rate law with no runtime dependency is folded into a constant rate
coefficient when the engine compiles the generated network. When that number
was not finite — a model function such as `f() = ln(-1)`, a parameter
expression, or a derived rate — the coefficient reached the simulator as a NaN
or an infinity: the SSA drew the next reaction from a NaN propensity table
and the ODE integrated NaN derivatives, so both engines ran a model that
cannot be simulated and reported nothing. The engine now refuses such a model
while it compiles the network, which is where the constant coefficient first
enters it, and the refusal reuses the established "non-finite functional rate
coefficient" wording. Because every simulator on that integrator compiles the
network first, the refusal covers the SSA, the batch SSA and the ODE methods,
as well as the rate-coefficient validation hook, which used to report the
non-finite value instead of refusing it. A coefficient that is non-finite only
at some later time belongs to a functional rate: the SSA already refuses that
case when it evaluates the rate, and the compile-time check leaves those
models alone.

`tests/validation/test_ssa_functional_rates.py` was not executed by any CI
job, which is why the gap stayed invisible. It now runs in the required
parity step, and it covers the ODE counterpart of the SSA refusal, the
parameter-expression case, and a finite-function model that must still run.

## Integrated semantic validation repairs (2026-10-19 candidate)

The hosted integrated semantic validation job failed on `main` with sixteen
failing results in three clusters, and the C++ suite failed with six placement
tests. Every cause was established against an independent oracle before
anything was changed.

- The native BNGIR compartment controls accepted a compartmented document, but
  the public network API reported the bare graph label, so the analytic control
  could not observe the compartment. `ast::Species::canonicalName()` now
  produces the BNG2-canonical identity (`@compartment::Pattern`, with the
  constant marker and per-molecule suffixes) and the `.net` writer and the
  network API share one implementation of it. `GeneratedNetwork.species_names`
  therefore names a compartmented species the way BNG2's `.net` and
  `SpeciesGraph::StringExact` do, and two species that differ only by
  compartment stay distinct. The control states the compartment spelling
  independently of the prefix, suffix and molecule spellings.
- The BNG-XML and NET rate comparison compared two conventions. The NET export
  folds BNG2's compartment unit conversion into the coefficient; the BNG-XML
  export keeps the rule rate constant, the symmetry factor and the compartment
  size apart, exactly as BNG2's `writeXML` does. The XML probe now applies the
  same conversion before the two are compared, so the boundary states one rate
  in one convention, and reports a parameter-backed compartment size as not
  comparable.
- The pinned native NFsim applies a compartment size only to zero-order
  synthesis, so it would sample a bimolecular rule in a compartment whose
  size is not one at `rate constant x symmetry factor` rather than at BNG2's
  count-rate coefficient. Running the pinned binary on BNG2's own XML at two
  compartment sizes produces identical trajectories, while BNG2's own `cvode`
  run on BNG2's `.net` matches the independent count law. The marginal stage
  now normalises the model it hands the oracle before it runs: it folds the
  same compartment unit conversion the XML probe applies into the rule's rate
  constant and drops the now-redundant symmetry factor, so the oracle samples
  the model the embedded engine executes and its marginals are compared
  against the independent count law again. An export whose compartment size
  is not statically determinable states no count-rate coefficient, and those
  native rows stay explicitly not tested with that reason.

The same candidate repairs a C++ regression that `main` carried: the
wildcard-compartment conversion guard introduced by `6e6a5a88` compared
compartment dimensions as well as sizes, so a model with several compartments of
one size but mixed dimensions was refused. The dimension selects the anchor
compartment, not the factor, so the guard now states the criterion it
documents, "every compartment shares one size and refreshes identically", and
the six placement tests pass again.

A non-pass stage rollup now states the reason its children give, and the
consumer matrix lane fails on failed or malformed results rather than on a
documented support boundary, which it reports distinctly. The remaining
openings are unchanged: the exact native-versus-embedded NFsim parity lane,
which still compares the pinned oracle on BNG2's own XML, the native BNGIR
rule-direction boundary behind the dimerization cases' `UNSUPPORTED` outcome,
and the #151/#146/#155 obligations that these rows feed.



## Generated dependency and native identity gates (2026-10-17)

Continuation from `e4394172` on PR #288, with bounded implementation work
selected from #138/#141/#143 and #153/#155. Existing explicit-grid action
`stop_if` behavior already matches pinned BNG2; its historical discrepancy was
not used to justify a duplicate repair.

- Shared parameter mutation now invalidates transitive values and time-dependence
  together. A deferred reset preserves linear block declaration construction.
  The generated Catch2 gate enumerates four dependency depths, both declaration
  orders, eager/lazy evaluation, five static/dynamic mutations, three times,
  and invalid-cycle recovery. Independent arithmetic and fresh construction
  check every node. Captured graph/order/step coordinates make failures replayable.
  The final matrix reports 1,224 failed assertions against the baseline
  `ParameterList.cpp` linked into the same test harness, and passes after repair.
- The Python lifecycle matrix checks timed ODE dynamics analytically, mutates to
  two constant rates, compares fresh/reused ODE trajectories and seeded NFsim
  replay. NFsim previously refused a stale transitive timed-rate classification.
  This is lifecycle evidence using embedded NFsim, not new independent-native
  NFsim qualification.
- Direct native BNGIR reconstruction rejects duplicate parameter/molecule-type
  names before distinct IDs can alias. A reusable ID remapper exercises all six
  permutations of a three-parameter dependency chain. Each reconstruction blocks
  BNGL parsing/rendering and checks native ODE derivatives against an analytic
  oracle. This does not establish a complete native BNGIR schema implementation.
- C++ and Python matrix jobs retain JUnit reports even on failure; C++ artifacts
  also retain CTest replay logs. Workflow contracts check report destinations,
  distinct filenames, upload ordering and unconditional retention. Reports expose
  actual test outcomes; a passing rejection test does not qualify that rejected
  feature as supported, and jobs not executed remain untested.

Local validation after final source/test edits: Release build passed; all 632
CTest checks passed; Python reported 1,393 passed, 30 skipped and two existing
xfails; workflow/report contracts passed 95 checks. The expression suite passed
3,600 assertions across 31 cases. Black, Ruff and diff checks passed. Hosted
exact-head results remain a separate gate. No full BioModels campaign was run.

Next priority is executing upstream PyBioNetGen as an isolated behavioral oracle
(the existing lane checks source signatures and BNG3 contracts), followed by
feature-class SBML/event qualification against official references/RoadRunner and
broader NFnext execution correspondence against pinned native NFsim. These remain
open workstreams; generated mutation/identity gates do not establish broad parity.

## Automation continuation (2026-10-17 candidate)

The follow-up read all 60 GitHub issue bodies (44 open, 16 closed) and selected
bounded work from their acceptance criteria:

- #141: a parameter-role × ODE/SSA reuse matrix compares mutations of volume,
  seed population and dependent rates with fresh compilation, an analytic ODE
  trajectory and exact seeded SSA replay.
- #171/#172: cold behavioral subprocesses select the parent's package. Required
  public-module and native-loader failures propagate instead of silently
  selecting legacy behavior or exposing `None`. Explicit Perl mode and genuinely
  absent native-module importability remain separate tested boundaries.
- #180: CI resolves populated reconciliation test references against Python AST
  test nodes, Catch2 declarations and CTest targets. Renamed, missing or
  commented-out tests fail the guard. Five of seven incorporated/superseded
  entries still have no test references; resolving a reference does not prove
  its associated behavior claim. Upstream drift/approval remains open.
- #157/#160: the event inactivity proof no longer freezes rate-ruled trigger
  parameters at their initial values. Three-state and coupled two-state controls
  now remain explicitly untranslated instead of falsely claiming the event can
  never fire. Official semantic/00403 is classified unsupported; RoadRunner shows
  its source event firing. This is a classification repair, not new event support.

Continue from the runtime/event and NFnext execution changes rather than treating
green CI as broad implementation equivalence. This candidate adds:

- 128 locked semantic SBML cases on PRs and the full semantic/stochastic inventory
  on scheduled/manual runs. Conversion, structural round-trip, independent
  RoadRunner comparison and official references have separate stage counts.
  Per-case inputs, translations, exported XML, worker reports and logs are retained;
  worker identity includes a digest of the Python sources.
  Each case runs in its own process; the default isolation mode forks one child
  per case from a parent that never executes a case body, and
  `--isolation-mode process` keeps the one-fresh-interpreter-per-case mode.
  Pooling changes no verdict: the per-case diff over all 1923 records is empty
  in both directions. A full-suite run takes an advisory, fail-open shared
  verification slot (`--lock-file`, `--no-lock`, `--lock-wait`).
- Live pinned BNG2 SSA ensembles in scheduled/manual parity, deterministic spread
  seeds, and an independent analytic marginal check for the fixed michment model.
  Scratch generation never refreshes committed golden files implicitly.
- Workflow contracts that detect removed triggers and explicitly selected tests
  omitted from PR path filters. CPU fallback does not qualify GPU execution.
- Focused regressions for concentration/amount rate rules, non-unit-volume Multi
  state changes and forward function calls during SBML export.

Local candidate evidence: build and 629 CTest checks passed; 65 focused
SBML/event/GPU-contract checks passed. The locked 128-case run passed all 128
conversion, structural round-trip and RoadRunner comparisons; official references
reported 122 passed and six unsupported, with no failures or timeouts. This is a
partial suite run, and full-suite aggregate flags remain false. Hosted final-head
CI remains a separate qualification gate. All three live 200-member BNG2 SSA
ensemble comparisons passed locally against the clean pinned source revision
`9601746f8884ed19ab2acea49fe87fc4660ace46`. CPU statistical controls passed all
four models. Actual GPU execution remains unqualified on this host.

The headless Python suite passes with 1,382 passed, 30 skipped and two existing
xfails. The subprocess selection contract repairs the source-versus-installed
notebook-defaults failure. Infrastructure
checks pass (138), including import identity, workflow wiring, reconciliation
references and SBML report/artifact handling. The event regression module passes
81 checks. Official semantic/00403 is explicitly unsupported with downstream
stages not tested; it is not counted as a passing scientific comparison.

Next development sequence:

1. Diagnose newly exposed scheduled failures by layer using retained replay
   artifacts; add a focused regression before each semantic repair.
2. Expand supported SBML/event/NFnext classes only with independent quantitative
   evidence and explicit unsupported boundaries.
3. Run GPU qualification on actual hardware; keep unavailable hardware and
   unsupported stochastic SBML statistics visible instead of inferring support.

The dated audit below describes its original revision, not this candidate.

**Audit refreshed:** 2026-10-16 against RuleWorld/BNG3 main
`2f7200a279767bcc4a78a33775224e30f3d65521`. This is an issue/CI scope audit,
not full qualification of that revision. Semantic convergence and release
qualification remain incomplete. The authoritative backlog is issues
[#132–#186](BNG3_CONVERGENCE_DONE_CHECKLIST.md): 44 open and eleven closed
(#132/#133/#134/#135/#136/#145/#165/#169/#173/#182/#183). #146 and #154 remain
open because their broader acceptance criteria are unmet.

The [convergence checklist](BNG3_CONVERGENCE_DONE_CHECKLIST.md) maps all 55 tasks
one-to-one. Issues own acceptance criteria, dependencies and detailed evidence;
unassigned work has no implied review owner. The
[repository audit](REPOSITORY_AUDIT_2026-10-07.md) is a dated source snapshot.
Historical [progress](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/CURRENT_PROGRESS.md)
and [checklist](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md)
retain the earlier reports.

## CI scope audit (2026-10-16)

For the revision above, push CI and push cross-tool parity passed, but scheduled
cross-tool parity [run 38878018998](https://github.com/RuleWorld/BNG3/actions/runs/38878018998)
failed. Its historical NFsim lane reported three failures and two errors; the
broader conformance lane also reported parser/oracle failures and downstream
`NOT_TESTED` results. Those findings require case-by-case diagnosis; neither
all-product-failure nor all-harness-failure is an established conclusion.

Green CI establishes only its selected contracts. Current limitations include:

- PyBioNetGen qualification checks upstream exports/signatures and BNG3
  compatibility contracts; it does not execute the upstream package as an
  independent differential oracle.
- Official SBML PR qualification selects 32 locked semantic cases. It does not
  establish complete SBML, structural Atomizer or SBML Multi execution support.
- Native event-bearing ODE execution explicitly rejects in `OdeIntegrator.cpp`;
  #157/#158 require implementation, not just longer qualification jobs.
- BNGIR and NFnext have executable tests, but those do not establish all of
  #153–#155 or a complete production model-to-NFnext boundary (#147/#148).
- CUDA hardware evidence, maintenance policy, scientific ownership and release
  approvals cannot be replaced by CPU CI success.

## Validation-only graph identity continuation (2026-10-18 candidate)

The integrated campaign now has a bounded #142 detector that feeds its normal
report and issue queue. Six generated seed-only cases exercise the installed
BNG3 native network generator against the independent validation graph matcher:
3-, 4- and 5-molecule symmetric rings under molecule/site/bond-label
permutations, plus negative controls for site-state, species-compartment and
per-molecule-compartment distinctions. Each named result links to #142, and a
mismatch is an ordinary failure. Focused local harness checks validate
non-vacuous oracle cases and
report wiring; no BNG3 build or native campaign was run locally, so production
outcomes await parity CI. This does not compare BNGcore and NFsim canonical
labels, exercise embedded or standalone NFsim identity, or establish general
network equivalence. #142's implementation/contract criteria remain open.
The first PR294 hosted graph batch had one apparent compartment mismatch: the
validation parser omitted the BNGL rule that molecules without an explicit
local compartment inherit the species prefix. The comparator now treats an
explicit inherited suffix and its omitted spelling as equal while retaining
failures for outer-compartment changes and loss of a non-default local
compartment. This was a harness representation discrepancy, not evidence of a
BNG3 graph-identity defect.

The next integrated-campaign slice preserves the 48-case baseline (18
PR-selected cases) and adds six generated semantic siblings to PR runs and
twelve to full runs. Three function-definition cases pass a rate through a
lambda formal named `rate` while a global `rate=7` is present and the analytic
rate remains `k=0.4`; three concentration-coordinate cases initialize
`N0/V`, use `hasOnlySubstanceUnits=false`, and express extent as `k*cell*A`.
Each sibling records its unchanged baseline case ID and transformation.
Generated SBML is checked with libSBML before results are attributed. Raw
source execution is compared in libRoadRunner against fixed closed-form
species coordinates using explicit selections (`A` for amount and `[A]` for
concentration); version, source SHA-256, RoadRunner model name and selections are retained.
BNG outputs are separately judged as item amounts/counts.
The existing Atomizer, BNG2, BNG3, PyBioNetGen, BNGIR, and NFsim routes retain
their ordinary reports and status classifications. Focused local checks cover
case generation, lineage, analytic coordinates, source-validation
classification, and required check IDs; no product build or scientific
campaign was run locally. This is partial detector evidence for function/rate
and quantity boundaries relevant to #143 and #151/#161; it does not establish
the shared rate-law contract, NFsim count-rate parity, structural
Atomizer/Multi qualification, or close any linked issue. CI still must execute
the generated cases, and embedded/native NFsim outcomes remain separately
classified rather than assumed supported.

## Integrated acceptance slices

A bounded repair does not close its broader issue.

| Issues | Merged PRs | Scope and remaining boundary |
| --- | --- | --- |
| #132 | #130 | Scoped constant/live assignment rates, XML rule parity and reporting repairs; exact-head installed BNG2 and all three platform corpus gates pass. Broader rate semantics remain open in #143. |
| #133/#173 | #190/#191 | Native-compiled static mass-action JAX ODE, fixed-step RK4; public JAX SSA explicitly unavailable. Installed CPU qualification satisfies these scoped issues; functional/time-dependent rates and adaptive integration remain unsupported. |
| #134 | #128/#204 | Combined parser grammar reuse, cardinality guards and pyparsing 3.0.9 fallback. Source-only shape/fallback checks pass; same-cardinality equality asymmetry remains pre-existing. |
| #135/#136 | #187/#189 | Current issue-linked ledger and corrected architecture/validation claims. Closed after review; historical reports remain historical. |
| #140 | #207/#220/#236/#241/#244/#248/#254/#257/#260 | Compile-owned numeric max_iter/max_agg, product filtering, finite ODE/SSA n_steps expressions, static numeric setParameter expressions, a bounded unlimited-stoichiometry correction, numeric-only static max_stoich compilation, strict full-input standalone expression parsing, preserved identifier spelling in scalar action expressions, and default-grid initial-state stop_if checking. PR #260 checks stop_if before the first output interval; it does not fix the separate explicit sample_times timing discrepancy. Dynamic parameter-backed arithmetic, functions/names, quoted numeric text, non-finite values, Safe-Perl caret semantics, general raw-option/typed-dispatch, sequential-action/default/entrypoint behavior, CLI/Python equivalence, invalid-option coverage and installed-package qualification remain open. Product-only limits preserve seed amounts, matching pinned BNG2. |
| #141/#142 | #203/#211/#222/#224 | Worker identity, graph-cache race repairs, compartmental seed association and exact species identity. Concurrent ODE instances with distinct rate snapshots have a shared-topology contract; serial scan exceptions restore base/dependent parameters and the original network before successful analytic/fresh-model recovery. Broader invalidation/lifecycle and graph encoding unification remain open. |
| #144/#145 | #200/#214 | Shared fail-closed BNGsim capability boundary, adapter ON/OFF agreement and scoped steady-state options. No default backend promotion; #145 closed. |
| #138/#163 | #196/#197/#228/#230/#233/#237 | Compile-owned units and version-aware SBML units; NET has an independent Network3 analytic consumer contract. Observable projection preserves graph-prefix context, counting modes, inert Molecules qualifiers and qualified Species CountUnique termination; #237 explicitly rejects unsupported Counter/Fraction kinds before opening the NET destination, without adding runtime support. Broader runtime migration/export qualification remains open. |
| #139 | #225; commits `c5ca62df` / `5a5bf0ba` | Compiler-owned direction-specific whole-deletion and typed DeleteMolecules hooks drive compatibility execution; full kernel retirement remains open. The previously recorded connected-context deletion discrepancy was repaired. The current `[issue139]` native regression passes 36 assertions, including rejection of bound product-only sites, preservation of free-site/state-change behavior, explicit bond breaks and DeleteMolecules partner release. This local regression is not a fresh independent BNG2 campaign or proof of broader graph equivalence. |
| #151 | #231 | Verified static zero-order physical count rates and bound parameter updates in one explicit positive 3D compartment. Physical XML fallback refuses; broader molecularity, unit seeds and dynamic contexts remain unsupported. |
| #143 | #201 | Typed ODE dependency classification and time/state reevaluation; broader backend scope, propensity and cache-invalidation criteria remain open. |
| #146 | #210/#215/#235/#238 | Deletion scope, pending waits, output clocks, canonical leading %label: XML scope and direct-NFsim compiled local-function binding. Independent native checks now cover four scoped cases; the original unmapped conditional remains unsupported, composite XML is not native parity, and the previously recorded strict native -oSteps final-endpoint failure is no longer current: the required endpoint step passed in push parity run [38852202284](https://github.com/RuleWorld/BNG3/actions/runs/38852202284) at the audited revision. This does not establish endpoint parity for every model. |
| #147/#148 | #219 | Whole-species DestroyComplex, same-complex matcher constraints and native index-width refusal. Runtime tests use an action adapter; production ActionIR execution and formal correspondence remain open. |
| #153–#155 | #209/#212/#213/#217/#226/#227/#242/#246/#247/#249/#250/#251/#252/#255/#256/#258 | Narrow parser-free BNGIR v0.2 import, strict model/action envelopes and boolean-reference rejection; seed-only zero-reaction models execute static ODE/SSA. Unknown model keys and unknown feature/protocol/action keys now reject, while string-valued action arguments and optional provenance remain accepted. Direct-builder malformed dense IDs, boolean references, unsupported top-level sections, unknown/non-string parameter properties, unsupported per-kind expression properties, boolean numeric nodes, wrong unary/binary arity, invalid `parameter_ref` symbol envelopes/kinds, non-finite numeric values, unsupported multi-pattern rules, and nonempty component/site payloads that would otherwise be discarded also reject; required parameter keys are diagnosed and optional `constant_value` remains accepted when finite. #251 adds one frozen v0.1-to-v0.2 migration fixture on the default Python route with pinned deterministic v0.2 output and schema/semantic checks. #255 repairs the Python integration test environment's missing `jsonschema` dependency after the #251/#252 bridge test failed during collection. #258 adds a narrow direct-native refusal guard for components and sites; it does not add site, bond, or population lowering. The generic expression/symbol schema remains broader than the direct-native subset. Broad structural round trips, deeper direct-native validation and independent C++ reader validation remain open. |
| #165/#166 | #194/#198 | All-input Lean reference matcher and bounded packing/native guards; #165 closed, production lowering correspondence remains open. |
| #169 | #192 | Proof trust accounting and harness qualification. Closed after review. |
| #171/#172 | #193/#208/#245 | Legacy positional run compatibility and defaults/version without optional Cement. PR [#245](https://github.com/RuleWorld/BNG3/pull/245) documents that `BIONETGEN_USE_PERL=1` selects the Perl path for Python API `bionetgen.run(path)` and `bionetgen.load(path).execute()`; the `bionetgen run MODEL` CLI is unavailable in this mode. The broad public matrix and legacy retirement remain open. |
| #182 | #199/#216 | Required numerical/expression/export and scheduled/manual frozen ensemble CI wiring, exact-source package/native/worker checks and permanent receipts; #182 closed. Scientific stochastic and historical NFsim qualification remain open. |
| #183 | #206 | Budgeted locked SSTS CI, per-case classifications/digests and permanent receipts. This bounded workflow issue is closed; full #159 qualification remains open. |

Root merged #187, #219, #206, #193, #208, #190, #191, the combined #128/#204 stack, and #220, #201, #222, #188, #224, #226, #227, #130, #228, #225, #231, #230, #233, #235, #236, #237, #238, static setter #241, BNGIR model-key guard #242, unlimited-stoichiometry slice #244, Perl API/CLI documentation #245, BNGIR action-envelope guard #246, BNGIR native parameter-key guard #247, numeric max_stoich slice #248, BNGIR native expression guard #249, BNGIR native symbol guard #250, the bounded BNGIR v0.1-to-v0.2 bridge fixture #251, the BNGIR finite-value guard #252, strict expression parsing #254, the BNGIR integration-test dependency repair #255, native rule-arity guard #256, scalar action identifier-spelling guard #257, direct-native component/site refusal guard #258, default-grid initial-state stop_if repair #260, and ledger refreshes #221/#223/#229/#232/#239/#253/#259 during this continuation.
PR #205 integrated the Rasi performance port separately. PRs #236, #241, #244 and #248 are merged, bounded #140
slices; the umbrella issue remains open. Work continues in isolated checkouts. Only root may
merge reviewed changes or close satisfied issues; no release publication is
authorized.

## Current qualification receipts

- Observable scope/counting #233: exact source `e03a750108330cf0f5434184db05bb741ac7c5e7`,
  merge `9bf28a0b0b89d30560f5920339101b2d5ef82de1`, tree
  `ccec8ad7c6ca6d38e8826d9972119601f187e80e`. Root/fresh Luna reviewed
  required candidate compartment context and per-term typed prefix IDs in the
  NET, C++ and regulatory graph writers. A prefix miss yields zero before
  Species predicates; qualified Species CountUnique stops even when false,
  matching pinned BNG2. NET groups reuse the compile-owned projection.
  Final clean-head cached Release validation: 11 native cases/93 assertions,
  count-filter contracts 2/18 and 18 strict exporter/NET round-trip/independent
  Network3 tests (37 deselected) pass. Architecture check passes with 41 explicit
  compatibility files. Inverting the prefix-ID comparison caused eight assertions
  in four cases to fail; restoring source returned all 93 assertions to green.
  CLI SHA256 `ed2a30a170860e6b74610d13c069de49a9631396b2b607ae464b1ec7f4caf35b`.
  Independent fixtures use pinned BNG2 `9601746` and locally source-rebuilt
  Network3 `9f39d22e`; the latter is not the separately locked binary artifact.
  At merge: five hosted successes, 12 in progress, one neutral and one skip;
  these are separate from local exact-head evidence. All-explicit-node coverage
  is a validity guard. Zero-count `<1` coverage uses the AST API; CLI grammar
  still rejects that form. Full generated solver consumption, installed package
  qualification and general compartment correspondence remain open. Outer AST
  dependencies remain; #138/#142/#163 stay open. The final #233 hosted Python
  matrix is red in 18 jobs across Python 3.9–3.14 on Ubuntu, macOS and Windows;
  the failures are the same Counter/Fraction `unknown compiled observable kind: At`
  error. The separate #235 PR-event [Linux Python 3.12 job](https://github.com/RuleWorld/BNG3/actions/runs/38152302145/job/114510215542)
  at exact head `b54ed0076166003b9f1a5c0af241b512a71e136d` reproduces the same
  two failures, with 1,142 passes, 58 skips and two xfails. Merged PR #237 adds the bounded fail-closed and destination-preservation
  behavior; its PR-head checks were absent after retargeting.
- Observable-kind fail-closed repair #237, merged
  [PR #237](https://github.com/RuleWorld/BNG3/pull/237)
  ([root review](https://github.com/RuleWorld/BNG3/pull/237#issuecomment-6113295483)):
  exact source `9561dd058519ce0d10f301bd56a1a752e167b1b1`, merge
  `e3dc33a4d272d621b2f969f1423253468f884a64`, base
  `eeb22cb4fed34a71f9ef11b904cf3963c2bfc981`, three files, tested tree
  `c4cc8d2a7655c54663c658935d4353c0aefb31a8`. Unsupported `Counter` and
  `Fraction` remain unsupported; NET now fails before opening the destination,
  preserving an existing file or leaving a missing output path absent. Root's
  restored source-mode qualification passed 36 Python tests (9 observable-type,
  27 BNGIR), 34 strict CLI tests (37 deselected), and 93 native projection
  assertions across 11 cases; the architecture scan found 41 explicit
  compatibility files. Inverting the unknown-kind predicate failed seven
  tests while two passed; restoring it returned the focused Python/native
  checks to green. PR-head hosted checks did not rerun after retargeting. At the
  2026-10-11 20:44:36 UTC query, merge commit `e3dc33a4` had Formatting
  patch, Lean semantic kernel, CodeQL and Cross-tool parity passed. Its CI run
  reported nine successes and 22 queued jobs, no failures, and remained queued
  overall ([run 38171605273](https://github.com/RuleWorld/BNG3/actions/runs/38171605273)).
  A 2026-10-12 exact-run refresh showed this e3 push completed with 39 successful jobs
  and one skipped job. That run predates PRs #238 and #241 and is not exact-current-main
  qualification. The #241 merge-push workflows are tracked separately below.
  This reports only the configured CI workflow on e3; it does not establish
  current-main qualification after #238/#241 or close #138.
- Local-function XML scope #235: exact source
  `b54ed0076166003b9f1a5c0af241b512a71e136d`, merge
  `bc952d4f76235d4710de9528a76505f99ccb664d`. The canonical leading `%label:`
  header is compiled as species-level local-function scope; XML binds both
  directions from checked scope metadata and refuses missing or ambiguous
  anchors. Restored focused qualification: NFsim adapter 138 cases/1,592
  assertions, XML writer 11/47, ODE options 23/132, projection 11/93, 18 strict
  exporter checks passed (37 deselected), and the architecture scan found 41
  explicit compatibility files. The review mutation failed two assertions before restoration. This covers
  the canonical prefix form only; installed packaging remains unqualified,
  and strict native `-oSteps` final-endpoint rows remain red. The final #235
  PR hosted-check aggregate at exact source
  `b54ed0076166003b9f1a5c0af241b512a71e136d` was 22 successes, 18 failures and
  7 skips. Run 38152302145 is that pull-request workflow; its [Linux Python
  3.12 job](https://github.com/RuleWorld/BNG3/actions/runs/38152302145/job/114510215542)
  reports 1,142 passes, 58 skips and two xfails, including the Counter/Fraction
  failures above. Full #146 remains open.
- C++ observable coefficients #230: exact source `bfbeeff497097da76539024b86d7055e0c01a99e`,
  merge `4795179ef16ae679d58e03e03444c28fc079b1fd`. Root/fresh Luna reviewed
  the shared-projection migration and repaired valid Molecules qualifier refusal:
  Molecules thresholds are inert in BNG2, while Species predicates stay active.
  Root preserved the unit artifacts and reused that cached build at the exact PR
  tree `1b1c0a5b00e00e0ac2ca3236cc72e5d7d28419ec`, avoiding another full build.
  Native projection 6 cases/49 assertions, existing ODE count-filter contracts
  2/18, strict live pinned-BNG2 exporter 10 tests and the architecture scan
  with 41 explicit compatibility files pass.
  CLI SHA256 `59dba6c49a93e8ed22569eeb1bf9f66f4d08ef710b43bbb9024fb9bcafb0d2c8`.
  Oracle inputs require the locked revision/script digest, clean tracked tree and
  no index-hiding flags; emitted coefficients match independent BNG2 group rows.
  At merge: three hosted successes and eleven pending checks. This is observable
  emission, not full generated CVODE solver consumption or general compartment
  correspondence. Outer AST dependencies remain; #138/#142/#163 stay open.
  NET groups were not qualified at that checkpoint; #233 supplies the bounded
  shared-projection repair above.
- CI wiring #182: root/fresh Luna accepted the existing #199/#216 implementation
  after [manual run 38076443040](https://github.com/RuleWorld/BNG3/actions/runs/38076443040)
  executed exact source `dfc4ba9cdefa62c96617d26ddba93151ef16b2be`.
  Installed source/git/expected head, package/native/model and worker identities
  verified on Linux Python 3.12.15; worker 1, assignment 32, live BNG2 network 5
  and required RHS/ODE/SSA determinism/export 60 tests pass. Three frozen
  200-member cohorts executed: two pass, michment fails with unchanged 10/306
  violations and worst |z|=9.344938257977688 at ScT. Both JUnit reports have
  zero skips/errors; the scheduled report explicitly records one failure.
  Native SHA256 `1965bfde6cc8269eaef95acb159033fd38f262e141f8f293496b6c25bbeecd8e`;
  CLI `a57825af859fc18a54245d38cd67c08fcad5132e1d69f9c8a6b00e216ac310ad`.
  The [permanent receipt](../tests/validation/evidence/issue182-parity-linux-py312-dfc4ba9.tar.gz)
  retains original JUnit, identity, limitations and four internal checksums;
  archive SHA256 `d4313dd1266d71646a0739ad492b461f4ad3af7aad1956f4f3535af8d124c999`.
  Overall workflow FAILED: historical NFsim also has three failures/three errors
  in 74 tests (v17 scoped-rate rejection, v19 parser errors, r21 statistics and
  empty-reference assertions). Source/oracle follow-up classifies v17 as a
  canonical leading `%x:` scope/serialization defect; v19 is malformed source
  accepted with a warning by BNG2; r42/r43 are missing XML input artifacts in the
  historical harness; r21 remains unresolved without retained trajectories. No
  seeds, retries, cohorts or thresholds changed. #182 closed for wiring with these reds retained;
  #146 and broader numerical qualification remain open. Later #231/#230 are
  excluded from this artifact, as is #233. #202's 14 provenance approval decisions stay pending.
- Physical units #231: exact source `4637d8e340c8fdc1004e3a7e8d6ce7de996d4fc1`,
  merge `35af757ae1143d1679d63317859b2b3220f18374`. Root/fresh Luna review
  repaired time/volume, capability/raw-lowering disagreement, aliases/mixed
  rates, geometry, parameter lifecycle, overflow and XML fallback admission.
  Final native adapter 136 cases/1,574 assertions, units 7/41, parser units 21/141,
  XML writer 8/32, forced-XML CLI gate and targeted source-mode Python checks pass.
  Root's guarded Python direct API returns [0,2,4,4] at [0,1,2,3], seed42;
  module SHA256 `09f57276889decb8f7fb9222b92eba7c4a9cbcb29cee80750cacfeb7f6c5f3d4`,
  CLI `37c9799ca223fd9899653ab2f426bfe7874a1d6df4602daacb22aa308e3cf789`.
  Fresh pinned BNG2 count-model XML `d0563b3a5bc38f1ac0079f9da57c7ae513ad666eee9ce1c6916d379dbcae9c4f`
  records rounded value=1.2044282, expr=1.204428152; pinned native NFsim explicit
  times agree with direct gdat SHA256 `cf9fe03790a4e6a249c6d4178d621e1aff9284e05acb081a5f716cda8d0bc5df`.
  Analytic native propensity asserts prove the conversion separately; this
  fixed-time agreement does not prove full stochastic or -oSteps equivalence.
  One explicit positive 3D-volume static zero-order subset only. Source-mode,
  not an installed wheel. At merge: five hosted successes, one neutral, one
  scheduled skip and 13 pending checks. Broader #151 remains open.
- Typed deletion #225: final synced source `0094dfe9f249fd6f2caa026d49006f980112258f`,
  merge `dfc4ba9cdefa62c96617d26ddba93151ef16b2be`. Root/fresh Luna review
  preserves #130's orphan guard. Final 19 native cases/276 assertions,
  architecture ratchet 41 and four fresh full-network comparisons against pinned
  BNG2 pass. Root independently regenerated both engines' networks; parameter,
  species/count and complete reaction/rate fields agree. CLI SHA256
  `6d1e38f74c821a8f185bbe39bbc8942bc754729f22f3b532065ac0b8d7e4a2af`.
  Final-head hosted snapshot: 41 successes, one neutral, five skips, no failures
  or pending checks. This migrates deletion decisions, not the full AST kernel;
  #138/#139 remain open.
- NET consumer #228: exact source `bd41199fbf08e4b484c4303f2ee6adc640bab829`,
  merge `0bf3a0446f46515b6ab09ed54d90f4e6fac228a4`. Root reviewed and reran
  the strict test on the tested #130 CLI against independent pinned-source Network3;
  one pass, 40 deselected. Local full export file: 33 passes, eight API/native skips.
  The local Network3 rebuild digest differs from the lock's binary artifact.
  [Exact-head installed parity](https://github.com/RuleWorld/BNG3/actions/runs/38074830773/job/114279587382)
  verifies source/git/PR head and package/native/model/worker identities; native
  SHA256 `b7897fcd2d20faf58c9eeefa412fa8f178b4fa32c6bbca4320d967483d6bc552`.
  Worker 1, assignment 32, network 5 and required parity/export 60 tests pass;
  three scheduled ensembles deselected. At merge: 17 successful checks, one
  scheduled skip and 22 pending platform/Python checks. Final exact-head snapshot
  has 41 successes and five skips, no failures or pending checks. No full #163 closure.
- Assignment/XML #130: exact source `5f2b5c1fd01d1bbeaa3a9bc9aa61a2393e0dae81`,
  merge `7f6b1969d369171064ff01e29ac4d5cb6d266996`; #132 closed after review.
  Local 32 assignment, 71 strict CLI corpus, five live pinned BNG2 network and
  106 comparator/CI contracts pass. Root read the exact-head installed
  [parity log](https://github.com/RuleWorld/BNG3/actions/runs/38053916751/job/114218464840):
  source/git/PR head agree; package/native/model and spawned worker identity
  verified, 32 assignment contracts, five original networks and 59 required
  parity tests pass. Three scheduled ensemble tests were deselected on the PR.
  Ubuntu, macOS and Windows each pass 71 corpus tests with no failures/errors/skips.
  Final exact-head snapshot: 42 successful checks, five scheduled/release skips,
  none pending. Linux Python 3.12.15 native SHA256
  `f6f88bcb95635727632bb6923ee296a4783a49a18685197f229295c85f953c86`;
  CLI `065a5f20ba90c40e19d0c03bae7b05d6218caddd2c46eb7d3dbaf4b83b84af70`.
  Scoped time ODE has analytic evidence where BNG2 only supplies a network oracle.
  Frozen michment and strict NFsim endpoint discrepancies remain open.
- Native BNGIR validation #227: exact source
  `25b12456eb012584da5752cca7d8eaa3e9e3b1eb`, merge
  `3accee429183a7f6c8a15e4f075daf1b25757233`. Root/fresh Luna review and
  four modules on a freshly built candidate native extension: 115 passes,
  two existing population-map xfails. Raw native calls reject boolean/invalid
  indices, duplicate/misordered IDs and nonempty known unsupported sections.
  macOS CPython 3.14 native SHA256
  `ed40bd2d54bc7c71f68f0c0754f6b9dda66578a66b95ca6c1c845cc71eb0b6c2`;
  source-mode qualification, not an installed wheel. Hosted jobs were pending
  at merge. Unknown fields/deeper nested validation and broader #155 remain open.
- Scan exception cleanup #224: exact source `18c4245eb394fd0c9537b06f5dacbbfa7c4941c2`,
  merge `c1210f170459444043edf1747b2c7d102c2745fc`. Root/fresh Luna review
  and root's guarded full scan suite passed all 11 tests. The runtime failure
  follows parameter mutation/cache clear; base and dependent parameters and exact
  network identity restore, then analytic/fresh-model trajectories agree.
- Seed-only BNGIR #226: exact source `e8c1dac8589f313fe7a5555ce39ae1209c2e477c`,
  merge `7536f6ae7dc6acb02a1b2134c589fafe7e01cc68`. Root/fresh Luna review;
  root reran four BNGIR modules: 91 passes and two existing population-map xfails.
  Import forbids parsing/rendering, preserves structural/semantic equality,
  generates one species/zero reactions, and executes static ODE/SSA trajectories.
  At least one seed and other malformed/unsupported gates remain required.
  Both slices used candidate Python with the recorded b842 native extension:
  source C++ b842 is byte-identical to their integration baselines (480/c121).
  Native SHA256 `620f40b6be5fcc40b71edee602188407c7bed6680b734bd7e24bd23c3aea17e5`.
  These are source-mode receipts, not freshly installed current-head artifacts;
  hosted jobs were queued/in progress at merge. Broader #141/#153/#154 remain open.

- Shared rates #201: exact source `b8428dc6fe1f8ebbdd3189ff430777c350abb9af`,
  merge `dbf1dac0faaf2b2cfdd65d09e1da54c80aae5ad3`. Focused ODE 22/120,
  compiler 124/2,572,270 and reaction-rule 14/239 tests passed, plus 75 verified
  source-mode Python backend tests. Root reran six live pinned BNG2 RHS items
  at the final source with cached goldens disabled and source=perl asserted.
  CLI SHA256 `8653f9283912719e3d6ff842a28e3975b362fb1ea5749c677277a56f6306da69`;
  native `620f40b6be5fcc40b71edee602188407c7bed6680b734bd7e24bd23c3aea17e5`.
  Final-head hosted native, Python, corpus, JAX and parity checks passed;
  release-only jobs were skipped. No full #143 closure.
- ODE reuse #222: merge `3118fa66a7fa33ebc066bd940ebac9f12e727faa`, test-only
  source `8d1d0005442c75acdab6867c896ae91f81419900`. Root verified b842 source
  cpp/python equals integration main dbf1, then ran all ten scan contracts with
  the proposed test on that verified runtime. A guarded file entry point passed;
  an earlier stdin launch failed worker startup and is excluded. The older
  installed source9712 receipt remains historical. This qualifies independent
  parameter snapshots sharing unchanged topology, not concurrent mutation,
  broader topology/volume invalidation, exception cleanup or NFsim lifecycle.
- CPython 3.14 full CPU suite and parallel-scan diagnosis: the run was launched
  from commit `ed49cfa3a6dc4144a20b26357f600cbef2b7899c` plus a frozen three-file
  #237 fail-closed patch. That patch content was later committed as source
  `9561dd058519ce0d10f301bd56a1a752e167b1b1` with tested tree
  `c4cc8d2a7655c54663c658935d4353c0aefb31a8`; the suite was not run from a clean
  checkout of that final source head. It reported 1,208 passed, 28 skipped, two
  xfailed and 10 failed. For eight subprocess tests, the global editable finder
  resolved package modules from the shared Anaconda installation at `07ea87d3`;
  those results do not qualify the source checkpoint. The other two failures
  occurred before worker startup because a stdin-launched pytest process could
  not be re-imported as `<stdin>` by multiprocessing. On the separate base-
  `e3dc33` plus two-file NFscope prototype, root reran those same two scan tests
  through a guarded file-based entry point without changing source, tests or
  tolerances: two passed, nine were deselected, in 0.63 seconds. Existing tests
  assert source/native/worker identity. The eight shadowed checks still need an
  isolated installed-package run; the full suite remains red and is not full-suite
  qualification for #237 or main.
- Direct-NFsim compiled local-function scope #238, merged
  [PR #238](https://github.com/RuleWorld/BNG3/pull/238)
  ([root review](https://github.com/RuleWorld/BNG3/pull/238#issuecomment-6113492546)):
  exact source `4566e38b33ed5536fbd758ef7d976a9f33d51629`, merge
  `af6afb00279a236031dc50afde452a6bfb913175`, base
  `e3dc33a4d272d621b2f969f1423253468f884a64`, tested tree
  `c7f058957666691f76df422404ce41bba9f196b0`. The code binds compiled
  local-function scopes to the intended molecule occurrences for direct NFsim.
  Final restored source-mode qualification passed 142 NFsim cases/1,621
  assertions, XML writer 11/47, ODE options
  23/132, observable projection 11/93, 36 Python tests, 34 strict CLI tests
  (37 deselected), and the architecture scan with 41 explicit compatibility
  files. The scope-inversion mutation produced two failures across 29 assertions
  while both control cases passed; restoring the candidate returned the focused
  checks green. The pinned independent native receipt passed four scoped cases
  (prefix, mapped M1, RP1 M2 and RP2 M2); M2/RP2 M2 also matched six exact
  seed-17 rows. The original unmapped conditional remains unsupported by native
  NFsim. The new composite direct test passes, but native NFsim rejects the
  same-source BNG2 XML with `ObservableRefinComposite` (exit 1), so that case
  is not an independent parity pass. During the 2026-10-11 20:49:40–20:49:44 UTC
  PR-head-associated check rollup for PR source `4566e38b33ed5536fbd758ef7d976a9f33d51629`,
  the rollup was 14 successes, 3 in progress, 1 neutral and 1 skipped ([PR checks](https://github.com/RuleWorld/BNG3/pull/238/checks)).
  A 2026-10-12 refresh of the same PR head showed 41 successes, five skips and
  one neutral check; the earlier in-progress snapshot is historical. This PR-head
  rollup remains separate from the later `ce441399` merge-push workflows.
  The separate main push at merge `af6afb00279a236031dc50afde452a6bfb913175`,
  checked during the 2026-10-11 20:49:40–20:49:44 UTC refresh, showed CI queued,
  CodeQL and Cross-tool parity in progress, and Lean semantic kernel passed
  ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38173018621),
  [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38173018637),
  [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38173018628),
  [cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38173018623)).
  No installed-package qualification is claimed; strict `-oSteps` final-endpoint
  rows remain red, and full #146 remains open.

- max_agg #220: exact source `ffd4043a8798dd20d708b26b1e370c6a294b371d`,
  merge `9a1de7ed7fb617df4cf8828748de45fac486e14e`. Root reviewed the five-file
  diff and reran five focused CTests. Four Python regressions passed in verified
  source mode; an earlier auto-mode run resolving an installed extension was
  excluded. Seven fresh probes against clean pinned BNG2 cover arithmetic,
  negative/fractional thresholds, seed/product filtering and empty products.
  Quoted numeric-prefix coercion stays explicitly unsupported. Direct Python
  max_iter/default behavior is preserved; no new max_agg API keyword. Hosted
  Linux C++, Lean, SSTS and compatibility checks passed at integration. All native
  C++/ASan/parity, Python and corpus checks subsequently passed; release-only
  jobs were skipped. No full #140 completion.
- Simulation n_steps #140, merged [PR #236](https://github.com/RuleWorld/BNG3/pull/236)
  ([merge review](https://github.com/RuleWorld/BNG3/pull/236#issuecomment-6113249716)):
  exact source `ed49cfa3a6dc4144a20b26357f600cbef2b7899c`, merge
  `eeb22cb4fed34a71f9ef11b904cf3963c2bfc981`, base
  `bc952d4f76235d4710de9528a76505f99ccb664d`. All five source files matched
  the restored green identity before the formatting-only commit. Static finite
  ODE/SSA actions use compiled, validated counts; parameter-backed expressions
  resolve after argfile merge and earlier
  protocol mutations; `^` is refused as Safe-Perl XOR. PLA/PSA/NF keep their
  existing path. Verified source-mode checks: 16 action regressions passed, C++
  reaction-rule expansion 23 cases/387 assertions, and architecture scan with
  41 explicit compatibility files; pinned BNG2 and candidate produce eight
  intervals (nine rows) for `2**3`, while the prior BNG3 baseline produced six
  intervals.
  The numeric-literal `2**3` result is the pinned-BNG2 parity case. Separately,
  a BNG3 execution-time protocol mutation to N=4 yielded 17 rows for `2**N`; this
  is a BNG3 regression/count result only, not dynamic-action parity against
  pinned BNG2. The separate dynamic-N probe exposes an unresolved unqualified
  Safe-Perl identifier boundary: pinned BNG2 leaves `k=1`, while BNG3 evaluates
  `k=8`; the 17-row result does not validate a 16-row expectation. The
  inverted-condition
  mutation failed focused assertions and the restored candidate passed. Pinned
  Black 26.10.0, Ruff 0.15.1 and the final local formatting checks passed. During
  the 2026-10-11 20:49:40–20:49:44 UTC PR-head-associated check rollup for source
  `ed49cfa3a6dc4144a20b26357f600cbef2b7899c`, the rollup was 21 successes,
  14 failures, four in progress, one skipped and one neutral; all 14 failing
  jobs were Python-platform jobs ([PR checks](https://github.com/RuleWorld/BNG3/pull/236/checks)).
  The Linux Python 3.12 job in run 38170926789 had exactly the Counter/Fraction
  failures, with 1,142 passed, 58 skipped and two xfailed ([job](https://github.com/RuleWorld/BNG3/actions/runs/38170926789/job/114565376022)).
  This pre-#237 hosted snapshot is not full-matrix qualification. This is a
  partial #140 slice; broader typed
  protocol values, shared CLI/Python semantics, defaults/invalid-option coverage
  and installed-package qualification remain open.
- Static numeric `setParameter` #140, merged [PR #241](https://github.com/RuleWorld/BNG3/pull/241)
  ([root review](https://github.com/RuleWorld/BNG3/pull/241#issuecomment-6116610037)):
  exact source `e16c159d34d9a756e8ca39ab468bc160807b998e`, merge
  `ce44139985582e53ee4b8191efdbcf0aa9e64340`, base
  `fd64bbc60c60f7e4bca498a900e774396571f20e`, tested tree
  `08c4c5825c6b3c4e71d0d974b8e5fb6936eeff10`. Compile-owned static numeric
  expressions now feed top-level and protocol action execution; `setParameter("k",2**3)`
  yields `k=8` in both. Cached Release, BNGsim adapter OFF: three focused CTests,
  rule expansion 25 cases/432 assertions, ODE 23/132, NFsim adapter 142/1,621,
  XML 11/47 and 84 selected Python tests passed. Independent pinned BNG2
  `9601746f8884ed19ab2acea49fe87fc4660ace46` agrees in both scopes on exact
  unique columns, all nine timestamps and observables; maximum absolute delta
  was `1.0009354456386177e-15` under the unchanged `2e-6` bound, and the analytic
  endpoint passes. Inverting the numeric gate reproduced `k=6` and failed the
  focused regression; restoration passed. CLI SHA256
  `827ecf921e788d03ce59db158d5dba150f33601387397f3f5a494c436dd210ad`; native
  SHA256 `b8e355152b68be34e15c48e1732f87a76dcbbc6298d102fd336a45e8bc03768b`.
  A normal source-mode Python float setter passed with package/native identity
  verified. This is not installed-wheel qualification: the premerge exact-head
  hosted snapshot had four successes, 13 in progress, one skipped and one
  neutral; pending checks were not validation. Dynamic parameter-backed arithmetic remains
  unqualified (the dynamic `2**N` result above is BNG3-only, not pinned-BNG2
  parity); full typed dispatch, shared CLI/Python defaults and broad #140
  acceptance remain open.
  In the 2026-10-12 02:29:17–02:29:23 UTC refresh, the current `ce441399`
  merge-push had Lean semantic kernel passed; CI, CodeQL and Cross-tool parity
  remained in progress ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38195519567),
  [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38195519559),
  [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38195519576),
  [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38195519562)).
  Those are hosted workflow states, not installed-wheel qualification.
- BNGIR unknown model properties #242, merged [PR #242](https://github.com/RuleWorld/BNG3/pull/242)
  ([root review](https://github.com/RuleWorld/BNG3/pull/242#issuecomment-6116694392)):
  exact source `49f8f396dc82e6c709d7616142e89df563352938`, merge
  `749dc464ad6e3430cc4f3c76c7a4b88a43fc7d9e`, base
  `ce44139985582e53ee4b8191efdbcf0aa9e64340`, tested tree
  `a9138bfed259b386d269f3b74e4fe309cc1e0acf`. This Python-only slice makes
  default-route reconstruction refuse unknown model properties before rendering
  or parsing; the allowed model key sets match the published v0.1 and v0.2
  schemas, and optional provenance remains accepted. The two focused regressions
  first failed on unchanged source, then passed; inverted model-key validation
  failed both, and restoration returned 88 BNGIR/native-import tests to green.
  Black and diff checks pass. The reused native module SHA256 is
  `b8e355152b68be34e15c48e1732f87a76dcbbc6298d102fd336a45e8bc03768b`; its C++
  subtree is identical to the compiled source from #241, so no rebuild was
  needed. Python module paths were asserted from the candidate checkout; this is
  source-mode evidence, not installed-wheel qualification. At root review, 14
  hosted checks were queued and one was in progress. Deeper nested action/object
  validation and broad scope/unit/energy/population/protocol round trips remain
  open; #154 and #155 remain open.
- Unlimited stoichiometry bounds #140, merged [PR #244](https://github.com/RuleWorld/BNG3/pull/244)
  ([root review](https://github.com/RuleWorld/BNG3/pull/244#issuecomment-6117118067)):
  exact source `73f517526956b6f9a8b00bb110d40fd5fcab08d6`, merge
  `cca53cd254aadec4dc39f52a0d76ece463425d45`, base
  `8b12e7e5ca7bc8970310635620c1eeb3595db7fe`, tested tree
  `8182a167e4f44075171a137826322a5724c3407f`. The unlimited sentinel skips
  only that molecule-type bound after outer trimming; a mixed finite A / unlimited
  B case preserves an over-limit A seed, filters A's channel, and generates B's
  channel. Four fresh controlled one-generation network cases match pinned BNG2
  `9601746f8884ed19ab2acea49fe87fc4660ace46` in species graphs, seed amounts,
  channels and numeric rates; final-head CLI reruns reproduce the same NET bytes.
  Six padded/internal-space quoted sentinel values are refused like pinned BNG2.
  Final source/native checks: 121 selected Python tests, reaction expansion
  28 cases/474 assertions, network 5/40 and three focused CTests; earlier affected
  ODE 23/132, NFsim 142/1,621, XML 11/47 and compartment 13/129 checks passed.
  The sentinel and whitespace mutations failed their expected regressions, and
  restoration returned checks green. CLI SHA256
  `ddcbb3b4e0026b582d6f9d22150d2a0da098a01f1c6be95dc4af999d11568a6e`; native
  SHA256 `3aba9bf257b2b59fc7e94df4efb0e6d4ddab315c5bff860ba71f5946f40ce66b`.
  Release source/native, adapter OFF; no installed-wheel claim. At root review,
  14 PR-head checks were queued at the 2026-10-12 03:18 UTC root review. At
  2026-10-12 03:19 UTC, the separate merge-push
  had four workflows queued ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38199225815),
  [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38199225796),
  [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38199225787),
  [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38199225786)); pending
  jobs are not validation. This is bounded one-generation parity, not unrestricted
  growth. At the #244 checkpoint, numeric `max_stoich` expression-prefix/negative-wrap
  handling remained assigned; #248 subsequently covers those cases within its
  supported finite numeric class. Broader
  typed-protocol/default/API criteria and #140 remain open.
- Perl API/CLI boundary #171, merged documentation-only [PR #245](https://github.com/RuleWorld/BNG3/pull/245)
  ([root review](https://github.com/RuleWorld/BNG3/pull/245#issuecomment-6116911488)):
  exact source `662987b66c7fbb3bf4d0705c881d0ba4a8f2fe26`, merge
  `1f20e1cac12dcf11cc6bd38404ce947c1b7f1a5f`, based on
  `749dc464ad6e3430cc4f3c76c7a4b88a43fc7d9e`. The reference now limits
  `BIONETGEN_USE_PERL=1` to Python API calls `bionetgen.run(path)` and
  `bionetgen.load(path).execute()` and states that `bionetgen run MODEL` is
  unavailable in this mode. Source-mode reproduction at the base used pinned BNG2
  `9601746f8884ed19ab2acea49fe87fc4660ace46`, an XML-only fixture, and asserted
  package/legacy-runner paths: the API produced XML and preserved verbose output
  and nonzero Perl stderr; the CLI exited 1 without XML or invoking Perl. A larger
  fixture requires unavailable `run_network`; no NET/ODE or installed-package
  qualification is claimed. At 2026-10-12 02:55 UTC root review, 13 hosted jobs
  were queued; they are not validation. The broader #171 API/installed-CLI matrix
  remains open.
- BNGIR feature/protocol/action envelope #154/#155, merged [PR #246](https://github.com/RuleWorld/BNG3/pull/246)
  ([root review](https://github.com/RuleWorld/BNG3/pull/246#issuecomment-6117020055)):
  exact source `a3c0243bef3eb448b67c755de94cad3d246a8bbf`, merge
  `8b12e7e5ca7bc8970310635620c1eeb3595db7fe`, base
  `1f20e1cac12dcf11cc6bd38404ce947c1b7f1a5f`, tree
  `bf08aee93e3b4b769a770222e39f49bb738aaa61`. In two Python files, the default
  route now rejects feature/protocol/action properties outside the v0.1/v0.2
  contracts while preserving arbitrary string-valued action arguments and optional
  provenance. Root reproduced six tests RED on unchanged source, then GREEN96
  BNGIR/native-import tests; each guard mutation failed its focused cases and
  restoration passed 96 again. Black/diff checks and fresh independent Luna review
  passed. Package paths and the reused native module were asserted; its SHA256
  `b8e355152b68be34e15c48e1732f87a76dcbbc6298d102fd336a45e8bc03768b` is from
  #241's identical C++ subtree. No rebuild or installed-wheel qualification is
  claimed. The separate native route still refuses nonempty protocol actions.
  At the 2026-10-12 03:07 UTC premerge root review, the PR-head snapshot had five
  successes, three in progress, ten queued, one skip and one neutral. At
  2026-10-12 03:19 UTC, its merge-push had
  Formatting passed, CodeQL in progress, and CI, Lean and Cross-tool queued
  ([Formatting](https://github.com/RuleWorld/BNG3/actions/runs/38198505877),
  [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38198505879),
  [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38198505903),
  [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38198505880),
  [CI](https://github.com/RuleWorld/BNG3/actions/runs/38198505912)). These snapshots
  are not a complete matrix. Deeper node properties, direct-native nested
  validation, independent C++ reader validation and broad semantic round trips
  remain open; #154 and #155 remain open.
- Direct-native BNGIR parameter-property guard #155, merged [PR #247](https://github.com/RuleWorld/BNG3/pull/247), source `bd001c328c8aa920abb2d1c06258c228a3d48abd`, merge `5cd3782c875628aac8272702c7ccdb49e7d3207c`, based on main `44fc050f4324fd955e0dff3ddad59bc4815e0d3b` ([root review](https://github.com/RuleWorld/BNG3/pull/247#issuecomment-6117423886); [issue receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6117426430)): the raw v0.2 C++ import rejects unknown/non-string parameter properties, diagnoses missing required keys, and accepts optional `constant_value`. The contract matches the published schema: `id`, `name`, and `expression` are required; `constant_value` is optional; other properties are forbidden. Missing `expression` already raised `KeyError` before the patch; unknown fields were silently discarded. Root's baseline probes gave two expected failures and two valid controls; the published head passed 129 tests with two existing xfails across all four BNGIR modules. A guard-bypass mutation produced one failure with 62 tests deselected; restoration returned 129 passes/two xfails. Architecture passed 1/1; Black, Ruff and diff checks passed. Source/native paths were asserted; native SHA256 `2b88a5f5883ebc1a24248a2e69c7560b5570f3027c119607a057e5528fc82b9e`, built from root cache in Release with Python ON and adapter OFF. The PR's premerge snapshot had 15 hosted checks queued; local source-build evidence does not qualify an installed wheel or the full native schema. At 2026-10-12 14:50:02 UTC, the PR-head-associated check rollup showed 42 successes, five skips and one neutral check, with no failures or pending jobs ([PR checks](https://github.com/RuleWorld/BNG3/pull/247/checks)). The Linux Python 3.12 job in that rollup ran synthetic merge `03846628c8354883eb7010b89e4b06dac21a315e`, not the literal PR source commit; GitHub's commit API verified both trees equal `8be860ee89948cd13f79c0811918d8814bfd78ff`, and the job identity recorded the PR head. Its installed native module SHA256 was `0a4010261600fa1c12087b0b0ca2549d9ead6c00f386e0a5869ab67661ee86bc`; its Python suite passed 1,160, skipped 58 and had two existing xfails ([job](https://github.com/RuleWorld/BNG3/actions/runs/38201409922/job/114666782886)). This is identical-content synthetic-merge validation, distinct from literal source-commit execution ([identity receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6126659735)). At the #247 checkpoint, no test crossed a frozen v0.1 import into deterministic, schema-valid v0.2 output; merged [PR #251](https://github.com/RuleWorld/BNG3/pull/251) subsequently added one bounded default-Python bridge fixture (receipt below). Generated adversarial references, deeper nested validation and broader migration/round-trip coverage remain open; #155 stays open.
- Numeric-only `max_stoich` compilation for #140, merged [PR #248](https://github.com/RuleWorld/BNG3/pull/248) ([root review](https://github.com/RuleWorld/BNG3/pull/248#issuecomment-6125666025); [issue receipt](https://github.com/RuleWorld/BNG3/issues/140#issuecomment-6125677878)): exact source `73aaf3edacd6a91debbd27d449a2b508307ce231`, merge/main `48a980c7c61b39e6ae2d70355c8156767b618f8c`, tested tree `72cf2959c34052142f67a33c9ba3fbccf88fb034`, based on `5cd3782c875628aac8272702c7ccdb49e7d3207c`. The Release source build used Python ON and adapter OFF; CLI SHA256 `52c12a9d57525ce4ea24a219c4e00d93b60a8f9e7b1b10e466d91771f47515fb`, native SHA256 `4954e1bca74e150313c3797f146d2780a21844b0f37d3bc5e85c0350f9f3f329`; no installed-wheel claim. The change compiles ordered nested-map values through a finite static numeric-expression subset, preserves the existing first-supplying-action behavior, and defers unsupported syntax as a generation diagnostic. Nine bounded pinned-BNG2 cases matched exact graphs, amounts, channels and rates where BNG2 emitted NET; zero-reaction cases are classified separately because BNG2 refuses empty NET, and both engines refuse division by zero without writing NET. The scope suite passed 35 reaction-expansion cases/532 assertions, 5 network cases/40 assertions, ODE 23/132, NFsim 142/1,621, XML 11/47, 212 Python tests with two existing xfails, and three CTests. A two-case lexer/key-guard mutation failed nine assertions; restoring the source returned the focused suites green. A 2026-10-12 14:10:14–14:10:17 UTC PR-head-associated check-rollup refresh showed 21 success, four in progress, 15 queued, one skipped scheduled NFsim job and one neutral CodeQL check, with no failures ([CI run 38258590951](https://github.com/RuleWorld/BNG3/actions/runs/38258590951)). Dynamic parameter-backed arithmetic, functions/names, quoted numeric text, non-finite values, caret syntax, general raw-option/typed-dispatch, and broader sequential-action/default/entrypoint/CLI-Python semantics remain unsupported or unqualified. Product-only limits preserve seed amounts as pinned BNG2 does; #140 stays open.
Pending `setParameter` caret review: the unpublished candidate's quoted path bypasses the static arithmetic guard and is not qualified. A later proposed caret slice also failed late-bound `N` dependency retention and non-finite-result checks; its helper correction remains in progress before admission. Root's probe against pinned BNG2 `9601746f8884ed19ab2acea49fe87fc4660ace46` found `-2^N` logs 16 while its native NET trajectory implies -16; BNG3 currently evaluates parsed `(-2)^N` as +16. Merged [PR #254](https://github.com/RuleWorld/BNG3/pull/254) now rejects lexer errors and trailing tokens through the shared full-input expression parser, but it does not settle Safe-Perl caret/XOR semantics or qualify the setter path. Keep caret arithmetic refused pending semantic resolution; this is not a parity or support claim.
- Direct-native expression guard for #155, merged [PR #249](https://github.com/RuleWorld/BNG3/pull/249) ([root review](https://github.com/RuleWorld/BNG3/pull/249#issuecomment-6125817751); [issue receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6125824783)): source `d955516f0e61b414bdfc891ddb3c71553620c2f6`, merge `f3a8a0f367d7b8dbb6035b6ef324e10a4f26b369`, tested tree `181f8c3f6641b1ab7f1b4a6cc979ff5c671c59b7`, based on `48a980c7c61b39e6ae2d70355c8156767b618f8c`. The raw C++ importer rejects unsupported per-kind expression properties and boolean numeric values recursively, and checks exact unary/binary arity before indexing. Extra children were previously dropped; empty arity already raised `IndexError`. Public `native=True` already refused these malformed documents in Python, so this qualifies the separately callable raw C++ boundary. The positive nested parameter-reference/arithmetic control has hand-derived derivatives dA/dt=-20 and dB/dt=20. Baseline and guard-bypass probes produced eight refusal failures and one valid control; final source passed 221 tests with two existing xfails and mutation restoration returned the same result. Architecture 1/1; formatting and diff checks pass. The fresh Release Python-on/adapter-off native SHA256 was `24962dd7ff2944e7be8a7def2a0b314a5ec7d0f094771634f6e14520f9d96ca4`; this is source-build evidence, not an installed wheel. The PR's premerge snapshot had three successes, eight in progress, eight queued and one skip. A later 2026-10-12 14:10:14–14:10:17 UTC PR-head-associated query showed 15 successes, three in progress, 22 queued, one skip and one neutral, with no failures ([PR checks](https://github.com/RuleWorld/BNG3/pull/249)). The schema still admits a broader expression shape than the native subset; PR #250 subsequently covers parameter-reference symbol keys and kind. At the #249 checkpoint, finite-number checks remained open; merged [PR #252](https://github.com/RuleWorld/BNG3/pull/252) subsequently adds a bounded direct-native finite-value guard (receipt below). Deeper contracts and full #155/#154 criteria remain open.
- Direct-native `parameter_ref` symbol guard for #155, merged [PR #250](https://github.com/RuleWorld/BNG3/pull/250) ([root review](https://github.com/RuleWorld/BNG3/pull/250#issuecomment-6126008923); [issue receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6126015622)): source `f4c209cebc56d7f2aaca0a1debccd3f8e884f3f4`, merge/main `1eb960c03ff536709d182edf1aac0773c2dc93e0`, tested tree `90cca79a2879cd75cac8109aad29a2ed328e1588`, based on `f3a8a0f367d7b8dbb6035b6ef324e10a4f26b369`. The direct C++ reader requires `parameter_ref.symbol` to contain exactly `kind` and `index`, with string `kind == "parameter"`, before unchanged index validation. Wrong/missing/non-string kinds and extra semantic properties were previously accepted or discarded. The generic published schema admits broader symbol kinds; this guard enforces only the native subset. Root reproduced four refusal failures and two supported-model controls on the unchanged reader; bypassing the validator reproduced all four failures while both controls passed. Final published-head validation passed 225 tests with two existing xfails; restoration returned the same result. Architecture 1/1, Black/Ruff and diff checks pass. The fresh Release Python-on/adapter-off native SHA256 was `41a294490efcfa8033eb59d3e9157b1b045a5a30802fb011d032212e1f142157`; this is source-build evidence, not an installed wheel. At the 2026-10-12 14:12:55–14:13:02 UTC PR-head snapshot, five checks succeeded, three were in progress, ten queued, one scheduled NFsim job was skipped and CodeQL was neutral; no failures were reported. The separate merge-push snapshot for `1eb960c` showed Formatting passed, Cross-tool parity in progress, and CI, CodeQL and Lean queued ([Formatting](https://github.com/RuleWorld/BNG3/actions/runs/38261140828), [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38261140745), [CI](https://github.com/RuleWorld/BNG3/actions/runs/38261140870), [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38261140525), [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38261140737)). This remains bounded source-build qualification. At the #250 checkpoint, finite-number checks remained open; merged [PR #252](https://github.com/RuleWorld/BNG3/pull/252) subsequently adds the bounded direct-native finite-value guard. #155 stays open for other nested objects, generated references, version migration, independent C++ reader coverage and broader round trips.
- BNGIR v0.1-to-v0.2 bridge fixture for #155, merged [PR #251](https://github.com/RuleWorld/BNG3/pull/251) ([root review](https://github.com/RuleWorld/BNG3/pull/251#issuecomment-6126193996); [issue receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6126205185)): exact source `d9d4afebf49b9801e3841e03e8dbbb62b3a28b68`, merge/main `c5d45016ec48f4eeec358aa98345d26b9b5e9321`, tested tree `22a5476ef9119bc879a4aa4547255dcf3ef515fa`, based on `1eb960c03ff536709d182edf1aac0773c2dc93e0`. The default Python route now has one frozen v0.1-to-v0.2 bridge contract: the fixture specifies `k=0.1`, `A(x)` states `u/p`, seed `A(x~u)=10`, and one `u→p` conversion at rate `k`. The test checks both fixture schemas, hand-checks typed semantic fields, pins the canonical UTF-8 v0.2 export bytes, reparses that document and checks semantic equivalence and identical re-export. `jsonschema` is an explicit development dependency used in the existing Python CI environment; direct import makes a missing dependency fail with `ModuleNotFoundError` instead of silently skipping the contract. Root's selected Python backend, four BNGIR modules, bridge, and workflow/CI contract tests passed 301 tests with two existing xfails. Changing the exported seed amount from 10 to 11 failed the pinned-wire assertion; a fresh unchanged process passed after restoration. The C++ subtree is unchanged; the reused native SHA256 is `41a294490efcfa8033eb59d3e9157b1b045a5a30802fb011d032212e1f142157`, and source/package/native paths were asserted. The 2026-10-12 14:22:37 UTC root review's premerge PR-head snapshot had two successes, one in progress and 12 queued; queued checks are not validation. This is source-mode default-Python evidence, not installed-wheel, raw-native-reader or full #155 qualification. #155 remains open for broader migration and round-trip coverage, direct-native C++ reader validation and deeper generated adversarial cases.
- Direct-native finite-number guard for #155, merged [PR #252](https://github.com/RuleWorld/BNG3/pull/252) ([root review](https://github.com/RuleWorld/BNG3/pull/252#issuecomment-6126649862)): exact source `abc0d00796bfa046839aa60a637b10c939977cd3`, merge/main `3890557995ab9615dd3833a98f0222275315601a`, tree `518243e503c302c78cc368945244f920b962bcb9`, based on `c5d45016ec48f4eeec358aa98345d26b9b5e9321`. The raw native importer now rejects booleans, non-numeric values, integer overflow and non-finite doubles recursively in numeric-expression leaves and for an optional parameter `constant_value`; omission remains allowed, as do finite integer, zero and negative values. The public `native=True` Python route already enforced finite values, so this qualifies only the independently callable C++ boundary. The oversized expression value was already rejected by pybind conversion; the oversized optional constant had been ignored. Baseline probes produced 16 invalid-value refusal failures and 12 finite controls; a mutation bypassing only `std::isfinite` failed 12 invalid-value assertions while 16 controls passed. The restored exact source passed 329 selected tests with two existing xfails across the Python backend, BNGIR/new bridge and workflow/CI contracts. Architecture passed 1/1; Black, Ruff and diff checks passed. Source/package/native paths were asserted; the fresh Release Python-on/adapter-off native SHA256 was `8c6da161c6d12dc1fcc8e021ec8e6694e288ebdb81fff379cb60371c5b169718`. This is source-build evidence, not installed-wheel qualification or complete native-schema validation; arithmetic-domain/result validation, broader native graph/rule shapes, generated references and full #155/#154 acceptance remain open. At the 2026-10-12 14:54 UTC refresh, #252 PR-head checks showed seven successes, five in progress, six queued, one skipped and one neutral; the separate merge-push had Formatting and Lean passed while CI, CodeQL and Cross-tool parity were queued ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38265725222), [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38265725269), [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38265725256), [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38265725345), [Formatting](https://github.com/RuleWorld/BNG3/actions/runs/38265725347)). This partial hosted snapshot does not expand the scope claim; #155 remains open.
- Strict standalone expression parsing for #140, merged [PR #254](https://github.com/RuleWorld/BNG3/pull/254) ([issue receipt](https://github.com/RuleWorld/BNG3/issues/140#issuecomment-6132177836)): exact source `6b27357d65e5089540bf041f09ac9f2e26b50ae3`, merge `304d928abfe012db7196ebb97e0a087b86987b06`, based on `3890557995ab9615dd3833a98f0222275315601a`. The shared standalone expression parser now refuses lexer errors, parser errors, null expressions and trailing tokens instead of accepting a valid prefix. Baseline and guard-bypass probes each failed both malformed-expression refusal assertions. The restored Catch suite passed 20 cases/100 assertions; affected expansion 35/532, ODE 23/132, NFsim 142/1,621, XML 11/47, symbol 1/2 and three focused CTests passed. Selected Python/BNGIR/workflow tests passed 329 with two existing xfails; source/package/native paths were asserted, Release Python ON and adapter OFF, native SHA256 `4316c217cbb00848dfdcc88a6c3aae2cd7ff87bdc31e4f1ba9351cd5aec1cb02`, CLI SHA256 `602f70b1c062dcb07cfc9ecba1afb0e1908e690e6d48c6c492ed435bb8abe3e5`. Pinned BNG2 and that tested CLI match the 41-row TFUN fixture exactly. For valid `stop_if=>"2^N"`, BNG2 stops at the initial row and the tested BNG3 CLI stops after the first step; this runtime timing gap remains open. The expression parser change does not qualify installed wheels, whole-model lexer validation or every expression-construct semantics.
- BNGIR integration collection dependency repair, merged [PR #255](https://github.com/RuleWorld/BNG3/pull/255) ([issue receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6132214020)): literal source `fa1cd20258f467a6f1d728f554fbd8df7d4326db`, merge `9c5ca01dea620374670bfa3f9681828a8595cf6f`, based on `304d928abfe012db7196ebb97e0a087b86987b06`. The Python integration job now installs the `jsonschema` test dependency required while pytest imports the v0.1-to-v0.2 bridge module during collection; a workflow contract enforces that setup. Before the repair, PR-head-associated snapshots for #251 and #252 each showed 41 successes, five skips, one Integration Tests collection failure and one neutral result. Both failed because `jsonschema` was absent ([#251 job](https://github.com/RuleWorld/BNG3/actions/runs/38261840335/job/114888742725), [#252 job](https://github.com/RuleWorld/BNG3/actions/runs/38264568073/job/114890789843)); these are historical collection failures, not scientific or installed-artifact results. The new workflow regression failed on the old workflow (one failure/59 deselected); after the repair, 76 CI/workflow contracts passed locally. This does not add production dependencies or BNGIR semantic support. The 2026-10-12 21:00:28–21:00:32 UTC check query was a pending snapshot; it was superseded when run [38305336672](https://github.com/RuleWorld/BNG3/actions/runs/38305336672) completed successfully at 22:49:17 UTC. Its `Integration Tests` job [115026547938](https://github.com/RuleWorld/BNG3/actions/runs/38305336672/job/115026547938) recorded PR head `fa1cd20258f467a6f1d728f554fbd8df7d4326db` but installed/tested synthetic merge `18fc5b3fe6719cbfefa43046092fa281a56b3e1e`; that synthetic tree `cb6349c0d358482e3744e9e44f21ff3309be3be0` matches the final merge tree, while the literal head tree is `97f0d85d56f2e8499bb893148a5042e85a6eb71f`. The Python 3.12 installed package, model and native extension resolved under `site-packages`; built wheel SHA256 `915a4c6bd3917d230e085fb448ab494391679528694e592435f387167bc761bf`, native extension SHA256 `8fdab47306d8c250d827448365550310838866eb6da253e435c970577ad6b6d6`. Selected tests passed: Atomizer 465/27 skipped/779 deselected; model loading 72/18 skipped/1,181 deselected; workflow contracts 16; CLI smoke and 101-point simulation passed. The separate sdist smoke job also succeeded. This is installed validation of the synthetic tree identical to merged content, not literal PR-head execution; the #155 acceptance criteria remain open.
- Direct-native rule-pattern cardinality guard for #155, merged [PR #256](https://github.com/RuleWorld/BNG3/pull/256) ([issue receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6132301130)): exact source `1675848d4e7ac3c9bf48c7facb6571bfe7e72de9`, merge/main `07dc6ed20cbd5803609c58759bf7da4286ce43ab`, based on `9c5ca01dea620374670bfa3f9681828a8595cf6f`. The direct reader now requires exactly one pattern on each rule side before indexing; it previously read only the first pattern and silently discarded extras, and empty sides also fail the new guard. Baseline had four refusal/diagnostic failures and two valid controls. Final published-head source validation, including the #255 CI contract, passed 334 tests with two existing xfails. Architecture 1/1, Black/Ruff/diff checks and exact package/native identity passed; Release Python ON, adapter OFF, native SHA256 `21f21aef12f4d51166f8c2a0a2398a6bacc7f54dc80ccd896c3352f01830b49e`. This is bounded source-build validation, not installed-wheel, full-schema or independent C++ reader qualification; #155 remains open.
- Dated main merge-push snapshot at #256: the 2026-10-12 20:51:32–20:51:36 UTC query window for `07dc6ed20cbd5803609c58759bf7da4286ce43ab` showed Formatting and Lean semantic kernel passed; CI, Cross-tool parity and CodeQL were queued ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38306203491), [Formatting](https://github.com/RuleWorld/BNG3/actions/runs/38306203496), [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38306203524), [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38306203557), [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38306203575)). This is a dated partial snapshot, not current-main hosted qualification.
- Scalar action identifier spelling for #140, merged [PR #257](https://github.com/RuleWorld/BNG3/pull/257) ([root review](https://github.com/RuleWorld/BNG3/pull/257#issuecomment-6132383057)): exact source `171fe7c7c35165b5b1c5baf506d29b7b95530135`, merge `b28a2ae012f0bf4505efe4d0a7cf72b72c40c2a2`, based on `07dc6ed20cbd5803609c58759bf7da4286ce43ab`. The scalar `setParameter` expression path now preserves identifier spelling; D/d-to-E/e normalization remains confined to numeric literal tokens. This prevents compound identifiers such as `Nd`/`D` from being rewritten to `Ne`/`E`. The baseline CLI mismatched six Nd/D cases spanning top-level and protocol actions; Ne/E and standalone `1D-3` controls passed. Pinned BNG2 `9601746f8884ed19ab2acea49fe87fc4660ace46` gave the expected 8, 5 and 4 values for the qualified cases; combined `1D-3*Nd` remains unqualified because pinned BNG2 generates NET but downstream `run_network` fails. Final source validation passed five focused CTests, expression 20/100, expansion 35/532, ODE 23/132, NFsim 142/1,621, XML 11/47 and 334 selected Python/BNGIR/workflow tests with two existing xfails. Architecture 1/1, diff checks and source/package/native identity passed; Release Python ON, adapter OFF, native SHA256 `71e4a2b3aa5d6f69666f19c9bb3a16c0982ea514a9286e6b1b105204ecf54789`, CLI SHA256 `2a0ee0131c78dae2b24fe5f9b3f5c1e15f365a53417dd9681cf24daf991a5e3b`. This is bounded source-build validation, not all action-language/default/entrypoint behavior or installed packaging. At the 2026-10-12 21:00:28–21:00:32 UTC PR-head-associated check snapshot, four checks succeeded, one scheduled NFsim check was skipped, two were in progress and 11 queued; no failure was reported. #140 remains open.
- Direct-native component/site refusal for #153/#155, merged [PR #258](https://github.com/RuleWorld/BNG3/pull/258) ([root review](https://github.com/RuleWorld/BNG3/pull/258#issuecomment-6132448888)): exact source `1f37ff45b865d54cbc87fdb6ac060add585a02c0`, merge `e13ed95c0080a383099c208cc2e1b2de96c0a2c5`, based on `b28a2ae012f0bf4505efe4d0a7cf72b72c40c2a2`. The raw C++ importer accepted site-bearing models but discarded component definitions and molecule sites, changing structures such as `A(x~u)`/`B(x~p)` into `A()`/`B()`. It now refuses nonempty site data at seed, forward-reactant and forward-product pattern boundaries and refuses components before model construction; the public `native=True` path already rejected this semantic class. Baseline had four refusal failures and two supported empty-component/site controls. Final source validation passed 338 selected Python/BNGIR/workflow tests with two existing xfails; architecture 1/1 and Black/Ruff/diff checks passed. Release Python ON/adapter OFF, source/native paths verified, native SHA256 `6bf4f11acdf522f2726892d0ed27b966694c1296568ea4f4d791374d095fc1aa`. This is source-build refusal qualification, not installed packaging, component/site/bond/population lowering, full schema validation or independent C++ reader coverage. At the 2026-10-12 21:00:28–21:00:32 UTC PR-head-associated check snapshot, one check succeeded, one was in progress and 13 were queued; no failure was reported.
- Default-grid initial-state `stop_if` for #140, merged [PR #260](https://github.com/RuleWorld/BNG3/pull/260) ([issue receipt](https://github.com/RuleWorld/BNG3/issues/140#issuecomment-6132800760)): exact source `3a353c76e5bc86becf2d5934c0c944790a6d5dab`, merge/main `3ec99904afed69631808556c5646fed99328bb26`, based on `811e772d369f61ca92c32af19e5f0a558ec298fc`. On the default output grid the simulator now checks the initial state before advancing; CVODE evaluates the original state at that point to avoid a scale/unscale threshold flip, and SSA keeps the initial row without consuming an event when already stopped. The exact-source Release build used Python ON and adapter OFF; all 509 tracked C++ files and the four changed files matched the published source, with C++ tree `d1e9af9bc5cdbed0ac66d5f74e027943edd5b717`, native SHA256 `412a78fcf2cfa6ada657d6fac5487fecd9359919955e6ef5eec96bc531538676`, and CLI SHA256 `5d8dad626b1ee715bbf91e0b0d51868f23739b77e7939660d96fefba8c2a8e69`. Six focused CTests passed; native expression 20/100, expansion 35/532, network 5/40, ODE 23/132, NFsim 142/1,621, XML 11/47, and 338 selected Python/BNGIR/workflow tests passed with two existing xfails. Seven default-grid probes matched pinned BNG2 `9601746f8884ed19ab2acea49fe87fc4660ace46` in rows, times and initial states; six full matrices were identical, with a maximum threshold-case absolute delta of `3.7297e-16` (BNG3 CVODE versus BNG2 ODE adapter). A scaled-CVODE-state mutation failed only the threshold regression; restoring the original-state check passed. No Euler/RK4 or zero-species parity claim is made. The corrected explicit `sample_times=>[0,0.25,1]` fixture remains different: BNG3 returns two rows while BNG2 stops at the initial row. The separate PR-head-associated installed `Integration Tests` job `115051915226` succeeded on run [38309302624](https://github.com/RuleWorld/BNG3/actions/runs/38309302624), testing synthetic merge `6a6854dac422431e4bf07e0e96022c09296146c3` against recorded PR head `3a353c76e5bc86becf2d5934c0c944790a6d5dab`; both trees and merged main share `cd18d2682d8c62216e247e74045f415252d74421`. The installed Linux CPython 3.12 wheel/native SHA256 values are recorded in the [#155 receipt](https://github.com/RuleWorld/BNG3/issues/155#issuecomment-6137699903); selected atomizer/model/workflow tests, CLI smoke and the 101-point run passed. This is identical-content synthetic-merge installed validation, not literal PR-source execution; the selected installed tests and generic CLI smoke do not exercise `stop_if`, so feature-specific installed qualification remains open. The PR-head-associated run completed with 33 successful jobs and four skips; release-artifact/wheel and scheduled NFsim jobs were skipped ([run](https://github.com/RuleWorld/BNG3/actions/runs/38309302624)). Main merge-push run [38309918922](https://github.com/RuleWorld/BNG3/actions/runs/38309918922) started at 2026-10-12 21:19:36 UTC and completed at 2026-10-13 02:03:08 UTC, with 39 successful CI jobs and one skipped; its CI, Lean semantic kernel, CodeQL and Cross-tool parity runs succeeded ([CI](https://github.com/RuleWorld/BNG3/actions/runs/38309918922), [Lean](https://github.com/RuleWorld/BNG3/actions/runs/38309918917), [CodeQL](https://github.com/RuleWorld/BNG3/actions/runs/38309918956), [Cross-tool](https://github.com/RuleWorld/BNG3/actions/runs/38309918876)). These results do not close #140 or qualify the broader action language, explicit-grid behavior, full installed-package surface, frozen stochastic behavior or NFsim endpoint rows.
- Parser #128/#204: combined source preview on main `f4adb7b7` passed 68 parsed
  field/text comparisons against baseline on actual pyparsing 3.0.9 and 3.3.2;
  root independently reran 68 round trips and separator/fallback/cardinality
  assertions on 3.3.2. Three-run alternating microbenchmarks improved 580 parses
  from median 2297.387ms to 252.987ms and 50 unequal 300/299-molecule comparisons
  from 3091.732ms to 0.288ms. These are source-only microbenchmarks, not native
  or full-application qualification. #128's 41 successful/five skipped checks
  do not qualify #204's exact stacked head, which had no hosted checks. The
  old branch had no dispatch trigger; retargeting #204 starts combined checks.
  Both landed atomically through #204 at `f917a3a7a706bc80b9cc15ed5dd793ab3ef19a95`.

- JAX: exact combined source `7e3e3d5cfe078b1a450f28e1d4a2eeb26db65e9e`
  has the same tree as merged main `58654f3b`. The
  [installed CPU lane](https://github.com/RuleWorld/BNG3/actions/runs/38000802875/job/114058116699)
  verified source/package/model/native identity with Linux Python 3.12 and
  JAX/JAXlib 0.11.2: 25 tests with x64 disabled, 20 ODE tests with x64 enabled.
  Wheel SHA256 `a27d46468757aa72ce59333f8f6ca2515ad8ae0d91cb15733553a1aa6dbbfd70`;
  native SHA256 `3049ae440e0706b7fbbaf9b73a1971d903492e883efcdae257b786ba382d085f`.
  Exact-head C++, ASan, 18 Python, three corpus, integration and sdist-smoke
  jobs passed. The whole exact-source dispatch subsequently completed successfully,
  including all four wheel platforms; release jobs were skipped. CUDA compilation/CPU fallback do not qualify GPU execution.
- NFnext #219: final source `58f097e8d829df752179cf1df3ee2301742e5cbe`,
  merge `a9b9d7e143888aafbd674f5778815d1294fcebe8`. Root reran 15 architecture
  contracts with effective Release assertions after two review-found repairs.
  Independent pinned BNG2/NFsim probes distinguish whole-species deletion,
  DeleteMolecules and connected/disconnected pattern matches. Exact fixtures,
  commands and digests are in the PR. Simultaneous replacement stays refused;
  the test-only runtime adapter does not establish production ActionIR execution.
- Compatibility #193/#208: fresh isolated macOS arm64 CPython 3.14.7 wheel of
  source `9712ba30b28c8dc27f70e7a61e4bdb04761ede28`: 227 helper-installed passes,
  106 independent root API/CLI/worker/notebook checks. All 167 tracked package
  files and installed paths verified. Wheel SHA256
  `0aa91cc3973dc047a32cc00d66cf8d124335ca7867b4fce0f8ec60f5ceb2d108`;
  native SHA256 `e49be78a04fc4be943b91d1dbf3b08fd42fe8512243d313acd80dd4915a94849`.
  Positional run semantics checked against canonical PyBioNetGen
  `28bf351a9bbfc197e19487c26dedda683716bb64`. Non-None timeout stays unsupported.
  This is that candidate's artifact, not a new wheel of current main.
- SSTS #206: exact source `13344aa4cb480d30e0dcb6f324f67c0d58dd775d` passed
  [run 37996312024](https://github.com/RuleWorld/BNG3/actions/runs/37996312024).
  Locked suite `cf38585fac5de8e0e90112febb62851ee2181816`; unchanged 32/1,923
  selection: round-trip/RoadRunner 32 passed, official 31 passed/one unsupported
  scheduled-action case, zero failures/timeouts. Full-suite flags remain false.
  The final receipt-only commit `67e5f4a7` adds
  [the permanent archive](../tests/validation/evidence/ssts-ci32-linux-py312-13344aa4.tar.gz),
  SHA256 `4e8d5ca5c1f850efac7cfdd0ee697474025520852eeaec660dea7c2560f9802e`.
  Root verified six internal digests and reran 73 gate/CI contracts. Later main
  integrations are not automatically qualified by this receipt.

Historical main `dd23c267` completed 46 successful/two skipped hosted checks.
Its previous local installed receipt had 178 passes/two existing xfails and
required an external pinned BNGsim dylib through DYLD_LIBRARY_PATH; it does not
establish current artifact identity or self-contained packaging. Queued,
skipped, synthetic-merge and historical checks must stay distinct from exact-head
execution.

The closure audit found no accepted disposition for #146/#154. Both remain
reopened with their full unmet criteria:
[#146](https://github.com/RuleWorld/BNG3/issues/146#issuecomment-6089843989),
[#154](https://github.com/RuleWorld/BNG3/issues/154#issuecomment-6089844484).

## Candidates under review

| Issues | PR / head | Qualification boundary |
| --- | --- | --- |
| #137 | #195 `e530328e` | Capability inventory; policy/owners remain unapproved. |
| #179 | #202 `78543775` | 14 approvals pending; strict validation intentionally reports 14 errors. |
| #174 | #188 merged; #218 closed as superseded, former head `2f51b79f` | #188 was narrowed to a bounded 128-entry function-call regex cache and merged after root/Luna review; slower copy changes were removed. #218’s branch and commits are preserved. Broader representative speed/memory qualification remains open. |

The [initial #188 review](https://github.com/RuleWorld/BNG3/pull/188#issuecomment-6093309268)
and [initial #218 review](https://github.com/RuleWorld/BNG3/pull/218#issuecomment-6093309400)
record the historical overlapping copy regressions and unbounded cache. Those
findings motivated the narrowed #188 candidate. Five alternating fresh-process
runs measured a 4.9% median gain for 40,000 function expansions and a 1.6% median
gain for 200 existing event-fixture exports, with identical output hashes. These
are source-level workload measurements, not native simulation or broad application
speed claims. The representative export difference is inconclusive for noise. Final-head native, Python, corpus, parity and package-smoke checks pass;
release-only jobs were skipped. Root merged exact head
`67b46804d0be63636bca28b59967f2075f9e1bc8` as
`2c3ebf2126071e2a0189ab2d537f768239ff519d`; the
[final review](https://github.com/RuleWorld/BNG3/pull/188#issuecomment-6097669630)
records source-only test limitations and excludes broad speed/RSS claims.

## Unchanged stop conditions

- Frozen `michment` SSA: 10/306 points outside three pooled standard errors,
  worst |z| about 9.3449 at ScT. Fresh pinned BNG2 reproduced all 200 golden
  files. Preserve seeds, horizons, tolerances, exclusions and goldens while
  investigating source/harness/output/RNG behavior.
- NFsim strict pinned native `-oSteps`: final-row mismatch on four deletion
  fixtures remains red. For the unchanged whole_species fixture, root/Luna traced
  the pinned native `System::sim` fallback: accumulated sample 2.0000000000000004
  skips the in-loop endpoint, then writes after a post-horizon firing (93 events
  versus 92 in stepTo/direct). The [causal review](https://github.com/RuleWorld/BNG3/issues/146#issuecomment-6093362793)
  retains the red strict gate; BNG3 horizon semantics are unchanged. Supplemental
  `-oTimes` and distributional checks remain separate; receipts remain under
  `tests/validation/evidence/`.
- Reference pins: BNG2 `9601746f8884ed19ab2acea49fe87fc4660ace46`;
  NFsim `9b00d42f734dcc3e695205600f12cae5b44d1daa`. BNG3-generated artifacts
  cannot serve as independent oracles for BNG3.
- #165 proves the Lean reference matcher, including exact embedding domains
  and mapping equality independent of association-list order. No `sorry`,
  new axiom or hidden premise; #166 production lowering remains unproved.
- The authorized full curated BioModels #162 run is recorded above; its
  product execution/numerical failure, timeout cohort, unresolved
  output-comparison case, and missing legacy Atomizer comparator keep the
  issue open. CUDA #175 requires actual NVIDIA hardware. #195 policy/owners
  and #202's 14 approval decisions remain unresolved.

Continue existing candidates and explicit issue dependencies. Current work covers
NET group counting/compartment investigation and classification of the historical NFsim failures.
The bounded unit/deletion checkpoints are integrated; higher-order units and
remaining writer/runtime consumers still need qualified slices. Preserve exact source/artifact/oracle identity,
commit tested checkpoints and update this ledger after integration. Do not create
a replacement roadmap.
