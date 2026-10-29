#!/usr/bin/env python3
"""Reproducible source-law calibration for SSTS stochastic case 00003.

This samples the exact conditional transition law of the linear birth–death
process, independently of BNG3. It estimates diagnostic behavior of the
official normal-theory SD statistic, not whether a BNG3 run passes SSTS.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

from stochastic_00003_law import INITIAL_COUNT, LAMBDA, MU, birth_death_moments

ENSEMBLES = 100
TRAJECTORIES = 40_000
SEED = 2_581_028
OUTPUT_STEPS = 50
STATISTIC_RANGE = (-5.0, 5.0)


def wilson_interval(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    half_width = (
        z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials**2)) / denominator
    )
    return [center - half_width, center + half_width]


def calibrate() -> dict[str, object]:
    delta = MU - LAMBDA
    transition_decay = math.exp(-delta)
    denominator = MU - LAMBDA * transition_decay
    p_zero = MU * (1.0 - transition_decay) / denominator
    p_survive = 1.0 - p_zero
    rho = LAMBDA * (1.0 - transition_decay) / denominator

    rng = np.random.Generator(np.random.PCG64(SEED))
    times = np.arange(1, OUTPUT_STEPS + 1, dtype=np.float64)
    expected_sd = np.asarray(
        [birth_death_moments(float(time)).standard_deviation for time in times]
    )
    violation_counts: list[int] = []
    has_run_of_five: list[bool] = []

    for _ in range(ENSEMBLES):
        population = np.full(TRAJECTORIES, INITIAL_COUNT, dtype=np.int32)
        sample_sd = np.empty(OUTPUT_STEPS, dtype=np.float64)

        for output_index in range(OUTPUT_STEPS):
            surviving_lineages = rng.binomial(population, p_survive)
            next_population = np.zeros_like(population)
            positive = surviving_lineages > 0
            # A surviving lineage has a positive geometric descendant count.
            # The sum of k such counts is k + NegativeBinomial(k, 1-rho).
            k = surviving_lineages[positive]
            next_population[positive] = rng.negative_binomial(k, 1.0 - rho) + k
            population = next_population
            sample_sd[output_index] = population.std(ddof=0)

        standardized_variance = math.sqrt(TRAJECTORIES / 2.0) * (
            sample_sd**2 / expected_sd**2 - 1.0
        )
        violations = np.logical_or(
            standardized_variance < STATISTIC_RANGE[0],
            standardized_variance > STATISTIC_RANGE[1],
        )
        violation_counts.append(int(violations.sum()))
        has_run_of_five.append(
            any(violations[i : i + 5].all() for i in range(OUTPUT_STEPS - 4))
        )

    count_array = np.asarray(violation_counts, dtype=np.int64)
    count_ge_five = int(np.count_nonzero(count_array >= 5))
    run_ge_five = int(sum(has_run_of_five))
    return {
        "purpose": "source-law diagnostic calibration only; not a BNG3 result or SSTS verdict",
        "source_model": {
            "process": "X -> 2X at lambda*X; X -> 0 at mu*X",
            "lambda": LAMBDA,
            "mu": MU,
            "initial_count": INITIAL_COUNT,
            "conditional_transition": "Binomial surviving lineages plus negative-binomial geometric descendants",
        },
        "randomness": {"generator": "numpy.random.PCG64", "seed": SEED},
        "budget": {
            "independent_ensembles": ENSEMBLES,
            "trajectories_per_ensemble": TRAJECTORIES,
            "output_steps_tested": OUTPUT_STEPS,
        },
        "statistic": {
            "formula": "sqrt(n/2) * (sample_sd^2 / exact_source_sd^2 - 1)",
            "official_range": list(STATISTIC_RANGE),
            "violation_count_per_ensemble": violation_counts,
        },
        "summary": {
            "ensembles_with_at_least_five_violations": count_ge_five,
            "fraction_with_at_least_five_violations": count_ge_five / ENSEMBLES,
            "wilson_95_interval_at_least_five": wilson_interval(
                count_ge_five, ENSEMBLES
            ),
            "ensembles_with_five_consecutive_violations": run_ge_five,
            "fraction_with_five_consecutive_violations": run_ge_five / ENSEMBLES,
            "wilson_95_interval_five_consecutive": wilson_interval(
                run_ge_five, ENSEMBLES
            ),
            "mean_violations_per_ensemble": float(count_array.mean()),
            "maximum_violations_in_an_ensemble": int(count_array.max()),
        },
        "scope": "The simulation checks only the sampled SD statistic at the 50 official integer output times. It does not test BNG3, other SSTS models, or a final-main revision.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON receipt path")
    args = parser.parse_args()
    report = calibrate()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
