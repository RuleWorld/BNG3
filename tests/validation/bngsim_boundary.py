"""Executable contract for the supported BNGsim boundary (ADR 0003; issue #144).

The BNGsim adapter boundary is stated here as an executable contract instead
of as prose.  For a generated set of finite-network models and methods a run
either

* lowers the model onto the BNGsim backend and reproduces an independent
  closed-form law, or
* falls back to the native backend with an explicit, named, recorded decision.

The expectation is always an independent law -- the analytic amount
trajectory or the exact count law of the generated model -- never another
implementation's output.  A fallback that is not named and recorded is a
failure, and an explicit BNGsim request that cannot be honoured is refused
rather than downgraded silently.

The semantic boundary is a property of the model, not of the build, so it is
confirmed through the adapter's own lowering check, which is compiled in every
build.  The BNGsim route itself can only be executed where the adapter is
linked; that difference is reported as an explicit unsupported route instead
of being hidden.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import integrated_marginals
from .integrated_cases import (
    RATE,
    REVERSE_RATE,
    TIMES,
    expected_trajectory,
)

ISSUES = (144,)
METHODS = ("ode", "ssa")
POPULATIONS = (20, 80)
UNSUPPORTED_POPULATION = 20

# Ensemble budget and error budget for the stochastic route.  The bound is a
# Hoeffding/DKW bound over the recorded ensemble, not a pathwise equivalence
# claim; the family budget is stated here before execution and split across
# the generated cases.
ENSEMBLE_RUNS = 128
FAMILY_ALPHA = 1e-6

# The named routes the engine may record.  A route outside this set is a
# contract violation, not a new decision.
ROUTES = (
    "native-explicit",
    "bngsim-explicit",
    "native-fallback:unsupported-semantics",
    "native-fallback:bngsim-unavailable",
    "native-fallback:method-not-claimed",
    "native-policy:auto-native-during-migration",
)

# Analytic comparison thresholds for the deterministic route.  The solver is
# run far tighter than this so the comparison measures the route, not the
# solver tolerance.
ODE_RTOL = 1e-8
ODE_ATOL = 1e-9
SOLVER_RTOL = 1e-10
SOLVER_ATOL = 1e-12


def _decay_rule(rate_law: str, compartment: bool) -> str:
    source = "@cell:A()" if compartment else "A()"
    product = "@cell:B()" if compartment else "B()"
    return f"  forward: {source} -> {product} {rate_law}\n"


def _source(
    *,
    population: int,
    parameters: str,
    rules: str,
    compartment: bool = False,
    functions: str = "",
    actions: str = "",
) -> str:
    pattern_a = "@cell:A()" if compartment else "A()"
    pattern_b = "@cell:B()" if compartment else "B()"
    blocks = ["begin model"]
    if compartment:
        blocks.append("begin compartments\n  cell 1 1\nend compartments")
    if functions:
        blocks.append(functions.rstrip("\n"))
    blocks.append("begin parameters\n" + parameters.rstrip("\n") + "\nend parameters")
    blocks.append("begin molecule types\n  A()\n  B()\nend molecule types")
    blocks.append(
        "begin seed species\n"
        f"  {pattern_a} {population}\n"
        f"  {pattern_b} 0\n"
        "end seed species"
    )
    blocks.append(
        "begin observables\n"
        f"  Molecules A {pattern_a}\n"
        f"  Molecules B {pattern_b}\n"
        "end observables"
    )
    blocks.append(
        "begin reaction rules\n" + rules.rstrip("\n") + "\nend reaction rules"
    )
    if actions:
        blocks.append(actions.rstrip("\n"))
    blocks.append("end model")
    return "\n".join(blocks) + "\n"


def _case(
    case_id: str,
    *,
    family: str,
    population: int,
    parameters: str,
    rules: str,
    lowerable: bool,
    expected_blocker: str | None = None,
    compartment: bool = False,
    functions: str = "",
    actions: str = "",
) -> dict:
    return dict(
        id=case_id,
        family=family,
        population=population,
        initial=population,
        reverse=False,
        lowerable=lowerable,
        expected_blocker=expected_blocker,
        source=_source(
            population=population,
            parameters=parameters,
            rules=rules,
            compartment=compartment,
            functions=functions,
            actions=actions,
        ),
    )


def cases() -> list:
    """Return the generated boundary cases.

    The lowerable families exercise an elementary parameter rate, a pair of
    elementary rates, and a bounded zero-argument function rate.  The
    unsupported families name one semantic class each, so a fallback is
    attributable to a recorded blocker rather than to "not supported".
    """
    result = []
    for population in POPULATIONS:
        result.append(
            _case(
                f"decay-n{population}",
                family="decay",
                population=population,
                parameters=f"  k {RATE:.17g}",
                rules=_decay_rule("k", False),
                lowerable=True,
            )
        )
        result.append(
            _case(
                f"reversible-n{population}",
                family="reversible",
                population=population,
                parameters=f"  kf {RATE:.17g}\n  kr {REVERSE_RATE:.17g}",
                rules=("  forward: A() -> B() kf\n" "  backward: B() -> A() kr\n"),
                lowerable=True,
            )
        )
        result.append(
            _case(
                f"functional-n{population}",
                family="decay",
                population=population,
                parameters=f"  k {RATE:.17g}",
                rules=_decay_rule("rate", False),
                functions=f"begin functions\n  rate() = {RATE:.17g}\nend functions",
                lowerable=True,
            )
        )
    population = UNSUPPORTED_POPULATION
    result.append(
        _case(
            f"compartment-n{population}",
            family="decay",
            population=population,
            parameters=f"  k {RATE:.17g}",
            rules=_decay_rule("k", True),
            compartment=True,
            lowerable=False,
            expected_blocker="compartments require a volume-aware bridge",
        )
    )
    result.append(
        _case(
            f"function-arguments-n{population}",
            family="decay",
            population=population,
            parameters=f"  k {RATE:.17g}",
            rules=_decay_rule("k", False),
            functions="begin functions\n  scale(x) = 2*x\nend functions",
            lowerable=False,
            expected_blocker="function arguments require a local-function bridge",
        )
    )
    result.append(
        _case(
            f"non-reference-rate-n{population}",
            family="decay",
            population=population,
            # 2*k with k=0.2 is the same effective rate as the decay family,
            # so the independent law is unchanged.
            parameters=f"  k {RATE / 2:.17g}",
            rules=_decay_rule("2*k", False),
            lowerable=False,
            expected_blocker="is not a direct parameter or function reference",
        )
    )
    result.append(
        _case(
            f"protocol-action-n{population}",
            family="decay",
            population=population,
            parameters=f"  k {RATE:.17g}",
            rules=_decay_rule("k", False),
            actions="begin actions\n  simulate_ode({t_end=>1})\nend actions",
            lowerable=False,
            expected_blocker="action execution requires a protocol bridge",
        )
    )
    return result


def check_ids() -> list:
    """Stable check identities for the boundary qualification."""
    ids = [
        f"bngsim-boundary:{case['id']}:{method}:{name}"
        for case in cases()
        for method in METHODS
        for name in ("route-decision", "independent-law")
    ]
    ids.append("bngsim-boundary:differential-native-routes")
    ids.append("bngsim-boundary:differential-bngsim-route")
    return ids


def _row(check_id: str, check: str, status: str, detail: str, **evidence) -> dict:
    row = dict(
        id=check_id,
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
    )
    row.update(evidence)
    return row


def _analytic_amounts(case: dict) -> dict:
    """Independent analytic amounts for the generated case (columns A, B)."""
    data, columns = expected_trajectory(case)
    return {
        "A": data[:, columns.index("A_amt")],
        "B": data[:, columns.index("B_amt")],
    }


def _ode_difference(observed: dict, case: dict) -> dict | None:
    """First difference between the route trajectory and the analytic law."""
    expected = _analytic_amounts(case)
    times = np.asarray(TIMES, dtype=float)
    if not np.allclose(
        np.asarray(observed["time"], dtype=float), times, rtol=0, atol=1e-9
    ):
        return dict(
            field="time",
            expected=[float(value) for value in times[:3]],
            observed=[float(value) for value in observed["time"][:3]],
        )
    for name in ("A", "B"):
        values = np.asarray(observed[name], dtype=float)
        reference = expected[name]
        if values.shape != reference.shape:
            return dict(
                field=name + ".shape",
                expected=list(reference.shape),
                observed=list(values.shape),
            )
        error = np.abs(values - reference)
        limit = ODE_ATOL + ODE_RTOL * np.abs(reference)
        bad = np.flatnonzero(error > limit)
        if len(bad):
            index = int(bad[0])
            return dict(
                field=name,
                time=float(times[index]),
                reference=float(reference[index]),
                observed=float(values[index]),
                absolute_error=float(error[index]),
                limit=float(limit[index]),
            )
    return None


def _ssa_difference(samples: dict, case: dict, *, alpha: float) -> dict | None:
    """First difference between the SSA ensemble and the exact count law."""
    values = np.asarray(samples["A"], dtype=float)
    partners = np.asarray(samples["B"], dtype=float)
    population = case["population"]
    if values.ndim != 2 or values.shape[1] != len(TIMES):
        return dict(field="sample.shape", observed=list(values.shape))
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        return dict(field="sample.finite")
    if not np.array_equal(values, np.rint(values)):
        return dict(field="sample.integer")
    if np.any(values > population):
        return dict(field="sample.bound", limit=population)
    # Conservation is exact for both generated families.
    total = values + partners
    if not np.allclose(total, population, rtol=0, atol=1e-9):
        index = int(np.flatnonzero(np.abs(total - population) > 1e-9)[0])
        return dict(
            field="conservation",
            time=float(TIMES[index]),
            expected=float(population),
            observed=float(total[index, 0]),
        )
    law_case = dict(
        family=case["family"],
        initial=case["initial"],
        reverse=case["reverse"],
        times=TIMES,
    )
    rows = integrated_marginals.assess_samples(values, law_case, alpha=alpha)
    for row in rows:
        if row["status"] != "PASS":
            return dict(
                field=row.get("check", "marginal"),
                detail=row.get("detail", ""),
                first_difference=row.get("first_difference"),
            )
    return None


def _collect_samples(source: Path, runs: int, directory: Path) -> dict:
    """Run the recorded SSA ensemble and return the observable samples."""
    import bionetgen

    samples = {"A": [], "B": []}
    for index in range(runs):
        seed = 1013 + 7919 * (index + 1)
        result = bionetgen.load(str(source)).simulate(
            method="ssa",
            t_end=float(TIMES[-1]),
            n_steps=len(TIMES) - 1,
            seed=seed,
        )
        for name in ("A", "B"):
            samples[name].append(np.asarray(result.observables[name], dtype=float))
    stacked = {name: np.asarray(values) for name, values in samples.items()}
    np.save(directory / "ssa-samples.npy", stacked)
    return stacked


def run(directory, *, runs: int = ENSEMBLE_RUNS, alpha: float | None = None) -> list:
    """Execute the boundary contract and return one row per named check."""
    import bionetgen
    from bionetgen import _bionetgen_cpp as cpp

    if alpha is None:
        alpha = FAMILY_ALPHA / max(1, len(cases()))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    native_evidence = []

    for case in cases():
        case_directory = directory / case["id"]
        case_directory.mkdir(parents=True, exist_ok=True)
        source = case_directory / "source.bngl"
        source.write_text(case["source"], encoding="utf-8")
        model = bionetgen.load(str(source))
        model.generate_network()

        lowering = cpp.check_bngsim_lowering(model._model, model._network)
        blockers = list(lowering.get("blockers", []))
        lowerable = bool(lowering.get("supported", False))

        for method in METHODS:
            decision = cpp.finite_backend_decision(
                model._model, model._network, requested="auto", method=method
            )
            explicit = cpp.finite_backend_decision(
                model._model, model._network, requested="bngsim", method=method
            )
            problems = []

            if decision["route"] not in ROUTES:
                problems.append(
                    dict(field="route", observed=decision["route"], expected="declared")
                )
            if decision["backend"] != "native":
                # The migration policy keeps the native backend as the default;
                # a route to BNGsim would have to be a deliberate change.
                problems.append(
                    dict(
                        field="auto.backend",
                        observed=decision["backend"],
                        expected="native",
                    )
                )
            if lowerable != case["lowerable"]:
                problems.append(
                    dict(
                        field="lowering.supported",
                        observed=lowerable,
                        expected=case["lowerable"],
                    )
                )
            if not lowerable and case["expected_blocker"] is not None:
                joined = "; ".join(blockers)
                if case["expected_blocker"] not in joined:
                    problems.append(
                        dict(
                            field="lowering.blocker",
                            observed=joined,
                            expected=case["expected_blocker"],
                        )
                    )
            if explicit["backend"] == "bngsim":
                expected_route = "bngsim-explicit"
            elif not lowerable:
                expected_route = "native-fallback:unsupported-semantics"
            else:
                expected_route = "native-fallback:bngsim-unavailable"
            if explicit["route"] != expected_route:
                problems.append(
                    dict(
                        field="explicit.route",
                        observed=explicit["route"],
                        expected=expected_route,
                    )
                )

            # An explicit BNGsim request must be honoured or refused; it is
            # never downgraded to a silent native run.
            refusal = None
            if explicit["backend"] != "bngsim":
                try:
                    model.simulate(
                        method=method,
                        t_end=float(TIMES[-1]),
                        n_steps=len(TIMES) - 1,
                        seed=7,
                        backend="bngsim",
                    )
                    problems.append(
                        dict(
                            field="explicit.refusal",
                            observed="native result returned",
                            expected="refusal",
                        )
                    )
                except RuntimeError as error:
                    refusal = str(error)
                    if explicit["route"] not in refusal:
                        problems.append(
                            dict(
                                field="explicit.refusal",
                                observed=refusal,
                                expected=explicit["route"],
                            )
                        )
                except Exception as error:  # pragma: no cover - defensive
                    problems.append(
                        dict(
                            field="explicit.refusal",
                            observed=f"{type(error).__name__}: {error}",
                            expected="refusal",
                        )
                    )

            # The automatic route must record the decision it took.
            result = model.simulate(
                method=method,
                t_end=float(TIMES[-1]),
                n_steps=len(TIMES) - 1,
                seed=7,
                rtol=SOLVER_RTOL,
                atol=SOLVER_ATOL,
            )
            observed_route = getattr(result, "backend_route", None)
            observed_reason = getattr(result, "backend_reason", None)
            if observed_route != decision["route"]:
                problems.append(
                    dict(
                        field="result.route",
                        observed=observed_route,
                        expected=decision["route"],
                    )
                )
            if observed_reason != decision["reason"]:
                problems.append(
                    dict(
                        field="result.reason",
                        observed=observed_reason,
                        expected=decision["reason"],
                    )
                )
            if getattr(result, "backend", None) != decision["backend"]:
                problems.append(
                    dict(
                        field="result.backend",
                        observed=getattr(result, "backend", None),
                        expected=decision["backend"],
                    )
                )

            rows.append(
                _row(
                    f"bngsim-boundary:{case['id']}:{method}:route-decision",
                    "route-decision",
                    "FAIL" if problems else "PASS",
                    (
                        "recorded route "
                        f"{decision['route']} for method '{method}'; explicit "
                        f"BNGsim request route {explicit['route']}"
                    ),
                    first_difference=problems[0] if problems else None,
                    route=decision["route"],
                    reason=decision["reason"],
                    explicit_route=explicit["route"],
                    explicit_refusal=refusal,
                    lowering_supported=lowerable,
                    lowering_blockers=blockers,
                    bngsim_available=bool(decision["bngsim_available"]),
                    bngsim_version=decision["bngsim_version"],
                )
            )

            if method == "ode":
                observed = {
                    "time": result.time,
                    "A": result.observables["A"],
                    "B": result.observables["B"],
                }
                difference = _ode_difference(observed, case)
                np.savetxt(
                    case_directory / "ode.gdat",
                    np.column_stack(
                        [
                            np.asarray(result.time, dtype=float),
                            np.asarray(result.observables["A"], dtype=float),
                            np.asarray(result.observables["B"], dtype=float),
                        ]
                    ),
                    header="time A B",
                    fmt="%.17g",
                )
            else:
                samples = _collect_samples(source, runs, case_directory)
                difference = _ssa_difference(samples, case, alpha=alpha)
                observed = {
                    "time": TIMES,
                    "A": np.mean(samples["A"], axis=0),
                    "B": case["population"] - np.mean(samples["A"], axis=0),
                }

            rows.append(
                _row(
                    f"bngsim-boundary:{case['id']}:{method}:independent-law",
                    "independent-law",
                    "FAIL" if difference else "PASS",
                    (
                        "native route amounts against the independent analytic law"
                        if method == "ode"
                        else "native route count marginals against the exact "
                        "count law"
                    ),
                    first_difference=difference,
                    expectation=(
                        "analytic amount trajectory of the generated model"
                        if method == "ode"
                        else "exact binomial count law of the generated model"
                    ),
                    ensemble_runs=runs if method == "ssa" else None,
                    alpha=alpha if method == "ssa" else None,
                )
            )
            native_evidence.append(
                dict(
                    case=case["id"],
                    method=method,
                    lowerable=lowerable,
                    difference=difference,
                    observed=observed,
                )
            )

    # Differential evidence: every route that this build can execute must
    # reproduce the same independent law, so the routes agree with each other
    # through that common reference.
    native_problems = [row for row in native_evidence if row["difference"]]
    rows.append(
        _row(
            "bngsim-boundary:differential-native-routes",
            "differential-native-routes",
            "FAIL" if native_problems else "PASS",
            (
                f"{len(native_evidence)} native ODE/SSA route observations "
                "compared against one independent law"
            ),
            first_difference=(
                dict(
                    case=native_problems[0]["case"],
                    method=native_problems[0]["method"],
                    detail=native_problems[0]["difference"],
                )
                if native_problems
                else None
            ),
            executed_routes=["native-ode", "native-ssa"],
        )
    )

    # The BNGsim route can only be executed where the adapter is linked.
    bngsim_available = bool(cpp.bngsim_available())
    bngsim_problems = []
    bngsim_executed = []
    if bngsim_available:
        for case in cases():
            if not case["lowerable"]:
                continue
            case_directory = directory / case["id"]
            source = case_directory / "source.bngl"
            model = bionetgen.load(str(source))
            model.generate_network()
            result = model.simulate(
                method="ode",
                t_end=float(TIMES[-1]),
                n_steps=len(TIMES) - 1,
                rtol=SOLVER_RTOL,
                atol=SOLVER_ATOL,
                backend="bngsim",
            )
            observed = {
                "time": result.time,
                "A": result.observables["A"],
                "B": result.observables["B"],
            }
            difference = _ode_difference(observed, case)
            bngsim_executed.append(case["id"])
            if difference:
                bngsim_problems.append(dict(case=case["id"], difference=difference))
        status = "FAIL" if bngsim_problems else "PASS"
        detail = (
            f"BNGsim route compared against the same independent law for "
            f"{len(bngsim_executed)} lowerable generated cases"
        )
    else:
        status = "UNSUPPORTED"
        detail = (
            "the BNGsim adapter is not linked into this build, so the BNGsim "
            "route cannot be executed; the native routes were compared against "
            "the same independent law instead"
        )
    rows.append(
        _row(
            "bngsim-boundary:differential-bngsim-route",
            "differential-bngsim-route",
            status,
            detail,
            first_difference=(
                dict(
                    case=bngsim_problems[0]["case"],
                    detail=bngsim_problems[0]["difference"],
                )
                if bngsim_problems
                else None
            ),
            executed_routes=["bngsim-ode"] if bngsim_available else [],
            unavailable_routes=[] if bngsim_available else ["bngsim-ode", "bngsim-ssa"],
        )
    )

    (directory / "boundary-plan.json").write_text(
        json.dumps(
            dict(
                cases=[case["id"] for case in cases()],
                check_ids=check_ids(),
                methods=list(METHODS),
                ensemble_runs=runs,
                alpha=alpha,
                routes=list(ROUTES),
                expectation=(
                    "analytic amount trajectory and exact binomial count law of "
                    "the generated model; never another implementation's output"
                ),
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return rows
