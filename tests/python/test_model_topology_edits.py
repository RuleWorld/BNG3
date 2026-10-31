"""In-place topology edits through the public Model API.

Each edited model must simulate exactly like a model written with the same
change in BNGL and loaded fresh, so every test compares the edited model with
an independently written source.
"""

from __future__ import annotations

import numpy as np
import pytest

import bionetgen

BASE = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_tot A()
  Molecules B_tot B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""

COMPARTMENTAL = """begin model
begin parameters
  k 0.5
end parameters
begin compartments
  C 3 1
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  @C:A() 10
end seed species
begin observables
  Molecules A_tot A()
  Molecules B_tot B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""


def _load(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return bionetgen.load(path)


def _assert_same(edited, fresh):
    left = edited.simulate(method="ode", t_end=4.0, n_steps=8)
    right = fresh.simulate(method="ode", t_end=4.0, n_steps=8)
    np.testing.assert_array_equal(np.asarray(left.time), np.asarray(right.time))
    assert set(left.observables) == set(right.observables)
    for name in right.observables:
        np.testing.assert_allclose(
            np.asarray(left.observables[name]),
            np.asarray(right.observables[name]),
            rtol=1e-12,
            atol=0.0,
        )


def test_added_molecule_type_and_seed_species_match_fresh_source(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.add_molecule_type("C()")
    edited.add_seed_species("B()", 4)
    source = BASE.replace("  B()\nend molecule", "  B()\n  C()\nend molecule")
    source = source.replace("  A() 10\n", "  A() 10\n  B() 4\n")
    _assert_same(edited, _load(tmp_path, "fresh.bngl", source))
    result = edited.simulate(method="ode", t_end=4.0, n_steps=8)
    assert np.asarray(result.observables["B_tot"])[0] == pytest.approx(4.0)


def test_removed_seed_species_matches_fresh_source(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.add_seed_species("B()", 4)
    edited.remove_seed_species("B()")
    _assert_same(edited, _load(tmp_path, "fresh.bngl", BASE))


def test_seed_amount_edit_matches_fresh_source(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.set_seed_species_amount("A()", 25)
    fresh = _load(tmp_path, "fresh.bngl", BASE.replace("  A() 10\n", "  A() 25\n"))
    _assert_same(edited, fresh)


def test_added_compartment_and_moved_species_match_fresh_source(tmp_path):
    edited = _load(tmp_path, "comp.bngl", COMPARTMENTAL)
    edited.add_compartment("D", 3, 2)
    edited.move_species_to_compartment("A()", "D", from_compartment="C")
    edited.add_seed_species("B()", 5, compartment="C")
    source = COMPARTMENTAL.replace("  C 3 1\n", "  C 3 1\n  D 3 2\n")
    source = source.replace("  @C:A() 10\n", "  @D:A() 10\n  @C:B() 5\n")
    _assert_same(edited, _load(tmp_path, "fresh.bngl", source))


def test_edits_keep_parameter_overrides(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.set_parameter("k", 0.25)
    edited.add_seed_species("B()", 1)
    source = BASE.replace("  k 0.5\n", "  k 0.25\n")
    source = source.replace("  A() 10\n", "  A() 10\n  B() 1\n")
    _assert_same(edited, _load(tmp_path, "fresh.bngl", source))


def test_edit_restarts_from_the_edited_seeds(tmp_path):
    model = _load(tmp_path, "base.bngl", BASE)
    model.simulate(method="ode", t_end=4.0, n_steps=8)
    model.add_seed_species("B()", 4)
    result = model.simulate(method="ode", t_end=4.0, n_steps=8)
    assert np.asarray(result.observables["A_tot"])[0] == pytest.approx(10.0)
    assert np.asarray(result.observables["B_tot"])[0] == pytest.approx(4.0)


def test_failed_edits_leave_the_model_unchanged(tmp_path):
    model = _load(tmp_path, "base.bngl", BASE)
    before = model.to_bngl()
    with pytest.raises(ValueError):
        model.remove_seed_species("B()")
    with pytest.raises(ValueError):
        model.add_compartment("bad name", 3, 1)
    assert model.to_bngl() == before


def test_ambiguous_seed_species_requires_a_compartment(tmp_path):
    model = _load(tmp_path, "comp.bngl", COMPARTMENTAL)
    model.add_compartment("D", 3, 2)
    model.add_seed_species("A()", 5, compartment="D")
    with pytest.raises(ValueError, match="compartment="):
        model.remove_seed_species("A()")
    model.remove_seed_species("A()", compartment="D")
    source = COMPARTMENTAL.replace("  C 3 1\n", "  C 3 1\n  D 3 2\n")
    _assert_same(model, _load(tmp_path, "fresh.bngl", source))


def test_parameter_addition_and_removal_match_fresh_source(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.add_parameter("k2", 0.1)
    fresh_source = BASE.replace("  k 0.5\n", "  k 0.5\n  k2 0.1\n")
    _assert_same(edited, _load(tmp_path, "fresh.bngl", fresh_source))

    # Reject duplicate parameter name
    with pytest.raises(ValueError, match="already exists"):
        edited.add_parameter("k2", 0.2)

    # Remove parameter
    edited.remove_parameter("k2")
    _assert_same(edited, _load(tmp_path, "fresh2.bngl", BASE))

    # Refuse to remove nonexistent parameter
    with pytest.raises(ValueError, match="no parameter"):
        edited.remove_parameter("nonexistent")

    # Refuse to remove a parameter currently referenced by a rule
    with pytest.raises(ValueError, match="produced an invalid model"):
        edited.remove_parameter("k")


def test_reaction_rule_addition_and_removal_match_fresh_source(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.add_parameter("k_rev", 0.2)
    edited.add_reaction_rule("rev: B() -> A() k_rev")

    fresh_text = BASE.replace("  k 0.5\n", "  k 0.5\n  k_rev 0.2\n")
    fresh_text = fresh_text.replace(
        "  A() -> B() k\n", "  A() -> B() k\n  rev: B() -> A() k_rev\n"
    )
    _assert_same(edited, _load(tmp_path, "fresh.bngl", fresh_text))

    # Remove the rule by name
    edited.remove_reaction_rule("rev")
    edited.remove_parameter("k_rev")
    _assert_same(edited, _load(tmp_path, "fresh_base.bngl", BASE))

    # Refuse to remove nonexistent rule
    with pytest.raises(ValueError, match="no reaction rule"):
        edited.remove_reaction_rule("nonexistent_rule")


def test_observable_addition_and_removal_match_fresh_source(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.add_observable("AB_tot", "A() B()")

    fresh_text = BASE.replace(
        "  Molecules B_tot B()\n",
        "  Molecules B_tot B()\n  Molecules AB_tot A() B()\n",
    )
    _assert_same(edited, _load(tmp_path, "fresh.bngl", fresh_text))

    # Reject duplicate observable
    with pytest.raises(ValueError, match="already exists"):
        edited.add_observable("AB_tot", "A()")

    # Remove observable
    edited.remove_observable("AB_tot")
    _assert_same(edited, _load(tmp_path, "fresh_base.bngl", BASE))

    # Refuse nonexistent observable removal
    with pytest.raises(ValueError, match="no observable"):
        edited.remove_observable("nonexistent_obs")


def test_compartment_and_molecule_type_removal(tmp_path):
    edited = _load(tmp_path, "comp.bngl", COMPARTMENTAL)
    edited.add_compartment("Extra", 3, 5)
    source_with_extra = COMPARTMENTAL.replace(
        "  C 3 1\n", "  C 3 1\n  Extra 3 5.0\n"
    )
    _assert_same(edited, _load(tmp_path, "fresh_extra.bngl", source_with_extra))

    # Remove compartment
    edited.remove_compartment("Extra")
    _assert_same(edited, _load(tmp_path, "fresh_comp.bngl", COMPARTMENTAL))

    # Refuse removing compartment with species
    with pytest.raises(ValueError, match="still referenced"):
        edited.remove_compartment("C")

    # Add and remove unused molecule type
    edited.add_molecule_type("Dummy()")
    edited.remove_molecule_type("Dummy")
    _assert_same(edited, _load(tmp_path, "fresh_comp2.bngl", COMPARTMENTAL))

    # Refuse removing molecule type in use
    with pytest.raises(ValueError, match="still referenced"):
        edited.remove_molecule_type("A")


def test_function_addition_and_removal(tmp_path):
    edited = _load(tmp_path, "base.bngl", BASE)
    edited.add_function("2 * k", name="doubled_k")

    fresh_text = BASE.replace(
        "end observables\n",
        "end observables\nbegin functions\n  doubled_k() = 2 * k\nend functions\n",
    )
    _assert_same(edited, _load(tmp_path, "fresh.bngl", fresh_text))

    edited.remove_function("doubled_k")
    _assert_same(edited, _load(tmp_path, "fresh_base.bngl", BASE))


def test_topology_edits_invalidate_cached_network_and_crn_properties(tmp_path):
    model = _load(tmp_path, "base.bngl", BASE)
    assert len(model.reactions) == 1
    assert model._network is not None

    model.add_parameter("k_rev", 0.1)
    # Cached network must be invalidated immediately
    assert model._network is None

    model.add_reaction_rule("rev: B() -> A() k_rev")
    # Accessing reactions regenerates network
    assert len(model.reactions) == 2
    assert model.reactions[1].label.startswith("rev")


def test_legacy_bngmodel_compartments_and_add_parameter(tmp_path):
    model_path = tmp_path / "model_comp.bngl"
    model_path.write_text(COMPARTMENTAL)

    m = bionetgen.bngmodel(str(model_path))
    assert "compartments" in m.active_blocks
    assert "parameters" in m.active_blocks
    m.parameters.add_parameter("k_extra", 1.25)

    out_path = tmp_path / "out.bngl"
    m.write_model(str(out_path))
    out_text = out_path.read_text()
    assert "k_extra 1.25" in out_text
