"""The hybrid model generator must not claim an execution it does not perform.

``generate_hybrid_model`` records the requested actions in the generated
hybrid model's own action block; the caller reads that model back and runs
the actions against it.  The generator used to print "Executing actions on
hybrid model...", which claimed an execution that never happened there.
"""

import bionetgen
from _extdep import require_extension

require_extension()


MODEL = """begin model
begin parameters
  k 1
  N 100
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() N
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
begin population maps
  A() -> A_pop() k
end population maps
end model
"""


def test_hybrid_generator_does_not_claim_to_execute_the_actions(tmp_path, capfd):
    source = tmp_path / "model.bngl"
    source.write_text(
        MODEL
        + "\nbegin actions\n"
        + 'generate_hybrid_model({overwrite=>1, execute=>1, actions=>["writeXML()"]})\n'
        + "end actions\n"
    )
    model = bionetgen.load(source)
    model.execute()
    stderr = capfd.readouterr().err
    assert "Executing actions on hybrid model" not in stderr
    assert "Requested actions are recorded in the generated hybrid model" in stderr
