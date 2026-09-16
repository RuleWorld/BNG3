from pathlib import Path

import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

import bionetgen


def test_sbml_to_bngl_and_from_sbml():
    sbml_path = (
        Path(__file__).parent.parent
        / "validation"
        / "Validate"
        / "INPUT_FILES"
        / "test_sbml_flat_SBML.xml"
    )
    assert sbml_path.exists()

    try:
        bngl_text = bionetgen.sbml_to_bngl(str(sbml_path), atomize=False)
        model = bionetgen.from_sbml(str(sbml_path), atomize=False)
    except bionetgen.BioNetGenError as exc:
        pytest.skip(f"SBML import unavailable in this environment: {exc}")

    assert "begin model" in bngl_text
    assert len(model.parameters) > 0
    assert len(model.seed_species) > 0


def test_from_sbml_preserves_source_metadata_on_sbml_export(tmp_path):
    pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen.atomizer.modern import SBMLParser, source_metadata_payload

    source = tmp_path / "source.xml"
    source.write_text(
        """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
            xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns:bqbiol="http://biomodels.net/biology-qualifiers/"
            level="3" version="2">
          <model id="public_metadata" metaid="meta_model" sboTerm="SBO:0000001">
            <notes><body xmlns="http://www.w3.org/1999/xhtml">source note</body></notes>
            <annotation><rdf:RDF><rdf:Description rdf:about="#meta_model">
              <bqbiol:is><rdf:Bag><rdf:li rdf:resource="urn:miriam:pubmed:12345"/></rdf:Bag></bqbiol:is>
            </rdf:Description></rdf:RDF></annotation>
            <listOfCompartments><compartment id="cell" size="1" constant="true"/></listOfCompartments>
            <listOfSpecies><species id="A" compartment="cell" initialAmount="1"/></listOfSpecies>
            <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
            <listOfReactions><reaction id="r">
              <listOfReactants><speciesReference species="A"/></listOfReactants>
              <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math></kineticLaw>
            </reaction></listOfReactions>
          </model>
        </sbml>""",
        encoding="utf-8",
    )

    model = bionetgen.from_sbml(str(source))
    output = tmp_path / "roundtrip.xml"
    model.write_sbml(str(output))

    source_model = SBMLParser().parse(source.read_text(encoding="utf-8"))
    roundtrip_model = SBMLParser().parse(output.read_text(encoding="utf-8"))
    assert source_metadata_payload(source_model)
    assert roundtrip_model.source_metadata_payload == source_metadata_payload(source_model)
