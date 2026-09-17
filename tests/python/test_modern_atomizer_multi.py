"""Spec-derived regression tests for SBML Level 3 Multi v1 support."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from bionetgen.atomizer.modern import parse_multi_package


def test_parse_multi_package_empty_input_is_an_empty_result():
    result = parse_multi_package("")

    assert result.present is False
    assert result.deep is False
    assert result.bngl_molecule_types == []
    assert result.complex_patterns == []


def test_parse_multi_package_discovers_namespaced_top_type_outside_species_list():
    xml = """<?xml version="1.0"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
          xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
          level="3" version="1">
      <model id="multi_top_type" multi:speciesType="AType">
        <multi:listOfSpeciesTypes>
          <multi:bindingSiteSpeciesType id="binding" name="binding"/>
          <multi:speciesType id="AType" name="A">
            <multi:listOfSpeciesTypeInstances>
              <multi:speciesTypeInstance id="site1"
                speciesType="binding" name="site"/>
            </multi:listOfSpeciesTypeInstances>
          </multi:speciesType>
        </multi:listOfSpeciesTypes>
      </model>
    </sbml>
    """

    result = parse_multi_package(xml)

    assert result.present is True
    assert result.deep is False
    assert result.bngl_molecule_types == ["A(site)"]


def test_parse_multi_package_returns_structured_warning_records():
    from bionetgen.atomizer.modern import SBMLImportWarning

    xml = """<?xml version="1.0"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
          xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
          level="3" version="1">
      <model id="multi_without_types">
        <multi:listOfSpeciesTypes/>
      </model>
    </sbml>
    """

    result = parse_multi_package(xml)

    assert result.present is True
    assert len(result.warnings) >= 2
    warning = next(
        warning
        for warning in result.warnings
        if "no referenced top-level" in warning.message
    )
    assert isinstance(warning, SBMLImportWarning)
    assert warning.category == "package:multi"
    assert warning.severity == "info"
    assert warning["message"] == warning.message


def test_parse_multi_package_matches_reference_result_field_names_and_patterns():
    xml = """<?xml version="1.0"?>
    <sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
          xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
          level="3" version="1">
      <model id="multi_complex" multi:speciesType="ABType">
        <multi:listOfSpeciesTypes>
          <multi:bindingSiteSpeciesType id="bindSite" name="bind"/>
          <multi:speciesType id="AType" name="A">
            <multi:listOfSpeciesTypeInstances>
              <multi:speciesTypeInstance id="bind1" speciesType="bindSite" name="bind"/>
            </multi:listOfSpeciesTypeInstances>
          </multi:speciesType>
          <multi:speciesType id="ABType" name="ABComplex">
            <multi:listOfSpeciesTypeInstances>
              <multi:speciesTypeInstance id="A1" speciesType="AType"/>
              <multi:speciesTypeInstance id="A2" speciesType="AType"/>
            </multi:listOfSpeciesTypeInstances>
            <multi:listOfSpeciesTypeComponentIndexes>
              <multi:speciesTypeComponentIndex id="bind1_1" component="bind1" identifyingParent="A1"/>
              <multi:speciesTypeComponentIndex id="bind1_2" component="bind1" identifyingParent="A2"/>
            </multi:listOfSpeciesTypeComponentIndexes>
            <multi:listOfInSpeciesTypeBonds>
              <multi:inSpeciesTypeBond bindingSite1="bind1_1" bindingSite2="bind1_2"/>
            </multi:listOfInSpeciesTypeBonds>
          </multi:speciesType>
        </multi:listOfSpeciesTypes>
      </model>
    </sbml>
    """

    result = parse_multi_package(xml)

    assert result.bnglMoleculeTypes == ["A(bind)"]
    pattern = result.complexPatterns[0]
    assert pattern.typeId == "ABType"
    assert pattern.pattern == "A(bind!1).A(bind!1)"
    assert result.seedPatterns == []


def _shallow_multi_xml(component: str = "bind") -> str:
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1">
  <model id="shallow">
    <listOfSpecies>
      <species id="AB" multi:speciesType="ABType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType id="bindSite" name="bind"/>
      <multi:speciesType id="AType" name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance id="bind1" speciesType="bindSite" name="bind"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType id="ABType" name="ABComplex">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance id="A1" speciesType="AType"/>
          <multi:speciesTypeInstance id="A2" speciesType="AType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex id="bind1_1" component="{component}" identifyingParent="A1"/>
          <multi:speciesTypeComponentIndex id="bind1_2" component="{component}" identifyingParent="A2"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond bindingSite1="bind1_1" bindingSite2="bind1_2"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""


def test_multi_rejects_component_index_outside_its_identifying_parent_scope():
    result = parse_multi_package(_shallow_multi_xml(component="not_the_site_id"))

    assert result.present is True
    assert result.deep is False
    assert result.bngl_molecule_types == ["A(bind)"]
    assert [(item.type_id, item.pattern) for item in result.complex_patterns] == [
        ("ABType", "A(bind!1).A(bind!1)")
    ]
    assert result.executable is False
    assert any("unknown component" in item.message for item in result.warnings)


def test_multi_spec_features_and_outward_binding_statuses_become_reference_seed_pattern():
    xml = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="multi_species">
    <listOfSpecies>
      <species id="A0" multi:speciesType="AType" initialAmount="1">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="binding" multi:name="site"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:name="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="u" multi:name="U"/>
              <multi:possibleSpeciesFeatureValue multi:id="p" multi:name="P"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="binding"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.bngl_molecule_types == ["A(state~U~P,site)"]
    assert result.seed_patterns == [("A0", "A(state~P,site)")]
    assert not any(
        "required attribute" in warning.message for warning in result.warnings
    )


def test_playground_multi_detects_deep_hierarchy_without_flattening():
    xml = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1">
  <model id="deep">
    <listOfSpecies><species id="complex" multi:speciesType="complexType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType id="bst_1" name="site"/>
      <multi:speciesType id="mol_1" name="mol_1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance id="site_1" speciesType="bst_1" name="site"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType id="cps_1" name="cps_1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance id="mol_instance" speciesType="mol_1"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType id="complexType" name="complex">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance id="cps_instance" speciesType="cps_1"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.present is True
    assert result.deep is True
    assert result.bngl_molecule_types == []
    assert result.complex_patterns == []
    assert any(
        "multi-layer hierarchy" in warning.message for warning in result.warnings
    )
    assert "boundaries cannot be inferred safely" in result.warnings[0].message


def test_multi_required_deep_hierarchy_fails_closed_instead_of_flattening():
    xml = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="deep_required">
    <listOfSpecies>
      <species id="complex" multi:speciesType="complexType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="bst_1" multi:name="site"/>
      <multi:speciesType multi:id="mol_1" multi:name="mol_1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site_1" multi:speciesType="bst_1"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="cps_1" multi:name="cps_1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="mol_instance" multi:speciesType="mol_1"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="complexType" multi:name="complex">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="cps_instance" multi:speciesType="cps_1"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.deep is True
    assert result.executable is False
    assert result.bngl_molecule_types == []
    assert any(
        warning.severity == "dropped"
        and "boundaries cannot be inferred safely" in warning.message
        for warning in result.warnings
    )


def test_multi_repeated_features_on_binding_site_fail_closed():
    xml = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="repeated_binding_site_feature">
    <listOfSpecies><species id="a0" multi:speciesType="aType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
              <multi:possibleSpeciesFeatureValue multi:id="off"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:bindingSiteSpeciesType>
      <multi:speciesType multi:id="aType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        warning.severity == "dropped"
        and "repeated speciesFeature occurrences" in warning.message
        for warning in result.warnings
    )


def test_playground_multi_reports_missing_species_type_list():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1">
  <model id="missing"/>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.present is True
    assert result.deep is False
    assert any(warning.severity == "info" for warning in result.warnings)
    assert "no listOfSpeciesTypes" in result.warnings[0].message


def test_multi_product_component_map_carries_source_wildcard_binding_status():
    from bionetgen.atomizer.modern import (
        SBMLParser,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="mapped_product">
    <listOfCompartments>
      <compartment id="c" size="1" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
          <species id="A0" compartment="c" initialAmount="0"
                   multi:speciesType="AType" name="human-readable A">
            <multi:listOfOutwardBindingSites>
              <multi:outwardBindingSite multi:component="x"
                                        multi:bindingStatus="bound"/>
            </multi:listOfOutwardBindingSites>
          </species>
      <species id="A1" compartment="c" multi:speciesType="AType"
               name="A()"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r" reversible="false">
        <listOfReactants>
          <speciesReference id="r1" species="A0"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference id="p1" species="A1">
            <multi:listOfSpeciesTypeComponentMapsInProduct>
              <multi:speciesTypeComponentMapInProduct
                multi:reactant="r1" multi:reactantComponent="AType"
                multi:productComponent="AType"/>
            </multi:listOfSpeciesTypeComponentMapsInProduct>
          </speciesReference>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn>1</cn>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:name="x"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:name="x"
                                     multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    model = SBMLParser().parse(xml)
    assert model.multi_executable is True
    assert model.reactions["r"].multi_intra_species is False
    assert model.reactions["r"].products[0].multi_component_maps
    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))

    reaction = next(line for line in bngl.splitlines() if line.startswith("  r:"))
    assert "M_A(x!+)@c -> M_A(x!+)@c" in reaction


def test_multi_intra_species_reaction_requires_association_or_dissociation_shape():
    valid = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="intra_valid">
    <listOfSpecies>
      <species id="A1" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="A2" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="AA" multi:speciesType="AAType"/>
    </listOfSpecies>
    <listOfReactions>
      <multi:intraSpeciesReaction id="associate" reversible="false">
        <listOfReactants>
          <speciesReference species="A1"/>
          <speciesReference species="A2"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="AA"/></listOfProducts>
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
    result = parse_multi_package(valid)
    assert result.executable is True
    assert not any("must be a two-reactant" in w.message for w in result.warnings)

    invalid = valid.replace(
        '<multi:intraSpeciesReaction id="associate" reversible="false">',
        '<multi:intraSpeciesReaction id="transform" reversible="false">',
    ).replace(
        """        <listOfReactants>
          <speciesReference species="A1"/>
          <speciesReference species="A2"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="AA"/></listOfProducts>""",
        """        <listOfReactants><speciesReference species="A1"/></listOfReactants>
        <listOfProducts><speciesReference species="AA"/></listOfProducts>""",
    )
    rejected = parse_multi_package(invalid)
    assert rejected.executable is False
    assert any("must be a two-reactant" in w.message for w in rejected.warnings)


def test_multi_compartment_reference_overrides_species_reference_compartment():
    from bionetgen.atomizer.modern import (
        SBMLParser,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="compartment_reference">
    <listOfCompartments>
      <compartment id="c1" size="1"/>
      <compartment id="c2" size="1">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="1"
               multi:speciesType="AType" name="A(x)">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="B" compartment="c1" multi:speciesType="AType"
               name="A(x)"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="move">
        <listOfReactants><speciesReference species="A"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="B" multi:compartmentReference="inside"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:name="x"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:name="x"
                                     multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    model = SBMLParser().parse(xml)
    assert model.multi_compartment_references == {"c2": {"inside": "c2"}}
    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))
    reaction = next(line for line in bngl.splitlines() if line.startswith("  move:"))
    assert "@c1 -> M_A(x)@c2" in reaction


def test_multi_namespace_violation_is_parseable_but_not_executable():
    from bionetgen.atomizer.modern import parse_multi_package

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="bad_namespace">
        <listOfSpecies><species id="A" speciesType="AType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType id="xType" multi:name="x"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)
    assert result.present is True
    assert result.executable is False
    assert any(
        "must use the Multi namespace" in warning.message for warning in result.warnings
    )


def test_multi_repeated_feature_occurrences_and_numeric_values_are_executable():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="repeated_feature">
    <listOfParameters><parameter id="p" value="1"/></listOfParameters>
    <listOfSpecies>
      <species id="A0" multi:speciesType="AType" initialAmount="1">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="u"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="2">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="x"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="u" multi:name="U"
                                                   multi:numericValue="p"/>
              <multi:possibleSpeciesFeatureValue multi:id="x" multi:name="X"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.type_patterns["AType"] == "A(state_1~U~X,state_2~U~X)"
    assert result.species_patterns["A0"] == "A(state_1~U,state_2~X)"


def test_multi_unprefixed_attributes_on_package_elements_are_spec_valid():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="unprefixed_multi">
    <listOfSpecies>
          <species id="A0" multi:speciesType="AType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType id="xType" name="x"/>
      <multi:speciesType id="AType" name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance id="x" speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.type_patterns["AType"] == "A(x)"
    assert not any("must use the Multi namespace" in w.message for w in result.warnings)


def test_multi_empty_optional_type_list_does_not_block_core_model_import():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="core_only">
    <listOfSpecies><species id="A" name="A()"/></listOfSpecies>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.present is True
    assert result.executable is True
    assert not any(warning.severity == "dropped" for warning in result.warnings)


def test_multi_type_definitions_are_executable_without_core_species():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="definitions_only">
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.type_patterns["AType"] == "A()"


def test_multi_ignores_foreign_package_content_inside_core_metadata():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      xmlns:foo="urn:example:foo" multi:required="true">
  <model id="metadata_foreign">
    <annotation><foo:payload foo:token="opaque"><foo:item/></foo:payload></annotation>
    <listOfSpecies><species id="A0" multi:speciesType="AType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert not any("foreign" in warning.message.lower() for warning in result.warnings)


def test_multi_binding_site_species_type_is_atomic():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="non_atomic_binding_site">
    <listOfSpecies><species id="A0" multi:speciesType="AType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="bad" multi:speciesType="yType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:bindingSiteSpeciesType>
      <multi:bindingSiteSpeciesType multi:id="yType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any("must be atomic" in warning.message for warning in result.warnings)


def test_multi_scopes_local_ids_and_accepts_species_type_identifying_parent():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="scoped_ids">
    <listOfSpecies>
      <species id="outer0" multi:speciesType="outerType"/>
      <species id="a0" multi:speciesType="aType"/>
      <species id="b0" multi:speciesType="bType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType"/>
      <multi:speciesType multi:id="aType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="same" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="bType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="same" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="innerType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="innerSite" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="outerType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="inner" multi:speciesType="innerType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="outerSite"
            multi:component="innerSite" multi:identifyingParent="innerType"/>
        </multi:listOfSpeciesTypeComponentIndexes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert not any("globally unique" in warning.message for warning in result.warnings)
    assert not any(
        "unknown component" in warning.message for warning in result.warnings
    )
    assert not any(
        "unknown identifyingParent" in warning.message for warning in result.warnings
    )


def test_multi_rejects_type_and_possible_value_global_id_collision():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="global_id_collision">
    <listOfSpecies><species id="a0" multi:speciesType="aType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="aType">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="aType"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any("globally unique" in warning.message for warning in result.warnings)


def test_multi_rejects_species_feature_id_collision_with_species_id():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="species_id_scope">
    <listOfSpecies>
      <species id="a0" multi:speciesType="aType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:id="a0" multi:speciesFeatureType="state"
            multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="on"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="aType">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "Duplicate Multi speciesFeature id" in w.message for w in result.warnings
    )


def test_multi_rejects_compartment_reference_id_collision_with_parent():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="compartment_id_scope">
    <listOfCompartments>
      <compartment id="c1" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="c1" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" multi:isType="false"/>
    </listOfCompartments>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="aType"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "Duplicate compartmentReference id" in w.message for w in result.warnings
    )


def test_multi_rejects_intra_species_reaction_id_collision_with_species_type():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="reaction_id_scope">
    <listOfSpecies>
      <species id="a1" multi:speciesType="aType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x"
            multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="a2" multi:speciesType="aType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x"
            multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="aa" multi:speciesType="aaType"/>
    </listOfSpecies>
    <listOfReactions>
      <multi:intraSpeciesReaction id="aType">
        <listOfReactants>
          <speciesReference species="a1"/>
          <speciesReference species="a2"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="aa"/></listOfProducts>
      </multi:intraSpeciesReaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:speciesType multi:id="aType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="aaType"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "collides with a core Model identifier" in w.message for w in result.warnings
    )


def test_multi_positive_initial_pool_requires_fully_defined_sites():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="partial_initial_pool">
    <listOfSpecies>
      <species id="a0" initialAmount="1" multi:speciesType="aType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType"/>
      <multi:speciesType multi:id="aType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "positive initial pool" in warning.message for warning in result.warnings
    )


def test_multi_initial_assignment_initializes_species_for_definition_checks():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      xmlns:math="http://www.w3.org/1998/Math/MathML"
      multi:required="true">
  <model id="assignment_initial_pool">
    <listOfSpecies>
      <species id="a0" multi:speciesType="aType"/>
    </listOfSpecies>
    <listOfInitialAssignments>
      <initialAssignment symbol="a0">
        <math:math><math:cn type="integer">1</math:cn></math:math>
      </initialAssignment>
    </listOfInitialAssignments>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType"/>
      <multi:speciesType multi:id="aType">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.seed_patterns == [("a0", "aType(siteType)")]
    assert result.executable is False
    assert any(
        "positive initial pool" in warning.message for warning in result.warnings
    )


def test_multi_initial_assignment_requires_core_target_and_mathml():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      xmlns:math="http://www.w3.org/1998/Math/MathML"
      multi:required="true">
  <model id="invalid_assignments">
    <listOfSpecies><species id="a0" multi:speciesType="aType"/></listOfSpecies>
    <listOfInitialAssignments>
      <initialAssignment symbol="missing">
        <math:math><math:cn type="integer">1</math:cn></math:math>
      </initialAssignment>
      <initialAssignment symbol="a0"/>
    </listOfInitialAssignments>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="aType"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.seed_patterns == []
    assert any(
        "does not identify a Model element" in warning.message
        for warning in result.warnings
    )
    assert any(
        "missing its required MathML" in warning.message for warning in result.warnings
    )


def test_multi_positive_initial_pool_allows_internal_species_type_bonds():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="bonded_initial_pool">
    <listOfSpecies>
      <species id="a0" initialAmount="1" multi:speciesType="aType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:bindingSiteSpeciesType multi:id="yType"/>
      <multi:speciesType multi:id="aType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
          <multi:speciesTypeInstance multi:id="y" multi:speciesType="yType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="x"
            multi:bindingSite2="y"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.seed_patterns == [("a0", "A(xType!1,yType!1)")]
    assert not any(
        "positive initial pool" in warning.message for warning in result.warnings
    )


def test_multi_scopes_repeated_feature_type_ids_by_component():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="scoped_features">
    <listOfSpecies>
      <species id="c0" multi:speciesType="cType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state"
            multi:component="a" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="a_on"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="state"
            multi:component="b" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="b_on"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="aType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="a_on" multi:name="A"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
      <multi:speciesType multi:id="bType" multi:name="B">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="b_on" multi:name="B"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
      <multi:speciesType multi:id="cType" multi:name="C">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a" multi:speciesType="aType"/>
          <multi:speciesTypeInstance multi:id="b" multi:speciesType="bType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.species_patterns["c0"] == "A(state~A).B(state~B)"


def test_multi_resolves_component_indexes_independent_of_declaration_order():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="index_order">
    <listOfSpecies>
      <species id="x0" initialAmount="1" multi:speciesType="outer">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="aSite"
            multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType"/>
      <multi:speciesType multi:id="inner">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="outer">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a" multi:speciesType="inner"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="aSite"
            multi:component="site" multi:identifyingParent="aParent"/>
          <multi:speciesTypeComponentIndex multi:id="aParent"
            multi:component="a"/>
        </multi:listOfSpeciesTypeComponentIndexes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.species_patterns["x0"] == "inner(siteType)"
    assert not any(
        "could not resolve component" in warning.message for warning in result.warnings
    )


def test_multi_resolves_nested_index_bonds_through_indexed_parents():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="nested_index_bond">
    <listOfSpecies>
      <species id="x0" initialAmount="1" multi:speciesType="outer"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteAType"/>
      <multi:bindingSiteSpeciesType multi:id="siteBType"/>
      <multi:speciesType multi:id="innerA">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteAType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="innerB">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteBType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="outer">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a" multi:speciesType="innerA"/>
          <multi:speciesTypeInstance multi:id="b" multi:speciesType="innerB"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="aSite"
            multi:component="site" multi:identifyingParent="aParent"/>
          <multi:speciesTypeComponentIndex multi:id="bSite"
            multi:component="site" multi:identifyingParent="bParent"/>
          <multi:speciesTypeComponentIndex multi:id="aParent" multi:component="a"/>
          <multi:speciesTypeComponentIndex multi:id="bParent" multi:component="b"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="aSite"
            multi:bindingSite2="bSite"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.species_patterns["x0"] == "innerA(siteAType!1).innerB(siteBType!1)"
    assert not any(
        "must resolve both endpoints" in warning.message for warning in result.warnings
    )


def test_multi_product_component_map_ids_are_unique_across_products():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="duplicate_map_ids">
    <listOfSpecies>
      <species id="a0" multi:speciesType="aType"/>
      <species id="a1" multi:speciesType="aType"/>
      <species id="a2" multi:speciesType="aType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r">
        <listOfReactants><speciesReference id="r1" species="a0"/></listOfReactants>
        <listOfProducts>
          <speciesReference id="p1" species="a1">
            <multi:listOfSpeciesTypeComponentMapsInProduct>
              <multi:speciesTypeComponentMapInProduct multi:id="map"
                multi:reactant="r1" multi:reactantComponent="aType"
                multi:productComponent="aType"/>
            </multi:listOfSpeciesTypeComponentMapsInProduct>
          </speciesReference>
          <speciesReference id="p2" species="a2">
            <multi:listOfSpeciesTypeComponentMapsInProduct>
              <multi:speciesTypeComponentMapInProduct multi:id="map"
                multi:reactant="r1" multi:reactantComponent="aType"
                multi:productComponent="aType"/>
            </multi:listOfSpeciesTypeComponentMapsInProduct>
          </speciesReference>
        </listOfProducts>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="aType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "Duplicate Multi product component map id" in warning.message
        for warning in result.warnings
    )


def test_multi_rejects_invalid_primitive_values_before_reconstruction():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="invalid_primitives">
    <listOfSpecies>
      <species id="A0" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x"
                                    multi:bindingStatus="sometimes"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any("invalid value" in warning.message for warning in result.warnings)


def test_multi_rejects_duplicate_outward_binding_site_ids():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="duplicate_outward_ids">
    <listOfSpecies>
      <species id="A0" initialAmount="1" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:id="site1" multi:component="x"
            multi:bindingStatus="unbound"/>
          <multi:outwardBindingSite multi:id="site1" multi:component="y"
            multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:bindingSiteSpeciesType multi:id="yType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
          <multi:speciesTypeInstance multi:id="y" multi:speciesType="yType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "Duplicate Multi outwardBindingSite id" in warning.message
        for warning in result.warnings
    )


def test_multi_reports_spec_valid_cross_compartment_component_as_nonrepresentable():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="cross_compartment_component">
    <listOfCompartments>
      <compartment id="cc" size="1">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c" size="1"/>
    </listOfCompartments>
    <listOfSpecies><species id="A0" compartment="cc"
      multi:speciesType="AType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:compartment="c"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cc">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"
            multi:compartmentReference="inside"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.present is True
    assert result.executable is False
    assert any(
        "different compartment" in warning.message for warning in result.warnings
    )


def test_multi_accepts_species_in_instance_of_species_type_compartment():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="compartment_type_instance">
    <listOfCompartments>
      <compartment id="ct" multi:isType="true"/>
      <compartment id="c1" multi:isType="false" multi:compartmentType="ct"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="x0" compartment="c1" initialAmount="1"
        multi:speciesType="aType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site"
            multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site"
        multi:compartment="ct"/>
      <multi:speciesType multi:id="aType" multi:name="A" multi:compartment="ct">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.species_patterns["x0"] == "A(site)@c1"
    assert not any(
        "conflicts with speciesType compartment" in warning.message
        for warning in result.warnings
    )


def test_multi_supports_features_defined_on_binding_site_species_types():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="binding_site_feature">
    <listOfSpecies>
      <species id="x0" initialAmount="1" multi:speciesType="aType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site"
            multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state"
            multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="on"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
              <multi:possibleSpeciesFeatureValue multi:id="off"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:bindingSiteSpeciesType>
      <multi:speciesType multi:id="aType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.species_patterns["x0"] == "A(site~on)"


def test_multi_allows_state_features_and_in_species_bonds_on_one_species_type():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="feature_and_bond">
    <listOfSpecies><species id="A0" multi:speciesType="AType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:bindingSiteSpeciesType multi:id="yType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x1" multi:speciesType="xType"/>
          <multi:speciesTypeInstance multi:id="x2" multi:speciesType="yType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="x1" multi:bindingSite2="x2"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert result.type_patterns["AType"] == "A(state~on,xType!1,yType!1)"


def test_multi_rejects_same_binding_type_bonds_and_anonymous_reference_cycles():
    same_type = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="same_binding_type">
    <listOfSpecies><species id="A0" multi:speciesType="AType"/></listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x1" multi:speciesType="xType"/>
          <multi:speciesTypeInstance multi:id="x2" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="x1" multi:bindingSite2="x2"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""
    rejected = parse_multi_package(same_type)
    assert rejected.executable is False
    assert any("same type" in warning.message for warning in rejected.warnings)

    cycle = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="anonymous_cycle">
    <listOfCompartments>
      <compartment id="c1" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:compartment="c1"/>
        </multi:listOfCompartmentReferences>
      </compartment>
    </listOfCompartments>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""
    cycle_result = parse_multi_package(cycle)
    assert any(
        "contain a cycle" in warning.message for warning in cycle_result.warnings
    )


def test_multi_and_sublist_is_flattened_but_or_sublist_fails_closed():
    def make_xml(relation: str) -> str:
        return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
          xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
          multi:required="true">
      <model id="sublist">
        <listOfSpecies>
          <species id="A0" multi:speciesType="AType" initialAmount="0">
            <multi:listOfSpeciesFeatures>
              <multi:subListOfSpeciesFeatures multi:relation="{relation}">
                <multi:speciesFeature multi:speciesFeatureType="a" multi:occur="1">
                  <multi:listOfSpeciesFeatureValues>
                    <multi:speciesFeatureValue multi:value="a_on"/>
                  </multi:listOfSpeciesFeatureValues>
                </multi:speciesFeature>
                <multi:speciesFeature multi:speciesFeatureType="b" multi:occur="1">
                  <multi:listOfSpeciesFeatureValues>
                    <multi:speciesFeatureValue multi:value="b_on"/>
                  </multi:listOfSpeciesFeatureValues>
                </multi:speciesFeature>
              </multi:subListOfSpeciesFeatures>
            </multi:listOfSpeciesFeatures>
          </species>
        </listOfSpecies>
        <multi:listOfSpeciesTypes>
          <multi:speciesType multi:id="AType" multi:name="A">
            <multi:listOfSpeciesFeatureTypes>
              <multi:speciesFeatureType multi:id="a" multi:name="a" multi:occur="2">
                <multi:listOfPossibleSpeciesFeatureValues>
                  <multi:possibleSpeciesFeatureValue multi:id="a_on" multi:name="on"/>
                </multi:listOfPossibleSpeciesFeatureValues>
              </multi:speciesFeatureType>
              <multi:speciesFeatureType multi:id="b" multi:name="b" multi:occur="1">
                <multi:listOfPossibleSpeciesFeatureValues>
                  <multi:possibleSpeciesFeatureValue multi:id="b_on" multi:name="on"/>
                </multi:listOfPossibleSpeciesFeatureValues>
              </multi:speciesFeatureType>
            </multi:listOfSpeciesFeatureTypes>
          </multi:speciesType>
        </multi:listOfSpeciesTypes>
      </model>
    </sbml>"""

    conjunction = parse_multi_package(make_xml("and"))
    assert conjunction.executable is True
    assert conjunction.species_patterns["A0"] == "A(a_1~on,a_2,b~on)"

    invalid_conjunction = parse_multi_package(
        make_xml("and").replace('multi:occur="2"', 'multi:occur="1"')
    )
    assert invalid_conjunction.executable is False
    assert any(
        "relation=and is only valid" in warning.message
        for warning in invalid_conjunction.warnings
    )

    disjunction = parse_multi_package(make_xml("or"))
    assert disjunction.executable is False
    assert any("relation=or" in warning.message for warning in disjunction.warnings)

    negation = parse_multi_package(make_xml("not"))
    assert negation.executable is False
    assert any("relation=not" in warning.message for warning in negation.warnings)


def test_multi_mathml_ci_extensions_are_validated_and_reconstructed():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      xmlns:m="http://www.w3.org/1998/Math/MathML" multi:required="true">
  <model id="mathml_multi">
    <listOfParameters><parameter id="p" value="2"/></listOfParameters>
    <listOfSpecies>
      <species id="A0" compartment="c" multi:speciesType="AType"/>
    </listOfSpecies>
    <listOfCompartments>
      <compartment id="c" size="1" multi:isType="false"/>
    </listOfCompartments>
    <listOfReactions>
      <reaction id="r">
        <listOfReactants><speciesReference id="r1" species="A0"/></listOfReactants>
        <listOfProducts><speciesReference id="p1" species="A0"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><plus/>
            <ci multi:representationType="sum">A0</ci>
            <ci multi:representationType="numericValue" multi:speciesReference="r1">u</ci>
          </apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="u" multi:numericValue="p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is True
    assert not any(warning.severity == "dropped" for warning in result.warnings)

    from bionetgen.atomizer.modern import (
        SBMLParser,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    model = SBMLParser().parse(xml)
    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))
    assert "Molecules __multi_sum_A0" in bngl
    assert "__multi_sum_A0 + p" in bngl


def test_multi_mathml_species_reference_compartment_amount_fails_closed():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="mathml_compartment_reference">
    <listOfCompartments>
      <compartment id="c1" size="1"/>
      <compartment id="c2" size="1">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A0" compartment="c1" multi:speciesType="AType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r">
        <listOfReactants><speciesReference id="r1" species="A0"/></listOfReactants>
        <listOfProducts>
          <speciesReference id="p1" species="A0" multi:compartmentReference="inside"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci multi:speciesReference="p1">A0</ci>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "reference-specific amount is not representable" in warning.message
        for warning in result.warnings
    )


def test_multi_mathml_species_feature_count_fails_closed():
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      multi:required="true">
  <model id="mathml_feature_count">
    <listOfSpecies>
      <species id="A0" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:id="sf" multi:speciesFeatureType="state"
                                multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="on"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r">
        <listOfReactants><speciesReference id="r1" species="A0"/></listOfReactants>
        <listOfProducts><speciesReference id="p1" species="A0"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <ci multi:speciesReference="r1">sf</ci>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)

    assert result.executable is False
    assert any(
        "feature-count rate laws are not representable" in warning.message
        for warning in result.warnings
    )


def test_multi_invalid_xml_fails_closed_with_diagnostic():
    result = parse_multi_package("<sbml xmlns:multi='broken'>")

    assert result.executable is False
    assert any(
        "could not be parsed as XML" in warning.message for warning in result.warnings
    )


def test_real_sbml_multi_validation_model_reconstructs_and_parses_with_bng_cpp():
    from bionetgen.atomizer.modern import (
        SBMLParser,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    fixture = (
        Path(__file__).parents[1]
        / "validation/Validate/test_write_sbml_multi_sbml_sbmlmulti.xml"
    )
    model = SBMLParser().parse(fixture.read_text())
    assert model.multi_executable is True
    assert len(model.multi_species_patterns) == 13
    assert len(model.multi_reaction_mappings) == 6
    assert model.multi_type_patterns["ST3"] == "L(r,r,r!1)@cell.R(l!1,l)@cell"

    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))
    assert "not yet fed into the simulated network" not in bngl
    assert "M_L(r,r,r)" in bngl
    assert "M_L(r,r,r!1).M_R(l!1,l!?)" in bngl
    assert "__sp~" not in bngl

    configured_oracle = os.environ.get("BNG_CPP")
    oracle = (
        Path(configured_oracle)
        if configured_oracle
        else Path(__file__).parents[2] / "build/cpp/bng_cpp"
    )
    if not oracle.exists():
        pytest.skip("bng_cpp execution oracle is not built")
    completed = subprocess.run(
        [str(oracle), "/dev/stdin"],
        input=bngl,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "parse ok" in completed.stdout


def test_cpp_sbml_multi_writer_roundtrip_is_libsbml_consistent(tmp_path):
    libsbml = pytest.importorskip("libsbml")
    configured = os.environ.get("BNG_CPP")
    oracle = (
        Path(configured)
        if configured
        else Path(__file__).parents[2] / "build/cpp/bng_cpp"
    )
    if not oracle.exists():
        pytest.skip("bng_cpp writer oracle is not built (set BNG_CPP)")

    source = (
        Path(__file__).parents[1] / "validation/Validate/test_write_sbml_multi.bngl"
    )
    input_path = tmp_path / source.name
    input_path.write_text(source.read_text())
    completed = subprocess.run(
        [str(oracle), str(input_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    outputs = sorted(tmp_path.glob("*_sbml_multi.xml"))
    assert len(outputs) == 1

    document = libsbml.readSBML(str(outputs[0]))
    assert document.getNumErrors() == 0
    assert document.checkInternalConsistency() == 0
    result = parse_multi_package(outputs[0].read_text())
    assert result.present is True
    output_text = outputs[0].read_text()
    assert 'multi:required="true"' in output_text
    assert "multi:listOfOutwardBindingSites" in output_text
    assert 'multi:bindingStatus="unbound"' in output_text
    assert result.executable is True
    assert not any(warning.severity == "dropped" for warning in result.warnings)


def test_reconstructed_sbml_multi_model_runs_in_independent_nfsim(tmp_path):
    configured_cpp = os.environ.get("BNG_CPP")
    oracle_cpp = (
        Path(configured_cpp)
        if configured_cpp
        else Path(__file__).parents[2] / "build/cpp/bng_cpp"
    )
    native_nfsim = os.environ.get("NFSIM_BIN")
    if not oracle_cpp.exists():
        pytest.skip("bng_cpp execution oracle is not built (set BNG_CPP)")
    if not native_nfsim or not Path(native_nfsim).exists():
        pytest.skip("independent NFsim oracle is unavailable (set NFSIM_BIN)")

    from bionetgen.atomizer.modern import (
        SBMLParser,
        build_species_composition_table,
        generate_bngl,
        get_molecule_types,
        get_seed_species,
    )

    fixture = (
        Path(__file__).parents[1]
        / "validation/Validate/test_write_sbml_multi_sbml_sbmlmulti.xml"
    )
    model = SBMLParser().parse(fixture.read_text())
    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))
    sanitized_lines = []
    skipped_section = None
    in_seed_species = False
    for line in bngl.splitlines():
        marker = line.strip().lower()
        if marker in {"begin observables", "begin functions"}:
            skipped_section = marker.removeprefix("begin ")
            continue
        if skipped_section is not None:
            if marker == f"end {skipped_section}":
                skipped_section = None
            continue
        if marker == "begin seed species":
            in_seed_species = True
        elif marker == "end seed species":
            in_seed_species = False
        if in_seed_species and line.split() and line.split()[-1] == "0":
            continue
        sanitized_lines.append(line)
    bngl = "\n".join(sanitized_lines)
    input_path = tmp_path / "multi_oracle.bngl"
    input_path.write_text(
        bngl.rstrip() + "\n\n## actions ##\nwriteXML({overwrite=>1})\n"
    )
    compiled = subprocess.run(
        [str(oracle_cpp), str(input_path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    xml_path = tmp_path / "multi_oracle.xml"
    assert xml_path.exists()

    gdat_path = tmp_path / "multi_oracle_nf.gdat"
    executed = subprocess.run(
        [
            str(Path(native_nfsim).resolve()),
            "-xml",
            str(xml_path),
            "-o",
            str(gdat_path),
            "-sim",
            "0.1",
            "-oSteps",
            "1",
            "-seed",
            "17",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr or executed.stdout
    assert gdat_path.exists()
    gdat_lines = gdat_path.read_text().splitlines()
    assert "time" in gdat_lines[0]
    assert len(gdat_lines) >= 2
