"""SBML unit normalization for the Playground-derived atomizer.

The Playground parser converts declared SBML quantities to SI-base values before
the BNGL writer turns concentrations into molecule counts.  Keeping that step
separate makes the transformation auditable and leaves unit-less BNG round trips
unchanged.
"""

from __future__ import annotations

import math
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

    def scale_parameter(parameter: Any, scope: str) -> None:
        parameter_id = (
            parameter.get("id", "")
            if isinstance(parameter, Mapping)
            else getattr(parameter, "id", "")
        )
        units = (
            parameter.get("units", "")
            if isinstance(parameter, Mapping)
            else getattr(parameter, "units", "")
        )
        factor = resolve_unit_factor(str(units or ""), model)
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

    for parameter in model.parameters.values():
        scale_parameter(parameter, "global")
    for reaction in model.reactions.values():
        for parameter in _local_parameters(getattr(reaction, "kinetic_law", None)):
            scale_parameter(parameter, f"local ({getattr(reaction, 'id', 'reaction')})")

    compartment_factors: Dict[str, float] = {}
    compartment_exact_factors: Dict[str, Optional[Decimal]] = {}
    for compartment_id, compartment in model.compartments.items():
        dimensions = float(getattr(compartment, "spatial_dimensions", 3) or 3)
        default_units = (
            area_default
            if dimensions == 2
            else length_default if dimensions == 1 else volume_default
        )
        units = str(getattr(compartment, "units", "") or default_units or "")
        factor = resolve_unit_factor(units, model)
        compartment_factors[compartment_id] = factor
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

    for species_id, species in model.species.items():
        substance_units = str(
            getattr(species, "substance_units", "") or substance_default or ""
        )
        substance_factor = resolve_unit_factor(substance_units, model)
        substance_exact_factor = resolve_decimal_unit_factor(substance_units, model)
        volume_factor = compartment_factors.get(
            getattr(species, "compartment", ""), 1.0
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

    if warnings:
        warnings.append(
            _warning(
                f"Applied SBML unit conversion to {len(warnings)} quantity/ies. "
                "Check these factors if a model declares inconsistent units."
            )
        )
    return warnings


__all__ = ["apply_unit_scaling", "resolve_unit_factor", "unit_conversion_factor"]
