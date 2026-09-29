"""Governed diagnostics for unsupported SBML packages and absent MathML.

The modern Atomizer has to choose between representing a construct exactly and
refusing it.  These tests pin the two places where the parser used to stay
silent: a declared SBML Level 3 package whose elements are not imported, and a
reaction whose kinetic law carries no MathML (the writer substitutes a
fallback rate for it).
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer, SBMLParser


def _topology_sbml() -> str:
    return """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:topology="http://www.sbml.org/sbml/level3/version1/topology/version1"
      level="3" version="1" topology:required="true">
  <model id="topology_model">
    <topology:interaction id="link1" sboTerm="FMA:0000000"/>
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def test_declared_topology_package_elements_are_reported_as_dropped():
    model = SBMLParser().parse(_topology_sbml())

    warning = next(
        record
        for record in model.import_warnings
        if record["category"] == "package:topology"
    )
    assert warning["severity"] == "dropped"
    assert "not imported" in warning["message"]
    assert "1 element(s)" in warning["message"]


def test_required_unsupported_package_reports_the_package_requirement():
    model = SBMLParser().parse(_topology_sbml())

    warning = next(
        record
        for record in model.import_warnings
        if record["category"] == "package:topology"
    )
    assert "required" in warning["message"]


def test_declared_package_without_elements_produces_no_unsupported_report():
    sbml = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:topology="http://www.sbml.org/sbml/level3/version1/topology/version1"
      level="3" version="1" topology:required="false">
  <model id="empty_topology_package">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
  </model>
</sbml>"""

    model = SBMLParser().parse(sbml)

    assert not any(
        record["category"] == "package:topology" for record in model.import_warnings
    )


def test_core_only_model_reports_no_package_diagnostic():
    sbml = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="core_only">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
  </model>
</sbml>"""

    model = SBMLParser().parse(sbml)

    assert not any(
        record["category"].startswith("package:") for record in model.import_warnings
    )


def _reaction_without_kinetic_math(kinetic_law: str) -> str:
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="no_kinetic_math">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
      <species id="B" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        {kinetic_law}
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def test_empty_kinetic_law_reports_missing_math():
    model = SBMLParser().parse(_reaction_without_kinetic_math("<kineticLaw/>"))

    warning = next(
        record
        for record in model.import_warnings
        if record["category"] == "missingMath" and "R1" in record["message"]
    )
    assert warning["severity"] == "dropped"


def test_absent_kinetic_law_reports_missing_math():
    model = SBMLParser().parse(_reaction_without_kinetic_math(""))

    warning = next(
        record
        for record in model.import_warnings
        if record["category"] == "missingMath" and "R1" in record["message"]
    )
    assert warning["severity"] == "dropped"


def test_missing_math_diagnostic_reaches_the_generated_bngl_import_notes():
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _reaction_without_kinetic_math("<kineticLaw/>")
    )

    assert result.success
    assert "R1:" in result.bngl
    assert "missingMath" in result.bngl
