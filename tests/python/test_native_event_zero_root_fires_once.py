"""An initially-zero strict trigger must fire once, not once per detection path.

Regression for official SBML Test Suite case 00663 (pinned suite revision
``cf38585fac5de8e0e90112febb62851ee2181816``). Its strict trigger
``S4 > S3`` has root zero at t=0 and a zero initial slope. CVODE localizes the
later rising edge, while the initially-zero strict-trigger poll can also see
the positive root. Both paths queued the same event, doubling S4 twice. The
expected S4 values below are the official suite reference outputs, not values
from this implementation.
"""

from __future__ import annotations

import pytest
from _extdep import require_extension

require_extension()
import bionetgen
import bionetgen._bionetgen_cpp as cpp
from bionetgen.model import BioNetGenModel

MODEL = """begin model
begin parameters
  __Avogadro__ 1
  __compartment_C__ 1
  k1 1000
  k3 0.7
end parameters
begin compartments
  C 3 1
end compartments
begin molecule types
  M_S1()
  M_S2()
  M_S3()
  M_S4()
end molecule types
begin seed species
  @C:M_S1() 0.002
  @C:M_S2() 0.002
  @C:M_S3() 0
  @C:M_S4() 0
end seed species
begin observables
  Species S1_amt @C:M_S1()
  Species S2_amt @C:M_S2()
  Species S3_amt @C:M_S3()
  Species S4_amt @C:M_S4()
end observables
begin functions
  _c_S1() = S1_amt / __compartment_C__
  _c_S2() = S2_amt / __compartment_C__
  _c_S3() = S3_amt / __compartment_C__
  _c_S4() = S4_amt / __compartment_C__
  k2() = 0.9
  reaction1_rate() = __compartment_C__ * k1 * _c_S1() * _c_S2()
  reaction2_rate() = __compartment_C__ * (0.9) * _c_S3()
  reaction3_rate() = __compartment_C__ * k3 * _c_S3()
end functions
begin reaction rules
  reaction1: @C:M_S1() + @C:M_S2() -> @C:M_S3() 1000
  reaction2: @C:M_S3() -> @C:M_S1() + @C:M_S2() k2()
  reaction3: @C:M_S3() -> @C:M_S1() + @C:M_S4() 0.7
end reaction rules
begin bng3_events version 1
  event "event1"
    trigger: S4_amt > S3_amt
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: S4_amt = 2 * S4_amt
  end event
end bng3_events
end model
"""


def test_initially_zero_strict_trigger_fires_once(tmp_path):
    bngl = tmp_path / "strict0.bngl"
    bngl.write_text(MODEL)
    model = BioNetGenModel(cpp.parse_file(str(bngl)), source_path=str(bngl))
    result = model.simulate(method="ode", t_end=2.0, n_steps=10)
    s4 = result.observables["S4_amt"]

    # Official SSTS 00663 reference values at t=1.6 and t=2.0.
    assert s4[8] == pytest.approx(0.001383678295203963, abs=1e-6)
    assert s4[10] == pytest.approx(0.001554424237313804, abs=1e-6)
