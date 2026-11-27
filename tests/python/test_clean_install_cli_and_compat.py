"""Regression tests for clean-install CLI and PyBioNetGen compatibility fixes."""

from __future__ import annotations

import builtins
import csv
import importlib.util
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from click.testing import CliRunner

import bionetgen
from bionetgen.cli import main
from bionetgen.core.exc import BNGParseError
from bionetgen.core.tools.plot import BNGPlotter
from bionetgen.core.utils.utils import ActionList, _StdlibActionParser

BIND_MODEL = """begin model
begin parameters
  kf 0.1
  kr 0.05
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 100
  B(a) 100
end seed species
begin observables
  Molecules FreeA A(b)
  Molecules BoundAB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1.0,n_steps=>10})
"""


def _block_import(monkeypatch, blocked_roots: set[str]):
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".", 1)[0]
        if root in blocked_roots:
            raise ModuleNotFoundError(f"No module named '{root}'", name=root)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_cli_export_latex_generates_network_and_writes_tex(tmp_path: Path):
    model = tmp_path / "bind.bngl"
    model.write_text(BIND_MODEL, encoding="utf-8")
    tex = tmp_path / "bind.tex"

    result = CliRunner().invoke(
        main, ["export", str(model), "-f", "latex", "-o", str(tex)]
    )

    assert result.exit_code == 0, result.output
    assert tex.is_file()
    text = tex.read_text(encoding="utf-8")
    assert r"\usepackage{amsmath}" in text
    assert r"\usepackage{amssymb}" in text


def test_cli_scan_and_sensitivity_work_without_pandas(tmp_path: Path, monkeypatch):
    model = tmp_path / "bind.bngl"
    model.write_text(BIND_MODEL, encoding="utf-8")
    _block_import(monkeypatch, {"pandas"})

    runner = CliRunner()
    scan_csv = tmp_path / "scan.csv"
    res_scan = runner.invoke(
        main,
        [
            "scan",
            str(model),
            "--parameter",
            "kf",
            "--min",
            "0.05",
            "--max",
            "0.2",
            "--n-points",
            "3",
            "--t-end",
            "1.0",
            "--n-steps",
            "2",
            "-o",
            str(scan_csv),
        ],
    )
    assert res_scan.exit_code == 0, res_scan.output
    with scan_csv.open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["kf", "time", "FreeA", "BoundAB"]
    assert len(rows) == 1 + 3 * 3

    res_scan_stdout = runner.invoke(
        main,
        [
            "scan",
            str(model),
            "--parameter",
            "kf",
            "--min",
            "0.05",
            "--max",
            "0.1",
            "--n-points",
            "2",
            "--t-end",
            "1.0",
            "--n-steps",
            "1",
        ],
    )
    assert res_scan_stdout.exit_code == 0, res_scan_stdout.output
    assert "BoundAB" in res_scan_stdout.output

    sens_csv = tmp_path / "sens.csv"
    res_sens = runner.invoke(
        main,
        [
            "sensitivity",
            str(model),
            "--parameter",
            "kf",
            "--observable",
            "BoundAB",
            "--t-end",
            "1.0",
            "--n-steps",
            "2",
            "-o",
            str(sens_csv),
        ],
    )
    assert res_sens.exit_code == 0, res_sens.output
    with sens_csv.open(encoding="utf-8") as handle:
        srows = list(csv.reader(handle))
    assert srows[0] == ["parameter", "BoundAB"]
    assert srows[1][0] == "kf"

    res_sens_stdout = runner.invoke(
        main,
        [
            "sensitivity",
            str(model),
            "--parameter",
            "kf",
            "--observable",
            "BoundAB",
            "--t-end",
            "1.0",
            "--n-steps",
            "2",
        ],
    )
    assert res_sens_stdout.exit_code == 0, res_sens_stdout.output
    assert "parameter" in res_sens_stdout.output
    assert "kf" in res_sens_stdout.output


def test_bng_plotter_works_without_seaborn_and_honors_zero_bounds(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("matplotlib") is None:
        pytest.skip("matplotlib not installed in this environment")

    gdat = tmp_path / "trace.gdat"
    gdat.write_text("# time A_tot\n0.0 10.0\n1.0 5.0\n2.0 2.5\n", encoding="utf-8")
    out_png = tmp_path / "trace.png"

    _block_import(monkeypatch, {"seaborn"})
    plotter = BNGPlotter(str(gdat), str(out_png), legend=True, xmin=0.0, xmax=2.0)
    plotter.plot()

    assert out_png.is_file()
    assert out_png.stat().st_size > 0


def test_bng_plotter_missing_matplotlib_reports_plotting_extra(
    tmp_path: Path, monkeypatch
):
    gdat = tmp_path / "trace.gdat"
    gdat.write_text("# time A_tot\n0.0 10.0\n1.0 5.0\n", encoding="utf-8")
    out_png = tmp_path / "trace.png"

    _block_import(monkeypatch, {"matplotlib"})
    with pytest.raises(ImportError, match=r"bionetgen\[plotting\]"):
        BNGPlotter(str(gdat), str(out_png)).plot()


@pytest.mark.parametrize(
    "action",
    [
        "generate_network({overwrite=>1})",
        'simulate({method=>"ode",t_end=>1.0,n_steps=>10});',
        'simulate_nf({param=>"-v -gml 1000 #tag",t_end=>2})',
        "simulate_ode({sample_times=>[0,2.3e-10,1]})",
        'generate_network({max_stoich=>{"A"=>5,"B"=>3}})',
        'setParameter("k",2)',
        'setConcentration("A()", 10)',
        'setModelName("my_model")',
        "saveParameters([])",
        'saveParameters(["k1","k2"])',
        "quit();",
    ],
)
def test_stdlib_action_parser_matches_pyparsing_tokens(action: str):
    stdlib_tokens = _StdlibActionParser().parseString(action)
    if importlib.util.find_spec("pyparsing") is not None:
        alist = ActionList()
        alist.define_parser()
        pp_tokens = list(alist.action_parser.parseString(action))
        assert stdlib_tokens == pp_tokens
    else:
        assert stdlib_tokens[0]
        assert stdlib_tokens[1] == "("


def test_bngmodel_parses_actions_without_pyparsing(tmp_path: Path, monkeypatch):
    model_path = tmp_path / "with_actions.bngl"
    model_path.write_text(BIND_MODEL, encoding="utf-8")

    _block_import(monkeypatch, {"pyparsing"})
    model = bionetgen.bngmodel(str(model_path))

    assert len(model.actions) == 2
    assert model.actions[0].type == "generate_network"
    assert model.actions[1].type == "simulate"
    assert model.actions[1].args["method"] == '"ode"'


def test_bngparseerror_matches_pybionetgen_format():
    default_err = BNGParseError("probe-message")
    assert (
        str(default_err) == "There was an issue parsing BNGL file: probe-message"
        "There was an issue with parsing your BNGL file"
    )
    err = BNGParseError("model.bngl", ": unexpected token")
    assert "model.bngl: unexpected token" in str(err)


def test_run_accepts_bngmodel_directly_in_modern_and_compat_paths(tmp_path: Path):
    model_path = tmp_path / "bind.bngl"
    model_path.write_text(BIND_MODEL, encoding="utf-8")

    model = bionetgen.bngmodel(str(model_path))
    model.parameters.kf = 0.2

    # 1. Legacy file-runner form via top-level bionetgen.run(..., out=...)
    compat_out = tmp_path / "compat_out"
    res_compat = bionetgen.run(model, out=str(compat_out), suppress=True)
    assert isinstance(res_compat, bionetgen.BNGResult)
    bound_compat = float(res_compat[model.model_name]["BoundAB"][-1])

    # 2. Modern top-level bionetgen.run(model, method="ode", ...)
    res_modern = bionetgen.run(model, method="ode", t_end=1.0, n_steps=10)
    assert isinstance(res_modern, bionetgen.SimResult)
    bound_modern = float(res_modern.observables["BoundAB"][-1])

    # 3. Default modern bionetgen.run(model)
    res_default = bionetgen.run(model)
    assert isinstance(res_default, bionetgen.SimResult)

    # Mutated kf=0.2 gives higher BoundAB (~93.73) than baseline kf=0.1 (~89.39).
    assert np.isclose(bound_compat, bound_modern, rtol=1e-5)
    assert bound_modern > 92.0


def test_setup_simulator_preserves_actions_and_does_not_leak_sbml_on_missing_librr(
    tmp_path: Path, monkeypatch
):
    model_path = tmp_path / "bind.bngl"
    model_path.write_text(BIND_MODEL, encoding="utf-8")
    model = bionetgen.bngmodel(str(model_path))
    original_action_count = len(model.actions)
    assert original_action_count == 2

    work_cwd = tmp_path / "clean_cwd"
    work_cwd.mkdir()
    monkeypatch.chdir(work_cwd)

    with patch("bionetgen.simulator.simulators.libRRSimulator") as mock_rr:
        mock_rr.side_effect = ImportError(
            "libRoadRunner is required for sim_type='libRR'"
        )
        with pytest.raises(ImportError, match="libRoadRunner is required"):
            model.setup_simulator()

    assert len(model.actions) == original_action_count
    assert list(work_cwd.iterdir()) == []
