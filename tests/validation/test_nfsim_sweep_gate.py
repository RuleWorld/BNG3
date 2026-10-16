"""A trajectory mismatch must remain an ordinary failure with its report intact."""

import json

import pytest

from tests.validation import test_parity_nfsim as sweep


def test_divergence_fails_after_classification(monkeypatch, tmp_path):
    artifact = tmp_path / "sweep.json"
    monkeypatch.setattr(sweep, "SWEEP_ARTIFACT", artifact)
    monkeypatch.setattr(sweep, "TIER_P_MODELS", ["AN"])
    monkeypatch.setattr(sweep, "NF_MODELS", ["AN"])
    record = {
        "model": "AN",
        "direct_status": "accepted",
        "parity_status": "compared",
        "xml_construction_path": "in-memory-xml",
        "construction_path": "direct",
        "direct_unavailable_reason": "",
        "direct_columns": ["R0"],
        "xml_columns": ["R0"],
        "max_rel_err": 1.0,
        "max_rel_col": "R0",
    }
    monkeypatch.setattr(sweep, "_sweep_models", lambda models: [record])
    with pytest.raises(AssertionError, match="diverge from in-memory-XML"):
        sweep.test_tierp_direct_path_outcome_is_measured_and_attributed(None)
    report = json.loads(artifact.read_text())
    assert report["diverged"] == 1
    assert report["records"][0]["outcome"] == "diverged"
