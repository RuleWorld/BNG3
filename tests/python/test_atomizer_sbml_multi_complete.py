"""End-to-end semantic verification of complete SBML Level 3 Multi v1 BNGL lowering.

Every newly lowered construct is validated for SBML consistency with libSBML,
atomized to BNGL, simulated in BNG3's native C++ CVODE engine, and checked
against an independently authored Core SBML model simulated in libRoadRunner
(and/or closed-form analytical ODEs). Truly spec-invalid or mathematically
under-specified Multi constructs are verified to fail closed.
"""

from __future__ import annotations

import numpy as np
import pytest

from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer, parse_multi_package

MULTI_NS = "http://www.sbml.org/sbml/level3/version1/multi/version1"


def _validate_sbml(xml: str, libsbml) -> None:
    doc = libsbml.readSBMLFromString(xml)
    assert doc.getNumErrors() == 0, doc.getErrorLog().toString()
    doc.checkConsistency()
    errors = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert errors == [], errors


def _compare_with_core_oracle(
    multi_xml: str,
    core_xml: str,
    species_names: list[str],
    *,
    t_end: float = 4.0,
    n_steps: int = 40,
    rtol: float = 1e-6,
    atol: float = 1e-8,
    validate_multi: bool = True,
):
    libsbml = pytest.importorskip("libsbml", exc_type=ImportError)
    roadrunner = pytest.importorskip("roadrunner", exc_type=ImportError)

    if validate_multi:
        _validate_sbml(multi_xml, libsbml)
    _validate_sbml(core_xml, libsbml)

    imported = Atomizer(atomize=False, quiet_mode=True).atomize(multi_xml)
    assert imported.success, imported.error

    native = BioNetGenModel(cpp.parse_string(imported.bngl))
    actual = native.simulate(method="ode", t_end=t_end, n_steps=n_steps)

    oracle = roadrunner.RoadRunner(core_xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(times=actual.time, selections=["time", *species_names])

    for col, sp_id in enumerate(species_names, start=1):
        obs_name = imported.observable_map[sp_id]
        np.testing.assert_allclose(
            actual.observables[obs_name],
            expected[:, col],
            rtol=rtol,
            atol=atol,
            err_msg=f"Mismatch on species {sp_id} (obs {obs_name})\nBNGL:\n{imported.bngl}",
        )
    return imported, actual


# ---------------------------------------------------------------------------
# (1) >2-level nested speciesType hierarchies
# ---------------------------------------------------------------------------


def test_multi_three_level_nested_species_type_hierarchy_matches_core_oracle():
    """3-level hierarchy: SuperComplex -> (SubAB, SubCD) -> (A, B, C, D) -> sites,
    with intra-subcomplex bonds, cross-subcomplex bond, chained componentIndexes,
    and molecule-group componentMapInProduct."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="three_level_hierarchy">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="SubAB_u" compartment="cell" initialAmount="12"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SubABType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="stA" multi:component="mA" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="stA_u"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="subAB_out" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="SubAB_p" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SubABType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="stA" multi:component="mA" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="stA_p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="subAB_out" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="SubCD_free" compartment="cell" initialAmount="8"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SubCDType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="subCD_in" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="Super_any" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SuperType"/>
      <species id="Super_u" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SuperType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="stA" multi:component="sup_mA" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="stA_u"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Super_p" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SuperType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="stA" multi:component="sup_mA" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="stA_p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="SubAB_any" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="SubABType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="subAB_out" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_phos" value="0.4" constant="true"/>
      <parameter id="k_bind" value="0.05" constant="true"/>
      <parameter id="k_unbind" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="phos_free" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r_pf" species="SubAB_u" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference id="p_pf" species="SubAB_p" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_phos</ci><ci>SubAB_u</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="bind_super" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference id="r_ab" species="SubAB_any" stoichiometry="1" constant="true"/>
          <speciesReference id="r_cd" species="SubCD_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference id="p_sup" species="Super_any" stoichiometry="1" constant="true">
            <multi:listOfSpeciesTypeComponentMapsInProduct>
              <multi:speciesTypeComponentMapInProduct multi:reactant="r_ab"
                multi:reactantComponent="SubABType" multi:productComponent="sub1"/>
              <multi:speciesTypeComponentMapInProduct multi:reactant="r_cd"
                multi:reactantComponent="SubCDType" multi:productComponent="sub2"/>
            </multi:listOfSpeciesTypeComponentMapsInProduct>
          </speciesReference>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_bind</ci><ci>SubAB_any</ci><ci>SubCD_free</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="unbind_p" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r_ub" species="Super_p" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference id="p_ab" species="SubAB_p" stoichiometry="1" constant="true"/>
          <speciesReference id="p_cd" species="SubCD_free" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_unbind</ci><ci>Super_p</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="bA" multi:name="s1"/>
      <multi:bindingSiteSpeciesType multi:id="bB1" multi:name="s2"/>
      <multi:bindingSiteSpeciesType multi:id="bB2" multi:name="s3"/>
      <multi:bindingSiteSpeciesType multi:id="bC1" multi:name="s4"/>
      <multi:bindingSiteSpeciesType multi:id="bC2" multi:name="s5"/>
      <multi:bindingSiteSpeciesType multi:id="bD" multi:name="s6"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="stA" multi:name="p" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="stA_u" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="stA_p" multi:name="p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a_s1" multi:speciesType="bA"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="BType" multi:name="B" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="b_s2" multi:speciesType="bB1"/>
          <multi:speciesTypeInstance multi:id="b_s3" multi:speciesType="bB2"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="CType" multi:name="C" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="c_s4" multi:speciesType="bC1"/>
          <multi:speciesTypeInstance multi:id="c_s5" multi:speciesType="bC2"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="DType" multi:name="D" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="d_s6" multi:speciesType="bD"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="SubABType" multi:name="SubAB" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="mA" multi:speciesType="AType"/>
          <multi:speciesTypeInstance multi:id="mB" multi:speciesType="BType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="ab_s1" multi:component="a_s1" multi:identifyingParent="mA"/>
          <multi:speciesTypeComponentIndex multi:id="ab_s2" multi:component="b_s2" multi:identifyingParent="mB"/>
          <multi:speciesTypeComponentIndex multi:id="subAB_out" multi:component="b_s3" multi:identifyingParent="mB"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="ab_s1" multi:bindingSite2="ab_s2"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
      <multi:speciesType multi:id="SubCDType" multi:name="SubCD" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="mC" multi:speciesType="CType"/>
          <multi:speciesTypeInstance multi:id="mD" multi:speciesType="DType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="subCD_in" multi:component="c_s4" multi:identifyingParent="mC"/>
          <multi:speciesTypeComponentIndex multi:id="cd_s5" multi:component="c_s5" multi:identifyingParent="mC"/>
          <multi:speciesTypeComponentIndex multi:id="cd_s6" multi:component="d_s6" multi:identifyingParent="mD"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="cd_s5" multi:bindingSite2="cd_s6"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
      <multi:speciesType multi:id="SuperType" multi:name="Super" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="sub1" multi:speciesType="SubABType"/>
          <multi:speciesTypeInstance multi:id="sub2" multi:speciesType="SubCDType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="sup_mA" multi:component="mA" multi:identifyingParent="sub1"/>
          <multi:speciesTypeComponentIndex multi:id="sup_out" multi:component="subAB_out" multi:identifyingParent="sub1"/>
          <multi:speciesTypeComponentIndex multi:id="sup_in" multi:component="subCD_in" multi:identifyingParent="sub2"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="sup_out" multi:bindingSite2="sup_in"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="three_level_oracle">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="SubAB_u" compartment="cell" initialAmount="12" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="SubAB_p" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="SubCD_free" compartment="cell" initialAmount="8" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Super_u" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Super_p" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_phos" value="0.4" constant="true"/>
      <parameter id="k_bind" value="0.05" constant="true"/>
      <parameter id="k_unbind" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="SubAB_u" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="SubAB_p" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_phos</ci><ci>SubAB_u</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="r2u" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="SubAB_u" stoichiometry="1" constant="true"/>
          <speciesReference species="SubCD_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="Super_u" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_bind</ci><ci>SubAB_u</ci><ci>SubCD_free</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="r2p" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="SubAB_p" stoichiometry="1" constant="true"/>
          <speciesReference species="SubCD_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="Super_p" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_bind</ci><ci>SubAB_p</ci><ci>SubCD_free</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="r3" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Super_p" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="SubAB_p" stoichiometry="1" constant="true"/>
          <speciesReference species="SubCD_free" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_unbind</ci><ci>Super_p</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    parsed = parse_multi_package(multi_xml)
    assert parsed.deep is True
    assert parsed.executable is True
    _compare_with_core_oracle(
        multi_xml,
        core_xml,
        ["SubAB_u", "SubAB_p", "SubCD_free", "Super_u", "Super_p"],
    )


def test_multi_cyclic_species_type_hierarchy_still_fails_closed():
    cyclic_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="cyclic">
    <listOfSpecies><species id="s0" multi:speciesType="T1"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="T1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="i2" multi:speciesType="T2"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="T2">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="i1" multi:speciesType="T1"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""
    result = parse_multi_package(cyclic_xml)
    assert result.executable is False
    assert any("cycle" in w.message for w in result.warnings)


# ---------------------------------------------------------------------------
# (2) Composite speciesTypes with direct features and direct binding sites
# ---------------------------------------------------------------------------


def test_multi_composite_with_direct_features_and_binding_site_matches_core_oracle():
    """Composite ABType owns direct speciesFeatureType (allostery) AND direct
    bindingSiteSpeciesType (ext), participates in assembly A+B->AB, allosteric
    transition, external binding AB+C->ABC, and disassembly AB->A+B."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="composite_direct_feat_and_site">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A_free" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="sa" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="B_free" compartment="cell" initialAmount="9" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="BType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="sb" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="C_free" compartment="cell" initialAmount="6" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="CType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="sc" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="AB_tense" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="ABType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="allo" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="tense"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="ext" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="AB_relaxed" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="ABType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="allo" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="relaxed"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="ext" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="ABC_bound" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="ABCType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="allo" multi:component="ab_inst" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="relaxed"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_form" value="0.06" constant="true"/>
      <parameter id="k_diss" value="0.15" constant="true"/>
      <parameter id="k_relax" value="0.5" constant="true"/>
      <parameter id="k_bind_c" value="0.08" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="assemble" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A_free" stoichiometry="1" constant="true"/>
          <speciesReference species="B_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="AB_tense" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_form</ci><ci>A_free</ci><ci>B_free</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="disassemble" reversible="false" fast="false">
        <listOfReactants><speciesReference species="AB_tense" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="A_free" stoichiometry="1" constant="true"/>
          <speciesReference species="B_free" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_diss</ci><ci>AB_tense</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="relax" reversible="false" fast="false">
        <listOfReactants><speciesReference species="AB_tense" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="AB_relaxed" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_relax</ci><ci>AB_tense</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="bind_c" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="AB_relaxed" stoichiometry="1" constant="true"/>
          <speciesReference species="C_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="ABC_bound" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_bind_c</ci><ci>AB_relaxed</ci><ci>C_free</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="bA" multi:name="sa"/>
      <multi:bindingSiteSpeciesType multi:id="bB" multi:name="sb"/>
      <multi:bindingSiteSpeciesType multi:id="bExt" multi:name="ext"/>
      <multi:bindingSiteSpeciesType multi:id="bC" multi:name="sc"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="sa" multi:speciesType="bA"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="BType" multi:name="B" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="sb" multi:speciesType="bB"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="CType" multi:name="C" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="sc" multi:speciesType="bC"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="ABType" multi:name="AB" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="allo" multi:name="allo" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="tense" multi:name="T"/>
              <multi:possibleSpeciesFeatureValue multi:id="relaxed" multi:name="R"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a_i" multi:speciesType="AType"/>
          <multi:speciesTypeInstance multi:id="b_i" multi:speciesType="BType"/>
          <multi:speciesTypeInstance multi:id="ext" multi:speciesType="bExt"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="ab_sa" multi:component="sa" multi:identifyingParent="a_i"/>
          <multi:speciesTypeComponentIndex multi:id="ab_sb" multi:component="sb" multi:identifyingParent="b_i"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="ab_sa" multi:bindingSite2="ab_sb"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
      <multi:speciesType multi:id="ABCType" multi:name="ABC" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="ab_inst" multi:speciesType="ABType"/>
          <multi:speciesTypeInstance multi:id="c_inst" multi:speciesType="CType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="abc_ext" multi:component="ext" multi:identifyingParent="ab_inst"/>
          <multi:speciesTypeComponentIndex multi:id="abc_sc" multi:component="sc" multi:identifyingParent="c_inst"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="abc_ext" multi:bindingSite2="abc_sc"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="composite_oracle">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A_free" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B_free" compartment="cell" initialAmount="9" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="C_free" compartment="cell" initialAmount="6" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="AB_tense" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="AB_relaxed" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="ABC_bound" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_form" value="0.06" constant="true"/>
      <parameter id="k_diss" value="0.15" constant="true"/>
      <parameter id="k_relax" value="0.5" constant="true"/>
      <parameter id="k_bind_c" value="0.08" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="assemble" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A_free" stoichiometry="1" constant="true"/>
          <speciesReference species="B_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="AB_tense" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_form</ci><ci>A_free</ci><ci>B_free</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="disassemble" reversible="false" fast="false">
        <listOfReactants><speciesReference species="AB_tense" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="A_free" stoichiometry="1" constant="true"/>
          <speciesReference species="B_free" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_diss</ci><ci>AB_tense</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="relax" reversible="false" fast="false">
        <listOfReactants><speciesReference species="AB_tense" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="AB_relaxed" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_relax</ci><ci>AB_tense</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="bind_c" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="AB_relaxed" stoichiometry="1" constant="true"/>
          <speciesReference species="C_free" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="ABC_bound" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_bind_c</ci><ci>AB_relaxed</ci><ci>C_free</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    _compare_with_core_oracle(
        multi_xml,
        core_xml,
        ["A_free", "B_free", "C_free", "AB_tense", "AB_relaxed", "ABC_bound"],
    )


# ---------------------------------------------------------------------------
# (3) bindingSiteSpeciesType with >1 feature types & occur > 1
# ---------------------------------------------------------------------------


def test_multi_binding_site_multiple_features_and_component_map_matches_core_oracle():
    """bindingSiteSpeciesType with 2 independent speciesFeatureTypes (phos, methyl):
    phosphorylation rule preserves methyl via componentMap on the binding site."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="bs_multi_feat">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A_u_m0" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="meth" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="m0"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_u_m1" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="meth" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="m1"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_p_m0" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="meth" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="m0"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_p_m1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="meth" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="m1"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_u_any" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_p_any" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.35" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="phos_rxn" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r1" species="A_u_any" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference id="p1" species="A_p_any" stoichiometry="1" constant="true">
            <multi:listOfSpeciesTypeComponentMapsInProduct>
              <multi:speciesTypeComponentMapInProduct multi:reactant="r1"
                multi:reactantComponent="site" multi:productComponent="site"/>
            </multi:listOfSpeciesTypeComponentMapsInProduct>
          </speciesReference>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_u_any</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="phos" multi:name="p" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="pu" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="pp" multi:name="p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="meth" multi:name="m" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="m0" multi:name="0"/>
              <multi:possibleSpeciesFeatureValue multi:id="m1" multi:name="1"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:bindingSiteSpeciesType>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="bs_multi_feat_oracle">
    <listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A_u_m0" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_u_m1" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_p_m0" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_p_m1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.35" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="r0" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_u_m0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_p_m0" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_u_m0</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_u_m1" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_p_m1" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_u_m1</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    _compare_with_core_oracle(
        multi_xml, core_xml, ["A_u_m0", "A_u_m1", "A_p_m0", "A_p_m1"]
    )


def test_multi_binding_site_occur_gt_1_preserves_multiset_symmetry_and_stat_factors():
    """bindingSiteSpeciesType with occur=2 on phos~u~p:
    pattern A(site__p~u) -> A(site__p~p) fires with factor 2 on (u,u) and 1 on (u,p)."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="bs_occur2">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A_uu" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="2">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_up" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_pp" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="2">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_has_u" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_has_p" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.4" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="phos1" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r1" species="A_has_u" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference id="p1" species="A_has_p" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_has_u</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="phos" multi:name="p" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="pu" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="pp" multi:name="p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:bindingSiteSpeciesType>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="bs_occur2_oracle">
    <listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A_uu" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_up" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_pp" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.4" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="step1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_uu" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_up" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>2</cn><ci>k</ci><ci>A_uu</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="step2" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_up" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_pp" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_up</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    _compare_with_core_oracle(multi_xml, core_xml, ["A_uu", "A_up", "A_pp"])


# ---------------------------------------------------------------------------
# (4) Proper-subset multi-value speciesFeatures & subListOfSpeciesFeatures (or, not)
# ---------------------------------------------------------------------------


def test_multi_proper_subset_dnf_reactant_and_sum_modifier_matches_core_oracle():
    """Proper-subset {u, p} out of {u, p, q} used simultaneously as:
    - reactant in A_up -> Aq with rate k * sum(A_up) * A_up
    - homodimerization 2 A_up -> D with rate k2 * A_up * A_up (multinomial test!)"""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="proper_subset_dnf">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="7" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="st" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="vu"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Ap" compartment="cell" initialAmount="3" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="st" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="vp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Aq" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="st" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="vq"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_up" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="st" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="vu"/>
              <multi:speciesFeatureValue multi:value="vp"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="D" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="DType"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.05" constant="true"/>
      <parameter id="k2" value="0.02" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="to_q" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_up" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Aq" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci>
            <ci multi:representationType="sum">A_up</ci>
            <ci>A_up</ci>
          </apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="dimerize" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_up" stoichiometry="2" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="D" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k2</ci><ci>A_up</ci><ci>A_up</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="st" multi:name="x" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="vu" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="vp" multi:name="p"/>
              <multi:possibleSpeciesFeatureValue multi:id="vq" multi:name="q"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
      <multi:speciesType multi:id="DType" multi:name="D" multi:compartment="cell"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="proper_subset_oracle">
    <listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="7" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Ap" compartment="cell" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Aq" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="D" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.05" constant="true"/>
      <parameter id="k2" value="0.02" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="to_q_u" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Au" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Aq" stoichiometry="1" constant="true"/></listOfProducts>
        <listOfModifiers><modifierSpeciesReference species="Ap"/></listOfModifiers>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci><apply><plus/><ci>Au</ci><ci>Ap</ci></apply><ci>Au</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="to_q_p" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Ap" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Aq" stoichiometry="1" constant="true"/></listOfProducts>
        <listOfModifiers><modifierSpeciesReference species="Au"/></listOfModifiers>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci><apply><plus/><ci>Au</ci><ci>Ap</ci></apply><ci>Ap</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="dim_uu" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Au" stoichiometry="2" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="D" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k2</ci><ci>Au</ci><ci>Au</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="dim_pp" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Ap" stoichiometry="2" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="D" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k2</ci><ci>Ap</ci><ci>Ap</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="dim_up" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="Au" stoichiometry="1" constant="true"/>
          <speciesReference species="Ap" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="D" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>2</cn><ci>k2</ci><ci>Au</ci><ci>Ap</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    imported, actual = _compare_with_core_oracle(
        multi_xml, core_xml, ["Au", "Ap", "Aq", "D"]
    )
    # Also verify A_up observable equals Au + Ap with zero double counting!
    np.testing.assert_allclose(
        actual.observables[imported.observable_map["A_up"]],
        actual.observables[imported.observable_map["Au"]]
        + actual.observables[imported.observable_map["Ap"]],
        rtol=1e-9,
        atol=1e-12,
    )


@pytest.mark.parametrize("relation", ["or", "not"])
def test_multi_sublist_or_and_not_relations_match_core_oracle(relation: str):
    """Verify exact orthogonal DNF execution for BOTH relation='or' (a=on OR b=on)
    and relation='not' (NOT(a=on AND b=on)) with zero double counting."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="sublist_{relation}">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A00" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fa" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_off"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fb" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="b_off"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A01" compartment="cell" initialAmount="4" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fa" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_off"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fb" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="b_on"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A10" compartment="cell" initialAmount="3" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fa" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_on"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fb" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="b_off"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A11" compartment="cell" initialAmount="6" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fa" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_on"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fb" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="b_on"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_pat" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:subListOfSpeciesFeatures multi:relation="{relation}">
            <multi:speciesFeature multi:speciesFeatureType="fa" multi:occur="1">
              <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_on"/></multi:listOfSpeciesFeatureValues>
            </multi:speciesFeature>
            <multi:speciesFeature multi:speciesFeatureType="fb" multi:occur="1">
              <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="b_on"/></multi:listOfSpeciesFeatureValues>
            </multi:speciesFeature>
          </multi:subListOfSpeciesFeatures>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Sink" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="SinkType"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.3" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="consume_pat" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_pat" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Sink" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_pat</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="fa" multi:name="a" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="a_off" multi:name="off"/>
              <multi:possibleSpeciesFeatureValue multi:id="a_on" multi:name="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="fb" multi:name="b" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="b_off" multi:name="off"/>
              <multi:possibleSpeciesFeatureValue multi:id="b_on" multi:name="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
      <multi:speciesType multi:id="SinkType" multi:name="Sink" multi:compartment="cell"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    active_states = ["A01", "A10", "A11"] if relation == "or" else ["A00", "A01", "A10"]
    rxn_xml = "\n".join(f"""      <reaction id="r_{sp}" reversible="false" fast="false">
        <listOfReactants><speciesReference species="{sp}" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Sink" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>{sp}</ci></apply>
        </math></kineticLaw>
      </reaction>""" for sp in active_states)
    core_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="sublist_{relation}_oracle">
    <listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A00" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A01" compartment="cell" initialAmount="4" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A10" compartment="cell" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A11" compartment="cell" initialAmount="6" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Sink" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.3" constant="true"/></listOfParameters>
    <listOfReactions>{rxn_xml}</listOfReactions>
  </model>
</sbml>"""

    imported, actual = _compare_with_core_oracle(
        multi_xml, core_xml, ["A00", "A01", "A10", "A11", "Sink"]
    )
    expected_pat = sum(
        actual.observables[imported.observable_map[s]] for s in active_states
    )
    np.testing.assert_allclose(
        actual.observables[imported.observable_map["A_pat"]],
        expected_pat,
        rtol=1e-9,
        atol=1e-12,
    )


def test_multi_disjunctive_reactant_and_matching_disjunctive_product_preserves_state():
    """A(x in {u, p}, y~0) -> A(x in {u, p}, y~1) preserves x per branch."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="disjunctive_pair">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A_u0" compartment="cell" initialAmount="8" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="xu"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y0"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_p0" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="xp"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y0"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_q0" compartment="cell" initialAmount="4" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="xq"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y0"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_u1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="xu"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y1"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_p1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="xp"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y1"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_up0" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues>
            <multi:speciesFeatureValue multi:value="xu"/><multi:speciesFeatureValue multi:value="xp"/>
          </multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y0"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_up1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="fx" multi:occur="1"><multi:listOfSpeciesFeatureValues>
            <multi:speciesFeatureValue multi:value="xu"/><multi:speciesFeatureValue multi:value="xp"/>
          </multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="fy" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="y1"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.5" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="flip_y" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_up0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_up1" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>A_up0</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="fx" multi:name="x" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="xu" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="xp" multi:name="p"/>
              <multi:possibleSpeciesFeatureValue multi:id="xq" multi:name="q"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="fy" multi:name="y" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="y0" multi:name="0"/>
              <multi:possibleSpeciesFeatureValue multi:id="y1" multi:name="1"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="disjunctive_pair_oracle">
    <listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A_u0" compartment="cell" initialAmount="8" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_p0" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_q0" compartment="cell" initialAmount="4" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_u1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_p1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.5" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="r_u" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_u0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_u1" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A_u0</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="r_p" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_p0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_p1" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A_p0</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    _compare_with_core_oracle(
        multi_xml, core_xml, ["A_u0", "A_p0", "A_q0", "A_u1", "A_p1"]
    )


# ---------------------------------------------------------------------------
# (5) Multi-level nested compartmentReference hierarchies
# ---------------------------------------------------------------------------


def test_multi_three_level_compartment_reference_hierarchy_specializes_and_executes():
    """3-level compartmentType tree ct_ec (3D) -> ct_pm (2D) -> ct_cyto (3D)
    uniquely specialized to ec1 -> pm1 -> cyto1, plus ambiguous 2nd-level refusal."""

    def make_xml(extra_cyto_ref: str = "") -> str:
        return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="three_level_compartments">
    <listOfCompartments>
      <compartment id="ct_ec" spatialDimensions="3" constant="true" multi:isType="true">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="ref_pm" multi:compartment="ct_pm"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="ct_pm" spatialDimensions="2" constant="true" multi:isType="true">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="ref_cyto" multi:compartment="ct_cyto"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="ct_cyto" spatialDimensions="3" constant="true" multi:isType="true"/>
      <compartment id="ec1" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct_ec">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="ref_pm1" multi:compartment="pm1"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="pm1" size="1" spatialDimensions="2" constant="true" multi:isType="false" multi:compartmentType="ct_pm">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="ref_cyto1" multi:compartment="cyto1"/>
          {extra_cyto_ref}
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="cyto1" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct_cyto"/>
      <compartment id="cyto2" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct_cyto"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="LRA_u" compartment="ec1" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="LRAType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="act" multi:component="adp" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_off"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="LRA_a" compartment="ec1" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="LRAType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="act" multi:component="adp" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a_on"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.4" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="signal" reversible="false" fast="false">
        <listOfReactants><speciesReference species="LRA_u" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="LRA_a" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>LRA_u</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="bL" multi:name="l" multi:compartment="ct_ec"/>
      <multi:bindingSiteSpeciesType multi:id="bR1" multi:name="r1" multi:compartment="ct_pm"/>
      <multi:bindingSiteSpeciesType multi:id="bR2" multi:name="r2" multi:compartment="ct_pm"/>
      <multi:bindingSiteSpeciesType multi:id="bA" multi:name="a" multi:compartment="ct_cyto"/>
      <multi:speciesType multi:id="LType" multi:name="L" multi:compartment="ct_ec">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="ls" multi:speciesType="bL"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="RType" multi:name="R" multi:compartment="ct_pm">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="rs1" multi:speciesType="bR1"/>
          <multi:speciesTypeInstance multi:id="rs2" multi:speciesType="bR2"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="AdpType" multi:name="Adp" multi:compartment="ct_cyto">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="act" multi:name="act" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="a_off" multi:name="off"/>
              <multi:possibleSpeciesFeatureValue multi:id="a_on" multi:name="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="as" multi:speciesType="bA"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="RAType" multi:name="RA" multi:compartment="ct_pm">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="rec" multi:speciesType="RType"/>
          <multi:speciesTypeInstance multi:id="adp" multi:speciesType="AdpType" multi:compartmentReference="ref_cyto"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="ra_r1" multi:component="rs1" multi:identifyingParent="rec"/>
          <multi:speciesTypeComponentIndex multi:id="ra_r2" multi:component="rs2" multi:identifyingParent="rec"/>
          <multi:speciesTypeComponentIndex multi:id="ra_a" multi:component="as" multi:identifyingParent="adp"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="ra_r2" multi:bindingSite2="ra_a"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
      <multi:speciesType multi:id="LRAType" multi:name="LRA" multi:compartment="ct_ec">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="lig" multi:speciesType="LType"/>
          <multi:speciesTypeInstance multi:id="ra" multi:speciesType="RAType" multi:compartmentReference="ref_pm"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="lra_l" multi:component="ls" multi:identifyingParent="lig"/>
          <multi:speciesTypeComponentIndex multi:id="lra_r1" multi:component="ra_r1" multi:identifyingParent="ra"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="lra_l" multi:bindingSite2="lra_r1"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    unique_xml = make_xml()
    parsed = parse_multi_package(unique_xml)
    assert parsed.executable is True
    assert (
        parsed.species_patterns["LRA_u"]
        == "L(l!2)@ec1.R(r1!2,r2!1)@pm1.Adp(act~off,a!1)@cyto1"
    )

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="three_level_comp_oracle">
    <listOfCompartments><compartment id="ec1" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="LRA_u" compartment="ec1" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="LRA_a" compartment="ec1" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.4" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="signal" reversible="false" fast="false">
        <listOfReactants><speciesReference species="LRA_u" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="LRA_a" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>LRA_u</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    _compare_with_core_oracle(unique_xml, core_xml, ["LRA_u", "LRA_a"])

    # Ambiguous 2nd-level compartmentType specialization must still fail closed!
    ambiguous = parse_multi_package(
        make_xml(
            '<multi:compartmentReference multi:id="ref_cyto2" multi:compartment="cyto2"/>'
        )
    )
    assert ambiguous.executable is False
    assert any(
        "cannot unambiguously specialize nested compartmentType" in w.message
        for w in ambiguous.warnings
    )


# ---------------------------------------------------------------------------
# (6) MathML multi:speciesReference sub-compartment & feature-count rate laws
# ---------------------------------------------------------------------------


def test_multi_mathml_subcompartment_species_reference_rate_matches_core_oracle():
    """Transport A@c1 -> A@c2 with feedback kinetic law referencing
    <ci multi:speciesReference="p1">A0</ci> (the c2 pool!)."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="subcomp_sref_rate">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="to_c2" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A0" compartment="c1" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType"/>
      <species id="A_c2" compartment="c2" initialAmount="2" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_in" value="0.5" constant="true"/>
      <parameter id="k_back" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="move_in" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r1" species="A0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference id="p1" species="A0" stoichiometry="1" constant="true" multi:compartmentReference="to_c2"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_in</ci><ci>A0</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="move_back" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r2" species="A0" stoichiometry="1" constant="true" multi:compartmentReference="to_c2"/></listOfReactants>
        <listOfProducts><speciesReference id="p2" species="A0" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k_back</ci><ci multi:speciesReference="r2">A0</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="subcomp_sref_oracle">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true"/>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A0" compartment="c1" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_c2" compartment="c2" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_in" value="0.5" constant="true"/>
      <parameter id="k_back" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="move_in" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_c2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k_in</ci><ci>A0</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="move_back" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_c2" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A0" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k_back</ci><ci>A_c2</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    _compare_with_core_oracle(multi_xml, core_xml, ["A0", "A_c2"])


def test_multi_mathml_dynamic_species_feature_count_rate_matches_core_oracle():
    """Dynamic feature-count MathML ci: speciesFeatureType occur=2, pattern
    has speciesFeature id='sf_p' occur=1 value=p, rate law multiplies by
    <ci multi:speciesReference='r1'>sf_p</ci> -> 1*k on (p,u) and 2*k on (p,p)."""

    multi_xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="dynamic_feature_count">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A_uu" compartment="cell" initialAmount="4" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:occur="2"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_pu" compartment="cell" initialAmount="6" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pu"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_pp" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="phos" multi:occur="2"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="A_has_p" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:id="sf_p" multi:speciesFeatureType="phos" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="pp"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Sink" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="SinkType"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.25" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="degrade_p" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r1" species="A_has_p" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Sink" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci multi:speciesReference="r1">sf_p</ci><ci>A_has_p</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="phos" multi:name="p" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="pu" multi:name="u"/>
              <multi:possibleSpeciesFeatureValue multi:id="pp" multi:name="p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
      <multi:speciesType multi:id="SinkType" multi:name="Sink" multi:compartment="cell"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    core_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="dynamic_feature_count_oracle">
    <listOfCompartments><compartment id="cell" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A_uu" compartment="cell" initialAmount="4" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_pu" compartment="cell" initialAmount="6" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_pp" compartment="cell" initialAmount="5" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Sink" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.25" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="r_pu" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_pu" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Sink" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A_pu</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="r_pp" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A_pp" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Sink" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>2</cn><ci>k</ci><ci>A_pp</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    # libSBML's L3V1 Core MathML validator does not recognize Multi v1 (3.26)
    # speciesFeature IDs inside <ci multi:speciesReference="r1">sf_p</ci>,
    # so validate the independent Core oracle and compare full ODE trajectories.
    _compare_with_core_oracle(
        multi_xml,
        core_xml,
        ["A_uu", "A_pu", "A_pp", "Sink"],
        validate_multi=False,
    )


# ---------------------------------------------------------------------------
# Genuinely unrepresentable / spec-invalid Multi constructs fail closed
# ---------------------------------------------------------------------------


def test_multi_truly_underspecified_and_contradictory_constructs_fail_closed():
    # 1. Positive initialAmount on a proper-subset disjunctive species
    pos_disj = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="pos_disj">
    <listOfCompartments><compartment id="c" size="1" spatialDimensions="3" constant="true" multi:isType="false"/></listOfCompartments>
    <listOfSpecies>
      <species id="A_up" compartment="c" initialAmount="5" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="st" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="vu"/>
              <multi:speciesFeatureValue multi:value="vp"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="st" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="vu"/>
              <multi:possibleSpeciesFeatureValue multi:id="vp"/>
              <multi:possibleSpeciesFeatureValue multi:id="vq"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""
    r_pos = parse_multi_package(pos_disj)
    assert r_pos.executable is False
    assert any("positive initial pool" in w.message for w in r_pos.warnings)

    # 2. Unsatisfiable (contradictory) feature predicate: NOT(a=on AND b=on) when only 'on' exists
    unsat = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="unsat">
    <listOfCompartments><compartment id="c" size="1" spatialDimensions="3" constant="true" multi:isType="false"/></listOfCompartments>
    <listOfSpecies>
      <species id="A_empty" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:subListOfSpeciesFeatures multi:relation="not">
            <multi:speciesFeature multi:speciesFeatureType="fa" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="a1"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
            <multi:speciesFeature multi:speciesFeatureType="fb" multi:occur="1"><multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="b1"/></multi:listOfSpeciesFeatureValues></multi:speciesFeature>
          </multi:subListOfSpeciesFeatures>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="fa" multi:occur="1"><multi:listOfPossibleSpeciesFeatureValues><multi:possibleSpeciesFeatureValue multi:id="a1"/></multi:listOfPossibleSpeciesFeatureValues></multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="fb" multi:occur="1"><multi:listOfPossibleSpeciesFeatureValues><multi:possibleSpeciesFeatureValue multi:id="b1"/></multi:listOfPossibleSpeciesFeatureValues></multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""
    r_unsat = parse_multi_package(unsat)
    assert r_unsat.executable is False
    assert any("unsatisfiable" in w.message for w in r_unsat.warnings)

    # 3. Non-deterministic synthesis 0 -> A(x in {u, p})
    nondet_prod = pos_disj.replace('initialAmount="5"', 'initialAmount="0"').replace(
        "</listOfSpecies>",
        """</listOfSpecies>
    <listOfReactions>
      <reaction id="synth" reversible="false" fast="false">
        <listOfProducts><speciesReference species="A_up" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>""",
    )
    imported = Atomizer(atomize=False, quiet_mode=True).atomize(nondet_prod)
    # Must record a dropped warning for the non-deterministic disjunctive product
    assert (
        any(
            "non-deterministic disjunctive products" in str(entry)
            for entry in imported.log
        )
        or "non-deterministic disjunctive products" in imported.bngl
    )
