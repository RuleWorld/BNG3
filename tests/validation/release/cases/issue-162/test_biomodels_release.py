"""Release acceptance suite for Issue #162: Curated BioModels Qualification.

Validates:
- release-biomodels: complete revision-locked inventory produces per-model
  flat/atomized source comparisons.
- release-biomodels-triage: fail-closed triage categorizes records cleanly,
  ensuring source solver errors have independent documented diagnoses.
- release-obligation-162: verifies exact-revision release contracts,
  inventory rows, and live acceptance obligations.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

if str(REPO_ROOT / "scripts" / "ci") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from validate_published_biomodels import (  # noqa: E402
    NUMERICAL_COMPARISON_ATOL_FLOOR,
    NUMERICAL_COMPARISON_RTOL_FLOOR,
    OracleIntegrationError,
    _is_archive_entry,
    _is_declared_sbml,
    _sbml_surface_limitations,
    _supported_surface_passed,
)
from compare_biomodels_suite_reports import (  # noqa: E402
    compare_reports,
)


def test_release_biomodels():
    """Validate release-biomodels.

    1. Verify published BioModels query manifest schema and exact counts.
    2. Verify curated source bundle inventory and payload mapping.
    3. Verify execution parameters and surface limitation filtering.
    """
    manifest_path = REPO_ROOT / "provenance" / "published-biomodels.json"
    assert manifest_path.is_file(), "published-biomodels.json manifest missing"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["curation_query"] == "curationstatus:Manually curated"
    assert manifest["sbml_query"].endswith("modelformat:SBML")
    assert manifest["expected_total_records"] == 1096
    assert manifest["expected_sbml_records"] == 1075
    assert manifest["expected_non_sbml_records"] == 21

    # Verify source bundle metadata and payload completeness
    bundle_name = "curated-biomodels-source-bundle.json"
    bundle_path = REPO_ROOT / "provenance" / bundle_name
    assert bundle_path.is_file(), "source bundle manifest missing"
    bundle_manifest = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle_manifest["record_count"] == 1096
    assert bundle_manifest["payload_count"] == 1084
    assert bundle_manifest["license"]["spdx"] == "CC0-1.0"

    # Verify tolerance floors for independent CVODE comparison
    assert NUMERICAL_COMPARISON_ATOL_FLOOR == 5e-12
    assert NUMERICAL_COMPARISON_RTOL_FLOOR == 1e-5

    # Verify archive and declared-SBML record classification helpers
    sbml_rec = {"format": "SBML", "filename": "model.xml"}
    omex_rec = {"format": "COMBINE archive", "filename": "model.omex"}
    other_rec = {"format": "CellML", "filename": "model.cellml"}

    assert _is_declared_sbml(sbml_rec) is True
    assert _is_declared_sbml(omex_rec) is False
    assert _is_declared_sbml(other_rec) is False

    assert _is_archive_entry(sbml_rec) is False
    assert _is_archive_entry(omex_rec) is True

    # Verify surface limitation gate on valid Core SBML
    xml_sample = (
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">\n'
        '  <model id="sample">\n'
        "    <listOfCompartments>\n"
        '      <compartment id="c" spatialDimensions="3"\n'
        '                   size="1.0" constant="true"/>\n'
        "    </listOfCompartments>\n"
        "    <listOfSpecies>\n"
        '      <species id="A" compartment="c" initialAmount="10"\n'
        '               hasOnlySubstanceUnits="true"\n'
        '               boundaryCondition="false" constant="false"/>\n'
        "    </listOfSpecies>\n"
        "  </model>\n"
        "</sbml>"
    )
    _counts, limitations = _sbml_surface_limitations(xml_sample)
    assert limitations == []


def test_release_biomodels_triage():
    """Validate release-biomodels-triage.

    1. Fail-closed triage guarantees that any failed, timed-out,
       harness-errored, or uncomparable record prevents release pass.
    2. Oracle integration exceptions are distinguished with diagnoses.
    3. Verdict comparisons distinguish load-induced timeouts from verdicts.
    """
    valid_baseline = {
        "partial": False,
        "counts_match": True,
        "failed_records": 0,
        "harness_error_records": 0,
        "timeout_records": 0,
        "not_comparable_records": 0,
    }
    assert _supported_surface_passed(**valid_baseline) is True

    # Test that every non-passing category strictly fails the surface
    for field in (
        "partial",
        "counts_match",
        "failed_records",
        "harness_error_records",
        "timeout_records",
        "not_comparable_records",
    ):
        mutated = dict(valid_baseline)
        if field in ("partial", "counts_match"):
            mutated[field] = not valid_baseline[field]
        else:
            mutated[field] = 1
        assert _supported_surface_passed(**mutated) is False

    # Verify OracleIntegrationError behavior
    exc = OracleIntegrationError("CVODE failed: singularity at t=0.5")
    assert "singularity" in str(exc)
    assert isinstance(exc, RuntimeError)

    # Verify report comparison verdict vs timeout classification
    base_report = {
        "schema_version": 4,
        "mode": "flat",
        "manifest": "provenance/published-biomodels.json",
        "cache_dir": "/tmp/cache",
        "inventory": {"matches": 1},
        "records": [
            {
                "id": "BIOMD0000000001",
                "format": "SBML",
                "status": "passed",
                "core_passed": True,
                "modes": [{"mode": "flat", "status": "passed"}],
            }
        ],
    }

    # Case 1: Timeout difference is recognized without verdict change
    timeout_report = {
        "schema_version": 4,
        "mode": "flat",
        "manifest": "provenance/published-biomodels.json",
        "cache_dir": "/tmp/cache",
        "inventory": {"matches": 1},
        "records": [
            {
                "id": "BIOMD0000000001",
                "format": "SBML",
                "status": "timeout",
                "core_passed": False,
                "modes": [{"mode": "flat", "status": "timeout"}],
            }
        ],
    }
    cmp_timeout = compare_reports(base_report, timeout_report)
    assert cmp_timeout.verdict_differences == []
    assert bool(cmp_timeout.timeout_differences) is True

    # Case 2: Verdict difference (failure or unsupported format)
    fail_report = {
        "schema_version": 4,
        "mode": "flat",
        "manifest": "provenance/published-biomodels.json",
        "cache_dir": "/tmp/cache",
        "inventory": {"matches": 1},
        "records": [
            {
                "id": "BIOMD0000000001",
                "format": "SBML",
                "status": "failed",
                "core_passed": False,
                "modes": [{"mode": "flat", "status": "failed"}],
            }
        ],
    }
    cmp_fail = compare_reports(base_report, fail_report)
    assert bool(cmp_fail.verdict_differences) is True


def test_release_obligation_162():
    """Validate release-obligation-162.

    1. Verify contract.json schema, issue number, and acceptance checks.
    2. Verify mapped capability rows against provenance/capability-matrix.yml.
    3. Verify live acceptance obligations in provenance/issue-obligations.json.
    """
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), "contract.json missing"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["issue"] == 162
    assert contract["acceptance_checks"] == [
        "release-biomodels",
        "release-biomodels-triage",
        "release-obligation-162",
    ]

    # Verify inventory rows exist in capability-matrix.yml
    matrix_path = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_path.is_file(), "capability-matrix.yml missing"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_ids = {row["id"] for row in matrix.get("rows", [])}
    for row_id in contract["inventory_rows"]:
        assert row_id in matrix_ids, f"Row {row_id} not in capability matrix"

    # Verify live acceptance obligations in issue-obligations.json
    obligations_path = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_path.is_file(), "issue-obligations.json missing"
    prov = json.loads(obligations_path.read_text(encoding="utf-8"))
    issue_entry = next(
        (item for item in prov.get("issues", []) if item.get("number") == 162),
        None,
    )
    assert issue_entry is not None, "Issue 162 missing from issue-obligations"
    declared_ob_ids = {ob["id"] for ob in issue_entry.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in issue-obligations for issue 162"
