"""Public CRN structure API checks against hand-derived stoichiometry."""

import pytest

from _extdep import require_extension

require_extension()
import bionetgen


def _load_model(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return bionetgen.load(path)


def test_reversible_conversion_exposes_native_order_and_signed_matrix(tmp_path):
    model = _load_model(
        tmp_path,
        "reversible.bngl",
        """
begin model
begin parameters
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
    A() <-> B() kf, kr
end reaction rules
end model
""",
    )

    assert [(species.index, species.name) for species in model.species] == [
        (0, "A()"),
        (1, "B()"),
    ]
    assert isinstance(model.species[0], bionetgen.CRNSpecies)
    assert isinstance(model.reactions[0], bionetgen.CRNReaction)
    assert [reaction.index for reaction in model.reactions] == [0, 1]
    assert all(reaction.label for reaction in model.reactions)
    assert [
        (reaction.reactants, reaction.products) for reaction in model.reactions
    ] == [((0,), (1,)), ((1,), (0,))]
    assert model.stoichiometric_matrix.dtype == "int64"
    assert model.stoichiometric_matrix.tolist() == [[-1, 1], [1, -1]]


def test_synthesis_and_degradation_have_opposite_unit_columns(tmp_path):
    model = _load_model(
        tmp_path,
        "source_sink.bngl",
        """
begin model
begin parameters
    ks 1
    kd 2
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    0 -> A() ks
    A() -> 0 kd
end reaction rules
end model
""",
    )

    assert [(species.index, species.name) for species in model.species] == [
        (0, "A()"),
    ]
    assert [
        (reaction.reactants, reaction.products) for reaction in model.reactions
    ] == [((), (0,)), ((0,), ())]
    assert model.stoichiometric_matrix.tolist() == [[1, -1]]


def test_repeated_reactant_occurrences_preserve_nonunit_coefficient(tmp_path):
    model = _load_model(
        tmp_path,
        "nonunit.bngl",
        """
begin model
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
begin reaction rules
    A() + A() -> B() k
end reaction rules
end model
""",
    )

    assert [(species.index, species.name) for species in model.species] == [
        (0, "A()"),
        (1, "B()"),
    ]
    assert [
        (reaction.reactants, reaction.products) for reaction in model.reactions
    ] == [((0, 0), (1,))]
    assert model.stoichiometric_matrix.tolist() == [[-2], [1]]


def test_empty_and_seed_only_networks_have_species_by_reaction_shape(tmp_path):
    empty = _load_model(tmp_path, "empty.bngl", "begin model\nend model\n")

    assert empty.species == ()
    assert empty.reactions == ()
    assert empty.stoichiometric_matrix.shape == (0, 0)
    assert empty.stoichiometric_matrix.dtype.kind in "iu"

    seed_only = _load_model(
        tmp_path,
        "seed_only.bngl",
        """
begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
end model
""",
    )
    assert [(species.index, species.name) for species in seed_only.species] == [
        (0, "A()"),
    ]
    assert seed_only.reactions == ()
    assert seed_only.stoichiometric_matrix.shape == (1, 0)
