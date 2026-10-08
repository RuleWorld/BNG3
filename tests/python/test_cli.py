"""Tests for the Click CLI."""

import os
import numpy as np
import pytest
from click.testing import CliRunner
from unittest.mock import patch

from bionetgen import BNGResult

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
            "--t-start",
            "2",
            "--t-end",
            "3",
            "--n-steps",
            "4",
        ],
    )

    assert result.exit_code == 0, result.output
    assert {"test.net", "test.xml", "test.gdat", "test.cdat"}.issubset(
        {path.name for path in output.iterdir()}
    )
    assert np.allclose(
        BNGResult(path=str(output)).gdats["test"]["time"], np.linspace(2.0, 3.0, 5)
    )


def test_input_cli_rejects_unimplemented_solver_options_instead_of_dropping_them(
    runner, tmp_path
):
    output = tmp_path / "input-results"
    result = runner.invoke(
        main,
        [
            "run",
            "--input",
            os.path.join(os.path.dirname(__file__), "test.bngl"),
            "--output",
            str(output),
            "--rtol",
            "1e-6",
        ],
    )

    assert result.exit_code != 0
    assert "rtol" in result.output
    assert not output.exists()


def test_input_cli_explicit_method_runs_one_modern_simulation(runner, tmp_path):
    output = tmp_path / "single-method-results"
    result = runner.invoke(
        main,
        [
            "run",
            "--input",
            os.path.join(os.path.dirname(__file__), "test.bngl"),
            "--output",
            str(output),
            "--method",
            "ssa",
            "--t-start",
            "2",
            "--t-end",
            "3",
            "--n-steps",
            "4",
            "--seed",
            "7",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output / "test.gdat").is_file()
    assert not (output / "test.net").exists()
    assert not (output / "test.xml").exists()
    data = BNGResult(path=str(output)).gdats["test"]
    assert np.allclose(data["time"], np.linspace(2.0, 3.0, 5))


@pytest.mark.parametrize("method", ["ode", "ssa", "nf", "pla", "psa"])
def test_installed_cli_runs_each_supported_method(runner, tmp_path, method):
    model = tmp_path / f"{method}.bngl"
    model.write_text("""begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_count A()
    Molecules B_count B()
end observables
begin reaction rules
    convert: A() -> B() k
end reaction rules
end model
""")
    output = tmp_path / f"{method}.tsv"

    result = runner.invoke(
        main,
        [
            "run",
            str(model),
            "--method",
            method,
            "--t-end",
            "0.5",
            "--n-steps",
            "4",
            "--seed",
            "7",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        output.read_text(encoding="utf-8")
        .splitlines()[0]
        .lstrip("# ")
        .startswith("time\tA_count\tB_count")
    )
    data = np.loadtxt(output, comments="#", delimiter="\t")
    assert data.shape == (5, 3)
    assert np.allclose(data[:, 0], np.linspace(0.0, 0.5, 5))
    assert np.isfinite(data).all()


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


def test_cli_nf_honors_nonzero_start_time(runner, tmp_path):
    model = tmp_path / "tiny_nf.bngl"
    model.write_text("""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    R: 0 -> X() 1
end reaction rules
end model
""")
    output = tmp_path / "nf.tsv"
    result = runner.invoke(
        main,
        [
            "run",
            str(model),
            "--method",
            "nf",
            "--t-start",
            "1",
            "--t-end",
            "2",
            "--n-steps",
            "1",
            "--seed",
            "1",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    times = [
        float(line.split()[0])
        for line in output.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert times == [1.0, 2.0]


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
