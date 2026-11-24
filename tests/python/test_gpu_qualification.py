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


def test_poisson_count_oracle_accepts_the_declared_immigration_death_law(gate):
    sample = np.random.default_rng(20261120).poisson(4.5, size=5000)

    report = gate.evaluate_poisson_count_sample(sample, expected_mean=4.5)

    assert report["status"] == "PASS"
    assert report["chi_square_p"] >= gate.POISSON_CHI2_ALPHA
    assert abs(report["mean_z"]) <= gate.POISSON_MEAN_Z_LIMIT
    assert gate.POISSON_VARIANCE_RATIO_MIN <= report["variance_ratio"]
    assert report["variance_ratio"] <= gate.POISSON_VARIANCE_RATIO_MAX


def test_poisson_count_oracle_rejects_immigration_without_death(gate):
    # With the same immigration rate but omitted death, N(t) is Poisson(lambda*t)
    # instead of Poisson(lambda/mu * (1-exp(-mu*t))).
    wrong_sample = np.random.default_rng(20261120).poisson(8.0, size=5000)

    report = gate.evaluate_poisson_count_sample(wrong_sample, expected_mean=4.5)

    assert report["status"] == "FAIL"
    assert abs(report["mean_z"]) > gate.POISSON_MEAN_Z_LIMIT


@pytest.mark.parametrize(
    "sample",
    [
        np.array([0.0, 1.5, 2.0]),
        np.array([0.0, -1.0, 2.0]),
        np.array([0.0, np.nan, 2.0]),
        np.array([1.0]),
    ],
)
def test_poisson_count_oracle_rejects_malformed_samples(gate, sample):
    report = gate.evaluate_poisson_count_sample(sample, expected_mean=1.0)

    assert report["status"] == "FAIL"
    assert report["reason"]


def test_public_gpu_inventory_and_batch_ssa_cpu_route():
    import bionetgen

    backends = bionetgen.gpu_backends()
    capabilities = bionetgen.gpu_backend_capabilities()
    default = bionetgen.default_gpu_backend()
    assert [row["name"] for row in backends] == ["cuda", "metal"]
    assert [row["name"] for row in capabilities] == ["cuda", "metal"]
    assert default in {"none", "cuda", "metal"}

    model = bionetgen.load("models/isomerization.bngl")
    cpu_batch = model.simulate_batch_ssa(
        batch_size=32, t_end=2.0, n_steps=4, base_seed=77, backend="none"
    )
    assert cpu_batch["batch_size"] == 32
    assert len(cpu_batch["time"]) == 5
    np.testing.assert_allclose(cpu_batch["observable_means"]["A_total"], 20.0)

    with pytest.raises(RuntimeError, match="Unknown GPU backend"):
        model.simulate_batch_ssa(batch_size=8, backend="opencl")
    with pytest.raises(
        ValueError, match="batch_size is supported only for method='ssa'"
    ):
        model.simulate(method="ode", t_end=1.0, n_steps=2, batch_size=8)


def test_public_batch_ssa_preserves_custom_sample_times():
    import bionetgen

    # toy-jim has >50 reactions, so batch_size=1000 clears the GPU launch
    # threshold; custom sample_times must never be replaced by a uniform grid.
    model = bionetgen.load("models/toy-jim.bngl")
    custom_times = [0.0, 0.25, 1.0]
    res = model.simulate(
        method="ssa",
        t_end=1.0,
        n_steps=0,
        sample_times=custom_times,
        seed=123,
        batch_size=1000,
        batch_gpu_backend="auto",
    )
    np.testing.assert_allclose(res.time, custom_times)
    assert res.batch_size == 1000
    assert res.concentrations.shape == (len(custom_times), 25)
    np.testing.assert_allclose(res.observables["A_total"], 1.0)


def test_public_batch_ssa_metal_route_and_species_grid():
    import bionetgen

    metal = next(
        (row for row in bionetgen.gpu_backends() if row["name"] == "metal"), None
    )
    model = bionetgen.load("models/toy-jim.bngl")
    if not metal or not metal["available"]:
        with pytest.raises(RuntimeError):
            model.simulate_batch_ssa(
                batch_size=1000,
                t_end=5.0,
                n_steps=5,
                base_seed=474001,
                backend="metal",
            )
        return

    res = model.simulate(
        method="ssa",
        t_end=5.0,
        n_steps=5,
        seed=474001,
        batch_size=1000,
        batch_gpu_backend="metal",
    )
    assert res.backend == "metal"
    assert res.batch_size == 1000
    assert res.concentrations.shape == (6, 25)
    assert np.isfinite(res.concentrations).all()
    assert (res.concentrations >= 0).all()
    np.testing.assert_allclose(res.observables["A_total"], 1.0, atol=1e-5)
    assert len(res.batch_std_devs["Rec_A"]) == 6

    batch_dict = model.simulate_batch_ssa(
        batch_size=1000,
        t_end=5.0,
        n_steps=5,
        base_seed=474001,
        backend="metal",
    )
    assert batch_dict["backend"] == "metal"
    assert batch_dict["batch_size"] == 1000
    np.testing.assert_allclose(
        batch_dict["observable_means"]["A_total"], 1.0, atol=1e-5
    )
