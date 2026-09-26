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
