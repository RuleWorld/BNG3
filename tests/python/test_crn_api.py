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


def test_complexes_and_rate_laws_for_reversible_network(tmp_path):
    model = _load_model(
        tmp_path,
        "binding.bngl",
        """
begin model
begin parameters
    kon 10.0
    koff 2.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 50
end seed species
begin reaction rules
    bind: A(b) + B(a) <-> A(b!1).B(a!1) kon, koff
end reaction rules
end model
""",
    )

    # 3 species: A(b), B(a), A(b!1).B(a!1)
    assert len(model.species) == 3
    # 2 unique complexes: {A, B} (indices 0, 1) and {AB} (index 2)
    assert len(model.complexes) == 2
    c0 = model.complexes[0]
    c1 = model.complexes[1]
    assert c0.index == 0
    assert c0.species == (0, 1)
    assert c1.index == 1
    assert c1.species == (2,)

    # 2 reactions: forward (c0 -> c1) and reverse (c1 -> c0)
    assert len(model.reactions) == 2
    r_fwd = model.reactions[0]
    r_rev = model.reactions[1]

    assert r_fwd.reactant_complex == 0
    assert r_fwd.product_complex == 1
    assert r_fwd.rate_law.type == "mass_action"
    assert r_fwd.rate_law.expression == "kon"
    assert r_fwd.rate_law.factor == 1.0
    assert r_fwd.rate_law.parameters == ("kon",)

    assert r_rev.reactant_complex == 1
    assert r_rev.product_complex == 0
    assert r_rev.rate_law.type == "mass_action"
    assert r_rev.rate_law.expression == "koff"
    assert r_rev.rate_law.factor == 1.0
    assert r_rev.rate_law.parameters == ("koff",)


def test_crn_export_and_json_serialization(tmp_path):
    model = _load_model(
        tmp_path,
        "model.bngl",
        """
begin model
begin parameters
    k 1.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    r1: A() -> B() k
end reaction rules
end model
""",
    )

    crn_dict = model.to_crn()
    assert crn_dict["version"] == "1.0"
    assert len(crn_dict["species"]) == 2
    assert len(crn_dict["complexes"]) == 2
    assert len(crn_dict["reactions"]) == 1
    assert crn_dict["reactions"][0]["reactant_complex"] == 0
    assert crn_dict["reactions"][0]["product_complex"] == 1
    assert crn_dict["reactions"][0]["rate_law"]["expression"] == "k"
    assert crn_dict["reactions"][0]["rate_law"]["parameters"] == ["k"]

    json_file = tmp_path / "crn.json"
    model.write_crn(json_file)
    import json

    loaded = json.loads(json_file.read_text(encoding="utf-8"))
    assert loaded == crn_dict
