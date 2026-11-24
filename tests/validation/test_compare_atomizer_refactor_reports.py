"""Negative controls for the #164 before/after corpus comparator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "compare_atomizer_refactor_reports",
    ROOT / "scripts/ci/compare_atomizer_refactor_reports.py",
)
comparator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(comparator)

BEFORE = "b" * 40
AFTER = "a" * 40


def _write(
    path: Path,
    *,
    kind: str,
    revision: str,
    records: dict,
    suite="cf38585f",
    corpus="1111111",
    dirty=False,
    partial=False,
    counts=None,
) -> Path:
    if kind == "ssts":
        source = {"bng3_commit": revision, "bng3_tracked_worktree_clean": not dirty}
        document = {
            "schema_version": 1,
            "suite_commit": suite,
            "case_inventory": len(records),
            "source_provenance": source,
            "partial_run": partial,
            "counts": counts or {"failed": 0, "timeout": 0, "invalid-source": 0},
            "records": [
                {"category": "semantic", "id": key, "status": value}
                for key, value in records.items()
            ],
        }
    else:
        document = {
            "schema_version": 1,
            "mode": "flat",
            "corpus_sha256": corpus,
            "partial_run": partial,
            "source": {"revision": revision, "dirty": dirty},
            "counts": counts or {"failed": 0, "timeout": 0},
            "records": [
                {"id": key, "verdict": value} for key, value in records.items()
            ],
        }
    path.write_text(json.dumps(document))
    return path


def _reports(tmp_path, **kwargs):
    specs = kwargs or {}
    results = []
    for name, kind, revision in (
        ("before_ssts", "ssts", BEFORE),
        ("after_ssts", "ssts", AFTER),
        ("before_bm", "biomodels", BEFORE),
        ("after_bm", "biomodels", AFTER),
    ):
        records = specs.get(name, {"case/00001": "passed", "case/00002": "passed"})
        extra = {k: v for k, v in specs.items() if k.startswith(name + "__")}
        extra = {k[len(name) + 2 :]: v for k, v in extra.items()}
        results.append(
            _write(
                tmp_path / f"{name}.json",
                kind=kind,
                revision=revision,
                records=records,
                **extra,
            )
        )
    return results


def test_matching_reports_pass(tmp_path):
    before_ssts, after_ssts, before_bm, after_bm = _reports(tmp_path)
    result = comparator.compare(before_ssts, after_ssts, before_bm, after_bm, AFTER)
    assert result["record_comparison"]["all_match"] is True
    assert result["problems"] == []


def test_missing_case_is_reported(tmp_path):
    specs = {"after_ssts": {"case/00001": "passed"}}
    before_ssts, after_ssts, before_bm, after_bm = _reports(tmp_path, **specs)
    result = comparator.compare(before_ssts, after_ssts, before_bm, after_bm, AFTER)
    assert result["record_comparison"]["all_match"] is False
    assert result["record_comparison"]["missing"]["ssts"] == ["case/00002"]


def test_verdict_regression_is_reported(tmp_path):
    specs = {"after_bm": {"case/00001": "passed", "case/00002": "failed"}}
    before_ssts, after_ssts, before_bm, after_bm = _reports(tmp_path, **specs)
    result = comparator.compare(before_ssts, after_ssts, before_bm, after_bm, AFTER)
    assert result["record_comparison"]["all_match"] is False
    assert "biomodels:case/00002" in result["record_comparison"]["status_changed"]


def test_stale_pin_is_reported(tmp_path):
    specs = {"after_ssts__suite": "old-suite"}
    before_ssts, after_ssts, before_bm, after_bm = _reports(tmp_path, **specs)
    result = comparator.compare(before_ssts, after_ssts, before_bm, after_bm, AFTER)
    assert result["record_comparison"]["all_match"] is False
    assert any("ssts" in problem for problem in result["problems"])


@pytest.mark.parametrize("flag", ["dirty", "partial"])
def test_dirty_or_partial_input_is_reported(tmp_path, flag):
    specs = {f"after_ssts__{flag}": True}
    before_ssts, after_ssts, before_bm, after_bm = _reports(tmp_path, **specs)
    result = comparator.compare(before_ssts, after_ssts, before_bm, after_bm, AFTER)
    assert result["record_comparison"]["all_match"] is False
    assert any(flag in problem for problem in result["problems"])
