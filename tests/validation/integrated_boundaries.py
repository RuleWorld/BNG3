"""Generated source-validated SBML boundary and execution controls.

Unsupported cases pass only with matching structured loss diagnostics. The
native-event cases are positive semantic checks: raw SBML runs in libRoadRunner
and must match BNG3 execution at the declared sample points.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any
from collections.abc import Mapping

ISSUES = (157, 158, 160, 161, 164)

# Variant formulas stay inside each unsupported semantic subclass. Nearby
# constant/simple cases are deliberately not included as rejection controls.
CASES = (
    ("delay_state_history_a", "delay", "delay(A, 1)", "rate"),
    ("delay_state_history_b", "delay", "delay(A, time / 2)", "rate"),
    ("algebraic_species_product", "algebraic", "A * B - 1", "algebraic"),
    ("algebraic_species_square", "algebraic", "A * A - 1", "algebraic"),
    ("variable_stoich_state_a", "stoichiometry", "1 + A", "stoichiometry"),
    ("variable_stoich_state_b", "stoichiometry", "A * B", "stoichiometry"),
)

# These source trajectories are independent positive controls.
SUPPORTED_EVENT_CASES = (
    ("event_dynamic_delay_a", "event-delay", "time > 1", "k = A * A"),
    ("event_dynamic_delay_b", "event-delay", "time > 2", "k = A * B"),
    ("event_state_nonlinear_a", "event", "time > 1", "k = A * A"),
    ("event_state_nonlinear_b", "event", "B > A", "k = A * B"),
)

_DIAGNOSTIC_MATCHERS = {
    "event": (
        frozenset({"event"}),
        re.compile(r"untranslated|state-dependent|not simulated", re.I),
    ),
    "event-delay": (
        frozenset({"event"}),
        re.compile(r"untranslated|state-dependent|not simulated", re.I),
    ),
    "delay": (frozenset({"delay", "mathml"}), re.compile(r"delay|history", re.I)),
    "algebraic": (
        frozenset({"algebraicRule"}),
        re.compile(r"algebraic|implicit DAE", re.I),
    ),
    "stoichiometry": (
        frozenset({"stoichiometry"}),
        re.compile(r"fast.*semantics prevent deterministic flux lowering", re.I),
    ),
}
_LOSS_SEVERITIES = frozenset({"dropped", "unsupported", "untranslated", "approximated"})
_CHECK_NAME = "explicit-loss-diagnostic"
_REGISTRY_NAME = "unsupported-boundary-contract"


def expected_check_ids() -> list[str]:
    """Declare expected worker evidence independently of runtime execution."""
    return [
        *(
            f"sbml-boundary:{case_id}:{_registry_name(case_id)}"
            for case_id, *_ in CASES
        ),
        *(
            f"sbml-event:{case_id}:source-trajectory"
            for case_id, *_ in SUPPORTED_EVENT_CASES
        ),
    ]


def _registry_name(case_id: str) -> str:
    if case_id == "delay_state_history_a":
        return "static-delay-execution"
    if case_id == "delay_state_history_b":
        return "dynamic-delay-execution"
    return _REGISTRY_NAME


def _source(libsbml: Any, case: tuple[str, str, str, str]) -> str:
    case_id, feature, first, second = case
    # fast reactions exist in L3V1 and were removed in L3V2.
    doc = libsbml.SBMLDocument(3, 1 if feature == "stoichiometry" else 2)
    model = doc.createModel()
    model.setId(case_id)
    comp = model.createCompartment()
    comp.setId("cell")
    comp.setConstant(True)
    comp.setSize(1.0)
    for sid, amount in (("A", 10.0), ("B", 1.0)):
        species = model.createSpecies()
        species.setId(sid)
        species.setCompartment("cell")
        species.setInitialConcentration(amount)
        species.setHasOnlySubstanceUnits(False)
        species.setBoundaryCondition(False)
        species.setConstant(False)
    rate = model.createParameter()
    rate.setId("k")
    rate.setValue(1.0)
    rate.setConstant(False)

    if feature in {"event", "event-delay"}:
        rule = model.createRateRule()
        rule.setVariable("B")
        rule.setMath(libsbml.parseL3Formula("1"))
        event = model.createEvent()
        event.setId("dynamic_event")
        event.setUseValuesFromTriggerTime(True)
        trigger = event.createTrigger()
        trigger.setInitialValue(False)
        trigger.setPersistent(True)
        trigger.setMath(libsbml.parseL3Formula(first))
        assignment = event.createEventAssignment()
        assignment.setVariable("k")
        assignment.setMath(libsbml.parseL3Formula(second.split("=", 1)[1].strip()))
        if feature == "event-delay":
            delay = event.createDelay()
            delay.setMath(libsbml.parseL3Formula("A / 2"))
        # Couple a nonlinear mutable rate rule to a state-dependent event.
        nonlinear = model.createRateRule()
        nonlinear.setVariable("A")
        nonlinear.setMath(libsbml.parseL3Formula("-k * A * A"))
    elif feature == "delay":
        rule = model.createRateRule()
        rule.setVariable("A")
        rule.setMath(libsbml.parseL3Formula(first))
    elif feature == "algebraic":
        rule = model.createAlgebraicRule()
        rule.setMath(libsbml.parseL3Formula(first))
    elif feature == "stoichiometry":
        reaction = model.createReaction()
        reaction.setId("R")
        reaction.setReversible(False)
        reactant = reaction.createReactant()
        reactant.setSpecies("A")
        reactant.setStoichiometry(1.0)
        reactant.setConstant(False)
        reactant.setId("nu")
        product = reaction.createProduct()
        product.setSpecies("B")
        product.setStoichiometry(1.0)
        product.setConstant(True)
        law = reaction.createKineticLaw()
        law.setMath(libsbml.parseL3Formula("k * A"))
        # BNG3 can lower ordinary dynamic stoichiometry into deterministic ODE
        # rules. A fast reaction cannot use that fallback and must be rejected.
        reaction.setFast(True)
        assignment = model.createAssignmentRule()
        assignment.setVariable("nu")
        assignment.setMath(libsbml.parseL3Formula(first))
    else:  # pragma: no cover - protected by the static case table
        raise ValueError(f"unknown feature class: {feature}")
    return libsbml.writeSBMLToString(doc)


def _validate_source(libsbml: Any, xml: str) -> list[str]:
    doc = libsbml.readSBMLFromString(xml)
    doc.checkConsistency()
    errors = []
    for index in range(doc.getNumErrors()):
        error = doc.getError(index)
        if error.getSeverity() >= libsbml.LIBSBML_SEV_ERROR:
            errors.append(error.getMessage().strip())
    if doc.getModel() is None:
        errors.append("libSBML did not produce a model")
    return errors


def _supported_event_row(case: tuple[str, str, str, str]) -> dict[str, Any]:
    """Create an unqualified positive-control row until execution is proven."""
    case_id = case[0]
    return {
        "id": f"sbml-event:{case_id}:source-trajectory",
        "stage": "sbml-native-event",
        "check": "source-trajectory",
        "status": "NOT_TESTED",
        "detail": "source validation or independent comparison did not complete",
        "related_issues": list(ISSUES),
        "case_id": case_id,
        "question": "source-trajectory",
        "expected_behavior": "native-event-matches-independent-sbml-execution",
        "evidence_kind": "supported-execution",
        "supported_execution": False,
        "labels": {"feature_class": "event", "native_event": True},
    }


def _valid_supported_event_row(row: dict[str, Any]) -> bool:
    """Require each positive event PASS to carry independent trajectory evidence."""
    if (
        row.get("evidence_kind") != "supported-execution"
        or row.get("expected_behavior")
        != "native-event-matches-independent-sbml-execution"
    ):
        return False
    if row.get("status") != "PASS":
        return row.get("supported_execution") is False
    return (
        row.get("supported_execution") is True
        and row.get("source_engine") == "libRoadRunner"
        and row.get("time_points") == 101
        and set(row.get("compared_observables", [])) == {"A", "B"}
    )


def _diagnostics(result: Any, atomizer: Any) -> list[dict[str, str]]:
    rows = []
    for warning in getattr(atomizer.model, "import_warnings", []) or []:
        field = (
            warning.get
            if isinstance(warning, Mapping)
            else lambda key, default=None: getattr(warning, key, default)
        )
        rows.append(
            dict(
                kind="import_warning",
                category=str(field("category", "")),
                severity=str(field("severity", "")),
                message=str(field("message", warning)),
            )
        )
    if not getattr(result, "success", False) and getattr(result, "error", None):
        rows.append(
            {
                "kind": "rejection",
                "category": "atomizer",
                "severity": "error",
                "message": str(result.error),
            }
        )
    return rows


def _run_supported_event_case(
    directory: Path, case: tuple[str, str, str, str]
) -> dict[str, Any]:
    """Compare a newly supported event model with its raw SBML execution."""
    case_id = case[0]
    row = _supported_event_row(case)
    try:
        import libsbml  # type: ignore
        import numpy as np
        import roadrunner  # type: ignore
        import bionetgen
        from bionetgen.atomizer.modern import Atomizer

        xml = _source(libsbml, case)
        source_path = directory / f"{case_id}.xml"
        source_path.write_text(xml, encoding="utf-8")
        source_errors = _validate_source(libsbml, xml)
        if source_errors:
            row.update(
                status="INVALID_INPUT",
                detail="libSBML rejected generated source: "
                + " | ".join(source_errors),
            )
            return row

        times = np.linspace(0.0, 10.0, 101)
        reference = roadrunner.RoadRunner(str(source_path.resolve()))
        reference.integrator.relative_tolerance = 1e-10
        reference.integrator.absolute_tolerance = 1e-12
        source_values = np.asarray(
            reference.simulate(times=times, selections=["time", "A", "B"]),
            dtype=float,
        )

        atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
        result = atomizer.atomize(xml, source_path=source_path)
        if not result.success:
            row.update(
                status="FAIL",
                detail=f"Atomizer rejected a supported event source: {result.error}",
            )
            return row
        event_losses = [
            item
            for item in _diagnostics(result, atomizer)
            if item.get("category") == "event"
            and item.get("severity", "").lower() in _LOSS_SEVERITIES
        ]
        if event_losses:
            row.update(
                status="FAIL",
                detail="native event source retained a structured event loss diagnostic",
                first_difference=event_losses,
            )
            return row

        bngl_path = directory / f"{case_id}.bngl"
        bngl_path.write_text(result.bngl, encoding="utf-8")
        model = bionetgen.load(str(bngl_path))
        compiled = model.simulate(
            method="ode", t_end=10.0, n_steps=100, rtol=1e-10, atol=1e-12
        )
        observables = compiled.observables
        names = {}
        for symbol in ("A", "B"):
            # SBML models with hasOnlySubstanceUnits=false expose concentration
            # selectors under the source id. Prefer that exact source symbol;
            # the amount alias is a fallback only when no concentration output
            # was created.
            observable_name = symbol if symbol in observables else f"{symbol}_amt"
            if observable_name not in observables:
                row.update(
                    status="UNSUPPORTED",
                    detail=(
                        f"could not uniquely map SBML species {symbol} to a BNG3 "
                        f"observable; available={list(observables)}"
                    ),
                )
                return row
            names[symbol] = observable_name
        actual = np.column_stack(
            (
                np.asarray(compiled.time, dtype=float),
                np.asarray(observables[names["A"]], dtype=float),
                np.asarray(observables[names["B"]], dtype=float),
            )
        )
        # The continuous root for B > A is independently located by each
        # solver; allow a few nanounits of state drift after that root while
        # keeping the comparison two orders tighter than the SBML suite gate.
        rtol, atol = 1e-8, 1e-9
        if source_values.shape != actual.shape or not np.allclose(
            source_values, actual, rtol=rtol, atol=atol
        ):
            difference: dict[str, Any] = {
                "source_shape": list(source_values.shape),
                "bng3_shape": list(actual.shape),
            }
            if source_values.shape == actual.shape:
                mismatches = np.argwhere(
                    ~np.isclose(source_values, actual, rtol=rtol, atol=atol)
                )
                if len(mismatches):
                    time_index, column = map(int, mismatches[0])
                    difference.update(
                        time_index=time_index,
                        variable=("time", "A", "B")[column],
                        source=float(source_values[time_index, column]),
                        bng3=float(actual[time_index, column]),
                    )
            row.update(
                status="FAIL",
                detail="BNG3 native-event trajectory differs from raw SBML in libRoadRunner",
                first_difference=difference,
            )
            return row

        row.update(
            status="PASS",
            detail=(
                "libSBML validated the source; BNG3 native-event ODE trajectory matched "
                "independent libRoadRunner for A, B, and time on 101 points"
            ),
            supported_execution=True,
            source_engine="libRoadRunner",
            source_engine_version=getattr(roadrunner, "__version__", None),
            time_points=101,
            compared_observables=["A", "B"],
            relative_tolerance=rtol,
            absolute_tolerance=atol,
        )
    except ImportError as exc:
        row.update(
            status="HARNESS_ERROR",
            detail=f"required independent event comparison dependency unavailable: {exc}",
        )
    except Exception as exc:
        row.update(status="FAIL", detail=f"{type(exc).__name__}: {exc}")
    return row


def classify_boundary_evidence(
    feature: str,
    diagnostics: list[dict[str, str]],
    *,
    result_success: bool = True,
) -> list[dict[str, str]]:
    """Select structured loss or actual rejection evidence; prose logs do not qualify."""
    if feature not in _DIAGNOSTIC_MATCHERS:
        raise ValueError(f"unknown feature class: {feature}")
    categories, pattern = _DIAGNOSTIC_MATCHERS[feature]
    return [
        item
        for item in diagnostics
        if (
            item.get("kind") == "import_warning"
            and item.get("category") in categories
            and item.get("severity", "").lower() in _LOSS_SEVERITIES
            and pattern.search(item.get("message", ""))
        )
        or (
            not result_success
            and item.get("kind") == "rejection"
            and item.get("category") == "atomizer"
            and item.get("severity", "").lower() == "error"
            and pattern.search(item.get("message", ""))
        )
    ]


def run(directory: Path) -> list[dict[str, Any]]:
    """Generate controls, retain source and diagnostics, and return evidence rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        import libsbml  # type: ignore
        import bionetgen
        from bionetgen.atomizer.modern import Atomizer
    except Exception as exc:
        return [
            _row(
                case,
                "NOT_TESTED",
                f"required Atomizer/libSBML dependency unavailable: {exc}",
            )
            for case in CASES
        ] + [
            {
                "id": f"sbml-event:{case[0]}:source-trajectory",
                "stage": "sbml-native-event",
                "check": "source-trajectory",
                "status": "NOT_TESTED",
                "detail": f"required Atomizer/libSBML dependency unavailable: {exc}",
                "related_issues": list(ISSUES),
                "case_id": case[0],
                "question": "source-trajectory",
                "expected_behavior": "native-event-matches-independent-sbml-execution",
                "evidence_kind": "supported-execution",
                "supported_execution": False,
            }
            for case in SUPPORTED_EVENT_CASES
        ]

    output = []
    for case in CASES:
        case_id, feature, *_ = case
        try:
            xml = _source(libsbml, case)
            source_path = directory / f"{case_id}.xml"
            source_path.write_text(xml, encoding="utf-8")
            source_errors = _validate_source(libsbml, xml)
            if source_errors:
                detail = f"invalid generated source; libSBML errors: {' | '.join(source_errors)}"
                output.append(_row(case, "HARNESS_ERROR", detail))
                continue
            # The Atomizer logger is process-global; clear it so this row cannot
            # borrow a diagnostic produced by an earlier generated model.
            from bionetgen.atomizer.modern.helpers import logger

            logger.clear()
            t_end = 1 if case_id == "delay_state_history_a" else 10
            atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": t_end})
            result = atomizer.atomize(xml, source_path=source_path)
            diagnostics = _diagnostics(result, atomizer)
            diagnostic_path = directory / f"{case_id}.diagnostics.json"
            diagnostic_path.write_text(
                json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8"
            )
            if case_id in {"delay_state_history_a", "delay_state_history_b"}:
                delay_losses = [
                    item
                    for item in diagnostics
                    if item.get("category") == "mathml"
                    and item.get("severity", "").lower() in _LOSS_SEVERITIES
                    and "delay" in item.get("message", "").lower()
                ]
                if not result.success or delay_losses:
                    execution = {
                        "passed": False,
                        "reason": (
                            "Atomizer rejected the source"
                            if not result.success
                            else "Atomizer retained a delay loss diagnostic"
                        ),
                        "diagnostics": delay_losses,
                    }
                elif case_id == "delay_state_history_a":
                    execution = _verify_static_delay_history(
                        bionetgen, result.bngl, directory, case_id
                    )
                else:
                    execution = _verify_dynamic_delay_history(
                        bionetgen, result.bngl, directory, case_id
                    )
                explicit_diagnostics = []
                static_delay = case_id == "delay_state_history_a"
                check = (
                    "static-delay-analytic-execution"
                    if static_delay
                    else "dynamic-delay-analytic-execution"
                )
                expected_behavior = (
                    "execute-static-delay-history"
                    if static_delay
                    else "execute-state-dependent-delay-history"
                )
                evidence_kind = "analytic-execution"
                supported_execution = execution["passed"]
                status = "PASS" if execution["passed"] else "FAIL"
                reason = (
                    "BNG3 trajectory matches the analytic delay-history law"
                    if execution["passed"]
                    else "BNG3 trajectory did not match the analytic delay history"
                )
                detail = (
                    f"{reason}; source={source_path}; diagnostics={diagnostic_path}; "
                    f"atomizer_success={bool(result.success)}; "
                    f"execution={json.dumps(execution, separators=(',', ':'))}; "
                    f"diagnostics={json.dumps(diagnostics, separators=(',', ':'))}"
                )
            else:
                explicit_diagnostics = classify_boundary_evidence(
                    feature, diagnostics, result_success=bool(result.success)
                )
                if result.success:
                    check = _CHECK_NAME
                    expected_behavior = "explicit-loss-diagnostic"
                    evidence_kind = "diagnostic-only"
                else:
                    check = "unsupported-boundary-contract"
                    expected_behavior = "reject-with-diagnostic"
                    evidence_kind = "atomizer-rejection"
                if explicit_diagnostics:
                    status = "PASS"
                    reason = "structured loss diagnostic records this unsupported semantic boundary"
                else:
                    status = "FAIL"
                    reason = f"valid source lacks a matching structured {feature} loss diagnostic"
                supported_execution = False
                detail = (
                    f"{reason}; source={source_path}; diagnostics={diagnostic_path}; "
                    f"atomizer_success={bool(result.success)}; "
                    f"diagnostics={json.dumps(diagnostics, separators=(',', ':'))}"
                )
            output.append(
                _row(
                    case,
                    status,
                    detail,
                    explicit=bool(explicit_diagnostics),
                    check=check,
                    expected_behavior=expected_behavior,
                    evidence_kind=evidence_kind,
                    supported_execution=supported_execution,
                )
            )
        except Exception as exc:
            output.append(_row(case, "HARNESS_ERROR", f"{type(exc).__name__}: {exc}"))
    for case in SUPPORTED_EVENT_CASES:
        row = _run_supported_event_case(directory, case)
        if not _valid_supported_event_row(row):
            row.update(
                status="HARNESS_ERROR",
                supported_execution=False,
                detail="positive event evidence row violated its independent-execution contract",
            )
        output.append(row)
    return output


def _verify_static_delay_history(
    bionetgen: Any, bngl: str, directory: Path, case_id: str
) -> dict[str, Any]:
    """Compare a bounded static-delay trajectory with its analytic source law."""

    if not bngl:
        return {"passed": False, "reason": "Atomizer produced no executable BNGL"}
    model_path = directory / f"{case_id}.bngl"
    model_path.write_text(bngl, encoding="utf-8")
    model = bionetgen.load(model_path)
    simulation = model.simulate(
        method="ode",
        t_start=0.0,
        t_end=1.0,
        n_steps=10,
        rtol=1e-9,
        atol=1e-12,
    )
    times = [float(value) for value in simulation.time]
    values = simulation.observables.get("A_amt")
    if values is None:
        values = simulation.observables.get("A")
    if values is None or len(values) != len(times) or len(times) != 11:
        return {
            "passed": False,
            "reason": "expected 11 time points and observable A_amt or A",
            "time_count": len(times),
            "observable_count": len(values) if values is not None else 0,
        }
    errors = [
        abs(float(value) - (10.0 + 10.0 * time)) for time, value in zip(times, values)
    ]
    max_error = max(errors, default=float("inf"))
    return {
        "passed": max_error <= 1e-8
        and all(abs(time - index / 10.0) <= 1e-12 for index, time in enumerate(times)),
        "reference": "A(t)=10+10*t on 0<=t<=1 from delay(A,1) and A(0)=10",
        "method": "BNG3 CVODE",
        "time_count": len(times),
        "observable": "A_amt" if "A_amt" in simulation.observables else "A",
        "max_abs_error": max_error,
    }


def _verify_dynamic_delay_history(
    bionetgen: Any, bngl: str, directory: Path, case_id: str
) -> dict[str, Any]:
    """Compare ``A' = delay(A, time/2)`` with its analytic power series."""

    if not bngl:
        return {"passed": False, "reason": "Atomizer produced no executable BNGL"}
    model_path = directory / f"{case_id}.bngl"
    model_path.write_text(bngl, encoding="utf-8")
    model = bionetgen.load(model_path)
    simulation = model.simulate(
        method="ode",
        t_start=0.0,
        t_end=10.0,
        n_steps=100,
        rtol=1e-10,
        atol=1e-12,
    )
    times = [float(value) for value in simulation.time]
    values = simulation.observables.get("A_amt")
    if values is None:
        values = simulation.observables.get("A")
    if values is None or len(values) != len(times) or len(times) != 101:
        return {
            "passed": False,
            "reason": "expected 101 time points and observable A_amt or A",
            "time_count": len(times),
            "observable_count": len(values) if values is not None else 0,
        }

    expected = []
    for time in times:
        terms = [10.0]
        for order in range(40):
            terms.append(terms[-1] * time / ((order + 1) * (2**order)))
        expected.append(math.fsum(terms))
    horizon_terms = [10.0]
    for order in range(40):
        horizon_terms.append(horizon_terms[-1] * 10.0 / ((order + 1) * (2**order)))
    largest_next_term_ratio = 10.0 / (41 * (2**40))
    series_tail_bound = (
        horizon_terms[-1] * largest_next_term_ratio / (1.0 - largest_next_term_ratio)
    )
    errors = [
        abs(float(value) - reference) for value, reference in zip(values, expected)
    ]
    max_error = max(errors, default=float("inf"))
    return {
        "passed": max_error <= 1e-5
        and series_tail_bound <= 1e-12
        and all(abs(time - index / 10.0) <= 1e-12 for index, time in enumerate(times)),
        "reference": "A(t)=sum(a_n*t^n), a_0=10, a_(n+1)=a_n/((n+1)*2^n), from A'=A(t/2)",
        "series_terms": 41,
        "series_truncation_tail_bound_at_t_10": series_tail_bound,
        "method": "BNG3 CVODE vs analytic series",
        "time_count": len(times),
        "observable": "A_amt" if "A_amt" in simulation.observables else "A",
        "max_abs_error": max_error,
    }


def _row(
    case: tuple[str, str, str, str],
    status: str,
    detail: str,
    *,
    explicit: bool = False,
    check: str = _CHECK_NAME,
    expected_behavior: str = "explicit-loss-diagnostic",
    evidence_kind: str | None = None,
    supported_execution: bool = False,
) -> dict[str, Any]:
    case_id, feature, *_ = case
    evidence_kind = evidence_kind or ("diagnostic-only" if explicit else "none")
    return {
        # Keep the original registry keys stable while the named check now
        # distinguishes diagnostic evidence from actual Atomizer rejection.
        "id": f"sbml-boundary:{case_id}:{_registry_name(case_id)}",
        "stage": "atomizer-boundary",
        "check": check,
        "status": status,
        "detail": detail,
        "related_issues": list(ISSUES),
        "case_id": case_id,
        "question": check,
        "expected_behavior": expected_behavior,
        "evidence_kind": evidence_kind,
        "supported_execution": supported_execution,
        "labels": {
            "rejected_feature": evidence_kind == "atomizer-rejection",
            "boundary_diagnostic": bool(explicit),
            "feature_class": feature,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run(args.report_dir)
    (args.report_dir / "integrated_boundaries.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, indent=2))
    return 1 if any(row["status"] in {"FAIL", "HARNESS_ERROR"} for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI contract
    raise SystemExit(main())
