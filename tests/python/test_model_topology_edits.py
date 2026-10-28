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
