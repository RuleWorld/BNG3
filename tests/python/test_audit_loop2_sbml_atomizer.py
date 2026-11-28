"""Loop 2 audit regression tests for SBML Atomizer Core, Multi, MathML, and Delay lowering.

Covers confirmed bugs:
- L2-04-06: Static ``delay(f(time), tau)`` folding clamps ``time - tau`` to ``t0 = 0``.
- L2-09-01: Unified topological ``t = 0`` ``initialAssignment`` resolution & fail-closed
  refusal of unresolvable time-varying initial assignments (never mutated into live rules).
- L2-09-02: SBML ``multi`` ``speciesFeatureType`` with ``occur > 1`` preserves BNGL
  multiset component symmetry, statistical factors, observable matching, and disjoint DNF.
- L2-09-08: Non-decimal ``<log><logbase>`` is accepted losslessly without stale warnings.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

import bionetgen
from bionetgen.atomizer.modern import Atomizer, SBMLParser
from bionetgen.atomizer.modern.multi import parse_multi_package

MATHML_NS = "http://www.w3.org/1998/Math/MathML"
MULTI_NS = "http://www.sbml.org/sbml/level3/version1/multi/version1"
TIME_CSYMBOL = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>'
)
DELAY_CSYMBOL = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol>'
)


def _write_and_sim(
    tmp_path: Path,
    name: str,
    sbml_xml: str,
    *,
    t_end: float = 10.0,
    n_steps: int = 50,
    atomize: bool = True,
    rtol: float = 1e-9,
    atol: float = 1e-12,
):
    path = tmp_path / f"{name}.xml"
    path.write_text(sbml_xml, encoding="utf-8")
    model = bionetgen.from_sbml(str(path), atomize=atomize)
    return model.simulate(
        method="ode", t_end=t_end, n_steps=n_steps, rtol=rtol, atol=atol
    )


def _obs(sim, name: str):
    if f"{name}_amt" in sim.observables:
        return sim.observables[f"{name}_amt"]
    return sim.observables[name]


# ---------------------------------------------------------------------------
# L2-04-06: delay(f(time), tau) clamping at t < tau
# ---------------------------------------------------------------------------


def _delay_time_sbml(kinetic_law_xml: str, extra_rules_xml: str = "") -> str:
    rules_block = (
        f"<listOfRules>{extra_rules_xml}</listOfRules>" if extra_rules_xml else ""
    )
    params_block = (
        '<listOfParameters><parameter id="y" constant="false"/></listOfParameters>'
        if extra_rules_xml
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="delay_time_clamp">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="c" initialAmount="1" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    {params_block}
    {rules_block}
    <listOfReactions>
      <reaction id="rX" reversible="false">
        <listOfReactants><speciesReference species="X" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><cn>0.5</cn><ci>X</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="rB" reversible="false">
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}">{kinetic_law_xml}</math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def test_l2_04_06_delay_singular_time_expressions_clamp_to_t0(tmp_path):
    """delay(10/(1+time), 1), delay(ln(1+time), 1), delay(sqrt(time), 1) must not crash at t=0."""

    # 10/(1 + max(0, t-1)): 10 on [0,1], 10/t on [1,3] => integral = 10 + 10*ln(3)
    res_div = _write_and_sim(
        tmp_path,
        "delay_div",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}"
            f"<apply><divide/><cn>10</cn><apply><plus/><cn>1</cn>{TIME_CSYMBOL}</apply></apply>"
            f"<cn>1.0</cn></apply>"
        ),
        t_end=3.0,
        n_steps=30,
    )
    assert float(_obs(res_div, "B")[-1]) == pytest.approx(
        10.0 + 10.0 * math.log(3.0), rel=1e-5
    )

    # ln(1 + max(0, t-1)): 0 on [0,1], ln(t) on [1,3] => integral = 3*ln(3) - 2
    res_ln = _write_and_sim(
        tmp_path,
        "delay_ln",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}"
            f"<apply><ln/><apply><plus/><cn>1</cn>{TIME_CSYMBOL}</apply></apply>"
            f"<cn>1.0</cn></apply>"
        ),
        t_end=3.0,
        n_steps=30,
    )
    assert float(_obs(res_ln, "B")[-1]) == pytest.approx(
        3.0 * math.log(3.0) - 2.0, rel=1e-5
    )

    # sqrt(max(0, t-1)): 0 on [0,1], sqrt(t-1) on [1,3] => integral = (2/3) * 2^(3/2)
    res_sqrt = _write_and_sim(
        tmp_path,
        "delay_sqrt",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}<apply><root/>{TIME_CSYMBOL}</apply><cn>1.0</cn></apply>"
        ),
        t_end=3.0,
        n_steps=30,
    )
    assert float(_obs(res_sqrt, "B")[-1]) == pytest.approx(
        (2.0 / 3.0) * (2.0**1.5), rel=1e-5
    )


def test_l2_04_06_delay_folded_and_runtime_time_expressions_agree(tmp_path):
    """Statically folded delay(2+time, 1) must match runtime delay(2+time+0*X, 1) and exact math."""

    res_folded = _write_and_sim(
        tmp_path,
        "delay_folded",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}<apply><plus/><cn>2</cn>{TIME_CSYMBOL}</apply><cn>1.0</cn></apply>"
        ),
        t_end=3.0,
        n_steps=30,
    )
    res_runtime = _write_and_sim(
        tmp_path,
        "delay_runtime",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}"
            f"<apply><plus/><apply><plus/><cn>2</cn>{TIME_CSYMBOL}</apply>"
            f"<apply><times/><cn>0</cn><ci>X</ci></apply></apply>"
            f"<cn>1.0</cn></apply>"
        ),
        t_end=3.0,
        n_steps=30,
    )
    b_folded = _obs(res_folded, "B")
    b_runtime = _obs(res_runtime, "B")
    assert float(b_folded[10]) == pytest.approx(2.0, rel=1e-6)
    assert float(b_folded[-1]) == pytest.approx(8.0, rel=1e-6)
    assert float(b_runtime[10]) == pytest.approx(float(b_folded[10]), rel=1e-6)
    assert float(b_runtime[-1]) == pytest.approx(float(b_folded[-1]), rel=1e-6)


def test_l2_04_06_delay_assignment_rule_and_nested_delay_clamp(tmp_path):
    """AssignmentRule referencing time and nested delay(delay(2+time, 0.5), 0.7) clamp to t0."""

    res_ar = _write_and_sim(
        tmp_path,
        "delay_ar",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}<ci>y</ci><cn>1.0</cn></apply>",
            extra_rules_xml=(
                f'<assignmentRule variable="y"><math xmlns="{MATHML_NS}">'
                f"<apply><divide/><cn>10</cn><apply><plus/><cn>1</cn>{TIME_CSYMBOL}</apply></apply>"
                f"</math></assignmentRule>"
            ),
        ),
        t_end=3.0,
        n_steps=30,
    )
    assert float(_obs(res_ar, "B")[-1]) == pytest.approx(
        10.0 + 10.0 * math.log(3.0), rel=1e-5
    )

    # delay(delay(2+time, 0.5), 0.7) = 2 on [0, 1.2], 2 + (t - 1.2) on [1.2, 3.0]
    # integral = 2*1.2 + (2*1.8 + 0.5*1.8^2) = 2.4 + 3.6 + 1.62 = 7.62
    res_nested = _write_and_sim(
        tmp_path,
        "delay_nested",
        _delay_time_sbml(
            f"<apply>{DELAY_CSYMBOL}"
            f"<apply>{DELAY_CSYMBOL}<apply><plus/><cn>2</cn>{TIME_CSYMBOL}</apply><cn>0.5</cn></apply>"
            f"<cn>0.7</cn></apply>"
        ),
        t_end=3.0,
        n_steps=30,
    )
    assert float(_obs(res_nested, "B")[-1]) == pytest.approx(7.62, rel=1e-5)


# ---------------------------------------------------------------------------
# L2-09-01: initialAssignment topological dependency folding & live-rule guard
# ---------------------------------------------------------------------------


def test_l2_09_01_ia_reads_compartment_ia_overrides_declared_size(tmp_path):
    """Parameter IA reading compartment IA must see C=4.0, not declared size=1.0."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ia_param_reads_ia_comp">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1.0" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="10.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" constant="true"/></listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>0.1</cn><ci>C</ci></apply></math>
      </initialAssignment>
      <initialAssignment symbol="C">
        <math xmlns="{MATHML_NS}"><cn>4.0</cn></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    sim = _write_and_sim(tmp_path, "ia_comp", sbml, t_end=10.0, n_steps=50)
    expected_a = 10.0 * math.exp(-0.4 * 10.0)
    assert float(_obs(sim, "A")[-1]) == pytest.approx(expected_a, rel=1e-5)
    assert float(_obs(sim, "B")[-1]) == pytest.approx(10.0 - expected_a, rel=1e-5)


def test_l2_09_01_ia_reads_species_ia_overrides_declared_initial_amount(tmp_path):
    """Parameter IA reading species IA must see A(0)=10.0, not declared initialAmount=1.0."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ia_param_reads_ia_species">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="1.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" constant="true"/></listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>0.05</cn><ci>A</ci></apply></math>
      </initialAssignment>
      <initialAssignment symbol="A">
        <math xmlns="{MATHML_NS}"><cn>10.0</cn></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    sim = _write_and_sim(tmp_path, "ia_sp", sbml, t_end=10.0, n_steps=50)
    expected_a = 10.0 * math.exp(-0.5 * 10.0)
    assert float(_obs(sim, "A")[-1]) == pytest.approx(expected_a, rel=1e-5)


def test_l2_09_01_ia_reads_species_assignment_rule_overrides_declared_amount(tmp_path):
    """Parameter IA reading an assignment-ruled species must evaluate rule math at t=0."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ia_param_reads_ar_species">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="C" initialAmount="1.0" hasOnlySubstanceUnits="true"
               boundaryCondition="true" constant="false"/>
      <species id="A" compartment="C" initialAmount="10.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" constant="true"/></listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>0.05</cn><ci>S</ci></apply></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="S">
        <math xmlns="{MATHML_NS}"><cn>10.0</cn></math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    sim = _write_and_sim(tmp_path, "ia_ar_sp", sbml, t_end=10.0, n_steps=50)
    expected_a = 10.0 * math.exp(-0.5 * 10.0)
    assert float(_obs(sim, "A")[-1]) == pytest.approx(expected_a, rel=1e-5)


def test_l2_09_01_ia_reads_rate_ruled_parameter_freezes_t0_value(tmp_path):
    """Parameter IA reading a rate-ruled parameter must freeze p1(0)=0.2, never emit a live rule."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ia_param_reads_rr_param">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="10.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="p1" value="0.2" constant="false"/>
      <parameter id="k" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>1.0</cn><ci>p1</ci></apply></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <rateRule variable="p1"><math xmlns="{MATHML_NS}"><cn>0.5</cn></math></rateRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert atomized.success, atomized.error
    assert "k() =" not in atomized.bngl
    assert "__assign_rule__k()" not in atomized.bngl

    sim = _write_and_sim(tmp_path, "ia_rr", sbml, t_end=10.0, n_steps=50)
    expected_a = 10.0 * math.exp(-0.2 * 10.0)
    assert float(_obs(sim, "A")[-1]) == pytest.approx(expected_a, rel=1e-5)


def test_l2_09_01_multi_hop_cross_entity_ia_chain_and_concentration_units(tmp_path):
    """Reverse-ordered chain p0 -> C -> concentration species S -> k1 -> k2 resolves cleanly."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ia_chain">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="C" initialAmount="12.0" hasOnlySubstanceUnits="false"
               boundaryCondition="true" constant="false"/>
      <species id="A" compartment="C" initialAmount="10.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="p0" value="0.0" constant="true"/>
      <parameter id="k1" constant="true"/>
      <parameter id="k2" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k2">
        <math xmlns="{MATHML_NS}"><apply><plus/><ci>k1</ci><cn>0.2</cn></apply></math>
      </initialAssignment>
      <initialAssignment symbol="k1">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>0.1</cn><ci>S</ci></apply></math>
      </initialAssignment>
      <initialAssignment symbol="C">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>2.0</cn><ci>p0</ci></apply></math>
      </initialAssignment>
      <initialAssignment symbol="p0">
        <math xmlns="{MATHML_NS}"><cn>2.0</cn></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><ci>k2</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    # p0=2 -> C=4 -> [S]=12/4=3 -> k1=0.3 -> k2=0.5 => A(10)=10*exp(-5)
    sim = _write_and_sim(tmp_path, "ia_chain", sbml, t_end=10.0, n_steps=50)
    expected_a = 10.0 * math.exp(-0.5 * 10.0)
    assert float(_obs(sim, "A")[-1]) == pytest.approx(expected_a, rel=1e-5)


def test_l2_09_01_compartment_ia_reading_reacting_species_freezes_at_t0(tmp_path):
    """A compartment IA reading a reacting species must keep its t=0 size, not track the species."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="comp_ia_reacting_species">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="false"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="10.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfInitialAssignments>
      <initialAssignment symbol="C">
        <math xmlns="{MATHML_NS}"><apply><times/><cn>0.2</cn><ci>A</ci></apply></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><cn>0.1</cn><ci>C</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert atomized.success, atomized.error
    assert "__compartment_C__ 2" in atomized.bngl
    assert "C() =" not in atomized.bngl

    sim = _write_and_sim(tmp_path, "comp_ia_sp", sbml, t_end=5.0, n_steps=25)
    # C(0) = 0.2 * 10 = 2.0 fixed -> rate = 0.2 * A -> A(5) = 10 * exp(-1)
    assert float(_obs(sim, "A")[-1]) == pytest.approx(10.0 * math.exp(-1.0), rel=1e-5)


def test_l2_09_01_unresolvable_time_varying_ia_fails_closed(tmp_path):
    """An unfolded time-varying IA (depending on a nonlinear algebraic variable) must fail closed."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ia_alg_unresolvable">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="10.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="Z" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" constant="true"/></listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k">
        <math xmlns="{MATHML_NS}"><ci>Z</ci></math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <algebraicRule>
        <math xmlns="{MATHML_NS}">
          <apply><minus/>
            <apply><plus/><apply><power/><ci>Z</ci><cn>3</cn></apply><ci>Z</ci></apply>
            <ci>A</ci>
          </apply>
        </math>
      </algebraicRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><cn>0.01</cn><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    path = tmp_path / "ia_alg_unresolvable.xml"
    path.write_text(sbml, encoding="utf-8")
    with pytest.raises(bionetgen.BioNetGenError, match="initialAssignment"):
        bionetgen.from_sbml(str(path))


# ---------------------------------------------------------------------------
# L2-09-02: SBML Multi speciesFeatureType occur > 1 multiset symmetry
# ---------------------------------------------------------------------------


def test_l2_09_02_multi_occur2_preserves_multiset_symmetry_and_stat_factors(tmp_path):
    """occur=2 speciesFeatureType must emit identical BNGL components and exact binomial kinetics."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}"
      level="3" version="1" multi:required="true">
  <model id="multi_occur2">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="st_P" multi:compartment="C">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="sft_p" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="v_u"/>
              <multi:possibleSpeciesFeatureValue multi:id="v_p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
    <listOfSpecies>
      <species id="P_uu" compartment="C" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="2">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_up" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_p"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_pp" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="2">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_p"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_u_any" compartment="C" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_p_any" compartment="C" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_p"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R_phos" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r1" species="P_u_any" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference id="p1" species="P_p_any" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><cn>0.2</cn><ci>P_u_any</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    parsed = parse_multi_package(sbml)
    assert parsed.executable is True
    assert parsed.type_patterns["st_P"] == "st_P(sft_p~v_u~v_p,sft_p~v_u~v_p)@C"
    assert "sft_p_1" not in parsed.type_patterns["st_P"]
    assert "sft_p_2" not in parsed.type_patterns["st_P"]

    sim = _write_and_sim(tmp_path, "multi_occur2", sbml, t_end=5.0, n_steps=50)
    e = math.exp(-0.2 * 5.0)
    expected_uu = 10.0 * (e**2)
    expected_up = 20.0 * e * (1.0 - e)
    expected_pp = 10.0 * ((1.0 - e) ** 2)
    assert float(_obs(sim, "P_uu")[-1]) == pytest.approx(expected_uu, rel=1e-4)
    assert float(_obs(sim, "P_up")[-1]) == pytest.approx(expected_up, rel=1e-4)
    assert float(_obs(sim, "P_pp")[-1]) == pytest.approx(expected_pp, rel=1e-4)
    assert float(_obs(sim, "P_u_any")[-1]) == pytest.approx(
        expected_uu + expected_up, rel=1e-4
    )
    assert float(_obs(sim, "P_p_any")[-1]) == pytest.approx(
        expected_up + expected_pp, rel=1e-4
    )


def test_l2_09_02_multi_occur3_preserves_three_site_binomial_kinetics(tmp_path):
    """occur=3 speciesFeatureType generates all 4 phosphorylation states with exact 3:2:1 rates."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}"
      level="3" version="1" multi:required="true">
  <model id="multi_occur3">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="st_P" multi:compartment="C">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="sft_p" multi:occur="3">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="v_u"/>
              <multi:possibleSpeciesFeatureValue multi:id="v_p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
    <listOfSpecies>
      <species id="P_uuu" compartment="C" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="3">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_ppp" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="3">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_p"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_u_any" compartment="C" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_p_any" compartment="C" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_p"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R_phos" reversible="false" fast="false">
        <listOfReactants><speciesReference id="r1" species="P_u_any" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference id="p1" species="P_p_any" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="{MATHML_NS}"><apply><times/><cn>0.2</cn><ci>P_u_any</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    sim = _write_and_sim(tmp_path, "multi_occur3", sbml, t_end=5.0, n_steps=50)
    e = math.exp(-0.2 * 5.0)
    assert float(_obs(sim, "P_uuu")[-1]) == pytest.approx(10.0 * (e**3), rel=1e-4)
    assert float(_obs(sim, "P_ppp")[-1]) == pytest.approx(
        10.0 * ((1.0 - e) ** 3), rel=1e-4
    )
    assert float(_obs(sim, "P_u_any")[-1]) == pytest.approx(
        10.0 * (1.0 - (1.0 - e) ** 3), rel=1e-4
    )


def test_l2_09_02_multi_occur2_multivalue_dnf_is_pairwise_disjoint(tmp_path):
    """Multi-value speciesFeature on occur=2 emits pairwise-disjoint multiset DNF variants."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="{MULTI_NS}"
      level="3" version="1" multi:required="true">
  <model id="multi_occur2_dnf">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="st_P" multi:compartment="C">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="sft_p" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="v_u"/>
              <multi:possibleSpeciesFeatureValue multi:id="v_p"/>
              <multi:possibleSpeciesFeatureValue multi:id="v_q"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
    <listOfSpecies>
      <species id="P_uq" compartment="C" initialAmount="4" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_q"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_up" compartment="C" initialAmount="3" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_u"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_p"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_qq" compartment="C" initialAmount="5" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="2">
            <multi:listOfSpeciesFeatureValues><multi:speciesFeatureValue multi:value="v_q"/></multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="P_has_u_or_p" compartment="C" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="st_P">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="sft_p" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="v_u"/>
              <multi:speciesFeatureValue multi:value="v_p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
  </model>
</sbml>"""

    parsed = parse_multi_package(sbml)
    assert parsed.executable is True
    # 5 canonical concrete multiset pairs containing at least one of {v_u, v_p}:
    # (u,u), (u,p), (u,q), (p,p), (p,q) -- no symmetric duplicates!
    assert len(parsed.species_pattern_variants["P_has_u_or_p"]) == 5

    sim = _write_and_sim(tmp_path, "multi_occur2_dnf", sbml, t_end=1.0, n_steps=5)
    # P_uq (4) + P_up (3) = 7.0 exactly (no double counting!), P_qq (5) excluded.
    assert float(_obs(sim, "P_has_u_or_p")[0]) == pytest.approx(7.0, rel=1e-9)


# ---------------------------------------------------------------------------
# L2-09-08: Non-decimal <log><logbase> accepted without stale warning
# ---------------------------------------------------------------------------


def test_l2_09_08_non_decimal_logbase_accepted_losslessly(tmp_path):
    """<log><logbase> with base 2 and base 5 must succeed without allow_lossy=True."""

    sbml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="math_log_base2">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1.0" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="2.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="p" value="0.0" constant="false"/>
      <parameter id="c5" constant="true"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="c5">
        <math xmlns="{MATHML_NS}">
          <apply><log/><logbase><cn>5</cn></logbase><cn>25</cn></apply>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="p">
        <math xmlns="{MATHML_NS}">
          <apply><log/><logbase><cn>2</cn></logbase><apply><plus/><ci>A</ci><cn>6</cn></apply></apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="{MATHML_NS}">
            <apply><times/><cn>0.1</cn><ci>p</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""

    parsed = SBMLParser().parse(sbml)
    mathml_warnings = [
        w for w in parsed.import_warnings if w.get("category") == "mathml"
    ]
    assert mathml_warnings == []
    assert parsed.parameters["c5"].value == pytest.approx(2.0, rel=1e-12)

    path = tmp_path / "math_log_base2.xml"
    path.write_text(sbml, encoding="utf-8")
    bngl_text = bionetgen.sbml_to_bngl(str(path))
    assert "ln(" in bngl_text

    sim = _write_and_sim(tmp_path, "math_log_base2_sim", sbml, t_end=2.0, n_steps=20)
    assert float(sim.functions["p"][0]) == pytest.approx(3.0, rel=1e-9)
    # Exact check: dA/dt = -0.1 * log2(A + 6), A(0) = 2 => B(2) = 0.5890378...
    assert float(_obs(sim, "B")[-1]) == pytest.approx(0.5890378, rel=1e-5)
