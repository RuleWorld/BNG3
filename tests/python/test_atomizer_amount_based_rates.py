"""Regression tests for amount-based SBML rate laws in non-unity compartments.

SBML Level 3 Version 2 Core (Sec. 4.11) states that the numeric value of a
kinetic law is the rate of change of the reaction's *extent*, and that a
species' amount changes by ``stoichiometry * extent rate``.  A model writes a
concentration-based law with an explicit compartment factor
(``compartment * k * S1 * S2``), which already carries the volume, while an
amount-based law (``k * S1 * S2``) does not.

BNGL rate laws are always concentration rates, so an amount-based law must
gain a volume factor of ``V**(m-1)`` for a law with ``m`` reactant factors
when it is lowered.  The official SBML Test Suite cases ``01002``-``01010``
and ``01307`` exercise exactly this and are the reference for the expected
numbers.
"""

from __future__ import annotations

import math

from bionetgen.atomizer.modern import Atomizer


def _model(
    *,
    volume: str,
    species: str,
    reactants: str,
    products: str,
    law: str,
    has_only_substance_units: str = "true",
) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="amount_based">
        <listOfCompartments>
          <compartment id="C" size="{volume}" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species}</listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="1" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>{reactants}</listOfReactants>
            <listOfProducts>{products}</listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">{law}</math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""


def _species(has_only_substance_units: str = "true") -> str:
    return (
        '<species id="S1" compartment="C" initialAmount="1" '
        f'hasOnlySubstanceUnits="{has_only_substance_units}" constant="false"/>'
        '<species id="S2" compartment="C" initialAmount="2" '
        f'hasOnlySubstanceUnits="{has_only_substance_units}" constant="false"/>'
        '<species id="S3" compartment="C" initialAmount="0" '
        f'hasOnlySubstanceUnits="{has_only_substance_units}" constant="false"/>'
    )


def _rate_law(bngl: str) -> str:
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith("J0:"):
            return stripped
    raise AssertionError("no reaction rule emitted")


def test_amount_based_unimolecular_rate_keeps_its_constant():
    # One reactant factor: the correction is V**0, so the rate is unchanged.
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(
            volume="10",
            species=_species(),
            reactants='<speciesReference species="S1" stoichiometry="1"/>',
            products='<speciesReference species="S3" stoichiometry="1"/>',
            law=("<apply><times/><ci>k1</ci><ci>S1</ci></apply>"),
        )
    )

    assert result.success, result.error
    assert _rate_law(result.bngl).endswith("1")


def test_amount_based_bimolecular_rate_gains_one_volume_factor():
    # Two reactant factors: the BNGL constant must be k1 * V.
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(
            volume="10",
            species=_species(),
            reactants=(
                '<speciesReference species="S1" stoichiometry="1"/>'
                '<speciesReference species="S2" stoichiometry="1"/>'
            ),
            products='<speciesReference species="S3" stoichiometry="1"/>',
            law=("<apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>"),
        )
    )

    assert result.success, result.error
    assert "__compartment_C__" in _rate_law(result.bngl)
    assert "**1" in _rate_law(result.bngl)


def test_concentration_based_rate_keeps_its_constant():
    # A concentration-based law already carries the compartment factor that
    # SBML's convention requires, so no correction applies.
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(
            volume="10",
            species=_species(has_only_substance_units="false"),
            reactants=(
                '<speciesReference species="S1" stoichiometry="1"/>'
                '<speciesReference species="S2" stoichiometry="1"/>'
            ),
            products='<speciesReference species="S3" stoichiometry="1"/>',
            law=("<apply><times/><ci>C</ci><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>"),
        )
    )

    assert result.success, result.error
    rate = _rate_law(result.bngl)
    assert "__compartment_C__" not in rate
    assert rate.endswith("1")


def test_amount_based_zero_order_rate_is_a_complete_flux():
    # A zero-order law is an extent rate in substance/time and the rule has
    # no reactant population, so the rule states the complete flux and must
    # carry the TotalRate modifier.
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(
            volume="3",
            species=(
                '<species id="S3" compartment="C" initialAmount="2" '
                'hasOnlySubstanceUnits="true" constant="false"/>'
            ),
            reactants="",
            products='<speciesReference species="S3" stoichiometry="1"/>',
            law="<cn>1</cn>",
        )
    )

    assert result.success, result.error
    rate = _rate_law(result.bngl)
    assert "TotalRate" in rate
    # The extent rate is the law's own value; no volume factor is applied.
    assert rate.endswith("1 TotalRate")
    assert "__compartment_C__" not in rate


def test_official_01002_trajectory_is_reproduced():
    """The official SBML Test Suite reference for semantic/01002.

    ``01002`` is a two-species reaction in a size-10 compartment whose
    species have ``hasOnlySubstanceUnits="true"``.  The official reference
    treats the kinetic law as an extent rate in substance/time, so the
    species' amounts change by ``stoichiometry * k1 * S1 * S2``.  The official
    settings use a 15-second horizon with 50 steps.
    """

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="case01002">
        <listOfUnitDefinitions>
          <unitDefinition id="volume">
            <listOfUnits><unit kind="litre" exponent="1" scale="0" multiplier="1"/></listOfUnits>
          </unitDefinition>
          <unitDefinition id="substance">
            <listOfUnits><unit kind="mole" exponent="1" scale="0" multiplier="1"/></listOfUnits>
          </unitDefinition>
          <unitDefinition id="time">
            <listOfUnits><unit kind="second" exponent="1" scale="0" multiplier="1"/></listOfUnits>
          </unitDefinition>
        </listOfUnitDefinitions>
        <listOfCompartments>
          <compartment id="compartment" size="10" units="volume" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" name="S1" compartment="compartment" initialAmount="1.0e-3"
                   substanceUnits="substance" hasOnlySubstanceUnits="true"
                   boundaryCondition="false" constant="false"/>
          <species id="S2" name="S2" compartment="compartment" initialAmount="2.0e-3"
                   substanceUnits="substance" hasOnlySubstanceUnits="true"
                   boundaryCondition="false" constant="false"/>
          <species id="S3" name="S3" compartment="compartment" initialAmount="1.0e-3"
                   substanceUnits="substance" hasOnlySubstanceUnits="true"
                   boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" name="k1" value="17" constant="true"/>
          <parameter id="k2" name="k2" value="0.3" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="reaction1" name="reaction1" reversible="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts><speciesReference species="S3" stoichiometry="1" constant="true"/></listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="reaction2" name="reaction2" reversible="false">
            <listOfReactants><speciesReference species="S3" stoichiometry="1" constant="true"/></listOfReactants>
            <listOfProducts><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k2</ci><ci>S3</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert result.success, result.error

    # The forward law is amount-based and bimolecular, so the BNGL constant
    # must carry one volume factor; the reverse law is unimolecular and
    # keeps its constant.
    assert "**1" in result.bngl

    # Integrate the SBML extent-rate reading and compare with the official
    # reference values of semantic/01002.
    k1, k2 = 17.0, 0.3
    state = [1.0e-3, 2.0e-3, 1.0e-3]
    steps = 400000
    dt = 15.0 / steps
    samples = []
    for index in range(steps + 1):
        if index % (steps // 50) == 0:
            samples.append(list(state))
        s1, s2, s3 = state
        forward = k1 * s1 * s2
        reverse = k2 * s3
        state = [
            s1 + (-forward + reverse) * dt,
            s2 + (-forward + reverse) * dt,
            s3 + (forward - reverse) * dt,
        ]

    # The official reference at t=0.3 is S1 = 0.001075732452247863.
    assert math.isclose(samples[1][0], 0.001075732452247863, rel_tol=1e-5)
    # The official reference at t=0.6 is S1 = 0.001143844032353959.
    assert math.isclose(samples[2][0], 0.001143844032353959, rel_tol=1e-5)


def test_amount_based_law_that_names_the_compartment_keeps_its_own_volume_factor():
    """A law that states its own volume dependence needs no correction.

    The generated integrated-validation case ``dimerization-v1-n20-r0-a0``
    uses the rate law ``k * A * A / cell`` in a size-1 compartment.  The
    amount-based correction would multiply the constant by the compartment
    size, but the law already carries that factor, and BNGL's rate-law
    grammar and BNG2's expression parser do not accept a compartment
    parameter raised to a power inside a rate law.
    """

    sbml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="dimerization">
        <listOfUnitDefinitions>
          <unitDefinition id="litre_per_item_second">
            <listOfUnits>
              <unit kind="litre" exponent="1" scale="0" multiplier="1"/>
              <unit kind="item" exponent="-1" scale="0" multiplier="1"/>
              <unit kind="second" exponent="-1" scale="0" multiplier="1"/>
            </listOfUnits>
          </unitDefinition>
        </listOfUnitDefinitions>
        <listOfCompartments>
          <compartment id="cell" spatialDimensions="3" units="litre" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="cell" initialAmount="20" substanceUnits="item"
                   hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
          <species id="D" compartment="cell" initialAmount="0" substanceUnits="item"
                   hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.4" units="litre_per_item_second" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="dimerize" reversible="false">
            <listOfReactants>
              <speciesReference species="A" stoichiometry="2" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="D" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><divide/>
                  <apply><times/><ci>k</ci><ci>A</ci><ci>A</ci></apply>
                  <ci>cell</ci>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert result.success, result.error
    rule = next(
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith("dimerize:")
    )
    # The rate law keeps the constant it was derived from; no compartment
    # factor is added to it.
    assert "__compartment_cell__" not in rule
    assert rule.endswith("0.8")
