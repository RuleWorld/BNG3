"""Source-derived tests for conservative SBML-Multi discovery boundaries."""

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
    assert len(result.warnings) == 1
    warning = result.warnings[0]
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
