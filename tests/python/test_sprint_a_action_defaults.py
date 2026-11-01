"""The BNGL action defaults must not change Python simulation defaults."""

import math
from pathlib import Path

import pytest

from bionetgen import BioNetGenModel
from _extdep import require_extension
from tests.validation import compare, runner

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


def test_bngl_simulate_rejects_unknown_expand_mode(tmp_path):
    source = tmp_path / "unknown_expand_mode.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + '  simulate({method=>"ode",t_end=>1,n_steps=>2,expand=>"invalid"})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / "run")

    assert gdat is None
    assert "Unrecognized expand method invalid" in error


@pytest.mark.parametrize("expand", ["lazy", "layered"])
def test_bngl_simulate_accepts_supported_expand_modes(tmp_path, expand):
    source = tmp_path / f"expand_{expand}.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + f'  simulate({{method=>"ode",t_end=>1,n_steps=>2,expand=>"{expand}"}})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / expand)

    assert gdat is not None, error


@pytest.mark.parametrize("print_end", [0, 1])
def test_bngl_simulate_print_end_controls_final_network(tmp_path, print_end):
    source = tmp_path / f"print_end_{print_end}.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + f'  simulate({{method=>"ode",prefix=>"custom",t_end=>1,n_steps=>2,print_end=>{print_end}}})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"
    run_dir = tmp_path / f"run_{print_end}"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, run_dir)

    assert gdat is not None, error
    end_net = run_dir / "custom_end.net"
    if print_end:
        assert end_net.is_file()
        parsed = compare.parse_net(end_net)
        assert parsed is not None
        amount_by_species = {
            parsed.species_by_index[index]: float(amount)
            for index, amount in parsed.initial_amounts.items()
        }
        expected_a = 10.0 * math.exp(-0.4)
        assert amount_by_species["A()"] == pytest.approx(expected_a, abs=1e-6)
        assert amount_by_species["B()"] == pytest.approx(10.0 - expected_a, abs=1e-6)
    else:
        assert not end_net.exists()


@pytest.mark.parametrize("print_active", [0, 1])
def test_bngl_simulate_print_n_species_active_controls_ode_jdat(tmp_path, print_active):
    source = tmp_path / f"print_active_{print_active}.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + f'  simulate({{method=>"ode",prefix=>"custom",t_end=>1,n_steps=>2,print_n_species_active=>{print_active}}})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"
    run_dir = tmp_path / f"run_{print_active}"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, run_dir)

    assert gdat is not None, error
    jdat = run_dir / "custom.jdat"
    if not print_active:
        assert not jdat.exists()
        return

    rows = [
        [float(value) for value in line.split()]
        for line in jdat.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert [row[0] for row in rows] == [0.0, 0.5, 1.0]
    assert [int(row[1]) for row in rows] == [1, 2, 2]
    assert [int(row[2]) for row in rows] == [0, 0, 0]
    assert [int(row[3]) for row in rows] == [2, 2, 2]
    observable_rows = [
        [float(value) for value in line.split()]
        for line in gdat.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for time, a_count, b_count in observable_rows:
        expected_a = 10.0 * math.exp(-0.4 * time)
        assert a_count == pytest.approx(expected_a, abs=1e-6)
        assert b_count == pytest.approx(10.0 - expected_a, abs=1e-6)


@pytest.mark.parametrize("method", ["ssa", "pla", "psa", "nf"])
def test_bngl_simulate_print_n_species_active_rejects_unqualified_methods(
    tmp_path, method
):
    source = tmp_path / f"print_active_{method}.bngl"
    source.write_text(
        SOURCE
        + "\nbegin actions\n"
        + f'  simulate({{method=>"{method}",t_end=>1,n_steps=>2,print_n_species_active=>1,seed=>1}})\n'
        + "end actions\n",
        encoding="utf-8",
    )
    bng_cpp = Path(__file__).resolve().parents[2] / "build/cpp/bng_cpp"

    _, gdat, error = runner.run_cli_path(bng_cpp, source, tmp_path / f"run_{method}")

    assert gdat is None
    assert "print_n_species_active is currently supported only for ODE methods" in error
