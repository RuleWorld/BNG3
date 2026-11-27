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
    assert (
        "state-triggered SBML events require stochastic jump scheduling"
        not in result.bngl
    )
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
    # Continuous constant-slope rateRule clock (dt/dt = 1) with truncated
    # distrib draws now lowers and executes faithfully under BOTH hybrid SSA
    # (exact analytical clock ticks + seeded distrib draws + CPU batch SSA)
    # and ODE (CVODE).
    ssa_result = _atomize(
        xml,
        actions='simulate({method=>"ssa", t_end=>30, n_steps=>30})',
        t_end=30,
        n_steps=30,
    )
    assert ssa_result.success, ssa_result.error
    assert "begin bng3_events version 1" in ssa_result.bngl
    assert not any(w.get("severity") == "dropped" for w in ssa_result.import_warnings)

    ssa_model = _load_bngl(tmp_path, "periodic_distrib_ssa.bngl", ssa_result.bngl)
    ssa1 = ssa_model.simulate(method="ssa", t_end=30, n_steps=30, seed=42)
    ssa2 = ssa_model.simulate(method="ssa", t_end=30, n_steps=30, seed=42)
    ssa_samples = np.asarray(ssa1.observables["X_amt"][1:], dtype=float)
    np.testing.assert_array_equal(ssa1.observables["X_amt"], ssa2.observables["X_amt"])
    assert np.all(ssa_samples < 0.5)
    assert ssa_samples.std() > 0.2
    # Clock t_id resets to -0.5 at every half-integer tick, so at integer
    # sample times t = 0, 1, ..., 30 it must be identically 0.0.
    np.testing.assert_allclose(ssa1.observables["t_id_amt"], 0.0, atol=1e-12)

    # Analytical moments of Normal(mu=0, sigma=1.5) upper-truncated at b=0.5:
    # beta = (b - mu)/sigma = 1/3, phi(beta)/Phi(beta) = Mills ratio.
    import math

    sigma = 1.5
    beta = 0.5 / sigma
    phi_beta = math.exp(-0.5 * beta * beta) / math.sqrt(2.0 * math.pi)
    Phi_beta = 0.5 * (1.0 + math.erf(beta / math.sqrt(2.0)))
    lam = phi_beta / Phi_beta
    expected_mean = -sigma * lam
    expected_sd = sigma * math.sqrt(1.0 - beta * lam - lam * lam)

    from bionetgen import _bionetgen_cpp as cpp

    cpp_model = cpp.parse_string(ssa_result.bngl)
    cpp_net = cpp.generate_network(cpp_model)
    batch = cpp.simulate_batch_ssa_cpu(
        cpp_model,
        cpp_net,
        batch_size=2000,
        t_end=10.0,
        n_steps=10,
        t_start=0.0,
        base_seed=1000000,
        threads=4,
        max_sim_steps=0,
    )
    batch_means = np.asarray(batch["observable_means"]["X_amt"], dtype=float)
    batch_stds = np.asarray(batch["observable_stds"]["X_amt"], dtype=float)
    assert batch_means[0] == pytest.approx(0.0, abs=1e-12)
    assert batch_stds[0] == pytest.approx(0.0, abs=1e-12)
    np.testing.assert_allclose(batch_means[1:], expected_mean, atol=0.12)
    np.testing.assert_allclose(batch_stds[1:], expected_sd, atol=0.10)

    result = _atomize(
        xml,
        actions='simulate({method=>"ode", t_end=>30, n_steps=>30})',
        t_end=30,
        n_steps=30,
    )
    assert result.success, result.error
    assert "begin bng3_events version 1" in result.bngl
    assert not any(w.get("severity") == "dropped" for w in result.import_warnings)

    model = _load_bngl(tmp_path, "periodic_distrib.bngl", result.bngl)
    sim1 = model.simulate(method="ode", t_end=30, n_steps=30, seed=42)
    sim2 = model.simulate(method="ode", t_end=30, n_steps=30, seed=42)
    samples = np.asarray(sim1.observables["X_amt"][1:], dtype=float)
    np.testing.assert_array_equal(sim1.observables["X_amt"], sim2.observables["X_amt"])
    assert np.all(samples < 0.5)
    assert samples.std() > 0.2


def test_hybrid_clock_coupled_with_discrete_ssa_and_inf_param_truncation(tmp_path):
    """Verify (1) INF/-INF parameter truncation bounds (SSTS 00096..00099),
    (2) state-triggered reset events in CPU batch SSA (SSTS 00033), and
    (3) fail-closed refusal for nonlinear rateRules / coupled propensities."""
    from bionetgen import _bionetgen_cpp as cpp

    # 1. INF parameter truncation bound (stochastic/00096 pattern)
    inf_param_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      xmlns:distrib="http://www.sbml.org/sbml/level3/version1/distrib/version1"
      level="3" version="2" distrib:required="true">
  <model id="inf_param_trunc">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="t" value="0" constant="false"/>
      <parameter id="mean" value="0" constant="true"/>
      <parameter id="stddev" value="1.5" constant="true"/>
      <parameter id="truncationLowerBound" value="-0.5" constant="true"/>
      <parameter id="truncationUpperBound" value="INF" constant="true"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="t"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
    </listOfRules>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><ci>t</ci><cn>0.5</cn></apply></math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="X">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply>
                <csymbol definitionURL="http://www.sbml.org/sbml/symbols/distrib/normal">normal</csymbol>
                <ci>mean</ci><ci>stddev</ci><ci>truncationLowerBound</ci><ci>truncationUpperBound</ci>
              </apply>
            </math>
          </eventAssignment>
          <eventAssignment variable="t"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>-0.5</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    res_inf = _atomize(
        inf_param_xml,
        actions='simulate({method=>"ssa", t_end=>5, n_steps=>5})',
        t_end=5,
        n_steps=5,
    )
    assert res_inf.success, res_inf.error
    assert "begin bng3_events version 1" in res_inf.bngl
    assert not any(w.get("severity") == "dropped" for w in res_inf.import_warnings)
    m_inf = cpp.parse_string(res_inf.bngl)
    net_inf = cpp.generate_network(m_inf)
    batch_inf = cpp.simulate_batch_ssa_cpu(
        m_inf, net_inf, batch_size=1000, t_end=5.0, n_steps=5, base_seed=42, threads=2
    )
    # Symmetric mirror of upper-truncated at 0.5 -> positive mean > 0.7
    assert np.all(np.asarray(batch_inf["observable_means"]["X_amt"][1:]) > 0.7)

    # 2. State-triggered reset in CPU batch SSA (stochastic/00033 pattern)
    dimer_reset_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="dimer_reset">
    <listOfCompartments><compartment id="Cell" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="P" compartment="Cell" initialAmount="100" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="P2" compartment="Cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.001" constant="true"/>
      <parameter id="k2" value="0.01" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="Dimerisation" reversible="false">
        <listOfReactants><speciesReference species="P" stoichiometry="2" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="P2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><divide/><apply><times/><ci>k1</ci><ci>P</ci><apply><minus/><ci>P</ci><cn>1</cn></apply></apply><cn>2</cn></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="Disassociation" reversible="false">
        <listOfReactants><speciesReference species="P2" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="P" stoichiometry="2" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k2</ci><ci>P2</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="reset" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><gt/><ci>P2</ci><cn>30</cn></apply></math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="P"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>100</cn></math></eventAssignment>
          <eventAssignment variable="P2"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    res_33 = _atomize(
        dimer_reset_xml,
        actions='simulate({method=>"ssa", t_end=>10, n_steps=>10})',
        t_end=10,
        n_steps=10,
    )
    assert res_33.success and "begin bng3_events version 1" in res_33.bngl
    m_33 = cpp.parse_string(res_33.bngl)
    net_33 = cpp.generate_network(m_33)
    b1 = cpp.simulate_batch_ssa_cpu(
        m_33, net_33, batch_size=64, t_end=10.0, n_steps=10, base_seed=100, threads=1
    )
    b4 = cpp.simulate_batch_ssa_cpu(
        m_33, net_33, batch_size=64, t_end=10.0, n_steps=10, base_seed=100, threads=4
    )
    np.testing.assert_allclose(
        b1["observable_means"]["P2_amt"], b4["observable_means"]["P2_amt"], atol=1e-5
    )
    np.testing.assert_allclose(
        b1["observable_stds"]["P2_amt"], b4["observable_stds"]["P2_amt"], atol=1e-5
    )
    assert np.all(np.asarray(b4["observable_means"]["P2_amt"]) <= 30.0)
    # GPU/JAX flattening must still fail closed on native events.
    with pytest.raises(RuntimeError, match="native events"):
        cpp.jax_ssa_flatten(m_33, net_33)

    # 3. Fail-closed refusal when nonlinear rateRule is coupled to SSA reactions
    nonlinear_ssa_xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="nonlinear_coupled_ssa">
    <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="C" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="u" value="2" constant="false"/></listOfParameters>
    <listOfRules>
      <rateRule variable="u"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><ci>u</ci></apply></math></rateRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="r" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><leq/><ci>u</ci><cn>1</cn></apply></math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="u"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    res_nl = _atomize(
        nonlinear_ssa_xml,
        actions='simulate({method=>"ssa", t_end=>5, n_steps=>5})',
        t_end=5,
        n_steps=5,
    )
    assert res_nl.success
    assert "begin bng3_events version 1" not in res_nl.bngl
    assert any(w.get("severity") == "dropped" for w in res_nl.import_warnings)

    # 4. Fail-closed refusal when discrete SSA reaction kinetic law reads a
    # continuously drifting rateRule variable.
    coupled_rate_xml = nonlinear_ssa_xml.replace(
        "<apply><minus/><ci>u</ci></apply>", "<cn>1</cn>"
    ).replace(
        '<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></kineticLaw>',
        '<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>u</ci><ci>A</ci></apply></math></kineticLaw>',
    )
    res_cp = _atomize(
        coupled_rate_xml,
        actions='simulate({method=>"ssa", t_end=>5, n_steps=>5})',
        t_end=5,
        n_steps=5,
    )
    assert res_cp.success
    assert "begin bng3_events version 1" not in res_cp.bngl
    assert any(w.get("severity") == "dropped" for w in res_cp.import_warnings)


def test_competing_nonpersistent_equal_priority_pairs_with_discrete_sum_trigger(
    tmp_path,
):
    n_pairs = 24
    params = ['<parameter id="trig" value="1" constant="true"/>']
    params.extend(
        f'<parameter id="A{i}" value="0" constant="false"/>' for i in range(n_pairs)
    )
    params.extend(
        f'<parameter id="B{i}" value="0" constant="false"/>' for i in range(n_pairs)
    )
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


def _synthetic_function_heavy_sbml(
    n_species: int, n_functions: int, n_reactions: int
) -> str:
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
    parts.append(
        '    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>'
    )
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
    # Hold species count fixed while scaling function definitions and reactions
    # 4x so the ratio isolates function-inlining scaling (previously O(F*R) ~16x)
    # rather than pairwise species naming heuristics.
    small_xml = _synthetic_function_heavy_sbml(
        n_species=30, n_functions=40, n_reactions=60
    )
    scaled_xml = _synthetic_function_heavy_sbml(
        n_species=30, n_functions=160, n_reactions=240
    )
    t_small = time.perf_counter()
    small_result = _atomize(small_xml)
    small_elapsed = time.perf_counter() - t_small
    assert small_result.success, small_result.error

    t_scaled = time.perf_counter()
    scaled_result = _atomize(scaled_xml)
    scaled_elapsed = time.perf_counter() - t_scaled
    assert scaled_result.success, scaled_result.error
    scaling_ratio = scaled_elapsed / max(small_elapsed, 0.05)
    assert (
        scaling_ratio < 10.0
    ), f"4x function/reaction scale-up took {scaling_ratio:.2f}x ({small_elapsed:.2f}s -> {scaled_elapsed:.2f}s)"

    large_xml = _synthetic_function_heavy_sbml(
        n_species=160, n_functions=160, n_reactions=240
    )
    t_large = time.perf_counter()
    result = _atomize(large_xml)
    elapsed = time.perf_counter() - t_large
    assert result.success, result.error
    # Previously >20s uninstrumented (>200s under pytest-cov); stay well under 25s
    # even with coverage bytecode tracing on slower Windows CI runners.
    assert (
        elapsed < 25.0
    ), f"Atomizer took {elapsed:.2f}s on 240-reaction nested-function model"
    assert "fn_0(" not in result.bngl and "fn_40(" not in result.bngl

    # Verify PYTHONHASHSEED-invariance across distinct hash seeds.
    xml_path = tmp_path / "large.xml"
    xml_path.write_text(large_xml, encoding="utf-8")
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
    expected = rr.simulate(
        0.0, 2.0, 21, selections=["time", *(f"S_{i}" for i in range(6))]
    )
    for i in range(6):
        np.testing.assert_allclose(
            sim.observables[f"S_{i}_amt"], expected[:, i + 1], rtol=1e-6, atol=1e-8
        )


def test_rewrite_mass_action_symbols_preserves_semantics_and_scales_linearly():
    from bionetgen.atomizer.modern.writer import _rewrite_mass_action_symbols

    species_map = {f"S{i}": "C" if i % 2 == 0 else "" for i in range(250)}
    assign_vars = [f"A{i}" for i in range(250)]
    expr = "k * _c_S0() + S1_amt * _c_s2() + A10() + unknown_amt + other()"
    rewritten = _rewrite_mass_action_symbols(expr, species_map, None, assign_vars)
    assert (
        rewritten == "k * (S0 / __compartment_C__) + S1 * (S2 / __compartment_C__) "
        "+ A10 + unknown_amt + other()"
    )
    t0 = time.perf_counter()
    for _ in range(250):
        _rewrite_mass_action_symbols(
            "k * S100_amt + A50()", species_map, None, assign_vars
        )
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"_rewrite_mass_action_symbols regressed: {elapsed:.2f}s"
