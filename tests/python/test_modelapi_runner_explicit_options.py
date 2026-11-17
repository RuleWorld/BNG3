import subprocess

import numpy as np
import pytest
from unittest.mock import MagicMock

from bionetgen.core.exc import BNGRunError
from bionetgen.modelapi.runner import run
from bionetgen.result import SimResult


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"simulator": "subprocess"}, "subprocess"),
        ({"out": "results"}, "out"),
        ({"timeout": 30}, "timeout"),
    ],
)
def test_single_simulation_does_not_ignore_explicit_controls(
    options, message, monkeypatch, tmp_path
):
    if message == "out":
        monkeypatch.setattr("bionetgen.model.load", lambda _: MagicMock())
        with pytest.raises(NotImplementedError, match=message):
            run("model.bngl", method="ode", **options)
        return

    model = tmp_path / "decay.bngl"
    model.write_text(
        "begin model\nbegin parameters\nk 0.5\nend parameters\n"
        "begin molecule types\nA()\nend molecule types\n"
        "begin seed species\nA() 10\nend seed species\n"
        "begin observables\nMolecules A_total A()\nend observables\n"
        "begin reaction rules\nA() -> 0 k\nend reaction rules\nend model\n",
        encoding="utf-8",
    )
    result = run(
        model, method="ode", t_span=(0, 1), n_points=2, suppress=True, **options
    )
    assert list(result.time) == [0, 0.5, 1]
    assert result.backend == "native"


@pytest.mark.parametrize("n_points", [0, 1, True, 2.5])
def test_single_simulation_rejects_invalid_point_counts_before_loading(
    n_points, monkeypatch
):
    def unexpected_load(_):
        pytest.fail("invalid output grid reached model loading")

    monkeypatch.setattr("bionetgen.model.load", unexpected_load)
    with pytest.raises(ValueError, match="n_points"):
        run("model.bngl", method="ode", n_points=n_points)


def test_single_simulation_point_count_includes_both_endpoints(tmp_path):
    model = tmp_path / "decay.bngl"
    model.write_text(
        "begin model\nbegin parameters\nk 0.5\nend parameters\n"
        "begin molecule types\nA()\nend molecule types\n"
        "begin seed species\nA() 10\nend seed species\n"
        "begin observables\nMolecules A_total A()\nend observables\n"
        "begin reaction rules\nA() -> 0 k\nend reaction rules\nend model\n",
        encoding="utf-8",
    )
    # Pinned PyBioNetGen's modelapi runner.run(method=..., n_points=n) emits
    # n+1 points (n_points is forwarded as the backend step count). This is
    # distinct from top-level bionetgen.run(..., out=..., n_points=n), which
    # emits n rows. Verify both n=4 and n=5 on the modelapi law.
    result = run(str(model), method="ode", t_span=(0, 2), n_points=4)
    assert list(result.time) == pytest.approx([0.0, 0.5, 1.0, 1.5, 2.0], abs=1e-12)
    result = run(str(model), method="ode", t_span=(0, 2), n_points=5)
    assert list(result.time) == pytest.approx([0.0, 0.4, 0.8, 1.2, 1.6, 2.0], abs=1e-12)


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
begin functions
doubled() = 2*total
end functions
begin reaction rules
A() -> 0 k
end reaction rules
end model
"""


@pytest.mark.parametrize(
    "controls",
    [
        {"simulator": "subprocess"},
        {"timeout": 30},
        {"simulator": "native", "timeout": 30},
    ],
)
def test_single_simulation_process_preserves_full_result(
    tmp_path, monkeypatch, controls
):
    source = tmp_path / "model.bngl"
    source.write_text(MODEL)
    direct = run(source, method="ode", t_span=(0, 1), n_points=4, suppress=True)

    assert "doubled" in direct.functions

    def no_parent_load(*args, **kwargs):
        pytest.fail("requested process isolation loaded the model in the parent")

    monkeypatch.setattr("bionetgen.model.load", no_parent_load)
    isolated = run(
        source, method="ode", t_span=(0, 1), n_points=4, suppress=True, **controls
    )
    assert isinstance(isolated, SimResult)
    np.testing.assert_array_equal(isolated.time, [0, 0.25, 0.5, 0.75, 1])
    for field in ("observables", "functions"):
        actual, expected = getattr(isolated, field), getattr(direct, field)
        assert list(actual) == list(expected)
        for name in expected:
            assert actual[name].dtype == expected[name].dtype
            np.testing.assert_array_equal(actual[name], expected[name])
    assert isolated.concentrations.dtype == direct.concentrations.dtype
    np.testing.assert_array_equal(isolated.concentrations, direct.concentrations)
    assert isolated.backend == direct.backend == "native"
    assert isolated.construction_path == direct.construction_path
    assert isolated.direct_unavailable_reason == direct.direct_unavailable_reason
    assert source.read_text() == MODEL


def test_single_simulation_timeout_cancels_before_success(tmp_path):
    source = tmp_path / "model.bngl"
    source.write_text(MODEL)
    with pytest.raises(subprocess.TimeoutExpired):
        run(source, method="ode", timeout=0.000001, suppress=True)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["model.bngl"]


def test_single_simulation_process_error_retains_native_diagnostic(tmp_path):
    source = tmp_path / "invalid.bngl"
    source.write_text(
        "begin model\nbegin parameters\nk = (\nend parameters\nend model\n"
    )
    with pytest.raises(BNGRunError) as caught:
        run(source, method="ode", simulator="subprocess", suppress=True)
    assert "invalid.bngl" in caught.value.stdout


def test_process_result_archive_preserves_arrays_and_metadata(tmp_path):
    from bionetgen.compat._native_process import _read_sim_result, _write_sim_result

    archive = tmp_path / "result.npz"
    original = SimResult(
        {
            "time": np.array([0, 1], dtype=np.float32),
            "observables": {"x/y": np.array([4, 3], dtype=np.int64)},
            "functions": {"signal": np.array([8, 6], dtype=np.float32)},
            "concentrations": None,
            "backend": "nfsim",
            "construction_path": "in-memory-xml",
            "direct_unavailable_reason": "direct construction declined",
        }
    )
    _write_sim_result(archive, original)
    restored = _read_sim_result(archive)
    assert restored.time.dtype == np.dtype("float32")
    np.testing.assert_array_equal(restored.time, [0, 1])
    assert restored.observables["x/y"].dtype == np.dtype("int64")
    np.testing.assert_array_equal(restored.observables["x/y"], [4, 3])
    assert restored.functions["signal"].dtype == np.dtype("float32")
    np.testing.assert_array_equal(restored.functions["signal"], [8, 6])
    assert restored.concentrations is None
    assert restored.backend == "nfsim"
    assert restored.construction_path == "in-memory-xml"
    assert restored.direct_unavailable_reason == "direct construction declined"
