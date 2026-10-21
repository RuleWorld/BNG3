"""Generated NFsim fixture family: named features, routes and error control.

Issue #146 asks for fixtures covering scopes, dynamic rates, observables,
symmetry, deletion, filters, compartments and lifecycle with the selected
route asserted, and for a comparison of the direct route, the XML route and
an independently built native NFsim under fixed seeds and a stated error
control.

This module states that boundary as an executable contract instead of prose:

* every fixture names the NFsim feature it covers, the independent
  expectation it must satisfy (a source count law where one exists, exact
  invariants otherwise) and the observable the comparison reads;
* the selected route is asserted.  A fixture the direct path declines is
  reported as a decline with its attributed reason, never as a pass, and the
  XML route must report the XML construction path;
* the XML route must reproduce the direct route bit for bit under the same
  fixed seed, for every seed of the recorded budget;
* where an independent source count law exists, the ensemble of the executed
  route is compared against that law with the stated Hoeffding/DKW budget;
* the independently built native NFsim is compared distributionally with the
  same fixed seeds and the same error control.  Its absence is reported as an
  explicit untested route with the reason, never as a pass, and a model the
  oracle cannot be handed in the executed count-rate convention is reported
  the same way.

The comparison is distributional where the two engines are not the same
implementation.  Equal seeds establish pathwise parity only when the
construction and the draw ordering are comparable; the pathwise agreement
rate is therefore recorded as evidence next to the distributional result and
is not itself the claim.
"""

from __future__ import annotations

import contextlib
import io
import math
import os
from pathlib import Path

import numpy as np

from . import campaign, contracts, integrated_marginals, integrated_traces

ISSUES = (146,)

# The recorded seed and run budget.  The seeds are fixed before execution and
# are the same for every route, so the direct, XML and native legs of one
# fixture are compared on the same sample of trajectories.
SEED_BASE = 17
SEED_STRIDE = 7919
ENSEMBLE_RUNS = 8

# The family error budget.  The global alpha is split across the fixtures
# that carry an independent source count law; the per-check budget and the
# resulting Hoeffding/DKW bounds are recorded with every row.
FAMILY_ALPHA = 1e-6

T_END = 2.0
N_STEPS = 10
TIMES = tuple(float(value) for value in np.linspace(0, T_END, 11))

# The named checks of one fixture.
CHECKS = (
    "route",
    "source-law",
    "direct-xml-equality",
    "native-distributional",
)


def _fixture_source(text: str) -> str:
    return text.strip() + "\n"


# --------------------------------------------------------------------------- #
# The generated fixtures
# --------------------------------------------------------------------------- #
#
# Every fixture states the feature it covers, the ordered observable names the
# output contract must report, the exact invariants that must hold on every
# trajectory, and (where one exists) the independent source count law the
# ensemble must reproduce.

_SCOPE = """begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A(b~u~p)
  I(i)
end molecule types
begin seed species
  A(b~u!1).I(i!1) 20
end seed species
begin observables
  Molecules I_total I()
  Molecules A_phosphorylated A(b~p!?)
  Molecules A_unphosphorylated A(b~u!?)
end observables
begin functions
  f(x) = I_total(x)
end functions
begin reaction rules
  %x::A(b~u!1).I(i!1) -> %x::A(b~p!1).I(i!1) f(x)
end reaction rules
end model
"""

_DYNAMIC_RATE = """begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 40
  B() 0
end seed species
begin observables
  Molecules atotal A()
  Molecules btotal B()
end observables
begin functions
  base k + atotal
end functions
begin reaction rules
  r1: A() -> B() k * base()
end reaction rules
end model
"""

_OBSERVABLES = """begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 10
  A(b) 20
  B(a) 20
end seed species
begin observables
  Molecules Complex A(b!1).B(a!1)
  Molecules FreeA A(b)
  Molecules FreeB B(a)
end observables
begin reaction rules
  r1: A(b) + B(a) -> A(b!1).B(a!1) k
end reaction rules
end model
"""

_SYMMETRY = """begin model
begin parameters
  k 0.4
end parameters
begin compartments
  cell 3 1
end compartments
begin molecule types
  A()
  D()
end molecule types
begin seed species
  @cell:A() 12
  @cell:D() 0
end seed species
begin observables
  Molecules A @cell:A()
  Molecules D @cell:D()
end observables
begin reaction rules
  r1: @cell:A() + @cell:A() -> @cell:D() k
end reaction rules
end model
"""

_DELETION = """begin model
begin parameters
  k 1
end parameters
begin molecule types
  A(b)
  B(a,c)
  D()
end molecule types
begin seed species
  A(b!1).B(a!1,c!2) 100
  D() 1
end seed species
begin observables
  Molecules OA A()
  Molecules OB B()
  Molecules OD D()
end observables
begin reaction rules
  delete: A(b!1).B(a!1) -> 0 k DeleteMolecules
end reaction rules
end model
"""

_FILTERS = """begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A(b)
  B(a)
  C()
  D()
end molecule types
begin seed species
  A(b!1).B(a!1) 20
  A(b!2) 20
end seed species
begin observables
  Molecules Complex A(b!1).B(a!1)
  Molecules OC C()
  Molecules OD D()
end observables
begin reaction rules
  excluded: A(b!+) -> A(b!+) + C() k exclude_reactants(1,B())
  included: A(b!+) -> A(b!+) + D() k include_reactants(1,B())
end reaction rules
end model
"""

_COMPARTMENTS = """begin model
begin parameters
  k 0.4
end parameters
begin compartments
  cell 3 1
  membrane 3 1
end compartments
begin molecule types
  A()
  B()
end molecule types
begin seed species
  @cell:A() 20
  @membrane:B() 10
end seed species
begin observables
  Molecules A @cell:A()
  Molecules Bcell @cell:B()
  Molecules Bmembrane @membrane:B()
end observables
begin reaction rules
  r1: @cell:A() -> @cell:B() k
end reaction rules
end model
"""

_LIFECYCLE = """begin model
begin parameters
  kon 0.4
  koff 0.2
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 20
  B(a) 20
end seed species
begin observables
  Molecules OA A()
  Molecules OB B()
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  bind: A(b) + B(a) -> A(b!1).B(a!1) kon
  unbind: A(b!1).B(a!1) -> A(b) + B(a) koff
end reaction rules
end model
"""


def fixture_cases():
    """The generated NFsim fixture family of issue #146.

    The family covers the named features.  ``law`` states the independent
    source count law of the fixture where one exists; the law is the law of
    the model the fixture states, not another implementation's output.
    """
    return [
        dict(
            id="nfsim-fixture-scope",
            feature="scopes",
            source=_fixture_source(_SCOPE),
            observables=("I_total", "A_phosphorylated", "A_unphosphorylated"),
            invariants=(
                ("constant", "I_total", 20),
                ("non_decreasing", "A_phosphorylated"),
                ("changed", "A_phosphorylated"),
            ),
            law=dict(
                law="first-order",
                family="first-order",
                rate_convention="physical_source_law",
                quantity_basis="amount",
                initial=20,
                rate=1.0,
                volume=1.0,
                observable="A_unphosphorylated",
            ),
        ),
        dict(
            id="nfsim-fixture-dynamic-rate",
            feature="dynamic-rates",
            source=_fixture_source(_DYNAMIC_RATE),
            observables=("atotal", "btotal"),
            invariants=(
                ("sum_constant", ("atotal", "btotal"), 40),
                ("non_increasing", "atotal"),
                ("non_decreasing", "btotal"),
            ),
            law=None,
        ),
        dict(
            id="nfsim-fixture-observables",
            feature="observables",
            source=_fixture_source(_OBSERVABLES),
            observables=("Complex", "FreeA", "FreeB"),
            invariants=(
                ("sum_constant", ("FreeA", "Complex"), 30),
                ("sum_constant", ("FreeB", "Complex"), 30),
                ("non_decreasing", "Complex"),
            ),
            law=None,
        ),
        dict(
            id="nfsim-fixture-symmetry",
            feature="symmetry",
            source=_fixture_source(_SYMMETRY),
            observables=("A", "D"),
            invariants=(
                ("conserved", None, (("A", 1), ("D", 2)), 12),
                ("non_increasing", "A"),
            ),
            law=dict(
                law="second-order",
                family="second-order",
                rate_convention="bngl_count",
                quantity_basis="amount",
                initial=12,
                rate=0.4,
                volume=1.0,
                observable="A",
            ),
        ),
        dict(
            id="nfsim-fixture-deletion",
            feature="deletion",
            source=_fixture_source(_DELETION),
            observables=("OA", "OB", "OD"),
            invariants=(
                ("equal", "OA", "OB"),
                ("constant", "OD", 1),
                ("non_increasing", "OA"),
            ),
            law=dict(
                law="first-order",
                family="first-order",
                rate_convention="physical_source_law",
                quantity_basis="amount",
                initial=100,
                rate=1.0,
                volume=1.0,
                observable="OA",
            ),
        ),
        dict(
            id="nfsim-fixture-filters",
            feature="filters",
            source=_fixture_source(_FILTERS),
            observables=("Complex", "OC", "OD"),
            invariants=(
                ("constant", "Complex", 20),
                ("non_decreasing", "OC"),
                ("non_decreasing", "OD"),
            ),
            law=None,
        ),
        dict(
            id="nfsim-fixture-compartments",
            feature="compartments",
            source=_fixture_source(_COMPARTMENTS),
            observables=("A", "Bcell", "Bmembrane"),
            invariants=(
                ("sum_constant", ("A", "Bcell"), 20),
                ("constant", "Bmembrane", 10),
                ("non_increasing", "A"),
            ),
            law=None,
        ),
        dict(
            id="nfsim-fixture-lifecycle",
            feature="lifecycle",
            source=_fixture_source(_LIFECYCLE),
            observables=("OA", "OB", "AB"),
            invariants=(
                ("sum_constant", ("OA", "OB"), 40),
                ("changed", "AB"),
            ),
            law=None,
        ),
    ]


def check_ids(cases=None):
    """The stable check identities of the NFsim fixture family."""
    ids = []
    for case in cases if cases is not None else fixture_cases():
        for name in CHECKS:
            if name == "source-law" and case["law"] is None:
                continue
            ids.append(f"{case['id']}:nf-fixtures:{name}")
    return ids


# --------------------------------------------------------------------------- #
# Execution helpers
# --------------------------------------------------------------------------- #


def seed_for(index: int) -> int:
    """The fixed seed of one ensemble member."""
    return SEED_BASE + SEED_STRIDE * (index + 1)


@contextlib.contextmanager
def _route_environment(force_xml: bool):
    """Select the NFsim construction route for one call.

    The direct leg must not fall back to the XML route: a fallback would make
    a declined direct path read as an accepted XML run.
    """
    previous = {
        name: os.environ.get(name)
        for name in ("BNG_NFSIM_FORCE_XML", "BNG_NFSIM_ALLOW_XML_FALLBACK")
    }
    try:
        if force_xml:
            os.environ["BNG_NFSIM_FORCE_XML"] = "1"
            os.environ["BNG_NFSIM_ALLOW_XML_FALLBACK"] = "1"
        else:
            os.environ.pop("BNG_NFSIM_FORCE_XML", None)
            os.environ.pop("BNG_NFSIM_ALLOW_XML_FALLBACK", None)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _trajectory(result):
    """(data, columns) from a bionetgen SimResult; time first."""
    names = list(result.observables)
    data = np.column_stack(
        [np.asarray(result.time, dtype=float)]
        + [np.asarray(result.observables[name], dtype=float) for name in names]
    )
    return data, ["time", *names]


def run_route(source: Path, *, force_xml: bool, seed: int):
    """Run one fixture on one route and return (data, columns, path)."""
    import bionetgen

    with _route_environment(force_xml):
        # The engine prints progress on stdout; the harness records the
        # trajectory, not the console noise.
        with contextlib.redirect_stdout(io.StringIO()):
            result = bionetgen.load(str(source)).simulate(
                method="nf", t_end=T_END, n_steps=N_STEPS, seed=seed
            )
    data, columns = _trajectory(result)
    return data, columns, result.construction_path


def _invariant_failure(case, data, columns):
    """The first violated invariant of one trajectory, or None."""
    values = {name: data[:, columns.index(name)] for name in case["observables"]}
    for invariant in case["invariants"]:
        kind = invariant[0]
        if kind == "equal":
            left, right = invariant[1], invariant[2]
            if not np.array_equal(values[left], values[right]):
                return dict(
                    invariant="equal",
                    observables=[left, right],
                    detail="the two observables do not report the same counts",
                )
        elif kind == "constant":
            name, expected = invariant[1], invariant[2]
            if not np.all(values[name] == expected):
                return dict(
                    invariant="constant",
                    observables=[name],
                    expected=expected,
                    observed=[float(value) for value in values[name]],
                    detail="the observable is not constant at its declared value",
                )
        elif kind == "sum_constant":
            names, expected = invariant[1], invariant[2]
            total = np.sum([values[name] for name in names], axis=0)
            if not np.all(total == expected):
                return dict(
                    invariant="sum_constant",
                    observables=list(names),
                    expected=expected,
                    observed=[float(value) for value in total],
                    detail="the conserved total does not hold",
                )
        elif kind == "conserved":
            weights, expected = invariant[2], invariant[3]
            total = np.zeros(data.shape[0], dtype=float)
            for name, weight in weights:
                total = total + weight * values[name]
            if not np.all(total == expected):
                return dict(
                    invariant="conserved",
                    observables=[name for name, _ in weights],
                    expected=expected,
                    observed=[float(value) for value in total],
                    detail="the weighted total is not conserved",
                )
        elif kind == "non_increasing":
            name = invariant[1]
            if np.any(np.diff(values[name]) > 0):
                return dict(
                    invariant="non_increasing",
                    observables=[name],
                    detail="the observable increased although it may only decrease",
                )
        elif kind == "non_decreasing":
            name = invariant[1]
            if np.any(np.diff(values[name]) < 0):
                return dict(
                    invariant="non_decreasing",
                    observables=[name],
                    detail="the observable decreased although it may only increase",
                )
        elif kind == "changed":
            name = invariant[1]
            if values[name][0] == values[name][-1]:
                return dict(
                    invariant="changed",
                    observables=[name],
                    detail="the observable never changed although the rule fires",
                )
        else:
            raise ValueError(f"unknown invariant kind: {kind!r}")
    return None


def _row(case, name, status, detail, **evidence):
    row = dict(
        id=f"{case['id']}:nf-fixtures:{name}",
        check=name,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        evidence_kind="supported-execution",
        supported_execution=status == "PASS",
        fixture=case["id"],
        feature=case["feature"],
        seed_policy=f"{SEED_BASE} + {SEED_STRIDE} * (index + 1); fresh model per seed",
        **evidence,
    )
    return row


def _law_case(case):
    """The source count law descriptor of a fixture, in the harness shape."""
    law = dict(case["law"])
    law["times"] = TIMES
    return law


def _native_samples(case, source, directory, native_binary, seeds):
    """The native NFsim ensemble of one fixture, or (None, reason)."""
    import bionetgen

    if native_binary is None or not Path(native_binary).is_file():
        return None, "the independently built native NFsim binary is unavailable"
    xml = directory / "model.xml"
    with contextlib.redirect_stdout(io.StringIO()):
        bionetgen.load(str(source)).write_xml(str(xml))
    normalisation = integrated_traces.native_count_rate_xml(
        xml, directory / "count-rate-model.xml"
    )
    if normalisation["status"] != "NORMALISED":
        return None, (
            "the native NFsim oracle cannot be handed this model in the "
            "executed count-rate convention: " + str(normalisation["detail"])
        )
    samples = []
    for index, seed in enumerate(seeds):
        work = directory / f"seed-{seed}"
        work.mkdir(parents=True, exist_ok=True)
        receipt = campaign.run_command(
            [
                str(native_binary),
                "-xml",
                str(normalisation["path"]),
                "-o",
                str(work / "trajectory.gdat"),
                "-sim",
                str(T_END),
                "-oSteps",
                str(N_STEPS),
                "-seed",
                str(seed),
            ],
            work,
            60,
            required=("trajectory.gdat",),
        )
        if receipt["status"] != "PASS":
            return (
                None,
                f"native NFsim run failed: {receipt['status']}: {receipt['detail']}",
            )
        data, columns = contracts._trajectory(work / "trajectory.gdat")
        name = case["law"]["observable"] if case["law"] else case["observables"][0]
        if name not in columns:
            return None, (
                "the native NFsim output does not report the compared observable "
                f"{name!r}"
            )
        samples.append((data, columns))
    return samples, None


def _compared_observable(case, data, columns):
    """The observable column the fixture comparison reads."""
    name = case["law"]["observable"] if case["law"] else case["observables"][0]
    if name not in columns:
        raise ValueError(f"the compared observable {name!r} is missing")
    return name


def run(directory, *, native_binary=None, runs=ENSEMBLE_RUNS, alpha=None, cases=None):
    """Execute the NFsim fixture family and return its named check rows."""
    if type(runs) is not int or not 8 <= runs <= 64:
        raise ValueError("the fixture ensemble budget must be 8..64 runs")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cases = list(cases) if cases is not None else fixture_cases()
    law_cases = [case for case in cases if case["law"] is not None]
    alpha = alpha if alpha is not None else FAMILY_ALPHA / max(1, len(law_cases))
    seeds = [seed_for(index) for index in range(runs)]
    rows = []
    for case in cases:
        case_dir = directory / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "fixture.bngl"
        source.write_text(case["source"], encoding="utf-8")

        direct = {}
        xml = {}
        failure = None
        for index, seed in enumerate(seeds):
            try:
                data, columns, path = run_route(source, force_xml=False, seed=seed)
            except Exception as exc:  # noqa: BLE001 - the reason is reported
                failure = dict(
                    status="FAIL",
                    detail=("the direct route raised " f"{type(exc).__name__}: {exc}"),
                )
                break
            if path != "direct":
                failure = dict(
                    status="FAIL",
                    detail=(
                        "the direct route reported the construction path "
                        f"{path!r} instead of 'direct'"
                    ),
                )
                break
            direct[seed] = (data, columns)
        if failure is None:
            for index, seed in enumerate(seeds):
                try:
                    data, columns, path = run_route(source, force_xml=True, seed=seed)
                except Exception as exc:  # noqa: BLE001 - the reason is reported
                    failure = dict(
                        status="FAIL",
                        detail=("the XML route raised " f"{type(exc).__name__}: {exc}"),
                    )
                    break
                if path != "in-memory-xml":
                    failure = dict(
                        status="FAIL",
                        detail=(
                            "the XML route reported the construction path "
                            f"{path!r} instead of 'in-memory-xml'"
                        ),
                    )
                    break
                xml[seed] = (data, columns)

        if failure is not None:
            rows.append(
                _row(
                    case,
                    "route",
                    failure["status"],
                    failure["detail"],
                    first_difference=dict(route="direct", detail=failure["detail"]),
                )
            )
            for name in CHECKS:
                if name == "route":
                    continue
                if name == "source-law" and case["law"] is None:
                    continue
                rows.append(
                    _row(
                        case,
                        name,
                        "NOT_TESTED",
                        "the direct route did not execute, so this comparison "
                        "has no observation",
                        blocked_by=[f"{case['id']}:nf-fixtures:route"],
                    )
                )
            continue

        # The route assertion also carries the exact invariants of the
        # fixture: a route that runs but changes the model's meaning is not a
        # pass.
        invariant_failure = None
        for seed in seeds:
            data, columns = direct[seed]
            invariant_failure = _invariant_failure(case, data, columns)
            if invariant_failure is not None:
                invariant_failure = dict(invariant_failure, seed=seed, route="direct")
                break
        rows.append(
            _row(
                case,
                "route",
                "FAIL" if invariant_failure else "PASS",
                (
                    "the direct route was selected and the fixture invariants hold"
                    if invariant_failure is None
                    else "the direct route violated a fixture invariant"
                ),
                first_difference=invariant_failure,
                construction_path="direct",
                ensemble_runs=len(seeds),
                invariants=[list(invariant) for invariant in case["invariants"]],
            )
        )

        # The XML route must reproduce the direct route bit for bit.
        mismatch = None
        for seed in seeds:
            left_data, left_columns = direct[seed]
            right_data, right_columns = xml[seed]
            if left_columns != right_columns:
                mismatch = dict(
                    seed=seed,
                    reason="the observable columns differ between the routes",
                    direct_columns=left_columns,
                    xml_columns=right_columns,
                )
                break
            if not np.array_equal(left_data, right_data):
                difference = np.abs(left_data - right_data)
                mismatch = dict(
                    seed=seed,
                    reason="the XML route does not reproduce the direct route",
                    max_abs_difference=float(np.max(difference)),
                    column=left_columns[int(np.argmax(np.max(difference, axis=0)))],
                )
                break
        rows.append(
            _row(
                case,
                "direct-xml-equality",
                "FAIL" if mismatch else "PASS",
                (
                    "the XML route reproduces the direct route bit for bit under "
                    "every recorded seed"
                    if mismatch is None
                    else "the XML route does not reproduce the direct route"
                ),
                first_difference=mismatch,
                construction_path="in-memory-xml",
                ensemble_runs=len(seeds),
                comparison="exact equality (rtol=0, atol=0) of the whole trajectory",
            )
        )

        # The independent source count law, where the fixture has one.
        if case["law"] is not None:
            name = _compared_observable(case, direct[seeds[0]][0], direct[seeds[0]][1])
            samples = np.asarray(
                [direct[seed][0][:, direct[seed][1].index(name)] for seed in seeds]
            )
            law_rows = integrated_marginals.assess_samples(
                samples, _law_case(case), alpha=alpha
            )
            failed = [row for row in law_rows if row["status"] != "PASS"]
            rows.append(
                _row(
                    case,
                    "source-law",
                    "FAIL" if failed else "PASS",
                    (
                        "the executed ensemble reproduces the independent source "
                        "count law of this fixture"
                        if not failed
                        else "the executed ensemble does not reproduce the "
                        "independent source count law of this fixture"
                    ),
                    first_difference=(
                        failed[0].get("first_difference") if failed else None
                    ),
                    observable=name,
                    source_law=case["law"]["law"],
                    rate_convention=case["law"]["rate_convention"],
                    error_control=(
                        "Hoeffding bound on the ensemble mean and DKW bound on "
                        "the empirical count CDF against the independent source "
                        "count law"
                    ),
                    alpha=alpha,
                    per_check_budget=alpha / (3 * len(TIMES)),
                    ensemble_runs=len(seeds),
                    source_law_rows={row["check"]: row["status"] for row in law_rows},
                )
            )

        # The independently built native NFsim, compared distributionally.
        native, reason = _native_samples(case, source, case_dir, native_binary, seeds)
        if native is None:
            rows.append(
                _row(
                    case,
                    "native-distributional",
                    "NOT_TESTED",
                    "the native NFsim comparison has no observation: " + reason,
                    applicability="native-oracle-unavailable",
                    ensemble_runs=len(seeds),
                )
            )
            continue
        name = _compared_observable(case, direct[seeds[0]][0], direct[seeds[0]][1])
        embedded = np.asarray(
            [direct[seed][0][:, direct[seed][1].index(name)] for seed in seeds]
        )
        oracle = np.asarray([data[:, columns.index(name)] for data, columns in native])
        status, detail, difference = _native_comparison(embedded, oracle, alpha=alpha)
        rows.append(
            _row(
                case,
                "native-distributional",
                status,
                detail,
                first_difference=difference,
                observable=name,
                error_control=(
                    "exact two-sample Kolmogorov-Smirnov test at the stated level "
                    "and a two-sample Hoeffding bound on the difference of the "
                    "ensemble sums"
                ),
                alpha=alpha,
                ensemble_runs=len(seeds),
                oracle_identity="independently built native NFsim binary",
            )
        )
    return rows


def _native_comparison(embedded, oracle, *, alpha):
    """Compare two ensembles of the same fixture distributionally.

    The two engines are not the same implementation, so the claim is a
    distributional one.  The pathwise agreement rate is recorded next to it:
    equal seeds only establish pathwise parity when the construction and the
    draw ordering are comparable, which the distributional comparison does
    not assume.
    """
    from scipy.stats import ks_2samp

    if embedded.shape != oracle.shape:
        return (
            "FAIL",
            "the native NFsim and the executed route disagree on the trajectory "
            "shape",
            dict(embedded_shape=list(embedded.shape), oracle_shape=list(oracle.shape)),
        )
    identical = 0
    for left, right in zip(embedded, oracle):
        if left.shape == right.shape and np.array_equal(left, right):
            identical += 1
    statistic, pvalue = ks_2samp(
        embedded[:, -1], oracle[:, -1], alternative="two-sided", method="exact"
    )
    # The two-sample Hoeffding bound on the difference of the ensemble means:
    # both samples are bounded by their own range, so the larger range bounds
    # both.
    scale = float(max(np.ptp(embedded), np.ptp(oracle), 1.0))
    bound = scale * math.sqrt(math.log(4 / alpha) / (2 * len(embedded)))
    difference = abs(float(embedded[:, -1].mean()) - float(oracle[:, -1].mean()))
    ok = pvalue >= alpha and difference <= bound
    return (
        "PASS" if ok else "FAIL",
        (
            "the independently built native NFsim and the executed route agree "
            "distributionally at the stated level"
            if ok
            else "the independently built native NFsim and the executed route "
            "disagree at the stated level"
        ),
        dict(
            ks_statistic=float(statistic),
            ks_pvalue=float(pvalue),
            mean_difference=difference,
            sum_difference=abs(
                float(np.sum(embedded[:, -1])) - float(np.sum(oracle[:, -1]))
            ),
            hoeffding_bound=bound,
            pathwise_identical_runs=identical,
            pathwise_identical_fraction=identical / len(embedded),
        ),
    )
