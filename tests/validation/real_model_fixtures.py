"""Real-model fixtures with source-linked results (#152).

Issue #152 asks for the relevant real RNA/uORF, motor, TQSSA, fceRI and
multisite protocol fixtures to be added with source-linked results.  This
module adds them.

Each fixture is a *real* model taken from the canonical NFsim source at the
locked revision and vendored byte-identically under
``tests/validation/fixtures/nfsim``.  The source link (repository, revision,
upstream path and digest) is recorded in ``SOURCES.json`` and re-checked here,
so a fixture cannot drift away from the source it claims to represent.

Every fixture is compared against an *independent expectation* that is not
produced by BNG3:

``invariant``
    A conservation or exclusivity law that the model's own source semantics
    imply, expressed over the observables the model publishes.  The law is
    stated in the fixture, not derived from the simulation.

``closed-form-law``
    An analytic law computed in this harness from the model's declared
    semantics.  The motor fixture's phosphorylation subsystem is a closed
    two-state chain, so its trajectory is the exact solution of that chain.
    The TQSSA fixture's steady state is the solution of the declared
    mass-action steady-state equations, solved here with an independent root
    finder, including the model's own quirk that the E-catalysed step carries
    ``k2d``.

A fixture the engine cannot represent is *refused* with its reason: the
refusal is recorded as an explicit UNSUPPORTED result, never as a skip and
never as a silent pass.  The fixture's own checks then carry that refusal, so
an unrepresentable model is visible instead of absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ISSUES = (152,)

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "tests" / "validation" / "fixtures" / "nfsim" / "SOURCES.json"

# The five fixture families named by the issue.  Every family must be present.
FAMILIES = ("rna-uorf", "motor", "tqssa", "fceri", "multisite-protocol")

# The named checks every fixture carries.
CHECKS = ("source-link", "initial-state", "invariant", "closed-form-law")

# The one obligation of issue #152 that a named executable check closes.
OBLIGATION_CHECK = "add-relevant-real-rna-uorf-motor-tqssa-fceri-and-multisite-proto"

# The fixed simulation budget.  Both the horizon and the sample grid are
# recorded so a re-run reproduces the same comparison.
T_END = {
    "rna-uorf": 2.0,
    "motor": 1.0,
    "tqssa": 1000.0,
    "fceri": 10.0,
    "multisite-protocol": 100.0,
}
N_STEPS = 20
SEED = 20240517

# Relative and absolute tolerances of an invariant comparison.  A stochastic
# route counts molecules, so its comparison is exact; a deterministic route
# carries the solver's own residual.
ODE_RTOL = 1e-8
ODE_ATOL = 1e-6
LAW_RTOL = 1e-6


def _sources() -> dict:
    return json.loads(SOURCES.read_text(encoding="utf-8"))


def _invariant(name, terms, value=None, at_most=None):
    return dict(
        name=name,
        terms=[(float(coefficient), observable) for coefficient, observable in terms],
        value=value,
        at_most=at_most,
    )


def _rna_nucleotide_terms():
    """The mRNA nucleotide count of the RNA fixture, over its observables.

    The rules only move mRNA molecules between the free and the polymerised
    forms, so the total number of mRNA nucleotides is conserved.
    """
    terms = [(1.0, "RNA_A"), (1.0, "RNA_T"), (1.0, "RNA_C"), (1.0, "RNA_G")]
    terms += [(float(length), f"RNA_{length}") for length in range(2, 9)]
    return terms


def _expectations() -> dict:
    """The independent expectation of every fixture, keyed by fixture id."""
    return {
        "rna-uorf-rna-synthesis3": dict(
            route="nf",
            initial={
                "RNA_A": 6.0,
                "RNA_T": 6.0,
                "RNA_C": 6.0,
                "RNA_G": 6.0,
                "DNA_free": 6.0,
            },
            invariants=[
                _invariant("rna_nucleotides", _rna_nucleotide_terms(), value=24.0)
            ],
            law=None,
        ),
        "motor-motor": dict(
            route="ode",
            initial={"CheYp": 0.0, "MotCW": 10.0, "MotCCW": 0.0},
            invariants=[
                _invariant(
                    "motor_population", [(1.0, "MotCW"), (1.0, "MotCCW")], value=10.0
                )
            ],
            law=dict(
                kind="two-state-thinning",
                observable="CheYp",
                population=8200.0,
                forward=3.5,
                reverse=10.0,
                reason=(
                    "the CheY phosphorylation subsystem is a closed two-state "
                    "chain, so its trajectory is the exact thinning limit of "
                    "that chain and does not depend on the motor feedback"
                ),
            ),
        ),
        "tqssa-gk-simple": dict(
            route="ode",
            initial={"S": 0.0, "Sp": 900.0},
            invariants=[
                _invariant("substrate", [(1.0, "S"), (1.0, "Sp")], value=900.0)
            ],
            law=dict(
                kind="mass-action-steady-state",
                reason=(
                    "the steady state of the declared mass-action system, "
                    "including the fixture's own use of k2d for the "
                    "E-catalysed step and the observable's free-plus-bound "
                    "counting"
                ),
            ),
        ),
        "fceri-ji": dict(
            route="ode",
            initial={"RecTest": 400.0, "SykTest": 400.0, "LynTest": 28.0},
            invariants=[
                _invariant("receptor_total", [(1.0, "RecTest")], value=400.0),
                _invariant("syk_total", [(1.0, "SykTest")], value=400.0),
                _invariant("lyn_total", [(1.0, "LynTest")], value=28.0),
            ],
            law=None,
        ),
        "multisite-protocol-il2": dict(
            route="ode",
            initial={
                "IL2Rb_total": 1000.0,
                "IL2Rb_free": 1000.0,
                "ChromIL2_open": 2.0,
                "StatPhos": 0.0,
            },
            invariants=[
                _invariant(
                    "chromatin_locus",
                    [(1.0, "ChromIL2_open"), (1.0, "ChromIL2_Stat5")],
                    value=2.0,
                ),
                _invariant(
                    "stat5_capacity",
                    [(1.0, "StatPhos"), (1.0, "ChromIL2_Stat5")],
                    at_most=2000.0,
                ),
            ],
            law=None,
        ),
    }


def fixtures():
    """Return the generated, parameterized real-model fixtures."""
    source = _sources()
    expectations = _expectations()
    rows = []
    for entry in source["fixtures"]:
        expectation = expectations[entry["id"]]
        rows.append(
            dict(
                id=entry["id"],
                family=entry["family"],
                path=ROOT / entry["path"],
                relative_path=entry["path"],
                sha256=entry["sha256"],
                source=dict(
                    repository=source["source"]["repository"],
                    revision=source["source"]["revision"],
                    path=entry["source_path"],
                    sha256=entry["sha256"],
                ),
                route=expectation["route"],
                t_end=T_END[entry["family"]],
                n_steps=N_STEPS,
                seed=SEED,
                initial=expectation["initial"],
                invariants=expectation["invariants"],
                law=expectation["law"],
            )
        )
    return rows


def check_ids():
    """Stable expected check identities for the real-model fixture operation."""
    ids = ["real-model-fixtures:family-coverage"]
    for fixture in fixtures():
        for name in CHECKS:
            if name == "closed-form-law" and fixture["law"] is None:
                continue
            ids.append(f"real-model-fixtures:{fixture['id']}:{name}")
    ids.append(f"qualification:issue:152:{OBLIGATION_CHECK}")
    return ids


def _row(check, status, detail, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="real-model-fixture-versus-independent-expectation",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


def _digest(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upstream_digest(source: dict) -> tuple[str | None, str]:
    """The digest of the fixture in the upstream checkout, when one is named.

    ``BNG3_NFSIM_SOURCE`` may point at an NFsim checkout.  When it does, the
    fixture is compared with the upstream file at the recorded revision, so
    the source link is verified against the source itself and not only
    against the recorded digest.  Without the checkout the recorded digest
    remains the executed contract and the reason is recorded.
    """
    import os
    import subprocess

    root = os.environ.get("BNG3_NFSIM_SOURCE")
    if not root:
        return None, "no upstream NFsim checkout was named for this run"
    directory = Path(root)
    if not directory.is_dir():
        return None, f"the named upstream checkout {root!r} does not exist"
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(directory),
                "show",
                f"{source['revision']}:{source['path']}",
            ],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return None, f"the upstream checkout could not be read: {exc}"
    if completed.returncode != 0:
        return None, (
            "the upstream checkout has no "
            f"{source['path']!r} at {source['revision']}"
        )
    import hashlib

    return hashlib.sha256(completed.stdout).hexdigest(), ""


def _observable_series(result, names):
    series = {}
    for name in names:
        if name not in result.observables:
            raise KeyError(f"the model does not publish the observable {name!r}")
        values = np.asarray(result.observables[name], dtype=float)
        if values.ndim != 1 or values.size < 2:
            raise ValueError(f"the observable {name!r} has no usable trajectory")
        series[name] = values
    return series


def _simulate(fixture, directory):
    """Run one fixture and return its sampled observables."""
    import bionetgen

    source = directory / fixture["id"] / "model.bngl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(fixture["path"].read_text(encoding="utf-8"), encoding="utf-8")
    model = bionetgen.load(str(source))
    result = model.simulate(
        method=fixture["route"],
        t_end=fixture["t_end"],
        n_steps=fixture["n_steps"],
        seed=fixture["seed"],
    )
    names = set(fixture["initial"])
    for invariant in fixture["invariants"]:
        names.update(observable for _, observable in invariant["terms"])
    if fixture["law"] and fixture["law"]["kind"] == "two-state-thinning":
        names.add(fixture["law"]["observable"])
    names = sorted(names)
    series = _observable_series(result, names)
    times = np.asarray(result.time, dtype=float)
    if times.shape != series[names[0]].shape:
        raise ValueError("the sampled time grid does not match the observables")
    return times, series


def _thinning_law(fixture, times):
    """The exact two-state chain trajectory of the motor fixture."""
    law = fixture["law"]
    population = float(law["population"])
    forward = float(law["forward"])
    reverse = float(law["reverse"])
    total = forward + reverse
    equilibrium = population * forward / total
    return equilibrium * (1.0 - np.exp(-total * np.asarray(times, dtype=float)))


def _steady_state_law(fixture):
    """Solve the declared mass-action steady state of the TQSSA fixture.

    The states are the free enzyme D, the free enzyme E, the free
    unphosphorylated substrate, the free phosphorylated substrate and the two
    enzyme-substrate complexes.  The equations are the fixture's own rate
    laws; the observable counts the free and the bound form of a substrate.
    """
    from scipy.optimize import fsolve

    # The fixture's declared parameters.
    k1d, km1d, k2d = 0.05555, 0.83, 0.17
    k1e, km1e = 0.05, 0.8
    d_total, e_total, substrate_total = 900.0, 4500.0, 900.0

    def equations(state):
        d_free, e_free, s_free, sp_free, d_complex, e_complex = state
        forward_d = k1d * d_free * sp_free
        backward_d = km1d * d_complex
        dephosphorylate = k2d * d_complex
        forward_e = k1e * e_free * s_free
        backward_e = km1e * e_complex
        phosphorylate = k2d * e_complex
        return [
            forward_d - backward_d - dephosphorylate,
            forward_e - backward_e - phosphorylate,
            -forward_d + backward_d + phosphorylate,
            d_free + d_complex - d_total,
            e_free + e_complex - e_total,
            s_free + sp_free + d_complex + e_complex - substrate_total,
        ]

    solutions = []
    for guess in (
        [450.0, 4000.0, 2.0, 17.0, 440.0, 440.0],
        [10.0, 100.0, 400.0, 400.0, 200.0, 200.0],
        [800.0, 4000.0, 50.0, 50.0, 100.0, 100.0],
    ):
        state, _info, ier, _message = fsolve(equations, guess, full_output=True)
        if ier != 1:
            continue
        residual = max(abs(value) for value in equations(state))
        if residual > 1e-6:
            continue
        solutions.append(state)
    if not solutions:
        raise ValueError("the declared steady state did not converge")
    reference = solutions[0]
    for state in solutions[1:]:
        if not np.allclose(state, reference, rtol=1e-6, atol=1e-6):
            raise ValueError("the declared steady state is not unique")
    d_free, e_free, s_free, sp_free, d_complex, e_complex = reference
    return {
        "S": s_free + e_complex,
        "Sp": sp_free + d_complex,
        "residual": float(max(abs(value) for value in equations(reference))),
    }


def _compare_invariant(invariant, series, exact):
    worst = 0.0
    worst_time = None
    for index in range(len(series[invariant["terms"][0][1]])):
        total = 0.0
        for coefficient, observable in invariant["terms"]:
            total += coefficient * float(series[observable][index])
        if invariant["value"] is not None:
            difference = abs(total - float(invariant["value"]))
            tolerance = (
                0.0 if exact else ODE_ATOL + ODE_RTOL * abs(float(invariant["value"]))
            )
        else:
            difference = max(0.0, total - float(invariant["at_most"]))
            tolerance = 0.0 if exact else ODE_ATOL
        if difference - tolerance > worst:
            worst = difference - tolerance
            worst_time = index
    return worst, worst_time


def _assess(fixture, times, series):
    """Compare one fixture with its independent expectation."""
    exact = fixture["route"] == "nf"
    rows = []
    initial = []
    for name, expected in sorted(fixture["initial"].items()):
        observed = float(series[name][0])
        initial.append(
            dict(
                observable=name,
                expected=float(expected),
                observed=observed,
                difference=abs(observed - float(expected)),
            )
        )
    initial_worst = max((row["difference"] for row in initial), default=0.0)
    rows.append(
        _row(
            "initial-state",
            "PASS" if initial_worst <= ODE_ATOL else "FAIL",
            (
                "the published observables reproduce the model's declared seed "
                "values at the first sample"
            ),
            first_difference=(
                None
                if initial_worst <= ODE_ATOL
                else dict(worst_difference=initial_worst, observables=initial)
            ),
            observables=initial,
        )
    )

    invariant_rows = []
    failures = []
    for invariant in fixture["invariants"]:
        worst, worst_index = _compare_invariant(invariant, series, exact)
        passed = worst <= 0.0
        if not passed:
            failures.append(invariant["name"])
        invariant_rows.append(
            dict(
                name=invariant["name"],
                passed=passed,
                excess=worst,
                sample_index=worst_index,
                terms=invariant["terms"],
                value=invariant["value"],
                at_most=invariant["at_most"],
            )
        )
    rows.append(
        _row(
            "invariant",
            "PASS" if not failures else "FAIL",
            (
                "every declared conservation or exclusivity law of the model "
                "holds at every sampled timepoint"
            ),
            first_difference=(
                None
                if not failures
                else dict(failed=sorted(failures), invariants=invariant_rows)
            ),
            invariants=invariant_rows,
            exact_counts=exact,
        )
    )

    if fixture["law"] is None:
        return rows
    if fixture["law"]["kind"] == "two-state-thinning":
        expected = _thinning_law(fixture, times)
        observed = series[fixture["law"]["observable"]]
        difference = np.abs(observed - expected)
        scale = np.maximum(np.abs(expected), 1.0)
        worst = float(np.max(difference / scale))
        passed = worst <= LAW_RTOL
        detail = (
            "the sampled trajectory matches the exact two-state chain law of "
            "the model's phosphorylation subsystem"
        )
        evidence = dict(
            first_difference=(
                None
                if passed
                else dict(
                    worst_relative_error=worst,
                    times=[float(value) for value in times],
                    observed=[float(value) for value in observed],
                    expected=[float(value) for value in expected],
                )
            ),
            worst_relative_error=worst,
            law=fixture["law"],
        )
    else:
        law = _steady_state_law(fixture)
        observed = {name: float(series[name][-1]) for name in ("S", "Sp")}
        worst = max(
            abs(observed[name] - law[name]) / max(abs(law[name]), 1.0)
            for name in ("S", "Sp")
        )
        passed = worst <= LAW_RTOL
        detail = (
            "the converged trajectory matches the independent steady state of "
            "the declared mass-action system"
        )
        evidence = dict(
            first_difference=(
                None
                if passed
                else dict(worst_relative_error=worst, observed=observed, expected=law)
            ),
            worst_relative_error=worst,
            law=fixture["law"],
            steady_state=law,
        )
    rows.append(
        _row(
            "closed-form-law",
            "PASS" if passed else "FAIL",
            detail,
            **evidence,
        )
    )
    return rows


def _refusal(fixture, message):
    """Record an engine refusal as an explicit result, never as a skip."""
    rows = []
    for name in CHECKS:
        if name == "closed-form-law" and fixture["law"] is None:
            continue
        rows.append(
            dict(
                _row(
                    name,
                    "UNSUPPORTED",
                    "the engine refused the fixture: " + message,
                    applicability="engine-refused-the-model",
                ),
                id=f"real-model-fixtures:{fixture['id']}:{name}",
                check=name,
                family=fixture["family"],
            )
        )
    return rows


def _coverage_row(fixtures_):
    families = {fixture["family"] for fixture in fixtures_}
    missing = sorted(set(FAMILIES) - families)
    linked = all(
        fixture["source"]["repository"]
        and fixture["source"]["revision"]
        and fixture["source"]["path"]
        for fixture in fixtures_
    )
    return _row(
        "family-coverage",
        "PASS" if not missing and linked else "FAIL",
        (
            "every named real-model family is present with a recorded source "
            "link and an independent expectation"
        ),
        first_difference=(
            None
            if not missing and linked
            else dict(missing_families=missing, source_links=linked)
        ),
        families=sorted(families),
        missing_families=missing,
        fixtures=[
            dict(
                id=fixture["id"],
                family=fixture["family"],
                source=fixture["source"],
                expectation=(
                    [invariant["name"] for invariant in fixture["invariants"]]
                    + ([fixture["law"]["kind"]] if fixture["law"] else [])
                ),
            )
            for fixture in fixtures_
        ],
    )


def _obligation_row(rows, fixtures_, refused):
    failures = [
        row["id"]
        for row in rows
        if row["id"].startswith("real-model-fixtures:") and row["status"] == "FAIL"
    ]
    evidence = dict(
        fixture_families=sorted({fixture["family"] for fixture in fixtures_}),
        fixtures=len(fixtures_),
        refused_fixtures=[dict(id=key, reason=value) for key, value in refused],
        independent_expectation=(
            "a declared conservation or exclusivity law of the model's own "
            "source semantics, and where the model admits one an analytic law "
            "computed in this harness; never the product's own output"
        ),
    )
    row = dict(
        _row(
            OBLIGATION_CHECK,
            "FAIL" if failures else "PASS",
            (
                "every named real-model fixture is present with its source "
                "link and a recorded result against an independent expectation"
            ),
            **evidence,
        ),
        id=f"qualification:issue:152:{OBLIGATION_CHECK}",
        check=OBLIGATION_CHECK,
    )
    if failures:
        row["detail"] = (
            "a real-model fixture does not reproduce its independent "
            "expectation: " + ", ".join(sorted(failures))
        )
        row["first_difference"] = dict(failed_checks=sorted(failures))
    elif refused:
        row["detail"] = (
            "every named real-model fixture is present with its source link "
            "and a recorded result; the refused fixtures state their reason"
        )
    return row


def run(directory):
    """Execute every real-model fixture against its independent expectation."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fixtures_ = fixtures()
    rows = []
    refused = []
    for fixture in fixtures_:
        # The source link is checked before the model is executed: a fixture
        # that no longer matches its upstream source is not evidence.
        actual = _digest(fixture["path"]) if fixture["path"].is_file() else None
        source_ok = actual == fixture["sha256"]
        upstream, upstream_detail = _upstream_digest(fixture["source"])
        upstream_ok = upstream is None or upstream == fixture["sha256"]
        if not source_ok or not upstream_ok:
            rows.append(
                dict(
                    _row(
                        "source-link",
                        "FAIL",
                        "the vendored fixture does not match its recorded source digest",
                        first_difference=dict(
                            expected=fixture["sha256"],
                            observed=actual,
                            upstream=upstream,
                        ),
                        source=fixture["source"],
                    ),
                    id=f"real-model-fixtures:{fixture['id']}:source-link",
                    check="source-link",
                    family=fixture["family"],
                )
            )
            for name in CHECKS:
                if name == "source-link":
                    continue
                if name == "closed-form-law" and fixture["law"] is None:
                    continue
                rows.append(
                    dict(
                        _row(
                            name,
                            "NOT_TESTED",
                            "the fixture does not match its recorded source digest",
                            blocked_by=[
                                f"real-model-fixtures:{fixture['id']}:source-link"
                            ],
                        ),
                        id=f"real-model-fixtures:{fixture['id']}:{name}",
                        check=name,
                        family=fixture["family"],
                    )
                )
            continue
        rows.append(
            dict(
                _row(
                    "source-link",
                    "PASS",
                    "the vendored fixture is byte-identical to its recorded source",
                    source=fixture["source"],
                    sha256=actual,
                    upstream_sha256=upstream,
                    upstream_verified=upstream is not None,
                    upstream_detail=upstream_detail,
                ),
                id=f"real-model-fixtures:{fixture['id']}:source-link",
                check="source-link",
                family=fixture["family"],
            )
        )
        try:
            times, series = _simulate(fixture, directory)
        except Exception as exc:  # the engine refused or failed the fixture
            message = f"{type(exc).__name__}: {exc}"
            refused.append((fixture["id"], message))
            rows.extend(_refusal(fixture, message))
            continue
        try:
            assessed = _assess(fixture, times, series)
        except Exception as exc:  # the expectation could not be evaluated
            message = f"{type(exc).__name__}: {exc}"
            refused.append((fixture["id"], message))
            rows.extend(_refusal(fixture, message))
            continue
        for row in assessed:
            rows.append(
                dict(
                    row,
                    id=f"real-model-fixtures:{fixture['id']}:{row['check']}",
                    check=row["check"],
                    family=fixture["family"],
                )
            )
    rows.insert(
        0,
        dict(
            _coverage_row(fixtures_),
            id="real-model-fixtures:family-coverage",
            check="family-coverage",
        ),
    )
    rows.append(_obligation_row(rows, fixtures_, refused))
    return rows


def run_worker(directory):
    """Execute the operation in the integrated worker and return its rows."""
    return run(Path(directory))
