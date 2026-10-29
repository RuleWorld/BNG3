"""Prerequisite checks for the independent SSTS stochastic/00003 source law."""

import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from stochastic_00003_law import birth_death_moments


@pytest.mark.parametrize(
    ("time", "expected_mean", "expected_sd"),
    [
        (1.0, 90.48374180359595, 13.44708),
        (41.0, 1.657267541912, 5.85029),
        (50.0, 0.6737946999086565, 3.74891),
    ],
)
def test_exact_birth_death_moments_match_official_ssts_reference(
    time: float, expected_mean: float, expected_sd: float
):
    moments = birth_death_moments(time)

    assert moments.mean == pytest.approx(expected_mean, abs=5e-5)
    assert moments.standard_deviation == pytest.approx(expected_sd, abs=5e-5)


def test_late_time_sd_statistic_has_non_normal_source_law_scale():
    moments = birth_death_moments(41.0)

    # The checker treats Y=sqrt(n/2)*(S²/σ²-1) as unit-scale normal. Its
    # leading source-law variance is instead (kurtosis-1)/2 for a nonnormal
    # marginal; the exact birth-death marginal already yields about 19.66.
    assert moments.kurtosis == pytest.approx(40.326, abs=0.002)
    assert moments.standardized_variance_statistic_factor == pytest.approx(
        19.663, abs=0.002
    )


def test_reference_mean_and_variance_follow_closed_form():
    for time in (0.0, 1.0, 20.0, 41.0, 50.0):
        moments = birth_death_moments(time)
        decay = math.exp(-0.1 * time)
        expected_mean = 100.0 * decay
        expected_variance = 100.0 * (2.1 / 0.1) * decay * (1.0 - decay)

        assert moments.mean == pytest.approx(expected_mean, rel=2e-12)
        assert moments.variance == pytest.approx(expected_variance, rel=2e-10)
