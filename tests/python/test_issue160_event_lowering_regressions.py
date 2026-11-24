"""Focused regressions for SBML event lowering used by conversionFactor rows.

The fixture is the pinned source of official SBML Test Suite case 01000.
The assertion is a product regression: it checks exact lowering, not
acceptance answers or corpus membership.
"""

from pathlib import Path

from bionetgen.atomizer.modern import Atomizer

FIXTURE = Path(__file__).parent / "fixtures" / "sbml_01000.xml"


def test_rate_ruled_parameter_is_native_event_target_and_window_stays_scheduled():
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(FIXTURE.read_text(encoding="utf-8"))
    assert result.success, result.error
    bngl = result.bngl
    assert "begin bng3_events version 1" in bngl
    # A rate-ruled parameter is a native state even with a non-unit default
    # compartment, and its assignment reads the other promoted state.
    assert "assignment: k4_amt = k3_amt" in bngl
    assert "assignment: k5_amt = k4_amt" in bngl
    assert "assignment: k3_amt = k5_amt" in bngl
    # The pure clock window is exact as a scheduled action.
    assert "begin actions" in bngl
    assert "14.5" in bngl
    assert "remain untranslated" not in bngl


STOICHIOMETRY_FIXTURE = Path(__file__).parent / "fixtures" / "sbml_01398.xml"


def test_event_stoichiometry_change_transfers_the_added_amount_to_the_pool_state():
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(STOICHIOMETRY_FIXTURE.read_text(encoding="utf-8"))
    assert result.success, result.error
    bngl = result.bngl
    # The fast equilibrium holds S1 at zero; the source event's S1 write is
    # re-expressed as S2 += 5/5, and the stoichiometry parameter still changes.
    assert 'setConcentration("@default_compartment:M_S2()", "6")' in bngl
    assert 'setParameter("S1_stoichiometry", "5")' in bngl
    assert "remain untranslated" not in bngl
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning.get("severity") in {"dropped", "approximated"}
    ]


ZERO_SWITCH_FIXTURE = Path(__file__).parent / "fixtures" / "sbml_00988.xml"


def test_zero_interval_fast_coefficient_lowers_exactly():
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 2})
    result = atomizer.atomize(ZERO_SWITCH_FIXTURE.read_text(encoding="utf-8"))
    assert result.success, result.error
    bngl = result.bngl
    # The fast reaction is removed; A is a rate-rule state whose production is
    # gated by the coefficient, B keeps the conserved pool, and the event that
    # turns the coefficient on also transfers A to the pool.
    assert "__rate_rule__A()" in bngl
    assert 'setParameter("k2", "1")' in bngl
    assert 'setConcentration("@comp:M_A()", "0")' in bngl
    assert 'setParameter("k2", "0")' in bngl
    assert "remain untranslated" not in bngl
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning.get("severity") in {"dropped", "approximated"}
    ]


def test_rate_ruled_boundary_species_event_to_initial_value_is_not_dropped():
    """An event restoring a rate-ruled boundary species to its initial value is not a no-op."""
    sbml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="boundary_rate_rule_priority">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="2" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="true" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <rateRule variable="S1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn type="integer"> -1 </cn>
        </math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol><cn> 2.5 </cn></apply>
          </math>
        </trigger>
        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci> S1 </ci></math>
        </priority>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer"> 5 </cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="E1" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol><cn> 2.5 </cn></apply>
          </math>
        </trigger>
        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 7.4 </cn></math>
        </priority>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer"> 10 </cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(sbml)
    assert result.success, result.error
    bngl = result.bngl
    assert "remain untranslated" not in bngl
    idx_five = bngl.index('setConcentration("@C:M_S1()", "5")')
    idx_ten = bngl.index('setConcentration("@C:M_S1()", "10")')
    assert idx_five < idx_ten
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning.get("severity") in {"dropped", "approximated"}
    ]


def test_event_restoring_prior_event_target_to_initial_value_is_not_dropped():
    """An event restoring a species changed by another event is not a no-op."""
    sbml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="boundary_two_events_restore">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="true" constant="false"/>
    </listOfSpecies>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol><cn> 1 </cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer"> 5 </cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="E1" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol><cn> 3 </cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn type="integer"> 10 </cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 5})
    result = atomizer.atomize(sbml)
    assert result.success, result.error
    bngl = result.bngl
    assert 'setConcentration("@C:M_S1()", "5")' in bngl
    assert 'setConcentration("@C:M_S1()", "10")' in bngl
