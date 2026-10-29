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


def test_multi_binding_topology_is_encoded_without_pattern_name_fallback(tmp_path):
    import xml.etree.ElementTree as ET
    from bionetgen.atomizer.modern.multi import parse_multi_package

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
    xml = bionetgen.load(str(path)).sbml_multi()
    root = ET.fromstring(xml)
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "species":
            node.attrib.pop("name", None)
    result = parse_multi_package(ET.tostring(root, encoding="unicode"))
    assert result.executable, [warning.message for warning in result.warnings]
    multi_ns = "{http://www.sbml.org/sbml/level3/version1/multi/version1}"
    assert list(root.iter(multi_ns + "inSpeciesTypeBond"))
    mappings = list(root.iter(multi_ns + "speciesTypeComponentMapInProduct"))
    assert len(mappings) == 4

    # SBML references have their own global IDs; aliasing a species ID makes
    # the importer read a kinetic-law species symbol as stoichiometry 1.
    core_ids = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
    assert len(core_ids) == len(set(core_ids))
    structural = tmp_path / "structural.xml"
    ET.ElementTree(root).write(structural, encoding="unicode")
    imported = bionetgen.from_sbml(str(structural))
    original = bionetgen.load(str(path))
    import numpy as np

    expected = original.simulate(method="ode", t_end=1, n_steps=4)
    actual = imported.simulate(method="ode", t_end=1, n_steps=4)
    np.testing.assert_allclose(
        actual.concentrations, expected.concentrations, rtol=1e-6, atol=1e-8
    )
