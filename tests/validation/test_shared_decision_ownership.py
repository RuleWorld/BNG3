"""Issue #178 bounded architecture check: one owner for the general-energy gate."""

from __future__ import annotations

from pathlib import Path

from tests.validation.shared_decision_ownership import (
    duplicated_gate_readers,
    has_single_owner,
    rejects_duplicated_decision,
)

ROOT = Path(__file__).resolve().parents[2]


def test_general_energy_gate_has_one_owner():
    assert has_single_owner(ROOT), (
        "general-energy capability decision is not single-owned; "
        f"duplicated readers: {duplicated_gate_readers(ROOT)}"
    )


def test_checker_rejects_a_duplicated_gate_decision():
    # Positive and negative fixtures are independent of BNG3 output.
    assert rejects_duplicated_decision(
        'bool enabled() { return std::getenv("BNG_NFSIM_GENERAL_ENERGY") != nullptr; }'
    )
    assert not rejects_duplicated_decision(
        "bool enabled() { return compile::energy::generalEnergyEnabled(); }"
    )
    assert not rejects_duplicated_decision(
        "// refuse barrier patterns: BNG_NFSIM_GENERAL_ENERGY is not set"
    )
