import pytest
from unittest.mock import MagicMock

from bionetgen.modelapi.runner import run


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"simulator": "subprocess"}, "subprocess"),
        ({"out": "results"}, "out"),
        ({"timeout": 1}, "timeout"),
    ],
)
def test_single_simulation_does_not_ignore_explicit_controls(
    options, message, monkeypatch
):
    monkeypatch.setattr("bionetgen.model.load", lambda _: MagicMock())
    with pytest.raises(NotImplementedError, match=message):
        run("model.bngl", method="ode", **options)


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
    result = run(str(model), method="ode", t_span=(0, 2), n_points=5)
    assert list(result.time) == [0.0, 0.5, 1.0, 1.5, 2.0]
