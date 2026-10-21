"""Regression tests for the SBML ``fast`` reaction lowering.

SBML Level 2 and Level 3 Version 1 Section 4.11 define a reaction whose
``fast`` attribute is true by a pseudo steady state of the fast subsystem:
the fast reactions "are considered to be instantaneous relative to the slow
reactions", so the model's system of equations is constructed with the fast
subsystem in equilibrium.  The Atomizer lowers the one shape of fast
reaction whose pseudo steady state it can express exactly and refuses the
rest with the reason the reduction is impossible.
"""

from __future__ import annotations

import numpy as np
import pytest

from bionetgen import BioNetGenModel
from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.parser import SBMLParser

FAST_HEADER = (
    '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
    'level="3" version="1">'
)


def _model(body: str, conversion_factor: str = "") -> str:
    model_attributes = 'id="fast_model" timeUnits="time"'
    if conversion_factor:
        model_attributes += f' conversionFactor="{conversion_factor}"'
    return FAST_HEADER + f"<model {model_attributes}>" + body + "</model></sbml>"


def _fast_warnings(xml: str):
    model = SBMLParser().parse(xml)
    return [
        warning
        for warning in model.import_warnings
        if warning.category == "fastReaction"
    ]


def _simulate(bngl: str, sample_times):
    from bionetgen import _bionetgen_cpp as cpp

    model = BioNetGenModel(cpp.parse_string(bngl))
    return model.simulate(
        method="ode",
        t_start=0.0,
        t_end=max(sample_times),
        n_steps=0,
        sample_times=list(sample_times),
        rtol=1e-10,
        atol=1e-14,
    )


def test_fast_reaction_is_reduced_to_its_pseudo_steady_state():
    """A fast reaction proportional to one species is held at zero."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A1" compartment="C" initialAmount="2" constant="false"/>
          <species id="A2" compartment="C" initialAmount="3" constant="false"/>
          <species id="A3" compartment="C" initialAmount="4" constant="false"/>
          <species id="A4" compartment="C" initialAmount="1" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Kf1" value="1" constant="true"/>
          <parameter id="Kf" value="1" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="reaction1" reversible="false" fast="true">
            <listOfReactants>
              <speciesReference species="A4" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>A4</ci><ci>C</ci><ci>Kf1</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="reaction2" reversible="false" fast="false">
            <listOfReactants>
              <speciesReference species="A1" stoichiometry="1" constant="true"/>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A3" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>A1</ci><ci>A2</ci><ci>C</ci><ci>Kf</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "info"
    assert "reduces to one" in warnings[0].message
    assert 'species "A4" is held at zero' in warnings[0].message

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=3, n_steps=50).atomize(
        xml
    )
    assert atomized.success, atomized.error
    # The fast reaction is replaced by the steady state, so it is gone.
    assert "reaction1:" not in atomized.bngl
    assert "@C:M_A4() 0" in atomized.bngl
    assert "@C:M_A2() 4" in atomized.bngl
    assert "reaction2" in atomized.bngl


def test_reduced_fast_reaction_reproduces_the_official_reference():
    """The reduced model reproduces the official suite's reference trajectory.

    The values are the published reference of the SBML Test Suite case 00986,
    whose fast reaction ``A -> B`` goes to completion instantly.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="default_compartment" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="default_compartment" initialAmount="1"
                   hasOnlySubstanceUnits="true" constant="false"/>
          <species id="B" compartment="default_compartment" initialAmount="0"
                   hasOnlySubstanceUnits="true" constant="false"/>
          <species id="C" compartment="default_compartment" initialAmount="0"
                   hasOnlySubstanceUnits="true" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="fast" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="A" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="B" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>1</cn><ci>A</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="slow" reversible="true" fast="false">
            <listOfReactants>
              <speciesReference species="B" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="C" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>1</cn><ci>B</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=2, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "fast:" not in atomized.bngl

    reference = [
        (0.0, 1.0, 0.0),
        (0.2, 0.818730753, 0.181269247),
        (0.4, 0.670320046, 0.329679954),
        (0.6, 0.548811636, 0.451188364),
        (0.8, 0.449328964, 0.550671036),
        (1.0, 0.367879441, 0.632120559),
        (1.2, 0.301194212, 0.698805788),
        (1.4, 0.246596964, 0.753403036),
        (1.6, 0.201896518, 0.798103482),
        (1.8, 0.165298888, 0.834701112),
        (2.0, 0.135335283, 0.864664717),
    ]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    expected_b = np.array([row[1] for row in reference])
    expected_c = np.array([row[2] for row in reference])
    assert np.allclose(result.observables["B_amt"], expected_b, rtol=1e-6, atol=1e-9)
    assert np.allclose(result.observables["C_amt"], expected_c, rtol=1e-6, atol=1e-9)
    assert np.allclose(result.observables["A_amt"], 0.0, atol=1e-12)


def test_fast_reaction_rate_proportional_to_the_product_reduces_in_reverse():
    """A negative rate proportional to the product consumes the product."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" constant="false"/>
          <species id="S2" compartment="C" initialAmount="3" constant="false"/>
        </listOfSpecies>
        <listOfFunctionDefinitions>
          <functionDefinition id="isneg">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <lambda><cn>-0.01</cn></lambda>
            </math>
          </functionDefinition>
        </listOfFunctionDefinitions>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S2</ci><apply><ci>isneg</ci></apply></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "info"
    assert 'species "S2" is held at zero' in warnings[0].message

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl
    assert "@C:M_S1() 5" in atomized.bngl
    assert "@C:M_S2() 0" in atomized.bngl


def test_reversible_fast_reaction_is_held_on_its_algebraic_balance():
    """A fast reaction that balances its two species is held on the balance.

    The pseudo steady state of a fast reaction whose rate is the difference
    of a term proportional to the reactant and a term proportional to the
    product is the algebraic balance between the two species.  The slow
    reactions then move along that balance, so the eliminated species
    changes at a scaled rate.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A1" compartment="C" initialAmount="2" constant="false"/>
          <species id="A2" compartment="C" initialAmount="3" constant="false"/>
          <species id="A3" compartment="C" initialAmount="4" constant="false"/>
          <species id="A4" compartment="C" initialAmount="1" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Kf1" value="1" constant="true"/>
          <parameter id="Kr1" value="2" constant="true"/>
          <parameter id="Kf" value="1" constant="true"/>
          <parameter id="Kr" value="2" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="fasterReaction" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="A4" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <times/>
                  <apply><minus/>
                    <apply><times/><ci>Kf1</ci><ci>A4</ci></apply>
                    <apply><times/><ci>Kr1</ci><ci>A2</ci></apply>
                  </apply>
                  <ci>C</ci>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="slowerReaction1" reversible="true" fast="false">
            <listOfReactants>
              <speciesReference species="A1" stoichiometry="1" constant="true"/>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A3" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <times/>
                  <apply><minus/>
                    <apply><times/><ci>Kf</ci><ci>A1</ci><ci>A2</ci></apply>
                    <apply><times/><ci>Kr</ci><ci>A3</ci></apply>
                  </apply>
                  <ci>C</ci>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "info"
    assert "reduces to one" in warnings[0].message
    assert "held on the balance" in warnings[0].message

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=50).atomize(
        xml
    )
    assert atomized.success, atomized.error
    # The fast reaction is replaced by the balance, so it is gone.
    assert "fasterReaction:" not in atomized.bngl
    # The balance Kf1 * A4 = Kr1 * A2 holds at the first output point.
    assert "@C:M_A2() 1.3333333333333333" in atomized.bngl
    assert "@C:M_A4() 2.6666666666666665" in atomized.bngl


def test_balanced_fast_reaction_reproduces_the_official_reference():
    """The balanced reduction reproduces the official suite's reference.

    The values are the published reference of the SBML Test Suite case
    00870, whose fast reaction ``A4 <-> A2`` is held on the balance
    ``Kf1 * A4 = Kr1 * A2`` while the slow reaction consumes ``A2``.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A1" compartment="C" initialAmount="2" constant="false"/>
          <species id="A2" compartment="C" initialAmount="3" constant="false"/>
          <species id="A3" compartment="C" initialAmount="4" constant="false"/>
          <species id="A4" compartment="C" initialAmount="1" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Kf1" value="1" constant="true"/>
          <parameter id="Kr1" value="2" constant="true"/>
          <parameter id="Kf" value="1" constant="true"/>
          <parameter id="Kr" value="2" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="fasterReaction" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="A4" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <times/>
                  <apply><minus/>
                    <apply><times/><ci>Kf1</ci><ci>A4</ci></apply>
                    <apply><times/><ci>Kr1</ci><ci>A2</ci></apply>
                  </apply>
                  <ci>C</ci>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="slowerReaction1" reversible="true" fast="false">
            <listOfReactants>
              <speciesReference species="A1" stoichiometry="1" constant="true"/>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A3" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <times/>
                  <apply><minus/>
                    <apply><times/><ci>Kf</ci><ci>A1</ci><ci>A2</ci></apply>
                    <apply><times/><ci>Kr</ci><ci>A3</ci></apply>
                  </apply>
                  <ci>C</ci>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=50).atomize(
        xml
    )
    assert atomized.success, atomized.error

    reference = [
        (0.0, 2.0, 1.333333333333333, 4.0, 2.666666666666667),
        (
            0.5,
            3.092713521845432,
            1.697571173948477,
            2.907286478154568,
            3.395142347896955,
        ),
        (
            1.0,
            3.200252057250727,
            1.733417352416909,
            2.799747942749273,
            3.466834704833818,
        ),
    ]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    for index, name in enumerate(("A1", "A2", "A3", "A4"), start=1):
        expected = np.array([row[index] for row in reference])
        # The suite's own tolerance for this case.
        assert np.allclose(
            result.observables[f"{name}_amt"], expected, rtol=1e-4, atol=1e-2
        ), name


def test_fast_reaction_rate_over_an_unconverted_species_is_refused():
    """A fast reaction that reads a third species cannot be reduced."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A4" compartment="C" initialAmount="1" constant="false"/>
          <species id="A2" compartment="C" initialAmount="3" constant="false"/>
          <species id="A5" compartment="C" initialAmount="2" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Kf1" value="1" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="fasterReaction" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="A4" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="A2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>Kf1</ci><ci>A4</ci><ci>A5</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "approximated"
    assert "is marked fast" in warnings[0].message
    assert "does not convert" in warnings[0].message
    assert "no fast-equilibrium solve" in warnings[0].message

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    # The reaction is kept, but the model is not claimed to be equivalent.
    assert "fasterReaction" in atomized.bngl


def test_fast_reaction_read_by_a_delay_expression_is_refused():
    """A delay reports the declared initial value, so the reduction is unsafe."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" constant="false"/>
          <species id="S2" compartment="C" initialAmount="3" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="P1" value="0" constant="false"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S1</ci><cn>1</cn></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfRules>
          <assignmentRule variable="P1">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <delay/>
                <ci>S1</ci>
                <cn>1.5</cn>
              </apply>
            </math>
          </assignmentRule>
        </listOfRules>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "approximated"
    assert "read by a delay expression" in warnings[0].message


def test_several_fast_reactions_are_reduced_independently():
    """Independent fast reactions each reduce to their own steady state."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" constant="false"/>
          <species id="S2" compartment="C" initialAmount="3" constant="false"/>
          <species id="S3" compartment="C" initialAmount="4" constant="false"/>
          <species id="S4" compartment="C" initialAmount="5" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>1</cn><ci>S1</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="J1" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S3" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S4" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>1</cn><ci>S3</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 2
    assert {warning.severity for warning in warnings} == {"info"}
    for warning in warnings:
        assert "reduces to one" in warning.message

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=1, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl
    assert "J1:" not in atomized.bngl
    assert "@C:M_S1() 0" in atomized.bngl
    assert "@C:M_S2() 5" in atomized.bngl
    assert "@C:M_S3() 0" in atomized.bngl
    assert "@C:M_S4() 9" in atomized.bngl


def test_two_fast_reactions_sharing_a_species_are_refused():
    """Two fast reactions that share a species are one balance."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" constant="false"/>
          <species id="S2" compartment="C" initialAmount="3" constant="false"/>
          <species id="S3" compartment="C" initialAmount="4" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>1</cn><ci>S1</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="J1" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S3" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><cn>1</cn><ci>S2</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 2
    assert {warning.severity for warning in warnings} == {"approximated"}
    for warning in warnings:
        assert "multi-species balance" in warning.message


def test_fast_reaction_of_a_species_used_elsewhere_is_refused():
    """The consumed species must not also take part in another reaction."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" constant="false"/>
          <species id="S2" compartment="C" initialAmount="3" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S1</ci><cn>1</cn></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="J1" reversible="true" fast="false">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S1</ci><cn>2</cn></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "approximated"
    assert 'also takes part in reaction "J1"' in warnings[0].message


def test_fast_reaction_rate_over_both_species_runs_to_completion():
    """A rate proportional to both converted species vanishes with one of them.

    A rate of the form ``c * X * Y`` is zero exactly when one of the two
    species is zero, so the infinitely fast relaxation holds that species at
    zero and lets the other absorb its amount.  The sign of ``c`` says which
    of the two the reaction runs towards.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="default_compartment" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="default_compartment" initialConcentration="5"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="default_compartment" initialConcentration="5"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
              </math>
              <listOfLocalParameters>
                <localParameter id="k1" value="-1"/>
              </listOfLocalParameters>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "info"
    assert 'species "S2" is held at zero' in warnings[0].message

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl
    assert "@default_compartment:M_S1() 10" in atomized.bngl
    assert "@default_compartment:M_S2() 0" in atomized.bngl

    # The published reference of the SBML Test Suite case 01399.
    reference = [(0.0, 10.0, 0.0), (5.0, 10.0, 0.0), (10.0, 10.0, 0.0)]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    assert np.allclose(
        result.observables["S1_amt"], [row[1] for row in reference], atol=1e-9
    )
    assert np.allclose(
        result.observables["S2_amt"], [row[2] for row in reference], atol=1e-9
    )


def test_fast_reaction_with_a_non_unity_stoichiometry_runs_to_completion():
    """The absorbed amount follows the stoichiometry ratio.

    The published reference of the SBML Test Suite case 01571: the fast
    reaction consumes two ``S1`` per ``S2``, so the three units of ``S1``
    produce one and a half units of ``S2``.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialConcentration="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="C" initialConcentration="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfRules>
          <assignmentRule variable="S1_stoich">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <cn type="integer"> 2 </cn>
            </math>
          </assignmentRule>
        </listOfRules>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference id="S1_stoich" species="S1" stoichiometry="1"
                                constant="false"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S1</ci><ci>S2</ci><cn>0.1</cn></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl

    reference = [(0.0, 0.0, 4.5), (5.0, 0.0, 4.5), (10.0, 0.0, 4.5)]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    assert np.allclose(
        result.observables["S1_amt"], [row[1] for row in reference], atol=1e-9
    )
    assert np.allclose(
        result.observables["S2_amt"], [row[2] for row in reference], atol=1e-9
    )


def test_fast_reaction_with_a_conversion_factor_runs_to_completion():
    """A conversion factor scales the amount a reaction moves.

    The published reference of the SBML Test Suite case 01544: the species
    ``S1`` carries the conversion factor ``s1_cf`` and the model carries
    ``m_cf``, so the two units of ``S1`` move one and a fifth units of ``S2``.
    """

    xml = _model(
        """
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="2" conversionFactor="s1_cf"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="C" initialAmount="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="m_cf" value="3" constant="true"/>
          <parameter id="s1_cf" value="5" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S1</ci><cn>0.01</cn></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """,
        conversion_factor="m_cf",
    )

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl

    reference = [(0.0, 0.0, 4.2), (5.0, 0.0, 4.2), (10.0, 0.0, 4.2)]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    assert np.allclose(
        result.observables["S1_amt"], [row[1] for row in reference], atol=1e-9
    )
    assert np.allclose(
        result.observables["S2_amt"], [row[2] for row in reference], atol=1e-9
    )


def test_several_fast_reactions_reproduce_the_official_reference():
    """Independent fast reactions each reduce to their own steady state.

    The published reference of the SBML Test Suite case 01569: the first
    fast reaction runs forwards and holds ``S1`` at zero, the second runs
    backwards and holds ``S4`` at zero.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialConcentration="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="C" initialConcentration="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S3" compartment="C" initialConcentration="4"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S4" compartment="C" initialConcentration="4"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k1" value="0" constant="false"/>
          <parameter id="k2" value="0" constant="false"/>
        </listOfParameters>
        <listOfInitialAssignments>
          <initialAssignment symbol="k1">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/><cn>0.5</cn>
                <csymbol encoding="text"
                         definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
              </apply>
            </math>
          </initialAssignment>
          <initialAssignment symbol="k2">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/>
                <csymbol encoding="text"
                         definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
                <cn>0.5</cn>
              </apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S1</ci><ci>S2</ci><ci>k1</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="J1" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S3" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S4" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S3</ci><ci>S4</ci><ci>k2</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl
    assert "J1:" not in atomized.bngl

    reference = [
        (0.0, 0.0, 6.0, 8.0, 0.0),
        (5.0, 0.0, 6.0, 8.0, 0.0),
        (10.0, 0.0, 6.0, 8.0, 0.0),
    ]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    for index, name in enumerate(("S1", "S2", "S3", "S4"), start=1):
        assert np.allclose(
            result.observables[f"{name}_amt"],
            [row[index] for row in reference],
            atol=1e-9,
        ), name


def test_fast_reaction_rate_constant_from_an_algebraic_rule_is_reduced():
    """A rate constant an algebraic rule fixes is a constant.

    The published reference of the SBML Test Suite case 01567: the
    algebraic rule ``k + 3 = 0`` fixes the rate constant at ``-3``, so the
    fast reaction runs backwards and holds ``S2`` at zero.
    """

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialConcentration="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
          <species id="S2" compartment="C" initialConcentration="3"
                   hasOnlySubstanceUnits="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0" constant="false"/>
        </listOfParameters>
        <listOfRules>
          <algebraicRule>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><plus/><ci>k</ci><cn>3</cn></apply>
            </math>
          </algebraicRule>
        </listOfRules>
        <listOfReactions>
          <reaction id="J0" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="S1" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="S2" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>S2</ci><ci>k</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=10, n_steps=10).atomize(
        xml
    )
    assert atomized.success, atomized.error
    assert "J0:" not in atomized.bngl

    reference = [(0.0, 6.0, 0.0), (5.0, 6.0, 0.0), (10.0, 6.0, 0.0)]
    times = [row[0] for row in reference]
    result = _simulate(atomized.bngl, times)
    assert np.allclose(
        result.observables["S1_amt"], [row[1] for row in reference], atol=1e-9
    )
    assert np.allclose(
        result.observables["S2_amt"], [row[2] for row in reference], atol=1e-9
    )


@pytest.mark.parametrize("level", [2, 3])
def test_level_two_and_three_version_one_models_are_reduced(level: int):
    """The attribute means the same thing in Level 2 and Level 3 Version 1."""

    namespace = (
        "http://www.sbml.org/sbml/level2/version4"
        if level == 2
        else "http://www.sbml.org/sbml/level3/version1/core"
    )
    version = "4" if level == 2 else "1"
    xml = (
        f'<sbml xmlns="{namespace}" level="{level}" version="{version}">'
        '<model id="fast_model">'
        '<listOfCompartments><compartment id="C" size="1"/></listOfCompartments>'
        "<listOfSpecies>"
        '<species id="A" compartment="C" initialAmount="1"/>'
        '<species id="B" compartment="C" initialAmount="0"/>'
        "</listOfSpecies>"
        "<listOfReactions>"
        '<reaction id="fast" reversible="true" fast="true">'
        '<listOfReactants><speciesReference species="A"/></listOfReactants>'
        '<listOfProducts><speciesReference species="B"/></listOfProducts>'
        '<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><times/><cn>1</cn><ci>A</ci></apply></math></kineticLaw>"
        "</reaction>"
        "</listOfReactions>"
        "</model></sbml>"
    )

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "info"
    assert 'species "A" is held at zero' in warnings[0].message
