"""Negative controls and bounded release gates for issue #471."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert report["evidence_scope"] == "DECLARATION_ONLY"
    assert report["source_status_counts"].get("missing", 0) > 0
    assert report["result"] == "fail"
    assert not any(
        "matrix/inventory ID coverage mismatch" in item for item in report["findings"]
    )
    assert any(
        "no exact-revision downstream consumer receipt" in item
        for item in report["findings"]
    )
    assert any(
        "does not name an external or analytic source" in item
        for item in report["findings"]
    )


BNG2_SOURCE_REVISION = "9601746f8884ed19ab2acea49fe87fc4660ace46"
BNG2_EXECUTABLE_SHA256 = "9f39d22ebdad7aefc38f8ceddf287799f0f262ed0e914b42b1f7cb640a7ffa39"


def _write_upstream_lock(root: Path) -> None:
    lock_path = root / "provenance/upstreams.lock.yml"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": {
                    "bionetgen": {
                        "revision": BNG2_SOURCE_REVISION,
                        "status": "accepted",
                    }
                },
                "oracles": {
                    "bng2": {
                        "source": "bionetgen",
                        "status": "locked",
                        "artifact_digest": f"sha256:{BNG2_EXECUTABLE_SHA256}",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _valid_receipt(row_id: str, revision: str) -> dict:
    oracle_hash = hashlib.sha256(b"expected\n").hexdigest()
    product_hash = hashlib.sha256(b"producer-model\n").hexdigest()
    consumer_hash = hashlib.sha256(b"expected\n").hexdigest()
    return {
        "schema_version": 2,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": row_id,
        "check_id": f"release-capability[{row_id}]",
        "source_revision": revision,
        "product_revision": revision,
        "oracle": {
            "name": "Pinned BNG2 reference",
            "source_id": "bng2",
            "revision": BNG2_SOURCE_REVISION,
            "path": "oracle/expected.txt",
            "artifact_sha256": oracle_hash,
            "command": "BNG2.pl --outdir out case.bngl",
            "executable_sha256": BNG2_EXECUTABLE_SHA256,
            "expected_origin": "external-source",
            "execution": {
                "executable": "BNG2.pl",
                "version": "2.9.3-pinned",
                "command": "BNG2.pl --outdir out case.bngl",
                "exit_code": 0,
            },
        },
        "producer": {"path": "producer/model.bngl", "output_sha256": product_hash},
        "consumer": {
            "path": "consumer/result.txt",
            "output_sha256": consumer_hash,
            "consumed_producer_sha256": product_hash,
            "execution": {
                "executable": "independent-consumer",
                "version": "1.0",
                "command": "independent-consumer producer/model.bngl",
                "exit_code": 0,
            },
        },
    }


def _write_artifacts(root: Path) -> None:
    for rel, content in (
        ("producer/model.bngl", b"producer-model\n"),
        ("oracle/expected.txt", b"expected\n"),
        ("consumer/result.txt", b"expected\n"),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo-root"
    root.mkdir()
    _write_upstream_lock(root)
    return root


def test_oracle_consumer_rejects_unlocked_or_self_generated_receipt(tmp_path: Path):
    row = {"id": "sbml.case", "status": "implemented", "oracle": "pinned BNG2 reference"}
    receipt = _valid_receipt("sbml.case", "a" * 40)
    artifacts = tmp_path / "artifacts"
    _write_artifacts(artifacts)
    root = _minimal_root(tmp_path)
    errors, comparison = checks._oracle_receipt_errors(row, receipt, "a" * 40, artifacts, root)
    assert errors == []
    assert comparison is not None

    receipt["product_revision"] = "b" * 40
    receipt["oracle"]["expected_origin"] = "BNG3-generated"
    receipt["consumer"]["consumed_producer_sha256"] = "3" * 64
    errors, _ = checks._oracle_receipt_errors(row, receipt, "a" * 40, artifacts, root)
    assert any("revisions must equal" in error for error in errors)
    assert any("not independently grounded" in error for error in errors)
    assert any("not bound to the producer bytes" in error for error in errors)
    assert not checks._has_named_oracle(
        "pinned BNG2 reference plus BNG3-generated expected data"
    )


def test_owned_comparator_hashes_artifact_bytes_instead_of_receipt_claims(
    tmp_path: Path,
):
    row = {"id": "sbml.case", "status": "implemented", "oracle": "pinned BNG2 reference"}
    receipt = _valid_receipt("sbml.case", "a" * 40)
    artifacts = tmp_path / "artifacts"
    _write_artifacts(artifacts)
    root = _minimal_root(tmp_path)
    errors, comparison = checks._oracle_receipt_errors(
        row, receipt, "a" * 40, artifacts, root
    )
    assert errors == []
    assert comparison["consumer_equals_oracle"] is True

    # Replacing bytes while retaining receipt SHA values cannot preserve a pass.
    (artifacts / "consumer/result.txt").write_bytes(b"forged pass\n")
    errors, comparison = checks._oracle_receipt_errors(
        row, receipt, "a" * 40, artifacts, root
    )
    assert any("consumer artifact bytes do not match" in error for error in errors)
    assert comparison is None or comparison["consumer_equals_oracle"] is False


def test_artifact_root_rejects_missing_traversal_and_symlink_artifacts(tmp_path: Path):
    root = tmp_path / "artifacts"
    _write_artifacts(root)
    assert checks._artifact_bytes(root, "missing.bin")[1]
    assert checks._artifact_bytes(root, "../outside.bin")[1]
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "escaped.txt").symlink_to(outside)
    assert "symlink" in checks._artifact_bytes(root, "escaped.txt")[1]


def test_verified_output_bytes_are_compared_even_if_receipt_claims_success(
    tmp_path: Path,
):
    row = {"id": "sbml.case", "status": "implemented", "oracle": "pinned BNG2 reference"}
    receipt = _valid_receipt("sbml.case", "a" * 40)
    artifacts = tmp_path / "artifacts"
    _write_artifacts(artifacts)
    root = _minimal_root(tmp_path)
    actual = b"consumer output differs\n"
    (artifacts / "consumer/result.txt").write_bytes(actual)
    receipt["consumer"]["output_sha256"] = hashlib.sha256(actual).hexdigest()
    # No receipt-level result flag is consulted; the owned comparator reads
    # all artifact bytes and detects the real mismatch.
    errors, comparison = checks._oracle_receipt_errors(
        row, receipt, "a" * 40, artifacts, root
    )
    assert any(
        "owned byte comparator found consumer output differs" in error
        for error in errors
    )
    assert comparison is not None and comparison["consumer_equals_oracle"] is False


def test_oracle_consumer_preserves_nonimplemented_inventory_status(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "provenance").mkdir(parents=True)
    (root / "docs").mkdir()
    _write_upstream_lock(root)
    (root / "provenance/capability-matrix.yml").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "sbml.case",
                        "status": "missing",
                        "oracle": "Pinned BNG2 reference",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "docs/CAPABILITY_UNION_INVENTORY.md").write_text(
        "| ID | Behavior |\n|---|---|\n| sbml.case | Example |\n",
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


def test_minimal_consumer_json_without_artifact_bytes_is_declaration_only(
    tmp_path: Path,
):
    root = tmp_path / "repo"
    (root / "provenance").mkdir(parents=True)
    (root / "docs").mkdir()
    _write_upstream_lock(root)
    (root / "provenance/capability-matrix.yml").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "sbml.case",
                        "status": "implemented",
                        "oracle": "Pinned BNG2 reference",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "docs/CAPABILITY_UNION_INVENTORY.md").write_text(
        "| ID | Behavior |\n|---|---|\n| sbml.case | Example |\n",
        encoding="utf-8",
    )
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "sbml.case.json").write_text(
        json.dumps(_valid_receipt("sbml.case", "a" * 40)), encoding="utf-8"
    )
    report = checks.oracle_independence_report(root, receipts, "a" * 40)
    assert report["evidence_scope"] == "DECLARATION_ONLY"
    assert report["grounded_execution_rows"] == 0
    assert any("byte artifacts unavailable" in item for item in report["findings"])


def test_oracle_gate_counts_only_a_consumed_and_byte_compared_artifact_set(
    tmp_path: Path,
):
    root = tmp_path / "repo"
    (root / "provenance").mkdir(parents=True)
    (root / "docs").mkdir()
    _write_upstream_lock(root)
    (root / "provenance/capability-matrix.yml").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "sbml.case",
                        "status": "implemented",
                        "oracle": "Pinned BNG2 reference",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "docs/CAPABILITY_UNION_INVENTORY.md").write_text(
        "| ID | Behavior |\n|---|---|\n| sbml.case | Example |\n",
        encoding="utf-8",
    )
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "sbml.case.json").write_text(
        json.dumps(_valid_receipt("sbml.case", "a" * 40)), encoding="utf-8"
    )
    artifacts = tmp_path / "artifacts"
    _write_artifacts(artifacts)
    report = checks.oracle_independence_report(root, receipts, "a" * 40, artifacts)
    assert report["evidence_scope"] == "ARTIFACT_CHECKS_ENABLED"
    assert report["grounded_execution_rows"] == 1
    assert report["owned_comparisons"][0]["id"] == "release-oracle-byte-equality-v1"
    assert report["result"] == "pass"


def test_oracle_gate_requires_nonempty_matrix_and_independent_inventory_ids(
    tmp_path: Path,
):
    root = tmp_path / "repo"
    matrix = root / "provenance/capability-matrix.yml"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(json.dumps({"rows": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="must not be empty"):
        checks.oracle_independence_report(root, tmp_path / "receipts", "a" * 40)

    matrix.write_text(
        json.dumps(
            {
                "rows": [
                    {"id": "matrix.only", "status": "missing", "oracle": "Pinned BNG2"}
                ]
            }
        ),
        encoding="utf-8",
    )
    docs = root / "docs"
    docs.mkdir()
    (docs / "CAPABILITY_UNION_INVENTORY.md").write_text(
        "| ID | Behavior |\n|---|---|\n| inventory.only | Example |\n",
        encoding="utf-8",
    )
    report = checks.oracle_independence_report(root, tmp_path / "receipts", "a" * 40)
    assert any(
        "matrix/inventory ID coverage mismatch" in item for item in report["findings"]
    )


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
