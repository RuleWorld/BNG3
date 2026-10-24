import numpy as np

from bionetgen import BioNetGenModel
from _extdep import require_extension


cpp = require_extension()


SOURCE = """
begin model
begin parameters
  tau 2
end parameters
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
  A() -> B() 0.5 delay=tau
end reaction rules
end model
"""


def test_python_native_continuation_reset_and_default_fresh_run():
    model = BioNetGenModel(cpp.parse_string(SOURCE))
    first = model.simulate(method="ode", t_end=2.0, n_steps=4)
    continued = model.simulate(
        method="ode", t_start=2.0, t_end=4.0, n_steps=4,
        continue_simulation=True,
    )
    a = continued.observables["A_count"]
    b = continued.observables["B_count"]
    np.testing.assert_allclose(a[-1], 10.0 * np.exp(-2.0), rtol=1e-5)
    np.testing.assert_allclose(b[-1], 10.0 * (1.0 - np.exp(-1.0)), rtol=1e-5)
    np.testing.assert_allclose(first.observables["B_count"][-1], 0.0, atol=1e-8)

    # A plain call starts from model seeds even though the binding updates the
    # cached generated network after each native simulation.
    fresh = model.simulate(method="ode", t_end=4.0, n_steps=8)
    np.testing.assert_allclose(fresh.observables["A_count"][-1], a[-1], rtol=1e-5)
    np.testing.assert_allclose(fresh.observables["B_count"][-1], b[-1], rtol=1e-5)

    model.reset_simulation()
    reset = model.simulate(method="ode", t_end=2.0, n_steps=4)
    np.testing.assert_allclose(reset.observables["A_count"][0], 10.0)
    np.testing.assert_allclose(reset.observables["B_count"][-1], 0.0, atol=1e-8)
