"""Behavior-level compatibility checks for PyBioNetGen-style runner/result APIs.

These tests use analytic expectations and installed-package contracts rather than
requiring the pinned PyBioNetGen runtime in-process.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

import bionetgen
from bionetgen.modelapi.runner import run as runner_run


def _action_decay_model(path: Path) -> Path:
    path.write_text(
        """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_tot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>2,n_steps=>4})
""",
        encoding="utf-8",
    )
    return path


def test_modelapi_runner_run_returns_bngresult_with_gdat_access():
    with tempfile.TemporaryDirectory() as td:
        model = _action_decay_model(Path(td) / "decay.bngl")
        result = runner_run(str(model))

    assert isinstance(result, bionetgen.BNGResult)
    assert bool(getattr(result, "gdats", {}))

    gdat = result.gdat
    names = tuple(gdat.dtype.names)
    assert names[0] == "time"
    assert "A_tot" in names

    expected_t = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    np.testing.assert_allclose(gdat["time"], expected_t)
    np.testing.assert_allclose(
        gdat["A_tot"], 10.0 * np.exp(-0.5 * expected_t), rtol=1e-6, atol=1e-9
    )


def test_modelapi_runner_run_accepts_mutated_bngmodel_object(tmp_path: Path):
    model_path = _action_decay_model(tmp_path / "decay.bngl")
    model = bionetgen.bngmodel(str(model_path))
    model.parameters.k = 1.0

    result_action = runner_run(model, suppress=True)
    assert isinstance(result_action, bionetgen.BNGResult)
    gdat = result_action.gdat
    expected_t = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    np.testing.assert_allclose(gdat["time"], expected_t)
    np.testing.assert_allclose(
        gdat["A_tot"], 10.0 * np.exp(-1.0 * expected_t), rtol=1e-6, atol=1e-9
    )

    result_sim = runner_run(model, method="ode", t_span=(0.0, 2.0), n_points=4)
    assert isinstance(result_sim, bionetgen.SimResult)
    np.testing.assert_allclose(
        result_sim.observables["A_tot"],
        10.0 * np.exp(-1.0 * expected_t),
        rtol=1e-6,
        atol=1e-9,
    )
