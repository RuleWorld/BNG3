"""Tests for the Click CLI."""

import os
import pytest
from click.testing import CliRunner

try:
    from bionetgen.cli import main
except ImportError:
    pytest.skip("CLI not available", allow_module_level=True)

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def simple_model():
    path = os.path.join(MODELS_DIR, "simple_system.bngl")
    if not os.path.exists(path):
        pytest.skip("simple_system.bngl not found")
    return path


def test_cli_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "BioNetGen" in result.output or "bionetgen" in result.output


def test_cli_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0


def test_cli_check(runner, simple_model):
    result = runner.invoke(main, ["check", simple_model])
    assert result.exit_code == 0


def test_cli_export_bngl(runner, simple_model, tmp_path):
    out = str(tmp_path / "output.bngl")
    result = runner.invoke(
        main, ["export", simple_model, "--format", "bngl", "-o", out]
    )
    assert result.exit_code == 0
    assert os.path.exists(out)


@pytest.mark.parametrize("method", ["pla", "psa"])
def test_cli_approximate_simulation_start_time(runner, simple_model, method):
    result = runner.invoke(
        main,
        [
            "run",
            simple_model,
            "--method",
            method,
            "--t-start",
            "2",
            "--t-end",
            "4",
            "--n-steps",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output


def test_cli_nf_rejects_nonzero_start_time(runner, simple_model):
    result = runner.invoke(
        main,
        ["run", simple_model, "--method", "nf", "--t-start", "1"],
    )
    assert result.exit_code != 0
    assert "t-start" in result.output
