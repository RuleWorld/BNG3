import pytest

from bionetgen.atomizer.utils import smallStructures, structures


@pytest.mark.parametrize(
    ("component_type", "args"),
    [
        (structures.Component, ("site",)),
        (smallStructures.Component, ("site", 7)),
    ],
)
def test_legacy_component_copy_preserves_independent_states_and_bonds(
    component_type, args
):
    component = component_type(*args)
    component.bonds = ["1"]
    component.states = ["P"]
    component.activeState = "P"

    copied = component.copy()

    assert copied.bonds == ["1"]
    assert copied.states == ["P"]
    assert copied.activeState == "P"
    assert copied.bonds is not component.bonds
    assert copied.states is not component.states
    if hasattr(component, "idx"):
        assert copied.idx == component.idx

    copied.bonds.append("2")
    copied.states.append("U")
    assert component.bonds == ["1"]
    assert component.states == ["P"]


def test_structures_molecule_copy_avoids_random_hash_allocation(monkeypatch):
    molecule = structures.Molecule("M")
    component = structures.Component("site")
    component.bonds = ["1"]
    component.states = ["P"]
    molecule.components = [component]
    molecule.hash = b"stable-hash"

    def unexpected_random_allocation(*args, **kwargs):
        pytest.fail("copying a molecule must not allocate a random hash array")

    monkeypatch.setattr(structures.numpy.random, "rand", unexpected_random_allocation)

    copied = molecule.copy()

    assert copied is not molecule
    assert copied.hash == b"stable-hash"
    assert copied.components[0] is not component
    assert copied.components[0].bonds == ["1"]
    assert copied.components[0].states == ["P"]


def test_smallstructures_molecule_copy_preserves_metadata_without_new_identifier(
    monkeypatch,
):
    molecule = smallStructures.Molecule("M", 3)
    component = smallStructures.Component("site", 7)
    component.bonds = ["1"]
    component.states = ["P"]
    component.activeState = "P"
    molecule.components = [component]
    molecule.compartment = "cell"
    molecule.trueName = "original-name"
    molecule.uniqueIdentifier = 2468

    def unexpected_identifier(*args, **kwargs):
        pytest.fail("copying a molecule must not allocate a new identifier")

    monkeypatch.setattr(smallStructures, "randint", unexpected_identifier)

    copied = molecule.copy()

    assert copied is not molecule
    assert copied.name == "M"
    assert copied.idx == 3
    assert copied.compartment == "cell"
    assert copied.trueName == "original-name"
    assert copied.uniqueIdentifier == 2468
    assert copied.components[0] is not component
    assert copied.components[0].bonds == ["1"]
    assert copied.components[0].states == ["P"]
    assert copied.components[0].activeState == "P"
