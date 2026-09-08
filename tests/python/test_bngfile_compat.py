"""Compatibility contracts for the legacy ``BNGFile`` facade."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

from bionetgen.modelapi.bngfile import BNGFile


def test_write_xml_accepts_the_file_owned_bngl_source(tmp_path):
    source = tmp_path / "file_owned.bngl"
    source.write_text("""
begin model
begin parameters
    k 1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 2
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
end model
""")

    output = io.StringIO()
    assert BNGFile(str(source)).write_xml(output)

    root = ET.fromstring(output.getvalue())
    assert root.tag.endswith("sbml")
    assert root.find(".//{*}ListOfReactionRules") is not None


def test_write_xml_file_owned_source_supports_sbml(tmp_path):
    source = tmp_path / "file_owned_sbml.bngl"
    source.write_text("""
begin model
begin parameters
    k 1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 2
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
end model
""")

    output = io.StringIO()
    assert BNGFile(str(source)).write_xml(output, xml_type="sbml")

    root = ET.fromstring(output.getvalue())
    assert root.tag.endswith("sbml")
    assert root.find(".//{*}listOfReactions") is not None


def test_legacy_bngmodel_loads_blocks_without_perl_bng(tmp_path):
    import bionetgen

    source = tmp_path / "legacy_modelapi.bngl"
    source.write_text("""
begin model
begin parameters
    k 1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 2
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
end model
""")

    model = bionetgen.bngmodel(str(source))

    assert model.model_name == "legacy_modelapi"
    assert len(model.parameters) == 1
    assert len(model.molecule_types) == 1
    assert len(model.species) == 1
    assert len(model.rules) == 1
