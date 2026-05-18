# Benchmarks

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