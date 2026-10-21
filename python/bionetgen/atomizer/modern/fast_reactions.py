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

This module lowers the one shape of fast reaction whose pseudo steady state
BNG3 can express exactly: a fast reaction that converts one species into
one species and whose kinetic law is a constant multiple of one of those
two species.  The species the rate is proportional to is then held at zero
for all time, and the other species absorbs its initial amount at the
initial instant, scaled by the stoichiometry ratio.  Every other shape of
fast reaction needs an algebraic solve that BNG3 cannot perform, so those
are reported with the specific reason they cannot be reduced.
"""

from __future__ import annotations

import ast
import copy
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .types import SBMLModel, SBMLReaction, SBMLSpecies, standardize_name


@dataclass
class FastReactionOutcome:
    """The result of trying to reduce one fast reaction to its steady state."""

    reaction_id: str
    reduced: bool
    detail: str = ""
    reason: str = ""


def lower_fast_reactions(model: SBMLModel) -> Dict[str, FastReactionOutcome]:
    """Reduce the model's fast reactions to their pseudo steady states.

    The reduced reaction is removed from ``model.reactions`` and the initial
    amounts of the two species it converts are updated.  Reactions that
    cannot be reduced are left in the model and reported with the reason.
    """

    fast = [reaction for reaction in model.reactions.values() if reaction.fast]
    if not fast:
        return {}
    if len(fast) > 1:
        return {
            reaction.id: FastReactionOutcome(
                reaction.id,
                False,
                reason=(
                    "the model declares more than one fast reaction, so the "
                    "fast subsystem is not a single balance"
                ),
            )
            for reaction in fast
        }
    reaction = fast[0]
    outcome = _reduce_fast_reaction(model, reaction)
    if outcome.reduced:
        model.reactions = OrderedDict(
            (key, value) for key, value in model.reactions.items() if key != reaction.id
        )
    return {reaction.id: outcome}


def _reduce_fast_reaction(
    model: SBMLModel, reaction: SBMLReaction
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
    if model.conversion_factor:
        return refuse("the model declares a conversion factor")

    rate = _kinetic_law_math(reaction)
    if not rate.strip():
        return refuse("the fast reaction has no kinetic law")
    expression = _parse_expression(rate)
    if expression is None:
        return refuse("the fast reaction's kinetic law is not a supported expression")
    expression = _inline_function_calls(expression, model.function_definitions)

    resolver = _ConstantResolver(model, reaction)
    species_symbols = _species_symbols(expression, model)
    if len(species_symbols) != 1:
        participants = {reactant.species, product.species}
        if not species_symbols:
            return refuse(
                "the fast reaction's rate does not depend on a species it converts"
            )
        if len(species_symbols) > 1 and all(
            symbol in participants for symbol in species_symbols
        ):
            return refuse(
                "the fast reaction's rate depends on both species it converts, "
                "so its pseudo steady state is not a single-species balance"
            )
        return refuse(
            "the fast reaction's rate depends on a species it does not convert"
        )
    target = species_symbols[0]
    if target not in {reactant.species, product.species}:
        return refuse(
            "the fast reaction's kinetic law depends on a species that the "
            "reaction does not convert"
        )
    proportional, coefficient = _proportional_coefficient(
        expression.body, target, resolver
    )
    if not proportional:
        return refuse(
            "the fast reaction's kinetic law is not proportional to a single species"
        )
    if coefficient is None or coefficient == 0:
        return refuse(
            "the fast reaction's rate constant is not a time-independent value"
        )
    if target == reactant.species:
        if coefficient < 0:
            return refuse(
                "the fast reaction's rate runs backwards from the species it "
                "consumes"
            )
        consumed, produced = reactant.species, product.species
        consumed_stoichiometry = reactant_stoichiometry
        produced_stoichiometry = product_stoichiometry
    else:
        if coefficient > 0:
            return refuse(
                "the fast reaction's rate runs forwards from the species it " "produces"
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
        if species.conversion_factor:
            return refuse(f'species "{species.id}" declares a conversion factor')
        compartment = model.compartments.get(species.compartment or "")
        if compartment is not None and not compartment.constant:
            return refuse(f'compartment "{compartment.id}" is not constant')

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
    ratio = produced_stoichiometry / consumed_stoichiometry
    _set_species_amount(model, consumed_species, 0.0)
    _set_species_amount(
        model, produced_species, produced_amount + ratio * consumed_amount
    )
    return FastReactionOutcome(
        reaction.id,
        True,
        detail=(
            f'species "{consumed}" is held at zero and its initial amount is '
            f'transferred to "{produced}"'
        ),
    )


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


class _ConstantResolver:
    """Resolve the symbols of a rate law that hold a time-independent value."""

    def __init__(self, model: SBMLModel, reaction: SBMLReaction) -> None:
        self._values: Dict[str, float] = {}
        controlled = _controlled_symbols(model)
        for identifier, parameter in model.parameters.items():
            key = standardize_name(str(identifier))
            if key in controlled or not getattr(parameter, "constant", True):
                continue
            value = float(parameter.value)
            if math.isfinite(value):
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

    def value(self, identifier: str) -> Optional[float]:
        return self._values.get(standardize_name(str(identifier)))


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


def _species_symbols(expression: ast.AST, model: SBMLModel) -> List[str]:
    names = {
        standardize_name(node.id)
        for node in ast.walk(expression)
        if isinstance(node, ast.Name)
    }
    return [
        identifier
        for identifier in model.species
        if standardize_name(str(identifier)) in names
    ]


def _constant_value(node: ast.AST, resolver: _ConstantResolver) -> Optional[float]:
    """Evaluate an expression that holds a time-independent value."""

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        value = float(node.value)
        return value if math.isfinite(value) else None
    if isinstance(node, ast.Name):
        return resolver.value(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        inner = _constant_value(node.operand, resolver)
        if inner is None:
            return None
        return inner if isinstance(node.op, ast.UAdd) else -inner
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
    ):
        left = _constant_value(node.left, resolver)
        right = _constant_value(node.right, resolver)
        if left is None or right is None:
            return None
        try:
            value = {
                ast.Add: lambda: left + right,
                ast.Sub: lambda: left - right,
                ast.Mult: lambda: left * right,
                ast.Div: lambda: left / right,
                ast.Pow: lambda: left**right,
            }[type(node.op)]()
        except (ArithmeticError, OverflowError, ValueError):
            return None
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        return float(value)
    return None


def _proportional_coefficient(
    node: ast.AST, target: str, resolver: _ConstantResolver
) -> Tuple[bool, Optional[float]]:
    """Return whether the expression is proportional to ``target`` and its coefficient.

    The first element says whether the expression has the shape ``c *
    target`` at all; the second is the constant coefficient when the shape
    holds and the coefficient is a time-independent value.
    """

    key = standardize_name(target)
    if isinstance(node, ast.Name):
        return (True, 1.0) if standardize_name(node.id) == key else (False, None)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        proportional, coefficient = _proportional_coefficient(
            node.operand, target, resolver
        )
        if not proportional or coefficient is None:
            return proportional, coefficient
        return True, coefficient if isinstance(node.op, ast.UAdd) else -coefficient
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left_proportional, left_coefficient = _proportional_coefficient(
            node.left, target, resolver
        )
        right_proportional, right_coefficient = _proportional_coefficient(
            node.right, target, resolver
        )
        if left_proportional and right_proportional:
            return False, None
        if left_proportional:
            factor = _constant_value(node.right, resolver)
            if factor is None or left_coefficient is None:
                return True, None
            return True, left_coefficient * factor
        if right_proportional:
            factor = _constant_value(node.left, resolver)
            if factor is None or right_coefficient is None:
                return True, None
            return True, right_coefficient * factor
        return False, None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        proportional, coefficient = _proportional_coefficient(
            node.left, target, resolver
        )
        if not proportional:
            return False, None
        factor = _constant_value(node.right, resolver)
        if factor is None or coefficient is None or factor == 0:
            return True, None
        return True, coefficient / factor
    return False, None
