# Benchmarks

Benchmark claims are exact-checkpoint evidence. The current implementation
snapshot and pending verification state are in
[`../docs/CURRENT_PROGRESS.md`](../docs/CURRENT_PROGRESS.md).

This directory tracks simple performance measurements for the in-process C++ backend.

## Run

```bash
python benchmarks/run_benchmarks.py
```

For a bounded network-generation measurement, select models, skip simulation
and scans, and repeat fresh model loads:

```bash
PYTHONPATH=build/cpp:python python benchmarks/run_benchmarks.py \
  --models simple_system --generation-only --repeats 5 \
  --json /tmp/bng3-benchmark.json --markdown /tmp/bng3-benchmark.md
```

Repeated parse and network-generation values are retained in JSON, and the
summary columns report their medians. Species and reaction counts must match
across repetitions. With simulation enabled, simulation and parameter-scan
timings run once on the final repetition.

The script writes:

- `benchmarks/results/latest.json` for CI artifact tracking
- `benchmarks/results/latest.md` for a human-readable summary

## Measures

For each standard model the script records:

- Parse time
- Network generation time
- ODE simulation time
- 100-point parameter scan time
- Species and reaction counts

These results are intended for trend tracking, not gating.

## Legacy Atomizer

To repeat the legacy Python Atomizer CLI on one SBML model and capture
per-process timings, implementation hashes, input hash, and raw/canonical
BNGL output hashes:

```bash
PYTHONPATH=python:build/cpp python benchmarks/benchmark_legacy_atomizer.py \
  /path/to/model.xml --mode atomized --repeats 7 \
  --json /tmp/bng3-legacy-atomizer.json
```

The canonical hash sorts annotation URI lists before comparison because their
order varied across identical runs; it leaves the remaining BNGL text intact.
This runner reports wall time only. Use a separate peak-memory profiler for
memory claims, and compare the same model/output mode when measuring a source
change.

## SBML Atomizer cross-engine benchmark

`benchmark_atomizer_cross_engine.py` compares BNG3's modern Atomizer and the
independent PyBioNetGen legacy Atomizer on the same SBML inputs. It repeats
each conversion, sends each generated BNGL file to both BNG3 and Perl BNG2,
and reports Atomizer time, network-generation wall time, output hashes,
structural network parity, and rate-expression parity as separate results.
The JSON also records the `bng_cpp` executable hash and parser source hash so
reports distinguish a rebuilt CLI from a stale executable.
Use the same fixed SBML inputs and source checkouts when comparing runs:

```bash
PYTHONPATH=python:build/cpp python benchmarks/benchmark_atomizer_cross_engine.py \
  /path/to/BIOMD0000000584.xml /path/to/BIOMD0000000202.xml \
  --modes flat atomized --repeats 3 \
  --json /tmp/bng3-atomizer-cross-engine.json
```

The runner defaults to the sibling PyBioNetGen and BNG2 checkouts and accepts
`--pybionetgen-root` and `--bng2-perl` overrides. A structural pass does not
imply rate or trajectory parity. The benchmark does not execute NFsim or
libRoadRunner; use the curated BioModels and SBML Test Suite validators for
the BNG3-to-libRoadRunner round-trip gate, and the dedicated NFsim parity
tests for eligible NFsim models. Rate comparison treats BNG2's
`A/cell()` and BNG3's `(A/cell)()` compartment-observable spellings as the same
generated expression form; it does not relax numeric rate differences.

`benchmark_atomizer_nfsim.py` runs fresh-process ensembles through BNG3's
direct NFsim path and standalone NFsim reading BNG-XML written by Perl BNG2.
It requires an explicit standalone binary and withholds ensemble means if any
seed fails, since dropping failed trajectories would bias the comparison:

```bash
PYTHONPATH=python:build/cpp python benchmarks/benchmark_atomizer_nfsim.py \
  /path/to/BIOMD0000001037.xml \
  --nfsim-binary /path/to/NFsim \
  --nfsim-source-root /path/to/nfsim \
  --modes flat atomized --runs 200 --seed-start 1 \
  --t-end 0.11 --n-steps 11 \
  --json /tmp/bng3-atomizer-nfsim.json
```

This comparison is meaningful only for models whose generated stochastic
propensities remain non-negative over the ensemble. A pass is an ensemble
mean check at three pooled standard errors, not per-seed trajectory identity.
Reported process timings include Python startup for BNG3 and should not be
read as simulator-only timings. Repeated run errors are grouped by engine and
failure signature in the report, with every affected seed retained.
