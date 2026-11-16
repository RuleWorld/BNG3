import tempfile
from pathlib import Path

import bionetgen


def test_bngmodel_loads_delayed_rule_without_xml_export_failure():
    text = r"""begin model
begin parameters
  k 1
  tau 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A A()
end observables
begin reaction rules
  A() -> 0 k delay=tau
end reaction rules
end model
"""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "delay.bngl"
        path.write_text(text)
        model = bionetgen.bngmodel(str(path))
        assert "A" in model.observables
        assert len(model.rules) == 1
