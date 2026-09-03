"""Tests for duplicated validation fixtures and their source provenance."""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_canonical_model_fixture_matches_validation_fixture():
    """The validated cBNGL model must not drift from the canonical fixture."""

    canonical = REPO / "models" / "Motivating_example_cBNGL.bngl"
    validation = (
        REPO
        / "tests"
        / "validation"
        / "Validate"
        / "Motivating_example_cBNGL.bngl"
    )
    assert validation.read_bytes() == canonical.read_bytes()
