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
    )

    assert foldNumeric is fold_numeric
    assert foldNumeric("1 + 2", lambda _identifier: None) == 3
    assert parseTimeThreshold is parse_time_threshold
    assert parseTimeThreshold("time >= 2") == "2"

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
