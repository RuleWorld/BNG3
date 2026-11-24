"""writeSBML's prefix argument must name the exported artifact for its consumer.

Regression: ActionDispatch ignored ``prefix`` for writeSBML and wrote
``<model>_<suffix>.xml`` regardless, so the ``action.writeSBML.prefix`` contract
could not be satisfied. The export is consumed with libRoadRunner and compared
against the source model's closed-form law.
"""

from __future__ import annotations

import math

import pytest
from _extdep import require_extension

require_extension()
import bionetgen

rr = pytest.importorskip("roadrunner")

MODEL = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeSBML({prefix=>"custom",suffix=>"suf",overwrite=>1})
"""


def test_prefixed_sbml_export_is_consumed_by_roadrunner(tmp_path):
    source = tmp_path / "m.bngl"
    source.write_text(MODEL)
    bionetgen.load(str(source)).execute()

    exported = tmp_path / "custom_suf.xml"
    assert exported.is_file()
    assert not (tmp_path / "m_suf.xml").exists()

    simulator = rr.RoadRunner(str(exported))
    result = simulator.simulate(0.0, 1.0, 2)
    assert result["[S1]"][-1] == pytest.approx(10 * math.exp(-0.1), rel=1e-4)
