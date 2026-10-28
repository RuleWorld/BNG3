"""Compartments with more than three spatial dimensions.

SBML Level 3 Version 2 Core Sec. 4.5.2 lets a compartment declare any
floating-point ``spatialDimensions`` value. An integer value above 3 is kept
in the BNGL compartment declaration, and the writer keeps the reaction's
explicit SBML flux for any compartment whose dimension is not 2 or 3, so no
rate depends on the declared dimension.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer


def _model(dimensions: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
      <model id="spatial_dimensions">
        <listOfCompartments>
          <compartment id="C" spatialDimensions="{dimensions}" size="4" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"
                   boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.5" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k</ci><ci>S1</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""


def _compartment_warnings(atomizer, severity):
    return [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "compartment" and warning["severity"] == severity
    ]


def test_integer_dimension_above_three_is_preserved():
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_model("7"))

    assert result.success, result.error
    assert not _compartment_warnings(
        atomizer, "dropped"
    ), atomizer.model.import_warnings
    assert _compartment_warnings(atomizer, "info"), atomizer.model.import_warnings
    compartments = result.bngl.split("begin compartments", 1)[1].split(
        "end compartments", 1
    )[0]
    declarations = [
        line.split("#", 1)[0].split()
        for line in compartments.strip().splitlines()
        if line.split("#", 1)[0].strip()
    ]
    assert len(declarations) == 1, compartments
    name, dimension, size = declarations[0][:3]
    assert (name, dimension) == ("C", "7")
    assert float(size) == 4.0


def test_non_integer_dimension_above_three_is_still_refused():
    # The BNGL compartment declaration holds an integer dimension, so a
    # non-integer value above 3 cannot be preserved.
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_model("7.5"))

    assert result.success, result.error
    assert _compartment_warnings(atomizer, "dropped"), atomizer.model.import_warnings
