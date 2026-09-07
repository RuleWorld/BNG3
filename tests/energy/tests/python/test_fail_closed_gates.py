import numpy as np
import pytest

from scripts import compare_numeric_tables as tables
from scripts import energy_performance_gate as performance
from scripts import nf_energy_statistical_parity as statistical
from scripts import run_energy_validation as runner


def test_nf_header_retains_first_data_row(tmp_path):
    p = tmp_path / "result.gdat"
    p.write_text("# time A\n0 3\n1 4\n")
    assert tables.load_table(p) == (["time", "A"], [[0.0, 3.0], [1.0, 4.0]])


@pytest.mark.parametrize("content", ["time A\n", "0 3\n1 4\n", "time A A\n0 1 2\n"])
def test_table_requires_named_unique_columns_and_data(tmp_path, content):
    p = tmp_path / "result.gdat"
    p.write_text(content)
    with pytest.raises(ValueError):
        tables.load_table(p)


def test_matching_infinities_are_not_valid_simulation_output(tmp_path):
    p = tmp_path / "result.gdat"
    p.write_text("time A\n0 inf\n")
    assert not tables.compare(p, p)["passed"]


def test_nan_tolerance_cannot_accept_arbitrary_values(tmp_path):
    p = tmp_path / "result.gdat"
    p.write_text("time A\n0 1\n")
    with pytest.raises(ValueError):
        tables.compare(p, p, rtol=float("nan"))


@pytest.mark.parametrize(
    "observables,times", [({}, [0]), ({"A": np.empty((3, 0))}, [])]
)
def test_stochastic_comparison_requires_observations(observables, times):
    with pytest.raises(ValueError):
        statistical.compare_trajectories(observables, observables, times)


def test_unimplemented_backend_cannot_pass_an_on_off_comparison(tmp_path):
    with pytest.raises(NotImplementedError, match="backend activation"):
        statistical.run_gate(tmp_path / "model.bngl", [1, 2], 1, 1)


def test_zero_ctest_cases_is_failure(tmp_path):
    (tmp_path / "CTestTestfile.cmake").write_text("")
    result = runner.run_ctest(tmp_path, "energy")
    assert not result["passed"]


@pytest.mark.parametrize("count", [0, -1, 1.5, True, float("nan")])
def test_invalid_reaction_class_counts_cannot_pass_performance(count):
    base = dict(
        disabled_median_s=1,
        nonenergy_median_s=1,
        energy_construction_median_s=8,
        energy_reaction_classes=256,
        energy_predicates=8,
    )
    candidate = dict(
        base, energy_reaction_classes=count, energy_construction_median_s=1
    )
    with pytest.raises(ValueError):
        performance.evaluate(base, candidate)
