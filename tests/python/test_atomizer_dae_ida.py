"""End-to-end SBML index-1 DAE execution through the native ODE engine."""

from pathlib import Path

import pytest

import bionetgen


def _dae_sbml(*, impossible_constraint=False, with_event=False, ambiguous=False):
    constraint = (
        "<apply><plus/><apply><power/><ci>Z</ci><cn>2</cn></apply>" "<cn>1</cn></apply>"
        if impossible_constraint
        else (
            "<apply><minus/><apply><plus/><apply><power/><ci>Z</ci><cn>2</cn></apply>"
            "<apply><power/><ci>Y</ci><cn>2</cn></apply></apply><ci>X</ci></apply>"
            if ambiguous
            else "<apply><minus/><apply><power/><ci>Z</ci><cn>2</cn></apply>"
            "<ci>X</ci></apply>"
        )
    )
    event = ""
    if with_event:
        event = """<listOfEvents><event id="reset" useValuesFromTriggerTime="true">
          <trigger initialValue="true" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>X</ci><cn>0.25</cn></apply>
          </math></trigger>
          <listOfEventAssignments><eventAssignment variable="X"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment></listOfEventAssignments>
        </event></listOfEvents>"""
    return f"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
 <model id="index1_dae">
  <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
  <listOfSpecies>
   <species id="X" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
   <species id="Z" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
   {('<species id="Y" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>' if ambiguous else '')}
  </listOfSpecies>
  <listOfParameters><parameter id="k" value="1" constant="true"/></listOfParameters>
  <listOfRules><algebraicRule><math xmlns="http://www.w3.org/1998/Math/MathML">{constraint}</math></algebraicRule></listOfRules>
  <listOfReactions><reaction id="decay" reversible="false">
   <listOfReactants><speciesReference species="X" stoichiometry="1" constant="true"/></listOfReactants>
   <listOfModifiers><modifierSpeciesReference species="Z"/></listOfModifiers>
   <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>Z</ci></apply></math></kineticLaw>
  </reaction></listOfReactions>
  {event}
 </model>
</sbml>"""


def _load(tmp_path: Path, **options):
    source = tmp_path / "index1-dae.xml"
    source.write_text(_dae_sbml(**options), encoding="utf-8")
    return bionetgen.from_sbml(str(source))


def _by_time_and_species(model, result):
    network = model.generate_network()
    return {
        (time, name): value
        for time, row in zip(result.time, result.concentrations)
        for name, value in zip(network.species_names, row)
    }


def test_nonlinear_algebraic_rule_is_enforced_during_ode_simulation(tmp_path):
    model = _load(tmp_path)
    result = model.simulate(method="ode", t_end=0.5, n_steps=1)
    values = _by_time_and_species(model, result)
    assert values[(0.5, "@C::M_X()")] == pytest.approx(0.5625, abs=1e-6)
    assert values[(0.5, "@C::M_Z()")] == pytest.approx(0.75, abs=1e-6)


def test_state_event_reinitializes_consistent_dae_state(tmp_path):
    model = _load(tmp_path, with_event=True)
    result = model.simulate(method="ode", t_end=2.0, n_steps=4)
    values = _by_time_and_species(model, result)
    assert values[(2.0, "@C::M_X()")] == pytest.approx(0.25, abs=2e-5)
    assert values[(2.0, "@C::M_Z()")] == pytest.approx(0.5, abs=2e-5)


def test_inconsistent_singular_algebraic_constraint_fails_explicitly(tmp_path):
    model = _load(tmp_path, impossible_constraint=True)
    with pytest.raises(
        RuntimeError, match="DAE.*consistent initial|algebraic.*singular"
    ):
        model.simulate(method="ode", t_end=0.5, n_steps=1)


def test_underdetermined_algebraic_target_fails_explicitly(tmp_path):
    source = tmp_path / "underdetermined-dae.xml"
    source.write_text(_dae_sbml(ambiguous=True), encoding="utf-8")
    with pytest.raises(bionetgen.BioNetGenError, match="unambiguous free species"):
        bionetgen.from_sbml(str(source))
