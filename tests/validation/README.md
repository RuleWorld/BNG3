# Validation harness

Differential testing against the originals. Nothing merges until it matches.

## Oracles
- **Perl** — `legacy/perl/BNG2.pl`. Truth for `.net` and ODE/SSA `.gdat`. Cached as golden so Perl is off the hot path.
- **NFsim** — native binary from the CMake `NFsim` target. Truth for network-free. Set `NFSIM_BIN`.
- **Golden** — committed under `golden/`. Regenerated only by `scripts/regen_golden.py`, reviewed, committed. Never auto-regenerated.

## Run
```bash
# build first: cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build && pip install -e .
pytest tests/validation -m smoke                     # Tier-S, every commit
pytest tests/validation -m "parity and not slow"     # full corpus
pytest tests/validation -m nf      --bng-cpp build/bng_cpp
pytest tests/validation -m export
python scripts/regen_golden.py --tier p              # (re)build golden, reviewed
```
Engine discovery: `--bng-cpp PATH` / `BNG_CPP` for the CLI; `import bionetgen` for the API.

## What each gate proves
- `test_parity_net` — WO-1. `blbr` + `Motivating_example_cBNGL` are `xfail(strict)` until canonical labeling is unified; remove them from `KNOWN_OVERCOUNT` when WO-1 lands.
- `test_parity_ode` — ODE rel-err <= 1e-6 vs Perl.
- `test_parity_stochastic` — seeded determinism + ensemble within mean +/- 3 SE.
- `test_parity_nfsim` — WO-2. ast-direct vs native binary, and ast-direct vs in-memory-XML (`BNG_NFSIM_FORCE_XML=1`).
- `test_parity_expressions` — WO-3. function-driven RHS to 1e-9.
- `test_export_formats` — WO-5. BNG-XML/SBML valid, `.net` idempotent.

## Comparator notes
`.net` reactions are keyed by **species strings**, not indices, so networks equal up to ordering compare equal and a failed merge (the over-count) compares unequal. Verified: a duplicated reaction is detected and named.
