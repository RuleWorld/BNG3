"""A parameter assigned by a native SBML event is part of the model state."""

from bionetgen.atomizer.modern import Atomizer


def _model(trigger: str, extra_events: str = "") -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="event_parameter_state">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="X" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
          <species id="Y" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"/>
          <species id="Z" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="k" value="0.75" constant="true"/>
          <parameter id="r" value="0.25" constant="true"/>
          <parameter id="reset" value="0" constant="false"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="consume" reversible="false">
            <listOfReactants>
              <speciesReference species="X"/>
              <speciesReference species="Y" stoichiometry="2"/>
            </listOfReactants>
            <listOfProducts><speciesReference species="Z"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>k</ci><ci>X</ci><ci>Y</ci></apply>
            </math></kineticLaw>
          </reaction>
          <reaction id="release" reversible="false">
            <listOfReactants><speciesReference species="Z"/></listOfReactants>
            <listOfProducts>
              <speciesReference species="X"/>
              <speciesReference species="Y"/>
            </listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>r</ci><ci>Z</ci></apply>
            </math></kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="E0">
            <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></priority>
            <trigger initialValue="false" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">{trigger}</math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="reset">
                <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
              </eventAssignment>
            </listOfEventAssignments>
          </event>
          {extra_events}
        </listOfEvents>
      </model>
    </sbml>"""


def _atomize(trigger: str):
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(_model(trigger))
    assert result.success, result.error
    return atomizer, result


def test_native_event_promotes_mutable_parameter_to_state():
    atomizer, result = _atomize("<apply><lt/><ci>X</ci><cn>0.75</cn></apply>")

    assert "begin bng3_events version 1" in result.bngl
    assert "assignment: reset_amt = 3" in result.bngl
    assert "Species reset_amt" in result.bngl
    assert "__rate_rule_state__reset" in result.bngl
    assert any(
        warning["category"] == "event" and warning["severity"] == "info"
        for warning in atomizer.model.import_warnings
    )


def test_finite_schedule_keeps_parameter_as_parameter():
    _atomizer, result = _atomize(
        '<apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>'
    )

    assert "__rate_rule_state__reset" not in result.bngl
    assert 'setParameter("reset", "3")' in result.bngl


def test_parameter_valued_trigger_is_lowered_against_promoted_state():
    extra = """<event id="E1">
      <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></priority>
      <trigger initialValue="false" persistent="true">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><ci>reset</ci><cn>2</cn></apply></math>
      </trigger>
      <listOfEventAssignments><eventAssignment variable="Y">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
      </eventAssignment></listOfEventAssignments>
    </event>"""
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model("<apply><lt/><ci>X</ci><cn>0.75</cn></apply>", extra)
    )

    assert result.success, result.error
    assert "trigger: reset_amt > 2" in result.bngl


def test_native_and_finite_schedule_events_share_promoted_parameter_state():
    extra = """<event id="scheduled_reset">
      <trigger initialValue="false" persistent="true">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><geq/>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
            <cn>2</cn>
          </apply>
        </math>
      </trigger>
      <listOfEventAssignments><eventAssignment variable="reset">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math>
      </eventAssignment></listOfEventAssignments>
    </event>
    <event id="parameter_trigger">
      <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></priority>
      <trigger initialValue="false" persistent="true">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><ci>reset</ci><cn>2</cn></apply></math>
      </trigger>
      <listOfEventAssignments><eventAssignment variable="Y">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
      </eventAssignment></listOfEventAssignments>
    </event>"""
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model("<apply><lt/><ci>X</ci><cn>0.75</cn></apply>", extra)
    )

    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "begin actions" in result.bngl
    assert 'setConcentration("M___rate_rule_state__reset()", "4")' in result.bngl
    assert "trigger: reset_amt > 2" in result.bngl


def test_time_minus_mutable_parameter_trigger_is_rewritten_as_time_threshold():
    extra = """<event id="E1">
      <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></priority>
      <trigger initialValue="false" persistent="true">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><geq/>
            <apply><minus/>
              <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
              <ci>reset</ci>
            </apply>
            <cn>1</cn>
          </apply>
        </math>
      </trigger>
      <listOfEventAssignments><eventAssignment variable="Y">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
      </eventAssignment></listOfEventAssignments>
    </event>"""
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model("<apply><lt/><ci>X</ci><cn>0.75</cn></apply>", extra)
    )

    assert result.success, result.error
    assert "trigger: time >= reset_amt + 1" in result.bngl


def test_abs_of_continuous_species_is_lowered_as_a_native_root():
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model(
            "<apply><lt/><apply><abs/><apply><minus/><ci>X</ci><cn>0.5</cn></apply></apply><cn>0.25</cn></apply>"
        )
    )

    assert result.success, result.error
    assert "trigger: abs(X_amt - 0.5) < 0.25" in result.bngl


def test_floor_ge_integer_trigger_uses_equivalent_continuous_boundary():
    _atomizer, result = _atomize(
        "<apply><geq/><apply><floor/><apply><divide/><ci>X</ci><cn>2</cn></apply></apply><cn>1</cn></apply>"
    )

    assert "trigger: X_amt / 2 >= 1" in result.bngl


def test_nonlinear_event_assignment_preserves_mathml_power_grouping():
    trigger = "<apply><lt/><ci>X</ci><cn>0.75</cn></apply>"
    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(trigger).replace(
            '<eventAssignment variable="reset">\n                <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>',
            '<eventAssignment variable="reset">\n                <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><divide/><apply><power/><apply><minus/><ci>X</ci><cn>0.5</cn></apply><cn>2</cn></apply><cn>0.5</cn></apply></math>',
        )
    )

    assert result.success, result.error
    assert "assignment: reset_amt = (X_amt - 0.5) ** 2 / 0.5" in result.bngl
