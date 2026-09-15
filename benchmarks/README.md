# Benchmarks

Benchmark claims are exact-checkpoint evidence. The current implementation
snapshot and pending verification state are in
[`../docs/CURRENT_PROGRESS.md`](../docs/CURRENT_PROGRESS.md).

This directory tracks simple performance measurements for the in-process C++ backend.

## Run

```bash
python benchmarks/run_benchmarks.py
```

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

## Atomizer copy benchmark

To measure the modern and legacy structure copy paths against a recursive
`deepcopy` baseline, run this from the repository root:

```bash
PYTHONPATH=python python benchmarks/atomizer_copy_benchmark.py
```

The benchmark checks copy isolation before timing each case and reports the
Python/platform identity, repeat settings, median and minimum microseconds per
copy, and peak traced allocations. Run it in a fresh process for each
checkpoint you compare; benchmark output is not committed by default.
