"""Validation-harness path contracts.

The runners change their subprocess working directory, so configured binary
paths must be anchored before execution begins.
"""

from __future__ import annotations

from tests.validation import conftest, oracle_nfsim


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
