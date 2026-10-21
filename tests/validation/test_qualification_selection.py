"""The focused campaign selection of the integrated validation harness.

Every focused campaign flag must select exactly its own qualification and
exclude the others. A flag that excluded its own qualification produced an
empty campaign: the selected family then reported no check at all, and the
issue queue's plan pointed at a campaign that could not execute it.
"""

from __future__ import annotations

import pytest

from tests.validation import integrated
from tests.validation import integrated_extensions as extensions

QUALIFICATIONS = {
    "boundaries": "include_boundaries",
    "graph_identity": "include_graph_identity",
    "bngir_adversarial": "include_bngir_adversarial",
    "quantity_laws": "include_quantity_laws",
    "export_format_tier": "include_export_format_tier",
    "netrule_execution": "include_netrule_execution",
    "bngsim_boundary": "include_bngsim_boundary",
    "jax_backend_measurement": "include_jax_backend_measurement",
    "rate_law_contract": "include_rate_law_contract",
    "nfnext_slices": "include_nfnext_slices",
    "api_surface": "include_api_surface",
    "stochastic_parity": "include_stochastic_parity",
    "graph_identity_contract": "include_graph_identity_contract",
    "sbml_support_boundary": "include_sbml_support_boundary",
    "atomizer_symbol_resolution": "include_atomizer_symbol_resolution",
    "atomizer_reconstruction": "include_atomizer_reconstruction",
    "energy_qualification": "include_energy_qualification",
    "workload_profile": "include_workload_profile",
    "semantic_identity": "include_semantic_identity",
    "graph_differential": "include_graph_differential",
    "capability_inventory": "include_capability_inventory",
    "real_model_fixtures": "include_real_model_fixtures",
    "corpus_selection": "include_corpus_selection",
    "biomodels_hold": "include_biomodels_hold",
}


def _flags(**selected):
    return {name: name in selected for name in QUALIFICATIONS}


def test_the_flag_table_covers_every_qualification():
    # Every operation is either a qualification with its own focus flag, or one
    # of the two operations that are not qualifications.
    qualified = {name.replace("_", "-") for name in QUALIFICATIONS}
    assert set(extensions.OPERATIONS) - qualified == {
        "protocol",
        "nf-marginals",
    }


@pytest.mark.parametrize("name", sorted(QUALIFICATIONS))
def test_a_focused_flag_selects_exactly_its_own_qualification(name):
    selection = integrated.select_qualifications(_flags(**{name: True}))
    assert selection[QUALIFICATIONS[name]] is True
    for other, key in QUALIFICATIONS.items():
        if other == name:
            continue
        assert (
            selection[key] is False
        ), f"the {name} focused campaign also selected {other}"


def test_no_focused_flag_selects_every_qualification():
    selection = integrated.select_qualifications(_flags())
    assert all(selection.values())
    assert set(selection) == set(QUALIFICATIONS.values())


def test_the_selection_rejects_an_empty_flag_table():
    with pytest.raises(ValueError):
        integrated.select_qualifications({})
