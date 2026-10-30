"""Independent Core oracles for Multi numericValue and sum kinetics.

The Multi source declares a state value's numeric parameter.  The separate
Core model states the resulting elementary reaction directly; it is not made
by stripping the Multi package or by enumerating a candidate network.
"""

import libsbml
import numpy as np
import pytest
roadrunner = pytest.importorskip("roadrunner")

from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer, SBMLParser

MULTI_SOURCE = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
  xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
  level="3" version="1" multi:required="true">
  <model id="multi_numeric_rate">
    <listOfCompartments><compartment id="cell" size="0.5"
      spatialDimensions="3" constant="true" multi:isType="false"/></listOfCompartments>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="10"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
        multi:speciesType="AType">
        <multi:listOfSpeciesFeatures><multi:speciesFeature
          multi:speciesFeatureType="state" multi:occur="1">
          <multi:listOfSpeciesFeatureValues>
            <multi:speciesFeatureValue multi:value="state_u"/>
          </multi:listOfSpeciesFeatureValues>
        </multi:speciesFeature></multi:listOfSpeciesFeatures>
      </species>
      <species id="Ap" compartment="cell" initialAmount="0"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
        multi:speciesType="AType">
        <multi:listOfSpeciesFeatures><multi:speciesFeature
          multi:speciesFeatureType="state" multi:occur="1">
          <multi:listOfSpeciesFeatureValues>
            <multi:speciesFeatureValue multi:value="state_p"/>
          </multi:listOfSpeciesFeatureValues>
        </multi:speciesFeature></multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.3" constant="true"/></listOfParameters>
    <listOfReactions><reaction id="activate" reversible="false" fast="false">
      <listOfReactants><speciesReference id="source_ref" species="Au"
        stoichiometry="1" constant="true"/></listOfReactants>
      <listOfProducts><speciesReference id="target_ref" species="Ap"
        stoichiometry="1" constant="true"/></listOfProducts>
      <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
        <apply><times/>
          <ci multi:representationType="numericValue"
            multi:speciesReference="source_ref">state_u</ci>
          <ci>Au</ci>
        </apply>
      </math></kineticLaw>
    </reaction></listOfReactions>
    <multi:listOfSpeciesTypes><multi:speciesType multi:id="AType" multi:name="A"
      multi:compartment="cell">
      <multi:listOfSpeciesFeatureTypes><multi:speciesFeatureType multi:id="state"
        multi:name="x" multi:occur="1">
        <multi:listOfPossibleSpeciesFeatureValues>
          <multi:possibleSpeciesFeatureValue multi:id="state_u" multi:name="u"
            multi:numericValue="k"/>
          <multi:possibleSpeciesFeatureValue multi:id="state_p" multi:name="p"/>
        </multi:listOfPossibleSpeciesFeatureValues>
      </multi:speciesFeatureType></multi:listOfSpeciesFeatureTypes>
    </multi:speciesType></multi:listOfSpeciesTypes>
  </model>
</sbml>"""

CORE_ORACLE = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
  level="3" version="1">
  <model id="explicit_numeric_rate">
    <listOfCompartments><compartment id="cell" size="0.5"
      spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="10"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Ap" compartment="cell" initialAmount="0"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.3" constant="true"/></listOfParameters>
    <listOfReactions><reaction id="activate" reversible="false" fast="false">
      <listOfReactants><speciesReference species="Au" stoichiometry="1"
        constant="true"/></listOfReactants>
      <listOfProducts><speciesReference species="Ap" stoichiometry="1"
        constant="true"/></listOfProducts>
      <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
        <apply><times/><ci>k</ci><ci>Au</ci></apply>
      </math></kineticLaw>
    </reaction></listOfReactions>
  </model>
</sbml>"""

# The second Multi source explicitly requests the sum representation of a
# state-resolved species (Au). The independent Core source writes Au*Au,
# whereas the first oracle writes k*Au.  This avoids using the candidate's
# Multi-to-BNGL lowering to derive either expected kinetic law.
MULTI_SUM_SOURCE = MULTI_SOURCE.replace(
    '<ci multi:representationType="numericValue"\n'
    '            multi:speciesReference="source_ref">state_u</ci>',
    '<ci multi:representationType="sum">Au</ci>',
)
CORE_SUM_ORACLE = CORE_ORACLE.replace(
    "<apply><times/><ci>k</ci><ci>Au</ci></apply>",
    "<apply><times/><ci>Au</ci><ci>Au</ci></apply>",
)

# Aany is an unseeded wildcard state pattern, so its Multi sum counts both Au
# and Ap.  The independently authored Core law is (Au + Ap) * Au.  In
# particular, a missing wildcard observable must not silently become zero.
MULTI_WILDCARD_SUM_SOURCE = (
    MULTI_SUM_SOURCE.replace(
        "</listOfSpecies>",
        '<species id="Aany" compartment="cell" initialAmount="0" '
        'hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" '
        'multi:speciesType="AType"/></listOfSpecies>',
    )
    .replace(
        "</listOfProducts>\n      <kineticLaw>",
        "</listOfProducts><listOfModifiers>"
        '<modifierSpeciesReference species="Aany"/></listOfModifiers>\n      <kineticLaw>',
    )
    .replace(
        'multi:representationType="sum">Au</ci>',
        'multi:representationType="sum">Aany</ci>',
    )
)
CORE_WILDCARD_SUM_ORACLE = CORE_ORACLE.replace(
    "<apply><times/><ci>k</ci><ci>Au</ci></apply>",
    "<apply><times/><apply><plus/><ci>Au</ci><ci>Ap</ci></apply><ci>Au</ci></apply>",
)

# SpeciesFeature.occur is a count, not an occurrence ordinal.  The two
# feature records each describe one instance, as in Multi §3.18.3's example.
# The valid states are {u,p} -> {p,p}; the Core oracle is k*Au.
MULTI_REPEATED_FEATURE_SOURCE = MULTI_SOURCE.replace(
    "</multi:speciesFeature></multi:listOfSpeciesFeatures>",
    """</multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="state_p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature></multi:listOfSpeciesFeatures>""",
).replace('multi:name="x" multi:occur="1"', 'multi:name="x" multi:occur="2"')

# The same two site constraints can be written as an explicit Multi
# conjunction.  This is a separate valid packaging of the feature semantics.
MULTI_CONJUNCTION_SOURCE = MULTI_REPEATED_FEATURE_SOURCE.replace(
    "<multi:listOfSpeciesFeatures>",
    '<multi:listOfSpeciesFeatures><multi:subListOfSpeciesFeatures multi:relation="and">',
).replace(
    "</multi:listOfSpeciesFeatures>",
    "</multi:subListOfSpeciesFeatures></multi:listOfSpeciesFeatures>",
)


@pytest.mark.parametrize("atomize", [False, True])
@pytest.mark.parametrize(
    "mode, multi_source, core_oracle",
    [
        ("numericValue", MULTI_SOURCE, CORE_ORACLE),
        ("sum", MULTI_SUM_SOURCE, CORE_SUM_ORACLE),
        ("wildcard_sum", MULTI_WILDCARD_SUM_SOURCE, CORE_WILDCARD_SUM_ORACLE),
        ("repeated_feature", MULTI_REPEATED_FEATURE_SOURCE, CORE_ORACLE),
        ("conjunction", MULTI_CONJUNCTION_SOURCE, CORE_ORACLE),
    ],
)
def test_multi_math_representation_preserves_core_dynamics(
    atomize, mode, multi_source, core_oracle
):
    for source in (multi_source, core_oracle):
        document = libsbml.readSBMLFromString(source)
        assert document.getNumErrors() == 0, document.getErrorLog().toString()
        document.checkConsistency()
        consistency_errors = [
            document.getError(index).getErrorId()
            for index in range(document.getNumErrors())
            if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
        ]
        # libSBML's Core-only MathML identifier check reports 10215 for the
        # Multi §3.26.2 numericValue form: its ci text is a
        # PossibleSpeciesFeatureValue id, and Multi explicitly requires
        # speciesReference for that form. Preserve that single known Core /
        # package-boundary diagnostic; all other package and Core consistency
        # errors remain failures.
        expected_errors = (
            [10215]
            if source == multi_source
            and mode
            in {
                "numericValue",
                "repeated_feature",
                "conjunction",
            }
            else []
        )
        assert consistency_errors == expected_errors, document.getErrorLog().toString()

    parsed = SBMLParser().parse(multi_source)
    assert parsed.multi_executable
    assert parsed.multi_numeric_values["state_u"] == "k"
    assert ('representationType="sum"' in multi_source) == (
        mode in {"sum", "wildcard_sum"}
    )
    atomized = Atomizer(atomize=atomize, quiet_mode=True).atomize(multi_source)
    assert atomized.success, atomized.error
    if mode in {"repeated_feature", "conjunction"}:
        assert "M_A(x_1~u,x_2~p)" in atomized.bngl
        assert "M_A(x_1~p,x_2~p)" in atomized.bngl
    if mode == "wildcard_sum":
        assert "Molecules __multi_sum_Aany M_A(x)@cell" in atomized.bngl
    native = cpp.parse_string(atomized.bngl)
    result = BioNetGenModel(native).simulate(method="ode", t_end=4, n_steps=40)

    oracle = roadrunner.RoadRunner(core_oracle)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(times=result.time, selections=["time", "Au", "Ap"])
    for column, species in enumerate(("Au", "Ap"), start=1):
        actual = result.observables[atomized.observable_map[species]]
        np.testing.assert_allclose(actual, expected[:, column], rtol=1e-6, atol=1e-8)
