"""SBML L3V2 Core 4.6: every species references a declared compartment.

https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf
"""

import xml.etree.ElementTree as ET

import pytest
from _extdep import require_extension

cpp = require_extension()
CORE = "{http://www.sbml.org/sbml/level3/version2/core}"


@pytest.mark.parametrize(
    "seed,rule,compartments,expected",
    [
        ("U() 3", "", "cell 3 2", {"cell", "default"}),
        ("", "0 -> U() 1", "cell 3 2", {"cell", "default"}),
        ("", "", "cell 3 2", {"cell"}),
        ("U() 3", "", "cell 3 2\ndefault 3 1", {"cell", "default"}),
    ],
    ids=["global-seed", "created-global-species", "all-located", "declared-default"],
)
def test_export_declares_every_species_compartment(
    tmp_path, seed, rule, compartments, expected
):
    model = cpp.parse_string(
        "begin model\nbegin compartments\n"
        + compartments
        + "\nend compartments\nbegin molecule types\nA()\nU()\n"
        "end molecule types\nbegin seed species\n@cell:A() 8\n"
        + seed
        + "\nend seed species\nbegin reaction rules\n"
        + rule
        + "\nend reaction rules\nend model\n"
    )
    network = cpp.generate_network(model, max_iter=5)
    output = tmp_path / "mixed.xml"
    cpp.io.write_sbml(model, network, str(output))
    root = ET.parse(output).getroot()
    declarations = list(root.iter(CORE + "compartment"))
    ids = [item.attrib["id"] for item in declarations]
    assert len(ids) == len(set(ids))
    assert set(ids) == expected
    species = list(root.iter(CORE + "species"))
    assert species
    assert {item.attrib["compartment"] for item in species} <= set(ids)
    if "default" in expected:
        implicit = next(item for item in declarations if item.attrib["id"] == "default")
        assert float(implicit.attrib["size"]) == 1.0

    # Exercise the downstream import/network consumer, not just XML syntax.
    from bionetgen.atomizer.modern import Atomizer

    restored = Atomizer(atomize=False, quiet_mode=True).atomize(output.read_text())
    assert restored.success, restored.error
    reconstructed = cpp.parse_string(restored.bngl)
    actual = cpp.generate_network(reconstructed, max_iter=5)
    assert actual.num_species == network.num_species
