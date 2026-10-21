"""The NFnext execution boundary of issue #148.

NFnext is a bounded prototype: it lowers a production ``CompiledModel`` into
its own IR and executes a narrow subset of the semantics.  Issue #148 asks
for the supported seeds, observables, parameter/function graph, protocol and
output contract to be carried and initialized beyond topology and rules, and
for the production-lowered execution to be compared with reference fixtures
and an independent NFsim before NFnext is promoted as a replacement.

This module states that boundary as an executable contract:

* the C++ component that owns the NFnext semantics qualifies the supported
  subset and exports the recorded trajectories
  (``tests/architecture_contracts/nfnext/test_execution_boundary.cpp``).  The
  exported artifact is consumed here; this module never re-implements the
  NFnext execution;
* the artifact must state the same model the harness states, so a drifted
  prototype cannot pass against a fixture it no longer executes;
* the carried state is checked: the output contract names the declared
  observables in the declared order, the seeds are initialized to the
  declared counts, and the protocol produced the declared sample grid;
* the recorded ensemble is compared with the independent pure-death count
  law of the model, with a stated error control that also requires the
  observed mean to be separated from the law a wrong rate would produce;
* the parts of the model graph NFnext does not execute must be refused with
  a named reason, and the refusals are reported next to the executions;
* the recorded ensemble is compared with an independently built native NFsim
  distributionally, with the same fixed seeds and the same error control.
  The absence of the oracle is reported as an explicit untested route.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path

import numpy as np

from . import campaign, contracts, integrated_traces

ISSUES = (148,)

# The number of standard errors the reference comparison uses.  The recorded
# seed policy and run budget fix the sampling error, so the observed mean is
# accepted only when it is inside this many empirical standard errors of the
# independent count law and outside the same distance of the law a wrong rate
# would produce.
DISCRIMINATION_SIGMA = 4.0

# The stated error budget of the family.  The native comparison splits it
# across the fixtures.
FAMILY_ALPHA = 1e-6

CHECKS = ("carried-state", "reference-fixture", "native-independent")

# The generated fixture family.  Every fixture states a unary site-state rule
# with an elementary expression rate over the parameter graph, an isolated
# integer seed population and two unary Molecules observables.
FIXTURES = (
    dict(id="nfnext-unary-site-state-n100-k0.500000", initial=100, rate=0.5),
    dict(id="nfnext-unary-site-state-n40-k0.250000", initial=40, rate=0.25),
    dict(id="nfnext-unary-site-state-n200-k1.000000", initial=200, rate=1.0),
)

SAMPLE_TIMES = (0.0, 0.5, 1.0, 2.0)


def fixture_source(fixture) -> str:
    """The BNGL source of one fixture, in the shape the prototype executes."""
    return (
        "begin parameters\n"
        f"  k {fixture['rate']:g}\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(x~u~p)\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A(x~u) {fixture['initial']}\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules U A(x~u)\n"
        "  Molecules P A(x~p)\n"
        "end observables\n"
        "begin reaction rules\n"
        "  A(x~u) -> A(x~p) k\n"
        "end reaction rules\n"
    )


def check_ids(fixtures=None):
    """The stable check identities of the NFnext execution boundary."""
    ids = []
    for fixture in fixtures if fixtures is not None else FIXTURES:
        for name in CHECKS:
            ids.append(f"{fixture['id']}:nfnext-boundary:{name}")
    ids.append("nfnext-boundary:unsupported-refusals")
    return ids


def _row(fixture_id, name, status, detail, **evidence):
    return dict(
        id=f"{fixture_id}:nfnext-boundary:{name}",
        check=name,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        evidence_kind="supported-execution",
        supported_execution=status == "PASS",
        fixture=fixture_id,
        **evidence,
    )


def _boundary_row(name, status, detail, **evidence):
    return dict(
        id=f"nfnext-boundary:{name}",
        check=name,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        evidence_kind="supported-execution",
        supported_execution=status == "PASS",
        **evidence,
    )


def _run_prototype(binary, artifact, directory):
    """Run the NFnext component's qualification and read its artifact."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    command = [str(binary), str(artifact)]
    receipt = campaign.run_command(command, directory, 300, required=())
    if receipt["status"] != "PASS":
        return None, (
            "the NFnext execution-boundary qualification did not pass: "
            f"{receipt['status']}: {receipt['detail']}"
        )
    if not Path(artifact).is_file():
        return None, "the NFnext qualification produced no artifact"
    try:
        return json.loads(Path(artifact).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"the NFnext artifact could not be read: {exc}"


def _reference_mean(fixture):
    """The independent pure-death count law of the fixture.

    Every particle converts independently at the declared rate, so the count
    of unconverted particles at time t is binomial(n, exp(-k t)) and its mean
    is n exp(-k t).
    """
    return fixture["initial"] * math.exp(-fixture["rate"] * SAMPLE_TIMES[-1])


def _alternative_mean(fixture):
    """The count law a wrong rate would produce."""
    return fixture["initial"] * math.exp(-2.0 * fixture["rate"] * SAMPLE_TIMES[-1])


def _native_samples(fixture, directory, native_binary):
    """The independently built native NFsim ensemble of one fixture."""
    source = Path(directory) / "fixture.bngl"
    Path(directory).mkdir(parents=True, exist_ok=True)
    source.write_text(fixture_source(fixture), encoding="utf-8")
    xml = Path(directory) / "model.xml"
    import bionetgen

    with contextlib.redirect_stdout(io.StringIO()):
        bionetgen.load(str(source)).write_xml(str(xml))
    normalisation = integrated_traces.native_count_rate_xml(
        xml, Path(directory) / "count-rate-model.xml"
    )
    if normalisation["status"] != "NORMALISED":
        return None, (
            "the native NFsim oracle cannot be handed this model in the "
            "executed count-rate convention: " + str(normalisation["detail"])
        )
    samples = []
    for seed in range(64):
        work = Path(directory) / f"seed-{seed}"
        work.mkdir(parents=True, exist_ok=True)
        receipt = campaign.run_command(
            [
                str(native_binary),
                "-xml",
                str(normalisation["path"]),
                "-o",
                str(work / "trajectory.gdat"),
                "-sim",
                str(SAMPLE_TIMES[-1]),
                "-oSteps",
                str(len(SAMPLE_TIMES) - 1),
                "-seed",
                str(seed),
            ],
            work,
            60,
            required=("trajectory.gdat",),
        )
        if receipt["status"] != "PASS":
            return None, (
                f"the native NFsim run failed: {receipt['status']}: {receipt['detail']}"
            )
        data, columns = contracts._trajectory(work / "trajectory.gdat")
        if "U" not in columns:
            return None, "the native NFsim output does not report the observable U"
        samples.append(float(data[-1, columns.index("U")]))
    return np.asarray(samples), None


class contextlib_redirect_stdout:
    """Silence the engine's console output while a component is driven."""

    def __enter__(self):
        self._context = contextlib.redirect_stdout(io.StringIO())
        return self._context.__enter__()

    def __exit__(self, *args):
        return self._context.__exit__(*args)


def run(
    directory,
    *,
    native_binary=None,
    prototype_binary=None,
    alpha=None,
    fixtures=None,
):
    """Execute the NFnext execution-boundary qualification."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = list(fixtures) if fixtures is not None else list(FIXTURES)
    alpha = alpha if alpha is not None else FAMILY_ALPHA / max(1, len(fixtures))
    rows = []
    artifact_path = directory / "nfnext-boundary.json"
    if prototype_binary is None or not Path(prototype_binary).is_file():
        reason = (
            "the NFnext execution-boundary qualification binary is unavailable: "
            f"{prototype_binary}"
        )
        for fixture in fixtures:
            for name in CHECKS:
                rows.append(
                    _row(
                        fixture["id"],
                        name,
                        "NOT_TESTED",
                        "the NFnext component produced no observation: " + reason,
                        applicability="nfnext-boundary-binary-unavailable",
                    )
                )
        rows.append(
            _boundary_row(
                "unsupported-refusals",
                "NOT_TESTED",
                "the NFnext component produced no observation: " + reason,
                applicability="nfnext-boundary-binary-unavailable",
            )
        )
        return rows

    artifact, reason = _run_prototype(
        prototype_binary, artifact_path, directory / "prototype"
    )
    if artifact is None:
        for fixture in fixtures:
            for name in CHECKS:
                rows.append(
                    _row(
                        fixture["id"],
                        name,
                        "FAIL",
                        "the NFnext execution-boundary qualification failed: " + reason,
                    )
                )
        rows.append(
            _boundary_row(
                "unsupported-refusals",
                "FAIL",
                "the NFnext execution-boundary qualification failed: " + reason,
            )
        )
        return rows

    recorded = {entry["source"]: entry for entry in artifact.get("fixtures", [])}
    for fixture in fixtures:
        source = fixture_source(fixture)
        entry = recorded.get(source)
        if entry is None:
            for name in CHECKS:
                rows.append(
                    _row(
                        fixture["id"],
                        name,
                        "FAIL",
                        "the NFnext component did not execute the model this "
                        "fixture states; the prototype and the fixture family "
                        "have drifted apart",
                    )
                )
            continue

        # The carried state: the output contract, the initialized seeds and
        # the protocol grid.
        columns = entry.get("columns") or []
        initial_row = entry.get("initial_row") or []
        problems = []
        if columns != ["time", "U", "P"]:
            problems.append(
                "the output contract does not name the declared observables"
            )
        if len(initial_row) != 3 or abs(initial_row[1] - fixture["initial"]) > 1e-9:
            problems.append("the seeds are not initialized to the declared counts")
        if abs(initial_row[2] if len(initial_row) > 2 else 0.0) > 1e-9:
            problems.append("the initialized seed state is not the declared one")
        if list(entry.get("sample_times") or []) != list(SAMPLE_TIMES):
            problems.append("the protocol did not produce the declared sample grid")
        if entry.get("reason"):
            problems.append("the execution reported: " + entry["reason"])
        rows.append(
            _row(
                fixture["id"],
                "carried-state",
                "FAIL" if problems else "PASS",
                (
                    "the production lowering carried the supported seeds, the "
                    "observables, the parameter graph, the protocol and the "
                    "output contract"
                    if not problems
                    else "; ".join(problems)
                ),
                first_difference=dict(problems=problems) if problems else None,
                columns=columns,
                initial_row=initial_row,
                sample_times=entry.get("sample_times"),
                parameter_graph=dict(
                    rate=fixture["rate"],
                    parameter="k",
                    carried="elementary expression rate",
                ),
            )
        )

        # The independent reference fixture: the recorded ensemble mean
        # against the pure-death count law of the model, and its separation
        # from the law a wrong rate would produce.
        values = np.asarray(entry.get("final_unphosphorylated") or [], dtype=float)
        reference = _reference_mean(fixture)
        alternative = _alternative_mean(fixture)
        if values.size < 2:
            rows.append(
                _row(
                    fixture["id"],
                    "reference-fixture",
                    "FAIL",
                    "the NFnext component recorded no ensemble to compare",
                )
            )
        else:
            observed = float(values.mean())
            standard_error = float(values.std(ddof=1) / math.sqrt(values.size))
            within = abs(observed - reference) <= DISCRIMINATION_SIGMA * standard_error
            separated = (
                abs(observed - alternative) > DISCRIMINATION_SIGMA * standard_error
            )
            rows.append(
                _row(
                    fixture["id"],
                    "reference-fixture",
                    "PASS" if within and separated else "FAIL",
                    (
                        "the production-lowered execution reproduces the "
                        "independent count law of the model and is separated "
                        "from the law a wrong rate would produce"
                        if within and separated
                        else "the production-lowered execution does not "
                        "reproduce the independent count law of the model"
                    ),
                    first_difference=(
                        None
                        if within and separated
                        else dict(
                            observed_mean=observed,
                            reference_mean=reference,
                            alternative_mean=alternative,
                            standard_error=standard_error,
                        )
                    ),
                    observed_mean=observed,
                    reference_mean=reference,
                    standard_error=standard_error,
                    error_control=(
                        f"{DISCRIMINATION_SIGMA} empirical standard errors of the "
                        "recorded ensemble against the independent pure-death "
                        "count law of the model"
                    ),
                    ensemble_runs=int(values.size),
                    seed_policy="0 .. 63; the same seed set for every route",
                )
            )

        # The independently built native NFsim, compared distributionally.
        if native_binary is None or not Path(native_binary).is_file():
            rows.append(
                _row(
                    fixture["id"],
                    "native-independent",
                    "NOT_TESTED",
                    "the native NFsim comparison has no observation: the "
                    "independently built native NFsim binary is unavailable",
                    applicability="native-oracle-unavailable",
                )
            )
        else:
            oracle, reason = _native_samples(
                fixture, directory / fixture["id"], native_binary
            )
            if oracle is None:
                rows.append(
                    _row(
                        fixture["id"],
                        "native-independent",
                        "NOT_TESTED",
                        "the native NFsim comparison has no observation: " + reason,
                        applicability="native-oracle-unavailable",
                    )
                )
            else:
                status, detail, difference = _native_comparison(
                    values, oracle, alpha=alpha
                )
                rows.append(
                    _row(
                        fixture["id"],
                        "native-independent",
                        status,
                        detail,
                        first_difference=difference,
                        error_control=(
                            "exact two-sample Kolmogorov-Smirnov test at the "
                            "stated level and a two-sample Hoeffding bound on "
                            "the difference of the ensemble sums"
                        ),
                        alpha=alpha,
                        ensemble_runs=int(oracle.size),
                        oracle_identity="independently built native NFsim binary",
                    )
                )

    # The refusal controls of the unsupported model graph.
    refusals = artifact.get("refusals") or []
    unrefused = [entry["case"] for entry in refusals if not entry.get("refused")]
    missing = [
        case
        for case in ("function-rate", "compartment", "bonded-seed")
        if case not in {entry.get("case") for entry in refusals}
    ]
    problems = []
    if unrefused:
        problems.append(
            "the unsupported model graph was not refused: " + ", ".join(unrefused)
        )
    if missing:
        problems.append("the refusal controls are missing: " + ", ".join(missing))
    rows.append(
        _boundary_row(
            "unsupported-refusals",
            "FAIL" if problems else "PASS",
            (
                "every part of the model graph NFnext does not execute is "
                "refused with a named reason"
                if not problems
                else "; ".join(problems)
            ),
            first_difference=dict(problems=problems) if problems else None,
            refusals=[
                dict(case=entry.get("case"), refused=entry.get("refused"))
                for entry in refusals
            ],
        )
    )
    return rows


def _native_comparison(lowered, oracle, *, alpha):
    """Compare the NFnext ensemble with the independent native NFsim.

    The two engines are different implementations, so the claim is a
    distributional one: equal seeds establish pathwise parity only when the
    construction and the draw ordering are comparable, which this comparison
    does not assume.
    """
    from scipy.stats import ks_2samp

    lowered = np.asarray(lowered, dtype=float)
    oracle = np.asarray(oracle, dtype=float)
    if lowered.size != oracle.size:
        return (
            "FAIL",
            "the native NFsim and the NFnext ensembles have different sizes",
            dict(lowered=int(lowered.size), oracle=int(oracle.size)),
        )
    statistic, pvalue = ks_2samp(
        lowered, oracle, alternative="two-sided", method="exact"
    )
    # The two-sample Hoeffding bound on the difference of the ensemble means:
    # both samples are bounded by their own range, so the larger range bounds
    # both.
    scale = float(max(np.ptp(lowered), np.ptp(oracle), 1.0))
    bound = scale * math.sqrt(math.log(4 / alpha) / (2 * lowered.size))
    difference = abs(float(lowered.mean()) - float(oracle.mean()))
    ok = pvalue >= alpha and difference <= bound
    return (
        "PASS" if ok else "FAIL",
        (
            "the independently built native NFsim and the production-lowered "
            "NFnext execution agree distributionally at the stated level"
            if ok
            else "the independently built native NFsim and the production-lowered "
            "NFnext execution disagree at the stated level"
        ),
        dict(
            ks_statistic=float(statistic),
            ks_pvalue=float(pvalue),
            mean_difference=difference,
            sum_difference=abs(float(np.sum(lowered)) - float(np.sum(oracle))),
            hoeffding_bound=bound,
            alpha=alpha,
        ),
    )
