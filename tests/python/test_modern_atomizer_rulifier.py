"""Source-derived tests for the modern Atomizer Rulifier surface.

Expectations mirror RuleWorld/bngplayground's pinned Rulifier tests and data
structures, not the legacy Python atomizer.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import (
    Action,
    Component,
    Molecule,
    Rule,
    Species,
    analyze_rate_law,
    build_state_transition_diagram,
    collapse_redundant_rules,
    extract_parameters,
    find_redundant_rules,
    group_by_reaction_center,
)


def _pattern(
    molecule_name: str,
    component_name: str | None = None,
    component_idx: str = "",
    state: str = "",
) -> Species:
    species = Species()
    molecule = Molecule(molecule_name)
    if component_name is not None:
        component = Component(component_name, component_idx)
        if state:
            component.active_state = state
            component.states.append(state)
        molecule.components.append(component)
    species.molecules.append(molecule)
    return species


def _state_rule(
    label: str,
    molecule_name: str = "A",
    component_name: str = "b",
    component_idx: str = "b_site",
    from_state: str = "U",
    to_state: str = "P",
    context_state: str | None = None,
) -> Rule:
    rule = Rule(label)
    reactant = _pattern(molecule_name, component_name, component_idx, from_state)
    product = _pattern(molecule_name, component_name, component_idx, to_state)
    rule.add_reactant(reactant)
    rule.add_product(product)
    if context_state is not None:
        rule.add_reactant(_pattern("Ctx", "site", "ctx", context_state))
        rule.add_product(_pattern("Ctx", "site", "ctx", context_state))
    action = Action()
    action.set_action("StateChange", component_idx)
    rule.add_action_list([action])
    return rule


def test_group_by_reaction_center_groups_same_center_and_separates_action():
    first = _state_rule("first")
    second = _state_rule("second")
    different = _state_rule("different")
    different.actions[0].set_action("AddBond", "b_site", "other_site")

    grouped = group_by_reaction_center([first, second, different])

    assert len(grouped) == 2
    assert any(group == [first, second] for group in grouped.values())


def test_build_state_transition_diagram_matches_reference_contract():
    rule = _state_rule("state-change")
    rule.add_rate("k1")

    diagram = build_state_transition_diagram([rule], "A", "b")

    assert diagram.states == {"U", "P"}
    assert diagram.initial_state == "U"
    assert len(diagram.transitions) == 1
    transition = diagram.transitions[0]
    assert transition.from_state == "U"
    assert transition.to_state == "P"
    assert transition.rate == "k1"
    assert transition.rule is rule


def test_build_state_transition_diagram_ignores_non_state_changes_and_defaults_rate():
    rule = _state_rule("state-change")
    rule.actions[0].set_action("AddBond", "b_site", "other_site")
    ignored = build_state_transition_diagram([rule], "A", "b")
    assert ignored.states == set()
    assert ignored.transitions == []

    default_rate_rule = _state_rule("default-rate")
    diagram = build_state_transition_diagram([default_rate_rule], "A", "b")
    assert diagram.transitions[0].rate == "1"


def test_find_and_collapse_redundant_rules_preserves_generalized_rule_shape():
    first = _state_rule("first", context_state="same")
    second = _state_rule("second", context_state="same")

    redundant = find_redundant_rules([first, second])

    assert len(redundant) == 1
    assert next(iter(redundant.values())) == [first, second]

    collapsed = collapse_redundant_rules([first, second])
    assert len(collapsed) == 1
    assert collapsed[0].label == "first_generalized"
    assert collapsed[0].rates == []


def test_different_contexts_are_not_marked_redundant():
    first = _state_rule("first", context_state="StateA")
    second = _state_rule("second", context_state="StateB")

    assert find_redundant_rules([first, second]) == {}


def test_extract_parameters_and_analyze_rate_law_follow_reference_rules():
    rule = _state_rule("rate")
    rule.add_rate("k1 * A + exp(B) + log(C)")

    assert extract_parameters([rule]) == {"k1", "A", "B", "C"}
    assert analyze_rate_law("k*A*B", ["A", "B"]) == {
        "order": 2,
        "mass_action": True,
        "rate_constant": "k",
    }
    nonlinear = analyze_rate_law("k*A*(B+1)", ["A", "B"])
    assert nonlinear["order"] == 2
    assert nonlinear["mass_action"] is False
    assert nonlinear["rate_constant"] is None
