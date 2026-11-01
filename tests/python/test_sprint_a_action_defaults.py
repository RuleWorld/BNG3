"""The BNGL action defaults must not change Python simulation defaults."""

from bionetgen import BioNetGenModel
from _extdep import require_extension

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
