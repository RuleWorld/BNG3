"""Child-model Core conversion factors survive comp flattening."""

from pathlib import Path

import pytest

from bionetgen.atomizer.modern.parser import _flatten_comp_package

SOURCE = Path(__file__).parent / "fixtures/comp_conversion/model_conversion.sbml"


def test_inline_child_model_conversion_factor_preserves_trajectory():
    libsbml = pytest.importorskip("libsbml")
    roadrunner = pytest.importorskip("roadrunner")
    source = SOURCE.read_text()
    doc = libsbml.readSBMLFromString(source)
    doc.checkConsistency()
    assert not [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    flat, failure = _flatten_comp_package(source)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[child__A]"]
    # Source Core law: dA/dt = model conversion factor * reaction extent
    # rate = 3 * 2, with A(0) = 0. No submodel conversion is specified.
    assert rr.simulate(0, 1, 2)[-1, 1] == pytest.approx(6)


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("general", [False, True])
def test_child_default_and_species_override_keep_distinct_scales(
    tmp_path, external, general
):
    roadrunner = pytest.importorskip("roadrunner")
    import xml.etree.ElementTree as ET

    source = (
        SOURCE.read_text()
        .replace(
            "</listOfSpecies>",
            '<species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" '
            'boundaryCondition="false" constant="false" conversionFactor="override"/></listOfSpecies>',
        )
        .replace(
            "</listOfParameters>",
            '<parameter id="override" value="4" constant="true"/></listOfParameters>',
        )
        .replace(
            "</listOfProducts>",
            '<speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>',
        )
    )
    source_path = None
    if external:
        core = "http://www.sbml.org/sbml/level3/version1/core"
        comp = "http://www.sbml.org/sbml/level3/version1/comp/version1"
        root = ET.fromstring(source)
        definitions = root.find(f"{{{comp}}}listOfModelDefinitions")
        child = definitions[0]
        child.tag = f"{{{core}}}model"
        child_doc = ET.Element(f"{{{core}}}sbml", level="3", version="1")
        child_doc.append(child)
        (tmp_path / "child.xml").write_bytes(
            ET.tostring(child_doc, encoding="utf-8", xml_declaration=True)
        )
        source = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
        xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
        level="3" version="1" comp:required="true"><model id="parent">
        <comp:listOfSubmodels><comp:submodel comp:id="child" comp:modelRef="external"/>
        </comp:listOfSubmodels></model><comp:listOfExternalModelDefinitions>
        <comp:externalModelDefinition comp:id="external" comp:source="child.xml"
        comp:modelRef="childModel"/></comp:listOfExternalModelDefinitions></sbml>"""
        source_path = tmp_path / "parent.xml"
        source_path.write_text(source)
    if general:
        source = source.replace(
            '<model id="parent">',
            '<model id="parent"><listOfParameters><parameter id="other" value="1" constant="true"/></listOfParameters>',
        )
        if source_path:
            source_path.write_text(source)
    flat, failure = _flatten_comp_package(source, source_path)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[child__A]", "[child__B]"]
    # Both species are produced at extent rate 2; B overrides model factor 3.
    assert rr.simulate(0, 1, 2)[-1, 1:] == pytest.approx([6, 8])


def test_inline_child_model_conversion_executes_in_bng3(tmp_path):
    import bionetgen
    from bionetgen.atomizer.modern import Atomizer

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        SOURCE.read_text()
    )
    assert atomized.success, atomized.error
    model_path = tmp_path / "converted.bngl"
    model_path.write_text(atomized.bngl)
    result = bionetgen.run(str(model_path), "ode", 1, 10)
    assert result.observables["child__A_amt"][-1] == pytest.approx(6, rel=2e-6)


def test_general_inline_flattening_keeps_child_conversion():
    roadrunner = pytest.importorskip("roadrunner")
    source = SOURCE.read_text().replace(
        '<model id="parent">',
        '<model id="parent"><listOfParameters><parameter id="unrelated" '
        'value="1" constant="true"/></listOfParameters>',
    )
    flat, failure = _flatten_comp_package(source)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[child__A]"]
    assert rr.simulate(0, 1, 2)[-1, 1] == pytest.approx(6)


def test_parent_conversion_factor_does_not_change_child_without_one():
    roadrunner = pytest.importorskip("roadrunner")
    source = (
        SOURCE.read_text()
        .replace(' conversionFactor="cf"', "")
        .replace(
            '<model id="parent">',
            '<model id="parent" conversionFactor="parent_cf"><listOfParameters>'
            '<parameter id="parent_cf" value="3" constant="true"/></listOfParameters>',
        )
    )
    flat, failure = _flatten_comp_package(source)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[child__A]"]
    assert rr.simulate(0, 1, 2)[-1, 1] == pytest.approx(2)


def test_replaced_child_species_uses_replacement_conversion_factor():
    roadrunner = pytest.importorskip("roadrunner")
    source = SOURCE.read_text().replace(
        '<model id="parent">',
        """<model id="parent"><listOfCompartments>
        <compartment id="pc" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="X" compartment="pc" initialAmount="0"
         hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
          <comp:listOfReplacedElements><comp:replacedElement comp:submodelRef="child"
            comp:idRef="A"/></comp:listOfReplacedElements></species></listOfSpecies>""",
    )
    flat, failure = _flatten_comp_package(source)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[X]"]
    assert rr.simulate(0, 1, 2)[-1, 1] == pytest.approx(2)


def test_replacement_species_factor_applies_to_parent_and_child_flux():
    libsbml = pytest.importorskip("libsbml")
    roadrunner = pytest.importorskip("roadrunner")
    source = SOURCE.read_text().replace(
        '<model id="parent">',
        """<model id="parent" conversionFactor="parent_cf"><listOfCompartments>
        <compartment id="pc" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies><species id="X" compartment="pc" initialAmount="0"
         hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false">
          <comp:listOfReplacedElements><comp:replacedElement comp:submodelRef="child"
            comp:idRef="A"/></comp:listOfReplacedElements></species></listOfSpecies>
        <listOfParameters><parameter id="parent_cf" value="5" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="pr" reversible="false" fast="false">
         <listOfProducts><speciesReference species="X" stoichiometry="1" constant="true"/>
         </listOfProducts><kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
         <cn>1</cn></math></kineticLaw></reaction></listOfReactions>""",
    )
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    assert not [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    flat, failure = _flatten_comp_package(source)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[X]"]
    # Replacement removes child A; both reactions now target parent X.
    # X inherits parent factor 5, so dX/dt = 5 * (1 + 2).
    assert rr.simulate(0, 1, 2)[-1, 1] == pytest.approx(15)


def test_nested_inline_model_default_survives_flattening():
    libsbml = pytest.importorskip("libsbml")
    roadrunner = pytest.importorskip("roadrunner")
    source = (
        SOURCE.read_text()
        .replace('comp:modelRef="childModel"', 'comp:modelRef="middle"', 1)
        .replace(
            "<comp:listOfModelDefinitions>",
            '<comp:listOfModelDefinitions><comp:modelDefinition id="middle">'
            '<comp:listOfSubmodels><comp:submodel comp:id="inner" comp:modelRef="childModel"/>'
            "</comp:listOfSubmodels></comp:modelDefinition>",
        )
    )
    doc = libsbml.readSBMLFromString(source)
    doc.checkConsistency()
    assert not [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    flat, failure = _flatten_comp_package(source)
    assert failure is None
    rr = roadrunner.RoadRunner(flat)
    rr.timeCourseSelections = ["time", "[child__inner__A]"]
    assert rr.simulate(0, 1, 2)[-1, 1] == pytest.approx(6)
