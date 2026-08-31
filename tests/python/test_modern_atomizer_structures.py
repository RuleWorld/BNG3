"""Source-derived tests for the remaining modern Atomizer structures."""

from __future__ import annotations

from bionetgen.atomizer.modern import (
    Component,
    Databases,
    Molecule,
    Species,
    States,
    read_from_string,
)


def test_component_hash_and_remove_components_match_reference_surface():
    component = Component("site")
    assert component.hash() == "site"

    molecule = Molecule("A")
    first = Component("first")
    second = Component("second")
    molecule.components = [first, second]
    molecule.remove_components([first])
    assert molecule.components == [second]


def test_extract_atomic_patterns_preserves_reaction_center_and_bond_context():
    species = read_from_string("A(site~P!1).B(bind!1)")

    result = species.extract_atomic_patterns("AddBond", "site", "bind")

    assert "A(site~P)" in result.atomic_patterns
    assert "A(site!1).B(bind!1)" in result.atomic_patterns
    assert "A(site!1).B(bind!1)" in result.reaction_center
    assert "A(site~P)" in result.context


def test_list_of_bonds_maps_internal_component_ids_to_public_names():
    species = Species()
    species.bonds = [("A_C1", "B_C2")]

    bonds = species.list_of_bonds(
        {"A": "Alpha", "B": "Beta", "A_C1": "left", "B_C2": "right"}
    )

    assert bonds == {
        "Alpha": {"left": [("Beta", "right")]},
        "Beta": {"right": [("Alpha", "left")]},
    }


def test_databases_and_states_expose_reference_containers():
    databases = Databases()
    databases.add2_label_dictionary(["B", "A"], "value")
    assert databases.get_label_dictionary()["A,B"] == "value"
    assert databases.get_raw_database() == {}
    assert databases.get_translator() == {}

    states = States("phosphorylation", "p1")
    assert states.name == "phosphorylation"
    assert states.idx == "p1"
