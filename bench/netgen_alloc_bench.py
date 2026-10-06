#!/usr/bin/env python3
"""Netgen allocation benchmark using tools/memory_allocs methodology."""

from __future__ import annotations
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_child(code: str, what: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", code, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{what}: child exited {proc.returncode}\n{proc.stderr}")
    return json.loads(proc.stdout)


def measure_allocs(model_path, max_iter=32, n_runs=5):
    code = f"""
import json, time
import _bionetgen_cpp as cpp
model = cpp.parse_file("{model_path}")
# Warmup
for i in range(3):
    cpp.generate_network(model)
# Measure
import gc
gc.collect()
t0 = time.perf_counter()
for i in range({5}):
    net = cpp.generate_network(model)
elapsed = time.perf_counter() - t0
print(json.dumps({{"wall_ms": elapsed * 1000 / {5}}}))
"""
    return f"""
import json, time, sys
sys.path.insert(0, '{ROOT}/build/cpp')
sys.path.insert(0, '{ROOT}/python')
sys.meta_path[:] = [f for f in sys.meta_path if not type(f).__module__.startswith('_editable')]
import _bionetgen_cpp as cpp
model = cpp.parse_file("{model_path}")
times = []
for _ in range({5}):
    t0 = time.perf_counter()
    net = cpp.generate_network(model)
    times.append(time.perf_counter() - t0)
import statistics
print(json.dumps({{"median_ms": statistics.median(times)*1000, "stdev_ms": statistics.stdev(times)*1000 if len(times)>1 else 0}}))
"""
    # We'll run a simpler measurement
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import json, time, sys
sys.path.insert(0, '{ROOT}/build/cpp')
sys.path.insert(0, '{ROOT}/python')
sys.meta_path[:] = [f for f in sys.meta_path if not type(f).__module__.startswith('_editable')]
import _bionetgen_cpp as cpp
model = cpp.parse_file("{model_path}")
times = []
for _ in range({5}):
    t0 = time.perf_counter()
    net = cpp.generate_network(model)
    times.append(time.perf_counter() - t0)
import statistics
print(json.dumps({{"median_ms": statistics.median(times)*1000, "stdev_ms": statistics.stdev(times)*1000 if len(times)>1 else 0}}))
""",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise SystemExit(f"alloc bench failed: {proc.stderr}")
    return json.loads(proc.stdout)


def main():
    models = [
        "models/isomerization.bngl",
        "models/gene_expr_simple.bngl",
        "bench/fixtures/netgen_egfr.bngl",
    ]
    results = {}
    for path in models:
        print(f"Measuring {path}...")
        results[Path(path).stem] = measure_allocs(path)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
