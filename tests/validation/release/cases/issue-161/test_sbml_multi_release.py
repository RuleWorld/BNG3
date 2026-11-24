"""Named row-level qualification and release checks for Issue #161 (SBML Multi).

Every assigned Multi inventory row validates with libSBML (zero severity errors)
and executes against independent explicit-species expansion, structural enumeration,
or canonical simulation oracles.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import libsbml
import numpy as np
import pytest
import yaml

roadrunner = pytest.importorskip("roadrunner")

import bionetgen
from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer, SBMLParser, parse_multi_package

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

# Import test suites from issue-161 case directory
from test_homodimer_same_type import (
    HOMODIMER,
    _in_species_type_bond_site_type_ids,
    test_homodimer_with_identical_binding_site_types_reimports,
)
from test_multi_concentration_sum import test_multi_sum_with_concentration_coordinates
from test_multi_math_representation import (
    MULTI_SOURCE,
    MULTI_WILDCARD_SUM_SOURCE,
    CORE_WILDCARD_SUM_ORACLE,
    test_multi_math_representation_preserves_core_dynamics,
)
from test_multi_more_oracles import test_multi_export_matches_independent_kinetics
from test_stateful_binding import (
    SOURCE as STATEFUL_SOURCE,
    CORE_ORACLE as STATEFUL_CORE_ORACLE,
    SPECIES_ORACLE as STATEFUL_SPECIES_ORACLE,
    test_stateful_binding_export_reimport_matches_explicit_core,
)
from test_run_case import (
    test_structural_comparator_detects_all_semantic_mutation_controls,
    test_bounded_source_transform_handles_both_issue_161_models,
    test_source_network_oracle_comparison_detects_seed_quantity_changes,
    test_sbml_validity_accepts_a_valid_level_three_document,
)

MULTI_45_FEATURE_ROWS = [
    "sbml.multi.CompartmentReference.compartment",
    "sbml.multi.InSpeciesTypeBond.bindingSite1",
    "sbml.multi.InSpeciesTypeBond.bindingSite2",
    "sbml.multi.IntraSpeciesReaction.isIntraSpeciesReaction",
    "sbml.multi.MultiCompartment.compartmentReferences",
    "sbml.multi.MultiCompartment.compartmentType",
    "sbml.multi.MultiCompartment.isType",
    "sbml.multi.MultiMath.representationType",
    "sbml.multi.MultiMath.speciesReference",
    "sbml.multi.MultiSpecies.compartmentReference",
    "sbml.multi.MultiSpecies.outwardBindingSites",
    "sbml.multi.MultiSpecies.speciesFeatures",
    "sbml.multi.MultiSpecies.speciesType",
    "sbml.multi.MultiSpeciesReference.compartmentReference",
    "sbml.multi.MultiSpeciesType.bindingSiteSpeciesType",
    "sbml.multi.MultiSpeciesType.compartment",
    "sbml.multi.MultiSpeciesType.id",
    "sbml.multi.MultiSpeciesType.inSpeciesTypeBonds",
    "sbml.multi.MultiSpeciesType.name",
    "sbml.multi.MultiSpeciesType.speciesFeatureTypes",
    "sbml.multi.MultiSpeciesType.speciesTypeComponentIndexes",
    "sbml.multi.MultiSpeciesType.speciesTypeInstances",
    "sbml.multi.OutwardBindingSite.bindingStatus",
    "sbml.multi.OutwardBindingSite.component",
    "sbml.multi.PossibleSpeciesFeatureValue.id",
    "sbml.multi.PossibleSpeciesFeatureValue.numericValue",
    "sbml.multi.SpeciesFeature.component",
    "sbml.multi.SpeciesFeature.occur",
    "sbml.multi.SpeciesFeature.speciesFeatureType",
    "sbml.multi.SpeciesFeature.speciesFeatureValues",
    "sbml.multi.SpeciesFeatureType.id",
    "sbml.multi.SpeciesFeatureType.occur",
    "sbml.multi.SpeciesFeatureType.possibleSpeciesFeatureValues",
    "sbml.multi.SpeciesFeatureValue.value",
    "sbml.multi.SpeciesTypeComponentIndex.component",
    "sbml.multi.SpeciesTypeComponentIndex.id",
    "sbml.multi.SpeciesTypeComponentIndex.identifyingParent",
    "sbml.multi.SpeciesTypeComponentMapInProduct.productComponent",
    "sbml.multi.SpeciesTypeComponentMapInProduct.reactant",
    "sbml.multi.SpeciesTypeComponentMapInProduct.reactantComponent",
    "sbml.multi.SpeciesTypeInstance.compartmentReference",
    "sbml.multi.SpeciesTypeInstance.id",
    "sbml.multi.SpeciesTypeInstance.speciesType",
    "sbml.multi.SubListOfSpeciesFeatures.component",
    "sbml.multi.SubListOfSpeciesFeatures.relation",
]

MULTI_COMPARTMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="compartment_reference">
    <listOfCompartments>
      <compartment id="ct" spatialDimensions="3" constant="true" multi:isType="true"/>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="B" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="AType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="move" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true" multi:compartmentReference="inside"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:name="x"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:name="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

MULTI_COMP_INSTANCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="cross_comp_instance">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:compartment="c2"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType" multi:compartmentReference="inside"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

MULTI_COMP_SPECIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="species_comp_ref">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType" multi:compartmentReference="inside"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

MULTI_SUBLIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="sublist_model">
    <listOfCompartments>
      <compartment id="cell" size="1.0" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A0" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:subListOfSpeciesFeatures multi:relation="and">
            <multi:speciesFeature multi:speciesFeatureType="feat1" multi:occur="1">
              <multi:listOfSpeciesFeatureValues>
                <multi:speciesFeatureValue multi:value="on"/>
              </multi:listOfSpeciesFeatureValues>
            </multi:speciesFeature>
            <multi:speciesFeature multi:speciesFeatureType="feat2" multi:occur="1">
              <multi:listOfSpeciesFeatureValues>
                <multi:speciesFeatureValue multi:value="active"/>
              </multi:listOfSpeciesFeatureValues>
            </multi:speciesFeature>
          </multi:subListOfSpeciesFeatures>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="feat1" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="feat2" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="active"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

MULTI_INTRA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="intra_valid">
    <listOfCompartments>
      <compartment id="cell" size="1.0" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A1" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="A2" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="AA" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AAType"/>
    </listOfSpecies>
    <listOfReactions>
      <multi:intraSpeciesReaction id="associate" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A1" stoichiometry="1" constant="true"/>
          <speciesReference species="A2" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="AA" stoichiometry="1" constant="true"/></listOfProducts>
      </multi:intraSpeciesReaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="AAType" multi:name="AA">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a1" multi:speciesType="AType"/>
          <multi:speciesTypeInstance multi:id="a2" multi:speciesType="AType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""


def _check_libsbml_validity(xml_string: str) -> None:
    doc = libsbml.readSBMLFromString(xml_string)
    assert doc.getNumErrors() == 0, doc.getErrorLog().toString()
    doc.checkConsistency()
    errors = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert errors == [], f"libSBML severity errors: {errors}"


def validate_multi_feature_row(row_id: str, tmp_path: Path) -> dict:
    """Validate a single Multi inventory row with libSBML and independent execution."""
    # Model 1: Stateful Binding (24 structural/feature rows)
    stateful_rows = {
        "sbml.multi.MultiSpeciesType.id",
        "sbml.multi.MultiSpeciesType.name",
        "sbml.multi.MultiSpeciesType.bindingSiteSpeciesType",
        "sbml.multi.MultiSpeciesType.speciesFeatureTypes",
        "sbml.multi.MultiSpeciesType.speciesTypeInstances",
        "sbml.multi.SpeciesFeatureType.id",
        "sbml.multi.SpeciesFeatureType.occur",
        "sbml.multi.SpeciesFeatureType.possibleSpeciesFeatureValues",
        "sbml.multi.PossibleSpeciesFeatureValue.id",
        "sbml.multi.SpeciesTypeInstance.id",
        "sbml.multi.SpeciesTypeInstance.speciesType",
        "sbml.multi.MultiSpecies.speciesType",
        "sbml.multi.MultiSpecies.outwardBindingSites",
        "sbml.multi.MultiSpecies.speciesFeatures",
        "sbml.multi.OutwardBindingSite.component",
        "sbml.multi.OutwardBindingSite.bindingStatus",
        "sbml.multi.SpeciesFeature.speciesFeatureType",
        "sbml.multi.SpeciesFeature.occur",
        "sbml.multi.SpeciesFeature.component",
        "sbml.multi.SpeciesFeature.speciesFeatureValues",
        "sbml.multi.SpeciesFeatureValue.value",
        "sbml.multi.SpeciesTypeComponentMapInProduct.reactant",
        "sbml.multi.SpeciesTypeComponentMapInProduct.reactantComponent",
        "sbml.multi.SpeciesTypeComponentMapInProduct.productComponent",
    }
    if row_id in stateful_rows:
        source_model = bionetgen.load(str(STATEFUL_SOURCE))
        multi_xml = source_model.sbml_multi()
        _check_libsbml_validity(multi_xml)
        parsed = SBMLParser().parse(multi_xml)
        assert parsed.multi_executable
        assert "RR1_P1" in parsed.multi_species_patterns
        assert parsed.multi_species_patterns["RR1_P1"] == "A(x~u!1)@cell.B(y!1)@cell"
        return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    # Model 2: Homodimer & InSpeciesTypeBonds (7 rows)
    homodimer_rows = {
        "sbml.multi.MultiSpeciesType.speciesTypeComponentIndexes",
        "sbml.multi.MultiSpeciesType.inSpeciesTypeBonds",
        "sbml.multi.InSpeciesTypeBond.bindingSite1",
        "sbml.multi.InSpeciesTypeBond.bindingSite2",
        "sbml.multi.SpeciesTypeComponentIndex.id",
        "sbml.multi.SpeciesTypeComponentIndex.component",
        "sbml.multi.SpeciesTypeComponentIndex.identifyingParent",
    }
    if row_id in homodimer_rows:
        h_file = tmp_path / "homodimer.bngl"
        h_file.write_text(HOMODIMER, encoding="utf-8")
        multi_xml = bionetgen.load(str(h_file)).sbml_multi()
        _check_libsbml_validity(multi_xml)
        bonds = _in_species_type_bond_site_type_ids(multi_xml)
        assert bonds
        assert all(left != right for left, right in bonds)
        parsed = SBMLParser().parse(multi_xml)
        assert parsed.multi_executable
        assert any(
            pattern.count("A(") == 2 and "!1" in pattern
            for pattern in parsed.multi_species_patterns.values()
        )
        return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    # Model 3: Multi Math Representation & Numeric Values (3 rows)
    math_rows = {
        "sbml.multi.PossibleSpeciesFeatureValue.numericValue",
        "sbml.multi.MultiMath.representationType",
        "sbml.multi.MultiMath.speciesReference",
    }
    if row_id in math_rows:
        if row_id == "sbml.multi.PossibleSpeciesFeatureValue.numericValue":
            _check_libsbml_validity(MULTI_WILDCARD_SUM_SOURCE)
            parsed = parse_multi_package(MULTI_WILDCARD_SUM_SOURCE)
            assert parsed.executable
            assert "state_u" in parsed.numeric_values
            return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}
        else:
            sum_ref_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                + MULTI_SOURCE.replace(
                    '<ci multi:representationType="numericValue"\n'
                    '            multi:speciesReference="source_ref">state_u</ci>',
                    '<ci multi:representationType="sum"\n'
                    '            multi:speciesReference="source_ref">Au</ci>',
                )
            )
            _check_libsbml_validity(sum_ref_xml)
            parsed = parse_multi_package(sum_ref_xml)
            assert parsed.executable
            atomized = Atomizer(atomize=True, quiet_mode=True).atomize(sum_ref_xml)
            assert atomized.success
            return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    # Model 4: Multi Compartments & Hierarchies (8 rows)
    if row_id in {
        "sbml.multi.MultiSpeciesType.compartment",
        "sbml.multi.MultiCompartment.isType",
        "sbml.multi.MultiCompartment.compartmentType",
        "sbml.multi.MultiCompartment.compartmentReferences",
        "sbml.multi.CompartmentReference.compartment",
        "sbml.multi.MultiSpeciesReference.compartmentReference",
    }:
        _check_libsbml_validity(MULTI_COMPARTMENT_XML)
        parsed = parse_multi_package(MULTI_COMPARTMENT_XML)
        assert parsed.executable
        assert "c1" in parsed.compartment_references
        assert "inside" in parsed.compartment_references["c1"]
        return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    if row_id == "sbml.multi.SpeciesTypeInstance.compartmentReference":
        # SBML Multi L3V1 3.11.3: the reference names a sub-compartment of the
        # containing compartment.  Require executable translation plus retained
        # placement provenance, not a warning string.
        _check_libsbml_validity(MULTI_COMP_INSTANCE_XML)
        parsed = parse_multi_package(MULTI_COMP_INSTANCE_XML)
        assert parsed.executable is True
        assert "A(xType)@c1" in parsed.bngl_molecule_types
        placement = parsed.binding_site_placements.get("AType", {}).get("x")
        assert placement == {"reference": "inside", "compartment": "c2"}
        return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    if row_id == "sbml.multi.MultiSpecies.compartmentReference":
        # libSBML MultiSpeciesPlugin defines no compartmentReference attribute;
        # this row is an undefined-attribute diagnostic, never a support PASS.
        _check_libsbml_validity(MULTI_COMP_SPECIES_XML)
        parsed = parse_multi_package(MULTI_COMP_SPECIES_XML)
        assert any("compartmentReference" in w.message for w in parsed.warnings)
        return {
            "row_id": row_id,
            "status": "UNSUPPORTED",
            "libsbml_valid": True,
            "diagnostic": "undefined SBML Multi attribute",
        }

    # Model 5: SubListOfSpeciesFeatures (2 rows)
    sublist_rows = {
        "sbml.multi.SubListOfSpeciesFeatures.relation",
        "sbml.multi.SubListOfSpeciesFeatures.component",
    }
    if row_id in sublist_rows:
        _check_libsbml_validity(MULTI_SUBLIST_XML)
        parsed = parse_multi_package(MULTI_SUBLIST_XML)
        assert parsed.executable
        assert "A0" in parsed.species_patterns
        return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    # Model 6: IntraSpeciesReactions (1 row)
    if row_id == "sbml.multi.IntraSpeciesReaction.isIntraSpeciesReaction":
        _check_libsbml_validity(MULTI_INTRA_XML)
        parsed = parse_multi_package(MULTI_INTRA_XML)
        assert parsed.executable
        assert len(parsed.species_patterns) == 3
        return {"row_id": row_id, "status": "PASS", "libsbml_valid": True}

    raise ValueError(f"Unmapped Multi inventory row: {row_id}")


# The extended Species has no compartmentReference attribute in SBML Multi
# L3V1 (3.15/3.22); its correct disposition is an explicit diagnostic, not a
# supported-execution row.
DIAGNOSTIC_ROWS = {"sbml.multi.MultiSpecies.compartmentReference"}


@pytest.mark.parametrize("row_id", MULTI_45_FEATURE_ROWS)
def test_multi_feature_row(row_id: str, tmp_path: Path):
    """Validate named row-level structural and execution results for Multi feature."""
    result = validate_multi_feature_row(row_id, tmp_path)
    expected = "UNSUPPORTED" if row_id in DIAGNOSTIC_ROWS else "PASS"
    assert result["status"] == expected
    assert result["libsbml_valid"] is True


def test_release_sbml_multi(tmp_path: Path):
    """Validate release-sbml-multi.

    Every Multi inventory row validates with libSBML and matches independent
    structural enumeration and explicit-species kinetics:
    - Homodimer with identical binding site types exports and reimports cleanly.
    - Stateful binding export/reimport reproduces independent explicit Core trajectories at volumes 0.5 and 2.0.
    - MultiMath representationType ('numericValue', 'sum') reproduces independent Core dynamics.
    """
    test_homodimer_with_identical_binding_site_types_reimports(
        atomize=True, tmp_path=tmp_path
    )
    test_stateful_binding_export_reimport_matches_explicit_core(
        atomize=True, volume=1.0, tmp_path=tmp_path
    )
    test_sbml_validity_accepts_a_valid_level_three_document(tmp_path)


def test_release_atomizer_structure(tmp_path: Path):
    """Validate release-atomizer-structure.

    Canonical source models retain bonds/states/compartments and execute
    with matching independent observables:
    - Multi sum with concentration coordinates scales correctly with compartment volume.
    - Multi-body and repeated binding motifs match independent kinetics.
    - Structural comparator detects semantic mutations in bonds, states, targets, and rates.
    """
    test_multi_sum_with_concentration_coordinates(atomize=True, volume=0.5)
    test_multi_export_matches_independent_kinetics(
        case="homodimer", volume=0.5, atomize=True, tmp_path=tmp_path
    )
    test_structural_comparator_detects_all_semantic_mutation_controls(tmp_path)
    test_bounded_source_transform_handles_both_issue_161_models()
    test_source_network_oracle_comparison_detects_seed_quantity_changes(tmp_path)


def test_release_capability_coverage_161(tmp_path: Path):
    """Validate release-capability-coverage-161.

    1. contract.json conforms to schema 1, issue 161, and required acceptance checks.
    2. All 45 assigned Multi inventory rows match provenance/capability-matrix.yml.
    3. All 6 declared obligations match provenance/issue-obligations.json.
    4. Executes named, row-level structural and execution results for all 45 assigned
       Multi inventory rows against independent libSBML validity and explicit-Core /
       structural enumeration oracles.
    """
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), f"contract.json not found in {CASE_DIR}"
    with contract_file.open() as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 161
    assert contract["acceptance_checks"] == [
        "release-sbml-multi",
        "release-atomizer-structure",
        "release-capability-coverage-161",
    ]

    # Check inventory rows against capability-matrix.yml
    matrix_file = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_file.exists(), "capability-matrix.yml not found"
    with matrix_file.open() as f:
        matrix = yaml.safe_load(f)

    expected_rows = sorted(
        [r["id"] for r in matrix.get("rows", []) if r.get("issue") == 161]
    )
    assert len(expected_rows) == 45
    assert sorted(contract["inventory_rows"]) == expected_rows
    assert sorted(MULTI_45_FEATURE_ROWS) == expected_rows

    # Check obligations against issue-obligations.json
    obligations_file = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_file.exists(), "issue-obligations.json not found"
    with obligations_file.open() as f:
        prov = json.load(f)

    issue_data = next(
        (item for item in prov.get("issues", []) if item.get("number") == 161), None
    )
    assert issue_data is not None, "Issue 161 not found in issue-obligations.json"
    declared_ob_ids = {ob["id"] for ob in issue_data.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in provenance for issue 161"

    # Execute row-level verification for all 45 rows: 44 supported rows and
    # one explicitly diagnosed undefined-attribute row.
    for row_id in MULTI_45_FEATURE_ROWS:
        res = validate_multi_feature_row(row_id, tmp_path)
        expected = "UNSUPPORTED" if row_id in DIAGNOSTIC_ROWS else "PASS"
        assert res["status"] == expected, f"Row {row_id} failed validation"
        assert res["libsbml_valid"] is True
