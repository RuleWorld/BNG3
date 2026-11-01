"""The BNGL action defaults must not change Python simulation defaults."""

from pathlib import Path

import pytest

from bionetgen import BioNetGenModel
from _extdep import require_extension
from tests.validation import runner

cpp = require_extension()


SOURCE = """
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  A() -> B() 0.4
end reaction rules
end model
"""


def test_python_api_keeps_ode_and_100_step_defaults():
    model = BioNetGenModel(cpp.parse_string(SOURCE))

    result = model.simulate(t_end=1.0)

    assert len(result.time) == 101
    assert result.time[0] == 0.0
    assert result.time[-1] == 1.0


def test_bngl_simulate_rejects_conflicting_step_count_aliases(tmp_path):
    source = tmp_path / "step_count_aliases.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + '  simulate({method=>"ode",t_end=>1,n_steps=>4,n_output_steps=>2})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "run")

    assert gdat is None
    assert "'n_steps' and 'n_output_steps' are the same thing" in error


@pytest.mark.parametrize(("print_net", "save_progress"), [(1, 1), (0, 0)])
def test_bngl_simulate_rejects_conflicting_network_output_aliases(
    tmp_path, print_net, save_progress
):
    source = tmp_path / "network_output_aliases.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + f'  simulate({{method=>"ode",t_end=>1,n_steps=>2,print_net=>{print_net},save_progress=>{save_progress}}})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "run")

    assert gdat is None
    assert "'print_net' and 'save_progress' are the same thing" in error


@pytest.mark.parametrize("method", ["ssa", "psa"])
def test_bngl_zero_max_sim_steps_stops_at_initial_state(tmp_path, method):
    source = tmp_path / "zero_max_sim_steps.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + f'  simulate({{method=>"{method}",t_end=>1,n_steps=>4,max_sim_steps=>0,seed=>123}})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "run")

    assert gdat is not None, error
    rows = [
        [float(value) for value in line.split()]
        for line in gdat.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert rows
    assert all(row[0] == 0.0 for row in rows)
    assert all(row[1:] == [10.0, 0.0] for row in rows)


def test_bngl_simulate_rejects_non_net_custom_netfile_suffix(tmp_path):
    source = tmp_path / "invalid_netfile_suffix.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + '  simulate({method=>"ode",t_end=>1,n_steps=>2,netfile=>"input.txt"})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "run")

    assert gdat is None
    assert "File input.txt does not have .net suffix" in error
