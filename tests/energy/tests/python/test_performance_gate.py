from __future__ import annotations
from pathlib import Path

from scripts import energy_performance_gate as gate


def base():
    return {
        "disabled_median_s": 1.0,
        "nonenergy_median_s": 1.0,
        "energy_reaction_classes": 256,
        "energy_construction_median_s": 8.0,
        "energy_predicates": 8,
    }


def test_good_candidate_passes():
    c = {
        "disabled_median_s": 1.01,
        "nonenergy_median_s": 1.02,
        "energy_reaction_classes": 2,
        "energy_construction_median_s": 1.0,
    }
    r = gate.evaluate(base(), c)
    assert r["passed"]
    assert r["class_reduction"] == 128
    assert r["construction_speedup"] == 8


def test_disabled_regression_fails():
    c = {
        "disabled_median_s": 1.03,
        "nonenergy_median_s": 1.0,
        "energy_reaction_classes": 2,
        "energy_construction_median_s": 1.0,
    }
    assert not gate.evaluate(base(), c)["passed"]


def test_exponential_class_reduction_gate_fails():
    c = {
        "disabled_median_s": 1.0,
        "nonenergy_median_s": 1.0,
        "energy_reaction_classes": 32,
        "energy_construction_median_s": 1.0,
    }
    r = gate.evaluate(base(), c)
    assert not r["passed"]
    assert r["class_reduction"] == 8


def test_small_context_does_not_require_large_context_reduction_thresholds():
    b = base()
    b["energy_predicates"] = 4
    c = {
        "disabled_median_s": 1.0,
        "nonenergy_median_s": 1.0,
        "energy_reaction_classes": 128,
        "energy_construction_median_s": 7.0,
    }
    assert gate.evaluate(b, c)["passed"]


def test_invalid_zero_timing_is_rejected():
    import pytest

    c = {
        "disabled_median_s": 1.0,
        "nonenergy_median_s": 1.0,
        "energy_reaction_classes": 1,
        "energy_construction_median_s": 0.0,
    }
    with pytest.raises(ValueError):
        gate.evaluate(base(), c)
