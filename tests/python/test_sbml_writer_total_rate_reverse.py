"""The SBML writer must preserve finite-network TotalRate fluxes both ways.

A BNGL reaction rule with the ``TotalRate`` modifier omits the reaction-center
symmetry factor.  In BNG2 finite-network simulation it still multiplies the
reactant populations, and the modifier belongs to the rule, so **both**
directions of a reversible rule carry it.

The SBML writer used to recognise the modifier only in the forward direction.
The reverse reaction of a reversible ``TotalRate`` rule was therefore written
as an ordinary mass-action law: it gained a symmetry factor and lost the
source-rate annotation.  The writer now emits both reactant factors and an
absolute-flux annotation, so a reader does not apply those factors a second
time.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
import re

import pytest

SBML_NS = "{http://www.sbml.org/sbml/level3/version2/core}"
MATHML_NS = "{http://www.w3.org/1998/Math/MathML}"

REVERSIBLE_TOTAL_RATE = """begin parameters
    kf 1
    kr 2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    R: A() <-> B() kf, kr TotalRate
end reaction rules
begin observables
    Molecules A A()
    Molecules B B()
end observables
"""


def _written_sbml(tmp_path: Path) -> tuple[Path, str]:
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")

    model = cpp.parse_string(REVERSIBLE_TOTAL_RATE)
    network = cpp.generate_network(model, max_iter=10)
    output = tmp_path / "total-rate.xml"
    cpp.io.write_sbml(model, network, str(output))
    return output, network.num_species and str(network.num_species) or ""


def _reactions(path: Path) -> list[ET.Element]:
    root = ET.parse(path).getroot()
    return list(root.iter(SBML_NS + "reaction"))


def _species_ids_by_name(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        element.attrib.get("name", ""): element.attrib["id"]
        for element in root.iter(SBML_NS + "species")
    }


def test_the_reverse_direction_of_a_total_rate_rule_keeps_the_modifier(tmp_path):
    """Both directions of a reversible TotalRate rule are total rates."""

    output, _ = _written_sbml(tmp_path)
    reactions = _reactions(output)

    assert len(reactions) == 2
    for reaction in reactions:
        annotation = reaction.find(SBML_NS + "annotation")
        assert (
            annotation is not None
        ), f"reaction {reaction.attrib['id']} lost the bng:totalRate annotation"
        assert any(
            "totalRate" in (child.tag or "") for child in annotation
        ), f"reaction {reaction.attrib['id']} lost the bng:totalRate annotation"


def test_the_reverse_direction_of_a_total_rate_rule_serializes_reactant_flux(
    tmp_path,
):
    """The SBML law contains the finite-network reactant factor exactly once."""

    output, _ = _written_sbml(tmp_path)
    ids = _species_ids_by_name(output)
    reactant_id = ids["B()"]

    reverse = None
    for reaction in _reactions(output):
        reactants = reaction.find(SBML_NS + "listOfReactants")
        if reactants is None:
            continue
        referenced = {
            reference.attrib["species"]
            for reference in reactants.iter(SBML_NS + "speciesReference")
        }
        if referenced == {reactant_id}:
            reverse = reaction
            break

    assert reverse is not None, "the reverse reaction was not written"
    kinetic_law = reverse.find(SBML_NS + "kineticLaw")
    assert kinetic_law is not None
    referenced = {
        (element.text or "").strip() for element in kinetic_law.iter(MATHML_NS + "ci")
    }
    assert reactant_id in referenced
    annotation = reverse.find(SBML_NS + "annotation")
    assert annotation is not None
    assert any("absoluteFlux" in (element.tag or "") for element in annotation)


def test_absolute_flux_annotation_survives_sbml_reparse(tmp_path):
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    output, _ = _written_sbml(tmp_path)
    parsed = cpp.io.read_sbml(str(output))
    assert parsed["success"], parsed["error"]
    assert parsed["absolute_flux_reaction_count"] == 2


def test_legacy_total_rate_sbml_is_still_read_as_a_complete_flux(tmp_path):
    """Older exports lack bng:absoluteFlux but their SBML law is still full flux."""
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    output, _ = _written_sbml(tmp_path)
    legacy = tmp_path / "legacy-total-rate.xml"
    legacy.write_text(
        re.sub(r"^\s*<bng:absoluteFlux[^>]*/>\s*\n", "", output.read_text(), flags=re.M)
    )

    parsed = cpp.io.read_sbml(str(legacy))
    assert parsed["success"], parsed["error"]
    assert parsed["absolute_flux_reaction_count"] == 2


def test_the_written_total_rate_model_reproduces_the_generated_model(tmp_path):
    """The written SBML must integrate like the model it came from."""

    roadrunner = pytest.importorskip("roadrunner")
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen import BioNetGenModel

    model = cpp.parse_string(REVERSIBLE_TOTAL_RATE)
    network = cpp.generate_network(model, max_iter=10)
    output = tmp_path / "total-rate-parity.xml"
    cpp.io.write_sbml(model, network, str(output))

    result = BioNetGenModel(model).simulate(
        method="ode", t_start=0.0, t_end=1.0, n_steps=10, rtol=1e-9, atol=1e-12
    )
    series = dict(result.observables)
    times = list(result.time)

    ids = _species_ids_by_name(output)
    names = ["A()", "B()"]
    rr = roadrunner.RoadRunner(str(output))
    rr.integrator.setValue("relative_tolerance", 1e-9)
    rr.integrator.setValue("absolute_tolerance", 1e-12)
    rr.timeCourseSelections = ["time", *[ids[name] for name in names]]
    reference = rr.simulate(0.0, 1.0, 11)

    for index, name in enumerate(names):
        observable = name[:-2]
        expected = series[observable]
        actual = [row[index + 1] for row in reference]
        for position, value in enumerate(expected):
            assert abs(value - actual[position]) <= 1e-6 + 1e-6 * abs(
                actual[position]
            ), (
                f"{observable} differs at t={times[position]}: "
                f"{value} != {actual[position]}"
            )
