"""Regression test for a signed flux in an irreversible reaction.

SBML Level 3 Version 2 Core Sec. 4.11.7 gives the species' rate of change as
``c_Si * stoich_ij(t) * v_Rj``: the reaction's extent rate ``v_Rj`` is the
kinetic law's value, and a negative one runs the reaction backwards.  The
deterministic flux lowering therefore has to pick the reaction's side from the
sign of the *derivative*, not from the sign of the stoichiometry.

A single BNGL rule with a negative rate is correct for the ODE, but the
stochastic engine cannot give a reaction a negative propensity: the rule is
inert and the species never changes.  That is a silent wrong trajectory, so
the rate is guarded on the derivative's sign, as the reversible lowering
already does.
"""

from __future__ import annotations

from bionetgen.atomizer.modern import Atomizer

_MODEL = """<sbml xmlns="http://www.sbml.org/sbml/level2/version4">
  <model id="signed_irreversible_flux">
    <listOfCompartments>
      <compartment id="C" size="1"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialConcentration="1"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J0" fast="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="2"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="A" stoichiometry="-3"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer"> -1 </cn>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def _model():
    result = Atomizer(atomize=False, quiet_mode=True).atomize(_MODEL)
    assert result.success, result.error

    from bionetgen import _bionetgen_cpp as cpp

    return cpp.parse_string(result.bngl)


def test_the_emitted_rate_is_guarded_on_the_derivative_sign():
    """No rule may carry a negative rate.

    A negative propensity is inert in the stochastic engine, so the rate has
    to be the non-negative magnitude of the derivative.
    """

    from bionetgen import BioNetGenModel

    model = _model()
    simulation = BioNetGenModel(model).simulate(
        method="ode", t_start=0, t_end=2, n_steps=4, rtol=1e-9, atol=1e-14
    )

    # dA/dt = (-2 + -3) * (-1) = 5, so the species grows by 5 per unit time.
    amounts = list(simulation.observables["A_amt"])
    assert abs(amounts[0] - 1.0) < 1e-9
    assert abs(amounts[-1] - 11.0) < 1e-6


def test_the_stochastic_engine_does_not_ignore_the_reaction():
    """The stochastic trajectory must not be inert.

    A negative rate made the rule's propensity negative, which the
    stochastic engine clamps away: the species then never changes at all.
    """

    from bionetgen import BioNetGenModel

    model = _model()
    simulation = BioNetGenModel(model).simulate(
        method="ssa", t_start=0, t_end=2, n_steps=4, seed=20261020
    )

    amounts = list(simulation.observables["A_amt"])
    assert abs(amounts[0] - 1.0) < 1e-9
    assert amounts[-1] > 1.0, amounts
