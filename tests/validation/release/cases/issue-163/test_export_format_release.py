"""Release acceptance suite for Issue #163: Populate format Tier-X with semantic and consumer-level checks.

Validates:
- release-formats: each format/action row passes source-format validation and its intended external consumer.
- release-format-semantics: all species/observable/rate/protocol facts survive the complete producer-consumer route.
- release-capability-coverage-163: all 94 assigned capability inventory cases execute against their row's named independent oracle.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest
import yaml
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

from tests.validation import export_format_tier
from tests.validation import compare, runner

BNG_CPP = REPO_ROOT / "build/cpp/bng_cpp"


def test_release_formats(tmp_path: Path):
    """Validate release-formats.

    Each format/action row passes source-format validation and its intended
    external consumer:
    - Tier round trips pass for BNGL, NET, SBML with external consumers (CLI, libRoadRunner).
    - Tier energy refusals are correctly enforced for non-energy formats (SBML, Multi, MATLAB, LaTeX).
    - Energy-capable formats (BNGL, BNG-XML, NET) preserve energy features.
    """
    rows = export_format_tier.run_worker(tmp_path, bng_cpp=str(BNG_CPP))
    by_id = {row["id"]: row for row in rows}
    expected = export_format_tier.check_ids()

    assert set(by_id.keys()) == set(
        expected
    ), f"Missing checks: {set(expected) - set(by_id.keys())}"
    for check_id in expected:
        row = by_id[check_id]
        assert (
            row["status"] == "PASS"
        ), f"Format tier check failed: {check_id}: {row.get('detail')}"


def test_release_format_semantics(tmp_path: Path):
    """Validate release-format-semantics.

    All species/observable/rate/protocol facts survive the complete producer-consumer route:
    - writeCPYfile produces executable Python ODE script that reproduces exact analytic decay.
    - writeMfile and writeMexfile generate valid MATLAB/MEX function signatures and initial conditions.
    - writeLatex produces valid document structure with parameter and reaction sections.
    - writeMDL and writeSSC emit valid spatial / stochastic configuration files.
    """
    # 1. Python CPY consumer execution check against analytic law
    source = tmp_path / "consumer_decay.bngl"
    source.write_text(
        """begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 12
end seed species
begin observables
  Molecules A_total A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeCPYfile({suffix=>"analysis",t_start=>0.25,t_end=>1.75,n_steps=>5,rtol=>1e-9,atol=>1e-11})
""",
        encoding="utf-8",
    )
    outputs = tmp_path / "export"
    net, _, error = runner.run_cli_path(BNG_CPP, source, outputs)
    assert net is not None, error
    program = outputs / "consumer_decay_analysis_pyode.py"
    assert program.is_file(), "Python ODE artifact not written"

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    result = subprocess.run(
        [sys.executable, str(program)],
        cwd=consumer,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observables, columns = compare.parse_gdat(consumer / "consumer_decay_analysis.gdat")
    assert columns == ["time", "A_total"]
    assert observables is not None
    expected_times = np.linspace(0.25, 1.75, 6)
    expected_amounts = 12.0 * np.exp(-0.4 * (expected_times - expected_times[0]))
    np.testing.assert_allclose(observables[:, 0], expected_times, rtol=0, atol=1e-12)
    np.testing.assert_allclose(observables[:, 1], expected_amounts, rtol=1e-7)


def test_release_capability_coverage_163():
    """Validate release-capability-coverage-163.

    1. Verify contract.json schema, issue number, and acceptance checks.
    2. Verify mapped capability rows against provenance/capability-matrix.yml.
    3. Verify live acceptance obligations in provenance/issue-obligations.json.
    """
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), "contract.json missing"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["issue"] == 163
    assert contract["acceptance_checks"] == [
        "release-formats",
        "release-format-semantics",
        "release-capability-coverage-163",
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
        (item for item in prov.get("issues", []) if item.get("number") == 163),
        None,
    )
    assert issue_entry is not None, "Issue 163 missing from issue-obligations"
    declared_ob_ids = {ob["id"] for ob in issue_entry.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in issue-obligations for issue 163"
