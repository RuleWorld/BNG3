"""Focused contracts for the maintained engine routes (issues #149, #150).

The campaign qualification lives in
``tests/validation/integrated_engine_routes.py``.  These tests are the
focused, offline part: the NFcore2 route is contained and not promoted, the
population-map model is refused by the NFsim route, and the hybrid model
generator produces the hybrid model without an execution artefact.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.validation import integrated_engine_routes as routes

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"


def bng_cpp():
    candidate = BUILD / "cpp/bng_cpp"
    return candidate if candidate.is_file() else None


def test_the_check_identities_are_stable_and_unique():
    ids = routes.check_ids()
    assert len(ids) == len(set(ids))
    assert "nfcore2-route:containment" in ids
    assert "nfcore2-route:prototype-parity" in ids
    assert "nfcore2-route:disposition" in ids
    assert "population-map:storage-not-execution" in ids
    assert "population-map:hybrid-generation" in ids
    assert "population-map:execution-refinement-refusal" in ids


def test_the_nfcore2_route_is_recorded_as_contained_and_not_promoted():
    assert routes.NF_CORE2_DISPOSITION == "contained-prototype-not-promoted"
    assert not any("nfcore" in method.lower() for method in routes.PUBLIC_METHODS)


def test_the_public_method_set_is_the_supported_one():
    import bionetgen

    assert set(routes.PUBLIC_METHODS) == set(bionetgen._MODERN_METHODS)


def test_the_population_map_model_states_a_map_and_a_rule():
    source = routes.POPULATION_MAP_MODEL
    assert "begin population maps" in source
    assert "A() -> A_pop()" in source
    assert "begin reaction rules" in source


@pytest.mark.slow
def test_a_model_that_stores_a_population_map_is_not_executed(tmp_path):
    problems, message = routes._population_map_refusal(tmp_path)
    assert not problems
    assert "population map" in message
    assert "not implemented" in message or "cannot execute" in message


@pytest.mark.slow
def test_the_hybrid_generator_produces_the_model_and_no_simulation_artefact(tmp_path):
    binary = bng_cpp()
    if binary is None:
        pytest.skip("the CLI binary is not built in this tree")
    status, detail, _ = routes._hybrid_generation(tmp_path, binary)
    assert status == "PASS", detail
    assert not (tmp_path / "hybrid_hpp.gdat").is_file()
    assert not (tmp_path / "hybrid_hpp.cdat").is_file()


@pytest.mark.slow
def test_a_requested_hybrid_execution_is_refused_and_the_other_actions_run_on_the_hybrid_model(
    tmp_path,
):
    binary = bng_cpp()
    if binary is None:
        pytest.skip("the CLI binary is not built in this tree")
    status, detail, _ = routes._hybrid_execution_refusal(tmp_path, binary)
    assert status == "PASS", detail
    assert (tmp_path / "hybrid-write_hpp.xml").is_file()
    assert not (tmp_path / "hybrid-write_hpp.gdat").is_file()
    assert not (tmp_path / "hybrid-simulate_hpp.gdat").is_file()
