from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_manifest_references_existing_unique_fixtures():
    path = ROOT / "fixtures" / "energy" / "validation_manifest.json"
    manifest = json.loads(path.read_text())
    files = [m["file"] for m in manifest["models"]]
    assert len(files) == len(set(files))
    for f in files:
        assert (path.parent / f).is_file(), f


def test_manifest_contains_required_strategy_classes():
    manifest = json.loads(
        (ROOT / "fixtures" / "energy" / "validation_manifest.json").read_text()
    )
    strategies = {m["expected"] for m in manifest["models"]}
    assert "pair_factorized" in strategies
    assert "materialized_fallback" in strategies
    assert "mapping_local_generalized" in strategies
