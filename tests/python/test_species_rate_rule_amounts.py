"""Species rate rules define SBML symbol derivatives, not always amount fluxes."""

import pytest
from _extdep import require_extension

cpp = require_extension()


def source(volume=0.5, amount_symbol=False, dimension=3, volume_rule=""):
    size = f'size="{volume}"' if dimension != 0 else ""
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="species_rate"><listOfCompartments>
<compartment id="C" {size} spatialDimensions="{dimension}" constant="{'false' if volume_rule else 'true'}"/>
</listOfCompartments><listOfSpecies>
<species id="S" compartment="C" initialAmount="1" hasOnlySubstanceUnits="{str(amount_symbol).lower()}" boundaryCondition="false" constant="false"/>
</listOfSpecies><listOfRules>
<rateRule variable="S"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.4</cn></math></rateRule>
{volume_rule}</listOfRules></model></sbml>"""


def execute(xml):
    from bionetgen import BioNetGenModel
    from bionetgen.atomizer.modern import Atomizer

    converted = Atomizer(atomize=False, quiet_mode=True).atomize(xml)
    assert converted.success, converted.error
    return BioNetGenModel(cpp.parse_string(converted.bngl)).simulate(
        method="ode", t_end=2, n_steps=1, rtol=1e-10, atol=1e-14
    )


@pytest.mark.parametrize("volume", [0.5, 1.75, 0.93])
@pytest.mark.parametrize("amount_symbol", [False, True])
def test_static_volume_converts_only_concentration_rate_rule(volume, amount_symbol):
    actual = execute(source(volume=volume, amount_symbol=amount_symbol))
    expected = 1 + 0.4 * 2 * (1 if amount_symbol else volume)
    assert actual.observables["S_amt"][-1] == pytest.approx(expected, rel=1e-7)


def test_zero_dimensional_rate_rule_is_amount_valued():
    assert execute(source(dimension=0)).observables["S_amt"][-1] == pytest.approx(1.8)


def test_rate_ruled_volume_uses_the_amount_product_rule():
    rule = '<rateRule variable="C"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.25</cn></math></rateRule>'
    actual = execute(source(volume_rule=rule))
    # N = concentration * V; C(0)=1/0.5, dC/dt=.4, V=.5+.25t.
    assert actual.observables["S_amt"][-1] == pytest.approx((2 + 0.4 * 2) * 1, rel=1e-7)


def test_assignment_ruled_volume_requires_an_explicit_derivative_contract():
    from bionetgen.atomizer.modern import Atomizer

    rule = '<assignmentRule variable="C"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><cn>0.5</cn><apply><times/><cn>0.25</cn><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply></apply></math></assignmentRule>'
    actual = Atomizer(atomize=False, quiet_mode=True).atomize(source(volume_rule=rule))
    assert not actual.success
    assert (
        "concentration rate rule requires an explicit compartment derivative"
        in actual.error
    )


@pytest.mark.parametrize("amount_symbol,dimension", [(False, 3), (True, 3), (False, 0)])
def test_species_rule_agrees_with_independent_roadrunner(amount_symbol, dimension):
    roadrunner = pytest.importorskip("roadrunner")
    xml = source(amount_symbol=amount_symbol, dimension=dimension)
    oracle = roadrunner.RoadRunner(xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-14
    expected = oracle.simulate(0, 2, 2, selections=["time", "S"])
    assert execute(xml).observables["S_amt"][-1] == pytest.approx(
        expected[-1, 1], rel=1e-7
    )


def test_dynamic_volume_product_rule_agrees_with_independent_roadrunner():
    roadrunner = pytest.importorskip("roadrunner")
    rule = '<rateRule variable="C"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.25</cn></math></rateRule>'
    xml = source(volume_rule=rule)
    oracle = roadrunner.RoadRunner(xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-14
    expected = oracle.simulate(0, 2, 2, selections=["time", "S"])
    assert execute(xml).observables["S_amt"][-1] == pytest.approx(
        expected[-1, 1], rel=1e-7
    )
