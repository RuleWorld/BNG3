"""Issue #174 published CPU benchmark evidence with correctness guards.

A performance claim is only publishable when runtime identity, declared
workloads and independent correctness controls travel with the timings. This
case validates the retained bench/baseline.json manifest and emits a structured
measurement record; it never re-times a workload or compares across machines.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BASELINE = ROOT / "bench" / "baseline.json"
COMPONENTS = ("netgen", "ssa_batch", "ode", "out_write", "py_import", "py_load")
GUARDS = (
    "netgen_sha",
    "ssa_events",
    "ode_digest",
    "out_write_hashes",
    "py_load_counts",
)


def _load():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_benchmark_manifest_covers_required_cpu_workloads():
    doc = _load()
    meta = doc["meta"]
    for key in ("git", "host", "machine", "python", "cpu_count", "reps", "weights"):
        assert key in meta and meta[key] not in (None, "", []), f"meta.{key} missing"
    assert set(doc["components"]) == set(COMPONENTS)
    assert math.isclose(sum(meta["weights"].values()), 1.0, abs_tol=1e-9)
    for name in COMPONENTS:
        row = doc["components"][name]
        assert len(row["reps"]) == meta["reps"]
        assert row["min"] <= row["median"] <= row["mean"]
    for guard in GUARDS:
        assert guard in doc["guards"] and doc["guards"][guard] not in (None, "", [])


def test_benchmark_correctness_guards_are_retained():
    doc = _load()
    guards = doc["guards"]
    # Guards are retained as serialized strings in the published manifest.
    for name in (
        "ssa_events",
        "ode_digest",
        "out_write_hashes",
        "netgen_sha",
        "py_load_counts",
    ):
        assert isinstance(guards[name], str) and guards[name], f"guard {name} empty"
    assert len(guards["netgen_sha"]) == 64
    assert "iso" in guards["ssa_events"] and "ge" in guards["ssa_events"]
    assert (
        ".cdat" in guards["out_write_hashes"] and ".gdat" in guards["out_write_hashes"]
    )


def test_benchmark_measurement_record_is_emitted():
    doc = _load()
    record = {
        "check": "cpu-benchmark-identity",
        "source_revision": doc["meta"]["git"],
        "host": doc["meta"]["host"],
        "machine": doc["meta"]["machine"],
        "python": doc["meta"]["python"],
        "components": list(doc["components"]),
        "guards": list(doc["guards"]),
        "composite_mean": doc["composite"]["mean"],
        "gpu_scope": "#474 (separate device acceptance; not measured here)",
    }
    destination = os.environ.get("BNG3_CPU_BENCHMARK_REPORT")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
