"""Regression tests for SBML L3 layout/render/groups metadata preservation and Multi v1 boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest

from bionetgen.atomizer.modern import (
    Atomizer,
    SBMLParser,
    attach_preserved_package_metadata,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
    metadata_payload,
    parse_multi_package,
    source_metadata_payload,
    source_metadata_summary,
)

LAYOUT_NS = "http://www.sbml.org/sbml/level3/version1/layout/version1"
RENDER_NS = "http://www.sbml.org/sbml/level3/version1/render/version1"
GROUPS_NS = "http://www.sbml.org/sbml/level3/version1/groups/version1"
MULTI_NS = "http://www.sbml.org/sbml/level3/version1/multi/version1"


CORE_KINETIC_SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="kinetic_core" metaid="meta_model">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" metaid="meta_A" compartment="cell" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" metaid="meta_B" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants>
          <speciesReference id="sr_A" species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference id="sr_B" species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


FULL_METADATA_PACKAGES_SBML = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      xmlns:layout="{LAYOUT_NS}"
      xmlns:render="{RENDER_NS}"
      xmlns:groups="{GROUPS_NS}"
      level="3" version="2"
      layout:required="false" render:required="false" groups:required="false">
  <model id="kinetic_core" metaid="meta_model">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" metaid="meta_A" compartment="cell" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" metaid="meta_B" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants>
          <speciesReference id="sr_A" species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference id="sr_B" species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <layout:listOfLayouts>
      <layout:layout layout:id="main_layout" layout:name="Main Diagram">
        <layout:dimensions layout:width="640" layout:height="480"/>
        <layout:listOfCompartmentGlyphs>
          <layout:compartmentGlyph layout:id="cg_cell" layout:compartment="cell">
            <layout:boundingBox>
              <layout:position layout:x="0" layout:y="0"/>
              <layout:dimensions layout:width="600" layout:height="440"/>
            </layout:boundingBox>
          </layout:compartmentGlyph>
        </layout:listOfCompartmentGlyphs>
        <layout:listOfSpeciesGlyphs>
          <layout:speciesGlyph layout:id="sg_A" layout:species="A">
            <layout:boundingBox>
              <layout:position layout:x="40" layout:y="80"/>
              <layout:dimensions layout:width="90" layout:height="40"/>
            </layout:boundingBox>
          </layout:speciesGlyph>
          <layout:speciesGlyph layout:id="sg_B" layout:species="B">
            <layout:boundingBox>
              <layout:position layout:x="240" layout:y="80"/>
              <layout:dimensions layout:width="90" layout:height="40"/>
            </layout:boundingBox>
          </layout:speciesGlyph>
        </layout:listOfSpeciesGlyphs>
        <layout:listOfReactionGlyphs>
          <layout:reactionGlyph layout:id="rg_r1" layout:reaction="r1">
            <layout:listOfSpeciesReferenceGlyphs>
              <layout:speciesReferenceGlyph layout:id="srg_A"
                layout:speciesGlyph="sg_A" layout:speciesReference="sr_A"
                layout:role="substrate"/>
              <layout:speciesReferenceGlyph layout:id="srg_B"
                layout:speciesGlyph="sg_B" layout:speciesReference="sr_B"
                layout:role="product"/>
            </layout:listOfSpeciesReferenceGlyphs>
          </layout:reactionGlyph>
        </layout:listOfReactionGlyphs>
        <layout:listOfTextGlyphs>
          <layout:textGlyph layout:id="tg_A" layout:graphicalObject="sg_A"
                            layout:text="Species A">
            <layout:boundingBox>
              <layout:position layout:x="45" layout:y="90"/>
              <layout:dimensions layout:width="80" layout:height="20"/>
            </layout:boundingBox>
          </layout:textGlyph>
        </layout:listOfTextGlyphs>
        <render:listOfRenderInformation>
          <render:renderInformation render:id="local_style" render:name="Local Style"
                                    render:backgroundColor="#ffffff">
            <render:listOfColorDefinitions>
              <render:colorDefinition render:id="node_blue" render:value="#1e88e5"/>
            </render:listOfColorDefinitions>
            <render:listOfStyles>
              <render:style render:idList="sg_A">
                <render:g render:fill="node_blue"/>
              </render:style>
            </render:listOfStyles>
          </render:renderInformation>
        </render:listOfRenderInformation>
      </layout:layout>
      <render:listOfGlobalRenderInformation>
        <render:renderInformation render:id="global_style" render:name="Global Style"
                                  render:programName="BNG3Test" render:programVersion="1.0">
          <render:listOfColorDefinitions>
            <render:colorDefinition render:id="accent_red" render:value="#e53935"/>
          </render:listOfColorDefinitions>
          <render:listOfLineEndings>
            <render:lineEnding render:id="arrow_head">
              <layout:boundingBox>
                <layout:position layout:x="-10" layout:y="-5"/>
                <layout:dimensions layout:width="10" layout:height="10"/>
              </layout:boundingBox>
              <render:g/>
            </render:lineEnding>
          </render:listOfLineEndings>
          <render:listOfStyles>
            <render:style render:typeList="SPECIESGLYPH">
              <render:g render:stroke="accent_red"/>
            </render:style>
          </render:listOfStyles>
        </render:renderInformation>
      </render:listOfGlobalRenderInformation>
    </layout:listOfLayouts>
    <groups:listOfGroups>
      <groups:group groups:id="pathway_members" groups:name="Pathway"
                    groups:kind="classification" sboTerm="SBO:0000633">
        <groups:listOfMembers>
          <groups:member groups:id="m_A" groups:idRef="A"/>
          <groups:member groups:id="m_B" groups:metaIdRef="meta_B"/>
        </groups:listOfMembers>
      </groups:group>
    </groups:listOfGroups>
  </model>
</sbml>
"""


def test_layout_render_groups_extracted_structured_and_raw_into_model_and_result():
    libsbml = pytest.importorskip("libsbml")
    source_doc = libsbml.readSBMLFromString(FULL_METADATA_PACKAGES_SBML)
    assert source_doc.getNumErrors() == 0, source_doc.getErrorLog().toString()

    model = SBMLParser().parse(FULL_METADATA_PACKAGES_SBML)

    assert set(model.package_metadata) == {"layout", "render", "groups"}
    assert model.packageMetadata == model.package_metadata

    # Structured layout metadata
    layout_meta = model.package_metadata["layout"]
    assert layout_meta["namespace"] == LAYOUT_NS
    assert layout_meta["required"] is False
    assert len(layout_meta["layouts"]) == 1
    main_layout = layout_meta["layouts"][0]
    assert main_layout["id"] == "main_layout"
    assert main_layout["name"] == "Main Diagram"
    assert main_layout["dimensions"] == {"width": 640.0, "height": 480.0}
    assert main_layout["compartmentGlyphs"] == [
        {"id": "cg_cell", "compartment": "cell"}
    ]
    assert [g["species"] for g in main_layout["speciesGlyphs"]] == ["A", "B"]
    assert main_layout["reactionGlyphs"][0]["reaction"] == "r1"
    assert len(main_layout["reactionGlyphs"][0]["speciesReferenceGlyphs"]) == 2
    assert main_layout["textGlyphs"][0]["text"] == "Species A"
    assert main_layout["localRenderInformationIds"] == ["local_style"]
    assert len(layout_meta["rawXml"]) == 1
    assert "main_layout" in layout_meta["rawXml"][0]

    # Structured render metadata (global + local)
    render_meta = model.package_metadata["render"]
    assert render_meta["namespace"] == RENDER_NS
    assert len(render_meta["globalRenderInformation"]) == 1
    assert render_meta["globalRenderInformation"][0]["id"] == "global_style"
    assert render_meta["globalRenderInformation"][0]["colorDefinitions"] == [
        {"id": "accent_red", "value": "#e53935"}
    ]
    assert render_meta["globalRenderInformation"][0]["lineEndings"] == ["arrow_head"]
    assert render_meta["globalRenderInformation"][0]["styleCount"] == 1
    assert len(render_meta["localRenderInformation"]) == 1
    assert render_meta["localRenderInformation"][0]["layoutId"] == "main_layout"
    assert render_meta["localRenderInformation"][0]["id"] == "local_style"
    assert render_meta["localRenderInformation"][0]["colorDefinitions"] == [
        {"id": "node_blue", "value": "#1e88e5"}
    ]
    assert render_meta["rawXml"]["standaloneGlobalXml"] == []
    assert len(render_meta["rawXml"]["globalXml"]) == 1
    assert len(render_meta["rawXml"]["localXml"]) == 1

    # Structured groups metadata
    groups_meta = model.package_metadata["groups"]
    assert groups_meta["namespace"] == GROUPS_NS
    assert len(groups_meta["groups"]) == 1
    group = groups_meta["groups"][0]
    assert group["id"] == "pathway_members"
    assert group["kind"] == "classification"
    assert group["sboTerm"] == "SBO:0000633"
    assert group["members"] == [
        {"id": "m_A", "idRef": "A"},
        {"id": "m_B", "metaIdRef": "meta_B"},
    ]
    assert len(groups_meta["rawXml"]) == 1

    # Informational warnings (never dropped)
    for pkg in ("layout", "render", "groups"):
        warning = next(
            w for w in model.import_warnings if w["category"] == f"package:{pkg}"
        )
        assert warning["severity"] == "info"
        assert "preserved non-kinetic metadata" in warning["message"]

    # Summary + compact BNGL comment payload + AtomizerResult exposure
    summary = source_metadata_summary(model)
    assert summary["preservedMetadataPackages"] == ["groups", "layout", "render"]

    compact = metadata_payload(model)
    assert compact["preservedMetadataPackages"] == ["groups", "layout", "render"]
    assert compact["preservedPackageCounts"] == {
        "layouts": 1,
        "globalRenderInformation": 1,
        "localRenderInformation": 1,
        "groups": 1,
    }

    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        FULL_METADATA_PACKAGES_SBML
    )
    assert result.success
    assert set(result.package_metadata) == {"layout", "render", "groups"}
    assert result.packageMetadata == result.package_metadata
    meta_line = next(
        line
        for line in result.bngl.splitlines()
        if line.startswith("# @sbml-metadata ")
    )
    comment_payload = json.loads(unquote(meta_line.split(" ", 2)[2]))
    assert comment_payload["preservedMetadataPackages"] == [
        "groups",
        "layout",
        "render",
    ]


def test_layout_render_groups_roundtrip_sbml_and_zero_kinetic_perturbation(tmp_path):
    pytest.importorskip("bionetgen._bionetgen_cpp")
    libsbml = pytest.importorskip("libsbml")
    roadrunner = pytest.importorskip("roadrunner")
    import bionetgen

    core_path = tmp_path / "core.xml"
    meta_path = tmp_path / "meta.xml"
    core_path.write_text(CORE_KINETIC_SBML, encoding="utf-8")
    meta_path.write_text(FULL_METADATA_PACKAGES_SBML, encoding="utf-8")

    core_model = bionetgen.from_sbml(str(core_path))
    meta_model = bionetgen.from_sbml(str(meta_path))

    # Zero kinetic / semantic perturbation
    assert bionetgen.semantic_equal(core_model, meta_model)
    assert set(meta_model.sbml_metadata["packageMetadata"]) == {
        "layout",
        "render",
        "groups",
    }

    sim_core = core_model.simulate(method="ode", t_end=4.0, n_steps=20)
    sim_meta = meta_model.simulate(method="ode", t_end=4.0, n_steps=20)
    expected_A = 10.0 * np.exp(-0.5 * np.asarray(sim_meta.time))
    expected_B = 10.0 - expected_A
    np.testing.assert_allclose(
        sim_meta.observables["A"], sim_core.observables["A"], rtol=0, atol=0
    )
    np.testing.assert_allclose(
        sim_meta.observables["B"], sim_core.observables["B"], rtol=0, atol=0
    )
    np.testing.assert_allclose(
        sim_meta.observables["A"], expected_A, rtol=1e-6, atol=1e-8
    )
    np.testing.assert_allclose(
        sim_meta.observables["B"], expected_B, rtol=1e-6, atol=1e-8
    )

    # Export SBML with native L3 package XML re-attachment
    exported_path = tmp_path / "exported.xml"
    meta_model.write_sbml(str(exported_path))
    exported_xml = exported_path.read_text(encoding="utf-8")

    # libSBML reads back layout, global/local render, and groups directly
    doc = libsbml.readSBMLFromString(exported_xml)
    assert doc.getNumErrors() == 0, doc.getErrorLog().toString()
    m = doc.getModel()
    layout_plugin = m.getPlugin("layout")
    assert layout_plugin is not None and layout_plugin.getNumLayouts() == 1
    lay = layout_plugin.getLayout(0)
    assert lay.getId() == "main_layout"
    assert lay.getNumSpeciesGlyphs() == 2
    assert lay.getNumReactionGlyphs() == 1
    assert lay.getNumTextGlyphs() == 1

    global_render_plugin = layout_plugin.getListOfLayouts().getPlugin("render")
    assert global_render_plugin is not None
    assert global_render_plugin.getListOfGlobalRenderInformation().size() == 1
    assert (
        global_render_plugin.getListOfGlobalRenderInformation().get(0).getId()
        == "global_style"
    )

    local_render_plugin = lay.getPlugin("render")
    assert local_render_plugin is not None
    assert local_render_plugin.getListOfLocalRenderInformation().size() == 1
    assert (
        local_render_plugin.getListOfLocalRenderInformation().get(0).getId()
        == "local_style"
    )

    groups_plugin = m.getPlugin("groups")
    assert groups_plugin is not None and groups_plugin.getNumGroups() == 1
    grp = groups_plugin.getGroup(0)
    assert grp.getId() == "pathway_members"
    assert grp.getKindAsString() == "classification"
    assert grp.getNumMembers() == 2

    # Independent RoadRunner simulation of exported SBML matches source kinetics
    rr = roadrunner.RoadRunner(exported_xml)
    rr.integrator.relative_tolerance = 1e-10
    rr.integrator.absolute_tolerance = 1e-12
    rr_traj = rr.simulate(times=sim_meta.time, selections=["time", "A", "B"])
    np.testing.assert_allclose(rr_traj[:, 1], expected_A, rtol=1e-6, atol=1e-8)
    np.testing.assert_allclose(rr_traj[:, 2], expected_B, rtol=1e-6, atol=1e-8)

    # Re-importing exported SBML recovers identical package metadata + payload
    source_parsed = SBMLParser().parse(FULL_METADATA_PACKAGES_SBML)
    roundtrip_parsed = SBMLParser().parse(exported_xml)
    assert roundtrip_parsed.source_metadata_payload == source_metadata_payload(
        source_parsed
    )
    assert roundtrip_parsed.package_metadata["layout"]["layouts"] == (
        source_parsed.package_metadata["layout"]["layouts"]
    )
    assert roundtrip_parsed.package_metadata["render"]["globalRenderInformation"] == (
        source_parsed.package_metadata["render"]["globalRenderInformation"]
    )
    assert roundtrip_parsed.package_metadata["render"]["localRenderInformation"] == (
        source_parsed.package_metadata["render"]["localRenderInformation"]
    )
    assert roundtrip_parsed.package_metadata["groups"]["groups"] == (
        source_parsed.package_metadata["groups"]["groups"]
    )

    # preserve_packages=False keeps bng:sourceMetadata channel without top-level XML,
    # and SBMLParser still recovers package_metadata from the annotation payload.
    opaque_only_path = tmp_path / "opaque_only.xml"
    meta_model.write_sbml(str(opaque_only_path), preserve_packages=False)
    opaque_xml = opaque_only_path.read_text(encoding="utf-8")
    assert "<layout:listOfLayouts" not in opaque_xml
    assert "<groups:listOfGroups" not in opaque_xml
    recovered = SBMLParser().parse(opaque_xml)
    assert recovered.package_metadata == source_parsed.package_metadata

    # attach_preserved_package_metadata is idempotent and skips SBML Level 2
    assert (
        attach_preserved_package_metadata(exported_xml, meta_model.sbml_metadata)
        == exported_xml
    )
    l2_stub = '<?xml version="1.0"?><sbml level="2" version="4"><model id="m"/></sbml>'
    assert (
        attach_preserved_package_metadata(l2_stub, meta_model.sbml_metadata) == l2_stub
    )


@pytest.mark.parametrize("version", ["0.1", "0.2"])
def test_layout_render_groups_preserved_through_bngir_roundtrip(tmp_path, version):
    pytest.importorskip("bionetgen._bionetgen_cpp")
    jsonschema = pytest.importorskip("jsonschema")
    import bionetgen

    meta_path = tmp_path / "meta.xml"
    meta_path.write_text(FULL_METADATA_PACKAGES_SBML, encoding="utf-8")
    model = bionetgen.from_sbml(str(meta_path))

    bngir_text = model.to_bngir(version=version)
    doc = json.loads(bngir_text)
    schema_path = (
        Path(__file__).parents[2]
        / "provenance"
        / "schemas"
        / f"bngir-{version}.schema.json"
    )
    jsonschema.validate(doc, json.loads(schema_path.read_text(encoding="utf-8")))
    assert set(doc["provenance"]["sbml_source_metadata"]["packageMetadata"]) == {
        "layout",
        "render",
        "groups",
    }

    restored = bionetgen.from_bngir(bngir_text)
    sim_orig = model.simulate(method="ode", t_end=2.0, n_steps=10)
    sim_restored = restored.simulate(method="ode", t_end=2.0, n_steps=10)
    np.testing.assert_allclose(
        sim_restored.observables["A"], sim_orig.observables["A"], rtol=1e-9, atol=1e-12
    )
    np.testing.assert_allclose(
        sim_restored.observables["B"], sim_orig.observables["B"], rtol=1e-9, atol=1e-12
    )
    if version == "0.1":
        assert bionetgen.semantic_equal(model, restored, version=version)
    assert restored.sbml_metadata == model.sbml_metadata

    roundtrip_sbml = tmp_path / f"from_bngir_{version}.xml"
    restored.write_sbml(str(roundtrip_sbml))
    xml_out = roundtrip_sbml.read_text(encoding="utf-8")
    assert "<layout:listOfLayouts" in xml_out
    assert "<render:listOfGlobalRenderInformation" in xml_out
    assert "<render:listOfRenderInformation" in xml_out
    assert "<groups:listOfGroups" in xml_out


def test_multi_full_domain_occur_gt_1_wildcard_and_partial_subset_refusal():
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="occur_gt_1_full_domain">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="Aany" compartment="cell" initialAmount="0"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="2">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="state_u"/>
              <multi:speciesFeatureValue multi:value="state_p"/>
              <multi:speciesFeatureValue multi:value="state_q"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:name="s" multi:occur="2">
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

    full = parse_multi_package(xml)
    assert full.executable is True
    assert full.species_patterns["Aany"] == "A(s_1,s_2)@cell"
    assert "Aany" in full.abstract_species_ids

    # Positive initial pool on an unconstrained wildcard must still fail closed (Multi §3.19)
    positive_ic = parse_multi_package(
        xml.replace('initialAmount="0"', 'initialAmount="5"')
    )
    assert positive_ic.executable is False
    assert any("positive initial pool" in w.message for w in positive_ic.warnings)

    # Proper subset of 2 out of 3 values must still fail closed
    partial = parse_multi_package(
        xml.replace('<multi:speciesFeatureValue multi:value="state_q"/>', "")
    )
    assert partial.executable is False
    assert any("multiple values" in w.message for w in partial.warnings)


def test_multi_locally_scoped_compartment_reference_resolves_per_parent_compartment():
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="scoped_comp_refs">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="sub1"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="sub2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="sub1" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
      <compartment id="sub2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A1" compartment="c1" initialAmount="1" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType"/>
      <species id="A2" compartment="c2" initialAmount="1" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r_c2" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A2" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="A2" stoichiometry="1" constant="true"
                            multi:compartmentReference="inside"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    model = SBMLParser().parse(xml)
    assert model.multi_executable is True
    assert model.multi_compartment_references == {
        "c1": {"inside": "sub1"},
        "c2": {"inside": "sub2"},
    }
    sct = build_species_composition_table(model)
    molecule_types = get_molecule_types(sct, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(model, sct, molecule_types, get_seed_species(sct, model))
    rule_line = next(line for line in bngl.splitlines() if "r_c2:" in line)
    # Species A2 belongs to c2, whose local "inside" points to sub2 (not c1's sub1)
    assert "@sub2:" in rule_line
    assert "@sub1:" not in rule_line


def test_multi_compartment_type_child_specialization_unique_vs_ambiguous():
    def make_xml(extra_sub_ref: str = "") -> str:
        return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="comp_type_child">
    <listOfCompartments>
      <compartment id="ct_cell" multi:isType="true">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="ref_nuc" multi:compartment="ct_nuc"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="ct_nuc" multi:isType="true"/>
      <compartment id="cell1" size="1" multi:isType="false" multi:compartmentType="ct_cell">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="ref_nuc1" multi:compartment="nuc1"/>
          {extra_sub_ref}
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="nuc1" size="1" multi:isType="false" multi:compartmentType="ct_nuc"/>
      <compartment id="nuc2" size="1" multi:isType="false" multi:compartmentType="ct_nuc"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="AB1" compartment="cell1" initialAmount="1" multi:speciesType="ABType"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="ct_cell"/>
      <multi:speciesType multi:id="BType" multi:name="B" multi:compartment="ct_nuc"/>
      <multi:speciesType multi:id="ABType" multi:name="AB" multi:compartment="ct_cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a" multi:speciesType="AType"/>
          <multi:speciesTypeInstance multi:id="b" multi:speciesType="BType"
                                     multi:compartmentReference="ref_nuc"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    unique = parse_multi_package(make_xml())
    assert unique.executable is True
    assert unique.species_patterns["AB1"] == "A()@cell1.B()@nuc1"

    ambiguous = parse_multi_package(
        make_xml(
            '<multi:compartmentReference multi:id="ref_nuc2" multi:compartment="nuc2"/>'
        )
    )
    assert ambiguous.executable is False
    assert any(
        "cannot unambiguously specialize nested compartmentType" in w.message
        for w in ambiguous.warnings
    )


def test_multi_binding_site_with_multiple_feature_types_fails_closed():
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="multi_feature_binding_site">
    <listOfSpecies>
      <species id="A0" initialAmount="1" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="f1" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="f1_a"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="f2" multi:component="site" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="f2_x"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="f1" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="f1_a" multi:name="a"/>
              <multi:possibleSpeciesFeatureValue multi:id="f1_b" multi:name="b"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="f2" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="f2_x" multi:name="x"/>
              <multi:possibleSpeciesFeatureValue multi:id="f2_y" multi:name="y"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:bindingSiteSpeciesType>
      <multi:speciesType multi:id="AType" multi:name="A">
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
        w.severity == "dropped" and "defines multiple speciesFeatureTypes" in w.message
        for w in result.warnings
    )


def test_multi_aliased_duplicate_outward_binding_site_fails_closed():
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}" level="3" version="1" multi:required="true">
  <model id="aliased_outward_dup">
    <listOfSpecies>
      <species id="A0" initialAmount="0" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="site" multi:bindingStatus="unbound"/>
          <multi:outwardBindingSite multi:component="siteIdx" multi:bindingStatus="bound"/>
        </multi:listOfOutwardBindingSites>
      </species>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="siteType" multi:name="site"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="site" multi:speciesType="siteType"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="siteIdx" multi:component="site"/>
        </multi:listOfSpeciesTypeComponentIndexes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

    result = parse_multi_package(xml)
    assert result.executable is False
    assert any(
        w.severity == "dropped" and "already listed via another alias" in w.message
        for w in result.warnings
    )
