"""Validation-harness path contracts.

The runners change their subprocess working directory, so configured binary
paths must be anchored before execution begins.
"""

from __future__ import annotations

import subprocess

import pytest

from tests.validation import conftest, oracle_nfsim, oracle_perl, runner


def test_configured_nfsim_path_is_anchored_to_discovery_directory(
    tmp_path, monkeypatch
):
    binary = tmp_path / "bin" / "NFsim"
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NFSIM_BIN", "bin/NFsim")

    assert oracle_nfsim._nfsim_bin() == binary.resolve()


def test_missing_configured_nfsim_path_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NFSIM_BIN", "missing/NFsim")

    assert oracle_nfsim._nfsim_bin() is None


def test_unconfigured_nfsim_requires_an_explicit_oracle(monkeypatch):
    monkeypatch.delenv("NFSIM_BIN", raising=False)

    assert oracle_nfsim._nfsim_bin() is None


def test_perl_oracle_anchors_bng_root_and_keeps_fixture_relative_files(
    tmp_path, monkeypatch
):
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    source = fixture_dir / "model.bngl"
    source.write_text("begin model\nend model\n", encoding="utf-8")
    bng2 = tmp_path / "bng2" / "BNG2.pl"
    bng2.parent.mkdir()
    bng2.write_text("", encoding="utf-8")
    work_dir = tmp_path / "work"

    monkeypatch.setenv("BNG2_PERL", str(bng2))
    monkeypatch.delenv("BNGPATH", raising=False)
    monkeypatch.setattr(oracle_perl.corpus, "resolve", lambda _name: source)

    def fake_run(command, *, cwd, env, **_kwargs):
        assert cwd == str(fixture_dir)
        assert env["BNGPATH"] == str(bng2.parent)
        assert command[2:4] == ["--outdir", str(work_dir)]
        assert command[4] == str(source)
        work_dir.mkdir(exist_ok=True)
        (work_dir / "model.net").write_text("net\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(oracle_perl.subprocess, "run", fake_run)
    net, gdat, _error = oracle_perl.run_perl("model", work_dir)

    assert net == work_dir / "model.net"
    assert gdat is None


def test_explicit_bng_cpp_path_is_anchored_to_discovery_directory(
    tmp_path, monkeypatch
):
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


def test_native_ensemble_parallel_workers_preserve_seed_order(tmp_path):
    if not oracle_nfsim.nfsim_available():
        pytest.skip("native NFsim binary not available")

    runs = oracle_nfsim.ensemble(
        "simple_system",
        tmp_path,
        n_runs=2,
        base_seed=11,
        t_end=1.0,
        n_steps=1,
        workers=2,
    )

    assert len(runs) == 2
    assert runs[0][0][0, 0] == pytest.approx(0.0)
