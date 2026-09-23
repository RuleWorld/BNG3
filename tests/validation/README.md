# Validation harness

The current combined-tree verification state is recorded in
[`../../docs/CURRENT_PROGRESS.md`](../../docs/CURRENT_PROGRESS.md). The
repository validation command runs every fixture in `Validate/`: network
fixtures compare against committed independent BNG2 `.net` references, while
action-only fixtures use explicit output contracts from
`validation_manifest.json`. A successful full-corpus run must report
`SKIP=0`.

Differential testing against the originals. Nothing merges until it matches.

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
- `test_parity_ode` — ODE rel-err <= 1e-6 vs Perl.
- `test_parity_stochastic` — seeded determinism + fixed-seed ensembles (at least
  200 members per side) within mean +/- 3 SE. A single `.gdat` is never treated
  as an ensemble reference.
- `test_parity_nfsim` — WO-2. ast-direct vs native binary, and ast-direct vs in-memory-XML (`BNG_NFSIM_FORCE_XML=1`).
- `test_parity_expressions` — WO-3. function-driven RHS to 1e-9.
- `test_export_formats` — WO-5. BNG-XML/SBML valid, `.net` idempotent.

## Comparator notes
`.net` reactions are keyed by structural species identity, not indices or raw bond-label strings. Molecule/site order and explicit bond numbers are ignored; site states, compartments, connectivity, stoichiometry, multiplicity, and rate values remain significant. Molecule names remain significant except where the validation manifest records an explicit, one-to-one source-specific alias. The `test_sbml_flat` aliases cover BNG2's historical `A()` to `A____` sanitization while keeping the network topology, compartments, stoichiometry, group membership, and rates under strict comparison. A duplicated reaction is detected and named.

## Exceptions
`exceptions.json` is the only expected-failure ledger. Every entry names exact tests, model, method/platform scope, tracking URL, technical reason, owner, introduction/review dates, and expected assertion signature. `exception_ledger.py` rejects incomplete, duplicate, expired, or stale references and exposes `--max-exceptions` for a non-increasing budget gate.
