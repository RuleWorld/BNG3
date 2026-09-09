"""Source-derived tests for the bounded Playground SBML-Multi extractor."""

from __future__ import annotations

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


def test_playground_multi_resolves_single_site_bonds_with_component_fallback():
    result = parse_multi_package(_shallow_multi_xml(component="not_the_site_id"))

    assert result.present is True
    assert result.deep is False
    assert result.bngl_molecule_types == ["A(bind)"]
    assert [(item.type_id, item.pattern) for item in result.complex_patterns] == [
        ("ABType", "A(bind!1).A(bind!1)")
    ]
    assert not any("could not be resolved" in item.message for item in result.warnings)


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
    assert not any("required attribute" in warning.message for warning in result.warnings)


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
    assert any("multi-layer hierarchy" in warning.message for warning in result.warnings)
    assert "complex" in result.warnings[0].message


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
