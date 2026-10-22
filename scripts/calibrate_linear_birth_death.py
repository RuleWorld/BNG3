#!/usr/bin/env python3
"""Calibrate ensemble statistics under an exact subcritical birth-death law.

This is an independent source-law analysis tool, not an SBML verdict override.
It samples the exact Markov transition between equally spaced observation
times, preserving dependence between tests on the same trajectory. The model
has independent particles with per-particle birth rate ``birth_rate`` and
death rate ``death_rate``, with birth_rate < death_rate.

Example::

    python scripts/calibrate_linear_birth_death.py report.json \
        --category stochastic --case-id 00003 --initial-count 100 \
        --birth-rate 1 --death-rate 1.1 --replicates 1000 --seed 20261022

The JSON output estimates how often the source law itself produces at least
the observed number of mean/variance threshold violations. It leaves the
report's recorded PASS/FAIL status untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time
from typing import Any, Mapping

import numpy as np
from numpy.random import Generator, default_rng


def transition_parameters(birth_rate: float, death_rate: float, interval: float):
    """Return survival and geometric probabilities for one ancestor lineage."""

    if not (0 < birth_rate < death_rate and interval > 0):
        raise ValueError("require 0 < birth_rate < death_rate and interval > 0")
    decay = math.exp(-(death_rate - birth_rate) * interval)
    denominator = death_rate - birth_rate * decay
    survival = (death_rate - birth_rate) * decay / denominator
    geometric_success = (death_rate - birth_rate) / denominator
    return survival, geometric_success


def transition(
    rng: Generator,
    population: np.ndarray,
    birth_rate: float,
    death_rate: float,
    interval: float,
) -> np.ndarray:
    """Sample exact descendant counts after one interval for each trajectory."""

    survival, geometric_success = transition_parameters(
        birth_rate, death_rate, interval
    )
    surviving_lineages = rng.binomial(population, survival)
    descendants = np.zeros_like(population)
    alive = surviving_lineages > 0
    descendants[alive] = (
        rng.negative_binomial(surviving_lineages[alive], geometric_success)
        + surviving_lineages[alive]
    )
    return descendants


def moments(initial_count: int, birth_rate: float, death_rate: float, time: float):
    """Return the exact mean and variance of the linear branching process."""

    decay = math.exp(-(death_rate - birth_rate) * time)
    mean = initial_count * decay
    variance = (
        initial_count
        * (birth_rate + death_rate)
        / (death_rate - birth_rate)
        * decay
        * -math.expm1(-(death_rate - birth_rate) * time)
    )
    return mean, variance


def _wilson_interval(successes: int, trials: int, z: float = 1.959963984540054):
    """Return a two-sided Wilson interval for a binomial probability."""

    estimate = successes / trials
    z_squared = z * z
    denominator = 1 + z_squared / trials
    center = (estimate + z_squared / (2 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            estimate * (1 - estimate) / trials + z_squared / (4 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def source_law_compatibility_status(interval: tuple[float, float], alpha: float) -> str:
    """Classify this receipt under the selected familywise diagnostic rule."""

    if interval[0] > alpha:
        return "PASS"
    if interval[1] < alpha:
        return "FAIL"
    return "INCONCLUSIVE"


def calibrate(
    observed_mean: list[float],
    observed_sd: list[float],
    *,
    initial_count: int,
    birth_rate: float,
    death_rate: float,
    runs: int,
    start: float,
    duration: float,
    steps: int,
    mean_limit: float,
    sd_limit: float,
    observed_sd_thresholds: Mapping[int, float] | None = None,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    """Estimate the exact-law familywise count tail for reported statistics."""

    if min(initial_count, runs, steps, replicates) <= 0:
        raise ValueError("initial_count, runs, steps, and replicates must be positive")
    if start != 0.0:
        raise ValueError(
            "the source-law adapter currently requires observation start=0"
        )
    if len(observed_mean) != steps + 1 or len(observed_sd) != steps + 1:
        raise ValueError("observed mean/SD vectors must have steps + 1 entries")
    if not (0 < birth_rate < death_rate):
        raise ValueError("only subcritical linear birth-death laws are supported")
    if mean_limit <= 0 or sd_limit <= 0:
        raise ValueError("mean and standard-deviation limits must be positive")

    interval = duration / steps
    times = [start + index * interval for index in range(steps + 1)]
    observed_mean_z = []
    observed_sd_y = []
    for index, time in enumerate(times):
        mean, variance = moments(initial_count, birth_rate, death_rate, time)
        if variance == 0:
            observed_mean_z.append(0.0)
            observed_sd_y.append(0.0)
        else:
            observed_mean_z.append(
                math.sqrt(runs) * (observed_mean[index] - mean) / math.sqrt(variance)
            )
            observed_sd_y.append(
                math.sqrt(runs / 2) * (observed_sd[index] ** 2 / variance - 1)
            )
    observed_violations = sum(
        abs(value) > mean_limit for value in observed_mean_z[1:]
    ) + sum(abs(value) > sd_limit for value in observed_sd_y[1:])
    observed_max_familywise_statistic = max(
        max(abs(value) / mean_limit for value in observed_mean_z[1:]),
        max(abs(value) / sd_limit for value in observed_sd_y[1:]),
    )

    rng = default_rng(seed)
    familywise_exceedances = 0
    observed_joint_exceedances = 0
    maximum_violation_counts: list[int] = []
    maximum_familywise_statistics: list[float] = []
    observed_sd_thresholds = dict(observed_sd_thresholds or {})
    if any(index <= 0 or index > steps for index in observed_sd_thresholds):
        raise ValueError("observed SD threshold indices must be in [1, steps]")
    for _ in range(replicates):
        population = np.full(runs, initial_count, dtype=np.int64)
        violations = 0
        observed_sd_exceedances = 0
        maximum_statistic = 0.0
        for index, time in enumerate(times[1:], start=1):
            population = transition(rng, population, birth_rate, death_rate, interval)
            mean, variance = moments(initial_count, birth_rate, death_rate, time)
            mean_z = math.sqrt(runs) * (population.mean() - mean) / math.sqrt(variance)
            # Match the DSMTS harness statistic, which uses the 1/n ensemble
            # variance estimator returned by the batched samplers.
            sd_y = math.sqrt(runs / 2) * (population.var(ddof=0) / variance - 1)
            maximum_statistic = max(
                maximum_statistic,
                abs(mean_z) / mean_limit,
                abs(sd_y) / sd_limit,
            )
            violations += abs(mean_z) > mean_limit
            violations += abs(sd_y) > sd_limit
            if index in observed_sd_thresholds:
                observed_sd_exceedances += sd_y >= observed_sd_thresholds[index]
        maximum_violation_counts.append(int(violations))
        maximum_familywise_statistics.append(maximum_statistic)
        familywise_exceedances += int(violations >= observed_violations)
        observed_joint_exceedances += int(
            observed_sd_exceedances == len(observed_sd_thresholds)
        )

    interval_low, interval_high = _wilson_interval(familywise_exceedances, replicates)
    joint_interval_low, joint_interval_high = _wilson_interval(
        observed_joint_exceedances, replicates
    )
    max_statistic_exceedances = int(
        sum(
            simulated >= observed_max_familywise_statistic
            for simulated in maximum_familywise_statistics
        )
    )
    max_statistic_interval = _wilson_interval(max_statistic_exceedances, replicates)
    alpha = 0.01
    max_statistic_p_value = (max_statistic_exceedances + 1) / (replicates + 1)
    return {
        "source_law": "subcritical linear birth-death process",
        "initial_count": initial_count,
        "birth_rate": birth_rate,
        "death_rate": death_rate,
        "runs_per_ensemble": runs,
        "observation_start": start,
        "observation_duration": duration,
        "observation_steps": steps,
        "mean_statistic_limit": mean_limit,
        "variance_statistic_limit": sd_limit,
        "familywise_statistic": "max over 100 tests of |Z|/mean_limit and |Y|/sd_limit",
        "familywise_statistic_alpha": alpha,
        "observed_max_familywise_statistic": observed_max_familywise_statistic,
        "source_law_replicates_at_least_observed_max": max_statistic_exceedances,
        "source_law_max_statistic_tail_probability": (
            max_statistic_exceedances / replicates
        ),
        "source_law_max_statistic_tail_wilson_95_percent_interval": list(
            max_statistic_interval
        ),
        "source_law_max_statistic_monte_carlo_p_value": max_statistic_p_value,
        "source_law_compatibility_status_for_this_receipt": (
            source_law_compatibility_status(max_statistic_interval, alpha)
        ),
        "observed_familywise_violations": observed_violations,
        "source_law_replicates": replicates,
        "source_law_seed": seed,
        "ensemble_variance_estimator": "population variance with denominator n (1/n)",
        "replicates_with_at_least_observed_violations": familywise_exceedances,
        "estimated_familywise_probability": familywise_exceedances / replicates,
        "wilson_95_percent_interval": [interval_low, interval_high],
        "observed_sd_thresholds": {
            str(index): value for index, value in sorted(observed_sd_thresholds.items())
        },
        "replicates_exceeding_all_observed_sd_thresholds": observed_joint_exceedances,
        "estimated_probability_exceeding_all_observed_sd_thresholds": (
            observed_joint_exceedances / replicates
        ),
        "joint_threshold_wilson_95_percent_interval": [
            joint_interval_low,
            joint_interval_high,
        ],
        "maximum_violations_by_replicate": max(maximum_violation_counts, default=0),
        "observed_max_abs_mean_statistic": max(map(abs, observed_mean_z[1:])),
        "observed_max_abs_variance_statistic": max(map(abs, observed_sd_y[1:])),
        "interpretation": (
            "Source-law calibration only; the observed harness verdict is not "
            "changed and this does not establish simulator correctness."
        ),
    }


def _read_report_record(report_path: Path, category: str, case_id: str):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    record = next(
        (
            item
            for item in report.get("records", [])
            if str(item.get("category")) == category and str(item.get("id")) == case_id
        ),
        None,
    )
    if record is None:
        raise ValueError(f"report has no {category}/{case_id} record")
    official = record.get("official_conformance") or {}
    statistics = official.get("statistics") or {}
    variable = str(official.get("output_targets", {}).get("X", "X").split("_")[0])
    mean_stats = statistics.get(f"{variable}-mean")
    sd_stats = statistics.get(f"{variable}-sd")
    if not mean_stats or not sd_stats:
        candidates = [
            key.removesuffix("-mean") for key in statistics if key.endswith("-mean")
        ]
        if len(candidates) != 1:
            raise ValueError("select a source statistic with one unambiguous output")
        variable = candidates[0]
        mean_stats = statistics[f"{variable}-mean"]
        sd_stats = statistics[f"{variable}-sd"]
    return report, record, official, mean_stats, sd_stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--category", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--initial-count", required=True, type=int)
    parser.add_argument("--birth-rate", required=True, type=float)
    parser.add_argument("--death-rate", required=True, type=float)
    parser.add_argument("--replicates", type=int, default=1000)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report, record, official, mean_stats, sd_stats = _read_report_record(
        args.report, args.category, args.case_id
    )
    observed_sd_thresholds = {
        int(item["index"]): float(item["statistic"])
        for item in sd_stats.get("sd_violations", [])
    }
    started = time.perf_counter()
    result = calibrate(
        mean_stats["sample_mean"],
        sd_stats["sample_sd"],
        initial_count=args.initial_count,
        birth_rate=args.birth_rate,
        death_rate=args.death_rate,
        runs=int(official["runs"]),
        start=float(official["start"]),
        duration=float(official["duration"]),
        steps=int(official["steps"]),
        mean_limit=max(abs(float(bound)) for bound in official["mean_range"]),
        sd_limit=max(abs(float(bound)) for bound in official["sd_range"]),
        observed_sd_thresholds=observed_sd_thresholds,
        replicates=args.replicates,
        seed=args.seed,
    )
    result["wall_runtime_seconds"] = time.perf_counter() - started
    result.update(
        {
            "case": f"{args.category}/{args.case_id}",
            "analysis_design": (
                "retrospective compatibility diagnostic against one previously "
                "recorded engine ensemble; the statistic was selected after "
                "reviewing that report"
            ),
            "recorded_verdict": official["status"],
            "official_case_error_rate": official.get("case_error_rate"),
            "diagnostic_alpha_is_not_official_case_error_rate": True,
            "diagnostic_status_scope": (
                "receipt-scoped only; does not establish general simulator correctness"
            ),
            "source_report_sha256": hashlib.sha256(
                args.report.read_bytes()
            ).hexdigest(),
            "source_model_sha256": record.get("input_sha256", {}).get("sbml"),
            "source_report_commit": (report.get("source_provenance") or {}).get(
                "bng3_commit"
            ),
            "engine_ensemble": {
                "engine": official.get("engine"),
                "runs": official.get("runs"),
                "seeds": official.get("seeds"),
                "settings_sha256": official.get("settings_sha256"),
                "results_sha256": official.get("results_sha256"),
            },
            "analysis_script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "analysis_runtime": {
                "python_version": platform.python_version(),
                "numpy_version": np.__version__,
            },
            "sampling_method": (
                "exact equally spaced subcritical linear birth-death Markov "
                "transition: binomial surviving ancestors plus a negative-"
                "binomial number of additional descendants"
            ),
        }
    )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
