"""Validation-harness path contracts.

The runners change their subprocess working directory, so configured binary
paths must be anchored before execution begins.
"""

from __future__ import annotations

from tests.validation import conftest, oracle_nfsim, runner


def test_configured_nfsim_path_is_anchored_to_discovery_directory(tmp_path, monkeypatch):
    binary = tmp_path / "bin" / "NFsim"
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NFSIM_BIN", "bin/NFsim")

    assert oracle_nfsim._nfsim_bin() == binary.resolve()


def test_explicit_bng_cpp_path_is_anchored_to_discovery_directory(tmp_path, monkeypatch):
    binary = tmp_path / "bin" / "bng_cpp"
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.chdir(tmp_path)

    assert conftest._discover_bng_cpp("bin/bng_cpp") == binary.resolve()


def test_api_ensemble_parallel_workers_preserve_seed_order():
    runs = runner.run_api_ensemble(
        "simple_system",
        method="nf",
        n_runs=2,
        base_seed=11,
        t_end=1.0,
        n_steps=1,
        workers=2,
    )

    assert len(runs) == 2
    assert [columns[0] for _, columns in runs] == ["time", "time"]
