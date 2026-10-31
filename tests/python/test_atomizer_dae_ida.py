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


def _coupled_parameter_dae_sbml(*, singular=False):
    """Three parameter states with a two-equation nonlinear DAE."""

    second_constraint = (
        "<apply><times/><cn>2</cn><apply><minus/><apply><plus/>"
        "<ci>x</ci><ci>y</ci></apply><ci>T</ci></apply></apply>"
        if singular
        else "<apply><minus/><apply><times/><ci>x</ci><ci>y</ci></apply><cn>1</cn></apply>"
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
 <model id="coupled_parameter_dae">
  <listOfParameters>
   <parameter id="T" value="2.5" constant="false"/>
   <parameter id="x" value="2" constant="false"/>
   <parameter id="y" value="0.5" constant="false"/>
  </listOfParameters>
  <listOfRules>
   <rateRule variable="T"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
   <algebraicRule><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><apply><plus/><ci>x</ci><ci>y</ci></apply><ci>T</ci></apply></math></algebraicRule>
   <algebraicRule><math xmlns="http://www.w3.org/1998/Math/MathML">{second_constraint}</math></algebraicRule>
  </listOfRules>
 </model>
</sbml>'''


def _assert_libsbml_error_free(source):
    import libsbml

    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors


def _by_time_and_species(model, result):
    network = model.generate_network()
    return {
        (time, name): value
        for time, row in zip(result.time, result.concentrations)
        for name, value in zip(network.species_names, row)
    }


def test_coupled_algebraic_rules_bind_all_free_parameter_states():
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.atomizer.modern.parser import SBMLParser
    from bionetgen.sbml import _native_algebraic_rules

    source = _coupled_parameter_dae_sbml()
    _assert_libsbml_error_free(source)
    parsed = SBMLParser().parse(source)
    assert _native_algebraic_rules(parsed) == [
        ("x_amt", "__algebraic_residual_0()"),
        ("y_amt", "__algebraic_residual_1()"),
    ]
    atomizer = Atomizer(atomize=False, quiet_mode=True, native_dae_runtime=True)
    converted = atomizer.atomize(source)
    assert converted.success, converted.error
    assert not any(
        warning.get("category") == "algebraicRule"
        for warning in atomizer.get_model().import_warnings
    )
    assert "algebraicRule" not in converted.bngl
    assert "__algebraic_residual_0() = (x_amt + y_amt) - T_amt" in converted.bngl
    assert "__algebraic_residual_1() = (x_amt * y_amt) - 1" in converted.bngl


def test_algebraic_parameter_without_initial_value_is_not_seeded_as_zero():
    from bionetgen.atomizer.modern import Atomizer

    source = _coupled_parameter_dae_sbml().replace('value="2" ', "")
    converted = Atomizer(
        atomize=False, quiet_mode=True, native_dae_runtime=True
    ).atomize(source)
    assert not converted.success
    assert "no defined time-zero value" in converted.error


def test_algebraic_target_selection_preserves_case_sensitive_sbml_sids():
    from bionetgen.atomizer.modern.parser import SBMLParser
    from bionetgen.sbml import BioNetGenError, _native_algebraic_rules

    source = '''<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
 <model id="case_sensitive_ids">
  <listOfParameters>
   <parameter id="x" value="1" constant="false"/>
   <parameter id="X" value="1" constant="false"/>
  </listOfParameters>
  <listOfRules>
   <algebraicRule><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><ci>X</ci><ci>x</ci></apply></math></algebraicRule>
  </listOfRules>
 </model>
</sbml>'''
    _assert_libsbml_error_free(source)
    parsed = SBMLParser().parse(source)
    with pytest.raises(BioNetGenError, match="square set of free mutable state"):
        _native_algebraic_rules(parsed)


def test_coupled_algebraic_parameter_system_follows_the_analytic_branch(tmp_path):
    source = tmp_path / "coupled-parameter-dae.xml"
    source.write_text(_coupled_parameter_dae_sbml(), encoding="utf-8")
    model = bionetgen.from_sbml(str(source))
    result = model.simulate(method="ode", t_end=2.0, n_steps=8)

    # x+y=T and xy=1, starting from x>y. The requested branch stays x>y.
    assert len(result.time) > 3
    assert result.time[0] == pytest.approx(0.0, abs=0.0)
    assert result.time[-1] == pytest.approx(2.0, abs=0.0)
    for index, time in enumerate(result.time):
        total = 2.5 + time
        x = (total + (total * total - 4.0) ** 0.5) / 2.0
        y = 1.0 / x
        observed_total = result.observables["T_amt"][index]
        observed_x = result.observables["x_amt"][index]
        observed_y = result.observables["y_amt"][index]
        assert observed_total == pytest.approx(total, abs=2e-7)
        assert observed_x + observed_y - observed_total == pytest.approx(
            0.0, abs=2e-7
        )
        assert observed_x * observed_y - 1.0 == pytest.approx(0.0, abs=2e-7)
        assert observed_x > observed_y
        assert observed_x == pytest.approx(x, abs=2e-7)
        assert observed_y == pytest.approx(y, abs=2e-7)


def test_singular_square_algebraic_system_fails_consistent_initialization(tmp_path):
    source_text = _coupled_parameter_dae_sbml(singular=True)
    _assert_libsbml_error_free(source_text)
    source = tmp_path / "singular-coupled-parameter-dae.xml"
    source.write_text(source_text, encoding="utf-8")
    model = bionetgen.from_sbml(str(source))
    with pytest.raises(
        RuntimeError, match="DAE.*consistent initial|algebraic.*singular"
    ):
        model.simulate(method="ode", t_end=0.5, n_steps=2)


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
    with pytest.raises(
        bionetgen.BioNetGenError,
        match="square set of free mutable state candidates",
    ):
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


def test_initially_true_dae_event_evaluates_its_delay_at_trigger_time(tmp_path):
    source = _dae_sbml(with_event=True)
    source = source.replace('initialValue="true"', 'initialValue="false"')
    source = source.replace("<lt/><ci>X</ci><cn>0.25</cn>", "<gt/><ci>X</ci><cn>0</cn>")
    source = source.replace(
        "<listOfEventAssignments>",
        '<delay><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><times/><ci>X</ci><cn>0.1</cn></apply></math></delay>"
        "<listOfEventAssignments>",
    )
    source = source.replace(
        '<eventAssignment variable="X"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn>',
        '<eventAssignment variable="X"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.25</cn>',
    )
    path = tmp_path / "initial-dae-delay.xml"
    path.write_text(source, encoding="utf-8")
    model = bionetgen.from_sbml(str(path))
    result = model.simulate(method="ode", t_end=0.2, n_steps=2)
    values = _by_time_and_species(model, result)
    # Initial X=1 sets the delay to 0.1. After resetting X=0.25 at t=0.1,
    # d sqrt(X)/dt=-1/2 for another 0.1 time units.
    assert values[(0.2, "@C::M_X()")] == pytest.approx(0.45**2, abs=2e-6)
    assert values[(0.2, "@C::M_Z()")] == pytest.approx(0.45, abs=2e-6)
