import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

import bionetgen


def _write_decay_model(path):
    path.write_text("""
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


def test_model_and_result_html(tmp_path):
    model_path = tmp_path / "display.bngl"
    _write_decay_model(model_path)

    model = bionetgen.load(str(model_path))
    model_html = model._repr_html_()
    assert "<table" in model_html
    assert "Parameters" in model_html
    assert "Xtot" in model_html

    result = model.simulate(method="ode", t_end=5, n_steps=10)
    result_html = result._repr_html_()
    assert "<img" in result_html
    assert "Xtot" in result_html


def test_scan_html(tmp_path):
    model_path = tmp_path / "scan_html.bngl"
    _write_decay_model(model_path)

    model = bionetgen.load(str(model_path))
    scan = model.parameter_scan(
        parameter="k", values=[0.01, 0.1, 0.2], method="ode", t_end=5, n_steps=10
    )
    scan_html = scan._repr_html_()
    assert "<img" in scan_html
    assert "k" in scan_html
