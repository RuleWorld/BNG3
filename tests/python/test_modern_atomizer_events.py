"""Source-derived contracts for the Playground eventActions module."""


def test_playground_event_actions_exposes_reference_names_and_result_fields():
    from bionetgen.atomizer.modern.events import (
        EventActionsResult,
        EventSet,
        EventTranslationContext,
        foldNumeric,
        fold_numeric,
        parseTimeThreshold,
        parse_time_threshold,
        synthesizeEventActions,
        synthesize_event_actions,
    )

    assert foldNumeric is fold_numeric
    assert foldNumeric("1 + 2", lambda _identifier: None) == 3
    assert parseTimeThreshold is parse_time_threshold
    assert parseTimeThreshold("time >= 2") == "2"
    assert parse_time_threshold("time == 2.5") == "2.5"
    assert parse_time_threshold("eq(time, 2.5)") == "2.5"
    assert synthesizeEventActions is synthesize_event_actions

    context = EventTranslationContext(
        resolve_species_pattern=lambda identifier: f"{identifier}()",
        resolve_param=lambda _identifier: 2,
        is_param=lambda _identifier: True,
    )
    assert context.resolveSpeciesPattern("A") == "A()"
    context.baseTEnd = 20
    context.baseSteps = 5
    assert context.base_t_end == 20
    assert context.base_steps == 5

    event_set = EventSet("param", "k", 3, "k")
    assert (event_set.kind, event_set.target, event_set.value, event_set.variable) == (
        "param",
        "k",
        3,
        "k",
    )

    result = EventActionsResult(None, 0, [])
    assert result.actionsBlock is None
    result.actionsBlock = "simulate({})"
    assert result.actions_block == "simulate({})"


def test_fixed_time_window_event_is_scheduled_at_its_rising_edge():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="window",
        name="window",
        trigger="and(gt((time), 1.5), lt((time), 2.5))",
        delay="2",
        assignments=[SBMLEventAssignment("p", "3")],
        trigger_persistent=True,
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 0,
            is_param=lambda _identifier: True,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>3.5" in result.actions_block
    assert 'setParameter("p", "3")' in result.actions_block


def test_time_window_with_constant_gate_is_scheduled():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="gated-window",
        trigger="and(geq(time, 2), gt(enabled, 0))",
        assignments=[SBMLEventAssignment("p", "4")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda identifier: {"enabled": 1, "p": 0}.get(identifier),
            is_param=lambda _identifier: True,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>2" in result.actions_block


def test_time_window_with_false_constant_gate_is_dropped_as_never_firing():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="false-gated-window",
        trigger="and(geq(time, 2), gt(enabled, 0))",
        assignments=[SBMLEventAssignment("p", "4")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda identifier: {"enabled": 0, "p": 0}.get(identifier),
            is_param=lambda _identifier: True,
        ),
    )

    assert result.converted == 1
    assert result.actions_block is None
    assert result.untranslated == []


def test_time_window_with_mutable_gate_stays_untranslated():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="dynamic-gate",
        trigger="and(geq(time, 2), gt(enabled, 0))",
        assignments=[SBMLEventAssignment("p", "4")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda identifier: {"enabled": 1, "p": 0}.get(identifier),
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda identifier: identifier != "enabled",
        ),
    )

    assert result.converted == 0
    assert result.actions_block is None
    assert "state-dependent triggers" in result.untranslated[0][1]


def test_static_state_trigger_is_proven_never_firing():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="static-state",
        trigger="gt(S, 5)",
        trigger_initial_value=True,
        assignments=[SBMLEventAssignment("p", "4")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 0,
            is_param=lambda _identifier: True,
            resolve_initial_value=lambda identifier: {"S": 2}.get(identifier),
            resolve_affine_rate=lambda identifier: (
                (2, 0) if identifier == "S" else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.actions_block is None
    assert result.untranslated == []


def test_static_state_trigger_with_false_initial_value_fires_at_zero():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="static-state-edge",
        trigger="gt(S, 1)",
        trigger_initial_value=False,
        assignments=[SBMLEventAssignment("p", "4")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 0,
            is_param=lambda _identifier: True,
            resolve_initial_value=lambda identifier: {"S": 2}.get(identifier),
            resolve_affine_rate=lambda identifier: (
                (2, 0) if identifier == "S" else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("p", "4")' in result.actions_block


def test_time_only_sinusoidal_assignment_rule_expands_delayed_event_edges():
    from bionetgen.atomizer.modern import Atomizer

    source = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="sinusoidal_event">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialConcentration="0" boundaryCondition="true" constant="false"/>
      <species id="S2" compartment="c" initialConcentration="0" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <assignmentRule variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML"><piecewise><piece><apply><sin/><apply><times/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>10</cn></apply></apply><apply><lt/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>2</cn></apply></piece><otherwise><cn>1</cn></otherwise></piecewise></math></assignmentRule>
    </listOfRules>
    <listOfEvents>
      <event id="increment" useValuesFromTriggerTime="false">
        <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><lt/><ci>S1</ci><cn>0</cn></apply></math></trigger>
        <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
        <listOfEventAssignments><eventAssignment variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>S2</ci><cn>1</cn></apply></math></eventAssignment></listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result = Atomizer(
        {"atomize": False, "quiet_mode": True, "t_end": 5, "n_steps": 50}
    ).atomize(source)

    assert result.success, result.error
    assert 'setConcentration("@c:M_S2()", "1")' in result.bngl
    assert 'setConcentration("@c:M_S2()", "2")' in result.bngl
    assert 'setConcentration("@c:M_S2()", "3")' in result.bngl
    event_warnings = [
        warning
        for warning in result.log
        if getattr(warning, "category", None) == "event"
    ]
    assert not any(
        getattr(warning, "severity", None) == "dropped" for warning in event_warnings
    )


def test_time_only_cosh_assignment_rule_window_becomes_exact_time_bounds():
    import math

    from bionetgen.atomizer.modern.events import expand_cosh_assignment_rule_events
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLRule

    event = SBMLEvent(
        id="cosh-window",
        trigger="and(gt(cosh(time), 9), lt(cosh(time), 11))",
        delay="1",
        trigger_initial_value=True,
        trigger_persistent=True,
    )
    rewritten = expand_cosh_assignment_rule_events(
        [event],
        [SBMLRule("assignment", "P1", "cosh(time)")],
        resolve_constant=lambda _identifier: None,
    )

    assert len(rewritten) == 1
    lower, upper = math.acosh(9), math.acosh(11)
    trigger = rewritten[0].trigger
    assert trigger.startswith("and(gt(time, ")
    assert ", lt(time, " in trigger
    encoded_lower, encoded_upper = trigger[len("and(gt(time, ") : -2].split(
        "), lt(time, "
    )
    assert math.isclose(float(encoded_lower), lower, rel_tol=1e-11)
    assert math.isclose(float(encoded_upper), upper, rel_tol=1e-11)
    assert rewritten[0].delay == "1"
    assert rewritten[0].trigger_persistent is True

    reversed_comparisons = SBMLEvent(
        id="cosh-window-reversed",
        trigger="and(lt(9, cosh(time)), gt(11, cosh(time)))",
    )
    reversed_result = expand_cosh_assignment_rule_events(
        [reversed_comparisons],
        [SBMLRule("assignment", "P1", "cosh(time)")],
        resolve_constant=lambda _identifier: None,
    )
    assert reversed_result[0].trigger == rewritten[0].trigger


def test_cosh_window_without_matching_assignment_rule_stays_unchanged():
    from bionetgen.atomizer.modern.events import expand_cosh_assignment_rule_events
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLRule

    event = SBMLEvent(
        id="cosh-window",
        trigger="and(gt(cosh(time), 9), lt(cosh(time), 11))",
    )
    result = expand_cosh_assignment_rule_events(
        [event],
        [SBMLRule("assignment", "P1", "time")],
        resolve_constant=lambda _identifier: None,
    )

    assert result == [event]


def test_already_true_cosh_threshold_preserves_a_zero_time_rising_edge():
    from bionetgen.atomizer.modern.events import expand_cosh_assignment_rule_events
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLRule

    event = SBMLEvent(
        id="cosh-already-true",
        trigger="gt(cosh(time), 0.5)",
        trigger_initial_value=False,
    )
    result = expand_cosh_assignment_rule_events(
        [event],
        [SBMLRule("assignment", "P1", "cosh(time)")],
        resolve_constant=lambda _identifier: None,
    )

    assert result[0].trigger == "geq(time, 0)"
    assert result[0].trigger_initial_value is False


def test_static_state_threshold_can_use_another_static_species():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="static-species-threshold",
        trigger="gt(S4, S2)",
        trigger_initial_value=True,
        assignments=[SBMLEventAssignment("p", "4")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 0,
            is_param=lambda _identifier: True,
            resolve_constant=lambda identifier: {"S2": 1}.get(identifier),
            resolve_initial_value=lambda identifier: {"S4": 2}.get(identifier),
            resolve_affine_rate=lambda identifier: (
                (2, 0) if identifier == "S4" else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.actions_block is None
    assert result.untranslated == []


def test_nonpersistent_delayed_window_event_is_omitted_after_window_closes():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="window",
        name="window",
        trigger="and(gt(time, 1.5), lt(time, 2.5))",
        delay="2",
        assignments=[SBMLEventAssignment("p", "3")],
        trigger_persistent=False,
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 0,
            is_param=lambda _identifier: True,
        ),
    )

    assert result.converted == 1
    assert result.actions_block is None
    assert result.untranslated == []


def test_static_parameter_events_schedule_state_dependent_firings():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    events = [
        SBMLEvent(
            id="set-high",
            trigger="gt(P1, 1)",
            trigger_initial_value=False,
            delay="2.3",
            assignments=[("P1", "3")],
        ),
        SBMLEvent(
            id="set-low",
            trigger="gt(P1, 1)",
            trigger_initial_value=False,
            delay="1.5",
            assignments=[("P1", "0")],
        ),
    ]
    lowered = expand_static_parameter_event_system(
        events,
        t_end=5,
        parameter_ids=["P1"],
        resolve_initial=lambda identifier: 1.5 if identifier == "P1" else None,
    )

    assert lowered is not None
    assert [event.trigger for event in lowered] == [
        "geq(time, 1.5)",
        "geq(time, 2.3)",
        "geq(time, 3.8)",
        "geq(time, 4.6)",
    ]
    assert [event.assignments[0].math for event in lowered] == ["0", "3", "0", "3"]


def test_static_parameter_events_respect_delay_cancellation_and_value_snapshot():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    def events(persistent, use_trigger_values):
        return [
            SBMLEvent(
                id="copy",
                trigger="gt(P1, 1)",
                trigger_initial_value=False,
                trigger_persistent=persistent,
                delay="1",
                use_values_from_trigger_time=use_trigger_values,
                assignments=[("P2", "P1")],
            ),
            SBMLEvent(
                id="clear",
                trigger="gt(P1, 1)",
                trigger_initial_value=False,
                delay="0.5",
                assignments=[("P1", "0")],
            ),
        ]

    def lower(persistent, use_trigger_values):
        return expand_static_parameter_event_system(
            events(persistent, use_trigger_values),
            t_end=2,
            parameter_ids=["P1", "P2"],
            resolve_initial=lambda identifier: {"P1": 2, "P2": 0}.get(identifier),
        )

    canceled = lower(False, True)
    snapshot = lower(True, True)
    execution_value = lower(True, False)
    assert canceled is not None and len(canceled) == 1
    assert [event.assignments[0].math for event in canceled] == ["0"]
    assert snapshot is not None and [
        event.assignments[0].math for event in snapshot
    ] == [
        "0",
        "2",
    ]
    assert execution_value is not None and [
        event.assignments[0].math for event in execution_value
    ] == ["0", "0"]


def test_static_parameter_event_lowering_rejects_time_triggers():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    lowered = expand_static_parameter_event_system(
        [
            SBMLEvent(
                id="dynamic-time",
                trigger="and(gt(P1, 1), gt(time, 1))",
                assignments=[("P1", "0")],
            )
        ],
        t_end=2,
        parameter_ids=["P1"],
        resolve_initial=lambda _identifier: 2,
    )
    assert lowered is None


def test_static_parameter_event_delay_uses_trigger_time_state():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    events = [
        SBMLEvent(
            id="delayed-copy",
            trigger="gt(P1, 1)",
            trigger_initial_value=False,
            delay="P1",
            assignments=[("P2", "1")],
        ),
        SBMLEvent(
            id="lower-P1",
            trigger="gt(P1, 1)",
            trigger_initial_value=False,
            delay="0.5",
            assignments=[("P1", "0")],
        ),
    ]
    lowered = expand_static_parameter_event_system(
        events,
        t_end=3,
        parameter_ids=["P1", "P2"],
        resolve_initial=lambda identifier: {"P1": 2, "P2": 0}.get(identifier),
    )

    assert lowered is not None
    assert [event.trigger for event in lowered] == [
        "geq(time, 0.5)",
        "geq(time, 2)",
    ]


def test_static_parameter_events_accept_one_fixed_time_trigger():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    events = [
        SBMLEvent(
            id="later-high",
            trigger="gt(P1, 1)",
            trigger_initial_value=True,
            delay="2",
            assignments=[("P1", "3")],
        ),
        SBMLEvent(
            id="earlier-low",
            trigger="gt(P1, 1)",
            trigger_initial_value=True,
            delay="1",
            assignments=[("P1", "0")],
        ),
        SBMLEvent(
            id="raise",
            trigger="gt(time, 0.65)",
            trigger_initial_value=True,
            assignments=[("P1", "2")],
        ),
    ]
    lowered = expand_static_parameter_event_system(
        events,
        t_end=4,
        parameter_ids=["P1"],
        resolve_initial=lambda identifier: 0.5 if identifier == "P1" else None,
    )

    assert lowered is not None
    assert [event.trigger for event in lowered] == [
        "geq(time, 0.65)",
        "geq(time, 1.65)",
        "geq(time, 2.65)",
        "geq(time, 3.65)",
    ]


def test_static_parameter_events_apply_simultaneous_priorities_in_order():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    events = [
        SBMLEvent(
            id="low",
            trigger="geq(time, 1)",
            trigger_initial_value=False,
            priority="1",
            assignments=[("P1", "0")],
        ),
        SBMLEvent(
            id="high",
            trigger="geq(time, 1)",
            trigger_initial_value=False,
            priority="10",
            assignments=[("P1", "2")],
        ),
    ]
    lowered = expand_static_parameter_event_system(
        events,
        t_end=2,
        parameter_ids=["P1"],
        resolve_initial=lambda _identifier: 0,
    )

    assert lowered is not None
    assert [event.id.split("__static_")[0] for event in lowered] == ["high", "low"]
    assert [event.assignments[0].math for event in lowered] == ["2", "0"]


def test_static_parameter_events_recompute_time_offset_after_reset():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    event = SBMLEvent(
        id="periodic-reset",
        trigger="geq((time - reset), 1)",
        trigger_initial_value=True,
        priority="time",
        assignments=[("reset", "time"), ("count", "count + 1")],
    )
    lowered = expand_static_parameter_event_system(
        [event],
        t_end=3,
        parameter_ids=["reset", "count"],
        resolve_initial=lambda identifier: {"reset": 0, "count": 0}.get(identifier),
    )

    assert lowered is not None
    assert [event.trigger for event in lowered] == [
        "geq(time, 1)",
        "geq(time, 2)",
        "geq(time, 3)",
    ]
    assert [event.assignments[1].math for event in lowered] == ["1", "2", "3"]


def test_static_parameter_events_ignore_missing_triggers_and_coerce_numeric_truth():
    from bionetgen.atomizer.modern.events import expand_static_parameter_event_system
    from bionetgen.atomizer.modern.types import SBMLEvent

    lowered = expand_static_parameter_event_system(
        [
            SBMLEvent(
                id="missing-trigger",
                trigger="",
                assignments=[("P1", "3")],
            ),
            SBMLEvent(
                id="numeric-true",
                trigger="3",
                trigger_initial_value=False,
                assignments=[("P1", "2")],
            ),
        ],
        t_end=1,
        parameter_ids=["P1"],
        resolve_initial=lambda _identifier: 5,
    )

    assert lowered is not None
    assert len(lowered) == 1
    assert lowered[0].id.startswith("numeric-true__static_")
    assert lowered[0].trigger == "geq(time, 0)"
    assert lowered[0].assignments[0].math == "2"


def test_affine_interval_of_delayed_state_obeys_event_persistence():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    cases = ((2, True, True), (2, False, False), (2.6, False, True))
    for upper, persistent, should_schedule in cases:
        event = SBMLEvent(
            id="delayed-affine-window",
            trigger=f"and(gt(delay(P1, 1), 1.5), lt(delay(P1, 1), {upper}))",
            delay="1",
            trigger_persistent=persistent,
            assignments=[SBMLEventAssignment("P2", "3")],
        )
        trajectory = lambda identifier: (0, 1) if identifier == "P1" else None
        result = synthesize_event_actions(
            [event],
            EventTranslationContext(
                resolve_species_pattern=lambda _identifier: None,
                resolve_param=lambda _identifier: 0,
                is_param=lambda _identifier: True,
                resolve_affine_rate=trajectory,
                resolve_affine_rate_for_event=lambda identifier, _event: trajectory(
                    identifier
                ),
            ),
        )

        assert result.converted == 1
        assert result.untranslated == []
        assert (result.actions_block is not None) is should_schedule
        if should_schedule:
            assert 'setParameter("P2", "3")' in result.actions_block


def test_exponential_interval_of_delayed_state_uses_shifted_crossings():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="delayed-exponential-window",
        trigger="and(gt(delay(P1, 1), 0.4), lt(delay(P1, 1), 0.5))",
        trigger_initial_value=False,
        trigger_persistent=True,
        assignments=[SBMLEventAssignment("P2", "P1")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 0,
            is_param=lambda _identifier: True,
            resolve_exponential_rate_for_event=lambda identifier, _event: (
                (1, -1) if identifier == "P1" else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("P2", "0.183939720586")' in result.actions_block
    assert "t_end=>1.69314718056" in result.actions_block


def test_constant_false_mathml_conjunction_folds_with_unknown_time_term():
    from bionetgen.atomizer.modern.events import fold_numeric

    assert (
        fold_numeric("and(gt(time, 0.21), leq(5, 5, 2))", lambda _identifier: None) == 0
    )
    assert fold_numeric("leq(1, 2, 3)", lambda _identifier: None) == 1


def test_initially_true_mutable_trigger_fires_at_t0_only_when_initial_value_false():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    def context():
        return EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: 3,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: 3 if identifier == "x" else None,
        )

    fire_now = SBMLEvent(
        id="initial-edge",
        trigger="gt(x, 2)",
        trigger_initial_value=False,
        assignments=[SBMLEventAssignment("x", "x + 1")],
    )
    result = synthesize_event_actions([fire_now], context())
    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("x", "4")' in result.actions_block

    no_initial_edge = SBMLEvent(
        id="already-true",
        trigger="gt(x, 2)",
        trigger_initial_value=True,
        assignments=[SBMLEventAssignment("x", "x + 1")],
    )
    result = synthesize_event_actions([no_initial_edge], context())
    assert result.converted == 0
    assert result.actions_block is None
    assert result.untranslated


def test_constant_rate_rule_threshold_is_scheduled_at_exact_crossing_time():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="linear-crossing",
        trigger="gt(trig, -5.2)",
        trigger_initial_value=True,
        assignments=[SBMLEventAssignment("P", "2")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_affine_rate=lambda identifier: (
                (-5.3, 1.0) if identifier == "trig" else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>0.1" in result.actions_block
    assert 'setParameter("P", "2")' in result.actions_block


def test_affine_threshold_event_reads_species_at_trigger_time():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="threshold-value",
        trigger="geq(x, 3.5)",
        delay="2",
        assignments=[SBMLEventAssignment("P", "x")],
        use_values_from_trigger_time=True,
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_affine_rate=lambda identifier: (
                (1.0, 1.0) if identifier == "x" else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>4.5" in result.actions_block
    assert 'setParameter("P", "3.5")' in result.actions_block

    event.use_values_from_trigger_time = False
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_affine_rate=lambda identifier: (
                (1.0, 1.0) if identifier == "x" else None
            ),
        ),
    )
    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("P", "5.5")' in result.actions_block


def test_sbml_comparison_operator_aliases_schedule_affine_thresholds():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    for trigger, initial, derivative in (
        ("lessthan(x, 0.5)", 1.0, -1.0),
        ("greaterthan(x, 0.5)", 0.0, 1.0),
        ("lessThanOrEqual(x, 0.5)", 1.0, -1.0),
        ("greaterOrEqual(x, 0.5)", 0.0, 1.0),
    ):
        result = synthesize_event_actions(
            [
                SBMLEvent(
                    id="operator-alias",
                    trigger=trigger,
                    assignments=[SBMLEventAssignment("P", "1")],
                )
            ],
            EventTranslationContext(
                resolve_species_pattern=lambda _identifier: None,
                resolve_param=lambda _identifier: None,
                is_param=lambda _identifier: True,
                is_compile_time_constant=lambda _identifier: False,
                resolve_affine_rate=lambda identifier: (
                    (initial, derivative) if identifier == "x" else None
                ),
            ),
        )
        assert result.converted == 1
        assert result.untranslated == []
        assert result.actions_block is not None
        assert f'setParameter("P", "1")' in result.actions_block
        assert "t_end=>0.5" in result.actions_block


def test_affine_state_threshold_with_fixed_time_gate():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="time-gated-threshold",
        trigger="and(geq(time, 1), geq(x, 3))",
        assignments=[SBMLEventAssignment("P", "1")],
    )
    context = EventTranslationContext(
        resolve_species_pattern=lambda _identifier: None,
        resolve_param=lambda _identifier: None,
        is_param=lambda _identifier: True,
        is_compile_time_constant=lambda _identifier: False,
        resolve_initial_value=lambda identifier: 1.0 if identifier == "x" else None,
        resolve_affine_rate=lambda identifier: (
            (1.0, 1.0) if identifier == "x" else None
        ),
    )
    result = synthesize_event_actions([event], context)

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>2" in result.actions_block

    event.trigger = "and(geq(time, 3), geq(x, 2))"
    result = synthesize_event_actions([event], context)
    assert result.converted == 0
    assert len(result.untranslated) == 1


def test_quadratic_state_difference_threshold_uses_composite_trajectory():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="difference-threshold",
        trigger="gt(A, B)",
        assignments=[SBMLEventAssignment("P", "A * time")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {
                "A": 1.0,
                "B": 2.0,
            }.get(identifier),
            resolve_quadratic_rate_for_event=lambda expression, _event: (
                (-1.0, 0.0, 0.0, 1.0) if expression == "(A) - (B)" else None
            ),
            resolve_quadratic_state_values_for_event=lambda expression, value, _event: (
                {"A": 4.0, "B": 4.0}
                if expression == "(A) - (B)" and value == 0
                else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>1" in result.actions_block
    assert 'setParameter("P", "4")' in result.actions_block


def test_affine_state_difference_threshold_preserves_trigger_snapshot():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="affine-difference-threshold",
        trigger="gt(A, B)",
        assignments=[SBMLEventAssignment("P", "A + B + time")],
    )
    trajectories = {"A": (1.0, 1.0), "B": (2.0, 0.0)}
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: trajectories.get(
                identifier, (None,)
            )[0],
            resolve_affine_rate_for_event=lambda identifier, _event: trajectories.get(
                identifier
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>1" in result.actions_block
    assert 'setParameter("P", "5")' in result.actions_block


def test_quadratic_state_threshold_supplies_trigger_time_species_snapshot():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="quadratic-trigger-snapshot",
        trigger="gt(A, 0)",
        assignments=[SBMLEventAssignment("P", "B * time")],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {"A": -1.0, "B": 2.0}.get(
                identifier
            ),
            resolve_quadratic_rate_for_event=lambda identifier, _event: (
                (-1.0, 0.0, 0.0, 1.0) if identifier == "A" else None
            ),
            resolve_quadratic_state_values_for_event=lambda identifier, value, _event: (
                {"A": value, "B": 4.0} if identifier == "A" and value == 0 else None
            ),
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("P", "4")' in result.actions_block


def test_exponential_threshold_event_reads_trigger_or_execution_state():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="exponential-threshold",
        trigger="geq(x, 2)",
        delay="1",
        assignments=[SBMLEventAssignment("P", "x")],
        use_values_from_trigger_time=True,
    )
    context = EventTranslationContext(
        resolve_species_pattern=lambda _identifier: None,
        resolve_param=lambda _identifier: None,
        is_param=lambda _identifier: True,
        is_compile_time_constant=lambda _identifier: False,
        resolve_exponential_rate=lambda identifier: (
            (1.0, 0.5) if identifier == "x" else None
        ),
    )
    result = synthesize_event_actions([event], context)

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert "t_end=>2.38629436112" in result.actions_block
    assert 'setParameter("P", "2")' in result.actions_block

    event.use_values_from_trigger_time = False
    result = synthesize_event_actions([event], context)
    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("P", "3.2974425414")' in result.actions_block


def test_fold_numeric_supports_mathml_nary_and_inverse_hyperbolic_functions():
    from bionetgen.atomizer.modern.events import fold_numeric

    assert fold_numeric("plus(5.3)", lambda _identifier: None) == 5.3
    assert fold_numeric("times()", lambda _identifier: None) == 1
    assert fold_numeric("arcsinh(0)", lambda _identifier: None) == 0
    assert fold_numeric("arcsec(1)", lambda _identifier: None) == 0


def test_periodic_reset_event_is_expanded_to_repeated_parameter_updates():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="periodic-increment",
        trigger="geq(minus(time, reset), 1)",
        assignments=[
            SBMLEventAssignment("reset", "time"),
            SBMLEventAssignment("Q", "Q + 0.5"),
        ],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {
                "reset": 0,
                "Q": 0,
            }.get(identifier),
            base_t_end=2.5,
            base_steps=10,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert result.actions_block.count('setParameter("Q",') == 2
    assert 'setParameter("Q", "0.5")' in result.actions_block
    assert 'setParameter("Q", "1")' in result.actions_block
    assert 'setParameter("reset", "1")' in result.actions_block
    assert 'setParameter("reset", "2")' in result.actions_block
    assert "t_end=>2.5" in result.actions_block


def test_periodic_event_at_requested_end_does_not_extend_past_scheduled_horizon():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="periodic-at-end",
        trigger="geq(minus(time, reset), 1)",
        assignments=[
            SBMLEventAssignment("reset", "time"),
            SBMLEventAssignment("Q", "Q + 1"),
        ],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {
                "reset": 0,
                "Q": 0,
            }.get(identifier),
            base_t_end=1,
            base_steps=10,
        ),
    )

    assert result.actions_block is not None
    assert result.actions_block.count('setParameter("Q",') == 1
    assert "t_end=>1" in result.actions_block
    assert "t_end=>2.5" not in result.actions_block


def test_simultaneous_periodic_events_prove_constant_difference_never_triggers():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    increment_q = SBMLEvent(
        id="increment-q",
        trigger="geq(minus(time, reset), 1)",
        assignments=[
            SBMLEventAssignment("reset", "time"),
            SBMLEventAssignment("Q", "Q + 0.5"),
        ],
    )
    increment_r = SBMLEvent(
        id="increment-r",
        trigger="geq(minus(time, reset), 1)",
        assignments=[
            SBMLEventAssignment("reset", "time"),
            SBMLEventAssignment("R", "R + 0.5"),
        ],
    )
    never_error = SBMLEvent(
        id="difference-threshold",
        trigger="geq(abs(Q - R), 4)",
        assignments=[SBMLEventAssignment("error", "1")],
    )
    initial = {"reset": 0, "Q": 0, "R": 0, "error": 0}
    result = synthesize_event_actions(
        [increment_q, increment_r, never_error],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda identifier: identifier in initial,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=initial.get,
            base_t_end=2.5,
            base_steps=10,
        ),
    )

    assert result.converted == 3
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("Q", "1")' in result.actions_block
    assert 'setParameter("R", "1")' in result.actions_block
    assert 'setParameter("error",' not in result.actions_block


def test_rate_rule_reset_event_is_repeated_from_its_constant_slope():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="rate-reset",
        trigger="geq(reset, 0.5)",
        assignments=[
            SBMLEventAssignment("reset", "0"),
            SBMLEventAssignment("Q", "Q + 0.25"),
        ],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {"Q": 0}.get(identifier),
            resolve_rate_reset=lambda identifier: (
                (0.0, 0.5) if identifier == "reset" else None
            ),
            base_t_end=2.5,
            base_steps=10,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert result.actions_block.count('setParameter("Q",') == 2
    assert 'setParameter("Q", "0.25")' in result.actions_block
    assert 'setParameter("Q", "0.5")' in result.actions_block
    assert 'setParameter("reset", "0")' in result.actions_block


def test_decreasing_rate_rule_reset_event_repeats_on_the_correct_side():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="descending-reset",
        trigger="leq(reset, 0.5)",
        assignments=[
            SBMLEventAssignment("reset", "1"),
            SBMLEventAssignment("Q", "Q + 2"),
        ],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {"Q": 0}.get(identifier),
            resolve_rate_reset=lambda identifier: (
                (1.0, -0.5) if identifier == "reset" else None
            ),
            base_t_end=2.5,
            base_steps=10,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert result.actions_block.count('setParameter("Q",') == 2
    assert 'setParameter("Q", "2")' in result.actions_block
    assert 'setParameter("Q", "4")' in result.actions_block


def test_delayed_clock_reset_event_reschedules_from_execution_time():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="delayed-reset",
        trigger="geq(time - reset, 1)",
        delay="0.5",
        use_values_from_trigger_time=False,
        assignments=[
            SBMLEventAssignment("reset", "time"),
            SBMLEventAssignment("Q", "Q + 1"),
        ],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {"reset": 0, "Q": 0}.get(
                identifier
            ),
            base_t_end=3.5,
            base_steps=10,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("reset", "1.5")' in result.actions_block
    assert 'setParameter("reset", "3.5")' in result.actions_block
    assert 'setParameter("Q", "1")' in result.actions_block
    assert 'setParameter("Q", "2")' in result.actions_block


def test_rate_reset_event_folds_delayed_history_at_each_trigger():
    from bionetgen.atomizer.modern.events import (
        EventTranslationContext,
        synthesize_event_actions,
    )
    from bionetgen.atomizer.modern.types import SBMLEvent, SBMLEventAssignment

    event = SBMLEvent(
        id="rate-reset-delay-history",
        trigger="geq(reset, 0.01)",
        assignments=[
            SBMLEventAssignment("reset", "0"),
            SBMLEventAssignment("Q", "Q + delay(reset, 0.005) + 0.005"),
        ],
    )
    result = synthesize_event_actions(
        [event],
        EventTranslationContext(
            resolve_species_pattern=lambda _identifier: None,
            resolve_param=lambda _identifier: None,
            is_param=lambda _identifier: True,
            is_compile_time_constant=lambda _identifier: False,
            resolve_initial_value=lambda identifier: {"Q": 0}.get(identifier),
            resolve_rate_reset=lambda identifier: (
                (0.0, 1.0) if identifier == "reset" else None
            ),
            base_t_end=0.025,
            base_steps=10,
        ),
    )

    assert result.converted == 1
    assert result.untranslated == []
    assert result.actions_block is not None
    assert 'setParameter("Q", "0.01")' in result.actions_block
    assert 'setParameter("Q", "0.02")' in result.actions_block


def test_quadratic_trajectory_crossings_match_exact_state_solution():
    import math

    from bionetgen.atomizer.modern.events import (
        _quadratic_crossing_time,
        _quadratic_state_at_time,
    )

    cases = (
        (1.0, 0.75, -0.75, -1.0, 0.5),
        (0.0, 1.0, 1.0, 0.0, 1.0),
        (1.0, 2.0, 1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 2.0, 1.0),
    )
    for initial, target, quadratic, linear, constant in cases:
        crossing_time = _quadratic_crossing_time(
            initial, target, quadratic, linear, constant
        )
        assert crossing_time is not None and crossing_time > 0
        assert math.isclose(
            _quadratic_state_at_time(
                initial, quadratic, linear, constant, crossing_time
            ),
            target,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
