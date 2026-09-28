"""Regression tests for the cross-engine Atomizer benchmark workers."""

from pathlib import Path

from benchmarks.benchmark_atomizer_cross_engine import run_atomizer


def test_modern_benchmark_worker_resolves_external_comp_source(tmp_path: Path):
    parent_path = tmp_path / "parent.xml"
    child_path = tmp_path / "child.xml"
    child_path.write_text(
        """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
            level="3" version="2">
          <model id="childModel">
            <listOfCompartments>
              <compartment id="cell" size="1" constant="true"/>
            </listOfCompartments>
            <listOfSpecies>
              <species id="A" compartment="cell" initialAmount="2"
                       hasOnlySubstanceUnits="true" boundaryCondition="false"
                       constant="false"/>
            </listOfSpecies>
            <listOfReactions>
              <reaction id="synthesis" reversible="false">
                <listOfProducts>
                  <speciesReference species="A" stoichiometry="1" constant="true"/>
                </listOfProducts>
                <kineticLaw>
                  <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
                </kineticLaw>
              </reaction>
            </listOfReactions>
          </model>
        </sbml>""",
        encoding="utf-8",
    )
    parent_path.write_text(
        """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
            xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
            level="3" version="2" comp:required="true">
          <model id="parent">
            <comp:listOfSubmodels>
              <comp:submodel comp:id="child" comp:modelRef="childModel"/>
            </comp:listOfSubmodels>
          </model>
          <comp:listOfExternalModelDefinitions>
            <comp:externalModelDefinition comp:id="childModel"
                                          comp:source="child.xml"
                                          comp:modelRef="childModel"/>
          </comp:listOfExternalModelDefinitions>
        </sbml>""",
        encoding="utf-8",
    )
    output_path = tmp_path / "converted.bngl"

    result = run_atomizer(
        source=parent_path,
        mode="flat",
        output=output_path,
        metadata=tmp_path / "metadata.json",
        implementation="bng3_modern",
        pybionetgen_root=tmp_path,
    )

    assert result["status"] == "ok", result
    bngl = output_path.read_text(encoding="utf-8")
    assert "child__A()" in bngl
    assert "child__synthesis" in bngl
