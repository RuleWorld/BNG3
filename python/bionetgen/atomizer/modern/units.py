"""SBML unit normalization for the Playground-derived atomizer.

The Playground parser converts declared SBML quantities to SI-base values before
the BNGL writer turns concentrations into molecule counts.  Keeping that step
separate makes the transformation auditable and leaves unit-less BNG round trips
unchanged.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Dict, Iterable, Mapping, Optional

from .types import SBMLModel

# The number of significant digits used while a scaled value is computed.
# A double carries at most seventeen, and a conversion factor adds a handful
# more, so this is enough to round the product to the nearest double exactly
# once.
_SCALING_PRECISION = 60


def _term_value(term: Any, key: str, index: int, default: float) -> float:
    if isinstance(term, Mapping):
        value = term.get(key, default)
    else:
        try:
            value = term[index]
        except (IndexError, KeyError, TypeError):
            value = default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def unit_conversion_factor(terms: Iterable[Any]) -> float:
    """Return ``Π (multiplier * 10**scale)**exponent`` for one unit definition."""

    factor = 1.0
    for term in terms:
        scale = _term_value(term, "scale", 1, 0.0)
        exponent = _term_value(term, "exponent", 2, 1.0)
        multiplier = _term_value(term, "multiplier", 3, 1.0)
        if multiplier < 0:
            return 1.0
        try:
            factor *= math.pow(multiplier * math.pow(10.0, scale), exponent)
        except (OverflowError, ValueError, ZeroDivisionError):
            return 1.0
        if not math.isfinite(factor):
            return 1.0
    return factor


def decimal_conversion_factor(terms: Iterable[Any]) -> Optional[Decimal]:
    """Return the exact conversion factor of one unit definition.

    A unit definition is a product of ``(multiplier * 10**scale)**exponent``
    terms, so its factor is a decimal number.  The double returned by
    :func:`unit_conversion_factor` is only an approximation of it, and scaling
    a value by that approximation rounds twice: once when the factor is
    approximated and once when the product is rounded.  For a compartment
    whose size is of order 1e-15 the second rounding is worth a full unit in
    the last place of the scaled size, which is enough to change the
    trajectory of a stiff model.
    """

    factor = Decimal(1)
    for term in terms:
        scale = int(_term_value(term, "scale", 1, 0.0))
        exponent = int(_term_value(term, "exponent", 2, 1.0))
        multiplier = _term_value(term, "multiplier", 3, 1.0)
        if multiplier < 0:
            return None
        try:
            base = Decimal(repr(multiplier)) * (Decimal(10) ** scale)
            factor *= (
                base**exponent if exponent >= 0 else Decimal(1) / base ** (-exponent)
            )
        except (InvalidOperation, OverflowError, ValueError, ZeroDivisionError):
            return None
    if not factor.is_finite() or factor == 0:
        return None
    return factor


def resolve_unit_factor(unit_id: str, model: SBMLModel) -> float:
    """Resolve a declared unit id, treating unknown/base units as a no-op."""

    if not unit_id:
        return 1.0
    terms = model.unit_definitions.get(unit_id)
    if terms is None:
        return 1.0
    factor = unit_conversion_factor(terms)
    return factor if math.isfinite(factor) and factor != 0 else 1.0


def resolve_decimal_unit_factor(unit_id: str, model: SBMLModel) -> Optional[Decimal]:
    """Resolve a declared unit id into its exact decimal factor."""

    if not unit_id:
        return None
    terms = model.unit_definitions.get(unit_id)
    if terms is None:
        return None
    return decimal_conversion_factor(terms)


def scaled_value(
    value: float, factor: Optional[Decimal], fallback: float = 1.0
) -> float:
    """Scale a value by an exact factor and round the product once.

    Scaling by the double approximation of the factor rounds the product
    twice, so the result can sit one unit in the last place away from the
    value the source states.  The scaled size of a compartment is the case
    where that matters: the value is the denominator of every concentration
    in the compartment, and the resulting rate laws are stiff enough that a
    single unit in the last place changes the trajectory.

    ``fallback`` is the double approximation of the factor, used when the
    unit definition has no exact decimal form.
    """

    if factor is None:
        return value * fallback
    try:
        with localcontext() as context:
            context.prec = _SCALING_PRECISION
            return float(Decimal(value) * factor)
    except (InvalidOperation, OverflowError, ValueError):
        return value * fallback


def _near_one(factor: float) -> bool:
    return abs(factor - 1.0) < 1e-12


def _warning(message: str) -> Dict[str, Any]:
    return {"category": "units", "message": message, "count": 1, "severity": "info"}


def _local_parameters(kinetic_law: Any):
    if kinetic_law is None:
        return []
    if isinstance(kinetic_law, Mapping):
        return kinetic_law.get("localParameters", []) or []
    return getattr(kinetic_law, "local_parameters", []) or []


def _parameter_value(parameter: Any) -> float:
    value = (
        parameter.get("value")
        if isinstance(parameter, Mapping)
        else getattr(parameter, "value", 0)
    )
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value


def _set_parameter_value(parameter: Any, value: float) -> None:
    if isinstance(parameter, Mapping):
        parameter["value"] = value
    else:
        parameter.value = value


def _parameter_id(parameter: Any) -> str:
    return str(
        parameter.get("id", "")
        if isinstance(parameter, Mapping)
        else getattr(parameter, "id", "")
    )


def _kinetic_law_math(kinetic_law: Any) -> str:
    if isinstance(kinetic_law, Mapping):
        return str(kinetic_law.get("math", "") or "")
    return str(getattr(kinetic_law, "math", "") or "")


def _set_kinetic_law_math(kinetic_law: Any, expression: str) -> None:
    if isinstance(kinetic_law, Mapping):
        kinetic_law["math"] = expression
    if hasattr(kinetic_law, "math"):
        kinetic_law.math = expression


def _source_coordinate_expression(
    expression: str,
    symbol_factors: Mapping[str, float],
    result_factor: float,
    function_definitions: Mapping[str, Any],
) -> str:
    """Rewrite one SBML expression from normalized coordinates to source ones."""

    if not expression:
        return expression
    if function_definitions:
        # Use the writer's established bounded expansion so formal arguments
        # remain local even when they shadow a scaled global parameter.
        from .writer import inline_sbml_functions

        expression = inline_sbml_functions(expression, function_definitions)
    factors = {
        str(symbol): factor
        for symbol, factor in symbol_factors.items()
        if symbol and math.isfinite(factor) and factor != 0 and not _near_one(factor)
    }
    if function_definitions:
        # Valid SBML function bodies can reference only their formal arguments
        # and other functions (L3V2 Core 4.3.2). After expansion, a remaining
        # call therefore carries any scaled dependencies in its actuals.
        # Reuse the writer's nested-call parser to avoid confusing function
        # formals or similarly named globals with real dependencies.
        from .writer import _function_call_pattern, _split_arguments

        for function_id in function_definitions:
            pattern = _function_call_pattern(str(function_id))
            cursor = 0
            while match := pattern.search(expression, cursor):
                depth = 1
                end = match.end()
                while depth and end < len(expression):
                    if expression[end] == "(":
                        depth += 1
                    elif expression[end] == ")":
                        depth -= 1
                    end += 1
                if depth:
                    break
                actuals = _split_arguments(expression[match.end() : end - 1])
                actual_text = " ".join(actuals)
                if any(
                    re.search(
                        rf"(?<![A-Za-z0-9_.$]){re.escape(symbol)}(?![A-Za-z0-9_])",
                        actual_text,
                    )
                    for symbol in factors
                ):
                    raise ValueError(
                        "Cannot preserve SBML unit normalization for unresolved "
                        f"function call {function_id!r} with scaled actual arguments."
                    )
                cursor = end
    if factors:
        identifiers = sorted(factors, key=lambda symbol: (-len(symbol), symbol))
        pattern = re.compile(
            r"(?<![A-Za-z0-9_.$])(?:"
            + "|".join(re.escape(symbol) for symbol in identifiers)
            + r")(?![A-Za-z0-9_])"
        )

        def source_coordinate(match: re.Match[str]) -> str:
            symbol = match.group(0)
            factor = factors[symbol]
            return f"({symbol} / {factor:.17g})"

        expression = pattern.sub(source_coordinate, expression)
    if math.isfinite(result_factor) and not _near_one(result_factor):
        expression = f"({result_factor:.17g}) * ({expression})"
    return expression


def _expression_value(owner: Any, name: str) -> str:
    if isinstance(owner, Mapping):
        return str(owner.get(name, "") or "")
    return str(getattr(owner, name, "") or "")


def _set_expression_value(owner: Any, name: str, expression: str) -> None:
    if hasattr(owner, name):
        setattr(owner, name, expression)
    elif isinstance(owner, dict):
        owner[name] = expression


def apply_unit_scaling(model: SBMLModel) -> list[Dict[str, Any]]:
    """Scale parsed SBML values into SI-base units and return audit warnings."""

    warnings: list[Dict[str, Any]] = []
    substance_default = getattr(model, "substance_units", "")
    volume_default = getattr(model, "volume_units", "")
    area_default = getattr(model, "area_units", "")
    length_default = getattr(model, "length_units", "")

    # Without model-level defaults, SBML leaves the units of unqualified
    # species values implicit.  Several curated VCell/MathSBML models attach
    # detailed unit definitions but intentionally use their source numeric
    # scale (and omit both defaults); converting compartments to SI while
    # leaving those unqualified values unchanged creates artificial 1e18
    # factors and a numerically different model.  Preserve that source scale
    # and make the choice auditable instead of guessing a default.
    if not substance_default and not volume_default:
        has_finite_quantity = (
            any(
                math.isfinite(float(getattr(parameter, "value", 0) or 0))
                for parameter in model.parameters.values()
            )
            or any(
                math.isfinite(float(getattr(species, "initial_amount", 0) or 0))
                or math.isfinite(
                    float(getattr(species, "initial_concentration", 0) or 0)
                )
                for species in model.species.values()
            )
            or any(
                math.isfinite(float(getattr(compartment, "size", 0) or 0))
                for compartment in model.compartments.values()
            )
        )
        if not has_finite_quantity and model.unit_definitions:
            return warnings
        warnings.append(
            _warning(
                "Model omits substanceUnits and volumeUnits; preserved source "
                "numeric scale and skipped unit normalization."
            )
        )
        return warnings

    coordinate_factors: Dict[str, float] = {}
    local_coordinate_factors: Dict[str, Dict[str, float]] = {}

    def scale_parameter(
        parameter: Any, scope: str, coordinate_map: Dict[str, float]
    ) -> float:
        parameter_id = _parameter_id(parameter)
        units = (
            parameter.get("units", "")
            if isinstance(parameter, Mapping)
            else getattr(parameter, "units", "")
        )
        factor = resolve_unit_factor(str(units or ""), model)
        if parameter_id:
            coordinate_map[parameter_id] = factor
        exact_factor = resolve_decimal_unit_factor(str(units or ""), model)
        value = _parameter_value(parameter)
        if not _near_one(factor) and math.isfinite(value):
            _set_parameter_value(parameter, scaled_value(value, exact_factor, factor))
            warnings.append(
                _warning(
                    f'Scaled {scope} parameter "{parameter_id}" by {factor:g} '
                    f'(unit "{units}") to SI base units.'
                )
            )
        return factor

    for parameter in model.parameters.values():
        scale_parameter(parameter, "global", coordinate_factors)
    for reaction in model.reactions.values():
        local_factors: Dict[str, float] = {}
        for parameter in _local_parameters(getattr(reaction, "kinetic_law", None)):
            factor = scale_parameter(
                parameter,
                f"local ({getattr(reaction, 'id', 'reaction')})",
                local_factors,
            )
            parameter_id = _parameter_id(parameter)
            if parameter_id:
                local_factors[parameter_id] = factor
        if local_factors:
            local_coordinate_factors[str(getattr(reaction, "id", ""))] = local_factors

    compartment_factors: Dict[str, float] = {}
    compartment_exact_factors: Dict[str, Optional[Decimal]] = {}
    for compartment_id, compartment in model.compartments.items():
        dimensions = float(getattr(compartment, "spatial_dimensions", 3))
        default_units = (
            area_default
            if dimensions == 2
            else (
                length_default
                if dimensions == 1
                else volume_default if dimensions == 3 else ""
            )
        )
        units = str(getattr(compartment, "units", "") or default_units or "")
        factor = resolve_unit_factor(units, model)
        compartment_factors[compartment_id] = factor
        coordinate_factors[str(compartment_id)] = factor
        compartment_exact_factors[compartment_id] = resolve_decimal_unit_factor(
            units, model
        )
        size = float(getattr(compartment, "size", 0) or 0)
        if not _near_one(factor) and math.isfinite(size):
            compartment.size = scaled_value(
                size, compartment_exact_factors[compartment_id], factor
            )
            warnings.append(
                _warning(
                    f'Scaled compartment "{compartment_id}" size by {factor:g} '
                    f'(unit "{units}").'
                )
            )

    species_amount_factors: Dict[str, float] = {}
    for species_id, species in model.species.items():
        substance_units = str(
            getattr(species, "substance_units", "") or substance_default or ""
        )
        substance_factor = resolve_unit_factor(substance_units, model)
        substance_exact_factor = resolve_decimal_unit_factor(substance_units, model)
        compartment = model.compartments.get(getattr(species, "compartment", ""))
        raw_dimensions = getattr(compartment, "spatial_dimensions", 3)
        dimensions = 3.0 if raw_dimensions is None else float(raw_dimensions)
        volume_factor = (
            compartment_factors.get(getattr(species, "compartment", ""), 1.0)
            if dimensions != 0
            else 1.0
        )
        species_amount_factors[str(species_id)] = substance_factor
        coordinate_factors[str(species_id)] = (
            substance_factor
            if dimensions == 0
            or bool(getattr(species, "has_only_substance_units", False))
            else substance_factor / (volume_factor or 1.0)
        )
        volume_exact_factor = compartment_exact_factors.get(
            getattr(species, "compartment", "")
        )
        amount = float(getattr(species, "initial_amount", 0) or 0)
        amount_set = bool(getattr(species, "initial_amount_set", False) or amount != 0)
        if amount_set and not _near_one(substance_factor) and math.isfinite(amount):
            species.initial_amount = scaled_value(
                amount, substance_exact_factor, substance_factor
            )
            warnings.append(
                _warning(
                    f'Scaled species "{species_id}" initialAmount by '
                    f"{substance_factor:g}."
                )
            )

        concentration_factor = substance_factor / (volume_factor or 1.0)
        concentration_exact_factor: Optional[Decimal] = None
        if substance_exact_factor is not None and volume_exact_factor is not None:
            with localcontext() as context:
                context.prec = _SCALING_PRECISION
                concentration_exact_factor = (
                    substance_exact_factor / volume_exact_factor
                )
        concentration = float(getattr(species, "initial_concentration", 0) or 0)
        concentration_set = bool(
            getattr(species, "initial_concentration_set", False) or concentration != 0
        )
        if (
            concentration_set
            and not _near_one(concentration_factor)
            and math.isfinite(concentration)
        ):
            species.initial_concentration = scaled_value(
                concentration, concentration_exact_factor, concentration_factor
            )
            warnings.append(
                _warning(
                    f'Scaled species "{species_id}" initialConcentration by '
                    f"{concentration_factor:g}."
                )
            )

    reaction_rate_factors: Dict[str, float] = {}
    for reaction_id, reaction in model.reactions.items():
        participants: Dict[str, float] = {}
        net_stoichiometry: Dict[str, float] = {}
        for reference in reaction.reactants:
            species_id = str(reference.species)
            if species_id == "EmptySet":
                continue
            net_stoichiometry[species_id] = net_stoichiometry.get(
                species_id, 0
            ) - float(reference.stoichiometry)
        for reference in reaction.products:
            species_id = str(reference.species)
            if species_id == "EmptySet":
                continue
            net_stoichiometry[species_id] = net_stoichiometry.get(
                species_id, 0
            ) + float(reference.stoichiometry)
        for species_id, coefficient in net_stoichiometry.items():
            if coefficient == 0:
                continue
            species = model.species.get(species_id)
            if species is None or species.boundary_condition or species.constant:
                continue
            conversion_factor_id = (
                getattr(species, "conversion_factor", None) or model.conversion_factor
            )
            conversion_factor_scale = coordinate_factors.get(
                str(conversion_factor_id), 1.0
            )
            participants[species_id] = (
                species_amount_factors.get(species_id, 1.0) / conversion_factor_scale
            )
        rate_factors = list(participants.values())
        rate_factor = rate_factors[0] if rate_factors else 1.0
        if any(
            not math.isclose(factor, rate_factor, rel_tol=1e-12)
            for factor in rate_factors[1:]
        ):
            raise ValueError(
                f'Cannot preserve reaction "{reaction_id}" because its species '
                "require different normalized flux scales."
            )
        reaction_rate_factors[str(reaction_id)] = rate_factor
        coordinate_factors[str(reaction_id)] = rate_factor

    for reaction_id, reaction in model.reactions.items():
        kinetic_law = getattr(reaction, "kinetic_law", None)
        if kinetic_law is None:
            continue
        rate_factor = reaction_rate_factors[str(reaction_id)]
        factors = dict(coordinate_factors)
        factors.update(local_coordinate_factors.get(str(reaction_id), {}))
        expression = _kinetic_law_math(kinetic_law)
        _set_kinetic_law_math(
            kinetic_law,
            _source_coordinate_expression(
                expression, factors, rate_factor, model.function_definitions
            ),
        )

    def rewrite_owner(owner: Any, field: str, result_factor: float) -> None:
        expression = _expression_value(owner, field)
        if expression:
            _set_expression_value(
                owner,
                field,
                _source_coordinate_expression(
                    expression,
                    coordinate_factors,
                    result_factor,
                    model.function_definitions,
                ),
            )

    for rule in model.rules:
        result_factor = coordinate_factors.get(str(rule.variable), 1.0)
        rewrite_owner(rule, "math", result_factor if rule.type != "algebraic" else 1.0)
    for assignment in model.initial_assignments:
        rewrite_owner(
            assignment,
            "math",
            coordinate_factors.get(str(assignment.symbol), 1.0),
        )
    for event in model.events:
        rewrite_owner(event, "trigger", 1.0)
        rewrite_owner(event, "delay", 1.0)
        rewrite_owner(event, "priority", 1.0)
        for assignment in event.assignments:
            rewrite_owner(
                assignment,
                "math",
                coordinate_factors.get(str(assignment.variable), 1.0),
            )

    if warnings:
        warnings.append(
            _warning(
                f"Applied SBML unit conversion to {len(warnings)} quantity/ies. "
                "Check these factors if a model declares inconsistent units."
            )
        )
    return warnings


__all__ = ["apply_unit_scaling", "resolve_unit_factor", "unit_conversion_factor"]
