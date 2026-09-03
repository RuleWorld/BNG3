"""SBML unit normalization for the Playground-derived atomizer.

The Playground parser converts declared SBML quantities to SI-base values before
the BNGL writer turns concentrations into molecule counts.  Keeping that step
separate makes the transformation auditable and leaves unit-less BNG round trips
unchanged.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping

from .types import SBMLModel


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


def resolve_unit_factor(unit_id: str, model: SBMLModel) -> float:
    """Resolve a declared unit id, treating unknown/base units as a no-op."""

    if not unit_id:
        return 1.0
    terms = model.unit_definitions.get(unit_id)
    if terms is None:
        return 1.0
    factor = unit_conversion_factor(terms)
    return factor if math.isfinite(factor) and factor != 0 else 1.0


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
    return value if math.isfinite(value) else 0.0


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
        value = _parameter_value(parameter)
        if not _near_one(factor) and math.isfinite(value):
            _set_parameter_value(parameter, value * factor)
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
        size = float(getattr(compartment, "size", 0) or 0)
        if not _near_one(factor) and math.isfinite(size):
            compartment.size = size * factor
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
        volume_factor = compartment_factors.get(
            getattr(species, "compartment", ""), 1.0
        )
        amount = float(getattr(species, "initial_amount", 0) or 0)
        amount_set = bool(getattr(species, "initial_amount_set", False) or amount != 0)
        if amount_set and not _near_one(substance_factor) and math.isfinite(amount):
            species.initial_amount = amount * substance_factor
            warnings.append(
                _warning(
                    f'Scaled species "{species_id}" initialAmount by '
                    f"{substance_factor:g}."
                )
            )

        concentration_factor = substance_factor / (volume_factor or 1.0)
        concentration = float(getattr(species, "initial_concentration", 0) or 0)
        concentration_set = bool(
            getattr(species, "initial_concentration_set", False) or concentration != 0
        )
        if (
            concentration_set
            and not _near_one(concentration_factor)
            and math.isfinite(concentration)
        ):
            species.initial_concentration = concentration * concentration_factor
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
