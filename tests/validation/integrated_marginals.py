"""Independent finite-population NFsim marginals for unimolecular source models.

Decay and two-state conversion have binomial A-count marginals. Means use a
Hoeffding bound over independent source Bernoulli trials; CDFs use the DKW
bound. A union budget covers both engines, all samples and selected cases.
This tests those marginals, not complete stochastic execution equivalence.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import campaign, contracts
from .integrated_cases import TIMES, expected_trajectory

CHECKS = ("sample-validity", "marginal-means", "binomial-cdf", "seed-spread")
ISSUES = (143, 146, 151, 167)


def binomial_mass(population, probability):
    if type(population) is not int or population < 1 or not 0 <= probability <= 1:
        raise ValueError("invalid binomial source parameters")
    return np.array(
        [
            math.comb(population, k)
            * probability**k
            * (1 - probability) ** (population - k)
            for k in range(population + 1)
        ],
        dtype=float,
    )


def _row(check, ok, detail, **evidence):
    return dict(
        check=check,
        status="PASS" if ok else "FAIL",
        detail=detail,
        related_issues=list(ISSUES),
        question="independent-binomial-marginals",
        **evidence,
    )


def assess_samples(samples, case, *, alpha=1e-6):
    if case["family"] not in ("decay", "reversible") or not 0 < alpha < 1:
        raise ValueError(
            "binomial marginals require a declared unimolecular family and valid alpha"
        )
    samples = np.asarray(samples, dtype=float)
    population = case["initial"]
    valid = (
        samples.ndim == 2
        and samples.shape[0] >= 8
        and samples.shape[1] == len(TIMES)
        and np.all(np.isfinite(samples))
        and np.all(samples >= 0)
        and np.all(samples <= population)
        and np.array_equal(samples, np.rint(samples))
    )
    if not valid:
        return [
            dict(
                check=name,
                status="FAIL" if name == "sample-validity" else "NOT_TESTED",
                detail="missing, malformed, nonfinite or noninteger count samples",
                related_issues=list(ISSUES),
            )
            for name in CHECKS
        ]
    expected, names = expected_trajectory(case)
    probabilities = expected[:, names.index("A")] / population
    runs = len(samples)
    budget = alpha / (3 * len(TIMES))
    mean_bound = math.sqrt(0.5 * population * runs * math.log(2 / budget))
    cdf_bound = math.sqrt(math.log(2 / budget) / (2 * runs))
    first_mean = first_cdf = first_spread = None
    for index, probability in enumerate(probabilities):
        counts = samples[:, index].astype(int)
        mass = binomial_mass(population, float(probability))
        expected_sum = runs * population * probability
        error = abs(float(counts.sum()) - expected_sum)
        # Source deterministic endpoints (including t=0) have no uncertainty.
        limit = 0 if probability in (0, 1) else mean_bound
        if error > limit and first_mean is None:
            first_mean = dict(
                time=float(TIMES[index]),
                observed_sum=int(counts.sum()),
                expected_sum=float(expected_sum),
                absolute_error=error,
                bound=limit,
            )
        observed_cdf = np.cumsum(np.bincount(counts, minlength=population + 1)) / runs
        difference = float(np.max(np.abs(observed_cdf - np.cumsum(mass))))
        if difference > cdf_bound and first_cdf is None:
            first_cdf = dict(
                time=float(TIMES[index]), max_cdf_error=difference, bound=cdf_bound
            )
        same_count_probability = float(np.sum(mass**runs))
        if (
            np.ptp(counts) == 0
            and same_count_probability < budget
            and first_spread is None
        ):
            first_spread = dict(
                time=float(TIMES[index]),
                repeated_count=int(counts[0]),
                probability_of_all_counts_equal=same_count_probability,
                budget=budget,
            )
    return [
        _row(
            "sample-validity",
            True,
            f"{runs} complete finite integer count trajectories",
        ),
        _row(
            "marginal-means",
            first_mean is None,
            "source binomial mean; Hoeffding simultaneous bounds",
            first_difference=first_mean,
            alpha=alpha,
            per_check_budget=budget,
        ),
        _row(
            "binomial-cdf",
            first_cdf is None,
            "empirical counts against exact source binomial CDF; DKW bound",
            first_difference=first_cdf,
            alpha=alpha,
            cdf_bound=cdf_bound,
        ),
        _row(
            "seed-spread",
            first_spread is None,
            "shared-seed collapse tested against exact probability of equal outcomes",
            first_difference=first_spread,
            alpha=alpha,
        ),
    ]


def run(
    source: Path,
    case,
    native_binary: Path,
    native_xml: Path,
    directory: Path,
    *,
    runs=32,
    cases=48,
):
    import bionetgen

    if type(runs) is not int or not 8 <= runs <= 256 or cases < 1:
        raise ValueError("ensemble budget must be 8..256 runs and positive case count")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    output = []
    for engine in ("embedded", "native"):
        samples, failure = [], None
        for index in range(runs):
            seed = 17 + 7919 * (index + 1)
            work = directory / engine / f"seed-{seed}"
            work.mkdir(parents=True, exist_ok=True)
            try:
                if engine == "embedded":
                    result = bionetgen.load(str(source)).simulate(
                        method="nf", t_end=2, n_steps=10, seed=seed
                    )
                    names = list(result.observables)
                    data = np.column_stack(
                        [result.time] + [result.observables[n] for n in names]
                    )
                    columns = ["time", *names]
                    np.savetxt(
                        work / "trajectory.gdat",
                        data,
                        header=" ".join(columns),
                        fmt="%.17g",
                    )
                    if result.construction_path != "direct":
                        raise ValueError(
                            f"embedded NFsim construction changed: {result.construction_path}"
                        )
                else:
                    receipt = campaign.run_command(
                        [
                            str(native_binary),
                            "-xml",
                            str(native_xml),
                            "-o",
                            str(work / "trajectory.gdat"),
                            "-sim",
                            "2",
                            "-oSteps",
                            "10",
                            "-seed",
                            str(seed),
                        ],
                        work,
                        20,
                        required=("trajectory.gdat",),
                    )
                    if receipt["status"] != "PASS":
                        raise ValueError(
                            f"native seed {seed}: {receipt['status']}: {receipt['detail']}"
                        )
                    data, columns = contracts._trajectory(work / "trajectory.gdat")
                expected, expected_columns = expected_trajectory(case)
                if (
                    data.shape != expected.shape
                    or set(columns) != set(expected_columns)
                    or not np.allclose(data[:, 0], TIMES, rtol=0, atol=1e-9)
                ):
                    raise ValueError(
                        f"{engine} seed {seed}: incomplete grid or changed observable identity"
                    )
                samples.append(data[:, columns.index("A")])
                # Preserve partial samples even when a later seed crashes.
                np.save(directory / f"{engine}-samples.npy", np.asarray(samples))
            except Exception as exc:
                failure = dict(
                    status="FAIL",
                    detail=f"{engine} sampling raised {type(exc).__name__}: {exc}",
                )
                break
        if failure:
            rows = [
                dict(
                    check=check,
                    status="FAIL" if check == "sample-validity" else "NOT_TESTED",
                    detail=failure["detail"],
                    related_issues=list(ISSUES),
                )
                for check in CHECKS
            ]
        else:
            rows = assess_samples(samples, case, alpha=1e-6 / (2 * cases))
        for row in rows:
            row["check"] = engine + "." + row["check"]
            row["ensemble_runs_requested"] = runs
            row["ensemble_runs_completed"] = len(samples)
            row["seed_policy"] = "17 + 7919 * (index + 1); fresh model per seed"
            output.append(row)
    return output
