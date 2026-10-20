"""Regression tests for an assigned species-reference stoichiometry.

SBML Level 3 Version 2 Core (Sec. 4.11.3) says that a species reference's
``id`` names a model-level symbol that holds the stoichiometry:

> If the SpeciesReference object's ``constant`` attribute has the value
> ``true``, then the stoichiometry is fixed and cannot be changed except by an
> InitialAssignment. […] It is not an error to define ``stoichiometry`` on a
> species reference and also redefine the stoichiometry using an
> InitialAssignment, but the ``stoichiometry`` attribute in that case is
> ignored.

So an initial assignment to a fixed reference's symbol replaces the
``stoichiometry`` attribute.  When the assigned value cannot be resolved to a
number, the Atomizer has to say so instead of silently keeping the
attribute's value.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer


def _model(reference: str, assignment: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="assigned_stoichiometry">
        <listOfCompartments>
          <compartment id="C" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="S1" compartment="C" initialAmount="1" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>
              <speciesReference {reference}/>
            </listOfReactants>
            <listOfProducts/>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfInitialAssignments>
          <initialAssignment symbol="S1_sr">
            <math xmlns="http://www.w3.org/1998/Math/MathML">{assignment}</math>
          </initialAssignment>
        </listOfInitialAssignments>
      </model>
    </sbml>"""


def test_unresolvable_assigned_stoichiometry_is_reported():
    # The assigned value depends on the species amount, so it is not a
    # constant the Atomizer can resolve at initialization and the
    # stoichiometry is not representable.  The model must say so rather than
    # silently use the attribute's value.
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model(
            'id="S1_sr" species="S1" stoichiometry="1" constant="true"',
            "<apply><abs/><ci>S1</ci></apply>",
        )
    )

    assert result.success, result.error
    assert any(
        warning["category"] == "stoichiometry"
        and warning["severity"] == "dropped"
        and "S1_sr" in warning["message"]
        for warning in atomizer.model.import_warnings
    ), atomizer.model.import_warnings


def test_a_builtin_assigned_stoichiometry_folds_to_the_writers_value():
    # ``exp`` is one of the MathML built-ins the writer lowers exactly, so
    # the assigned value is a constant the Atomizer can resolve.  The folded
    # value is the value of the expression the writer emits, which uses the
    # writer's own truncated constant.
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model(
            'id="S1_sr" species="S1" stoichiometry="1" constant="true"',
            "<apply><exp/><cn>2.7</cn></apply>",
        )
    )

    assert result.success, result.error
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings
    reference = atomizer.model.reactions["J0"].reactants[0]
    assert reference.variable_stoichiometry is False
    assert reference.stoichiometry == 2.71828182845905**2.7
    # The assigned value is not an integer, so the deterministic flux
    # lowering carries it in the rate coefficient.
    assert "2.71828182845905" not in result.bngl
    assert f"({2.71828182845905**2.7!r})" in result.bngl


def test_resolvable_assigned_stoichiometry_replaces_the_attribute():
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(
        _model(
            'id="S1_sr" species="S1" stoichiometry="1" constant="true"',
            "<cn>2</cn>",
        )
    )

    assert result.success, result.error
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning["category"] == "stoichiometry" and warning["severity"] == "dropped"
    ], atomizer.model.import_warnings
    # The assigned value 2 replaces the declared stoichiometry 1, so the
    # reaction consumes two S1 molecules.
    assert "@C:M_S1() + @C:M_S1()" in result.bngl
