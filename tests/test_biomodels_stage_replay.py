"""Bounded BioModels stage-journal replay selection contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts/ci/validate_published_biomodels.py"
COHORT = REPO / "provenance/biomodels-stage-timeout-cohort-40003233859.json"


def _validator():
    spec = importlib.util.spec_from_file_location("stage_replay_validator", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_cohort_selects_only_prior_timeouts_for_requested_mode():
    validator = _validator()
    cohort = validator._load_stage_replay_cohort(
        COHORT,
        inventory_ids=set(json.loads(COHORT.read_text())["models"]),
        mode="flat",
        model_timeout=180,
    )

    assert cohort["partial_run"] is True
    assert cohort["source_run_id"] == "40003233859"
    assert cohort["model_timeout_seconds"] == 180
    assert set(cohort["source_reports_sha256"]) == {"flat", "atomized"}
    assert all(len(digest) == 64 for digest in cohort["source_reports_sha256"].values())
    assert len(cohort["models"]) == 21
    assert all(modes == ["flat"] for modes in cohort["models"].values())
    assert "BIOMD0000000557" not in cohort["models"]
    assert "BIOMD0000000026" not in cohort["models"]


def test_replay_cohort_both_mode_selection_retains_per_mode_statuses():
    validator = _validator()
    raw = json.loads(COHORT.read_text())
    cohort = validator._load_stage_replay_cohort(
        COHORT,
        inventory_ids=set(raw["models"]),
        mode="both",
        model_timeout=180,
    )

    assert len(cohort["models"]) == 23
    assert cohort["models"]["BIOMD0000000557"] == ["atomized"]
    assert cohort["prior_statuses"]["BIOMD0000000557"] == {"atomized": "timeout"}
    assert sum("flat" in modes for modes in cohort["models"].values()) == 21
    assert sum("atomized" in modes for modes in cohort["models"].values()) == 23
    assert sum(map(len, cohort["models"].values())) == 44
    assert cohort["prior_statuses"]["BIOMD0000000579"] == {
        "flat": "timeout",
        "atomized": "timeout",
    }


@pytest.mark.parametrize(
    ("patch", "inventory_ids", "mode", "timeout", "message"),
    [
        ({"kind": "other"}, {"BIOMD0000000579"}, "flat", 180, "kind"),
        ({}, {"BIOMD0000000001"}, "flat", 180, "unknown model"),
        ({}, {"BIOMD0000000579"}, "flat", 120, "timeout"),
        ({}, {"BIOMD0000000579"}, "both", 180, "prior status"),
    ],
)
def test_replay_cohort_rejects_invalid_or_unbounded_selection(
    tmp_path, patch, inventory_ids, mode, timeout, message
):
    validator = _validator()
    raw = json.loads(COHORT.read_text())
    raw.update(patch)
    if patch == {"kind": "other"}:
        raw["models"] = {"BIOMD0000000579": ["flat"]}
        raw["prior_statuses"] = {"BIOMD0000000579": {"flat": "timeout"}}
    elif message == "prior status":
        raw["models"] = {"BIOMD0000000579": ["flat"]}
        raw["prior_statuses"] = {"BIOMD0000000579": {"flat": "passed"}}
    path = tmp_path / "cohort.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError, match=message):
        validator._load_stage_replay_cohort(
            path,
            inventory_ids=inventory_ids,
            mode=mode,
            model_timeout=timeout,
        )
