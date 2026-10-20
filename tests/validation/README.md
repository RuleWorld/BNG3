# Validation harness

The current combined-tree verification state is recorded in
[`../../docs/CURRENT_PROGRESS.md`](../../docs/CURRENT_PROGRESS.md). The
repository validation command runs every fixture in `Validate/`: network
fixtures compare against committed independent BNG2 `.net` references, while
action-only fixtures use explicit output contracts from
`validation_manifest.json`. A successful full-corpus run must report
`SKIP=0`.

Differential testing against the originals. Nothing merges until it matches.

## Cross-component generated integration cases

`tests.validation.integrated` runs a twenty-five-case pairwise PR matrix that sends generated SBML through Atomizer, BNG3 command-line and Python execution, locked BNG2, an isolated upstream PyBioNetGen interpreter, and independently built native NFsim. Scheduled and manually dispatched parity runs can select the full sixty-one-case matrix. Reports retain stage-specific outcomes, tool identities, logs, commands, intermediates, and investigation packets; a passing stage does not imply that a later stage ran or passed.

After building BNG3 and checking out the locked oracles, run the same worker locally with a fresh report directory:

```bash
python -m tests.validation.integrated \
  --bng-cpp build/cpp/bng_cpp \
  --bng2-root /absolute/path/to/locked/bionetgen \
  --bng2-network-sha256 <run_network-sha256> \
  --nfsim-root /absolute/path/to/locked/nfsim \
  --nfsim-binary /absolute/path/to/locked/nfsim/build/NFsim \
  --nfsim-sha256 <native-nfsim-sha256> \
  --pybionetgen-root /absolute/path/to/locked/pybionetgen \
  --pybionetgen-python /absolute/path/to/isolated/pybionetgen-venv/bin/python \
  --report-dir /tmp/bng3-integrated-validation
```

Decay, reversible conversion and dimerization families vary compartment volume, population, declaration order (or initially occupied side for reversible conversion), and Atomizer mode. The source analytic amounts are checked against each deterministic route; network identities/rates use BNG2, and native NFsim consumes BNG2 XML for seeded trajectory comparison in the single-channel families. Reversible models check source count/initial/conservation invariants on both NFsim routes; they do not claim pathwise equivalence across differently ordered reaction channels. The final-pass ensemble checks below independently test selected source marginals. `--case v1-n20-r0-a0` selects one replay.

The upstream PyBioNetGen source is imported by the isolated worker; install its requirements into that interpreter without installing the upstream package. Pull requests use the bounded default selection; `--full` selects the expanded matrix. This is regression-discovery evidence, not a claim of complete component equivalence.

The same cases also feed BNGL export/reload, BNGIR 0.1 and native 0.2 reconstruction, SBML export consumed by RoadRunner, and model reuse/mutation/reset/seed replay. Per-consumer `checks.json` is merged into the same report with required check identities. Native BNGIR checks block BNGL parser/render fallback during reconstruction; its guarded NET exporter stays guarded. Native generation compares graph identity, counts and a mapped unit-state RHS snapshot, with independent source trajectories checked separately. Independent source analytic trajectories still judge each deterministic consumer; fresh/reused agreement alone cannot validate both.

Each generated SBML case also records its reaction MathML, parameter/unit
definitions, compartment volumes and source rate evaluated at a unit amount
state. An isolated BNG3 worker captures native compiled reaction coefficients,
ODE RHS, NET, and BNG-XML output. It compares the observed source-to-compiled,
compiled-to-NET, and NET-to-BNG-XML boundaries in sequence, retaining all
statuses and a stable source trace ID. A missing boundary prevents the report
from assigning a first divergence past that point, while later failures remain
visible in the trace and repair packet. The NET rate parser resolves emitted
rate expressions with the existing comparison helper. For the generated scalar
elementary BNG-XML slice, the detector compares each numeric `RateConstant`
times its explicit `symmetry_factor` (default 1); a mismatch is diagnostic
evidence only (`supported_execution=false`). Native compiled rate comparison
is explicitly a reaction-rate multiset probe because reaction identity mapping
is unavailable at this hook. Dynamic/multi-parameter XML laws and missing
observations remain `NOT_TESTED`; these traces do not qualify all downstream
NFsim semantics or stochastic count conventions.

CI also runs `tests.validation.integrated_matrix` over four PR-selected decay
sources: the baseline, function-argument shadowing, amount-to-concentration
coordinates, and a new function-shadowing case whose unused global `rate=13`
is deliberately far from the active `k=0.4`. The matrix requires named
Atomizer, BNG2, CLI, Python, PyBioNetGen, compatibility, NET reload, BNGIR,
SBML/RoadRunner, reuse, embedded NFsim, native NFsim, protocol, and stochastic
marginal/invariant receipts. It verifies receipt paths and
SHA-256 values and records the exact candidate revision and replay commands.
For each deterministic artifact it independently checks the source analytic
trajectory. For reuse it checks the selected parameter and before/after values,
then compares both the mutated instance and a fresh compilation with the
closed-form changed-rate trajectory; a missing mutable dependency remains
`NOT_TESTED`. The separate `matrix-report.json` is uploaded with the integrated
report and makes missing cells, stale artifacts, and shared wrong mutation
references visible. The matrix lane fails on a failed, malformed or missing
result; a consumer that explicitly refuses a construct, or a check that was
never applicable, keeps that status in the report and stays distinct from a
pass, the same distinction the integrated report's gate makes.

`tests.validation.issue_queue` joins one or more exact-revision reports to a retained `gh issue list` snapshot. It rejects stale/conflicting observations and avoids counting a successful process as a passed behavior. Every issue remains explicitly ineligible for automatic closure. The queue includes strict provenance approval debt, reconciliation claims without test references, stale named references, and optional upstream branch observations. A reference resolving in source never counts as executed qualification. CI collects a bounded 1,000-issue snapshot and checks upstream branch drift only on scheduled/manual runs; unavailable or unobserved branches are not treated as matching the lock.

```bash
python -m tests.validation.issue_queue \
  --issues-json /tmp/issues.json --report /tmp/bng3-integrated-validation/report.json \
  --revision <exact-candidate-sha> --output-dir /tmp/bng3-issue-queue
```

This command reads local evidence and produces a repair/evidence/decision queue; it never modifies GitHub issues or source approvals.

The final qualification stages add eight valid-source SBML boundary controls for nonlinear events, delay history, nonlinear algebraic constraints, and fast reactions with dynamic stoichiometry. LibSBML consistency runs before Atomizer evidence is scored; fast-reaction fixtures use L3V1 because L3V2 removed that attribute. Only matching structured loss diagnostics or actual Atomizer rejections qualify the boundary control. Successful diagnostic-only rows have `supported_execution=false` and enter a separate issue-queue count; they do not establish consumer refusal or supported execution. `--boundaries-only` reproduces this bounded group.

Every generated case also checks modern API equivalence on a requested nonuniform absolute grid, invalid-option refusal with a working positive control, concurrent SSA instances against fresh sequential references, saved-result isolation, and exception recovery. All three families additionally sample fresh embedded and native NFsim runs with fixed spread seeds: 32 per engine on PRs and 128 on scheduled/full runs. Independent source count laws (binomial conversion and the finite dimer pure-death generator), CDFs and seed spread use Hoeffding/DKW/equal-outcome probability bounds with a conservative global error budget of 1e-6 across the full case inventory. The checks concern these count marginals, not a complete stochastic equivalence proof. Dimer count hazards use `k*n*(n-1)/V`; the deterministic `k*A^2/V` trajectory is not a stochastic mean oracle. `--ensemble-runs` overrides a bounded run budget; reports and replay commands retain its exact value.

The native lane samples the model the embedded engine executes. BNG2 states a reactant-bearing rate constant in count-rate units, dividing it by the reaction compartment's size, while the pinned native NFsim applies a compartment size only to zero-order synthesis. The marginal stage therefore normalises the BNG-XML export it hands the oracle before it runs: the same compartment unit conversion the XML rate probe applies is folded into the rule's rate constant, and the now-redundant symmetry factor is dropped. The native rows state that the oracle sampled the model in that convention, and an export whose compartment size is not statically determinable states no count-rate coefficient, so those native rows stay explicitly not tested with that reason.

The native NFsim stage applies the same normalisation to BNG2's XML, so the seeded native and embedded NFsim trajectories compare exactly for every generated case, the compartment and reversible families included. The rewrite reads the compartment of a rule pattern, drops the symmetry factor the coefficient now carries, and removes the compartment factor the oracle applies itself for a zero-order rule whose product molecule states a compartment; an export the rewrite cannot state is an explicit refusal rather than an approximation.



Mutable source controls accompany each generated translation. Atomizer may legally
fold static rate parameters into numeric coefficients, so changing an unused
source parameter is not evidence of cache invalidation failure. Dependency
selection follows function calls, and separately identified native BNGL controls
retain named rate, seed and compartment dependencies. Reused ODE/SSA instances
are checked against source-edited fresh compilations, then reset; concurrent SSA
checks identify which source they used. Semantic reload failures retain both
canonical documents and the first differing JSON pointer.
Downstream comparisons depend on their named artifact handoff, so an unrelated
failed semantic contract does not suppress an already completed simulation or
network comparison. Process/identity errors still block handoffs. A process
summary explained by complete validated child checks is marked as an aggregate
rather than counted as a second scientific finding.

The integrated lane requests `rtol=1e-10`, `atol=1e-12` from deterministic
solvers; its trajectory comparison thresholds remain unchanged. BNG2 NET embeds
conversion prefactors with eight significant digits (for example `1/6` becomes
`0.16666667`), so integrated numeric rate comparison explicitly allows relative
serialization error of `5e-8` with zero absolute allowance. Topology,
multiplicity and symbolic rates remain exact; general network comparison
continues to default to strict rate identity.

The issue queue retains each live acceptance checkbox as an independently named
unverified obligation. A checked issue box or a passing related test cannot
establish that the full acceptance sentence was executed. Known source-law
mismatches, including NFsim compartment count-rate conversion, remain ordinary
failures for investigation rather than exclusions or tolerance changes.

## Integrated capability campaign

The existing entry point also orchestrates discovery, component tests and live
bounded differential validation. Its original reference-fixture invocation
remains available unchanged. Install the normal development dependencies
(discovery/smoke requires `pytest`, `numpy`, and `pyyaml`), build BNG3, then run:

```bash
python scripts/validate.py --tier smoke \
  --models simple_system michment blbr \
  --bng-cpp build/cpp/bng_cpp \
  --bng2-root /absolute/path/to/locked/bionetgen \
  --bng2-network-sha256 <independently-built-run_network-sha256> \
  --report-dir /tmp/bng3-smoke
```

Use a new/empty output directory each time. `report.json`, `inventory.json`,
`report.md`, and `artifacts.json` retain outcomes, source/model/tool hashes,
commands, logs, intermediate networks, and pytest scratch artifacts. Binary and
package identities are observations of the actual run, not source-build or
release approval. Existing source-lock approvals remain unchanged.

`provenance/capability-matrix.yml` remains the inventory source: its original
policy rows are retained, and `validation_capabilities` maps semantic families
to implementation, tests, references and issues. `provenance/validation-plan.json`
defines execution suites. Source discovery additionally inventories C++/GPU
units, public Python symbols, bindings, grammar rules, action handlers, compiler
features/backends and Lean declarations. New/unmapped entries are **unverified /
NOT_TESTED**, even when adjacent code has tests. One passing test establishes
only partial evidence for a mapped capability. Discovery cannot prove the
absence of further semantic distinctions.

```bash
# Discovery and coverage gaps only; no execution or compatibility qualification.
python scripts/validate.py --inventory-only --report-dir /tmp/bng3-inventory

# Native contracts and the Python tests mapped by the capability inventory.
python scripts/validate.py --tier integration --package-mode source \
  --report-dir /tmp/bng3-integration

# Existing parse/generation benchmark, five fresh repetitions, separate results.
python scripts/validate.py --tier performance --report-dir /tmp/bng3-performance
```

Repeat `--tier` to combine tiers; `--suite NAME` restricts execution to named
suites. `full` adds existing BNG2/NFsim/stochastic/legacy-Python lanes and the
existing official SBML runner (`--sbml-suite PATH`). Finite BNG2 suites also
require `--bng2-network-sha256` for the built `bng2/bin/run_network`; NFsim requires
`--nfsim-root`, `--nfsim-binary`, and `--nfsim-sha256`. Checkouts must match the
locked commit/repository and have no modified tracked inputs, hidden index
flags or untracked inputs. Embedded NFsim binaries are rejected. Source/oracle
approval and scientific qualification remain separate from these identity
checks. `--pybionetgen-root` and `--rulehub-root` add verified external corpus
discovery without adding models to any gate.

Model execution uses the existing frozen selection. `--corpus-tier p` selects
the locked parity IDs for stage checks; `--shard-count N --shard-index I` shards
them deterministically. Discovery retains duplicate stems by path. Lexical
capability hints and file size do not establish support or runtime cost.
Parsing uses the original model; network comparison uses the existing
network-only staging helper with explicit `--network-iterations` (default 4),
`--max-aggregate` (default 8), and `--case-timeout` (default 30 seconds). These
results qualify bounded expansion only. Models outside the approved selection
are discovered without executing their action blocks.

`PASS`, `FAIL`, `UNSUPPORTED`, `NOT_TESTED`, `INVALID_INPUT`, `TIMEOUT` and
`HARNESS_ERROR` stay distinct. Missing references/outputs and skipped selected
compatibility cases cannot qualify compatibility. A successful invocation with
NOT_TESTED entries is not a compatibility pass. `--report-only` preserves every
result while returning zero for new, nonblocking CI coverage. Existing gates
are not replaced. The existing parity workflow runs nightly; existing weekly
performance/platform and dedicated SBML/formal workflows retain their own scope.

`--baseline /path/to/report.json` compares case outcomes only when corpus,
configuration, tests/comparators, goldens, references and runtime fingerprints
match. Deselecting a failure never counts as resolving it. Failure clusters are
signature hypotheses, not confirmed shared causes. Official SBML conformance,
round trips and libRoadRunner agreement remain separate report rows.

## Deterministic triage and repair packets

Triage adds a novelty and evidence gate to an existing validation report. It
does not rerun commands from the report, change scientific outcomes, approve
support, or close issues. Give `--replicate` one or more separately generated
reports from the same clean source revision, candidate binary, configuration,
inputs and references. A named failure is `REPRODUCED` after at least two
matching observations; a pass or a different failure makes it
`NONDETERMINISTIC`, and a missing selected case remains `INCOMPLETE_REPLAY`.
Missing unrelated rows do not change a case's reproduction classification.

```bash
python -m tests.validation.triage report.json \
  --output /tmp/bng3-triage \
  --previous /path/to/previous-ledger.json \
  --replicate /path/to/repeat-report.json \
  --baseline /path/to/reviewed-baseline.json \
  --issues-json /path/to/issues.json --strict
```

`--strict` returns nonzero for unresolved novelty or evidence gaps. Outcomes
remain separate: `FAIL`, `TIMEOUT`, and `HARNESS_ERROR` are not interchangeable;
`UNSUPPORTED`, `INVALID_INPUT`, and `NOT_TESTED` remain visible and cannot be
counted as scientific passes. Diagnostic refusal failures may receive an
investigation packet, but they are never eligible for a product repair task as
supported scientific execution. The gate also remains failing when a known
failure is accompanied by another unresolved outcome.

The tool never creates or updates a reviewed baseline. A maintainer must review
the exact case, issue, configuration and two matching reports from the same
revision before adding an entry. This is a schema example only; the placeholders
are not evidence:

```json
{
  "schema_version": 1,
  "entries": [{
    "comparison_key": "<64-hex configuration and oracle identity>",
    "case_id": "<exact leaf result id>",
    "fingerprint": "<64-hex observed failure identity>",
    "issue": 151,
    "reviewed_by": "<maintainer>",
    "reason": "<why the same observed contract failure is accepted as known>",
    "evidence": [
      {
        "report_sha256": "<64-hex report digest>",
        "source_revision": "<40- or 64-hex commit>",
        "comparison_key": "<same 64-hex value as above>",
        "fingerprint": "<same 64-hex value as above>"
      },
      {
        "report_sha256": "<different 64-hex report digest>",
        "source_revision": "<same commit as above>",
        "comparison_key": "<same 64-hex value as above>",
        "fingerprint": "<same 64-hex value as above>"
      }
    ]
  }]
}
```

Repair eligibility is narrower than a failure finding: the source must be
clean, the named result must be an application or contract `FAIL`, at least two
reports must reproduce its exact fingerprint, a replay command must be
recorded, and every referenced artifact must be retained within the packet
limits. These conditions only mark a bounded candidate for human assignment;
they do not confirm a root cause or establish issue closure. Each packet keeps
the report identity, source dirty state, candidate and reference identities,
configuration, platform, receipt load errors and hashes of retained artifacts.
Artifact collection is capped at 128 files per task, 2 MB per file, 12 MB per
task, 50 MB for the source report, and 200 task packages per run. Files outside
the report directory, missing files and oversized files remain listed as
missing evidence.

For an actual recorded network mismatch, an opt-in reducer removes complete
single-line reaction rules, retaining only candidates for which both engines
emit valid networks with the same observed mismatch category:

```bash
python -m tests.validation.minimize /tmp/bng3-smoke/report.json \
  --case MODEL_ID --output /tmp/bng3-reproducer --attempts 24
```

It preserves attempts and a smaller BNGL reproducer; it does not claim global
minimality or a root cause. Controlled-mutation self-tests cover wrong networks,
rates, initial amounts, observable weights, nonfinite/missing trajectory data,
shared/incorrect references, stale digests, missing output and incomplete test
reports. Golden references are never regenerated by the campaign.

## Focused diagnostic probes

The smoke/full campaign also runs `diagnostic-probes`, a small live BNG2/BNG3
suite in `test_diagnostic_probes.py`. It uses seven explicit BNGL fixtures under
`probes/`, outside the unchanged frozen release selection. Both the canonical
locked BNG2 checkout and the independently built Network3 binary digest are
required. CLI probes do not need an unrelated Python native package.

The suite intentionally remains red for the separately tracked boundaries:

| Named boundary | Issue |
| --- | --- |
| set/add concentration changes missing from exported seed state | #272 |
| NET reload loses exact observable columns | #273 |
| NET reload rejects empty observable groups | #274 |
| NET reload changes an observable-dependent rate trajectory | #275 |
| CDAT omits constant/compartment species identity | #276 |

These are ordinary failing tests, with no xfails, exclusions or regenerated
references. Passing controls independently check the complete first-order
trajectory, `A(t)=10*exp(-0.5*t)`, conservation `A+B=13`, per-species positivity,
and reconstruction of declared observables from weighted NET groups. Each
engine must satisfy the analytic/algebraic checks independently. A symmetric
dimer additionally checks the k/2 identical-reactant factor, molecule-versus-species
observable weights, trajectory agreement and molecular-unit conservation.

```bash
# Run only the small probes, retaining exact commands and intermediate outputs.
BNG3_CI_STRICT_ORACLES=1 \
BNG2_PERL=/path/to/locked/bionetgen/bng2/BNG2.pl \
BNG2_NETWORK_SHA256=<independently-built-run_network-sha256> \
python -m pytest -c tests/validation/pytest.ini \
  tests/validation/test_diagnostic_probes.py --bng-cpp build/cpp/bng_cpp \
  --basetemp=/tmp/bng3-probes -q
```

For the frozen corpus, `--simulate --net-reload` adds separate bounded BNGL and
NET reload CDAT/GDAT checks. Names and complete requested grids must agree;
CDAT uses a graph bijection, preserving flags/compartments. A failed network
prerequisite blocks simulation instead of creating a second solver diagnosis.
Models with no declared observables explicitly report that GDAT is inapplicable;
CDAT remains required.

CI retains the existing parity jobs and publishes a separate **Conformance
findings (network, cdat, gdat)** check. Its strict gate rejects failures, missing
contracts, duplicate case IDs, unexpected skips and reports for the wrong
candidate revision. Summaries link each named failure to
`investigation-tasks.json`, source/test locations, exact replay commands and
bounded acceptance criteria. Aggregate model rows do not create duplicate
investigation tasks. These diagnostics expose failures; they do not approve a
release or repair product behavior.

## Oracles
- **Perl** — `legacy/perl/BNG2.pl`. Truth for `.net` and ODE/SSA `.gdat`. Cached as golden so Perl is off the hot path.
- **NFsim** — independently built native binary from the pinned pre-convergence
  NFsim source. Truth for network-free. Set `NFSIM_BIN` to its existing path;
  the harness never falls back to BNG3's embedded `NFsim` target.
- **Golden** — committed under `golden/`. Regenerated only by `scripts/regen_golden.py`, reviewed, committed. Never auto-regenerated.

The exact model IDs used by each tier are frozen in
`provenance/corpus/selection.json`. The manifest is linked to
`provenance/upstreams.lock.yml` and records a SHA-256 digest for every model
fixture. Validate it and check that it was generated from the current tree with:

```bash
python scripts/validate_corpus_manifest.py
python scripts/generate_corpus_manifest.py --check
```

The RuleHub revision is recorded but external selectors remain pending
maintainer approval; CI does not infer an unpinned RuleHub corpus.

## Run
```bash
# build first: cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build && pip install -e .
pytest tests/validation -m smoke                     # Tier-S, every commit
pytest tests/validation -m "parity and not slow"     # full corpus
NFSIM_BIN=/absolute/path/to/pinned/native/NFsim \
  PYTHONPATH=python:build/cpp pytest tests/validation -m nf --bng-cpp build/cpp/bng_cpp
NFSIM_BIN=/absolute/path/to/pinned/native/NFsim \
  BNG_ENSEMBLE_WORKERS=8 PYTHONPATH=python:build/cpp \
  pytest tests/validation -m nf  # fixed 200-seed NF gate
pytest tests/validation -m export
python -m tests.validation.exception_ledger --max-exceptions 1
python scripts/regen_golden.py --tier p              # (re)build golden, reviewed
```
Engine discovery: `--bng-cpp PATH` / `BNG_CPP` for the CLI; `import bionetgen` for the API.

The 2026-09-14 independent checkpoint used BNG2 revision
`e0a5c6d9e6c4730f66102e48d0d0a598337083e7` and NFsim revision
`a6f9fa945c9d6e1e122e789c952260112c93f157`. The selected structural BNG2
workflow reported `5/5` passes. The selected NFsim gate reported `10 passed`,
covering direct/XML construction, four 200-run seeded ensembles, and fixed-seed
endpoints.

The direct/XML tests assert the returned `construction_path`: the shadow leg
must be `in-memory-xml`, and the direct leg must be `direct` after
`BNG_NFSIM_ALLOW_XML_FALLBACK` is removed. The ensemble worker explicitly adds
the repository root and `python/` to `sys.path`, and rejects any member that
does not report direct construction. This prevents XML-vs-XML comparisons or
caller-dependent source-tree imports from being counted as direct evidence.

The former reference-exclusion ledger is closed. The six fixtures whose
primary behavior is an action output (`ANx`, `hybrid_test`, `test_tfun`,
`test_tfun_xml`, `test_write_sbml_multi`, and `visualize`) are independently
validated by `scripts/validate_actions.py`; the remaining fixtures are checked
against committed BNG2 network references. The native reader also has a narrow
legacy structured-SBML `atomize=>1` contract for the `plain2` validation model.

## What each gate proves
- `test_parity_net` — WO-1a. Active expected failures come only from `exceptions.json`; each is signature-checked and an unexpected pass fails. The current ledger is empty: `blbr` now compares equal under structural species identity, including its symmetry-heavy bond-label orientations.
- `test_parity_ode` — action-aware CLI trajectories against BNG2 at fixed
  `rtol=1e-6`, `atol=1e-9`, plus exact observable-set Python API comparisons
  for action-matched models. The original `Motivating_example` action remains
  unedited in the BNG2 comparison.
- `test_parity_stochastic` — exact repeated-seed SSA determinism. Its
  distributional BNG2 comparison requires a committed 200-member `.ens`
  reference for each model; one trajectory is never substituted for an
  ensemble.
- `test_parity_nfsim` — WO-2. ast-direct vs native binary, and ast-direct vs in-memory-XML (`BNG_NFSIM_FORCE_XML=1`).
- `test_parity_expressions` — action-aware `.net` structure and rate-expression parity for the deterministic function fixtures.
- `test_parity_rhs` — per-reaction rate coefficients and instantaneous
  `OdeIntegrator::derivs` against an independent, restricted evaluator of
  pinned BNG2 `.net` expressions across all five frozen `expr` tier models.
  Coefficients are compared before mass-action species factors. It uses three
  positive synthetic states and three times per model (`rtol=1e-9`,
  `atol=1e-12`); unsupported syntax and non-finite values fail closed. This
  checks each selected reaction's expression result and the accumulated
  derivative. It does not export intermediate parameter, function, or group
  symbols as standalone outputs.
- `test_oracle_perl` — exact model-stem output selection, unambiguous phase fallback, and source-only network generation flags.
- `test_export_formats` — WO-5. BNG-XML/SBML valid, `.net` idempotent.

## Comparator notes
`.net` reactions are keyed by structural species identity, not indices or raw bond-label strings. Molecule/site order and explicit bond numbers are ignored; site states, compartments, connectivity, stoichiometry, multiplicity, and rate values remain significant. Molecule names remain significant except where the validation manifest records an explicit, one-to-one source-specific alias. The `test_sbml_flat` aliases cover BNG2's historical `A()` to `A____` sanitization while keeping the network topology, compartments, stoichiometry, group membership, and rates under strict comparison. A duplicated reaction is detected and named.

Trajectory comparisons choose their observable policy explicitly. Network-free and
stochastic identity checks require the exact observable set; the BNG2 ODE gate
uses the intersection because the two action implementations can expose
different but valid columns. The comparator reports missing, extra, duplicate,
and reordered columns instead of silently aligning an accidental subset.

## Graph identity boundary

BNGcore canonicalizes pattern graphs through `PatternGraph::get_label` and
NFsim constructs its own complex labels in `Complex::generateCanonicalLabel`;
both link the one compiled `nauty` target documented in
[`../../cpp/nauty/README.md`](../../cpp/nauty/README.md). The parity comparator
uses its own structural species-graph isomorphism, with tests for molecule/site
order and bond-number independence, and for preserving state and connectivity.
These checks establish structural parity for the tested encodings. They do not
assert that BNGcore and NFsim raw label strings are interchangeable or prove a
global cross-domain canonical-label contract; cache keys and serialization
remain domain-specific.

The integrated campaign also runs six generated seed-only identity controls
through the installed BNG3 native network generator: 3-, 4- and 5-molecule
symmetric rings under molecule/site/bond-label permutations, plus state,
species-compartment and molecule-compartment distinctions. Expected seed
partitions come from the validation graph matcher, whose implementation is
separate from the native identity consumer. This is a bounded
`SpeciesList`/network-generation detector;
it does not compare BNGcore and NFsim labels, exercise embedded or standalone
NFsim identity, or qualify general network canonicalization. The issue queue
links each named result to #142, and mismatches remain ordinary failures.
Run just this group with `--graph-identity-only`; generated BNGL, written NET
files, per-case outcomes and the first identity difference stay in the report
directory. Invalid generated inputs and evidence-harness failures retain their
own classifications, and do not stop later cases.

## Exceptions
`exceptions.json` is the only expected-failure ledger. Every entry names exact tests, model, method/platform scope, tracking URL, technical reason, owner, introduction/review dates, and expected assertion signature. `exception_ledger.py` rejects incomplete, duplicate, expired, or stale references and exposes `--max-exceptions` for a non-increasing budget gate.

### Acceptance obligations and next work

`issue_queue.py` joins the live issue snapshot to the reviewed inventory in
`provenance/issue-obligations.json`. Each obligation has a stable ID, the exact
acceptance sentence, bounded semantic scope, dependencies, producer/consumer
boundaries, relevant test references, required named checks, and a completion
condition. Tests linked at issue level establish relevance only. Missing
`qualification:*` checks explicitly identify work that has no reviewed executable
contract yet. They are not generated tests or evidence of execution.

The initial vertical slice covers #141 model reuse, #151 count/rate qualification,
and #155 native BNGIR import. Existing generated checks assess narrow parts of
those issues; broad lifecycle independence, physical-unit semantics, migration,
and serialization requirements remain separate. A count-law baseline without
physical-unit annotations cannot qualify the unit bridge. A native refusal can
only demonstrate its named rejection obligation, with a positive native reader
control as a dependency. These are issue-specific contracts, not universal gates.

The inventory then extends across the 43 open issues observed on 2026-10-18.
Scope without reviewed boundaries or executable evidence remains explicitly
unmapped. New acceptance text creates unmapped obligations; any changed issue
body invalidates the reviewed scope until reconciled. Maintainer decisions and
support-policy choices require explicit review; checkboxes are never execution.

Generate the dashboard using the current checkout and downloaded or locally
retained evidence:

```bash
gh issue list --state open --limit 1000 \
  --json number,title,body,state,url,updatedAt > /tmp/issues.json
python -m tests.validation.issue_queue \
  --issues-json /tmp/issues.json \
  --report /path/to/integrated/report.json \
  --report /path/to/integrated/matrix-report.json \
  --revision "$(git rev-parse HEAD)" --output-dir /tmp/acceptance-queue
```

Use a new output directory. `issue-queue.json` and `issue-queue.md` contain each
issue's demonstrated obligations, named failures, unsupported and unexecuted
checks, scope decisions, and explained ranking. `obligation-assessment.json`
retains every required consumer independently of observed execution, including
untested routes/combinations and missing candidate/oracle identity evidence.
Stale, dirty/unverifiable, duplicate, or conflicting evidence is audited
separately and cannot demonstrate current obligations. Failures lacking required
oracle identities remain observations with evidence gaps, not confirmed defects.

`campaign-selection.json` ranks bounded plans using uncovered exact check IDs
from existing integrated families and known failing obligations. Plans record
shared issues, target obligations, case/check budgets and limits. They authorize
no new execution, full corpus sweep, GPU use, or budget expansion. Representatives
never establish complete corpus coverage. Requirements without an executable
family remain visible instead of receiving a speculative runner.

Pass the assessment into the existing repair-packet builder:

```bash
python -m tests.validation.triage /path/to/integrated/report.json \
  --output /tmp/acceptance-triage \
  --obligations-json /tmp/acceptance-queue/obligation-assessment.json
```

Packets associate failures by exact check ID, retain independent expectations,
candidate/oracle identities, affected obligations, missing evidence and the first
observed boundary. Retention is labeled `RETAINED_NOT_MINIMIZED` unless separate
reduction evidence exists; matching symptoms never establish a shared cause.
Missing required consumers or identities prevent repair eligibility. Product
repairs remain separate. The common parity workflow builds the dashboard before
packet generation and uploads both, including on scientific failures. No command
in this workflow merges PRs or closes issues.

### Executed lifecycle, quantity and reconstruction slices

The installed-worker protocol adds four bounded lifecycle cases: two concurrent
constructions, distinct parameters/seeds, three interleaved runs per model,
V/N/k mutations with fresh and closed-form controls, restoration, and installed
console-script/API/action execution. Trajectories and CLI ownership/digests are
retained. Public in-place topology edits remain explicitly unavailable; these
checks do not qualify arbitrary threaded engine execution.

`quantity-laws` declares six PR cases and twelve scheduled cases before running.
Each case uses 32 PR (128 full) trajectories per stochastic consumer: SSA,
embedded NFsim and independently built native NFsim. Independent Poisson,
binomial and finite pure-death laws judge A-count marginals with a campaign
error budget of 1e-6, split across cases, consumers, times and checks. ODE uses
closed-form laws. These physical-law fixtures are independently prelowered BNGL
controls; their unit descriptions and concentration-coordinate seed conversion
do not establish product ingestion of physical-unit annotations. Existing
unit-annotated SBML families and source-oracle checks remain separate.

Native BNGIR adversarial controls now execute seeds, RHS and closed-form
trajectories after disabling BNGL parsing/rendering during reconstruction.
Molecule-ID permutations are positive controls. Compartment controls preserve
prefix/suffix/molecule placement when accepted, or report UNSUPPORTED pending
#300. Bonded structures remain an explicit unsupported boundary. Actual JSON
outputs and input hashes accompany the existing receipts; malformed references
remain diagnostic-only controls.

The three nonunit-volume dimer trajectory disagreements on main `65c8d336`
coexist with passing embedded/native source-CDF checks at that run's finite
budget. They remain trajectory disagreements without an established cause;
neither source-law acceptance nor equal seeds establishes full path equivalence.
`--quantity-laws-only` selects the new bounded campaign; `--full` expands it.
Manual workflow `bounded=true` retains PR selection on a stacked candidate.

`stochastic-parity` compares the stochastic backends with the independent count
law of each supported rate convention: the elementary parameter law, a local
function (constant and state-dependent), a builtin call, a TFUN table, the `Sat`
and `Hill` special rates and the elementary bimolecular rule. The law is
computed in the harness from the master equation of the declared convention, so
a stochastic result is never compared against the product's own output, and
every case also declares one specific misreading of its convention that the
observed ensemble must be separated from. The seed policy
(`17 + 7919 * (index + 1)`) and the run budget (64 trajectories) are fixed and
recorded; the mean comparison is an exact two-sided test whose null
distribution is the law's own mass function, corrected over the sampled
timepoints by a union bound, and the count distribution is compared with the
DKW bound. The qualified slice covers one distinct reactant plus the
elementary bimolecular rule; a case outside it is reported as `UNSUPPORTED`
with its reason. `--stochastic-parity-only` selects that campaign on its own.
