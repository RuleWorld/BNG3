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


def test_delete_bond_matches_playground_component_pair_semantics():
    species = read_from_string("A(site!1).B(bind!1)")

    species.delete_bond(["A", "site"])

    assert species.molecules[0].get_component("site").bonds == []
    assert species.molecules[1].get_component("bind").bonds == ["1"]


def test_databases_and_states_expose_reference_containers():
    databases = Databases()
    databases.add2_label_dictionary(["B", "A"], "value")
    assert databases.get_label_dictionary()["A,B"] == "value"
    assert databases.get_raw_database() == {}
    assert databases.get_translator() == {}

    states = States("phosphorylation", "p1")
    assert states.name == "phosphorylation"
    assert states.idx == "p1"


def test_playground_structures_expose_camel_case_object_methods():
    from bionetgen.atomizer.modern import readFromString

    component = Component("site")
    component.addState("P")
    component.addBond(1)

    assert component.getName() == "site"
    assert component.getRuleStr() == "site!1~P"
    assert component.getTotalStr() == "site~P~0"
    assert component.toString() == "site!1~P"

    molecule = Molecule("A")
    molecule.addComponent(component)
    molecule.setCompartment("cell")

    assert molecule.getComponent("site") is component
    assert molecule.getBondNumbers() == [1]
    assert molecule.toString(True) == "A(site!1~P)@cell"

    species = Species()
    species.addMolecule(molecule)

    assert species.getMolecule("A") is molecule
    assert species.getMoleculeNames() == ["A"]
    assert species.getSize() == 1
    assert species.toString(True) == "A(site!1~P)@cell"
    assert str(readFromString("A(site~P)")) == "A(site~P)"
