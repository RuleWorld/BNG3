"""Source-derived tests for the Playground SBML unit-normalization contract."""

from __future__ import annotations

import math
from collections import OrderedDict

import pytest

from bionetgen.atomizer.modern.types import (
    SBMLCompartment,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLSpecies,
)
from bionetgen.atomizer.modern.units import (
    apply_unit_scaling,
    resolve_unit_factor,
    unit_conversion_factor,
)


def test_playground_unit_conversion_factor_uses_all_term_fields():
    terms = [(0, -3, 1, 2), (0, 2, 2, 1)]

    assert unit_conversion_factor(terms) == pytest.approx(20.0)
    assert unit_conversion_factor(
        [{"scale": "invalid", "exponent": "invalid", "multiplier": "invalid"}]
    ) == pytest.approx(1.0)


def test_playground_resolve_unit_factor_treats_base_and_unknown_units_as_noops():
    model = SBMLModel(
        id="units",
        unit_definitions=OrderedDict([("mM", [(0, -3, 1, 1)])]),
    )

    assert resolve_unit_factor("mM", model) == pytest.approx(1e-3)
    assert resolve_unit_factor("litre", model) == pytest.approx(1.0)
    assert resolve_unit_factor("not_declared", model) == pytest.approx(1.0)
    assert resolve_unit_factor("", model) == pytest.approx(1.0)


def test_playground_apply_unit_scaling_covers_parameters_compartments_and_species():
    model = SBMLModel(
        id="units",
        substance_units="mmol",
        volume_units="litre",
        area_units="cm2",
        length_units="cm",
        unit_definitions=OrderedDict(
            [
                ("mmol", [(0, -3, 1, 1)]),
                ("cm", [(0, -2, 1, 1)]),
                ("cm2", [(0, -2, 2, 1)]),
            ]
        ),
        parameters=OrderedDict([("k", SBMLParameter(id="k", value=4, units="mmol"))]),
        reactions=OrderedDict(
            [
                (
                    "r",
                    SBMLReaction(
                        id="r",
                        kinetic_law=SBMLKineticLaw(
                            local_parameters=[
                                SBMLParameter(id="local", value=5, units="mmol")
                            ]
                        ),
                    ),
                )
            ]
        ),
        compartments=OrderedDict(
            [
                ("cell", SBMLCompartment(id="cell", spatial_dimensions=3, size=2)),
                (
                    "membrane",
                    SBMLCompartment(id="membrane", spatial_dimensions=2, size=3),
                ),
                ("line", SBMLCompartment(id="line", spatial_dimensions=1, size=4)),
            ]
        ),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A",
                        compartment="cell",
                        initial_amount=3,
                        initial_concentration=2,
                    ),
                ),
                (
                    "B",
                    SBMLSpecies(
                        id="B",
                        compartment="membrane",
                        initial_amount=5,
                        initial_concentration=7,
                    ),
                ),
            ]
        ),
    )

    warnings = apply_unit_scaling(model)

    assert model.parameters["k"].value == pytest.approx(0.004)
    assert model.reactions["r"].kinetic_law.local_parameters[0].value == pytest.approx(
        0.005
    )
    assert model.compartments["membrane"].size == pytest.approx(3e-4)
    assert model.compartments["line"].size == pytest.approx(0.04)
    assert model.species["A"].initial_amount == pytest.approx(0.003)
    assert model.species["A"].initial_concentration == pytest.approx(0.002)
    assert model.species["B"].initial_amount == pytest.approx(0.005)
    assert model.species["B"].initial_concentration == pytest.approx(70.0)
    assert len(warnings) == 9
    assert warnings[-1]["category"] == "units"
    assert "Applied SBML unit conversion" in warnings[-1]["message"]


def test_playground_unit_scaling_leaves_nonfinite_parameters_untouched():
    parameter = SBMLParameter(id="nan", value=math.nan, units="mmol")
    model = SBMLModel(
        id="units",
        unit_definitions=OrderedDict([("mmol", [(0, -3, 1, 1)])]),
        parameters=OrderedDict([("nan", parameter)]),
    )

    warnings = apply_unit_scaling(model)

    assert math.isnan(parameter.value)
    assert warnings == []
