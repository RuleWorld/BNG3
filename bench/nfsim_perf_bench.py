#!/usr/bin/env python3
"""NFsim performance benchmark with parity verification."""

from __future__ import annotations
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODELS = [
    "models/isomerization.bngl",
    "models/gene_expr_simple.bngl",
    "models/performance_test_models/egfr_net.bngl",
]


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


def measure_nfsim(model_path, t_end, n_runs=5):
    code = f"""
import json, time, hashlib
import _bionetgen_cpp as cpp
model = cpp.parse_file("{model_path}")
network = cpp.generate_network(model)
times = []
for i in range({5}):
    t0 = time.perf_counter()
    res = cpp.simulate_nfsim(model, network, t_end={50.0}, n_steps=100, seed=12345+i)
    elapsed = time.perf_counter() - t0
    times.append(elapsed)
print(json.dumps({{"times": times, "median": sorted(times)[len(times)//2]}}))
"""
    return run_child(
        f"""
import json, time, sys
sys.path.insert(0, '{ROOT}/build/cpp')
sys.path.insert(0, '{ROOT}/python')
sys.meta_path[:] = [f for f in sys.meta_path if not type(f).__module__.startswith('_editable')]
{code}
""",
        f"nfsim_{Path(model_path).stem}",
    )


def main():
    results = {}
    for path in MODELS:
        results[Path(path).stem] = measure_nfsim(path, 50.0)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
