"""The BNGL action defaults must not change Python simulation defaults."""

from pathlib import Path

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
