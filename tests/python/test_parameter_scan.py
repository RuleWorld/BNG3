import numpy as np
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


def test_parameter_scan_1d_and_dataframe(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)

    model = bionetgen.load(str(model_path))
    scan = model.parameter_scan(
        parameter="k",
        values=np.array([0.01, 0.1, 0.2]),
        method="ode",
        t_end=20,
        n_steps=40,
    )

    final = scan.final("Xtot")
    assert final.shape == (3,)
    assert final[0] > final[-1]
    assert scan.at_time(10.0, "Xtot").shape == (3,)

    pandas = pytest.importorskip("pandas")
    frame = scan.to_dataframe()
    assert isinstance(frame, pandas.DataFrame)
    assert set(["k", "time", "Xtot"]).issubset(frame.columns)


def test_parameter_scan_log_and_linear_spacing(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)
    model = bionetgen.load(str(model_path))

    log_scan = model.parameter_scan(
        parameter="k", min=1e-2, max=1e2, n_points=4, log_scale=True
    )
    assert np.allclose(log_scan.parameter_values, np.logspace(-2, 2, 4))

    lin_scan = model.parameter_scan(
        parameter="k", min=0.0, max=1.0, n_points=5, log_scale=False
    )
    assert np.allclose(lin_scan.parameter_values, np.linspace(0.0, 1.0, 5))


def test_parameter_scan_2d_shape_and_standalone(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)

    scan = bionetgen.parameter_scan(
        str(model_path),
        parameter="k",
        values=[0.01, 0.05, 0.1],
        method="ode",
        t_end=10,
        n_steps=20,
    )
    assert scan.final("Xtot").shape == (3,)

    model = bionetgen.load(str(model_path))
    scan2d = model.parameter_scan_2d(
        parameter1="k",
        values1=[0.01, 0.1],
        parameter2="X0",
        values2=[50, 100, 150],
        method="ode",
        t_end=10,
        n_steps=20,
    )

    assert scan2d.final("Xtot").shape == (2, 3)
    assert scan2d.at_time(5.0, "Xtot").shape == (2, 3)

    pandas = pytest.importorskip("pandas")
    frame = scan2d.to_dataframe()
    assert isinstance(frame, pandas.DataFrame)
    assert set(["k", "X0", "time", "Xtot"]).issubset(frame.columns)
