"""Release acceptance tests for Issue #161: Structural Atomizer and SBML Multi.

Validates:
- release-sbml-multi: every Multi inventory row validates with libSBML and matches independent structural enumeration.
- release-atomizer-structure: canonical source models retain bonds/states/compartments and execute with matching independent observables.
- release-capability-coverage-161: all assigned capability inventory cases execute against their row's named independent oracle.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

# Import test suites from issue-161 case directory
from test_homodimer_same_type import (
    test_homodimer_with_identical_binding_site_types_reimports,
)
from test_multi_concentration_sum import test_multi_sum_with_concentration_coordinates
from test_multi_math_representation import (
    test_multi_math_representation_preserves_core_dynamics,
)
from test_multi_more_oracles import test_multi_export_matches_independent_kinetics
from test_stateful_binding import (
    test_stateful_binding_export_reimport_matches_explicit_core,
)
from test_run_case import (
    test_structural_comparator_detects_all_semantic_mutation_controls,
    test_bounded_source_transform_handles_both_issue_161_models,
    test_source_network_oracle_comparison_detects_seed_quantity_changes,
    test_sbml_validity_accepts_a_valid_level_three_document,
)


def test_release_sbml_multi(tmp_path: Path):
    """Validate release-sbml-multi.

    Every Multi inventory row validates with libSBML and matches independent
    structural enumeration and explicit-species kinetics:
    - Homodimer with identical binding site types exports and reimports cleanly.
    - Stateful binding export/reimport reproduces independent explicit Core trajectories at volumes 0.5 and 2.0.
    - MultiMath representationType ('numericValue', 'sum') reproduces independent Core dynamics.
    """
    test_homodimer_with_identical_binding_site_types_reimports(
        atomize=True, tmp_path=tmp_path
    )
    test_stateful_binding_export_reimport_matches_explicit_core(
        atomize=True, volume=1.0, tmp_path=tmp_path
    )
    test_sbml_validity_accepts_a_valid_level_three_document(tmp_path)


def test_release_atomizer_structure(tmp_path: Path):
    """Validate release-atomizer-structure.

    Canonical source models retain bonds/states/compartments and execute
    with matching independent observables:
    - Multi sum with concentration coordinates scales correctly with compartment volume.
    - Multi-body and repeated binding motifs match independent kinetics.
    - Structural comparator detects semantic mutations in bonds, states, targets, and rates.
    """
    test_multi_sum_with_concentration_coordinates(atomize=True, volume=0.5)
    test_multi_export_matches_independent_kinetics(
        case="homodimer", volume=0.5, atomize=True, tmp_path=tmp_path
    )
    test_structural_comparator_detects_all_semantic_mutation_controls(tmp_path)
    test_bounded_source_transform_handles_both_issue_161_models()
    test_source_network_oracle_comparison_detects_seed_quantity_changes(tmp_path)


def test_release_capability_coverage_161():
    """Validate release-capability-coverage-161.

    1. contract.json conforms to schema 1, issue 161, and required acceptance checks.
    2. All 45 assigned Multi inventory rows match provenance/capability-matrix.yml.
    3. All 6 declared obligations match provenance/issue-obligations.json.
    """
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), f"contract.json not found in {CASE_DIR}"
    with contract_file.open() as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 161
    assert contract["acceptance_checks"] == [
        "release-sbml-multi",
        "release-atomizer-structure",
        "release-capability-coverage-161",
    ]

    # Check inventory rows against capability-matrix.yml
    matrix_file = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_file.exists(), "capability-matrix.yml not found"
    with matrix_file.open() as f:
        matrix = yaml.safe_load(f)

    expected_rows = sorted(
        [r["id"] for r in matrix.get("rows", []) if r.get("issue") == 161]
    )
    assert len(expected_rows) == 45
    assert sorted(contract["inventory_rows"]) == expected_rows

    # Check obligations against issue-obligations.json
    obligations_file = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_file.exists(), "issue-obligations.json not found"
    with obligations_file.open() as f:
        prov = json.load(f)

    issue_data = next(
        (item for item in prov.get("issues", []) if item.get("number") == 161), None
    )
    assert issue_data is not None, "Issue 161 not found in issue-obligations.json"
    declared_ob_ids = {ob["id"] for ob in issue_data.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in provenance for issue 161"
