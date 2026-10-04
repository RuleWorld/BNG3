#!/usr/bin/env python3
"""GPU dispatch benchmark: measure prep/launch/H2D/D2H to derive better thresholds."""

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
    ("isomerization", "models/isomerization.bngl", 20.0, 2),
    ("gene_expr_simple", "models/gene_expr_simple.bngl", 500.0, 4),
    ("toy_jim", "models/toy_jim.bngl", 20.0, 101),
    ("egfr_net", "models/performance_test_models/egfr_net.bngl", 10.0, 3749),
]

BATCH_SIZES = [100, 1000, 10000]

def run_child(code: str, what: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", f"""
import sys
sys.path.insert(0, '{ROOT}/build/cpp')
sys.path.insert(0, '{ROOT}/python')
sys.meta_path[:] = [f for f in sys.meta_path if not type(f).__module__.startswith('_editable')]
{code}
        """, str(ROOT)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{what}: child exited {proc.returncode}\n{proc.stderr}")
    return json.loads(proc.stdout)

def measure_gpu_cpu(model_path, t_end, batch, base_seed=12345):
    code = f"""
import json, time
import _bionetgen_cpp as cpp
model = cpp.parse_file("{model_path}")
network = cpp.generate_network(model)

# CPU pool (multi-core)
t0 = time.perf_counter()
res_cpu = cpp.simulate_batch_ssa_cpu(model, network, batch_size={batch}, t_end={t_end}, n_steps=10, threads=0, base_seed={base_seed})
cpu_time = time.perf_counter() - t0

# GPU (Metal)
try:
    t0 = time.perf_counter()
    res_gpu = cpp.simulate_batch_ssa_gpu(model, network, batch_size={batch}, t_end={t_end}, n_steps=10, base_seed={base_seed})
    gpu_time = time.perf_counter() - t0
    gpu_ok = True
except Exception as e:
    gpu_time = None
    gpu_ok = False

print(json.dumps({{
    "cpu_time_ms": cpu_time * 1000,
    "gpu_time_ms": gpu_time * 1000 if gpu_ok else None,
    "gpu_ok": gpu_ok,
    "cpu_events": res_cpu.get("total_events", 0),
    "gpu_events": res_gpu.get("total_events", 0) if gpu_ok else None,
}}))
"""
    return run_child(code, f"gpu_dispatch_{Path(model_path).stem}_{batch}")

def main():
    results = []
    for name, path, t_end, n_reactions in MODELS:
        for batch in BATCH_SIZES:
            print(f"Measuring {name} batch={batch}...")
            results.append(measure_gpu_cpu(path, t_end, batch))
    
    print(json.dumps(results, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
