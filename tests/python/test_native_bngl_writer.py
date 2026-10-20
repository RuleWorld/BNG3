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


@pytest.mark.parametrize(
    ("rate", "canonical"),
    [
        ("Arrhenius(phi,Ea)", "Arrhenius(phi, Ea)"),
        ("Sat(Vmax,Km,S)", "Sat(Vmax, Km, S)"),
        ("Hill(Vmax,Kh,n,S)", "Hill(Vmax, Kh, n, S)"),
        ("MM(kcat,Km,St,Et)", "MM(kcat, Km, St, Et)"),
    ],
)
def test_native_writer_emits_a_rate_law_spelling_the_reader_accepts(
    tmp_path, rate, canonical
):
    """The writer must emit a spelling the reader -- and BNG2 -- accept.

    The parser lower-cases every function name it reads, and the grammar's
    rate-law keywords are spelled 'Sat', 'MM', 'Hill' and 'Arrhenius'. A
    writer that emitted the lower-cased name produced text the reader reads
    back as an ordinary identifier, so the model could not be executed
    again, and canonical BioNetGen rejected it as well.
    """
    source = tmp_path / "model.bngl"
    source.write_text(f"""begin model
begin parameters
  phi 0.5
  Ea 1
  GU 0
  GP 1
  Vmax 2
  Km 1
  S 1
  Kh 1
  n 2
  kcat 1
  St 1
  Et 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin energy patterns
  A() GU
  B() GP
end energy patterns
begin seed species
  A() 10
  B() 0
end seed species
begin reaction rules
  convert: A() -> B() {rate}
end reaction rules
end model
""")
    model = bionetgen.load(source)
    target = tmp_path / "written.bngl"
    model.write_bngl(str(target))

    written = target.read_text(encoding="utf-8")
    assert canonical in written
    assert f"convert: A() -> B() {canonical}" in written

    # The written model has to be executable again: the spelling is only
    # canonical if the reader accepts it.
    restored = bionetgen.load(target)
    restored.generate_network()
