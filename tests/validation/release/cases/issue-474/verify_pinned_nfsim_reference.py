#!/usr/bin/env python3
"""Independent pinned-native-NFsim reference for the bounded NFnext GPU route.

This executes the pinned NFsim oracle source/artifact from
``provenance/upstreams.lock.yml`` on the same two-state CTMC used by the
physical Metal test.  It is a distributional comparison with a fixed, recorded
seed budget and Bonferroni-controlled error; equal seeds are not used because
the GPU and native kernels have different construction and draw ordering.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_PATH = ROOT / "tests/python/nfnext/test_nfnext_gpu_unary_state.py"
LOCK_PATH = ROOT / "provenance/upstreams.lock.yml"


def _load_test_module():
    spec = importlib.util.spec_from_file_location(
        "bng3_issue474_nfsim_reference_test", TEST_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the NFnext Metal device test")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lock():
    # The lock is JSON despite its .yml suffix.
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _parse_gdat(path: Path) -> list[list[float]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append([float(field) for field in line.split()])
    return rows


def verify(nfsim: Path, source: Path, runs: int, seed0: int) -> dict:
    lock = _lock()
    pinned_revision = lock["sources"]["nfsim"]["revision"]
    pinned_digest = lock["oracles"]["nfsim"]["artifact_digest"].split(":", 1)[1]
    source_revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if source_revision != pinned_revision:
        raise ValueError("NFsim source is not at the pinned revision")
    digest = _sha256(nfsim)
    if digest != pinned_digest:
        raise ValueError("NFsim executable does not match the pinned artifact digest")

    test = _load_test_module()
    from bionetgen import gpu_backend_capabilities
    from bionetgen.model import BioNetGenModel, _cpp as cpp

    metal = next(
        (row for row in gpu_backend_capabilities() if row["name"] == "metal"), None
    )
    if metal is None or not metal["compiled"] or not metal["available"]:
        raise RuntimeError("physical Metal device unavailable")

    work = Path(
        subprocess.check_output(
            ["mktemp", "-d", "/private/var/folders/cl/rt1592vn0sq5jw5vv4shrs4m0000gn/T/opencode/bng3-nfsim-474.XXXXXX"],
            text=True,
        ).strip()
    )
    model = BioNetGenModel(cpp.parse_string(test.MODEL))
    xml = work / "unary.xml"
    model.write_xml(str(xml))

    times_text = ",".join(str(value) for value in test.TIMES)
    samples: dict[float, list[float]] = {t: [] for t in test.TIMES}
    for offset in range(runs):
        out = work / f"run{offset}.gdat"
        proc = subprocess.run(
            [
                str(nfsim),
                "-xml", str(xml),
                "-sim", str(test.TIMES[-1]),
                "-oTimes", times_text,
                "-seed", str(seed0 + offset),
                "-o", str(out),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pinned NFsim failed: {proc.stderr[:500]}")
        rows = _parse_gdat(out)
        if len(rows) != len(test.TIMES):
            raise RuntimeError("pinned NFsim output grid mismatch")
        for row, time in zip(rows, test.TIMES):
            if abs(row[0] - time) > 1e-9:
                raise RuntimeError("pinned NFsim output time mismatch")
            samples[time].append(row[2])  # observable P

    gpu = model.simulate_nfnext_gpu(
        list(test.TIMES),
        seed=test.SEED,
        batch_size=test.BATCH_SIZE,
        backend="metal",
    )
    import numpy as np

    gpu_p = np.asarray(gpu.observables["P"])

    alpha = 0.001
    comparisons = 2 * (len(test.TIMES) - 1)
    z_threshold = statistics.NormalDist().inv_cdf(1.0 - alpha / (2 * comparisons))
    checks = []
    for time in test.TIMES[1:]:
        probability = test._analytic_fraction_p(time)
        expected_mean = test.PARTICLES * probability
        expected_variance = test.PARTICLES * probability * (1.0 - probability)
        native = np.asarray(samples[time], dtype=float)
        native_mean = float(np.mean(native))
        native_var = float(np.var(native, ddof=1))
        native_z = (native_mean - expected_mean) / math.sqrt(
            expected_variance / runs
        )
        device = gpu_p[:, list(test.TIMES).index(time)].astype(float)
        device_mean = float(np.mean(device))
        pooled_se = math.sqrt(
            native_var / runs + float(np.var(device, ddof=1)) / len(device)
        )
        cross_z = (device_mean - native_mean) / pooled_se
        checks.append(
            {
                "time": time,
                "analytic_mean": expected_mean,
                "native_mean": native_mean,
                "native_variance": native_var,
                "native_mean_z": native_z,
                "native_variance_ratio": native_var / expected_variance,
                "metal_mean": device_mean,
                "metal_native_mean_z": cross_z,
                "pass": (
                    abs(native_z) <= z_threshold
                    and 0.8 <= native_var / expected_variance <= 1.2
                    and abs(cross_z) <= z_threshold
                ),
            }
        )
    if not all(row["pass"] for row in checks):
        raise RuntimeError("pinned native NFsim / Metal distributional check failed")

    native = np.asarray([samples[t] for t in test.TIMES[1:]], dtype=float)
    wrong_mean = test.PARTICLES * (1.0 - math.exp(-test.KF * test.TIMES[-1]))
    right_probability = test._analytic_fraction_p(test.TIMES[-1])
    right_se = math.sqrt(
        test.PARTICLES
        * right_probability
        * (1.0 - right_probability)
        / runs
    )
    wrong_law_rejected = abs(float(native[:, -1].mean()) - wrong_mean) > 10.0 * right_se
    if not wrong_law_rejected:
        raise RuntimeError("wrong-law negative control did not reject")

    shutil.rmtree(work)

    return {
        "schema_version": 1,
        "check": "pinned-native-nfsim-bounded-reference",
        "status": "PASS",
        "source": {
            "nfsim_source": str(source),
            "nfsim_revision": source_revision,
            "nfsim_executable": str(nfsim),
            "nfsim_sha256": digest,
            "lock_digest": pinned_digest,
            "bng3_revision": subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
            ).strip(),
        },
        "device": {
            "backend": "metal",
            "name": metal["detail"],
            "reported_device": gpu.device,
        },
        "budget": {
            "native_runs": runs,
            "native_first_seed": seed0,
            "metal_batch_size": test.BATCH_SIZE,
            "metal_seed": test.SEED,
            "alpha": alpha,
            "bonferroni_z_threshold": z_threshold,
        },
        "analytic_law": "P(t)/N = kf/(kf+kr) * (1 - exp(-(kf+kr)t))",
        "checks": checks,
        "wrong_law_rejected": wrong_law_rejected,
        "scope": (
            "bounded one-type one-site static unary state-change route only; "
            "not the full network-free corpus and not CUDA"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nfsim", required=True, type=Path)
    parser.add_argument("--nfsim-source", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=256)
    parser.add_argument("--seed0", type=int, default=1000)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    receipt = verify(args.nfsim, args.nfsim_source, args.runs, args.seed0)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        f"Pinned NFsim reference PASS: {args.runs} runs at "
        f"{receipt['source']['nfsim_revision'][:10]}, "
        f"{len(receipt['checks'])} analytic times compared to Metal"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
