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


def _model(body: str) -> str:
    return (
        FAST_HEADER
        + '<model id="fast_model" timeUnits="time">'
        + body
        + "</model></sbml>"
    )


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


def test_fast_reaction_rate_over_both_converted_species_is_refused():
    """A fast reaction that balances its two species cannot be reduced."""

    xml = _model("""
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="A4" compartment="C" initialAmount="1" constant="false"/>
          <species id="A2" compartment="C" initialAmount="3" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Kf1" value="1" constant="true"/>
          <parameter id="Kr1" value="2" constant="true"/>
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
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 1
    assert warnings[0].severity == "approximated"
    assert "is marked fast" in warnings[0].message
    assert "depends on both species it converts" in warnings[0].message
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


def test_several_fast_reactions_are_refused():
    """More than one fast reaction is not a single balance."""

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
                <apply><times/><ci>S1</ci><cn>1</cn></apply>
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
                <apply><times/><ci>S3</ci><cn>1</cn></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        """)

    warnings = _fast_warnings(xml)
    assert len(warnings) == 2
    assert {warning.severity for warning in warnings} == {"approximated"}
    for warning in warnings:
        assert "more than one fast reaction" in warning.message


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
