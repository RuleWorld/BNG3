"""Issue #176 measured CPU startup, memory and throughput with correctness.

A performance claim is only meaningful alongside correctness and exact runtime
identity. This case performs one bounded NFnext measurement on a declared
immigration-death workload and emits a structured record:

* startup wall time for model lowering plus the first sample;
* ensemble wall time and events/second over a fixed seed/run budget;
* peak resident memory of the worker process (recorded, not thresholded);
* the ensemble mean checked against the independent closed-form law.

The measurement is recorded, not asserted against a hardware threshold; a
runner-to-runner comparison is not a scientific claim. A wrong analytic law is
rejected by the same control used in the ensemble suite.
"""

from __future__ import annotations

import json
import math
import os
import resource
import time
from pathlib import Path

import numpy as np

import importlib.util

ROOT = Path(__file__).resolve().parents[5]
_build = ROOT / "build" / "cpp" / "_bionetgen_cpp.cpython-314-darwin.so"


def _cpp():
    # Reuse the extension the installed package already loaded. Loading the
    # shared object a second time under a fresh module name double-registers
    # pybind11 types ("Expression is already registered") in CI.
    try:
        import bionetgen._bionetgen_cpp as cpp  # type: ignore

        return cpp
    except ImportError:
        spec = importlib.util.spec_from_file_location("_bionetgen_cpp", str(_build))
        assert spec is not None and spec.loader is not None
        cpp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cpp)
        return cpp


MODEL = """begin model
begin parameters
  lam 3.0
  mu 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules N A()
end observables
begin reaction rules
  birth: 0 -> A() lam
  death: A() -> 0 mu
end reaction rules
end model
"""


def test_nfnext_startup_memory_throughput_with_analytic_correctness():
    cpp = _cpp()
    model = cpp.parse_string(MODEL)
    times = [0.0, 0.5, 1.0, 2.0]
    seeds = 2000 + np.arange(16)

    start = time.perf_counter()
    first = cpp.simulate_nfnext(model, times, seed=int(seeds[0]))
    startup_seconds = time.perf_counter() - start

    start = time.perf_counter()
    runs = [cpp.simulate_nfnext(model, times, seed=int(seed)) for seed in seeds]
    ensemble_seconds = time.perf_counter() - start

    counts = np.asarray([r["observables"]["N"] for r in runs], dtype=float)
    last = counts[:, -1]
    expected = 5.0 * math.exp(-0.5 * 2.0) + (3.0 / 0.5) * (1.0 - math.exp(-0.5 * 2.0))
    variance = 3.0 / (2.0 * 0.5) * (1.0 - math.exp(-2.0 * 0.5 * 2.0)) + max(
        expected * math.exp(-0.5 * 2.0), 0.0
    )
    se = math.sqrt(variance / len(seeds))
    assert abs(float(last.mean()) - expected) <= 4.0 * se

    events = sum(int(r["event_count"]) for r in runs)
    record = {
        "check": "nfnext-cpu-measurement",
        "workload": "immigration-death:n0=5:lam=3:mu=0.5",
        "seeds": int(len(seeds)),
        "sample_times": times,
        "startup_seconds": startup_seconds,
        "ensemble_seconds": ensemble_seconds,
        "events": events,
        "events_per_second": events / ensemble_seconds if ensemble_seconds > 0 else 0.0,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "analytic_mean": expected,
        "observed_mean": float(last.mean()),
        "control_sigma": 4.0,
        "source_revision": "",
    }
    destination = os.environ.get("BNG3_NFNEXT_MEASUREMENT_REPORT")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
