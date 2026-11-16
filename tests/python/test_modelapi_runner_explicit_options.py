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
