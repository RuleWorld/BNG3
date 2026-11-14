"""Release acceptance tests for Issue 159 (Official SBML Conformance)."""

import json
from pathlib import Path
import pytest
import yaml

from scripts.ci import validate_sbml_test_suite as runner
from tests.workflow_yaml import parse_workflow
from stochastic_00003_law import birth_death_moments

_CASE_DIR = Path(__file__).resolve().parent
_REPO = _CASE_DIR.parents[4]


def _load_contract() -> dict:
    contract_path = _CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract file at {contract_path}"
    with open(contract_path, encoding="utf-8") as f:
        return json.load(f)


def _passed_case():
    return {
        "status": "passed",
        "simulation_comparison": {"passed": True},
        "official_conformance": {"status": "passed"},
    }


def test_release_ssts():
    """Verify official SSTS gate contracts and stochastic calibration."""
    # 1. Selected gate accepts executed reference and explicit unsupported
    valid_records = [
        _passed_case(),
        {
            "status": "unsupported",
            "official_conformance": {"status": "unsupported"},
        },
    ]
    assert runner._selected_surface_passed(valid_records)

    # 2. Selected gate rejects official failure even when roundtrip passes
    for bad_status in [
        "failed",
        "timed-out",
        "invalid-source",
        "pending",
        "missing",
    ]:
        case = _passed_case()
        case["official_conformance"]["status"] = bad_status
        assert not runner._selected_surface_passed([case])

    # 3. Selected gate rejects roundtrip failure even when reference passes
    for bad_rt in ["failed", "timeout"]:
        case = _passed_case()
        case["status"] = bad_rt
        assert not runner._selected_surface_passed([case])

    # 4. Selected gate rejects skipped independent comparison
    skipped_case = _passed_case()
    skipped_case["simulation_comparison"] = {"passed": False, "skipped": True}
    assert not runner._selected_surface_passed([skipped_case])

    # 5. Selected gate requires an executed official reference (not empty)
    assert not runner._selected_surface_passed([])
    assert not runner._selected_surface_passed(
        [
            {
                "status": "unsupported",
                "official_conformance": {"status": "unsupported"},
            }
        ]
    )

    # 6. Stochastic case 00003 calibration against exact source law
    check_points = [
        (1.0, 90.48374180359595, 13.44708),
        (41.0, 1.657267541912, 5.85029),
        (50.0, 0.6737946999086565, 3.74891),
    ]
    for t, expected_mean, expected_sd in check_points:
        moments = birth_death_moments(t)
        assert moments.mean == pytest.approx(expected_mean, abs=5e-5)
        assert moments.standard_deviation == pytest.approx(expected_sd, abs=5e-5)
        assert moments.standardized_variance_statistic_factor >= 0.0


def test_release_ssts_coverage():
    """Verify Core inventory row mapping and gate workflow binding."""
    contract = _load_contract()
    declared_rows = set(contract.get("inventory_rows", []))

    # Check against capability matrix
    matrix_path = _REPO / "provenance" / "capability-matrix.yml"
    assert matrix_path.is_file()
    with open(matrix_path, encoding="utf-8") as f:
        matrix = yaml.safe_load(f)
    core_rows = {
        r["id"] for r in matrix.get("rows", []) if r["id"].startswith("sbml.core")
    }
    assert len(core_rows) == 104
    assert core_rows == declared_rows, (
        f"Mismatch between capability matrix and contract: "
        f"missing={core_rows - declared_rows}, "
        f"extra={declared_rows - core_rows}"
    )

    # Check that campaign expectations exist and cover the suite
    expectations_path = _REPO / "provenance" / "sbml-campaign" / "expectations.json"
    assert expectations_path.is_file()
    with open(expectations_path, encoding="utf-8") as f:
        expectations = json.load(f)
    assert expectations["schema_version"] == 1
    assert "suite" in expectations
    expected_rev = "cf38585fac5de8e0e90112febb62851ee2181816"
    assert expectations["suite"]["revision"] == expected_rev
    assert len(expectations["cases"]) >= 1000

    # Check workflow file enforces fail-closed gate
    workflow_path = _REPO / ".github" / "workflows" / "sbml-conformance.yml"
    assert workflow_path.is_file()
    wf = parse_workflow(workflow_path)
    job = wf["jobs"]["conformance"]
    steps = job["steps"]
    run = next(
        step["run"]
        for step in steps
        if step.get("name") == "Run bounded official conformance"
    )
    assert "--gate-selected-cases" in run
    assert "--selection-strategy feature-cover" in run


def test_release_obligation_159():
    """Verify live acceptance obligations for Issue 159 are recorded."""
    contract = _load_contract()
    declared_obligations = set(contract.get("obligations", []))
    expected_obligations = {
        "issue:159:live-acceptance:release-ssts",
        "issue:159:live-acceptance:release-ssts-coverage",
        "issue:159:live-acceptance:release-obligation-159",
    }
    assert declared_obligations == expected_obligations

    # Verify obligations file
    obligations_path = _REPO / "provenance" / "issue-obligations.json"
    assert obligations_path.is_file()
    with open(obligations_path, encoding="utf-8") as f:
        data = json.load(f)

    issue_entry = next(
        (issue for issue in data.get("issues", []) if issue.get("number") == 159),
        None,
    )
    assert issue_entry is not None, "Issue 159 not found in issue-obligations.json"
    recorded_ids = {ob["id"] for ob in issue_entry.get("obligations", [])}
    for ob_id in expected_obligations:
        assert ob_id in recorded_ids, f"Obligation {ob_id} missing from issue 159"
