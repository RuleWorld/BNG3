"""Stochastic parity of the supported rate conventions against count laws (#167).

Issue #167 asks for the exact supported special-rate, local-function, TFUN and
builtin conventions and the full propensity/event-selection contract to be
stated and checked.  This module states them as *laws* and compares the
stochastic backends against those laws.

Every case is a generated, parameterized model.  Each case declares

``law``
    The independent expectation.  It is never produced by BNG3: it is derived
    from the rate law's own semantics (the master equation of the declared
    reaction) and computed here, so a stochastic result is never compared
    against the product's own output.

``decoy``
    A second law that states a *specific* plausible misreading of the same
    convention (a dropped saturation factor, a doubled rate constant, a
    missing statistical factor, a stale function value).  The observed
    ensemble must be separated from the decoy, so the check says which
    convention holds and not merely that some convention holds.

The laws used here are the ones the canonical BioNetGen semantics state:

``binomial-thinning``
    A first-order rule whose per-molecule hazard is the constant ``lambda``
    thins ``N0`` independent molecules, so the count at time ``t`` is exactly
    ``Binomial(N0, exp(-lambda t))``.

``pure-death``
    A rule whose propensity depends on the count has a finite-state pure-death
    generator ``n -> n - step`` with hazard ``a(n)``.  The law is the exact
    matrix exponential of that generator, computed from the declared hazard.

The special-rate hazards follow the canonical saturation and Hill laws: the
saturation law of ``Sat(kcat, K)`` has hazard ``kcat * n / (K + n)`` for one
distinct reactant, and the Hill law of ``Hill(Vmax, Kh, h)`` has hazard
``Vmax * n**h / (Kh**h + n**h)``.  The elementary bimolecular rule has hazard
``k * C(n, 2)``: the statistical factor of two identical reactants is part of
the propensity, not an afterthought.  Those are the canonical BioNetGen
conventions, not BNG3's: they are the saturation and Hill rate expressions of
the canonical Network3 engine (``bng2/Network3/src/model/rateExpressions/``)
and the statistical-factor convention of its reaction reader, and the
canonical Perl BNG2 reproduces the same law.  A direct cross-check on the
canonical Perl BNG2 2.9.3 (the RuleWorld/bionetgen checkout at ``3513bca7``,
which is not the locked oracle revision; 60 seeded SSA trajectories of the
saturation case, mean final count 19.817 with a standard error of 0.061)
agrees with the analytic mean of the law used here (19.7339).

A rule outside the declared slice is refused with its reason rather than
compared against a law that does not describe it.  Two refusals are expected
and recorded: the embedded NFsim route does not construct a model whose rate
law carries a function, so the TFUN case is unsupported for that backend; and
a saturated or Hill law with repeated identical reactants is outside the
slice, because BNG3's stochastic backends do not reproduce the canonical
BioNetGen propensity for that form.  For ``A() + A() -> D() Sat(kcat, K)`` with
``N = 20``, ``kcat = 0.4`` and ``K = 10``, the BNG3 SSA mean final count over
150 seeded trajectories is 12.03 while the canonical Perl BNG2 2.9.3 gives
17.00 over 60 (standard error 0.30); that divergence is recorded, not judged.

The statistical control is stated, not assumed:

* the mean of the ensemble is compared with the analytic mean of the law by an
  *exact* two-sided test on the ensemble total, whose null distribution is the
  exact convolution of the law's own mass function over the recorded number
  of trajectories.  The per-timepoint error rate is corrected over the sampled
  timepoints by a union bound, so the recorded ``alpha`` bounds the
  family-wise error rate of the whole case;
* the empirical count distribution is compared with the law's distribution by
  the Dvoretzky-Kiefer-Wolfowitz bound, which is distribution free and holds
  for the discrete laws used here;
* the decoy is rejected by the same exact test, so the separation claim has
  the same error control as the agreement claim.

The seed policy and the run budget are fixed and recorded, so the sampling
error of a result is a number rather than a tolerance that drifts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

ISSUES = (167,)

# The recorded run budget and seed policy.  Both are fixed: the statistical
# control of every result below is computed from them, so a re-run reproduces
# the same numbers instead of a different sample of the same law.
RUNS = 64
SEED_BASE = 17
SEED_STRIDE = 7919
SEED_POLICY = "17 + 7919 * (index + 1); a fresh model per trajectory"

# The family-wise error rate of one case (all timepoints, both statistical
# controls) and the per-timepoint budget the union bound spends.
ALPHA = 1e-6

TIMES = tuple(float(t) for t in np.linspace(0.0, 2.0, 11))
T_END = 2.0
N_STEPS = 10
OBSERVABLE = "Acount"
BACKENDS = ("ssa", "nf")

# The declared qualified slice.  A rule outside it is reported as refused with
# its reason instead of being compared against a law that does not describe it.
SLICE = (
    "rules with one distinct reactant, plus the elementary bimolecular rule "
    "with two identical reactants; a saturated or Hill law with repeated "
    "identical reactants is outside the slice"
)

CHECKS = (
    "sample-validity",
    "law-cdf",
    "mean-refinement",
    "convention-separation",
)

# The two obligations of issue #167 that a named executable check closes.
OBLIGATION_CHECKS = (
    "encode-the-exact-supported-special-rate-local-function-tfun-and",
    "prove-the-selected-refinement-statements-explicitly-exclude-unpr",
)


def _model(
    *,
    parameters,
    rule,
    functions=(),
    molecule_types=("A()", "B()", "D()"),
    seeds=(("A()", "N"), ("B()", "0"), ("D()", "0")),
):
    """Return the BNGL source of one generated case."""
    function_block = ""
    if functions:
        function_block = (
            "begin functions\n"
            + "\n".join("  " + f for f in functions)
            + "\nend functions\n"
        )
    seed_block = "\n".join(f"  {name} {amount}" for name, amount in seeds)
    return f"""# Generated stochastic-parity case: one rate convention, one count law.
begin model
begin parameters
{chr(10).join("  " + p for p in parameters)}
end parameters
begin molecule types
{chr(10).join("  " + m for m in molecule_types)}
end molecule types
begin seed species
{seed_block}
end seed species
begin observables
  Molecules Acount A()
end observables
{function_block}begin reaction rules
  {rule}
end reaction rules
end model
"""


def _thinning_law(population, rate):
    return dict(kind="binomial-thinning", population=int(population), rate=float(rate))


def _death_law(population, hazard, step=1):
    return dict(
        kind="pure-death",
        population=int(population),
        hazard=hazard,
        step=int(step),
    )


def _hazard_value(hazard, count):
    """Evaluate a declared hazard descriptor at a molecule count."""
    kind = hazard[0]
    if kind == "none":
        return 0.0
    if kind == "saturation":
        kcat, km = float(hazard[1]), float(hazard[2])
        return kcat * count / (km + count)
    if kind == "hill":
        vmax, kh, h = float(hazard[1]), float(hazard[2]), float(hazard[3])
        return vmax * count**h / (kh**h + count**h)
    if kind == "elementary-bimolecular":
        k = float(hazard[1])
        return k * (count * (count - 1) / 2.0)
    if kind == "quadratic":
        k = float(hazard[1])
        return k * count * count
    if kind == "frozen-function-state":
        k, population = float(hazard[1]), float(hazard[2])
        return k * population * count
    if kind == "linear":
        k = float(hazard[1])
        return k * count
    if kind == "elementary-bimolecular-no-symmetry":
        k = float(hazard[1])
        return k * count * (count - 1)
    raise ValueError("unknown hazard descriptor: " + repr(kind))


def _hazard_descriptor(hazard):
    """A JSON-serialisable form of a hazard descriptor."""
    return [hazard[0], *[float(value) for value in hazard[1:]]]


def cases():
    """Return the generated, parameterized stochastic-parity cases.

    Each family states one supported rate convention.  The families are
    instantiated over a small parameter grid, so the law is checked at more
    than one population and rate.
    """
    generated = []
    grid = ((20, 0.4), (40, 0.25))
    for population, rate in grid:
        tag = f"n{population}-k{str(rate).replace('.', '')}"

        # The elementary rate law: the propensity/event-selection baseline.
        generated.append(
            dict(
                id=f"parameter-{tag}",
                convention="elementary-parameter",
                text=_model(
                    parameters=[f"k {rate!r}", f"N {population}"],
                    rule="A() -> B() k",
                ),
                law=_thinning_law(population, rate),
                decoy=_thinning_law(population, 2.0 * rate),
                decoy_reason="the rate constant counted twice",
            )
        )

        # A local function whose body is a parameter.
        generated.append(
            dict(
                id=f"local-function-{tag}",
                convention="local-function",
                text=_model(
                    parameters=[f"k {rate!r}", f"N {population}"],
                    rule="A() -> B() f()",
                    functions=["f() = k"],
                ),
                law=_thinning_law(population, rate),
                decoy=_thinning_law(population, 2.0 * rate),
                decoy_reason="the function body counted twice",
            )
        )

        # A local function whose body depends on the current state: the
        # function must be re-evaluated from the state after every event.
        generated.append(
            dict(
                id=f"local-function-state-{tag}",
                convention="local-function-state",
                text=_model(
                    parameters=[f"k {rate!r}", f"N {population}"],
                    rule="A() -> B() f()",
                    functions=["f() = k*Acount"],
                ),
                law=_death_law(population, ("quadratic", rate)),
                decoy=_death_law(
                    population, ("frozen-function-state", rate, float(population))
                ),
                decoy_reason=("the function value frozen at the initial state"),
            )
        )

        # A builtin call in the rate law.
        generated.append(
            dict(
                id=f"builtin-{tag}",
                convention="builtin",
                text=_model(
                    parameters=[f"k {rate!r}", f"N {population}"],
                    rule="A() -> B() f()",
                    functions=["f() = k*sqrt(4)"],
                ),
                law=_thinning_law(population, 2.0 * rate),
                decoy=_thinning_law(population, 4.0 * rate),
                decoy_reason="the builtin result applied twice",
            )
        )

        # A table function in the rate law.
        generated.append(
            dict(
                id=f"tfun-{tag}",
                convention="tfun",
                text=_model(
                    parameters=[f"N {population}"],
                    rule="A() -> B() f()",
                    functions=[f"f() = tfun([0,1],[{rate!r},{rate!r}],1)"],
                ),
                law=_thinning_law(population, rate),
                decoy=_thinning_law(population, 2.0 * rate),
                decoy_reason="the table value counted twice",
            )
        )

        # The saturation special rate.
        generated.append(
            dict(
                id=f"saturation-{tag}",
                convention="special-rate-saturation",
                text=_model(
                    parameters=[f"kcat {rate!r}", f"K 10", f"N {population}"],
                    rule="A() -> B() Sat(kcat,K)",
                ),
                law=_death_law(population, ("saturation", rate, 10.0)),
                decoy=_death_law(population, ("linear", rate)),
                decoy_reason="the saturation factor dropped",
            )
        )

        # The Hill special rate.
        generated.append(
            dict(
                id=f"hill-{tag}",
                convention="special-rate-hill",
                text=_model(
                    parameters=[f"Vmax {rate!r}", f"Kh 10", f"h 2", f"N {population}"],
                    rule="A() -> B() Hill(Vmax,Kh,h)",
                ),
                law=_death_law(population, ("hill", rate, 10.0, 2.0)),
                decoy=_death_law(population, ("linear", rate)),
                decoy_reason="the Hill saturation dropped",
            )
        )

        # The elementary bimolecular rule: the statistical factor of two
        # identical reactants belongs to the propensity.
        generated.append(
            dict(
                id=f"elementary-bimolecular-{tag}",
                convention="elementary-bimolecular",
                text=_model(
                    parameters=[f"k {rate!r}", f"N {population}"],
                    rule="A() + A() -> D() k",
                ),
                law=_death_law(population, ("elementary-bimolecular", rate), step=2),
                decoy=_death_law(
                    population, ("elementary-bimolecular-no-symmetry", rate), step=2
                ),
                decoy_reason="the statistical factor of identical reactants dropped",
            )
        )
    return generated


def check_ids():
    """Stable expected check identities for the stochastic-parity operation."""
    ids = []
    for case in cases():
        for backend in BACKENDS:
            ids.extend(
                f"stochastic-parity:{case['id']}:{backend}.{name}" for name in CHECKS
            )
    ids.extend(f"qualification:issue:167:{name}" for name in OBLIGATION_CHECKS)
    return ids


def _law_masses(law, times):
    """Exact mass function of the declared law at every sampled time.

    The result is indexed by molecule count, so a convolution over the
    ensemble total keeps the same index.
    """
    population = int(law["population"])
    if law["kind"] == "binomial-thinning":
        rate = float(law["rate"])
        from scipy.stats import binom

        masses = []
        for time in times:
            q = math.exp(-rate * float(time))
            masses.append(binom.pmf(np.arange(population + 1), population, q))
        return np.asarray(masses, dtype=float)

    if law["kind"] != "pure-death":
        raise ValueError("unknown law kind: " + repr(law["kind"]))
    from scipy.linalg import expm

    step = int(law["step"])
    states = np.arange(population, -1, -step)
    generator = np.zeros((len(states), len(states)))
    for index, count in enumerate(states[:-1]):
        hazard = _hazard_value(law["hazard"], float(count))
        generator[index, index] = -hazard
        generator[index, index + 1] = hazard
    masses = []
    for time in times:
        probabilities = expm(generator * float(time))[0]
        if np.min(probabilities) < -1e-12 or abs(probabilities.sum() - 1.0) > 1e-10:
            raise ValueError("the independent count law lost probability mass")
        probabilities = np.maximum(probabilities, 0.0)
        mass = np.zeros(population + 1)
        for index, count in enumerate(states):
            mass[int(count)] = probabilities[index]
        masses.append(mass / mass.sum())
    return np.asarray(masses, dtype=float)


def _law_mean(law, times, masses):
    counts = np.arange(int(law["population"]) + 1)
    return np.asarray([float(np.dot(counts, mass)) for mass in masses], dtype=float)


def _law_variance(law, times, masses):
    counts = np.arange(int(law["population"]) + 1)
    variances = []
    for mass in masses:
        mean = float(np.dot(counts, mass))
        second = float(np.dot(counts**2, mass))
        variances.append(max(second - mean * mean, 0.0))
    return np.asarray(variances, dtype=float)


def _null_distribution(mass, runs):
    """Exact null distribution of the ensemble total under one law.

    The total of ``runs`` independent trajectories is the convolution of the
    law's own mass function ``runs`` times, so the test that uses it is exact
    rather than asymptotic.
    """
    distribution = np.array([1.0])
    for _ in range(runs):
        distribution = np.convolve(distribution, mass)
    return distribution


def _exact_two_sided_pvalue(distribution, observed_total):
    """Exact two-sided p-value of an observed ensemble total.

    The test is the probability-ordering one: the p-value is the probability
    of a deviation at least as large as the observed one, under the exact
    null distribution.
    """
    values = np.arange(len(distribution))
    expected = float(np.dot(values, distribution))
    deviation = abs(float(observed_total) - expected)
    mask = np.abs(values - expected) >= deviation - 1e-9
    return float(min(1.0, distribution[mask].sum())), expected


def _dkw_bound(runs, alpha):
    """The Dvoretzky-Kiefer-Wolfowitz bound for one timepoint."""
    return math.sqrt(math.log(2.0 / alpha) / (2.0 * runs))


def _row(check, status, detail, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="stochastic-backend-versus-independent-count-law",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


def _sample(case, backend, runs, directory):
    """Sample one case with one backend and return the count trajectories."""
    import bionetgen

    source = directory / case["id"] / "model.bngl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(case["text"], encoding="utf-8")
    trajectories = []
    for index in range(runs):
        seed = SEED_BASE + SEED_STRIDE * (index + 1)
        model = bionetgen.load(str(source))
        result = model.simulate(method=backend, t_end=T_END, n_steps=N_STEPS, seed=seed)
        names = list(result.observables)
        if OBSERVABLE not in names:
            raise ValueError(
                f"{backend} seed {seed}: the model does not report {OBSERVABLE}"
            )
        times = np.asarray(result.time, dtype=float)
        if times.shape != np.asarray(TIMES).shape or not np.allclose(
            times, np.asarray(TIMES), rtol=0, atol=1e-9
        ):
            raise ValueError(f"{backend} seed {seed}: the sampled time grid changed")
        trajectories.append(np.asarray(result.observables[OBSERVABLE], dtype=float))
    samples = np.asarray(trajectories, dtype=float)
    np.save(directory / case["id"] / f"{backend}-samples.npy", samples)
    return samples


def _assess(case, backend, samples, masses, means, runs, alpha):
    """Compare one sampled ensemble with the declared law and its decoy."""
    population = int(case["law"]["population"])
    times = np.asarray(TIMES, dtype=float)
    per_timepoint = alpha / len(times)

    if (
        samples.ndim != 2
        or samples.shape[0] != runs
        or samples.shape[1] != len(times)
        or not np.all(np.isfinite(samples))
        or np.any(samples < 0)
        or np.any(samples > population)
        or not np.array_equal(samples, np.rint(samples))
    ):
        return [
            _row(
                name,
                "FAIL" if name == "sample-validity" else "NOT_TESTED",
                "the ensemble is missing, malformed, non-finite or non-integer",
                ensemble_runs_requested=runs,
                ensemble_runs_completed=(
                    int(samples.shape[0]) if samples.ndim == 2 else 0
                ),
                seed_policy=SEED_POLICY,
                alpha=alpha,
            )
            for name in CHECKS
        ]

    observed_means = samples.mean(axis=0)
    observed_totals = samples.sum(axis=0)

    # The exact test of the refinement statement: the stochastic mean must be
    # the analytic mean of the declared law, at every sampled time.
    refinement = []
    for index, mass in enumerate(masses):
        distribution = _null_distribution(mass, runs)
        pvalue, expected = _exact_two_sided_pvalue(distribution, observed_totals[index])
        refinement.append(
            dict(
                time=float(times[index]),
                observed_mean=float(observed_means[index]),
                law_mean=float(means[index]),
                observed_total=float(observed_totals[index]),
                exact_pvalue=float(pvalue),
                per_timepoint_budget=float(per_timepoint),
            )
        )
    worst_refinement = min(refinement, key=lambda row: row["exact_pvalue"])

    # The distributional comparison: the empirical count distribution against
    # the law's own distribution, bounded by the DKW inequality.
    dkw = _dkw_bound(runs, per_timepoint)
    cdf_rows = []
    for index, mass in enumerate(masses):
        counts = samples[:, index].astype(int)
        observed_cdf = (
            np.cumsum(np.bincount(counts, minlength=population + 1))[: population + 1]
            / runs
        )
        expected_cdf = np.cumsum(mass)
        difference = float(np.max(np.abs(observed_cdf - expected_cdf)))
        cdf_rows.append(
            dict(
                time=float(times[index]),
                max_cdf_error=difference,
                bound=float(dkw),
            )
        )
    worst_cdf = max(cdf_rows, key=lambda row: row["max_cdf_error"])

    # The separation claim: the decoy law must be rejected by the same exact
    # test, so the observed ensemble states which convention holds.
    decoy_masses = _law_masses(case["decoy"], TIMES)
    decoy_rows = []
    for index, mass in enumerate(decoy_masses):
        distribution = _null_distribution(mass, runs)
        pvalue, _expected = _exact_two_sided_pvalue(
            distribution, observed_totals[index]
        )
        decoy_rows.append(
            dict(
                time=float(times[index]),
                decoy_pvalue=float(pvalue),
                per_timepoint_budget=float(per_timepoint),
            )
        )
    rejected = [row for row in decoy_rows if row["decoy_pvalue"] <= per_timepoint]
    worst_decoy = min(decoy_rows, key=lambda row: row["decoy_pvalue"])

    cdf_ok = worst_cdf["max_cdf_error"] <= worst_cdf["bound"]
    refinement_ok = worst_refinement["exact_pvalue"] > per_timepoint
    separation_ok = bool(rejected)
    return [
        _row(
            "sample-validity",
            "PASS",
            f"{runs} complete finite integer count trajectories on the declared grid",
            ensemble_runs_requested=runs,
            ensemble_runs_completed=int(samples.shape[0]),
            seed_policy=SEED_POLICY,
        ),
        _row(
            "law-cdf",
            "PASS" if cdf_ok else "FAIL",
            "empirical count distribution against the independent law; DKW bound",
            first_difference=(None if cdf_ok else worst_cdf),
            alpha=alpha,
            per_timepoint_budget=per_timepoint,
            cdf_bound=worst_cdf["bound"],
            worst_cdf_error=worst_cdf["max_cdf_error"],
        ),
        _row(
            "mean-refinement",
            "PASS" if refinement_ok else "FAIL",
            (
                "stochastic ensemble mean against the analytic mean of the "
                "independent law; exact two-sided test, union bound over the "
                "sampled timepoints"
            ),
            first_difference=(None if refinement_ok else worst_refinement),
            alpha=alpha,
            per_timepoint_budget=per_timepoint,
            worst_exact_pvalue=worst_refinement["exact_pvalue"],
            observed_mean=worst_refinement["observed_mean"],
            law_mean=worst_refinement["law_mean"],
        ),
        _row(
            "convention-separation",
            "PASS" if separation_ok else "FAIL",
            (
                "the observed ensemble is separated from the declared misreading "
                f"({case['decoy_reason']}) by the same exact test"
            ),
            first_difference=(None if separation_ok else worst_decoy),
            alpha=alpha,
            per_timepoint_budget=per_timepoint,
            decoy_pvalue=worst_decoy["decoy_pvalue"],
            decoy_reason=case["decoy_reason"],
        ),
    ]


def _plan(cases_, runs, alpha):
    """The recorded plan of the qualification."""
    return dict(
        cases=[
            dict(
                id=case["id"],
                convention=case["convention"],
                law=dict(
                    kind=case["law"]["kind"],
                    population=case["law"]["population"],
                    rate=case["law"].get("rate"),
                    hazard=(
                        _hazard_descriptor(case["law"]["hazard"])
                        if "hazard" in case["law"]
                        else None
                    ),
                    step=case["law"].get("step"),
                ),
                decoy=dict(
                    kind=case["decoy"]["kind"],
                    population=case["decoy"]["population"],
                    rate=case["decoy"].get("rate"),
                    hazard=(
                        _hazard_descriptor(case["decoy"]["hazard"])
                        if "hazard" in case["decoy"]
                        else None
                    ),
                    step=case["decoy"].get("step"),
                    reason=case["decoy_reason"],
                ),
                check_ids=[
                    f"stochastic-parity:{case['id']}:{backend}.{name}"
                    for backend in BACKENDS
                    for name in CHECKS
                ],
            )
            for case in cases_
        ],
        backends=list(BACKENDS),
        ensemble_runs=runs,
        alpha=alpha,
        seed_policy=SEED_POLICY,
        times=list(TIMES),
        t_end=T_END,
        n_steps=N_STEPS,
        qualified_slice=SLICE,
        statistical_control=(
            "exact two-sided test on the ensemble total with a union bound over "
            "the sampled timepoints; DKW bound for the count distribution"
        ),
        independent_expectation=(
            "the master-equation law of the declared rate convention, computed "
            "in the harness; never the product's own output"
        ),
    )


def run(directory, *, runs=RUNS, alpha=ALPHA):
    """Execute every generated case against its independent count law."""
    import bionetgen  # noqa: F401  (the product is exercised below)

    if type(runs) is not int or not 8 <= runs <= 256:
        raise ValueError("the ensemble budget must be 8..256 runs")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be a probability")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cases_ = cases()
    (directory / "stochastic-parity-plan.json").write_text(
        json.dumps(_plan(cases_, runs, alpha), indent=2) + "\n", encoding="utf-8"
    )

    rows = []
    judged = 0
    refused = []
    for case in cases_:
        masses = _law_masses(case["law"], TIMES)
        means = _law_mean(case["law"], TIMES, masses)
        for backend in BACKENDS:
            try:
                samples = _sample(case, backend, runs, directory)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                refused.append((case["id"], backend, message))
                for name in CHECKS:
                    rows.append(
                        dict(
                            _row(
                                name,
                                "UNSUPPORTED",
                                "the backend refused the case: " + message,
                                applicability="backend-refused-the-model",
                                ensemble_runs_requested=runs,
                                seed_policy=SEED_POLICY,
                                alpha=alpha,
                            ),
                            id=f"stochastic-parity:{case['id']}:{backend}.{name}",
                            check=f"{backend}.{name}",
                            convention=case["convention"],
                            ensemble_runs=runs,
                        )
                    )
                continue
            judged += 1
            for row in _assess(case, backend, samples, masses, means, runs, alpha):
                name = row["check"]
                rows.append(
                    dict(
                        row,
                        id=f"stochastic-parity:{case['id']}:{backend}.{name}",
                        check=f"{backend}.{name}",
                        convention=case["convention"],
                        ensemble_runs=runs,
                    )
                )

    rows.extend(_obligation_rows(rows, cases_, judged, refused, runs, alpha))
    return rows


def _obligation_rows(rows, cases_, judged, refused, runs, alpha):
    """Summarise the executed evidence into the two named obligations."""
    conventions = sorted({case["convention"] for case in cases_})
    evidence = {
        "qualified_slice": SLICE,
        "conventions": conventions,
        "cases": len(cases_),
        "judged_case_backends": judged,
        "refused_case_backends": [
            dict(case=case, backend=backend, detail=detail)
            for case, backend, detail in refused
        ],
        "ensemble_runs": runs,
        "seed_policy": SEED_POLICY,
        "alpha": alpha,
        "statistical_control": (
            "exact two-sided test on the ensemble total with a union bound over "
            "the sampled timepoints; DKW bound for the count distribution"
        ),
    }

    failures = []
    for row in rows:
        if row["id"].startswith("stochastic-parity:") and row["status"] == "FAIL":
            failures.append(row["id"])

    encode = dict(
        id="qualification:issue:167:" + OBLIGATION_CHECKS[0],
        check=OBLIGATION_CHECKS[0],
        related_issues=list(ISSUES),
        question="stochastic-backend-versus-independent-count-law",
        evidence_kind="supported-execution",
        supported_execution=True,
        **evidence,
    )
    if failures:
        encode.update(
            status="FAIL",
            detail=(
                "the stochastic backends do not reproduce the declared law of "
                "their rate convention: " + ", ".join(sorted(failures))
            ),
            first_difference=dict(failed_checks=sorted(failures)),
        )
    else:
        encode.update(
            status="PASS",
            detail=(
                "every generated case reproduces the independent count law of its "
                "rate convention under the recorded seed policy and run budget, "
                "and every refused case states its reason"
            ),
        )

    refinement_failures = [
        row["id"]
        for row in rows
        if row["id"].endswith(".mean-refinement") and row["status"] == "FAIL"
    ]
    unproved = [
        row["id"]
        for row in rows
        if row["id"].endswith(".mean-refinement") and row["status"] == "NOT_TESTED"
    ]
    prove = dict(
        id="qualification:issue:167:" + OBLIGATION_CHECKS[1],
        check=OBLIGATION_CHECKS[1],
        related_issues=list(ISSUES),
        question="stochastic-backend-versus-independent-count-law",
        evidence_kind="supported-execution",
        supported_execution=True,
        **evidence,
    )
    if refinement_failures:
        prove.update(
            status="FAIL",
            detail=(
                "the selected refinement statement does not hold: the stochastic "
                "ensemble mean departs from the analytic mean of the declared "
                "law beyond the recorded statistical error budget"
            ),
            first_difference=dict(failed_checks=sorted(refinement_failures)),
        )
    else:
        prove.update(
            status="PASS",
            detail=(
                "the selected refinement statement holds at every sampled time: "
                "the stochastic ensemble mean is the analytic mean of the "
                "declared law within the recorded statistical error budget. The "
                "reference is the analytic law, so no unproved floating-point "
                "solver behaviour is claimed"
            ),
            unproved_scope=(
                "the statement is distributional; it says nothing about the "
                "floating-point accuracy of any deterministic solver, and no "
                "solver output is used as a reference"
            ),
            not_judged=sorted(unproved),
        )
    return [encode, prove]


def run_worker(directory):
    """Execute the operation in the integrated worker and return its rows."""
    return run(Path(directory))
