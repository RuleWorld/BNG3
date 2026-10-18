"""Native writer round trips must preserve model identity and dependencies."""

import pytest
import bionetgen
from _extdep import require_extension

require_extension()


@pytest.mark.parametrize("seed", ["@cell:A() N", "$@cell:A() N", "A()@cell N"])
def test_native_writer_preserves_seed_semantics_and_rule_label(tmp_path, seed):
    source = tmp_path / "model.bngl"
    source.write_text(f"""begin model
begin parameters
  k 0.4
  N 20
end parameters
begin compartments
  cell 3 1
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  {seed}
end seed species
begin observables
  Molecules A_total @cell:A()
end observables
begin reaction rules
  convert: @cell:A() -> @cell:B() k
end reaction rules
end model
""")
    model = bionetgen.load(source)
    target = tmp_path / "written.bngl"
    model.write_bngl(str(target))
    restored = bionetgen.load(target)
    assert bionetgen.semantic_equal(model, restored, version="0.2")
    model.set_parameter("N", 35)
    restored.set_parameter("N", 35)
    assert bionetgen.semantic_equal(model, restored, version="0.2")
