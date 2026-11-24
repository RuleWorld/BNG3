#!/usr/bin/env python3
"""Consume exact-revision GPU device receipts for issue #474.

The recorder does not run a device and does not turn compilation, fallback or
one backend into another backend's evidence.  It validates the identity and
content of already-produced Metal and CUDA receipts and emits an
``issue_queue``-compatible report.  Checks whose required execution is absent
are reported as ``NOT_TESTED`` with the blocker named; they are never promoted
to PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

METAL_CHECKS = ("release-metal-device", "release-metal-performance")
CUDA_CHECKS = ("release-cuda-device", "release-cuda-performance")
ALL_CHECKS = (
    "release-metal-device",
    "release-metal-performance",
    "release-cuda-device",
    "release-cuda-performance",
    "release-nf-gpu",
    "release-capability-coverage-474",
)
BUILD_IDENTITY_FIELDS = (
    "device",
    "metal_support",
    "os",
    "hardware",
    "compiler",
    "sdk",
    "cmake",
    "ninja",
    "python",
    "configure_options",
    "native_binary_sha256",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> dict:
    _require(path.is_file(), f"missing receipt: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


def _validate_source(source: dict, revision: str, label: str) -> None:
    _require(source.get("revision") == revision, f"{label}: stale source revision")
    _require(source.get("dirty") is False, f"{label}: receipt from a dirty checkout")


def _row(check: str, status: str, detail: str, receipts: list[Path]) -> dict:
    return {
        "id": check,
        "status": status,
        "stage": "issue-474-device-qualification",
        "check": check,
        "related_issues": [474],
        "evidence_kind": "supported-execution" if status == "PASS" else "diagnostic-only",
        "supported_execution": status == "PASS",
        "detail": detail,
        "receipts": [{"path": str(path), "sha256": _sha256(path)} for path in receipts],
    }


def _validate_parity(path: Path, revision: str, device: str, sha: str) -> dict:
    data = _read(path)
    _require(data.get("source_revision") == revision, "parity receipt: stale revision")
    _require(data.get("source_dirty") is False, "parity receipt: dirty checkout")
    _require(data.get("native_sha256") == sha, "parity receipt: native binary mismatch")
    gpu = data.get("gpu") or {}
    _require(gpu.get("status") == "PASS", "parity gate did not pass")
    _require(gpu.get("backend") == "metal", "parity receipt is not a Metal run")
    inventory = next(
        (row for row in gpu.get("inventory", []) if row.get("name") == "metal"), None
    )
    _require(
        bool(inventory and inventory.get("compiled") and inventory.get("available")),
        "parity receipt does not show a usable compiled Metal device",
    )
    _require(inventory.get("detail") == device, "parity device identity mismatch")
    models = gpu.get("models") or []
    _require(len(models) >= 5, "parity receipt is missing required models")
    _require(
        all(row.get("status") == "PASS" and row.get("backend") == "metal" for row in models),
        "parity receipt has a non-Metal or non-passing model",
    )
    _require(
        any(row.get("model") == "gpu_immigration_death" for row in models),
        "parity receipt is missing the independent immigration-death law",
    )
    return data


def _validate_nfnext(path: Path, revision: str, sha: str) -> dict:
    data = _read(path)
    _validate_source(data.get("source") or {}, revision, "NFnext device receipt")
    _require(
        (data.get("source") or {}).get("native_sha256") == sha,
        "NFnext device receipt: native binary mismatch",
    )
    _require(data.get("status") == "PASS", "NFnext device receipt did not pass")
    _require(data.get("backend") == "metal", "NFnext receipt is not a Metal run")
    _require(data.get("conserved") is True, "NFnext receipt lost conservation")
    _require(all(row.get("pass") for row in data.get("checks", [])), "NFnext analytic check failed")
    _require(data.get("total_events", 0) > 0, "NFnext kernel executed no events")
    return data


def _validate_performance(path: Path, revision: str, sha: str) -> dict:
    data = _read(path)
    _validate_source(data.get("source_identity") or {}, revision, "Metal performance receipt")
    identity = data["source_identity"]
    _require(
        identity.get("native_binary_sha256") == sha,
        "Metal performance receipt: native binary mismatch",
    )
    equivalence = data.get("equivalence") or {}
    _require(equivalence.get("passed") is True, "Metal performance equivalence did not pass")
    _require(data.get("device_assertions"), "no Metal device assertion recorded")
    _require("memory_accounting" in data, "no memory accounting recorded")
    verdicts = (data.get("measurement") or {}).get("verdicts") or {}
    _require("self_cpu_s" in verdicts and "wall_s" in verdicts, "missing timing verdicts")
    rounds = (data.get("measurement") or {}).get("rounds") or []
    _require(rounds, "no measured rounds recorded")
    for row in rounds:
        metrics = ((row.get("b") or {}).get("extra") or {}).get("native_metrics") or {}
        for field in (
            "h2d_transfer_ms",
            "d2h_transfer_ms",
            "memory_usage_bytes",
            "model_prep_time_ms",
            "sim_time_ms",
            "events_per_sec_sim",
        ):
            _require(field in metrics, f"Metal performance receipt missing {field}")
        _require(
            (row.get("b") or {}).get("label") == "gpu:metal",
            "performance round is not attributed to Metal",
        )
    return data


def _validate_crossover(paths: list[Path], revision: str, sha: str) -> list[dict]:
    _require(len(paths) == 6, "expected six crossover batch receipts")
    summaries = []
    for path in paths:
        data = _read(path)
        _validate_source(data.get("source_identity") or {}, revision, str(path))
        _require(
            data["source_identity"].get("native_binary_sha256") == sha,
            f"crossover receipt native mismatch: {path}",
        )
        _require(data.get("device_assertions"), f"no device assertion: {path}")
        verdicts = (data.get("measurement") or {}).get("verdicts") or {}
        _require("self_cpu_s" in verdicts and "wall_s" in verdicts, f"no verdicts: {path}")
        summaries.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "batch_size": data["config"]["batch_size"],
                "cpu_effect": verdicts["self_cpu_s"]["effect_ratio_b_over_a"],
                "wall_effect": verdicts["wall_s"]["effect_ratio_b_over_a"],
                "clock_divergence": (data.get("measurement") or {}).get("clock_divergence", {}).get("agree") is False,
            }
        )
    return sorted(summaries, key=lambda row: row["batch_size"])


def record(args: argparse.Namespace) -> dict:
    revision = args.revision
    _require(revision == _git("rev-parse", "HEAD"), "requested revision differs from checkout")
    _require(not _git("status", "--porcelain"), "exact-revision evidence requires a clean checkout")

    build = _read(args.build_identity)
    for field in BUILD_IDENTITY_FIELDS:
        _require(field in build, f"build identity missing {field}")
    sha = build["native_binary_sha256"]
    device = build["device"]
    native = ROOT / "build/cpp/_bionetgen_cpp.cpython-314-darwin.so"
    if native.is_file():
        _require(_sha256(native) == sha, "built extension does not match build identity")

    parity = _validate_parity(args.parity, revision, device, sha)
    nfnext = _validate_nfnext(args.nfnext, revision, sha)
    performance = _validate_performance(args.performance, revision, sha)
    crossover = _validate_crossover(args.crossover, revision, sha)
    cuda = _read(args.cuda_probe)
    _require(cuda.get("schema_version") == 1, "invalid CUDA availability probe")

    receipts = [args.parity, args.performance, args.nfnext, args.build_identity, args.cuda_probe, *args.crossover]
    pinned = None
    if args.pinned_nfsim:
        pinned = _read(args.pinned_nfsim)
        _require(pinned.get("status") == "PASS", "pinned NFsim reference did not pass")
        _require(
            pinned["device"].get("reported_device") == nfnext["device"].get("reported_device"),
            "pinned NFsim reference used a different device",
        )
        receipts.append(args.pinned_nfsim)

    cuda_blocked = cuda["verdict"]["status"] == "BLOCKED"
    cuda_detail = cuda["verdict"]["detail"]
    if not cuda_blocked:
        raise ValueError(
            "CUDA resources are available; supply real CUDA device receipts before recording #474"
        )

    results = [
        _row(
            "release-metal-device",
            "PASS",
            "Metal finite batch SSA executed on the recorded Apple device with analytic, "
            "conservation, reproducibility and distributional checks.",
            [args.parity, args.build_identity],
        ),
        _row(
            "release-metal-performance",
            "PASS",
            "Paired CPU/Metal measurements with A/A null, statistical equivalence, "
            "transfer costs, memory, startup and crossover ladder.",
            [args.performance, *args.crossover],
        ),
        _row(
            "release-cuda-device",
            "NOT_TESTED",
            "No CUDA device execution: " + cuda_detail,
            [args.cuda_probe],
        ),
        _row(
            "release-cuda-performance",
            "NOT_TESTED",
            "No CUDA device measurement: " + cuda_detail,
            [args.cuda_probe],
        ),
        _row(
            "release-nf-gpu",
            "NOT_TESTED",
            "Bounded Metal unary-state route passes analytic"
            + (" and pinned native NFsim" if pinned else "")
            + " checks, but the full network-free GPU corpus and CUDA reporting are not qualified.",
            ([args.nfnext, args.pinned_nfsim] if pinned else [args.nfnext]),
        ),
        _row(
            "release-capability-coverage-474",
            "NOT_TESTED",
            "backend.gpu is not fully covered: Metal executions recorded, CUDA device "
            "execution externally blocked and network-free CUDA unimplemented.",
            [args.cuda_probe],
        ),
    ]

    return {
        "schema_version": 1,
        "source": {"revision": revision, "dirty": False},
        "artifact": {
            "name": f"issue-474-gpu-device-qualification-{revision}",
            "platform": platform.platform(),
            "host": build,
        },
        "results": results,
        "metal": {
            "device": device,
            "finite_models": [row["model"] for row in parity["gpu"]["models"]],
            "crossover": crossover,
            "native_sha256": sha,
        },
        "network_free": {
            "metal": {
                "device": nfnext["device"]["reported_device"],
                "total_events": nfnext["total_events"],
                "analytic_times": [row["time"] for row in nfnext["checks"]],
            },
            "pinned_nfsim": pinned,
            "cuda": "UNSUPPORTED: network-free CUDA execution is not implemented",
        },
        "cuda": cuda,
        "receipts": [
            {"path": str(path), "sha256": _sha256(path)} for path in receipts
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--parity", required=True, type=Path)
    parser.add_argument("--nfnext", required=True, type=Path)
    parser.add_argument("--performance", required=True, type=Path)
    parser.add_argument("--crossover", required=True, type=Path, action="append")
    parser.add_argument("--pinned-nfsim", type=Path)
    parser.add_argument("--cuda-probe", required=True, type=Path)
    parser.add_argument("--build-identity", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    report = record(args)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    statuses = ", ".join(f"{row['id']}={row['status']}" for row in report["results"])
    print("issue-474 report: " + statuses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
