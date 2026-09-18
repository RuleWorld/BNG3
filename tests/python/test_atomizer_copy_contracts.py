"""Copy contracts for modern and legacy Atomizer structure containers."""

from bionetgen.atomizer.modern import (
    Component as ModernComponent,
    Molecule as ModernMolecule,
    Species as ModernSpecies,
)
from bionetgen.atomizer.utils import smallStructures
from bionetgen.atomizer.utils import structures


def test_modern_component_copy_isolates_primitive_lists():
    original = ModernComponent("site", "site", bonds=[1], states=["P"])
    original.active_state = "P"

    copied = original.copy()

    assert copied.bonds == original.bonds
    assert copied.states == original.states
    assert copied.bonds is not original.bonds
    assert copied.states is not original.states
    assert copied.active_state == original.active_state

    copied.bonds.append(2)
    copied.states.append("U")

    assert original.bonds == [1]
    assert original.states == ["P"]


def test_modern_species_copy_isolates_lists_and_nested_components():
    original = ModernSpecies()
    original.bond_numbers = [1]
    original.bonds = [("A_site", "B_site")]
    molecule = ModernMolecule("A")
    molecule.components.append(ModernComponent("site", bonds=[1], states=["P"]))
    original.molecules.append(molecule)

    copied = original.copy()

    assert copied.bond_numbers is not original.bond_numbers
    assert copied.bonds is not original.bonds
    assert copied.molecules is not original.molecules
    assert copied.molecules[0].components is not original.molecules[0].components

    copied.bond_numbers.append(2)
    copied.bonds.append(("B_site", "C_site"))
    copied.molecules[0].components[0].states.append("U")

    assert original.bond_numbers == [1]
    assert original.bonds == [("A_site", "B_site")]
    assert original.molecules[0].components[0].states == ["P"]


def test_legacy_component_copy_preserves_and_isolates_lists():
    original = structures.Component("site")
    original.bonds = ["1"]
    original.states = ["P"]
    original.activeState = "P"

    copied = original.copy()

    assert copied.bonds == original.bonds
    assert copied.states == original.states
    assert copied.bonds is not original.bonds
    assert copied.states is not original.states
    assert copied.activeState == original.activeState

    copied.bonds.append("2")
    copied.states.append("U")

    assert original.bonds == ["1"]
    assert original.states == ["P"]


def test_legacy_molecule_copy_isolates_nested_components():
    original = structures.Molecule("A")
    component = structures.Component("site")
    component.bonds = ["1"]
    original.components.append(component)

    copied = original.copy()
    copied.components[0].bonds.append("2")

    assert original.components[0].bonds == ["1"]


def test_small_structures_component_copy_preserves_and_isolates_lists():
    original = smallStructures.Component("site", "site")
    original.bonds = ["1"]
    original.states = ["P"]
    original.activeState = "P"

    copied = original.copy()

    assert copied.bonds == original.bonds
    assert copied.states == original.states
    assert copied.bonds is not original.bonds
    assert copied.states is not original.states
    assert copied.activeState == original.activeState

    copied.bonds.append("2")
    copied.states.append("U")

    assert original.bonds == ["1"]
    assert original.states == ["P"]


def test_small_structures_species_copy_isolates_nested_components():
    original = smallStructures.Species()
    molecule = smallStructures.Molecule("A", "A")
    component = smallStructures.Component("site", "site")
    component.bonds = ["1"]
    molecule.components.append(component)
    original.molecules.append(molecule)

    copied = original.copy()
    copied.molecules[0].components[0].bonds.append("2")

    assert original.molecules[0].components[0].bonds == ["1"]
