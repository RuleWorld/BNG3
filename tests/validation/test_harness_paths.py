"""Validation-harness path contracts.

The runners change their subprocess working directory, so configured binary
paths must be anchored before execution begins.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from tests.validation import conftest, oracle_nfsim, oracle_perl, runner
from tests.validation.strict import require_oracle


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


def test_cli_output_selection_prefers_model_stem_over_action_artifacts(tmp_path):
    preferred = tmp_path / "model.gdat"
    preferred.touch()
    (tmp_path / "model_burnin.gdat").touch()

    assert runner._select_cli_output(tmp_path, "model", ".gdat") == preferred


def test_cli_output_selection_fails_closed_on_ambiguous_artifacts(tmp_path):
    (tmp_path / "model_burnin.gdat").touch()
    (tmp_path / "model_equil.gdat").touch()

    assert runner._select_cli_output(tmp_path, "model", ".gdat") is None


def test_api_ensemble_parallel_workers_preserve_seed_order():
    if not runner.api_available():
        pytest.skip("compiled bionetgen API backend not available")
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


def test_api_ensemble_can_require_actual_construction_route(monkeypatch):
    fake = runner.Trajectory(
        data=np.asarray([[0.0], [1.0]]),
        columns=["time"],
        construction_path="in-memory-xml",
    )
    monkeypatch.setattr(runner, "_run_api_ensemble_item", lambda payload: fake)

    with pytest.raises(AssertionError, match="expected 'direct'"):
        runner.run_api_ensemble(
            "simple_system",
            method="nf",
            n_runs=1,
            workers=1,
            expected_construction_path="direct",
        )


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


def test_source_python_path_is_anchored_for_spawned_workers(monkeypatch):
    source_python = str((runner.corpus.REPO / "python").resolve())
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != source_python])

    runner._ensure_source_python_path()

    assert sys.path[0] == source_python


def test_required_oracle_fails_in_strict_ci(monkeypatch):
    monkeypatch.setenv("BNG3_CI_STRICT_ORACLES", "1")

    with pytest.raises(pytest.fail.Exception, match="required oracle unavailable"):
        require_oracle(False, "required oracle unavailable")
