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
    "graph-identity": "include_graph_identity",
    "bngir-adversarial": "include_bngir_adversarial",
    "quantity-laws": "include_quantity_laws",
    "export-format-tier": "include_export_format_tier",
    "netrule-execution": "include_netrule_execution",
    "bngsim-boundary": "include_bngsim_boundary",
    "jax-backend-measurement": "include_jax_backend_measurement",
    "rate-law-contract": "include_rate_law_contract",
    "nfnext-slices": "include_nfnext_slices",
    "api-surface": "include_api_surface",
    "stochastic-parity": "include_stochastic_parity",
    "graph-identity-contract": "include_graph_identity_contract",
    "sbml-support-boundary": "include_sbml_support_boundary",
    "atomizer-symbol-resolution": "include_atomizer_symbol_resolution",
    "atomizer-reconstruction": "include_atomizer_reconstruction",
}


def _flags(**selected):
    return {name: name in selected for name in QUALIFICATIONS}


def test_the_flag_table_covers_every_qualification():
    assert set(QUALIFICATIONS) == set(extensions.OPERATIONS) - {
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
