"""Common compatibility routing uses the maintained native worker."""

import subprocess

import numpy as np
import pytest

import bionetgen

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
Molecules total A()
end observables
begin reaction rules
A() -> 0 k
end reaction rules
end model
simulate({method=>"ode",t_end=>1,n_steps=>4})
"""


@pytest.mark.parametrize(
    "options",
    [
        {"simulator": "subprocess"},
        {"timeout": 30},
        {"simulator": "native", "timeout": 30},
        {"simulator": "subprocess", "method": "ode", "t_span": (0, 1), "n_points": 5},
        {"timeout": 30, "t_span": (0, 1), "n_points": 5},
    ],
)
def test_common_runner_executes_process_controls(tmp_path, monkeypatch, options):
    model = tmp_path / "model.bngl"
    model.write_text(MODEL)
    output = tmp_path / "results"

    def no_parent_parse(*args, **kwargs):
        raise AssertionError("requested process isolation executed in the parent")

    monkeypatch.setattr(bionetgen._bionetgen_cpp, "parse_file", no_parent_parse)
    result = bionetgen.run(model, out=output, suppress=True, **options)

    assert result.process_return == 0
    data = next(iter(result.gdats.values()))
    np.testing.assert_allclose(data["time"], [0, 0.25, 0.5, 0.75, 1])
    assert "total" in data.dtype.names
    assert (output / "model.bngl").read_text() == MODEL
    assert model.read_text() == MODEL


@pytest.mark.parametrize("override", [{}, {"method": "ode"}, {"n_points": 5}])
def test_common_runner_timeout_terminates_without_success(tmp_path, override):
    model = tmp_path / "model.bngl"
    model.write_text(MODEL)
    output = tmp_path / "results"

    with pytest.raises(subprocess.TimeoutExpired):
        bionetgen.run(model, out=output, timeout=0.000001, suppress=True, **override)
    assert not list(output.glob("*.gdat"))


def test_subprocess_preserves_numpy_seed_and_native_trajectory(tmp_path):
    model = tmp_path / "model.bngl"
    model.write_text(MODEL)
    options = dict(method="ssa", t_end=1, n_steps=4, seed=np.int64(17), suppress=True)
    direct = bionetgen.run(
        model, out=tmp_path / "direct", simulator="native", **options
    )
    isolated = bionetgen.run(
        model, out=tmp_path / "isolated", simulator="subprocess", **options
    )
    np.testing.assert_array_equal(
        next(iter(direct.gdats.values())), next(iter(isolated.gdats.values()))
    )
