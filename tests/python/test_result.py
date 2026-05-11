"""Tests for SimResult class."""

import numpy as np
import pytest

from bionetgen.result import SimResult


@pytest.fixture
def sample_result():
    data = {
        "time": np.array([0.0, 1.0, 2.0, 3.0]),
        "observables": {"A": np.array([100.0, 80.0, 60.0, 40.0])},
        "concentrations": np.array([[100.0], [80.0], [60.0], [40.0]]),
    }
    return SimResult(data)


def test_time_property(sample_result):
    assert len(sample_result.time) == 4
    assert sample_result.time[0] == 0.0
    assert sample_result.time[-1] == 3.0


def test_observables_property(sample_result):
    assert "A" in sample_result.observables
    assert len(sample_result.observables["A"]) == 4


def test_n_steps(sample_result):
    assert sample_result.n_steps == 4


def test_observable_names(sample_result):
    assert sample_result.observable_names == ["A"]


def test_to_dataframe(sample_result):
    pd = pytest.importorskip("pandas")
    df = sample_result.to_dataframe()
    assert "time" in df.columns
    assert "A" in df.columns
    assert len(df) == 4


def test_plot_runs(sample_result, monkeypatch):
    mpl = pytest.importorskip("matplotlib")
    monkeypatch.setattr(mpl.pyplot, "show", lambda: None)
    sample_result.plot(show=False)


def test_repr(sample_result):
    r = repr(sample_result)
    assert "SimResult" in r
