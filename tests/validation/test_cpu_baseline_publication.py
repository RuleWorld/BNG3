"""Issue #174: the retained CPU baseline must be a publishable artifact."""

from __future__ import annotations

from pathlib import Path

from tests.validation.cpu_baseline_publication import validate, validate_file

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "bench" / "baseline.json"


def test_retained_cpu_baseline_is_publishable():
    assert BASELINE.is_file(), f"missing published baseline: {BASELINE}"
    assert validate_file(BASELINE) == []


def test_checker_rejects_weak_or_uncomparable_baselines():
    import json

    good = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert validate(good) == []

    # Timing without the correctness guard is not a comparable baseline.
    no_guard = json.loads(json.dumps(good))
    del no_guard["guards"]["ssa_events"]
    assert any("ssa_events" in err for err in validate(no_guard))

    # A changed weight set is not comparable to the recorded v2 metric.
    changed_weight = json.loads(json.dumps(good))
    changed_weight["meta"]["weights"]["netgen"] = 0.50
    assert any("weights" in err for err in validate(changed_weight))

    # A non-finite timing is a broken measurement, not a slow one.
    broken = json.loads(json.dumps(good))
    broken["components"]["ode"]["reps"][0] = -1
    assert any("ode.reps" in err for err in validate(broken))
