"""Hardware qualification cannot substitute another backend or skip a device."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def gate():
    path = Path(__file__).resolve().parents[1] / "test_batch_ssa_statistical_parity.py"
    spec = importlib.util.spec_from_file_location("gpu_qualification_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_device_cannot_skip_or_use_another_backend(gate, monkeypatch):
    monkeypatch.setattr(gate.cpp, "default_gpu_backend", lambda: "metal")
    monkeypatch.setattr(
        gate.cpp,
        "gpu_backends",
        lambda: [
            {"name": "metal", "available": True},
            {"name": "cuda", "available": False},
        ],
    )
    report = {}
    assert not gate.run_gpu_parity_gate(
        backend="cuda", require_device=True, report=report
    )
    assert report["status"] == "NOT_TESTED"
    assert report["backend"] == "cuda"
    assert report["models"] == []


def test_optional_missing_device_is_recorded_as_not_tested(gate, monkeypatch):
    monkeypatch.setattr(gate.cpp, "default_gpu_backend", lambda: "none")
    monkeypatch.setattr(gate.cpp, "gpu_backends", lambda: [])
    report = {}
    assert gate.run_gpu_parity_gate(report=report)
    assert report["status"] == "NOT_TESTED"


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "backend",
        "shape",
        "time",
        "nonfinite",
        "events",
        "species",
        "nonfinite_events",
        "events_total",
        "cpu_nonfinite",
    ],
)
def test_device_result_contract_rejects_false_qualification(gate, defect):
    result = {
        "backend": "metal",
        "batch_size": 4,
        "time": np.array([0.0, 1.0]),
        "observable_names": ["A"],
        "observable_means": {"A": np.array([2.0, 1.0])},
        "observable_stds": {"A": np.array([0.0, 0.5])},
        "final_observables": np.ones((4, 1)),
        "final_species": np.ones((4, 1), dtype=int),
        "event_counts": np.ones(4, dtype=int),
        "total_events": 4,
    }
    if defect == "backend":
        result["backend"] = "cpu"
    elif defect == "shape":
        result["final_observables"] = np.ones((3, 1))
    elif defect == "time":
        result["time"] = np.array([0.0, 0.5])
    elif defect == "nonfinite":
        result["observable_means"]["A"][1] = np.nan
    elif defect == "events":
        result["event_counts"] = np.ones(3, dtype=int)
    elif defect == "species":
        result["final_species"][0, 0] = -1
    elif defect == "nonfinite_events":
        result["event_counts"] = np.full(4, np.nan)
    elif defect == "events_total":
        result["total_events"] = 5
    elif defect == "cpu_nonfinite":
        result["observable_stds"]["A"][1] = np.nan
    if defect is None:
        gate.check_device_result(result, "metal", 4, np.array([0.0, 1.0]))
        return
    with pytest.raises(AssertionError):
        gate.check_device_result(
            result,
            None if defect == "cpu_nonfinite" else "metal",
            4,
            np.array([0.0, 1.0]),
        )
