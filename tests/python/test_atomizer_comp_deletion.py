"""SBML comp deletions must affect the executed reaction network."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import libsbml

import bionetgen
from bionetgen.atomizer.modern import Atomizer

_DELETION_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
    xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
    level="3" version="2" comp:required="true">
  <model id="root">
    <comp:listOfSubmodels>
      <comp:submodel comp:id="child" comp:modelRef="component">
        <comp:listOfDeletions>
          <comp:deletion comp:idRef="leak"/>
        </comp:listOfDeletions>
      </comp:submodel>
    </comp:listOfSubmodels>
  </model>
  <comp:listOfModelDefinitions>
    <comp:modelDefinition id="component">
      <listOfCompartments>
        <compartment id="c" size="1" constant="true"/>
      </listOfCompartments>
      <listOfSpecies>
        <species id="A" compartment="c" initialAmount="10"
                 hasOnlySubstanceUnits="true" boundaryCondition="false"
                 constant="false"/>
        <species id="B" compartment="c" initialAmount="0"
                 hasOnlySubstanceUnits="true" boundaryCondition="false"
                 constant="false"/>
        <species id="C" compartment="c" initialAmount="0"
                 hasOnlySubstanceUnits="true" boundaryCondition="false"
                 constant="false"/>
      </listOfSpecies>
      <listOfReactions>
        <reaction id="decay" reversible="false">
          <listOfReactants>
            <speciesReference species="A" stoichiometry="1" constant="true"/>
          </listOfReactants>
          <listOfProducts>
            <speciesReference species="B" stoichiometry="1" constant="true"/>
          </listOfProducts>
          <kineticLaw>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><cn>0.1</cn><ci>A</ci></apply>
            </math>
          </kineticLaw>
        </reaction>
        <reaction id="leak" reversible="false">
          <listOfReactants>
            <speciesReference species="A" stoichiometry="1" constant="true"/>
          </listOfReactants>
          <listOfProducts>
            <speciesReference species="C" stoichiometry="1" constant="true"/>
          </listOfProducts>
          <kineticLaw>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><cn>0.05</cn><ci>A</ci></apply>
            </math>
          </kineticLaw>
        </reaction>
      </listOfReactions>
    </comp:modelDefinition>
  </comp:listOfModelDefinitions>
</sbml>"""


def _write_external_deletion_model(tmp_path, *, extra_function=False):
    core = "http://www.sbml.org/sbml/level3/version2/core"
    comp = "http://www.sbml.org/sbml/level3/version1/comp/version1"
    root = ET.fromstring(_DELETION_MODEL)
    model_definitions = root.find(f"{{{comp}}}listOfModelDefinitions")
    assert model_definitions is not None
    model_definition = model_definitions[0]
    model_definitions.remove(model_definition)
    root.remove(model_definitions)
    model_definition.tag = f"{{{core}}}model"
    if extra_function:
        functions = ET.Element(f"{{{core}}}listOfFunctionDefinitions")
        function = ET.SubElement(
            functions, f"{{{core}}}functionDefinition", {"id": "identity"}
        )
        math = ET.SubElement(function, "{http://www.w3.org/1998/Math/MathML}math")
        lam = ET.SubElement(math, "{http://www.w3.org/1998/Math/MathML}lambda")
        ET.SubElement(lam, "{http://www.w3.org/1998/Math/MathML}bvar").append(
            ET.Element("{http://www.w3.org/1998/Math/MathML}ci")
        )
        lam[0][0].text = "x"
        ET.SubElement(lam, "{http://www.w3.org/1998/Math/MathML}ci").text = "x"
        model_definition.insert(0, functions)
    submodel = root.find(
        f"{{{core}}}model/{{{comp}}}listOfSubmodels/{{{comp}}}submodel"
    )
    assert submodel is not None
    submodel.set(f"{{{comp}}}modelRef", "componentRef")

    child_root = ET.Element(f"{{{core}}}sbml", {"level": "3", "version": "2"})
    child_root.append(model_definition)
    child_path = tmp_path / "component.xml"
    child_path.write_bytes(
        ET.tostring(child_root, encoding="utf-8", xml_declaration=True)
    )

    external_definitions = ET.SubElement(
        root, f"{{{comp}}}listOfExternalModelDefinitions"
    )
    ET.SubElement(
        external_definitions,
        f"{{{comp}}}externalModelDefinition",
        {
            f"{{{comp}}}id": "componentRef",
            f"{{{comp}}}source": "component.xml",
            f"{{{comp}}}modelRef": "component",
        },
    )
    parent_path = tmp_path / "parent.xml"
    parent_xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    parent_path.write_text(parent_xml, encoding="utf-8")
    return parent_xml, parent_path


def test_comp_submodel_deletion_changes_executed_trajectory(tmp_path):
    source_document = libsbml.readSBMLFromString(_DELETION_MODEL)
    source_errors = [
        source_document.getError(index).getMessage()
        for index in range(source_document.getNumErrors())
        if source_document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not source_errors, source_errors

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        _DELETION_MODEL
    )
    assert atomized.success, atomized.error
    model_path = tmp_path / "comp_deletion.bngl"
    model_path.write_text(atomized.bngl, encoding="utf-8")
    result = bionetgen.run(str(model_path), "ode", 1.0, 10)

    amounts_a = result.observables["child__A_amt"]
    amounts_b = result.observables["child__B_amt"]
    amounts_c = result.observables["child__C_amt"]
    assert len(amounts_a) == len(amounts_b) == len(amounts_c) == 11
    # The deleted `leak` reaction is absent. Only A -> B at flux 0.1*A remains.
    # The independent exact solution is A=10*exp(-0.1*t), B=10-A, C=0.
    for index, (amount_a, amount_b, amount_c) in enumerate(
        zip(amounts_a, amounts_b, amounts_c)
    ):
        time = index / 10
        expected_a = 10 * math.exp(-0.1 * time)
        assert math.isclose(float(amount_a), expected_a, rel_tol=2e-6, abs_tol=1e-8)
        assert math.isclose(
            float(amount_b), 10 - expected_a, rel_tol=2e-6, abs_tol=1e-8
        )
        assert math.isclose(float(amount_c), 0, abs_tol=1e-8)


def test_external_comp_submodel_deletion_changes_executed_trajectory(tmp_path):
    source, parent_path = _write_external_deletion_model(tmp_path)
    source_document = libsbml.readSBMLFromFile(str(parent_path))
    source_errors = [
        source_document.getError(index).getMessage()
        for index in range(source_document.getNumErrors())
        if source_document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not source_errors, source_errors

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        source, source_path=parent_path
    )
    assert atomized.success, atomized.error
    model_path = tmp_path / "external_comp_deletion.bngl"
    model_path.write_text(atomized.bngl, encoding="utf-8")
    result = bionetgen.run(str(model_path), "ode", 1.0, 10)

    amounts_a = result.observables["child__A_amt"]
    amounts_b = result.observables["child__B_amt"]
    amounts_c = result.observables["child__C_amt"]
    assert len(amounts_a) == len(amounts_b) == len(amounts_c) == 11
    for index, (amount_a, amount_b, amount_c) in enumerate(
        zip(amounts_a, amounts_b, amounts_c)
    ):
        time = index / 10
        expected_a = 10 * math.exp(-0.1 * time)
        assert math.isclose(float(amount_a), expected_a, rel_tol=2e-6, abs_tol=1e-8)
        assert math.isclose(
            float(amount_b), 10 - expected_a, rel_tol=2e-6, abs_tol=1e-8
        )
        assert math.isclose(float(amount_c), 0, abs_tol=1e-8)


def test_unsupported_external_deletion_shape_refuses_before_libsbml_flatten(tmp_path):
    source, parent_path = _write_external_deletion_model(tmp_path, extra_function=True)
    source_document = libsbml.readSBMLFromFile(str(parent_path))
    source_errors = [
        source_document.getError(index).getMessage()
        for index in range(source_document.getNumErrors())
        if source_document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not source_errors, source_errors

    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(
        source, source_path=parent_path
    )
    assert not atomized.success
    assert "cannot be flattened safely" in atomized.error
