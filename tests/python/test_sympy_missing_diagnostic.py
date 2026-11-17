import importlib

import pytest

sympy_odes = importlib.import_module("bionetgen.modelapi.sympy_odes")


def test_extract_odes_reports_missing_sympy(tmp_path, monkeypatch):
    source = tmp_path / "model_mex.c"
    source.write_text("void f(){ ydot[0] = 1; }", encoding="utf-8")
    monkeypatch.setattr(sympy_odes, "sp", None)

    with pytest.raises(ImportError, match="SymPy"):
        sympy_odes.extract_odes_from_mexfile(str(source))


def test_export_odes_reports_missing_sympy(monkeypatch):
    monkeypatch.setattr(sympy_odes, "sp", None)

    with pytest.raises(ImportError, match="SymPy"):
        sympy_odes.export_sympy_odes(None)
