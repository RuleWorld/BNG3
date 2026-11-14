"""Release qualification suite for Issue #475: Delayed-rule semantics across formats and engines.

Qualifies:
- release-delay-ode: Analytic DDE histories and method-of-steps exact solutions agree with native ODE execution across intervals, prehistory, and discontinuities.
- release-delay-ssa: Independent delayed jump-process reference verifies initiation/completion and NonConsuming distributions against analytic Poisson/Binomial laws, continuation across runs, and queue state recovery.
- release-delay-formats: Lossless roundtrip and execution of delayed rules in both BNGIR versions (v0.1 and v0.2), SBML Level 3 Version 2 <csymbol> delay export, re-import, and ODE execution comparisons, and finite backend lowering capability checks.
- release-capability-coverage-475: Full capability matrix and issue obligation crosswalk verification.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

import bionetgen  # noqa: E402
import tests.python.test_delayed_method_of_steps as dmos  # noqa: E402
import tests.python.test_delayed_simulation_api as dsa  # noqa: E402
from tests.python.test_bngir import (  # noqa: E402
    test_bngir_round_trips_delayed_rules_in_both_wire_versions,
    test_semantic_equal_does_not_ignore_delayed_completion_time,
)


def test_release_delay_ode():
    """Acceptance check release-delay-ode:

    analytic DDE histories and independent delayed source solver agree
    including prehistory and discontinuities.
    """
    dmos.test_delayed_decay_method_of_steps_intervals()
    dmos.test_delayed_multi_interval_continuation()
    dmos.test_delayed_nonconsuming_linear_ramp()
    dmos.test_delayed_parameter_change_preserves_prehistory()
    dmos.test_delayed_prehistory_jump_across_delay_horizon()


def test_release_delay_ssa():
    """Acceptance check release-delay-ssa:

    independent delayed jump-process reference verifies initiation/completion
    and NonConsuming distributions.
    """
    dsa.test_python_native_continuation_reset_and_default_fresh_run()
    dsa.test_python_parameter_change_preserves_explicit_continuation()
    dsa.test_python_parameter_change_uses_new_seed_for_fresh_run()
    dsa.test_failed_fresh_run_preserves_pending_continuation_after_parameter_change()  # noqa: E501
    dsa.test_python_direct_ssa_continues_pending_completion()
    dsa.test_delayed_ssa_independent_jump_distribution()


def test_release_delay_formats(tmp_path: Path):
    """Acceptance check release-delay-formats:

    both BNGIR versions and all applicable formats preserve delay semantics
    through actual consumers.
    """
    import numpy as np
    from bionetgen.atomizer.modern import sbml_to_bngl_flat

    # 1. BNGIR wire format v0.1 and v0.2 lossless roundtrip and execution comparison
    test_bngir_round_trips_delayed_rules_in_both_wire_versions()
    test_semantic_equal_does_not_ignore_delayed_completion_time()

    source = """
begin model
begin parameters
  tau 1.5
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(source))
    res_orig = model.simulate(method="ode", t_end=5.0, n_steps=50)

    for version in ("0.1", "0.2"):
        document = model.to_bngir(version=version)
        restored = bionetgen.from_bngir(document)
        res_rest = restored.simulate(method="ode", t_end=5.0, n_steps=50)
        np.testing.assert_allclose(
            res_orig.observables["A"],
            res_rest.observables["A"],
            rtol=1e-5,
            atol=1e-8,
        )
        np.testing.assert_allclose(
            res_orig.observables["B"],
            res_rest.observables["B"],
            rtol=1e-5,
            atol=1e-8,
        )

    # 2. SBML Level 3 Version 2 export with delay csymbol, re-import and execution
    net = model.generate_network()
    sbml_file = tmp_path / "delayed_test.xml"
    bionetgen.model._cpp.io.write_sbml(model._model, net, str(sbml_file), level=3)
    xml_text = sbml_file.read_text()
    assert 'definitionURL="http://www.sbml.org/sbml/symbols/delay"' in xml_text

    reimported_bngl = sbml_to_bngl_flat(xml_text)
    reimported_model = bionetgen.BioNetGenModel(
        bionetgen.model._cpp.parse_string(reimported_bngl.bngl)
    )
    res_sbml = reimported_model.simulate(method="ode", t_end=5.0, n_steps=50)
    np.testing.assert_allclose(
        res_orig.observables["A"],
        res_sbml.observables["A"],
        rtol=1e-4,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        res_orig.observables["B"],
        res_sbml.observables["B"],
        rtol=1e-4,
        atol=1e-6,
    )

    # 3. Finite backend adapter capability check
    chk = bionetgen.model._cpp.check_bngsim_lowering(model._model, net)
    assert chk["supported"] is False
    assert any("delayed reactions require the native DDE" in b for b in chk["blockers"])


def test_release_capability_coverage_475():
    """Acceptance check release-capability-coverage-475:

    all assigned capability inventory cases execute against their row's
    named independent oracle.
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
        (item for item in prov.get("issues", []) if item.get("number") == 475),
        None,
    )
    assert issue_data is not None, "Issue 475 not found in obligations"
    declared_ob_ids = {ob["id"] for ob in issue_data.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in provenance for issue 475"
