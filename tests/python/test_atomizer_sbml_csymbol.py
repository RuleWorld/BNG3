"""Regression tests for SBML ``csymbol`` semantics and initial assignments.

SBML Level 3 Version 2 Core defines the built-in MathML ``csymbol`` elements
by their ``definitionURL``; the element text is only a display label and may
be empty or misleading.  The specification also fixes the value of the
``avogadro`` symbol at 6.02214179e+23 and requires every reader of this SBML
version to use exactly that number.

Separately, SBML evaluates each ``initialAssignment`` once, at the start of
the simulation (where the start time is zero), so a static initial assignment
for a parameter fixes that parameter's value for the whole run.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import Atomizer, SBMLParser

SBML_AVOGADRO = 6.02214179e23


def _model(body: str, parameters: str = "") -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="csymbol_model">
        {parameters}
        {body}
      </model>
    </sbml>"""


def _csymbol(url: str, text: str) -> str:
    return (
        f'<csymbol encoding="text" '
        f'definitionURL="http://www.sbml.org/sbml/symbols/{url}">{text}</csymbol>'
    )


def test_avogadro_csymbol_value_follows_the_specification_not_the_element_text():
    # The text says "time" but the definitionURL says "avogadro"; SBML keys
    # the symbol on the definitionURL.
    model = SBMLParser().parse(
        _model(
            f"""<listOfInitialAssignments>
              <initialAssignment symbol="p">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  {_csymbol("avogadro", "time")}
                </math>
              </initialAssignment>
            </listOfInitialAssignments>""",
            '<listOfParameters><parameter id="p" value="0" constant="true"/></listOfParameters>',
        )
    )

    assert not model.initial_assignments
    assert model.parameters["p"].value == pytest.approx(SBML_AVOGADRO, rel=1e-15)
    # BNGL's __Avogadro__ is BNG's molecule-count factor and is 1; the SBML
    # symbol is the physical constant and must not be folded into it.
    assert model.parameters["p"].value != 1.0


def test_avogadro_csymbol_is_not_the_2019_si_redefinition():
    # 6.02214076e23 is the 2019 SI redefinition.  SBML Level 3 Version 2 Core
    # was published in 2019-03 and specifies 6.02214179e+23; every reader of
    # this SBML version must use that value.
    assert SBML_AVOGADRO == 6.02214179e23
    assert SBML_AVOGADRO != 6.02214076e23


def test_avogadro_csymbol_ignores_an_empty_element_body():
    model = SBMLParser().parse(
        _model(
            f"""<listOfInitialAssignments>
              <initialAssignment symbol="p">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  {_csymbol("avogadro", "")}
                </math>
              </initialAssignment>
            </listOfInitialAssignments>""",
            '<listOfParameters><parameter id="p" value="0" constant="true"/></listOfParameters>',
        )
    )

    assert model.parameters["p"].value == pytest.approx(SBML_AVOGADRO, rel=1e-15)


def test_time_csymbol_ignores_an_element_body_naming_another_symbol():
    model = SBMLParser().parse(
        _model(
            f"""<listOfInitialAssignments>
              <initialAssignment symbol="p">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  {_csymbol("time", "avogadro")}
                </math>
              </initialAssignment>
            </listOfInitialAssignments>""",
            '<listOfParameters><parameter id="p" value="0" constant="true"/></listOfParameters>',
        )
    )

    # SBML assumes a zero start time, so the time symbol is 0 while the
    # initial values are established.
    assert not model.initial_assignments
    assert model.parameters["p"].value == 0.0


def test_operator_position_csymbol_uses_the_definition_url():
    model = SBMLParser().parse(
        _model(
            f"""<listOfInitialAssignments>
              <initialAssignment symbol="p">
                <math xmlns="http://www.w3.org/1998/Math/MathML">
                  <apply><times/>
                    {_csymbol("avogadro", "time")}
                    <cn>2</cn>
                  </apply>
                </math>
              </initialAssignment>
            </listOfInitialAssignments>""",
            '<listOfParameters><parameter id="p" value="0" constant="true"/></listOfParameters>',
        )
    )

    assert model.parameters["p"].value == pytest.approx(2.0 * SBML_AVOGADRO, rel=1e-15)


def test_static_parameter_initial_assignment_is_folded_to_a_fixed_value():
    model = SBMLParser().parse(_model("""<listOfParameters>
                 <parameter id="k" value="3" constant="true"/>
                 <parameter id="p" value="0" constant="false"/>
               </listOfParameters>
               <listOfInitialAssignments>
                 <initialAssignment symbol="p">
                   <math xmlns="http://www.w3.org/1998/Math/MathML">
                     <apply><times/><ci>k</ci><cn>2</cn></apply>
                   </math>
                 </initialAssignment>
               </listOfInitialAssignments>"""))

    assert not model.initial_assignments
    assert model.parameters["p"].value == 6.0


def test_static_parameter_initial_assignment_is_not_emitted_as_a_runtime_function():
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model("""<listOfParameters>
                 <parameter id="k" value="3" constant="true"/>
                 <parameter id="p" value="0" constant="false"/>
               </listOfParameters>
               <listOfInitialAssignments>
                 <initialAssignment symbol="p">
                   <math xmlns="http://www.w3.org/1998/Math/MathML">
                     <apply><times/><ci>k</ci><cn>2</cn></apply>
                   </math>
                 </initialAssignment>
               </listOfInitialAssignments>""")
    )

    assert result.success, result.error
    assert "p 6" in result.bngl
    assert "p() =" not in result.bngl


def test_initial_assignment_that_depends_on_a_species_is_not_folded():
    model = SBMLParser().parse(_model("""<listOfCompartments>
                 <compartment id="C" size="1" constant="true"/>
               </listOfCompartments>
               <listOfSpecies>
                 <species id="S1" compartment="C" initialAmount="1"
                          hasOnlySubstanceUnits="true" constant="false"/>
               </listOfSpecies>
               <listOfParameters>
                 <parameter id="p" value="0" constant="false"/>
               </listOfParameters>
               <listOfInitialAssignments>
                 <initialAssignment symbol="p">
                   <math xmlns="http://www.w3.org/1998/Math/MathML">
                     <apply><times/><ci>S1</ci><cn>2</cn></apply>
                   </math>
                 </initialAssignment>
               </listOfInitialAssignments>"""))

    assert len(model.initial_assignments) == 1
    assert model.parameters["p"].value == 0.0


def test_initial_assignment_seeds_a_rate_rule_parameter():
    import math

    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen import BioNetGenModel

    sbml = _model("""
      <listOfParameters><parameter id="x" constant="false"/></listOfParameters>
      <listOfInitialAssignments>
        <initialAssignment symbol="x">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><tanh/><cn>1</cn></apply>
          </math>
        </initialAssignment>
      </listOfInitialAssignments>
      <listOfRules>
        <rateRule variable="x">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
        </rateRule>
      </listOfRules>
    """)
    translated = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert translated.success, translated.error
    result = BioNetGenModel(cpp.parse_string(translated.bngl)).simulate(
        method="ode", t_end=1.0, n_steps=2
    )
    assert result.observables["x_amt"] == pytest.approx(
        [math.tanh(1.0) + t for t in result.time], rel=1e-7
    )


def test_parameter_initial_assignment_reads_the_time_zero_state_once():
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    from bionetgen import BioNetGenModel

    sbml = _model("""
      <listOfParameters>
        <parameter id="x" value="2" constant="false"/>
        <parameter id="y" constant="false"/>
        <parameter id="p" constant="true"/>
      </listOfParameters>
      <listOfInitialAssignments>
        <initialAssignment symbol="p">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>y</ci></math>
        </initialAssignment>
      </listOfInitialAssignments>
      <listOfRules>
        <rateRule variable="x">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p</ci></math>
        </rateRule>
        <assignmentRule variable="y">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>2</cn><ci>x</ci></apply>
          </math>
        </assignmentRule>
      </listOfRules>
    """)
    translated = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert translated.success, translated.error
    result = BioNetGenModel(cpp.parse_string(translated.bngl)).simulate(
        method="ode", t_end=1.0, n_steps=2
    )
    assert result.observables["x_amt"] == pytest.approx([2, 4, 6], rel=1e-7)


def test_chained_initial_assignments_resolve_in_dependency_order():
    # An initial assignment overrides the declared ``value`` attribute of its
    # target, so a chain must be resolved from the root of the chain, not
    # from the declared values.
    model = SBMLParser().parse(_model("""<listOfParameters>
                 <parameter id="a" value="1" constant="true"/>
                 <parameter id="b" value="0" constant="true"/>
                 <parameter id="c" value="0" constant="true"/>
                 <parameter id="d" value="0" constant="true"/>
               </listOfParameters>
               <listOfInitialAssignments>
                 <initialAssignment symbol="c">
                   <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>b</ci></math>
                 </initialAssignment>
                 <initialAssignment symbol="b">
                   <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>a</ci></math>
                 </initialAssignment>
                 <initialAssignment symbol="d">
                   <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>c</ci></math>
                 </initialAssignment>
               </listOfInitialAssignments>"""))

    assert not model.initial_assignments
    assert model.parameters["b"].value == 1.0
    assert model.parameters["c"].value == 1.0
    assert model.parameters["d"].value == 1.0


def _scaled_compartment_model(body: str, *, scaled: bool) -> str:
    units = ""
    compartment_units = ""
    if scaled:
        units = """<listOfUnitDefinitions>
          <unitDefinition id="volume"><listOfUnits>
            <unit kind="dimensionless" scale="-3" exponent="1"/>
          </listOfUnits></unitDefinition>
        </listOfUnitDefinitions>"""
        compartment_units = ' units="volume"'
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="m" substanceUnits="substance" volumeUnits="volume">
        {units}
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"{compartment_units}/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="T" compartment="C" initialConcentration="10000000"
                   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="E" compartment="C" initialConcentration="20000"
                   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="I" compartment="C" initialConcentration="1"
                   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S" compartment="C" initialConcentration="0"
                   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfInitialAssignments>
          <initialAssignment symbol="S">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/><apply><minus/><ci> T </ci><ci> E </ci></apply><ci> I </ci></apply>
            </math>
          </initialAssignment>
        </listOfInitialAssignments>
        {body}
      </model>
    </sbml>"""


def _seed_amount(bngl: str, species: str) -> float:
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith("@") and f"M_{species}()" in stripped:
            return float(stripped.rsplit(" ", 1)[1])
    raise AssertionError(f"no seed for {species}")


@pytest.mark.parametrize("scaled", [False, True])
def test_species_initial_assignment_seed_is_a_normalized_amount(scaled):
    """The seed is the source amount whether or not units are scaled."""
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _scaled_compartment_model("", scaled=scaled)
    )
    assert result.success
    assert _seed_amount(result.bngl, "S") == pytest.approx(9979999, rel=1e-12)
