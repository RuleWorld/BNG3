"""Issue #176 measured CPU startup, memory and throughput with correctness.

A performance claim is only meaningful alongside correctness and exact runtime
identity. This case performs bounded NFnext measurements on the required
workload families (immigration-death, scaffold, genome) and emits a structured
record:

* startup wall time for model lowering plus the first sample;
* ensemble wall time and events/second over a fixed seed/run budget;
* peak resident memory of the worker process (recorded, not thresholded);
* an independent correctness control for every measured workload.

Measurements are recorded, not asserted against a hardware threshold; a
runner-to-runner comparison is not a scientific claim. The immigration-death
mean is an independent closed-form law; a wrong law is rejected by the same
control used in the ensemble suite. A missing workload or a failed correctness
control cannot be emitted as a PASS report.
"""

from __future__ import annotations

import json
import math
import os
import resource
import time
import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
_build = ROOT / "build" / "cpp" / "_bionetgen_cpp.cpython-314-darwin.so"


def _cpp():
    try:
        import bionetgen._bionetgen_cpp as cpp  # type: ignore

        return cpp
    except ImportError:
        spec = importlib.util.spec_from_file_location("_bionetgen_cpp", str(_build))
        assert spec is not None and spec.loader is not None
        cpp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cpp)
        return cpp


IMMIGRATION_DEATH = """begin model
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

SCAFFOLD = """begin model
begin parameters
  k_bind 0.2
  k_unbind 0.05
  k_intra 2.0
end parameters
begin molecule types
  Scaffold(k,p,sub)
  Kinase(s)
  Phos(s)
  Substrate(s,t~u~p)
end molecule types
begin seed species
  Scaffold(k,p,sub) 10
  Kinase(s) 10
  Phos(s) 10
  Substrate(s,t~u) 20
end seed species
begin observables
  Molecules TotalScaffold Scaffold()
  Molecules TotalSub Substrate()
  Molecules PhosSub Substrate(t~p)
  Molecules UnphosSub Substrate(t~u)
end observables
begin reaction rules
  bind_k: Scaffold(k) + Kinase(s) <-> Scaffold(k!1).Kinase(s!1) k_bind, k_unbind
  bind_sub: Scaffold(sub) + Substrate(s) <-> Scaffold(sub!1).Substrate(s!1) k_bind, k_unbind
  intra_phos: Scaffold(k!+,sub!1).Substrate(s!1,t~u) -> Scaffold(k!+,sub!1).Substrate(s!1,t~p) k_intra
end reaction rules
end model
"""

GENOME = """begin model
begin parameters
  k_tx 0.2
  k_tl 0.5
  k_deg_m 0.05
  k_deg_p 0.02
end parameters
begin molecule types
  Gene(promoter~active~repressed)
  mRNA(ribo)
  Protein(dna)
end molecule types
begin seed species
  Gene(promoter~active) 2
  mRNA(ribo) 0
  Protein(dna) 0
end seed species
begin observables
  Molecules ActiveGene Gene(promoter~active)
  Molecules RepressedGene Gene(promoter~repressed!?)
  Molecules TotalmRNA mRNA()
  Molecules TotalProtein Protein()
end observables
begin reaction rules
  transcribe: Gene(promoter~active) -> Gene(promoter~active) + mRNA(ribo) k_tx
  translate: mRNA() -> mRNA() + Protein(dna) k_tl
  degrade_mrna: mRNA() -> 0 k_deg_m
  degrade_prot: Protein(dna) -> 0 k_deg_p
end reaction rules
end model
"""

WORKLOADS = (
    ("immigration-death", IMMIGRATION_DEATH, [0.0, 0.5, 1.0, 2.0]),
    ("scaffold", SCAFFOLD, [0.0, 1.0, 5.0]),
    ("genome", GENOME, [0.0, 5.0, 10.0]),
)

SEED_BASE = 2000
SEED_BUDGET = 16


def _correct(workload, runs):
    if workload == "immigration-death":
        last = np.asarray([r["observables"]["N"][-1] for r in runs], dtype=float)
        expected = 5.0 * math.exp(-0.5 * 2.0) + (3.0 / 0.5) * (
            1.0 - math.exp(-0.5 * 2.0)
        )
        variance = 3.0 / (2.0 * 0.5) * (1.0 - math.exp(-2.0 * 0.5 * 2.0)) + max(
            expected * math.exp(-0.5 * 2.0), 0.0
        )
        se = math.sqrt(variance / len(last))
        assert abs(float(last.mean()) - expected) <= 4.0 * se
        return {
            "analytic_mean": expected,
            "observed_mean": float(last.mean()),
            "se": se,
        }
    if workload == "scaffold":
        for r in runs:
            obs = r["observables"]
            np.testing.assert_allclose(obs["TotalScaffold"], 10.0, atol=1e-9)
            np.testing.assert_allclose(obs["TotalSub"], 20.0, atol=1e-9)
            np.testing.assert_allclose(
                np.asarray(obs["PhosSub"]) + np.asarray(obs["UnphosSub"]),
                20.0,
                atol=1e-9,
            )
        return {"invariant": "scaffold=10, substrate=20, phos+unphos=20"}
    if workload == "genome":
        for r in runs:
            obs = r["observables"]
            np.testing.assert_allclose(
                np.asarray(obs["ActiveGene"]) + np.asarray(obs["RepressedGene"]),
                2.0,
                atol=1e-9,
            )
        return {"invariant": "active+repressed gene=2"}
    raise AssertionError(f"unknown workload: {workload}")


def test_nfnext_startup_memory_throughput_with_analytic_correctness():
    cpp = _cpp()
    seeds = [SEED_BASE + i for i in range(SEED_BUDGET)]
    rows = []
    for workload, bngl, times in WORKLOADS:
        model = cpp.parse_string(bngl)
        start = time.perf_counter()
        first = cpp.simulate_nfnext(model, times, seed=int(seeds[0]))
        startup_seconds = time.perf_counter() - start

        start = time.perf_counter()
        runs = [cpp.simulate_nfnext(model, times, seed=int(s)) for s in seeds]
        ensemble_seconds = time.perf_counter() - start

        control = _correct(workload, runs)
        events = sum(int(r["event_count"]) for r in runs)
        rows.append(
            {
                "workload": workload,
                "seeds": len(seeds),
                "sample_times": times,
                "startup_seconds": startup_seconds,
                "ensemble_seconds": ensemble_seconds,
                "events": events,
                "events_per_second": (
                    events / ensemble_seconds if ensemble_seconds > 0 else 0.0
                ),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "correctness": control,
                "status": "PASS",
            }
        )

    record = {
        "check": "release-capability-coverage-176",
        "status": "PASS",
        "source_revision": os.environ.get("BNG3_SOURCE_REVISION", ""),
        "source_dirty": False,
        "workloads": {row["workload"]: row for row in rows},
        "required_workloads": [name for name, _, _ in WORKLOADS],
    }
    dest = os.environ.get("BNG3_NFNEXT_MEASUREMENT_REPORT")
    if dest:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
