#!/usr/bin/env python3
"""Execute and record the bounded network-free Metal device qualification.

This is validation orchestration, not a second implementation of the kernel.
It reuses the retained physical-device test in
``tests/python/nfnext/test_nfnext_gpu_unary_state.py`` — including its model,
seed, sample times, batch size, analytic CTMC law and tolerances — and emits a
machine-readable receipt with source, toolchain, device and artifact identity.

CUDA is deliberately absent: ``simulate_nfnext_gpu`` refuses that backend and
this receipt must never be presented as CUDA evidence.
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

TEST_PATH = (
    ROOT / "tests/python/nfnext/test_nfnext_gpu_unary_state.py"
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_test_module():
    spec = importlib.util.spec_from_file_location(
        "bng3_issue474_nfnext_device_test", TEST_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the NFnext Metal device test")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(revision: str) -> dict:
    test = _load_test_module()

    # The retained test itself asserts the analytic law, conservation, replay
    # and refusal boundaries.  Running it first prevents a receipt from being
    # emitted for a kernel that merely returned arrays of the right shape.
    test.test_unary_state_change_metal_batch_matches_exact_ctmc_and_replays()

    from bionetgen import gpu_backend_capabilities
    from bionetgen.model import BioNetGenModel, _cpp as cpp

    capabilities = gpu_backend_capabilities()
    metal = next((row for row in capabilities if row["name"] == "metal"), None)
    if metal is None or not metal["compiled"] or not metal["available"]:
        raise RuntimeError("physical Metal device unavailable")

    model = BioNetGenModel(cpp.parse_string(test.MODEL))
    result = model.simulate_nfnext_gpu(
        list(test.TIMES),
        seed=test.SEED,
        batch_size=test.BATCH_SIZE,
        backend="metal",
    )
    if result.backend != "metal" or result.engine != "nfnext-gpu" or not result.device:
        raise RuntimeError("result is not attributable to the Metal NFnext kernel")

    import numpy as np

    p = np.asarray(result.observables["P"])
    u = np.asarray(result.observables["U"])
    counts = np.asarray(result.event_counts)
    checks = []
    for index, time in enumerate(test.TIMES[1:], start=1):
        probability = test._analytic_fraction_p(time)
        expected_mean = test.PARTICLES * probability
        expected_variance = test.PARTICLES * probability * (1.0 - probability)
        observed_mean = float(np.mean(p[:, index]))
        observed_variance = float(np.var(p[:, index], ddof=1))
        standard_error = math.sqrt(expected_variance / test.BATCH_SIZE)
        z = (observed_mean - expected_mean) / standard_error
        variance_ratio = observed_variance / expected_variance
        checks.append(
            {
                "time": time,
                "analytic_mean": expected_mean,
                "observed_mean": observed_mean,
                "mean_z": z,
                "analytic_variance": expected_variance,
                "observed_variance": observed_variance,
                "variance_ratio": variance_ratio,
                "pass": abs(z) <= 5.0 and 0.9 <= variance_ratio <= 1.1,
            }
        )
    if not all(row["pass"] for row in checks):
        raise RuntimeError("analytic CTMC check failed")
    if not np.array_equal(p + u, np.full(p.shape, test.PARTICLES)):
        raise RuntimeError("conservation check failed")
    if int(np.sum(counts)) <= 0:
        raise RuntimeError("kernel recorded no transition events")

    native = Path(cpp.__file__).resolve()
    source_revision = _git("rev-parse", "HEAD")
    if source_revision != revision:
        raise ValueError("requested revision differs from checked-out candidate")
    dirty = bool(_git("status", "--porcelain"))
    if dirty:
        raise ValueError("NFnext device receipt requires a clean checkout")

    return {
        "schema_version": 1,
        "check": "release-nf-gpu",
        "status": "PASS",
        "backend": "metal",
        "scope": "bounded one-type one-site static unary state-change route",
        "source": {
            "revision": source_revision,
            "dirty": dirty,
            "native_module": str(native),
            "native_sha256": _sha256(native),
            "device_test": str(TEST_PATH.relative_to(ROOT)),
            "device_test_sha256": _sha256(TEST_PATH),
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "compiler": subprocess.check_output(
                ["clang", "--version"], text=True
            ).splitlines()[0],
        },
        "device": {
            "name": metal["detail"],
            "compiled": metal["compiled"],
            "available": metal["available"],
            "reported_device": result.device,
            "engine": result.engine,
        },
        "protocol": {
            "sample_times": list(test.TIMES),
            "seed": test.SEED,
            "batch_size": test.BATCH_SIZE,
            "particles": test.PARTICLES,
            "kf": test.KF,
            "kr": test.KR,
        },
        "analytic_law": "P(t)/N = kf/(kf+kr) * (1 - exp(-(kf+kr)t))",
        "checks": checks,
        "conserved": True,
        "total_events": int(np.sum(counts)),
        "timings": {
            "wall_time_ms": result.wall_time_ms,
            "dispatch_wait_time_ms": result.dispatch_wait_time_ms,
        },
        "cuda": {
            "status": "UNSUPPORTED",
            "detail": "network-free CUDA execution is not implemented",
        },
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
        f"NFnext Metal device receipt: {receipt['device']['reported_device']}, "
        f"{len(receipt['checks'])} analytic times, "
        f"{receipt['total_events']} events"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
