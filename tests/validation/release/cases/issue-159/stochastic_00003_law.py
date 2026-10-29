"""Independent analytic law for official SSTS stochastic case 00003.

The model has X -> 2X at rate lambda * X and X -> 0 at rate mu * X, with
X(0)=100.  For one initial molecule, the transition distribution at time t is
zero-inflated geometric.  Its PGF is

    g_t(z) = p0 + (1-p0) (1-rho) z / (1-rho*z),

where p0 = mu(1-exp(-delta*t))/(mu-lambda*exp(-delta*t)),
rho = lambda(1-exp(-delta*t))/(mu-lambda*exp(-delta*t)), and
delta = mu-lambda.  The initial 100 lineages are independent, so cumulants
for X(t) are 100 times the one-lineage cumulants.

This module is a source-law oracle and diagnostic calibration only.  It does
not run BNG3 and cannot change the official SSTS verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LAMBDA = 1.0
MU = 1.1
INITIAL_COUNT = 100


@dataclass(frozen=True)
class Moments:
    mean: float
    variance: float
    fourth_central_moment: float

    @property
    def standard_deviation(self) -> float:
        return math.sqrt(self.variance)

    @property
    def kurtosis(self) -> float:
        return self.fourth_central_moment / (self.variance**2)

    @property
    def standardized_variance_statistic_factor(self) -> float:
        """Asymptotic Var(Y), where Y=sqrt(n/2)*(S²/σ²-1).

        The checker uses the normal-theory Var(Y)=1. For nonnormal source
        laws, the leading-order factor is (kurtosis-1)/2. This is a diagnostic
        scale, not a replacement acceptance band.
        """

        return (self.kurtosis - 1.0) / 2.0


def birth_death_moments(time: float) -> Moments:
    """Return exact first, second, and fourth central moments at ``time``."""

    if time < 0.0:
        raise ValueError("time must be nonnegative")

    delta = MU - LAMBDA
    decay = math.exp(-delta * time)
    denominator = MU - LAMBDA * decay
    p_zero = MU * (1.0 - decay) / denominator
    survival = 1.0 - p_zero
    rho = LAMBDA * (1.0 - decay) / denominator
    one_minus_rho = 1.0 - rho

    # Raw moments of a positive geometric random variable with
    # P(K=k)=(1-rho)*rho**(k-1), then multiplied by its survival mass.
    geometric_raw = (
        1.0 / one_minus_rho,
        (1.0 + rho) / one_minus_rho**2,
        (1.0 + 4.0 * rho + rho**2) / one_minus_rho**3,
        (1.0 + 11.0 * rho + 11.0 * rho**2 + rho**3) / one_minus_rho**4,
    )
    m1, m2, m3, m4 = (survival * value for value in geometric_raw)

    # Convert one-lineage raw moments to cumulants and add 100 independent
    # lineages.  The fourth central moment is kappa_4 + 3*kappa_2**2.
    kappa1 = m1
    kappa2 = m2 - m1**2
    kappa4 = m4 - 4.0 * m3 * m1 - 3.0 * m2**2 + 12.0 * m2 * m1**2 - 6.0 * m1**4
    mean = INITIAL_COUNT * kappa1
    variance = INITIAL_COUNT * kappa2
    fourth_cumulant = INITIAL_COUNT * kappa4
    fourth_central = fourth_cumulant + 3.0 * variance**2
    return Moments(mean, variance, fourth_central)
