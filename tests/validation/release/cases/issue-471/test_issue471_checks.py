"""Negative controls and bounded release gates for issue #471."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

CASE_DIR = Path(__file__).parent
ROOT = CASE_DIR.parents[4]
POLICY = ROOT / "tests/validation/policy/antigaming.py"
sys.path.insert(0, str(CASE_DIR))
import issue471_checks as checks  # noqa: E402


def _load_policy():
    spec = importlib.util.spec_from_file_location("issue471_antigaming", POLICY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=root, text=True).strip()


def _git_repo(root: Path, files: dict[str, str]) -> tuple[Path, str]:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "issue471@example.invalid")
    _git(root, "config", "user.name", "Issue 471 fixture")
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root, _git(root, "rev-parse", "HEAD")


def test_oracle_gate_does_not_promote_inventory_declarations_to_execution(
    tmp_path: Path,
):
    receipts = tmp_path / "consumer-receipts"
    receipts.mkdir()
    report = checks.oracle_independence_report(ROOT, receipts, "a" * 40)
    assert report["row_count"] == 994
    assert report["named_oracle_rows"] < 994
    assert report["grounded_execution_rows"] == 0
    assert report["source_status_counts"].get("missing", 0) > 0
    assert report["result"] == "fail"
    assert any(
        "no exact-revision downstream consumer receipt" in item
        for item in report["findings"]
    )
    assert any(
        "does not name an external or analytic source" in item
        for item in report["findings"]
    )


def _valid_receipt(row_id: str, revision: str) -> dict:
    oracle_hash = "1" * 64
    product_hash = "2" * 64
    return {
        "schema_version": 1,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": row_id,
        "check_id": f"release-capability[{row_id}]",
        "source_revision": revision,
        "product_revision": revision,
        "result": "pass",
        "oracle": {
            "name": "Pinned external simulator",
            "revision": "deadbeef",
            "artifact_sha256": oracle_hash,
            "command": "oracle --source case.xml",
            "expected_origin": "external-source",
        },
        "producer": {"output_sha256": product_hash},
        "consumer": {
            "consumed_producer_sha256": product_hash,
            "consumed_oracle_sha256": oracle_hash,
            "comparison": "pass",
        },
    }


def test_oracle_consumer_rejects_unlocked_or_self_generated_receipt():
    row = {"id": "sbml.case", "status": "implemented"}
    receipt = _valid_receipt("sbml.case", "a" * 40)
    assert checks._oracle_receipt_errors(row, receipt, "a" * 40) == []

    receipt["product_revision"] = "b" * 40
    receipt["oracle"]["expected_origin"] = "BNG3-generated"
    receipt["consumer"]["consumed_producer_sha256"] = "3" * 64
    errors = checks._oracle_receipt_errors(row, receipt, "a" * 40)
    assert any("revisions must equal" in error for error in errors)
    assert any("not independently grounded" in error for error in errors)
    assert any("did not identify the producer output" in error for error in errors)
    assert not checks._has_named_oracle(
        "pinned BNG2 reference plus BNG3-generated expected data"
    )


def test_oracle_consumer_preserves_nonimplemented_inventory_status(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "provenance").mkdir(parents=True)
    (root / "provenance/capability-matrix.yml").write_text(
        json.dumps(
            {
                "rows": [
                    {"id": "sbml.case", "status": "missing", "oracle": "Pinned source"}
                ]
            }
        ),
        encoding="utf-8",
    )
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "sbml.case.json").write_text(
        json.dumps(_valid_receipt("sbml.case", "a" * 40)), encoding="utf-8"
    )
    report = checks.oracle_independence_report(root, receipts, "a" * 40)
    assert report["grounded_execution_rows"] == 0
    assert report["result"] == "fail"
    assert any("matrix status is missing" in item for item in report["findings"])


def test_tamper_gate_rejects_product_and_existing_expected_data_in_one_pr(
    tmp_path: Path,
):
    policy = _load_policy()
    root, base = _git_repo(
        tmp_path / "repo",
        {
            "python/bionetgen/runtime.py": "VALUE = 1\n",
            "tests/validation/golden/simple_system.gdat": "time\tA\n0\t1\n",
        },
    )
    (root / "python/bionetgen/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    (root / "tests/validation/golden/simple_system.gdat").write_text(
        "time\tA\n0\t9\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "mixed product and expected output")
    errors = policy.check_protected_changes(root, base)
    assert (
        errors and "product changes mixed with protected acceptance data" in errors[0]
    )


def test_tamper_gate_rejects_fixture_name_in_product_code(tmp_path: Path):
    policy = _load_policy()
    root, base = _git_repo(
        tmp_path / "repo",
        {
            "python/bionetgen/runtime.py": "VALUE = 1\n",
            "tests/fixtures/cycle_fixture.bngl": "begin model\nend model\n",
            "tests/test_contract.py": 'case_id = "case.alpha"\n',
        },
    )
    (root / "python/bionetgen/runtime.py").write_text(
        'FIXTURE = "cycle_fixture"\nVALUE = 1\n', encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "reference test fixture from product")
    errors = policy.check_product_fixture_names(root, base)
    assert errors and "cycle_fixture" in errors[0]


def test_mutation_ratchet_rejects_surviving_known_non_equivalent_mutant(tmp_path: Path):
    policy = _load_policy()
    rows = [{"id": "rate.multiplier", "classification": "non_equivalent"}]
    baseline = {
        "schema": 1,
        "status": "verified",
        "artifact_sha256": "a" * 64,
        "mutants": [{**rows[0], "status": "killed"}],
        "denominator": 1,
        "caught": 1,
    }
    report = {
        "schema": 1,
        "revision": "b" * 40,
        "mutants": [{**rows[0], "status": "survived"}],
        "denominator": 1,
        "caught": 0,
        "status_counts": {
            "killed": 0,
            "survived": 1,
            "invalid": 0,
            "equivalent": 0,
            "infrastructure_error": 0,
        },
        "classification_counts": {"non_equivalent": 1, "equivalent": 0},
    }
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    errors = policy.verify_mutation_ratchet(report_path, baseline_path, "b" * 40)
    assert (
        errors
        and "mutation detection score dropped: 0/1 versus recorded 1/1" in errors[0]
    )


def test_release_ci_topology_keeps_independent_parity_jobs_parallel_and_artifacts(
    tmp_path: Path,
):
    workflow = checks.check_workflow_topology(ROOT / ".github/workflows/parity.yml")
    # The current final obligation receipt upload is success-only. Preserve
    # that concrete topology gap as a finding until the workflow owner wires it.
    assert workflow["result"] == "fail"
    assert any(
        "release-obligation-142: artifact upload does not run after failure" in error
        for error in workflow["errors"]
    )

    mutated = {
        "jobs": {
            "oracle-lock": {"steps": []},
            "oracle-a": {
                "needs": ["oracle-lock"],
                "steps": [{"uses": "actions/upload-artifact@v4", "if": "success()"}],
            },
            "oracle-b": {"needs": ["oracle-lock", "oracle-a"], "steps": []},
        }
    }
    errors = checks.topology_errors(mutated, [["oracle-a", "oracle-b"]])
    assert any("serialized" in error for error in errors)
    assert any("does not run after failure" in error for error in errors)
