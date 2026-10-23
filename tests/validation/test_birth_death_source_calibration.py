"""The source-law calibration uses the exact linear birth-death transition."""

from __future__ import annotations

import math
import json

import pytest

from scripts.calibrate_linear_birth_death import (
    analysis_design_description,
    calibrate,
    moments,
    source_law_compatibility_status,
    transition_parameters,
    validate_preregistration,
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


def test_heldout_analysis_label_distinguishes_preregistered_from_retrospective():
    assert "statistic was selected after" in analysis_design_description(
        "retrospective"
    )
    heldout = analysis_design_description("preregistered-heldout")
    assert "registered before that report" in heldout
    with pytest.raises(ValueError, match="unknown analysis design"):
        analysis_design_description("after-the-fact")


def test_preregistered_mode_validates_source_and_all_frozen_run_settings():
    from copy import deepcopy
    from pathlib import Path

    prereg_path = (
        Path(__file__).parents[2]
        / "provenance/sbml-campaign/stochastic-linear-birth-death-preregistration.json"
    )
    preregistration = json.loads(prereg_path.read_text())
    official = {
        "engine": "cpu:batch",
        "runs": 40000,
        "start": 0.0,
        "duration": 50.0,
        "steps": 50,
        "seeds": {"base": 2000000},
        "mean_range": [-3, 3],
        "sd_range": [-5, 5],
        "case_error_rate": 0.001,
    }
    arguments = {
        "preregistration_sha256": "7950ae79dc71bc5bf4ce0b2394fbffa8dbc0e9450b56cae4cb7ffefa170b1fe1",
        "category": "stochastic",
        "case_id": "00003",
        "source_model_sha256": preregistration["source_validation"][
            "source_model_sha256"
        ],
        "initial_count": 100,
        "birth_rate": 1.0,
        "death_rate": 1.1,
        "official": official,
        "report_seed_base": 2000000,
        "replicates": 1000,
        "source_law_seed": 20261024,
    }
    validate_preregistration(preregistration, **arguments)

    with pytest.raises(ValueError, match="registered lock"):
        validate_preregistration(
            preregistration, **{**arguments, "preregistration_sha256": "wrong"}
        )

    altered = deepcopy(preregistration)
    altered["decision"]["familywise_alpha"] = 0.05
    with pytest.raises(ValueError, match="diagnostic alpha"):
        validate_preregistration(altered, **arguments)

    altered = deepcopy(preregistration)
    altered["decision"]["monte_carlo_p_value"] = "unlocked rule"
    with pytest.raises(ValueError, match="Monte Carlo tail rule"):
        validate_preregistration(altered, **arguments)

    altered = deepcopy(preregistration)
    altered["engine_run"]["runs"] = 20000
    with pytest.raises(ValueError, match="engine runs"):
        validate_preregistration(altered, **arguments)

    with pytest.raises(ValueError, match="model hash"):
        validate_preregistration(
            preregistration, **{**arguments, "source_model_sha256": "wrong"}
        )
