"""Controls for the #184 CPU-release consumers (not product-support evidence)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cpu_release_checks as checks  # noqa: E402

REVISION = "1" * 40


def _receipt(tmp_path: Path, name: str, *, failed=False, revision=REVISION) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "source": {"revision": revision, "dirty": False},
                "references": {},
                "results": [
                    {
                        "id": f"{name}-check",
                        "status": "FAIL" if failed else "PASS",
                        "supported_execution": True,
                        "evidence_kind": "supported-execution",
                    }
                ],
            }
        )
    )
    return path


def test_package_metadata_is_truthful_about_cpu_and_gpu_scope():
    assert checks.metadata_gaps() == []


def test_consumer_accepts_clean_exact_revision_receipts(tmp_path):
    sci = [_receipt(tmp_path, "parity"), _receipt(tmp_path, "sbml")]
    inst = [_receipt(tmp_path, f"wheel-{p}") for p in checks.PLATFORMS]
    s, rejected = checks._receipts(sci, REVISION)
    i, irejected = checks._receipts(inst, REVISION)
    assert not rejected and not irejected
    assert checks.candidate_gaps(s, rejected) == []
    assert checks.installed_gaps(i, irejected) == []


@pytest.mark.parametrize("mutation", ["failed-result", "stale", "missing-platform"])
def test_consumer_rejects_unqualified_receipts(tmp_path, mutation):
    sci = [_receipt(tmp_path, "parity", failed=(mutation == "failed-result"))]
    if mutation == "stale":
        sci = [_receipt(tmp_path, "parity", revision="2" * 40)]
    inst = [_receipt(tmp_path, f"wheel-{p}") for p in checks.PLATFORMS]
    if mutation == "missing-platform":
        inst = inst[:-1]
    s, rejected = checks._receipts(sci, REVISION)
    i, irejected = checks._receipts(inst, REVISION)
    if mutation in {"failed-result", "stale"}:
        assert checks.candidate_gaps(s, rejected)
    if mutation == "missing-platform":
        assert checks.installed_gaps(i, irejected)


def test_gpu_extra_declaration_is_rejected(tmp_path):
    root = tmp_path / "repo"
    for rel in ("pyproject.toml", "docs/DECISIONS.md", "README.md"):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(checks.ROOT / rel, dest)
    with (root / "pyproject.toml").open("a") as stream:
        stream.write('\ngpu = ["torch"]\n')
    assert checks.metadata_gaps(root)
