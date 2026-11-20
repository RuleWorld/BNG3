"""Public SBML imports resolve comp external documents relative to the input."""

import pytest

import bionetgen

CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
 <model id="component"><listOfCompartments><compartment id="cell" size="1" constant="true"/></listOfCompartments>
 <listOfSpecies><species id="A" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
  boundaryCondition="false" constant="false"/></listOfSpecies><listOfReactions>
 <reaction id="birth" reversible="false" fast="false"><listOfProducts>
 <speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts><kineticLaw>
 <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></kineticLaw>
 </reaction></listOfReactions></model></sbml>"""
PARENT = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
 xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
 level="3" version="1" comp:required="true"><model id="root">
 <comp:listOfSubmodels><comp:submodel comp:id="sub" comp:modelRef="external"/>
 </comp:listOfSubmodels></model><comp:listOfExternalModelDefinitions>
 <comp:externalModelDefinition comp:id="external" comp:source="child.xml" comp:modelRef="component"/>
 </comp:listOfExternalModelDefinitions></sbml>"""


def test_public_import_executes_relative_external_model(tmp_path, monkeypatch):
    libsbml = pytest.importorskip("libsbml")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "child.xml").write_text(CHILD, encoding="utf-8")
    parent_path = model_dir / "parent.xml"
    parent_path.write_text(PARENT, encoding="utf-8")
    doc = libsbml.readSBMLFromFile(str(parent_path))
    doc.checkConsistency()
    assert not [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    monkeypatch.chdir(tmp_path)
    translated = bionetgen.sbml_to_bngl("models/parent.xml")
    assert "sub__A" in translated
    model = bionetgen.from_sbml("models/parent.xml")
    result = model.simulate(method="ode", t_end=1, n_steps=10)
    assert result.observables["sub__A_amt"][-1] == pytest.approx(2, rel=2e-6)


def test_public_import_reports_missing_external_file(tmp_path):
    parent = tmp_path / "parent.xml"
    parent.write_text(PARENT, encoding="utf-8")
    with pytest.raises(bionetgen.sbml.BioNetGenError, match="does not exist"):
        bionetgen.from_sbml(str(parent))
