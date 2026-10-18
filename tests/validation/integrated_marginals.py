"""Independent finite-population NFsim marginals from source count laws.

Decay and two-state conversion use binomial laws; dimerization uses its finite
pure-death generator. Means use Hoeffding bounds over independent particles
or trajectories as applicable; CDFs use the DKW bound. A union budget covers both engines, all samples and selected cases.
This tests those marginals, not complete stochastic execution equivalence.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import campaign, contracts
from .integrated_cases import TIMES, expected_trajectory

CHECKS = ("sample-validity", "marginal-means", "source-cdf", "seed-spread")
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


def source_marginal_mass(case):
    """Independent source count law; columns index the number of A molecules.

    Dimerization is the finite pure-death chain n -> n-2 with propensity
    k*n*(n-1)/V. Its stochastic mean is not the deterministic A^2 solution.
    """
    population = case["initial"]
    if case["family"] in ("decay", "reversible"):
        expected, names = expected_trajectory(case)
        return np.array(
            [
                binomial_mass(population, float(p))
                for p in expected[:, names.index("A")] / population
            ]
        )
    if case["family"] != "dimerization":
        raise ValueError("no independent source count law for family")
    from scipy.linalg import expm
    from .integrated_cases import RATE

    states = np.arange(population, -1, -2)
    generator = np.zeros((len(states), len(states)))
    for index, count in enumerate(states[:-1]):
        hazard = RATE * count * (count - 1) / case["volume"]
        generator[index, index] = -hazard
        generator[index, index + 1] = hazard
    mass = np.zeros((len(TIMES), population + 1))
    for index, time in enumerate(TIMES):
        probabilities = expm(generator * time)[0]
        if np.min(probabilities) < -1e-13 or abs(probabilities.sum() - 1) > 1e-12:
            raise ValueError(
                "independent count-law exponentiation lost probability mass"
            )
        probabilities = np.maximum(probabilities, 0)
        mass[index, states] = probabilities / probabilities.sum()
    return mass


def _row(check, ok, detail, **evidence):
    return dict(
        check=check,
        status="PASS" if ok else "FAIL",
        detail=detail,
        related_issues=list(ISSUES),
        question="independent-source-count-marginals",
        **evidence,
    )


def assess_samples(samples, case, *, alpha=1e-6):
    if (
        case["family"] not in ("decay", "reversible", "dimerization")
        or not 0 < alpha < 1
    ):
        raise ValueError(
            "marginals require a declared source count law and valid alpha"
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
    masses = source_marginal_mass(case)
    runs = len(samples)
    budget = alpha / (3 * len(TIMES))
    # Unimolecular families are sums of independent Bernoulli particles.
    # For dimers only independent trajectories, bounded by population, apply.
    scale = population ** (2 if case["family"] == "dimerization" else 1)
    mean_bound = math.sqrt(0.5 * scale * runs * math.log(2 / budget))
    cdf_bound = math.sqrt(math.log(2 / budget) / (2 * runs))
    first_mean = first_cdf = first_spread = None
    for index, mass in enumerate(masses):
        counts = samples[:, index].astype(int)
        expected_sum = runs * float(np.dot(np.arange(population + 1), mass))
        error = abs(float(counts.sum()) - expected_sum)
        # Source deterministic endpoints (including t=0) have no uncertainty.
        limit = 0 if np.count_nonzero(mass) == 1 else mean_bound
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
            "source count-law mean; Hoeffding simultaneous bounds",
            first_difference=first_mean,
            alpha=alpha,
            per_check_budget=budget,
        ),
        _row(
            "source-cdf",
            first_cdf is None,
            "empirical counts against independent source count CDF; DKW bound",
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
