"""Regression tests for NFsim `-rnf` script execution in `bng_cpp`."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _require_bng_cpp() -> Path:
    configured = os.environ.get("BNG_CPP")
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        pytest.fail(f"BNG_CPP points to missing binary: {path}")
    for rel in ("build/cpp/bng_cpp", "build/bng_cpp"):
        candidate = REPO_ROOT / rel
        if candidate.is_file():
            return candidate
    pytest.fail(
        f"bng_cpp not found under {REPO_ROOT / 'build'}. Build bng_cpp before running."
    )


def test_simulate_nf_executes_rnf_script_and_updates_parameters(tmp_path):
    """Multi-phase -rnf scripts execute in-process and match pinned native NFsim on phase 1."""
    bng_cpp = _require_bng_cpp()

    model_text = """begin model
begin parameters
  k_on 0.05
  k_off 0.1
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
  Molecules Afree A(b)
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) k_on, k_off
end reaction rules
end model
"""
    (tmp_path / "script.rnf").write_text(
        "-utl 2\nbegin\n  sim 1.0 5\n  set k_on 0.0\n  update\n  sim 1.0 5\nend\n",
        encoding="utf-8",
    )
    run_bngl = tmp_path / "run.bngl"
    run_bngl.write_text(
        model_text + "\nsimulate_nf({seed=>7,param=>'-rnf script.rnf'})\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(run_bngl)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    arr = np.loadtxt(tmp_path / "run.gdat")
    assert arr.shape == (12, 3)
    assert arr[5, 0] == pytest.approx(1.0)
    # Phase 2 starts cleanly at t=1.0 and advances to t=2.0 with k_on=0 (monotonically dissociating AB).
    assert np.allclose(arr[6:, 0], np.linspace(1.0, 2.0, 6), rtol=0.0, atol=1e-12)
    assert np.all(np.diff(arr[6:, 2]) <= 0.0)

    nfsim_bin = os.environ.get("NFSIM_BIN")
    if nfsim_bin and Path(nfsim_bin).is_file():
        xml_bngl = tmp_path / "xml.bngl"
        xml_bngl.write_text(model_text + "\nwriteXML()\n", encoding="utf-8")
        subprocess.run(
            [str(bng_cpp), str(xml_bngl)], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            [
                nfsim_bin,
                "-xml",
                str(tmp_path / "xml.xml"),
                "-rnf",
                str(tmp_path / "script.rnf"),
                "-o",
                str(tmp_path / "native.gdat"),
                "-seed",
                "7",
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        native = np.loadtxt(tmp_path / "native.gdat")
        assert np.allclose(arr[:6], native[:6], rtol=0.0, atol=0.0)


def test_simulate_nf_rejects_missing_rnf_script(tmp_path):
    """A missing -rnf target must fail explicitly rather than falling back."""
    bng_cpp = _require_bng_cpp()
    bngl = tmp_path / "missing.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules A A()
end observables
begin reaction rules
  A() -> 0 1
end reaction rules
end model
simulate_nf({param=>'-rnf does_not_exist.rnf'})
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), str(bngl)], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "does_not_exist.rnf" in proc.stderr or "RNF" in proc.stderr
