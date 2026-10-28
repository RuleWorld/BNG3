"""PyBioNetGen 28bf351 API surface kept by BNG3.

docs/PYBIONETGEN_API_AUDIT.md lists the symbols and signatures these tests
cover.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from bionetgen.core import exc
from bionetgen.core.tools.cli import BNGCLI
from bionetgen.core.tools.result import BNGResult
from bionetgen.modelapi import runner

MODEL = """begin model
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
"""


def test_format_and_bngsim_exceptions_match_pybionetgen():
    error = exc.BNGFormatError("model.ant")
    assert isinstance(error, exc.BNGError)
    assert error.path == "model.ant"
    assert "model.ant" in error.message
    assert exc.BNGFormatError("x", "custom").message == "custom"
    assert isinstance(exc.BNGSimError(), exc.BNGError)
    assert exc.BNGSimError("failed").message == "failed"


def test_run_accepts_the_pybionetgen_arguments():
    parameters = inspect.signature(runner.run).parameters
    assert list(parameters)[:4] == ["inp", "out", "suppress", "timeout"]
    assert parameters["simulator"].default == "auto"
    for name in ("format", "method", "t_span", "n_points"):
        assert parameters[name].default is None


def test_run_rejects_non_bngl_formats_explicitly():
    with pytest.raises(exc.BNGFormatError, match="BNGL input only"):
        runner.run("model.xml", format="sbml")
    with pytest.raises(ValueError, match="simulator must be"):
        runner.run("model.bngl", simulator="other")


def test_run_with_a_method_override_runs_one_simulation(tmp_path):
    path = tmp_path / "decay.bngl"
    path.write_text(MODEL)
    result = runner.run(str(path), method="ode", t_span=(0.0, 2.0), n_points=4)
    time = np.asarray(result.time)
    np.testing.assert_allclose(time, [0.0, 0.5, 1.0, 1.5, 2.0])
    values = np.asarray(result.observables["A_tot"])
    np.testing.assert_allclose(values, 10.0 * np.exp(-0.5 * time), rtol=1e-6)


def test_bngcli_reports_the_bngsim_replacement(tmp_path):
    parameters = inspect.signature(BNGCLI.__init__).parameters
    assert parameters["bngsim_backend"].default is False
    assert parameters["bngsim_backend_helper"].default is None
    assert parameters["bngsim_backend_method"].default is None
    path = tmp_path / "decay.bngl"
    path.write_text(MODEL)
    with pytest.raises(exc.BNGSimError, match="backend='bngsim'"):
        BNGCLI(str(path), str(tmp_path / "out"), None, bngsim_backend=True)


def test_bngresult_accepts_extensions_and_folder_paths():
    assert inspect.signature(BNGResult.__init__).parameters["ext"].default is None
    for method in (BNGResult.find_dat_files, BNGResult.load_results):
        assert inspect.signature(method).parameters["folder_path"].default is None
