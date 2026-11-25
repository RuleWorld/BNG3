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
CUDA_BUILD_IDENTITY_FIELDS = (
    "device",
    "os",
    "compiler",
    "native_binary_sha256",
)
REQUIRED_TIER_NF_MODELS = ("motor", "simple_system", "localfunc", "tlbr")


def _is_hex_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value.lower())
    )


def _validate_nf_corpus(path: Path, revision: str, *, backend: str) -> dict:
    label = "Metal" if backend == "metal" else "CUDA"
    data = _read(path)
    _require(
        data.get("kind") == "issue474-nfnext-gpu-corpus-receipt",
        f"NF-GPU {label} corpus receipt: unexpected kind",
    )
    _require(
        data.get("source_revision") == revision,
        f"NF-GPU {label} corpus receipt: stale source revision",
    )
    _require(
        data.get("source_dirty") is False,
        f"NF-GPU {label} corpus receipt: receipt from a dirty checkout",
    )
    _require(
        data.get("backend") == backend,
        f"NF-GPU {label} corpus receipt: backend mismatch ({data.get('backend')!r})",
    )
    _require(
        bool(data.get("device")),
        f"NF-GPU {label} corpus receipt: missing device identity",
    )
    _require(
        data.get("tier") == "TIER_NF",
        f"NF-GPU {label} corpus receipt: expected TIER_NF",
    )
    _require(
        _is_hex_sha256(data.get("oracle_nfsim_sha256")),
        f"NF-GPU {label} corpus receipt: invalid pinned NFsim oracle digest",
    )
    _require(
        _is_hex_sha256(data.get("oracle_bng2_sha256")),
        f"NF-GPU {label} corpus receipt: invalid pinned BNG2 oracle digest",
    )
    _require(
        data.get("result") == "pass",
        f"NF-GPU {label} corpus receipt: overall result is not pass",
    )
    cases = data.get("cases") or []
    by_model = {str(row.get("model")): row for row in cases if isinstance(row, dict)}
    missing = [name for name in REQUIRED_TIER_NF_MODELS if name not in by_model]
    _require(
        not missing,
        f"NF-GPU {label} corpus receipt: missing required TIER_NF model(s): {missing}",
    )
    for name in REQUIRED_TIER_NF_MODELS:
        row = by_model[name]
        _require(
            row.get("backend") == backend,
            f"NF-GPU {label} corpus receipt ({name}): backend mismatch",
        )
        _require(
            row.get("passed") is True,
            f"NF-GPU {label} corpus receipt ({name}): case did not pass",
        )
        _require(
            row.get("deterministic_replay") is True,
            f"NF-GPU {label} corpus receipt ({name}): deterministic replay did not pass",
        )
        dist = row.get("distribution") or {}
        _require(
            dist.get("passed") is True and not dist.get("failures"),
            f"NF-GPU {label} corpus receipt ({name}): distributional comparison failed",
        )
        _require(
            int(row.get("gpu_total_events", 0)) > 0,
            f"NF-GPU {label} corpus receipt ({name}): zero GPU events executed",
        )
    return data


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> dict:
    _require(path.is_file(), f"missing receipt: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def _validate_source(source: dict, revision: str, label: str) -> None:
    _require(source.get("revision") == revision, f"{label}: stale source revision")
    # The benchmark harness calls the cleanliness field ``source_dirty`` while
    # the standalone device receipts use ``dirty``; both mean the same check.
    dirty = source.get("dirty", source.get("source_dirty"))
    _require(dirty is False, f"{label}: receipt from a dirty checkout")


def _row(check: str, status: str, detail: str, receipts: list[Path]) -> dict:
    return {
        "id": check,
        "status": status,
        "stage": "issue-474-device-qualification",
        "check": check,
        "related_issues": [474],
        "evidence_kind": (
            "supported-execution" if status == "PASS" else "diagnostic-only"
        ),
        "supported_execution": status == "PASS",
        "detail": detail,
        "receipts": [{"path": str(path), "sha256": _sha256(path)} for path in receipts],
    }


def _validate_parity(
    path: Path, revision: str, device: str, sha: str, *, backend: str = "metal"
) -> dict:
    label = "Metal" if backend == "metal" else "CUDA"
    data = _read(path)
    _require(data.get("source_revision") == revision, "parity receipt: stale revision")
    _require(data.get("source_dirty") is False, "parity receipt: dirty checkout")
    _require(data.get("native_sha256") == sha, "parity receipt: native binary mismatch")
    gpu = data.get("gpu") or {}
    _require(gpu.get("status") == "PASS", "parity gate did not pass")
    _require(gpu.get("backend") == backend, f"parity receipt is not a {label} run")
    inventory = next(
        (row for row in gpu.get("inventory", []) if row.get("name") == backend), None
    )
    _require(
        bool(inventory and inventory.get("compiled") and inventory.get("available")),
        f"parity receipt does not show a usable compiled {label} device",
    )
    _require(inventory.get("detail") == device, "parity device identity mismatch")
    models = gpu.get("models") or []
    _require(len(models) >= 5, "parity receipt is missing required models")
    _require(
        all(
            row.get("status") == "PASS" and row.get("backend") == backend
            for row in models
        ),
        f"parity receipt has a non-{label} or non-passing model",
    )
    _require(
        any(row.get("model") == "gpu_immigration_death" for row in models),
        "parity receipt is missing the independent immigration-death law",
    )
    return data


def _validate_nfnext(
    path: Path, revision: str, sha: str, *, backend: str = "metal"
) -> dict:
    label = "Metal" if backend == "metal" else "CUDA"
    data = _read(path)
    _validate_source(
        data.get("source") or {}, revision, f"NFnext {label} device receipt"
    )
    _require(
        (data.get("source") or {}).get("native_sha256") == sha,
        f"NFnext {label} device receipt: native binary mismatch",
    )
    _require(
        data.get("status") == "PASS", f"NFnext {label} device receipt did not pass"
    )
    _require(data.get("backend") == backend, f"NFnext receipt is not a {label} run")
    _require(data.get("conserved") is True, "NFnext receipt lost conservation")
    _require(
        all(row.get("pass") for row in data.get("checks", [])),
        "NFnext analytic check failed",
    )
    _require(data.get("total_events", 0) > 0, "NFnext kernel executed no events")
    return data


def _validate_performance(
    path: Path, revision: str, sha: str, *, backend: str = "metal"
) -> dict:
    label = "Metal" if backend == "metal" else "CUDA"
    data = _read(path)
    _validate_source(
        data.get("source_identity") or {}, revision, f"{label} performance receipt"
    )
    identity = data["source_identity"]
    _require(
        identity.get("native_binary_sha256") == sha,
        f"{label} performance receipt: native binary mismatch",
    )
    equivalence = data.get("equivalence") or {}
    _require(
        equivalence.get("passed") is True,
        f"{label} performance equivalence did not pass",
    )
    _require(data.get("device_assertions"), f"no {label} device assertion recorded")
    _require("memory_accounting" in data, "no memory accounting recorded")
    verdicts = (data.get("measurement") or {}).get("verdicts") or {}
    _require(
        "self_cpu_s" in verdicts and "wall_s" in verdicts, "missing timing verdicts"
    )
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
            _require(field in metrics, f"{label} performance receipt missing {field}")
        _require(
            (row.get("b") or {}).get("label") == f"gpu:{backend}",
            f"performance round is not attributed to {label}",
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
        _require(
            "self_cpu_s" in verdicts and "wall_s" in verdicts, f"no verdicts: {path}"
        )
        summaries.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "batch_size": data["config"]["batch_size"],
                "cpu_effect": verdicts["self_cpu_s"]["effect_ratio_b_over_a"],
                "wall_effect": verdicts["wall_s"]["effect_ratio_b_over_a"],
                "clock_divergence": (data.get("measurement") or {})
                .get("clock_divergence", {})
                .get("agree")
                is False,
            }
        )
    return sorted(summaries, key=lambda row: row["batch_size"])


def record(args: argparse.Namespace) -> dict:
    revision = args.revision
    _require(
        revision == _git("rev-parse", "HEAD"),
        "requested revision differs from checkout",
    )
    _require(
        not _git("status", "--porcelain"),
        "exact-revision evidence requires a clean checkout",
    )

    build = _read(args.build_identity)
    for field in BUILD_IDENTITY_FIELDS:
        _require(field in build, f"build identity missing {field}")
    sha = build["native_binary_sha256"]
    device = build["device"]
    if platform.system().lower() == "darwin":
        native_candidates = sorted((ROOT / "build/cpp").glob("_bionetgen_cpp*.so"))
        if len(native_candidates) == 1:
            _require(
                _sha256(native_candidates[0]) == sha,
                "built extension does not match build identity",
            )

    parity = _validate_parity(args.parity, revision, device, sha, backend="metal")
    # The finite Metal lane can be recorded on an exact-main checkout that has
    # no network-free device receipt; in that case the unqualified nf-gpu row
    # says so explicitly instead of borrowing the finite result.
    nfnext = (
        _validate_nfnext(args.nfnext, revision, sha, backend="metal")
        if args.nfnext
        else None
    )
    _validate_performance(args.performance, revision, sha, backend="metal")
    crossover = _validate_crossover(args.crossover, revision, sha)

    cuda_receipt_args = (
        args.cuda_build_identity,
        args.cuda_parity,
        args.cuda_performance,
        args.cuda_crossover,
    )
    has_any_cuda_receipt = any(cuda_receipt_args)
    has_all_cuda_receipts = all(cuda_receipt_args)
    if has_any_cuda_receipt and not has_all_cuda_receipts:
        raise ValueError(
            "supply --cuda-build-identity, --cuda-parity, --cuda-performance, and "
            "six --cuda-crossover receipts together when recording CUDA execution"
        )

    cuda = _read(args.cuda_probe) if args.cuda_probe else None
    if cuda is not None:
        _require(cuda.get("schema_version") == 1, "invalid CUDA availability probe")

    receipts = [
        args.parity,
        args.performance,
        args.build_identity,
        *args.crossover,
    ]
    if args.cuda_probe:
        receipts.append(args.cuda_probe)
    if args.nfnext:
        receipts.append(args.nfnext)
    workloads = None
    if args.nfnext_workloads:
        workloads = _read(args.nfnext_workloads)
        _require(workloads.get("status") == "PASS", "workload receipt did not pass")
        _require(
            workloads["device"]["backend"] == "metal", "workload receipt is not Metal"
        )
        _require(
            workloads.get("full_corpus_claimed") is False,
            "workload receipt must not claim the full network-free corpus",
        )
        _require(
            workloads["cuda"]["status"]
            in {"UNSUPPORTED", "NOT_RUN_HERE", "NOT_TESTED_IN_THIS_RECEIPT"},
            "workload receipt claims CUDA",
        )
        _require(
            len(workloads.get("workloads", [])) >= 3,
            "workload receipt has too few classes",
        )
        _require(workloads.get("refusals"), "workload receipt has no explicit refusals")
        _require(
            all(
                row.get("device_memory_bytes", 0) > 0 and row.get("total_events", 0) > 0
                for row in workloads["workloads"]
            ),
            "workload receipt is missing device/memory/throughput evidence",
        )
        _validate_source(
            workloads.get("source") or {}, revision, "NFnext workload receipt"
        )
        _require(
            (workloads["source"]).get("native_sha256") == sha,
            "NFnext workload receipt: native binary mismatch",
        )
        receipts.append(args.nfnext_workloads)
    pinned = None
    if args.pinned_nfsim:
        pinned = _read(args.pinned_nfsim)
        _require(pinned.get("status") == "PASS", "pinned NFsim reference did not pass")
        _require(
            nfnext is not None
            and pinned["device"].get("reported_device")
            == nfnext["device"].get("reported_device"),
            "pinned NFsim reference requires matching Metal NFnext device receipt",
        )
        receipts.append(args.pinned_nfsim)

    cuda_section: dict | None = None
    cuda_nfnext = None
    cuda_device_name = ""
    cuda_crossover: list[dict] = []
    if has_all_cuda_receipts:
        cuda_build = _read(args.cuda_build_identity)
        for field in CUDA_BUILD_IDENTITY_FIELDS:
            _require(field in cuda_build, f"CUDA build identity missing {field}")
        cuda_sha = cuda_build["native_binary_sha256"]
        cuda_device_name = cuda_build["device"]
        cuda_parity = _validate_parity(
            args.cuda_parity, revision, cuda_device_name, cuda_sha, backend="cuda"
        )
        _validate_performance(args.cuda_performance, revision, cuda_sha, backend="cuda")
        cuda_crossover = _validate_crossover(args.cuda_crossover, revision, cuda_sha)
        receipts.extend(
            [
                args.cuda_build_identity,
                args.cuda_parity,
                args.cuda_performance,
                *args.cuda_crossover,
            ]
        )
        if args.cuda_nfnext:
            cuda_nfnext = _validate_nfnext(
                args.cuda_nfnext, revision, cuda_sha, backend="cuda"
            )
            receipts.append(args.cuda_nfnext)
        cuda_section = {
            "device": cuda_device_name,
            "finite_models": [row["model"] for row in cuda_parity["gpu"]["models"]],
            "crossover": cuda_crossover,
            "native_sha256": cuda_sha,
        }
        if cuda is None:
            cuda = {
                "schema_version": 1,
                "verdict": {
                    "status": "RECORDED",
                    "detail": f"Real NVIDIA CUDA receipts verified on {cuda_device_name}.",
                },
            }
        cuda_row_device = _row(
            "release-cuda-device",
            "PASS",
            f"CUDA finite batch SSA executed on {cuda_device_name} with analytic, "
            "conservation, reproducibility and distributional checks.",
            [args.cuda_parity, args.cuda_build_identity],
        )
        cuda_row_perf = _row(
            "release-cuda-performance",
            "PASS",
            f"Paired CPU/CUDA measurements on {cuda_device_name} with A/A null, "
            "statistical equivalence, transfer costs, memory, startup and crossover ladder.",
            [args.cuda_performance, *args.cuda_crossover],
        )
    else:
        _require(
            cuda is not None, "--cuda-probe is required when CUDA receipts are omitted"
        )
        cuda_blocked = cuda["verdict"]["status"] == "BLOCKED"
        cuda_detail = cuda["verdict"]["detail"]
        if not cuda_blocked:
            raise ValueError(
                "CUDA resources are available; supply real CUDA device receipts before recording #474"
            )
        cuda_row_device = _row(
            "release-cuda-device",
            "NOT_TESTED",
            "No CUDA device execution: " + cuda_detail,
            [args.cuda_probe],
        )
        cuda_row_perf = _row(
            "release-cuda-performance",
            "NOT_TESTED",
            "No CUDA device measurement: " + cuda_detail,
            [args.cuda_probe],
        )

    metal_nf_corpus_path = getattr(args, "metal_nf_corpus", None)
    cuda_nf_corpus_path = getattr(args, "cuda_nf_corpus", None)
    metal_nf_corpus = None
    if metal_nf_corpus_path:
        metal_nf_corpus = _validate_nf_corpus(
            metal_nf_corpus_path, revision, backend="metal"
        )
        receipts.append(metal_nf_corpus_path)
    cuda_nf_corpus = None
    if cuda_nf_corpus_path:
        cuda_nf_corpus = _validate_nf_corpus(
            cuda_nf_corpus_path, revision, backend="cuda"
        )
        receipts.append(cuda_nf_corpus_path)

    nf_gpu_receipts = [
        row
        for row in (
            args.nfnext,
            args.nfnext_workloads,
            args.pinned_nfsim,
            args.cuda_nfnext,
            metal_nf_corpus_path,
            cuda_nf_corpus_path,
        )
        if row
    ]
    full_nf_gpu_passed = metal_nf_corpus is not None and cuda_nf_corpus is not None
    if full_nf_gpu_passed:
        nf_gpu_status = "PASS"
        nf_detail = (
            f"Full TIER_NF network-free GPU corpus ({', '.join(REQUIRED_TIER_NF_MODELS)}) "
            f"passed on both Metal ({metal_nf_corpus['device']}) and CUDA "
            f"({cuda_nf_corpus['device']}) against pinned native NFsim with 4-sigma "
            "Welch mean, two-sample KS/DKW, and deterministic same-device replay."
        )
    elif metal_nf_corpus or cuda_nf_corpus:
        nf_gpu_status = "NOT_TESTED"
        present = "Metal" if metal_nf_corpus else "CUDA"
        missing_be = "CUDA" if metal_nf_corpus else "Metal"
        nf_detail = (
            f"Full TIER_NF network-free GPU corpus passed on {present}, "
            f"but {missing_be} full network-free GPU corpus receipt is missing."
        )
    elif nfnext or cuda_nfnext:
        nf_gpu_status = "NOT_TESTED"
        backends_tested = " and ".join(
            name
            for name, present in (("Metal", nfnext), ("CUDA", cuda_nfnext))
            if present
        )
        nf_detail = (
            f"Bounded {backends_tested} unary-state route passes analytic"
            + (" and pinned native NFsim" if pinned else "")
            + (" across extended bounded workload classes" if workloads else "")
            + " checks, but the full network-free GPU corpus is not qualified"
            + (" and CUDA reporting is not included." if not cuda_nfnext else ".")
        )
    else:
        nf_gpu_status = "NOT_TESTED"
        nf_detail = (
            "No network-free device receipt was consumed on this exact revision; "
            "finite GPU evidence cannot qualify this row."
        )

    if has_all_cuda_receipts and full_nf_gpu_passed:
        coverage_status = "PASS"
        coverage_detail = (
            "backend.gpu is fully covered on both Metal and CUDA: finite batch SSA "
            "device/performance parity and full TIER_NF network-free GPU graph SSA "
            "passed against independent references on this exact revision."
        )
        coverage_receipts = [
            args.parity,
            args.cuda_parity,
            metal_nf_corpus_path,
            cuda_nf_corpus_path,
        ]
    elif has_all_cuda_receipts:
        coverage_status = "NOT_TESTED"
        coverage_detail = (
            "backend.gpu is not fully covered: finite batch SSA passed on Metal and CUDA "
            "and bounded unary NFnext passed, but the full network-free GPU corpus "
            "(multi-type/bond/function kernels) remains unimplemented."
        )
        coverage_receipts = [args.parity, args.cuda_parity]
    else:
        coverage_status = "NOT_TESTED"
        coverage_detail = (
            "backend.gpu is not fully covered: Metal executions recorded, CUDA device "
            "execution externally blocked and full network-free corpus unimplemented."
        )
        coverage_receipts = [args.cuda_probe]

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
        cuda_row_device,
        cuda_row_perf,
        _row("release-nf-gpu", nf_gpu_status, nf_detail, nf_gpu_receipts),
        _row(
            "release-capability-coverage-474",
            coverage_status,
            coverage_detail,
            coverage_receipts,
        ),
    ]

    report = {
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
            "metal": (
                {
                    "device": nfnext["device"]["reported_device"],
                    "total_events": nfnext["total_events"],
                    "analytic_times": [row["time"] for row in nfnext["checks"]],
                }
                if nfnext
                else None
            ),
            "pinned_nfsim": pinned,
            "bounded_workloads": workloads,
            "cuda": (
                {
                    "device": cuda_nfnext["device"]["reported_device"],
                    "total_events": cuda_nfnext["total_events"],
                    "analytic_times": [row["time"] for row in cuda_nfnext["checks"]],
                }
                if cuda_nfnext
                else "NOT_RECORDED: bounded CUDA NFnext receipt not supplied"
            ),
            "metal_corpus": (
                {
                    "device": metal_nf_corpus["device"],
                    "models": [c["model"] for c in metal_nf_corpus["cases"]],
                    "passed_count": metal_nf_corpus["passed_count"],
                    "case_count": metal_nf_corpus["case_count"],
                }
                if metal_nf_corpus
                else None
            ),
            "cuda_corpus": (
                {
                    "device": cuda_nf_corpus["device"],
                    "models": [c["model"] for c in cuda_nf_corpus["cases"]],
                    "passed_count": cuda_nf_corpus["passed_count"],
                    "case_count": cuda_nf_corpus["case_count"],
                }
                if cuda_nf_corpus
                else None
            ),
        },
        "cuda": cuda,
        "receipts": [{"path": str(path), "sha256": _sha256(path)} for path in receipts],
    }
    if cuda_section is not None:
        report["cuda_device"] = cuda_section
    if args.display_base:
        base = Path(args.display_base)

        def add_display_path(entry: dict) -> None:
            # Keep the original path for provenance; add the portable location
            # where the receipt is retained in the repository.
            entry["display_path"] = str(base / Path(entry["path"]).name)

        for row in report["results"]:
            for entry in row.get("receipts", []):
                add_display_path(entry)
        for entry in report["receipts"]:
            add_display_path(entry)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--parity", required=True, type=Path)
    parser.add_argument("--nfnext", type=Path)
    parser.add_argument("--nfnext-workloads", type=Path)
    parser.add_argument("--performance", required=True, type=Path)
    parser.add_argument("--crossover", required=True, type=Path, action="append")
    parser.add_argument("--pinned-nfsim", type=Path)
    parser.add_argument("--cuda-probe", type=Path)
    parser.add_argument("--build-identity", required=True, type=Path)
    parser.add_argument("--cuda-build-identity", type=Path)
    parser.add_argument("--cuda-parity", type=Path)
    parser.add_argument("--cuda-performance", type=Path)
    parser.add_argument("--cuda-crossover", type=Path, action="append")
    parser.add_argument("--cuda-nfnext", type=Path)
    parser.add_argument("--metal-nf-corpus", type=Path)
    parser.add_argument("--cuda-nf-corpus", type=Path)
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument(
        "--display-base",
        help="repository-relative directory where receipts are retained",
    )
    args = parser.parse_args()
    report = record(args)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    statuses = ", ".join(f"{row['id']}={row['status']}" for row in report["results"])
    print("issue-474 report: " + statuses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
