"""Reduce an SBML fast reaction to the pseudo steady state it defines.

SBML Level 2 and Level 3 Version 1 Section 4.11 describe a reaction whose
``fast`` attribute is true as operating on a time scale significantly faster
than the model's other reactions: fast reactions are "considered to be
instantaneous relative to the slow reactions", and software tools "should
use a pseudo steady-state approximation for the set of fast reactions when
constructing the system of equations for the model".  The attribute changes
the mathematical interpretation of the model rather than only the solver's
effort, and the specification says it "cannot be safely ignored" by a tool
that cannot analyse the model with that approximation.  SBML Level 3
Version 2 removes the attribute entirely: every reaction in a Level 3
Version 2 model is equivalent to a Level 3 Version 1 reaction whose ``fast``
value is false.

This module lowers the shapes of fast reaction whose pseudo steady state
BNG3 can express exactly:

* a fast reaction whose rate is proportional to one of the two species it
  converts, or to both of them with a constant factor.  Such a rate
  vanishes only when one of the two species is zero, so the pseudo steady
  state holds that species at zero and lets the other absorb its amount,
  scaled by the stoichiometry ratio.  This is the reduction the infinitely
  fast relaxation produces: the fast subsystem's conserved combination
  ``nu_P * R + nu_R * P`` does not change while it relaxes.
* a fast reaction whose rate is the difference of two terms, one
  proportional to each of the two species it converts.  Its pseudo steady
  state is the algebraic balance between them, and the constrained slow
  dynamics follow from that balance: the species the slow reactions change
  is the one the balance pins, and the slow reactions' effect on the fast
  subsystem is scaled by the balance's stiffness.

Every other shape of fast reaction needs an algebraic solve that BNG3 cannot
perform, so those are reported with the specific reason they cannot be
reduced.
"""

from __future__ import annotations

import ast
import copy
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .math_builtins import evaluate_math_builtin, format_number
from .types import SBMLModel, SBMLReaction, SBMLSpecies, standardize_name


@dataclass
class FastReactionOutcome:
    """The result of trying to reduce one fast reaction to its steady state."""

    reaction_id: str
    reduced: bool
    detail: str = ""
    reason: str = ""


@dataclass(frozen=True)
class _RateTerm:
    """One additive term of a rate law.

    ``species`` holds the species the term is proportional to, with their
    exponents, and ``coefficient`` the term's signed constant factor.
    """

    species: Tuple[Tuple[str, int], ...]
    coefficient: float

    @property
    def species_ids(self) -> Tuple[str, ...]:
        return tuple(identifier for identifier, _ in self.species)


def lower_fast_reactions(model: SBMLModel) -> Dict[str, FastReactionOutcome]:
    """Reduce the model's fast reactions to their pseudo steady states.

    A reduced reaction is removed from ``model.reactions`` and the initial
    amounts of the species it converts are updated.  Reactions that cannot
    be reduced are left in the model and reported with the reason.
    """

    fast = [reaction for reaction in model.reactions.values() if reaction.fast]
    if not fast:
        return {}
    outcomes: Dict[str, FastReactionOutcome] = {}
    reduced: List[str] = []
    shared = _shared_fast_species(fast)
    for reaction in fast:
        outcome = _reduce_fast_reaction(model, reaction, shared)
        outcomes[reaction.id] = outcome
        if outcome.reduced:
            reduced.append(reaction.id)
    if reduced:
        model.reactions = OrderedDict(
            (key, value) for key, value in model.reactions.items() if key not in reduced
        )
    return outcomes


def _shared_fast_species(fast: Sequence[SBMLReaction]) -> Dict[str, List[str]]:
    """Return the species more than one fast reaction converts.

    Two fast reactions that share a species describe one fast subsystem, and
    its pseudo steady state is a multi-species balance rather than the
    independent reduction of either reaction.
    """

    owners: Dict[str, List[str]] = {}
    for reaction in fast:
        for identifier in _reaction_species_ids(reaction):
            owners.setdefault(identifier, []).append(reaction.id)
    return {
        identifier: reactions
        for identifier, reactions in owners.items()
        if len(reactions) > 1
    }


def _reaction_species_ids(reaction: SBMLReaction) -> Tuple[str, ...]:
    return tuple(
        reference.species
        for reference in [*reaction.reactants, *reaction.products]
        if reference.species and reference.species != "EmptySet"
    )


def _reduce_fast_reaction(
    model: SBMLModel,
    reaction: SBMLReaction,
    shared: Mapping[str, Sequence[str]],
) -> FastReactionOutcome:
    """Return the steady-state reduction of one fast reaction, when it has one."""

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    if reaction.multi_intra_species:
        return refuse("the fast reaction is an intra-species reaction")
    reactants = [
        reference
        for reference in reaction.reactants
        if reference.species and reference.species != "EmptySet"
    ]
    products = [
        reference
        for reference in reaction.products
        if reference.species and reference.species != "EmptySet"
    ]
    if len(reactants) != 1 or len(products) != 1:
        return refuse(
            "the fast reaction does not convert exactly one species into "
            "exactly one species"
        )
    reactant, product = reactants[0], products[0]
    for identifier in (reactant.species, product.species):
        owners = shared.get(identifier)
        if owners:
            others = ", ".join(f'"{owner}"' for owner in owners)
            return refuse(
                f'species "{identifier}" also takes part in the fast reaction '
                f"{others}, so the fast subsystem is a "
                "multi-species balance; reproducing it needs an algebraic "
                "solve in the simulation engine, which is a separate feature "
                "rather than a missing diagnostic"
            )
    if reactant.variable_stoichiometry or product.variable_stoichiometry:
        return refuse("the fast reaction's stoichiometry is not a constant")
    reactant_stoichiometry = float(reactant.stoichiometry)
    product_stoichiometry = float(product.stoichiometry)
    if (
        not math.isfinite(reactant_stoichiometry)
        or not math.isfinite(product_stoichiometry)
        or reactant_stoichiometry <= 0
        or product_stoichiometry <= 0
    ):
        return refuse("the fast reaction's stoichiometry is not a positive constant")
    if reactant_stoichiometry != round(
        reactant_stoichiometry
    ) or product_stoichiometry != round(product_stoichiometry):
        return refuse(
            "the fast reaction's stoichiometry is not a positive integer count"
        )

    rate = _kinetic_law_math(reaction)
    if not rate.strip():
        return refuse("the fast reaction has no kinetic law")
    expression = _parse_expression(rate)
    if expression is None:
        return refuse("the fast reaction's kinetic law is not a supported expression")
    expression = _inline_function_calls(expression, model.function_definitions)

    resolver = _ConstantResolver(model, reaction)
    terms = _rate_terms(expression, model, resolver)
    if terms is None:
        if any(
            resolver.is_time_dependent(name) for name in _expression_names(expression)
        ):
            return refuse(
                "the fast reaction's rate constant is not a time-independent value"
            )
        return refuse("the fast reaction's kinetic law is not a supported expression")
    active = [term for term in terms if term.coefficient != 0.0]
    if not active:
        # A rate that is zero for every state is an inert reaction: removing
        # it changes nothing, so the model keeps the source's trajectory.
        return FastReactionOutcome(
            reaction.id,
            True,
            detail=(
                "its kinetic law is zero for every state, so the reaction "
                "never carries a flux and is removed"
            ),
        )

    participants = {reactant.species, product.species}
    for term in active:
        for identifier in term.species_ids:
            if identifier not in participants:
                return refuse(
                    "the fast reaction's rate depends on a species it does "
                    "not convert"
                )
    if len(active) == 1:
        return _reduce_to_completion(
            model,
            reaction,
            reactant,
            product,
            reactant_stoichiometry,
            product_stoichiometry,
            active[0],
        )
    if len(active) == 2:
        return _reduce_to_balance(
            model,
            reaction,
            reactant,
            product,
            reactant_stoichiometry,
            product_stoichiometry,
            active,
        )
    return refuse(
        "the fast reaction's rate is a sum of more than two terms, so its "
        "pseudo steady state is a multi-term balance that needs an "
        "algebraic solve in the simulation engine"
    )


def _reduce_to_completion(
    model: SBMLModel,
    reaction: SBMLReaction,
    reactant: Any,
    product: Any,
    reactant_stoichiometry: float,
    product_stoichiometry: float,
    term: _RateTerm,
) -> FastReactionOutcome:
    """Reduce a fast reaction whose rate vanishes when one species is zero.

    A rate that is proportional to one of the two species, or to both of
    them, is zero exactly when the species it is proportional to is zero.
    The reaction therefore runs to completion: the species the rate
    vanishes with is held at zero and the other absorbs its initial
    amount, scaled by the stoichiometry ratio.
    """

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    coefficient = term.coefficient
    depends_on_reactant = reactant.species in term.species_ids
    depends_on_product = product.species in term.species_ids
    if coefficient > 0:
        # The reaction runs forwards, so the species it consumes is the one
        # the rate has to vanish with.
        if not depends_on_reactant:
            return refuse(
                "the fast reaction's rate runs forwards from the species it " "produces"
            )
        consumed, produced = reactant.species, product.species
        consumed_stoichiometry = reactant_stoichiometry
        produced_stoichiometry = product_stoichiometry
    else:
        # The reaction runs backwards, so the species it produces is the one
        # the rate has to vanish with.
        if not depends_on_product:
            return refuse(
                "the fast reaction's rate runs backwards from the species it "
                "consumes"
            )
        consumed, produced = product.species, reactant.species
        consumed_stoichiometry = product_stoichiometry
        produced_stoichiometry = reactant_stoichiometry

    consumed_species = model.species.get(consumed)
    produced_species = model.species.get(produced)
    if consumed_species is None or produced_species is None:
        return refuse("the fast reaction refers to a species the model does not define")
    if consumed == produced:
        return refuse("the fast reaction converts a species into itself")
    for modifier in reaction.modifiers:
        name = (
            modifier
            if isinstance(modifier, str)
            else str(getattr(modifier, "species", "") or "")
        )
        if name in {consumed, produced}:
            return refuse(
                f'species "{name}" is a modifier of the fast reaction, so the '
                "reaction does not change it"
            )
    for species in (consumed_species, produced_species):
        if species.constant:
            return refuse(f'species "{species.id}" is constant')
        if species.boundary_condition:
            return refuse(f'species "{species.id}" is a boundary species')
        if not (species.initial_amount_set or species.initial_concentration_set):
            return refuse(f'species "{species.id}" has no initial value')
        compartment = model.compartments.get(species.compartment or "")
        if compartment is not None and not compartment.constant:
            return refuse(f'compartment "{compartment.id}" is not constant')
    consumed_factor = _conversion_factor(model, consumed)
    produced_factor = _conversion_factor(model, produced)
    if consumed_factor is None or produced_factor is None:
        return refuse(
            "the fast reaction's species declare a conversion factor that is "
            "not a constant value"
        )

    for other in model.reactions.values():
        if other.id == reaction.id:
            continue
        for reference in [*other.reactants, *other.products]:
            if reference.species == consumed:
                return refuse(
                    f'species "{consumed}" also takes part in reaction "{other.id}"'
                )
        for modifier in other.modifiers:
            name = (
                modifier
                if isinstance(modifier, str)
                else str(getattr(modifier, "species", "") or "")
            )
            if name == consumed:
                return refuse(
                    f'species "{consumed}" is a modifier of reaction "{other.id}"'
                )

    controlled = _controlled_symbols(model)
    for identifier in (consumed, produced):
        if standardize_name(identifier) in controlled:
            return refuse(
                f'species "{identifier}" is reassigned by a rule, an initial '
                "assignment, or an event"
            )

    delayed = _delayed_species(model)
    for identifier in (consumed, produced):
        if standardize_name(identifier) in delayed:
            return refuse(
                f'species "{identifier}" is read by a delay expression, whose '
                "value before the delay elapses is the species' declared "
                "initial value"
            )

    consumed_amount = _species_amount(model, consumed_species)
    produced_amount = _species_amount(model, produced_species)
    if consumed_amount is None or produced_amount is None:
        return refuse("the fast reaction's species have no usable initial amount")
    # The reaction's extent follows from the consumed species' amount and its
    # own conversion factor, and the produced species' amount follows from the
    # extent and *its* conversion factor (SBML Level 3 Version 2 Core,
    # Sec. 4.11.7: the rate of change of a species' amount is its conversion
    # factor times the stoichiometry-weighted extent rate).
    extent = consumed_amount / (consumed_factor * consumed_stoichiometry)
    _set_species_amount(model, consumed_species, 0.0)
    _set_species_amount(
        model,
        produced_species,
        produced_amount + produced_factor * produced_stoichiometry * extent,
    )
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f'species "{consumed}" is held at zero and its initial amount is '
            f'transferred to "{produced}"'
        ),
    )


def _reduce_to_balance(
    model: SBMLModel,
    reaction: SBMLReaction,
    reactant: Any,
    product: Any,
    reactant_stoichiometry: float,
    product_stoichiometry: float,
    terms: Sequence[_RateTerm],
) -> FastReactionOutcome:
    """Reduce a fast reaction whose rate balances its two converted species.

    A rate that is the difference of a term proportional to the reactant
    and a term proportional to the product is zero exactly on the algebraic
    balance between the two species.  The pseudo steady state therefore
    holds the fast subsystem on that balance, and the slow reactions move
    along it: the species the balance pins changes at the slow reactions'
    scaled rate, and the fast subsystem's conserved combination changes at
    the slow reactions' own rate.
    """

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    positive = [term for term in terms if term.coefficient > 0]
    negative = [term for term in terms if term.coefficient < 0]
    if len(positive) != 1 or len(negative) != 1:
        return refuse(
            "the fast reaction's rate does not separate into one term per "
            "species it converts"
        )
    forward, backward = positive[0], negative[0]
    if len(forward.species) != 1 or len(backward.species) != 1:
        return refuse(
            "the fast reaction's rate is not proportional to one species each"
        )
    pinned_id = forward.species_ids[0]
    other_id = backward.species_ids[0]
    if pinned_id == other_id:
        return refuse("the fast reaction's rate balances a species against itself")
    if forward.species[0][1] != 1 or backward.species[0][1] != 1:
        return refuse(
            "the fast reaction's rate is not linear in the species it converts"
        )
    if pinned_id not in {reactant.species, product.species} or other_id not in {
        reactant.species,
        product.species,
    }:
        return refuse(
            "the fast reaction's rate depends on a species it does not convert"
        )

    pinned_species = model.species.get(pinned_id)
    other_species = model.species.get(other_id)
    if pinned_species is None or other_species is None:
        return refuse("the fast reaction refers to a species the model does not define")
    if (
        pinned_species.has_only_substance_units
        != other_species.has_only_substance_units
    ):
        return refuse(
            "the fast reaction's two species do not carry the same kind of "
            "quantity, so their balance is not a single algebraic condition"
        )
    if pinned_species.compartment != other_species.compartment:
        return refuse(
            "the fast reaction's two species are in different compartments, "
            "so their balance is not a single algebraic condition"
        )
    for species in (pinned_species, other_species):
        if species.constant:
            return refuse(f'species "{species.id}" is constant')
        if species.conversion_factor:
            return refuse(f'species "{species.id}" declares a conversion factor')
        if not (species.initial_amount_set or species.initial_concentration_set):
            return refuse(f'species "{species.id}" has no initial value')
    compartment = model.compartments.get(pinned_species.compartment or "")
    if compartment is None:
        return refuse("the fast reaction's species have no compartment")
    if not compartment.constant:
        return refuse(f'compartment "{compartment.id}" is not constant')
    if standardize_name(compartment.id) in _controlled_symbols(model):
        return refuse(
            f'compartment "{compartment.id}" is reassigned by a rule, an '
            "initial assignment, or an event"
        )

    pinned_value = _species_value(model, pinned_species)
    other_value = _species_value(model, other_species)
    if pinned_value is None or other_value is None:
        return refuse("the fast reaction's species have no usable initial value")
    pinned_coefficient = forward.coefficient
    other_coefficient = -backward.coefficient

    # The fast subsystem's conserved combination is nu_N * pinned + nu_P *
    # other, where the stoichiometries are the fast reaction's own counts.
    if pinned_id == reactant.species:
        pinned_stoichiometry = reactant_stoichiometry
        other_stoichiometry = product_stoichiometry
        pinned_signed = -reactant_stoichiometry
        other_signed = product_stoichiometry
    else:
        pinned_stoichiometry = product_stoichiometry
        other_stoichiometry = reactant_stoichiometry
        pinned_signed = product_stoichiometry
        other_signed = -reactant_stoichiometry

    pinned_boundary = pinned_species.boundary_condition
    other_boundary = other_species.boundary_condition
    if pinned_boundary and other_boundary:
        return refuse(
            "both species the fast reaction converts are boundary species, so "
            "the fast subsystem has no algebraic condition to satisfy"
        )
    frozen = pinned_boundary or other_boundary
    if frozen:
        # One of the two species is pinned, so the balance pins the other one
        # too, and the fast subsystem cannot move at all.
        frozen_id = other_id if pinned_boundary else pinned_id
        for other in model.reactions.values():
            if other.id == reaction.id:
                continue
            for reference in [*other.reactants, *other.products]:
                if reference.species == frozen_id:
                    return refuse(
                        f'species "{frozen_id}" also takes part in reaction '
                        f'"{other.id}", so it does not stay on the fast '
                        "reaction's balance"
                    )
    if pinned_boundary:
        # The pinned species keeps its value and the balance fixes the other.
        other_value = pinned_coefficient * pinned_value / other_coefficient
    elif other_boundary:
        pinned_value = other_coefficient * other_value / pinned_coefficient
    else:
        invariant = (
            other_stoichiometry * pinned_value + pinned_stoichiometry * other_value
        )
        denominator = (
            other_coefficient * other_stoichiometry
            + pinned_coefficient * pinned_stoichiometry
        )
        pinned_value = invariant * other_coefficient / denominator
        other_value = invariant * pinned_coefficient / denominator

    volume = _compartment_volume(model, pinned_species)
    if not math.isfinite(volume) or volume <= 0:
        return refuse("the fast reaction's compartment has no usable volume")
    substance_units = pinned_species.has_only_substance_units

    # The slow reactions' contribution to the fast subsystem's conserved
    # combination, scaled by the balance's stiffness.
    stiffness = pinned_coefficient * pinned_signed - other_coefficient * other_signed
    if stiffness == 0:
        return refuse(
            "the fast reaction's balance does not constrain the slow dynamics"
        )
    terms_expression = _slow_invariant_expression(
        model,
        reaction,
        pinned_id,
        other_id,
        pinned_signed,
        other_signed,
    )
    if terms_expression is None:
        return refuse(
            "the fast reaction's slow reactions do not have a kinetic law the "
            "balance can use"
        )
    if not substance_units:
        terms_expression = f"({terms_expression}) / {format_number(volume)}"

    pinned_rule = (
        f"({format_number(other_coefficient)} / {format_number(stiffness)})"
        f" * ({terms_expression})"
    )
    other_rule = (
        f"({format_number(pinned_coefficient)} / {format_number(stiffness)})"
        f" * ({terms_expression})"
    )

    for identifier in (pinned_id, other_id):
        species = model.species[identifier]
        if standardize_name(identifier) in _controlled_symbols(model):
            return refuse(
                f'species "{identifier}" is reassigned by a rule, an initial '
                "assignment, or an event"
            )
        if standardize_name(identifier) in _delayed_species(model):
            return refuse(
                f'species "{identifier}" is read by a delay expression, whose '
                "value before the delay elapses is the species' declared "
                "initial value"
            )

    # A slow reaction that only converts the two fast species would have no
    # participant left once the balance's rate rules replace them.
    for other in model.reactions.values():
        if other.id == reaction.id:
            continue
        participants = [
            reference.species
            for reference in [*other.reactants, *other.products]
            if reference.species and reference.species != "EmptySet"
        ]
        if not participants or not set(participants) <= {pinned_id, other_id}:
            continue
        return refuse(
            f'reaction "{other.id}" only converts the species the fast '
            "reaction converts, so the balance leaves it without a "
            "participant"
        )

    _set_species_value(model, pinned_species, pinned_value)
    _set_species_value(model, other_species, other_value)
    if not frozen:
        _add_rate_rule(model, pinned_id, pinned_rule)
        _add_rate_rule(model, other_id, other_rule)
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f"the fast subsystem is held on the balance "
            f"{format_number(pinned_coefficient)}*{pinned_id} = "
            f"{format_number(other_coefficient)}*{other_id}, and the slow "
            "reactions move along it"
        ),
    )


def _slow_invariant_expression(
    model: SBMLModel,
    reaction: SBMLReaction,
    pinned_id: str,
    other_id: str,
    pinned_signed: float,
    other_signed: float,
) -> Optional[str]:
    """Return the slow reactions' contribution to the fast subsystem's balance.

    The expression is the sum over the slow reactions of the change their
    stoichiometry makes to the fast subsystem's conserved combination.
    """

    pieces: List[str] = []
    for other in model.reactions.values():
        if other.id == reaction.id:
            continue
        pinned_coefficient = _signed_stoichiometry(other, pinned_id)
        other_coefficient = _signed_stoichiometry(other, other_id)
        weight = pinned_signed * other_coefficient - other_signed * pinned_coefficient
        if weight == 0:
            continue
        rate = _kinetic_law_math(other).strip()
        if not rate:
            return None
        if weight == 1:
            pieces.append(f"({rate})")
        elif weight == -1:
            pieces.append(f"-({rate})")
        else:
            pieces.append(f"({format_number(weight)}) * ({rate})")
    if not pieces:
        return "0"
    return " + ".join(pieces)


def _signed_stoichiometry(reaction: SBMLReaction, species_id: str) -> float:
    """Return a species' signed stoichiometry in a reaction."""

    total = 0.0
    for reference in reaction.reactants:
        if reference.species == species_id:
            total -= float(reference.stoichiometry)
    for reference in reaction.products:
        if reference.species == species_id:
            total += float(reference.stoichiometry)
    return total


def _add_rate_rule(model: SBMLModel, variable: str, math: str) -> None:
    """Give a species the derivative the fast reaction's balance implies."""

    from .types import SBMLRule

    model.rules.append(SBMLRule(type="rate", variable=variable, math=math))


def _kinetic_law_math(reaction: SBMLReaction) -> str:
    law = reaction.kinetic_law
    if isinstance(law, Mapping):
        return str(law.get("math", "") or "")
    return str(getattr(law, "math", "") or "")


def _model_expressions(model: SBMLModel) -> List[str]:
    """Return every expression the model evaluates."""

    expressions = [_kinetic_law_math(reaction) for reaction in model.reactions.values()]
    expressions.extend(str(rule.math or "") for rule in model.rules)
    expressions.extend(
        str(assignment.math or "") for assignment in model.initial_assignments
    )
    for event in model.events:
        expressions.append(str(event.trigger or ""))
        expressions.append(str(event.delay or ""))
        expressions.append(str(event.priority or ""))
        expressions.extend(
            str(assignment.math or "") for assignment in event.assignments
        )
    return expressions


def _delayed_species(model: SBMLModel) -> set[str]:
    """Return the species a delay expression reads.

    A delay expression reports the delayed quantity's declared initial value
    until the delay elapses, so a fast reaction that changes that value
    cannot be reduced without changing the delay's own semantics.
    """

    delayed: set[str] = set()
    for expression in _model_expressions(model):
        for match in re.finditer(
            r"\bdelay\s*\(\s*([A-Za-z_][A-Za-z_0-9]*)", expression
        ):
            delayed.add(standardize_name(match.group(1)))
    return delayed


def _controlled_symbols(model: SBMLModel) -> set[str]:
    """Return the symbols whose value a rule, assignment, or event can change."""

    controlled: set[str] = set()
    for rule in model.rules:
        if rule.variable:
            controlled.add(standardize_name(str(rule.variable)))
    for assignment in model.initial_assignments:
        if assignment.symbol:
            controlled.add(standardize_name(str(assignment.symbol)))
    for event in model.events:
        for assignment in event.assignments:
            variable = getattr(assignment, "variable", None)
            if variable:
                controlled.add(standardize_name(str(variable)))
    return controlled


def _time_dependent_symbols(model: SBMLModel) -> set[str]:
    """Return the symbols whose value changes during the run.

    A rate rule and an event assignment change a symbol's value as the run
    proceeds; an assignment rule holds its target's value for the whole run,
    and an initial assignment only sets a value at the start of it.
    """

    dependent: set[str] = set()
    for rule in model.rules:
        if rule.variable and rule.type == "rate":
            dependent.add(standardize_name(str(rule.variable)))
    for event in model.events:
        for assignment in event.assignments:
            variable = getattr(assignment, "variable", None)
            if variable:
                dependent.add(standardize_name(str(variable)))
    return dependent


class _ConstantResolver:
    """Resolve the symbols of a rate law that hold a time-independent value."""

    def __init__(self, model: SBMLModel, reaction: SBMLReaction) -> None:
        self._model = model
        self._values: Dict[str, float] = {}
        self._species: Dict[str, str] = {
            standardize_name(str(identifier)): str(identifier)
            for identifier in model.species
        }
        controlled = _controlled_symbols(model)
        dependent = _time_dependent_symbols(model)
        # Two passes: a parameter's value can be stated in terms of another
        # parameter's, and the second pass picks up what the first resolved.
        for _ in range(2):
            for identifier, parameter in model.parameters.items():
                key = standardize_name(str(identifier))
                if key in dependent or key in self._values:
                    continue
                value = self._parameter_value(model, identifier, parameter, controlled)
                if value is not None and math.isfinite(value):
                    self._values[key] = value
        for identifier, compartment in model.compartments.items():
            key = standardize_name(str(identifier))
            if key in controlled or not getattr(compartment, "constant", True):
                continue
            value = float(compartment.size)
            if math.isfinite(value):
                self._values[key] = value
        for identifier, species in model.species.items():
            key = standardize_name(str(identifier))
            if key in controlled or not getattr(species, "constant", False):
                continue
            amount = _species_amount(model, species)
            if amount is None:
                continue
            self._values[key] = (
                amount
                if species.has_only_substance_units
                else amount / _compartment_volume(model, species)
            )
        law = reaction.kinetic_law
        for parameter in list(getattr(law, "local_parameters", []) or []):
            value = float(getattr(parameter, "value", 0.0))
            if math.isfinite(value):
                self._values[standardize_name(str(parameter.id))] = value

    def species_id(self, identifier: str) -> Optional[str]:
        """Return the model species an expression symbol names."""

        if str(identifier).strip().lower() == "time":
            return None
        return self._species.get(standardize_name(str(identifier)))

    def value(self, identifier: str) -> Optional[float]:
        """Return the time-independent value of a symbol, when it has one."""

        text = str(identifier).strip()
        if text.lower() == "time":
            return 0.0 if self._allow_time else None
        return self._values.get(standardize_name(text))

    def is_time_dependent(self, identifier: str) -> bool:
        """Say whether a symbol's value changes during the run.

        Only a parameter or a compartment can make a rate law time-dependent
        on its own: a species' value changes with the model's state, and an
        unknown symbol is a shape the reduction does not understand.
        """

        text = str(identifier).strip()
        if text.lower() == "time":
            return True
        key = standardize_name(text)
        if key in self._values or key in self._species:
            return False
        return key in self._model.parameters or key in self._model.compartments

    _allow_time = False

    def _parameter_value(
        self,
        model: SBMLModel,
        identifier: str,
        parameter: Any,
        controlled: Mapping[str, str],
    ) -> Optional[float]:
        """Return the time-independent value of a parameter, when it has one.

        An initial assignment overrides a parameter's declared value at the
        start of the run, and an assignment rule holds its target's value for
        the whole run.  A parameter that nothing else changes keeps the value
        it starts with.
        """

        key = standardize_name(str(identifier))
        value = self._initial_assignment_value(model, identifier)
        if value is not None:
            return value
        value = self._assignment_rule_value(model, identifier)
        if value is not None:
            return value
        if getattr(parameter, "constant", True):
            return None if key in controlled else float(parameter.value)
        if getattr(parameter, "value_set", False):
            return float(parameter.value)
        return None

    def _assignment_rule_value(
        self, model: SBMLModel, identifier: str
    ) -> Optional[float]:
        """Return the value a static assignment rule gives a parameter."""

        key = standardize_name(str(identifier))
        rules = [
            rule
            for rule in model.rules
            if rule.type == "assignment"
            and rule.variable
            and standardize_name(str(rule.variable)) == key
        ]
        if len(rules) != 1:
            return None
        expression = _parse_expression(str(rules[0].math or ""))
        if expression is None:
            return None
        terms = _rate_terms(expression, model, self)
        if terms is None or any(term.species for term in terms):
            return None
        value = math.fsum(term.coefficient for term in terms)
        return value if math.isfinite(value) else None

    def _initial_assignment_value(
        self, model: SBMLModel, identifier: str
    ) -> Optional[float]:
        """Return the value an initial assignment gives a parameter at t=0."""

        key = standardize_name(str(identifier))
        for assignment in model.initial_assignments:
            if standardize_name(str(assignment.symbol or "")) != key:
                continue
            expression = _parse_expression(str(assignment.math or ""))
            if expression is None:
                return None
            self._allow_time = True
            try:
                terms = _rate_terms(expression, model, self)
            finally:
                self._allow_time = False
            if terms is None or any(term.species for term in terms):
                return None
            value = math.fsum(term.coefficient for term in terms)
            return value if math.isfinite(value) else None
        return None


def _conversion_factor(model: SBMLModel, species_id: str) -> Optional[float]:
    """Return the effective conversion factor of a species.

    A species' own conversion factor takes precedence over the model's
    (SBML Level 3 Version 2 Core, Sec. 4.6.7), and a model without one
    leaves the factor at one.
    """

    species = model.species.get(species_id)
    factor_id = (getattr(species, "conversion_factor", None) if species else None) or (
        getattr(model, "conversion_factor", None) or None
    )
    if not factor_id:
        return 1.0
    parameter = model.parameters.get(factor_id)
    if parameter is None or not getattr(parameter, "constant", True):
        return None
    try:
        value = float(parameter.value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value == 0:
        return None
    return value


def _expression_names(expression: ast.AST) -> List[str]:
    """Return the symbols an expression names."""

    return [node.id for node in ast.walk(expression) if isinstance(node, ast.Name)]


def _compartment_volume(model: SBMLModel, species: SBMLSpecies) -> float:
    if not species.compartment:
        return 1.0
    compartment = model.compartments.get(species.compartment)
    if compartment is None:
        return 1.0
    return float(compartment.size)


def _species_amount(model: SBMLModel, species: SBMLSpecies) -> Optional[float]:
    """Return the species' initial amount of substance."""

    if not (species.initial_amount_set or species.initial_concentration_set):
        return None
    volume = _compartment_volume(model, species)
    if not math.isfinite(volume) or volume == 0:
        return None
    if species.has_only_substance_units:
        amount = (
            float(species.initial_amount)
            if species.initial_amount_set
            else float(species.initial_concentration) * volume
        )
    else:
        amount = (
            float(species.initial_concentration) * volume
            if species.initial_concentration_set
            else float(species.initial_amount)
        )
    return amount if math.isfinite(amount) else None


def _species_value(model: SBMLModel, species: SBMLSpecies) -> Optional[float]:
    """Return the species' initial value, the quantity its symbol denotes."""

    amount = _species_amount(model, species)
    if amount is None:
        return None
    if species.has_only_substance_units:
        return amount
    volume = _compartment_volume(model, species)
    if not math.isfinite(volume) or volume == 0:
        return None
    return amount / volume


def _set_species_amount(model: SBMLModel, species: SBMLSpecies, amount: float) -> None:
    """Write an initial amount of substance back into the species' own units."""

    volume = _compartment_volume(model, species)
    if not math.isfinite(volume) or volume == 0:
        volume = 1.0
    if species.has_only_substance_units:
        if species.initial_amount_set:
            species.initial_amount = amount
        else:
            species.initial_concentration = amount / volume
    elif species.initial_concentration_set:
        species.initial_concentration = amount / volume
    else:
        species.initial_amount = amount


def _set_species_value(model: SBMLModel, species: SBMLSpecies, value: float) -> None:
    """Write an initial value back into the species' own units."""

    if species.has_only_substance_units:
        _set_species_amount(model, species, value)
        return
    volume = _compartment_volume(model, species)
    if not math.isfinite(volume) or volume == 0:
        volume = 1.0
    _set_species_amount(model, species, value * volume)


def _parse_expression(source: str) -> Optional[ast.Expression]:
    safe_source = re.sub(
        r"\b(if|and|or|not)\s*(?=\()",
        lambda match: "bng_" + match.group(1),
        source,
    )
    safe_source = safe_source.replace("^", "**")
    try:
        return ast.parse(safe_source, mode="eval")
    except (SyntaxError, ValueError):
        return None


def _inline_function_calls(
    node: ast.AST,
    functions: Mapping[str, Any],
    stack: Tuple[str, ...] = (),
) -> ast.AST:
    """Expand user-defined SBML function calls into their bodies."""

    return _FunctionInliner(functions, stack).visit(node)


class _FunctionInliner(ast.NodeTransformer):
    """Replace user-defined SBML function calls with their expanded bodies."""

    def __init__(
        self, functions: Mapping[str, Any], stack: Tuple[str, ...] = ()
    ) -> None:
        self._functions = functions
        self._stack = stack

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.func, ast.Name):
            return node
        definition = _find_function(self._functions, node.func.id)
        if definition is None:
            return node
        key = str(getattr(definition, "id", "") or node.func.id)
        arguments = [str(argument) for argument in getattr(definition, "arguments", [])]
        body = _parse_expression(str(getattr(definition, "math", "") or ""))
        if body is None or key in self._stack or len(arguments) != len(node.args):
            return node
        mapping = {
            argument: copy.deepcopy(actual)
            for argument, actual in zip(arguments, node.args)
        }
        expanded = _Substituter(mapping).visit(body.body)
        return _FunctionInliner(self._functions, (*self._stack, key)).visit(expanded)


def _find_function(functions: Mapping[str, Any], name: str) -> Optional[Any]:
    direct = functions.get(name)
    if direct is not None:
        return direct
    normalized = standardize_name(name)
    return next(
        (
            function
            for function_id, function in functions.items()
            if standardize_name(str(function_id)) == normalized
        ),
        None,
    )


class _Substituter(ast.NodeTransformer):
    """Replace the formal parameters of a function body with actual arguments."""

    def __init__(self, mapping: Mapping[str, ast.AST]) -> None:
        self._mapping = {standardize_name(key): value for key, value in mapping.items()}

    def visit_Name(self, node: ast.Name) -> ast.AST:
        replacement = self._mapping.get(standardize_name(node.id))
        if replacement is None:
            return node
        return copy.deepcopy(replacement)


def _merge_species(
    left: Tuple[Tuple[str, int], ...], right: Tuple[Tuple[str, int], ...]
) -> Tuple[Tuple[str, int], ...]:
    merged: Dict[str, int] = {identifier: exponent for identifier, exponent in left}
    for identifier, exponent in right:
        merged[identifier] = merged.get(identifier, 0) + exponent
    return tuple(sorted(merged.items()))


def _rate_terms(
    node: ast.AST, model: SBMLModel, resolver: _ConstantResolver
) -> Optional[List[_RateTerm]]:
    """Split a rate law into the additive terms of species products it holds.

    Every term is a product of species with a constant coefficient, so a
    rate law the pseudo steady state can be read from is one whose terms
    name species and multiply them by time-independent factors.
    """

    def constant(value: float) -> List[_RateTerm]:
        return [_RateTerm((), float(value))]

    def scale(terms: List[_RateTerm], factor: float) -> List[_RateTerm]:
        return [_RateTerm(term.species, term.coefficient * factor) for term in terms]

    def merge(left: _RateTerm, right: _RateTerm) -> _RateTerm:
        return _RateTerm(
            _merge_species(left.species, right.species),
            left.coefficient * right.coefficient,
        )

    def visit(node: ast.AST) -> Optional[List[_RateTerm]]:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return constant(float(value))
        if isinstance(node, ast.Name):
            identifier = resolver.species_id(node.id)
            if identifier is not None:
                return [_RateTerm(((identifier, 1),), 1.0)]
            value = resolver.value(node.id)
            if value is None:
                return None
            return constant(value)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.UAdd):
                return visit(node.operand)
            if isinstance(node.op, ast.USub):
                inner = visit(node.operand)
                return None if inner is None else scale(inner, -1.0)
            return None
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Add):
                left, right = visit(node.left), visit(node.right)
                if left is None or right is None:
                    return None
                return left + right
            if isinstance(node.op, ast.Sub):
                left, right = visit(node.left), visit(node.right)
                if left is None or right is None:
                    return None
                return left + scale(right, -1.0)
            if isinstance(node.op, ast.Mult):
                left, right = visit(node.left), visit(node.right)
                if left is None or right is None:
                    return None
                if len(left) == 1 and len(right) == 1:
                    return [merge(left[0], right[0])]
                if all(not term.species for term in left):
                    factor = 1.0
                    for term in left:
                        factor *= term.coefficient
                    return scale(right, factor)
                if all(not term.species for term in right):
                    factor = 1.0
                    for term in right:
                        factor *= term.coefficient
                    return scale(left, factor)
                return None
            if isinstance(node.op, ast.Div):
                left, right = visit(node.left), visit(node.right)
                if left is None or right is None or len(right) != 1:
                    return None
                denominator = right[0]
                if denominator.species or denominator.coefficient == 0:
                    return None
                return scale(left, 1.0 / denominator.coefficient)
            if isinstance(node.op, ast.Pow):
                base = visit(node.left)
                exponent = visit(node.right)
                if base is None or exponent is None or len(exponent) != 1:
                    return None
                power = exponent[0]
                if power.species:
                    return None
                if len(base) != 1:
                    return None
                term = base[0]
                if not term.species:
                    try:
                        value = float(term.coefficient**power.coefficient)
                    except (ArithmeticError, OverflowError, ValueError):
                        return None
                    if not math.isfinite(value):
                        return None
                    return constant(value)
                if not float(power.coefficient).is_integer():
                    return None
                count = int(power.coefficient)
                if count < 1:
                    return None
                return [
                    _RateTerm(
                        tuple(
                            (identifier, exponent * count)
                            for identifier, exponent in term.species
                        ),
                        term.coefficient,
                    )
                ]
            return None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            values: List[float] = []
            for argument in node.args:
                inner = visit(argument)
                if inner is None or len(inner) != 1 or inner[0].species:
                    return None
                values.append(inner[0].coefficient)
            value = evaluate_math_builtin(node.func.id, values)
            if value is None:
                return None
            return constant(value)
        return None

    return visit(node)
