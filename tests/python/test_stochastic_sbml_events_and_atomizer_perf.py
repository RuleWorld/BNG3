"""Regression tests for stochastic SBML events, piecewise fast reactions,
and Atomizer function-inlining performance and determinism.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from _extdep import require_extension

require_extension()
import bionetgen
from bionetgen.atomizer.modern import Atomizer


def _atomize(xml: str, **kwargs):
    atomizer = Atomizer(atomize=False, quiet_mode=True, **kwargs)
    result = atomizer.atomize(xml)
    result.import_warnings = list(atomizer.model.import_warnings)
    return result


def _load_bngl(tmp_path: Path, name: str, bngl: str):
    path = tmp_path / name
    path.write_text(bngl, encoding="utf-8")
    return bionetgen.load(str(path))


# ---------------------------------------------------------------------------
# 1. Stochastic SBML events (Atomizer lowering + native SSA execution)
# ---------------------------------------------------------------------------


def test_stochastic_state_triggered_reset_event_lowers_and_executes(tmp_path):
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="stoch_reset">
    <listOfCompartments><compartment id="Cell" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="P" compartment="Cell" initialAmount="40" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="P2" compartment="Cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="make" reversible="false">
        <listOfReactants><speciesReference species="P" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="P2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci><ci>P</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="reset" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci>P2</ci><cn>10</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="P"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>40</cn></math></eventAssignment>
          <eventAssignment variable="P2"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result = _atomize(
        xml,
        actions='simulate({method=>"ssa", t_end=>10, n_steps=>50})',
        t_end=10,
        n_steps=50,
    )
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert "state-triggered SBML events require stochastic jump scheduling" not in result.bngl
    assert not any(w.get("severity") == "dropped" for w in result.import_warnings)

    sim = _load_bngl(tmp_path, "stoch_reset.bngl", result.bngl).simulate(
        method="ssa", t_end=10, n_steps=50, seed=11
    )
    # Every time P2 reaches 10 on a jump, the reset event fires immediately and
    # restores P2 to 0, so P2 never exceeds 9 at any observed point.
    assert np.all(np.asarray(sim.observables["P2_amt"]) < 10.0)


def test_stochastic_delayed_event_snapshot_vs_execution_time_values(tmp_path):
    def build_xml(use_trigger_time: str) -> str:
        return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="stoch_delay">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="20" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>1</cn><ci>A</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="capture" useValuesFromTriggerTime="{use_trigger_time}">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><leq/><ci>A</ci><cn>15</cn></apply>
          </math>
        </trigger>
        <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
        <listOfEventAssignments>
          <eventAssignment variable="B">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""

    res_trig = _atomize(
        build_xml("true"),
        actions='simulate({method=>"ssa", t_end=>6, n_steps=>60})',
        t_end=6,
        n_steps=60,
    )
    res_exec = _atomize(
        build_xml("false"),
        actions='simulate({method=>"ssa", t_end=>6, n_steps=>60})',
        t_end=6,
        n_steps=60,
    )
    assert res_trig.success and "begin bng3_events version 1" in res_trig.bngl
    assert res_exec.success and "begin bng3_events version 1" in res_exec.bngl

    sim_trig = _load_bngl(tmp_path, "trig.bngl", res_trig.bngl).simulate(
        method="ssa", t_end=6, n_steps=60, seed=7
    )
    sim_exec = _load_bngl(tmp_path, "exec.bngl", res_exec.bngl).simulate(
        method="ssa", t_end=6, n_steps=60, seed=7
    )
    # Trigger-time snapshot captures A == 15 exactly when A drops to 15.
    assert sim_trig.observables["B_amt"][-1] == pytest.approx(15.0)
    # Execution-time evaluation captures A two time units later (strictly < 15).
    assert sim_exec.observables["B_amt"][-1] < 10.0


def test_stochastic_equal_priority_seeded_random_tie_breaking(tmp_path):
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="stoch_tie">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="C" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="Winner" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="step" reversible="false">
        <listOfReactants><speciesReference species="X" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>1</cn><ci>X</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E1" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.5</cn></apply>
          </math>
        </trigger>
        <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math></priority>
        <listOfEventAssignments>
          <eventAssignment variable="Winner"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="E2" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.5</cn></apply>
          </math>
        </trigger>
        <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math></priority>
        <listOfEventAssignments>
          <eventAssignment variable="Winner"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result = _atomize(
        xml,
        actions='simulate({method=>"ssa", t_end=>1, n_steps=>4})',
        t_end=1,
        n_steps=4,
    )
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert not any(w.get("severity") == "dropped" for w in result.import_warnings)

    model = _load_bngl(tmp_path, "stoch_tie.bngl", result.bngl)
    # Fixed seed is strictly reproducible.
    run_a = model.simulate(method="ssa", t_end=1, n_steps=4, seed=123)
    run_b = model.simulate(method="ssa", t_end=1, n_steps=4, seed=123)
    assert run_a.observables["Winner_amt"][-1] == run_b.observables["Winner_amt"][-1]

    # Across distinct seeds, both equal-priority execution orders occur.
    outcomes = [
        model.simulate(method="ssa", t_end=1, n_steps=4, seed=s).observables[
            "Winner_amt"
        ][-1]
        for s in range(1, 41)
    ]
    assert set(outcomes) == {1.0, 2.0}
    assert 10 <= outcomes.count(1.0) <= 30


def test_periodic_rate_rule_clock_with_truncated_distrib_draws(tmp_path):
    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      xmlns:distrib="http://www.sbml.org/sbml/level3/version1/distrib/version1"
      level="3" version="2" distrib:required="true">
  <model id="periodic_distrib">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="t" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="t">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
      </rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci>t</ci><cn>0.5</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="X">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <csymbol definitionURL="http://www.sbml.org/sbml/symbols/distrib/normal">normal</csymbol>
                <cn>0</cn><cn>1.5</cn>
                <apply><minus/><infinity/></apply>
                <cn>0.5</cn>
              </apply>
            </math>
          </eventAssignment>
          <eventAssignment variable="t">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>-0.5</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    result = _atomize(
        xml,
        actions='simulate({method=>"ssa", t_end=>30, n_steps=>30})',
        t_end=30,
        n_steps=30,
    )
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert not any(w.get("severity") == "dropped" for w in result.import_warnings)

    model = _load_bngl(tmp_path, "periodic_distrib.bngl", result.bngl)
    sim1 = model.simulate(method="ssa", t_end=30, n_steps=30, seed=42)
    sim2 = model.simulate(method="ssa", t_end=30, n_steps=30, seed=42)
    samples = np.asarray(sim1.observables["X_amt"][1:], dtype=float)
    np.testing.assert_array_equal(sim1.observables["X_amt"], sim2.observables["X_amt"])
    assert np.all(samples < 0.5)
    assert samples.std() > 0.2


def test_competing_nonpersistent_equal_priority_pairs_with_discrete_sum_trigger(tmp_path):
    n_pairs = 24
    params = ['<parameter id="trig" value="1" constant="true"/>']
    params.extend(f'<parameter id="A{i}" value="0" constant="false"/>' for i in range(n_pairs))
    params.extend(f'<parameter id="B{i}" value="0" constant="false"/>' for i in range(n_pairs))
    params.append('<parameter id="Asum" constant="false"/>')
    params.append('<parameter id="Bsum" constant="false"/>')
    params.append('<parameter id="flagged" value="0" constant="false"/>')
    asum_terms = "".join(f"<ci>A{i}</ci>" for i in range(n_pairs))
    bsum_terms = "".join(f"<ci>B{i}</ci>" for i in range(n_pairs))
    evts = []
    for i in range(n_pairs):
        evts.append(f"""
      <event id="E{i}" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="false">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><gt/><ci>trig</ci><cn>0</cn></apply>
              <apply><lt/><ci>A{i}</ci><cn>1</cn></apply>
            </apply>
          </math>
        </trigger>
        <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math></priority>
        <listOfEventAssignments>
          <eventAssignment variable="B{i}"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
      <event id="Eb{i}" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="false">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><and/>
              <apply><gt/><ci>trig</ci><cn>0</cn></apply>
              <apply><lt/><ci>B{i}</ci><cn>1</cn></apply>
            </apply>
          </math>
        </trigger>
        <priority><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math></priority>
        <listOfEventAssignments>
          <eventAssignment variable="A{i}"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>""")
    evts.append("""
      <event id="check_balance" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/>
              <apply><abs/><apply><minus/><ci>Asum</ci><ci>Bsum</ci></apply></apply>
              <cn>100</cn>
            </apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="flagged"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>""")
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="competing_pairs">
    <listOfParameters>{''.join(params)}</listOfParameters>
    <listOfRules>
      <assignmentRule variable="Asum"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/>{asum_terms}</apply></math></assignmentRule>
      <assignmentRule variable="Bsum"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/>{bsum_terms}</apply></math></assignmentRule>
    </listOfRules>
    <listOfEvents>{''.join(evts)}</listOfEvents>
  </model>
</sbml>"""
    result = _atomize(xml, t_end=2, n_steps=4)
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert not any(w.get("severity") == "dropped" for w in result.import_warnings)

    model = _load_bngl(tmp_path, "competing_pairs.bngl", result.bngl)
    s1 = model.simulate(method="ode", t_end=2, n_steps=4, seed=1)
    s1_repeat = model.simulate(method="ode", t_end=2, n_steps=4, seed=1)
    s2 = model.simulate(method="ode", t_end=2, n_steps=4, seed=2)
    assert s1.observables["flagged_amt"][-1] == pytest.approx(0.0)
    for i in range(n_pairs):
        a1 = s1.observables[f"A{i}_amt"][-1]
        b1 = s1.observables[f"B{i}_amt"][-1]
        # Mutual exclusion via persistent="false" cancellation.
        assert a1 + b1 == pytest.approx(2.0)
        assert a1 == s1_repeat.observables[f"A{i}_amt"][-1]
    assert any(
        s1.observables[f"A{i}_amt"][-1] != s2.observables[f"A{i}_amt"][-1]
        for i in range(n_pairs)
    )


# ---------------------------------------------------------------------------
# 2. Piecewise sign-switching fast reactions (SBML L3V1 Sec. 4.11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_xml,k_attr,switch_index",
    [
        (
            '<assignmentRule variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML">'
            '<apply><minus/><cn>5.5</cn><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply>'
            "</math></assignmentRule>",
            'constant="false"',
            6,
        ),
        (
            '<rateRule variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<cn>-1</cn></math></rateRule>",
            'value="4.5" constant="false"',
            5,
        ),
    ],
)
def test_piecewise_switching_fast_reaction_reduces_exactly(
    tmp_path, rule_xml, k_attr, switch_index
):
    xml = f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="piecewise_fast">
    <listOfCompartments><compartment id="C" spatialDimensions="3" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialConcentration="3" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C" initialConcentration="3" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" {k_attr}/></listOfParameters>
    <listOfRules>{rule_xml}</listOfRules>
    <listOfReactions>
      <reaction id="J0" reversible="true" fast="true">
        <listOfReactants><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <piecewise>
              <piece><apply><times/><ci>S1</ci><ci>k</ci></apply><apply><gt/><ci>k</ci><cn>0</cn></apply></piece>
              <otherwise><apply><times/><ci>S2</ci><ci>k</ci></apply></otherwise>
            </piecewise>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    result = _atomize(xml, t_end=10, n_steps=10)
    assert result.success, result.error
    fast_warnings = [
        w for w in result.import_warnings if w.get("category") == "fastReaction"
    ]
    assert fast_warnings and all(w.get("severity") == "info" for w in fast_warnings)

    sim = _load_bngl(tmp_path, "piecewise_fast.bngl", result.bngl).simulate(
        method="ode", t_end=10, n_steps=10
    )
    s1 = np.asarray(sim.functions["S1"], dtype=float)
    s2 = np.asarray(sim.functions["S2"], dtype=float)
    expected_s1 = np.array([0.0] * switch_index + [6.0] * (11 - switch_index))
    expected_s2 = np.array([6.0] * switch_index + [0.0] * (11 - switch_index))
    np.testing.assert_allclose(s1, expected_s1, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(s2, expected_s2, rtol=1e-12, atol=1e-12)


# ---------------------------------------------------------------------------
# 3. Large-model Atomizer function-inlining performance & determinism
# ---------------------------------------------------------------------------


def _synthetic_function_heavy_sbml(n_species: int, n_functions: int, n_reactions: int) -> str:
    base_count = max(1, n_functions // 4)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">',
        '  <model id="large_fn_bench">',
        "    <listOfFunctionDefinitions>",
    ]
    for i in range(n_functions):
        if i < base_count:
            parts.append(
                f'      <functionDefinition id="fn_{i}"><math xmlns="http://www.w3.org/1998/Math/MathML">'
                "<lambda><bvar><ci>x</ci></bvar><bvar><ci>k</ci></bvar><bvar><ci>Km</ci></bvar>"
                "<apply><divide/><apply><times/><ci>k</ci><ci>x</ci></apply>"
                "<apply><plus/><ci>Km</ci><ci>x</ci></apply></apply></lambda></math></functionDefinition>"
            )
        else:
            base = i % base_count
            parts.append(
                f'      <functionDefinition id="fn_{i}"><math xmlns="http://www.w3.org/1998/Math/MathML">'
                "<lambda><bvar><ci>s</ci></bvar><bvar><ci>p</ci></bvar>"
                "<bvar><ci>v</ci></bvar><bvar><ci>km1</ci></bvar><bvar><ci>km2</ci></bvar>"
                f"<apply><minus/><apply><ci>fn_{base}</ci><ci>s</ci><ci>v</ci><ci>km1</ci></apply>"
                f"<apply><ci>fn_{base}</ci><ci>p</ci><ci>v</ci><ci>km2</ci></apply></apply>"
                "</lambda></math></functionDefinition>"
            )
    parts.append("    </listOfFunctionDefinitions>")
    parts.append('    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>')
    parts.append("    <listOfSpecies>")
    for i in range(n_species):
        parts.append(
            f'      <species id="S_{i}" compartment="c" initialAmount="{1.0 + i * 0.1:.1f}" '
            'hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>'
        )
    parts.append("    </listOfSpecies><listOfParameters>")
    for i in range(n_reactions):
        parts.append(
            f'      <parameter id="v_{i}" value="0.5" constant="true"/>'
            f'<parameter id="km1_{i}" value="1.0" constant="true"/>'
            f'<parameter id="km2_{i}" value="2.0" constant="true"/>'
        )
    parts.append("    </listOfParameters><listOfReactions>")
    for i in range(n_reactions):
        s = f"S_{i % n_species}"
        p = f"S_{(i + 1) % n_species}"
        fn = f"fn_{base_count + (i % max(1, n_functions - base_count))}"
        parts.append(
            f'      <reaction id="R_{i}" reversible="true">'
            f'<listOfReactants><speciesReference species="{s}" stoichiometry="1" constant="true"/></listOfReactants>'
            f'<listOfProducts><speciesReference species="{p}" stoichiometry="1" constant="true"/></listOfProducts>'
            f'<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">'
            f"<apply><ci>{fn}</ci><ci>{s}</ci><ci>{p}</ci><ci>v_{i}</ci><ci>km1_{i}</ci><ci>km2_{i}</ci></apply>"
            "</math></kineticLaw></reaction>"
        )
    parts.append("    </listOfReactions></model></sbml>")
    return "\n".join(parts)


def test_large_function_heavy_sbml_atomizes_fast_and_deterministically(tmp_path):
    xml = _synthetic_function_heavy_sbml(n_species=160, n_functions=160, n_reactions=240)
    t0 = time.perf_counter()
    result = _atomize(xml)
    elapsed = time.perf_counter() - t0
    assert result.success, result.error
    # Previously quadratic (>20 s for this size); must stay well under 5 s.
    assert elapsed < 5.0, f"Atomizer took {elapsed:.2f}s on 240-reaction nested-function model"
    assert "fn_0(" not in result.bngl and "fn_40(" not in result.bngl

    # Verify PYTHONHASHSEED-invariance across distinct hash seeds.
    xml_path = tmp_path / "large.xml"
    xml_path.write_text(xml, encoding="utf-8")
    outputs = []
    for hash_seed in ("0", "1", "42"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = hash_seed
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from bionetgen.atomizer.modern import Atomizer; "
                "print(Atomizer(atomize=False, quiet_mode=True).atomize(open(sys.argv[1]).read()).bngl)",
                str(xml_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1] == outputs[2]


def test_nested_function_inlining_matches_independent_roadrunner(tmp_path):
    roadrunner = pytest.importorskip("roadrunner")
    xml = _synthetic_function_heavy_sbml(n_species=6, n_functions=8, n_reactions=6)
    result = _atomize(xml, t_end=2.0, n_steps=20)
    assert result.success, result.error

    sim = _load_bngl(tmp_path, "nested_fn.bngl", result.bngl).simulate(
        method="ode", t_end=2.0, n_steps=20
    )
    rr = roadrunner.RoadRunner(xml)
    rr.integrator.relative_tolerance = 1e-10
    rr.integrator.absolute_tolerance = 1e-12
    expected = rr.simulate(0.0, 2.0, 21, selections=["time", *(f"S_{i}" for i in range(6))])
    for i in range(6):
        np.testing.assert_allclose(
            sim.observables[f"S_{i}_amt"], expected[:, i + 1], rtol=1e-6, atol=1e-8
        )
