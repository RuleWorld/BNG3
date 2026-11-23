"""Fail-closed result handling for GPU qualification measurements."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))

import gpu.run_gpu_bench as benchmark
from gpu.run_gpu_bench import compare_arm_payloads, crossover_verdict


def _matching_run():
    return {
        "observable_names": ["A"],
        "observable_means": {"A": [1.0]},
        "observable_stds": {"A": [0.0]},
        "final_observables": [[1.0], [1.0]],
        "batch_size": 2,
        "time": [0.0],
    }


def test_requested_equivalence_fails_when_an_arm_payload_is_missing():
    report, status = compare_arm_payloads(_matching_run(), None, alpha=0.001)

    assert status != 0
    assert report["passed"] is False
    assert "missing" in report["notes"][0]


def test_requested_equivalence_fails_when_comparison_rejects():
    host = _matching_run()
    device = {**host, "observable_means": {"A": [100.0]}}

    report, status = compare_arm_payloads(host, device, alpha=0.001)

    assert status != 0
    assert report["passed"] is False


def test_requested_equivalence_succeeds_only_for_a_passing_comparison():
    report, status = compare_arm_payloads(_matching_run(), _matching_run(), alpha=0.001)

    assert status == 0
    assert report["passed"] is True


def test_run_one_returns_failure_when_requested_equivalence_is_rejected(monkeypatch):
    host = _matching_run()
    device = {**host, "observable_means": {"A": [100.0]}}

    class FakeArm:
        def __init__(self, label, payload):
            self.label = label
            self.payload = payload
            self.device_claim = None

        def prepare(self, _model, _network):
            pass

        def run(self, _model, _network):
            return SimpleNamespace(
                sample=object(), payload=self.payload, precision=None
            )

    class FakeTimer:
        def __init__(self, runner, config):
            self.runner = runner

        def run(self, label_a, label_b):
            self.runner(label_a)
            self.runner(label_b)
            return {
                "primary_metric": "self_cpu_s",
                "verdicts": {"self_cpu_s": {"clears_null": True, "verdict": "faster"}},
                "null_rounds": [],
                "rounds": [],
                "order_log": [],
            }

    monkeypatch.setattr(
        benchmark,
        "source_identity",
        lambda *_: {
            "revision": "a" * 40,
            "source_dirty": False,
            "native_binary_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        benchmark.arms_mod,
        "build_arms",
        lambda *_args, **_kwargs: (
            [FakeArm("host", host), FakeArm("device", device)],
            ["host", "device"],
        ),
    )
    monkeypatch.setattr(benchmark, "PairedTimer", FakeTimer)
    monkeypatch.setattr(benchmark, "print_null_band", lambda *_: None)
    monkeypatch.setattr(benchmark, "print_effect", lambda *_: None)
    monkeypatch.setattr(benchmark, "_p", lambda *_: None)
    trace = SimpleNamespace(
        mark=lambda: None,
        summary=lambda: {"interpretation": "test"},
    )
    args = SimpleNamespace(
        batch=2,
        n_steps=1,
        seed=7,
        arms="host,device",
        model_dir=None,
        self_test=False,
        rounds=1,
        warmups=0,
        no_null=False,
        null_rounds=1,
        equivalence=True,
        alpha=0.001,
    )
    info = {
        "source": "fixture",
        "path": "fixture.bngl",
        "t_end": 1.0,
        "S": 1,
        "R": 1,
    }

    payload, status = benchmark.run_one(
        args, object(), object(), object(), info, trace, {}
    )

    assert status != 0
    assert payload["equivalence"]["passed"] is False
    assert payload["outcome"] == "EQUIVALENCE_FAILED"


def test_crossover_verdict_uses_elapsed_time_not_host_cpu_time():
    report = {
        "verdicts": {
            "self_cpu_s": {"clears_null": True, "verdict": "CPU faster"},
            "wall_s": {"clears_null": True, "verdict": "GPU slower"},
        }
    }

    assert crossover_verdict(report) == report["verdicts"]["wall_s"]
    assert (
        crossover_verdict({"verdicts": {"self_cpu_s": {"clears_null": True}}}) is None
    )


def test_run_sweep_reports_wall_verdict_and_keeps_cpu_resource_separate(monkeypatch):
    calibration = SimpleNamespace(
        path="synthetic.bngl",
        spec=SimpleNamespace(t_end=1.0),
        achieved_density=4.0,
        as_dict=lambda: {"target_density": 4.0},
    )
    wall = {
        "null_band": [0.8, 1.2],
        "effect_ratio_b_over_a": 0.7,
        "clears_null": False,
        "verdict": "within wall-clock noise",
    }
    cpu = {
        "null_band": [0.8, 1.2],
        "effect_ratio_b_over_a": 0.15,
        "clears_null": True,
        "verdict": "lower host CPU use",
    }
    monkeypatch.setattr(
        benchmark, "calibrate_event_density", lambda *a, **k: calibration
    )
    monkeypatch.setattr(
        benchmark,
        "run_one",
        lambda *a, **k: (
            {
                "measurement": {
                    "primary_metric": "self_cpu_s",
                    "verdicts": {"self_cpu_s": cpu, "wall_s": wall},
                },
                "events_per_trajectory": 4.0,
            },
            0,
        ),
    )
    cpp = SimpleNamespace(
        parse_file=lambda _path: object(),
        generate_network=lambda _model: SimpleNamespace(num_species=2, num_reactions=2),
    )
    args = SimpleNamespace(
        sweep_reactions="2",
        event_density=4.0,
        species=2,
        t_end=1.0,
        model_dir=None,
    )

    payload, status = benchmark.run_sweep(
        args, cpp, SimpleNamespace(mark=lambda: None), {}
    )

    assert status == 0
    assert payload["sweep"][0]["effect"] == 0.7
    assert payload["sweep"][0]["clears"] is False
    assert payload["sweep"][0]["host_cpu_effect_ratio_b_over_a"] == 0.15


def test_run_sweep_fails_when_elapsed_time_verdict_is_missing(monkeypatch):
    calibration = SimpleNamespace(
        path="synthetic.bngl",
        spec=SimpleNamespace(t_end=1.0),
        achieved_density=4.0,
        as_dict=lambda: {"target_density": 4.0},
    )
    monkeypatch.setattr(
        benchmark, "calibrate_event_density", lambda *a, **k: calibration
    )
    monkeypatch.setattr(
        benchmark,
        "run_one",
        lambda *a, **k: (
            {
                "measurement": {
                    "primary_metric": "self_cpu_s",
                    "verdicts": {"self_cpu_s": {"clears_null": True}},
                }
            },
            0,
        ),
    )
    cpp = SimpleNamespace(
        parse_file=lambda _path: object(),
        generate_network=lambda _model: SimpleNamespace(num_species=2, num_reactions=2),
    )
    args = SimpleNamespace(
        sweep_reactions="2",
        event_density=4.0,
        species=2,
        t_end=1.0,
        model_dir=None,
    )

    payload, status = benchmark.run_sweep(
        args, cpp, SimpleNamespace(mark=lambda: None), {}
    )

    assert status != 0
    assert payload["sweep"] == []


def test_cuda_workflow_records_runtime_ordinal_zero_identity():
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github/workflows/gpu-device-qualification.yml"
    ).read_text(encoding="utf-8")

    assert "cuDeviceGet" in workflow
    assert "cuDeviceGetName" in workflow
    assert "cuDeviceGetUuid" in workflow
    assert "cuDeviceComputeCapability" in workflow
    assert "runtime ordinal 0" in workflow
    assert "rows[0]" not in workflow
