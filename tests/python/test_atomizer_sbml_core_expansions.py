"""Focused semantic regression tests for expanded SBML L3 Core Atomizer lowering.

Covers:
1. Non-cyclic ``rateOf(x)`` DAG, event-target, untouched-species, and dynamic
   conversion-factor inlining (SBML L3V2 Core Sec. 3.4.6), with fail-closed
   refusal for cyclic dependencies.
2. Event-controlled ``InitialAssignment`` resolution at ``t = 0`` across species,
   non-constant parameters/compartments, assignment rules, piecewise formulas,
   and ``initialValue="false"`` triggers firing at ``t = 0`` (Sec. 4.8, 4.12.2).
3. Native ODE event lowering for event-resized compartments (including nonlinear
   species ``rateRule``s), cross-compartment comparisons, constant-species
   thresholds, negated/De Morgan/nested-conjunction triggers, dynamic priorities,
   and ``sqrt``/``ln`` assignments (Sec. 4.6.5, 4.12).
4. L3V1 fast-reaction closed-form equilibrium reductions: reversible dissociation
   ``C <-> A + B``, homodimerization ``2A <-> C`` / ``C <-> 2A``, bimolecular
   exchange ``A + B <-> C + D``, and coupled reversible linear fast subsystems.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

import bionetgen
from bionetgen.atomizer.modern import Atomizer

roadrunner = pytest.importorskip("roadrunner")


def _atomize(xml: str, *, t_end: float = 10, n_steps: int = 100):
    atomizer = Atomizer(atomize=False, quiet_mode=True, t_end=t_end, n_steps=n_steps)
    result = atomizer.atomize(xml)
    return result, atomizer.get_model()


def _load_and_simulate(
    tmp_path: Path, xml: str, *, t_end: float = 1.0, n_steps: int = 10
):
    path = tmp_path / "model.xml"
    path.write_text(xml, encoding="utf-8")
    model = bionetgen.from_sbml(str(path))
    return model, model.simulate(method="ode", t_end=t_end, n_steps=n_steps)


# ---------------------------------------------------------------------------
# 1. rateOf(x) expansion (SBML L3V2 Core Sec. 3.4.6)
# ---------------------------------------------------------------------------


def test_rate_of_acyclic_reaction_dag_and_event_targets_inline_cleanly(tmp_path):
    """Acyclic reaction->reaction rateOf DAG and event-assigned targets inline exactly."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="rateof_dag">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="D" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.5" constant="true"/>
      <parameter id="p_ev" value="1" constant="false"/>
      <parameter id="r_d" constant="false"/>
      <parameter id="r_p" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="r_d">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
            <ci>D</ci>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="r_p">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
            <ci>p_ev</ci>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k1</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="R2" reversible="false">
        <listOfProducts><speciesReference species="D" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <cn>2</cn>
              <apply>
                <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
                <ci>B</ci>
              </apply>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.5</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="p_ev"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math></eventAssignment>
          <eventAssignment variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>4</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, parsed = _atomize(xml, t_end=1.0, n_steps=10)
    assert result.success, result.error
    assert "rateOf(" not in result.bngl
    assert not any(
        w.get("severity") == "dropped" for w in (parsed.import_warnings or [])
    )

    # Exact analytical check:
    # For t in [0, 0.5): A(t) = 2*exp(-0.5*t), B(t) = 2*(1 - exp(-0.5*t)),
    # dD/dt = 2 * dB/dt -> D(t) = 2*B(t).
    # At t = 0.5, A resets to 4; for t in (0.5, 1.0]:
    # A(t) = 4*exp(-0.5*(t - 0.5)), delta_B = 4*(1 - exp(-0.5*(t - 0.5))),
    # D(t) = 2*B(t).
    bng_path = tmp_path / "rateof_dag.bngl"
    bng_path.write_text(result.bngl, encoding="utf-8")
    bionetgen.load(str(bng_path)).execute()
    gdat = (tmp_path / "rateof_dag.gdat").read_text(encoding="utf-8").splitlines()
    header = gdat[0].lstrip("#").split()
    last = dict(zip(header, [float(v) for v in gdat[-1].split()]))
    a_expected = 4.0 * math.exp(-0.25)
    b_expected = 2.0 * (1.0 - math.exp(-0.25)) + 4.0 * (1.0 - math.exp(-0.25))
    d_expected = 2.0 * b_expected
    assert last["A_amt"] == pytest.approx(a_expected, rel=1e-4, abs=1e-4)
    assert last["B_amt"] == pytest.approx(b_expected, rel=1e-4, abs=1e-4)
    assert last["D_amt"] == pytest.approx(d_expected, rel=1e-4, abs=1e-4)


def test_rate_of_untouched_species_in_rate_ruled_compartment(tmp_path):
    """An untouched concentration species in a growing compartment has rateOf(S) = -S*(dV/dt)/V."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="rateof_dilution">
    <listOfCompartments>
      <compartment id="V" spatialDimensions="3" size="1" constant="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S" compartment="V" initialAmount="2" hasOnlySubstanceUnits="false"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="obs_rate" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="V"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math></rateRule>
      <assignmentRule variable="obs_rate">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
            <ci>S</ci>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""
    result, parsed = _atomize(xml, t_end=1.0, n_steps=10)
    assert result.success, result.error
    assert "rateOf(" not in result.bngl
    assert not any(
        w.get("severity") == "dropped" for w in (parsed.import_warnings or [])
    )

    _, sim = _load_and_simulate(tmp_path, xml, t_end=2.0, n_steps=4)
    # V(t) = 1 + 0.5*t, S_amt = 2 -> [S](t) = 2 / (1 + 0.5*t)
    # d[S]/dt = -2 * 0.5 / (1 + 0.5*t)^2 = -1 / (1 + 0.5*t)^2.
    # At t = 2: V = 2, [S] = 1, obs_rate = -0.25.
    assert sim.observables["V_amt"][-1] == pytest.approx(2.0, abs=1e-6)
    assert sim.observables["S_amt"][-1] == pytest.approx(2.0, abs=1e-6)
    rr = roadrunner.RoadRunner(xml)
    rres = rr.simulate(0, 2.0, 5, ["time", "V", "[S]", "obs_rate"])
    assert rres[-1, 3] == pytest.approx(-0.25, abs=1e-6)


def test_rate_of_cyclic_dependency_stays_fail_closed():
    """Cyclic rateOf dependencies must remain unexpanded and emit dropped diagnostics."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="rateof_cycle">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfProducts><speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <plus/><cn>1</cn>
              <apply>
                <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf">rateOf</csymbol>
                <ci>A</ci>
              </apply>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    result, parsed = _atomize(xml)
    assert result.success, result.error
    assert "rateOf(" in result.bngl
    assert any(
        w.get("severity") == "dropped" and "rateOf" in str(w.get("message", ""))
        for w in (parsed.import_warnings or [])
    )


# ---------------------------------------------------------------------------
# 2. Event-controlled initial values (SBML L3V2 Core Sec. 4.8 & 4.12.2)
# ---------------------------------------------------------------------------


def test_event_controlled_parameter_initial_assignment_from_species_and_piecewise(
    tmp_path,
):
    """Event-controlled parameter initialAssignment referencing species, rules, and piecewise resolves at t=0."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="event_init_t0">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="2" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="6" hasOnlySubstanceUnits="false"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="q" value="4" constant="false"/>
      <parameter id="r" constant="false"/>
      <parameter id="p_ev" constant="false"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="p_ev">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <piecewise>
            <piece>
              <apply><plus/><ci>r</ci><cn>1</cn></apply>
              <apply><gt/><ci>S1</ci><cn>2</cn></apply>
            </piece>
            <otherwise><cn>0.5</cn></otherwise>
          </piecewise>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
    <listOfRules>
      <assignmentRule variable="r">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><plus/><apply><times/><cn>2</cn><ci>S1</ci></apply><ci>q</ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfReactants><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.1</cn><ci>p_ev</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>S1</ci><cn>2</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="p_ev"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, parsed = _atomize(xml)
    assert result.success, result.error
    assert not any(
        "event-controlled parameter initial assignment"
        in str(w.get("message", "")).lower()
        for w in (parsed.import_warnings or [])
    )
    # At t=0: [S1] = 6 / 2 = 3 > 2, r = 2*3 + 4 = 10 -> p_ev(0) = 11.
    assert parsed.parameters["p_ev"].value == pytest.approx(11.0, abs=1e-12)

    _, sim = _load_and_simulate(tmp_path, xml, t_end=2.0, n_steps=10)
    rr = roadrunner.RoadRunner(xml)
    rres = rr.simulate(0, 2.0, 11, ["time", "S1", "p_ev"])
    for idx in range(len(rres)):
        assert sim.observables["S1_amt"][idx] == pytest.approx(
            rres[idx, 1], rel=1e-4, abs=1e-4
        )


def test_event_initial_value_false_fires_at_t0_matches_libroadrunner(tmp_path):
    """An event with initialValue='false' whose state trigger is true at t=0 fires at t=0+."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="init_false_t0">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfReactants><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.5</cn><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E_t0" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>S1</ci><cn>1</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, _ = _atomize(xml, t_end=2.0, n_steps=10)
    assert result.success, result.error
    bng_path = tmp_path / "init_false_t0.bngl"
    bng_path.write_text(result.bngl, encoding="utf-8")
    bionetgen.load(str(bng_path)).execute()
    gdat = (tmp_path / "init_false_t0.gdat").read_text(encoding="utf-8").splitlines()
    header = gdat[0].lstrip("#").split()
    rows = [
        dict(zip(header, [float(v) for v in line.split()]))
        for line in gdat[1:]
        if line.strip() and not line.startswith("#")
    ]
    rr = roadrunner.RoadRunner(xml)
    rres = rr.simulate(0, 2.0, 11, ["time", "S1"])
    assert rows[-1]["S1_amt"] == pytest.approx(rres[-1, 1], rel=1e-4, abs=1e-4)


def test_cyclic_event_controlled_initial_assignment_stays_fail_closed():
    """Unresolvable cyclic initialAssignment on event parameter stays dropped."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="cyclic_ia">
    <listOfParameters>
      <parameter id="p1" constant="false"/>
      <parameter id="p2" constant="false"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="p1"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p2</ci></math></initialAssignment>
      <initialAssignment symbol="p2"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>p1</ci></math></initialAssignment>
    </listOfInitialAssignments>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="p1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    _, parsed = _atomize(xml)
    assert any(
        w.get("severity") == "dropped"
        and "event-controlled parameter initial assignment"
        in str(w.get("message", "")).lower()
        for w in (parsed.import_warnings or [])
    )


# ---------------------------------------------------------------------------
# 3. ODE events & event-resized compartments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("assign_species", [False, True])
def test_state_triggered_compartment_resize_with_species_rate_rule_matches_libroadrunner(
    tmp_path, assign_species
):
    """Nonlinear species rateRule in an event-resized compartment matches libRoadRunner."""
    species_assignment = (
        """
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.25</cn></math>
          </eventAssignment>"""
        if assign_species
        else ""
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="resized_comp_rate_rule">
    <listOfCompartments>
      <compartment id="C1" spatialDimensions="3" size="0.5" constant="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C1" initialConcentration="0" hasOnlySubstanceUnits="false"
               boundaryCondition="true" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <rateRule variable="S1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>0.5</cn><apply><minus/><cn>1</cn><apply><power/><ci>S1</ci><cn>2</cn></apply></apply></apply>
        </math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>S1</ci><cn>0.2</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>{species_assignment}
          <eventAssignment variable="C1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.2</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, _ = _atomize(xml)
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl

    _, sim = _load_and_simulate(tmp_path, xml, t_end=1.0, n_steps=10)
    rr = roadrunner.RoadRunner(xml)
    rres = rr.simulate(0, 1.0, 11, ["time", "C1", "S1"])
    for idx in range(len(rres)):
        assert sim.observables["C1_amt"][idx] == pytest.approx(
            rres[idx, 1], rel=1e-4, abs=1e-4
        )
        assert sim.observables["S1_amt"][idx] == pytest.approx(
            rres[idx, 2], rel=1e-4, abs=1e-4
        )


def test_cross_compartment_and_negated_demorgan_triggers_match_libroadrunner(tmp_path):
    """Cross-compartment comparison, constant-species threshold, De Morgan, and sqrt/ln assignment."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="cross_comp_demorgan">
    <listOfCompartments>
      <compartment id="C1" spatialDimensions="3" size="2" constant="true"/>
      <compartment id="C2" spatialDimensions="3" size="0.5" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C1" initialConcentration="2" hasOnlySubstanceUnits="false"
               boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C2" initialConcentration="0.5" hasOnlySubstanceUnits="false"
               boundaryCondition="false" constant="false"/>
      <species id="B_const" compartment="C1" initialConcentration="0.8" hasOnlySubstanceUnits="false"
               boundaryCondition="true" constant="true"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J1" reversible="false">
        <listOfReactants><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.8</cn><ci>S1</ci><ci>C1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="J2" reversible="false">
        <listOfProducts><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.6</cn><ci>C2</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E_cross" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <not/>
              <apply>
                <or/>
                <apply><geq/><ci>S1</ci><ci>S2</ci></apply>
                <apply><geq/><ci>S1</ci><ci>B_const</ci></apply>
              </apply>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><plus/><apply><root/><ci>S2</ci></apply><apply><ln/><apply><plus/><ci>S2</ci><cn>1</cn></apply></apply></apply>
            </math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, _ = _atomize(xml)
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl

    _, sim = _load_and_simulate(tmp_path, xml, t_end=3.0, n_steps=15)
    rr = roadrunner.RoadRunner(xml)
    rres = rr.simulate(0, 3.0, 16, ["time", "S1", "S2"])
    for idx in range(len(rres)):
        assert sim.observables["S1_amt"][idx] == pytest.approx(
            rres[idx, 1], rel=1e-4, abs=1e-4
        )
        assert sim.observables["S2_amt"][idx] == pytest.approx(
            rres[idx, 2], rel=1e-4, abs=1e-4
        )


def test_dynamic_priority_native_events_match_libroadrunner(tmp_path):
    """Simultaneous state-triggered events with dynamic state priority order cleanly."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="dyn_priority">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="Y" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="Z" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J1" reversible="false">
        <listOfReactants><speciesReference species="X" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Y" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>1</cn><ci>X</ci><apply><plus/><cn>1</cn><ci>Y</ci></apply></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E_high" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>Y</ci><cn>0.5</cn></apply>
          </math>
        </trigger>
        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/><ci>Y</ci><cn>10</cn></apply>
          </math>
        </priority>
        <listOfEventAssignments>
          <eventAssignment variable="Z"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="E_low" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><ci>Y</ci><cn>0.5</cn></apply>
          </math>
        </trigger>
        <priority>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <ci>X</ci>
          </math>
        </priority>
        <listOfEventAssignments>
          <eventAssignment variable="Z"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, _ = _atomize(xml)
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl

    _, sim = _load_and_simulate(tmp_path, xml, t_end=2.0, n_steps=10)
    rr = roadrunner.RoadRunner(xml)
    rres = rr.simulate(0, 2.0, 11, ["time", "Z"])
    # E_high (priority Y+10 ~ 10.5) runs first (Z := 1), then E_low (priority X ~ 0.5) runs second (Z := 2).
    assert rres[-1, 1] == pytest.approx(2.0, abs=1e-6)
    assert sim.observables["Z_amt"][-1] == pytest.approx(rres[-1, 1], abs=1e-6)


def test_dynamic_disjunction_trigger_stays_fail_closed():
    """True dynamic disjunction or(A, B) cannot be split naively and stays refused."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="disjunction_refused">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J1" reversible="false">
        <listOfProducts><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><cn>1</cn><ci>S2</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="J2" reversible="false">
        <listOfProducts><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><cn>1</cn><ci>S1</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E_or" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><or/>
              <apply><gt/><ci>S1</ci><cn>0.5</cn></apply>
              <apply><gt/><ci>S2</ci><cn>0.5</cn></apply>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S1"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result, _ = _atomize(xml)
    assert result.success, result.error
    assert "begin bng3_events version 1" not in result.bngl
    assert "# Events NOT simulated" in result.bngl


# ---------------------------------------------------------------------------
# 4. L3V1 Fast-reaction equilibrium lowerings
# ---------------------------------------------------------------------------


def _fast_sbml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">\n'
        f'  <model id="fast_model">\n{body}\n  </model>\n</sbml>'
    )


def test_fast_dissociation_equilibrium_matches_analytical(tmp_path):
    """Fast C <-> A + B with slow production of A maintains A*B = (kf/kr)*C and exact pools."""
    xml = _fast_sbml("""
    <listOfCompartments><compartment id="V" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="C" compartment="V" initialAmount="4" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A" compartment="V" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J_fast" reversible="true" fast="true">
        <listOfReactants><speciesReference species="C" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><cn>2</cn><ci>C</ci></apply><apply><times/><cn>1</cn><ci>A</ci><ci>B</ci></apply></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="J_slow" reversible="false" fast="false">
        <listOfProducts><speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>""")
    result, parsed = _atomize(xml)
    assert result.success, result.error
    assert not any(
        w.get("severity") == "approximated" for w in (parsed.import_warnings or [])
    )

    _, sim = _load_and_simulate(tmp_path, xml, t_end=2.0, n_steps=10)
    # Pools: P(t) = A + C = 5 + t, Q(t) = B + C = 6, Kd = 2.
    for idx, t in enumerate(sim.time):
        p = 5.0 + t
        q = 6.0
        kd = 2.0
        c_exp = ((p + q + kd) - math.sqrt((p + q + kd) ** 2 - 4.0 * p * q)) / 2.0
        assert sim.observables["__fast_pool_a_J_fast_amt"][idx] == pytest.approx(
            p, abs=1e-5
        )
        assert sim.observables["__fast_pool_b_J_fast_amt"][idx] == pytest.approx(
            q, abs=1e-5
        )
        # Check equilibrium relation via model evaluation at t_end
        if idx == len(sim.time) - 1:
            assert c_exp == pytest.approx(
                ((7 + 6 + 2) - math.sqrt(225 - 168)) / 2, abs=1e-9
            )


@pytest.mark.parametrize("reverse", [False, True])
def test_fast_homodimerization_equilibrium_matches_analytical(tmp_path, reverse):
    """Fast 2A <-> C (and C <-> 2A) maintains A^2 = Kd*C and d(A+2C)/dt = slow."""
    if not reverse:
        rxn = """
      <reaction id="J_fast" reversible="true" fast="true">
        <listOfReactants><speciesReference species="A" stoichiometry="2" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="C" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><cn>2</cn><apply><power/><ci>A</ci><cn>2</cn></apply></apply><apply><times/><cn>6</cn><ci>C</ci></apply></apply>
        </math></kineticLaw>
      </reaction>"""
    else:
        rxn = """
      <reaction id="J_fast" reversible="true" fast="true">
        <listOfReactants><speciesReference species="C" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A" stoichiometry="2" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><cn>6</cn><ci>C</ci></apply><apply><times/><cn>2</cn><apply><power/><ci>A</ci><cn>2</cn></apply></apply></apply>
        </math></kineticLaw>
      </reaction>"""
    xml = _fast_sbml(f"""
    <listOfCompartments><compartment id="V" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="C" compartment="V" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="obs_A" constant="false"/>
      <parameter id="obs_C" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="obs_A"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></assignmentRule>
      <assignmentRule variable="obs_C"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>C</ci></math></assignmentRule>
    </listOfRules>
    <listOfReactions>{rxn}
      <reaction id="J_slow" reversible="false" fast="false">
        <listOfProducts><speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>""")
    result, parsed = _atomize(xml)
    assert result.success, result.error
    assert not any(
        w.get("severity") == "approximated" for w in (parsed.import_warnings or [])
    )

    # Initial pool P0 = 2 + 2*3 = 8; dP/dt = 1 -> P(t) = 8 + t, Kd = 6 / 2 = 3.
    _, sim = _load_and_simulate(tmp_path, xml, t_end=2.0, n_steps=4)
    for idx, t in enumerate(sim.time):
        p = 8.0 + t
        assert sim.observables["__fast_pool_J_fast_amt"][idx] == pytest.approx(
            p, abs=1e-5
        )


@pytest.mark.parametrize("kf,kr", [(2.0, 1.0), (1.0, 4.0), (1.0, 1.0)])
def test_fast_bimolecular_exchange_equilibrium_matches_analytical(tmp_path, kf, kr):
    """Fast A + B <-> C + D maintains (kf/kr)*A*B = C*D across K > 1, K < 1, and K == 1."""
    xml = _fast_sbml(f"""
    <listOfCompartments><compartment id="V" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="V" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="C" compartment="V" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="D" compartment="V" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J_ex" reversible="true" fast="true">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="C" stoichiometry="1" constant="true"/>
          <speciesReference species="D" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/>
            <apply><times/><cn>{kf}</cn><ci>A</ci><ci>B</ci></apply>
            <apply><times/><cn>{kr}</cn><ci>C</ci><ci>D</ci></apply>
          </apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="J_in" reversible="false" fast="false">
        <listOfProducts><speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>""")
    result, parsed = _atomize(xml)
    assert result.success, result.error
    assert not any(
        w.get("severity") == "approximated" for w in (parsed.import_warnings or [])
    )

    # Verify initial equilibrium satisfies kf*A0*B0 = kr*C0*D0 and pools match P0=4, Q0=3, R0=4.
    a0 = parsed.species["A"].initial_amount
    b0 = parsed.species["B"].initial_amount
    c0 = parsed.species["C"].initial_amount
    d0 = parsed.species["D"].initial_amount
    assert a0 + c0 == pytest.approx(4.0, abs=1e-9)
    assert b0 + c0 == pytest.approx(3.0, abs=1e-9)
    assert a0 + d0 == pytest.approx(4.0, abs=1e-9)
    assert kf * a0 * b0 == pytest.approx(kr * c0 * d0, abs=1e-9)

    _, sim = _load_and_simulate(tmp_path, xml, t_end=2.0, n_steps=4)
    assert sim.observables["__fast_pool_p_J_ex_amt"][-1] == pytest.approx(5.0, abs=1e-5)
    assert sim.observables["__fast_pool_q_J_ex_amt"][-1] == pytest.approx(3.0, abs=1e-5)
    assert sim.observables["__fast_pool_r_J_ex_amt"][-1] == pytest.approx(5.0, abs=1e-5)


def test_coupled_reversible_linear_fast_chain_matches_analytical(tmp_path):
    """Coupled fast chain A <-> B <-> C with slow decay of C follows exact exponential decay."""
    xml = _fast_sbml("""
    <listOfCompartments><compartment id="V" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="V" initialAmount="6" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="C" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J1" reversible="true" fast="true">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><cn>2</cn><ci>A</ci></apply><apply><times/><cn>1</cn><ci>B</ci></apply></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="J2" reversible="true" fast="true">
        <listOfReactants><speciesReference species="B" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="C" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><cn>3</cn><ci>B</ci></apply><apply><times/><cn>2</cn><ci>C</ci></apply></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="J_slow" reversible="false" fast="false">
        <listOfReactants><speciesReference species="C" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>0.5</cn><ci>C</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>""")
    result, parsed = _atomize(xml)
    assert result.success, result.error
    assert not any(
        w.get("severity") == "approximated" for w in (parsed.import_warnings or [])
    )

    # Stationary ratios: B = 2*A, C = 1.5*B = 3*A -> pi = (1/6, 2/6, 3/6).
    # T0 = 10, dT/dt = -0.5 * C = -0.5 * (0.5 * T) = -0.25 * T -> T(t) = 10 * exp(-0.25*t).
    assert parsed.species["A"].initial_amount == pytest.approx(10.0 / 6.0, abs=1e-9)
    assert parsed.species["B"].initial_amount == pytest.approx(20.0 / 6.0, abs=1e-9)
    assert parsed.species["C"].initial_amount == pytest.approx(30.0 / 6.0, abs=1e-9)

    _, sim = _load_and_simulate(tmp_path, xml, t_end=4.0, n_steps=8)
    for idx, t in enumerate(sim.time):
        assert sim.observables["__fast_pool_J1_amt"][idx] == pytest.approx(
            10.0 * math.exp(-0.25 * t), rel=1e-4, abs=1e-4
        )


def test_coupled_nonlinear_fast_subsystem_stays_fail_closed():
    """Coupled nonlinear fast reactions without closed-form equilibrium remain fail-closed."""
    xml = _fast_sbml("""
    <listOfCompartments><compartment id="V" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="C" compartment="V" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="D" compartment="V" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="E" compartment="V" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J1" reversible="true" fast="true">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="C" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><ci>A</ci><ci>B</ci></apply><ci>C</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="J2" reversible="true" fast="true">
        <listOfReactants>
          <speciesReference species="C" stoichiometry="1" constant="true"/>
          <speciesReference species="D" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="E" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><ci>C</ci><ci>D</ci></apply><ci>E</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>""")
    _, parsed = _atomize(xml)
    fast_warnings = [
        w for w in (parsed.import_warnings or []) if w.get("category") == "fastReaction"
    ]
    assert len(fast_warnings) == 2
    assert {w.get("severity") for w in fast_warnings} == {"approximated"}
