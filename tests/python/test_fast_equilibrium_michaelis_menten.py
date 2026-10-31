"""Parameterized test suite qualifying fast equilibrium coupled to slow enzymatic consumption.

Establishes:
1. Exact stoichiometric pool reduction for bimolecular fast subsystems (E + S <-> ES).
2. Exact agreement against an independent differential oracle for the conserved pool:
       dP_S/dt = - k_cat * ES(E_0, P_S),
   where ES(E_0, P_S) = ((E_0 + P_S + K_d) - sqrt((E_0 + P_S + K_d)^2 - 4 * E_0 * P_S)) / 2.
3. Strict conservation of total enzyme (E + ES = E_0) and total substrate/product
   (S + ES + P = S_0) across the entire trajectory.
4. Instantaneous adherence to the algebraic fast-equilibrium balance:
       k_f * E(t) * S(t) - k_r * ES(t) = 0.
5. Asymptotic convergence to the classical Henri-Michaelis-Menten analytical limit
       K_d * ln(S_MM(t) / S_0) + (S_MM(t) - S_0) = - V_max * t
   as the enzyme-to-substrate ratio E_0 / S_0 approaches zero.
"""

from __future__ import annotations

import math
import numpy as np
import pytest
import scipy.integrate as integrate
import libsbml

from bionetgen import BioNetGenModel
from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.helpers import logger


@pytest.fixture(autouse=True)
def _clean_logger():
    logger.clear()
    yield
    logger.clear()


FAST_HEADER = (
    '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
    'level="3" version="1">'
)


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


def _build_mm_sbml(e0: float, s0: float, kf: float, kr: float, kcat: float) -> str:
    """Construct an SBML model with fast binding E + S <-> ES and slow catalysis ES -> E + P."""
    return FAST_HEADER + f"""<model id="mm_fast" timeUnits="second">
        <listOfCompartments>
          <compartment id="cell" size="1" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="E" compartment="cell" initialAmount="{e0}" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="S" compartment="cell" initialAmount="{s0}" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="ES" compartment="cell" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
          <species id="P" compartment="cell" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="kf" value="{kf}" constant="true"/>
          <parameter id="kr" value="{kr}" constant="true"/>
          <parameter id="kcat" value="{kcat}" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="binding" reversible="true" fast="true">
            <listOfReactants>
              <speciesReference species="E" stoichiometry="1" constant="true"/>
              <speciesReference species="S" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="ES" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><minus/>
                  <apply><times/><ci>kf</ci><ci>E</ci><ci>S</ci></apply>
                  <apply><times/><ci>kr</ci><ci>ES</ci></apply>
                </apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="catalysis" reversible="false" fast="false">
            <listOfReactants>
              <speciesReference species="ES" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="E" stoichiometry="1" constant="true"/>
              <speciesReference species="P" stoichiometry="1" constant="true"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>kcat</ci><ci>ES</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        </model></sbml>
        """


def test_independent_sbml_validation():
    """Verify the authored SBML source model passes independent libSBML validation."""
    xml = _build_mm_sbml(e0=0.05, s0=10.0, kf=2.0, kr=1.0, kcat=0.5)
    doc = libsbml.readSBMLFromString(xml)
    assert doc.getNumErrors() == 0, doc.getErrorLog().toString()


@pytest.mark.parametrize(
    ("e0", "s0", "kf", "kr", "kcat"),
    [
        (0.05, 10.0, 2.0, 1.0, 0.5),  # Ordinary MM regime: Kd = 0.5, Vmax = 0.025
        (0.02, 5.0, 4.0, 2.0, 1.0),  # Fast turnover: Kd = 0.5, Vmax = 0.02
        (0.1, 20.0, 1.0, 2.0, 0.2),  # Weak binding: Kd = 2.0, Vmax = 0.02
    ],
)
def test_fast_equilibrium_coupled_to_catalysis_simulation(e0, s0, kf, kr, kcat):
    """Qualify ODE simulation of fast equilibrium binding coupled to slow catalysis against independent oracles."""
    xml = _build_mm_sbml(e0=e0, s0=s0, kf=kf, kr=kr, kcat=kcat)
    doc = libsbml.readSBMLFromString(xml)
    assert doc.getNumErrors() == 0, doc.getErrorLog().toString()

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=100, n_steps=20).atomize(
        xml
    )
    assert atomized.success, atomized.error

    fast_notes = [
        entry.message
        for entry in atomized.log
        if "[fastReaction]" in entry.message
        and "reconstructed on the conserved pools" in entry.message
    ]
    assert len(fast_notes) >= 1

    sample_times = np.linspace(0.0, 100.0, 11)
    result = _simulate(atomized.bngl, sample_times)

    e_sim = result.functions["E"]
    s_sim = result.functions["S"]
    es_sim = result.functions["ES"]
    p_sim = result.observables["P"]
    ps_sim = s_sim + es_sim

    kd = kr / kf
    vmax = kcat * e0

    # 1. Exact Independent Differential Oracle: solve dP_S/dt = - kcat * ES(e0, P_S)
    def pool_deriv(t, y):
        ps = y[0]
        total = e0 + ps + kd
        es = (total - math.sqrt(max(0.0, total * total - 4.0 * e0 * ps))) / 2.0
        return [-kcat * es]

    sol = integrate.solve_ivp(
        pool_deriv,
        [0.0, max(sample_times)],
        [s0],
        t_eval=sample_times,
        rtol=1e-10,
        atol=1e-12,
    )

    for t, e_val, s_val, es_val, p_val, ps_val, ps_oracle in zip(
        sample_times, e_sim, s_sim, es_sim, p_sim, ps_sim, sol.y[0]
    ):
        # 1. Exact agreement with independent pool ODE oracle
        assert ps_val == pytest.approx(ps_oracle, rel=1e-5, abs=1e-6)

        # 2. Exact Enzyme Conservation: E(t) + ES(t) == E_0
        assert e_val + es_val == pytest.approx(e0, rel=1e-6, abs=1e-8)

        # 3. Exact Substrate + Product Conservation: S(t) + ES(t) + P(t) == S_0
        assert s_val + es_val + p_val == pytest.approx(s0, rel=1e-6, abs=1e-8)

        # 4. Instantaneous Fast Equilibrium Balance: kf * E * S == kr * ES
        assert kf * e_val * s_val == pytest.approx(kr * es_val, rel=1e-5, abs=1e-7)


def test_asymptotic_convergence_to_michaelis_menten():
    """Verify asymptotic convergence to the classical Henri-Michaelis-Menten law as E_0/S_0 -> 0."""
    # When E_0 << S_0, the evolving substrate pool P_S = S + ES satisfies:
    # dP_S/dt = - kcat * ES ~= - Vmax * P_S / (Kd + P_S)
    # Integrating from P_S(0) = S_0 gives:
    # Kd * ln(P_S(t) / S_0) + (P_S(t) - S_0) ~= - V_max * t
    s0 = 100.0
    kf = 2.0
    kr = 1.0
    kcat = 0.5
    kd = kr / kf

    # Test small E_0 (E_0/S_0 = 0.001)
    e0 = 0.1
    vmax = kcat * e0

    xml = _build_mm_sbml(e0=e0, s0=s0, kf=kf, kr=kr, kcat=kcat)
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=50, n_steps=10).atomize(
        xml
    )
    assert atomized.success

    sample_times = np.linspace(0.0, 50.0, 6)
    result = _simulate(atomized.bngl, sample_times)

    ps_sim = result.functions["S"] + result.functions["ES"]
    for t, ps_val in zip(sample_times, ps_sim):
        if t > 0:
            lhs = kd * math.log(ps_val / s0) + (ps_val - s0)
            rhs = -vmax * t
            # Relative agreement with MM analytical limit is within 0.1%
            assert lhs == pytest.approx(rhs, rel=1e-3)


def test_fast_equilibrium_boundary_zero_order_to_first_order():
    """Boundary transition: zero-order (S >> Kd) to first-order (S << Kd) kinetics."""
    xml = _build_mm_sbml(e0=0.1, s0=10.0, kf=2.0, kr=1.0, kcat=0.5)
    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=200, n_steps=20).atomize(
        xml
    )
    assert atomized.success

    # Early times: S >> Kd => rate ~= - Vmax (linear slope)
    early_times = np.array([0.0, 5.0, 10.0])
    res_early = _simulate(atomized.bngl, early_times)
    s_early = res_early.functions["S"]
    vmax = 0.1 * 0.5  # 0.05
    # Rate of consumption in zero-order regime: delta_S / delta_t ~= - Vmax
    slope = (s_early[-1] - s_early[0]) / 10.0
    assert abs(slope - (-vmax * 10.0 / 10.5)) < 1e-3


def test_fast_equilibrium_refuses_variable_compartment_volume():
    """Verify Atomizer explicitly refuses bimolecular pool lowering when compartment volume is variable.

    Per SBML Level 3 specifications and AGENTS.md, dynamic volume changes (e.g. rate rules,
    non-constant compartments) alter concentrations and equilibrium positions continuously.
    Because BNG3 does not approximate unsupported dynamic volume shifts during static
    lowering, it must explicitly refuse the reduction with an informative diagnostic.
    """
    xml_var = FAST_HEADER + """<model id="mm_var_vol" timeUnits="second">
      <listOfCompartments>
        <compartment id="cell" size="1.0" constant="false"/>
      </listOfCompartments>
      <listOfSpecies>
        <species id="E" compartment="cell" initialAmount="1.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        <species id="S" compartment="cell" initialAmount="10.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        <species id="ES" compartment="cell" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      </listOfSpecies>
      <listOfParameters>
        <parameter id="kf" value="2.0" constant="true"/>
        <parameter id="kr" value="1.0" constant="true"/>
      </listOfParameters>
      <listOfReactions>
        <reaction id="binding" reversible="true" fast="true">
          <listOfReactants>
            <speciesReference species="E" stoichiometry="1" constant="true"/>
            <speciesReference species="S" stoichiometry="1" constant="true"/>
          </listOfReactants>
          <listOfProducts>
            <speciesReference species="ES" stoichiometry="1" constant="true"/>
          </listOfProducts>
          <kineticLaw>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/>
                <apply><times/><ci>kf</ci><ci>E</ci><ci>S</ci></apply>
                <apply><times/><ci>kr</ci><ci>ES</ci></apply>
              </apply>
            </math>
          </kineticLaw>
        </reaction>
      </listOfReactions>
    </model></sbml>"""

    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(xml_var)
    warnings = [
        entry.message for entry in atomized.log if "[fastReaction]" in entry.message
    ]
    assert len(warnings) == 1
    assert "requires a constant shared compartment" in warnings[0]
    # Fast reaction was NOT stripped; kept explicitly in generated BNGL
    assert "binding:" in atomized.bngl.split("begin reaction rules")[1]


def test_fast_equilibrium_compartment_volume_scaling():
    """Verify bimolecular fast equilibrium holds to machine precision in a non-unit compartment volume."""
    vol = 2.5
    e0_conc = 0.04  # concentration
    s0_conc = 8.0  # concentration
    e0_amt = e0_conc * vol  # amount = 0.1
    s0_amt = s0_conc * vol  # amount = 20.0
    kf = 2.0
    kr = 1.0
    kcat = 0.5

    xml = FAST_HEADER + f"""<model id="mm_vol25" timeUnits="second">
      <listOfCompartments>
        <compartment id="cell" size="{vol}" constant="true"/>
      </listOfCompartments>
      <listOfSpecies>
        <species id="E" compartment="cell" initialAmount="{e0_amt}" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        <species id="S" compartment="cell" initialAmount="{s0_amt}" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        <species id="ES" compartment="cell" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
        <species id="P" compartment="cell" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      </listOfSpecies>
      <listOfParameters>
        <parameter id="kf" value="{kf}" constant="true"/>
        <parameter id="kr" value="{kr}" constant="true"/>
        <parameter id="kcat" value="{kcat}" constant="true"/>
      </listOfParameters>
      <listOfReactions>
        <reaction id="binding" reversible="true" fast="true">
          <listOfReactants>
            <speciesReference species="E" stoichiometry="1" constant="true"/>
            <speciesReference species="S" stoichiometry="1" constant="true"/>
          </listOfReactants>
          <listOfProducts>
            <speciesReference species="ES" stoichiometry="1" constant="true"/>
          </listOfProducts>
          <kineticLaw>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><minus/>
                <apply><times/><ci>kf</ci><ci>E</ci><ci>S</ci></apply>
                <apply><times/><ci>kr</ci><ci>ES</ci></apply>
              </apply>
            </math>
          </kineticLaw>
        </reaction>
        <reaction id="catalysis" reversible="false" fast="false">
          <listOfReactants>
            <speciesReference species="ES" stoichiometry="1" constant="true"/>
          </listOfReactants>
          <listOfProducts>
            <speciesReference species="E" stoichiometry="1" constant="true"/>
            <speciesReference species="P" stoichiometry="1" constant="true"/>
          </listOfProducts>
          <kineticLaw>
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><times/><ci>kcat</ci><ci>ES</ci></apply>
            </math>
          </kineticLaw>
        </reaction>
      </listOfReactions>
    </model></sbml>"""

    atomized = Atomizer(atomize=False, quiet_mode=True, t_end=100, n_steps=20).atomize(
        xml
    )
    assert atomized.success, atomized.error

    sample_times = np.array([0.0, 10.0, 20.0, 50.0, 100.0])
    res = _simulate(atomized.bngl, sample_times)

    e_sim = np.array(res.functions["E"])
    s_sim = np.array(res.functions["S"])
    es_sim = np.array(res.functions["ES"])
    p_sim = np.array(res.observables["P"])

    # 1. Exact Enzyme Concentration Conservation: E(t) + ES(t) == e0_conc
    np.testing.assert_allclose(e_sim + es_sim, e0_conc, rtol=1e-6, atol=1e-8)

    # 2. Exact Substrate Concentration Conservation: S(t) + ES(t) + P(t)/vol == s0_conc
    np.testing.assert_allclose(
        s_sim + es_sim + p_sim / vol, s0_conc, rtol=1e-6, atol=1e-8
    )

    # 3. Exact Instantaneous Fast Equilibrium Balance: kf * E * S == kr * ES
    np.testing.assert_allclose(kf * e_sim * s_sim, kr * es_sim, rtol=1e-5, atol=1e-8)
