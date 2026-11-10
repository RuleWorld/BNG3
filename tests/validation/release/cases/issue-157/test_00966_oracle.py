"""Pure, independently derived checks for official SSTS semantic/00966."""

from pathlib import Path

import numpy as np
import pytest

from oracle_00966 import (
    ALPHA_FAMILYWISE,
    BLOCK_SIZE,
    BLOCKS_PER_RUN,
    FLIPS_PER_RUN,
    SEEDS,
    SourceContractError,
    check_trajectory,
    validate_source,
    validate_settings,
)

SOURCE = Path(__file__).with_name("semantic-00966-source.xml")


def test_official_source_contract_is_verified_by_libsbml():
    contract = validate_source(SOURCE)
    assert contract["event_count"] == 23
    assert contract["tie_pair"] == ["Rinc", "Qinc"]
    assert contract["initial_Q"] == 0
    assert contract["initial_R"] == 0
    assert contract["block_size"] == BLOCK_SIZE == 16


@pytest.mark.parametrize(
    "mutation",
    [
        "priority",
        "persistence",
        "event_id",
    ],
)
def test_source_contract_rejects_semantic_mutations(tmp_path, mutation):
    text = SOURCE.read_text(encoding="utf-8")
    if mutation == "priority":
        # Change only Qinc's priority while preserving parseable XML.
        marker = '<event id="Qinc"'
        start = text.index(marker)
        priority = text.index('<math xmlns="http://www.w3.org/1998/Math/MathML">', start)
        text = text[:priority] + text[priority:].replace(
            '<cn type="integer"> 10 </cn>', '<cn type="integer"> 11 </cn>', 1
        )
    elif mutation == "persistence":
        text = text.replace('persistent="false"', 'persistent="true"', 1)
    else:
        text = text.replace('id="Rinc"', 'id="Rinc-mutated"', 1)
    mutated = tmp_path / "mutated.xml"
    mutated.write_text(text, encoding="utf-8")
    with pytest.raises(SourceContractError):
        validate_source(mutated)


def test_predeclared_sample_budget_and_error_control_are_fixed():
    settings = validate_settings()
    assert settings["start"] == 0
    assert settings["duration"] == 1000
    assert settings["steps"] == 1000
    assert SEEDS == tuple(range(1, 17))
    assert FLIPS_PER_RUN == 100_000
    assert BLOCKS_PER_RUN == FLIPS_PER_RUN // BLOCK_SIZE == 6_250
    assert ALPHA_FAMILYWISE == 1e-6


def test_exact_binomial_acceptance_rejects_deterministic_tie_order():
    # A deterministic implementation always assigns each tie to Q. It must
    # fail both the total-Q test and at least one independently checked bin.
    result = {
        "time": np.arange(1001, dtype=float),
        "S": np.arange(1001, dtype=float),
        "Q": np.arange(1001, dtype=float),
        "R": np.zeros(1001, dtype=float),
        **{f"chi{k}": np.asarray([BLOCKS_PER_RUN if k == BLOCK_SIZE else 0.0]) for k in range(17)},
    }
    report = check_trajectory(result, seed=1)
    assert not report["passed"]
    assert "familywise_binomial" in report["failures"]


def test_source_derived_roundoff_bound_is_finite_and_small():
    contract = validate_source(SOURCE)
    assert 0 < contract["s_roundoff_bound"] < 2e-8
