"""Rule-based analysis helpers from the Playground Atomizer.

The Rulifier operates on the modern structured ``Rule`` representation. It
keeps transformation centers, state transitions, redundant-rule groups, and
rate-law diagnostics explicit so callers can audit each generalization.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set, Tuple

from .structures import Action, Rule, Species


@dataclass
class ComponentGroup:
    name: str
    molecule: str
    states: List[str]
    patterns: List[Species]


@dataclass
class TransformationCenter:
    action: str
    site1: str
    site2: str
    molecules: List[str]


@dataclass
class TransformationContext:
    patterns: List[Species]
    modifiers: List[str]


@dataclass
class RuleGrouping:
    center: TransformationCenter
    context: TransformationContext
    rate: str
    rules: List[Rule]


@dataclass
class StateTransition:
    from_state: str
    to_state: str
    molecule: str
    component: str
    rate: str
    rule: Rule


@dataclass
class StateTransitionDiagram:
    states: Set[str]
    transitions: List[StateTransition]
    initial_state: str


def _parse_action_site(
    site_id: str, patterns: List[Species]
) -> Optional[Tuple[str, str]]:
    for pattern in patterns:
        for molecule in pattern.molecules:
            for component in molecule.components:
                if component.idx == site_id:
                    return molecule.name, component.name
    return None


def _find_component_state(
    patterns: List[Species], molecule_name: str, component_name: str
) -> Optional[str]:
    for pattern in patterns:
        for molecule in pattern.molecules:
            if molecule.name != molecule_name:
                continue
            for component in molecule.components:
                if component.name == component_name:
                    return component.active_state or None
    return None


def build_state_transition_diagram(
    rules: List[Rule], molecule_name: str, component_name: str
) -> StateTransitionDiagram:
    """Build a state graph for one molecule component across reaction rules."""

    states: Set[str] = set()
    transitions: List[StateTransition] = []
    initial_state = "0"

    for rule in rules:
        for action in rule.actions:
            if action.action != "StateChange":
                continue
            site_info = _parse_action_site(action.site1, rule.reactants)
            if site_info != (molecule_name, component_name):
                continue

            reactant_state = _find_component_state(
                rule.reactants, molecule_name, component_name
            )
            product_state = _find_component_state(
                rule.products, molecule_name, component_name
            )
            if reactant_state and product_state and reactant_state != product_state:
                states.update((reactant_state, product_state))
                transitions.append(
                    StateTransition(
                        from_state=reactant_state,
                        to_state=product_state,
                        molecule=molecule_name,
                        component=component_name,
                        rate=rule.rates[0] if rule.rates else "1",
                        rule=rule,
                    )
                )

    if "0" in states:
        initial_state = "0"
    elif "U" in states:
        initial_state = "U"
    elif states:
        initial_state = next(iter(states))

    return StateTransitionDiagram(states, transitions, initial_state)


def extract_transformation_center(rule: Rule) -> TransformationCenter:
    """Extract the first action and all molecules touched by a rule."""

    action = rule.actions[0] if rule.actions else Action()
    molecules: List[str] = []
    for pattern in [*rule.reactants, *rule.products]:
        for molecule in pattern.molecules:
            if molecule.name not in molecules:
                molecules.append(molecule.name)
    return TransformationCenter(
        action=action.action,
        site1=action.site1,
        site2=action.site2,
        molecules=molecules,
    )


def _extract_transformation_context(rule: Rule) -> TransformationContext:
    patterns: List[Species] = []
    for reactant in rule.reactants:
        for product in rule.products:
            if str(reactant) == str(product):
                patterns.append(reactant)
    return TransformationContext(patterns=patterns, modifiers=[])


def species_equal(first: Species, second: Species) -> bool:
    """Compare species using the same rendered-pattern identity as the port."""

    return str(first) == str(second)


def group_by_reaction_center(rules: List[Rule]) -> Dict[str, List[Rule]]:
    """Group rules by action sites and participating molecule names."""

    groups: Dict[str, List[Rule]] = {}
    for rule in rules:
        center = extract_transformation_center(rule)
        key = json.dumps(asdict(center), separators=(",", ":"))
        groups.setdefault(key, []).append(rule)
    return groups


def find_redundant_rules(rules: List[Rule]) -> Dict[str, List[Rule]]:
    """Find rules sharing both transformation center and unchanged context."""

    redundant: Dict[str, List[Rule]] = {}
    for center_key, center_rules in group_by_reaction_center(rules).items():
        if len(center_rules) <= 1:
            continue
        context_signatures: Dict[str, List[Rule]] = {}
        for rule in center_rules:
            context = _extract_transformation_context(rule)
            context_key = json.dumps(
                sorted(str(pattern) for pattern in context.patterns),
                separators=(",", ":"),
            )
            context_signatures.setdefault(context_key, []).append(rule)
        for context_key, context_rules in context_signatures.items():
            if len(context_rules) > 1:
                redundant[f"{center_key}_{context_key}"] = context_rules
    return redundant


def _generalize_species(patterns: List[Species]) -> Species:
    if not patterns:
        return Species()
    base_pattern = patterns[0].copy()
    states: Dict[str, Dict[str, Set[str]]] = {}
    for pattern in patterns:
        for molecule in pattern.molecules:
            molecule_states = states.setdefault(molecule.name, {})
            for component in molecule.components:
                if component.active_state:
                    molecule_states.setdefault(component.name, set()).add(
                        component.active_state
                    )

    for molecule in base_pattern.molecules:
        molecule_states = states.get(molecule.name, {})
        for component in molecule.components:
            component_states = molecule_states.get(component.name, set())
            if len(component_states) > 1:
                component.active_state = ""
    return base_pattern


def _generalize_rule(rules: List[Rule]) -> Rule:
    if not rules:
        return Rule()
    base_rule = rules[0]
    generalized = Rule(f"{base_rule.label}_generalized")
    for index in range(len(base_rule.reactants)):
        generalized.add_reactant(
            _generalize_species(
                [rule.reactants[index] for rule in rules if index < len(rule.reactants)]
            )
        )
    for index in range(len(base_rule.products)):
        generalized.add_product(
            _generalize_species(
                [rule.products[index] for rule in rules if index < len(rule.products)]
            )
        )
    if base_rule.rates:
        generalized.add_rate(base_rule.rates[0])
    generalized.bidirectional = base_rule.bidirectional
    generalized.actions = list(base_rule.actions)
    return generalized


def collapse_redundant_rules(rules: List[Rule]) -> List[Rule]:
    """Replace each redundant group with one generalized rule."""

    collapsed: List[Rule] = []
    processed: Set[Rule] = set()
    for group in find_redundant_rules(rules).values():
        collapsed.append(_generalize_rule(group))
        processed.update(group)
    collapsed.extend(rule for rule in rules if rule not in processed)
    return collapsed


_RESERVED_RATE_WORDS = {
    "if",
    "then",
    "else",
    "ln",
    "log",
    "exp",
    "sin",
    "cos",
    "tan",
    "sqrt",
    "abs",
    "min",
    "max",
}


def extract_parameters(rules: List[Rule]) -> Set[str]:
    """Extract identifier-like rate terms excluding common math functions."""

    parameters: Set[str] = set()
    for rule in rules:
        for rate in rule.rates:
            for parameter in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", rate):
                if parameter.lower() not in _RESERVED_RATE_WORDS:
                    parameters.add(parameter)
    return parameters


def analyze_rate_law(rate: str, reactant_species: List[str]) -> Dict[str, object]:
    """Estimate reaction order and mass-action status from a rate expression."""

    remaining_rate = rate
    order = 0
    for species in reactant_species:
        pattern = re.compile(rf"\b{species}\b")
        matches = pattern.findall(remaining_rate)
        if matches:
            order += len(matches)
            remaining_rate = pattern.sub("1", remaining_rate)

    cleaned = re.sub(r"[\s*()1]", "", remaining_rate)
    is_mass_action = bool(
        re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", cleaned)
        or re.fullmatch(r"[\d.e+-]+", cleaned)
    )
    return {
        "order": order,
        "mass_action": is_mass_action,
        "rate_constant": cleaned if is_mass_action else None,
    }


# Source-facing aliases ease migration of callers that still use the
# Playground's camelCase names.
buildStateTransitionDiagram = build_state_transition_diagram
groupByReactionCenter = group_by_reaction_center
groupRulesByCenter = group_by_reaction_center
findRedundantRules = find_redundant_rules
collapseRedundantRules = collapse_redundant_rules
extractParameters = extract_parameters
analyzeRateLaw = analyze_rate_law
extractTransformationCenter = extract_transformation_center
extractTransformationContext = _extract_transformation_context
speciesEqual = species_equal


__all__ = [
    "Action",
    "ComponentGroup",
    "RuleGrouping",
    "StateTransition",
    "StateTransitionDiagram",
    "TransformationCenter",
    "TransformationContext",
    "analyzeRateLaw",
    "analyze_rate_law",
    "buildStateTransitionDiagram",
    "build_state_transition_diagram",
    "collapseRedundantRules",
    "collapse_redundant_rules",
    "extractParameters",
    "extractTransformationCenter",
    "extractTransformationContext",
    "extract_parameters",
    "extract_transformation_center",
    "findRedundantRules",
    "find_redundant_rules",
    "groupByReactionCenter",
    "groupRulesByCenter",
    "group_by_reaction_center",
    "speciesEqual",
    "species_equal",
]
