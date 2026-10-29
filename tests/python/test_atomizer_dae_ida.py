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


def _concentration_dae_sbml():
    """The same index-1 DAE with concentration-valued species in C = 2."""

    return (
        _dae_sbml()
        .replace('size="1"', 'size="2"')
        .replace('hasOnlySubstanceUnits="true"', 'hasOnlySubstanceUnits="false"')
    )


def test_algebraic_residual_reads_the_sbml_quantity_of_each_species():
    """SBML math names a species' concentration unless it has only substance units.

    The residual the native DAE runtime evaluates is the rule's math with the
    SBML symbols translated as in an assignment rule, so ``Z^2 - X`` reads
    the concentration functions, not the amount observables.
    """

    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.atomizer.modern.parser import SBMLParser
    from bionetgen.sbml import _native_algebraic_rules

    source = _concentration_dae_sbml()
    bngl = (
        Atomizer(atomize=False, quiet_mode=True, native_dae_runtime=True)
        .atomize(source)
        .bngl
    )
    assert "__algebraic_residual_0() = (_c_Z()) ^ (2) - _c_X()" in bngl
    assert _native_algebraic_rules(SBMLParser().parse(source)) == [
        ("Z", "__algebraic_residual_0()")
    ]
    amounts = (
        Atomizer(atomize=False, quiet_mode=True, native_dae_runtime=True)
        .atomize(_dae_sbml())
        .bngl
    )
    assert "__algebraic_residual_0() = (Z_amt) ^ (2) - X_amt" in amounts


def test_concentration_algebraic_rule_is_enforced_in_its_compartment(tmp_path):
    # [Z]^2 = [X] and d n_X/dt = -k [Z] with n = 2 [.], so
    # d sqrt([X])/dt = -1/4 from [X](0) = 0.5; amounts are reported.
    source = tmp_path / "concentration-dae.xml"
    source.write_text(_concentration_dae_sbml(), encoding="utf-8")
    model = bionetgen.from_sbml(str(source))
    result = model.simulate(method="ode", t_end=0.5, n_steps=1)
    values = _by_time_and_species(model, result)
    root = 0.5**0.5 - 0.125
    assert values[(0.5, "@C::M_X()")] == pytest.approx(2 * root**2, abs=1e-6)
    assert values[(0.5, "@C::M_Z()")] == pytest.approx(2 * root, abs=1e-6)
