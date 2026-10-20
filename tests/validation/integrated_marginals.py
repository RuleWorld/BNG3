"""Independent finite-population NFsim marginals from source count laws.

Decay and two-state conversion use binomial laws; dimerization uses its finite
pure-death generator. Means use Hoeffding bounds over independent particles
or trajectories as applicable; CDFs use the DKW bound. A union budget covers both engines, all samples and selected cases.
This tests those marginals, not complete stochastic execution equivalence.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from . import campaign, contracts, integrated_traces
from .integrated_cases import (
    TIMES,
    expected_trajectory,
    source_law_cases,
    source_law_bngl,
    physical_bridge_bngl,
    physical_bridge_cases,
    physical_bridge_refusal_bngl,
    physical_bridge_refusal_cases,
)

CHECKS = ("sample-validity", "marginal-means", "source-cdf", "seed-spread")
SOURCE_LAW_CHECKS = ("ode-source-law", "ssa-source-marginals")
ISSUES = (143, 146, 151, 167)

# The named obligations of the physical-unit count-rate bridge.  Each check
# below runs against an independent count law, never against the product's own
# output.
PHYSICAL_BRIDGE_CHECKS = (
    "amount-count-conversion",
    "elementary-rate-conversion",
    "molecularity",
    "compartment-context",
    "independent-count-model-comparison",
    "missing-context-refusal",
    "unsupported-dimension-refusal",
    "double-scaling-refusal",
)

# The number of standard errors the count-rate discrimination uses.  The
# recorded seed policy and run budget fix the sampling error, so a converted
# count rate is accepted only when the observed mean is inside this many
# standard errors of the independent source law and outside the same distance
# of the law a wrong conversion would produce.
DISCRIMINATION_SIGMA = 4.0


def physical_bridge_check_ids():
    """Stable check identities for the physical-unit count-rate bridge."""
    return [f"qualification:issue:151:{name}" for name in PHYSICAL_BRIDGE_CHECKS]


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
    k*n*(n-1)/V for unit-annotated physical rates and k*n*(n-1)/(2V) for
    bare BNGL count rates. Its stochastic mean is not the deterministic A^2
    solution. Zero-order production is an unbounded Poisson count law.
    """
    population = int(case.get("initial", 0))
    law = case.get("law", case.get("family"))
    rate = float(case.get("rate", 0.4))
    volume = float(case.get("volume", 1.0))
    rate_convention = case.get("rate_convention", "physical_source_law")
    quantity_basis = case.get("quantity_basis", "amount")
    if (
        not math.isfinite(rate)
        or rate < 0
        or not math.isfinite(volume)
        or volume <= 0
        or rate_convention not in ("physical_source_law", "bngl_count")
        or quantity_basis not in ("amount", "concentration")
    ):
        raise ValueError("invalid source-law rate, volume, convention, or quantity")
    if law in ("zero-order", "zero_order"):
        # In the typed source, k has amount/time units. A bare BNGL zero-order
        # rate is a concentration/time count rate and receives product volume.
        production = rate if rate_convention == "physical_source_law" else rate * volume
        from scipy.stats import poisson

        times = np.asarray(case.get("times", TIMES), dtype=float)
        if times.ndim != 1 or np.any(~np.isfinite(times)) or np.any(times < 0):
            raise ValueError("invalid source-law time grid")
        means = production * times
        upper = int(max(16, poisson.ppf(1 - 1e-14, float(np.max(means)))))
        upper = max(upper, int(case.get("initial", 0)))
        mass = np.zeros((len(times), upper + 1), dtype=float)
        initial = int(case.get("initial", 0))
        for index, mean in enumerate(means):
            mass[index, initial:] = poisson.pmf(
                np.arange(upper - initial + 1), float(mean)
            )
            mass[index, -1] += poisson.sf(upper - initial, float(mean))
            # A shifted Poisson count is the initial population plus births.
        return mass
    if law in ("first-order", "first_order"):
        times = np.asarray(case.get("times", TIMES), dtype=float)
        return np.array(
            [binomial_mass(population, math.exp(-rate * float(t))) for t in times]
        )
    if case.get("family") in ("decay", "reversible"):
        expected, names = expected_trajectory(case)
        return np.array(
            [
                binomial_mass(population, float(p))
                for p in expected[:, names.index("A")] / population
            ]
        )
    if law not in ("dimerization", "second-order", "second_order"):
        raise ValueError("no independent source count law for family")
    from scipy.linalg import expm

    # The annotated SBML law k*A^2/V has transition hazard k*n*(n-1)/V.
    # A bare BNGL bimolecular rate uses k*n*(n-1)/(2V); keep the convention
    # explicit so the two sources cannot silently share an assumption.
    symmetry = 1.0 if rate_convention == "physical_source_law" else 0.5

    states = np.arange(population, -1, -2)
    generator = np.zeros((len(states), len(states)))
    for index, count in enumerate(states[:-1]):
        hazard = symmetry * rate * count * (count - 1) / volume
        generator[index, index] = -hazard
        generator[index, index + 1] = hazard
    mass = np.zeros((len(TIMES), population + 1))
    times = np.asarray(case.get("times", TIMES), dtype=float)
    for index, time in enumerate(times):
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


def source_law_check_ids(full=False):
    """Stable expected check identities for the source-law campaign."""
    ids = []
    for case in source_law_cases(full=full):
        ids.append(f"{case['id']}:ode-source-law")
        ids.extend(f"{case['id']}:ssa-source-marginals:{name}" for name in CHECKS)
        ids.extend(
            f"{case['id']}:nf-marginals:{engine}.{name}"
            for engine in ("embedded", "native")
            for name in CHECKS
        )
    for case in physical_bridge_cases(full=full):
        ids.extend(
            f"{case['id']}:nf-marginals:{engine}.{name}"
            for engine in ("embedded", "native")
            for name in CHECKS
        )
    ids.extend(physical_bridge_check_ids())
    return ids


def assess_samples(samples, case, *, alpha=1e-6):
    law = case.get("law", case.get("family"))
    if (
        law
        not in (
            "decay",
            "reversible",
            "dimerization",
            "zero-order",
            "zero_order",
            "first-order",
            "first_order",
            "second-order",
            "second_order",
        )
        or not 0 < alpha < 1
    ):
        raise ValueError(
            "marginals require a declared source count law and valid alpha"
        )
    samples = np.asarray(samples, dtype=float)
    population = case.get("initial")
    bounded = law not in ("zero-order", "zero_order")
    valid = (
        samples.ndim == 2
        and samples.shape[0] >= 8
        and samples.shape[1] == len(case.get("times", TIMES))
        and np.all(np.isfinite(samples))
        and np.all(samples >= 0)
        and (not bounded or np.all(samples <= population))
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
    times = np.asarray(case.get("times", TIMES), dtype=float)
    budget = alpha / (3 * len(times))
    # Unimolecular families are sums of independent Bernoulli particles.
    # For dimers only independent trajectories, bounded by population, apply.
    if bounded:
        scale = population ** (
            2 if law in ("dimerization", "second-order", "second_order") else 1
        )
        mean_bound = math.sqrt(0.5 * scale * runs * math.log(2 / budget))
    else:
        # For Poisson production, Chebyshev gives a finite-sample bound without
        # imposing an arbitrary count ceiling or a normal approximation.
        production = float(case.get("rate", 0.4))
        if case.get("rate_convention", "physical_source_law") == "bngl_count":
            production *= float(case.get("volume", 1.0))
        mean_bound = None
    cdf_bound = math.sqrt(math.log(2 / budget) / (2 * runs))
    first_mean = first_cdf = first_spread = None
    for index, mass in enumerate(masses):
        counts = samples[:, index].astype(int)
        expected_sum = runs * float(np.dot(np.arange(len(mass)), mass))
        error = abs(float(counts.sum()) - expected_sum)
        # Source deterministic endpoints (including t=0) have no uncertainty.
        if bounded:
            limit = 0 if np.count_nonzero(mass) == 1 else mean_bound
        else:
            mean = production * float(times[index])
            variance_sum = runs * mean
            log_budget = math.log(2 / budget)
            limit = (
                0
                if variance_sum == 0
                else math.sqrt(2 * variance_sum * log_budget) + (2 / 3) * log_budget
            )
        if error > limit and first_mean is None:
            first_mean = dict(
                time=float(times[index]),
                observed_sum=int(counts.sum()),
                expected_sum=float(expected_sum),
                absolute_error=error,
                bound=limit,
            )
        observed = np.bincount(counts)
        observed_cdf = np.cumsum(observed) / runs
        expected_cdf = np.cumsum(mass)
        common = min(len(observed_cdf), len(expected_cdf))
        difference = float(
            np.max(np.abs(observed_cdf[:common] - expected_cdf[:common]))
        )
        if len(observed_cdf) > common:
            difference = max(
                difference,
                float(np.max(np.abs(observed_cdf[common:] - 1.0))),
            )
        if difference > cdf_bound and first_cdf is None:
            first_cdf = dict(
                time=float(times[index]), max_cdf_error=difference, bound=cdf_bound
            )
        same_count_probability = float(np.sum(mass**runs))
        if (
            np.ptp(counts) == 0
            and same_count_probability < budget
            and first_spread is None
        ):
            first_spread = dict(
                time=float(times[index]),
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
            (
                "source count-law mean; Hoeffding simultaneous bounds"
                if bounded
                else "source count-law mean; Poisson Chernoff simultaneous bounds"
            ),
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


def native_oracle_realizes_source_law(case):
    """Whether the pinned native NFsim oracle can express this source law.

    The oracle is handed the model the embedded engine executes, stated in
    BNG2's count-rate convention (``integrated_traces.native_count_rate_xml``
    folds the compartment unit conversion into the rule's rate constant),
    so every source law the independent count law covers is reachable.  A
    model whose compartment unit conversion cannot be determined statically
    is not: the export then states no count-rate coefficient, and the
    comparison stays explicitly not tested.
    """
    law = case.get("law", case.get("family"))
    return law in (
        "decay",
        "reversible",
        "dimerization",
        "zero-order",
        "zero_order",
        "first-order",
        "first_order",
        "second-order",
        "second_order",
    )


def run(
    source: Path,
    case,
    native_binary: Path,
    native_xml: Path,
    directory: Path,
    *,
    runs=32,
    cases=48,
    alpha=None,
):
    import bionetgen

    if type(runs) is not int or not 8 <= runs <= 256 or cases < 1:
        raise ValueError("ensemble budget must be 8..256 runs and positive case count")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    output = []
    for engine in ("embedded", "native"):
        samples, failure = [], None
        oracle_model = None
        if engine == "native":
            # The oracle samples BNG2's count-rate convention, so it is handed
            # the same model the embedded engine executes.
            if not native_oracle_realizes_source_law(case):
                failure = dict(
                    status="NOT_TESTED",
                    detail=(
                        "the native NFsim oracle cannot be handed this model in "
                        "BNG2's compartment unit conversion convention: the "
                        "harness states no independent count law for this family; "
                        "the embedded engine comparison against the independent "
                        "count law remains the authoritative one"
                    ),
                    applicability="native-oracle-unit-conversion-unsupported",
                )
            else:
                normalisation = integrated_traces.native_count_rate_xml(
                    native_xml, directory / "native-count-rate.xml"
                )
                if normalisation["status"] == "UNAVAILABLE":
                    failure = dict(
                        status="HARNESS_ERROR",
                        detail=(
                            "the model handed to the native NFsim oracle is "
                            f"unavailable: {normalisation['detail']}"
                        ),
                    )
                elif normalisation["status"] != "NORMALISED":
                    failure = dict(
                        status="NOT_TESTED",
                        detail=(
                            "the native NFsim oracle cannot be handed this model "
                            "in BNG2's compartment unit conversion convention: "
                            f"{normalisation['detail']}; the embedded engine "
                            "comparison against the independent count law remains "
                            "the authoritative one"
                        ),
                        applicability="native-oracle-unit-conversion-unsupported",
                    )
                else:
                    oracle_model = normalisation
        if failure is None and engine == "native" and not Path(native_binary).is_file():
            failure = dict(
                status="HARNESS_ERROR",
                detail=f"native NFsim executable is unavailable: {native_binary}",
            )
        for index in range(runs):
            if failure:
                break
            seed = 17 + 7919 * (index + 1)
            work = directory / engine / f"seed-{seed}"
            work.mkdir(parents=True, exist_ok=True)
            status_on_exception = "FAIL"
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
                            str(oracle_model["path"]),
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
                        refusal = bool(
                            re.search(
                                r"unsupported|not supported|unimplemented|cannot handle",
                                receipt.get("detail", ""),
                                re.IGNORECASE,
                            )
                        )
                        status_on_exception = (
                            "UNSUPPORTED"
                            if refusal
                            else (
                                receipt["status"]
                                if receipt["status"] in ("HARNESS_ERROR", "TIMEOUT")
                                else "FAIL"
                            )
                        )
                        raise ValueError(
                            f"native seed {seed}: {receipt['status']}: {receipt['detail']}"
                        )
                    data, columns = contracts._trajectory(work / "trajectory.gdat")
                if case.get("law"):
                    times = np.asarray(case.get("times", TIMES), dtype=float)
                    if (
                        data.ndim != 2
                        or data.shape[0] != len(times)
                        or "A" not in columns
                        or not np.allclose(data[:, 0], times, rtol=0, atol=1e-9)
                    ):
                        raise ValueError(
                            f"{engine} seed {seed}: incomplete source-law time grid or missing A observable"
                        )
                elif (
                    data.shape != expected_trajectory(case)[0].shape
                    or set(columns) != set(expected_trajectory(case)[1])
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
                    status=status_on_exception,
                    detail=f"{engine} sampling raised {type(exc).__name__}: {exc}",
                )
                break
        if failure:
            rows = [
                dict(
                    check=check,
                    status=(
                        failure["status"]
                        if check == "sample-validity"
                        and not failure.get("applicability")
                        else "NOT_TESTED"
                    ),
                    detail=failure["detail"],
                    related_issues=list(ISSUES),
                    **(
                        {"applicability": failure["applicability"]}
                        if failure.get("applicability")
                        else {}
                    ),
                )
                for check in CHECKS
            ]
        else:
            rows = assess_samples(
                samples,
                case,
                alpha=alpha if alpha is not None else 1e-6 / (2 * cases),
            )
            if engine == "native":
                # Say plainly that the oracle sampled the model: the rows of a
                # native comparison that could not be expressed at all carry an
                # applicability instead.
                for row in rows:
                    row["detail"] = (
                        "the native oracle sampled the model in BNG2's count-rate "
                        "convention (rule rate constant x symmetry factor x "
                        "compartment unit conversion); " + row["detail"]
                    )
                    row["oracle_count_rate_rules"] = oracle_model["rules"]
        for row in rows:
            row["check"] = engine + "." + row["check"]
            row["ensemble_runs_requested"] = runs
            row["ensemble_runs_completed"] = len(samples)
            row["seed_policy"] = "17 + 7919 * (index + 1); fresh model per seed"
            output.append(row)
    return output


def _count_law_mean(case):
    """Expected count of the independent source law at the final time."""
    mass = source_marginal_mass(case)
    return float(np.dot(np.arange(mass.shape[1]), mass[-1]))


def _count_rate_alternatives(case):
    """The count laws a wrong conversion of this rule would produce.

    ``volume`` drops the compartment context, ``double`` applies the
    compartment volume a second time, and ``order`` states the rule with a
    different molecularity.  Each alternative is a count law of the same
    reaction under a different conversion, so the observed ensemble can be
    told apart from it.
    """
    alternatives = {}
    if case["law"] == "second-order":
        alternatives["volume"] = dict(case, volume=1.0)
        alternatives["double"] = dict(case, volume=case["volume"] ** 2)
        alternatives["order"] = dict(
            case,
            law="first-order",
            family="first-order",
            rate=case["rate"],
        )
    elif case["law"] == "zero-order":
        alternatives["double"] = dict(case, rate=case["rate"] * case["volume"])
    return alternatives


def _discriminates(observed_mean, standard_error, expected_mean):
    """Whether the observed mean is inside the error budget of the law."""
    if not math.isfinite(observed_mean) or not math.isfinite(expected_mean):
        return False
    budget = DISCRIMINATION_SIGMA * standard_error
    return abs(observed_mean - expected_mean) <= budget


def _separates(observed_mean, standard_error, alternative_mean):
    """Whether the observed mean is outside the error budget of the law."""
    if not math.isfinite(observed_mean) or not math.isfinite(alternative_mean):
        return False
    return abs(observed_mean - alternative_mean) > DISCRIMINATION_SIGMA * standard_error


def _embedded_bridge_samples(case, source, directory, runs):
    """Sample the embedded NFsim count marginals of a typed model."""
    import bionetgen

    samples = []
    for index in range(runs):
        seed = 17 + 7919 * (index + 1)
        result = bionetgen.load(str(source)).simulate(
            method="nf", t_end=2, n_steps=10, seed=seed
        )
        names = list(result.observables)
        if "A" not in names:
            raise ValueError("typed model does not report the A observable")
        data = np.column_stack(
            [result.time] + [result.observables[name] for name in names]
        )
        if data.shape[0] != len(case["times"]) or not np.allclose(
            data[:, 0], np.asarray(case["times"], dtype=float), rtol=0, atol=1e-9
        ):
            raise ValueError("typed model changed the source-law time grid")
        samples.append(data[:, 1 + names.index("A")])
    np.save(directory / "embedded-samples.npy", np.asarray(samples))
    return np.asarray(samples)


def run_physical_bridge(directory, *, full=False, runs=32, alpha=None):
    """Execute the typed count-rate bridge cases and their refusal controls.

    The product converts a unit-annotated physical law into a count rate; the
    observed count marginals are compared against the independent count law of
    the same physical reaction.  The controls below state the conversions the
    product must not apply: a missing conversion context, an unsupported
    compartment dimension, and a second application of the compartment volume.
    """
    import bionetgen

    if type(runs) is not int or not 8 <= runs <= 256:
        raise ValueError("ensemble budget must be 8..256 runs")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cases = physical_bridge_cases(full=full)
    alpha = alpha if alpha is not None else 1e-6 / (2 * len(cases))
    output = []
    observations = {}
    for case in cases:
        case_dir = directory / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "typed.bngl"
        source.write_text(physical_bridge_bngl(case), encoding="utf-8")
        try:
            samples = _embedded_bridge_samples(case, source, case_dir, runs)
        except Exception as exc:
            detail = f"typed NFsim execution raised {type(exc).__name__}: {exc}"
            output.extend(
                dict(
                    id=f"{case['id']}:nf-marginals:embedded.{name}",
                    check=name,
                    status="FAIL" if name == "sample-validity" else "NOT_TESTED",
                    detail=detail,
                    related_issues=list(ISSUES),
                )
                for name in CHECKS
            )
            output.extend(
                dict(
                    id=f"{case['id']}:nf-marginals:native.{name}",
                    check=name,
                    status="NOT_TESTED",
                    detail=(
                        "the typed model is not handed to the pinned oracle: the "
                        "oracle reads the count-rate convention, and the "
                        "prelowered counterpart of this case in the same family "
                        "already samples that count law with it"
                    ),
                    applicability="native-oracle-unit-conversion-unsupported",
                    related_issues=list(ISSUES),
                )
                for name in CHECKS
            )
            observations[case["id"]] = None
            continue
        rows = assess_samples(samples, case, alpha=alpha)
        for row in rows:
            row.update(
                id=f"{case['id']}:nf-marginals:embedded.{row['check']}",
                check=row["check"],
                source_representation="unit-annotated physical quantity law",
                rate_convention=case["rate_convention"],
                quantity_basis=case["quantity_basis"],
                substance_basis=case["substance_basis"],
                ensemble_runs_requested=runs,
                ensemble_runs_completed=len(samples),
                seed_policy="17 + 7919 * (index + 1); fresh model per seed",
            )
            output.append(row)
        output.extend(
            dict(
                id=f"{case['id']}:nf-marginals:native.{name}",
                check=name,
                status="NOT_TESTED",
                detail=(
                    "the typed model is not handed to the pinned oracle: the "
                    "oracle reads the count-rate convention, and the prelowered "
                    "counterpart of this case in the same family already samples "
                    "that count law with it"
                ),
                applicability="native-oracle-unit-conversion-unsupported",
                related_issues=list(ISSUES),
            )
            for name in CHECKS
        )
        final = samples[:, -1].astype(float)
        observations[case["id"]] = dict(
            mean=float(final.mean()),
            standard_error=(
                float(final.std(ddof=1) / math.sqrt(len(final)))
                if len(final) > 1
                else 0.0
            ),
            rows={row["check"]: row["status"] for row in rows},
        )

    output.extend(
        _physical_bridge_obligations(cases, observations, directory, runs=runs)
    )
    output.extend(_physical_bridge_refusals(directory))
    return output


def _physical_bridge_obligations(cases, observations, directory, *, runs):
    """Summarise the typed bridge cases into the named obligation checks."""
    import bionetgen  # noqa: F401  (the product is exercised by the caller)

    def observation(case_id):
        return observations.get(case_id)

    def law_mean(case):
        return _count_law_mean(case)

    def case_by(**fields):
        for case in cases:
            if all(case.get(key) == value for key, value in fields.items()):
                return case
        return None

    rows = []

    def row(name, ok, detail, *, evidence_kind, first_difference=None, **evidence):
        rows.append(
            dict(
                id=f"qualification:issue:151:{name}",
                check=name,
                status="PASS" if ok else "FAIL",
                detail=detail,
                related_issues=[151],
                evidence_kind=evidence_kind,
                supported_execution=evidence_kind == "supported-execution",
                first_difference=first_difference,
                **evidence,
            )
        )

    # The amount/count conversion: the same physical reaction stated per mole
    # and per item must produce the same count law.
    mole = case_by(law="second-order", substance_basis="mole")
    item = case_by(law="second-order", substance_basis="item")
    ok = True
    detail = ""
    difference = None
    for case in (mole, item):
        observed = observation(case["id"])
        if observed is None:
            ok = False
            detail = "the typed mole/item case did not execute"
            break
        expected = law_mean(case)
        if not _discriminates(observed["mean"], observed["standard_error"], expected):
            ok = False
            detail = (
                "the typed case does not reproduce the independent count law of "
                "the same physical reaction"
            )
            difference = dict(
                case=case["id"],
                observed_mean=observed["mean"],
                expected_mean=expected,
                standard_error=observed["standard_error"],
            )
            break
        detail = (
            "the mole-basis and item-basis statements of the same physical "
            "reaction reproduce the same independent count law"
        )
    row(
        "amount-count-conversion",
        ok,
        detail or "the mole-to-item bridge is applied exactly once",
        evidence_kind="supported-execution",
        first_difference=difference,
        ensemble_runs=runs,
    )

    # The elementary rate conversion: the typed rate constant of every order
    # becomes the count rate of the independent source law.
    ok = True
    detail = ""
    for case in cases:
        observed = observation(case["id"])
        if observed is None:
            ok = False
            detail = f"the typed case {case['id']} did not execute"
            break
        if (
            observed["rows"].get("source-cdf") != "PASS"
            or observed["rows"].get("marginal-means") != "PASS"
        ):
            ok = False
            detail = (
                f"the typed case {case['id']} does not match the independent count law"
            )
            break
        detail = (
            "every typed rate constant converts to the count rate of the "
            "independent source law"
        )
    row(
        "elementary-rate-conversion",
        ok,
        detail or "the typed rate constants are converted to count rates",
        evidence_kind="supported-execution",
        ensemble_runs=runs,
    )

    # The molecularity: the conversion exponent follows the reaction order.
    order_case = case_by(law="second-order", substance_basis="item")
    observed = observation(order_case["id"]) if order_case else None
    ok = observed is not None
    difference = None
    detail = "the molecularity of the reacting order selects the count-rate exponent"
    if ok:
        expected = law_mean(order_case)
        alternatives = _count_rate_alternatives(order_case)
        ok = _discriminates(
            observed["mean"], observed["standard_error"], expected
        ) and all(
            _separates(
                observed["mean"],
                observed["standard_error"],
                law_mean(alternative),
            )
            for alternative in alternatives.values()
        )
        if not ok:
            difference = dict(
                case=order_case["id"],
                observed_mean=observed["mean"],
                expected_mean=expected,
                standard_error=observed["standard_error"],
                alternatives={
                    name: law_mean(alternative)
                    for name, alternative in alternatives.items()
                },
            )
            detail = (
                "the observed count law is not the molecularity-selected law, or "
                "it is not separated from a different reaction order"
            )
    row(
        "molecularity",
        ok,
        detail,
        evidence_kind="supported-execution",
        first_difference=difference,
        ensemble_runs=runs,
    )

    # The compartment context: the conversion uses the reaction compartment.
    ok = True
    detail = ""
    difference = None
    for case in cases:
        observed = observation(case["id"])
        if observed is None:
            ok = False
            detail = f"the typed case {case['id']} did not execute"
            break
        alternatives = _count_rate_alternatives(case)
        if "volume" not in alternatives:
            continue
        expected = law_mean(case)
        if not _discriminates(
            observed["mean"], observed["standard_error"], expected
        ) or not _separates(
            observed["mean"],
            observed["standard_error"],
            law_mean(alternatives["volume"]),
        ):
            ok = False
            detail = "the converted count rate does not use the reaction compartment"
            difference = dict(
                case=case["id"],
                observed_mean=observed["mean"],
                expected_mean=expected,
                standard_error=observed["standard_error"],
                without_compartment_mean=law_mean(alternatives["volume"]),
            )
            break
        detail = (
            "the converted count rate uses the declared reaction compartment, and "
            "is separated from the law without that compartment"
        )
    row(
        "compartment-context",
        ok,
        detail
        or "the conversion context of every typed case is the reaction compartment",
        evidence_kind="supported-execution",
        first_difference=difference,
        ensemble_runs=runs,
    )

    # The independent count model comparison: the sampled count marginals of
    # every typed case match the independent source count law.
    ok = True
    detail = ""
    for case in cases:
        observed = observation(case["id"])
        if observed is None:
            ok = False
            detail = f"the typed case {case['id']} did not execute"
            break
        if observed["rows"].get("source-cdf") != "PASS":
            ok = False
            detail = f"the typed case {case['id']} does not match the source count CDF"
            break
        detail = (
            "every typed case reproduces the count marginals of the independent "
            "source count law"
        )
    row(
        "independent-count-model-comparison",
        ok,
        detail or "the typed cases match the independent source count laws",
        evidence_kind="supported-execution",
        ensemble_runs=runs,
    )

    # The double volume scaling: the converted count rate applies the
    # compartment volume once, so the observed law is separated from the law a
    # second application would produce.
    ok = True
    detail = ""
    difference = None
    for case in cases:
        observed = observation(case["id"])
        if observed is None:
            ok = False
            detail = f"the typed case {case['id']} did not execute"
            break
        alternatives = _count_rate_alternatives(case)
        if "double" not in alternatives:
            continue
        if not _separates(
            observed["mean"],
            observed["standard_error"],
            law_mean(alternatives["double"]),
        ):
            ok = False
            detail = (
                "the observed count law is not separated from the law a second "
                "compartment-volume scaling would produce"
            )
            difference = dict(
                case=case["id"],
                observed_mean=observed["mean"],
                double_scaled_mean=law_mean(alternatives["double"]),
                standard_error=observed["standard_error"],
            )
            break
        detail = (
            "the compartment volume is applied once: the observed count law is "
            "separated from the doubly scaled law"
        )
    row(
        "double-scaling-refusal",
        ok,
        detail or "no typed case applies the compartment volume twice",
        evidence_kind="diagnostic-only",
        first_difference=difference,
        ensemble_runs=runs,
    )
    return rows


def _physical_bridge_refusals(directory):
    """The refusal controls of the physical-unit count-rate bridge."""
    import bionetgen

    rows = []
    for case in physical_bridge_refusal_cases():
        case_dir = directory / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "typed.bngl"
        source.write_text(physical_bridge_refusal_bngl(case), encoding="utf-8")
        refused = False
        detail = "the model was executed instead of being refused"
        try:
            bionetgen.load(str(source)).simulate(
                method="nf", t_end=2, n_steps=10, seed=17
            )
        except Exception as exc:
            message = str(exc)
            refused = "physical-unit" in message
            detail = (
                f"the product refused the model: {type(exc).__name__}: {message}"
                if refused
                else f"the product refused the model without naming the physical-unit "
                f"boundary: {type(exc).__name__}: {message}"
            )
        name = (
            "missing-context-refusal"
            if case["refusal"] == "missing-context"
            else "unsupported-dimension-refusal"
        )
        rows.append(
            dict(
                id=f"qualification:issue:151:{name}",
                check=name,
                status="PASS" if refused else "FAIL",
                detail=detail,
                related_issues=[151],
                evidence_kind="diagnostic-only",
                supported_execution=False,
                model=str(source),
            )
        )
    return rows


def _source_law_mean(case):
    """Deterministic amount trajectory implied by a declared source law."""
    law = case["law"]
    times = np.asarray(case.get("times", TIMES), dtype=float)
    initial = float(case["initial"])
    rate = float(case["rate"])
    volume = float(case["volume"])
    convention = case["rate_convention"]
    if law == "zero-order":
        production = rate if convention == "physical_source_law" else rate * volume
        return initial + production * times
    if law == "first-order":
        return initial * np.exp(-rate * times)
    if law == "second-order":
        coefficient = 2.0 if convention == "physical_source_law" else 1.0
        return initial / (1 + coefficient * rate * initial * times / volume)
    raise ValueError(f"unknown source-law family: {law!r}")


def run_source_laws(directory, native_binary, *, full=False, runs=32):
    """Run source-law cases through BNG3 ODE/SSA/NF and native NFsim."""
    import bionetgen

    cases = source_law_cases(full=full)
    if type(runs) is not int or not 8 <= runs <= 256:
        raise ValueError("ensemble budget must be 8..256 runs")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    output = []
    alpha = 1e-6 / max(1, 3 * len(cases))
    physical_alpha = 1e-6 / max(1, 3 * len(physical_bridge_cases(full=full)))
    import json

    (directory / "source-law-plan.json").write_text(
        json.dumps(
            dict(
                cases=cases,
                check_ids=source_law_check_ids(full=full),
                ensemble_runs=runs,
                campaign_alpha=1e-6,
                alpha_per_engine_case=alpha,
                physical_bridge_alpha=physical_alpha,
                nf_seed_policy="17 + 7919 * (index + 1)",
                ssa_seed_policy="19 + 7919 * (index + 1)",
                scope=(
                    "A count marginals only; the physical source-law controls are "
                    "prelowered independently, and the typed physical-bridge family "
                    "states the physical law with unit annotations so the product "
                    "performs the amount/count and count-rate conversion itself"
                ),
            ),
            indent=2,
        )
        + "\n"
    )
    for case in cases:
        case_dir = directory / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "source.bngl"
        xml = case_dir / "model.xml"
        source.write_text(source_law_bngl(case), encoding="utf-8")
        try:
            model = bionetgen.load(str(source))
            model.write_xml(str(xml))
        except Exception as exc:
            refusal = bool(
                re.search(
                    r"unsupported|not supported|unimplemented",
                    str(exc),
                    re.IGNORECASE,
                )
            )
            prep_status = "UNSUPPORTED" if refusal else "HARNESS_ERROR"
            prep_detail = (
                f"BNG3 model/XML preparation failed: {type(exc).__name__}: {exc}"
            )
            output.append(
                dict(
                    id=f"{case['id']}:ode-source-law",
                    check="ode-source-law",
                    status=prep_status,
                    detail=prep_detail,
                    related_issues=list(ISSUES),
                )
            )
            output.extend(
                dict(
                    id=f"{case['id']}:ssa-source-marginals:{name}",
                    check=name,
                    status="NOT_TESTED",
                    detail=f"source preparation prerequisite failed: {prep_detail}",
                    related_issues=list(ISSUES),
                )
                for name in CHECKS
            )
            output.extend(
                dict(
                    id=f"{case['id']}:nf-marginals:{engine}.{name}",
                    check=f"{engine}.{name}",
                    status="NOT_TESTED",
                    detail=f"source preparation prerequisite failed: {prep_detail}",
                    related_issues=list(ISSUES),
                )
                for engine in ("embedded", "native")
                for name in CHECKS
            )
            continue

        times = np.asarray(case["times"], dtype=float)
        ode_row = dict(
            id=f"{case['id']}:ode-source-law",
            check="ode-source-law",
            related_issues=list(ISSUES),
            source_units=case["source_units"],
            rate_convention=case["rate_convention"],
            source_representation="prelowered physical source-law control or bare BNGL count law",
            quantity_basis=case["quantity_basis"],
            parameter_backed_volume=case["volume"],
        )
        try:
            result = model.simulate(
                method="ode",
                t_end=float(times[-1]),
                n_steps=len(times) - 1,
                # BDF tolerances bound local error, whereas the analytic check
                # below bounds accumulated trajectory error. Leave headroom for
                # the second-order pure-death controls without relaxing it.
                rtol=1e-12,
                atol=1e-14,
            )
            observed = np.asarray(result.observables[case["observable"]], dtype=float)
            observed_times = np.asarray(result.time, dtype=float)
            expected = _source_law_mean(case)
            first_difference = None
            if observed.shape != expected.shape or not np.allclose(
                observed_times, times, rtol=0, atol=1e-9
            ):
                first_difference = {"detail": "ODE grid or observable shape changed"}
            else:
                error = np.abs(observed - expected)
                bad = np.flatnonzero(error > 1e-9 + 1e-9 * np.abs(expected))
                if len(bad):
                    i = int(bad[0])
                    first_difference = dict(
                        time=float(times[i]),
                        reference=float(expected[i]),
                        subject=float(observed[i]),
                        absolute_error=float(error[i]),
                    )
            np.savetxt(
                case_dir / "ode.gdat",
                np.column_stack((observed_times, observed)),
                header="time A",
                fmt="%.17g",
            )
            ode_row.update(
                status="PASS" if first_difference is None else "FAIL",
                detail="BNG3 ODE amount trajectory against analytic source law",
                first_difference=first_difference,
                receipt=str((case_dir / "ode.gdat").resolve()),
            )
        except Exception as exc:
            ode_row.update(
                status="FAIL",
                detail=f"ODE execution raised {type(exc).__name__}: {exc}",
            )
        output.append(ode_row)

        ssa_samples = []
        ssa_failure = None
        for index in range(runs):
            seed = 19 + 7919 * (index + 1)
            try:
                result = bionetgen.load(str(source)).simulate(
                    method="ssa",
                    t_end=float(times[-1]),
                    n_steps=len(times) - 1,
                    seed=seed,
                )
                observed = np.asarray(
                    result.observables[case["observable"]], dtype=float
                )
                if observed.shape != times.shape or not np.allclose(
                    np.asarray(result.time), times, rtol=0, atol=1e-9
                ):
                    raise ValueError("SSA grid or observable shape changed")
                ssa_samples.append(observed)
            except Exception as exc:
                ssa_failure = f"SSA seed {seed}: {type(exc).__name__}: {exc}"
                break
        if ssa_failure:
            ssa_rows = [
                dict(
                    check=name,
                    status="FAIL" if name == "sample-validity" else "NOT_TESTED",
                    detail=ssa_failure,
                    related_issues=list(ISSUES),
                )
                for name in CHECKS
            ]
        else:
            np.save(case_dir / "ssa-samples.npy", np.asarray(ssa_samples))
            ssa_rows = assess_samples(ssa_samples, case, alpha=alpha)
        for row in ssa_rows:
            row.update(
                id=f"{case['id']}:ssa-source-marginals:{row['check']}",
                check=row["check"],
                source_units=case["source_units"],
                source_representation="prelowered physical source-law control or bare BNGL count law",
                rate_convention=case["rate_convention"],
                quantity_basis=case["quantity_basis"],
                ensemble_runs_requested=runs,
                ensemble_runs_completed=len(ssa_samples),
                seed_policy="19 + 7919 * (index + 1); fresh model per seed",
            )
            output.append(row)

        nf_rows = run(
            source,
            case,
            native_binary,
            xml,
            case_dir / "nf-ensembles",
            runs=runs,
            cases=len(cases),
            alpha=alpha,
        )
        output.extend(
            dict(
                row,
                id=f"{case['id']}:nf-marginals:{row['check']}",
                source_units=case["source_units"],
                source_representation="prelowered physical source-law control or bare BNGL count law",
                rate_convention=case["rate_convention"],
                quantity_basis=case["quantity_basis"],
            )
            for row in nf_rows
        )
    output.extend(
        run_physical_bridge(
            directory / "physical-bridge",
            full=full,
            runs=runs,
            alpha=physical_alpha,
        )
    )
    return output
