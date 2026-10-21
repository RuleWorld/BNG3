"""Focused contracts for the NFnext execution boundary (issue #148).

The campaign qualification lives in
``tests/validation/integrated_nfnext_boundary.py`` and consumes the artifact
the C++ component that owns the NFnext semantics exports
(``tests/architecture_contracts/nfnext/test_execution_boundary.cpp``).  These
tests are the focused, offline part: the family is stated once, the
component's artifact is required to state the same model, a missing component
is an untested route rather than a pass, and a drifted fixture fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.validation import integrated_nfnext_boundary as boundary

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_SOURCE = (
    ROOT / "tests/architecture_contracts/nfnext/test_execution_boundary.cpp"
)


def test_the_family_states_a_supported_model_with_seeds_observables_and_a_rate():
    for fixture in boundary.FIXTURES:
        source = boundary.fixture_source(fixture)
        assert "begin seed species" in source
        assert "begin observables" in source
        assert "Molecules U" in source and "Molecules P" in source
        assert "begin parameters" in source
        assert "begin reaction rules" in source
        assert f"A(x~u) {fixture['initial']}" in source
        assert f"k {fixture['rate']:g}" in source


def test_check_identities_are_stable_and_unique():
    ids = boundary.check_ids()
    assert len(ids) == len(set(ids))
    for fixture in boundary.FIXTURES:
        for name in boundary.CHECKS:
            assert f"{fixture['id']}:nfnext-boundary:{name}" in ids
    assert "nfnext-boundary:unsupported-refusals" in ids


def test_the_component_that_owns_the_nfnext_semantics_exports_the_artifact():
    assert PROTOTYPE_SOURCE.is_file()
    text = PROTOTYPE_SOURCE.read_text(encoding="utf-8")
    assert "lowerFromBioNetGen" in text
    assert "executeFromBioNetGen" in text
    assert "BNG3_NFNEXT_BOUNDARY_ARTIFACT" in text


def test_the_reference_expectation_is_the_independent_count_law_of_the_model():
    import math

    fixture = boundary.FIXTURES[0]
    assert boundary._reference_mean(fixture) == pytest.approx(
        fixture["initial"] * math.exp(-fixture["rate"] * 2.0)
    )
    # The law a wrong rate would produce must be a different law.
    assert boundary._alternative_mean(fixture) < boundary._reference_mean(fixture)


def test_a_missing_component_is_an_untested_route_and_never_a_pass(tmp_path):
    rows = boundary.run(tmp_path, prototype_binary=None)
    assert rows
    for row in rows:
        assert row["status"] == "NOT_TESTED"
        assert row["applicability"] == "nfnext-boundary-binary-unavailable"
        assert row["supported_execution"] is False


def test_a_failed_component_is_reported_as_a_failure(tmp_path):
    failing = tmp_path / "failing-prototype"
    failing.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failing.chmod(0o755)
    rows = boundary.run(tmp_path, prototype_binary=failing)
    assert rows
    for row in rows:
        assert row["status"] == "FAIL"
        assert "did not pass" in row["detail"] or "failed" in row["detail"]


def test_a_drifted_fixture_cannot_pass_against_the_component(tmp_path):
    # A component that reports a different model than the harness states is
    # a drift, not a pass.
    artifact = {
        "schema_version": 1,
        "fixtures": [
            {
                "id": "drifted",
                "source": "begin model\nend model\n",
                "initial": 1,
                "rate": 1.0,
                "sample_times": [0.0, 1.0],
                "columns": ["time", "U", "P"],
                "initial_row": [0.0, 1.0, 0.0],
                "seeds": [0, 1],
                "final_unphosphorylated": [1.0, 1.0],
                "observed_mean": 1.0,
                "observed_standard_error": 0.0,
                "reference_mean": 1.0,
                "alternative_mean": 0.0,
                "reason": "",
            }
        ],
        "refusals": [],
    }
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    rows = boundary.run(
        tmp_path / "run",
        prototype_binary=None,
    )
    # Without the component binary there is no observation at all.
    assert {row["status"] for row in rows} == {"NOT_TESTED"}
    # The drifted artifact would not match the harness fixture family.
    recorded = {entry["source"]: entry for entry in artifact["fixtures"]}
    for fixture in boundary.FIXTURES:
        assert boundary.fixture_source(fixture) not in recorded
