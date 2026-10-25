from collections import OrderedDict

from bionetgen.atomizer.modern import SBMLCompartment, SBMLModel, SBMLRule, SBMLSpecies
from bionetgen.atomizer.modern import writer


def test_lowerable_species_rules_normalize_each_candidate_once(monkeypatch):
    count = 300
    model = SBMLModel(
        id="assignment_rule_scaling",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1))]),
        species=OrderedDict(
            (
                f"S{index}",
                SBMLSpecies(id=f"S{index}", compartment="cell"),
            )
            for index in range(count)
        ),
        rules=[
            SBMLRule(type="assignment", variable=f"S{index}", math="1")
            for index in range(count)
        ],
    )
    original = writer.standardize_name
    calls = 0

    def counted(value):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(writer, "standardize_name", counted)

    lowered = writer._lowerable_species_assignment_rules(model)

    assert list(lowered) == [f"S{index}" for index in range(count)]
    assert calls <= count
