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


def _structured_install(
    tmp_path: Path,
    name: str,
    *,
    plat: str,
    kind: str,
    rev: str = REVISION,
    missing_sub: str | None = None,
    gpu_claimed: bool = False,
) -> Path:
    path = tmp_path / f"{name}.json"
    results = [
        {
            "id": sub,
            "status": "PASS",
            "supported_execution": True,
            "evidence_kind": "supported-execution",
        }
        for sub in checks.REQUIRED_INSTALL_SUBCHECKS
        if sub != missing_sub
    ]
    path.write_text(
        json.dumps(
            {
                "check_id": "issue184-install-receipt",
                "source": {"revision": rev, "dirty": False},
                "references": {
                    "platform": plat,
                    "artifact_kind": kind,
                    "artifact_sha256": "a" * 64,
                    "gpu_scope_deferred_to": "#474",
                    "gpu_qualified_by_this_receipt": gpu_claimed,
                },
                "results": results,
            }
        )
    )
    return path


def _candidate_report(
    tmp_path: Path,
    *,
    rev: str = REVISION,
    missing_check: str | None = None,
    diagnostic_only: bool = False,
) -> Path:
    path = tmp_path / "candidate.json"
    rows = [
        {
            "id": cid,
            "status": "PASS",
            "supported_execution": not diagnostic_only,
            "evidence_kind": "supported-execution",
        }
        for cid in checks.REQUIRED_CANDIDATE_CHECKS
        if cid != missing_check
    ]
    path.write_text(
        json.dumps(
            {
                "check_id": "issue184-candidate-evidence",
                "source": {"revision": rev, "dirty": False},
                "references": {},
                "results": rows,
            }
        )
    )
    return path


def test_strict_release_consumer_passes_with_full_evidence(tmp_path):
    sci = [_receipt(tmp_path, "parity"), _receipt(tmp_path, "sbml")]
    cand = [_candidate_report(tmp_path)]
    inst = [
        _structured_install(tmp_path, f"wheel-{p}", plat=p, kind="wheel")
        for p in checks.PLATFORMS
    ] + [_structured_install(tmp_path, "sdist-linux", plat="linux", kind="sdist")]

    s, srej = checks._receipts(sci, REVISION)
    c, crej = checks._receipts(cand, REVISION)
    i, irej = checks._receipts(inst, REVISION)
    assert (
        checks.candidate_gaps(
            s,
            srej,
            candidate_reports=c,
            candidate_rejected=crej,
            require_candidate_checks=True,
        )
        == []
    )
    assert checks.installed_gaps(i, irej, require_structured_install=True) == []


@pytest.mark.parametrize(
    "case",
    [
        "missing-sdist",
        "missing-upgrade-subcheck",
        "dishonest-gpu-claim",
        "missing-sanitizer-candidate-check",
        "diagnostic-only-candidate-check",
    ],
)
def test_strict_release_consumer_fails_closed(tmp_path, case):
    sci = [_receipt(tmp_path, "parity")]
    cand = [
        _candidate_report(
            tmp_path,
            missing_check=(
                "release-candidate:sanitizer-configuration"
                if case == "missing-sanitizer-candidate-check"
                else None
            ),
            diagnostic_only=(case == "diagnostic-only-candidate-check"),
        )
    ]
    inst = [
        _structured_install(
            tmp_path,
            f"wheel-{p}",
            plat=p,
            kind="wheel",
            missing_sub=(
                "upgrade_path"
                if case == "missing-upgrade-subcheck" and p == "linux"
                else None
            ),
            gpu_claimed=(case == "dishonest-gpu-claim" and p == "macos"),
        )
        for p in checks.PLATFORMS
    ]
    if case != "missing-sdist":
        inst.append(
            _structured_install(tmp_path, "sdist-linux", plat="linux", kind="sdist")
        )

    s, srej = checks._receipts(sci, REVISION)
    c, crej = checks._receipts(cand, REVISION)
    i, irej = checks._receipts(inst, REVISION)
    c_gaps = checks.candidate_gaps(
        s,
        srej,
        candidate_reports=c,
        candidate_rejected=crej,
        require_candidate_checks=True,
    )
    i_gaps = checks.installed_gaps(i, irej, require_structured_install=True)
    if case in {"missing-sanitizer-candidate-check", "diagnostic-only-candidate-check"}:
        assert c_gaps
    else:
        assert i_gaps


def _issue142_receipt(
    tmp_path: Path,
    name: str,
    *,
    rev: str = REVISION,
    dirty: bool = False,
    include_source_dict: bool = False,
    source_dict_rev: str | None = None,
    failed_check: bool = False,
) -> Path:
    checks_map = {
        "release-graph-identity": {"status": "PASS"},
        "release-graph-observables": {"status": "FAIL" if failed_check else "PASS"},
        "release-obligation-142": {"status": "PASS"},
    }
    payload: dict = {
        "schema_version": 1,
        "acceptance_check": "release-obligation-142",
        "source_revision": rev,
        "source_dirty": dirty,
        "checks": checks_map,
    }
    if include_source_dict:
        payload["source"] = {"revision": source_dict_rev or rev, "dirty": dirty}
        payload["results"] = [
            {
                "id": cid,
                "status": entry["status"],
                "supported_execution": entry["status"] == "PASS",
                "evidence_kind": "supported-execution",
            }
            for cid, entry in checks_map.items()
        ]
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_consumer_accepts_issue142_receipt_legacy_and_canonical_shapes(tmp_path):
    legacy = _issue142_receipt(tmp_path, "legacy-142", include_source_dict=False)
    canonical = _issue142_receipt(tmp_path, "canonical-142", include_source_dict=True)
    accepted, rejected = checks._receipts([legacy, canonical], REVISION)
    assert rejected == []
    assert len(accepted) == 2
    assert all(not r["failed"] for r in accepted)
    assert "release-obligation-142" in accepted[0]["passed_ids"]
    assert "release-obligation-142" in accepted[1]["passed_ids"]


@pytest.mark.parametrize(
    "case",
    ["stale-rev", "dirty", "conflicting-source", "failed-subcheck"],
)
def test_consumer_rejects_invalid_issue142_receipts(tmp_path, case):
    path = _issue142_receipt(
        tmp_path,
        f"bad-142-{case}",
        rev=("2" * 40) if case == "stale-rev" else REVISION,
        dirty=(case == "dirty"),
        include_source_dict=(case == "conflicting-source"),
        source_dict_rev=("3" * 40) if case == "conflicting-source" else None,
        failed_check=(case == "failed-subcheck"),
    )
    accepted, rejected = checks._receipts([path], REVISION)
    assert checks.candidate_gaps(accepted, rejected)
