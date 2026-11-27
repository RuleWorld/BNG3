"""Reduce an SBML fast reaction to the pseudo steady state it defines.

SBML Level 3 Version 1 Section 4.11 and SBML Level 2 Section 4.13 (Section 4.9
in Level 2 Version 1) describe a reaction whose
``fast`` attribute is true as operating on a time scale significantly faster
than the model's other reactions: fast reactions are "considered to be
instantaneous relative to the slow reactions", and, from Level 2 Version 2
on, software tools "should use a pseudo steady-state approximation for the set
of fast reactions when constructing the system of equations for the model".
The attribute changes
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

When the rate constants change during the run (an event or a rule sets
them) or an event changes the fast reaction's stoichiometry, the steady state
moves with them.  Both shapes then reduce through the fast subsystem's
conserved pool ``nu_P * n_R + nu_R * n_P`` (amounts): the pool is a state that
only the slow reactions change, and the two species are the closed-form
functions of the pool and the current rate constants that the steady state
defines.  An event that changes the stoichiometry re-expresses the pool from
the amounts at that instant.  See ``_reduce_with_pool`` for the conditions.

Every other shape of fast reaction needs an algebraic solve that BNG3 cannot
perform, so those are reported with the specific reason they cannot be
reduced.
"""

from __future__ import annotations

import ast
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .math_builtins import evaluate_math_builtin, format_number
from .types import SBMLModel, SBMLReaction, SBMLSpecies, standardize_name
from .helpers import clone_ast


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

    # First attempt coupled reversible linear fast subsystems (connected
    # components of >= 2 fast reactions sharing species).
    handled_coupled: set[str] = set()
    if shared:
        for component in _fast_reaction_components(fast):
            if len(component) < 2:
                continue
            coupled_outcomes = _reduce_coupled_linear_fast_component(model, component)
            if coupled_outcomes is not None:
                for rxn_id, outcome in coupled_outcomes.items():
                    outcomes[rxn_id] = outcome
                    if outcome.reduced:
                        reduced.append(rxn_id)
                        handled_coupled.add(rxn_id)

    for reaction in fast:
        if reaction.id in handled_coupled:
            continue
        outcome = _reduce_fast_reaction(model, reaction, shared)
        outcomes[reaction.id] = outcome
        if outcome.reduced:
            reduced.append(reaction.id)
    if reduced:
        model.reactions = OrderedDict(
            (key, value) for key, value in model.reactions.items() if key not in reduced
        )
    return outcomes


def _fast_reaction_components(
    fast: Sequence[SBMLReaction],
) -> List[List[SBMLReaction]]:
    """Partition fast reactions into connected components by shared species."""

    by_id = {reaction.id: reaction for reaction in fast}
    species_to_rxns: Dict[str, List[str]] = {}
    for reaction in fast:
        for sid in _reaction_species_ids(reaction):
            species_to_rxns.setdefault(sid, []).append(reaction.id)
    visited: set[str] = set()
    components: List[List[SBMLReaction]] = []
    for reaction in fast:
        if reaction.id in visited:
            continue
        queue = [reaction.id]
        visited.add(reaction.id)
        comp_ids: List[str] = []
        while queue:
            current = queue.pop(0)
            comp_ids.append(current)
            for sid in _reaction_species_ids(by_id[current]):
                for neighbor in species_to_rxns.get(sid, ()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
        components.append([by_id[rid] for rid in comp_ids])
    return components


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
    if (len(reactants) == 2 and len(products) == 1) or (
        len(reactants) == 1 and len(products) == 2
    ):
        for identifier in _reaction_species_ids(reaction):
            owners = shared.get(identifier)
            if owners:
                others = ", ".join(f'"{owner}"' for owner in owners)
                return refuse(
                    f'species "{identifier}" also takes part in the fast reaction '
                    f"{others}, so the fast subsystem is not an isolated equilibrium"
                )
        if len(reactants) == 2:
            return _reduce_bimolecular_equilibrium(
                model, reaction, reactants, products[0], dissociation=False
            )
        return _reduce_bimolecular_equilibrium(
            model, reaction, products, reactants[0], dissociation=True
        )
    if len(reactants) == 2 and len(products) == 2:
        for identifier in _reaction_species_ids(reaction):
            owners = shared.get(identifier)
            if owners:
                others = ", ".join(f'"{owner}"' for owner in owners)
                return refuse(
                    f'species "{identifier}" also takes part in the fast reaction '
                    f"{others}, so the fast subsystem is not an isolated equilibrium"
                )
        return _reduce_bimolecular_exchange_equilibrium(
            model, reaction, reactants, products
        )
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
        # An event can change the stoichiometry, which changes the fast
        # subsystem's conserved combination; the pooled reduction carries it.
        return _reduce_with_pool(model, reaction, reactant, product)
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
            # The rate constant changes during the run (an event or a rule
            # sets it), so the fast subsystem's steady state moves with it.
            return _reduce_with_pool(model, reaction, reactant, product)
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


def _reduce_bimolecular_equilibrium(
    model: SBMLModel,
    reaction: SBMLReaction,
    pair: Sequence[Any],
    complex_ref: Any,
    *,
    dissociation: bool = False,
) -> FastReactionOutcome:
    """Lower A+B<->C (or C<->A+B) to its exact equilibrium on its two evolving pools.

    This bounded form requires unit stoichiometry and constant positive forward
    and reverse coefficients.  The coordinates P=A+C and Q=B+C are the two
    independent invariants of the fast reaction; slow reactions evolve those
    pools, while the quadratic root reconstructs the fast equilibrium.
    """

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    a_ref, b_ref = pair
    identifiers = (a_ref.species, b_ref.species, complex_ref.species)
    if len(set(identifiers)) != 3:
        return refuse("the fast reaction does not convert three distinct species")
    if any(
        re.search(r"\bdelay\s*\(", expression, flags=re.IGNORECASE)
        for expression in _model_expressions(model)
    ):
        return refuse(
            "the bimolecular pool projection cannot preserve delayed prehistory"
        )
    if any(
        reference.variable_stoichiometry or float(reference.stoichiometry) != 1
        for reference in (*pair, complex_ref)
    ):
        return refuse("the bimolecular fast reaction requires unit stoichiometry")
    species = [model.species.get(identifier) for identifier in identifiers]
    if any(item is None for item in species):
        return refuse("the fast reaction refers to a species the model does not define")
    a_species, b_species, c_species = species
    assert a_species is not None and b_species is not None and c_species is not None
    if len({item.compartment for item in species}) != 1:
        return refuse("the fast reaction's species must share one compartment")
    if len({item.has_only_substance_units for item in species}) != 1:
        return refuse("the fast reaction's species must use the same quantity kind")
    for item in species:
        if item.constant or item.boundary_condition:
            return refuse(f'species "{item.id}" must be mutable and non-boundary')
        if not (item.initial_amount_set or item.initial_concentration_set):
            return refuse(f'species "{item.id}" has no initial value')
        if item.conversion_factor or getattr(model, "conversion_factor", None):
            return refuse(
                "the bimolecular pool lowering does not carry conversion factors"
            )
        if standardize_name(item.id) in _controlled_symbols(model):
            return refuse(f'species "{item.id}" is reassigned by a rule or event')
        if standardize_name(item.id) in _delayed_species(model):
            return refuse(f'species "{item.id}" is read by a delay expression')
    compartment = model.compartments.get(a_species.compartment or "")
    if compartment is None or not compartment.constant:
        return refuse("the fast reaction requires a constant shared compartment")
    if standardize_name(compartment.id) in _controlled_symbols(model):
        return refuse(
            f'compartment "{compartment.id}" is reassigned by a rule or event'
        )
    volume = _compartment_volume(model, a_species)
    if not math.isfinite(volume) or volume <= 0:
        return refuse("the fast reaction's compartment has no usable volume")

    expression = _parse_expression(_kinetic_law_math(reaction))
    if expression is None:
        return refuse("the fast reaction's kinetic law is not a supported expression")
    expression = _inline_function_calls(expression, model.function_definitions)
    resolver = _ConstantResolver(model, reaction)
    terms = _rate_terms(expression, model, resolver)
    if terms is None or len(terms) != 2:
        return refuse(
            "the fast rate must be a two-term constant-coefficient mass action law"
        )
    terms = [term for term in terms if term.coefficient]
    pair_term = next(
        (
            term
            for term in terms
            if term.species == tuple(sorted(((a_ref.species, 1), (b_ref.species, 1))))
        ),
        None,
    )
    complex_term = next(
        (term for term in terms if term.species == ((complex_ref.species, 1),)), None
    )
    if dissociation:
        # C <-> A + B: forward rate is +kf * C, reverse rate is -kr * A * B.
        if (
            len(terms) != 2
            or complex_term is None
            or pair_term is None
            or complex_term.coefficient <= 0
            or pair_term.coefficient >= 0
        ):
            return refuse("the fast rate must be positive kf*C minus positive kr*A*B")
        equilibrium_constant = complex_term.coefficient / (-pair_term.coefficient)
    else:
        # A + B <-> C: forward rate is +kf * A * B, reverse rate is -kr * C.
        if (
            len(terms) != 2
            or pair_term is None
            or complex_term is None
            or pair_term.coefficient <= 0
            or complex_term.coefficient >= 0
        ):
            return refuse("the fast rate must be positive kf*A*B minus positive kr*C")
        equilibrium_constant = (-complex_term.coefficient) / pair_term.coefficient
    if not math.isfinite(equilibrium_constant) or equilibrium_constant <= 0:
        return refuse("the fast rate has no finite positive equilibrium constant")

    initial = [_species_amount(model, item) for item in species]
    if any(value is None for value in initial):
        return refuse("the fast reaction's species have no usable initial amount")
    amount_a, amount_b, amount_c = (float(value) for value in initial)
    if min(amount_a, amount_b, amount_c) < 0:
        return refuse("the fast reaction's species have a negative initial amount")
    if a_species.has_only_substance_units:
        pool_a0, pool_b0 = amount_a + amount_c, amount_b + amount_c
    else:
        pool_a0, pool_b0 = (amount_a + amount_c) / volume, (
            amount_b + amount_c
        ) / volume

    from .types import SBMLModifierSpeciesReference, SBMLParameter, SBMLRule

    pool_a = _unique_identifier(model, f"__fast_pool_a_{standardize_name(reaction.id)}")
    pool_b = _unique_identifier(model, f"__fast_pool_b_{standardize_name(reaction.id)}")
    symbol_scale = 1.0 if a_species.has_only_substance_units else 1.0 / volume

    pool_rate_a: List[str] = []
    pool_rate_b: List[str] = []
    for slow in model.reactions.values():
        if slow.id == reaction.id:
            continue
        if any(
            reference.species in identifiers and reference.variable_stoichiometry
            for reference in [*slow.reactants, *slow.products]
        ):
            return refuse(
                f'reaction "{slow.id}" changes a fast-equilibrium species with '
                "variable stoichiometry"
            )
        sigma_a = _signed_stoichiometry(slow, a_species.id)
        sigma_b = _signed_stoichiometry(slow, b_species.id)
        sigma_c = _signed_stoichiometry(slow, c_species.id)
        if sigma_a + sigma_c:
            rate = _global_kinetic_law(slow)
            if rate is None:
                return refuse(
                    f'reaction "{slow.id}" has no usable kinetic law for pool A'
                )
            pool_rate_a.append(
                f"({format_number(symbol_scale * (sigma_a + sigma_c))}) * ({rate})"
            )
        if sigma_b + sigma_c:
            rate = _global_kinetic_law(slow)
            if rate is None:
                return refuse(
                    f'reaction "{slow.id}" has no usable kinetic law for pool B'
                )
            pool_rate_b.append(
                f"({format_number(symbol_scale * (sigma_b + sigma_c))}) * ({rate})"
            )

    # Reject initial pools outside the real, nonnegative equilibrium branch.
    discriminant = (
        pool_a0 + pool_b0 + equilibrium_constant
    ) ** 2 - 4 * pool_a0 * pool_b0
    if pool_a0 < 0 or pool_b0 < 0 or discriminant < 0:
        return refuse("the initial pools have no real nonnegative fast equilibrium")
    c0 = (pool_a0 + pool_b0 + equilibrium_constant - math.sqrt(discriminant)) / 2
    if c0 < 0 or c0 > min(pool_a0, pool_b0):
        return refuse("the initial fast equilibrium is outside the nonnegative branch")

    pool_a_expr, pool_b_expr = pool_a, pool_b
    c_expr = (
        f"(({pool_a_expr} + {pool_b_expr} + {format_number(equilibrium_constant)}) "
        f"- sqrt(({pool_a_expr} + {pool_b_expr} + {format_number(equilibrium_constant)})^2 "
        f"- 4 * {pool_a_expr} * {pool_b_expr})) / 2"
    )
    reconstructed = {
        a_species.id: f"{pool_a_expr} - {c_expr}",
        b_species.id: f"{pool_b_expr} - {c_expr}",
        c_species.id: c_expr,
    }
    for item, amount in zip(species, (pool_a0 - c0, pool_b0 - c0, c0)):
        _set_species_amount(
            model, item, amount if item.has_only_substance_units else amount * volume
        )
    for name, initial_value in ((pool_a, pool_a0), (pool_b, pool_b0)):
        model.parameters[name] = SBMLParameter(
            id=name, name=name, value=initial_value, constant=False, value_set=True
        )
    model.rules.extend(
        [
            SBMLRule(type="rate", variable=pool_a, math=" + ".join(pool_rate_a) or "0"),
            SBMLRule(type="rate", variable=pool_b, math=" + ".join(pool_rate_b) or "0"),
            *[
                SBMLRule(
                    type="assignment",
                    variable=item.id,
                    math=reconstructed[item.id],
                )
                for item in species
            ],
        ]
    )
    del model.reactions[reaction.id]
    participants = set(identifiers)
    for slow in model.reactions.values():
        moved = [
            reference
            for reference in [*slow.reactants, *slow.products]
            if reference.species in participants
        ]
        slow.reactants = [
            reference
            for reference in slow.reactants
            if reference.species not in participants
        ]
        slow.products = [
            reference
            for reference in slow.products
            if reference.species not in participants
        ]
        present = {_modifier_species(modifier) for modifier in slow.modifiers}
        for reference in moved:
            if reference.species not in present:
                slow.modifiers.append(SBMLModifierSpeciesReference(reference.species))
                present.add(reference.species)
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f"the fast equilibrium is reconstructed on the conserved pools "
            f"{pool_a}={a_species.id}+{c_species.id} and "
            f"{pool_b}={b_species.id}+{c_species.id}"
        ),
    )


def _reduce_homodimer_equilibrium(
    model: SBMLModel,
    reaction: SBMLReaction,
    monomer_id: str,
    dimer_id: str,
    equilibrium_constant: float,
) -> FastReactionOutcome:
    """Lower 2A <-> C (or C <-> 2A) to its exact equilibrium on pool P = A + 2C.

    At equilibrium A^2 = Kd * C with C = (P - A)/2, giving the unique
    nonnegative root A = (-Kd + sqrt(Kd^2 + 8*Kd*P)) / 4 for all P >= 0.
    """

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    if any(
        re.search(r"\bdelay\s*\(", expression, flags=re.IGNORECASE)
        for expression in _model_expressions(model)
    ):
        return refuse(
            "the homodimer pool projection cannot preserve delayed prehistory"
        )
    for expression in _model_expressions(model):
        names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expression))
        if reaction.id in names:
            return refuse(
                f'an expression reads the fast reaction "{reaction.id}"\'s rate'
            )
        if "rateOf" in names and names & {monomer_id, dimer_id}:
            return refuse(
                "an expression reads the rate of change of a fast-equilibrium species"
            )
    a_species = model.species.get(monomer_id)
    c_species = model.species.get(dimer_id)
    if a_species is None or c_species is None:
        return refuse("the fast reaction refers to a species the model does not define")
    if a_species.compartment != c_species.compartment:
        return refuse("the fast reaction's species must share one compartment")
    if a_species.has_only_substance_units != c_species.has_only_substance_units:
        return refuse("the fast reaction's species must use the same quantity kind")
    for item in (a_species, c_species):
        if item.constant or item.boundary_condition:
            return refuse(f'species "{item.id}" must be mutable and non-boundary')
        if not (item.initial_amount_set or item.initial_concentration_set):
            return refuse(f'species "{item.id}" has no initial value')
        if item.conversion_factor or getattr(model, "conversion_factor", None):
            return refuse(
                "the homodimer pool lowering does not carry conversion factors"
            )
        if standardize_name(item.id) in _controlled_symbols(model):
            return refuse(f'species "{item.id}" is reassigned by a rule or event')
        if standardize_name(item.id) in _delayed_species(model):
            return refuse(f'species "{item.id}" is read by a delay expression')
    compartment = model.compartments.get(a_species.compartment or "")
    if compartment is None or not compartment.constant:
        return refuse("the fast reaction requires a constant shared compartment")
    if standardize_name(compartment.id) in _controlled_symbols(model):
        return refuse(
            f'compartment "{compartment.id}" is reassigned by a rule or event'
        )
    volume = _compartment_volume(model, a_species)
    if not math.isfinite(volume) or volume <= 0:
        return refuse("the fast reaction's compartment has no usable volume")
    if not math.isfinite(equilibrium_constant) or equilibrium_constant <= 0:
        return refuse("the fast rate has no finite positive equilibrium constant")

    amount_a = _species_amount(model, a_species)
    amount_c = _species_amount(model, c_species)
    if amount_a is None or amount_c is None or min(amount_a, amount_c) < 0:
        return refuse("the fast reaction's species have no nonnegative initial amounts")
    symbol_scale = 1.0 if a_species.has_only_substance_units else 1.0 / volume
    pool0 = (amount_a + 2.0 * amount_c) * symbol_scale
    if pool0 < 0 or not math.isfinite(pool0):
        return refuse("the initial pool has no real nonnegative fast equilibrium")

    kd = equilibrium_constant
    a0 = (-kd + math.sqrt(kd * kd + 8.0 * kd * pool0)) / 4.0
    c0 = (pool0 - a0) / 2.0
    if a0 < -1e-12 or c0 < -1e-12:
        return refuse("the initial fast equilibrium is outside the nonnegative branch")
    a0 = max(0.0, a0)
    c0 = max(0.0, c0)

    from .types import SBMLModifierSpeciesReference, SBMLParameter, SBMLRule

    pool_name = _unique_identifier(
        model, f"__fast_pool_{standardize_name(reaction.id)}"
    )
    pool_rates: List[str] = []
    participants = {monomer_id, dimer_id}
    for slow in model.reactions.values():
        if slow.id == reaction.id:
            continue
        if any(
            reference.species in participants and reference.variable_stoichiometry
            for reference in [*slow.reactants, *slow.products]
        ):
            return refuse(
                f'reaction "{slow.id}" changes a fast-equilibrium species with '
                "variable stoichiometry"
            )
        sigma_a = _signed_stoichiometry(slow, monomer_id)
        sigma_c = _signed_stoichiometry(slow, dimer_id)
        net = sigma_a + 2.0 * sigma_c
        if net:
            rate = _global_kinetic_law(slow)
            if rate is None:
                return refuse(
                    f'reaction "{slow.id}" has no usable kinetic law for homodimer pool'
                )
            pool_rates.append(f"({format_number(symbol_scale * net)}) * ({rate})")

    kd_text = format_number(kd)
    a_expr = f"((-({kd_text}) + sqrt(({kd_text})^2 + ({format_number(8.0 * kd)}) * {pool_name})) / 4)"
    c_expr = f"(({pool_name} - ({a_expr})) / 2)"
    _set_species_amount(
        model, a_species, a0 if a_species.has_only_substance_units else a0 * volume
    )
    _set_species_amount(
        model, c_species, c0 if c_species.has_only_substance_units else c0 * volume
    )
    model.parameters[pool_name] = SBMLParameter(
        id=pool_name, name=pool_name, value=pool0, constant=False, value_set=True
    )
    model.rules.extend(
        [
            SBMLRule(
                type="rate", variable=pool_name, math=" + ".join(pool_rates) or "0"
            ),
            SBMLRule(type="assignment", variable=monomer_id, math=a_expr),
            SBMLRule(type="assignment", variable=dimer_id, math=c_expr),
        ]
    )
    del model.reactions[reaction.id]
    for slow in model.reactions.values():
        moved = [
            reference
            for reference in [*slow.reactants, *slow.products]
            if reference.species in participants
        ]
        slow.reactants = [
            reference
            for reference in slow.reactants
            if reference.species not in participants
        ]
        slow.products = [
            reference
            for reference in slow.products
            if reference.species not in participants
        ]
        present = {_modifier_species(modifier) for modifier in slow.modifiers}
        for reference in moved:
            if reference.species not in present:
                slow.modifiers.append(SBMLModifierSpeciesReference(reference.species))
                present.add(reference.species)
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f"the fast homodimer equilibrium is reconstructed on the conserved "
            f"pool {pool_name}={monomer_id}+2*{dimer_id}"
        ),
    )


def _reduce_bimolecular_exchange_equilibrium(
    model: SBMLModel,
    reaction: SBMLReaction,
    reactants: Sequence[Any],
    products: Sequence[Any],
) -> FastReactionOutcome:
    """Lower A + B <-> C + D to its exact equilibrium on three conserved pools.

    With P = A + C, Q = B + C, R = A + D and equilibrium constant K = kf / kr,
    A = P - C, B = Q - C, D = R - P + C satisfy K*(P - C)*(Q - C) = C*(R - P + C),
    which solves cleanly in closed form (linear for K = 1, quadratic for K != 1).
    """

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    a_ref, b_ref = reactants
    c_ref, d_ref = products
    identifiers = (a_ref.species, b_ref.species, c_ref.species, d_ref.species)
    if len(set(identifiers)) != 4:
        return refuse(
            "the fast exchange reaction does not convert four distinct species"
        )
    if any(
        re.search(r"\bdelay\s*\(", expression, flags=re.IGNORECASE)
        for expression in _model_expressions(model)
    ):
        return refuse(
            "the bimolecular exchange projection cannot preserve delayed prehistory"
        )
    for expression in _model_expressions(model):
        names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expression))
        if reaction.id in names:
            return refuse(
                f'an expression reads the fast reaction "{reaction.id}"\'s rate'
            )
        if "rateOf" in names and names & set(identifiers):
            return refuse(
                "an expression reads the rate of change of a fast-equilibrium species"
            )
    if any(
        reference.variable_stoichiometry or float(reference.stoichiometry) != 1
        for reference in (*reactants, *products)
    ):
        return refuse(
            "the bimolecular exchange fast reaction requires unit stoichiometry"
        )
    species = [model.species.get(identifier) for identifier in identifiers]
    if any(item is None for item in species):
        return refuse("the fast reaction refers to a species the model does not define")
    a_sp, b_sp, c_sp, d_sp = species
    assert (
        a_sp is not None and b_sp is not None and c_sp is not None and d_sp is not None
    )
    if len({item.compartment for item in species}) != 1:
        return refuse("the fast reaction's species must share one compartment")
    if len({item.has_only_substance_units for item in species}) != 1:
        return refuse("the fast reaction's species must use the same quantity kind")
    for item in species:
        if item.constant or item.boundary_condition:
            return refuse(f'species "{item.id}" must be mutable and non-boundary')
        if not (item.initial_amount_set or item.initial_concentration_set):
            return refuse(f'species "{item.id}" has no initial value')
        if item.conversion_factor or getattr(model, "conversion_factor", None):
            return refuse(
                "the bimolecular exchange lowering does not carry conversion factors"
            )
        if standardize_name(item.id) in _controlled_symbols(model):
            return refuse(f'species "{item.id}" is reassigned by a rule or event')
        if standardize_name(item.id) in _delayed_species(model):
            return refuse(f'species "{item.id}" is read by a delay expression')
    compartment = model.compartments.get(a_sp.compartment or "")
    if compartment is None or not compartment.constant:
        return refuse("the fast reaction requires a constant shared compartment")
    if standardize_name(compartment.id) in _controlled_symbols(model):
        return refuse(
            f'compartment "{compartment.id}" is reassigned by a rule or event'
        )
    volume = _compartment_volume(model, a_sp)
    if not math.isfinite(volume) or volume <= 0:
        return refuse("the fast reaction's compartment has no usable volume")

    expression = _parse_expression(_kinetic_law_math(reaction))
    if expression is None:
        return refuse("the fast reaction's kinetic law is not a supported expression")
    expression = _inline_function_calls(expression, model.function_definitions)
    resolver = _ConstantResolver(model, reaction)
    terms = _rate_terms(expression, model, resolver)
    if terms is None:
        return refuse(
            "the fast rate must be a two-term constant-coefficient mass action law"
        )
    terms = [term for term in terms if term.coefficient]
    reactant_sig = tuple(sorted(((a_ref.species, 1), (b_ref.species, 1))))
    product_sig = tuple(sorted(((c_ref.species, 1), (d_ref.species, 1))))
    r_term = next((term for term in terms if term.species == reactant_sig), None)
    p_term = next((term for term in terms if term.species == product_sig), None)
    if (
        len(terms) != 2
        or r_term is None
        or p_term is None
        or r_term.coefficient <= 0
        or p_term.coefficient >= 0
    ):
        return refuse("the fast rate must be positive kf*A*B minus positive kr*C*D")
    k_eq = r_term.coefficient / (-p_term.coefficient)
    if not math.isfinite(k_eq) or k_eq <= 0:
        return refuse("the fast rate has no finite positive equilibrium constant")

    initial = [_species_amount(model, item) for item in species]
    if any(value is None for value in initial):
        return refuse("the fast reaction's species have no usable initial amounts")
    amt_a, amt_b, amt_c, amt_d = (float(value) for value in initial)
    if min(amt_a, amt_b, amt_c, amt_d) < 0:
        return refuse("the fast reaction's species have a negative initial amount")
    symbol_scale = 1.0 if a_sp.has_only_substance_units else 1.0 / volume
    p0 = (amt_a + amt_c) * symbol_scale
    q0 = (amt_b + amt_c) * symbol_scale
    r0 = (amt_a + amt_d) * symbol_scale

    if abs(k_eq - 1.0) <= 1e-12:
        if q0 + r0 <= 0:
            return refuse("the initial exchange pools sum to zero at K=1")
        c0 = (p0 * q0) / (q0 + r0)
    else:
        quad_a = k_eq - 1.0
        quad_b = k_eq * (p0 + q0) + (r0 - p0)
        disc = quad_b * quad_b - 4.0 * quad_a * k_eq * p0 * q0
        if disc < -1e-12:
            return refuse("the initial pools have no real fast exchange equilibrium")
        c0 = (quad_b - math.sqrt(max(0.0, disc))) / (2.0 * quad_a)
    a0, b0, d0 = p0 - c0, q0 - c0, r0 - p0 + c0
    if min(a0, b0, c0, d0) < -1e-10:
        return refuse(
            "the initial fast exchange equilibrium is outside the nonnegative branch"
        )
    a0, b0, c0, d0 = max(0.0, a0), max(0.0, b0), max(0.0, c0), max(0.0, d0)

    from .types import SBMLModifierSpeciesReference, SBMLParameter, SBMLRule

    std_rxn = standardize_name(reaction.id)
    pool_p = _unique_identifier(model, f"__fast_pool_p_{std_rxn}")
    pool_q = _unique_identifier(model, f"__fast_pool_q_{std_rxn}")
    pool_r = _unique_identifier(model, f"__fast_pool_r_{std_rxn}")
    rate_p: List[str] = []
    rate_q: List[str] = []
    rate_r: List[str] = []
    participants = set(identifiers)
    for slow in model.reactions.values():
        if slow.id == reaction.id:
            continue
        if any(
            reference.species in participants and reference.variable_stoichiometry
            for reference in [*slow.reactants, *slow.products]
        ):
            return refuse(
                f'reaction "{slow.id}" changes a fast-equilibrium species with '
                "variable stoichiometry"
            )
        sa = _signed_stoichiometry(slow, a_sp.id)
        sb = _signed_stoichiometry(slow, b_sp.id)
        sc = _signed_stoichiometry(slow, c_sp.id)
        sd = _signed_stoichiometry(slow, d_sp.id)
        if sa + sc or sb + sc or sa + sd:
            rate = _global_kinetic_law(slow)
            if rate is None:
                return refuse(
                    f'reaction "{slow.id}" has no usable kinetic law for exchange pools'
                )
            if sa + sc:
                rate_p.append(f"({format_number(symbol_scale * (sa + sc))}) * ({rate})")
            if sb + sc:
                rate_q.append(f"({format_number(symbol_scale * (sb + sc))}) * ({rate})")
            if sa + sd:
                rate_r.append(f"({format_number(symbol_scale * (sa + sd))}) * ({rate})")

    if abs(k_eq - 1.0) <= 1e-12:
        c_expr = f"(({pool_p} * {pool_q}) / ({pool_q} + {pool_r}))"
    else:
        quad_a = k_eq - 1.0
        k_text = format_number(k_eq)
        b_expr = f"({k_text} * ({pool_p} + {pool_q}) + ({pool_r} - {pool_p}))"
        c_expr = (
            f"(({b_expr} - sqrt(({b_expr})^2 - "
            f"({format_number(4.0 * quad_a * k_eq)}) * {pool_p} * {pool_q})) "
            f"/ ({format_number(2.0 * quad_a)}))"
        )
    reconstructed = {
        a_sp.id: f"{pool_p} - {c_expr}",
        b_sp.id: f"{pool_q} - {c_expr}",
        c_sp.id: c_expr,
        d_sp.id: f"{pool_r} - {pool_p} + {c_expr}",
    }
    for item, val in zip(species, (a0, b0, c0, d0)):
        _set_species_amount(
            model, item, val if item.has_only_substance_units else val * volume
        )
    for name, initial_value in ((pool_p, p0), (pool_q, q0), (pool_r, r0)):
        model.parameters[name] = SBMLParameter(
            id=name, name=name, value=initial_value, constant=False, value_set=True
        )
    model.rules.extend(
        [
            SBMLRule(type="rate", variable=pool_p, math=" + ".join(rate_p) or "0"),
            SBMLRule(type="rate", variable=pool_q, math=" + ".join(rate_q) or "0"),
            SBMLRule(type="rate", variable=pool_r, math=" + ".join(rate_r) or "0"),
            *[
                SBMLRule(
                    type="assignment", variable=item.id, math=reconstructed[item.id]
                )
                for item in species
            ],
        ]
    )
    del model.reactions[reaction.id]
    for slow in model.reactions.values():
        moved = [
            reference
            for reference in [*slow.reactants, *slow.products]
            if reference.species in participants
        ]
        slow.reactants = [
            reference
            for reference in slow.reactants
            if reference.species not in participants
        ]
        slow.products = [
            reference
            for reference in slow.products
            if reference.species not in participants
        ]
        present = {_modifier_species(modifier) for modifier in slow.modifiers}
        for reference in moved:
            if reference.species not in present:
                slow.modifiers.append(SBMLModifierSpeciesReference(reference.species))
                present.add(reference.species)
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f"the fast bimolecular exchange equilibrium is reconstructed on the "
            f"conserved pools {pool_p}={a_sp.id}+{c_sp.id}, "
            f"{pool_q}={b_sp.id}+{c_sp.id}, {pool_r}={a_sp.id}+{d_sp.id}"
        ),
    )


def _solve_linear_system(
    matrix: List[List[float]], rhs: List[float]
) -> Optional[List[float]]:
    """Solve an n x n linear system with partial pivoting; return None if singular."""

    n = len(rhs)
    aug = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) <= 1e-14:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        diag = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= diag
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                aug[r][j] -= factor * aug[col][j]
    solution = [aug[i][n] for i in range(n)]
    return solution if all(math.isfinite(val) for val in solution) else None


def _reduce_coupled_linear_fast_component(
    model: SBMLModel, component: Sequence[SBMLReaction]
) -> Optional[Dict[str, FastReactionOutcome]]:
    """Reduce a connected component of reversible unit-stoichiometry linear fast reactions.

    Each reaction S_i <-> S_j must have mass-action rate kf*S_i - kr*S_j with
    constant positive kf, kr.  The resulting irreducible Markov generator Q has
    a unique strictly positive stationary distribution pi (Q*pi = 0, sum(pi) = 1),
    so the entire fast subsystem reduces to one conserved pool T = sum(S_k) and
    exact equilibrium assignments S_k = pi_k * T.
    """

    species_ids: List[str] = []
    seen_species: set[str] = set()
    rxn_ids = {rxn.id for rxn in component}
    for rxn in component:
        if rxn.multi_intra_species:
            return None
        reactants = [
            ref for ref in rxn.reactants if ref.species and ref.species != "EmptySet"
        ]
        products = [
            ref for ref in rxn.products if ref.species and ref.species != "EmptySet"
        ]
        if len(reactants) != 1 or len(products) != 1:
            return None
        r_ref, p_ref = reactants[0], products[0]
        if (
            r_ref.species == p_ref.species
            or r_ref.variable_stoichiometry
            or p_ref.variable_stoichiometry
            or float(r_ref.stoichiometry) != 1.0
            or float(p_ref.stoichiometry) != 1.0
        ):
            return None
        for sid in (r_ref.species, p_ref.species):
            if sid not in seen_species:
                seen_species.add(sid)
                species_ids.append(sid)
    n = len(species_ids)
    if n < 3:
        return None
    if any(
        re.search(r"\bdelay\s*\(", expression, flags=re.IGNORECASE)
        for expression in _model_expressions(model)
    ):
        return None
    for expression in _model_expressions(model):
        names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expression))
        if names & rxn_ids:
            return None
        if "rateOf" in names and names & seen_species:
            return None

    species_objs = [model.species.get(sid) for sid in species_ids]
    if any(item is None for item in species_objs):
        return None
    typed_species = [item for item in species_objs if item is not None]
    if len({item.compartment for item in typed_species}) != 1:
        return None
    if len({item.has_only_substance_units for item in typed_species}) != 1:
        return None
    controlled = _controlled_symbols(model)
    delayed = _delayed_species(model)
    for item in typed_species:
        if item.constant or item.boundary_condition:
            return None
        if not (item.initial_amount_set or item.initial_concentration_set):
            return None
        if item.conversion_factor or getattr(model, "conversion_factor", None):
            return None
        if (
            standardize_name(item.id) in controlled
            or standardize_name(item.id) in delayed
        ):
            return None
    compartment = model.compartments.get(typed_species[0].compartment or "")
    if compartment is None or not compartment.constant:
        return None
    if standardize_name(compartment.id) in controlled:
        return None
    volume = _compartment_volume(model, typed_species[0])
    if not math.isfinite(volume) or volume <= 0:
        return None

    index_of = {sid: idx for idx, sid in enumerate(species_ids)}
    generator = [[0.0] * n for _ in range(n)]
    for rxn in component:
        r_sid = next(ref.species for ref in rxn.reactants if ref.species != "EmptySet")
        p_sid = next(ref.species for ref in rxn.products if ref.species != "EmptySet")
        expr = _parse_expression(_kinetic_law_math(rxn))
        if expr is None:
            return None
        expr = _inline_function_calls(expr, model.function_definitions)
        resolver = _ConstantResolver(model, rxn)
        terms = _rate_terms(expr, model, resolver)
        if terms is None:
            return None
        active = [term for term in terms if term.coefficient != 0.0]
        if len(active) != 2:
            return None
        r_term = next((t for t in active if t.species == ((r_sid, 1),)), None)
        p_term = next((t for t in active if t.species == ((p_sid, 1),)), None)
        if (
            r_term is None
            or p_term is None
            or r_term.coefficient <= 0.0
            or p_term.coefficient >= 0.0
        ):
            return None
        kf = float(r_term.coefficient)
        kr = float(-p_term.coefficient)
        if not (math.isfinite(kf) and math.isfinite(kr) and kf > 0.0 and kr > 0.0):
            return None
        ri, pi_idx = index_of[r_sid], index_of[p_sid]
        generator[ri][ri] -= kf
        generator[pi_idx][ri] += kf
        generator[pi_idx][pi_idx] -= kr
        generator[ri][pi_idx] += kr

    # Solve Q * pi = 0 with sum(pi) = 1.
    system = [list(generator[i]) for i in range(n - 1)] + [[1.0] * n]
    rhs = [0.0] * (n - 1) + [1.0]
    pi = _solve_linear_system(system, rhs)
    if pi is None or any(val <= 1e-12 for val in pi):
        return None
    # Verify all rows of Q * pi = 0.
    q_norm = max(1.0, max(abs(x) for row in generator for x in row))
    for row in generator:
        residual = sum(row[j] * pi[j] for j in range(n))
        if abs(residual) > 1e-10 * q_norm:
            return None

    initial_amounts = [_species_amount(model, item) for item in typed_species]
    if any(val is None or val < 0 for val in initial_amounts):
        return None
    symbol_scale = 1.0 if typed_species[0].has_only_substance_units else 1.0 / volume
    pool0 = sum(float(val) for val in initial_amounts if val is not None) * symbol_scale
    if pool0 < 0 or not math.isfinite(pool0):
        return None

    from .types import SBMLModifierSpeciesReference, SBMLParameter, SBMLRule

    pool_name = _unique_identifier(
        model, f"__fast_pool_{standardize_name(component[0].id)}"
    )
    pool_rates: List[str] = []
    for slow in model.reactions.values():
        if slow.id in rxn_ids:
            continue
        if any(
            reference.species in seen_species and reference.variable_stoichiometry
            for reference in [*slow.reactants, *slow.products]
        ):
            return None
        net = sum(_signed_stoichiometry(slow, sid) for sid in species_ids)
        if net:
            rate = _global_kinetic_law(slow)
            if rate is None:
                return None
            pool_rates.append(f"({format_number(symbol_scale * net)}) * ({rate})")

    for item, weight in zip(typed_species, pi):
        val = weight * pool0
        _set_species_amount(
            model, item, val if item.has_only_substance_units else val * volume
        )
    model.parameters[pool_name] = SBMLParameter(
        id=pool_name, name=pool_name, value=pool0, constant=False, value_set=True
    )
    model.rules.append(
        SBMLRule(type="rate", variable=pool_name, math=" + ".join(pool_rates) or "0")
    )
    for item, weight in zip(typed_species, pi):
        model.rules.append(
            SBMLRule(
                type="assignment",
                variable=item.id,
                math=f"({format_number(weight)}) * {pool_name}",
            )
        )
    for rxn in component:
        del model.reactions[rxn.id]
    for slow in model.reactions.values():
        moved = [
            reference
            for reference in [*slow.reactants, *slow.products]
            if reference.species in seen_species
        ]
        slow.reactants = [
            reference
            for reference in slow.reactants
            if reference.species not in seen_species
        ]
        slow.products = [
            reference
            for reference in slow.products
            if reference.species not in seen_species
        ]
        present = {_modifier_species(modifier) for modifier in slow.modifiers}
        for reference in moved:
            if reference.species not in present:
                slow.modifiers.append(SBMLModifierSpeciesReference(reference.species))
                present.add(reference.species)
    detail = (
        f"the coupled linear fast subsystem is reconstructed on the conserved "
        f"pool {pool_name}={'+'.join(species_ids)}"
    )
    return {
        rxn.id: FastReactionOutcome(rxn.id, True, detail=detail) for rxn in component
    }


def _zero_switch_coefficient(
    model: SBMLModel,
    term: _SymbolicTerm,
    analysis: Any,
    reactant_id: str,
    reactant_species: SBMLSpecies,
) -> Optional[str]:
    """Identify a rate constant that switches from zero to positive by events."""
    if set(term.species) != {(reactant_id, 1)}:
        return None
    if _term_sign(term, analysis) != "0+":
        return None
    if _species_amount(model, reactant_species) != 0.0:
        return None
    names = {
        node.id
        for factor in term.factors
        for node in ast.walk(ast.parse(ast.unparse(factor), mode="eval"))
        if isinstance(node, ast.Name)
    }
    candidates = []
    for name in names:
        key = standardize_name(name)
        if key in analysis._rate_rules or key in analysis._assignment_rules:
            return None
        values = analysis._event_values.get(key)
        if not values:
            return None
        numbers = [_fast_number(value) for value in values]
        if any(value is None for value in numbers):
            return None
        if any(value < 0 for value in numbers) or not any(
            value > 0 for value in numbers
        ):
            return None
        if 0.0 not in numbers:
            return None
        candidates.append(name)
    return candidates[0] if len(candidates) == 1 else None


def _reduce_zero_switch(
    model: SBMLModel,
    reaction: SBMLReaction,
    reactant: Any,
    product: Any,
    coefficient: str,
) -> FastReactionOutcome:
    """Lower a fast reaction that is inactive until its rate constant turns on.

    While the coefficient is zero the fast reaction carries no flux and the
    converted species follows the slow reactions. Once it is positive the fast
    reaction holds the reactant at zero and the conserved pool puts the added
    amount entirely into the product. An event that turns the coefficient on
    transfers the reactant's amount at that instant.
    """
    reactant_id, product_id = reactant.species, product.species
    reactant_species = model.species.get(reactant_id)
    product_species = model.species.get(product_id)
    if reactant_species is None or product_species is None:
        return FastReactionOutcome(reaction.id, False, reason="undefined fast species")
    if reactant_species.has_only_substance_units is not True:
        return FastReactionOutcome(
            reaction.id, False, reason="the zero-switch reduction needs substance units"
        )
    for species in (reactant_species, product_species):
        if species.compartment != reactant_species.compartment:
            return FastReactionOutcome(
                reaction.id,
                False,
                reason="the fast species are in different compartments",
            )
    amount_r = _species_amount(model, reactant_species)
    amount_p = _species_amount(model, product_species)
    if amount_r is None or amount_p is None:
        return FastReactionOutcome(
            reaction.id, False, reason="no usable initial amount"
        )
    pool = amount_r + amount_p
    numerator_r = abs(float(reactant.stoichiometry))
    numerator_p = abs(float(product.stoichiometry))
    if numerator_r <= 0 or numerator_p <= 0:
        return FastReactionOutcome(reaction.id, False, reason="invalid stoichiometry")

    slow = 0.0
    for other in model.reactions.values():
        if other.id == reaction.id or other.fast:
            continue
        sigma = _signed_stoichiometry(other, reactant_id)
        if sigma == 0:
            continue
        law = _global_kinetic_law(other)
        if law is None:
            return FastReactionOutcome(
                reaction.id, False, reason="a slow reaction has no reducible rate"
            )
        constant = _constant_value(law, _ConstantResolver(model, other))
        if constant is None:
            return FastReactionOutcome(
                reaction.id, False, reason="a slow reaction rate is not constant"
            )
        slow += sigma * constant

    from .types import SBMLRule

    reduced_state = pool / numerator_p
    # Before the fast coefficient turns on, the source trajectory of the held
    # species is affine. Record it so the event lowering can prove the first
    # trigger crossing on the exact source dynamics.
    model.event_affine_source_trajectory = {reactant_id: (0.0, slow)}
    _set_species_amount(model, reactant_species, 0.0)
    _set_species_amount(model, product_species, reduced_state)
    model.rules.append(
        SBMLRule(
            type="rate",
            variable=reactant_id,
            math=f"if(gt({coefficient}, 0), 0, {format_number(slow)})",
        )
    )
    model.rules.append(
        SBMLRule(
            type="assignment",
            variable=product_id,
            math=(
                f"(({format_number(pool)}) - "
                f"({_amount_symbol(reactant_species, 1.0)})) * "
                f"{format_number(numerator_r / numerator_p)}"
            ),
        )
    )
    transferred = False
    for event in model.events:
        for assignment in event.assignments:
            variable = getattr(assignment, "variable", None)
            expression = getattr(assignment, "math", "")
            if variable is None or standardize_name(str(variable)) != standardize_name(
                coefficient
            ):
                continue
            value = _fast_number(expression)
            if value is None or value <= 0:
                continue
            from .types import SBMLEventAssignment

            event.assignments.append(
                SBMLEventAssignment(variable=reactant_id, math="0")
            )
            transferred = True
    if not transferred:
        return FastReactionOutcome(
            reaction.id, False, reason="no event turns the fast coefficient on"
        )
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f'the fast reaction is inactive while "{coefficient}" is zero; '
            f'"{reactant_id}" is held at zero when it turns on and the pool '
            f"is conserved"
        ),
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
        if standardize_name(identifier) in delayed and not _delay_is_rewritable(
            model, identifier
        ):
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
    reduced_produced = (
        produced_amount + produced_factor * produced_stoichiometry * extent
    )
    _set_species_amount(model, consumed_species, 0.0)
    _set_species_amount(model, produced_species, reduced_produced)
    _rewrite_fast_reduction_delays(
        model,
        {consumed: consumed_amount, produced: produced_amount},
        _compartment_volume(model, consumed_species),
        {consumed: "0", produced: format_number(reduced_produced)},
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
        # Check exact homodimerization 2A <-> C (kf*A^2 - kr*C) or C <-> 2A (kf*C - kr*A^2).
        if (
            pinned_id == reactant.species
            and other_id == product.species
            and reactant_stoichiometry == 2.0
            and product_stoichiometry == 1.0
            and forward.species[0][1] == 2
            and backward.species[0][1] == 1
        ):
            return _reduce_homodimer_equilibrium(
                model,
                reaction,
                monomer_id=reactant.species,
                dimer_id=product.species,
                equilibrium_constant=(-backward.coefficient) / forward.coefficient,
            )
        if (
            pinned_id == reactant.species
            and other_id == product.species
            and reactant_stoichiometry == 1.0
            and product_stoichiometry == 2.0
            and forward.species[0][1] == 1
            and backward.species[0][1] == 2
        ):
            return _reduce_homodimer_equilibrium(
                model,
                reaction,
                monomer_id=product.species,
                dimer_id=reactant.species,
                equilibrium_constant=forward.coefficient / (-backward.coefficient),
            )
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
        # The law becomes part of a global rate rule, so its local
        # parameters are replaced by their values.
        rate = _global_kinetic_law(other)
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
        if any(
            rule.type == "assignment"
            and rule.variable
            and standardize_name(str(rule.variable)) == key
            for rule in model.rules
        ):
            # An assignment rule holds the parameter's value for the whole
            # run, so a rule this resolver cannot fold to a constant makes the
            # parameter time-dependent; its declared value is not its value.
            return None
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
            argument: clone_ast(actual)
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
        return clone_ast(replacement)


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


# ---------------------------------------------------------------------------
# Reduction through the fast subsystem's conserved pool
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SymbolicTerm:
    """One additive term of a rate law whose coefficient may change in time.

    ``factors`` are the term's species-free factors that are not constants,
    kept as parsed expressions; ``coefficient`` is the constant part.
    """

    species: Tuple[Tuple[str, int], ...]
    coefficient: float
    factors: Tuple[ast.AST, ...] = ()

    @property
    def species_ids(self) -> Tuple[str, ...]:
        return tuple(identifier for identifier, _ in self.species)


def _infix(node: ast.AST) -> str:
    """Render a parsed expression back in the parser's infix dialect."""

    text = ast.unparse(node)
    text = text.replace("**", "^")
    return re.sub(r"\bbng_(if|and|or|not)\(", r"\1(", text)


def _fast_number(text: object) -> Optional[float]:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


_DELAY_CALL = re.compile(r"\bdelay\s*\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*,\s*([^()]+)\)")


def _delay_is_rewritable(model: SBMLModel, species_id: str) -> bool:
    """True when every delayed read of a fast species has a constant history.

    The fast reduction changes a species' amount instantly at t=0. A delayed
    read before the delay elapses must then report the source's original
    value, not the reduced steady state. That history is exact when the read
    lives in an assignment rule with a constant delay and a target outside
    the fast subsystem, so it can be replaced by a time piecewise.
    """
    found = False
    for rule in model.rules:
        if rule.type != "assignment" or not rule.variable:
            continue
        standardized_target = standardize_name(str(rule.variable))
        if standardized_target in {standardize_name(name) for name in model.species}:
            continue
        for match in _DELAY_CALL.finditer(str(rule.math or "")):
            if standardize_name(match.group(1)) != standardize_name(species_id):
                continue
            if _fast_number(match.group(2)) is None:
                return False
            found = True
    # Any delayed read outside such a rule still needs the live history.
    for expression in _model_expressions(model):
        for match in _DELAY_CALL.finditer(expression):
            if standardize_name(match.group(1)) != standardize_name(species_id):
                continue
            if not any(
                rule.type == "assignment"
                and str(rule.math or "") == expression
                and rule.variable
                and standardize_name(str(rule.variable))
                not in {standardize_name(name) for name in model.species}
                for rule in model.rules
            ):
                return False
    return found


def _event_stoichiometry_transfer(
    model: SBMLModel,
    held_id: str,
    state_id: str,
    stoich_id: str,
    volume: float,
) -> bool:
    """Re-express event writes to the held fast species as pool-state writes.

    When an event changes the fast reaction's stoichiometry and simultaneously
    adds some of the species the reduction holds at zero, that amount joins
    the non-held species scaled by the new stoichiometry. The pool's state is
    the non-held species, so the event is rewritten to add the source amount
    divided by the new stoichiometry to that state. Returns False unless every
    event that writes the held species also writes a constant stoichiometry.
    """
    changed = False
    for event in model.events:
        variables = [
            standardize_name(str(getattr(assignment, "variable", "") or ""))
            for assignment in event.assignments
        ]
        if standardize_name(held_id) not in variables:
            continue
        held_values = [
            str(getattr(assignment, "math", "") or "")
            for assignment in event.assignments
            if standardize_name(str(getattr(assignment, "variable", "") or ""))
            == standardize_name(held_id)
        ]
        stoich_values = [
            str(getattr(assignment, "math", "") or "")
            for assignment in event.assignments
            if standardize_name(str(getattr(assignment, "variable", "") or ""))
            == standardize_name(stoich_id)
        ]
        if len(held_values) != 1 or len(stoich_values) != 1:
            return False
        added = _fast_number(held_values[0])
        new_stoich = _fast_number(stoich_values[0])
        if added is None or new_stoich is None or new_stoich <= 0:
            return False
        increment = added / (new_stoich * volume)
        replaced = False
        for assignment in event.assignments:
            if not replaced and standardize_name(
                str(getattr(assignment, "variable", "") or "")
            ) == standardize_name(held_id):
                assignment.variable = state_id
                assignment.math = f"(({state_id}) + {format_number(increment)})"
                replaced = True
        changed = True
    return changed


def _rewrite_fast_reduction_delays(
    model: SBMLModel,
    original_amounts: Mapping[str, float],
    volume: float,
    reduced_expressions: Optional[Mapping[str, str]] = None,
) -> None:
    """Keep the source's pre-reduction history for delayed reads."""

    for rule in model.rules:
        if rule.type != "assignment" or not rule.variable:
            continue
        text = str(rule.math or "")

        def replace(match: "re.Match[str]") -> str:
            species_id = match.group(1)
            if species_id not in original_amounts:
                return match.group(0)
            delay = _fast_number(match.group(2))
            if delay is None or delay < 0:
                return match.group(0)
            reduced = (reduced_expressions or {}).get(species_id)
            if reduced is None:
                reduced = next(
                    (
                        str(other.math or "")
                        for other in model.rules
                        if other.type == "assignment"
                        and other.variable
                        and standardize_name(str(other.variable))
                        == standardize_name(species_id)
                    ),
                    None,
                )
            if not reduced:
                return match.group(0)
            species = model.species.get(species_id)
            original = original_amounts[species_id]
            if species is not None and not species.has_only_substance_units:
                original = original / volume
            return (
                f"if(time() <= {format_number(delay)}, "
                f"{format_number(original)}, ({reduced}))"
            )

        rule.math = _DELAY_CALL.sub(replace, text)


def _reduce_with_pool(
    model: SBMLModel,
    reaction: SBMLReaction,
    reactant: Any,
    product: Any,
) -> FastReactionOutcome:
    """Reduce a fast reaction whose steady state moves during the run.

    With ``nu_R`` and ``nu_P`` the reaction's stoichiometries and ``n`` the
    species amounts, the fast reaction leaves the pool ``T = nu_P * n_R +
    nu_R * n_P`` unchanged, so only the slow reactions change it::

        dT/dt = sum_j (nu_P * sigma_Rj + nu_R * sigma_Pj) * v_j

    and the steady state fixes the two amounts as functions of ``T``:

    * a rate ``c * x_R^a * x_P^b`` (``a, b >= 1``) vanishes when either
      species is zero; it holds the reactant at zero while ``c > 0`` and the
      product at zero while ``c < 0``, so ``n_R = [c <= 0] T / nu_P`` and
      ``n_P = [c > 0] T / nu_R``.  A rate of one species only (``b = 0`` or
      ``a = 0``) has a steady state only while ``c`` keeps the sign that runs
      the reaction away from that species, so its sign must be provable.
    * a rate ``a * x_R - b * x_P`` with ``a, b > 0`` is zero on the balance
      ``a n_R = b n_P``: ``n_R = b T / (nu_P b + nu_R a)`` and
      ``n_P = a T / (nu_P b + nu_R a)``.

    ``c``, ``a`` and ``b`` may be any expression of constants, time and
    parameters whose values do not depend on the species (an event, an
    assignment rule or a rate rule may set them); ``T`` is then the state and
    the two amounts are its functions, so a change of a rate constant moves
    the steady state at once.  The switching shape assumes ``c`` is zero only
    at isolated instants; a model where an event sets it to zero is refused.
    It takes the stable root at every instant, so the held species changes
    as soon as ``c`` changes sign.  That is the algebraic condition SBML
    defines; a large but finite fast rate can stay on the unstable root for
    a while when the held species has no source, so it is not the limit of
    such a simulation in that case.

    When an event changes a stoichiometry instead, the amounts do not jump,
    but ``T`` does.  The rate constants must then be constant, and one of
    the two species keeps its amount as the state: the species that is not
    held at zero, or the reactant of a balance, whose partner is
    ``(a / b) n_R``.  Both moving at once would need an event assignment
    computed from the state, which is refused.
    """

    def refuse(reason: str) -> FastReactionOutcome:
        return FastReactionOutcome(reaction.id, False, reason=reason)

    reactant_id, product_id = reactant.species, product.species
    reactant_species = model.species.get(reactant_id)
    product_species = model.species.get(product_id)
    if reactant_species is None or product_species is None:
        return refuse("the fast reaction refers to a species the model does not define")
    if reactant_id == product_id:
        return refuse("the fast reaction converts a species into itself")
    for modifier in reaction.modifiers:
        name = _modifier_species(modifier)
        if name in {reactant_id, product_id}:
            return refuse(
                f'species "{name}" is a modifier of the fast reaction, so the '
                "reaction does not change it"
            )
    if reactant_species.compartment != product_species.compartment:
        return refuse(
            "the fast reaction's two species are in different compartments, "
            "so their pool is not a single amount"
        )
    if (
        reactant_species.has_only_substance_units
        != product_species.has_only_substance_units
    ):
        return refuse(
            "the fast reaction's two species do not carry the same kind of "
            "quantity, so their steady state is not a single algebraic condition"
        )
    controlled = _controlled_symbols(model)
    delayed = _delayed_species(model)
    for species in (reactant_species, product_species):
        if species.constant:
            return refuse(f'species "{species.id}" is constant')
        if species.boundary_condition:
            return refuse(f'species "{species.id}" is a boundary species')
        if species.conversion_factor or getattr(model, "conversion_factor", None):
            return refuse(
                f'species "{species.id}" has a conversion factor, which the '
                "pooled reduction does not carry"
            )
        if not (species.initial_amount_set or species.initial_concentration_set):
            return refuse(f'species "{species.id}" has no initial value')
        if standardize_name(species.id) in delayed and not _delay_is_rewritable(
            model, species.id
        ):
            return refuse(
                f'species "{species.id}" is read by a delay expression, whose '
                "value before the delay elapses is the species' declared "
                "initial value"
            )
    compartment = model.compartments.get(reactant_species.compartment or "")
    if compartment is not None:
        if not compartment.constant:
            return refuse(f'compartment "{compartment.id}" is not constant')
        if standardize_name(compartment.id) in controlled:
            return refuse(
                f'compartment "{compartment.id}" is reassigned by a rule, an '
                "initial assignment, or an event"
            )
    volume = _compartment_volume(model, reactant_species)
    if not math.isfinite(volume) or volume <= 0:
        return refuse("the fast reaction's compartment has no usable volume")

    # The stoichiometries: a positive constant, or a species reference that
    # only events change.
    stoichiometries: Dict[str, Tuple[str, float]] = {}
    stoichiometry_ids: Dict[str, str] = {}
    for role, reference in (("reactant", reactant), ("product", product)):
        value = float(reference.stoichiometry)
        if not math.isfinite(value) or value <= 0:
            return refuse("the fast reaction's stoichiometry is not a positive value")
        if not reference.variable_stoichiometry:
            stoichiometries[role] = (format_number(value), value)
            continue
        identifier = str(reference.id or "")
        problem = _event_only_stoichiometry(model, reference)
        if problem:
            return refuse(problem)
        stoichiometries[role] = (identifier, value)
        stoichiometry_ids[role] = identifier
    nu_r_text, nu_r_value = stoichiometries["reactant"]
    nu_p_text, nu_p_value = stoichiometries["product"]

    # Nothing else may read the fast reaction's own rate or the species'
    # rates of change: the steady state does not define them.
    for expression in _model_expressions(model):
        names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expression))
        if reaction.id in names:
            return refuse(
                f'an expression reads the fast reaction "{reaction.id}"\'s rate, '
                "which its steady state does not define"
            )
        if "rateOf" in names and names & {reactant_id, product_id}:
            return refuse(
                "an expression reads the rate of change of a species the fast "
                "reaction converts"
            )

    rate = _kinetic_law_math(reaction)
    expression = _parse_expression(rate) if rate.strip() else None
    if expression is None:
        return refuse("the fast reaction's kinetic law is not a supported expression")
    expression = _inline_function_calls(expression, model.function_definitions)
    # A local parameter is scoped to this kinetic law, so its value replaces
    # it before the coefficients become global rules.
    local = {
        str(parameter.id): ast.Constant(value=float(getattr(parameter, "value", 0.0)))
        for parameter in list(
            getattr(reaction.kinetic_law, "local_parameters", []) or []
        )
    }
    if local:
        expression = _Substituter(local).visit(expression)
    resolver = _ConstantResolver(model, reaction)
    analysis = _SymbolAnalysis(model, reaction, resolver, {reactant_id, product_id})
    terms = _symbolic_terms(expression.body, resolver, analysis)
    piecewise_plan = None
    if terms is None:
        piecewise_plan = _piecewise_switch_plan(
            expression.body, reactant_id, product_id, resolver, analysis
        )
        if piecewise_plan is None:
            return refuse(
                "the fast reaction's kinetic law is not a sum of species products "
                "with coefficients that do not depend on the species"
            )
    participants = {reactant_id, product_id}
    if piecewise_plan is not None:
        active = []
        plan = piecewise_plan
        varying = True
    else:
        assert terms is not None
        active = [term for term in terms if term.coefficient != 0.0]
        if len(active) == 1:
            zero_switch = _zero_switch_coefficient(
                model, active[0], analysis, reactant_id, reactant_species
            )
            if zero_switch is not None:
                return _reduce_zero_switch(
                    model, reaction, reactant, product, zero_switch
                )
        for term in active:
            if not set(term.species_ids) <= participants:
                return refuse(
                    "the fast reaction's rate depends on a species it does not convert"
                )

        if not active:
            return FastReactionOutcome(
                reaction.id,
                True,
                detail=(
                    "its kinetic law is zero for every state, so the reaction "
                    "never carries a flux and is removed"
                ),
            )
        if len(active) == 1:
            sourced = {
                identifier
                for other in model.reactions.values()
                if other.id != reaction.id
                for identifier in (reactant_id, product_id)
                if _signed_stoichiometry(other, identifier) > 0
            }
            plan = _completion_plan(
                active[0], reactant_id, product_id, analysis, sourced, model=model
            )
        elif len(active) == 2:
            plan = _balance_plan(active, reactant_id, product_id, analysis)
        else:
            return refuse(
                "the fast reaction's rate is a sum of more than two terms, so its "
                "pseudo steady state is a multi-term balance that needs an "
                "algebraic solve in the simulation engine"
            )
        if isinstance(plan, str):
            return refuse(plan)
        varying = any(term.factors for term in active)
    varying_reference = (
        reactant
        if reactant.variable_stoichiometry
        else product if product.variable_stoichiometry else None
    )
    stoich_id = (
        str(getattr(varying_reference, "id", "") or "") if varying_reference else ""
    )
    held_id, state_id = {
        "forward": (reactant_id, product_id),
        "backward": (product_id, reactant_id),
    }.get(plan.kind, (None, None))
    transfer_stoichiometry = False
    for species in (reactant_species, product_species):
        if standardize_name(species.id) not in controlled:
            continue
        if (
            held_id
            and stoich_id
            and standardize_name(species.id) == standardize_name(held_id)
        ):
            transfer_stoichiometry = True
            continue
        return refuse(
            f'species "{species.id}" is reassigned by a rule, an initial '
            "assignment, or an event"
        )
    if stoichiometry_ids and varying:
        return refuse(
            "an event changes the fast reaction's stoichiometry while its rate "
            "constants change during the run, so re-expressing the steady "
            "state at that event needs an assignment computed from the state, "
            "which the event lowering does not carry"
        )
    if stoichiometry_ids and plan.kind == "switch":
        return refuse(
            "an event changes the fast reaction's stoichiometry while the "
            "species it holds at zero can change, so re-expressing the steady "
            "state at that event needs an assignment computed from the state, "
            "which the event lowering does not carry"
        )

    # The slow reactions' contributions: sigma_R and sigma_P per reaction.
    slow: List[Tuple[float, float, str]] = []
    for other in model.reactions.values():
        if other.id == reaction.id:
            continue
        for identifier in (reactant_id, product_id):
            for reference in [*other.reactants, *other.products]:
                if reference.species == identifier and reference.variable_stoichiometry:
                    return refuse(
                        f'reaction "{other.id}" changes species "{identifier}" '
                        "with a stoichiometry that is not a constant"
                    )
        sigma_r = _signed_stoichiometry(other, reactant_id)
        sigma_p = _signed_stoichiometry(other, product_id)
        if sigma_r == 0 and sigma_p == 0:
            continue
        law = _global_kinetic_law(other)
        if law is None:
            return refuse(
                f'reaction "{other.id}" has no kinetic law the pooled reduction '
                "can use"
            )
        slow.append((sigma_r, sigma_p, law))

    initial_r = _species_amount(model, reactant_species)
    initial_p = _species_amount(model, product_species)
    if initial_r is None or initial_p is None:
        return refuse("the fast reaction's species have no usable initial amount")
    initial_pool = nu_p_value * initial_r + nu_r_value * initial_p

    from .types import SBMLModifierSpeciesReference, SBMLParameter, SBMLRule

    def symbol_value(species: SBMLSpecies, amount: str) -> str:
        if species.has_only_substance_units:
            return amount
        return f"({amount}) / {format_number(volume)}"

    def weighted(weight_r: str, weight_p: str) -> str:
        pieces = []
        for sigma_r, sigma_p, law in slow:
            weight = _weight_text(weight_r, sigma_r, weight_p, sigma_p)
            if weight != "0":
                pieces.append(f"({weight}) * ({law})")
        return " + ".join(pieces) if pieces else "0"

    rules: List[Any] = []
    if stoichiometry_ids:
        # Constant rate constants: the steady state's ratio does not move, and
        # the amounts do not jump when an event changes the stoichiometry,
        # so one of the two species keeps its amount as the state.
        if plan.kind == "forward":
            state_species, other_species = product_species, reactant_species
            state_rate = weighted(f"({nu_p_text}) / ({nu_r_text})", "1")
            state_amount = initial_pool / nu_r_value
            other_amount = "0"
        elif plan.kind == "backward":
            state_species, other_species = reactant_species, product_species
            state_rate = weighted("1", f"({nu_r_text}) / ({nu_p_text})")
            state_amount = initial_pool / nu_p_value
            other_amount = "0"
        else:
            # a * n_R = b * n_P, so n_P = (a / b) n_R and the pool is
            # n_R * (nu_P + nu_R * a / b).
            ratio = f"({plan.forward}) / ({plan.backward})"
            denominator = f"(({nu_p_text}) + ({nu_r_text}) * {ratio})"
            state_species, other_species = reactant_species, product_species
            state_rate = (
                f"({weighted(nu_p_text, nu_r_text)}) / {denominator}" if slow else "0"
            )
            ratio_value = plan.forward_value / plan.backward_value
            state_amount = initial_pool / (nu_p_value + nu_r_value * ratio_value)
            other_amount = f"{ratio} * {_amount_symbol(state_species, volume)}"
        _set_species_amount(model, state_species, state_amount)
        rules.append(
            SBMLRule(
                type="rate",
                variable=state_species.id,
                math=symbol_value(state_species, f"{state_rate}"),
            )
        )
        rules.append(
            SBMLRule(
                type="assignment",
                variable=other_species.id,
                math=symbol_value(other_species, other_amount),
            )
        )
        for role, identifier in stoichiometry_ids.items():
            value = nu_r_value if role == "reactant" else nu_p_value
            model.parameters[identifier] = SBMLParameter(
                id=identifier,
                name=identifier,
                value=value,
                constant=False,
                value_set=True,
            )
    else:
        # Constant stoichiometry: the pool T = nu_P n_R + nu_R n_P is the
        # state, and the two amounts are functions of T and the current rate
        # constants, so an event or a rule that moves the rate constants
        # moves the steady state at once.
        pool = _unique_identifier(model, f"__fast_pool_{standardize_name(reaction.id)}")
        amount_r, amount_p = plan.amounts(pool, nu_r_text, nu_p_text)
        model.parameters[pool] = SBMLParameter(
            id=pool,
            name=pool,
            value=initial_pool,
            constant=False,
            value_set=True,
        )
        rules.append(
            SBMLRule(type="rate", variable=pool, math=weighted(nu_p_text, nu_r_text))
        )
        rules.append(
            SBMLRule(
                type="assignment",
                variable=reactant_species.id,
                math=symbol_value(reactant_species, amount_r),
            )
        )
        rules.append(
            SBMLRule(
                type="assignment",
                variable=product_species.id,
                math=symbol_value(product_species, amount_p),
            )
        )
    model.rules.extend(rules)
    _rewrite_fast_reduction_delays(
        model,
        {reactant_id: initial_r, product_id: initial_p},
        volume,
    )
    if transfer_stoichiometry and not _event_stoichiometry_transfer(
        model, held_id, state_id, stoich_id, volume
    ):
        return refuse(
            "an event changes the stoichiometry and the held species without "
            "a constant amount it can transfer to the pool state"
        )
    # The slow reactions keep reading the two species, but the reduction's
    # rules own their values, so they become modifiers.
    for other in model.reactions.values():
        if other.id == reaction.id:
            continue
        moved = [
            reference
            for reference in [*other.reactants, *other.products]
            if reference.species in participants
        ]
        if not moved:
            continue
        other.reactants = [
            reference
            for reference in other.reactants
            if reference.species not in participants
        ]
        other.products = [
            reference
            for reference in other.products
            if reference.species not in participants
        ]
        present = {_modifier_species(modifier) for modifier in other.modifiers}
        for reference in moved:
            if reference.species not in present:
                other.modifiers.append(SBMLModifierSpeciesReference(reference.species))
                present.add(reference.species)
    return FastReactionOutcome(reaction.id, True, detail=plan.description)


def _amount_symbol(species: SBMLSpecies, volume: float) -> str:
    """Return the expression for a species' amount from its own symbol."""

    if species.has_only_substance_units:
        return species.id
    return f"({species.id} * {format_number(volume)})"


@dataclass(frozen=True)
class _SteadyStatePlan:
    """How the steady state fixes the two amounts.

    ``kind`` is ``forward`` (the reactant is held at zero), ``backward`` (the
    product is held at zero), ``switch`` (the sign of ``coefficient``
    decides) or ``balance`` (``forward * x_R = backward * x_P``).
    """

    kind: str
    description: str
    coefficient: str = ""
    forward: str = ""
    backward: str = ""
    forward_value: float = 0.0
    backward_value: float = 0.0

    def amounts(self, pool: str, nu_r: str, nu_p: str) -> Tuple[str, str]:
        if self.kind == "forward":
            return "0", f"{pool} / ({nu_r})"
        if self.kind == "backward":
            return f"{pool} / ({nu_p})", "0"
        if self.kind == "switch":
            return (
                f"if(gt({self.coefficient}, 0), 0, {pool} / ({nu_p}))",
                f"if(gt({self.coefficient}, 0), {pool} / ({nu_r}), 0)",
            )
        # a * n_R = b * n_P and T = nu_P n_R + nu_R n_P.
        denominator = f"({nu_p}) * ({self.backward}) + ({nu_r}) * ({self.forward})"
        return (
            f"({self.backward}) * {pool} / ({denominator})",
            f"({self.forward}) * {pool} / ({denominator})",
        )


def _modifier_species(modifier: Any) -> str:
    if isinstance(modifier, str):
        return modifier
    return str(getattr(modifier, "species", "") or "")


def _unique_identifier(model: SBMLModel, base: str) -> str:
    taken = (
        set(model.parameters)
        | set(model.species)
        | set(model.compartments)
        | set(model.reactions)
        | set(model.function_definitions)
    )
    taken = {standardize_name(str(name)) for name in taken}
    candidate = base
    suffix = 1
    while standardize_name(candidate) in taken:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _event_only_stoichiometry(model: SBMLModel, reference: Any) -> str:
    """Return why a variable stoichiometry is not event-only, or ``""``."""

    identifier = str(getattr(reference, "id", "") or "")
    if not identifier or str(getattr(reference, "stoichiometry_math", "") or ""):
        return "the fast reaction's stoichiometry is not a constant"
    key = standardize_name(identifier)
    for rule in model.rules:
        if rule.variable and standardize_name(str(rule.variable)) == key:
            return (
                "a rule sets the fast reaction's stoichiometry, so the fast "
                "subsystem's pool changes continuously"
            )
    for assignment in model.initial_assignments:
        if standardize_name(str(assignment.symbol or "")) == key:
            return (
                "an initial assignment sets the fast reaction's stoichiometry, "
                "which the pooled reduction does not evaluate"
            )
    if identifier in model.parameters or identifier in model.species:
        return (
            f'the fast reaction\'s stoichiometry "{identifier}" shares its '
            "identifier with another element"
        )
    return ""


def _constant_value(text: str, resolver: "_ConstantResolver") -> Optional[float]:
    expression = _parse_expression(text)
    if expression is None:
        return None
    resolver._allow_time = False
    terms = _rate_terms(expression, resolver._model, resolver)
    if terms is None or any(term.species for term in terms):
        return None
    value = math.fsum(term.coefficient for term in terms)
    return value if math.isfinite(value) else None


def _global_kinetic_law(reaction: SBMLReaction) -> Optional[str]:
    """Return a kinetic law with its local parameters replaced by their values."""

    rate = _kinetic_law_math(reaction).strip()
    if not rate:
        return None
    law = reaction.kinetic_law
    local = {
        str(parameter.id): float(getattr(parameter, "value", 0.0))
        for parameter in list(getattr(law, "local_parameters", []) or [])
    }
    if not local:
        return rate
    expression = _parse_expression(rate)
    if expression is None:
        return None
    mapping = {name: ast.Constant(value=value) for name, value in local.items()}
    return _infix(_Substituter(mapping).visit(expression.body))


def _weight_text(nu_p: str, sigma_r: float, nu_r: str, sigma_p: float) -> str:
    """Return ``nu_P * sigma_R + nu_R * sigma_P`` with constant parts folded."""

    try:
        return format_number(float(nu_p) * sigma_r + float(nu_r) * sigma_p)
    except ValueError:
        parts = []
        if sigma_r:
            parts.append(f"{nu_p} * {format_number(sigma_r)}")
        if sigma_p:
            parts.append(f"{nu_r} * {format_number(sigma_p)}")
        return " + ".join(parts) if parts else "0"


class _SymbolAnalysis:
    """Decide which symbols a coefficient may hold and what sign they have."""

    def __init__(
        self,
        model: SBMLModel,
        reaction: SBMLReaction,
        resolver: "_ConstantResolver",
        fast_species: Sequence[str] = (),
    ) -> None:
        self._model = model
        self._resolver = resolver
        self._species = {standardize_name(str(name)) for name in model.species}
        self._fast = {standardize_name(str(name)) for name in fast_species}
        self._reactions = {standardize_name(str(name)) for name in model.reactions}
        self._assignment_rules: Dict[str, str] = {}
        self._rate_rules: set[str] = set()
        for rule in model.rules:
            if not rule.variable:
                continue
            key = standardize_name(str(rule.variable))
            if rule.type == "assignment":
                self._assignment_rules[key] = str(rule.math or "")
            elif rule.type == "rate":
                self._rate_rules.add(key)
        self._event_values: Dict[str, List[str]] = {}
        for event in model.events:
            for assignment in event.assignments:
                variable = str(getattr(assignment, "variable", "") or "")
                if variable:
                    self._event_values.setdefault(
                        standardize_name(variable), []
                    ).append(str(assignment.math or ""))
        self._local = {
            standardize_name(str(parameter.id))
            for parameter in list(
                getattr(reaction.kinetic_law, "local_parameters", []) or []
            )
        }

    def is_fast_species(self, name: str) -> bool:
        """Say whether a symbol is one of the two species the fast reaction converts."""

        return standardize_name(str(name).strip()) in self._fast

    def is_species_free(self, name: str, stack: Tuple[str, ...] = ()) -> bool:
        """Say whether a symbol's value is independent of the converted species.

        The steady state fixes the two converted species as functions of the
        pool and of the rate constants, so a rate constant may read time,
        parameters, compartments and the model's other species, but not
        the converted species themselves, a reaction's rate, or a rule that
        reads either.
        """

        text = str(name).strip()
        if text.lower() == "time":
            return True
        key = standardize_name(text)
        if key in self._fast or key in self._reactions:
            return False
        if self._resolver.value(text) is not None or key in self._local:
            return True
        if key in stack:
            return False
        if key in self._assignment_rules:
            expression = _parse_expression(self._assignment_rules[key])
            if expression is None:
                return False
            return all(
                self.is_species_free(inner, (*stack, key))
                for inner in _expression_names(expression)
                if inner not in _CALLABLE_NAMES
            )
        model = self._model
        known = (
            {standardize_name(str(item)) for item in model.parameters}
            | {standardize_name(str(item)) for item in model.compartments}
            | self._species
        )
        return key in known

    def initial_value(self, node: ast.AST) -> Optional[float]:
        """Return a factor's value at the start of the run, when it is known."""

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self.initial_value(node.operand)
            return None if inner is None else -inner
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            left, right = self.initial_value(node.left), self.initial_value(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Mult):
                return left * right
            return None if right == 0 else left / right
        if isinstance(node, ast.Name):
            value = self._resolver.value(node.id)
            if value is not None:
                return value
            key = standardize_name(node.id)
            parameter = self._model.parameters.get(node.id)
            if (
                parameter is None
                or key in self._assignment_rules
                or not getattr(parameter, "value_set", True)
                or any(
                    standardize_name(str(assignment.symbol or "")) == key
                    for assignment in self._model.initial_assignments
                )
            ):
                return None
            return float(parameter.value)
        return None

    def sign(self, node: ast.AST) -> Optional[str]:
        """Return a factor's provable sign over the run, or ``None``.

        ``"+"`` and ``"-"`` are strict; ``"0+"`` and ``"0-"`` allow zero.  A
        factor is provably signed when it is a constant, or a parameter
        whose only changes are events assigning constants; products,
        quotients and integer powers combine.
        """

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value > 0:
                return "+"
            if node.value < 0:
                return "-"
            return None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self.sign(node.operand)
            return None if inner is None else _flip_sign(inner)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            left, right = self.sign(node.left), self.sign(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Div) and right.startswith("0"):
                return None
            return _combine_signs(left, right)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            base = self.sign(node.left)
            exponent = node.right
            if (
                base is not None
                and isinstance(exponent, ast.Constant)
                and isinstance(exponent.value, (int, float))
                and float(exponent.value).is_integer()
                and exponent.value >= 1
            ):
                if int(exponent.value) % 2 == 0:
                    return "0+" if base.startswith("0") else "+"
                return base
            return None
        if isinstance(node, ast.Name):
            return self._name_sign(node.id)
        return None

    def _name_sign(self, name: str) -> Optional[str]:
        value = self._resolver.value(name)
        key = standardize_name(name)
        if value is not None:
            return "+" if value > 0 else ("-" if value < 0 else None)
        if key in self._assignment_rules or key in self._rate_rules:
            return None
        parameter = self._model.parameters.get(name)
        if parameter is None or key not in self._event_values:
            return None
        values = [float(parameter.value)]
        for text in self._event_values[key]:
            assigned = _constant_value(text, self._resolver)
            if assigned is None:
                return None
            values.append(assigned)
        if all(item > 0 for item in values):
            return "+"
        if all(item < 0 for item in values):
            return "-"
        if all(item >= 0 for item in values):
            return "0+"
        if all(item <= 0 for item in values):
            return "0-"
        return None

    def can_vanish_on_an_interval(self, factors: Sequence[ast.AST]) -> bool:
        """Say whether an event provably sets a factor to zero."""

        for factor in factors:
            for name in _expression_names(factor):
                key = standardize_name(name)
                if key in self._assignment_rules or key in self._rate_rules:
                    continue
                parameter = self._model.parameters.get(name)
                if parameter is not None and key in self._event_values:
                    if float(parameter.value) == 0.0:
                        return True
                    for text in self._event_values[key]:
                        if _constant_value(text, self._resolver) == 0.0:
                            return True
        return False


def _flip_sign(sign: str) -> str:
    return {"+": "-", "-": "+", "0+": "0-", "0-": "0+"}[sign]


def _combine_signs(left: str, right: str) -> str:
    """Return the sign of a product of two signed factors."""

    zero = left.startswith("0") or right.startswith("0")
    negative = left.endswith("-") != right.endswith("-")
    return ("0" if zero else "") + ("-" if negative else "+")


_CALLABLE_NAMES = {"bng_if", "bng_and", "bng_or", "bng_not"}


def _symbolic_terms(
    node: ast.AST, resolver: "_ConstantResolver", analysis: _SymbolAnalysis
) -> Optional[List[_SymbolicTerm]]:
    """Split a rate law into species products with species-free coefficients."""

    def species_free(inner: ast.AST) -> bool:
        for name_node in ast.walk(inner):
            if isinstance(name_node, ast.Name):
                if name_node.id in _CALLABLE_NAMES:
                    continue
                if isinstance(name_node.ctx, ast.Load) and _is_call_target(
                    inner, name_node
                ):
                    continue
                if analysis.is_fast_species(name_node.id):
                    return False
                if not analysis.is_species_free(name_node.id):
                    return False
        return True

    def factor(inner: ast.AST) -> List[_SymbolicTerm]:
        constant = _rate_terms(inner, resolver._model, resolver)
        if constant is not None and len(constant) == 1 and not constant[0].species:
            return [_SymbolicTerm((), constant[0].coefficient)]
        return [_SymbolicTerm((), 1.0, (inner,))]

    def scale(terms: List[_SymbolicTerm], value: float) -> List[_SymbolicTerm]:
        return [
            _SymbolicTerm(term.species, term.coefficient * value, term.factors)
            for term in terms
        ]

    def multiply(left: _SymbolicTerm, right: _SymbolicTerm) -> _SymbolicTerm:
        return _SymbolicTerm(
            _merge_species(left.species, right.species),
            left.coefficient * right.coefficient,
            left.factors + right.factors,
        )

    def visit(inner: ast.AST) -> Optional[List[_SymbolicTerm]]:
        if isinstance(inner, ast.Name) and analysis.is_fast_species(inner.id):
            identifier = resolver.species_id(inner.id)
            if identifier is not None:
                return [_SymbolicTerm(((identifier, 1),), 1.0)]
        if species_free(inner):
            return factor(inner)
        if isinstance(inner, ast.UnaryOp):
            if isinstance(inner.op, ast.UAdd):
                return visit(inner.operand)
            if isinstance(inner.op, ast.USub):
                result = visit(inner.operand)
                return None if result is None else scale(result, -1.0)
            return None
        if not isinstance(inner, ast.BinOp):
            return None
        if isinstance(inner.op, (ast.Add, ast.Sub)):
            left, right = visit(inner.left), visit(inner.right)
            if left is None or right is None:
                return None
            if isinstance(inner.op, ast.Sub):
                right = scale(right, -1.0)
            return left + right
        if isinstance(inner.op, ast.Mult):
            left, right = visit(inner.left), visit(inner.right)
            if left is None or right is None:
                return None
            if len(left) == 1:
                return [multiply(left[0], term) for term in right]
            if len(right) == 1:
                return [multiply(term, right[0]) for term in left]
            return None
        if isinstance(inner.op, ast.Div):
            if not species_free(inner.right):
                return None
            left = visit(inner.left)
            if left is None:
                return None
            denominator = factor(inner.right)[0]
            if not denominator.factors:
                if denominator.coefficient == 0:
                    return None
                return scale(left, 1.0 / denominator.coefficient)
            reciprocal = ast.BinOp(
                left=ast.Constant(value=1.0), op=ast.Div(), right=inner.right
            )
            return [
                _SymbolicTerm(
                    term.species, term.coefficient, term.factors + (reciprocal,)
                )
                for term in left
            ]
        if isinstance(inner.op, ast.Pow):
            exponent = inner.right
            if not (
                isinstance(exponent, ast.Constant)
                and isinstance(exponent.value, (int, float))
                and float(exponent.value).is_integer()
                and exponent.value >= 1
            ):
                return None
            base = visit(inner.left)
            if base is None or len(base) != 1:
                return None
            term = base[0]
            count = int(exponent.value)
            if term.factors or term.coefficient != 1.0:
                return None
            return [
                _SymbolicTerm(
                    tuple((name, power * count) for name, power in term.species),
                    1.0,
                )
            ]
        return None

    return visit(node)


def _piecewise_switch_plan(
    node: ast.AST,
    reactant_id: str,
    product_id: str,
    resolver: "_ConstantResolver",
    analysis: _SymbolAnalysis,
) -> Optional[_SteadyStatePlan]:
    """Lower a two-branch piecewise fast rate whose sign follows a condition.

    For a fast reaction ``R -> P`` with rate
    ``piecewise(R * k, k > 0, P * k)`` (parsed as ``if(gt(k, 0), R * k, P * k)``),
    the reaction runs forwards to completion (``R = 0``) while ``k > 0`` and
    backwards to completion (``P = 0``) while ``k < 0``.  Its pseudo steady
    state is therefore the switching pool projection governed by the sign of
    ``k``.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    func_name = node.func.id.lower()
    if func_name == "bng_if" and len(node.args) == 3:
        cond_node, true_branch, false_branch = node.args
    elif func_name == "piecewise" and len(node.args) == 3:
        true_branch, cond_node, false_branch = node.args
    else:
        return None

    def is_zero(expr: ast.AST) -> bool:
        value = _constant_value(_infix(expr), resolver)
        return value is not None and value == 0.0

    def is_species_free_expr(expr: ast.AST) -> bool:
        for name_node in ast.walk(expr):
            if isinstance(name_node, ast.Name):
                if name_node.id in _CALLABLE_NAMES:
                    continue
                if isinstance(name_node.ctx, ast.Load) and _is_call_target(
                    expr, name_node
                ):
                    continue
                if analysis.is_fast_species(name_node.id):
                    return False
                if not analysis.is_species_free(name_node.id):
                    return False
        return True

    # Extract (coeff_node, true_is_positive_branch) from cond_node.
    coeff_node: Optional[ast.AST] = None
    true_is_positive = True
    if (
        isinstance(cond_node, ast.Call)
        and isinstance(cond_node.func, ast.Name)
        and len(cond_node.args) == 2
    ):
        op = cond_node.func.id.lower()
        left, right = cond_node.args
        if op in {"gt", "geq"}:
            if is_zero(right):
                coeff_node, true_is_positive = left, True
            elif is_zero(left):
                coeff_node, true_is_positive = right, False
        elif op in {"lt", "leq"}:
            if is_zero(right):
                coeff_node, true_is_positive = left, False
            elif is_zero(left):
                coeff_node, true_is_positive = right, True
    if coeff_node is None or not is_species_free_expr(coeff_node):
        return None
    if analysis.can_vanish_on_an_interval((coeff_node,)):
        return None

    pos_branch, neg_branch = (
        (true_branch, false_branch) if true_is_positive else (false_branch, true_branch)
    )
    pos_terms = _symbolic_terms(pos_branch, resolver, analysis)
    neg_terms = _symbolic_terms(neg_branch, resolver, analysis)
    if pos_terms is None or neg_terms is None:
        return None
    pos_active = [term for term in pos_terms if term.coefficient != 0.0]
    neg_active = [term for term in neg_terms if term.coefficient != 0.0]
    if len(pos_active) != 1 or len(neg_active) != 1:
        return None
    pos_term, neg_term = pos_active[0], neg_active[0]
    participants = {reactant_id, product_id}
    if not (
        set(pos_term.species_ids) <= participants
        and set(neg_term.species_ids) <= participants
    ):
        return None
    pos_powers = dict(pos_term.species)
    neg_powers = dict(neg_term.species)
    if pos_powers.get(reactant_id, 0) < 1 or neg_powers.get(product_id, 0) < 1:
        return None

    coeff_dump = ast.dump(coeff_node)

    def branch_sign(term: _SymbolicTerm, coeff_sign: str) -> Optional[str]:
        sign = "+" if term.coefficient > 0 else "-"
        for factor in term.factors:
            if ast.dump(factor) == coeff_dump:
                factor_sign = coeff_sign
            else:
                factor_sign = analysis.sign(factor)
                if factor_sign not in {"+", "-"}:
                    return None
            sign = _combine_signs(sign, factor_sign)
        return sign

    if branch_sign(pos_term, "+") != "+" or branch_sign(neg_term, "-") != "-":
        return None
    return _SteadyStatePlan(
        "switch",
        "the species the fast reaction holds at zero follows the sign of "
        f'"{_infix(coeff_node)}": "{reactant_id}" while it is positive and '
        f'"{product_id}" while it is negative',
        coefficient=_infix(coeff_node),
    )


def _is_call_target(root: ast.AST, name_node: ast.Name) -> bool:
    for node in ast.walk(root):
        if isinstance(node, ast.Call) and node.func is name_node:
            return True
    return False


def _coefficient_text(term: _SymbolicTerm) -> str:
    pieces = [format_number(term.coefficient)]
    pieces.extend(f"({_infix(factor)})" for factor in term.factors)
    return " * ".join(pieces)


def _term_sign(term: _SymbolicTerm, analysis: _SymbolAnalysis) -> Optional[str]:
    sign = "+" if term.coefficient > 0 else "-"
    for factor in term.factors:
        factor_sign = analysis.sign(factor)
        if factor_sign is None:
            return None
        sign = _combine_signs(sign, factor_sign)
    return sign


def _initial_coefficient(term: _SymbolicTerm, analysis: _SymbolAnalysis):
    value = term.coefficient
    for factor in term.factors:
        factor_value = analysis.initial_value(factor)
        if factor_value is None:
            return None
        value *= factor_value
    return value


def _completion_plan(
    term: _SymbolicTerm,
    reactant_id: str,
    product_id: str,
    analysis: _SymbolAnalysis,
    sourced: Sequence[str] = (),
    model: Optional[SBMLModel] = None,
):
    """Return how a single-term fast rate fixes the amounts, or a refusal.

    A rate of one species holds that species at zero.  Its rate constant may
    become zero later only when no slow reaction produces the species: the
    species is then zero from the start and stays zero whatever the constant
    does, provided the constant is nonzero at the start.
    """

    def holds_from_the_start(species: str, wanted: str) -> bool:
        value = _initial_coefficient(term, analysis)
        if value is None or species in sourced:
            return False
        return value > 0 if wanted == "+" else value < 0

    def turns_on_from_zero(species_empty_initially: str, wanted: str) -> bool:
        if _initial_coefficient(term, analysis) != 0.0:
            return False
        if species_empty_initially in sourced:
            return False
        if model is not None:
            sp = model.species.get(species_empty_initially)
            if sp is not None:
                amount = _species_amount(model, sp)
                if amount is None or amount != 0.0:
                    return False
        for factor in term.factors:
            for name in _expression_names(factor):
                key = standardize_name(name)
                if key in analysis._assignment_rules or key in analysis._rate_rules:
                    return False
                if key not in analysis._event_values:
                    return False
                values = []
                for text in analysis._event_values[key]:
                    assigned = _constant_value(text, analysis._resolver)
                    if assigned is None:
                        return False
                    values.append(assigned)
                if not values:
                    return False
                if wanted == "+":
                    if not all(v > 0 for v in values):
                        return False
                else:
                    if not all(v < 0 for v in values):
                        return False
        return True

    powers = dict(term.species)
    depends_on_reactant = powers.get(reactant_id, 0) >= 1
    depends_on_product = powers.get(product_id, 0) >= 1
    if not (depends_on_reactant or depends_on_product):
        return (
            "the fast reaction's rate does not depend on the species it "
            "converts, so it has no steady state"
        )
    sign = _term_sign(term, analysis)
    forward = _SteadyStatePlan(
        "forward",
        f'species "{reactant_id}" is held at zero and "{product_id}" carries '
        "the fast subsystem's pool",
    )
    backward = _SteadyStatePlan(
        "backward",
        f'species "{product_id}" is held at zero and "{reactant_id}" carries '
        "the fast subsystem's pool",
    )
    if depends_on_reactant and depends_on_product:
        if sign == "+":
            return forward
        if sign == "-":
            return backward
        if analysis.can_vanish_on_an_interval(term.factors):
            return (
                "an event sets the fast reaction's rate constant to zero, so "
                "the fast reaction stops constraining its species over an "
                "interval and the two species are no longer a function of "
                "their pool"
            )
        return _SteadyStatePlan(
            "switch",
            "the species the fast reaction holds at zero follows the sign of "
            f'its rate constant: "{reactant_id}" while it is positive and '
            f'"{product_id}" while it is negative',
            coefficient=_coefficient_text(term),
        )
    if depends_on_reactant:
        if sign == "+" or (sign == "0+" and holds_from_the_start(reactant_id, "+")):
            return forward
        if sign == "0+" and turns_on_from_zero(product_id, "+"):
            return _SteadyStatePlan(
                "switch",
                "the species the fast reaction holds at zero follows the sign of "
                f'its rate constant: "{product_id}" while it is zero and '
                f'"{reactant_id}" while it is positive',
                coefficient=_coefficient_text(term),
            )
        return (
            "the fast reaction's rate depends only on the species it consumes, "
            "and its rate constant is not provably positive for the whole run, "
            "so its steady state is not defined at every instant"
        )
    if sign == "-" or (sign == "0-" and holds_from_the_start(product_id, "-")):
        return backward
    return (
        "the fast reaction's rate depends only on the species it produces, "
        "and its rate constant is not provably negative for the whole run, "
        "so its steady state is not defined at every instant"
    )


def _balance_plan(
    terms: Sequence[_SymbolicTerm],
    reactant_id: str,
    product_id: str,
    analysis: _SymbolAnalysis,
):
    """Return how a two-term balance fixes the amounts, or a refusal."""

    by_species: Dict[str, _SymbolicTerm] = {}
    for term in terms:
        if len(term.species) != 1 or term.species[0][1] != 1:
            return "the fast reaction's rate is not linear in one species per term"
        identifier = term.species[0][0]
        if identifier in by_species:
            return "the fast reaction's rate balances a species against itself"
        by_species[identifier] = term
    if set(by_species) != {reactant_id, product_id}:
        return "the fast reaction's rate depends on a species it does not convert"
    forward, backward = by_species[reactant_id], by_species[product_id]
    forward_sign = _term_sign(forward, analysis)
    backward_sign = _term_sign(backward, analysis)
    if forward_sign is None or backward_sign is None:
        return (
            "the signs of the fast reaction's rate constants cannot be "
            "established for the whole run, so the stability of its balance "
            "is not known"
        )
    if forward_sign in {"0+", "0-"} or backward_sign in {"0+", "0-"}:
        return (
            "an event can set one of the fast reaction's rate constants to "
            "zero, so its balance is not provably a single algebraic condition "
            "for the whole run"
        )
    if forward_sign != "+" or backward_sign != "-":
        return (
            "the fast reaction's balance is not stable: its rate does not "
            "decrease as the reaction proceeds"
        )
    negated = _SymbolicTerm(backward.species, -backward.coefficient, backward.factors)
    return _SteadyStatePlan(
        "balance",
        f'the fast subsystem is held on the balance between "{reactant_id}" '
        f'and "{product_id}", and the slow reactions move it along the '
        "balance",
        forward=_coefficient_text(forward),
        backward=_coefficient_text(negated),
        forward_value=forward.coefficient,
        backward_value=-backward.coefficient,
    )
