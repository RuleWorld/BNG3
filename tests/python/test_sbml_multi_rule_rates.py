"""SBML Multi must preserve the flux of each authored rule direction."""

from pathlib import Path

import libsbml
import bionetgen


def test_reversible_multi_rule_emits_two_mass_action_fluxes(tmp_path):
    path = tmp_path / "binding.bngl"
    path.write_text("""begin model
begin parameters
 kf 0.125
 kr 0.75
end parameters
begin molecule types
 A(b)
 B(a)
end molecule types
begin seed species
 A(b) 4
 B(a) 3
end seed species
begin reaction rules
 bind: A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
end model
""")
    document = libsbml.readSBMLFromString(bionetgen.load(str(path)).sbml_multi())
    assert document.getNumErrors() == 0
    model = document.getModel()
    assert model.getNumReactions() == 2
    forward, reverse = model.getReaction(0), model.getReaction(1)
    assert not forward.getReversible()
    assert not reverse.getReversible()
    assert forward.getNumReactants() == reverse.getNumProducts() == 2
    assert forward.getNumProducts() == reverse.getNumReactants() == 1
    for reaction, rate in [(forward, "kf"), (reverse, "kr")]:
        formula = libsbml.formulaToL3String(reaction.getKineticLaw().getMath())
        assert rate in formula
        for reference in reaction.getListOfReactants():
            assert reference.getSpecies() in formula
    assert forward.getProduct(0).getSpecies() == reverse.getReactant(0).getSpecies()
    assert [r.getSpecies() for r in forward.getListOfReactants()] == [
        p.getSpecies() for p in reverse.getListOfProducts()
    ]
