"""Positive and negative controls for #471 batch-2 (analytic, CRN, BNGsim) receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

CASE_DIR = Path(__file__).resolve().parent
ROOT = CASE_DIR.parents[4]
sys.path.insert(0, str(CASE_DIR))
sys.path.insert(0, str(ROOT))

import issue471_checks as checks  # noqa: E402
import test_record_issue471_bng2_receipts as base_fixture  # noqa: E402
from scripts.ci import record_issue471_bngsim_receipt as bngsim_rec  # noqa: E402
from scripts.ci import record_issue471_crn_receipt as crn_rec  # noqa: E402


@pytest.mark.parametrize(
    ("oracle_json", "consumer_json", "expect_ok"),
    [
        ('{"kf": 1.0, "kr": 2.0}', '{"kf": 1.0, "kr": 2.0000000001}', True),
        ('{"kf": 1.0, "kr": 2.0}', '{"kf": 1.0, "kr": 2.5}', False),
        ('{"kf": 1.0}', '{"kf": 1.0, "kr": 2.0}', False),
        ('{"kf": true}', '{"kf": true}', False),
        ('{"kf": 1.0}', '{"kf": "1.0"}', False),
    ],
)
def test_numeric_json_comparator_controls(
    oracle_json: str, consumer_json: str, expect_ok: bool
):
    ok, detail = checks._compare_numeric_json_bytes(
        oracle_json.encode("utf-8"), consumer_json.encode("utf-8")
    )
    assert ok is expect_ok, detail


def test_crn_bng2_comparator_controls():
    oracle_net = (
        "begin species\n"
        "  1 A() 10\n"
        "  2 B() 0\n"
        "end species\n"
        "begin reactions\n"
        "  1 1 2 k1 #make\n"
        "end reactions\n"
    ).encode("utf-8")
    valid_crn = json.dumps(
        {
            "species": [{"name": "A()"}, {"name": "B()"}],
            "complexes": [{"species": [0]}, {"species": [1]}],
            "stoichiometric_matrix": [[-1], [1]],
            "reactions": [
                {
                    "reactants": [0],
                    "products": [1],
                    "rate_law": {"rule_name": "make", "expression": "k1"},
                }
            ],
        }
    ).encode("utf-8")
    ok, detail = checks._compare_crn_bng2_bytes(oracle_net, valid_crn)
    assert ok, detail

    tampered = json.loads(valid_crn)
    tampered["stoichiometric_matrix"] = [[1], [-1]]
    ok_bad, _ = checks._compare_crn_bng2_bytes(
        oracle_net, json.dumps(tampered).encode("utf-8")
    )
    assert not ok_bad


def test_analytic_oracle_rejects_spec_digest_tamper_and_missing_law(tmp_path: Path):
    spec = tmp_path / "docs/nonequilibrium_energy.md"
    spec.parent.mkdir(parents=True)
    spec_bytes = b"# Energy spec\n"
    spec.write_bytes(spec_bytes)
    import hashlib

    spec_sha = hashlib.sha256(spec_bytes).hexdigest()
    art = tmp_path / "artifacts"
    (art / "energy.barriers").mkdir(parents=True)
    p_bytes = b"begin model\nend model\n"
    o_bytes = b'{"kf": 0.5}\n'
    c_bytes = b'{"kf": 0.5}\n'
    (art / "energy.barriers/producer.bngl").write_bytes(p_bytes)
    (art / "energy.barriers/oracle.json").write_bytes(o_bytes)
    (art / "energy.barriers/consumer.json").write_bytes(c_bytes)
    row = {
        "id": "energy.barriers",
        "status": "implemented",
        "oracle": "analytic rate ratios and detailed balance",
    }
    rev = "a" * 40
    receipt = {
        "schema_version": 2,
        "kind": "release-oracle-consumer-receipt",
        "capability_id": "energy.barriers",
        "check_id": "release-capability[energy.barriers]",
        "comparator": "release-oracle-numeric-json-v1",
        "source_revision": rev,
        "product_revision": rev,
        "oracle": {
            "name": "Analytic closed-form evaluation",
            "revision": spec_sha,
            "spec_path": "docs/nonequilibrium_energy.md",
            "spec_sha256": spec_sha,
            "law": "k_f = exp(-(Ea+B+phi*dG))",
            "path": "energy.barriers/oracle.json",
            "artifact_sha256": hashlib.sha256(o_bytes).hexdigest(),
            "executable_sha256": "1" * 64,
            "command": "python record_issue471_analytic_receipts.py",
            "expected_origin": "analytic-derivation",
            "execution": {
                "executable": "python",
                "version": "3.12",
                "command": "analytic",
                "exit_code": 0,
            },
        },
        "producer": {
            "path": "energy.barriers/producer.bngl",
            "output_sha256": hashlib.sha256(p_bytes).hexdigest(),
        },
        "consumer": {
            "path": "energy.barriers/consumer.json",
            "output_sha256": hashlib.sha256(c_bytes).hexdigest(),
            "consumed_producer_sha256": hashlib.sha256(p_bytes).hexdigest(),
            "execution": {
                "executable": "cpp",
                "version": "1",
                "command": "cpp",
                "exit_code": 0,
            },
        },
    }
    errors, comp = checks._oracle_receipt_errors(row, receipt, rev, art, tmp_path)
    assert errors == []
    assert comp is not None and comp["consumer_equals_oracle"] is True

    # Tampered spec bytes must fail fail-closed.
    spec.write_bytes(b"# Altered spec\n")
    errors_tamper, _ = checks._oracle_receipt_errors(row, receipt, rev, art, tmp_path)
    assert any("specification bytes" in e for e in errors_tamper)


def test_bngsim_receipt_rejects_mismatched_bngsim_pin(tmp_path: Path):
    repo, rev, _, bng2_root, _ = base_fixture._setup_fixture(tmp_path)
    bngsim_root = tmp_path / "oracle-bngsim"
    bngsim_rev = base_fixture._init_repo(bngsim_root, {"README.md": "bngsim"})
    lock_path = repo / "provenance/upstreams.lock.yml"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_data["sources"]["bngsim"] = {"revision": bngsim_rev, "status": "accepted"}
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
    base_fixture._git(repo, "add", "provenance/upstreams.lock.yml")
    base_fixture._git(repo, "commit", "-qm", "pin mock bngsim")
    rev = base_fixture._git(repo, "rev-parse", "HEAD")

    # Wrong bngsim checkout revision must fail immediately before running anything.
    wrong_bngsim = tmp_path / "wrong-bngsim"
    base_fixture._init_repo(wrong_bngsim, {"README.md": "wrong"})
    with pytest.raises(ValueError, match="pinned bngsim checkout mismatch"):
        bngsim_rec.build_bngsim_receipt(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            bngsim_root=wrong_bngsim,
            receipts_dir=tmp_path / "r",
            artifacts_dir=tmp_path / "a",
        )
    # Also ensure crn_rec rejects dirty tree when allow_dirty=False.
    (repo / "untracked.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match="clean revision"):
        crn_rec.build_crn_receipt(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            receipts_dir=tmp_path / "r2",
            artifacts_dir=tmp_path / "a2",
        )
