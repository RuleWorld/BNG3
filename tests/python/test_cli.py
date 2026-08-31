"""Tests for the Click CLI."""

import os
import pytest
from click.testing import CliRunner
from unittest.mock import patch

try:
    from bionetgen.cli import main
except ImportError:
    pytest.skip("CLI not available", allow_module_level=True)

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


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


def test_cli_legacy_run_flags_preserve_action_outputs(runner, tmp_path):
    output = tmp_path / "legacy-results"
    result = runner.invoke(
        main,
        [
            "run",
            "-i",
            os.path.join(os.path.dirname(__file__), "test.bngl"),
            "-o",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert {"test.net", "test.xml", "test.gdat", "test.cdat"}.issubset(
        {path.name for path in output.iterdir()}
    )


@pytest.mark.parametrize(
    "command", ["info", "plot", "notebook", "graphdiff", "atomize"]
)
def test_cli_legacy_command_surface(runner, command):
    result = runner.invoke(main, [command, "--help"])
    assert result.exit_code == 0, result.output


def test_cli_export_bngl(runner, simple_model, tmp_path):
    out = str(tmp_path / "output.bngl")
    result = runner.invoke(
        main, ["export", simple_model, "--format", "bngl", "-o", out]
    )
    assert result.exit_code == 0
    assert os.path.exists(out)


def test_cli_visualize_legacy_flags_write_graphml(runner, simple_model, tmp_path):
    result = runner.invoke(
        main,
        [
            "visualize",
            "-i",
            simple_model,
            "--type",
            "contactmap",
            "-o",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert any(path.suffix == ".graphml" for path in tmp_path.iterdir())


def test_legacy_bngcli_does_not_fallback_after_cpp_failure(tmp_path):
    from bionetgen.core.tools.cli import BNGCLI

    model = tmp_path / "invalid.bngl"
    model.write_text("begin model\nend model\n")
    cli = BNGCLI(model, tmp_path / "output", str(tmp_path / "missing"), suppress=True)
    with patch("bionetgen._bionetgen_cpp.parse_file") as parse_file:
        parse_file.side_effect = RuntimeError("backend parse failure")
        with pytest.raises(RuntimeError, match="backend parse failure"):
            cli.run()


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


def test_cli_scan_and_sensitivity_forward_simulation_options(runner, tmp_path):
    model = tmp_path / "decay.bngl"
    model.write_text("""
begin model
begin parameters
    k 0.1
    X0 100
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() X0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")

    scan_output = tmp_path / "scan.csv"
    result = runner.invoke(
        main,
        [
            "scan",
            str(model),
            "--parameter",
            "k",
            "--min",
            "0.05",
            "--max",
            "0.1",
            "--n-points",
            "2",
            "--t-start",
            "2",
            "--t-end",
            "4",
            "--n-steps",
            "2",
            "--output",
            str(scan_output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert scan_output.exists()
    assert "time" in scan_output.read_text()

    sensitivity_output = tmp_path / "sensitivity.csv"
    result = runner.invoke(
        main,
        [
            "sensitivity",
            str(model),
            "--parameter",
            "k",
            "--observable",
            "Xtot",
            "--t-start",
            "2",
            "--t-end",
            "4",
            "--n-steps",
            "2",
            "--output",
            str(sensitivity_output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sensitivity_output.exists()
    assert "parameter" in sensitivity_output.read_text()
