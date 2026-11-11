"""Independent source-RHS checks must reject rate and coordinate corruption."""

from pathlib import Path

import pytest

from tests.validation.sbml_source_coordinates import compare_source_rhs

SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="decay"><listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
<listOfSpecies><species id="A" compartment="c" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
<species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
<listOfParameters><parameter id="k" value="0.5" constant="true"/></listOfParameters>
<listOfReactions><reaction id="r" reversible="false"><listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw></reaction></listOfReactions></model></sbml>"""
NETWORK = """begin parameters
  1 rate 0.5
end parameters
begin species
  1 X() 2
  2 Y() 0
end species
begin reactions
  1 1 2 rate
end reactions
"""


def packet(tmp_path, network=NETWORK, source=SOURCE):
    xml, net = tmp_path / "source.xml", tmp_path / "model.net"
    xml.write_text(source)
    net.write_text(network)
    return xml, net


def test_source_rhs_matches_a_hand_derived_decay_network(tmp_path):
    xml, net = packet(tmp_path)
    result = compare_source_rhs(xml, net, {"A": 1, "B": 2})
    assert result["residuals"] == {"A": "0", "B": "0"}


@pytest.mark.parametrize(
    "before,after",
    [("rate 0.5", "rate 1"), ("X() 2", "X() 3"), ("1 1 2 rate", "1 1 0 rate")],
)
def test_source_rhs_rejects_semantically_corrupted_networks(tmp_path, before, after):
    xml, net = packet(tmp_path, NETWORK.replace(before, after))
    with pytest.raises(ValueError, match="initial amount|RHS mismatch"):
        compare_source_rhs(xml, net, {"A": 1, "B": 2})


def test_source_rhs_rejects_a_nonbijective_coordinate_map(tmp_path):
    xml, net = packet(tmp_path)
    with pytest.raises(ValueError, match="bijection"):
        compare_source_rhs(xml, net, {"A": 1, "B": 1})


def test_source_rhs_does_not_silently_fold_dynamic_compartments(tmp_path):
    xml, net = packet(
        tmp_path,
        source=SOURCE.replace('size="1" constant="true"', 'size="2" constant="false"'),
    )
    with pytest.raises(ValueError, match="unit constant compartment"):
        compare_source_rhs(xml, net, {"A": 1, "B": 2})


def test_source_rhs_rejects_unknown_rate_symbols(tmp_path):
    xml, net = packet(tmp_path, NETWORK.replace("rate 0.5", "rate missing"))
    with pytest.raises(ValueError, match="unresolved"):
        compare_source_rhs(xml, net, {"A": 1, "B": 2})
