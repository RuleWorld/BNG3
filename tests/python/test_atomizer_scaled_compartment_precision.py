"""Regression test for the precision of a scaled compartment size.

A unit conversion factor is a decimal number: a unit definition is a product
of ``(multiplier * 10**scale)**exponent`` terms.  Scaling a value by the
*double* approximation of that factor rounds the product twice, once when the
factor is approximated and once when the product is rounded, and the result
can sit a full unit in the last place away from the value the source states.

For a compartment that matters.  The curated record BIOMD0000000638 declares
a compartment of 3.92 femtolitre; the scaled size is 3.92e-15 litre, and the
record's rate laws divide by it, so the rate coefficients are of order 1e19
and the model is stiff.  The double-rounded size, one unit in the last place
away, is enough to stop libRoadRunner's CVODE from taking its first step:
the independent oracle fails with ``CV_CONV_FAILURE`` at ``t = 0`` and
``h = 2.4e-43``.

The fixture in ``models/scaled_compartment_3_92_picolitre.sbml`` is that record
reduced to the eight reactions and the species the failure needs.  The test
judges the translation with libRoadRunner as the oracle, and it also states
the value property directly, so a failure names the cause.
"""

from __future__ import annotations

import pathlib

import pytest

from bionetgen.atomizer.modern import Atomizer

from _extdep import require_extension

MODEL = (
    pathlib.Path(__file__).parent / "models" / "scaled_compartment_3_92_picolitre.sbml"
)

# The correctly rounded double of 3.92e-15, the SI-base value of the
# compartment the fixture declares.
EXPECTED_SIZE = float("3.92e-15")
SOURCE_VOLUME_SCALE = 1e-15
# The source fixture expresses concentrations in item/(10^-15 litre), while
# the generated SBML uses item/litre. Preserve the same absolute error scale
# when changing coordinates for RoadRunner: 1e-12 source units becomes 1e3
# item/litre. Keeping 1e-12 unchanged would ask CVODE to resolve values at a
# scale fifteen orders of magnitude smaller after the unit conversion.
ROADRUNNER_ABSOLUTE_TOLERANCE = 1e-12 / SOURCE_VOLUME_SCALE


def _translation() -> str:
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        MODEL.read_text(encoding="utf-8")
    )
    assert result.success, result.error
    return result.bngl


def test_scaled_compartment_size_is_the_correctly_rounded_value():
    """The scaled size must be the value the source states, to the last bit."""

    bngl = _translation()
    sizes = [
        line.split()[-1]
        for line in bngl.splitlines()
        if line.strip().startswith("__compartment_PM__ ")
    ]
    assert sizes, "the scaled compartment size is missing from the model"
    for text in sizes:
        assert float(text) == EXPECTED_SIZE, (
            f"the scaled compartment size {text} is not the correctly rounded "
            f"value {EXPECTED_SIZE!r}"
        )


def test_independent_oracle_integrates_the_scaled_model():
    """libRoadRunner has to be able to integrate the written model."""

    roadrunner = pytest.importorskip("roadrunner")
    extension = require_extension()
    bngl = _translation()
    model = extension.parse_string(bngl)
    network = extension.generate_network(model, max_iter=100)
    output = MODEL.parent / "scaled_compartment_3_92_picolitre_written.sbml"
    try:
        extension.io.write_sbml(model, network, str(output))
        solver = roadrunner.RoadRunner(str(output))
        source_solver = roadrunner.RoadRunner(str(MODEL))
        source_amount = source_solver.getFloatingSpeciesAmountsNamedArray()[0, 0]
        written_amount = solver.getFloatingSpeciesAmountsNamedArray()[0, 0]
        source_concentration = (
            source_solver.getFloatingSpeciesConcentrationsNamedArray()[0, 0]
        )
        written_concentration = solver.getFloatingSpeciesConcentrationsNamedArray()[
            0, 0
        ]
        assert written_amount == pytest.approx(source_amount, rel=0, abs=1e-12)
        assert written_concentration == pytest.approx(
            source_concentration / SOURCE_VOLUME_SCALE, rel=1e-12
        )
        integrator = solver.integrator
        if integrator.hasValue("relative_tolerance"):
            integrator.setValue("relative_tolerance", 1e-7)
        if integrator.hasValue("absolute_tolerance"):
            integrator.setValue("absolute_tolerance", ROADRUNNER_ABSOLUTE_TOLERANCE)
        solver.timeCourseSelections = ["time"]
        values = solver.simulate(0.0, 1.0, 11)
    finally:
        output.unlink(missing_ok=True)
    assert len(values) == 11
