"""Consuming checks for the locally recorded #474 device report.

The report is produced by ``scripts/ci/record_issue474_release.py`` from actual
device receipts.  These tests only consume it; a passing command with no device
receipt, a Metal result wearing a CUDA label, or a compilation/fallback artifact
cannot produce a PASS row here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
REPORT_ENV = "BNG3_ISSUE474_REPORT"
RECORDER = ROOT / "scripts/ci/record_issue474_release.py"


def _report() -> dict:
    path = os.environ.get(REPORT_ENV)
    if not path:
        pytest.skip(f"set {REPORT_ENV} to a recorded issue-474 report")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rows(report: dict) -> dict:
    return {row["id"]: row for row in report["results"]}


def _head() -> str:
    expected = os.environ.get("BNG3_ISSUE474_REVISION")
    if expected:
        return expected
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def test_report_is_exact_revision_and_clean():
    report = _report()
    assert report["source"]["revision"] == _head()
    assert report["source"]["dirty"] is False
    assert {row["id"] for row in report["results"]} == {
        "release-metal-device",
        "release-metal-performance",
        "release-cuda-device",
        "release-cuda-performance",
        "release-nf-gpu",
        "release-capability-coverage-474",
    }


@pytest.mark.parametrize("check", ("release-metal-device", "release-metal-performance"))
def test_metal_rows_are_supported_device_execution(check):
    row = _rows(_report())[check]
    assert row["status"] == "PASS"
    assert row["supported_execution"] is True
    assert row["evidence_kind"] == "supported-execution"
    assert row["related_issues"] == [474]


def test_metal_performance_carries_cost_and_correctness_evidence():
    report = _report()
    assert report["metal"]["crossover"]
    assert report["metal"]["native_sha256"]
    assert report["network_free"]["metal"]["total_events"] > 0


def _receipt_path(entry: dict) -> Path:
    path = Path(entry.get("display_path", entry["path"]))
    if not path.is_absolute():
        path = ROOT / path
    assert path.is_file(), path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    return path


def _parity_receipt(report: dict) -> dict:
    override = os.environ.get("BNG3_ISSUE474_PARITY")
    if override:
        return json.loads(Path(override).read_text(encoding="utf-8"))
    metal_receipts = _rows(report)["release-metal-device"]["receipts"]
    assert metal_receipts, "release-metal-device report is missing its parity receipt"
    return json.loads(_receipt_path(metal_receipts[0]).read_text(encoding="utf-8"))


def test_public_simulate_ssa_route_is_attributed_and_qualified():
    report = _report()
    assert "toy-jim-public-route" in report["metal"]["finite_models"]
    parity = _parity_receipt(report)
    rows = [
        row
        for row in parity["gpu"]["models"]
        if row.get("model") == "toy-jim-public-route"
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "PASS"
    assert row["backend"] == "metal"
    assert row["device_grid_shape"] == [11, 25]
    assert row["seed_replay"] is True
    assert row["n_steps"] > 0 and row["batch_size"] > 0
    assert row["comparison"].startswith("distributional")
    assert all(check["pass"] for check in row["checks"])


def test_cuda_rows_require_real_device_execution():
    report = _report()
    rows = _rows(report)
    status = report_cuda_status(report)
    if status == "BLOCKED":
        for check in ("release-cuda-device", "release-cuda-performance"):
            assert rows[check]["status"] == "NOT_TESTED"
            assert rows[check]["supported_execution"] is False
    elif status == "RECORDED":
        for check in ("release-cuda-device", "release-cuda-performance"):
            assert rows[check]["status"] == "PASS"
            assert rows[check]["supported_execution"] is True
            assert rows[check]["evidence_kind"] == "supported-execution"
        assert report["cuda_device"]["device"]
        assert report["cuda_device"]["native_sha256"]
        assert report["cuda_device"]["crossover"]
    else:
        raise AssertionError(f"unexpected cuda status: {status}")


def report_cuda_status(report: dict) -> str:
    return report["cuda"]["verdict"]["status"]


def test_nf_gpu_does_not_claim_the_full_corpus_or_cuda():
    report = _report()
    row = _rows(report)["release-nf-gpu"]
    assert row["status"] == "NOT_TESTED"
    assert "full network-free GPU corpus" in row["detail"]
    if not isinstance(report["network_free"].get("cuda"), dict):
        assert "CUDA" in row["detail"]


def test_capability_coverage_acknowledges_remaining_gap():
    row = _rows(_report())["release-capability-coverage-474"]
    assert row["status"] == "NOT_TESTED"
    assert "full network-free" in row["detail"] or "CUDA" in row["detail"]


def test_workload_receipt_keeps_extended_scope_when_supplied():
    path = os.environ.get("BNG3_ISSUE474_NF_WORKLOADS")
    if not path:
        pytest.skip("set BNG3_ISSUE474_NF_WORKLOADS to a recorded workload receipt")
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
    assert data["device"]["backend"] == "metal"
    assert data["cuda"]["status"] in {
        "UNSUPPORTED",
        "NOT_RUN_HERE",
        "NOT_TESTED_IN_THIS_RECEIPT",
    }
    assert data["full_corpus_claimed"] is False
    assert len(data["workloads"]) >= 3
    assert {row["class"] for row in data["workloads"]} >= {
        "two_state_ctmc",
        "three_state_chain",
        "particle_heavy",
    }
    assert all(row["status"] == "REFUSED" for row in data["refusals"])
    for row in data["workloads"]:
        assert row["total_events"] > 0
        assert row["device_memory_bytes"] > 0
        assert row["events_per_sec_dispatch"] > 0
        assert row["timings_ms"]["setup"] >= 0.0
        assert all(check["pass"] for check in row["checks"])


def test_receipt_digests_match_the_files(tmp_path):
    report = _report()
    for entry in report["receipts"]:
        _receipt_path(entry)


def _recorder_module():
    spec = importlib.util.spec_from_file_location("issue474_recorder", RECORDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_receipt(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_stale_parity_receipt_is_rejected(tmp_path):
    recorder = _recorder_module()
    receipt = _write_receipt(
        tmp_path,
        "parity.json",
        {
            "source_revision": "0" * 40,
            "source_dirty": False,
            "native_sha256": "a" * 64,
            "gpu": {
                "status": "PASS",
                "backend": "metal",
                "inventory": [],
                "models": [],
            },
        },
    )
    with pytest.raises(ValueError, match="parity receipt: stale revision"):
        recorder._validate_parity(receipt, "1" * 40, "Apple M5 Pro", "a" * 64)


def test_fallback_labelled_metal_is_rejected(tmp_path):
    recorder = _recorder_module()
    receipt = _write_receipt(
        tmp_path,
        "parity.json",
        {
            "source_revision": "1" * 40,
            "source_dirty": False,
            "native_sha256": "a" * 64,
            "gpu": {"status": "PASS", "backend": "cpu", "inventory": [], "models": []},
        },
    )
    with pytest.raises(ValueError, match="not a Metal run"):
        recorder._validate_parity(receipt, "1" * 40, "Apple M5 Pro", "a" * 64)


def test_metal_receipt_wearing_cuda_label_is_rejected(tmp_path):
    recorder = _recorder_module()
    receipt = _write_receipt(
        tmp_path,
        "cuda_parity.json",
        {
            "source_revision": "1" * 40,
            "source_dirty": False,
            "native_sha256": "b" * 64,
            "gpu": {
                "status": "PASS",
                "backend": "cuda",
                "inventory": [
                    {
                        "name": "cuda",
                        "compiled": True,
                        "available": True,
                        "detail": "NVIDIA GeForce RTX 2080 Ti",
                    }
                ],
                "models": [
                    {"model": f"m{i}", "status": "PASS", "backend": "metal"}
                    for i in range(5)
                ]
                + [
                    {
                        "model": "gpu_immigration_death",
                        "status": "PASS",
                        "backend": "cuda",
                    }
                ],
            },
        },
    )
    with pytest.raises(ValueError, match="non-CUDA or non-passing model"):
        recorder._validate_parity(
            receipt, "1" * 40, "NVIDIA GeForce RTX 2080 Ti", "b" * 64, backend="cuda"
        )


def _sample_parity(backend: str, device: str, sha: str, rev: str) -> dict:
    return {
        "source_revision": rev,
        "source_dirty": False,
        "native_sha256": sha,
        "gpu": {
            "status": "PASS",
            "backend": backend,
            "inventory": [
                {
                    "name": backend,
                    "compiled": True,
                    "available": True,
                    "detail": device,
                }
            ],
            "models": [
                {"model": f"m{i}", "status": "PASS", "backend": backend}
                for i in range(4)
            ]
            + [
                {
                    "model": "gpu_immigration_death",
                    "status": "PASS",
                    "backend": backend,
                }
            ],
        },
    }


def _sample_perf(backend: str, sha: str, rev: str, batch_size: int = 2000) -> dict:
    return {
        "config": {"batch_size": batch_size},
        "source_identity": {
            "revision": rev,
            "source_dirty": False,
            "native_binary_sha256": sha,
        },
        "equivalence": {"passed": True},
        "device_assertions": [{"backend": backend}],
        "memory_accounting": {"bytes": 1024},
        "measurement": {
            "verdicts": {
                "self_cpu_s": {"effect_ratio_b_over_a": 0.1},
                "wall_s": {"effect_ratio_b_over_a": 0.2},
            },
            "clock_divergence": {"agree": True},
            "rounds": [
                {
                    "b": {
                        "label": f"gpu:{backend}",
                        "extra": {
                            "native_metrics": {
                                "h2d_transfer_ms": 0.1,
                                "d2h_transfer_ms": 0.1,
                                "memory_usage_bytes": 1024,
                                "model_prep_time_ms": 0.2,
                                "sim_time_ms": 1.0,
                                "events_per_sec_sim": 1e6,
                            }
                        },
                    }
                }
            ],
        },
    }


def test_record_promotes_cuda_rows_when_real_cuda_receipts_supplied(
    tmp_path, monkeypatch
):
    import argparse

    recorder = _recorder_module()
    rev = "1" * 40
    metal_sha = "a" * 64
    cuda_sha = "b" * 64
    monkeypatch.setattr(
        recorder,
        "_git",
        lambda *args: rev if args[:2] == ("rev-parse", "HEAD") else "",
    )
    monkeypatch.setattr(recorder.platform, "system", lambda: "Linux")

    metal_build = _write_receipt(
        tmp_path,
        "build-metal.json",
        {
            **{k: "x" for k in recorder.BUILD_IDENTITY_FIELDS},
            "device": "Apple M5 Pro",
            "native_binary_sha256": metal_sha,
        },
    )
    metal_parity = _write_receipt(
        tmp_path,
        "metal-parity.json",
        _sample_parity("metal", "Apple M5 Pro", metal_sha, rev),
    )
    metal_perf = _write_receipt(
        tmp_path, "metal-perf.json", _sample_perf("metal", metal_sha, rev)
    )
    metal_cross = [
        _write_receipt(
            tmp_path, f"m_cross_{b}.json", _sample_perf("metal", metal_sha, rev, b)
        )
        for b in (1, 10, 100, 300, 500, 1000)
    ]

    cuda_build = _write_receipt(
        tmp_path,
        "build-cuda.json",
        {
            "device": "NVIDIA GeForce RTX 2080 Ti",
            "os": "Linux",
            "compiler": "g++ / nvcc 12.4",
            "native_binary_sha256": cuda_sha,
        },
    )
    cuda_parity = _write_receipt(
        tmp_path,
        "cuda-parity.json",
        _sample_parity("cuda", "NVIDIA GeForce RTX 2080 Ti", cuda_sha, rev),
    )
    cuda_perf = _write_receipt(
        tmp_path, "cuda-perf.json", _sample_perf("cuda", cuda_sha, rev)
    )
    cuda_cross = [
        _write_receipt(
            tmp_path, f"c_cross_{b}.json", _sample_perf("cuda", cuda_sha, rev, b)
        )
        for b in (1, 10, 100, 300, 500, 1000)
    ]

    partial_args = argparse.Namespace(
        revision=rev,
        parity=metal_parity,
        nfnext=None,
        nfnext_workloads=None,
        performance=metal_perf,
        crossover=metal_cross,
        pinned_nfsim=None,
        cuda_probe=None,
        build_identity=metal_build,
        cuda_build_identity=cuda_build,
        cuda_parity=cuda_parity,
        cuda_performance=None,
        cuda_crossover=None,
        cuda_nfnext=None,
        display_base=None,
    )
    with pytest.raises(ValueError, match="supply --cuda-build-identity"):
        recorder.record(partial_args)

    full_args = argparse.Namespace(
        **{
            **vars(partial_args),
            "cuda_performance": cuda_perf,
            "cuda_crossover": cuda_cross,
        }
    )
    report = recorder.record(full_args)
    rows = {row["id"]: row for row in report["results"]}
    assert rows["release-metal-device"]["status"] == "PASS"
    assert rows["release-metal-performance"]["status"] == "PASS"
    assert rows["release-cuda-device"]["status"] == "PASS"
    assert rows["release-cuda-performance"]["status"] == "PASS"
    assert rows["release-nf-gpu"]["status"] == "NOT_TESTED"
    assert rows["release-capability-coverage-474"]["status"] == "NOT_TESTED"
    assert report["cuda_device"]["device"] == "NVIDIA GeForce RTX 2080 Ti"


def _sample_nf_corpus(backend: str, device: str, rev: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "issue474-nfnext-gpu-corpus-receipt",
        "backend": backend,
        "device": device,
        "source_revision": rev,
        "source_dirty": False,
        "oracle_nfsim_sha256": "c" * 64,
        "oracle_bng2_sha256": "d" * 64,
        "tier": "TIER_NF",
        "case_count": 4,
        "passed_count": 4,
        "result": "pass",
        "cases": [
            {
                "model": name,
                "backend": backend,
                "device": device,
                "passed": True,
                "deterministic_replay": True,
                "gpu_total_events": 1000,
                "distribution": {
                    "passed": True,
                    "max_z": 1.2,
                    "max_ks": 0.08,
                    "failures": [],
                },
            }
            for name in ("motor", "simple_system", "localfunc", "tlbr")
        ],
    }


def test_recorder_promotes_nf_gpu_and_coverage_only_when_both_metal_and_cuda_corpus_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import argparse

    recorder = _recorder_module()
    rev = "2" * 40
    metal_sha = "a" * 64
    cuda_sha = "b" * 64
    monkeypatch.setattr(
        recorder,
        "_git",
        lambda *args: rev if args[:2] == ("rev-parse", "HEAD") else "",
    )
    monkeypatch.setattr(recorder.platform, "system", lambda: "Linux")

    metal_build = _write_receipt(
        tmp_path,
        "build-metal.json",
        {
            **{k: "x" for k in recorder.BUILD_IDENTITY_FIELDS},
            "device": "Apple M5 Pro",
            "native_binary_sha256": metal_sha,
        },
    )
    metal_parity = _write_receipt(
        tmp_path,
        "metal-parity.json",
        _sample_parity("metal", "Apple M5 Pro", metal_sha, rev),
    )
    metal_perf = _write_receipt(
        tmp_path, "metal-perf.json", _sample_perf("metal", metal_sha, rev)
    )
    metal_cross = [
        _write_receipt(
            tmp_path, f"m_cross_{b}.json", _sample_perf("metal", metal_sha, rev, b)
        )
        for b in (1, 10, 100, 300, 500, 1000)
    ]
    cuda_build = _write_receipt(
        tmp_path,
        "build-cuda.json",
        {
            "device": "NVIDIA GeForce RTX 2080 Ti",
            "os": "Linux",
            "compiler": "g++ / nvcc 12.4",
            "native_binary_sha256": cuda_sha,
        },
    )
    cuda_parity = _write_receipt(
        tmp_path,
        "cuda-parity.json",
        _sample_parity("cuda", "NVIDIA GeForce RTX 2080 Ti", cuda_sha, rev),
    )
    cuda_perf = _write_receipt(
        tmp_path, "cuda-perf.json", _sample_perf("cuda", cuda_sha, rev)
    )
    cuda_cross = [
        _write_receipt(
            tmp_path, f"c_cross_{b}.json", _sample_perf("cuda", cuda_sha, rev, b)
        )
        for b in (1, 10, 100, 300, 500, 1000)
    ]
    metal_nf = _write_receipt(
        tmp_path,
        "metal-nf.json",
        _sample_nf_corpus("metal", "Apple M5 Pro", rev),
    )
    cuda_nf = _write_receipt(
        tmp_path,
        "cuda-nf.json",
        _sample_nf_corpus("cuda", "NVIDIA GeForce RTX 2080 Ti", rev),
    )

    base = dict(
        revision=rev,
        parity=metal_parity,
        nfnext=None,
        nfnext_workloads=None,
        performance=metal_perf,
        crossover=metal_cross,
        pinned_nfsim=None,
        cuda_probe=None,
        build_identity=metal_build,
        cuda_build_identity=cuda_build,
        cuda_parity=cuda_parity,
        cuda_performance=cuda_perf,
        cuda_crossover=cuda_cross,
        cuda_nfnext=None,
        metal_nf_corpus=metal_nf,
        cuda_nf_corpus=None,
        display_base=None,
    )
    # Single-backend NF corpus must stay NOT_TESTED
    metal_only = recorder.record(argparse.Namespace(**base))
    m_rows = {row["id"]: row for row in metal_only["results"]}
    assert m_rows["release-nf-gpu"]["status"] == "NOT_TESTED"
    assert m_rows["release-capability-coverage-474"]["status"] == "NOT_TESTED"

    # Both Metal and CUDA full TIER_NF receipts promote all 6 rows to PASS
    both = recorder.record(argparse.Namespace(**{**base, "cuda_nf_corpus": cuda_nf}))
    b_rows = {row["id"]: row for row in both["results"]}
    for check_id in recorder.ALL_CHECKS:
        assert b_rows[check_id]["status"] == "PASS", check_id
        assert b_rows[check_id]["supported_execution"] is True

    # Negative control: missing a required TIER_NF model fails closed
    bad_nf = _sample_nf_corpus("cuda", "NVIDIA GeForce RTX 2080 Ti", rev)
    bad_nf["cases"] = [c for c in bad_nf["cases"] if c["model"] != "tlbr"]
    bad_path = _write_receipt(tmp_path, "cuda-nf-missing.json", bad_nf)
    with pytest.raises(ValueError, match="missing required TIER_NF model"):
        recorder.record(argparse.Namespace(**{**base, "cuda_nf_corpus": bad_path}))

    # Negative control: stale revision fails closed
    stale_nf = _sample_nf_corpus("cuda", "NVIDIA GeForce RTX 2080 Ti", "3" * 40)
    stale_path = _write_receipt(tmp_path, "cuda-nf-stale.json", stale_nf)
    with pytest.raises(ValueError, match="stale source revision"):
        recorder.record(argparse.Namespace(**{**base, "cuda_nf_corpus": stale_path}))
