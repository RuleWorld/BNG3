"""Tests for GPU benchmark timing and memory fields."""

import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))

from gpu.arms import _native_metrics
from gpu.measure import finish_host_facts, host_facts, source_identity


def test_native_metrics_retain_transfer_throughput_and_buffer_counts():
    result = {
        "total_events": 42,
        "model_prep_time_ms": 1.0,
        "h2d_transfer_ms": 2.0,
        "sim_time_ms": 3.0,
        "d2h_transfer_ms": 4.0,
        "total_wall_time_ms": 10.0,
        "trajectories_per_sec_sim": 100.0,
        "trajectories_per_sec_total": 90.0,
        "events_per_sec_sim": 4200.0,
        "events_per_sec_total": 3780.0,
        "memory_usage_bytes": 1234,
        "observable_means": {"A": [1.0]},
    }

    metrics = _native_metrics(result)

    assert metrics["h2d_transfer_ms"] == 2.0
    assert metrics["d2h_transfer_ms"] == 4.0
    assert metrics["events_per_sec_total"] == 3780.0
    assert metrics["memory_usage_bytes"] == 1234
    assert "observable_means" not in metrics


def test_host_report_records_process_peak_rss():
    facts = finish_host_facts(host_facts())

    assert facts["host_process_peak_rss_bytes"] > 0


def test_source_identity_records_revision_cleanliness_and_binary_hash(tmp_path):
    source = tmp_path / "source.txt"
    binary = tmp_path / "native-extension.so"
    source.write_text("source", encoding="utf-8")
    binary.write_bytes(b"native binary")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "add", "source.txt", "native-extension.so"], cwd=tmp_path, check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=GPU benchmark test",
            "-c",
            "user.email=gpu-bench-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )

    clean = source_identity(str(tmp_path), SimpleNamespace(__file__=str(binary)))

    assert len(clean["revision"]) == 40
    assert clean["source_dirty"] is False
    assert (
        clean["native_binary_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    )

    source.write_text("modified", encoding="utf-8")
    dirty = source_identity(str(tmp_path), SimpleNamespace(__file__=str(binary)))
    assert dirty["source_dirty"] is True


def test_resource_fallback_when_posix_resource_is_unavailable(monkeypatch):
    import importlib
    import gpu.arms as arms_mod
    import gpu.measure as measure_mod

    monkeypatch.setattr(measure_mod, "resource", None)
    assert measure_mod._rusage_children() == (0.0, 0.0)
    self_u, self_s = measure_mod._rusage_self()
    assert self_u >= 0.0 and self_s == 0.0
    assert arms_mod._self_cpu() >= 0.0
    assert measure_mod._process_peak_rss_bytes() >= 0

    # Verify importing both modules succeeds even when `resource` is absent.
    monkeypatch.setitem(sys.modules, "resource", None)
    reloaded_measure = importlib.reload(measure_mod)
    reloaded_arms = importlib.reload(arms_mod)
    assert reloaded_measure.resource is None
    assert reloaded_arms._self_cpu() >= 0.0

    monkeypatch.undo()
    importlib.reload(measure_mod)
    importlib.reload(arms_mod)


def test_win32_peak_rss_configures_handle_argtypes_and_restype(monkeypatch):
    import ctypes
    from ctypes import wintypes
    import gpu.measure as measure_mod

    def fake_get_current_process():
        return -1

    def fake_k32_get_process_memory_info(handle, counters_ref, cb):
        assert fake_get_current_process.restype is wintypes.HANDLE
        assert fake_get_current_process.argtypes == []
        assert fake_k32_get_process_memory_info.restype is wintypes.BOOL
        assert len(fake_k32_get_process_memory_info.argtypes) == 3
        assert fake_k32_get_process_memory_info.argtypes[0] is wintypes.HANDLE
        assert fake_k32_get_process_memory_info.argtypes[2] is wintypes.DWORD
        assert handle == -1
        assert cb == ctypes.sizeof(counters_ref._obj)
        counters_ref._obj.PeakWorkingSetSize = 654321
        return 1

    fake_kernel32 = SimpleNamespace(
        GetCurrentProcess=fake_get_current_process,
        K32GetProcessMemoryInfo=fake_k32_get_process_memory_info,
    )
    monkeypatch.setattr(measure_mod, "resource", None)
    monkeypatch.setattr(measure_mod.sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=fake_kernel32), raising=False
    )

    assert measure_mod._process_peak_rss_bytes() == 654321
