"""Regression test for a reaction whose rounded BNGL pattern list is empty.

A reaction whose only reactant carries a fractional stoichiometry has no
BNGL pattern for it: the molecule count rounds to zero.  The reaction is not
lost, though: the deterministic flux lowering emits the species-specific
``TotalRate`` rules that carry the fractional stoichiometry, so the model's
derivative still matches the source model.

The change that keeps such a reaction alive touches every model, not only
the ones that use ``delay`` or ``rateOf``, so it needs a test of its own.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer

_SBML = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
  <model id="fractional_stoichiometry">
    <listOfCompartments>
      <compartment id="C" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1"
               hasOnlySubstanceUnits="true" constant="false"/>
      <species id="S2" compartment="C" initialAmount="0"
               hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="0.4" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="0.4" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn> 0.5 </cn></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def test_fractional_stoichiometry_reaction_is_not_dropped():
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_SBML)
    assert result.success, result.error

    assert "J0_consume_S1:" in result.bngl
    assert "J0_produce_S2:" in result.bngl
    assert "0.4" in result.bngl


def test_fractional_stoichiometry_reaction_keeps_its_derivative():
    """The generated rule carries the fractional stoichiometry and the flux."""

    from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_SBML)
    assert result.success, result.error
    model = cpp.parse_string(result.bngl)

    simulation = BioNetGenModel(model).simulate(
        method="ode", t_start=0, t_end=1, n_steps=10, rtol=1e-9, atol=1e-14
    )

    # dS1/dt = -0.4 * 0.5 and dS2/dt = 0.4 * 0.5.
    np_s1 = simulation.observables["S1_amt"]
    np_s2 = simulation.observables["S2_amt"]
    assert abs(np_s1[-1] - (1.0 - 0.2)) < 1e-6
    assert abs(np_s2[-1] - 0.2) < 1e-6
