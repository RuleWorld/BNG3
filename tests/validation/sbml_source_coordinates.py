"""Bounded ODE identity in source coordinates; never a graph/SSA oracle.

The admitted source subset has one fixed unit compartment, explicit initial
amounts, parameter assignment rules and polynomial kinetic laws. Network
coordinates must form a bijection with source species. Unsupported source or
rate syntax raises instead of being approximated.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import libsbml
import sympy as sp

from tests.validation.compare import parse_net


class InvalidSource(ValueError):
    pass


class UnsupportedSource(ValueError):
    pass


class SemanticMismatch(ValueError):
    pass


def _expression(text: str):
    """Parse arithmetic without eval/sympify on executable source strings."""
    text = text.replace("^", "**")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return sp.Rational(ast.get_source_segment(text, node))
        if isinstance(node, ast.Name):
            return sp.Symbol(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            operations = {
                ast.Add: lambda: left + right,
                ast.Sub: lambda: left - right,
                ast.Mult: lambda: left * right,
                ast.Div: lambda: left / right,
                ast.Pow: lambda: left**right,
            }
            if type(node.op) in operations:
                return operations[type(node.op)]()
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and not node.args
            and not node.keywords
        ):
            return sp.Symbol(node.func.id)
        raise ValueError("unsupported symbolic expression")

    return visit(ast.parse(text, mode="eval").body)


def _resolved(expression, definitions, variables):
    for _ in range(len(definitions) + 1):
        updated = expression.subs(definitions, simultaneous=True)
        if updated == expression:
            break
        expression = updated
    if expression.free_symbols - set(variables):
        raise ValueError(
            f"unresolved rate symbols: {expression.free_symbols - set(variables)}"
        )
    return expression


def compare_source_rhs(source: Path, network: Path, coordinates: dict[str, int]):
    document = libsbml.readSBMLFromFile(str(source))
    document.checkConsistency()
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    if errors:
        raise InvalidSource(f"invalid source: {errors}")
    model = document.getModel()
    if (
        model.getNumCompartments() != 1
        or not model.getCompartment(0).getConstant()
        or model.getCompartment(0).getSize() != 1
    ):
        raise UnsupportedSource("requires one unit constant compartment")
    if (
        model.getNumEvents()
        or model.getNumFunctionDefinitions()
        or model.getNumInitialAssignments()
        or model.isSetConversionFactor()
    ):
        raise UnsupportedSource("source outside bounded ODE subset")
    species = list(model.getListOfSpecies())
    if any(
        not s.isSetInitialAmount()
        or s.getBoundaryCondition()
        or s.getConstant()
        or s.isSetConversionFactor()
        for s in species
    ):
        raise UnsupportedSource("source requires explicit dynamic initial amounts")
    parsed = parse_net(network)
    if (
        set(coordinates) != {s.id for s in species}
        or set(coordinates.values()) != set(parsed.species_by_index)
        or len(set(coordinates.values())) != len(coordinates)
    ):
        raise ValueError("source/network coordinates must be a complete bijection")
    variables = {s.id: sp.Symbol("source:" + s.id) for s in species}
    environment = {sp.Symbol(name): value for name, value in variables.items()}
    environment.update(
        {
            sp.Symbol(p.id): sp.Rational(str(p.value))
            for p in model.getListOfParameters()
            if p.isSetValue()
        }
    )
    for rule in model.getListOfRules():
        if not rule.isAssignment() or model.getParameter(rule.getVariable()) is None:
            raise UnsupportedSource("source rule outside parameter-assignment subset")
        environment[sp.Symbol(rule.getVariable())] = _expression(
            libsbml.formulaToL3String(rule.getMath())
        )
    expected = {name: sp.S.Zero for name in variables}
    for reaction in model.getListOfReactions():
        if reaction.getFast():
            raise UnsupportedSource("fast reaction outside bounded ODE subset")
        law = reaction.getKineticLaw()
        if law is None:
            raise ValueError("missing source kinetic law")
        local = dict(environment)
        local.update(
            {
                sp.Symbol(p.id): sp.Rational(str(p.value))
                for p in law.getListOfLocalParameters()
            }
        )
        local.update(
            {
                sp.Symbol(p.id): sp.Rational(str(p.value))
                for p in law.getListOfParameters()
            }
        )
        rate = _resolved(
            _expression(libsbml.formulaToL3String(law.getMath())),
            local,
            variables.values(),
        )
        for references, sign in [
            (reaction.getListOfReactants(), -1),
            (reaction.getListOfProducts(), 1),
        ]:
            for reference in references:
                if reference.isSetStoichiometryMath():
                    raise UnsupportedSource(
                        "dynamic stoichiometry outside bounded subset"
                    )
                expected[reference.species] += (
                    sign * sp.Rational(str(reference.stoichiometry)) * rate
                )
    mapping = {index: variables[name] for name, index in coordinates.items()}
    for s in species:
        if _expression(parsed.initial_amounts[coordinates[s.id]]) != sp.Rational(
            str(s.getInitialAmount())
        ):
            raise SemanticMismatch(f"initial amount mismatch: {s.id}")
    definitions = {
        sp.Symbol(name): _expression(value) for name, value in parsed.rate_defs.items()
    }
    definitions.update(
        {
            sp.Symbol(name): sum(
                sp.Rational(str(weight)) * mapping[index]
                for index, weight in weights.items()
            )
            for name, weights in parsed.groups.values()
        }
    )
    actual = {name: sp.S.Zero for name in variables}
    reverse = {index: name for name, index in coordinates.items()}
    for reactants, products, raw in parsed._raw:
        rate = _resolved(_expression(raw), definitions, variables.values())
        for index in reactants:
            rate *= mapping[index]
        for indices, sign in [(reactants, -1), (products, 1)]:
            for index in indices:
                actual[reverse[index]] += sign * rate
    residuals = {
        name: str(sp.simplify(expected[name] - actual[name])) for name in variables
    }
    if any(value != "0" for value in residuals.values()):
        raise SemanticMismatch(f"RHS mismatch: {residuals}")
    return {
        "scope": "initial amounts and deterministic ODE RHS under the stated bijection",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "network_sha256": hashlib.sha256(network.read_bytes()).hexdigest(),
        "coordinates": coordinates,
        "residuals": residuals,
        "libsbml": libsbml.getLibSBMLDottedVersion(),
        "sympy": sp.__version__,
    }
