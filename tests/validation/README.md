# Validation harness

The current combined-tree verification state is recorded in
[`../../docs/CURRENT_PROGRESS.md`](../../docs/CURRENT_PROGRESS.md). The
repository validation command runs every fixture in `Validate/`: network
fixtures compare against committed independent BNG2 `.net` references, while
action-only fixtures use explicit output contracts from
`validation_manifest.json`. A successful full-corpus run must report
`SKIP=0`.

Differential testing against the originals. Nothing merges until it matches.

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

## Exceptions
`exceptions.json` is the only expected-failure ledger. Every entry names exact tests, model, method/platform scope, tracking URL, technical reason, owner, introduction/review dates, and expected assertion signature. `exception_ledger.py` rejects incomplete, duplicate, expired, or stale references and exposes `--max-exceptions` for a non-increasing budget gate.
