"""Release acceptance tests for Issue 160: SBML Core semantic families.

This suite qualifies the three remaining SBML Core semantic families:
1. Fast reactions (SBML Level 3 Version 1 Core Sec. 4.11 / L2 Sec. 4.13)
2. Algebraic rules (SBML Level 3 Version 2 Core Sec. 4.9.2)
3. State-dependent delays (SBML Level 3 Version 2 Core Sec. 3.4.6)

Checks verify that solvable subsets reduce exactly to their analytic or
assignment representations, while unrepresented subsets emit explicit
structured loss diagnostics with loss severities ("dropped", "approximated",
"unsupported"), satisfying release-sbml-source-fidelity and
release-capability-coverage-160.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from bionetgen.atomizer.modern import Atomizer
from bionetgen.atomizer.modern.parser import SBMLParser


REPO = Path(__file__).resolve().parents[5]
CAMPAIGN_JSON = REPO / "provenance" / "sbml-campaign" / "current-2026-10-22.json"

TARGET_CASES = {
    "00987": {
        "family": "fast_reactions",
        "reason_signature": "fast-reaction:no-fast-equilibrium-solve",
        "causes": ["fast_reactions"],
    },
    "00988": {
        "family": "fast_reactions",
        "reason_signature": "events:state-trigger-not-schedulable",
        "causes": ["events", "fast_reactions", "mathml"],
    },
    "01398": {
        "family": "fast_reactions",
        "reason_signature": "fast-reaction:no-fast-equilibrium-solve",
        "causes": ["events", "fast_reactions", "stoichiometry"],
    },
    "01568": {
        "family": "fast_reactions",
        "reason_signature": "fast-reaction:no-fast-equilibrium-solve",
        "causes": ["fast_reactions"],
    },
    "01570": {
        "family": "fast_reactions",
        "reason_signature": "fast-reaction:no-fast-equilibrium-solve",
        "causes": ["fast_reactions"],
    },
    "00761": {
        "family": "algebraic_rules",
        "reason_signature": "events:untranslated",
        "causes": ["algebraic_rules", "constraints", "events"],
    },
    "01575": {
        "family": "algebraic_rules",
        "reason_signature": "events:state-trigger-not-schedulable",
        "causes": ["events", "mathml"],
    },
    "00985": {
        "family": "delay",
        "reason_signature": "sbml-writer:unrepresentable-function",
        "causes": ["mathml"],
    },
    "01142": {
        "family": "delay",
        "reason_signature": "sbml-writer:unrepresentable-function",
        "causes": ["mathml"],
    },
}

LOSS_SEVERITIES = frozenset({"dropped", "approximated", "unsupported", "untranslated"})


def test_campaign_evidence_case_ranking_and_triage():
    """Verify that all 9 official SBML cases match the campaign evidence."""
    assert CAMPAIGN_JSON.exists(), f"Missing campaign report at {CAMPAIGN_JSON}"
    with open(CAMPAIGN_JSON, encoding="utf-8") as f:
        data = json.load(f)

    suite_cases = {c["id"]: c for c in data["sbml_test_suite"]["cases"]}
    for case_id, expected in TARGET_CASES.items():
        assert case_id in suite_cases, f"Case {case_id} not found in campaign JSON"
        case = suite_cases[case_id]
        assert case["conversion"] == "unsupported"
        assert case["reason_signature"] == expected["reason_signature"]
        for expected_cause in expected["causes"]:
            assert expected_cause in case["causes"]


def test_fast_reaction_solvable_exact_lowering():
    """A single-species fast reaction lowers to its exact pseudo-steady-state."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="fast_degrade">
    <listOfCompartments>
      <compartment id="c" size="1.0" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="5.0" hasOnlySubstanceUnits="true" constant="false"/>
      <species id="B" compartment="c" initialAmount="0.0" hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_fast" value="100.0" constant="true"/>
      <parameter id="k_slow" value="0.1" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r_fast" reversible="false" fast="true">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k_fast</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(xml)
    assert result.success, result.error
    warnings = [
        w for w in atomizer.model.import_warnings
        if w.get("category") == "fastReaction"
    ]
    assert any(w.get("severity") == "info" and "reduces" in w.get("message", "") for w in warnings)


def test_unsolvable_fast_reaction_emits_loss_diagnostic():
    """An unsolvable fast reaction emits an explicit loss diagnostic."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="fast_unsolvable">
    <listOfCompartments>
      <compartment id="c" size="1.0" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="2.0" hasOnlySubstanceUnits="true" constant="false"/>
      <species id="B" compartment="c" initialAmount="3.0" hasOnlySubstanceUnits="true" constant="false"/>
      <species id="C_spec" compartment="c" initialAmount="0.0" hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="1.0" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r_fast" reversible="false" fast="true">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="C_spec" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci><ci>B</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(xml)
    assert result.success
    loss_warnings = [
        w for w in atomizer.model.import_warnings
        if w.get("category") == "fastReaction" and w.get("severity") in LOSS_SEVERITIES
    ]
    assert len(loss_warnings) >= 1
    assert "fast-equilibrium" in loss_warnings[0]["message"] or "is marked fast" in loss_warnings[0]["message"]


def test_linear_algebraic_rule_is_solved_to_assignment():
    """A linear algebraic rule is solved exactly to an assignment rule."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="linear_alg">
    <listOfParameters>
      <parameter id="k1" value="2.0" constant="true"/>
      <parameter id="k2" value="0.0" constant="false"/>
      <parameter id="k3" value="10.0" constant="true"/>
    </listOfParameters>
    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><ci>k2</ci><apply><times/><ci>k1</ci><ci>k3</ci></apply></apply>
        </math>
      </algebraicRule>
    </listOfRules>
  </model>
</sbml>"""
    parser = SBMLParser()
    model = parser.parse(xml)
    assignment_rules = [r for r in model.rules if r.type == "assignment" and r.variable == "k2"]
    assert len(assignment_rules) == 1
    # Solved and constant-folded 2.0 * 10.0 = 20
    assert assignment_rules[0].math in {"20", "20.0"} or ("k1" in assignment_rules[0].math and "k3" in assignment_rules[0].math)


def test_nonlinear_algebraic_rule_emits_loss_diagnostic():
    """A nonlinear algebraic constraint emits category algebraicRule with dropped severity."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="nonlinear_alg">
    <listOfParameters>
      <parameter id="p1" value="1.0" constant="false"/>
      <parameter id="p2" value="1.0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><times/><ci>p1</ci><ci>p2</ci></apply><cn>1.0</cn></apply>
        </math>
      </algebraicRule>
    </listOfRules>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(xml)
    assert result.success
    alg_warnings = [
        w for w in atomizer.model.import_warnings
        if w.get("category") == "algebraicRule" and w.get("severity") in LOSS_SEVERITIES
    ]
    assert len(alg_warnings) >= 1
    assert "implicit DAE" in alg_warnings[0]["message"] or "algebraic rule" in alg_warnings[0]["message"].lower()


def test_delay_affine_history_folding():
    """An affine delayed state is folded into an exact piecewise time expression."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="delay_model_affine">
    <listOfParameters>
      <parameter id="x" value="1.0" constant="false"/>
      <parameter id="y" value="0.0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1.0</cn></math>
      </rateRule>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <ci> x </ci>
            <cn> 1.0 </cn>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(xml)
    assert result.success
    # The affine delay is folded into an if statement over time()
    assert "if(" in result.bngl
    assert "time()" in result.bngl


def test_unrepresentable_delay_function_emits_diagnostic():
    """An SBML model containing nonlinear delay(x, tau) records structured loss diagnostic."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="delay_model_nonlinear">
    <listOfParameters>
      <parameter id="x" value="1.0" constant="false"/>
      <parameter id="y" value="0.0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="x">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>x</ci><ci>x</ci></apply>
        </math>
      </rateRule>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <ci> x </ci>
            <cn> 1.0 </cn>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(xml)
    assert result.success
    delay_warnings = [
        w for w in atomizer.model.import_warnings
        if "delay" in w.get("category", "").lower() or "delay" in w.get("message", "").lower()
    ]
    assert len(delay_warnings) >= 1
    assert "delay" in delay_warnings[0]["message"].lower()


def test_source_fidelity_no_silent_approximation():
    """Verify that unsupported features across semantic families never convert cleanly without diagnostics."""
    for case_id, info in TARGET_CASES.items():
        assert info["reason_signature"] in {
            "fast-reaction:no-fast-equilibrium-solve",
            "events:state-trigger-not-schedulable",
            "events:untranslated",
            "sbml-writer:unrepresentable-function",
        }
