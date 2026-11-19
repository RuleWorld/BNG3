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
    assert roundtrip_model.source_metadata_payload == source_metadata_payload(
        source_model
    )


# Independently authored metadata-preservation case for #160's
# ``sbml.core.SBase.notes`` slice.  This is NOT one of the official FBC cases
# (01186/01187/01188): those are flux-balance cases with no time-course
# reference whose official expectation checks R01/R26/OBJF optima, not notes.
# The source below is a small libSBML-valid kinetic model carrying meaningful
# XHTML notes on two distinguishable SBase elements: the Model and species A.
_NOTES_ROUNDTRIP_SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="notes_model" metaid="meta_model">
    <notes><body xmlns="http://www.w3.org/1999/xhtml">
      <p>Model-level <em>provenance</em> note for the notes round-trip case.</p>
    </body></notes>
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" metaid="meta_A" compartment="cell" initialAmount="1"
               hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false">
        <notes><body xmlns="http://www.w3.org/1999/xhtml">
          <p>Species-A <strong>identifier</strong> note; must stay on A.</p>
        </body></notes>
      </species>
      <species id="B" metaid="meta_B" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="r" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""

# Distinctive text/markup that must remain on each owning element.  The two
# sets are deliberately disjoint so relocating a note to the wrong element is
# caught (element ownership, not just content presence).
_NOTES_EXPECTED = {
    "model": {
        "tokens": ("Model-level", "provenance", "notes round-trip case"),
        "markup": ("<em>", "</em>", "<p>"),
    },
    "species_A": {
        "tokens": ("Species-A", "identifier", "must stay on A"),
        "markup": ("<strong>", "</strong>", "<p>"),
    },
}


def _libsbml_notes(path):
    """Return libSBML-visible notes for the two elements, keyed by owner."""
    libsbml = pytest.importorskip("libsbml")
    doc = libsbml.readSBMLFromFile(str(path))
    assert doc.getNumErrors() == 0, "fixture must be libSBML-valid"
    model = doc.getModel()
    species_a = model.getElementByMetaId("meta_A")
    return {
        "model": model.getNotesString() if model.isSetNotes() else "",
        "species_A": (
            species_a.getNotesString()
            if species_a is not None and species_a.isSetNotes()
            else ""
        ),
    }


def _notes_preserved(exported):
    """Comparator: each element keeps its own notes content and markup."""
    for owner, spec in _NOTES_EXPECTED.items():
        note = exported.get(owner, "")
        if not note:
            return False
        if any(token not in note for token in spec["tokens"]):
            return False
        if any(tag not in note for tag in spec["markup"]):
            return False
    return True


def test_notes_comparator_catches_removal_and_relocation(tmp_path):
    """Positive control for the comparator itself, using the authored source.

    A comparator that accepts every input proves nothing.  Removing a note or
    moving A's note onto the Model must both be rejected.
    """
    source = tmp_path / "source.xml"
    source.write_text(_NOTES_ROUNDTRIP_SBML, encoding="utf-8")
    original = _libsbml_notes(source)
    assert all(original.values()), "source must carry notes on both elements"
    assert _notes_preserved(original) is True

    removed = {"model": "", "species_A": original["species_A"]}
    moved = {
        "model": original["model"] + " " + original["species_A"],
        "species_A": "",
    }
    assert _notes_preserved(removed) is False
    assert _notes_preserved(moved) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "#160 metadata finding: the public from_sbml(...).write_sbml(...) path "
        "does not restore XHTML <notes> on SBase elements. The Atomizer retains "
        "the raw notesXml in the bng:sourceMetadata base64 annotation payload, "
        "but the C++ SbmlWriter emits only that opaque model-level annotation, "
        "so libSBML getNotes()/getNotesString() returns empty for both the Model "
        "and species A after export. First stage of loss: the SBML write/export "
        "step (cpp/io/SbmlWriter.cpp), not SBML import. Turning green requires a "
        "product change that re-emits per-element <notes>; this case is scoped "
        "evidence for SBase.notes only and grants no kinetic or whole-row "
        "acceptance."
    ),
)
def test_public_sbml_roundtrip_preserves_libsbml_notes_on_two_elements(tmp_path):
    """The authored metadata-preservation case over the real public path."""
    pytest.importorskip("bionetgen._bionetgen_cpp")
    source = tmp_path / "source.xml"
    source.write_text(_NOTES_ROUNDTRIP_SBML, encoding="utf-8")
    original = _libsbml_notes(source)

    model = bionetgen.from_sbml(str(source))
    output = tmp_path / "roundtrip.xml"
    model.write_sbml(str(output))

    assert _libsbml_notes(output) == original
    assert _notes_preserved(_libsbml_notes(output)) is True
