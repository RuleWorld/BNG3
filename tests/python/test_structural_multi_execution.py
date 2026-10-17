"""Quantitative qualification of one fully specified Multi state-change class.

The independent core model has the same explicit species and reaction. Multi
only supplies their internal state structure; there are no wildcard species,
pattern expansion, delays, or package kinetic operators in this fixture.
"""

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from bionetgen.atomizer.modern import Atomizer, SBMLParser, source_metadata_payload

MULTI = "http://www.sbml.org/sbml/level3/version1/multi/version1"


def _state_change_fixture(volume):
    species = []
    for name, state, amount in (("Au", "u", 20), ("Ap", "p", 0)):
        species.append(f"""
          <species id="{name}" compartment="cell" initialAmount="{amount}"
                   hasOnlySubstanceUnits="true" boundaryCondition="false"
                   constant="false" multi:speciesType="AType">
            <multi:listOfSpeciesFeatures>
              <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
                <multi:listOfSpeciesFeatureValues>
                  <multi:speciesFeatureValue multi:value="{state}"/>
                </multi:listOfSpeciesFeatureValues>
              </multi:speciesFeature>
            </multi:listOfSpeciesFeatures>
          </species>""")
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI}" level="3" version="1" multi:required="true">
      <model id="multi_state_change">
        <notes><body xmlns="http://www.w3.org/1999/xhtml"><p>state qualification</p></body></notes>
        <listOfCompartments><compartment id="cell" size="{volume}" spatialDimensions="3"
          constant="true" multi:isType="false"/></listOfCompartments>
        <listOfSpecies>{''.join(species)}</listOfSpecies>
        <listOfParameters><parameter id="k" value="0.3" constant="true"/></listOfParameters>
        <listOfReactions><reaction id="phosphorylate" reversible="false" fast="false">
          <listOfReactants><speciesReference species="Au" stoichiometry="1" constant="true"/></listOfReactants>
          <listOfProducts><speciesReference species="Ap" stoichiometry="1" constant="true"/></listOfProducts>
          <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>Au</ci></apply>
          </math></kineticLaw>
        </reaction></listOfReactions>
        <multi:listOfSpeciesTypes><multi:speciesType multi:id="AType" multi:name="A"
          multi:compartment="cell">
          <multi:listOfSpeciesFeatureTypes>
            <multi:speciesFeatureType multi:id="state" multi:occur="1">
              <multi:listOfPossibleSpeciesFeatureValues>
                <multi:possibleSpeciesFeatureValue multi:id="u"/>
                <multi:possibleSpeciesFeatureValue multi:id="p"/>
              </multi:listOfPossibleSpeciesFeatureValues>
            </multi:speciesFeatureType>
          </multi:listOfSpeciesFeatureTypes>
        </multi:speciesType></multi:listOfSpeciesTypes>
      </model></sbml>"""


@pytest.mark.parametrize("volume", [0.5, 2])
@pytest.mark.parametrize("atomize", [False, True])
def test_multi_state_dynamics_quantities_metadata_and_core_roundtrip(
    atomize, volume, tmp_path
):
    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp

    import libsbml
    import roadrunner

    source = _state_change_fixture(volume)
    document = libsbml.readSBMLFromString(source)
    assert document.getNumErrors() == 0, document.getErrorLog().toString()
    parsed = SBMLParser().parse(source)
    assert parsed.multi_executable
    assert parsed.multi_species_patterns["Au"] != parsed.multi_species_patterns["Ap"]
    atomized = Atomizer(atomize=atomize, quiet_mode=True).atomize(source)
    assert atomized.success, atomized.error
    assert "state~u" in atomized.bngl and "state~p" in atomized.bngl
    native = cpp.parse_string(atomized.bngl)
    result = BioNetGenModel(native).simulate(method="ode", t_end=5, n_steps=20)
    # A fully specified internal-state decoration does not change this explicit
    # first-order core network. Remove only Multi declarations for RoadRunner.
    core = ET.fromstring(source)
    for parent in core.iter():
        for child in list(parent):
            if child.tag.startswith("{" + MULTI + "}"):
                parent.remove(child)
        for attribute in list(parent.attrib):
            if attribute.startswith("{" + MULTI + "}"):
                del parent.attrib[attribute]
    oracle = roadrunner.RoadRunner(ET.tostring(core, encoding="unicode"))
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    reference = oracle.simulate(times=result.time, selections=["time", "Au", "Ap"])
    expected_u = 20 * np.exp(-0.3 * np.asarray(result.time))
    for species, expected, column in (
        ("Au", expected_u, 1),
        ("Ap", 20 - expected_u, 2),
    ):
        actual = result.observables[atomized.observable_map[species]]
        np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-8)
        np.testing.assert_allclose(actual, reference[:, column], rtol=1e-6, atol=1e-8)
    network = cpp.generate_network(native)
    exported = tmp_path / "roundtrip.xml"
    payload = source_metadata_payload(parsed)
    assert payload
    cpp.io.write_sbml(native, network, str(exported), source_metadata=payload)
    reimport = SBMLParser().parse(exported.read_text())
    assert reimport.source_metadata_payload == payload
    roundtrip = roadrunner.RoadRunner(str(exported))
    roundtrip.integrator.relative_tolerance = 1e-10
    roundtrip.integrator.absolute_tolerance = 1e-12
    # Exported observables preserve source amount quantities at either non-unit volume.
    for species, column in (("Au", 1), ("Ap", 2)):
        observable = atomized.observable_map[species]
        roundtrip.resetAll()
        values = roundtrip.simulate(times=result.time, selections=["time", observable])
        np.testing.assert_allclose(
            values[:, 1], reference[:, column], rtol=1e-6, atol=1e-8
        )
