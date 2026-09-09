"""Source-derived tests for the bounded Playground SBML-Multi extractor."""

from __future__ import annotations

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
    <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
    <listOfSpecies>
      <species id="A0" compartment="c" initialAmount="1"
               multi:speciesType="AType" name="A(x!+)"/>
      <species id="A1" compartment="c" multi:speciesType="AType"
               name="A()"/>
    </listOfSpecies>
    <listOfReactions>
      <multi:intraSpeciesReaction multi:id="r" multi:reversible="false">
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
      </multi:intraSpeciesReaction>
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
    assert model.reactions["r"].multi_intra_species is True
    assert model.reactions["r"].products[0].multi_component_maps
    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))

    reaction = next(line for line in bngl.splitlines() if line.startswith("  r:"))
    assert "M_A(x!+)@c -> M_A(x!+)@c" in reaction


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
               multi:speciesType="AType" name="A(x)"/>
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
    <listOfSpecies><species id="A" multi:speciesType="AType"/></listOfSpecies>
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
    assert model.multi_type_patterns["ST3"] == "L(r,r,r!1).R(l!1,l)"

    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))
    assert "not yet fed into the simulated network" not in bngl
    assert "M_L(r,r,r)" in bngl
    assert "M_L(r,r,r!1).M_R(l!1)" in bngl
    assert "__sp~" not in bngl

    oracle = Path(__file__).parents[2] / "build/cpp/bng_cpp"
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
