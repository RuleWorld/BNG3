#!/usr/bin/env python3
"""Record bounded network-free Metal coverage across workload classes.

Validation orchestration only: the kernels and their rejections are owned by
``cpp/engine/gpu/NfnextMetalBackend.mm`` and ``NfnextGpuBackend.cpp``. This
recorder reuses the public ``simulate_nfnext_gpu`` API and prespecified
analytic laws; it does not implement a second kernel or a second RNG.

No pathwise CPU/GPU or native/GPU claim is made: construction and draw ordering
are different. Device/device replay within one kernel construction is the only
equality claim. All other comparisons are distributional with fixed seeds,
fixed budgets and a Bonferroni-corrected normal threshold.

CUDA is deliberately absent: the network-free entry point refuses that backend
and this receipt must never be presented as CUDA evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from scipy.linalg import expm

from bionetgen import gpu_backend_capabilities
from bionetgen.model import BioNetGenModel, _cpp as cpp

TWO_STATE_MODEL = """begin model
begin parameters
  kf 0.5
  kr 0.3
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) {particles}
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) -> A(x~p) kf
  A(x~p) -> A(x~u) kr
end reaction rules
end model
"""

THREE_STATE_MODEL = """begin model
begin parameters
  k1 0.8
  k2 0.2
end parameters
begin molecule types
  A(x~u~p~q)
end molecule types
begin seed species
  A(x~u) 64
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
  Molecules Q A(x~q)
end observables
begin reaction rules
  A(x~u) -> A(x~p) k1
  A(x~p) -> A(x~u) k2
  A(x~p) -> A(x~q) k1
  A(x~q) -> A(x~p) k2
end reaction rules
end model
"""

BONDED_MODEL = """begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 1
  B(a) 1
end seed species
begin observables
  Molecules A_free A(b)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 1.0
end reaction rules
end model
"""

COMPARTMENT_MODEL = """begin model
begin compartments
  C 3 1
end compartments
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u)@C 10
end seed species
begin observables
  Molecules U A(x~u)
end observables
begin reaction rules
  A(x~u)@C -> A(x~p)@C 0.5
end reaction rules
end model
"""

DELAYED_MODEL = """begin model
begin parameters
  kf 0.5
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 10
end seed species
begin observables
  Molecules U A(x~u)
end observables
begin reaction rules
  A(x~u) -> A(x~p) kf delay=1
end reaction rules
end model
"""

# Prespecified budgets. No threshold is changed after seeing a measurement.
BUDGET = {
    "alpha": 0.001,
    "variance_ratio_min": 0.85,
    "variance_ratio_max": 1.15,
    "conservation_atol": 1e-5,
}

WORKLOADS = (
    {
        "class": "two_state_ctmc",
        "source": TWO_STATE_MODEL.format(particles=100),
        "seed": 474910,
        "batch_size": 2048,
        "times": (0.0, 0.5, 1.0, 2.0, 5.0),
        "particles": 100,
        "observables": ("U", "P"),
        "comparisons": 8,
        "law": "two-state reversible CTMC, P(t)/N = kf/(kf+kr)(1-exp(-(kf+kr)t))",
    },
    {
        "class": "three_state_chain",
        "source": THREE_STATE_MODEL,
        "seed": 474911,
        "batch_size": 2048,
        "times": (0.0, 0.5, 1.0, 2.0, 5.0),
        "particles": 64,
        "observables": ("U", "P", "Q"),
        "comparisons": 12,
        "law": "three-state reversible chain, p(t) = p(0) expm(Q t)",
    },
    {
        "class": "particle_heavy",
        "source": TWO_STATE_MODEL.format(particles=256),
        "seed": 474912,
        "batch_size": 1024,
        "times": (0.0, 0.25, 0.5, 1.0, 2.0),
        "particles": 256,
        "observables": ("U", "P"),
        "comparisons": 8,
        "law": "two-state reversible CTMC with a bounded 256-particle population",
    },
)

REFUSALS = (
    ("binding_topology", BONDED_MODEL, "unary single-site state-change"),
    ("bound_rule_constraint", TWO_STATE_MODEL.format(particles=10).replace(
        "A(x~u) -> A(x~p) kf", "A(x~u!+) -> A(x~p!+) kf"
    ), "invariant free-site constraint"),
    ("compartment", COMPARTMENT_MODEL, "compartments are outside"),
    ("delayed_rule", DELAYED_MODEL, "delayed rules are outside"),
    ("cuda_backend", TWO_STATE_MODEL.format(particles=10),
     "network-free CUDA execution is not implemented"),
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metal_device() -> dict:
    metal = next(
        (row for row in gpu_backend_capabilities() if row["name"] == "metal"),
        None,
    )
    if not metal or not metal["compiled"] or not metal["available"]:
        raise RuntimeError("physical Metal device unavailable")
    return metal


def _analytic_fractions(spec: dict) -> np.ndarray:
    times = np.asarray(spec["times"], dtype=float)
    if spec["class"] == "three_state_chain":
        k1, k2 = 0.8, 0.2
        generator = np.array(
            [[-k1, k1, 0.0], [k2, -(k1 + k2), k1], [0.0, k2, -k2]]
        )
        start = np.array([1.0, 0.0, 0.0])
        return np.vstack([start @ expm(generator * t) for t in times])
    kf, kr = 0.5, 0.3
    p = kf / (kf + kr) * (1.0 - np.exp(-(kf + kr) * times))
    return np.column_stack([1.0 - p, p])


def _check_workload(spec: dict) -> dict:
    fractions = _analytic_fractions(spec)
    names = list(spec["observables"])
    from statistics import NormalDist

    z_limit = NormalDist().inv_cdf(
        1.0 - BUDGET["alpha"] / (2 * spec["comparisons"])
    )
    model = BioNetGenModel(cpp.parse_string(spec["source"]))
    raw = model.simulate_nfnext_gpu(
        list(spec["times"]),
        seed=spec["seed"],
        batch_size=spec["batch_size"],
        backend="metal",
    )
    if raw.backend != "metal" or raw.engine != "nfnext-gpu" or not raw.device:
        raise RuntimeError("result is not attributable to the Metal NFnext kernel")
    if list(raw.observable_names) != names:
        raise RuntimeError(f"unexpected observables: {raw.observable_names}")
    counts = {name: np.asarray(raw.observables[name], dtype=float) for name in names}
    for name, values in counts.items():
        if values.shape != (spec["batch_size"], len(spec["times"])):
            raise RuntimeError(f"invalid shape for {name}: {values.shape}")
        if not np.isfinite(values).all() or (values < 0).any():
            raise RuntimeError(f"non-finite or negative counts for {name}")
    total = sum(counts[name] for name in names)
    expected_total = np.full(total.shape, spec["particles"])
    if not np.allclose(total, expected_total, rtol=0.0, atol=BUDGET["conservation_atol"]):
        raise RuntimeError("particle conservation failed")

    checks = []
    for time_index in range(1, len(spec["times"])):
        for obs_index, name in enumerate(names):
            expected_mean = spec["particles"] * fractions[time_index, obs_index]
            expected_variance = spec["particles"] * fractions[time_index, obs_index] * (
                1.0 - fractions[time_index, obs_index]
            )
            if expected_variance <= 0.0:
                continue
            observed = counts[name][:, time_index]
            observed_mean = float(np.mean(observed))
            observed_variance = float(np.var(observed, ddof=1))
            standard_error = math.sqrt(expected_variance / spec["batch_size"])
            z = (observed_mean - expected_mean) / standard_error
            ratio = observed_variance / expected_variance
            passed = (
                abs(z) <= z_limit
                and BUDGET["variance_ratio_min"] <= ratio <= BUDGET["variance_ratio_max"]
            )
            checks.append(
                {
                    "time": spec["times"][time_index],
                    "observable": name,
                    "expected_mean": expected_mean,
                    "observed_mean": observed_mean,
                    "mean_z": z,
                    "variance_ratio": ratio,
                    "pass": bool(passed),
                }
            )
    if not checks or not all(row["pass"] for row in checks):
        raise RuntimeError(f"analytic law check failed for {spec['class']}: {checks}")

    events = np.asarray(raw.event_counts, dtype=np.int64)
    if int(events.sum()) <= 0 or (events < 0).any():
        raise RuntimeError("kernel recorded no events or a negative event count")
    throughput = (
        float(events.sum()) / (raw.dispatch_wait_time_ms / 1000.0)
        if raw.dispatch_wait_time_ms > 0.0
        else 0.0
    )
    if throughput <= 0.0:
        raise RuntimeError("no device throughput measurement")
    result = {
        "class": spec["class"],
        "law": spec["law"],
        "device": raw.device,
        "seed": spec["seed"],
        "batch_size": spec["batch_size"],
        "particles": spec["particles"],
        "sample_times": list(spec["times"]),
        "comparisons": spec["comparisons"],
        "z_limit": z_limit,
        "checks": checks,
        "conserved": True,
        "total_events": int(events.sum()),
        "timings_ms": {
            "setup": raw.setup_time_ms,
            "dispatch_wait": raw.dispatch_wait_time_ms,
            "wall": raw.wall_time_ms,
        },
        "device_memory_bytes": raw.device_memory_bytes,
        "events_per_sec_dispatch": throughput,
        "pathwise_claim": False,
    }
    if spec["class"] == "two_state_ctmc":
        replay = model.simulate_nfnext_gpu(
            list(spec["times"]),
            seed=spec["seed"],
            batch_size=spec["batch_size"],
            backend="metal",
        )
        for name in names:
            np.testing.assert_array_equal(
                np.asarray(raw.observables[name]),
                np.asarray(replay.observables[name]),
            )
        np.testing.assert_array_equal(raw.event_counts, replay.event_counts)
        result["same_kernel_replay"] = True
    return result


def verify(revision: str) -> dict:
    device = _metal_device()
    workloads = [_check_workload(spec) for spec in WORKLOADS]
    refusals = []
    for name, source, expected in REFUSALS:
        model = BioNetGenModel(cpp.parse_string(source))
        selected = "cuda" if name == "cuda_backend" else "metal"
        try:
            model.simulate_nfnext_gpu(
                [0.0, 1.0], batch_size=16, backend=selected
            )
        except RuntimeError as exc:
            if expected not in str(exc):
                raise RuntimeError(f"{name} refused with an unexpected reason: {exc}")
            refusals.append({"class": name, "status": "REFUSED", "reason": str(exc)})
        else:
            raise RuntimeError(f"{name} was incorrectly admitted to the GPU route")

    native = Path(cpp.__file__).resolve()
    source_revision = _git("rev-parse", "HEAD")
    if source_revision != revision:
        raise ValueError("requested revision differs from checked-out candidate")
    if _git("status", "--porcelain"):
        raise ValueError("network-free device receipt requires a clean checkout")

    return {
        "schema_version": 1,
        "check": "release-nf-gpu-workloads",
        "status": "PASS",
        "scope": (
            "bounded unary single-site state-change Metal route: two-state CTMC, "
            "three-state chain and bounded particle-heavy ensemble; unsupported "
            "workload classes are explicitly refused"
        ),
        "source": {
            "revision": source_revision,
            "dirty": False,
            "native_module": str(native),
            "native_sha256": _sha256(native),
            "recorder": str(Path(__file__).relative_to(ROOT)),
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "compiler": subprocess.check_output(
                ["clang", "--version"], text=True
            ).splitlines()[0],
        },
        "device": {
            "name": device["detail"],
            "backend": "metal",
            "compiled": device["compiled"],
            "available": device["available"],
        },
        "budget": BUDGET,
        "workloads": workloads,
        "refusals": refusals,
        "cuda": {
            "status": "UNSUPPORTED",
            "detail": "network-free CUDA execution is not implemented",
        },
        "full_corpus_claimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    receipt = verify(args.revision)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        f"NFnext Metal workloads: {len(receipt['workloads'])} classes, "
        f"{len(receipt['refusals'])} explicit refusals, "
        f"{sum(row['total_events'] for row in receipt['workloads'])} events"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
