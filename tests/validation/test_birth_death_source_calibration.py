"""The source-law calibration uses the exact linear birth-death transition."""

from __future__ import annotations

import math
import json

import pytest

from scripts.calibrate_linear_birth_death import (
    calibrate,
    moments,
    source_law_compatibility_status,
    transition_parameters,
)


def test_one_ancestor_transition_matches_exact_birth_death_moments():
    birth_rate, death_rate, interval = 1.0, 1.1, 0.7
    survival, geometric_success = transition_parameters(
        birth_rate, death_rate, interval
    )
    decay = math.exp(-(death_rate - birth_rate) * interval)
    transition_mean = survival / geometric_success
    transition_second_moment = (
        survival * (2 - geometric_success) / (geometric_success**2)
    )
    transition_variance = transition_second_moment - transition_mean**2
    exact_mean, exact_variance = moments(1, birth_rate, death_rate, interval)

    assert math.isclose(transition_mean, exact_mean, rel_tol=1e-12)
    assert math.isclose(transition_variance, exact_variance, rel_tol=1e-12)
    assert math.isclose(transition_mean, decay, rel_tol=1e-12)


def test_familywise_calibration_is_seed_reproducible_and_keeps_verdict_context():
    observed = [10.0, 9.0, 7.0]
    kwargs = dict(
        initial_count=10,
        birth_rate=1.0,
        death_rate=1.1,
        runs=100,
        start=0.0,
        duration=2.0,
        steps=2,
        mean_limit=5.0,
        sd_limit=5.0,
        observed_sd_thresholds={1: 7.0},
        replicates=20,
        seed=37,
    )
    result = calibrate(observed, observed, **kwargs)
    assert result == calibrate(observed, observed, **kwargs)
    json.dumps(result)
    assert result["observed_familywise_violations"] >= 0
    assert result["replicates_exceeding_all_observed_sd_thresholds"] <= 20
    assert result["source_law_max_statistic_monte_carlo_p_value"] >= 0
    assert result["source_law_compatibility_status_for_this_receipt"] in {
        "PASS",
        "FAIL",
        "INCONCLUSIVE",
    }
    assert result["ensemble_variance_estimator"] == (
        "population variance with denominator n (1/n)"
    )
    assert "does not establish simulator correctness" in result["interpretation"]


def test_source_law_adapter_rejects_nonzero_start_without_initial_distribution():
    with pytest.raises(ValueError, match="observation start=0"):
        calibrate(
            [10.0, 9.0, 7.0],
            [10.0, 9.0, 7.0],
            initial_count=10,
            birth_rate=1.0,
            death_rate=1.1,
            runs=100,
            start=1.0,
            duration=2.0,
            steps=2,
            mean_limit=5.0,
            sd_limit=5.0,
            replicates=20,
            seed=37,
        )


def test_source_law_compatibility_status_uses_whole_interval_at_alpha():
    assert source_law_compatibility_status((0.02, 0.08), 0.01) == "PASS"
    assert source_law_compatibility_status((0.001, 0.009), 0.01) == "FAIL"
    assert source_law_compatibility_status((0.005, 0.02), 0.01) == "INCONCLUSIVE"
