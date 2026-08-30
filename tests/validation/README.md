# Validation harness

Differential testing against the originals. Nothing merges until it matches.

## Oracles
- **Perl** — `legacy/perl/BNG2.pl`. Truth for `.net` and ODE/SSA `.gdat`. Cached as golden so Perl is off the hot path.
- **NFsim** — native binary from the CMake `NFsim` target. Truth for network-free. Set `NFSIM_BIN`.
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
pytest tests/validation -m nf      --bng-cpp build/bng_cpp
pytest tests/validation -m export
python -m tests.validation.exception_ledger --max-exceptions 1
python scripts/regen_golden.py --tier p              # (re)build golden, reviewed
```
Engine discovery: `--bng-cpp PATH` / `BNG_CPP` for the CLI; `import bionetgen` for the API.

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
`.net` reactions are keyed by structural species identity, not indices or raw bond-label strings. Molecule/site order and explicit bond numbers are ignored; site states, compartments, connectivity, stoichiometry, multiplicity, and rate values remain significant. A duplicated reaction is detected and named.

## Exceptions
`exceptions.json` is the only expected-failure ledger. Every entry names exact tests, model, method/platform scope, tracking URL, technical reason, owner, introduction/review dates, and expected assertion signature. `exception_ledger.py` rejects incomplete, duplicate, expired, or stale references and exposes `--max-exceptions` for a non-increasing budget gate.
