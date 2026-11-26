"""Focused contract tests for the #471/#180 BNGL feature receipt producer."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci import record_issue471_bngl_feature_receipts as mod

ROOT = Path(__file__).resolve().parents[5]


def test_feature_probes_reference_valid_bionetgen_matrix_rows():
    matrix = json.loads(
        (ROOT / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    bng2_ids = {
        str(row["id"])
        for row in matrix.get("rows", [])
        if str(row.get("upstream", "")).startswith("bionetgen:")
    }
    seen: set[str] = set()
    assert len(mod.FEATURE_PROBES) == 60
    for spec in mod.FEATURE_PROBES:
        assert spec.row_id in bng2_ids, f"{spec.row_id} missing from capability matrix"
        assert spec.row_id not in seen, f"duplicate feature probe {spec.row_id}"
        seen.add(spec.row_id)
        assert spec.comparator in {mod._GDAT, mod._NET, mod._HYBRID}
        assert spec.output_file
        assert "begin model" in spec.bngl_text
