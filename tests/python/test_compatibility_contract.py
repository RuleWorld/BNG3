"""Small, source-derived PyBioNetGen compatibility contracts."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

import bionetgen

REPO = Path(__file__).resolve().parents[2]
MODEL = Path(__file__).with_name("test.bngl")


def test_legacy_public_symbols_are_available_from_package_root():
    assert callable(bionetgen.bngmodel)
    assert callable(bionetgen.run)
    assert callable(bionetgen.sim_getter)
    assert bionetgen.SympyOdes is not None
    assert callable(bionetgen.export_sympy_odes)
    assert bionetgen.BNGResult is not None


def test_legacy_run_accepts_output_directory_and_returns_file_result(tmp_path):
    output = tmp_path / "results"

    result = bionetgen.run(MODEL, output)

    assert isinstance(result, bionetgen.BNGResult)
    assert result.process_return == 0
    assert {"test.net", "test.xml", "test.gdat", "test.cdat"}.issubset(
        {path.name for path in output.iterdir()}
    )
    assert result.gdats["test"].dtype.names[0] == "time"
    assert np.isfinite(result.gdats["test"]["time"]).all()


def test_legacy_run_supports_method_and_time_overrides(tmp_path):
    output = tmp_path / "override-results"

    result = bionetgen.run(
        MODEL,
        out=output,
        method="ode",
        t_span=(2.0, 3.0),
        n_points=5,
    )

    assert isinstance(result, bionetgen.BNGResult)
    assert result.process_return == 0
    data = result.gdats["test"]
    assert data.dtype.names[0] == "time"
    assert len(data) == 5
    assert np.allclose(data["time"], np.linspace(2.0, 3.0, 5))


@pytest.mark.parametrize("output_directory", [False, True])
@pytest.mark.parametrize("entry_point", ["compat", "public"])
@pytest.mark.parametrize(
    "override",
    [
        {},
        {"method": "ssa"},
        {"t_span": (0, 1)},
        {"n_points": 2},
        {"t_end": 1},
        {"n_steps": 1},
    ],
)
def test_compatibility_timeout_is_rejected_before_execution(
    tmp_path, monkeypatch, output_directory, entry_point, override
):
    from bionetgen.compat.runner import run as compatibility_run

    run = compatibility_run if entry_point == "compat" else bionetgen.run

    def unexpected_execution(*args, **kwargs):
        pytest.fail("unsupported timeout reached model execution")

    monkeypatch.setattr(bionetgen, "load", unexpected_execution)
    monkeypatch.setattr(bionetgen._bionetgen_cpp, "parse_file", unexpected_execution)
    output = tmp_path / "results" if output_directory else None

    with pytest.raises(NotImplementedError, match="timeout"):
        run(MODEL, out=output, timeout=1, **override)

    if output is not None:
        assert not output.exists()


def test_module_entry_point_exposes_cli_help(tmp_path):
    env = os.environ.copy()
    package_path = Path(bionetgen.__file__).resolve()
    source_package = (REPO / "python" / "bionetgen").resolve()
    source_mode = package_path.is_relative_to(source_package)
    if source_mode:
        extension_dir = REPO / "build" / "cpp"
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(REPO / "python"),
                str(extension_dir),
                env.get("PYTHONPATH", ""),
            ]
        )
        code = (
            "import pathlib, runpy, sys, bionetgen; "
            "bionetgen.__path__.insert(0, "
            "str(pathlib.Path(sys.argv.pop(1)).resolve())); "
            "runpy.run_module('bionetgen', run_name='__main__', alter_sys=True)"
        )
        command = [sys.executable, "-c", code, str(extension_dir), "--help"]
        cwd = REPO
    else:
        # An installed-mode child must not inherit paths that could replace
        # the wheel being tested. Its working directory is outside the repo.
        env.pop("PYTHONPATH", None)
        command = [sys.executable, "-m", "bionetgen", "--help"]
        cwd = tmp_path
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
    assert "BioNetGen" in result.stdout


def test_legacy_sim_getter_rejects_unknown_simulator_type():
    with pytest.raises(ValueError, match="not supported"):
        bionetgen.sim_getter(model_file=str(MODEL), sim_type="unknown")
