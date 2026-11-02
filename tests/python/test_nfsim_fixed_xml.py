"""BNG-XML must preserve fixed seeds for a separate native NFsim consumer."""

import xml.etree.ElementTree as ET

import pytest

from bionetgen import _bionetgen_cpp as cpp

SOURCE = """begin model
begin parameters
  kd 1
  ks 10
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  $A() 5
  B() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> 0 kd
  0 -> B() ks
end reaction rules
end model
"""


@pytest.mark.parametrize("generated_network", [False, True])
def test_xml_marks_fixed_species_for_native_nfsim(tmp_path, generated_network):
    source = tmp_path / "fixed.bngl"
    if generated_network:
        source.write_text(SOURCE + "generate_network()\nwriteXML()\n")
        cpp.execute(cpp.parse_file(str(source)), str(source), verbose=False)
        xml = source.with_suffix(".xml").read_text()
    else:
        source.write_text(SOURCE)
        xml = cpp.io.write_xml_string(cpp.parse_file(str(source)))
    species = [
        e for e in ET.fromstring(xml).iter() if e.tag.rsplit("}", 1)[-1] == "Species"
    ]

    def species_for(molecule):
        return next(
            seed
            for seed in species
            if any(
                e.tag.endswith("Molecule") and e.get("name") == molecule
                for e in seed.iter()
            )
        )

    fixed = species_for("A")
    free = species_for("B")
    assert fixed.get("Fixed") == "1"
    assert fixed.get("concentration") == "5"
    assert free.get("Fixed", "0") == "0"
