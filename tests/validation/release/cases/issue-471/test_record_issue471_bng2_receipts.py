"""End-to-end regression and negative controls for #471 BNG2 receipt routing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CASE_DIR = Path(__file__).resolve().parent
ROOT = CASE_DIR.parents[4]
sys.path.insert(0, str(CASE_DIR))
sys.path.insert(0, str(ROOT))

import issue471_checks as checks  # noqa: E402
from scripts.ci import record_issue471_bng2_receipts as recorder  # noqa: E402

ORACLE_NET = (
    "# Created by BioNetGen 2.9.3\n"
    "begin parameters\n"
    "  1 k 0.1\n"
    "end parameters\n"
    "begin species\n"
    "  1 A() 10\n"
    "end species\n"
    "begin reactions\n"
    "  1 1 0 k\n"
    "end reactions\n"
)
CONSUMER_NET = (
    "# Created by bng_cpp\n"
    "begin parameters\n"
    "  1 k 0.1\n"
    "end parameters\n"
    "begin species\n"
    "  1 A() 10\n"
    "end species\n"
    "begin reactions\n"
    "  1 1 0 k\n"
    "end reactions\n"
)
PRODUCER_BNGL = (
    "begin model\n"
    "begin parameters\n"
    "  k 0.1\n"
    "end parameters\n"
    "begin molecule types\n"
    "  A()\n"
    "end molecule types\n"
    "begin seed species\n"
    "  A() 10\n"
    "end seed species\n"
    "begin reaction rules\n"
    "  A() -> 0 k\n"
    "end reaction rules\n"
    "end model\n"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _init_repo(
    repo: Path, files: dict[str, str], *, revision: str | None = None
) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "issue471@example.invalid")
    _git(repo, "config", "user.name", "Issue 471 fixture")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    head = _git(repo, "rev-parse", "HEAD")
    if revision is not None:
        assert head == revision
    return head


def _setup_fixture(tmp_path: Path):
    lock_data = json.loads(
        (ROOT / "provenance/upstreams.lock.yml").read_text(encoding="utf-8")
    )
    bng2_pin = lock_data["sources"]["bionetgen"]["revision"]

    bng2_root = tmp_path / "oracle-bionetgen"
    bng2_pl_text = "# BioNetGen 2.9.3\nprint 'oracle';\n"
    _init_repo(bng2_root, {"bng2/BNG2.pl": bng2_pl_text})
    fake_bng2_rev = _git(bng2_root, "rev-parse", "HEAD")
    # Build run_network as untracked compiled binary inside bng2_root
    run_net = bng2_root / "bng2/bin/run_network"
    run_net.parent.mkdir(parents=True, exist_ok=True)
    run_net.write_bytes(b"fake-run-network")
    lock_data["sources"]["bionetgen"]["revision"] = fake_bng2_rev
    lock_data["oracles"]["bng2"]["build_recipe"] = "macOS arm64"
    import hashlib

    lock_data["oracles"]["bng2"]["artifact_digest"] = (
        "sha256:" + hashlib.sha256(b"fake-run-network").hexdigest()
    )

    repo = tmp_path / "repo"
    matrix_text = (ROOT / "provenance/capability-matrix.yml").read_text(
        encoding="utf-8"
    )
    inv_text = (ROOT / "docs/CAPABILITY_UNION_INVENTORY.md").read_text(encoding="utf-8")
    rev = _init_repo(
        repo,
        {
            "provenance/upstreams.lock.yml": json.dumps(lock_data, indent=2),
            "provenance/capability-matrix.yml": matrix_text,
            "docs/CAPABILITY_UNION_INVENTORY.md": inv_text,
        },
    )

    conf_dir = tmp_path / "bng3-conformance"
    conf_dir.mkdir()
    (conf_dir / "report.json").write_text(
        json.dumps({"source": {"revision": rev, "dirty": False}}),
        encoding="utf-8",
    )
    for model_name in ("egfr_net", "Motivating_example_cBNGL", "localfunc"):
        mdir = conf_dir / "models" / model_name
        for sub in ("input", "reference", "subject"):
            (mdir / sub).mkdir(parents=True)
        (mdir / "input" / f"{model_name}.bngl").write_text(
            PRODUCER_BNGL, encoding="utf-8"
        )
        (mdir / "subject" / f"{model_name}.bngl").write_text(
            PRODUCER_BNGL, encoding="utf-8"
        )
        (mdir / "reference" / f"{model_name}.net").write_text(
            ORACLE_NET, encoding="utf-8"
        )
        (mdir / "subject" / f"{model_name}.net").write_text(
            CONSUMER_NET, encoding="utf-8"
        )
        (mdir / "reference" / "command.json").write_text(
            json.dumps(
                {
                    "command": ["perl", "BNG2.pl", f"{model_name}.bngl"],
                    "status": "PASS",
                    "returncode": 0,
                }
            ),
            encoding="utf-8",
        )
        (mdir / "subject" / "command.json").write_text(
            json.dumps(
                {
                    "command": ["bng_cpp", f"{model_name}.bngl"],
                    "status": "PASS",
                    "returncode": 0,
                }
            ),
            encoding="utf-8",
        )
    return repo, rev, conf_dir, bng2_root, bng2_pin


def test_single_row_and_generalized_bng2_receipts_ground_end_to_end(tmp_path: Path):
    repo, rev, conf_dir, bng2_root, _ = _setup_fixture(tmp_path)

    # 1. Baseline with zero receipts: 0/997 grounded
    empty_receipts = tmp_path / "empty-receipts"
    empty_receipts.mkdir()
    baseline = checks.oracle_independence_report(repo, empty_receipts, rev)
    assert baseline["grounded_execution_rows"] == 0
    assert baseline["result"] == "fail"

    # 2. Single row first (bngl.model-blocks): grounds 1/997
    single_receipts = tmp_path / "single-receipts"
    single_artifacts = tmp_path / "single-artifacts"
    summary_single = recorder.build_bng2_receipts(
        root=repo,
        revision=rev,
        conformance_dir=conf_dir,
        bng2_root=bng2_root,
        receipts_dir=single_receipts,
        artifacts_dir=single_artifacts,
        rows=["bngl.model-blocks"],
    )
    assert summary_single["emitted_rows"] == ["bngl.model-blocks"]
    report_single = checks.oracle_independence_report(
        repo, single_receipts, rev, single_artifacts
    )
    assert report_single["evidence_scope"] == "ARTIFACT_CHECKS_ENABLED"
    assert report_single["grounded_execution_rows"] == 1
    assert report_single["owned_comparisons"][0]["capability_id"] == "bngl.model-blocks"
    assert report_single["owned_comparisons"][0]["consumer_equals_oracle"] is True

    # 3. Generalized sibling set (all 35 mapped implemented bngl.* rows): grounds 35/997
    all_receipts = tmp_path / "all-receipts"
    all_artifacts = tmp_path / "all-artifacts"
    summary_all = recorder.build_bng2_receipts(
        root=repo,
        revision=rev,
        conformance_dir=conf_dir,
        bng2_root=bng2_root,
        receipts_dir=all_receipts,
        artifacts_dir=all_artifacts,
    )
    assert len(summary_all["emitted_rows"]) == 35
    report_all = checks.oracle_independence_report(
        repo, all_receipts, rev, all_artifacts
    )
    assert report_all["grounded_execution_rows"] == 35
    assert report_all["result"] == "fail"  # other 962 rows remain ungrounded


@pytest.mark.parametrize(
    "failure_mode",
    ["stale-revision", "wrong-oracle", "non-independent-oracle", "missing-receipt"],
)
def test_single_row_route_fails_closed_on_tamper_or_missing(
    tmp_path: Path, failure_mode: str
):
    repo, rev, conf_dir, bng2_root, _ = _setup_fixture(tmp_path)
    receipts = tmp_path / "receipts"
    artifacts = tmp_path / "artifacts"
    recorder.build_bng2_receipts(
        root=repo,
        revision=rev,
        conformance_dir=conf_dir,
        bng2_root=bng2_root,
        receipts_dir=receipts,
        artifacts_dir=artifacts,
        rows=["bngl.model-blocks"],
    )
    receipt_path = receipts / "bngl.model-blocks.json"
    data = json.loads(receipt_path.read_text(encoding="utf-8"))

    if failure_mode == "stale-revision":
        check_rev = "0" * 40
        report = checks.oracle_independence_report(repo, receipts, check_rev, artifacts)
        assert report["grounded_execution_rows"] == 0
        assert any("revisions must equal" in f for f in report["findings"])
        return

    if failure_mode == "wrong-oracle":
        data["oracle"]["revision"] = "1" * 40
        receipt_path.write_text(json.dumps(data), encoding="utf-8")
        report = checks.oracle_independence_report(repo, receipts, rev, artifacts)
        assert report["grounded_execution_rows"] == 0
        assert any("oracle revision does not match" in f for f in report["findings"])
        return

    if failure_mode == "non-independent-oracle":
        data["oracle"]["expected_origin"] = "bng3-generated"
        receipt_path.write_text(json.dumps(data), encoding="utf-8")
        report = checks.oracle_independence_report(repo, receipts, rev, artifacts)
        assert report["grounded_execution_rows"] == 0
        assert any("not independently grounded" in f for f in report["findings"])
        return

    receipt_path.unlink()
    report = checks.oracle_independence_report(repo, receipts, rev, artifacts)
    assert report["grounded_execution_rows"] == 0
    assert any(
        "bngl.model-blocks: no exact-revision downstream consumer receipt" in f
        for f in report["findings"]
    )
