"""Native mutation checks for the topology validation probe."""

import pytest

from tests.validation import integrated_protocol as protocol


@pytest.mark.parametrize(
    ("with_compartment", "ignored_edit"),
    [
        (False, None),
        (False, "set_seed_species_amount"),
        (False, "remove_seed_species"),
        (True, None),
        (True, "set_seed_species_amount"),
        (True, "remove_seed_species"),
        (True, "move_species_to_compartment"),
    ],
)
def test_topology_detector_rejects_an_inert_probe_edit_that_has_no_effect(
    tmp_path, monkeypatch, with_compartment, ignored_edit
):
    import bionetgen

    source = tmp_path / "source.bngl"
    source.write_text("""begin model
begin parameters
 k 1
end parameters
begin molecule types
 A()
 B()
end molecule types
begin seed species
 A() 10
end seed species
begin observables
 Molecules X A()
end observables
begin reaction rules
 A() -> B() k
end reaction rules
end model
""")
    if with_compartment:
        source.write_text(
            source.read_text()
            .replace(
                "begin molecule types",
                "begin compartments\n C 3 1\nend compartments\nbegin molecule types",
            )
            .replace(" A() 10", " @C:A() 10")
        )
    if ignored_edit is not None:
        monkeypatch.setattr(
            bionetgen.BioNetGenModel, ignored_edit, lambda *args, **kwargs: None
        )
    difference = protocol._topology_edit_contract(bionetgen, source, tmp_path)
    if ignored_edit is None:
        assert difference is None, difference
    else:
        assert difference is not None, ignored_edit
        assert difference["field"].startswith("topology.probe"), difference
