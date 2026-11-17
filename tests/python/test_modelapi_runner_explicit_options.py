import pytest
from unittest.mock import MagicMock

from bionetgen.modelapi.runner import run


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
