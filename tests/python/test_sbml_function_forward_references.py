"""Export forward function calls without confusing compartment identifiers."""

import numpy as np
import pytest

MODEL = """
begin model
begin compartments
  C 3 2
end compartments
begin molecule types
  A()
  P()
end molecule types
begin seed species
  @C:A() 10
  @C:P() 2
end seed species
begin observables
  Species amount @C:A()
  Species volume @C:P()
end observables
begin functions
  concentration() = amount / C()
  C() = volume
end functions
begin reaction rules
  decay: @C:A() -> 0 C()*concentration() TotalRate
  grow: 0 -> @C:P() 1 TotalRate
end reaction rules
end model
"""


def test_export_forward_function_call_that_shares_a_compartment_name(tmp_path):
    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp

    roadrunner = pytest.importorskip("roadrunner")
    model = cpp.parse_string(MODEL)
    actual = BioNetGenModel(model).simulate(method="ode", t_end=2, n_steps=20)
    expected = 10 * np.exp(-np.asarray(actual.time))
    np.testing.assert_allclose(actual.observables["amount"], expected, rtol=1e-6)
    exported = tmp_path / "forward.xml"
    cpp.io.write_sbml(model, cpp.generate_network(model), str(exported))
    oracle = roadrunner.RoadRunner(str(exported))
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    result = oracle.simulate(times=actual.time, selections=["time", "amount"])
    np.testing.assert_allclose(result[:, 1], expected, rtol=1e-6)
