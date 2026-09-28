"""Contracts for independent seed streams in the Atomizer NFsim benchmark."""

from pathlib import Path
import subprocess

import numpy as np
import pytest

import benchmarks.benchmark_atomizer_nfsim as benchmark


def test_benchmark_mode_uses_disjoint_seed_ranges(monkeypatch, tmp_path: Path):
    direct_seeds = []
    native_seeds = []

    def fake_direct(*, seed, **_kwargs):
        direct_seeds.append(seed)
        return (
            {
                "columns": ["time", "X"],
                "data": [[0.0, 1.0], [1.0, 2.0]],
                "construction_path": "direct",
            },
            1.0,
        )

    def fake_native(*, seed, **_kwargs):
        native_seeds.append(seed)
        return np.asarray([[0.0, 1.0], [1.0, 2.0]]), ["time", "X"], 1.0, ""

    monkeypatch.setattr(benchmark, "run_direct", fake_direct)
    monkeypatch.setattr(benchmark, "run_native", fake_native)

    result = benchmark.benchmark_mode(
        source=tmp_path / "model.xml",
        mode="flat",
        bngl=tmp_path / "model.bngl",
        native_xml=tmp_path / "model.xml.native",
        nfsim_binary=tmp_path / "NFsim",
        runs=2,
        seed_start=11,
        native_seed_start=13,
        t_end=1.0,
        n_steps=1,
        timeout=1,
        work_dir=tmp_path / "work",
    )

    assert direct_seeds == [11, 12]
    assert native_seeds == [13, 14]
    assert result["seed_ranges"] == {
        "bng3_direct": [11, 12],
        "standalone_nfsim": [13, 14],
    }
    assert result["mean_comparison"]["passed"] is True


def test_native_seed_range_defaults_after_direct_range():
    assert benchmark.resolve_native_seed_start(seed_start=11, runs=200) == 211


def test_native_seed_range_rejects_overlap():
    with pytest.raises(ValueError, match="must not overlap"):
        benchmark.resolve_native_seed_start(
            seed_start=11, runs=200, native_seed_start=200
        )


def test_git_state_records_tracked_changes(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    config = [
        "git",
        "-C",
        str(repo),
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.invalid",
    ]
    source = repo / "source.txt"
    source.write_text("baseline\n", encoding="utf-8")
    subprocess.run([*config, "add", "source.txt"], check=True, capture_output=True)
    subprocess.run(
        [*config, "commit", "-m", "baseline"], check=True, capture_output=True
    )

    clean = benchmark.git_state(repo)
    source.write_text("changed\n", encoding="utf-8")
    dirty = benchmark.git_state(repo)

    assert clean["status_available"] is True
    assert clean["dirty"] is False
    assert dirty["dirty"] is True
    assert dirty["tracked_diff_sha256"] != clean["tracked_diff_sha256"]
