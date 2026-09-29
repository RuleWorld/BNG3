"""Contracts for fail-closed SBML corpus classification."""

import importlib.util
from pathlib import Path


def _load_validator(name: str):
    path = Path(__file__).parents[2] / "scripts" / "ci" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sbml_test_suite_blocks_approximated_semantics_but_not_unit_notes():
    validator = _load_validator("validate_sbml_test_suite")
    warnings = [
        {
            "category": "stoichiometry",
            "message": "variable stoichiometry was fixed",
            "severity": "approximated",
        },
        {
            "category": "units",
            "message": "source numeric scale preserved",
            "severity": "info",
        },
    ]

    assert validator._simulation_limitations(warnings) == [
        "variable stoichiometry was fixed"
    ]


def test_stochastic_sbml_cases_select_ssa_for_event_translation():
    validator = _load_validator("validate_sbml_test_suite")

    assert validator._atomizer_actions_for_category("stochastic", 1.0, 10) == (
        'simulate({method=>"ssa", t_start=>0, t_end=>1, n_steps=>10})'
    )
    assert validator._atomizer_actions_for_category("semantic", 1.0, 10) == ""


def test_curated_biomodel_gate_blocks_approximated_semantics():
    validator = _load_validator("validate_published_biomodels")
    warnings = [
        {
            "category": "fastReaction",
            "message": "fast equilibrium was approximated",
            "severity": "approximated",
        },
        {
            "category": "units",
            "message": "source numeric scale preserved",
            "severity": "info",
        },
    ]

    assert validator._simulation_limitations(warnings) == [
        "fast equilibrium was approximated"
    ]


def test_curated_numerical_mismatch_retries_at_stricter_solver_tolerances(monkeypatch):
    validator = _load_validator("validate_published_biomodels")
    initial = {
        "passed": False,
        "failed_observables": ["low_abundance_total"],
        "rtol": 1e-7,
        "atol": 1e-12,
    }
    calls = []

    def compare(**kwargs):
        calls.append(kwargs)
        return {
            "passed": True,
            "rtol": kwargs["rtol"],
            "atol": kwargs["atol"],
            "max_step": kwargs["max_step"],
        }

    refined = validator._retry_numerical_comparison(
        initial,
        compare=compare,
        t_end=10.0,
        n_steps=100,
        rtol=1e-7,
        atol=1e-12,
        max_step=1e-4,
    )

    assert refined["passed"] is True
    assert refined["rtol"] == 1e-11
    assert refined["atol"] == 1e-20
    assert calls == [
        {
            "t_end": 10.0,
            "n_steps": 100,
            "rtol": 1e-11,
            "atol": 1e-20,
            "max_step": 1e-4,
        }
    ]


def test_curated_solver_refinement_keeps_original_on_failure_or_solver_error():
    validator = _load_validator("validate_published_biomodels")
    initial = {"passed": False, "failed_observables": ["x"]}

    def mismatch(**_kwargs):
        return {"passed": False, "failed_observables": ["x"]}

    def solver_error(**_kwargs):
        raise RuntimeError("CVODE failed")

    for compare in (mismatch, solver_error):
        result = validator._retry_numerical_comparison(
            initial,
            compare=compare,
            t_end=10.0,
            n_steps=100,
            rtol=1e-7,
            atol=1e-12,
            max_step=1e-4,
        )
        assert result["passed"] is False
        assert result["failed_observables"] == ["x"]


def test_event_lowering_replaces_parser_only_event_warning():
    generated = {
        "category": "event",
        "message": "fixed-time event lowered",
        "severity": "info",
    }
    parser = {
        "category": "event",
        "message": "event was not executed",
        "severity": "dropped",
    }

    for name in ("validate_sbml_test_suite", "validate_published_biomodels"):
        validator = _load_validator(name)
        merged = validator._merge_generated_warnings([parser], [generated])
        assert merged == [generated]


def test_unsupported_summary_retains_exact_ids_and_causes():
    for name in ("validate_sbml_test_suite", "validate_published_biomodels"):
        validator = _load_validator(name)
        records = [
            {
                "id": "case-a",
                "status": "unsupported",
                "unsupported_reason": "event trigger and stoichiometry are unsupported",
            },
            {"id": "case-b", "status": "passed"},
        ]
        summary = validator._unsupported_summary(records)
        assert summary["record_count"] == 1
        assert summary["by_cause"]["events"]["ids"] == ["case-a"]
        assert summary["by_cause"]["stoichiometry"]["ids"] == ["case-a"]
        assert summary["by_cause"]["events"]["records"] == ["case-a"]
        assert records[0]["unsupported_causes"] == ["events", "stoichiometry"]
        assert records[0]["unsupported_subcauses"] == {
            "stoichiometry": ["unclassified_stoichiometry"]
        } | (
            {"events": ["unclassified_events"]}
            if name == "validate_sbml_test_suite"
            else {}
        )
        assert summary["intersection_summary"]["cause_cardinality"] == {"2": 1}
        assert summary["intersection_summary"]["pairwise"]["events + stoichiometry"][
            "records"
        ] == ["case-a"]


def test_stoichiometry_summary_separates_dynamic_and_constant_boundaries():
    validator = _load_validator("validate_sbml_test_suite")
    records = [
        {
            "category": "semantic",
            "id": "dynamic",
            "status": "unsupported",
            "unsupported_reason": "variable stoichiometryMath was lowered",
        },
        {
            "category": "semantic",
            "id": "fractional",
            "status": "unsupported",
            "unsupported_reason": "unsupported stoichiometry 0.5",
        },
        {
            "category": "semantic",
            "id": "negative",
            "status": "unsupported",
            "unsupported_reason": "unsupported stoichiometry -1",
        },
    ]
    summary = validator._unsupported_summary(records)
    assert summary["stoichiometry_subsummary"]["by_subcause"] == {
        "constant_negative": {
            "count": 1,
            "records": ["semantic/negative"],
        },
        "constant_noninteger": {
            "count": 1,
            "records": ["semantic/fractional"],
        },
        "dynamic_or_stoichiometryMath": {
            "count": 1,
            "records": ["semantic/dynamic"],
        },
    }
    assert validator._stoichiometry_subcauses(
        "SBML contains non-integer reaction stoichiometry"
    ) == ["constant_noninteger"]
    assert validator._stoichiometry_subcauses(
        "stoichiometry above the BNGL expansion limit"
    ) == ["constant_integer_above_expansion_limit"]


# Every refusal reason the BNGL event lowering can emit, with the subcause it
# must be booked under.  Copied verbatim from the ``untranslated`` reasons in
# python/bionetgen/atomizer/modern/events.py so the taxonomy cannot silently
# drift away from the diagnostics it is meant to describe.
EVENT_REFUSAL_REASONS = [
    (
        "state-triggered SBML events require stochastic jump scheduling",
        "state_trigger_not_schedulable",
    ),
    (
        "trigger is not a simple time threshold (state-dependent "
        "triggers cannot be scheduled)",
        "state_trigger_not_schedulable",
    ),
    (
        'trigger time "12" does not reduce to a constant',
        "trigger_time_not_constant",
    ),
    (
        "state threshold crosses outside its fixed time gate",
        "trigger_outside_time_gate",
    ),
    (
        "volume change can cause the state trigger to re-enter within the "
        "simulation horizon",
        "trigger_reentry_within_horizon",
    ),
    (
        "exponential self-reset requires one undelayed event to prove that the "
        "trigger cannot re-enter",
        "exponential_self_reset",
    ),
    (
        "exponential self-reset has no proven trigger threshold",
        "exponential_self_reset",
    ),
    (
        "exponential self-reset does not assign its trigger state",
        "exponential_self_reset",
    ),
    (
        "exponential self-reset can make the state trigger re-enter within the "
        "simulation horizon",
        "exponential_self_reset",
    ),
    (
        "delayed interval assignment can create another rising trigger edge",
        "delayed_assignment_retrigger_edge",
    ),
    ('delay "3" is not constant', "delay_not_constant"),
    ('time scale "tau" is not a positive constant', "time_scale_not_positive_constant"),
    (
        "nonpersistent delayed event may be canceled at the window end",
        "nonpersistent_cancellation_at_window_end",
    ),
    (
        "simultaneous nonpersistent event cancellation could not be resolved",
        "simultaneous_cancellation_unresolved",
    ),
    (
        "simultaneous dynamic-priority event group could not be ordered soundly",
        "simultaneous_dynamic_priority_unordered",
    ),
    (
        "time-window bounds do not form a nonempty interval",
        "time_window_empty",
    ),
    (
        "time windows beginning at or before t=0 are not lowered",
        "time_window_starts_at_or_before_zero",
    ),
    (
        'assignment target "S2" is neither a known species nor a parameter',
        "assignment_target_unknown",
    ),
    ('priority "2" is not compile-time constant', "priority_not_constant"),
    (
        'assignment "S1 := S1 + 1" is not constant (depends on species/time or '
        "a function)",
        "assignment_not_constant",
    ),
    (
        "event state at execution time is not finite",
        "trigger_state_not_finite",
    ),
]


def test_event_unsupported_cause_is_subclassified():
    validator = _load_validator("validate_sbml_test_suite")

    # 1. Every refusal reason the lowering can emit lands in exactly one bucket.
    for reason, expected in EVENT_REFUSAL_REASONS:
        detail = (
            "Generated BNGL retained untranslated SBML event(s). "
            f"Details: event e0: {reason}"
        )
        assert validator._event_unsupported_subcauses(detail) == [expected], reason

    # 2. No refusal reason falls through unclassified.
    classified = {reason for reason, _ in EVENT_REFUSAL_REASONS}
    markers = [marker for _, marker in validator._EVENT_REFUSAL_SUBCAUSES]
    for reason in classified:
        assert any(
            marker in reason.lower() for marker in markers
        ), f"unclassified event refusal reason: {reason}"

    # 3. An event refusal with no recognised reason text is still booked, not
    #    collapsed into the bare ``events`` cause.
    assert validator._event_unsupported_subcauses(
        "3 SBML event(s) parsed; 0 fixed-time event(s) lowered to scheduled "
        "actions, while 1 state-dependent or non-constant event(s) remain "
        "untranslated."
    ) == ["unclassified_events"]

    # 4. The buckets are surfaced in the summary alongside the stoichiometry
    #    subcauses, and each subcause is filed under exactly one parent cause.
    records = [
        {
            "category": "semantic",
            "id": "trigger",
            "status": "unsupported",
            "unsupported_reason": (
                "Generated BNGL retained untranslated SBML event(s); "
                "state-dependent or dynamic event scheduling is outside the "
                "BNGL action engine. Details: event e0: trigger is not a "
                "simple time threshold (state-dependent triggers cannot be "
                "scheduled) | trigger: (S1 > 1) | assign: S1 := 0"
            ),
        },
        {
            "category": "stochastic",
            "id": "priority",
            "status": "unsupported",
            "unsupported_reason": (
                'Details: event e3: priority "2" is not compile-time constant | '
                "trigger: true"
            ),
        },
        {
            "category": "stochastic",
            "id": "reentry",
            "status": "unsupported",
            "unsupported_reason": (
                "1 SBML event(s) parsed; 0 fixed-time event(s) lowered to "
                "scheduled actions, while 1 state-dependent or non-constant "
                "event(s) remain untranslated. Generated BNGL retained "
                "untranslated SBML event(s). Details: event e1: volume change "
                "can cause the state trigger to re-enter within the simulation "
                "horizon | trigger: true"
            ),
        },
    ]
    summary = validator._unsupported_summary(records)

    assert records[0]["unsupported_subcauses"] == {
        "events": ["state_trigger_not_schedulable"]
    }
    assert summary["events_subsummary"]["record_count"] == 3
    assert summary["events_subsummary"]["by_subcause"] == {
        "priority_not_constant": {"count": 1, "records": ["stochastic/priority"]},
        "state_trigger_not_schedulable": {"count": 1, "records": ["semantic/trigger"]},
        "trigger_reentry_within_horizon": {
            "count": 1,
            "records": ["stochastic/reentry"],
        },
    }

    # A subcause is only ever filed under a cause the record actually carries,
    # and never under more than one parent bucket.
    for record in records:
        causes = set(record["unsupported_causes"])
        assert set(record["unsupported_subcauses"]) <= causes
        assert len(record["unsupported_subcauses"]) == len(
            {key for key in record["unsupported_subcauses"]}
        )

    # Bookkeeping only: the pass/unsupported partition is untouched.
    assert summary["record_count"] == 3
    assert summary["by_cause"]["events"]["count"] == 3


def test_unsupported_summary_promotes_error_to_reason():
    validator = _load_validator("validate_sbml_test_suite")
    records = [
        {
            "category": "semantic",
            "id": "writer-error",
            "status": "unsupported",
            "error": "MathML writer rejected arcsin",
        }
    ]
    summary = validator._unsupported_summary(records)
    assert records[0]["unsupported_reason"] == "MathML writer rejected arcsin"
    assert summary["by_cause"]["mathml"]["records"] == ["semantic/writer-error"]


def test_observable_comparison_accepts_matching_nonfinite_math_results():
    import numpy as np

    validator = _load_validator("validate_sbml_test_suite")
    result = validator._compare_observable_samples(
        np.array([1.0, np.nan, np.inf, -np.inf]),
        np.array([1.0 + 1e-9, np.nan, np.inf, -np.inf]),
        tolerance=1e-6,
    )

    assert result["passed"] is True
    assert result["finite"] is False
    assert result["nonfinite_equivalent"] is True
    assert result["finite_sample_count"] == 1
    assert result["nonfinite_sample_count"] == 3


def test_observable_comparison_rejects_different_nonfinite_math_results():
    import numpy as np

    validator = _load_validator("validate_sbml_test_suite")
    result = validator._compare_observable_samples(
        np.array([np.nan, np.inf, -np.inf]),
        np.array([np.inf, np.inf, -np.inf]),
        tolerance=1e-6,
    )

    assert result["passed"] is False
    assert result["nonfinite_equivalent"] is False
