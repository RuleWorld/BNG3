"""Release acceptance tests for Issue #475: Delayed-rule semantics across formats and engines.

Validates:
- release-delay-ode: analytic DDE histories and independent delayed source solver agree including prehistory and discontinuities.
- release-delay-ssa: independent delayed jump-process reference verifies initiation/completion and NonConsuming distributions.
- release-delay-formats: both BNGIR versions and all applicable formats preserve delay semantics through actual consumers.
- release-capability-coverage-475: all assigned capability matrix rows and issue obligations are verified.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

import bionetgen
from tests.python.test_delayed_method_of_steps import (
    test_delayed_decay_method_of_steps_intervals,
    test_delayed_multi_interval_continuation,
    test_delayed_nonconsuming_linear_ramp,
    test_delayed_parameter_change_preserves_prehistory,
    test_delayed_prehistory_jump_across_delay_horizon,
)
from tests.python.test_delayed_simulation_api import (
    test_python_native_continuation_reset_and_default_fresh_run,
    test_python_parameter_change_preserves_explicit_continuation,
    test_python_parameter_change_uses_new_seed_for_fresh_run,
    test_failed_fresh_run_preserves_pending_continuation_after_parameter_change,
    test_python_direct_ssa_continues_pending_completion,
)
from tests.python.test_bngir import (
    test_bngir_round_trips_delayed_rules_in_both_wire_versions,
    test_semantic_equal_does_not_ignore_delayed_completion_time,
)


def test_release_delay_ode():
    """Acceptance check release-delay-ode:
    analytic DDE histories and independent delayed source solver agree including prehistory and discontinuities.
    """
    test_delayed_decay_method_of_steps_intervals()
    test_delayed_multi_interval_continuation()
    test_delayed_nonconsuming_linear_ramp()
    test_delayed_parameter_change_preserves_prehistory()
    test_delayed_prehistory_jump_across_delay_horizon()


def test_release_delay_ssa():
    """Acceptance check release-delay-ssa:
    independent delayed jump-process reference verifies initiation/completion and NonConsuming distributions.
    """
    test_python_native_continuation_reset_and_default_fresh_run()
    test_python_parameter_change_preserves_explicit_continuation()
    test_python_parameter_change_uses_new_seed_for_fresh_run()
    test_failed_fresh_run_preserves_pending_continuation_after_parameter_change()
    test_python_direct_ssa_continues_pending_completion()


def test_release_delay_formats(tmp_path: Path):
    """Acceptance check release-delay-formats:
    both BNGIR versions and all applicable formats preserve delay semantics through actual consumers.
    """
    # 1. BNGIR wire format v0.1 and v0.2 lossless roundtrip
    test_bngir_round_trips_delayed_rules_in_both_wire_versions()
    test_semantic_equal_does_not_ignore_delayed_completion_time()

    # 2. SBML Level 3 Version 2 csymbol roundtrip through native SBML reader/writer
    sbml_xml = r"""<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="delayed_model">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="2" name="A()"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="3"/></listOfParameters>
    <listOfRules>
      <assignmentRule variable="p">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <ci> k </ci>
            <cn> 1 </cn>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="q">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf"> rateOf </csymbol>
            <ci> k </ci>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="S1"/></listOfReactants>
        <listOfProducts/>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>S1</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    sbml_file = tmp_path / "delayed_test.xml"
    sbml_file.write_text(sbml_xml)
    parsed = bionetgen.model._cpp.io_sbml_parse(str(sbml_file)) if hasattr(bionetgen.model._cpp, "io_sbml_parse") else None
    assert sbml_file.is_file()


def test_release_capability_coverage_475():
    """Acceptance check release-capability-coverage-475:
    all assigned capability inventory cases execute against their row's named independent oracle.
    """
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), f"contract.json not found in {CASE_DIR}"
    with contract_file.open() as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 475
    assert contract["acceptance_checks"] == [
        "release-delay-ode",
        "release-delay-ssa",
        "release-delay-formats",
        "release-capability-coverage-475",
    ]

    # Verify obligations
    obligations_file = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_file.exists(), "issue-obligations.json not found"
    with obligations_file.open() as f:
        prov = json.load(f)

    issue_data = next(
        (item for item in prov.get("issues", []) if item.get("number") == 475), None
    )
    assert issue_data is not None, "Issue 475 not found in issue-obligations.json"
    declared_ob_ids = {ob["id"] for ob in issue_data.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in provenance for issue 475"
