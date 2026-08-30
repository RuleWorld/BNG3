"""Small, source-derived PyBioNetGen compatibility contracts."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import numpy as np

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


def test_module_entry_point_exposes_cli_help():
    env = os.environ.copy()
    source_python = str(REPO / "python")
    env["PYTHONPATH"] = os.pathsep.join(
        [source_python, str(REPO / "build" / "cpp"), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", "bionetgen", "--help"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
    assert "BioNetGen" in result.stdout
