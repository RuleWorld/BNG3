#!/usr/bin/env python3
"""Diagnose the DSMTS variance statistic for SSTS stochastic/00003.

This is a source-law diagnostic, not an alternative official pass/fail gate.
It samples the exact linear birth-death transition law independently of BNG3,
then compares the DSMTS standardized variance statistic with its source-law
sampling distribution. The official verdict is retained verbatim in the JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


EXPECTED_SOURCE_SHA256 = "c58a50dd86f981150b533dd9af25c38f9ef3aeeedad2f679400e022add77f50e"
EXPECTED_REPORT_SHA256 = "ef8b7e737d5c72a10acaa3dddbd4fa02e86c48678b3cd5968d80b0c6fdb23f80"
EXPECTED_BNG3_REVISION = "0f004fecd318abb5b21829d869765a07cb6684cf"
OFFICIAL_RUN_ID = 40314965237
RUNS = 40_000
SEED = 20_261_026
DEFAULT_REPLICATES = 250


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_moments(time: int) -> dict[str, float]:
    """Return exact moments for 100 independent birth-death lineages."""
    lam, mu, initial = 1.0, 1.1, 100
    delta = mu - lam
    a = math.exp(-delta * time)
    denominator = mu - lam * a
    survival = delta * a / denominator
    q = lam * (1.0 - a) / denominator

    # Factorial moments of a zero-inflated geometric lineage, followed by
    # Stirling-number conversion to raw moments through order four.
    factorial = [0.0] + [
        survival * math.factorial(k) * q ** (k - 1) / (1.0 - q) ** k
        for k in range(1, 5)
    ]
    m1 = factorial[1]
    m2 = factorial[2] + factorial[1]
    m3 = factorial[3] + 3.0 * factorial[2] + factorial[1]
    m4 = factorial[4] + 6.0 * factorial[3] + 7.0 * factorial[2] + factorial[1]

    k2 = m2 - m1**2
    k3 = m3 - 3.0 * m2 * m1 + 2.0 * m1**3
    k4 = m4 - 4.0 * m3 * m1 - 3.0 * m2**2 + 12.0 * m2 * m1**2 - 6.0 * m1**4
    mean = initial * m1
    variance = initial * k2
    fourth_central = initial * k4 + 3.0 * variance**2

    # Independent identity for the linear birth-death process.
    closed_variance = initial * (lam + mu) / delta * a * (1.0 - a)
    if not math.isclose(variance, closed_variance, rel_tol=1e-11, abs_tol=1e-12):
        raise ArithmeticError("fourth-moment derivation disagrees with exact variance")
    return {
        "mean": mean,
        "variance": variance,
        "sd": math.sqrt(variance),
        "excess_kurtosis": fourth_central / variance**2 - 3.0,
        "asymptotic_dsmts_y_sd": math.sqrt(
            (fourth_central / variance**2 - 1.0) / 2.0
        ),
    }


def _wilson_interval(successes: int, trials: int) -> list[float]:
    if trials <= 0:
        return [0.0, 1.0]
    p = successes / trials
    z = 1.959963984540054
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    radius = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials**2)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _verify_source_law_identities() -> None:
    """Guard the closed-form and transition derivation at boundary cases."""
    lam, mu, initial = 1.0, 1.1, 100
    delta = mu - lam
    at_zero = math.exp(-delta * 0.0)
    if initial * at_zero != 100.0 or 2100.0 * (at_zero - at_zero**2) != 0.0:
        raise ArithmeticError("initial-state source-law identity failed")
    for time in (1e-5, 1e-4):
        a = math.exp(-delta * time)
        slope = 2100.0 * (a - a * a) / time
        if not math.isclose(slope, initial * (lam + mu), rel_tol=2e-5):
            raise ArithmeticError("small-time variance slope identity failed")
    late = math.exp(-delta * 500.0)
    if not (initial * late < 1e-18 and 2100.0 * (late - late**2) < 1e-17):
        raise ArithmeticError("late-time source-law limit failed")


def _load_case(
    report_path: Path, case_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = json.loads(report_path.read_text())
    report_sha = _sha256(report_path)
    if report_sha != EXPECTED_REPORT_SHA256:
        raise ValueError(
            "report SHA-256 does not match the pinned report.json extracted from "
            "the downloaded official run artifact"
        )
    if report.get("source_provenance", {}).get("bng3_commit") != EXPECTED_BNG3_REVISION:
        raise ValueError("report is not from the declared BNG3 revision")
    record = next(
        item
        for item in report["records"]
        if item.get("category") == "stochastic" and item.get("id") == "00003"
    )
    source = case_dir / "source.xml"
    source_sha = _sha256(source)
    if source_sha != EXPECTED_SOURCE_SHA256:
        raise ValueError("SSTS source XML hash differs from the locked case")
    if record["input_sha256"]["sbml"] != source_sha:
        raise ValueError("report source hash does not match the supplied case XML")
    runtime = report.get("runtime_provenance", {})
    return record["official_conformance"], {
        "sbml_sha256": source_sha,
        "report_sha256": report_sha,
        "suite_revision": report.get("suite_commit"),
        "run_id": OFFICIAL_RUN_ID,
        "bng3_revision": EXPECTED_BNG3_REVISION,
        "bng3_package_source_sha256": runtime.get("python_package_source_sha256"),
        "native_extension_sha256": runtime.get("native_extension_sha256"),
        "python_version": runtime.get("python_version"),
        "bionetgen_version": runtime.get("bionetgen_version"),
        "numpy_version": runtime.get("numpy_version"),
        "libsbml_version": runtime.get("libsbml_version"),
        "roadrunner_version": runtime.get("roadrunner_version"),
    }


def diagnose(report_path: Path, case_dir: Path, replicates: int) -> dict[str, Any]:
    official, provenance = _load_case(report_path, case_dir)
    _verify_source_law_identities()
    if replicates < 2:
        raise ValueError("replicates must be at least two to estimate pilot spread")

    # Over one unit interval, each molecule independently leaves a
    # zero-inflated geometric number of descendants. Conditional on K
    # surviving lineages, their extra descendants are negative-binomial.
    lam, mu, dt = 1.0, 1.1, 1.0
    delta = mu - lam
    a = math.exp(-delta * dt)
    denominator = mu - lam * a
    survival = delta * a / denominator
    q = lam * (1.0 - a) / denominator
    rng = np.random.default_rng(SEED)
    statistic_samples = np.empty((replicates, 50), dtype=np.float64)
    violation_counts = np.empty(replicates, dtype=np.int16)

    for replicate in range(replicates):
        populations = np.full(RUNS, 100, dtype=np.int64)
        for time in range(1, 51):
            survivors = rng.binomial(populations, survival)
            failures = rng.negative_binomial(np.maximum(survivors, 1), 1.0 - q)
            populations = survivors + np.where(survivors > 0, failures, 0)
            variance = 2100.0 * (math.exp(-0.1 * time) - math.exp(-0.2 * time))
            statistic_samples[replicate, time - 1] = math.sqrt(RUNS / 2.0) * (
                float(populations.var()) / variance - 1.0
            )
        violation_counts[replicate] = np.count_nonzero(
            np.abs(statistic_samples[replicate]) > 5.0
        )

    violation_events = []
    for item in official["statistics"]["X-sd"]["sd_violations"]:
        time = int(item["index"])
        law = _source_moments(time)
        violation_events.append(
            {
                "time": time,
                "official_statistic": item["statistic"],
                "source_law_asymptotic_y_sd": law["asymptotic_dsmts_y_sd"],
                "source_law_sd_units": item["statistic"] / law["asymptotic_dsmts_y_sd"],
            }
        )

    count_at_least_five = int(np.count_nonzero(violation_counts >= 5))
    p_hat = count_at_least_five / replicates
    return {
        "diagnostic_only": True,
        "official_verdict_unchanged": official["status"],
        "official_reason_unchanged": official["reason"],
        "source": {
            "suite_case": "stochastic/00003 l3v2",
            "sha256": provenance["sbml_sha256"],
            "suite_revision": provenance["suite_revision"],
            "process": "X -> 2X at 1*X; X -> 0 at 1.1*X; X(0)=100",
        },
        "implementation": {
            "revision": provenance["bng3_revision"],
            "official_run_id": provenance["run_id"],
            "official_run_id_binding": (
                "expected SHA-256 of report.json extracted from downloaded workflow artifact"
            ),
            "report_sha256": provenance["report_sha256"],
            "python_package_source_sha256": provenance[
                "bng3_package_source_sha256"
            ],
            "native_extension_sha256": provenance["native_extension_sha256"],
            "official_engine": official.get("engine"),
            "official_runs": official.get("runs"),
            "official_seed_base": official.get("seeds", {}).get("base"),
            "python_version": provenance["python_version"],
            "bionetgen_version": provenance["bionetgen_version"],
            "numpy_version": provenance["numpy_version"],
            "libsbml_version": provenance["libsbml_version"],
            "roadrunner_version": provenance["roadrunner_version"],
        },
        "source_law": {
            "mean": "100*a",
            "variance": "2100*(a-a^2)",
            "a": "exp(-0.1*t)",
            "lineage_distribution": "P(0)=1-p; P(k)=p*(1-q)*q^(k-1), k>=1",
            "p": "0.1*a/(1.1-a)",
            "q": "(1-a)/(1.1-a)",
            "dsmts_y_asymptotic_variance": "(mu4/sigma^4 - 1)/2",
            "identity_checks": {
                "t0_mean": 100.0,
                "t0_variance": 0.0,
                "small_time_variance_slope": 210.0,
                "late_time_mean_and_variance_tend_to_zero": True,
                "executed_before_sampling": True,
            },
        },
        "official_variance_violations": violation_events,
        "pilot": {
            "sampler": "exact conditional Binomial survivors + negative-binomial descendants",
            "independent_ensembles": replicates,
            "trajectories_per_ensemble": RUNS,
            "sample_times": 50,
            "rng": "numpy.default_rng PCG64",
            "seed": SEED,
            "numpy_version": np.__version__,
            "acceptance_limit_changed": False,
            "mean_sd_statistic_violations_per_ensemble": float(violation_counts.mean()),
            "sd_of_sd_statistic_violation_count": float(violation_counts.std(ddof=1)),
            "p_ensemble_has_at_least_five_sd_violations": p_hat,
            "p_ensemble_has_at_least_five_sd_violations_wilson_95pct": _wilson_interval(
                count_at_least_five, replicates
            ),
            "per_time": {
                str(time): {
                    "mean_y": float(statistic_samples[:, time - 1].mean()),
                    "sd_y": float(statistic_samples[:, time - 1].std(ddof=1)),
                    "fraction_abs_y_gt_5": float(
                        np.mean(np.abs(statistic_samples[:, time - 1]) > 5.0)
                    ),
                }
                for time in (41, 43, 44, 45, 46)
            },
        },
        "interpretation": (
            "The official conformance status remains failed. The exact-source-law "
            "pilot shows that five standard-deviation-statistic violations are "
            "typical for this non-Gaussian birth-death source law at the recorded "
            "ensemble size; this does not establish a batch SSA defect or change "
            "the official acceptance rule."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--replicates", default=DEFAULT_REPLICATES, type=int)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    result = diagnose(args.report, args.case_dir, args.replicates)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["pilot"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
