"""Execution checks for fully explicit SBML Multi feature value domains."""

from __future__ import annotations

import numpy as np
import pytest

from bionetgen.atomizer.modern import parse_multi_package

MULTI_FULL_DOMAIN = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
  xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
  level="3" version="1" multi:required="true">
  <model id="full_domain_feature_or">
    <listOfCompartments>
      <compartment id="cell" size="0.5" spatialDimensions="3"
        constant="true" multi:isType="false"/>
    </listOfCompartments>
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
      <species id="Aq" compartment="cell" initialAmount="2"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
        multi:speciesType="AType">
        <multi:listOfSpeciesFeatures><multi:speciesFeature
          multi:speciesFeatureType="state" multi:occur="1">
          <multi:listOfSpeciesFeatureValues>
            <multi:speciesFeatureValue multi:value="state_q"/>
          </multi:listOfSpeciesFeatureValues>
        </multi:speciesFeature></multi:listOfSpeciesFeatures>
      </species>
      <species id="Aany" compartment="cell" initialAmount="0"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
        multi:speciesType="AType">
        <multi:listOfSpeciesFeatures><multi:speciesFeature
          multi:speciesFeatureType="state" multi:occur="1">
          <multi:listOfSpeciesFeatureValues>
            <multi:speciesFeatureValue multi:value="state_u"/>
            <multi:speciesFeatureValue multi:value="state_p"/>
            <multi:speciesFeatureValue multi:value="state_q"/>
          </multi:listOfSpeciesFeatureValues>
        </multi:speciesFeature></multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.3" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="activate" reversible="false" fast="false">
        <listOfReactants><speciesReference id="source_ref" species="Au"
          stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference id="target_ref" species="Ap"
          stoichiometry="1" constant="true"/></listOfProducts>
        <listOfModifiers><modifierSpeciesReference species="Aany"/></listOfModifiers>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci>
            <ci multi:representationType="sum">Aany</ci>
            <ci>Au</ci>
          </apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="M_A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:name="x" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="state_u" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="state_p" multi:name="p"/>
              <multi:possibleSpeciesFeatureValue multi:id="state_q" multi:name="q"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""


CORE_ORACLE = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
  level="3" version="1">
  <model id="explicit_core_sum">
    <listOfCompartments>
      <compartment id="cell" size="0.5" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="10"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Ap" compartment="cell" initialAmount="0"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Aq" compartment="cell" initialAmount="2"
        hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.3" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="activate" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Au" stoichiometry="1"
          constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Ap" stoichiometry="1"
          constant="true"/></listOfProducts>
        <listOfModifiers><modifierSpeciesReference species="Aq"/></listOfModifiers>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci>
            <apply><plus/><ci>Au</ci><ci>Ap</ci><ci>Aq</ci></apply>
            <ci>Au</ci>
          </apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

# This Core model is authored independently of the Multi source. Its rate law
# writes the three-state sum directly, so it does not reuse candidate output.


def _validate_sbml(xml: str, libsbml) -> None:
    document = libsbml.readSBMLFromString(xml)
    assert document.getNumErrors() == 0, document.getErrorLog().toString()
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert errors == []


def _partial_domain_source() -> str:
    return MULTI_FULL_DOMAIN.replace(
        '<multi:speciesFeatureValue multi:value="state_p"/>\n'
        '            <multi:speciesFeatureValue multi:value="state_q"/>',
        '<multi:speciesFeatureValue multi:value="state_p"/>',
        1,
    )


def test_atomizer_multi_explicit_full_value_domain_is_a_wildcard():
    result = parse_multi_package(MULTI_FULL_DOMAIN)

    assert result.executable is True
    pattern = result.species_patterns["Aany"]
    assert pattern == "M_A(x)@cell"

    partial = parse_multi_package(_partial_domain_source())
    assert partial.executable is False
    assert any(
        warning.severity == "dropped" and "multiple values" in warning.message
        for warning in partial.warnings
    )


def test_atomizer_multi_full_domain_matches_core_oracle_through_sbml_export(
    tmp_path,
):
    libsbml = pytest.importorskip("libsbml", exc_type=ImportError)
    roadrunner = pytest.importorskip("roadrunner", exc_type=ImportError)
    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
    from bionetgen.atomizer.modern import Atomizer

    _validate_sbml(MULTI_FULL_DOMAIN, libsbml)
    _validate_sbml(CORE_ORACLE, libsbml)
    _validate_sbml(_partial_domain_source(), libsbml)

    imported = Atomizer(atomize=False, quiet_mode=True).atomize(MULTI_FULL_DOMAIN)
    assert imported.success, imported.error
    assert "Molecules __multi_sum_Aany M_A(x)@cell" in imported.bngl

    native = BioNetGenModel(cpp.parse_string(imported.bngl))
    actual = native.simulate(method="ode", t_end=4, n_steps=40)
    oracle = roadrunner.RoadRunner(CORE_ORACLE)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(times=actual.time, selections=["time", "Au", "Ap", "Aq"])

    def assert_matches_core(result, observable_map):
        for column, species in enumerate(("Au", "Ap", "Aq"), start=1):
            np.testing.assert_allclose(
                result.observables[observable_map[species]],
                expected[:, column],
                rtol=1e-6,
                atol=1e-8,
            )

    assert_matches_core(actual, imported.observable_map)

    exported_path = tmp_path / "full_domain_roundtrip.xml"
    native.write_sbml(str(exported_path))
    exported = exported_path.read_text(encoding="utf-8")
    _validate_sbml(exported, libsbml)

    reimported = Atomizer(atomize=False, quiet_mode=True).atomize(exported)
    assert reimported.success, reimported.error
    replay = BioNetGenModel(cpp.parse_string(reimported.bngl)).simulate(
        method="ode", t_end=4, n_steps=40
    )
    exported_model = libsbml.readSBMLFromString(exported).getModel()
    species_ids_by_name = {
        species.getName(): species.getId()
        for species in (
            exported_model.getSpecies(index)
            for index in range(exported_model.getNumSpecies())
        )
    }
    exported_species = {
        "Au": "M_A(x~u)",
        "Ap": "M_A(x~p)",
        "Aq": "M_A(x~q)",
    }
    assert all(pattern in species_ids_by_name for pattern in exported_species.values())
    roundtrip_observable_map = {
        source_id: reimported.observable_map[species_ids_by_name[pattern]]
        for source_id, pattern in exported_species.items()
    }
    assert_matches_core(replay, roundtrip_observable_map)
